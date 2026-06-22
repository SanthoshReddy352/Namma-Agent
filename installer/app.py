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
import subprocess
import threading
import time
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
    # Read from the bundled app source when available; else "dev". Never raises — a
    # version-read hiccup must not break get_defaults (which would blank the whole
    # Welcome screen, not just the version line).
    import re
    from contextlib import suppress
    for root in (core.bundled_source(), Path(__file__).resolve().parents[1]):
        if not root:
            continue
        with suppress(Exception):
            vf = Path(root) / "namma_agent" / "version.py"
            if vf.exists():
                m = re.search(r'__version__\s*=\s*"([^"]+)"', vf.read_text(encoding="utf-8"))
                if m:
                    return m.group(1)
    return "dev"


def _windows_folder_dialog(start: str) -> Optional[str]:
    """Show a Windows folder picker in a separate (console-less) PowerShell process
    and return the chosen path, or None if cancelled. Runs out-of-process so it can
    never block the installer's WebView2 UI thread."""
    start_q = (start or "").replace("'", "''")
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$f=New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$f.Description='Choose where to install Namma Agent';"
        "$f.ShowNewFolderButton=$true;"
        f"$f.SelectedPath='{start_q}';"
        "if($f.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
        "{[Console]::Out.Write($f.SelectedPath)}"
    )
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", ps],
            capture_output=True, text=True, timeout=600,
            creationflags=core._NO_WINDOW, startupinfo=core._startupinfo(),
        )
        path = (out.stdout or "").strip()
        return path or None
    except Exception:  # noqa: BLE001
        return None


class Bridge:
    """Exposed to React as ``window.pywebview.api.*``. Returns plain JSON values;
    long-running work runs on a thread and reports via ``_push``."""

    def __init__(self):
        self.window = None  # set by main() after the window is created
        # Progress events are COALESCED through a single timed flusher. Each
        # window.evaluate_js() is a synchronous round-trip marshalled onto the
        # WebView2 UI thread; firing one per log line / step update floods that
        # thread and Windows shows the window as "not responding" until it drains.
        # Batching to ~5 Hz keeps the message pump responsive throughout the install.
        self._lock = threading.Lock()
        self._pending_steps = None   # latest snapshot wins (intermediates droppable)
        self._pending_logs: list[str] = []
        self._flusher_on = False
        self._stop = False

    # ── outbound events → JS ────────────────────────────────────────────────
    def _evaluate(self, event: str, payload) -> None:
        """One marshalled call into the page. Best-effort (UI may be navigating)."""
        if self.window is None:
            return
        try:
            self.window.evaluate_js(
                f"window.__installer && window.__installer.{event} "
                f"&& window.__installer.{event}({json.dumps(payload)})"
            )
        except Exception:  # noqa: BLE001
            pass

    def _ensure_flusher(self) -> None:
        if self._flusher_on:
            return
        self._flusher_on = True
        threading.Thread(target=self._flush_loop, daemon=True).start()

    def _flush_loop(self) -> None:
        while not self._stop:
            time.sleep(0.2)
            self._flush()

    def _flush(self) -> None:
        with self._lock:
            steps, logs = self._pending_steps, self._pending_logs
            self._pending_steps, self._pending_logs = None, []
        if steps is not None:
            self._evaluate("onSteps", steps)
        if logs:
            self._evaluate("onLog", logs)  # batched array → React appends all

    def _queue_steps(self, steps) -> None:
        with self._lock:
            self._pending_steps = steps
        self._ensure_flusher()

    def _queue_log(self, line: str) -> None:
        with self._lock:
            self._pending_logs.append(line)
        self._ensure_flusher()

    def _push_now(self, event: str, payload) -> None:
        """Flush any backlog, then deliver a terminal event immediately."""
        self._flush()
        self._evaluate(event, payload)

    # ── inbound calls ← JS ──────────────────────────────────────────────────
    def get_defaults(self) -> dict:
        # Each field is computed defensively: this call is awaited by the Welcome
        # screen, so a single slow/failing piece must never blank the whole payload
        # (which would leave the provider/onboarding screens empty too).
        try:
            install_dir = str(core.default_install_dir())
        except Exception:  # noqa: BLE001
            install_dir = str(Path.home() / core.APP_DIR_NAME)
        return {
            "version": _version(),
            "os": platform.system(),
            "default_install_dir": install_dir,
            "providers": [
                {"id": p[0], "label": p[1], "model": p[2], "needs_key": p[3], "base_url": p[4]}
                for p in PROVIDERS
            ],
            "onboarding_fields": [{"key": k, "label": l} for k, l in ONBOARDING],
            "steps": [{"key": k, "label": l, "status": "pending"} for k, l in core.INSTALL_STEPS],
        }

    def choose_dir(self) -> Optional[str]:
        """Native folder picker. Returns the chosen folder (or None).

        On Windows the dialog runs in a SEPARATE PowerShell process, NOT via
        pywebview's create_file_dialog — that one runs the modal dialog on the
        WebView2 UI thread, which freezes the window ("not responding") the whole
        time it's open. A separate process can never block our UI thread.
        """
        if os.name == "nt":
            return _windows_folder_dialog(str(core.default_install_dir().parent))
        # macOS/Linux: pywebview's native dialog (no UI-thread freeze observed there).
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
        self._stop = False
        reporter = core.StepReporter(
            core.INSTALL_STEPS,
            on_update=self._queue_steps,
            on_log=self._queue_log,
        )

        def work():
            try:
                core.bootstrap(target, reporter)
                self._push_now("onInstallDone", {"install_dir": str(target)})
            except Exception as exc:  # noqa: BLE001
                self._push_now("onInstallError", str(exc))
            finally:
                self._stop = True  # let the flusher thread exit

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


def _centered_geometry(width: int, height: int):
    """Center the installer window on the primary screen, clamped to fit — so it
    never opens half off-screen on smaller / DPI-scaled displays. Returns
    (x, y, width, height); x/y are None if the screen can't be read."""
    try:
        import webview

        screens = webview.screens
        s = screens[0] if screens else None
        if s and s.width and s.height:
            sw, sh = int(s.width), int(s.height)
            width = min(width, int(sw * 0.92))
            height = min(height, int(sh * 0.90))
            return max(0, (sw - width) // 2), max(0, (sh - height) // 2), width, height
    except Exception:  # noqa: BLE001
        pass
    return None, None, width, height


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

    gx, gy, gw, gh = _centered_geometry(980, 720)
    window = webview.create_window(
        title, str(index), js_api=bridge,
        width=gw, height=gh, x=gx, y=gy, min_size=(820, 620),
        background_color="#f5f7fb",
    )
    bridge.window = window
    webview.start(gui=gui, icon=icon, private_mode=False)


if __name__ == "__main__":
    main()
