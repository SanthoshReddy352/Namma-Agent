"""Phase 5 — MCP setup: config validation/import, presets, install-from-URL,
background connects with per-server status, the Streamable-HTTP client, and
the service's add/remove/save paths."""
from __future__ import annotations

import io
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.mcp import catalog as mcp_catalog
from namma_agent.mcp.config import (
    expand_vars,
    import_servers,
    merge_servers,
    resolved,
    validate_servers,
)
from namma_agent.mcp.http_client import HttpMCPClient
from namma_agent.mcp.manager import MCPManager
from namma_agent.tests.test_mcp import _FAKE_SERVER


def _fields(issues):
    return {(i["server"], i["field"]) for i in issues}


# ── validation ───────────────────────────────────────────────────────────────

def test_validate_reports_errors_per_field():
    r = validate_servers([
        {"command": ["x"]},                                   # no name
        {"name": "a", "command": []},                         # empty command
        {"name": "a", "command": ["y"]},                      # duplicate
        {"name": "web", "transport": "http", "url": "ftp://x"},
        {"name": "t", "command": ["z"], "connect_timeout": 0, "env": {"K": ["list"]}},
    ])
    assert not r["ok"]
    got = _fields(r["errors"])
    assert {("#1", "name"), ("a", "command"), ("a", "name"), ("web", "url"),
            ("t", "connect_timeout"), ("t", "env")} <= got


def test_validate_warnings_do_not_block(monkeypatch):
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    r = validate_servers([{"name": "s", "command": "npx -y pkg", "args": ["--flag"],
                           "env": {"TOKEN": "ghp_" + "a" * 36, "OTHER": "${NOT_SET_ANYWHERE}"},
                           "colour": "blue"}])
    assert r["ok"]
    assert r["servers"][0]["command"] == ["npx", "-y", "pkg", "--flag"]
    warned = {i["field"] for i in r["warnings"]}
    assert {"command", "env.TOKEN", "${NOT_SET_ANYWHERE}", "colour"} <= warned


def test_resolved_expands_vars_only_at_connect(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cret")
    server = {"name": "g", "transport": "http", "url": "https://h/mcp",
              "headers": {"Authorization": "Bearer ${MY_TOKEN}"}}
    assert resolved(server)["headers"]["Authorization"] == "Bearer s3cret"
    assert server["headers"]["Authorization"] == "Bearer ${MY_TOKEN}"   # untouched
    assert expand_vars("${NOPE_NOT_SET}x") == "x"


# ── import formats ───────────────────────────────────────────────────────────

def test_import_claude_desktop_and_vscode():
    claude = {"mcpServers": {
        "fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "/d"],
               "env": {"A": "1"}},
        "off": {"command": "uvx", "args": ["x"], "disabled": True}}}
    r = import_servers(claude)
    assert r["format"] == "claude-desktop" and r["ok"]
    fs, off = r["servers"]
    assert fs["command"] == ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/d"]
    assert off["enabled"] is False
    vs = import_servers({"servers": {"gh": {"type": "http", "url": "https://api.example/mcp"}}})
    assert vs["format"] == "vscode" and vs["servers"][0]["transport"] == "http"


def test_import_registry_server_json():
    obj = {"name": "io.github.acme/weather",
           "packages": [{"registry_type": "npm", "identifier": "@acme/weather-mcp",
                         "version": "1.2.0",
                         "environment_variables": [{"name": "WEATHER_KEY"}]}],
           "remotes": [{"type": "streamable-http", "url": "https://weather.acme/mcp"}]}
    r = import_servers(obj)
    assert r["format"] == "mcp-registry"
    local, remote = r["servers"]
    assert local["command"] == ["npx", "-y", "@acme/weather-mcp@1.2.0"]
    assert local["env"] == {"WEATHER_KEY": "${WEATHER_KEY}"}
    assert remote["transport"] == "http" and remote["name"] == "weather-remote"
    assert import_servers({"packages": [{"registry_type": "pypi", "identifier": "w"}]}
                          )["servers"][0]["command"] == ["uvx", "w"]


def test_import_unknown_format_is_an_error():
    r = import_servers({"hello": "world"})
    assert not r["ok"] and r["format"] == "unknown"


def test_merge_servers_keeps_existing_unless_replace():
    a = [{"name": "x", "command": ["1"]}]
    assert merge_servers(a, [{"name": "X", "command": ["2"]}])[0]["command"] == ["1"]
    assert merge_servers(a, [{"name": "X", "command": ["2"]}], replace=True)[0]["command"] == ["2"]
    assert len(merge_servers(a, [{"name": "y", "command": ["3"]}])) == 2


# ── presets ──────────────────────────────────────────────────────────────────

def test_github_hosted_preset_toolsets_and_read_only():
    r = mcp_catalog.build_from_preset("github", {"toolsets": ["repos", "issues", "bogus"],
                                                 "read_only": True})
    assert r["ok"], r["errors"]
    s = r["servers"][0]
    assert s["transport"] == "http" and s["url"].startswith("https://api.githubcopilot.com")
    assert s["headers"]["X-MCP-Toolsets"] == "repos,issues"
    assert s["headers"]["X-MCP-Readonly"] == "true"
    assert s["headers"]["Authorization"] == "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"
    rw = mcp_catalog.build_from_preset("github", {"read_only": False})["servers"][0]
    assert "X-MCP-Readonly" not in rw["headers"]


def test_github_docker_preset_uses_env_not_literals():
    s = mcp_catalog.build_from_preset("github-docker", {"toolsets": "repos"})["servers"][0]
    assert s["command"][:4] == ["docker", "run", "-i", "--rm"]
    assert s["env"]["GITHUB_TOOLSETS"] == "repos" and s["env"]["GITHUB_READ_ONLY"] == "1"
    assert s["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "${GITHUB_PERSONAL_ACCESS_TOKEN}"


def test_preset_required_params_and_unknown():
    assert not mcp_catalog.build_from_preset("filesystem", {})["ok"]
    fs = mcp_catalog.build_from_preset("filesystem", {"folders": "C:/a\nC:/b"}, name="docs")
    assert fs["servers"][0]["command"][-2:] == ["C:/a", "C:/b"]
    assert fs["servers"][0]["name"] == "docs"
    assert not mcp_catalog.build_from_preset("nope")["ok"]
    assert all(p["id"] and p["title"] for p in mcp_catalog.catalog())


# ── install from URL ─────────────────────────────────────────────────────────

def test_raw_url_conversion():
    assert mcp_catalog._raw_url("https://github.com/o/r/blob/main/mcp.json") == [
        "https://raw.githubusercontent.com/o/r/main/mcp.json"]
    assert mcp_catalog._raw_url("https://github.com/o/r")[0].endswith("/o/r/HEAD/server.json")


def test_fetch_config_https_only_and_parses(monkeypatch):
    assert not mcp_catalog.fetch_config("http://evil.example/x.json")["ok"]
    body = json.dumps({"mcpServers": {"t": {"command": "uvx", "args": ["mcp-server-time"]}}})

    class _Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mcp_catalog.urllib.request, "urlopen",
                        lambda req, timeout=10: _Resp(body.encode()))
    r = mcp_catalog.fetch_config("https://example.com/mcp.json")
    assert r["ok"] and r["servers"][0]["command"] == ["uvx", "mcp-server-time"]


# ── manager: background connect + status ─────────────────────────────────────

@pytest.fixture
def fake_cmd(tmp_path):
    script = tmp_path / "fake_mcp.py"
    script.write_text(_FAKE_SERVER)
    return [sys.executable, str(script)]


def _wait(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_start_async_status_transitions(fake_cmd):
    reg = ToolRegistry()
    mgr = MCPManager([{"name": "fake", "command": fake_cmd},
                      {"name": "broken", "command": ["definitely-not-a-binary-xyz"]}])
    events = []
    mgr.on_change = lambda name, st: events.append((name, st["state"]))
    mgr.start_async(reg)
    assert _wait(lambda: mgr.status_of("fake")["state"] == "connected"
                 and mgr.status_of("broken")["state"] == "failed")
    assert reg.get("mcp_fake_echo").category == "mcp"
    assert "not found" in mgr.status_of("broken")["error"]
    assert ("fake", "connecting") in events and ("fake", "connected") in events
    assert "broken: failed" in reg.get("mcp_list_servers").handler({}).content
    mgr.disconnect_server("fake", reg)
    assert mgr.status_of("fake")["state"] == "disabled" and reg.get("mcp_fake_echo") is None
    mgr.close()


def test_env_adds_to_inherited_environment(fake_cmd, monkeypatch):
    from namma_agent.mcp.manager import make_client
    monkeypatch.setenv("SECRET_FOR_SERVER", "v")
    client, _ = make_client({"name": "f", "command": fake_cmd, "env": {"X": "${SECRET_FOR_SERVER}"}})
    assert client._env["X"] == "v" and "PATH" in {k.upper() for k in client._env}


# ── Streamable HTTP client ───────────────────────────────────────────────────

class _MCPHandler(BaseHTTPRequestHandler):
    sse = False

    def log_message(self, *a):
        pass

    def do_POST(self):  # noqa: N802
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.headers.get("Authorization") != "Bearer good":
            self.send_response(401)
            self.end_headers()
            return
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:                                  # notification
            self.send_response(202)
            self.end_headers()
            return
        if method != "initialize" and self.headers.get("Mcp-Session-Id") != "sess-1":
            self.send_response(400)
            self.end_headers()
            return
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {}}
        elif method == "tools/list":
            result = {"tools": [{"name": "ping", "inputSchema": {"type": "object"}}]}
        else:
            result = {"content": [{"type": "text", "text": "pong " + json.dumps(msg["params"]["arguments"])}]}
        body = json.dumps({"jsonrpc": "2.0", "id": mid, "result": result})
        self.send_response(200)
        self.send_header("Mcp-Session-Id", "sess-1")
        if type(self).sse:
            payload = (f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'method': 'x'})}\n\n"
                       f"event: message\ndata: {body}\n\n").encode()
            self.send_header("Content-Type", "text/event-stream")
        else:
            payload = body.encode()
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.mark.parametrize("sse", [False, True])
def test_http_client_json_and_sse(sse):
    handler = type("H", (_MCPHandler,), {"sse": sse})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/mcp"
    try:
        good = HttpMCPClient("h", url, headers={"Authorization": "Bearer good"})
        assert good.connect(timeout=5)
        assert [t["name"] for t in good.list_tools()] == ["ping"]
        assert good.call_tool("ping", {"a": 1}) == 'pong {"a": 1}'
        bad = HttpMCPClient("h", url, headers={"Authorization": "Bearer nope"})
        assert not bad.connect(timeout=5)
        assert "credentials" in bad.last_error
    finally:
        srv.shutdown()


# ── service paths ────────────────────────────────────────────────────────────

class _Prov(Provider):
    name = "scripted"

    def __init__(self):
        super().__init__(model="scripted")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="ok")


def test_service_add_remove_and_refuse_invalid(fake_cmd):
    from namma_agent.service import NammaAgentService
    svc = NammaAgentService(config={"persona": "core", "conversation": {}}, provider=_Prov(),
                            registry=ToolRegistry(), db=Database(":memory:"))
    seen = []
    svc.broadcast.subscribe(lambda etype, payload: seen.append((etype, payload)))
    bad = svc.mcp_add_server({"name": "x"})
    assert not bad["ok"] and bad["errors"]
    ok = svc.mcp_add_server({"name": "fake", "command": fake_cmd})
    assert ok["ok"] and ok["server"] == "fake"
    assert _wait(lambda: svc.registry.get("mcp_fake_echo") is not None)
    assert any(e == "mcp_status" and p["state"] == "connected" for e, p in seen)
    detail = svc.mcp_detail()
    assert detail["servers"][0]["state"] == "connected"
    dup = svc.mcp_add_server({"name": "FAKE", "command": fake_cmd})
    assert not dup["ok"] and "exists" in dup["errors"][0]["message"]
    assert not svc.mcp_save_servers([{"name": "", "command": []}])["ok"]
    assert [s["name"] for s in svc.config["mcp"]["servers"]] == ["fake"]   # untouched
    gone = svc.mcp_remove_server("fake")
    assert gone["ok"] and svc.registry.get("mcp_fake_echo") is None
    assert svc.config["mcp"]["servers"] == []
    assert svc.mcp_catalog()["presets"]
