"""Tool registry for Namma Agent.

A tool is ``{name, description, parameters(JSON Schema), handler}``. The registry
emits provider-neutral tool definitions (the agent passes them straight to any
provider) and executes handlers, normalizing the result into a string the model
can read.

This replaces the legacy stack — no YAML catalog, no embedding router, no intent
recognizer. The model picks the tool from the schema; the registry just runs it.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Optional

from namma_agent.core.logger import logger

#: A handler takes the parsed argument dict and returns anything stringifiable.
Handler = Callable[[dict], Any]


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema (object)
    handler: Handler
    destructive: bool = False  # gated behind approval when True
    category: str = "general"  # toolset grouping (the Toolsets tab)
    enabled: bool = True  # set from the persisted disabled-set (Toolsets tab)

    def one_line(self, width: int = 200) -> str:
        desc = " ".join((self.description or "").split())
        return desc if len(desc) <= width else desc[: width - 1] + "…"

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

    def __init__(
        self,
        approval: Optional[Callable[[Tool, dict], bool]] = None,
        disabled: Optional[list[str]] = None,
    ):
        self._tools: dict[str, Tool] = {}
        # approval(tool, args) -> True to proceed. Default: allow.
        self._approval = approval
        # Tools the user turned off in the Toolsets tab — excluded from the
        # definitions the agent sees and refused by execute(), but still listed
        # in the UI so they can be re-enabled. Persisted by the caller
        # (config.local.yaml: tools.disabled).
        self._disabled: set[str] = {str(n).strip() for n in (disabled or []) if str(n).strip()}
        # Toolset assigned to tools registered while no explicit category is given;
        # load_tools() flips this per module so each tool inherits its module name.
        self._default_category = "general"

    # -- registration ------------------------------------------------------

    @contextmanager
    def categorize(self, category: str) -> Iterator["ToolRegistry"]:
        """Tag every tool registered inside the block with ``category`` (unless it
        passes its own). Lets service/load_tools group tools into toolsets without
        editing each ``register`` call."""
        previous = self._default_category
        self._default_category = category or previous
        try:
            yield self
        finally:
            self._default_category = previous

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Handler,
        destructive: bool = False,
        category: str = "",
    ) -> Tool:
        if not name:
            raise ValueError("tool name is required")
        tool = Tool(name=name, description=description, parameters=parameters,
                    handler=handler, destructive=destructive,
                    category=category or self._default_category,
                    enabled=name not in self._disabled)
        self._tools[name] = tool
        logger.debug("[tools] registered %s", name)
        return tool

    def add(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> bool:
        """Drop a tool from the registry. Used when MCP servers are reloaded so a
        removed server's tools don't linger. Returns True if a tool was removed."""
        return self._tools.pop(name, None) is not None

    def register_function(self, fn: Callable) -> Tool:
        """Register a function decorated with :func:`tool`."""
        spec = getattr(fn, "_tool_spec", None)
        if not spec:
            raise ValueError(f"{fn!r} is not a @tool function")
        return self.register(handler=fn, **spec)

    # -- introspection -----------------------------------------------------

    def names(self) -> list[str]:
        return sorted(self._tools)

    def all(self) -> list[Tool]:
        """Every registered tool (enabled or not), sorted by name — for the UI."""
        return sorted(self._tools.values(), key=lambda t: t.name)

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
        ignored; the registration order is preserved. Tools the user disabled in the
        Toolsets tab are always excluded — the model never sees them."""
        tools = [t for t in self._tools.values() if t.enabled]
        if only is not None:
            tools = [t for t in tools if t.name in only]
        return [t.definition() for t in tools]

    # -- enable / disable (the Toolsets tab) -------------------------------

    def set_enabled(self, name: str, enabled: bool) -> Optional[Tool]:
        """Turn a tool on/off in memory and return it. Persistence (the
        ``tools.disabled`` list in config) is the caller's job."""
        tool = self._tools.get(name)
        if not tool:
            return None
        if enabled:
            self._disabled.discard(name)
        else:
            self._disabled.add(name)
        tool.enabled = enabled
        return tool

    def set_category_enabled(self, category: str, enabled: bool) -> list[Tool]:
        """Toggle every tool in a toolset at once; returns the affected tools."""
        changed = []
        for tool in self._tools.values():
            if tool.category == category:
                self.set_enabled(tool.name, enabled)
                changed.append(tool)
        return changed

    def disabled_names(self) -> list[str]:
        """The current disabled-set, sorted — what the caller persists to config.
        Only names that still exist as tools are kept (drops stale entries)."""
        return sorted(n for n in self._disabled if n in self._tools)

    def detail(self) -> list[dict]:
        """Every tool with toolset/enabled/destructive info, for the Toolsets tab."""
        return [
            {
                "name": t.name,
                "description": t.one_line(220),
                "category": t.category or "general",
                "destructive": t.destructive,
                "enabled": t.enabled,
            }
            for t in self.all()
        ]

    # -- execution ---------------------------------------------------------

    def execute(self, name: str, args: Optional[dict] = None) -> ToolResult:
        args = args or {}
        if "_json_error" in args:
            return ToolResult(
                ok=False,
                content="",
                error=(
                    f"Failed to parse tool call arguments as valid JSON. "
                    f"Error: {args['_json_error']}. "
                    f"Raw arguments sent: {args.get('_raw_args') or ''}. "
                    f"Please make sure your arguments match the JSON schema, escape backslashes on Windows "
                    f"(use \\\\ instead of \\), and ensure all quotes and JSON syntax are valid."
                )
            )
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, content="", error=f"Unknown tool: {name}")
        if not tool.enabled:
            return ToolResult(ok=False, content="",
                              error=f"Tool '{name}' is disabled in the Toolsets settings.")
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
