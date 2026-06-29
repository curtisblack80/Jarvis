"""The Factory façade — the one object the CLI and host wire to.

Holds a single shared instance of each repo, the live tool registry, a lazily
built provider, and the registry watcher. It enforces the two creation-time caps
(daily spawn limit, input sanitization) and exposes the verbs the approval
surface needs: create, run, pending, approve, reject, list, dispatch.

Provider construction is lazy so read-only verbs (pending / show / list) work
without an API key.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .. import audit
from ..provider import Provider, build_provider
from ..tools import build_default_registry
from ..tools.base import ToolRegistry
from . import approval
from .models import SpawnTask
from .pipeline import SpawnPipeline
from .repo import ResearchReportRepo, SpawnedAgentRepo, SpawnTaskRepo
from .runtime import ConfigDrivenAgent, RegistryWatcher
from .sanitize import sanitize
from .slugs import pick_slug, slugify
from .state import TERMINAL

# Strong references to background pipeline threads so a fire-and-forget run can't
# be collected mid-flight (the threaded analogue of the asyncio weak-ref trap).
_IN_FLIGHT: set[threading.Thread] = set()


class DailyCapReached(RuntimeError):
    """The requester has staged their allowance of new agents for the day."""


class FactoryService:
    def __init__(
        self,
        config,
        *,
        registry: ToolRegistry | None = None,
        provider: Provider | None = None,
        confirmer: Callable | None = None,
    ):
        self.config = config
        self.tasks = SpawnTaskRepo()
        self.agents = SpawnedAgentRepo()
        self.reports = ResearchReportRepo()
        self.registry = registry if registry is not None else build_default_registry(config)
        self._provider = provider
        self._injected_provider = provider is not None  # test/explicit override
        self.confirmer = confirmer
        self.daily_cap = int(config.get("factory.daily_cap", 5))
        self.max_revisions = int(config.get("factory.max_revisions", 3))

        self.watcher = RegistryWatcher(
            registry=self.registry,
            make_provider=self.make_provider,
            confirmer=confirmer,
            load_active=lambda: self.agents.list_active(),
            load_row=lambda slug: self.agents.by_slug(slug),
        )
        self.watcher.refresh()  # load already-approved agents on startup

    # --- providers ---------------------------------------------------------

    def provider(self) -> Provider:
        if self._provider is None:
            self._provider = build_provider(self.config)
        return self._provider

    def make_provider(self, model: str) -> Provider:
        # A spawned agent may run on a different model than the host default.
        # Honor an explicitly injected provider (tests); otherwise build one
        # bound to this agent's own model rather than reusing the host's.
        if self._injected_provider:
            return self._provider
        return build_provider(self.config, model=model)

    # --- create (daily cap + sanitization enforced here) -------------------

    def _inflight_slugs(self) -> set[str]:
        """Slugs claimed by tasks that haven't reached a terminal state yet."""
        return {
            slugify(t.name_hint)
            for t in self.tasks.all()
            if t.state not in TERMINAL
        }

    def create_task(
        self,
        *,
        name_hint: str,
        role_description: str,
        special_requirements: str = "",
        requested_by: str = "owner",
    ) -> SpawnTask:
        # Sanitize at the front door — before anything is stored or dispatched.
        role = sanitize(role_description, field="role description")
        reqs = sanitize(special_requirements, field="special requirements") if special_requirements else ""
        name = sanitize(name_hint, field="name").strip()

        # Fail the cheap, obvious checks before recording the task. Reserve the
        # slugs of in-flight (non-terminal) tasks too, so two same-named tasks
        # can't both be staged and then collide when both are approved.
        taken = self.agents.slugs() | self._inflight_slugs()
        pick_slug(
            name,
            taken_slugs=taken,
            tool_names={t.name for t in self.registry.list_all()},
        )

        # Daily cap: enforced at creation so a flood of tasks can't be queued
        # even if approvals are gated.
        since = time.time() - 24 * 60 * 60
        if self.tasks.count_created_since(requested_by, since) >= self.daily_cap:
            raise DailyCapReached(
                f"daily spawn cap of {self.daily_cap} reached for {requested_by}"
            )

        task = SpawnTask.new(
            requested_by=requested_by,
            name_hint=name,
            role_description=role,
            special_requirements=reqs,
        )
        self.tasks.save(task)
        audit.log("factory_task_created", task_id=task.id, name=name)
        return task

    # --- run the pipeline --------------------------------------------------

    def _pipeline(self) -> SpawnPipeline:
        return SpawnPipeline(
            tasks=self.tasks,
            agents=self.agents,
            reports=self.reports,
            provider=self.provider(),
            registry=self.registry,
            config=self.config,
        )

    def run_pipeline(self, task_id: str) -> SpawnTask:
        return self._pipeline().run(task_id)

    def run_pipeline_background(self, task_id: str) -> threading.Thread:
        """Fire-and-forget run, holding a strong ref so it can't be collected."""
        def go() -> None:
            try:
                self._pipeline().run(task_id)
            except Exception:  # noqa: BLE001 — pipeline already records FAILED
                pass

        thread = threading.Thread(target=go, daemon=True)
        _IN_FLIGHT.add(thread)
        thread.start()
        thread_done = threading.Thread(
            target=lambda: (thread.join(), _IN_FLIGHT.discard(thread)), daemon=True
        )
        thread_done.start()
        return thread

    # --- approval surface --------------------------------------------------

    def pending(self) -> list[SpawnTask]:
        """All awaiting_approval tasks — the durable re-hydration path."""
        return self.tasks.awaiting_approval()

    def get_task(self, task_id: str) -> SpawnTask | None:
        return self.tasks.get(task_id)

    def approve(self, task_id: str) -> dict[str, Any]:
        return approval.handle_approve(
            task_id=task_id,
            tasks=self.tasks,
            agents=self.agents,
            notify_registry=self.watcher.notify,
        )

    def reject(self, task_id: str, feedback: str | None = None) -> dict[str, Any]:
        return approval.handle_reject(
            task_id=task_id,
            tasks=self.tasks,
            reports=self.reports,
            provider=self.provider(),
            feedback=feedback,
            max_iterations=self.max_revisions,
        )

    # --- run a spawned agent ----------------------------------------------

    def list_agents(self):
        return self.agents.all()

    def dispatch(self, slug: str, message: str) -> str:
        row = self.agents.by_slug(slug)
        if row is None or row.status != "active":
            raise KeyError(f"no active agent '{slug}'")
        agent = ConfigDrivenAgent(
            row,
            registry=self.registry,
            provider=self.make_provider(row.model),
            confirmer=self.confirmer,
        )
        return agent.run(message)
