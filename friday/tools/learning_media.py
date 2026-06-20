"""Learning-Room media tools: Mermaid diagrams, online images, HTML simulations.

Each writes a file under ``data/media/`` (served read-only at ``/api/media``) and
returns markdown that renders inline in the chat/Learning Room. Every file is a
downloadable artifact; when produced inside a learning topic it's also recorded
against that topic for the insights view.

Degrade gracefully: a missing ``mmdc`` or a failed network fetch returns a clear
error, never a crash.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
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


# ── Hybrid server-side render: API first, local fallback ─────────────────────
# Every diagram is rendered to a real PNG ON THE SERVER — the browser NEVER runs
# mermaid. Two methods, tried in order:
#   1. mermaid.ink — a hosted renderer. Zero local footprint, fast, no browser.
#   2. local render — mermaid-cli (the `mermaid_cli` Python package, which drives
#      a headless Chromium via Playwright) or the `mmdc` Node binary if present.
# Method 2 is the air-gapped safety net for when mermaid.ink is unreachable/down,
# so a diagram is produced even with no network. Both paths return raw PNG bytes
# that must pass `_verify_png_bytes` before anything reaches disk or the chat.
_INK_HOSTS = ("https://mermaid.ink", "https://mermaid-ink.fly.dev")
_INK_TIMEOUT = 20
# High-resolution, white-background output. On mermaid.ink `scale` MULTIPLIES
# `width`, so width=1400 × scale=3 ≈ a 4200px-wide PNG — crisp enough to zoom into
# in the image viewer without blur (the default endpoint returns ~400px, which is
# what looked fuzzy).
_INK_QUERY = "?type=png&bgColor=white&width=1400&scale=3"

# NO styling/theme directive is injected. The model writes the whole Mermaid source
# (declaration, nodes, edges, and any `%%{init}%%` it chooses) and we render it
# verbatim — Mermaid's clean default look, exactly what mermaid.ink produces. The
# only post-processing is image hygiene (white background + margin trim in
# `_finalize_png`), which is about the PNG, not the diagram's design.


def _render_via_ink(code: str) -> tuple[bytes | None, str]:
    """Method 1 — POST the diagram to mermaid.ink and get a PNG back. The source is
    URL-safe base64 in the path (mermaid.ink's documented contract). Returns
    (png_bytes, error); png_bytes is None on any failure so we fall through to local."""
    try:
        import requests  # optional dep; absence just means we skip to local render
    except Exception:  # noqa: BLE001
        return None, "requests not installed"
    enc = base64.urlsafe_b64encode(code.encode("utf-8")).decode("ascii")
    last = "mermaid.ink unreachable"
    for host in _INK_HOSTS:
        url = f"{host}/img/{enc}{_INK_QUERY}"
        try:
            r = requests.get(url, timeout=_INK_TIMEOUT)
        except Exception as exc:  # noqa: BLE001
            last = f"mermaid.ink request failed: {exc}"
            continue
        if r.status_code == 200 and _verify_png_bytes(r.content):
            return r.content, ""
        last = f"mermaid.ink returned {r.status_code}"
    return None, last


def _run_coro(coro, timeout: float = 75.0):
    """Run an async coroutine to completion from sync code, regardless of whether an
    event loop is already running in this thread — we spin a dedicated thread with a
    fresh loop. (The server runs turns off the main loop, but this keeps the render
    safe to call from anywhere, including the async context.)

    Bounded by ``timeout`` so a wedged headless browser can NEVER hang the whole
    turn: if the render thread doesn't finish in time we raise, the caller falls
    through to the next render method / text outline, and the daemon thread is left
    to die with the process."""
    box: dict = {}

    def runner():
        try:
            box["v"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            box["e"] = exc

    t = threading.Thread(target=runner, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"local render exceeded {timeout:.0f}s")
    if "e" in box:
        raise box["e"]
    return box.get("v")


def _render_via_local(code: str, out_path: Path) -> tuple[bytes | None, str]:
    """Method 2 — render locally with no network. Prefer the `mermaid_cli` Python
    package (bundled Playwright/Chromium); fall back to the `mmdc` Node binary if it
    is on PATH. Returns (png_bytes, error)."""
    # 2a — the Python mermaid-cli package (cross-platform, pip-installable).
    try:
        from mermaid_cli import render_mermaid  # type: ignore
    except Exception:  # noqa: BLE001
        render_mermaid = None
    if render_mermaid is not None:
        try:
            # A large, hi-DPI viewport for a crisp render (the styling/scale also rides
            # in the source's %%{init}%% directive, so it looks the same as the API path).
            _, _, data = _run_coro(render_mermaid(
                code, output_format="png", background_color="white",
                viewport={"width": 1400, "height": 1000, "deviceScaleFactor": 3}))
            if _verify_png_bytes(data):
                return data, ""
            return None, "mermaid_cli produced an invalid/empty PNG"
        except Exception as exc:  # noqa: BLE001
            logger.warning("[learning_media] mermaid_cli render failed: %s", str(exc)[:200])
            # fall through to the binary

    # 2b — the `mmdc` Node binary, retried once (puppeteer fails transiently).
    mmdc = _mmdc()
    if not mmdc:
        return None, "mermaid-cli not installed (pip install mermaid-cli)"
    last_err = ""
    for attempt in (1, 2):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "d.mmd"
            src.write_text(code, encoding="utf-8")
            cfg = Path(tmp) / "pp.json"
            cfg.write_text(json.dumps({"args": ["--no-sandbox"]}), encoding="utf-8")
            env = dict(os.environ)
            for cand in ("/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome"):
                if Path(cand).exists():
                    env.setdefault("PUPPETEER_EXECUTABLE_PATH", cand)
                    break
            cmd = [mmdc, "-i", str(src), "-o", str(out_path),
                   "-w", "2048", "-H", "1536", "-s", "4", "-b", "white", "-p", str(cfg)]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                                      env=env, encoding="utf-8", errors="replace")
            except subprocess.TimeoutExpired:
                last_err = "diagram render timed out"
                continue
            produced = _locate_output(out_path)
            if proc.returncode == 0 and produced is not None and _verify_png(produced):
                try:
                    data = produced.read_bytes()
                finally:
                    if produced != out_path:
                        produced.unlink(missing_ok=True)
                return data, ""
            last_err = (proc.stderr or "").strip()[:200] or "render produced an invalid/empty PNG"
            logger.warning("[learning_media] mmdc attempt %d failed: %s", attempt, last_err[:300])
    return None, last_err or "local render failed"


# PNG signature + minimum plausible size for a real diagram (mmdc can emit a
# 0-byte or truncated file when puppeteer dies mid-render; that file would 404 /
# show broken in the chat). We never hand a URL to the chat unless the bytes on
# disk are a genuine, non-degenerate PNG.
_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _verify_png_bytes(data: bytes) -> bool:
    """True only for a real, decodable PNG with non-zero dimensions — applied to the
    raw bytes BEFORE they ever touch disk or the chat. This is the server-side
    verification gate: a diagram is placed in the chat ONLY after we confirm the
    rendered image is valid, so the learner never sees a broken/blank image and
    never has to re-render client-side."""
    if not data or len(data) < 256:  # a valid diagram PNG is comfortably larger
        return False
    head = data[:24]  # 8-byte sig + IHDR length/type + width/height
    if len(head) < 24 or head[:8] != _PNG_SIG or head[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", head[16:24])
    return width > 0 and height > 0


def _finalize_png(data: bytes) -> bytes:
    """Make a raw rendered PNG chat-ready: flatten any transparency onto a solid
    WHITE background and trim the empty margins.

    mermaid.ink returns a TRANSPARENT PNG with the diagram sitting in a large empty
    canvas — which made the picture (a) look microscopic in the chat (mostly margin)
    and (b) lose its dark lines/text on any dark backdrop. Flattening bakes in a
    white background so the node-connection lines are always visible regardless of
    theme; trimming removes the dead margin so the diagram fills its frame.

    Best-effort: if Pillow isn't installed or anything goes wrong, the original
    bytes are returned unchanged (the diagram still shows, just un-trimmed)."""
    try:
        import io

        from PIL import Image, ImageChops
    except Exception:  # noqa: BLE001 — Pillow optional
        return data
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
        white = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
            rgba = img.convert("RGBA")
            white.paste(rgba, mask=rgba.split()[-1])
        else:
            white.paste(img.convert("RGB"))
        # Trim the white margin down to the diagram, leaving a small even border.
        bbox = ImageChops.difference(white, Image.new("RGB", white.size, (255, 255, 255))).getbbox()
        if bbox:
            pad = 28
            l, t, r, b = bbox
            white = white.crop((max(0, l - pad), max(0, t - pad),
                                min(white.size[0], r + pad), min(white.size[1], b + pad)))
        out = io.BytesIO()
        white.save(out, "PNG", optimize=True)
        result = out.getvalue()
        # Header check only — NOT _verify_png_bytes' 256-byte floor, which exists to
        # catch truncated *renders*; a legitimately tiny trimmed diagram can be smaller.
        return result if result[:8] == _PNG_SIG else data
    except Exception as exc:  # noqa: BLE001
        logger.warning("[learning_media] PNG finalize skipped: %s", str(exc)[:160])
        return data


def _verify_png(path: Path) -> bool:
    """Same gate as :func:`_verify_png_bytes`, reading the header off disk."""
    try:
        if path.stat().st_size < 256:
            return False
        with path.open("rb") as fh:
            head = fh.read(24)
    except OSError:
        return False
    if len(head) < 24 or head[:8] != _PNG_SIG or head[12:16] != b"IHDR":
        return False
    width, height = struct.unpack(">II", head[16:24])
    return width > 0 and height > 0


# ── Model-authored Mermaid ──────────────────────────────────────────────────
# The model writes the Mermaid source itself (modern models are reliable at this
# when given strict rules + examples — see the tool description). We render that
# source verbatim, with NO theme/node styling injected. The only things we touch
# are robustness niceties: stripping a ```mermaid fence the model may wrap the code
# in, and a light sanity check that it actually looks like a diagram.

# The keywords a Mermaid diagram's FIRST real line must begin with. Used only as a
# guardrail against the model passing prose / JSON instead of diagram source — not
# an exhaustive grammar (Mermaid itself is the real validator at render time).
_MERMAID_HEADS = (
    "graph", "flowchart", "sequencediagram", "classdiagram", "statediagram",
    "erdiagram", "journey", "gantt", "pie", "mindmap", "timeline", "gitgraph",
    "quadrantchart", "requirementdiagram", "c4context", "c4container",
    "c4component", "sankey", "xychart", "block-beta", "packet-beta",
)


def _clean_code(code: str) -> str:
    """Normalise the model's Mermaid source: strip a wrapping ```mermaid / ``` fence
    (models love to add one) and surrounding whitespace, so it renders verbatim."""
    t = (code or "").strip()
    if t.startswith("```"):
        t = t[3:]
        if t[:7].lower().startswith("mermaid"):
            t = t[7:]
        if t.endswith("```"):
            t = t[:-3]
    return t.strip()


def _looks_like_mermaid(code: str) -> bool:
    """True if the first meaningful line opens with a known diagram declaration —
    catching the case where the model passes prose or JSON instead of Mermaid."""
    for raw in code.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%"):  # skip blanks + %%{init}%% / comments
            continue
        head = re.split(r"[\s({]", line, maxsplit=1)[0].lower()
        return head in _MERMAID_HEADS
    return False


# The tool description doubles as the model's Mermaid spec: strict rules + worked
# examples so the source it writes renders first time. Kept here (not inline in
# register) so it's easy to extend with more examples as failure modes show up.
_DIAGRAM_TOOL_DESC = """\
Draw a diagram and show it inline as a crisp, downloadable PNG. YOU write the \
Mermaid source in `code`; we render it server-side and display the image. Use this \
for EVERY structure, flow, hierarchy, sequence, or relationship worth a picture.

STRICT MERMAID RULES — follow exactly so it renders the first time:
1. Put ONLY raw Mermaid in `code`. No prose, no Markdown, no ``` fences.
2. The FIRST line is the diagram declaration, e.g. `flowchart TD`, `sequenceDiagram`, \
`classDiagram`, `stateDiagram-v2`, `erDiagram`, `mindmap`, `timeline`. One statement \
per line.
3. Node ids are short and alphanumeric (A, B, db, api). Put human text in the LABEL, \
not the id: `A["User signs in"]`.
4. ALWAYS quote a label that contains spaces, punctuation, parentheses, slashes, or \
quotes: `B["Validate (email + password)"]`. For a line break inside a label use \
`<br/>`. Never put a raw `"` inside a quoted label — rephrase or drop it.
5. Don't use Mermaid reserved words as ids (`end`, `graph`, `class`, `state`, \
`subgraph`, `click`, `style`). Capitalise or rename: `End`, `node_end`.
6. Flowchart edges: `A --> B`, labelled `A -->|"yes"| B`. Decisions use a diamond: \
`C{"Valid?"}`.
7. Sequence: declare `participant X as Label` (no quotes on the alias), then \
`A->>B: message` (solid) / `B-->>A: reply` (dashed). Group with \
`alt`/`else`/`end`, `loop`/`end`, `opt`/`end`, and `Note over A,B: text`.
8. Keep it focused — the fewest nodes that carry the idea. Do NOT add any color, \
class, or style directives; the clean default look is intended.

EXAMPLES (copy the shape):

Flowchart with a decision:
flowchart TD
    A["User submits form"] --> B{"All fields valid?"}
    B -->|"yes"| C["Save to database"]
    B -->|"no"| D["Show error message"]
    C --> E["Show success"]

Hierarchy / breakdown (top-down tree):
flowchart TD
    Root["Machine Learning"] --> S["Supervised"]
    Root --> U["Unsupervised"]
    Root --> R["Reinforcement"]
    S --> S1["Classification"]
    S --> S2["Regression"]

Sequence (interaction over time):
sequenceDiagram
    autonumber
    actor User
    participant API as Auth Server
    participant DB as Database
    User->>API: POST /login (credentials)
    API->>DB: look up user
    DB-->>API: password hash
    alt valid
        API-->>User: 200 OK + token
    else invalid
        API-->>User: 401 Unauthorized
    end

State machine:
stateDiagram-v2
    [*] --> Idle
    Idle --> Loading: fetch()
    Loading --> Success: 200
    Loading --> Error: failure
    Success --> [*]
    Error --> Idle: retry

Mind map (radial concept map):
mindmap
    root(("Photosynthesis"))
        Inputs
            Sunlight
            Water
            CO2
        Outputs
            Glucose
            Oxygen
"""


def _render_diagram(args: dict) -> ToolResult:
    title = (args.get("title") or "Diagram").strip()
    code = _clean_code(args.get("code") or "")
    if not code:
        return ToolResult(ok=False, content="", error="'code' (Mermaid diagram source) is required")
    if not _looks_like_mermaid(code):
        return ToolResult(
            ok=False, content="",
            error="'code' must be valid Mermaid source — the first line has to be a "
                  "diagram declaration (e.g. 'flowchart TD', 'sequenceDiagram', "
                  "'classDiagram', 'mindmap'). Don't pass prose or JSON.")

    out_dir = _media_dir("diagrams")
    name = f"{uuid.uuid4().hex}.png"
    out_path = out_dir / name

    # Hybrid render, all server-side: hosted API first, local renderer as the
    # offline/down fallback. The model's source is rendered AS-IS (no styling
    # injected). Bytes are verified BEFORE they touch disk, so the chat only ever
    # sees a real, decodable PNG. The browser NEVER renders mermaid.
    data, api_err = _render_via_ink(code)
    local_err = ""
    source = "mermaid.ink"
    if data is None:
        logger.info("[learning_media] mermaid.ink unavailable (%s) — rendering locally", api_err)
        data, local_err = _render_via_local(code, out_path)
        source = "local renderer"
    if data is not None:
        # Flatten onto white + trim margins so the diagram fills its frame and its
        # lines stay visible on any theme (mermaid.ink hands back a padded transparent PNG).
        out_path.write_bytes(_finalize_png(data))
        url = f"/api/media/diagrams/{name}"
        record_artifact("diagram", url, title)
        logger.info("[learning_media] diagram rendered server-side via %s", source)
        content = f"![{title}]({url})\n\n*{title}* · [⬇ Download diagram]({url})"
        return ToolResult(ok=True, content=content, data={"url": url, "kind": "diagram"})

    # BOTH render methods failed (e.g. mermaid.ink rejected the syntax AND no local
    # renderer is installed). Surface the failure so the model can fix its Mermaid and
    # retry — a malformed diagram is now possible (the model authors the source), so
    # an honest error beats silently swallowing it.
    logger.warning("[learning_media] no server PNG (api: %s; local: %s)", api_err, local_err)
    return ToolResult(
        ok=False, content="",
        error=f"diagram render failed (mermaid.ink: {api_err}; local: {local_err}). "
              "If this looks like a syntax error, fix the Mermaid and call render_diagram again.")


def _fetch_image(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="'query' is required")
    # Ask for several LARGE candidates (not one tiny thumbnail) so we can pick the
    # highest-resolution hit — small images were what looked poor in the viewer.
    api = "https://api.openverse.org/v1/images/?" + urllib.parse.urlencode(
        {"q": query, "page_size": 12, "license_type": "all", "size": "large",
         "mature": "false"})
    req = urllib.request.Request(api, headers={"User-Agent": "FRIDAY-LearningRoom/2.0"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"image search failed: {exc}")
    results = payload.get("results") or []
    if not results:
        return ToolResult(ok=True, content=f"No images found for “{query}”.")

    def _area(h: dict) -> int:
        try:
            return int(h.get("width") or 0) * int(h.get("height") or 0)
        except (TypeError, ValueError):
            return 0
    # Prefer the largest real-resolution result; ties/unknowns keep search order.
    hit = max(results, key=_area) if any(_area(h) for h in results) else results[0]
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
        _DIAGRAM_TOOL_DESC,
        {
            "type": "object",
            "properties": {
                "code": {"type": "string",
                         "description": "the complete Mermaid diagram source (see the rules "
                                        "and examples in this tool's description)"},
                "title": {"type": "string", "description": "short caption shown under the diagram"},
            },
            "required": ["code", "title"],
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
