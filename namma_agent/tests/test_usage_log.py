"""Phase 2: cache-stable prompt, per-request usage log, background-call
attribution and the per-turn token budget."""
from __future__ import annotations

import threading
from datetime import datetime

import pytest

from namma_agent.core import usage as usage_mod
from namma_agent.core.agent import Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import date_line, load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.providers.registry import ProviderChain
from namma_agent.core.tools import ToolRegistry


class MeteredProvider(Provider):
    name = "metered"

    def __init__(self, responses, usage=None):
        super().__init__(model="m-1")
        self._responses = list(responses)
        self._usage = usage or {"input_tokens": 100, "output_tokens": 10,
                                "cache_read_tokens": 900, "cache_write_tokens": 0}
        self.seen: list[list[dict]] = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen.append(list(messages))
        resp = self._responses.pop(0) if self._responses else LLMResponse(content="done")
        resp.usage = dict(self._usage)
        return resp


@pytest.fixture
def db():
    d = Database(":memory:")
    usage_mod.set_sink(d)
    yield d
    usage_mod.set_sink(None)


def _registry():
    reg = ToolRegistry()
    reg.register("ping", "Ping.", {"type": "object", "properties": {}}, lambda a: "pong")
    return reg


# ── cache-stable prompt ──────────────────────────────────────────────────────

def test_system_prompt_has_no_clock_and_is_stable_across_turns(db):
    agent = Agent(MeteredProvider([]), _registry(), db, load_persona())
    sid = db.create_session()
    first = agent._build_messages("hello", sid)
    second = agent._build_messages("something else entirely", sid)
    assert first[0]["content"] == second[0]["content"]   # byte-identical system prompt
    sys_text = first[0]["content"]
    assert "CURRENT DATE & TIME" in sys_text
    assert datetime.now().strftime("%H:%M") not in sys_text  # no minute stamp


def test_date_rides_the_latest_user_message_at_day_resolution(db):
    agent = Agent(MeteredProvider([]), _registry(), db, load_persona())
    sid = db.create_session()
    msgs = agent._build_messages("what's new?", sid)
    last = msgs[-1]["content"]
    assert last.startswith("<context>\n")
    assert date_line() in last and last.endswith("what's new?")
    assert str(datetime.now().year) in last


def test_date_line_format():
    line = date_line(datetime(2026, 6, 20, 14, 30))
    assert line.startswith("Today: Saturday, 20 June 2026")
    assert "14:30" not in line


def test_turn_context_is_not_persisted(db):
    agent = Agent(MeteredProvider([LLMResponse(content="hi there")]), _registry(), db,
                  load_persona())
    res = agent.process_turn("hello")
    rows = db.recent_turns(res.session_id, 10)
    assert rows[0]["content"] == "hello"            # raw text in the transcript


def test_openai_prompt_cache_key_only_for_native_openai():
    from namma_agent.core.interactive import set_current_session
    from namma_agent.core.providers.openai_compat import OpenAICompatProvider
    from namma_agent.core.providers.openai_provider import OpenAIProvider

    set_current_session("abc123session")
    try:
        assert OpenAIProvider(model="gpt-5", api_key="x")._prompt_cache_key() \
            == "namma-abc123session"
        assert OpenAICompatProvider(model="llama", api_key="x",
                                    base_url="http://localhost:11434/v1")._prompt_cache_key() == ""
        assert OpenAIProvider(model="gpt-5", api_key="x",
                              base_url="https://proxy.example/v1")._prompt_cache_key() == ""
    finally:
        set_current_session(None)


# ── usage log ────────────────────────────────────────────────────────────────

def test_every_loop_step_is_logged_with_kind_step_and_session(db):
    prov = MeteredProvider([
        LLMResponse(content="", tool_calls=[ToolCall(id="1", name="ping", args={})]),
        LLMResponse(content="all done"),
    ])
    agent = Agent(prov, _registry(), db, load_persona())
    res = agent.process_turn("ping it")
    rows = list(reversed(db.usage_requests(session_id=res.session_id)))
    assert [r["step"] for r in rows] == [1, 2]
    assert {r["kind"] for r in rows} == {"turn"}
    assert rows[0]["provider"] == "metered" and rows[0]["model"] == "m-1"
    assert rows[0]["cache_read_tokens"] == 900


def test_background_calls_are_attributed_by_label(db):
    prov = MeteredProvider([LLMResponse(content="t")] * 3)
    usage_mod.labeled(prov, "title").generate([{"role": "user", "content": "x"}])
    with usage_mod.usage_scope("compaction"):
        prov.generate([{"role": "user", "content": "x"}])
    prov.generate([{"role": "user", "content": "x"}])     # unlabeled
    kinds = sorted(r["kind"] for r in db.usage_requests())
    assert kinds == ["background", "compaction", "title"]


def test_labeled_provider_proxies_attributes():
    prov = MeteredProvider([])
    lab = usage_mod.labeled(prov, "memory")
    assert lab.model == "m-1" and lab.is_available()
    lab.tool_allow = ["x"]
    assert prov.tool_allow == ["x"]
    assert usage_mod.labeled(lab, "title")._inner is prov   # no double wrapping
    assert usage_mod.labeled(None, "title") is None


def test_chain_counts_each_call_once(db):
    inner = MeteredProvider([LLMResponse(content="ok")])
    ProviderChain([inner]).generate([{"role": "user", "content": "x"}])
    assert len(db.usage_requests()) == 1


def test_label_survives_the_generate_worker_thread(db):
    """The agent runs generate on a worker thread; attribution must follow it."""
    from namma_agent.core.agent import _generate_bounded

    prov = MeteredProvider([LLMResponse(content="ok")])
    with usage_mod.usage_scope("watcher", step=3):
        _generate_bounded(prov, 10, messages=[{"role": "user", "content": "x"}])
    row = db.usage_requests()[0]
    assert (row["kind"], row["step"]) == ("watcher", 3)


def test_compaction_call_is_logged_as_compaction(db):
    from namma_agent.core.agent import _COMPACT_BATCH

    prov = MeteredProvider([LLMResponse(content="summary")])
    agent = Agent(prov, _registry(), db, load_persona(), max_history_turns=2)
    sid = db.create_session()
    for i in range(_COMPACT_BATCH + 4):
        db.add_turn(sid, "user" if i % 2 == 0 else "assistant", f"m{i}")
    t = agent._schedule_compaction(sid, prov)
    assert isinstance(t, threading.Thread)
    t.join(timeout=5)
    assert [r["kind"] for r in db.usage_requests()] == ["compaction"]


def test_breakdown_reports_cache_read_ratio(db):
    db.log_usage(kind="turn", usage={"input_tokens": 100, "cache_read_tokens": 300,
                                     "output_tokens": 5})
    db.log_usage(kind="memory", usage={"input_tokens": 100, "output_tokens": 5})
    db.log_usage(kind="turn", usage={})      # empty usage is not stored
    out = db.usage_breakdown(days=1)
    assert out["total"]["calls"] == 2
    assert out["total"]["cache_read_ratio"] == 0.6
    assert {k["kind"] for k in out["kinds"]} == {"turn", "memory"}


def test_status_and_endpoint_expose_the_breakdown(db):
    from fastapi.testclient import TestClient

    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=MeteredProvider([LLMResponse(content="hi")]),
                            registry=_registry(), db=db)
    svc.agent.process_turn("hello")
    status = svc.background_status()
    assert status["usage"]["requests"]["total"]["calls"] == 1
    client = TestClient(create_app(svc))
    body = client.get("/api/usage/requests?limit=5").json()
    assert body["requests"][0]["kind"] == "turn"
    assert body["breakdown"]["total"]["cache_read_ratio"] == 0.9


# ── per-turn budget ──────────────────────────────────────────────────────────

def test_turn_budget_stops_before_the_next_tool_round(db):
    calls = [LLMResponse(content="", tool_calls=[ToolCall(id=str(i), name="ping", args={})])
             for i in range(5)]
    prov = MeteredProvider(calls, usage={"input_tokens": 600, "output_tokens": 0})
    agent = Agent(prov, _registry(), db, load_persona())
    agent.turn_token_budget = 1000
    events = []
    res = agent.process_turn("loop forever", emit=lambda e, p: events.append(e))
    assert len(prov.seen) == 2                       # 600 → 1200 ≥ 1000 → stop
    assert res.tools_used == ["ping"]
    assert "turn_budget_exceeded" in events
    assert "budget" in res.content


def test_turn_budget_zero_means_off(db):
    calls = [LLMResponse(content="", tool_calls=[ToolCall(id="1", name="ping", args={})]),
             LLMResponse(content="fin")]
    prov = MeteredProvider(calls, usage={"input_tokens": 10**6})
    agent = Agent(prov, _registry(), db, load_persona())
    assert agent.process_turn("go").content == "fin"
