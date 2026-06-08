#!/usr/bin/env python3
"""验证动态处境 (situation) 对 auto 模式 agent 的影响。

启动 orchestrator (mock_mode=True) + mock P1 + auto 模式嘉音(P5)，
只运行到第一个时间槽，观察嘉音的日志输出。
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator.core import Orchestrator


async def mock_client(seat_id: str, role_name: str, host: str, port: int):
    """极简 mock 客户端：注册后快速响应 turn_token。"""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=10.0
        )
    except Exception as e:
        print(f"[Verify] {seat_id} 连接失败: {e}")
        return

    writer.write((json.dumps({
        "type": "register",
        "seat_id": seat_id,
        "role_name": role_name,
    }, ensure_ascii=False) + "\n").encode("utf-8"))
    await writer.drain()

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            msg = json.loads(line.decode("utf-8").strip())
            if msg.get("type") == "turn_token":
                resp = {
                    "type": "action",
                    "seat_id": seat_id,
                    "parent_id": msg.get("id"),
                    "action_text": "我环顾四周。",
                    "id": f"action_{seat_id}_mock",
                }
                writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
                await writer.drain()
    except asyncio.CancelledError:
        pass
    except Exception:
        pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


async def main():
    root = Path(__file__).resolve().parent.parent
    orch = Orchestrator(
        root,
        mock_mode=True,
        test_mode=True,
        max_day=1,
        min_seats=2,  # P1 + P5 都注册后才启动
        active_seats=["P5"],
    )

    # 阻止 mock_mode 自动启动所有 NPC
    orch.npc_engine.start_all_npcs = lambda *a, **k: None

    await orch.start()
    await asyncio.sleep(1.5)

    # 先启动 auto 模式嘉音（P5），再启动 mock P1
    role_dir = root / "roles" / "嘉音"
    python_exe = str(Path(sys.executable).resolve())
    cmd = [
        python_exe,
        str(root / "scripts" / "agent_wrapper.py"),
        "--work-dir", str(role_dir),
        "--seat-id", "P5",
        "--orchestrator-host", "127.0.0.1",
        "--orchestrator-port", "9123",
        "--mode", "auto",
        "--yolo",
    ]
    agent_log_path = root / "shared" / "logs" / "verify_agent_P5.log"
    agent_log_path.parent.mkdir(parents=True, exist_ok=True)
    agent_log_fh = open(agent_log_path, "w", encoding="utf-8", buffering=1)
    print(f"[Verify] 启动 agent，日志 -> {agent_log_path}")
    proc = subprocess.Popen(
        cmd,
        stdout=agent_log_fh,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
    )
    await asyncio.sleep(2.5)  # 给 agent 时间完成注册

    # 启动 mock P1（战人）
    mock_task = asyncio.create_task(mock_client("P1", "右代宫战人", orch.host, orch.port))

    print("[Verify] 等待游戏推进到第一个时间槽...")
    advanced = False
    for i in range(120):
        await asyncio.sleep(1)
        if orch.state.phase != "DAWN":
            print(f"[Verify] 游戏进入 {orch.state.phase}")
            advanced = True
            break
        if proc.poll() is not None:
            print("[Verify] Agent 进程意外退出")
            break

    if advanced:
        # 给 agent 足够时间处理 turn_token（LLM 推理 + 生成行动）
        print("[Verify] 等待 agent 处理 turn_token（最多 90 秒）...")
        for i in range(90):
            await asyncio.sleep(1)
            if proc.poll() is not None:
                break
            # 检查 narrative log 是否有嘉音的行动
            narrative = root / "shared" / "logs" / "narrative.log"
            if narrative.exists():
                text = narrative.read_text(encoding="utf-8")
                if "嘉音" in text and "[ACTION]" in text:
                    print("[Verify] 检测到嘉音的行动记录")
                    break

    print("\n[Verify] 正在停止...")
    mock_task.cancel()
    try:
        await mock_task
    except asyncio.CancelledError:
        pass

    await orch.stop()
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    agent_log_fh.close()

    # 打印 agent 日志
    if agent_log_path.exists():
        print("\n=== Agent 日志 ===")
        print(agent_log_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
