"""Phase 1c — sandboxed shell execution (core/sandbox.py).

Windows Job Object limits (exercised with a fake kernel32 everywhere, plus one
real-OS integration test that only runs on Windows), POSIX rlimits (exercised
with a fake resource module so the test runs on any platform), graceful
degradation (warn once, never block the shell), and the confined-root tripwire.
"""
from __future__ import annotations

import subprocess
import sys
import time

import pytest

from namma_agent.core import sandbox as sb


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Each test starts from defaults and leaves no config behind."""
    sb.configure_sandbox(None)
    sb._WARNED = False
    sb._LAST_ATTACH_OK = None
    yield
    sb.configure_sandbox(None)
    sb._WARNED = False
    sb._LAST_ATTACH_OK = None


# ── config parsing ───────────────────────────────────────────────────────────

def test_defaults():
    cfg = sb.sandbox_config(None)
    assert cfg.enabled and cfg.memory_mb == 4096
    assert cfg.cpu_seconds == 0 and cfg.max_processes == 128


def test_config_overrides_and_bad_values():
    cfg = sb.sandbox_config({"sandbox": {
        "enabled": False, "memory_mb": 512, "cpu_seconds": "abc",
        "max_processes": -5}})
    assert cfg.enabled is False
    assert cfg.memory_mb == 512
    assert cfg.cpu_seconds == 0      # malformed keeps the default
    assert cfg.max_processes == 0    # negatives clamp to off


def test_status_shape():
    st = sb.status()
    assert st["mechanism"] in ("job-object", "rlimits")
    assert st["active"] is None  # nothing spawned yet
    assert st["enabled"] is True


# ── Windows job object (fake kernel32 — runs on every platform) ──────────────

class FakeKernel32:
    def __init__(self, fail=""):
        self.fail = fail
        self.calls = []
        self.closed = []

    def CreateJobObjectW(self, a, b):  # noqa: N802
        self.calls.append("create")
        return 0 if self.fail == "create" else 1234

    def SetInformationJobObject(self, job, cls, info, size):  # noqa: N802
        self.calls.append("set")
        self.limits = info._obj if hasattr(info, "_obj") else info
        return 0 if self.fail == "set" else 1

    def AssignProcessToJobObject(self, job, handle):  # noqa: N802
        self.calls.append(("assign", job, handle))
        return 0 if self.fail == "assign" else 1

    def CloseHandle(self, job):  # noqa: N802
        self.closed.append(job)
        return 1


class FakeProc:
    _handle = 42


def test_windows_job_sets_limits_and_assigns():
    cfg = sb.SandboxConfig(memory_mb=256, cpu_seconds=60, max_processes=16)
    k32 = FakeKernel32()
    box = sb._attach_windows(FakeProc(), cfg, kernel32=k32)
    assert isinstance(box, sb.WindowsJobSandbox)
    assert ("assign", 1234, 42) in k32.calls
    basic = k32.limits.BasicLimitInformation
    assert basic.LimitFlags & sb._JOB_KILL_ON_CLOSE
    assert basic.LimitFlags & sb._JOB_PROCESS_MEMORY
    assert basic.LimitFlags & sb._JOB_ACTIVE_PROCESS
    assert basic.LimitFlags & sb._JOB_JOB_TIME
    assert k32.limits.ProcessMemoryLimit == 256 * 1024 * 1024
    assert basic.ActiveProcessLimit == 16
    assert basic.PerJobUserTimeLimit == 60 * 10_000_000
    box.close()
    assert k32.closed == [1234]
    box.close()  # idempotent
    assert k32.closed == [1234]


def test_windows_job_zero_caps_leave_flags_off():
    cfg = sb.SandboxConfig(memory_mb=0, cpu_seconds=0, max_processes=0)
    k32 = FakeKernel32()
    assert sb._attach_windows(FakeProc(), cfg, kernel32=k32) is not None
    flags = k32.limits.BasicLimitInformation.LimitFlags
    assert flags == sb._JOB_KILL_ON_CLOSE  # kill-on-close always; caps off


@pytest.mark.parametrize("fail_at", ["create", "set", "assign"])
def test_windows_job_failure_degrades(fail_at):
    k32 = FakeKernel32(fail=fail_at)
    box = sb._attach_windows(FakeProc(), sb.SandboxConfig(), kernel32=k32)
    assert box is None
    if fail_at in ("set", "assign"):  # a created job never leaks its handle
        assert k32.closed == [1234]


# ── POSIX rlimits (fake resource module — runs on every platform) ────────────

class FakeResource:
    RLIMIT_AS, RLIMIT_CPU, RLIMIT_FSIZE = "as", "cpu", "fsize"

    def __init__(self):
        self.set = {}

    def setrlimit(self, which, pair):
        self.set[which] = pair


def test_posix_limiter_applies_configured_caps():
    res = FakeResource()
    fn = sb._posix_limiter(sb.SandboxConfig(memory_mb=100, cpu_seconds=30,
                                            fsize_mb=10), resource_mod=res)
    fn()
    assert res.set["as"] == (100 * 1024 * 1024, 100 * 1024 * 1024)
    assert res.set["cpu"] == (30, 30)
    assert res.set["fsize"] == (10 * 1024 * 1024, 10 * 1024 * 1024)


def test_posix_limiter_zero_caps_touch_nothing():
    res = FakeResource()
    sb._posix_limiter(sb.SandboxConfig(memory_mb=0, cpu_seconds=0, fsize_mb=0),
                      resource_mod=res)()
    assert res.set == {}


# ── attach()/popen_extras() plumbing + degradation ───────────────────────────

def test_disabled_sandbox_is_a_noop():
    sb.configure_sandbox({"sandbox": {"enabled": False}})
    assert sb.popen_extras() == {}
    assert sb.attach(FakeProc()) is None
    assert sb.status()["enabled"] is False


def test_attach_windows_path_warns_once_on_refusal(monkeypatch, caplog):
    monkeypatch.setattr(sb, "IS_WINDOWS", True)
    monkeypatch.setattr(sb, "_attach_windows", lambda proc, cfg: None)
    import logging
    with caplog.at_level(logging.WARNING):
        assert sb.attach(FakeProc()) is None
        assert sb.attach(FakeProc()) is None
    warnings = [r for r in caplog.records if "WITHOUT resource caps" in r.message]
    assert len(warnings) == 1  # warned exactly once
    assert sb.status()["active"] is False


def test_attach_success_marks_active(monkeypatch):
    monkeypatch.setattr(sb, "IS_WINDOWS", True)
    fake_box = sb.WindowsJobSandbox(1, FakeKernel32())
    monkeypatch.setattr(sb, "_attach_windows", lambda proc, cfg: fake_box)
    assert sb.attach(FakeProc()) is fake_box
    assert sb.status()["active"] is True


def test_popen_extras_posix(monkeypatch):
    monkeypatch.setattr(sb, "IS_WINDOWS", False)
    extras = sb.popen_extras()
    if sys.platform == "win32":
        # No resource module here — must degrade to {} without raising.
        assert extras == {}
    else:
        assert callable(extras.get("preexec_fn"))


# ── real-OS integration (Windows only): kill-on-close kills the child ────────

@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job Object")
def test_real_job_object_kill_on_close_terminates_process():
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                            creationflags=0x08000000)
    try:
        box = sb._attach_windows(proc, sb.SandboxConfig())
        assert box is not None
        assert proc.poll() is None  # alive inside the job
        box.close()                 # kill-on-close → the whole tree dies
        deadline = time.monotonic() + 5
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            proc.kill()


# ── confined shell root ──────────────────────────────────────────────────────

def test_confine_off_by_default():
    assert sb.confine_root() == ""
    assert sb.outside_confine("rm -rf /", cwd="/") == []


def test_confine_flags_outside_paths(tmp_path):
    root = str(tmp_path)
    sb.configure_sandbox({"shell": {"confine_to": root}})
    inside = str(tmp_path / "sub" / "x.txt")
    if sys.platform == "win32":
        outside = "C:\\Windows\\System32\\drivers\\etc\\hosts"
    else:
        outside = "/etc/passwd"
    assert sb.outside_confine(f'cat "{inside}"', cwd=root) == []
    offenders = sb.outside_confine(f"cat {outside}", cwd=root)
    assert offenders and outside in offenders[0]


def test_confine_flags_cwd_outside_root(tmp_path):
    sb.configure_sandbox({"shell": {"confine_to": str(tmp_path / "workdir")}})
    offenders = sb.outside_confine("ls", cwd=str(tmp_path))
    assert offenders and "(current directory)" in offenders[0]


def test_confine_ignores_urls(tmp_path):
    sb.configure_sandbox({"shell": {"confine_to": str(tmp_path)}})
    if sys.platform != "win32":
        # URL slashes must not read as absolute paths.
        assert sb.outside_confine("curl https://example.com/a/b", cwd=str(tmp_path)) == []


def test_run_shell_confine_gate(tmp_path, monkeypatch):
    """The tool refuses outside-root commands until the model passes the
    explicit user-approval flag."""
    from namma_agent.tools import shell as shellmod

    class StubShell:
        cwd = str(tmp_path)

        def close(self):
            pass

    ran = {}

    def fake_run(cmd, timeout, password=None):
        ran["cmd"] = cmd
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(shellmod, "get_shell", lambda sid: StubShell())
    monkeypatch.setattr(shellmod, "_run", fake_run)
    sb.configure_sandbox({"shell": {"confine_to": str(tmp_path)}})

    outside = "C:\\Windows\\foo.txt" if sys.platform == "win32" else "/etc/passwd"
    r = shellmod._run_shell({"command": f"cat {outside}"})
    assert not r.ok and "confined" in r.error and "outside_root_approved" in r.error
    assert "cmd" not in ran  # never reached the shell

    r = shellmod._run_shell({"command": f"cat {outside}", "outside_root_approved": True})
    assert r.ok and ran["cmd"].startswith("cat ")

    r = shellmod._run_shell({"command": "echo hello"})
    assert r.ok  # inside-root commands flow through untouched
