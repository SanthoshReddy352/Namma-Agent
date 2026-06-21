"""Namma Agent entry point.

Boots the FastAPI backend (uvicorn in a background thread) and opens the modern
web GUI in a native desktop window via pywebview. Falls back to opening the
default browser only if no native GUI toolkit can be found.

    python -m namma_agent            # native window
    python -m namma_agent --server   # backend only (use the vite dev server / browser)
"""
from __future__ import annotations

import os
import platform
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

from namma_agent.config import load_config
from namma_agent.core.logger import configure_logging, logger
from namma_agent.service import NammaAgentService
from namma_agent.version import __version__

_HOST = "127.0.0.1"
_PORT = int(os.environ.get("PORT", 8000))
_URL = f"http://{_HOST}:{_PORT}"

# Set by _serve() if uvicorn/create_app raises on the background thread, so main()
# can surface the *real* reason instead of a silent "did not come up in time".
_serve_error: BaseException | None = None

# Brand window icon — the "sparkle" mark rendered from webui/public/logo.svg.
# We ship a multi-res .ico for Windows and a 256px .png for GTK/Qt so the native
# window + taskbar show the Namma Agent spark, never the stock Python/pywebview icon.
_ASSETS = Path(__file__).resolve().parent / "assets"


def _build_service() -> NammaAgentService:
    # NammaAgentService builds Piper TTS + local STT from config (graceful if absent).
    config = load_config()
    log_cfg = config.get("logging") or {}
    configure_logging(
        level=log_cfg.get("level"),
        log_file=log_cfg.get("file", "logs/namma_agent.log"),
        to_file=bool(log_cfg.get("to_file", True)),
    )
    logger.info("[app] starting Namma Agent v%s (log level=%s)", __version__, logger.level and __import__("logging").getLevelName(logger.level))
    return NammaAgentService(config=config)


def _serve(service: NammaAgentService) -> None:
    # Runs on a daemon thread. ANY exception here (a bad import in create_app, a
    # port already in use, a uvicorn failure) would otherwise die silently and the
    # only symptom would be the window's "127.0.0.1 refused to connect" page. Catch
    # it, log the full traceback, and record it so main() can report the real cause.
    global _serve_error
    try:
        import uvicorn

        from namma_agent.server.api import create_app

        uvicorn.run(create_app(service), host=_HOST, port=_PORT, log_level="warning")
    except BaseException as exc:  # noqa: BLE001 — surface every startup failure
        _serve_error = exc
        logger.exception("[app] backend failed to start")


def _wait_for_server(timeout: float = 60.0) -> bool:
    # Generous so the native window never paints before the backend is reachable
    # (cold first boot — importing providers/playwright — can take >10s). Bails out
    # early if the server thread already crashed.
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        if _serve_error is not None:
            return False
        with suppress(Exception):
            urllib.request.urlopen(f"{_URL}/api/health", timeout=1)
            return True
        time.sleep(0.2)
    return False


def _icon_path() -> str | None:
    """Absolute path to the sparkle icon for the current platform, or None."""
    name = "sparkle.ico" if os.name == "nt" else "sparkle.png"
    candidate = _ASSETS / name
    return str(candidate) if candidate.exists() else None


def _ensure_linux_gui_backend() -> None:
    """Make a native GUI toolkit importable on Linux.

    pywebview needs GTK (PyGObject + WebKit2) or Qt. A project venv created
    *without* ``--system-site-packages`` can't see the distro's PyGObject, so
    pywebview finds no backend and we'd silently fall back to a browser tab —
    exactly the "it opens in Chrome" symptom on Kali. The distro ships PyGObject
    + WebKit2 system-wide, so if the system interpreter is ABI-compatible (same
    major.minor as ours), splice its site dir onto ``sys.path`` and the native
    GTK window works with zero extra installs.
    """
    if platform.system() != "Linux":
        return
    with suppress(Exception):
        import gi  # noqa: F401  (already importable — nothing to do)
        return

    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    candidates = [
        "/usr/lib/python3/dist-packages",          # Debian/Kali/Ubuntu
        f"/usr/lib/python{ver}/site-packages",      # Arch/Fedora
        f"/usr/lib64/python{ver}/site-packages",    # Fedora (64-bit)
        f"/usr/local/lib/python{ver}/dist-packages",
    ]
    for d in candidates:
        if not (Path(d) / "gi").is_dir() or d in sys.path:
            continue
        sys.path.append(d)
        try:
            import gi  # noqa: F811
            gi.require_version("Gtk", "3.0")  # forces the C extension to load
            logger.info("[app] bridged system PyGObject for native window (%s)", d)
            return
        except Exception as exc:  # noqa: BLE001 — ABI mismatch / partial import
            logger.debug("[app] gi at %s unusable (%s)", d, exc)
            sys.modules.pop("gi", None)
            with suppress(ValueError):
                sys.path.remove(d)


def _set_windows_app_id(title: str) -> None:
    """Tell Windows this process is its own app so the taskbar shows our icon
    (grouped under our title) instead of the generic Python interpreter icon."""
    if os.name != "nt":
        return
    with suppress(Exception):
        import ctypes

        app_id = f"NammaAgent.Assistant.{title}".replace(" ", "")
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)


def _gui_order() -> list[str | None]:
    """Preferred pywebview backends for this OS, best first.

    Windows: force EdgeChromium (the modern WebView2 engine). pywebview's silent
    fallback is MSHTML — the legacy IE/Trident engine — which renders our React UI
    slowly and janky; that is the Windows "lag". Linux: native GTK, then Qt.
    """
    system = platform.system()
    if system == "Windows":
        return ["edgechromium", None]
    if system == "Linux":
        return ["gtk", "qt", None]
    return [None]  # macOS — Cocoa/WKWebView is the only/right choice


def _enable_clipboard_access() -> None:
    """Turn on JS clipboard access in the native webview.

    WebKit2GTK — the Linux pywebview backend (and the default on Kali) — ships with
    `javascript-can-access-clipboard` DISABLED. That blocks `document.execCommand`
    copy/cut/paste AND the webview's own Ctrl+C/V/X handling, so copy/paste appears
    completely dead inside the desktop window. We flip it on the moment the native
    WebKit view exists. Best-effort: any failure just leaves the prior behavior, and
    on non-GTK backends this is a quiet no-op.

    Passed as pywebview's ``start(func=…)`` callback, so it runs on a worker thread
    once the GUI loop is up; the actual setting change is marshalled onto the GTK
    main loop via GLib.
    """
    try:
        from gi.repository import GLib, Gtk  # type: ignore
    except Exception:  # noqa: BLE001 — not the GTK backend / PyGObject missing
        return

    # Duck-type the WebKit view: a Gtk.Widget exposes get_settings() too, but only
    # WebKitSettings carries the clipboard property — so this finds the WebView
    # without depending on pywebview internals or the GI type name.
    def _is_webview(widget) -> bool:
        getter = getattr(widget, "get_settings", None)
        if not callable(getter):
            return False
        try:
            s = getter()
            return s is not None and s.find_property("javascript-can-access-clipboard") is not None
        except Exception:  # noqa: BLE001
            return False

    def _collect(widget, out: list) -> None:
        if _is_webview(widget):
            out.append(widget)
        # GTK3 containers expose get_children(); single-child holders, get_child().
        if hasattr(widget, "get_children"):
            with suppress(Exception):
                for child in widget.get_children():
                    _collect(child, out)
        elif hasattr(widget, "get_child"):
            with suppress(Exception):
                child = widget.get_child()
                if child is not None:
                    _collect(child, out)

    def _apply() -> bool:
        try:
            tops = list(Gtk.Window.list_toplevels())
        except Exception:  # noqa: BLE001
            return False  # not GTK3 / no toplevels — stop
        views: list = []
        for top in tops:
            _collect(top, views)
        if not views:
            return True  # window/webview not realized yet — retry
        for wv in views:
            try:
                settings = wv.get_settings()
                # The GObject property is "javascript-can-access-clipboard"; try the
                # "enable-" spelling too in case a WebKit build differs.
                for prop in ("javascript-can-access-clipboard",
                             "enable-javascript-can-access-clipboard"):
                    with suppress(Exception):
                        settings.set_property(prop, True)
                with suppress(Exception):
                    wv.set_settings(settings)
                logger.info("[app] enabled WebKit clipboard access")
            except Exception as exc:  # noqa: BLE001
                logger.debug("[app] clipboard enable failed: %s", exc)
        return False  # done — don't retry

    state = {"tries": 0}

    def _tick() -> bool:
        state["tries"] += 1
        keep_going = _apply()
        return bool(keep_going) and state["tries"] < 25  # ~5s of retries, then give up

    # Schedule on the GTK main loop (thread-safe to call from this worker thread).
    GLib.timeout_add(200, _tick)


def _patch_pywebview_for_windows() -> None:
    """Patch pywebview's WebView2 backend so copy/paste + the right-click menu work
    and the title bar tracks the page title. No-op off Windows / the WinForms backend.

    Two things pywebview does that we undo, both done ON the WebView2 UI thread (so
    there's no cross-thread COM access — that was the InvalidCast crash):

    * It HARD-DISABLES ``AreBrowserAcceleratorKeysEnabled`` (Ctrl+C/V/X/A) and
      ``AreDefaultContextMenusEnabled`` (right-click → Copy) whenever debug is off —
      which is exactly why you can't copy from the desktop window. We flip both back
      on inside ``load_url``, right BEFORE each navigation, so the setting is live for
      the loaded page (no reload needed).
    * It never syncs the document ``<title>`` to the native window title. We
      subscribe to ``DocumentTitleChanged`` so renaming the assistant (the web UI
      updates ``document.title``) updates the title bar live.
    """
    if os.name != "nt":
        return
    try:
        from webview.platforms import edgechromium as ec  # type: ignore
    except Exception:  # noqa: BLE001 — not the WinForms/EdgeChromium backend
        return
    if getattr(ec.EdgeChrome, "_namma_agent_patched", False):
        return

    _orig_load_url = ec.EdgeChrome.load_url

    def load_url(self, url):  # runs on the WebView2 UI thread (the safe place)
        try:
            core = self.webview.CoreWebView2
            if core is not None:
                core.Settings.AreBrowserAcceleratorKeysEnabled = True
                core.Settings.AreDefaultContextMenusEnabled = True
        except Exception as exc:  # noqa: BLE001 — best-effort; still navigate
            logger.debug("[app] webview2 settings enable failed: %s", exc)
        return _orig_load_url(self, url)

    _orig_ready = ec.EdgeChrome.on_webview_ready

    def on_webview_ready(self, sender, args):
        _orig_ready(self, sender, args)
        try:
            if args.IsSuccess:
                core = sender.CoreWebView2

                def _sync_title(_s, _a):
                    try:
                        self.form.Text = core.DocumentTitle
                    except Exception:  # noqa: BLE001
                        pass

                core.DocumentTitleChanged += _sync_title
        except Exception as exc:  # noqa: BLE001
            logger.debug("[app] webview2 title sync setup failed: %s", exc)

    ec.EdgeChrome.load_url = load_url
    ec.EdgeChrome.on_webview_ready = on_webview_ready
    ec.EdgeChrome._namma_agent_patched = True
    logger.info("[app] patched WebView2 for copy/paste + live title")


def _error_html(detail: str) -> str:
    """A friendly in-window page shown when the backend never became reachable —
    so the user sees an explanation + Retry instead of WebView2's raw
    '127.0.0.1 refused to connect' error."""
    safe = (detail or "The local server did not respond.").replace("<", "&lt;")
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<style>
  body{{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
       font-family:Inter,Segoe UI,system-ui,sans-serif;background:#faf9f5;color:#2d2a26}}
  .card{{max-width:520px;text-align:center;padding:40px}}
  h1{{font-size:22px;margin:0 0 10px}} p{{color:#6b6760;line-height:1.6;font-size:14px}}
  code{{display:block;margin-top:14px;padding:12px;background:#efece3;border-radius:10px;
        font-family:Consolas,monospace;font-size:12px;color:#b8623f;word-break:break-word}}
  button{{margin-top:22px;border:0;border-radius:10px;background:#cc785c;color:#fff;
          padding:12px 26px;font-size:15px;font-weight:600;cursor:pointer}}
</style></head><body><div class='card'>
  <h1>Starting up is taking longer than usual</h1>
  <p>The app's local engine didn't respond yet. This can happen on a cold first
     start. Click retry, or relaunch Namma Agent.</p>
  <code>{safe}</code>
  <button onclick="location.href='{_URL}'">Retry</button>
</div></body></html>"""


def _launch_window(service: NammaAgentService, server_thread: threading.Thread,
                   healthy: bool = True) -> None:
    """Open the native desktop window; fall back to a browser tab only if no GUI
    toolkit is available at all. When ``healthy`` is False the window shows a
    friendly error/retry page instead of the backend URL (which would render as a
    'connection refused' error)."""
    from namma_agent.config import assistant_name

    _ensure_linux_gui_backend()

    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        logger.info("[app] pywebview not installed (%s); opening browser", exc)
        return _open_browser(server_thread)

    _patch_pywebview_for_windows()  # copy/paste + live title on WebView2 (no-op elsewhere)

    title = assistant_name(service.config)
    _set_windows_app_id(title)
    icon = _icon_path()

    last_exc: Exception | None = None
    for gui in _gui_order():
        with suppress(Exception):
            webview.windows.clear()  # drop any window from a failed prior attempt
        win_kwargs = dict(
            width=1100, height=760, min_size=(720, 560),
            # Match the app's default (light) shell so there's no jarring flash of
            # plain white before React paints. (webui body bg is #faf9f5.)
            background_color="#faf9f5",
        )
        if healthy:
            webview.create_window(title, _URL, **win_kwargs)
        else:
            detail = f"{type(_serve_error).__name__}: {_serve_error}" if _serve_error else ""
            webview.create_window(title, html=_error_html(detail), **win_kwargs)
        try:
            # private_mode=False keeps a disk cache between launches → faster
            # warm starts and smoother navigation (esp. on Windows/WebView2).
            webview.start(
                _enable_clipboard_access,  # Linux/GTK clipboard once the GUI loop is up
                gui=gui, icon=icon, private_mode=False,
                storage_path=str(_ASSETS.parent / ".webview"),
            )
            return  # window closed cleanly — normal shutdown
        except Exception as exc:  # noqa: BLE001 — backend unavailable; try the next
            last_exc = exc
            logger.info("[app] GUI backend %s unavailable (%s)", gui or "default", exc)

    logger.warning(
        "[app] no native GUI toolkit found (%s). On Linux install one with "
        "`sudo apt install python3-gi gir1.2-webkit2-4.1` (GTK) — opening browser instead.",
        last_exc,
    )
    _open_browser(server_thread)


def _open_browser(server_thread: threading.Thread) -> None:
    import webbrowser

    webbrowser.open(_URL)
    server_thread.join()


def main(server_only: bool = False) -> None:
    service = _build_service()
    server_thread = threading.Thread(target=_serve, args=(service,), daemon=True)
    server_thread.start()

    healthy = _wait_for_server()
    if not healthy:
        if _serve_error is not None:
            logger.error("[app] backend crashed on startup: %s: %s",
                         type(_serve_error).__name__, _serve_error)
        else:
            logger.error("[app] backend did not come up in time")

    if server_only:
        logger.info("[app] backend running at %s (server-only mode)", _URL)
        server_thread.join()
        return

    _launch_window(service, server_thread, healthy=healthy)


if __name__ == "__main__":  # pragma: no cover
    import sys

    if "--setup" in sys.argv:
        # First-run provider configuration (the installers call this).
        from namma_agent.core.setup_wizard import run_wizard
        run_wizard()
        sys.exit(0)
    if "--version" in sys.argv:
        print(f"Namma Agent v{__version__}")
        sys.exit(0)

    main(server_only="--server" in sys.argv)
