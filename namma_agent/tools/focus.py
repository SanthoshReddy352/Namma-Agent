"""Focus-session tools — a lightweight pomodoro/focus timer. Ports v1 focus_session.

  start_focus(minutes, label?)  focus_status()  end_focus()

State is a single JSON file (``data/focus.json``). Starting a session also drops a
due reminder ("Focus session over") so the background ReminderRunner announces the
end — no separate daemon needed.
"""
from __future__ import annotations

import time

from namma_agent.core.tools import ToolRegistry, ToolResult
from namma_agent.tools import _jsonstore as store
from namma_agent.tools import scheduler as _sched

_FILE = "focus.json"


def _path():
    return store.store_path("focus", _FILE)


def _current() -> dict | None:
    items = store.load(_path())
    return items[0] if items else None


def _start(args: dict) -> ToolResult:
    try:
        minutes = int(args.get("minutes", 25))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="minutes must be a number")
    minutes = max(1, min(minutes, 240))
    if _current() is not None:
        return ToolResult(ok=False, content="", error="a focus session is already running; end it first")
    label = (args.get("label") or "").strip()
    now = time.time()
    session = {"label": label, "minutes": minutes,
               "started_at": int(now), "ends_at": int(now + minutes * 60)}
    store.save(_path(), [session])
    # Let the reminder runner announce the end of the session.
    reminders = _sched._load()
    rid = (max((int(r.get("id", 0)) for r in reminders), default=0) + 1)
    reminders.append({"id": rid, "text": f"Focus session over{f' ({label})' if label else ''}",
                      "when": f"in {minutes} minutes", "due_ts": int(now + minutes * 60),
                      "fired": False, "created_at": int(now)})
    _sched._save(reminders)
    tag = f" on {label}" if label else ""
    return ToolResult(ok=True, content=f"Focus session started{tag} for {minutes} minutes.", data=session)


def _status(_args: dict) -> ToolResult:
    cur = _current()
    if cur is None:
        return ToolResult(ok=True, content="No focus session is running.")
    remaining = max(0, int(cur["ends_at"] - time.time()))
    mins, secs = divmod(remaining, 60)
    tag = f" ({cur['label']})" if cur.get("label") else ""
    return ToolResult(ok=True, content=f"Focus session{tag}: {mins}m {secs}s remaining.", data=cur)


def _end(_args: dict) -> ToolResult:
    cur = _current()
    if cur is None:
        return ToolResult(ok=False, content="", error="no focus session is running")
    store.save(_path(), [])
    return ToolResult(ok=True, content="Focus session ended.")


def register(registry: ToolRegistry) -> None:
    registry.register("start_focus", "Start a focus/pomodoro timer.", {
        "type": "object",
        "properties": {
            "minutes": {"type": "integer", "description": "session length (default 25)"},
            "label": {"type": "string", "description": "optional what you're focusing on"},
        },
    }, _start)

    registry.register("focus_status", "Check the current focus session's remaining time.", {
        "type": "object", "properties": {},
    }, _status)

    registry.register("end_focus", "End the current focus session early.", {
        "type": "object", "properties": {},
    }, _end)
