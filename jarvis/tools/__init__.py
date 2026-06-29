"""Tool wiring. ``build_default_registry`` is the one place tools are assembled.

To add a capability: write a self-contained tool module and register it here.
The core loop never changes.
"""

from __future__ import annotations

from ..memory import Memory
from .base import Tool, ToolRegistry, ToolResult
from . import drafting, memory_tools, notes, reminders

__all__ = ["Tool", "ToolRegistry", "ToolResult", "build_default_registry"]


def build_default_registry(config, memory: Memory | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in reminders.tools():
        registry.register(tool)
    for tool in notes.tools(config):
        registry.register(tool)
    for tool in drafting.tools():
        registry.register(tool)
    if memory is not None:
        for tool in memory_tools.tools(memory):
            registry.register(tool)
    return registry
