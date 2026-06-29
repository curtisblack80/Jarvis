"""Push-to-talk capture seam.

Push-to-talk first: you control exactly when it listens, which removes a whole
class of "is it listening?" bugs and means the assistant never captures its own
voice. We use a press-Enter-to-start / press-Enter-to-stop toggle here because
it's terminal-portable and unambiguous; a hold-a-key variant can replace this
body without touching the rest of the harness.

Returns a complete WAV clip, which the transcriber consumes.
"""

from __future__ import annotations

import io
import threading
import wave

from .stt import VoiceUnavailable

SAMPLE_RATE = 16000  # Plenty for speech; keeps clips small and STT fast.
CHANNELS = 1


class PushToTalkRecorder:
    """Records from the default mic between two Enter presses."""

    def __init__(self, *, sample_rate: int = SAMPLE_RATE):
        self.sample_rate = sample_rate
        try:
            import numpy  # noqa: F401
            import sounddevice  # noqa: F401
        except ImportError as exc:  # pragma: no cover - optional dep
            raise VoiceUnavailable(
                "sounddevice/numpy not installed. `pip install sounddevice numpy`."
            ) from exc

    def record(self, prompt: str = "Press Enter, speak, press Enter to send", *, on_start=None) -> bytes:
        import sounddevice as sd

        print(f"  🎙  {prompt}…", flush=True)
        input()  # wait for the first Enter to begin
        # Barge-in: starting a new turn silences any reply still being spoken.
        if on_start:
            on_start()

        frames: list[bytes] = []
        stop = threading.Event()

        def callback(indata, _frames, _time, _status):
            frames.append(bytes(indata))

        with sd.RawInputStream(
            samplerate=self.sample_rate,
            channels=CHANNELS,
            dtype="int16",
            callback=callback,
        ):
            print("  ● recording… (Enter to stop)", flush=True)
            input()  # second Enter stops
            stop.set()

        audio = b"".join(frames)
        return self._to_wav(audio)

    def _to_wav(self, pcm: bytes) -> bytes:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)  # int16
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm)
        return buf.getvalue()


def build_recorder(config) -> PushToTalkRecorder:
    return PushToTalkRecorder()
