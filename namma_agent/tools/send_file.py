"""send_file tool — deliver a local file to the user's Telegram chat.

Lets the agent push a file that exists on disk (a PDF on the desktop, a rendered
chart, an export, …) into Telegram so the user can download it on their phone.
Built fresh from the environment on each call, like ``send_notification``; stays
off unless NAMMA_TELEGRAM_TOKEN + NAMMA_TELEGRAM_CHAT_ID are set.

Telegram is the one channel with outbound media today; other channels are
text-only (use ``send_notification`` for those).
"""
from __future__ import annotations

from pathlib import Path

from namma_agent.comms.telegram import TelegramChannel
from namma_agent.core.tools import ToolRegistry, ToolResult

_MAX_BYTES = 50 * 1024 * 1024  # Telegram bot upload limit


def _send_file(args: dict) -> ToolResult:
    path = (args.get("path") or "").strip()
    if not path:
        return ToolResult(ok=False, content="", error="a file path is required")
    caption = (args.get("caption") or "").strip()
    as_photo = bool(args.get("as_photo", False))

    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return ToolResult(ok=False, content="", error=f"no file found at {path!r}")
    size = p.stat().st_size
    if size > _MAX_BYTES:
        return ToolResult(ok=False, content="",
                          error=f"{p.name} is {size // (1024 * 1024)} MB — over Telegram's "
                                "50 MB upload limit")

    channel = TelegramChannel()
    if not channel.available:
        return ToolResult(ok=False, content="",
                          error="Telegram isn't configured (set NAMMA_TELEGRAM_TOKEN and "
                                "NAMMA_TELEGRAM_CHAT_ID)")

    ok = (channel.send_photo(p, caption) if as_photo
          else channel.send_document(p, caption))
    if not ok:
        return ToolResult(ok=False, content="",
                          error="Telegram rejected the upload (image too large for a photo, "
                                "or a network error) — try again or send it as a document")
    how = "photo" if as_photo else "document"
    return ToolResult(ok=True, content=f"Sent {p.name} to your Telegram chat as a {how}.")


def register(registry: ToolRegistry) -> None:
    registry.register(
        "send_file",
        "Send a local file (PDF, image, document, archive, …) that exists on this "
        "machine to the user's Telegram chat so they can download it on their phone. "
        "Use this whenever the user asks you to send, share, or deliver them a file. "
        "Set as_photo=true for an image you want previewed inline; otherwise it goes as "
        "a downloadable document (preserves the original file).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string",
                         "description": "absolute path to the file on this machine"},
                "caption": {"type": "string",
                            "description": "optional caption / label shown with the file"},
                "as_photo": {"type": "boolean",
                             "description": "send an image inline as a photo (default false "
                                            "= downloadable document)"},
            },
            "required": ["path"],
        },
        _send_file,
    )
