"""User-persona authoring: save → list → load → delete (built-ins untouched)."""
from __future__ import annotations

from pathlib import Path

import friday.core.persona as persona


def _use_tmp_user_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(persona, "_USER_PERSONA_DIR", tmp_path / "personas")


def test_default_builtin_listed_with_resolved_name_and_identity(monkeypatch, tmp_path):
    # Isolate the user-persona dir so the real ~/.friday/personas (which may hold a
    # persona that shadows the builtin 'core') can't pollute this assertion.
    _use_tmp_user_dir(monkeypatch, tmp_path)
    rows = persona.list_personas("Heaven")
    core = next(r for r in rows if r["id"] == "core")
    assert core["source"] == "builtin"
    assert core["name"] == "Heaven"  # the {name} placeholder resolves in the label
    assert core["identity_line"] and "{name}" not in core["identity_line"]
    assert "Heaven" in core["identity_line"]  # {name} resolved to the display name


def test_save_list_load_and_delete_user_persona(monkeypatch, tmp_path):
    _use_tmp_user_dir(monkeypatch, tmp_path)

    saved = persona.save_persona({
        "name": "Sage",
        "identity": "You are {name}, a calm stoic mentor who teaches by asking questions.",
        "tone": "calm, measured",
        "dos": "Ask a guiding question first\nKeep it brief",
        "donts": ["Don't lecture"],
    })
    assert saved["id"] == "sage"

    rows = persona.list_personas("Heaven")
    sage = next(r for r in rows if r["id"] == "sage")
    assert sage["source"] == "user" and sage["name"] == "Sage"

    p = persona.load_persona("sage", display_name="Heaven")
    assert p.name == "Heaven"  # display name wins over the YAML name
    assert "calm stoic mentor" in p.identity
    assert p.dos == ["Ask a guiding question first", "Keep it brief"]
    assert "Heaven" in p.system_prompt()  # {name} substituted in the built prompt

    assert persona.delete_user_persona("sage") is True
    assert "sage" not in {r["id"] for r in persona.list_personas("Heaven")}


def test_system_prompt_anchors_to_the_present():
    """The prompt must carry today's real date so the agent doesn't default to its
    training-cutoff year (which made it search for stale "...2025" news)."""
    from datetime import datetime

    p = persona.load_persona("core", display_name="Heaven")
    prompt = p.system_prompt()
    assert "CURRENT DATE & TIME" in prompt
    assert str(datetime.now().year) in prompt  # the actual current year, not the cutoff
    assert "knowledge cutoff" in prompt.lower()


def test_temporal_block_uses_supplied_now():
    from datetime import datetime

    block = persona._temporal_block(datetime(2026, 6, 20, 14, 30))
    assert "2026" in block and "June" in block and "14:30" in block


def test_save_persona_requires_name_and_identity(monkeypatch, tmp_path):
    _use_tmp_user_dir(monkeypatch, tmp_path)
    import pytest
    with pytest.raises(ValueError):
        persona.save_persona({"name": "X", "identity": ""})
