"""Messaging channels for Namma Agent.

Self-contained, stdlib-only, env-gated. Channels stay off unless their tokens are
present in the environment:

  * Telegram — ``NAMMA_TELEGRAM_TOKEN`` + ``NAMMA_TELEGRAM_CHAT_ID`` (outbound + inbound)
  * Discord  — ``NAMMA_DISCORD_WEBHOOK_URL``
  * Slack    — ``NAMMA_SLACK_WEBHOOK_URL``
  * WhatsApp — Cloud API (``NAMMA_WHATSAPP_TOKEN`` + ``NAMMA_WHATSAPP_PHONE_ID`` +
    ``NAMMA_WHATSAPP_TO``) or, with ``NAMMA_WHATSAPP_MODE=qr``, a QR-linked personal
    number (``NAMMA_WHATSAPP_TO`` only) via ``neonize``
  * Signal   — ``NAMMA_SIGNAL_API_URL`` + ``NAMMA_SIGNAL_NUMBER`` + ``NAMMA_SIGNAL_RECIPIENT``

:class:`CommsManager` wires outbound notifications across every channel and (for
Telegram) an inbound bridge so you can chat with Namma Agent from your phone.
"""
from namma_agent.comms.console import ConsoleInbound
from namma_agent.comms.discord import DiscordChannel
from namma_agent.comms.inbound import InboundBridge
from namma_agent.comms.manager import CommsManager
from namma_agent.comms.signal import SignalChannel, SignalInbound
from namma_agent.comms.slack import SlackChannel, SlackInbound
from namma_agent.comms.telegram import TelegramChannel, TelegramInbound
from namma_agent.comms.whatsapp import WhatsAppChannel, WhatsAppInbound
from namma_agent.comms.whatsapp_qr import WhatsAppQRChannel, WhatsAppQRInbound

__all__ = ["InboundBridge", "TelegramChannel", "TelegramInbound", "DiscordChannel",
           "SlackChannel", "SlackInbound", "WhatsAppChannel", "WhatsAppInbound",
           "WhatsAppQRChannel", "WhatsAppQRInbound",
           "SignalChannel", "SignalInbound", "ConsoleInbound", "CommsManager"]
