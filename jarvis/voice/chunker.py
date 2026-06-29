"""Sentence chunking for streaming speech.

The brain streams text token by token (Tier 1) and ElevenLabs streams audio
(Tier 3), so we can begin speaking the first sentence while the rest is still
being written. This buffers incoming text deltas and emits complete sentences as
soon as they're ready — the seam that makes the assistant feel responsive
instead of laggy.
"""

from __future__ import annotations

from typing import Callable, Iterable, Iterator

# End-of-sentence punctuation we flush on. Kept simple on purpose.
_ENDERS = ".!?"
# Don't emit a one- or two-character fragment as if it were a sentence.
_MIN_LEN = 2


class SentenceChunker:
    """Feed it text deltas; it yields complete sentences as they finish."""

    def __init__(self) -> None:
        self._buf = ""

    def feed(self, delta: str) -> Iterator[str]:
        self._buf += delta
        while True:
            idx = self._next_boundary(self._buf)
            if idx is None:
                return
            sentence = self._buf[: idx + 1].strip()
            self._buf = self._buf[idx + 1 :]
            if len(sentence) >= _MIN_LEN:
                yield sentence

    def flush(self) -> str | None:
        """Return whatever's left at end of stream (the final partial sentence)."""
        leftover = self._buf.strip()
        self._buf = ""
        return leftover or None

    @staticmethod
    def _next_boundary(text: str) -> int | None:
        for i, ch in enumerate(text):
            if ch in _ENDERS:
                # Don't split inside a decimal like "3.14" — require the next
                # char to be whitespace, end of buffer, or a closing quote.
                nxt = text[i + 1] if i + 1 < len(text) else " "
                if nxt.isspace() or nxt in "\"')]}":
                    return i
        return None


def stream_sentences(deltas: Iterable[str], on_sentence: Callable[[str], None]) -> None:
    """Convenience: drive a chunker over an iterable of deltas."""
    chunker = SentenceChunker()
    for delta in deltas:
        for sentence in chunker.feed(delta):
            on_sentence(sentence)
    tail = chunker.flush()
    if tail:
        on_sentence(tail)
