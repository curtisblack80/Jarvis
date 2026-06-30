"""The Factory's data shapes.

Two "tables" (spawn_tasks, spawned_agents) plus a cached research_reports store,
all dataclasses persisted as plain JSON under ``state/factory/`` — same
human-readable, hand-correctable storage the rest of Jarvis uses. The
``SkillsReport`` family is the validated structured output of Tier 1.

Validation is deliberately lightweight and dependency-free (no Pydantic in the
host's requirements): each model has a ``from_dict`` that coerces and a
``validate`` that raises ``ReportError`` on a malformed payload, so a model that
emits garbage fails cleanly instead of poisoning a spawned agent.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from .state import State


class ReportError(ValueError):
    """A structured payload from the model failed validation."""


def _new_id() -> str:
    return uuid.uuid4().hex


def _now() -> float:
    return time.time()


# --- Tier 1: the Skills Report -------------------------------------------

@dataclass
class Source:
    url: str
    title: str
    excerpt: str = ""

    def __post_init__(self) -> None:
        if len(self.excerpt) > 400:  # keep cited excerpts short + attributable
            self.excerpt = self.excerpt[:397] + "..."


@dataclass
class ToolWishlistEntry:
    name: str
    purpose: str
    external_dependency: str = ""


@dataclass
class SkillsReport:
    domain: str
    competencies: list[str] = field(default_factory=list)
    tools_available: list[str] = field(default_factory=list)
    tools_wishlist: list[ToolWishlistEntry] = field(default_factory=list)
    design_patterns: list[str] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkillsReport":
        if not isinstance(data, dict):
            raise ReportError("skills report must be an object")
        try:
            report = cls(
                domain=str(data.get("domain", "")).strip(),
                competencies=[str(c).strip() for c in data.get("competencies", []) if str(c).strip()],
                tools_available=[str(t).strip() for t in data.get("tools_available", []) if str(t).strip()],
                tools_wishlist=[
                    ToolWishlistEntry(
                        name=str(w.get("name", "")).strip(),
                        purpose=str(w.get("purpose", "")).strip(),
                        external_dependency=str(w.get("external_dependency", "")).strip(),
                    )
                    for w in data.get("tools_wishlist", [])
                    if isinstance(w, dict) and str(w.get("name", "")).strip()
                ],
                design_patterns=[str(p).strip() for p in data.get("design_patterns", []) if str(p).strip()],
                sources=[
                    Source(
                        url=str(s.get("url", "")).strip(),
                        title=str(s.get("title", "")).strip(),
                        excerpt=str(s.get("excerpt", "")).strip(),
                    )
                    for s in data.get("sources", [])
                    if isinstance(s, dict) and str(s.get("url", "")).strip()
                ],
            )
        except (AttributeError, TypeError) as exc:
            raise ReportError(f"malformed skills report: {exc}") from exc
        report.validate()
        return report

    def validate(self) -> None:
        if not self.domain:
            raise ReportError("skills report missing 'domain'")
        if not self.competencies:
            raise ReportError("skills report has no competencies")
        if len(self.sources) < 1:
            raise ReportError("skills report cites no sources")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ResearchReport:
    """A cached SkillsReport keyed by a normalized query, for 24h dedup."""

    id: str
    query: str            # normalized query the report answers
    report: dict[str, Any]  # SkillsReport.to_dict()
    created_at: float = field(default_factory=_now)

    @classmethod
    def new(cls, query: str, report: SkillsReport) -> "ResearchReport":
        return cls(id=_new_id(), query=query, report=report.to_dict())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResearchReport":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def skills_report(self) -> SkillsReport:
        return SkillsReport.from_dict(self.report)


# --- the spawn task -------------------------------------------------------

@dataclass
class SpawnTask:
    id: str
    requested_by: str
    name_hint: str
    role_description: str
    special_requirements: str = ""
    status: str = State.PENDING.value
    research_report_id: str | None = None
    proposed_manifest: dict[str, Any] | None = None
    approval_iterations: int = 0
    revision_feedback: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=_now)

    @classmethod
    def new(
        cls,
        *,
        requested_by: str,
        name_hint: str,
        role_description: str,
        special_requirements: str = "",
    ) -> "SpawnTask":
        return cls(
            id=_new_id(),
            requested_by=requested_by,
            name_hint=name_hint,
            role_description=role_description,
            special_requirements=special_requirements,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpawnTask":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def state(self) -> State:
        return State(self.status)


# --- the spawned agent (pure configuration) ------------------------------

@dataclass
class SpawnedAgent:
    id: str
    slug: str
    name: str
    specialty: str
    system_prompt: str
    tool_allowlist: list[str]
    model: str
    status: str = "active"  # 'active' | 'archived'
    created_by_task_id: str | None = None
    created_at: float = field(default_factory=_now)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpawnedAgent":
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
