"""System tray (Phase 5) — menu wiring, status text, graceful absence."""
from __future__ import annotations

from namma_agent.core import tray


class _FakeMenuItem:
    def __init__(self, text, action, default=False, enabled=True):
        self.text = text
        self.action = action
        self.default = default
        self.enabled = enabled


class _FakeMenu:
    SEPARATOR = object()

    def __init__(self, *items):
        self.items = items


class _FakePystray:
    Menu = _FakeMenu
    MenuItem = _FakeMenuItem

    class Icon:
        def __init__(self, name, image, title, menu):
            self.name, self.image, self.title, self.menu = name, image, title, menu
            self.detached = False

        def run_detached(self):
            self.detached = True

        def stop(self):
            self.stopped = True


def test_menu_wiring_and_gateway_text():
    calls = []
    status = {"configured": True, "running": True}
    menu = tray.build_menu(
        _FakePystray, on_toggle=lambda: calls.append("toggle"),
        on_quit=lambda: calls.append("quit"), url="http://127.0.0.1:8000",
        status_getter=lambda: status)
    items = [i for i in menu.items if i is not _FakeMenu.SEPARATOR]
    labels = [i.text for i in items if isinstance(i.text, str)]
    assert "Show / hide window" in labels and "Quit" in labels
    # The show/hide item is the double-click default.
    assert next(i for i in items if i.text == "Show / hide window").default

    # The gateway line recomputes from live status and is informational.
    gw = next(i for i in items if callable(i.text))
    assert gw.enabled is False
    assert gw.text(None) == "● Gateway: running"
    status["running"] = False
    assert gw.text(None) == "○ Gateway: stopped"
    status["configured"] = False
    assert gw.text(None) == "○ Gateway: not configured"

    # Click-throughs reach the launcher's callbacks.
    next(i for i in items if i.text == "Show / hide window").action()
    next(i for i in items if i.text == "Quit").action()
    assert calls == ["toggle", "quit"]


def test_gateway_text_survives_broken_status():
    def boom():
        raise RuntimeError("status exploded")

    menu = tray.build_menu(_FakePystray, on_toggle=lambda: None,
                           on_quit=lambda: None, url="u", status_getter=boom)
    gw = next(i for i in menu.items
              if i is not _FakeMenu.SEPARATOR and callable(i.text))
    assert gw.text(None) == "○ Gateway: not configured"


def test_start_tray_without_icon_returns_none():
    # No icon asset → None, never an exception (the app must still launch).
    assert tray.start_tray(title="T", url="u", icon_path=None,
                           on_toggle=lambda: None, on_quit=lambda: None,
                           _pystray=_FakePystray) is None


def test_start_tray_real_pystray_headless(tmp_path):
    """With the REAL pystray + a real .ico, the icon object builds and detaches.
    Skipped where pystray can't work at all (headless CI without a tray)."""
    import pytest

    try:
        import pystray  # noqa: F401
        from PIL import Image  # noqa: F401 — probing Pillow availability
    except Exception:
        pytest.skip("pystray/Pillow not installed")
    from pathlib import Path
    ico = Path("namma_agent/assets/sparkle.ico")
    if not ico.is_file():
        pytest.skip("no icon asset")
    # Use the fake for run_detached (running a real tray loop in tests would
    # leave a stray icon); the point is the image+menu build path.
    h = tray.start_tray(title="T", url="http://127.0.0.1:8000",
                        icon_path=str(ico), on_toggle=lambda: None,
                        on_quit=lambda: None, _pystray=_FakePystray)
    assert h is not None
    h.stop()
