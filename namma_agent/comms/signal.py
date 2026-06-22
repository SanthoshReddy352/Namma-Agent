"""Signal channel — outbound notifications via a signal-cli REST API.

Stdlib-only (urllib). Signal has no official HTTP API, so the standard approach
(the one Hermes uses too) is to run the small open-source ``signal-cli-rest-api``
service and POST to it. Env-gated — all three must be set:
  NAMMA_SIGNAL_API_URL    base url of the signal-cli REST service, e.g. http://localhost:8080
  NAMMA_SIGNAL_NUMBER     the registered sender number in E.164, e.g. +919876543210
  NAMMA_SIGNAL_RECIPIENT  recipient number (E.164) or a group id

Run the service with, e.g.:
  docker run -p 8080:8080 -v $HOME/.local/share/signal-cli:/home/.local/share/signal-cli \
    -e MODE=native bbernhard/signal-cli-rest-api
then register/link the sender number once before sending.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Callable, Optional

from namma_agent.comms._util import chunk_text
from namma_agent.comms.inbound import InboundBridge
from namma_agent.core.logger import logger

_MAX_CHARS = 3500


class SignalChannel:
    def __init__(self, api_url: Optional[str] = None, number: Optional[str] = None,
                 recipient: Optional[str] = None):
        url = api_url if api_url is not None else os.environ.get("NAMMA_SIGNAL_API_URL", "")
        self._url = url.rstrip("/") if url else ""
        self._number = number if number is not None else os.environ.get("NAMMA_SIGNAL_NUMBER", "")
        self._recipient = recipient if recipient is not None else os.environ.get(
            "NAMMA_SIGNAL_RECIPIENT", "")
        self._available = bool(self._url and self._number and self._recipient)

    @property
    def available(self) -> bool:
        return self._available

    @property
    def api_url(self) -> str:
        return self._url

    @property
    def number(self) -> str:
        return self._number

    def send(self, text: str) -> bool:
        if not self.available or not text:
            return False
        threading.Thread(target=self._send_sync, args=(text,), daemon=True).start()
        return True

    def _send_sync(self, text: str) -> None:
        endpoint = f"{self._url}/v2/send"
        for chunk in chunk_text(text, _MAX_CHARS):
            try:
                body = {
                    "message": chunk,
                    "number": self._number,
                    "recipients": [self._recipient],
                }
                req = urllib.request.Request(
                    endpoint, data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                    if resp.status not in (200, 201):
                        logger.warning("[signal] send failed: HTTP %d", resp.status)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[signal] send error: %s", exc)


class SignalInbound(InboundBridge):
    """Two-way Signal via polling the signal-cli REST API's receive endpoint
    (``GET /v1/receive/{number}``). Fits Namma's local-first, no-public-URL model —
    the same shape as the Telegram poller. Replies go back through the channel."""

    _POLL_SECONDS = 2.0  # gap between receive polls

    def __init__(self, channel: SignalChannel,
                 on_message: Callable[..., tuple],
                 get_models: Optional[Callable[[], list]] = None):
        super().__init__(on_message, get_models)
        self._channel = channel

    @property
    def available(self) -> bool:
        return self._channel.available

    @property
    def channel_name(self) -> str:
        return "signal"

    def _say(self, text: str) -> None:
        self._channel.send(text)

    def _run_loop(self) -> None:
        backoff = self._POLL_SECONDS
        fails = 0  # consecutive receive failures (for throttled, actionable logging)
        while not self._stop.is_set():
            try:
                for text in self._receive():
                    self.handle_text(text)
                if fails:
                    logger.info("[signal] receive recovered after %d failure(s)", fails)
                fails = 0
                backoff = self._POLL_SECONDS
            except Exception as exc:  # noqa: BLE001
                fails += 1
                # Don't spam every 2s: log the 1st failure, then every ~30s of failures.
                if fails == 1 or fails % 15 == 0:
                    logger.warning(
                        "[signal] receive failing (x%d): %s — is signal-cli-rest-api "
                        "running at %s in 'normal' or 'native' mode? (json-rpc mode "
                        "disables /v1/receive polling)",
                        fails, exc, self._channel.api_url or "(unset)")
                backoff = min(backoff * 2, 30)
            self._stop.wait(backoff)

    def _receive(self) -> list[str]:
        """Drain queued messages, returning the plain text of each incoming message."""
        from urllib.parse import quote

        url = f"{self._channel.api_url}/v1/receive/{quote(self._channel.number)}"
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
            data = json.load(resp)
        out: list[str] = []
        for env in data or []:
            envelope = env.get("envelope") if isinstance(env, dict) else None
            if not isinstance(envelope, dict):
                continue
            msg = envelope.get("dataMessage") or {}
            text = (msg.get("message") or "").strip()
            if text:
                out.append(text)
        return out
