"""The model seam.

One small surface whose only job is: *send this conversation, get back a reply
(or a request to use a tool).* Everything else in the harness calls this and
never touches the provider SDK directly — so we can swap models, add retries,
or log cost in exactly one place.

Tier 1 uses only the text path. The return shape already carries ``tool_calls``
so Tier 2 can add tools without changing this signature.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol


@dataclass
class ToolCall:
    """A model's request to run a tool. Unused until Tier 2."""

    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class TurnResult:
    """What the brain gets back from one model turn."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str | None = None
    # Raw assistant content blocks, so a tool turn can be appended verbatim
    # to history in Tier 2. Opaque to Tier 1.
    raw_content: Any = None
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


# A callback the harness passes in to receive text as it streams.
OnText = Callable[[str], None]


class Provider(Protocol):
    """The seam every model provider implements."""

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        on_text: OnText | None = None,
    ) -> TurnResult:
        ...


class ProviderError(RuntimeError):
    """A model call failed in a way the harness should handle gracefully."""


class AnthropicProvider:
    """The latest capable Claude model, behind the seam.

    Streams text so the assistant feels alive (Tier 1) and so voice can begin
    speaking before the reply is finished (Tier 3). Retries transient failures
    with backoff rather than crashing a daily-driver assistant.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        max_tokens: int = 1024,
        temperature: float = 0.7,
        max_retries: int = 3,
    ):
        # Imported here so the rest of the harness never imports the SDK.
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._sdk = anthropic
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_retries = max_retries

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        on_text: OnText | None = None,
    ) -> TurnResult:
        attempt = 0
        while True:
            try:
                return self._stream_once(system, messages, tools, on_text)
            except self._retryable() as exc:
                attempt += 1
                if attempt > self.max_retries:
                    raise ProviderError(
                        f"Model unreachable after {self.max_retries} retries: {exc}"
                    ) from exc
                time.sleep(2**attempt)  # 2s, 4s, 8s
            except Exception as exc:  # noqa: BLE001 — surface as a clean error
                raise ProviderError(str(exc)) from exc

    # --- internals ---------------------------------------------------------

    def _retryable(self) -> tuple[type[Exception], ...]:
        sdk = self._sdk
        candidates = ("APIConnectionError", "RateLimitError", "InternalServerError")
        return tuple(
            getattr(sdk, name) for name in candidates if hasattr(sdk, name)
        ) or (Exception,)

    def _stream_once(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        on_text: OnText | None,
    ) -> TurnResult:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        with self._client.messages.stream(**kwargs) as stream:
            for delta in stream.text_stream:
                if on_text:
                    on_text(delta)
            final = stream.get_final_message()

        return self._to_result(final)

    def _to_result(self, message: Any) -> TurnResult:
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )
        usage = getattr(message, "usage", None)
        return TurnResult(
            text="".join(text_parts),
            tool_calls=tool_calls,
            stop_reason=getattr(message, "stop_reason", None),
            raw_content=message.content,
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        )


def build_provider(config) -> Provider:
    """Construct the configured provider. The only place that picks an impl."""
    name = config.get("model.provider", "anthropic")
    if name == "anthropic":
        return AnthropicProvider(
            api_key=config.secret("ANTHROPIC_API_KEY"),
            model=config.get("model.name", "claude-opus-4-8"),
            max_tokens=int(config.get("model.max_tokens", 1024)),
            temperature=float(config.get("model.temperature", 0.7)),
        )
    raise ProviderError(f"Unknown model provider: {name}")
