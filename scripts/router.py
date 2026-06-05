#!/usr/bin/env python3
"""
《海猫鸣泣之时：六轩岛黄昏》消息路由器

支持两种模式：
1. local: 基于文件系统的消息队列（单机或共享文件夹）
2. server: WebSocket中心服务器（多设备联机）

用法:
    python router.py --mode local [--inbox-dir ../shared/inbox]
    python router.py --mode server --host 0.0.0.0 --port 8765
"""

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

# 角色列表（根据角色切换版设定）
ALL_CHARACTERS = [
    "GM",
    "ALL",
    "右代宫战人",
    "右代宫朱志香",
    "右代宫夏妃",
    "右代宫藏臼",
    "右代宫让治",
    "右代宫雾江",
    "右代宫留弗夫",
    "右代宫真里亚",
    "右代宫楼座",
    "右代宫秀吉",
    "嘉音",
    "乡田",
    "纱音",
    "熊泽",
    "南条医师",
    "贝阿朵莉切",
    "右代宫金藏",
]

# 场景列表
SCENES = [
    "港口",
    "本馆",
    "别馆",
    "神社",
    "庭院",
    "地下密室",
    "玫瑰园",
    "镇守之森",
    "餐厅",
    "书房",
    "客房",
]


class Message:
    """消息对象"""

    def __init__(self, data: dict):
        self.from_ = data.get("from", "UNKNOWN")
        self.to = data.get("to", "ALL")
        self.type = data.get("type", "say")
        self.content = data.get("content", "")
        self.timestamp = data.get("timestamp", datetime.now().isoformat())
        self.day = data.get("day", 0)
        self.scene = data.get("scene", "未知")
        self.require_approval = data.get("require_approval", False)
        self.meta = data.get("meta", {})
        self.raw = data

    def to_dict(self) -> dict:
        return {
            "from": self.from_,
            "to": self.to,
            "type": self.type,
            "content": self.content,
            "timestamp": self.timestamp,
            "day": self.day,
            "scene": self.scene,
            "require_approval": self.require_approval,
            "meta": self.meta,
        }

    def filename(self) -> str:
        ts = self.timestamp.replace(":", "-").replace(".", "-")
        return f"{ts}_{self.from_}_{self.to}_{self.type}.json"


class LocalRouter:
    """
    本地文件系统路由器。
    
    工作原理：
    1. 所有进程将消息写入 inbox/outbox/ 目录
    2. 路由器扫描 outbox/ 中的新消息
    3. 根据消息的目标（to）分发给对应的 inbox/{target}/ 子目录
    4. 广播消息（to=ALL）复制到所有存活角色的收件箱
    
    目录结构：
        inbox/
            outbox/     # 临时投递区（所有进程写入这里）
            GM/         # GM收到的消息
            右代宫战人/ # 战人收到的消息
            ...
    """

    def __init__(self, inbox_dir: str, poll_interval: float = 0.5):
        self.inbox_dir = Path(inbox_dir).resolve()
        self.outbox_dir = self.inbox_dir / "outbox"
        self.poll_interval = poll_interval
        self.processed = set()
        self.running = False

        # 确保目录存在
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        for char in ALL_CHARACTERS:
            (self.inbox_dir / char).mkdir(exist_ok=True)

        print(f"[LocalRouter] 启动")
        print(f"  收件箱根目录: {self.inbox_dir}")
        print(f"  临时投递区: {self.outbox_dir}")
        print(f"  轮询间隔: {poll_interval}s")

    def get_alive_characters(self) -> List[str]:
        """从游戏状态读取存活角色列表"""
        game_state_path = self.inbox_dir.parent / "game_state.json"
        if not game_state_path.exists():
            return ALL_CHARACTERS[2:]  # 排除 GM, ALL
        try:
            with open(game_state_path, "r", encoding="utf-8") as f:
                state = json.load(f)
            return state.get("characters_alive", ALL_CHARACTERS[2:])
        except Exception:
            return ALL_CHARACTERS[2:]

    def route_message(self, msg: Message) -> List[str]:
        """将消息路由到目标收件箱，返回成功投递的目标列表"""
        delivered = []
        targets = []

        if msg.to == "ALL":
            # 广播给所有存活角色 + GM
            targets = ["GM"] + self.get_alive_characters()
        elif msg.to == "GM":
            targets = ["GM"]
        else:
            targets = [msg.to]

        for target in targets:
            target_dir = self.inbox_dir / target
            if not target_dir.exists():
                target_dir.mkdir(exist_ok=True)

            filepath = target_dir / msg.filename()
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(msg.to_dict(), f, ensure_ascii=False, indent=2)
                delivered.append(target)
            except Exception as e:
                print(f"[LocalRouter] 投递失败 {target}: {e}")

        return delivered

    def scan_outbox(self) -> List[Path]:
        """扫描 outbox 中的新消息文件"""
        if not self.outbox_dir.exists():
            return []

        files = sorted(self.outbox_dir.glob("*.json"))
        new_files = [f for f in files if f.name not in self.processed]
        return new_files

    def process_file(self, filepath: Path) -> Optional[Message]:
        """处理单个消息文件"""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            msg = Message(data)
            delivered = self.route_message(msg)
            print(f"[LocalRouter] [{msg.type}] {msg.from_} → {msg.to} "
                  f"(scene={msg.scene}, day={msg.day}) | 投递到: {delivered}")
            return msg
        except json.JSONDecodeError as e:
            print(f"[LocalRouter] JSON解析失败 {filepath}: {e}")
            return None
        except Exception as e:
            print(f"[LocalRouter] 处理失败 {filepath}: {e}")
            return None

    def run_once(self):
        """执行一轮扫描和路由"""
        new_files = self.scan_outbox()
        for filepath in new_files:
            self.process_file(filepath)
            self.processed.add(filepath.name)
            # 可选：处理完后移动到归档目录
            # archived = self.inbox_dir / "archived" / filepath.name
            # archived.parent.mkdir(exist_ok=True)
            # filepath.rename(archived)

    async def run(self):
        """持续运行路由器"""
        self.running = True
        print("[LocalRouter] 开始轮询消息...")
        while self.running:
            self.run_once()
            await asyncio.sleep(self.poll_interval)

    def stop(self):
        self.running = False


class ServerRouter:
    """
    WebSocket中心服务器路由器（多设备联机模式）。
    
    工作原理：
    1. 启动WebSocket服务器
    2. 各设备上的角色进程通过WebSocket连接
    3. 消息通过服务器中转
    
    协议：
    - 连接时发送: {"cmd": "register", "character": "角色名", "player_id": "P1"}
    - 发送消息: {"cmd": "send", "to": "目标", "type": "say", "content": "..."}
    - 接收消息: 服务器推送到客户端
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.clients: Dict[str, object] = {}  # character -> websocket
        self.player_map: Dict[str, str] = {}  # character -> player_id
        self.message_history: List[Message] = []

    async def handle_client(self, websocket, path):
        """处理WebSocket连接"""
        character = None
        try:
            async for message in websocket:
                data = json.loads(message)
                cmd = data.get("cmd")

                if cmd == "register":
                    character = data.get("character")
                    player_id = data.get("player_id", "UNKNOWN")
                    if character:
                        self.clients[character] = websocket
                        self.player_map[character] = player_id
                        print(f"[ServerRouter] 注册: {character} (player={player_id})")
                        await websocket.send(json.dumps({
                            "cmd": "registered",
                            "character": character,
                            "status": "ok"
                        }, ensure_ascii=False))

                elif cmd == "send":
                    msg = Message({
                        "from": character or data.get("from", "UNKNOWN"),
                        "to": data.get("to", "ALL"),
                        "type": data.get("type", "say"),
                        "content": data.get("content", ""),
                        "timestamp": datetime.now().isoformat(),
                        "day": data.get("day", 0),
                        "scene": data.get("scene", "未知"),
                        "require_approval": data.get("require_approval", False),
                        "meta": data.get("meta", {}),
                    })
                    await self.broadcast(msg)

                elif cmd == "ping":
                    await websocket.send(json.dumps({"cmd": "pong"}))

        except Exception as e:
            print(f"[ServerRouter] 客户端异常: {e}")
        finally:
            if character and character in self.clients:
                del self.clients[character]
                print(f"[ServerRouter] 断开: {character}")

    async def broadcast(self, msg: Message):
        """广播消息到目标客户端"""
        targets = []
        if msg.to == "ALL":
            targets = list(self.clients.keys())
        else:
            targets = [msg.to]

        payload = json.dumps({
            "cmd": "message",
            "data": msg.to_dict()
        }, ensure_ascii=False)

        delivered = []
        for target in targets:
            if target in self.clients:
                try:
                    await self.clients[target].send(payload)
                    delivered.append(target)
                except Exception as e:
                    print(f"[ServerRouter] 发送失败 {target}: {e}")

        self.message_history.append(msg)
        print(f"[ServerRouter] [{msg.type}] {msg.from_} → {msg.to} "
              f"| 投递到: {delivered}")

    async def run(self):
        """启动WebSocket服务器"""
        try:
            import websockets
        except ImportError:
            print("[ServerRouter] 错误: 需要安装 websockets 库")
            print("  pip install websockets")
            sys.exit(1)

        print(f"[ServerRouter] 启动 WebSocket 服务器: ws://{self.host}:{self.port}")
        async with websockets.serve(self.handle_client, self.host, self.port):
            await asyncio.Future()  # 永久运行


def create_sample_message(sender: str, target: str, msg_type: str, content: str,
                          day: int = 1, scene: str = "港口") -> str:
    """创建示例消息文件到 outbox"""
    msg = Message({
        "from": sender,
        "to": target,
        "type": msg_type,
        "content": content,
        "timestamp": datetime.now().isoformat(),
        "day": day,
        "scene": scene,
        "require_approval": False,
        "meta": {},
    })
    return json.dumps(msg.to_dict(), ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="海猫鸣泣之时消息路由器")
    parser.add_argument("--mode", choices=["local", "server"], default="local",
                        help="运行模式: local(文件系统) 或 server(WebSocket)")
    parser.add_argument("--inbox-dir", default="../shared/inbox",
                        help="本地模式: 收件箱根目录")
    parser.add_argument("--host", default="0.0.0.0",
                        help="服务器模式: 监听地址")
    parser.add_argument("--port", type=int, default=8765,
                        help="服务器模式: 监听端口")
    parser.add_argument("--poll-interval", type=float, default=0.5,
                        help="本地模式: 轮询间隔(秒)")
    parser.add_argument("--send", action="store_true",
                        help="发送一条测试消息后退出")
    parser.add_argument("--from", dest="sender", default="GM",
                        help="测试消息发送者")
    parser.add_argument("--to", dest="target", default="ALL",
                        help="测试消息接收者")
    parser.add_argument("--type", dest="msg_type", default="system",
                        help="测试消息类型")
    parser.add_argument("--content", default="游戏开始！",
                        help="测试消息内容")

    args = parser.parse_args()

    if args.send:
        # 发送测试消息
        inbox_dir = Path(args.inbox_dir).resolve()
        outbox_dir = inbox_dir / "outbox"
        outbox_dir.mkdir(parents=True, exist_ok=True)

        msg_json = create_sample_message(
            args.sender, args.target, args.msg_type, args.content
        )
        filename = f"{datetime.now().isoformat().replace(':', '-')}_{args.sender}_{args.target}_{args.msg_type}.json"
        filepath = outbox_dir / filename
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(msg_json)
        print(f"[Test] 消息已写入: {filepath}")
        return

    if args.mode == "local":
        router = LocalRouter(args.inbox_dir, args.poll_interval)
        try:
            asyncio.run(router.run())
        except KeyboardInterrupt:
            print("\n[LocalRouter] 停止")
            router.stop()
    else:
        router = ServerRouter(args.host, args.port)
        try:
            asyncio.run(router.run())
        except KeyboardInterrupt:
            print("\n[ServerRouter] 停止")


if __name__ == "__main__":
    main()
