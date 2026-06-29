"""Tiny durable storage helpers.

Local runtime state lives under ``state/`` (git-ignored). Everything is plain
JSON on purpose — human-readable, easy to inspect, easy to correct by hand.
This is reused by reminders (Tier 2), memory (Tier 4), and the heartbeat's
schedule and notice inbox (Tier 5).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import ROOT

STATE_DIR = ROOT / "state"


def _path(name: str) -> Path:
    return STATE_DIR / name


def load_json(name: str, default: Any) -> Any:
    """Load ``state/<name>``, returning ``default`` if it doesn't exist yet."""
    path = _path(name)
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        # A corrupt state file should not crash a daily-driver assistant.
        return default


def save_json(name: str, data: Any) -> None:
    """Write ``state/<name>`` atomically so a crash mid-write can't corrupt it."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _path(name)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    tmp.replace(path)
