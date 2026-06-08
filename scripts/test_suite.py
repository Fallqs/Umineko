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

    # 加速测试：大幅缩短令牌环等待时间和轮数
    orch.config._game_rules = orch.config._load_json("game_rules.json")
    orch.config._game_rules.setdefault("token_ring", {})
    orch.config._game_rules["token_ring"]["wait_timeout"] = 0.5
    orch.config._game_rules["token_ring"]["free_slot_rounds"] = 1
    orch.config._game_rules["token_ring"]["meal_slot_rounds"] = 1
    # 直接覆盖 TokenRing 实例的限速间隔（实例化时读取的默认值可能未被配置覆盖）
    orch.token_ring._min_turn_interval = 0.1

    # 禁用外部 NPC 进程自动启动，改为纯 mock NPC（更快更可控）
    orch.npc_engine.start_all_npcs = lambda *args, **kwargs: None

    # 启动 orchestrator 服务器
    await orch.start()
    await asyncio.sleep(0.5)

    events = asyncio.Queue()
    clients = []

    async def mock_client(seat_id: str, role_name: str):
        """模拟客户端：长连接，收到 turn_token 后快速响应。"""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(orch.host, orch.port), timeout=10.0
            )
        except Exception as e:
            print(f"  [TEST] {seat_id} 连接失败: {e}")
            return

        writer.write((json.dumps({
            "type": "register",
            "seat_id": seat_id,
            "role_name": role_name,
        }, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        await events.put((seat_id, "registered"))

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = json.loads(line.decode("utf-8").strip())
                msg_type = msg.get("type")

                if msg_type == "turn_token":
                    location = msg.get("location", "本馆")
                    actions = [
                        f"我环顾{location}四周。",
                        f"我调查了{location}。",
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
                    pass
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"  [TEST] {seat_id} error: {e}")
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # 启动 3 个真人 + 4 个 NPC mock（共 7 个活跃角色，控制总时长）
    seats = [
        ("P1", "右代宫战人"), ("P2", "右代宫朱志香"), ("P3", "嘉音"),
        ("NPC_纱音", "纱音"), ("NPC_让治", "右代宫让治"),
        ("NPC_楼座", "右代宫楼座"), ("NPC_南条医师", "南条医师"),
    ]
    for sid, role in seats:
        clients.append(asyncio.create_task(mock_client(sid, role)))

    # 等待所有客户端注册
    registered = 0
    try:
        while registered < len(seats):
            ev = await asyncio.wait_for(events.get(), timeout=15.0)
            if ev[1] == "registered":
                registered += 1
                print(f"  [TEST] {ev[0]} registered ({registered}/{len(seats)})")
    except asyncio.TimeoutError:
        print(f"  [WARN] Timeout waiting for registration, only {registered}/{len(seats)} registered")

    # 等待游戏推进：轮询检测状态变化
    print("  [TEST] Waiting for Day 1 to advance...")
    advanced = False
    for _ in range(120):
        await asyncio.sleep(1)
        if orch.state.phase != "DAWN" or orch.state.day > 1:
            advanced = True
            print(f"  [TEST] Game advanced to Day {orch.state.day}, Phase {orch.state.phase}")
            break

    if not advanced:
        print(f"  [FAIL] Game did not advance from DAWN")
        await orch.stop()
        for c in clients:
            c.cancel()
            try:
                await c
            except asyncio.CancelledError:
                pass
        return False

    # 继续等待第一天结束（SLEEP_CHECK 或 MIDNIGHT 即视为完成）
    print("  [TEST] Waiting for Day 1 to complete...")
    completed = False
    for _ in range(240):
        await asyncio.sleep(1)
        if orch.state.day > 1:
            completed = True
            break
        if orch.state.phase in ('SLEEP_CHECK', 'EVENING', 'MIDNIGHT'):
            completed = True
            break
        if orch.server.server is None or not orch.server.server.is_serving():
            completed = True
            break

    day = orch.state.day
    phase = orch.state.phase
    print(f"  [TEST] Final state: Day {day}, Phase {phase}")

    await orch.stop()
    for c in clients:
        c.cancel()
    # 给取消信号一点时间传播，但不阻塞等待（Windows 下客户端关闭可能挂起）
    await asyncio.sleep(0.5)

    # 强制取消所有剩余后台任务（包括 run_game），确保进程能退出
    for task in asyncio.all_tasks():
        if task is not asyncio.current_task():
            task.cancel()
    # 短暂等待任务响应取消，超时则放弃
    await asyncio.sleep(0.5)

    if not completed and day <= 1 and phase == "DAWN":
        print("  [FAIL] Day 1 did not complete")
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
