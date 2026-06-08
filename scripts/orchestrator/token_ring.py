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
        # 限速器：每 turn 最小间隔（秒），默认 5 秒
        self._min_turn_interval = self._get_rule("min_turn_interval", 5.0)
        self._last_turn_time = 0.0

    def _get_rule(self, key: str, default=None):
        if self.config:
            return self.config.get_token_ring_rule(key, default)
        return default

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

        # 动态构建可用行动列表
        parts.append("")
        parts.append("你可以选择：")
        action_lines = self.state.build_available_actions(role, investigations_remaining, nearby)
        parts.extend(action_lines)

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
        parts.append("你的输出应只包含：")
        parts.append("1. 你做了什么（调查、移动、使用物品等）")
        parts.append("2. 如有发言，直接写出说的话（控制在2-3句以内）")
        parts.append('3. 如有移动意图，在末尾声明："下轮移动：{地点名}"')
        parts.append("")
        parts.append("示例：")
        parts.append('"我调查了书桌抽屉，发现了一盘录音带。下轮移动：书房"')
        parts.append('"纱音，你昨晚睡得好吗？下轮移动：餐厅"')
        parts.append('"我走向中庭花园，看看玫瑰开得怎样。"')
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
