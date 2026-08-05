"""Phase 2 tests — single SQLite memory store."""
from __future__ import annotations

from namma_agent.core.memory import Database


def _db():
    return Database(":memory:")


def test_session_and_turns_roundtrip():
    db = _db()
    sid = db.create_session()
    db.add_turn(sid, "user", "hello")
    db.add_turn(sid, "assistant", "hi there", tools_used=["x"])
    turns = db.recent_turns(sid, limit=10)
    assert turns == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


def test_recent_turns_limit_and_order():
    db = _db()
    sid = db.create_session()
    for i in range(20):
        db.add_turn(sid, "user", f"m{i}")
    turns = db.recent_turns(sid, limit=5)
    assert [t["content"] for t in turns] == ["m15", "m16", "m17", "m18", "m19"]


def test_recent_turns_drops_empty_assistant_rows():
    """An interrupted/failed turn can leave a content-less assistant row in the
    DB; replaying it would poison the next request (endpoints reject assistant
    messages with neither content nor tool_calls)."""
    db = _db()
    sid = db.create_session()
    db.add_turn(sid, "user", "do the thing")
    db.add_turn(sid, "assistant", "")           # the poisoned row
    db.add_turn(sid, "assistant", "done", tools_used=["echo"])
    turns = db.recent_turns(sid, limit=10)
    assert turns == [
        {"role": "user", "content": "do the thing"},
        {"role": "assistant", "content": "done"},
    ]


def test_facts_upsert_and_get():
    db = _db()
    db.save_fact("Name", "Tricky")
    assert db.get_fact("name") == "Tricky"
    db.save_fact("name", "Tricky R")  # upsert, case-insensitive key
    assert db.get_fact("name") == "Tricky R"
    assert len(db.all_facts()) == 1


def test_facts_fts_search():
    db = _db()
    db.save_fact("preferred_editor", "vim")
    db.save_fact("os", "Kali Linux")
    hits = db.search_facts("vim")
    assert any(h["key"] == "preferred_editor" for h in hits)


def test_facts_search_handles_punctuation():
    db = _db()
    db.save_fact("target", "192.168.1.0/24")
    # Slash/dot would break a raw FTS MATCH; the LIKE fallback should still find it.
    hits = db.search_facts("192.168.1.0/24")
    assert any(h["key"] == "target" for h in hits)


def test_audit_log():
    db = _db()
    sid = db.create_session()
    db.log_audit(sid, "nmap", {"host": "x"}, "3 ports open", True)
    rows = db.conn.execute("SELECT tool_name, success FROM audit").fetchall()
    assert rows[0]["tool_name"] == "nmap"
    assert rows[0]["success"] == 1
