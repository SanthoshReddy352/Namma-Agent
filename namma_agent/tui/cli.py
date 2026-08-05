"""The ``namma`` command surface.

Shaped after Hermes Agent's CLI — the same flag names and subcommand layout, so
muscle memory transfers — but every command is wired to a real Namma feature.
Commands that exist in Hermes only because of Hermes-specific infrastructure
(its account/billing portal, the codex runtime switch, ACP pairing) are not
stubbed here; a command that can't do anything is worse than no command.

Layout::

    namma                     interactive TUI
    namma -z "prompt"         one-shot: print the answer, nothing else
    namma -c / --resume ID    continue the last session / a specific one
    namma gateway             messaging-only gateway (no terminal chat)
    namma serve               the web UI + API
    namma sessions list|browse|resume|rename
    namma model list|set      config get|set|path|edit
    namma skills / tools / mcp / memory / status / logs / doctor / setup

Every subcommand handler takes the parsed args and returns a process exit code.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Optional

_EPILOGUE = """
Examples:
  namma                          Start the interactive terminal UI
  namma -z "what's my agenda"    One-shot: print only the answer
  namma -c                       Resume the most recent session
  namma --resume a1b2c3d4        Resume a specific session
  namma -m fast "..."            Pick a configured model profile
  namma --yolo                   Skip approval prompts (destructive tools run)
  namma gateway                  Run the messaging gateway only
  namma serve                    Run the web UI on http://127.0.0.1:8000
  namma sessions list            List recent sessions
  namma sessions rename ID TITLE Rename a session
  namma logs -f                  Follow the log file
  namma config set assistant.name Ada
  namma skills list              Show skills and whether they're enabled

Run `namma <command> --help` for a command's own options.
"""


# ── Parser ─────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    """The full ``namma`` parser. Kept importable so tests can introspect it."""
    parser = argparse.ArgumentParser(
        prog="namma",
        description="Namma Agent — a personal AI assistant in your terminal",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOGUE,
    )

    # -- top-level flags (apply to the default chat/TUI action) ------------
    parser.add_argument("-V", "--version", action="store_true",
                        help="Show the version and exit")
    parser.add_argument("-z", "--oneshot", metavar="PROMPT", default=None,
                        help="Send one prompt and print ONLY the answer — no banner, "
                             "no chrome, no tool lines. For scripts and pipes.")
    parser.add_argument("-m", "--model", default=None, metavar="ID",
                        help="Use a configured model profile for this run "
                             "(see `namma model list`)")
    parser.add_argument("--mode", choices=("agent", "chat"), default="agent",
                        help="agent runs tools; chat only talks (default: agent)")
    parser.add_argument("-r", "--resume", metavar="SESSION", default=None,
                        help="Resume a session by id, id prefix, or title")
    parser.add_argument("-c", "--continue", dest="continue_last", nargs="?",
                        const=True, default=None, metavar="SESSION",
                        help="Resume the most recent session, or one matching SESSION")
    parser.add_argument("--yolo", action="store_true",
                        help="Bypass every approval prompt — destructive tools run "
                             "unasked. Use at your own risk.")
    parser.add_argument("--skin", default=None, metavar="NAME",
                        help="TUI color skin (see `namma config path` for where "
                             "custom skins live)")
    parser.add_argument("--tui", action="store_true",
                        help="Force the full terminal UI even when stdout isn't a TTY")
    parser.add_argument("--cli", action="store_true",
                        help="Force the plain REPL instead of the terminal UI")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable color (same as NO_COLOR=1)")
    parser.add_argument("--ascii", action="store_true",
                        help="ASCII-only output — no box art, emoji, or braille")
    parser.add_argument("--gateway", dest="with_gateway", action="store_true",
                        help="Also run the messaging gateway alongside the terminal "
                             "session (off by default so the terminal owns the agent)")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # -- chat (the default action, named for discoverability) --------------
    chat = sub.add_parser("chat", help="Interactive terminal chat (the default)")
    chat.add_argument("-q", "--query", default=None,
                      help="Run a single query and exit, with normal output")
    chat.set_defaults(func=cmd_chat)

    # -- gateway -----------------------------------------------------------
    gw = sub.add_parser("gateway", help="Run the messaging gateway only "
                                        "(Telegram/Slack/Discord/WhatsApp/Signal)")
    gw_sub = gw.add_subparsers(dest="action", metavar="<action>")
    gw_sub.add_parser("run", help="Run in the foreground until Ctrl+C (default)")
    gw_sub.add_parser("status", help="Show which channels are configured and running")
    gw.set_defaults(func=cmd_gateway)

    # -- serve -------------------------------------------------------------
    serve = sub.add_parser("serve", help="Run the web UI and API")
    serve.add_argument("--host", default=None, help="Bind address")
    serve.add_argument("--port", type=int, default=None, help="Port")
    serve.set_defaults(func=cmd_serve)

    # -- sessions ----------------------------------------------------------
    sessions = sub.add_parser("sessions", help="List, browse, resume and rename sessions")
    s_sub = sessions.add_subparsers(dest="action", metavar="<action>")
    s_list = s_sub.add_parser("list", help="List recent sessions")
    s_list.add_argument("-n", "--limit", type=int, default=20)
    s_sub.add_parser("browse", help="Pick a session interactively, then resume it")
    s_resume = s_sub.add_parser("resume", help="Resume a session by id or title")
    s_resume.add_argument("session")
    s_rename = s_sub.add_parser("rename", help="Give a session a title")
    s_rename.add_argument("session")
    s_rename.add_argument("title", nargs="+")
    sessions.set_defaults(func=cmd_sessions)

    # -- model -------------------------------------------------------------
    model = sub.add_parser("model", help="List or set the default model")
    m_sub = model.add_subparsers(dest="action", metavar="<action>")
    m_sub.add_parser("list", help="Show the configured model profiles")
    m_set = m_sub.add_parser("set", help="Set the default model profile")
    m_set.add_argument("model_id")
    model.set_defaults(func=cmd_model)

    # -- config ------------------------------------------------------------
    config = sub.add_parser("config", help="View and change configuration")
    c_sub = config.add_subparsers(dest="action", metavar="<action>")
    c_sub.add_parser("show", help="Print the merged configuration")
    c_sub.add_parser("path", help="Print the config and data file locations")
    c_sub.add_parser("edit", help="Open the config in $EDITOR")
    c_get = c_sub.add_parser("get", help="Read one dotted key, e.g. assistant.name")
    c_get.add_argument("key")
    c_set = c_sub.add_parser("set", help="Write one dotted key to the local overlay")
    c_set.add_argument("key")
    c_set.add_argument("value", nargs="+")
    config.set_defaults(func=cmd_config)

    # -- skills ------------------------------------------------------------
    skills = sub.add_parser("skills", help="List, enable and disable skills")
    sk_sub = skills.add_subparsers(dest="action", metavar="<action>")
    sk_sub.add_parser("list", help="Show every skill and whether it's enabled")
    sk_enable = sk_sub.add_parser("enable", help="Enable a skill")
    sk_enable.add_argument("name")
    sk_disable = sk_sub.add_parser("disable", help="Disable a skill")
    sk_disable.add_argument("name")
    skills.set_defaults(func=cmd_skills)

    # -- tools / mcp / memory / status / doctor ----------------------------
    tools = sub.add_parser("tools", help="List the registered tools")
    tools.add_argument("--json", action="store_true", help="Machine-readable output")
    tools.set_defaults(func=cmd_tools)

    mcp = sub.add_parser("mcp", help="Show MCP servers and their tools")
    mcp.set_defaults(func=cmd_mcp)

    memory = sub.add_parser("memory", help="Inspect and search long-term memory")
    mem_sub = memory.add_subparsers(dest="action", metavar="<action>")
    mem_sub.add_parser("status", help="Memory counts and health")
    mem_recall = mem_sub.add_parser("recall", help="Search memory")
    mem_recall.add_argument("query", nargs="+")
    mem_recall.add_argument("-k", type=int, default=8, help="How many results")
    mem_remember = mem_sub.add_parser("remember", help="Store a fact")
    mem_remember.add_argument("text", nargs="+")
    memory.set_defaults(func=cmd_memory)

    status = sub.add_parser("status", help="Model, memory, gateway and security overview")
    status.set_defaults(func=cmd_status)

    doctor = sub.add_parser("doctor", help="Check the install for common problems")
    doctor.set_defaults(func=cmd_doctor)

    logs = sub.add_parser("logs", help="View the log file")
    logs.add_argument("-n", "--lines", type=int, default=50, help="How many lines")
    logs.add_argument("-f", "--follow", action="store_true", help="Follow in real time")
    logs.set_defaults(func=cmd_logs)

    setup = sub.add_parser("setup", help="Run the first-run setup wizard")
    setup.set_defaults(func=cmd_setup)

    version = sub.add_parser("version", help="Print the version")
    version.set_defaults(func=cmd_version)

    return parser


# ── Shared helpers ─────────────────────────────────────────────────────

def _apply_display_flags(args: argparse.Namespace) -> None:
    """Turn display flags into the env vars the theme module reads.

    Doing it through the environment (rather than a parameter) means every
    module — including ones reached indirectly — sees the same decision.
    """
    if getattr(args, "no_color", False):
        os.environ["NO_COLOR"] = "1"
    if getattr(args, "ascii", False):
        os.environ["NAMMA_TUI_ASCII"] = "1"
    if getattr(args, "skin", None):
        os.environ["NAMMA_TUI_SKIN"] = args.skin


def build_service(args: argparse.Namespace, *, with_gateway: bool = False) -> Any:
    """Construct the service for a CLI run.

    The messaging gateway is suppressed unless asked for: a terminal session and
    a Telegram bot answering the same agent at once interleave turns confusingly.
    ``namma gateway`` is the way to run messaging, matching how Hermes splits the
    two. ``comms.inbound_enabled`` is the config knob the service already honors.
    """
    from namma_agent.config import load_config
    from namma_agent.service import NammaAgentService

    config = load_config()
    if not with_gateway:
        comms = dict(config.get("comms") or {})
        comms["inbound_enabled"] = False
        config = {**config, "comms": comms}
    service = NammaAgentService(config=config)
    if getattr(args, "yolo", False):
        service.auto_approve = True
    return service


def _resolve_session(service: Any, args: argparse.Namespace) -> Optional[str]:
    """Turn ``--resume`` / ``--continue`` into a session id, or None for a new one."""
    from namma_agent.tui.app import _find_session

    needle = getattr(args, "resume", None)
    continue_last = getattr(args, "continue_last", None)
    if needle:
        match = _find_session(service.db, needle)
        if not match:
            _err(f"no session matching {needle!r}")
            return None
        return str(match["id"])
    if continue_last is True:
        rows = service.db.list_sessions(limit=1) or []
        if not rows:
            _err("no previous sessions to continue")
            return None
        return str(rows[0]["id"])
    if isinstance(continue_last, str) and continue_last:
        match = _find_session(service.db, continue_last)
        if not match:
            _err(f"no session matching {continue_last!r}")
            return None
        return str(match["id"])
    return None


def _console():
    from rich.console import Console
    return Console()


def _err(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def _print_rows(rows: list[tuple[str, str]], title: str = "") -> None:
    """Print aligned label/value pairs through the active skin.

    Values are clipped to the terminal width rather than wrapped — a wrapped
    value breaks the column alignment that makes these tables readable.
    """
    from namma_agent.tui import render, theme

    console = _console()
    if title:
        console.print(theme.styled(title, "banner_accent", bold=True))
    label_width = max((len(label) for label, _ in rows), default=0)
    value_width = max(20, console.width - label_width - 5)
    for label, value in rows:
        clipped = render.truncate(str(value), value_width)
        console.print(f"  {theme.styled(label.ljust(label_width), 'banner_dim')}  "
                      f"{_escape(clipped)}")


def _escape(text: str) -> str:
    """Escape rich markup so config values containing ``[...]`` render literally."""
    return str(text).replace("[", "\\[")


def _interface(args: argparse.Namespace) -> str:
    """``tui`` or ``plain`` — which front end this invocation should use.

    The full TUI needs a real terminal and both optional display dependencies.
    Anything else (a pipe, a CI job, a missing package) gets the plain REPL,
    which needs neither, rather than a crash.
    """
    if getattr(args, "cli", False):
        return "plain"
    if getattr(args, "tui", False):
        return "tui"
    if not _display_deps_available():
        return "plain"
    try:
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return "plain"
    except (ValueError, OSError):
        return "plain"
    return "tui"


def _display_deps_available() -> bool:
    try:
        import prompt_toolkit  # noqa: F401
        import rich  # noqa: F401
    except ImportError:
        return False
    return True


# ── Command handlers ───────────────────────────────────────────────────

def cmd_chat(args: argparse.Namespace) -> int:
    """The default action: the terminal UI, or a single query with ``-q``."""
    service = build_service(args, with_gateway=getattr(args, "with_gateway", False))
    session_id = _resolve_session(service, args)
    if session_id is None and (args.resume or args.continue_last):
        return 1

    query = getattr(args, "query", None)
    if query:
        result = service.run_turn(query, session_id=session_id, mode=args.mode,
                                  model_id=args.model)
        _console().print(result.content or "")
        return 0

    if _interface(args) == "plain":
        return _run_plain(service, args, session_id)

    from namma_agent.tui import app as tui_app
    tui_app.run(service, session_id=session_id, mode=args.mode,
                model_id=args.model, auto_approve=bool(args.yolo))
    return 0


def _run_plain(service: Any, args: argparse.Namespace, session_id: Optional[str]) -> int:
    """The dependency-free REPL used when the TUI can't or shouldn't run."""
    from namma_agent.comms.console import ConsoleInbound
    from namma_agent.config import assistant_name

    def turn(text, sid, mode, askpass=None, model=None):
        result = service.run_turn(text, session_id=sid, mode=mode,
                                  askpass=askpass, model_id=model)
        return result.content, result.session_id

    bridge = ConsoleInbound(turn, get_models=service.configured_models,
                            name=assistant_name(service.config))
    bridge._session_id = session_id
    bridge._mode = args.mode
    bridge._model_id = args.model
    bridge.run_blocking()
    return 0


def cmd_oneshot(args: argparse.Namespace) -> int:
    """``-z``: print only the answer, so the output can be piped."""
    service = build_service(args)
    session_id = _resolve_session(service, args)
    if session_id is None and (args.resume or args.continue_last):
        return 1
    # A one-shot run has nobody to ask, so approvals are auto-granted — the same
    # decision Hermes makes for -z, and the reason it's documented as script-only.
    service.auto_approve = True
    result = service.run_turn(args.oneshot, session_id=session_id, mode=args.mode,
                              model_id=args.model)
    sys.stdout.write((result.content or "").rstrip() + "\n")
    return 0


def cmd_gateway(args: argparse.Namespace) -> int:
    """Messaging-only mode: no terminal chat, just the inbound channels."""
    import time

    from namma_agent.tui import theme

    service = build_service(args, with_gateway=True)
    console = _console()
    status = service.comms_status()

    if getattr(args, "action", None) == "status":
        _print_rows([("running", str(status.get("running", False))),
                     ("channels", ", ".join(status.get("channels") or []) or "none"),
                     ("available", ", ".join(status.get("available") or []) or "none")],
                    title="Gateway")
        return 0

    channels = status.get("channels") or []
    if not channels:
        _err("no messaging channels are configured — add a token first "
             "(namma serve → Settings → Messaging)")
        return 1

    console.print(theme.styled(
        f"Gateway running on: {', '.join(channels)}", "good", bold=True))
    console.print(theme.styled("Ctrl+C to stop.", "banner_dim"))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        console.print(theme.styled("\nStopping…", "banner_dim"))
        service.stop_comms()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the web UI + API (the same thing ``python -m namma_agent --server`` does)."""
    from namma_agent.app import main

    if getattr(args, "host", None):
        os.environ["NAMMA_HOST"] = str(args.host)
    if getattr(args, "port", None):
        os.environ["NAMMA_PORT"] = str(args.port)
    main(server_only=True)
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    from namma_agent.tui import theme
    from namma_agent.tui.app import _find_session

    service = build_service(args)
    action = getattr(args, "action", None) or "list"
    console = _console()

    if action == "list":
        rows = service.db.list_sessions(limit=getattr(args, "limit", 20)) or []
        if not rows:
            console.print(theme.styled("No sessions yet.", "banner_dim"))
            return 0
        console.print(theme.styled("Recent sessions", "banner_accent", bold=True))
        for row in rows:
            sid = str(row.get("id") or "")
            when = str(row.get("updated_at") or row.get("created_at") or "")[:16]
            title = str(row.get("title") or row.get("summary") or "(untitled)")[:60]
            console.print(f"  {theme.styled(sid[:8], 'banner_accent')} "
                          f"{theme.styled(when, 'banner_dim')}  {title}")
        return 0

    if action == "browse":
        return _browse_sessions(service, args)

    if action == "resume":
        match = _find_session(service.db, args.session)
        if not match:
            _err(f"no session matching {args.session!r}")
            return 1
        args.resume = str(match["id"])
        args.continue_last = None
        return cmd_chat(args)

    if action == "rename":
        match = _find_session(service.db, args.session)
        if not match:
            _err(f"no session matching {args.session!r}")
            return 1
        title = " ".join(args.title)
        if not service.db.rename_session(str(match["id"]), title):
            _err("rename failed")
            return 1
        console.print(f"Renamed {str(match['id'])[:8]} to {title!r}")
        return 0

    _err(f"unknown sessions action: {action}")
    return 2


def _browse_sessions(service: Any, args: argparse.Namespace) -> int:
    """Numbered picker, then resume the chosen session."""
    from namma_agent.tui import theme

    rows = service.db.list_sessions(limit=30) or []
    console = _console()
    if not rows:
        console.print(theme.styled("No sessions yet.", "banner_dim"))
        return 0
    console.print(theme.styled("Pick a session", "banner_accent", bold=True))
    for i, row in enumerate(rows, start=1):
        when = str(row.get("updated_at") or row.get("created_at") or "")[:16]
        title = str(row.get("title") or row.get("summary") or "(untitled)")[:56]
        console.print(f"  {theme.styled(f'{i:>2}', 'banner_accent')}. "
                      f"{theme.styled(when, 'banner_dim')}  {title}")
    try:
        choice = input("\nNumber (or Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        return 0
    if not choice:
        return 0
    if not choice.isdigit() or not 1 <= int(choice) <= len(rows):
        _err("not a valid choice")
        return 1
    args.resume = str(rows[int(choice) - 1]["id"])
    args.continue_last = None
    return cmd_chat(args)


def cmd_model(args: argparse.Namespace) -> int:
    from namma_agent.tui import theme

    service = build_service(args)
    action = getattr(args, "action", None) or "list"
    console = _console()
    models = service.configured_models() or []

    if action == "list":
        if not models:
            console.print(theme.styled(
                "No model profiles configured — run `namma setup`.", "banner_dim"))
            return 0
        current = str(getattr(service.provider, "model", ""))
        console.print(theme.styled("Configured models", "banner_accent", bold=True))
        for entry in models:
            label = entry.get("label") or entry.get("model") or entry.get("id")
            mark = "  (current)" if entry.get("model") == current else ""
            console.print(f"  {theme.styled(str(entry.get('id')), 'banner_accent')}  "
                          f"{label}{theme.styled(mark, 'good')}")
        return 0

    if action == "set":
        known = {str(entry.get("id")) for entry in models}
        if args.model_id not in known:
            _err(f"unknown model profile {args.model_id!r} — see `namma model list`")
            return 1
        # There is no "default profile" key: provider_for() falls back to the
        # FIRST configured profile, so making one the default means moving it to
        # the front of the models list.
        reordered = ([m for m in models if str(m.get("id")) == args.model_id]
                     + [m for m in models if str(m.get("id")) != args.model_id])
        _config_set_value("models", reordered)
        console.print(f"Default model is now {args.model_id}")
        return 0

    _err(f"unknown model action: {action}")
    return 2


def cmd_config(args: argparse.Namespace) -> int:
    import json

    from namma_agent.config import load_config
    from namma_agent.tui import theme

    action = getattr(args, "action", None) or "show"
    console = _console()

    if action == "show":
        console.print_json(json.dumps(load_config(), default=str))
        return 0

    if action == "path":
        _print_rows(_config_paths(), title="Locations")
        return 0

    if action == "edit":
        return _edit_config()

    if action == "get":
        value = _dig(load_config(), args.key)
        if value is None:
            _err(f"no such key: {args.key}")
            return 1
        console.print(json.dumps(value, default=str) if isinstance(value, (dict, list))
                      else str(value))
        return 0

    if action == "set":
        value = " ".join(args.value)
        path = _config_set(args.key, value)
        console.print(f"Set {args.key} = {value!r} in {path}")
        console.print(theme.styled("Restart Namma for it to take effect.", "banner_dim"))
        return 0

    _err(f"unknown config action: {action}")
    return 2


def _config_paths() -> list[tuple[str, str]]:
    from namma_agent.config import _config_path, _local_overrides_path

    base = _config_path()
    return [
        ("config", os.path.normpath(str(base))),
        ("local overlay", os.path.normpath(str(_local_overrides_path(base)))),
        ("data", os.path.normpath(os.path.expanduser("~/.namma_agent"))),
        ("skins", os.path.normpath(os.path.expanduser("~/.namma_agent/skins"))),
        ("logs", os.path.abspath("logs/namma_agent.log")),
    ]


def _dig(data: Any, dotted: str) -> Any:
    """Read a dotted key out of nested dicts, or None if any hop is missing."""
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _config_set(dotted: str, value: str) -> str:
    """Write a dotted key into ``config.local.yaml``, coercing the string value."""
    return _config_set_value(dotted, _coerce(value))


def _config_set_value(dotted: str, value: Any) -> str:
    """Write an already-typed value at a dotted key. Returns the file written.

    The local overlay is the right target: it survives upgrades and is already
    where the web UI persists settings, so the CLI and the UI don't fight.
    """
    import yaml

    from namma_agent.config import _config_path, _local_overrides_path

    path = _local_overrides_path(_config_path())
    data: dict = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle.read()) or {}

    node = data
    parts = dotted.split(".")
    for part in parts[:-1]:
        if not isinstance(node.get(part), dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value

    os.makedirs(os.path.dirname(str(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
    return str(path)


def _coerce(value: str) -> Any:
    """Turn a command-line string into a bool/int/float when it clearly is one."""
    low = value.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def _edit_config() -> int:
    import subprocess

    from namma_agent.config import _config_path, _local_overrides_path

    path = _local_overrides_path(_config_path())
    if not os.path.exists(path):
        open(path, "w", encoding="utf-8").write("# Namma Agent local overrides\n")
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    try:
        subprocess.run([editor, str(path)], check=False)
    except OSError as exc:
        _err(f"could not launch {editor}: {exc}")
        return 1
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    from namma_agent.tui import theme

    service = build_service(args)
    action = getattr(args, "action", None) or "list"
    console = _console()

    if action == "list":
        from namma_agent.tui import render

        details = sorted(service.skills_detail() or [],
                         key=lambda d: str(d.get("name", "")))
        console.print(theme.styled(f"{len(details)} skills", "banner_accent", bold=True))
        name_width = min(32, max((len(str(d.get("name", ""))) for d in details), default=0))
        blurb_width = max(20, console.width - name_width - 12)
        for entry in details:
            enabled = entry.get("enabled", True)
            mark = theme.styled("on ", "good") if enabled else theme.styled("off", "bad")
            name = render.truncate(str(entry.get("name") or ""), name_width)
            blurb = render.truncate(str(entry.get("description") or ""), blurb_width)
            console.print(f"  {mark}  "
                          f"{theme.styled(name.ljust(name_width), 'banner_accent')}  "
                          f"{theme.styled(_escape(blurb), 'banner_dim')}")
        return 0

    if action in ("enable", "disable"):
        service.set_skill_enabled(args.name, action == "enable")
        console.print(f"{args.name}: {action}d")
        return 0

    _err(f"unknown skills action: {action}")
    return 2


def cmd_tools(args: argparse.Namespace) -> int:
    import json

    from namma_agent.tui import render, theme

    service = build_service(args)
    names = sorted(service.registry.names())
    if getattr(args, "json", False):
        print(json.dumps(names))
        return 0
    console = _console()
    console.print(theme.styled(f"{len(names)} tools", "banner_accent", bold=True))
    for row in render.columns(names, max(20, console.width - 4)):
        console.print(theme.styled(row, "banner_dim"))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from namma_agent.tui import theme

    service = build_service(args)
    console = _console()
    detail = service.mcp_detail() or {}
    servers = detail.get("servers") or []
    if not servers:
        console.print(theme.styled("No MCP servers configured.", "banner_dim"))
        return 0
    console.print(theme.styled("MCP servers", "banner_accent", bold=True))
    for server in servers:
        state = "connected" if server.get("connected") else "not connected"
        color = "good" if server.get("connected") else "bad"
        tools = server.get("tools") or []
        count = len(tools) if isinstance(tools, list) else tools
        console.print(f"  {theme.styled(str(server.get('name')), 'banner_accent')}  "
                      f"{theme.styled(state, color)}  "
                      f"{theme.styled(f'{count} tool(s)', 'banner_dim')}")
    return 0


def cmd_memory(args: argparse.Namespace) -> int:
    from namma_agent.tui import theme

    service = build_service(args)
    action = getattr(args, "action", None) or "status"
    console = _console()

    if action == "status":
        status = service.memory_status() or {}
        _print_rows([(k, str(v)) for k, v in status.items()], title="Memory")
        return 0

    if action == "recall":
        query = " ".join(args.query)
        found = (service.memory_recall(query, k=args.k) or {}).get("items") or []
        if not found:
            console.print(theme.styled("Nothing recalled.", "banner_dim"))
            return 0
        console.print(theme.styled(f"{len(found)} result(s)", "banner_accent", bold=True))
        for item in found:
            text = str(item.get("text") or item.get("content") or "")[:100]
            console.print(f"  {theme.styled('·', 'banner_dim')} {text}")
        return 0

    if action == "remember":
        text = " ".join(args.text)
        service.memory_remember(text)
        console.print("Remembered.")
        return 0

    _err(f"unknown memory action: {action}")
    return 2


def cmd_status(args: argparse.Namespace) -> int:
    from namma_agent.tui import theme

    from namma_agent.version import __version__

    service = build_service(args)
    info = service.info() or {}
    comms = service.comms_status() or {}
    memory = service.memory_status() or {}

    rows = [
        ("assistant", str(info.get("assistant_name") or "")),
        ("version", __version__),
        ("persona", str(info.get("persona") or "")),
        ("provider", ", ".join(info.get("provider") or [])),
        ("model", str(info.get("model") or "unconfigured")),
        ("tools", str(len(info.get("tools") or []))),
        ("memory", str(memory.get("items", memory.get("count", "—")))),
        ("gateway", ", ".join(comms.get("channels") or []) or "not running"),
        ("colors", theme.color_depth()),
        ("skin", theme.get_active_skin().name),
    ]
    _print_rows(rows, title="Namma Agent")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Check the things that actually break installs, and say how to fix each."""
    from namma_agent.tui import theme

    console = _console()
    checks: list[tuple[bool, str, str]] = []

    checks.append((sys.version_info >= (3, 10), "python >= 3.10",
                   f"found {sys.version.split()[0]}"))
    for module, why in (("rich", "TUI rendering"), ("prompt_toolkit", "TUI input")):
        try:
            __import__(module)
            checks.append((True, module, why))
        except ImportError:
            checks.append((False, module, f"missing — pip install {module} ({why})"))

    try:
        service = build_service(args)
        model = str(getattr(service.provider, "model", ""))
        checks.append((bool(model), "provider configured",
                       model or "run `namma setup`"))
        checks.append((True, "database", "opened"))
        tools = len(service.registry.names())
        checks.append((tools > 0, "tools registered", f"{tools}"))
    except Exception as exc:  # noqa: BLE001 - doctor reports failures, never raises
        checks.append((False, "service", f"failed to start: {exc}"))

    console.print(theme.styled("Checks", "banner_accent", bold=True))
    failed = 0
    for ok, label, detail in checks:
        mark = theme.styled("ok  ", "good") if ok else theme.styled("FAIL", "critical")
        if not ok:
            failed += 1
        console.print(f"  {mark}  {label.ljust(20)} {theme.styled(detail, 'banner_dim')}")

    # Terminal capability is reported, never failed: no-color is the correct
    # answer when output is piped or NO_COLOR is set, not a broken install.
    glyphs = "unicode" if theme.supports_unicode() else "ascii"
    console.print(f"  {theme.styled('info', 'banner_dim')}  {'terminal'.ljust(20)} "
                  f"{theme.styled(f'{theme.color_depth()} color, {glyphs}', 'banner_dim')}")

    console.print()
    console.print(theme.styled(
        "All good." if not failed else f"{failed} problem(s) found.",
        "good" if not failed else "bad"))
    return 0 if not failed else 1


def cmd_logs(args: argparse.Namespace) -> int:
    import time

    path = os.path.abspath("logs/namma_agent.log")
    if not os.path.exists(path):
        _err(f"no log file at {path}")
        return 1

    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
        for line in lines[-max(1, args.lines):]:
            sys.stdout.write(line)
        if not args.follow:
            return 0
        handle.seek(0, os.SEEK_END)
        try:
            while True:
                line = handle.readline()
                if line:
                    sys.stdout.write(line)
                    sys.stdout.flush()
                else:
                    time.sleep(0.3)
        except KeyboardInterrupt:
            return 0


def cmd_setup(args: argparse.Namespace) -> int:
    from namma_agent.core.setup_wizard import run_onboarding, run_wizard

    run_wizard()
    run_onboarding()
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    from namma_agent.config import assistant_name
    from namma_agent.version import __version__

    print(f"{assistant_name()} v{__version__}")
    return 0


# ── Entry point ────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    """Parse ``argv`` and run the matching command. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    _apply_display_flags(args)

    if args.version:
        return cmd_version(args)
    if args.oneshot:
        return cmd_oneshot(args)

    handler = getattr(args, "func", None)
    if handler is None:
        # No subcommand — the default action is interactive chat.
        args.query = None
        handler = cmd_chat
    try:
        return int(handler(args) or 0)
    except KeyboardInterrupt:
        return 130
