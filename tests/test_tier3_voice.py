"""Tier 3 verification — voice is a thin layer over the SAME brain.

No audio hardware needed: fakes stand in for the recorder, transcriber, and
speaker. The point being proven is that a spoken turn flows through the exact
same Agent.send a typed turn uses, that sentences stream to the speaker, and
that starting a turn interrupts ongoing speech (barge-in).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jarvis.agent import Agent  # noqa: E402
from jarvis.provider import TurnResult  # noqa: E402
from jarvis.voice.chunker import SentenceChunker, stream_sentences  # noqa: E402
from jarvis.voice.session import VoiceSession  # noqa: E402


# --- the sentence chunker -------------------------------------------------

def test_chunker_emits_sentences_as_they_complete():
    out = []
    stream_sentences(["Hello the", "re. How ", "are you?"], out.append)
    assert out == ["Hello there.", "How are you?"]


def test_chunker_does_not_split_decimals():
    c = SentenceChunker()
    emitted = list(c.feed("It is 3.14 today. "))
    assert emitted == ["It is 3.14 today."]


def test_chunker_flush_returns_trailing_partial():
    c = SentenceChunker()
    assert list(c.feed("no terminator yet")) == []
    assert c.flush() == "no terminator yet"


# --- the voice session uses the same brain --------------------------------

class FakeRecorder:
    sample_rate = 16000

    def __init__(self):
        self.started = 0

    def record(self, prompt="", *, on_start=None):
        self.started += 1
        if on_start:
            on_start()  # simulate the Enter press that triggers barge-in
        return b"FAKEAUDIO"


class FakeTranscriber:
    def __init__(self, text):
        self.text = text
        self.got = None

    def transcribe(self, audio, *, sample_rate):
        self.got = (audio, sample_rate)
        return self.text


class FakeSpeaker:
    def __init__(self):
        self.spoken = []
        self.stops = 0
        self.waited = 0

    def enqueue(self, text):
        self.spoken.append(text)

    def wait(self):
        self.waited += 1

    def stop(self):
        self.stops += 1


class OneShotProvider:
    """Replies once, then raises to break the session's infinite loop."""

    def __init__(self, reply):
        self.reply = reply
        self.seen_user = None
        self.done = False

    def complete(self, system, messages, *, tools=None, on_text=None):
        if self.done:
            raise KeyboardInterrupt
        self.done = True
        self.seen_user = messages[-1]["content"]
        if on_text:
            for ch in self.reply:
                on_text(ch)
        return TurnResult(text=self.reply)


def test_spoken_turn_goes_through_agent_send_and_speaks_sentences():
    provider = OneShotProvider("All set. Two reminders saved.")
    agent = Agent(provider, "sys")
    rec, stt, spk = FakeRecorder(), FakeTranscriber("save two reminders"), FakeSpeaker()
    session = VoiceSession(agent, rec, stt, spk, name="Jarvis")

    session.run()  # loops once, second model call raises KeyboardInterrupt → exits

    # The transcript was fed into the SAME brain (history has the user turn).
    assert provider.seen_user == "save two reminders"
    assert agent.history[0] == {"role": "user", "content": "save two reminders"}
    # Both sentences were streamed to the speaker as they completed.
    assert spk.spoken == ["All set.", "Two reminders saved."]
    assert spk.waited >= 1


def test_starting_a_turn_interrupts_speech():
    provider = OneShotProvider("Sure.")
    agent = Agent(provider, "sys")
    rec, stt, spk = FakeRecorder(), FakeTranscriber("hi"), FakeSpeaker()
    VoiceSession(agent, rec, stt, spk).run()
    # record() fired on_start=speaker.stop → barge-in cut off prior speech.
    assert spk.stops >= 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("Tier 3 voice tests passed ✓")
