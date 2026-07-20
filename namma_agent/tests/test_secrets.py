"""Phase 1d — secrets vault + redaction (core/secrets.py).

Vault round-trips (file backend everywhere; a real Credential Manager round-trip
on Windows), the names-only index, the boot bridge, opt-in .env migration, and
the redaction pass in tool output + the application log.
"""
from __future__ import annotations

import logging
import os
import sys
import uuid

import pytest

from namma_agent.core import secrets as sec
from namma_agent.core.logger import logger
from namma_agent.core.tools import ToolRegistry


@pytest.fixture()
def store(tmp_path):
    """A file-backed vault in a temp dir, installed as the process singleton."""
    s = sec.SecretStore(str(tmp_path),
                        backend=sec.FileBackend(tmp_path / "vault.json"))
    sec.set_store(s)
    yield s
    sec.set_store(None)
    sec.refresh_redaction()


# ── vault round-trips ────────────────────────────────────────────────────────

def test_file_backend_round_trip(store):
    assert store.set("NAMMA_TEST_TOKEN", "super-secret-value-123")
    assert store.get("NAMMA_TEST_TOKEN") == "super-secret-value-123"
    assert store.names() == ["NAMMA_TEST_TOKEN"]
    assert store.delete("NAMMA_TEST_TOKEN")
    assert store.get("NAMMA_TEST_TOKEN") is None
    assert store.names() == []


def test_file_backend_values_not_plaintext_on_disk(store, tmp_path):
    store.set("NAMMA_TEST_TOKEN", "plainly-visible-value")
    raw = (tmp_path / "vault.json").read_text(encoding="utf-8")
    assert "plainly-visible-value" not in raw  # DPAPI (win) / obfuscated (posix)
    assert "NAMMA_TEST_TOKEN" in raw           # names are not secret


def test_store_rejects_bad_input(store):
    assert not store.set("", "value")
    assert not store.set("has space", "value")
    assert not store.set("NAMMA_X", "")
    assert store.names() == []


def test_unknown_get_returns_none(store):
    assert store.get("NEVER_STORED") is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Credential Manager")
def test_credential_manager_round_trip():
    backend = sec.CredManBackend()
    name = f"NAMMA_PYTEST_{uuid.uuid4().hex[:8]}"
    try:
        assert backend.set(name, "credman-secret-42")
        assert backend.get(name) == "credman-secret-42"
    finally:
        backend.delete(name)
    assert backend.get(name) is None


# ── boot bridge + migration ──────────────────────────────────────────────────

def test_bridge_env_fills_only_unset(store, monkeypatch):
    store.set("NAMMA_BRIDGE_A_TOKEN", "bridged-value-aaa")
    store.set("NAMMA_BRIDGE_B_TOKEN", "bridged-value-bbb")
    monkeypatch.delenv("NAMMA_BRIDGE_A_TOKEN", raising=False)
    monkeypatch.setenv("NAMMA_BRIDGE_B_TOKEN", "live-env-wins")
    bridged = sec.bridge_env()
    assert "NAMMA_BRIDGE_A_TOKEN" in bridged
    assert os.environ["NAMMA_BRIDGE_A_TOKEN"] == "bridged-value-aaa"
    assert os.environ["NAMMA_BRIDGE_B_TOKEN"] == "live-env-wins"  # untouched
    monkeypatch.delenv("NAMMA_BRIDGE_A_TOKEN", raising=False)


def test_migrate_env_file_moves_secret_looking_keys(store, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment stays\n"
        "NAMMA_TELEGRAM_TOKEN=tg-secret-123456\n"
        "ASSISTANT_NAME=Namma\n"
        "SOME_API_KEY='quoted-key-987654'\n",
        encoding="utf-8")
    monkeypatch.delenv("NAMMA_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("SOME_API_KEY", raising=False)

    report = sec.migrate_env_file(str(env_file))
    assert sorted(report["migrated"]) == ["NAMMA_TELEGRAM_TOKEN", "SOME_API_KEY"]
    assert store.get("NAMMA_TELEGRAM_TOKEN") == "tg-secret-123456"
    assert store.get("SOME_API_KEY") == "quoted-key-987654"
    assert store.get("ASSISTANT_NAME") is None       # not secret-looking
    assert not report["scrubbed"]
    assert "tg-secret-123456" in env_file.read_text(encoding="utf-8")  # no scrub

    monkeypatch.delenv("NAMMA_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("SOME_API_KEY", raising=False)


def test_migrate_with_scrub_blanks_values_keeps_keys(store, tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("NAMMA_DISCORD_BOT_TOKEN=dc-secret-abcdef\nPLAIN=1\n",
                        encoding="utf-8")
    monkeypatch.delenv("NAMMA_DISCORD_BOT_TOKEN", raising=False)
    report = sec.migrate_env_file(str(env_file), scrub=True)
    assert report["scrubbed"]
    text = env_file.read_text(encoding="utf-8")
    assert "dc-secret-abcdef" not in text
    assert "NAMMA_DISCORD_BOT_TOKEN=" in text  # the key stays as documentation
    assert "PLAIN=1" in text
    assert store.get("NAMMA_DISCORD_BOT_TOKEN") == "dc-secret-abcdef"
    monkeypatch.delenv("NAMMA_DISCORD_BOT_TOKEN", raising=False)


def test_migrate_missing_file_reports_cleanly(store, tmp_path):
    report = sec.migrate_env_file(str(tmp_path / "nope.env"))
    assert report["migrated"] == [] and "error" in report


# ── redaction ────────────────────────────────────────────────────────────────

def test_redact_masks_env_and_vault_values(store, monkeypatch):
    monkeypatch.setenv("NAMMA_FAKE_TOKEN", "env-secret-XYZ-1234")
    store.set("VAULT_API_KEY", "vault-secret-ABC-5678")
    sec.refresh_redaction()
    out = sec.redact("token is env-secret-XYZ-1234 and key is vault-secret-ABC-5678, ok?")
    assert "env-secret-XYZ-1234" not in out and "***NAMMA_FAKE_TOKEN***" in out
    assert "vault-secret-ABC-5678" not in out and "***VAULT_API_KEY***" in out


def test_redact_ignores_short_and_non_secret_names(store, monkeypatch):
    monkeypatch.setenv("NAMMA_TINY_TOKEN", "abc")          # under the length floor
    monkeypatch.setenv("JUST_A_SETTING", "not-a-secret-but-long")
    sec.refresh_redaction()
    text = "abc and not-a-secret-but-long stay visible"
    assert sec.redact(text) == text


def test_redact_longest_value_first(store, monkeypatch):
    monkeypatch.setenv("SHORT_TOKEN", "secret123")
    monkeypatch.setenv("LONG_TOKEN", "secret123-extended-456")
    sec.refresh_redaction()
    out = sec.redact("value: secret123-extended-456")
    assert out == "value: ***LONG_TOKEN***"


def test_tool_output_is_redacted(store, monkeypatch):
    monkeypatch.setenv("NAMMA_LEAK_TOKEN", "leak-me-please-9999")
    sec.refresh_redaction()
    reg = ToolRegistry()
    reg.register("leak", "leaks", {"type": "object", "properties": {}},
                 lambda a: "the token is leak-me-please-9999")
    result = reg.execute("leak", {})
    assert result.ok
    assert "leak-me-please-9999" not in result.content
    assert "***NAMMA_LEAK_TOKEN***" in result.content


def test_tool_error_is_redacted(store, monkeypatch):
    monkeypatch.setenv("NAMMA_LEAK_TOKEN", "leak-me-please-9999")
    sec.refresh_redaction()

    def boom(args):
        raise RuntimeError("auth failed for leak-me-please-9999")

    reg = ToolRegistry()
    reg.register("boom", "raises", {"type": "object", "properties": {}}, boom)
    result = reg.execute("boom", {})
    assert not result.ok
    assert "leak-me-please-9999" not in result.error
    assert "***NAMMA_LEAK_TOKEN***" in result.error


def test_log_records_are_redacted(store, monkeypatch, caplog):
    monkeypatch.setenv("NAMMA_LOG_LEAK_TOKEN", "log-secret-77777")
    sec.refresh_redaction()
    with caplog.at_level(logging.INFO, logger="namma_agent"):
        logger.info("connecting with token log-secret-77777")
    messages = [r.getMessage() for r in caplog.records]
    assert any("***NAMMA_LOG_LEAK_TOKEN***" in m for m in messages)
    assert not any("log-secret-77777" in m for m in messages)
