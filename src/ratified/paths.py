"""Resolve the local data and cache roots, overridable by environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = os.environ.get("RATIFIED_DATA_DIR", str(ROOT / "data"))
CACHE_DIR = os.environ.get("RATIFIED_CACHE_DIR", str(ROOT / "cache" / "http"))
