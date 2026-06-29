"""Proactive layer — the heartbeat.

A background loop, separate from the conversation loop, that lets the assistant
act without being spoken to: wake on an interval, run small checks, decide
whether anything is worth your attention, and surface only what counts.

Guiding principle: **quiet by default.** It earns interruptions; it doesn't
assume them. Most checks produce nothing most of the time; routine notices
accumulate in a calm inbox you can glance at, and only genuinely noteworthy
things interrupt. Notices are held for catch-up-on-return, never fired into the
void. The loop doesn't care which machine it runs on, so it can move to an
always-on host later as a relocation, not a rewrite.
"""
