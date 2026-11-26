"""Event bus + fan-out for Namma Agent.

The agent emits typed events (``turn_started``, ``preamble``, ``tool_started``,
``tool_finished``, ``turn_completed``, plus ``token`` for streaming). Multiple
sinks consume the same stream: the narration engine (→ Piper TTS), the backend
WebSocket (→ GUI), and logging.

``fanout`` adapts several ``emit(event_type, payload)`` callables into one, so the
agent's single ``emit`` hook can drive all of them.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

from namma_agent.core.logger import logger

EmitFn = Callable[[str, dict], None]


class EventBus:
    """Minimal pub/sub. Subscribe by event type (or ``"*"`` for all)."""

    def __init__(self):
        self._subs: dict[str, list[Callable[[dict], None]]] = defaultdict(list)

    def subscribe(self, event_type: str, callback: Callable[[dict], None]) -> None:
        self._subs[event_type].append(callback)

    def publish(self, event_type: str, payload: dict) -> None:
        for cb in self._subs.get(event_type, []):
            self._safe(cb, payload)
        for cb in self._subs.get("*", []):
            self._safe(cb, {"type": event_type, **payload})

    @staticmethod
    def _safe(cb, payload):
        try:
            cb(payload)
        except Exception as exc:  # noqa: BLE001
            logger.error("event handler %s failed: %s", cb, exc)

    def emit(self, event_type: str, payload: dict) -> None:
        """Adapter matching the agent's ``emit(event_type, payload)`` signature."""
        self.publish(event_type, payload)


class Broadcaster:
    """Process-wide event fan-out to every connected client (each WebSocket
    subscribes its sink on connect). For events that outlive one turn — e.g. a
    background sub-agent finishing after its chat's turn ended."""

    def __init__(self):
        import threading

        self._subs: list[EmitFn] = []
        self._lock = threading.Lock()

    def subscribe(self, sink: EmitFn) -> Callable[[], None]:
        with self._lock:
            self._subs.append(sink)

        def _unsubscribe() -> None:
            with self._lock:
                if sink in self._subs:
                    self._subs.remove(sink)

        return _unsubscribe

    def publish(self, event_type: str, payload: dict) -> None:
        with self._lock:
            subs = list(self._subs)
        for sink in subs:
            try:
                sink(event_type, payload)
            except Exception as exc:  # noqa: BLE001 — one dead client can't block the rest
                logger.debug("broadcast sink failed: %s", exc)

    def __len__(self) -> int:
        return len(self._subs)


def fanout(*sinks: EmitFn) -> EmitFn:
    """Combine several emit callables into one."""

    def emit(event_type: str, payload: dict) -> None:
        for sink in sinks:
            if sink is None:
                continue
            try:
                sink(event_type, payload)
            except Exception as exc:  # noqa: BLE001
                logger.error("event sink failed: %s", exc)

    return emit
