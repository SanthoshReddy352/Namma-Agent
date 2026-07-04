"""Background auto-ingestion of chat turns into Cognee's knowledge graph.

Opt-in (``cognee.auto_ingest``). After each turn the user's message is queued and a
single worker thread runs Cognee's permanent ``remember`` (cognify) one item at a
time — so the graph grows from normal chat WITHOUT adding latency to the reply and
WITHOUT concurrent writes (Kuzu is single-writer). It degrades silently when Cognee
isn't connected.
"""
from __future__ import annotations

import queue
import threading
from typing import Callable, Optional

from namma_agent.core.logger import logger


class CogneeIngestor:
    def __init__(self, client_getter: Callable[[], object], enabled: bool = False,
                 min_chars: int = 24, include_reply: bool = False,
                 learning_enabled: bool = True):
        # client_getter() -> the live cognee MCP client (or None). A getter (not the
        # client itself) so reconnects/late-connects are picked up automatically.
        self._get_client = client_getter
        self.enabled = enabled
        self.min_chars = min_chars
        self.include_reply = include_reply
        # Learning-Room → graph: completed-module recaps flow into Cognee on their
        # own switch, independent of per-turn auto_ingest. Module completion is a
        # rare, explicit, high-value event (not every turn), so it's safe to default
        # ON — it still no-ops unless the cognee server is actually connected.
        self.learning_enabled = learning_enabled
        self._q: "queue.Queue[str]" = queue.Queue(maxsize=200)
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="cognee-ingest", daemon=True)
                self._worker.start()

    def ingest_async(self, user_text: str, assistant_text: str = "") -> None:
        """Queue a turn for background graph ingestion (no-op when disabled/short)."""
        if not self.enabled:
            return
        text = (user_text or "").strip()
        if len(text) < self.min_chars:
            return
        if self.include_reply and assistant_text:
            text = f"{text}\n\n(Assistant replied: {assistant_text.strip()[:800]})"
        self._enqueue(text)

    def ingest_text(self, text: str) -> None:
        """Queue text for the graph UNCONDITIONALLY (not gated by the auto-ingest
        flag) — the path behind explicit remembers: memory tools, project /
        learning notes, onboarding. Still background + best-effort."""
        text = (text or "").strip()
        if text:
            self._enqueue(text)

    def ingest_learning(self, text: str) -> None:
        """Queue a Learning-Room concept (e.g. a completed-module recap) for the
        graph. Gated by ``learning_enabled`` (its own switch), not the per-turn
        ``enabled`` flag, since module completions are rare + meaningful. No-op when
        disabled, too short, or the cognee server isn't connected."""
        if not self.learning_enabled:
            return
        text = (text or "").strip()
        if len(text) < self.min_chars:
            return
        self._enqueue(text)

    def _enqueue(self, text: str) -> None:
        self._ensure_worker()
        try:
            self._q.put_nowait(text)
        except queue.Full:
            logger.debug("[cognee] ingest queue full — dropping an item")

    def _run(self) -> None:
        while True:
            text = self._q.get()
            try:
                client = self._get_client() if callable(self._get_client) else None
                if client is None:
                    continue  # Cognee not connected — drop silently
                client.call_tool("remember", {"data": text}, timeout=900)
                logger.info("[cognee] auto-ingested a turn into the knowledge graph")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[cognee] auto-ingest failed: %s", exc)
            finally:
                self._q.task_done()
