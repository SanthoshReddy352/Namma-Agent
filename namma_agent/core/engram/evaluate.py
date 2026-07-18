"""Engram memory eval — does the memory actually remember?

Seeds a small dataset of user statements through the REAL write pipeline
(salience gate → extraction → resolution → store), then asks recall questions
and scores recall@k: a case is a hit when the expected answer substring appears
in the top-k recalled texts. Run it two ways:

  * against the configured provider (scripts/memory_eval.py) — measures the
    whole pipeline including the model's extraction quality;
  * with a mock provider (scripts/memory_eval.py --mock, and the offline test) —
    extraction returns nothing, the explicit-remember fallback stores the raw
    text, so the score isolates RETRIEVAL quality (BM25/graph/vector fusion).

The point is a regression needle: unit tests prove the plumbing, this proves
the system answers "what is my register number?" after being told once.
"""
from __future__ import annotations

from typing import Callable, Optional

from namma_agent.core.engram import Engram
from namma_agent.core.memory import Database

#: (what the user said once) → (how they ask later, what the answer must contain)
DATASET: list[dict] = [
    {"fact": "My register number is 99240040721",
     "question": "what is my register number?", "expect": "99240040721"},
    {"fact": "I study B.Tech CSE with an AI and ML specialization at KARE",
     "question": "where do I study and what course?", "expect": "KARE"},
    {"fact": "My dog is called Bruno and he is a golden retriever",
     "question": "what's my dog's name?", "expect": "Bruno"},
    {"fact": "I prefer answers in Telugu when we talk casually",
     "question": "which language do I prefer for casual replies?", "expect": "Telugu"},
    {"fact": "My best friend Ravi works at Infosys in Hyderabad",
     "question": "where does Ravi work?", "expect": "Infosys"},
    {"fact": "The wifi password at home is sunflower42",
     "question": "what's my home wifi password?", "expect": "sunflower42"},
    {"fact": "I am allergic to peanuts, never suggest recipes with them",
     "question": "do I have any food allergies?", "expect": "peanut"},
    {"fact": "My final-year project is a drone that maps crop health",
     "question": "what is my final year project about?", "expect": "drone"},
    {"fact": "Mom's birthday is on March 14th",
     "question": "when is my mom's birthday?", "expect": "March 14"},
    {"fact": "I use VS Code as my main editor and dark mode everywhere",
     "question": "which code editor do I use?", "expect": "VS Code"},
    {"fact": "My laptop is a ThinkPad T14 running Windows 11",
     "question": "what laptop do I have?", "expect": "ThinkPad"},
    {"fact": "I bank with SBI and my branch is in Krishnankoil",
     "question": "which bank do I use?", "expect": "SBI"},
]


def run_eval(provider_getter: Callable[[], object], k: int = 5,
             dataset: Optional[list[dict]] = None,
             embedder=None) -> dict:
    """Seed → recall → score. Fresh in-memory DB, real pipeline, no threads."""
    dataset = dataset or DATASET
    db = Database(":memory:")
    eng = Engram(db, config={"database": {"path": ":memory:"}},
                 provider_getter=provider_getter)
    if embedder is not None:
        eng.embedder = embedder
        eng.writer.embedder = embedder

    for case in dataset:
        # explicit=True: if extraction yields nothing (mock/weak model), the raw
        # statement itself is stored — so retrieval is always measurable.
        eng.writer.process(case["fact"], source="eval", explicit=True)

    cases = []
    hits = 0
    for case in dataset:
        results = eng.recall(case["question"], k=k)
        texts = [r.get("text", "") for r in results]
        hit = any(case["expect"].lower() in t.lower() for t in texts)
        hits += hit
        cases.append({"question": case["question"], "expect": case["expect"],
                      "hit": hit, "top": texts[:3]})
    total = len(dataset)
    return {"total": total, "hits": hits,
            "recall_at_k": round(hits / total, 3) if total else 0.0,
            "k": k, "cases": cases}


def format_report(report: dict) -> str:
    lines = [f"Memory eval — recall@{report['k']}: "
             f"{report['hits']}/{report['total']} = {report['recall_at_k']:.0%}", ""]
    for c in report["cases"]:
        # ASCII markers — Windows consoles often can't print ✓/✗ (cp1252).
        mark = "[ok]  " if c["hit"] else "[MISS]"
        lines.append(f" {mark} {c['question']}  (expect: {c['expect']})")
        if not c["hit"]:
            for t in c["top"]:
                lines.append(f"     · {t[:90]}")
    return "\n".join(lines)
