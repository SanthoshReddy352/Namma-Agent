"""AWS Bedrock provider (Converse API via boto3).

Credentials come from boto3's normal chain — env keys, ``AWS_PROFILE`` / SSO,
an instance role — or a Bedrock API key in ``AWS_BEARER_TOKEN_BEDROCK`` (boto3
reads it itself). The region comes from ``region`` (config), ``AWS_REGION`` /
``AWS_DEFAULT_REGION``, or the ``bedrock-runtime.<region>.amazonaws.com`` host
in ``base_url``; default ``us-east-1``.

boto3 is OPTIONAL: without it the provider reports "install boto3" instead of
crashing (``pip install boto3``).
"""
from __future__ import annotations

import os
import re
import time
from typing import Optional

from namma_agent.core.logger import logger

from .base import LLMResponse, Provider, ProviderError, ThinkingCallback, TokenCallback, ToolCall

_DEFAULT_HOST_RE = re.compile(r"^https://bedrock-runtime\.([a-z0-9-]+)\.amazonaws\.com/?$")


class BedrockProvider(Provider):
    name = "bedrock"

    def __init__(self, model: str = "us.anthropic.claude-sonnet-4-6", region: str = "", **kwargs):
        kwargs.setdefault("api_key_env", "AWS_BEARER_TOKEN_BEDROCK")
        super().__init__(model=model, **kwargs)
        host = _DEFAULT_HOST_RE.match(self.base_url or "")
        self.region = (region or (self.extra.get("region") if self.extra else "")
                       or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
                       or (host.group(1) if host else "") or "us-east-1")
        # A non-standard base_url (VPC endpoint, proxy) is passed through as-is.
        self._endpoint = None if (not self.base_url or host) else self.base_url

    def _default_key_env(self) -> str:
        return "AWS_BEARER_TOKEN_BEDROCK"

    def _requires_key(self) -> bool:
        return False                      # boto3's credential chain decides

    def _client_importable(self) -> bool:
        try:
            import boto3  # noqa: F401
            return True
        except ImportError:
            return False

    def unavailable_reason(self) -> str:
        if not self._client_importable():
            return "AWS Bedrock needs boto3 — install it with: pip install boto3"
        return ""

    def _client(self):
        import boto3
        kwargs: dict = {"region_name": self.region}
        if self._endpoint:
            kwargs["endpoint_url"] = self._endpoint
        try:
            from botocore.config import Config
            kwargs["config"] = Config(read_timeout=self.timeout_s, retries={"max_attempts": 1})
        except ImportError:  # pragma: no cover - botocore ships with boto3
            pass
        return boto3.client("bedrock-runtime", **kwargs)

    # -- translation -------------------------------------------------------

    @staticmethod
    def _to_wire_messages(messages: list[dict]) -> list[dict]:
        """Neutral messages → Converse ``messages`` (strict user/assistant turns).

        Tool results become a *user* turn of ``toolResult`` blocks; consecutive
        same-role turns are merged, as Converse rejects two in a row."""
        out: list[dict] = []

        def push(role: str, blocks: list[dict]) -> None:
            if not blocks:
                return
            if out and out[-1]["role"] == role:
                out[-1]["content"].extend(blocks)
            else:
                out.append({"role": role, "content": blocks})

        for m in messages:
            role = m.get("role")
            if role == "tool":
                push("user", [{"toolResult": {
                    "toolUseId": m.get("tool_call_id", ""),
                    "content": [{"text": str(m.get("content", "") or "(empty)")}]}}])
            elif role == "assistant":
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"text": m["content"]})
                for tc in m.get("tool_calls") or []:
                    blocks.append({"toolUse": {"toolUseId": tc.id, "name": tc.name,
                                               "input": tc.args or {}}})
                push("assistant", blocks)
            elif role == "user":
                content = m.get("content", "")
                if content:
                    push("user", [{"text": content}])
        return out

    @staticmethod
    def _to_wire_tools(tools: Optional[list[dict]]) -> Optional[dict]:
        if not tools:
            return None
        return {"tools": [{"toolSpec": {
            "name": t["name"], "description": t.get("description", "") or t["name"],
            "inputSchema": {"json": t.get("parameters") or {"type": "object", "properties": {}}},
        }} for t in tools]}

    def _parse(self, resp: dict) -> LLMResponse:
        msg = ((resp or {}).get("output") or {}).get("message") or {}
        text: list[str] = []
        reasoning: list[str] = []
        calls: list[ToolCall] = []
        for block in msg.get("content") or []:
            if "text" in block:
                text.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                calls.append(ToolCall(id=tu.get("toolUseId", ""), name=tu.get("name", ""),
                                      args=tu.get("input") if isinstance(tu.get("input"), dict) else {}))
            elif "reasoningContent" in block:
                rt = (block["reasoningContent"].get("reasoningText") or {}).get("text", "")
                if rt:
                    reasoning.append(rt)
        usage = resp.get("usage") or {}
        return LLMResponse(
            content="".join(text), tool_calls=calls, reasoning_content="".join(reasoning),
            usage={"input_tokens": usage.get("inputTokens", 0) or 0,
                   "output_tokens": usage.get("outputTokens", 0) or 0,
                   "cache_read_tokens": usage.get("cacheReadInputTokens", 0) or 0,
                   "cache_write_tokens": usage.get("cacheWriteInputTokens", 0) or 0},
            finish_reason=resp.get("stopReason", "") or "", provider=self.name,
            model=self.model, raw=resp)

    # -- generate ----------------------------------------------------------

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        on_token: Optional[TokenCallback] = None,
        on_thinking: Optional[ThinkingCallback] = None,
    ) -> LLMResponse:
        if not self._client_importable():
            raise ProviderError(self.unavailable_reason())
        system_text, convo = self.split_system(messages)
        body: dict = {
            "modelId": self.model,
            "messages": self._to_wire_messages(convo),
            "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": self.temperature},
        }
        if system_text:
            body["system"] = [{"text": system_text}]
        tool_cfg = self._to_wire_tools(tools)
        if tool_cfg:
            body["toolConfig"] = tool_cfg
        client = self._client()
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                result = self._parse(client.converse(**body))
                # Converse is one-shot here; a streaming caller still gets the
                # text through its callbacks, just in one piece.
                if stream:
                    if on_thinking and result.reasoning_content:
                        on_thinking(result.reasoning_content)
                    if on_token and result.content:
                        on_token(result.content)
                return result
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("[bedrock] attempt %d failed: %s", attempt + 1, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
        raise ProviderError(f"bedrock failed after {self.max_retries} attempts: {last_exc}")
