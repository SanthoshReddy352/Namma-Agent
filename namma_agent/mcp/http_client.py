"""Streamable-HTTP MCP client (Phase 5) — remote servers such as GitHub's hosted
MCP (``https://api.githubcopilot.com/mcp/``).

Same interface as :class:`~namma_agent.mcp.client.StdioMCPClient` (connect /
list_tools / call_tool / call_tool_raw / close) so the manager treats both alike.

Protocol (MCP 2025-03-26 "Streamable HTTP"): every JSON-RPC message is a POST to
the endpoint with ``Accept: application/json, text/event-stream``. The reply is
either one JSON body or an SSE stream whose ``data:`` lines carry JSON-RPC
messages; we read until the response with our id arrives. The server may hand
out an ``Mcp-Session-Id`` on initialize, which every later request must echo.
Stdlib only (urllib) — no new dependency.
"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Optional

from namma_agent.core.logger import logger

_PROTOCOL_VERSION = "2025-03-26"
_MAX_BODY = 8 * 1024 * 1024


class HttpMCPClient:
    def __init__(self, name: str, url: str, headers: Optional[dict] = None):
        self.name = name
        self.url = url
        self._headers = {k: str(v) for k, v in (headers or {}).items() if str(v)}
        self._session: Optional[str] = None
        self._tools: list[dict] = []
        self._id = 0
        self._lock = threading.Lock()
        self.last_error = ""

    # -- lifecycle ---------------------------------------------------------

    def connect(self, timeout: int = 30) -> bool:
        try:
            self._request("initialize", {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "Namma Agent", "version": "2.0"},
            }, timeout=timeout)
            self._notify("notifications/initialized", {}, timeout=timeout)
            result = self._request("tools/list", {}, timeout=timeout)
            self._tools = (result or {}).get("tools", [])
            logger.info("[mcp] %s: connected over HTTP, %d tool(s)", self.name, len(self._tools))
            return True
        except Exception as exc:  # noqa: BLE001
            self.last_error = _explain(exc)
            logger.warning("[mcp] %s: HTTP connect failed: %s", self.name, self.last_error)
            return False

    def close(self) -> None:
        if not self._session:
            return
        try:  # polite session teardown; servers that don't support it 405
            req = urllib.request.Request(self.url, method="DELETE",
                                         headers={**self._headers, "Mcp-Session-Id": self._session})
            urllib.request.urlopen(req, timeout=5).close()  # noqa: S310
        except Exception:  # noqa: BLE001
            pass
        self._session = None

    # -- API ---------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        return self._tools

    def call_tool_raw(self, tool_name: str, arguments: dict, timeout: int = 60) -> dict:
        return self._request("tools/call", {"name": tool_name, "arguments": arguments or {}},
                             timeout=timeout) or {}

    def call_tool(self, tool_name: str, arguments: dict, timeout: int = 60) -> str:
        result = self.call_tool_raw(tool_name, arguments, timeout)
        if not result:
            return "(no result)"
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content
                     if isinstance(c, dict) and c.get("type") == "text"]
            body = "\n".join(t for t in texts if t)
            if result.get("isError"):
                return f"ERROR: {body or result}"
            return body or json.dumps(result, default=str)
        return json.dumps(result, default=str)

    # -- transport ---------------------------------------------------------

    def _post(self, message: dict, timeout: int):
        headers = {"Content-Type": "application/json",
                   "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": _PROTOCOL_VERSION,
                   "User-Agent": "Namma-Agent-MCP/2.0", **self._headers}
        if self._session:
            headers["Mcp-Session-Id"] = self._session
        req = urllib.request.Request(self.url, data=json.dumps(message).encode("utf-8"),
                                     headers=headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=timeout)  # noqa: S310
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session = sid
        return resp

    def _notify(self, method: str, params: dict, timeout: int = 30) -> None:
        with self._lock:
            resp = self._post({"jsonrpc": "2.0", "method": method, "params": params}, timeout)
            resp.close()

    def _request(self, method: str, params: dict, timeout: int = 30) -> Optional[dict]:
        with self._lock:
            self._id += 1
            req_id = self._id
            resp = self._post({"jsonrpc": "2.0", "id": req_id, "method": method,
                               "params": params}, timeout)
            try:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                if "text/event-stream" in ctype:
                    obj = _read_sse(resp, req_id)
                else:
                    raw = resp.read(_MAX_BODY + 1)
                    if len(raw) > _MAX_BODY:
                        raise RuntimeError("response too large")
                    obj = _pick(json.loads(raw.decode("utf-8") or "null"), req_id)
            finally:
                resp.close()
        if obj is None:
            raise RuntimeError(f"{self.name}: no response to {method}")
        if "error" in obj:
            err = obj["error"]
            raise RuntimeError(f"{self.name}: {err.get('message') if isinstance(err, dict) else err}")
        return obj.get("result")


def _pick(payload, req_id: int) -> Optional[dict]:
    """The JSON-RPC response with ``req_id`` from a single object or a batch."""
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if isinstance(item, dict) and item.get("id") == req_id:
            return item
    return None


def _read_sse(resp, req_id: int) -> Optional[dict]:
    """Read SSE events until one carries the response for ``req_id``."""
    data_lines: list[str] = []
    read = 0
    for raw in resp:
        read += len(raw)
        if read > _MAX_BODY:
            raise RuntimeError("event stream too large")
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
            continue
        if line == "" and data_lines:            # end of one event
            try:
                found = _pick(json.loads("\n".join(data_lines)), req_id)
            except json.JSONDecodeError:
                found = None
            data_lines = []
            if found is not None:
                return found
    if data_lines:
        try:
            return _pick(json.loads("\n".join(data_lines)), req_id)
        except json.JSONDecodeError:
            return None
    return None


def _explain(exc: Exception) -> str:
    """A connect failure a user can act on (bad token vs bad URL vs offline)."""
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code in (401, 403):
            return f"HTTP {exc.code}: the server rejected the credentials — check the token"
        if exc.code == 404:
            return "HTTP 404: no MCP endpoint at that URL — check the URL"
        if exc.code == 405:
            return "HTTP 405: that URL doesn't accept MCP requests (wrong path?)"
        return f"HTTP {exc.code} from the server"
    if isinstance(exc, urllib.error.URLError):
        return f"couldn't reach the server ({exc.reason}) — check the URL / your connection"
    return str(exc)[:200]
