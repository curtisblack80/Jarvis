"""Tier 4 — the human-in-the-loop approval gate.

A proposed manifest sits in AWAITING_APPROVAL until a human decides:

  - **approve** → insert a row into ``spawned_agents``, flip the task to
    APPROVED, and tell the registry to load the new dispatch tool (Tier 5).
  - **reject with feedback** → roll back to WRITING_PROMPT, regenerate *only*
    the system prompt (research and spec are cached — don't burn the budget),
    and re-stage for review. Capped at ``max_iterations`` rounds.
  - **reject with no feedback** → terminal REJECTED.

Skipping this gate is the one anti-pattern that defeats the whole design: it is
how a prompt-injection payload would reach a registered agent. The gate is the
point.
"""

from __future__ import annotations

from typing import Any, Callable

from .. import audit
from ..provider import Provider
from . import spec as spec_mod
from .models import SpawnedAgent, _new_id
from .repo import ResearchReportRepo, SpawnedAgentRepo, SpawnTaskRepo
from .state import State

NotifyRegistry = Callable[[str], None]
EmitEvent = Callable[..., None]


def _noop_emit(kind: str, event: dict[str, Any]) -> None:
    audit.log(f"factory_{kind}", **event)


def _noop_notify(slug: str) -> None:
    pass


def handle_approve(
    *,
    task_id: str,
    tasks: SpawnTaskRepo,
    agents: SpawnedAgentRepo,
    notify_registry: NotifyRegistry = _noop_notify,
    emit_event: EmitEvent = _noop_emit,
) -> dict[str, Any]:
    task = tasks.get(task_id)
    if task is None:
        raise KeyError(f"no spawn task {task_id}")
    if task.state is not State.AWAITING_APPROVAL:
        raise ValueError("task not in approvable state")
    p = task.proposed_manifest or {}

    agent = SpawnedAgent(
        id=_new_id(),
        slug=p["slug"],
        name=p["name"],
        specialty=p["specialty"],
        system_prompt=p["system_prompt"],
        tool_allowlist=list(p.get("tool_allowlist", [])),
        model=p["model"],
        status="active",
        created_by_task_id=task_id,
    )
    agents.save(agent)
    tasks.transition(task_id, State.APPROVED)
    notify_registry(agent.slug)  # hot-load the dispatch tool (Tier 5)
    emit_event(
        "agent_added",
        {
            "slug": agent.slug,
            "name": agent.name,
            # The row key on the approval surface — without it the UI can't tell
            # which pending card just resolved.
            "created_by_task_id": task_id,
        },
    )
    return {"status": "approved", "slug": agent.slug}


def handle_reject(
    *,
    task_id: str,
    tasks: SpawnTaskRepo,
    reports: ResearchReportRepo,
    provider: Provider,
    feedback: str | None = None,
    max_iterations: int = 3,
    emit_event: EmitEvent = _noop_emit,
) -> dict[str, Any]:
    task = tasks.get(task_id)
    if task is None:
        raise KeyError(f"no spawn task {task_id}")
    if task.state is not State.AWAITING_APPROVAL:
        raise ValueError("task not in approvable state")

    feedback = (feedback or "").strip()
    if not feedback:
        tasks.transition(task_id, State.REJECTED)
        emit_event("rejected", {"task_id": task_id})
        return {"status": "rejected"}

    # Reject-with-feedback: record it, then enforce the revision cap.
    task = tasks.set_revision_feedback(task_id, feedback)
    if task.approval_iterations >= max_iterations:
        tasks.set_error(task_id, f"rejected {task.approval_iterations}x; revision cap reached")
        tasks.transition(task_id, State.FAILED)
        emit_event("failed", {"task_id": task_id, "error": "revision cap reached"})
        return {"status": "failed", "reason": "revision cap reached"}

    # Re-run Tier 2 ONLY. Research + spec are cached on the task row.
    manifest = dict(task.proposed_manifest or {})
    report_row = reports.get(task.research_report_id) if task.research_report_id else None
    if report_row is None:
        raise ValueError("cannot revise: research report missing from task")
    report = report_row.skills_report()

    tasks.transition(task_id, State.WRITING_PROMPT)
    new_prompt = spec_mod.generate_system_prompt(
        name=manifest["name"],
        role_description=task.role_description,
        special_requirements=task.special_requirements,
        report=report,
        provider=provider,
        prior_prompt=manifest.get("system_prompt"),
        revision_feedback=feedback,
    )
    manifest["system_prompt"] = new_prompt
    tasks.set_manifest(task_id, manifest)
    tasks.transition(task_id, State.AWAITING_APPROVAL)
    emit_event(
        "ready_for_approval",
        {"task_id": task_id, "slug": manifest["slug"], "name": manifest["name"],
         "tools_wishlist": manifest.get("tools_wishlist", [])},
    )
    return {"status": "awaiting_approval", "approval_iterations": task.approval_iterations}
