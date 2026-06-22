"""Wave 5e/5f — web onboarding endpoint + focus-session tools."""
from __future__ import annotations

import pytest

from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.service import NammaAgentService
from namma_agent.tools import load_tools
from namma_agent.tools import focus as focusmod
from namma_agent.tools import scheduler as sched


class Echo(Provider):
    name = "echo"

    def __init__(self):
        super().__init__(model="echo")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="ok")


# ── onboarding (service + REST) ───────────────────────────────────────────────

@pytest.fixture
def service():
    return NammaAgentService(config={"database": {"path": ":memory:"}}, provider=Echo())


def test_onboarding_needed_when_no_name(service):
    status = service.onboarding_status()
    assert status["needed"] is True and status["name"] is None


def test_complete_onboarding_saves_name_and_facts(service):
    status = service.complete_onboarding("Sri", {"city": "Mumbai"})
    assert status["needed"] is False and status["name"] == "Sri"
    assert service.db.get_fact("city") == "Mumbai"
    assert service.onboarding_status()["needed"] is False


def test_onboarding_rest_endpoints(service):
    from fastapi.testclient import TestClient
    from namma_agent.server.api import create_app

    c = TestClient(create_app(service))
    assert c.get("/api/onboarding").json()["needed"] is True
    r = c.post("/api/onboarding", json={"name": "Ada", "facts": {"role": "engineer"}})
    assert r.json()["name"] == "Ada"
    assert c.get("/api/onboarding").json()["needed"] is False


# ── focus session ─────────────────────────────────────────────────────────────

@pytest.fixture
def reg(monkeypatch, tmp_path):
    monkeypatch.setattr(focusmod, "_path", lambda: tmp_path / "focus.json")
    monkeypatch.setattr(sched, "_store_path", lambda: tmp_path / "reminders.json")
    return load_tools(ToolRegistry())


def test_focus_start_status_end(reg):
    start = reg.execute("start_focus", {"minutes": 30, "label": "writing"})
    assert start.ok and "30 minutes" in start.content
    status = reg.execute("focus_status", {})
    assert "remaining" in status.content and "writing" in status.content
    # starting a session also queued an end reminder with a due_ts
    assert sched._load()[0]["text"].startswith("Focus session over")
    assert reg.execute("end_focus", {}).ok
    assert reg.execute("focus_status", {}).content == "No focus session is running."


def test_focus_rejects_double_start(reg):
    reg.execute("start_focus", {"minutes": 10})
    second = reg.execute("start_focus", {"minutes": 5})
    assert not second.ok and "already running" in second.error


def test_end_without_session(reg):
    assert not reg.execute("end_focus", {}).ok
