#!/usr/bin/env python3
"""
Agent Wrapper for kimi-cli-remote

无需修改第三方代码，直接导入 kimi_cli 模块驱动 AI 角色进程。
监听 pipe 文件输入，将 AI 输出写入 .out 文件。

用法:
    python agent_wrapper.py --work-dir ../roles/右代宫战人 --pipe ../shared/inbox/战人/agent_pipe.jsonl --session battler
"""

import argparse
import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

# Ensure kimi_cli is importable (repo paths already in sys.path in this env)
from kaos.path import KaosPath
from kaos.path import KaosPath
from kimi_cli.app import KimiCLI, enable_logging
from kimi_cli.config import Config, load_config
from kimi_cli.session import Session
from kimi_cli.wire.types import TextPart, ThinkPart, ToolCall, ToolCallPart


def _read_pipe_input(pipe_path: Path, last_pos: int) -> tuple[list[dict], int]:
    if not pipe_path.exists():
        return [], last_pos
    current_size = pipe_path.stat().st_size
    if current_size <= last_pos:
        return [], last_pos
    with open(pipe_path, "r", encoding="utf-8") as f:
        f.seek(last_pos)
        new_content = f.read()
        new_pos = f.tell()
    messages = []
    for line in new_content.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages, new_pos


def _write_output(out_path: Path, msg: dict) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(msg, ensure_ascii=False) + "\n")


async def run_agent_mode(
    work_dir: Path,
    pipe_path: Path,
    session_id: str | None = None,
    yolo: bool = True,
    thinking: bool = False,
    model_name: str | None = None,
) -> None:
    enable_logging(debug=False, redirect_stderr=False)

    kaos_work_dir = KaosPath.unsafe_from_local_path(work_dir)

    # Create or resume session
    if session_id:
        session = await Session.find(kaos_work_dir, session_id)
        if session is None:
            session = await Session.create(kaos_work_dir, session_id)
            print(f"[Agent] Created new session: {session.id}")
        else:
            print(f"[Agent] Resumed session: {session.id}")
    else:
        session = await Session.create(kaos_work_dir)
        print(f"[Agent] Created new session: {session.id}")

    config: Config | None = None
    try:
        config = load_config()
    except Exception:
        pass

    instance = await KimiCLI.create(
        session,
        config=config,
        model_name=model_name,
        thinking=thinking,
        yolo=yolo,
    )

    out_path = Path(str(pipe_path) + ".out")
    last_pos = pipe_path.stat().st_size if pipe_path.exists() else 0

    print(f"[Agent] Started. work_dir={work_dir}, pipe={pipe_path}, session={session.id}")
    print(f"[Agent] Waiting for input...")

    try:
        while True:
            messages, last_pos = _read_pipe_input(pipe_path, last_pos)
            for msg in messages:
                if msg.get("type") != "input":
                    continue
                text = msg.get("text", "")
                msg_id = msg.get("id", "")
                print(f"[Agent] Input ({msg_id}): {text[:120]}...")

                cancel_event = asyncio.Event()
                output_parts: list[str] = []
                thinking_parts: list[str] = []
                tool_names: list[str] = []
                error_info: str | None = None

                try:
                    async for wire_msg in instance.run(text, cancel_event):
                        if isinstance(wire_msg, TextPart):
                            output_parts.append(wire_msg.text)
                        elif isinstance(wire_msg, ThinkPart):
                            thinking_parts.append(wire_msg.text)
                        elif isinstance(wire_msg, ToolCall):
                            tool_names.append(wire_msg.function.name)
                        elif isinstance(wire_msg, ToolCallPart):
                            for tc in wire_msg.tool_calls:
                                tool_names.append(tc.function.name)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    error_info = f"{type(e).__name__}: {e}"
                    traceback.print_exc()

                full_text = "".join(output_parts)
                full_thinking = "".join(thinking_parts)

                if error_info:
                    print(f"[Agent] Error ({msg_id}): {error_info}")
                    _write_output(out_path, {
                        "type": "status",
                        "phase": "error",
                        "error": error_info,
                        "id": msg_id,
                    })
                    continue

                print(f"[Agent] Output ({msg_id}): {full_text[:120]}...")
                if tool_names:
                    print(f"[Agent] Tools ({msg_id}): {tool_names}")

                _write_output(out_path, {
                    "type": "output",
                    "text": full_text,
                    "thinking": full_thinking if full_thinking else None,
                    "tools": tool_names,
                    "id": msg_id,
                })
                _write_output(out_path, {
                    "type": "status",
                    "phase": "idle",
                    "id": msg_id,
                })

            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        print("[Agent] Shutting down (cancelled)...")
    finally:
        instance.shutdown_background_tasks()
        print("[Agent] Stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent wrapper for kimi-cli-remote")
    parser.add_argument("--work-dir", type=Path, required=True, help="Working directory (role dir)")
    parser.add_argument("--pipe", type=Path, required=True, help="Path to agent_pipe.jsonl")
    parser.add_argument("--session", type=str, default=None, help="Session ID to resume")
    parser.add_argument("--yolo", action="store_true", default=True, help="Auto-approve actions")
    parser.add_argument("--no-yolo", dest="yolo", action="store_false", help="Do not auto-approve")
    parser.add_argument("--thinking", action="store_true", default=False, help="Enable thinking mode")
    parser.add_argument("--model", type=str, default=None, help="Model name")
    args = parser.parse_args()

    asyncio.run(
        run_agent_mode(
            work_dir=args.work_dir.resolve(),
            pipe_path=args.pipe.resolve(),
            session_id=args.session,
            yolo=args.yolo,
            thinking=args.thinking,
            model_name=args.model,
        )
    )


if __name__ == "__main__":
    main()
