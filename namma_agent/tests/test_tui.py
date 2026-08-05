"""Offline tests for the terminal UI: theme, art, renderers, chat logic, CLI.

No terminal, no provider, no network. The prompt_toolkit ``Application`` itself
isn't constructed here — the testable seam is :class:`TuiChat`, which holds all
the chat behavior, with the widgets kept to layout in ``app.TerminalUI``.
"""
from __future__ import annotations

import pytest

from namma_agent.tui import art, banner, render, theme
from namma_agent.tui import app as tui_app
from namma_agent.tui import cli as tui_cli


@pytest.fixture(autouse=True)
def _clean_theme(monkeypatch):
    """Every test starts from a known, fully-colored, unicode-capable terminal."""
    monkeypatch.setenv("NAMMA_TUI_COLOR", "truecolor")
    monkeypatch.delenv("NAMMA_TUI_ASCII", raising=False)
    monkeypatch.delenv("NAMMA_TUI_SKIN", raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    theme.reset_caches()
    monkeypatch.setattr(theme, "supports_unicode", lambda: True)
    yield
    theme.reset_caches()


# ── theme ──────────────────────────────────────────────────────────────

def test_truecolor_passes_hex_through():
    assert theme.downgrade("#FFD700") == "#FFD700"


def test_no_color_yields_empty_and_styled_stays_plain(monkeypatch):
    monkeypatch.setenv("NAMMA_TUI_COLOR", "none")
    theme.reset_caches()
    assert theme.color("banner_title") == ""
    # The important part: styled() must NOT produce "[]text[/]", which rich
    # rejects with MarkupError — that bug silently swallows whole lines.
    assert theme.styled("hello", "banner_title") == "hello"


def test_styled_is_valid_markup_at_every_color_depth(monkeypatch):
    from rich.console import Console

    for depth in ("truecolor", "256", "16", "none"):
        monkeypatch.setenv("NAMMA_TUI_COLOR", depth)
        theme.reset_caches()
        console = Console(file=open_devnull(), force_terminal=True)
        # Would raise MarkupError on a malformed tag.
        console.print(theme.styled("text", "banner_title", bold=True))
        console.print(render.tool_line("run_shell", {"command": "ls"}))
        console.print(render.tool_result_line("run_shell", False, "boom"))


def open_devnull():
    import io
    return io.StringIO()


def test_256_and_16_downgrade_shapes(monkeypatch):
    monkeypatch.setenv("NAMMA_TUI_COLOR", "256")
    theme.reset_caches()
    assert theme.downgrade("#FFD700").startswith("color(")
    monkeypatch.setenv("NAMMA_TUI_COLOR", "16")
    theme.reset_caches()
    assert theme.downgrade("#FFD700").startswith("ansi")


def test_unknown_skin_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NAMMA_TUI_SKIN", "does-not-exist")
    theme.reset_caches()
    assert theme.get_active_skin().name == "namma"


def test_custom_skin_overrides_only_given_keys(tmp_path, monkeypatch):
    monkeypatch.setattr(theme, "skins_dir", lambda: tmp_path)
    (tmp_path / "midnight.yaml").write_text(
        "colors:\n  banner_title: '#123456'\n", encoding="utf-8")
    skin = theme.load_skin("midnight")
    assert skin.get_color("banner_title") == "#123456"
    # Untouched keys keep the default palette.
    assert skin.get_color("banner_border") == theme.DEFAULT_COLORS["banner_border"]


def test_ascii_mode_drops_glyphs(monkeypatch):
    monkeypatch.setattr(theme, "supports_unicode", lambda: False)
    assert theme.get_active_skin().faces("waiting") == []
    assert art.hero() == ""
    assert art.wordmark() == ""
    assert render.tool_emoji("run_shell") == "*"
    assert theme.glyph("vbar") == "|"
    assert theme.glyph("ellipsis") == "..."


def test_ascii_mode_output_is_encodable_on_a_legacy_console(monkeypatch):
    """Everything the TUI prints must survive a cp1252 Windows console.

    A stray hardcoded box-drawing character raises UnicodeEncodeError there and
    takes the whole session down, so this asserts on the bytes, not the look.
    """
    monkeypatch.setattr(theme, "supports_unicode", lambda: False)

    produced = [
        render.tool_line("run_shell", {"command": "x" * 200}),
        render.tool_result_line("run_shell", True, "done", 1.0),
        render.tool_result_line("run_shell", False, "bad"),
        render.truncate("y" * 200, 20),
        render.shorten_path("/a/b/c/d/e/f/g.py", 12),
        *render.unified_diff("a\nb\n", "a\nB\n", "x.py"),
    ]
    spinner = render.Spinner()
    spinner.start()
    produced.append(spinner.text(now=spinner.started_at + 2))

    for text in produced:
        text.encode("cp1252")  # raises UnicodeEncodeError if a glyph leaked through


def test_ascii_mode_banner_is_encodable(monkeypatch):
    from rich.console import Console

    monkeypatch.setattr(theme, "supports_unicode", lambda: False)
    buffer = open_devnull()
    console = Console(file=buffer, force_terminal=False, width=100)
    console.print(banner.build(_StubService(), session_id="abc", width=100))
    buffer.getvalue().encode("cp1252")


# ── art ────────────────────────────────────────────────────────────────

def test_hero_rows_are_equal_width_and_centered():
    rows = art.hero_rows()
    widths = {len(plain) for plain, _ in rows}
    assert widths == {art._HERO_WIDTH}, "rows must be padded to one width"


def test_wordmark_follows_the_assistant_name():
    """The name is configurable, so the wordmark must be rendered, not baked in."""
    assert "NAMMA" not in art.wordmark(name="Ada")
    rows = art._wordmark_rows("AB")
    assert len(rows) == art._GLYPH_ROWS
    assert all(len(row) == len(rows[0]) for row in rows)


def test_wordmark_ignores_unrenderable_characters():
    assert art._wordmark_rows("!!!") == []


# ── render ─────────────────────────────────────────────────────────────

def test_tool_preview_picks_the_informative_argument():
    assert render.tool_preview("run_shell", {"command": "git status"}) == "git status"
    assert render.tool_preview("web_search", {"query": "a b"}) == "a b"


def test_tool_preview_falls_back_and_collapses_whitespace():
    assert render.tool_preview("odd_tool", {"weird": "v"}) == "weird=v"
    assert render.tool_preview("run_shell", {"command": "a\n  b"}) == "a b"
    assert render.tool_preview("x", {}) == ""


def test_tool_preview_truncates():
    out = render.tool_preview("run_shell", {"command": "x" * 200}, max_len=20)
    assert len(out) == 20 and out.endswith("…")


def test_tool_line_escapes_markup_in_arguments():
    """A tool argument containing brackets must not be parsed as rich markup."""
    line = render.tool_line("run_shell", {"command": "ls [a-z]"})
    assert "\\[a-z]" in line


def test_tool_emoji_falls_back_by_prefix_then_generic():
    assert render.tool_emoji("gmail_archive") == "📧"
    assert render.tool_emoji("totally_unknown") == "⚡"


def test_format_context_length():
    assert render.format_context_length(200_000) == "200K"
    assert render.format_context_length(1_048_576) == "1M"
    assert render.format_context_length(None) == ""


def test_unified_diff_marks_changes_and_is_empty_when_equal():
    assert render.unified_diff("a\n", "a\n") == []
    lines = render.unified_diff("a\nb\n", "a\nB\n", "x.py")
    assert any("-b" in line for line in lines)
    assert any("+B" in line for line in lines)
    assert render.diff_stat("a\nb\n", "a\nB\n") == (1, 1)


def test_spinner_reports_elapsed_and_stops():
    spinner = render.Spinner(message="working")
    spinner.start("working")
    text = spinner.text(now=spinner.started_at + 3)
    assert "working" in text and "(3s)" in text
    spinner.stop()
    assert spinner.text() == "" and not spinner.running


def test_columns_never_exceed_the_width():
    rows = render.columns([f"tool_{i}" for i in range(20)], width=40)
    assert rows and all(len(row) <= 40 for row in rows)


def test_shorten_path_elides_the_middle():
    out = render.shorten_path("/a/b/c/d/e/f/g/h.py", max_len=16)
    assert "…" in out and len(out) <= 20


# ── banner ─────────────────────────────────────────────────────────────

class _StubProvider:
    model = "anthropic/claude-sonnet-4"
    context_length = 200_000


class _StubRegistry:
    def names(self):
        return ["run_shell", "read_file", "web_search", "gmail_list"]


class _StubSkills:
    def all(self):
        return []


class _StubService:
    config: dict = {}
    provider = _StubProvider()
    registry = _StubRegistry()
    skills = _StubSkills()
    mcp = None
    auto_approve = False
    db = None

    def configured_models(self):
        return []


def test_group_tools_buckets_by_purpose():
    grouped = banner.group_tools(["run_shell", "read_file", "gmail_list", "zzz_odd"])
    assert grouped["system"] == ["run_shell"]
    assert grouped["files"] == ["read_file"]
    assert grouped["google"] == ["gmail_list"]
    assert grouped["other"] == ["zzz_odd"]


def test_banner_renders_at_wide_and_narrow_widths():
    from rich.console import Console

    for width in (120, 90, 50):
        console = Console(file=open_devnull(), force_terminal=True, width=width)
        console.print(banner.build(_StubService(), session_id="abc123", width=width))


def test_banner_survives_a_broken_service():
    """A banner must never be what stops a session from starting."""
    class Broken:
        config: dict = {}

        def __getattr__(self, name):
            raise RuntimeError("nope")

    from rich.console import Console
    banner.print_banner(Broken(), console=Console(file=open_devnull()))


# ── chat behavior ──────────────────────────────────────────────────────

class _Result:
    def __init__(self, content="ok", session_id="s1"):
        self.content = content
        self.session_id = session_id
        self.usage = {"input_tokens": 3, "output_tokens": 5}


class _ChatService(_StubService):
    def __init__(self, **kwargs):
        self.calls: list[dict] = []
        self.kwargs = kwargs
        self.db = _StubDB()

    def run_turn(self, text, sink=None, on_token=None, approval=None, **kw):
        self.calls.append({"text": text, **kw})
        if self.kwargs.get("emit_tool") and sink:
            sink("tool_started", {"tool": "run_shell", "args": {"command": "ls"}})
            sink("tool_finished", {"tool": "run_shell", "ok": True, "summary": "done"})
        if self.kwargs.get("stream") and on_token:
            on_token("hel")
            on_token("lo")
        if self.kwargs.get("ask_approval") and approval:
            self.approved = approval("delete_path", {"path": "/tmp/x"})
        return _Result()


class _StubDB:
    def list_sessions(self, limit=50, **kw):
        return [
            {"id": "aaaa1111", "title": "First chat", "updated_at": "2026-07-01"},
            {"id": "bbbb2222", "title": "Second chat", "updated_at": "2026-07-02"},
        ]

    def rename_session(self, session_id, title):
        self.renamed = (session_id, title)
        return True


def make_chat(**kwargs):
    """A TuiChat whose transcript is captured instead of printed."""
    chat = tui_app.TuiChat(_ChatService(**kwargs), name="Namma Agent")
    chat.lines: list[str] = []
    chat.write = lambda markup="", **kw: chat.lines.append(markup)
    return chat


def test_a_plain_message_runs_a_turn_and_keeps_the_session():
    chat = make_chat()
    chat.handle_text("hello")
    assert chat.service.calls[0]["text"] == "hello"
    assert chat._session_id == "s1"
    assert chat._turns == 1


def test_streamed_output_is_not_printed_twice():
    """Tokens already on screen must not be reprinted from the final result."""
    chat = make_chat(stream=True)
    written: list[str] = []
    chat._console.file.write = written.append
    chat._console.file.flush = lambda: None
    chat.handle_text("hi")
    assert "".join(written) == "hello"
    assert not any("ok" == line for line in chat.lines), "final content re-printed"


def test_unstreamed_replies_are_printed():
    chat = make_chat(stream=False)
    chat.handle_text("hi")
    assert any("ok" in line for line in chat.lines)


def test_tool_events_reach_the_transcript():
    chat = make_chat(emit_tool=True)
    chat.handle_text("do it")
    transcript = "\n".join(chat.lines)
    assert "run_shell" in transcript and "ls" in transcript


def test_shell_bang_is_routed_through_the_agent():
    chat = make_chat()
    chat.handle_text("!git status")
    assert "run_shell" in chat.service.calls[0]["text"]
    assert "git status" in chat.service.calls[0]["text"]


def test_mode_and_new_commands_are_handled_locally():
    chat = make_chat()
    chat.handle_text("/mode chat")
    assert chat._mode == "chat"
    chat._session_id = "s1"
    chat.handle_text("/new")
    assert chat._session_id is None
    assert not chat.service.calls, "a /command must not run a turn"


def test_quit_command_raises_for_the_ui_to_catch():
    chat = make_chat()
    with pytest.raises(tui_app._Quit):
        chat.handle_text("/quit")


def test_resume_accepts_an_id_prefix_and_a_title():
    chat = make_chat()
    chat.handle_text("/resume aaaa")
    assert chat._session_id == "aaaa1111"
    chat.handle_text("/resume Second")
    assert chat._session_id == "bbbb2222"


def test_resume_reports_an_unknown_session():
    chat = make_chat()
    chat.handle_text("/resume nope")
    assert any("no session" in line for line in chat.lines)
    assert chat._session_id is None


def test_approval_denies_when_the_answer_is_not_yes():
    chat = make_chat(ask_approval=True)
    # The approval prompt blocks the turn thread; answer it from this one.
    import threading
    thread = threading.Thread(target=chat.handle_text, args=("delete it",))
    thread.start()
    _wait_for(lambda: chat._approval_event is not None)
    chat.handle_text("n")
    thread.join(timeout=5)
    assert chat.service.approved is False


def test_approval_runs_the_tool_on_yes():
    chat = make_chat(ask_approval=True)
    import threading
    thread = threading.Thread(target=chat.handle_text, args=("delete it",))
    thread.start()
    _wait_for(lambda: chat._approval_event is not None)
    chat.handle_text("y")
    thread.join(timeout=5)
    assert chat.service.approved is True


def test_auto_approve_never_prompts():
    chat = make_chat(ask_approval=True)
    chat.auto_approve = True
    chat.handle_text("delete it")
    assert chat.service.approved is True
    assert chat._approval_event is None


def _wait_for(predicate, timeout=5.0):
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition never became true")


# ── CLI ────────────────────────────────────────────────────────────────

def test_parser_exposes_the_documented_surface():
    parser = tui_cli.build_parser()
    args = parser.parse_args([])
    assert args.command is None and args.mode == "agent"

    for argv, attr, expected in (
        (["-z", "hi"], "oneshot", "hi"),
        (["--yolo"], "yolo", True),
        (["-m", "fast"], "model", "fast"),
        (["--mode", "chat"], "mode", "chat"),
        (["-r", "abc"], "resume", "abc"),
        (["-c"], "continue_last", True),
        (["-c", "name"], "continue_last", "name"),
        (["--skin", "midnight"], "skin", "midnight"),
    ):
        assert getattr(parser.parse_args(argv), attr) == expected


@pytest.mark.parametrize("command", [
    "chat", "gateway", "serve", "sessions", "model", "config", "skills",
    "tools", "mcp", "memory", "status", "doctor", "logs", "setup", "version",
])
def test_every_subcommand_parses_and_has_a_handler(command):
    args = tui_cli.build_parser().parse_args([command])
    assert callable(getattr(args, "func", None)), f"{command} has no handler"


def test_display_flags_become_environment_settings(monkeypatch):
    import os

    # setenv first so monkeypatch owns (and restores) these keys — _apply_display_flags
    # writes to os.environ directly, and leaking NO_COLOR would silently recolor
    # every test that runs after this one.
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setenv("NAMMA_TUI_ASCII", "")
    monkeypatch.setenv("NAMMA_TUI_SKIN", "")

    args = tui_cli.build_parser().parse_args(["--no-color", "--ascii", "--skin", "x"])
    tui_cli._apply_display_flags(args)
    assert os.environ["NO_COLOR"] == "1"
    assert os.environ["NAMMA_TUI_ASCII"] == "1"
    assert os.environ["NAMMA_TUI_SKIN"] == "x"


def test_interface_choice_prefers_plain_without_a_tty(monkeypatch):
    parser = tui_cli.build_parser()
    monkeypatch.setattr(tui_cli, "_display_deps_available", lambda: True)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    assert tui_cli._interface(parser.parse_args([])) == "plain"
    # An explicit --tui overrides the check; --cli always wins.
    assert tui_cli._interface(parser.parse_args(["--tui"])) == "tui"
    assert tui_cli._interface(parser.parse_args(["--cli", "--tui"])) == "plain"


def test_interface_falls_back_when_the_display_deps_are_missing(monkeypatch):
    monkeypatch.setattr(tui_cli, "_display_deps_available", lambda: False)
    args = tui_cli.build_parser().parse_args([])
    assert tui_cli._interface(args) == "plain"


def test_config_set_writes_the_local_overlay_and_coerces(tmp_path, monkeypatch):
    overlay = tmp_path / "config.local.yaml"
    monkeypatch.setattr("namma_agent.config._config_path", lambda: tmp_path / "config.yaml")
    monkeypatch.setattr("namma_agent.config._local_overrides_path", lambda _p: overlay)

    tui_cli._config_set("assistant.name", "Ada")
    tui_cli._config_set("tui.animate", "true")
    tui_cli._config_set("agent.max_turns", "12")

    import yaml
    data = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    assert data["assistant"]["name"] == "Ada"
    assert data["tui"]["animate"] is True
    assert data["agent"]["max_turns"] == 12


def test_dig_reads_dotted_keys():
    config = {"a": {"b": {"c": 1}}}
    assert tui_cli._dig(config, "a.b.c") == 1
    assert tui_cli._dig(config, "a.b.missing") is None
    assert tui_cli._dig(config, "nope.at.all") is None


def test_build_service_suppresses_the_gateway_by_default(monkeypatch):
    """A terminal session owns the agent; Telegram answering at the same time
    would interleave turns. `namma gateway` is the way to run messaging."""
    captured = {}

    class FakeService:
        def __init__(self, config=None):
            captured["config"] = config
            self.auto_approve = False

    monkeypatch.setattr("namma_agent.service.NammaAgentService", FakeService)
    monkeypatch.setattr("namma_agent.config.load_config",
                        lambda: {"comms": {"inbound_enabled": True}})

    args = tui_cli.build_parser().parse_args([])
    tui_cli.build_service(args)
    assert captured["config"]["comms"]["inbound_enabled"] is False

    tui_cli.build_service(args, with_gateway=True)
    assert captured["config"]["comms"]["inbound_enabled"] is True


def test_yolo_sets_auto_approve(monkeypatch):
    class FakeService:
        def __init__(self, config=None):
            self.auto_approve = False

    monkeypatch.setattr("namma_agent.service.NammaAgentService", FakeService)
    monkeypatch.setattr("namma_agent.config.load_config", lambda: {})
    args = tui_cli.build_parser().parse_args(["--yolo"])
    assert tui_cli.build_service(args).auto_approve is True


# ── entry point routing ────────────────────────────────────────────────

@pytest.mark.parametrize("argv,expected", [
    ([], None),                                   # bare → the desktop app
    (["--server"], None),                         # unchanged legacy path
    (["--server", "--tui"], None),                # --server still wins
    (["--chat"], []),                             # legacy alias → default action
    (["--tui"], ["--tui"]),
    (["gateway"], ["gateway"]),
    (["sessions", "list"], ["sessions", "list"]),
    (["-z", "hi"], ["-z", "hi"]),
    (["--chat", "--yolo"], ["--yolo"]),           # --chat dropped, rest kept
])
def test_module_entry_routes_to_the_cli(argv, expected):
    """The installers call --server/--setup/--version; those must not change."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "__main__.py"
    source = path.read_text(encoding="utf-8")
    namespace: dict = {}
    # Execute only the routing helper, not the module (which would launch the app).
    start = source.index("_CLI_SUBCOMMANDS = {")
    end = source.index("_argv = _cli_argv(")
    exec(source[start:end], namespace)  # noqa: S102 - fixed, in-repo source
    assert namespace["_cli_argv"](argv) == expected
