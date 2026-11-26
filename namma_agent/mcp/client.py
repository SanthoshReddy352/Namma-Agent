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
import os
import shutil
import subprocess
import sys
import threading
from typing import Optional

from namma_agent.core.logger import logger

_PROTOCOL_VERSION = "2024-11-05"


def _docker_container_name(command: list[str]) -> str:
    """If ``command`` is a ``docker run … --name X …`` invocation, return X — so the
    client can force-remove a stale/orphaned container of that name. ``docker run
    --rm`` containers do NOT die when the parent process is killed (only when the
    container's own stdio closes cleanly), so without this they leak and, for a
    file-locked store like Kuzu, hold the lock → the next launch can't start until a
    full app restart. Naming + ``docker rm -f`` makes reconnect/switch reliable."""
    if not command:
        return ""
    head = os.path.basename(str(command[0])).lower()
    if "docker" not in head:
        return ""
    for i, tok in enumerate(command):
        if tok == "--name" and i + 1 < len(command):
            return str(command[i + 1])
    return ""


def _docker_rm(name: str) -> None:
    """Best-effort ``docker rm -f <name>`` (force-stop + remove). Silent on any error
    (Docker down, no such container, …) — it only ever clears leftovers."""
    if not name:
        return
    try:
        subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20)
    except Exception:  # noqa: BLE001
        pass


def _resolve_cmd(cmd: str) -> str:
    """Resolve a command name to a full path, especially on Windows where
    ``subprocess.Popen`` with ``shell=False`` can't resolve ``.cmd`` files
    (e.g. ``npx`` → ``npx.cmd``) without the full path."""
    # Already a full path or has an extension — return as-is
    if os.path.isabs(cmd) or os.path.splitext(cmd)[1]:
        return cmd
    resolved = shutil.which(cmd)
    if resolved:
        return resolved
    # On Windows, try with common extensions
    if sys.platform == "win32":
        for ext in [".cmd", ".bat", ".exe", ".ps1"]:
            resolved = shutil.which(cmd + ext)
            if resolved:
                return resolved
    return cmd


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
        self._docker_name = _docker_container_name(command)
        self.last_error = ""   # why the last connect failed (shown in Settings)

    # -- lifecycle ---------------------------------------------------------

    def connect(self, timeout: int = 15) -> bool:
        # Resolve the executable on Windows (npx → npx.cmd full path)
        resolved = self.command[:]
        if resolved:
            resolved[0] = _resolve_cmd(resolved[0])

        # Clear any orphaned container of the same name first, so a `--name` launch
        # can't fail with "container name already in use" (e.g. after a hard kill).
        _docker_rm(self._docker_name)

        # Build env: inherit parent if none explicitly set
        env = self._env
        if env is None:
            env = os.environ.copy()

        try:
            self._proc = subprocess.Popen(
                resolved, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=env, cwd=self._cwd,
            )
        except (FileNotFoundError, OSError) as exc:
            logger.warning("[mcp] %s: spawn failed (%s): %s", self.name, resolved[0], exc)
            self.last_error = (f"'{self.command[0]}' was not found — install it or fix the "
                               "command" if isinstance(exc, FileNotFoundError)
                               else f"couldn't start '{self.command[0]}': {exc}")
            return False
        try:
            self._request("initialize", {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "Namma Agent", "version": "2.0"},
            }, timeout=timeout)
            self._notify("notifications/initialized", {})
            result = self._request("tools/list", {}, timeout=timeout)
            self._tools = (result or {}).get("tools", [])
            logger.info("[mcp] %s: connected, %d tool(s)", self.name, len(self._tools))
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[mcp] %s: handshake failed: %s", self.name, exc)
            self.last_error = (f"started, but the MCP handshake failed: {str(exc)[:160]} "
                               "(wrong package, a missing key, or still downloading — "
                               "try a longer connect_timeout)")
            self.close()
            return False

    def close(self) -> None:
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
        # A Dockerised server's container can outlive the client process — force-remove
        # it so reconnecting/switching backends doesn't leave a lock-holding orphan.
        _docker_rm(self._docker_name)

    # -- API ---------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        return self._tools

    def call_tool_raw(self, tool_name: str, arguments: dict, timeout: int = 60) -> dict:
        """Like :meth:`call_tool` but returns the FULL result dict — needed when a
        tool puts its payload in ``structuredContent`` (e.g. cognee's
        ``visualize_graph_ui`` returns the graph HTML there, not in ``content``)."""
        return self._request("tools/call", {"name": tool_name, "arguments": arguments or {}},
                             timeout=timeout) or {}

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
