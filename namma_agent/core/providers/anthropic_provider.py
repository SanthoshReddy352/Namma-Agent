"""Native Anthropic (Claude) provider.

Uses the Messages API with native ``tool_use`` blocks (higher fidelity than the
OpenAI-compat proxy) and **prompt caching** on the system block and tool
definitions to cut cost/latency on multi-turn tool loops.

Requires ``pip install anthropic`` and ``ANTHROPIC_API_KEY``.
"""
from __future__ import annotations

import time
from typing import Optional

from namma_agent.core.logger import logger

from .base import LLMResponse, Provider, ProviderError, ThinkingCallback, TokenCallback, ToolCall


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-6", **kwargs):
        kwargs.setdefault("api_key_env", "ANTHROPIC_API_KEY")
        super().__init__(model=model, **kwargs)

    def _default_key_env(self) -> str:
        return "ANTHROPIC_API_KEY"

    def _client_importable(self) -> bool:
        try:
            import anthropic  # noqa: F401

            return True
        except ImportError:
            return False

    # -- translation -------------------------------------------------------

    @staticmethod
    def _to_wire_messages(messages: list[dict]) -> list[dict]:
        """Translate neutral messages into Anthropic content-block format.

        - assistant tool calls  -> content blocks ``{"type": "tool_use", ...}``
        - tool results          -> a *user* message with ``{"type": "tool_result"}``
        Consecutive tool results are merged into one user message so the API
        sees the expected user/assistant alternation.
        """
        out: list[dict] = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            elif role == "assistant" and m.get("tool_calls"):
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    blocks.append({"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.args})
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": role, "content": m.get("content", "")})
        # Cache the conversation prefix: drop an ephemeral breakpoint on the last
        # block so the next tool-loop step re-reads everything up to here from the
        # cache instead of re-billing it as fresh input. This is what stops a deep
        # tool loop from paying full input price for the whole (growing) prefix on
        # every single step.
        AnthropicProvider._cache_last_block(out)
        return out

    @staticmethod
    def _cache_last_block(out: list[dict]) -> None:
        if not out:
            return
        content = out[-1].get("content")
        if isinstance(content, str):
            if content:  # skip empty strings — an empty text block is rejected
                out[-1]["content"] = [
                    {"type": "text", "text": content, "cache_control": {"type": "ephemeral"}}
                ]
        elif isinstance(content, list) and content:
            content[-1] = {**content[-1], "cache_control": {"type": "ephemeral"}}

    @staticmethod
    def _to_wire_tools(tools: Optional[list[dict]]) -> Optional[list[dict]]:
        if not tools:
            return None
        wire = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
            }
            for t in tools
        ]
        # Cache the (stable) tool definitions across turns.
        wire[-1]["cache_control"] = {"type": "ephemeral"}
        return wire

    # -- generate ----------------------------------------------------------

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        on_token: Optional[TokenCallback] = None,
        on_thinking: Optional[ThinkingCallback] = None,
    ) -> LLMResponse:
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key, timeout=self.timeout_s)
        system_text, convo = self.split_system(messages)
        wire_messages = self._to_wire_messages(convo)
        wire_tools = self._to_wire_tools(tools)

        system_param = anthropic.NOT_GIVEN
        if system_text:
            system_param = [
                {"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}
            ]

        body: dict = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_param,
            "messages": wire_messages,
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
                logger.warning("[anthropic] attempt %d failed: %s", attempt + 1, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

        raise ProviderError(f"anthropic failed after {self.max_retries} attempts: {last_exc}")

    def _parse_blocks(self, resp) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                content_parts.append(block.text)
            elif block.type == "tool_use":
                args = block.input if isinstance(block.input, dict) else {}
                tool_calls.append(ToolCall(id=block.id, name=block.name, args=args))
        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage={
                "input_tokens": getattr(resp.usage, "input_tokens", 0),
                "output_tokens": getattr(resp.usage, "output_tokens", 0),
                "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
                "cache_write_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
            },
            finish_reason=getattr(resp, "stop_reason", "") or "",
            provider=self.name,
            model=self.model,
            raw=resp,
        )

    def _generate_once(self, client, body: dict) -> LLMResponse:
        resp = client.messages.create(**body)
        return self._parse_blocks(resp)

    def _generate_stream(self, client, body: dict, on_token: Optional[TokenCallback],
                         on_thinking: Optional[ThinkingCallback] = None) -> LLMResponse:
        # Iterate raw stream events so we can split `text_delta` (the visible answer)
        # from `thinking_delta` (extended-thinking reasoning) onto their own channels.
        # Draining the loop fully is required either way to reach the final message.
        with client.messages.stream(**body) as stream:
            for event in stream:
                if getattr(event, "type", "") != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", "")
                if dtype == "text_delta" and on_token:
                    on_token(delta.text)
                elif dtype == "thinking_delta" and on_thinking:
                    on_thinking(getattr(delta, "thinking", "") or "")
            final = stream.get_final_message()
        return self._parse_blocks(final)
