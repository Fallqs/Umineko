#!/usr/bin/env python3
"""全AI玩家端到端实验：启动orchestrator + agent_wrapper.py 驱动的真实AI seats，跑完第一天。

用法:
    python scripts/run_end_to_end.py [--seats N] [--max-day D] [--timeout T]

注意：Windows上子进程直接继承stdout，避免pipe缓冲问题。
每个AI seat由agent_wrapper.py驱动，连接真实LLM后端。
"""

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

# 强制UTF-8编码，防止Windows GBK乱码
os.environ["PYTHONIOENCODING"] = "utf-8"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass
try:
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable

# 角色池：seat_id -> 角色目录名（中文，对应 roles/ 下的文件夹）
ROLES = [
    ("P1", "右代宫战人"),
    ("P2", "右代宫朱志香"),
    ("P3", "嘉音"),
    ("P4", "纱音"),
    ("P5", "右代宫让治"),
    ("P6", "右代宫真里亚"),
    ("P7", "熊泽"),
]

# BEATRICE 角色目录
BEATRICE_ROLE = "贝阿朵莉切"


def _release_port(port: int) -> None:
    """Windows: 强制释放指定端口上所有正在监听的进程。"""
    if sys.platform != "win32":
        return
    try:
        result = subprocess.run(
            ["cmd", "/c", f'netstat -ano | findstr ":{port}"'],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        pids = set()
        for line in result.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 5:
                try:
                    pid = int(parts[-1])
                    pids.add(pid)
                except ValueError:
                    continue
        if pids:
            for pid in pids:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/PID", str(pid)],
                        capture_output=True,
                        timeout=5,
                    )
                    print(f"[E2E] Killed process {pid} occupying port {port}")
                except Exception:
                    pass
            time.sleep(2)
    except Exception as e:
        print(f"[E2E] Port release warning: {e}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seats", type=int, default=3, help="AI玩家数量(不含BEATRICE，默认3)")
    parser.add_argument("--max-day", type=int, default=1, help="最大天数")
    parser.add_argument("--timeout", type=int, default=600, help="总超时时间(秒)，AI调用较慢需要更长时间")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9123)
    parser.add_argument("--seat-delay", type=float, default=3.0, help="启动每个AI seat的间隔(秒)")
    args = parser.parse_args()

    seats = ROLES[:args.seats]
    min_seats = len(seats)

    # 强制释放计划端口，防止上一次测试残留的僵尸进程占用
    _release_port(args.port)

    print(f"[E2E] 启动全AI端到端实验: {len(seats)} AI seats + BEATRICE, max_day={args.max_day}")
    print(f"[E2E] 超时: {args.timeout}s, 端口: {args.port}")

    # 启动 orchestrator（直接继承stdout）
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

    # 等待 orchestrator 启动完成
    await asyncio.sleep(3)

    # 启动 AI seats（agent_wrapper.py 驱动）
    seat_procs = []
    for seat_id, role_name in seats:
        role_dir = ROOT / "roles" / role_name
        if not role_dir.exists():
            print(f"[E2E] WARNING: Role directory not found: {role_dir}, skipping {seat_id}")
            continue

        cmd = [
            PYTHON, "-u", str(ROOT / "scripts" / "agent_wrapper.py"),
            "--work-dir", str(role_dir),
            "--seat-id", seat_id,
            "--orchestrator-host", args.host,
            "--orchestrator-port", str(args.port),
            "--mode", "auto",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=None,
            stderr=None,
            cwd=str(ROOT),
        )
        seat_procs.append((seat_id, role_name, proc))
        print(f"[E2E] Started AI seat {seat_id} ({role_name}) via agent_wrapper")
        await asyncio.sleep(args.seat_delay)

    # 启动 BEATRICE
    beatrice_dir = ROOT / "roles" / BEATRICE_ROLE
    beatrice_proc = None
    if beatrice_dir.exists():
        beatrice_cmd = [
            PYTHON, "-u", str(ROOT / "scripts" / "agent_wrapper.py"),
            "--work-dir", str(beatrice_dir),
            "--seat-id", "BEATRICE",
            "--orchestrator-host", args.host,
            "--orchestrator-port", str(args.port),
            "--mode", "beatrice",
        ]
        beatrice_proc = await asyncio.create_subprocess_exec(
            *beatrice_cmd,
            stdout=None,
            stderr=None,
            cwd=str(ROOT),
        )
        print("[E2E] Started BEATRICE via agent_wrapper")
    else:
        print(f"[E2E] WARNING: BEATRICE directory not found: {beatrice_dir}")

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
        for seat_id, role_name, proc in seat_procs:
            if proc.returncode is None:
                print(f"[E2E] Terminating {seat_id} ({role_name})...")
                proc.terminate()
        if beatrice_proc and beatrice_proc.returncode is None:
            print("[E2E] Terminating BEATRICE...")
            beatrice_proc.terminate()
        if orch_proc.returncode is None:
            print("[E2E] Terminating orchestrator...")
            orch_proc.terminate()

        # 等待子进程结束
        await asyncio.sleep(3)
        for seat_id, role_name, proc in seat_procs:
            if proc.returncode is None:
                proc.kill()
        if beatrice_proc and beatrice_proc.returncode is None:
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
