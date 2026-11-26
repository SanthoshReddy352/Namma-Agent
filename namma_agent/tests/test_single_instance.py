"""Single-instance launch (PROGRESS.md BUG-08).

A second launch used to build the WHOLE service (Telegram poller, MCP
subprocesses, runner threads) before noticing a backend was already running,
then open a second window + tray icon. Now it checks first, asks the running
instance to focus its window, and exits.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from namma_agent import app as launcher
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


def test_second_launch_focuses_existing_window_without_building_a_service(monkeypatch):
    calls = {"build": 0, "window": 0}
    monkeypatch.setattr(launcher, "_server_already_running", lambda: True)
    monkeypatch.setattr(launcher, "_request_focus", lambda: True)
    monkeypatch.setattr(launcher, "_build_service",
                        lambda: calls.__setitem__("build", calls["build"] + 1))
    monkeypatch.setattr(launcher, "_launch_window",
                        lambda *a, **k: calls.__setitem__("window", calls["window"] + 1))
    launcher.main()
    assert calls == {"build": 0, "window": 0}


def test_second_launch_attaches_a_window_when_the_backend_has_none(monkeypatch):
    seen = {}
    monkeypatch.setattr(launcher, "_server_already_running", lambda: True)
    monkeypatch.setattr(launcher, "_request_focus", lambda: False)
    monkeypatch.setattr(launcher, "_build_service",
                        lambda: (_ for _ in ()).throw(AssertionError("must not build")))
    monkeypatch.setattr(launcher, "_launch_window",
                        lambda service, thread, healthy=True: seen.update(service=service))
    launcher.main()
    assert seen == {"service": None}


def test_server_only_relaunch_does_nothing(monkeypatch):
    monkeypatch.setattr(launcher, "_server_already_running", lambda: True)
    monkeypatch.setattr(launcher, "_build_service",
                        lambda: (_ for _ in ()).throw(AssertionError("must not build")))
    launcher.main(server_only=True)


def test_focus_endpoint_reports_whether_a_window_exists(monkeypatch):
    from namma_agent.server.api import create_app
    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=_Provider(), registry=ToolRegistry(),
                            db=Database(":memory:"))
    client = TestClient(create_app(svc))
    monkeypatch.setattr(launcher, "_WINDOW", None)
    assert client.post("/api/desktop/focus").json()["focused"] is False

    shown = {}

    class _Win:
        def restore(self):
            shown["restore"] = True

        def show(self):
            shown["show"] = True

    monkeypatch.setattr(launcher, "_WINDOW", _Win())
    assert client.post("/api/desktop/focus").json()["focused"] is True
    assert shown.get("show")
