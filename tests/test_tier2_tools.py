"""Tier 2 verification — the agent can call tools, chain them, and survive errors.

No network: a scripted fake provider issues tool calls, then a final answer, so
we can prove the whole tool round-trip without a model.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.agent import Agent  # noqa: E402
from jarvis.provider import ToolCall, TurnResult  # noqa: E402
from jarvis.tools.base import Tool, ToolError, ToolRegistry, ToolResult  # noqa: E402


class ScriptedProvider:
    """Returns queued TurnResults in order; records tool_result blocks it sees."""

    def __init__(self, script: list[TurnResult]):
        self._script = list(script)
        self.calls = 0

    def complete(self, system, messages, *, tools=None, on_text=None):
        self.calls += 1
        result = self._script.pop(0)
        if on_text and result.text:
            on_text(result.text)
        return result


def _registry_with(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# --- registry basics ------------------------------------------------------

def test_validation_rejects_missing_and_mistyped_inputs():
    reg = _registry_with(
        Tool(
            name="echo",
            description="echo n",
            input_schema={
                "type": "object",
                "properties": {"n": {"type": "integer"}},
                "required": ["n"],
            },
            fn=lambda a: ToolResult(str(a["n"])),
        )
    )
    assert reg.run("echo", {}).is_error          # missing required
    assert reg.run("echo", {"n": "x"}).is_error  # wrong type
    assert reg.run("echo", {"n": 5}).content == "5"


def test_tool_failure_returns_clean_error_not_crash():
    def boom(_args):
        raise RuntimeError("disk gone")

    reg = _registry_with(
        Tool("boom", "always fails", {"type": "object", "properties": {}}, boom)
    )
    res = reg.run("boom", {})
    assert res.is_error and "boom failed" in res.content


def test_unknown_tool_is_reported():
    assert ToolRegistry().run("nope", {}).is_error


# --- the agent tool loop --------------------------------------------------

def test_agent_runs_a_tool_then_answers():
    reg = _registry_with(
        Tool(
            "add",
            "add two ints",
            {
                "type": "object",
                "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                "required": ["a", "b"],
            },
            fn=lambda x: ToolResult(str(x["a"] + x["b"])),
        )
    )
    provider = ScriptedProvider(
        [
            TurnResult(
                tool_calls=[ToolCall(id="t1", name="add", arguments={"a": 2, "b": 3})],
                raw_content=[{"type": "tool_use", "id": "t1"}],
            ),
            TurnResult(text="That's 5."),
        ]
    )
    agent = Agent(provider, "sys", registry=reg)

    seen = []
    out = agent.send("add 2 and 3", on_tool=lambda n, a: seen.append((n, a)))

    assert out == "That's 5."
    assert seen == [("add", {"a": 2, "b": 3})]
    # History should contain the tool_result feeding back to the model.
    flat = str(agent.history)
    assert "tool_result" in flat and "'content': '5'" in flat


def test_consequential_tool_blocked_when_confirmer_declines():
    ran = {"v": False}

    def do(_a):
        ran["v"] = True
        return ToolResult("done")

    reg = _registry_with(
        Tool("wipe", "deletes things", {"type": "object", "properties": {}}, do,
             consequential=True)
    )
    provider = ScriptedProvider(
        [
            TurnResult(
                tool_calls=[ToolCall(id="w1", name="wipe", arguments={})],
                raw_content=[{"type": "tool_use", "id": "w1"}],
            ),
            TurnResult(text="Okay, left it alone."),
        ]
    )
    agent = Agent(provider, "sys", registry=reg, confirmer=lambda *a: False)
    out = agent.send("wipe it")

    assert out == "Okay, left it alone."
    assert ran["v"] is False  # the gate stopped it
    assert "declined" in str(agent.history)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("Tier 2 tool tests passed ✓")
