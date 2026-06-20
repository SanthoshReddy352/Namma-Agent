"""Follow-up round — unlimited tool loop, delete session, app tracking, exit, auto-approve."""
from __future__ import annotations

from friday.core.agent import Agent
from friday.core.memory import Database
from friday.core.persona import load_persona
from friday.core.providers.base import LLMResponse, Provider, ToolCall
from friday.core.tools import ToolRegistry, ToolResult


class _ToolThenDone(Provider):
    """Emits `rounds` tool-calls, then a final answer."""
    name = "ttd"

    def __init__(self, rounds):
        super().__init__(model="ttd")
        self.rounds = rounds
        self.calls = 0

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None):
        self.calls += 1
        if self.calls <= self.rounds:
            return LLMResponse(content="", tool_calls=[ToolCall(id=str(self.calls), name="ping", args={})])
        return LLMResponse(content="done")


def _reg():
    r = ToolRegistry()
    r.register("ping", "p", {"type": "object", "properties": {}}, lambda a: ToolResult(ok=True, content="pong"))
    return r


def test_unlimited_tool_loop_runs_past_old_limit():
    prov = _ToolThenDone(rounds=25)  # far beyond the old cap of 10
    agent = Agent(prov, _reg(), Database(":memory:"), load_persona(), tool_loop_limit=0)
    result = agent.process_turn("go")
    assert result.content == "done"
    assert prov.calls == 26  # 25 tool rounds + 1 final


def test_hard_limit_still_works():
    prov = _ToolThenDone(rounds=99)
    agent = Agent(prov, _reg(), Database(":memory:"), load_persona(), tool_loop_limit=3)
    result = agent.process_turn("go")
    assert "limit" in result.content.lower()
    assert prov.calls == 3


def test_delete_session():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "hi")
    assert any(s["id"] == sid for s in db.list_sessions())
    assert db.delete_session(sid) is True
    assert all(s["id"] != sid for s in db.list_sessions())
    assert db.session_turns(sid) == []


def test_app_tracker():
    from friday.core.app_tracker import AppTracker, _aliases, is_running
    assert "chrome" in _aliases("google-chrome")
    assert is_running("definitely-not-a-real-app-xyz123") is False
    import tempfile
    from pathlib import Path
    t = AppTracker(Path(tempfile.mkdtemp()) / "apps.json")
    t.record("myapp", "/usr/bin/myapp", 1234)
    assert "myapp" in t._apps


def test_session_turns_have_timestamps():
    db = Database(":memory:")
    sid = db.create_session()
    db.add_turn(sid, "user", "hi")
    turns = db.session_turns(sid)
    assert turns and "created_at" in turns[0]


def test_exit_tool_registered_and_calls_shutdown():
    from friday.service import FridayService
    from friday.tests.test_server import ScriptedProvider
    svc = FridayService(config={"persona": "core", "conversation": {}},
                        provider=ScriptedProvider([LLMResponse(content="hi")]),
                        registry=ToolRegistry(), db=Database(":memory:"))
    called = {}
    svc.shutdown = lambda *a, **k: called.setdefault("yes", True)
    svc._register_exit_tool()
    assert "exit_friday" in svc.registry.names()
    out = svc.registry.execute("exit_friday", {"farewell": "bye!"})
    assert out.ok and out.data.get("shutdown") is True and called.get("yes")


def test_auto_approve_bypasses_prompt():
    from friday.service import FridayService
    from friday.tests.test_server import ScriptedProvider
    # A turn that calls a destructive tool; auto_approve should run it without prompting.
    reg = ToolRegistry()
    hits = {"ran": False}
    reg.register("danger", "d", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="boom") if not hits.update(ran=True) else None,
                 destructive=True)
    prov = ScriptedProvider([
        LLMResponse(content="", tool_calls=[ToolCall(id="1", name="danger", args={})]),
        LLMResponse(content="done"),
    ])
    svc = FridayService(config={"persona": "core", "conversation": {}},
                        provider=prov, registry=reg, db=Database(":memory:"))
    svc.auto_approve = True
    # approval returns False — but auto_approve must override and still run the tool.
    svc.run_turn("do danger", approval=lambda *_: False)
    assert hits["ran"] is True
