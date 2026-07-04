"""Wave 5a — Telegram + Discord channels and the send_notification tool."""
from __future__ import annotations

import pytest

from namma_agent.comms._util import chunk_text, markdown_to_whatsapp
from namma_agent.comms.console import ConsoleInbound
from namma_agent.comms.discord import DiscordChannel, DiscordInbound
from namma_agent.comms.manager import CommsManager
from namma_agent.comms.signal import SignalChannel, SignalInbound
from namma_agent.comms import slack as slack_mod
from namma_agent.comms.slack import SlackChannel, SlackSocketInbound
from namma_agent.comms.telegram import (
    TelegramChannel, TelegramInbound, _chunk, _markdown_to_telegram_html, _split_media,
)
from namma_agent.comms import signal as signal_mod
from namma_agent.comms import whatsapp as whatsapp_mod
from namma_agent.comms import whatsapp_qr as whatsapp_qr_mod
from namma_agent.comms.whatsapp import WhatsAppChannel, WhatsAppInbound
from namma_agent.comms.whatsapp_qr import WhatsAppQRChannel, whatsapp_mode
from namma_agent.core.tools import ToolRegistry
from namma_agent.tools import comms as comms_tool
from namma_agent.tools import load_tools


@pytest.fixture
def reg():
    return load_tools(ToolRegistry())


@pytest.fixture(autouse=True)
def _no_inbound_env(monkeypatch):
    """Keep the host's inbound-only credentials from bleeding into wiring tests
    (a real NAMMA_SLACK_APP_TOKEN would flip Slack from webhook to Socket Mode)."""
    for k in ("NAMMA_DISCORD_BOT_TOKEN", "NAMMA_DISCORD_CHANNEL_ID",
              "NAMMA_SLACK_APP_TOKEN", "NAMMA_SLACK_BOT_TOKEN"):
        monkeypatch.delenv(k, raising=False)


# ── channels ──────────────────────────────────────────────────────────────────

def test_send_notification_registered(reg):
    assert "send_notification" in reg


def test_telegram_unavailable_without_tokens():
    assert TelegramChannel(token="", chat_id="").available is False


def test_telegram_available_with_tokens():
    assert TelegramChannel(token="t", chat_id="c").available is True


def test_telegram_send_skipped_when_unavailable():
    assert TelegramChannel(token="", chat_id="").send("hi") is False


def test_markdown_to_html():
    out = _markdown_to_telegram_html("**bold** *it* `code` <x>")
    assert "<b>bold</b>" in out and "<i>it</i>" in out and "<code>code</code>" in out
    assert "&lt;x&gt;" in out  # escaped


def test_markdown_headers_links_and_bullets():
    out = _markdown_to_telegram_html(
        "## Auth Overview\n"
        "- first point\n"
        "* second point\n"
        "See [the docs](https://x.test/a_b) for more."
    )
    assert "<b>Auth Overview</b>" in out          # header → bold (no literal ##)
    assert "##" not in out
    assert "• first point" in out and "• second point" in out  # bullets normalized
    assert '<a href="https://x.test/a_b">the docs</a>' in out   # link → anchor
    assert "[the docs]" not in out


def test_markdown_code_fence_is_protected():
    out = _markdown_to_telegram_html("text\n```py\nif a < b and c > d:\n    go(**kw)\n```\nend")
    # Fence body is preserved verbatim (HTML-escaped) inside <pre>, not mangled by
    # the bold/italic passes.
    assert "<pre>" in out and "</pre>" in out
    assert "if a &lt; b and c &gt; d:" in out
    assert "go(**kw)" in out                       # ** inside code stays literal
    assert "<b>" not in out.split("</pre>")[0]


def test_markdown_narrow_table_becomes_monospace_grid():
    out = _markdown_to_telegram_html(
        "| Client | File |\n|---|---|\n| Browser | client.js |\n| Server | server.js |"
    )
    assert "|" not in out                          # no raw pipe table leaks
    assert "<pre>" in out and "</pre>" in out       # aligned monospace grid
    assert "Browser  client.js" in out              # columns padded/aligned


def test_markdown_wide_table_becomes_bullets():
    out = _markdown_to_telegram_html(
        "| Client | Purpose |\n|---|---|\n"
        "| Browser Client | Used in client components that handle the session from cookies |\n"
        "| Server Client | Reads cookies from next/headers on the server for every request |"
    )
    assert "|" not in out and "<pre>" not in out     # too wide for a grid → bullets
    assert "<b>Browser Client</b>" in out
    assert "• Purpose: Used in client components" in out


def test_table_cell_markdown_is_sanitized():
    # Bold/inline-code inside cells must not leak ** or ` into the output.
    out = _markdown_to_telegram_html(
        "| Name | Note |\n|---|---|\n| **Auth** | use `signUp()` |"
    )
    assert "**" not in out and "`" not in out and "|" not in out


def test_separatorless_pipe_table_is_detected():
    out = _markdown_to_telegram_html(
        "| A | B |\n| one | two |\n| three | four |"      # no |---| delimiter row
    )
    assert "|" not in out and ("<pre>" in out or "•" in out)


def test_no_markdown_symbols_leak():
    # Unbalanced/odd markers and missing-space headers must not reach the user.
    out = _markdown_to_telegram_html(
        "##Heading\n"                      # header with no space after ##
        "Some **bold** and a stray ** marker.\n"
        "### Another Section ###\n"
        "~~struck~~ and a lone ~~ too.\n"
        "---\n"
        "done"
    )
    assert "##" not in out and "**" not in out and "~~" not in out
    assert "<b>Heading</b>" in out and "<b>Another Section</b>" in out
    assert "<b>bold</b>" in out and "<s>struck</s>" in out
    assert "────────" in out               # horizontal rule rendered as a divider


def test_telegram_plain_fallback_strips_markup():
    from namma_agent.comms.telegram import _telegram_plain
    out = _telegram_plain("## Title\n- **bold** point\n`code` and [t](http://x)")
    assert "<" not in out and "##" not in out and "**" not in out and "`" not in out
    assert "• bold point" in out and "Title" in out and "[t]" not in out


def test_deliver_falls_back_to_plain_on_parse_error():
    ch = TelegramChannel(token="t", chat_id="42")
    calls = []

    def fake_post(method, body, timeout=10):
        calls.append(body)
        # First (HTML) attempt fails like Telegram's "can't parse entities".
        if body.get("parse_mode") == "HTML":
            return {"ok": False, "description": "Bad Request: can't parse entities"}
        return {"ok": True}

    ch._post = fake_post
    ch._deliver("**hi** <there>")
    assert len(calls) == 2
    assert calls[0]["parse_mode"] == "HTML"
    assert "parse_mode" not in calls[1]            # plain retry, no parse mode
    assert "hi" in calls[1]["text"] and "<there>" in calls[1]["text"]


# ── outbound media (photos / documents / send_file) ─────────────────────────────

def test_resolve_media_maps_api_url_and_paths():
    from pathlib import Path
    assert TelegramChannel._resolve_media("/api/media/diagrams/x.png") == Path("data/media/diagrams/x.png")
    assert TelegramChannel._resolve_media("/tmp/y.pdf") == Path("/tmp/y.pdf")
    assert TelegramChannel._resolve_media("") is None


def test_send_document_builds_multipart_upload(tmp_path):
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    ch = TelegramChannel(token="t", chat_id="42")
    captured = {}

    def fake_mp(method, fields, files, timeout=120):
        captured.update(method=method, fields=fields, files=files)
        return {"ok": True}

    ch._post_multipart = fake_mp
    assert ch.send_document(str(f), caption="here you go", reply_to=7) is True
    assert captured["method"] == "sendDocument"
    assert captured["fields"]["chat_id"] == "42"
    assert captured["fields"]["caption"] == "here you go"
    assert "reply_parameters" in captured["fields"]            # quotes the user's message
    name, content, _mime = captured["files"]["document"]
    assert name == "report.pdf" and content == b"%PDF-1.4 fake"


def test_post_multipart_builds_valid_body(tmp_path, monkeypatch):
    ch = TelegramChannel(token="TOK", chat_id="42")
    sent = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"ok": true}'

    def fake_urlopen(req, timeout=120):
        sent["url"] = req.full_url
        sent["ctype"] = req.headers.get("Content-type")
        sent["body"] = req.data
        return _Resp()

    from namma_agent.comms import telegram as tg
    monkeypatch.setattr(tg.urllib.request, "urlopen", fake_urlopen)
    out = ch._post_multipart("sendDocument", {"chat_id": "42"},
                             {"document": ("a.txt", b"hello", "text/plain")})
    assert out == {"ok": True}
    assert sent["url"].endswith("/botTOK/sendDocument")
    assert sent["ctype"].startswith("multipart/form-data; boundary=")
    body = sent["body"]
    assert b'name="chat_id"' in body and b"42" in body
    assert b'filename="a.txt"' in body and b"hello" in body


def test_send_photo_uses_sendphoto_for_image(tmp_path):
    f = tmp_path / "diagram.png"
    f.write_bytes(b"\x89PNG fake")
    ch = TelegramChannel(token="t", chat_id="42")
    seen = {}
    ch._post_multipart = lambda method, fields, files, timeout=120: (
        seen.update(m=method) or {"ok": True})
    assert ch.send_photo(str(f)) is True
    assert seen["m"] == "sendPhoto"


def test_send_media_routes_by_extension(tmp_path):
    ch = TelegramChannel(token="t", chat_id="42")
    kinds = []
    ch.send_photo = lambda src, caption="", reply_to=None: kinds.append("photo") or True
    ch.send_document = lambda src, caption="", reply_to=None: kinds.append("doc") or True
    (tmp_path / "a.png").write_bytes(b"x")
    (tmp_path / "a.zip").write_bytes(b"x")
    ch.send_media(str(tmp_path / "a.png"))
    ch.send_media(str(tmp_path / "a.zip"))
    assert kinds == ["photo", "doc"]


def test_send_media_missing_file_returns_false():
    ch = TelegramChannel(token="t", chat_id="42")
    assert ch.send_media("/api/media/diagrams/gone.png") is False


def test_split_media_separates_text_and_images():
    parts = _split_media(
        "intro\n![Flow](/api/media/diagrams/x.png)\n\n"
        "*Flow* · [⬇ Download](/api/media/diagrams/x.png)\nmore")
    assert [k for k, _ in parts] == ["text", "media", "text"]
    assert parts[1][1] == ("/api/media/diagrams/x.png", "Flow")


def test_send_reply_uploads_diagram_and_strips_dead_link():
    ch = TelegramChannel(token="t", chat_id="42")
    delivered, media = [], []
    ch._deliver = lambda chunk, reply_to=None: delivered.append(chunk)
    ch.send_media = lambda src, caption="", reply_to=None: media.append((src, caption)) or True
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("x", "s"))
    inbound._send_reply(
        "Here is the flow:\n\n![Flow](/api/media/diagrams/x.png)\n\n"
        "*Flow* · [⬇ Download diagram](/api/media/diagrams/x.png)\n\nThat's it.", reply_to=5)
    # the diagram was uploaded as a real photo with its title as caption …
    assert media == [("/api/media/diagrams/x.png", "Flow")]
    # … and the surrounding prose was sent, with the dead /api/media link stripped.
    joined = "\n".join(delivered)
    assert "Here is the flow:" in joined and "That's it." in joined
    assert "/api/media/" not in joined and "Download diagram" not in joined


def test_send_file_tool_registered(reg):
    assert "send_file" in reg


def test_send_file_tool_missing_file(reg):
    r = reg.execute("send_file", {"path": "/no/such/file.pdf"})
    assert not r.ok and "no file" in r.error.lower()


def test_send_file_tool_uploads_document(reg, tmp_path, monkeypatch):
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"data")
    sent = []

    class _FakeCh:
        available = True

        def send_document(self, p, caption=""):
            sent.append(("doc", str(p), caption))
            return True

        def send_photo(self, p, caption=""):
            sent.append(("photo", str(p), caption))
            return True

    from namma_agent.tools import send_file as sf
    monkeypatch.setattr(sf, "TelegramChannel", lambda: _FakeCh())
    r = reg.execute("send_file", {"path": str(f), "caption": "yours"})
    assert r.ok and sent == [("doc", str(f), "yours")]


def test_chunk_splits_long_text():
    chunks = _chunk("a" * 9000)
    assert len(chunks) >= 3 and all(len(c) <= 3800 for c in chunks)


def test_discord_unavailable_without_url():
    assert DiscordChannel(webhook_url="").available is False


# ── Slack / WhatsApp / Signal channels ──────────────────────────────────────────

def test_slack_availability_gating():
    assert SlackChannel(webhook_url="").available is False
    assert SlackChannel(webhook_url="https://hooks.slack.com/x").available is True
    assert SlackChannel(webhook_url="").send("hi") is False


def test_whatsapp_requires_all_three():
    assert WhatsAppChannel(token="", phone_id="", to="").available is False
    assert WhatsAppChannel(token="t", phone_id="p", to="").available is False  # missing recipient
    assert WhatsAppChannel(token="t", phone_id="p", to="919").available is True
    assert WhatsAppChannel(token="", phone_id="", to="").send("hi") is False


def test_signal_requires_all_three():
    assert SignalChannel(api_url="", number="", recipient="").available is False
    assert SignalChannel(api_url="http://x", number="+1", recipient="").available is False
    assert SignalChannel(api_url="http://x", number="+1", recipient="+2").available is True
    assert SignalChannel(api_url="", number="", recipient="").send("hi") is False


def test_signal_strips_trailing_slash():
    assert SignalChannel(api_url="http://localhost:8080/", number="+1", recipient="+2")._url == "http://localhost:8080"


def test_chunk_text_splits_long():
    chunks = chunk_text("a" * 9000, 3500)
    assert len(chunks) >= 3 and all(len(c) <= 3500 for c in chunks)


# ── inbound bridge ────────────────────────────────────────────────────────────

def test_inbound_routes_text_to_callback():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True  # capture replies synchronously
    seen = []

    def on_msg(text, session_id, mode, askpass=None, model=None):
        seen.append((text, mode))
        return f"echo: {text}", "sess-1"

    inbound = TelegramInbound(ch, on_msg)
    inbound._process("hello namma_agent")
    assert seen == [("hello namma_agent", "agent")] and sent == ["echo: hello namma_agent"]
    assert inbound._session_id == "sess-1"  # session persists


def test_inbound_shell_command():
    ch = TelegramChannel(token="t", chat_id="42")
    ch.send = lambda text: True
    seen = []
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: (seen.append(t) or "ok", s))
    inbound._process("!df -h")
    assert seen and "df -h" in seen[0] and "run_shell" in seen[0]


def test_inbound_mode_command():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("x", s))
    assert inbound._handle_command("/mode chat") is True
    assert inbound._mode == "chat"


def test_inbound_model_picker_flow():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True
    models = [{"id": "opus", "label": "Claude Opus"}, {"id": "gpt", "label": "GPT-5.5"}]
    used = []
    inbound = TelegramInbound(
        ch, lambda t, s, m, a=None, model=None: (used.append(model) or "ok", "sess-1"),
        get_models=lambda: models)

    # /model lists the models numbered, with a Cancel option, and opens the picker.
    assert inbound._handle_command("/model") is True
    menu = sent[-1]
    assert "1. Claude Opus" in menu and "2. GPT-5.5" in menu and "0. Cancel" in menu
    assert inbound._pending_models == models

    # A bad choice re-prompts and keeps the picker open.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "9"}})
    assert inbound._pending_models == models and "isn't on the list" in sent[-1]

    # A non-number also re-prompts.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "blah"}})
    assert inbound._pending_models == models and "isn't a number" in sent[-1]

    # A valid choice switches the model and starts a fresh session.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "2"}})
    assert inbound._pending_models is None
    assert inbound._model_id == "gpt" and inbound._session_id is None
    assert "Switched to GPT-5.5" in sent[-1]

    # The chosen model is now passed on every turn.
    inbound._process("hello")
    assert used[-1] == "gpt"


def test_inbound_model_cancel():
    ch = TelegramChannel(token="t", chat_id="42")
    sent = []
    ch.send = lambda text: sent.append(text) or True
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("ok", s),
                              get_models=lambda: [{"id": "x", "label": "X"}])
    inbound._handle_command("/model")
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "0"}})
    assert inbound._pending_models is None and inbound._model_id is None
    assert "keeping the current model" in sent[-1].lower()


def test_inbound_ignores_wrong_chat():
    ch = TelegramChannel(token="t", chat_id="42")
    calls = []
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: (calls.append(t) or "x", s))
    inbound._dispatch({"message": {"chat": {"id": 999}, "text": "hi"}})
    assert calls == []


def test_inbound_askpass_captures_password():
    ch = TelegramChannel(token="t", chat_id="42")
    sent, deleted = [], []
    ch.send = lambda text: sent.append(text) or True
    ch._post = lambda method, body: deleted.append((method, body)) or {"ok": True}
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("ok", s))

    import threading
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("pw", inbound.askpass("Enter your sudo password")))
    t.start()
    # Wait until the prompt is sent / pending request registered.
    import time
    for _ in range(50):
        if inbound._pw_event is not None:
            break
        time.sleep(0.01)
    # The next message is treated as the password (not a turn) and deleted.
    inbound._dispatch({"message": {"chat": {"id": 42}, "text": "s3cret", "message_id": 9}})
    t.join(timeout=2)
    assert result["pw"] == "s3cret"
    assert any(m == "deleteMessage" for m, _ in deleted)  # password scrubbed
    assert any("🔒" in s for s in sent)                    # prompt was shown


# ── live progress preambles (mid-turn lines as their own messages) ──────────────

def test_execute_exposes_progress_sink_for_live_preambles():
    """The bridge sets a per-turn progress sink so the agent's intermediate lines
    can be delivered as their own messages while the turn is still running."""
    from namma_agent.core.interactive import get_progress_sink

    out = []

    def on_msg(text, sid, mode, askpass=None, model=None):
        prog = get_progress_sink()
        assert prog is not None
        prog("Let me check my memory…")        # a mid-turn preamble, delivered live
        return "Here's the final answer.", "s1"

    c = ConsoleInbound(on_msg, output_fn=out.append)
    reply = c._execute("who am I?")
    assert "Let me check my memory…" in out     # streamed as its own message
    assert reply == "Here's the final answer."
    # The sink is cleared once the turn ends (no leakage between turns).
    assert get_progress_sink() is None


def test_strip_sent_preambles_removes_live_lines_from_final():
    from namma_agent.service import NammaAgentService

    content = "Let me check my memory.\n\nLet me dig deeper.\n\nHere is the full breakdown."
    sent = ["Let me check my memory.", "Let me dig deeper."]
    out = NammaAgentService._strip_sent_preambles(content, sent)
    assert out == "Here is the full breakdown."

    # If stripping would empty the message, keep the original (never send nothing).
    assert NammaAgentService._strip_sent_preambles("just this", ["just this"]) == "just this"


# ── shared InboundBridge logic (exercised via ConsoleInbound) ───────────────────

def test_console_handles_commands_and_turns():
    out, seen = [], []

    def on_msg(text, sid, mode, askpass=None, model=None):
        seen.append((text, mode))
        return f"echo: {text}", "s1"

    lines = iter(["/mode chat", "hello", "!ls", "/quit"])
    c = ConsoleInbound(on_msg, input_fn=lambda _p: next(lines), output_fn=out.append)
    c.run_blocking()
    assert any("Mode set to chat" in o for o in out)
    assert ("hello", "chat") in seen
    assert any("run_shell" in t and "ls" in t for t, _ in seen)   # !ls → run_shell prompt
    assert "echo: hello" in out
    assert c._session_id == "s1"


def test_console_model_picker_switches_brain():
    out, used = [], []
    models = [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]

    def on_msg(text, sid, mode, askpass=None, model=None):
        used.append(model)
        return "ok", "s1"

    lines = iter(["/model", "2", "go", "/quit"])
    c = ConsoleInbound(on_msg, get_models=lambda: models,
                       input_fn=lambda _p: next(lines), output_fn=out.append)
    c.run_blocking()
    assert any("1. A" in o for o in out) and any("2. B" in o for o in out)
    assert c._model_id == "b"
    assert used[-1] == "b"  # the chosen model is passed on the next turn


# ── Signal inbound (polling) ────────────────────────────────────────────────────

def test_signal_inbound_routes_text():
    ch = SignalChannel(api_url="http://x", number="+1", recipient="+2")
    sent = []
    ch.send = lambda text: sent.append(text) or True  # capture replies synchronously
    seen = []
    sb = SignalInbound(ch, lambda t, s, m, a=None, model=None: (seen.append(t) or "the answer", "s1"))
    sb.handle_text("ping")
    assert seen == ["ping"] and sent == ["the answer"]
    assert sb._session_id == "s1"


def test_signal_receive_extracts_message_text(monkeypatch):
    class _Resp:
        def __init__(self, data): self._d = data
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self._d

    payload = (b'[{"envelope":{"dataMessage":{"message":"hi"}}},'
               b'{"envelope":{"dataMessage":{"message":"   "}}},'
               b'{"envelope":{}},{"nope":1}]')
    monkeypatch.setattr(signal_mod.urllib.request, "urlopen", lambda *a, **k: _Resp(payload))
    sb = SignalInbound(SignalChannel(api_url="http://x", number="+1", recipient="+2"),
                       lambda *a, **k: ("", "s"))
    assert sb._receive() == ["hi"]


# ── Slack / WhatsApp webhook parsers ────────────────────────────────────────────

def test_slack_extract_texts_ignores_bot_and_edits():
    assert slack_mod.extract_texts({"event": {"type": "message", "text": "hello"}}) == ["hello"]
    assert slack_mod.extract_texts({"event": {"type": "message", "text": "x", "bot_id": "B1"}}) == []
    assert slack_mod.extract_texts({"event": {"type": "message", "subtype": "message_changed", "text": "x"}}) == []
    assert slack_mod.extract_texts({"event": {"type": "reaction_added"}}) == []


def test_slack_verify_signature():
    import hashlib
    import hmac
    secret, ts, body = "shh", "1700000000", b'{"a":1}'
    good = "v0=" + hmac.new(secret.encode(), b"v0:" + ts.encode() + b":" + body, hashlib.sha256).hexdigest()
    assert slack_mod.verify_signature(secret, ts, good, body) is True
    assert slack_mod.verify_signature(secret, ts, "v0=deadbeef", body) is False
    assert slack_mod.verify_signature("", ts, good, body) is False


def test_whatsapp_extract_texts():
    payload = {"entry": [{"changes": [{"value": {"messages": [
        {"type": "text", "text": {"body": "hi there"}},
        {"type": "image"},
    ]}}]}]}
    assert whatsapp_mod.extract_texts(payload) == ["hi there"]
    # Status callbacks carry no messages → nothing.
    assert whatsapp_mod.extract_texts({"entry": [{"changes": [{"value": {"statuses": [{"status": "read"}]}}]}]}) == []


def test_whatsapp_verify_handshake():
    wb = WhatsAppInbound(WhatsAppChannel(token="t", phone_id="p", to="9"),
                         lambda *a, **k: ("", "s"), verify_token="V")
    assert wb.verify("subscribe", "V", "CHAL") == "CHAL"
    assert wb.verify("subscribe", "wrong", "CHAL") is None
    assert wb.verify("", "V", "CHAL") is None


# ── WhatsApp QR (personal-number) backend ───────────────────────────────────────

def test_whatsapp_mode_defaults_to_cloud(monkeypatch):
    monkeypatch.delenv("NAMMA_WHATSAPP_MODE", raising=False)
    assert whatsapp_mode() == "cloud"
    monkeypatch.setenv("NAMMA_WHATSAPP_MODE", "QR")  # case-insensitive
    assert whatsapp_mode() == "qr"


def test_manager_selects_whatsapp_backend_by_mode(monkeypatch):
    monkeypatch.setenv("NAMMA_WHATSAPP_MODE", "qr")
    assert isinstance(CommsManager().whatsapp, WhatsAppQRChannel)
    monkeypatch.setenv("NAMMA_WHATSAPP_MODE", "cloud")
    assert isinstance(CommsManager().whatsapp, WhatsAppChannel)


def test_whatsapp_qr_unavailable_outside_qr_mode(monkeypatch):
    monkeypatch.setenv("NAMMA_WHATSAPP_MODE", "cloud")
    assert WhatsAppQRChannel(to="919876543210").available is False


def test_whatsapp_qr_send_skipped_until_linked(monkeypatch):
    monkeypatch.setenv("NAMMA_WHATSAPP_MODE", "qr")
    ch = WhatsAppQRChannel(to="919876543210")
    assert ch.send("hi") is False          # not linked yet → nothing dispatched
    assert ch.status()["linked"] is False


def test_whatsapp_qr_extract_text():
    import types
    convo = types.SimpleNamespace(conversation="hello", extendedTextMessage=None)
    assert whatsapp_qr_mod._extract_text(types.SimpleNamespace(Message=convo)) == "hello"
    ext = types.SimpleNamespace(conversation="",
                                extendedTextMessage=types.SimpleNamespace(text="  world "))
    assert whatsapp_qr_mod._extract_text(types.SimpleNamespace(Message=ext)) == "world"


def _wa_msg(text, *, sender, chat, from_me=False, group=False, mid="m",
           sender_alt=None, recipient_alt=None):
    import types
    jid = lambda u: types.SimpleNamespace(User=u) if u is not None else None  # noqa: E731
    src = types.SimpleNamespace(IsFromMe=from_me, IsGroup=group,
                                Sender=jid(sender), Chat=jid(chat),
                                SenderAlt=jid(sender_alt), RecipientAlt=jid(recipient_alt),
                                AddressingMode="lid" if (sender_alt or recipient_alt) else "pn")
    info = types.SimpleNamespace(MessageSource=src, ID=mid)
    body = types.SimpleNamespace(conversation=text, extendedTextMessage=None)
    return types.SimpleNamespace(Info=info, Message=body)


def test_whatsapp_qr_matches_lid_via_alt_field():
    """WhatsApp LID addressing: Sender/Chat carry a privacy LID and the real phone
    number is in the *Alt field — the configured number must still match."""
    me = "919398542229"
    lid = "231997020581942"
    ch = WhatsAppQRChannel(to=me)
    seen: list[str] = []
    ch.set_message_handler(seen.append)

    # Incoming addressed by LID, real number in SenderAlt.
    ch._handle_incoming(_wa_msg("hi", sender=lid, chat=lid, from_me=False,
                                sender_alt=me, mid="l1"))
    # Message-Yourself addressed by LID, real number in RecipientAlt.
    ch._handle_incoming(_wa_msg("self", sender=lid, chat=lid, from_me=True,
                                recipient_alt=me, mid="l2"))
    # A different LID with a different real number is still ignored.
    ch._handle_incoming(_wa_msg("nope", sender="999888777", chat="999888777",
                                from_me=False, sender_alt="911111111111", mid="l3"))
    assert seen == ["hi", "self"]


def test_whatsapp_qr_incoming_self_chat_and_loop_guard():
    """Own-number config: 'Message Yourself' is accepted, but our own replies
    (tracked by id) and strangers/groups are not."""
    me = "919876543210"
    ch = WhatsAppQRChannel(to=me)
    seen: list[str] = []
    ch.set_message_handler(seen.append)

    ch._handle_incoming(_wa_msg("hi self", sender=me, chat=me, from_me=True, mid="a"))  # I type to myself
    ch._handle_incoming(_wa_msg("stranger", sender="111", chat="111", from_me=False, mid="b"))  # not my number
    ch._handle_incoming(_wa_msg("grp", sender=me, chat=me, group=True, mid="c"))         # group
    ch._sent_ids.append("d")                                                             # a reply we dispatched
    ch._handle_incoming(_wa_msg("echo of my reply", sender=me, chat=me, from_me=True, mid="d"))  # loop guard
    assert seen == ["hi self"]


def test_whatsapp_qr_incoming_peer_model():
    """Peer config (to = a contact): the peer's messages come in, and our own
    replies to that chat (same id we sent) don't loop back."""
    peer = "15550001111"
    ch = WhatsAppQRChannel(to=peer)
    seen: list[str] = []
    ch.set_message_handler(seen.append)

    ch._handle_incoming(_wa_msg("hello", sender=peer, chat=peer, from_me=False, mid="p1"))  # peer → me
    ch._sent_ids.append("p2")
    ch._handle_incoming(_wa_msg("assistant reply", sender="919876543210", chat=peer,
                                from_me=True, mid="p2"))  # our echoed reply
    assert seen == ["hello"]


class _FakeChannel:
    def __init__(self, available, ok):
        self._available, self._ok, self.sent = available, ok, []

    @property
    def available(self):
        return self._available

    def send(self, text):
        self.sent.append(text)
        return self._ok


def test_markdown_to_whatsapp():
    out = markdown_to_whatsapp("**bold** and _it_ and ~~gone~~\n## Heading\n- one\n- two\n"
                               "[link](https://x.io)")
    assert "*bold*" in out and "_it_" in out and "~gone~" in out
    assert "*Heading*" in out and "#" not in out
    assert "• one" in out and "• two" in out
    assert "link (https://x.io)" in out


def test_whatsapp_qr_recipient_reads_env_live(monkeypatch):
    """Changing NAMMA_WHATSAPP_TO takes effect without a restart (no pinned `to`)."""
    monkeypatch.setenv("NAMMA_WHATSAPP_TO", "919000000001")
    ch = WhatsAppQRChannel()  # not pinned → reads env
    assert ch.recipient == "919000000001"
    monkeypatch.setenv("NAMMA_WHATSAPP_TO", "919000000002")
    assert ch.recipient == "919000000002"  # updated live


def test_manager_send_each_reports_only_dispatched():
    tg = _FakeChannel(available=True, ok=True)
    wa = _FakeChannel(available=True, ok=False)  # available (configured) but not ready
    mgr = CommsManager(telegram=tg, whatsapp=wa)
    assert mgr.send_each("hi", "all") == ["telegram"]   # wa didn't dispatch → not listed
    assert mgr.send_each("hi", "whatsapp") == []
    assert mgr.send("hi", "telegram") is True


def test_send_notification_prefers_live_comms_for_whatsapp():
    """The tool routes through the running manager (so the connected WhatsApp QR
    channel is reachable) rather than rebuilding channels from env."""
    from namma_agent.core import interactive

    class _Live:
        any_available = True
        def channels(self):
            return ["telegram", "whatsapp"]
        def send_each(self, msg, channel):
            return [c for c in self.channels() if channel in ("all", c)]

    interactive.set_comms(_Live())
    try:
        r = comms_tool._send_notification({"message": "hi", "channel": "whatsapp"})
        assert r.ok and "whatsapp" in r.content
    finally:
        interactive.set_comms(None)


def test_send_notification_reports_channel_not_ready():
    from namma_agent.core import interactive

    class _Live:
        any_available = True
        def channels(self):
            return ["telegram", "whatsapp"]  # whatsapp configured…
        def send_each(self, msg, channel):
            return []                          # …but not ready (e.g. QR not linked)

    interactive.set_comms(_Live())
    try:
        r = comms_tool._send_notification({"message": "hi", "channel": "whatsapp"})
        assert not r.ok and "not ready" in (r.error or "")
    finally:
        interactive.set_comms(None)


# ── manager ───────────────────────────────────────────────────────────────────

def _bare_manager(**overrides):
    """A manager with every channel explicitly off, except those overridden — so the
    host's real env vars can't bleed into routing assertions."""
    off = {
        "telegram": TelegramChannel(token="", chat_id=""),
        "discord": DiscordChannel(webhook_url=""),
        "slack": SlackChannel(webhook_url=""),
        "whatsapp": WhatsAppChannel(token="", phone_id="", to=""),
        "signal": SignalChannel(api_url="", number="", recipient=""),
    }
    off.update(overrides)
    return CommsManager(**off)


def test_manager_routes_to_named_channel():
    tg = TelegramChannel(token="t", chat_id="c")
    tg_sent = []
    tg._send_sync = lambda text, reply_to=None: tg_sent.append(text)
    mgr = _bare_manager(telegram=tg)
    assert mgr.channels() == ["telegram"]
    assert mgr.send("hey", channel="telegram") is True
    assert tg_sent == ["hey"]


def test_manager_lists_and_routes_new_channels():
    sl = SlackChannel(webhook_url="https://hooks.slack.com/x")
    sl_sent = []
    sl._send_sync = lambda text: sl_sent.append(text)
    mgr = _bare_manager(slack=sl)
    assert mgr.channels() == ["slack"]
    assert mgr.any_available is True
    # 'all' fans out and reaches the one available channel.
    assert mgr.send("ping", channel="all") is True
    assert sl_sent == ["ping"]
    # A named channel that's off does not dispatch.
    assert mgr.send("ping", channel="signal") is False


def test_manager_registers_webhook_bridges():
    sl = SlackChannel(webhook_url="https://hooks.slack.com/x")
    wa = WhatsAppChannel(token="t", phone_id="p", to="9")
    mgr = _bare_manager(slack=sl, whatsapp=wa)  # no pollable channels → no threads/greeting
    mgr.start_inbound(lambda *a, **k: ("ok", "s"), name="X")
    assert mgr.webhook_bridge("slack") is not None
    assert mgr.webhook_bridge("whatsapp") is not None
    assert mgr.webhook_bridge("telegram") is None
    # Idempotent — a second call is a no-op.
    before = mgr.webhook_bridge("slack")
    mgr.start_inbound(lambda *a, **k: ("ok", "s"))
    assert mgr.webhook_bridge("slack") is before


def test_manager_starts_signal_pollable(monkeypatch):
    started = []
    monkeypatch.setattr(SignalInbound, "start", lambda self: started.append(self))
    sig = SignalChannel(api_url="http://x", number="+1", recipient="+2")
    sig.send = lambda text: True  # greeting goes here; keep it off the network
    mgr = _bare_manager(signal=sig)
    mgr.start_inbound(lambda *a, **k: ("ok", "s"), name="X")
    assert any(isinstance(s, SignalInbound) for s in started)


def test_manager_status_and_restart():
    """The gateway reports its state and can be stopped then started again
    (stop clears state so a later start builds fresh bridges)."""
    sl = SlackChannel(webhook_url="https://hooks.slack.com/x")  # webhook bridge, no threads
    mgr = _bare_manager(slack=sl)
    assert mgr.running is False
    assert mgr.status() == {"running": False, "available": ["slack"],
                            "polling": [], "webhooks": []}

    mgr.start_inbound(lambda *a, **k: ("ok", "s"), name="X")
    assert mgr.running is True
    assert mgr.status()["webhooks"] == ["slack"]

    mgr.stop()
    assert mgr.running is False
    assert mgr.webhook_bridge("slack") is None

    # Restart works after a stop (the idempotency guard was cleared).
    mgr.start_inbound(lambda *a, **k: ("ok", "s"), name="X")
    assert mgr.running is True
    assert mgr.webhook_bridge("slack") is not None


def test_manager_reload_noop_while_running():
    """reload() rebuilds channels from env, but never while the gateway is up."""
    sl = SlackChannel(webhook_url="https://hooks.slack.com/x")
    mgr = _bare_manager(slack=sl)
    mgr.start_inbound(lambda *a, **k: ("ok", "s"), name="X")
    before = mgr.slack
    mgr.reload()
    assert mgr.slack is before  # unchanged while running


# ── Discord gateway (bot) inbound ───────────────────────────────────────────────

def test_discord_inbound_availability_gating():
    assert DiscordInbound(None, lambda *a, **k: ("", "s"), bot_token="").available is False
    assert DiscordInbound(None, lambda *a, **k: ("", "s"), bot_token="T").available is True
    assert DiscordInbound(None, lambda *a, **k: ("", "s"), bot_token="T").channel_name == "discord"


def _discord(on, **kw):
    db = DiscordInbound(None, on, bot_token="T", **kw)
    sent = []
    db._rest_send = lambda cid, text: sent.append((cid, text))
    return db, sent


def test_discord_dispatch_routes_message_and_replies():
    seen = []
    db, sent = _discord(lambda t, s, m, a=None, model=None: (seen.append(t) or "pong", "s1"))
    db._dispatch({"t": "MESSAGE_CREATE",
                  "d": {"content": "ping", "channel_id": "C9", "author": {"id": "U1"}}})
    assert seen == ["ping"]
    assert sent == [("C9", "pong")]           # reply lands in the originating channel
    assert db._session_id == "s1"


def test_discord_dispatch_ignores_bots_and_self():
    db, sent = _discord(lambda *a, **k: ("x", "s"))
    db._bot_user_id = "ME"
    db._dispatch({"t": "MESSAGE_CREATE", "d": {"content": "hi", "channel_id": "C", "author": {"bot": True}}})
    db._dispatch({"t": "MESSAGE_CREATE", "d": {"content": "hi", "channel_id": "C", "author": {"id": "ME"}}})
    assert sent == []  # neither another bot nor our own message triggers a turn


def test_discord_dispatch_channel_restriction():
    db, sent = _discord(lambda *a, **k: ("x", "s"), channel_id="ONLY")
    db._dispatch({"t": "MESSAGE_CREATE", "d": {"content": "hi", "channel_id": "OTHER", "author": {"id": "U"}}})
    assert sent == []  # wrong channel ignored
    db._dispatch({"t": "MESSAGE_CREATE", "d": {"content": "hi", "channel_id": "ONLY", "author": {"id": "U"}}})
    assert sent == [("ONLY", "x")]


def test_discord_ready_sets_bot_id():
    db, _ = _discord(lambda *a, **k: ("x", "s"))
    db._dispatch({"t": "READY", "d": {"user": {"id": "BID", "username": "namma"}}})
    assert db._bot_user_id == "BID"


# ── Slack Socket Mode inbound ───────────────────────────────────────────────────

def test_slack_socket_availability_gating():
    assert SlackSocketInbound(SlackChannel(webhook_url=""), lambda *a, **k: ("", "s"),
                              app_token="").available is False
    sb = SlackSocketInbound(SlackChannel(webhook_url=""), lambda *a, **k: ("", "s"), app_token="xapp-1")
    assert sb.available is True and sb.channel_name == "slack"


def test_slack_socket_event_routes_and_replies_via_bot():
    seen, posted = [], []
    sb = SlackSocketInbound(SlackChannel(webhook_url=""),
                            lambda t, s, m, a=None, model=None: (seen.append(t) or "reply", "s1"),
                            app_token="xapp-1", bot_token="xoxb-1")
    sb._post_message = lambda channel, text: posted.append((channel, text))
    sb._on_event({"event": {"type": "message", "text": "hello", "channel": "C42"}})
    assert seen == ["hello"]
    assert posted == [("C42", "reply")]       # reply goes back to the same channel via the bot


def test_slack_socket_reply_falls_back_to_webhook_without_bot_token():
    ch = SlackChannel(webhook_url="https://hooks.slack.com/x")
    sent = []
    ch.send = lambda text: sent.append(text) or True
    sb = SlackSocketInbound(ch, lambda t, s, m, a=None, model=None: ("reply", "s1"), app_token="xapp-1")
    sb._on_event({"event": {"type": "message", "text": "hi", "channel": "C1"}})
    assert sent == ["reply"]                   # no bot token → outgoing webhook fallback


# ── manager wiring for the new bridges ──────────────────────────────────────────

def test_manager_starts_discord_gateway_when_bot_token(monkeypatch):
    monkeypatch.setenv("NAMMA_DISCORD_BOT_TOKEN", "T")
    started = []
    monkeypatch.setattr(DiscordInbound, "start", lambda self: started.append(self))
    mgr = _bare_manager()  # no outbound channels at all
    assert mgr.any_available is True  # an inbound-only bot token is enough to run
    mgr.start_inbound(lambda *a, **k: ("ok", "s"), name="X")
    assert any(isinstance(s, DiscordInbound) for s in started)
    assert "discord" in mgr.status()["polling"]


def test_manager_prefers_slack_socket_over_webhook(monkeypatch):
    monkeypatch.setenv("NAMMA_SLACK_APP_TOKEN", "xapp-1")
    monkeypatch.setattr(SlackSocketInbound, "start", lambda self: None)
    sl = SlackChannel(webhook_url="https://hooks.slack.com/x")  # webhook also configured
    sl._send_sync = lambda text: None  # the greeting falls back here; keep it off the network
    mgr = _bare_manager(slack=sl)
    mgr.start_inbound(lambda *a, **k: ("ok", "s"), name="X")
    # Socket Mode wins: it's a pollable bridge, and the HTTP webhook bridge is NOT registered.
    assert any(isinstance(b, SlackSocketInbound) for b in mgr._inbound)
    assert mgr.webhook_bridge("slack") is None


# ── tool ──────────────────────────────────────────────────────────────────────

def _all_channels_off(monkeypatch):
    """Force every channel factory in the tool to build an unavailable instance."""
    monkeypatch.setitem(comms_tool._CHANNELS, "telegram", lambda: TelegramChannel(token="", chat_id=""))
    monkeypatch.setitem(comms_tool._CHANNELS, "discord", lambda: DiscordChannel(webhook_url=""))
    monkeypatch.setitem(comms_tool._CHANNELS, "slack", lambda: SlackChannel(webhook_url=""))
    monkeypatch.setitem(comms_tool._CHANNELS, "whatsapp", lambda: WhatsAppChannel(token="", phone_id="", to=""))
    monkeypatch.setitem(comms_tool._CHANNELS, "signal", lambda: SignalChannel(api_url="", number="", recipient=""))


def test_send_notification_no_channels(reg, monkeypatch):
    _all_channels_off(monkeypatch)
    r = reg.execute("send_notification", {"message": "hi"})
    assert not r.ok and "no channels" in r.error


def test_send_notification_to_slack(reg, monkeypatch):
    _all_channels_off(monkeypatch)
    sl = SlackChannel(webhook_url="https://hooks.slack.com/x")
    sent = []
    sl._send_sync = lambda text: sent.append(text)
    monkeypatch.setitem(comms_tool._CHANNELS, "slack", lambda: sl)
    r = reg.execute("send_notification", {"message": "deploy done", "channel": "slack"})
    assert r.ok and "slack" in r.content and sent == ["deploy done"]


def test_send_notification_sends(reg, monkeypatch):
    _all_channels_off(monkeypatch)
    tg = TelegramChannel(token="t", chat_id="c")
    sent = []
    tg._send_sync = lambda text, reply_to=None: sent.append(text)
    monkeypatch.setitem(comms_tool._CHANNELS, "telegram", lambda: tg)
    r = reg.execute("send_notification", {"message": "deploy done", "channel": "telegram"})
    assert r.ok and "telegram" in r.content and sent == ["deploy done"]


# ── inbound: command menu, replies, voice ───────────────────────────────────────

def _recording_channel():
    ch = TelegramChannel(token="t", chat_id="42")
    calls = []
    ch._post = lambda method, body, timeout=10: (
        calls.append((method, body)) or {"ok": True, "result": {"message_id": 99}})
    return ch, calls


def test_inbound_registers_command_menu():
    ch, calls = _recording_channel()
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("x", s))
    inbound._register_commands()
    setcmds = [b for meth, b in calls if meth == "setMyCommands"]
    assert setcmds and any(c["command"] == "help" for c in setcmds[0]["commands"])


def test_inbound_reply_quotes_user_message():
    ch, calls = _recording_channel()
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("the answer", "sess"))
    inbound._reply_turn("hi", reply_to=5)
    # The answer is sent ONCE as a reply quoting the user's message — no edits/placeholder.
    sends = [b for meth, b in calls if meth == "sendMessage"]
    assert sends and sends[0]["reply_parameters"]["message_id"] == 5
    assert "the answer" in sends[0]["text"]
    assert not [m for m, _ in calls if m == "editMessageText"]


def test_inbound_voice_transcribes_and_answers(monkeypatch):
    ch, calls = _recording_channel()
    seen = []
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: (seen.append(t) or "ok", s))
    monkeypatch.setattr(inbound, "_download", lambda v: "/tmp/voice.oga")
    monkeypatch.setattr("namma_agent.comms.transcribe.transcribe_audio", lambda p: "what's the time")
    inbound._process_voice({"file_id": "v1"}, "", reply_to=7)
    assert seen == ["what's the time"]


def test_inbound_voice_without_stt_replies_gracefully(monkeypatch):
    ch, calls = _recording_channel()
    sent = []
    ch.send = lambda text, reply_to=None: sent.append(text) or True
    inbound = TelegramInbound(ch, lambda t, s, m, a=None, model=None: ("x", s))
    monkeypatch.setattr(inbound, "_download", lambda v: "/tmp/voice.oga")
    monkeypatch.setattr("namma_agent.comms.transcribe.transcribe_audio", lambda p: None)
    inbound._process_voice({"file_id": "v1"}, "", reply_to=7)
    assert sent and "transcription isn't set up" in sent[0]


# ── webhook routes (Slack / WhatsApp) ───────────────────────────────────────────

def _webhook_client(mgr=None):
    """A TestClient over the API with an optional comms manager attached."""
    from fastapi.testclient import TestClient

    from namma_agent.core.memory import Database
    from namma_agent.core.providers.base import LLMResponse
    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService
    from namma_agent.tests.test_projects import ScriptedProvider

    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=ScriptedProvider([LLMResponse(content="ok")]),
                            registry=ToolRegistry(), db=Database(":memory:"))
    svc.comms = mgr  # injected registry leaves comms None; attach ours
    return TestClient(create_app(svc)), svc


def test_slack_url_verification_handshake():
    client, _ = _webhook_client()
    r = client.post("/webhooks/slack", json={"type": "url_verification", "challenge": "C123"})
    assert r.status_code == 200 and r.json()["challenge"] == "C123"


def test_whatsapp_verify_rejects_when_unconfigured():
    client, _ = _webhook_client()  # no comms → no bridge
    r = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe",
                                                 "hub.verify_token": "x", "hub.challenge": "c"})
    assert r.status_code == 403


def test_webhook_routes_dispatch_to_bridge():
    seen = []
    sl = SlackChannel(webhook_url="https://hooks.slack.com/x")
    sl.send = lambda *a, **k: True
    wa = WhatsAppChannel(token="t", phone_id="p", to="9")
    wa.send = lambda *a, **k: True
    mgr = _bare_manager(slack=sl, whatsapp=wa)
    mgr.start_inbound(lambda text, s, m, a=None, model=None: (seen.append(text) or "ok", "s1"))
    client, _ = _webhook_client(mgr)

    # WhatsApp text message → routed to the bridge (background thread).
    client.post("/webhooks/whatsapp", json={"entry": [{"changes": [{"value": {"messages": [
        {"type": "text", "text": {"body": "hi wa"}}]}}]}]})
    # WhatsApp verify handshake now succeeds (token matches the unset default "").
    # Slack real event → routed too.
    client.post("/webhooks/slack", json={"event": {"type": "message", "text": "hi slack"}})

    import time
    for _ in range(100):
        if "hi wa" in seen and "hi slack" in seen:
            break
        time.sleep(0.01)
    assert "hi wa" in seen and "hi slack" in seen
