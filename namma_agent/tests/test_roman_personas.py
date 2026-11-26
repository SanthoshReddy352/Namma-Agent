"""Phase 9 W4: the Roman personas (Caesar, Cicero, Augustus, Seneca, Aurelius).

A persona is a manner, not a name: the assistant stays `assistant.name` (here
"Aria"), every identity uses the {name} placeholder, and each persona ships an
original coin portrait that the profile rail shows.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from namma_agent.core import persona
from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.server.api import create_app
from namma_agent.service import NammaAgentService

ROMANS = ["caesar", "cicero", "augustus", "seneca", "aurelius"]
PKG = Path(persona.__file__).resolve().parent.parent
PORTRAITS = PKG / "webui" / "public" / "brand" / "personas"


@pytest.mark.parametrize("pid", ROMANS)
def test_persona_file_uses_name_placeholder_and_ships_a_portrait(pid):
    data = yaml.safe_load((PKG / "personas" / f"{pid}.yaml").read_text(encoding="utf-8"))
    assert data["persona_id"] == pid
    assert "{name}" in data["identity"]
    assert "Namma Agent" not in yaml.safe_dump(data)          # never hard-codes the assistant's name
    assert data["title"] and data["dos"] and data["donts"]
    assert data["portrait"] == f"/brand/personas/{pid}.svg"
    svg = (PORTRAITS / f"{pid}.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and "Original art" in svg


@pytest.mark.parametrize("pid", ROMANS)
def test_prompt_keeps_the_assistant_name(pid):
    p = persona.load_persona(pid, display_name="Aria")
    prompt = p.system_prompt()
    assert prompt.startswith("You are Aria, a personal AI assistant")
    assert "{name}" not in prompt
    assert p.tone and p.dos


def test_rail_lists_the_romans_with_titles_and_portraits():
    rows = {r["id"]: r for r in persona.list_personas("Aria")}
    assert set(ROMANS) <= set(rows)
    assert rows["core"]["name"] == "Aria" and rows["core"]["portrait"] is None
    assert rows["caesar"]["name"] == "Caesar" and rows["caesar"]["title"] == "Dictator"
    assert rows["seneca"]["portrait"] == "/brand/personas/seneca.svg"
    assert all(rows[p]["source"] == "builtin" for p in ROMANS)


def test_portrait_urls_are_restricted_to_bundled_coins():
    assert persona._portrait("/brand/personas/caesar.svg") == "/brand/personas/caesar.svg"
    for bad in ("https://evil.example/x.svg", "/brand/personas/../../secret.svg",
                "javascript:alert(1)", "/brand/personas/caesar.png", "", None):
        assert persona._portrait(bad) is None


class _Provider(Provider):
    name = "scripted"

    def __init__(self):
        super().__init__(model="scripted")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="hi")


def test_switching_to_a_roman_persona_over_the_api(monkeypatch, tmp_path):
    monkeypatch.setenv("NAMMA_USER_CONFIG", str(tmp_path / "user_config.yaml"))
    svc = NammaAgentService(config={"persona": "core", "conversation": {}, "assistant": {"name": "Aria"}},
                            provider=_Provider(), registry=ToolRegistry(), db=Database(":memory:"))
    client = TestClient(create_app(svc))
    listed = client.get("/api/personas").json()
    caesar = next(p for p in listed["personas"] if p["id"] == "caesar")
    assert caesar["portrait"] == "/brand/personas/caesar.svg" and caesar["title"] == "Dictator"
    assert client.post("/api/persona", json={"id": "caesar"}).json() == {"persona": "caesar"}
    assert svc.persona.id == "caesar"
    assert "Gaius Julius Caesar" in svc.persona.system_prompt()
    spec = client.get("/api/personas/caesar").json()["persona"]
    assert spec["portrait"] == "/brand/personas/caesar.svg"
