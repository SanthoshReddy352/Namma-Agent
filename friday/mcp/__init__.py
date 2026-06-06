"""MCP (Model Context Protocol) client for FRIDAY v2.

Connects to configured stdio MCP servers and exposes their tools through the same
:class:`~friday.core.tools.ToolRegistry` the native tools use — so a third-party
MCP server's tools are indistinguishable from built-ins to the agent.

Self-contained: a stdlib JSON-RPC-over-stdio client (no `mcp` SDK dependency).
"""
from friday.mcp.client import StdioMCPClient
from friday.mcp.manager import MCPManager

__all__ = ["StdioMCPClient", "MCPManager"]
