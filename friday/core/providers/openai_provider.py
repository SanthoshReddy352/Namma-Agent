"""Native OpenAI provider.

Thin subclass of :class:`OpenAICompatProvider` — the wire format is identical;
this only pins OpenAI defaults (api.openai.com, ``OPENAI_API_KEY``).
"""
from __future__ import annotations

from .openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    name = "openai"

    def __init__(self, model: str = "gpt-4o-mini", **kwargs):
        # No base_url → the OpenAI SDK targets api.openai.com by default.
        kwargs.setdefault("api_key_env", "OPENAI_API_KEY")
        super().__init__(model=model, **kwargs)

    def _default_key_env(self) -> str:
        return "OPENAI_API_KEY"

    def _requires_key(self) -> bool:
        return True
