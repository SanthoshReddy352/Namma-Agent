"""Phase 9 W2 — one provider catalogue, OpenRouter PKCE, explicit active_model."""
from __future__ import annotations

import base64
import hashlib
import re
import sys
import types
import urllib.parse

import pytest
from fastapi.testclient import TestClient

import namma_agent.tests.test_server as ts
from namma_agent.core.memory import Database
from namma_agent.core.oauth import OAuthError, OAuthManager, pkce_challenge, pkce_verifier
from namma_agent.core.providers import catalog as cat
from namma_agent.core.providers.base import LLMResponse, ToolCall
from namma_agent.core.providers.registry import (
    _TYPE_DEFAULTS,
    ADAPTERS,
    PROVIDER_TYPES,
    build_provider,
)
from namma_agent.core.tools import ToolRegistry
from namma_agent.server.api import create_app
from namma_agent.service import NammaAgentService

CONTRACT_FIELDS = {"id", "label", "group", "auth", "key_env", "key_url", "base_url",
                   "needs_base_url", "key_set", "connected", "docs_url"}

# The plan's Hermes list (W2 §2), by catalogue id.
EXPECTED_IDS = {
    # native
    "openai", "anthropic", "google",
    # gateways & services
    "openrouter", "nous", "groq", "deepseek", "mistral", "xai", "together", "fireworks",
    "novita", "ai-gateway", "ramp-router", "kilocode", "opencode", "opencode-go",
    "commandcode", "huggingface", "nvidia", "deepinfra", "cerebras", "perplexity", "nebius",
    "gmi", "arcee", "stepfun", "meta-ai", "ollama-cloud",
    # China
    "zai", "kimi-coding", "kimi-coding-cn", "minimax", "minimax-cn", "alibaba",
    "alibaba-coding-plan", "alibaba-token-plan", "xiaomi", "tencent-tokenhub",
    "tencent-tokenplan",
    # cloud
    "bedrock", "vertex", "azure-foundry",
    # local
    "ollama", "lmstudio", "vllm", "sglang", "llamacpp", "litellm", "localai", "jan",
    "openai_compat",
}


# ── catalogue ────────────────────────────────────────────────────────────────

def test_catalogue_ids_and_aliases_are_unique():
    ids = [p["id"] for p in cat.CATALOG]
    assert len(ids) == len(set(ids))
    names = ids + [a for p in cat.CATALOG for a in p["aliases"]]
    assert len(names) == len(set(names)), "an alias collides with an id or another alias"


def test_catalogue_is_complete_and_well_formed():
    assert EXPECTED_IDS <= set(cat.CATALOG_BY_ID)
    for p in cat.CATALOG:
        assert p["group"] in cat.GROUPS, p["id"]
        assert p["adapter"] in ADAPTERS, p["id"]
        assert p["auth"] in {"api_key", "oauth", "aws", "gcp", "none"}, p["id"]
        assert p["auth"] in p["auths"], p["id"]
        for url in ("base_url", "key_url", "docs_url", "models_url"):
            assert not p[url] or re.match(r"^https?://", p[url]), (p["id"], url)
        if p["key_env"]:
            assert re.match(r"^[A-Z][A-Z0-9_]+$", p["key_env"]), p["id"]
        # A hosted, key-based provider must say where to get the key.
        if p["auth"] in ("api_key", "oauth") and p["group"] != "Local":
            assert p["key_env"] and p["key_url"], p["id"]
        if p["group"] == "Local":
            assert p["needs_base_url"], p["id"]
    # Every group is populated.
    assert {p["group"] for p in cat.CATALOG} == set(cat.GROUPS)


def test_no_two_hosted_providers_share_a_key_env():
    """The old bug: opencode and openai_compat both read OPENAI_API_KEY."""
    seen: dict[str, str] = {}
    for p in cat.CATALOG:
        env = p["key_env"]
        if not env:
            continue
        assert env not in seen, f"{p['id']} and {seen[env]} share {env}"
        seen[env] = p["id"]
    assert cat.CATALOG_BY_ID["opencode"]["key_env"] != "OPENAI_API_KEY"
    assert cat.CATALOG_BY_ID["openai_compat"]["key_env"] != "OPENAI_API_KEY"


def test_hermes_env_vars_and_base_urls():
    """Spot-check parity with Hermes' registry (same names → keys carry over)."""
    by = cat.CATALOG_BY_ID
    assert (by["zai"]["key_env"], by["zai"]["base_url"]) == ("GLM_API_KEY", "https://api.z.ai/api/paas/v4")
    assert by["huggingface"]["key_env"] == "HF_TOKEN"
    assert by["ai-gateway"]["base_url"] == "https://ai-gateway.vercel.sh/v1"
    assert by["minimax"]["adapter"] == "anthropic"
    assert by["kimi-coding-cn"]["base_url"] == "https://api.moonshot.cn/v1"
    assert by["nous"]["base_url"] == "https://inference-api.nousresearch.com/v1"


@pytest.mark.parametrize("entry", cat.CATALOG, ids=lambda p: p["id"])
def test_every_entry_builds_a_provider(entry):
    for t in (entry["id"], *entry["aliases"]):
        assert t in PROVIDER_TYPES
    base = entry["base_url"] or ("https://example.test/v1" if entry["needs_base_url"] else "")
    prov = build_provider({"type": entry["id"], "model": "m", "base_url": base})
    assert isinstance(prov, ADAPTERS[entry["adapter"]])
    assert prov.model == "m"
    if entry["base_url"] and entry["adapter"] not in ("bedrock",):
        assert prov.base_url == entry["base_url"].rstrip("/")
    if entry["key_env"]:
        assert prov._api_key_env == entry["key_env"]
    # Never raises; either usable or says why not.
    assert prov.is_available() or prov.unavailable_reason()


def test_registry_defaults_are_derived_from_the_catalogue():
    for p in cat.CATALOG:
        d = _TYPE_DEFAULTS[p["id"]]
        assert d.get("base_url", "") == p["base_url"]
        assert d.get("api_key_env", "") == p["key_env"]
    # aliases share their entry's defaults
    assert _TYPE_DEFAULTS["gemini"] == _TYPE_DEFAULTS["google"]
    assert _TYPE_DEFAULTS["opencode-zen"] == _TYPE_DEFAULTS["opencode"]


def test_borrowed_adapters_never_read_another_providers_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-real")
    for env in ("MINIMAX_API_KEY", "GROQ_API_KEY", "OPENAI_COMPAT_API_KEY"):
        monkeypatch.delenv(env, raising=False)
    minimax = build_provider({"type": "minimax", "model": "MiniMax-M3"})
    assert minimax._api_key == "" and not minimax.is_available()
    groq = build_provider({"type": "groq", "model": "x"})
    assert groq._api_key == ""
    # Natives still use their own conventional var.
    assert build_provider({"type": "anthropic", "model": "c"})._api_key == "sk-ant-real"
    assert build_provider({"type": "openai", "model": "g"})._api_key == "sk-openai-real"


def test_derived_presets_cover_the_catalogue():
    from namma_agent.core.setup_wizard import _ORDER, PROVIDER_PRESETS

    assert set(PROVIDER_PRESETS) == set(cat.CATALOG_BY_ID)
    for pid, preset in PROVIDER_PRESETS.items():
        entry = cat.CATALOG_BY_ID[pid]
        assert preset["api_key_env"] == entry["key_env"]
        assert (preset["base_url"] or "") == entry["base_url"]
        assert preset["needs_key"] == entry["needs_key"]
    assert set(_ORDER) <= set(PROVIDER_PRESETS)
    # Curated defaults survive the derivation.
    assert PROVIDER_PRESETS["anthropic"]["default_model"] == "claude-opus-4-8"
    assert PROVIDER_PRESETS["groq"]["default_model"] == "llama-3.3-70b-versatile"


def test_configure_provider_works_for_a_new_catalogue_entry(tmp_path):
    from namma_agent.core.setup_wizard import configure_provider

    cfg, env = tmp_path / "c.yaml", tmp_path / ".env"
    cfg.write_text("persona: core\n", encoding="utf-8")
    prov = configure_provider("fireworks", api_key="fw-test", config_path=str(cfg),
                              env_path=str(env))
    assert prov["base_url"] == "https://api.fireworks.ai/inference/v1"
    assert prov["api_key_env"] == "FIREWORKS_API_KEY"
    assert "FIREWORKS_API_KEY=fw-test" in env.read_text(encoding="utf-8")


def test_list_models_uses_curated_fallback_and_skips_unlistable(monkeypatch):
    calls = []
    monkeypatch.setattr(cat, "_get_json", lambda url, h, timeout=8: calls.append(url) or {})
    r = cat.list_models_result("bedrock")
    assert r["source"] == "fallback" and r["models"] and calls == []
    r = cat.list_models_result("minimax", api_key="k")       # no /models route
    assert r["models"][0] == "MiniMax-M3" and calls == []
    cat.list_models_result("kimi", api_key="k")               # alias → its base_url
    assert calls == ["https://api.moonshot.ai/v1/models"]


# ── GET /api/providers ───────────────────────────────────────────────────────

def _svc(models=None, providers=None):
    cfg = {"persona": "core", "conversation": {},
           "provider": {"type": "anthropic", "model": "claude-x"}}
    if models is not None:
        cfg["models"] = models
    if providers is not None:
        cfg["providers"] = providers
    return NammaAgentService(config=cfg, provider=ts.ScriptedProvider([LLMResponse(content="hi")]),
                             registry=ToolRegistry(), db=Database(":memory:"))


def test_providers_endpoint_contract_shape(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_x")
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    monkeypatch.setenv("MY_OWN_MISTRAL", "m")
    svc = _svc(providers=[{"id": "Mine", "type": "mistral", "api_key_env": "MY_OWN_MISTRAL"}])
    body = TestClient(create_app(svc)).get("/api/providers").json()
    rows = {p["id"]: p for p in body["providers"]}
    assert body["groups"] == list(cat.GROUPS)
    for p in body["providers"]:
        assert CONTRACT_FIELDS <= set(p), p["id"]
        assert {"type", "needs_key", "key_prefix"} <= set(p)       # what today's UI reads
        assert p["type"] == p["id"]
    assert rows["groq"]["key_set"] and rows["groq"]["connected"]
    assert rows["ollama"]["connected"] and rows["ollama"]["auth"] == "none"
    # Connected through the user's own configured connection (its own key var).
    assert rows["mistral"]["key_set"] is False and rows["mistral"]["connected"] is True
    assert rows["openrouter"]["auth"] == "oauth" and "api_key" in rows["openrouter"]["auths"]
    assert "active" in body


# ── OpenRouter PKCE ──────────────────────────────────────────────────────────

def test_pkce_s256_matches_rfc7636():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"   # RFC 7636 appendix B
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    v = pkce_verifier()
    assert 43 <= len(v) <= 128 and re.match(r"^[A-Za-z0-9_-]+$", v)
    expect = base64.urlsafe_b64encode(hashlib.sha256(v.encode()).digest()).decode().rstrip("=")
    assert pkce_challenge(v) == expect


def test_oauth_manager_flow_with_mocked_exchange():
    posted = []

    def poster(url, payload, timeout):
        posted.append((url, payload))
        return 200, {"key": "sk-or-v1-abc"}

    mgr = OAuthManager(poster=poster)
    flow = mgr.start("openrouter", "http://127.0.0.1:8000")
    u = urllib.parse.urlparse(flow["authorize_url"])
    q = dict(urllib.parse.parse_qsl(u.query))
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://openrouter.ai/auth"
    assert q["code_challenge_method"] == "S256"
    assert q["callback_url"] == f"http://127.0.0.1:8000/api/oauth/openrouter/callback/{flow['state']}"
    env, key = mgr.finish("openrouter", flow["state"], "the-code")
    assert (env, key) == ("OPENROUTER_API_KEY", "sk-or-v1-abc")
    url, payload = posted[0]
    assert url == "https://openrouter.ai/api/v1/auth/keys"
    assert payload["code"] == "the-code" and payload["code_challenge_method"] == "S256"
    assert pkce_challenge(payload["code_verifier"]) == q["code_challenge"]
    # Single use.
    with pytest.raises(OAuthError):
        mgr.finish("openrouter", flow["state"], "the-code")


def test_oauth_manager_rejects_bad_state_expiry_and_refusals():
    now = [1000.0]
    mgr = OAuthManager(poster=lambda *a: (403, None), clock=lambda: now[0])
    with pytest.raises(OAuthError):
        mgr.start("anthropic", "http://x")                     # no OAuth for it
    f = mgr.start("openrouter", "http://x")
    with pytest.raises(OAuthError):
        mgr.finish("openrouter", "forged", "c")
    with pytest.raises(OAuthError, match="rejected"):
        mgr.finish("openrouter", f["state"], "c")              # 403 from the provider
    f = mgr.start("openrouter", "http://x")
    now[0] += 601
    with pytest.raises(OAuthError, match="expired"):
        mgr.finish("openrouter", f["state"], "c")
    mgr2 = OAuthManager(poster=lambda *a: (200, {"nokey": 1}))
    f = mgr2.start("openrouter", "http://x")
    with pytest.raises(OAuthError, match="key"):
        mgr2.finish("openrouter", f["state"], "c")


def test_oauth_endpoints_end_to_end_store_key_in_vault(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    svc = _svc()
    app = create_app(svc)
    app.state.oauth._poster = lambda url, payload, timeout: (200, {"key": "sk-or-v1-zzz"})
    c = TestClient(app)
    r = c.post("/api/providers/openrouter/oauth/start").json()
    assert r["authorize_url"].startswith("https://openrouter.ai/auth?")
    q = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(r["authorize_url"]).query))
    cb = urllib.parse.urlparse(q["callback_url"])
    resp = c.get(f"{cb.path}?code=abc", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/settings/model?connected=openrouter"
    from namma_agent.core.secrets import get_store
    assert get_store().get("OPENROUTER_API_KEY") == "sk-or-v1-zzz"
    rows = {p["id"]: p for p in c.get("/api/providers").json()["providers"]}
    assert rows["openrouter"]["key_set"] and rows["openrouter"]["connected"]
    # Replaying the callback fails cleanly (single-use nonce).
    again = c.get(f"{cb.path}?code=abc", follow_redirects=False)
    assert "oauth_error=" in again.headers["location"]


def test_oauth_contract_callback_path_with_state_query(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app = create_app(_svc())
    app.state.oauth._poster = lambda *a: (200, {"key": "sk-or-v1-q"})
    c = TestClient(app)
    url = c.post("/api/providers/openrouter/oauth/start").json()["authorize_url"]
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["callback_url"][0].rsplit("/", 1)[1]
    resp = c.get(f"/api/oauth/openrouter/callback?state={state}&code=x", follow_redirects=False)
    assert resp.headers["location"] == "/settings/model?connected=openrouter"
    denied = c.get("/api/oauth/openrouter/callback?error=access_denied", follow_redirects=False)
    assert "oauth_error=" in denied.headers["location"]


def test_oauth_start_refuses_cross_origin_and_unknown_providers():
    c = TestClient(create_app(_svc()))
    r = c.post("/api/providers/openrouter/oauth/start", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    ok = c.post("/api/providers/openrouter/oauth/start", headers={"Origin": "http://testserver"})
    assert ok.status_code == 200 and ok.json()["authorize_url"]
    assert c.post("/api/providers/groq/oauth/start").status_code == 404


def test_oauth_callback_passes_the_access_token_guard(monkeypatch):
    monkeypatch.setenv("NAMMA_AUTH_TOKEN", "t0ken-t0ken-t0ken")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    app = create_app(_svc())
    app.state.oauth._poster = lambda *a: (200, {"key": "sk-or-v1-t"})
    c = TestClient(app)
    assert c.post("/api/providers/openrouter/oauth/start").status_code == 401   # still guarded
    url = c.post("/api/providers/openrouter/oauth/start",
                 headers={"X-Namma-Token": "t0ken-t0ken-t0ken"}).json()["authorize_url"]
    cb = urllib.parse.urlparse(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["callback_url"][0])
    resp = c.get(f"{cb.path}?code=abc", follow_redirects=False)       # no token: a redirect
    assert resp.status_code == 303 and "connected=openrouter" in resp.headers["location"]


# ── active_model ─────────────────────────────────────────────────────────────

def _two_models_svc():
    return _svc(
        providers=[{"id": "oc", "type": "opencode", "api_key_env": "OPENCODE_ZEN_API_KEY"}],
        models=[{"id": "first", "provider": "oc", "model": "big-pickle"},
                {"id": "second", "provider": "oc", "model": "glm-5"}])


def test_active_model_defaults_to_first_then_follows_explicit_choice():
    svc = _two_models_svc()
    c = TestClient(create_app(svc))
    assert c.get("/api/active_model").json() == {"model_id": "first"}
    assert svc.provider_for("").model == "big-pickle"
    r = c.post("/api/active_model", json={"model_id": "second"}).json()
    assert r == {"ok": True, "model_id": "second"}
    assert c.get("/api/active_model").json()["model_id"] == "second"
    # The default brain follows it, and so does every "first in models:" reader.
    assert svc.provider_for("").model == "glm-5"
    assert svc.provider_for("unknown").model == "glm-5"
    assert c.get("/api/configured_models").json()["models"][0]["id"] == "second"
    assert svc.setup_status(check_gws=False)["default_model"] == "second"


def test_active_model_persists_to_user_config(_isolated_user_config):
    import yaml

    svc = _two_models_svc()
    TestClient(create_app(svc)).post("/api/active_model", json={"model_id": "second"})
    saved = yaml.safe_load(_isolated_user_config.read_text(encoding="utf-8"))
    assert saved["active_model"] == "second"
    assert [m["id"] for m in saved["models"]][:1] == ["second"]


def test_active_model_rejects_unknown_and_falls_back_when_removed():
    svc = _two_models_svc()
    c = TestClient(create_app(svc))
    bad = c.post("/api/active_model", json={"model_id": "ghost"}).json()
    assert bad["ok"] is False and bad["model_id"] == "first"
    c.post("/api/active_model", json={"model_id": "second"})
    svc.reload_models([{"id": "first", "provider": "oc", "model": "big-pickle"}])
    assert svc.active_model_id() == "first"          # stale choice → first in list
    assert c.post("/api/active_model", json={"model_id": ""}).json()["ok"]


def test_save_model_make_default_sets_active_model():
    svc = _two_models_svc()
    r = svc.setup_save_model("oc", "kimi-k2.6", make_default=True)
    assert r["default"] == "kimi-k2.6" and svc.active_model_id() == "kimi-k2.6"


def test_provider_ready_still_works_with_active_model(monkeypatch):
    monkeypatch.delenv("OPENCODE_ZEN_API_KEY", raising=False)
    svc = _two_models_svc()
    assert svc.provider_ready() is False
    monkeypatch.setenv("OPENCODE_ZEN_API_KEY", "k")
    svc.set_active_model("second")
    assert svc.provider_ready() is True


# ── cloud adapters (optional SDKs, mocked) ───────────────────────────────────

def test_bedrock_without_boto3_says_install(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", None)
    prov = build_provider({"type": "bedrock", "model": "m"})
    assert not prov.is_available()
    assert "pip install boto3" in prov.unavailable_reason()


def test_bedrock_converse_translation_with_fake_boto3(monkeypatch):
    sent = {}

    class FakeClient:
        def converse(self, **body):
            sent.update(body)
            return {"output": {"message": {"content": [
                {"text": "calling"},
                {"toolUse": {"toolUseId": "t2", "name": "lookup", "input": {"q": "y"}}}]}},
                "usage": {"inputTokens": 5, "outputTokens": 2}, "stopReason": "tool_use"}

    fake = types.SimpleNamespace(client=lambda service, **kw: FakeClient())
    monkeypatch.setitem(sys.modules, "boto3", fake)
    monkeypatch.setenv("AWS_REGION", "eu-west-1")
    prov = build_provider({"type": "bedrock", "model": "us.anthropic.claude-sonnet-4-6",
                           "base_url": ""})
    assert prov.region == "eu-west-1"
    resp = prov.generate([
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [ToolCall("t1", "lookup", {"q": "x"})]},
        {"role": "tool", "tool_call_id": "t1", "name": "lookup", "content": "found"},
    ], tools=[{"name": "lookup", "description": "d", "parameters": {"type": "object"}}])
    assert sent["system"] == [{"text": "be brief"}]
    assert [m["role"] for m in sent["messages"]] == ["user", "assistant", "user"]
    assert sent["messages"][2]["content"][0]["toolResult"]["toolUseId"] == "t1"
    assert sent["toolConfig"]["tools"][0]["toolSpec"]["name"] == "lookup"
    assert resp.content == "calling" and resp.tool_calls[0].args == {"q": "y"}
    assert resp.usage["input_tokens"] == 5 and resp.provider == "bedrock"


def test_vertex_builds_endpoint_from_project(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "my-proj")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    prov = build_provider({"type": "vertex", "model": "google/gemini-2.5-flash"})
    assert prov.base_url == ("https://us-central1-aiplatform.googleapis.com/v1/projects/my-proj"
                             "/locations/us-central1/endpoints/openapi")
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT")
    monkeypatch.delenv("VERTEX_PROJECT", raising=False)
    bare = build_provider({"type": "vertex", "model": "m"})
    assert not bare.is_available() and "GOOGLE_CLOUD_PROJECT" in bare.unavailable_reason()


def test_azure_needs_endpoint_and_uses_api_version(monkeypatch):
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "az")
    assert not build_provider({"type": "azure-foundry", "model": "dep"}).is_available()
    prov = build_provider({"type": "azure", "model": "dep",
                           "base_url": "https://r.openai.azure.com/openai/v1",
                           "api_version": "2024-10-21"})
    assert prov.api_version == "2024-10-21"
    client = prov._client()
    assert type(client).__name__ == "AzureOpenAI"
