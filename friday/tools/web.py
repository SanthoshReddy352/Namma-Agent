"""Web tools — search, extract, crawl. Stdlib-only, self-contained.

Three tools the model can route to from their schemas:

  web_search  — DuckDuckGo search (duckduckgo-search lib if present, HTML fallback)
  web_extract — fetch a URL and return clean plain text
  web_crawl   — follow links from a seed URL (bounded depth/pages)

No API key required. The model decides *whether* a URL is appropriate to fetch;
the code just runs the fetch and caps the size.
"""
from __future__ import annotations

import html
import html.parser
import re
import urllib.parse
import urllib.request

from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult

_FETCH_CAP = 512 * 1024  # bytes read off the wire
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


# ── HTML → plain text ────────────────────────────────────────────────────────

class _TextExtractor(html.parser.HTMLParser):
    _SKIP = {"script", "style", "noscript", "head", "nav", "footer"}

    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
        self._skip_depth = 0
        self._links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith("http"):
                self._links.append(href)

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)

    def get_links(self) -> list[str]:
        return self._links


def _html_to_text(raw_html: str) -> tuple[str, list[str]]:
    extractor = _TextExtractor()
    try:
        extractor.feed(html.unescape(raw_html))
    except Exception:  # noqa: BLE001
        pass
    text = re.sub(r"\s{3,}", "  ", extractor.get_text())
    return text, extractor.get_links()


def _fetch_url(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        raw = resp.read(_FETCH_CAP)
        charset = "utf-8"
        ct = resp.headers.get("Content-Type", "")
        if "charset=" in ct:
            charset = ct.split("charset=")[-1].split(";")[0].strip()
        return raw.decode(charset, errors="replace")


# ── DuckDuckGo search ────────────────────────────────────────────────────────

_DDG_REDIRECT_RE = re.compile(r"^https?://(?:www\.)?duckduckgo\.com/l/?\?", re.IGNORECASE)


def _unwrap_ddg_redirect(url: str) -> str:
    """DDG HTML wraps result links in a `/l/?uddg=<encoded real URL>` tracker
    that 400s a lot and can't be followed — hand back the decoded destination."""
    if not url or not _DDG_REDIRECT_RE.match(url):
        return url
    try:
        parsed = urllib.parse.urlparse(html.unescape(url))
        real = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
        if real:
            return urllib.parse.unquote(real)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[web_search] DDG unwrap failed for %s: %s", url[:80], exc)
    return url


def _ddg_search(query: str, max_results: int) -> list[dict]:
    """duckduckgo-search lib if installed, else the keyless DDG HTML endpoint."""
    try:
        from duckduckgo_search import DDGS  # noqa: PLC0415

        results = list(DDGS().text(query, max_results=max_results))
        return [{
            "title": r.get("title", ""),
            "url": _unwrap_ddg_redirect(r.get("href", "")),
            "snippet": r.get("body", ""),
        } for r in results]
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.debug("[web_search] DDGS lib failed: %s", exc)

    try:
        q = urllib.parse.quote_plus(query)
        raw = _fetch_url(f"https://html.duckduckgo.com/html/?q={q}", timeout=8)
        results: list[dict] = []
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>([^<]+)', raw):
            url, title = m.group(1), html.unescape(m.group(2)).strip()
            if url.startswith("//"):
                url = "https:" + url
            url = _unwrap_ddg_redirect(url)
            if url.startswith("http") and len(results) < max_results:
                results.append({"title": title, "url": url, "snippet": ""})
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("[web_search] DDG fallback failed: %s", exc)
        return []


# ── Handlers ─────────────────────────────────────────────────────────────────

def _search(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(ok=False, content="", error="no query given")
    limit = max(1, min(int(args.get("limit", 5)), 10))
    results = _ddg_search(query, limit)
    if not results:
        return ToolResult(ok=False, content="", error=f"no results for: {query}")
    lines = [f"Search results for {query!r}:"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet'][:200]}")
    return ToolResult(ok=True, content="\n".join(lines), data=results)


def _extract(args: dict) -> ToolResult:
    url = (args.get("url") or "").strip()
    if not url.startswith("http"):
        return ToolResult(ok=False, content="", error="a full http(s) URL is required")
    try:
        text, _ = _html_to_text(_fetch_url(url))
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"couldn't fetch {url}: {exc}")
    if len(text) > 4000:
        text = text[:4000] + "…"
    return ToolResult(ok=True, content=text or "(page had no readable text)")


def _crawl(args: dict) -> ToolResult:
    url = (args.get("url") or "").strip()
    if not url.startswith("http"):
        return ToolResult(ok=False, content="", error="a full http(s) seed URL is required")
    depth = max(1, min(int(args.get("depth", 1)), 2))
    visited: set[str] = set()
    collected: list[str] = []
    _crawl_page(url, depth, visited, collected)
    if not collected:
        return ToolResult(ok=False, content="", error="couldn't extract content from that site")
    combined = "\n\n---\n\n".join(collected[:3])
    return ToolResult(ok=True, content=combined[:5000])


def _crawl_page(url: str, depth: int, visited: set, collected: list) -> None:
    if url in visited or len(collected) >= 3:
        return
    visited.add(url)
    try:
        text, links = _html_to_text(_fetch_url(url, timeout=8))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[web_crawl] failed to fetch %s: %s", url, exc)
        return
    if text:
        collected.append(f"[{url}]\n{text[:2000]}")
    if depth > 1:
        for link in links[:5]:
            if link not in visited:
                _crawl_page(link, depth - 1, visited, collected)


def register(registry: ToolRegistry) -> None:
    registry.register("web_search", "Search the web (DuckDuckGo) and return ranked results.", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "what to search for"},
            "limit": {"type": "integer", "description": "max results (1-10, default 5)"},
        },
        "required": ["query"],
    }, _search)

    registry.register("web_extract", "Fetch a web page and return its readable text.", {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "full http(s) URL"}},
        "required": ["url"],
    }, _extract)

    registry.register("web_crawl", "Follow links from a seed URL and collect page text (bounded).", {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "full http(s) seed URL"},
            "depth": {"type": "integer", "description": "crawl depth (1-2, default 1)"},
        },
        "required": ["url"],
    }, _crawl)
