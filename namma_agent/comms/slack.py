"""Slack channel — outbound webhook + two-way inbound (Socket Mode or webhook).

Outbound (``SlackChannel``) uses an incoming webhook URL — stdlib-only. Env:
  NAMMA_SLACK_WEBHOOK_URL

Inbound has two shapes:
  * ``SlackSocketInbound`` — **Socket Mode**: the app opens a websocket *out* to
    Slack (no public URL needed), so it works on a laptop / behind NAT. This is the
    local-first path. Env:
        NAMMA_SLACK_APP_TOKEN   app-level token (xapp-…) with connections:write
        NAMMA_SLACK_BOT_TOKEN   bot token (xoxb-…) used to post replies
    Enable in: Slack app → Socket Mode (on) + Event Subscriptions → message.* events.
  * ``SlackInbound`` — **HTTP Events API**: Slack POSTs to ``/webhooks/slack``;
    needs the server publicly reachable + a signing secret. Used as a fallback.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import urllib.request
from typing import Callable, Optional

from namma_agent.comms._util import chunk_text
from namma_agent.comms.inbound import InboundBridge
from namma_agent.core.logger import logger

_MAX_CHARS = 3500  # comfortable margin under Slack's block text limits
_API = "https://slack.com/api"


class SlackChannel:
    def __init__(self, webhook_url: Optional[str] = None):
        self._url = webhook_url if webhook_url is not None else os.environ.get(
            "NAMMA_SLACK_WEBHOOK_URL", "")
        self._available = bool(self._url)

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str) -> bool:
        if not self.available or not text:
            return False
        threading.Thread(target=self._send_sync, args=(text,), daemon=True).start()
        return True

    def _send_sync(self, text: str) -> None:
        for chunk in chunk_text(text, _MAX_CHARS):
            try:
                payload = json.dumps({"text": chunk}).encode()
                req = urllib.request.Request(
                    self._url, data=payload,
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                    if resp.status not in (200, 204):
                        logger.warning("[slack] send failed: HTTP %d", resp.status)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[slack] send error: %s", exc)


def extract_texts(payload: dict) -> list[str]:
    """Pull user message text out of a Slack Events API ``event_callback`` payload.

    Ignores anything posted by a bot/webhook (``bot_id`` / ``bot_message``) so our
    own replies don't loop, and message edits/deletions (which carry a subtype)."""
    event = (payload or {}).get("event") or {}
    if event.get("type") != "message":
        return []
    if event.get("bot_id") or event.get("subtype"):
        return []
    text = (event.get("text") or "").strip()
    return [text] if text else []


def verify_signature(signing_secret: str, timestamp: str, signature: str,
                     raw_body: bytes) -> bool:
    """Verify a Slack request signature (v0 HMAC-SHA256 over ``v0:ts:body``)."""
    if not (signing_secret and timestamp and signature):
        return False
    base = f"v0:{timestamp}:".encode() + (raw_body or b"")
    digest = hmac.new(signing_secret.encode(), base, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"v0={digest}", signature)


class SlackInbound(InboundBridge):
    """Webhook-driven Slack bridge. Slack delivers events to the server's
    ``/webhooks/slack`` route, which calls :meth:`handle_text`; replies go back via
    the incoming webhook (to its configured channel)."""

    def __init__(self, channel: SlackChannel,
                 on_message: Callable[..., tuple],
                 get_models: Optional[Callable[[], list]] = None,
                 signing_secret: Optional[str] = None):
        super().__init__(on_message, get_models)
        self._channel = channel
        self._signing_secret = signing_secret if signing_secret is not None else os.environ.get(
            "NAMMA_SLACK_SIGNING_SECRET", "")

    @property
    def available(self) -> bool:
        return self._channel.available

    @property
    def channel_name(self) -> str:
        return "slack"

    @property
    def signing_secret(self) -> str:
        return self._signing_secret

    def _say(self, text: str) -> None:
        self._channel.send(text)


class SlackSocketInbound(InboundBridge):
    """Two-way Slack over **Socket Mode**. Dials a websocket out to Slack (via
    ``apps.connections.open``), acks each event envelope, runs message events
    through the agent, and replies in the same channel with ``chat.postMessage``
    (falling back to the outgoing webhook if no bot token is set). No public URL."""

    def __init__(self, channel: SlackChannel,
                 on_message: Callable[..., tuple],
                 get_models: Optional[Callable[[], list]] = None,
                 app_token: Optional[str] = None, bot_token: Optional[str] = None):
        super().__init__(on_message, get_models)
        self._channel = channel  # outgoing webhook, used as a reply fallback
        self._app_token = app_token if app_token is not None else os.environ.get(
            "NAMMA_SLACK_APP_TOKEN", "")
        self._bot_token = bot_token if bot_token is not None else os.environ.get(
            "NAMMA_SLACK_BOT_TOKEN", "")
        self._reply_channel: Optional[str] = None

    @property
    def available(self) -> bool:
        return bool(self._app_token)

    @property
    def channel_name(self) -> str:
        return "slack"

    # -- transport ---------------------------------------------------------

    def _say(self, text: str) -> None:
        if self._reply_channel and self._bot_token:
            self._post_message(self._reply_channel, text)
        elif self._channel.available:
            self._channel.send(text)

    def _post_message(self, channel: str, text: str) -> None:
        for chunk in chunk_text(text, _MAX_CHARS):
            try:
                req = urllib.request.Request(
                    f"{_API}/chat.postMessage",
                    data=json.dumps({"channel": channel, "text": chunk}).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {self._bot_token}"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                    body = json.load(resp)
                if not body.get("ok"):
                    logger.warning("[slack] postMessage failed: %s", body.get("error"))
            except Exception as exc:  # noqa: BLE001
                logger.warning("[slack] reply error: %s", exc)

    def _open_url(self) -> str:
        req = urllib.request.Request(
            f"{_API}/apps.connections.open", data=b"",
            headers={"Authorization": f"Bearer {self._app_token}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = json.load(resp)
        if not body.get("ok"):
            raise RuntimeError(f"apps.connections.open: {body.get('error')}")
        return body["url"]

    # -- socket loop -------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                url = self._open_url()
                self._listen(url)
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                logger.warning("[slack] socket error: %s; reconnecting in 5s", exc)
                self._stop.wait(5)

    def _listen(self, url: str) -> None:
        from websockets.sync.client import connect

        with connect(url, open_timeout=20, max_size=None) as ws:
            while not self._stop.is_set():
                try:
                    raw = ws.recv(timeout=5.0)
                except TimeoutError:
                    continue
                msg = json.loads(raw)
                typ = msg.get("type")
                env_id = msg.get("envelope_id")
                if env_id:  # ack every envelope immediately so Slack doesn't retry
                    ws.send(json.dumps({"envelope_id": env_id}))
                if typ == "disconnect":  # Slack asks us to reconnect (refresh/timeout)
                    return
                if typ == "events_api":
                    self._on_event(msg.get("payload") or {})

    def _on_event(self, payload: dict) -> None:
        event = (payload or {}).get("event") or {}
        self._reply_channel = event.get("channel")
        for text in extract_texts(payload):
            self.handle_text(text)
