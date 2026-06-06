"""Provider abstraction for FRIDAY v2 (cloud-only brain).

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
        max_tokens: int = 4096,
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
    ) -> LLMResponse:
        """Run one completion. Returns a normalized :class:`LLMResponse`."""

    # -- shared helpers ----------------------------------------------------

    def is_available(self) -> bool:
        """True if credentials are present and the client library is importable.

        Endpoints that don't require a key (e.g. a local Ollama server) override
        :meth:`_requires_key` to return ``False``.
        """
        if self._requires_key() and not self._api_key:
            return False
        return self._client_importable()

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
