"""Phase E backend foundation — modes, cancel, memory cleanup, config/env write,
markitdown, self-knowledge, self-authoring, gws graceful-degrade."""
from __future__ import annotations


from namma_agent.core.agent import Agent
from namma_agent.core.memory import Database
from namma_agent.core.persona import load_persona
from namma_agent.core.providers.base import LLMResponse, Provider
from namma_agent.core.tools import ToolRegistry, ToolResult


class _RecordingProvider(Provider):
    name = "rec"

    def __init__(self, responses):
        super().__init__(model="rec")
        self._responses = list(responses)
        self.tools_seen = []

    def is_available(self):
        return True

    def generate(self, messages, tools=None, stream=False, on_token=None, on_thinking=None):
        self.tools_seen.append(tools)
        return self._responses.pop(0)


def _tool_registry():
    reg = ToolRegistry()
    reg.register("ping", "ping", {"type": "object", "properties": {}},
                 lambda a: ToolResult(ok=True, content="pong"))
    return reg


# ── chat vs agent mode ───────────────────────────────────────────────────────

def test_chat_mode_passes_no_tools():
    prov = _RecordingProvider([LLMResponse(content="hi")])
    agent = Agent(prov, _tool_registry(), Database(":memory:"), load_persona())
    agent.process_turn("hello", mode="chat")
    assert prov.tools_seen[0] == []  # chat mode → no tools offered


def test_agent_mode_passes_tools():
    prov = _RecordingProvider([LLMResponse(content="hi")])
    agent = Agent(prov, _tool_registry(), Database(":memory:"), load_persona())
    agent.process_turn("hello", mode="agent")
    assert prov.tools_seen[0] and any(t["name"] == "ping" for t in prov.tools_seen[0])


def test_cancellation_stops_turn():
    prov = _RecordingProvider([LLMResponse(content="should not be used")])
    agent = Agent(prov, _tool_registry(), Database(":memory:"), load_persona())
    result = agent.process_turn("hello", should_cancel=lambda: True)
    assert result.content == "Stopped."
    assert prov.tools_seen == []  # provider never called


# ── memory cleanup ───────────────────────────────────────────────────────────

def test_db_clear_methods():
    db = Database(":memory:")
    db.save_fact("k", "v")
    sid = db.create_session()
    db.add_turn(sid, "user", "hi")
    assert db.clear_facts() == 1
    assert db.all_facts() == []
    assert db.clear_conversations() == 1
    assert db.search_turns("hi") == []


def test_clear_memory_tool():
    from namma_agent.core.builtins import register_memory_tools
    from namma_agent.core.memory_notes import MemoryNotes
    import tempfile
    db = Database(":memory:")
    db.save_fact("k", "v")
    notes = MemoryNotes(tempfile.mkdtemp())
    notes.append_note("remember this")
    reg = ToolRegistry()
    register_memory_tools(reg, db, notes=notes)
    out = reg.execute("clear_memory", {"scope": "all"})
    assert out.ok
    assert db.all_facts() == []
    assert notes.block() == ""


# ── config + env write ───────────────────────────────────────────────────────

def test_update_config_and_env(tmp_path):
    from namma_agent import config as cfg
    base = tmp_path / "config.yaml"
    base.write_text("provider:\n  active: anthropic\n", encoding="utf-8")
    merged = cfg.update_config({"provider": {"model": "claude-x"}, "logging": {"level": "debug"}},
                               path=str(base))
    assert merged["provider"]["active"] == "anthropic"   # base preserved
    assert merged["provider"]["model"] == "claude-x"     # override applied
    assert (tmp_path / "config.local.yaml").exists()     # base file untouched

    env = tmp_path / ".env"
    written = cfg.set_env_values({"OPENAI_API_KEY": "sk-test"}, path=str(env))
    assert "OPENAI_API_KEY" in written
    assert "OPENAI_API_KEY=sk-test" in env.read_text()


# ── markitdown document extraction ───────────────────────────────────────────

def test_read_document_markitdown_text(tmp_path):
    from namma_agent.tools.documents import register
    reg = ToolRegistry()
    register(reg)
    f = tmp_path / "note.md"
    f.write_text("# Title\n\nHello world.")
    out = reg.execute("read_document", {"path": str(f)})
    assert out.ok and "Hello world" in out.content


# ── self-knowledge ───────────────────────────────────────────────────────────

def test_about_namma_tool():
    from namma_agent.tools.selfdoc import register
    reg = ToolRegistry()
    register(reg)
    out = reg.execute("about_namma", {"topic": "provider"})
    assert out.ok and "provider" in out.content.lower()


# ── self-authoring ───────────────────────────────────────────────────────────

def test_create_tool_authoring(tmp_path, monkeypatch):
    import namma_agent.tools.authoring as authoring
    monkeypatch.setattr(authoring, "USER_TOOLS_DIR", tmp_path / "user_tools")
    reg = ToolRegistry()
    authoring.register(reg)
    out = reg.execute("create_tool", {
        "name": "shout",
        "description": "uppercase text",
        "code": "def run(args):\n    return args.get('text','').upper()",
        "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
    })
    assert out.ok
    assert "shout" in reg.names()
    assert reg.execute("shout", {"text": "hi"}).content == "HI"


# ── gws graceful degrade ─────────────────────────────────────────────────────

def test_gws_without_cli(monkeypatch):
    import namma_agent.tools.gws as gws
    monkeypatch.setattr(gws, "_gws_path", lambda: None)
    reg = ToolRegistry()
    gws.register(reg)
    assert {"gmail_list", "gmail_send", "calendar_agenda", "calendar_create_event"} <= set(reg.names())
    out = reg.execute("gmail_list", {})
    assert not out.ok and "gws" in out.error.lower()


# ── formatting rules in prompt ───────────────────────────────────────────────

def test_formatting_rules_in_prompt():
    sp = load_persona().system_prompt()
    assert "FORMATTING" in sp
    assert "never use markdown headings" in sp.lower() or "headings (#)" in sp
