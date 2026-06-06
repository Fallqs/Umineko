#!/usr/bin/env python3
"""
《海猫鸣泣之时：六轩岛黄昏》地点数据与调查内容

从 config/ 目录下的 JSON 文件动态加载，便于剧情作者修改配置。
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple

# ---------------------------------------------------------------------------
# 配置文件路径
# ---------------------------------------------------------------------------

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def _load_json(filename: str) -> dict:
    """加载 config/ 目录下的 JSON 文件。"""
    path = CONFIG_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# 动态加载配置
# ---------------------------------------------------------------------------

# 地点列表
_loc_cfg = _load_json("locations.json")
LOCATIONS: List[str] = _loc_cfg["locations"]

# 距离矩阵（扁平化为 (a,b) -> int）
_DISTANCES_RAW: Dict[str, Dict[str, int]] = _loc_cfg["distances"]


# 角色初始位置
_role_loc_cfg = _load_json("role_locations.json")
ROLE_INITIAL_LOCATIONS: Dict[str, str] = _role_loc_cfg["locations"]

# 地点信息表（线索）
_info_cfg = _load_json("location_info.json")
# 将字符串天数键转为整数
LOCATION_INFO_TABLE: Dict[str, Dict[int, List[Tuple[str, str]]]] = {}
for loc, day_map in _info_cfg.items():
    if loc.startswith("_"):
        continue
    LOCATION_INFO_TABLE[loc] = {}
    for day_str, entries in day_map.items():
        LOCATION_INFO_TABLE[loc][int(day_str)] = [tuple(e) for e in entries]


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def get_distance(a: str, b: str) -> int:
    """获取两个地点之间的距离（行动点消耗）。"""
    if a == b:
        return 0
    # 直接查找
    d = _DISTANCES_RAW.get(a, {}).get(b)
    if d is not None:
        return d
    d = _DISTANCES_RAW.get(b, {}).get(a)
    if d is not None:
        return d
    # 默认远距
    return 3


def get_location_info(location: str, day: int) -> List[Tuple[str, str]]:
    """获取指定地点在指定天数可解锁的信息列表。"""
    return LOCATION_INFO_TABLE.get(location, {}).get(day, [])
