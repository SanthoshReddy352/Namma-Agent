"""The terminal UI application.

A ``prompt_toolkit`` :class:`Application` in non-fullscreen mode: the transcript
prints into normal terminal scrollback (so it stays scrollable and copyable)
while the bottom of the screen holds live chrome — spinner, status bar, and the
input box between two bronze rules.

The chat logic is inherited from :class:`~namma_agent.comms.inbound.InboundBridge`,
the same base the Telegram, Signal and console channels use, so ``/commands``,
``!shell``, the model picker and the sudo askpass all behave identically here.
This module overrides only *transport*: how a line is read, and how a reply and
its intermediate events are shown.

Turns run on a worker thread. The UI thread never blocks, so Ctrl+C can cancel a
turn in flight and the spinner keeps animating while a tool runs.
"""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Optional

from namma_agent.comms.inbound import InboundBridge
from namma_agent.core.logger import logger
from namma_agent.tui import banner, render, theme

# Slash commands offered by tab-completion, with the one-line help shown beside
# each. Handled in _handle_command below or by the InboundBridge base.
TUI_COMMANDS: dict[str, str] = {
    "/help": "show this help",
    "/new": "start a fresh conversation",
    "/mode": "switch between chat and agent mode",
    "/model": "switch the AI model",
    "/tools": "list the available tools",
    "/skills": "list the available skills",
    "/sessions": "list recent sessions",
    "/resume": "resume a session by id",
    "/status": "show model, session and gateway status",
    "/skin": "switch the TUI color skin",
    "/cls": "clear the screen",
    "/clear": "wipe the agent's memory",
    "/quit": "exit",
}


class TuiChat(InboundBridge):
    """The chat session behind the TUI.

    Subclasses :class:`InboundBridge` for the shared command/turn logic and
    replaces its transport: :meth:`_say` writes to the transcript, and
    :meth:`_execute` runs the turn through the service with a live event sink and
    token stream rather than waiting for a single blob of text.
    """

    def __init__(self, service: Any, *, name: str = "Namma Agent",
                 mode: str = "agent", model_id: Optional[str] = None,
                 session_id: Optional[str] = None,
                 auto_approve: bool = False):
        # on_message is unused — _execute is overridden to call the service
        # directly so it can pass a sink, a token stream and a cancel check.
        super().__init__(on_message=lambda *a, **k: ("", None),
                         get_models=service.configured_models)
        self.service = service
        self.name = name
        self._mode = mode
        self._model_id = model_id
        self._session_id = session_id
        self.auto_approve = auto_approve

        self._console = _console()
        self.spinner = render.Spinner()
        self._cancel = threading.Event()
        self._busy = threading.Event()
        self._turns = 0
        self._last_usage: dict = {}
        self._streamed = False   # did this turn print any token yet?
        self._invalidate: Callable[[], None] = lambda: None

        # Set while a destructive tool waits on a y/n answer. The next line typed
        # is consumed as that answer — the same pattern the base class already
        # uses for the sudo password and the numbered model picker. The inline
        # approval panel replaces this in the widget pass.
        self._approval_lock = threading.Lock()
        self._approval_event: Optional[threading.Event] = None
        self._approval_value: Optional[bool] = None
        self._approval_what: str = ""

    # -- transport ---------------------------------------------------------

    @property
    def channel_name(self) -> str:
        return "tui"

    def _say(self, text: str) -> None:
        """Write a plain (already-formatted) message to the transcript."""
        self.write(text)

    def write(self, markup: str = "", *, plain: bool = False) -> None:
        """Print one line into the scrollback above the chrome.

        ``patch_stdout`` (installed by :meth:`TerminalUI.run`) routes this above
        the live widgets, so it is safe to call from the worker thread.
        """
        try:
            if plain:
                self._console.print(markup, markup=False, highlight=False)
            else:
                self._console.print(markup, highlight=False)
        except Exception as exc:  # noqa: BLE001 - never let display kill a turn
            logger.debug("[tui] write failed: %s", exc)

    # -- the turn ----------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy.is_set()

    def cancel(self) -> bool:
        """Ask the running turn to stop. Returns True if a turn was running."""
        if not self.busy:
            return False
        self._cancel.set()
        self.spinner.start("cancelling" + theme.glyph("ellipsis"))
        return True

    def _execute(self, text: str) -> str:
        """Run one turn with live streaming. Overrides the base's blocking call.

        Note there is no progress sink here, unlike the messaging bridges. Those
        need one because a chat app can only show whole messages; a terminal
        gets the model's between-tool narration through ``on_token`` already, in
        the right order, so re-delivering ``preamble`` events would double it.
        """
        from namma_agent.core.trust import reset_message_trust, set_message_trust

        self._cancel.clear()
        self._busy.set()
        self._streamed = False
        self.spinner.start(kind="thinking")
        trust_token = set_message_trust(self.trust)
        started = time.monotonic()
        try:
            result = self.service.run_turn(
                text,
                session_id=self._session_id,
                sink=self._on_event,
                on_token=self._on_token,
                approval=self._approve,
                mode=self._mode,
                should_cancel=self._cancel.is_set,
                askpass=self.askpass,
                model_id=self._model_id,
            )
            self._session_id = result.session_id
            self._turns += 1
            self._last_usage = dict(result.usage or {})
            reply = result.content or ""
        except Exception as exc:  # noqa: BLE001 - one bad turn must not end the session
            logger.warning("[tui] turn failed: %s", exc, exc_info=True)
            self._error(f"That turn failed: {exc}")
            reply = ""
        finally:
            reset_message_trust(trust_token)
            was_cancelled = self._cancel.is_set()
            self.spinner.stop()
            self._busy.clear()
            self._cancel.clear()
            self._invalidate()

        if was_cancelled:
            self._note("cancelled")
        logger.debug("[tui] turn finished in %.1fs", time.monotonic() - started)
        # Anything already streamed is on screen; returning "" stops the base
        # class from printing the whole answer a second time.
        return "" if self._streamed else reply

    def _run_turn(self, text: str) -> None:
        """A /command turn — the base prints the reply; we may already have."""
        reply = self._execute(text)
        if reply:
            self._say(reply)

    def _reply_turn(self, text: str, ref=None) -> None:
        reply = self._execute(text)
        if reply:
            self._answer(reply)

    # -- streaming sinks ---------------------------------------------------

    def _on_token(self, chunk: str) -> None:
        """Write streamed model output straight through, unstyled."""
        if not chunk:
            return
        if not self._streamed:
            self.spinner.stop()
            self._answer_label()
            self._streamed = True
        try:
            self._console.file.write(chunk)
            self._console.file.flush()
        except Exception:  # noqa: BLE001 - a closed stream shouldn't kill the turn
            pass

    def _on_event(self, event_type: str, payload: dict) -> None:
        """Render the agent's typed events as transcript lines."""
        try:
            if event_type == "tool_started":
                name = payload.get("tool") or payload.get("name") or "tool"
                self.spinner.start(f"running {name}", kind="waiting")
                self.write(render.tool_line(name, payload.get("args") or {}))
            elif event_type == "tool_finished":
                name = payload.get("tool") or payload.get("name") or "tool"
                ok = bool(payload.get("ok", True))
                self.write(render.tool_result_line(
                    name, ok, str(payload.get("summary") or payload.get("error") or ""),
                    payload.get("elapsed")))
                self.spinner.start(kind="thinking")
            elif event_type == "turn_completed":
                self.spinner.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("[tui] event %s failed to render: %s", event_type, exc)
        finally:
            self._invalidate()

    # -- approval (typed y/n until the inline panel lands) ------------------

    def _approve(self, tool_name: str, args: dict) -> bool:
        """Ask the user to approve a destructive tool call.

        Blocks the worker thread on the answer typed into the input box. Denies
        on timeout so a walked-away-from terminal never runs something
        destructive on its own.
        """
        if self.auto_approve:
            return True
        event = threading.Event()
        with self._approval_lock:
            if self._approval_event is not None:
                return False  # one at a time; a second request is refused
            self._approval_event, self._approval_value = event, None
            self._approval_what = tool_name

        preview = render.tool_preview(tool_name, args)
        self.spinner.stop()
        line = (theme.styled(f"{theme.glyph('warn')} approve", "bad")
                + " " + theme.styled(tool_name, "banner_accent", bold=True))
        if preview:
            line += " " + theme.styled(_escape(preview), "tool_line")
        self.write(line)
        self.write(theme.styled("type y to run it, anything else to skip", "hint"))
        self._invalidate()

        answered = event.wait(timeout=300)
        with self._approval_lock:
            value, self._approval_event = self._approval_value, None
            self._approval_what = ""
        if not answered:
            self._note(f"no answer in 5 minutes {theme.glyph('emdash')} skipped")
            return False
        return bool(value)

    def _capture_approval(self, text: str) -> None:
        with self._approval_lock:
            self._approval_value = text.strip().lower() in ("y", "yes", "ok", "run")
            event = self._approval_event
        if event:
            event.set()

    # -- transcript helpers ------------------------------------------------

    def _answer_label(self) -> None:
        self.write()
        self.write(theme.styled(f"{self.name}:", "agent_label", bold=True))

    def _answer(self, text: str) -> None:
        self._answer_label()
        self.write(_escape(text))

    def _note(self, text: str) -> None:
        self.write(theme.styled(_escape(text), "banner_dim"))

    def _error(self, text: str) -> None:
        self.write(theme.styled(_escape(text), "critical"))

    def echo_user(self, text: str) -> None:
        """Echo the submitted line into the transcript, above the chrome."""
        mark = theme.styled(theme.glyph("prompt"), "user_label", bold=True)
        self.write()
        self.write(f"{mark} {_escape(text)}")

    # -- commands ----------------------------------------------------------

    def handle_text(self, text: str, ref=None) -> None:
        """Route one submitted line. Approval answers are consumed first."""
        text = (text or "").strip()
        if not text:
            return
        if self._approval_event is not None:
            self._capture_approval(text)
            return
        super().handle_text(text, ref)

    def _handle_command(self, text: str) -> bool:
        """TUI-only commands; anything unhandled falls through to the base set."""
        low = text.strip().lower()
        cmd, _, arg = low.partition(" ")
        arg = arg.strip()

        if cmd in ("/quit", "/exit", "/q"):
            raise _Quit()
        if cmd == "/cls":
            self._console.clear()
            return True
        if cmd == "/tools":
            self._list_tools()
            return True
        if cmd == "/skills":
            self._list_skills()
            return True
        if cmd == "/sessions":
            self._list_sessions()
            return True
        if cmd == "/resume":
            self._resume(arg)
            return True
        if cmd == "/status":
            self._status()
            return True
        if cmd == "/skin":
            self._switch_skin(arg)
            return True
        if low in ("/help", "/start"):
            self._help()
            return True
        return super()._handle_command(text)

    def _help(self) -> None:
        self.write()
        self.write(theme.styled(f"{self.name} — commands", "banner_accent", bold=True))
        for cmd, blurb in TUI_COMMANDS.items():
            self.write(f"  {theme.styled(f'{cmd:<11}', 'banner_accent')} "
                       f"{theme.styled(blurb, 'banner_dim')}")
        self.write(f"  {theme.styled('!<cmd>'.ljust(11), 'banner_accent')} "
                   f"{theme.styled('run a shell command, e.g. !git status', 'banner_dim')}")
        self.write()
        dot = theme.glyph("middot")
        self.write(theme.styled(
            f"Enter sends {dot} Ctrl+J newline {dot} Ctrl+C cancels a turn "
            f"{dot} Ctrl+D exits", "banner_dim"))

    def _list_tools(self) -> None:
        names = sorted(self.service.registry.names())
        self.write()
        self.write(theme.styled(f"{len(names)} tools", "banner_accent", bold=True))
        for row in render.columns(names, self._console.width - 4):
            self.write(theme.styled(row, "banner_dim"))

    def _list_skills(self) -> None:
        try:
            skills = sorted(self.service.skills.all(), key=lambda s: s.name)
        except Exception:  # noqa: BLE001
            skills = []
        self.write()
        self.write(theme.styled(f"{len(skills)} skills", "banner_accent", bold=True))
        for skill in skills:
            mark = "" if getattr(skill, "enabled", True) else " (disabled)"
            blurb = (getattr(skill, "description", "") or "")[:60]
            self.write(f"  {theme.styled(skill.name, 'banner_accent')}{mark} "
                       f"{theme.styled(_escape(blurb), 'banner_dim')}")

    def _list_sessions(self, limit: int = 15) -> None:
        rows = self.service.db.list_sessions(limit=limit) or []
        self.write()
        self.write(theme.styled("Recent sessions", "banner_accent", bold=True))
        if not rows:
            self._note("no sessions yet")
            return
        for row in rows:
            sid = str(row.get("id") or "")[:8]
            title = row.get("title") or row.get("summary") or "(untitled)"
            when = str(row.get("updated_at") or row.get("created_at") or "")[:16]
            current = f" {theme.glyph('arrow_left')}" if (
                self._session_id and str(row.get("id")) == self._session_id) else ""
            self.write(f"  {theme.styled(sid, 'banner_accent')} "
                       f"{theme.styled(when, 'banner_dim')} "
                       f"{_escape(str(title)[:52])}{current}")
        self._note("resume one with /resume <id>")

    def _resume(self, session_id: str) -> None:
        if not session_id:
            self._note("usage: /resume <session id>")
            return
        match = _find_session(self.service.db, session_id)
        if not match:
            self._error(f"no session matching {session_id!r}")
            return
        self._session_id = str(match["id"])
        title = match.get("title") or "(untitled)"
        self._note(f"resumed {self._session_id[:8]} — {title}")

    def _status(self) -> None:
        model = getattr(self.service.provider, "model", "unconfigured")
        rows = [
            ("model", str(model)),
            ("mode", self._mode),
            ("session", self._session_id or "(new)"),
            ("turns", str(self._turns)),
            ("cwd", os.getcwd()),
            ("skin", theme.get_active_skin().name),
            ("colors", theme.color_depth()),
        ]
        if self._last_usage:
            used = self._last_usage
            rows.append(("last turn", f"{used.get('input_tokens', 0)} in / "
                                      f"{used.get('output_tokens', 0)} out"))
        self.write()
        self.write(theme.styled("Status", "banner_accent", bold=True))
        for label, value in rows:
            self.write(f"  {theme.styled(label.ljust(10), 'banner_dim')} {_escape(value)}")

    def _switch_skin(self, name: str) -> None:
        if not name:
            self._note(f"skins: {', '.join(theme.available_skins())}")
            return
        theme.set_active_skin(name)
        self._note(f"skin set to {theme.get_active_skin().name}")
        self._invalidate()


class _Quit(Exception):
    """Raised by /quit to unwind out of the input handler."""


# ── The prompt_toolkit application ─────────────────────────────────────

class TerminalUI:
    """Owns the widgets, the key bindings and the event loop."""

    def __init__(self, chat: TuiChat):
        self.chat = chat
        self.app = None
        self._worker: Optional[threading.Thread] = None
        self._exiting = False

    # -- chrome ------------------------------------------------------------

    def _status_segments(self) -> list[tuple[str, str]]:
        """``(style_class, text)`` pairs for the status bar, left to right."""
        chat = self.chat
        model = str(getattr(chat.service.provider, "model", "") or "unconfigured")
        if "/" in model:
            model = model.split("/")[-1]
        segments = [
            ("class:status-bar-strong", f" {model} "),
            ("class:status-bar-dim", theme.glyph("vbar") + " "),
            ("class:status-bar", f"{chat._mode} "),
            ("class:status-bar-dim", theme.glyph("vbar") + " "),
        ]
        if chat._session_id:
            segments += [("class:status-bar", f"{chat._session_id[:8]} "),
                         ("class:status-bar-dim", theme.glyph("vbar") + " ")]
        if chat.auto_approve:
            segments += [("class:status-bar-yolo", " auto-approve "),
                         ("class:status-bar-dim", theme.glyph("vbar") + " ")]
        segments.append(("class:status-bar-dim", f"{render.shorten_path(os.getcwd(), 30)} "))
        state = ("class:status-bar-warn", " working ") if chat.busy else \
                ("class:status-bar-good", " ready ")
        segments.append(state)
        return segments

    def _spinner_fragments(self):
        spinner = self.chat.spinner
        if not spinner.running:
            return []
        spinner.advance()
        return [("class:prompt-working", f"  {spinner.text()}")]

    def _build(self):
        from prompt_toolkit.application import Application
        from prompt_toolkit.filters import Condition
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.layout import (
            ConditionalContainer, FormattedTextControl, HSplit, Layout, Window,
        )
        from prompt_toolkit.layout.dimension import Dimension
        from prompt_toolkit.layout.menus import CompletionsMenu
        from prompt_toolkit.styles import Style
        from prompt_toolkit.widgets import TextArea

        chat = self.chat
        rule_char = theme.glyph("hbar")

        input_area = TextArea(
            height=Dimension(min=1, max=8),
            prompt=theme.glyph("prompt") + " ",
            multiline=True,
            wrap_lines=True,
            style="class:input-area",
            completer=_slash_completer(),
            complete_while_typing=True,
            history=_history(),
            accept_handler=None,   # Enter is bound explicitly below
        )
        self.input_area = input_area

        def rule():
            return Window(height=1, char=rule_char, style="class:input-rule")

        spinner_window = ConditionalContainer(
            Window(FormattedTextControl(self._spinner_fragments), height=1),
            filter=Condition(lambda: chat.spinner.running),
        )
        status_window = Window(
            FormattedTextControl(self._status_segments),
            height=1, style="class:status-bar",
        )

        layout = Layout(HSplit([
            spinner_window,
            Window(height=1, char=" "),      # spacer
            status_window,
            rule(),
            input_area,
            rule(),
            ConditionalContainer(CompletionsMenu(max_height=10, scroll_offset=1),
                                 filter=Condition(lambda: True)),
        ]))

        kb = KeyBindings()

        @kb.add("enter")
        def _submit(event) -> None:
            buffer = event.current_buffer
            text = buffer.text
            if not text.strip():
                return
            buffer.reset(append_to_history=True)
            self._submit(text)

        @kb.add("c-j")
        def _newline(event) -> None:
            event.current_buffer.insert_text("\n")

        @kb.add("c-c")
        def _interrupt(event) -> None:
            if chat.cancel():
                return
            if event.current_buffer.text:
                event.current_buffer.reset()
                return
            self._quit()

        @kb.add("c-d")
        def _eof(event) -> None:
            if not event.current_buffer.text:
                self._quit()

        @kb.add("c-l")
        def _clear(event) -> None:
            chat._console.clear()

        style_dict = _style_dict()
        self.app = Application(
            layout=layout,
            key_bindings=kb,
            style=Style.from_dict(style_dict),
            color_depth=theme.prompt_toolkit_color_depth(),
            full_screen=False,
            mouse_support=False,
            # Keeps the spinner animating and the status bar's state fresh
            # while a turn runs. Idle cost is one repaint of two short lines.
            refresh_interval=0.12,
            erase_when_done=True,
        )
        chat._invalidate = self._invalidate
        return self.app

    def _invalidate(self) -> None:
        try:
            if self.app is not None:
                self.app.invalidate()
        except Exception:  # noqa: BLE001 - invalidate races with teardown
            pass

    # -- driving turns -----------------------------------------------------

    def _submit(self, text: str) -> None:
        """Handle a submitted line: echo it, then run it off the UI thread."""
        chat = self.chat
        stripped = text.strip()
        # Approval answers and the numbered model picker are instant and must
        # not queue behind a running turn.
        instant = (chat._approval_event is not None
                   or (chat._pending_models is not None and not stripped.startswith("/")))
        if chat.busy and not instant:
            chat._note("still working — Ctrl+C cancels the current turn")
            return

        chat.echo_user(stripped)
        if instant:
            self._dispatch(stripped)
            return
        self._worker = threading.Thread(target=self._dispatch, args=(stripped,),
                                        name="tui-turn", daemon=True)
        self._worker.start()

    def _dispatch(self, text: str) -> None:
        try:
            self.chat.handle_text(text)
        except _Quit:
            self._quit()
        except Exception as exc:  # noqa: BLE001 - keep the session alive
            logger.warning("[tui] input failed: %s", exc, exc_info=True)
            self.chat._error(f"Something went wrong: {exc}")
        finally:
            self._invalidate()

    def _quit(self) -> None:
        self._exiting = True
        try:
            if self.app is not None:
                self.app.exit()
        except Exception:  # noqa: BLE001
            pass

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> None:
        """Show the banner, then run the event loop until the user exits."""
        from prompt_toolkit.patch_stdout import patch_stdout

        app = self._build()
        banner.print_banner(self.chat.service, self.chat._session_id,
                            console=self.chat._console)
        self.chat.write(theme.styled(
            "Type a message, /help for commands, Ctrl+D to exit.", "banner_dim"))
        try:
            with patch_stdout(raw=True):
                app.run()
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            self._farewell()

    def _farewell(self) -> None:
        chat = self.chat
        chat.write()
        if chat._session_id:
            chat.write(theme.styled(
                f"Session {chat._session_id} — resume it with "
                f"`namma --resume {chat._session_id[:8]}`", "banner_dim"))
        chat.write(theme.styled("Bye.", "banner_dim"))


# ── Support ────────────────────────────────────────────────────────────

def _slash_completer():
    """Completer for ``/commands`` at the start of the input, and nothing else.

    Built here rather than at module scope because it must subclass
    prompt_toolkit's ``Completer`` (which supplies ``get_completions_async``),
    and prompt_toolkit is imported lazily so the rest of this package stays
    importable without it.
    """
    from prompt_toolkit.completion import Completer, Completion

    class SlashCompleter(Completer):
        def get_completions(self, document, complete_event):
            text = document.text_before_cursor
            if not text.startswith("/") or "\n" in text or text.endswith(" "):
                return
            word = text.split()[0]
            for cmd, blurb in TUI_COMMANDS.items():
                if cmd.startswith(word):
                    yield Completion(cmd, start_position=-len(word), display=cmd,
                                     display_meta=blurb)

    return SlashCompleter()


def _style_dict() -> dict[str, str]:
    """prompt_toolkit style rules built from the active skin."""
    skin = theme.get_active_skin()
    bg = skin.get_color("chrome_bg")
    bg_prefix = f"bg:{bg} " if bg else ""
    return {
        # Empty strings inherit the terminal's own colors, which keeps typed
        # text readable on both light and dark backgrounds.
        "input-area": "",
        "prompt": "",
        "prompt-working": f"{skin.get_color('hint')} italic",
        "input-rule": skin.get_color("input_rule"),
        "status-bar": f"{bg_prefix}{skin.get_color('chrome_fg')}",
        "status-bar-strong": f"{bg_prefix}{skin.get_color('chrome_strong')} bold",
        "status-bar-dim": f"{bg_prefix}{skin.get_color('chrome_dim')}",
        "status-bar-good": f"{bg_prefix}{skin.get_color('good')} bold",
        "status-bar-warn": f"{bg_prefix}{skin.get_color('warn')} bold",
        "status-bar-bad": f"{bg_prefix}{skin.get_color('bad')} bold",
        "status-bar-yolo": f"{bg_prefix}{skin.get_color('danger')} bold",
        "completion-menu.completion": f"{bg_prefix}{skin.get_color('banner_text')}",
        "completion-menu.completion.current":
            f"bg:{skin.get_color('chrome_sel_bg')} {skin.get_color('chrome_strong')}",
        "completion-menu.meta.completion": f"{bg_prefix}{skin.get_color('hint')}",
        "completion-menu.meta.completion.current":
            f"bg:{skin.get_color('chrome_sel_bg')} {skin.get_color('banner_accent')}",
    }


def _history():
    """Persistent input history, shared with the plain console channel."""
    from prompt_toolkit.history import FileHistory, InMemoryHistory

    try:
        path = os.path.expanduser("~/.namma_agent/tui_history")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        return FileHistory(path)
    except OSError as exc:
        logger.debug("[tui] history unavailable (%s) — using memory", exc)
        return InMemoryHistory()


def _console():
    """A rich console that resolves ``sys.stdout`` lazily, so ``patch_stdout``
    can redirect writes above the live chrome after the console is built."""
    from rich.console import Console

    return Console(soft_wrap=False, highlight=False, emoji=False)


def _escape(text: str) -> str:
    """Escape rich markup so agent output containing ``[...]`` renders literally."""
    return str(text).replace("[", "\\[")


def _find_session(db, needle: str) -> Optional[dict]:
    """Find a session by full id, id prefix, or title substring."""
    needle = needle.strip().lower()
    rows = db.list_sessions(limit=200) or []
    for row in rows:
        if str(row.get("id", "")).lower() == needle:
            return row
    for row in rows:
        if str(row.get("id", "")).lower().startswith(needle):
            return row
    for row in rows:
        if needle in str(row.get("title") or "").lower():
            return row
    return None


def run(service: Any, *, session_id: Optional[str] = None,
        mode: str = "agent", model_id: Optional[str] = None,
        auto_approve: bool = False) -> None:
    """Launch the TUI against a live service. Blocks until the user exits."""
    from namma_agent.config import assistant_name

    chat = TuiChat(service, name=assistant_name(service.config), mode=mode,
                   model_id=model_id, session_id=session_id,
                   auto_approve=auto_approve)
    TerminalUI(chat).run()
