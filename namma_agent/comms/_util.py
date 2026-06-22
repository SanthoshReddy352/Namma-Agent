"""Shared helpers for outbound messaging channels (Slack/WhatsApp/Signal).

Stdlib-only. Telegram keeps its own chunker (tests import it); this is the
neutral version the newer channels share so each one doesn't re-implement it.
"""
from __future__ import annotations


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
