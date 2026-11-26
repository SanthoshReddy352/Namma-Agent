"""MCPManager — connects configured MCP servers and registers their tools.

Config (``mcp.servers`` in user_config.yaml; see :mod:`namma_agent.mcp.config`)::

    mcp:
      servers:
        - name: filesystem
          command: ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/home/me"]
        - name: github
          transport: http
          url: https://api.githubcopilot.com/mcp/
          headers: {Authorization: "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"}

Each server's tools land in the registry as ``mcp_<server>_<tool>`` with the
server's own JSON-Schema, so the agent calls them like any native tool.

Phase 5: servers connect in the BACKGROUND (:meth:`start_async`) so a slow
``npx`` download or Docker cold start never blocks startup, and each server has
a live status — ``connecting`` / ``connected`` / ``failed`` (with the reason) /
``disabled`` — that Settings shows and the setup agent reads.
"""
from __future__ import annotations

import os
import re
import threading
import time
from typing import Callable, Optional

from namma_agent.core.logger import logger
from namma_agent.core.tools import ToolRegistry, ToolResult
from namma_agent.mcp.client import StdioMCPClient
from namma_agent.mcp.config import normalize_server, resolved
from namma_agent.mcp.widgets import augment_widget_result, widget_resource_uri


def _safe(part: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", part.lower())


#: OpenAI requires tool names to match ``^[a-zA-Z0-9_-]{1,64}$``.
_MAX_TOOL_NAME = 64


def _tool_reg_name(server: str, tool_name: str) -> str:
    """``mcp_<server>_<tool>``, sanitized and capped at 64 chars.

    An over-long name is shortened in its TOOL part (the ``mcp_<server>_``
    prefix is kept — :meth:`MCPManager.disconnect_server` matches on it) and
    suffixed with a short hash of the full name, so two long names that share a
    prefix never collide."""
    prefix = f"mcp_{_safe(server)}_"
    full = prefix + _safe(tool_name)
    if len(full) <= _MAX_TOOL_NAME:
        return full
    import hashlib
    digest = hashlib.sha1(full.encode("utf-8")).hexdigest()[:8]
    room = _MAX_TOOL_NAME - len(prefix) - len(digest) - 1
    if room < 1:  # absurdly long server name: keep what fits
        return (full[:_MAX_TOOL_NAME - len(digest) - 1] + "_" + digest)
    return f"{prefix}{_safe(tool_name)[:room]}_{digest}"


def make_client(cfg: dict):
    """Build the right client for a (normalised) server config, with ``${VAR}``
    references resolved from the environment. Returns ``(client, error)``."""
    cfg = resolved(normalize_server(cfg))
    name = cfg.get("name") or "unnamed"
    if cfg.get("transport") == "http":
        from namma_agent.mcp.http_client import HttpMCPClient
        if not cfg.get("url"):
            return None, "no url"
        return HttpMCPClient(name, cfg["url"], headers=cfg.get("headers")), ""
    command = cfg.get("command")
    if not command:
        return None, "no command"
    # A server's own env ADDS to ours — a config that only sets a token must not
    # lose PATH (npx / uvx / docker couldn't even start).
    env = {**os.environ, **cfg["env"]} if cfg.get("env") else None
    return StdioMCPClient(name, command, env=env, cwd=cfg.get("cwd")), ""


class MCPManager:
    def __init__(self, server_configs: Optional[list[dict]] = None):
        self._configs = server_configs or []
        self.clients: dict = {}
        self.status: dict[str, dict] = {}
        self._lock = threading.RLock()
        self.on_change: Optional[Callable[[str, dict], None]] = None

    @classmethod
    def from_config(cls, config: dict) -> "MCPManager":
        mcp = (config or {}).get("mcp") or {}
        servers = [s for s in (mcp.get("servers") or [])
                   if isinstance(s, dict) and s.get("enabled", True)]
        return cls(servers)

    # -- status ------------------------------------------------------------

    def _set_status(self, name: str, **fields) -> None:
        with self._lock:
            cur = dict(self.status.get(name) or {})
            cur.update(fields, updated_at=time.time())
            self.status[name] = cur
        cb = self.on_change
        if cb is not None:
            try:
                cb(name, dict(cur))
            except Exception:  # noqa: BLE001 — a UI push must never break connects
                logger.debug("[mcp] status callback failed", exc_info=True)

    def status_of(self, name: str) -> dict:
        with self._lock:
            return dict(self.status.get(name) or {"state": "unknown"})

    # -- connect -----------------------------------------------------------

    def register_into(self, registry: ToolRegistry) -> int:
        """Connect every configured server NOW (blocking) and register its tools.
        Returns the number of MCP tools registered. Always registers
        ``mcp_list_servers``. Startup uses :meth:`start_async` instead."""
        count = 0
        for cfg in self._configs:
            count += self.connect_server(cfg, registry)
        self._register_list_servers(registry)
        logger.info("[mcp] registered %d tool(s) from %d server(s)", count, len(self.clients))
        return count

    def start_async(self, registry: ToolRegistry) -> list[threading.Thread]:
        """Connect every configured server in its own background thread; status
        moves connecting → connected | failed as each finishes."""
        self._register_list_servers(registry)
        threads = []
        for cfg in self._configs:
            name = cfg.get("name") or "unnamed"
            self._set_status(name, state="connecting", error="", tools=0,
                             transport=normalize_server(cfg)["transport"])
            t = threading.Thread(target=self.connect_server, args=(cfg, registry),
                                 name=f"mcp-{name}", daemon=True)
            t.start()
            threads.append(t)
        return threads

    def connect_server(self, cfg: dict, registry: ToolRegistry) -> int:
        """Connect ONE server config and register its tools, leaving every other
        running server untouched — the targeted path behind per-server enable and
        backend switches. Returns the number of tools registered (0 on failure)."""
        name = cfg.get("name") or "unnamed"
        started = time.time()
        transport = normalize_server(cfg)["transport"]
        self._set_status(name, state="connecting", error="", tools=0, transport=transport)
        client, err = make_client(cfg)
        if client is None:
            logger.warning("[mcp] server %r: %s — skipping", name, err)
            self._set_status(name, state="failed", error=err)
            return 0
        # Some servers cold-start slowly (a Dockerised server running migrations,
        # an npx first download). Generous default; a fast server returns at once.
        connect_timeout = int(cfg.get("connect_timeout") or 60)
        if not client.connect(timeout=connect_timeout):
            self._set_status(name, state="failed",
                             error=getattr(client, "last_error", "") or "connect failed",
                             ms=int((time.time() - started) * 1000))
            return 0
        with self._lock:
            old = self.clients.pop(name, None)
            self.clients[name] = client
        if old is not None and old is not client:
            old.close()
        call_timeout = int(cfg.get("call_timeout") or 120)
        count = 0
        for tool in client.list_tools():
            count += self._register_tool(registry, name, client, tool, call_timeout)
        self._set_status(name, state="connected", error="", tools=count,
                         ms=int((time.time() - started) * 1000))
        return count

    def disconnect_server(self, name: str, registry: ToolRegistry,
                          state: str = "disabled") -> None:
        """Close ONE server's client and drop its tools from the registry, leaving
        the other servers running (counterpart of :meth:`connect_server`)."""
        with self._lock:
            client = self.clients.pop(name, None)
        if client is not None:
            client.close()
        prefix = f"mcp_{_safe(name)}_"
        for reg_name in [n for n in registry.names() if n.startswith(prefix)]:
            registry.unregister(reg_name)
        if state == "removed":
            with self._lock:
                self.status.pop(name, None)
        else:
            self._set_status(name, state=state, error="", tools=0)

    def _register_tool(self, registry: ToolRegistry, server: str,
                       client, tool: dict, call_timeout: int = 120) -> int:
        tool_name = tool.get("name", "")
        if not tool_name:
            return 0
        reg_name = _tool_reg_name(server, tool_name)
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

        # Explicit category: background connects run outside the service's
        # `registry.categorize("mcp")` block (and that default isn't thread-safe).
        registry.register(reg_name, description, schema, handler, category="mcp")
        return 1

    def _register_list_servers(self, registry: ToolRegistry) -> None:
        def handler(_args: dict) -> ToolResult:
            with self._lock:
                status = {k: dict(v) for k, v in self.status.items()}
                clients = dict(self.clients)
            if not status and not clients:
                return ToolResult(ok=True, content="No MCP servers configured.")
            lines = ["MCP servers:"]
            for name in sorted(set(status) | set(clients)):
                st = status.get(name) or {"state": "connected"}
                line = f"- {name}: {st.get('state')}"
                if st.get("error"):
                    line += f" ({st['error']})"
                client = clients.get(name)
                if client is not None:
                    tools = ", ".join(t.get("name", "?") for t in client.list_tools()) or "(none)"
                    line += f" — tools: {tools}"
                lines.append(line)
            return ToolResult(ok=True, content="\n".join(lines))

        registry.register("mcp_list_servers",
                          "List configured MCP servers, their connection status and tools.",
                          {"type": "object", "properties": {}}, handler, category="mcp")

    def close(self) -> None:
        with self._lock:
            clients = list(self.clients.values())
        for client in clients:
            client.close()
