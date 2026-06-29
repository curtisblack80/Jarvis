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

    inbox = _start_heartbeat(config, name)

    if want_voice and _start_voice(agent, config, name):
        return 0  # voice ran (and has now exited)
    if want_voice:
        print("[voice] falling back to text — see the message above.\n")

    return _run_text(agent, name, n_tools=len(registry), inbox=inbox)


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


def _run_text(agent: Agent, name: str, *, n_tools: int, inbox=None) -> int:
    n_facts = len(agent.memory.facts()) if agent.memory else 0
    knows = f", remembering {n_facts} things about you" if n_facts else ""
    print(
        f"{name} is awake with {n_tools} tools{knows}.\n"
        f"  commands: notices · dismiss <id> · pause · resume · log · quit\n"
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
