"""Shared helpers for outbound messaging channels (Slack/WhatsApp/Signal).

Stdlib-only. Telegram keeps its own chunker (tests import it); this is the
neutral version the newer channels share so each one doesn't re-implement it.
"""
from __future__ import annotations

import re


def markdown_to_whatsapp(text: str) -> str:
    """Render the model's Markdown into WhatsApp's own lightweight formatting so
    replies read cleanly (like the Telegram HTML path) instead of showing raw
    ``**`` / ``##`` noise. WhatsApp uses ``*bold*``, ``_italic_``, ``~strike~`` and
    triple-backtick monospace — close enough to map onto directly."""
    if not text:
        return text
    s = text
    s = re.sub(r"\*\*(.+?)\*\*", r"*\1*", s, flags=re.S)   # **bold** → *bold*
    s = re.sub(r"__(.+?)__", r"*\1*", s, flags=re.S)        # __bold__ → *bold*
    s = re.sub(r"~~(.+?)~~", r"~\1~", s, flags=re.S)        # ~~strike~~ → ~strike~
    s = re.sub(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*#*$", r"*\1*", s)  # # Heading → *Heading*
    s = re.sub(r"(?m)^(\s*)[-*+]\s+", r"\1• ", s)          # bullet markers → •
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", s)  # [t](url) → t (url)
    return s


def chunk_text(text: str, limit: int) -> list[str]:
    """Split ``text`` into pieces no longer than ``limit`` chars, preferring to
    break on a newline or sentence boundary so messages don't snap mid-word."""
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
