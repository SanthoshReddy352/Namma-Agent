"""MCP server config: validation, normalisation and import (Phase 5).

One server entry (``mcp.servers[]`` in user_config.yaml)::

    # stdio (a local process)
    {"name": "git", "command": ["uvx", "mcp-server-git"],
     "env": {"GITHUB_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"}, "cwd": "...",
     "enabled": true, "connect_timeout": 60, "call_timeout": 120}

    # Streamable HTTP (a remote server)
    {"name": "github", "transport": "http",
     "url": "https://api.githubcopilot.com/mcp/",
     "headers": {"Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}",
                 "X-MCP-Toolsets": "repos,issues"}}

``${NAME}`` in ``env`` / ``headers`` / ``url`` is resolved from the environment
(the vault is bridged into it) at connect time, so secrets never sit in the
config file. A literal secret is accepted but flagged with a warning.

:func:`import_servers` turns the other common formats into entries:
Claude Desktop / Cursor (``{"mcpServers": {name: {command, args, env}}}``),
VS Code (``{"servers": {name: {type, command|url, ...}}}``), the official MCP
registry ``server.json`` (``packages`` / ``remotes``), or our own list.
"""
from __future__ import annotations

import os
import re
import shlex
from typing import Any

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,39}$")
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
#: Literal values that look like real credentials (they belong in the vault).
_LITERAL_SECRET_RE = re.compile(
    r"^(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{30,}|Bearer\s+[A-Za-z0-9._-]{20,})$")
_KNOWN_KEYS = {"name", "command", "args", "env", "cwd", "enabled", "connect_timeout",
               "call_timeout", "transport", "url", "headers", "preset", "description"}
_TRANSPORTS = {"stdio", "http"}


def _issue(server: str, field: str, message: str) -> dict:
    return {"server": server, "field": field, "message": message}


def _str_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(k, str) and isinstance(v, (str, int, float, bool)) for k, v in value.items())


def _check_secretish(name: str, field: str, mapping: dict, warnings: list) -> None:
    for key, val in (mapping or {}).items():
        if isinstance(val, str) and _LITERAL_SECRET_RE.match(val.strip()):
            warnings.append(_issue(name, f"{field}.{key}",
                                   "looks like a literal secret — store it in the vault "
                                   f"and write ${{{key if field == 'env' else 'NAME'}}} here"))


def normalize_server(raw: dict) -> dict:
    """Fill defaults and fold ``args`` into ``command`` (Claude-Desktop style).
    Does not validate — see :func:`validate_servers`."""
    s = dict(raw or {})
    cmd = s.get("command")
    if isinstance(cmd, str):
        cmd = shlex.split(cmd, posix=os.name != "nt") if cmd.strip() else []
    if isinstance(cmd, list) and isinstance(s.get("args"), list):
        cmd = [*cmd, *[str(a) for a in s["args"]]]
    s.pop("args", None)
    if cmd is not None:
        s["command"] = cmd
    transport = (s.get("transport") or ("http" if s.get("url") and not cmd else "stdio"))
    s["transport"] = str(transport).lower().replace("streamable-http", "http").replace("sse", "http")
    s.setdefault("enabled", True)
    return s


def validate_servers(servers: Any) -> dict:
    """Validate a ``mcp.servers`` list. Returns
    ``{ok, servers (normalised), errors: [...], warnings: [...]}`` where each issue
    is ``{server, field, message}``. ``ok`` is False only for errors."""
    errors: list[dict] = []
    warnings: list[dict] = []
    if servers is None:
        servers = []
    if not isinstance(servers, list):
        return {"ok": False, "servers": [], "warnings": [],
                "errors": [_issue("", "servers", "must be a list of server objects")]}
    out: list[dict] = []
    seen: set[str] = set()
    for i, raw in enumerate(servers):
        if not isinstance(raw, dict):
            errors.append(_issue(f"#{i + 1}", "", "each server must be an object"))
            continue
        s = normalize_server(raw)
        name = str(s.get("name") or "")
        label = name or f"#{i + 1}"
        if not NAME_RE.match(name):
            errors.append(_issue(label, "name",
                                 "required: letters, digits, '_', '.', '-' (max 40, starts "
                                 "with a letter or digit)"))
        elif name.lower() in seen:
            errors.append(_issue(label, "name", "duplicate server name"))
        seen.add(name.lower())
        transport = s["transport"]
        if transport not in _TRANSPORTS:
            errors.append(_issue(label, "transport", "must be 'stdio' or 'http'"))
        elif transport == "stdio":
            cmd = s.get("command")
            if not (isinstance(cmd, list) and cmd and all(isinstance(c, str) and c for c in cmd)):
                errors.append(_issue(label, "command",
                                     "required for stdio: a non-empty list like "
                                     '["npx", "-y", "@scope/server"]'))
            if isinstance(raw.get("command"), str):
                warnings.append(_issue(label, "command",
                                       "was a string — split into an argument list"))
        else:
            url = str(s.get("url") or "")
            if not re.match(r"^https?://[^\s/]+", _VAR_RE.sub("x", url)):
                errors.append(_issue(label, "url", "required for http: an http(s):// URL"))
            elif url.startswith("http://") and not re.match(
                    r"^http://(localhost|127\.0\.0\.1|\[::1\])[:/]", url):
                warnings.append(_issue(label, "url",
                                       "plain http to a remote host — prefer https"))
        for field in ("env", "headers"):
            if field in s and s[field] is not None:
                if not _str_map(s[field]):
                    errors.append(_issue(label, field, "must be an object of string values"))
                else:
                    s[field] = {k: str(v) for k, v in s[field].items()}
                    _check_secretish(label, field, s[field], warnings)
        if s.get("cwd") is not None:
            if not isinstance(s["cwd"], str):
                errors.append(_issue(label, "cwd", "must be a string path"))
            elif s["cwd"] and not os.path.isdir(os.path.expanduser(s["cwd"])):
                warnings.append(_issue(label, "cwd", "folder does not exist"))
        if not isinstance(s.get("enabled"), bool):
            errors.append(_issue(label, "enabled", "must be true or false"))
        for field, hi in (("connect_timeout", 600), ("call_timeout", 3600)):
            if field in s and s[field] is not None:
                v = s[field]
                if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= hi:
                    errors.append(_issue(label, field, f"must be a whole number 1–{hi} (seconds)"))
        for key in sorted(set(s) - _KNOWN_KEYS):
            warnings.append(_issue(label, key, "unknown field (ignored)"))
        missing = sorted({m for v in _all_strings(s) for m in _VAR_RE.findall(v)}
                         - set(os.environ))
        for var in missing:
            warnings.append(_issue(label, "${" + var + "}",
                                   "not set — add it in Settings → Keys (the vault)"))
        out.append(s)
    return {"ok": not errors, "servers": out, "errors": errors, "warnings": warnings}


def _all_strings(s: dict) -> list[str]:
    vals = [str(s.get("url") or "")]
    for field in ("env", "headers"):
        vals += [str(v) for v in (s.get(field) or {}).values()] if isinstance(s.get(field), dict) else []
    vals += [c for c in (s.get("command") or []) if isinstance(c, str)]
    return vals


def expand_vars(value: str) -> str:
    """Resolve ``${NAME}`` from the environment (missing → empty string)."""
    return _VAR_RE.sub(lambda m: os.environ.get(m.group(1), ""), value or "")


def resolved(server: dict) -> dict:
    """A copy with ``${NAME}`` expanded in url / env / headers / command — used only
    at connect time, never persisted or shown."""
    s = dict(server)
    if s.get("url"):
        s["url"] = expand_vars(s["url"])
    for field in ("env", "headers"):
        if isinstance(s.get(field), dict):
            s[field] = {k: expand_vars(str(v)) for k, v in s[field].items()}
    if isinstance(s.get("command"), list):
        s["command"] = [expand_vars(c) if "${" in c else c for c in s["command"]]
    return s


# ── import from other formats ───────────────────────────────────────────────

def _from_registry_server_json(obj: dict) -> list[dict]:
    """The official MCP registry ``server.json``: packages (npm / pypi / oci) and
    remotes (streamable-http)."""
    base = re.sub(r"[^A-Za-z0-9_.-]", "-", str(obj.get("name") or "server").split("/")[-1])[:40]
    out: list[dict] = []
    for pkg in obj.get("packages") or []:
        if not isinstance(pkg, dict):
            continue
        kind = str(pkg.get("registry_type") or pkg.get("registryType") or "").lower()
        ident = str(pkg.get("identifier") or pkg.get("name") or "")
        if not ident:
            continue
        version = str(pkg.get("version") or "")
        if kind == "npm":
            cmd = ["npx", "-y", f"{ident}@{version}" if version else ident]
        elif kind == "pypi":
            cmd = ["uvx", f"{ident}=={version}" if version else ident]
        elif kind in ("oci", "docker"):
            cmd = ["docker", "run", "-i", "--rm", f"{ident}:{version}" if version else ident]
        else:
            continue
        env = {}
        for var in pkg.get("environment_variables") or pkg.get("environmentVariables") or []:
            if isinstance(var, dict) and var.get("name"):
                env[var["name"]] = "${" + var["name"] + "}"
        entry = {"name": base, "command": cmd}
        if env:
            entry["env"] = env
        out.append(entry)
        break                                   # one local package is enough
    for remote in obj.get("remotes") or []:
        if isinstance(remote, dict) and remote.get("url"):
            out.append({"name": f"{base}-remote" if out else base,
                        "transport": "http", "url": remote["url"]})
            break
    return out


def import_servers(obj: Any) -> dict:
    """Turn a pasted/fetched config in any common format into server entries.
    Returns the same shape as :func:`validate_servers` plus ``format``."""
    fmt, servers = "unknown", []
    if isinstance(obj, list):
        fmt, servers = "namma", obj
    elif isinstance(obj, dict):
        if isinstance(obj.get("mcp"), dict):
            obj = obj["mcp"]
        named = obj.get("mcpServers") if isinstance(obj.get("mcpServers"), dict) else None
        if named is None and isinstance(obj.get("servers"), dict):
            named = obj["servers"]
            fmt = "vscode"
        elif named is not None:
            fmt = "claude-desktop"
        if named is not None:
            for name, spec in named.items():
                if not isinstance(spec, dict):
                    continue
                entry = {"name": re.sub(r"[^A-Za-z0-9_.-]", "-", str(name))[:40], **spec}
                if str(spec.get("type", "")).lower() in ("http", "sse", "streamable-http"):
                    entry["transport"] = "http"
                entry.pop("type", None)
                if entry.pop("disabled", None):          # Claude Desktop's off switch
                    entry["enabled"] = False
                servers.append(entry)
        elif isinstance(obj.get("servers"), list):
            fmt, servers = "namma", obj["servers"]
        elif obj.get("packages") or obj.get("remotes"):
            fmt, servers = "mcp-registry", _from_registry_server_json(obj)
        elif obj.get("command") or obj.get("url"):
            fmt, servers = "single", [obj]
    result = validate_servers(servers)
    if fmt == "unknown":
        result["ok"] = False
        result["errors"].insert(0, _issue("", "", "no MCP servers found — expected "
                                          "mcpServers, servers, or a server.json"))
    result["format"] = fmt
    return result


def merge_servers(existing: list[dict], new: list[dict], replace: bool = False) -> list[dict]:
    """Add ``new`` entries to ``existing`` by name (a same-name entry is replaced
    only when ``replace``)."""
    by_name = {str(s.get("name", "")).lower(): i for i, s in enumerate(existing)}
    merged = [dict(s) for s in existing]
    for s in new:
        key = str(s.get("name", "")).lower()
        if key in by_name:
            if replace:
                merged[by_name[key]] = dict(s)
        else:
            by_name[key] = len(merged)
            merged.append(dict(s))
    return merged
