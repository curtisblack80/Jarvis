"""Text-to-speech seam: give me text, play it aloud.

The reference build uses ElevenLabs (natural voices, streaming). It lives behind
this seam so the voice or provider changes in one place; the voice id is config,
not code.

Playback is stoppable mid-stream so the user can interrupt (barge-in). Sentences
are spoken as they arrive from the brain, so speech starts before the full reply
is written.
"""

from __future__ import annotations

import queue
import threading
from typing import Protocol

from .stt import VoiceUnavailable


class Speaker(Protocol):
    def enqueue(self, text: str) -> None:
        """Queue a sentence to be spoken (returns immediately)."""

    def wait(self) -> None:
        """Block until the queue has drained."""

    def stop(self) -> None:
        """Stop speaking now and drop anything queued (barge-in)."""


class ElevenLabsSpeaker:
    """Speaks queued sentences in order on a background worker, stoppable."""

    def __init__(self, *, api_key: str, voice_id: str, model: str):
        if not voice_id:
            raise VoiceUnavailable(
                "No ElevenLabs voice_id set in config (voice.tts.voice_id)."
            )
        try:
            from elevenlabs.client import ElevenLabs
        except ImportError as exc:  # pragma: no cover - optional dep
            raise VoiceUnavailable(
                "elevenlabs not installed. `pip install elevenlabs`."
            ) from exc
        self._client = ElevenLabs(api_key=api_key)
        self._voice_id = voice_id
        self._model = model

        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._stop = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def enqueue(self, text: str) -> None:
        if text.strip():
            self._q.put(text)

    def wait(self) -> None:
        self._q.join()

    def stop(self) -> None:
        self._stop.set()
        # Drain anything pending so it isn't spoken after the interruption.
        try:
            while True:
                self._q.get_nowait()
                self._q.task_done()
        except queue.Empty:
            pass

    # --- worker ------------------------------------------------------------

    def _run(self) -> None:
        while True:
            text = self._q.get()
            if text is None:
                self._q.task_done()
                return
            if not self._stop.is_set():
                try:
                    self._speak_one(text)
                except Exception:  # noqa: BLE001 - audio glitches shouldn't crash
                    pass
            self._q.task_done()
            # Clear the stop flag once the queue empties, ready for the next turn.
            if self._q.empty():
                self._stop.clear()

    def _speak_one(self, text: str) -> None:
        # Request raw PCM so we can play through sounddevice and cut it off
        # instantly on barge-in, rather than waiting for a clip to finish.
        import numpy as np
        import sounddevice as sd

        sample_rate = 24000
        stream = self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            model_id=self._model,
            text=text,
            output_format="pcm_24000",
        )
        pcm = b"".join(stream)
        samples = np.frombuffer(pcm, dtype=np.int16)
        sd.play(samples, sample_rate)
        # Poll so a stop request can interrupt playback promptly.
        while sd.get_stream().active:
            if self._stop.is_set():
                sd.stop()
                break
            sd.sleep(50)


def build_speaker(config) -> Speaker:
    from ..config import Config

    provider = config.get("voice.tts.provider", "elevenlabs")
    if provider == "elevenlabs":
        key = Config.secret("ELEVENLABS_API_KEY", required=False)
        if not key:
            raise VoiceUnavailable("ELEVENLABS_API_KEY is not set.")
        return ElevenLabsSpeaker(
            api_key=key,
            voice_id=config.get("voice.tts.voice_id", ""),
            model=config.get("voice.tts.model", "eleven_turbo_v2_5"),
        )
    raise VoiceUnavailable(f"Unknown TTS provider: {provider}")
