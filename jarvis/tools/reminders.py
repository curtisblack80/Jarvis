"""Reminder tools — the first of the three jobs.

add/list are everyday capabilities and run freely. delete removes data, so it is
flagged consequential and will pass through the Tier 6 confirmation gate.
"""

from __future__ import annotations

import time
from typing import Any

from ..storage import load_json, save_json
from .base import Tool, ToolResult

_FILE = "reminders.json"


def _load() -> list[dict[str, Any]]:
    return load_json(_FILE, [])


def _save(items: list[dict[str, Any]]) -> None:
    save_json(_FILE, items)


def _add(args: dict[str, Any]) -> ToolResult:
    items = _load()
    item = {
        "id": int(time.time() * 1000),
        "text": args["text"].strip(),
        "when": args.get("when", "").strip(),
        "done": False,
    }
    items.append(item)
    _save(items)
    when = f" ({item['when']})" if item["when"] else ""
    return ToolResult(f"Saved reminder #{item['id']}: {item['text']}{when}")


def _list(args: dict[str, Any]) -> ToolResult:
    items = [i for i in _load() if not i.get("done")]
    if not items:
        return ToolResult("No active reminders.")
    lines = [
        f"#{i['id']}: {i['text']}" + (f" ({i['when']})" if i.get("when") else "")
        for i in items
    ]
    return ToolResult("Active reminders:\n" + "\n".join(lines))


def _delete(args: dict[str, Any]) -> ToolResult:
    target = int(args["id"])
    items = _load()
    kept = [i for i in items if i["id"] != target]
    if len(kept) == len(items):
        return ToolResult(f"No reminder with id {target}.", is_error=True)
    _save(kept)
    return ToolResult(f"Deleted reminder #{target}.")


def tools() -> list[Tool]:
    return [
        Tool(
            name="add_reminder",
            description=(
                "Save a reminder for the user. Use whenever they ask to be "
                "reminded of something or to note a task for later."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to remember."},
                    "when": {
                        "type": "string",
                        "description": "Optional natural-language time, e.g. 'tomorrow 9am'.",
                    },
                },
                "required": ["text"],
            },
            fn=_add,
        ),
        Tool(
            name="list_reminders",
            description="List the user's active (not-yet-done) reminders.",
            input_schema={"type": "object", "properties": {}, "required": []},
            fn=_list,
        ),
        Tool(
            name="delete_reminder",
            description=(
                "Delete a reminder by its numeric id. This removes data, so it "
                "requires the user's confirmation."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "The reminder id to delete."}
                },
                "required": ["id"],
            },
            fn=_delete,
            consequential=True,  # deletes data
            factory_allowed=False,  # destructive — keep out of spawned agents' hands
        ),
    ]
