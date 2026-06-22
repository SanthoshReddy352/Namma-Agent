"""Console channel — a local CLI chat gateway.

``python -m namma_agent --chat`` drops you into a REPL that talks to the same
agent (same memory, tools, model picker, /commands, !shell) as every other
channel — Hermes's "CLI" channel, the Namma way. No server, no window.

Built on :class:`InboundBridge`, so it shares all the command/turn logic; it only
supplies transport: read a line from stdin, print the reply.
"""
from __future__ import annotations

from typing import Callable, Optional

from namma_agent.comms.inbound import InboundBridge


class ConsoleInbound(InboundBridge):
    def __init__(self, on_message: Callable[..., tuple],
                 get_models: Optional[Callable[[], list]] = None,
                 *, name: str = "Namma Agent",
                 input_fn: Callable[[str], str] = input,
                 output_fn: Callable[[str], None] = print):
        super().__init__(on_message, get_models)
        self._name = name
        self._in = input_fn
        self._out = output_fn

    @property
    def channel_name(self) -> str:
        return "console"

    def _say(self, text: str) -> None:
        self._out(text)

    def run_blocking(self) -> None:
        """Run the REPL on the calling thread until EOF or /quit. Used by --chat."""
        self._out(f"{self._name} — type a message, /help for commands, /quit to exit.")
        while not self._stop.is_set():
            try:
                line = self._in(f"{self._name}> ")
            except (EOFError, KeyboardInterrupt):
                break
            if line is None:
                break
            if line.strip().lower() in ("/quit", "/exit", "/q"):
                break
            self.handle_text(line)
        self._out("Bye.")

    # The base spawns _run_loop on a thread; for the console we prefer a blocking
    # foreground REPL, so start() runs it inline rather than detaching.
    def start(self) -> None:  # pragma: no cover - thin wrapper over run_blocking
        self.run_blocking()
