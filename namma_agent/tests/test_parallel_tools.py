"""Phase 4: read-only tool calls of one model step run in parallel; anything
with side effects keeps strict order."""
from __future__ import annotations

import threading
import time

from namma_agent.core.agent import PARALLEL_SAFE_TOOLS, Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry

_OBJ = {"type": "object", "properties": {}}


class Scripted(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="s")
        self._r = list(responses)
        self.seen = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen.append(list(messages))
        return self._r.pop(0)


def _registry(log):
    reg = ToolRegistry()
    lock = threading.Lock()
    state = {"active": 0, "max": 0}

    def slow(name):
        def run(args):
            with lock:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            time.sleep(0.3)
            with lock:
                state["active"] -= 1
            log.append(name)
            return f"{name} result"
        return run

    for name in ("read_file", "web_search", "list_dir"):
        reg.register(name, name, _OBJ, slow(name))
    reg.register("open_app", "Open.", _OBJ, slow("open_app"))      # side effect
    return reg, state


def _calls(*names):
    return [ToolCall(id=f"c{i}", name=n, args={}) for i, n in enumerate(names)]


def test_read_only_batch_runs_concurrently_and_keeps_transcript_order():
    log = []
    reg, state = _registry(log)
    prov = Scripted([LLMResponse(content="", tool_calls=_calls("read_file", "web_search",
                                                                "list_dir")),
                     LLMResponse(content="done")])
    agent = Agent(prov, reg, Database(":memory:"), load_persona())
    events = []
    t0 = time.monotonic()
    res = agent.process_turn("go", emit=lambda e, p: events.append((e, p)))
    elapsed = time.monotonic() - t0
    assert res.content == "done"
    assert state["max"] == 3 and elapsed < 0.8            # 3 × 0.3 s sequentially = 0.9 s
    tool_msgs = [m for m in prov.seen[1] if m.get("role") == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["c0", "c1", "c2"]
    assert [m["content"] for m in tool_msgs] == ["read_file result", "web_search result",
                                                 "list_dir result"]
    assert res.tools_used == ["read_file", "web_search", "list_dir"]
    started = [p for e, p in events if e == "tool_started"]
    assert all(p.get("parallel") for p in started) and len(started) == 3
    assert sum(1 for e, _ in events if e == "tool_finished") == 3


def test_a_batch_with_a_side_effect_runs_in_order():
    log = []
    reg, state = _registry(log)
    prov = Scripted([LLMResponse(content="", tool_calls=_calls("read_file", "open_app",
                                                                "list_dir")),
                     LLMResponse(content="done")])
    Agent(prov, reg, Database(":memory:"), load_persona()).process_turn("go")
    assert state["max"] == 1
    assert log == ["read_file", "open_app", "list_dir"]


def test_single_calls_are_not_parallelised():
    log = []
    reg, state = _registry(log)
    prov = Scripted([LLMResponse(content="", tool_calls=_calls("read_file")),
                     LLMResponse(content="done")])
    events = []
    Agent(prov, reg, Database(":memory:"), load_persona()).process_turn(
        "go", emit=lambda e, p: events.append((e, p)))
    assert not any(p.get("parallel") for e, p in events if e == "tool_started")


def test_allowlist_has_no_side_effecting_tools():
    for name in ("open_app", "memory_save", "update_todos", "render_diagram", "write_file",
                 "run_shell", "send_notification", "delegate_task", "background_task"):
        assert name not in PARALLEL_SAFE_TOOLS
