"""Proactive routines — schedule math, the runner's tick, and the tool surface.
All offline: the store is a tmp file, run_turn/deliver are stubs."""
from __future__ import annotations

from datetime import datetime

import pytest

from namma_agent.core.routines import (
    RoutineRunner,
    due_routines,
    load_routines,
    next_occurrence,
    register_routine_tools,
    save_routines,
)
from namma_agent.core.tools import ToolRegistry


@pytest.fixture
def cfg(tmp_path):
    return {"routines": {"store_path": str(tmp_path / "routines.json")}}


def _runner(cfg, results=("brief text",)):
    calls = {"turns": [], "delivered": []}
    results = list(results)

    def run_turn(prompt, session_id):
        calls["turns"].append((prompt, session_id))
        return (results.pop(0) if results else ""), "sess-1"

    def deliver(name, content):
        calls["delivered"].append((name, content))

    return RoutineRunner(run_turn, deliver, config=cfg), calls


def _ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).timestamp()


# ── schedule math ────────────────────────────────────────────────────────────

def test_interval_schedule():
    t0 = _ts(2026, 7, 16, 10, 0)
    assert next_occurrence({"kind": "interval", "every_minutes": 90}, t0) \
        == t0 + 90 * 60
    assert next_occurrence({"kind": "interval", "every_minutes": 0}, t0) is None


def test_daily_schedule_rolls_to_tomorrow():
    morning = _ts(2026, 7, 16, 7, 0)
    evening = _ts(2026, 7, 16, 9, 30)
    sched = {"kind": "daily", "at": "08:00"}
    assert next_occurrence(sched, morning) == _ts(2026, 7, 16, 8, 0)
    assert next_occurrence(sched, evening) == _ts(2026, 7, 17, 8, 0)


def test_weekly_schedule():
    # 2026-07-16 is a Thursday (weekday 3)
    thu_morning = _ts(2026, 7, 16, 7, 0)
    sched = {"kind": "weekly", "weekday": 3, "at": "08:00"}
    assert next_occurrence(sched, thu_morning) == _ts(2026, 7, 16, 8, 0)
    # after today's slot → next Thursday
    assert next_occurrence(sched, _ts(2026, 7, 16, 9, 0)) == _ts(2026, 7, 23, 8, 0)
    # a Monday routine seen from Thursday → next Monday
    mon = {"kind": "weekly", "weekday": 0, "at": "10:00"}
    assert next_occurrence(mon, thu_morning) == _ts(2026, 7, 20, 10, 0)


def test_malformed_schedules_are_never_due():
    assert next_occurrence({}, 0) is None
    assert next_occurrence({"kind": "daily", "at": "25:99"}, 0) is None
    assert next_occurrence({"kind": "weekly", "weekday": 9, "at": "08:00"}, 0) is None
    assert due_routines([{"enabled": True, "schedule": {}, "created_at": 0}], 1e12) == []


def test_due_routines_anchor_on_last_run():
    sched = {"kind": "interval", "every_minutes": 60}
    created = _ts(2026, 7, 16, 8, 0)
    routine = {"id": 1, "enabled": True, "schedule": sched, "created_at": created,
               "last_run_ts": None}
    assert due_routines([routine], created + 30 * 60) == []          # not yet
    assert due_routines([routine], created + 61 * 60) == [routine]   # due
    routine["last_run_ts"] = created + 61 * 60
    assert due_routines([routine], created + 90 * 60) == []          # re-anchored
    routine["enabled"] = False
    assert due_routines([routine], created + 10 * 3600) == []        # disabled


# ── the runner ───────────────────────────────────────────────────────────────

def test_tick_runs_due_routines_and_persists_last_run(cfg):
    created = _ts(2026, 7, 16, 8, 0)
    save_routines([{"id": 1, "name": "brief", "prompt": "brief me",
                    "schedule": {"kind": "interval", "every_minutes": 30},
                    "enabled": True, "created_at": created,
                    "last_run_ts": None, "session_id": None}], cfg)
    runner, calls = _runner(cfg)
    now = created + 31 * 60
    fired = runner.tick(now)
    assert len(fired) == 1
    assert calls["turns"] == [("brief me", None)]
    assert calls["delivered"] == [("brief", "brief text")]
    stored = load_routines(cfg)[0]
    assert stored["last_run_ts"] == now
    assert stored["session_id"] == "sess-1"       # runs build on one session
    # immediately after, nothing is due
    assert runner.tick(now + 60) == []


def test_runner_survives_turn_failure(cfg):
    save_routines([{"id": 1, "name": "boomer", "prompt": "x",
                    "schedule": {"kind": "interval", "every_minutes": 1},
                    "enabled": True, "created_at": 0, "last_run_ts": None}], cfg)

    def bad_turn(prompt, session_id):
        raise RuntimeError("model down")

    delivered = []
    runner = RoutineRunner(bad_turn, lambda n, c: delivered.append(n), config=cfg)
    fired = runner.tick(1e12)
    assert len(fired) == 1 and delivered == []    # no delivery of nothing


def test_ensure_started_is_lazy(cfg):
    runner, _ = _runner(cfg)
    runner.ensure_started()
    assert not runner.running                      # no routines → no thread
    save_routines([{"id": 1, "name": "n", "prompt": "p",
                    "schedule": {"kind": "daily", "at": "08:00"},
                    "enabled": True, "created_at": 0}], cfg)
    runner.ensure_started()
    assert runner.running
    runner.stop()


# ── tools ────────────────────────────────────────────────────────────────────

def test_routine_tools_roundtrip(cfg):
    runner, calls = _runner(cfg, results=["ran!"])
    reg = ToolRegistry()
    register_routine_tools(reg, runner, config=cfg)
    runner.stop()  # keep the test synchronous

    r = reg.execute("create_routine", {
        "name": "Morning brief", "prompt": "summarize my day",
        "schedule": {"kind": "daily", "at": "08:00"}})
    assert r.ok and r.data["id"] == 1
    assert reg.get("create_routine").destructive is True

    assert "Morning brief" in reg.execute("list_routines", {}).content
    assert reg.execute("run_routine_now", {"id": 1}).content == "ran!"
    assert calls["delivered"] == [("Morning brief", "ran!")]

    assert reg.execute("toggle_routine", {"id": 1, "enabled": False}).ok
    assert load_routines(cfg)[0]["enabled"] is False

    assert reg.execute("delete_routine", {"id": 1}).ok
    assert load_routines(cfg) == []
    runner.stop()


def test_create_routine_rejects_bad_schedule(cfg):
    runner, _ = _runner(cfg)
    reg = ToolRegistry()
    register_routine_tools(reg, runner, config=cfg)
    r = reg.execute("create_routine", {"name": "x", "prompt": "y",
                                       "schedule": {"kind": "sometimes"}})
    assert not r.ok and "schedule" in r.error
    assert load_routines(cfg) == []
