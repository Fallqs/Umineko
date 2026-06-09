"""
《海猫鸣泣之时：六轩岛黄昏》令牌环引擎

实现"全局行动序列"的核心机制。
"""

import asyncio
import random
from typing import List, Optional, Protocol

from .config_loader import ConfigLoader
from .network import NetworkLayer, SeatConnection
from .state import GameState


class TokenCallbacks(Protocol):
    async def on_action_received(self, role: str, action_msg: dict, slot: str) -> None: ...


class TokenRingEngine:
    def __init__(self, game_state: GameState, network: NetworkLayer, callbacks: TokenCallbacks, config: Optional[ConfigLoader] = None, seat_event_log=None):
        self.state = game_state
        self.network = network
        self.cb = callbacks
        self.config = config
        self.seat_event_log = seat_event_log
        self._action_buffer: List[dict] = []
        self._action_event = asyncio.Event()
        # 限速器：每 turn 最小间隔（秒）。
        # 计算：16角色×120turn/天=1920turn，1auto(2.5次)+15npc(1次)≈2093请求/天
        # 要满足5h/1300次限制，总时长需≥8h，故间隔≥20秒
        self._min_turn_interval = self._get_rule("min_turn_interval", 20.0)
        self._last_turn_time = 0.0

    def _get_rule(self, key: str, default=None):
        if self.config:
            return self.config.get_token_ring_rule(key, default)
        return default

    def _build_situation(self, role: str, slot: str) -> str:
        """根据游戏状态动态生成角色处境描述。"""
        day = self.state.day
        # 区分初始死亡（游戏开始前已死亡）与游戏中死亡
        initial_dead = set(self.config.game_rules.get("initial_dead_roles", []) if self.config else [])
        game_deaths = self.state.dead_roles - initial_dead
        has_game_deaths = bool(game_deaths)
        has_initial_deaths = bool(initial_dead & self.state.dead_roles)
        is_beatrice = role == "贝阿朵莉切"

        if is_beatrice:
            if has_game_deaths:
                return "棋盘上的棋子开始倒下了。他们开始害怕，但还不够——人类的挣扎才刚刚开始有趣。让他们再走近一点真相吧。"
            elif has_initial_deaths:
                return "棋盘上已经缺少了一枚棋子。他们还没发现，但很快就会了。人类的迟钝总是让我发笑。"
            else:
                return "棋盘已经铺好，棋子们还不知道游戏的规则。让他们享受最后的安宁吧。"

        if day == 1 and not has_game_deaths:
            if has_initial_deaths:
                return "你踏上六轩岛，参加家族聚会。天空阴云密布，海风带着咸涩的潮湿。家族的气氛比往常更加紧张——金藏老爷今天没有出现在早餐桌上，管家说他还在休息，但没有人真正见过他。一切看起来只是寻常的不和，但你的直觉告诉你——有什么东西正在暗处注视。"
            else:
                return "你踏上六轩岛，参加家族聚会。天空阴云密布，海风带着咸涩的潮湿。一切看起来只是寻常的不和，但你的直觉告诉你——有什么东西正在暗处注视。"

        if has_game_deaths:
            return "杀戮的漩涡正悄然转动。有人死去，有人将死，你也不例外。你感到血液在耳中轰鸣——请竭力阻止或逃离这场亲人间的屠杀。"

        return "又一天开始了。尸体已经冰冷，但凶手仍在某处呼吸。你能信任谁？你能拯救谁？"

    async def _rate_limit(self):
        """限速：确保 turn_token 发放间隔不低于最小值。"""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_turn_time
        if elapsed < self._min_turn_interval:
            await asyncio.sleep(self._min_turn_interval - elapsed)
        self._last_turn_time = asyncio.get_event_loop().time()

    async def run(self, players: List[str], slot: str, rounds: Optional[int] = None) -> None:
        if not players:
            return
        players = list(players)
        random.shuffle(players)
        # 从配置读取默认值
        if rounds is None:
            if slot in {"BREAKFAST", "LUNCH", "DINNER"}:
                rounds = self._get_rule("meal_slot_rounds", 5)
            else:
                rounds = self._get_rule("free_slot_rounds", 10)
        max_inv = self._get_rule("investigations_per_slot", 2)
        wait_timeout = self._get_rule("wait_timeout", 30.0)
        print(f"[TokenRing] 🌐 全局令牌环开始，玩家: {players}，轮数: {rounds}")

        for round_num in range(1, rounds + 1):
            for role in players:
                if getattr(self.state, "_stop_requested", False) or getattr(self.cb, "_stop_requested", False):
                    print("[TokenRing] 收到停止请求，中断令牌环")
                    return
                if role in self.state.sleeping:
                    continue
                seat_id = self.state.role_controller.get(role)
                if not seat_id:
                    continue
                seat = self.network.seats.get(seat_id)
                if not seat or not seat.alive:
                    continue

                location = self.state.locations.get(role, "本馆")
                nearby = [r for r in players
                          if r != role
                          and self.state.locations.get(r) == location
                          and not self.state.is_hidden(r)]
                ap = self.state.action_points.get(role, 0)
                cost_multiplier = 2 if role in self.state.night_owl else 1
                investigations_remaining = max(0, max_inv - self.state.get_investigations_used(role))

                # 薛定谔隐藏角色：nearby 强制为空（对任何人不可见）
                if self.state.is_schrodinger_hidden(role):
                    nearby = []

                context = self._build_context(role, slot, round_num, rounds, nearby, ap, cost_multiplier, investigations_remaining)
                msg_id = f"turn_d{self.state.day}_{slot}_{seat_id}_r{round_num}"
                # 携带背包信息（供 agent_wrapper 直接展示）
                inventory_ids = self.state.get_container_items(role)
                inventory_names = []
                for iid in inventory_ids:
                    item = self.state.item_registry.get(iid, {})
                    name = item.get("name", iid)
                    if self.state.is_container(iid):
                        state = self.state.container_states.get(iid, "closed")
                        state_desc = "打开" if state == "open" else "关闭"
                        inventory_names.append(f"{name}（{state_desc}）")
                    else:
                        inventory_names.append(name)
                situation = self._build_situation(role, slot)
                msg = {
                    "type": "turn_token",
                    "seat_id": seat_id,
                    "role_name": role,
                    "time_slot": slot,
                    "day": self.state.day,
                    "location": location,
                    "action_points": ap,
                    "token_round": round_num,
                    "token_total_rounds": rounds,
                    "investigations_remaining": investigations_remaining,
                    "nearby_players": nearby,
                    "context": context,
                    "inventory": inventory_names,
                    "situation": situation,
                    "id": msg_id,
                }
                if role in ("嘉音", "纱音"):
                    msg["can_duel_beatrice"] = True

                # 附带 expected_event_count：自该 seat 上次行动以来应收到的 notification 数量
                # agent_wrapper 据此校验是否收到了全量消息
                if self.seat_event_log is not None:
                    expected_count = self.seat_event_log.pop(seat_id, 0)
                    if expected_count:
                        msg["expected_event_count"] = expected_count

                await self._rate_limit()
                print(f"[TokenRing] 🎫 turn_token -> {seat_id}({role}) at {location} round {round_num}/{rounds} (inv_remaining={investigations_remaining})")
                await self.network.send_and_drain(seat, msg)

                action_msg = await self._wait_for_action(seat, msg_id, timeout=wait_timeout)
                if action_msg:
                    await self.cb.on_action_received(role, action_msg, slot)
                else:
                    print(f"[TokenRing] ⏱️ {seat_id}({role}) 未响应，跳过")

        print(f"[TokenRing] 🌐 全局令牌环结束")
        # 推进按回合数计算的 buff 持续时间
        self.state.tick_buff_durations("token_ring_end")

    def _build_context(self, role, slot, round_num, total_rounds, nearby, ap, cost_multiplier, investigations_remaining: int = 2) -> str:
        location = self.state.locations.get(role, "本馆")

        # 薛定谔隐藏角色的宿命感描述
        if self.state.is_schrodinger_hidden(role):
            parts = [
                f"【第{self.state.day}天 - {slot}】",
                f"你在{location}。",
                "一股宿命的力量将你剥离现实，众人的声音仿佛离你远去，你的身躯无法触碰真实。",
                "连你的声音也变得稀薄。",
                f"当前是第 {round_num}/{total_rounds} 轮对话/行动。",
                f"你剩余 {ap} 行动点。",
                f"本时间槽还可进行调查：{investigations_remaining}/2 次。",
            ]
        else:
            parts = [
                f"【第{self.state.day}天 - {slot}】",
                f"你在{location}。",
                f"同场的有：{', '.join(nearby)}。" if nearby else "这里只有你一个人。",
                f"当前是第 {round_num}/{total_rounds} 轮对话/行动。",
                f"你剩余 {ap} 行动点。",
                f"本时间槽还可进行调查：{investigations_remaining}/2 次。",
            ]
        if cost_multiplier > 1:
            parts.append("【熬夜惩罚】你的所有行动消耗变为2倍！")

        # 背包信息
        inventory = self.state.get_container_items(role)
        if inventory:
            item_descs = []
            for iid in inventory:
                item = self.state.item_registry.get(iid, {})
                name = item.get("name", iid)
                if self.state.is_container(iid):
                    state = self.state.container_states.get(iid, "closed")
                    state_desc = "打开" if state == "open" else "关闭"
                    item_descs.append(f"{name}（{state_desc}）")
                else:
                    item_descs.append(name)
            parts.append(f"你携带的物品：{', '.join(item_descs)}")
        else:
            parts.append("你的背包是空的。")

        # 地点可见物品
        visible_item_descs = []
        for item_id, loc in self.state.item_locations.items():
            if loc != f"map:{location}":
                continue
            if self.state.get_effective_visibility(item_id) != "visible":
                continue
            item = self.state.item_registry.get(item_id, {})
            name = item.get("name", item_id)
            if self.state.is_container(item_id) and self.state.container_states.get(item_id) == "open":
                inner = self.state.get_container_items(item_id)
                inner_names = [self.state.item_registry.get(iid, {}).get("name", iid) for iid in inner]
                if inner_names:
                    visible_item_descs.append(f"{name}（内有：{', '.join(inner_names)}）")
                else:
                    visible_item_descs.append(name)
            else:
                visible_item_descs.append(name)
        if visible_item_descs:
            parts.append(f"你注意到这里有：{', '.join(visible_item_descs)}")
        else:
            parts.append("这里没有引人注目的物品。")

        # 贝阿朵莉切（GM角色）专属上下文
        if role == "贝阿朵莉切":
            parts.append("")
            parts.append("你是六轩岛棋盘的主宰者，一切尽在掌握。你不需要调查——你早已知晓一切。")
            parts.append("你的选择：")
            parts.append("1. 观察（默默注视棋子们的行动，保持沉默）")
            parts.append("2. 暗示/引导（通过谜语或红字，将某个角色引向特定方向）")
            parts.append("3. 命令棋子（给某个NPC下达秘密指令，推动杀人诡计）")
            parts.append("4. 执行诡计（布置或触发某个杀人机关）")
            parts.append("")
            parts.append("【输出格式要求】")
            parts.append("请用简洁的自然语言描述你的行动（150字以内）。")
            parts.append("保持魔女的傲慢与神秘感。不需要解释动机。")
            parts.append('3. 如有移动意图，在末尾声明："下轮移动：{地点名}"')
            return "\n".join(parts)

        # 动态构建可用行动列表
        parts.append("")
        parts.append("你可以选择：")
        action_lines = self.state.build_available_actions(role, investigations_remaining, nearby)
        parts.extend(action_lines)

        # 全局 whisper 提示（所有角色）
        parts.append("- 在发言中使用 <whisper>内容</whisper> 标签，可以发出只有自己能听见的声音……或许某人也能听见哦")

        # 嘉音/纱音专属：切换/现身可用性提示
        if role in ("嘉音", "纱音"):
            # 检查地点中是否仅有嘉音+纱音两人
            loc_roles = [r for r in self.state.alive_roles if self.state.locations.get(r) == location]
            others = [r for r in loc_roles if r not in ("嘉音", "纱音")]
            if not others:
                parts.append("- 切换隐藏（消耗2行动点）")
                parts.append("- 现身（不消耗行动点）")
            else:
                if role == "嘉音":
                    parts.append("- 切换隐藏（不可用）：命运般的力量阻止了你的行动，你意识到你的力量尚不足以与之抗衡")
                    parts.append("- 现身（不可用）：命运般的力量阻止了你的行动，你意识到你的力量尚不足以与之抗衡")
                else:
                    parts.append("- 切换隐藏（不可用）：命运般的力量阻止了你的行动，规则的约束无法逾越")
                    parts.append("- 现身（不可用）：命运般的力量阻止了你的行动，规则的约束无法逾越")

        # 通用行动（从 game_rules.json 读取，所有角色可用）
        if self.config:
            for action_def in self.config.game_rules.get("universal_actions", []):
                action_name = action_def.get("name", action_def.get("id", ""))
                base_cost = action_def.get("ap_cost", 0)
                actual_cost = self.state.get_action_point_cost(role, base_cost)
                target_type = action_def.get("target_type", "none")
                target_desc = ""
                if target_type == "role":
                    target_desc = f"（目标：{'/'.join(nearby) if nearby else '无'}）"
                parts.append(f"【通用】{action_name}（消耗{actual_cost}点）{target_desc}")

        # 角色专属行动（从 game_rules.json 读取）
        if self.config:
            role_actions = self.config.game_rules.get("role_granted_actions", {}).get(role, [])
            for action_def in role_actions:
                action_name = action_def.get("name", action_def.get("id", ""))
                base_cost = action_def.get("ap_cost", 0)
                actual_cost = self.state.get_action_point_cost(role, base_cost)
                parts.append(f"【专属】{action_name}（消耗{actual_cost}点）")

        parts.append("")
        parts.append("【重要：输出格式要求】")
        parts.append("请用简洁的自然语言描述你的行动（200字以内），不要写小说式的心理描写、环境渲染或长篇对话。")
        parts.append("【规则】每回合你只能选择 [一个] 行动选项执行，不能组合。")
        parts.append("  - 调查、验尸、移动、使用物品、上锁/解锁/破门、专属行动——这些是互斥的，一次只能选其一。")
        parts.append("  - 发言可以与行动同时出现（免费，不消耗行动点），但行动本身只能有一个。")
        parts.append("  - 如果你既想调查又想移动，请分两次行动：本轮移动，下轮调查。")
        parts.append("【钥匙机制】部分房间（如书房）的门可能上锁，需要对应钥匙才能进入。")
        parts.append("  - 钥匙是特殊物品，可在地点内自动拾取，或通过剧情获得。")
        parts.append("  - 持有钥匙的角色可以在门外解锁后进入，或在门内上锁。")
        parts.append("  - 斧头可以永久破坏门锁（无需钥匙），但会发出巨大声响。")
        parts.append("你的输出应只包含：")
        parts.append("1. 你做的那 [一个] 行动（调查、移动、使用物品、验尸等）")
        parts.append("2. 如有发言，直接写出说的话，通常你的发言能被在场所有人听到")
        parts.append('ps: 如果你选择移动，直接写："移动：{地点名}"（移动会立即生效，本回合不能再做其他事）')
        parts.append("")
        parts.append("示例：")
        parts.append('"我调查了书桌抽屉，发现了一盘录音带。"')
        parts.append('"纱音，你昨晚睡得好吗？"')
        parts.append('"移动：书房"')
        return "\n".join(parts)

    async def _wait_for_action(self, seat: SeatConnection, parent_id: str, timeout: float = 180.0) -> Optional[dict]:
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                await asyncio.wait_for(self._action_event.wait(), timeout=min(remaining, 1.0))
                self._action_event.clear()
                for action in list(self._action_buffer):
                    if action.get("parent_id") == parent_id or action.get("seat_id") == seat.seat_id:
                        self._action_buffer.remove(action)
                        return action
            except asyncio.TimeoutError:
                continue
        return None

    def push_action(self, action_msg: dict) -> None:
        """由Server层调用，将收到的action消息加入缓冲区。"""
        self._action_buffer.append(action_msg)
        self._action_event.set()
