"""Phase 7a — SSRF guard for URL-fetching tools (core/urlguard.py).

Everything here is offline: DNS is faked with a stub ``getaddrinfo`` so the
suite never touches the network and the "hostname resolves into private space"
cases (the actual attack) are exercised deterministically.
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.request

import pytest

from namma_agent.core import urlguard as ug


@pytest.fixture(autouse=True)
def _reset_module_state():
    ug.configure_urlguard(None)
    yield
    ug.configure_urlguard(None)


@pytest.fixture
def resolves(monkeypatch):
    """Point every hostname at the given addresses (no real DNS)."""
    def _install(mapping: dict[str, list[str]]):
        def fake_getaddrinfo(host, port, *a, **kw):
            try:
                addrs = mapping[host]
            except KeyError:
                raise socket.gaierror(f"unknown test host {host!r}") from None
            out = []
            for addr in addrs:
                fam = socket.AF_INET6 if ":" in addr else socket.AF_INET
                out.append((fam, socket.SOCK_STREAM, socket.IPPROTO_TCP, "",
                            (addr, port or 80)))
            return out
        monkeypatch.setattr(ug.socket, "getaddrinfo", fake_getaddrinfo)
    return _install


# ── address classification ───────────────────────────────────────────────────

@pytest.mark.parametrize("addr, fragment", [
    ("127.0.0.1", "loopback"),
    ("::1", "loopback"),
    ("10.1.2.3", "private"),
    ("192.168.1.10", "private"),
    ("172.16.0.1", "private"),
    ("169.254.1.1", "link-local"),
    ("169.254.169.254", "metadata"),
    ("100.100.100.200", "metadata"),        # Alibaba
    ("100.64.0.1", "blocked range"),        # CGNAT
    ("224.0.0.1", "multicast"),
    ("0.0.0.0", "unspecified"),
    ("fd00::1", "private"),                 # IPv6 unique-local
    ("fe80::1", "link-local"),
])
def test_blocked_addresses(addr, fragment):
    reason = ug.address_block_reason(addr)
    assert reason, f"{addr} should be blocked"
    assert fragment in reason


@pytest.mark.parametrize("addr", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:4700::1111"])
def test_public_addresses_allowed(addr):
    assert ug.address_block_reason(addr) == ""


def test_ipv4_mapped_ipv6_is_unwrapped():
    """``::ffff:127.0.0.1`` is a loopback address wearing a v6 costume — the
    naive check (IPv6Address.is_loopback) says False."""
    assert "loopback" in ug.address_block_reason("::ffff:127.0.0.1")
    assert "private" in ug.address_block_reason("::ffff:10.0.0.1")


def test_nat64_and_sixtofour_are_unwrapped():
    assert ug.address_block_reason("64:ff9b::7f00:1")      # 127.0.0.1
    assert ug.address_block_reason("2002:0a00:0001::1")    # 6to4 wrapping 10.0.0.1


# ── scheme handling ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///etc/passwd",
    "gopher://evil.example/_",
    "ftp://example.com/x",
    "/relative/path",
])
def test_non_http_schemes_refused(url):
    with pytest.raises(ug.BlockedURL) as exc:
        ug.check_url(url)
    assert "only http/https" in str(exc.value)


def test_empty_url_refused():
    with pytest.raises(ug.BlockedURL):
        ug.check_url("")


def test_missing_host_refused():
    with pytest.raises(ug.BlockedURL) as exc:
        ug.check_url("http:///nohost")
    assert "no host" in str(exc.value)


# ── the resolution check (the real attack) ───────────────────────────────────

def test_public_hostname_passes(resolves):
    resolves({"example.com": ["93.184.216.34"]})
    assert ug.check_url("https://example.com/page") == "https://example.com/page"


def test_hostname_resolving_private_is_refused(resolves):
    """The attack: a perfectly public-looking name with a private A record."""
    resolves({"internal.example.com": ["10.0.0.5"]})
    with pytest.raises(ug.BlockedURL) as exc:
        ug.check_url("https://internal.example.com/admin")
    assert "10.0.0.5" in str(exc.value)
    assert "private" in str(exc.value)


def test_metadata_endpoint_refused_by_literal(resolves):
    resolves({"169.254.169.254": ["169.254.169.254"]})
    with pytest.raises(ug.BlockedURL) as exc:
        ug.check_url("http://169.254.169.254/latest/meta-data/iam/security-credentials/")
    assert "metadata" in str(exc.value)


def test_any_private_answer_blocks_the_whole_name(resolves):
    """A round-robin record mixing one private answer among public ones must
    not be fetchable — urllib could connect to any of them."""
    resolves({"mixed.example.com": ["93.184.216.34", "127.0.0.1"]})
    with pytest.raises(ug.BlockedURL):
        ug.check_url("http://mixed.example.com/")


def test_unresolvable_host_refused(resolves):
    resolves({})
    with pytest.raises(ug.BlockedURL) as exc:
        ug.check_url("http://nope.invalid/")
    assert "could not resolve" in str(exc.value)


def test_refusal_message_names_the_escape_hatch(resolves):
    resolves({"nas.local": ["192.168.1.50"]})
    with pytest.raises(ug.BlockedURL) as exc:
        ug.check_url("http://nas.local/")
    assert "allow_private_urls" in str(exc.value)


# ── the opt-out ──────────────────────────────────────────────────────────────

def test_allow_private_urls_config_lets_private_through(resolves):
    resolves({"nas.local": ["192.168.1.50"]})
    ug.configure_urlguard({"allow_private_urls": True})
    assert ug.allow_private() is True
    assert ug.check_url("http://nas.local/") == "http://nas.local/"


def test_allow_private_argument_overrides_config(resolves):
    resolves({"nas.local": ["192.168.1.50"]})
    assert ug.check_url("http://nas.local/", allow_private=True)
    with pytest.raises(ug.BlockedURL):
        ug.check_url("http://nas.local/", allow_private=False)


def test_opt_out_still_refuses_non_http_schemes():
    """allow_private_urls widens the ADDRESS policy, not the scheme policy —
    file:// was never about the network."""
    ug.configure_urlguard({"allow_private_urls": True})
    with pytest.raises(ug.BlockedURL):
        ug.check_url("file:///etc/passwd")


def test_default_is_guarded():
    ug.configure_urlguard(None)
    assert ug.allow_private() is False
    assert ug.status()["enabled"] is True


def test_is_blocked_is_the_nonraising_form(resolves):
    resolves({"example.com": ["93.184.216.34"], "internal": ["10.0.0.5"]})
    assert ug.is_blocked("https://example.com/") == ""
    assert "private" in ug.is_blocked("http://internal/")


# ── redirect hops ────────────────────────────────────────────────────────────

def test_redirect_into_private_space_is_refused(resolves):
    """A public URL that 302s to the metadata service is the standard bypass."""
    resolves({"example.com": ["93.184.216.34"]})
    handler = ug._GuardedRedirectHandler()
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(
            _FakeRequest(), None, 302, "Found", {},
            "http://169.254.169.254/latest/meta-data/")


def test_redirect_to_public_is_allowed(resolves, monkeypatch):
    resolves({"example.com": ["93.184.216.34"], "other.example": ["8.8.8.8"]})
    handler = ug._GuardedRedirectHandler()
    called = {}

    def fake_super(self, req, fp, code, msg, headers, newurl):
        called["url"] = newurl
        return "redirected"

    monkeypatch.setattr(urllib.request.HTTPRedirectHandler, "redirect_request", fake_super)
    out = handler.redirect_request(_FakeRequest(), None, 302, "Found", {},
                                   "https://other.example/next")
    assert out == "redirected"
    assert called["url"] == "https://other.example/next"


class _FakeRequest:
    full_url = "https://example.com/"

    def get_full_url(self):
        return self.full_url


# ── tool wiring (the point of the whole module) ──────────────────────────────

def test_web_extract_refuses_metadata_endpoint(resolves):
    """The exact scenario: an untrusted Slack sender asks the agent to read the
    instance-metadata service. web_extract is not 'destructive', so Phase 1a
    does not strip it — this guard is what stops it."""
    from namma_agent.tools import web
    resolves({"169.254.169.254": ["169.254.169.254"]})
    result = web._extract({"url": "http://169.254.169.254/latest/meta-data/"})
    assert result.ok is False
    assert "metadata" in result.error
    assert "refusing to fetch" in result.error


def test_web_extract_refuses_private_hostname(resolves):
    from namma_agent.tools import web
    resolves({"router.lan": ["192.168.0.1"]})
    result = web._extract({"url": "http://router.lan/admin"})
    assert result.ok is False and "private" in result.error


def test_web_crawl_refuses_private_seed(resolves):
    from namma_agent.tools import web
    resolves({"internal.corp": ["10.0.0.9"]})
    result = web._crawl({"url": "http://internal.corp/"})
    assert result.ok is False and "private" in result.error


def test_web_extract_still_fetches_public_pages(resolves, monkeypatch):
    """The guard must be invisible on the happy path."""
    from namma_agent.tools import web
    resolves({"example.com": ["93.184.216.34"]})

    class _Resp:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self, _n=None):
            return b"<html><body><p>Hello world</p></body></html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    # web.py imported the symbol by name, so patch it there (patching urlguard
    # would leave web's own reference bound to the real opener).
    monkeypatch.setattr(web, "guarded_opener",
                        lambda: type("O", (), {"open": lambda self, r, timeout=0: _Resp()})())
    result = web._extract({"url": "https://example.com/page"})
    assert result.ok is True and "Hello world" in result.content


def test_learning_media_guards_the_downloaded_image_url():
    """img_url comes from the Openverse response — remote data picking a fetch
    target. Verify the module routes it through the guard rather than urlopen."""
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "tools" / "learning_media.py"
    text = src.read_text(encoding="utf-8")
    assert "urlguard.check_url(img_url)" in text
    assert "urlguard.guarded_opener()" in text
