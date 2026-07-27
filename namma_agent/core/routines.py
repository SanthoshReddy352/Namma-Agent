"""Proactive routines — scheduled agent runs delivered over comms.

A routine is a standing instruction ("every morning at 08:00: summarize my day's
calendar and the top AI news") persisted to ``data/routines.json``. A background
runner polls for due routines, runs each one as a normal agent turn (in the
routine's own persistent session, so runs build on each other), and delivers the
result over the user's messaging channels (Telegram/Signal/…), falling back to a
desktop notification.

This is the difference between a tool and a companion: the agent can now reach
out FIRST. Design notes:

  * The runner thread is started lazily — only when at least one enabled routine
    exists (creating a routine IS the opt-in; no hidden background work before).
  * Routine turns run with an always-decline approval gate: a scheduled run has
    nobody to ask, so destructive tools are refused, never silently executed.
  * Pure helpers (:func:`due_routines`, :func:`next_occurrence`) are unit-tested
    without threads or a live service.

Schedules (local time):
  {"kind": "interval", "every_minutes": 90}
  {"kind": "daily",    "at": "08:00"}
  {"kind": "weekly",   "weekday": 0-6 (Mon=0), "at": "18:30"}
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from namma_agent.core.logger import logger

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: run_turn(prompt, session_id) -> (content, session_id)
RunTurn = Callable[[str, Optional[str]], tuple[str, str]]
#: deliver(routine_name, content) -> None
Deliver = Callable[[str, str], None]


# ── store ─────────────────────────────────────────────────────────────────────

def _store_path(config: Optional[dict] = None) -> Path:
    path = ((config or {}).get("routines") or {}).get("store_path")
    from namma_agent.config import data_dir
    return Path(path).expanduser() if path else data_dir() / "routines.json"


def load_routines(config: Optional[dict] = None) -> list[dict]:
    path = _store_path(config)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:  # noqa: BLE001
        logger.debug("[routines] load failed: %s", exc)
        return []


def save_routines(items: list[dict], config: Optional[dict] = None) -> None:
    path = _store_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


# ── schedule math (pure) ──────────────────────────────────────────────────────

def _parse_hhmm(at: str) -> Optional[tuple[int, int]]:
    try:
        hh, mm = (int(x) for x in str(at).split(":", 1))
    except (ValueError, AttributeError):
        return None
    return (hh, mm) if 0 <= hh <= 23 and 0 <= mm <= 59 else None


def next_occurrence(schedule: dict, after_ts: float) -> Optional[float]:
    """The first moment strictly after ``after_ts`` this schedule fires, as a
    unix timestamp (local wall clock), or None for a malformed schedule."""
    kind = str(schedule.get("kind") or "")
    if kind == "interval":
        try:
            every = float(schedule.get("every_minutes") or 0) * 60
        except (TypeError, ValueError):
            return None
        return (after_ts + every) if every > 0 else None
    hhmm = _parse_hhmm(schedule.get("at") or "")
    if hhmm is None:
        return None
    base = datetime.fromtimestamp(after_ts)
    target = base.replace(hour=hhmm[0], minute=hhmm[1], second=0, microsecond=0)
    if kind == "daily":
        if target.timestamp() <= after_ts:
            target += timedelta(days=1)
        return target.timestamp()
    if kind == "weekly":
        try:
            weekday = int(schedule.get("weekday"))
        except (TypeError, ValueError):
            return None
        if not 0 <= weekday <= 6:
            return None
        target += timedelta(days=(weekday - target.weekday()) % 7)
        if target.timestamp() <= after_ts:
            target += timedelta(days=7)
        return target.timestamp()
    return None


def due_routines(items: list[dict], now: float) -> list[dict]:
    """Enabled routines whose next occurrence (after their last run / creation)
    has passed."""
    due = []
    for it in items:
        if not it.get("enabled", True):
            continue
        anchor = it.get("last_run_ts")
        if anchor is None:
            anchor = it.get("created_at")
        anchor = float(now if anchor is None else anchor)
        nxt = next_occurrence(it.get("schedule") or {}, anchor)
        if nxt is not None and nxt <= now:
            due.append(it)
    return due


# ── runner ────────────────────────────────────────────────────────────────────

class RoutineRunner:
    """Polls the store and runs due routines through the agent."""

    def __init__(self, run_turn: RunTurn, deliver: Deliver,
                 config: Optional[dict] = None, interval: float = 30.0):
        self._run_turn = run_turn
        self._deliver = deliver
        self._config = config
        self._interval = max(5.0, float(interval))
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def ensure_started(self) -> None:
        """Start the poll thread if any enabled routine exists (lazy opt-in)."""
        if self.running:
            return
        if not any(r.get("enabled", True) for r in load_routines(self._config)):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="RoutineRunner",
                                        daemon=True)
        self._thread.start()
        logger.info("[routines] runner started (every %.0fs)", self._interval)

    def stop(self) -> None:
        self._stop.set()
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self.tick(time.time())
            except Exception as exc:  # noqa: BLE001
                logger.warning("[routines] tick failed: %s", exc)

    # -- one pass (synchronous, testable) ------------------------------------

    def tick(self, now: float) -> list[dict]:
        """Run every due routine once. Returns those that ran."""
        items = load_routines(self._config)
        fired = due_routines(items, now)
        for it in fired:
            self.run_routine(it, now=now)
            it["last_run_ts"] = now
        if fired:
            save_routines(items, self._config)
        return fired

    def run_routine(self, routine: dict, now: Optional[float] = None) -> str:
        """Execute one routine's prompt as an agent turn and deliver the result.
        The routine keeps its own session, so runs can build on earlier ones."""
        name = routine.get("name") or f"routine {routine.get('id')}"
        try:
            content, session_id = self._run_turn(str(routine.get("prompt") or ""),
                                                 routine.get("session_id"))
            routine["session_id"] = session_id
        except Exception as exc:  # noqa: BLE001
            logger.warning("[routines] %s failed: %s", name, exc)
            content = ""
        if content:
            try:
                self._deliver(str(name), content)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[routines] delivery of %s failed: %s", name, exc)
        return content


# ── tools ─────────────────────────────────────────────────────────────────────

def register_routine_tools(registry, runner: RoutineRunner,
                           config: Optional[dict] = None) -> None:
    """Model-facing surface: create / list / toggle / delete / run-now."""
    from namma_agent.core.tools import ToolResult

    def _create(args: dict) -> ToolResult:
        name = (args.get("name") or "").strip()
        prompt = (args.get("prompt") or "").strip()
        schedule = args.get("schedule") if isinstance(args.get("schedule"), dict) else {}
        if not (name and prompt):
            return ToolResult(ok=False, content="", error="'name' and 'prompt' are required")
        if next_occurrence(schedule, time.time()) is None:
            return ToolResult(ok=False, content="", error=(
                "invalid 'schedule' — use {kind: interval, every_minutes: N}, "
                "{kind: daily, at: 'HH:MM'} or {kind: weekly, weekday: 0-6, at: 'HH:MM'}"))
        items = load_routines(config)
        rid = max((int(i.get("id", 0)) for i in items), default=0) + 1
        item = {"id": rid, "name": name, "prompt": prompt, "schedule": schedule,
                "enabled": True, "created_at": time.time(), "last_run_ts": None,
                "session_id": None}
        items.append(item)
        save_routines(items, config)
        runner.ensure_started()
        return ToolResult(ok=True, content=(
            f"Routine #{rid} “{name}” saved and scheduled. I'll run it and message "
            f"you with the result each time."), data=item)

    def _list(_args: dict) -> ToolResult:
        items = load_routines(config)
        if not items:
            return ToolResult(ok=True, content="No routines are set up.")
        lines = ["Routines:"]
        for it in items:
            sched = it.get("schedule") or {}
            if sched.get("kind") == "interval":
                when = f"every {sched.get('every_minutes')} min"
            elif sched.get("kind") == "weekly":
                days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
                try:
                    day = days[int(sched.get("weekday"))]
                except (TypeError, ValueError, IndexError):
                    day = "?"
                when = f"{day} {sched.get('at')}"
            else:
                when = f"daily {sched.get('at')}"
            state = "on" if it.get("enabled", True) else "off"
            lines.append(f"#{it['id']} [{state}] “{it['name']}” — {when}: {it['prompt'][:80]}")
        return ToolResult(ok=True, content="\n".join(lines), data={"routines": items})

    def _find(items: list[dict], rid) -> Optional[dict]:
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            return None
        return next((i for i in items if int(i.get("id", 0)) == rid), None)

    def _toggle(args: dict) -> ToolResult:
        items = load_routines(config)
        item = _find(items, args.get("id"))
        if item is None:
            return ToolResult(ok=False, content="", error="no routine with that id")
        item["enabled"] = bool(args.get("enabled", True))
        save_routines(items, config)
        if item["enabled"]:
            runner.ensure_started()
        state = "enabled" if item["enabled"] else "disabled"
        return ToolResult(ok=True, content=f"Routine #{item['id']} {state}.", data=item)

    def _delete(args: dict) -> ToolResult:
        items = load_routines(config)
        item = _find(items, args.get("id"))
        if item is None:
            return ToolResult(ok=False, content="", error="no routine with that id")
        items.remove(item)
        save_routines(items, config)
        return ToolResult(ok=True, content=f"Deleted routine #{item['id']} “{item['name']}”.")

    def _run_now(args: dict) -> ToolResult:
        items = load_routines(config)
        item = _find(items, args.get("id"))
        if item is None:
            return ToolResult(ok=False, content="", error="no routine with that id")
        content = runner.run_routine(item)
        item["last_run_ts"] = time.time()
        save_routines(items, config)
        return ToolResult(ok=True, content=content or "(the routine produced no output)")

    registry.register(
        "create_routine",
        ("Create a standing routine: on a schedule, run a prompt as a full agent "
         "task and message the user the result (their messaging channels, or a "
         "desktop notification). Perfect for a morning brief, news/inbox watches, "
         "or recurring check-ins."),
        {"type": "object",
         "properties": {
             "name": {"type": "string", "description": "short label, e.g. 'Morning brief'"},
             "prompt": {"type": "string",
                        "description": "the full instruction to run each time"},
             "schedule": {"type": "object", "description": (
                 "{kind: 'interval', every_minutes: N} | {kind: 'daily', at: 'HH:MM'} "
                 "| {kind: 'weekly', weekday: 0-6 (Mon=0), at: 'HH:MM'}")},
         },
         "required": ["name", "prompt", "schedule"]},
        _create, destructive=True)

    registry.register(
        "list_routines", "List the user's standing routines and their schedules.",
        {"type": "object", "properties": {}}, _list)

    registry.register(
        "toggle_routine", "Enable or disable a routine by id.",
        {"type": "object",
         "properties": {"id": {"type": "integer"},
                        "enabled": {"type": "boolean"}},
         "required": ["id", "enabled"]},
        _toggle)

    registry.register(
        "delete_routine", "Delete a routine by id.",
        {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        _delete, destructive=True)

    registry.register(
        "run_routine_now", "Run a routine immediately (also delivers the result).",
        {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]},
        _run_now)
