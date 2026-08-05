"""Render an Excalidraw scene to a self-contained, pannable HTML page.

The excalidraw MCP server draws into a host-side widget Namma Agent cannot run (see
:mod:`namma_agent.mcp.widgets`), and a share link only tells the user to go look
somewhere else. This module closes that gap locally: it rasterises the scene to SVG
and wraps it in the page format the chat already renders inline —
``data/media/sims/<id>.html``, which :file:`Markdown.jsx` turns into a sandboxed card
with expand-to-fullscreen.

No network, no CDN, no npm: the SVG is generated here, so a diagram shows up in the
chat even with the machine offline.
"""
from __future__ import annotations

import html
import uuid
from pathlib import Path
from typing import Optional

from namma_agent.config import data_dir

#: Excalidraw's font families. 1 is its hand-drawn Virgil; dense architecture
#: diagrams read better in a clean sans, so 1 and 2 share one stack.
_FONTS = {
    1: '"Segoe UI", system-ui, -apple-system, sans-serif',
    2: '"Segoe UI", system-ui, -apple-system, sans-serif',
    3: '"Cascadia Code", "Consolas", ui-monospace, monospace',
}
_DASH = {"dashed": "12 8", "dotted": "2 6"}


def _esc(text: str) -> str:
    return html.escape(text, quote=False)


def _radius(el: dict) -> float:
    """Excalidraw's adaptive corner radius for ``roundness: {type: 3}``."""
    if not el.get("roundness"):
        return 0.0
    return min(min(el["width"], el["height"]) * 0.25, 32.0)


def _stroke_attrs(el: dict) -> str:
    dash = _DASH.get(el.get("strokeStyle") or "solid")
    out = f'stroke="{el["strokeColor"]}" stroke-width="{el.get("strokeWidth", 2)}"'
    out += ' stroke-linecap="round" stroke-linejoin="round"'
    return out + (f' stroke-dasharray="{dash}"' if dash else "")


def _fill(el: dict) -> str:
    bg = el.get("backgroundColor") or "transparent"
    return "none" if bg == "transparent" else bg


def _shape(el: dict, markers: dict) -> str:
    kind = el["type"]
    x, y, w, h = el["x"], el["y"], el["width"], el["height"]
    stroke, fill = _stroke_attrs(el), _fill(el)

    if kind == "rectangle":
        r = _radius(el)
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" ry="{r}" fill="{fill}" {stroke}/>'
    if kind == "ellipse":
        return (f'<ellipse cx="{x + w / 2}" cy="{y + h / 2}" rx="{w / 2}" ry="{h / 2}" '
                f'fill="{fill}" {stroke}/>')
    if kind == "diamond":
        pts = f"{x + w / 2},{y} {x + w},{y + h / 2} {x + w / 2},{y + h} {x},{y + h / 2}"
        return f'<polygon points="{pts}" fill="{fill}" {stroke}/>'
    if kind in ("arrow", "line"):
        pts = " ".join(f"{x + p[0]},{y + p[1]}" for p in (el.get("points") or []))
        if not pts:
            return ""
        ends = ""
        if el.get("endArrowhead"):
            ends += f' marker-end="url(#{markers[el["strokeColor"]]})"'
        if el.get("startArrowhead"):
            ends += f' marker-start="url(#{markers[el["strokeColor"]]}-s)"'
        closed = kind == "line" and len(el.get("points") or []) > 2
        tag = "polygon" if closed and fill != "none" else "polyline"
        return f'<{tag} points="{pts}" fill="{fill if closed else "none"}" {stroke}{ends}/>'
    if kind == "text":
        size = el.get("fontSize", 20)
        font = _FONTS.get(el.get("fontFamily", 1), _FONTS[1])
        anchor = {"center": "middle", "right": "end"}.get(el.get("textAlign"), "start")
        tx = {"middle": x + w / 2, "end": x + w}.get(anchor, x)
        lines = str(el.get("text", "")).split("\n")
        out = []
        for i, line in enumerate(lines):
            out.append(f'<text x="{tx}" y="{y + size * (0.95 + 1.25 * i)}" '
                       f'text-anchor="{anchor}" font-family={font!r} font-size="{size}" '
                       f'fill="{el["strokeColor"]}" style="white-space:pre">{_esc(line)}</text>')
        return "".join(out)
    return ""


def scene_to_svg(elements: list[dict], pad: float = 40.0) -> str:
    """Render normalized Excalidraw elements to standalone SVG markup."""
    drawable = [e for e in elements if not e.get("isDeleted")]
    if not drawable:
        raise ValueError("no drawable elements")

    xs = [e["x"] for e in drawable] + [e["x"] + e["width"] for e in drawable]
    ys = [e["y"] for e in drawable] + [e["y"] + e["height"] for e in drawable]
    minx, miny = min(xs) - pad, min(ys) - pad
    width, height = max(xs) - minx + pad, max(ys) - miny + pad

    # One arrowhead marker per stroke colour — markers can't inherit the referring
    # element's stroke without `context-stroke`, which isn't safe across webviews.
    colors = {e["strokeColor"] for e in drawable if e["type"] in ("arrow", "line")}
    markers, defs = {}, []
    for i, color in enumerate(sorted(colors)):
        mid = f"ah{i}"
        markers[color] = mid
        for suffix, path in ((mid, "M0,0 L10,3.5 L0,7 z"), (f"{mid}-s", "M10,0 L0,3.5 L10,7 z")):
            defs.append(f'<marker id="{suffix}" markerWidth="10" markerHeight="7" '
                        f'refX="{9 if suffix == mid else 1}" refY="3.5" orient="auto" '
                        f'markerUnits="strokeWidth"><path d="{path}" fill="{color}"/></marker>')

    body = []
    for el in drawable:
        markup = _shape(el, markers)
        if not markup:
            continue
        opacity = el.get("opacity", 100) / 100
        body.append(markup if opacity >= 1 else f'<g opacity="{opacity:g}">{markup}</g>')

    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{minx} {miny} {width} {height}" '
            f'width="{width}" height="{height}">'
            f'<defs>{"".join(defs)}</defs>{"".join(body)}</svg>')


def scene_title(elements: list[dict], fallback: str = "Diagram") -> str:
    """The scene's biggest standalone text — its title, for the card caption."""
    texts = [e for e in elements if e["type"] == "text" and not e.get("containerId")
             and str(e.get("text", "")).strip()]
    if not texts:
        return fallback
    return str(max(texts, key=lambda e: e.get("fontSize", 0))["text"]).split("\n")[0][:80]


_PAGE = """<!doctype html>
<meta charset="utf-8"><title>{title}</title>
<style>
  html,body{{margin:0;height:100%;background:#fff;overflow:hidden;
    font-family:"Segoe UI",system-ui,sans-serif}}
  #vp{{width:100%;height:100%;cursor:grab;touch-action:none}}
  #vp.drag{{cursor:grabbing}}
  #vp svg{{transform-origin:0 0;will-change:transform;max-width:none}}
  #bar{{position:fixed;right:10px;bottom:10px;display:flex;gap:6px}}
  #bar button{{border:1px solid #d9d9e0;background:#fff;color:#333;border-radius:8px;
    width:30px;height:30px;font-size:15px;cursor:pointer;line-height:1}}
  #bar button:hover{{background:#f2f2f5}}
</style>
<div id="vp">{svg}</div>
<div id="bar">
  <button id="i" title="Zoom in">+</button>
  <button id="o" title="Zoom out">&minus;</button>
  <button id="r" title="Reset">&#8634;</button>
</div>
<script>
(function(){{
  var vp=document.getElementById('vp'),svg=vp.querySelector('svg');
  var w=svg.width.baseVal.value,h=svg.height.baseVal.value;
  var s=1,x=0,y=0,base=1;
  function apply(){{svg.style.transform='translate('+x+'px,'+y+'px) scale('+s+')';}}
  function fit(){{
    base=Math.min(vp.clientWidth/w,vp.clientHeight/h);
    s=base;x=(vp.clientWidth-w*s)/2;y=(vp.clientHeight-h*s)/2;apply();
  }}
  function zoom(f,cx,cy){{
    var ns=Math.min(base*12,Math.max(base*0.4,s*f));
    x=cx-(cx-x)*(ns/s);y=cy-(cy-y)*(ns/s);s=ns;apply();
  }}
  vp.addEventListener('wheel',function(e){{
    e.preventDefault();zoom(e.deltaY<0?1.12:1/1.12,e.offsetX,e.offsetY);
  }},{{passive:false}});
  var dragging=false,px=0,py=0;
  vp.addEventListener('pointerdown',function(e){{
    dragging=true;px=e.clientX;py=e.clientY;vp.classList.add('drag');
    vp.setPointerCapture(e.pointerId);
  }});
  vp.addEventListener('pointermove',function(e){{
    if(!dragging)return;x+=e.clientX-px;y+=e.clientY-py;px=e.clientX;py=e.clientY;apply();
  }});
  vp.addEventListener('pointerup',function(e){{
    dragging=false;vp.classList.remove('drag');vp.releasePointerCapture(e.pointerId);
  }});
  document.getElementById('i').onclick=function(){{zoom(1.25,vp.clientWidth/2,vp.clientHeight/2);}};
  document.getElementById('o').onclick=function(){{zoom(0.8,vp.clientWidth/2,vp.clientHeight/2);}};
  document.getElementById('r').onclick=fit;
  window.addEventListener('resize',fit);fit();
}})();
</script>
"""


def write_scene_page(elements: list[dict], title: str = "",
                     media_root: Optional[Path] = None) -> tuple[str, str]:
    """Render ``elements`` into ``data/media/sims/<id>.html``.

    Returns ``(url, title)`` — the URL is the ``/api/media/sims/…`` path the chat
    renders as an inline, zoomable card.
    """
    caption = title or scene_title(elements)
    page = _PAGE.format(title=_esc(caption), svg=scene_to_svg(elements))
    root = media_root or (data_dir() / "media")
    sims = root / "sims"
    sims.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}.html"
    (sims / name).write_text(page, encoding="utf-8")
    return f"/api/media/sims/{name}", caption
