"""Backward-compatible process launcher. Prefer `lexaegis start`."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from lexaegis.launcher import run

run()
