"""MCPManager — connects configured MCP servers and registers their tools.

Config (``friday/config.yaml``)::

    mcp:
      servers:
        - name: filesystem
          command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home/me"]
        - name: git
          command: ["uvx", "mcp-server-git"]
          enabled: true

Each server's tools land in the registry as ``mcp_<server>_<tool>`` with the
server's own JSON-Schema, so the agent calls them like any native tool.
"""
from __future__ import annotations

import re
from typing import Optional

from friday.core.logger import logger
from friday.core.tools import ToolRegistry, ToolResult
from friday.mcp.client import StdioMCPClient


def _safe(part: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", part.lower())


class MCPManager:
    def __init__(self, server_configs: Optional[list[dict]] = None):
        self._configs = server_configs or []
        self.clients: dict[str, StdioMCPClient] = {}

    @classmethod
    def from_config(cls, config: dict) -> "MCPManager":
        mcp = (config or {}).get("mcp") or {}
        servers = [s for s in (mcp.get("servers") or []) if s.get("enabled", True)]
        return cls(servers)

    def register_into(self, registry: ToolRegistry) -> int:
        """Connect every configured server and register its tools. Returns the
        number of MCP tools registered. Always registers ``mcp_list_servers``."""
        count = 0
        for cfg in self._configs:
            name = cfg.get("name") or "unnamed"
            command = cfg.get("command")
            if not command:
                logger.warning("[mcp] server %r has no command — skipping", name)
                continue
            client = StdioMCPClient(name, command, env=cfg.get("env"), cwd=cfg.get("cwd"))
            if not client.connect():
                continue
            self.clients[name] = client
            for tool in client.list_tools():
                count += self._register_tool(registry, name, client, tool)
        self._register_list_servers(registry)
        logger.info("[mcp] registered %d tool(s) from %d server(s)", count, len(self.clients))
        return count

    def _register_tool(self, registry: ToolRegistry, server: str,
                       client: StdioMCPClient, tool: dict) -> int:
        tool_name = tool.get("name", "")
        if not tool_name:
            return 0
        reg_name = f"mcp_{_safe(server)}_{_safe(tool_name)}"
        schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
        description = f"[{server}] " + (tool.get("description") or f"MCP tool {tool_name}")

        def handler(args: dict, _client=client, _tool=tool_name) -> ToolResult:
            try:
                return ToolResult(ok=True, content=_client.call_tool(_tool, args))
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, content="", error=f"MCP error: {exc}")

        registry.register(reg_name, description, schema, handler)
        return 1

    def _register_list_servers(self, registry: ToolRegistry) -> None:
        def handler(_args: dict) -> ToolResult:
            if not self.clients:
                return ToolResult(ok=True, content="No MCP servers connected.")
            lines = ["Connected MCP servers:"]
            for name, client in self.clients.items():
                tools = ", ".join(t.get("name", "?") for t in client.list_tools()) or "(none)"
                lines.append(f"- {name}: {tools}")
            return ToolResult(ok=True, content="\n".join(lines))

        registry.register("mcp_list_servers", "List connected MCP servers and their tools.",
                          {"type": "object", "properties": {}}, handler)

    def close(self) -> None:
        for client in self.clients.values():
            client.close()
