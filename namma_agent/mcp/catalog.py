"""Curated MCP server catalogue + install-from-URL (Phase 5).

A *preset* is a well-known server with a small form: ``params`` the user fills
in (folders, a repo path, GitHub toolsets …) and ``secrets`` that go to the
vault and are referenced as ``${ENV_NAME}`` — never written into the config.
:func:`build_from_preset` turns a preset + answers into a validated server entry.

This is deliberately a short, curated list (the old "marketplace" decline still
stands for an open ecosystem); anything else installs from a URL or a pasted
config via :func:`fetch_config` / :mod:`namma_agent.mcp.config`.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from namma_agent.mcp.config import import_servers, validate_servers

#: GitHub MCP toolsets (github/github-mcp-server). "default" = the server's own set.
GITHUB_TOOLSETS = ["context", "repos", "issues", "pull_requests", "users", "actions",
                   "code_security", "dependabot", "discussions", "gists", "notifications",
                   "orgs", "projects", "secret_protection", "security_advisories",
                   "stargazers", "experiments"]
GITHUB_DEFAULT_TOOLSETS = ["context", "repos", "issues", "pull_requests", "users"]

_GH_TOKEN = {"env": "GITHUB_PERSONAL_ACCESS_TOKEN", "label": "GitHub personal access token",
             "url": "https://github.com/settings/personal-access-tokens/new",
             "help": "Fine-grained token; grant only the repositories and scopes you need.",
             "required": True}
_GH_PARAMS = [
    {"key": "toolsets", "label": "Toolsets", "type": "multi", "options": GITHUB_TOOLSETS,
     "default": GITHUB_DEFAULT_TOOLSETS,
     "help": "Fewer toolsets = fewer tools in every prompt (cheaper, more accurate)."},
    {"key": "read_only", "label": "Read-only", "type": "bool", "default": True,
     "help": "Only tools that read — no issues, PRs or pushes on your behalf."},
]

PRESETS: list[dict] = [
    {"id": "filesystem", "title": "Filesystem", "category": "files", "runtime": "npx",
     "description": "Read and write files inside folders you choose (and only those).",
     "params": [{"key": "folders", "label": "Allowed folders", "type": "paths",
                 "required": True, "help": "One or more folders the server may access."}],
     "secrets": []},
    {"id": "git", "title": "Git", "category": "code", "runtime": "uvx",
     "description": "Inspect a local git repository: status, log, diff, branches, commits.",
     "params": [{"key": "repository", "label": "Repository folder", "type": "path",
                 "required": True}],
     "secrets": []},
    {"id": "github", "title": "GitHub (hosted)", "category": "code", "runtime": "http",
     "description": "GitHub's hosted MCP server: repos, issues, PRs, Actions. No install.",
     "params": _GH_PARAMS, "secrets": [_GH_TOKEN]},
    {"id": "github-docker", "title": "GitHub (local, Docker)", "category": "code",
     "runtime": "docker",
     "description": "The same GitHub server run locally in Docker (works with GitHub "
                    "Enterprise and offline-only policies).",
     "params": _GH_PARAMS, "secrets": [_GH_TOKEN]},
    {"id": "fetch", "title": "Fetch", "category": "web", "runtime": "uvx",
     "description": "Fetch a web page and convert it to Markdown.",
     "params": [], "secrets": []},
    {"id": "context7", "title": "Context7 docs", "category": "code", "runtime": "http",
     "description": "Up-to-date library and framework documentation for coding questions.",
     "params": [],
     "secrets": [{"env": "CONTEXT7_API_KEY", "label": "Context7 API key (optional)",
                  "url": "https://context7.com/dashboard", "required": False,
                  "help": "Works without a key at lower rate limits."}]},
    {"id": "playwright", "title": "Playwright browser", "category": "web", "runtime": "npx",
     "description": "Drive a real browser (navigate, click, fill forms) via accessibility "
                    "snapshots.",
     "params": [], "secrets": []},
    {"id": "time", "title": "Time zones", "category": "utility", "runtime": "uvx",
     "description": "Current time and time-zone conversion.",
     "params": [], "secrets": []},
    {"id": "sqlite", "title": "SQLite", "category": "data", "runtime": "uvx",
     "description": "Query and inspect a SQLite database file.",
     "params": [{"key": "db_path", "label": "Database file", "type": "path", "required": True}],
     "secrets": []},
    {"id": "sequential-thinking", "title": "Sequential thinking", "category": "utility",
     "runtime": "npx",
     "description": "A scratchpad tool for step-by-step problem solving.",
     "params": [], "secrets": []},
    {"id": "docker-gateway", "title": "Docker MCP Toolkit", "category": "utility",
     "runtime": "docker",
     "description": "Every server you enabled in Docker Desktop's MCP Toolkit, through "
                    "one gateway.",
     "params": [], "secrets": []},
]

_BY_ID = {p["id"]: p for p in PRESETS}


def catalog() -> list[dict]:
    return [dict(p) for p in PRESETS]


def _toolsets(params: dict) -> str:
    value = params.get("toolsets")
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",")]
    chosen = [v for v in (value or GITHUB_DEFAULT_TOOLSETS) if v in GITHUB_TOOLSETS or v == "all"]
    return ",".join(chosen or GITHUB_DEFAULT_TOOLSETS)


def _paths(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [v for v in re.split(r"[\n;]", value) if v.strip()]
    return [str(v).strip() for v in (value or []) if str(v).strip()]


def build_from_preset(preset_id: str, params: dict | None = None, name: str = "") -> dict:
    """Server entry for a preset. Returns the :func:`validate_servers` result
    for the one server (``servers[0]`` is the entry when ``ok``)."""
    preset = _BY_ID.get(preset_id)
    if preset is None:
        return {"ok": False, "servers": [], "warnings": [],
                "errors": [{"server": preset_id, "field": "preset", "message": "unknown preset"}]}
    params = dict(params or {})
    for p in preset["params"]:
        if p.get("required") and not params.get(p["key"]):
            return {"ok": False, "servers": [], "warnings": [],
                    "errors": [{"server": preset_id, "field": p["key"],
                                "message": f"{p['label']} is required"}]}
    read_only = bool(params.get("read_only", True))
    entry: dict = {"name": name or preset_id, "preset": preset_id}
    if preset_id == "filesystem":
        entry["command"] = ["npx", "-y", "@modelcontextprotocol/server-filesystem",
                            *_paths(params.get("folders"))]
    elif preset_id == "git":
        entry["command"] = ["uvx", "mcp-server-git", "--repository", str(params["repository"])]
    elif preset_id == "github":
        headers = {"Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}",
                   "X-MCP-Toolsets": _toolsets(params)}
        if read_only:
            headers["X-MCP-Readonly"] = "true"
        entry.update(transport="http", url="https://api.githubcopilot.com/mcp/", headers=headers)
    elif preset_id == "github-docker":
        entry["command"] = ["docker", "run", "-i", "--rm",
                            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "-e", "GITHUB_TOOLSETS",
                            "-e", "GITHUB_READ_ONLY", "ghcr.io/github/github-mcp-server"]
        entry["env"] = {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}",
                        "GITHUB_TOOLSETS": _toolsets(params),
                        "GITHUB_READ_ONLY": "1" if read_only else "0"}
        entry["connect_timeout"] = 180          # first run pulls the image
    elif preset_id == "fetch":
        entry["command"] = ["uvx", "mcp-server-fetch"]
    elif preset_id == "context7":
        entry.update(transport="http", url="https://mcp.context7.com/mcp")
        if os.environ.get("CONTEXT7_API_KEY"):          # optional key, if saved
            entry["headers"] = {"CONTEXT7_API_KEY": "${CONTEXT7_API_KEY}"}
    elif preset_id == "playwright":
        entry["command"] = ["npx", "-y", "@playwright/mcp@latest"]
        entry["connect_timeout"] = 180
    elif preset_id == "time":
        entry["command"] = ["uvx", "mcp-server-time"]
    elif preset_id == "sqlite":
        entry["command"] = ["uvx", "mcp-server-sqlite", "--db-path", str(params["db_path"])]
    elif preset_id == "sequential-thinking":
        entry["command"] = ["npx", "-y", "@modelcontextprotocol/server-sequential-thinking"]
    elif preset_id == "docker-gateway":
        entry["command"] = ["docker", "mcp", "gateway", "run"]
        entry["connect_timeout"] = 120
    return validate_servers([entry])


# ── install from a URL ───────────────────────────────────────────────────────

_MAX_FETCH = 256 * 1024


def _raw_url(url: str) -> list[str]:
    """Candidate raw URLs: a GitHub blob → raw; a bare repo → its server.json /
    mcp.json at the default branch."""
    url = url.strip()
    m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/(.+)$", url)
    if m:
        return [f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"]
    m = re.match(r"^https://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?$", url)
    if m:
        base = f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/HEAD"
        return [f"{base}/server.json", f"{base}/mcp.json", f"{base}/.vscode/mcp.json"]
    return [url]


def fetch_config(url: str, timeout: int = 10) -> dict:
    """Fetch an MCP config (Claude Desktop / VS Code / server.json / ours) from a
    URL and turn it into validated server entries. https only (http allowed for
    localhost); 256 KB cap; the content is data, never executed."""
    url = (url or "").strip()
    if not re.match(r"^(https://|http://(localhost|127\.0\.0\.1)[:/])", url):
        return {"ok": False, "servers": [], "warnings": [], "format": "",
                "errors": [{"server": "", "field": "url", "message": "use an https:// URL"}]}
    last_err = ""
    for candidate in _raw_url(url):
        try:
            req = urllib.request.Request(candidate, headers={"User-Agent": "Namma-Agent/2.0",
                                                             "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read(_MAX_FETCH + 1)
            if len(raw) > _MAX_FETCH:
                last_err = "file is larger than 256 KB"
                continue
            obj = json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code} for {candidate}"
            continue
        except (urllib.error.URLError, OSError) as exc:
            last_err = f"couldn't reach {candidate}: {getattr(exc, 'reason', exc)}"
            continue
        except ValueError:
            last_err = f"{candidate} is not JSON"
            continue
        result = import_servers(obj)
        result["source"] = candidate
        return result
    return {"ok": False, "servers": [], "warnings": [], "format": "",
            "errors": [{"server": "", "field": "url",
                        "message": last_err or "nothing found at that URL"}]}
