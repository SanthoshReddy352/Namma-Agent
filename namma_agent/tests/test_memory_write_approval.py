"""Phase 7c — approval-gated memory writes (memory.write_approval).

The contract under test:
  * OFF (default) → today's behaviour, byte for byte.
  * ON  → facts the agent EXTRACTED land 'pending': not FTS-indexed, not
          embedded, never recalled, and a supersede is PARKED (rejecting must
          never change memory that already existed).
  * Explicit "remember this" is never gated — that was already the user's call.
"""
from __future__ import annotations

import pytest

from namma_agent.core.engram import Engram
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.memory import Database


@pytest.fixture
def store():
    return EngramStore(Database(":memory:"))


def _add_pending(store, text, supersedes=None, **kw):
    return store.add_item(text, screen_status="pending",
                          pending_supersedes=supersedes, **kw)


# ── the held-out state ───────────────────────────────────────────────────────

def test_pending_facts_are_not_recallable(store):
    """The whole point: a fact awaiting approval is not memory yet."""
    _add_pending(store, "the user dislikes cilantro")
    assert store.search_items("cilantro") == []


def test_pending_facts_are_not_in_the_facts_browser(store):
    store.add_item("the user lives in Bengaluru")
    _add_pending(store, "the user dislikes cilantro")
    texts = [i["text"] for i in store.list_items()]
    assert "the user lives in Bengaluru" in texts
    assert "the user dislikes cilantro" not in texts


def test_pending_is_a_separate_queue_from_the_security_quarantine(store):
    """'pending' means "I inferred this, is it right?"; 'untrusted'/'flagged'
    mean "someone may be attacking you". Mixing them would be misleading."""
    _add_pending(store, "inferred fact")
    store.add_item("from a stranger", screen_status="untrusted")
    store.add_item("injection attempt", screen_status="flagged")

    quarantined = [i["text"] for i in store.quarantined_items()]
    assert "from a stranger" in quarantined and "injection attempt" in quarantined
    assert "inferred fact" not in quarantined

    pending = [i["text"] for i in store.pending_items()]
    assert pending == ["inferred fact"]


def test_pending_count(store):
    assert store.pending_count() == 0
    _add_pending(store, "one")
    _add_pending(store, "two")
    assert store.pending_count() == 2


# ── approve ──────────────────────────────────────────────────────────────────

def test_approving_makes_a_fact_recallable(store):
    item_id = _add_pending(store, "the user dislikes cilantro")
    assert store.approve_item(item_id) is True

    assert [i["text"] for i in store.search_items("cilantro")] == \
        ["the user dislikes cilantro"]
    assert store.pending_count() == 0
    assert any(i["id"] == item_id for i in store.list_items())


def test_approving_applies_a_parked_supersede(store):
    old = store.add_item("the user lives in Chennai")
    new = _add_pending(store, "the user lives in Bengaluru", supersedes=old)

    # Until approval the ORIGINAL fact is untouched and still recallable.
    assert store.get_item(old)["expired_at"] is None
    assert store.search_items("Chennai")

    store.approve_item(new)

    assert store.get_item(old)["expired_at"] is not None
    assert store.get_item(old)["superseded_by"] == new
    assert [i["text"] for i in store.search_items("Bengaluru")] == \
        ["the user lives in Bengaluru"]


def test_approving_something_that_is_not_pending_is_refused(store):
    live = store.add_item("already real")
    assert store.approve_item(live) is False
    assert store.approve_item("no-such-id") is False


# ── reject ───────────────────────────────────────────────────────────────────

def test_rejecting_discards_the_fact(store):
    item_id = _add_pending(store, "the user dislikes cilantro")
    assert store.reject_item(item_id) is True
    assert store.get_item(item_id) is None
    assert store.search_items("cilantro") == []


def test_rejecting_a_supersede_leaves_the_original_alone(store):
    """The failure mode this guards: a wrong "correction" quietly expiring a
    fact that was right."""
    old = store.add_item("the user lives in Chennai")
    new = _add_pending(store, "the user lives in Bengaluru", supersedes=old)

    store.reject_item(new)

    original = store.get_item(old)
    assert original["expired_at"] is None and original["superseded_by"] is None
    assert store.search_items("Chennai")


def test_rejecting_something_that_is_not_pending_is_refused(store):
    live = store.add_item("already real")
    assert store.reject_item(live) is False
    assert store.get_item(live) is not None


# ── bulk ─────────────────────────────────────────────────────────────────────

def test_resolve_all_approve(store):
    for text in ("a fact", "b fact", "c fact"):
        _add_pending(store, text)
    assert store.resolve_all_pending(approve=True) == 3
    assert store.pending_count() == 0
    assert len(store.list_items()) == 3


def test_resolve_all_reject(store):
    for text in ("a fact", "b fact"):
        _add_pending(store, text)
    assert store.resolve_all_pending(approve=False) == 2
    assert store.pending_count() == 0
    assert store.list_items() == []


# ── what the queue shows ─────────────────────────────────────────────────────

def test_pending_items_show_what_would_be_replaced(store):
    old = store.add_item("the user lives in Chennai")
    _add_pending(store, "the user lives in Bengaluru", supersedes=old)
    item = store.pending_items()[0]
    assert item["replaces"] == "the user lives in Chennai"
    assert item["replaces_id"] == old


def test_pending_items_newest_first(store):
    first = _add_pending(store, "older fact")
    second = _add_pending(store, "newer fact")
    ids = [i["id"] for i in store.pending_items()]
    assert set(ids) == {first, second}


# ── the writer end of the pipe ───────────────────────────────────────────────

def _engram(tmp_path, **memory_cfg):
    db = Database(":memory:")
    return Engram(db, config={"memory": memory_cfg,
                              "database": {"path": ":memory:"}},
                  provider_getter=lambda: None)


def test_writer_defaults_to_no_approval(tmp_path):
    engram = _engram(tmp_path)
    assert engram.writer.write_approval is False


def test_writer_reads_the_config_flag(tmp_path):
    engram = _engram(tmp_path, write_approval=True)
    assert engram.writer.write_approval is True


def test_auto_extracted_fact_lands_pending_when_approval_is_on(tmp_path):
    engram = _engram(tmp_path, write_approval=True)
    writer = engram.writer
    result = writer._apply({"text": "the user dislikes cilantro"},
                           "the user dislikes cilantro",
                           {"op": "ADD"}, [], "chat", pending=True)
    assert result["op"] == "PENDING"
    assert engram.store.pending_count() == 1
    assert engram.store.search_items("cilantro") == []


def test_apply_without_pending_writes_straight_through(tmp_path):
    engram = _engram(tmp_path, write_approval=True)
    result = engram.writer._apply({"text": "the user likes filter coffee"},
                                  "the user likes filter coffee",
                                  {"op": "ADD"}, [], "chat", pending=False)
    assert result["op"] == "ADD"
    assert engram.store.pending_count() == 0
    assert engram.store.search_items("coffee")


def test_pending_update_parks_the_supersede(tmp_path):
    engram = _engram(tmp_path, write_approval=True)
    old_id = engram.store.add_item("the user lives in Chennai")
    neighbour = engram.store.get_item(old_id)

    engram.writer._apply({"text": "the user lives in Bengaluru"},
                         "the user lives in Bengaluru",
                         {"op": "UPDATE", "target": 1}, [neighbour], "chat",
                         pending=True)

    assert engram.store.get_item(old_id)["expired_at"] is None
    assert engram.store.pending_items()[0]["replaces_id"] == old_id


def test_explicit_remember_is_never_gated(tmp_path, monkeypatch):
    """Approval gates what the agent INFERRED, not what it was told to save."""
    engram = _engram(tmp_path, write_approval=True)
    captured = {}

    def fake_apply(cand, ctext, decision, neighbours, source, pending=False):
        captured["pending"] = pending
        return {"op": "ADD", "text": ctext}

    monkeypatch.setattr(engram.writer, "_apply", fake_apply)
    monkeypatch.setattr(engram.writer, "_resolve",
                        lambda *a, **k: {"op": "ADD"})

    engram.writer.apply_candidate({"text": "remember my passport number is X"},
                                  source="manual", explicit=True)
    assert captured["pending"] is False

    engram.writer.apply_candidate({"text": "the user seems to like jazz"},
                                  source="chat", explicit=False)
    assert captured["pending"] is True


def test_flag_off_means_nothing_is_held(tmp_path, monkeypatch):
    engram = _engram(tmp_path, write_approval=False)
    captured = {}
    monkeypatch.setattr(engram.writer, "_resolve", lambda *a, **k: {"op": "ADD"})
    monkeypatch.setattr(engram.writer, "_apply",
                        lambda c, t, d, n, s, pending=False: captured.update(pending=pending))
    engram.writer.apply_candidate({"text": "the user seems to like jazz"},
                                  source="chat", explicit=False)
    assert captured["pending"] is False
