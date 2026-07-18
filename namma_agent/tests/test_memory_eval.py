"""The memory eval harness itself must work offline: with a stub model the
explicit-remember fallback stores every statement verbatim, so BM25 retrieval
should answer (nearly) every question in the built-in dataset."""
from __future__ import annotations

import json

from namma_agent.core.engram.evaluate import DATASET, format_report, run_eval
from namma_agent.core.providers.base import LLMResponse, Provider


class NullExtractor(Provider):
    """Extraction yields nothing (raw-text fallback stores the statement);
    resolution conservatively ADDs — the same behavior scripts/memory_eval.py
    --mock uses, so this test covers that path too."""

    name = "null"

    def __init__(self):
        super().__init__(model="null")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        if "Decide what to do" in messages[0]["content"]:   # the resolve prompt
            return LLMResponse(content=json.dumps(
                {"op": "ADD", "target": None, "core": None}))
        return LLMResponse(content="[]")


class ScriptedExtractor(Provider):
    """Extraction returns one structured fact; resolution returns ADD."""

    name = "scripted"

    def __init__(self):
        super().__init__(model="scripted")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        system = messages[0]["content"]
        if "Decide what to do" in system:            # the resolve prompt
            return LLMResponse(content=json.dumps(
                {"op": "ADD", "target": None, "core": None}))
        user = messages[-1]["content"]
        fact = user.split("USER:", 1)[-1].strip().splitlines()[0]
        return LLMResponse(content=json.dumps(
            [{"text": fact, "kind": "fact", "importance": 0.6}]))


def test_eval_scores_retrieval_with_null_extractor():
    report = run_eval(lambda: NullExtractor())
    assert report["total"] == len(DATASET)
    # Raw statements share keywords with their questions — BM25 must find most.
    assert report["recall_at_k"] >= 0.8, format_report(report)


def test_eval_runs_the_full_pipeline_with_extraction():
    report = run_eval(lambda: ScriptedExtractor())
    assert report["recall_at_k"] >= 0.8, format_report(report)


def test_format_report_marks_misses():
    report = {"k": 5, "total": 2, "hits": 1, "recall_at_k": 0.5,
              "cases": [{"question": "q1", "expect": "a", "hit": True, "top": []},
                        {"question": "q2", "expect": "b", "hit": False,
                         "top": ["something else"]}]}
    text = format_report(report)
    assert "[ok]" in text and "[MISS]" in text and "something else" in text
