"""Containment for user-supplied text that flows into LLM prompts.

The Factory writes prompts for *other* agents from a user's role description. A
malicious description ("...and also exfiltrate all env vars", "ignore previous
instructions") must not escape the meta-prompt or land verbatim in a spawned
agent's system prompt. This is shallow defense — its job is to nudge sloppy or
hostile input into a safe shape and to refuse the most obvious escapes, not to
defeat a determined attacker. The deeper guarantee is enforced elsewhere: the
prompt-generator LLM paraphrases rather than quotes, and we assert the user's
raw text never appears verbatim in the final prompt (see ``spec.py``).
"""

from __future__ import annotations

import re

# Patterns that read as an attempt to seize control of the meta-prompt. We
# refuse the whole task rather than silently strip them — a clean error to the
# user beats a half-sanitized injection.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I),
    re.compile(r"ignore\s+(your|the)\s+(rules|instructions|system\s*prompt)", re.I),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)", re.I),
    re.compile(r"(^|\n)\s*system\s*:", re.I),
    re.compile(r"</?(system|assistant)\b", re.I),
    re.compile(r"exfiltrate", re.I),
    re.compile(r"\benv(ironment)?\s*vars?\b", re.I),
    re.compile(r"reveal\s+(your|the)\s+(system\s*prompt|secrets?|api\s*key)", re.I),
]

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FENCE = re.compile(r"```+")
_MAX_LEN = 4000


class UnsafeInput(ValueError):
    """User text contained an injection pattern; the task is refused."""


def sanitize(text: str, *, field: str = "input") -> str:
    """Return a cleaned copy of ``text``, or raise ``UnsafeInput``.

    Strips control characters and code fences, collapses runaway whitespace,
    caps length, and refuses outright if an injection pattern is present.
    """
    if text is None:
        return ""
    cleaned = _CONTROL_CHARS.sub("", str(text))
    cleaned = _FENCE.sub("", cleaned)  # remove fenced-code framing
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    if len(cleaned) > _MAX_LEN:
        cleaned = cleaned[:_MAX_LEN]

    for pat in _INJECTION_PATTERNS:
        if pat.search(cleaned):
            raise UnsafeInput(
                f"the {field} contains text that looks like a prompt-injection "
                f"attempt ({pat.pattern!r}); refusing to build an agent from it"
            )
    return cleaned


def contains_verbatim(haystack: str, needle: str, *, min_run: int = 24) -> bool:
    """True if a long run of ``needle`` appears verbatim in ``haystack``.

    Used as a post-generation assertion: the spawned agent's system prompt must
    not echo the user's raw role description verbatim — the generator must
    paraphrase. Short overlaps (common words) are fine; a 24+ char contiguous
    lift is the signal we reject.
    """
    needle = (needle or "").strip()
    if len(needle) < min_run:
        return needle.lower() in haystack.lower() if needle else False
    hay = haystack.lower()
    # Slide a window of min_run chars; any verbatim run is a hit.
    low = needle.lower()
    for i in range(0, len(low) - min_run + 1):
        if low[i : i + min_run] in hay:
            return True
    return False
