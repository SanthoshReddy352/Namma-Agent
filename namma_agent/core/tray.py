"""System tray icon (Phase 5 — Windows first-class polish).

A small always-there presence: show/hide the desktop window, see at a glance
whether the messaging gateway is listening (● running / ○ stopped), open the
web UI in a browser, quit cleanly.

Built on **pystray** (the library the plan names) with the icon image loaded
via Pillow — both optional: if either is missing, ``start_tray`` returns None
and the app runs exactly as before. The tray must never be the reason the app
can't start.

Testability: the pystray module is injectable (``_pystray=``), so the menu
wiring is covered by the offline suite without a real system tray.
"""
from __future__ import annotations

import webbrowser
from typing import Callable, Optional

from namma_agent.core.logger import logger


class TrayHandle:
    """What the launcher holds: stop() tears the icon down."""

    def __init__(self, icon):
        self._icon = icon

    def stop(self) -> None:
        try:
            self._icon.stop()
        except Exception:  # noqa: BLE001 — teardown is best-effort
            pass


def build_menu(pystray, *, on_toggle: Callable[[], None],
               on_quit: Callable[[], None], url: str,
               status_getter: Optional[Callable[[], dict]] = None):
    """The tray menu. Split from start_tray so tests can drive it headlessly.

    The gateway line is *informational* (disabled): its text is recomputed by
    pystray every time the menu opens, so it's always current with zero polling.
    """

    def gateway_text(_item) -> str:
        try:
            st = status_getter() if status_getter else {}
        except Exception:  # noqa: BLE001
            st = {}
        if not st.get("configured"):
            return "○ Gateway: not configured"
        return "● Gateway: running" if st.get("running") else "○ Gateway: stopped"

    return pystray.Menu(
        pystray.MenuItem("Show / hide window", lambda: on_toggle(), default=True),
        pystray.MenuItem(gateway_text, None, enabled=False),
        pystray.MenuItem("Open in browser", lambda: webbrowser.open(url)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda: on_quit()),
    )


def start_tray(*, title: str, url: str, icon_path: Optional[str],
               on_toggle: Callable[[], None], on_quit: Callable[[], None],
               status_getter: Optional[Callable[[], dict]] = None,
               _pystray=None) -> Optional[TrayHandle]:
    """Start the tray icon on its own thread. Returns None (logged, not raised)
    when pystray/Pillow or an icon image isn't available."""
    try:
        pystray = _pystray
        if pystray is None:
            import pystray  # type: ignore  # noqa: F811
        from PIL import Image
    except Exception as exc:  # noqa: BLE001
        logger.info("[tray] no tray icon (%s) — running without one", exc)
        return None
    try:
        if not icon_path:
            raise FileNotFoundError("no icon asset")
        image = Image.open(icon_path)
        menu = build_menu(pystray, on_toggle=on_toggle, on_quit=on_quit,
                          url=url, status_getter=status_getter)
        icon = pystray.Icon("namma-agent", image, title, menu)
        icon.run_detached()
        logger.info("[tray] tray icon started")
        return TrayHandle(icon)
    except Exception as exc:  # noqa: BLE001 — a tray failure must never block launch
        logger.info("[tray] tray icon unavailable (%s)", exc)
        return None
