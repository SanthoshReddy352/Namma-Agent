"""MCP-Apps (UI widget) awareness — make widget-only tools honest, and repair them.

Some MCP servers ship tools that don't return an answer at all: they render into a
host-side HTML widget. Such a tool declares ``_meta.ui.resourceUri`` (a ``ui://…``
template the host is expected to load in an iframe and drive over a postMessage
JSON-RPC bridge) and replies with a cheerful ack — excalidraw's ``create_view``
answers *"Diagram displayed!"*.

Namma Agent has no widget renderer, so on this host nothing is displayed. Worse,
the ack reads like success, so the model tells the user to go look at a diagram
that was never drawn.

This module fixes both halves:

* :func:`widget_resource_uri` spots those tools from their ``_meta``.
* :func:`augment_widget_result` rewrites the ack. For a server Namma knows how to
  bridge, it renders the view itself and hands back a link the chat displays as an
  inline card — the diagram lands in the conversation, which is what the widget was
  for. For anything else it says plainly that nothing was shown, so the model stops
  claiming otherwise.

The bridge table is keyed by ``ui://`` resource URI, so teaching Namma a second
MCP-App server is one entry — no changes to the manager.
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Callable, Optional

from namma_agent.core.interactive import record_artifact
from namma_agent.core.logger import logger
from namma_agent.mcp.excalidraw_render import write_scene_page

#: Pseudo-elements the excalidraw widget interprets as canvas commands. They are
#: not drawable elements and must not reach a real ``.excalidraw`` scene.
_PSEUDO = {"cameraUpdate", "delete", "restoreCheckpoint"}

_HONEST_NOTE = (
    "\n\n[namma] NOTE: this tool renders into an MCP UI widget, which this host does "
    "not display. NOTHING was shown to the user. Do not tell them it is on screen — "
    "produce a shareable artifact (e.g. an export_* tool on the same server) and give "
    "them the link."
)


def ui_meta(tool: dict) -> dict:
    """The ``_meta.ui`` block of an MCP tool definition ({} when absent)."""
    meta = (tool or {}).get("_meta") or {}
    ui = meta.get("ui")
    return ui if isinstance(ui, dict) else {}


def widget_resource_uri(tool: dict) -> str:
    """The ``ui://…`` template a tool renders into, or "" for a normal tool.

    Both the nested (``_meta.ui.resourceUri``) and flattened
    (``_meta["ui/resourceUri"]``) spellings are accepted — servers emit either.
    """
    uri = ui_meta(tool).get("resourceUri")
    if not uri:
        uri = ((tool or {}).get("_meta") or {}).get("ui/resourceUri")
    return str(uri or "")


# ── excalidraw bridge ──────────────────────────────────────────────────────────

def _rand() -> int:
    return random.randint(1, 2 ** 31 - 1)


def _base(el: dict, kind: str) -> dict:
    """Fill the fields every Excalidraw element needs. The shorthand the model
    writes carries only geometry and colour; excalidraw.com's importer is strict
    about the rest being *present*, not about its values."""
    return {
        "id": str(el.get("id") or f"{kind}-{_rand()}"),
        "type": kind,
        "x": float(el.get("x", 0)), "y": float(el.get("y", 0)),
        "width": float(el.get("width", 0)), "height": float(el.get("height", 0)),
        "angle": float(el.get("angle", 0)),
        "strokeColor": el.get("strokeColor", "#1e1e1e"),
        "backgroundColor": el.get("backgroundColor", "transparent"),
        "fillStyle": el.get("fillStyle", "solid"),
        "strokeWidth": el.get("strokeWidth", 2),
        "strokeStyle": el.get("strokeStyle", "solid"),
        "roughness": el.get("roughness", 1),
        "opacity": el.get("opacity", 100),
        "groupIds": el.get("groupIds", []),
        "frameId": el.get("frameId"),
        "roundness": el.get("roundness"),
        "seed": _rand(), "version": 1, "versionNonce": _rand(),
        "isDeleted": False, "boundElements": [], "updated": int(time.time() * 1000),
        "link": el.get("link"), "locked": False,
    }


def _text_element(text: str, container: dict, spec: dict) -> dict:
    """A bound text element centred in ``container`` — the expansion of the
    ``label`` shorthand, which is a widget convenience with no equivalent in the
    real Excalidraw format (there, text is a separate element linked both ways)."""
    size = float(spec.get("fontSize", 20))
    lines = str(text).split("\n")
    width = max(len(ln) for ln in lines) * size * 0.5
    height = size * 1.25 * len(lines)
    el = _base({"id": f"{container['id']}-label"}, "text")
    el.update({
        "x": container["x"] + (container["width"] - width) / 2,
        "y": container["y"] + (container["height"] - height) / 2,
        "width": width, "height": height,
        "text": text, "originalText": text,
        "fontSize": size, "fontFamily": spec.get("fontFamily", 1),
        "textAlign": "center", "verticalAlign": "middle",
        "containerId": container["id"], "lineHeight": 1.25,
        "strokeColor": spec.get("strokeColor", "#1e1e1e"),
        "backgroundColor": "transparent",
    })
    return el


def _binding(raw: Any) -> Optional[dict]:
    """Convert the shorthand ``{elementId, fixedPoint}`` binding into the
    ``{elementId, focus, gap}`` shape plain (non-elbowed) arrows use. The arrow's
    own points already encode the geometry, so this only preserves the link."""
    if not isinstance(raw, dict) or not raw.get("elementId"):
        return None
    return {"elementId": str(raw["elementId"]), "focus": 0, "gap": 1}


def normalize_elements(raw: Any) -> list[dict]:
    """Expand the widget's authoring shorthand into a real Excalidraw scene.

    Drops the pseudo-elements (``cameraUpdate`` / ``delete`` / ``restoreCheckpoint``
    are canvas commands, not shapes), expands ``label`` into bound text elements,
    and fills the fields excalidraw.com expects. ``raw`` is the tool's ``elements``
    argument — a JSON array *string*, or an already-parsed list.
    """
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"elements is not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise ValueError("elements must be a JSON array")

    out: list[dict] = []
    by_id: dict[str, dict] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if not kind or kind in _PSEUDO:
            continue
        el = _base(item, kind)
        if kind == "text":
            body = str(item.get("text", ""))
            size = float(item.get("fontSize", 20))
            el.update({
                "text": body, "originalText": body, "fontSize": size,
                "fontFamily": item.get("fontFamily", 1),
                "textAlign": item.get("textAlign", "left"),
                "verticalAlign": item.get("verticalAlign", "top"),
                "containerId": None, "lineHeight": 1.25,
            })
            if not el["width"]:
                el["width"] = max(len(ln) for ln in body.split("\n") or [""]) * size * 0.5
            if not el["height"]:
                el["height"] = size * 1.25 * len(body.split("\n"))
        elif kind in ("arrow", "line"):
            pts = item.get("points") or [[0, 0], [el["width"], el["height"]]]
            el.update({
                "points": pts, "lastCommittedPoint": None,
                "startBinding": _binding(item.get("startBinding")),
                "endBinding": _binding(item.get("endBinding")),
                "startArrowhead": item.get("startArrowhead"),
                "endArrowhead": item.get("endArrowhead", "arrow" if kind == "arrow" else None),
                "elbowed": False,
            })
        out.append(el)
        by_id[el["id"]] = el

        label = item.get("label")
        if isinstance(label, dict) and label.get("text"):
            text_el = _text_element(str(label["text"]), el, label)
            el["boundElements"] = [{"type": "text", "id": text_el["id"]}]
            out.append(text_el)
            by_id[text_el["id"]] = text_el

    # Bound arrows are recorded on the shape too, or Excalidraw drops the link.
    for el in out:
        for side in ("startBinding", "endBinding"):
            target = by_id.get(((el.get(side) or {}).get("elementId")) or "")
            if target is not None:
                target.setdefault("boundElements", []).append(
                    {"type": "arrow", "id": el["id"]})
    return out


def _excalidraw_scene(elements: list[dict]) -> str:
    return json.dumps({
        "type": "excalidraw", "version": 2, "source": "namma-agent",
        "elements": elements,
        "appState": {"viewBackgroundColor": "#ffffff", "gridSize": None},
        "files": {},
    })


def _excalidraw_bridge(args: dict, call: Callable[[str, dict], str]) -> tuple[str, dict]:
    """Draw the scene where the user will actually see it: an inline chat card.

    Returns ``(content, data)``. ``data["url"]`` is what makes the agent inject the
    markdown into the answer itself — the model reliably paraphrases a link instead
    of pasting it, so asking it nicely does not work (see :mod:`namma_agent.core.agent`,
    "surfaced inline since the model rarely re-pastes the markdown"). Because the
    agent shows this content verbatim, it holds only user-facing markdown.

    The local render comes first and never depends on the network, so a diagram shows
    up even offline. The excalidraw.com export is a bonus edit link — if it fails, the
    user still has the picture.
    """
    elements = normalize_elements(args.get("elements"))
    if not elements:
        raise ValueError("no drawable elements")

    url, title = write_scene_page(elements)
    record_artifact("diagram", url, title)
    lines = [f"[{title}]({url})"]

    try:
        share = (call("export_to_excalidraw", {"json": _excalidraw_scene(elements)}) or "").strip()
        if share.startswith("http"):
            lines += ["", f"[Edit on excalidraw.com]({share})"]
    except Exception as exc:  # noqa: BLE001
        logger.info("[mcp] excalidraw export skipped: %s", exc)
    return "\n".join(lines), {"url": url, "kind": "diagram"}


#: ``ui://`` resource URI → a repair that turns the widget-only ack into something
#: the user can actually see. Each returns ``(content, data)``; a ``data["url"]``
#: makes the agent surface the content inline. Add an entry for another MCP-App server.
BRIDGES: dict[str, Callable[[dict, Callable[[str, dict], str]], tuple[str, dict]]] = {
    "ui://excalidraw/mcp-app.html": _excalidraw_bridge,
}


def augment_widget_result(content: str, args: dict, resource_uri: str,
                          call: Callable[[str, dict], str]) -> tuple[str, dict]:
    """Replace a widget-only tool's ack with something true on this host.

    Returns ``(content, data)`` for :class:`~namma_agent.core.tools.ToolResult`. Uses
    the bridge registered for ``resource_uri`` when there is one, falling back to an
    explicit "nothing was displayed" note — including when the bridge itself fails, so
    a broken render never masquerades as a drawn diagram. The fallback carries no
    ``url``, so nothing is injected into the answer.
    """
    bridge = BRIDGES.get(resource_uri)
    if bridge is not None:
        try:
            return bridge(args or {}, call)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[mcp] widget bridge %s failed: %s", resource_uri, exc)
            return f"{content}\n\n[namma] Widget bridge failed ({exc})." + _HONEST_NOTE, {}
    return f"{content}{_HONEST_NOTE}", {}
