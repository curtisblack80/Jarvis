"""The notice inbox — the single place surfaced items land.

Persisted to disk so a notice raised while your interface was closed (or while
you were asleep) is *held for you* and shown when you return — catch-up-on-
return, never deliver-once-and-lose-it. Every item is dismissible; an inbox you
can't empty becomes clutter you'll ignore.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Literal

from ..storage import load_json, save_json

_FILE = "inbox.json"

Urgency = Literal["calm", "alert", "critical"]


@dataclass
class Notice:
    id: int
    check: str
    text: str
    urgency: Urgency
    created_at: float

    def pretty(self) -> str:
        mark = {"calm": "·", "alert": "!", "critical": "‼"}.get(self.urgency, "·")
        when = time.strftime("%H:%M", time.localtime(self.created_at))
        return f"  [{mark}] #{self.id} ({when}) {self.text}"


class Inbox:
    """A durable list of undismissed notices."""

    def __init__(self) -> None:
        self._items: list[Notice] = [Notice(**d) for d in load_json(_FILE, [])]

    def add(self, check: str, text: str, urgency: Urgency) -> Notice:
        notice = Notice(
            id=int(time.time() * 1000),
            check=check,
            text=text,
            urgency=urgency,
            created_at=time.time(),
        )
        self._items.append(notice)
        self._save()
        return notice

    def pending(self) -> list[Notice]:
        return list(self._items)

    def dismiss(self, notice_id: int) -> bool:
        before = len(self._items)
        self._items = [n for n in self._items if n.id != notice_id]
        if len(self._items) != before:
            self._save()
            return True
        return False

    def dismiss_all(self) -> int:
        n = len(self._items)
        self._items = []
        self._save()
        return n

    def _save(self) -> None:
        save_json(_FILE, [asdict(n) for n in self._items])
