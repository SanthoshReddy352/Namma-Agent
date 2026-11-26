"""Per-request token accounting (PROGRESS.md Phase 2).

Every model call — the chat loop's steps AND the background calls nobody used to
count (context compaction, the Engram memory writer, chat titles, session
summaries, the watcher gate, skill capture, the weekly self-review, sub-agents)
— is recorded as one row in the ``usage_log`` table with its input, output,
cache-read and cache-write tokens.

How a call gets recorded without touching every caller:

* :class:`~namma_agent.core.providers.base.Provider` wraps each concrete
  provider's ``generate`` (``__init_subclass__``) so the response's normalized
  usage reaches :func:`record` after every call. Chains don't record — their
  member providers do — and nested calls are recorded once.
* **Attribution** comes from two context variables: the *kind* of work
  (``turn`` / ``compaction`` / ``memory`` / ``title`` / …; default
  ``background``) and the agent-loop *step*. The session id comes from the
  turn's current-session variable. :func:`usage_scope` sets them, and
  :func:`labeled` wraps a provider so every call through it carries a kind —
  the way the service tags the providers it hands to background subsystems.

The sink is a :class:`~namma_agent.core.memory.Database` installed with
:func:`set_sink`; with no sink (bare tests) recording is a no-op.
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Iterator, Optional

from namma_agent.core.logger import logger

#: What kind of work the current model call is for.
_KIND: contextvars.ContextVar[str] = contextvars.ContextVar("namma_usage_kind",
                                                            default="background")
#: The agent-loop step (1-based) of the current call; 0 outside the loop.
_STEP: contextvars.ContextVar[int] = contextvars.ContextVar("namma_usage_step", default=0)
#: True while a metered generate() is running — nested calls aren't re-counted.
_ACTIVE: contextvars.ContextVar[bool] = contextvars.ContextVar("namma_usage_active",
                                                               default=False)

#: Known kinds, in the order the usage panel lists them.
KINDS = ("turn", "delegate", "compaction", "memory", "title", "summary", "watcher",
         "skill_capture", "self_review", "routine", "background")

_sink: Any = None


def set_sink(db: Any) -> None:
    """Install the Database that receives usage rows (``None`` disables)."""
    global _sink
    _sink = db


def get_sink() -> Any:
    return _sink


def current_kind() -> str:
    return _KIND.get()


@contextmanager
def usage_scope(kind: Optional[str] = None, step: Optional[int] = None) -> Iterator[None]:
    """Attribute every model call inside the block to ``kind`` (and ``step``)."""
    tokens = []
    if kind:
        tokens.append((_KIND, _KIND.set(kind)))
    if step is not None:
        tokens.append((_STEP, _STEP.set(int(step))))
    try:
        yield
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)


def set_step(step: int) -> contextvars.Token:
    return _STEP.set(int(step))


def reset_step(token: contextvars.Token) -> None:
    _STEP.reset(token)


def record(provider: Any, resp: Any) -> None:
    """Persist one call's usage. Never raises — accounting must not break a turn."""
    db = _sink
    usage = getattr(resp, "usage", None) or {}
    if db is None or not usage or not hasattr(db, "log_usage"):
        return
    try:
        from namma_agent.core.interactive import get_current_session

        session_id = get_current_session() or ""
    except Exception:  # noqa: BLE001
        session_id = ""
    try:
        db.log_usage(
            kind=_KIND.get(), session_id=session_id, step=_STEP.get(),
            provider=str(getattr(resp, "provider", "") or getattr(provider, "name", "")),
            model=str(getattr(resp, "model", "") or getattr(provider, "model", "") or ""),
            usage=usage)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[usage] record failed: %s", exc)


def metered(generate):
    """Decorator for a provider's ``generate``: record usage once per call."""
    import functools

    @functools.wraps(generate)
    def wrapper(self, *args, **kwargs):
        if _ACTIVE.get():
            return generate(self, *args, **kwargs)
        token = _ACTIVE.set(True)
        try:
            resp = generate(self, *args, **kwargs)
        finally:
            _ACTIVE.reset(token)
        record(self, resp)
        return resp

    wrapper.__namma_metered__ = True  # type: ignore[attr-defined]
    return wrapper


class _LabeledProvider:
    """A provider proxy whose calls are attributed to a fixed usage kind."""

    def __init__(self, provider: Any, kind: str):
        self.__dict__["_inner"] = provider
        self.__dict__["_kind"] = kind

    def generate(self, *args, **kwargs):
        with usage_scope(self._kind):
            return self._inner.generate(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._inner, name, value)


def labeled(provider: Any, kind: str) -> Any:
    """Wrap ``provider`` so every ``generate`` through it is logged as ``kind``.
    ``None`` passes through (callers often hold an optional provider)."""
    if provider is None:
        return None
    if isinstance(provider, _LabeledProvider):
        provider = provider._inner
    return _LabeledProvider(provider, kind)
