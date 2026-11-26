"""Config loading for Namma Agent.

Loads a YAML config and a ``.env`` file (no external dependency — a tiny parser
covers the ``KEY=value`` format). Resolution order for the config path:

  1. ``$NAMMA_CONFIG`` if set
  2. ``namma_agent/config.yaml`` (the v2 config, preferred during the migration)
  3. ``config.yaml`` at the repo root (legacy fallback)

User changes (Settings, setup wizard, ``namma config set``) never rewrite that
documented base: they go to ONE user config in the data dir
(:func:`user_config_file`), deep-merged on top of it.
"""
from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _state_dir() -> Optional[Path]:
    """The explicit state directory (``$NAMMA_DATA_DIR``), or None in the
    default dev/desktop layout. When set (Docker, systemd), the Settings overlay
    and ``.env`` live there too, so UI edits survive an image rebuild (BUG-11)."""
    d = os.environ.get("NAMMA_DATA_DIR", "").strip()
    if d:
        return Path(d).expanduser()
    if _desktop_mode():
        # Phase 9 W3: under the Electron shell state never lands in the
        # CWD-relative ``data/`` (the install dir) — it lives in the per-user
        # app-data folder. The shell passes NAMMA_DATA_DIR; this is the fallback.
        from namma_agent.core.desktop import default_data_dir
        return default_data_dir()
    return None


def _desktop_mode() -> bool:
    return os.environ.get("NAMMA_DESKTOP", "").strip().lower() in {"1", "true", "yes", "on"}


def env_file() -> Path:
    """Where ``.env`` is read from and written to: ``$NAMMA_ENV_FILE`` →
    ``$NAMMA_DATA_DIR/.env`` → the repo-root ``.env``."""
    explicit = os.environ.get("NAMMA_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    state = _state_dir()
    if state is not None:
        return state / ".env"
    return _REPO_ROOT / ".env"


def load_dotenv(path: Optional[str] = None) -> None:
    """Load ``.env`` into ``os.environ``.

    A real, non-empty environment variable still wins (the documented precedence),
    but an **empty or whitespace-only** existing var does NOT shadow ``.env`` — that
    case (e.g. a shell that exports ``OPENAI_API_KEY=``) was silently blanking the
    provider key and making every provider look "unavailable".

    Without an explicit ``path``, :func:`env_file` is loaded first and the
    repo-root ``.env`` second (filling only what is still unset), so moving
    state to ``$NAMMA_DATA_DIR`` never loses keys kept in the old place — unless
    ``$NAMMA_ENV_FILE`` is set, which pins the one file to read."""
    if path:
        _load_env_path(Path(path))
        return
    primary = env_file()
    _load_env_path(primary)
    # An EXPLICIT $NAMMA_ENV_FILE means exactly that file: isolated runs (the test
    # suite, scratch instances) must not quietly pick up the real repo .env keys.
    if os.environ.get("NAMMA_ENV_FILE", "").strip():
        return
    legacy = _REPO_ROOT / ".env"
    if legacy != primary:
        _load_env_path(legacy)


def _load_env_path(env_path: Path) -> None:
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


def config_file() -> Path:
    """The documented base config file in use."""
    return _config_path()


#: The legacy overlay name. It was retired in Phase 2 (owner decision, 2026-11-25)
#: in favour of ONE user config in the data dir; it is migrated once, then renamed
#: with this suffix.
_LEGACY_OVERLAY = "config.local.yaml"
_MIGRATED_SUFFIX = ".migrated"
USER_CONFIG_NAME = "user_config.yaml"
_migrate_lock = threading.Lock()


def user_config_file() -> Path:
    """The ONE user config: everything Settings, the setup wizard and the CLI
    change is written here, deep-merged over the documented base config (which
    is never rewritten and stays a clean, git-tracked default).

    Location: ``$NAMMA_USER_CONFIG`` → ``$NAMMA_DATA_DIR/user_config.yaml`` →
    ``<install>/data/user_config.yaml``. It lives with the rest of the user's
    state (database, vault), so it survives updates and, in Docker, image
    rebuilds (BUG-11). On first use the legacy ``config.local.yaml`` is migrated
    into it (see :func:`_migrate_legacy_overlay`)."""
    explicit = os.environ.get("NAMMA_USER_CONFIG", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    state = _state_dir() or (_REPO_ROOT / "data")
    target = state / USER_CONFIG_NAME
    if not target.exists():
        _migrate_legacy_overlay(target)
    return target


def _migrate_legacy_overlay(target: Path) -> Optional[Path]:
    """One-shot: copy the legacy overlay into ``target`` and rename the old file
    to ``config.local.yaml.migrated`` so it is obviously no longer read. The
    candidates, in order: an overlay in the state dir, then the one beside the
    base config (the dev/desktop location, or the Docker image's bundled
    server-lite profile, which becomes the seed of the volume's user config).
    Returns the file migrated from, or None. Never raises."""
    with _migrate_lock:
        if target.exists():
            return None
        candidates = []
        state = _state_dir()
        if state is not None:
            candidates.append(state / _LEGACY_OVERLAY)
        candidates.append(_config_path().with_name(_LEGACY_OVERLAY))
        for legacy in candidates:
            if not legacy.is_file():
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                tmp = target.with_name(target.name + ".tmp")
                tmp.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
                tmp.replace(target)
            except OSError as exc:
                _log_warning(f"[config] could not migrate {legacy} → {target}: {exc}")
                return None
            try:
                legacy.replace(legacy.with_name(legacy.name + _MIGRATED_SUFFIX))
            except OSError:
                pass  # read-only image layer etc. — the old file is simply ignored now
            _log_info(f"[config] migrated settings from {legacy} to {target}")
            return legacy
    return None


def _log_info(msg: str) -> None:
    from namma_agent.core.logger import logger  # noqa: PLC0415 — avoid an import cycle
    logger.info(msg)


def _log_warning(msg: str) -> None:
    from namma_agent.core.logger import logger  # noqa: PLC0415
    logger.warning(msg)


def _local_overrides_path(cfg_path: Path) -> Path:
    """The overlay merged over ``cfg_path``. For the app's own base config that
    is the user config in the data dir (:func:`user_config_file`). A base config
    passed EXPLICITLY (tests, portable tooling) keeps a sibling
    ``config.local.yaml``, so such callers never touch the user's settings."""
    try:
        is_default = Path(cfg_path).resolve() == _config_path().resolve()
    except OSError:
        is_default = False
    if is_default:
        return user_config_file()
    return Path(cfg_path).with_name(_LEGACY_OVERLAY)


def overlay_file() -> Path:
    """The file Settings edits are written to (:func:`update_config`)."""
    return _local_overrides_path(_config_path())


def load_config(path: Optional[str] = None) -> dict[str, Any]:
    """Load the merged config dict (base + the user config) and ensure ``.env``."""
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
    """Persist ``updates`` (deep-merged) into the user config and return the
    merged effective config. Leaves the commented base ``config.yaml`` untouched."""
    cfg_path = Path(path) if path else _config_path()
    local = _local_overrides_path(cfg_path)
    current = (yaml.safe_load(local.read_text(encoding="utf-8")) or {}) if local.exists() else {}
    _deep_merge(current, updates or {})
    # Atomic write (tmp + replace): a crash mid-write must never leave a truncated
    # user config behind — that would wipe every UI-made setting on next boot.
    local.parent.mkdir(parents=True, exist_ok=True)
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
    return _state_dir() or Path("data")


def server_bind(config: Optional[dict] = None) -> tuple[str, int]:
    """(host, port) the web server binds. Defaults to loopback — never silently
    public. ``$NAMMA_HOST``/``$PORT`` override the config (containers set env,
    not files)."""
    cfg = config if config is not None else load_config()
    srv = cfg.get("server") or {}
    host = (os.environ.get("NAMMA_HOST", "").strip()
            or str(srv.get("host") or "127.0.0.1").strip() or "127.0.0.1")
    # NAMMA_PORT is what `namma serve --port` sets (and the desktop shell passes);
    # PORT is the container convention. Either beats the config file.
    port = int(os.environ.get("NAMMA_PORT", "").strip() or os.environ.get("PORT")
               or srv.get("port") or 8000)
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
            "context_window": int(m.get("context_window") or 0),
            "tools_allow": [str(t).strip() for t in (m.get("tools_allow") or [])
                            if str(t).strip()],
        })
    return out


_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def set_env_values(updates: dict, path: Optional[str] = None) -> list[str]:
    """Create/update ``KEY=value`` lines in ``.env`` (preserving other lines).
    Also applies to the live ``os.environ``. Returns the keys written."""
    env_path = Path(path) if path else env_file()
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    written: list[str] = []
    for key, value in (updates or {}).items():
        key = str(key).strip()
        if not key:
            continue
        value = "" if value is None else str(value)
        # A key or value carrying a line break would inject extra KEY=value lines
        # into .env (e.g. a pasted "sk-…\nNAMMA_API_TOKEN=" overriding auth).
        if not _ENV_KEY_RE.match(key):
            raise ValueError(f"invalid environment variable name: {key!r}")
        if "\n" in value or "\r" in value or "\x00" in value:
            raise ValueError(f"value for {key} contains a line break or NUL")
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
    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return written


def remove_env_values(keys, path: Optional[str] = None) -> list[str]:
    """Drop ``KEY=`` lines from ``.env`` (used once a key moved to the vault, so
    a stale ``.env`` copy can't shadow the vault at the next boot). Returns the
    keys removed; never touches ``os.environ``."""
    env_path = Path(path) if path else env_file()
    if not env_path.exists():
        return []
    wanted = {str(k).strip() for k in keys or [] if str(k).strip()}
    kept, removed = [], []
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        name = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if name and not stripped.startswith("#") and name in wanted:
            removed.append(name)
            continue
        kept.append(raw)
    if removed:
        env_path.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return removed
