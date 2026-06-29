"""Speech-to-text seam: give me audio, get back text.

The reference build uses Deepgram (fast, accurate, streaming). It lives behind
this seam so the transcriber can be swapped in one place. The key comes from the
environment, never code.
"""

from __future__ import annotations

from typing import Protocol


class Transcriber(Protocol):
    def transcribe(self, audio: bytes, *, sample_rate: int) -> str:
        """WAV/PCM bytes in, recognized text out."""
        ...


class VoiceUnavailable(RuntimeError):
    """Raised when a voice dependency or key is missing — caller falls back."""


class DeepgramTranscriber:
    """Deepgram prerecorded transcription behind the seam."""

    def __init__(self, *, api_key: str, model: str = "nova-2"):
        try:
            from deepgram import DeepgramClient
        except ImportError as exc:  # pragma: no cover - depends on optional dep
            raise VoiceUnavailable(
                "deepgram-sdk not installed. `pip install deepgram-sdk`."
            ) from exc
        self._client = DeepgramClient(api_key)
        self._model = model

    def transcribe(self, audio: bytes, *, sample_rate: int) -> str:
        # Prerecorded (push-to-talk gives us a complete clip), which keeps this
        # simple; a streaming variant can replace the body later.
        from deepgram import PrerecordedOptions

        source = {"buffer": audio, "mimetype": "audio/wav"}
        options = PrerecordedOptions(model=self._model, smart_format=True)
        resp = self._client.listen.rest.v("1").transcribe_file(source, options)
        return (
            resp.results.channels[0].alternatives[0].transcript.strip()
        )


def build_transcriber(config) -> Transcriber:
    """Construct the configured transcriber. The only place that picks an impl."""
    from ..config import Config

    provider = config.get("voice.stt.provider", "deepgram")
    if provider == "deepgram":
        key = Config.secret("DEEPGRAM_API_KEY", required=False)
        if not key:
            raise VoiceUnavailable("DEEPGRAM_API_KEY is not set.")
        return DeepgramTranscriber(
            api_key=key, model=config.get("voice.stt.model", "nova-2")
        )
    raise VoiceUnavailable(f"Unknown STT provider: {provider}")
