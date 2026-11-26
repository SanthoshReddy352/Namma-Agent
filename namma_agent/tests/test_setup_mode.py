"""Phase 5 — setup mode: secret paste guard, provider verification + failure
classification, integration status (gws / mail / bridges), the IMAP/SMTP mail
account model, the setup service operations, and setup-mode turns."""
from __future__ import annotations

import json
import subprocess

import pytest

from namma_agent.core import setup as setup_mod
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry
from namma_agent.tools import mail

OPENAI_KEY = "sk-proj-" + "A1b2C3d4" * 6


# ── paste guard ──────────────────────────────────────────────────────────────

def test_redact_secrets_labels_and_placeholders():
    text = (f"my key is {OPENAI_KEY} and github ghp_{'x' * 36}, "
            f"telegram 123456789:{'A' * 35}")
    clean, found = setup_mod.redact_secrets(text)
    assert OPENAI_KEY not in clean and "ghp_" not in clean and "123456789:" not in clean
    assert [f["env"] for f in found] == ["OPENAI_API_KEY", "GITHUB_PERSONAL_ACCESS_TOKEN",
                                         "NAMMA_TELEGRAM_TOKEN"]
    assert clean.count("use the secure key field") == 3


def test_redact_leaves_normal_text_alone():
    for text in ("commit 3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39 fixed it",
                 "use sk-learn for that", "ask-anything", "the AIza prefix", ""):
        assert setup_mod.redact_secrets(text) == (text, [])


def test_specific_pattern_wins_over_generic():
    _, found = setup_mod.redact_secrets("sk-ant-" + "Z" * 40)
    assert [f["label"] for f in found] == ["Anthropic API key"]


# ── provider verification ────────────────────────────────────────────────────

def _listing(models=None, error=""):
    return lambda *a, **k: {"models": models or [], "source": "live" if models else "fallback",
                            "error": error}


def test_verify_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = setup_mod.verify_provider("openai", "gpt-x")
    assert r["code"] == "missing_key" and not r["ok"]


@pytest.mark.parametrize("error, code", [
    ("Provider rejected the request (401) — check the API key.", "bad_key"),
    ("Provider has no /models endpoint at that Base URL — check the URL.", "bad_base_url"),
    ("Couldn't reach the provider — check the Base URL / your connection.", "unreachable"),
])
def test_verify_classifies_listing_failures(monkeypatch, error, code):
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 20)
    from namma_agent.core.providers import catalog
    monkeypatch.setattr(catalog, "list_models_result", _listing(error=error))
    assert setup_mod.verify_provider("openai", "m")["code"] == code


@pytest.mark.parametrize("message, code", [
    ("openai failed after 1 attempts: Error code: 401 - invalid_api_key", "bad_key"),
    ("Error code: 404 - {'error': {'code': 'model_not_found'}}", "bad_model"),
    ("Error code: 429 - insufficient_quota", "quota"),
    ("Connection error: getaddrinfo failed", "unreachable"),
])
def test_verify_classifies_generate_failures(monkeypatch, message, code):
    monkeypatch.setenv("OPENAI_API_KEY", "x" * 20)
    from namma_agent.core.providers import catalog, registry

    class Boom:
        def generate(self, *a, **k):
            raise RuntimeError(message)

    monkeypatch.setattr(catalog, "list_models_result", _listing(["gpt-a", "gpt-b"]))
    monkeypatch.setattr(registry, "build_provider", lambda cfg: Boom())
    r = setup_mod.verify_provider("openai", "gpt-zzz")
    assert r["code"] == code and not r["ok"]
    assert r["models"] == ["gpt-a", "gpt-b"]


def test_verify_success_reports_latency(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g" * 20)
    from namma_agent.core.providers import catalog, registry
    seen = {}

    class Ok:
        def generate(self, *a, **k):
            return LLMResponse(content="OK")

    def build(cfg):
        seen.update(cfg)
        return Ok()

    monkeypatch.setattr(catalog, "list_models_result", _listing(["llama"]))
    monkeypatch.setattr(registry, "build_provider", build)
    r = setup_mod.verify_provider("groq", "llama")
    assert r["ok"] and r["code"] == "ok" and r["latency_ms"] >= 0
    assert seen["base_url"] == "https://api.groq.com/openai/v1" and seen["max_tokens"] == 16


def test_new_catalogue_types_build_with_their_defaults():
    from namma_agent.core.providers.registry import build_provider
    p = build_provider({"type": "openrouter", "model": "x", "base_url": ""})
    assert p.base_url == "https://openrouter.ai/api/v1"


# ── integrations ─────────────────────────────────────────────────────────────

def _fake_gws(monkeypatch, status: dict | None):
    monkeypatch.setattr(setup_mod.shutil, "which",
                        lambda n: None if status is None else "C:/bin/gws")
    out = "Using keyring backend: keyring\n" + json.dumps(status or {})
    monkeypatch.setattr(setup_mod.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, out, ""))


def test_gws_status_states(monkeypatch):
    _fake_gws(monkeypatch, None)
    assert setup_mod.gws_status()["state"] == "not_installed"
    _fake_gws(monkeypatch, {"client_config_exists": False})
    assert setup_mod.gws_status()["state"] == "needs_setup"
    _fake_gws(monkeypatch, {"client_config_exists": True, "has_refresh_token": True,
                            "token_valid": False, "token_error": "Bad Request",
                            "enabled_apis": ["gmail.googleapis.com"]})
    st = setup_mod.gws_status()
    assert st["state"] == "needs_login" and "gws auth login" in st["next"]
    assert st["services"] == {"gmail": True, "calendar": False, "drive": False}
    _fake_gws(monkeypatch, {"client_config_exists": True, "has_refresh_token": True,
                            "token_valid": True, "enabled_apis": [
                                "gmail.googleapis.com", "calendar-json.googleapis.com",
                                "drive.googleapis.com"]})
    assert setup_mod.gws_status() ["state"] == "ok"


def test_integrations_status_mail_and_bridges(monkeypatch):
    monkeypatch.delenv("NAMMA_TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("NAMMA_MAIL_WORK_PASSWORD", "pw")
    cfg = {"mail": {"accounts": [{"id": "work", "address": "a@b.co",
                                  "password_env": "NAMMA_MAIL_WORK_PASSWORD"}]}}
    rows = {r["id"]: r for r in setup_mod.integrations_status(cfg, check_gws=False)}
    assert rows["mail"]["state"] == "ok"
    assert rows["telegram"]["state"] == "not_configured" and rows["telegram"]["next"]
    assert setup_mod.integrations_status({}, check_gws=False)[1]["state"] == "not_configured"


# ── mail accounts ────────────────────────────────────────────────────────────

def test_mail_account_presets_and_validation():
    a = mail.normalize_account({"address": "me@fastmail.com", "provider": "fastmail",
                                "id": "Work Mail"})
    assert a["imap_host"] == "imap.fastmail.com" and a["smtp_port"] == 465
    assert a["id"] == "work-mail" and a["password_env"] == "NAMMA_MAIL_WORK_MAIL_PASSWORD"
    assert mail.normalize_account({"address": "x@icloud.com", "provider": "icloud"})["smtp_port"] == 587
    assert mail.validate_account({"address": "nope", "provider": "custom"})
    assert not mail.validate_account({"address": "a@b.co", "provider": "yahoo"})


def test_mail_tools_explain_missing_setup(monkeypatch):
    monkeypatch.setattr(mail, "_accounts", lambda: [])
    r = mail._mail_list({})
    assert not r.ok and "No email account" in r.error
    acc = mail.normalize_account({"address": "a@b.co", "provider": "zoho", "id": "z"})
    monkeypatch.setattr(mail, "_accounts", lambda: [acc])
    monkeypatch.delenv(acc["password_env"], raising=False)
    r = mail._mail_send({"to": "x@y.z", "subject": "s", "body": "b"})
    assert not r.ok and acc["password_env"] in r.error


# ── service operations ───────────────────────────────────────────────────────

class _Script(Provider):
    name = "scripted"

    def __init__(self, replies):
        super().__init__(model="scripted")
        self.replies = list(replies)
        self.seen: list = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen.append({"messages": messages, "tools": [t["name"] for t in tools or []]})
        return self.replies.pop(0) if self.replies else LLMResponse(content="done")


def _svc(provider=None):
    from namma_agent.core.setup_tools import register_setup_tools
    from namma_agent.service import NammaAgentService
    reg = ToolRegistry()
    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=provider or _Script([]), registry=reg,
                            db=Database(":memory:"))
    register_setup_tools(svc.registry, svc)   # an empty registry is falsy: use the service's
    return svc


def test_save_secret_only_accepts_credential_names(monkeypatch):
    svc = _svc()
    assert not svc.setup_save_secret("PATH", "x")["ok"]
    assert not svc.setup_save_secret("lower_api_key", "x")["ok"]
    assert not svc.setup_save_secret("GROQ_API_KEY", "  ")["ok"]
    r = svc.setup_save_secret("GROQ_API_KEY", "gsk_" + "q" * 30)
    assert r == {"ok": True, "name": "GROQ_API_KEY", "vault": True}
    assert "value" not in json.dumps(r)
    assert svc.secret_names()["GROQ_API_KEY"] is True


def test_provider_model_and_readiness(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    svc = _svc()
    assert not svc.setup_save_provider("nonsense")["ok"]
    p = svc.setup_save_provider("deepseek")
    assert p["ok"] and p["provider"]["base_url"] == "https://api.deepseek.com/v1"
    assert p["provider"]["api_key_env"] == "DEEPSEEK_API_KEY" and not p["key_set"]
    assert not svc.setup_save_model("missing", "m")["ok"]
    m = svc.setup_save_model(p["provider"]["id"], "deepseek-chat", make_default=True)
    assert m["ok"] and m["default"] == "deepseek-chat"
    assert svc.provider_ready() in (True, False)      # the scripted brain is "available"
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-" + "d" * 32)
    assert svc.provider_ready()


def test_onboard_only_sets_default_after_verify(monkeypatch):
    svc = _svc()
    from namma_agent.core import setup as s
    monkeypatch.setattr(s, "verify_provider",
                        lambda *a, **k: {"ok": False, "code": "bad_key", "message": "no"})
    r = svc.setup_onboard_provider("groq", "llama-3.3-70b-versatile", key="gsk_" + "k" * 30)
    assert r["code"] == "bad_key" and not svc.configured_models()
    monkeypatch.setattr(s, "verify_provider",
                        lambda *a, **k: {"ok": True, "code": "ok", "message": "fine"})
    r = svc.setup_onboard_provider("groq", "llama-3.3-70b-versatile")
    assert r["ok"] and svc.configured_models()[0]["model"] == "llama-3.3-70b-versatile"


def test_mail_add_persists_without_password(monkeypatch):
    svc = _svc()
    r = svc.setup_mail_add("me@yahoo.com", "yahoo")
    assert r["ok"] and r["password_env"] == "NAMMA_MAIL_ME_PASSWORD"
    assert "app_password_url" in r and svc.config["mail"]["accounts"][0]["imap_host"]
    assert "password" not in {k for k in svc.config["mail"]["accounts"][0] if k != "password_env"}
    assert not svc.setup_mail_add("bad-address")["ok"]


# ── setup-mode turns ─────────────────────────────────────────────────────────

def test_setup_mode_scopes_tools_and_prompt():
    prov = _Script([LLMResponse(content="hello")])
    svc = _svc(prov)
    svc.run_turn("help me set up", mode="setup")
    call = prov.seen[0]
    assert "request_secret" in call["tools"] and "setup_status" in call["tools"]
    assert "run_shell" not in call["tools"] and "tool_search" not in call["tools"]
    assert "SETUP MODE" in call["messages"][0]["content"]


def test_request_secret_places_a_card_not_a_value():
    prov = _Script([
        LLMResponse(content="", tool_calls=[ToolCall(id="1", name="request_secret", args={
            "name": "OPENAI_API_KEY", "label": "OpenAI key",
            "url": "https://platform.openai.com/api-keys"})]),
        LLMResponse(content="Paste it in the secure field above."),
    ])
    svc = _svc(prov)
    res = svc.run_turn("set up openai", mode="setup")
    assert "```secret" in res.content
    card = json.loads(res.content.split("```secret\n", 1)[1].split("\n```", 1)[0])
    assert card["name"] == "OPENAI_API_KEY" and card["url"].startswith("https://")
    bad = svc.registry.get("request_secret").handler({"name": "PATH"})
    assert not bad.ok


def test_pasted_key_never_reaches_model_or_transcript():
    prov = _Script([LLMResponse(content="I removed it — use the secure field.")])
    svc = _svc(prov)
    events = []
    res = svc.run_turn(f"here is my key {OPENAI_KEY}", mode="agent",
                       sink=lambda e, p: events.append((e, p)))
    sent = json.dumps(prov.seen[0]["messages"])
    assert OPENAI_KEY not in sent and "OpenAI API key" in sent
    stored = json.dumps(svc.db.session_turns(res.session_id))
    assert OPENAI_KEY not in stored
    assert any(e == "secret_redacted" for e, _ in events)
    assert all(OPENAI_KEY not in json.dumps(p) for _, p in events)


# ── isolation regressions found while verifying Phase 5 ─────────────────────

def test_shipped_config_does_not_pin_the_database_path():
    """A pinned database.path made NAMMA_DATA_DIR useless for the DB — and the
    vault + memory that live beside it (a scratch run wrote to the real data/)."""
    import yaml

    from namma_agent.config import _config_path
    base = yaml.safe_load(_config_path().read_text(encoding="utf-8"))
    assert not ((base.get("database") or {}).get("path"))


def test_explicit_env_file_skips_the_repo_dotenv(tmp_path, monkeypatch):
    from namma_agent import config as cfg
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("LEAKY_TEST_KEY=from-repo\n", encoding="utf-8")
    mine = tmp_path / "mine.env"
    mine.write_text("MINE_TEST_KEY=yes\n", encoding="utf-8")
    monkeypatch.setattr(cfg, "_REPO_ROOT", repo)
    monkeypatch.setenv("NAMMA_ENV_FILE", str(mine))
    monkeypatch.delenv("LEAKY_TEST_KEY", raising=False)
    monkeypatch.delenv("MINE_TEST_KEY", raising=False)
    cfg.load_dotenv()
    import os
    assert os.environ.get("MINE_TEST_KEY") == "yes" and "LEAKY_TEST_KEY" not in os.environ


def test_shipped_default_provider_is_not_ready(monkeypatch):
    """No model profiles + no user-set provider → onboarding, even when some
    OPENAI_API_KEY exists (the shipped default is opencode, which can't use it)."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-" + "x" * 40)
    svc = _svc()
    assert svc.configured_models() == []
    assert svc.provider_ready() is False
