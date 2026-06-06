#!/usr/bin/env python3
"""集成测试：在同一进程中启动orchestrator + mock clients"""

import asyncio
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.core import Orchestrator


async def mock_client(seat_id: str, role_name: str, host: str, port: int, events: asyncio.Queue):
    reader, writer = await asyncio.open_connection(host, port)
    writer.write((json.dumps({
        "type": "register", "seat_id": seat_id, "role_name": role_name,
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
            await events.put((seat_id, f"recv:{msg_type}"))

            if msg_type == "turn_token":
                await asyncio.sleep(0.1)
                location = msg.get("location", "本馆")
                actions = [
                    f"我调查了{location}，发现了一些痕迹。",
                    f"我在{location}四处张望。",
                    f"我决定在{location}静观其变。",
                ]
                action_text = random.choice(actions)
                resp = {
                    "type": "action", "seat_id": seat_id,
                    "parent_id": msg.get("id"),
                    "action_text": action_text,
                    "id": f"action_{seat_id}_{random.randint(1000,9999)}",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                await events.put((seat_id, "sent:action"))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        await events.put((seat_id, f"error:{e}"))
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(
        root_dir=root,
        host="127.0.0.1",
        port=9123,
        mock_mode=True,
        min_seats=2,
        max_day=1,
    )

    events = asyncio.Queue()

    # 启动server
    await orch.start()
    print("[Test] Orchestrator started")

    # 启动mock clients（覆盖所有seat，避免NPC启动）
    clients = []
    seats = [
        ("P1", "右代宫战人"),
        ("P2", "右代宫朱志香"),
        ("P3", "右代宫让治"),
        ("P4", "右代宫真里亚"),
        ("P5", "嘉音"),
        ("P6", "纱音"),
        ("P7", "右代宫秀吉"),
    ]
    for seat_id, role in seats:
        task = asyncio.create_task(mock_client(seat_id, role, "127.0.0.1", 9123, events))
        clients.append(task)

    # 等待游戏结束或超时
    try:
        await asyncio.wait_for(orch.server._shutdown_event.wait(), timeout=120)
    except asyncio.CancelledError:
        print("[Test] Timeout waiting for game end")

    # 取消clients
    for task in clients:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await orch.stop()

    # 打印事件日志
    print("\n[Test] Event log:")
    event_list = []
    while not events.empty():
        event_list.append(await events.get())
    for seat_id, event in event_list:
        print(f"  [{seat_id}] {event}")

    # 检查关键事件
    registered = [e for e in event_list if e[1] == "registered"]
    actions_sent = [e for e in event_list if e[1] == "sent:action"]
    print(f"\n[Test] Registered: {len(registered)}, Actions sent: {len(actions_sent)}")

    if len(registered) >= 2 and len(actions_sent) >= 10:
        print("[Test] PASSED")
    else:
        print("[Test] FAILED")


if __name__ == "__main__":
    asyncio.run(main())
