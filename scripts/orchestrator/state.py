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


# GM 角色豁免列表：不受行动点和调查次数限制
GM_ROLES = {"贝阿朵莉切"}


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

    # 贝阿朵闪回历史：记录已发送给贝阿朵的闪回章节ID
    beatrice_flashback_history: List[str] = field(default_factory=list)

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

    # 三位一体·薛定谔隐藏系统（嘉音/纱音专用）
    schrodinger_anchor: Optional[str] = None  # 当前主导人格（未隐藏者）
    schrodinger_revealed: Set[str] = field(default_factory=set)  # 临时现身的角色

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

    # 停止标志（用于测试和优雅关闭）
    _stop_requested: bool = False

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

    # 容器系统：container_id → Set[item_id]
    # container_id 可以是角色名、尸体ID、容器物品ID
    containers: Dict[str, Set[str]] = field(default_factory=dict)

    # 容器开闭状态：container_id → "open" | "closed"
    container_states: Dict[str, str] = field(default_factory=dict)

    # 物品实例状态：item_id → dict（如 {"ammo": 5}）
    # 每个 item_id 对应唯一的物品实例，状态在 add_item 时从 initial_state 初始化
    item_states: Dict[str, dict] = field(default_factory=dict)

    # 物品动态位置：item_id → 地点名 或 "container:容器ID" 或 "void"
    # 由 core.py 初始化时从 item_registry 的 location 字段填入
    item_locations: Dict[str, str] = field(default_factory=dict)

    # 物品可见性：item_id → "hidden" | "visible"
    # 初始化时从 item_registry 的 default_visibility 读取
    item_visibility: Dict[str, str] = field(default_factory=dict)

    # 藏匿系统
    hiding_spots: Dict[str, str] = field(default_factory=dict)  # role -> spot_id
    hiding_spot_occupants: Dict[str, Set[str]] = field(default_factory=dict)  # spot_id -> {roles}

    # buff 定义注册表（由 core.py 从 buffs.json 注入，供 hook 系统使用）
    buff_registry: Dict[str, dict] = field(default_factory=dict)

    # 已被取走的物品（全局唯一物品，取走后从初始位置移除）
    taken_items: Set[str] = field(default_factory=set)

    # 角色可观测物：role_name → List[observable_desc]
    # 每个时间槽 GM Session 生成一条 observable
    player_observables: Dict[str, List[str]] = field(default_factory=dict)

    # 当前时间槽内每个角色已使用的调查次数（10 轮对话 + 最多 2 次调查）
    investigations_used_this_slot: Dict[str, int] = field(default_factory=dict)

    # 门状态：location -> "locked" | "unlocked" | "broken"
    door_states: Dict[str, str] = field(default_factory=dict)

    # 剧情任务系统：role -> {quest_id -> quest_state}
    active_quests: Dict[str, Dict[str, dict]] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # 行动点操作
    # ------------------------------------------------------------------

    def consume_action_point(self, role: str, cost: int = 1) -> bool:
        if role in GM_ROLES:
            return True
        current = self.action_points.get(role, 50)
        if current >= cost:
            self.action_points[role] = current - cost
            return True
        return False

    def refund_action_point(self, role: str, cost: int = 1):
        if role in GM_ROLES:
            return
        current = self.action_points.get(role, 0)
        self.action_points[role] = current + cost

    def reset_action_points(self, points: int = 26):
        for role in self.alive_roles:
            # 跳过标记为无限行动点的角色（如贝阿朵莉切）
            if self.action_points.get(role, 0) >= 900:
                continue
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
        corpse_id = f"corpse:{role}"
        if corpse_id in self.item_registry:
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

        # 生成尸体物品（带容器属性）
        corpse_id = f"corpse:{role}"
        corpse_location = self.locations.get(role, "未知")
        self.item_registry[corpse_id] = {
            "id": corpse_id,
            "name": f"{role}的尸体",
            "type": "corpse",
            "description": f"{role}的尸体，安静地躺在地上。",
            "player_desc": f"你看着{role}的尸体，心中涌起复杂的情绪。",
            "gm_desc": f"{role}的尸体。死亡原因需要验尸确认。",
            "default_visibility": "visible",
            "is_container": True,
            "volume": 0,
            "capacity": None,
            "default_state": "open",
            "hooks": {
                "on_add": {
                    "steps": [
                        {"op": "grant_buff", "buff_id": "carrying_corpse", "target": "{role}"}
                    ]
                },
                "on_remove": {
                    "steps": [
                        {"op": "remove_buff", "buff_id": "carrying_corpse", "target": "{role}"}
                    ]
                }
            }
        }
        self.item_locations[corpse_id] = f"map:{corpse_location}"
        self.item_visibility[corpse_id] = "visible"
        self.container_states[corpse_id] = "open"

        # 将角色背包物品转移到尸体容器（跳过容积检查，确保不丢失）
        role_items = list(self.containers.get(role, set()))
        for item_id in role_items:
            self.containers[role].discard(item_id)
            self.containers.setdefault(corpse_id, set()).add(item_id)
            self.item_locations[item_id] = f"container:{corpse_id}"

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

    def is_corpse(self, item_id: str) -> bool:
        """判断物品是否为尸体。"""
        return item_id.startswith("corpse:")
    def is_container(self, container_id: str) -> bool:
        """判断 container_id 是否是一个容器。
        角色名（alive 或 dead）、尸体ID、或 is_container=True 的物品都是容器。"""
        if container_id in self.alive_roles or container_id in self.dead_roles:
            return True
        if container_id.startswith("corpse:"):
            return True
        item = self.item_registry.get(container_id, {})
        return item.get("is_container", False)

    # ------------------------------------------------------------------
    # 藏匿系统
    # ------------------------------------------------------------------

    def is_hidden(self, role: str) -> bool:
        if role in self.hiding_spots:
            return True
        # 薛定谔隐藏：嘉音/纱音若不等于 anchor 且不在 revealed 集合，则隐藏
        if role in ("嘉音", "纱音"):
            if self.schrodinger_anchor and role != self.schrodinger_anchor and role not in self.schrodinger_revealed:
                return True
        return False

    def is_schrodinger_hidden(self, role: str) -> bool:
        """仅检查薛定谔隐藏状态（不含普通藏匿）。"""
        if role not in ("嘉音", "纱音"):
            return False
        if self.schrodinger_anchor and role != self.schrodinger_anchor and role not in self.schrodinger_revealed:
            return True
        return False

    def hide_in(self, role: str, spot_id: str) -> bool:
        """将角色藏入藏匿点。"""
        item = self.item_registry.get(spot_id, {})
        if not item.get("is_hiding_spot"):
            return False
        capacity = item.get("hiding_capacity", 1)
        current = len(self.hiding_spot_occupants.get(spot_id, set()))
        if current >= capacity:
            return False
        # 离开当前藏匿点（如果有）
        self.leave_hiding_spot(role)
        self.hiding_spots[role] = spot_id
        self.hiding_spot_occupants.setdefault(spot_id, set()).add(role)
        return True

    def leave_hiding_spot(self, role: str) -> bool:
        """角色离开藏匿点。"""
        spot_id = self.hiding_spots.pop(role, None)
        if spot_id:
            occupants = self.hiding_spot_occupants.get(spot_id)
            if occupants:
                occupants.discard(role)
                if not occupants:
                    self.hiding_spot_occupants.pop(spot_id, None)
            return True
        return False

    def get_visible_roles_at(self, location: str, observer: Optional[str] = None) -> List[str]:
        """获取某地点对观察者可见的角色列表。

        可见性规则：
        - 非藏匿角色在地点中 → 对所有人可见
        - 藏匿角色 → 仅对同藏匿点内的其他藏匿者可见
        - 藏匿中的观察者可以看到同地点的非藏匿角色（偷听）
        - 薛定谔隐藏角色 → 对任何人（包括另一人格）不可见
        """
        visible = []
        observer_spot = self.hiding_spots.get(observer) if observer else None
        for role in self.alive_roles:
            role_loc = self.locations.get(role, "本馆")
            if role_loc != location:
                continue
            # 薛定谔隐藏角色对任何观察者都不可见
            if self.is_schrodinger_hidden(role):
                continue
            spot = self.hiding_spots.get(role)
            if not spot:
                # 非藏匿者：对所有人可见
                visible.append(role)
            elif observer_spot and observer_spot == spot:
                # 藏匿者：仅对同藏匿点内的观察者可见
                visible.append(role)
        return visible

    def get_hiding_spots_at(self, location: str) -> List[str]:
        """获取某地点的所有藏匿点ID。"""
        spots = []
        for item_id, item in self.item_registry.items():
            if item.get("is_hiding_spot") and item.get("location") == location:
                spots.append(item_id)
        return spots

    def get_container_used_volume(self, container_id: str) -> int:
        """计算容器总占用 = 内部物品体积之和 + 容器自身体积。
        V(x) = sum(V(i) for i in x) + v(x)"""
        items = self.containers.get(container_id, set())
        inner_sum = sum(
            self.item_registry.get(iid, {}).get("volume", 1)
            for iid in items
        )
        own_volume = self.item_registry.get(container_id, {}).get("volume", 1)
        return inner_sum + own_volume

    def can_fit(self, container_id: str, item_id: str) -> bool:
        """检查物品是否能放入容器（容积约束）。"""
        capacity = self.item_registry.get(container_id, {}).get("capacity")
        if capacity is None:
            return True  # 无限容量
        used = self.get_container_used_volume(container_id)
        item_volume = self.item_registry.get(item_id, {}).get("volume", 1)
        return used + item_volume <= capacity

    def open_container(self, container_id: str) -> bool:
        """打开容器。"""
        if not self.is_container(container_id):
            return False
        self.container_states[container_id] = "open"
        return True

    def close_container(self, container_id: str) -> bool:
        """关闭容器。"""
        if not self.is_container(container_id):
            return False
        self.container_states[container_id] = "closed"
        return True

    def get_effective_visibility(self, item_id: str, parent_container: str = None) -> str:
        """递归计算物品的有效可见性。
        closed 容器内所有物品 → hidden
        open 容器内物品 → min(容器visibility, 物品visibility)
        """
        item_vis = self.item_visibility.get(item_id, "hidden")
        
        if parent_container:
            # 容器 closed → 内部全部 hidden
            if self.container_states.get(parent_container) == "closed":
                return "hidden"
            # 容器 open → 取容器和物品的最小可见性
            container_vis = self.item_visibility.get(parent_container, "hidden")
            if container_vis == "hidden":
                return "hidden"
            # 继续向上递归（检查父容器）
            parent_loc = self.item_locations.get(parent_container, "")
            if parent_loc.startswith("container:"):
                grandparent = parent_loc[10:]
                return self.get_effective_visibility(item_id, grandparent)
        
        return item_vis


    def _run_item_hooks(self, item_id: str, hook_name: str, container_id: str) -> None:
        """执行物品 hook。只处理纯状态变更（buff），不涉及网络 IO。
        支持的操作：grant_buff, remove_buff。
        """
        item = self.item_registry.get(item_id, {})
        hooks = item.get("hooks", {}).get(hook_name, {})
        for step in hooks.get("steps", []):
            op = step.get("op")
            if op == "grant_buff":
                buff_id = step.get("buff_id", "")
                target = step.get("target", "{role}").replace("{role}", container_id)
                buff_def = self.buff_registry.get(buff_id, {})
                if buff_def:
                    self.apply_buff(target, buff_id, buff_def)
            elif op == "remove_buff":
                buff_id = step.get("buff_id", "")
                target = step.get("target", "{role}").replace("{role}", container_id)
                self.remove_buff(target, buff_id)

    def add_item(self, container_id: str, item_id: str) -> bool:
        """将物品加入容器。更新动态位置为 container:容器ID。
        检查容器是否 open、容积是否足够。
        若物品为全局唯一，自动标记为已取走。
        同时初始化物品实例状态（从 item_registry 的 initial_state 读取）。
        触发 on_add hook。"""
        if not self.is_container(container_id):
            return False
        
        # 非角色容器必须 open 才能放入
        if container_id not in (self.alive_roles | self.dead_roles):
            if self.container_states.get(container_id) == "closed":
                return False
        
        # 容积检查
        if not self.can_fit(container_id, item_id):
            return False
        
        self.containers.setdefault(container_id, set()).add(item_id)
        self.item_locations[item_id] = f"container:{container_id}"
        # 设置可见性：尸体强制 visible，其他物品默认 hidden
        if self.is_corpse(item_id):
            self.item_visibility[item_id] = "visible"
        else:
            item_def = self.item_registry.get(item_id, {})
            self.item_visibility[item_id] = item_def.get("default_visibility", "hidden")
        item = self.item_registry.get(item_id, {})
        if item.get("type") == "permanent":
            self.taken_items.add(item_id)
        # 初始化物品状态（若尚未初始化）
        if item_id not in self.item_states:
            initial = item.get("initial_state", {})
            self.item_states[item_id] = dict(initial)
        # 触发 on_add hook
        self._run_item_hooks(item_id, "on_add", container_id)
        return True

    def remove_item(self, container_id: str, item_id: str) -> bool:
        """从角色背包移除物品。触发 on_remove hook。
        不更新动态位置（由调用者决定物品去向）。"""
        inv = self.containers.get(container_id)
        if inv and item_id in inv:
            inv.discard(item_id)
            # 触发 on_remove hook
            self._run_item_hooks(item_id, "on_remove", container_id)
            return True
        return False

    def drop_item(self, container_id: str, item_id: str, location: str) -> bool:
        """将物品从容器丢弃到指定地点。
        内部调用 remove_item（触发 on_remove hook），再设置位置。"""
        if not self.has_item(container_id, item_id):
            return False
        self.remove_item(container_id, item_id)
        self.item_locations[item_id] = f"map:{location}"
        return True

    def has_item(self, container_id: str, item_id: str) -> bool:
        """检查角色是否持有指定物品。"""
        return item_id in self.containers.get(container_id, set())

    def can_enter_location(self, role: str, location: str, door_config: Optional[dict] = None) -> tuple[bool, str]:
        """检查角色是否可以进入有门的地点。
        返回 (能否进入, 原因/提示)。"""
        state = self.door_states.get(location)
        if state is None:
            return True, ""  # 无门
        if state == "broken" or state == "unlocked":
            return True, ""
        # locked
        if door_config:
            key_item = door_config.get("key_item")
            if key_item and self.has_item(role, key_item):
                return True, f"用{self.item_registry.get(key_item, {}).get('name', '钥匙')}打开了门"
            if self.has_item(role, "key:万能"):
                return True, "用万能钥匙打开了门"
        return False, f"{location}的门锁着，需要钥匙才能进入"

    def auto_acquire_room_key(self, role: str, location: str) -> Optional[str]:
        """角色进入地点时，自动拾取该地点的钥匙（如果钥匙在地点里且角色没有）。
        返回拾取的钥匙 item_id，或 None。"""
        for item_id, item in self.item_registry.items():
            if not item_id.startswith("key:"):
                continue
            current_loc = self.item_locations.get(item_id, "")
            if current_loc == f"map:{location}":
                if not self.has_item(role, item_id):
                    if self.add_item(role, item_id):
                        return item_id
        return None

    def get_container_items(self, container_id: str) -> Set[str]:
        """获取角色背包中的物品 ID 集合。
        嘉音与纱音共享同一背包（指针指向同一 set 实例）。"""
        if container_id in ("嘉音", "纱音"):
            # 确保两人共享同一集合
            if "嘉音" not in self.containers:
                self.containers["嘉音"] = set()
            if "纱音" not in self.containers:
                self.containers["纱音"] = self.containers["嘉音"]
            # 若因历史原因指向不同集合，强制合并并统一
            if self.containers["嘉音"] is not self.containers["纱音"]:
                unified = self.containers["嘉音"] | self.containers["纱音"]
                self.containers["嘉音"] = unified
                self.containers["纱音"] = unified
            return set(self.containers["嘉音"])
        return set(self.containers.get(container_id, set()))

    def get_item_location(self, item_id: str) -> str:
        """获取物品的当前位置。
        返回地点名、'container:容器ID'、或 'void'。"""
        if item_id in self.item_locations:
            return self.item_locations[item_id]
        # 回退到注册表中的初始位置
        item = self.item_registry.get(item_id, {})
        return item.get("location", "void")

    def set_item_visibility(self, item_id: str, visibility: str) -> bool:
        """设置物品可见性。尸体在背包中时不可修改（始终 visible）。
        返回是否成功修改。"""
        if item_id not in self.item_locations:
            return False
        loc = self.item_locations[item_id]
        if self.is_corpse(item_id) and loc.startswith("container:"):
            # 尸体在背包中时强制 visible，不可修改
            return False
        self.item_visibility[item_id] = visibility
        return True

    def build_available_actions(self, role: str, investigations_remaining: int = 2, nearby_players: Optional[List[str]] = None) -> List[str]:
        """动态构建角色当前可用的行动列表。

        返回格式化的行动描述字符串列表，供 turn_token 上下文拼接。
        """
        lines: List[str] = []
        # 基础行动
        lines.append("1. 发言（每轮都可以，同地点所有人能听到，消耗0行动点）")
        if investigations_remaining > 0:
            cost = self.get_action_point_cost(role, 2)
            lines.append(f"2. 调查/互动（消耗{cost}点行动点，占用1次调查机会，本时间槽剩余 {investigations_remaining} 次机会）")
            lines.append("   包括：调查地点或人物、拾取物品、搜身、安慰、开枪等")
        else:
            lines.append("2. 调查/互动（本时间槽次数已用尽，本轮无法执行）")
        # 移动作为独立选项，与调查互斥
        move_cost = self.get_action_point_cost(role, 1)
        lines.append(f"3. 移动（消耗{move_cost}点行动点，立即生效。选择移动后本回合不能再调查或互动）")
        lines.append("4. 跳过回合")
        lines.append("5. 丢弃物品（将背包中的物品丢在当前地点，消耗0行动点）")

        # 藏匿点信息
        role_loc = self.locations.get(role, "本馆")
        spots = self.get_hiding_spots_at(role_loc)
        if spots:
            spot_names = [self.item_registry.get(sid, {}).get("name", sid) for sid in spots]
            lines.append(f"5. 藏匿：你注意到这里有可以躲藏的地方：{', '.join(spot_names)}")

        # 物品授予的行动（使用、赠送、射击等全部在这里）
        inventory = self.get_container_items(role)
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

    def transfer_item(self, from_container: str, to_container: str, item_id: str) -> bool:
        """将物品从 from_container 转移给 to_container。
        触发 on_remove（from 方）→ on_add（to 方）。
        自动检查目标容器容积。"""
        if not self.has_item(from_container, item_id):
            return False
        self.remove_item(from_container, item_id)
        return self.add_item(to_container, item_id)

    def get_location_items(self, location: str, day: int, visibility_filter: Optional[str] = None, max_depth: int = 5) -> List[str]:
        """获取指定地点和日期下可用的物品 ID 列表。
        递归展开 open 容器内的物品。
        visibility_filter: None 返回所有，"visible" 只返回可见，"hidden" 只返回隐藏。
        max_depth: 递归深度限制，防止无限套娃。"""
        if max_depth <= 0:
            return []
        result = []
        for item_id, loc in self.item_locations.items():
            if loc != f"map:{location}":
                continue
            if loc == "void":
                continue
            item = self.item_registry.get(item_id, {})
            if item.get("day_available", 1) > day:
                continue
            if visibility_filter is not None:
                vis = self.get_effective_visibility(item_id)
                if vis != visibility_filter:
                    continue
            result.append(item_id)
            # 递归展开 open 容器内的物品
            if self.is_container(item_id) and self.container_states.get(item_id) == "open":
                inner_items = self.containers.get(item_id, set())
                for inner_id in inner_items:
                    inner_item = self.item_registry.get(inner_id, {})
                    if inner_item.get("day_available", 1) > day:
                        continue
                    if visibility_filter is not None:
                        inner_vis = self.get_effective_visibility(inner_id, item_id)
                        if inner_vis != visibility_filter:
                            continue
                    result.append(inner_id)
        return result

    def get_visible_location_items(self, location: str, day: int) -> List[str]:
        """获取指定地点和日期下可见的物品 ID 列表。"""
        return self.get_location_items(location, day, visibility_filter="visible")

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
        """消耗一次调查次数。若未超过上限则成功。GM角色豁免。"""
        if role in GM_ROLES:
            return True
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

    # ------------------------------------------------------------------
    # 薛定谔隐藏系统辅助方法
    # ------------------------------------------------------------------

    def bind_schrodinger_location(self, role: str, location: str) -> None:
        """同步嘉音与纱音的位置。任意一方移动时，另一方自动跟随。"""
        if role not in ("嘉音", "纱音"):
            return
        other = "纱音" if role == "嘉音" else "嘉音"
        self.locations[role] = location
        if other in self.alive_roles:
            self.locations[other] = location

    def set_schrodinger_anchor(self, role: str) -> None:
        """设置主导人格，另一人自动进入隐藏。"""
        if role not in ("嘉音", "纱音"):
            return
        self.schrodinger_anchor = role
        self.schrodinger_revealed.discard(role)
        other = "纱音" if role == "嘉音" else "嘉音"
        self.schrodinger_revealed.discard(other)

    def try_reveal(self, role: str) -> bool:
        """尝试现身。若地点中仅有嘉音/纱音（无第三人），则成功。"""
        if role not in ("嘉音", "纱音"):
            return False
        loc = self.locations.get(role, "本馆")
        others = [r for r in self.alive_roles if r != role and self.locations.get(r) == loc and r not in ("嘉音", "纱音", "贝阿朵莉切")]
        if others:
            return False
        self.schrodinger_revealed.add(role)
        return True

    def force_conceal(self, role: str) -> bool:
        """强制恢复隐藏。"""
        if role not in self.schrodinger_revealed:
            return False
        self.schrodinger_revealed.discard(role)
        return True

    def get_schrodinger_other(self, role: str) -> Optional[str]:
        """获取另一人格名称。"""
        if role == "嘉音":
            return "纱音"
        if role == "纱音":
            return "嘉音"
        return None

    def auto_schrodinger_anchor_by_location(self, location: str) -> Optional[str]:
        """根据地点自动决定主导人格。
        嘉音地盘 → 嘉音主导；纱音地盘 → 纱音主导；其他 → 纱音主导（表人格优先）。"""
        kanon_territory = {"玫瑰园", "庭院", "仓库", "镇守之森"}
        shannon_territory = {"本馆", "餐厅", "厨房", "客房", "书房"}
        if location in kanon_territory:
            return "嘉音"
        # 默认纱音主导（包括纱音地盘和其他地点）
        return "纱音"
