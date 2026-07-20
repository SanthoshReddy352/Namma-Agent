"""Phase 3 tests — the weekly self-review: mining heuristics, the offline
memory eval, snapshot persistence + trends, proposal draft/accept/reject
round-trips, schedule math, and the REST surface. All offline."""
from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

from namma_agent.core import self_review as sr
from namma_agent.core.memory import Database
from namma_agent.core.routines import load_routines
from namma_agent.core.watchers import load_watchers


@pytest.fixture
def cfg(tmp_path):
    return {
        "self_review": {"dir": str(tmp_path / "sr")},
        "routines": {"store_path": str(tmp_path / "routines.json")},
        "watchers": {"store_path": str(tmp_path / "watchers.json")},
    }


# ── mining heuristics ─────────────────────────────────────────────────────────

def _seeded_db() -> Database:
    db = Database(":memory:")
    s1 = db.create_session()
    db.add_turn(s1, "user", "convert this video for me")
    db.add_turn(s1, "assistant", "Done.", tools_used=["web_search", "web_extract"])
    db.add_turn(s1, "user", "no, that's wrong — I wanted audio only")
    db.add_turn(s1, "assistant", "Fixed.", tools_used=["web_search", "web_extract"])
    s2 = db.create_session()
    db.add_turn(s2, "user", "please summarize the quarterly report numbers")
    db.add_turn(s2, "assistant", "Here.", tools_used=["web_search", "web_extract"])
    db.add_turn(s2, "user", "summarize the quarterly report numbers please")  # retry
    db.add_turn(s2, "assistant", "Again, here.")
    db.add_turn(s2, "user", "and what about next quarter?")  # left hanging
    db.log_audit(s1, "run_shell", {"cmd": "x"}, "exit 1: boom", success=False)
    db.log_audit(s1, "run_shell", {"cmd": "y"}, "ok", success=True)
    db.log_audit(s2, "web_extract", {}, "timeout", success=False)
    return db


def test_mine_week_heuristics():
    mined = sr.mine_week(_seeded_db(), time.time())
    assert mined["sessions"] == 2
    assert mined["failures"]["count"] == 2
    assert mined["failures"]["by_tool"] == {"run_shell": 1, "web_extract": 1}
    assert mined["tool_calls"] == 3
    assert 0 < mined["failure_rate"] < 1
    assert len(mined["corrections"]) == 1
    assert "wrong" in mined["corrections"][0]["text"]
    assert len(mined["retries"]) == 1
    assert len(mined["unanswered"]) == 1
    assert "next quarter" in mined["unanswered"][0]["text"]
    # web_search→web_extract ran 3× across sessions → a repeated workflow
    assert mined["repeated_workflows"][0]["tools"] == ["web_search", "web_extract"]
    assert mined["repeated_workflows"][0]["count"] == 3


def test_mine_week_ignores_old_turns():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "old question")
    # a "now" far in the future puts everything outside the 7-day window
    mined = sr.mine_week(db, time.time() + 30 * 86400)
    assert mined["sessions"] == 0 and mined["tool_calls"] == 0


# ── offline memory eval + snapshots ───────────────────────────────────────────

def test_mock_memory_eval_runs_offline():
    report = sr.run_mock_memory_eval(k=5)
    assert report and 0.0 <= report["recall_at_k"] <= 1.0
    assert report["k"] == 5 and report["total"] > 0


def test_snapshot_build_save_load_trend(cfg):
    mined = {"tool_calls": 10, "failures": {"count": 2}, "failure_rate": 0.2}
    snap = sr.build_snapshot(mined, {"recall_at_k": 0.8, "k": 5},
                             {"items": 42, "entities": 7, "relations": 3},
                             skills_count=4,
                             usage={"total": {"tokens": 1000, "cached": 400}},
                             now_ts=time.time())
    assert snap["facts"] == 42 and snap["skills"] == 4 and snap["tokens_7d"] == 1000
    sr.save_snapshot(snap, cfg)
    sr.save_snapshot(snap, cfg)                      # same day → overwrite, not dup
    assert len(sr.load_snapshots(cfg)) == 1

    older = dict(snap, date="2026-07-01", recall_at_k=0.6, facts=30)
    sr.save_snapshot(older, cfg)
    snaps = sr.load_snapshots(cfg)
    assert [s["date"] for s in snaps] == sorted(s["date"] for s in snaps)
    assert snaps[-1]["recall_at_k"] == 0.8           # newest last (the trend line)


# ── proposals ─────────────────────────────────────────────────────────────────

def _skill_prop(title="Video convert procedure"):
    return {"kind": "skill", "title": title, "why": "workflow repeated",
            "payload": {"name": "convert-video", "description": "convert media",
                        "body": "1. ffmpeg…"}}


def test_validate_proposal():
    assert sr.validate_proposal(_skill_prop()) == ""
    assert "payload" in sr.validate_proposal(
        {"kind": "skill", "title": "x", "payload": {"name": "y"}})
    assert sr.validate_proposal(
        {"kind": "routine", "title": "r",
         "payload": {"name": "n", "prompt": "p",
                     "schedule": {"kind": "daily", "at": "08:00"}}}) == ""
    assert "schedule" in sr.validate_proposal(
        {"kind": "routine", "title": "r",
         "payload": {"name": "n", "prompt": "p", "schedule": {"kind": "x"}}})
    assert sr.validate_proposal(
        {"kind": "watcher", "title": "w",
         "payload": {"name": "n", "intent": "i",
                     "trigger": {"type": "web", "url": "https://x"}}}) == ""
    assert sr.validate_proposal({"kind": "note", "title": "t", "payload": {}}) == ""
    assert "unknown" in sr.validate_proposal({"kind": "magic", "title": "t"})


def test_draft_proposals_parses_and_validates():
    good = _skill_prop()
    bad = {"kind": "skill", "title": "broken", "payload": {}}
    raw = "Sure! Here are my proposals:\n" + json.dumps([good, bad]) + "\nDone."
    drafts = sr.draft_proposals(lambda msgs: raw, {"failures": {}})
    assert len(drafts) == 1 and drafts[0]["title"] == good["title"]
    assert sr.draft_proposals(lambda msgs: "no json here", {}) == []
    assert sr.draft_proposals(lambda msgs: (_ for _ in ()).throw(RuntimeError()),
                              {}) == []


def test_add_proposals_dedupes_even_rejected(cfg):
    added = sr.add_proposals([_skill_prop()], cfg)
    assert len(added) == 1 and added[0]["status"] == "pending"
    ok, _ = sr.set_proposal_status(added[0]["id"], "rejected", cfg)
    assert ok
    # the same idea drafted next week must NOT come back
    assert sr.add_proposals([_skill_prop()], cfg) == []
    assert len(sr.load_proposals(cfg)) == 1


class _FakeSkills:
    def __init__(self):
        self.created = []

    def create(self, name, description, body, category=""):
        self.created.append(name)
        return type("S", (), {"name": name})()


def test_accept_skill_proposal_applies(cfg):
    added = sr.add_proposals([_skill_prop()], cfg)
    skills = _FakeSkills()
    ok, detail = sr.set_proposal_status(added[0]["id"], "accepted", cfg,
                                        skills_store=skills)
    assert ok and "convert-video" in detail and skills.created == ["convert-video"]
    assert sr.load_proposals(cfg)[0]["status"] == "accepted"
    # already resolved → second resolve refuses
    ok, detail = sr.set_proposal_status(added[0]["id"], "rejected", cfg)
    assert not ok and "already" in detail


def test_accept_routine_and_watcher_arrive_disabled(cfg):
    added = sr.add_proposals([
        {"kind": "routine", "title": "Morning check", "why": "",
         "payload": {"name": "Morning check", "prompt": "check things",
                     "schedule": {"kind": "daily", "at": "08:00"}}},
        {"kind": "watcher", "title": "Inbox watch", "why": "",
         "payload": {"name": "Inbox watch", "intent": "boss mail",
                     "trigger": {"type": "email", "query": "from:boss"}}},
    ], cfg)
    for p in added:
        ok, detail = sr.set_proposal_status(p["id"], "accepted", cfg)
        assert ok and "disabled" in detail
    assert load_routines(cfg)[0]["enabled"] is False
    assert load_watchers(cfg)[0]["enabled"] is False


def test_accept_skill_without_store_fails_cleanly(cfg):
    added = sr.add_proposals([_skill_prop("Another skill")], cfg)
    ok, detail = sr.set_proposal_status(added[0]["id"], "accepted", cfg,
                                        skills_store=None)
    assert not ok and "store" in detail
    assert sr.load_proposals(cfg)[0]["status"] == "pending"   # still decidable


# ── report ────────────────────────────────────────────────────────────────────

def test_format_report_shows_trends_and_proposals():
    mined = {"window_days": 7, "sessions": 3, "tool_calls": 10,
             "failures": {"count": 2, "by_tool": {"run_shell": 2}},
             "failure_rate": 0.2, "corrections": [{}], "retries": [],
             "repeated_workflows": [{"tools": ["a", "b"], "count": 3}],
             "unanswered": [{}]}
    snaps = [{"recall_at_k": 0.6, "facts": 30, "skills": 2, "k": 5,
              "failure_rate": 0.3, "tokens_7d": 100, "cached_7d": 10},
             {"recall_at_k": 0.8, "facts": 42, "skills": 4, "k": 5,
              "failure_rate": 0.2, "tokens_7d": 200, "cached_7d": 50}]
    text = sr.format_report(mined, snaps, [{"kind": "skill", "title": "Do X"}])
    assert "80% (was 60%)" in text
    assert "42 (was 30)" in text
    assert "run_shell ×2" in text
    assert "a → b (×3)" in text
    assert "Do X" in text
    # empty history still renders
    assert "n/a" in sr.format_report(mined, [], [])


# ── schedule math + runner ────────────────────────────────────────────────────

def _ts(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi).timestamp()


def test_review_due_weekly_anchoring():
    cfg = {"self_review": {"weekday": 6, "at": "18:00"}}    # Sunday 18:00
    sun_1759 = _ts(2026, 7, 19, 17, 59)                      # 2026-07-19 is a Sunday
    sun_1801 = _ts(2026, 7, 19, 18, 1)
    # ran last Sunday → due only once this Sunday's slot passes
    last = _ts(2026, 7, 12, 18, 0)
    assert not sr.review_due(cfg, sun_1759, last)
    assert sr.review_due(cfg, sun_1801, last)
    # never run: enabling right after the slot → due; mid-week → waits
    assert sr.review_due(cfg, sun_1801, None)
    assert not sr.review_due(cfg, _ts(2026, 7, 22, 12, 0), None)


def test_runner_tick_runs_and_reanchors(cfg, tmp_path):
    cfg["self_review"].update({"weekday": 6, "at": "18:00", "enabled": True})
    runs = []

    def fake_review():
        # a real review saves a snapshot — mimic that so the anchor advances
        snap = {"date": "2026-07-19", "ts": _ts(2026, 7, 19, 18, 1)}
        sr.save_snapshot(snap, cfg)
        runs.append(1)
        return {}

    runner = sr.SelfReviewRunner(fake_review, config=cfg)
    assert runner.tick(_ts(2026, 7, 19, 18, 1)) is True
    assert runner.tick(_ts(2026, 7, 20, 9, 0)) is False       # re-anchored
    assert runner.tick(_ts(2026, 7, 26, 18, 1)) is True       # next Sunday
    assert len(runs) == 2


def test_runner_only_starts_when_enabled(cfg):
    runner = sr.SelfReviewRunner(lambda: {}, config=cfg)
    runner.ensure_started()
    assert not runner.running                                 # off by default
    cfg["self_review"]["enabled"] = True
    runner.ensure_started()
    assert runner.running
    runner.stop()


# ── REST surface ──────────────────────────────────────────────────────────────

def test_self_review_endpoints(tmp_path):
    from fastapi.testclient import TestClient

    from namma_agent.core.providers.base import LLMResponse
    from namma_agent.core.tools import ToolRegistry
    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService
    from namma_agent.tests.test_server import ScriptedProvider

    cfg = {"persona": "core", "conversation": {},
           "self_review": {"dir": str(tmp_path / "sr")},
           "routines": {"store_path": str(tmp_path / "routines.json")},
           "watchers": {"store_path": str(tmp_path / "watchers.json")}}
    svc = NammaAgentService(
        config=cfg,
        provider=ScriptedProvider([LLMResponse(content="[]")]),  # drafts: none
        registry=ToolRegistry(), db=Database(":memory:"))
    client = TestClient(create_app(svc))

    # before any run: empty but well-shaped
    ov = client.get("/api/self_review").json()
    assert ov["enabled"] is False and ov["report"] is None
    assert ov["snapshots"] == [] and ov["proposals"] == []

    # manual run works without the runner (and without comms)
    r = client.post("/api/self_review/run").json()
    assert r["ok"] and "What I learned this week" in r["report"]["text"]
    ov = client.get("/api/self_review").json()
    assert len(ov["snapshots"]) == 1
    assert ov["snapshots"][0]["recall_at_k"] is not None      # eval really ran

    # proposal resolution surface (seed one directly)
    added = sr.add_proposals([{"kind": "note", "title": "Try shorter prompts",
                               "why": "", "payload": {}}], cfg)
    ok = client.post(f"/api/self_review/proposals/{added[0]['id']}/reject").json()
    assert ok["ok"]
    assert client.post("/api/self_review/proposals/999/accept").json()["ok"] is False
    assert client.post(f"/api/self_review/proposals/{added[0]['id']}/nuke"
                       ).json()["ok"] is False

    # status carries the self_review block
    st = client.get("/api/status").json()
    assert st["self_review"]["enabled"] is False
    assert st["self_review"]["last_snapshot"] is not None
