"""Platform-agnostic inbound chat bridge.

:class:`InboundBridge` owns everything that is the *same* no matter which
messenger a message arrived on: per-chat session id, agent/chat mode, the model
picker, the ``/command`` set, ``!shell`` passthrough, the in-chat sudo askpass,
and running one turn through the agent. Subclasses implement only *transport* —
how messages are received and how a reply is sent back.

Concrete bridges:
  * :class:`~namma_agent.comms.telegram.TelegramInbound` — long-poll getUpdates
  * :class:`~namma_agent.comms.signal.SignalInbound`     — poll signal-cli REST
  * :class:`~namma_agent.comms.console.ConsoleInbound`    — local CLI REPL
  * Slack / WhatsApp are webhook-driven: the server calls :meth:`handle_text`.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

from namma_agent.core.logger import logger

# on_message(text, session_id, mode, askpass, model) -> (reply, session_id)
OnMessage = Callable[..., tuple]


class InboundBridge:
    def __init__(self, on_message: OnMessage,
                 get_models: Optional[Callable[[], list]] = None):
        self._on_message = on_message
        # Returns the configured model profiles (for the /model picker). Optional so
        # callers/tests that don't switch models still work.
        self._get_models = get_models or (lambda: [])
        self._session_id: Optional[str] = None
        self._mode = "agent"
        self._model_id: Optional[str] = None        # chosen brain (None = default)
        self._pending_models: Optional[list] = None  # set while awaiting a number
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Pending sudo-password request (set while a turn waits for a reply).
        self._pw_lock = threading.Lock()
        self._pw_event: Optional[threading.Event] = None
        self._pw_value: Optional[str] = None

    # -- transport hooks (subclasses override) -----------------------------

    @property
    def available(self) -> bool:
        return True

    @property
    def channel_name(self) -> str:
        return "inbound"

    def _say(self, text: str) -> None:
        """Send a plain message back to the user."""
        raise NotImplementedError

    def _reply(self, text: str, ref=None) -> None:
        """Send an answer, optionally referencing the user's message. Default: plain."""
        self._say(text)

    def _run_loop(self) -> None:
        """The receive loop (runs on the bridge's daemon thread). Webhook-driven
        bridges leave this as a no-op and are fed via :meth:`handle_text`."""
        self._stop.wait()

    def _scrub(self, ref) -> None:
        """Delete a message (used to remove a typed password). No-op if unsupported."""

    def _help_text(self) -> str:
        from namma_agent.config import assistant_name
        name = assistant_name()
        return (f"{name} commands:\n"
                "• plain text — I handle it (agent mode by default)\n"
                "• !<cmd> — run a shell command, e.g. !df -h\n"
                "• /mode chat|agent — switch mode\n"
                "• /model — switch the AI model (pick by number)\n"
                "• /new — start a fresh conversation\n"
                "• /clear — wipe my memory\n"
                "• /help — this message")

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if not self.available or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run_loop,
                                        name=f"{type(self).__name__}", daemon=True)
        self._thread.start()
        logger.info("[%s] inbound started", self.channel_name)

    def stop(self) -> None:
        self._stop.set()

    # -- inbound entry -----------------------------------------------------

    def handle_text(self, text: str, ref=None) -> None:
        """Route one inbound text message: password capture → model picker →
        /command → otherwise run it as a turn."""
        text = (text or "").strip()
        if not text:
            return
        if self._pw_event is not None:
            self._capture_password(text, ref)
            return
        if self._pending_models is not None and not text.startswith("/"):
            self._handle_model_selection(text)
            return
        if self._handle_command(text):
            return
        self._process(text, ref)

    # -- commands ----------------------------------------------------------

    def _handle_command(self, text: str) -> bool:
        """Handle /commands locally. Returns True if consumed."""
        low = text.lower()
        if low in ("/start", "/help"):
            self._say(self._help_text())
            return True
        if low == "/new":
            self._session_id = None
            self._say("Started a fresh conversation.")
            return True
        if low == "/mode" or low.startswith("/mode "):
            arg = text[5:].strip().lower()
            if arg in ("chat", "agent"):
                self._mode = arg
                self._say(f"Mode set to {arg}.")
            else:
                self._say(f"Current mode: {self._mode}. Use /mode chat or /mode agent.")
            return True
        if low == "/model":
            self._show_model_menu()
            return True
        if low == "/clear":
            self._run_turn("Clear all of my memory.")
            return True
        return False

    # -- model switching (numbered picker) ---------------------------------

    def _show_model_menu(self) -> None:
        models = list(self._get_models() or [])
        if not models:
            self._say("No models are configured yet. Add some in Settings → Models, "
                      "then use /model to switch.")
            return
        lines = ["Pick a model — reply with its number:", ""]
        for i, m in enumerate(models, start=1):
            current = " ✅ (current)" if m.get("id") == self._model_id else ""
            label = m.get("label") or m.get("model") or m.get("id")
            lines.append(f"{i}. {label}{current}")
        default_mark = " ✅ (current)" if self._model_id is None else ""
        lines.append(f"\n0. Cancel{default_mark}")
        self._pending_models = models
        self._say("\n".join(lines))

    def _handle_model_selection(self, text: str) -> None:
        models = self._pending_models or []
        choice = text.strip()
        if choice.lower() in ("cancel", "stop", "abort"):
            choice = "0"
        if not choice.lstrip("-").isdigit():
            self._say(f"That isn't a number. Reply with 1–{len(models)} to choose, or 0 to cancel.")
            return
        n = int(choice)
        if n == 0:
            self._pending_models = None
            self._say("Okay — keeping the current model.")
            return
        if not 1 <= n <= len(models):
            self._say(f"{n} isn't on the list. Reply with a number from 1 to {len(models)}, or 0 to cancel.")
            return
        chosen = models[n - 1]
        self._pending_models = None
        self._model_id = chosen.get("id")
        self._session_id = None  # switching the brain starts a fresh conversation
        label = chosen.get("label") or chosen.get("model") or chosen.get("id")
        self._say(f"✅ Switched to {label}. Started a fresh conversation.")

    # -- sudo askpass (in-chat) --------------------------------------------

    def askpass(self, prompt: str) -> Optional[str]:
        """Ask for the sudo password in chat and wait for the reply (one at a time).
        The reply is captured, scrubbed where supported, and returned — never logged."""
        ev = threading.Event()
        with self._pw_lock:
            if self._pw_event is not None:
                return None
            self._pw_event, self._pw_value = ev, None
        self._say(f"🔒 {prompt}\nReply with your sudo password — I'll delete it right after.")
        got = ev.wait(timeout=120)
        with self._pw_lock:
            value, self._pw_event, self._pw_value = self._pw_value, None, None
        return value if got else None

    def _capture_password(self, text: str, ref=None) -> None:
        with self._pw_lock:
            self._pw_value = text
            ev = self._pw_event
        self._scrub(ref)
        if ev:
            ev.set()

    # -- turns -------------------------------------------------------------

    def _execute(self, text: str) -> str:
        """Run one turn through the agent, persisting the session. Returns the reply."""
        try:
            reply, self._session_id = self._on_message(
                text, self._session_id, self._mode, self.askpass, self._model_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] turn failed: %s", self.channel_name, exc)
            reply = "Sorry — something went wrong handling that."
        return reply or "(no response)"

    def _run_turn(self, text: str) -> None:
        """Plain turn → plain reply (used by /commands)."""
        self._say(self._execute(text))

    def _reply_turn(self, text: str, ref=None) -> None:
        """Run a turn and deliver the answer as a reply to the user's message."""
        self._reply(self._execute(text), ref)

    def _process(self, text: str, ref=None) -> None:
        # `!cmd` → run a shell command via the agent's run_shell tool.
        if text.startswith("!"):
            cmd = text[1:].strip()
            self._reply_turn(
                f"Run this shell command with run_shell and show me the output:\n{cmd}", ref)
            return
        self._reply_turn(text, ref)
