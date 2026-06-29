# Jarvis

A voice-first AI assistant harness, built tier by tier. See [`AGENT.md`](AGENT.md)
for the spec, the personality, and the build order.

The guiding discipline: **one shared agent core, many ways in and out.** The
brain works in plain text first; voice, memory, and proactivity are layers added
on top — each independently testable.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env        # then fill in ANTHROPIC_API_KEY
```

Secrets live in `.env` (git-ignored). Tunables live in `config.yaml`.

## Run (text)

```bash
python -m jarvis
```

Type to talk; `quit` or Ctrl-D to leave.

## Tiers

| Tier | What it adds | Status |
|------|--------------|--------|
| 1 | The brain — text conversation loop with session memory | ✅ |
| 2 | The hands — tool registry the model can call | ⬜ |
| 3 | The ears & mouth — push-to-talk voice (Deepgram + ElevenLabs) | ⬜ |
| 4 | The memory — durable facts across restarts | ⬜ |
| 5 | The heartbeat — proactive background loop | ⬜ |
| 6 | The rails — confirmation gate, audit log, kill switch | ⬜ |

## Verify

```bash
python tests/test_tier1_brain.py     # core loop, no network needed
```

**Tier 1 by hand:** run `python -m jarvis`, hold a short back-and-forth, and
confirm it remembers earlier turns. Kill and restart it — it forgets everything
(expected; durable memory is Tier 4).
