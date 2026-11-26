"""Event protocol v2 (PROGRESS.md Phase 4).

Before: ~17 WebSocket event types, no sequence numbers, no replay — a dropped
socket lost the in-flight reply, and a turn's events went only to the
connection that started it.

Now every chat event goes through one app-level :class:`EventLog`:

* each event gets a monotonically increasing ``seq`` (and the log a ``boot``
  id, so a client can tell a server restart from a reconnect);
* the newest ``size`` (default 500) entries are kept in a ring buffer.
  Consecutive tokens of one session fold into ONE entry that keeps its
  per-token pieces, so a whole streamed reply costs one slot and a replay never
  re-sends text the client already has;
* every connected WebSocket subscribes; a reconnecting client sends
  ``{"type": "resume", "from_seq": N, "boot": B}`` and receives exactly the
  events after N, then live ones — or ``resync_required`` when the gap fell out
  of the ring or the server restarted.

``EVENT_SCHEMA`` documents every event type and its required fields;
:func:`validate` checks an event against it (used by the tests).
"""
from __future__ import annotations

import threading
import uuid
from collections import deque
from typing import Callable, Optional

#: Event type → fields every instance must carry (besides ``type``/``seq``).
#: Connection-local control messages (hello, pong, resync_required,
#: stop_speaking) are not logged and carry no seq.
EVENT_SCHEMA: dict[str, tuple[str, ...]] = {
    # turn lifecycle
    "session_started": ("session_id",),
    "turn_queued": ("session_id",),
    "turn_started": ("session_id",),
    "token": ("session_id", "text"),
    "thinking": ("session_id", "text"),
    "preamble": ("session_id", "text"),
    "tool_started": ("session_id", "tool"),
    "tool_output": ("session_id",),
    "tool_finished": ("session_id", "tool", "ok"),
    "turn_completed": ("session_id",),
    "turn_result": ("session_id", "content"),
    "turn_cancelled": ("session_id",),
    "stopped": (),
    "error": ("message",),
    # interaction
    "approval_request": ("id", "tool", "session_id"),
    "approval_resolved": ("id",),
    "password_request": ("id", "prompt"),
    # notices
    "tools_trimmed": ("session_id", "limit", "dropped"),
    "turn_budget_exceeded": ("session_id", "tokens", "budget"),
    "context_compacted": ("session_id", "phase"),
    # chat content & panels
    "session_titled": ("session_id", "title"),
    "todo_updated": ("todos",),
    "plan_updated": ("session_id", "plan"),
    "visual": ("session_id", "artifact"),
    "a2ui": ("session_id", "message"),
    "subagent": ("run",),
    "speak": ("text",),
    "quiz": (),
    "learn_suggestion": (),
    "learning_progress": (),
    "learning_plan_updated": (),
    "learning_insights": (),
    "history_changed": ("session_id",),
    # setup (Phase 5)
    "mcp_status": ("server", "state"),
    "secret_redacted": ("session_id", "labels"),
}


def validate(event: dict) -> list[str]:
    """Problems with one event (empty = valid). Unknown types are reported."""
    etype = event.get("type")
    if etype not in EVENT_SCHEMA:
        return [f"unknown event type {etype!r}"]
    return [f"{etype}: missing {f!r}" for f in EVENT_SCHEMA[etype] if f not in event]


Subscriber = Callable[[dict], None]


class EventLog:
    def __init__(self, size: int = 500):
        self.boot = uuid.uuid4().hex[:12]
        self._size = max(10, int(size))
        self._ring: deque[dict] = deque()
        self._seq = 0
        self._lock = threading.RLock()
        self._subs: list[Subscriber] = []

    @property
    def seq(self) -> int:
        return self._seq

    def publish(self, event: dict) -> dict:
        """Stamp ``seq``, keep it in the ring, fan out to every subscriber.
        Returns the stamped event (what live subscribers receive)."""
        with self._lock:
            self._seq += 1
            stamped = {**event, "seq": self._seq}
            last = self._ring[-1] if self._ring else None
            if (event.get("type") == "token" and last is not None
                    and last.get("type") == "token"
                    and last.get("session_id") == event.get("session_id")):
                last["pieces"].append((self._seq, event.get("text", "")))
                last["seq"] = self._seq
            else:
                entry = dict(stamped)
                if entry.get("type") == "token":
                    entry["pieces"] = [(self._seq, entry.pop("text", ""))]
                self._ring.append(entry)
                while len(self._ring) > self._size:
                    self._ring.popleft()
            subs = list(self._subs)
        for fn in subs:
            try:
                fn(stamped)
            except Exception:  # noqa: BLE001 — a dead client never blocks the rest
                pass
        return stamped

    def _replay_entry(self, entry: dict, after: int) -> Optional[dict]:
        if entry.get("type") != "token":
            return {k: v for k, v in entry.items()} if entry["seq"] > after else None
        pieces = [(s, t) for s, t in entry["pieces"] if s > after]
        if not pieces:
            return None
        out = {k: v for k, v in entry.items() if k != "pieces"}
        out["text"] = "".join(t for _, t in pieces)
        out["seq"] = pieces[-1][0]
        return out

    def oldest_seq(self) -> int:
        with self._lock:
            if not self._ring:
                return self._seq + 1
            first = self._ring[0]
            return first["pieces"][0][0] if first.get("type") == "token" else first["seq"]

    def subscribe(self, fn: Subscriber, *, after: Optional[int] = None,
                  boot: Optional[str] = None) -> tuple[Callable[[], None], list[dict], bool]:
        """Atomically replay and subscribe. With ``after`` (the client's last seq)
        returns the missed events; ``ok`` is False when they can't all be
        replayed (a server restart, or the gap fell out of the ring) — the client
        must then reload state. Returns ``(unsubscribe, replay, ok)``."""
        with self._lock:
            replay: list[dict] = []
            ok = True
            if after is not None:
                if boot is not None and boot != self.boot:
                    ok = False
                elif after < self.oldest_seq() - 1 or after > self._seq:
                    ok = False
                else:
                    for entry in self._ring:
                        item = self._replay_entry(entry, after)
                        if item is not None:
                            replay.append(item)
            self._subs.append(fn)

        def _unsubscribe() -> None:
            with self._lock:
                if fn in self._subs:
                    self._subs.remove(fn)

        return _unsubscribe, replay, ok

    def __len__(self) -> int:
        return len(self._ring)
