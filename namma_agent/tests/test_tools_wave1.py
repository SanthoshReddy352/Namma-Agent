"""Phase 7 Wave 1 — file/shell/system/apps tools + auto-discovery + safety."""
from __future__ import annotations

import os

import pytest

from namma_agent.core.safety import check_path
from namma_agent.core.tools import ToolRegistry
from namma_agent.tools import load_tools


@pytest.fixture
def reg():
    return load_tools(ToolRegistry())


def test_autodiscovery_registers_core_tools(reg):
    for name in ("read_file", "write_file", "list_dir", "run_shell", "system_info", "open_app"):
        assert name in reg


def test_write_then_read(tmp_path, reg):
    f = tmp_path / "note.txt"
    w = reg.execute("write_file", {"path": str(f), "content": "hello v2"})
    assert w.ok
    r = reg.execute("read_file", {"path": str(f)})
    assert r.ok and r.content == "hello v2"


def test_list_dir(tmp_path, reg):
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "sub").mkdir()
    out = reg.execute("list_dir", {"path": str(tmp_path)})
    assert "f a.txt" in out.content and "d sub" in out.content


def test_dotdot_paths_are_checked_after_resolution(tmp_path):
    """Phase 2: a literal ``..`` is no longer rejected outright — the policy runs
    on the RESOLVED path, so ``..`` can't smuggle a write into a protected tree
    or a read into a secret dir, while ``../notes.md`` just works."""
    (tmp_path / "sub").mkdir()
    ok, _ = check_path(str(tmp_path / "sub" / ".." / "notes.md"), write=True)
    assert ok
    home = os.path.expanduser("~")
    ok, reason = check_path(os.path.join(home, "Documents", "..", ".ssh", "id_rsa"))
    assert not ok and "secret" in reason
    sneaky = (r"C:\Users\..\Windows\namma_probe.txt" if os.name == "nt"
              else "/home/../usr/namma_probe.txt")
    ok, reason = check_path(sneaky, write=True)
    assert not ok and "read-only" in reason


def test_app_install_dir_is_writable_even_under_a_protected_root(tmp_path):
    from namma_agent.core.safety import PathSecurity

    app = tmp_path / "Program Files" / "Namma"
    policy = PathSecurity(write_roots=[str(tmp_path / "Program Files")], app_roots=[str(app)])
    assert policy.validate(str(app / "namma_agent" / "config.yaml"), write=True)[0]
    assert not policy.validate(str(tmp_path / "Program Files" / "Other" / "x"), write=True)[0]


def test_path_security_blocks_sensitive():
    ok, reason = check_path("/etc/shadow")
    assert not ok


def test_reads_allowed_but_writes_blocked_in_system_dir():
    # OS / installed-software trees are READ-ONLY: the agent may read them...
    sys_file = r"C:\Windows\namma_agent_probe.txt" if os.name == "nt" else "/usr/namma_agent_probe.txt"
    ok_read, _ = check_path(sys_file, write=False)
    ok_write, reason = check_path(sys_file, write=True)
    assert ok_read                                   # ...reading a system path is fine
    assert not ok_write and "read-only" in reason    # ...but writing it is refused


def test_writes_allowed_outside_system(tmp_path):
    # Documents / project folders (here: a temp dir) stay fully writable.
    ok, _ = check_path(str(tmp_path / "x.txt"), write=True)
    assert ok


def test_secret_keys_blocked_even_for_read():
    ok, _ = check_path(os.path.expanduser("~/.ssh/id_rsa"))
    assert not ok


def test_run_shell(reg):
    r = reg.execute("run_shell", {"command": "echo hello-shell"})
    assert r.ok and "hello-shell" in r.content


def test_run_shell_nonzero(reg):
    r = reg.execute("run_shell", {"command": "exit 3"})
    assert not r.ok and "exit 3" in r.error


def test_system_info(reg):
    r = reg.execute("system_info", {})
    assert r.ok and "os:" in r.content


def test_destructive_classification(reg):
    assert reg.get("write_file").destructive is True
    assert reg.get("run_shell").destructive is True
    assert reg.get("read_file").destructive is False
