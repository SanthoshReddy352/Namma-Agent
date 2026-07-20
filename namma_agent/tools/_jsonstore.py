"""Tiny JSON-list persistence shared by the reminder/task/goal tools.

Underscore-prefixed so the auto-discovery loader skips it (it's a helper, not a
tool). Each store is a JSON array of dict rows under ``data/`` (path overridable
via the matching config section).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from namma_agent.config import load_config
from namma_agent.core.logger import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def store_path(config_section: str, default_filename: str) -> Path:
    try:
        cfg = (load_config() or {}).get(config_section) or {}
        path = cfg.get("store_path")
    except Exception:  # noqa: BLE001
        path = None
    from namma_agent.config import data_dir
    return Path(path).expanduser() if path else data_dir() / default_filename


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("[jsonstore] load failed %s: %s", path, exc)
        return []


def save(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def next_id(items: list[dict]) -> int:
    return max((int(i.get("id", 0)) for i in items), default=0) + 1


def find(items: list[dict], rid: int) -> Optional[dict]:
    for it in items:
        if int(it.get("id", 0)) == rid:
            return it
    return None
