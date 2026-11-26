"""Delegation eval suite (PROGRESS.md Phase 3 acceptance: ≥85% of 20 tasks).

Twenty small, checkable delegations over a seeded scratch workspace: single
lookups, multi-step file work, context-only answers, fan-out (``tasks[]``), an
orchestrator split and a step budget. Each task passes when every child ends
``completed`` and its summary matches the expected answer(s).

``run_eval(provider)`` drives the REAL delegation runtime
(:class:`~namma_agent.core.delegation.DelegationManager`) with real file tools;
only the brain is pluggable. ``scripts/delegation_eval.py`` runs it against the
configured model (spends tokens) or ``--mock`` (an oracle brain that checks the
harness plumbing only — it says nothing about model quality).
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

_FILES = {
    "README.md": "# Kestrel\n\nKestrel is a tiny inventory service.\n",
    "config/settings.ini": "[server]\nhost=0.0.0.0\nport=8421\n",
    "notes/meeting.txt": ("Weekly sync, 3 Nov.\nDecision: ship v2 on Friday.\n"
                          "Owner: Priya.\nRisk: the payments migration.\n"),
    "notes/todo.md": ("- [x] write changelog\n- [ ] tag release\n- [x] update docs\n"
                      "- [ ] notify sales\n- [ ] archive old branch\n"),
    "data/sales.csv": ("region,amount\nnorth,500\nsouth,300\nnorth,750\neast,200\n"
                       "south,250\n"),
    "src/app.py": ("def handle_login(user):\n    return True\n\n\n"
                   "def handle_logout(user):\n    return True\n\n\n"
                   "def list_items():\n    return []\n\n\n"
                   "def add_item(name):\n    return name\n"),
    "src/util.py": "def slug(text):\n    return text.lower()\n",
    "logs/app.log": ("INFO start\nERROR E42 db timeout\nINFO retry\nERROR E42 db timeout\n"
                     "WARN slow\nERROR E17 bad token\nINFO done\n"),
}

#: (id, delegate_task args with {root} placeholders, expected patterns — one list
#: per child; every pattern of a child must match its summary, case-insensitive).
TASKS: list[tuple[str, dict, list[list[str]]]] = [
    ("port", {"goal": "What port does {root}/config/settings.ini set?"}, [[r"8421"]]),
    ("owner", {"goal": "Who owns the decision recorded in {root}/notes/meeting.txt?"},
     [[r"priya"]]),
    ("ship-day", {"goal": "On which day does v2 ship, per {root}/notes/meeting.txt?"},
     [[r"friday"]]),
    ("unchecked", {"goal": "How many unchecked items are in {root}/notes/todo.md?"},
     [[r"\b3\b|three"]]),
    ("north-total", {"goal": "What is the total amount for region north in "
                             "{root}/data/sales.csv?"}, [[r"1,?250"]]),
    ("functions", {"goal": "How many functions are defined in {root}/src/app.py?"},
     [[r"\b4\b|four"]]),
    ("login-fn", {"goal": "What is the name of the function that handles login in "
                          "{root}/src/app.py?"}, [[r"handle_login"]]),
    ("errors", {"goal": "How many ERROR lines are in {root}/logs/app.log?"},
     [[r"\b3\b|three"]]),
    ("top-code", {"goal": "Which error code appears most often in {root}/logs/app.log?"},
     [[r"E42"]]),
    ("project", {"goal": "What is the project called, according to {root}/README.md?"},
     [[r"kestrel"]]),
    ("who-file", {"goal": "Which file under {root} mentions Priya? Give the file name."},
     [[r"meeting\.txt"]]),
    ("folders", {"goal": "List the folders directly inside {root}."},
     [[r"config", r"data", r"logs", r"notes", r"src"]]),
    ("context-only", {"goal": "What is the user's preferred deploy day?",
                      "context": "The user said they prefer deploying on Tuesdays."},
     [[r"tuesday"]]),
    ("context-check", {"goal": "Does {root}/config/settings.ini use the port the user "
                               "asked for? Answer yes or no and give the port.",
                       "context": "The user asked for port 8421."}, [[r"\byes\b", r"8421"]]),
    ("fanout-3", {"tasks": ["What port does {root}/config/settings.ini set?",
                            "Who owns the decision in {root}/notes/meeting.txt?",
                            "What is the project called in {root}/README.md?"]},
     [[r"8421"], [r"priya"], [r"kestrel"]]),
    ("fanout-2", {"tasks": ["How many ERROR lines are in {root}/logs/app.log?",
                            "How many unchecked items are in {root}/notes/todo.md?"]},
     [[r"\b3\b|three"], [r"\b3\b|three"]]),
    ("orchestrator", {"goal": "Report three facts: the port in {root}/config/settings.ini, "
                              "the decision owner in {root}/notes/meeting.txt and the "
                              "project name in {root}/README.md. Split the work across "
                              "sub-agents.", "role": "orchestrator"},
     [[r"8421", r"priya", r"kestrel"]]),
    ("budget", {"goal": "What port does {root}/config/settings.ini set?",
                "budget": {"max_steps": 4}}, [[r"8421"]]),
    ("py-count", {"goal": "How many .py files are under {root}/src?"}, [[r"\b2\b|two"]]),
    ("sales-sum", {"goal": "What is the sum of all amounts in {root}/data/sales.csv?"},
     [[r"2,?000"]]),
]


def seed_workspace(root: Path) -> Path:
    for rel, text in _FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _fill(value: Any, root: str) -> Any:
    if isinstance(value, str):
        return value.replace("{root}", root)
    if isinstance(value, list):
        return [_fill(v, root) for v in value]
    if isinstance(value, dict):
        return {k: _fill(v, root) for k, v in value.items()}
    return value


class TokenCapExceeded(RuntimeError):
    """The eval's token cap would be crossed by another model call."""


class CappedProvider:
    """Wraps the eval's brain with a HARD token cap across every call (children
    run in parallel, so the counter is locked). A new call is refused once
    ``spent + reserve`` would pass ``cap`` — the reserve covers the largest
    single call we expect, so the call that crosses the line can't overshoot it
    by much. Counts everything the provider bills: fresh input, cache reads and
    writes, and output."""

    def __init__(self, inner, cap: int, reserve: int = 15_000):
        import threading

        self.__dict__.update(_inner=inner, cap=int(cap), reserve=int(reserve),
                             spent=0, calls=0, inflight=0, exhausted=False,
                             _lock=threading.Lock())

    def generate(self, *args, **kwargs):
        with self._lock:
            # Room for this call AND every call already in flight (parallel
            # children), so concurrent calls can't jointly overshoot the cap.
            if self.spent + (self.inflight + 1) * self.reserve > self.cap:
                self.__dict__["exhausted"] = True
                raise TokenCapExceeded(
                    f"eval token cap reached ({self.spent:,} used of {self.cap:,})")
            self.__dict__["calls"] = self.calls + 1
            self.__dict__["inflight"] = self.inflight + 1
        used = 0
        try:
            resp = self._inner.generate(*args, **kwargs)
            u = getattr(resp, "usage", None) or {}
            used = sum(int(u.get(k, 0) or 0) for k in
                       ("input_tokens", "output_tokens", "cache_read_tokens",
                        "cache_write_tokens"))
            return resp
        finally:
            with self._lock:
                self.__dict__["spent"] = self.spent + used
                self.__dict__["inflight"] = self.inflight - 1

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        setattr(self._inner, name, value)


def _manager(provider, registry=None):
    from namma_agent.core.delegation import DelegationManager
    from namma_agent.core.memory import Database
    from namma_agent.core.persona import load_persona
    from namma_agent.core.tools import ToolRegistry

    if registry is None:
        from namma_agent.tools import load_tools
        registry = load_tools(ToolRegistry())
    parent = SimpleNamespace(tool_loop_limit=0, persona=load_persona())
    return DelegationManager(db=Database(":memory:"), registry=registry,
                             parent_agent=parent, resolve_provider=lambda: provider,
                             config={})


def run_eval(provider, *, registry=None, tasks: Optional[list] = None) -> dict:
    """Run the suite; returns ``{passed, total, score, items: [...]}``."""
    tasks = tasks if tasks is not None else TASKS
    items = []
    with tempfile.TemporaryDirectory(prefix="namma-deleg-eval-") as tmp:
        root = str(seed_workspace(Path(tmp)))
        mgr = _manager(provider, registry)
        for tid, args, expected in tasks:
            if getattr(provider, "exhausted", False):
                items.append({"id": tid, "ok": False, "skipped": True,
                              "error": "skipped: token cap reached", "notes": [],
                              "summaries": []})
                continue
            spec = _fill(dict(args), root)
            spec.setdefault("toolsets", ["file_ops"])
            if spec.get("tasks"):
                spec["context"] = (spec.get("context", "") + f"\nWorkspace root: {root}").strip()
            try:
                results = mgr.delegate(spec)
                error = ""
            except Exception as exc:  # noqa: BLE001 — a crash is a failed item
                results, error = [], str(exc)
            ok = bool(results) and len(results) == len(expected) and not error
            notes = []
            for res, patterns in zip(results, expected):
                if res["status"] != "completed":
                    ok = False
                    notes.append(f"{res['name'][:30]}: {res['status']}/{res['exit_reason']}")
                    continue
                missing = [p for p in patterns
                           if not re.search(p, res["summary"] or "", re.IGNORECASE)]
                if missing:
                    ok = False
                    notes.append(f"{res['name'][:30]}: missing {missing}")
            items.append({"id": tid, "ok": ok, "error": error, "notes": notes,
                          "summaries": [r["summary"][:200] for r in results]})
    passed = sum(1 for i in items if i["ok"])
    report = {"passed": passed, "total": len(items),
              "score": round(passed / len(items), 3) if items else 0.0, "items": items}
    if isinstance(provider, CappedProvider):
        report["tokens"] = {"spent": provider.spent, "cap": provider.cap,
                            "calls": provider.calls, "exhausted": provider.exhausted}
    return report


def format_report(report: dict) -> str:
    lines = [f"Delegation eval: {report['passed']}/{report['total']} passed "
             f"({report['score'] * 100:.0f}%)"]
    if report.get("tokens"):
        t = report["tokens"]
        lines.append(f"Tokens: {t['spent']:,} used in {t['calls']} calls (cap {t['cap']:,})"
                     + (" — CAP REACHED, remaining tasks skipped" if t["exhausted"] else ""))
    for item in report["items"]:
        mark = "PASS" if item["ok"] else "FAIL"
        detail = item["error"] or "; ".join(item["notes"])
        lines.append(f"  {mark}  {item['id']}" + (f" — {detail}" if detail else ""))
    return "\n".join(lines)


class OracleProvider:
    """``--mock`` brain: answers each child with the expected facts straight from
    the seeded files (and makes orchestrators really delegate), so a full pass
    proves the harness and runtime plumbing — not model quality."""

    name = "oracle"
    model = "oracle"

    _ANSWERS = (
        ("settings.ini", "The port is 8421. Yes, it matches."),
        ("decision owner", "8421; owner Priya; project Kestrel"),
        ("meeting.txt", "Priya owns it; v2 ships on Friday. File: meeting.txt."),
        ("mentions Priya", "notes/meeting.txt"),
        ("todo.md", "3 unchecked items."),
        ("north", "The north total is 1250."),
        ("sum of all", "The sum is 2000."),
        ("handles login", "handle_login"),
        ("functions are defined", "4 functions."),
        ("ERROR lines", "3 ERROR lines."),
        ("error code", "E42 appears most."),
        ("README", "The project is Kestrel."),
        ("folders", "config, data, logs, notes, src"),
        (".py files", "2 Python files."),
        ("deploy day", "Tuesday."),
    )

    def __init__(self):
        from namma_agent.core.providers.base import LLMResponse, ToolCall
        self._LLMResponse, self._ToolCall = LLMResponse, ToolCall

    def is_available(self) -> bool:
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        names = [t["name"] for t in (tools or [])]
        goal = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        goal = goal.split("GOAL: ", 1)[-1]
        has_tool = any(m.get("role") == "tool" for m in messages)
        if "delegate_task" in names:          # an orchestrator: really fan out, then merge
            if not has_tool:
                return self._LLMResponse(content="", tool_calls=[self._ToolCall(
                    id="o1", name="delegate_task", args={"tasks": [
                        "What port does the settings.ini set?",
                        "Who owns the decision in meeting.txt?",
                        "What is the project called in README?"]})])
            return self._LLMResponse(content="Port 8421; owner Priya; project Kestrel.")
        for needle, answer in self._ANSWERS:
            if needle in goal:
                return self._LLMResponse(content=answer)
        return self._LLMResponse(content="I don't know.")
