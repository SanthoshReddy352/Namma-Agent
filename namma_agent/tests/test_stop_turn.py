"""Stop really stops (PROGRESS.md BUG-19).

Reported: pressing Stop mid-turn showed "stopped" in the UI while the model kept
working and finished the whole task; an immediate new prompt then ran a SECOND
turn concurrently in the same chat. Causes fixed here:
  * Stop was only checked between agent steps — an in-flight model call and
    every tool in the step ran to completion.
  * Tokens kept streaming after Stop.
  * A running shell command was never killed.
  * A pending approval card held the stopped turn for up to 300 s.
  * The WebSocket server ran same-session turns concurrently and the newer
    turn's cancel flag was deleted by the older turn's cleanup.
"""
from __future__ import annotations

import platform
import threading
import time

from fastapi.testclient import TestClient

from namma_agent.core.agent import Agent
from namma_agent.core.interactive import set_current_cancel
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry, ToolResult

WIN = platform.system() == "Windows"


class _SlowProvider(Provider):
    """Streams a token every 50 ms for ``seconds``, then answers."""
    name = "slow"

    def __init__(self, seconds: float = 5.0):
        super().__init__(model="slow")
        self.seconds = seconds

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        end = time.monotonic() + self.seconds
        while time.monotonic() < end:
            if on_token is not None:
                on_token("x")
            time.sleep(0.05)
        return LLMResponse(content="full answer that should never be shown")


def _cancel_after(seconds: float):
    t0 = time.monotonic()
    return lambda: time.monotonic() - t0 >= seconds


def test_stop_aborts_an_in_flight_model_call_quickly():
    events = []
    agent = Agent(_SlowProvider(seconds=5), ToolRegistry(), Database(":memory:"), load_persona())
    t0 = time.monotonic()
    result = agent.process_turn("go", should_cancel=_cancel_after(0.3),
                                emit=lambda e, p: events.append(e))
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0, f"stop took {elapsed:.1f}s"
    assert "should never be shown" not in result.content
    assert "turn_cancelled" in events


def test_no_tokens_reach_the_ui_after_stop():
    tokens: list[tuple[float, str]] = []
    stop_at = {"t": None}

    def should_cancel():
        if stop_at["t"] is None and len(tokens) >= 3:
            stop_at["t"] = time.monotonic()
        return stop_at["t"] is not None

    agent = Agent(_SlowProvider(seconds=2), ToolRegistry(), Database(":memory:"), load_persona())
    agent.process_turn("go", on_token=lambda t: tokens.append((time.monotonic(), t)),
                       should_cancel=should_cancel)
    time.sleep(0.4)  # the abandoned generation keeps streaming in the background
    assert stop_at["t"] is not None
    assert all(ts <= stop_at["t"] for ts, _ in tokens), "tokens arrived after Stop"


def test_stop_skips_the_remaining_tools_in_a_batch():
    ran: list[str] = []
    flag = {"stop": False}
    reg = ToolRegistry()
    schema = {"type": "object", "properties": {}}

    def first(_a):
        ran.append("first")
        flag["stop"] = True  # the user presses Stop while this tool runs
        return ToolResult(ok=True, content="ok")

    reg.register("first", "f", schema, first)
    reg.register("second", "s", schema,
                 lambda a: ran.append("second") or ToolResult(ok=True, content="ok"))

    class _TwoTools(Provider):
        name = "two"

        def __init__(self):
            super().__init__(model="two")
            self.calls = 0

        def is_available(self):
            return True

        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
            self.calls += 1
            return LLMResponse(content="", tool_calls=[
                ToolCall(id="1", name="first", args={}), ToolCall(id="2", name="second", args={})])

    prov = _TwoTools()
    agent = Agent(prov, reg, Database(":memory:"), load_persona())
    agent.process_turn("go", should_cancel=lambda: flag["stop"])
    assert ran == ["first"]
    assert prov.calls == 1  # no further model call after Stop


def test_stop_kills_a_running_shell_command():
    from namma_agent.core.shell_session import PersistentShell

    sh = PersistentShell("stop-test-shell")
    try:
        set_current_cancel(_cancel_after(1.0))
        t0 = time.monotonic()
        r = sh.run("Start-Sleep -Seconds 30" if WIN else "sleep 30", timeout=60)
        elapsed = time.monotonic() - t0
    finally:
        set_current_cancel(None)
    try:
        assert r.cancelled and not r.ok
        assert elapsed < 10, f"shell stop took {elapsed:.1f}s"
        again = sh.run("echo still_works")
        assert again.ok and "still_works" in again.output
    finally:
        sh.close()


def test_websocket_runs_same_chat_turns_one_at_a_time():
    """Stop + an immediate new prompt must not run two TURNS at once in one chat.

    (A stopped turn's in-flight HTTP read can't be killed, so its abandoned model
    call may still finish in the background — but its tokens are dropped and its
    result discarded. What must never overlap is the turns themselves.)"""
    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=_SlowProvider(seconds=0.6), registry=ToolRegistry(),
                            db=Database(":memory:"))
    svc.auto_title = lambda _sid: None
    state = {"active": 0, "max_active": 0, "started": 0}
    lock = threading.Lock()
    real_process_turn = svc.agent.process_turn

    def tracked(*args, **kwargs):
        with lock:
            state["active"] += 1
            state["started"] += 1
            state["max_active"] = max(state["max_active"], state["active"])
        try:
            return real_process_turn(*args, **kwargs)
        finally:
            with lock:
                state["active"] -= 1

    svc.agent.process_turn = tracked
    sid = svc.db.create_session()
    client = TestClient(create_app(svc))
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "first", "session_id": sid})
        deadline = time.monotonic() + 5
        while state["started"] == 0 and time.monotonic() < deadline:
            time.sleep(0.02)
        ws.send_json({"type": "stop", "session_id": sid})
        ws.send_json({"type": "user_input", "text": "second", "session_id": sid})
        results = []
        while len(results) < 2:
            msg = ws.receive_json()
            if msg.get("type") == "turn_result":
                results.append(msg)
    assert state["started"] == 2
    assert state["max_active"] == 1, "two turns ran concurrently in one chat"
    assert results[0]["content"] in ("Stopped.", "")  # the stopped turn produced nothing more
    assert "should never be shown" in results[1]["content"]  # the new prompt ran to completion


def test_a_finished_turn_does_not_leak_its_stop_check():
    """process_turn binds its Stop check on the thread; it must be restored, or
    every later shell command on that thread looks "stopped"."""
    from namma_agent.core.interactive import get_current_cancel
    agent = Agent(_SlowProvider(seconds=1), ToolRegistry(), Database(":memory:"), load_persona())
    assert get_current_cancel() is None
    agent.process_turn("go", should_cancel=lambda: True)
    assert get_current_cancel() is None
