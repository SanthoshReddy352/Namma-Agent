"""Phase 3: the delegation runtime — goal/context/tasks[] contract, fan-out with
a concurrency cap, depth cap and roles, the cancellation tree, the bounded
background pool that reports back into the chat, persisted runs and events."""
from __future__ import annotations

import threading
import time

import pytest

from namma_agent.core.agent import Agent
from namma_agent.core.builtins import register_agent_tools
from namma_agent.core.delegation import TERMINAL, wait_for
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider, ToolCall
from namma_agent.core.tools import ToolRegistry, ToolResult

_OBJ = {"type": "object", "properties": {}}


def _goal_of(messages) -> str:
    user = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
    return user.split("GOAL: ", 1)[-1].split("\n", 1)[0]


class ScriptProvider(Provider):
    """Thread-safe: the reply is decided by ``script(goal, messages, tools)``."""
    name = "script"

    def __init__(self, script):
        super().__init__(model="script")
        self.script = script
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls: list[dict] = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append({"system": messages[0]["content"], "messages": messages,
                               "tools": [t["name"] for t in (tools or [])]})
        try:
            return self.script(_goal_of(messages), messages, tools or [])
        finally:
            with self.lock:
                self.active -= 1


class _Comms:
    any_available = True

    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def _wire(script, config=None, tmp_path=None):
    db = Database(":memory:")
    reg = ToolRegistry()
    with reg.categorize("web"):
        reg.register("web_search", "Search the web.", _OBJ,
                     lambda a: ToolResult(ok=True, content="results"))
    with reg.categorize("file_ops"):
        reg.register("read_file", "Read a file.", _OBJ, lambda a: "text")
        reg.register("delete_path", "Delete.", _OBJ, lambda a: "gone", destructive=True)
    prov = ScriptProvider(script)
    agent = Agent(prov, reg, db, load_persona())
    events: list[tuple[str, dict]] = []
    comms = _Comms()
    handles = register_agent_tools(
        reg, agent, prov, db, get_comms=lambda: comms,
        bg_store_path=(tmp_path / "bg.json") if tmp_path else None,
        publish=lambda e, p: events.append((e, p)), config=config or {})
    return reg, handles["delegation"], prov, db, events, comms


def _answer(goal, messages, tools):
    return LLMResponse(content=f"report for {goal}")


# ── contract ─────────────────────────────────────────────────────────────────

def test_single_goal_returns_the_summary_and_contract_data(tmp_path):
    reg, mgr, prov, db, events, _ = _wire(_answer, tmp_path=tmp_path)
    r = reg.execute("delegate_task", {"goal": "find the capital", "context": "user is in India"})
    assert r.ok and r.content == "report for find the capital"
    res = r.data["results"][0]
    assert (res["status"], res["exit_reason"], res["truncated"]) == ("completed", "completed", False)
    child_msg = prov.calls[0]["messages"][-1]["content"]
    assert "GOAL: find the capital" in child_msg and "user is in India" in child_msg
    row = db.get_run(res["id"])
    assert row["status"] == "completed" and row["child_session_id"]


def test_child_persona_lists_only_its_own_tools(tmp_path):
    reg, _, prov, *_ = _wire(_answer, tmp_path=tmp_path)
    reg.execute("delegate_task", {"goal": "g", "toolsets": ["file_ops"]})
    call = prov.calls[0]
    assert call["tools"] == ["read_file"]                         # destructive stripped
    assert "YOUR TOOLS (the only ones you have): read_file" in call["system"]
    assert "open_app" not in call["system"]                       # no main preamble


def test_fan_out_runs_children_in_parallel_with_a_cap_of_three(tmp_path):
    gate = threading.Barrier(3, timeout=5)
    first_wave = {"t0", "t1", "t2"}

    def slow(goal, messages, tools):
        if goal in first_wave:          # the first 3 only pass if they run at once
            gate.wait()
        time.sleep(0.05)
        return LLMResponse(content=f"done {goal}")

    reg, _, prov, *_ = _wire(slow, tmp_path=tmp_path)
    r = reg.execute("delegate_task", {"tasks": [f"t{i}" for i in range(5)],
                                      "context": "shared"})
    assert r.ok
    results = r.data["results"]
    assert [x["summary"] for x in results] == [f"done t{i}" for i in range(5)]  # task order
    assert prov.max_active == 3                                    # parallel, capped at 3
    assert all("shared" in c["messages"][-1]["content"] for c in prov.calls)


def test_concurrency_cap_is_configurable(tmp_path):
    def slow(goal, messages, tools):
        time.sleep(0.05)
        return LLMResponse(content="ok")

    reg, _, prov, *_ = _wire(slow, config={"delegation": {"concurrency": 1}}, tmp_path=tmp_path)
    reg.execute("delegate_task", {"tasks": ["a", "b", "c"]})
    assert prov.max_active == 1


def test_step_budget_gives_a_partial_truncated_result(tmp_path):
    def loop(goal, messages, tools):
        return LLMResponse(content="", tool_calls=[ToolCall(id=str(time.time()),
                                                            name="web_search", args={})])

    reg, *_ = _wire(loop, tmp_path=tmp_path)
    r = reg.execute("delegate_task", {"goal": "dig", "budget": {"max_steps": 2}})
    res = r.data["results"][0]
    assert res["status"] == "partial" and res["exit_reason"] == "step_limit"
    assert res["truncated"] is True
    assert "status=partial" in r.content


def test_long_summaries_are_clipped_and_flagged(tmp_path):
    reg, *_ = _wire(lambda g, m, t: LLMResponse(content="x" * 500),
                    config={"delegation": {"summary_chars": 100}}, tmp_path=tmp_path)
    res = reg.execute("delegate_task", {"goal": "g"}).data["results"][0]
    assert res["truncated"] is True and "[summary clipped]" in res["summary"]


def test_bad_specs_are_errors(tmp_path):
    reg, *_ = _wire(_answer, tmp_path=tmp_path)
    assert "goal" in reg.execute("delegate_task", {}).error
    assert "role" in reg.execute("delegate_task", {"goal": "g", "role": "boss"}).error
    assert "at most" in reg.execute("delegate_task", {"tasks": ["x"] * 9}).error
    err = reg.execute("delegate_task", {"goal": "g", "toolsets": ["nope"]}).error
    assert "Valid toolsets" in err


def test_untrusted_senders_cannot_delegate(tmp_path):
    from namma_agent.core.trust import reset_message_trust, set_message_trust

    reg, *_ = _wire(_answer, tmp_path=tmp_path)
    token = set_message_trust("untrusted")
    try:
        assert "untrusted" in reg.execute("delegate_task", {"goal": "g"}).error
        assert "untrusted" in reg.execute("background_task", {"goal": "g"}).error
    finally:
        reset_message_trust(token)


# ── roles and depth ──────────────────────────────────────────────────────────

def test_leaf_children_cannot_delegate(tmp_path):
    reg, _, prov, *_ = _wire(_answer, tmp_path=tmp_path)
    reg.execute("delegate_task", {"goal": "g", "role": "leaf"})
    assert "delegate_task" not in prov.calls[0]["tools"]


def test_orchestrator_fans_out_once_and_grandchildren_are_leaves(tmp_path):
    def script(goal, messages, tools):
        names = [t["name"] for t in tools]
        if goal == "plan" and not any(m.get("role") == "tool" for m in messages):
            return LLMResponse(content="", tool_calls=[ToolCall(
                id="d1", name="delegate_task",
                args={"tasks": ["sub-a", "sub-b"], "role": "orchestrator"})])
        if goal.startswith("sub-"):
            assert "delegate_task" not in names            # depth 2 → leaf
            return LLMResponse(content=f"leaf {goal}")
        return LLMResponse(content="merged")

    reg, mgr, prov, db, *_ = _wire(script, tmp_path=tmp_path)
    r = reg.execute("delegate_task", {"goal": "plan", "role": "orchestrator"})
    assert r.ok and r.content == "merged"
    root = r.data["results"][0]
    runs = db.list_runs()
    kids = [x for x in runs if x["parent_id"] == root["id"]]
    assert sorted(k["goal"] for k in kids) == ["sub-a", "sub-b"]
    assert all(k["depth"] == 2 and k["role"] == "leaf" and k["root_id"] == root["id"]
               for k in kids)
    orch_call = next(c for c in prov.calls if _goal_of(c["messages"]) == "plan")
    assert "delegate_task" in orch_call["tools"] and "ORCHESTRATOR" in orch_call["system"]


# ── cancellation tree ────────────────────────────────────────────────────────

def test_cancelling_a_run_cancels_its_subtree(tmp_path):
    release = threading.Event()

    def script(goal, messages, tools):
        if goal == "boss" and not any(m.get("role") == "tool" for m in messages):
            return LLMResponse(content="", tool_calls=[ToolCall(
                id="d", name="delegate_task", args={"tasks": ["w1", "w2"]})])
        if goal.startswith("w"):
            release.wait(5)                                # parked until cancelled
            return LLMResponse(content="late")
        return LLMResponse(content="boss done")

    reg, mgr, prov, db, *_ = _wire(script, tmp_path=tmp_path)
    out = {}
    t = threading.Thread(target=lambda: out.update(
        r=reg.execute("delegate_task", {"goal": "boss", "role": "orchestrator"})))
    t.start()
    deadline = time.time() + 5
    while time.time() < deadline:
        workers = [r for r in mgr.list() if r["goal"].startswith("w") and r["status"] == "running"]
        if len(workers) == 2:
            break
        time.sleep(0.02)
    root = next(r for r in mgr.list() if r["goal"] == "boss")
    res = mgr.cancel(root["id"])
    assert res["ok"] and len(res["cancelled"]) == 3
    t.join(10)
    release.set()
    assert not t.is_alive()
    statuses = {r["goal"]: r["status"] for r in mgr.list()}
    assert statuses == {"boss": "cancelled", "w1": "cancelled", "w2": "cancelled"}


# ── background pool ──────────────────────────────────────────────────────────

def test_background_pool_is_bounded_and_reports_back_into_the_chat(tmp_path):
    release = threading.Event()

    def script(goal, messages, tools):
        if goal == "first":
            release.wait(5)
        return LLMResponse(content=f"bg report {goal}")

    reg, mgr, prov, db, events, comms = _wire(
        script, config={"delegation": {"background_workers": 1}}, tmp_path=tmp_path)
    from namma_agent.core.interactive import set_current_session
    chat = db.create_session()
    set_current_session(chat)
    try:
        a = reg.execute("background_task", {"goal": "first"}).data["id"]
        b = reg.execute("background_task", {"goal": "second"}).data["id"]
    finally:
        set_current_session(None)
    time.sleep(0.2)
    assert mgr.get(b)["status"] == "queued"                    # pool of 1 → waits
    release.set()
    wait_for(mgr, a)
    wait_for(mgr, b)
    turns = [t["content"] for t in db.recent_turns(chat, 10)]
    assert any("bg report first" in t for t in turns)
    assert any("bg report second" in t for t in turns)
    reports = [p for e, p in events if e == "subagent" and p.get("report")]
    assert {p["run"]["id"] for p in reports} == {a, b}
    assert len(comms.sent) == 2


def test_queued_background_task_can_be_cancelled(tmp_path):
    release = threading.Event()

    def script(goal, messages, tools):
        if goal == "hog":
            release.wait(5)
        return LLMResponse(content="ok")

    reg, mgr, *_ = _wire(script, config={"delegation": {"background_workers": 1}},
                         tmp_path=tmp_path)
    reg.execute("background_task", {"goal": "hog"})
    queued = reg.execute("background_task", {"goal": "later"}).data["id"]
    out = reg.execute("cancel_background_task", {"id": queued})
    assert out.ok
    assert mgr.get(queued)["status"] == "cancelled"
    release.set()


# ── events and API ───────────────────────────────────────────────────────────

def test_runs_publish_progress_events(tmp_path):
    def script(goal, messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return LLMResponse(content="", tool_calls=[ToolCall(id="1", name="web_search",
                                                                args={})])
        return LLMResponse(content="found")

    reg, _, _, _, events, _ = _wire(script, tmp_path=tmp_path)
    reg.execute("delegate_task", {"goal": "g"})
    seen = [(p["run"]["status"], p["run"].get("current_tool")) for e, p in events
            if e == "subagent"]
    assert seen[0][0] == "queued"
    assert ("running", "web_search") in seen
    # tool_finished clears the live tool in the UI before the next model call
    i = seen.index(("running", "web_search"))
    assert seen[i + 1] == ("running", "")
    assert seen[-1][0] == "completed"
    assert all(s in ("queued", "running") or s in TERMINAL for s, _ in seen)


def test_runs_api_lists_and_cancels():
    from fastapi.testclient import TestClient

    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=ScriptProvider(_answer), registry=ToolRegistry(),
                            db=Database(":memory:"))
    reg = svc.registry
    handles = register_agent_tools(reg, svc.agent, svc.provider, svc.db,
                                   publish=svc.broadcast.publish, config=svc.config)
    svc.delegation = handles["delegation"]
    got = []
    unsubscribe = svc.broadcast.subscribe(lambda e, p: got.append(e))
    r = reg.execute("delegate_task", {"goal": "g"})
    unsubscribe()
    assert "subagent" in got
    client = TestClient(create_app(svc))
    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["id"] == r.data["results"][0]["id"]
    assert client.get(f"/api/runs/{runs[0]['id']}").json()["status"] == "completed"
    assert client.get("/api/runs/nope").status_code == 404
    out = client.post(f"/api/runs/{runs[0]['id']}/cancel").json()
    assert out["ok"] and out["cancelled"] == []                # already finished


def test_skills_are_injected_and_unknown_skills_rejected(tmp_path):
    class _Skill:
        name, body = "triage", "1. read the issue\n2. label it"

    class _Store:
        def get(self, name):
            return _Skill() if name == "triage" else None

    db = Database(":memory:")
    reg = ToolRegistry()
    prov = ScriptProvider(_answer)
    agent = Agent(prov, reg, db, load_persona())
    register_agent_tools(reg, agent, prov, db, skills_getter=lambda: _Store(),
                         bg_store_path=tmp_path / "bg.json")
    assert reg.execute("delegate_task", {"goal": "g", "skills": ["triage"]}).ok
    assert "label it" in prov.calls[0]["system"]
    assert "unknown skill" in reg.execute("delegate_task",
                                          {"goal": "g", "skills": ["nope"]}).error


def test_eval_harness_passes_with_the_oracle_brain():
    """The 20-task eval runs end to end through the real runtime and file tools.
    (The oracle proves the plumbing; model quality needs a live run.)"""
    from namma_agent.core.delegation_eval import TASKS, OracleProvider, run_eval

    report = run_eval(OracleProvider())
    assert report["total"] == len(TASKS) == 20
    failed = [i["id"] for i in report["items"] if not i["ok"]]
    assert failed == []


def test_eval_token_cap_is_hard_and_skips_the_rest():
    """The live eval must never pass its token budget: calls are refused once
    spent + (in-flight + 1) × reserve would cross the cap, and remaining tasks
    are skipped (not billed)."""
    from namma_agent.core.delegation_eval import CappedProvider, run_eval

    class Costly(ScriptProvider):
        def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
            resp = super().generate(messages, tools, stream, on_token, on_thinking)
            resp.usage = {"input_tokens": 9000, "output_tokens": 1000}
            return resp

    capped = CappedProvider(Costly(_answer), cap=50_000, reserve=10_000)
    report = run_eval(capped)
    t = report["tokens"]
    assert t["exhausted"] and t["spent"] <= 50_000
    assert any(i.get("skipped") for i in report["items"])
    assert t["calls"] * 10_000 == t["spent"]


def test_standalone_manager_gives_orchestrators_a_delegate_tool():
    from types import SimpleNamespace

    from namma_agent.core.delegation import DelegationManager

    reg = ToolRegistry()
    mgr = DelegationManager(db=Database(":memory:"), registry=reg,
                            parent_agent=SimpleNamespace(tool_loop_limit=0, persona=None),
                            resolve_provider=lambda: None)
    assert "delegate_task" in mgr.sub_registry(role="orchestrator", depth=1)
    assert "delegate_task" not in mgr.sub_registry(role="orchestrator", depth=2)
    assert "delegate_task" not in mgr.sub_registry(role="leaf", depth=1)


@pytest.mark.parametrize("bad", [{"tasks": "notalist"}, {"goal": "g", "budget": 5}])
def test_type_errors_in_specs(tmp_path, bad):
    reg, *_ = _wire(_answer, tmp_path=tmp_path)
    assert not reg.execute("delegate_task", bad).ok


def test_runs_record_the_brief_and_a_step_trail_for_the_ui(tmp_path):
    """Phase 9: the UI shows each sub-agent's exact brief and what it did."""
    def script(goal, messages, tools):
        if not any(m.get("role") == "tool" for m in messages):
            return LLMResponse(content="", tool_calls=[ToolCall(id="1", name="web_search",
                                                                args={"query": "orbital speed of ISS"})])
        return LLMResponse(content="found")

    reg, _, _, _, events, _ = _wire(script, tmp_path=tmp_path)
    reg.execute("delegate_task", {"goal": "find the ISS speed", "context": "user is a student"})
    final = [p["run"] for e, p in events if e == "subagent"][-1]
    meta = final["meta"]
    assert meta["prompt"].startswith("GOAL: find the ISS speed")
    assert "CONTEXT FROM THE MAIN AGENT:\nuser is a student" in meta["prompt"]
    assert meta["step_limit"] > 0
    [step] = meta["trail"]
    assert step["tool"] == "web_search" and step["status"] in ("ok", "error")
    assert "orbital speed of ISS" in step["args"]


def test_trail_previews_are_one_line_and_capped():
    from namma_agent.core.delegation import DelegationManager

    p = DelegationManager._preview({"text": "a\n\nb  " + "x" * 400})
    assert "\n" not in p and len(p) <= 160 and p.endswith("…")
