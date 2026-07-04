"""WhatsApp channel — QR-linked personal number via the WhatsApp Web protocol.

Unlike :mod:`namma_agent.comms.whatsapp` (the official Cloud API), this backend
links your *own* WhatsApp account by scanning a QR code, exactly like WhatsApp Web
/ Linked Devices. That means **no Meta Business account, no template messages, and
no 24-hour window** — the assistant can message you first, any time, and reply
freely. The cost: it drives an unofficial multi-device session via the
``neonize`` library (bindings to whatsmeow), which is against WhatsApp's ToS and
can get a number banned. Best for self-hosted, personal use — see docs/COMMS.md.

Env-gated:
  NAMMA_WHATSAPP_MODE   set to ``qr`` to activate this backend (default: ``cloud``)
  NAMMA_WHATSAPP_TO     recipient in E.164 digits (e.g. 919876543210). Outbound
                        notifications go here; inbound is scoped to this number so
                        randoms can't drive your agent. Leave empty to accept DMs
                        from anyone (personal boxes only).

The linked session persists in ``~/.namma_agent/whatsapp_qr.sqlite3`` — scan once,
then it reconnects on its own. ``neonize`` is an optional dependency: when it isn't
installed the channel simply reports unavailable (``pip install neonize``).
"""
from __future__ import annotations

import importlib.util
import os
import threading
from collections import deque
from pathlib import Path
from typing import Callable, Optional

from namma_agent.comms._util import chunk_text, markdown_to_whatsapp
from namma_agent.comms.inbound import InboundBridge
from namma_agent.core.logger import logger

_MAX_CHARS = 4000  # under WhatsApp's ~4096 text body limit
_SESSION_DB = Path("~/.namma_agent/whatsapp_qr.sqlite3").expanduser()


def whatsapp_mode() -> str:
    """Selected WhatsApp backend: ``qr`` or ``cloud`` (the default)."""
    return (os.environ.get("NAMMA_WHATSAPP_MODE") or "cloud").strip().lower()


def _neonize_installed() -> bool:
    """True if the ``neonize`` package is importable, without loading its native
    library (``find_spec`` doesn't import the ctypes .so/.dll). Retries after
    invalidating the import caches so a package installed *while the server is
    running* is picked up without a restart."""
    try:
        if importlib.util.find_spec("neonize") is not None:
            return True
        importlib.invalidate_caches()
        return importlib.util.find_spec("neonize") is not None
    except Exception:  # noqa: BLE001 — a broken install shouldn't crash startup
        return False


def _jid_user(jid) -> str:
    """The bare user part of a JID (digits), stripped of any ``+``. '' if absent."""
    return (getattr(jid, "User", "") or "").lstrip("+")


def _extract_text(message) -> str:
    """Pull plain text out of a neonize ``MessageEv`` (conversation or extended text)."""
    body = message.Message
    text = getattr(body, "conversation", "") or ""
    if not text:
        ext = getattr(body, "extendedTextMessage", None)
        text = getattr(ext, "text", "") if ext is not None else ""
    return (text or "").strip()


class WhatsAppQRChannel:
    """Outbound + session owner for the QR-linked backend.

    Owns the single ``neonize`` client and its (blocking) connect loop. The QR
    string is captured as it arrives so the web UI can render it; once the phone
    scans it, ``linked`` flips true and the session persists. Both outbound sends
    and the inbound bridge share this one client, so a message handler must be
    registered (via :meth:`set_message_handler`) *before* :meth:`start`."""

    def __init__(self, to: Optional[str] = None, db_path: Optional[Path] = None):
        # An explicit `to` (tests) pins the recipient; otherwise it's read from the
        # environment *live* on every use, so changing NAMMA_WHATSAPP_TO in Settings
        # takes effect without a restart (and a mistyped number is corrected at once).
        self._to_override = to.lstrip("+") if to is not None else None
        self._db_path = db_path or _SESSION_DB
        self._client = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._linked = False
        self._qr_uri: Optional[str] = None       # data: URI of the current QR (None once linked)
        self._msg_cb: Optional[Callable[[str], None]] = None
        # IDs of messages we've sent, so their echoes on the linked account aren't
        # mistaken for user input (which would make the assistant reply to itself).
        self._sent_ids: "deque[str]" = deque(maxlen=256)

    # -- availability ------------------------------------------------------

    @property
    def available(self) -> bool:
        """Active only in QR mode, and only if neonize can be imported."""
        return whatsapp_mode() == "qr" and _neonize_installed()

    def _recipient(self) -> str:
        """Current recipient (E.164 digits), read live from the env unless pinned."""
        if self._to_override is not None:
            return self._to_override
        return (os.environ.get("NAMMA_WHATSAPP_TO", "") or "").lstrip("+")

    @property
    def recipient(self) -> str:
        return self._recipient()

    # -- link status (for the UI) ------------------------------------------

    @property
    def linked(self) -> bool:
        return self._linked

    @property
    def qr_uri(self) -> Optional[str]:
        return self._qr_uri

    def status(self) -> dict:
        return {
            "mode": "qr",
            "available": self.available,
            "neonize": _neonize_installed(),  # so the UI can tell "not installed" from "not in qr mode"
            "linked": self._linked,
            "qr": self._qr_uri,
            "recipient_set": bool(self._recipient()),
        }

    # -- wiring ------------------------------------------------------------

    def set_message_handler(self, cb: Callable[[str], None]) -> None:
        """Register the inbound callback. Must be called before :meth:`start`."""
        self._msg_cb = cb

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Build the client, register callbacks, and run its connect loop on a
        daemon thread. Idempotent — a second call is a no-op."""
        if not self.available:
            return
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._run, name="WhatsAppQR", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            from neonize.client import NewClient
            from neonize.events import ConnectedEv, LoggedOutEv, MessageEv
        except Exception as exc:  # noqa: BLE001
            logger.warning("[whatsapp-qr] neonize unavailable: %s", exc)
            return

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        client = NewClient(str(self._db_path))
        self._client = client
        client.qr(self._on_qr)

        @client.event(ConnectedEv)
        def _on_connected(_c, _e):  # noqa: ANN001
            self._linked = True
            self._qr_uri = None
            logger.info("[whatsapp-qr] linked and connected")

        @client.event(LoggedOutEv)
        def _on_logout(_c, _e):  # noqa: ANN001
            self._linked = False
            logger.warning("[whatsapp-qr] logged out — re-scan the QR to re-link")

        @client.event(MessageEv)
        def _on_message(_c, message):  # noqa: ANN001
            # Run off the neonize event-loop thread: the agent turn is slow and it
            # calls back into the client to reply — doing that inline would block
            # (and can deadlock) the Go↔Python event bridge, so replies never send.
            threading.Thread(target=self._handle_incoming, args=(message,),
                             name="WhatsAppQR-msg", daemon=True).start()

        try:
            client.connect()  # blocks, running the event loop until disconnect
        except Exception as exc:  # noqa: BLE001
            logger.warning("[whatsapp-qr] connect ended: %s", exc)

    def _on_qr(self, _client, data_qr) -> None:  # noqa: ANN001
        """neonize hands us the raw QR content; render it as an inline SVG data URI."""
        try:
            import segno
            self._qr_uri = segno.make_qr(data_qr).svg_data_uri(scale=6, border=2)
            logger.info("[whatsapp-qr] scan the QR in Settings → Messaging to link")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[whatsapp-qr] failed to render QR: %s", exc)

    def _resolve_pn(self, jid) -> str:
        """Resolve a LID JID to its phone-number user part via the server. '' unless
        ``jid`` is a LID and a linked client can look it up (best-effort, no raise)."""
        client = self._client
        if client is None or jid is None:
            return ""
        if (getattr(jid, "Server", "") or "").lower() != "lid":
            return ""
        try:
            return _jid_user(client.get_pn_from_lid(jid))
        except Exception:  # noqa: BLE001
            return ""

    def _handle_incoming(self, message) -> None:
        info = message.Info
        src = info.MessageSource
        if src.IsGroup:
            return  # never act on group chatter
        mid = getattr(info, "ID", "") or ""
        if mid and mid in self._sent_ids:
            return  # our own outgoing message echoed back — don't reply to ourselves
        # On a personal number you reach the assistant either from the same account
        # ("Message Yourself" / typing on the linked phone → IsFromMe) or from another
        # number that messages you. The counterparty is the chat we sent to (IsFromMe)
        # or the sender (incoming). WhatsApp may address it by phone number (PN) or by a
        # privacy LID, with the other form in the *Alt field — so match the configured
        # number against BOTH. Scope to NAMMA_WHATSAPP_TO when set (empty = accept from
        # anyone — personal boxes only).
        if src.IsFromMe:
            primary, alt = src.Chat, getattr(src, "RecipientAlt", None)
        else:
            primary, alt = src.Sender, getattr(src, "SenderAlt", None)
        party_ids = {_jid_user(primary), _jid_user(alt)}
        party_ids.discard("")
        to = self._recipient()
        if to and to not in party_ids:
            # Fallback: no PN alt present, only a LID — ask the server to resolve it.
            resolved = self._resolve_pn(primary) or self._resolve_pn(alt)
            if resolved:
                party_ids.add(resolved)
            if to not in party_ids:
                logger.info("[whatsapp-qr] ignoring message; ids=%s configured=%s from_me=%s mode=%s",
                            sorted(party_ids) or ["?"], to, src.IsFromMe,
                            getattr(src, "AddressingMode", "?"))
                return
        text = _extract_text(message)
        if not text:
            return
        logger.info("[whatsapp-qr] handling inbound (ids=%s from_me=%s)",
                    sorted(party_ids) or ["?"], src.IsFromMe)
        if self._msg_cb:
            self._msg_cb(text)

    def relink(self) -> bool:
        """Drop the current session and re-establish so a fresh QR is issued —
        the 'Reconnect' action. Logs the linked device out (clearing creds server-
        and client-side), removes the persisted session, and restarts the connect
        loop, which then emits a new QR to scan. Returns False if unavailable."""
        if not self.available:
            return False
        client = self._client
        if client is not None:
            # Best-effort: unregister so the next connect shows a QR instead of
            # silently resuming the old session.
            for op in ("logout", "disconnect"):
                try:
                    getattr(client, op)()
                except Exception:  # noqa: BLE001
                    pass
        with self._lock:
            self._client = None
            self._thread = None
            self._linked = False
            self._qr_uri = None
        try:
            self._db_path.unlink(missing_ok=True)  # belt-and-suspenders past logout()
        except Exception:  # noqa: BLE001 — a locked db is fine; logout already cleared it
            pass
        self.start()
        return True

    def stop(self) -> None:
        client = self._client
        if client is not None:
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001
                pass

    # -- outbound ----------------------------------------------------------

    def send(self, text: str) -> bool:
        """Dispatch a message to the configured recipient. Returns False (nothing
        queued) when not linked, no recipient is set, or the text is empty."""
        if not self.available or not self._linked or not self._recipient() or not text:
            return False
        threading.Thread(target=self._send_sync, args=(text,), daemon=True).start()
        return True

    def _send_sync(self, text: str) -> None:
        client = self._client
        to = self._recipient()
        if client is None or not to:
            return
        try:
            from neonize.utils import build_jid
            jid = build_jid(to)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[whatsapp-qr] bad recipient %r: %s", to, exc)
            return
        for chunk in chunk_text(markdown_to_whatsapp(text), _MAX_CHARS):
            try:
                res = client.send_message(jid, chunk)
                mid = getattr(res, "ID", "") or ""
                if mid:
                    self._sent_ids.append(mid)  # so the echo isn't treated as user input
            except Exception as exc:  # noqa: BLE001
                logger.warning("[whatsapp-qr] send error: %s", exc)


class WhatsAppQRInbound(InboundBridge):
    """Two-way bridge over the QR-linked session. Like Telegram/Signal it dials
    out (no public URL), so it lives in the pollable-bridge list. Its ``_run_loop``
    hooks the channel's message callback and drives the connect loop; replies go
    back through the same client."""

    def __init__(self, channel: WhatsAppQRChannel,
                 on_message: Callable[..., tuple],
                 get_models: Optional[Callable[[], list]] = None):
        super().__init__(on_message, get_models)
        self._channel = channel

    @property
    def available(self) -> bool:
        return self._channel.available

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    def _say(self, text: str) -> None:
        self._channel.send(text)

    def _run_loop(self) -> None:
        # Feed incoming messages through the shared bridge routing, then start the
        # client (its own connect thread) and idle until stopped.
        self._channel.set_message_handler(self.handle_text)
        self._channel.start()
        self._stop.wait()

    def stop(self) -> None:
        super().stop()
        self._channel.stop()
