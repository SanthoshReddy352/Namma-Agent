"""Phase 6a — bind config, access-token auth (REST + WS), data-dir override."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from namma_agent import config as config_mod
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.server.api import create_app
from namma_agent.service import NammaAgentService


class _Provider(Provider):
    name = "scripted"

    def __init__(self):
        super().__init__(model="scripted")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="hi")


def _service(extra_config: dict | None = None):
    cfg = {"persona": "core", "conversation": {}}
    cfg.update(extra_config or {})
    return NammaAgentService(config=cfg, provider=_Provider(),
                             registry=ToolRegistry(), db=Database(":memory:"))


# ── bind config ──────────────────────────────────────────────────────────────

def test_server_bind_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    assert config_mod.server_bind({}) == ("127.0.0.1", 8000)


def test_server_bind_from_config_and_port_env(monkeypatch):
    monkeypatch.delenv("PORT", raising=False)
    host, port = config_mod.server_bind({"server": {"host": "0.0.0.0", "port": 9000}})
    assert (host, port) == ("0.0.0.0", 9000)
    monkeypatch.setenv("PORT", "9001")  # legacy env override still wins
    assert config_mod.server_bind({"server": {"port": 9000}})[1] == 9001


def test_auth_token_resolution(monkeypatch):
    monkeypatch.delenv("NAMMA_AUTH_TOKEN", raising=False)
    assert config_mod.auth_token({}) == ""
    assert config_mod.auth_token({"server": {"auth_token": "abc"}}) == "abc"
    monkeypatch.setenv("NAMMA_AUTH_TOKEN", "env-wins")
    assert config_mod.auth_token({"server": {"auth_token": "abc"}}) == "env-wins"


# ── REST auth ────────────────────────────────────────────────────────────────

def test_no_token_configured_means_open(monkeypatch):
    monkeypatch.delenv("NAMMA_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(_service()))
    assert client.get("/api/config").status_code == 200


def test_api_requires_token_when_set(monkeypatch):
    monkeypatch.delenv("NAMMA_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(_service({"server": {"auth_token": "s3cret"}})))
    # No token / wrong token → 401 on /api/*.
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/config", headers={"X-Namma-Token": "wrong"}).status_code == 401
    # All three supported carriers.
    assert client.get("/api/config", headers={"X-Namma-Token": "s3cret"}).status_code == 200
    assert client.get("/api/config",
                      headers={"Authorization": "Bearer s3cret"}).status_code == 200
    assert client.get("/api/config?token=s3cret").status_code == 200
    # Health stays open (Docker/systemd probes have no token).
    assert client.get("/api/health").status_code == 200


def test_static_shell_stays_open(monkeypatch):
    """The UI shell must load without a token — it hosts the unlock screen."""
    monkeypatch.delenv("NAMMA_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(_service({"server": {"auth_token": "s3cret"}})))
    r = client.get("/")
    assert r.status_code != 401  # 200 with a built webui; 404 without — never locked


# ── WebSocket auth ───────────────────────────────────────────────────────────

def test_ws_rejects_bad_token(monkeypatch):
    monkeypatch.delenv("NAMMA_AUTH_TOKEN", raising=False)
    client = TestClient(create_app(_service({"server": {"auth_token": "s3cret"}})))
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 4401
    # Correct token connects.
    with client.websocket_connect("/ws?token=s3cret"):
        pass


# ── data dir ─────────────────────────────────────────────────────────────────

def test_data_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path / "state"))
    assert config_mod.data_dir() == tmp_path / "state"
    monkeypatch.delenv("NAMMA_DATA_DIR", raising=False)
    assert str(config_mod.data_dir()) == "data"


def test_stores_follow_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMMA_DATA_DIR", str(tmp_path))
    from namma_agent.core.routines import _store_path as routines_path
    from namma_agent.core.self_review import _dir as review_dir
    from namma_agent.core.watchers import _store_path as watchers_path
    assert watchers_path({}) == tmp_path / "watchers.json"
    assert routines_path({}) == tmp_path / "routines.json"
    assert review_dir({}) == tmp_path / "self_review"
