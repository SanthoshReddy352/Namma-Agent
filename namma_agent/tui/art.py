"""ASCII artwork for the TUI banner: the hero emblem and the name wordmark.

Two pieces:

* :func:`hero` — Namma's emblem, a diya (oil lamp) with a rising flame and
  radiating light. Composed as a tall, narrow, symmetric figure so it sits in
  the banner's left column, and colored as a gradient from the flame's gold down
  to the lamp's bronze.
* :func:`wordmark` — the assistant's name in a six-row block font, rendered at
  runtime from :func:`namma_agent.config.assistant_name`. Nothing here is
  hardcoded to "Namma": rename the assistant and the wordmark follows.

Both degrade: terminals without UTF-8 get a plain-text banner instead of
mojibake, and narrow terminals get the compact emblem.
"""
from __future__ import annotations

from typing import Optional

from namma_agent.tui import theme

# ── The hero emblem ────────────────────────────────────────────────────
# A diya with its flame: teardrop flame, wick, shallow bowl, footed base, and
# two rays of cast light. Rows are given as (token, gradient-key) and centered
# programmatically on a fixed width, so the figure can never drift off-axis.
# The key names a skin color, so a reskin recolors the emblem without redrawing.
_HERO_WIDTH = 29

_HERO_ROWS: list[tuple[str, str]] = [
    ("▄", "banner_title"),
    ("▟█▙", "banner_title"),
    ("▟███▙", "banner_title"),
    ("▜███▛", "banner_accent"),
    ("▜█▛", "banner_accent"),
    ("▐▌", "banner_accent"),
    ("·           ▐▌           ·", "banner_dim"),
    ("▗▄▄▄▄▄▄▄▄▟▙▄▄▄▄▄▄▄▄▖", "banner_accent"),
    ("▜██████████████████▛", "banner_border"),
    ("▝▜██████████████▛▘", "banner_border"),
    ("▝▀▀▀▀▀▀▀▀▀▀▘", "banner_border"),
    ("▀▀▀▀▀▀", "banner_dim"),
]

# Same figure, six rows, for terminals too short or narrow for the full one.
_HERO_COMPACT_WIDTH = 15
_HERO_COMPACT_ROWS: list[tuple[str, str]] = [
    ("▄", "banner_title"),
    ("▟█▙", "banner_title"),
    ("▐▌", "banner_accent"),
    ("▗▄▄▄▟▙▄▄▄▖", "banner_accent"),
    ("▜█████████▛", "banner_border"),
    ("▝▀▀▀▀▀▀▘", "banner_dim"),
]


def _center(token: str, width: int) -> str:
    """Center a token on ``width`` columns, padded so every row is equal length."""
    pad = width - len(token)
    left = pad // 2
    return " " * left + token + " " * (pad - left)


def hero_rows(compact: bool = False) -> list[tuple[str, str]]:
    """The emblem as ``(plain, markup)`` rows.

    Callers need the plain text to measure alignment: rich strips trailing
    whitespace and re-justifies each line on its own visible width, which pulls
    a centered figure apart unless the caller does the padding itself.
    """
    skin = theme.get_active_skin()
    if skin.hero:
        return [(line, line) for line in skin.hero.splitlines()]
    if not theme.supports_unicode():
        return []
    rows = _HERO_COMPACT_ROWS if compact else _HERO_ROWS
    width = _HERO_COMPACT_WIDTH if compact else _HERO_WIDTH
    out = []
    for token, key in rows:
        text = _center(token, width)
        color = skin.get_color(key)
        out.append((text, f"[{color}]{text}[/]" if color else text))
    return out


def hero(compact: bool = False) -> str:
    """The emblem as rich markup, or "" when the terminal can't render it.

    A skin's ``hero:`` value replaces this wholesale (it is used verbatim, so a
    skin author supplies their own markup).
    """
    return "\n".join(markup for _plain, markup in hero_rows(compact))


# ── The block font ─────────────────────────────────────────────────────
# Six-row glyphs. Every glyph is exactly six lines; widths vary per character
# and are padded to a common height when composed.
_FONT: dict[str, list[str]] = {
    "A": [" █████╗ ", "██╔══██╗", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "B": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██████╔╝", "╚═════╝ "],
    "C": [" ██████╗", "██╔════╝", "██║     ", "██║     ", "╚██████╗", " ╚═════╝"],
    "D": ["██████╗ ", "██╔══██╗", "██║  ██║", "██║  ██║", "██████╔╝", "╚═════╝ "],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "F": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "██║     ", "╚═╝     "],
    "G": [" ██████╗ ", "██╔════╝ ", "██║  ███╗", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "H": ["██╗  ██╗", "██║  ██║", "███████║", "██╔══██║", "██║  ██║", "╚═╝  ╚═╝"],
    "I": ["██╗", "██║", "██║", "██║", "██║", "╚═╝"],
    "J": ["     ██╗", "     ██║", "     ██║", "██   ██║", "╚█████╔╝", " ╚════╝ "],
    "K": ["██╗  ██╗", "██║ ██╔╝", "█████╔╝ ", "██╔═██╗ ", "██║  ██╗", "╚═╝  ╚═╝"],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "M": ["███╗   ███╗", "████╗ ████║", "██╔████╔██║", "██║╚██╔╝██║", "██║ ╚═╝ ██║", "╚═╝     ╚═╝"],
    "N": ["███╗   ██╗", "████╗  ██║", "██╔██╗ ██║", "██║╚██╗██║", "██║ ╚████║", "╚═╝  ╚═══╝"],
    "O": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "P": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔═══╝ ", "██║     ", "╚═╝     "],
    "Q": [" ██████╗ ", "██╔═══██╗", "██║   ██║", "██║▄▄ ██║", "╚██████╔╝", " ╚══▀▀═╝ "],
    "R": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██║  ██║", "╚═╝  ╚═╝"],
    "S": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
    "U": ["██╗   ██╗", "██║   ██║", "██║   ██║", "██║   ██║", "╚██████╔╝", " ╚═════╝ "],
    "V": ["██╗   ██╗", "██║   ██║", "██║   ██║", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚═══╝  "],
    "W": ["██╗    ██╗", "██║    ██║", "██║ █╗ ██║", "██║███╗██║", "╚███╔███╔╝", " ╚══╝╚══╝ "],
    "X": ["██╗  ██╗", "╚██╗██╔╝", " ╚███╔╝ ", " ██╔██╗ ", "██╔╝ ██╗", "╚═╝  ╚═╝"],
    "Y": ["██╗   ██╗", "╚██╗ ██╔╝", " ╚████╔╝ ", "  ╚██╔╝  ", "   ██║   ", "   ╚═╝   "],
    "Z": ["███████╗", "╚══███╔╝", "  ███╔╝ ", " ███╔╝  ", "███████╗", "╚══════╝"],
    "0": [" ██████╗ ", "██╔═████╗", "██║██╔██║", "████╔╝██║", "╚██████╔╝", " ╚═════╝ "],
    "1": [" ██╗", "███║", "╚██║", " ██║", " ██║", " ╚═╝"],
    "2": ["██████╗ ", "╚════██╗", " █████╔╝", "██╔═══╝ ", "███████╗", "╚══════╝"],
    "3": ["██████╗ ", "╚════██╗", " █████╔╝", " ╚═══██╗", "██████╔╝", "╚═════╝ "],
    "4": ["██╗  ██╗", "██║  ██║", "███████║", "╚════██║", "     ██║", "     ╚═╝"],
    "5": ["███████╗", "██╔════╝", "███████╗", "╚════██║", "███████║", "╚══════╝"],
    "6": [" ██████╗ ", "██╔════╝ ", "███████╗ ", "██╔═══██╗", "╚██████╔╝", " ╚═════╝ "],
    "7": ["███████╗", "╚══██╔═╝", "   ██║  ", "   ██║  ", "   ██║  ", "   ╚═╝  "],
    "8": [" █████╗ ", "██╔══██╗", "╚█████╔╝", "██╔══██╗", "╚█████╔╝", " ╚════╝ "],
    "9": [" █████╗ ", "██╔══██╗", "╚██████║", " ╚═══██║", " █████╔╝", " ╚════╝ "],
    " ": ["    ", "    ", "    ", "    ", "    ", "    "],
    "-": ["      ", "      ", "█████╗", "╚════╝", "      ", "      "],
    ".": ["   ", "   ", "   ", "   ", "██╗", "╚═╝"],
    "'": ["██╗", "╚═╝", "   ", "   ", "   ", "   "],
}

_GLYPH_ROWS = 6

# Row-by-row gradient down the wordmark, mirroring the emblem's flame-to-lamp fade.
_WORDMARK_GRADIENT = [
    "banner_title", "banner_title", "banner_accent",
    "banner_accent", "banner_border", "banner_border",
]


def wordmark_width(name: Optional[str] = None) -> int:
    """Columns the wordmark needs, so callers can pick it or the compact banner."""
    return len(_wordmark_rows(name)[0]) if _wordmark_rows(name) else 0


def _wordmark_rows(name: Optional[str] = None) -> list[str]:
    """The wordmark as six plain (uncolored) rows. Unknown characters are dropped."""
    from namma_agent.config import assistant_name

    text = (name if name is not None else assistant_name()).upper()
    glyphs = [_FONT[ch] for ch in text if ch in _FONT]
    if not glyphs:
        return []
    return ["".join(g[row] for g in glyphs) for row in range(_GLYPH_ROWS)]


def wordmark(name: Optional[str] = None) -> str:
    """The assistant's name in block letters as rich markup.

    Returns ``""`` when the terminal can't render box-drawing glyphs — the
    banner then falls back to a plain title. A skin's ``wordmark:`` replaces it.
    """
    skin = theme.get_active_skin()
    if skin.wordmark:
        return skin.wordmark
    if not theme.supports_unicode():
        return ""
    rows = _wordmark_rows(name)
    if not rows:
        return ""
    out = []
    for i, row in enumerate(rows):
        color = skin.get_color(_WORDMARK_GRADIENT[i])
        bold = "bold " if i < 2 else ""
        out.append(f"[{bold}{color}]{row}[/]" if color else row)
    return "\n".join(out)
