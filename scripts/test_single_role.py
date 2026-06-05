#!/usr/bin/env python3
"""Quick single-role real AI test."""

import subprocess
import sys
import time
from pathlib import Path

root = Path(__file__).resolve().parent.parent
pipe = root / "shared" / "inbox" / "test_single" / "agent_pipe.jsonl"
out = Path(str(pipe) + ".out")
pipe.parent.mkdir(parents=True, exist_ok=True)
if pipe.exists(): pipe.unlink()
if out.exists(): out.unlink()

python = sys.executable
wrapper = root / "scripts" / "agent_wrapper.py"
work_dir = root / "roles" / "右代宫战人"

print("Starting agent_wrapper...")
proc = subprocess.Popen(
    [python, str(wrapper), "--work-dir", str(work_dir), "--pipe", str(pipe), "--session", "test_single", "--yolo"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
)

time.sleep(3)

# Send input
msg = '{"type":"input","text":"你是右代宫战人。今天是第1天清晨，你刚醒来在六轩岛的本馆。请描述你此刻的心情和打算。","id":"t1"}\n'
with open(pipe, "w", encoding="utf-8") as f:
    f.write(msg)

print("Sent input, waiting for response (up to 60s)...")
start = time.time()
response_text = None
last_pos = 0
while time.time() - start < 60:
    if not out.exists():
        time.sleep(0.5)
        continue
    size = out.stat().st_size
    if size <= last_pos:
        time.sleep(0.5)
        continue
    with open(out, "r", encoding="utf-8") as f:
        f.seek(last_pos)
        content = f.read()
        last_pos = f.tell()
    for line in content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            import json
            m = json.loads(line)
            if m.get("type") == "output":
                response_text = m.get("text", "")
                print(f"\n[RESPONSE] {response_text}\n")
            elif m.get("type") == "status" and m.get("phase") == "idle":
                if response_text:
                    print("Got idle status, test complete.")
                    break
        except json.JSONDecodeError:
            continue
    if response_text:
        break

if not response_text:
    print("No response received within 60s.")

print("\nAgent stdout/stderr:")
try:
    outs, _ = proc.communicate(timeout=5)
    if outs:
        print(outs[-2000:])
except subprocess.TimeoutExpired:
    proc.kill()
    print("(killed after timeout)")

print("Test finished.")
