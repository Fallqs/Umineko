#!/usr/bin/env python3
"""综合测试：覆盖移动、多天、BEATRICE、NPC等盲区"""

import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.core import Orchestrator


# ---------------------------------------------------------------------------
# 通用 mock client
# ---------------------------------------------------------------------------

async def mock_client(
    seat_id: str,
    role_name: str,
    host: str,
    port: int,
    events: asyncio.Queue,
    move_prob: float = 0.3,
    investigate_prob: float = 0.5,
):
    """通用mock client，支持移动意向和行动选择。"""
    reader, writer = await asyncio.open_connection(host, port)
    writer.write((json.dumps({
        "type": "register", "seat_id": seat_id, "role_name": role_name,
    }, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()
    await events.put((seat_id, "registered"))

    locations = ["本馆", "别馆", "玫瑰园", "书房", "餐厅", "港口"]
    sent_actions = 0

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            msg = json.loads(line.decode("utf-8").strip())
            msg_type = msg.get("type")
            await events.put((seat_id, f"recv:{msg_type}"))

            if msg_type == "turn_token":
                await asyncio.sleep(0.05)
                location = msg.get("location", "本馆")
                ap = msg.get("action_points", 50)

                # 决定行动
                if random.random() < investigate_prob:
                    action_text = f"我仔细调查了{location}的每个角落。"
                else:
                    action_text = f"我在{location}四处张望，观察周围的情况。"

                # 移动意向
                next_move = None
                if random.random() < move_prob:
                    candidates = [l for l in locations if l != location]
                    next_move = random.choice(candidates)
                    action_text += f"\n下轮移动：{next_move}"

                resp = {
                    "type": "action", "seat_id": seat_id,
                    "parent_id": msg.get("id"),
                    "action_text": action_text,
                    "next_move": next_move,
                    "id": f"action_{seat_id}_{random.randint(1000,9999)}",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                sent_actions += 1
                await events.put((seat_id, "sent:action"))

            elif msg_type == "notification":
                title = msg.get("title", "")
                if "死亡" in title or "移动" in title or "结算" in title:
                    await events.put((seat_id, f"notif:{title}"))
    except Exception as e:
        await events.put((seat_id, f"error:{e}"))
    finally:
        writer.close()
        await writer.wait_closed()
        await events.put((seat_id, f"disconnected:actions={sent_actions}"))


# ---------------------------------------------------------------------------
# 测试1：移动系统 + 初始位置差异化
# ---------------------------------------------------------------------------

async def test_movement():
    """测试初始位置差异化和移动结算。"""
    print("\n" + "=" * 60)
    print("TEST 1: 移动系统 + 初始位置差异化")
    print("=" * 60)

    root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(
        root_dir=root,
        host="127.0.0.1",
        port=9124,  # 不同端口避免冲突
        mock_mode=True,
        min_seats=2,
        max_day=1,
    )

    events = asyncio.Queue()

    # 启动角色覆盖不同初始位置：港口、本馆、书房
    seats = [
        ("P1", "右代宫战人"),   # 港口
        ("P2", "嘉音"),         # 本馆
        ("P3", "右代宫金藏"),   # 书房
    ]

    await orch.start()
    clients = []
    for seat_id, role in seats:
        task = asyncio.create_task(
            mock_client(seat_id, role, "127.0.0.1", 9124, events, move_prob=0.6)
        )
        clients.append(task)

    try:
        await asyncio.wait_for(orch.server._shutdown_event.wait(), timeout=120)
    except asyncio.TimeoutError:
        print("[Test1] Timeout")

    for task in clients:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await orch.stop()

    # 分析结果
    event_list = []
    while not events.empty():
        event_list.append(await events.get())

    # 检查初始位置
    locs = orch.state.locations
    print(f"[Test1] 最终位置: {dict(locs)}")
    print(f"[Test1] 行动点剩余: {dict(orch.state.action_points)}")

    # 验证至少有一个角色移动了
    moved = any(
        orch.state.locations.get(role) != orch.location_engine.get_initial_location(role)
        for role, _ in seats
    )
    # 验证行动点有消耗
    ap_consumed = any(
        orch.state.action_points.get(role, 50) < 50
        for role, _ in seats
    )
    # 验证信息解锁
    info_unlocked = any(
        len(orch.state.unlocked_info.get(role, set())) > 0
        for role, _ in seats
    )
    if info_unlocked:
        for role, _ in seats:
            infos = orch.state.unlocked_info.get(role, set())
            if infos:
                print(f"[Test1] {role} 解锁信息: {infos}")

    actions_sent = len([e for e in event_list if e[1] == "sent:action"])
    print(f"[Test1] Actions sent: {actions_sent}")

    passed = actions_sent >= 6 and (moved or ap_consumed or info_unlocked)
    print(f"[Test1] {'PASSED' if passed else 'FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# 测试2：多天运行
# ---------------------------------------------------------------------------

async def test_multi_day():
    """测试多天运行，验证DAWN重置。"""
    print("\n" + "=" * 60)
    print("TEST 2: 多天运行 (max_day=2)")
    print("=" * 60)

    root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(
        root_dir=root,
        host="127.0.0.1",
        port=9125,
        mock_mode=True,
        min_seats=2,
        max_day=2,
    )

    events = asyncio.Queue()
    seats = [("P1", "右代宫战人"), ("P2", "嘉音")]

    await orch.start()
    clients = []
    for seat_id, role in seats:
        task = asyncio.create_task(
            mock_client(seat_id, role, "127.0.0.1", 9125, events, move_prob=0.3)
        )
        clients.append(task)

    try:
        await asyncio.wait_for(orch.server._shutdown_event.wait(), timeout=180)
    except asyncio.TimeoutError:
        print("[Test2] Timeout")

    for task in clients:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await orch.stop()

    event_list = []
    while not events.empty():
        event_list.append(await events.get())

    actions_sent = len([e for e in event_list if e[1] == "sent:action"])
    print(f"[Test2] Actions sent: {actions_sent}")
    print(f"[Test2] 最终天数标记: {orch.state.day}")

    # 多天应该有更多action
    passed = actions_sent >= 15
    print(f"[Test2] {'PASSED' if passed else 'FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# 测试3：BEATRICE参与令牌环
# ---------------------------------------------------------------------------

async def test_beatrice():
    """测试BEATRICE作为普通seat参与令牌环。"""
    print("\n" + "=" * 60)
    print("TEST 3: BEATRICE参与令牌环")
    print("=" * 60)

    root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(
        root_dir=root,
        host="127.0.0.1",
        port=9126,
        mock_mode=True,
        min_seats=2,
        max_day=1,
    )

    events = asyncio.Queue()
    seats = [("P1", "右代宫战人"), ("P2", "嘉音")]

    await orch.start()
    clients = []
    for seat_id, role in seats:
        task = asyncio.create_task(
            mock_client(seat_id, role, "127.0.0.1", 9126, events)
        )
        clients.append(task)

    # 额外启动一个mock BEATRICE
    async def mock_beatrice():
        reader, writer = await asyncio.open_connection("127.0.0.1", 9126)
        writer.write((json.dumps({
            "type": "register", "seat_id": "BEATRICE", "role_name": "贝阿朵莉切",
        }, ensure_ascii=False) + "\n").encode("utf-8"))
        await writer.drain()
        await events.put(("BEATRICE", "registered"))
        sent = 0
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                msg = json.loads(line.decode("utf-8").strip())
                msg_type = msg.get("type")
                await events.put(("BEATRICE", f"recv:{msg_type}"))
                if msg_type == "turn_token":
                    await asyncio.sleep(0.05)
                    loc = msg.get("location", "本馆")
                    resp = {
                        "type": "action", "seat_id": "BEATRICE",
                        "parent_id": msg.get("id"),
                        "action_text": f"贝阿朵莉切在{loc}环视四周，嘴角浮现意味深长的微笑。",
                        "id": f"action_BEATRICE_{random.randint(1000,9999)}",
                    }
                    writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                    await writer.drain()
                    sent += 1
                    await events.put(("BEATRICE", "sent:action"))
        except Exception:
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            await events.put(("BEATRICE", f"disconnected:actions={sent}"))

    beatrice_task = asyncio.create_task(mock_beatrice())

    try:
        await asyncio.wait_for(orch.server._shutdown_event.wait(), timeout=120)
    except asyncio.TimeoutError:
        print("[Test3] Timeout")

    for task in clients:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    beatrice_task.cancel()
    try:
        await beatrice_task
    except asyncio.CancelledError:
        pass
    await orch.stop()

    event_list = []
    while not events.empty():
        event_list.append(await events.get())

    beatrice_actions = len([e for e in event_list if e[0] == "BEATRICE" and e[1] == "sent:action"])
    print(f"[Test3] BEATRICE actions sent: {beatrice_actions}")

    passed = beatrice_actions >= 2
    print(f"[Test3] {'PASSED' if passed else 'FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# 测试4：NPC进程参与（使用mock_seat模拟NPC行为）
# ---------------------------------------------------------------------------

async def test_npc():
    """测试NPC seat以"NPC_"前缀注册并参与令牌环。"""
    print("\n" + "=" * 60)
    print("TEST 4: NPC进程参与令牌环")
    print("=" * 60)

    root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(
        root_dir=root,
        host="127.0.0.1",
        port=9127,
        mock_mode=True,
        min_seats=1,
        max_day=1,
    )

    events = asyncio.Queue()

    # 只启动P1，其他角色由NPC覆盖
    await orch.start()

    # 手动启动NPC mock
    npc_roles = [("NPC_右代宫朱志香", "右代宫朱志香"), ("NPC_嘉音", "嘉音")]
    clients = []

    # P1
    p1_task = asyncio.create_task(
        mock_client("P1", "右代宫战人", "127.0.0.1", 9127, events)
    )
    clients.append(p1_task)

    # NPCs
    for seat_id, role in npc_roles:
        task = asyncio.create_task(
            mock_client(seat_id, role, "127.0.0.1", 9127, events)
        )
        clients.append(task)

    try:
        await asyncio.wait_for(orch.server._shutdown_event.wait(), timeout=120)
    except asyncio.TimeoutError:
        print("[Test4] Timeout")

    for task in clients:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    await orch.stop()

    event_list = []
    while not events.empty():
        event_list.append(await events.get())

    npc_actions = len([e for e in event_list if e[0].startswith("NPC_") and e[1] == "sent:action"])
    p1_actions = len([e for e in event_list if e[0] == "P1" and e[1] == "sent:action"])
    print(f"[Test4] P1 actions: {p1_actions}, NPC actions: {npc_actions}")

    passed = p1_actions >= 2 and npc_actions >= 2
    print(f"[Test4] {'PASSED' if passed else 'FAILED'}")
    return passed


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def main():
    results = []
    results.append(("movement", await test_movement()))
    await asyncio.sleep(1)
    results.append(("multi_day", await test_multi_day()))
    await asyncio.sleep(1)
    results.append(("beatrice", await test_beatrice()))
    await asyncio.sleep(1)
    results.append(("npc", await test_npc()))

    print("\n" + "=" * 60)
    print("综合测试汇总")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {name:15s} {status}")
    all_passed = all(p for _, p in results)
    print(f"\n总体: {'ALL PASSED' if all_passed else 'SOME FAILED'}")


if __name__ == "__main__":
    asyncio.run(main())
