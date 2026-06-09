#!/usr/bin/env python3
"""第一天全量AI测试：1 auto(P1战人) + 其余全NPC。

流程：
1. 启动 Orchestrator（生成 access_token 和 start_npcs.bat）
2. 启动 P1 auto agent
3. 用 Python subprocess.Popen 直接启动所有 NPC（避免 bat 不可靠问题）
4. Orchestrator 等待全员到齐后自动开始游戏
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
import socket

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.orchestrator.core import Orchestrator


async def main():
    root = Path(__file__).resolve().parent.parent
    log_path = root / "shared" / "logs" / "test_day1_full_ai.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(msg: str):
        line = f"[{asyncio.get_event_loop().time():.0f}] {msg}"
        print(line)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    log("=" * 60)
    log("启动第一天全量AI测试")
    log("配置: 1 auto(P1战人) + 其余全NPC")
    log("预计运行时间: ~10小时")
    log("=" * 60)

    # 找一个可用端口（避免僵尸进程占用）
    def find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    port = find_free_port()
    log(f"使用端口: {port}")

    orch = Orchestrator(
        root,
        mock_mode=True,
        test_mode=True,
        max_day=1,
        active_seats=["P1"],
        port=port,
    )

    await orch.start()
    await asyncio.sleep(1.0)

    python_exe = str(Path(sys.executable).resolve())
    npc_procs = []

    # 读取 NPC 配置
    config_path = root / "shared" / ".npc_config.json"
    npc_config = json.loads(config_path.read_text(encoding="utf-8"))
    token = npc_config["access_token"]
    host = npc_config["host"]
    port = npc_config["port"]

    # 计算需要启动的 NPC 角色（与 core.py 中 _generate_npc_launch_scripts 逻辑一致）
    all_roles = set()
    for chain in orch.config.seat_chains.values():
        all_roles.update(chain)
    all_roles.add("右代宫金藏")
    all_roles.add("贝阿朵莉切")
    controlled_by_player = set()
    for seat_id, chain in orch.config.seat_chains.items():
        if chain:
            controlled_by_player.add(chain[0])
    npc_roles = sorted(all_roles - controlled_by_player)
    log(f"需要启动的NPC角色: {npc_roles}")

    def _ascii_dir_name(seat_id: str) -> str:
        parts = []
        for ch in seat_id:
            if ord(ch) < 128:
                parts.append(ch)
            else:
                parts.append(f"_u{ord(ch):04x}")
        return "".join(parts)

    # 启动所有 NPC
    for role in npc_roles:
        agent_log = root / "shared" / "logs" / f"NPC_{role}.log"
        agent_log_fh = open(agent_log, "w", encoding="utf-8", buffering=1)
        cmd = [
            python_exe,
            str(root / "scripts" / "agent_wrapper.py"),
            "--work-dir", str(root / "roles" / role),
            "--seat-id", f"NPC_{role}",
            "--orchestrator-host", host,
            "--orchestrator-port", str(port),
            "--mode", "npc",
            "--yolo",
            "--access-token", token,
        ]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        proc = subprocess.Popen(
            cmd,
            stdout=agent_log_fh,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=env,
        )
        npc_procs.append((proc, agent_log_fh))
        log(f"启动NPC: {role}")
        await asyncio.sleep(0.5)

    # 启动 P1 auto mode（战人）
    agent_log = root / "shared" / "logs" / "agent_P1.log"
    agent_log_fh = open(agent_log, "w", encoding="utf-8", buffering=1)
    cmd = [
        python_exe,
        str(root / "scripts" / "agent_wrapper.py"),
        "--work-dir", str(root / "roles" / "右代宫战人"),
        "--seat-id", "P1",
        "--orchestrator-host", host,
        "--orchestrator-port", str(port),
        "--mode", "auto",
        "--yolo",
        "--access-token", token,
    ]
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    log(f"启动 P1 auto agent")
    proc = subprocess.Popen(
        cmd,
        stdout=agent_log_fh,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        env=env,
    )

    # 等待游戏完成或超时（12小时）
    last_alive = 0
    last_phase = ""
    stall_counter = 0

    try:
        for _ in range(12 * 60 * 60 // 30):  # 每30秒检查一次，最多12小时
            await asyncio.sleep(30)

            alive = len(orch.state.alive_roles)
            phase = orch.state.phase
            day = orch.state.day

            # 检测是否卡死（alive/phase 5分钟无变化）
            if alive == last_alive and phase == last_phase:
                stall_counter += 1
            else:
                stall_counter = 0
                last_alive = alive
                last_phase = phase

            log(f"Day{day} {phase} | 存活:{alive} | turn:{orch.turn_counter} | stall:{stall_counter}")

            # 如果游戏已完成或卡死超过10分钟
            if day > 1 or orch._stop_requested:
                log("游戏自然结束")
                break
            if stall_counter > 20:  # 10分钟无变化
                log("检测到卡死，强制停止")
                break

    except asyncio.CancelledError:
        log("测试被取消")
    finally:
        await orch.stop()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        for npc_proc, npc_log_fh in npc_procs:
            if npc_proc.poll() is None:
                npc_proc.terminate()
                try:
                    npc_proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    npc_proc.kill()
            npc_log_fh.close()
        agent_log_fh.close()

    # 最终报告
    log("=" * 60)
    log("测试结束")
    log(f"最终 Day: {orch.state.day}, Phase: {orch.state.phase}")
    log(f"存活角色: {sorted(orch.state.alive_roles)}")
    log(f"死亡角色: {sorted(orch.state.dead_roles)}")
    log(f"总turn数: {orch.turn_counter}")
    log(f" narrative 日志行数: {len(orch.narrative_log)}")
    log("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
