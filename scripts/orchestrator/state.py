"""
《海猫鸣泣之时：六轩岛黄昏》游戏状态层

纯数据层，不依赖任何其他模块。
所有游戏状态集中管理，作为共享上下文被各引擎持有引用。
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# 信息条目分值规则
INFO_POINTS = {"P-": 1, "S-": 2, "C-": 4}


def get_info_points(info_id: str) -> int:
    for prefix, points in INFO_POINTS.items():
        if info_id.startswith(prefix):
            return points
    return 0


@dataclass
class GameState:
    """全局游戏状态。所有方法只操作自身字段，不触发网络 IO。"""

    day: int = 1
    phase: str = "DAWN"
    phase_index: int = 0

    alive_roles: Set[str] = field(default_factory=set)
    dead_roles: Set[str] = field(default_factory=set)

    # 行动点系统：每个角色每天50点
    action_points: Dict[str, int] = field(default_factory=dict)
    cooldowns: Dict[str, Dict[str, int]] = field(default_factory=dict)

    # 位置系统
    locations: Dict[str, str] = field(default_factory=dict)
    pending_moves: Dict[str, str] = field(default_factory=dict)
    beatrice_location: Optional[str] = None

    # 信息解锁
    unlocked_info: Dict[str, Set[str]] = field(default_factory=dict)

    # 角色控制映射：role_name -> seat_id（"P1" 或 "NPC_xxx"）
    role_controller: Dict[str, str] = field(default_factory=dict)

    # 睡觉/熬夜
    sleeping: Set[str] = field(default_factory=set)
    night_owl: Set[str] = field(default_factory=set)

    # 薛定谔规则
    schrodinger_violations: List[str] = field(default_factory=list)

    # 死亡与计分
    death_order: List[str] = field(default_factory=list)
    settled_role_scores: Dict[str, int] = field(default_factory=dict)
    battler_final_score: Optional[int] = None
    gm_bonus: Dict[str, int] = field(default_factory=dict)

    # Seat 历史
    seat_role_history: Dict[str, List[str]] = field(default_factory=dict)
    elimination_order: List[str] = field(default_factory=list)
    spectator_seats: Set[str] = field(default_factory=set)
    ai_seats: Set[str] = field(default_factory=set)

    # 状态继承池：角色名 → 待继承状态（角色切换时使用）
    inheritance_pool: Dict[str, dict] = field(default_factory=dict)

    # 贝阿朵
    beatrice_actions: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # 行动点操作
    # ------------------------------------------------------------------

    def consume_action_point(self, role: str, cost: int = 1) -> bool:
        current = self.action_points.get(role, 50)
        if current >= cost:
            self.action_points[role] = current - cost
            return True
        return False

    def refund_action_point(self, role: str, cost: int = 1):
        current = self.action_points.get(role, 0)
        self.action_points[role] = current + cost

    def reset_action_points(self):
        for role in self.alive_roles:
            self.action_points[role] = 50

    def get_action_point_cost(self, role: str, base_cost: int) -> int:
        return base_cost * 2 if role in self.night_owl else base_cost

    # ------------------------------------------------------------------
    # 冷却
    # ------------------------------------------------------------------

    def check_cooldown(self, role: str, ability: str) -> bool:
        cd = self.cooldowns.get(role, {}).get(ability, 0)
        return self.day >= cd

    def set_cooldown(self, role: str, ability: str, days: int):
        if role not in self.cooldowns:
            self.cooldowns[role] = {}
        self.cooldowns[role][ability] = self.day + days

    # ------------------------------------------------------------------
    # 死亡
    # ------------------------------------------------------------------

    def is_role_alive(self, role: str) -> bool:
        return role in self.alive_roles and role not in self.dead_roles

    def mark_dead(self, role: str) -> int:
        if role in self.dead_roles:
            return self.settled_role_scores.get(role, 0)
        self.dead_roles.add(role)
        self.alive_roles.discard(role)
        self.death_order.append(role)
        self.action_points.pop(role, None)
        self.sleeping.discard(role)
        self.night_owl.discard(role)
        score = self.calculate_role_score(role)
        self.settled_role_scores[role] = score
        return score

    # ------------------------------------------------------------------
    # 信息
    # ------------------------------------------------------------------

    def unlock_info(self, role: str, info_id: str):
        if role not in self.unlocked_info:
            self.unlocked_info[role] = set()
        self.unlocked_info[role].add(info_id)

    def calculate_role_score(self, role: str) -> int:
        return sum(get_info_points(iid) for iid in self.unlocked_info.get(role, set()))

    def calculate_seat_score(self, seat_id: str) -> Tuple[int, int]:
        rule_score = 0
        for role in self.seat_role_history.get(seat_id, []):
            if role == "右代宫战人" and self.battler_final_score is not None:
                rule_score += self.battler_final_score
            else:
                rule_score += self.settled_role_scores.get(role, 0)
        gm_score = self.gm_bonus.get(seat_id, 0)
        return rule_score, gm_score

    # ------------------------------------------------------------------
    # Seat 历史
    # ------------------------------------------------------------------

    def record_role_for_seat(self, seat_id: str, role: str):
        if seat_id not in self.seat_role_history:
            self.seat_role_history[seat_id] = []
        if role and role not in self.seat_role_history[seat_id]:
            self.seat_role_history[seat_id].append(role)

    def get_role_history(self, seat_id: str) -> List[str]:
        return list(self.seat_role_history.get(seat_id, []))

    def add_gm_bonus(self, seat_id: str, points: int, reason: str = ""):
        self.gm_bonus[seat_id] = self.gm_bonus.get(seat_id, 0) + points

    # ------------------------------------------------------------------
    # 观剧
    # ------------------------------------------------------------------

    def mark_spectator(self, seat_id: str):
        self.spectator_seats.add(seat_id)

    def is_spectator(self, seat_id: str) -> bool:
        return seat_id in self.spectator_seats

    def mark_eliminated(self, seat_id: str):
        if seat_id not in self.elimination_order:
            self.elimination_order.append(seat_id)

    # ------------------------------------------------------------------
    # 摘要
    # ------------------------------------------------------------------

    def get_summary(self) -> str:
        lines = ["=== 游戏状态 ==="]
        lines.append(f"Day {self.day} - {self.phase}")
        lines.append(f"存活: {sorted(self.alive_roles)}")
        lines.append(f"死亡: {sorted(self.dead_roles)}")
        lines.append(f"死亡顺序: {self.death_order}")
        lines.append(f"行动点: {self.action_points}")
        if self.schrodinger_violations:
            lines.append(f"薛定谔违规: {self.schrodinger_violations}")
        return "\n".join(lines)
