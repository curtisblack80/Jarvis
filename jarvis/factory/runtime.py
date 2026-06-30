"""Tier 5 — config-driven runtime + hot-reload registry.

Every Factory-spawned agent is *pure configuration*: no class is written per
agent. ``ConfigDrivenAgent`` reads a ``spawned_agents`` row and runs the host's
own tool-use loop (``jarvis.agent.Agent``) with that row's system prompt, model,
and tool allowlist. If you ever feel the urge to branch on a slug, the behavior
belongs in the row's prompt or allowlist — not here.

``RegistryWatcher`` makes newly-approved agents dispatchable without a restart:
it diffs the active rows against the tools currently registered and (un)registers
the matching ``dispatch_to_<slug>`` tool. It reads the agents store fresh each
refresh, so it reflects rows approved by another process (the CLI) too.
"""

from __future__ import annotations

import threading
from typing import Callable

from ..agent import Agent, Confirmer
from ..provider import Provider
from ..tools.base import Tool, ToolRegistry, ToolResult
from .models import SpawnedAgent
from .repo import SpawnedAgentRepo
from .slugs import dispatch_tool_name

# Builds a provider bound to a specific model id (spawned agents may differ from
# the host's default model).
MakeProvider = Callable[[str], Provider]


class ConfigDrivenAgent:
    """One generic runtime, parameterized by a ``spawned_agents`` row."""

    def __init__(
        self,
        row: SpawnedAgent,
        *,
        registry: ToolRegistry,
        provider: Provider,
        confirmer: Confirmer | None = None,
    ):
        self._row = row
        self._registry = registry
        self._provider = provider
        self._confirmer = confirmer

    def _filtered_registry(self) -> ToolRegistry:
        allow = set(self._row.tool_allowlist)
        sub = ToolRegistry()
        for tool in self._registry.list_all():
            if tool.name in allow:
                sub.register(tool)
        return sub

    def run(self, user_message: str) -> str:
        # The same brain every other entry point uses — never forked.
        agent = Agent(
            self._provider,
            self._row.system_prompt,
            registry=self._filtered_registry(),
            confirmer=self._confirmer,
        )
        return agent.send(user_message)


def build_dispatch_tool(
    row: SpawnedAgent,
    *,
    registry: ToolRegistry,
    make_provider: MakeProvider,
    confirmer: Confirmer | None = None,
    load_row: Callable[[str], SpawnedAgent | None] | None = None,
) -> Tool:
    """A uniform ``dispatch_to_<slug>`` tool: input is always ``{message}``.

    The tool re-reads the row at call time (via ``load_row``) so an archived or
    edited agent is respected without rebuilding the tool.
    """
    slug = row.slug

    def _dispatch(args: dict) -> ToolResult:
        current = load_row(slug) if load_row else row
        if current is None or current.status != "active":
            return ToolResult(f"Agent '{slug}' is not available.", is_error=True)
        sub = ConfigDrivenAgent(
            current,
            registry=registry,
            provider=make_provider(current.model),
            confirmer=confirmer,
        )
        return ToolResult(sub.run(args["message"]))

    return Tool(
        name=dispatch_tool_name(slug),
        description=(
            f"Dispatch a request to the {row.name} sub-agent ({row.specialty}). "
            f"Pass the full task as 'message'."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The task for the sub-agent."}
            },
            "required": ["message"],
        },
        fn=_dispatch,
        factory_allowed=False,  # spawned agents don't dispatch to each other
    )


class RegistryWatcher:
    """Keeps the live tool registry in sync with the active spawned agents."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        make_provider: MakeProvider,
        confirmer: Confirmer | None = None,
        load_active: Callable[[], list[SpawnedAgent]] | None = None,
        load_row: Callable[[str], SpawnedAgent | None] | None = None,
    ):
        self._registry = registry
        self._make_provider = make_provider
        self._confirmer = confirmer
        # Default to reading the store fresh each call, so refreshes pick up rows
        # written by another process (the approval CLI).
        self._load_active = load_active or (lambda: SpawnedAgentRepo().list_active())
        self._load_row = load_row or (lambda slug: SpawnedAgentRepo().by_slug(slug))
        self._known: set[str] = set()
        self._stop = threading.Event()

    def refresh(self) -> None:
        rows = {r.slug: r for r in self._load_active()}
        for slug, row in rows.items():
            if slug not in self._known:
                tool = build_dispatch_tool(
                    row,
                    registry=self._registry,
                    make_provider=self._make_provider,
                    confirmer=self._confirmer,
                    load_row=self._load_row,
                )
                self._registry.register(tool, replace=True)
        for slug in self._known - set(rows):
            self._registry.unregister(dispatch_tool_name(slug))
        self._known = set(rows)

    def notify(self, slug: str) -> None:
        """Approval calls this; a targeted refresh keeps the cost trivial."""
        self.refresh()

    # --- optional background polling (host process) ------------------------

    def start_polling(self, interval_seconds: float = 30.0) -> threading.Thread:
        def loop() -> None:
            while not self._stop.is_set():
                try:
                    self.refresh()
                except Exception:  # noqa: BLE001 — a bad refresh must not crash the host
                    pass
                self._stop.wait(interval_seconds)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()
