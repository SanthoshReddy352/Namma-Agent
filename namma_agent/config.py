"""Config loading for Namma Agent.

Loads a YAML config and a ``.env`` file (no external dependency — a tiny parser
covers the ``KEY=value`` format). Resolution order for the config path:

  1. ``$NAMMA_CONFIG`` if set
  2. ``namma_agent/config.yaml`` (the v2 config, preferred during the migration)
  3. ``config.yaml`` at the repo root (legacy fallback)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Optional[str] = None) -> None:
    """Load ``.env`` into ``os.environ``.

    A real, non-empty environment variable still wins (the documented precedence),
    but an **empty or whitespace-only** existing var does NOT shadow ``.env`` — that
    case (e.g. a shell that exports ``OPENAI_API_KEY=``) was silently blanking the
    provider key and making every provider look "unavailable"."""
    env_path = Path(path) if path else _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and not os.environ.get(key, "").strip():
            os.environ[key] = value


def _config_path() -> Path:
    if os.environ.get("NAMMA_CONFIG"):
        return Path(os.environ["NAMMA_CONFIG"])
    v2 = _REPO_ROOT / "namma_agent" / "config.yaml"
    if v2.exists():
        return v2
    return _REPO_ROOT / "config.yaml"


def _deep_merge(base: dict, overrides: dict) -> dict:
    """Recursively merge ``overrides`` into ``base`` (overrides win)."""
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _local_overrides_path(cfg_path: Path) -> Path:
    """UI-written overrides live beside the base config as ``config.local.yaml``;
    merged on top so the documented, commented base file is never rewritten."""
    return cfg_path.with_name("config.local.yaml")


def load_config(path: Optional[str] = None) -> dict[str, Any]:
    """Load the merged config dict (base + local overrides) and ensure ``.env``."""
    load_dotenv()
    cfg_path = Path(path) if path else _config_path()
    data: dict[str, Any] = {}
    if cfg_path.exists():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    local = _local_overrides_path(cfg_path)
    if local.exists():
        _deep_merge(data, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    return data


def update_config(updates: dict, path: Optional[str] = None) -> dict:
    """Persist ``updates`` (deep-merged) into ``config.local.yaml`` and return the
    merged effective config. Leaves the commented base ``config.yaml`` untouched."""
    cfg_path = Path(path) if path else _config_path()
    local = _local_overrides_path(cfg_path)
    current = (yaml.safe_load(local.read_text(encoding="utf-8")) or {}) if local.exists() else {}
    _deep_merge(current, updates or {})
    # Atomic write (tmp + replace): a crash mid-write must never leave a truncated
    # config.local.yaml behind — that would wipe every UI-made setting on next boot.
    tmp = local.with_name(local.name + ".tmp")
    tmp.write_text(yaml.safe_dump(current, sort_keys=False, default_flow_style=False),
                   encoding="utf-8")
    tmp.replace(local)
    return load_config(path)


def data_dir() -> Path:
    """Root directory for runtime state (DB, uploads, media, watchers, vault…).

    ``$NAMMA_DATA_DIR`` overrides it — the server/Docker story (Phase 6): mount
    a volume, point the var at it, and every store follows. Default stays the
    relative ``data/`` (the repo root in dev, the install dir for the app).
    Read at import time by some modules, so set the var before launch (systemd
    ``EnvironmentFile=`` and docker-compose ``environment:`` both do).
    """
    d = os.environ.get("NAMMA_DATA_DIR", "").strip()
    return Path(d).expanduser() if d else Path("data")


def server_bind(config: Optional[dict] = None) -> tuple[str, int]:
    """(host, port) the web server binds. Defaults to loopback — never silently
    public. ``$NAMMA_HOST``/``$PORT`` override the config (containers set env,
    not files)."""
    cfg = config if config is not None else load_config()
    srv = cfg.get("server") or {}
    host = (os.environ.get("NAMMA_HOST", "").strip()
            or str(srv.get("host") or "127.0.0.1").strip() or "127.0.0.1")
    port = int(os.environ.get("PORT") or srv.get("port") or 8000)
    return host, port


def auth_token(config: Optional[dict] = None) -> str:
    """The access token protecting /api/* and /ws when set. Resolution:
    ``$NAMMA_AUTH_TOKEN`` → ``server.auth_token`` in config → "" (auth off)."""
    env = os.environ.get("NAMMA_AUTH_TOKEN", "").strip()
    if env:
        return env
    cfg = config if config is not None else load_config()
    return str((cfg.get("server") or {}).get("auth_token") or "").strip()


def assistant_name(config: Optional[dict] = None) -> str:
    """The assistant's display name — the single source of truth for what the
    assistant is called everywhere (system prompt, UI, voice, messaging).

    Resolution order: ``$ASSISTANT_NAME`` env override → ``assistant.name`` in the
    config → ``"Namma Agent"``. Change it in one place (``namma_agent/config.yaml`` under
    ``assistant.name``, or the ``ASSISTANT_NAME`` env var) to rename the assistant.
    """
    env = os.environ.get("ASSISTANT_NAME")
    if env and env.strip():
        return env.strip()
    cfg = config if config is not None else load_config()
    name = ((cfg.get("assistant") or {}).get("name") or "").strip()
    return name or "Namma Agent"


def configured_providers(config: Optional[dict] = None) -> list[dict]:
    """The user's named provider connections (``providers:`` in config).

    Each is a reusable connection — type + base_url + its OWN api_key_env — so
    several providers (Opencode, Groq, OpenAI, …) coexist, each with a distinct
    API key. Models reference one of these by ``id``. Normalised with a stable id.
    """
    cfg = config if config is not None else load_config()
    out: list[dict] = []
    seen: set[str] = set()
    for i, p in enumerate(cfg.get("providers") or []):
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or p.get("label") or p.get("type") or f"provider-{i}").strip()
        if not pid or pid in seen:
            pid = f"{pid or 'provider'}-{i}"
        seen.add(pid)
        out.append({
            "id": pid,
            "label": (p.get("label") or pid).strip(),
            "type": (p.get("type") or "").strip(),
            "base_url": (p.get("base_url") or "").strip(),
            "api_key_env": (p.get("api_key_env") or "").strip(),
        })
    return out


def configured_models(config: Optional[dict] = None) -> list[dict]:
    """The user's curated list of switchable model profiles (``models:`` in config).

    Each profile names a ``provider`` (one of :func:`configured_providers`) plus a
    ``model`` id, so models from different providers can be swapped per-chat. Older
    self-contained rows (inline type/base_url/api_key_env, no ``provider`` ref) are
    still honoured. Normalised to a stable shape with a guaranteed ``id``.
    """
    cfg = config if config is not None else load_config()
    out: list[dict] = []
    seen: set[str] = set()
    for i, m in enumerate(cfg.get("models") or []):
        if not isinstance(m, dict):
            continue
        mid = str(m.get("id") or m.get("model") or f"model-{i}").strip()
        if not mid or mid in seen:
            mid = f"{mid or 'model'}-{i}"
        seen.add(mid)
        out.append({
            "id": mid,
            "label": (m.get("label") or m.get("model") or mid).strip(),
            "provider": (m.get("provider") or "").strip(),   # → configured_providers id
            "model": (m.get("model") or "").strip(),
            # Back-compat: inline connection used when no provider ref is given.
            "type": (m.get("type") or "").strip(),
            "base_url": (m.get("base_url") or "").strip(),
            "api_key_env": (m.get("api_key_env") or "").strip(),
            # Optional per-profile turn shaping for small-context (local) models —
            # see the "models:" docs in config.yaml. 0/empty = inherit the global
            # provider/conversation settings.
            "max_tokens": int(m.get("max_tokens") or 0),
            "timeout_s": float(m.get("timeout_s") or 0),
            "max_history_turns": int(m.get("max_history_turns") or 0),
            "tool_result_max_chars": int(m.get("tool_result_max_chars") or 0),
            "tools_allow": [str(t).strip() for t in (m.get("tools_allow") or [])
                            if str(t).strip()],
        })
    return out


def set_env_values(updates: dict, path: Optional[str] = None) -> list[str]:
    """Create/update ``KEY=value`` lines in ``.env`` (preserving other lines).
    Also applies to the live ``os.environ``. Returns the keys written."""
    env_path = Path(path) if path else _REPO_ROOT / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    written: list[str] = []
    for key, value in (updates or {}).items():
        key = str(key).strip()
        if not key:
            continue
        value = "" if value is None else str(value)
        new_line = f"{key}={value}"
        for i, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped and not stripped.startswith("#") and stripped.split("=", 1)[0].strip() == key:
                lines[i] = new_line
                break
        else:
            lines.append(new_line)
        os.environ[key] = value
        written.append(key)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written
