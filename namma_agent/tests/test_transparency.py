"""Phase 4 tests — chat transparency: the structured activity timeline (thinking +
tool steps) collected during a turn, persisted to turn meta, and surfaced by the UI.
Also covers reasoning ("thinking") deltas flowing from a provider to a `thinking` event."""
from __future__ import annotations

from types import SimpleNamespace

from namma_agent.core.agent import Agent, _record_step
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry


# ── _record_step (the reducer shared in spirit with the web UI) ──────────────

def test_record_step_preamble_and_tools():
    steps: list[dict] = []
    _record_step(steps, "preamble", {"text": "On it."})
    _record_step(steps, "tool_started", {"tool": "echo", "args": {"x": 1}})
    _record_step(steps, "tool_finished", {"tool": "echo", "ok": True, "summary": "done"})
    assert steps[0] == {"kind": "preamble", "text": "On it."}
    assert steps[1]["kind"] == "tool" and steps[1]["state"] == "ok"
    assert steps[1]["summary"] == "done" and steps[1]["args"] == {"x": 1}


def test_record_step_tool_failure():
    steps: list[dict] = []
    _record_step(steps, "tool_started", {"tool": "boom", "args": {}})
    _record_step(steps, "tool_finished", {"tool": "boom", "ok": False, "summary": "nope"})
    assert steps[0]["state"] == "fail" and steps[0]["summary"] == "nope"


def test_record_step_thinking_coalesces():
    steps: list[dict] = []
    _record_step(steps, "thinking", {"text": "Let me "})
    _record_step(steps, "thinking", {"text": "think…"})
    assert steps == [{"kind": "thinking", "text": "Let me think…"}]
    # A non-thinking event breaks the run; the next thinking starts a new entry.
    _record_step(steps, "tool_started", {"tool": "t", "args": {}})
    _record_step(steps, "thinking", {"text": "more"})
    assert steps[-1] == {"kind": "thinking", "text": "more"}
    assert sum(1 for s in steps if s["kind"] == "thinking") == 2


# ── provider harnesses ───────────────────────────────────────────────────────

class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        resp = self._responses.pop(0)
        if stream and on_token and resp.content:
            on_token(resp.content)
        return resp


class ThinkingProvider(Provider):
    """Streams a reasoning delta before the visible answer (like a reasoning model)."""
    name = "thinker"

    def __init__(self, thought, answer):
        super().__init__(model="thinker")
        self._thought, self._answer = thought, answer

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        if on_thinking:
            on_thinking(self._thought)
        if on_token and self._answer:
            on_token(self._answer)
        return LLMResponse(content=self._answer)


def _agent(provider, registry=None):
    db = Database(":memory:")
    agent = Agent(provider, registry or ToolRegistry(), db, load_persona())
    return agent, db


# ── steps collected on the turn + persisted ──────────────────────────────────

def test_steps_collected_and_persisted():
    reg = ToolRegistry()
    reg.register("echo", "echo", {"type": "object", "properties": {"x": {"type": "string"}}},
                 lambda a: f"echoed {a.get('x')}")
    responses = [
        LLMResponse(content="On it.", tool_calls=[ToolCall(id="t1", name="echo", args={"x": "hi"})]),
        LLMResponse(content="Done."),
    ]
    agent, db = _agent(ScriptedProvider(responses), registry=reg)
    result = agent.process_turn("echo hi")

    kinds = [s["kind"] for s in result.steps]
    assert "preamble" in kinds and "tool" in kinds
    tool_step = next(s for s in result.steps if s["kind"] == "tool")
    assert tool_step["tool"] == "echo" and tool_step["state"] == "ok"

    # Persisted to the assistant turn's meta so a reload restores them.
    turns = db.session_turns(result.session_id)
    assistant = next(t for t in turns if t["role"] == "assistant")
    assert (assistant.get("meta") or {}).get("steps")
    assert any(s["kind"] == "tool" for s in assistant["meta"]["steps"])


def test_thinking_streams_to_event_and_steps():
    agent, _ = _agent(ThinkingProvider("pondering…", "The answer."))
    events: list[tuple] = []
    result = agent.process_turn("q", on_token=lambda t: None,
                                emit=lambda e, p: events.append((e, p)))
    assert result.content == "The answer."
    # A thinking event was emitted, and it landed in the persisted steps.
    assert any(e == "thinking" for e, _ in events)
    assert any(s["kind"] == "thinking" and "pondering" in s["text"] for s in result.steps)


def test_no_steps_when_plain_chat():
    """A bare answer with no tools/thinking carries no activity timeline."""
    agent, db = _agent(ScriptedProvider([LLMResponse(content="hello")]))
    result = agent.process_turn("hi")
    assert result.steps == []
    turns = db.session_turns(result.session_id)
    assistant = next(t for t in turns if t["role"] == "assistant")
    assert "steps" not in (assistant.get("meta") or {})


# ── openai_compat surfaces reasoning_content on the thinking channel ──────────

def test_openai_compat_reasoning_to_thinking():
    from namma_agent.core.providers.openai_compat import OpenAICompatProvider

    def _chunk(content=None, reasoning=None, finish=None):
        delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=None)
        choice = SimpleNamespace(delta=delta, finish_reason=finish)
        return SimpleNamespace(choices=[choice], usage=None)

    class FakeClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**body):
                    return iter([
                        _chunk(reasoning="thinking hard"),
                        _chunk(content="hello"),
                        _chunk(finish="stop"),
                    ])

    prov = OpenAICompatProvider(model="x", base_url="http://local", api_key="k")
    tokens, thoughts = [], []
    resp = prov._generate_stream(FakeClient(), {"messages": []},
                                 on_token=tokens.append, on_thinking=thoughts.append)
    assert resp.content == "hello"
    assert tokens == ["hello"]
    assert thoughts == ["thinking hard"]
