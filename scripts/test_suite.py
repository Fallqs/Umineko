#!/usr/bin/env python3
"""《海猫鸣泣之时》重构后完整测试套件

用法:
    python scripts/test_suite.py [-v]
"""

import argparse
import asyncio
import json
import random
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.config_loader import ConfigLoader
from orchestrator.state import GameState
from orchestrator.action_engine import ActionEngine, ParsedAction
from orchestrator.core import Orchestrator
from orchestrator.network import NetworkLayer, SeatConnection


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------

def make_orchestrator() -> Orchestrator:
    root = Path(__file__).resolve().parent.parent
    return Orchestrator(root, mock_mode=True, test_mode=True, max_day=1)


# ---------------------------------------------------------------------------
# 单元测试
# ---------------------------------------------------------------------------

def test_config_time_slots():
    orch = make_orchestrator()
    slots = orch.config.get_time_slot_list()
    assert "DAWN" in slots
    assert "MORNING" in slots
    assert "NOON" in slots
    assert "AFTERNOON" in slots
    assert "EVENING" in slots
    assert "MIDNIGHT" in slots
    assert "MORNING_1" not in slots
    assert "MORNING_2" not in slots
    assert len(slots) == 10
    print("  [PASS] config/time_slots.json")


def test_config_action_ranges():
    orch = make_orchestrator()
    assert orch.config.get_action_range("speech") == 0
    assert orch.config.get_action_range("shout") == 1
    assert orch.config.get_action_range("shoot") == 2
    assert orch.config.get_action_range("threaten") == 2
    assert orch.config.get_action_range("comfort") == 0
    assert orch.config.get_action_range("nonexistent") == 0
    print("  [PASS] config/action_ranges")


def test_parsed_action_fields():
    pa = ParsedAction()
    assert hasattr(pa, "move_target")
    assert hasattr(pa, "shout_text")
    assert hasattr(pa, "hide_in")
    assert hasattr(pa, "leave_hideout")
    assert not hasattr(pa, "next_move")
    assert not hasattr(pa, "toggle_corpse_visibility")
    assert not hasattr(pa, "toggle_corpse_target")
    print("  [PASS] ParsedAction fields")


def test_parse_move():
    orch = make_orchestrator()
    cases = [
        ("我移动到书房。", "书房"),
        ("前往餐厅", "餐厅"),
        ("去庭院", "庭院"),
        ("走向港口", "港口"),
    ]
    for text, expected in cases:
        parsed = orch.action_engine.parse(text)
        assert parsed.move_target == expected, f"'{text}' -> expected {expected}, got {parsed.move_target}"
    print("  [PASS] parse move_target")


def test_parse_shout():
    orch = make_orchestrator()
    text = '我对着窗外大喊：<shout>有人吗！</shout> 然后静静等待回应。'
    parsed = orch.action_engine.parse(text)
    assert parsed.shout_text == "有人吗！", f"got {parsed.shout_text}"
    print("  [PASS] parse shout_text")


def test_parse_hide():
    orch = make_orchestrator()
    cases = [
        ("我躲进了大衣柜", "大衣柜"),
        ("藏到书柜后面", "书柜后面"),
    ]
    for text, expected in cases:
        parsed = orch.action_engine.parse(text)
        assert parsed.hide_in == expected, f"'{text}' -> expected {expected}, got {parsed.hide_in}"
    print("  [PASS] parse hide_in")


def test_parse_leave_hideout():
    orch = make_orchestrator()
    assert orch.action_engine.parse("我从藏身处出来了").leave_hideout is True
    assert orch.action_engine.parse("离开藏身处").leave_hideout is True
    assert orch.action_engine.parse("我调查了房间").leave_hideout is False
    print("  [PASS] parse leave_hideout")


def test_state_hiding():
    state = GameState()
    state.alive_roles.add("战人")
    state.locations["战人"] = "书房"
    state.item_registry["wardrobe_书房"] = {
        "id": "wardrobe_书房", "name": "大衣柜",
        "is_hiding_spot": True, "location": "书房", "hiding_capacity": 2,
    }

    # 进入藏匿
    assert state.hide_in("战人", "wardrobe_书房") is True
    assert state.is_hidden("战人") is True
    assert "战人" in state.hiding_spot_occupants["wardrobe_书房"]

    # 可见性
    visible = state.get_visible_roles_at("书房")
    assert "战人" not in visible

    # 离开藏匿
    assert state.leave_hiding_spot("战人") is True
    assert state.is_hidden("战人") is False
    assert "wardrobe_书房" not in state.hiding_spot_occupants
    print("  [PASS] state hiding system")


def test_state_hiding_capacity():
    state = GameState()
    state.item_registry["spot"] = {
        "id": "spot", "name": "小柜子",
        "is_hiding_spot": True, "location": "书房", "hiding_capacity": 1,
    }
    state.alive_roles.add("A")
    state.alive_roles.add("B")
    assert state.hide_in("A", "spot") is True
    assert state.hide_in("B", "spot") is False  # 已满
    print("  [PASS] hiding capacity limit")


def test_broadcast_distance():
    orch = make_orchestrator()
    state = orch.state
    state.alive_roles.add("战人")
    state.alive_roles.add("让治")
    state.locations["战人"] = "书房"
    state.locations["让治"] = "神社"  # 距离3

    # range=0 不同地点不可见
    assert orch.action_engine._is_within_range("战人", "让治", 0) is False
    # range=3 可见
    assert orch.action_engine._is_within_range("战人", "让治", 3) is True
    # 同地点总是可见
    state.locations["让治"] = "书房"
    assert orch.action_engine._is_within_range("战人", "让治", 0) is True
    print("  [PASS] broadcast distance")


def test_token_ring_signature():
    import inspect
    orch = make_orchestrator()
    sig = inspect.signature(orch.token_ring.run)
    params = list(sig.parameters.keys())
    assert params == ["players", "slot", "rounds"], f"got {params}"
    print("  [PASS] token_ring.run signature")


def test_location_engine_no_resolve_moves():
    orch = make_orchestrator()
    assert not hasattr(orch.location_engine, "resolve_pending_moves")
    print("  [PASS] location_engine.resolve_pending_moves removed")


# ---------------------------------------------------------------------------
# 集成测试: 完整一天
# ---------------------------------------------------------------------------

async def test_full_day_mock():
    """用 mock 客户端跑完第一天所有时间槽。"""
    root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(root, mock_mode=True, test_mode=True, max_day=1, min_seats=3)

    # 启动 orchestrator 服务器
    await orch.start()
    await asyncio.sleep(0.5)

    events = asyncio.Queue()
    clients = []

    async def mock_client(seat_id: str, role_name: str):
        reader, writer = await asyncio.open_connection(orch.host, orch.port)
        writer.write((json.dumps({
            "type": "register",
            "seat_id": seat_id,
            "role_name": role_name,
        }, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        await events.put((seat_id, "registered"))

        try:
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5.0)
                if not line:
                    break
                msg = json.loads(line.decode("utf-8").strip())
                msg_type = msg.get("type")

                if msg_type == "turn_token":
                    location = msg.get("location", "本馆")
                    actions = [
                        f"我环顾{location}四周，\"这里似乎有些不对劲。\"",
                        f"我调查了{location}，发现了一些痕迹。",
                        f"<shout>有人吗！</shout>",
                        f"我移动到：{random.choice(['本馆', '书房', '庭院'])}",
                    ]
                    action_text = random.choice(actions)
                    resp = {
                        "type": "action",
                        "seat_id": seat_id,
                        "parent_id": msg.get("id"),
                        "action_text": action_text,
                        "id": f"action_{seat_id}_{random.randint(1000,9999)}",
                    }
                    writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                    await writer.drain()

                elif msg_type == "notification":
                    pass  # ignore

        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    # 启动3个mock客户端
    seats = [("P1", "右代宫战人"), ("P2", "右代宫朱志香"), ("P3", "嘉音")]
    for sid, role in seats:
        clients.append(asyncio.create_task(mock_client(sid, role)))

    # 等待游戏开始
    registered = 0
    try:
        while registered < 3:
            ev = await asyncio.wait_for(events.get(), timeout=10.0)
            if ev[1] == "registered":
                registered += 1
                print(f"  [TEST] {ev[0]} registered ({registered}/3)")
    except asyncio.TimeoutError:
        print("  [FAIL] Timeout waiting for registration")
        await orch.stop()
        return False

    # 等待游戏跑完第一天
    print("  [TEST] Waiting for Day 1 to complete...")
    try:
        # 等待足够时间让第一天跑完
        await asyncio.sleep(25.0)
    except asyncio.TimeoutError:
        pass

    # 验证状态
    day = orch.state.day
    phase = orch.state.phase
    print(f"  [TEST] Final state: Day {day}, Phase {phase}")

    await orch.stop()
    for c in clients:
        c.cancel()
        try:
            await c
        except asyncio.CancelledError:
            pass

    # 至少应该推进到某个非DAWN阶段
    if orch.state.day <= 1 and orch.state.phase == "DAWN":
        print("  [FAIL] Game did not advance")
        return False

    print("  [PASS] full day mock run")
    return True


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

UNIT_TESTS = [
    test_config_time_slots,
    test_config_action_ranges,
    test_parsed_action_fields,
    test_parse_move,
    test_parse_shout,
    test_parse_hide,
    test_parse_leave_hideout,
    test_state_hiding,
    test_state_hiding_capacity,
    test_broadcast_distance,
    test_token_ring_signature,
    test_location_engine_no_resolve_moves,
]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    passed = 0
    failed = 0

    print("=" * 60)
    print("Unit Tests")
    print("=" * 60)
    for test_fn in UNIT_TESTS:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  [FAIL] {test_fn.__name__}: {e}")
            if args.verbose:
                traceback.print_exc()

    print()
    print("=" * 60)
    print("Integration Test: Full Day Mock Run")
    print("=" * 60)
    try:
        ok = await test_full_day_mock()
        if ok:
            passed += 1
        else:
            failed += 1
    except Exception as e:
        failed += 1
        print(f"  [FAIL] test_full_day_mock: {e}")
        if args.verbose:
            traceback.print_exc()

    print()
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
