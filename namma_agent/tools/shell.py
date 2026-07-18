"""Shell tool — run a command in the session's persistent shell (approval-gated).

Each chat session owns one long-lived shell (see ``core/shell_session.py``), so
``cd``, environment variables, and activated venvs persist across calls. Output
streams live to the UI as ``tool_output`` events — the mini-terminal view.
"""
from __future__ import annotations

import re
import subprocess

from namma_agent.core.interactive import emit_event, get_current_session
from namma_agent.core.shell_session import get_shell
from namma_agent.core.tools import ToolRegistry, ToolResult

_TIMEOUT = 180

# Force every `sudo` into non-interactive mode so it never grabs the server's
# terminal to prompt for a password (it reads from /dev/tty, not stdin). With
# passwordless sudo it just works; otherwise it fails fast with a clear message.
_SUDO_RE = re.compile(r"(^|[;&|]\s*)sudo\s+(?!-n\b|-S\b|-A\b|-K\b|-k\b)")


def _noninteractive_sudo(cmd: str) -> str:
    return _SUDO_RE.sub(lambda m: m.group(1) + "sudo -n ", cmd)


def _needs_password(returncode: int, out: str) -> bool:
    low = out.lower()
    return returncode != 0 and ("a password is required" in low
                                or "a terminal is required" in low
                                or "no askpass" in low)


def _run(cmd: str, timeout: int, password: str | None = None) -> subprocess.CompletedProcess:
    """Run in the session's persistent shell, streaming chunks to the UI. With a
    password, feed it on the shell's stdin for `sudo -S` (and nowhere else).
    Returns a CompletedProcess-alike (stderr is merged into stdout)."""
    sid = get_current_session()
    shell = get_shell(sid)

    def stream(chunk: str) -> None:
        emit_event("tool_output", {"session_id": sid, "tool": "run_shell", "text": chunk})

    res = shell.run(cmd, timeout=timeout, on_output=stream,
                    stdin_data=(password + "\n") if password is not None else None)
    if res.timed_out:
        raise subprocess.TimeoutExpired(cmd, timeout, output=res.output)
    out = res.output
    if res.died:
        out += ("\n[the shell process exited during this command — a fresh shell "
                "(home directory, clean environment) starts on the next call]")
    return subprocess.CompletedProcess(args=cmd, returncode=res.exit_code,
                                       stdout=out, stderr="")


def _run_shell(args: dict) -> ToolResult:
    raw = args.get("command", "").strip()
    if not raw:
        return ToolResult(ok=False, content="", error="empty command")
    cmd = _noninteractive_sudo(raw)
    timeout = max(1, min(int(args.get("timeout", _TIMEOUT) or _TIMEOUT), 1800))
    shell = get_shell(get_current_session())
    if args.get("restart"):
        shell.close()
        shell = get_shell(get_current_session())
    cwd_before = shell.cwd
    # Phase 1c: confined shell root (security.shell.confine_to). Touching paths
    # outside it needs the user's explicit go-ahead — the model must ask, then
    # re-run with outside_root_approved=true. A tripwire, not a jail.
    from namma_agent.core.sandbox import confine_root, outside_confine

    if confine_root() and not args.get("outside_root_approved"):
        offenders = outside_confine(cmd, cwd=cwd_before)
        if offenders:
            return ToolResult(ok=False, content="", error=(
                f"The shell is confined to {confine_root()} and this command touches "
                f"paths outside it: {', '.join(offenders[:3])}. Ask the user for "
                "explicit permission first; if they approve, re-run this exact "
                "command with outside_root_approved=true."))
    try:
        proc = _run(cmd, timeout)
        # If a sudo password is required, ask the UI once and retry with `sudo -S`.
        # The secret goes ONLY to sudo's stdin — never logged, stored, or returned.
        if _needs_password(proc.returncode, (proc.stdout or "") + (proc.stderr or "")) and "sudo -n " in cmd:
            from namma_agent.core.interactive import get_askpass

            askpass = get_askpass()
            if askpass is not None:
                pwd = askpass("Enter your sudo password")
                if pwd:
                    proc = _run(cmd.replace("sudo -n ", "sudo -S -p '' "), timeout, password=pwd)
                    del pwd
    except subprocess.TimeoutExpired as exc:
        partial = (exc.output or "").strip()
        note = (f"timed out after {timeout}s — the command was killed and the shell "
                f"restarted (cwd is kept; shell variables are lost)")
        return ToolResult(ok=False, content=partial, error=note if not partial
                          else f"{note}\npartial output:\n{partial[:2000]}")
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    out = out.strip()[:20_000] or "(no output)"
    if _needs_password(proc.returncode, out):
        out += ("\n\n(No sudo password was provided. Configure passwordless sudo, "
                "or run it yourself with `! sudo …` in your terminal.)")
    cwd_after = get_shell(get_current_session()).cwd
    if cwd_after != cwd_before:
        out += f"\n[cwd is now: {cwd_after}]"
    return ToolResult(ok=proc.returncode == 0, content=out,
                      data={"cwd": cwd_after, "exit_code": proc.returncode},
                      error="" if proc.returncode == 0 else f"exit {proc.returncode}: {out[:300]}")


def register(registry: ToolRegistry) -> None:
    registry.register("run_shell",
        "Run a NON-INTERACTIVE shell command in this chat's PERSISTENT terminal "
        "(PowerShell on Windows, bash on Linux/macOS) and return stdout/stderr. "
        "The working directory, environment variables, and activated venvs PERSIST "
        "between calls — `cd` somewhere once and later commands run there. Cannot "
        "answer interactive prompts (use `sudo -n` / `apt -y` / "
        "`DEBIAN_FRONTEND=noninteractive`).", {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "the shell command to run"},
                "timeout": {"type": "integer", "description": "seconds (default 180, max 1800)"},
                "restart": {"type": "boolean", "description":
                            "restart the shell first (fresh environment, home directory) "
                            "— use only if the shell seems wedged"},
                "outside_root_approved": {"type": "boolean", "description":
                            "set true ONLY after the user explicitly approved touching "
                            "paths outside the confined shell root"},
            },
            "required": ["command"],
        }, _run_shell, destructive=True)
