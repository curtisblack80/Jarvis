"""The spawn pipeline's state machine.

A spawn task walks one path from PENDING to a terminal state. Every transition
is an explicit, allowed edge — invalid transitions fail loudly at the repo
layer rather than letting a task drift into a nonsense state. This is the spine
the whole Factory hangs off: research → spec → prompt → human gate → live.
"""

from __future__ import annotations

from enum import Enum


class State(str, Enum):
    PENDING = "pending"
    RESEARCHING = "researching"
    DRAFTING_SPEC = "drafting_spec"
    WRITING_PROMPT = "writing_prompt"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"      # terminal
    REJECTED = "rejected"      # terminal
    FAILED = "failed"          # terminal

    def __str__(self) -> str:  # so f-strings and CLI prints read cleanly
        return self.value


# Allowed edges. AWAITING_APPROVAL can loop back to WRITING_PROMPT when the
# human rejects with feedback (a revision round), or go terminal otherwise.
_TRANSITIONS: dict[State, set[State]] = {
    State.PENDING:           {State.RESEARCHING, State.FAILED},
    State.RESEARCHING:       {State.DRAFTING_SPEC, State.FAILED},
    State.DRAFTING_SPEC:     {State.WRITING_PROMPT, State.FAILED},
    State.WRITING_PROMPT:    {State.AWAITING_APPROVAL, State.FAILED},
    State.AWAITING_APPROVAL: {State.APPROVED, State.REJECTED,
                              State.WRITING_PROMPT, State.FAILED},
    State.APPROVED:          set(),  # terminal
    State.REJECTED:          set(),  # terminal
    State.FAILED:            set(),  # terminal
}

TERMINAL = {State.APPROVED, State.REJECTED, State.FAILED}


class InvalidTransition(Exception):
    """Raised when code tries to move a task along an edge that doesn't exist."""


def can_transition(src: State, dst: State) -> bool:
    return dst in _TRANSITIONS.get(src, set())


def assert_transition(src: State, dst: State) -> None:
    if not can_transition(src, dst):
        raise InvalidTransition(f"illegal spawn-task transition: {src} -> {dst}")
