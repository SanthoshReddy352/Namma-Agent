"""Phase 4: message actions (delete, truncate for regenerate / edit-and-resend,
branch), turn ids on results, and the step inspector data (durations, plan
card, notices)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from namma_agent.core.agent import Agent, _record_step
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry


def _seed(db, n=6):
    sid = db.create_session()
    ids = [db.add_turn(sid, "user" if i % 2 == 0 else "assistant", f"m{i}") for i in range(n)]
    return sid, ids


def test_add_turn_returns_ids_and_history_carries_them():
    db = Database(":memory:")
    sid, ids = _seed(db, 2)
    assert all(isinstance(i, int) for i in ids) and ids[1] > ids[0]
    assert [t["id"] for t in db.session_turns(sid)] == ids


def test_delete_one_turn_and_its_search_entry():
    db = Database(":memory:")
    sid, ids = _seed(db)
    assert db.delete_turn(sid, ids[2])
    assert [t["content"] for t in db.session_turns(sid)] == ["m0", "m1", "m3", "m4", "m5"]
    assert not db.search_turns("m2")
    assert not db.delete_turn("other-session", ids[3])       # scoped to the session


def test_truncate_rewinds_from_a_turn_and_drops_a_stale_summary():
    db = Database(":memory:")
    sid, ids = _seed(db)
    db.set_compaction(sid, "summary covering m4", ids[4])
    assert db.delete_turns_from(sid, ids[2]) == 4
    assert [t["content"] for t in db.session_turns(sid)] == ["m0", "m1"]
    assert db.get_compaction(sid) == {"summary": "", "upto": 0}


def test_branch_copies_history_up_to_a_turn():
    db = Database(":memory:")
    sid, ids = _seed(db)
    db.set_session_model(sid, "m-large")
    new = db.branch_session(sid, ids[3])
    assert new and new != sid
    assert [t["content"] for t in db.session_turns(new)] == ["m0", "m1", "m2", "m3"]
    assert db.get_session(new)["model"] == "m-large"
    assert db.get_session(new)["title"].startswith("↳")
    assert len(db.session_turns(sid)) == 6                    # the original is untouched
    assert db.branch_session("nope", 1) is None


class _P(Provider):
    name = "p"

    def __init__(self, responses):
        super().__init__(model="p")
        self._r = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return self._r.pop(0) if self._r else LLMResponse(content="ok")


def test_agent_result_carries_the_persisted_turn_ids():
    db = Database(":memory:")
    res = Agent(_P([LLMResponse(content="hello")]), ToolRegistry(), db,
                load_persona()).process_turn("hi")
    rows = db.session_turns(res.session_id)
    assert [res.user_turn_id, res.assistant_turn_id] == [r["id"] for r in rows]


def test_api_endpoints_delete_truncate_branch():
    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=_P([]), registry=ToolRegistry(), db=Database(":memory:"))
    client = TestClient(create_app(svc))
    sid, ids = _seed(svc.db)
    assert client.delete(f"/api/sessions/{sid}/turns/{ids[5]}").json()["ok"]
    assert client.post(f"/api/sessions/{sid}/truncate", json={"from_turn_id": ids[4]}).json()["removed"] == 1
    branched = client.post(f"/api/sessions/{sid}/branch", json={"upto_turn_id": ids[1]}).json()
    assert branched["ok"] and len(svc.db.session_turns(branched["session_id"])) == 2
    assert client.post(f"/api/sessions/{sid}/truncate", json={}).status_code == 400
    assert client.post(f"/api/sessions/{sid}/branch", json={"upto_turn_id": 0}).status_code == 404
    hist = client.get(f"/api/sessions/{sid}").json()
    assert all("id" in t for t in hist["turns"])


# ── step inspector data ──────────────────────────────────────────────────────

def test_steps_carry_duration_plan_and_notices():
    reg = ToolRegistry()
    reg.register("update_todos", "Plan.", {"type": "object", "properties": {}}, lambda a: "ok")
    reg.register("read_file", "Read.", {"type": "object", "properties": {}}, lambda a: "text")
    todos = [{"text": "read", "status": "done"}, {"text": "answer", "status": "in_progress"}]
    prov = _P([LLMResponse(content="", tool_calls=[
        ToolCall(id="1", name="update_todos", args={"todos": todos}),
        ToolCall(id="2", name="read_file", args={"path": "x"})]),
        LLMResponse(content="done")])
    res = Agent(prov, reg, Database(":memory:"), load_persona()).process_turn("go")
    tools = [s for s in res.steps if s["kind"] == "tool"]
    assert all(isinstance(s.get("ms"), int) for s in tools)
    plan = [s for s in res.steps if s["kind"] == "plan"]
    assert len(plan) == 1 and plan[0]["plan"] == todos


def test_notice_steps_from_turn_events():
    steps: list = []
    _record_step(steps, "tools_trimmed", {"limit": 128, "dropped": ["a", "b"]})
    _record_step(steps, "context_compacted", {"phase": 2})
    _record_step(steps, "turn_budget_exceeded", {"tokens": 1200, "budget": 1000})
    _record_step(steps, "plan_updated", {"plan": [{"text": "a"}]})
    _record_step(steps, "plan_updated", {"plan": [{"text": "b"}]})
    kinds = [s["kind"] for s in steps]
    assert kinds == ["notice", "notice", "notice", "plan"]        # latest plan only
    assert "2 tools" in steps[0]["text"] and "Summarized" in steps[1]["text"]
    assert "1,200" in steps[2]["text"] and steps[3]["plan"] == [{"text": "b"}]
