"""Wave 2 tests — Projects: dedicated layered memory, filing chats, scoped prompt."""
from __future__ import annotations

from fastapi.testclient import TestClient

from friday.core.memory import Database
from friday.core.providers.base import LLMResponse, Provider
from friday.core.tools import ToolRegistry
from friday.server.api import create_app
from friday.service import FridayService


class ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, responses):
        super().__init__(model="scripted")
        self._responses = list(responses)

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None):
        return self._responses.pop(0)


# ── DB layer ────────────────────────────────────────────────────────────────

def test_project_crud_and_chat_count():
    db = Database(":memory:")
    p = db.create_project("Roof Garden", "balcony build")
    assert p["name"] == "Roof Garden"
    assert db.list_projects()[0]["chat_count"] == 0

    sid = db.create_session_in(project_id=p["id"])
    db.add_turn(sid, "user", "what soil?")
    assert db.list_projects()[0]["chat_count"] == 1

    p2 = db.update_project(p["id"], name="Rooftop Garden")
    assert p2["name"] == "Rooftop Garden"


def test_delete_project_unfiles_chats_and_drops_memory():
    db = Database(":memory:")
    p = db.create_project("Temp")
    sid = db.create_session_in(project_id=p["id"])
    db.add_turn(sid, "user", "hi")
    db.add_scope_memory("project", p["id"], "uses metric units")

    assert db.delete_project(p["id"]) is True
    assert db.get_project(p["id"]) is None
    # chat survives but is unfiled
    assert db.get_session(sid)["project_id"] in (None, "")
    assert db.list_scope_memory("project", p["id"]) == []


def test_rename_and_file_chat_and_list_filtering():
    db = Database(":memory:")
    p = db.create_project("Work")
    chat = db.create_session()
    db.add_turn(chat, "user", "a very long first message that should be truncated for the title display nicely")
    learning = db.create_session_in(kind="learning")
    db.add_turn(learning, "user", "teach me napkins")

    # learning sessions are excluded from the normal sidebar list
    ids = {s["id"] for s in db.list_sessions()}
    assert chat in ids and learning not in ids

    # custom rename wins over the first-message title
    assert db.rename_session(chat, "Groceries") is True
    assert next(s for s in db.list_sessions() if s["id"] == chat)["title"] == "Groceries"

    # filing into a project, then filtering by project
    assert db.set_session_project(chat, p["id"]) is True
    assert [s["id"] for s in db.list_sessions(project_id=p["id"])] == [chat]
    assert [s["id"] for s in db.list_sessions(project_id="")] == []


def test_scope_memory_add_list_delete():
    db = Database(":memory:")
    p = db.create_project("P")
    eid = db.add_scope_memory("project", p["id"], "deadline is Friday")
    assert db.add_scope_memory("project", p["id"], "  ") == 0  # empty ignored
    mem = db.list_scope_memory("project", p["id"])
    assert [m["content"] for m in mem] == ["deadline is Friday"]
    assert db.delete_scope_memory_entry(eid) is True
    assert db.list_scope_memory("project", p["id"]) == []


# ── scoped system prompt (layered memory) ────────────────────────────────────

def _service():
    return FridayService(
        config={"persona": "core", "conversation": {}},
        provider=ScriptedProvider([LLMResponse(content="ok")]),
        registry=ToolRegistry(),
        db=Database(":memory:"),
    )


def test_project_context_injected_and_layered():
    svc = _service()
    svc.db.save_fact("name", "Tricky")  # global identity fact
    p = svc.db.create_project("Garden", "balcony build")
    sid = svc.db.create_session_in(project_id=p["id"])
    svc.db.add_scope_memory("project", p["id"], "south-facing balcony")

    block = svc.agent._scope_block(sid)
    assert "PROJECT CONTEXT" in block
    assert "Garden" in block and "south-facing balcony" in block

    # layered: the full system prompt still carries the global fact
    messages = svc.agent._build_messages("hello", sid)
    system = messages[0]["content"]
    assert "PROJECT CONTEXT" in system
    assert "Tricky" in system  # global identity preserved inside a project


def test_unfiled_chat_has_no_scope_block():
    svc = _service()
    sid = svc.db.create_session()
    assert svc.agent._scope_block(sid) == ""


# ── REST ─────────────────────────────────────────────────────────────────────

def test_project_rest_flow():
    svc = _service()
    client = TestClient(create_app(svc))

    pid = client.post("/api/projects", json={"name": "Trip", "description": "Japan"}).json()["project"]["id"]
    assert any(p["id"] == pid for p in client.get("/api/projects").json()["projects"])

    sid = client.post(f"/api/projects/{pid}/sessions").json()["session_id"]
    assert client.patch(f"/api/sessions/{sid}", json={"title": "Day 1"}).json()["renamed"] is True

    mem = client.post(f"/api/projects/{pid}/memory", json={"content": "vegetarian"}).json()
    assert mem["memory"][0]["content"] == "vegetarian"

    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["project"]["description"] == "Japan"
    assert detail["memory"][0]["content"] == "vegetarian"

    assert client.delete(f"/api/projects/{pid}").json()["deleted"] is True
