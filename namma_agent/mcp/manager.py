"""MCPManager — connects configured MCP servers and registers their tools.

Config (``namma_agent/config.yaml``)::

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

from namma_agent.core.logger import logger
from namma_agent.core.tools import ToolRegistry, ToolResult
from namma_agent.mcp.client import StdioMCPClient
from namma_agent.mcp.widgets import augment_widget_result, widget_resource_uri


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
            count += self.connect_server(cfg, registry)
        self._register_list_servers(registry)
        logger.info("[mcp] registered %d tool(s) from %d server(s)", count, len(self.clients))
        return count

    def connect_server(self, cfg: dict, registry: ToolRegistry) -> int:
        """Connect ONE server config and register its tools, leaving every other
        running server untouched — the targeted path behind per-server enable and
        backend switches (a github toggle must not restart the cognee container).
        Returns the number of tools registered (0 when the connect failed)."""
        name = cfg.get("name") or "unnamed"
        command = cfg.get("command")
        if not command:
            logger.warning("[mcp] server %r has no command — skipping", name)
            return 0
        client = StdioMCPClient(name, command, env=cfg.get("env"), cwd=cfg.get("cwd"))
        # Some servers cold-start slowly (e.g. a Dockerised server that runs DB
        # migrations before answering the handshake). Allow a per-server override;
        # default generously so a slow server isn't dropped, while a fast one still
        # returns the instant it answers.
        connect_timeout = int(cfg.get("connect_timeout") or 60)
        if not client.connect(timeout=connect_timeout):
            return 0
        self.clients[name] = client
        # Per-server tool-call timeout — heavy tools (e.g. graph build) can take
        # minutes; a fast server is unaffected since it returns immediately.
        call_timeout = int(cfg.get("call_timeout") or 120)
        count = 0
        for tool in client.list_tools():
            count += self._register_tool(registry, name, client, tool, call_timeout)
        return count

    def disconnect_server(self, name: str, registry: ToolRegistry) -> None:
        """Close ONE server's client and drop its tools from the registry, leaving
        the other servers running (counterpart of :meth:`connect_server`)."""
        client = self.clients.pop(name, None)
        if client is not None:
            client.close()
        prefix = f"mcp_{_safe(name)}_"
        for reg_name in [n for n in registry.names() if n.startswith(prefix)]:
            registry.unregister(reg_name)

    def _register_tool(self, registry: ToolRegistry, server: str,
                       client: StdioMCPClient, tool: dict, call_timeout: int = 120) -> int:
        tool_name = tool.get("name", "")
        if not tool_name:
            return 0
        reg_name = f"mcp_{_safe(server)}_{_safe(tool_name)}"
        schema = tool.get("inputSchema") or {"type": "object", "properties": {}}
        description = f"[{server}] " + (tool.get("description") or f"MCP tool {tool_name}")

        # Tools that render into an MCP-Apps UI widget return an ack ("Displayed!")
        # rather than an answer — and this host has no widget renderer, so nothing
        # reaches the user. Flag them so the result can be repaired into a real
        # artifact link (see namma_agent.mcp.widgets) instead of a false success.
        widget_uri = widget_resource_uri(tool)
        if widget_uri:
            logger.info("[mcp] %s.%s renders into widget %s — bridging",
                        server, tool_name, widget_uri)

        def handler(args: dict, _client=client, _tool=tool_name, _timeout=call_timeout,
                    _widget=widget_uri) -> ToolResult:
            try:
                content = _client.call_tool(_tool, args, timeout=_timeout)
            except Exception as exc:  # noqa: BLE001
                return ToolResult(ok=False, content="", error=f"MCP error: {exc}")
            if _widget:
                # `data["url"]` is load-bearing: it's what makes the agent place the
                # rendered diagram in the answer instead of trusting the model to
                # re-paste the markdown (which it reliably does not).
                content, data = augment_widget_result(
                    content, args, _widget,
                    lambda name, a: _client.call_tool(name, a, timeout=_timeout))
                return ToolResult(ok=True, content=content, data=data or None)
            return ToolResult(ok=True, content=content)

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
