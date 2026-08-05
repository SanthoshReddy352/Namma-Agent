"""Palette, skins, and terminal color-depth handling for the TUI.

One :class:`Skin` owns every color the terminal UI paints, plus the spinner's
faces and verbs and an optional replacement hero emblem. The default skin
("namma") is the gold-on-midnight scheme the banner, status bar and input rules
are designed around.

Users drop ``<name>.yaml`` into ``~/.namma_agent/skins/`` and select it with
``tui.skin`` in the config (or the ``NAMMA_TUI_SKIN`` env var) — same shape as
the built-ins below, and any key left out falls back to the default.

Color depth is detected once and applied everywhere: Windows Terminal, iTerm and
modern Linux terminals get 24-bit hex, legacy ``conhost.exe`` and ``TERM=xterm``
degrade to the 16/256-color cube, and ``NO_COLOR``/non-TTY output goes plain.
"""
from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from namma_agent.core.logger import logger

# ── The default palette ────────────────────────────────────────────────
# Gold → amber → bronze on midnight chrome. Keys are semantic, not literal, so
# a skin can recolor the whole UI without any module knowing what a color is.
DEFAULT_COLORS: dict[str, str] = {
    # Banner
    "banner_title": "#FFD700",   # gold — the version label in the panel title
    "banner_border": "#CD7F32",  # bronze — the panel frame
    "banner_accent": "#FFBF00",  # amber — section headings, the model name
    "banner_dim": "#B8860B",     # dark gold — labels, separators, the cwd
    "banner_text": "#FFF8DC",    # cornsilk — tool and skill names
    "session_border": "#8B8682", # warm grey — the session id line
    # Chrome (status bar, completion menu)
    "chrome_bg": "#1a1a2e",
    "chrome_fg": "#C0C0C0",
    "chrome_strong": "#FFD700",
    "chrome_dim": "#8B8682",
    "chrome_sel_bg": "#333355",
    # Semantic states
    "good": "#8FBC8F",
    "warn": "#FFD700",
    "bad": "#FF8C00",
    "critical": "#FF6B6B",
    "danger": "#FF4444",
    "info": "#87CEEB",
    # Input area
    "input_rule": "#CD7F32",     # bronze rules above and below the prompt
    "hint": "#888888",
    # Transcript
    "user_label": "#FFBF00",
    "agent_label": "#FFD700",
    "tool_line": "#B8860B",
    "diff_plus": "#8FBC8F",
    "diff_minus": "#FF6B6B",
    "diff_hunk": "#87CEEB",
}

# The spinner's personality. Skins may replace any of these lists.
DEFAULT_SPINNER: dict[str, list[str]] = {
    "frames": ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"],
    "waiting_faces": [
        "(◕‿◕)", "(◠‿◠)", "( ˘▽˘)", "(≧◡≦)", "(★‿★)",
        "٩(◕‿◕)۶", "(✿◠‿◠)", "(◕ᴗ◕)", "ヾ(＾∇＾)", "(´｡• ᵕ •｡`)",
    ],
    "thinking_faces": [
        "(◔_◔)", "(¬‿¬)", "(⌐■_■)", "(´･_･`)", "◉_◉",
        "( ˘⌣˘)", "(⊙_⊙)", "(•_•)", "(°ロ°)", "(๑•̀ㅂ•́)",
    ],
    "thinking_verbs": [
        "pondering", "contemplating", "musing", "deliberating", "reflecting",
        "processing", "reasoning", "analyzing", "synthesizing", "formulating",
        "weighing", "considering", "working", "thinking", "figuring it out",
    ],
}

_ASCII_SPINNER_FRAMES = ["|", "/", "-", "\\"]


@dataclass
class Skin:
    """A named palette + spinner personality + optional hero art override."""

    name: str = "namma"
    colors: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_COLORS))
    spinner: dict[str, list[str]] = field(default_factory=lambda: {
        k: list(v) for k, v in DEFAULT_SPINNER.items()
    })
    hero: Optional[str] = None      # replaces the banner's emblem
    wordmark: Optional[str] = None  # replaces the rendered name wordmark

    def get_color(self, key: str, fallback: str = "") -> str:
        """The color for ``key``, degraded to what this terminal can show.

        Returns ``""`` when color is off entirely, which is a no-op in both a
        rich markup tag and a prompt_toolkit style string.
        """
        raw = self.colors.get(key) or DEFAULT_COLORS.get(key) or fallback
        return downgrade(raw)

    def frames(self) -> list[str]:
        """Spinner frames, falling back to ASCII where braille won't render."""
        if not supports_unicode():
            return list(_ASCII_SPINNER_FRAMES)
        return list(self.spinner.get("frames") or DEFAULT_SPINNER["frames"])

    def faces(self, kind: str = "waiting") -> list[str]:
        """Kaomoji for the spinner. Empty when the terminal can't render them."""
        if not supports_unicode():
            return []
        key = "thinking_faces" if kind == "thinking" else "waiting_faces"
        return list(self.spinner.get(key) or DEFAULT_SPINNER[key])

    def verbs(self) -> list[str]:
        return list(self.spinner.get("thinking_verbs") or DEFAULT_SPINNER["thinking_verbs"])


# ── Color-depth detection ──────────────────────────────────────────────

TRUECOLOR = "truecolor"
ANSI256 = "256"
ANSI16 = "16"
NOCOLOR = "none"


@lru_cache(maxsize=1)
def color_depth() -> str:
    """What this terminal can actually paint.

    Honors ``NO_COLOR`` (https://no-color.org/) and ``TERM=dumb``, requires a
    TTY, and treats Windows Terminal / ConEmu / modern VTE as truecolor.
    ``NAMMA_TUI_COLOR`` (truecolor|256|16|none) overrides the whole check.
    """
    forced = (os.environ.get("NAMMA_TUI_COLOR") or "").strip().lower()
    if forced in (TRUECOLOR, ANSI256, ANSI16, NOCOLOR):
        return forced
    if os.environ.get("NO_COLOR") is not None:
        return NOCOLOR
    if os.environ.get("TERM") == "dumb":
        return NOCOLOR
    try:
        if not sys.stdout.isatty():
            return NOCOLOR
    except (ValueError, OSError):  # stream closed underneath us
        return NOCOLOR

    if (os.environ.get("COLORTERM") or "").lower() in ("truecolor", "24bit"):
        return TRUECOLOR
    if platform.system() == "Windows":
        # WT_SESSION marks Windows Terminal; ConEmu and VS Code's terminal both
        # advertise themselves too. Anything else is likely legacy conhost,
        # which only reliably does the 16-color set.
        if os.environ.get("WT_SESSION") or os.environ.get("ConEmuANSI") == "ON":
            return TRUECOLOR
        if os.environ.get("TERM_PROGRAM") == "vscode":
            return TRUECOLOR
        return ANSI16
    term = (os.environ.get("TERM") or "").lower()
    if "256" in term:
        return ANSI256
    if term in ("", "xterm", "vt100", "linux"):
        return ANSI16
    return ANSI256


@lru_cache(maxsize=1)
def supports_unicode() -> bool:
    """Whether braille/kaomoji glyphs will render instead of mojibake.

    ``NAMMA_TUI_ASCII=1`` forces the ASCII path (useful for CI logs and for
    terminals that claim UTF-8 but render double-width glyphs badly).
    """
    if (os.environ.get("NAMMA_TUI_ASCII") or "").strip() in ("1", "true", "yes"):
        return False
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in encoding


@lru_cache(maxsize=256)
def downgrade(hex_color: str) -> str:
    """Map a ``#RRGGBB`` color onto what :func:`color_depth` can display.

    Truecolor passes through. 256-color returns an ``ansi256`` index that rich
    and prompt_toolkit both understand. 16-color picks the nearest basic ANSI
    name. No-color returns ``""``.
    """
    if not hex_color or not hex_color.startswith("#") or len(hex_color) != 7:
        return hex_color if color_depth() != NOCOLOR else ""
    depth = color_depth()
    if depth == NOCOLOR:
        return ""
    if depth == TRUECOLOR:
        return hex_color
    try:
        r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return hex_color
    if depth == ANSI256:
        return f"color({_rgb_to_256(r, g, b)})"
    return _rgb_to_ansi16(r, g, b)


def _rgb_to_256(r: int, g: int, b: int) -> int:
    """Nearest xterm-256 index: the 6x6x6 cube, or the greyscale ramp."""
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + round((r - 8) / 247 * 24)
    cube = [round(c / 255 * 5) for c in (r, g, b)]
    return 16 + 36 * cube[0] + 6 * cube[1] + cube[2]


# The 16 basic ANSI colors, as (name, r, g, b). Bright variants included so
# gold doesn't collapse to a muddy dark yellow on legacy conhost.
_ANSI16 = [
    ("ansiblack", 0, 0, 0), ("ansired", 170, 0, 0),
    ("ansigreen", 0, 170, 0), ("ansiyellow", 170, 85, 0),
    ("ansiblue", 0, 0, 170), ("ansimagenta", 170, 0, 170),
    ("ansicyan", 0, 170, 170), ("ansiwhite", 170, 170, 170),
    ("ansibrightblack", 85, 85, 85), ("ansibrightred", 255, 85, 85),
    ("ansibrightgreen", 85, 255, 85), ("ansibrightyellow", 255, 255, 85),
    ("ansibrightblue", 85, 85, 255), ("ansibrightmagenta", 255, 85, 255),
    ("ansibrightcyan", 85, 255, 255), ("ansibrightwhite", 255, 255, 255),
]


def _rgb_to_ansi16(r: int, g: int, b: int) -> str:
    """Nearest basic ANSI color by squared distance in RGB space."""
    best, best_dist = _ANSI16[0][0], None
    for name, cr, cg, cb in _ANSI16:
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if best_dist is None or dist < best_dist:
            best, best_dist = name, dist
    return best


def prompt_toolkit_color_depth():
    """The matching ``prompt_toolkit.output.ColorDepth``, or None to let it decide."""
    try:
        from prompt_toolkit.output import ColorDepth
    except ImportError:  # pragma: no cover - prompt_toolkit is an optional dep
        return None
    return {
        TRUECOLOR: ColorDepth.TRUE_COLOR,
        ANSI256: ColorDepth.DEPTH_8_BIT,
        ANSI16: ColorDepth.DEPTH_4_BIT,
        NOCOLOR: ColorDepth.DEPTH_1_BIT,
    }.get(color_depth())


# ── Skin loading ───────────────────────────────────────────────────────

_active: Optional[Skin] = None


def skins_dir() -> Path:
    """Where user-authored skins live."""
    return Path.home() / ".namma_agent" / "skins"


def available_skins() -> list[str]:
    """Built-in plus user skin names, sorted, deduped."""
    names = {"namma"}
    try:
        for path in skins_dir().glob("*.y*ml"):
            names.add(path.stem)
    except OSError:
        pass
    return sorted(names)


def load_skin(name: str) -> Skin:
    """Load a skin by name. Unknown names and unreadable files fall back to the
    default rather than taking the UI down."""
    if not name or name == "namma":
        return Skin()
    for suffix in (".yaml", ".yml"):
        path = skins_dir() / f"{name}{suffix}"
        if not path.exists():
            continue
        try:
            import yaml
            data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception as exc:  # noqa: BLE001 - a bad skin must never block startup
            logger.warning("[tui] skin %s failed to load: %s", name, exc)
            return Skin()
        colors = dict(DEFAULT_COLORS)
        colors.update({k: str(v) for k, v in (data.get("colors") or {}).items()})
        spinner = {k: list(v) for k, v in DEFAULT_SPINNER.items()}
        for key, value in (data.get("spinner") or {}).items():
            if isinstance(value, list) and value:
                spinner[key] = [str(v) for v in value]
        return Skin(name=name, colors=colors, spinner=spinner,
                    hero=data.get("hero"), wordmark=data.get("wordmark"))
    logger.warning("[tui] skin %s not found in %s — using the default", name, skins_dir())
    return Skin()


def get_active_skin(config: Optional[dict] = None) -> Skin:
    """The process-wide active skin (loaded once, then cached).

    Resolution: ``$NAMMA_TUI_SKIN`` → ``tui.skin`` in the config → ``namma``.
    """
    global _active
    if _active is not None:
        return _active
    name = os.environ.get("NAMMA_TUI_SKIN") or ""
    if not name and config is not None:
        name = str((config.get("tui") or {}).get("skin") or "")
    _active = load_skin(name)
    return _active


def set_active_skin(skin: Skin | str) -> Skin:
    """Swap the active skin at runtime (the ``/skin`` command)."""
    global _active
    _active = load_skin(skin) if isinstance(skin, str) else skin
    return _active


def color(key: str, fallback: str = "") -> str:
    """Shorthand for ``get_active_skin().get_color(key, fallback)``."""
    return get_active_skin().get_color(key, fallback)


# Decorative characters, each with an ASCII stand-in. Every one of these must go
# through :func:`glyph` — writing them literally crashes with UnicodeEncodeError
# on a legacy Windows console (cp1252), which is a supported target.
_GLYPHS: dict[str, tuple[str, str]] = {
    "ellipsis": ("…", "..."),
    "middot": ("·", "-"),
    "vbar": ("│", "|"),
    "hbar": ("─", "-"),
    "prompt": ("❯", ">"),
    "check": ("✓", "ok"),
    "cross": ("✗", "!!"),
    "warn": ("⚠", "!!"),
    "arrow_left": ("←", "<"),
    "emdash": ("—", "-"),
}


def glyph(name: str) -> str:
    """A decorative character, or its ASCII stand-in on terminals without UTF-8."""
    unicode_char, ascii_char = _GLYPHS.get(name, ("", ""))
    return unicode_char if supports_unicode() else ascii_char


def styled(text: str, key: str = "", *, bold: bool = False) -> str:
    """Wrap ``text`` in rich markup for the skin color ``key``.

    Always build markup through this rather than by hand. When color is off
    (``NO_COLOR``, a pipe, legacy conhost) :func:`color` returns ``""``, and an
    f-string like ``f"[{c}]{text}[/]"`` then produces ``[]text[/]`` — which rich
    rejects with ``MarkupError``, so the line silently never prints.
    """
    tag = " ".join(part for part in ("bold" if bold else "", color(key) if key else "") if part)
    return f"[{tag}]{text}[/]" if tag else text


def reset_caches() -> None:
    """Drop every cached detection + the active skin. For tests.

    Tolerates a detector having been monkeypatched with a plain function (which
    has no ``cache_clear``) — a reset helper must not itself raise.
    """
    global _active
    _active = None
    for fn in (color_depth, supports_unicode, downgrade):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()
