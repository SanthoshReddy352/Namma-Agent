"""Lifecycle hooks (Phase 7e) — user code that runs around the agent's actions.

Namma already loads user-authored *tools* from ``~/.namma_agent/tools/*.py``
(see ``tools/authoring.py``). This is the other extension point: small Python
modules in ``~/.namma_agent/hooks/*.py`` that get told when things happen and
can, in one case, say no.

A hook module defines any subset of these functions — anything it doesn't
define is simply not called::

    def pre_tool(name, args):
        '''Runs BEFORE a tool. Return a string to VETO it (the string is the
        reason the model and the user see); return None to allow.'''

    def post_tool(name, args, result):
        '''Runs after a tool. `result` is the ToolResult. Return value ignored.'''

    def post_turn(session_id, user_text, reply):
        '''Runs after a completed turn.'''

    def on_approval(name, args, approved):
        '''Runs when a destructive tool was approved or declined.'''

**Design rules, and why.**

*Hooks never break the agent.* Every call is wrapped: an exception is logged and
swallowed. A typo in a personal automation script must not take down the
assistant mid-turn.

*Only ``pre_tool`` can change behaviour*, and only by refusing. Letting hooks
rewrite arguments or fake results would make the audit trail lie about what ran.

*They are visible.* Loaded hooks are listed in the Security tab: this is
user-supplied code running in-process with the agent's privileges, so it must
never be invisible — even though the user put it there themselves.

*Zero cost when unused.* No hooks directory, no work: the dispatcher
short-circuits on an empty list, so the overwhelmingly common case pays nothing.
"""
from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from namma_agent.core.logger import logger

HOOKS_DIR = Path("~/.namma_agent/hooks").expanduser()

#: The events a hook module may implement.
HOOK_NAMES = ("pre_tool", "post_tool", "post_turn", "on_approval")


@dataclass
class LoadedHook:
    name: str                    # the module's file stem
    path: str
    events: list[str] = field(default_factory=list)
    fns: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {"name": self.name, "path": self.path, "events": list(self.events)}


class HookRegistry:
    """Holds the loaded hook modules and dispatches events to them."""

    def __init__(self):
        self._hooks: list[LoadedHook] = []
        self._errors: list[dict] = []

    # -- loading -----------------------------------------------------------

    def load(self, directory: Optional[Path] = None) -> int:
        """Import every ``*.py`` in the hooks directory. A module that fails to
        import is skipped and recorded — never fatal."""
        directory = Path(directory) if directory else HOOKS_DIR
        self._hooks = []
        self._errors = []
        if not directory.is_dir():
            return 0
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                self._load_one(path)
            except Exception as exc:  # noqa: BLE001 — a bad hook is skipped
                logger.warning("[hooks] failed to load %s: %s", path.name, exc)
                self._errors.append({"name": path.stem, "error": str(exc)})
        if self._hooks:
            logger.info("[hooks] loaded %d hook module(s): %s", len(self._hooks),
                        ", ".join(h.name for h in self._hooks))
        return len(self._hooks)

    def _load_one(self, path: Path) -> None:
        spec = importlib.util.spec_from_file_location(
            f"namma_agent_user_hooks.{path.stem}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        hook = LoadedHook(name=path.stem, path=str(path))
        for event in HOOK_NAMES:
            fn = getattr(module, event, None)
            if callable(fn):
                hook.events.append(event)
                hook.fns[event] = fn
        if not hook.events:
            # A module with none of the four functions is almost certainly a
            # mistake — say so rather than loading it silently as a no-op.
            raise RuntimeError(
                f"defines none of {', '.join(HOOK_NAMES)} — nothing to hook")
        self._hooks.append(hook)

    # -- introspection -----------------------------------------------------

    def __len__(self) -> int:
        return len(self._hooks)

    def loaded(self) -> list[dict]:
        return [h.summary() for h in self._hooks]

    def errors(self) -> list[dict]:
        return list(self._errors)

    def status(self) -> dict:
        return {"count": len(self._hooks), "dir": str(HOOKS_DIR),
                "hooks": self.loaded(), "errors": self.errors()}

    # -- dispatch ----------------------------------------------------------

    def _call(self, event: str, *args) -> list[Any]:
        if not self._hooks:
            return []                      # the common case pays nothing
        out = []
        for hook in self._hooks:
            fn: Optional[Callable] = hook.fns.get(event)
            if fn is None:
                continue
            try:
                out.append(fn(*args))
            except Exception as exc:  # noqa: BLE001 — a hook never breaks a turn
                logger.warning("[hooks] %s.%s raised: %s", hook.name, event, exc)
                out.append(None)
        return out

    def pre_tool(self, name: str, args: dict) -> str:
        """Returns a veto reason, or "" to allow. The FIRST veto wins — later
        hooks aren't consulted once the call is already refused."""
        if not self._hooks:
            return ""
        for hook in self._hooks:
            fn = hook.fns.get("pre_tool")
            if fn is None:
                continue
            try:
                verdict = fn(name, args)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[hooks] %s.pre_tool raised: %s", hook.name, exc)
                continue
            if isinstance(verdict, str) and verdict.strip():
                logger.info("[hooks] %s vetoed %s: %s", hook.name, name, verdict)
                return f"blocked by your '{hook.name}' hook: {verdict.strip()}"
        return ""

    def post_tool(self, name: str, args: dict, result: Any) -> None:
        self._call("post_tool", name, args, result)

    def post_turn(self, session_id: str, user_text: str, reply: str) -> None:
        self._call("post_turn", session_id, user_text, reply)

    def on_approval(self, name: str, args: dict, approved: bool) -> None:
        self._call("on_approval", name, args, approved)


# -- the process-wide registry (service-configured at boot) ------------------

_REGISTRY = HookRegistry()


def registry() -> HookRegistry:
    return _REGISTRY


def load_hooks(directory: Optional[Path] = None) -> int:
    return _REGISTRY.load(directory)


def status() -> dict:
    return _REGISTRY.status()
