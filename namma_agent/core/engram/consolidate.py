"""Engram consolidator — sleep-time self-improvement (design §8).

One run = a pass of independent, individually-budgeted steps that make memory
*tighter, not bigger* while the app is idle:

  1. **summarize**  — finished sessions get recallable summaries (service hook)
  2. **promote**    — durable facts sitting in session summaries that never got
                      extracted are proposed by the model and fed through the
                      normal resolution pipeline (dedup/contradiction handling)
  3. **merge**      — same-triple and same-text duplicate facts are folded
  4. **decay**      — stale, low-importance, never-reinforced facts are archived
                      (out of recall, still browsable); old `event` facts expire
  5. **reflect**    — a few higher-level `insight` memories are written from the
                      recent facts + episodes (Generative-Agents style)
  6. **compact**    — a core-memory block over 80% budget is densified
  7. **environment**— the L5 host model is re-probed (new drives/tools show up)

Every model call goes through the writer's provider getter — the model the user
selected in Settings — and shares the writer's hourly budget. Every step is
best-effort: a failure is recorded in the report, never raised.

The :class:`ConsolidationScheduler` triggers runs on **idle** (no turns for N
minutes) and **daily** (a local wall-clock time), mirroring the manual
"Improve memory" button. Reports persist in ``consolidation_runs``.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from namma_agent.core.docscan import scan_text
from namma_agent.core.engram.core_memory import BLOCK_BUDGET_CHARS, CoreMemory
from namma_agent.core.engram.environment import EnvironmentMemory
from namma_agent.core.engram.store import EngramStore
from namma_agent.core.engram.writer import EngramWriter
from namma_agent.core.logger import logger

_PROMOTE_SYSTEM = """You maintain the long-term memory of a personal AI assistant.
Below are RECENT CONVERSATION SUMMARIES and the KNOWN FACTS already stored.
Propose durable facts about the USER's world that appear in the summaries but are
MISSING from the known facts (identity, preferences, people, projects, decisions).

Return ONLY a JSON array (max 3 elements, [] when nothing qualifies):
[{"text": "<one self-contained sentence, third person>",
  "kind": "fact|preference|event",
  "subject": "<entity>", "predicate": "<snake_case relation>", "object": "<entity>",
  "importance": <0.0-1.0>}]
Be conservative — when unsure, leave it out."""

_REFLECT_SYSTEM = """You maintain the long-term memory of a personal AI assistant.
From the RECENT FACTS and CONVERSATION SUMMARIES below, write up to 3 higher-level
INSIGHTS about the user — patterns, preferences, or goals that span multiple
observations (e.g. "Santhosh prefers step-by-step explanations with code first").
An insight must be grounded in at least two observations; do not restate a single
fact. Return ONLY a JSON array of strings ([] when nothing qualifies)."""

_SKILL_DRAFT_SYSTEM = """You maintain the procedural memory (skills) of a personal
AI assistant. From the CONVERSATION SUMMARIES below, identify ONE multi-step
workflow the user asked for at least TWICE that is NOT covered by the EXISTING
SKILLS. Return ONLY a JSON array (max 1 element, [] when nothing qualifies):
[{"name": "<short-kebab-case-name>",
  "description": "<one line: when to use this skill>",
  "steps": ["<step 1>", "<step 2>", ...]}]
Be very conservative — a skill is only worth drafting when the SAME workflow
clearly repeats. When unsure, return []."""

_COMPACT_SYSTEM = """You curate the small always-in-context core memory of a
personal AI assistant. Rewrite the entries below into FEWER, DENSER single-line
entries that preserve every distinct fact. Merge overlapping entries; never invent
information. Return ONLY a JSON array of strings, total length under {budget}
characters."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_days(iso: str) -> float:
    try:
        then = datetime.fromisoformat(iso)
        if then.tzinfo is None:
            then = then.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - then).total_seconds() / 86400)
    except ValueError:
        return 0.0


class Consolidator:
    """The steps. Pure against the store/writer — schedulable and testable."""

    def __init__(self, store: EngramStore, core: CoreMemory, writer: EngramWriter,
                 environment: EnvironmentMemory,
                 summarize_fn: Optional[Callable[[int], int]] = None,
                 recent_summaries_fn: Optional[Callable[[int], list[str]]] = None,
                 skills_getter: Optional[Callable[[], object]] = None,
                 skill_usage_fn: Optional[Callable[[], dict]] = None,
                 skill_disable_fn: Optional[Callable[[str], None]] = None,
                 half_life_days: float = 30.0, archive_floor: float = 0.05,
                 event_horizon_days: float = 90.0):
        self.store = store
        self.core = core
        self.writer = writer
        self.environment = environment
        self._summarize = summarize_fn            # (limit) -> sessions summarized
        self._recent_summaries = recent_summaries_fn  # (limit) -> summary texts
        self._skills = skills_getter              # () -> SkillStore | None (L4)
        self._skill_usage = skill_usage_fn        # () -> {skill_name: use count}
        self._disable_skill = skill_disable_fn    # (name) -> persist disabled state
        self.half_life_days = float(half_life_days)
        self.archive_floor = float(archive_floor)
        self.event_horizon_days = float(event_horizon_days)
        self._run_lock = threading.Lock()

    # -- the run ---------------------------------------------------------------

    def run(self, reason: str = "manual") -> dict:
        """One full pass. Never raises; each step lands its count (or an error
        marker) in the persisted report."""
        if not self._run_lock.acquire(blocking=False):
            return {"ok": False, "error": "a consolidation run is already in progress"}
        try:
            report: dict = {}
            for name, step in (
                ("sessions_summarized", self._step_summarize),
                ("promoted", self._step_promote),
                ("merged", self._step_merge),
                ("archived", self._step_decay),
                ("events_expired", self._step_event_horizon),
                ("insights", self._step_reflect),
                ("skill_drafts", self._step_skill_drafts),
                ("skills_reinforced", self._step_skill_usage),
                ("core_compacted", self._step_compact_core),
                ("environment_refreshed", self._step_environment),
            ):
                try:
                    report[name] = step()
                except Exception as exc:  # noqa: BLE001 — a step never kills the run
                    logger.warning("[engram] consolidate step %s failed: %s", name, exc)
                    report[name] = 0
            self.store.record_consolidation(report, reason=reason)
            return {"ok": True, "at": _now_iso(), "reason": reason, **report}
        finally:
            self._run_lock.release()

    # -- steps -------------------------------------------------------------------

    def _step_summarize(self) -> int:
        return self._summarize(5) if self._summarize else 0

    def _step_promote(self) -> int:
        """Episodic → semantic: facts living only in session summaries get
        extracted and run through the normal resolver (so duplicates NOOP)."""
        summaries = (self._recent_summaries(10) if self._recent_summaries else [])
        summaries = [s for s in summaries if (s or "").strip()]
        if not summaries:
            return 0
        known = [i["text"] for i in self.store.list_items(limit=60)]
        user = ("RECENT CONVERSATION SUMMARIES:\n"
                + "\n".join(f"- {s[:400]}" for s in summaries[:10])
                + "\n\nKNOWN FACTS:\n"
                + ("\n".join(f"- {t}" for t in known) if known else "(none)"))
        data = self.writer._call_json(_PROMOTE_SYSTEM, user)
        if not isinstance(data, list):
            return 0
        promoted = 0
        for cand in data[:3]:
            if not isinstance(cand, dict):
                continue
            result = self.writer.apply_candidate(cand, source="consolidator:promote")
            if result and result.get("op") in ("ADD", "UPDATE"):
                promoted += 1
        return promoted

    def _step_merge(self) -> int:
        return self.store.merge_exact_duplicates() + self.store.merge_triple_duplicates()

    def decay_score(self, item: dict) -> float:
        """Ebbinghaus-style retention: importance × reinforcement × recency."""
        importance = float(item.get("importance") or 0.5)
        freq = max(1, int(item.get("frequency") or 1))
        age = _age_days(item.get("last_seen") or item.get("created_at") or _now_iso())
        return (importance * (1 + 0.2 * math.log(freq))
                * math.exp(-age / self.half_life_days))

    def _step_decay(self) -> int:
        """Archive facts the user hasn't touched in ages and that never mattered
        much. Deliberately conservative: identity-grade (importance ≥ 0.7),
        preferences, insights, and reinforced (freq ≥ 3) facts never decay."""
        archived = 0
        for item in self.store.list_items(limit=2000):
            if item.get("kind") in ("preference", "insight"):
                continue
            if float(item.get("importance") or 0.5) >= 0.7:
                continue
            if int(item.get("frequency") or 1) >= 3:
                continue
            if self.decay_score(item) < self.archive_floor:
                self.store.archive(item["id"])
                archived += 1
        return archived

    def _step_event_horizon(self) -> int:
        """Time-boxed happenings ("has an exam on Friday") stop being true on
        their own — expire `event` facts past the horizon (bi-temporal: they
        stay queryable as history)."""
        expired = 0
        for item in self.store.list_items(kind="event", limit=1000):
            if _age_days(item.get("last_seen") or item["created_at"]) > self.event_horizon_days:
                self.store.invalidate(item["id"])
                expired += 1
        return expired

    def _step_reflect(self) -> int:
        facts = self.store.list_items(limit=40)
        summaries = (self._recent_summaries(8) if self._recent_summaries else [])
        if len(facts) < 4:          # nothing to generalize over yet
            return 0
        user = ("RECENT FACTS:\n" + "\n".join(f"- {f['text']}" for f in facts)
                + "\n\nCONVERSATION SUMMARIES:\n"
                + ("\n".join(f"- {s[:300]}" for s in summaries) if summaries else "(none)"))
        data = self.writer._call_json(_REFLECT_SYSTEM, user)
        if not isinstance(data, list):
            return 0
        existing = {" ".join(f["text"].lower().split())
                    for f in self.store.list_items(kind="insight", limit=200)}
        written = 0
        for text in data[:3]:
            text = " ".join(str(text or "").strip().split())
            if not text or " ".join(text.lower().split()) in existing:
                continue
            if scan_text(text).flagged:
                continue
            self.store.add_item(text, kind="insight", importance=0.6,
                                source="consolidator:reflect")
            written += 1
        return written

    def _step_skill_drafts(self) -> int:
        """Reflection → procedural memory (design §8 step 5 / §5 L4): when the
        episodes show the SAME multi-step workflow repeating, draft it as a
        DISABLED skill (out of the agent's catalog until the user enables it in
        Settings → Skills — a proposal, not a self-granted capability)."""
        skills = self._skills() if self._skills else None
        if skills is None:
            return 0
        summaries = self._recent_summaries(8) if self._recent_summaries else []
        if len(summaries) < 2:      # a workflow can't repeat inside one session
            return 0
        existing = sorted(s.name for s in skills.all())
        user = ("EXISTING SKILLS: " + (", ".join(existing) or "(none)")
                + "\n\nCONVERSATION SUMMARIES:\n"
                + "\n".join(f"- {s[:300]}" for s in summaries))
        data = self.writer._call_json(_SKILL_DRAFT_SYSTEM, user)
        if not isinstance(data, list):
            return 0
        drafted = 0
        for d in data[:1]:
            if not isinstance(d, dict):
                continue
            name = str(d.get("name") or "").strip()
            desc = str(d.get("description") or "").strip()
            steps = [str(s).strip() for s in (d.get("steps") or []) if str(s).strip()]
            if not name or not desc or len(steps) < 2:
                continue
            body = "## Steps\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1))
            if scan_text(desc + "\n" + body).flagged:
                continue
            slug = skills._slug(name)
            if skills.get(slug) is not None:    # never overwrite an existing skill
                continue
            skill = skills.create(name, desc, body, category="draft",
                                  tags=["draft", "consolidator"])
            # The service's disable hook persists the choice to config
            # (skills.disabled) so the draft stays a proposal across restarts.
            if self._disable_skill is not None:
                self._disable_skill(skill.name)
            else:
                skills.set_enabled(skill.name, False)
            drafted += 1
        return drafted

    def _step_skill_usage(self) -> int:
        """Skill usage feeds semantic importance (design §5 L4): facts related to
        a skill the user actually exercises get reinforced (frequency + recency —
        the decay score's counterweights), so what the user *does* keeps the
        matching part of memory alive."""
        usage = self._skill_usage() if self._skill_usage else {}
        reinforced = 0
        for name, count in (usage or {}).items():
            if not name or int(count or 0) <= 0:
                continue
            for item in self.store.search_items(str(name).replace("-", " "), limit=3):
                self.store.reinforce(item["id"])
                reinforced += 1
        return reinforced

    def _step_compact_core(self) -> int:
        """Densify any core block over 80% budget (design: compact at 80%).
        The model's output only replaces the block when it verifiably fits and
        passes screening — otherwise the block is left untouched."""
        compacted = 0
        for block in ("user", "agent"):
            if self.core.usage(block)["pct"] <= 80:
                continue
            entries = self.store.core_entries(block)
            if len(entries) < 2:
                continue
            budget = int(BLOCK_BUDGET_CHARS[block] * 0.7)
            user = "ENTRIES:\n" + "\n".join(f"- {e['text']}" for e in entries)
            data = self.writer._call_json(
                _COMPACT_SYSTEM.replace("{budget}", str(budget)), user)
            if not isinstance(data, list) or not data:
                continue
            new = [" ".join(str(t or "").strip().split()) for t in data]
            new = [t for t in new if t and not scan_text(t).flagged]
            if not new or sum(len(t) + 3 for t in new) > budget or len(new) >= len(entries):
                continue    # not actually denser / doesn't fit → keep the original
            for e in entries:
                self.store.core_remove(e["id"])
            for t in new:
                self.store.core_add(block, t)
            self.core._write_mirror(block)
            compacted += 1
        return compacted

    def _step_environment(self) -> int:
        self.environment.get(refresh=True)
        return 1


class ConsolidationScheduler:
    """Sleep-time triggers: idle (no turns for N minutes) and a daily wall-clock
    time. One daemon thread, 30 s tick, never crashes the app. The Settings →
    Memory section exposes the knobs; ``memory.consolidate.background: false``
    turns the thread off entirely (manual runs still work)."""

    #: Idle runs repeat no more often than this, so an idle afternoon doesn't
    #: burn the model budget on back-to-back passes.
    MIN_GAP_S = 6 * 3600

    def __init__(self, consolidator: Consolidator,
                 idle_minutes: float = 20.0, daily_at: str = "03:30"):
        self.consolidator = consolidator
        self.idle_minutes = float(idle_minutes)
        self.daily_at = str(daily_at or "").strip()
        self._last_activity = time.time()
        # Pace from boot: the first idle-triggered run waits a full gap, so app
        # start never causes a model-burning pass by itself (daily still covers
        # the nightly one, and manual runs are always available).
        self._last_run = time.time()
        # If today's daily time is already past at boot, don't fire it late —
        # the daily trigger only fires when the clock crosses it while running.
        self._last_daily_date: Optional[str] = None
        if self.daily_at:
            try:
                hh, mm = (int(x) for x in self.daily_at.split(":", 1))
                now = datetime.now()
                if (now.hour, now.minute) >= (hh, mm):
                    self._last_daily_date = now.strftime("%Y-%m-%d")
            except ValueError:
                pass
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # -- signals -----------------------------------------------------------------

    def note_activity(self) -> None:
        """Called on every turn — resets the idle clock."""
        self._last_activity = time.time()

    def note_run(self) -> None:
        """Any run (incl. manual) resets the pacing so triggers don't double up."""
        self._last_run = time.time()

    # -- trigger logic (pure, testable) --------------------------------------------

    def due(self, now: Optional[float] = None,
            local_now: Optional[datetime] = None) -> Optional[str]:
        """The trigger reason if a run is due right now, else None."""
        now = time.time() if now is None else now
        local_now = local_now or datetime.now()
        if self.daily_at:
            try:
                hh, mm = (int(x) for x in self.daily_at.split(":", 1))
                today = local_now.strftime("%Y-%m-%d")
                past_time = (local_now.hour, local_now.minute) >= (hh, mm)
                if past_time and self._last_daily_date != today:
                    return "daily"
            except ValueError:
                pass
        if (self.idle_minutes > 0
                and now - self._last_activity >= self.idle_minutes * 60
                and now - self._last_run >= self.MIN_GAP_S):
            return "idle"
        return None

    def mark_fired(self, reason: str, local_now: Optional[datetime] = None) -> None:
        self.note_run()
        if reason == "daily":
            self._last_daily_date = (local_now or datetime.now()).strftime("%Y-%m-%d")

    # -- thread --------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="engram-consolidator",
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(30):
            reason = self.due()
            if reason is None:
                continue
            self.mark_fired(reason)
            try:
                report = self.consolidator.run(reason=reason)
                logger.info("[engram] %s consolidation: %s", reason, report)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[engram] scheduled consolidation failed: %s", exc)
