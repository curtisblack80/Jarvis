"""JSON-backed repositories for the Factory's three stores.

Jarvis has no SQL database — durable state is plain JSON under ``state/`` via
``jarvis.storage``. So the "tables" the architecture calls for become small
repos over JSON files: human-readable, hand-correctable, and consistent with
how reminders, memory, and the heartbeat already persist.

The task repo owns the one privileged operation — ``transition`` — which is the
*only* sanctioned way to change a task's status, and it refuses illegal edges
via the state machine. Everything that moves a task goes through here.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from ..storage import load_json, save_json
from .models import ResearchReport, SpawnedAgent, SpawnTask
from .state import State, assert_transition

_TASKS_FILE = "factory_spawn_tasks.json"
_AGENTS_FILE = "factory_spawned_agents.json"
_REPORTS_FILE = "factory_research_reports.json"

# Optional broadcast on every state change: a WebSocket frame, a log line, a
# Slack ping. Jarvis has no event bus, so the default is the audit log (wired in
# the pipeline); this seam keeps the repo from caring which.
EmitEvent = Callable[..., None]


class SpawnTaskRepo:
    def __init__(self) -> None:
        self._items: dict[str, SpawnTask] = {
            d["id"]: SpawnTask.from_dict(d) for d in load_json(_TASKS_FILE, [])
        }

    def _save(self) -> None:
        save_json(_TASKS_FILE, [t.to_dict() for t in self._items.values()])

    def get(self, task_id: str) -> SpawnTask | None:
        return self._items.get(task_id)

    def save(self, task: SpawnTask) -> SpawnTask:
        self._items[task.id] = task
        self._save()
        return task

    def all(self) -> list[SpawnTask]:
        return sorted(self._items.values(), key=lambda t: t.created_at, reverse=True)

    def awaiting_approval(self) -> list[SpawnTask]:
        """Every task ready for review. The durable re-hydration path: a CLI
        ``pending`` / web ``GET /pending`` calls this on load, so work finished
        while no one was looking is never invisible."""
        return [t for t in self.all() if t.state is State.AWAITING_APPROVAL]

    def count_created_since(self, requested_by: str, since_ts: float) -> int:
        return sum(
            1
            for t in self._items.values()
            if t.requested_by == requested_by and t.created_at >= since_ts
        )

    def transition(self, task_id: str, dst: State) -> SpawnTask:
        """The only sanctioned status change. Refuses illegal edges loudly."""
        task = self._require(task_id)
        assert_transition(task.state, dst)
        task.status = dst.value
        self._save()
        return task

    def set_error(self, task_id: str, message: str) -> SpawnTask:
        task = self._require(task_id)
        task.error = message
        self._save()
        return task

    def set_research_report(self, task_id: str, report_id: str) -> SpawnTask:
        task = self._require(task_id)
        task.research_report_id = report_id
        self._save()
        return task

    def set_manifest(self, task_id: str, manifest: dict[str, Any]) -> SpawnTask:
        task = self._require(task_id)
        task.proposed_manifest = manifest
        self._save()
        return task

    def set_revision_feedback(self, task_id: str, feedback: str) -> SpawnTask:
        task = self._require(task_id)
        task.revision_feedback = feedback
        task.approval_iterations += 1
        self._save()
        return task

    def _require(self, task_id: str) -> SpawnTask:
        task = self._items.get(task_id)
        if task is None:
            raise KeyError(f"no spawn task {task_id}")
        return task


class SpawnedAgentRepo:
    def __init__(self) -> None:
        self._items: dict[str, SpawnedAgent] = {
            d["id"]: SpawnedAgent.from_dict(d) for d in load_json(_AGENTS_FILE, [])
        }

    def _save(self) -> None:
        save_json(_AGENTS_FILE, [a.to_dict() for a in self._items.values()])

    def save(self, agent: SpawnedAgent) -> SpawnedAgent:
        self._items[agent.id] = agent
        self._save()
        return agent

    def by_slug(self, slug: str) -> SpawnedAgent | None:
        for a in self._items.values():
            if a.slug == slug:
                return a
        return None

    def slugs(self) -> set[str]:
        return {a.slug for a in self._items.values()}

    def all(self) -> list[SpawnedAgent]:
        return sorted(self._items.values(), key=lambda a: a.created_at)

    def list_active(self) -> list[SpawnedAgent]:
        return [a for a in self.all() if a.status == "active"]

    def archive(self, slug: str) -> bool:
        agent = self.by_slug(slug)
        if agent is None or agent.status == "archived":
            return False
        agent.status = "archived"
        self._save()
        return True


class ResearchReportRepo:
    """Caches Skills Reports for 24h dedup on the normalized query."""

    TTL_SECONDS = 24 * 60 * 60

    def __init__(self) -> None:
        self._items: list[ResearchReport] = [
            ResearchReport.from_dict(d) for d in load_json(_REPORTS_FILE, [])
        ]

    def _save(self) -> None:
        save_json(_REPORTS_FILE, [r.to_dict() for r in self._items])

    def get(self, report_id: str) -> ResearchReport | None:
        for r in self._items:
            if r.id == report_id:
                return r
        return None

    def fresh_for_query(self, query: str, *, now: float | None = None) -> ResearchReport | None:
        now = time.time() if now is None else now
        for r in self._items:
            if r.query == query and (now - r.created_at) < self.TTL_SECONDS:
                return r
        return None

    def save(self, report: ResearchReport) -> ResearchReport:
        self._items.append(report)
        self._save()
        return report
