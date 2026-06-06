"""Phase 7 Wave 1 — file/shell/system/apps tools + auto-discovery + safety."""
from __future__ import annotations

import os

import pytest

from friday.core.safety import check_path, is_destructive
from friday.core.tools import ToolRegistry
from friday.tools import load_tools


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


def test_path_security_blocks_traversal(reg):
    r = reg.execute("read_file", {"path": "../../etc/passwd"})
    assert not r.ok and "traversal" in r.error


def test_path_security_blocks_sensitive():
    ok, reason = check_path("/etc/shadow")
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
    assert is_destructive("run_shell")
