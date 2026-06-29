"""The tool registry — the assistant's hands.

A tool is a named capability with a reader-friendly description and a typed,
validated input schema. The model decides when to call one; the harness runs it
and feeds the result back. Adding a capability later means writing one
self-contained tool and registering it — never editing the core loop.

Each tool declares whether it is ``consequential`` (sends, spends, deletes, or
changes a setting). The flag is set here in Tier 2; the confirmation gate that
acts on it is built in Tier 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolResult:
    """The outcome of running a tool, handed back to the model as text."""

    content: str
    is_error: bool = False


# A tool's body: takes validated args, returns a ToolResult (or a bare string).
ToolFn = Callable[[dict[str, Any]], "ToolResult | str"]


@dataclass
class Tool:
    name: str
    description: str  # Written for the model to read — say *when* to use it.
    input_schema: dict[str, Any]  # JSON-schema object: properties + required.
    fn: ToolFn
    # True if it sends, spends, deletes, or changes a setting (Tier 6 gates it).
    consequential: bool = False

    def spec(self) -> dict[str, Any]:
        """The provider-facing tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolError(Exception):
    """Raised by validation or a tool body to return a clean error to the model."""


class ToolRegistry:
    """Holds tools, exposes their specs, and dispatches calls by name."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[dict[str, Any]]:
        """All tool specs, handed to the model each turn."""
        return [t.spec() for t in self._tools.values()]

    def is_consequential(self, name: str) -> bool:
        tool = self._tools.get(name)
        return bool(tool and tool.consequential)

    def __len__(self) -> int:
        return len(self._tools)

    def run(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        """Validate inputs, run the tool, and always return a ToolResult.

        A failing tool returns a plain-language error *to the model* rather than
        crashing — the agent reasoning over a failed result is a feature.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(f"No such tool: {name}", is_error=True)

        try:
            self._validate(tool, arguments)
            out = tool.fn(arguments)
        except ToolError as exc:
            return ToolResult(f"{name} could not run: {exc}", is_error=True)
        except Exception as exc:  # noqa: BLE001 — never crash the loop on a tool
            return ToolResult(f"{name} failed unexpectedly: {exc}", is_error=True)

        if isinstance(out, ToolResult):
            return out
        return ToolResult(str(out))

    # --- lightweight input validation -------------------------------------

    @staticmethod
    def _validate(tool: Tool, arguments: dict[str, Any]) -> None:
        schema = tool.input_schema
        props: dict[str, Any] = schema.get("properties", {})
        required: list[str] = schema.get("required", [])

        for key in required:
            if key not in arguments or arguments[key] in (None, ""):
                raise ToolError(f"missing required input '{key}'")

        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, value in arguments.items():
            if key not in props:
                continue  # Be lenient about extras; only police declared inputs.
            expected = props[key].get("type")
            py_type = type_map.get(expected)
            if py_type and not isinstance(value, py_type):
                raise ToolError(
                    f"input '{key}' should be {expected}, got {type(value).__name__}"
                )
