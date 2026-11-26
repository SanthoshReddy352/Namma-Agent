"""Self-knowledge generated from the live install (PROGRESS.md Phase 2).

The old ``self_knowledge.md`` was hand-written and went stale (wrong name, tools
that no longer exist, the wrong default model) and was never in the prompt, so
"what's my MCP config?" turned into a filesystem crawl. Now:

* :func:`about_block` — a short, static "about you" block (name, version and
  the real install / source / config / data paths) injected into every system
  prompt. Static per config, so it doesn't disturb prompt caching.
* :func:`render` — the full reference returned by the ``about_namma`` tool: live
  sections built from the running config and tool registry, followed by the
  narrative sections of ``self_knowledge.md``. Secrets are never included —
  only the *names* of the environment variables that hold them.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Optional

_PKG_DIR = Path(__file__).resolve().parent.parent          # …/namma_agent
_DOC = _PKG_DIR / "self_knowledge.md"


def paths(config: Optional[dict] = None) -> dict[str, str]:
    """The app's own locations, resolved to absolute paths."""
    from namma_agent.config import _REPO_ROOT, config_file, data_dir, env_file, overlay_file

    cfg = config or {}
    data = data_dir().resolve()
    db = (cfg.get("database") or {}).get("path") or str(data / "namma_agent.db")
    out = {
        "install_dir": str(_REPO_ROOT),
        "source_dir": str(_PKG_DIR),
        "config_file": str(config_file()),
        "env_file": str(env_file()),
        "data_dir": str(data),
        "database": str(Path(db).resolve()) if db != ":memory:" else db,
        "logs_dir": str((_REPO_ROOT / "logs")),
        "user_dir": str(Path("~/.namma_agent").expanduser()),
        "python": sys.executable,
    }
    out["user_config"] = str(overlay_file())
    return out


def about_block(config: Optional[dict] = None, name: str = "") -> str:
    """Compact, cache-stable "about you" block for the system prompt."""
    from namma_agent.config import assistant_name
    from namma_agent.version import __version__

    p = paths(config)
    name = name or assistant_name(config)
    lines = [
        f"ABOUT YOU — you are {name}, version {__version__}, running from this machine. "
        "Your own files (read them with read_file; edits ask the user first):",
        f"- install: {p['install_dir']} · source: {p['source_dir']}",
        f"- config: {p['config_file']} (documented defaults) + your settings in "
        f"{p['user_config']} (what Settings changes; it wins)",
        f"- secrets: vault (Settings → Security) or {p['env_file']} — never reveal values",
        f"- data: {p['data_dir']} · user skills/personas/hooks: {p['user_dir']}",
        "- MCP servers are under `mcp.servers` in the config file. For anything about "
        "your own setup (models, MCP, toolsets, paths), call `about_namma` first "
        "instead of searching the disk.",
    ]
    return "\n".join(lines)


def _mcp_section(config: dict) -> list[str]:
    servers = ((config.get("mcp") or {}).get("servers")) or []
    if not servers:
        return ["No MCP servers are configured (add them under `mcp.servers`)."]
    out = []
    for s in servers:
        if not isinstance(s, dict):
            continue
        cmd = s.get("command")
        cmd_text = " ".join(map(str, cmd)) if isinstance(cmd, list) else str(cmd or s.get("url") or "")
        env_names = sorted((s.get("env") or {}).keys()) if isinstance(s.get("env"), dict) else []
        state = "enabled" if s.get("enabled", True) else "disabled"
        line = f"- {s.get('name', '?')} ({state}): `{cmd_text[:160]}`"
        if env_names:
            line += f" · env vars: {', '.join(env_names)}"
        out.append(line)
    return out


def _models_section(config: dict) -> list[str]:
    from namma_agent.config import configured_models, configured_providers

    lines = []
    for p in configured_providers(config):
        lines.append(f"- provider `{p['id']}`: type {p['type'] or '?'}"
                     + (f", base_url {p['base_url']}" if p["base_url"] else "")
                     + (f", key in ${p['api_key_env']}" if p["api_key_env"] else ""))
    for m in configured_models(config):
        lines.append(f"- model `{m['id']}`: {m['model']} via {m['provider'] or m['type'] or '?'}")
    legacy = config.get("provider") or {}
    if legacy:
        fb = len(legacy.get("fallback") or [])
        lines.append(f"- default `provider:` {legacy.get('type', '?')} / {legacy.get('model', '?')}"
                     + (f" (+{fb} fallback)" if fb else ""))
    return lines or ["No models configured."]


def _tools_section(registry: Any, config: dict) -> list[str]:
    if registry is None:
        return []
    from namma_agent.core.tool_search import search_settings

    groups: dict[str, list[str]] = {}
    disabled = 0
    for t in registry.all():
        if not t.enabled:
            disabled += 1
            continue
        groups.setdefault(t.category or "general", []).append(t.name)
    ts = search_settings(config)
    tools_cfg = config.get("tools") or {}
    lines = [f"{sum(len(v) for v in groups.values())} tools enabled ({disabled} disabled) · "
             f"tool search: {ts['mode']} (threshold {ts['threshold']}) · "
             f"profile: {tools_cfg.get('profile') or 'general'}"]
    for cat in sorted(groups):
        lines.append(f"- {cat}: {', '.join(sorted(groups[cat]))}")
    return lines


def render(config: Optional[dict] = None, registry: Any = None, topic: str = "") -> str:
    """The full self-reference for ``about_namma`` (optionally one topic)."""
    from namma_agent.config import assistant_name, load_config
    from namma_agent.version import __version__

    cfg = config if config is not None else load_config()
    name = assistant_name(cfg)
    p = paths(cfg)
    live = [
        f"# About {name} (live)",
        "",
        "## Version",
        f"{name} {__version__} · Python {sys.version.split()[0]} · {sys.platform}",
        "",
        "## Paths",
        *[f"- {k}: {v}" for k, v in p.items()],
        "",
        "## Models",
        *_models_section(cfg),
        "",
        "## MCP servers",
        f"Configured in {p['config_file']} under `mcp.servers`.",
        *_mcp_section(cfg),
    ]
    tools = _tools_section(registry, cfg)
    if tools:
        live += ["", "## Toolsets", *tools]
    narrative = ""
    if _DOC.exists():
        narrative = _DOC.read_text(encoding="utf-8", errors="replace").replace("{name}", name)
    text = "\n".join(live) + ("\n\n" + narrative if narrative else "")
    topic = (topic or "").strip().lower()
    if topic:
        sections = text.split("\n## ")
        hits = ["## " + s for s in sections[1:] if topic in s.lower()]
        if hits:
            return "\n\n".join(hits)
    return text


