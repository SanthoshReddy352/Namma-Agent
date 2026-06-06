"""Browser tools — open URLs / searches in the user's web browser.

Lightweight and cross-platform via the stdlib :mod:`webbrowser` module — no
Selenium/Playwright dependency. The heavy "controlled browser session" media
control from v1 is dropped; the model opens destinations and lets the OS browser
handle playback.

  open_browser_url    — open any URL
  search_google       — open a Google results page
  play_youtube        — open a YouTube search (first video autoplays)
  play_youtube_music  — open a YouTube Music search
"""
from __future__ import annotations

import urllib.parse
import webbrowser

from friday.core.tools import ToolRegistry, ToolResult


def _open(url: str, what: str) -> ToolResult:
    try:
        opened = webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))
    if not opened:
        return ToolResult(ok=False, content="", error="no usable web browser found")
    return ToolResult(ok=True, content=f"Opened {what}: {url}", data={"url": url})


def _open_url(args: dict) -> ToolResult:
    url = (args.get("url") or "").strip()
    if not url:
        return ToolResult(ok=False, content="", error="no url given")
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return _open(url, "page")


def _search_google(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="no query given")
    q = urllib.parse.quote_plus(query)
    return _open(f"https://www.google.com/search?q={q}", f"Google search for {query!r}")


def _play_youtube(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="no query given")
    q = urllib.parse.quote_plus(query)
    return _open(f"https://www.youtube.com/results?search_query={q}",
                 f"YouTube search for {query!r}")


def _play_youtube_music(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="no query given")
    q = urllib.parse.quote_plus(query)
    return _open(f"https://music.youtube.com/search?q={q}",
                 f"YouTube Music search for {query!r}")


def register(registry: ToolRegistry) -> None:
    registry.register("open_browser_url", "Open a URL in the user's web browser.", {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "the URL (scheme optional)"}},
        "required": ["url"],
    }, _open_url)

    registry.register("search_google", "Open a Google search results page in the browser.", {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "what to search for"}},
        "required": ["query"],
    }, _search_google)

    registry.register("play_youtube", "Open a YouTube search in the browser (first result plays).", {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "video title or terms"}},
        "required": ["query"],
    }, _play_youtube)

    registry.register("play_youtube_music", "Open a YouTube Music search in the browser.", {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "song/artist/album"}},
        "required": ["query"],
    }, _play_youtube_music)
