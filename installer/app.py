"""Modern React installer for Namma Agent (pywebview host + JS bridge).

A single pywebview window loads the bundled React UI (``installer/webui/dist``) and
talks to Python through a ``js_api`` :class:`Bridge`. The bridge runs the real
install logic from :mod:`installer.core` on a worker thread and streams structured
step + log events back to the UI via ``window.evaluate_js`` — so the install runs
silently (no console windows; see ``core._NO_WINDOW``) under a clean stepper.

Screens (all React): Welcome → Progress → Provider → Onboarding → Done.

The window needs a WebView engine: WebView2 on Windows (preinstalled on Win10/11),
WebKitGTK/Qt on Linux, WKWebView on macOS — the same toolkit the app itself uses.
"""
from __future__ import annotations

import json
import os
import platform
import threading
from pathlib import Path
from typing import Optional

from installer import core

# Mirrors namma_agent.core.setup_wizard.PROVIDER_PRESETS — kept local because the
# app package isn't importable until it's installed. (key, label, default_model,
# needs_key, base_url)
PROVIDERS = [
    ("anthropic", "Anthropic (Claude)", "claude-opus-4-8", True, ""),
    ("openai", "OpenAI (GPT)", "gpt-4o", True, ""),
    ("google", "Google (Gemini)", "gemini-2.0-flash", True, ""),
    ("ollama", "Ollama (local, no key)", "llama3.1", False, "http://localhost:11434/v1"),
    ("lmstudio", "LM Studio (local, no key)", "local-model", False, "http://localhost:1234/v1"),
    ("openai_compat", "OpenAI-compatible (custom URL)", "", True, ""),
]
ONBOARDING = [
    ("name", "Your name"),
    ("date_of_birth", "Date of birth (optional)"),
    ("occupation", "What do you do (work / study)"),
    ("location", "Where are you based"),
    ("interests", "A few interests or hobbies"),
]


def _ui_index() -> Path:
    """The built React UI's index.html — bundled next to this file (frozen: in
    <_MEIPASS>/installer_ui), else installer/webui/dist for dev."""
    base = getattr(__import__("sys"), "_MEIPASS", None)
    if base:
        p = Path(base) / "installer_ui" / "index.html"
        if p.exists():
            return p
    return Path(__file__).resolve().parent / "webui" / "dist" / "index.html"


def _version() -> str:
    # Read from the bundled app source when available; else "dev".
    for root in (core.bundled_source(), Path(__file__).resolve().parents[1]):
        if not root:
            continue
        vf = Path(root) / "namma_agent" / "version.py"
        if vf.exists():
            import re
            m = re.search(r'__version__\s*=\s*"([^"]+)"', vf.read_text(encoding="utf-8"))
            if m:
                return m.group(1)
    return "dev"


class Bridge:
    """Exposed to React as ``window.pywebview.api.*``. Returns plain JSON values;
    long-running work runs on a thread and reports via ``_push``."""

    def __init__(self):
        self.window = None  # set by main() after the window is created

    # ── outbound events → JS ────────────────────────────────────────────────
    def _push(self, event: str, payload) -> None:
        if self.window is None:
            return
        try:
            self.window.evaluate_js(
                f"window.__installer && window.__installer.{event} "
                f"&& window.__installer.{event}({json.dumps(payload)})"
            )
        except Exception:  # noqa: BLE001 — UI may be navigating; events are best-effort
            pass

    # ── inbound calls ← JS ──────────────────────────────────────────────────
    def get_defaults(self) -> dict:
        return {
            "version": _version(),
            "os": platform.system(),
            "default_install_dir": str(core.default_install_dir()),
            "providers": [
                {"id": p[0], "label": p[1], "model": p[2], "needs_key": p[3], "base_url": p[4]}
                for p in PROVIDERS
            ],
            "onboarding_fields": [{"key": k, "label": l} for k, l in ONBOARDING],
            "steps": [{"key": k, "label": l, "status": "pending"} for k, l in core.INSTALL_STEPS],
        }

    def choose_dir(self) -> Optional[str]:
        """Native folder picker; returns the chosen parent folder (or None)."""
        if self.window is None:
            return None
        try:
            import webview
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            if res:
                return res[0] if isinstance(res, (list, tuple)) else str(res)
        except Exception:  # noqa: BLE001
            pass
        return None

    def resolve_dir(self, chosen: Optional[str]) -> str:
        return str(core.resolve_install_dir(chosen))

    def start_install(self, install_dir: Optional[str]) -> None:
        """Kick off bootstrap on a worker thread; progress arrives via events."""
        target = core.resolve_install_dir(install_dir)
        reporter = core.StepReporter(
            core.INSTALL_STEPS,
            on_update=lambda steps: self._push("onSteps", steps),
            on_log=lambda line: self._push("onLog", line),
        )

        def work():
            try:
                core.bootstrap(target, reporter)
                self._push("onInstallDone", {"install_dir": str(target)})
            except Exception as exc:  # noqa: BLE001
                self._push("onInstallError", str(exc))

        threading.Thread(target=work, daemon=True).start()

    def save_provider(self, install_dir: str, provider: dict) -> dict:
        try:
            core.write_provider(core.resolve_install_dir(install_dir), provider)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def save_onboarding(self, install_dir: str, answers: dict) -> dict:
        try:
            answers = {k: v for k, v in (answers or {}).items() if (v or "").strip()}
            if answers:
                core.write_onboarding(core.resolve_install_dir(install_dir), answers)
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def verify(self, install_dir: str) -> dict:
        ok = core.verify_launch(core.resolve_install_dir(install_dir))
        return {"ok": bool(ok)}

    def launch(self, install_dir: str) -> dict:
        try:
            core.launch(core.resolve_install_dir(install_dir))
            return {"ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def close(self) -> None:
        if self.window is not None:
            with __import__("contextlib").suppress(Exception):
                self.window.destroy()


def main() -> None:
    import webview

    bridge = Bridge()
    index = _ui_index()
    title = "Namma Agent Installer"

    # On Windows force the modern WebView2 engine (EdgeChromium); MSHTML can't run
    # the React bundle. Other platforms have a single right backend.
    gui = "edgechromium" if os.name == "nt" else None

    assets = core.bundled_source()
    icon = None
    if assets:
        cand = Path(assets) / "namma_agent" / "assets" / ("sparkle.ico" if os.name == "nt" else "sparkle.png")
        icon = str(cand) if cand.exists() else None

    window = webview.create_window(
        title, str(index), js_api=bridge,
        width=980, height=720, min_size=(820, 620),
        background_color="#f5f7fb",
    )
    bridge.window = window
    webview.start(gui=gui, icon=icon, private_mode=False)


if __name__ == "__main__":
    main()
