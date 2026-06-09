"""
《海猫鸣泣之时：六轩岛黄昏》剧情任务引擎

在特定阶段为特定角色自动发放任务，检测完成并发放奖励。
"""

import asyncio
from typing import Dict, List, Optional

from .config_loader import ConfigLoader
from .state import GameState


class QuestEngine:
    """任务引擎：管理任务的触发、分配、完成检测和奖励发放。"""

    def __init__(self, state: GameState, config: ConfigLoader, network):
        self.state = state
        self.config = config
        self.network = network

    # ------------------------------------------------------------------
    # 触发与分配
    # ------------------------------------------------------------------

    def check_triggers(self, phase: str, day: int) -> None:
        """在阶段切换时检查是否有任务需要触发。"""
        if not self.config:
            return
        for quest in self.config.quests:
            trigger = quest.get("trigger", {})
            if trigger.get("phase") == phase and trigger.get("day") == day:
                if trigger.get("auto_assign", False):
                    self._assign_quest(quest)

    def _assign_quest(self, quest: dict) -> None:
        """将任务分配给目标角色，发送通知。"""
        target_roles = quest["trigger"].get("target_roles", [])
        if target_roles == "all_alive_except_gm":
            target_roles = [r for r in self.state.alive_roles if r not in ("贝阿朵莉切", "GM")]
        elif not isinstance(target_roles, list):
            target_roles = []

        for role in target_roles:
            if role not in self.state.alive_roles:
                continue
            if role not in self.state.active_quests:
                self.state.active_quests[role] = {}
            quest_id = quest["id"]
            if quest_id in self.state.active_quests[role]:
                continue
            self.state.active_quests[role][quest_id] = {
                "status": "active",
                "assigned_at": (self.state.day, self.state.phase),
                "quest": quest,
            }
            self._notify_quest(role, quest)

    def _notify_quest(self, role: str, quest: dict) -> None:
        """向角色发送任务提示通知。"""
        prompt = quest.get("prompt", "")
        room = self.config.role_rooms.get(role, "未知") if self.config else "未知"
        prompt = prompt.replace("{room}", room)

        seat_id = self.state.role_controller.get(role)
        if not seat_id:
            return
        seat = self.network.seats.get(seat_id)
        if not seat or not seat.alive:
            return
        asyncio.create_task(self.network.send_and_drain(seat, {
            "type": "notification",
            "title": f"【任务】{quest['name']}",
            "body": prompt,
            "severity": "info",
        }))

    # ------------------------------------------------------------------
    # 完成检测
    # ------------------------------------------------------------------

    def check_completion(self, role: str, action_type: str, **kwargs) -> None:
        """检查角色是否完成了当前活跃的任务目标。"""
        quests = self.state.active_quests.get(role, {})
        for quest_id, quest_state in list(quests.items()):
            if quest_state["status"] != "active":
                continue
            quest = quest_state["quest"]
            objective = quest.get("objective", {})
            completed = False

            if objective.get("type") == "move_to" and action_type == "move_to":
                current_loc = self.state.locations.get(role, "")
                target = objective.get("location")
                if not target:
                    # 动态目标：角色的房间
                    target = self.config.role_rooms.get(role) if self.config else None
                if target and current_loc == target:
                    completed = True

            elif objective.get("type") == "broadcast_speech" and action_type == "broadcast_speech":
                speech = kwargs.get("speech", "")
                keywords = objective.get("contains", [])
                if any(kw in speech for kw in keywords):
                    completed = True

            if completed:
                self._complete_quest(role, quest_id)

    def _complete_quest(self, role: str, quest_id: str) -> None:
        """完成任务，发放奖励。"""
        quests = self.state.active_quests.get(role, {})
        if quest_id not in quests:
            return
        quest = quests[quest_id]["quest"]
        reward = quest.get("reward", {})

        points = reward.get("points", 0)
        if points > 0:
            self.state.gm_bonus[role] = self.state.gm_bonus.get(role, 0) + points

        info_id = reward.get("info_id")
        if info_id:
            self.state.unlock_info(role, info_id)

        quests[quest_id]["status"] = "completed"

        seat_id = self.state.role_controller.get(role)
        if seat_id:
            seat = self.network.seats.get(seat_id)
            if seat and seat.alive:
                asyncio.create_task(self.network.send_and_drain(seat, {
                    "type": "notification",
                    "title": "【任务完成】",
                    "body": f"任务「{quest['name']}」已完成！获得 {points} 分。",
                    "severity": "success",
                }))

    # ------------------------------------------------------------------
    # 超时处理
    # ------------------------------------------------------------------

    def check_timeouts(self, phase: str, day: int) -> None:
        """检查在当前阶段超时的任务。"""
        for role, quests in self.state.active_quests.items():
            for quest_id, quest_state in list(quests.items()):
                if quest_state["status"] != "active":
                    continue
                quest = quest_state["quest"]
                timeout = quest.get("timeout", {})
                if timeout.get("phase") == phase and timeout.get("day", day) == day:
                    quests[quest_id]["status"] = "timeout"

    # ------------------------------------------------------------------
    # 提示词生成
    # ------------------------------------------------------------------

    def get_active_quest_prompts(self, role: str) -> List[str]:
        """获取角色当前活跃任务的提示文本列表。"""
        result: List[str] = []
        quests = self.state.active_quests.get(role, {})
        for quest_state in quests.values():
            if quest_state["status"] != "active":
                continue
            quest = quest_state["quest"]
            prompt = quest.get("prompt", "")
            room = self.config.role_rooms.get(role, "未知") if self.config else "未知"
            prompt = prompt.replace("{room}", room)
            result.append(f"{quest['name']}：{prompt}")
        return result
