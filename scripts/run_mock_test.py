#!/usr/bin/env python3
"""一次性运行mock测试：启动orchestrator + mock seats"""

import asyncio
import subprocess
import sys
import time
from pathlib import Path


async def main():
    root = Path(__file__).resolve().parent.parent

    # 启动orchestrator（后台）
    print("[Test] Starting orchestrator...")
    orch_proc = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "orchestrator.py"),
         "--mock", "--max-day", "1", "--min-seats", "2",
         "--host", "127.0.0.1", "--port", "9123"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(root),
    )

    await asyncio.sleep(2)

    # 启动mock seats（后台）
    seats = [
        ("P1", "右代宫战人"),
        ("P2", "右代宫朱志香"),
    ]
    seat_procs = []
    for seat_id, role in seats:
        print(f"[Test] Starting mock seat {seat_id} ({role})...")
        proc = subprocess.Popen(
            [sys.executable, str(root / "scripts" / "mock_seat.py"),
             "--seat-id", seat_id, "--role-name", role,
             "--host", "127.0.0.1", "--port", "9123"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(root),
        )
        seat_procs.append((seat_id, proc))

    await asyncio.sleep(1)

    # 启动BEATRICE
    print("[Test] Starting mock BEATRICE...")
    beatrice_proc = subprocess.Popen(
        [sys.executable, str(root / "scripts" / "mock_seat.py"),
         "--beatrice",
         "--host", "127.0.0.1", "--port", "9123"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(root),
    )

    # 等待游戏结束（最多60秒）
    print("[Test] Waiting for game to finish...")
    deadline = time.monotonic() + 60
    while orch_proc.poll() is None and time.monotonic() < deadline:
        await asyncio.sleep(0.5)

    # 收集输出
    def _decode(out_bytes):
        if out_bytes is None:
            return ""
        try:
            return out_bytes.decode("utf-8", errors="replace")
        except Exception:
            return str(out_bytes)

    print("\n" + "="*60)
    print("ORCHESTRATOR OUTPUT:")
    print("="*60)
    try:
        orch_out, _ = orch_proc.communicate(timeout=15)
        print(_decode(orch_out))
    except Exception as e:
        print(f"Failed to get orchestrator output: {e}")
        orch_proc.kill()

    for seat_id, proc in seat_procs:
        print(f"\n{'='*60}")
        print(f"SEAT {seat_id} OUTPUT:")
        print("="*60)
        try:
            out, _ = proc.communicate(timeout=5)
            print(_decode(out))
        except Exception as e:
            print(f"Failed: {e}")
            proc.kill()

    print(f"\n{'='*60}")
    print("BEATRICE OUTPUT:")
    print("="*60)
    try:
        out, _ = beatrice_proc.communicate(timeout=5)
        print(_decode(out))
    except Exception as e:
        print(f"Failed: {e}")
        beatrice_proc.kill()

    print("\n[Test] Done.")


if __name__ == "__main__":
    asyncio.run(main())
