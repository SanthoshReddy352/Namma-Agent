"""Phase 7 Wave 2 — web / browser / network / security tools.

Network-touching paths (web search/extract/crawl, ping, public_ip) are exercised
with monkeypatched fetchers/subprocess so the suite stays offline and fast.
"""
from __future__ import annotations

import pytest

from friday.core.safety import is_destructive
from friday.core.tools import ToolRegistry
from friday.tools import load_tools
from friday.tools import network as net
from friday.tools import security as sec
from friday.tools import web as webmod


@pytest.fixture
def reg():
    return load_tools(ToolRegistry())


def test_autodiscovery_registers_wave2_tools(reg):
    for name in ("web_search", "web_extract", "web_crawl",
                 "open_browser_url", "search_google", "play_youtube", "play_youtube_music",
                 "ping_host", "dns_lookup", "check_port", "public_ip",
                 "port_scan", "ping_sweep", "dir_enum", "dns_enum"):
        assert name in reg, name


# ── web ──────────────────────────────────────────────────────────────────────

def test_web_search_formats_results(reg, monkeypatch):
    monkeypatch.setattr(webmod, "_ddg_search",
                        lambda q, n: [{"title": "Py", "url": "https://python.org", "snippet": "lang"}])
    r = reg.execute("web_search", {"query": "python"})
    assert r.ok and "python.org" in r.content and r.data[0]["title"] == "Py"


def test_web_search_empty_query(reg):
    r = reg.execute("web_search", {"query": ""})
    assert not r.ok


def test_web_extract_strips_html(reg, monkeypatch):
    monkeypatch.setattr(webmod, "_fetch_url",
                        lambda url, timeout=10: "<html><body><p>Hello</p><script>x</script></body></html>")
    r = reg.execute("web_extract", {"url": "https://example.com"})
    assert r.ok and "Hello" in r.content and "x" not in r.content


def test_web_extract_requires_http(reg):
    r = reg.execute("web_extract", {"url": "ftp://nope"})
    assert not r.ok


def test_ddg_unwrap_redirect():
    wrapped = "https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fa&rut=z"
    assert webmod._unwrap_ddg_redirect(wrapped) == "https://example.com/a"


# ── browser ──────────────────────────────────────────────────────────────────

def test_open_browser_url_adds_scheme(reg, monkeypatch):
    seen = {}
    monkeypatch.setattr("webbrowser.open", lambda url: seen.setdefault("url", url) or True)
    r = reg.execute("open_browser_url", {"url": "example.com"})
    assert r.ok and seen["url"] == "https://example.com"


def test_search_google_builds_query(reg, monkeypatch):
    seen = {}
    monkeypatch.setattr("webbrowser.open", lambda url: seen.setdefault("url", url) or True)
    r = reg.execute("search_google", {"query": "hello world"})
    assert r.ok and "google.com/search?q=hello+world" in seen["url"]


def test_play_youtube_no_browser(reg, monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda url: False)
    r = reg.execute("play_youtube", {"query": "lofi"})
    assert not r.ok and "browser" in r.error


# ── network ──────────────────────────────────────────────────────────────────

def test_dns_lookup_resolves(reg, monkeypatch):
    monkeypatch.setattr(net.socket, "getaddrinfo",
                        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))])
    r = reg.execute("dns_lookup", {"host": "example.com"})
    assert r.ok and "93.184.216.34" in r.content


def test_check_port_open(reg, monkeypatch):
    class _Sock:
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(net.socket, "create_connection", lambda addr, timeout=3: _Sock())
    r = reg.execute("check_port", {"host": "127.0.0.1", "port": 80})
    assert r.ok and r.data["open"] is True


def test_check_port_closed(reg, monkeypatch):
    def _boom(addr, timeout=3):
        raise OSError("refused")
    monkeypatch.setattr(net.socket, "create_connection", _boom)
    r = reg.execute("check_port", {"host": "127.0.0.1", "port": 81})
    assert r.ok and r.data["open"] is False


def test_check_port_invalid(reg):
    assert not reg.execute("check_port", {"host": "127.0.0.1", "port": 99999}).ok


def test_ping_host_invalid_host(reg):
    assert not reg.execute("ping_host", {"host": "bad;rm -rf"}).ok


# ── security gating ───────────────────────────────────────────────────────────

def test_security_off_by_default(reg, monkeypatch):
    monkeypatch.setattr(sec, "_cfg", lambda: {"lab_mode": False})
    r = reg.execute("port_scan", {"target": "127.0.0.1"})
    assert not r.ok and "lab_mode" in r.error


def test_security_blocks_unauthorized_target(monkeypatch):
    monkeypatch.setattr(sec, "_cfg",
                        lambda: {"lab_mode": True, "authorized_scopes": ["192.168.1.0/24"]})
    r = sec._port_scan({"target": "8.8.8.8"})
    assert not r.ok and "authorized_scopes" in r.error


def test_security_allows_loopback(monkeypatch):
    monkeypatch.setattr(sec, "_cfg", lambda: {"lab_mode": True, "authorized_scopes": []})
    captured = {}
    monkeypatch.setattr(sec, "_run", lambda argv, t: captured.setdefault("argv", argv) or None)
    sec._port_scan({"target": "127.0.0.1", "profile": "quick"})
    assert captured["argv"][-1] == "127.0.0.1" and "-sT" in captured["argv"]


def test_security_authorizes_in_scope(monkeypatch):
    monkeypatch.setattr(sec, "_cfg",
                        lambda: {"lab_mode": True, "authorized_scopes": ["192.168.1.0/24"]})
    captured = {}
    monkeypatch.setattr(sec, "_run", lambda argv, t: captured.setdefault("argv", argv) or None)
    sec._port_scan({"target": "192.168.1.50"})
    assert "192.168.1.50" in captured["argv"]


def test_security_blocks_dangerous_flag():
    bad = sec._block_dangerous(["nmap", "--script", "vuln", "127.0.0.1"])
    assert bad and "script" in bad


def test_security_rejects_bad_ports(monkeypatch):
    monkeypatch.setattr(sec, "_cfg", lambda: {"lab_mode": True, "authorized_scopes": []})
    r = sec._port_scan({"target": "127.0.0.1", "ports": "80;evil"})
    assert not r.ok and "port spec" in r.error


def test_security_tools_destructive(reg):
    for name in ("port_scan", "ping_sweep", "dir_enum", "dns_enum"):
        assert reg.get(name).destructive is True
        assert is_destructive(name)
