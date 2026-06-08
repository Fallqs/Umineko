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

    def bind_schrodinger_move(self, role: str, location: str) -> None:
        """移动角色，若角色为嘉音/纱音则同步另一人位置。"""
        if role in ("嘉音", "纱音"):
            self.state.bind_schrodinger_location(role, location)
        else:
            self.state.locations[role] = location

    def init_schrodinger_shared_inventory(self) -> None:
        """初始化嘉音与纱音的共享背包（指针指向同一 set 实例）。"""
        if "嘉音" not in self.state.containers:
            self.state.containers["嘉音"] = set()
        if "纱音" not in self.state.containers:
            self.state.containers["纱音"] = self.state.containers["嘉音"]
        # 若因历史原因指向不同集合，强制统一
        if self.state.containers["嘉音"] is not self.state.containers["纱音"]:
            unified = self.state.containers["嘉音"] | self.state.containers["纱音"]
            self.state.containers["嘉音"] = unified
            self.state.containers["纱音"] = unified
