"""Phase 3 — the consolidator: sleep-time self-improvement (design §8/§12).

Offline: scripted providers (payloads pop in LLM-call order), in-memory SQLite,
stubbed environment probes. Covers decay/archive, event horizon, triple merge,
promote, reflect (with dedup), core compaction, the persisted report card,
scheduler trigger logic (pure — no threads), and the time-travel graph query.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from namma_agent.core.engram import Engram
from namma_agent.core.engram.consolidate import ConsolidationScheduler, Consolidator
from namma_agent.core.engram.core_memory import BLOCK_BUDGET_CHARS, CoreMemory
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.engram.writer import EngramWriter
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.service import NammaAgentService


class ScriptedProvider(Provider):
    """Returns queued JSON payloads, one per LLM call, in order."""

    name = "scripted"

    def __init__(self, payloads=()):
        super().__init__(model="scripted")
        self._payloads = list(payloads)
        self.calls = 0

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.calls += 1
        payload = self._payloads.pop(0) if self._payloads else []
        return LLMResponse(content=json.dumps(payload))


class _StubEnv:
    def __init__(self):
        self.refreshes = 0

    def get(self, refresh=False):
        if refresh:
            self.refreshes += 1
        return {}


def _consolidator(payloads=(), summaries=None, **knobs):
    db = Database(":memory:")
    store = EngramStore(db)
    core = CoreMemory(store)
    provider = ScriptedProvider(payloads)
    writer = EngramWriter(store, core, provider_getter=lambda: provider)
    env = _StubEnv()
    cons = Consolidator(store, core, writer, env,
                        recent_summaries_fn=(lambda n: list(summaries or [])),
                        **knobs)
    return cons, store, core, provider, env


def _backdate(store, item_id, days):
    then = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    store.conn.execute("UPDATE memory_items SET last_seen=?, created_at=? WHERE id=?",
                       (then, then, item_id))
    store.conn.commit()


# ── decay & event horizon ─────────────────────────────────────────────────────

def test_decay_archives_stale_low_importance():
    cons, store, *_ = _consolidator()
    old = store.add_item("mentioned some cafe once", importance=0.3)
    _backdate(store, old, days=120)
    fresh = store.add_item("another minor fact", importance=0.3)

    assert cons._step_decay() == 1
    live_ids = {i["id"] for i in store.list_items()}
    assert old not in live_ids and fresh in live_ids
    # out of recall…
    assert all(h["id"] != old for h in store.search_items("cafe"))
    # …but still browsable, flagged archived (not superseded)
    everything = {i["id"]: i for i in store.list_items(include_expired=True)}
    assert everything[old]["archived_at"] and not everything[old]["expired_at"]


def test_decay_spares_important_preferences_and_reinforced():
    cons, store, *_ = _consolidator()
    ids = [
        store.add_item("identity-grade fact", importance=0.9),
        store.add_item("a standing preference", kind="preference", importance=0.3),
    ]
    reinforced = store.add_item("reinforced fact", importance=0.3)
    for _ in range(4):
        store.reinforce(reinforced)
    ids.append(reinforced)
    for iid in ids:
        _backdate(store, iid, days=365)
    # reinforce() bumps last_seen — re-backdate after the bumps
    _backdate(store, reinforced, days=365)

    assert cons._step_decay() == 0
    assert {i["id"] for i in store.list_items()} == set(ids)


def test_event_horizon_expires_old_events():
    cons, store, *_ = _consolidator(event_horizon_days=90)
    exam = store.add_item("user has an exam on Friday", kind="event")
    _backdate(store, exam, days=100)
    keep = store.add_item("user got a new laptop", kind="event")

    assert cons._step_event_horizon() == 1
    live = {i["id"] for i in store.list_items()}
    assert exam not in live and keep in live
    gone = next(i for i in store.list_items(include_expired=True) if i["id"] == exam)
    assert gone["expired_at"]                      # bi-temporal: history kept


def test_merge_triple_duplicates_folds_rephrasings():
    cons, store, *_ = _consolidator()
    store.add_item("Santhosh studies at KARE", subject="Santhosh",
                   predicate="studies_at", object="KARE")
    store.add_item("The user is a student of KARE", subject="santhosh",
                   predicate="Studies At", object="kare")
    assert cons._step_merge() == 1
    live = store.list_items()
    assert len(live) == 1 and live[0]["frequency"] == 2


# ── promote & reflect (model steps) ───────────────────────────────────────────

def test_promote_runs_candidates_through_pipeline():
    cand = {"text": "The user started a new job at ACME", "kind": "fact",
            "subject": "user", "predicate": "works_at", "object": "ACME",
            "importance": 0.7}
    cons, store, *_ = _consolidator(
        payloads=[[cand]],
        summaries=["Talked about the user's first week at their new job, ACME."])
    assert cons._step_promote() == 1
    items = store.list_items()
    assert len(items) == 1 and items[0]["source"] == "consolidator:promote"
    assert store.graph()["edges"], "the promoted triple grew the graph"


def test_promote_without_summaries_costs_no_model_call():
    cons, _, _, provider, _ = _consolidator(payloads=[["never popped"]])
    assert cons._step_promote() == 0
    assert provider.calls == 0


def test_reflect_writes_deduped_insights():
    cons, store, _, provider, _ = _consolidator(
        payloads=[["Santhosh prefers step-by-step explanations"],
                  ["Santhosh prefers step-by-step explanations"]])
    for i in range(4):
        store.add_item(f"observed fact number {i}")
    assert cons._step_reflect() == 1
    insights = store.list_items(kind="insight")
    assert len(insights) == 1 and insights[0]["source"] == "consolidator:reflect"
    # a second pass proposing the same insight writes nothing
    assert cons._step_reflect() == 0


def test_reflect_needs_enough_material():
    cons, store, _, provider, _ = _consolidator(payloads=[["too eager"]])
    store.add_item("only one fact")
    assert cons._step_reflect() == 0 and provider.calls == 0


# ── core compaction ───────────────────────────────────────────────────────────

def test_compact_core_over_budget():
    dense = ["User: name Santhosh; B.Tech CSE (AI&ML) at KARE; prefers Python."]
    cons, store, core, *_ = _consolidator(payloads=[dense])
    chunk = "the user mentioned a detail worth keeping around number "
    for i in range(5):
        assert core.add("user", (chunk + str(i)) * 6)["ok"]
    assert core.usage("user")["pct"] > 80
    assert cons._step_compact_core() == 1
    entries = store.core_entries("user")
    assert [e["text"] for e in entries] == dense
    assert core.usage("user")["pct"] < 80


def test_compact_skips_when_result_not_denser():
    # Model echoes as many entries back → not denser → block left untouched.
    cons, store, core, *_ = _consolidator(
        payloads=[["a" * 300, "b" * 300, "c" * 300, "d" * 300, "e" * 300]])
    chunk = "another remembered working detail about the user number "
    for i in range(5):
        core.add("user", (chunk + str(i)) * 6)
    before = [e["text"] for e in store.core_entries("user")]
    assert cons._step_compact_core() == 0
    assert [e["text"] for e in store.core_entries("user")] == before


# ── the full run: report card persists ────────────────────────────────────────

def test_run_records_persistent_report():
    cons, store, *_ = _consolidator()
    store.add_item("dup fact")
    store.add_item("dup  fact")
    out = cons.run(reason="idle")
    assert out["ok"] and out["merged"] == 1
    latest = store.latest_consolidation()
    assert latest["reason"] == "idle" and latest["merged"] == 1


def test_run_survives_step_failure():
    cons, store, *_ = _consolidator()
    cons.environment = None            # _step_environment will raise
    out = cons.run()
    assert out["ok"] and out["environment_refreshed"] == 0
    assert store.latest_consolidation() is not None


# ── scheduler trigger logic (pure, no threads) ────────────────────────────────

def _sched(idle_minutes=20, daily_at=""):
    cons, *_ = _consolidator()
    return ConsolidationScheduler(cons, idle_minutes=idle_minutes, daily_at=daily_at)


def test_idle_trigger_needs_idle_and_gap():
    s = _sched(idle_minutes=20)
    now = time.time()
    s._last_activity = now - 21 * 60
    s._last_run = now - 7 * 3600
    assert s.due(now=now) == "idle"
    s.note_activity()                                  # a turn resets the clock
    assert s.due(now=time.time()) is None
    s._last_activity = now - 21 * 60
    s._last_run = now - 3600                           # ran recently → paced out
    assert s.due(now=now) is None


def test_daily_trigger_fires_once_per_day():
    s = _sched(idle_minutes=0, daily_at="03:30")
    s._last_daily_date = None
    at_4am = datetime(2026, 7, 16, 4, 0)
    assert s.due(now=time.time(), local_now=at_4am) == "daily"
    s.mark_fired("daily", local_now=at_4am)
    assert s.due(now=time.time(), local_now=at_4am) is None
    next_day = datetime(2026, 7, 17, 3, 45)
    assert s.due(now=time.time(), local_now=next_day) == "daily"


def test_daily_not_fired_late_on_boot():
    """Booting after today's daily time must not trigger a catch-up run."""
    late = datetime.now().replace(hour=0, minute=0)
    s = ConsolidationScheduler(_consolidator()[0], idle_minutes=0, daily_at="00:00")
    assert s.due(now=time.time(), local_now=datetime.now()) is None


# ── time travel: as_of graph ──────────────────────────────────────────────────

def test_graph_as_of_time_travels():
    _, store, *_ = _consolidator()
    iid = store.add_item("user works at ACME", subject="user",
                         predicate="works_at", object="ACME")
    store.add_relation("user", "works_at", "ACME", item_id=iid)
    created = datetime.now(timezone.utc)

    store.invalidate(iid)                              # superseded now
    assert store.graph()["edges"] == []                # live view: gone

    during = (created + timedelta(seconds=0)).isoformat()
    assert len(store.graph(as_of=during)["edges"]) == 1     # knew it then
    before = (created - timedelta(days=1)).isoformat()
    g = store.graph(as_of=before)
    assert g["edges"] == [] and g["nodes"] == []             # didn't know it yet


# ── service wiring ────────────────────────────────────────────────────────────

class Echo(Provider):
    name = "echo"

    def __init__(self):
        super().__init__(model="echo")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="[]")


@pytest.fixture
def svc():
    return NammaAgentService(config={"database": {"path": ":memory:"}},
                             provider=Echo(), registry=ToolRegistry())


def test_service_manual_consolidate_and_status(svc):
    svc.engram.store.add_item("dup fact")
    svc.engram.store.add_item("dup fact")
    out = svc.memory_consolidate()
    assert out["ok"] and out["reason"] == "manual" and out["merged"] == 1
    assert "Improved memory" in out["content"]
    last = svc.memory_status()["last_consolidation"]
    assert last["reason"] == "manual" and last["merged"] == 1


def test_service_scheduler_not_started_in_tests(svc):
    assert svc.engram.scheduler._thread is None


def test_service_consolidate_settings_roundtrip(svc, monkeypatch, tmp_path):
    import namma_agent.config as cfg
    monkeypatch.setattr(cfg, "_config_path", lambda: tmp_path / "config.yaml")
    s = svc.memory_settings()
    assert s["consolidate_background"] is True and s["daily_at"] == "03:30"
    out = svc.save_memory_settings({"consolidate_background": False,
                                    "idle_minutes": 45, "daily_at": "02:15"})
    assert out["consolidate_background"] is False
    assert svc.engram.scheduler.idle_minutes == 45.0
    assert svc.engram.scheduler.daily_at == "02:15"
    local = (tmp_path / "config.local.yaml").read_text(encoding="utf-8")
    assert "background: false" in local and "daily_at: 02:15" in local
    # malformed time is ignored, valid state untouched
    svc.save_memory_settings({"daily_at": "25:99"})
    assert svc.engram.scheduler.daily_at == "02:15"


def test_service_turn_resets_idle_clock(svc):
    svc.engram.scheduler._last_activity = time.time() - 9999
    try:
        svc.run_turn("hello there, quick check")
    except Exception:  # noqa: BLE001 — the Echo provider turn itself may be bare
        pass
    assert time.time() - svc.engram.scheduler._last_activity < 60


def test_engram_facade_consolidate_records(svc):
    out = svc.engram.consolidate(reason="daily")
    assert out["ok"]
    assert svc.engram.status()["last_consolidation"]["reason"] == "daily"
