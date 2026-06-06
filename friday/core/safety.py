"""Safety for FRIDAY v2 — the code-enforceable bits kept from v1.

Two concerns survive into the cloud-only design (the rest was the model's job):

  * :class:`PathSecurity` — filesystem isolation (traversal / sandbox escape).
  * :func:`is_destructive` — classify tools that should be approval-gated.

Prompt-level policy (URL judgment, website policy, guardrails) is handled by the
capable model, not by code.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

_DEFAULT_ROOTS = [os.path.expanduser("~"), "/tmp", "/var/tmp"]

_BLOCKED = ["/etc/shadow", "/etc/sudoers", "/.ssh/", "/.gnupg/"]


class PathSecurity:
    def __init__(self, roots: Sequence[str] | None = None):
        self._roots = [str(Path(r).resolve()) for r in (roots or _DEFAULT_ROOTS)]

    def validate(self, path: str) -> tuple[bool, str]:
        if not path:
            return False, "empty path"
        if "\x00" in path:
            return False, "null byte in path"
        if ".." in Path(path).parts:
            return False, "path traversal (..)"
        try:
            resolved = str(Path(path).expanduser().resolve())
        except Exception as exc:  # noqa: BLE001
            return False, f"resolve error: {exc}"
        if any(b in resolved for b in _BLOCKED):
            return False, f"blocked path: {resolved}"
        if not any(resolved == r or resolved.startswith(r + os.sep) for r in self._roots):
            return False, f"path outside safe roots: {resolved}"
        return True, ""


_default = PathSecurity()


def check_path(path: str) -> tuple[bool, str]:
    return _default.validate(path)


_DESTRUCTIVE = {
    "delete_file", "write_file", "run_shell", "run_command", "install_package",
    "kill_process", "modify_system",
    # active security scanning — approval-gated even inside lab_mode
    "port_scan", "ping_sweep", "dir_enum", "dns_enum",
    # smart-home device changes + reminder deletion
    "ha_turn_on", "ha_turn_off", "ha_set_temperature", "remove_reminder",
    # memory deletion
    "forget_fact",
}


def is_destructive(tool_name: str) -> bool:
    return tool_name in _DESTRUCTIVE
