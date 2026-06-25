from __future__ import annotations

from unittest.mock import MagicMock
from namma_agent.core.providers.openai_compat import OpenAICompatProvider
from namma_agent.core.tools import ToolRegistry


def test_tool_registry_json_error():
    # Verify that the tool registry fails immediately with a helpful message
    # when "_json_error" is in the tool call arguments.
    registry = ToolRegistry()

    # Register a dummy tool
    def dummy_handler(args):
        return "success"

    registry.register("dummy", "description", {}, dummy_handler)

    # execute with normal args
    res = registry.execute("dummy", {"a": 1})
    assert res.ok
    assert res.content == "success"

    # execute with json error args
    error_args = {
        "_json_error": "Expecting value: line 1 column 1 (char 0)",
        "_raw_args": "{invalid_json"
    }
    res = registry.execute("dummy", error_args)
    assert not res.ok
    assert "Failed to parse tool call arguments as valid JSON" in res.error
    assert "{invalid_json" in res.error
    assert "Expecting value" in res.error


def test_openai_compat_json_error_parsing():
    provider = OpenAICompatProvider(model="m", api_key_env="DUMMY_KEY")
    provider._api_key = "dummy"

    # Mocking choices for non-streaming response
    mock_choice = MagicMock()
    mock_choice.finish_reason = "stop"
    mock_choice.message.content = ""

    mock_tc = MagicMock()
    mock_tc.id = "call_1"
    mock_tc.function.name = "dummy_tool"
    mock_tc.function.arguments = "{invalid_json"  # triggers JSONDecodeError

    mock_choice.message.tool_calls = [mock_tc]

    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = None

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = mock_resp

    provider._client = lambda: mock_client

    resp = provider.generate([{"role": "user", "content": "hi"}], stream=False)
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.name == "dummy_tool"
    assert "_json_error" in tc.args
    assert tc.args["_raw_args"] == "{invalid_json"


def test_openai_compat_json_error_parsing_stream():
    provider = OpenAICompatProvider(model="m", api_key_env="DUMMY_KEY")
    provider._api_key = "dummy"

    # Mock stream chunks
    mock_chunk1 = MagicMock()
    mock_chunk1.choices = []
    mock_chunk1.usage = None

    mock_tcd_start = MagicMock()
    mock_tcd_start.index = 0
    mock_tcd_start.id = "call_1"
    mock_tcd_start.function.name = "dummy_tool"
    mock_tcd_start.function.arguments = "{"

    mock_chunk2 = MagicMock()
    mock_chunk2.usage = None
    mock_choice2 = MagicMock()
    mock_choice2.delta.content = None
    mock_choice2.delta.tool_calls = [mock_tcd_start]
    mock_choice2.finish_reason = None
    mock_chunk2.choices = [mock_choice2]

    mock_tcd_end = MagicMock()
    mock_tcd_end.index = 0
    mock_tcd_end.id = None
    mock_tcd_end.function.name = None
    mock_tcd_end.function.arguments = "invalid_json"

    mock_chunk3 = MagicMock()
    mock_chunk3.usage = None
    mock_choice3 = MagicMock()
    mock_choice3.delta.content = None
    mock_choice3.delta.tool_calls = [mock_tcd_end]
    mock_choice3.finish_reason = "stop"
    mock_chunk3.choices = [mock_choice3]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = [mock_chunk1, mock_chunk2, mock_chunk3]

    provider._client = lambda: mock_client

    resp = provider.generate([{"role": "user", "content": "hi"}], stream=True)
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert tc.name == "dummy_tool"
    assert "_json_error" in tc.args
    assert tc.args["_raw_args"] == "{invalid_json"
