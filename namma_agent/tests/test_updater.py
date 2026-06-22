"""Update-check + first-run provider configuration."""
from __future__ import annotations

import pytest
import yaml

from namma_agent.core import updater
from namma_agent.core.setup_wizard import configure_provider, run_wizard


# ── version comparison ──────────────────────────────────────────────────────

def test_parse_version_lenient():
    assert updater.parse_version("v2.3.1") == (2, 3, 1)
    assert updater.parse_version("2.3") == (2, 3, 0)
    assert updater.parse_version("release-1.0.0") == (1, 0, 0)
    assert updater.parse_version("") == (0, 0, 0)
    assert updater.parse_version(None) == (0, 0, 0)


def test_check_for_update_available(monkeypatch):
    monkeypatch.setattr(updater, "current_version", lambda: "2.2.0")
    monkeypatch.setattr(updater, "latest_release",
                        lambda *a, **k: {"version": "2.3.0", "html_url": "u", "notes": "n"})
    r = updater.check_for_update()
    assert r["update_available"] is True
    assert r["current"] == "2.2.0" and r["latest"] == "2.3.0"


def test_check_for_update_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "current_version", lambda: "2.3.0")
    monkeypatch.setattr(updater, "latest_release", lambda *a, **k: {"version": "2.3.0"})
    assert updater.check_for_update()["update_available"] is False


def test_check_for_update_offline(monkeypatch):
    monkeypatch.setattr(updater, "latest_release", lambda *a, **k: None)
    r = updater.check_for_update()
    assert r["update_available"] is False
    assert r["latest"] is None and r["error"]


# ── first-run provider configuration ────────────────────────────────────────

def _cfg(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("provider:\n  type: anthropic\n", encoding="utf-8")
    return str(p), str(tmp_path / ".env")


def test_configure_cloud_provider_writes_overlay_and_env(tmp_path):
    cfg_path, env_path = _cfg(tmp_path)
    prov = configure_provider("openai", model="gpt-4o", api_key="sk-test",
                              config_path=cfg_path, env_path=env_path)
    assert prov["type"] == "openai"
    assert prov["model"] == "gpt-4o"
    assert prov["api_key_env"] == "OPENAI_API_KEY"

    overlay = yaml.safe_load((tmp_path / "config.local.yaml").read_text())
    assert overlay["provider"]["type"] == "openai"
    # Also registered in the switchable UI lists so it shows in the model picker.
    assert any(p["id"] == "openai" for p in overlay["providers"])
    assert any(m["model"] == "gpt-4o" for m in overlay["models"])
    assert "OPENAI_API_KEY=sk-test" in (tmp_path / ".env").read_text()


def test_configure_local_provider_needs_no_key(tmp_path):
    cfg_path, env_path = _cfg(tmp_path)
    prov = configure_provider("ollama", config_path=cfg_path, env_path=env_path)
    assert prov["type"] == "ollama"
    assert prov["base_url"].startswith("http")
    assert "api_key_env" not in prov
    assert not (tmp_path / ".env").exists()  # no key written for a local provider


def test_configure_unknown_provider_raises(tmp_path):
    with pytest.raises(ValueError):
        configure_provider("bogus", config_path=str(tmp_path / "c.yaml"))


def test_run_wizard_skip_returns_none(tmp_path, monkeypatch):
    # Choosing "0" skips configuration without touching anything.
    out = run_wizard(input_fn=lambda _q: "0", print_fn=lambda *a, **k: None)
    assert out is None


# ── first-run onboarding -> DB ───────────────────────────────────────────────

def test_save_onboarding_writes_to_db(tmp_path):
    from namma_agent.core.memory import Database
    from namma_agent.core.setup_wizard import save_onboarding

    db_path = str(tmp_path / "namma.db")
    saved = save_onboarding(
        {"name": "Asha", "occupation": "student", "date_of_birth": "2000-01-01", "blank": ""},
        db_path=db_path)
    assert saved == {"name": "Asha", "occupation": "student", "date_of_birth": "2000-01-01"}

    db = Database(db_path)
    assert db.get_fact("name") == "Asha"           # identity fact (same as in-chat onboarding)
    assert db.get_fact("occupation") == "student"  # onboarding fact
    assert db.get_fact("blank") is None            # empty answers are skipped
