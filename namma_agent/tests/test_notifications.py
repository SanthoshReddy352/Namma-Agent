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


def _toasts_available(monkeypatch):
    """Pretend the OS is willing to render toasts (the Windows gate reads HKCU)."""
    monkeypatch.setattr(notifications, "_windows_toasts_enabled", lambda: (True, ""))


def test_native_notification_dispatches_per_platform(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications.subprocess, "Popen",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(notifications.shutil, "which", lambda _n: "/usr/bin/notify-send")
    _toasts_available(monkeypatch)

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
    _toasts_available(monkeypatch)
    # Best-effort: a failure to spawn returns False, never propagates.
    assert notifications.send_native_notification("t", "b") is False


def test_windows_toast_carries_action_urls(monkeypatch):
    """Phase 5: the Windows toast has Reply/Open protocol actions wired to the
    app URL (Reply carries the ?reply=1 hint), passed via env — never templated
    into the script body."""
    calls = []
    monkeypatch.setattr(notifications.subprocess, "Popen",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    _toasts_available(monkeypatch)
    assert notifications.send_native_notification(
        "T", "B", url="http://127.0.0.1:9999") is True
    (argv,), kwargs = calls[0][0], calls[0][1]
    env = kwargs["env"]
    assert env["NAMMA_NOTIFY_URL"] == "http://127.0.0.1:9999"
    assert env["NAMMA_NOTIFY_REPLY_URL"] == "http://127.0.0.1:9999?reply=1"
    script = argv[-1]
    assert "ToastNotificationManager" in script     # the modern toast path
    assert 'content="Reply"' in script and 'content="Open"' in script
    assert "NotifyIcon" in script                   # the graceful fallback


def test_windows_toast_default_url(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications.subprocess, "Popen",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    _toasts_available(monkeypatch)
    monkeypatch.delenv("NAMMA_APP_URL", raising=False)
    monkeypatch.delenv("PORT", raising=False)
    notifications.send_native_notification("T")
    env = calls[0][1]["env"]
    assert env["NAMMA_NOTIFY_URL"] == "http://127.0.0.1:8000"


def test_api_notify_route(monkeypatch):
    seen = {}

    def fake(title, body=""):
        seen["title"], seen["body"] = title, body
        return True

    monkeypatch.setattr(notifications, "send_native_notification", fake)
    client = TestClient(create_app(_service()))
    r = client.post("/api/notify", json={"title": "Response ready", "body": "done"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "reason": ""}
    assert seen == {"title": "Response ready", "body": "done"}


def test_windows_toasts_gated_on_os_switch(monkeypatch):
    """The core fix: Show() succeeds silently when Windows notifications are off,
    so we must not spawn-and-claim-success — report False so the UI can fall back."""
    spawned = []
    monkeypatch.setattr(notifications.subprocess, "Popen",
                        lambda *a, **k: spawned.append(a))
    monkeypatch.setattr(notifications.platform, "system", lambda: "Windows")
    monkeypatch.setattr(notifications, "_windows_toasts_enabled",
                        lambda: (False, "Windows notifications are turned off."))

    assert notifications.send_native_notification("T", "B") is False
    assert spawned == []  # no pointless helper process
    assert notifications.notification_status() == {
        "available": False,
        "reason": "Windows notifications are turned off.",
        "platform": "windows",
    }


def test_linux_status_needs_notify_send(monkeypatch):
    monkeypatch.setattr(notifications.platform, "system", lambda: "Linux")
    monkeypatch.setattr(notifications.shutil, "which", lambda _n: None)
    st = notifications.notification_status()
    assert st["available"] is False and "notify-send" in st["reason"]
    assert notifications.send_native_notification("T", "B") is False

    monkeypatch.setattr(notifications.shutil, "which", lambda _n: "/usr/bin/notify-send")
    assert notifications.notification_status()["available"] is True


def test_api_notify_reports_reason_when_os_refuses(monkeypatch):
    """/api/notify tells the UI *why* nothing showed, so Settings stops saying
    'Sent — check your desktop' when the OS displayed nothing."""
    monkeypatch.setattr(notifications, "send_native_notification", lambda *a, **k: False)
    monkeypatch.setattr(notifications, "notification_status",
                        lambda: {"available": False, "reason": "Turn them on.", "platform": "windows"})
    client = TestClient(create_app(_service()))
    r = client.post("/api/notify", json={"title": "T", "body": "b"})
    assert r.json() == {"ok": False, "reason": "Turn them on."}

    s = client.get("/api/notify/status")
    assert s.status_code == 200
    assert s.json()["available"] is False
