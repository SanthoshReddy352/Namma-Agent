"""Persistent shell sessions — the agent's dedicated terminal.

One long-lived shell process per chat session (PowerShell on Windows, bash/sh on
POSIX), so working directory, environment variables, and shell state persist
across ``run_shell`` calls — the agent can ``cd`` anywhere on the system and keep
working there, activate a venv once, export a variable and use it later.

Design: instead of piping commands straight into the shell's stdin (fragile for
multiline scripts, and PowerShell echoes prompts), each shell runs a tiny REPL
*driver script*. The driver reads one line per command — ``<nonce> <script-path>``
— dot-sources the script (so state changes stick), then prints a sentinel line
carrying the nonce, the exit code, and the current directory. Python writes each
command to a temp script file, sends the line, and streams stdout (stderr merged)
until the matching sentinel appears. The shell's stdin stays free between frames,
so a foreground command that reads stdin (``sudo -S``) still can.

A command that times out or kills its shell (``exit``) marks the session dead;
the next command transparently respawns it in the last known directory.
"""
from __future__ import annotations

import codecs
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Optional

from namma_agent.core.logger import logger

IS_WINDOWS = platform.system() == "Windows"

# How much received-but-unstreamed text to hold back while waiting for more —
# enough to guarantee a sentinel is never partially streamed to the live view.
_HOLDBACK = 1024
# Cap on the output kept/returned per command (the tool truncates further).
_MAX_OUTPUT = 200_000
# Cap on text pushed to the live on_output stream per command (the UI view).
_MAX_STREAM = 64_000
# Shells idle longer than this are closed by the manager's lazy sweep.
_IDLE_SECONDS = 30 * 60

_SENT_OPEN = "<<<NAMMA:"


def _sentinel_re(nonce: str):
    import re
    return re.compile(re.escape(_SENT_OPEN) + re.escape(nonce) + r":(-?\d+):(.*?)>>>")


_POSIX_DRIVER = """\
while IFS= read -r __namma_line; do
  __namma_nonce=${__namma_line%% *}
  __namma_file=${__namma_line#* }
  . "$__namma_file"
  __namma_ec=$?
  printf '\\n<<<NAMMA:%s:%s:%s>>>\\n' "$__namma_nonce" "$__namma_ec" "$PWD"
  rm -f "$__namma_file" 2>/dev/null
done
"""

# PowerShell driver. Dot-sourcing runs in the driver's scope, so $vars, $env: and
# cd all persist between commands. LASTEXITCODE is reset per command; a cmdlet
# failure without a native exit code reports 1. Terminating errors are caught and
# printed so a bad command can never kill the driver loop itself.
_PS_DRIVER = """\
$ErrorActionPreference = 'Continue'
try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch {}
while ($true) {
  $__namma_line = [Console]::In.ReadLine()
  if ($null -eq $__namma_line) { break }
  $__namma_i = $__namma_line.IndexOf(' ')
  if ($__namma_i -lt 1) { continue }
  $__namma_nonce = $__namma_line.Substring(0, $__namma_i)
  $__namma_file = $__namma_line.Substring($__namma_i + 1)
  $global:LASTEXITCODE = 0
  $__namma_ok = $true
  try { . $__namma_file; $__namma_ok = $? } catch { $_ | Out-String | Write-Output; $__namma_ok = $false }
  $__namma_ec = $global:LASTEXITCODE
  if ($null -eq $__namma_ec) { $__namma_ec = 0 }
  if (($__namma_ec -eq 0) -and (-not $__namma_ok)) { $__namma_ec = 1 }
  [Console]::Out.WriteLine()
  [Console]::Out.WriteLine('<<<NAMMA:' + $__namma_nonce + ':' + $__namma_ec + ':' + (Get-Location).Path + '>>>')
  [Console]::Out.Flush()
  Remove-Item -LiteralPath $__namma_file -Force -ErrorAction SilentlyContinue
}
"""


@dataclass
class ShellResult:
    ok: bool
    exit_code: int
    output: str
    cwd: str
    timed_out: bool = False
    died: bool = False  # the shell process ended during this command


def _shell_env() -> dict:
    """Environment for spawned shells, with a sanitized PATH.

    Two problems with inheriting PATH verbatim:

    * **Stray virtualenvs shadow python.** A leftover ``venv\\Scripts`` (or
      ``venv/bin``) entry from some *other* product on the user PATH — the
      observed case: an old Hermes install at
      ``AppData\\Local\\hermes\\hermes-agent\\venv\\Scripts`` — makes ``python``
      resolve to that abandoned interpreter in every agent shell. Any entry
      that looks like another venv's binary dir is dropped.
    * **`python` should mean Namma's interpreter.** The running interpreter's
      directory is prepended, so ``python``/``pip`` in the agent's terminal
      operate on the same environment the agent itself runs in.
    """
    env = os.environ.copy()
    exe_dir = os.path.dirname(sys.executable or "")
    exe_key = exe_dir.replace("\\", "/").rstrip("/").lower()

    def _is_stray_venv(entry: str) -> bool:
        key = entry.replace("\\", "/").rstrip("/").lower()
        if not key or key == exe_key:
            return False
        return key.endswith(("/venv/scripts", "/venv/bin",
                             "/.venv/scripts", "/.venv/bin"))

    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]
    kept = [p for p in parts if not _is_stray_venv(p)]
    if len(kept) != len(parts):
        dropped = [p for p in parts if _is_stray_venv(p)]
        logger.info("[shell] dropped stray venv PATH entries: %s", "; ".join(dropped))
    if exe_dir:
        kept = [exe_dir] + [p for p in kept
                            if p.replace("\\", "/").rstrip("/").lower() != exe_key]
    env["PATH"] = os.pathsep.join(kept)
    return env


def _find_shell() -> list[str]:
    if IS_WINDOWS:
        exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File"]
    exe = shutil.which("bash") or "/bin/sh"
    return [exe]


class PersistentShell:
    """One live shell process. ``run()`` is serialized with an internal lock."""

    def __init__(self, session_id: str, cwd: Optional[str] = None):
        self.session_id = session_id
        self.cwd = cwd or os.path.expanduser("~")
        self.last_used = time.time()
        self._proc: Optional[subprocess.Popen] = None
        self._queue: "queue.Queue[Optional[str]]" = queue.Queue()
        self._lock = threading.Lock()
        self._tmpdir = tempfile.mkdtemp(prefix="namma_shell_")
        # Phase 1c: the OS-level sandbox around the current shell child (Windows
        # Job Object handle wrapper; None on POSIX / when unavailable).
        self._sandbox = None

    # -- lifecycle -----------------------------------------------------------

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _spawn(self) -> None:
        if not os.path.isdir(self.cwd):  # last cwd was deleted — fall back home
            self.cwd = os.path.expanduser("~")
        argv = _find_shell()
        ext = ".ps1" if IS_WINDOWS else ".sh"
        driver = os.path.join(self._tmpdir, "driver" + ext)
        # utf-8-sig: Windows PowerShell 5.1 needs the BOM to parse UTF-8 scripts.
        with open(driver, "w", encoding="utf-8-sig" if IS_WINDOWS else "utf-8") as fh:
            fh.write(_PS_DRIVER if IS_WINDOWS else _POSIX_DRIVER)
        from namma_agent.core import sandbox as _sandboxmod

        kwargs: dict = dict(stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=self.cwd,
                            env=_shell_env())
        if IS_WINDOWS:
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        else:
            kwargs["start_new_session"] = True
        # Phase 1c: POSIX rlimits ride the spawn (preexec_fn); the Windows Job
        # Object is attached right after. Both degrade gracefully to today's
        # behavior when the OS refuses.
        kwargs.update(_sandboxmod.popen_extras())
        self._proc = subprocess.Popen(argv + [driver], **kwargs)
        self._sandbox = _sandboxmod.attach(self._proc)
        self._queue = queue.Queue()
        threading.Thread(target=self._reader, args=(self._proc, self._queue),
                         daemon=True, name=f"namma-shell-{self.session_id[:8]}").start()
        logger.info("[shell] spawned %s for session %s (cwd=%s)",
                    os.path.basename(argv[0]), self.session_id[:8], self.cwd)

    @staticmethod
    def _reader(proc: subprocess.Popen, out_q: "queue.Queue[Optional[str]]") -> None:
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        stream = proc.stdout
        try:
            while True:
                raw = stream.read1(4096)
                if not raw:
                    break
                text = decoder.decode(raw)
                if text:
                    out_q.put(text)
        except (OSError, ValueError):
            pass
        out_q.put(None)  # EOF marker

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                if not IS_WINDOWS:
                    # start_new_session=True makes the shell a group leader —
                    # kill the whole group so children die with it.
                    try:
                        os.killpg(os.getpgid(proc.pid), 9)
                    except (OSError, ProcessLookupError):
                        proc.kill()
                else:
                    proc.kill()
                proc.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                pass
        # Windows: closing the Job Object handle (KILL_ON_JOB_CLOSE) terminates
        # any descendant the plain kill() missed.
        sandbox, self._sandbox = self._sandbox, None
        if sandbox is not None:
            sandbox.close()

    def close(self) -> None:
        with self._lock:
            self._kill()
            shutil.rmtree(self._tmpdir, ignore_errors=True)

    # -- execution -------------------------------------------------------------

    def run(self, command: str, timeout: int = 180,
            on_output: Optional[Callable[[str], None]] = None,
            stdin_data: Optional[str] = None) -> ShellResult:
        """Run ``command`` in the persistent shell. ``on_output`` receives chunks
        of merged stdout+stderr as they arrive (live streaming). ``stdin_data``
        is written to the shell's stdin right after the command is dispatched —
        the foreground command inherits it (used for ``sudo -S`` passwords)."""
        with self._lock:
            self.last_used = time.time()
            if not self.alive:
                self._kill()
                self._spawn()
            nonce = uuid.uuid4().hex[:12]
            ext = ".ps1" if IS_WINDOWS else ".sh"
            script = os.path.join(self._tmpdir, f"cmd_{nonce}{ext}")
            with open(script, "w", encoding="utf-8-sig" if IS_WINDOWS else "utf-8") as fh:
                fh.write(command)
                fh.write("\n")
            try:
                self._proc.stdin.write(f"{nonce} {script}\n".encode("utf-8"))
                self._proc.stdin.flush()
                if stdin_data:
                    self._proc.stdin.write(stdin_data.encode("utf-8"))
                    self._proc.stdin.flush()
            except (OSError, ValueError):
                self._kill()
                return ShellResult(ok=False, exit_code=-1, output="",
                                   cwd=self.cwd, died=True)
            return self._collect(nonce, timeout, on_output)

    def _collect(self, nonce: str, timeout: int,
                 on_output: Optional[Callable[[str], None]]) -> ShellResult:
        sent_re = _sentinel_re(nonce)
        deadline = time.monotonic() + timeout
        done: list[str] = []      # finalized output (already streamed)
        done_len = 0
        streamed = 0
        pending = ""              # received, held back until sentinel-safe
        truncated = False

        def _finalize(text: str) -> None:
            nonlocal done_len, streamed, truncated
            if text == "":
                return
            if done_len < _MAX_OUTPUT:
                done.append(text[: _MAX_OUTPUT - done_len])
                done_len += len(done[-1])
            else:
                truncated = True
            if on_output is not None and streamed < _MAX_STREAM:
                chunk = text[: _MAX_STREAM - streamed]
                streamed += len(chunk)
                try:
                    on_output(chunk)
                except Exception:  # noqa: BLE001 - a UI sink must never break the shell
                    pass

        def _result(ec: int, cwd: str, **flags) -> ShellResult:
            out = "".join(done)
            if truncated:
                out += "\n…[output truncated]…"
            if cwd:
                self.cwd = cwd
            return ShellResult(ok=ec == 0 and not flags.get("timed_out") and not flags.get("died"),
                               exit_code=ec, output=out, cwd=self.cwd, **flags)

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _finalize(pending)
                self._kill()
                return _result(-1, "", timed_out=True)
            try:
                chunk = self._queue.get(timeout=min(remaining, 0.5))
            except queue.Empty:
                continue
            if chunk is None:  # EOF — the shell process ended (e.g. `exit`)
                m = sent_re.search(pending)
                if m:  # sentinel made it out just before the shell died
                    _finalize(pending[: m.start()])
                    self._kill()
                    return _result(int(m.group(1)), m.group(2))
                _finalize(pending)
                # A sourced `exit N` takes the whole POSIX shell with it — the
                # shell's own exit status IS the command's. Report it instead
                # of a blanket -1 (died still marks the session for respawn).
                code = self._proc.poll() if self._proc is not None else None
                self._kill()
                return _result(code if code is not None else -1, "", died=True)
            pending += chunk
            m = sent_re.search(pending)
            if m:
                _finalize(pending[: m.start()])
                return _result(int(m.group(1)), m.group(2))
            if len(pending) > _HOLDBACK:
                _finalize(pending[:-_HOLDBACK])
                pending = pending[-_HOLDBACK:]


# -- session manager -----------------------------------------------------------

_shells: dict[str, PersistentShell] = {}
_manager_lock = threading.Lock()


def get_shell(session_id: Optional[str]) -> PersistentShell:
    """The persistent shell for a chat session (created on first use). Also lazily
    closes shells idle past the TTL so abandoned chats don't leak processes."""
    key = session_id or "default"
    with _manager_lock:
        now = time.time()
        for sid in [s for s, sh in _shells.items()
                    if s != key and now - sh.last_used > _IDLE_SECONDS]:
            _shells.pop(sid).close()
        shell = _shells.get(key)
        if shell is None:
            shell = _shells[key] = PersistentShell(key)
        return shell


def close_all() -> None:
    """Shut down every live shell (called on service shutdown)."""
    with _manager_lock:
        for shell in _shells.values():
            shell.close()
        _shells.clear()
