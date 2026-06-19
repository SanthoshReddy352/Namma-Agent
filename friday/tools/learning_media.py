"""Learning-Room media tools: Mermaid diagrams, online images, HTML simulations.

Each writes a file under ``data/media/`` (served read-only at ``/api/media``) and
returns markdown that renders inline in the chat/Learning Room. Every file is a
downloadable artifact; when produced inside a learning topic it's also recorded
against that topic for the insights view.

Degrade gracefully: a missing ``mmdc`` or a failed network fetch returns a clear
error, never a crash.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from friday.core.interactive import record_artifact
from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult

_MEDIA = Path("data/media")
_TIMEOUT = 12


def _media_dir(kind: str) -> Path:
    d = _MEDIA / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mmdc() -> str | None:
    return shutil.which("mmdc") or (
        str(Path.home() / ".npm-global/bin/mmdc")
        if (Path.home() / ".npm-global/bin/mmdc").exists() else None)


def _locate_output(out_path: Path) -> Path | None:
    """The file mmdc actually produced: the requested path, or the `-1`-suffixed
    variant some mermaid-cli versions emit. None when nothing was written."""
    if out_path.exists():
        return out_path
    suffixed = out_path.with_name(f"{out_path.stem}-1{out_path.suffix}")
    return suffixed if suffixed.exists() else None


# PNG signature + minimum plausible size for a real diagram (mmdc can emit a
# 0-byte or truncated file when puppeteer dies mid-render; that file would 404 /
# show broken in the chat). We never hand a URL to the chat unless the bytes on
# disk are a genuine, non-degenerate PNG.
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _verify_png(path: Path) -> bool:
    """True only for a real, decodable PNG with non-zero dimensions. This is the
    server-side verification gate: a diagram is placed in the chat ONLY after we
    confirm the rendered image is valid, so the learner never sees a broken/blank
    image and never has to re-render client-side."""
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < 256:  # a valid diagram PNG is comfortably larger than this
        return False
    try:
        with path.open("rb") as fh:
            head = fh.read(24)  # 8-byte sig + IHDR length/type + width/height
    except OSError:
        return False
    if len(head) < 24 or head[:8] != _PNG_SIG or head[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", head[16:24])
    return width > 0 and height > 0


# ── Foolproof diagram generation ────────────────────────────────────────────
# The model never writes Mermaid syntax (that's what produced broken diagrams —
# quotes / parentheses / commas inside node labels crash the parser). It picks one
# of a few CLASSICAL diagram types and supplies only labels + relationships as
# structured data; WE generate guaranteed-valid Mermaid with every label safely
# quoted. Result: a render can fail transiently, but never from bad syntax.

_DIAGRAM_TYPES = ("flowchart", "tree", "sequence")


def _safe_label(text: str) -> str:
    """A node/edge label that can never break the Mermaid flowchart parser:
    wrapped in quotes by the caller, with inner quotes escaped to the HTML entity
    Mermaid understands and newlines turned into <br/>."""
    t = (text or "").strip().replace("\r", " ")
    t = t.replace('"', "#quot;")
    t = re.sub(r"\s*\n\s*", "<br/>", t)
    t = re.sub(r"[ \t]+", " ", t)
    return t or " "


def _seq_text(text: str) -> str:
    """Sequence message text: ';' and newlines are statement separators in Mermaid,
    so neutralise them; everything else is safe after the colon."""
    t = (text or "").replace("\r", " ")
    t = re.sub(r"\s*\n\s*", " ", t).replace(";", ",")
    t = re.sub(r"[ \t]+", " ", t).strip()
    return t or "…"


def _build_flow(links: list[dict], nodes_extra: list[str], direction: str) -> str:
    """A flowchart / hierarchy from edges. ``links`` are {from,to,label?} using the
    human labels themselves; we assign safe ids so the model can never mismatch one."""
    seen: dict[str, str] = {}
    order: list[str] = []

    def nid(label: str) -> str:
        label = (label or "").strip()
        if label not in seen:
            seen[label] = f"n{len(seen)}"
            order.append(label)
        return seen[label]

    for lab in nodes_extra or []:
        if (lab or "").strip():
            nid(lab)
    edges: list[str] = []
    for lk in links or []:
        frm, to = (lk.get("from") or "").strip(), (lk.get("to") or "").strip()
        if not frm or not to:
            continue
        a, b = nid(frm), nid(to)
        lbl = (lk.get("label") or "").strip()
        edges.append(f'    {a} -->|"{_safe_label(lbl)}"| {b}' if lbl else f"    {a} --> {b}")
    lines = [f"graph {direction}"]
    lines += [f'    {seen[l]}["{_safe_label(l)}"]' for l in order]
    lines += edges
    return "\n".join(lines)


def _build_sequence(steps: list[dict]) -> str:
    seen: dict[str, str] = {}
    decls: list[str] = []
    body: list[str] = []

    def pid(name: str) -> str:
        name = (name or "").strip() or "?"
        if name not in seen:
            seen[name] = f"p{len(seen)}"
            decls.append(f'    participant {seen[name]} as "{_safe_label(name)}"')
        return seen[name]

    for s in steps or []:
        frm, to = (s.get("from") or "").strip(), (s.get("to") or "").strip()
        if not frm or not to:
            continue
        body.append(f"    {pid(frm)}->>{pid(to)}: {_seq_text(s.get('text'))}")
    return "sequenceDiagram\n" + "\n".join(decls + body)


def _build_mermaid(args: dict) -> tuple[str, str]:
    """(mermaid_source, error). One non-empty; never both."""
    dtype = (args.get("type") or "flowchart").strip().lower()
    if dtype not in _DIAGRAM_TYPES:
        return "", f"'type' must be one of {', '.join(_DIAGRAM_TYPES)}"
    if dtype == "sequence":
        steps = args.get("steps") or []
        if not steps:
            return "", "a sequence diagram needs 'steps' ([{from,to,text}, …])"
        return _build_sequence(steps), ""
    # flowchart / tree share the edge-based builder; a tree is just top-down.
    links = args.get("links") or []
    nodes = args.get("nodes") or []
    if not links and len(nodes) < 2:
        return "", "a flowchart/tree needs 'links' ([{from,to,label?}, …])"
    direction = "TD" if dtype == "tree" else (args.get("direction") or "TD").upper()
    if direction not in ("TD", "LR"):
        direction = "TD"
    return _build_flow(links, nodes, direction), ""


def _outline_fallback(args: dict, title: str) -> str:
    """A clean text rendering of the SAME structured data, used only when the image
    render fails (rare, transient). Keeps the lesson moving — never a broken image."""
    dtype = (args.get("type") or "flowchart").strip().lower()
    lines = [f"**{title}**"]
    if dtype == "sequence":
        for s in args.get("steps") or []:
            frm, to = (s.get("from") or "?").strip(), (s.get("to") or "?").strip()
            txt = (s.get("text") or "").strip()
            lines.append(f"- **{frm} → {to}:** {txt}" if txt else f"- **{frm} → {to}**")
    else:
        for lk in args.get("links") or []:
            frm, to = (lk.get("from") or "?").strip(), (lk.get("to") or "?").strip()
            lbl = (lk.get("label") or "").strip()
            lines.append(f"- {frm} → *{lbl}* → {to}" if lbl else f"- {frm} → {to}")
    return "\n".join(lines)


def _render_diagram(args: dict) -> ToolResult:
    title = (args.get("title") or "Diagram").strip()
    code, err = _build_mermaid(args)
    if err:
        return ToolResult(ok=False, content="", error=err)

    mmdc = _mmdc()
    produced: Path | None = None
    out_dir = _media_dir("diagrams")
    name = f"{uuid.uuid4().hex}.png"
    out_path = out_dir / name
    last_err = "mermaid-cli (mmdc) not installed" if not mmdc else ""
    # mmdc/puppeteer fails transiently under load — one retry absorbs most of it.
    if mmdc:
        for attempt in (1, 2):
            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "d.mmd"
                src.write_text(code, encoding="utf-8")
                cfg = Path(tmp) / "pp.json"
                cfg.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
                env = dict(os.environ)
                # Use the system Chromium for puppeteer if mmdc's bundled one is absent.
                for cand in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
                    if Path(cand).exists():
                        env.setdefault("PUPPETEER_EXECUTABLE_PATH", cand)
                        break
                # 4× scale on a 2048×1536 canvas for crisp, downloadable artifacts.
                cmd = [mmdc, "-i", str(src), "-o", str(out_path),
                       "-w", "2048", "-H", "1536", "-s", "4", "-b", "white", "-p", str(cfg)]
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                                          env=env, encoding="utf-8", errors="replace")
                    last_err = (proc.stderr or "").strip()[:200]
                except subprocess.TimeoutExpired:
                    last_err = "diagram render timed out"
                    continue
                produced = _locate_output(out_path)
                # The image is placed in the chat ONLY after server-side verification
                # that the bytes are a real, decodable PNG — a 0 returncode is not
                # enough (puppeteer can exit clean having written a truncated file).
                if proc.returncode == 0 and produced is not None and _verify_png(produced):
                    break
                if produced is not None and not _verify_png(produced):
                    last_err = (last_err or "render produced an invalid/empty PNG")
                produced = None
                logger.warning("[learning_media] mmdc attempt %d failed: %s", attempt, last_err[:300])

    if produced is not None:
        if produced != out_path:  # normalize the `-1`-suffixed name to the URL we return
            produced.rename(out_path)
        url = f"/api/media/diagrams/{name}"
        record_artifact("diagram", url, title)
        content = f"![{title}]({url})\n\n*{title}* · [⬇ Download diagram]({url})"
        return ToolResult(ok=True, content=content, data={"url": url, "kind": "diagram"})

    # Render unavailable (no mmdc, or a transient puppeteer failure). The syntax is
    # valid by construction, so this is never the model's fault — degrade to a clean
    # text outline of the same data and KEEP TEACHING. ok=True so the turn (and any
    # follow-up quiz) is never derailed by a missing picture.
    logger.warning("[learning_media] diagram fell back to text outline: %s", last_err)
    outline = _outline_fallback(args, title)
    return ToolResult(ok=True, content=outline,
                      data={"inline": outline, "kind": "diagram", "fallback": True})


def _fetch_image(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="'query' is required")
    api = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "page_size": 1, "license_type": "all"})
    req = urllib.request.Request(api, headers={"User-Agent": "FRIDAY-LearningRoom/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"image search failed: {exc}")
    results = payload.get("results") or []
    if not results:
        return ToolResult(ok=True, content=f"No images found for “{query}”.")
    hit = results[0]
    img_url = hit.get("url")
    creator = hit.get("creator") or "unknown"
    lic = (hit.get("license") or "").upper()
    try:
        ireq = urllib.request.Request(img_url, headers={"User-Agent": "FRIDAY-LearningRoom/2.0"})
        with urllib.request.urlopen(ireq, timeout=_TIMEOUT) as r:
            data = r.read()
            ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
                   "image/gif": "gif"}.get(r.headers.get("Content-Type", "").split(";")[0], "jpg")
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"image download failed: {exc}")
    name = f"{uuid.uuid4().hex}.{ext}"
    (_media_dir("images") / name).write_bytes(data)
    url = f"/api/media/images/{name}"
    record_artifact("image", url, hit.get("title") or query)
    caption = f"*{hit.get('title') or query}* — by {creator}" + (f" ({lic})" if lic else "")
    content = f"![{query}]({url})\n\n{caption} · [⬇ Download]({url})"
    return ToolResult(ok=True, content=content, data={"url": url, "kind": "image"})


def _render_simulation(args: dict) -> ToolResult:
    html = args.get("html") or ""
    title = (args.get("title") or "Interactive simulation").strip()
    if "<" not in html:
        return ToolResult(ok=False, content="", error="'html' (a self-contained HTML document) is required")
    name = f"{uuid.uuid4().hex}.html"
    (_media_dir("sims") / name).write_text(html, encoding="utf-8")
    url = f"/api/media/sims/{name}"
    record_artifact("simulation", url, title)
    # Every chat renders /api/media/sims/* links as a playable, sandboxed iframe
    # card right inline (with an expand-to-fullscreen control) — the learner runs
    # the simulation in place, never bounced to a separate browser tab.
    content = f"[▶ Open interactive simulation — {title}]({url})"
    return ToolResult(ok=True, content=content, data={"url": url, "kind": "simulation"})


def register(registry: ToolRegistry) -> None:
    registry.register(
        "render_diagram",
        "Draw a clear diagram and show it inline (crisp, downloadable). You do NOT "
        "write diagram code — just pick a type and give the labels + relationships; "
        "the diagram is built for you, so it can never come out malformed. Types:\n"
        "• 'flowchart' — a process / relationship: pass `links` [{from,to,label?}] "
        "(node labels are the plain text; optional `direction` 'TD' or 'LR').\n"
        "• 'tree' — a hierarchy / breakdown (X splits into A, B): pass `links` "
        "[{from,to}] from parent to child.\n"
        "• 'sequence' — a step-by-step interaction over time: pass `steps` "
        "[{from,to,text}].\n"
        "Keep labels short. Use this for EVERY major concept worth a visual.",
        {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": list(_DIAGRAM_TYPES),
                         "description": "flowchart | tree | sequence"},
                "title": {"type": "string", "description": "short caption"},
                "direction": {"type": "string", "enum": ["TD", "LR"],
                              "description": "flowchart layout (top-down or left-right)"},
                "links": {"type": "array", "description": "flowchart/tree edges",
                          "items": {"type": "object", "properties": {
                              "from": {"type": "string"}, "to": {"type": "string"},
                              "label": {"type": "string"}}, "required": ["from", "to"]}},
                "nodes": {"type": "array", "items": {"type": "string"},
                          "description": "optional standalone flowchart node labels"},
                "steps": {"type": "array", "description": "sequence messages",
                          "items": {"type": "object", "properties": {
                              "from": {"type": "string"}, "to": {"type": "string"},
                              "text": {"type": "string"}}, "required": ["from", "to", "text"]}},
            },
            "required": ["type", "title"],
        },
        _render_diagram,
    )
    registry.register(
        "fetch_image",
        "Find a real, license-clean photo/illustration online (Openverse) and show it "
        "inline as a downloadable artifact. Use to build visual intuition.",
        {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "what to picture, e.g. 'water cycle'"}},
            "required": ["query"],
        },
        _fetch_image,
    )
    registry.register(
        "render_simulation",
        "Build a self-contained interactive HTML/JS simulation (one full <html> document, "
        "all CSS/JS inline) — it plays INLINE in the chat in a sandboxed, expandable frame, "
        "so the user experiences it right here without ever leaving for a browser tab. Reach "
        "for this whenever hands-on interaction or motion teaches better than a static "
        "picture: sliders that change a graph, a clickable diagram, a physics/animation demo, "
        "a step-through visualizer, a tiny playground. Make it self-explanatory with on-screen "
        "controls and labels.",
        {
            "type": "object",
            "properties": {
                "html": {"type": "string", "description": "a complete self-contained HTML document"},
                "title": {"type": "string", "description": "short title"},
            },
            "required": ["html"],
        },
        _render_simulation,
    )
