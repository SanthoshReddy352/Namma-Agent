"""Generate the Roman persona portraits (Phase 9 W4) as original SVG coins.

Each persona is a struck coin: a metal disc with a beaded rim, a legend in
Roman capitals along the top, and a relief profile bust with the persona's
attributes (laurel, curls, beard). All shapes are drawn here, from scratch, so
the art is original. Output: public/brand/personas/<id>.svg

    python namma_agent/webui/scripts/make_roman_portraits.py
"""
from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "public" / "brand" / "personas"

METALS = {
    #           highlight   face        edge        relief-dark  relief-light ink
    "gold":   ("#fff3c4", "#e2b54e", "#9c6f17", "#a57722", "#fbe39a", "#5e4108"),
    "silver": ("#ffffff", "#c9ced6", "#7b828e", "#8a919c", "#eef1f5", "#3d434d"),
    "bronze": ("#f6d2b0", "#c08452", "#7a4a22", "#8d5730", "#e9b88c", "#4a2a10"),
}

# Profile facing right, in a 100x100 box (the coin maps it into its field).
PROFILE = (
    "M30 100 C32 90 34 84 33 78 C26 74 22 64 23 54 C24 40 34 28 48 25 "
    "C60 22 71 27 74 37 C75 41 75 44 76 47 C79 51 82 55 84 59 C82 61 80 61 78 61 "
    "C79 63 79 65 78 66 C79 67 78 69 77 70 C77 73 76 76 72 78 C68 80 64 80 61 80 "
    "C61 86 63 92 66 100 Z"
)
# Drapery over the shoulders (a toga's folds).
DRAPE = "M8 112 C14 98 26 92 40 92 C50 92 58 96 66 100 C76 98 88 100 96 112 Z"
DRAPE_FOLDS = ["M22 102 C30 98 38 98 44 101", "M58 102 C66 99 76 100 84 106", "M36 108 C44 104 52 104 58 108"]

PERSONAS = {
    "caesar":   {"metal": "gold",   "legend": "CAESAR",   "laurel": True,  "curls": False, "beard": False, "hair": "thin"},
    "cicero":   {"metal": "silver", "legend": "CICERO",   "laurel": False, "curls": True,  "beard": False, "hair": "short"},
    "augustus": {"metal": "gold",   "legend": "AVGVSTVS", "laurel": True,  "curls": True,  "beard": False, "hair": "fringe"},
    "seneca":   {"metal": "bronze", "legend": "SENECA",   "laurel": False, "curls": True,  "beard": True,  "hair": "short"},
    "aurelius": {"metal": "silver", "legend": "AVRELIVS", "laurel": True,  "curls": True,  "beard": True,  "hair": "full"},
}


def _arc_points(cx, cy, r, a0, a1, n):
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / (n - 1))),
             cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / (n - 1)))) for i in range(n)]


def _hair(kind, curls, dark, light):
    """Hair over the cranium: a cap shape, plus curl knots for curly heads."""
    parts = []
    cap = {
        "thin":   "M27 52 C26 40 35 29 48 27 C58 25 66 28 70 34 C62 31 52 31 44 34 C36 37 31 44 27 52 Z",
        "short":  "M25 56 C24 40 34 27 49 25 C61 23 70 28 73 36 C66 32 56 32 47 35 C38 38 31 46 25 56 Z",
        "fringe": "M24 58 C22 40 34 26 50 24 C62 22 71 27 74 36 L70 38 C64 33 55 33 47 36 C38 40 30 48 24 58 Z",
        "full":   "M23 60 C20 40 33 24 50 22 C63 21 73 27 75 37 L71 39 C65 33 55 33 46 37 C36 42 28 50 23 60 Z",
    }[kind]
    parts.append(f'<path d="{cap}" fill="{dark}" opacity="0.55"/>')
    if curls:
        for i, (x, y) in enumerate(_arc_points(49, 50, 23, 160, 290, 11)):
            r = 3.4 if i % 2 else 3.0
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{light}" stroke="{dark}" stroke-width="0.9"/>')
        for x, y in _arc_points(47, 50, 16, 175, 270, 6):
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.4" fill="{light}" stroke="{dark}" stroke-width="0.8"/>')
    else:
        for x, y in _arc_points(49, 50, 22, 175, 285, 9):
            parts.append(f'<path d="M{x:.1f} {y:.1f} q2 -2 4 0" fill="none" stroke="{dark}" stroke-width="0.9"/>')
    return "".join(parts)


def _laurel(dark, light):
    """A laurel wreath: paired leaves along the crown, ribbons tied at the nape."""
    leaves = []
    for i, (x, y) in enumerate(_arc_points(49, 50, 27, 150, 300, 12)):
        ang = 150 + 150 * i / 11 + 90
        for side in (-1, 1):
            leaves.append(
                f'<ellipse cx="{x:.1f}" cy="{y:.1f}" rx="2.2" ry="5.2" fill="{light}" stroke="{dark}" '
                f'stroke-width="0.8" transform="rotate({ang + side * 32:.1f} {x:.1f} {y:.1f}) translate(0 {side * -2.5:.1f})"/>')
    ribbons = (f'<path d="M24 62 C20 70 22 76 18 84" fill="none" stroke="{dark}" stroke-width="1.6"/>'
               f'<path d="M26 63 C25 72 28 78 25 87" fill="none" stroke="{dark}" stroke-width="1.6"/>')
    return ribbons + "".join(leaves)


def _beard(dark, light):
    jaw = ("M58 62 C60 70 64 76 70 78 C74 77 77 74 78 70 C79 74 77 80 72 83 "
           "C65 86 58 83 55 76 C54 71 55 66 58 62 Z")
    spots = [(59, 66), (61, 71), (64, 75), (67, 79), (71, 81), (75, 79), (77, 74), (57, 72),
             (60, 77), (63, 81), (67, 84), (72, 85), (76, 82), (58, 81), (62, 85), (69, 74), (73, 76)]
    curls = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.2" fill="{light}" stroke="{dark}" stroke-width="0.75"/>'
                    for x, y in spots)
    mustache = f'<path d="M73 62 C75 63 77 63 79 62" fill="none" stroke="{dark}" stroke-width="1.1"/>'
    return f'<path d="{jaw}" fill="{dark}" opacity="0.6"/>' + curls + mustache


def coin(pid: str, spec: dict) -> str:
    hi, face, edge, rdark, rlight, ink = METALS[spec["metal"]]
    # Beads around the rim.
    beads = "".join(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.25" fill="{rlight}" stroke="{rdark}" stroke-width="0.4"/>'
                    for x, y in _arc_points(60, 60, 52.5, 0, 354, 60))
    bust = [
        f'<path d="{DRAPE}" fill="url(#relief-{pid})" stroke="{rdark}" stroke-width="1.2"/>',
        *(f'<path d="{d}" fill="none" stroke="{rdark}" stroke-width="1" opacity="0.8"/>' for d in DRAPE_FOLDS),
        f'<path d="{PROFILE}" fill="url(#relief-{pid})" stroke="{rdark}" stroke-width="1.4" stroke-linejoin="round"/>',
        # Highlight along the face edge (light from the upper left), ear, eye, brow, mouth.
        f'<path d="M74 37 C75 41 75 44 76 47 C79 51 82 55 84 59" fill="none" stroke="{rlight}" stroke-width="1" opacity="0.9"/>',
        f'<ellipse cx="46" cy="56" rx="3.4" ry="5" fill="none" stroke="{rdark}" stroke-width="1.1"/>',
        f'<path d="M66 46 C68 44.5 70.5 44.5 72 46 C70.5 47.3 68 47.3 66 46 Z" fill="{rdark}"/>',
        f'<path d="M64 42 C67 40 71 40 74 42" fill="none" stroke="{rdark}" stroke-width="1.1"/>',
        f'<path d="M73 65.5 C74.5 66 76 66 77.5 65.5" fill="none" stroke="{rdark}" stroke-width="0.9"/>',
        _hair(spec["hair"], spec["curls"], rdark, rlight),
    ]
    if spec["beard"]:
        bust.append(_beard(rdark, rlight))
    if spec["laurel"]:
        bust.append(_laurel(rdark, rlight))
    legend = spec["legend"]
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" role="img" aria-label="{legend.title()}">
  <!-- Namma Agent persona portrait ({pid}). Original art, generated by scripts/make_roman_portraits.py. -->
  <defs>
    <radialGradient id="metal-{pid}" cx="0.35" cy="0.3" r="0.8">
      <stop offset="0" stop-color="{hi}"/><stop offset="0.55" stop-color="{face}"/><stop offset="1" stop-color="{edge}"/>
    </radialGradient>
    <linearGradient id="relief-{pid}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{rlight}"/><stop offset="1" stop-color="{face}"/>
    </linearGradient>
    <clipPath id="field-{pid}"><circle cx="60" cy="60" r="47"/></clipPath>
    <path id="legend-{pid}" d="M18 64 A42 42 0 0 1 102 64"/>
  </defs>
  <circle cx="60" cy="60" r="59" fill="{edge}"/>
  <circle cx="60" cy="60" r="57" fill="url(#metal-{pid})"/>
  <circle cx="60" cy="60" r="55.5" fill="none" stroke="{rdark}" stroke-width="0.8" opacity="0.7"/>
  {beads}
  <circle cx="60" cy="60" r="48.5" fill="none" stroke="{rdark}" stroke-width="0.8" opacity="0.6"/>
  <g clip-path="url(#field-{pid})">
    <g transform="translate(17 27) scale(0.86)">
      {"".join(bust)}
    </g>
  </g>
  <text font-family="Cinzel, 'Trajan Pro', Georgia, 'Times New Roman', serif" font-size="9.5" font-weight="700"
        letter-spacing="2.6" fill="{ink}" text-anchor="middle">
    <textPath href="#legend-{pid}" startOffset="50%">{legend}</textPath>
  </text>
</svg>
'''


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for pid, spec in PERSONAS.items():
        (OUT / f"{pid}.svg").write_text(coin(pid, spec), encoding="utf-8")
        print("wrote", OUT / f"{pid}.svg")


if __name__ == "__main__":
    main()
