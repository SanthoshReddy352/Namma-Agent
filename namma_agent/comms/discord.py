"""Discord channel — outbound webhook + two-way bot (Gateway) inbound.

Outbound (``DiscordChannel``) uses an incoming webhook URL — stdlib-only, no bot
needed. Env: ``NAMMA_DISCORD_WEBHOOK_URL``.

Inbound (``DiscordInbound``) needs a **bot**, because a webhook is send-only and
can never *receive* a message. The bot connects to the Discord Gateway over a
websocket (no public URL required — it dials out, so it works behind NAT / on a
laptop, unlike an HTTP webhook). Env:
  NAMMA_DISCORD_BOT_TOKEN    bot token (Developer Portal → Bot)
  NAMMA_DISCORD_CHANNEL_ID   optional — restrict listening to one channel id

The bot must have the **Message Content Intent** enabled (Developer Portal → Bot →
Privileged Gateway Intents); without it, message text arrives empty.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from typing import Callable, Optional

from namma_agent.comms._util import chunk_text
from namma_agent.comms.inbound import InboundBridge
from namma_agent.core.logger import logger

_API = "https://discord.com/api/v10"
_GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"
# Intents we need: GUILD_MESSAGES (1<<9) | DIRECT_MESSAGES (1<<12) | MESSAGE_CONTENT (1<<15).
_INTENTS = (1 << 9) | (1 << 12) | (1 << 15)


class DiscordChannel:
    def __init__(self, webhook_url: Optional[str] = None):
        self._url = webhook_url if webhook_url is not None else os.environ.get(
            "NAMMA_DISCORD_WEBHOOK_URL", "")
        self._available = bool(self._url)

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str, username: Optional[str] = None) -> bool:
        if not self.available or not text:
            return False
        if not username:
            from namma_agent.config import assistant_name
            username = assistant_name()
        threading.Thread(target=self._send_sync, args=(text, username), daemon=True).start()
        return True

    def _send_sync(self, text: str, username: str) -> None:
        try:
            payload = json.dumps({"content": text[:2000], "username": username}).encode()
            req = urllib.request.Request(
                self._url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                if resp.status not in (200, 204):
                    logger.warning("[discord] send failed: HTTP %d", resp.status)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[discord] send error: %s", exc)


class DiscordInbound(InboundBridge):
    """Two-way Discord via a bot on the Gateway (websocket). Listens for messages
    (optionally restricted to one channel), runs each through the agent, and replies
    in the same channel via the bot REST API. Local-first: the bot dials out, so no
    public URL is needed."""

    def __init__(self, channel: Optional[DiscordChannel],
                 on_message: Callable[..., tuple],
                 get_models: Optional[Callable[[], list]] = None,
                 bot_token: Optional[str] = None, channel_id: Optional[str] = None):
        super().__init__(on_message, get_models)
        self._token = bot_token if bot_token is not None else os.environ.get(
            "NAMMA_DISCORD_BOT_TOKEN", "")
        self._channel_id = str(channel_id if channel_id is not None else os.environ.get(
            "NAMMA_DISCORD_CHANNEL_ID", "")).strip()
        self._fallback = channel            # outbound webhook, used if we can't REST-reply
        self._seq: Optional[int] = None     # last sequence number (for heartbeats)
        self._bot_user_id: Optional[str] = None
        self._reply_channel: Optional[str] = None  # channel of the last inbound message
        self._warned_empty = False

    @property
    def available(self) -> bool:
        return bool(self._token)

    @property
    def channel_name(self) -> str:
        return "discord"

    # -- transport ---------------------------------------------------------

    def _say(self, text: str) -> None:
        cid = self._reply_channel or self._channel_id
        if cid and self._token:
            self._rest_send(cid, text)
        elif self._fallback is not None and self._fallback.available:
            self._fallback.send(text)

    def _rest_send(self, channel_id: str, text: str) -> None:
        for chunk in chunk_text(text, 1900):  # Discord hard-limits messages to 2000 chars
            try:
                req = urllib.request.Request(
                    f"{_API}/channels/{channel_id}/messages",
                    data=json.dumps({"content": chunk}).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bot {self._token}"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                    if resp.status not in (200, 201):
                        logger.warning("[discord] reply failed: HTTP %d", resp.status)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[discord] reply error: %s", exc)

    # -- gateway loop ------------------------------------------------------

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect_and_listen()
            except Exception as exc:  # noqa: BLE001
                if self._stop.is_set():
                    break
                logger.warning("[discord] gateway error: %s; reconnecting in 5s", exc)
                self._stop.wait(5)

    def _connect_and_listen(self) -> None:
        from websockets.sync.client import connect

        with connect(_GATEWAY, open_timeout=20, max_size=None) as ws:
            hello = json.loads(ws.recv(timeout=20))
            interval = float((hello.get("d") or {}).get("heartbeat_interval", 41250)) / 1000.0
            ws.send(json.dumps({
                "op": 2,  # IDENTIFY
                "d": {
                    "token": self._token,
                    "intents": _INTENTS,
                    "properties": {"os": "namma", "browser": "namma", "device": "namma"},
                },
            }))
            # Single-threaded heartbeat+receive: never call send from two threads.
            next_hb = time.monotonic() + interval
            while not self._stop.is_set():
                if time.monotonic() >= next_hb:
                    ws.send(json.dumps({"op": 1, "d": self._seq}))
                    next_hb = time.monotonic() + interval
                try:
                    raw = ws.recv(timeout=1.0)
                except TimeoutError:
                    continue
                data = json.loads(raw)
                if data.get("s") is not None:
                    self._seq = data["s"]
                op = data.get("op")
                if op == 0:               # DISPATCH
                    self._dispatch(data)
                elif op == 1:             # server requested a heartbeat
                    ws.send(json.dumps({"op": 1, "d": self._seq}))
                    next_hb = time.monotonic() + interval
                elif op in (7, 9):        # RECONNECT / INVALID SESSION → reconnect fresh
                    return

    def _dispatch(self, data: dict) -> None:
        t = data.get("t")
        d = data.get("d") or {}
        if t == "READY":
            self._bot_user_id = (d.get("user") or {}).get("id")
            logger.info("[discord] connected as %s", (d.get("user") or {}).get("username", "?"))
            return
        if t != "MESSAGE_CREATE":
            return
        author = d.get("author") or {}
        if author.get("bot") or author.get("id") == self._bot_user_id:
            return  # ignore other bots and our own messages (prevents loops)
        cid = str(d.get("channel_id") or "")
        if self._channel_id and cid != self._channel_id:
            return  # only listen in the configured channel, when one is set
        text = (d.get("content") or "").strip()
        if not text:
            if not self._warned_empty:
                logger.warning("[discord] empty message content — enable the Message "
                               "Content Intent in the Developer Portal (Bot → Privileged "
                               "Gateway Intents)")
                self._warned_empty = True
            return
        self._reply_channel = cid
        self.handle_text(text)
