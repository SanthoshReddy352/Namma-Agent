"""Telegram channel — outbound notifications + an inbound chat bridge.

Stdlib-only (urllib). Tokens live in the environment, never in config:
  NAMMA_TELEGRAM_TOKEN, NAMMA_TELEGRAM_CHAT_ID

Outbound: :meth:`TelegramChannel.send` (async, markdown→Telegram HTML, chunked).
Inbound:  :class:`TelegramInbound` long-polls getUpdates and routes each text
message through the shared :class:`~namma_agent.comms.inbound.InboundBridge`
(commands, model picker, askpass, turns), replying in-chat. This subclass adds
only the Telegram transport: the poller, reply quoting, the typing indicator,
password scrubbing, and voice/document handling.
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import urllib.request
import uuid
from html import escape as _html_escape
from pathlib import Path
from typing import Callable, Optional

from namma_agent.comms.inbound import InboundBridge
from namma_agent.core.logger import logger

_MAX_CHARS = 3800  # safe margin under Telegram's 4096 limit
_API = "https://api.telegram.org/bot{token}/{method}"

# Local media mount: the agent's render tools write files under data/media/ and
# reference them as /api/media/<rel> (served read-only by the web app). Telegram
# can't fetch that relative path, so the reply path resolves it to the on-disk
# file and uploads it as a real photo/document instead of a dead link.
_MEDIA_ROOT = Path("data/media")
_PHOTO_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
# Markdown image the render tools emit: ![alt](/api/media/diagrams/x.png)
_MEDIA_IMG_RE = re.compile(r"!\[([^\]]*)\]\((/api/media/[^)\s]+)\)")


def _split_media(text: str) -> list[tuple]:
    """Split a reply into an ordered list of ``("text", str)`` runs and
    ``("media", (url, alt))`` events, so the reply path can interleave text
    messages with real photo/document uploads in place."""
    parts: list[tuple] = []
    pos = 0
    for m in _MEDIA_IMG_RE.finditer(text):
        if m.start() > pos:
            parts.append(("text", text[pos:m.start()]))
        parts.append(("media", (m.group(2), m.group(1))))
        pos = m.end()
    if pos < len(text):
        parts.append(("text", text[pos:]))
    return parts


def _strip_media_residue(text: str) -> str:
    """Drop the orphan caption/download lines that referenced media we're now
    uploading as a file (e.g. ``*Title* · [⬇ Download diagram](/api/media/…)``),
    so the dead link isn't also sent as text."""
    kept = [ln for ln in text.split("\n") if "/api/media/" not in ln]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()

# ── markdown → Telegram HTML ─────────────────────────────────────────────────
# Telegram's HTML parse mode accepts only a small tag set (<b> <i> <u> <s>
# <code> <pre> <a> <blockquote>) and none of its own markdown. We reuse
# hermes-agent's formatting strategy: pull code spans / links out behind
# placeholders so their contents are never mangled, rewrite the remaining
# markdown (tables, headers, bold/italic/strike, bullets, blockquotes),
# HTML-escape the plain prose, then restore the placeholders. A plain-text
# fallback (`_telegram_plain`) keeps a formatting edge case from ever dropping a
# message: if Telegram rejects the HTML, the same text is resent unformatted.

# A GFM table delimiter row (|---|:--:|…); needs ≥1 internal '|' so a lone '---'
# horizontal rule is not mistaken for a table.
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*){1,}\|?\s*$")
_FENCE_RE = re.compile(r"```[^\n]*\n?([\s\S]*?)```")
_INLINE_CODE_RE = re.compile(r"`([^`\n]+?)`")
# A markdown link or image; an empty alt ([](url)) falls back to the url as text.
_LINK_RE = re.compile(r"!?\[([^\]]*)\]\(([^()\s]+)\)")
# Headers: leading #'s, space OPTIONAL (models often drop it → "##Heading"), any
# trailing #'s trimmed. Requires a non-space first char so a bare "# " is skipped.
_HEADER_RE = re.compile(r"^[ \t]*#{1,6}[ \t]*(\S.*?)[ \t]*#*$", re.MULTILINE)
# A horizontal rule: 3+ of -, * or _ (optionally space-separated) on their own line.
_HR_RE = re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$", re.MULTILINE)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_US_RE = re.compile(r"(?<!\w)__(?!\s)(.+?)(?<!\s)__(?!\w)", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![\*\w])\*(?!\s)([^\*\n]+?)(?<!\s)\*(?!\w)")
_ITALIC_US_RE = re.compile(r"(?<!\w)_(?!\s)([^_\n]+?)(?<!\s)_(?!\w)")
_BULLET_RE = re.compile(r"^([ \t]*)[-*+•][ \t]+(?=\S)", re.MULTILINE)
_QUOTE_RE = re.compile(r"(?:^[ \t]*>[ \t]?.*(?:\n|$))+", re.MULTILINE)
# Inline emphasis markers, used to clean table cells down to plain text.
_CELL_MD_RES = (
    re.compile(r"\*\*(.+?)\*\*"), re.compile(r"(?<!\w)__(.+?)__(?!\w)"),
    re.compile(r"~~(.+?)~~"), re.compile(r"\*(.+?)\*"),
    re.compile(r"(?<!\w)_(.+?)_(?!\w)"), re.compile(r"`(.+?)`"),
)
_BLANKS_RE = re.compile(r"\n{3,}")


def _split_table_row(line: str) -> list[str]:
    """Split a GFM table row into cells, honoring escaped pipes (``\\|``)."""
    s = line.strip().replace("\\|", "\x00PIPE\x00")
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip().replace("\x00PIPE\x00", "|") for c in s.split("|")]


def _clean_cell(cell: str) -> str:
    """Reduce a table cell to plain text: strip inline markdown emphasis/code so it
    never leaks into the rendered table, and collapse internal whitespace."""
    s = cell
    for rx in _CELL_MD_RES:
        s = rx.sub(r"\1", s)
    s = s.replace("**", "").replace("`", "")
    return " ".join(s.split())


def _detect_table(lines: list[str], start: int):
    """If a markdown table begins at ``lines[start]``, return ``(rows, consumed)``
    where ``rows`` is a list of cell-lists (header first); else ``(None, 0)``.

    Handles both GFM tables (header + ``|---|`` delimiter) and the separator-less
    pipe tables some models emit (header + ≥2 rows with matching column counts)."""
    header = lines[start]
    if "|" not in header:
        return None, 0
    hcells = _split_table_row(header)
    if len(hcells) < 2:
        return None, 0
    # GFM: a delimiter row sits directly under the header.
    if start + 1 < len(lines) and _TABLE_SEP_RE.match(lines[start + 1]):
        rows = [hcells]
        j = start + 2
        while (j < len(lines) and lines[j].strip() and "|" in lines[j]
               and not _TABLE_SEP_RE.match(lines[j])):
            rows.append(_split_table_row(lines[j]))
            j += 1
        return rows, j - start
    # Separator-less: only treat as a table with ≥2 consistent pipe rows below.
    body = []
    j = start + 1
    while (j < len(lines) and lines[j].strip() and "|" in lines[j]
           and not _TABLE_SEP_RE.match(lines[j])):
        rc = _split_table_row(lines[j])
        if len(rc) != len(hcells):
            break
        body.append(rc)
        j += 1
    if len(body) >= 2:
        return [hcells, *body], j - start
    return None, 0


def _table_layout(rows: list[list[str]]):
    """Normalize a detected table → ``(headers, data, widths)`` of cleaned cells."""
    headers = [_clean_cell(c) for c in rows[0]]
    ncol = len(headers)
    data = []
    for r in rows[1:]:
        cells = [_clean_cell(c) for c in r]
        data.append((cells + [""] * ncol)[:ncol])
    widths = [max([len(headers[c]), *(len(d[c]) for d in data)] or [0])
              for c in range(ncol)] if data else [len(h) for h in headers]
    return headers, data, widths


def _render_table_html(rows: list[list[str]]) -> str:
    """Render a table as Telegram HTML. Narrow tables become an aligned monospace
    ``<pre>`` grid (an actual table); wide ones fall back to per-row key/value bullet
    groups so long cells don't force endless horizontal scrolling on mobile."""
    headers, data, widths = _table_layout(rows)
    ncol = len(headers)
    if not data:
        joined = " · ".join(h for h in headers if h)
        return f"<b>{_html_escape(joined)}</b>" if joined else ""
    total = sum(widths) + 2 * (ncol - 1)
    if ncol <= 4 and max(widths) <= 18 and total <= 44:  # narrow → real grid
        def line(cells):
            return "  ".join(cells[c].ljust(widths[c]) for c in range(ncol)).rstrip()
        grid = [line(headers), "  ".join("-" * widths[c] for c in range(ncol)),
                *(line(d) for d in data)]
        return f"<pre>{_html_escape(chr(10).join(grid))}</pre>"
    groups = []  # wide → bullet groups, first cell as the row heading
    for d in data:
        heading = d[0] or next((c for c in d if c), "")
        bullets = [f"• {_html_escape(h)}: {_html_escape(v)}"
                   for h, v in list(zip(headers, d))[1:] if (h or v)]
        head = f"<b>{_html_escape(heading)}</b>" if heading else ""
        groups.append("\n".join(x for x in [head, *bullets] if x))
    return "\n\n".join(g for g in groups if g)


def _render_table_plain(rows: list[list[str]]) -> str:
    """Plain-text table render (no HTML) for the fallback path: always key/value
    bullet groups so nothing tabular leaks as raw pipes."""
    headers, data, _ = _table_layout(rows)
    if not data:
        return " · ".join(h for h in headers if h)
    groups = []
    for d in data:
        heading = d[0] or next((c for c in d if c), "")
        bullets = [f"• {h}: {v}" for h, v in list(zip(headers, d))[1:] if (h or v)]
        groups.append("\n".join(x for x in [heading, *bullets] if x))
    return "\n\n".join(g for g in groups if g)


def _replace_tables(text: str, render) -> str:
    """Walk ``text`` line by line (skipping fenced code) and replace each detected
    table with ``render(rows)``. Shared by the HTML and plain paths."""
    if "|" not in text:
        return text
    lines = text.split("\n")
    out: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(lines[i])
            i += 1
            continue
        if not in_fence:
            rows, consumed = _detect_table(lines, i)
            if rows:
                out.append(render(rows))
                i += consumed
                continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


def _strip_residual_markers(text: str) -> str:
    """Final sweep: drop stray emphasis markers that never formed a valid pair
    (unbalanced ``**`` / ``~~``) so they can't leak as literal symbols. Runs on the
    escaped text, before protected code/link spans are restored, so it never touches
    real code (e.g. Python ``**kwargs`` lives safely inside a <code> placeholder)."""
    return text.replace("**", "").replace("~~", "")


def _render_blockquote(m: "re.Match") -> str:
    inner = "\n".join(re.sub(r"^[ \t]*>[ \t]?", "", ln)
                      for ln in m.group(0).rstrip("\n").split("\n"))
    return f"\x00BQ\x00{inner}\x00/BQ\x00"  # marker resolved after escaping


def _markdown_to_telegram_html(text: str) -> str:
    """Convert standard markdown to Telegram HTML: headers/tables → bold groups,
    `code`/```fences``` → <code>/<pre>, [links](…) → <a>, **/__ → <b>, */_ → <i>,
    ~~ → <s>, '- ' → '• ', '> ' → <blockquote>. Everything else is HTML-escaped."""
    if not text:
        return text
    placeholders: dict[str, str] = {}

    def ph(value: str) -> str:
        key = f"\x00P{len(placeholders)}\x00"
        placeholders[key] = value
        return key

    # Protect spans whose contents must survive verbatim, innermost meaning first.
    text = _FENCE_RE.sub(lambda m: ph(f"<pre>{_html_escape(m.group(1))}</pre>"), text)
    text = _INLINE_CODE_RE.sub(lambda m: ph(f"<code>{_html_escape(m.group(1))}</code>"), text)
    text = _LINK_RE.sub(
        lambda m: ph(f'<a href="{_html_escape(m.group(2), quote=True)}">'
                     f"{_html_escape(m.group(1) or m.group(2))}</a>"),
        text,
    )
    # Tables → pre-rendered HTML, protected so the escape/inline passes skip them.
    text = _replace_tables(text, lambda rows: ph(_render_table_html(rows)))
    # Blockquotes: collapse a run of '> ' lines into one marker (resolved below).
    text = _QUOTE_RE.sub(_render_blockquote, text)

    # Escape the remaining plain prose; placeholders/markers carry no special chars.
    text = _html_escape(text)

    # Rewrite the markdown constructs that survived escaping.
    text = _HR_RE.sub("────────", text)
    text = _HEADER_RE.sub(lambda m: f"<b>{m.group(1).replace('**', '')}</b>", text)
    text = _BULLET_RE.sub(r"\1• ", text)
    text = _BOLD_RE.sub(r"<b>\1</b>", text)
    text = _BOLD_US_RE.sub(r"<b>\1</b>", text)
    text = _STRIKE_RE.sub(r"<s>\1</s>", text)
    text = _ITALIC_STAR_RE.sub(r"<i>\1</i>", text)
    text = _ITALIC_US_RE.sub(r"<i>\1</i>", text)
    text = _strip_residual_markers(text)
    text = text.replace("\x00BQ\x00", "<blockquote>").replace("\x00/BQ\x00", "</blockquote>")

    # Restore protected spans (reverse insertion order resolves nested refs).
    for key in reversed(list(placeholders.keys())):
        text = text.replace(key, placeholders[key])
    return _BLANKS_RE.sub("\n\n", text).strip()


def _telegram_plain(text: str) -> str:
    """Plain-text fallback (all markdown markers removed) for when Telegram rejects
    the HTML message — so a formatting edge case degrades to a clean, readable
    message instead of one littered with stray ``*``, ``#`` and ``|`` symbols."""
    t = _FENCE_RE.sub(lambda m: m.group(1), text)
    t = _INLINE_CODE_RE.sub(r"\1", t)
    t = _LINK_RE.sub(lambda m: m.group(1) or m.group(2), t)
    t = _replace_tables(t, _render_table_plain)
    t = _HR_RE.sub("────────", t)
    t = _HEADER_RE.sub(r"\1", t)
    t = _BULLET_RE.sub(r"\1• ", t)
    t = _BOLD_RE.sub(r"\1", t)
    t = _BOLD_US_RE.sub(r"\1", t)
    t = _STRIKE_RE.sub(r"\1", t)
    t = _ITALIC_STAR_RE.sub(r"\1", t)
    t = _ITALIC_US_RE.sub(r"\1", t)
    t = _strip_residual_markers(t)
    return _BLANKS_RE.sub("\n\n", t).strip()


def _chunk(text: str, limit: int = _MAX_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        window = text[:limit]
        cut = max(window.rfind("\n"), window.rfind(". "), window.rfind("! "), window.rfind("? "))
        cut = cut + 1 if cut > 0 else limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


class TelegramChannel:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self._token = token if token is not None else os.environ.get("NAMMA_TELEGRAM_TOKEN", "")
        self._chat_id = chat_id if chat_id is not None else os.environ.get("NAMMA_TELEGRAM_CHAT_ID", "")
        self._available = bool(self._token and self._chat_id)

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str, reply_to: Optional[int] = None) -> bool:
        """Dispatch a message on a background thread. Returns True if dispatched.
        ``reply_to`` makes the message quote/point at the user's message id."""
        if not self.available or not text:
            return False
        threading.Thread(target=self._send_sync, args=(text, reply_to), daemon=True).start()
        return True

    def send_chat_action(self, action: str = "typing") -> None:
        """Show the '<name> is typing…' status at the top of the chat (best-effort).
        Expires after ~5s, so callers refresh it on a heartbeat."""
        if not self.available:
            return
        try:
            self._post("sendChatAction", {"chat_id": self._chat_id, "action": action})
        except Exception:  # noqa: BLE001
            pass

    def _post(self, method: str, body: dict, timeout: int = 10) -> dict:
        req = urllib.request.Request(
            _API.format(token=self._token, method=method),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.load(resp)

    def _send_sync(self, text: str, reply_to: Optional[int] = None) -> None:
        for chunk in _chunk(text):
            self._deliver(chunk, reply_to)
            reply_to = None  # only the first chunk quotes the user's message

    def _deliver(self, chunk: str, reply_to: Optional[int] = None) -> None:
        """Send one chunk as Telegram HTML; on a parse/format rejection, resend it
        as plain text so a markdown edge case never drops the message."""
        base: dict = {"chat_id": self._chat_id}
        if reply_to:
            base["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        try:
            result = self._post("sendMessage",
                                {**base, "text": _markdown_to_telegram_html(chunk),
                                 "parse_mode": "HTML"})
            if result.get("ok"):
                return
            logger.warning("[telegram] send failed (%s); retrying as plain text",
                           result.get("description"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] send error (%s); retrying as plain text", exc)
        try:
            self._post("sendMessage", {**base, "text": _telegram_plain(chunk)})
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] plain send error: %s", exc)

    # -- outbound media (photos / documents) -------------------------------

    def send_photo(self, src, caption: str = "", reply_to: Optional[int] = None) -> bool:
        """Upload an image so it previews inline in the chat. Falls back to a
        document when the image is over Telegram's 10 MB sendPhoto limit. ``src`` is
        a filesystem path or an ``/api/media/…`` url. Returns True on success."""
        if not self.available:
            return False
        path = self._resolve_media(src)
        if not path or not path.exists():
            logger.warning("[telegram] photo not found: %s", src)
            return False
        if path.stat().st_size > 10 * 1024 * 1024:
            return self._deliver_file("sendDocument", "document", path, caption, reply_to)
        return self._deliver_file("sendPhoto", "photo", path, caption, reply_to)

    def send_document(self, src, caption: str = "", reply_to: Optional[int] = None) -> bool:
        """Upload any file as a downloadable document (no recompression). ``src`` is a
        filesystem path or an ``/api/media/…`` url. Returns True on success."""
        if not self.available:
            return False
        path = self._resolve_media(src)
        if not path or not path.exists():
            logger.warning("[telegram] file not found: %s", src)
            return False
        if path.stat().st_size > 50 * 1024 * 1024:
            logger.warning("[telegram] file over Telegram's 50 MB limit: %s", path)
            return False
        return self._deliver_file("sendDocument", "document", path, caption, reply_to)

    def send_media(self, src, caption: str = "", reply_to: Optional[int] = None) -> bool:
        """Auto-pick: images go as inline photos, everything else as documents.
        Used to surface the agent's rendered diagrams/images in replies."""
        path = self._resolve_media(src)
        if not path or not path.exists():
            return False
        if path.suffix.lower() in _PHOTO_EXTS:
            return self.send_photo(path, caption, reply_to)
        return self.send_document(path, caption, reply_to)

    @staticmethod
    def _resolve_media(src) -> Optional[Path]:
        """Map an ``/api/media/<rel>`` url (the local media mount) to its file under
        ``data/media``; treat anything else as a filesystem path (~ expanded)."""
        if not src:
            return None
        s = str(src)
        if s.startswith("/api/media/"):
            rel = s[len("/api/media/"):].split("?", 1)[0].split("#", 1)[0]
            return _MEDIA_ROOT / rel
        return Path(s).expanduser()

    def _deliver_file(self, method: str, field: str, path: Path,
                      caption: str = "", reply_to: Optional[int] = None,
                      timeout: int = 120) -> bool:
        try:
            data = path.read_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] could not read %s: %s", path, exc)
            return False
        fields: dict = {"chat_id": self._chat_id}
        if (caption or "").strip():
            fields["caption"] = caption.strip()[:1024]  # Telegram caption cap
        if reply_to:
            fields["reply_parameters"] = json.dumps(
                {"message_id": reply_to, "allow_sending_without_reply": True})
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        files = {field: (path.name, data, mime)}
        try:
            result = self._post_multipart(method, fields, files, timeout=timeout)
            if result.get("ok"):
                return True
            logger.warning("[telegram] %s failed: %s", method, result.get("description"))
            return False
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] %s error: %s", method, exc)
            return False

    def _post_multipart(self, method: str, fields: dict, files: dict,
                        timeout: int = 120) -> dict:
        """POST multipart/form-data with stdlib only (Telegram media uploads)."""
        boundary = "----NammaAgent" + uuid.uuid4().hex
        bnd = boundary.encode()
        crlf = b"\r\n"
        body = bytearray()
        for k, v in fields.items():
            body += b"--" + bnd + crlf
            body += f'Content-Disposition: form-data; name="{k}"'.encode() + crlf + crlf
            body += str(v).encode() + crlf
        for name, (filename, content, mime) in files.items():
            body += b"--" + bnd + crlf
            body += (f'Content-Disposition: form-data; name="{name}"; '
                     f'filename="{filename}"').encode() + crlf
            body += f"Content-Type: {mime}".encode() + crlf + crlf
            body += content + crlf
        body += b"--" + bnd + b"--" + crlf
        req = urllib.request.Request(
            _API.format(token=self._token, method=method), data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.load(resp)


_HELP = (
    "{name} commands:\n"
    "• plain text — I handle it (agent mode by default)\n"
    "• 🎤 voice message — I'll transcribe and answer it\n"
    "• !<cmd> — run a shell command, e.g. !df -h\n"
    "• /mode chat|agent — switch mode\n"
    "• /model — switch the AI model (pick by number)\n"
    "• /new — start a fresh conversation\n"
    "• /clear — wipe my memory\n"
    "• send a document — I'll read it\n"
    "• /help — this message"
)

# Registered with Telegram so the in-app "/" button shows a command menu w/ tooltips.
_BOT_COMMANDS = [
    {"command": "help", "description": "Show what I can do"},
    {"command": "new", "description": "Start a fresh conversation"},
    {"command": "mode", "description": "Switch mode — /mode chat or /mode agent"},
    {"command": "model", "description": "Switch the AI model (pick by number)"},
    {"command": "clear", "description": "Wipe my memory"},
]


class _TypingStatus:
    """The standard Telegram '<name> is typing…' indicator at the top of the chat,
    kept alive on a daemon heartbeat while a turn runs (the action expires after ~5s).
    No in-chat placeholder, no streaming — just the subtle top status."""

    def __init__(self, channel: "TelegramChannel"):
        self._ch = channel
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="TelegramTyping", daemon=True)

    def start(self) -> "_TypingStatus":
        self._ch.send_chat_action("typing")   # show it immediately
        self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(4.0):        # refresh before the ~5s TTL lapses
            self._ch.send_chat_action("typing")

    def stop(self) -> None:
        self._stop.set()


class TelegramInbound(InboundBridge):
    """Long-poll the bot and route messages (text, voice, /commands, !shell, documents).

    The shared session/command/picker/askpass/turn logic lives in
    :class:`InboundBridge`; this subclass supplies the Telegram transport.
    """

    _POLL_TIMEOUT = 20

    def __init__(self, channel: TelegramChannel,
                 on_message: Callable[..., tuple],  # (text, session_id, mode, askpass, model) -> (reply, sid)
                 get_models: Optional[Callable[[], list]] = None):
        super().__init__(on_message, get_models)
        self._channel = channel
        self._offset = 0

    @property
    def available(self) -> bool:
        return self._channel.available

    @property
    def channel_name(self) -> str:
        return "telegram"

    def _help_text(self) -> str:
        from namma_agent.config import assistant_name
        return _HELP.replace("{name}", assistant_name())

    # -- transport ---------------------------------------------------------

    def _say(self, text: str) -> None:
        self._channel.send(text)

    def _reply(self, text: str, ref=None) -> None:
        if ref:
            self._send_reply(text, ref)
        else:
            self._channel.send(text)

    def _scrub(self, ref) -> None:
        self._delete_message(ref)

    def start(self) -> None:
        if not self._channel.available or self._thread is not None:
            return
        self._register_commands()  # populate the in-app "/" command menu
        self._thread = threading.Thread(target=self._loop, name="TelegramInbound", daemon=True)
        self._thread.start()
        logger.info("[telegram] inbound polling started")

    def _register_commands(self) -> None:
        """Register the bot's slash-command menu so Telegram shows the "/" tooltips."""
        try:
            self._channel._post("setMyCommands", {"commands": _BOT_COMMANDS})
        except Exception as exc:  # noqa: BLE001
            logger.debug("[telegram] setMyCommands failed: %s", exc)

    def _send_reply(self, text: str, reply_to: Optional[int]) -> None:
        """Send the answer synchronously as a reply to the user's message. Rendered
        diagrams/images (``![…](/api/media/…)``) are uploaded as real photos in place;
        the surrounding prose goes as chunked text. Only the first message quotes the
        user's message."""
        if not (text or "").strip():
            return
        first = True
        for kind, val in _split_media(text):
            if kind == "text":
                cleaned = _strip_media_residue(val)
                if not cleaned:
                    continue
                for chunk in _chunk(cleaned):
                    self._channel._deliver(chunk, reply_to if first else None)
                    first = False
            else:
                url, alt = val
                caption = (alt or "").strip()
                if self._channel.send_media(url, caption=caption,
                                            reply_to=reply_to if first else None):
                    first = False
                elif caption:  # upload failed (file gone) — keep the label, drop the link
                    self._channel._deliver(caption, reply_to if first else None)
                    first = False

    def _progress_send(self, text: str) -> None:
        """Deliver one intermediate progress line ('Let me check…') as its own message,
        synchronously so the live updates stay in order ahead of the final reply."""
        self._channel._send_sync(text)

    # -- poll loop ---------------------------------------------------------

    def _loop(self) -> None:
        backoff = 1
        while not self._stop.is_set():
            try:
                for update in self._get_updates():
                    self._dispatch(update)
                backoff = 1
            except (TimeoutError, OSError):
                continue
            except Exception as exc:  # noqa: BLE001
                logger.warning("[telegram] poll error: %s", exc)
                time.sleep(backoff)
                backoff = min(backoff * 2, 15)

    def _get_updates(self) -> list:
        url = _API.format(token=self._channel._token, method="getUpdates") + (
            f"?offset={self._offset}&timeout={self._POLL_TIMEOUT}"
        )
        with urllib.request.urlopen(url, timeout=self._POLL_TIMEOUT + 10) as resp:  # noqa: S310
            data = json.load(resp)
        if not data.get("ok"):
            return []
        updates = data.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    def _dispatch(self, update: dict) -> None:
        message = update.get("message") or {}
        if str(message.get("chat", {}).get("id", "")) != self._channel._chat_id:
            return  # only the authorized chat
        msg_id = message.get("message_id")
        document = message.get("document")
        voice = message.get("voice") or message.get("audio")  # voice note or audio file
        caption = (message.get("caption") or "").strip()
        text = (message.get("text") or "").strip()
        # If a turn is waiting for a sudo password, this message IS the password.
        if text and self._pw_event is not None:
            self._capture_password(text, msg_id)
            return
        if voice:
            threading.Thread(target=self._process_voice, args=(voice, caption, msg_id),
                             daemon=True).start()
            return
        if document:
            threading.Thread(target=self._process_document, args=(document, caption, msg_id),
                             daemon=True).start()
            return
        if not text:
            return
        # A /model picker is open → this message is the user's number choice.
        if self._pending_models is not None and not text.startswith("/"):
            self._handle_model_selection(text)
            return
        if self._handle_command(text):
            return
        threading.Thread(target=self._process, args=(text, msg_id), daemon=True).start()

    def _delete_message(self, message_id) -> None:
        if not message_id:
            return
        try:
            self._channel._post("deleteMessage",
                                {"chat_id": self._channel._chat_id, "message_id": message_id})
        except Exception:  # noqa: BLE001
            pass

    # -- turn (with Telegram typing indicator + reply quoting) -------------

    def _reply_turn(self, text: str, reply_to: Optional[int] = None) -> None:
        """Run one turn and deliver the answer ONCE as a reply to the user's message,
        showing only the standard top '<name> is typing…' status while it works. When
        reply_to is absent (e.g. unit tests), sends plainly."""
        status = _TypingStatus(self._channel).start() if reply_to else None
        try:
            reply = self._execute(text)
        finally:
            if status is not None:
                status.stop()
        if reply_to:
            self._send_reply(reply, reply_to)
        else:
            self._channel.send(reply)

    # -- voice / documents -------------------------------------------------

    def _process_voice(self, voice: dict, caption: str, reply_to: Optional[int] = None) -> None:
        from namma_agent.comms.transcribe import transcribe_audio
        try:
            path = self._download(voice)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] voice download failed: %s", exc)
            self._channel.send("Couldn't download that voice message.", reply_to=reply_to)
            return
        self._channel.send_chat_action("typing")
        text = transcribe_audio(path)
        if not text:
            self._channel.send(
                "I got your voice message, but voice transcription isn't set up. Add an "
                "OpenAI(-compatible) API key under `comms.stt` in config to enable it.",
                reply_to=reply_to)
            return
        prompt = f"{caption}\n{text}".strip() if caption else text
        self._reply_turn(prompt, reply_to)

    def _process_document(self, document: dict, caption: str, reply_to: Optional[int] = None) -> None:
        try:
            path = self._download(document)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[telegram] document download failed: %s", exc)
            self._channel.send("Couldn't download that file.", reply_to=reply_to)
            return
        ask = caption or "Read this document and give me a short summary."
        self._reply_turn(f"The user sent a document saved at {path}. "
                         f"Use read_document on it, then: {ask}", reply_to)

    def _download(self, document: dict) -> str:
        file_id = document["file_id"]
        info = self._channel._post("getFile", {"file_id": file_id})
        file_path = info["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{self._channel._token}/{file_path}"
        dest_dir = os.path.join("data", "uploads")
        os.makedirs(dest_dir, exist_ok=True)
        name = document.get("file_name") or os.path.basename(file_path)
        dest = os.path.join(dest_dir, name)
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            with open(dest, "wb") as fh:
                fh.write(resp.read())
        return os.path.abspath(dest)
