"""Provider abstraction for Namma Agent (cloud-only brain).

Every provider — native OpenAI / Anthropic / Google, or the generic
OpenAI-compatible adapter (opencode / LM Studio / Ollama / custom) — normalizes
its wire format **into the same neutral types** so the agent loop never has to
know which backend it is talking to.

Neutral message schema (what the agent builds and passes around):

    {"role": "system",    "content": str}
    {"role": "user",      "content": str}
    {"role": "assistant", "content": str, "tool_calls": [ToolCall, ...]}   # tool_calls optional
    {"role": "tool",      "tool_call_id": str, "name": str, "content": str}

Neutral tool schema (what ToolRegistry emits; providers translate it):

    {"name": str, "description": str, "parameters": <JSON Schema dict>}

`generate()` always returns a final :class:`LLMResponse`. When ``stream=True``
and an ``on_token`` callback is supplied, the provider invokes it with each text
delta as it arrives (used to drive the GUI typewriter + TTS) while still
accumulating the full response to return.
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# A callback that receives streamed text chunks as they arrive.
TokenCallback = Callable[[str], None]

# A callback that receives streamed *reasoning* ("thinking") chunks as they arrive,
# kept separate from the visible answer so the UI can show a collapsible Thinking
# section. Only fires for models that emit reasoning (Claude extended thinking when
# enabled, OpenAI/DeepSeek reasoning models, Gemini thoughts).
ThinkingCallback = Callable[[str], None]

# Canonical per-call usage keys every provider normalizes into. Splitting cache
# reads out of `input_tokens` is what keeps the turn total honest: on a multi-step
# tool loop the same conversation prefix is re-sent each step, and with prompt
# caching the provider serves it as a cheap *cache read* rather than billing it as
# fresh input. Lumping those re-reads into `input_tokens` (or summing a non-cached
# `input_tokens` across steps) re-bills the same context N times and inflates the
# reported total far past what the provider's usage dashboard shows.
#   input_tokens       — new, full-rate input tokens
#   output_tokens      — generated tokens
#   cache_read_tokens  — prefix served from the prompt cache (re-reads; ~0.1x cost)
#   cache_write_tokens — tokens written into the cache on this call
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


def usage_tokens(usage: Optional[dict]) -> int:
    """Headline token count for a turn — the genuinely new work the provider bills
    at full rate (fresh input + cache writes + output). Cheap cache *reads* are
    excluded on purpose: they're the same prompt prefix re-served on every tool-loop
    step, so counting them would re-bill one context many times over."""
    if not usage:
        return 0
    return (
        (usage.get("input_tokens", 0) or 0)
        + (usage.get("cache_write_tokens", 0) or 0)
        + (usage.get("output_tokens", 0) or 0)
    )


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""

    id: str
    name: str
    args: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Normalized result of one model call, identical across providers."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    finish_reason: str = ""
    provider: str = ""
    model: str = ""
    ok: bool = True
    error: str = ""
    raw: Any = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class ProviderError(RuntimeError):
    """Raised on unrecoverable provider failure (after retries)."""


class Provider(ABC):
    """Abstract base for all LLM providers.

    Subclasses implement :meth:`generate`. Construction is uniform so the
    registry can build any provider from the same config dict.
    """

    #: Short stable identifier used in logs and :class:`LLMResponse.provider`.
    name: str = "base"

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        api_key_env: Optional[str] = None,
        base_url: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.3,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        extra: Optional[dict] = None,
        **_ignored: Any,
    ):
        self.model = model
        self.base_url = base_url.rstrip("/") if base_url else None
        self.max_tokens = int(max_tokens)
        self.temperature = float(temperature)
        self.timeout_s = float(timeout_s)
        self.max_retries = int(max_retries)
        self.extra = dict(extra or {})
        # Resolve the API key: explicit value wins, else read the named env var,
        # else fall back to the provider's conventional env var.
        self._api_key_env = api_key_env
        self._api_key = api_key or (os.environ.get(api_key_env) if api_key_env else None)
        if not self._api_key:
            self._api_key = os.environ.get(self._default_key_env(), "")

    # -- to override -------------------------------------------------------

    def _default_key_env(self) -> str:
        """Conventional environment variable name for this provider's key."""
        return f"{self.name.upper()}_API_KEY"

    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        on_token: Optional[TokenCallback] = None,
        on_thinking: Optional[ThinkingCallback] = None,
    ) -> LLMResponse:
        """Run one completion. Returns a normalized :class:`LLMResponse`.

        When ``stream=True`` and ``on_thinking`` is supplied, providers that emit
        reasoning deltas surface them here (separate from ``on_token``)."""

    # -- shared helpers ----------------------------------------------------

    def is_available(self) -> bool:
        """True if credentials are present and the client library is importable.

        Endpoints that don't require a key (e.g. a local Ollama server) override
        :meth:`_requires_key` to return ``False``.
        """
        if self._requires_key() and not self._api_key:
            return False
        return self._client_importable()

    def unavailable_reason(self) -> str:
        """Human-readable reason :meth:`is_available` is False (else "")."""
        if self._requires_key() and not self._api_key:
            key = self._api_key_env or self._default_key_env()
            return f"no API key — set {key} in .env"
        if not self._client_importable():
            import sys
            return (f"client library not installed in this Python "
                    f"({sys.executable}) — run with the project venv")
        return ""

    def _requires_key(self) -> bool:
        return True

    def _client_importable(self) -> bool:  # pragma: no cover - trivial
        return True

    def test_connection(self) -> bool:
        """Cheap round-trip to verify the endpoint + key work."""
        try:
            resp = self.generate(
                messages=[{"role": "user", "content": "ping"}],
                tools=None,
                stream=False,
            )
            return resp.ok
        except Exception:
            return False

    @staticmethod
    def split_system(messages: list[dict]) -> tuple[str, list[dict]]:
        """Return (joined system text, non-system messages) for APIs that take
        the system prompt as a separate argument (Anthropic, Google)."""
        system_parts = [m["content"] for m in messages if m.get("role") == "system" and m.get("content")]
        convo = [m for m in messages if m.get("role") != "system"]
        return "\n\n".join(system_parts), convo
