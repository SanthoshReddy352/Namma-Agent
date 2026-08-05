"""Transcript rendering: tool lines, spinner frames, and inline diffs.

Everything here is a pure function of its arguments (plus the active skin), so
the whole module is unit-testable without a terminal, a provider, or an agent.
:mod:`~namma_agent.tui.app` owns the side effects; this module owns the look.
"""
from __future__ import annotations

import difflib
import itertools
import os
import random
import time
from typing import Iterable, Optional

from namma_agent.tui import theme

# ── Tool presentation ──────────────────────────────────────────────────
# One emoji per tool, grouped by what the tool does. Tools not listed here fall
# back to the group prefix match below, then to a generic glyph — so a newly
# added tool always renders sensibly without touching this table.
TOOL_EMOJI: dict[str, str] = {
    # Shell + system
    "run_shell": "⚡", "system_info": "🖥️", "take_screenshot": "📸",
    "open_app": "🚀", "list_open_apps": "🪟", "send_notification": "🔔",
    # Files
    "read_file": "📖", "write_file": "✍️", "list_dir": "📂", "find_files": "🔍",
    "make_dir": "📁", "copy_path": "📋", "move_path": "📦", "delete_path": "🗑️",
    "organize_dir": "🗂️",
    # Documents
    "read_document": "📄", "read_text_from_image": "🔎",
    # Web
    "web_search": "🌐", "search_google": "🔍", "web_crawl": "🕷️",
    "web_extract": "📰", "open_browser_url": "🧭",
    # Network
    "ping_host": "📡", "ping_sweep": "📡", "port_scan": "🔌",
    "check_port": "🔌", "dns_lookup": "🧭", "dns_enum": "🧭",
    "dir_enum": "🗺️", "public_ip": "🌍",
    # Productivity
    "add_task": "✅", "list_tasks": "📋", "complete_task": "✔️", "remove_task": "🗑️",
    "add_reminder": "⏰", "list_reminders": "⏰", "remove_reminder": "🗑️",
    "add_goal": "🎯", "list_goals": "🎯", "update_goal_progress": "📈",
    "remove_goal": "🗑️",
    "start_focus": "🧘", "end_focus": "🧘", "focus_status": "🧘",
    # Google Workspace
    "gmail_list": "📧", "gmail_read": "📧", "gmail_send": "📤",
    "calendar_agenda": "📅", "calendar_create_event": "📅",
    # Ambient
    "get_weather": "🌤️", "get_news": "📰",
    "ha_turn_on": "💡", "ha_turn_off": "💡",
    "ha_set_temperature": "🌡️", "ha_get_state": "🏠",
}

# Prefix → emoji, checked when a tool name isn't in the table above.
_TOOL_PREFIX_EMOJI: list[tuple[str, str]] = [
    ("gmail_", "📧"), ("calendar_", "📅"), ("ha_", "🏠"),
    ("web_", "🌐"), ("dns_", "🧭"), ("ping_", "📡"), ("port_", "🔌"),
    ("read_", "📖"), ("write_", "✍️"), ("list_", "📋"), ("find_", "🔍"),
    ("search_", "🔍"), ("add_", "➕"), ("remove_", "🗑️"), ("delete_", "🗑️"),
    ("memory_", "🧠"), ("recall", "🧠"), ("remember", "🧠"),
    ("mcp_", "🔗"), ("skill", "📚"),
]

_GENERIC_EMOJI = "⚡"
_ASCII_TOOL_PREFIX = "*"

# Argument keys worth showing in a one-line preview, most informative first.
# The first key a tool's arguments actually contain wins.
_PREVIEW_KEYS = (
    "command", "query", "path", "file_path", "url", "name", "title",
    "text", "message", "prompt", "pattern", "host", "target", "location",
    "to", "subject", "task", "goal", "expression", "code",
)

DEFAULT_PREVIEW_LEN = 72


def tool_emoji(tool_name: str, default: str = _GENERIC_EMOJI) -> str:
    """The glyph for a tool. ASCII terminals get a plain marker instead."""
    if not theme.supports_unicode():
        return _ASCII_TOOL_PREFIX
    if tool_name in TOOL_EMOJI:
        return TOOL_EMOJI[tool_name]
    for prefix, emoji in _TOOL_PREFIX_EMOJI:
        if tool_name.startswith(prefix):
            return emoji
    return default


def _oneline(text: str) -> str:
    """Collapse whitespace so a multi-line argument stays on one row."""
    return " ".join(str(text).split())


def truncate(text: str, max_len: int = DEFAULT_PREVIEW_LEN) -> str:
    """Trim to ``max_len`` with an ellipsis, never mid-escape."""
    text = _oneline(text)
    if max_len <= 0 or len(text) <= max_len:
        return text
    ellipsis = theme.glyph("ellipsis")
    return text[: max(1, max_len - len(ellipsis))] + ellipsis


def tool_preview(tool_name: str, args: Optional[dict] = None,
                 max_len: int = DEFAULT_PREVIEW_LEN) -> str:
    """A short, human-readable summary of what a tool call is about to do.

    Picks the most informative argument rather than dumping the whole dict:
    ``run_shell {"command": "git status"}`` → ``git status``. Returns ``""``
    when there's nothing worth showing, and the caller then prints just the
    tool name.
    """
    if not args:
        return ""
    for key in _PREVIEW_KEYS:
        value = args.get(key)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return truncate(str(value), max_len)
    # Nothing recognized — show the first scalar argument we do have.
    for key, value in args.items():
        if isinstance(value, (str, int, float)) and str(value).strip():
            return truncate(f"{key}={value}", max_len)
    return ""


def tool_line(tool_name: str, args: Optional[dict] = None,
              max_len: int = DEFAULT_PREVIEW_LEN) -> str:
    """One transcript line for a starting tool call, as rich markup."""
    preview = tool_preview(tool_name, args, max_len)
    line = f"{tool_emoji(tool_name)} {theme.styled(tool_name, 'banner_accent')}"
    if preview:
        line += f" {theme.styled(_escape(preview), 'tool_line')}"
    return line


def tool_result_line(tool_name: str, ok: bool, detail: str = "",
                     elapsed: Optional[float] = None) -> str:
    """One transcript line for a finished tool call, as rich markup."""
    mark = ("✓" if ok else "✗") if theme.supports_unicode() else ("ok" if ok else "!!")
    parts = [theme.styled(mark, "good" if ok else "critical"),
             theme.styled(tool_name, "tool_line")]
    if detail:
        parts.append(theme.styled(_escape(truncate(detail)), "tool_line"))
    if elapsed is not None and elapsed >= 0.1:
        parts.append(theme.styled(f"({elapsed:.1f}s)", "tool_line"))
    return "  " + " ".join(parts)


def _escape(text: str) -> str:
    """Escape rich markup so tool arguments containing ``[...]`` render literally."""
    return text.replace("[", "\\[")


# ── Spinner ────────────────────────────────────────────────────────────

class Spinner:
    """Frame source for the status spinner.

    Holds no thread and does no I/O: :mod:`~namma_agent.tui.app` renders
    :meth:`text` from prompt_toolkit's own redraw loop. That keeps the animation
    on the UI thread and out of the agent's way, and makes it testable by
    calling :meth:`text` with a fixed clock.
    """

    def __init__(self, skin: Optional[theme.Skin] = None,
                 message: str = "", kind: str = "waiting"):
        self._skin = skin or theme.get_active_skin()
        self._frames = itertools.cycle(self._skin.frames())
        self._frame = next(self._frames)
        self.message = message
        self.kind = kind
        self.started_at: Optional[float] = None
        self._face = self._pick(self._skin.faces(kind))
        self._verb = self._pick(self._skin.verbs())

    @staticmethod
    def _pick(items: list[str]) -> str:
        return random.choice(items) if items else ""

    def start(self, message: str = "", kind: str = "waiting") -> None:
        """Begin (or restart) the animation, resetting the elapsed clock."""
        self.started_at = time.monotonic()
        self.message = message or self.message
        if kind != self.kind:
            self.kind = kind
            self._face = self._pick(self._skin.faces(kind))
        self._verb = self._pick(self._skin.verbs())

    def stop(self) -> None:
        self.started_at = None

    @property
    def running(self) -> bool:
        return self.started_at is not None

    def advance(self) -> None:
        """Step to the next frame. Called once per redraw."""
        self._frame = next(self._frames)

    def elapsed(self, now: Optional[float] = None) -> float:
        if self.started_at is None:
            return 0.0
        return max(0.0, (now if now is not None else time.monotonic()) - self.started_at)

    def text(self, now: Optional[float] = None) -> str:
        """The spinner line as plain text: frame, face, message and elapsed time."""
        if not self.running:
            return ""
        parts = [self._frame]
        if self._face:
            parts.append(self._face)
        parts.append(self.message or f'{self._verb}{theme.glyph("ellipsis")}')
        seconds = self.elapsed(now)
        if seconds >= 1:
            parts.append(f"({seconds:.0f}s)")
        return " ".join(p for p in parts if p)


# ── Inline diffs ───────────────────────────────────────────────────────

def unified_diff(before: str, after: str, path: str = "",
                 context: int = 3, max_lines: int = 60) -> list[str]:
    """A colorized unified diff as rich-markup lines.

    Returns ``[]`` when the two texts are identical. Long diffs are cut off with
    a summary line rather than flooding the transcript.
    """
    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    raw = list(difflib.unified_diff(
        before_lines, after_lines,
        fromfile=path or "before", tofile=path or "after",
        n=context,
    ))
    if not raw:
        return []

    out: list[str] = []
    for line in raw[2:]:  # drop the ---/+++ header; the caller shows the path
        line = line.rstrip("\n")
        text = _escape(line)
        if line.startswith("@@"):
            out.append(theme.styled(text, "diff_hunk"))
        elif line.startswith("+"):
            out.append(theme.styled(text, "diff_plus"))
        elif line.startswith("-"):
            out.append(theme.styled(text, "diff_minus"))
        else:
            out.append(theme.styled(text, "tool_line"))
        if len(out) >= max_lines:
            remaining = len(raw) - 2 - len(out)
            if remaining > 0:
                more = f'{theme.glyph("ellipsis")} {remaining} more diff line(s)'
                out.append(theme.styled(more, "tool_line"))
            break
    return out


def diff_stat(before: str, after: str) -> tuple[int, int]:
    """``(added, removed)`` line counts between two texts."""
    added = removed = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


# ── Misc formatting ────────────────────────────────────────────────────

def format_context_length(tokens: Optional[int]) -> str:
    """``200000`` → ``200K``; ``1048576`` → ``1M``."""
    if not tokens:
        return ""
    for scale, suffix in ((1_000_000, "M"), (1_000, "K")):
        if tokens >= scale:
            value = tokens / scale
            # 1048576 is "1M", not "1.0M" — round to the nearest tenth first so
            # power-of-two context windows read the way people quote them.
            return (f"{value:.0f}{suffix}" if abs(value - round(value)) < 0.05
                    else f"{value:.1f}{suffix}")
    return str(tokens)


def shorten_path(path: str, max_len: int = 48) -> str:
    """Collapse ``$HOME`` to ``~`` and elide the middle of a long path."""
    try:
        home = os.path.expanduser("~")
        if home and path.startswith(home):
            path = "~" + path[len(home):]
    except Exception:  # noqa: BLE001 - cosmetic only
        pass
    if len(path) <= max_len:
        return path
    sep = "\\" if "\\" in path else "/"
    parts = path.split(sep)
    if len(parts) <= 2:
        return theme.glyph("ellipsis") + path[-(max_len - 1):]
    return f'{parts[0]}{sep}{theme.glyph("ellipsis")}{sep}{sep.join(parts[-2:])}'


def columns(items: Iterable[str], width: int, gap: int = 2) -> list[str]:
    """Lay names out in even columns that fit ``width``. Used by /tools, /skills."""
    items = [str(i) for i in items]
    if not items:
        return []
    cell = max(len(i) for i in items) + gap
    per_row = max(1, width // cell)
    rows = []
    for start in range(0, len(items), per_row):
        rows.append("".join(i.ljust(cell) for i in items[start:start + per_row]).rstrip())
    return rows
