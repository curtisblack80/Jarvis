"""The audit trail — a plain log of what the assistant did and why.

Which tools ran, what it asked you to confirm and what you decided, what the
heartbeat surfaced, and a running model-cost tally so a runaway loop is visible
immediately. When something surprises you, this is how you find out what
happened. It's append-only JSON-lines under state/audit.log.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from . import storage

_FILE = "audit.log"


def _path() -> Path:
    return storage.STATE_DIR / _FILE


def log(event: str, **fields) -> None:
    """Append one event. Never raises — auditing must not break the app."""
    try:
        storage.STATE_DIR.mkdir(parents=True, exist_ok=True)
        record = {"ts": round(time.time(), 3), "event": event, **fields}
        with _path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass


def tail(n: int = 20) -> list[dict]:
    """Return the most recent ``n`` events (for a 'log' command)."""
    path = _path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-n:]
        return [json.loads(line) for line in lines if line.strip()]
    except Exception:  # noqa: BLE001
        return []
