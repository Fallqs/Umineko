"""验证钥匙/门锁系统 + 邻接表/Dijkstra 距离计算。"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "orchestrator"))

from config_loader import ConfigLoader
from state import GameState

CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "config")

def _make_state():
    config = ConfigLoader(CONFIG_DIR)
    state = GameState()
    # 同步 core.py 中的初始化
    state.item_registry = dict(config.items)
    for item_id, item in state.item_registry.items():
        loc = item.get("location", "")
        if loc:
            state.item_locations[item_id] = f"map:{loc}" if loc != "void" else "void"
        vis = item.get("default_visibility", "hidden")
        state.item_visibility[item_id] = vis
        if item.get("is_container"):
            state.container_states[item_id] = item.get("default_state", "closed")
    for loc, door_config in config.doors.items():
        state.door_states[loc] = door_config.get("default_state", "locked")
    # 注册测试角色为存活
    state.alive_roles.update(["战人", "熊泽", "藏臼", "秀吉"])
    return state, config

def test_door_init():
    state, config = _make_state()
    assert state.door_states.get("书房") == "locked", "书房应初始上锁"
    assert state.door_states.get("客房") == "unlocked", "客房应初始未上锁"
    assert state.door_states.get("主卧") == "unlocked", "主卧应初始未上锁"
    assert state.door_states.get("秀吉房间") == "unlocked", "秀吉房间应初始未上锁"
    print("[PASS] 门状态初始化正确")

def test_master_key():
    state, config = _make_state()
    state.add_item("熊泽", "key:万能")
    assert state.has_item("熊泽", "key:万能"), "熊泽应持有万能钥匙"
    print("[PASS] 熊泽获得万能钥匙")

def test_can_enter():
    state, config = _make_state()
    door_config = config.doors.get("书房")

    ok, reason = state.can_enter_location("战人", "书房", door_config)
    assert not ok, "战人无钥匙时不应能进入书房"
    assert "锁着" in reason
    print("[PASS] 无钥匙进入被阻止: " + reason)

    state.add_item("战人", "key:书房")
    ok, reason = state.can_enter_location("战人", "书房", door_config)
    assert ok, "战人持有书房钥匙时应能进入"
    print("[PASS] 有钥匙可进入: " + reason)

    state.add_item("熊泽", "key:万能")
    ok, reason = state.can_enter_location("熊泽", "书房", door_config)
    assert ok, "熊泽持有万能钥匙时应能进入书房"
    print("[PASS] 万能钥匙可进入: " + reason)

def test_auto_acquire_key():
    state, config = _make_state()
    state.item_locations["key:客房"] = "map:客房"
    key_id = state.auto_acquire_room_key("战人", "客房")
    assert key_id == "key:客房", f"应自动获得客房钥匙，实际获得: {key_id}"
    assert state.has_item("战人", "key:客房"), "战人应持有客房钥匙"
    print("[PASS] 自动获得钥匙逻辑正确")

def test_lock_unlock():
    state, config = _make_state()
    state.add_item("战人", "key:书房")

    state.door_states["书房"] = "locked"
    ok, _ = state.can_enter_location("战人", "书房", config.doors.get("书房"))
    assert ok, "解锁前应能进入（持有钥匙）"
    state.door_states["书房"] = "unlocked"
    ok, _ = state.can_enter_location("战人", "书房", config.doors.get("书房"))
    assert ok, "解锁后应能进入"
    print("[PASS] 上锁/解锁状态切换正确")

def test_broken_door():
    state, config = _make_state()
    state.door_states["书房"] = "broken"
    ok, _ = state.can_enter_location("战人", "书房", config.doors.get("书房"))
    assert ok, "破坏后的门应始终可进入"
    print("[PASS] 破坏后的门永久开放")

def test_normalize_location():
    config = ConfigLoader(CONFIG_DIR)
    # 精确匹配
    assert config.normalize_location("书房") == "书房"
    # sub_locations 映射
    assert config.normalize_location("本馆-书房") == "书房"
    assert config.normalize_location("别馆-秀吉房间") == "秀吉房间"
    # 前缀匹配
    assert config.normalize_location("主卧") == "主卧"
    # 括号清理
    assert config.normalize_location("本馆-客房（妈妈的房间）") == "客房"
    # 按 '-' 拆分后前缀匹配
    assert config.normalize_location("别馆-秀吉") == "秀吉房间"
    print("[PASS] normalize_location 前缀匹配正确")

def test_dijkstra_distance():
    config = ConfigLoader(CONFIG_DIR)
    # 同一建筑物内房间距离为 0
    assert config.get_distance("书房", "餐厅") == 0, "同一建筑内房间应为 0"
    assert config.get_distance("主卧", "厨房") == 0, "同一建筑内房间应为 0"
    assert config.get_distance("秀吉房间", "书房") == 2, "秀吉房间(别馆)到书房(本馆)应为 2"
    # 独立地点
    assert config.get_distance("本馆", "港口") == 4, "本馆到港口应为 4"
    assert config.get_distance("庭院", "港口") == 3, "庭院到港口应为 3"
    # 自身到自身
    assert config.get_distance("书房", "书房") == 0
    print("[PASS] Dijkstra 距离计算正确")

if __name__ == "__main__":
    test_door_init()
    test_master_key()
    test_can_enter()
    test_auto_acquire_key()
    test_lock_unlock()
    test_broken_door()
    test_normalize_location()
    test_dijkstra_distance()
    print("\n所有门锁系统测试通过！")
