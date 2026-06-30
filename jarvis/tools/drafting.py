"""Drafting — the third job.

``draft_message`` only *produces* text and hands it back; it never sends, so it
runs freely. Actually sending is a separate, consequential capability (a stub
here) that must pass through the Tier 6 confirmation gate — drafting and sending
are deliberately kept apart.
"""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult


def _draft(args: dict[str, Any]) -> ToolResult:
    # The model writes the draft itself; this tool just frames and returns it so
    # the draft is an explicit artifact the user can approve or edit.
    recipient = args.get("recipient", "").strip()
    to = f" to {recipient}" if recipient else ""
    body = args["body"].strip()
    return ToolResult(f"Draft{to}:\n\n{body}\n\n(Not sent — say the word to send it.)")


def _send(args: dict[str, Any]) -> ToolResult:
    # Intentionally not wired to any channel yet. When a real sender is added it
    # stays consequential=True so the confirmation gate always covers it.
    return ToolResult(
        "Sending isn't connected to a channel yet. Add a sender and it will go "
        "out only after you confirm.",
        is_error=True,
    )


def tools() -> list[Tool]:
    return [
        Tool(
            name="draft_message",
            description=(
                "Compose a draft message (email, text, note) and return it for "
                "the user to review. Use when they ask you to write or draft "
                "something. Does NOT send."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "body": {"type": "string", "description": "The drafted message text."},
                    "recipient": {
                        "type": "string",
                        "description": "Optional name of who it's for.",
                    },
                },
                "required": ["body"],
            },
            fn=_draft,
        ),
        Tool(
            name="send_message",
            description=(
                "Send a previously drafted message. Consequential: this reaches "
                "another person and cannot be undone, so it requires confirmation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "Who to send to."},
                    "body": {"type": "string", "description": "The message to send."},
                },
                "required": ["recipient", "body"],
            },
            fn=_send,
            consequential=True,  # sends a message
            factory_allowed=False,  # reaches another person — never hand to spawned agents
        ),
    ]
