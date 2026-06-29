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


def run() -> int:
    try:
        config = Config.load()
        provider = build_provider(config)
    except ConfigError as exc:
        print(f"[config] {exc}", file=sys.stderr)
        return 2

    name = config.get("identity.name", "Jarvis")
    agent = Agent(provider, build_system_prompt(config))

    print(f"{name} is awake. Type to talk; Ctrl-D or 'quit' to leave.\n")

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
            agent.send(user_text, on_text=lambda chunk: print(chunk, end="", flush=True))
            print("\n")
        except ProviderError as exc:
            # The model was slow or unreachable — shrug it off, don't crash.
            print(f"\n[!] I couldn't reach the model just now: {exc}\n")

    # Unreachable, but keeps type checkers happy.


if __name__ == "__main__":
    raise SystemExit(run())
