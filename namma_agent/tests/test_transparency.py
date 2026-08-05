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
    # The reasoning is captured in full so the next loop step can echo it back.
    assert resp.reasoning_content == "thinking hard"


def test_openai_compat_non_streamed_captures_reasoning():
    from namma_agent.core.providers.openai_compat import OpenAICompatProvider

    class FakeClient:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**body):
                    message = SimpleNamespace(content="answer", reasoning_content="deep thought",
                                              tool_calls=[])
                    choice = SimpleNamespace(message=message, finish_reason="stop")
                    return SimpleNamespace(choices=[choice], usage=None)

    prov = OpenAICompatProvider(model="x", base_url="http://local", api_key="k")
    resp = prov._generate_once(FakeClient(), {"messages": []})
    assert resp.content == "answer"
    assert resp.reasoning_content == "deep thought"


def test_openai_compat_wire_echos_reasoning_content():
    from namma_agent.core.providers.openai_compat import OpenAICompatProvider

    messages = [
        {"role": "assistant", "content": "On it.",
         "reasoning_content": "pondering…",
         "tool_calls": [ToolCall(id="c1", name="echo", args={"x": 1})]},
        {"role": "tool", "tool_call_id": "c1", "name": "echo", "content": "ok"},
    ]
    wire = OpenAICompatProvider._to_wire_messages(messages)
    assert wire[0]["reasoning_content"] == "pondering…"
    assert wire[0]["tool_calls"][0]["id"] == "c1"
    # A reasoning-only assistant turn (no tool calls) keeps the field too.
    wire2 = OpenAICompatProvider._to_wire_messages(
        [{"role": "assistant", "content": "", "reasoning_content": "pondering…"}])
    assert wire2[0]["reasoning_content"] == "pondering…"
    # And the field is never invented for non-reasoning turns.
    wire3 = OpenAICompatProvider._to_wire_messages(
        [{"role": "assistant", "content": "hi", "tool_calls": [ToolCall(id="c2", name="t", args={})]}])
    assert "reasoning_content" not in wire3[0]


def test_openai_compat_wire_never_emits_null_content_assistant():
    """An assistant turn with empty content must translate to content='' — a
    null content with no tool_calls is rejected by the endpoint."""
    from namma_agent.core.providers.openai_compat import OpenAICompatProvider

    wire = OpenAICompatProvider._to_wire_messages(
        [{"role": "assistant", "content": ""}])
    assert wire[0]["content"] == ""
    assert wire[0]["content"] is not None
    wire2 = OpenAICompatProvider._to_wire_messages(
        [{"role": "assistant", "content": ""},
         {"role": "assistant", "content": "", "tool_calls": [ToolCall(id="c1", name="t", args={})]}])
    assert wire2[0]["content"] == ""
    assert wire2[1]["content"] == ""


def test_openai_compat_wire_fills_reasoning_holes_in_thinking_mode():
    """Once a conversation carries reasoning_content (thinking mode), EVERY
    assistant message must keep the field — empty when the model happened to
    produce no reasoning on that turn. Otherwise the upstream intermittently
    400s: 'The reasoning_content in the thinking mode must be passed back'.
    """
    from namma_agent.core.providers.openai_compat import OpenAICompatProvider

    messages = [
        {"role": "assistant", "content": "On it.",
         "reasoning_content": "pondering…",
         "tool_calls": [ToolCall(id="c1", name="echo", args={"x": 1})]},
        {"role": "tool", "tool_call_id": "c1", "name": "echo", "content": "ok"},
        # A reasoning-less assistant turn mid-conversation leaves a hole — the
        # wire must still carry reasoning_content (empty), not drop the key.
        {"role": "assistant", "content": "",
         "tool_calls": [ToolCall(id="c2", name="echo", args={"x": 2})]},
    ]
    wire = OpenAICompatProvider._to_wire_messages(messages)
    assert wire[0]["reasoning_content"] == "pondering…"
    assert "reasoning_content" in wire[2]
    assert wire[2]["reasoning_content"] == ""
    # A reasoning-less conversation stays untouched (no field invented).
    wire2 = OpenAICompatProvider._to_wire_messages(
        [{"role": "assistant", "content": "hi", "tool_calls": [ToolCall(id="c3", name="t", args={})]}])
    assert "reasoning_content" not in wire2[0]


# ── the agent loop echoes reasoning back on the next step ─────────────────────

class ReasoningEchoProvider(Provider):
    """Returns reasoning + a tool call first, then inspects what the agent
    actually sent back on the follow-up step (like DeepSeek-R1 endpoints)."""
    name = "reason_echo"

    def __init__(self):
        super().__init__(model="reason_echo")
        self.seen: list[list[dict]] = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen.append(messages)
        if len(self.seen) == 1:
            return LLMResponse(content="Using echo.",
                               tool_calls=[ToolCall(id="t1", name="echo", args={"x": "hi"})],
                               reasoning_content="pondering…")
        return LLMResponse(content="All good.")


def test_agent_echoes_reasoning_content_after_tool_step():
    reg = ToolRegistry()
    reg.register("echo", "echo", {"type": "object", "properties": {"x": {"type": "string"}}},
                 lambda a: f"echoed {a.get('x')}")
    provider = ReasoningEchoProvider()
    agent, _ = _agent(provider, registry=reg)
    result = agent.process_turn("echo hi")
    assert result.content == "All good."
    assert len(provider.seen) == 2
    assistant_turn = next(m for m in provider.seen[1] if m["role"] == "assistant")
    assert assistant_turn["reasoning_content"] == "pondering…"
    assert assistant_turn["tool_calls"][0].name == "echo"


# ── an empty response mid-task is never silently final ───────────────────────

def test_empty_response_mid_task_nudges_then_finishes():
    """A reasoning model that burns its budget thinking (empty content, no tool
    calls, finish_reason='length') must be nudged to continue, not end the turn
    with a blank bubble."""
    reg = ToolRegistry()
    reg.register("echo", "echo", {"type": "object", "properties": {"x": {"type": "string"}}},
                 lambda a: f"echoed {a.get('x')}")
    responses = [
        LLMResponse(content="On it.", tool_calls=[ToolCall(id="t1", name="echo", args={"x": "hi"})]),
        LLMResponse(content="", finish_reason="length"),   # budget exhausted mid-thought
        LLMResponse(content="All good."),
    ]
    agent, _ = _agent(ScriptedProvider(responses), registry=reg)
    result = agent.process_turn("do the thing")
    assert result.content == "All good."


def test_two_empty_responses_fail_loudly():
    import pytest
    from namma_agent.core.providers.base import ProviderError

    responses = [
        LLMResponse(content="", finish_reason="length"),
        LLMResponse(content="", finish_reason="length"),
    ]
    agent, _ = _agent(ScriptedProvider(responses))
    with pytest.raises(ProviderError):
        agent.process_turn("do the thing")


def test_empty_nudge_leaves_no_invalid_assistant_turn():
    """The nudge after an empty response must NOT record the content-less
    assistant turn — the endpoint rejects it ('content or tool_calls must be
    set'). The follow-up request may only carry user/user + the nudge."""
    seen: list[list[dict]] = []

    class InspectProvider(Provider):
        name = "inspector"

        def __init__(self):
            super().__init__(model="inspector")

        def is_available(self):
            return True

        def generate(self, messages, tools=None, stream=False, on_token=None,
                     on_thinking=None):
            seen.append(messages)
            if len(seen) == 1:
                return LLMResponse(content="", finish_reason="length")
            return LLMResponse(content="Done.")

    agent, _ = _agent(InspectProvider())
    result = agent.process_turn("do the thing")
    assert result.content == "Done."
    follow_up = seen[1]
    # No assistant turn without content crept into the follow-up request…
    assert not any(m.get("role") == "assistant" and not m.get("content")
                   for m in follow_up)
    # …but the nudge itself did.
    assert any(m.get("role") == "user" and "empty" in m.get("content", "")
               for m in follow_up)
