"""Rolling context compaction — long chats keep a running summary of the turns
that fell off the history window, injected into every prompt (background update,
one model call per ~3 evicted exchanges)."""
from __future__ import annotations

from namma_agent.core.agent import _COMPACT_BATCH, Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)
        self.seen_messages: list[list[dict]] = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen_messages.append(list(messages))
        return self._responses.pop(0) if self._responses else LLMResponse(content="")


def _seed_turns(db: Database, sid: str, n: int) -> None:
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        db.add_turn(sid, role, f"message number {i}")


def _agent(responses, window: int = 4):
    db = Database(":memory:")
    agent = Agent(ScriptedProvider(responses), ToolRegistry(), db, load_persona(),
                  max_history_turns=window)
    return agent, db


# ── db helpers ───────────────────────────────────────────────────────────────

def test_evicted_turns_returns_rows_off_the_window():
    db = Database(":memory:")
    sid = db.create_session()
    _seed_turns(db, sid, 10)
    evicted = db.evicted_turns(sid, window=4)
    assert [t["content"] for t in evicted] == [f"message number {i}" for i in range(6)]
    # after_id skips rows the summary already covers
    later = db.evicted_turns(sid, window=4, after_id=evicted[2]["id"])
    assert [t["content"] for t in later] == ["message number 3",
                                             "message number 4",
                                             "message number 5"]


def test_compaction_roundtrip_defaults_empty():
    db = Database(":memory:")
    sid = db.create_session()
    assert db.get_compaction(sid) == {"summary": "", "upto": 0}
    db.set_compaction(sid, "the story so far", 42)
    assert db.get_compaction(sid) == {"summary": "the story so far", "upto": 42}


# ── the background pass ──────────────────────────────────────────────────────

def test_schedule_compaction_summarizes_evicted_turns():
    agent, db = _agent([LLMResponse(content="- user is renaming the project")])
    sid = db.create_session()
    _seed_turns(db, sid, 4 + _COMPACT_BATCH)          # exactly one batch evicted
    t = agent._schedule_compaction(sid, agent.provider)
    assert t is not None
    t.join(timeout=5)
    comp = db.get_compaction(sid)
    assert comp["summary"] == "- user is renaming the project"
    assert comp["upto"] > 0
    # Nothing new evicted since → no second pass, no model call.
    assert agent._schedule_compaction(sid, agent.provider) is None


def test_short_sessions_never_trigger_compaction():
    agent, db = _agent([])
    sid = db.create_session()
    _seed_turns(db, sid, 6)                            # within window + batch
    assert agent._schedule_compaction(sid, agent.provider) is None
    assert agent.provider.seen_messages == []


def test_compaction_merges_previous_summary():
    agent, db = _agent([LLMResponse(content="updated summary")])
    sid = db.create_session()
    _seed_turns(db, sid, 4 + 2 * _COMPACT_BATCH)
    db.set_compaction(sid, "old summary",
                      db.evicted_turns(sid, 4)[_COMPACT_BATCH - 1]["id"])
    t = agent._schedule_compaction(sid, agent.provider)
    t.join(timeout=5)
    sent = agent.provider.seen_messages[0][-1]["content"]
    assert "PREVIOUS SUMMARY:\nold summary" in sent
    assert db.get_compaction(sid)["summary"] == "updated summary"


# ── prompt injection ─────────────────────────────────────────────────────────

def test_summary_rides_the_system_prompt():
    agent, db = _agent([])
    sid = db.create_session()
    db.set_compaction(sid, "user is building a rocket", 3)
    messages = agent._build_messages("continue", sid)
    assert "EARLIER IN THIS CONVERSATION" in messages[0]["content"]
    assert "user is building a rocket" in messages[0]["content"]
    # No summary → no block.
    sid2 = db.create_session()
    messages2 = agent._build_messages("hi", sid2)
    assert "EARLIER IN THIS CONVERSATION" not in messages2[0]["content"]


def test_compact_history_flag_disables_everything():
    db = Database(":memory:")
    agent = Agent(ScriptedProvider([]), ToolRegistry(), db, load_persona(),
                  max_history_turns=4, compact_history=False)
    sid = db.create_session()
    _seed_turns(db, sid, 20)
    db.set_compaction(sid, "should not appear", 1)
    messages = agent._build_messages("hi", sid)
    assert "should not appear" not in messages[0]["content"]
