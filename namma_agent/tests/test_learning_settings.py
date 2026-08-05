"""Settings → System → Learning: the knobs behind the tab.

Before this, the Learning tab was read-only — the weekly review could only be
turned on by hand-editing config.yaml, the Learning-Room settings had no UI at
all, and ``apply_config`` rebound ``self.config`` to a fresh dict, leaving every
runner that was handed the original object reading stale values. These tests pin
the fixed behaviour: validated writes, config applied IN PLACE, and runners that
start/stop with the toggle. All offline.
"""
from __future__ import annotations

import copy

import pytest

from namma_agent.core.learning_nudge import LearningNudger
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse
from namma_agent.core.tools import ToolRegistry
from namma_agent.service import NammaAgentService
from namma_agent.tests.test_server import ScriptedProvider


def _merge(base: dict, updates: dict) -> dict:
    for k, v in (updates or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


@pytest.fixture
def svc(monkeypatch, tmp_path):
    """A bare service (no background threads) with config.local.yaml faked out —
    saving settings must never touch the developer's real overlay file."""
    service = NammaAgentService(
        config={"persona": "core", "conversation": {},
                "self_review": {"enabled": False, "dir": str(tmp_path / "sr")},
                "learning": {"notify_progress": True, "nudge_after_days": 3}},
        provider=ScriptedProvider([LLMResponse(content="ok")]),
        registry=ToolRegistry(), db=Database(":memory:"))

    stored: dict = copy.deepcopy(service.config)

    def fake_update_config(updates, path=None):
        _merge(stored, updates or {})
        return copy.deepcopy(stored)          # a NEW dict, like the real loader

    monkeypatch.setattr("namma_agent.config.update_config", fake_update_config)
    service._stored = stored                  # what landed in config.local.yaml
    return service


# ── the payload the tab renders ───────────────────────────────────────────────

def test_learning_settings_payload(svc):
    s = svc.learning_settings()
    assert s["self_review"] == {"enabled": False, "weekday": 6, "at": "18:00",
                                "runner_running": False}
    assert s["learning"]["notify_progress"] is True
    assert s["learning"]["nudge_after_days"] == 3.0
    # a bare service has no comms and no background switch → nudges are inert,
    # and the UI needs to know WHY rather than showing a lying toggle
    assert s["learning"]["comms_ready"] is False
    assert s["learning"]["background_on"] is False
    assert s["learning"]["nudger_running"] is False


def test_payload_survives_garbage_config(svc):
    svc.config["self_review"]["weekday"] = "sunday"
    svc.config["learning"]["nudge_after_days"] = "soon"
    s = svc.learning_settings()
    assert s["self_review"]["weekday"] == 6            # falls back, never crashes
    assert s["learning"]["nudge_after_days"] == 3.0


# ── saving: validated, persisted, applied ─────────────────────────────────────

def test_save_persists_and_applies(svc):
    r = svc.save_learning_settings({"self_review": {"enabled": True, "weekday": 2,
                                                    "at": "07:05"},
                                    "learning": {"nudge_after_days": 5,
                                                 "notify_progress": False}})
    assert r["ok"] is True
    # persisted (config.local.yaml)…
    assert svc._stored["self_review"]["enabled"] is True
    assert svc._stored["self_review"]["at"] == "07:05"
    assert svc._stored["learning"]["nudge_after_days"] == 5
    # …and live in the running config
    assert svc.config["self_review"]["weekday"] == 2
    assert svc.config["learning"]["notify_progress"] is False
    # the response is the fresh payload, so the UI needs no second fetch
    assert r["self_review"]["at"] == "07:05"
    assert r["learning"]["nudge_after_days"] == 5.0


def test_partial_save_leaves_other_keys_alone(svc):
    svc.save_learning_settings({"learning": {"notify_progress": False}})
    assert svc.config["learning"]["nudge_after_days"] == 3      # untouched
    assert svc.config["self_review"]["enabled"] is False


@pytest.mark.parametrize("bad", [
    {"self_review": {"weekday": 9}},
    {"self_review": {"weekday": "sunday"}},
    {"self_review": {"at": "25:00"}},
    {"self_review": {"at": "6pm"}},
    {"learning": {"nudge_after_days": -1}},
    {"learning": {"nudge_after_days": "later"}},
])
def test_bad_values_are_rejected_not_written(svc, bad):
    before = copy.deepcopy(svc._stored)
    r = svc.save_learning_settings(bad)
    assert r["ok"] is False and r["error"]
    assert svc._stored == before        # a half-typed value never reaches the file


# ── the live-apply contract ───────────────────────────────────────────────────

def test_apply_config_updates_in_place(svc):
    """Runners are handed ``service.config`` at boot; rebinding it to a new dict
    would leave them reading boot-time values forever."""
    original = svc.config
    svc.apply_config({**copy.deepcopy(svc.config),
                      "self_review": {"enabled": True, "at": "09:30"}})
    assert svc.config is original                       # same object, new values
    assert original["self_review"]["enabled"] is True
    assert original["self_review"]["at"] == "09:30"


def test_runner_sees_toggle_without_restart(svc):
    """A SelfReviewRunner built at boot picks up the Settings toggle live."""
    from namma_agent.core.self_review import SelfReviewRunner

    runner = SelfReviewRunner(lambda: {}, config=svc.config)
    runner.ensure_started()
    assert not runner.running                           # off in config

    svc.self_review = runner
    svc.save_learning_settings({"self_review": {"enabled": True}})
    assert runner.running                               # started by the save
    svc.save_learning_settings({"self_review": {"enabled": False}})
    assert not runner.running                           # and stopped again


# ── the nudger has to survive being turned off and on ─────────────────────────

def test_nudger_restarts_after_stop(tmp_path):
    nudger = LearningNudger(db=None, send=lambda _: True, after_days=1,
                            interval=3600, state_path=tmp_path / "n.json")
    nudger.start()
    assert nudger.running
    nudger.stop()
    assert not nudger.running
    nudger.start()                                      # used to be a silent no-op
    assert nudger.running
    nudger.stop()


# ── REST surface ──────────────────────────────────────────────────────────────

def test_learning_settings_endpoints(svc):
    from fastapi.testclient import TestClient

    from namma_agent.server.api import create_app

    client = TestClient(create_app(svc))
    got = client.get("/api/learning_settings").json()
    assert got["self_review"]["enabled"] is False

    saved = client.post("/api/learning_settings",
                        json={"settings": {"self_review": {"enabled": True,
                                                           "at": "21:15"}}}).json()
    assert saved["ok"] is True and saved["self_review"]["at"] == "21:15"
    assert client.get("/api/learning_settings").json()["self_review"]["enabled"] is True

    bad = client.post("/api/learning_settings",
                      json={"settings": {"self_review": {"at": "nope"}}}).json()
    assert bad["ok"] is False

    # the Learning-Room topic namespace is untouched (no route shadowing)
    assert client.get("/api/learning").json()["topics"] == []
