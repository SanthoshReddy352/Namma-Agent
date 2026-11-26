"""Delegation runtime (PROGRESS.md Phase 3 — Hermes-style contract).

``delegate_task`` used to be a helper: one blocking child, no context, no fan-out,
no depth or concurrency cap, and child events went nowhere. ``background_task``
ran on unbounded threads and never reported back into the chat. This module is
the runtime both now use.

**Contract.** A delegation is ``goal`` + optional ``context`` (what the parent
already knows), optional ``tasks[]`` (fan-out: each item is its own child), a
``role`` (``leaf`` or ``orchestrator``), a toolset / skill selection and a
``budget`` (``max_steps``, ``max_tokens``). Every child returns
``{status, summary, exit_reason, truncated}``:

* ``status`` — ``completed`` | ``partial`` (hit its step or token budget) |
  ``failed`` | ``cancelled`` (and ``interrupted`` after an app restart);
* ``exit_reason`` — ``completed`` | ``step_limit`` | ``token_budget`` |
  ``cancelled`` | ``error``;
* ``truncated`` — the summary was clipped or the child stopped early.

**Limits.** At most ``delegation.concurrency`` (default 3) children of one call
run at once; the rest wait their turn. Depth: a leaf child (depth 1) can't
delegate; an orchestrator child may fan out once more, and its children (depth
2) are always leaves — so the tree is bounded at 1 + 3 + 9. Background tasks run
on a bounded pool (``delegation.background_workers``, default 2); extra tasks
queue.

**Cancellation tree.** Each run has its own cancel flag and inherits its
parent's Stop: cancelling a run cancels its whole subtree, and the parent turn's
Stop button reaches every running child.

**Safety.** A child's tool surface never contains destructive tools (it has no
approval channel) and never the background tools; only orchestrators get
``delegate_task``. Delegation is refused for untrusted senders.

**Visibility.** Runs are persisted (``subagent_runs`` table) and every state
change is published as a ``subagent`` event (the WebSocket forwards it to the
UI's sub-agent panel). A finished background task also posts its report into
the chat it was started from.
"""
from __future__ import annotations

import contextvars
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from namma_agent.core.logger import logger
from namma_agent.core.tools import ToolRegistry

LEAF, ORCHESTRATOR = "leaf", "orchestrator"
#: Depth of a top-level child, and the deepest an orchestrator's children go.
MAX_DEPTH = 2
DEFAULT_CONCURRENCY = 3
DEFAULT_BACKGROUND_WORKERS = 2
#: Step cap for a child when neither the parent nor the budget sets one.
DEFAULT_STEPS = 25
DEFAULT_SUMMARY_CHARS = 6000
#: Most children one delegate_task call may ask for.
MAX_TASKS = 8

ACTIVE = ("queued", "running")
TERMINAL = ("completed", "partial", "failed", "cancelled", "interrupted")

#: Tools a child never gets (no recursion through the background path, no
#: self-management); ``delegate_task`` is re-added for orchestrators only.
EXCLUDED = frozenset({"delegate_task", "background_task", "check_background_task",
                      "cancel_background_task"})

#: The run executing on this thread — how an orchestrator child's delegate_task
#: call finds its parent (and so its depth).
_CURRENT_RUN: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "namma_current_subagent_run", default=None)


def current_run_id() -> Optional[str]:
    return _CURRENT_RUN.get()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def render_results(results: list[dict]) -> str:
    """Model-facing text for a delegation: a lone completed child is just its
    summary; otherwise each child's contract fields, then its summary."""
    if len(results) == 1 and results[0]["status"] == "completed":
        return results[0]["summary"] or "(no findings)"
    blocks = []
    for r in results:
        head = (f"[{r['name']}] status={r['status']} exit_reason={r['exit_reason']} "
                f"truncated={str(r['truncated']).lower()}")
        body = r["summary"] or (f"error: {r['error']}" if r.get("error") else "(no findings)")
        blocks.append(f"{head}\n{body}")
    return "\n\n".join(blocks)


class SubagentPersona:
    """The child's system prompt: its role, ONLY its own tools, and any skills
    the parent selected — not the main assistant's long preamble, which names
    tools the child doesn't have."""

    def __init__(self, parent_persona: Any, *, role: str, depth: int,
                 tool_names: list[str], skills_text: str = "", can_delegate: bool = False):
        self.id = getattr(parent_persona, "id", "core")
        self.name = getattr(parent_persona, "name", "the assistant")
        self.role, self.depth = role, depth
        self.tool_names = tool_names
        self.skills_text = skills_text
        self.can_delegate = can_delegate

    def system_prompt(self, **_ignored: Any) -> str:
        from namma_agent.core.persona import _TEMPORAL_POLICY

        tools = ", ".join(self.tool_names) or "(none — answer from what you know)"
        parts = [
            f"You are a focused sub-agent working for {self.name} (role: {self.role}, "
            f"depth {self.depth}). You cannot talk to the user and must not ask "
            "questions. Use your tools to actually complete the GOAL in the user "
            "message, then reply with a concise report for the main agent: what you "
            "found or did, with sources, paths or numbers. Structure it in markdown: "
            "'## ' headings when it covers more than one point, bullets for facts, a "
            "table for any comparison, and a final '## Sources' list of the URLs or "
            "paths you actually used. If you couldn't finish, say exactly what is "
            "missing.",
            f"YOUR TOOLS (the only ones you have): {tools}",
        ]
        if self.can_delegate:
            parts.append(
                "You are an ORCHESTRATOR: you may split independent parts of the goal "
                "with delegate_task (pass tasks[] to run up to 3 in parallel, each with "
                "the context it needs). Your sub-agents are leaves and can't delegate "
                "further. Merge their results into one report.")
        if self.skills_text:
            parts.append("SKILLS (procedures selected for you — follow them):\n"
                         + self.skills_text)
        parts.append(_TEMPORAL_POLICY)
        parts.append("Format: plain prose or short bullet lists; no headings.")
        return "\n\n".join(parts)


class _Unscoped:
    """The turn's provider without a per-model ``tool_allow`` (a child's registry
    is already its scope; the main agent's allow-list could leave it toolless)."""

    tool_allow: list = []

    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)


class DelegationManager:
    def __init__(self, *, db, registry: ToolRegistry, parent_agent,
                 resolve_provider: Callable[[], Any],
                 skills_getter: Optional[Callable[[], Any]] = None,
                 get_comms: Optional[Callable[[], Any]] = None,
                 publish: Optional[Callable[[str, dict], None]] = None,
                 config: Optional[dict] = None,
                 research_tools: tuple = ()):
        self.db = db
        self.registry = registry
        self.parent_agent = parent_agent
        self.resolve_provider = resolve_provider
        self.skills_getter = skills_getter
        self.get_comms = get_comms
        self.publish = publish
        self.config = config if config is not None else {}
        self.research_tools = tuple(research_tools)
        self._runs: dict[str, dict] = {}       # live state of runs started here
        self._lock = threading.RLock()
        self._bg_pool: Optional[ThreadPoolExecutor] = None
        try:
            n = db.interrupt_unfinished_runs()
            if n:
                logger.info("[delegation] marked %d unfinished run(s) as interrupted", n)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[delegation] interrupt sweep failed: %s", exc)

    # -- settings (read live, so Settings edits apply without a restart) ------

    def _setting(self, key: str, default: int) -> int:
        try:
            value = int((self.config.get("delegation") or {}).get(key, default))
        except (TypeError, ValueError):
            value = default
        return max(1, value)

    @property
    def concurrency(self) -> int:
        return self._setting("concurrency", DEFAULT_CONCURRENCY)

    @property
    def background_workers(self) -> int:
        return self._setting("background_workers", DEFAULT_BACKGROUND_WORKERS)

    @property
    def summary_chars(self) -> int:
        return self._setting("summary_chars", DEFAULT_SUMMARY_CHARS)

    # -- tool surface ----------------------------------------------------------

    def eligible_tools(self) -> list:
        """Every tool a child may ever see: enabled, available, non-destructive,
        not a delegation/background tool."""
        return [t for t in self.registry.all()
                if t.enabled and not t.destructive and t.name not in EXCLUDED
                and not t.unavailable_reason()]

    def valid_toolsets(self) -> list[str]:
        return sorted({(t.category or "general") for t in self.eligible_tools()})

    def sub_registry(self, toolsets: Optional[list] = None, *, role: str = LEAF,
                     depth: int = 1) -> ToolRegistry:
        """The child's tools: the requested toolsets / tool names, or the
        read-only research set. Unknown names raise ``ValueError`` listing the
        valid toolsets. Orchestrators below the depth cap also get delegate_task."""
        reg = ToolRegistry()
        wanted = {str(t).strip() for t in (toolsets or []) if str(t).strip()}
        eligible = self.eligible_tools()
        if wanted:
            known = {t.name for t in eligible} | {(t.category or "general") for t in eligible}
            unknown = sorted(wanted - known)
            if unknown:
                raise ValueError(
                    f"unknown toolset(s) {', '.join(unknown)}. Valid toolsets: "
                    f"{', '.join(self.valid_toolsets())} (or individual non-destructive "
                    "tool names)")
            for tool in eligible:
                if tool.name in wanted or (tool.category or "general") in wanted:
                    reg.add(tool)
        else:
            by_name = {t.name: t for t in eligible}
            for name in self.research_tools:
                if name in by_name:
                    reg.add(by_name[name])
        if role == ORCHESTRATOR and depth < MAX_DEPTH:
            reg.add(self.registry.get("delegate_task") or self._own_delegate_tool())
        return reg

    def _own_delegate_tool(self):
        """A delegate_task for orchestrator children when the parent registry has
        none (a standalone manager, e.g. the eval harness)."""
        from namma_agent.core.tools import Tool, ToolResult

        def handler(args: dict) -> ToolResult:
            try:
                results = self.delegate(args)
            except ValueError as exc:
                return ToolResult(ok=False, content="", error=str(exc))
            return ToolResult(ok=True, content=render_results(results),
                              data={"results": results})

        return Tool(name="delegate_task",
                    description="Split work across leaf sub-agents: goal, context, tasks[].",
                    parameters={"type": "object", "properties": {
                        "goal": {"type": "string"}, "context": {"type": "string"},
                        "tasks": {"type": "array", "items": {"type": "string"}}}},
                    handler=handler, category="agent")

    # -- specs -------------------------------------------------------------------

    def normalize(self, args: dict, *, depth: int) -> list[dict]:
        """``delegate_task`` arguments → one spec per child. ``task`` is accepted
        as an alias of ``goal``; ``tasks`` items (strings or objects) inherit the
        top-level context, toolsets, skills, role and budget unless they override
        them. Raises ``ValueError`` on bad input."""
        args = args or {}
        base = {
            "goal": str(args.get("goal") or args.get("task") or "").strip(),
            "context": str(args.get("context") or "").strip(),
            "toolsets": args.get("toolsets") or [],
            "skills": args.get("skills") or [],
            "role": str(args.get("role") or LEAF).strip().lower(),
            "budget": args.get("budget") or {},
            "name": str(args.get("name") or "").strip(),
        }
        raw_tasks = args.get("tasks") or []
        if not isinstance(raw_tasks, list):
            raise ValueError("'tasks' must be a list")
        specs = []
        for item in raw_tasks:
            spec = dict(base, name="")
            if isinstance(item, str):
                spec["goal"] = item.strip()
            elif isinstance(item, dict):
                for key in ("goal", "context", "toolsets", "skills", "role", "budget", "name"):
                    if item.get(key) not in (None, "", []):
                        spec[key] = item[key]
                if not item.get("goal") and item.get("task"):
                    spec["goal"] = item["task"]
                # A task's own context ADDS to the shared one.
                if item.get("context") and base["context"]:
                    spec["context"] = f"{base['context']}\n\n{item['context']}"
            else:
                raise ValueError("each item in 'tasks' must be a string or an object")
            specs.append(spec)
        if not specs:
            specs = [base]
        if len(specs) > MAX_TASKS:
            raise ValueError(f"at most {MAX_TASKS} tasks per delegation (got {len(specs)})")
        for spec in specs:
            spec["goal"] = str(spec.get("goal") or "").strip()
            if not spec["goal"]:
                raise ValueError("every task needs a goal ('goal' or 'task')")
            if spec["role"] not in (LEAF, ORCHESTRATOR):
                raise ValueError("role must be 'leaf' or 'orchestrator'")
            if depth >= MAX_DEPTH:
                spec["role"] = LEAF          # the deepest level is always a leaf
            if not isinstance(spec["toolsets"], list) or not isinstance(spec["skills"], list):
                raise ValueError("'toolsets' and 'skills' must be lists")
            if not isinstance(spec["budget"], dict):
                raise ValueError("'budget' must be an object like {\"max_steps\": 10}")
            spec["name"] = (spec["name"] or spec["goal"])[:60]
        return specs

    def _skills_text(self, names: list) -> str:
        if not names:
            return ""
        store = self.skills_getter() if self.skills_getter else None
        if store is None:
            raise ValueError("skills are not available in this setup")
        out, missing = [], []
        for n in names:
            skill = store.get(str(n))
            if skill is None:
                missing.append(str(n))
            else:
                out.append(f"## {skill.name}\n{skill.body.strip()}")
        if missing:
            raise ValueError(f"unknown skill(s): {', '.join(missing)}")
        return "\n\n".join(out)

    # -- runs ------------------------------------------------------------------

    def _new_run(self, spec: dict, *, kind: str, depth: int, parent: Optional[dict],
                 session_id: str) -> dict:
        run = {
            "id": uuid.uuid4().hex[:10],
            "parent_id": parent["id"] if parent else None,
            "root_id": (parent.get("root_id") or parent["id"]) if parent else None,
            "kind": kind, "role": spec["role"], "depth": depth,
            "name": spec["name"], "goal": spec["goal"], "status": "queued",
            "exit_reason": None, "summary": "", "truncated": False, "error": "",
            "session_id": session_id or None, "child_session_id": None,
            "tools_used": [], "steps": 0, "current_tool": "",
            "meta": {"toolsets": spec["toolsets"], "skills": spec["skills"],
                     "budget": spec["budget"], "context": spec["context"][:2000]},
            "created_at": _now(), "started_at": None, "finished_at": None,
            "_cancel": threading.Event(), "_spec": spec,
        }
        if run["root_id"] is None:
            run["root_id"] = run["id"]
        with self._lock:
            self._runs[run["id"]] = run
        self._persist(run)
        self._emit(run)
        return run

    @staticmethod
    def public(run: dict) -> dict:
        return {k: v for k, v in run.items() if not k.startswith("_")}

    def _persist(self, run: dict) -> None:
        try:
            self.db.save_run(self.public(run))
        except Exception as exc:  # noqa: BLE001 — bookkeeping must not break a run
            logger.debug("[delegation] persist %s failed: %s", run["id"], exc)

    def _emit(self, run: dict, **extra: Any) -> None:
        if self.publish is None:
            return
        try:
            self.publish("subagent", {"session_id": run.get("session_id"),
                                      "run": self.public(run), **extra})
        except Exception as exc:  # noqa: BLE001
            logger.debug("[delegation] publish failed: %s", exc)

    TRAIL_MAX = 40          # steps kept per run for the UI's live trail

    @staticmethod
    def _preview(value: Any, cap: int = 160) -> str:
        """One-line, capped preview of tool arguments/results for the trail."""
        try:
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
        text = " ".join(str(text).split())
        return text if len(text) <= cap else text[: cap - 1] + "…"

    def _child_event(self, run: dict, event: str, payload: dict) -> None:
        """Fold the child agent's own events into its run (live progress), and
        keep a short trail of its steps (tool, argument preview, outcome) so the
        UI can show what each sub-agent is actually doing."""
        trail = run.setdefault("meta", {}).setdefault("trail", [])
        if event == "tool_started":
            run["current_tool"] = payload.get("tool") or ""
            run["steps"] = int(run.get("steps") or 0) + 1
            trail.append({"tool": run["current_tool"], "args": self._preview(payload.get("args") or {}),
                          "status": "running", "at": _now()})
            del trail[:-self.TRAIL_MAX]
            self._emit(run)
        elif event == "tool_finished":
            run["current_tool"] = ""
            tool = payload.get("tool") or ""
            for step in reversed(trail):
                if step.get("status") == "running" and step.get("tool") == tool:
                    step["status"] = "ok" if payload.get("ok", True) else "error"
                    step["result"] = self._preview(payload.get("summary") or "", 200)
                    break
            self._persist(run)
            self._emit(run)          # the UI would otherwise show a stale "running X"

    def _step_limit(self, spec: dict) -> int:
        parent_limit = int(getattr(self.parent_agent, "tool_loop_limit", 0) or 0)
        limit = parent_limit if parent_limit > 0 else DEFAULT_STEPS
        try:
            wanted = int((spec.get("budget") or {}).get("max_steps") or 0)
        except (TypeError, ValueError):
            wanted = 0
        return min(limit, wanted) if wanted > 0 else limit

    def _execute(self, run: dict, provider: Any, registry: ToolRegistry,
                 parent_cancel: Optional[Callable[[], bool]]) -> None:
        """Run one child to the end (on a worker thread)."""
        from namma_agent.core.agent import Agent  # local: avoids an import cycle

        spec = run["_spec"]
        cancel: threading.Event = run["_cancel"]
        if cancel.is_set() or (parent_cancel is not None and parent_cancel()):
            self._finish(run, "cancelled", "cancelled", "")
            return
        _CURRENT_RUN.set(run["id"])
        run.update(status="running", started_at=_now())
        try:
            if getattr(provider, "tool_allow", None):
                provider = _Unscoped(provider)
            persona = SubagentPersona(
                getattr(self.parent_agent, "persona", None), role=spec["role"],
                depth=run["depth"], tool_names=registry.names(),
                skills_text=spec.get("_skills_text", ""),
                can_delegate="delegate_task" in registry)
            child = Agent(provider, registry, self.db, persona=persona,
                          tool_loop_limit=self._step_limit(spec), max_history_turns=4,
                          compact_history=False, verify_after_writes=False)
            child.usage_kind = "delegate"
            try:
                child.turn_token_budget = max(0, int(spec["budget"].get("max_tokens") or 0))
            except (TypeError, ValueError):
                child.turn_token_budget = 0
            run["child_session_id"] = self.db.create_session_in(
                kind="subagent", persona=persona.id)
            self._persist(run)
            self._emit(run)
            message = f"GOAL: {spec['goal']}"
            if spec.get("context"):
                message += f"\n\nCONTEXT FROM THE MAIN AGENT:\n{spec['context']}"
            # The exact brief the sub-agent received, for the UI.
            run["meta"]["prompt"] = message[:6000]
            run["meta"]["step_limit"] = self._step_limit(spec)
            result = child.process_turn(
                message, session_id=run["child_session_id"],
                should_cancel=lambda: cancel.is_set() or bool(parent_cancel and parent_cancel()),
                emit=lambda e, p: self._child_event(run, e, p))
            run["tools_used"] = list(result.tools_used)
            reason = result.exit_reason or "completed"
            status = {"completed": "completed", "cancelled": "cancelled"}.get(reason, "partial")
            self._finish(run, status, reason, result.content or "")
        except Exception as exc:  # noqa: BLE001 — a child failure is a result, not a crash
            logger.warning("[delegation] run %s failed: %s", run["id"], exc)
            self._finish(run, "failed", "error", "", error=str(exc))

    def _finish(self, run: dict, status: str, exit_reason: str, summary: str,
                error: str = "") -> None:
        cap = self.summary_chars
        clipped = len(summary) > cap
        if clipped:
            summary = summary[:cap].rstrip() + "\n…[summary clipped]"
        run.update(status=status, exit_reason=exit_reason, summary=summary,
                   truncated=clipped or status == "partial", error=error,
                   current_tool="", finished_at=_now())
        self._persist(run)
        self._emit(run)

    @staticmethod
    def result(run: dict) -> dict:
        out = {"id": run["id"], "name": run["name"], "status": run["status"],
               "summary": run["summary"], "exit_reason": run["exit_reason"],
               "truncated": bool(run["truncated"])}
        if run.get("error"):
            out["error"] = run["error"]
        return out

    def _prepare(self, args: dict, *, kind: str) -> tuple[list[dict], int, Optional[dict], str]:
        """Validate and stage: specs, depth, parent run, parent chat."""
        from namma_agent.core.interactive import get_current_session

        parent = None
        parent_id = current_run_id()
        if parent_id:
            with self._lock:
                parent = self._runs.get(parent_id)
        depth = (int(parent["depth"]) + 1) if parent else 1
        if parent is not None and (parent["role"] != ORCHESTRATOR or depth > MAX_DEPTH):
            raise ValueError("delegation depth limit reached — finish this part yourself")
        specs = self.normalize(args, depth=depth)
        for spec in specs:
            spec["_skills_text"] = self._skills_text(spec["skills"])
            spec["_registry"] = self.sub_registry(spec["toolsets"], role=spec["role"],
                                                  depth=depth)
        session = (parent or {}).get("session_id") or get_current_session() or ""
        return specs, depth, parent, session

    def delegate(self, args: dict) -> list[dict]:
        """Run the children of one ``delegate_task`` call (blocking) and return
        their results in task order. At most :attr:`concurrency` run at once."""
        from namma_agent.core.interactive import get_current_cancel

        specs, depth, parent, session = self._prepare(args, kind="delegate")
        provider = self.resolve_provider()          # on the TURN's thread (contextvar)
        parent_cancel = get_current_cancel()
        runs = [self._new_run(s, kind="delegate", depth=depth, parent=parent,
                              session_id=session) for s in specs]
        workers = min(self.concurrency, len(runs))
        with ThreadPoolExecutor(max_workers=workers,
                                thread_name_prefix="subagent") as pool:
            futures = [pool.submit(contextvars.copy_context().run, self._execute, run,
                                   provider, run["_spec"]["_registry"], parent_cancel)
                       for run in runs]
            for f in futures:
                f.result()
        return [self.result(r) for r in runs]

    # -- background tasks ----------------------------------------------------------

    def _pool(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._bg_pool is None:
                self._bg_pool = ThreadPoolExecutor(max_workers=self.background_workers,
                                                   thread_name_prefix="bg-task")
            return self._bg_pool

    def start_background(self, args: dict) -> dict:
        """Queue one background run on the bounded pool; returns its public row.
        When it finishes, the result is posted into the chat it came from and
        pushed over the user's messaging channel."""
        specs, depth, parent, session = self._prepare(args, kind="background")
        if len(specs) != 1:
            raise ValueError("background_task runs one task; use delegate_task for tasks[]")
        provider = self.resolve_provider()
        run = self._new_run(specs[0], kind="background", depth=depth, parent=parent,
                            session_id=session)

        def _work() -> None:
            self._execute(run, provider, run["_spec"]["_registry"], None)
            self._report(run)

        self._pool().submit(contextvars.copy_context().run, _work)
        return self.public(run)

    def _report(self, run: dict) -> None:
        name = run["name"]
        if run["status"] in ("completed", "partial"):
            text = (f"Background task “{name}” finished"
                    f"{' (partial)' if run['status'] == 'partial' else ''}:\n\n{run['summary']}")
        elif run["status"] == "cancelled":
            text = f"Background task “{name}” was cancelled."
        else:
            text = f"Background task “{name}” failed: {run.get('error') or run['exit_reason']}"
        report = None
        if run.get("session_id"):
            try:
                self.db.add_turn(run["session_id"], "assistant", text,
                                 meta={"background_run": run["id"]})
                report = text
            except Exception as exc:  # noqa: BLE001
                logger.debug("[delegation] report into chat failed: %s", exc)
        self._emit(run, report=report)
        try:
            comms = self.get_comms() if self.get_comms else None
            if comms is not None and getattr(comms, "any_available", False):
                icon = "✅" if run["status"] in ("completed", "partial") else "❌"
                comms.send(f"{icon} {text[:900]}")
        except Exception:  # noqa: BLE001 — notification is best-effort
            pass

    # -- control & queries ---------------------------------------------------------

    def cancel(self, run_id: str) -> dict:
        """Cancel a run and its whole subtree. Queued runs end immediately;
        running ones stop at their next check (within ~0.2 s of a model call)."""
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                stored = self.db.get_run(run_id)
                if stored is None:
                    return {"ok": False, "error": f"no run {run_id!r}"}
                return {"ok": False, "error": f"run {run_id} is {stored['status']} "
                                              "(not running in this process)"}
            tree = [run]
            frontier = [run_id]
            while frontier:
                pid = frontier.pop()
                kids = [r for r in self._runs.values() if r.get("parent_id") == pid]
                tree.extend(kids)
                frontier.extend(k["id"] for k in kids)
        cancelled = []
        for r in tree:
            if r["status"] in TERMINAL:
                continue
            r["_cancel"].set()
            cancelled.append(r["id"])
            if r["status"] == "queued":
                self._finish(r, "cancelled", "cancelled", "")
        return {"ok": True, "cancelled": cancelled}

    def get(self, run_id: str) -> Optional[dict]:
        with self._lock:
            live = self._runs.get(run_id)
        if live is not None:
            return self.public(live)
        return self.db.get_run(run_id)

    def list(self, session_id: str = "", kind: str = "", limit: int = 100) -> list[dict]:
        rows = self.db.list_runs(session_id=session_id, kind=kind, limit=limit)
        with self._lock:
            live = {rid: self.public(r) for rid, r in self._runs.items()}
        return [live.get(r["id"], r) for r in rows]

    def active_count(self) -> int:
        with self._lock:
            return sum(1 for r in self._runs.values() if r["status"] in ACTIVE)

    def import_legacy_background(self, entries: list[dict]) -> int:
        """One-time import of the old JSON background-task store into the runs
        table (status ``done``→``completed``; a task left ``running`` →
        ``interrupted``)."""
        n = 0
        for e in entries or []:
            rid = str(e.get("id") or "")
            if not rid or self.db.get_run(rid) is not None:
                continue
            status = {"done": "completed", "running": "interrupted"}.get(
                e.get("status"), e.get("status") or "interrupted")
            started = e.get("started_at")
            ts = (datetime.fromtimestamp(float(started), timezone.utc).isoformat()
                  if isinstance(started, (int, float)) else _now())
            self.db.save_run({
                "id": rid, "root_id": rid, "kind": "background", "role": LEAF, "depth": 1,
                "name": e.get("name") or "", "goal": e.get("task") or e.get("name") or "",
                "status": status, "exit_reason": "interrupted" if status == "interrupted"
                else ("completed" if status == "completed" else "error"),
                "summary": e.get("result") or "",
                "error": e.get("error") or ("the app restarted while this task was running"
                                            if status == "interrupted" else ""),
                "created_at": ts, "started_at": ts, "finished_at": ts,
            })
            n += 1
        return n

    def shutdown(self) -> None:
        with self._lock:
            pool, self._bg_pool = self._bg_pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)


def wait_for(manager: DelegationManager, run_id: str, timeout: float = 5.0) -> dict:
    """Test helper: poll until a run reaches a terminal status."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        row = manager.get(run_id) or {}
        if row.get("status") in TERMINAL:
            return row
        time.sleep(0.02)
    raise TimeoutError(f"run {run_id} did not finish")
