"""Tier 5 verification — the heartbeat surfaces, holds, schedules, and quiets.

A controllable clock (now_fn) makes scheduling deterministic without sleeping.
State is redirected to a temp dir so tests don't touch real runtime state.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jarvis.storage as storage  # noqa: E402
from jarvis.proactive.checks import Check  # noqa: E402
from jarvis.proactive.heartbeat import Heartbeat  # noqa: E402
from jarvis.proactive.inbox import Inbox  # noqa: E402


class FakeConfig:
    def __init__(self, data):
        self._d = data

    def get(self, dotted, default=None):
        node = self._d
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def _isolate_state():
    storage.STATE_DIR = Path(tempfile.mkdtemp())


def _counter_check(every, urgency="alert"):
    """A check that surfaces every time it runs, tagged with a run counter."""
    runs = {"n": 0}

    def fn(params, state):
        runs["n"] += 1
        return (f"run {runs['n']}", urgency)

    return Check("counter", fn, every_seconds=every), runs


def test_due_check_surfaces_then_waits_for_interval():
    _isolate_state()
    check, runs = _counter_check(every=100)
    inbox = Inbox()
    clock = {"t": 1000.0}
    hb = Heartbeat([check], inbox, FakeConfig({}), now_fn=lambda: clock["t"])

    assert len(hb.tick()) == 1          # due immediately on first tick
    assert hb.tick() == []              # not due again yet (no time passed)
    assert runs["n"] == 1
    clock["t"] += 100                   # interval elapses
    assert len(hb.tick()) == 1
    assert runs["n"] == 2


def test_schedule_persists_across_restart():
    _isolate_state()
    check, runs = _counter_check(every=100)
    clock = {"t": 5000.0}
    hb = Heartbeat([check], Inbox(), FakeConfig({}), now_fn=lambda: clock["t"])
    hb.tick()  # runs once, next_due = 5100, persisted

    # "Restart": a brand-new Heartbeat reading the same persisted schedule.
    hb2 = Heartbeat([check], Inbox(), FakeConfig({}), now_fn=lambda: clock["t"])
    assert hb2.tick() == []             # resumes — does NOT refire immediately
    clock["t"] = 5100.0
    assert len(hb2.tick()) == 1


def test_quiet_hours_downgrade_alert_to_held_only():
    _isolate_state()
    alerts = []
    cfg = FakeConfig({"heartbeat": {"quiet_hours": {"start": "00:00", "end": "23:59"}}})
    check, _ = _counter_check(every=100, urgency="alert")
    inbox = Inbox()
    hb = Heartbeat([check], inbox, cfg, on_alert=alerts.append, now_fn=lambda: 1000.0)

    raised = hb.tick()
    assert len(raised) == 1             # still surfaced…
    assert inbox.pending()             # …and held in the inbox…
    assert alerts == []                # …but did NOT interrupt during quiet hours


def test_critical_interrupts_even_in_quiet_hours():
    _isolate_state()
    alerts = []
    cfg = FakeConfig({"heartbeat": {"quiet_hours": {"start": "00:00", "end": "23:59"}}})
    check, _ = _counter_check(every=100, urgency="critical")
    hb = Heartbeat([check], Inbox(), cfg, on_alert=alerts.append, now_fn=lambda: 1000.0)
    hb.tick()
    assert len(alerts) == 1


def test_paused_holds_all_proactive_behavior():
    _isolate_state()
    check, runs = _counter_check(every=1)
    hb = Heartbeat([check], Inbox(), FakeConfig({}), is_paused=lambda: True,
                   now_fn=lambda: 1.0)
    assert hb.tick() == []
    assert runs["n"] == 0              # kill switch stops checks from running


def test_notices_held_for_catchup_and_dismissable():
    _isolate_state()
    check, _ = _counter_check(every=100)
    Heartbeat([check], Inbox(), FakeConfig({}), now_fn=lambda: 1.0).tick()

    # A fresh Inbox (= reopening the interface) still sees the held notice.
    inbox2 = Inbox()
    pending = inbox2.pending()
    assert len(pending) == 1
    assert inbox2.dismiss(pending[0].id)
    assert Inbox().pending() == []     # cleared, and the clear persisted


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("Tier 5 heartbeat tests passed ✓")
