"""FRIDAY v2 entry point.

Boots the FastAPI backend (uvicorn in a background thread) and opens the modern
web GUI in a native desktop window via pywebview. Falls back to opening the
default browser only if no native GUI toolkit can be found.

    python -m friday            # native window
    python -m friday --server   # backend only (use the vite dev server / browser)
"""
from __future__ import annotations

import os
import platform
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

from friday.config import load_config
from friday.core.logger import configure_logging, logger
from friday.service import FridayService

_HOST = "127.0.0.1"
_PORT = int(os.environ.get("PORT", 8000))
_URL = f"http://{_HOST}:{_PORT}"

# Brand window icon — the "sparkle" mark rendered from webui/public/logo.svg.
# We ship a multi-res .ico for Windows and a 256px .png for GTK/Qt so the native
# window + taskbar show the FRIDAY spark, never the stock Python/pywebview icon.
_ASSETS = Path(__file__).resolve().parent / "assets"


def _build_service() -> FridayService:
    # FridayService builds Piper TTS + local STT from config (graceful if absent).
    config = load_config()
    log_cfg = config.get("logging") or {}
    configure_logging(
        level=log_cfg.get("level"),
        log_file=log_cfg.get("file", "logs/friday.log"),
        to_file=bool(log_cfg.get("to_file", True)),
    )
    logger.info("[app] starting FRIDAY v2 (log level=%s)", logger.level and __import__("logging").getLevelName(logger.level))
    return FridayService(config=config)


def _serve(service: FridayService) -> None:
    import uvicorn

    from friday.server.api import create_app

    uvicorn.run(create_app(service), host=_HOST, port=_PORT, log_level="warning")


def _wait_for_server(timeout: float = 30.0) -> bool:
    # Generous so the native window never paints before the backend is reachable
    # (cold first boot — importing providers/playwright — can take >10s).
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
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

        app_id = f"Friday.Assistant.{title}".replace(" ", "")
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


def _launch_window(service: FridayService, server_thread: threading.Thread) -> None:
    """Open the native desktop window; fall back to a browser tab only if no GUI
    toolkit is available at all."""
    from friday.config import assistant_name

    _ensure_linux_gui_backend()

    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        logger.info("[app] pywebview not installed (%s); opening browser", exc)
        return _open_browser(server_thread)

    title = assistant_name(service.config)
    _set_windows_app_id(title)
    icon = _icon_path()

    last_exc: Exception | None = None
    for gui in _gui_order():
        with suppress(Exception):
            webview.windows.clear()  # drop any window from a failed prior attempt
        webview.create_window(
            title, _URL,
            width=1100, height=760, min_size=(720, 560),
            # Match the app's default (light) shell so there's no jarring flash of
            # plain white before React paints. (webui body bg is #faf9f5.)
            background_color="#faf9f5",
        )
        try:
            # private_mode=False keeps a disk cache between launches → faster
            # warm starts and smoother navigation (esp. on Windows/WebView2).
            webview.start(
                _enable_clipboard_access,  # runs once the GUI loop is up
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

    if not _wait_for_server():
        logger.error("[app] backend did not come up in time")

    if server_only:
        logger.info("[app] backend running at %s (server-only mode)", _URL)
        server_thread.join()
        return

    _launch_window(service, server_thread)


if __name__ == "__main__":  # pragma: no cover
    import sys

    main(server_only="--server" in sys.argv)
