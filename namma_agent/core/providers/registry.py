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

from namma_agent.core.logger import logger

from .anthropic_provider import AnthropicProvider
from .base import LLMResponse, Provider, ProviderError, ThinkingCallback, TokenCallback
from .bedrock_provider import BedrockProvider
from .catalog import CATALOG, is_strict
from .cloud_compat import AzureProvider, VertexProvider
from .google_provider import GoogleProvider
from .openai_compat import OpenAICompatProvider
from .openai_provider import OpenAIProvider

#: catalogue ``adapter`` -> the class that speaks that wire format.
ADAPTERS: dict[str, type[Provider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "openai_compat": OpenAICompatProvider,
    "bedrock": BedrockProvider,
    "vertex": VertexProvider,
    "azure": AzureProvider,
}

#: type string (catalogue id or alias) -> provider class. DERIVED from the
#: catalogue (core/providers/catalog.py) — add a provider there, not here.
PROVIDER_TYPES: dict[str, type[Provider]] = {
    t: ADAPTERS[p["adapter"]] for p in CATALOG for t in (p["id"], *p["aliases"])
}

#: Per-type defaults so a bare ``type: groq`` just works: the catalogue's
#: base_url and key env var (DERIVED from the catalogue, aliases included).
_TYPE_DEFAULTS: dict[str, dict] = {
    t: {k: v for k, v in (("base_url", p["base_url"]), ("api_key_env", p["key_env"])) if v}
    for p in CATALOG for t in (p["id"], *p["aliases"])
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
        if not cfg.get(key):        # "" / None from a profile still gets the default
            cfg[key] = val
    if is_strict(ptype):
        # Borrowed adapter: read only this provider's own key var, never the
        # adapter's conventional one (OPENAI_API_KEY / ANTHROPIC_API_KEY).
        cfg.setdefault("key_fallback", False)
    cls = PROVIDER_TYPES[ptype]
    return cls(**cfg)


class ProviderChain(Provider):
    """A primary provider plus ordered fallbacks.

    Implements the :class:`Provider` interface so the agent loop can treat a
    chain exactly like a single provider. On :class:`ProviderError` (or an
    unavailable provider) it advances to the next link.
    """

    name = "chain"
    # Member providers record their own usage; the chain must not count twice.
    _metered = False

    def __init__(self, providers: list[Provider]):
        if not providers:
            raise ValueError("ProviderChain needs at least one provider")
        self._providers = providers
        primary = providers[0]
        self.model = primary.model

    @property
    def active(self) -> Provider:
        return self._providers[0]

    # The agent's hard wall-clock ceiling (agent._generate_timeout) reads these;
    # a chain may try every link, so its budget covers all of them.
    @property
    def timeout_s(self) -> float:
        return float(sum(float(getattr(p, "timeout_s", 60.0) or 60.0) for p in self._providers))

    @property
    def max_retries(self) -> int:
        return max(int(getattr(p, "max_retries", 1) or 1) for p in self._providers)

    def is_available(self) -> bool:
        """A chain is usable when ANY link is. The base implementation reads
        ``self._api_key``, which a chain never has (it holds providers, not
        credentials) — inheriting it raised AttributeError on every caller."""
        return any(p.is_available() for p in self._providers)

    def unavailable_reason(self) -> str:
        if self.is_available():
            return ""
        return "; ".join(f"{p.name}: {p.unavailable_reason()}" for p in self._providers)

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        on_token: Optional[TokenCallback] = None,
        on_thinking: Optional[ThinkingCallback] = None,
    ) -> LLMResponse:
        last_exc: Optional[Exception] = None
        any_available = False
        for provider in self._providers:
            if not provider.is_available():
                logger.info("[chain] skipping unavailable provider: %s (%s)",
                            provider.name, provider.unavailable_reason())
                continue
            any_available = True
            try:
                return provider.generate(messages, tools=tools, stream=stream,
                                         on_token=on_token, on_thinking=on_thinking)
            except ProviderError as exc:
                last_exc = exc
                logger.warning("[chain] %s failed, trying next: %s", provider.name, exc)
        if not any_available:
            reasons = "; ".join(f"{p.name}: {p.unavailable_reason()}" for p in self._providers)
            raise ProviderError(
                "No LLM provider is available. " + reasons + ". "
                "If you launched with the system Python, start with the project venv "
                "(.venv/bin/python -m namma_agent) so the provider SDK is installed.")
        # A rate-limited free tier is the most common reason the whole chain falls
        # over — surface it in plain language (the raw 429 JSON is opaque to a user)
        # so they know it's a quota, not a crash, and what to do about it.
        blob = str(last_exc).lower()
        if "429" in blob or "rate limit" in blob or "freeusagelimit" in blob or "quota" in blob:
            raise ProviderError(
                "Every configured model is rate-limited right now (free-tier usage "
                "limit). This isn't a bug in the assistant — the brain (the LLM) is "
                "temporarily refusing requests. Wait a minute and retry, or set a more "
                "reliable model in namma_agent/config.yaml (e.g. an Anthropic/OpenAI key). "
                f"[detail: {last_exc}]")
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
    """`python -m namma_agent.core.providers.registry --test` — verify configured providers."""
    from namma_agent.config import load_config

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
    print("Usage: python -m namma_agent.core.providers.registry --test")
