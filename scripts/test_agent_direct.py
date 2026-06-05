#!/usr/bin/env python3
"""Direct test for agent_wrapper without subprocess."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_wrapper import run_agent_mode


async def main():
    root = Path(__file__).resolve().parent.parent
    pipe = root / "shared" / "inbox" / "test_direct" / "agent_pipe.jsonl"
    out = Path(str(pipe) + ".out")
    pipe.parent.mkdir(parents=True, exist_ok=True)
    if pipe.exists():
        pipe.unlink()
    if out.exists():
        out.unlink()

    print("Starting agent...")
    agent_task = asyncio.create_task(
        run_agent_mode(
            work_dir=root / "roles" / "右代宫战人",
            pipe_path=pipe,
            session_id="test_direct",
            yolo=True,
            thinking=False,
        )
    )

    await asyncio.sleep(3)
    print("Sending input...")
    with open(pipe, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "input", "text": "你是谁？请用一句话介绍自己。", "id": "t1"}, ensure_ascii=False) + "\n")

    print("Waiting for response (up to 60s)...")
    await asyncio.sleep(45)

    print("\n=== Output ===")
    if out.exists():
        print(out.read_text(encoding="utf-8"))
    else:
        print("No output file")

    print("\nCancelling agent...")
    agent_task.cancel()
    try:
        await agent_task
    except asyncio.CancelledError:
        pass
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
