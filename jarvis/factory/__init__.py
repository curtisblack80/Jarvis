"""The Factory — a sub-agent that mints other sub-agents.

A "compiler for sub-agents": given "build me an agent that does X", it researches
the role, drafts a spec and system prompt, picks a safe tool allowlist, stages a
proposed manifest, waits for human approval, then registers a first-class,
dispatchable agent — no restart, no bespoke class per agent.

The five tiers, each independently shippable:
  Tier 1  research.py   — structured Skills Report (web search + forced emit)
  Tier 2  spec.py       — spec markdown + system-prompt generation
  Tier 3  pipeline.py   — the PENDING→AWAITING_APPROVAL state machine
  Tier 4  approval.py   — the human-in-the-loop gate (approve / reject / revise)
  Tier 5  runtime.py    — ConfigDrivenAgent + hot-reload RegistryWatcher

``FactoryService`` (service.py) is the façade the CLI (``python -m jarvis.factory``)
and the host wire to.
"""

from __future__ import annotations

from .models import (
    ResearchReport,
    SkillsReport,
    Source,
    SpawnedAgent,
    SpawnTask,
    ToolWishlistEntry,
)
from .runtime import ConfigDrivenAgent, RegistryWatcher, build_dispatch_tool
from .service import DailyCapReached, FactoryService
from .state import State

__all__ = [
    "FactoryService",
    "DailyCapReached",
    "SpawnTask",
    "SpawnedAgent",
    "SkillsReport",
    "Source",
    "ToolWishlistEntry",
    "ResearchReport",
    "State",
    "ConfigDrivenAgent",
    "RegistryWatcher",
    "build_dispatch_tool",
]
