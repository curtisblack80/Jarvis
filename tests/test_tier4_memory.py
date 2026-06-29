"""Tier 4 verification — memory survives restarts and respects hand edits.

A fresh Memory pointed at the same file is exactly what "quit and restart" looks
like, so no process juggling is needed.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.agent import Agent  # noqa: E402
from jarvis.memory import Memory  # noqa: E402
from jarvis.provider import TurnResult  # noqa: E402


def _tmp() -> Path:
    return Path(tempfile.mkdtemp()) / "memory.md"


def test_fact_survives_a_restart():
    path = _tmp()
    Memory(path).add("The user's name is Dana.")
    # "Restart" = a brand-new Memory reading the same file.
    assert "The user's name is Dana." in Memory(path).facts()


def test_hand_edit_is_respected():
    path = _tmp()
    m = Memory(path)
    m.add("Prefers tea.")
    # Simulate the user opening the file and correcting it by hand.
    path.write_text("# header\n- Prefers coffee.\n", encoding="utf-8")
    assert Memory(path).facts() == ["Prefers coffee."]


def test_update_and_forget():
    path = _tmp()
    m = Memory(path)
    m.add("Lives in Berlin.")
    assert "Updated" in m.update("Berlin", "Lives in Munich.")
    assert m.facts() == ["Lives in Munich."]
    assert "Forgot" in m.forget("Munich")
    assert m.facts() == []


def test_no_duplicate_facts():
    path = _tmp()
    m = Memory(path)
    m.add("Likes oat milk.")
    m.add("likes OAT milk.")  # case-different duplicate
    assert m.facts() == ["Likes oat milk."]


def test_memory_lands_in_system_prompt_as_data_not_commands():
    path = _tmp()
    m = Memory(path)
    m.add("Prefers morning meetings.")

    seen = {}

    class P:
        def complete(self, system, messages, *, tools=None, on_text=None):
            seen["system"] = system
            return TurnResult(text="ok")

    agent = Agent(P(), "BASE", memory=m)
    agent.send("hi")
    assert "Prefers morning meetings." in seen["system"]
    assert "NOT instructions" in seen["system"]  # framed as data, not commands


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("Tier 4 memory tests passed ✓")
