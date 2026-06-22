"""CommsManager — owns the messaging channels and the inbound bridge.

Built once by :class:`NammaAgentService`. Outbound: :meth:`broadcast` / :meth:`send`
fan out to every configured channel (Telegram, Discord, Slack, WhatsApp, Signal).
Inbound: :meth:`start_inbound` launches the Telegram poller, routing each message
through the supplied ``on_message(text) -> reply`` callback (the service's turn).
Non-Telegram channels are outbound-only for now (per-platform inbound is a larger,
separate effort).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from namma_agent.comms.discord import DiscordChannel, DiscordInbound
from namma_agent.comms.inbound import InboundBridge
from namma_agent.comms.signal import SignalChannel, SignalInbound
from namma_agent.comms.slack import SlackChannel, SlackInbound, SlackSocketInbound
from namma_agent.comms.telegram import TelegramChannel, TelegramInbound
from namma_agent.comms.whatsapp import WhatsAppChannel, WhatsAppInbound
from namma_agent.core.logger import logger


class CommsManager:
    def __init__(self, telegram: Optional[TelegramChannel] = None,
                 discord: Optional[DiscordChannel] = None,
                 slack: Optional[SlackChannel] = None,
                 whatsapp: Optional[WhatsAppChannel] = None,
                 signal: Optional[SignalChannel] = None):
        self.telegram = telegram or TelegramChannel()
        self.discord = discord or DiscordChannel()
        self.slack = slack or SlackChannel()
        self.whatsapp = whatsapp or WhatsAppChannel()
        self.signal = signal or SignalChannel()
        # Started pollable inbound bridges (Telegram, Signal).
        self._inbound: list[InboundBridge] = []
        # Webhook-driven bridges (Slack, WhatsApp): the server routes requests to them.
        self._webhooks: dict[str, InboundBridge] = {}

    # Channel name → channel object, in a stable order. The single source of truth
    # for routing/listing so adding a channel above is the only edit needed.
    def _channels(self) -> dict:
        return {
            "telegram": self.telegram,
            "discord": self.discord,
            "slack": self.slack,
            "whatsapp": self.whatsapp,
            "signal": self.signal,
        }

    @property
    def any_available(self) -> bool:
        if any(ch.available for ch in self._channels().values()):
            return True
        # Inbound-only credentials (no outbound webhook) still warrant the gateway:
        # a Discord bot token or a Slack app-level (Socket Mode) token is two-way.
        return bool(os.environ.get("NAMMA_DISCORD_BOT_TOKEN")
                    or os.environ.get("NAMMA_SLACK_APP_TOKEN"))

    @property
    def running(self) -> bool:
        """True while the inbound gateway is up (any pollable bridge or registered webhook)."""
        return bool(self._inbound or self._webhooks)

    def channels(self) -> list[str]:
        return [name for name, ch in self._channels().items() if ch.available]

    def status(self) -> dict:
        """Gateway snapshot for the UI: whether it's running and which channels
        are configured / actively polling / webhook-driven."""
        return {
            "running": self.running,
            "available": self.channels(),
            "polling": [b.channel_name for b in self._inbound],
            "webhooks": sorted(self._webhooks.keys()),
        }

    def reload(self) -> None:
        """Rebuild the channels from the current environment. Called before a
        (re)start so credentials the user just saved in Settings take effect
        without a full app restart. No-op while the gateway is running."""
        if self.running:
            return
        self.telegram = TelegramChannel()
        self.discord = DiscordChannel()
        self.slack = SlackChannel()
        self.whatsapp = WhatsAppChannel()
        self.signal = SignalChannel()

    def send(self, text: str, channel: str = "all") -> bool:
        """Send to one named channel or 'all'. True if any channel dispatched."""
        channel = (channel or "all").lower()
        sent = False
        for name, ch in self._channels().items():
            if channel in ("all", name) and ch.available:
                sent = ch.send(text) or sent
        return sent

    def start_inbound(self, on_message: Callable[..., tuple],
                      name: Optional[str] = None,
                      get_models: Optional[Callable[[], list]] = None) -> None:
        """The single gateway: start every available *pollable* inbound bridge
        (Telegram, Signal, Discord bot, Slack Socket Mode) in this one process, and
        register the *webhook-driven* bridges (Slack Events API, WhatsApp) so the
        server can route requests to them. Idempotent."""
        if self._inbound or self._webhooks:
            return  # already started

        # Pollable / socket bridges run their own thread (dial out — no public URL).
        if self.telegram.available:
            self._inbound.append(TelegramInbound(self.telegram, on_message, get_models=get_models))
        if self.signal.available:
            self._inbound.append(SignalInbound(self.signal, on_message, get_models=get_models))
        # Discord is two-way only via a bot on the Gateway (the webhook is send-only).
        discord_in = DiscordInbound(self.discord, on_message, get_models=get_models)
        if discord_in.available:
            self._inbound.append(discord_in)
        # Slack: prefer Socket Mode (local, no public URL); fall back to the HTTP
        # Events API webhook only when an app-level token isn't configured.
        slack_socket = SlackSocketInbound(self.slack, on_message, get_models=get_models)
        if slack_socket.available:
            self._inbound.append(slack_socket)
        for bridge in self._inbound:
            bridge.start()

        # Webhook-driven bridges are fed by the FastAPI server (no thread here).
        if not slack_socket.available and self.slack.available:
            self._webhooks["slack"] = SlackInbound(self.slack, on_message, get_models=get_models)
        if self.whatsapp.available:
            self._webhooks["whatsapp"] = WhatsAppInbound(self.whatsapp, on_message, get_models=get_models)

        # Greet on the interactive (pollable/socket) channels only — webhook bridges
        # aren't greeted to avoid noise/loops.
        if self._inbound:
            if not name:
                from namma_agent.config import assistant_name
                name = assistant_name()
            for bridge in self._inbound:
                bridge._say(f"{name} is online and ready.")
        logger.info("[comms] active channels: %s", ", ".join(self.channels()) or "none")

    def webhook_bridge(self, name: str) -> Optional[InboundBridge]:
        """The webhook-driven inbound bridge for a channel ('slack'/'whatsapp'), or None."""
        return self._webhooks.get((name or "").lower())

    def stop(self) -> None:
        """Stop the inbound gateway and clear its state so it can be started again
        (the start path builds fresh bridge instances)."""
        for bridge in self._inbound:
            bridge.stop()
        self._inbound = []
        self._webhooks = {}
