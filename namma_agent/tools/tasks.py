"""Task tools — a persisted to-do list with status. Ports v1 task_manager.

  add_task(title, notes?)  list_tasks(status?)  complete_task(id)  remove_task(id)

Backed by ``data/tasks.json`` (path overridable via ``tasks.store_path``).
"""
from __future__ import annotations

import time

from namma_agent.core.tools import ToolRegistry, ToolResult
from namma_agent.tools import _jsonstore as store

_FILE = "tasks.json"


def _path():
    return store.store_path("tasks", _FILE)


def _add(args: dict) -> ToolResult:
    title = (args.get("title") or "").strip()
    if not title:
        return ToolResult(ok=False, content="", error="a task title is required")
    items = store.load(_path())
    item = {"id": store.next_id(items), "title": title,
            "notes": (args.get("notes") or "").strip(),
            "status": "open", "created_at": int(time.time())}
    items.append(item)
    store.save(_path(), items)
    return ToolResult(ok=True, content=f"Task #{item['id']} added: {title}", data=item)


def _list(args: dict) -> ToolResult:
    status = (args.get("status") or "").strip().lower()
    items = store.load(_path())
    if status in ("open", "done"):
        items = [t for t in items if t.get("status") == status]
    if not items:
        return ToolResult(ok=True, content="No tasks.")
    lines = ["Tasks:"]
    for t in items:
        mark = "x" if t.get("status") == "done" else " "
        notes = f" — {t['notes']}" if t.get("notes") else ""
        lines.append(f"[{mark}] #{t['id']}: {t['title']}{notes}")
    return ToolResult(ok=True, content="\n".join(lines), data=items)


def _complete(args: dict) -> ToolResult:
    try:
        rid = int(args.get("id"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="a numeric task id is required")
    items = store.load(_path())
    task = store.find(items, rid)
    if task is None:
        return ToolResult(ok=False, content="", error=f"no task with id {rid}")
    task["status"] = "done"
    task["completed_at"] = int(time.time())
    store.save(_path(), items)
    return ToolResult(ok=True, content=f"Completed task #{rid}: {task['title']}")


def _remove(args: dict) -> ToolResult:
    try:
        rid = int(args.get("id"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="a numeric task id is required")
    items = store.load(_path())
    kept = [t for t in items if int(t.get("id", 0)) != rid]
    if len(kept) == len(items):
        return ToolResult(ok=False, content="", error=f"no task with id {rid}")
    store.save(_path(), kept)
    return ToolResult(ok=True, content=f"Removed task #{rid}.")


def register(registry: ToolRegistry) -> None:
    registry.register("add_task", "Add a to-do task.", {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "the task"},
            "notes": {"type": "string", "description": "optional details"},
        },
        "required": ["title"],
    }, _add)

    registry.register("list_tasks", "List tasks, optionally filtered by status.", {
        "type": "object",
        "properties": {"status": {"type": "string", "enum": ["open", "done"],
                                  "description": "filter (default: all)"}},
    }, _list)

    registry.register("complete_task", "Mark a task as done by id.", {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "task id"}},
        "required": ["id"],
    }, _complete)

    registry.register("remove_task", "Delete a task by id.", {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "task id"}},
        "required": ["id"],
    }, _remove, destructive=True)
