"""The Factory CLI — the approval surface and operator console.

    python -m jarvis.factory research "PDF text extraction"
    python -m jarvis.factory spawn --name "doc-summarizer" \
        --role "summarizes long documents into bullet points"
    python -m jarvis.factory pending
    python -m jarvis.factory show <task_id>
    python -m jarvis.factory approve <task_id>
    python -m jarvis.factory reject <task_id> --feedback "less formal"
    python -m jarvis.factory list-agents
    python -m jarvis.factory dispatch <slug> "your message"

``pending`` is the durable re-hydration path: it reads every awaiting_approval
task from disk, so work finished while no one was watching is never invisible.
"""

from __future__ import annotations

import argparse
import json
import sys

from ..config import Config, ConfigError
from .research import research as run_research
from .service import DailyCapReached, FactoryService
from .slugs import SlugError


def _service() -> FactoryService:
    config = Config.load()
    return FactoryService(config)


def _print_task(task) -> None:
    print(f"task {task.id}")
    print(f"  status:      {task.status}")
    print(f"  name_hint:   {task.name_hint}")
    print(f"  role:        {task.role_description}")
    if task.special_requirements:
        print(f"  requirements:{task.special_requirements}")
    print(f"  iterations:  {task.approval_iterations}")
    if task.error:
        print(f"  error:       {task.error}")
    if task.proposed_manifest:
        m = task.proposed_manifest
        print(f"  proposed:    {m['name']} <{m['slug']}>  model={m['model']}")
        print(f"  tools:       {', '.join(m.get('tool_allowlist', [])) or '(none)'}")
        wishlist = m.get("tools_wishlist", [])
        if wishlist:
            print("  wishlist:    " + ", ".join(w["name"] for w in wishlist))
        print("  system_prompt:")
        for line in m["system_prompt"].splitlines():
            print(f"    | {line}")


# --- command handlers ------------------------------------------------------

def cmd_research(svc: FactoryService, args) -> int:
    report = run_research(
        args.domain,
        provider=svc.provider(),
        repo=svc.reports,
        allowed_tool_names=svc.registry.factory_allowed_names(),
    )
    print(json.dumps(report.report, indent=2, ensure_ascii=False))
    return 0


def cmd_create(svc: FactoryService, args) -> int:
    task = svc.create_task(
        name_hint=args.name,
        role_description=args.role,
        special_requirements=args.requirements or "",
    )
    print(f"created task {task.id} (status={task.status})")
    return 0


def cmd_spawn(svc: FactoryService, args) -> int:
    task = svc.create_task(
        name_hint=args.name,
        role_description=args.role,
        special_requirements=args.requirements or "",
    )
    print(f"created task {task.id}; running pipeline…")
    result = svc.run_pipeline(task.id)
    print(f"pipeline finished: status={result.status}")
    if result.error:
        print(f"  error: {result.error}")
    else:
        print(f"  review with: python -m jarvis.factory show {task.id}")
    return 0


def cmd_run_pipeline(svc: FactoryService, args) -> int:
    result = svc.run_pipeline(args.task_id)
    print(f"status={result.status}" + (f" error={result.error}" if result.error else ""))
    return 0


def cmd_pending(svc: FactoryService, args) -> int:
    tasks = svc.pending()
    if not tasks:
        print("nothing awaiting approval.")
        return 0
    print(f"{len(tasks)} awaiting approval (newest first):\n")
    for t in tasks:
        m = t.proposed_manifest or {}
        print(f"  {t.id}  {m.get('name', t.name_hint)} <{m.get('slug', '?')}>"
              f"  (revisions: {t.approval_iterations})")
    return 0


def cmd_show(svc: FactoryService, args) -> int:
    task = svc.get_task(args.task_id)
    if task is None:
        print(f"no such task: {args.task_id}", file=sys.stderr)
        return 1
    _print_task(task)
    return 0


def cmd_approve(svc: FactoryService, args) -> int:
    result = svc.approve(args.task_id)
    print(f"approved: registered dispatch_to_{result['slug']}")
    return 0


def cmd_reject(svc: FactoryService, args) -> int:
    result = svc.reject(args.task_id, feedback=args.feedback)
    print(f"reject result: {result['status']}")
    return 0


def cmd_list_agents(svc: FactoryService, args) -> int:
    agents = svc.list_agents()
    if not agents:
        print("no spawned agents yet.")
        return 0
    for a in agents:
        print(f"  {a.slug:24} {a.status:8} {a.name}  ({a.specialty})")
    return 0


def cmd_dispatch(svc: FactoryService, args) -> int:
    out = svc.dispatch(args.slug, args.message)
    print(out)
    return 0


# --- argument parsing ------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m jarvis.factory")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("research", help="produce a Skills Report for a domain")
    r.add_argument("domain")
    r.set_defaults(func=cmd_research)

    c = sub.add_parser("create", help="create a spawn task (no pipeline run)")
    c.add_argument("--name", required=True)
    c.add_argument("--role", required=True)
    c.add_argument("--requirements", default="")
    c.set_defaults(func=cmd_create)

    s = sub.add_parser("spawn", help="create a task and run the pipeline")
    s.add_argument("--name", required=True)
    s.add_argument("--role", required=True)
    s.add_argument("--requirements", default="")
    s.set_defaults(func=cmd_spawn)

    rp = sub.add_parser("run-pipeline", help="run the pipeline for an existing task")
    rp.add_argument("task_id")
    rp.set_defaults(func=cmd_run_pipeline)

    pe = sub.add_parser("pending", help="list tasks awaiting approval")
    pe.set_defaults(func=cmd_pending)

    sh = sub.add_parser("show", help="show a task and its proposed manifest")
    sh.add_argument("task_id")
    sh.set_defaults(func=cmd_show)

    ap = sub.add_parser("approve", help="approve a task → register the agent")
    ap.add_argument("task_id")
    ap.set_defaults(func=cmd_approve)

    rj = sub.add_parser("reject", help="reject a task (with optional feedback)")
    rj.add_argument("task_id")
    rj.add_argument("--feedback", default=None)
    rj.set_defaults(func=cmd_reject)

    la = sub.add_parser("list-agents", help="list spawned agents")
    la.set_defaults(func=cmd_list_agents)

    di = sub.add_parser("dispatch", help="run a spawned agent on a message")
    di.add_argument("slug")
    di.add_argument("message")
    di.set_defaults(func=cmd_dispatch)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        svc = _service()
        return args.func(svc, args)
    except ConfigError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2
    except (SlugError, DailyCapReached, ValueError, KeyError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
