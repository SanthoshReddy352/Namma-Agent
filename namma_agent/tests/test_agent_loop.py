"""Phase 2 tests — the agent loop (tool calling, persistence, events)."""
from __future__ import annotations

from namma_agent.core.agent import Agent
from namma_agent.core.builtins import register_memory_tools
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry, ToolResult


class ScriptedProvider(Provider):
    """Returns a queued list of responses, one per generate() call."""

    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)
        self.seen_messages = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen_messages.append(list(messages))
        resp = self._responses.pop(0)
        if stream and on_token and resp.content:
            on_token(resp.content)
        return resp


def _agent(responses, registry=None):
    db = Database(":memory:")
    reg = registry or ToolRegistry()
    events = []
    agent = Agent(ScriptedProvider(responses), reg, db, load_persona(),
                  emit=lambda e, p: events.append((e, p)))
    return agent, db, events


def test_plain_chat_turn_persists():
    agent, db, events = _agent([LLMResponse(content="Hello!")])
    result = agent.process_turn("hi")
    assert result.content == "Hello!"
    turns = db.recent_turns(result.session_id)
    assert turns == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "Hello!"},
    ]
    assert ("turn_completed", events[-1][1]) == ("turn_completed", events[-1][1])
    assert events[-1][0] == "turn_completed"


def test_tool_call_executes_and_feeds_back():
    reg = ToolRegistry()
    calls = {}

    def echo(args):
        calls["args"] = args
        return f"echoed:{args.get('x')}"

    reg.register("echo", "echo a value", {
        "type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"],
    }, echo)

    responses = [
        LLMResponse(content="On it.", tool_calls=[ToolCall(id="t1", name="echo", args={"x": "hi"})]),
        LLMResponse(content="Done — got hi."),
    ]
    agent, db, events = _agent(responses, registry=reg)
    result = agent.process_turn("echo hi")

    assert calls["args"] == {"x": "hi"}
    # The visible answer keeps the whole turn: the "On it." preamble that came with
    # the tool call (otherwise lost) plus the closing answer.
    assert result.content == "On it.\n\nDone — got hi."
    assert result.tools_used == ["echo"]
    # preamble + tool_started + tool_finished emitted
    kinds = [e for e, _ in events]
    assert "preamble" in kinds and "tool_started" in kinds and "tool_finished" in kinds
    # the second generate() call saw the tool result in its messages
    second_call = agent.provider.seen_messages[1]
    assert any(m.get("role") == "tool" and m.get("content") == "echoed:hi" for m in second_call)


def test_unknown_tool_returns_error_to_model():
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="nope", args={})]),
        LLMResponse(content="Recovered."),
    ]
    agent, db, events = _agent(responses)
    result = agent.process_turn("do nope")
    assert result.content == "Recovered."
    second_call = agent.provider.seen_messages[1]
    tool_msg = [m for m in second_call if m.get("role") == "tool"][0]
    assert "ERROR: Unknown tool" in tool_msg["content"]


def test_loop_limit_guard():
    # Always returns a tool call -> must terminate at the limit, not hang.
    looping = [
        LLMResponse(tool_calls=[ToolCall(id=f"t{i}", name="echo", args={})])
        for i in range(20)
    ]
    reg = ToolRegistry()
    reg.register("echo", "e", {"type": "object", "properties": {}}, lambda a: "ok")
    agent, db, events = _agent(looping, registry=reg)
    agent.tool_loop_limit = 3
    result = agent.process_turn("loop forever")
    assert result.content  # produced a fallback message
    assert result.tools_used.count("echo") == 3


def test_memory_tools_via_agent():
    reg = ToolRegistry()
    db = Database(":memory:")
    register_memory_tools(reg, db)
    responses = [
        LLMResponse(content="Saving.", tool_calls=[
            ToolCall(id="t1", name="remember_fact", args={"key": "editor", "value": "vim"})]),
        LLMResponse(content="Saved your editor as vim."),
    ]
    agent = Agent(ScriptedProvider(responses), reg, db, load_persona())
    agent.process_turn("remember my editor is vim")
    assert db.get_fact("editor") == "vim"


def test_facts_injected_into_system_prompt():
    db = Database(":memory:")
    db.save_fact("name", "Tricky")
    reg = ToolRegistry()
    agent = Agent(ScriptedProvider([LLMResponse(content="hi Tricky")]), reg, db, load_persona())
    agent.process_turn("who am i")
    system = agent.provider.seen_messages[0][0]
    assert system["role"] == "system"
    assert "Tricky" in system["content"]
    assert "USER_FACTS" in system["content"]


def test_media_tool_output_surfaced_in_answer():
    """Diagrams/images a tool generates must appear in the visible answer even
    when the model doesn't re-paste the markdown (regression: learning chats
    showed only the closing line, no diagram)."""
    reg = ToolRegistry()
    md = "![Gear ratio](/api/media/diagrams/abc.png)\n\n*Gear ratio* · [⬇ Download](/api/media/diagrams/abc.png)"
    reg.register("render_diagram", "draw", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=md, data={"url": "/api/media/diagrams/abc.png", "kind": "diagram"}))
    responses = [
        LLMResponse(content="Here's how gears trade speed for force.",
                    tool_calls=[ToolCall(id="d1", name="render_diagram", args={})]),
        LLMResponse(content="What would you pick?"),
    ]
    agent, db, _ = _agent(responses, registry=reg)
    result = agent.process_turn("teach me")
    # explanation + the diagram markdown + closing line all present, in order
    assert "Here's how gears trade speed for force." in result.content
    assert "/api/media/diagrams/abc.png" in result.content
    assert result.content.strip().endswith("What would you pick?")
    # and it persisted (reload-safe)
    assert "/api/media/diagrams/abc.png" in db.recent_turns(result.session_id)[-1]["content"]


def test_media_streamed_inline_in_order():
    """The generated media markdown is placed into the LIVE token stream at the exact
    point the tool finished — so the diagram appears in order (preamble, diagram,
    closing line), before the rest of the reply keeps streaming, and matches the
    canonical/persisted answer. (It doesn't flicker because the chat memoises each
    <img> on its src across re-parses.)"""
    reg = ToolRegistry()
    media_md = "![Water cycle](/api/media/diagrams/x.png)\n\n*Water cycle* · [⬇ Download](/api/media/diagrams/x.png)"

    reg.register("draw", "draw a diagram", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=media_md, data={"url": "/api/media/diagrams/x.png"}))

    responses = [
        LLMResponse(content="Here's the picture:",
                    tool_calls=[ToolCall(id="t1", name="draw", args={})]),
        LLMResponse(content="And that's the cycle."),
    ]
    agent, db, _events = _agent(responses, registry=reg)
    chunks = []
    result = agent.process_turn("show me", on_token=chunks.append)

    # The image markdown is in the canonical/persisted answer, in order …
    assert result.content == f"Here's the picture:\n\n{media_md}\n\nAnd that's the cycle."
    # … and it was pushed through the token stream in place (between the preamble and
    # the closing line) so the learner sees it appear where it belongs.
    streamed = "".join(chunks)
    assert "/api/media/diagrams/x.png" in streamed
    assert streamed.index("Here's the picture:") < streamed.index("/api/media/diagrams/x.png") < streamed.index("And that's the cycle.")


def test_turn_reports_ttft_and_summed_tokens():
    """A streamed turn records time-to-first-token and sums token usage across every
    model call (here: a tool round + the final answer)."""
    reg = ToolRegistry()
    reg.register("noop", "noop", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="done"))
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="noop", args={})],
                    usage={"input_tokens": 100, "output_tokens": 20}),
        LLMResponse(content="All set.", usage={"input_tokens": 130, "output_tokens": 8}),
    ]
    agent, _db, _ = _agent(responses, registry=reg)
    result = agent.process_turn("go", on_token=lambda _t: None)
    assert result.ttft is not None and result.ttft >= 0
    # 100+20 + 130+8 summed across both generations
    assert result.usage == {"input_tokens": 230, "output_tokens": 28}


def test_cache_reads_excluded_from_headline_tokens():
    """The headline token total must count only genuinely-new work (fresh input +
    cache writes + output) — NOT the prompt prefix re-read from cache on every
    tool-loop step. Counting cache reads is exactly the bug that ballooned a ~108K
    turn into a reported 3.1M."""
    reg = ToolRegistry()
    reg.register("noop", "noop", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="done"))
    # Step 1 writes the prefix to cache; step 2 re-reads it cheaply and adds a small
    # delta. Naive summing of all input would report 1000+50000 = 51,000 input tokens;
    # the honest headline is 1000(write) + 200(fresh) + 30(out) = 1,230.
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="noop", args={})],
                    usage={"input_tokens": 100, "output_tokens": 20,
                           "cache_write_tokens": 1000}),
        LLMResponse(content="All set.",
                    usage={"input_tokens": 100, "output_tokens": 10,
                           "cache_read_tokens": 50000}),
    ]
    agent, db, _ = _agent(responses, registry=reg)
    result = agent.process_turn("go", on_token=lambda _t: None)
    # Full breakdown is summed and preserved…
    assert result.usage == {"input_tokens": 200, "output_tokens": 30,
                            "cache_write_tokens": 1000, "cache_read_tokens": 50000}
    # …but the persisted headline excludes the 50K of cache re-reads.
    asst = [t for t in db.session_turns(result.session_id) if t["role"] == "assistant"][-1]
    assert asst["meta"]["tokens"] == 1230
    assert asst["meta"]["cached"] == 50000


def test_turn_stats_persist_in_db():
    """Per-turn stats are saved with the assistant turn (so they survive a reload):
    session_turns returns the meta {ttft, tokens} for that turn."""
    responses = [LLMResponse(content="Hi there.", usage={"input_tokens": 10, "output_tokens": 4})]
    agent, db, _ = _agent(responses)
    result = agent.process_turn("hello", on_token=lambda _t: None)
    asst = [t for t in db.session_turns(result.session_id) if t["role"] == "assistant"][-1]
    assert asst["meta"]["tokens"] == 14
    assert asst["meta"]["ttft"] is not None


def test_ttft_is_none_when_not_streamed():
    """Non-streamed turns (no on_token — e.g. Telegram) report no first-token time."""
    agent, _db, _ = _agent([LLMResponse(content="hi", usage={"input_tokens": 5, "output_tokens": 2})])
    result = agent.process_turn("hello")
    assert result.ttft is None
    assert result.usage == {"input_tokens": 5, "output_tokens": 2}


class CharStreamProvider(Provider):
    """Streams each response one character at a time, to exercise the live media
    filter's incremental holding (a phantom link arrives across many tokens)."""

    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._r = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        resp = self._r.pop(0)
        if stream and on_token and resp.content:
            for ch in resp.content:
                on_token(ch)
        return resp


def test_stream_media_filter_holds_and_strips_phantom():
    """Unit: the live filter never emits a phantom /api/media/ link even when fed one
    character at a time, and passes ordinary text (and the stray '!') through."""
    from namma_agent.core.agent import _StreamMediaFilter

    out = []
    f = _StreamMediaFilter(out.append)
    for ch in "See ![X](/api/media/diagrams/nope.png) and wow! done":
        f(ch)
    f.flush()
    streamed = "".join(out)
    assert "/api/media/" not in streamed     # the broken image never streamed
    assert "See " in streamed and "wow!" in streamed and "done" in streamed


def test_streamed_phantom_link_is_filtered_live():
    """Integration: a model that writes a phantom image link in its prose never
    flickers an 'unavailable' image — the link is gone from the live token stream and
    from the final answer."""
    db = Database(":memory:")
    content = "Here's a diagram:\n\n![X](/api/media/diagrams/nope-live.png)\n\nThat's it."
    agent = Agent(CharStreamProvider([LLMResponse(content=content)]),
                  ToolRegistry(), db, load_persona())
    chunks = []
    result = agent.process_turn("teach", on_token=chunks.append)
    streamed = "".join(chunks)
    assert "/api/media/" not in streamed
    assert "Here's a diagram:" in streamed and "That's it." in streamed
    assert "/api/media/" not in result.content


def test_phantom_media_link_is_stripped():
    """If the model writes an /api/media image link in its OWN prose (no render tool
    ran, so the file doesn't exist), it must not leave a broken/"unavailable" image —
    the phantom link is stripped, surrounding text kept."""
    agent, db, _ = _agent([LLMResponse(
        content="Here's a diagram:\n\n![X](/api/media/diagrams/does-not-exist-xyz.png)\n\nThat's it.")])
    result = agent.process_turn("teach")
    assert "/api/media/diagrams/does-not-exist-xyz.png" not in result.content
    assert "Here's a diagram:" in result.content and "That's it." in result.content


def test_phantom_diagram_block_fully_stripped():
    """A fabricated diagram block — the image line PLUS the orphan
    '*caption* · [⬇ Download diagram](…)' line — is removed whole: no broken image,
    no dangling caption, no dead download link, surrounding prose kept."""
    content = (
        "Here's what that looks like visually:\n\n"
        "![if-elif-else decision flow](/api/media/diagrams/phantom123.png)\n\n"
        "*if-elif-else decision flow* · [⬇ Download diagram](/api/media/diagrams/phantom123.png)\n\n"
        "Key thing: indentation matters.")
    agent, db, _ = _agent([LLMResponse(content=content)])
    result = agent.process_turn("teach")
    assert "/api/media/" not in result.content
    assert "⬇" not in result.content and "Download diagram" not in result.content
    assert "if-elif-else decision flow" not in result.content  # orphan caption gone too
    assert "Here's what that looks like visually:" in result.content
    assert "Key thing: indentation matters." in result.content


def test_does_not_duplicate_repeated_media():
    """A tool returning the same media URL twice is shown once in the final answer."""
    reg = ToolRegistry()
    media_md = "![d](/api/media/diagrams/same.png)"
    reg.register("draw", "draw", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content=media_md, data={"url": "/api/media/diagrams/same.png"}))
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="draw", args={}),
                                ToolCall(id="t2", name="draw", args={})]),
        LLMResponse(content="Done."),
    ]
    agent, db, _events = _agent(responses, registry=reg)
    chunks = []
    result = agent.process_turn("draw twice", on_token=chunks.append)
    assert result.content.count("same.png") == 1
    # placed into the stream exactly once too — the dedup guard keeps the repeated
    # render from streaming a second copy.
    assert "".join(chunks).count("same.png") == 1


# ── provider hard-timeout (a stuck model can't freeze the turn forever) ───────

def test_generate_bounded_times_out_on_a_stuck_provider():
    import threading

    from namma_agent.core import agent as agent_mod
    from namma_agent.core.providers.base import ProviderError

    class _Stuck:
        def generate(self, **kwargs):
            threading.Event().wait()  # blocks forever — simulates a hung stream

    import pytest
    with pytest.raises(ProviderError, match="didn't respond"):
        agent_mod._generate_bounded(_Stuck(), 0.2, messages=[])


def test_generate_bounded_propagates_result_and_errors():
    from namma_agent.core import agent as agent_mod

    class _Ok:
        def generate(self, **kwargs):
            return "RESULT"

    assert agent_mod._generate_bounded(_Ok(), 1.0, messages=[]) == "RESULT"

    class _Bad:
        def generate(self, **kwargs):
            raise ValueError("boom")

    import pytest
    with pytest.raises(ValueError, match="boom"):
        agent_mod._generate_bounded(_Bad(), 1.0, messages=[])


def test_generate_timeout_scales_with_provider_and_has_a_floor():
    from namma_agent.core import agent as agent_mod

    class _P:
        timeout_s = 60.0
        max_retries = 3

    assert agent_mod._generate_timeout(_P()) == 60.0 * 4 + 30.0

    class _Pmin:
        timeout_s = 5.0
        max_retries = 0

    assert agent_mod._generate_timeout(_Pmin()) == 120.0  # floor
