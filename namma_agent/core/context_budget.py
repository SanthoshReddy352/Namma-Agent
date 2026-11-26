"""Two-phase in-turn context compaction (PROGRESS.md Phase 2).

A long tool loop keeps every tool result in the working message list, so the
prompt grows with each step until the model's context window overflows. Before
each model call the agent checks the estimated prompt size against a fraction
(default 60%) of the model's context window and, when it is over:

1. **Clear old tool outputs.** Every tool result except the newest few is
   replaced by a one-line placeholder. Cheap, deterministic, and the call/result
   pairing stays intact, so the transcript remains valid for every provider.
2. **Template summary.** If that isn't enough, the earlier conversation
   history (the turns loaded from the database, before this turn) is condensed
   by one model call into a fixed-section summary that is appended to the
   system prompt, and those history messages are dropped.

Both phases are rare by design (most turns never reach 60%); each one is
reported as a ``context_compacted`` event and logged in the usage log as
``compaction``.
"""
from __future__ import annotations

import json
from typing import Any, Callable, Optional

from namma_agent.core.logger import logger

DEFAULT_FRACTION = 0.6
#: Newest tool results kept verbatim by phase 1.
KEEP_TOOL_RESULTS = 4
#: Tool results shorter than this aren't worth clearing.
_MIN_CLEAR_CHARS = 400
CLEARED = ("[Output cleared to save context — it was read earlier in this turn. "
           "Re-run the tool if you need it again.]")

_SUMMARY_TEMPLATE = (
    "Condense the EARLIER part of a conversation between a user and their "
    "assistant so the assistant can continue without it. Use exactly these "
    "sections, terse bullet points, at most 250 words in total:\n"
    "Goal: what the user is trying to achieve.\n"
    "Decisions & facts: things established (names, numbers, preferences).\n"
    "Files, paths & commands: anything concrete the work depends on.\n"
    "Current state: what has been done and what is in progress.\n"
    "Open questions: unresolved threads.\n"
    "Output only the summary."
)

# Context windows by model-id substring, most specific first. A model profile's
# ``context_window`` overrides this; unknown models get the conservative default.
_WINDOWS: tuple[tuple[str, int], ...] = (
    ("gpt-4.1", 1_000_000), ("gemini", 1_000_000),
    ("gpt-5", 400_000),
    ("claude", 200_000), ("o1", 200_000), ("o3", 200_000), ("o4", 200_000),
    ("gpt-4o", 128_000), ("deepseek", 128_000), ("grok", 128_000),
    ("kimi", 128_000), ("glm", 128_000), ("qwen", 32_768), ("llama", 32_768),
    ("mistral", 32_768), ("gemma", 32_768), ("phi", 16_384),
)
DEFAULT_WINDOW = 128_000


def context_window(provider: Any) -> int:
    explicit = int(getattr(provider, "context_window", 0) or 0)
    if explicit > 0:
        return explicit
    model = str(getattr(provider, "model", "") or "").lower()
    for needle, size in _WINDOWS:
        if needle in model:
            return size
    return DEFAULT_WINDOW


def estimate_tokens(messages: list[dict], tool_defs: Optional[list[dict]] = None) -> int:
    """Rough prompt size (~4 characters per token) — good enough for a 60% gate."""
    chars = 0
    for m in messages:
        chars += len(str(m.get("content") or "")) + 16
        for tc in m.get("tool_calls") or []:
            chars += len(getattr(tc, "name", "")) + len(json.dumps(getattr(tc, "args", {}) or {},
                                                                   default=str))
    if tool_defs:
        chars += len(json.dumps(tool_defs, default=str))
    return chars // 4


def clear_old_tool_outputs(messages: list[dict], keep: int = KEEP_TOOL_RESULTS) -> int:
    """Phase 1 (in place): blank all but the newest ``keep`` tool results.
    Returns how many were cleared."""
    tool_idx = [i for i, m in enumerate(messages)
                if m.get("role") == "tool" and len(str(m.get("content") or "")) >= _MIN_CLEAR_CHARS
                and m.get("content") != CLEARED]
    victims = tool_idx[:-keep] if keep > 0 else tool_idx
    for i in victims:
        messages[i] = {**messages[i], "content": CLEARED}
    return len(victims)


def summarize_history(messages: list[dict], history_end: int,
                      generate: Callable[[list[dict]], str]) -> Optional[list[dict]]:
    """Phase 2: condense ``messages[1:history_end]`` (earlier turns) into the
    system prompt. Returns the new list, or None when there is nothing to fold
    or the summary call failed."""
    history = messages[1:history_end]
    if not history or not messages or messages[0].get("role") != "system":
        return None
    convo = "\n".join(f"{m.get('role')}: {str(m.get('content') or '')[:1500]}"
                      for m in history)[:24000]
    try:
        summary = (generate([{"role": "system", "content": _SUMMARY_TEMPLATE},
                             {"role": "user", "content": convo}]) or "").strip()
    except Exception as exc:  # noqa: BLE001 — compaction must never break a turn
        logger.warning("[context] history summary failed: %s", exc)
        return None
    if not summary:
        return None
    system = {**messages[0], "content": (
        messages[0]["content"] + "\n\nEARLIER IN THIS CONVERSATION (condensed to fit "
        "the context window; details can be re-checked with search_conversations):\n"
        + summary[:4000])}
    return [system, *messages[history_end:]]


def fit(messages: list[dict], history_end: int, provider: Any,
        tool_defs: Optional[list[dict]], generate: Callable[[list[dict]], str],
        fraction: float = DEFAULT_FRACTION,
        emit: Optional[Callable[[dict], None]] = None) -> tuple[list[dict], int]:
    """Bring ``messages`` under ``fraction`` of the provider's window.

    Returns ``(messages, history_end)`` — the list may be a new object after
    phase 2, and ``history_end`` (index of the first message of THIS turn)
    shifts accordingly."""
    if fraction <= 0:
        return messages, history_end
    window = context_window(provider)
    limit = int(window * min(fraction, 0.95))
    before = estimate_tokens(messages, tool_defs)
    if before <= limit:
        return messages, history_end
    cleared = clear_old_tool_outputs(messages)
    after = estimate_tokens(messages, tool_defs)
    if cleared:
        logger.info("[context] phase 1: cleared %d old tool output(s) (%d → %d est. tokens, "
                    "limit %d)", cleared, before, after, limit)
        if emit:
            emit({"phase": 1, "cleared": cleared, "before": before, "after": after,
                  "limit": limit})
    if after <= limit:
        return messages, history_end
    folded = summarize_history(messages, history_end, generate)
    if folded is None:
        return messages, history_end
    dropped = history_end - 1
    final = estimate_tokens(folded, tool_defs)
    logger.info("[context] phase 2: folded %d history message(s) into a summary "
                "(%d → %d est. tokens)", dropped, after, final)
    if emit:
        emit({"phase": 2, "folded": dropped, "before": after, "after": final, "limit": limit})
    return folded, 1
