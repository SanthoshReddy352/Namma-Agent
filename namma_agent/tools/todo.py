"""The agent's live TODO plan for the chat UI.

One tool — ``update_todos`` — REPLACES the session's whole todo list each call
(the proven full-state pattern: no id bookkeeping for the model to get wrong).
Each todo is ``{text, status, subtasks?}``; a subtask is ``{text, status}``. The
list is kept per session (in memory) and every update is pushed to the browser
as a ``todo_updated`` event, so the panel above the message bar reflects the
plan and its progress live. The server's session-history endpoint reads
:func:`todos_for` so a reload restores the panel.
"""
from __future__ import annotations

import threading

from namma_agent.core.tools import ToolResult

_STATUSES = ("pending", "in_progress", "done")
_MAX_TODOS = 50
_MAX_SUBTASKS = 20
_MAX_TEXT = 300

# session_id -> the session's current todo list. In-memory by design: a plan is
# working state for the running app, not durable memory.
_TODOS: dict[str, list] = {}
_LOCK = threading.Lock()


def todos_for(session_id: str) -> list:
    """The session's current todo list (empty when it has none)."""
    with _LOCK:
        return list(_TODOS.get(session_id or "", []))


def _clean_status(value) -> str:
    s = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if s in ("complete", "completed", "finished"):
        s = "done"
    if s in ("active", "current", "doing", "started"):
        s = "in_progress"
    return s if s in _STATUSES else "pending"


def _clean_items(items, *, depth: int = 0) -> list:
    """Normalize the model's list: drop empty entries, coerce statuses, cap sizes.
    One level of subtasks only — deeper nesting is flattened away."""
    out: list = []
    limit = _MAX_TODOS if depth == 0 else _MAX_SUBTASKS
    for raw in items if isinstance(items, list) else []:
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or raw.get("title") or "").strip()[:_MAX_TEXT]
        if not text:
            continue
        item = {"text": text, "status": _clean_status(raw.get("status"))}
        if depth == 0:
            subs = _clean_items(raw.get("subtasks") or [], depth=1)
            if subs:
                item["subtasks"] = subs
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _render(todos: list) -> str:
    """Compact checklist echoed back to the model so it always sees the state it
    just wrote (and can resend it faithfully on the next update)."""
    mark = {"done": "[x]", "in_progress": "[>]", "pending": "[ ]"}
    lines = []
    for t in todos:
        lines.append(f"{mark[t['status']]} {t['text']}")
        for s in t.get("subtasks") or []:
            lines.append(f"    {mark[s['status']]} {s['text']}")
    return "\n".join(lines)


def register(registry) -> None:
    def update_todos(args: dict) -> ToolResult:
        from namma_agent.core.interactive import emit_event, get_current_session

        if "todos" not in args:
            return ToolResult(ok=False, content="", error="'todos' is required (a list).")
        todos = _clean_items(args.get("todos"))
        sid = get_current_session() or ""
        with _LOCK:
            if todos:
                _TODOS[sid] = todos
            else:
                _TODOS.pop(sid, None)
        emit_event("todo_updated", {"session_id": sid or None, "todos": todos})
        if not todos:
            return ToolResult(ok=True, content="Todo list cleared.", data={"todos": []})
        done = sum(1 for t in todos if t["status"] == "done")
        return ToolResult(
            ok=True,
            content=f"Todo list updated — {done}/{len(todos)} done:\n{_render(todos)}",
            data={"todos": todos},
        )

    registry.register(
        "update_todos",
        "Show/refresh your live TODO plan in the chat UI. REPLACES the whole list each "
        "call, so always resend every todo with its current status. Statuses: pending | "
        "in_progress (keep exactly one) | done. A todo may carry 'subtasks' "
        "[{text, status}] — add them the moment a step splits into sub-steps, and keep "
        "their statuses updated too. Call this BEFORE starting a multi-step task (the "
        "plan), and again AFTER EACH completed step (the progress). Pass an empty list "
        "to clear the plan.",
        {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The COMPLETE todo list, in order.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Short imperative step, e.g. 'Scan the config files'."},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                            "subtasks": {
                                "type": "array",
                                "description": "Optional sub-steps of this todo.",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "text": {"type": "string"},
                                        "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                                    },
                                    "required": ["text"],
                                },
                            },
                        },
                        "required": ["text"],
                    },
                },
            },
            "required": ["todos"],
        },
        update_todos,
    )
