"""Wave 5c — stdio MCP client + manager, exercised against a real fake server.

A tiny in-repo Python script speaks JSON-RPC-over-stdio so the handshake
(initialize → initialized → tools/list → tools/call) is tested end-to-end with
no external `mcp` dependency.
"""
from __future__ import annotations

import sys
import textwrap

import pytest

from friday.core.tools import ToolRegistry
from friday.mcp.client import StdioMCPClient
from friday.mcp.manager import MCPManager

_FAKE_SERVER = textwrap.dedent('''
    import sys, json
    def send(o):
        sys.stdout.write(json.dumps(o) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        mid, method = msg.get("id"), msg.get("method")
        if method == "initialize":
            # emit a stray notification first to test that the reader skips it
            send({"jsonrpc": "2.0", "method": "notifications/ready"})
            send({"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2024-11-05",
                  "capabilities": {}, "serverInfo": {"name": "fake", "version": "1"}}})
        elif method == "notifications/initialized":
            pass
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid, "result": {"tools": [
                {"name": "echo", "description": "echo text",
                 "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}},
                                 "required": ["text"]}}]}})
        elif method == "tools/call":
            args = msg["params"]["arguments"]
            send({"jsonrpc": "2.0", "id": mid,
                  "result": {"content": [{"type": "text", "text": "echo: " + args.get("text", "")}]}})
        else:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "unknown"}})
''')


@pytest.fixture
def server_cmd(tmp_path):
    script = tmp_path / "fake_mcp.py"
    script.write_text(_FAKE_SERVER)
    return [sys.executable, str(script)]


def test_client_connects_and_lists_tools(server_cmd):
    client = StdioMCPClient("fake", server_cmd)
    try:
        assert client.connect() is True
        tools = client.list_tools()
        assert len(tools) == 1 and tools[0]["name"] == "echo"
    finally:
        client.close()


def test_client_calls_tool(server_cmd):
    client = StdioMCPClient("fake", server_cmd)
    try:
        assert client.connect()
        assert client.call_tool("echo", {"text": "hi"}) == "echo: hi"
    finally:
        client.close()


def test_connect_failure_bad_command():
    client = StdioMCPClient("nope", ["this-binary-does-not-exist-xyz"])
    assert client.connect() is False


def test_manager_registers_tools_into_registry(server_cmd):
    mgr = MCPManager([{"name": "fake", "command": server_cmd}])
    reg = ToolRegistry()
    try:
        n = mgr.register_into(reg)
        assert n == 1
        assert "mcp_fake_echo" in reg
        assert "mcp_list_servers" in reg
        r = reg.execute("mcp_fake_echo", {"text": "yo"})
        assert r.ok and r.content == "echo: yo"
        servers = reg.execute("mcp_list_servers", {})
        assert "fake" in servers.content and "echo" in servers.content
    finally:
        mgr.close()


def test_manager_list_servers_when_none():
    mgr = MCPManager([])
    reg = ToolRegistry()
    mgr.register_into(reg)
    assert "mcp_list_servers" in reg
    assert "No MCP servers" in reg.execute("mcp_list_servers", {}).content


def test_manager_from_config_filters_disabled():
    cfg = {"mcp": {"servers": [
        {"name": "a", "command": ["x"]},
        {"name": "b", "command": ["y"], "enabled": False},
    ]}}
    mgr = MCPManager.from_config(cfg)
    assert len(mgr._configs) == 1 and mgr._configs[0]["name"] == "a"
