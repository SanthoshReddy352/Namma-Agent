"""Inline <think>…</think> reasoning handling in the OpenAI-compatible provider:
the splitter routes it to the thinking channel and keeps it out of the answer."""
from __future__ import annotations

from namma_agent.core.providers.openai_compat import (
    _THINK_BLOCK_RE, _ThinkTagSplitter, _partial_tag_tail,
)


def _run(chunks):
    text, think = [], []
    s = _ThinkTagSplitter(text.append, think.append)
    for c in chunks:
        s.feed(c)
    s.flush()
    return "".join(text), "".join(think)


def test_plain_text_passes_through():
    text, think = _run(["Hello ", "world"])
    assert text == "Hello world"
    assert think == ""


def test_think_block_routed_to_thinking():
    text, think = _run(["<think>step one</think>", "The answer."])
    assert think == "step one"
    assert text == "The answer."


def test_tags_split_across_chunks():
    text, think = _run(["<th", "ink>reason", "ing</thi", "nk>ans", "wer"])
    assert think == "reasoning"
    assert text == "answer"


def test_partial_open_tag_that_never_completes_is_text():
    # "<thin" arrives and the stream ends — it must be flushed as answer text.
    text, think = _run(["a <thin"])
    assert text == "a <thin"
    assert think == ""


def test_unclosed_think_flushes_to_thinking():
    text, think = _run(["<think>ran out of tokens"])
    assert think == "ran out of tokens"
    assert text == ""


def test_multiple_think_blocks():
    text, think = _run(["<think>a</think>x<think>b</think>y"])
    assert think == "ab"
    assert text == "xy"


def test_partial_tag_tail():
    assert _partial_tag_tail("hello <", "<think>") == 1
    assert _partial_tag_tail("hello <think", "<think>") == 6
    assert _partial_tag_tail("hello", "<think>") == 0
    # A full tag is not a *partial* tail (find() would have consumed it).
    assert _partial_tag_tail("x</think", "</think>") == 7


def test_nonstream_strip_regex():
    cleaned = _THINK_BLOCK_RE.sub("", "<think>chain\nof thought</think>\nFinal answer.")
    assert cleaned.strip() == "Final answer."
