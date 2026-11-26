"""The provider catalogue — the ONE source of truth for every LLM provider.

Everything that needs to know about providers derives from :data:`CATALOG`:

* ``registry.PROVIDER_TYPES`` / ``registry._TYPE_DEFAULTS`` — which adapter class
  builds each ``type:`` and the base_url / key env it defaults to;
* ``setup_wizard.PROVIDER_PRESETS`` — the terminal first-run wizard;
* ``GET /api/providers`` — the grouped catalogue the web UI's wizard renders;
* :func:`list_models_result` — live model listing with a curated fallback.

The list follows Hermes Agent's provider registry (NousResearch/hermes-agent,
MIT: ``hermes_cli/auth.py`` + ``plugins/model-providers/*``): same env-var names
and base URLs, so a key that works there works here. Namma keeps its own
historical ids where it already had them (``opencode``, ``openai_compat``,
``google``) and lists the Hermes ids as aliases.

Entry fields:
  id, label, group                      — identity; group is one of :data:`GROUPS`
  adapter                               — which provider class speaks the wire
                                          (``openai`` | ``anthropic`` | ``google`` |
                                          ``openai_compat`` | ``bedrock`` | ``vertex`` |
                                          ``azure``)
  base_url, needs_base_url              — default endpoint; True = the user supplies it
  key_env, key_url, key_prefix          — the credential's env var + where to get one
  auth, auths                           — primary auth (api_key|oauth|aws|gcp|none) +
                                          every auth the provider accepts
  docs_url, models_url                  — docs; where the live model list comes from
  aliases, fallback_models              — other ``type:`` spellings; curated models
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Optional

from namma_agent.core.logger import logger

#: Display order of the catalogue groups (the plan's W2 spec).
GROUPS = ("Popular", "Subscriptions", "Gateways", "China", "Cloud", "Local")

#: Adapters that are a provider's own native SDK. Every other catalogue type is
#: "strict": it reads only ITS key env var, never another provider's conventional
#: one (so a MiniMax entry on the Anthropic adapter can't send ANTHROPIC_API_KEY).
NATIVE_ADAPTER_TYPES = {"openai": "openai", "anthropic": "anthropic", "google": "google"}

_LOCAL = {"auth": "none", "auths": ["none"], "needs_base_url": True, "adapter": "openai_compat"}


def _p(id: str, label: str, group: str, base_url: str, key_env: str, key_url: str = "",
       docs_url: str = "", *, adapter: str = "openai_compat", auth: str = "api_key",
       auths: Optional[list] = None, needs_base_url: bool = False, key_prefix: str = "",
       aliases: tuple = (), fallback_models: tuple = (), models_url: Optional[str] = None,
       needs_key: Optional[bool] = None) -> dict:
    if models_url is None:
        models_url = (base_url.rstrip("/") + "/models") if base_url else ""
    return {
        "id": id, "label": label, "group": group, "adapter": adapter,
        "base_url": base_url, "needs_base_url": needs_base_url,
        "key_env": key_env, "key_url": key_url, "key_prefix": key_prefix,
        "auth": auth, "auths": list(auths or [auth]),
        "docs_url": docs_url or key_url, "models_url": models_url,
        "needs_key": (auth not in ("none", "aws", "gcp")) if needs_key is None else needs_key,
        "aliases": list(aliases), "fallback_models": list(fallback_models),
    }


CATALOG: list[dict] = [
    # ── Popular ──────────────────────────────────────────────────────────────
    _p("openai", "OpenAI", "Popular", "", "OPENAI_API_KEY",
       "https://platform.openai.com/api-keys", "https://platform.openai.com/docs",
       adapter="openai", key_prefix="sk-", aliases=("openai-api",),
       models_url="https://api.openai.com/v1/models",
       fallback_models=("gpt-4o", "gpt-4o-mini", "o3-mini")),
    _p("anthropic", "Anthropic (Claude)", "Popular", "", "ANTHROPIC_API_KEY",
       "https://console.anthropic.com/settings/keys", "https://docs.anthropic.com",
       adapter="anthropic", key_prefix="sk-ant-",
       models_url="https://api.anthropic.com/v1/models",
       fallback_models=("claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001")),
    _p("google", "Google (Gemini)", "Popular", "", "GOOGLE_API_KEY",
       "https://aistudio.google.com/apikey", "https://ai.google.dev/gemini-api/docs",
       adapter="google", key_prefix="AIza", aliases=("gemini",),
       models_url="https://generativelanguage.googleapis.com/v1beta/models",
       fallback_models=("gemini-2.0-flash", "gemini-1.5-pro", "gemini-1.5-flash")),
    # OpenRouter: an API key OR official PKCE sign-in (core/oauth.py).
    _p("openrouter", "OpenRouter (many models, one key)", "Popular",
       "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
       "https://openrouter.ai/keys", "https://openrouter.ai/docs",
       auth="oauth", auths=["oauth", "api_key"], key_prefix="sk-or-",
       fallback_models=("openai/gpt-4o-mini", "anthropic/claude-sonnet-4.5",
                        "google/gemini-2.5-flash")),
    _p("deepseek", "DeepSeek", "Popular", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY",
       "https://platform.deepseek.com/api_keys", "https://api-docs.deepseek.com",
       key_prefix="sk-", fallback_models=("deepseek-chat", "deepseek-reasoner")),
    _p("xai", "xAI (Grok)", "Popular", "https://api.x.ai/v1", "XAI_API_KEY",
       "https://console.x.ai", "https://docs.x.ai", key_prefix="xai-",
       fallback_models=("grok-4", "grok-3-mini")),

    # ── Subscriptions (coding plans / portals) ───────────────────────────────
    _p("nous", "Nous Portal", "Subscriptions", "https://inference-api.nousresearch.com/v1",
       "NOUS_API_KEY", "https://portal.nousresearch.com", "https://nousresearch.com/",
       fallback_models=("hermes-3-405b", "hermes-3-70b")),
    _p("opencode", "OpenCode Zen", "Subscriptions", "https://opencode.ai/zen/v1",
       "OPENCODE_ZEN_API_KEY", "https://opencode.ai/auth", "https://opencode.ai/docs/zen",
       aliases=("opencode-zen",), fallback_models=("big-pickle", "deepseek-v4-flash-free")),
    _p("opencode-go", "OpenCode Go", "Subscriptions", "https://opencode.ai/zen/go/v1",
       "OPENCODE_GO_API_KEY", "https://opencode.ai/auth", "https://opencode.ai/docs/go",
       fallback_models=("kimi-k2.6", "glm-5.2", "deepseek-v4-pro")),
    _p("kilocode", "Kilo Code", "Subscriptions", "https://api.kilo.ai/api/gateway",
       "KILOCODE_API_KEY", "https://app.kilo.ai", "https://kilo.ai/docs",
       fallback_models=("anthropic/claude-sonnet-4.6", "openai/gpt-5.4",
                        "google/gemini-3-flash-preview")),
    _p("commandcode", "CommandCode", "Subscriptions", "https://api.commandcode.ai/provider/v1",
       "COMMANDCODE_API_KEY", "https://commandcode.ai/", "https://commandcode.ai/",
       fallback_models=("deepseek/deepseek-v4-flash", "moonshotai/Kimi-K2.6", "zai-org/GLM-5.1")),
    _p("ollama-cloud", "Ollama Cloud", "Subscriptions", "https://ollama.com/v1",
       "OLLAMA_API_KEY", "https://ollama.com/settings/keys", "https://docs.ollama.com/cloud",
       fallback_models=("gpt-oss:120b", "nemotron-3-nano:30b")),

    # ── Gateways & services (OpenAI-compatible) ──────────────────────────────
    _p("groq", "Groq (very fast)", "Gateways", "https://api.groq.com/openai/v1", "GROQ_API_KEY",
       "https://console.groq.com/keys", "https://console.groq.com/docs", key_prefix="gsk_",
       fallback_models=("llama-3.3-70b-versatile", "llama-3.1-8b-instant")),
    _p("mistral", "Mistral", "Gateways", "https://api.mistral.ai/v1", "MISTRAL_API_KEY",
       "https://console.mistral.ai/api-keys", "https://docs.mistral.ai",
       fallback_models=("mistral-large-latest", "mistral-small-latest")),
    _p("together", "Together AI", "Gateways", "https://api.together.xyz/v1", "TOGETHER_API_KEY",
       "https://api.together.ai/settings/api-keys", "https://docs.together.ai",
       fallback_models=("meta-llama/Llama-3.3-70B-Instruct-Turbo",)),
    _p("fireworks", "Fireworks AI", "Gateways", "https://api.fireworks.ai/inference/v1",
       "FIREWORKS_API_KEY", "https://app.fireworks.ai/settings/users/api-keys",
       "https://docs.fireworks.ai",
       fallback_models=("accounts/fireworks/models/kimi-k2p6",
                        "accounts/fireworks/models/glm-5p2")),
    _p("novita", "NovitaAI", "Gateways", "https://api.novita.ai/openai/v1", "NOVITA_API_KEY",
       "https://novita.ai/settings/key-management", "https://novita.ai/docs",
       fallback_models=("moonshotai/kimi-k2.5", "deepseek/deepseek-v3-0324", "zai-org/glm-5")),
    _p("ai-gateway", "Vercel AI Gateway", "Gateways", "https://ai-gateway.vercel.sh/v1",
       "AI_GATEWAY_API_KEY", "https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai%2Fapi-keys",
       "https://vercel.com/docs/ai-gateway",
       fallback_models=("google/gemini-3-flash", "anthropic/claude-sonnet-4.6")),
    # Hermes drives Ramp Router and Meta's Model API over the Responses API; this
    # adapter speaks chat.completions. Listed for parity; verify with a real key.
    _p("ramp-router", "Ramp Router", "Gateways", "https://api.router.com/v1",
       "RAMP_ROUTER_API_KEY", "https://app.router.com/keys", "https://app.router.com/",
       aliases=("router",), fallback_models=("gpt-5.4-mini",)),
    _p("huggingface", "Hugging Face", "Gateways", "https://router.huggingface.co/v1", "HF_TOKEN",
       "https://huggingface.co/settings/tokens", "https://huggingface.co/docs/inference-providers",
       key_prefix="hf_",
       fallback_models=("moonshotai/Kimi-K2.5", "deepseek-ai/DeepSeek-V3.2", "zai-org/GLM-5")),
    _p("nvidia", "NVIDIA NIM", "Gateways", "https://integrate.api.nvidia.com/v1",
       "NVIDIA_API_KEY", "https://build.nvidia.com/", "https://docs.api.nvidia.com",
       key_prefix="nvapi-",
       fallback_models=("nvidia/llama-3.3-nemotron-super-49b-v1",
                        "nvidia/llama-3.1-nemotron-70b-instruct")),
    _p("deepinfra", "DeepInfra", "Gateways", "https://api.deepinfra.com/v1/openai",
       "DEEPINFRA_API_KEY", "https://deepinfra.com/dash/api_keys", "https://deepinfra.com/docs",
       fallback_models=("deepseek-ai/DeepSeek-V4-Flash",)),
    _p("cerebras", "Cerebras", "Gateways", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY",
       "https://cloud.cerebras.ai", "https://inference-docs.cerebras.ai", key_prefix="csk-",
       fallback_models=("llama-3.3-70b", "gpt-oss-120b")),
    _p("perplexity", "Perplexity", "Gateways", "https://api.perplexity.ai", "PERPLEXITY_API_KEY",
       "https://www.perplexity.ai/settings/api", "https://docs.perplexity.ai", key_prefix="pplx-",
       fallback_models=("sonar", "sonar-pro", "sonar-reasoning-pro")),
    _p("nebius", "Nebius Token Factory", "Gateways", "https://api.tokenfactory.nebius.com/v1",
       "NEBIUS_API_KEY", "https://tokenfactory.nebius.com/", "https://docs.tokenfactory.nebius.com",
       aliases=("nebius-token-factory",),
       fallback_models=("deepseek-ai/DeepSeek-V4-Pro", "zai-org/GLM-5.1")),
    _p("gmi", "GMI Cloud", "Gateways", "https://api.gmi-serving.com/v1", "GMI_API_KEY",
       "https://www.gmicloud.ai/", "https://docs.gmicloud.ai",
       fallback_models=("zai-org/GLM-5.1-FP8", "deepseek-ai/DeepSeek-V3.2")),
    _p("arcee", "Arcee AI", "Gateways", "https://api.arcee.ai/api/v1", "ARCEEAI_API_KEY",
       "https://chat.arcee.ai/", "https://docs.arcee.ai",
       fallback_models=("trinity-large-thinking", "trinity-mini")),
    _p("stepfun", "StepFun", "Gateways", "https://api.stepfun.ai/step_plan/v1", "STEPFUN_API_KEY",
       "https://platform.stepfun.ai/", "https://platform.stepfun.ai/docs",
       fallback_models=("step-3.5-flash", "step-3.7-flash")),
    _p("meta-ai", "Meta Model API", "Gateways", "https://api.meta.ai/v1", "META_API_KEY",
       "https://developer.meta.com/ai/", "https://developer.meta.com/ai/",
       fallback_models=("muse-spark-1.2",)),

    # ── China ────────────────────────────────────────────────────────────────
    _p("zai", "Z.AI / GLM", "China", "https://api.z.ai/api/paas/v4", "GLM_API_KEY",
       "https://z.ai/manage-apikey/apikey-list", "https://docs.z.ai",
       fallback_models=("glm-5.2", "glm-5", "glm-4.5-flash")),
    _p("kimi-coding", "Kimi / Moonshot", "China", "https://api.moonshot.ai/v1", "KIMI_API_KEY",
       "https://platform.moonshot.ai/console/api-keys", "https://platform.moonshot.ai/docs",
       aliases=("kimi", "moonshot"),
       fallback_models=("kimi-k2.6", "kimi-k2.5", "kimi-k2-turbo-preview")),
    _p("kimi-coding-cn", "Kimi / Moonshot (China)", "China", "https://api.moonshot.cn/v1",
       "KIMI_CN_API_KEY", "https://platform.moonshot.cn/console/api-keys",
       "https://platform.moonshot.cn/docs", aliases=("kimi-cn", "moonshot-cn"),
       fallback_models=("kimi-k2.6", "kimi-k2.5", "kimi-k2-turbo-preview")),
    # MiniMax and Tencent TokenPlan serve the Anthropic Messages API (Hermes'
    # api_mode anthropic_messages), so they ride the Anthropic adapter.
    _p("minimax", "MiniMax", "China", "https://api.minimax.io/anthropic", "MINIMAX_API_KEY",
       "https://platform.minimax.io/user-center/basic-information/interface-key",
       "https://platform.minimax.io/docs", adapter="anthropic", models_url="",
       fallback_models=("MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5")),
    _p("minimax-cn", "MiniMax (China)", "China", "https://api.minimaxi.com/anthropic",
       "MINIMAX_CN_API_KEY", "https://platform.minimaxi.com/user-center/basic-information/interface-key",
       "https://platform.minimaxi.com/docs", adapter="anthropic", models_url="",
       fallback_models=("MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5")),
    _p("alibaba", "Alibaba DashScope (Qwen)", "China",
       "https://dashscope-intl.aliyuncs.com/compatible-mode/v1", "DASHSCOPE_API_KEY",
       "https://modelstudio.console.alibabacloud.com/", "https://help.aliyun.com/zh/model-studio/",
       aliases=("dashscope",), fallback_models=("qwen3.7-plus", "qwen3.6-plus", "qwen3-coder-plus")),
    _p("alibaba-coding-plan", "Alibaba Cloud (Coding Plan)", "China",
       "https://coding-intl.dashscope.aliyuncs.com/v1", "ALIBABA_CODING_PLAN_API_KEY",
       "https://modelstudio.console.alibabacloud.com/", "https://help.aliyun.com/zh/model-studio/",
       fallback_models=("qwen3.7-plus", "qwen3-coder-plus", "kimi-k2.5")),
    _p("alibaba-token-plan", "Alibaba Cloud (Token Plan)", "China",
       "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
       "ALIBABA_TOKEN_PLAN_API_KEY", "https://modelstudio.console.alibabacloud.com/",
       "https://help.aliyun.com/zh/model-studio/",
       fallback_models=("qwen3.7-plus", "deepseek-v4-pro", "kimi-k2.6")),
    _p("xiaomi", "Xiaomi MiMo", "China", "https://api.xiaomimimo.com/v1", "XIAOMI_API_KEY",
       "https://platform.xiaomimimo.com/", "https://platform.xiaomimimo.com/",
       fallback_models=("mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-flash")),
    _p("tencent-tokenhub", "Tencent TokenHub", "China", "https://tokenhub.tencentmaas.com/v1",
       "TOKENHUB_API_KEY", "https://cloud.tencent.com/product/tokenhub",
       "https://cloud.tencent.com/product/tokenhub", fallback_models=("hy3", "hy3-preview")),
    _p("tencent-tokenplan", "Tencent TokenPlan", "China",
       "https://api.lkeap.cloud.tencent.com/plan/anthropic", "TOKENPLAN_API_KEY",
       "https://cloud.tencent.com/product/lkeap", "https://cloud.tencent.com/product/lkeap",
       adapter="anthropic", models_url="", fallback_models=("hy3", "hy3-preview")),

    # ── Cloud ────────────────────────────────────────────────────────────────
    # Bedrock: boto3's credential chain (profile / env / SSO) or a Bedrock API key
    # (AWS_BEARER_TOKEN_BEDROCK, read by boto3 itself). boto3 is optional.
    _p("bedrock", "AWS Bedrock", "Cloud", "https://bedrock-runtime.us-east-1.amazonaws.com",
       "AWS_BEARER_TOKEN_BEDROCK", "https://console.aws.amazon.com/bedrock/home#/api-keys",
       "https://docs.aws.amazon.com/bedrock/", adapter="bedrock", auth="aws",
       auths=["aws", "api_key"], models_url="",
       fallback_models=("us.anthropic.claude-sonnet-4-6", "us.anthropic.claude-haiku-4-5-20251001-v1:0",
                        "us.amazon.nova-pro-v1:0", "us.meta.llama4-maverick-17b-instruct-v1:0")),
    # Vertex: Application Default Credentials (google-auth, optional); the endpoint
    # is computed from GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION.
    _p("vertex", "Google Vertex AI", "Cloud", "", "", "https://console.cloud.google.com/vertex-ai",
       "https://cloud.google.com/vertex-ai/generative-ai/docs", adapter="vertex", auth="gcp",
       models_url="",
       fallback_models=("google/gemini-2.5-flash", "google/gemini-2.5-pro",
                        "google/gemini-3-flash-preview")),
    _p("azure-foundry", "Azure OpenAI / AI Foundry", "Cloud", "", "AZURE_FOUNDRY_API_KEY",
       "https://ai.azure.com/", "https://learn.microsoft.com/azure/ai-foundry/openai/",
       adapter="azure", needs_base_url=True, aliases=("azure", "azure-openai")),

    # ── Local (no key) ───────────────────────────────────────────────────────
    _p("ollama", "Ollama (local)", "Local", "http://localhost:11434/v1", "",
       docs_url="https://docs.ollama.com", **_LOCAL),
    _p("lmstudio", "LM Studio (local)", "Local", "http://localhost:1234/v1", "",
       docs_url="https://lmstudio.ai/docs", **_LOCAL),
    _p("vllm", "vLLM (local)", "Local", "http://localhost:8000/v1", "",
       docs_url="https://docs.vllm.ai", **_LOCAL),
    _p("sglang", "SGLang (local)", "Local", "http://localhost:30000/v1", "",
       docs_url="https://docs.sglang.ai", **_LOCAL),
    _p("llamacpp", "llama.cpp server (local)", "Local", "http://localhost:8080/v1", "",
       docs_url="https://github.com/ggml-org/llama.cpp/tree/master/tools/server",
       aliases=("llama.cpp", "llama-cpp"), **_LOCAL),
    _p("litellm", "LiteLLM proxy (local)", "Local", "http://localhost:4000/v1", "LITELLM_API_KEY",
       docs_url="https://docs.litellm.ai/docs/simple_proxy", **_LOCAL),
    _p("localai", "LocalAI (local)", "Local", "http://localhost:8080/v1", "",
       docs_url="https://localai.io", **_LOCAL),
    _p("jan", "Jan (local)", "Local", "http://localhost:1337/v1", "",
       docs_url="https://jan.ai/docs", **_LOCAL),
    # Any OpenAI-compatible endpoint. Its key var is its own — never OPENAI_API_KEY.
    _p("openai_compat", "Custom (OpenAI-compatible)", "Local", "", "OPENAI_COMPAT_API_KEY",
       adapter="openai_compat", auth="api_key", needs_base_url=True, needs_key=False,
       aliases=("custom",)),
]

#: id → entry (canonical ids only).
CATALOG_BY_ID: dict[str, dict] = {p["id"]: p for p in CATALOG}

#: id OR alias → entry. Back-compat name used by setup_service / setup.verify_provider.
_BY_TYPE: dict[str, dict] = {**{a: p for p in CATALOG for a in p["aliases"]}, **CATALOG_BY_ID}

#: Back-compat: the old flat list shape (``type`` == ``id``).
PROVIDER_CATALOG = CATALOG


def get_entry(ptype: str) -> Optional[dict]:
    """The catalogue entry for a ``type:`` (id or alias), or None."""
    return _BY_TYPE.get((ptype or "").strip().lower())


def canonical_id(ptype: str) -> str:
    entry = get_entry(ptype)
    return entry["id"] if entry else (ptype or "").strip().lower()


def is_strict(ptype: str) -> bool:
    """True when the type must read only its own key env (see NATIVE_ADAPTER_TYPES)."""
    entry = get_entry(ptype)
    return bool(entry) and NATIVE_ADAPTER_TYPES.get(entry["adapter"]) != entry["id"]


def provider_catalog(configured: Optional[list[dict]] = None) -> list[dict]:
    """The catalogue in the ``GET /api/providers`` contract shape.

    Each row: ``{id, label, group, auth, key_env, key_url, base_url,
    needs_base_url, key_set, connected, docs_url}`` plus the fields the current
    UI also reads (``type``, ``needs_key``, ``key_prefix``, ``auths``,
    ``adapter``, ``models_url``). ``connected`` is True when the provider can be
    used right now: its key is set, it needs none (local / cloud-SDK auth), or
    the user has a configured provider connection of this type whose own key
    var is set (``configured``: the ``providers:`` list).
    """
    conn_ok: set[str] = set()
    for c in configured or []:
        env = (c.get("api_key_env") or "").strip()
        if env and os.environ.get(env):
            conn_ok.add(canonical_id(c.get("type") or ""))
    out = []
    for p in CATALOG:
        key_set = bool(p["key_env"] and os.environ.get(p["key_env"]))
        row = {k: v for k, v in p.items() if k != "fallback_models"}
        row["type"] = p["id"]
        row["key_set"] = key_set
        row["connected"] = bool(key_set or p["id"] in conn_ok or p["auth"] == "none"
                                or _sdk_auth_present(p["auth"]))
        out.append(row)
    return out


def _sdk_auth_present(auth: str) -> bool:
    """Cheap, offline hint that cloud-SDK credentials exist (no network call)."""
    env = os.environ
    if auth == "aws":
        return bool(env.get("AWS_ACCESS_KEY_ID") or env.get("AWS_PROFILE")
                    or env.get("AWS_BEARER_TOKEN_BEDROCK"))
    if auth == "gcp":
        return bool(env.get("GOOGLE_CLOUD_PROJECT") or env.get("VERTEX_PROJECT"))
    return False


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
    spec = get_entry(ptype) or {}
    cid = spec.get("id", ptype)
    adapter = spec.get("adapter", "openai_compat")
    key = api_key or (os.environ.get(spec.get("key_env", "")) if spec.get("key_env") else "") or ""
    base = base_url or spec.get("base_url", "")
    models: list[str] = []
    error = ""
    try:
        if cid == "anthropic":
            data = _get_json("https://api.anthropic.com/v1/models",
                             {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
            models = [m["id"] for m in data.get("data", [])]
        elif cid == "openai":
            data = _get_json("https://api.openai.com/v1/models",
                             {"Authorization": f"Bearer {key}"}, timeout)
            models = [m["id"] for m in data.get("data", [])]
        elif cid == "google":
            data = _get_json(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
                             {}, timeout)
            models = [m["name"].split("/")[-1] for m in data.get("models", [])
                      if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        elif adapter in ("bedrock", "vertex") or (spec.get("base_url") and not spec.get("models_url")
                                                  and not base_url):
            pass  # no OpenAI-style /models route — the curated list is the answer
        else:  # openai-compatible family (gateways / local / custom / azure)
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
    return {"models": list(spec.get("fallback_models") or []), "source": "fallback",
            "error": error}


def list_models(ptype: str, base_url: str = "", api_key: str = "", timeout: int = 8) -> list[str]:
    """Best-effort live model list (names only). Never empty for known providers."""
    return list_models_result(ptype, base_url, api_key, timeout)["models"]
