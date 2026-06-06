"""Phase 4 tests — FastAPI REST + WebSocket turn channel + approval round-trip."""
from __future__ import annotations

from fastapi.testclient import TestClient

from friday.core.memory import Database
from friday.core.providers.base import LLMResponse, Provider, ToolCall
from friday.core.tools import ToolRegistry
from friday.server.api import create_app
from friday.service import FridayService


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None):
        resp = self._responses.pop(0)
        if stream and on_token and resp.content:
            on_token(resp.content)
        return resp


def _service(responses, registry=None):
    db = Database(":memory:")
    return FridayService(
        config={"persona": "friday_core", "conversation": {}},
        provider=ScriptedProvider(responses),
        registry=registry or ToolRegistry(),
        db=db,
    )


def _drain_until(ws, *terminal_types):
    """Receive events until one of terminal_types; return the full list."""
    events = []
    while True:
        msg = ws.receive_json()
        events.append(msg)
        if msg.get("type") in terminal_types:
            return events


# -- REST ------------------------------------------------------------------

def test_rest_health_and_config():
    app = create_app(_service([LLMResponse(content="hi")]))
    client = TestClient(app)
    assert client.get("/api/health").json() == {"ok": True}
    cfg = client.get("/api/config").json()
    assert "remember_fact" in cfg["tools"]
    assert cfg["persona"] == "friday_core"


def test_rest_tools_and_persona():
    app = create_app(_service([LLMResponse(content="hi")]))
    client = TestClient(app)
    tools = client.get("/api/tools").json()["tools"]
    assert any(t["name"] == "recall_facts" for t in tools)
    assert client.post("/api/persona", json={"id": "friday_core"}).json()["persona"] == "friday_core"


# -- WebSocket -------------------------------------------------------------

def test_ws_plain_turn():
    app = create_app(_service([LLMResponse(content="Hello there")]))
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "hi"})
        events = _drain_until(ws, "turn_result")
    types = [e["type"] for e in events]
    assert "token" in types  # streamed
    result = events[-1]
    assert result["content"] == "Hello there"
    assert result["session_id"]


def test_ws_tool_turn_emits_tool_events():
    reg = ToolRegistry()
    reg.register("echo", "echo", {"type": "object", "properties": {"x": {"type": "string"}}},
                 lambda a: f"echoed {a.get('x')}")
    responses = [
        LLMResponse(content="On it.", tool_calls=[ToolCall(id="t1", name="echo", args={"x": "hi"})]),
        LLMResponse(content="Done."),
    ]
    app = create_app(_service(responses, registry=reg))
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "echo hi"})
        events = _drain_until(ws, "turn_result")
    types = [e["type"] for e in events]
    assert "preamble" in types and "tool_started" in types and "tool_finished" in types
    assert events[-1]["content"] == "Done."


def test_ws_approval_approved():
    reg = ToolRegistry()
    ran = {}
    reg.register("wipe", "delete things", {"type": "object", "properties": {}},
                 lambda a: ran.setdefault("ran", True) or "wiped", destructive=True)
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="wipe", args={})]),
        LLMResponse(content="All clear."),
    ]
    app = create_app(_service(responses, registry=reg))
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "wipe it"})
        # respond to the approval request when it arrives
        while True:
            msg = ws.receive_json()
            if msg["type"] == "approval_request":
                ws.send_json({"type": "approval_response", "id": msg["id"], "approved": True})
            if msg["type"] == "turn_result":
                break
    assert ran.get("ran") is True
    assert msg["content"] == "All clear."


def test_ws_approval_declined():
    reg = ToolRegistry()
    ran = {}
    reg.register("wipe", "delete things", {"type": "object", "properties": {}},
                 lambda a: ran.setdefault("ran", True) or "wiped", destructive=True)
    responses = [
        LLMResponse(tool_calls=[ToolCall(id="t1", name="wipe", args={})]),
        LLMResponse(content="Okay, I won't."),
    ]
    app = create_app(_service(responses, registry=reg))
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "wipe it"})
        while True:
            msg = ws.receive_json()
            if msg["type"] == "approval_request":
                ws.send_json({"type": "approval_response", "id": msg["id"], "approved": False})
            if msg["type"] == "turn_result":
                break
    assert ran.get("ran") is None  # tool never executed
    assert msg["content"] == "Okay, I won't."
