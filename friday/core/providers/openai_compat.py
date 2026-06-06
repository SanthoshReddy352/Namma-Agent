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
import time
from typing import Optional

from friday.core.logger import logger

from .base import LLMResponse, Provider, ProviderError, TokenCallback, ToolCall


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
                    return self._generate_stream(client, body, on_token)
                return self._generate_once(client, body)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("[%s] attempt %d failed: %s", self.name, attempt + 1, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

        raise ProviderError(f"{self.name} failed after {self.max_retries} attempts: {last_exc}")

    def _generate_once(self, client, body: dict) -> LLMResponse:
        resp = client.chat.completions.create(**body)
        choice = resp.choices[0]
        msg = choice.message
        tool_calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))
        usage = getattr(resp, "usage", None)
        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            usage={
                "input_tokens": getattr(usage, "prompt_tokens", 0),
                "output_tokens": getattr(usage, "completion_tokens", 0),
            },
            finish_reason=choice.finish_reason or "",
            provider=self.name,
            model=self.model,
            raw=resp,
        )

    def _generate_stream(self, client, body: dict, on_token: Optional[TokenCallback]) -> LLMResponse:
        body = {**body, "stream": True}
        # Request usage in the final stream chunk when the endpoint supports it.
        body.setdefault("stream_options", {"include_usage": True})
        content_parts: list[str] = []
        # Accumulate tool-call deltas keyed by their streaming index.
        tool_acc: dict[int, dict] = {}
        finish_reason = ""
        usage = {}

        try:
            stream = client.chat.completions.create(**body)
        except TypeError:
            # Endpoint rejected stream_options; retry without it.
            body.pop("stream_options", None)
            stream = client.chat.completions.create(**body)

        for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = {
                    "input_tokens": getattr(chunk.usage, "prompt_tokens", 0),
                    "output_tokens": getattr(chunk.usage, "completion_tokens", 0),
                }
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            delta = choice.delta
            if getattr(delta, "content", None):
                content_parts.append(delta.content)
                if on_token:
                    on_token(delta.content)
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

        tool_calls = []
        for _, slot in sorted(tool_acc.items()):
            if not slot["name"]:
                continue
            try:
                args = json.loads(slot["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=slot["id"], name=slot["name"], args=args))

        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=finish_reason,
            provider=self.name,
            model=self.model,
        )
