"""Persistent stdio MCP client — JSON-RPC 2.0 over a long-lived subprocess.

The legacy v1 bridge spawned a fresh process per call, which loses the
``initialize`` handshake state. This keeps one process alive for the session and
does a proper handshake:

    initialize → (initialized notification) → tools/list → tools/call …

Messages are newline-delimited JSON. Requests are serialized behind a lock; the
reader skips server-initiated notifications (no ``id``) until it sees the
matching response id.
"""
from __future__ import annotations

import json
import subprocess
import threading
from typing import Any, Optional

from friday.core.logger import logger

_PROTOCOL_VERSION = "2024-11-05"


class StdioMCPClient:
    def __init__(self, name: str, command: list[str], env: Optional[dict] = None,
                 cwd: Optional[str] = None):
        self.name = name
        self.command = command
        self._env = env
        self._cwd = cwd
        self._proc: Optional[subprocess.Popen] = None
        self._tools: list[dict] = []
        self._id = 0
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def connect(self, timeout: int = 15) -> bool:
        try:
            self._proc = subprocess.Popen(
                self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=self._env, cwd=self._cwd,
            )
        except (FileNotFoundError, OSError) as exc:
            logger.warning("[mcp] %s: spawn failed: %s", self.name, exc)
            return False
        try:
            self._request("initialize", {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "FRIDAY", "version": "2.0"},
            }, timeout=timeout)
            self._notify("notifications/initialized", {})
            result = self._request("tools/list", {}, timeout=timeout)
            self._tools = (result or {}).get("tools", [])
            logger.info("[mcp] %s: connected, %d tool(s)", self.name, len(self._tools))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[mcp] %s: handshake failed: %s", self.name, exc)
            self.close()
            return False

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                self._proc.kill()
            except Exception:  # noqa: BLE001
                pass
        self._proc = None

    # -- API ---------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict, timeout: int = 60) -> str:
        result = self._request("tools/call", {"name": tool_name, "arguments": arguments or {}},
                               timeout=timeout)
        if not result:
            return "(no result)"
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            body = "\n".join(t for t in texts if t)
            if result.get("isError"):
                return f"ERROR: {body or result}"
            return body or json.dumps(result, default=str)
        return json.dumps(result, default=str)

    # -- transport ---------------------------------------------------------

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _send(self, message: dict) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("MCP server not connected")
        self._proc.stdin.write(json.dumps(message) + "\n")
        self._proc.stdin.flush()

    def _notify(self, method: str, params: dict) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict, timeout: int = 30) -> Optional[dict]:
        with self._lock:
            req_id = self._next_id()
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
            return self._read_response(req_id, timeout)

    def _read_response(self, req_id: int, timeout: int) -> Optional[dict]:
        if self._proc is None or self._proc.stdout is None:
            raise RuntimeError("MCP server not connected")
        # Bound the wait with a watchdog that kills the (blocking) readline.
        timer = threading.Timer(timeout, self._proc.kill)
        timer.start()
        try:
            while True:
                line = self._proc.stdout.readline()
                if line == "":  # EOF / process died
                    raise RuntimeError(f"{self.name}: server closed the connection")
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue  # server log noise on stdout — skip
                if obj.get("id") != req_id:
                    continue  # a notification or an out-of-band id
                if "error" in obj:
                    raise RuntimeError(f"{self.name}: {obj['error']}")
                return obj.get("result")
        finally:
            timer.cancel()
