"""Tier 1 — the research subagent.

Given a one-paragraph role description, produce a JSON-validated Skills Report:
what the new agent should be capable of, which existing tools it needs, and what
it would want that we don't have yet (the "wishlist" — our roadmap for the tool
catalog). It reuses the host's provider seam and Anthropic's server-side web
search, and it is useful on its own, not only inside the Factory.

The reliability trick: on the final iteration we *force* the model to call
``emit_skills_report`` via ``tool_choice``. Worst case is a slightly
under-researched report on the last turn, never an exhausted-iterations crash.
"""

from __future__ import annotations

import re
from typing import Any

from .. import audit
from ..provider import Provider
from .models import ResearchReport, SkillsReport
from .repo import ResearchReportRepo

MAX_ITERATIONS = 8

# Anthropic's server-side web search. Executes within a single model call, so it
# needs no client-side handling — results stream back and the model continues.
WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20250305",
    "name": "web_search",
    "max_uses": 5,
}

EMIT_TOOL: dict[str, Any] = {
    "name": "emit_skills_report",
    "description": (
        "Emit the final structured Skills Report. Call this exactly once, at the "
        "end, after you have gathered evidence with web_search."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "domain": {"type": "string"},
            "competencies": {
                "type": "array",
                "items": {"type": "string"},
                "description": "4-8 concrete capabilities the agent should have.",
            },
            "tools_available": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tool names from the provided catalog the agent can use today.",
            },
            "tools_wishlist": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "purpose": {"type": "string"},
                        "external_dependency": {"type": "string"},
                    },
                    "required": ["name", "purpose"],
                },
                "description": "Tools we DON'T have yet that this agent would need.",
            },
            "design_patterns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 real patterns observed in research.",
            },
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "excerpt": {"type": "string"},
                    },
                    "required": ["url", "title"],
                },
                "description": "5-15 cited sources, each with a short excerpt (<400 chars).",
            },
        },
        "required": ["domain", "competencies", "tools_available", "sources"],
    },
}

_SYSTEM_TEMPLATE = """\
You are a research specialist. Your job: research what an agent that does
{domain} should be capable of, and produce a structured Skills Report.

You have access to web_search. Use it 3-6 times to gather real evidence from
real sources (vendor docs, open-source projects, technical blogs).

You MUST end by calling emit_skills_report with these fields:
- domain: the domain you researched
- competencies: 4-8 concrete capabilities the agent should have
- tools_available: tool names from THIS catalog the agent can use today:
    {catalog}
- tools_wishlist: tools we DON'T have yet that this agent would need, each with
  a name, a purpose, and any external dependency (API, library, service).
- design_patterns: 2-5 real patterns you observed
- sources: 5-15 sources with url + title + short excerpt (<400 chars)

Only list tools in 'tools_available' that appear in the catalog above. Quote
excerpts must be SHORT and clearly attributable.
"""


def normalize_query(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def research(
    domain: str,
    *,
    provider: Provider,
    repo: ResearchReportRepo,
    allowed_tool_names: list[str],
    max_iterations: int = MAX_ITERATIONS,
    use_web_search: bool = True,
    now: float | None = None,
) -> ResearchReport:
    """Produce (or return a cached) Skills Report for ``domain``."""
    query = normalize_query(domain)

    cached = repo.fresh_for_query(query, now=now)
    if cached is not None:
        audit.log("factory_research_cache_hit", query=query)
        return cached

    report = _run_research_loop(
        domain=domain,
        provider=provider,
        allowed_tool_names=allowed_tool_names,
        max_iterations=max_iterations,
        use_web_search=use_web_search,
    )
    saved = repo.save(ResearchReport.new(query, report))
    audit.log(
        "factory_research_done",
        query=query,
        competencies=len(report.competencies),
        sources=len(report.sources),
    )
    return saved


def _run_research_loop(
    *,
    domain: str,
    provider: Provider,
    allowed_tool_names: list[str],
    max_iterations: int,
    use_web_search: bool,
) -> SkillsReport:
    catalog = ", ".join(allowed_tool_names) if allowed_tool_names else "(none)"
    system = _SYSTEM_TEMPLATE.format(domain=domain, catalog=catalog)
    tools: list[dict[str, Any]] = [EMIT_TOOL]
    if use_web_search:
        tools.insert(0, WEB_SEARCH_TOOL)

    messages: list[dict[str, Any]] = [
        {"role": "user", "content": f"Research the domain: {domain}"}
    ]

    for i in range(max_iterations):
        last = i == max_iterations - 1
        # On the final turn, force the emit so we never exhaust the budget.
        tool_choice = {"type": "tool", "name": "emit_skills_report"} if last else None

        result = provider.complete(
            system, messages, tools=tools, tool_choice=tool_choice
        )

        for call in result.tool_calls:
            if call.name == "emit_skills_report":
                return SkillsReport.from_dict(call.arguments)

        # No emit yet — record the model's turn (search results included) and
        # nudge it to keep going toward the structured emit.
        messages.append(
            {"role": "assistant", "content": result.raw_content or result.text or "(thinking)"}
        )
        messages.append(
            {
                "role": "user",
                "content": "Continue researching, then call emit_skills_report.",
            }
        )

    # Forced emit should have returned above; if a provider ignored tool_choice,
    # fail loudly rather than registering a half-built agent.
    raise RuntimeError("research loop ended without an emitted Skills Report")
