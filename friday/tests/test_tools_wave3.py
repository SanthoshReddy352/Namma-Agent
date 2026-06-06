"""Phase 7 Wave 3 — weather / smart_home / news / vision / documents / scheduler.

Network/subprocess/CLI paths are monkeypatched so the suite is offline and fast.
"""
from __future__ import annotations

import json

import pytest

from friday.core.safety import is_destructive
from friday.core.tools import ToolRegistry
from friday.tools import load_tools
from friday.tools import documents as docmod
from friday.tools import news as newsmod
from friday.tools import scheduler as schedmod
from friday.tools import smart_home as ha
from friday.tools import vision as vis
from friday.tools import weather as wx


@pytest.fixture
def reg():
    return load_tools(ToolRegistry())


def test_autodiscovery_registers_wave3_tools(reg):
    for name in ("get_weather", "ha_turn_on", "ha_turn_off", "ha_get_state",
                 "ha_set_temperature", "get_news", "take_screenshot",
                 "read_text_from_image", "read_document",
                 "add_reminder", "list_reminders", "remove_reminder"):
        assert name in reg, name


# ── weather ───────────────────────────────────────────────────────────────────

def test_weather_formats_report(reg, monkeypatch, tmp_path):
    monkeypatch.setattr(wx, "_cache_path", lambda name: str(tmp_path / "w.json"))
    monkeypatch.setattr(wx, "_geocode",
                        lambda loc: {"name": "Mumbai", "country": "India", "lat": 19.0, "lon": 72.0})
    monkeypatch.setattr(wx, "_get_json", lambda url, params: {
        "current": {"temperature_2m": 30, "apparent_temperature": 33,
                    "relative_humidity_2m": 70, "wind_speed_10m": 12, "weather_code": 2}})
    r = reg.execute("get_weather", {"location": "Mumbai"})
    assert r.ok and "Mumbai" in r.content and "partly cloudy" in r.content


def test_weather_requires_location(reg):
    assert not reg.execute("get_weather", {"location": ""}).ok


# ── smart_home ────────────────────────────────────────────────────────────────

def test_ha_not_configured(reg, monkeypatch):
    monkeypatch.setattr(ha, "_cfg", lambda: {})
    r = reg.execute("ha_turn_on", {"entity": "light.x"})
    assert not r.ok and "not configured" in r.error


def test_ha_resolves_alias_and_calls(monkeypatch):
    monkeypatch.setattr(ha, "_cfg", lambda: {
        "url": "http://hass:8123", "token": "tok", "aliases": {"bedroom lights": "light.bedroom"}})
    captured = {}
    monkeypatch.setattr(ha, "_request",
                        lambda base, token, method, path, data=None: captured.update(
                            {"method": method, "path": path, "data": data}) or {})
    r = ha._turn_on({"entity": "bedroom lights"})
    assert r.ok and captured["path"] == "services/light/turn_on"
    assert captured["data"]["entity_id"] == "light.bedroom"


def test_ha_get_state(monkeypatch):
    monkeypatch.setattr(ha, "_cfg", lambda: {"url": "http://h:8123", "token": "t"})
    monkeypatch.setattr(ha, "_request", lambda *a, **k: {"state": "on"})
    r = ha._get_state({"entity": "light.kitchen"})
    assert r.ok and "is on" in r.content


def test_ha_mutators_destructive(reg):
    for name in ("ha_turn_on", "ha_turn_off", "ha_set_temperature"):
        assert reg.get(name).destructive is True and is_destructive(name)
    assert reg.get("ha_get_state").destructive is False


# ── news ──────────────────────────────────────────────────────────────────────

def test_news_lists_headlines(reg, monkeypatch):
    monkeypatch.setattr(newsmod, "_fetch_feed",
                        lambda url, limit: [{"title": "Big story", "url": "https://x/1"}])
    r = reg.execute("get_news", {"category": "technology", "limit": 1})
    assert r.ok and "Big story" in r.content


def test_news_unknown_category(reg):
    assert not reg.execute("get_news", {"category": "sports"}).ok


def test_news_parse_atom_and_rss():
    rss = b"""<rss><channel><item><title>RSS One</title><link>http://a</link></item></channel></rss>"""
    import friday.tools.news as n
    import urllib.request

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return rss
    import contextlib
    with contextlib.ExitStack() as stack:
        stack.enter_context(_patch(urllib.request, "urlopen", lambda req, timeout=10: _Resp()))
        items = n._fetch_feed("http://feed", 5)
    assert items and items[0]["title"] == "RSS One"


# ── vision ────────────────────────────────────────────────────────────────────

def test_screenshot_no_tool(reg, monkeypatch):
    monkeypatch.setattr(vis, "_screenshot_argv", lambda out: None)
    r = reg.execute("take_screenshot", {})
    assert not r.ok and "no screenshot tool" in r.error


def test_screenshot_success(reg, monkeypatch, tmp_path):
    out = tmp_path / "shot.png"
    def _fake_argv(o):
        return ["true"]  # noqa
    def _fake_run(argv, **kw):
        out.write_bytes(b"\x89PNG fake")
        class R: stderr = ""; returncode = 0
        return R()
    monkeypatch.setattr(vis, "_screenshot_argv", _fake_argv)
    monkeypatch.setattr(vis.subprocess, "run", _fake_run)
    r = reg.execute("take_screenshot", {"path": str(out)})
    assert r.ok and r.data["path"].endswith("shot.png")


def test_read_text_needs_tesseract(reg, monkeypatch, tmp_path):
    img = tmp_path / "a.png"
    img.write_bytes(b"x")
    monkeypatch.setattr(vis.shutil, "which", lambda name: None)
    r = reg.execute("read_text_from_image", {"path": str(img)})
    assert not r.ok and "tesseract" in r.error


# ── documents ─────────────────────────────────────────────────────────────────

def test_read_document_plaintext(reg, tmp_path):
    f = tmp_path / "note.md"
    f.write_text("# Title\nbody text")
    r = reg.execute("read_document", {"path": str(f)})
    assert r.ok and "body text" in r.content


def test_read_document_unsupported(reg, tmp_path):
    f = tmp_path / "x.xyz"
    f.write_text("data")
    r = reg.execute("read_document", {"path": str(f)})
    assert not r.ok and "unsupported" in r.error


def test_read_document_missing(reg, tmp_path):
    r = reg.execute("read_document", {"path": str(tmp_path / "nope.txt")})
    assert not r.ok


# ── scheduler ─────────────────────────────────────────────────────────────────

def test_reminder_add_list_remove(reg, monkeypatch, tmp_path):
    store = tmp_path / "reminders.json"
    monkeypatch.setattr(schedmod, "_store_path", lambda: store)

    add = reg.execute("add_reminder", {"text": "call mom", "when": "tomorrow"})
    assert add.ok and add.data["id"] == 1
    listed = reg.execute("list_reminders", {})
    assert "call mom" in listed.content
    rem = reg.execute("remove_reminder", {"id": 1})
    assert rem.ok
    assert json.loads(store.read_text()) == []


def test_remove_missing_reminder(reg, monkeypatch, tmp_path):
    monkeypatch.setattr(schedmod, "_store_path", lambda: tmp_path / "r.json")
    r = reg.execute("remove_reminder", {"id": 99})
    assert not r.ok


def test_remove_reminder_destructive(reg):
    assert reg.get("remove_reminder").destructive is True
    assert reg.get("add_reminder").destructive is False


# small helper: monkeypatch via ExitStack without pytest fixture
class _patch:
    def __init__(self, obj, attr, value):
        self.obj, self.attr, self.value = obj, attr, value

    def __enter__(self):
        self.old = getattr(self.obj, self.attr)
        setattr(self.obj, self.attr, self.value)
        return self

    def __exit__(self, *a):
        setattr(self.obj, self.attr, self.old)
        return False
