"""background_task / check_background_task — detached sub-agents that report
back, plus toolset scoping for delegated sub-agents (never destructive)."""
from __future__ import annotations

import time

import pytest

from namma_agent.core.agent import Agent
from namma_agent.core.builtins import register_agent_tools
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry, ToolResult


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return self._responses.pop(0) if self._responses else LLMResponse(content="done")


class _StubComms:
    any_available = True

    def __init__(self):
        self.sent: list[str] = []

    def send(self, text):
        self.sent.append(text)


@pytest.fixture
def wired(tmp_path):
    db = Database(":memory:")
    reg = ToolRegistry()
    reg.register("system_info", "host", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="os: TestOS"))
    reg.register("read_notes", "read", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="notes"), category="files_ro")
    reg.register("delete_all", "danger", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="gone"),
                 destructive=True, category="files_ro")
    agent = Agent(ScriptedProvider([]), reg, db, load_persona())
    comms = _StubComms()
    handles = register_agent_tools(reg, agent, agent.provider, db,
                                   get_comms=lambda: comms,
                                   bg_store_path=tmp_path / "bg.json")
    reg._handles = handles  # test hook
    return reg, agent, comms


def _wait_done(reg, task_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = reg.execute("check_background_task", {"id": task_id})
        if r.data and r.data.get("status") != "running":
            return r
        time.sleep(0.02)
    raise AssertionError("background task never finished")


def test_background_task_runs_and_notifies(wired):
    reg, agent, comms = wired
    agent.provider._responses = [LLMResponse(content="Finding: 42.")]
    r = reg.execute("background_task", {"task": "compute the answer", "name": "answer"})
    assert r.ok and r.data.get("id")
    done = _wait_done(reg, r.data["id"])
    assert done.data["status"] == "done" and done.content == "Finding: 42."
    # give the notifier a beat — it fires right after the status flips
    deadline = time.time() + 2
    while not comms.sent and time.time() < deadline:
        time.sleep(0.02)
    assert comms.sent and "answer" in comms.sent[0] and "42" in comms.sent[0]


def test_background_task_failure_is_reported(wired, tmp_path):
    reg, agent, comms = wired

    class _Boom(Provider):
        name = "boom"

        def __init__(self):
            super().__init__(model="boom")

        def is_available(self):
            return True

        def generate(self, *a, **k):
            raise RuntimeError("brain offline")

    # rebuild so the closure sees the failing provider
    agent.provider = _Boom()
    db = Database(":memory:")
    register_agent_tools(reg, agent, agent.provider, db, get_comms=lambda: comms,
                         bg_store_path=tmp_path / "bg2.json")
    r = reg.execute("background_task", {"task": "anything"})
    done = _wait_done(reg, r.data["id"])
    assert done.data["status"] == "failed" and "brain offline" in done.content


def test_check_without_id_lists_tasks(wired):
    reg, agent, _ = wired
    assert "No background tasks" in reg.execute("check_background_task", {}).content
    agent.provider._responses = [LLMResponse(content="x")]
    r = reg.execute("background_task", {"task": "t", "name": "listed"})
    _wait_done(reg, r.data["id"])
    listing = reg.execute("check_background_task", {})
    assert "listed" in listing.content and "done" in listing.content


def test_background_task_requires_task(wired):
    reg, _, _ = wired
    assert not reg.execute("background_task", {"task": " "}).ok


def test_background_task_uses_the_turns_model(wired, tmp_path):
    """The brain is resolved on the TURN's thread — the worker thread does not
    inherit the current-provider contextvar, and the boot-time provider may hold
    no credentials at all."""
    from namma_agent.core.interactive import reset_current_provider, set_current_provider
    from namma_agent.core.memory import Database as _Db

    reg, agent, comms = wired

    class _Dead(Provider):
        name = "dead"
        def __init__(self): super().__init__(model="dead")
        def is_available(self): return False
        def generate(self, *a, **k): raise RuntimeError("No LLM provider is available")

    register_agent_tools(reg, agent, _Dead(), _Db(":memory:"),
                         get_comms=lambda: comms, bg_store_path=tmp_path / "bg4.json")
    token = set_current_provider(ScriptedProvider([LLMResponse(content="Finding: 42.")]))
    try:
        r = reg.execute("background_task", {"task": "compute", "name": "answer"})
    finally:
        reset_current_provider(token)
    done = _wait_done(reg, r.data["id"])
    assert done.data["status"] == "done" and "42" in done.content


def test_subagent_toolsets_scope_excludes_destructive(wired, tmp_path):
    """A requested toolset widens the sub-agent's surface but NEVER lets a
    destructive tool through (sub-agents have no approval channel)."""
    reg, agent, _ = wired
    captured = {}

    class _Capture(Provider):
        name = "cap"

        def __init__(self):
            super().__init__(model="cap")

        def is_available(self):
            return True

        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
            captured["tools"] = [t["name"] for t in (tools or [])]
            return LLMResponse(content="done")

    agent.provider = _Capture()
    db = Database(":memory:")
    register_agent_tools(reg, agent, agent.provider, db,
                         bg_store_path=tmp_path / "bg3.json")
    reg.execute("delegate_task", {"task": "x", "toolsets": ["files_ro"]})
    assert "read_notes" in captured["tools"]
    assert "delete_all" not in captured["tools"]        # destructive stripped
    assert "delegate_task" not in captured["tools"]     # no recursion


# ── persistence across restarts ──────────────────────────────────────────────

def test_finished_tasks_survive_a_restart(wired, tmp_path):
    reg, agent, _ = wired
    agent.provider._responses = [LLMResponse(content="the answer")]
    r = reg.execute("background_task", {"task": "t", "name": "persisted"})
    _wait_done(reg, r.data["id"])

    # "Restart": a fresh registry + registration over the same store file.
    db = Database(":memory:")
    reg2 = ToolRegistry()
    agent2 = Agent(ScriptedProvider([]), reg2, db, load_persona())
    register_agent_tools(reg2, agent2, agent2.provider, db,
                         bg_store_path=tmp_path / "bg.json")
    revived = reg2.execute("check_background_task", {"id": r.data["id"]})
    assert revived.ok and revived.content == "the answer"


def test_running_tasks_marked_interrupted_after_restart(tmp_path):
    from namma_agent.tools import _jsonstore
    store = tmp_path / "bg.json"
    _jsonstore.save(store, [{"id": "abc12345", "name": "orphan", "task": "t",
                             "status": "running", "result": "", "error": "",
                             "started_at": 1.0, "finished_at": None}])
    db = Database(":memory:")
    reg = ToolRegistry()
    agent = Agent(ScriptedProvider([]), reg, db, load_persona())
    handles = register_agent_tools(reg, agent, agent.provider, db,
                                   bg_store_path=store)
    r = reg.execute("check_background_task", {"id": "abc12345"})
    assert r.data["status"] == "interrupted" and "restarted" in r.content
    # the store itself was rewritten with the corrected status
    assert _jsonstore.load(store)[0]["status"] == "interrupted"
    # and the handle lists it for the status panel
    listing = handles["background_tasks"]()
    assert listing and listing[0]["id"] == "abc12345"
    assert "_thread" not in listing[0]
