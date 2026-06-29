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

## Run (voice, push-to-talk)

```bash
pip install deepgram-sdk elevenlabs sounddevice numpy   # voice extras
# set DEEPGRAM_API_KEY + ELEVENLABS_API_KEY in .env, and a voice id in config.yaml
python -m jarvis --voice
```

Press Enter to start a turn, speak, press Enter to send. It shows the transcript
(`heard › …`) next to its reply, speaks sentence-by-sentence as the reply
streams, and starting a new turn interrupts speech (barge-in). If voice deps or
keys are missing it prints why and falls back to text — the same brain either
way.

## Tiers

| Tier | What it adds | Status |
|------|--------------|--------|
| 1 | The brain — text conversation loop with session memory | ✅ |
| 2 | The hands — tool registry the model can call | ✅ |
| 3 | The ears & mouth — push-to-talk voice (Deepgram + ElevenLabs) | ✅ |
| 4 | The memory — durable facts across restarts | ✅ |
| 5 | The heartbeat — proactive background loop | ⬜ |
| 6 | The rails — confirmation gate, audit log, kill switch | ⬜ |

## Verify

```bash
python tests/test_tier1_brain.py     # core loop, no network needed
python tests/test_tier2_tools.py     # tool registry + tool loop, no network
python tests/test_tier3_voice.py     # chunker + voice-uses-same-brain, no audio
python tests/test_tier4_memory.py    # durable facts survive restart + hand edits
```

**Tier 1 by hand:** run `python -m jarvis`, hold a short back-and-forth, and
confirm it remembers earlier turns. Kill and restart it — it forgets everything
(expected; durable memory is Tier 4).

**Tier 2 by hand:** ask "what's on my list?" or "remind me to buy milk
tomorrow" and watch the tool activity line appear, then a natural reply. Notes
live in `notes/` (any `.md`/`.txt`); ask about something written there.

### First tools

| Tool | Job | Consequential? |
|------|-----|----------------|
| `add_reminder`, `list_reminders` | reminders | no |
| `delete_reminder` | reminders | yes (deletes data) |
| `search_notes` | notes Q&A | no (read-only) |
| `draft_message` | drafting | no (draft only) |
| `send_message` | drafting | yes (sends) |

Add a capability by writing one self-contained tool module and registering it
in `jarvis/tools/__init__.py` — the core loop never changes.

### Memory

Durable facts live in `state/memory.md` — one plain statement per line, fully
human-editable. The assistant loads them into its system prompt each turn (as
background knowledge, **not** commands) and manages them via `remember_fact`,
`update_fact`, and the consequential `forget_fact`. Open the file and correct a
fact by hand; the change is respected on the next run.

**Tier 4 by hand:** tell it your name, quit, restart — it greets you knowing it.
