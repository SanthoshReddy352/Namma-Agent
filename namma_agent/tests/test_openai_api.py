"""Phase 7f — the OpenAI-compatible surface (server/openai_api.py).

Shape compliance (so third-party clients work), session continuity (so they get
memory), and the two safety properties: the token guards /v1 exactly like /api,
and destructive tools are declined because HTTP has no approval channel.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry
from namma_agent.server.api import create_app
from namma_agent.server.openai_api import SESSION_PREFIX, _text_of, _turn_input
from namma_agent.service import NammaAgentService


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None,
                 on_thinking=None):
        resp = self._responses.pop(0)
        if stream and on_token and resp.content:
            on_token(resp.content)
        return resp


def _service(responses, registry=None, config=None):
    return NammaAgentService(
        config=config or {"persona": "core", "conversation": {}},
        provider=ScriptedProvider(responses),
        registry=registry or ToolRegistry(),
        db=Database(":memory:"),
    )


def _client(responses, **kw):
    return TestClient(create_app(_service(responses, **kw)))


# ── message flattening ───────────────────────────────────────────────────────

def test_text_of_handles_both_content_shapes():
    assert _text_of("plain") == "plain"
    assert _text_of([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"
    assert _text_of(None) == ""


def test_turn_input_takes_the_last_user_message():
    from namma_agent.server.openai_api import ChatMessage
    text = _turn_input([
        ChatMessage(role="user", content="old question"),
        ChatMessage(role="assistant", content="old answer"),
        ChatMessage(role="user", content="the real question"),
    ])
    assert text == "the real question"


def test_turn_input_prepends_a_system_message():
    from namma_agent.server.openai_api import ChatMessage
    text = _turn_input([
        ChatMessage(role="system", content="be terse"),
        ChatMessage(role="user", content="hello"),
    ])
    assert "be terse" in text and text.endswith("hello")


# ── /v1/models ───────────────────────────────────────────────────────────────

def test_models_lists_the_configured_models():
    client = _client([], config={"persona": "core", "conversation": {},
                                 "provider": {"model": "big-pickle"}})
    body = client.get("/v1/models").json()
    assert body["object"] == "list"
    assert body["data"][0]["id"] == "big-pickle"
    assert body["data"][0]["owned_by"] == "namma-agent"


# ── /v1/chat/completions — non-streaming ─────────────────────────────────────

def test_chat_completion_shape():
    client = _client([LLMResponse(content="Hello from the agent")])
    body = client.post("/v1/chat/completions", json={
        "model": "scripted",
        "messages": [{"role": "user", "content": "hi"}],
    }).json()

    assert body["object"] == "chat.completion"
    assert body["id"].startswith("chatcmpl-")
    choice = body["choices"][0]
    assert choice["message"] == {"role": "assistant", "content": "Hello from the agent"}
    assert choice["finish_reason"] == "stop"
    assert {"prompt_tokens", "completion_tokens", "total_tokens"} <= set(body["usage"])


def test_empty_messages_is_an_invalid_request():
    body = _client([]).post("/v1/chat/completions", json={"messages": []}).json()
    assert body["error"]["type"] == "invalid_request_error"


def test_assistant_only_history_is_an_invalid_request():
    body = _client([]).post("/v1/chat/completions", json={
        "messages": [{"role": "assistant", "content": "hi"}]}).json()
    assert "error" in body


def test_sampling_knobs_are_accepted_and_ignored():
    """A model's knobs don't map onto an agent turn, but 400ing on them would
    break otherwise-fine clients."""
    client = _client([LLMResponse(content="ok")])
    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.9, "max_tokens": 50})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "ok"


# ── session continuity ───────────────────────────────────────────────────────

def test_same_user_reuses_one_session():
    svc = _service([LLMResponse(content="one"), LLMResponse(content="two")])
    client = TestClient(create_app(svc))

    first = client.post("/v1/chat/completions", json={
        "user": "alice", "messages": [{"role": "user", "content": "hi"}]}).json()
    second = client.post("/v1/chat/completions", json={
        "user": "alice", "messages": [{"role": "user", "content": "again"}]}).json()

    assert first["namma"]["session_id"] == second["namma"]["session_id"]


def test_different_users_get_different_sessions():
    svc = _service([LLMResponse(content="a"), LLMResponse(content="b")])
    client = TestClient(create_app(svc))
    one = client.post("/v1/chat/completions", json={
        "user": "alice", "messages": [{"role": "user", "content": "hi"}]}).json()
    two = client.post("/v1/chat/completions", json={
        "user": "bob", "messages": [{"role": "user", "content": "hi"}]}).json()
    assert one["namma"]["session_id"] != two["namma"]["session_id"]


def test_session_is_titled_so_it_survives_a_restart():
    """The title is how a user maps back to their session after a restart —
    without it, every restart would strand the conversation."""
    svc = _service([LLMResponse(content="hi")])
    client = TestClient(create_app(svc))
    body = client.post("/v1/chat/completions", json={
        "user": "alice", "messages": [{"role": "user", "content": "hi"}]}).json()

    titles = [s.get("title") for s in svc.db.list_sessions(limit=10)]
    assert f"{SESSION_PREFIX}alice" in titles

    # A fresh app over the SAME db recovers the session rather than making one
    # (a new app means an empty in-process map — the DB title is the only link).
    svc.provider._responses.append(LLMResponse(content="more"))
    again = TestClient(create_app(svc)).post("/v1/chat/completions", json={
        "user": "alice", "messages": [{"role": "user", "content": "more"}]})
    assert again.json()["namma"]["session_id"] == body["namma"]["session_id"]


# ── streaming ────────────────────────────────────────────────────────────────

def test_streaming_chunk_format():
    client = _client([LLMResponse(content="streamed reply")])
    with client.stream("POST", "/v1/chat/completions", json={
            "stream": True, "messages": [{"role": "user", "content": "hi"}]}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        payload = "".join(chunk for chunk in r.iter_text())

    lines = [ln for ln in payload.splitlines() if ln.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"

    frames = [json.loads(ln[6:]) for ln in lines[:-1]]
    assert frames[0]["choices"][0]["delta"]["role"] == "assistant"
    assert frames[0]["object"] == "chat.completion.chunk"
    assert "streamed reply" in "".join(
        f["choices"][0]["delta"].get("content", "") for f in frames)
    assert frames[-1]["choices"][0]["finish_reason"] == "stop"


# ── safety: destructive tools are declined ───────────────────────────────────

def test_destructive_tools_are_declined_over_http():
    """No approval channel over HTTP — the same rule routines and watchers run
    under. Silently running them because the caller used REST would be wrong."""
    ran = {"count": 0}
    reg = ToolRegistry()

    def _delete(_args):
        ran["count"] += 1
        return "deleted"

    reg.register("delete_path", "delete", {"type": "object", "properties": {}},
                 _delete, destructive=True)

    client = _client([
        LLMResponse(content="", tool_calls=[
            ToolCall(id="1", name="delete_path", args={"path": "/tmp/x"})]),
        LLMResponse(content="I could not delete that."),
    ], registry=reg)

    body = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "delete /tmp/x"}]}).json()

    assert ran["count"] == 0
    assert body["choices"][0]["message"]["content"] == "I could not delete that."


def test_safe_tools_still_run():
    reg = ToolRegistry()
    reg.register("read_file", "read", {"type": "object", "properties": {}},
                 lambda a: "file contents")
    client = _client([
        LLMResponse(content="", tool_calls=[
            ToolCall(id="1", name="read_file", args={"path": "/tmp/x"})]),
        LLMResponse(content="It says: file contents"),
    ], registry=reg)

    body = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "read /tmp/x"}]}).json()
    assert "file contents" in body["choices"][0]["message"]["content"]
    assert body["namma"]["tools_used"] == ["read_file"]


# ── safety: the auth token guards /v1 too ────────────────────────────────────

def test_v1_requires_the_auth_token_when_one_is_set():
    """/v1 runs real tools — leaving it open would be a bigger hole than any
    read-only /api route."""
    svc = _service([LLMResponse(content="hi")],
                   config={"persona": "core", "conversation": {},
                           "server": {"auth_token": "s3cret"}})
    client = TestClient(create_app(svc))

    assert client.get("/v1/models").status_code == 401
    assert client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": "hi"}]}).status_code == 401

    ok = client.get("/v1/models", headers={"Authorization": "Bearer s3cret"})
    assert ok.status_code == 200


def test_v1_is_open_when_no_token_is_configured():
    assert _client([]).get("/v1/models").status_code == 200
