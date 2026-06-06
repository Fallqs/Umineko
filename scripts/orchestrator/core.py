"""
《海猫鸣泣之时：六轩岛黄昏》Orchestrator 外观类

组合所有引擎，协调调用顺序，保持对外接口不变。
"""

import argparse
import asyncio
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

# Windows 控制台编码兼容
if sys.platform == "win32":
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

from .action_engine import ActionEngine, ParsedAction
from .beatrice_engine import BeatriceEngine
from .config_loader import ConfigLoader
from .death_engine import DeathEngine, SEAT_CHAINS
from .location_engine import LocationEngine
from .network import NetworkLayer, SeatConnection
from .npc_engine import NPCEngine
from .process_manager import ProcessManager
from .server import GameServer
from .state import GameState
from .time_engine import TimeEngine
from .token_ring import TokenRingEngine


class Orchestrator:
    """Orchestrator 外观类。对外接口保持兼容。"""

    def __init__(
        self,
        root_dir: Path,
        host: str = "127.0.0.1",
        port: int = 9123,
        mock_mode: bool = False,
        python_exe: str = "python",
        mode: str = "auto",
        min_seats: Optional[int] = None,
        active_seats: Optional[List[str]] = None,
        max_day: int = 7,
        test_mode: bool = False,
        ai_seats: Optional[List[str]] = None,
    ):
        self.root_dir = Path(root_dir).resolve()
        self.host = host
        self.port = port
        self.mock_mode = mock_mode
        self.mode = mode
        self.test_mode = test_mode
        self.active_seats = active_seats or list(SEAT_CHAINS.keys())
        self.min_seats = min_seats or (len(self.active_seats) + 1)
        self.python_exe = python_exe
        self.max_day = max_day

        # 基础设施
        self.config = ConfigLoader(self.root_dir / "config")
        self.state = GameState()
        self.network = NetworkLayer()
        self.server = GameServer(host, port, self.network, msg_handler=self)
        self.pm = ProcessManager(self.root_dir, self._normalize_python_path(python_exe), self.network)

        # 游戏逻辑引擎
        self.time_engine = TimeEngine(self.state, callbacks=self)
        self.location_engine = LocationEngine(self.state, self.config)
        self.token_ring = TokenRingEngine(self.state, self.network, callbacks=self)
        self.action_engine = ActionEngine(self.state, self.config, self.network)
        self.npc_engine = NPCEngine(self.state, self.pm)
        self.death_engine = DeathEngine(self.state, self.pm, self.network, log_callback=self._log_event)
        self.beatrice_engine = BeatriceEngine(self.state, self.network)

        # 运行时状态
        self.narrative_log: List[str] = []
        self.turn_counter = 0
        self._game_start_triggered = False

        # 叙事日志文件
        self._log_file = self.root_dir / "shared" / "logs" / "narrative.log"
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        self._log_file.write_text(f"=== 海猫鸣泣之时：六轩岛黄昏 叙事日志 ===\n启动时间: {datetime.now().isoformat()}\n\n", encoding="utf-8")

        # AI seats
        self.state.ai_seats = set(ai_seats) if ai_seats is not None else (set(self.active_seats) if mode == "auto" else set())

    def _log_event(self, event_type: str, content: str) -> None:
        """记录叙事日志，同时写入文件和内存列表。"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[Day{self.state.day} {self.state.phase}] [{timestamp}] [{event_type}] {content}"
        self.narrative_log.append(entry)
        try:
            with open(self._log_file, "a", encoding="utf-8") as f:
                f.write(entry + "\n")
        except Exception as e:
            print(f"[Orchestrator] 日志写入失败: {e}")
        print(entry)

    @staticmethod
    def _normalize_python_path(path: str) -> str:
        if len(path) >= 3 and path[0] == "/" and path[2] == "/":
            drive = path[1].upper()
            rest = path[3:]
            return f"{drive}:\\{rest.replace('/', '\\')}"
        return path

    # ------------------------------------------------------------------
    # 对外接口（保持不变）
    # ------------------------------------------------------------------

    async def start(self):
        await self.server.start()
        inbox_dir = self.root_dir / "shared" / "inbox"
        self.pm.start_router(inbox_dir)
        self.beatrice_engine.start_worker()
        if not self.mock_mode:
            await self._start_player_seats()
            await asyncio.sleep(0.5)
            self.pm.start_seat("BEATRICE", "贝阿朵莉切", "beatrice", self.host, self.port)
            await asyncio.sleep(0.5)
        # 初始化角色位置
        for role in self.state.alive_roles:
            self.state.locations[role] = self.location_engine.get_initial_location(role)
        # 启动NPC（mock模式下跳过，由测试脚本手动控制）
        if not self.mock_mode:
            self.npc_engine.start_all_npcs(self.host, self.port)

    async def stop(self):
        print("[Orchestrator] Shutting down...")
        self.server.shutdown()
        self.beatrice_engine.stop_worker()
        self.pm.terminate_all()
        await self.server.stop()

    async def serve(self):
        await self.start()
        try:
            await self.server.serve()
        except KeyboardInterrupt:
            print("\n[Orchestrator] Interrupted")
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # 子进程启动
    # ------------------------------------------------------------------

    async def _start_player_seats(self):
        print(f"[Orchestrator] Starting {len(self.active_seats)} active seats + BEATRICE...")
        for seat_id in self.active_seats:
            chain = SEAT_CHAINS.get(seat_id, [])
            if chain:
                role = chain[0]
                self.state.alive_roles.add(role)
                self.state.action_points[role] = 50
                self.state.record_role_for_seat(seat_id, role)
                self.state.role_controller[role] = seat_id
                self.pm.start_seat(seat_id, role, self.mode, self.host, self.port)
                await asyncio.sleep(0.3)

    # ------------------------------------------------------------------
    # MessageHandler 实现
    # ------------------------------------------------------------------

    async def on_register(self, seat: SeatConnection, msg: dict) -> None:
        role = msg.get("role_name", seat.role_name)

        if seat.seat_id == "BEATRICE":
            # BEATRICE特殊注册：不消耗行动点，可自由现身
            if role:
                self.state.role_controller[role] = seat.seat_id
                self.state.alive_roles.add(role)
                self.state.action_points[role] = 999  # 标记为无限
        elif seat.seat_id.startswith("NPC_"):
            # NPC注册：与普通玩家同级
            if role:
                self.state.record_role_for_seat(seat.seat_id, role)
                self.state.role_controller[role] = seat.seat_id
                if role not in self.state.action_points:
                    self.state.action_points[role] = 50
                self.state.alive_roles.add(role)
                # 设置初始位置（如果尚未设置）
                if role not in self.state.locations:
                    self.state.locations[role] = self.location_engine.get_initial_location(role)
        else:
            # 普通玩家seat
            if role:
                self.state.record_role_for_seat(seat.seat_id, role)
                self.state.role_controller[role] = seat.seat_id
                if role not in self.state.action_points:
                    self.state.action_points[role] = 50
                self.state.alive_roles.add(role)

        # 状态继承：如果该角色有待继承状态，发送给新进程并写回GameState
        inherited = self.state.inheritance_pool.pop(role, None)
        if inherited and seat.alive:
            await self.network.send_and_drain(seat, {
                "type": "inherited_state",
                "seat_id": seat.seat_id,
                "role_name": role,
                "state": inherited,
            })
            # 将继承的状态写回GameState（覆盖on_register中的默认值）
            if "location" in inherited:
                self.state.locations[role] = inherited["location"]
            if "action_points" in inherited:
                self.state.action_points[role] = inherited["action_points"]
            if "unlocked_info" in inherited:
                for info_id in inherited["unlocked_info"]:
                    self.state.unlock_info(role, info_id)
            if "cooldowns" in inherited:
                self.state.cooldowns[role] = inherited["cooldowns"]
            if "sleeping" in inherited and inherited["sleeping"]:
                self.state.sleeping.add(role)
            else:
                self.state.sleeping.discard(role)
            if "night_owl" in inherited and inherited["night_owl"]:
                self.state.night_owl.add(role)
            else:
                self.state.night_owl.discard(role)
            if "pending_moves" in inherited and inherited["pending_moves"]:
                self.state.pending_moves[role] = inherited["pending_moves"]
            print(f"[Orchestrator] {seat.seat_id}({role}) 继承了状态: {inherited}")

        # 检查是否满足最小seat数，触发游戏开始
        if not self._game_start_triggered:
            player_seats = [
                s for s in self.network.seats.values()
                if s.seat_id != "BEATRICE" and not s.seat_id.startswith("NPC_")
            ]
            if len(player_seats) >= self.min_seats:
                self._game_start_triggered = True
                print(f"[Orchestrator] 已注册 {len(player_seats)} 个玩家seat，达到最小要求 {self.min_seats}，启动游戏循环")
                asyncio.create_task(self.run_game())

    async def on_action(self, seat: SeatConnection, msg: dict) -> None:
        """收到seat返回的action消息。"""
        self.token_ring.push_action(msg)

    async def on_action_review(self, seat: SeatConnection, msg: dict) -> None:
        """旧版action_review兼容（直接通过BEATRICE复核）。"""
        # 新版中不再通过action_review收集，直接让BEATRICE复核
        pass

    async def on_gm_output(self, seat: SeatConnection, msg: dict) -> None:
        # 旧版兼容
        pass

    async def on_orchestration_request(self, seat: SeatConnection, msg: dict) -> None:
        req = msg.get("request", {})
        result = self._handle_orchestration_request(seat.seat_id, req)
        await self.network.send_and_drain(seat, {
            "type": "notification",
            "seat_id": seat.seat_id,
            "title": "Orchestration 结果",
            "body": result,
            "severity": "info",
        })

    async def on_action_review_result(self, seat: SeatConnection, msg: dict) -> None:
        pass

    async def on_schrodinger_judgment_result(self, seat: SeatConnection, msg: dict) -> None:
        pass

    # ------------------------------------------------------------------
    # TimeCallbacks 实现
    # ------------------------------------------------------------------

    async def on_dawn(self) -> None:
        print("[Orchestrator] ☀️ DAWN: 清晨到来...")
        self._log_event("SYSTEM", f"===== DAWN Day{self.state.day} =====")
        self.state.reset_action_points()
        self.state.sleeping.clear()
        self.state.night_owl.clear()
        for role in self.state.alive_roles:
            self.state.locations[role] = "本馆"
        deaths = self.death_engine.check_scheduled_deaths(self.state.day, self.state.phase)
        if deaths:
            for role, cause in deaths:
                self._log_event("DEATH", f"{role}: {cause}")
            death_text = "\n".join([f"☠️ {r}: {c}" for r, c in deaths])
            await self._broadcast_notification("清晨事件", f"发现了新的死亡：\n{death_text}", severity="error")
        else:
            await self._broadcast_notification("清晨", "新的一天开始了。所有人被自动移动到本馆。", severity="info")
        self._log_event("SYSTEM", f"行动点重置为50，存活: {sorted(self.state.alive_roles)}")
        print(f"[Orchestrator] DAWN 完成，行动点已重置为50")

    async def on_free_slot(self, slot: str) -> None:
        active_roles = [r for r in self.state.alive_roles if r not in self.state.sleeping]
        if not active_roles:
            print(f"[Orchestrator] {slot}: 无活跃角色，跳过")
            self._log_event("SYSTEM", f"{slot}: 无活跃角色，跳过")
            return
        groups = self.location_engine.group_by_location(active_roles)
        locations = list(groups.keys())
        random.shuffle(locations)
        print(f"[Orchestrator] {slot}: 活跃地点 {locations}")
        self._log_event("SYSTEM", f"{slot} 开始，活跃地点: {locations}")
        for loc in locations:
            await self.token_ring.run(loc, groups[loc], slot, rounds=2)
        moves = self.location_engine.resolve_pending_moves()
        for role, frm, to, success in moves:
            status = "成功" if success else "失败"
            print(f"[Orchestrator] 🚶 {role}: {frm} -> {to} ({status})")
            self._log_event("MOVE", f"{role}: {frm} -> {to} ({status})")

    async def on_meal_slot(self, slot: str) -> None:
        meal_name = {"BREAKFAST": "早饭", "LUNCH": "午饭", "DINNER": "晚饭"}.get(slot, slot)
        print(f"[Orchestrator] 🍽️ {slot}: {meal_name}时间，强制回本馆...")
        self._log_event("SYSTEM", f"{slot} {meal_name}时间，强制移动到餐厅")
        for role in self.state.alive_roles:
            if role not in self.state.sleeping:
                self.state.locations[role] = "餐厅"
        active_roles = [r for r in self.state.alive_roles if r not in self.state.sleeping]
        if active_roles:
            await self.token_ring.run("餐厅", active_roles, slot, rounds=1)
        await self._broadcast_notification(f"{meal_name}结束", f"{meal_name}结束了。", severity="info")

    async def on_sleep_check(self) -> None:
        print("[Orchestrator] 🌙 SLEEP_CHECK: 询问是否睡觉...")
        self._log_event("SYSTEM", "SLEEP_CHECK: 选择睡觉或熬夜")
        active_roles = [r for r in self.state.alive_roles if r not in self.state.sleeping]
        for role in active_roles:
            seat_id = self.state.role_controller.get(role)
            if not seat_id:
                continue
            is_ai = seat_id in self.state.ai_seats or seat_id.startswith("NPC_")
            if is_ai:
                self.state.night_owl.add(role)
            else:
                self.state.night_owl.add(role)
        night_owls = sorted(self.state.night_owl)
        if night_owls:
            self._log_event("SYSTEM", f"熬夜角色: {night_owls}")
            await self._broadcast_notification(
                "深夜选择",
                f"以下角色选择继续行动（消耗2倍行动点）：{', '.join(night_owls)}",
                severity="info",
            )

    async def on_midnight(self) -> None:
        print("[Orchestrator] 🌑 MIDNIGHT: 深夜...")
        self._log_event("SYSTEM", f"MIDNIGHT: 第{self.state.day}天结束")
        await self._broadcast_notification(
            "深夜",
            f"第{self.state.day}天结束了。明天将是第{self.state.day + 1}天...",
            severity="info",
        )

    # ------------------------------------------------------------------
    # TokenCallbacks 实现
    # ------------------------------------------------------------------

    async def on_action_received(self, role: str, action_msg: dict, location: str, slot: str) -> None:
        seat_id = self.state.role_controller.get(role)
        seat = self.network.seats.get(seat_id) if seat_id else None
        if not seat:
            return

        action_text = action_msg.get("action_text", "")
        print(f"[Orchestrator] 📨 action from {seat_id}({role}): {action_text[:80]}...")

        parsed = self.action_engine.parse(action_text)

        # 记录完整行动（不截断）
        self._log_event("ACTION", f"{role} (@{location}): {action_text}")

        # 调查
        if parsed.investigate:
            base_cost = 2
            actual_cost = self.state.get_action_point_cost(role, base_cost)
            if self.state.consume_action_point(role, actual_cost):
                info = await self.action_engine.execute_investigate(role, location, seat)
                if info:
                    await self.network.send_and_drain(seat, {
                        "type": "notification", "title": "调查发现", "body": info, "severity": "info"
                    })
                    self._log_event("INVESTIGATE", f"{role} 在{location}: {info}")
            else:
                await self.network.send_and_drain(seat, {
                    "type": "notification", "title": "行动失败", "body": "行动点不足，无法调查。", "severity": "warning"
                })
                self._log_event("ACTION", f"{role} 调查失败（行动点不足）")

        # 发言
        if parsed.speech:
            await self.action_engine.broadcast_speech(role, parsed.speech, location)
            self._log_event("SPEECH", f'{role} (@{location}): "{parsed.speech}"')

        # 移动意向
        next_move = parsed.next_move or action_msg.get("next_move")
        if next_move:
            self.action_engine.handle_move_intent(role, next_move)
            self._log_event("MOVE_INTENT", f"{role} 计划移动到: {next_move}")

        # 决斗
        if parsed.duel_beatrice and role in ("嘉音", "纱音"):
            await self._handle_duel(role, location)

        # 薛定谔检查
        if slot in {"MORNING_1", "MORNING_2", "MORNING_3", "NOON_1", "NOON_2", "NOON_3",
                    "AFTERNOON_1", "AFTERNOON_2", "AFTERNOON_3", "EVENING_1", "EVENING_2", "EVENING_3"}:
            issue = self.beatrice_engine.check_schrodinger(role, location)
            if issue:
                await self._handle_schrodinger(issue)

        self.narrative_log.append(f"Day{self.state.day} {slot} {role}: {action_text[:200]}")

    # ------------------------------------------------------------------
    # 特殊事件
    # ------------------------------------------------------------------

    async def _handle_schrodinger(self, issue: str):
        print(f"[Orchestrator] ⚠️ {issue}")
        self.state.schrodinger_violations.append(issue)
        match = __import__('re').search(r"出现在(.+)$", issue)
        loc = match.group(1) if match else "本馆"
        self.beatrice_engine.teleport_beatrice(loc)
        self._log_event("SCHRODINGER", f"嘉音和纱音同时出现在{loc}，薛定谔崩溃")
        await self._broadcast_notification(
            "薛定谔崩溃",
            f"嘉音和纱音同时出现在{loc}！贝阿朵莉切瞬移至此进行裁决...",
            severity="error",
        )
        victim = await self.beatrice_engine.request_judgment(issue, [])
        if victim in self.state.alive_roles:
            score = self.state.mark_dead(victim)
            self._log_event("SCHRODINGER", f"贝阿朵裁决: {victim} 被抹杀")
            self.narrative_log.append(f"Day{self.state.day} {self.state.phase}: {victim} 因薛定谔崩溃被贝阿朵抹杀")
            await self._broadcast_notification(
                "贝阿朵的裁决",
                f"{victim} 因薛定谔规则崩溃，被贝阿朵莉切从现实中抹杀。",
                severity="error",
            )
            await self.death_engine.handle_death(victim, "薛定谔崩溃，被贝阿朵抹杀")

    async def _handle_duel(self, role: str, location: str):
        other = "纱音" if role == "嘉音" else "嘉音"
        print(f"[Orchestrator] ⚔️ {role} 向贝阿朵发起决斗！{other}将存活...")
        self._log_event("DUEL", f"{role} 向贝阿朵发起决斗，{other}存活")
        await self._broadcast_notification(
            "决斗",
            f"【{role}】向贝阿朵莉切发起了决斗！\n{role} 献出了自己的生命，{other} 得以继续存活。",
            severity="error",
        )
        if role in self.state.alive_roles:
            self.state.mark_dead(role)
            self.narrative_log.append(f"Day{self.state.day} {self.state.phase}: {role} 主动决斗牺牲")
            await self.death_engine.handle_death(role, f"主动向贝阿朵发起决斗，以命换{other}存活")

    # ------------------------------------------------------------------
    # 广播与通知
    # ------------------------------------------------------------------

    async def _broadcast_notification(self, title: str, body: str, severity: str = "info", exclude: Optional[Set[str]] = None):
        exclude = exclude or set()
        targets = set()
        for seat_id, seat in self.network.seats.items():
            if seat.alive and seat_id not in exclude:
                targets.add(seat_id)
        for seat_id in sorted(targets):
            seat = self.network.seats.get(seat_id)
            if seat and seat.alive:
                await self.network.send_and_drain(seat, {
                    "type": "notification",
                    "seat_id": seat_id,
                    "title": title,
                    "body": body,
                    "severity": severity,
                })

    # ------------------------------------------------------------------
    # Orchestration 请求处理（兼容旧版）
    # ------------------------------------------------------------------

    def _handle_orchestration_request(self, seat_id: str, req: dict) -> str:
        action = req.get("action", "")
        params = req.get("params", {})
        role_name = self.network.seats.get(seat_id, SeatConnection(seat_id=seat_id, role_name="", reader=None, writer=None)).role_name

        if action == "spend_action_point":
            target = params.get("target", role_name)
            amount = int(params.get("amount", 1))
            if self.state.consume_action_point(target, amount):
                return f"✅ 已消耗 {target} {amount} 行动点（剩余: {self.state.action_points.get(target, 0)}）"
            return f"❌ {target} 行动点不足"

        elif action == "refund_action_point":
            target = params.get("target", role_name)
            amount = int(params.get("amount", 1))
            self.state.refund_action_point(target, amount)
            return f"🔄 已退还 {target} {amount} 行动点"

        elif action == "mark_dead":
            target = params.get("target_role", "")
            cause = params.get("cause", "")
            if target in self.state.alive_roles:
                self.state.mark_dead(target)
                return f"☠️ {target} 已被标记死亡: {cause}"
            return f"⚠️ {target} 已经死亡或不存在"

        elif action == "unlock_info":
            target = params.get("target_role", "")
            info_id = params.get("info_id", "")
            self.state.unlock_info(target, info_id)
            return f"🔓 {target} 解锁信息: {info_id}"

        elif action == "get_state":
            return self.state.get_summary()

        elif action == "get_score":
            rule_score, gm_score = self.state.calculate_seat_score(seat_id)
            return f"📊 {seat_id} 得分：规则分 {rule_score} | GM主观分 {gm_score} | 总分 {rule_score + gm_score}"

        elif action == "gm_bonus":
            points = int(params.get("points", 0))
            reason = params.get("reason", "")
            self.state.add_gm_bonus(seat_id, points, reason)
            return f"✨ GM主观分：{seat_id} {'+' if points >= 0 else ''}{points} 分"

        return f"⚠️ 未知 orchestration 动作: {action}"

    # ------------------------------------------------------------------
    # 游戏主循环
    # ------------------------------------------------------------------

    async def run_game(self):
        await asyncio.sleep(2)
        await self._broadcast_system_rules()
        await asyncio.sleep(1)
        while self.state.day <= self.max_day:
            if not any(s.alive for s in self.network.seats.values() if s.seat_id != "BEATRICE" and not s.seat_id.startswith("NPC_")):
                print("[Orchestrator] 无存活玩家seat，游戏结束。")
                break
            await self.time_engine.run_day()
            self.state.day += 1
        await self._finalize_game()
        self.server.shutdown()

    async def _broadcast_system_rules(self):
        rules = """【系统公告】欢迎来到《海猫鸣泣之时：六轩岛黄昏》

重要规则：
1. 你的每次行动/发言如果超过 1200 字符，超出部分将被自动截断。
2. 所有涉及规则判定、行动点消耗、信息解锁、死亡判定等操作，均由 orchestrator 统一处理。
3. 开场时，请只描述你当前在做什么、感受到什么、看到什么。
4. 你可以使用工具与其他角色交流，但秘密信息不得随意泄露。

新版行动系统：
- 每天分为多个时间槽（清晨、自由时间、早午晚饭、睡觉选择、深夜）
- 自由时间内，按地点分组，同一地点内令牌环串行行动
- 每个角色每天50行动点，调查消耗2点，移动消耗1-3点
- 发言不消耗行动点
- 晚饭后可选择睡觉或继续行动（熬夜消耗2倍）

计分规则（核心：信息条目）：
- 公开条目：每条 1分
- 半隐藏条目：每条 2分
- 核心隐藏条目：每条 4分

祝各位游戏愉快。"""
        await self._broadcast_notification("系统公告", rules, severity="info")

    async def _finalize_game(self):
        battler_score = self.state.calculate_role_score("右代宫战人")
        if "右代宫战人" in self.state.alive_roles:
            self.state.battler_final_score = battler_score
        lines = ["🏆 游戏结束 — 最终成绩", "", "出局顺序 | Seat | 类型 | 规则分 | GM主观分 | 总分 | 扮演角色链", "-" * 80]
        ordered = list(self.state.elimination_order)
        for seat_id in sorted(self.network.seats.keys()):
            if seat_id == "BEATRICE" or seat_id.startswith("NPC_"):
                continue
            if seat_id not in ordered:
                ordered.append(seat_id)
        for rank, seat_id in enumerate(ordered, 1):
            if seat_id == "BEATRICE" or seat_id.startswith("NPC_"):
                continue
            rule_score, gm_score = self.state.calculate_seat_score(seat_id)
            total = rule_score + gm_score
            history = " -> ".join(self.state.get_role_history(seat_id))
            seat_type = "AI" if seat_id in self.state.ai_seats else "人类"
            eliminated = "✓ 已出局" if seat_id in self.state.elimination_order else "存活至终局"
            lines.append(f"{rank:>3}. {eliminated:<10} | {seat_id:<4} | {seat_type:<4} | {rule_score:>6} | {gm_score:>8} | {total:>5} | {history}")
        summary = "\n".join(lines)
        print("\n" + summary + "\n")
        await self._broadcast_notification("最终成绩", summary, severity="info")
        score_log = self.root_dir / "shared" / "logs" / "final_scores.log"
        score_log.parent.mkdir(parents=True, exist_ok=True)
        try:
            score_log.write_text(summary, encoding="utf-8")
        except Exception as e:
            print(f"[Orchestrator] 写入成绩日志失败: {e}")
