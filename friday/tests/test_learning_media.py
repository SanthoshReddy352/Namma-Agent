"""Wave 3 tests — Learning-Room media tools (diagram / image / simulation)."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from friday.core.tools import ToolRegistry
from friday.tools.learning_media import register


@pytest.fixture
def reg(tmp_path, monkeypatch):
    # Redirect media output into a temp dir so tests don't litter data/media.
    import friday.tools.learning_media as lm
    monkeypatch.setattr(lm, "_MEDIA", tmp_path / "media")
    r = ToolRegistry()
    register(r)
    return r


def test_render_simulation_writes_html(reg, tmp_path):
    html = "<!doctype html><html><body><h1>hi</h1><script>1+1</script></body></html>"
    res = reg.execute("render_simulation", {"html": html, "title": "Demo"})
    assert res.ok
    assert "/api/media/sims/" in res.content
    rel = res.data["url"].split("/api/media/")[1]
    assert (tmp_path / "media" / rel).read_text().startswith("<!doctype html>")


def test_render_simulation_rejects_non_html(reg):
    res = reg.execute("render_simulation", {"html": "just text"})
    assert not res.ok and "html" in res.error.lower()


def test_fetch_image_mocked(reg, tmp_path, monkeypatch):
    import io
    import friday.tools.learning_media as lm

    class FakeResp(io.BytesIO):
        def __init__(self, data, ctype="image/png"):
            super().__init__(data)
            self.headers = {"Content-Type": ctype}
        def __enter__(self): return self
        def __exit__(self, *a): return False

    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] == 1:  # the Openverse search
            import json
            body = json.dumps({"results": [{
                "url": "https://example.test/cat.png", "title": "Cat",
                "creator": "Ada", "license": "cc0"}]}).encode()
            return FakeResp(body, "application/json")
        return FakeResp(b"\x89PNG\r\n\x1a\n fake-bytes", "image/png")  # the image download

    monkeypatch.setattr(lm.urllib.request, "urlopen", fake_urlopen)
    res = reg.execute("fetch_image", {"query": "cat"})
    assert res.ok
    assert "/api/media/images/" in res.content and "Ada" in res.content
    rel = res.data["url"].split("/api/media/")[1]
    assert (tmp_path / "media" / rel).exists()


@pytest.mark.skipif(not (shutil.which("mmdc") or (Path.home() / ".npm-global/bin/mmdc").exists()),
                    reason="mermaid-cli (mmdc) not installed")
def test_render_diagram_real(reg, tmp_path):
    # The model writes the Mermaid source itself; we render it verbatim to a PNG.
    res = reg.execute("render_diagram", {
        "title": "Flow",
        "code": 'flowchart TD\n    A["Abstraction"] -->|"means"| B["Focus on what, not how"]\n'
                '    A --> C["Hide details (e.g. car pedals)"]'})
    assert res.ok, res.error
    rel = res.data["url"].split("/api/media/")[1]
    out = tmp_path / "media" / rel
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.skipif(not (shutil.which("mmdc") or (Path.home() / ".npm-global/bin/mmdc").exists()),
                    reason="mermaid-cli (mmdc) not installed")
def test_render_diagram_sequence(reg):
    res = reg.execute("render_diagram", {
        "title": "Chat",
        "code": "sequenceDiagram\n    participant L as Learner\n    participant T as Teacher\n"
                "    L->>T: why and how?\n    T-->>L: it hides how"})
    assert res.ok, res.error
    assert res.data.get("url") and res.data["kind"] == "diagram"


def test_render_diagram_strips_code_fence(reg, monkeypatch):
    # The model often wraps its source in a ```mermaid fence; we strip it and render
    # the inner source verbatim rather than rejecting it.
    import friday.tools.learning_media as lm
    seen = {}

    def fake_ink(code):
        seen["code"] = code
        return _FAKE_PNG, ""

    monkeypatch.setattr(lm, "_render_via_ink", fake_ink)
    res = reg.execute("render_diagram", {
        "title": "Fenced", "code": "```mermaid\nflowchart LR\n    A --> B\n```"})
    assert res.ok, res.error
    assert seen["code"].startswith("flowchart LR") and "```" not in seen["code"]


def test_render_diagram_requires_valid_mermaid(reg):
    # Missing code → clear error. Prose/JSON that isn't a diagram declaration → rejected
    # before any render attempt (not a crash).
    res = reg.execute("render_diagram", {"title": "x"})
    assert not res.ok and "code" in res.error
    res = reg.execute("render_diagram", {"title": "x", "code": "just explain it in words"})
    assert not res.ok and "Mermaid" in res.error


# A tiny but valid 1x1 PNG (passes _verify_png_bytes' header check) padded to the
# 256-byte minimum so the verification gate accepts it.
_FAKE_PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
             + b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89" + b"\x00" * 300)


def test_render_diagram_writes_server_png_from_api(reg, tmp_path, monkeypatch):
    # The primary path: the hosted API returns PNG bytes → we verify + write them to
    # disk server-side and hand the chat an <img> URL (never client-side mermaid).
    import friday.tools.learning_media as lm
    monkeypatch.setattr(lm, "_render_via_ink", lambda code: (_FAKE_PNG, ""))
    res = reg.execute("render_diagram", {
        "title": "Flow", "code": 'flowchart LR\n    A["A"] -->|"x"| B["B"]'})
    assert res.ok, res.error
    assert res.data.get("kind") == "diagram" and "/api/media/diagrams/" in res.data["url"]
    rel = res.data["url"].split("/api/media/")[1]
    assert (tmp_path / "media" / rel).read_bytes() == _FAKE_PNG
    assert "```mermaid" not in res.content


def test_render_diagram_local_fallback_when_api_down(reg, tmp_path, monkeypatch):
    # API unreachable → fall through to the local renderer, still a server-side PNG.
    import friday.tools.learning_media as lm
    monkeypatch.setattr(lm, "_render_via_ink", lambda code: (None, "offline"))
    monkeypatch.setattr(lm, "_render_via_local", lambda code, out: (_FAKE_PNG, ""))
    res = reg.execute("render_diagram", {
        "title": "T", "code": "flowchart TD\n    A --> B"})
    assert res.ok and "/api/media/diagrams/" in res.data["url"]
    rel = res.data["url"].split("/api/media/")[1]
    assert (tmp_path / "media" / rel).read_bytes() == _FAKE_PNG


def test_finalize_png_flattens_and_trims():
    """A transparent, heavily-padded PNG (what mermaid.ink returns) is flattened onto
    white (so dark lines stay visible on any theme) and trimmed to the content (so it
    isn't microscopic in the chat)."""
    pytest.importorskip("PIL")
    import io

    from PIL import Image

    from friday.tools.learning_media import _finalize_png
    # 400x400 fully transparent canvas with a small opaque black box in the middle.
    img = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    for x in range(180, 220):
        for y in range(180, 220):
            img.putpixel((x, y), (10, 10, 10, 255))
    raw = io.BytesIO(); img.save(raw, "PNG")
    out = _finalize_png(raw.getvalue())
    assert out[:8] == b"\x89PNG\r\n\x1a\n"          # a valid PNG came back
    res = Image.open(io.BytesIO(out))
    assert res.mode == "RGB"                       # flattened (no alpha)
    assert res.getpixel((0, 0)) == (255, 255, 255)  # white background baked in
    assert max(res.size) < 200                      # trimmed down from 400 to ~box+pad


def test_render_diagram_errors_when_render_unavailable(reg, monkeypatch):
    # When NO renderer is reachable (hosted API down AND no local renderer), the tool
    # returns an actionable error (not a crash, not client-side mermaid) so the model
    # can fix its syntax and retry. The browser NEVER renders mermaid source.
    import friday.tools.learning_media as lm
    monkeypatch.setattr(lm, "_render_via_ink", lambda code: (None, "offline"))
    monkeypatch.setattr(lm, "_render_via_local", lambda code, out: (None, "no renderer"))
    res = reg.execute("render_diagram", {
        "title": "Breakdown",
        "code": "flowchart TD\n    Animal --> Dog\n    Animal --> Cat"})
    assert not res.ok
    assert "offline" in res.error and "no renderer" in res.error
    assert "```mermaid" not in res.content
