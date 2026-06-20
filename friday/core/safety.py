"""Safety for FRIDAY v2 — the code-enforceable bits kept from v1.

Two concerns survive into the cloud-only design (the rest was the model's job):

  * :class:`PathSecurity` — filesystem ACCESS POLICY. FRIDAY's files live all over
    the disk (Desktop, Downloads, project folders on other drives…), so READS are
    allowed anywhere on the machine. WRITES / deletes / renames are refused inside
    operating-system and installed-software directories (``C:\\Windows``,
    ``Program Files``, ``/usr``, ``/etc`` …) so the agent can't corrupt the OS or
    your installed programs — those stay effectively read-only. A short list of
    SECRET files (ssh / gpg / aws keys, ``/etc/shadow`` …) is blocked for reads too.
  * :func:`is_destructive` — classify tools that should be approval-gated.

Tune it from ``config.yaml`` under ``security.filesystem`` (see
:func:`configure_path_security`). Prompt-level policy (URL judgment, website
policy, guardrails) is handled by the capable model, not by code.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

# Secret material — never readable OR writable, on any OS. Matched as a substring
# of the resolved path after folding to lower-case forward slashes, so it catches
# ``~/.ssh/id_rsa``, ``C:\\Users\\me\\.ssh\\…`` and ``/etc/shadow`` alike.
_SECRET_MARKERS = [
    "/.ssh/", "/.gnupg/", "/.aws/", "/.gcp/",
    "/etc/shadow", "/etc/gshadow", "/etc/sudoers",
]


def _default_write_roots() -> list[str]:
    """OS + installed-software directories that stay READ-ONLY to the agent.

    Reads are allowed everywhere; only writes/deletes/renames are refused inside
    these trees, so FRIDAY can read system/program files but can't damage them.
    """
    if os.name == "nt":
        env = os.environ
        candidates = [
            env.get("SystemRoot", r"C:\Windows"),                      # C:\Windows
            env.get("ProgramFiles", r"C:\Program Files"),
            env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            env.get("ProgramW6432", r"C:\Program Files"),
            env.get("ProgramData", r"C:\ProgramData"),
        ]
        return [c for c in candidates if c]
    # POSIX (Linux / macOS): the OS, package-managed binaries/libs, boot + kernel
    # interfaces, and the macOS system/app trees. The user's $HOME is NOT here, so
    # documents and project folders stay fully writable.
    return [
        "/bin", "/sbin", "/lib", "/lib64", "/usr", "/boot", "/opt",
        "/etc", "/sys", "/proc", "/dev",
        "/System", "/Library", "/Applications",  # macOS
    ]


def _fold(resolved: str) -> str:
    """Comparison form of a resolved path: lower-case on case-insensitive OSes."""
    return resolved.lower() if os.name == "nt" else resolved


class PathSecurity:
    """Filesystem access policy. ``validate(path, write=...)`` is the gate."""

    def __init__(self, write_roots: Sequence[str] | None = None,
                 secret_markers: Sequence[str] | None = None):
        roots = list(write_roots) if write_roots is not None else _default_write_roots()
        self._write_roots: list[str] = []
        for r in roots:
            try:
                self._write_roots.append(_fold(str(Path(r).expanduser().resolve())).rstrip("/\\"))
            except Exception:  # noqa: BLE001 — skip an unresolvable root
                continue
        markers = secret_markers if secret_markers is not None else _SECRET_MARKERS
        self._secret_markers = [m.lower() for m in markers]

    def validate(self, path: str, write: bool = False) -> tuple[bool, str]:
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

        folded = _fold(resolved)
        # Secrets are off-limits for BOTH read and write.
        if any(m in folded.replace("\\", "/") for m in self._secret_markers):
            return False, f"blocked: secret path ({resolved})"

        # Reads may go anywhere else. Writes are refused inside system/software trees.
        if write:
            for root in self._write_roots:
                if folded == root or folded.startswith(root + os.sep):
                    return False, (f"read-only system path — writing inside {root!r} "
                                   f"is blocked to protect the OS/installed software: {resolved}")
        return True, ""


_default = PathSecurity()


def configure_path_security(security_config: dict | None = None) -> None:
    """(Re)build the default policy from the ``security`` config block.

    Recognized keys under ``security.filesystem``:

      * ``protected_write_paths``  — REPLACE the OS/software read-only roots.
      * ``extra_protected_write_paths`` — ADD more read-only roots to the defaults.
      * ``writable_anywhere`` (bool) — allow writes everywhere except secrets
        (drops the system/software write protection entirely; use with care).

    Called once at service startup; safe to call with ``None`` (keeps defaults).
    """
    global _default
    cfg = (security_config or {}).get("filesystem") or {}

    if cfg.get("writable_anywhere"):
        roots: list[str] = []
    elif cfg.get("protected_write_paths") is not None:
        roots = list(cfg.get("protected_write_paths") or [])
    else:
        roots = _default_write_roots()
    roots += list(cfg.get("extra_protected_write_paths") or [])

    _default = PathSecurity(write_roots=roots)


def check_path(path: str, write: bool = False) -> tuple[bool, str]:
    """Validate a path for reading (default) or writing (``write=True``)."""
    return _default.validate(path, write=write)


_DESTRUCTIVE = {
    "delete_file", "write_file", "run_shell", "run_command", "install_package",
    "kill_process", "modify_system",
    # active security scanning — approval-gated even inside lab_mode
    "port_scan", "ping_sweep", "dir_enum", "dns_enum",
    # smart-home device changes + reminder deletion
    "ha_turn_on", "ha_turn_off", "ha_set_temperature", "remove_reminder",
    # memory deletion
    "forget_fact",
    # task/goal deletion
    "remove_task", "remove_goal",
    # persona deletion
    "delete_persona",
}


def is_destructive(tool_name: str) -> bool:
    return tool_name in _DESTRUCTIVE
