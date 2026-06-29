"""Tools that let the assistant manage its own long-term memory.

remember/update are everyday learning and run freely. forget removes data, so it
is flagged consequential and passes through the Tier 6 confirmation gate.
"""

from __future__ import annotations

from typing import Any

from ..memory import Memory
from .base import Tool, ToolResult


def tools(memory: Memory) -> list[Tool]:
    def remember(args: dict[str, Any]) -> ToolResult:
        return ToolResult(memory.add(args["fact"]))

    def update(args: dict[str, Any]) -> ToolResult:
        return ToolResult(memory.update(args["match"], args["new_fact"]))

    def forget(args: dict[str, Any]) -> ToolResult:
        return ToolResult(memory.forget(args["match"]))

    return [
        Tool(
            name="remember_fact",
            description=(
                "Store one durable fact about the user — a preference, an "
                "identity, a decision worth keeping across conversations. Use "
                "for lasting things, not the play-by-play of one chat. One clear "
                "statement per call."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "fact": {
                        "type": "string",
                        "description": "A single plain statement, e.g. 'Prefers morning meetings.'",
                    }
                },
                "required": ["fact"],
            },
            fn=remember,
        ),
        Tool(
            name="update_fact",
            description=(
                "Replace a stale stored fact with a corrected one. 'match' is "
                "any text from the existing fact."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "match": {"type": "string", "description": "Text identifying the fact."},
                    "new_fact": {"type": "string", "description": "The corrected statement."},
                },
                "required": ["match", "new_fact"],
            },
            fn=update,
        ),
        Tool(
            name="forget_fact",
            description=(
                "Remove a stored fact. 'match' is any text from it. This deletes "
                "data, so it requires the user's confirmation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "match": {"type": "string", "description": "Text identifying the fact to remove."}
                },
                "required": ["match"],
            },
            fn=forget,
            consequential=True,  # deletes data
            factory_allowed=False,  # destructive — keep out of spawned agents' hands
        ),
    ]
