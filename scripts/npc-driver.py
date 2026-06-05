#!/usr/bin/env python3
"""
NPC外部驱动器示例

本脚本演示如何驱动一个kimi-code-cli NPC进程。
它通过读写agent pipe文件与NPC进程通信。

在实际游戏中，这个驱动器可以被替换为：
- 另一个LLM（如GPT-4、Claude等）
- 一个规则引擎
- 人类GM手动输入

用法:
    python npc-driver.py --npc 贝阿朵莉切 --inbox-dir ../shared/inbox
    python npc-driver.py --npc 贝阿朵莉切 --interactive
    python npc-driver.py --npc 贝阿朵莉切 --input "战人问你：金藏是怎么死的？"
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path


def write_input(pipe_path: Path, text: str, msg_id: str = None):
    """向NPC进程的pipe文件写入输入"""
    pipe_path.parent.mkdir(parents=True, exist_ok=True)
    msg = {
        "type": "input",
        "text": text,
        "id": msg_id or f"msg_{int(time.time() * 1000)}",
    }
    with open(pipe_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    print(f"[→ {pipe_path.name}] {text[:80]}...")
    return msg["id"]


def read_output(out_path: Path, last_pos: int = 0) -> tuple[list[dict], int]:
    """读取NPC进程的输出文件"""
    if not out_path.exists():
        return [], last_pos

    current_size = out_path.stat().st_size
    if current_size <= last_pos:
        return [], last_pos

    with open(out_path, "r", encoding="utf-8") as f:
        f.seek(last_pos)
        new_content = f.read()
        new_pos = f.tell()

    messages = []
    for line in new_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return messages, new_pos


def print_messages(messages: list[dict]):
    """格式化打印NPC输出"""
    for msg in messages:
        msg_type = msg.get("type", "unknown")
        if msg_type == "output":
            text = msg.get("text", "")
            tools = msg.get("tools", [])
            msg_id = msg.get("id", "")
            print(f"  [← output] (id={msg_id})")
            for line in text.split("\n"):
                print(f"      {line}")
            if tools:
                print(f"      [tools: {', '.join(tools)}]")
        elif msg_type == "status":
            phase = msg.get("phase", "?")
            msg_id = msg.get("id", "")
            print(f"  [← status] phase={phase} (id={msg_id})")


def interactive_mode(pipe_path: Path, out_path: Path):
    """交互模式：手动输入驱动NPC"""
    print(f"\n[NPC Driver] 交互模式启动")
    print(f"  Pipe输入: {pipe_path}")
    print(f"  Pipe输出: {out_path}")
    print(f"  输入 'quit' 或 'exit' 退出\n")

    last_pos = out_path.stat().st_size if out_path.exists() else 0

    while True:
        try:
            text = input("[You → NPC] ")
        except (EOFError, KeyboardInterrupt):
            break

        if text.lower() in ("quit", "exit", "q"):
            break

        if not text.strip():
            continue

        msg_id = write_input(pipe_path, text)

        # 等待并读取输出
        print("  等待NPC响应...")
        timeout = 120  # 最多等待120秒
        start = time.time()
        while time.time() - start < timeout:
            messages, last_pos = read_output(out_path, last_pos)
            if messages:
                print_messages(messages)
                # 检查是否收到了idle状态
                if any(m.get("type") == "status" and m.get("phase") == "idle" for m in messages):
                    break
            time.sleep(0.5)
        else:
            print("  [timeout] NPC未在120秒内完成响应")

    print("\n[NPC Driver] 已退出")


def auto_mode(pipe_path: Path, out_path: Path, inbox_dir: Path, npc_name: str):
    """自动模式：从消息收件箱读取场景信息，驱动NPC响应"""
    print(f"\n[NPC Driver] 自动模式启动: {npc_name}")
    print(f"  从 {inbox_dir}/{npc_name}/ 读取消息")
    print(f"  通过 {pipe_path} 驱动NPC")
    print(f"  按 Ctrl+C 退出\n")

    npc_inbox = inbox_dir / npc_name
    last_pos = out_path.stat().st_size if out_path.exists() else 0
    seen_files = set()

    try:
        while True:
            # 1. 检查NPC收件箱中的新消息
            if npc_inbox.exists():
                for msg_file in sorted(npc_inbox.glob("*.json")):
                    if msg_file.name in seen_files:
                        continue
                    seen_files.add(msg_file.name)
                    try:
                        with open(msg_file, "r", encoding="utf-8") as f:
                            msg = json.load(f)
                        content = msg.get("content", "")
                        msg_from = msg.get("from", "?")
                        msg_type = msg.get("type", "say")

                        # 构建NPC的"感知"
                        if msg_type == "say":
                            prompt = f"[{msg_from}] {content}"
                        elif msg_type == "whisper":
                            prompt = f"[{msg_from} 私下对你说] {content}"
                        elif msg_type == "gm_order":
                            prompt = f"[GM指令] {content}"
                        elif msg_type == "system":
                            prompt = f"[场景] {content}"
                        else:
                            prompt = f"[{msg_from} {msg_type}] {content}"

                        print(f"\n[→ NPC] {prompt[:100]}...")
                        write_input(pipe_path, prompt)

                    except Exception as e:
                        print(f"[warn] 处理消息失败: {e}")

            # 2. 读取NPC的输出
            messages, last_pos = read_output(out_path, last_pos)
            if messages:
                print_messages(messages)

            time.sleep(1)

    except KeyboardInterrupt:
        print("\n\n[NPC Driver] 已退出")


def main():
    parser = argparse.ArgumentParser(description="NPC外部驱动器")
    parser.add_argument("--npc", required=True, help="NPC角色名")
    parser.add_argument("--inbox-dir", default="../shared/inbox", help="收件箱根目录")
    parser.add_argument("--interactive", action="store_true", help="交互模式")
    parser.add_argument("--input", type=str, help="单次输入模式")

    args = parser.parse_args()

    inbox_dir = Path(args.inbox_dir).resolve()
    npc_inbox = inbox_dir / args.npc
    npc_inbox.mkdir(parents=True, exist_ok=True)

    pipe_path = npc_inbox / "agent_pipe.jsonl"
    out_path = npc_inbox / "agent_pipe.jsonl.out"

    if args.input:
        # 单次输入模式
        msg_id = write_input(pipe_path, args.input)
        print(f"  等待NPC响应 (id={msg_id})...")
        last_pos = out_path.stat().st_size if out_path.exists() else 0
        timeout = 120
        start = time.time()
        while time.time() - start < timeout:
            messages, last_pos = read_output(out_path, last_pos)
            if messages:
                print_messages(messages)
                if any(m.get("type") == "status" and m.get("phase") == "idle" for m in messages):
                    break
            time.sleep(0.5)
    elif args.interactive:
        interactive_mode(pipe_path, out_path)
    else:
        auto_mode(pipe_path, out_path, inbox_dir, args.npc)


if __name__ == "__main__":
    main()
