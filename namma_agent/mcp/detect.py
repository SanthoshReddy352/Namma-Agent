"""Detect what MCP servers this machine can run, and ones it already has (Phase 5).

* **Runtimes** — node/npx (npm servers), uv/uvx (PyPI servers), Docker (image
  servers; the CLI AND a running daemon), python.
* **Disk** — free space where packages and images land; Docker images and npx
  caches are large, so a nearly-full disk is the usual silent install failure.
* **Already configured elsewhere** — servers in Claude Desktop, Cursor, VS Code
  or Windsurf configs, offered for one-click import (nothing is read beyond
  those config files, and secrets in them are shown masked).
* **Docker MCP images** — local images under ``mcp/`` (Docker's MCP catalog).
* **Per configured server** — is its launcher on PATH?

Every probe is bounded (short timeouts) and best-effort: detection never raises.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from namma_agent.mcp.config import import_servers

#: Below this much free space, image/npx installs are likely to fail.
LOW_DISK_BYTES = 2 * 1024 ** 3

_RUNTIMES = {
    "node": {"bins": ["node"], "for": "npm servers (npx)", "install": "https://nodejs.org"},
    "npx": {"bins": ["npx"], "for": "npm servers", "install": "comes with Node.js"},
    "uvx": {"bins": ["uvx"], "for": "PyPI servers",
            "install": "https://docs.astral.sh/uv/getting-started/installation/"},
    "docker": {"bins": ["docker"], "for": "Docker image servers",
               "install": "https://docs.docker.com/get-docker/"},
    "python": {"bins": ["python3", "python"], "for": "Python servers",
               "install": "https://python.org"},
}


def _which(names: list[str]) -> str:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return ""


def _run(cmd: list[str], timeout: float = 6.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)
        return proc.returncode, (proc.stdout or proc.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return -1, str(exc)


def runtimes(check_versions: bool = True) -> dict:
    out: dict = {}
    for key, spec in _RUNTIMES.items():
        path = _which(spec["bins"])
        item = {"found": bool(path), "path": path, "for": spec["for"], "install": spec["install"]}
        if path and check_versions and key in ("node", "uvx", "python"):
            code, text = _run([path, "--version"], 5)
            if code == 0:
                item["version"] = text.splitlines()[0][:40] if text else ""
        out[key] = item
    if out["docker"]["found"]:
        code, text = _run([out["docker"]["path"], "info", "--format", "{{.ServerVersion}}"], 8)
        out["docker"]["daemon"] = code == 0 and bool(text)
        if code == 0:
            out["docker"]["version"] = text[:40]
        else:
            out["docker"]["hint"] = "Docker is installed but its engine isn't running — start Docker Desktop"
    return out


def disk(paths: Optional[list[str]] = None) -> list[dict]:
    """Free space on the drives that matter (data dir + home), de-duplicated."""
    from namma_agent.config import data_dir

    seen: set = set()
    out = []
    for p in paths or [str(data_dir()), str(Path.home())]:
        try:
            usage = shutil.disk_usage(p)
        except OSError:
            continue
        anchor = Path(p).anchor or p
        if anchor in seen:
            continue
        seen.add(anchor)
        out.append({"path": anchor, "free_bytes": usage.free, "total_bytes": usage.total,
                    "low": usage.free < LOW_DISK_BYTES})
    return out


def _client_config_paths() -> list[tuple[str, Path]]:
    home = Path.home()
    appdata = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
    system = platform.system()
    if system == "Windows":
        claude = appdata / "Claude" / "claude_desktop_config.json"
        vscode = appdata / "Code" / "User" / "mcp.json"
    elif system == "Darwin":
        claude = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
        vscode = home / "Library" / "Application Support" / "Code" / "User" / "mcp.json"
    else:
        claude = home / ".config" / "Claude" / "claude_desktop_config.json"
        vscode = home / ".config" / "Code" / "User" / "mcp.json"
    return [("Claude Desktop", claude), ("Cursor", home / ".cursor" / "mcp.json"),
            ("VS Code", vscode), ("Windsurf", home / ".codeium" / "windsurf" / "mcp_config.json")]


def _mask(server: dict) -> dict:
    """A display copy with env/header values masked (they often hold tokens)."""
    s = dict(server)
    for field in ("env", "headers"):
        if isinstance(s.get(field), dict):
            s[field] = {k: (v if str(v).startswith("${") else "••••") for k, v in s[field].items()}
    return s


def importable(paths: Optional[list[tuple[str, Path]]] = None) -> list[dict]:
    """Servers configured in other MCP clients on this machine."""
    found = []
    for source, path in paths or _client_config_paths():
        try:
            if not path.is_file() or path.stat().st_size > 1_000_000:
                continue
            obj = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        result = import_servers(obj)
        for s in result["servers"]:
            found.append({"source": source, "path": str(path), "server": _mask(s),
                          "valid": not any(e["server"] == s.get("name") for e in result["errors"])})
    return found


def docker_mcp_images(docker_path: str = "") -> list[dict]:
    """Local images from Docker's MCP catalog (``mcp/<name>``)."""
    docker = docker_path or shutil.which("docker")
    if not docker:
        return []
    code, text = _run([docker, "images", "--filter", "reference=mcp/*",
                       "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}"], 8)
    if code != 0 or not text:
        return []
    out = []
    for line in text.splitlines():
        image, _, size = line.partition("\t")
        if not image or image.endswith(":<none>"):
            continue
        name = image.split("/", 1)[-1].split(":", 1)[0]
        out.append({"image": image, "size": size,
                    "server": {"name": f"docker-{name}"[:40],
                               "command": ["docker", "run", "-i", "--rm", image]}})
    return out


def server_launchers(servers: list[dict]) -> dict:
    """``{server name: {launcher, found, hint}}`` for configured stdio servers."""
    out = {}
    for s in servers or []:
        if not isinstance(s, dict):
            continue
        cmd = s.get("command") if isinstance(s.get("command"), list) else []
        if (s.get("transport") == "http") or not cmd:
            continue
        exe = str(cmd[0])
        found = bool(os.path.isabs(exe) and os.path.exists(exe)) or bool(_which([exe]))
        hint = ""
        if not found:
            base = os.path.basename(exe).lower().split(".")[0]
            spec = _RUNTIMES.get(base) or (_RUNTIMES["node"] if base == "npx" else None)
            hint = f"install {base}: {spec['install']}" if spec else f"'{exe}' is not on PATH"
        out[s.get("name") or exe] = {"launcher": exe, "found": found, "hint": hint}
    return out


def detect(configured: Optional[list[dict]] = None) -> dict:
    rt = runtimes()
    return {
        "runtimes": rt,
        "disk": disk(),
        "importable": importable(),
        "docker_images": docker_mcp_images(rt["docker"]["path"]) if rt["docker"].get("daemon") else [],
        "launchers": server_launchers(configured or []),
    }
