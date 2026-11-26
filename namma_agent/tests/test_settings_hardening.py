"""Settings / upload hardening and live config re-apply.

Regression tests for audit findings (PROGRESS.md):
  * BUG-07 — .env writes accepted line breaks (injecting extra KEY=value lines);
    /api/settings said "applied live" but the agent's loop knobs were boot-only;
    six setters rebound ``self.config`` and left runners on a stale dict.
  * BUG-09 — /api/upload read the whole body into memory with no cap and
    overwrote same-named files.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from namma_agent.config import set_env_values
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.service import NammaAgentService


class _Provider(Provider):
    name = "scripted"

    def __init__(self):
        super().__init__(model="scripted")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="hi")


def _service(config: dict | None = None):
    cfg = {"persona": "core", "conversation": {}}
    cfg.update(config or {})
    return NammaAgentService(config=cfg, provider=_Provider(),
                             registry=ToolRegistry(), db=Database(":memory:"))


# -- .env writes --------------------------------------------------------------

@pytest.mark.parametrize("value", ["sk-abc\nNAMMA_API_TOKEN=", "a\rb", "a\x00b"])
def test_env_values_reject_line_breaks(tmp_path, value):
    env = tmp_path / ".env"
    env.write_text("KEEP=1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        set_env_values({"OPENAI_API_KEY": value}, path=str(env))
    assert env.read_text(encoding="utf-8") == "KEEP=1\n"


@pytest.mark.parametrize("key", ["BAD KEY", "1ABC", "A=B", "X\nY"])
def test_env_values_reject_bad_names(tmp_path, key):
    with pytest.raises(ValueError):
        set_env_values({key: "v"}, path=str(tmp_path / ".env"))


def test_env_values_still_write_normal_keys(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    monkeypatch.delenv("NAMMA_TEST_KEY_XYZ", raising=False)
    assert set_env_values({"NAMMA_TEST_KEY_XYZ": "value-1"}, path=str(env)) == ["NAMMA_TEST_KEY_XYZ"]
    assert "NAMMA_TEST_KEY_XYZ=value-1" in env.read_text(encoding="utf-8")
    monkeypatch.delenv("NAMMA_TEST_KEY_XYZ", raising=False)


# -- live re-apply ------------------------------------------------------------

def test_apply_config_reapplies_agent_loop_knobs():
    svc = _service({"conversation": {"tool_loop_limit": 0, "tool_result_max_chars": 0}})
    assert svc.agent.tool_loop_limit == 0
    svc.apply_config({
        "persona": "core",
        "conversation": {"tool_loop_limit": 7, "max_history_turns": 5,
                         "tool_result_max_chars": 1234, "compact_history": False},
        "tools": {"allow": ["web"], "max_per_request": 64},
    })
    a = svc.agent
    assert (a.tool_loop_limit, a.max_history_turns, a.tool_result_max_chars) == (7, 5, 1234)
    assert a.compact_history is False
    assert a.tool_allow == ["web"]
    assert a.max_tools_per_request == 64


def test_replace_config_keeps_the_same_dict_object():
    svc = _service()
    original = svc.config
    svc._replace_config({"persona": "core", "conversation": {"x": 1}})
    assert svc.config is original and svc.config["conversation"] == {"x": 1}


# -- uploads ------------------------------------------------------------------

@pytest.fixture
def client(tmp_path, monkeypatch):
    from namma_agent.server import api
    monkeypatch.setattr(api, "_UPLOAD_DIR", tmp_path / "uploads")
    svc = _service({"server": {"max_upload_mb": 0.01}})  # ~10 KB cap
    return TestClient(api.create_app(svc)), tmp_path / "uploads"


def test_upload_rejects_files_over_the_cap(client):
    c, updir = client
    r = c.post("/api/upload", files={"file": ("big.bin", b"x" * 20_000)})
    assert r.status_code == 413
    assert not any(updir.glob("*")) if updir.exists() else True


def test_upload_never_overwrites_a_same_named_file(client):
    c, updir = client
    first = c.post("/api/upload", files={"file": ("notes.txt", b"one")}).json()
    second = c.post("/api/upload", files={"file": ("notes.txt", b"two")}).json()
    assert first["ok"] and second["ok"] and first["path"] != second["path"]
    assert second["name"] == "notes (2).txt"
    assert (updir / "notes.txt").read_bytes() == b"one"
    assert (updir / "notes (2).txt").read_bytes() == b"two"


def test_settings_endpoint_rejects_env_injection(client):
    c, _ = client
    r = c.post("/api/settings", json={"env": {"OPENAI_API_KEY": "sk\nNAMMA_API_TOKEN="}})
    assert r.status_code == 400
