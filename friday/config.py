"""Config loading for FRIDAY v2.

Loads a YAML config and a ``.env`` file (no external dependency — a tiny parser
covers the ``KEY=value`` format). Resolution order for the config path:

  1. ``$FRIDAY_CONFIG`` if set
  2. ``friday/config.yaml`` (the v2 config, preferred during the migration)
  3. ``config.yaml`` at the repo root (legacy fallback)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: Optional[str] = None) -> None:
    """Load ``.env`` into ``os.environ`` (does not overwrite existing vars)."""
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
        if key and key not in os.environ:
            os.environ[key] = value


def _config_path() -> Path:
    if os.environ.get("FRIDAY_CONFIG"):
        return Path(os.environ["FRIDAY_CONFIG"])
    v2 = _REPO_ROOT / "friday" / "config.yaml"
    if v2.exists():
        return v2
    return _REPO_ROOT / "config.yaml"


def load_config(path: Optional[str] = None) -> dict[str, Any]:
    """Load the merged config dict and ensure ``.env`` is available."""
    load_dotenv()
    cfg_path = Path(path) if path else _config_path()
    if not cfg_path.exists():
        return {}
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    return data
