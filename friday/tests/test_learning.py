"""Wave 3 tests — Learning Room teacher agent: topics, path, progress, insights, prompt."""
from __future__ import annotations

from fastapi.testclient import TestClient

from friday.core.learning import learning_block
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


def _svc():
    return FridayService(
        config={"persona": "core", "conversation": {}},
        provider=ScriptedProvider([LLMResponse(content="ok")]),
        registry=ToolRegistry(),
        db=Database(":memory:"),
    )


def test_topic_create_plan_modules_and_progress():
    db = Database(":memory:")
    t = db.create_learning_topic("Photosynthesis", "deep")
    assert t["depth"] == "deep" and t["plan"] == []

    db.set_learning_plan(t["id"], [{"title": "Light"}, {"title": "Chlorophyll"}, {"title": "Sugar"}])
    t = db.get_learning_topic(t["id"])
    assert [m["title"] for m in t["plan"]] == ["Light", "Chlorophyll", "Sugar"]
    assert t["plan"][0]["status"] == "current"
    assert t["progress"] == {"done": 0, "total": 3, "current_module": "m1"}

    # module session is created lazily and resolves back to the topic
    sid = db.module_session(t["id"], "m1")
    assert db.get_topic_by_session(sid)["id"] == t["id"]

    db.mark_module(t["id"], "m1", "done")
    t = db.get_learning_topic(t["id"])
    assert t["progress"] == {"done": 1, "total": 3, "current_module": "m2"}


def test_replan_preserves_module_sessions():
    db = Database(":memory:")
    t = db.create_learning_topic("Topic")
    db.set_learning_plan(t["id"], [{"id": "m1", "title": "A"}, {"id": "m2", "title": "B"}])
    sid = db.module_session(t["id"], "m1")
    # re-plan keeping m1: its session must survive
    db.set_learning_plan(t["id"], [{"id": "m1", "title": "A (revised)"}, {"id": "m3", "title": "C"}])
    plan = db.get_learning_topic(t["id"])["plan"]
    assert plan[0]["title"] == "A (revised)" and plan[0]["session_id"] == sid


def test_insights_aggregate_quiz_and_artifacts():
    db = Database(":memory:")
    t = db.create_learning_topic("X")
    db.record_quiz(t["id"], "q1", True)
    db.record_quiz(t["id"], "q2", False)
    db.record_artifact(t["id"], "diagram", "/api/media/diagrams/a.png", "A")
    db.set_learning_insights(t["id"], {"analysis": "thinks visually", "understanding": 72})
    ins = db.topic_insights(t["id"])
    assert ins["quiz"]["total"] == 2 and ins["quiz"]["score"] == 50
    assert ins["understanding"] == 72 and ins["analysis"] == "thinks visually"
    assert ins["artifacts"][0]["kind"] == "diagram"


def test_delete_topic_cascades():
    db = Database(":memory:")
    t = db.create_learning_topic("Y")
    db.module_session(t["id"], "m?")  # no such module -> None, fine
    db.add_scope_memory("learning", t["id"], "goal: pass exam")
    db.record_quiz(t["id"], "q", True)
    assert db.delete_learning_topic(t["id"]) is True
    assert db.get_learning_topic(t["id"]) is None
    assert db.list_scope_memory("learning", t["id"]) == []


def test_learning_block_in_system_prompt():
    svc = _svc()
    t = svc.db.create_learning_topic("Fractions", "curious")
    svc.db.set_learning_plan(t["id"], [{"title": "Halves"}, {"title": "Quarters"}])
    svc.db.add_scope_memory("learning", t["id"], "learner is 10 years old")
    # the topic's overview session is the PATH CHAT (plan + preferences desk)
    sid = t["session_id"]
    block = svc.agent._scope_block(sid)
    assert "LEARNING ROOM" in block and "Fractions" in block
    assert "PATH CHAT" in block
    assert "learner is 10 years old" in block
    assert "Halves" in block

    # a module thread carries the full teaching (pedagogy) contract
    t = svc.db.get_learning_topic(t["id"])
    msid = svc.db.module_session(t["id"], t["plan"][0]["id"])
    mblock = learning_block(svc.db, svc.db.get_learning_topic(t["id"]), msid)
    assert "Halves" in mblock
    assert "real-life" in mblock.lower()  # pedagogy contract present


def test_learning_rest_flow():
    svc = _svc()
    client = TestClient(create_app(svc))
    tid = client.post("/api/learning", json={"topic": "Tides", "depth": "solid"}).json()["topic"]["id"]
    assert any(t["id"] == tid for t in client.get("/api/learning").json()["topics"])

    client.patch(f"/api/learning/{tid}/plan", json={"modules": [{"title": "Moon pull"}, {"title": "Spring tides"}]})
    detail = client.get(f"/api/learning/{tid}").json()
    assert [m["title"] for m in detail["topic"]["plan"]] == ["Moon pull", "Spring tides"]

    mid = detail["topic"]["plan"][0]["id"]
    sid = client.post(f"/api/learning/{tid}/module/{mid}/session").json()["session_id"]
    assert sid

    ins = client.post(f"/api/learning/{tid}/quiz", json={"question": "q", "correct": True}).json()["insights"]
    assert ins["quiz"]["total"] == 1
    assert client.delete(f"/api/learning/{tid}").json()["deleted"] is True
