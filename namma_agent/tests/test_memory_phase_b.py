"""Phase B memory upgrade — FTS turns search + session summaries.

(The curated-notes layer and the memory nudge were removed when Cognee became
the only memory; transcript search and summaries are what SQLite still does.)
"""
from __future__ import annotations

from namma_agent.core.builtins import register_agent_tools, register_memory_tools
from namma_agent.core.memory import Database
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


# ── Tools ───────────────────────────────────────────────────────────────────

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


# ── Cognee-backed memory tools ──────────────────────────────────────────────

class _StubIngestor:
    def __init__(self):
        self.texts = []

    def ingest_text(self, text):
        self.texts.append(text)


def test_remember_fact_routes_to_cognee():
    db = Database(":memory:")
    ing = _StubIngestor()
    reg = ToolRegistry()
    register_memory_tools(reg, db, get_cognee_ingestor=lambda: ing)
    out = reg.execute("remember_fact", {"key": "preferred_editor", "value": "vim"})
    assert out.ok and ing.texts and "vim" in ing.texts[0]
    # no SQLite fact is written anymore
    assert db.all_facts() == []


def test_remember_fact_without_cognee_errors():
    db = Database(":memory:")
    reg = ToolRegistry()
    register_memory_tools(reg, db)
    out = reg.execute("remember_fact", {"key": "a", "value": "b"})
    assert not out.ok and "cognee" in (out.error or "").lower()


def test_recall_facts_delegates_to_cognee_tool():
    db = Database(":memory:")
    reg = ToolRegistry()
    register_memory_tools(reg, db)
    # not connected → clear error
    out = reg.execute("recall_facts", {"query": "who am I"})
    assert not out.ok and "cognee" in (out.error or "").lower()
    # with a fake mcp_cognee_recall present, the call is delegated
    from namma_agent.core.tools import ToolResult
    reg.register("mcp_cognee_recall", "recall", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=f"answer to {a.get('query')}"))
    out = reg.execute("recall_facts", {"query": "who am I"})
    assert out.ok and "who am I" in out.content
