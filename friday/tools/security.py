"""Security tools — authorized-scope-gated Kali wrappers (nmap / gobuster / dig).

Active scanning is powerful and easy to misuse, so these tools stay **off by
default** and are fenced by two independent gates:

  1. ``security.lab_mode: true`` must be set in ``friday/config.yaml``.
  2. The target must fall inside ``security.authorized_scopes`` (a list of
     CIDRs / IPs / hostnames you own) — loopback is always allowed.

The model picks a target and (for port scans) an optional port list; it never
constructs flags. argv is built from fixed templates and run with ``shell=False``
(no shell-injection surface). Dangerous flags are blocked defensively. All four
tools are ``destructive=True`` → approval-gated through the registry.

Self-contained: no dependency on the legacy ``core/`` or ``modules/`` trees.
"""
from __future__ import annotations

import ipaddress
import re
import shlex
import subprocess
import urllib.parse

from friday.config import load_config
from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult

# Flags that must never appear in a composed argv (NSE scripts, OS fingerprint,
# evasion, spoofing, shell metachars). Defense in depth — the templates below
# never emit these, but we re-check the final argv before exec.
_DANGEROUS = (
    re.compile(r"(?:^|\s)--script(?:-args)?(?:=|\s|$)", re.I),
    re.compile(r"(?:^|\s)-O\b", re.I),
    re.compile(r"(?:^|\s)-f\b", re.I),
    re.compile(r"(?:^|\s)--mtu(?:=|\s)", re.I),
    re.compile(r"(?:^|\s)-[DS]\s", re.I),
    re.compile(r"(?:^|\s)--source-port(?:=|\s)", re.I),
    re.compile(r"[;&|`$()<>]"),
)
_PORTS_RE = re.compile(r"^[0-9]{1,5}(?:[-,][0-9]{1,5})*$")
_TARGET_RE = re.compile(
    r"^(?:[0-9]{1,3}(?:\.[0-9]{1,3}){3}(?:/[0-9]{1,2})?"   # IPv4 / CIDR
    r"|[A-Fa-f0-9:]+(?:/[0-9]{1,3})?"                       # IPv6 / CIDR
    r"|[A-Za-z0-9][A-Za-z0-9\-\.]{0,253})$"                 # hostname
)

_NMAP_PROFILES = {
    "quick": ["-T4", "--top-ports", "100"],
    "standard": ["-T3", "--top-ports", "1000", "-sV", "--version-intensity", "2"],
    "deep": ["-T2", "-p-", "-sV", "--version-intensity", "3"],
}
_DEFAULT_WORDLIST = "/usr/share/wordlists/dirb/common.txt"


# ── config + scope ───────────────────────────────────────────────────────────

def _cfg() -> dict:
    try:
        return (load_config() or {}).get("security") or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug("[security] config load failed: %s", exc)
        return {}


def _enabled(cfg: dict) -> bool:
    return bool(cfg.get("lab_mode", False))


def _is_loopback(target: str) -> bool:
    try:
        return ipaddress.ip_network(target, strict=False).is_loopback
    except ValueError:
        return target.lower() in ("localhost", "localhost.localdomain")


def _authorized(target: str, scopes: list[str]) -> tuple[bool, str]:
    """Allow loopback always; otherwise the target must sit inside an
    authorized CIDR/IP, or exactly match an authorized hostname entry."""
    if not _TARGET_RE.match(target):
        return False, f"target {target!r} is not a valid IP/CIDR/hostname"
    if _is_loopback(target):
        return True, ""
    if not scopes:
        return False, "no security.authorized_scopes configured (loopback only)"
    try:
        tnet = ipaddress.ip_network(target, strict=False)
    except ValueError:
        tnet = None  # hostname target — fall back to exact match
    for s in scopes:
        if tnet is not None:
            try:
                if tnet.subnet_of(ipaddress.ip_network(s, strict=False)):
                    return True, ""
                continue
            except ValueError:
                pass
        if target.lower() == str(s).lower():
            return True, ""
    return False, f"target {target!r} is outside authorized_scopes"


def _block_dangerous(argv: list[str]) -> str | None:
    joined = " ".join(argv)
    for pat in _DANGEROUS:
        m = pat.search(joined)
        if m:
            return m.group(0).strip()
    return None


def _gate(target: str) -> tuple[dict, str]:
    """Return (cfg, error). error is '' when the target is authorized."""
    cfg = _cfg()
    if not _enabled(cfg):
        return cfg, "security tools are off — set security.lab_mode: true in config.yaml"
    ok, reason = _authorized(target, list(cfg.get("authorized_scopes") or []))
    return cfg, "" if ok else reason


def _run(argv: list[str], timeout: int) -> ToolResult:
    bad = _block_dangerous(argv)
    if bad:
        return ToolResult(ok=False, content="", error=f"refused (dangerous flag: {bad})")
    logger.info("[security] exec: %s", shlex.join(argv))
    try:
        proc = subprocess.run(argv, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        return ToolResult(ok=False, content="", error=f"{argv[0]!r} binary not found")
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, content="", error=f"timed out after {timeout}s")
    out = (proc.stdout or "").strip()
    if proc.stderr.strip():
        out += ("\n[stderr]\n" + proc.stderr.strip())
    out = out.strip()[:20_000] or "(no output)"
    return ToolResult(ok=proc.returncode == 0, content=out,
                      error="" if proc.returncode == 0 else f"{argv[0]} exit {proc.returncode}")


# ── handlers ─────────────────────────────────────────────────────────────────

def _port_scan(args: dict) -> ToolResult:
    target = (args.get("target") or "").strip()
    cfg, err = _gate(target)
    if err:
        return ToolResult(ok=False, content="", error=err)
    profile = args.get("profile", "quick")
    flags = list(_NMAP_PROFILES.get(profile, _NMAP_PROFILES["quick"]))
    ports = (args.get("ports") or "").strip()
    if ports:
        if not _PORTS_RE.match(ports):
            return ToolResult(ok=False, content="", error=f"invalid port spec {ports!r}")
        flags = [f for f in flags if f not in ("--top-ports", "-p-")]
        # drop the count token left dangling after --top-ports removal
        flags = [f for f in flags if not f.isdigit()] + ["-p", ports]
    argv = [cfg.get("nmap_binary") or "nmap", "-sT", "--open", *flags, target]
    return _run(argv, int(cfg.get("default_timeout_sec") or 120))


def _ping_sweep(args: dict) -> ToolResult:
    target = (args.get("subnet") or args.get("target") or "").strip()
    cfg, err = _gate(target)
    if err:
        return ToolResult(ok=False, content="", error=err)
    argv = [cfg.get("nmap_binary") or "nmap", "-sn", target]
    return _run(argv, int(cfg.get("default_timeout_sec") or 120))


def _dir_enum(args: dict) -> ToolResult:
    url = (args.get("url") or "").strip()
    host = urllib.parse.urlparse(url).hostname or ""
    if not host:
        return ToolResult(ok=False, content="", error="a full http(s) URL is required")
    cfg, err = _gate(host)
    if err:
        return ToolResult(ok=False, content="", error=err)
    wordlist = cfg.get("wordlist") or _DEFAULT_WORDLIST
    argv = [cfg.get("gobuster_binary") or "gobuster", "dir", "-q",
            "-u", url, "-w", wordlist]
    return _run(argv, int(cfg.get("default_timeout_sec") or 120))


def _dns_enum(args: dict) -> ToolResult:
    domain = (args.get("domain") or "").strip()
    cfg, err = _gate(domain)
    if err:
        return ToolResult(ok=False, content="", error=err)
    record = (args.get("record_type") or "ANY").upper()
    if record not in ("A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "ANY"):
        record = "ANY"
    argv = [cfg.get("dig_binary") or "dig", domain, record, "+noall", "+answer"]
    return _run(argv, int(cfg.get("dig_timeout_sec") or 30))


def register(registry: ToolRegistry) -> None:
    registry.register("port_scan",
        "Scan TCP ports/services on an authorized host (nmap). Requires lab_mode.", {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "IP or hostname inside authorized_scopes"},
                "profile": {"type": "string", "enum": ["quick", "standard", "deep"],
                            "description": "scan depth (default quick)"},
                "ports": {"type": "string", "description": "optional port spec e.g. '22,80,443' or '1-1024'"},
            },
            "required": ["target"],
        }, _port_scan, destructive=True)

    registry.register("ping_sweep",
        "Discover live hosts on an authorized subnet (nmap -sn). Requires lab_mode.", {
            "type": "object",
            "properties": {"subnet": {"type": "string", "description": "CIDR inside authorized_scopes, e.g. 192.168.1.0/24"}},
            "required": ["subnet"],
        }, _ping_sweep, destructive=True)

    registry.register("dir_enum",
        "Brute-force web directories on an authorized host (gobuster). Requires lab_mode.", {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "http(s) URL whose host is in authorized_scopes"}},
            "required": ["url"],
        }, _dir_enum, destructive=True)

    registry.register("dns_enum",
        "Enumerate DNS records for an authorized domain (dig). Requires lab_mode.", {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "domain in authorized_scopes"},
                "record_type": {"type": "string",
                                "enum": ["A", "AAAA", "MX", "NS", "TXT", "SOA", "CNAME", "ANY"]},
            },
            "required": ["domain"],
        }, _dns_enum, destructive=True)
