"""Process sandbox for shell children (Phase 1c) — stdlib + ctypes only.

The persistent shell (``core/shell_session.py``) runs arbitrary model-authored
commands. This module bounds the blast radius:

**Windows** — every spawned shell is assigned to a **Job Object** with
``KILL_ON_JOB_CLOSE`` (closing the job handle kills the whole descendant tree —
the shell's children can no longer outlive a timeout kill), a per-process
memory cap, an active-process cap (fork-bomb guard), and an optional cumulative
CPU-time cap. Breakaway is NOT granted, so children cannot leave the job.

**POSIX** — ``resource.setrlimit`` applied in the child via ``preexec_fn``
(address-space / CPU / file-size caps, inherited by every descendant), on top of
the existing ``start_new_session=True`` (which lets the caller kill the whole
process group).

Degrades gracefully: if the OS refuses (nested-job quirks on old Windows,
containers without privileges), we warn ONCE and run exactly as before — the
sandbox is armor, not a gate. Config lives under ``security.sandbox`` in
config.yaml; :func:`configure_sandbox` is called by the service at boot (same
pattern as ``core.safety.configure_path_security``).
"""
from __future__ import annotations

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

from namma_agent.core.logger import logger

IS_WINDOWS = platform.system() == "Windows"

# Job Object limit flags (winnt.h).
_JOB_KILL_ON_CLOSE = 0x2000       # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
_JOB_PROCESS_MEMORY = 0x100       # JOB_OBJECT_LIMIT_PROCESS_MEMORY
_JOB_ACTIVE_PROCESS = 0x8         # JOB_OBJECT_LIMIT_ACTIVE_PROCESS
_JOB_JOB_TIME = 0x4               # JOB_OBJECT_LIMIT_JOB_TIME (cumulative user time)
_JOB_EXTENDED_INFO_CLASS = 9      # JobObjectExtendedLimitInformation


@dataclass
class SandboxConfig:
    enabled: bool = True
    memory_mb: int = 4096      # per-process address-space / commit cap (0 = off)
    cpu_seconds: int = 0       # cumulative CPU-time cap (0 = off; the per-command
                               # wall-clock timeout is the first line of defense)
    fsize_mb: int = 0          # POSIX only: largest file a child may create (0 = off)
    max_processes: int = 128   # Windows only: active processes in the job (0 = off)


def sandbox_config(security_cfg: Optional[dict] = None) -> SandboxConfig:
    """Parse ``security.sandbox`` from config (missing/partial → safe defaults)."""
    raw = (security_cfg or {}).get("sandbox") or {}
    cfg = SandboxConfig()
    cfg.enabled = bool(raw.get("enabled", cfg.enabled))
    for key in ("memory_mb", "cpu_seconds", "fsize_mb", "max_processes"):
        try:
            setattr(cfg, key, max(0, int(raw.get(key, getattr(cfg, key)))))
        except (TypeError, ValueError):
            pass  # a malformed value keeps the default
    return cfg


# Module state: the active config (service-configured at boot; defaults for
# bare tests), warn-once bookkeeping, and whether the last attach worked.
_CFG = SandboxConfig()
_WARNED = False
_LAST_ATTACH_OK: Optional[bool] = None  # None = never attempted
_CONFINE_ROOT = ""  # security.shell.confine_to ("" = off)


def configure_sandbox(security_cfg: Optional[dict] = None) -> SandboxConfig:
    """Install the sandbox + shell-confinement config from ``config['security']``
    (service boot)."""
    global _CFG, _CONFINE_ROOT
    _CFG = sandbox_config(security_cfg)
    raw_root = str(((security_cfg or {}).get("shell") or {}).get("confine_to") or "").strip()
    _CONFINE_ROOT = os.path.abspath(os.path.expanduser(raw_root)) if raw_root else ""
    return _CFG


# ── shell confinement (security.shell.confine_to) ────────────────────────────
# A tripwire, not a jail: absolute path arguments (and the shell's own cwd)
# outside the confined root make run_shell ask for explicit user approval
# before running. Relative-path escapes move the cwd, which IS checked on the
# next call — so drift outside the root can't go unnoticed.

_WIN_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s\"'|<>&;]*")
# POSIX absolute paths; `(?<![:\w-])` + `(?!/)` keep URL `//host/...` runs out.
_POSIX_PATH_RE = re.compile(r"(?<![:\w-])/(?!/)[^\s\"'|<>&;]*")


def confine_root() -> str:
    """The active confined shell root ('' when confinement is off)."""
    return _CONFINE_ROOT


def _inside(path: str, root: str) -> bool:
    try:
        candidate = os.path.abspath(os.path.expanduser(path))
        return os.path.commonpath([os.path.normcase(candidate),
                                   os.path.normcase(root)]) == os.path.normcase(root)
    except ValueError:  # different drives on Windows → definitely outside
        return False


def outside_confine(command: str, cwd: str = "") -> list[str]:
    """Absolute paths referenced by ``command`` (plus the shell's cwd) that fall
    outside the confined root. Empty when confinement is off or all inside."""
    root = _CONFINE_ROOT
    if not root:
        return []
    pattern = _WIN_PATH_RE if IS_WINDOWS else _POSIX_PATH_RE
    offenders: list[str] = []
    if cwd and not _inside(cwd, root):
        offenders.append(f"(current directory) {cwd}")
    for match in pattern.findall(command or ""):
        candidate = match.rstrip(").,:;\"'")
        if candidate and not _inside(candidate, root):
            offenders.append(candidate)
    # De-dupe, keep order.
    return list(dict.fromkeys(offenders))


def _warn_once(msg: str) -> None:
    global _WARNED
    if not _WARNED:
        _WARNED = True
        logger.warning("[sandbox] %s — shell commands run WITHOUT resource caps "
                       "(this notice is shown once)", msg)


# ── Windows: Job Objects ─────────────────────────────────────────────────────

def _win_structures(ctypes_mod):
    """Build the JOBOBJECT_* ctypes structures (factored for testability)."""
    ct = ctypes_mod
    wintypes = __import__("ctypes.wintypes", fromlist=["wintypes"])

    class IO_COUNTERS(ct.Structure):
        _fields_ = [(name, ct.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC_LIMITS(ct.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ct.c_size_t),
            ("MaximumWorkingSetSize", ct.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ct.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ct.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ct.c_size_t),
            ("JobMemoryLimit", ct.c_size_t),
            ("PeakProcessMemoryUsed", ct.c_size_t),
            ("PeakJobMemoryUsed", ct.c_size_t),
        ]

    return EXTENDED_LIMITS


class WindowsJobSandbox:
    """One Job Object wrapping one shell process (and every descendant)."""

    def __init__(self, job_handle, kernel32):
        self._job = job_handle
        self._k32 = kernel32

    def close(self) -> None:
        """Close the job handle. With KILL_ON_JOB_CLOSE set, this terminates
        every process still inside the job — the descendant-orphan gap the
        plain ``proc.kill()`` used to leave open."""
        job, self._job = self._job, None
        if job:
            try:
                self._k32.CloseHandle(job)
            except Exception:  # noqa: BLE001
                pass


def _make_windows_job(cfg: SandboxConfig, kernel32=None, ctypes_mod=None):
    """Create + configure a Job Object. Returns (job_handle, kernel32) or None."""
    import ctypes as _ctypes
    ct = ctypes_mod or _ctypes
    k32 = kernel32 if kernel32 is not None else ct.windll.kernel32

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    limits = _win_structures(ct)()
    flags = _JOB_KILL_ON_CLOSE
    if cfg.memory_mb > 0:
        flags |= _JOB_PROCESS_MEMORY
        limits.ProcessMemoryLimit = cfg.memory_mb * 1024 * 1024
    if cfg.max_processes > 0:
        flags |= _JOB_ACTIVE_PROCESS
        limits.BasicLimitInformation.ActiveProcessLimit = cfg.max_processes
    if cfg.cpu_seconds > 0:
        flags |= _JOB_JOB_TIME
        # PerJobUserTimeLimit is in 100-nanosecond ticks.
        limits.BasicLimitInformation.PerJobUserTimeLimit = cfg.cpu_seconds * 10_000_000
    limits.BasicLimitInformation.LimitFlags = flags
    ok = k32.SetInformationJobObject(job, _JOB_EXTENDED_INFO_CLASS,
                                     ct.byref(limits), ct.sizeof(limits))
    if not ok:
        k32.CloseHandle(job)
        return None
    return job, k32


def _attach_windows(proc: subprocess.Popen, cfg: SandboxConfig,
                    kernel32=None, ctypes_mod=None) -> Optional[WindowsJobSandbox]:
    made = _make_windows_job(cfg, kernel32=kernel32, ctypes_mod=ctypes_mod)
    if made is None:
        return None
    job, k32 = made
    # subprocess exposes the native process HANDLE as ``_handle`` on Windows.
    if not k32.AssignProcessToJobObject(job, int(proc._handle)):  # noqa: SLF001
        k32.CloseHandle(job)
        return None
    return WindowsJobSandbox(job, k32)


# ── POSIX: rlimits in the child ──────────────────────────────────────────────

def _posix_limiter(cfg: SandboxConfig, resource_mod=None):
    """The ``preexec_fn`` applying rlimits in the child (inherited by every
    descendant). ``resource_mod`` is injectable so tests run on any platform."""
    if resource_mod is None:
        try:
            import resource as resource_mod  # noqa: PLC0415
        except ImportError:
            return None

    def apply_limits() -> None:
        if cfg.memory_mb > 0:
            byte_cap = cfg.memory_mb * 1024 * 1024
            resource_mod.setrlimit(resource_mod.RLIMIT_AS, (byte_cap, byte_cap))
        if cfg.cpu_seconds > 0:
            resource_mod.setrlimit(resource_mod.RLIMIT_CPU,
                                   (cfg.cpu_seconds, cfg.cpu_seconds))
        if cfg.fsize_mb > 0:
            byte_cap = cfg.fsize_mb * 1024 * 1024
            resource_mod.setrlimit(resource_mod.RLIMIT_FSIZE, (byte_cap, byte_cap))

    return apply_limits


# ── the two calls shell_session makes ────────────────────────────────────────

def popen_extras() -> dict:
    """Extra ``subprocess.Popen`` kwargs for a sandboxed shell child. POSIX gets
    the rlimit ``preexec_fn`` here; Windows limits are applied post-spawn by
    :func:`attach` (a Job Object can't ride Popen kwargs)."""
    global _LAST_ATTACH_OK
    if not _CFG.enabled or IS_WINDOWS:
        return {}
    fn = _posix_limiter(_CFG)
    if fn is None:
        _warn_once("the resource module is unavailable on this platform")
        _LAST_ATTACH_OK = False
        return {}
    _LAST_ATTACH_OK = True
    return {"preexec_fn": fn}


def attach(proc: subprocess.Popen) -> Optional[WindowsJobSandbox]:
    """Attach OS-level limits to a just-spawned shell. Windows: assign to a
    configured Job Object and return its handle wrapper (caller closes it to
    kill the tree). POSIX: limits were installed by :func:`popen_extras`; None.
    Any failure degrades gracefully (warn once, run unsandboxed)."""
    global _LAST_ATTACH_OK
    if not _CFG.enabled or not IS_WINDOWS:
        return None
    try:
        box = _attach_windows(proc, _CFG)
    except Exception as exc:  # noqa: BLE001 — the sandbox must never block the shell
        box = None
        _warn_once(f"Job Object setup failed: {exc}")
    if box is None:
        _warn_once("Windows refused the Job Object (nested-job or policy limits)")
        _LAST_ATTACH_OK = False
        return None
    _LAST_ATTACH_OK = True
    return box


def status() -> dict:
    """Sandbox state for the Status/Security surfaces (names only, no handles)."""
    return {
        "platform": "windows" if IS_WINDOWS else "posix",
        "enabled": _CFG.enabled,
        "active": _LAST_ATTACH_OK,   # None until the first shell spawns
        "memory_mb": _CFG.memory_mb,
        "cpu_seconds": _CFG.cpu_seconds,
        "fsize_mb": _CFG.fsize_mb,
        "max_processes": _CFG.max_processes,
        "mechanism": "job-object" if IS_WINDOWS else "rlimits",
    }
