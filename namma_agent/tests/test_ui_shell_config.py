"""Phase 9 W1 — config the redesigned web UI shell reads from /api/config."""
from __future__ import annotations

import pytest

from namma_agent.core.memory import Database
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry
from namma_agent.service import NammaAgentService


class _Provider(Provider):
    name = "scripted"

    def __init__(self):
        super().__init__(model="scripted")

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        return LLMResponse(content="hi")


def _service(conversation: dict):
    cfg = {"persona": "core", "conversation": conversation}
    return NammaAgentService(config=cfg, provider=_Provider(),
                             registry=ToolRegistry(), db=Database(":memory:"))


@pytest.mark.parametrize("configured, expected", [
    ({}, "agent"),
    ({"default_mode": "chat"}, "chat"),
    ({"default_mode": "SETUP"}, "setup"),
    ({"default_mode": "bogus"}, "agent"),
])
def test_info_reports_default_mode(configured, expected):
    assert _service(configured).info()["default_mode"] == expected
