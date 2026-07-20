"""Learning nudges — "it's been a while since you studied X" over Telegram.

Spaced practice is one of the strongest effects in learning science, and the
nudge is the agentic half of it: when an active topic with modules still to go
hasn't been touched for ``after_days`` days, Namma Agent pings the user's messaging
channel with their progress and an invitation back.

Like the reminder runner, the background thread is OPT-IN (it rides the same
``scheduler.run_in_background`` switch — no hidden background processes); the
decision logic is pure and unit-tested without threads. Per-topic last-nudge
timestamps persist in a small JSON file so restarts don't re-spam, and a topic
is nudged at most once per ``after_days`` window.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from namma_agent.core.logger import logger

from namma_agent.config import data_dir as _data_dir
STATE_PATH = _data_dir() / "learning_nudges.json"


def _parse_ts(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso).timestamp()
    except (TypeError, ValueError):
        return 0.0


def stale_topics(topics: list[dict], now: float, after_days: float,
                 last_nudges: dict[str, float]) -> list[dict]:
    """Active, unfinished topics idle for >= after_days and not nudged within
    the current window. Pure — feed it anything in tests."""
    horizon = after_days * 86400
    out = []
    for t in topics:
        if (t.get("status") or "active") != "active":
            continue
        prog = t.get("progress") or {}
        if not (t.get("plan") or []):
            continue  # nothing to come back to yet
        if prog.get("total") and prog.get("done", 0) >= prog["total"]:
            continue  # finished — congratulations already sent
        idle = now - _parse_ts(t.get("updated_at") or "")
        if idle < horizon:
            continue
        if now - last_nudges.get(t["id"], 0.0) < horizon:
            continue  # already nudged this window
        out.append(t)
    return out


def nudge_message(topic: dict, after_days: float) -> str:
    prog = topic.get("progress") or {}
    done, total = prog.get("done", 0), prog.get("total", 0)
    cur = next((m["title"] for m in (topic.get("plan") or [])
                if m.get("status") == "current"), None)
    parts = [f"📚 It's been a while since you worked on “{topic['title']}” "
             f"({done}/{total} modules done)."]
    if cur:
        parts.append(f"Next up: “{cur}”.")
    parts.append("A short session keeps it fresh — shall we pick it back up?")
    return " ".join(parts)


def _load_state(path: Path) -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _save_state(path: Path, state: dict[str, float]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        logger.warning("[learning-nudge] could not persist state: %s", exc)


def nudge_tick(db, send: Callable[[str], bool], now: float, after_days: float,
               state_path: Path = STATE_PATH) -> int:
    """One pass: nudge every stale topic once. Returns how many were sent."""
    state = _load_state(state_path)
    sent = 0
    for topic in stale_topics(db.list_learning_topics(), now, after_days, state):
        try:
            if send(nudge_message(topic, after_days)):
                state[topic["id"]] = now
                sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("[learning-nudge] send failed for %s: %s", topic["id"], exc)
    if sent:
        _save_state(state_path, state)
    return sent


class LearningNudger:
    """Hourly background check (opt-in; started by the service)."""

    def __init__(self, db, send: Callable[[str], bool], after_days: float = 3.0,
                 interval: float = 3600.0, state_path: Optional[Path] = None):
        self._db = db
        self._send = send
        self._after_days = max(0.5, float(after_days))
        self._interval = max(60.0, float(interval))
        self._state_path = state_path or STATE_PATH
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="LearningNudger", daemon=True)
        self._thread.start()
        logger.info("[learning-nudge] started (idle > %.1f day(s), check every %.0fs)",
                    self._after_days, self._interval)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                n = nudge_tick(self._db, self._send, time.time(), self._after_days,
                               self._state_path)
                if n:
                    logger.info("[learning-nudge] sent %d nudge(s)", n)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[learning-nudge] tick failed: %s", exc)
