"""Provider catalog + live model listing for the settings UI.

Gives the web UI everything it needs to configure the brain:
  * the list of providers, each with its conventional ``.env`` key and whether
    that key is set, its base_url default, and whether it needs a key at all;
  * the available models for a provider, fetched live from its API (best-effort),
    with a small curated fallback so the dropdown is never empty.
"""
from __future__ import annotations

import json
import os
import urllib.request

from namma_agent.core.logger import logger

# Distinct, user-selectable providers (the registry also aliases gemini→google).
PROVIDER_CATALOG = [
    {"type": "anthropic", "label": "Anthropic (Claude)", "key_env": "ANTHROPIC_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "",
     "key_url": "https://console.anthropic.com/settings/keys", "key_prefix": "sk-ant-"},
    {"type": "openai", "label": "OpenAI", "key_env": "OPENAI_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "",
     "key_url": "https://platform.openai.com/api-keys", "key_prefix": "sk-"},
    {"type": "google", "label": "Google (Gemini)", "key_env": "GOOGLE_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "",
     "key_url": "https://aistudio.google.com/apikey", "key_prefix": "AIza"},
    # Phase 5: hosted OpenAI-compatible providers (one adapter, a base_url each).
    {"type": "openrouter", "label": "OpenRouter (many models, one key)",
     "key_env": "OPENROUTER_API_KEY", "needs_key": True, "needs_base_url": False,
     "base_url": "https://openrouter.ai/api/v1", "key_url": "https://openrouter.ai/keys",
     "key_prefix": "sk-or-"},
    {"type": "groq", "label": "Groq (very fast)", "key_env": "GROQ_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "https://api.groq.com/openai/v1",
     "key_url": "https://console.groq.com/keys", "key_prefix": "gsk_"},
    {"type": "deepseek", "label": "DeepSeek", "key_env": "DEEPSEEK_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "https://api.deepseek.com/v1",
     "key_url": "https://platform.deepseek.com/api_keys", "key_prefix": "sk-"},
    {"type": "mistral", "label": "Mistral", "key_env": "MISTRAL_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "https://api.mistral.ai/v1",
     "key_url": "https://console.mistral.ai/api-keys", "key_prefix": ""},
    {"type": "xai", "label": "xAI (Grok)", "key_env": "XAI_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "https://api.x.ai/v1",
     "key_url": "https://console.x.ai", "key_prefix": "xai-"},
    {"type": "together", "label": "Together AI", "key_env": "TOGETHER_API_KEY",
     "needs_key": True, "needs_base_url": False, "base_url": "https://api.together.xyz/v1",
     "key_url": "https://api.together.ai/settings/api-keys", "key_prefix": ""},
    {"type": "opencode", "label": "opencode (OpenAI-compatible)", "key_env": "OPENAI_API_KEY",
     "needs_key": True, "needs_base_url": True, "base_url": "https://opencode.ai/zen/v1",
     "key_url": "https://opencode.ai", "key_prefix": ""},
    {"type": "openai_compat", "label": "Custom (OpenAI-compatible)", "key_env": "OPENAI_API_KEY",
     "needs_key": False, "needs_base_url": True, "base_url": "", "key_url": "", "key_prefix": ""},
    {"type": "lmstudio", "label": "LM Studio (local)", "key_env": "",
     "needs_key": False, "needs_base_url": True, "base_url": "http://localhost:1234/v1",
     "key_url": "", "key_prefix": ""},
    {"type": "ollama", "label": "Ollama (local)", "key_env": "",
     "needs_key": False, "needs_base_url": True, "base_url": "http://localhost:11434/v1",
     "key_url": "", "key_prefix": ""},
]

_BY_TYPE = {p["type"]: p for p in PROVIDER_CATALOG}

# Curated fallbacks shown when a live fetch returns nothing (no key / offline).
_FALLBACK_MODELS = {
    "anthropic": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "openai": ["gpt-4o", "gpt-4o-mini", "o3-mini"],
    "google": ["gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash"],
    "opencode": ["big-pickle", "deepseek-v4-flash-free"],
    "openrouter": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5", "google/gemini-2.5-flash"],
    "groq": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    "deepseek": ["deepseek-chat", "deepseek-reasoner"],
    "mistral": ["mistral-large-latest", "mistral-small-latest"],
    "xai": ["grok-4", "grok-3-mini"],
    "together": ["meta-llama/Llama-3.3-70B-Instruct-Turbo"],
}


def provider_catalog() -> list[dict]:
    """The catalog with live ``key_set`` flags from the environment."""
    out = []
    for p in PROVIDER_CATALOG:
        item = dict(p)
        item["key_set"] = bool(p["key_env"] and os.environ.get(p["key_env"]))
        out.append(item)
    return out


# A real browser-ish User-Agent. Some provider gateways (notably opencode.ai,
# which sits behind a WAF) answer the default ``Python-urllib/3.x`` UA with a 403,
# which silently collapsed the live list down to the curated fallback. Sending a
# normal UA is the difference between 2 models and the provider's full catalogue.
_USER_AGENT = "Namma Agent/2.0 (+model-picker; like curl)"


def _get_json(url: str, headers: dict, timeout: int = 8) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.load(resp)


def _explain(exc: Exception) -> str:
    """Turn a raw urllib error into something a user can act on."""
    import urllib.error
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return f"Provider rejected the request ({exc.code}) — check the API key."
        if exc.code == 404:
            return "Provider has no /models endpoint at that Base URL — check the URL."
        return f"Provider returned HTTP {exc.code}."
    if isinstance(exc, urllib.error.URLError):
        return "Couldn't reach the provider — check the Base URL / your connection."
    return str(exc)[:160]


def list_models_result(ptype: str, base_url: str = "", api_key: str = "",
                       timeout: int = 8) -> dict:
    """Live model list for a provider, with provenance so the UI can explain a
    short list. Returns ``{models, source, error}`` where ``source`` is ``"live"``
    (fetched from the provider) or ``"fallback"`` (curated default — the live fetch
    found nothing or failed) and ``error`` is a human string when the fetch failed.
    """
    ptype = (ptype or "").lower()
    spec = _BY_TYPE.get(ptype, {})
    key = api_key or (os.environ.get(spec.get("key_env", "")) if spec.get("key_env") else "") or ""
    base = base_url or spec.get("base_url", "")
    models: list[str] = []
    error = ""
    try:
        if ptype == "anthropic":
            data = _get_json("https://api.anthropic.com/v1/models",
                             {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
            models = [m["id"] for m in data.get("data", [])]
        elif ptype == "openai":
            data = _get_json("https://api.openai.com/v1/models",
                             {"Authorization": f"Bearer {key}"}, timeout)
            models = [m["id"] for m in data.get("data", [])]
        elif ptype in ("google", "gemini"):
            data = _get_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                             {}, timeout)
            models = [m["name"].split("/")[-1] for m in data.get("models", [])
                      if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        else:  # openai-compatible family (opencode / lmstudio / ollama / custom)
            if not base:
                error = "Set a Base URL for this OpenAI-compatible provider first."
            else:
                headers = {"Authorization": f"Bearer {key}"} if key else {}
                data = _get_json(base.rstrip("/") + "/models", headers, timeout)
                models = [m.get("id") for m in data.get("data", []) if m.get("id")]
    except Exception as exc:  # noqa: BLE001
        error = _explain(exc)
        logger.debug("[catalog] model fetch for %s failed: %s", ptype, exc)
    models = sorted(set(filter(None, models)))
    if models:
        return {"models": models, "source": "live", "error": ""}
    if not error and spec.get("needs_key") and not key:
        error = f"No API key — set {spec.get('key_env')} to list this provider's models."
    return {"models": _FALLBACK_MODELS.get(ptype, []), "source": "fallback", "error": error}


def list_models(ptype: str, base_url: str = "", api_key: str = "", timeout: int = 8) -> list[str]:
    """Best-effort live model list (names only). Never empty for known providers."""
    return list_models_result(ptype, base_url, api_key, timeout)["models"]
