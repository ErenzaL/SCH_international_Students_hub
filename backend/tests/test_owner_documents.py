"""The owner's variable list and source list are generated from the code and never drift from it."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_environment_and_source_lists_are_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/env_inventory.py"), "--check"], capture_output=True, text=True, cwd=ROOT / "backend")
    assert r.returncode == 0, r.stdout + r.stderr
