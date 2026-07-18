"""Engram write pipeline — how memory gets in (Mem0-style, always on).

After every turn the exchange is queued for a background worker (off the reply
path, one item at a time). The pipeline:

  1. **salience gate** (cheap, no LLM) — skip trivia/commands/dumps
  2. **extraction** — one model call turns the turn into 0..n candidate facts
  3. **retrieve-similar** — BM25 neighbours of each candidate
  4. **resolution** — one model call decides ADD / UPDATE (invalidate the old
     fact) / DELETE (user retracted) / NOOP (duplicate → reinforce)
  5. **graph upsert** + optional core-memory patch for identity-grade facts

There is NO on/off ingest flag: the salience gate replaces it. Every model call
goes through the provider getter — i.e. **whatever model the user selected in
Settings**, never a hardcoded one — with strict JSON prompts and a NOOP bias
(when unsure, don't write). Every write is injection-screened; flagged text is
quarantined out of recall. A per-hour budget caps runaway usage.
"""
from __future__ import annotations

import json
import queue
import re
import threading
import time
from collections import deque
from typing import Callable, Optional

from namma_agent.core.docscan import scan_text
from namma_agent.core.engram.core_memory import CoreMemory
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.logger import logger

_EXTRACT_SYSTEM = """You maintain the long-term memory of a personal AI assistant.
From the conversation exchange, extract durable facts worth remembering about the
USER's world: identity, preferences, people, projects, plans, decisions, standing
instructions. NOT: small talk, one-off commands, questions, code dumps, or anything
easily re-derived. The assistant's reply is context only — never a fact source.

Return ONLY a JSON array (no prose, no markdown). Each element:
{"text": "<one self-contained sentence, third person>",
 "kind": "fact|preference|event",
 "subject": "<entity>", "predicate": "<snake_case relation>", "object": "<entity>",
 "importance": <0.0-1.0>}
Most exchanges contain nothing durable — then return []."""

_RESOLVE_SYSTEM = """You maintain the long-term memory of a personal AI assistant.
Decide what to do with a NEW candidate memory given the EXISTING similar memories.

Rules (be conservative — when unsure, NOOP):
- NOOP: candidate is already covered by an existing memory (same meaning).
- UPDATE: candidate contradicts or refreshes existing memory #N (a changed value,
  a correction, newer state). The old memory will be invalidated, not deleted.
- DELETE: the user explicitly retracted existing memory #N.
- ADD: genuinely new information.

Return ONLY JSON: {"op": "ADD|UPDATE|DELETE|NOOP", "target": <existing # or null>,
"core": null OR {"block": "user|agent", "action": "add|replace",
"text": "<dense entry>", "old_text": "<substring of entry to replace or null>"}}
Set "core" ONLY for identity-grade durable facts (name, role, standing preference,
a lasting instruction) — the small always-in-context memory. Otherwise null."""

_FENCE_RE = re.compile(r"^```[a-z]*\s*|\s*```$", re.MULTILINE)


class EngramWriter:
    def __init__(self, store: EngramStore, core: CoreMemory,
                 provider_getter: Callable[[], object],
                 min_chars: int = 24, budget_per_hour: int = 60,
                 embedder=None):
        self.store = store
        self.core = core
        # Optional vector channel: new facts are embedded as they land (best
        # effort; the consolidator backfills anything missed).
        self.embedder = embedder
        # Resolves to the LIVE provider chain — the model the user picked in
        # Settings drives all memory work (see namma-memory-model-routing).
        self._get_provider = provider_getter
        self.min_chars = int(min_chars)
        self.budget_per_hour = int(budget_per_hour)
        self._calls: deque = deque()
        # (text, reply, source, explicit) — see _enqueue.
        self._q: "queue.Queue[tuple[str, str, str, bool]]" = queue.Queue(maxsize=200)
        self._worker: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    # -- entry points ----------------------------------------------------------

    def ingest_turn(self, user_text: str, assistant_text: str = "",
                    source: str = "chat", trusted: bool = True) -> None:
        """Queue a completed turn (always on; the salience gate filters).
        ``trusted=False`` (an untrusted-channel sender, core.trust) quarantines
        the would-be write instead of running the pipeline."""
        text = (user_text or "").strip()
        if not self._salient(text):
            return
        if not trusted:
            self.quarantine(text, source=source)
            return
        self._enqueue(text, (assistant_text or "").strip()[:800], source, False)

    def ingest_text(self, text: str, source: str = "manual") -> None:
        """Explicit remember (memory tools, project/learning notes, onboarding) —
        bypasses the salience gate, shares the rest of the pipeline. Explicit
        items must never vanish: if extraction yields nothing (weak model, model
        offline), the raw text itself is stored as the fact. Tool-driven saves
        made during an untrusted-sender turn are quarantined, not written."""
        text = (text or "").strip()
        if not text:
            return
        from namma_agent.core.trust import get_message_trust
        if get_message_trust() == "untrusted":
            self.quarantine(text, source=source)
            return
        self._enqueue(text, "", source, True)

    def quarantine(self, text: str, source: str = "untrusted") -> None:
        """Store a would-be memory write from an untrusted sender for the owner's
        review — kept out of the recall index (any non-'ok' screen_status is
        never FTS-indexed), visible in the facts browser / future security tab."""
        text = (text or "").strip()
        if not text:
            return
        self.store.add_item(text[:500], kind="fact", source=f"untrusted:{source}",
                            screen_status="untrusted")
        logger.info("[engram] quarantined a memory write from an untrusted sender")

    def ingest_learning(self, text: str) -> None:
        """Learning-Room recaps (completed modules) enter the same pipeline."""
        self.ingest_text(text, source="learning")

    def pending(self) -> int:
        return self._q.qsize()

    # -- salience gate (no LLM) --------------------------------------------------

    def _salient(self, text: str) -> bool:
        # The length bar assumes English-ish density. Non-Latin scripts (Telugu,
        # Hindi, CJK, …) pack more meaning per character and never match the
        # English imperative list below, so they get a lower bar — the LLM
        # extractor (which returns [] for trivia) is the real filter for them.
        if any(ord(c) > 0x036F for c in text):
            min_chars = max(8, self.min_chars // 2)
        else:
            min_chars = self.min_chars
        if len(text) < min_chars:
            return False
        low = text.lower()
        # Bare imperatives ("open chrome", "run the tests") carry no durable fact.
        if len(text) < 60 and low.split()[:1] and low.split()[0] in (
                "open", "close", "run", "start", "stop", "play", "pause", "show",
                "list", "search", "find", "translate"):
            return False
        # Paste dumps: mostly code/log lines — episodic search already has them.
        lines = text.splitlines()
        if len(lines) > 8:
            codey = sum(1 for ln in lines if ln[:1] in (" ", "\t", "{", "<", "#", ">"))
            if codey > len(lines) // 2:
                return False
        return True

    # -- worker --------------------------------------------------------------------

    def _enqueue(self, text: str, reply: str, source: str, explicit: bool) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="engram-writer",
                                                daemon=True)
                self._worker.start()
        try:
            self._q.put_nowait((text, reply, source, explicit))
        except queue.Full:
            logger.debug("[engram] write queue full — dropping an item")

    def _run(self) -> None:
        while True:
            text, reply, source, explicit = self._q.get()
            try:
                self.process(text, reply, source, explicit=explicit)
            except Exception as exc:  # noqa: BLE001 — memory failures never surface
                logger.warning("[engram] write pipeline failed: %s", exc)
            finally:
                self._q.task_done()

    # -- the pipeline (public so tests run it synchronously) ------------------------

    def process(self, text: str, reply: str = "", source: str = "chat",
                explicit: bool = False) -> list[dict]:
        """Run one exchange through extract → resolve → apply. Returns the applied
        ops (for tests/telemetry)."""
        candidates = self._extract(text, reply)
        if not candidates and explicit:
            # An explicit remember is a promise — keep the raw text as the fact.
            candidates = [{"text": text[:400], "kind": "fact", "importance": 0.7}]
        applied: list[dict] = []
        for cand in candidates:
            result = self.apply_candidate(cand, source)
            if result is not None:
                applied.append(result)
        return applied

    def apply_candidate(self, cand: dict, source: str = "consolidator") -> Optional[dict]:
        """Run ONE already-structured candidate fact through screen →
        retrieve-similar → resolve → apply, skipping extraction. The
        consolidator's promote step uses this directly — its candidates come
        pre-extracted, and the resolver still dedups/invalidates as usual."""
        ctext = " ".join(str(cand.get("text") or "").strip().split())
        if not ctext:
            return None
        screen = scan_text(ctext)
        if screen.flagged:
            # Quarantined: stored for the audit trail, never indexed/recalled.
            self.store.add_item(ctext, kind=str(cand.get("kind") or "fact"),
                                source=source, screen_status="flagged")
            return {"op": "QUARANTINE", "text": ctext}
        neighbours = self.store.similar_items(ctext, limit=8)
        decision = self._resolve(cand, ctext, neighbours)
        return self._apply(cand, ctext, decision, neighbours, source)

    def _apply(self, cand: dict, ctext: str, decision: dict,
               neighbours: list[dict], source: str) -> dict:
        op = str(decision.get("op") or "NOOP").upper()
        target = decision.get("target")
        target_item = None
        if isinstance(target, int) and 1 <= target <= len(neighbours):
            target_item = neighbours[target - 1]

        if op == "NOOP":
            if target_item:
                self.store.reinforce(target_item["id"])
            return {"op": "NOOP", "text": ctext}
        if op == "DELETE":
            if target_item:
                self.store.invalidate(target_item["id"])
            return {"op": "DELETE", "text": ctext}

        # ADD / UPDATE both create the new fact; UPDATE also expires the old one.
        item_id = self.store.add_item(
            ctext, kind=str(cand.get("kind") or "fact"),
            subject=str(cand.get("subject") or ""),
            predicate=str(cand.get("predicate") or ""),
            object=str(cand.get("object") or ""),
            importance=float(cand.get("importance") or 0.5),
            source=source)
        if cand.get("subject") and cand.get("object") and cand.get("predicate"):
            self.store.add_relation(str(cand["subject"]), str(cand["predicate"]),
                                    str(cand["object"]), item_id=item_id)
        self._embed_item(item_id, ctext)
        if op == "UPDATE" and target_item:
            self.store.invalidate(target_item["id"], superseded_by=item_id)

        core = decision.get("core")
        if isinstance(core, dict) and core.get("text"):
            block = str(core.get("block") or "user")
            if str(core.get("action")) == "replace" and core.get("old_text"):
                self.core.replace(block, str(core["old_text"]), str(core["text"]))
            else:
                self.core.add(block, str(core["text"]))
        return {"op": op, "id": item_id, "text": ctext}

    def _embed_item(self, item_id: str, text: str) -> None:
        """Best-effort vector for a new fact (recall's semantic channel)."""
        if self.embedder is None or not self.embedder.available():
            return
        try:
            vecs = self.embedder.embed([text])
            if vecs:
                self.store.add_vector(item_id, self.embedder.model, vecs[0])
        except Exception as exc:  # noqa: BLE001 — vectors are an enhancement
            logger.debug("[engram] embed failed: %s", exc)

    # -- model calls -----------------------------------------------------------------

    def _extract(self, text: str, reply: str) -> list[dict]:
        user = f"USER: {text[:2000]}"
        if reply:
            user += f"\nASSISTANT (context only): {reply}"
        data = self._call_json(_EXTRACT_SYSTEM, user)
        return [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []

    def _resolve(self, cand: dict, ctext: str, neighbours: list[dict]) -> dict:
        if not neighbours:
            return {"op": "ADD", "target": None,
                    # Identity-grade facts may still patch core memory on first sight.
                    "core": self._default_core_patch(cand, ctext)}
        listing = "\n".join(f"#{i + 1}: {n['text']}" for i, n in enumerate(neighbours))
        user = f"NEW candidate: {ctext}\n\nEXISTING memories:\n{listing}"
        data = self._call_json(_RESOLVE_SYSTEM, user)
        if not isinstance(data, dict) or str(data.get("op", "")).upper() not in (
                "ADD", "UPDATE", "DELETE", "NOOP"):
            return {"op": "NOOP", "target": None, "core": None}  # unparseable → don't write
        return data

    @staticmethod
    def _default_core_patch(cand: dict, ctext: str) -> Optional[dict]:
        if (float(cand.get("importance") or 0) >= 0.85
                and str(cand.get("kind")) in ("fact", "preference")):
            return {"block": "user", "action": "add", "text": ctext, "old_text": None}
        return None

    def _call_json(self, system: str, user: str):
        provider = self._get_provider() if callable(self._get_provider) else None
        if provider is None or not self._within_budget():
            return None
        try:
            resp = provider.generate(
                [{"role": "system", "content": system},
                 {"role": "user", "content": user}],
                tools=None, stream=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[engram] memory model call failed: %s", exc)
            return None
        # Only a call that actually happened consumes budget — a provider outage
        # must not starve the pipeline for the rest of the hour once it recovers.
        self._calls.append(time.time())
        raw = _FENCE_RE.sub("", (getattr(resp, "content", "") or "").strip()).strip()
        start = min((i for i in (raw.find("["), raw.find("{")) if i >= 0), default=-1)
        if start < 0:
            return None
        try:
            # raw_decode tolerates trailing prose after the JSON payload.
            value, _ = json.JSONDecoder().raw_decode(raw[start:])
            return value
        except ValueError:
            return None

    def _within_budget(self) -> bool:
        """Checks only — successful calls are recorded in _call_json, so a failed
        call (provider down) never eats budget."""
        now = time.time()
        while self._calls and now - self._calls[0] > 3600:
            self._calls.popleft()
        if len(self._calls) >= self.budget_per_hour:
            logger.debug("[engram] hourly memory-write budget reached — skipping")
            return False
        return True
