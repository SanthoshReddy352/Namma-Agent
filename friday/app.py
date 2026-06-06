"""FRIDAY v2 entry point.

Boots the FastAPI backend (uvicorn in a background thread) and opens the modern
web GUI in a native desktop window via pywebview. Falls back to opening the
default browser if pywebview is unavailable.

    python -m friday            # native window
    python -m friday --server   # backend only (use the vite dev server / browser)
"""
from __future__ import annotations

import threading
import time
from contextlib import suppress

from friday.config import load_config
from friday.core.logger import logger
from friday.service import FridayService

_HOST = "127.0.0.1"
_PORT = 8000
_URL = f"http://{_HOST}:{_PORT}"


def _build_service() -> FridayService:
    config = load_config()
    speak = _make_speak(config)
    return FridayService(config=config, speak=speak)


def _make_speak(config: dict):
    """Wire Piper TTS as the narration/speech sink (Phase 6). No-op if unavailable."""
    if not (config.get("voice") or {}).get("enabled", True):
        return lambda _t: None
    try:
        from friday.voice.tts import PiperTTS

        tts = PiperTTS(config)
        return tts.speak
    except Exception as exc:  # noqa: BLE001
        logger.info("[app] Piper TTS unavailable (%s); narration will be text-only", exc)
        return lambda _t: None


def _serve(service: FridayService) -> None:
    import uvicorn

    from friday.server.api import create_app

    uvicorn.run(create_app(service), host=_HOST, port=_PORT, log_level="warning")


def _wait_for_server(timeout: float = 10.0) -> bool:
    import urllib.request

    deadline = time.time() + timeout
    while time.time() < deadline:
        with suppress(Exception):
            urllib.request.urlopen(f"{_URL}/api/health", timeout=1)
            return True
        time.sleep(0.2)
    return False


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

    try:
        import webview

        webview.create_window("FRIDAY", _URL, width=1100, height=760, min_size=(720, 560))
        webview.start()
    except Exception as exc:  # noqa: BLE001
        logger.info("[app] pywebview unavailable (%s); opening browser", exc)
        import webbrowser

        webbrowser.open(_URL)
        server_thread.join()


if __name__ == "__main__":  # pragma: no cover
    import sys

    main(server_only="--server" in sys.argv)
