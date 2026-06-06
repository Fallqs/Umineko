"""
《海猫鸣泣之时：六轩岛黄昏》地点引擎

地点分组、距离计算、移动结算。
"""

from typing import Dict, List, Tuple

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

    def resolve_pending_moves(self) -> List[Tuple[str, str, str, bool]]:
        """结算 pending_moves，返回 (role, from, to, success) 列表。"""
        results = []
        if not self.state.pending_moves:
            return results
        moves = dict(self.state.pending_moves)
        self.state.pending_moves.clear()
        for role, target in moves.items():
            if role not in self.state.alive_roles:
                continue
            current = self.state.locations.get(role, "本馆")
            if current == target:
                continue
            dist = self.get_distance(current, target)
            actual_cost = self.state.get_action_point_cost(role, dist)
            if self.state.consume_action_point(role, actual_cost):
                self.state.locations[role] = target
                results.append((role, current, target, True))
            else:
                results.append((role, current, target, False))
        return results

    def force_move_to(self, roles: List[str], location: str) -> None:
        """强制移动角色到指定地点（不消耗行动点）。"""
        for role in roles:
            if role in self.state.alive_roles:
                self.state.locations[role] = location

    def get_initial_location(self, role: str) -> str:
        return self.config.role_initial_locations.get(role, "本馆")
