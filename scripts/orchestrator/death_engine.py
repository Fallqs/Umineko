"""
《海猫鸣泣之时：六轩岛黄昏》死亡引擎

死亡判定、结算分数、角色切换、观剧模式。
"""

import asyncio
from typing import Dict, List, Optional, Tuple

from .network import NetworkLayer
from .process_manager import ProcessManager
from .state import GameState

# 预定死亡表: (day, phase, 角色名, 死因)
# phase 使用旧版兼容格式
DEATH_SCHEDULE: List[Tuple[int, str, str, str]] = [
    (2, "TWILIGHT", "右代宫秀吉", "在别馆被发现身亡，胸口有猎枪弹孔"),
    (3, "TWILIGHT", "右代宫朱志香", "在客房内被发现，额头有枪伤"),
    (4, "TWILIGHT", "右代宫让治", "在餐厅中毒身亡"),
    (4, "TWILIGHT", "南条医师", "在书房被发现，死因不明"),
    (5, "TWILIGHT", "右代宫真里亚", "在玫瑰园失踪后被发现身亡"),
    (5, "TWILIGHT", "右代宫夏妃", "在本馆走廊被发现，身上有刀伤"),
    (6, "TWILIGHT", "嘉音", "在别馆厨房被发现，中毒身亡"),
    (6, "TWILIGHT", "纱音", "在客房内被发现，窒息身亡"),
    (6, "TWILIGHT", "右代宫雾江", "在庭院被发现，身上有枪伤"),
    (7, "TWILIGHT", "右代宫藏臼", "在地下密室被发现身亡"),
    (7, "TWILIGHT", "右代宫留弗夫", "在港口被发现，溺亡"),
    (7, "TWILIGHT", "右代宫楼座", "在神社附近被发现身亡"),
    (7, "TWILIGHT", "乡田", "在餐厅被发现，中毒身亡"),
    (7, "TWILIGHT", "熊泽", "在本馆被发现，死因不明"),
]

# 角色链
SEAT_CHAINS: Dict[str, List[str]] = {
    "P1": ["右代宫战人"],
    "P2": ["右代宫朱志香", "右代宫夏妃", "右代宫藏臼"],
    "P3": ["右代宫让治", "右代宫雾江", "右代宫留弗夫"],
    "P4": ["右代宫真里亚", "右代宫楼座"],
    "P5": ["嘉音", "乡田"],
    "P6": ["纱音", "熊泽"],
    "P7": ["右代宫秀吉", "南条医师"],
}

ROLE_DIRS: Dict[str, str] = {
    "右代宫战人": "roles/右代宫战人",
    "右代宫朱志香": "roles/右代宫朱志香",
    "右代宫夏妃": "roles/右代宫夏妃",
    "右代宫藏臼": "roles/右代宫藏臼",
    "右代宫让治": "roles/右代宫让治",
    "右代宫雾江": "roles/右代宫雾江",
    "右代宫留弗夫": "roles/右代宫留弗夫",
    "右代宫真里亚": "roles/右代宫真里亚",
    "右代宫楼座": "roles/右代宫楼座",
    "嘉音": "roles/嘉音",
    "乡田": "roles/乡田",
    "纱音": "roles/纱音",
    "熊泽": "roles/熊泽",
    "右代宫秀吉": "roles/右代宫秀吉",
    "南条医师": "roles/南条医师",
    "贝阿朵莉切": "roles/贝阿朵莉切",
}


class DeathEngine:
    def __init__(self, game_state: GameState, process_manager: ProcessManager, network: NetworkLayer, log_callback=None):
        self.state = game_state
        self.pm = process_manager
        self.network = network
        self._log = log_callback

    def check_scheduled_deaths(self, day: int, phase: str) -> List[Tuple[str, str]]:
        deaths = []
        for d, p, role, cause in DEATH_SCHEDULE:
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
        chain = SEAT_CHAINS.get(seat_id, [])
        current_index = -1
        for i, role in enumerate(chain):
            if role == seat.role_name:
                current_index = i
                break
        next_index = current_index + 1
        if next_index >= len(chain):
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
            self.state.action_points[new_role] = 50
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
