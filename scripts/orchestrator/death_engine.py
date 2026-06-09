"""
《海猫鸣泣之时：六轩岛黄昏》死亡引擎

死亡判定、结算分数、角色切换、观剧模式。
"""

import asyncio
from typing import Dict, List, Optional, Tuple

from .config_loader import ConfigLoader
from .network import NetworkLayer
from .process_manager import ProcessManager
from .state import GameState


class DeathEngine:
    def __init__(self, game_state: GameState, process_manager: ProcessManager, network: NetworkLayer, config: Optional[ConfigLoader] = None, log_callback=None):
        self.state = game_state
        self.pm = process_manager
        self.network = network
        self.config = config
        self._log = log_callback

    def _get_death_schedule(self) -> List[Tuple[int, str, str, str]]:
        if self.config:
            raw = self.config.death_schedule
            if raw:
                return [(d["day"], d["phase"], d["role"], d["cause"]) for d in raw]
        return []

    def _get_seat_chains(self) -> Dict[str, List[str]]:
        if self.config:
            return self.config.seat_chains
        return {}

    def check_scheduled_deaths(self, day: int, phase: str) -> List[Tuple[str, str]]:
        deaths = []
        for d, p, role, cause in self._get_death_schedule():
            if d == day and p == phase:
                if role not in self.state.dead_roles:
                    deaths.append((role, cause))
        return deaths

    async def handle_death(self, role_name: str, cause: str) -> None:
        score = self.state.mark_dead(role_name)
        seat_id = None
        for sid, s in self.network.seats.items():
            if s.role_name == role_name and s.alive and sid != "BEATRICE":
                seat_id = sid
                break
        if not seat_id:
            return

        seat = self.network.seats[seat_id]
        is_ai = seat_id in self.state.ai_seats or seat_id.startswith("NPC_")
        print(f"\n[DeathEngine] ☠️ {role_name} ({seat_id}) 死亡: {cause} | 规则得分: {score} | AI={is_ai}\n")
        if self._log:
            self._log("DEATH", f"{role_name} ({seat_id}): {cause} | 规则得分: {score}")

        await self._notify_death(seat, role_name, cause, score)

        if is_ai:
            self.state.mark_eliminated(seat_id)
            self.network.seats.pop(seat_id, None)
            self.pm.terminate(seat_id)
        else:
            await self._switch_role(seat_id)

    async def _notify_death(self, seat, role_name, cause, score):
        await self.network.send_and_drain(seat, {
            "type": "notification",
            "seat_id": seat.seat_id,
            "title": "死亡通知",
            "body": f"你操控的角色 {role_name} 已死亡。{cause}",
            "severity": "error",
        })

    def _collect_role_state(self, role: str) -> dict:
        """收集角色的当前状态，用于角色切换时继承。"""
        return {
            "location": self.state.locations.get(role, "本馆"),
            "action_points": self.state.action_points.get(role, 50),
            "unlocked_info": list(self.state.unlocked_info.get(role, set())),
            "cooldowns": dict(self.state.cooldowns.get(role, {})),
            "sleeping": role in self.state.sleeping,
            "night_owl": role in self.state.night_owl,
            "pending_moves": self.state.pending_moves.get(role, ""),
        }

    async def _switch_role(self, seat_id: str):
        seat = self.network.seats.get(seat_id)
        if not seat:
            return
        chain = self._get_seat_chains().get(seat_id, [])
        current_index = -1
        for i, role in enumerate(chain):
            if role == seat.role_name:
                current_index = i
                break
        next_index = current_index + 1
        while next_index < len(chain):
            new_role = chain[next_index]
            if new_role not in self.state.dead_roles:
                break
            next_index += 1
        else:
            await self._make_spectator(seat_id)
            return

        new_role = chain[next_index]
        print(f"[DeathEngine] {seat_id} 切换角色: {seat.role_name} -> {new_role}")
        if self._log:
            self._log("SWITCH", f"{seat_id}: {seat.role_name} -> {new_role}")

        # 回收NPC（如果新角色由NPC控制）
        old_controller = self.state.role_controller.get(new_role)
        if old_controller and old_controller.startswith("NPC_"):
            # 收集NPC状态 BEFORE 终止
            self.state.inheritance_pool[new_role] = self._collect_role_state(new_role)
            if self._log:
                self._log("SWITCH", f"回收NPC {old_controller}({new_role})，状态已保存到继承池")
            self.pm.terminate(old_controller)
            self.state.role_controller.pop(new_role, None)

        self.state.alive_roles.discard(seat.role_name)
        self.state.alive_roles.add(new_role)
        if new_role not in self.state.action_points:
            self.state.action_points[new_role] = 26
        self.state.record_role_for_seat(seat_id, new_role)
        self.state.role_controller[new_role] = seat_id
        # 清理旧角色的控制映射，避免ghost映射
        self.state.role_controller.pop(seat.role_name, None)

        await self.network.send_and_drain(seat, {
            "type": "notification",
            "seat_id": seat_id,
            "title": "角色切换",
            "body": f"你之前控制的角色 {seat.role_name} 已死亡。现在你接管了 {new_role} 的视角。",
            "severity": "warning",
        })

        seat.alive = False
        try:
            seat.writer.close()
        except Exception:
            pass
        # 从 network.seats 中移除旧对象，避免新进程注册时冲突
        self.network.seats.pop(seat_id, None)
        await asyncio.sleep(1)
        self.pm.start_seat(seat_id, new_role, "auto", "127.0.0.1", 9123)

    async def _make_spectator(self, seat_id: str):
        seat = self.network.seats.get(seat_id)
        if not seat:
            return
        print(f"[DeathEngine] {seat_id} 转为观察者模式")
        if self._log:
            self._log("SWITCH", f"{seat_id} 角色链耗尽，转为观察者模式")
        self.state.mark_spectator(seat_id)
        self.state.mark_eliminated(seat_id)
        await self.network.send_and_drain(seat, {
            "type": "spectator_mode",
            "seat_id": seat_id,
            "title": "观察者模式",
            "body": "你操控的所有角色均已死亡。你进入观察者模式。\n你可以自由移动视角、旁听任何对话，但不能与物体或其他玩家交互，也不参与任何判定。",
            "severity": "info",
        })
