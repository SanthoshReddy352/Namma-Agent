"""Provider catalog + model-listing for the settings UI."""
from __future__ import annotations

from fastapi.testclient import TestClient

from friday.core.memory import Database
from friday.core.providers.base import LLMResponse
from friday.core.providers.catalog import list_models, list_models_result, provider_catalog
from friday.core.tools import ToolRegistry
from friday.server.api import create_app
from friday.service import FridayService
import friday.tests.test_server as ts


def test_catalog_has_all_providers(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    cat = {p["type"]: p for p in provider_catalog()}
    assert {"anthropic", "openai", "google", "opencode", "openai_compat", "lmstudio", "ollama"} <= set(cat)
    assert cat["anthropic"]["key_set"] is True
    assert cat["google"]["key_set"] is False
    assert cat["lmstudio"]["needs_key"] is False


def test_list_models_fallback_when_no_key():
    # No network/key → curated fallback (never empty for known providers).
    assert "claude-opus-4-8" in list_models("anthropic", api_key="")
    assert list_models("openai", api_key="")  # non-empty fallback


def test_list_models_result_reports_source_and_error():
    # A bad/missing base URL can't be fetched → fallback source + an actionable error.
    r = list_models_result("openai_compat", base_url="", api_key="")
    assert r["source"] == "fallback"
    assert r["error"]  # tells the user to set a Base URL
    # Known provider with no key still yields a non-empty curated list (never blank).
    r2 = list_models_result("anthropic", api_key="")
    assert r2["models"] and r2["source"] == "fallback"


def test_models_endpoint_returns_source(monkeypatch):
    # The live fetch is monkeypatched so the test is offline-deterministic.
    import friday.core.providers.catalog as cat
    monkeypatch.setattr(cat, "_get_json", lambda url, headers, timeout=8: {
        "data": [{"id": "model-a"}, {"id": "model-b"}]})
    r = cat.list_models_result("opencode", base_url="https://example/v1", api_key="k")
    assert r["source"] == "live"
    assert r["models"] == ["model-a", "model-b"] and r["error"] == ""


def test_provider_endpoints():
    svc = FridayService(
        config={"persona": "core", "conversation": {}, "provider": {"type": "anthropic", "model": "claude-x"}},
        provider=ts.ScriptedProvider([LLMResponse(content="hi")]),
        registry=ToolRegistry(), db=Database(":memory:"))
    c = TestClient(create_app(svc))
    pr = c.get("/api/providers").json()
    assert "providers" in pr and pr["active"]["type"] == "anthropic"
    md = c.get("/api/models?type=anthropic").json()
    assert "models" in md and isinstance(md["models"], list)


def _svc_with_models(models):
    return FridayService(
        config={"persona": "core", "conversation": {},
                "provider": {"type": "opencode", "model": "big-pickle",
                             "base_url": "https://opencode.ai/zen/v1", "api_key_env": "OPENAI_API_KEY"},
                "models": models},
        provider=ts.ScriptedProvider([LLMResponse(content="hi")]),
        registry=ToolRegistry(), db=Database(":memory:"))


def _no_disk_config(monkeypatch):
    """Stop settings endpoints from writing the repo's real config.local.yaml /
    .env during tests — return the merged dict / write nothing instead."""
    import friday.config as fcfg
    monkeypatch.setattr(fcfg, "update_config", lambda updates, path=None: dict(updates or {}))
    monkeypatch.setattr(fcfg, "set_env_values", lambda updates, path=None: list((updates or {}).keys()))


def test_configured_models_crud_and_live_apply(monkeypatch):
    _no_disk_config(monkeypatch)
    svc = _svc_with_models([])
    c = TestClient(create_app(svc))
    assert c.get("/api/configured_models").json()["models"] == []
    body = {"models": [
        {"label": "Opus", "type": "opencode", "model": "claude-opus-4-8",
         "base_url": "https://opencode.ai/zen/v1", "api_key_env": "OPENAI_API_KEY"},
        {"label": "GPT", "type": "opencode", "model": "gpt-5.5",
         "base_url": "https://opencode.ai/zen/v1", "api_key_env": "OPENAI_API_KEY"},
    ]}
    saved = c.post("/api/configured_models", json=body).json()
    assert saved["ok"] and [m["id"] for m in saved["models"]] == ["claude-opus-4-8", "gpt-5.5"]
    # Applied live (no restart): the service can now resolve a provider per profile.
    assert svc.provider_for("gpt-5.5").model == "gpt-5.5"
    assert svc.provider_for("claude-opus-4-8").model == "claude-opus-4-8"
    # No/unknown id → the user's FIRST configured model (not the legacy chain), so
    # default turns + internal features (auto-title) use a working brain.
    assert svc.provider_for("").model == "claude-opus-4-8"
    assert svc.provider_for("nope").model == "claude-opus-4-8"


def test_settings_post_rebuilds_provider_live(monkeypatch):
    _no_disk_config(monkeypatch)
    svc = _svc_with_models([])
    before = svc.provider
    c = TestClient(create_app(svc))
    # Changing the default brain applies immediately — no restart.
    r = c.post("/api/settings", json={"config": {"provider": {
        "type": "openai", "model": "gpt-4o", "api_key_env": "OPENAI_API_KEY"}}}).json()
    assert r["ok"] and "live" in r["note"].lower()
    assert svc.provider is not before
    assert svc.provider.model == "gpt-4o"
    # The agent uses the rebuilt provider for default (no model_id) turns.
    assert svc.provider_for("") is svc.provider


def test_apply_config_keeps_previous_on_bad_spec():
    svc = _svc_with_models([])
    good = svc.provider
    svc.apply_config({"provider": {"type": "nonsense-provider", "model": "x"}})
    assert svc.provider is good  # bad spec ignored, previous brain retained


def test_configured_providers_crud_and_resolution(monkeypatch):
    _no_disk_config(monkeypatch)
    svc = _svc_with_models([])
    c = TestClient(create_app(svc))
    # Configure two providers, each with its OWN key variable.
    provs = {"providers": [
        {"label": "Opencode", "type": "opencode",
         "base_url": "https://opencode.ai/zen/v1", "api_key_env": "OPENCODE_API_KEY"},
        {"label": "Groq", "type": "openai_compat",
         "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"},
    ]}
    rp = c.post("/api/configured_providers", json=provs).json()
    assert rp["ok"] and [p["id"] for p in rp["providers"]] == ["Opencode", "Groq"]
    # Models reference providers by id — no inline keys/URLs.
    rm = c.post("/api/configured_models", json={"models": [
        {"label": "Opus", "provider": "Opencode", "model": "claude-opus-4-8"},
        {"label": "Llama", "provider": "Groq", "model": "llama-3.3-70b"},
    ]}).json()
    assert rm["ok"]
    # Each model resolves to its provider's connection + its OWN key var.
    opus = svc.provider_for("claude-opus-4-8")
    assert opus.base_url == "https://opencode.ai/zen/v1" and opus._api_key_env == "OPENCODE_API_KEY"
    llama = svc.provider_for("llama-3.3-70b")
    assert llama.base_url == "https://api.groq.com/openai/v1" and llama._api_key_env == "GROQ_API_KEY"


def test_models_endpoint_by_provider_id(monkeypatch):
    _no_disk_config(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "gk")
    import friday.core.providers.catalog as cat
    monkeypatch.setattr(cat, "_get_json", lambda url, headers, timeout=8: {
        "data": [{"id": "llama-3.3-70b"}, {"id": "mixtral"}]})
    svc = _svc_with_models([])
    c = TestClient(create_app(svc))
    c.post("/api/configured_providers", json={"providers": [
        {"label": "Groq", "type": "openai_compat",
         "base_url": "https://api.groq.com/openai/v1", "api_key_env": "GROQ_API_KEY"}]})
    r = c.get("/api/models?provider_id=Groq").json()
    assert r["source"] == "live" and r["models"] == ["llama-3.3-70b", "mixtral"]
    # Unknown provider id → clear error, never a crash.
    assert c.get("/api/models?provider_id=nope").json()["error"]


def test_env_status_endpoint(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    monkeypatch.delenv("NOPE_KEY", raising=False)
    svc = _svc_with_models([])
    c = TestClient(create_app(svc))
    r = c.get("/api/env_status?keys=GROQ_API_KEY,NOPE_KEY").json()["env_set"]
    assert r == {"GROQ_API_KEY": True, "NOPE_KEY": False}


def test_provider_for_prefers_first_model_then_legacy_default():
    # With models configured, no/unknown id resolves to the FIRST model.
    svc = _svc_with_models([{"label": "X", "type": "opencode", "model": "m-x",
                             "base_url": "https://example/v1", "api_key_env": "OPENCODE_API_KEY"}])
    assert svc.provider_for("m-x").model == "m-x"
    assert svc.provider_for("nope").model == "m-x"   # falls back to first model
    assert svc.provider_for(None).model == "m-x"
    # With NOTHING configured, fall back to the legacy config `provider:` default.
    empty = _svc_with_models([])
    assert empty.provider_for(None) is empty.provider


def test_session_binds_and_keeps_its_model():
    db = Database(":memory:")
    sid = db.create_session(model="m-x")
    assert db.get_session(sid)["model"] == "m-x"
    # A later turn can't silently change it; switching is a NEW session by design.
    db.set_session_model(sid, "m-y")
    assert db.get_session(sid)["model"] == "m-y"
    sid2 = db.create_session()  # no model → default brain
    assert (db.get_session(sid2)["model"] or "") == ""
