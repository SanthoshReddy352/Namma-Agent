"""Native desktop notifications — backend module + /api/notify route."""
from __future__ import annotations

from fastapi.testclient import TestClient

from namma_agent.core import notifications
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
    return NammaAgentService(
        config={"persona": "core", "conversation": {}},
        provider=_Provider(),
        registry=ToolRegistry(),
        db=Database(":memory:"),
    )


def test_native_notification_dispatches_per_platform(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications.subprocess, "Popen",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(notifications.shutil, "which", lambda _n: "/usr/bin/notify-send")

    for system in ("Windows", "Darwin", "Linux"):
        calls.clear()
        monkeypatch.setattr(notifications.platform, "system", lambda s=system: s)
        assert notifications.send_native_notification("Title", "Body") is True
        assert len(calls) == 1  # exactly one OS helper spawned


def test_native_notification_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("no spawning here")

    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notifications.subprocess, "Popen", boom)
    # Best-effort: a failure to spawn returns False, never propagates.
    assert notifications.send_native_notification("t", "b") is False


def test_api_notify_route(monkeypatch):
    seen = {}

    def fake(title, body=""):
        seen["title"], seen["body"] = title, body
        return True

    monkeypatch.setattr(notifications, "send_native_notification", fake)
    client = TestClient(create_app(_service()))
    r = client.post("/api/notify", json={"title": "Response ready", "body": "done"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert seen == {"title": "Response ready", "body": "done"}
