"""Tier 3 — the spawn pipeline.

Wires Tiers 1 and 2 into one async-friendly state machine that walks a
``spawn_tasks`` row from PENDING to AWAITING_APPROVAL (or FAILED). The whole
``run`` is wrapped so that once a task starts it *always* ends in a terminal
state — an exception becomes a clean FAILED with the error recorded, never a
bubbled crash that strands a task half-built.

The slug is picked and validated *before* any LLM work, so a collision or
reserved-name error costs zero tokens.
"""

from __future__ import annotations

from typing import Any, Callable

from .. import audit
from ..provider import Provider
from ..tools.base import ToolRegistry
from . import research as research_mod
from . import spec as spec_mod
from .models import SkillsReport, SpawnTask
from .repo import ResearchReportRepo, SpawnedAgentRepo, SpawnTaskRepo
from .slugs import pick_slug
from .state import State, TERMINAL

# A broadcast seam: WS frame / Slack / log. Default writes the audit trail.
EmitEvent = Callable[..., None]


def _audit_emit(kind: str, event: dict[str, Any]) -> None:
    audit.log(f"factory_{kind}", **event)


class SpawnPipeline:
    def __init__(
        self,
        *,
        tasks: SpawnTaskRepo,
        agents: SpawnedAgentRepo,
        reports: ResearchReportRepo,
        provider: Provider,
        registry: ToolRegistry,
        config,
        emit_event: EmitEvent = _audit_emit,
    ):
        self.tasks = tasks
        self.agents = agents
        self.reports = reports
        self.provider = provider
        self.registry = registry
        self.config = config
        self.emit_event = emit_event

    def run(self, task_id: str) -> SpawnTask:
        """Walk a task to AWAITING_APPROVAL, or to FAILED on any error."""
        task = self.tasks.get(task_id)
        if task is None:
            raise KeyError(f"no spawn task {task_id}")
        try:
            return self._run(task)
        except Exception as exc:  # noqa: BLE001 — must end in a terminal state
            self._fail(task_id, str(exc))
            raise

    # --- the walk ----------------------------------------------------------

    def _run(self, task: SpawnTask) -> SpawnTask:
        # 1. Pick + validate the slug before any token burns.
        slug = pick_slug(
            task.name_hint,
            taken_slugs=self.agents.slugs(),
            tool_names={t.name for t in self.registry.list_all()},
        )

        # 2. RESEARCHING — Tier 1.
        self._to(task.id, State.RESEARCHING)
        report_row = research_mod.research(
            task.role_description,
            provider=self.provider,
            repo=self.reports,
            allowed_tool_names=self.registry.factory_allowed_names(),
        )
        self.tasks.set_research_report(task.id, report_row.id)
        report = report_row.skills_report()

        # The agent only ever gets factory-allowed tools the report named — the
        # intersection guards against a hallucinated or unsafe tool sneaking in.
        allowed = set(self.registry.factory_allowed_names())
        tool_allowlist = [t for t in report.tools_available if t in allowed]

        model = self.config.get("model.name", "claude-opus-4-8")
        name = task.name_hint.strip()
        specialty = report.domain or task.role_description.strip()[:80]

        # 3. DRAFTING_SPEC — Tier 2 (markdown).
        self._to(task.id, State.DRAFTING_SPEC)
        spec_path = spec_mod.write_spec_markdown(
            slug=slug,
            name=name,
            specialty=specialty,
            role_description=task.role_description,
            special_requirements=task.special_requirements,
            report=report,
            granted_tools=tool_allowlist,
            model=model,
        )

        # 4. WRITING_PROMPT — Tier 2 (system prompt).
        self._to(task.id, State.WRITING_PROMPT)
        system_prompt = spec_mod.generate_system_prompt(
            name=name,
            role_description=task.role_description,
            special_requirements=task.special_requirements,
            report=report,
            provider=self.provider,
        )

        # 5. Build the proposed manifest and stage it on the task row.
        manifest = self._manifest(
            slug=slug,
            name=name,
            specialty=specialty,
            system_prompt=system_prompt,
            tool_allowlist=tool_allowlist,
            model=model,
            task_id=task.id,
            report=report,
            spec_path=str(spec_path),
        )
        self.tasks.set_manifest(task.id, manifest)

        # 6. AWAITING_APPROVAL — surface it for review.
        final = self._to(task.id, State.AWAITING_APPROVAL)
        self.emit_event(
            "ready_for_approval",
            {
                "task_id": task.id,
                "slug": slug,
                "name": name,
                "tools_wishlist": manifest["tools_wishlist"],
            },
        )
        return final

    @staticmethod
    def _manifest(
        *,
        slug: str,
        name: str,
        specialty: str,
        system_prompt: str,
        tool_allowlist: list[str],
        model: str,
        task_id: str,
        report: SkillsReport,
        spec_path: str,
    ) -> dict[str, Any]:
        return {
            "slug": slug,
            "name": name,
            "specialty": specialty,
            "system_prompt": system_prompt,
            "tool_allowlist": tool_allowlist,
            "model": model,
            "created_by_task_id": task_id,
            "spec_path": spec_path,
            # Surfaced to the approval view: the roadmap of tools to build next.
            "tools_wishlist": [
                {"name": w.name, "purpose": w.purpose, "external_dependency": w.external_dependency}
                for w in report.tools_wishlist
            ],
        }

    # --- transitions -------------------------------------------------------

    def _to(self, task_id: str, dst: State) -> SpawnTask:
        task = self.tasks.transition(task_id, dst)
        self.emit_event("state", {"task_id": task_id, "state": dst.value})
        return task

    def _fail(self, task_id: str, message: str) -> None:
        task = self.tasks.get(task_id)
        if task is None or task.state in TERMINAL:
            return
        self.tasks.set_error(task_id, message)
        self.tasks.transition(task_id, State.FAILED)
        self.emit_event("failed", {"task_id": task_id, "error": message})
