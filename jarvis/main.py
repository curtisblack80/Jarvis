"""Entry point — front-ends over the one shared brain.

Run text (always works):   python -m jarvis
Run push-to-talk voice:    python -m jarvis --voice

The text path is never deleted. It's how every future change gets debugged, and
the graceful fallback when audio misbehaves. Voice (Tier 3) wraps this same
brain; it does not replace it.
"""

from __future__ import annotations

import sys

from . import audit, control
from .agent import Agent, build_system_prompt
from .config import Config, ConfigError
from .memory import Memory
from .provider import ProviderError, build_provider
from .safety import ConfirmationGate, interactive_asker, timeout_asker
from .tools import build_default_registry


def run(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    want_voice = "--voice" in argv

    try:
        config = Config.load()
        provider = build_provider(config)
    except ConfigError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2

    name = config.get("identity.name", "Jarvis")
    memory = Memory()
    registry = build_default_registry(config, memory=memory)

    # The confirmation gate: a human asker, wrapped in a timeout so it can never
    # hang forever (safe default = deny). Same gate covers every front-end.
    gate = ConfirmationGate(
        config,
        timeout_asker(
            interactive_asker(),
            float(config.get("safety.confirm_timeout_seconds", 120)),
        ),
    )
    agent = Agent(
        provider,
        build_system_prompt(config),
        registry=registry,
        memory=memory,
        confirmer=gate.confirm,
    )

    # Wire in the Factory: register the `dispatch_to_factory` tool so the user
    # can design new sub-agents by voice/text, load already-approved agents into
    # the live registry, and poll for newly-approved ones — all without a
    # restart (Tier 5). Approval stays a typed command (see _run_text).
    factory = _start_factory(config, registry, gate.confirm)

    inbox = _start_heartbeat(config, name)

    if want_voice and _start_voice(agent, config, name):
        return 0  # voice ran (and has now exited)
    if want_voice:
        print("[voice] falling back to text — see the message above.\n")

    return _run_text(agent, name, n_tools=len(registry), inbox=inbox, factory=factory)


def _start_factory(config, registry, confirmer):
    """Build the shared Factory service, register its `dispatch_to_factory`
    tool, and start watching for approved agents. Returns the service so the
    REPL can drive its human approval commands, or None on failure.

    Best-effort: a Factory that isn't set up must never stop the assistant from
    starting, so any failure here is swallowed.
    """
    try:
        from .factory.service import FactoryService

        # Share the live registry + confirmer so designed agents see the real
        # tool catalog and approved ones register straight into this session.
        factory = FactoryService(config, registry=registry, confirmer=confirmer)
        registry.register(factory.factory_tool(), replace=True)
        factory.watcher.start_polling(float(config.get("factory.watch_seconds", 30)))
        return factory
    except Exception:  # noqa: BLE001 — never block startup on the Factory
        return None


def _start_heartbeat(config, name: str):
    """Start the proactive loop in a background thread; return its inbox.

    Laptop-first: it beats while this process runs. The loop is front-end
    agnostic — the same inbox can be read from text or voice — and relocatable
    to an always-on host later.
    """
    from .proactive.checks import build_checks
    from .proactive.heartbeat import Heartbeat
    from .proactive.inbox import Inbox

    inbox = Inbox()
    if not config.get("heartbeat.enabled", True):
        return inbox

    def announce(notice) -> None:
        # An alert interrupts: print it where the user will see it.
        print(f"\n\n  🔔 {name}: {notice.text}  (#{notice.id})\nyou › ", end="", flush=True)

    heartbeat = Heartbeat(
        build_checks(config),
        inbox,
        config,
        on_alert=announce,
        is_paused=control.is_paused,  # the kill switch
    )
    heartbeat.start()
    return inbox


def _start_voice(agent: Agent, config, name: str) -> bool:
    """Try to start the voice session. Returns False to fall back to text."""
    from .voice.stt import VoiceUnavailable

    try:
        from .voice.audio import build_recorder
        from .voice.session import VoiceSession
        from .voice.stt import build_transcriber
        from .voice.tts import build_speaker

        session = VoiceSession(
            agent,
            recorder=build_recorder(config),
            transcriber=build_transcriber(config),
            speaker=build_speaker(config),
            name=name,
        )
    except VoiceUnavailable as exc:
        print(f"[voice] unavailable: {exc}")
        return False

    session.run()
    return True


def _run_text(agent: Agent, name: str, *, n_tools: int, inbox=None, factory=None) -> int:
    n_facts = len(agent.memory.facts()) if agent.memory else 0
    knows = f", remembering {n_facts} things about you" if n_facts else ""
    factory_help = "\n  factory: pending · show <id> · approve <id> · reject <id> <feedback>" if factory else ""
    print(
        f"{name} is awake with {n_tools} tools{knows}.\n"
        f"  commands: notices · dismiss <id> · pause · resume · log · quit"
        f"{factory_help}\n"
    )

    # Catch-up-on-return: show anything the heartbeat held while you were away.
    if inbox and inbox.pending():
        print(f"  While you were away, {name} noted:")
        for n in inbox.pending():
            print(n.pretty())
        print("  (type 'dismiss <id>' to clear, or 'dismiss all')\n")

    def show_tool(tool_name: str, args: dict) -> None:
        # While building, it helps to see the hands move — and it's the audit
        # trail for which tools ran.
        audit.log("tool_call", tool=tool_name, args=_brief(args))
        print(f"\n  · {tool_name}({_brief(args)})", flush=True)
        print(f"{name} › ", end="", flush=True)

    while True:
        try:
            user_text = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print(f"\n{name}: bye.")
            return 0

        if not user_text:
            continue
        if user_text.lower() in {"quit", "exit"}:
            print(f"{name}: bye.")
            return 0
        if inbox is not None and _handle_inbox_command(user_text, inbox):
            continue
        if factory is not None and _handle_factory_command(user_text, factory):
            continue
        if _handle_control_command(user_text, name, agent):
            continue

        # Stream the reply as it's generated — feels alive, and it's the same
        # streaming voice will lean on in Tier 3.
        print(f"{name} › ", end="", flush=True)
        try:
            agent.send(
                user_text,
                on_text=lambda chunk: print(chunk, end="", flush=True),
                on_tool=show_tool,
            )
            print("\n")
            audit.log(
                "turn",
                in_tokens=agent.total_input_tokens,
                out_tokens=agent.total_output_tokens,
            )
        except ProviderError as exc:
            # The model was slow or unreachable — shrug it off, don't crash.
            print(f"\n[!] I couldn't reach the model just now: {exc}\n")

    # Unreachable, but keeps type checkers happy.


def _handle_control_command(text: str, name: str, agent: Agent) -> bool:
    """Handle the kill switch and audit log commands."""
    low = text.lower().strip()
    if low in {"pause", "kill", "stop proactive"}:
        control.set_paused(True)
        audit.log("kill_switch", paused=True)
        print(f"  ⏸  Proactive behavior paused. You can still talk to {name}.\n")
        return True
    if low in {"resume", "unpause"}:
        control.set_paused(False)
        audit.log("kill_switch", paused=False)
        print("  ▶  Proactive behavior resumed.\n")
        return True
    if low in {"log", "audit"}:
        events = audit.tail(15)
        if not events:
            print("  (audit log empty)\n")
        for e in events:
            extra = {k: v for k, v in e.items() if k not in {"ts", "event"}}
            print(f"  {e['event']}: {extra}")
        cost = (
            f"  ~tokens this session: in={agent.total_input_tokens} "
            f"out={agent.total_output_tokens}\n"
        )
        print(cost)
        return True
    return False


def _handle_inbox_command(text: str, inbox) -> bool:
    """Handle 'notices' and 'dismiss …'. Returns True if it was such a command."""
    low = text.lower()
    if low in {"notices", "inbox"}:
        pending = inbox.pending()
        if not pending:
            print("  Nothing in the inbox.\n")
        else:
            for n in pending:
                print(n.pretty())
            print()
        return True
    if low.startswith("dismiss"):
        arg = text[len("dismiss"):].strip()
        if arg in {"all", "*"}:
            print(f"  Cleared {inbox.dismiss_all()} notice(s).\n")
        elif arg.isdigit() and inbox.dismiss(int(arg)):
            print(f"  Dismissed #{arg}.\n")
        else:
            print("  Usage: dismiss <id> | dismiss all\n")
        return True
    return False


def _handle_factory_command(text: str, factory) -> bool:
    """Handle the human side of the Factory: 'factory pending | show <id> |
    approve <id> | reject <id> <feedback>'. Returns True if it was such a
    command.

    Approval lives here, as a *typed* command, on purpose: the model can design
    an agent (via the dispatch_to_factory tool) but only the human makes it live.
    """
    low = text.lower().strip()
    if low != "factory" and not low.startswith("factory "):
        return False

    parts = text.split(maxsplit=2)  # ["factory", "<verb>", "<rest>"]
    verb = parts[1].lower() if len(parts) > 1 else "pending"
    rest = parts[2] if len(parts) > 2 else ""

    try:
        if verb in {"pending", "list"}:
            tasks = factory.pending()
            if not tasks:
                print("  Nothing awaiting approval.\n")
            else:
                print(f"  {len(tasks)} awaiting approval (newest first):")
                for t in tasks:
                    m = t.proposed_manifest or {}
                    print(f"    {t.id}  {m.get('name', t.name_hint)} "
                          f"<{m.get('slug', '?')}>  (revisions: {t.approval_iterations})")
                print()
        elif verb == "agents":
            agents = factory.list_agents()
            if not agents:
                print("  No spawned agents yet.\n")
            else:
                for a in agents:
                    print(f"    {a.slug:24} {a.status:8} {a.name}  ({a.specialty})")
                print()
        elif verb == "show":
            task = factory.get_task(rest.strip())
            if task is None:
                print(f"  No such task: {rest.strip()}\n")
            else:
                _print_factory_task(task)
        elif verb == "approve":
            res = factory.approve(rest.strip())
            print(f"  ✓ Approved — dispatch_to_{res['slug']} is now live.\n")
        elif verb == "reject":
            bits = rest.split(maxsplit=1)
            task_id = bits[0].strip() if bits else ""
            feedback = bits[1].strip() if len(bits) > 1 else None
            res = factory.reject(task_id, feedback=feedback)
            print(f"  reject → {res['status']}"
                  + (f" ({res['error']})" if res.get("error") else "") + "\n")
        else:
            print("  Usage: factory pending | agents | show <id> | "
                  "approve <id> | reject <id> <feedback>\n")
    except (KeyError, ValueError) as exc:
        print(f"  Factory: {exc}\n")
    return True


def _print_factory_task(task) -> None:
    m = task.proposed_manifest or {}
    print(f"  task {task.id}  (status: {task.status}, revisions: {task.approval_iterations})")
    if task.error:
        print(f"    last error: {task.error}")
    if m:
        print(f"    {m['name']} <{m['slug']}> — {m['specialty']}")
        print(f"    tools: {', '.join(m.get('tool_allowlist', [])) or 'none'}")
        print("    system prompt:")
        for line in m.get("system_prompt", "").splitlines():
            print(f"      | {line}")
    print()


def _brief(args: dict) -> str:
    """A short one-line render of tool arguments for the activity line."""
    parts = []
    for key, value in args.items():
        text = str(value).replace("\n", " ")
        if len(text) > 40:
            text = text[:37] + "..."
        parts.append(f"{key}={text}")
    return ", ".join(parts)


if __name__ == "__main__":
    raise SystemExit(run())
