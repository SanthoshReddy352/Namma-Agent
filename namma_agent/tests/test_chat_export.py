"""Chat export — download a session as a zip (chat.md transcript + its media)."""
from __future__ import annotations

import io
import zipfile

from namma_agent.core.chat_export import (
    build_chat_zip,
    collect_media,
    derive_title,
    export_filename,
    render_markdown,
)


def _turn(role, content, created_at="2026-07-15T10:00:00"):
    return {"role": role, "content": content, "tools_used": [], "meta": None,
            "created_at": created_at}


# -- markdown rendering ------------------------------------------------------

def test_markdown_has_title_roles_and_content():
    turns = [_turn("user", "How do gears work?"),
             _turn("assistant", "Gears mesh teeth to transfer torque.")]
    md = render_markdown(turns, {"model": "gpt-x", "created_at": "2026-07-15T09:59:00"},
                         assistant_name="Nova")
    assert md.startswith("# How do gears work?")
    assert "model `gpt-x`" in md
    assert "**You** · 2026-07-15 10:00" in md
    assert "**Nova**" in md
    assert "Gears mesh teeth to transfer torque." in md


def test_markdown_rewrites_media_links_to_zip_relative():
    turns = [_turn("assistant",
                   "![Gears](/api/media/diagrams/g.png)\n\n"
                   "[⬇ Download](/api/media/diagrams/g.png?v=2)")]
    md = render_markdown(turns, {})
    assert "/api/media/" not in md
    assert "![Gears](media/diagrams/g.png)" in md
    assert "[⬇ Download](media/diagrams/g.png)" in md


def test_markdown_hides_plumbing_and_renders_quiz():
    quiz = ('{"question": "2+2?", "options": ["3", "4"], "answer_index": 1}')
    turns = [_turn("user", "[quiz answer] I chose 4 — continue."),
             _turn("user", "[build path] make a plan"),
             _turn("quiz", quiz),
             _turn("assistant", "Nice, moving on.")]
    md = render_markdown(turns, {})
    assert "[quiz answer]" not in md and "[build path]" not in md
    assert "**Quiz:** 2+2?" in md
    assert "2. 4 ✓" in md


def test_title_prefers_rename_then_first_message():
    turns = [_turn("user", "hello there")]
    assert derive_title(turns, {"title": "My chat"}) == "My chat"
    assert derive_title(turns, {}) == "hello there"
    assert derive_title([], {}) == "Chat"
    assert export_filename(turns, {"title": "Gears & Torque!"}) == "gears-torque.zip"


# -- media collection --------------------------------------------------------

def test_collect_media_existing_only_and_traversal_safe(tmp_path):
    (tmp_path / "diagrams").mkdir()
    (tmp_path / "diagrams" / "g.png").write_bytes(b"png")
    turns = [_turn("assistant", "![a](/api/media/diagrams/g.png) "
                                "![b](/api/media/diagrams/missing.png) "
                                "![c](/api/media/../secret.txt)")]
    media = collect_media(turns, media_root=tmp_path)
    assert list(media) == ["diagrams/g.png"]
    assert media["diagrams/g.png"].read_bytes() == b"png"


# -- the zip -----------------------------------------------------------------

def test_build_chat_zip_bundles_transcript_and_media(tmp_path):
    (tmp_path / "diagrams").mkdir()
    (tmp_path / "diagrams" / "g.png").write_bytes(b"png-bytes")
    turns = [_turn("user", "show me gears"),
             _turn("assistant", "Here:\n\n![Gears](/api/media/diagrams/g.png)")]
    name, data = build_chat_zip(turns, {"title": "Gear chat"}, "Nova", media_root=tmp_path)
    assert name == "gear-chat.zip"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert set(zf.namelist()) == {"chat.md", "media/diagrams/g.png"}
        md = zf.read("chat.md").decode("utf-8")
        assert "![Gears](media/diagrams/g.png)" in md
        assert zf.read("media/diagrams/g.png") == b"png-bytes"


def test_build_chat_zip_survives_missing_media(tmp_path):
    turns = [_turn("assistant", "![gone](/api/media/diagrams/gone.png)")]
    name, data = build_chat_zip(turns, {}, media_root=tmp_path)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.namelist() == ["chat.md"]


# -- the endpoint ------------------------------------------------------------

def test_export_endpoint_returns_zip():
    from fastapi.testclient import TestClient

    from namma_agent.core.memory import Database
    from namma_agent.core.tools import ToolRegistry
    from namma_agent.server.api import create_app
    from namma_agent.service import NammaAgentService
    from namma_agent.tests.test_server import ScriptedProvider
    from namma_agent.core.providers.base import LLMResponse

    db = Database(":memory:")
    svc = NammaAgentService(config={"persona": "core", "conversation": {}},
                            provider=ScriptedProvider([LLMResponse(content="hi")]),
                            registry=ToolRegistry(), db=db)
    sid = db.create_session()
    db.add_turn(sid, "user", "hello")
    db.add_turn(sid, "assistant", "hi there")
    client = TestClient(create_app(svc))

    r = client.get(f"/api/sessions/{sid}/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert 'filename="hello.zip"' in r.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert "chat.md" in zf.namelist()
        assert "hi there" in zf.read("chat.md").decode("utf-8")

    assert client.get("/api/sessions/nope/export").status_code == 404
