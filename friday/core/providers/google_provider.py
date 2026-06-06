"""Native Google Gemini provider.

Uses the ``google-genai`` SDK (``from google import genai``) with native
``function_declarations`` for tool calling.

Requires ``pip install google-genai`` and ``GOOGLE_API_KEY`` (or ``GEMINI_API_KEY``).
"""
from __future__ import annotations

import time
from typing import Optional

from friday.core.logger import logger

from .base import LLMResponse, Provider, ProviderError, TokenCallback, ToolCall


class GoogleProvider(Provider):
    name = "google"

    def __init__(self, model: str = "gemini-2.5-flash", **kwargs):
        kwargs.setdefault("api_key_env", "GOOGLE_API_KEY")
        super().__init__(model=model, **kwargs)

    def _default_key_env(self) -> str:
        # Accept either GOOGLE_API_KEY or GEMINI_API_KEY.
        import os

        if os.environ.get("GOOGLE_API_KEY"):
            return "GOOGLE_API_KEY"
        return "GEMINI_API_KEY"

    def _client_importable(self) -> bool:
        try:
            from google import genai  # noqa: F401

            return True
        except ImportError:
            return False

    # -- translation -------------------------------------------------------

    def _to_contents(self, messages: list[dict]):
        """Translate neutral messages into a list of genai ``Content`` objects."""
        from google.genai import types

        contents = []
        for m in messages:
            role = m.get("role")
            if role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=m.get("name", "tool"),
                                response={"result": m.get("content", "")},
                            )
                        ],
                    )
                )
            elif role == "assistant" and m.get("tool_calls"):
                parts = []
                if m.get("content"):
                    parts.append(types.Part(text=m["content"]))
                for tc in m["tool_calls"]:
                    parts.append(
                        types.Part(function_call=types.FunctionCall(name=tc.name, args=tc.args))
                    )
                contents.append(types.Content(role="model", parts=parts))
            else:
                wire_role = "model" if role == "assistant" else "user"
                contents.append(
                    types.Content(role=wire_role, parts=[types.Part(text=m.get("content", ""))])
                )
        return contents

    def _to_config(self, system_text: str, tools: Optional[list[dict]]):
        from google.genai import types

        config_kwargs: dict = {
            "max_output_tokens": self.max_tokens,
            "temperature": self.temperature,
        }
        if system_text:
            config_kwargs["system_instruction"] = system_text
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters=t.get("parameters", {"type": "object", "properties": {}}),
                )
                for t in tools
            ]
            config_kwargs["tools"] = [types.Tool(function_declarations=declarations)]
        return types.GenerateContentConfig(**config_kwargs)

    # -- generate ----------------------------------------------------------

    def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
        on_token: Optional[TokenCallback] = None,
    ) -> LLMResponse:
        from google import genai

        client = genai.Client(api_key=self._api_key)
        system_text, convo = self.split_system(messages)
        contents = self._to_contents(convo)
        config = self._to_config(system_text, tools)

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                if stream:
                    return self._generate_stream(client, contents, config, on_token)
                resp = client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                return self._parse(resp)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning("[google] attempt %d failed: %s", attempt + 1, exc)
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)

        raise ProviderError(f"google failed after {self.max_retries} attempts: {last_exc}")

    def _parse(self, resp) -> LLMResponse:
        content_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        candidates = getattr(resp, "candidates", None) or []
        if candidates:
            parts = getattr(candidates[0].content, "parts", None) or []
            for i, part in enumerate(parts):
                if getattr(part, "text", None):
                    content_parts.append(part.text)
                fc = getattr(part, "function_call", None)
                if fc:
                    args = dict(fc.args) if fc.args else {}
                    tool_calls.append(ToolCall(id=f"{fc.name}_{i}", name=fc.name, args=args))
        usage = getattr(resp, "usage_metadata", None)
        return LLMResponse(
            content="".join(content_parts),
            tool_calls=tool_calls,
            usage={
                "input_tokens": getattr(usage, "prompt_token_count", 0) if usage else 0,
                "output_tokens": getattr(usage, "candidates_token_count", 0) if usage else 0,
            },
            provider=self.name,
            model=self.model,
            raw=resp,
        )

    def _generate_stream(self, client, contents, config, on_token: Optional[TokenCallback]) -> LLMResponse:
        last = None
        for chunk in client.models.generate_content_stream(
            model=self.model, contents=contents, config=config
        ):
            last = chunk
            if on_token and getattr(chunk, "text", None):
                on_token(chunk.text)
        # The streamed chunks accumulate; parse the final aggregate where the
        # SDK exposes it, else fall back to the last chunk.
        return self._parse(last) if last is not None else LLMResponse(provider=self.name, model=self.model)
