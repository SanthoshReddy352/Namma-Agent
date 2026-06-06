"""Wave 5d — reminder due-time parsing + the firing runner."""
from __future__ import annotations

import pytest

from friday.core import reminder_runner as rr
from friday.core.tools import ToolRegistry
from friday.tools import load_tools
from friday.tools import scheduler as sched
from friday.tools.scheduler import parse_when


# ── parse_when ────────────────────────────────────────────────────────────────

def test_parse_relative_minutes():
    assert parse_when("in 10 minutes", now=1000) == 1000 + 600


def test_parse_relative_hours():
    assert parse_when("in 2 hours", now=0) == 7200


def test_parse_iso():
    import datetime
    ts = parse_when("2030-01-01T00:00:00")
    assert ts == int(datetime.datetime(2030, 1, 1).timestamp())


def test_parse_hhmm_next_occurrence():
    # 00:00 is always "today already passed" relative to a mid-day base → tomorrow
    import datetime
    base = datetime.datetime(2026, 6, 6, 12, 0, 0).timestamp()
    ts = parse_when("at 09:30", now=base)
    assert ts > base and (ts - base) <= 24 * 3600


def test_parse_unparseable():
    assert parse_when("sometime soon") is None
    assert parse_when("") is None


# ── due_reminders ─────────────────────────────────────────────────────────────

def test_due_reminders_selects_only_due_unfired():
    items = [
        {"id": 1, "due_ts": 100, "fired": False},
        {"id": 2, "due_ts": 100, "fired": True},   # already fired
        {"id": 3, "due_ts": 999, "fired": False},  # not yet due
        {"id": 4, "due_ts": None, "fired": False},  # no time → never auto-fires
    ]
    due = rr.due_reminders(items, now=500)
    assert [d["id"] for d in due] == [1]


# ── fire_due (integration with the store) ─────────────────────────────────────

@pytest.fixture
def reg(monkeypatch, tmp_path):
    monkeypatch.setattr(sched, "_store_path", lambda: tmp_path / "reminders.json")
    return load_tools(ToolRegistry())


def test_fire_due_fires_and_marks(reg, monkeypatch):
    # add a reminder already due
    reg.execute("add_reminder", {"text": "stretch", "when": "in 1 minute"})
    # force its due_ts into the past by reloading + rewriting
    items = sched._load()
    items[0]["due_ts"] = 1
    sched._save(items)

    fired_msgs = []
    fired = rr.fire_due(now=10_000, on_fire=lambda it: fired_msgs.append(it["text"]))
    assert fired_msgs == ["stretch"]
    assert [f["id"] for f in fired] == [1]
    # marked fired so it won't fire again
    assert sched._load()[0]["fired"] is True
    assert rr.fire_due(now=10_001, on_fire=lambda it: fired_msgs.append(it["text"])) == []


def test_add_reminder_stores_due_ts(reg):
    r = reg.execute("add_reminder", {"text": "call", "when": "in 5 minutes"})
    assert r.ok and r.data["due_ts"] is not None and r.data["fired"] is False
