"""Comms tool — send a notification to any configured messaging channel.

Builds the channels from the environment on each call (cheap, stateless), so the
tool works through plain auto-discovery. Channels stay off unless their tokens are
set (see :mod:`namma_agent.comms`).
"""
from __future__ import annotations

from namma_agent.comms.discord import DiscordChannel
from namma_agent.comms.signal import SignalChannel
from namma_agent.comms.slack import SlackChannel
from namma_agent.comms.telegram import TelegramChannel
from namma_agent.comms.whatsapp import WhatsAppChannel
from namma_agent.core.tools import ToolRegistry, ToolResult

# name → factory, in a stable order. One place to add a channel.
_CHANNELS = {
    "telegram": TelegramChannel,
    "discord": DiscordChannel,
    "slack": SlackChannel,
    "whatsapp": WhatsAppChannel,
    "signal": SignalChannel,
}


def _send_notification(args: dict) -> ToolResult:
    message = (args.get("message") or "").strip()
    if not message:
        return ToolResult(ok=False, content="", error="a message is required")
    channel = (args.get("channel") or "all").lower()
    built = {name: factory() for name, factory in _CHANNELS.items()}

    if not any(ch.available for ch in built.values()):
        return ToolResult(ok=False, content="",
                          error="no channels configured (set NAMMA_TELEGRAM_TOKEN+"
                                "NAMMA_TELEGRAM_CHAT_ID, NAMMA_DISCORD_WEBHOOK_URL, "
                                "NAMMA_SLACK_WEBHOOK_URL, the NAMMA_WHATSAPP_* trio, "
                                "or the NAMMA_SIGNAL_* trio)")
    sent_to = []
    for name, ch in built.items():
        if channel in ("all", name) and ch.available and ch.send(message):
            sent_to.append(name)
    if not sent_to:
        return ToolResult(ok=False, content="", error=f"no available channel for {channel!r}")
    return ToolResult(ok=True, content=f"Notification sent to {', '.join(sent_to)}.")


def register(registry: ToolRegistry) -> None:
    registry.register("send_notification",
        "Send a notification message to a messaging channel (Telegram, Discord, "
        "Slack, WhatsApp, or Signal).", {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "the message to send"},
                "channel": {"type": "string",
                            "enum": ["all", *_CHANNELS.keys()],
                            "description": "target channel (default all)"},
            },
            "required": ["message"],
        }, _send_notification)
