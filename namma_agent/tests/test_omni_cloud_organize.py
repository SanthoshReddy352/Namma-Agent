"""Tests for omni_cloud_organize and cloud_move tools.

All HTTP calls are mocked — no live OmniCloud needed.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from unittest.mock import patch, MagicMock

import pytest

from namma_agent.core.tools import ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_files(*names, folder=False):
    """Build fake file lists for mocking _get responses."""
    files = []
    for i, name in enumerate(names):
        files.append({
            "id": f"file_{i}",
            "file_name": name,
            "is_folder": folder,
            "size": 1024,
            "provider": "google_drive",
        })
    return files


def _mock_get(responses):
    """Return a mock for _get that cycles through responses."""
    call_count = [0]

    def fake_get(path, **params):
        idx = call_count[0]
        call_count[0] += 1
        if idx < len(responses):
            return responses[idx]
        return False, None, "No more mocked responses"
    return fake_get


# ---------------------------------------------------------------------------
# cloud_move
# ---------------------------------------------------------------------------

class TestCloudMove:
    """Tests for the cloud_move tool registered in cloud_storage."""

    @pytest.fixture
    def reg(self):
        from namma_agent.tools.cloud_storage import register
        r = ToolRegistry()
        register(r)
        return r

    def test_cloud_move_registered(self, reg):
        assert "cloud_move" in reg
        assert reg.get("cloud_move").destructive is True

    def test_cloud_move_requires_file_id(self, reg):
        r = reg.execute("cloud_move", {"parent_id": "folder_1"})
        assert not r.ok and "file_id" in r.error

    def test_cloud_move_requires_parent_id(self, reg):
        r = reg.execute("cloud_move", {"file_id": "file_1"})
        assert not r.ok and "parent_id" in r.error

    @patch("namma_agent.tools.cloud_storage._patch")
    def test_cloud_move_success(self, mock_patch, reg):
        mock_patch.return_value = (True, {"data": {"success": True}}, "")
        r = reg.execute("cloud_move", {"file_id": "file_1", "parent_id": "folder_1"})
        assert r.ok
        assert "Moved" in r.content
        mock_patch.assert_called_once_with("/files/file_1", {"parent_id": "folder_1"})

    @patch("namma_agent.tools.cloud_storage._patch")
    def test_cloud_move_failure(self, mock_patch, reg):
        mock_patch.return_value = (False, None, "File not found")
        r = reg.execute("cloud_move", {"file_id": "bad", "parent_id": "folder_1"})
        assert not r.ok and "File not found" in r.error


# ---------------------------------------------------------------------------
# omni_cloud_organize
# ---------------------------------------------------------------------------

class TestOmniCloudOrganize:
    """Tests for the omni_cloud_organize tool."""

    @pytest.fixture
    def reg(self):
        from namma_agent.tools.omni_cloud_organize import register
        r = ToolRegistry()
        register(r)
        return r

    def test_registered(self, reg):
        assert "omni_cloud_organize" in reg
        assert reg.get("omni_cloud_organize").destructive is True

    @patch("namma_agent.tools.omni_cloud_organize._get")
    def test_empty_root(self, mock_get, reg):
        mock_get.return_value = (True, {"data": []}, "")
        r = reg.execute("omni_cloud_organize", {})
        assert r.ok
        assert "clean" in r.content.lower() or "no loose" in r.content.lower()

    @patch("namma_agent.tools.omni_cloud_organize._get")
    def test_dry_run_shows_preview(self, mock_get, reg):
        files = _make_files("report.pdf", "photo.jpg", "data.csv")
        # First call: list root files
        # Second call: list root for folders (inside organize)
        mock_get.side_effect = [
            (True, {"data": files}, ""),
            (True, {"data": []}, ""),
        ]
        r = reg.execute("omni_cloud_organize", {"dry_run": True})
        assert r.ok
        assert "DRY RUN" in r.content
        assert "Documents" in r.content  # .pdf -> Documents
        assert "Images" in r.content     # .jpg -> Images
        assert "Spreadsheets" in r.content  # .csv -> Spreadsheets

    @patch("namma_agent.tools.omni_cloud_organize._patch")
    @patch("namma_agent.tools.omni_cloud_organize._post")
    @patch("namma_agent.tools.omni_cloud_organize._get")
    def test_moves_files(self, mock_get, mock_post, mock_patch, reg):
        files = _make_files("report.pdf", "style.css")
        folders = _make_files("Documents", "Code", folder=True)
        folders[0]["id"] = "folder_docs"
        folders[1]["id"] = "folder_code"

        mock_get.side_effect = [
            (True, {"data": files}, ""),       # list root
            (True, {"data": folders}, ""),      # list root for existing folders
            (True, {"data": folders}, ""),      # re-list after create (not needed here)
        ]
        mock_post.return_value = (True, {"data": {"success": True}}, "")  # mkdir
        mock_patch.return_value = (True, {"data": {"success": True}}, "")  # move

        r = reg.execute("omni_cloud_organize", {"dry_run": False})
        assert r.ok
        assert "Moved 2/2" in r.content
        assert mock_patch.call_count == 2

    @patch("namma_agent.tools.omni_cloud_organize._get")
    def test_skips_folders_and_known_dirs(self, mock_get, reg):
        files = _make_files("DSA", "Projects", "report.pdf")
        files[0]["is_folder"] = True
        files[1]["is_folder"] = True
        # Only report.pdf should be categorized
        mock_get.return_value = (True, {"data": files}, "")
        r = reg.execute("omni_cloud_organize", {"dry_run": True})
        assert r.ok
        # Should show 1 file to move (report.pdf), skip 2 (DSA, Projects folders)
        assert "report.pdf" in r.content

    @patch("namma_agent.tools.omni_cloud_organize._get")
    def test_name_pattern_priority(self, mock_get, reg):
        """Name patterns (DSA, SE, etc.) should override extension mapping."""
        files = _make_files("hard_sol.py", "SE_report.docx")
        mock_get.return_value = (True, {"data": files}, "")
        r = reg.execute("omni_cloud_organize", {"dry_run": True})
        assert r.ok
        assert "DSA" in r.content      # hard_sol.py matches DSA pattern, not Code
        assert "SE" in r.content       # SE_report matches SE pattern, not Documents

    @patch("namma_agent.tools.omni_cloud_organize._get")
    def test_max_moves_cap(self, mock_get, reg):
        names = [f"file_{i}.txt" for i in range(100)]
        files = _make_files(*names)
        mock_get.return_value = (True, {"data": files}, "")
        r = reg.execute("omni_cloud_organize", {"dry_run": True, "max_moves": 5})
        assert r.ok
        assert "5 file(s)" in r.content

    @patch("namma_agent.tools.omni_cloud_organize._get")
    def test_no_files_to_organize(self, mock_get, reg):
        """When all items are folders or already categorized."""
        files = _make_files("DSA", "Projects", "Documents", folder=True)
        mock_get.return_value = (True, {"data": files}, "")
        r = reg.execute("omni_cloud_organize", {})
        assert r.ok
        assert "already" in r.content.lower() or "nothing" in r.content.lower()
