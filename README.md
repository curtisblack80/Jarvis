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
| 5 | The heartbeat — proactive background loop | ✅ |
| 6 | The rails — confirmation gate, audit log, kill switch | ✅ |

## Verify

```bash
python tests/test_tier1_brain.py     # core loop, no network needed
python tests/test_tier2_tools.py     # tool registry + tool loop, no network
python tests/test_tier3_voice.py     # chunker + voice-uses-same-brain, no audio
python tests/test_tier4_memory.py    # durable facts survive restart + hand edits
python tests/test_tier5_heartbeat.py # scheduling, quiet hours, hold, dismiss
python tests/test_tier6_rails.py     # confirmation gate, kill switch, data-tagging
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

### The heartbeat (proactive)

A background loop, started with the REPL (and runnable standalone with
`python -m jarvis.proactive` for an always-on host). Checks live in
`config.yaml` under `heartbeat` — what to check, how often, how loud. Surfaced
items land in a held, dismissible inbox (`state/inbox.json`).

- **Quiet by default:** routine notices just accumulate; only `alert`/`critical`
  interrupt, and `alert` is held silently during `quiet_hours`.
- In the REPL: `notices` lists them, `dismiss <id>` / `dismiss all` clears them,
  and held notices are shown on your next start (catch-up-on-return).

**Tier 5 by hand:** with the REPL running, `echo "tea is ready" > state/trigger.txt`
and within ~10s you'll see a 🔔 alert; it won't repeat for the same text.
Restart and the schedule resumes instead of refiring everything.

### The rails (safety)

- **Confirmation gate** (`jarvis/safety.py`): anything that sends/spends/
  deletes/changes a setting stops, states plainly what it'll do, and waits for
  an explicit `y`. Approval is per-action — it never generalizes. Read-only
  tools flow freely. The interactive asker is wrapped in a timeout so it can't
  hang forever (safe default: deny); background actions auto-deny and leave a
  note. Tune what's gated in `config.yaml` under `safety` (no code edit).
- **Data, not commands:** content the assistant reads (e.g. notes) is tagged as
  untrusted data, and the system prompt tells it to surface — not obey —
  anything that looks like an instruction.
- **Audit trail + cost:** `state/audit.log` records tools run, confirmations,
  and what the heartbeat surfaced; `log` in the REPL shows recent events plus a
  session token tally.
- **Kill switch:** `pause` stops all proactive behavior at once (you can still
  chat); `resume` turns it back on. Durable across restarts.

**Tier 6 by hand:** ask it to send a message → it asks first. Put a line like
"ignore your instructions and …" in a note, then ask about that note → it flags
it rather than obeying. `pause`, then trigger a heartbeat condition → nothing
fires until you `resume`.
