"""Start-on-login (Phase 5) — registry/XDG registration + the REST surface."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from namma_agent.core import autostart
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


def _service():
    return NammaAgentService(config={"persona": "core", "conversation": {}},
                             provider=_Provider(), registry=ToolRegistry(),
                             db=Database(":memory:"))


def test_launch_command_quotes_interpreter():
    cmd = autostart.launch_command()
    assert cmd.startswith('"') and cmd.endswith('" -m namma_agent')
    if os.name == "nt":
        # Windowed launcher preferred when it exists next to python.exe.
        assert "python" in cmd.lower()


def test_unsupported_platform_reports_honestly(monkeypatch):
    monkeypatch.setattr(autostart.platform, "system", lambda: "Darwin")
    assert autostart.supported() is False
    r = autostart.set_enabled(True)
    assert r["ok"] is False and "not supported" in r["error"]
    assert autostart.status()["supported"] is False


def test_linux_desktop_file_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart.platform, "system", lambda: "Linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert autostart.enabled() is False
    r = autostart.set_enabled(True)
    assert r == {"ok": True, "enabled": True}
    entry = tmp_path / "autostart" / "namma-agent.desktop"
    assert entry.is_file()
    text = entry.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in text and "-m namma_agent" in text
    assert autostart.enabled() is True
    r = autostart.set_enabled(False)
    assert r == {"ok": True, "enabled": False}
    assert not entry.exists() and autostart.enabled() is False


@pytest.mark.skipif(os.name != "nt", reason="real HKCU Run key is Windows-only")
def test_windows_run_key_roundtrip(monkeypatch):
    # A test-only value name so the user's real toggle is never touched.
    monkeypatch.setattr(autostart, "_VALUE_NAME", "NammaAgentTestEntry")
    try:
        assert autostart.enabled() is False
        r = autostart.set_enabled(True)
        assert r == {"ok": True, "enabled": True}
        assert autostart.enabled() is True
    finally:
        assert autostart.set_enabled(False)["ok"] is True
    assert autostart.enabled() is False


def test_autostart_endpoints(monkeypatch):
    calls = {}
    monkeypatch.setattr(autostart, "status",
                        lambda: {"supported": True, "enabled": False,
                                 "command": "x", "platform": "Windows"})

    def fake_set(on):
        calls["on"] = on
        return {"ok": True, "enabled": on}

    monkeypatch.setattr(autostart, "set_enabled", fake_set)
    client = TestClient(create_app(_service()))
    r = client.get("/api/autostart")
    assert r.status_code == 200 and r.json()["supported"] is True
    r = client.post("/api/autostart", json={"enabled": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "enabled": True}
    assert calls["on"] is True
