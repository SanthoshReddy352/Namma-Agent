"""Tool registry for FRIDAY v2.

A tool is ``{name, description, parameters(JSON Schema), handler}``. The registry
emits provider-neutral tool definitions (the agent passes them straight to any
provider) and executes handlers, normalizing the result into a string the model
can read.

This replaces the legacy stack — no YAML catalog, no embedding router, no intent
recognizer. The model picks the tool from the schema; the registry just runs it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from friday.core.logger import logger

#: A handler takes the parsed argument dict and returns anything stringifiable.
Handler = Callable[[dict], Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema (object)
    handler: Handler
    destructive: bool = False  # gated behind approval when True

    def definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters or {"type": "object", "properties": {}},
        }


@dataclass
class ToolResult:
    ok: bool
    content: str  # what the model sees
    data: Any = None
    error: str = ""

    def as_message_content(self) -> str:
        if self.ok:
            return self.content
        return f"ERROR: {self.error}"


def _coerce_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, ToolResult):
        return value.as_message_content()
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return str(value)


class ToolRegistry:
    """Holds tools and runs them. Optionally gated by an approval callback."""

    def __init__(self, approval: Optional[Callable[[Tool, dict], bool]] = None):
        self._tools: dict[str, Tool] = {}
        # approval(tool, args) -> True to proceed. Default: allow.
        self._approval = approval

    # -- registration ------------------------------------------------------

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Handler,
        destructive: bool = False,
    ) -> Tool:
        if not name:
            raise ValueError("tool name is required")
        tool = Tool(name=name, description=description, parameters=parameters,
                    handler=handler, destructive=destructive)
        self._tools[name] = tool
        logger.debug("[tools] registered %s", name)
        return tool

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_function(self, fn: Callable) -> Tool:
        """Register a function decorated with :func:`tool`."""
        spec = getattr(fn, "_tool_spec", None)
        if not spec:
            raise ValueError(f"{fn!r} is not a @tool function")
        return self.register(handler=fn, **spec)

    # -- introspection -----------------------------------------------------

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def definitions(self, only: Optional[set[str]] = None) -> list[dict]:
        """Provider-neutral tool defs for the agent loop. Pass ``only`` (a set of
        tool names) to expose just a scoped subset — fewer, more relevant tools sharpen
        the model's tool selection and shrink the prompt. Unknown names in ``only`` are
        ignored; the registration order is preserved."""
        tools = self._tools.values()
        if only is not None:
            tools = [t for t in tools if t.name in only]
        return [t.definition() for t in tools]

    # -- execution ---------------------------------------------------------

    def execute(self, name: str, args: Optional[dict] = None) -> ToolResult:
        args = args or {}
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, content="", error=f"Unknown tool: {name}")
        if tool.destructive and self._approval and not self._approval(tool, args):
            return ToolResult(ok=False, content="", error="User declined the action.")
        try:
            result = tool.handler(args)
            if isinstance(result, ToolResult):
                return result
            return ToolResult(ok=True, content=_coerce_content(result), data=result)
        except Exception as exc:  # noqa: BLE001 - surfaced back to the model
            logger.warning("[tools] %s raised: %s", name, exc)
            return ToolResult(ok=False, content="", error=str(exc))


def tool(name: str, description: str, parameters: dict, destructive: bool = False):
    """Decorator that tags a function with a tool spec for later registration."""

    def decorator(fn: Callable) -> Callable:
        fn._tool_spec = {  # type: ignore[attr-defined]
            "name": name,
            "description": description,
            "parameters": parameters,
            "destructive": destructive,
        }
        return fn

    return decorator
