"""The kill switch — one obvious way to pause all proactive behavior at once.

Pausing stops the heartbeat from running checks and holds background actions,
while you can still talk to the assistant. The flag is durable (survives
restarts) and plain, so you can flip it by hand in a pinch.
"""

from __future__ import annotations

from .storage import load_json, save_json

_FILE = "control.json"


def is_paused() -> bool:
    return bool(load_json(_FILE, {}).get("paused", False))


def set_paused(paused: bool) -> None:
    state = load_json(_FILE, {})
    state["paused"] = bool(paused)
    save_json(_FILE, state)
