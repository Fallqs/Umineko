"""
《海猫鸣泣之时：六轩岛黄昏》配置加载器

集中加载 config/ 目录下的 JSON 配置文件，懒加载 + 缓存。
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple


class ConfigLoader:
    """动态加载游戏配置。"""

    def __init__(self, config_dir: Path):
        self.config_dir = Path(config_dir)
        self._locations: Optional[List[str]] = None
        self._role_locs: Optional[Dict[str, str]] = None
        self._info_table: Optional[Dict[str, Dict[int, List[Tuple[str, str]]]]] = None
        self._distances: Optional[Dict[str, Dict[str, int]]] = None

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

    def get_location_info(self, location: str, day: int) -> List[Tuple[str, str]]:
        return self.location_info_table.get(location, {}).get(day, [])
