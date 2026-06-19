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
    # Visible answer includes the preamble that accompanied the tool call, not just
    # the final line (so teaching text / explanations aren't dropped).
    assert events[-1]["content"] == "On it.\n\nDone."


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


class EchoProvider(Provider):
    """Streams the turn's own user input back, so a token can be matched to the
    session that produced it — used to prove concurrent turns don't cross-talk."""
    name = "echo"

    def __init__(self):
        super().__init__(model="echo")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None):
        user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        if stream and on_token:
            on_token(user)
        return LLMResponse(content=user)


def test_ws_concurrent_turns_do_not_crosstalk():
    """Two chats running at once: every token / result must carry the session id
    of the chat that produced it, and tokens must never leak across sessions."""
    app = create_app(FridayService(
        config={"persona": "friday_core", "conversation": {}},
        provider=EchoProvider(), registry=ToolRegistry(), db=Database(":memory:"),
    ))
    client = TestClient(app)
    sa = client.post("/api/session").json()["session_id"]
    sb = client.post("/api/session").json()["session_id"]
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "alpha", "session_id": sa})
        ws.send_json({"type": "user_input", "text": "beta", "session_id": sb})
        seen_results = {}
        tokens = {sa: [], sb: []}
        while len(seen_results) < 2:
            msg = ws.receive_json()
            sid = msg.get("session_id")
            if msg["type"] == "token":
                tokens[sid].append(msg["text"])
            elif msg["type"] == "turn_result":
                seen_results[sid] = msg["content"]
    # Each session streamed only its own word and finished with its own content.
    assert tokens[sa] == ["alpha"] and tokens[sb] == ["beta"]
    assert seen_results[sa] == "alpha" and seen_results[sb] == "beta"


def test_ws_new_chat_gets_session_started_with_client_ref():
    """A brand-new chat (no session_id) is assigned a real session id the client
    can map back to its provisional ref via the session_started event."""
    app = create_app(_service([LLMResponse(content="hi")]))
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "user_input", "text": "hi", "client_ref": "refX"})
        started = None
        while True:
            msg = ws.receive_json()
            if msg["type"] == "session_started":
                started = msg
            if msg["type"] == "turn_result":
                break
    assert started and started["client_ref"] == "refX" and started["session_id"] == msg["session_id"]


def test_module_session_seeds_intro_once():
    """A freshly-opened learning module must not be a blank chat: it's seeded with
    a single teacher intro turn, and reopening doesn't duplicate it."""
    app = create_app(_service([LLMResponse(content="x")]))
    client = TestClient(app)
    tid = client.post("/api/learning", json={"topic": "How tides work", "depth": "solid"}).json()["topic"]["id"]
    client.patch(f"/api/learning/{tid}/plan", json={"modules": [
        {"title": "The Big Pull", "summary": "why the ocean rises and falls"}]})
    mid = client.get(f"/api/learning/{tid}").json()["topic"]["plan"][0]["id"]
    sid = client.post(f"/api/learning/{tid}/module/{mid}/session").json()["session_id"]
    turns = client.get(f"/api/sessions/{sid}").json()["turns"]
    assert len(turns) == 1 and turns[0]["role"] == "assistant"
    assert "The Big Pull" in turns[0]["content"] and "How tides work" in turns[0]["content"]
    # reopening the same module must not add another intro
    client.post(f"/api/learning/{tid}/module/{mid}/session")
    assert len(client.get(f"/api/sessions/{sid}").json()["turns"]) == 1


def test_auto_title_generates_from_first_exchange():
    svc = _service([LLMResponse(content="Homemade Pizza Dough")])
    sid = svc.db.create_session()
    svc.db.add_turn(sid, "user", "how do I make pizza dough?")
    svc.db.add_turn(sid, "assistant", "Mix flour, water, yeast and salt…")
    assert svc.auto_title(sid) == "Homemade Pizza Dough"
    assert svc.db.get_session(sid)["title"] == "Homemade Pizza Dough"
    # already titled → no-op (and the provider isn't consulted again)
    assert svc.auto_title(sid) is None


def test_auto_title_respects_user_rename():
    svc = _service([])  # provider must NOT be called for a renamed chat
    sid = svc.db.create_session()
    svc.db.add_turn(sid, "user", "hi")
    svc.db.rename_session(sid, "My Own Title")
    assert svc.auto_title(sid) is None
    assert svc.db.get_session(sid)["title"] == "My Own Title"


def test_auto_title_skips_learning_threads():
    svc = _service([])  # learning threads aren't in the chat list — never titled
    sid = svc.db.create_session_in(kind="learning")
    svc.db.add_turn(sid, "user", "teach me")
    assert svc.auto_title(sid) is None


def test_learning_switch_model_recaps_and_repoints():
    """Switching a learning thread's model recaps the session, binds the new model
    to a fresh session, re-points the module onto it, and seeds the recap intro —
    instead of cold-starting."""
    svc = _service([LLMResponse(content="- Covered what a neuron is\n- Next: activation functions")])
    app = create_app(svc)
    client = TestClient(app)
    topic = svc.db.create_learning_topic("Neural networks", "solid")
    svc.db.set_learning_plan(topic["id"], [{"id": "m1", "title": "Neurons", "summary": "the unit"}])
    old = svc.db.module_session(topic["id"], "m1")
    svc.db.add_turn(old, "assistant", "Welcome — today we learn neurons.")
    svc.db.add_turn(old, "user", "what's a neuron?")
    svc.db.add_turn(old, "assistant", "A neuron sums weighted inputs and fires.")

    r = client.post("/api/learning/switch_model",
                    json={"session_id": old, "model": "gemini-guider"}).json()
    assert r["ok"] is True
    new = r["session_id"]
    assert new and new != old
    # new session bound to the chosen model
    assert svc.db.get_session(new)["model"] == "gemini-guider"
    # module re-pointed onto the new session; old session detached from the topic
    plan = svc.db.get_learning_topic(topic["id"])["plan"]
    assert next(m for m in plan if m["id"] == "m1")["session_id"] == new
    assert svc.db.get_topic_by_session(old) is None
    # the new thread opens with a recap intro carrying the summary
    intro = svc.db.session_turns(new)[0]["content"]
    assert "now learning with" in intro and "activation functions" in intro
    assert "activation functions" in r["recap"]


def test_learning_switch_model_rejects_non_learning_session():
    svc = _service([])  # provider must not be called
    app = create_app(svc)
    client = TestClient(app)
    sid = svc.db.create_session()  # a plain chat, not a learning thread
    r = client.post("/api/learning/switch_model",
                    json={"session_id": sid, "model": "x"}).json()
    assert r["ok"] is False


def test_project_switch_model_recaps_and_keeps_project():
    """Switching a project chat's model mirrors the Learning-Room switch: recap the
    session, bind the new model to a fresh session in the SAME project, carry the
    chat title over, and seed the recap intro — instead of cold-starting."""
    svc = _service([LLMResponse(content="- Set up the build\n- Next: wire the deploy step")])
    app = create_app(svc)
    client = TestClient(app)
    project = svc.db.create_project("Pipeline", "ci/cd work")
    old = svc.db.create_session_in(project_id=project["id"], kind="chat")
    svc.db.rename_session(old, "CI setup")
    svc.db.add_turn(old, "user", "help me set up CI")
    svc.db.add_turn(old, "assistant", "Sure — let's start with the build job.")

    r = client.post("/api/projects/switch_model",
                    json={"session_id": old, "model": "gemini-guider"}).json()
    assert r["ok"] is True
    new = r["session_id"]
    assert new and new != old
    # new session bound to the chosen model and kept in the same project
    assert svc.db.get_session(new)["model"] == "gemini-guider"
    assert svc.db.get_session(new)["project_id"] == project["id"]
    # the chat title carries over for sidebar continuity
    assert svc.db.get_session(new)["title"] == "CI setup"
    # the new thread opens with a recap intro carrying the summary
    intro = svc.db.session_turns(new)[0]["content"]
    assert "now chatting with" in intro and "deploy step" in intro
    assert "deploy step" in r["recap"]


def test_project_switch_model_rejects_non_project_session():
    svc = _service([])  # provider must not be called
    app = create_app(svc)
    client = TestClient(app)
    sid = svc.db.create_session()  # a plain chat, not filed in any project
    r = client.post("/api/projects/switch_model",
                    json={"session_id": sid, "model": "x"}).json()
    assert r["ok"] is False
