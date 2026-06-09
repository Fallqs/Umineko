"""测试：同时启动 orchestrator + P1 + 1 NPC，使用 text=True"""
import asyncio, sys, os, subprocess
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
        min_seats=1,
    )
    await orch.start()
    print("[Test] Orchestrator started, waiting 3s...")
    await asyncio.sleep(3)
    
    # 同时启动 P1 和 NPC，使用 text=True
    procs = []
    for seat_id, role, mode in [("P1", "右代宫战人", "auto"), ("NPC_右代宫雾江", "右代宫雾江", "npc")]:
        log_file = root / "shared" / "logs" / f"{seat_id}_text_test.log"
        log_fh = open(log_file, "w", encoding="utf-8", buffering=1)
        proc = subprocess.Popen([
            sys.executable, str(root / "scripts" / "agent_wrapper.py"),
            "--work-dir", str(root / "roles" / role),
            "--seat-id", seat_id,
            "--orchestrator-host", "127.0.0.1",
            "--orchestrator-port", "9123",
            "--mode", mode,
            "--yolo",
        ], stdout=log_fh, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        procs.append((seat_id, proc, log_fh))
        print(f"[Test] Started {seat_id}, PID={proc.pid}")
    
    # 监控 30 秒
    for i in range(30):
        await asyncio.sleep(1)
        seats = list(orch.server.network.seats.keys()) if hasattr(orch.server, 'network') else []
        alive = [s for s in orch.server.network.seats.values() if s.alive] if hasattr(orch.server, 'network') else []
        exited = [sid for sid, p, _ in procs if p.poll() is not None]
        print(f"[Test] t={i+1}s seats={seats} alive={len(alive)} exited={exited}")
        if len(exited) == len(procs):
            break
    
    await orch.stop()
    for sid, proc, log_fh in procs:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=5)
        log_fh.close()

if __name__ == "__main__":
    asyncio.run(main())
