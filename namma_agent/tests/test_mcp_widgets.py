"""MCP-Apps widget tools — detection, shorthand expansion, and result repair.

Covers the failure this module exists for: a tool that renders into a host widget
answers "Displayed!" on a host that has no widget renderer, so the model reports a
diagram the user never saw.
"""
from __future__ import annotations

import json
import re

import pytest

from namma_agent.core.tools import ToolRegistry
from namma_agent.mcp.manager import MCPManager
from namma_agent.mcp.widgets import (
    augment_widget_result,
    normalize_elements,
    widget_resource_uri,
)

CREATE_VIEW = {
    "name": "create_view",
    "inputSchema": {"type": "object", "properties": {"elements": {"type": "string"}}},
    "_meta": {"ui": {"resourceUri": "ui://excalidraw/mcp-app.html"},
              "ui/resourceUri": "ui://excalidraw/mcp-app.html"},
}


# ── detection ─────────────────────────────────────────────────────────────────

def test_widget_tool_is_detected_in_both_spellings():
    assert widget_resource_uri(CREATE_VIEW) == "ui://excalidraw/mcp-app.html"
    assert widget_resource_uri({"_meta": {"ui": {"resourceUri": "ui://x"}}}) == "ui://x"
    assert widget_resource_uri({"_meta": {"ui/resourceUri": "ui://y"}}) == "ui://y"


def test_plain_tools_are_not_widgets():
    assert widget_resource_uri({"name": "read_me"}) == ""
    # visibility-only _meta marks an app-internal tool, not a rendering one
    assert widget_resource_uri({"_meta": {"ui": {"visibility": ["app"]}}}) == ""


# ── shorthand → real Excalidraw scene ─────────────────────────────────────────

def test_pseudo_elements_are_dropped():
    els = normalize_elements(json.dumps([
        {"type": "cameraUpdate", "width": 800, "height": 600, "x": 0, "y": 0},
        {"type": "restoreCheckpoint", "id": "abc"},
        {"type": "rectangle", "id": "r1", "x": 0, "y": 0, "width": 10, "height": 10},
        {"type": "delete", "ids": "r9"},
    ]))
    assert [e["type"] for e in els] == ["rectangle"]


def test_label_expands_to_a_bound_text_element():
    els = normalize_elements([{
        "type": "rectangle", "id": "r1", "x": 100, "y": 100,
        "width": 200, "height": 80, "label": {"text": "Gateway", "fontSize": 20},
    }])
    rect, text = els
    assert text["type"] == "text" and text["text"] == "Gateway"
    assert text["containerId"] == "r1"
    assert {"type": "text", "id": text["id"]} in rect["boundElements"]
    # centred inside the container
    assert 100 < text["x"] < 300 and 100 < text["y"] < 180


def test_every_element_carries_the_fields_excalidraw_requires():
    els = normalize_elements([{"type": "ellipse", "id": "e1", "x": 0, "y": 0,
                               "width": 50, "height": 50}])
    required = {"id", "type", "x", "y", "width", "height", "angle", "strokeColor",
                "backgroundColor", "fillStyle", "strokeWidth", "strokeStyle",
                "roughness", "opacity", "groupIds", "seed", "version",
                "versionNonce", "isDeleted", "boundElements", "updated", "locked"}
    assert required <= set(els[0])


def test_arrow_binding_shorthand_becomes_a_real_binding_both_ways():
    els = normalize_elements([
        {"type": "rectangle", "id": "r1", "x": 0, "y": 0, "width": 10, "height": 10},
        {"type": "arrow", "id": "a1", "x": 10, "y": 5, "width": 40, "height": 0,
         "points": [[0, 0], [40, 0]],
         "startBinding": {"elementId": "r1", "fixedPoint": [1, 0.5]}},
    ])
    rect, arrow = els
    assert arrow["startBinding"] == {"elementId": "r1", "focus": 0, "gap": 1}
    assert arrow["endBinding"] is None
    assert {"type": "arrow", "id": "a1"} in rect["boundElements"]


def test_malformed_elements_raise():
    with pytest.raises(ValueError):
        normalize_elements("{not json")
    with pytest.raises(ValueError):
        normalize_elements(json.dumps({"type": "rectangle"}))  # not an array


# ── result repair ─────────────────────────────────────────────────────────────

RECT = json.dumps([{"type": "rectangle", "id": "r1", "x": 0, "y": 0,
                    "width": 10, "height": 10}])


@pytest.fixture(autouse=True)
def _sandbox_media(tmp_path, monkeypatch):
    """Keep rendered pages out of the user's real data dir."""
    import namma_agent.mcp.widgets as mod
    real = mod.write_scene_page
    monkeypatch.setattr(mod, "write_scene_page",
                        lambda els, title="": real(els, title, media_root=tmp_path))


def test_bridge_renders_inline_and_offers_the_editable_copy():
    seen = {}

    def call(name, args):
        seen["name"], seen["args"] = name, args
        return "https://excalidraw.com/#json=abc,def"

    out, data = augment_widget_result("Diagram displayed!", {"elements": RECT},
                                      "ui://excalidraw/mcp-app.html", call)

    # the inline card is what the user actually sees
    assert "/api/media/sims/" in out and ".html)" in out
    # …and the export is a bonus link off the same scene
    assert seen["name"] == "export_to_excalidraw"
    scene = json.loads(seen["args"]["json"])
    assert scene["type"] == "excalidraw" and len(scene["elements"]) == 1
    assert "https://excalidraw.com/#json=abc,def" in out
    assert data["url"] == out.splitlines()[0].split("(")[1].rstrip(")")


def test_content_is_pure_markdown_because_the_agent_shows_it_verbatim():
    """`agent._loop` injects `as_message_content()` straight into the answer, so any
    model-facing instruction in the content would be shown to the user."""
    out, _ = augment_widget_result("Diagram displayed!", {"elements": RECT},
                                   "ui://excalidraw/mcp-app.html",
                                   lambda n, a: "https://excalidraw.com/#json=a,b")
    for line in (ln for ln in out.splitlines() if ln.strip()):
        assert re.fullmatch(r"\[[^\]]+\]\([^)]+\)", line.strip()), line
    assert "Reply with" not in out and "EXACTLY" not in out


def test_the_url_that_triggers_injection_is_returned_as_data():
    _, data = augment_widget_result("Diagram displayed!", {"elements": RECT},
                                    "ui://excalidraw/mcp-app.html", lambda n, a: "")
    assert data["url"].startswith("/api/media/sims/")
    assert data["kind"] == "diagram"


def test_the_diagram_still_renders_when_the_export_fails():
    """The local render never depends on the network — offline still shows a diagram."""
    def call(_name, _args):
        raise RuntimeError("server down")

    out, data = augment_widget_result("Diagram displayed!", {"elements": RECT},
                                      "ui://excalidraw/mcp-app.html", call)
    assert "/api/media/sims/" in out and data["url"]
    assert "excalidraw.com" not in out  # no link is better than a broken one


def test_an_unrenderable_scene_never_reports_success():
    out, data = augment_widget_result("Diagram displayed!", {"elements": "{not json"},
                                      "ui://excalidraw/mcp-app.html", lambda n, a: "")
    assert "NOTHING was shown" in out and "/api/media/sims/" not in out
    assert not data.get("url")  # nothing to inject, so nothing is claimed


def test_unknown_widget_server_gets_the_honest_note():
    out, data = augment_widget_result("Displayed!", {}, "ui://something/else.html",
                                      lambda n, a: "")
    assert "NOTHING was shown" in out and not data


# ── registry wiring ───────────────────────────────────────────────────────────

class _FakeClient:
    """Stands in for a connected MCP server: create_view acks, export returns a URL."""

    def __init__(self):
        self.calls = []

    def list_tools(self):
        return [CREATE_VIEW, {"name": "read_me", "inputSchema": {}}]

    def call_tool(self, name, args, timeout=60):
        self.calls.append(name)
        if name == "export_to_excalidraw":
            return "https://excalidraw.com/#json=ID,KEY"
        return 'Diagram displayed! Checkpoint id: "d4cd".'


def test_registered_widget_tool_returns_a_rendered_card_not_the_ack():
    registry, client = ToolRegistry(), _FakeClient()
    mgr = MCPManager([])
    for tool in client.list_tools():
        mgr._register_tool(registry, "excalidraw", client, tool)

    result = registry.get("mcp_excalidraw_create_view").handler({"elements": RECT})

    assert result.ok
    assert "Diagram displayed!" not in result.content
    assert "/api/media/sims/" in result.content
    assert "https://excalidraw.com/#json=ID,KEY" in result.content
    assert client.calls == ["create_view", "export_to_excalidraw"]
    # the contract agent._loop keys off to place the diagram in the answer
    assert result.data["url"].startswith("/api/media/sims/")


def test_plain_tools_carry_no_media_data():
    """Only widget tools inject; a normal MCP tool must not hijack the answer."""
    registry, client = ToolRegistry(), _FakeClient()
    MCPManager([])._register_tool(registry, "excalidraw", client,
                                  {"name": "read_me", "inputSchema": {}})
    assert registry.get("mcp_excalidraw_read_me").handler({}).data is None


# ── the whole path, through the real agent loop ───────────────────────────────

def test_diagram_reaches_the_answer_even_when_the_model_describes_it_instead():
    """The regression this module exists for, end to end.

    A model handed a diagram tends to narrate it ("All 8 diagrams are done…") rather
    than paste the markdown, and the user saw no diagram at all. The agent places
    media itself off `ToolResult.data["url"]`, so the picture must survive a reply
    that never mentions the link.
    """
    from namma_agent.core.agent import Agent
    from namma_agent.core.memory import Database
    from namma_agent.core.persona import load_persona
    from namma_agent.core.providers.base import LLMResponse, ToolCall
    from namma_agent.tests.test_agent_loop import ScriptedProvider

    registry, client = ToolRegistry(), _FakeClient()
    MCPManager([])._register_tool(registry, "excalidraw", client, CREATE_VIEW)

    responses = [
        LLMResponse(content="Drawing the architecture.",
                    tool_calls=[ToolCall(id="c1", name="mcp_excalidraw_create_view",
                                         args={"elements": RECT})]),
        # …the model narrates instead of pasting the link — exactly the failure mode
        LLMResponse(content="All 8 diagrams are done. Click to zoom into any section."),
    ]
    agent = Agent(ScriptedProvider(responses), registry, Database(":memory:"),
                  load_persona(), emit=lambda e, p: None)
    result = agent.process_turn("draw the whatsapp system")

    assert "/api/media/sims/" in result.content, "the diagram never reached the user"
    assert result.content.strip().endswith("Click to zoom into any section.")


def test_plain_tools_are_left_alone():
    registry, client = ToolRegistry(), _FakeClient()
    MCPManager([])._register_tool(registry, "excalidraw", client,
                                  {"name": "read_me", "inputSchema": {}})
    result = registry.get("mcp_excalidraw_read_me").handler({})
    assert result.ok and "[namma]" not in result.content
    assert client.calls == ["read_me"]
