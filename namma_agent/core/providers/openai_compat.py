"""OpenAI-compatible provider.

This is the reference implementation of the OpenAI *chat.completions* wire
format. It powers:

  * the generic compat adapter — opencode, LM Studio (``http://localhost:1234/v1``),
    Ollama (``http://localhost:11434/v1``), Together, Groq, OpenRouter, or any
    endpoint that speaks ``/v1/chat/completions``; and
  * the native OpenAI adapter (:mod:`.openai_provider`), which subclasses this
    with OpenAI defaults.

Tool calling and streaming are both implemented here so every OpenAI-style
endpoint gets them for free.
"""
from __future__ import annotations

import json
import re
import time
from typing import Callable, Optional

from namma_agent.core.logger import logger

from .base import LLMResponse, Provider, ProviderError, ThinkingCallback, TokenCallback, ToolCall

# Many models served over OpenAI-compatible endpoints (qwen, DeepSeek-R1 on some
# hosts, Nemotron, …) don't use the separate `reasoning_content` field — they emit
# their chain-of-thought INLINE as <think>…</think> in the content stream. That
# reasoning must go to the thinking channel (the UI's Thinking section), never
# into the visible answer.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)


def _partial_tag_tail(buf: str, tag: str) -> int:
    """Length of the longest strict prefix of ``tag`` that ``buf`` ends with —
    i.e. how many trailing chars might still grow into the tag."""
    for k in range(min(len(tag) - 1, len(buf)), 0, -1):
        if buf.endswith(tag[:k]):
            return k
    return 0


class _ThinkTagSplitter:
    """Routes inline ``<think>…</think>`` reasoning onto the thinking channel and
    everything else onto the text channel. Tags can arrive split across stream
    chunks, so a possibly-partial tag tail is held back until it resolves."""

    def __init__(self, emit_text: Callable[[str], None], emit_think: Callable[[str], None]):
        self._text = emit_text
        self._think = emit_think
        self._buf = ""
        self._in_think = False

    def feed(self, chunk: str) -> None:
        self._buf += chunk
        while self._buf:
            tag = _THINK_CLOSE if self._in_think else _THINK_OPEN
            emit = self._think if self._in_think else self._text
            i = self._buf.find(tag)
            if i >= 0:
                if i:
                    emit(self._buf[:i])
                self._buf = self._buf[i + len(tag):]
                self._in_think = not self._in_think
                continue
            keep = _partial_tag_tail(self._buf, tag)
            if len(self._buf) > keep:
                emit(self._buf[: len(self._buf) - keep])
                self._buf = self._buf[len(self._buf) - keep:]
            return

    def flush(self) -> None:
        """Emit whatever is still held (stream ended mid-possible-tag)."""
        if self._buf:
            (self._think if self._in_think else self._text)(self._buf)
            self._buf = ""


class OpenAICompatProvider(Provider):
    name = "openai_compat"

    def __init__(self, model: str, **kwargs):
        super().__init__(model=model, **kwargs)
        # Endpoints reached over localhost (Ollama/LM Studio) usually need no key.
        self._key_optional = bool(self.base_url and "localhost" in self.base_url) or bool(
            self.base_url and "127.0.0.1" in self.base_url
        )

    def _requires_key(self) -> bool:
        return not self._key_optional

    def _client_importable(self) -> bool:
        try:
            import openai  # noqa: F401

            return True
        except ImportError:
            return False

    # -- client ------------------------------------------------------------

    def _client(self):
        from openai import OpenAI

        kwargs: dict = {"timeout": self.timeout_s}
        # Some local servers reject an empty key; send a placeholder.
        kwargs["api_key"] = self._api_key or "not-needed"
        if self.base_url:
            kwargs["base_url"] = self.base_url
        return OpenAI(**kwargs)

    # -- translation -------------------------------------------------------

    @staticmethod
    def _to_wire_messages(messages: list[dict]) -> list[dict]:
        """Translate neutral messages into OpenAI chat format."""
        out: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.get("tool_call_id", ""),
                        "content": m.get("content", ""),
                    }
                )
            elif role == "assistant" and m.get("tool_calls"):
                out.append(
                    {
                        "role": "assistant",
                        "content": m.get("content") or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {"name": tc.name, "arguments": json.dumps(tc.args)},
                            }
                            for tc in m["tool_calls"]
                        ],
                    }
                )
            else:
                out.append({"role": role, "content": m.get("content", "")})
        return out

    @staticmethod
    def _to_wire_tools(tools: Optional[list[dict]]) -> Optional[list[dict]]:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("parameters", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    # -- generate ----------------------------------------------------------

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        on_token: Optional[TokenCallback] = None,
        on_thinking: Optional[ThinkingCallback] = None,
    ) -> LLMResponse:
        client = self._client()
        wire_messages = self._to_wire_messages(messages)
        wire_tools = self._to_wire_tools(tools)

        body: dict = {
            "model": self.model,
            "messages": wire_messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if wire_tools:
            body["tools"] = wire_tools

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                if stream:
                    return self._generate_stream(client, body, on_token, on_thinking)
                return self._generate_once(client, body)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("[%s] attempt %d failed: %s", self.name, attempt + 1, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

        raise ProviderError(f"{self.name} failed after {self.max_retries} attempts: {last_exc}")

    @staticmethod
    def _usage(usage) -> dict:
        """Normalize OpenAI usage. `prompt_tokens` already *includes* cached input,
        so split the cached portion out into its own bucket (it's billed cheaply and
        must not be counted as fresh input)."""
        if usage is None:
            return {}
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        return {
            "input_tokens": max(prompt - cached, 0),
            "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cache_read_tokens": cached,
        }

    def _generate_once(self, client, body: dict) -> LLMResponse:
        resp = client.chat.completions.create(**body)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                args = {"_json_error": str(exc), "_raw_args": tc.function.arguments}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
        usage = getattr(resp, "usage", None)
        # Inline <think>…</think> reasoning never belongs in the answer. The
        # non-streamed path has no thinking channel, so it's simply stripped.
        content = _THINK_BLOCK_RE.sub("", msg.content or "").strip()
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=self._usage(usage),
            finish_reason=choice.finish_reason or "",
            provider=self.name,
            model=self.model,
            raw=resp,
        )

    def _generate_stream(self, client, body: dict, on_token: Optional[TokenCallback],
                         on_thinking: Optional[ThinkingCallback] = None) -> LLMResponse:
        body = {**body, "stream": True}
        # Request usage in the final stream chunk when the endpoint supports it.
        body.setdefault("stream_options", {"include_usage": True})
        content_parts: list[str] = []
        # Accumulate tool-call deltas keyed by their streaming index.
        tool_acc: dict[int, dict] = {}
        finish_reason = ""
        usage = {}

        # Content deltas run through the <think>-tag splitter: reasoning goes to
        # the thinking channel (or is dropped when no listener), the answer text
        # to the token stream + the final content. Models that use the separate
        # reasoning_content field never emit the tags, so this is a pass-through.
        def _emit_text(s: str) -> None:
            content_parts.append(s)
            if on_token:
                on_token(s)

        def _emit_think(s: str) -> None:
            if on_thinking:
                on_thinking(s)

        splitter = _ThinkTagSplitter(_emit_text, _emit_think)

        try:
            stream = client.chat.completions.create(**body)
        except TypeError:
            # Endpoint rejected stream_options; retry without it.
            body.pop("stream_options", None)
            stream = client.chat.completions.create(**body)

        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = self._usage(chunk.usage)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            # Reasoning models (DeepSeek-R1, some OpenAI-compatible endpoints) stream
            # their chain-of-thought separately as `reasoning_content` / `reasoning`.
            # Surface it on the thinking channel; never mix it into the answer.
            if on_thinking:
                think = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
                if think:
                    on_thinking(think)
            if getattr(delta, "content", None):
                splitter.feed(delta.content)
            for tcd in (getattr(delta, "tool_calls", None) or []):
                slot = tool_acc.setdefault(tcd.index, {"id": "", "name": "", "args": ""})
                if tcd.id:
                    slot["id"] = tcd.id
                if tcd.function and tcd.function.name:
                    slot["name"] += tcd.function.name
                if tcd.function and tcd.function.arguments:
                    slot["args"] += tcd.function.arguments
            if choice.finish_reason:
                finish_reason = choice.finish_reason
        splitter.flush()

        tool_calls = []
        for _, slot in sorted(tool_acc.items()):
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError as exc:
                args = {"_json_error": str(exc), "_raw_args": slot["args"]}
            tool_calls.append(ToolCall(id=slot["id"], name=slot["name"], args=args))

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
            provider=self.name,
            model=self.model,
        )
