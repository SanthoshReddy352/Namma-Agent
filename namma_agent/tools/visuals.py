"""Inline visuals and agent-generated UI (PROGRESS.md Phase 4).

* ``render_visual`` — an interactive HTML/SVG visual the chat shows inline in a
  sandboxed iframe (``sandbox="allow-scripts"``, never same-origin, CSP
  ``connect-src 'none'``). The HTML is stored under ``<data>/media/visuals/``;
  the tool's result is a ```visual fence holding only its id, slotted into the
  reply exactly where the tool ran.
* ``show_ui`` — the A2UI spike: the model sends A2UI v0.9 messages (surface,
  components, data model); they are validated HERE (structure, catalogue,
  references, size) and an invalid payload comes straight back to the model as
  a ``render_error`` to fix. A valid one becomes an ```a2ui fence that the
  client renders with the official ``@a2ui/react`` renderer onto its own
  components — no agent-supplied code runs. User actions come back as a
  ``[ui action]`` message.
* ``ui_guide`` — the A2UI component catalogue, behind a tool so it costs no
  system-prompt tokens until the model actually wants to build a UI.

Simple diagrams and charts don't need a tool at all: the model writes
```mermaid or ```chart fences (see the persona's FORMATTING rules).
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from namma_agent.core.tools import ToolRegistry, ToolResult

MAX_VISUAL_BYTES = 200_000
MAX_UI_BYTES = 60_000
MAX_UI_COMPONENTS = 120
A2UI_VERSIONS = ("v0.9", "0.9", "v0.9.1", "0.9.1")
#: The v0.9 basic catalogue id the client's renderer registers.
BASIC_CATALOG_ID = "https://a2ui.org/specification/v0_9/catalogs/basic/catalog.json"
BASIC_COMPONENTS = frozenset({
    "Text", "Image", "Icon", "Video", "AudioPlayer", "Row", "Column", "List", "Card",
    "Tabs", "Modal", "Divider", "Button", "TextField", "CheckBox", "ChoicePicker",
    "Slider", "DateTimeInput",
})
_MESSAGE_KEYS = ("createSurface", "updateComponents", "updateDataModel", "deleteSurface")
_ID_RE = re.compile(r"^[a-f0-9]{8,32}$")


def visuals_dir() -> Path:
    from namma_agent.config import data_dir
    d = data_dir() / "media" / "visuals"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_visual(visual_id: str) -> str | None:
    """The stored HTML of a visual, or None (bad id / missing)."""
    if not _ID_RE.match(visual_id or ""):
        return None
    path = visuals_dir() / f"{visual_id}.html"
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _render_visual(args: dict) -> ToolResult:
    html = str(args.get("html") or args.get("svg") or "").strip()
    if not html:
        return ToolResult(ok=False, content="", error="render_visual needs 'html' (or 'svg')")
    if len(html.encode("utf-8")) > MAX_VISUAL_BYTES:
        return ToolResult(ok=False, content="",
                          error=f"render_error: visual is larger than {MAX_VISUAL_BYTES // 1000} KB")
    if re.search(r"<\s*(iframe|object|embed)\b", html, re.IGNORECASE):
        return ToolResult(ok=False, content="",
                          error="render_error: <iframe>/<object>/<embed> are not allowed in a visual")
    vid = uuid.uuid4().hex[:16]
    (visuals_dir() / f"{vid}.html").write_text(html, encoding="utf-8")
    spec = {"id": vid, "title": str(args.get("title") or "")[:120]}
    if args.get("height"):
        try:
            spec["max_height"] = max(120, min(int(args["height"]), 1200))
        except (TypeError, ValueError):
            pass
    fence = "```visual\n" + json.dumps(spec) + "\n```"
    return ToolResult(ok=True, content=fence, data={"inline": fence, "visual": spec})


# ── A2UI (spike) ─────────────────────────────────────────────────────────────

def validate_a2ui(messages) -> tuple[list, list[str]]:
    """Normalize and validate A2UI v0.9 messages. Returns ``(messages, errors)``.

    Surface ids get a unique suffix (they must be unique for the renderer's
    lifetime) and ``catalogId`` is pinned to the basic catalogue."""
    errors: list[str] = []
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except ValueError as exc:
            return [], [f"messages is not valid JSON: {exc}"]
    if not isinstance(messages, list) or not messages:
        return [], ["'messages' must be a non-empty array of A2UI messages"]
    if len(json.dumps(messages)) > MAX_UI_BYTES:
        return [], [f"payload larger than {MAX_UI_BYTES // 1000} KB"]
    suffix = uuid.uuid4().hex[:6]
    rename: dict[str, str] = {}
    created: set[str] = set()
    components: dict[str, dict] = {}
    out = []
    for i, msg in enumerate(messages):
        where = f"messages[{i}]"
        if not isinstance(msg, dict):
            errors.append(f"{where}: must be an object")
            continue
        if str(msg.get("version", "v0.9")) not in A2UI_VERSIONS:
            errors.append(f"{where}: version must be \"v0.9\"")
        keys = [k for k in _MESSAGE_KEYS if k in msg]
        if len(keys) != 1:
            errors.append(f"{where}: needs exactly one of {', '.join(_MESSAGE_KEYS)}")
            continue
        key = keys[0]
        body = dict(msg[key] or {})
        sid = str(body.get("surfaceId") or "").strip()
        if not sid:
            errors.append(f"{where}.{key}: surfaceId is required")
            continue
        if key == "createSurface":
            rename[sid] = f"{sid}-{suffix}"
            created.add(sid)
            body["catalogId"] = BASIC_CATALOG_ID
        elif sid not in created:
            errors.append(f"{where}.{key}: surface {sid!r} must be created first (createSurface)")
            continue
        body["surfaceId"] = rename[sid]
        if key == "updateComponents":
            comps = body.get("components")
            if not isinstance(comps, list) or not comps:
                errors.append(f"{where}.updateComponents: components must be a non-empty array")
                continue
            for j, c in enumerate(comps):
                cw = f"{where}.updateComponents.components[{j}]"
                if not isinstance(c, dict) or not c.get("id"):
                    errors.append(f"{cw}: needs an id")
                    continue
                if c.get("component") not in BASIC_COMPONENTS:
                    errors.append(f"{cw}: unknown component {c.get('component')!r} — use one of "
                                  f"{', '.join(sorted(BASIC_COMPONENTS))} (see ui_guide)")
                    continue
                if c["component"] == "Button":
                    action = c.get("action") or {}
                    if not (isinstance(action, dict) and (
                            (action.get("event") or {}).get("name") or action.get("functionCall"))):
                        errors.append(f"{cw}: a Button needs action: {{\"event\": {{\"name\": ...}}}}")
                components[c["id"]] = c
            if len(components) > MAX_UI_COMPONENTS:
                errors.append(f"more than {MAX_UI_COMPONENTS} components")
        out.append({"version": "v0.9", key: body})
    if created and "root" not in components:
        errors.append("one component must have id \"root\"")
    for cid, c in components.items():
        refs = list(c.get("children") or []) if isinstance(c.get("children"), list) else []
        if c.get("child"):
            refs.append(c["child"])
        for ref in refs:
            if isinstance(ref, str) and ref not in components:
                errors.append(f"component {cid!r} references missing child {ref!r}")
    return out, errors


def _show_ui(args: dict) -> ToolResult:
    messages, errors = validate_a2ui(args.get("messages"))
    if errors:
        shown = "; ".join(errors[:8]) + (f" (+{len(errors) - 8} more)" if len(errors) > 8 else "")
        return ToolResult(ok=False, content="",
                          error=f"render_error: invalid A2UI — {shown}. Fix and call show_ui again.")
    payload = {"title": str(args.get("title") or "")[:120], "messages": messages}
    fence = "```a2ui\n" + json.dumps(payload) + "\n```"
    return ToolResult(ok=True, content=fence, data={"inline": fence})


UI_GUIDE = """A2UI v0.9 — build an interactive card/form with show_ui.

Send `messages`, an array, in this order:
1. {"version":"v0.9","createSurface":{"surfaceId":"s1"}}
2. {"version":"v0.9","updateComponents":{"surfaceId":"s1","components":[ ... ]}}
3. optional {"version":"v0.9","updateDataModel":{"surfaceId":"s1","path":"/","value":{...}}}

Components are a FLAT list; each has "id", "component" and its props. Exactly one
has id "root". Containers reference children by id: Row/Column/List use
"children": ["a","b"]; Card, Button and Modal use "child": "id".
Values can be literals or bound to the data model: {"path": "/form/name"}.
Inputs (TextField, CheckBox, ChoicePicker, Slider, DateTimeInput) write their
value to the bound path.

Basic catalogue:
- Text: text, variant (h1..h5 | body | caption)
- Image: url, description, fit
- Icon: name (e.g. "check", "mail", "warning")
- Row / Column: children, justify (start|center|end|spaceBetween|spaceAround|spaceEvenly|stretch),
  align (start|center|end|stretch)
- List: children, direction (vertical|horizontal), listStyle (ordered|unordered|none)
- Card: child · Divider: axis · Tabs: tabs [{title, child}] · Modal: trigger, content (ids)
- Button: child (a Text id), variant (default|primary|borderless), action
- TextField: label, value {"path"}, variant (shortText|longText|number|obscured)
- CheckBox: label, value {"path"} · Slider: label, value, min, max
- ChoicePicker: label, options [{label, value}], value {"path"} (a string list),
  variant (mutuallyExclusive|multipleSelection)
- DateTimeInput: value {"path"}, enableDate, enableTime, min, max

Button action: {"event": {"name": "submit_booking", "context": {"when": {"path": "/when"}}}}
When the user presses it you receive a message starting "[ui action]" with the
name and the resolved context. Reply to it like any message.

Example: a yes/no confirmation card
[{"version":"v0.9","createSurface":{"surfaceId":"confirm"}},
 {"version":"v0.9","updateComponents":{"surfaceId":"confirm","components":[
  {"id":"root","component":"Card","child":"col"},
  {"id":"col","component":"Column","children":["q","row"]},
  {"id":"q","component":"Text","text":"Delete the 3 old backups?","variant":"h4"},
  {"id":"row","component":"Row","children":["yes","no"]},
  {"id":"yes","component":"Button","child":"yes_t","variant":"primary",
   "action":{"event":{"name":"confirm_delete","context":{"answer":"yes"}}}},
  {"id":"yes_t","component":"Text","text":"Delete"},
  {"id":"no","component":"Button","child":"no_t",
   "action":{"event":{"name":"confirm_delete","context":{"answer":"no"}}}},
  {"id":"no_t","component":"Text","text":"Keep them"}]}}]

Use a UI only when the user must choose or fill something in. Never put
passwords or API keys in a UI: ask the user to use Settings → Security.
"""


def register(registry: ToolRegistry) -> None:
    registry.register(
        "render_visual",
        ("Show an INTERACTIVE visual inline in the chat — a small self-contained "
         "HTML page or SVG with inline <script>/<style> (no external URLs: the "
         "sandbox blocks all network). It appears exactly where you call this. "
         "For plain diagrams write a ```mermaid block instead, and for simple "
         "bar/line/pie charts a ```chart block."),
        {"type": "object", "properties": {
            "html": {"type": "string", "description": "self-contained HTML (or SVG markup)"},
            "title": {"type": "string", "description": "short caption"},
            "height": {"type": "integer", "description": "max height in px (default fits content)"},
        }, "required": ["html"]},
        _render_visual)
    registry.register(
        "show_ui",
        ("Show an interactive UI card in the chat (A2UI v0.9 JSON: forms, choice "
         "pickers, confirmations, option cards) rendered with the app's own "
         "components. Call ui_guide first for the component catalogue and format. "
         "The user's button presses come back as a '[ui action]' message."),
        {"type": "object", "properties": {
            "messages": {"type": "array", "items": {"type": "object"},
                         "description": "A2UI v0.9 messages: createSurface, updateComponents, updateDataModel"},
            "title": {"type": "string"},
        }, "required": ["messages"]},
        _show_ui)
    registry.register(
        "ui_guide",
        "The A2UI component catalogue and message format for show_ui (read it before your first show_ui).",
        {"type": "object", "properties": {}},
        lambda _args: ToolResult(ok=True, content=UI_GUIDE))
