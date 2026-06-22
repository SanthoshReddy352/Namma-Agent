"""Phase B memory upgrade — FTS turns search, session summaries, curated notes."""
from __future__ import annotations

from namma_agent.core.builtins import register_agent_tools, register_memory_tools
from namma_agent.core.memory import Database
from namma_agent.core.memory_notes import MemoryNotes
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry


class _FixedProvider(Provider):
    name = "fixed"

    def __init__(self, text="A short summary."):
        super().__init__(model="fixed")
        self._text = text

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content=self._text)


# ── DB: FTS turns + session summaries ───────────────────────────────────────

def test_turns_fts_search():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "I love kayaking on the river")
    db.add_turn(sid, "assistant", "Noted — kayaking is great exercise")
    hits = db.search_turns("kayaking")
    assert any("kayaking" in h["content"] for h in hits)


def test_session_summary_roundtrip_and_search():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "plan a trip to Japan")
    assert db.count_turns(sid) == 1
    assert sid in db.unsummarized_sessions()
    db.set_session_summary(sid, "User planned a trip to Japan.")
    assert db.get_session_summary(sid) == "User planned a trip to Japan."
    assert sid not in db.unsummarized_sessions()
    hits = db.search_sessions("Japan")
    assert hits and hits[0]["id"] == sid


def test_session_turns_chronological():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "first")
    db.add_turn(sid, "assistant", "second")
    turns = db.session_turns(sid)
    assert [t["content"] for t in turns] == ["first", "second"]


# ── MemoryNotes ─────────────────────────────────────────────────────────────

def test_memory_notes_roundtrip(tmp_path):
    notes = MemoryNotes(tmp_path / "mem")
    assert notes.user_path.exists() and notes.memory_path.exists()
    assert notes.block() == ""  # empty headers only → no injection
    notes.append_note("user prefers dark mode")
    notes.write_user("# User Profile\n\nName: Tricky")
    block = notes.block()
    assert "dark mode" in block
    assert "Tricky" in block


# ── Tools ───────────────────────────────────────────────────────────────────

def test_memory_note_tools(tmp_path):
    db = Database(":memory:")
    notes = MemoryNotes(tmp_path / "mem")
    reg = ToolRegistry()
    register_memory_tools(reg, db, notes=notes)
    assert {"remember_note", "read_memory", "update_user_profile", "recall_sessions"} <= set(reg.names())

    assert reg.execute("remember_note", {"note": "ships on Fridays"}).ok
    assert reg.execute("update_user_profile", {"content": "Likes terse answers"}).ok
    out = reg.execute("read_memory", {})
    assert out.ok and "ships on Fridays" in out.content and "terse" in out.content


def test_recall_sessions_tool():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "hi")
    db.set_session_summary(sid, "Discussed deployment pipelines.")
    reg = ToolRegistry()
    register_memory_tools(reg, db)
    out = reg.execute("recall_sessions", {"query": "deployment"})
    assert out.ok and "deployment" in out.content.lower()


def test_summarize_session_tool():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "talk about gardening")
    db.add_turn(sid, "assistant", "sure")
    provider = _FixedProvider("User chatted about gardening.")
    reg = ToolRegistry()
    register_memory_tools(reg, db)
    # register_agent_tools needs a live agent; build a minimal one.
    from namma_agent.core.agent import Agent
    agent = Agent(provider, reg, db, load_persona())
    register_agent_tools(reg, agent, provider, db)
    assert "summarize_session" in reg.names()
    out = reg.execute("summarize_session", {"session_id": sid})
    assert out.ok and "gardening" in out.content
    assert db.get_session_summary(sid) == "User chatted about gardening."


# ── Nudge ───────────────────────────────────────────────────────────────────

def test_memory_nudge_cadence():
    from namma_agent.core.agent import Agent
    db = Database(":memory:")
    agent = Agent(_FixedProvider(), ToolRegistry(), db, load_persona(), nudge_every=2)
    sid = db.create_session()
    assert agent._memory_nudge(sid) == ""        # 0 turns
    for _ in range(4):                            # 4 turns == 2 exchanges
        db.add_turn(sid, "user", "x")
    assert "memory nudge" in agent._memory_nudge(sid)
