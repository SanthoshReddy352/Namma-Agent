"""WhatsApp channel — outbound notifications via the WhatsApp Cloud API.

Stdlib-only (urllib). Uses Meta's Graph API, so no third-party SDK is required.
Env-gated — all three must be set:
  NAMMA_WHATSAPP_TOKEN      access token (Meta app → WhatsApp → API Setup)
  NAMMA_WHATSAPP_PHONE_ID   the sender phone-number id (NOT the phone number)
  NAMMA_WHATSAPP_TO         recipient in E.164 digits, e.g. 919876543210

Note: outside the 24-hour customer-service window the Cloud API only delivers
pre-approved *template* messages; free-form text is for replies/within-window
notifications. The send still returns True (dispatched); delivery is Meta's call.
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

_MAX_CHARS = 4000  # under WhatsApp's ~4096 text body limit
_API = "https://graph.facebook.com/v21.0/{phone_id}/messages"


class WhatsAppChannel:
    def __init__(self, token: Optional[str] = None, phone_id: Optional[str] = None,
                 to: Optional[str] = None):
        self._token = token if token is not None else os.environ.get("NAMMA_WHATSAPP_TOKEN", "")
        self._phone_id = phone_id if phone_id is not None else os.environ.get(
            "NAMMA_WHATSAPP_PHONE_ID", "")
        self._to = to if to is not None else os.environ.get("NAMMA_WHATSAPP_TO", "")
        self._available = bool(self._token and self._phone_id and self._to)

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str) -> bool:
        if not self.available or not text:
            return False
        threading.Thread(target=self._send_sync, args=(text,), daemon=True).start()
        return True

    def _send_sync(self, text: str) -> None:
        url = _API.format(phone_id=self._phone_id)
        for chunk in chunk_text(text, _MAX_CHARS):
            try:
                body = {
                    "messaging_product": "whatsapp",
                    "to": self._to,
                    "type": "text",
                    "text": {"body": chunk, "preview_url": False},
                }
                req = urllib.request.Request(
                    url, data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {self._token}"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                    if resp.status not in (200, 201):
                        logger.warning("[whatsapp] send failed: HTTP %d", resp.status)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[whatsapp] send error: %s", exc)


def extract_texts(payload: dict) -> list[str]:
    """Pull inbound message text out of a WhatsApp Cloud API webhook payload.

    Status callbacks (delivered/read) carry no ``messages`` array and yield nothing.
    Only ``type == 'text'`` messages are surfaced."""
    out: list[str] = []
    for entry in (payload or {}).get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            for msg in value.get("messages", []) or []:
                if msg.get("type") == "text":
                    text = ((msg.get("text") or {}).get("body") or "").strip()
                    if text:
                        out.append(text)
    return out


class WhatsAppInbound(InboundBridge):
    """Webhook-driven WhatsApp bridge. Meta delivers messages to the server's
    ``/webhooks/whatsapp`` route, which calls :meth:`handle_text`; replies go back
    via the Cloud API (to the configured recipient)."""

    def __init__(self, channel: WhatsAppChannel,
                 on_message: Callable[..., tuple],
                 get_models: Optional[Callable[[], list]] = None,
                 verify_token: Optional[str] = None):
        super().__init__(on_message, get_models)
        self._channel = channel
        self._verify_token = verify_token if verify_token is not None else os.environ.get(
            "NAMMA_WHATSAPP_VERIFY_TOKEN", "")

    @property
    def available(self) -> bool:
        return self._channel.available

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    def verify(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Meta's GET webhook handshake: echo the challenge iff the token matches."""
        if mode == "subscribe" and token and token == self._verify_token:
            return challenge
        return None

    def _say(self, text: str) -> None:
        self._channel.send(text)
