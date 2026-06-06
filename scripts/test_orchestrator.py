#!/usr/bin/env python3
"""
《海猫鸣泣之时：六轩岛黄昏》全自动测试 Orchestrator

本文件是向后兼容的入口，实际逻辑已迁移到 orchestrator.py。
用法:
    python test_orchestrator.py [--root-dir ..] [--mock] [--mode {auto|human}]
"""

import sys
from pathlib import Path

# 导入新 orchestrator 的 main
sys.path.insert(0, str(Path(__file__).resolve().parent))
from orchestrator import main

if __name__ == "__main__":
    main()
