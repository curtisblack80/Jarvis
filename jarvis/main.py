"""Entry point — front-ends over the one shared brain.

Run text (always works):   python -m jarvis
Run push-to-talk voice:    python -m jarvis --voice

The text path is never deleted. It's how every future change gets debugged, and
the graceful fallback when audio misbehaves. Voice (Tier 3) wraps this same
brain; it does not replace it.
"""

from __future__ import annotations

import sys

from .agent import Agent, build_system_prompt
from .config import Config, ConfigError
from .memory import Memory
from .provider import ProviderError, build_provider
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
    agent = Agent(
        provider, build_system_prompt(config), registry=registry, memory=memory
    )

    if want_voice and _start_voice(agent, config, name):
        return 0  # voice ran (and has now exited)
    if want_voice:
        print("[voice] falling back to text — see the message above.\n")

    return _run_text(agent, name, n_tools=len(registry))


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


def _run_text(agent: Agent, name: str, *, n_tools: int) -> int:
    n_facts = len(agent.memory.facts()) if agent.memory else 0
    knows = f", remembering {n_facts} things about you" if n_facts else ""
    print(
        f"{name} is awake with {n_tools} tools{knows}. "
        f"Type to talk; Ctrl-D or 'quit' to leave.\n"
    )

    def show_tool(tool_name: str, args: dict) -> None:
        # While building, it helps to see the hands move.
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
        except ProviderError as exc:
            # The model was slow or unreachable — shrug it off, don't crash.
            print(f"\n[!] I couldn't reach the model just now: {exc}\n")

    # Unreachable, but keeps type checkers happy.


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
