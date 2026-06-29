"""The voice front-end — a thin adapter over the shared brain.

A spoken turn is: capture audio (push-to-talk) → transcribe → **call the exact
same Agent.send a typed turn uses** → speak the reply sentence by sentence as it
streams. The brain is not touched here. The seams (recorder, transcriber,
speaker) are injected, which is also what lets the tests drive this with fakes.
"""

from __future__ import annotations

from ..agent import Agent
from .chunker import SentenceChunker


class VoiceSession:
    def __init__(self, agent: Agent, recorder, transcriber, speaker, *, name="Jarvis"):
        self.agent = agent
        self.recorder = recorder
        self.transcriber = transcriber
        self.speaker = speaker
        self.name = name

    def run(self) -> None:
        print(
            f"{self.name} is listening (push-to-talk). "
            f"Press Enter to start/stop a turn; Ctrl-C to leave.\n"
        )
        try:
            while True:
                self._one_turn()
        except (KeyboardInterrupt, EOFError):
            self.speaker.stop()
            print(f"\n{self.name}: bye.")

    def _one_turn(self) -> None:
        # Pressing Enter to begin also cuts off any reply still being spoken
        # (barge-in), via on_start.
        audio = self.recorder.record(on_start=self.speaker.stop)
        print("  …thinking", flush=True)  # a sign the moment they release

        text = self.transcriber.transcribe(audio, sample_rate=self.recorder.sample_rate)
        if not text:
            print("  (heard nothing — try again)\n")
            return

        # Always show what it THOUGHT it heard, next to the reply, so a wrong
        # answer can be traced to the ears vs. the brain.
        print(f"  heard › {text}")
        print(f"{self.name} › ", end="", flush=True)

        self._answer(text)

    def _answer(self, text: str) -> None:
        chunker = SentenceChunker()

        def on_text(delta: str) -> None:
            print(delta, end="", flush=True)  # keep the printed path alive too
            for sentence in chunker.feed(delta):
                self.speaker.enqueue(sentence)  # speak as sentences complete

        # The same entry point a typed turn uses. One brain, many ways in.
        self.agent.send(text, on_text=on_text)

        tail = chunker.flush()
        if tail:
            self.speaker.enqueue(tail)
        print("\n")
        self.speaker.wait()
