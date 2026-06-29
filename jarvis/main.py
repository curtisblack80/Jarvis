"""Entry point — the typed interface (the brain's first, permanent front-end).

Run with:  python -m jarvis

The text path is never deleted. It's how every future change gets debugged, and
the graceful fallback when audio misbehaves (Tier 3 wraps this, it does not
replace it).
"""

from __future__ import annotations

import sys

from .agent import Agent, build_system_prompt
from .config import Config, ConfigError
from .provider import ProviderError, build_provider
from .tools import build_default_registry


def run() -> int:
    try:
        config = Config.load()
        provider = build_provider(config)
    except ConfigError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2

    name = config.get("identity.name", "Jarvis")
    registry = build_default_registry(config)
    agent = Agent(provider, build_system_prompt(config), registry=registry)

    print(
        f"{name} is awake with {len(registry)} tools. "
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
