"""
《海猫鸣泣之时：六轩岛黄昏》地点引擎

地点分组、距离计算、初始位置。
"""

from typing import Dict, List

from .config_loader import ConfigLoader
from .state import GameState


class LocationEngine:
    def __init__(self, game_state: GameState, config: ConfigLoader):
        self.state = game_state
        self.config = config

    def group_by_location(self, roles: List[str]) -> Dict[str, List[str]]:
        """按当前位置对角色分组。"""
        groups: Dict[str, List[str]] = {}
        for role in roles:
            loc = self.state.locations.get(role, "本馆")
            groups.setdefault(loc, []).append(role)
        return groups

    def get_distance(self, a: str, b: str) -> int:
        return self.config.get_distance(a, b)

    def force_move_to(self, roles: List[str], location: str) -> None:
        """强制移动角色到指定地点（不消耗行动点）。"""
        for role in roles:
            if role in self.state.alive_roles:
                self.state.locations[role] = location

    def get_initial_location(self, role: str) -> str:
        return self.config.role_initial_locations.get(role, "本馆")
