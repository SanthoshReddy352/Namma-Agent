"""News tool — headline briefing from public RSS feeds. Keyless, stdlib-only.

The v1 module routed through a key-gated aggregator + a local LLM summariser.
The v2 port drops both: it fetches well-known RSS feeds directly and returns the
headlines; the agent's own model writes the briefing if asked.

  get_news(category, limit) — category ∈ {technology, world, business, science, security}
"""
from __future__ import annotations

import urllib.request
import xml.etree.ElementTree as ET

from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult

_FEEDS: dict[str, list[str]] = {
    "technology": ["https://feeds.arstechnica.com/arstechnica/index",
                   "https://www.theverge.com/rss/index.xml"],
    "world": ["https://feeds.bbci.co.uk/news/world/rss.xml",
              "https://www.aljazeera.com/xml/rss/all.xml"],
    "business": ["https://feeds.bbci.co.uk/news/business/rss.xml"],
    "science": ["https://feeds.bbci.co.uk/news/science_and_environment/rss.xml"],
    "security": ["https://feeds.feedburner.com/TheHackersNews"],
}
_USER_AGENT = "FRIDAY-Linux-News/2.0"
_TIMEOUT = 10


def _fetch_feed(url: str, limit: int) -> list[dict]:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:  # noqa: S310
        raw = resp.read(1_000_000)
    root = ET.fromstring(raw)
    items = []
    # RSS <item> or Atom <entry>
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("item", "entry"):
            items.append(el)
    out = []
    for item in items[:limit]:
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if title:
            out.append({"title": title.strip(), "url": link.strip()})
    return out


def _child_text(item, name: str) -> str:
    for child in item:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == name:
            if child.text and child.text.strip():
                return child.text
            # Atom <link href="...">
            href = child.attrib.get("href")
            if href:
                return href
    return ""


def _news(args: dict) -> ToolResult:
    category = (args.get("category") or "world").strip().lower()
    if category not in _FEEDS:
        return ToolResult(ok=False, content="",
                          error=f"unknown category {category!r}; choose from {', '.join(_FEEDS)}")
    limit = max(1, min(int(args.get("limit", 5)), 15))
    headlines: list[dict] = []
    for url in _FEEDS[category]:
        try:
            headlines.extend(_fetch_feed(url, limit))
        except Exception as exc:  # noqa: BLE001
            logger.debug("[news] feed failed %s: %s", url, exc)
        if len(headlines) >= limit:
            break
    headlines = headlines[:limit]
    if not headlines:
        return ToolResult(ok=False, content="", error=f"couldn't fetch {category} headlines right now")
    lines = [f"Top {category} headlines:"]
    for i, h in enumerate(headlines, 1):
        lines.append(f"{i}. {h['title']}" + (f"\n   {h['url']}" if h["url"] else ""))
    return ToolResult(ok=True, content="\n".join(lines), data=headlines)


def register(registry: ToolRegistry) -> None:
    registry.register("get_news", "Get current news headlines for a category (keyless RSS).", {
        "type": "object",
        "properties": {
            "category": {"type": "string",
                         "enum": ["technology", "world", "business", "science", "security"],
                         "description": "news category (default world)"},
            "limit": {"type": "integer", "description": "max headlines (1-15, default 5)"},
        },
    }, _news)
