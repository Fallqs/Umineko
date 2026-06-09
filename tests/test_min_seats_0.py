"""测试：min_seats=0，不启动 run_game"""
import asyncio, sys, os, subprocess, time
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

from scripts.orchestrator.core import Orchestrator

async def main():
    orch = Orchestrator(
        root,
        mock_mode=True,
        test_mode=True,
        max_day=1,
        min_seats=0,  # 不启动 run_game
    )
    await orch.start()
    await asyncio.sleep(2.0)
    
    # 启动 P1
    agent_log = root / "shared" / "logs" / "agent_P1_min0.log"
    agent_log_fh = open(agent_log, "w", encoding="utf-8", buffering=1)
    proc = subprocess.Popen([
        sys.executable,
        str(root / "scripts" / "agent_wrapper.py"),
        "--work-dir", str(root / "roles" / "右代宫战人"),
        "--seat-id", "P1",
        "--orchestrator-host", "127.0.0.1",
        "--orchestrator-port", "9123",
        "--mode", "auto",
        "--yolo",
    ], stdout=agent_log_fh, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    
    print(f"[Test] P1 started, PID={proc.pid}")
    
    # 监控 60 秒
    for i in range(60):
        await asyncio.sleep(1)
        seats = list(orch.server.network.seats.keys()) if hasattr(orch.server, 'network') else []
        alive = [s for s in orch.server.network.seats.values() if s.alive] if hasattr(orch.server, 'network') else []
        print(f"[Test] t={i+1}s seats={seats} alive={len(alive)} proc_alive={proc.poll() is None}")
        if proc.poll() is not None:
            print(f"[Test] P1 exited with code {proc.returncode}")
            break
    
    await orch.stop()
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=5)
    agent_log_fh.close()

if __name__ == "__main__":
    asyncio.run(main())
