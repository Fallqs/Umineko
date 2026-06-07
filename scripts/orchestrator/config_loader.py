"""
《海猫鸣泣之时：六轩岛黄昏》配置加载器

集中加载 config/ 目录下的 JSON 配置文件，懒加载 + 缓存。
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class ConfigLoader:
    """动态加载游戏配置。"""

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self._locations: Optional[List[str]] = None
        self._role_locs: Optional[Dict[str, str]] = None
        self._info_table: Optional[Dict[str, Dict[int, List[Tuple[str, str]]]]] = None
        self._distances: Optional[Dict[str, Dict[str, int]]] = None
        self._items: Optional[Dict[str, dict]] = None
        self._game_rules: Optional[dict] = None
        self._time_slots: Optional[dict] = None
        self._buffs: Optional[dict] = None

    def _load_json(self, filename: str) -> dict:
        path = self.config_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"配置文件不存在: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @property
    def locations(self) -> List[str]:
        if self._locations is None:
            self._locations = self._load_json("locations.json")["locations"]
        return self._locations

    @property
    def role_initial_locations(self) -> Dict[str, str]:
        if self._role_locs is None:
            self._role_locs = self._load_json("role_locations.json")["locations"]
        return self._role_locs

    @property
    def _raw_distances(self) -> Dict[str, Dict[str, int]]:
        if self._distances is None:
            self._distances = self._load_json("locations.json")["distances"]
        return self._distances

    @property
    def location_info_table(self) -> Dict[str, Dict[int, List[Tuple[str, str]]]]:
        if self._info_table is None:
            raw = self._load_json("location_info.json")
            result: Dict[str, Dict[int, List[Tuple[str, str]]]] = {}
            for loc, day_map in raw.items():
                if loc.startswith("_"):
                    continue
                result[loc] = {}
                for day_str, entries in day_map.items():
                    result[loc][int(day_str)] = [tuple(e) for e in entries]
            self._info_table = result
        return self._info_table

    def get_distance(self, a: str, b: str) -> int:
        if a == b:
            return 0
        d = self._raw_distances.get(a, {}).get(b)
        if d is not None:
            return d
        d = self._raw_distances.get(b, {}).get(a)
        if d is not None:
            return d
        return 3

    def get_location_info(self, location: str, day: int) -> List[Tuple[str, str, Optional[dict]]]:
        """返回地点信息条目，格式: (info_id, desc, requires_dict)。
        requires_dict 可能为 None（无条件解锁）。"""
        entries = self.location_info_table.get(location, {}).get(day, [])
        result = []
        for entry in entries:
            if isinstance(entry, dict):
                # 新格式: {"id": ..., "desc": ..., "requires": ...}
                iid = entry.get("id", "")
                desc = entry.get("desc", "")
                requires = entry.get("requires")
                result.append((iid, desc, requires))
            elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
                # 旧格式兼容: [info_id, desc] 或 (info_id, desc)
                requires = entry[2] if len(entry) >= 3 else None
                result.append((entry[0], entry[1], requires))
        return result

    # ------------------------------------------------------------------
    # 物品配置（预留接口，数据填充阶段启用）
    # ------------------------------------------------------------------

    @property
    def items(self) -> Dict[str, dict]:
        """加载物品注册表。格式: {item_id: item_definition_dict}。
        若 items.json 不存在则返回空字典，不报错。"""
        if self._items is None:
            try:
                raw = self._load_json("items.json")
                # 支持两种格式: 直接是 dict 或 {"items": [...]}
                if isinstance(raw, dict) and "items" in raw:
                    item_list = raw["items"]
                elif isinstance(raw, list):
                    item_list = raw
                else:
                    item_list = []
                self._items = {item["id"]: item for item in item_list if "id" in item}
            except FileNotFoundError:
                self._items = {}
        return self._items

    @property
    def game_rules(self) -> dict:
        """加载游戏规则配置。若 game_rules.json 不存在则返回空字典，不报错。"""
        if self._game_rules is None:
            try:
                self._game_rules = self._load_json("game_rules.json")
            except FileNotFoundError:
                self._game_rules = {}
        return self._game_rules

    def get_ap_cost(self, action: str) -> int:
        """获取指定行动的AP消耗。若配置缺失则返回默认值。"""
        return self.game_rules.get("action_points", {}).get(action, 1)

    def get_token_ring_rule(self, key: str, default=None):
        """获取令牌环规则。"""
        return self.game_rules.get("token_ring", {}).get(key, default)

    def get_action_range(self, action_id: str) -> int:
        """获取行动的作用距离。优先级：物品action定义 > game_rules.action_ranges > 0"""
        # 1. 物品action定义中查找range
        for item in self.items.values():
            for action_def in item.get("granted_actions", []):
                if action_def.get("id") == action_id and "range" in action_def:
                    return int(action_def["range"])
        # 2. game_rules.action_ranges中查找
        return self.game_rules.get("action_ranges", {}).get(action_id, 0)

    def get_info_points(self, info_id: str) -> int:
        """根据信息ID前缀获取分值。"""
        for prefix, pts in self.game_rules.get("info_points", {}).items():
            if info_id.startswith(prefix):
                return pts
        return 0

    @property
    def time_slots(self) -> dict:
        """加载时间槽配置。若 time_slots.json 不存在则返回空字典，不报错。"""
        if self._time_slots is None:
            try:
                self._time_slots = self._load_json("time_slots.json")
            except FileNotFoundError:
                self._time_slots = {}
        return self._time_slots

    def get_time_slot_list(self) -> List[str]:
        """返回一天内的时间槽顺序列表。"""
        return self.time_slots.get("time_slots", [])

    def get_free_slots(self) -> List[str]:
        """返回自由时间槽列表。"""
        return self.time_slots.get("free_slots", [])

    def get_meal_slots(self) -> List[str]:
        """返回用餐时间槽列表。"""
        return self.time_slots.get("meal_slots", [])

    def get_special_slots(self) -> List[str]:
        """返回特殊时间槽列表。"""
        return self.time_slots.get("special_slots", [])

    @property
    def buffs(self) -> dict:
        """加载 buff 配置。若 buffs.json 不存在则返回空字典，不报错。"""
        if self._buffs is None:
            try:
                raw = self._load_json("buffs.json")
                self._buffs = raw.get("buffs", {})
            except FileNotFoundError:
                self._buffs = {}
        return self._buffs

    def get_buff(self, buff_id: str) -> Optional[dict]:
        """获取单个 buff 定义。"""
        return self.buffs.get(buff_id)

    def get_item(self, item_id: str) -> Optional[dict]:
        """获取单个物品定义。"""
        return self.items.get(item_id)

    def get_items_at_location(self, location: str, day: int) -> List[dict]:
        """获取指定地点和日期下可用的物品定义列表。"""
        result = []
        for item in self.items.values():
            if item.get("location") != location:
                continue
            if item.get("day_available", 1) > day:
                continue
            result.append(item)
        return result

    @property
    def death_schedule(self) -> List[dict]:
        """加载预定死亡表。若 death_schedule.json 不存在则返回空列表。"""
        try:
            raw = self._load_json("death_schedule.json")
            return raw.get("deaths", [])
        except FileNotFoundError:
            return []

    @property
    def seat_chains(self) -> Dict[str, List[str]]:
        """加载角色切换链。若 seat_chains.json 不存在则返回空字典。"""
        try:
            raw = self._load_json("seat_chains.json")
            return raw.get("chains", {})
        except FileNotFoundError:
            return {}
