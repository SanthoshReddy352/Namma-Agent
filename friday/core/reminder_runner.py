"""ReminderRunner — fires due reminders from the scheduler store.

The scheduler tool stores reminders with an optional ``due_ts``. This background
loop wakes periodically, fires any reminder whose time has passed (via an
``on_fire(reminder) -> None`` sink — e.g. speak + Telegram), marks it ``fired``,
and saves. Pure helpers (:func:`due_reminders`, :func:`fire_due`) are unit-tested
without threads.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

from friday.core.logger import logger
from friday.tools import scheduler as _store

OnFire = Callable[[dict], None]


def due_reminders(items: list[dict], now: float) -> list[dict]:
    out = []
    for it in items:
        due = it.get("due_ts")
        if due is not None and not it.get("fired") and float(due) <= now:
            out.append(it)
    return out


def fire_due(now: float, on_fire: OnFire) -> list[dict]:
    """Load the store, fire due reminders, mark them, save. Returns those fired."""
    items = _store._load()
    fired = due_reminders(items, now)
    for it in fired:
        try:
            on_fire(it)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[reminders] on_fire failed for #%s: %s", it.get("id"), exc)
        it["fired"] = True
        it["fired_at"] = int(now)
    if fired:
        _store._save(items)
    return fired


class ReminderRunner:
    def __init__(self, on_fire: OnFire, interval: float = 30.0):
        self._on_fire = on_fire
        self._interval = max(5.0, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="ReminderRunner", daemon=True)
        self._thread.start()
        logger.info("[reminders] runner started (every %.0fs)", self._interval)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                fired = fire_due(time.time(), self._on_fire)
                if fired:
                    logger.info("[reminders] fired %d reminder(s)", len(fired))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[reminders] tick failed: %s", exc)
