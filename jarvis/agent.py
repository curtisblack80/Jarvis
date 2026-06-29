"""The brain — one shared conversation core.

A typed turn, a spoken turn (Tier 3), and a heartbeat-initiated turn (Tier 5)
all flow through ``Agent.send``. Never fork this logic for voice.

Tier 1: input text in, get a streamed reply, keep in-session history. No tools,
no audio, no cross-restart memory yet — those are later tiers, and this core is
shaped to accept them without a rewrite.
"""

from __future__ import annotations

from typing import Any

from .provider import OnText, Provider, TurnResult

SYSTEM_TEMPLATE = """\
You are {name}, a voice-first personal assistant.

Purpose: {purpose}

Tone: {tone}. Speak like a calm, competent person who respects the user's
time — no filler, no preamble, no purple prose. Because your replies may be
spoken aloud, keep them short and natural to hear. Prefer one or two sentences
unless the user clearly wants more. If you don't know something, say so plainly.
"""


def build_system_prompt(config) -> str:
    return SYSTEM_TEMPLATE.format(
        name=config.get("identity.name", "Jarvis"),
        purpose=config.get("identity.purpose", "a personal assistant."),
        tone=config.get("identity.tone", "warm, plain-spoken, and brief"),
    )


class Agent:
    """Holds the system prompt and the running conversation, and runs turns."""

    def __init__(self, provider: Provider, system_prompt: str):
        self.provider = provider
        self.system_prompt = system_prompt
        self.history: list[dict[str, Any]] = []
        # Running cost signal (Tier 6 surfaces this; cheap to track from day 1).
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def send(self, user_text: str, *, on_text: OnText | None = None) -> str:
        """Run one turn: append input, get a reply, append it, return the text.

        ``on_text`` receives reply text as it streams, so any front-end can
        render it live. Returns the full reply for callers that just want it.
        """
        self.history.append({"role": "user", "content": user_text})

        result = self.provider.complete(
            self.system_prompt,
            self.history,
            on_text=on_text,
        )
        self._account(result)

        # Append the assistant turn so the next turn remembers it. This is the
        # short-term memory; if a reply ever forgets the previous turn, the
        # history isn't being passed back in.
        self.history.append({"role": "assistant", "content": result.text})
        return result.text

    def _account(self, result: TurnResult) -> None:
        self.total_input_tokens += result.input_tokens
        self.total_output_tokens += result.output_tokens
