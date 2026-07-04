"""Track B — the Cognee Cloud config switch.

`register_cognee_server` upserts the single `cognee` MCP server entry to either the
self-hosted container (Track A) or Cognee Cloud serve mode (Track B). These tests
exercise that switch offline (no Docker, no reconnect) and assert the cloud API key
never lands in the persisted config — it goes to the gitignored .env.cognee.cloud.
"""
from __future__ import annotations

import json

import pytest

import namma_agent.config as cfgmod
from namma_agent.service import NammaAgentService


@pytest.fixture
def svc(tmp_path, monkeypatch):
    import threading
    s = NammaAgentService.__new__(NammaAgentService)  # skip heavy __init__
    s.config = {"mcp": {"servers": []}}
    s._mcp_lock = threading.RLock()
    s.mcp = None
    # targeted connect is stubbed - no Docker in unit tests
    monkeypatch.setattr(s, "_apply_one_mcp_server", lambda cfg, enabled: True)
    monkeypatch.setattr(s, "_cognee_env_path", lambda: tmp_path / ".env.cognee")
    monkeypatch.setattr(s, "_cloud_env_path", lambda: tmp_path / ".env.cognee.cloud")
    monkeypatch.setattr(s, "reload_mcp", lambda: None)
    # don't touch real Docker during unit tests
    monkeypatch.setattr(NammaAgentService, "_stop_cognee_containers", staticmethod(lambda: None))
    s._cognee_client = lambda: None
    # update_config just merges the patch in-memory and hands the config back.
    monkeypatch.setattr(cfgmod, "update_config", lambda patch: {**s.config, **patch})
    return s


def _cognee_server(s):
    servers = (s.config.get("mcp") or {}).get("servers") or []
    return next((x for x in servers if x.get("name") == "cognee"), None)


def test_local_registration(svc):
    out = svc.register_cognee_server("local")
    assert out["ok"] and out["mode"] == "local"
    srv = _cognee_server(svc)
    assert srv and "--network" in srv["command"] and "cognee-data:/cognee-data" in srv["command"]
    assert "--serve-url" not in srv["command"]
    # named so a stale/orphaned container can be force-removed on reconnect
    assert "--name" in srv["command"] and "namma_cognee" in srv["command"]
    assert svc._cognee_serve_url() == ""   # self-hosted


def test_cloud_registration_is_named_and_has_serve_url(svc):
    svc.register_cognee_server("cloud", serve_url="https://acme.cognee.ai", api_key="sk-x")
    srv = _cognee_server(svc)
    assert "--name" in srv["command"] and "namma_cognee" in srv["command"]
    assert svc._cognee_serve_url() == "https://acme.cognee.ai"


def test_cloud_registration_writes_key_outside_config(svc, tmp_path):
    out = svc.register_cognee_server("cloud", serve_url="https://acme.cognee.ai/",
                                     api_key="sk-cloud-secret")
    assert out["ok"], out
    assert out["mode"] == "cloud"
    assert out["serve_url"] == "https://acme.cognee.ai"   # trailing slash trimmed
    assert out["cloud_key_set"] is True

    srv = _cognee_server(svc)
    assert "--serve-url" in srv["command"]
    assert srv["command"][srv["command"].index("--serve-url") + 1] == "https://acme.cognee.ai"

    # The secret is in the gitignored cloud env file, NOT in the persisted config.
    cloud_env = (tmp_path / ".env.cognee.cloud").read_text(encoding="utf-8")
    assert "COGNEE_API_KEY=sk-cloud-secret" in cloud_env
    assert "sk-cloud-secret" not in json.dumps(svc.config)


def test_cloud_requires_url(svc):
    out = svc.register_cognee_server("cloud", serve_url="", api_key="sk-x")
    assert out["ok"] is False and "URL" in out["error"]
    assert _cognee_server(svc) is None   # nothing registered


def test_cloud_requires_key_first_time(svc):
    out = svc.register_cognee_server("cloud", serve_url="https://acme.cognee.ai")
    assert out["ok"] is False and "key" in out["error"].lower()


def test_cloud_keeps_existing_key_when_blank(svc, tmp_path):
    svc.register_cognee_server("cloud", serve_url="https://acme.cognee.ai", api_key="sk-first")
    # Re-register with a blank key (e.g. user only changed the URL) → key preserved.
    out = svc.register_cognee_server("cloud", serve_url="https://acme2.cognee.ai", api_key="")
    assert out["ok"] and out["serve_url"] == "https://acme2.cognee.ai"
    assert "COGNEE_API_KEY=sk-first" in (tmp_path / ".env.cognee.cloud").read_text(encoding="utf-8")


def test_switch_cloud_to_local_upserts_single_entry(svc):
    svc.register_cognee_server("cloud", serve_url="https://acme.cognee.ai", api_key="sk-x")
    svc.register_cognee_server("local")
    servers = [s for s in svc.config["mcp"]["servers"] if s["name"] == "cognee"]
    assert len(servers) == 1                       # one entry, swapped — not duplicated
    assert "--serve-url" not in servers[0]["command"]
    assert svc.cognee_settings()["mode"] == "local"


def test_docker_container_name_extraction():
    from namma_agent.mcp.client import _docker_container_name
    assert _docker_container_name(
        ["docker", "run", "-i", "--rm", "--name", "namma_cognee", "img"]) == "namma_cognee"
    assert _docker_container_name(["npx", "-y", "server"]) == ""   # not docker
    assert _docker_container_name(["docker", "run", "img"]) == ""  # no --name
