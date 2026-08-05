"""The startup banner: wordmark, then a panel of what this session can do.

Layout follows Hermes' CLI — hero emblem and session facts on the left, the
tool/MCP/skill inventory on the right, wrapped in a bronze panel titled with the
version. Everything it displays is read from the live service, so the banner is
an honest inventory rather than a static splash.

Three widths are handled: the full banner (>= 95 columns) prints the wordmark
above the panel, the mid width drops the wordmark, and narrow terminals get a
few compact lines instead of a panel.
"""
from __future__ import annotations

import os
import shutil
from typing import Any, Optional

from namma_agent.tui import art, render, theme

# The wordmark for "NAMMA AGENT" is ~95 columns; below that it wraps and looks
# broken, so it's dropped rather than mangled.
_WORDMARK_MIN_WIDTH = 95
_PANEL_MIN_WIDTH = 70
_MAX_TOOL_GROUPS = 8
_TOOLS_PER_GROUP_CHARS = 46

# Tool-name prefix → the group it's filed under in the inventory. First match
# wins; anything unmatched lands in "other".
_TOOL_GROUPS: list[tuple[tuple[str, ...], str]] = [
    (("run_shell", "system_info", "take_screenshot", "open_app", "list_open_apps",
      "send_notification"), "system"),
    (("read_file", "write_file", "list_dir", "find_files", "make_dir", "copy_path",
      "move_path", "delete_path", "organize_dir"), "files"),
    (("read_document", "read_text_from_image", "convert_"), "documents"),
    (("web_", "search_google", "open_browser_url"), "web"),
    (("ping_", "port_", "check_port", "dns_", "dir_enum", "public_ip"), "network"),
    (("add_task", "list_tasks", "complete_task", "remove_task", "add_reminder",
      "list_reminders", "remove_reminder", "add_goal", "list_goals",
      "update_goal_progress", "remove_goal", "start_focus", "end_focus",
      "focus_status"), "productivity"),
    (("gmail_", "calendar_"), "google"),
    (("get_weather", "get_news"), "ambient"),
    (("ha_",), "smart home"),
    (("mcp_",), "mcp"),
]


def _group_for(tool_name: str) -> str:
    for prefixes, group in _TOOL_GROUPS:
        for prefix in prefixes:
            if tool_name == prefix or tool_name.startswith(prefix):
                return group
    return "other"


def group_tools(names: list[str]) -> dict[str, list[str]]:
    """Bucket tool names into display groups, each sorted."""
    grouped: dict[str, list[str]] = {}
    for name in names:
        grouped.setdefault(_group_for(name), []).append(name)
    return {k: sorted(v) for k, v in sorted(grouped.items())}


def _fit_names(names: list[str], budget: int, color_key: str = "banner_text") -> str:
    """Join names into one line, eliding once the character budget is spent."""
    shown, used = [], 0
    for name in names:
        if used + len(name) + 2 > budget and shown:
            shown.append(theme.glyph("ellipsis"))
            break
        shown.append(name)
        used += len(name) + 2
    ellipsis = theme.glyph("ellipsis")
    return ", ".join(n if n == ellipsis else theme.styled(n, color_key) for n in shown)


# ── Facts gathered from the live service ───────────────────────────────

def _model_label(service: Any) -> str:
    """The active model, shortened to the part a human recognizes."""
    model = ""
    try:
        model = str(getattr(service.provider, "model", "") or "")
    except Exception:  # noqa: BLE001 - the banner must never block startup
        pass
    if not model:
        return "unconfigured"
    if "/" in model:
        model = model.split("/")[-1]
    return model if len(model) <= 32 else model[:29] + theme.glyph("ellipsis")


def _context_length(service: Any) -> Optional[int]:
    for attr in ("context_length", "context_window", "max_context_tokens"):
        try:
            value = getattr(service.provider, attr, None)
            if value:
                return int(value)
        except Exception:  # noqa: BLE001
            continue
    return None


def _tool_names(service: Any) -> list[str]:
    try:
        return list(service.registry.names())
    except Exception:  # noqa: BLE001
        return []


def _mcp_servers(service: Any) -> list[tuple[str, int]]:
    """``(server_name, tool_count)`` for every connected MCP server."""
    try:
        clients = getattr(service.mcp, "clients", None) or {}
    except Exception:  # noqa: BLE001
        return []
    out = []
    for name, client in clients.items():
        try:
            count = len(client.list_tools() or [])
        except Exception:  # noqa: BLE001 - a wedged server shouldn't hide the rest
            count = 0
        out.append((str(name), count))
    return sorted(out)


def _skill_names(service: Any) -> list[str]:
    try:
        return sorted(s.name for s in service.skills.all() if getattr(s, "enabled", True))
    except Exception:  # noqa: BLE001
        return []


# ── Rendering ──────────────────────────────────────────────────────────

def _left_column(service: Any, session_id: Optional[str], compact: bool) -> str:
    """The emblem plus the session facts, centered as one block.

    Lines are padded here rather than by rich's ``justify="center"``: rich
    strips trailing whitespace and centers each line on its own visible width,
    which shears a symmetric figure apart row by row.
    """
    # (plain, markup) pairs — the plain text is what alignment is measured on.
    rows: list[tuple[str, str]] = []
    emblem = art.hero_rows(compact=compact)
    if emblem:
        rows += [("", ""), *emblem, ("", "")]

    model = _model_label(service)
    ctx = render.format_context_length(_context_length(service))
    dot = theme.glyph("middot")
    plain = f"{model} {dot} {ctx} context" if ctx else model
    markup = theme.styled(model, "banner_accent")
    if ctx:
        markup += " " + theme.styled(f"{dot} {ctx} context", "banner_dim")
    rows.append((plain, markup))

    if getattr(service, "auto_approve", False):
        warn = f'{theme.glyph("warn")} auto-approve'
        note = f'{theme.glyph("emdash")} destructive tools run unprompted'
        rows.append((f"{warn} {note}",
                     theme.styled(warn, "danger", bold=True) + " "
                     + theme.styled(note, "banner_dim")))

    cwd = render.shorten_path(os.getcwd())
    rows.append((cwd, theme.styled(cwd, "banner_dim")))
    if session_id:
        label = f"Session: {session_id}"
        rows.append((label, theme.styled(label, "session_border")))

    width = max((len(plain) for plain, _ in rows), default=0)
    return "\n".join(" " * ((width - len(plain)) // 2) + markup for plain, markup in rows)


def _right_column(service: Any) -> str:
    def heading(label: str) -> str:
        return theme.styled(label, "banner_accent", bold=True)

    tools = _tool_names(service)
    lines = [heading("Available Tools")]
    grouped = group_tools(tools)
    for group in list(grouped)[:_MAX_TOOL_GROUPS]:
        names = _fit_names(grouped[group], _TOOLS_PER_GROUP_CHARS)
        lines.append(f"{theme.styled(group + ':', 'banner_dim')} {names}")
    hidden = len(grouped) - _MAX_TOOL_GROUPS
    if hidden > 0:
        more = f'(and {hidden} more group(s){theme.glyph("ellipsis")})'
        lines.append(theme.styled(more, "banner_dim"))

    servers = _mcp_servers(service)
    if servers:
        lines += ["", heading("MCP Servers")]
        for name, count in servers:
            lines.append(f"{theme.styled(name, 'banner_dim')} {theme.glyph('emdash')} "
                         f"{theme.styled(f'{count} tool(s)', 'banner_text')}")

    skills = _skill_names(service)
    lines += ["", heading("Available Skills")]
    lines.append(_fit_names(skills, 52) if skills
                 else theme.styled("No skills installed", "banner_dim"))

    lines.append("")
    summary = [f"{len(tools)} tools", f"{len(skills)} skills"]
    if servers:
        summary.append(f"{len(servers)} MCP server{'' if len(servers) == 1 else 's'}")
    summary.append("/help for commands")
    separator = f" {theme.glyph('middot')} "
    lines.append(theme.styled(separator.join(summary), "banner_dim"))
    return "\n".join(lines)


def _title() -> str:
    from namma_agent.config import assistant_name
    from namma_agent.version import __version__

    return theme.styled(f"{assistant_name()} v{__version__}", "banner_title", bold=True)


def build(service: Any, session_id: Optional[str] = None,
          width: Optional[int] = None) -> Any:
    """The banner as a rich renderable, sized for the current terminal.

    Returns a ``Group`` so the caller only has to ``console.print`` it once.
    """
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    if width is None:
        width = shutil.get_terminal_size(fallback=(100, 30)).columns

    if width < _PANEL_MIN_WIDTH:
        return Group(*_compact_lines(service, session_id))

    compact_hero = width < _WORDMARK_MIN_WIDTH
    grid = Table.grid(padding=(0, 2))
    # Both columns are left-justified: _left_column already centered its own
    # block, and letting rich re-justify would undo that.
    grid.add_column("left", justify="left")
    grid.add_column("right", justify="left")
    grid.add_row(_left_column(service, session_id, compact_hero),
                 _right_column(service))

    # The frame is drawn from our own unicode detection rather than rich's
    # safe_box guess, so the panel can never emit box-drawing characters that a
    # cp1252 Windows console cannot encode.
    from rich import box as rich_box

    panel = Panel(
        grid,
        title=_title(),
        border_style=theme.color("banner_border") or "none",
        box=rich_box.ROUNDED if theme.supports_unicode() else rich_box.ASCII,
        padding=(0, 2),
    )

    parts = []
    mark = art.wordmark()
    if mark and width >= _WORDMARK_MIN_WIDTH and art.wordmark_width() <= width:
        parts += [mark, ""]
    parts.append(panel)
    return Group(*parts)


def _compact_lines(service: Any, session_id: Optional[str]) -> list[str]:
    """Banner for terminals too narrow for the panel — the same facts, no frame."""
    tools, skills = _tool_names(service), _skill_names(service)
    servers = _mcp_servers(service)

    summary = [f"{len(tools)} tools", f"{len(skills)} skills"]
    if servers:
        summary.append(f"{len(servers)} MCP")
    summary.append("/help")

    separator = f" {theme.glyph('middot')} "
    lines = [
        _title(),
        theme.styled(_model_label(service), "banner_accent"),
        theme.styled(render.shorten_path(os.getcwd(), 40), "banner_dim"),
        theme.styled(separator.join(summary), "banner_dim"),
    ]
    if session_id:
        lines.append(theme.styled(f"Session: {session_id}", "banner_dim"))
    return lines


def print_banner(service: Any, session_id: Optional[str] = None,
                 console: Any = None) -> None:
    """Print the banner. Never raises — a broken banner must not block a session."""
    try:
        from rich.console import Console
        console = console or Console()
        console.print()
        console.print(build(service, session_id, width=console.width))
        console.print()
    except Exception as exc:  # noqa: BLE001
        from namma_agent.core.logger import logger
        logger.warning("[tui] banner failed to render: %s", exc)
