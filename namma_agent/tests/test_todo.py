"""The update_todos tool: per-session store, todo_updated events, normalization."""
from __future__ import annotations

import pytest

from namma_agent.core.interactive import set_current_session, set_event_sink
from namma_agent.core.tools import ToolRegistry
from namma_agent.tools import todo as todo_mod


@pytest.fixture
def reg():
    r = ToolRegistry()
    todo_mod.register(r)
    return r


@pytest.fixture(autouse=True)
def _clean_state():
    todo_mod._TODOS.clear()
    yield
    todo_mod._TODOS.clear()
    set_current_session(None)
    set_event_sink(None)


def test_registered(reg):
    assert "update_todos" in reg


def test_plan_stored_and_event_emitted(reg):
    events = []
    set_current_session("s1")
    set_event_sink(lambda e, p: events.append((e, p)))
    res = reg.execute("update_todos", {"todos": [
        {"text": "Scan the repo", "status": "in_progress"},
        {"text": "Write the fix"},
        {"text": "Run the tests", "status": "pending"},
    ]})
    assert res.ok
    assert "1/3" not in res.content and "0/3 done" in res.content
    stored = todo_mod.todos_for("s1")
    assert [t["text"] for t in stored] == ["Scan the repo", "Write the fix", "Run the tests"]
    assert stored[0]["status"] == "in_progress"
    assert stored[1]["status"] == "pending"  # default
    assert events == [("todo_updated", {"session_id": "s1", "todos": stored})]


def test_full_replace_and_progress(reg):
    set_current_session("s1")
    reg.execute("update_todos", {"todos": [{"text": "a", "status": "in_progress"},
                                           {"text": "b"}]})
    res = reg.execute("update_todos", {"todos": [{"text": "a", "status": "done"},
                                                 {"text": "b", "status": "in_progress"}]})
    assert res.ok and "1/2 done" in res.content
    stored = todo_mod.todos_for("s1")
    assert [t["status"] for t in stored] == ["done", "in_progress"]


def test_subtasks_kept_and_normalized(reg):
    set_current_session("s1")
    res = reg.execute("update_todos", {"todos": [
        {"text": "Refactor", "status": "in-progress", "subtasks": [
            {"text": "rename module", "status": "completed"},
            {"text": "update imports"},
            {"text": "   "},                    # empty → dropped
        ]},
    ]})
    assert res.ok
    t = todo_mod.todos_for("s1")[0]
    assert t["status"] == "in_progress"          # dash variant coerced
    assert [s["status"] for s in t["subtasks"]] == ["done", "pending"]
    assert len(t["subtasks"]) == 2


def test_empty_list_clears(reg):
    set_current_session("s1")
    reg.execute("update_todos", {"todos": [{"text": "a"}]})
    res = reg.execute("update_todos", {"todos": []})
    assert res.ok
    assert todo_mod.todos_for("s1") == []


def test_missing_todos_arg_rejected(reg):
    res = reg.execute("update_todos", {})
    assert not res.ok


def test_sessions_isolated(reg):
    set_current_session("s1")
    reg.execute("update_todos", {"todos": [{"text": "one"}]})
    set_current_session("s2")
    reg.execute("update_todos", {"todos": [{"text": "two"}]})
    assert todo_mod.todos_for("s1")[0]["text"] == "one"
    assert todo_mod.todos_for("s2")[0]["text"] == "two"


def test_no_session_still_works(reg):
    events = []
    set_current_session(None)
    set_event_sink(lambda e, p: events.append((e, p)))
    res = reg.execute("update_todos", {"todos": [{"text": "headless step"}]})
    assert res.ok
    assert events[0][1]["session_id"] is None
