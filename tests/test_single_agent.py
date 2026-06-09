"""测试：只启动 orchestrator 和一个 agent，不启动 NPC"""
import asyncio, sys, os, subprocess, time
from pathlib import Path

root = Path(__file__).parent.parent
sys.path.insert(0, str(root))

# 覆盖 npc_engine.start_all_npcs 为空函数
from scripts.orchestrator.npc_engine import NPCEngine
NPCEngine.start_all_npcs = lambda *args, **kwargs: None
NPCEngine._launched_npc_roles = set()

from scripts.orchestrator.core import Orchestrator

async def main():
    orch = Orchestrator(
        root,
        mock_mode=True,
        test_mode=True,
        max_day=1,
        min_seats=1,
    )
    await orch.start()
    print("[Test] Orchestrator started, waiting 3s...")
    await asyncio.sleep(3)
    
    # 启动一个 agent
    log_file = root / "shared" / "logs" / "P1_single_test.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([
        sys.executable, str(root / "scripts" / "agent_wrapper.py"),
        "--work-dir", str(root / "roles" / "右代宫战人"),
        "--seat-id", "P1",
        "--orchestrator-host", "127.0.0.1",
        "--orchestrator-port", "9123",
        "--mode", "auto",
        "--yolo",
    ], stdout=open(log_file, "w", encoding="utf-8"), stderr=subprocess.STDOUT)
    
    print(f"[Test] Agent started, PID={proc.pid}")
    
    # 监控
    for i in range(30):
        await asyncio.sleep(1)
        seats = list(orch.server.network.seats.keys()) if hasattr(orch.server, 'network') else []
        alive = [s for s in orch.server.network.seats.values() if s.alive] if hasattr(orch.server, 'network') else []
        print(f"[Test] t={i+1}s seats={seats} alive={len(alive)}")
        if proc.poll() is not None:
            print(f"[Test] Agent exited with code {proc.returncode}")
            break
    
    await orch.stop()
    if proc.poll() is None:
        proc.terminate()
        proc.wait(timeout=5)

if __name__ == "__main__":
    asyncio.run(main())
