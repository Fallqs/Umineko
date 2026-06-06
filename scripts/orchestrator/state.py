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
    night_owl: Set[str] = field(default_factory=set)  # 向后兼容，将逐步迁移到 status_effects

    # 状态效果系统：role_name -> {buff_id -> buff_instance}
    # buff_instance 格式: {"applied_at": (day, phase), "duration": dict, "params": dict, "turns_remaining": int}
    status_effects: Dict[str, Dict[str, dict]] = field(default_factory=dict)

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
    # 物品系统（Phase B 架构）
    # ------------------------------------------------------------------

    # 物品注册表：item_id → 物品定义（由 ConfigLoader 注入）
    # 定义格式: {
    #   "id": str, "name": str, "type": "consumable"|"permanent",
    #   "gm_desc": str, "player_desc": str,
    #   "location": str, "day_available": int,
    #   "unlocks_info": [str], "effect": dict,
    # }
    item_registry: Dict[str, dict] = field(default_factory=dict)

    # 角色背包：role_name → Set[item_id]
    inventory: Dict[str, Set[str]] = field(default_factory=dict)

    # 物品实例状态：item_id → dict（如 {"ammo": 5}）
    # 每个 item_id 对应唯一的物品实例，状态在 add_item 时从 initial_state 初始化
    item_states: Dict[str, dict] = field(default_factory=dict)

    # 已被取走的物品（全局唯一物品，取走后从场景中移除）
    taken_items: Set[str] = field(default_factory=set)

    # 角色可观测物：role_name → List[observable_desc]
    # 每个时间槽 GM Session 生成一条 observable
    player_observables: Dict[str, List[str]] = field(default_factory=dict)

    # 当前时间槽内每个角色已使用的调查次数（10 轮对话 + 最多 2 次调查）
    investigations_used_this_slot: Dict[str, int] = field(default_factory=dict)

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

    def reset_action_points(self, points: int = 26):
        for role in self.alive_roles:
            self.action_points[role] = points

    def get_action_point_cost(self, role: str, base_cost: int) -> int:
        """计算实际 AP 消耗（含 buff 影响）。保留 night_owl 向后兼容。"""
        multiplier = self.calculate_ap_multiplier(role)
        # 向后兼容：若 night_owl 中有角色但未在 status_effects 中注册，视为 ×2
        if role in self.night_owl and role not in self.status_effects.get("night_owl", {}):
            multiplier *= 2.0
        return int(base_cost * multiplier)

    def calculate_ap_multiplier(self, role: str) -> float:
        """计算角色当前的 AP 消耗倍率（所有 buff 效果相乘）。"""
        total = 1.0
        for buff_id, buff_inst in self.status_effects.get(role, {}).items():
            for effect in buff_inst.get("effects", []):
                if effect.get("op") == "modify_ap_cost":
                    total *= effect.get("multiplier", 1.0)
        return total

    # ------------------------------------------------------------------
    # Buff 系统
    # ------------------------------------------------------------------

    def apply_buff(self, role: str, buff_id: str, buff_def: dict, **params) -> bool:
        """给角色施加 buff。若已存在同名 buff，刷新持续时间。"""
        if role not in self.status_effects:
            self.status_effects[role] = {}
        # 构造 buff 实例
        instance = {
            "buff_id": buff_id,
            "name": buff_def.get("name", buff_id),
            "type": buff_def.get("type", "neutral"),
            "duration": dict(buff_def.get("duration", {})),
            "effects": list(buff_def.get("effects", [])),
            "params": dict(params),
            "turns_remaining": buff_def.get("duration", {}).get("count", 0),
            "applied_day": self.day,
            "applied_phase": self.phase,
        }
        self.status_effects[role][buff_id] = instance
        return True

    def remove_buff(self, role: str, buff_id: str) -> bool:
        """移除角色的指定 buff。"""
        role_effects = self.status_effects.get(role, {})
        if buff_id in role_effects:
            del role_effects[buff_id]
            if not role_effects:
                self.status_effects.pop(role, None)
            return True
        return False

    def has_buff(self, role: str, buff_id: str) -> bool:
        """检查角色是否持有指定 buff。"""
        return buff_id in self.status_effects.get(role, {})

    def get_buffs(self, role: str) -> Dict[str, dict]:
        """获取角色当前所有 buff。"""
        return dict(self.status_effects.get(role, {}))

    def is_action_blocked(self, role: str, action_id: str) -> Optional[str]:
        """检查某行动是否被 buff 阻塞。返回阻塞原因或 None。"""
        for buff_id, buff_inst in self.status_effects.get(role, {}).items():
            for effect in buff_inst.get("effects", []):
                if effect.get("op") == "block_action":
                    blocked = effect.get("action_ids", [])
                    if action_id in blocked:
                        return f"受【{buff_inst.get('name', buff_id)}】影响，无法执行"
        return None

    def tick_buff_durations(self, event: str):
        """推进 buff 持续时间。在特定事件（如 token_ring_end、DAWN）时调用。"""
        expired: list[tuple[str, str]] = []
        for role, buffs in list(self.status_effects.items()):
            for buff_id, buff_inst in list(buffs.items()):
                duration = buff_inst.get("duration", {})
                dtype = duration.get("type")
                if dtype == "turns":
                    countdown_on = duration.get("countdown_on", ["token_ring_end"])
                    if event in countdown_on:
                        buff_inst["turns_remaining"] = buff_inst.get("turns_remaining", 1) - 1
                        if buff_inst["turns_remaining"] <= 0:
                            expired.append((role, buff_id))
                elif dtype == "until_phase":
                    if event in duration.get("phases", []):
                        expired.append((role, buff_id))
                elif dtype == "single_use":
                    pass  # 由具体行动触发移除
        for role, buff_id in expired:
            self.remove_buff(role, buff_id)

    def clear_phase_buffs(self, phase: str):
        """到达特定阶段时清除对应 buff（DAWN 时清除 night_owl 等）。"""
        self.tick_buff_durations(phase)
        # 向后兼容：同时清空 night_owl
        if phase == "DAWN":
            self.night_owl.clear()

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
        # 清理死亡角色的所有 buff
        self.status_effects.pop(role, None)
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

    # ------------------------------------------------------------------
    # 物品操作
    # ------------------------------------------------------------------

    def add_item(self, role: str, item_id: str) -> bool:
        """将物品加入角色背包。若物品为全局唯一，自动标记为已取走。
        同时初始化物品实例状态（从 item_registry 的 initial_state 读取）。"""
        if role not in self.inventory:
            self.inventory[role] = set()
        self.inventory[role].add(item_id)
        item = self.item_registry.get(item_id, {})
        if item.get("type") == "permanent":
            self.taken_items.add(item_id)
        # 初始化物品状态（若尚未初始化）
        if item_id not in self.item_states:
            initial = item.get("initial_state", {})
            self.item_states[item_id] = dict(initial)
        return True

    def remove_item(self, role: str, item_id: str) -> bool:
        """从角色背包移除物品。"""
        inv = self.inventory.get(role)
        if inv and item_id in inv:
            inv.discard(item_id)
            return True
        return False

    def has_item(self, role: str, item_id: str) -> bool:
        """检查角色是否持有指定物品。"""
        return item_id in self.inventory.get(role, set())

    def get_inventory(self, role: str) -> Set[str]:
        """获取角色背包中的物品 ID 集合。"""
        return set(self.inventory.get(role, set()))

    def build_available_actions(self, role: str, investigations_remaining: int = 2, nearby_players: Optional[List[str]] = None) -> List[str]:
        """动态构建角色当前可用的行动列表。

        返回格式化的行动描述字符串列表，供 turn_token 上下文拼接。
        """
        lines: List[str] = []
        # 基础行动
        lines.append("1. 发言（每轮都可以，同地点所有人能听到，消耗0行动点）")
        if investigations_remaining > 0:
            cost = self.get_action_point_cost(role, 2)
            lines.append(f"2. 调查当前地点或指定对象（消耗{cost}点，本时间槽剩余 {investigations_remaining} 次机会）")
        else:
            lines.append("2. 调查当前地点或指定对象（本时间槽调查次数已用尽）")
        lines.append("3. 移动（消耗1-3行动点，取决于距离）")
        lines.append("4. 跳过回合")

        # 物品授予的行动（使用、赠送、射击等全部在这里）
        inventory = self.get_inventory(role)
        special_actions: List[str] = []
        for item_id in inventory:
            item = self.item_registry.get(item_id, {})
            for action_def in item.get("granted_actions", []):
                action_id = action_def.get("id", "")
                action_name = action_def.get("name", action_id)
                base_cost = action_def.get("ap_cost", 1)
                actual_cost = self.get_action_point_cost(role, base_cost)
                target_type = action_def.get("target_type", "none")
                target_desc = ""
                if target_type == "role":
                    target_desc = f"（目标：{'/'.join(nearby_players) if nearby_players else '无'}）"
                elif target_type == "location":
                    target_desc = "（目标：地点）"
                special_actions.append(f"- {action_name}（消耗{actual_cost}点）{target_desc}")
        if special_actions:
            lines.append("")
            lines.append("【特殊行动】你持有的物品允许你执行以下行动：")
            lines.extend(special_actions)

        # buff 状态提示
        buffs = self.get_buffs(role)
        if buffs:
            lines.append("")
            lines.append("【状态效果】")
            for buff_id, inst in buffs.items():
                desc = inst.get("description", buff_id)
                remaining = inst.get("duration_remaining", "?")
                lines.append(f"- {desc}（剩余 {remaining} 回合/阶段）")

        return lines

    def is_item_taken(self, item_id: str) -> bool:
        """检查全局唯一物品是否已被取走。"""
        return item_id in self.taken_items

    def mark_item_taken(self, item_id: str):
        """手动标记物品为已取走（用于 GM 强制操作）。"""
        self.taken_items.add(item_id)

    def get_item_desc(self, item_id: str, gm_view: bool = False) -> str:
        """获取物品描述。gm_view=True 返回 gm_desc，否则返回 player_desc。"""
        item = self.item_registry.get(item_id, {})
        if gm_view:
            return item.get("gm_desc", "一件不明物品")
        return item.get("player_desc", item.get("gm_desc", "一件不明物品"))

    def transfer_item(self, from_role: str, to_role: str, item_id: str) -> bool:
        """将物品从 from_role 转移给 to_role。"""
        if not self.has_item(from_role, item_id):
            return False
        self.remove_item(from_role, item_id)
        self.add_item(to_role, item_id)
        return True

    def get_location_items(self, location: str, day: int) -> List[str]:
        """获取指定地点和日期下可用的物品 ID 列表（排除已被取走的）。"""
        result = []
        for item_id, item in self.item_registry.items():
            if item.get("location") != location:
                continue
            if item.get("day_available", 1) > day:
                continue
            if item_id in self.taken_items:
                continue
            result.append(item_id)
        return result

    def use_item(self, role: str, item_id: str) -> tuple[bool, str, list[str]]:
        """使用物品。
        Returns: (成功, 使用描述, 解锁的信息条目列表)
        """
        if not self.has_item(role, item_id):
            return False, "你没有这件物品。", []
        item = self.item_registry.get(item_id, {})
        if not item:
            return False, "未知物品。", []

        unlocked_infos = list(item.get("unlocks_info", []))
        for info_id in unlocked_infos:
            self.unlock_info(role, info_id)

        desc = item.get("player_desc", "你使用了这件物品。")

        # 应用状态变化（如果定义了 state_changes）
        state_changes = item.get("state_changes", {})
        if state_changes:
            current_state = self.item_states.get(item_id, {})
            for key, delta in state_changes.items():
                if isinstance(delta, (int, float)):
                    current_state[key] = current_state.get(key, 0) + delta
                else:
                    current_state[key] = delta
            self.item_states[item_id] = current_state

        # 一次性物品使用后移除
        if item.get("type") == "consumable":
            self.remove_item(role, item_id)
            desc += "（物品已消耗）"

        return True, desc, unlocked_infos

    def get_item_state(self, item_id: str, key: str, default=None):
        """获取指定物品实例的状态字段。"""
        return self.item_states.get(item_id, {}).get(key, default)

    def set_item_state(self, item_id: str, key: str, value):
        """设置指定物品实例的状态字段。"""
        if item_id not in self.item_states:
            self.item_states[item_id] = {}
        self.item_states[item_id][key] = value

    # ------------------------------------------------------------------
    # 可观测物
    # ------------------------------------------------------------------

    def add_observable(self, role: str, description: str):
        """为角色添加一个可观测物（GM Session 生成的时间槽观测）。"""
        if role not in self.player_observables:
            self.player_observables[role] = []
        self.player_observables[role].append(description)

    def get_observables(self, role: str) -> List[str]:
        """获取角色当前所有可观测物。"""
        return list(self.player_observables.get(role, []))

    def clear_observables(self, role: str):
        """清空角色的可观测物（通常在新的一天开始时调用）。"""
        self.player_observables.pop(role, None)

    # ------------------------------------------------------------------
    # 调查次数（10 轮对话 + 最多 2 次调查）
    # ------------------------------------------------------------------

    def reset_investigations(self):
        """新的时间槽开始时重置所有存活角色的调查次数。"""
        self.investigations_used_this_slot = {role: 0 for role in self.alive_roles}

    def get_investigations_used(self, role: str) -> int:
        """获取角色当前时间槽已用调查次数。"""
        return self.investigations_used_this_slot.get(role, 0)

    def use_investigation(self, role: str, max_per_slot: int = 2) -> bool:
        """消耗一次调查次数。若未超过上限则成功。"""
        used = self.investigations_used_this_slot.get(role, 0)
        if used >= max_per_slot:
            return False
        self.investigations_used_this_slot[role] = used + 1
        return True

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
