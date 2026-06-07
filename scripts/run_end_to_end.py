#!/usr/bin/env python3
"""全AI玩家端到端实验：启动orchestrator + mock seats，跑完第一天。

用法:
    python scripts/run_end_to_end.py [--seats N] [--max-day D] [--timeout T]

注意：Windows上子进程直接继承stdout，避免pipe缓冲问题。
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# 默认角色池（使用英文别名避免Windows命令行编码问题）
ROLES = [
    ("P1", "Battler"),
    ("P2", "Jessica"),
    ("P3", "Kanon"),
    ("P4", "Shannon"),
    ("P5", "George"),
    ("P6", "Maria"),
    ("P7", "Kumasawa"),
]


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seats", type=int, default=5, help="mock玩家数量(不含BEATRICE)")
    parser.add_argument("--max-day", type=int, default=1, help="最大天数")
    parser.add_argument("--timeout", type=int, default=120, help="总超时时间(秒)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9123)
    args = parser.parse_args()

    seats = ROLES[:args.seats]
    min_seats = len(seats)

    print(f"[E2E] 启动端到端实验: {len(seats)} mock seats + BEATRICE, max_day={args.max_day}")

    # 启动 orchestrator（直接继承stdout，避免pipe缓冲）
    orch_cmd = [
        PYTHON, "-u", str(ROOT / "scripts" / "orchestrator.py"),
        "--mock",
        "--max-day", str(args.max_day),
        "--min-seats", str(min_seats),
        "--host", args.host,
        "--port", str(args.port),
    ]
    print(f"[E2E] Orchestrator cmd: {' '.join(orch_cmd)}")
    orch_proc = await asyncio.create_subprocess_exec(
        *orch_cmd,
        stdout=None,
        stderr=None,
        cwd=str(ROOT),
    )

    await asyncio.sleep(2)

    # 启动 mock seats（直接继承stdout）
    seat_procs = []
    for seat_id, role_name in seats:
        cmd = [
            PYTHON, "-u", str(ROOT / "scripts" / "mock_seat.py"),
            "--host", args.host,
            "--port", str(args.port),
            "--seat-id", seat_id,
            "--role-name", role_name,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=None,
            stderr=None,
            cwd=str(ROOT),
        )
        seat_procs.append((seat_id, proc))
        print(f"[E2E] Started mock seat {seat_id} ({role_name})")
        await asyncio.sleep(0.3)

    # 启动 BEATRICE（直接继承stdout）
    beatrice_cmd = [
        PYTHON, "-u", str(ROOT / "scripts" / "mock_seat.py"),
        "--host", args.host,
        "--port", str(args.port),
        "--beatrice",
    ]
    beatrice_proc = await asyncio.create_subprocess_exec(
        *beatrice_cmd,
        stdout=None,
        stderr=None,
        cwd=str(ROOT),
    )
    print("[E2E] Started BEATRICE")

    # 等待超时或 orchestrator 结束
    start = time.time()
    try:
        while time.time() - start < args.timeout:
            if orch_proc.returncode is not None:
                print(f"[E2E] Orchestrator exited with code {orch_proc.returncode}")
                break
            await asyncio.sleep(1)
        else:
            print(f"[E2E] Timeout after {args.timeout}s, killing processes...")
    finally:
        for sid, proc in seat_procs:
            if proc.returncode is None:
                proc.terminate()
        if beatrice_proc.returncode is None:
            beatrice_proc.terminate()
        if orch_proc.returncode is None:
            orch_proc.terminate()

        # 等待子进程结束
        await asyncio.sleep(2)
        for sid, proc in seat_procs:
            if proc.returncode is None:
                proc.kill()
        if beatrice_proc.returncode is None:
            beatrice_proc.kill()
        if orch_proc.returncode is None:
            orch_proc.kill()

    # 检查叙事日志文件判断游戏是否成功完成
    log_file = ROOT / "shared" / "logs" / "narrative.log"
    success = False
    if log_file.exists():
        try:
            content = log_file.read_text(encoding="utf-8")
            success_markers = ["MIDNIGHT", "Day1", "全局令牌环结束"]
            found = [m for m in success_markers if m in content]
            if found:
                success = True
                print(f"[E2E] 日志中找到成功标记: {found}")
            else:
                print(f"[E2E] 日志中未找到成功标记")
        except Exception as e:
            print(f"[E2E] 读取日志失败: {e}")
    else:
        print(f"[E2E] 日志文件不存在: {log_file}")

    print()
    print("=" * 60)
    if success:
        print(f"[E2E] SUCCESS: Day 1 completed")
    else:
        print(f"[E2E] PARTIAL: Day 1 may not have completed (check logs)")
    print(f"[E2E] Orchestrator exit code: {orch_proc.returncode}")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
