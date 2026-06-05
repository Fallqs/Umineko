#!/usr/bin/env python3
"""
消息收件箱查看器

帮助玩家查看自己角色收到的消息。可以实时监听新消息或查看历史消息。

用法:
    python inbox-viewer.py --character 右代宫战人 [--watch]
    python inbox-viewer.py --character GM --watch
"""

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

# 类型颜色映射
TYPE_COLORS = {
    "say": "\033[36m",        # 青色
    "whisper": "\033[35m",    # 紫色
    "action": "\033[32m",     # 绿色
    "gm_order": "\033[31m",   # 红色
    "npc_inject": "\033[33m", # 黄色
    "system": "\033[37m",     # 白色
    "SWITCH": "\033[41m\033[37m", # 白字红底
    "thought": "\033[90m",    # 灰色
}
RESET = "\033[0m"


def colorize(msg_type: str, text: str) -> str:
    color = TYPE_COLORS.get(msg_type, "")
    return f"{color}{text}{RESET}" if color else text


def format_message(data: dict) -> str:
    """格式化单条消息为可读文本"""
    ts = data.get("timestamp", "?")[11:19]  # 只取 HH:MM:SS
    from_ = data.get("from", "?")
    to = data.get("to", "?")
    msg_type = data.get("type", "?")
    content = data.get("content", "")
    day = data.get("day", 0)
    scene = data.get("scene", "?")

    header = f"[{ts}] Day{day}@{scene} | {from_} → {to}"
    type_tag = f"[{msg_type}]"

    lines = [
        colorize(msg_type, f"{'='*60}"),
        colorize(msg_type, f"{header:50s} {type_tag}"),
        colorize(msg_type, f"{'-'*60}"),
    ]

    # 处理内容中的换行
    for line in content.split("\n"):
        lines.append(f"  {line}")

    lines.append(colorize(msg_type, f"{'='*60}"))
    return "\n".join(lines)


def read_messages(inbox_dir: Path, character: str, since: float = 0) -> list:
    """读取某角色的消息"""
    char_dir = inbox_dir / character
    if not char_dir.exists():
        return []

    messages = []
    for filepath in sorted(char_dir.glob("*.json")):
        mtime = filepath.stat().st_mtime
        if mtime < since:
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            data["_filepath"] = str(filepath)
            data["_mtime"] = mtime
            messages.append(data)
        except Exception:
            continue

    return messages


def watch_inbox(inbox_dir: Path, character: str, poll_interval: float = 1.0):
    """实时监听新消息"""
    char_dir = inbox_dir / character
    if not char_dir.exists():
        print(f"[inbox] 创建收件箱: {char_dir}")
        char_dir.mkdir(parents=True, exist_ok=True)

    print(f"[inbox] 正在监听 {character} 的收件箱...")
    print(f"[inbox] 按 Ctrl+C 停止\n")

    seen = set()
    last_check = time.time()

    while True:
        messages = read_messages(inbox_dir, character, since=0)
        for msg in messages:
            fp = msg.get("_filepath", "")
            if fp not in seen:
                seen.add(fp)
                print(format_message(msg))
                print()

        time.sleep(poll_interval)


def show_history(inbox_dir: Path, character: str, limit: int = 50):
    """显示历史消息"""
    messages = read_messages(inbox_dir, character, since=0)
    messages = messages[-limit:]

    if not messages:
        print(f"[inbox] {character} 暂无消息")
        return

    print(f"[inbox] {character} 的历史消息（最近 {len(messages)} 条）：\n")
    for msg in messages:
        print(format_message(msg))
        print()


def main():
    parser = argparse.ArgumentParser(description="消息收件箱查看器")
    parser.add_argument("--character", required=True, help="角色名")
    parser.add_argument("--inbox-dir", default="../shared/inbox", help="收件箱根目录")
    parser.add_argument("--watch", action="store_true", help="实时监听新消息")
    parser.add_argument("--limit", type=int, default=50, help="历史消息数量限制")
    parser.add_argument("--clear", action="store_true", help="清空该角色的收件箱")

    args = parser.parse_args()

    inbox_dir = Path(args.inbox_dir).resolve()

    if args.clear:
        char_dir = inbox_dir / args.character
        if char_dir.exists():
            for f in char_dir.glob("*.json"):
                f.unlink()
            print(f"[inbox] {args.character} 的收件箱已清空")
        return

    if args.watch:
        try:
            watch_inbox(inbox_dir, args.character)
        except KeyboardInterrupt:
            print("\n[inbox] 停止监听")
    else:
        show_history(inbox_dir, args.character, args.limit)


if __name__ == "__main__":
    main()
