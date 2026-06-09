#!/usr/bin/env python3
"""Mock seat agent for testing orchestrator TCP flow (v2, 适配全局序列+即时移动+距离广播+藏匿)."""

import argparse
import asyncio
import json
import random


LOCATIONS = ["本馆", "别馆", "玫瑰园", "庭院", "书房", "餐厅", "厨房", "客房", "神社", "港口"]
HIDING_SPOTS = ["大衣柜"]  # 简化版，只按名称匹配


def safe_print(text: str) -> None:
    """安全打印，处理Windows终端编码问题。"""
    try:
        print(text)
    except UnicodeEncodeError:
        try:
            print(text.encode("gbk", "replace").decode("gbk"))
        except Exception:
            pass


async def mock_seat(seat_id: str, role_name: str, host: str, port: int, mode: str = "auto"):
    reader, writer = await asyncio.open_connection(host, port)

    # Register
    writer.write((json.dumps({
        "type": "register",
        "seat_id": seat_id,
        "role_name": role_name,
    }, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()

    safe_print(f"[{seat_id}] Registered as role={role_name!r}")

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
            safe_print(f"[{seat_id}] <- {msg_type} {msg.get('id', '')}")

            if msg_type == "turn_token":
                await asyncio.sleep(0.2)
                location = msg.get("location", "本馆")
                nearby = msg.get("nearby_players", [])
                investigations_remaining = msg.get("investigations_remaining", 0)

                # 构建智能mock行动
                choices = []

                # 基础发言
                speeches = [
                    f"我环顾{location}，感觉气氛有些紧张。",
                    f"\"这里似乎有些不对劲...\" 我低声说道。",
                    f"我仔细观察着{location}的每个角落。",
                ]
                if nearby:
                    speeches.append(f"\"{'、'.join(nearby)}，你们觉得呢？\"")
                choices.append(("speech", random.choice(speeches)))

                # 偶尔大喊（range=1）
                if random.random() < 0.15:
                    choices.append(("shout", f"<shout>有人在吗！</shout>"))

                # 调查/移动/互动（如果还有调查次数）
                if investigations_remaining > 0:
                    if random.random() < 0.4:
                        choices.append(("investigate", f"我仔细调查了{location}的每个角落，发现了一些有趣的痕迹。"))
                    if random.random() < 0.25:
                        target = random.choice([l for l in LOCATIONS if l != location])
                        choices.append(("move", f"我快步走向{target}。\n移动到：{target}"))
                    if random.random() < 0.15:
                        choices.append(("hide", f"我迅速躲进了大衣柜。"))
                    if random.random() < 0.1:
                        choices.append(("pickup", "我捡起地上的物品，仔细检查。"))

                # 组合1-3个行动
                num_actions = random.randint(1, min(3, len(choices)))
                selected = random.sample(choices, num_actions)

                action_parts = []
                for action_type, text in selected:
                    action_parts.append(text)

                action_text = "\n".join(action_parts)

                resp = {
                    "type": "action",
                    "seat_id": seat_id,
                    "parent_id": msg.get("id"),
                    "action_text": action_text,
                    "id": f"action_{seat_id}_{random.randint(1000,9999)}",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                safe_print(f"[{seat_id}] -> action ({len(selected)} parts)")

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
                safe_print(f"[{seat_id}] -> gm_output")

            elif msg_type == "action_review_result":
                result = msg.get("result")
                safe_print(f"[{seat_id}] Review result: {result} - {msg.get('reason', '')[:60]}")

            elif msg_type == "notification":
                safe_print(f"[{seat_id}] Notification: {msg.get('title')} - {msg.get('body')[:80]}")

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
    safe_print("[BEATRICE] Registered")

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
            safe_print(f"[BEATRICE] <- {msg_type} {msg.get('id', '')}")

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
                    "text": f"<result>{result}</result>\n<reason>{reason}</reason>",
                    "id": msg.get("id"),
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
                safe_print(f"[BEATRICE] -> action_review_result: {result}")

            elif msg_type == "turn_token":
                # BEATRICE也参与全局令牌环
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
                safe_print("[BEATRICE] -> action")

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
