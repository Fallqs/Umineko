#!/usr/bin/env python3
"""
《海猫鸣泣之时：六轩岛黄昏》Orchestrator - TCP Server 版

【注意】本文件现仅为兼容薄wrapper。
核心实现已迁移至 scripts/orchestrator/ 包。

外部调用方式不变：
    python scripts/orchestrator.py --mock --max-day 3
    from orchestrator import Orchestrator
"""

import argparse
import asyncio
import sys
from pathlib import Path

# 确保 orchestrator 包在路径中
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orchestrator.core import Orchestrator


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("gbk", "replace").decode("gbk"))


async def amain(args) -> None:
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    if args.root_dir is None:
        root_dir = Path(__file__).resolve().parent.parent
    else:
        root_dir = args.root_dir.resolve()

    print(f"[Orchestrator] Root dir: {root_dir}")
    print(f"[Orchestrator] Mock mode: {args.mock}")
    print(f"[Orchestrator] Max day: {args.max_day}")
    print(f"[Orchestrator] Mode: {args.mode}")
    print(f"[Orchestrator] TCP: {args.host}:{args.port}")

    active_seats = None
    if args.active_seats:
        active_seats = [s.strip() for s in args.active_seats.split(",") if s.strip()]

    ai_seats = None
    if args.ai_seats:
        ai_seats = [s.strip() for s in args.ai_seats.split(",") if s.strip()]

    orch = Orchestrator(
        root_dir=root_dir,
        host=args.host,
        port=args.port,
        mock_mode=args.mock,
        python_exe=args.python,
        mode=args.mode,
        min_seats=args.min_seats,
        active_seats=active_seats,
        max_day=args.max_day,
        test_mode=args.test_mode,
        ai_seats=ai_seats,
    )

    try:
        await orch.serve()
    except KeyboardInterrupt:
        print("\n[Orchestrator] Interrupted")
    finally:
        await orch.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Umineko Orchestrator (TCP Server)")
    parser.add_argument("--root-dir", type=Path, default=None, help="项目根目录")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=9123, help="监听端口")
    parser.add_argument("--mock", action="store_true", help="Mock模式（不启动真实AI进程）")
    parser.add_argument("--python", type=str, default="python", help="Python可执行文件路径")
    parser.add_argument("--max-day", type=int, default=7, help="最大运行天数（默认7）")
    parser.add_argument("--mode", type=str, default="auto", choices=["auto", "human"],
                        help="运行模式: auto=AI驱动, human=人类玩家")
    parser.add_argument("--min-seats", type=int, default=None,
                        help="开始游戏所需的最少 seat 数量（测试用，默认全部）")
    parser.add_argument("--active-seats", type=str, default=None,
                        help="逗号分隔的活跃 seat ID 列表（例如 P1,P2,BEATRICE）")
    parser.add_argument("--test-mode", action="store_true",
                        help="测试模式：死亡与分数实时广播（正常游玩请勿开启，会泄密）")
    parser.add_argument("--ai-seats", type=str, default=None,
                        help="逗号分隔的 AI seat ID 列表（例如 P1,P2,P3）。未指定时 auto 模式全部为 AI，human 模式全部为人类。")
    args = parser.parse_args()
    asyncio.run(amain(args))


if __name__ == "__main__":
    main()
