"""Phase 7 Wave 4 — memory / delegate_task / persona tools.

These tools need live core handles (DB / provider / agent), so they're wired via
``register_memory_tools`` + ``register_agent_tools`` (not auto-discovery).
"""
from __future__ import annotations

import pytest

from friday.core.agent import Agent
from friday.core.builtins import register_agent_tools, register_memory_tools
from friday.core.memory import Database
from friday.core.persona import load_persona
from friday.core.providers.base import LLMResponse, Provider, ToolCall
from friday.core.safety import is_destructive
from friday.core.tools import ToolRegistry, ToolResult


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None):
        return self._responses.pop(0)


@pytest.fixture
def wired():
    db = Database(":memory:")
    reg = ToolRegistry()
    register_memory_tools(reg, db)
    # a couple of research tools so delegate_task has something to copy
    reg.register("system_info", "host", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="os: TestOS"))
    agent = Agent(ScriptedProvider([]), reg, db, load_persona())
    register_agent_tools(reg, agent, agent.provider, db)
    return reg, db, agent


# ── memory ────────────────────────────────────────────────────────────────────

def test_memory_tools_registered(wired):
    reg, _, _ = wired
    for name in ("remember_fact", "recall_facts", "forget_fact", "search_conversations"):
        assert name in reg


def test_remember_forget_roundtrip(wired):
    reg, db, _ = wired
    assert reg.execute("remember_fact", {"key": "editor", "value": "neovim"}).ok
    assert db.get_fact("editor") == "neovim"
    r = reg.execute("forget_fact", {"key": "editor"})
    assert r.ok and db.get_fact("editor") is None


def test_forget_missing_fact(wired):
    reg, _, _ = wired
    r = reg.execute("forget_fact", {"key": "nope"})
    assert not r.ok


def test_search_conversations(wired):
    reg, db, _ = wired
    sid = db.create_session()
    db.add_turn(sid, "user", "remind me to water the plants")
    db.add_turn(sid, "assistant", "Sure thing.")
    r = reg.execute("search_conversations", {"query": "plants"})
    assert r.ok and "water the plants" in r.content


def test_forget_fact_destructive(wired):
    reg, _, _ = wired
    assert reg.get("forget_fact").destructive is True
    assert is_destructive("forget_fact")


# ── delegate_task ─────────────────────────────────────────────────────────────

def test_delegate_task_runs_subagent(wired):
    reg, _, agent = wired
    # sub-agent returns a final answer immediately
    agent.provider._responses = [LLMResponse(content="Finding: the sky is blue.")]
    r = reg.execute("delegate_task", {"task": "why is the sky blue"})
    assert r.ok and "sky is blue" in r.content


def test_delegate_task_excludes_itself(wired):
    """The sub-agent must not be able to delegate again (no recursion)."""
    reg, db, agent = wired
    captured = {}

    class _Capture(Provider):
        name = "cap"
        def __init__(self): super().__init__(model="cap")
        def is_available(self): return True
        def generate(self, messages, tools=None, stream=False, on_token=None):
            captured["tools"] = [t["name"] for t in (tools or [])]
            return LLMResponse(content="done")

    agent.provider = _Capture()
    # rebuild agent tools so delegate_task closes over the new provider
    register_agent_tools(reg, agent, agent.provider, db)
    reg.execute("delegate_task", {"task": "x"})
    assert "delegate_task" not in captured["tools"]
    assert "system_info" in captured["tools"]


def test_delegate_task_requires_task(wired):
    reg, _, _ = wired
    assert not reg.execute("delegate_task", {"task": ""}).ok


# ── persona ───────────────────────────────────────────────────────────────────

def test_list_personas(wired):
    reg, _, agent = wired
    r = reg.execute("list_personas", {})
    assert r.ok and "friday_core" in r.content
    assert agent.persona.id in r.data["available"]


def test_switch_persona(wired):
    reg, _, agent = wired
    r = reg.execute("switch_persona", {"persona": "friday_concise"})
    assert r.ok and agent.persona.id == "friday_concise"


def test_switch_unknown_persona(wired):
    reg, _, agent = wired
    before = agent.persona.id
    r = reg.execute("switch_persona", {"persona": "does_not_exist"})
    assert not r.ok and agent.persona.id == before
