"""Wave 5b — task + goal CRUD tools (persisted JSON stores)."""
from __future__ import annotations

import pytest

from namma_agent.core.tools import ToolRegistry
from namma_agent.tools import load_tools
from namma_agent.tools import goals as goalmod
from namma_agent.tools import tasks as taskmod


@pytest.fixture
def reg(monkeypatch, tmp_path):
    monkeypatch.setattr(taskmod, "_path", lambda: tmp_path / "tasks.json")
    monkeypatch.setattr(goalmod, "_path", lambda: tmp_path / "goals.json")
    return load_tools(ToolRegistry())


def test_registered(reg):
    for name in ("add_task", "list_tasks", "complete_task", "remove_task",
                 "add_goal", "list_goals", "update_goal_progress", "remove_goal"):
        assert name in reg


def test_task_lifecycle(reg):
    a = reg.execute("add_task", {"title": "write tests", "notes": "wave5"})
    assert a.ok and a.data["id"] == 1
    assert "write tests" in reg.execute("list_tasks", {}).content
    assert reg.execute("complete_task", {"id": 1}).ok
    done = reg.execute("list_tasks", {"status": "done"})
    assert "[x] #1" in done.content
    assert reg.execute("list_tasks", {"status": "open"}).content == "No tasks."
    assert reg.execute("remove_task", {"id": 1}).ok


def test_complete_missing_task(reg):
    assert not reg.execute("complete_task", {"id": 9}).ok


def test_goal_lifecycle(reg):
    a = reg.execute("add_goal", {"title": "ship v2", "target": "June"})
    assert a.ok and a.data["id"] == 1
    up = reg.execute("update_goal_progress", {"id": 1, "progress": 150})
    assert up.ok and "100%" in up.content  # clamped
    assert "ship v2" in reg.execute("list_goals", {}).content
    assert reg.execute("remove_goal", {"id": 1}).ok
    assert reg.execute("list_goals", {}).content == "No goals."


def test_update_missing_goal(reg):
    assert not reg.execute("update_goal_progress", {"id": 5, "progress": 10}).ok


def test_destructive_flags(reg):
    assert reg.get("remove_task").destructive
    assert reg.get("remove_goal").destructive
    assert reg.get("add_task").destructive is False
