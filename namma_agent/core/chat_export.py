"""Chat export: bundle a session's transcript + its generated media into a zip.

The zip a user downloads from the sidebar's "Download chat" contains:

    chat.md            — the whole conversation as readable markdown
    media/<rel path>   — every /api/media/<rel> file the chat references
                         (diagrams, fetched images, simulations, …)

Media links inside ``chat.md`` are rewritten from ``/api/media/<rel>`` to the
relative ``media/<rel>`` entries, so the transcript renders offline exactly as
it did in the app. Files that no longer exist on disk are simply skipped (the
link is left pointing into ``media/`` — a shared zip degrades gracefully rather
than failing to build).

Pure functions over ``session_turns()`` rows — no FastAPI, no DB handle — so
the whole pipeline is unit-testable offline.
"""
from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

MEDIA_ROOT = Path("data/media")

# Same shape the agent/telegram layers use: any /api/media/<rel> reference,
# markdown or bare, with query/fragment tolerated.
_MEDIA_URL_RE = re.compile(r"/api/media/[^)\s\"'<>]+")

# Internal plumbing turns the UI also hides — a shared transcript doesn't need
# the raw "[quiz answer] …" continuation (the quiz card shows the pick).
_PLUMBING_PREFIXES = ("[quiz answer]", "[build path]")


def _media_rel(url: str) -> str:
    """`/api/media/diagrams/x.png?v=2` → `diagrams/x.png`."""
    return url[len("/api/media/"):].split("?", 1)[0].split("#", 1)[0]


def collect_media(turns: list[dict], media_root: Path = MEDIA_ROOT) -> dict[str, Path]:
    """Every media file the chat references that actually exists on disk, keyed by
    its relative path inside the zip's ``media/`` folder. Traversal-safe: a
    reference that escapes the media root is ignored."""
    root = media_root.resolve()
    out: dict[str, Path] = {}
    for t in turns:
        for url in _MEDIA_URL_RE.findall(t.get("content") or ""):
            rel = _media_rel(url)
            if not rel or rel in out:
                continue
            try:
                path = (media_root / rel).resolve()
                if path.is_file() and path.is_relative_to(root):
                    out[rel] = path
            except (OSError, ValueError):
                continue
    return out


def _rewrite_media_links(text: str) -> str:
    """Point every /api/media/<rel> reference at the zip's ``media/`` folder."""
    return _MEDIA_URL_RE.sub(lambda m: "media/" + _media_rel(m.group(0)), text)


def _fmt_when(created_at: Optional[str]) -> str:
    """Turn's stored timestamp → a short human stamp (best effort)."""
    if not created_at:
        return ""
    try:
        return datetime.fromisoformat(str(created_at)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(created_at)


def _render_quiz(content: str) -> str:
    """A persisted quiz turn (JSON) → a readable card in the transcript."""
    try:
        quiz = json.loads(content or "{}")
    except ValueError:
        return ""
    question = (quiz.get("question") or "").strip()
    if not question:
        return ""
    lines = [f"> **Quiz:** {question}"]
    answer_idx = quiz.get("answer_index")
    for i, opt in enumerate(quiz.get("options") or []):
        mark = " ✓" if i == answer_idx else ""
        lines.append(f"> {i + 1}. {opt}{mark}")
    return "\n".join(lines)


def derive_title(turns: list[dict], meta: Optional[dict]) -> str:
    """Chat title: the custom rename, else the first user message, else a stub —
    mirrors what the sidebar shows."""
    title = ((meta or {}).get("title") or "").strip()
    if not title:
        first = next((t.get("content") or "" for t in turns
                      if t.get("role") == "user"
                      and not (t.get("content") or "").startswith(_PLUMBING_PREFIXES)), "")
        title = first.strip().split("\n", 1)[0]
    title = title.strip()
    if len(title) > 60:
        title = title[:60] + "…"
    return title or "Chat"


def render_markdown(turns: list[dict], meta: Optional[dict],
                    assistant_name: str = "Assistant") -> str:
    """The whole conversation as one markdown document, media links rewritten to
    the zip-relative ``media/`` folder."""
    meta = meta or {}
    title = derive_title(turns, meta)
    header = [f"# {title}", ""]
    info = []
    if meta.get("created_at"):
        info.append(f"started {_fmt_when(meta['created_at'])}")
    if (meta.get("model") or "").strip():
        info.append(f"model `{meta['model'].strip()}`")
    info.append(f"exported {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    header.append(f"*Chat with {assistant_name} — " + " · ".join(info) + "*")

    blocks: list[str] = ["\n".join(header)]
    for t in turns:
        role = t.get("role") or ""
        content = (t.get("content") or "").strip()
        if role == "user" and content.startswith(_PLUMBING_PREFIXES):
            continue
        if role == "quiz":
            body = _render_quiz(content)
            if body:
                blocks.append(body)
            continue
        if role not in ("user", "assistant") or not content:
            continue
        who = "You" if role == "user" else assistant_name
        when = _fmt_when(t.get("created_at"))
        stamp = f" · {when}" if when else ""
        blocks.append(f"**{who}**{stamp}\n\n{_rewrite_media_links(content)}")
    return "\n\n---\n\n".join(blocks) + "\n"


def export_filename(turns: list[dict], meta: Optional[dict]) -> str:
    """ASCII-safe zip name from the chat title (Content-Disposition friendly)."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", derive_title(turns, meta)).strip("-").lower()
    return f"{slug or 'chat'}.zip"


def build_chat_zip(turns: list[dict], meta: Optional[dict],
                   assistant_name: str = "Assistant",
                   media_root: Path = MEDIA_ROOT) -> tuple[str, bytes]:
    """The downloadable archive: ``chat.md`` + the referenced ``media/`` files.
    Returns ``(filename, zip bytes)``."""
    md = render_markdown(turns, meta, assistant_name)
    media = collect_media(turns, media_root)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("chat.md", md)
        for rel, path in media.items():
            zf.write(path, "media/" + rel.replace("\\", "/"))
    return export_filename(turns, meta), buf.getvalue()
