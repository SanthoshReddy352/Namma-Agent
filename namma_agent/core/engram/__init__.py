"""Engram — Namma Agent's native memory engine (see docs/MEMORY_SYSTEM_DESIGN.md).

In-process, SQLite-backed, zero external infrastructure. Layers wired here:

  * L1 core memory      — bounded curated blocks, in EVERY system prompt
  * L3 semantic memory  — bi-temporal facts + entity graph, LLM write pipeline
  * L5 environment      — host model (OS/drives/folders) so paths are never guessed
  * recall              — fused BM25 + graph + episodic retrieval, no LLM, ms-fast

All memory model calls route through the provider getter — the model the user
selected in Settings, never a hardcoded one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from namma_agent.core.engram import environment as _environment
from namma_agent.core.engram import recall as _recall
from namma_agent.core.engram.consolidate import ConsolidationScheduler, Consolidator
from namma_agent.core.engram.core_memory import CoreMemory
from namma_agent.core.engram.environment import EnvironmentMemory
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.engram.writer import EngramWriter
from namma_agent.core.memory import Database

__all__ = ["Engram", "EngramStore", "CoreMemory", "EnvironmentMemory",
           "EngramWriter", "Consolidator", "ConsolidationScheduler"]


class Engram:
    """Facade the service builds once and hands to the agent + tools."""

    def __init__(self, db: Database, config: Optional[dict] = None,
                 provider_getter: Optional[Callable[[], object]] = None,
                 apps_count_getter: Optional[Callable[[], Optional[int]]] = None,
                 summarize_fn: Optional[Callable[[int], int]] = None,
                 skills_getter: Optional[Callable[[], object]] = None,
                 skill_usage_fn: Optional[Callable[[], dict]] = None,
                 skill_disable_fn: Optional[Callable[[str], None]] = None):
        cfg = (config or {}).get("memory") or {}
        write_cfg = cfg.get("write") or {}
        recall_cfg = cfg.get("recall") or {}
        cons_cfg = cfg.get("consolidate") or {}

        # data/memory/ next to the SQLite file (":memory:" test DBs skip mirrors).
        db_path = ((config or {}).get("database") or {}).get("path", db.path)
        data_dir = (Path(db_path).parent / "memory") if db_path != ":memory:" else None

        self.store = EngramStore(db)
        self.db = db
        # Optional vector channel (memory.embeddings): None when unconfigured —
        # recall is BM25-only, exactly as before.
        from namma_agent.core.engram.embeddings import Embedder
        self.embedder = Embedder.from_config(config)
        self.core = CoreMemory(self.store, data_dir=data_dir)
        self.environment = EnvironmentMemory(data_dir=data_dir,
                                             apps_count_getter=apps_count_getter)
        # File tools resolve model-written paths against THIS host model
        # (environment.resolve_path — design §5 L5 "validation assist").
        _environment.set_default(self.environment)
        self.writer = EngramWriter(
            self.store, self.core,
            provider_getter=provider_getter or (lambda: None),
            min_chars=int(write_cfg.get("salience_min_chars", 24)),
            budget_per_hour=int(write_cfg.get("budget_per_hour", 60)),
            embedder=self.embedder,
            # Phase 7c: hold auto-extracted facts for the user's yes/no.
            write_approval=bool(cfg.get("write_approval", False)),
        )
        self.prefetch_enabled = bool(recall_cfg.get("prefetch", True))
        self.prefetch_k = int(recall_cfg.get("k", 5))

        # Sleep-time self-improvement (design §8). The scheduler is built here
        # but STARTED by the service (background threads stay opt-out-able and
        # never run in bare test services).
        self.consolidator = Consolidator(
            self.store, self.core, self.writer, self.environment,
            summarize_fn=summarize_fn,
            recent_summaries_fn=self._recent_summaries,
            skills_getter=skills_getter,
            skill_usage_fn=skill_usage_fn,
            skill_disable_fn=skill_disable_fn,
            half_life_days=float(cons_cfg.get("half_life_days", 30)),
            archive_floor=float(cons_cfg.get("archive_floor", 0.05)),
            event_horizon_days=float(cons_cfg.get("event_horizon_days", 90)),
            quality_batch=int(cons_cfg.get("quality_batch", 30)),
        )
        self.consolidate_background = bool(cons_cfg.get("background", True))
        self.scheduler = ConsolidationScheduler(
            self.consolidator,
            idle_minutes=float(cons_cfg.get("idle_minutes", 20)),
            daily_at=str(cons_cfg.get("daily_at", "03:30")),
        )

    def _recent_summaries(self, limit: int = 10) -> list[str]:
        """Recent session summaries — promote/reflect source material."""
        try:
            sessions = self.db.list_sessions(limit=max(limit * 2, 10))
        except Exception:  # noqa: BLE001
            return []
        return [s["summary"] for s in sessions if (s.get("summary") or "").strip()][:limit]

    def note_activity(self) -> None:
        """Every turn resets the idle clock (called by the service)."""
        self.scheduler.note_activity()

    def consolidate(self, reason: str = "manual") -> dict:
        """One improvement pass — the Memory tab button and the scheduler share it."""
        result = self.consolidator.run(reason=reason)
        backfilled = self._backfill_vectors()
        if backfilled:
            result["vectors_backfilled"] = backfilled
        self.scheduler.note_run()
        return result

    def _backfill_vectors(self, limit: int = 200) -> int:
        """Embed live facts that don't have a vector yet (facts written while the
        embedder was down/unconfigured). Part of every consolidation pass."""
        if self.embedder is None or not self.embedder.available():
            return 0
        missing = self.store.items_missing_vectors(self.embedder.model, limit=limit)
        if not missing:
            return 0
        vecs = self.embedder.embed([m["text"] for m in missing])
        if not vecs:
            return 0
        for item, vec in zip(missing, vecs):
            self.store.add_vector(item["id"], self.embedder.model, vec)
        return len(missing)

    # -- read side --------------------------------------------------------------

    def recall(self, query: str, k: int = 8, include_expired: bool = False) -> list[dict]:
        return _recall.recall(self.store, self.db, query, k=k,
                              include_expired=include_expired,
                              embedder=self.embedder)

    def prefetch_block(self, user_input: str) -> str:
        """Automatic recall injected into the turn (replaces the old regex-gated
        Cognee context thread): score-floored, in-process, milliseconds."""
        if not self.prefetch_enabled:
            return ""
        results = [r for r in self.recall(user_input, k=self.prefetch_k)
                   if r.get("score", 0) >= _recall.PREFETCH_FLOOR]
        return _recall.render_block(results)

    def memory_block(self) -> str:
        """The always-in-context block: L1 core memory + L5 host model."""
        parts = [p for p in (self.core.render(), self.environment.render()) if p]
        return "\n\n".join(parts)

    # -- status ------------------------------------------------------------------

    def status(self) -> dict:
        counts = self.store.counts()
        return {"connected": True, "engine": "engram", **counts,
                "vectors": self.store.vector_count(),
                "embeddings": bool(self.embedder is not None
                                   and self.embedder.available()),
                "core_user": self.core.usage("user"),
                "core_agent": self.core.usage("agent"),
                "pending_writes": self.writer.pending(),
                # Storage quality (what memory CONTAINS, as opposed to what it
                # can retrieve) — the audit pass's headline figures.
                **self.store.quality_stats(),
                # Persisted report card + slider range for the Memory tab.
                "last_consolidation": self.store.latest_consolidation(),
                "since": self.store.first_memory_at()}
