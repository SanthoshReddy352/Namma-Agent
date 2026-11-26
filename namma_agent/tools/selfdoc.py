"""Self-knowledge tool — the assistant answers questions about its own setup.

The reference is generated from the LIVE install (core/self_knowledge.py): real
paths, configured models and MCP servers, enabled toolsets — followed by the
narrative sections of ``self_knowledge.md``. Secret values are never included.
"""
from __future__ import annotations

from namma_agent.core.tools import ToolRegistry, ToolResult


def register(registry: ToolRegistry) -> None:
    def _about_namma(args: dict) -> ToolResult:
        from namma_agent.core.self_knowledge import render

        try:
            text = render(registry=registry, topic=str(args.get("topic") or ""))
        except Exception as exc:  # noqa: BLE001 — surfaced to the model
            return ToolResult(ok=False, content="", error=f"self-knowledge unavailable: {exc}")
        return ToolResult(ok=True, content=text)

    registry.register(
        "about_namma",
        "Your own setup, generated live: version, install/source/config/data paths, "
        "configured models and providers, MCP servers (where they're configured), "
        "enabled toolsets, and how each subsystem works. Call this FIRST for any "
        "question about your own configuration — don't search the disk for it.",
        {
            "type": "object",
            "properties": {
                "topic": {"type": "string",
                          "description": "optional keyword to fetch matching sections "
                                         "(e.g. 'mcp', 'paths', 'models', 'memory')"},
            },
        }, _about_namma)
