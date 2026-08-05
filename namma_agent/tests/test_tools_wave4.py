"""Phase 7 Wave 4 — memory / delegate_task / persona tools.

These tools need live core handles (DB / provider / agent), so they're wired via
``register_memory_tools`` + ``register_agent_tools`` (not auto-discovery).
"""
from __future__ import annotations

import pytest

from namma_agent.core.agent import Agent
from namma_agent.core.builtins import register_agent_tools, register_memory_tools
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry, ToolResult


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return self._responses.pop(0)


class _StubIngestor:
    def __init__(self):
        self.texts = []

    def ingest_text(self, text):
        self.texts.append(text)


@pytest.fixture
def wired():
    db = Database(":memory:")
    reg = ToolRegistry()
    ing = _StubIngestor()
    reg._test_ingestor = ing  # handle for tests
    register_memory_tools(reg, db, get_plugin_ingestor=lambda: ing)
    # a couple of research tools so delegate_task has something to copy
    reg.register("system_info", "host", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="os: TestOS"))
    agent = Agent(ScriptedProvider([]), reg, db, load_persona())
    register_agent_tools(reg, agent, agent.provider, db)
    return reg, db, agent


# ── memory ────────────────────────────────────────────────────────────────────

def test_memory_tools_registered(wired):
    reg, _, _ = wired
    for name in ("remember_fact", "recall_facts", "search_conversations", "clear_memory"):
        assert name in reg


def test_remember_fact_goes_to_ingestor(wired):
    reg, db, _ = wired
    assert reg.execute("remember_fact", {"key": "editor", "value": "neovim"}).ok
    assert any("neovim" in t for t in reg._test_ingestor.texts)
    assert db.all_facts() == []  # the pipeline is the memory - no SQLite fact rows


def test_recall_facts_requires_memory_engine(wired):
    reg, _, _ = wired
    r = reg.execute("recall_facts", {"query": "editor"})
    assert not r.ok and "memory engine" in (r.error or "").lower()


def test_search_conversations(wired):
    reg, db, _ = wired
    sid = db.create_session()
    db.add_turn(sid, "user", "remind me to water the plants")
    db.add_turn(sid, "assistant", "Sure thing.")
    r = reg.execute("search_conversations", {"query": "plants"})
    assert r.ok and "water the plants" in r.content


def test_clear_memory_destructive(wired):
    reg, _, _ = wired
    assert reg.get("clear_memory").destructive is True


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
        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
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


class _DeadProvider(Provider):
    """Stands in for the legacy `provider:` chain on a profile-only setup: no
    credentials, so it refuses before any request goes out."""

    name = "dead"

    def __init__(self):
        super().__init__(model="dead")

    def is_available(self):
        return False

    def generate(self, *a, **k):
        raise RuntimeError("No LLM provider is available")


def test_delegate_runs_on_the_turns_model_not_the_boot_provider(wired):
    """The sub-agent must use the brain the user picked for THIS chat. Wiring it
    to the boot-time provider made every delegation fail instantly on any setup
    where the legacy `provider:` chain has no key."""
    from namma_agent.core.interactive import reset_current_provider, set_current_provider

    reg, db, agent = wired
    register_agent_tools(reg, agent, _DeadProvider(), db)
    turn_provider = ScriptedProvider([LLMResponse(content="Finding: from the turn's model.")])
    token = set_current_provider(turn_provider)
    try:
        r = reg.execute("delegate_task", {"task": "x"})
    finally:
        reset_current_provider(token)
    assert r.ok and "from the turn's model" in r.content


def test_delegate_falls_back_to_the_live_provider_getter(wired):
    """No turn provider (a routine, a comms turn) → the service's live getter,
    still never the dead boot-time chain."""
    reg, db, agent = wired
    live = ScriptedProvider([LLMResponse(content="Finding: from the live getter.")])
    register_agent_tools(reg, agent, _DeadProvider(), db, provider_getter=lambda: live)
    r = reg.execute("delegate_task", {"task": "x"})
    assert r.ok and "from the live getter" in r.content


def test_delegate_session_stays_out_of_the_chat_list(wired):
    """A sub-agent transcript is bookkeeping — it must not show up as a chat."""
    reg, db, agent = wired
    agent.provider._responses = [LLMResponse(content="done")]
    before = len(db.list_sessions())
    assert reg.execute("delegate_task", {"task": "x"}).ok
    assert len(db.list_sessions()) == before


def test_delegate_drops_per_model_tool_scoping(wired):
    """A model profile's `tools_allow` scopes the MAIN agent. Inheriting it would
    filter the sub-agent's already-scoped registry down to nothing."""
    reg, db, agent = wired
    captured = {}

    class _Capture(Provider):
        name = "cap"
        def __init__(self): super().__init__(model="cap")
        def is_available(self): return True
        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
            captured["tools"] = [t["name"] for t in (tools or [])]
            return LLMResponse(content="done")

    scoped = _Capture()
    scoped.tool_allow = ["send_message"]  # a tool the sub-agent doesn't have
    register_agent_tools(reg, agent, scoped, db)
    reg.execute("delegate_task", {"task": "x"})
    assert "system_info" in captured["tools"]


def test_delegate_inherits_main_tool_loop_limit(wired):
    """The research sub-agent must honour the main agent's tool-step budget — not a
    hidden hardcoded cap — so an unlimited config lets deep research finish."""
    reg, db, agent = wired

    class _Looping(Provider):
        name = "loop"
        def __init__(self):
            super().__init__(model="loop")
            self.calls = 0
        def is_available(self):
            return True
        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
            self.calls += 1  # never finalize → loop runs to the cap
            return LLMResponse(content="", tool_calls=[
                ToolCall(id=str(self.calls), name="system_info", args={})])

    prov = _Looping()
    agent.provider = prov
    agent.tool_loop_limit = 3  # the sub-agent must use THIS, not the old hardcoded 8
    register_agent_tools(reg, agent, prov, db)
    reg.execute("delegate_task", {"task": "x"})
    assert prov.calls == 3


# ── persona ───────────────────────────────────────────────────────────────────

def test_list_personas(wired):
    reg, _, agent = wired
    r = reg.execute("list_personas", {})
    assert r.ok and "core" in r.content
    assert agent.persona.id in r.data["available"]


def test_switch_persona(wired, tmp_path, monkeypatch):
    reg, _, agent = wired
    # Create a user persona (in a temp dir so we don't touch ~/.namma_agent), then switch.
    import namma_agent.core.persona as P
    monkeypatch.setattr(P, "_USER_PERSONA_DIR", tmp_path / "personas")
    c = reg.execute("create_persona", {"name": "Sage", "identity": "You are {name}, a sage."})
    assert c.ok
    r = reg.execute("switch_persona", {"persona": "sage"})
    assert r.ok and agent.persona.id == "sage"


def test_switch_unknown_persona(wired):
    reg, _, agent = wired
    before = agent.persona.id
    r = reg.execute("switch_persona", {"persona": "does_not_exist"})
    assert not r.ok and agent.persona.id == before
