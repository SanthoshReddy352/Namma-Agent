"""Goal tools — track goals with a 0-100 progress value. Ports v1 goals.

  add_goal(title, target?)  list_goals()  update_goal_progress(id, progress)  remove_goal(id)

Backed by ``data/goals.json`` (path overridable via ``goals.store_path``).
"""
from __future__ import annotations

import time

from namma_agent.core.tools import ToolRegistry, ToolResult
from namma_agent.tools import _jsonstore as store

_FILE = "goals.json"


def _path():
    return store.store_path("goals", _FILE)


def _add(args: dict) -> ToolResult:
    title = (args.get("title") or "").strip()
    if not title:
        return ToolResult(ok=False, content="", error="a goal title is required")
    items = store.load(_path())
    item = {"id": store.next_id(items), "title": title,
            "target": (args.get("target") or "").strip(),
            "progress": 0, "created_at": int(time.time())}
    items.append(item)
    store.save(_path(), items)
    return ToolResult(ok=True, content=f"Goal #{item['id']} added: {title}", data=item)


def _list(_args: dict) -> ToolResult:
    items = store.load(_path())
    if not items:
        return ToolResult(ok=True, content="No goals.")
    lines = ["Goals:"]
    for g in items:
        target = f" (target: {g['target']})" if g.get("target") else ""
        lines.append(f"#{g['id']}: {g['title']} — {g.get('progress', 0)}%{target}")
    return ToolResult(ok=True, content="\n".join(lines), data=items)


def _update(args: dict) -> ToolResult:
    try:
        rid = int(args.get("id"))
        progress = int(args.get("progress"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="numeric 'id' and 'progress' are required")
    progress = max(0, min(progress, 100))
    items = store.load(_path())
    goal = store.find(items, rid)
    if goal is None:
        return ToolResult(ok=False, content="", error=f"no goal with id {rid}")
    goal["progress"] = progress
    goal["updated_at"] = int(time.time())
    store.save(_path(), items)
    done = " 🎉 done!" if progress >= 100 else ""
    return ToolResult(ok=True, content=f"Goal #{rid} now at {progress}%.{done}")


def _remove(args: dict) -> ToolResult:
    try:
        rid = int(args.get("id"))
    except (TypeError, ValueError):
        return ToolResult(ok=False, content="", error="a numeric goal id is required")
    items = store.load(_path())
    kept = [g for g in items if int(g.get("id", 0)) != rid]
    if len(kept) == len(items):
        return ToolResult(ok=False, content="", error=f"no goal with id {rid}")
    store.save(_path(), kept)
    return ToolResult(ok=True, content=f"Removed goal #{rid}.")


def register(registry: ToolRegistry) -> None:
    registry.register("add_goal", "Add a goal to track.", {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "the goal"},
            "target": {"type": "string", "description": "optional target/deadline"},
        },
        "required": ["title"],
    }, _add)

    registry.register("list_goals", "List all goals with their progress.", {
        "type": "object", "properties": {},
    }, _list)

    registry.register("update_goal_progress", "Set a goal's progress (0-100).", {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "description": "goal id"},
            "progress": {"type": "integer", "description": "percent complete 0-100"},
        },
        "required": ["id", "progress"],
    }, _update)

    registry.register("remove_goal", "Delete a goal by id.", {
        "type": "object",
        "properties": {"id": {"type": "integer", "description": "goal id"}},
        "required": ["id"],
    }, _remove, destructive=True)
