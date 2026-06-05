#!/usr/bin/env python3
"""
消息发送工具

快速向消息队列发送消息，无需手动编写JSON文件。

用法:
    python send-msg.py --from 右代宫战人 --to ALL --type say --content "你好"
    python send-msg.py --from GM --to 右代宫朱志香 --type gm_order --content "调查完成，你发现..."
    python send-msg.py --from 嘉音 --to 纱音 --type whisper --content "今天不要出现在餐厅"
"""

import argparse
import json
import os
from datetime import datetime
from pathlib import Path


def send_message(outbox_dir: Path, from_: str, to: str, msg_type: str,
                 content: str, day: int = 0, scene: str = "未知",
                 require_approval: bool = False, meta: dict = None):
    """发送消息到 outbox"""
    outbox_dir.mkdir(parents=True, exist_ok=True)

    msg = {
        "from": from_,
        "to": to,
        "type": msg_type,
        "content": content,
        "timestamp": datetime.now().isoformat(),
        "day": day,
        "scene": scene,
        "require_approval": require_approval,
        "meta": meta or {},
    }

    ts = msg["timestamp"].replace(":", "-").replace(".", "-")
    filename = f"{ts}_{from_}_{to}_{msg_type}.json"
    filepath = outbox_dir / filename

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(msg, f, ensure_ascii=False, indent=2)

    print(f"[send] {from_} → {to} [{msg_type}]")
    print(f"[send] 文件: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="消息发送工具")
    parser.add_argument("--from", dest="sender", required=True, help="发送者")
    parser.add_argument("--to", default="ALL", help="接收者")
    parser.add_argument("--type", default="say", help="消息类型")
    parser.add_argument("--content", required=True, help="消息内容")
    parser.add_argument("--day", type=int, default=0, help="游戏日")
    parser.add_argument("--scene", default="未知", help="场景")
    parser.add_argument("--approval", action="store_true", help="需要审批")
    parser.add_argument("--outbox-dir", default="../shared/inbox/outbox", help="outbox路径")

    args = parser.parse_args()

    outbox = Path(args.outbox_dir).resolve()
    send_message(outbox, args.sender, args.to, args.type,
                 args.content, args.day, args.scene, args.approval)


if __name__ == "__main__":
    main()
