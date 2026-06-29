"""The heartbeat — a background scheduler, separate from the conversation loop.

Wakes on an interval, runs each due check, and routes anything noteworthy into
the inbox. Built to the hard-won rules:

- **Quiet by default.** Everything is held in the inbox; only alerts (and only
  outside quiet hours, unless critical) actually interrupt.
- **Survives restarts.** Each check's next-due time and small state persist to
  disk, so restarting resumes the schedule instead of refiring everything.
- **No overlapping runs.** A check still working when its next turn comes due is
  skipped, not stacked.
- **Relocatable.** It doesn't care which machine it's on, so it can move to an
  always-on host later without a rewrite.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, time as dtime
from typing import Callable

from ..storage import load_json, save_json
from .checks import Check
from .inbox import Inbox, Notice

_SCHEDULE = "schedule.json"


class Heartbeat:
    def __init__(
        self,
        checks: list[Check],
        inbox: Inbox,
        config,
        *,
        on_alert: Callable[[Notice], None] | None = None,
        is_paused: Callable[[], bool] | None = None,
        now_fn: Callable[[], float] = time.time,
    ):
        self.checks = checks
        self.inbox = inbox
        self.config = config
        self.on_alert = on_alert
        self.is_paused = is_paused or (lambda: False)
        self.now_fn = now_fn

        self.tick_seconds = float(config.get("heartbeat.tick_seconds", 5))
        self._schedule: dict = load_json(_SCHEDULE, {})
        self._running: set[str] = set()  # overlap guard
        self._stop = threading.Event()

    # --- the loop ----------------------------------------------------------

    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    def run_forever(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - a check blowing up must not kill the loop
                pass
            self._stop.wait(self.tick_seconds)

    def tick(self, now: float | None = None) -> list[Notice]:
        """Run all due checks once. Returns notices raised this tick (for tests)."""
        # Kill switch: when paused, hold all proactive behavior (Tier 6 wires it).
        if self.is_paused():
            return []

        now = self.now_fn() if now is None else now
        raised: list[Notice] = []

        for check in self.checks:
            slot = self._schedule.setdefault(check.name, {"next_due": now, "state": {}})
            if now < slot["next_due"]:
                continue
            if check.name in self._running:  # still working — don't stack
                continue

            self._running.add(check.name)
            try:
                result = check.fn(check.params, slot["state"])
            except Exception:  # noqa: BLE001 - a bad check shouldn't break the rest
                result = None
            finally:
                self._running.discard(check.name)
                # Reschedule from now so a slow run doesn't immediately re-fire.
                slot["next_due"] = now + check.every_seconds

            if result is not None:
                raised.append(self._surface(check.name, *result, now))

        save_json(_SCHEDULE, self._schedule)
        return raised

    # --- surfacing ---------------------------------------------------------

    def _surface(self, check: str, text: str, urgency: str, now: float) -> Notice:
        notice = self.inbox.add(check, text, urgency)  # always held for catch-up
        if self._should_interrupt(urgency, now) and self.on_alert:
            self.on_alert(notice)
        return notice

    def _should_interrupt(self, urgency: str, now: float) -> bool:
        if urgency == "critical":
            return True  # truly critical earns a late-night interruption
        if self._in_quiet_hours(now):
            return False  # non-urgent waits for waking hours
        return urgency == "alert"

    def _in_quiet_hours(self, now: float) -> bool:
        start = self._parse(self.config.get("heartbeat.quiet_hours.start"))
        end = self._parse(self.config.get("heartbeat.quiet_hours.end"))
        if start is None or end is None:
            return False
        current = datetime.fromtimestamp(now).time()
        if start <= end:
            return start <= current < end
        # Window wraps past midnight (e.g. 22:00 → 07:00).
        return current >= start or current < end

    @staticmethod
    def _parse(hhmm: str | None) -> dtime | None:
        if not hhmm:
            return None
        try:
            h, m = hhmm.split(":")
            return dtime(int(h), int(m))
        except (ValueError, AttributeError):
            return None
