"""Run the Engram memory eval (see namma_agent/core/engram/evaluate.py).

    python scripts/memory_eval.py            # against the configured provider
    python scripts/memory_eval.py --mock     # offline: retrieval quality only
    python scripts/memory_eval.py --min-score 0.8   # exit 1 below the bar

The default run seeds facts through the REAL write pipeline using the model the
user selected in Settings (the provider chain), so it measures extraction +
resolution + retrieval end to end. --mock replaces the model with a stub whose
extraction returns nothing (the explicit-remember fallback stores raw text), so
the score isolates the retrieval stack — useful on machines with no API key.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from namma_agent.core.engram.evaluate import format_report, run_eval  # noqa: E402
from namma_agent.core.providers.base import LLMResponse, Provider  # noqa: E402


class _MockProvider(Provider):
    """Extraction returns [] → the raw statement is stored verbatim; the resolve
    step conservatively ADDs (an unparseable resolve would NOOP the write away)."""

    name = "mock"

    def __init__(self):
        super().__init__(model="mock")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None,
                 on_thinking=None):
        if "Decide what to do" in messages[0]["content"]:   # the resolve prompt
            return LLMResponse(content='{"op": "ADD", "target": null, "core": null}')
        return LLMResponse(content="[]")


def main() -> int:
    ap = argparse.ArgumentParser(description="Engram memory eval")
    ap.add_argument("--mock", action="store_true",
                    help="offline: stub model, measures retrieval only")
    ap.add_argument("--k", type=int, default=5, help="recall@k (default 5)")
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="exit 1 if recall@k falls below this (0..1)")
    args = ap.parse_args()

    if args.mock:
        provider = _MockProvider()
    else:
        from namma_agent.config import load_config
        from namma_agent.core.providers import from_config

        provider = from_config(load_config())

    report = run_eval(lambda: provider, k=args.k)
    print(format_report(report))
    if report["recall_at_k"] < args.min_score:
        print(f"\nBELOW BAR: {report['recall_at_k']:.0%} < {args.min_score:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
