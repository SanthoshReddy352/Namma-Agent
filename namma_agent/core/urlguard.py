"""SSRF guard for URL-fetching tools (Phase 7a) — stdlib only.

Every tool that fetches a URL the *model* chose (``web_extract``, ``web_crawl``,
the ``web_search`` HTML fallback, ``get_news``) is a confused-deputy risk: the
agent runs on the user's machine, inside their network, and — since Phase 6 —
often on a cloud box with an instance-metadata service one HTTP request away.
An untrusted Slack/WhatsApp sender (Phase 1a) can reach those tools, because
fetching a page is not *destructive* and so is never stripped from their turn.

The guard refuses, before any socket is opened:

* non-``http(s)`` schemes (``file://``, ``gopher://``, ``ftp://`` …);
* URLs whose host **resolves** into loopback, private, link-local, CGNAT,
  reserved, or multicast space — the check is on the resolved addresses, not the
  literal text, because ``http://internal.example.com/`` resolving to 10.0.0.5
  is the actual attack. **Every** address the name resolves to must be public,
  so a round-robin record mixing one private answer in cannot slip through;
* the cloud metadata endpoints specifically (169.254.169.254 and friends fall
  out of link-local, but they get their own reason string because that is the
  credential-theft case people actually mean);
* IPv4-mapped / 6to4 / NAT64 IPv6 forms that smuggle a private v4 address inside
  a v6 literal (``::ffff:127.0.0.1``);
* redirects into any of the above — :func:`guarded_opener` re-checks each hop,
  since the first URL being public says nothing about where it forwards to.

**Honest limits.** This is not TOCTOU-proof: between our ``getaddrinfo`` and
urllib's own connect, a hostile resolver could answer differently (classic DNS
rebinding). Closing that needs pinning the checked IP and connecting to it
directly with a ``Host`` header, which means owning the HTTP stack. What is here
blocks the attack *class* — model- or sender-supplied URLs reaching internal
services — which is the realistic threat for a personal agent.

Home-lab users who legitimately want the agent to reach their own NAS or router
set ``security.allow_private_urls: true``. It is off by default: reaching into
the private network has to be a deliberate choice, not an omission.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from namma_agent.core.logger import logger

ALLOWED_SCHEMES = ("http", "https")

#: Ranges ``ipaddress``'s own predicates miss or don't classify the way we need.
_EXTRA_BLOCKED = (
    ipaddress.ip_network("100.64.0.0/10"),   # CGNAT (shared address space)
    ipaddress.ip_network("192.0.0.0/24"),    # IETF protocol assignments
    ipaddress.ip_network("64:ff9b::/96"),    # NAT64 — wraps a v4 address
)

#: Cloud instance-metadata addresses. These are inside link-local already; they
#: are called out so the refusal message names the real risk.
_METADATA_ADDRESSES = frozenset({
    "169.254.169.254",   # AWS / Azure / GCP / DigitalOcean / OpenStack
    "169.254.170.2",     # AWS ECS task metadata
    "fd00:ec2::254",     # AWS IMDSv2 over IPv6
    "100.100.100.200",   # Alibaba Cloud
})


class BlockedURL(Exception):
    """A URL was refused by the guard. The message is user/model-facing."""


# ── module state (service-configured at boot, same pattern as core.sandbox) ──

_ALLOW_PRIVATE = False


def configure_urlguard(security_cfg: Optional[dict] = None) -> bool:
    """Install ``security.allow_private_urls`` from ``config['security']``
    (service boot). Returns the effective setting."""
    global _ALLOW_PRIVATE
    _ALLOW_PRIVATE = bool((security_cfg or {}).get("allow_private_urls", False))
    if _ALLOW_PRIVATE:
        logger.warning(
            "[urlguard] security.allow_private_urls is ON — tools may fetch "
            "private/loopback addresses. Only do this on a network you trust.")
    return _ALLOW_PRIVATE


def allow_private() -> bool:
    return _ALLOW_PRIVATE


def status() -> dict:
    """Posture row for the Security tab / ``background_status()``."""
    return {
        "enabled": not _ALLOW_PRIVATE,
        "allow_private_urls": _ALLOW_PRIVATE,
        "schemes": list(ALLOWED_SCHEMES),
    }


# ── address classification ───────────────────────────────────────────────────

def _unwrap(ip: ipaddress._BaseAddress) -> ipaddress._BaseAddress:
    """Reduce a v6 address that merely wraps a v4 one to that v4 address, so
    ``::ffff:127.0.0.1`` is judged as 127.0.0.1 rather than as a public v6."""
    if isinstance(ip, ipaddress.IPv6Address):
        for wrapped in (ip.ipv4_mapped, ip.sixtofour):
            if wrapped is not None:
                return wrapped
        if ip in ipaddress.ip_network("64:ff9b::/96"):
            # NAT64: the low 32 bits carry the v4 address.
            return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return ip


def address_block_reason(raw: str) -> str:
    """Why this IP may not be fetched, or "" when it is fine."""
    try:
        ip = _unwrap(ipaddress.ip_address(raw))
    except ValueError:
        return "not a valid IP address"

    # Order matters only for the WORDING — several of these overlap (0.0.0.0 is
    # both unspecified and inside 0.0.0.0/8, which ipaddress calls private).
    # Most specific first so the reason names the real thing.
    if str(ip) in _METADATA_ADDRESSES:
        return "the cloud instance-metadata service (credential theft risk)"
    if ip.is_unspecified:
        return "an unspecified address"
    if ip.is_loopback:
        return "a loopback address"
    if ip.is_link_local:
        return "a link-local address"
    if ip.is_multicast:
        return "a multicast address"
    if ip.is_private:
        return "a private network address"
    if ip.is_reserved:
        return "a reserved address"
    for net in _EXTRA_BLOCKED:
        if ip.version == net.version and ip in net:
            return f"inside the blocked range {net}"
    return ""


def _resolve(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise BlockedURL(f"could not resolve {host!r}: {exc}") from exc
    return sorted({info[4][0].split("%")[0] for info in infos})


# ── the public check ─────────────────────────────────────────────────────────

def check_url(url: str, *, allow_private: Optional[bool] = None) -> str:
    """Validate a URL for tool fetching. Returns the normalized URL.

    Raises :class:`BlockedURL` with a plain-language reason when the scheme is
    not http(s) or any resolved address is non-public. ``allow_private``
    overrides the configured setting (tests, and callers that have their own
    policy); ``None`` means "use the configured value".
    """
    url = (url or "").strip()
    if not url:
        raise BlockedURL("no URL given")

    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise BlockedURL(
            f"refusing to fetch {url[:120]!r}: only "
            f"{'/'.join(ALLOWED_SCHEMES)} URLs are allowed, not {scheme or 'a relative URL'}")

    host = parsed.hostname
    if not host:
        raise BlockedURL(f"refusing to fetch {url[:120]!r}: no host in the URL")

    if allow_private is None:
        allow_private = _ALLOW_PRIVATE
    if allow_private:
        return url

    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:  # malformed port
        raise BlockedURL(f"refusing to fetch {url[:120]!r}: bad port ({exc})") from exc

    for addr in _resolve(host, port):
        reason = address_block_reason(addr)
        if reason:
            raise BlockedURL(
                f"refusing to fetch {url[:120]!r}: {host} resolves to {addr}, "
                f"which is {reason}. If this is your own device on a network you "
                f"trust, set security.allow_private_urls: true in config.")
    return url


def is_blocked(url: str, *, allow_private: Optional[bool] = None) -> str:
    """Non-raising form: the refusal reason, or "" when the URL is fetchable."""
    try:
        check_url(url, allow_private=allow_private)
    except BlockedURL as exc:
        return str(exc)
    return ""


# ── redirect-aware opener ────────────────────────────────────────────────────

class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-runs :func:`check_url` on every redirect target. A public URL that
    302s to ``http://169.254.169.254/`` is the standard SSRF bypass, so the
    first hop passing the check proves nothing about the rest."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        reason = is_blocked(newurl)
        if reason:
            raise urllib.error.HTTPError(newurl, code, reason, headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def guarded_opener() -> urllib.request.OpenerDirector:
    """An opener that enforces the guard across redirects. Callers still check
    the *initial* URL with :func:`check_url` — this covers the hops after it."""
    return urllib.request.build_opener(_GuardedRedirectHandler)


def urlopen(url: str, *, timeout: int = 10, headers: Optional[dict] = None,
            allow_private: Optional[bool] = None):
    """``urllib.request.urlopen`` with the guard applied to the initial URL and
    to every redirect. Raises :class:`BlockedURL` before opening any socket."""
    checked = check_url(url, allow_private=allow_private)
    req = urllib.request.Request(checked, headers=headers or {})
    return guarded_opener().open(req, timeout=timeout)
