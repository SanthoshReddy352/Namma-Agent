"""Email over IMAP/SMTP (Phase 5) — any provider that offers app passwords:
Gmail, Outlook/Hotmail, Yahoo, iCloud, Zoho, Fastmail, or a custom server.

Gmail can also go through the `gws` CLI (tools/gws.py); this is the universal
path. Config (``mail.accounts`` in user_config.yaml; written by the setup mode)::

    mail:
      accounts:
        - id: work
          address: me@example.com
          provider: fastmail            # a preset below, or "custom"
          imap_host: imap.fastmail.com  # presets fill host/port
          smtp_host: smtp.fastmail.com
          password_env: NAMMA_MAIL_WORK_PASSWORD   # the app password, in the vault

The password is read from the environment (the vault is bridged into it) at
call time and never stored in the config. Stdlib only (imaplib / smtplib).
"""
from __future__ import annotations

import email
import email.header
import email.utils
import imaplib
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

from namma_agent.core.tools import ToolRegistry, ToolResult

#: Provider presets: hosts/ports and where to create an app password.
MAIL_PRESETS: dict[str, dict] = {
    "gmail": {"label": "Gmail", "imap_host": "imap.gmail.com", "smtp_host": "smtp.gmail.com",
              "app_password_url": "https://myaccount.google.com/apppasswords",
              "note": "Needs 2-Step Verification; or use Google Workspace (gws) instead."},
    "outlook": {"label": "Outlook / Hotmail", "imap_host": "outlook.office365.com",
                "smtp_host": "smtp-mail.outlook.com",
                "app_password_url": "https://account.live.com/proofs/AppPassword",
                "note": "Microsoft is retiring password sign-in for IMAP on many accounts; "
                        "if sign-in fails, use Outlook's own connector or forward mail."},
    "yahoo": {"label": "Yahoo Mail", "imap_host": "imap.mail.yahoo.com",
              "smtp_host": "smtp.mail.yahoo.com",
              "app_password_url": "https://login.yahoo.com/account/security"},
    "icloud": {"label": "iCloud Mail", "imap_host": "imap.mail.me.com",
               "smtp_host": "smtp.mail.me.com", "smtp_port": 587,
               "app_password_url": "https://account.apple.com/account/manage"},
    "zoho": {"label": "Zoho Mail", "imap_host": "imap.zoho.com", "smtp_host": "smtp.zoho.com",
             "app_password_url": "https://accounts.zoho.com/home#security/app_password"},
    "fastmail": {"label": "Fastmail", "imap_host": "imap.fastmail.com",
                 "smtp_host": "smtp.fastmail.com",
                 "app_password_url": "https://app.fastmail.com/settings/security/apps"},
    "custom": {"label": "Other (custom IMAP/SMTP)", "imap_host": "", "smtp_host": ""},
}
_TIMEOUT = 25


def password_env_for(account_id: str) -> str:
    return "NAMMA_MAIL_" + re.sub(r"[^A-Z0-9]", "_", account_id.upper())[:30] + "_PASSWORD"


def normalize_account(acc: dict) -> dict:
    """Fill preset hosts/ports and the vault variable name."""
    a = dict(acc or {})
    preset = MAIL_PRESETS.get(str(a.get("provider") or "custom").lower(), MAIL_PRESETS["custom"])
    a["provider"] = str(a.get("provider") or "custom").lower()
    a["id"] = re.sub(r"[^a-z0-9_-]", "-", str(a.get("id") or a.get("address", "mail").split("@")[0]).lower())[:30] or "mail"
    a.setdefault("imap_host", preset.get("imap_host", ""))
    a.setdefault("smtp_host", preset.get("smtp_host", ""))
    a["imap_port"] = int(a.get("imap_port") or preset.get("imap_port", 993))
    a["smtp_port"] = int(a.get("smtp_port") or preset.get("smtp_port", 465))
    a.setdefault("username", a.get("address", ""))
    a.setdefault("password_env", password_env_for(a["id"]))
    return a


def validate_account(acc: dict) -> list[str]:
    a = normalize_account(acc)
    errs = []
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", str(a.get("address") or "")):
        errs.append("address: a valid email address is required")
    for host in ("imap_host", "smtp_host"):
        if not re.match(r"^[A-Za-z0-9.-]+$", str(a.get(host) or "")):
            errs.append(f"{host}: required (a hostname like imap.example.com)")
    return errs


def _accounts() -> list[dict]:
    from namma_agent.config import load_config
    try:
        raw = ((load_config() or {}).get("mail") or {}).get("accounts") or []
    except Exception:  # noqa: BLE001
        raw = []
    return [normalize_account(a) for a in raw if isinstance(a, dict)]


def _pick(account: str = "") -> tuple[Optional[dict], str]:
    accounts = _accounts()
    if not accounts:
        return None, ("No email account is set up. Use setup mode (or Settings) to add one — "
                      "an address plus an app password.")
    if not account:
        return accounts[0], ""
    for a in accounts:
        if account.lower() in (a["id"], str(a.get("address", "")).lower()):
            return a, ""
    return None, f"No email account '{account}'. Configured: {', '.join(a['id'] for a in accounts)}"


def _password(a: dict) -> tuple[str, str]:
    pw = os.environ.get(a["password_env"], "")
    if not pw:
        return "", (f"The app password for {a.get('address')} isn't saved — add "
                    f"{a['password_env']} via the secure key field.")
    return pw, ""


def _decode(value: str) -> str:
    try:
        return str(email.header.make_header(email.header.decode_header(value or "")))
    except Exception:  # noqa: BLE001
        return value or ""


def _imap(a: dict) -> imaplib.IMAP4_SSL:
    pw, err = _password(a)
    if err:
        raise RuntimeError(err)
    conn = imaplib.IMAP4_SSL(a["imap_host"], a["imap_port"], timeout=_TIMEOUT,
                             ssl_context=ssl.create_default_context())
    try:
        conn.login(a["username"], pw)
    except imaplib.IMAP4.error as exc:
        conn.logout()
        raise RuntimeError(f"sign-in rejected for {a['address']}: {exc} — check the app "
                           "password (a normal password usually won't work)") from exc
    return conn


def check_account(acc: dict) -> dict:
    """Sign in to IMAP and SMTP without reading or sending anything."""
    a = normalize_account(acc)
    result = {"imap": False, "smtp": False, "errors": []}
    try:
        conn = _imap(a)
        conn.logout()
        result["imap"] = True
    except Exception as exc:  # noqa: BLE001
        result["errors"].append(f"IMAP: {exc}")
    pw, err = _password(a)
    if not err:
        try:
            with _smtp(a) as s:
                s.login(a["username"], pw)
            result["smtp"] = True
        except Exception as exc:  # noqa: BLE001
            result["errors"].append(f"SMTP: {exc}")
    result["ok"] = result["imap"] and result["smtp"]
    return result


def _smtp(a: dict):
    ctx = ssl.create_default_context()
    if a["smtp_port"] == 465:
        return smtplib.SMTP_SSL(a["smtp_host"], 465, timeout=_TIMEOUT, context=ctx)
    s = smtplib.SMTP(a["smtp_host"], a["smtp_port"], timeout=_TIMEOUT)
    s.starttls(context=ctx)
    return s


def _mail_list(args: dict) -> ToolResult:
    a, err = _pick(args.get("account") or "")
    if err:
        return ToolResult(ok=False, content="", error=err)
    folder = args.get("folder") or "INBOX"
    unread = bool(args.get("unread", True))
    limit = max(1, min(int(args.get("max") or 10), 50))
    query = str(args.get("from") or "").strip()
    try:
        conn = _imap(a)
        try:
            conn.select(f'"{folder}"', readonly=True)
            criteria = ["UNSEEN"] if unread else ["ALL"]
            if query:
                criteria += ["FROM", f'"{query}"']
            typ, data = conn.uid("search", None, *criteria)
            uids = (data[0] or b"").split()[-limit:][::-1]
            lines = []
            for uid in uids:
                typ, msg = conn.uid("fetch", uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                hdr = email.message_from_bytes(msg[0][1]) if msg and msg[0] else {}
                lines.append(f"- [{uid.decode()}] {_decode(hdr.get('From', ''))}: "
                             f"{_decode(hdr.get('Subject', '(no subject)'))} ({hdr.get('Date', '')})")
        finally:
            conn.logout()
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))
    if not lines:
        return ToolResult(ok=True, content=f"No {'unread ' if unread else ''}mail in {folder}.")
    return ToolResult(ok=True, content=f"{a['address']} — {folder}:\n" + "\n".join(lines))


def _mail_read(args: dict) -> ToolResult:
    a, err = _pick(args.get("account") or "")
    if err:
        return ToolResult(ok=False, content="", error=err)
    uid = str(args.get("id") or "").strip()
    if not uid.isdigit():
        return ToolResult(ok=False, content="", error="'id' (the number from mail_list) is required")
    try:
        conn = _imap(a)
        try:
            conn.select(f'"{args.get("folder") or "INBOX"}"', readonly=True)
            typ, msg = conn.uid("fetch", uid, "(BODY.PEEK[])")
        finally:
            conn.logout()
        if not msg or not msg[0]:
            return ToolResult(ok=False, content="", error=f"no message {uid}")
        m = email.message_from_bytes(msg[0][1])
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=str(exc))
    body = ""
    for part in (m.walk() if m.is_multipart() else [m]):
        if part.get_content_type() == "text/plain" and not part.get_filename():
            body = (part.get_payload(decode=True) or b"").decode(
                part.get_content_charset() or "utf-8", errors="replace")
            break
    if not body:
        for part in (m.walk() if m.is_multipart() else [m]):
            if part.get_content_type() == "text/html":
                html = (part.get_payload(decode=True) or b"").decode(
                    part.get_content_charset() or "utf-8", errors="replace")
                body = re.sub(r"<[^>]+>", " ", html)
                break
    head = (f"From: {_decode(m.get('From', ''))}\nTo: {_decode(m.get('To', ''))}\n"
            f"Subject: {_decode(m.get('Subject', ''))}\nDate: {m.get('Date', '')}\n\n")
    return ToolResult(ok=True, content=head + re.sub(r"\n{3,}", "\n\n", body).strip()[:8000])


def _mail_send(args: dict) -> ToolResult:
    a, err = _pick(args.get("account") or "")
    if err:
        return ToolResult(ok=False, content="", error=err)
    to = str(args.get("to") or "").strip()
    subject = str(args.get("subject") or "").strip()
    if not (to and subject):
        return ToolResult(ok=False, content="", error="'to' and 'subject' are required")
    pw, perr = _password(a)
    if perr:
        return ToolResult(ok=False, content="", error=perr)
    msg = EmailMessage()
    msg["From"] = a["address"]
    msg["To"] = to
    if args.get("cc"):
        msg["Cc"] = args["cc"]
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid()
    msg.set_content(str(args.get("body") or ""))
    try:
        with _smtp(a) as s:
            s.login(a["username"], pw)
            s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        return ToolResult(ok=False, content="", error=f"send failed: {exc}")
    return ToolResult(ok=True, content=f"Email sent from {a['address']} to {to}.")


def register(registry: ToolRegistry) -> None:
    acct = {"type": "string", "description": "account id or address (default: the first)"}
    registry.register(
        "mail_list",
        "List recent emails from an IMAP account (Outlook, Yahoo, iCloud, Zoho, Fastmail, "
        "Gmail with an app password, …). For Gmail via Google Workspace use gmail_list.",
        {"type": "object", "properties": {
            "account": acct,
            "unread": {"type": "boolean", "description": "only unread (default true)"},
            "from": {"type": "string", "description": "only mail from this sender"},
            "folder": {"type": "string", "description": "IMAP folder (default INBOX)"},
            "max": {"type": "integer", "description": "how many (default 10, max 50)"}}},
        _mail_list)
    registry.register(
        "mail_read", "Read one email (by the id from mail_list).",
        {"type": "object", "properties": {
            "id": {"type": "string"}, "account": acct,
            "folder": {"type": "string"}}, "required": ["id"]},
        _mail_read)
    registry.register(
        "mail_send", "Send an email from an IMAP/SMTP account. Show the user the exact "
        "text and recipient first.",
        {"type": "object", "properties": {
            "to": {"type": "string"}, "subject": {"type": "string"},
            "body": {"type": "string"}, "cc": {"type": "string"}, "account": acct},
         "required": ["to", "subject", "body"]},
        _mail_send, destructive=True)
