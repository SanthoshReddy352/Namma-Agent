"""Network tools — read-only host/connectivity probes. Cross-platform, stdlib.

  ping_host   — ICMP reachability + round-trip (uses the OS `ping` binary)
  dns_lookup  — resolve a hostname to its A/AAAA addresses
  check_port  — TCP connect test to host:port
  public_ip   — this machine's public IP (via a keyless echo service)

These are diagnostics, not attacks — no scope gating (see security.py for active
scanning). All are bounded by short timeouts.
"""
from __future__ import annotations

import platform
import socket
import subprocess
import urllib.request

from friday.core.tools import ToolRegistry, ToolResult

_HOST_RE_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:")


def _valid_host(host: str) -> bool:
    return bool(host) and len(host) <= 253 and set(host) <= _HOST_RE_OK


def _ping(args: dict) -> ToolResult:
    host = (args.get("host") or "").strip()
    if not _valid_host(host):
        return ToolResult(ok=False, content="", error="invalid host")
    count = str(max(1, min(int(args.get("count", 3)), 10)))
    flag = "-n" if platform.system() == "Windows" else "-c"
    try:
        proc = subprocess.run(
            ["ping", flag, count, host],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20,
        )
    except FileNotFoundError:
        return ToolResult(ok=False, content="", error="ping binary not found")
    except subprocess.TimeoutExpired:
        return ToolResult(ok=False, content="", error="ping timed out")
    out = (proc.stdout or proc.stderr or "").strip()[:4000]
    return ToolResult(ok=proc.returncode == 0, content=out or "(no output)",
                      error="" if proc.returncode == 0 else f"host unreachable: {host}")


def _dns_lookup(args: dict) -> ToolResult:
    host = (args.get("host") or "").strip()
    if not _valid_host(host):
        return ToolResult(ok=False, content="", error="invalid host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return ToolResult(ok=False, content="", error=f"could not resolve {host}: {exc}")
    addrs = sorted({info[4][0] for info in infos})
    return ToolResult(ok=True, content=f"{host} resolves to:\n" + "\n".join(addrs),
                      data={"host": host, "addresses": addrs})


def _check_port(args: dict) -> ToolResult:
    host = (args.get("host") or "").strip()
    if not _valid_host(host):
        return ToolResult(ok=False, content="", error="invalid host")
    try:
        port = int(args.get("port"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="a numeric port is required")
    if not (1 <= port <= 65535):
        return ToolResult(ok=False, content="", error="port out of range 1..65535")
    timeout = max(1.0, min(float(args.get("timeout", 3)), 10.0))
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return ToolResult(ok=True, content=f"{host}:{port} is open",
                              data={"host": host, "port": port, "open": True})
    except (socket.timeout, OSError) as exc:
        return ToolResult(ok=True, content=f"{host}:{port} is closed/filtered ({exc})",
                          data={"host": host, "port": port, "open": False})


def _public_ip(_args: dict) -> ToolResult:
    for url in ("https://api.ipify.org", "https://ifconfig.me/ip", "https://icanhazip.com"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "friday/2"})
            with urllib.request.urlopen(req, timeout=6) as resp:  # noqa: S310
                ip = resp.read(64).decode("utf-8", errors="replace").strip()
            if ip:
                return ToolResult(ok=True, content=f"Public IP: {ip}", data={"ip": ip})
        except Exception:  # noqa: BLE001
            continue
    return ToolResult(ok=False, content="", error="could not determine public IP")


def register(registry: ToolRegistry) -> None:
    registry.register("ping_host", "Ping a host to check reachability and latency.", {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "hostname or IP"},
            "count": {"type": "integer", "description": "echo requests (1-10, default 3)"},
        },
        "required": ["host"],
    }, _ping)

    registry.register("dns_lookup", "Resolve a hostname to its IP addresses.", {
        "type": "object",
        "properties": {"host": {"type": "string", "description": "hostname to resolve"}},
        "required": ["host"],
    }, _dns_lookup)

    registry.register("check_port", "Test whether a TCP port is open on a host.", {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "hostname or IP"},
            "port": {"type": "integer", "description": "TCP port (1-65535)"},
            "timeout": {"type": "number", "description": "seconds (1-10, default 3)"},
        },
        "required": ["host", "port"],
    }, _check_port)

    registry.register("public_ip", "Get this machine's public IP address.", {
        "type": "object", "properties": {},
    }, _public_ip)
