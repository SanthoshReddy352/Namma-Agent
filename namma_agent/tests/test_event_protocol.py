"""Phase 4: event protocol v2 — seq on every event, a 500-entry ring buffer
with token folding, resume-from-seq on reconnect, app-level turn state (Stop and
approvals survive a reconnect), the queued state, in-session model switching,
and the event schema."""
from __future__ import annotations

import time

import json
import socket
import threading
from contextlib import contextmanager

from fastapi.testclient import TestClient

from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.server.api import create_app
from namma_agent.server.event_log import EVENT_SCHEMA, EventLog, validate
from namma_agent.service import NammaAgentService


# ── the log ──────────────────────────────────────────────────────────────────

def test_seq_is_monotonic_and_tokens_fold_into_one_entry():
    log = EventLog(size=50)
    log.publish({"type": "turn_started", "session_id": "a"})
    for ch in "hello":
        log.publish({"type": "token", "session_id": "a", "text": ch})
    log.publish({"type": "tool_started", "session_id": "a", "tool": "x"})
    assert log.seq == 7
    assert len(log) == 3                        # turn_started, ONE token entry, tool
    _, replay, ok = log.subscribe(lambda e: None, after=0)
    assert ok and [e["type"] for e in replay] == ["turn_started", "token", "tool_started"]
    assert replay[1]["text"] == "hello" and replay[1]["seq"] == 6


def test_replay_never_resends_text_the_client_already_has():
    log = EventLog()
    for ch in "abcdef":
        log.publish({"type": "token", "session_id": "s", "text": ch})
    _, replay, ok = log.subscribe(lambda e: None, after=3)     # client saw "abc"
    assert ok and replay == [{"type": "token", "session_id": "s", "text": "def", "seq": 6}]


def test_tokens_of_different_sessions_do_not_fold_together():
    log = EventLog()
    log.publish({"type": "token", "session_id": "a", "text": "1"})
    log.publish({"type": "token", "session_id": "b", "text": "2"})
    log.publish({"type": "token", "session_id": "a", "text": "3"})
    assert len(log) == 3


def test_gap_restart_and_future_seq_require_a_resync():
    log = EventLog(size=10)
    for i in range(30):
        log.publish({"type": "tool_started", "session_id": "s", "tool": str(i)})
    assert len(log) == 10
    assert log.subscribe(lambda e: None, after=5)[2] is False           # fell out of the ring
    assert log.subscribe(lambda e: None, after=25)[2] is True
    assert log.subscribe(lambda e: None, after=25, boot="other")[2] is False  # restart
    assert log.subscribe(lambda e: None, after=999)[2] is False         # from a future


def test_subscribers_get_stamped_live_events_and_can_unsubscribe():
    log = EventLog()
    got = []
    unsubscribe, _, _ = log.subscribe(got.append)
    log.publish({"type": "stopped"})
    unsubscribe()
    log.publish({"type": "stopped"})
    assert [e["seq"] for e in got] == [1]


def test_schema_validation():
    assert validate({"type": "token", "session_id": "s", "text": "x"}) == []
    assert validate({"type": "token", "text": "x"}) == ["token: missing 'session_id'"]
    assert validate({"type": "made_up"})[0].startswith("unknown event type")
    assert "subagent" in EVENT_SCHEMA and "a2ui" in EVENT_SCHEMA


# ── over the WebSocket ───────────────────────────────────────────────────────

class _Streaming(Provider):
    name = "stream"

    def __init__(self, text="one two three four", delay=0.0):
        super().__init__(model="stream")
        self.text, self.delay = text, delay

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        for word in self.text.split():
            if on_token:
                on_token(word + " ")
            time.sleep(self.delay)
        return LLMResponse(content=self.text)


def _svc(provider):
    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=provider, registry=ToolRegistry(), db=Database(":memory:"))
    svc.auto_title = lambda _sid: None
    return svc


def _until(ws, etype, limit=500):
    seen = []
    for _ in range(limit):
        msg = ws.receive_json()
        seen.append(msg)
        if msg["type"] == etype:
            return seen
    raise AssertionError(f"never got {etype}")


def test_every_logged_event_has_a_seq_and_matches_the_schema():
    client = TestClient(create_app(_svc(_Streaming())))
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["boot"] and "seq" in hello
        ws.send_json({"type": "resume", "from_seq": hello["seq"], "boot": hello["boot"]})
        ws.send_json({"type": "user_input", "text": "hi"})
        events = _until(ws, "turn_result")
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    problems = [p for e in events for p in validate(e)]
    assert problems == []
    assert "".join(e["text"] for e in events if e["type"] == "token") == "one two three four "


@contextmanager
def _live_server(app):
    """A REAL uvicorn server in a thread. (TestClient gives every WebSocket its
    own event loop and tears it down on close, so a turn could never outlive the
    connection that started it — which is exactly what resume is for.)"""
    import uvicorn

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", ws="websockets"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    try:
        yield f"ws://127.0.0.1:{port}/ws"
    finally:
        server.should_exit = True
        thread.join(10)


class _WS:
    """Tiny sync WebSocket client with the TestClient method names."""

    def __init__(self, url):
        from websockets.sync.client import connect
        self._c = connect(url, open_timeout=10)

    def receive_json(self):
        return json.loads(self._c.recv(timeout=15))

    def send_json(self, obj):
        self._c.send(json.dumps(obj))

    def close(self):
        self._c.close()


def test_reconnect_resumes_mid_turn_without_losing_or_doubling_text():
    app = create_app(_svc(_Streaming("alpha beta gamma delta epsilon", delay=0.15)))
    with _live_server(app) as url:
        ws = _WS(url)
        hello = ws.receive_json()
        ws.send_json({"type": "resume", "from_seq": hello["seq"], "boot": hello["boot"]})
        ws.send_json({"type": "user_input", "text": "go"})
        first = _until(ws, "token")                 # saw the first token, then "drop"
        ws.close()
        last_seq = first[-1]["seq"]
        got_text = first[-1]["text"]
        time.sleep(0.6)                              # the turn keeps running server-side
        ws2 = _WS(url)
        hello2 = ws2.receive_json()
        assert hello2["boot"] == hello["boot"]
        ws2.send_json({"type": "resume", "from_seq": last_seq, "boot": hello["boot"]})
        rest = _until(ws2, "turn_result")
        ws2.close()
    text = got_text + "".join(e["text"] for e in rest if e["type"] == "token")
    assert text == "alpha beta gamma delta epsilon "
    assert all(e["seq"] > last_seq for e in rest)


def test_resume_from_another_boot_asks_for_a_resync():
    client = TestClient(create_app(_svc(_Streaming())))
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "resume", "from_seq": 3, "boot": "an-old-server"})
        msg = ws.receive_json()
        assert msg["type"] == "resync_required" and msg["boot"] != "an-old-server"


def test_second_prompt_in_a_busy_chat_is_queued():
    svc = _svc(_Streaming("a b c d", delay=0.15))
    client = TestClient(create_app(svc))
    sid = svc.db.create_session()
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_input", "text": "first", "session_id": sid})
        ws.send_json({"type": "user_input", "text": "second", "session_id": sid})
        seen = []
        while sum(1 for e in seen if e["type"] == "turn_result") < 2:
            seen.append(ws.receive_json())
    types = [e["type"] for e in seen]
    assert "turn_queued" in types
    assert types.index("turn_queued") < [i for i, t in enumerate(types) if t == "turn_result"][0]


def test_stop_from_a_new_connection_reaches_a_running_turn():
    svc = _svc(_Streaming(" ".join(["w"] * 60), delay=0.05))
    sid = svc.db.create_session()
    with _live_server(create_app(svc)) as url:
        ws = _WS(url)
        ws.receive_json()
        ws.send_json({"type": "user_input", "text": "long", "session_id": sid})
        _until(ws, "token")
        ws.close()
        ws2 = _WS(url)                               # e.g. after a page reload
        hello = ws2.receive_json()
        ws2.send_json({"type": "resume", "from_seq": hello["seq"], "boot": hello["boot"]})
        t0 = time.monotonic()
        ws2.send_json({"type": "stop", "session_id": sid})
        events = _until(ws2, "turn_result")
        ws2.close()
    assert any(e["type"] == "stopped" and e.get("running") for e in events)
    assert time.monotonic() - t0 < 2.5               # 60 × 50 ms would be 3 s


def test_switching_model_keeps_the_same_session():
    svc = _svc(_Streaming())
    sid = svc.db.create_session(model="m1")
    client = TestClient(create_app(svc))
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
        ws.send_json({"type": "user_input", "text": "hi", "session_id": sid, "model": "m2"})
        events = _until(ws, "turn_result")
    started = next(e for e in events if e["type"] == "session_started")
    assert started["session_id"] == sid and started["model"] == "m2"
    assert svc.db.get_session(sid)["model"] == "m2"
