"""Compatibility entry point; the baseline writer lives in backend/baseline.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.baseline import *  # noqa: F401,F403
