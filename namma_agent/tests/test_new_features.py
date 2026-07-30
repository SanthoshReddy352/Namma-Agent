"""Tests for the new tool modules: cloud_storage (OmniCloud) and system_monitor."""
from __future__ import annotations

import json
import os
import time
from unittest.mock import patch, MagicMock

import pytest

from namma_agent.core.tools import ToolRegistry
from namma_agent.tools import load_tools


@pytest.fixture
def reg():
    return load_tools(ToolRegistry())


# ── Cloud Storage (OmniCloud) ──────────────────────────────────────

def test_cloud_tools_registered(reg):
    """All cloud tools should be registered via auto-discovery."""
    expected = (
        "cloud_health", "cloud_accounts", "cloud_connect",
        "cloud_list", "cloud_search", "cloud_upload", "cloud_download",
        "cloud_mkdir", "cloud_rename", "cloud_delete", "cloud_star", "cloud_sync",
    )
    for name in expected:
        assert name in reg, f"{name} not registered"


def test_cloud_health_omnicloud_down(reg):
    """When OmniCloud is not running, cloud_health should return a setup hint."""
    with patch("namma_agent.tools.cloud_storage._get", return_value=(False, None, "Connection refused")):
        r = reg.execute("cloud_health", {})
        assert not r.ok
        assert "refused" in r.error or "OmniCloud" in r.error


def test_cloud_health_omnicloud_up(reg):
    """When OmniCloud is running, cloud_health should return status."""
    mock_response = {
        "status": "ok",
        "config": {"appMode": "local"},
        "sync": {"lastRunAt": "2026-07-26T00:00:00Z", "scannedAccounts": 2},
    }
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, mock_response, "")):
        r = reg.execute("cloud_health", {})
        assert r.ok
        assert "ok" in r.content.lower()
        assert "local" in r.content


def test_cloud_accounts_empty(reg):
    """No accounts connected should return a helpful message."""
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, {"data": []}, "")):
        r = reg.execute("cloud_accounts", {})
        assert r.ok
        assert "No cloud accounts" in r.content


def test_cloud_accounts_lists_providers(reg):
    """Connected accounts should be listed with provider info."""
    mock_accounts = {
        "data": [
            {"provider": "google_drive", "email": "user@gmail.com", "status": "active",
             "total_space": 15000000000, "used_space": 5000000000, "free_space": 10000000000},
            {"provider": "onedrive", "email": "user@outlook.com", "status": "active",
             "total_space": 5000000000, "used_space": 1000000000, "free_space": 4000000000},
        ]
    }
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, mock_accounts, "")):
        r = reg.execute("cloud_accounts", {})
        assert r.ok
        assert "google_drive" in r.content
        assert "onedrive" in r.content
        assert "user@gmail.com" in r.content


def test_cloud_connect_requires_provider(reg):
    r = reg.execute("cloud_connect", {})
    assert not r.ok
    assert "provider" in r.error


def test_cloud_connect_invalid_provider(reg):
    r = reg.execute("cloud_connect", {"provider": "aws_s3"})
    assert not r.ok
    assert "Unknown provider" in r.error


def test_cloud_connect_google(reg):
    """Connect should return an OAuth URL."""
    mock_data = {
        "data": {
            "authorizationUrl": "https://accounts.google.com/o/oauth2/auth?...",
            "state": "test-state-123",
        }
    }
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, mock_data, "")):
        r = reg.execute("cloud_connect", {"provider": "google_drive"})
        assert r.ok
        assert "accounts.google.com" in r.content
        assert "test-state-123" in r.data.get("state", "")


def test_cloud_list_empty(reg):
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, {"data": []}, "")):
        r = reg.execute("cloud_list", {})
        assert r.ok
        assert "No files" in r.content


def test_cloud_list_with_files(reg):
    mock_files = {
        "data": [
            {"id": "f1", "file_name": "report.pdf", "is_folder": False, "size": 1048576,
             "provider": "google_drive", "is_starred": True},
            {"id": "d1", "file_name": "Photos", "is_folder": True, "size": 0,
             "provider": "google_drive"},
        ]
    }
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, mock_files, "")):
        r = reg.execute("cloud_list", {})
        assert r.ok
        assert "report.pdf" in r.content
        assert "Photos" in r.content
        assert "\u2605" in r.content  # star indicator


def test_cloud_list_starred(reg):
    """Starred filter should pass starred=1 param."""
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, {"data": []}, "")) as mock_get:
        reg.execute("cloud_list", {"starred": True})
        mock_get.assert_called_once_with("/files", starred="1")


def test_cloud_search_requires_query(reg):
    r = reg.execute("cloud_search", {})
    assert not r.ok
    assert "query" in r.error


def test_cloud_search_finds_files(reg):
    mock_files = {
        "data": [
            {"id": "f1", "file_name": "vacation.jpg", "is_folder": False, "provider": "google_drive"},
        ]
    }
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, mock_files, "")):
        r = reg.execute("cloud_search", {"query": "vacation"})
        assert r.ok
        assert "vacation.jpg" in r.content


def test_cloud_search_no_results(reg):
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, {"data": []}, "")):
        r = reg.execute("cloud_search", {"query": "zzzznotfound"})
        assert r.ok
        assert "No files matching" in r.content


def test_cloud_upload_requires_path(reg):
    r = reg.execute("cloud_upload", {})
    assert not r.ok
    assert "local_path" in r.error


def test_cloud_upload_missing_file(reg):
    r = reg.execute("cloud_upload", {"local_path": "/nonexistent/file.txt"})
    assert not r.ok
    assert "not found" in r.error.lower()


def test_cloud_upload_success(tmp_path, reg):
    """Upload a real file through mock OmniCloud."""
    test_file = tmp_path / "hello.txt"
    test_file.write_text("Hello, World!")

    # Mock initiate response
    mock_init = {
        "data": {
            "upload_id": "up-123",
            "session_token": "tok-abc",
            "target_account": {"id": "acc-1", "provider": "google_drive", "email": "user@gmail.com"},
        }
    }
    mock_stream = {"data": {"id": "file-456", "name": "hello.txt"}}

    with patch("namma_agent.tools.cloud_storage._post", return_value=(True, mock_init, "")) as mock_post, \
         patch("namma_agent.tools.cloud_storage.urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_stream).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        r = reg.execute("cloud_upload", {"local_path": str(test_file)})
        assert r.ok
        assert "hello.txt" in r.content
        assert "google_drive" in r.content


def test_cloud_download_requires_id(reg):
    r = reg.execute("cloud_download", {})
    assert not r.ok
    assert "file_id" in r.error


def test_cloud_download_folder_fails(reg):
    """Should not be able to download a folder."""
    mock_detail = {"data": {"file_name": "Photos", "is_folder": True}}
    with patch("namma_agent.tools.cloud_storage._get", return_value=(True, mock_detail, "")):
        r = reg.execute("cloud_download", {"file_id": "d1"})
        assert not r.ok
        assert "folder" in r.error.lower()


def test_cloud_mkdir_requires_name(reg):
    r = reg.execute("cloud_mkdir", {})
    assert not r.ok
    assert "name" in r.error


def test_cloud_mkdir_success(reg):
    with patch("namma_agent.tools.cloud_storage._post", return_value=(True, {"data": {"success": True}}, "")):
        r = reg.execute("cloud_mkdir", {"name": "New Folder"})
        assert r.ok
        assert "New Folder" in r.content


def test_cloud_rename_requires_both(reg):
    r = reg.execute("cloud_rename", {})
    assert not r.ok
    r2 = reg.execute("cloud_rename", {"file_id": "f1"})
    assert not r2.ok


def test_cloud_rename_success(reg):
    with patch("namma_agent.tools.cloud_storage._patch", return_value=(True, {"data": {"success": True}}, "")):
        r = reg.execute("cloud_rename", {"file_id": "f1", "name": "renamed.txt"})
        assert r.ok
        assert "renamed.txt" in r.content


def test_cloud_delete_requires_id(reg):
    r = reg.execute("cloud_delete", {})
    assert not r.ok
    assert "file_id" in r.error


def test_cloud_delete_success(reg):
    with patch("namma_agent.tools.cloud_storage._delete", return_value=(True, {"data": {"success": True}}, "")):
        r = reg.execute("cloud_delete", {"file_id": "f1"})
        assert r.ok
        assert "Deleted" in r.content


def test_cloud_star_requires_id(reg):
    r = reg.execute("cloud_star", {})
    assert not r.ok
    assert "file_id" in r.error


def test_cloud_star_success(reg):
    with patch("namma_agent.tools.cloud_storage._patch", return_value=(True, {"data": {"success": True}}, "")):
        r = reg.execute("cloud_star", {"file_id": "f1", "is_starred": True})
        assert r.ok
        assert "Starred" in r.content


def test_cloud_unstar(reg):
    with patch("namma_agent.tools.cloud_storage._patch", return_value=(True, {"data": {"success": True}}, "")):
        r = reg.execute("cloud_star", {"file_id": "f1", "is_starred": False})
        assert r.ok
        assert "Unstarred" in r.content


def test_cloud_sync(reg):
    mock_report = {"data": {"scannedAccounts": 3, "changesDetected": 5}}
    with patch("namma_agent.tools.cloud_storage._post", return_value=(True, mock_report, "")):
        r = reg.execute("cloud_sync", {})
        assert r.ok
        assert "3" in r.content
        assert "5" in r.content


def test_cloud_tools_destructive():
    """Verify destructive flags are set correctly."""
    reg = load_tools(ToolRegistry())
    # Read-only tools
    assert reg.get("cloud_health").destructive is False
    assert reg.get("cloud_accounts").destructive is False
    assert reg.get("cloud_connect").destructive is False
    assert reg.get("cloud_list").destructive is False
    assert reg.get("cloud_search").destructive is False
    # Destructive tools
    assert reg.get("cloud_upload").destructive is True
    assert reg.get("cloud_download").destructive is True
    assert reg.get("cloud_mkdir").destructive is True
    assert reg.get("cloud_rename").destructive is True
    assert reg.get("cloud_delete").destructive is True
    assert reg.get("cloud_star").destructive is True
    assert reg.get("cloud_sync").destructive is True


# ── System Monitor ─────────────────────────────────────────────────

def test_system_monitor_registered(reg):
    assert "system_monitor" in reg
    assert "system_monitor_trend" in reg


def test_system_monitor_snapshot(reg):
    r = reg.execute("system_monitor", {})
    assert r.ok
    assert "CPU" in r.content
    assert "Memory" in r.content


def test_system_monitor_trend_initial(reg):
    r = reg.execute("system_monitor_trend", {"action": "status"})
    assert r.ok


def test_system_monitor_trend_snapshot(reg):
    r = reg.execute("system_monitor_trend", {"action": "snapshot"})
    assert r.ok
    assert "Snapshot saved" in r.content


def test_system_monitor_trend_status_after_snapshot(reg):
    reg.execute("system_monitor_trend", {"action": "snapshot"})
    reg.execute("system_monitor_trend", {"action": "snapshot"})
    r = reg.execute("system_monitor_trend", {"action": "status"})
    assert r.ok
    assert "snapshots" in r.content.lower() or "CPU" in r.content


def test_system_monitor_trend_clear(reg):
    reg.execute("system_monitor_trend", {"action": "snapshot"})
    r = reg.execute("system_monitor_trend", {"action": "clear"})
    assert r.ok
    assert "cleared" in r.content


def test_system_monitor_non_destructive():
    reg = load_tools(ToolRegistry())
    assert reg.get("system_monitor").destructive is False
    assert reg.get("system_monitor_trend").destructive is False
