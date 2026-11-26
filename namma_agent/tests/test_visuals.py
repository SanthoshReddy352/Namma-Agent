"""Phase 4: inline visuals (render_visual → sandboxed iframe), the A2UI spike
(show_ui validated server-side, ui_guide behind a tool), the visuals endpoint,
null-origin rejection, and render errors fed back to the model."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from namma_agent.core.agent import Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry
from namma_agent.tools import visuals


@pytest.fixture(autouse=True)
def _visual_store(tmp_path, monkeypatch):
    monkeypatch.setattr(visuals, "visuals_dir", lambda: tmp_path)
    return tmp_path


def _reg():
    reg = ToolRegistry()
    visuals.register(reg)
    return reg


# ── render_visual ────────────────────────────────────────────────────────────

def test_render_visual_stores_html_and_returns_a_visual_fence(_visual_store):
    out = _reg().execute("render_visual", {"html": "<b>hi</b>", "title": "Demo", "height": 300})
    assert out.ok and out.content.startswith("```visual\n") and out.content.endswith("\n```")
    spec = json.loads(out.content.split("\n")[1])
    assert spec["title"] == "Demo" and spec["max_height"] == 300
    assert visuals.load_visual(spec["id"]) == "<b>hi</b>"
    assert out.data["inline"] == out.content          # the agent slots it in place


def test_render_visual_rejects_oversized_and_nested_frames():
    reg = _reg()
    big = reg.execute("render_visual", {"html": "x" * (visuals.MAX_VISUAL_BYTES + 1)})
    assert not big.ok and "render_error" in big.error
    framed = reg.execute("render_visual", {"html": "<iframe src='https://evil'></iframe>"})
    assert not framed.ok and "iframe" in framed.error
    assert not reg.execute("render_visual", {}).ok


def test_load_visual_refuses_bad_ids():
    assert visuals.load_visual("../../etc/passwd") is None
    assert visuals.load_visual("abc") is None


def test_visual_lands_inline_in_the_answer_exactly_where_the_tool_ran():
    class P(Provider):
        name = "p"

        def __init__(self):
            super().__init__(model="p")
            self.n = 0

        def is_available(self):
            return True

        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
            self.n += 1
            if self.n == 1:
                return LLMResponse(content="", tool_calls=[ToolCall(
                    id="v", name="render_visual", args={"html": "<p>sim</p>"})])
            return LLMResponse(content="Here it is.")

    res = Agent(P(), _reg(), Database(":memory:"), load_persona()).process_turn("show me")
    assert res.content.startswith("```visual\n") and res.content.endswith("Here it is.")


# ── A2UI (show_ui) ───────────────────────────────────────────────────────────

_GOOD = [
    {"version": "v0.9", "createSurface": {"surfaceId": "confirm"}},
    {"version": "v0.9", "updateComponents": {"surfaceId": "confirm", "components": [
        {"id": "root", "component": "Card", "child": "col"},
        {"id": "col", "component": "Column", "children": ["q", "yes"]},
        {"id": "q", "component": "Text", "text": "Delete?"},
        {"id": "yes", "component": "Button", "child": "yt",
         "action": {"event": {"name": "confirm", "context": {"answer": "yes"}}}},
        {"id": "yt", "component": "Text", "text": "Yes"}]}},
    {"version": "v0.9", "updateDataModel": {"surfaceId": "confirm", "path": "/", "value": {}}},
]


def test_show_ui_accepts_valid_a2ui_and_normalizes_it():
    out = _reg().execute("show_ui", {"messages": _GOOD, "title": "Confirm"})
    assert out.ok and out.content.startswith("```a2ui\n")
    payload = json.loads(out.content.split("\n", 1)[1].rsplit("\n```", 1)[0])
    msgs = payload["messages"]
    sid = msgs[0]["createSurface"]["surfaceId"]
    assert sid.startswith("confirm-")                               # made unique
    assert msgs[0]["createSurface"]["catalogId"] == visuals.BASIC_CATALOG_ID
    assert all(next(iter(v.values()))["surfaceId"] == sid for v in
               ({k: m[k] for k in m if k != "version"} for m in msgs))


@pytest.mark.parametrize("bad, needle", [
    ([], "non-empty"),
    ([{"version": "v0.9", "updateComponents": {"surfaceId": "x", "components": []}}], "created first"),
    ([{"version": "v0.9", "createSurface": {"surfaceId": "s"}},
      {"version": "v0.9", "updateComponents": {"surfaceId": "s", "components": [
          {"id": "root", "component": "Marquee"}]}}], "unknown component"),
    ([{"version": "v0.9", "createSurface": {"surfaceId": "s"}},
      {"version": "v0.9", "updateComponents": {"surfaceId": "s", "components": [
          {"id": "top", "component": "Text", "text": "x"}]}}], "root"),
    ([{"version": "v0.9", "createSurface": {"surfaceId": "s"}},
      {"version": "v0.9", "updateComponents": {"surfaceId": "s", "components": [
          {"id": "root", "component": "Column", "children": ["ghost"]}]}}], "missing child"),
    ([{"version": "v0.9", "createSurface": {"surfaceId": "s"}},
      {"version": "v0.9", "updateComponents": {"surfaceId": "s", "components": [
          {"id": "root", "component": "Button", "child": "t"},
          {"id": "t", "component": "Text", "text": "x"}]}}], "action"),
    ([{"version": "v2", "createSurface": {"surfaceId": "s"}}], "version"),
    ("{not json", "valid JSON"),
])
def test_show_ui_returns_render_errors_for_the_model_to_fix(bad, needle):
    out = _reg().execute("show_ui", {"messages": bad})
    assert not out.ok and out.error.startswith("render_error") and needle in out.error


def test_ui_guide_is_a_tool_not_prompt_text():
    reg = _reg()
    guide = reg.execute("ui_guide", {}).content
    assert "createSurface" in guide and "ChoicePicker" in guide and "[ui action]" in guide
    assert "createSurface" not in load_persona().system_prompt()


def test_every_component_in_the_guide_example_is_in_the_catalogue():
    example = visuals.UI_GUIDE.split("Example:", 1)[1].split("\n\n")[0]
    payload = json.loads(example.split("\n", 1)[1])
    _, errors = visuals.validate_a2ui(payload)
    assert errors == []


# ── server endpoints ─────────────────────────────────────────────────────────

def _app():
    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=_Echo(), registry=ToolRegistry(), db=Database(":memory:"))
    return svc, TestClient(create_app(svc))


class _Echo(Provider):
    name = "echo"

    def __init__(self):
        super().__init__(model="echo")
        self.seen = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.seen.append(messages)
        return LLMResponse(content="ok")


def test_visual_endpoint_serves_text_and_404s(_visual_store):
    _, client = _app()
    vid = json.loads(_reg().execute("render_visual", {"html": "<i>x</i>"}).content.split("\n")[1])["id"]
    r = client.get(f"/api/visuals/{vid}")
    assert r.status_code == 200 and r.text == "<i>x</i>"
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/api/visuals/0123456789abcdef").status_code == 404


def test_null_origin_requests_are_refused():
    _, client = _app()
    assert client.get("/api/health", headers={"Origin": "null"}).status_code == 403
    assert client.get("/api/health").status_code == 200


def test_render_errors_reach_the_model_once_on_the_next_turn():
    svc, client = _app()
    sid = svc.db.create_session()
    r = client.post("/api/render_error", json={"session_id": sid, "kind": "mermaid",
                                               "error": "Parse error on line 2"})
    assert r.json()["ok"]
    svc.agent.process_turn("next", session_id=sid)
    svc.agent.process_turn("again", session_id=sid)
    first, second = svc.provider.seen[-2][-1]["content"], svc.provider.seen[-1][-1]["content"]
    assert "RENDER ERRORS" in first and "Parse error on line 2" in first
    assert "RENDER ERRORS" not in second                 # told once


def test_persona_teaches_mermaid_charts_and_visuals():
    sp = load_persona().system_prompt()
    assert "```mermaid" in sp and "```chart" in sp and "render_visual" in sp
    assert "does NOT render" not in sp                   # the Phase 1 stopgap is gone
