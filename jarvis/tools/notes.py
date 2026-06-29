"""Notes Q&A — the second job. Read-only, so it runs freely.

Searches plain-text/markdown files under the configured notes directory and
returns matching snippets for the model to answer from. Keeping it simple
(keyword scan) is fine to start; the seam is the tool, so a smarter retriever
can replace the body later without touching anything else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import ROOT
from .base import Tool, ToolResult

_NOTES_DIR_DEFAULT = "notes"
_EXTS = {".md", ".txt", ".markdown"}
_MAX_SNIPPETS = 8


def _make_search(notes_dir: Path):
    def _search(args: dict[str, Any]) -> ToolResult:
        query = args["query"].strip().lower()
        terms = [t for t in query.split() if t]
        if not notes_dir.exists():
            return ToolResult(
                f"No notes directory found at {notes_dir}. Add notes there to search them."
            )

        hits: list[str] = []
        for path in sorted(notes_dir.rglob("*")):
            if path.suffix.lower() not in _EXTS or not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for n, line in enumerate(lines):
                low = line.lower()
                if any(term in low for term in terms):
                    hits.append(f"{path.name}:{n + 1}: {line.strip()}")
                    if len(hits) >= _MAX_SNIPPETS:
                        break
            if len(hits) >= _MAX_SNIPPETS:
                break

        if not hits:
            return ToolResult(f"No notes matched '{args['query']}'.")
        return ToolResult("Matching notes:\n" + "\n".join(hits))

    return _search


def tools(config) -> list[Tool]:
    notes_dir = ROOT / config.get("notes.dir", _NOTES_DIR_DEFAULT)
    return [
        Tool(
            name="search_notes",
            description=(
                "Search the user's personal notes for a word or phrase and "
                "return matching lines. Use this to answer questions about what "
                "they've written down. Read-only."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to look for in the notes.",
                    }
                },
                "required": ["query"],
            },
            fn=_make_search(notes_dir),
        )
    ]
