#!/usr/bin/env python3
"""第一天全量AI测试：1 auto(P1战人) + 其余全NPC。

预期运行时间：约10小时（_min_turn_interval=20秒，16角色×120turn/天=1920turn）
"""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator.core import Orchestrator


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

    orch = Orchestrator(
        root,
        mock_mode=True,      # npc_engine 自动启动所有未控制角色的NPC进程
        test_mode=True,
        max_day=1,
        min_seats=1,         # P1注册后即启动游戏
    )

    await orch.start()
    await asyncio.sleep(2.0)

    # 启动 P1 auto mode（战人）
    python_exe = str(Path(sys.executable).resolve())
    agent_log = root / "shared" / "logs" / "agent_P1.log"
    agent_log_fh = open(agent_log, "w", encoding="utf-8", buffering=1)
    cmd = [
        python_exe,
        str(root / "scripts" / "agent_wrapper.py"),
        "--work-dir", str(root / "roles" / "右代宫战人"),
        "--seat-id", "P1",
        "--orchestrator-host", "127.0.0.1",
        "--orchestrator-port", "9123",
        "--mode", "auto",
        "--yolo",
    ]
    log(f"启动 P1 auto agent: {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd,
        stdout=agent_log_fh,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
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
