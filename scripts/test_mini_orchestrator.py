#!/usr/bin/env python3
"""Mini orchestrator: 2 roles, 1 day, for quick real AI test."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_orchestrator as to

# Override SEAT_CHAINS to only 2 roles
to.SEAT_CHAINS = {
    "P1": ["右代宫战人"],
    "NPC1": ["贝阿朵莉切"],
}

root = Path(__file__).resolve().parent.parent
orch = to.TestOrchestrator(root, mock_mode=False, python_exe=sys.executable)
orch.run(max_day=1)
