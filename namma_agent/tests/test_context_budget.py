"""Phase 2: two-phase in-turn context compaction, context windows, and model
profiles honouring provider.fallback."""
from __future__ import annotations

from namma_agent.core import context_budget as cb
from namma_agent.core.agent import Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry


class Small(Provider):
    """A tiny-window provider that records what it was sent."""
    name = "small"

    def __init__(self, responses, window=4000):
        super().__init__(model="tiny")
        self.context_window = window
        self._r = list(responses)
        self.seen: list[list[dict]] = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen.append([dict(m) for m in messages])
        if tools is None and messages and "Condense" in messages[0]["content"]:
            return LLMResponse(content="Goal: build a rocket.")
        return self._r.pop(0) if self._r else LLMResponse(content="done")


def test_context_window_lookup():
    class P:
        model = "claude-sonnet-4-6"
    assert cb.context_window(P()) == 200_000
    P.model = "gpt-5.5"
    assert cb.context_window(P()) == 400_000
    P.model = "something-unknown"
    assert cb.context_window(P()) == cb.DEFAULT_WINDOW
    P.context_window = 8192
    assert cb.context_window(P()) == 8192


def test_phase1_clears_all_but_the_newest_tool_outputs():
    msgs = [{"role": "system", "content": "s"}]
    for i in range(6):
        msgs.append({"role": "tool", "tool_call_id": str(i), "name": "t", "content": "x" * 1000})
    assert cb.clear_old_tool_outputs(msgs, keep=4) == 2
    assert [m["content"] == cb.CLEARED for m in msgs[1:]] == [True, True, False, False, False, False]
    assert cb.clear_old_tool_outputs(msgs, keep=4) == 0      # idempotent


def test_fit_is_a_noop_under_the_limit():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "hi"}]

    class P:
        model = "claude"
    out, end = cb.fit(msgs, 1, P(), None, lambda p: "unused")
    assert out is msgs and end == 1


def test_fit_phase2_folds_history_into_the_system_prompt():
    msgs = [{"role": "system", "content": "SYS"}]
    msgs += [{"role": "user" if i % 2 == 0 else "assistant", "content": "y" * 3000}
             for i in range(8)]
    msgs.append({"role": "user", "content": "now?"})
    events = []

    class P:
        model = "x"
        context_window = 4000
    out, end = cb.fit(msgs, 9, P(), None, lambda p: "Goal: test.", emit=events.append)
    assert end == 1 and len(out) == 2
    assert out[0]["content"].startswith("SYS") and "Goal: test." in out[0]["content"]
    assert out[1]["content"] == "now?"
    assert [e["phase"] for e in events] == [2]


def test_agent_loop_clears_old_tool_outputs_when_the_window_fills():
    reg = ToolRegistry()
    reg.register("big", "Big output.", {"type": "object", "properties": {}},
                 lambda a: "z" * 3000)
    calls = [LLMResponse(content="", tool_calls=[ToolCall(id=str(i), name="big", args={})])
             for i in range(6)]
    prov = Small(calls + [LLMResponse(content="finished")], window=8000)
    agent = Agent(prov, reg, Database(":memory:"), load_persona())
    events = []
    res = agent.process_turn("go", emit=lambda e, p: events.append((e, p)))
    assert res.content == "finished"
    phases = [p["phase"] for e, p in events if e == "context_compacted"]
    assert 1 in phases
    last = prov.seen[-1]
    tool_contents = [m["content"] for m in last if m.get("role") == "tool"]
    assert tool_contents.count(cb.CLEARED) >= 1
    assert tool_contents[-1] == "z" * 3000                  # newest kept verbatim


def test_context_fraction_zero_disables_compaction():
    reg = ToolRegistry()
    reg.register("big", "Big.", {"type": "object", "properties": {}}, lambda a: "z" * 3000)
    calls = [LLMResponse(content="", tool_calls=[ToolCall(id=str(i), name="big", args={})])
             for i in range(5)]
    prov = Small(calls + [LLMResponse(content="ok")], window=6000)
    agent = Agent(prov, reg, Database(":memory:"), load_persona())
    agent.context_fraction = 0
    events = []
    agent.process_turn("go", emit=lambda e, p: events.append(e))
    assert "context_compacted" not in events


# ── model profiles honour provider.fallback ─────────────────────────────────

def test_profile_provider_gets_the_fallback_chain():
    from namma_agent.core.providers.registry import ProviderChain
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(
        config={"persona": "core", "conversation": {},
                "provider": {"type": "openai", "model": "gpt-4o-mini",
                             "fallback": [{"type": "ollama", "model": "llama3.1"},
                                          {"type": "openai", "model": "gpt-5"}]},
                "models": [{"id": "main", "type": "openai", "model": "gpt-5"}]},
        provider=Small([]), registry=ToolRegistry(), db=Database(":memory:"))
    prov = svc.provider_for("main")
    assert isinstance(prov, ProviderChain)
    assert [p.model for p in prov._providers] == ["gpt-5", "llama3.1"]   # self skipped
    assert prov.model == "gpt-5" and prov.timeout_s >= 120


def test_profile_without_fallback_stays_a_single_provider():
    from namma_agent.core.providers.registry import ProviderChain
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(
        config={"persona": "core", "conversation": {},
                "provider": {"type": "openai", "model": "gpt-4o-mini"},
                "models": [{"id": "main", "type": "openai", "model": "gpt-5",
                            "context_window": 50000}]},
        provider=Small([]), registry=ToolRegistry(), db=Database(":memory:"))
    prov = svc.provider_for("main")
    assert not isinstance(prov, ProviderChain)
    assert prov.context_window == 50000
