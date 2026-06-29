"""Tier 1 verification — the brain remembers earlier turns in a session.

No network: a fake provider stands in for the model and records what history it
was handed, which is exactly what we need to prove the loop passes context back.
Run with:  python -m pytest tests/  (or: python tests/test_tier1_brain.py)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.agent import Agent  # noqa: E402
from jarvis.provider import OnText, TurnResult  # noqa: E402


class FakeProvider:
    """Records the messages it was asked to complete; replies deterministically."""

    def __init__(self):
        self.seen_messages: list[list[dict]] = []
        self.reply = "ok"

    def complete(self, system, messages, *, tools=None, on_text: OnText | None = None):
        # Copy so later mutation of history doesn't rewrite what we recorded.
        self.seen_messages.append([dict(m) for m in messages])
        if on_text:
            on_text(self.reply)
        return TurnResult(text=self.reply, input_tokens=3, output_tokens=2)


def test_history_is_passed_back():
    fake = FakeProvider()
    agent = Agent(fake, system_prompt="test")

    agent.send("my name is Dana")
    fake.reply = "got it"
    agent.send("what's my name?")

    # The second model call must include the first user turn AND the first reply.
    second_call = fake.seen_messages[1]
    roles_and_text = [(m["role"], m["content"]) for m in second_call]
    assert ("user", "my name is Dana") in roles_and_text, roles_and_text
    assert ("assistant", "ok") in roles_and_text, roles_and_text
    assert ("user", "what's my name?") in roles_and_text, roles_and_text


def test_streaming_callback_receives_text():
    fake = FakeProvider()
    agent = Agent(fake, system_prompt="test")
    chunks: list[str] = []
    agent.send("hi", on_text=chunks.append)
    assert "".join(chunks) == "ok"


def test_token_accounting_accumulates():
    fake = FakeProvider()
    agent = Agent(fake, system_prompt="test")
    agent.send("one")
    agent.send("two")
    assert agent.total_input_tokens == 6
    assert agent.total_output_tokens == 4


if __name__ == "__main__":
    test_history_is_passed_back()
    test_streaming_callback_receives_text()
    test_token_accounting_accumulates()
    print("Tier 1 smoke tests passed ✓")
