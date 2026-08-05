"""Phase 7b — checkpoints + rollback (core/checkpoints.py).

Covers the three entry kinds (existing file, absent path, directory), the
manifest-only path for oversized directories (the organize_dir undo), retention
pruning, the model-facing tools, and the agent-loop wiring that snapshots only
destructive write-ish calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from namma_agent.core import checkpoints as cp
from namma_agent.core.checkpoints import CheckpointStore, paths_at_risk
from namma_agent.core.tools import ToolRegistry


@pytest.fixture
def store(tmp_path):
    return CheckpointStore(tmp_path / "checkpoints")


# ── path extraction ──────────────────────────────────────────────────────────

def test_paths_at_risk_reads_known_arg_names(tmp_path):
    found = paths_at_risk({"path": str(tmp_path / "a.txt"),
                           "source": str(tmp_path / "b.txt"),
                           "dest": str(tmp_path / "c.txt")})
    assert len(found) == 3
    assert all(str(tmp_path) in p for p in found)


def test_paths_at_risk_ignores_content_and_other_args():
    """write_file.content is a string but must never be treated as a path."""
    found = paths_at_risk({"content": "C:/Windows/System32", "to": "docx",
                           "query": "/etc/passwd"})
    assert found == []


def test_paths_at_risk_respects_the_schema_type(tmp_path):
    schema = {"properties": {"target": {"type": "integer"}}}
    assert paths_at_risk({"target": "12"}, schema) == []
    assert paths_at_risk({"target": str(tmp_path / "x")},
                         {"properties": {"target": {"type": "string"}}})


def test_paths_at_risk_skips_blanks():
    assert paths_at_risk({"path": "   ", "dest": ""}) == []


def test_paths_at_risk_dedupes(tmp_path):
    p = str(tmp_path / "same.txt")
    assert len(paths_at_risk({"path": p, "source": p})) == 1


# ── snapshot + restore: existing file ────────────────────────────────────────

def test_restore_puts_a_modified_file_back(store, tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")

    checkpoint = store.snapshot("sess1", "write_file", {"path": str(target)})
    assert checkpoint is not None

    target.write_text("clobbered", encoding="utf-8")          # the tool runs
    report = store.restore(checkpoint.id)

    assert report["ok"] is True
    assert target.read_text(encoding="utf-8") == "original"
    assert str(target) in report["restored"]


def test_restore_recreates_a_deleted_file(store, tmp_path):
    target = tmp_path / "gone.txt"
    target.write_text("keep me", encoding="utf-8")
    checkpoint = store.snapshot("s", "delete_path", {"path": str(target)})

    target.unlink()
    store.restore(checkpoint.id)

    assert target.exists() and target.read_text(encoding="utf-8") == "keep me"


# ── snapshot + restore: absent path (a creation) ─────────────────────────────

def test_restore_deletes_a_file_the_tool_created(store, tmp_path):
    target = tmp_path / "new.txt"
    checkpoint = store.snapshot("s", "write_file", {"path": str(target)})
    assert checkpoint.entries[0].kind == "absent"

    target.write_text("brand new", encoding="utf-8")          # the tool runs
    report = store.restore(checkpoint.id)

    assert not target.exists()
    assert str(target) in report["deleted"]


def test_restore_of_a_never_created_path_is_a_no_op(store, tmp_path):
    target = tmp_path / "never.txt"
    checkpoint = store.snapshot("s", "write_file", {"path": str(target)})
    report = store.restore(checkpoint.id)
    assert report["ok"] is True and report["deleted"] == []


# ── snapshot + restore: directories ──────────────────────────────────────────

def test_restore_brings_back_a_deleted_directory(store, tmp_path):
    folder = tmp_path / "docs"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("A", encoding="utf-8")
    (folder / "sub" / "b.txt").write_text("B", encoding="utf-8")

    checkpoint = store.snapshot("s", "delete_path", {"path": str(folder)})
    assert checkpoint.entries[0].kind == "dir"

    import shutil
    shutil.rmtree(folder)
    report = store.restore(checkpoint.id)

    assert report["ok"] is True
    assert (folder / "a.txt").read_text(encoding="utf-8") == "A"
    assert (folder / "sub" / "b.txt").read_text(encoding="utf-8") == "B"


def test_oversized_directory_keeps_a_manifest_and_undoes_moves(tmp_path):
    """The organize_dir case: too big to copy, but files MOVED inside the tree
    can still be put back from the manifest."""
    small_store = CheckpointStore(tmp_path / "cp")
    small_store.max_file_bytes = 1   # the COPY cap — any real folder exceeds it

    folder = tmp_path / "downloads"
    folder.mkdir()
    (folder / "photo.jpg").write_text("img", encoding="utf-8")
    (folder / "report.pdf").write_text("doc", encoding="utf-8")

    checkpoint = small_store.snapshot("s", "organize_dir", {"path": str(folder)})
    entry = checkpoint.entries[0]
    assert entry.truncated is True and entry.stored == ""
    assert sorted(entry.manifest) == ["photo.jpg", "report.pdf"]

    # organize_dir sorts them into type subfolders.
    (folder / "Images").mkdir()
    (folder / "Documents").mkdir()
    (folder / "photo.jpg").rename(folder / "Images" / "photo.jpg")
    (folder / "report.pdf").rename(folder / "Documents" / "report.pdf")

    report = small_store.restore(checkpoint.id)

    assert (folder / "photo.jpg").exists()
    assert (folder / "report.pdf").exists()
    assert report["ok"] is True


def test_manifest_restore_reports_what_it_cannot_find(tmp_path):
    small_store = CheckpointStore(tmp_path / "cp")
    small_store.max_file_bytes = 1

    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "x.txt").write_text("xxxxxxxx", encoding="utf-8")   # over the 1-byte cap
    checkpoint = small_store.snapshot("s", "organize_dir", {"path": str(folder)})
    assert checkpoint.entries[0].truncated is True

    (folder / "x.txt").unlink()          # genuinely gone, not moved
    report = small_store.restore(checkpoint.id)

    assert report["ok"] is False
    assert any("not found" in f["why"] for f in report["failed"])


# ── honest failure reporting ─────────────────────────────────────────────────

def test_oversized_file_is_recorded_as_unrestorable(tmp_path):
    tiny = CheckpointStore(tmp_path / "cp", max_file_mb=0)
    tiny.max_file_bytes = 4          # anything bigger than 4 bytes

    target = tmp_path / "big.bin"
    target.write_bytes(b"0123456789")
    checkpoint = tiny.snapshot("s", "write_file", {"path": str(target)})

    assert checkpoint.entries[0].truncated is True
    report = tiny.restore(checkpoint.id)
    assert report["ok"] is False
    assert "too large" in report["failed"][0]["why"]


def test_restoring_an_unknown_checkpoint_errors(store):
    assert store.restore("nope")["error"]


def test_snapshot_never_raises_on_a_bad_path(store):
    """A failed snapshot must not block a tool the user already approved."""
    assert store.snapshot("s", "write_file", {"path": "\x00invalid"}) is None


def test_disabled_store_snapshots_nothing(tmp_path):
    off = CheckpointStore(tmp_path / "cp", enabled=False)
    target = tmp_path / "a.txt"
    target.write_text("x", encoding="utf-8")
    assert off.snapshot("s", "write_file", {"path": str(target)}) is None


def test_call_with_no_path_args_makes_no_checkpoint(store):
    assert store.snapshot("s", "send_message", {"text": "hi"}) is None


# ── listing, retention, status ───────────────────────────────────────────────

def test_list_is_newest_first_and_session_scoped(store, tmp_path):
    for i, session in enumerate(["a", "b", "a"]):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x", encoding="utf-8")
        store.snapshot(session, "write_file", {"path": str(f)})

    everything = store.list()
    assert len(everything) == 3
    assert everything[0].created_at >= everything[-1].created_at
    assert len(store.list(session_id="a")) == 2


def test_prune_enforces_the_size_budget(tmp_path):
    small = CheckpointStore(tmp_path / "cp", max_total_mb=0)
    small.max_total_bytes = 200      # a couple of small snapshots' worth

    for i in range(6):
        f = tmp_path / f"f{i}.txt"
        f.write_text("x" * 100, encoding="utf-8")
        small.snapshot("s", "write_file", {"path": str(f)})

    assert small.total_bytes() <= small.max_total_bytes or len(small.list()) < 6


def test_delete_removes_the_checkpoint(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    checkpoint = store.snapshot("s", "write_file", {"path": str(f)})
    assert store.delete(checkpoint.id) is True
    assert store.load(checkpoint.id) is None
    assert store.delete(checkpoint.id) is False


def test_status_shape(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    store.snapshot("s", "write_file", {"path": str(f)})
    status = store.status()
    assert status["enabled"] is True and status["count"] == 1
    assert status["last"]


def test_manifest_survives_a_reload(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("original", encoding="utf-8")
    checkpoint = store.snapshot("s1", "write_file", {"path": str(f)})

    reloaded = CheckpointStore(store.root).load(checkpoint.id)
    assert reloaded is not None
    assert reloaded.session_id == "s1" and reloaded.tool == "write_file"
    assert reloaded.entries[0].path == str(f.resolve())


def test_restore_stamps_the_manifest(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("original", encoding="utf-8")
    checkpoint = store.snapshot("s", "write_file", {"path": str(f)})
    store.restore(checkpoint.id)
    raw = json.loads((store.root / checkpoint.id / "manifest.json").read_text(encoding="utf-8"))
    assert raw["restored_at"]


# ── config parsing ───────────────────────────────────────────────────────────

def test_store_config_defaults_and_overrides():
    assert cp.store_config(None) == {"enabled": True, "max_file_mb": 32,
                                     "max_total_mb": 512, "max_age_days": 14}
    parsed = cp.store_config({"checkpoints": {"enabled": False, "max_total_mb": 64,
                                              "max_age_days": "junk"}})
    assert parsed["enabled"] is False
    assert parsed["max_total_mb"] == 64
    assert parsed["max_age_days"] == 14      # malformed value keeps the default


# ── model-facing tools ───────────────────────────────────────────────────────

@pytest.fixture
def registry_with_tools(store):
    reg = ToolRegistry()
    cp.register_checkpoint_tools(reg, store, session_getter=lambda: "sess1")
    return reg


def test_rollback_tool_is_approval_gated(registry_with_tools):
    """Restoring is itself a write — it must go through the approval gate."""
    assert registry_with_tools.get("rollback").destructive is True
    assert registry_with_tools.get("list_checkpoints").destructive is False


def test_list_checkpoints_tool_is_session_scoped(registry_with_tools, store, tmp_path):
    for session in ("sess1", "other"):
        f = tmp_path / f"{session}.txt"
        f.write_text("x", encoding="utf-8")
        store.snapshot(session, "write_file", {"path": str(f)})

    result = registry_with_tools.execute("list_checkpoints", {})
    assert result.ok and len(result.data) == 1

    everything = registry_with_tools.execute("list_checkpoints", {"all_chats": True})
    assert len(everything.data) == 2


def test_list_checkpoints_tool_empty_state(registry_with_tools):
    result = registry_with_tools.execute("list_checkpoints", {})
    assert result.ok and "nothing has been changed" in result.content


def test_rollback_tool_without_an_id_undoes_the_latest_in_this_chat(
        registry_with_tools, store, tmp_path):
    target = tmp_path / "notes.txt"
    target.write_text("original", encoding="utf-8")
    store.snapshot("sess1", "write_file", {"path": str(target)})
    target.write_text("clobbered", encoding="utf-8")

    result = registry_with_tools.execute("rollback", {})
    assert result.ok
    assert target.read_text(encoding="utf-8") == "original"
    assert "Rolled back write_file" in result.content


def test_rollback_tool_with_nothing_to_undo(registry_with_tools):
    result = registry_with_tools.execute("rollback", {})
    assert not result.ok and "nothing to undo" in result.error


def test_rollback_tool_surfaces_partial_failure(registry_with_tools, store, tmp_path):
    store.max_file_bytes = 2
    target = tmp_path / "big.txt"
    target.write_text("too large to snapshot", encoding="utf-8")
    store.snapshot("sess1", "write_file", {"path": str(target)})

    result = registry_with_tools.execute("rollback", {})
    assert result.ok is False
    assert "COULD NOT restore" in result.error


# ── agent-loop wiring ────────────────────────────────────────────────────────

class _FakeTool:
    def __init__(self, name, category, destructive):
        self.name = name
        self.category = category
        self.destructive = destructive
        self.parameters = {"properties": {"path": {"type": "string"}}}


def _agent_with(store):
    from namma_agent.core.agent import Agent

    agent = Agent.__new__(Agent)          # no provider/db needed for this helper
    agent.checkpoints = store
    return agent


def test_agent_checkpoints_a_destructive_write_tool(store, tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    agent = _agent_with(store)
    cid = agent._checkpoint_before("s", _FakeTool("write_file", "file_ops", True),
                                   {"path": str(f)})
    assert cid and store.load(cid) is not None


@pytest.mark.parametrize("tool", [
    _FakeTool("read_file", "file_ops", False),      # not destructive
    _FakeTool("run_shell", "shell", True),          # destructive but not write-ish
    _FakeTool("gmail_send", "gws", True),           # destructive, no files
])
def test_agent_skips_checkpoints_for_other_tools(store, tmp_path, tool):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    agent = _agent_with(store)
    assert agent._checkpoint_before("s", tool, {"path": str(f)}) == ""


def test_agent_without_a_store_is_a_no_op(tmp_path):
    agent = _agent_with(None)
    assert agent._checkpoint_before("s", _FakeTool("write_file", "file_ops", True),
                                    {"path": str(tmp_path / "a.txt")}) == ""


def test_agent_discards_the_checkpoint_when_the_tool_failed(store, tmp_path):
    """A checkpoint for a call that then failed protects nothing — the Undo
    list must only offer real changes."""
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    agent = _agent_with(store)
    cid = agent._checkpoint_before("s", _FakeTool("write_file", "file_ops", True),
                                   {"path": str(f)})
    agent._discard_checkpoint(cid)
    assert store.load(cid) is None


def test_shell_is_deliberately_excluded_from_write_categories():
    assert "shell" not in cp.WRITE_CATEGORIES
    assert {"file_ops", "documents", "authoring", "convert"} == set(cp.WRITE_CATEGORIES)
