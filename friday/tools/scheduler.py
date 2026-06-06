"""Scheduler tools — a persisted reminder list (with optional firing).

The v1 ``triggers`` module ran a live daemon (cron / file-watch / clipboard).
The v2 port keeps the model-facing primitive — record, list, and drop reminders
— persisted to ``data/reminders.json``. When ``when`` parses to a concrete time,
a ``due_ts`` is stored and the background :class:`ReminderRunner`
(``friday/core/reminder_runner.py``, started by the service) fires it.

  add_reminder(text, when?)   list_reminders()   remove_reminder(id)
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from friday.config import load_config
from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_REL_RE = re.compile(r"\bin\s+(\d+)\s*(second|sec|minute|min|hour|hr|day)s?\b", re.I)
_HHMM_RE = re.compile(r"\b(?:at\s+)?([01]?\d|2[0-3]):([0-5]\d)\b")
_UNIT_SECONDS = {"second": 1, "sec": 1, "minute": 60, "min": 60,
                 "hour": 3600, "hr": 3600, "day": 86400}


def parse_when(when: str, now: Optional[float] = None) -> Optional[int]:
    """Best-effort parse of a free-text time into a unix timestamp, else None.

    Handles "in 10 minutes", "at 09:30"/"14:00" (next occurrence), and ISO
    timestamps. Returns None when nothing concrete is found (the reminder is
    still stored — it just won't auto-fire)."""
    when = (when or "").strip()
    if not when:
        return None
    base = now if now is not None else time.time()
    m = _REL_RE.search(when)
    if m:
        return int(base + int(m.group(1)) * _UNIT_SECONDS[m.group(2).lower()])
    try:  # ISO 8601, e.g. 2026-06-07T09:00
        return int(datetime.fromisoformat(when).timestamp())
    except ValueError:
        pass
    m = _HHMM_RE.search(when)
    if m:
        now_dt = datetime.fromtimestamp(base)
        target = now_dt.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                                second=0, microsecond=0)
        if target.timestamp() <= base:
            target += timedelta(days=1)  # next occurrence
        return int(target.timestamp())
    return None


def _store_path() -> Path:
    try:
        cfg = (load_config() or {}).get("scheduler") or {}
        path = cfg.get("store_path")
    except Exception:  # noqa: BLE001
        path = None
    return Path(path).expanduser() if path else _REPO_ROOT / "data" / "reminders.json"


def _load() -> list[dict]:
    path = _store_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("[scheduler] load failed: %s", exc)
        return []


def _save(items: list[dict]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def _add(args: dict) -> ToolResult:
    text = (args.get("text") or "").strip()
    if not text:
        return ToolResult(ok=False, content="", error="reminder text is required")
    items = _load()
    rid = (max((int(i.get("id", 0)) for i in items), default=0) + 1)
    when_text = (args.get("when") or "").strip()
    item = {"id": rid, "text": text, "when": when_text,
            "due_ts": parse_when(when_text), "fired": False,
            "created_at": int(time.time())}
    items.append(item)
    _save(items)
    when = f" ({when_text})" if when_text else ""
    return ToolResult(ok=True, content=f"Reminder #{rid} added: {text}{when}", data=item)


def _list(_args: dict) -> ToolResult:
    items = _load()
    if not items:
        return ToolResult(ok=True, content="No reminders.")
    lines = ["Reminders:"]
    for it in items:
        when = f" — {it['when']}" if it.get("when") else ""
        lines.append(f"#{it['id']}: {it['text']}{when}")
    return ToolResult(ok=True, content="\n".join(lines), data=items)


def _remove(args: dict) -> ToolResult:
    try:
        rid = int(args.get("id"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="a numeric reminder id is required")
    items = _load()
    kept = [i for i in items if int(i.get("id", 0)) != rid]
    if len(kept) == len(items):
        return ToolResult(ok=False, content="", error=f"no reminder with id {rid}")
    _save(kept)
    return ToolResult(ok=True, content=f"Removed reminder #{rid}.")


def register(registry: ToolRegistry) -> None:
    registry.register("add_reminder", "Save a reminder/to-do for later.", {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "what to be reminded about"},
            "when": {"type": "string", "description": "optional free-text time, e.g. 'tomorrow 9am'"},
        },
        "required": ["text"],
    }, _add)

    registry.register("list_reminders", "List all saved reminders.", {
        "type": "object", "properties": {},
    }, _list)

    registry.register("remove_reminder", "Delete a saved reminder by its id.", {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "reminder id to remove"}},
        "required": ["id"],
    }, _remove, destructive=True)
