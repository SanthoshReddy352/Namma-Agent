"""Run the delegation eval (see namma_agent/core/delegation_eval.py).

    python scripts/delegation_eval.py                 # configured model (spends tokens)
    python scripts/delegation_eval.py --model gpt-5   # a specific model profile id
    python scripts/delegation_eval.py --mock          # offline: harness plumbing only
    python scripts/delegation_eval.py --min-score 0.85   # exit 1 below the bar
    python scripts/delegation_eval.py --openai-model gpt-5-mini --max-tokens 1500000
        # native OpenAI with OPENAI_API_KEY from the environment, hard token cap

Twenty small delegations over a seeded scratch workspace (single lookups,
multi-step file work, context-only answers, fan-out, an orchestrator split, a
step budget) through the real DelegationManager and real file tools. The
default run uses the model you picked in Settings (or ``--model``); ``--mock``
swaps in an oracle brain, which proves the harness works but says nothing about
model quality. Phase 3's acceptance bar is 0.85.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from namma_agent.core.delegation_eval import (  # noqa: E402
    CappedProvider, OracleProvider, format_report, run_eval,
)


def _configured_provider(model_id: str):
    """The user's real brain, resolved the way the app does (model profiles,
    provider fallback) — without starting MCP servers, comms or runners."""
    from namma_agent.config import load_config
    from namma_agent.core.memory import Database
    from namma_agent.core.tools import ToolRegistry
    from namma_agent.service import NammaAgentService

    svc = NammaAgentService(config=load_config(), registry=ToolRegistry(),
                            db=Database(":memory:"))
    return svc.provider_for(model_id or None)


def main() -> int:
    ap = argparse.ArgumentParser(description="Delegation eval (20 tasks)")
    ap.add_argument("--mock", action="store_true",
                    help="offline oracle brain: checks the harness, not the model")
    ap.add_argument("--model", default="", help="model profile id (default: your first)")
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="exit 1 if the pass rate falls below this (0..1)")
    ap.add_argument("--openai-model", default="",
                    help="use native OpenAI with this model id and OPENAI_API_KEY from "
                         "the environment (skips your configured models)")
    ap.add_argument("--max-tokens", type=int, default=1_000_000,
                    help="HARD cap on total tokens across every call (default 1,000,000)")
    args = ap.parse_args()
    if args.mock:
        provider = OracleProvider()
    elif args.openai_model:
        from namma_agent.core.providers.openai_provider import OpenAIProvider
        # 8K output leaves reasoning models room to think AND answer.
        provider = OpenAIProvider(model=args.openai_model, max_tokens=8192,
                                  timeout_s=120, max_retries=2)
    else:
        provider = _configured_provider(args.model)
    if not args.mock:
        provider = CappedProvider(provider, cap=args.max_tokens)
    report = run_eval(provider)
    print(format_report(report))
    return 1 if report["score"] < args.min_score else 0


if __name__ == "__main__":
    raise SystemExit(main())
