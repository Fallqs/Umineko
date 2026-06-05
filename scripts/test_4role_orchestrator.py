#!/usr/bin/env python3
"""4-role orchestrator: P1+P2+P3+NPC1, 1 day, for real AI test."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestrator as to

# Override SEAT_CHAINS to 4 roles
to.SEAT_CHAINS = {
    "P1": ["右代宫战人"],
    "P2": ["右代宫朱志香"],
    "P3": ["右代宫让治"],
    "NPC1": ["贝阿朵莉切"],
}

root = Path(__file__).resolve().parent.parent
orch = to.TestOrchestrator(root, mock_mode=False, python_exe=sys.executable)
orch.run(max_day=1)
