#!/usr/bin/env python3
"""Mock seat agent for testing orchestrator TCP flow."""

import argparse
import asyncio
import json
import random


async def mock_seat(seat_id: str, role_name: str, host: str, port: int, mode: str = "auto"):
    reader, writer = await asyncio.open_connection(host, port)

    # Register
    writer.write((json.dumps({
        "type": "register",
        "seat_id": seat_id,
        "role_name": role_name,
    }, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()

    print(f"[{seat_id}] Registered")

    async def read_loop():
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type")
            print(f"[{seat_id}] <- {msg_type} {msg.get('id', '')}")

            if msg_type == "turn_token":
                # 新版：收到turn_token后返回action
                await asyncio.sleep(0.2)
                location = msg.get("location", "本馆")
                actions = [
                    f"我仔细调查了{location}的每个角落，发现了一些有趣的痕迹。",
                    f"我在{location}四处张望，然后对旁边的人说：\"这里似乎有些不对劲。\"",
                    f"我决定在{location}静观其变，暂时不采取行动。",
                    f"我搜索了{location}，在角落里发现了一本旧日记。",
                ]
                action_text = random.choice(actions)
                next_move = None
                if random.random() < 0.3:
                    next_move = random.choice(["本馆", "别馆", "玫瑰园", "庭院", "书房"])
                    action_text += f'\n下轮移动：{next_move}'
                resp = {
                    "type": "action",
                    "seat_id": seat_id,
                    "parent_id": msg.get("id"),
                    "action_text": action_text,
                    "next_move": next_move,
                    "id": f"action_{seat_id}_{random.randint(1000,9999)}",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                print(f"[{seat_id}] -> action")

            elif msg_type == "scene":
                # 旧版兼容
                await asyncio.sleep(0.2)
                resp = {
                    "type": "gm_output",
                    "seat_id": seat_id,
                    "parent_id": msg.get("id"),
                    "text": f"{role_name} 观察了场景，没有发现异常。",
                    "orchestration_requests": [],
                    "id": f"gm_out_{seat_id}_{random.randint(1000,9999)}",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                print(f"[{seat_id}] -> gm_output")

            elif msg_type == "action_review_result":
                result = msg.get("result")
                print(f"[{seat_id}] Review result: {result} - {msg.get('reason', '')[:60]}")

            elif msg_type == "notification":
                print(f"[{seat_id}] Notification: {msg.get('title')} - {msg.get('body')[:80]}")

    try:
        await read_loop()
    except asyncio.CancelledError:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def mock_beatrice(host: str, port: int):
    reader, writer = await asyncio.open_connection(host, port)
    writer.write((json.dumps({
        "type": "register",
        "seat_id": "BEATRICE",
        "role_name": "贝阿朵莉切",
    }, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()
    print("[BEATRICE] Registered")

    async def read_loop():
        while True:
            line = await reader.readline()
            if not line:
                break
            try:
                msg = json.loads(line.decode("utf-8").strip())
            except json.JSONDecodeError:
                continue
            msg_type = msg.get("type")
            print(f"[BEATRICE] <- {msg_type} {msg.get('id', '')}")

            if msg_type == "action_review":
                await asyncio.sleep(0.1)
                action_text = msg.get("action_text", "")
                forbidden = ["安田纱代", "三位一体", "地下密室", "角色卡", "剧本设定"]
                result = "approve"
                reason = "行动看起来合规。"
                for word in forbidden:
                    if word in action_text:
                        result = "reject"
                        reason = f"提到了不该提前提及的内容：{word}"
                        break

                resp = {
                    "type": "action_review_result",
                    "seat_id": "BEATRICE",
                    "request_id": msg.get("id"),
                    "action_text": action_text,
                    "result": result,
                    "reason": reason,
                    "text": f"【RESULT】{result}【/RESULT】\n【REASON】{reason}【/REASON】",
                    "id": msg.get("id"),
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                print(f"[BEATRICE] -> action_review_result: {result}")

            elif msg_type == "turn_token":
                # BEATRICE也参与令牌环
                await asyncio.sleep(0.1)
                resp = {
                    "type": "action",
                    "seat_id": "BEATRICE",
                    "parent_id": msg.get("id"),
                    "action_text": "贝阿朵莉切环视四周，嘴角浮现意味深长的微笑。",
                    "id": f"action_BEATRICE_{random.randint(1000,9999)}",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                print("[BEATRICE] -> action")

            elif msg_type == "scene":
                resp = {
                    "type": "gm_output",
                    "seat_id": "BEATRICE",
                    "parent_id": msg.get("id"),
                    "text": "已同步场景状态。",
                    "orchestration_requests": [],
                    "id": f"beatrice_ack_{random.randint(1000,9999)}",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()

    try:
        await read_loop()
    except asyncio.CancelledError:
        pass
    finally:
        writer.close()
        await writer.wait_closed()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9123)
    parser.add_argument("--beatrice", action="store_true")
    parser.add_argument("--seat-id", default="P1")
    parser.add_argument("--role-name", default="右代宫战人")
    args = parser.parse_args()

    if args.beatrice:
        await mock_beatrice(args.host, args.port)
    else:
        await mock_seat(args.seat_id, args.role_name, args.host, args.port)


if __name__ == "__main__":
    asyncio.run(main())
