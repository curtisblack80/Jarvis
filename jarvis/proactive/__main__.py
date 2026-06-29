"""Run the heartbeat on its own:  python -m jarvis.proactive

This is the same loop the chat REPL starts in a thread — here it runs standalone
so it can live on an always-on machine while you talk to Jarvis from elsewhere.
Notices land in the shared inbox (state/inbox.json); the chat front-end shows
them on your next return.
"""

from __future__ import annotations

from .. import control
from ..config import Config
from .checks import build_checks
from .heartbeat import Heartbeat
from .inbox import Inbox


def main() -> int:
    config = Config.load()
    name = config.get("identity.name", "Jarvis")
    inbox = Inbox()

    def announce(notice) -> None:
        print(f"🔔 {name}: {notice.text}  (#{notice.id})", flush=True)

    heartbeat = Heartbeat(
        build_checks(config),
        inbox,
        config,
        on_alert=announce,
        is_paused=control.is_paused,  # honors the kill switch too
    )
    print(f"{name} heartbeat running ({len(heartbeat.checks)} checks). Ctrl-C to stop.")
    try:
        heartbeat.run_forever()
    except KeyboardInterrupt:
        heartbeat.stop()
        print("\nheartbeat stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
