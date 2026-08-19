"""Ensure the parent directory is importable for package resolution."""

from __future__ import annotations

import sys
from pathlib import Path

PARENT = Path(__file__).resolve().parent.parent
for path in (str(PARENT),):
    if path not in sys.path:
        sys.path.insert(0, path)
