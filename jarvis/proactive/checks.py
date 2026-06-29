"""Scheduled checks — the small units the heartbeat runs.

Each check is its own unit: what it looks at, and whether the outcome is worth
surfacing (and how loudly). The *what to check* and *how often* live in config,
not here — editing a threshold or interval shouldn't mean editing code.

A check returns ``(text, urgency)`` to surface something, or ``None`` for the
common case of nothing-to-report. It gets a small persistent ``state`` dict
(saved across restarts) so it can avoid re-surfacing the same thing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import ROOT
from ..storage import load_json

CheckResult = tuple[str, str] | None  # (text, urgency) or None
CheckFn = Callable[[dict[str, Any], dict[str, Any]], CheckResult]


@dataclass
class Check:
    name: str
    fn: CheckFn
    every_seconds: float
    params: dict[str, Any] = field(default_factory=dict)


# --- example checks -------------------------------------------------------

def _watch_file(params: dict[str, Any], state: dict[str, Any]) -> CheckResult:
    """Surface the contents of a trigger file when it appears or changes.

    Handy for verification: create the file and the heartbeat notices it. It
    won't re-surface the same content (quiet by default).
    """
    path = ROOT / params.get("path", "state/trigger.txt")
    if not path.exists():
        return None
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content or content == state.get("last"):
        return None
    state["last"] = content
    return (f"Heads up — {content}", params.get("urgency", "alert"))


def _due_reminders(params: dict[str, Any], state: dict[str, Any]) -> CheckResult:
    """Surface reminders whose due time has passed, once each.

    Reminders only carry a due time if one was set (``due_ts``); without it this
    stays silent — exactly the quiet-by-default posture.
    """
    items = load_json("reminders.json", [])
    now = time.time()
    notified = set(state.get("notified", []))
    due = [
        i
        for i in items
        if not i.get("done")
        and i.get("due_ts")
        and i["due_ts"] <= now
        and i["id"] not in notified
    ]
    if not due:
        return None
    for i in due:
        notified.add(i["id"])
    state["notified"] = list(notified)
    text = "Reminder due — " + "; ".join(i["text"] for i in due)
    return (text, params.get("urgency", "alert"))


_REGISTRY: dict[str, CheckFn] = {
    "watch_file": _watch_file,
    "due_reminders": _due_reminders,
}


def build_checks(config) -> list[Check]:
    """Assemble the configured checks. The only place checks are wired."""
    checks: list[Check] = []
    for entry in config.get("heartbeat.checks", []) or []:
        name = entry.get("name")
        fn = _REGISTRY.get(name)
        if fn is None:
            continue  # unknown check name in config — skip rather than crash
        checks.append(
            Check(
                name=name,
                fn=fn,
                every_seconds=float(entry.get("every_seconds", 60)),
                params=entry.get("params", {}) or {},
            )
        )
    return checks
