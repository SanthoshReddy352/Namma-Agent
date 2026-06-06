"""Provider registry + fallback chain.

Builds the active provider(s) from config. ``provider.type`` selects the adapter;
an optional ``provider.fallback`` list provides ordered alternates that are tried
when the primary is unavailable or errors.

    provider:
      type: anthropic
      model: claude-sonnet-4-6
      max_tokens: 4096
      temperature: 0.3
      fallback:
        - type: openai
          model: gpt-4o-mini
        - type: openai_compat
          model: llama3.1
          base_url: http://localhost:11434/v1
"""
from __future__ import annotations

from typing import Optional

from friday.core.logger import logger

from .anthropic_provider import AnthropicProvider
from .base import LLMResponse, Provider, ProviderError, TokenCallback
from .google_provider import GoogleProvider
from .openai_compat import OpenAICompatProvider
from .openai_provider import OpenAIProvider

#: type string -> provider class. ``opencode``/``lmstudio``/``ollama`` are all
#: OpenAI-compatible; they map to the same adapter (differ only by base_url).
PROVIDER_TYPES: dict[str, type[Provider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "google": GoogleProvider,
    "gemini": GoogleProvider,
    "openai_compat": OpenAICompatProvider,
    "opencode": OpenAICompatProvider,
    "lmstudio": OpenAICompatProvider,
    "ollama": OpenAICompatProvider,
}

#: Convenience defaults so a bare ``type: ollama`` just works.
_TYPE_DEFAULTS: dict[str, dict] = {
    "lmstudio": {"base_url": "http://localhost:1234/v1"},
    "ollama": {"base_url": "http://localhost:11434/v1"},
}


def build_provider(cfg: dict) -> Provider:
    """Instantiate a single provider from one config block."""
    cfg = dict(cfg)
    ptype = (cfg.pop("type", None) or "").lower()
    if ptype not in PROVIDER_TYPES:
        raise ValueError(
            f"Unknown provider type {ptype!r}. Known: {sorted(set(PROVIDER_TYPES))}"
        )
    cfg.pop("fallback", None)
    for key, val in _TYPE_DEFAULTS.get(ptype, {}).items():
        cfg.setdefault(key, val)
    cls = PROVIDER_TYPES[ptype]
    return cls(**cfg)


class ProviderChain(Provider):
    """A primary provider plus ordered fallbacks.

    Implements the :class:`Provider` interface so the agent loop can treat a
    chain exactly like a single provider. On :class:`ProviderError` (or an
    unavailable provider) it advances to the next link.
    """

    name = "chain"

    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError("ProviderChain needs at least one provider")
        self._providers = providers
        primary = providers[0]
        self.model = primary.model

    @property
    def active(self) -> Provider:
        return self._providers[0]

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        on_token: Optional[TokenCallback] = None,
    ) -> LLMResponse:
        last_exc: Optional[Exception] = None
        for provider in self._providers:
            if not provider.is_available():
                logger.info("[chain] skipping unavailable provider: %s", provider.name)
                continue
            try:
                return provider.generate(messages, tools=tools, stream=stream, on_token=on_token)
            except ProviderError as exc:
                last_exc = exc
                logger.warning("[chain] %s failed, trying next: %s", provider.name, exc)
        raise ProviderError(f"All providers failed. Last error: {last_exc}")

    def test_connection(self) -> bool:
        return any(p.is_available() and p.test_connection() for p in self._providers)


def from_config(config: dict) -> Provider:
    """Build the active provider (single or chain) from the full config dict.

    ``config`` is expected to contain a ``provider`` block.
    """
    pcfg = config.get("provider") or config
    primary = build_provider(pcfg)
    fallbacks = [build_provider(fc) for fc in (pcfg.get("fallback") or [])]
    if not fallbacks:
        return primary
    return ProviderChain([primary, *fallbacks])


def _cli_test() -> int:  # pragma: no cover - manual smoke test
    """`python -m friday.core.providers.registry --test` — verify configured providers."""
    from friday.config import load_config

    config = load_config()
    provider = from_config(config)
    names = (
        [p.name for p in provider._providers]  # type: ignore[attr-defined]
        if isinstance(provider, ProviderChain)
        else [provider.name]
    )
    print(f"Configured provider(s): {names}")
    ok = provider.test_connection()
    print("Connection test:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--test" in sys.argv:
        raise SystemExit(_cli_test())
    print("Usage: python -m friday.core.providers.registry --test")
