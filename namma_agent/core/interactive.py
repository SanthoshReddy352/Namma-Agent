"""Per-turn interactive callbacks (askpass) shared with tools.

The ``run_shell`` tool can't reach the WebSocket directly, so the service stashes
an ``askpass(prompt) -> str | None`` callback for the duration of a turn here, and
the tool reads it when a command needs a sudo password. The callback round-trips
to the UI; the returned secret is used once for ``sudo -S`` and never stored,
logged, or shown to the model.
"""
from __future__ import annotations

import contextvars
from typing import Any, Callable, Optional

# The live CommsManager (process-wide, not turn-local). The service registers it
# once so stateless tools — notably send_notification — can reach the *running*
# channels instead of rebuilding them from env. That matters for stateful channels
# like WhatsApp QR, whose connected client lives only in the running gateway.
_COMMS: Any = None


def set_comms(comms: Any) -> None:
    global _COMMS
    _COMMS = comms


def get_comms() -> Any:
    return _COMMS


# Set inside the turn's worker thread; read by run_shell in the same thread.
_ASKPASS: "contextvars.ContextVar[Optional[Callable[[str], Optional[str]]]]" = (
    contextvars.ContextVar("namma_agent_askpass", default=None)
)


def set_askpass(fn: Optional[Callable[[str], Optional[str]]]) -> None:
    _ASKPASS.set(fn)


def get_askpass() -> Optional[Callable[[str], Optional[str]]]:
    return _ASKPASS.get()


# Current session id for the in-flight turn. Lets scope-aware tools (e.g.
# remember_project_note / remember_learning_note) resolve which project or
# learning topic they're writing to without threading it through every call.
_SESSION: "contextvars.ContextVar[Optional[str]]" = (
    contextvars.ContextVar("namma_agent_session", default=None)
)


def set_current_session(session_id: Optional[str]) -> None:
    _SESSION.set(session_id)


def get_current_session() -> Optional[str]:
    return _SESSION.get()


# The Provider driving the in-flight turn — i.e. the model the user picked for
# THIS chat. Set by the service around every turn so tools that spin up their own
# agent (delegate_task / background_task) run the sub-agent on the same working
# brain, instead of the boot-time `provider:` chain, which on a profile-only setup
# holds no credentials at all and made every delegation fail instantly.
_PROVIDER: "contextvars.ContextVar[Any]" = (
    contextvars.ContextVar("namma_agent_provider", default=None)
)


def set_current_provider(provider: Any):
    """Set the turn's provider; returns a token for ``reset_current_provider``."""
    return _PROVIDER.set(provider)


def reset_current_provider(token) -> None:
    _PROVIDER.reset(token)


def get_current_provider() -> Any:
    return _PROVIDER.get()


# Turn-local event sink: lets a tool push a typed event straight to the browser
# (e.g. an interactive quiz card or a "learn this" suggestion). Set per turn by the
# service to the WebSocket sink; None outside a turn / for headless callers.
_EVENT_SINK: "contextvars.ContextVar[Optional[Callable[[str, dict], None]]]" = (
    contextvars.ContextVar("namma_agent_event_sink", default=None)
)


def set_event_sink(fn: Optional[Callable[[str, dict], None]]) -> None:
    _EVENT_SINK.set(fn)


def get_event_sink() -> Optional[Callable[[str, dict], None]]:
    return _EVENT_SINK.get()


def emit_event(event: str, payload: dict) -> None:
    fn = _EVENT_SINK.get()
    if fn:
        fn(event, payload)


# Turn-local progress sink: a comms bridge (Telegram/Signal/…) sets this so the
# agent's intermediate "preamble" lines — the explanation that accompanies each
# tool round — are delivered to the user as separate messages AS THEY HAPPEN,
# instead of being bundled into the final reply. None for the web UI (which already
# streams those tokens live) and outside a turn.
_PROGRESS: "contextvars.ContextVar[Optional[Callable[[str], None]]]" = (
    contextvars.ContextVar("namma_agent_progress", default=None)
)


def set_progress_sink(fn: Optional[Callable[[str], None]]):
    """Set the per-turn progress sink; returns a token to pass to ``reset_progress_sink``."""
    return _PROGRESS.set(fn)


def reset_progress_sink(token) -> None:
    _PROGRESS.reset(token)


def get_progress_sink() -> Optional[Callable[[str], None]]:
    return _PROGRESS.get()


# Turn-local artifact recorder: media tools call this so generated diagrams/images/
# simulations are tracked against the active learning topic. No-op when unset.
_ARTIFACT_REC: "contextvars.ContextVar[Optional[Callable[[str, str, str], None]]]" = (
    contextvars.ContextVar("namma_agent_artifact_rec", default=None)
)


def set_artifact_recorder(fn: Optional[Callable[[str, str, str], None]]) -> None:
    _ARTIFACT_REC.set(fn)


def record_artifact(kind: str, url: str, title: str = "") -> None:
    fn = _ARTIFACT_REC.get()
    if fn:
        fn(kind, url, title)
