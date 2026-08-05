"""Local rendering of an Excalidraw scene into the inline chat card.

The point of this path is that a diagram shows up *in the conversation* without a
widget host and without the network, so these tests assert on the produced markup.
"""
from __future__ import annotations

import json
import re

import pytest

from namma_agent.mcp.excalidraw_render import (
    scene_title,
    scene_to_svg,
    write_scene_page,
)
from namma_agent.mcp.widgets import normalize_elements

SCENE = [
    {"type": "text", "id": "t", "x": 0, "y": -40, "text": "My Architecture", "fontSize": 28},
    {"type": "rectangle", "id": "r1", "x": 0, "y": 0, "width": 200, "height": 80,
     "backgroundColor": "#a5d8ff", "roundness": {"type": 3},
     "label": {"text": "Gateway", "fontSize": 16}},
    {"type": "ellipse", "id": "e1", "x": 300, "y": 0, "width": 120, "height": 80,
     "backgroundColor": "#b2f2bb"},
    {"type": "diamond", "id": "d1", "x": 500, "y": 0, "width": 100, "height": 80},
    {"type": "arrow", "id": "a1", "x": 200, "y": 40, "width": 100, "height": 0,
     "points": [[0, 0], [100, 0]], "endArrowhead": "arrow"},
]


def _svg():
    return scene_to_svg(normalize_elements(json.dumps(SCENE)))


# ── svg ───────────────────────────────────────────────────────────────────────

def test_every_shape_kind_reaches_the_svg():
    svg = _svg()
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "<rect" in svg and "<ellipse" in svg and "<polygon" in svg and "<polyline" in svg
    assert ">Gateway<" in svg and ">My Architecture<" in svg


def test_viewbox_covers_the_whole_scene_with_padding():
    svg = _svg()
    minx, miny, w, h = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg)[1].split())
    assert minx <= -40 and miny <= -80          # padding beyond the leftmost/topmost
    assert minx + w >= 640 and miny + h >= 120  # past the rightmost/bottommost


def test_arrowhead_marker_is_defined_and_referenced():
    svg = _svg()
    marker_id = re.search(r'<marker id="(ah\d+)"', svg)[1]
    assert f'marker-end="url(#{marker_id})"' in svg


def test_fill_and_opacity_are_honoured():
    svg = scene_to_svg(normalize_elements([
        {"type": "rectangle", "id": "z", "x": 0, "y": 0, "width": 10, "height": 10,
         "backgroundColor": "#dbe4ff", "opacity": 30},
        {"type": "rectangle", "id": "p", "x": 0, "y": 0, "width": 10, "height": 10},
    ]))
    assert 'fill="#dbe4ff"' in svg and 'opacity="0.3"' in svg
    assert 'fill="none"' in svg  # transparent default stays unfilled


def test_dashed_stroke_becomes_a_dasharray():
    svg = scene_to_svg(normalize_elements([
        {"type": "rectangle", "id": "z", "x": 0, "y": 0, "width": 10, "height": 10,
         "strokeStyle": "dashed"}]))
    assert "stroke-dasharray=" in svg


def test_text_is_escaped_not_injected():
    svg = scene_to_svg(normalize_elements([
        {"type": "text", "id": "t", "x": 0, "y": 0,
         "text": "<script>alert(1)</script> A & B"}]))
    assert "<script>" not in svg and "&lt;script&gt;" in svg and "&amp;" in svg


def test_multiline_text_becomes_separate_baselines():
    svg = scene_to_svg(normalize_elements([
        {"type": "text", "id": "t", "x": 0, "y": 0, "text": "one\ntwo\nthree"}]))
    assert svg.count("<text") == 3


def test_empty_scene_raises():
    with pytest.raises(ValueError):
        scene_to_svg([])


# ── title + page ──────────────────────────────────────────────────────────────

def test_title_is_the_largest_standalone_text():
    assert scene_title(normalize_elements(json.dumps(SCENE))) == "My Architecture"


def test_bound_labels_are_never_mistaken_for_the_title():
    els = normalize_elements([
        {"type": "rectangle", "id": "r", "x": 0, "y": 0, "width": 10, "height": 10,
         "label": {"text": "Inside", "fontSize": 99}}])
    assert scene_title(els, fallback="Diagram") == "Diagram"


def test_page_is_self_contained_and_lands_in_the_sims_pipeline(tmp_path):
    els = normalize_elements(json.dumps(SCENE))
    url, title = write_scene_page(els, media_root=tmp_path)

    assert url.startswith("/api/media/sims/") and url.endswith(".html")
    assert title == "My Architecture"

    page = (tmp_path / "sims" / url.rsplit("/", 1)[1]).read_text(encoding="utf-8")
    assert "<svg" in page and ">Gateway<" in page
    # nothing fetched at view time — no CDN, no npm, works offline. The SVG
    # namespace is a bare identifier, never dereferenced, so it doesn't count.
    fetchable = page.replace('xmlns="http://www.w3.org/2000/svg"', "")
    assert "http://" not in fetchable and "https://" not in fetchable
    assert "<script src" not in page and "@import" not in page
    # the pan/zoom controls the card relies on
    assert 'id="vp"' in page and "pointerdown" in page and "wheel" in page


def test_page_title_is_escaped(tmp_path):
    els = normalize_elements([
        {"type": "text", "id": "t", "x": 0, "y": 0, "text": "<b>x</b>", "fontSize": 30},
        {"type": "rectangle", "id": "r", "x": 0, "y": 0, "width": 10, "height": 10}])
    url, _ = write_scene_page(els, media_root=tmp_path)
    page = (tmp_path / "sims" / url.rsplit("/", 1)[1]).read_text(encoding="utf-8")
    assert "<title>&lt;b&gt;x&lt;/b&gt;</title>" in page
