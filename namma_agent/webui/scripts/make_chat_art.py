"""Generate the chat background's layers (Phase 9 W1, slice 4).

Every layer is a single-channel mask or a neutral-grey texture, so the page
colours it from theme tokens (CSS mask + background-color, or a blend mode):

  paper.webp    crumpled paper, mid-grey = neutral (dark themes, `soft-light`)
  paper-shade.webp the same, white = neutral (light themes, `multiply`)
  wash-a.webp   primary paint: a dry-brush sweep + the owner's ink wash (40.png)
  wash-b.webp   secondary paint (the mode's colour): a counter-stroke + the
                owner's ink splatter (14.jpg)
  art-drip.webp the ink-dripping hand (19.png)
  art-masks.webp the theatre masks (10.png)
  art-rise.webp the hand rising from below (20.png)

Masks are saved as white WebP with the paint in the alpha channel, so a plain
CSS `mask` (alpha mode) works in every engine; the textures are greyscale.

Usage: python scripts/make_chat_art.py <dir with the owner's PNGs> <out dir>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

W, H = 1920, 1200
RNG = np.random.default_rng(1182)


def save_mask(arr: np.ndarray, path: Path, quality: int = 82) -> None:
    """White with the mask in alpha: works as a plain CSS `mask` everywhere."""
    a = np.clip(arr * 255, 0, 255).astype(np.uint8)
    img = Image.merge("LA", (Image.new("L", (a.shape[1], a.shape[0]), 255), Image.fromarray(a, "L")))
    img.convert("RGBA").save(path, "WEBP", quality=quality, method=6, alpha_quality=50)
    print(f"{path.name}: {img.size}, {path.stat().st_size // 1024} KB")


def save_gray(arr: np.ndarray, path: Path, quality: int = 82) -> None:
    img = Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8), "L")
    img.save(path, "WEBP", quality=quality, method=6)
    print(f"{path.name}: {img.size}, {path.stat().st_size // 1024} KB")


def fbm(h: int, w: int, octaves: int = 5, base: float = 64.0) -> np.ndarray:
    """Fractal value noise in [0, 1]."""
    out = np.zeros((h, w))
    amp, total = 1.0, 0.0
    for o in range(octaves):
        cell = max(2, int(base / (2 ** o)))
        small = RNG.random((h // cell + 2, w // cell + 2))
        big = np.array(Image.fromarray((small * 255).astype(np.uint8)).resize(
            ((w // cell + 2) * cell, (h // cell + 2) * cell), Image.BICUBIC))[:h, :w] / 255.0
        out += amp * big
        total += amp
        amp *= 0.5
    return out / total


# ── Paper crush ────────────────────────────────────────────────────────────
def _crumple(sh: int, sw: int, cells: int, warp: float) -> np.ndarray:
    """Height field of one crumple scale: Worley F2 - F1 (zero on every crease,
    peaking inside each facet), with each facet randomly pushed up or down so
    folds alternate between ridges and valleys. Continuous across creases."""
    from scipy.spatial import cKDTree
    yy, xx = np.mgrid[0:sh, 0:sw].astype(np.float64)
    wx = (fbm(sh, sw, octaves=3, base=sw / 5) - 0.5) * warp
    wy = (fbm(sh, sw, octaves=3, base=sw / 5) - 0.5) * warp
    seeds = RNG.random((cells, 2)) * [sw, sh]
    d, idx = cKDTree(seeds).query(np.stack([(xx + wx).ravel(), (yy + wy).ravel()], 1), k=2)
    f = (d[:, 1] - d[:, 0])
    sign = RNG.choice((-1.0, 1.0), cells) * (0.6 + 0.4 * RNG.random(cells))
    h = (f * sign[idx[:, 0]]).reshape(sh, sw)
    return h / (np.sqrt(sh * sw / cells) + 1e-9)


def paper() -> np.ndarray:
    """Crumpled paper: three crumple scales lit from the top-left, a soft
    undulation, fibre grain and speckle. Returned around 0.5 (neutral)."""
    sh, sw = H // 2, W // 2
    h = (1.0 * _crumple(sh, sw, 60, 120) + 0.55 * _crumple(sh, sw, 260, 50)
         + 0.25 * _crumple(sh, sw, 1100, 20))
    h = ndimage.gaussian_filter(h, 0.7)
    gy, gx = np.gradient(h)
    shade = -(gx * -0.6 + gy * -0.8)
    shade /= np.percentile(np.abs(shade), 99) + 1e-9
    undulate = fbm(sh, sw, octaves=3, base=sw / 3) - 0.5
    img = 0.5 + 0.17 * np.clip(shade, -1.3, 1.3) + 0.10 * undulate
    img = np.array(Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)) / 255.0
    grain = ndimage.gaussian_filter(RNG.standard_normal((H, W)), (0.6, 2.2))
    grain /= np.abs(grain).max()
    speck = (RNG.random((H, W)) > 0.9985) * RNG.choice((-1, 1), (H, W)) * 0.10
    img += 0.045 * grain + speck
    return np.clip(img, 0, 1)


# ── Dry-brush strokes ──────────────────────────────────────────────────────
def bezier(p0, p1, p2, p3, n):
    t = np.linspace(0, 1, n)[:, None]
    return ((1 - t) ** 3) * p0 + 3 * ((1 - t) ** 2) * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def brush_stroke(points, width: float, dryness: float = 0.55, seed: int = 0) -> np.ndarray:
    """A loaded brush dragged along a cubic Bezier.

    Every pixel near the path gets (t, u): how far along the stroke it is and
    its signed offset across it (-1..1). From those: a body with ragged edges,
    bristle streaks that drift along the stroke, a dry-brush tail where the
    streaks break up, pigment pooling at the edges and a faint wet bloom."""
    from scipy.spatial import cKDTree
    rng = np.random.default_rng(seed or int(RNG.integers(1 << 30)))
    path = bezier(*[np.array(p, float) for p in points], 1400)
    tang = np.gradient(path, axis=0)
    tang /= np.linalg.norm(tang, axis=1, keepdims=True) + 1e-9
    n = len(path)
    t_all = np.linspace(0, 1, n)
    # Pressure: quick attack, swell, long lift-off.
    pressure = np.clip(np.minimum(t_all / 0.06, 1) * (1 - 0.45 * t_all ** 2), 0, 1)
    hw = width / 2
    x0, y0 = int(max(0, path[:, 0].min() - hw - 4)), int(max(0, path[:, 1].min() - hw - 4))
    x1, y1 = int(min(W, path[:, 0].max() + hw + 4)), int(min(H, path[:, 1].max() + hw + 4))
    canvas = np.zeros((H, W))
    if x1 <= x0 or y1 <= y0:
        return canvas
    yy, xx = np.mgrid[y0:y1, x0:x1]
    pts = np.stack([xx.ravel(), yy.ravel()], 1).astype(float)
    d, idx = cKDTree(path).query(pts, distance_upper_bound=hw * 1.2)
    ok = np.isfinite(d)
    idx = np.where(ok, idx, 0)
    rel = pts - path[idx]
    side = np.sign(tang[idx, 0] * rel[:, 1] - tang[idx, 1] * rel[:, 0])
    t = t_all[idx]
    pr = pressure[idx]
    u = np.where(ok, side * d / (hw * (0.55 + 0.45 * pr) + 1e-9), 9)
    # Noise grids indexed by (t, u): bristle streaks + a slow edge wobble.
    T, U = 90, 520
    streak = ndimage.gaussian_filter(rng.random((T, U)), (6, 0.8))
    streak = (streak - streak.min()) / (np.ptp(streak) + 1e-9)
    wob = ndimage.gaussian_filter(rng.standard_normal((T, 2)), (3, 0))
    wob /= np.abs(wob).max() + 1e-9
    ti = t * (T - 1)
    ui = np.clip((u + 1) / 2, 0, 1) * (U - 1)
    s = ndimage.map_coordinates(streak, [ti, ui], order=1)
    edge = 1 + 0.18 * np.where(u < 0, ndimage.map_coordinates(wob[:, 0], [ti], order=1),
                               ndimage.map_coordinates(wob[:, 1], [ti], order=1))
    au = np.abs(u) / edge
    body = np.clip((1.0 - au) / 0.12, 0, 1)
    # Dry brush: the threshold rises over the last part of the stroke.
    thr = dryness * np.clip((t - 0.35) / 0.65, 0, 1) ** 1.2
    alive = np.clip((s - thr) / 0.08, 0, 1)
    ink = body * (0.5 + 0.5 * s) * alive * (0.35 + 0.65 * pr)
    canvas[y0:y1, x0:x1] = np.where(ok, ink, 0).reshape(yy.shape)
    # Pigment pools at the edges; a wet bloom halos the stroke.
    blur = ndimage.gaussian_filter(canvas, 5)
    canvas = canvas + 0.45 * np.clip(canvas - blur, 0, None)
    canvas = np.maximum(canvas, 0.22 * ndimage.gaussian_filter(canvas, 22))
    return np.clip(canvas, 0, 1)


def load_mask(path: Path, invert_luma: bool = True) -> np.ndarray:
    """Owner art → 0..1 'ink' mask: dark, opaque pixels become paint."""
    im = Image.open(path).convert("RGBA")
    a = np.asarray(im, float) / 255.0
    luma = 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]
    ink = (1 - luma) if invert_luma else luma
    return ink * a[..., 3]


def place(canvas: np.ndarray, mask: np.ndarray, cx: float, cy: float, scale: float, angle: float = 0.0) -> None:
    img = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8), "L")
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS)
    if angle:
        img = img.rotate(angle, resample=Image.BICUBIC, expand=True)
    m = np.asarray(img, float) / 255.0
    x0, y0 = int(cx - m.shape[1] / 2), int(cy - m.shape[0] / 2)
    xs0, ys0 = max(0, x0), max(0, y0)
    xs1, ys1 = min(W, x0 + m.shape[1]), min(H, y0 + m.shape[0])
    if xs1 <= xs0 or ys1 <= ys0:
        return
    sub = m[ys0 - y0:ys1 - y0, xs0 - x0:xs1 - x0]
    canvas[ys0:ys1, xs0:xs1] = np.maximum(canvas[ys0:ys1, xs0:xs1], sub)


def edge_falloff() -> np.ndarray:
    """1 at the edges, ~0 in the middle reading column — keeps paint off the text."""
    xx = np.abs(np.linspace(-1, 1, W))[None, :]
    yy = np.abs(np.linspace(-1, 1, H))[:, None]
    col = np.clip((xx - 0.30) / 0.45, 0, 1) ** 1.3
    corner = np.clip(np.hypot(xx, yy) - 0.9, 0, 1) * 1.6
    return np.clip(np.maximum(col, corner) + 0.12, 0, 1)


def main(src: Path, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    pp = paper()
    save_gray(pp, out / "paper.webp", quality=78)
    # For light themes (multiply): white is neutral, facets in shadow darken.
    save_gray(np.clip(1 - 1.5 * np.clip(0.56 - pp, 0, None), 0, 1), out / "paper-shade.webp", quality=78)

    fall = edge_falloff()

    # Primary wash: a long dry-brush sweep across the top-left, a second down
    # the right edge, and the owner's ink wash (its dark side strokes).
    a = brush_stroke([(-120, 330), (360, 40), (720, 120), (1040, -60)], 210, dryness=0.6)
    a = np.maximum(a, brush_stroke([(1960, 380), (1700, 640), (1830, 980), (1620, 1290)], 180, dryness=0.5))
    a = np.maximum(a, 0.8 * brush_stroke([(-60, 1010), (240, 900), (420, 1080), (700, 1010)], 120, dryness=0.7))
    wash = load_mask(src / "40.png")
    wash = Image.fromarray((wash * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)
    wash = np.asarray(wash, float) / 255.0
    wash = np.clip((wash - 0.62) / 0.3, 0, 1) ** 1.1          # only the strong edge marks
    a = np.maximum(a, 0.85 * wash)
    save_mask(np.clip(a * fall, 0, 1), out / "wash-a.webp")

    # Secondary wash (the mode's colour): a counter-stroke and the splatter.
    b = brush_stroke([(1980, 60), (1560, 230), (1300, 90), (980, 260)], 150, dryness=0.65)
    b = np.maximum(b, 0.9 * brush_stroke([(260, 1260), (520, 1020), (900, 1180), (1240, 1100)], 140, dryness=0.6))
    splat = load_mask(src / "14.jpg")
    sh = splat.shape[0]
    splat = splat[: int(sh * 0.58)]                      # the spray, not the solid ink
    yy_, xx_ = np.mgrid[0:splat.shape[0], 0:splat.shape[1]]
    ry = (yy_ / splat.shape[0] - 0.75) / 0.55
    rx = (xx_ / splat.shape[1] - 0.5) / 0.55
    splat = np.clip((splat - 0.3) / 0.5, 0, 1) * np.clip(1 - (rx ** 2 + ry ** 2), 0, 1) ** 1.5
    place(b, splat, W - 330, H - 300, 0.62, angle=160)
    place(b, splat * 0.8, 300, 230, 0.45, angle=-20)
    save_mask(np.clip(b * fall, 0, 1), out / "wash-b.webp")

    # Line art — each on its own canvas so CSS can place, tint and animate it.
    # 19.png: the hand hangs in from the top edge; 20.png: the hand rises from
    # the bottom edge; 10.png: the masks. (7.png's two hands were dropped: both
    # arms end mid-image, so they could never enter from a screen edge.)
    for name, file, size in (("art-drip", "19.png", 900), ("art-masks", "10.png", 760), ("art-rise", "20.png", 900)):
        m = load_mask(src / file)
        # Crop to the drawing so CSS can sit it flush against a screen edge.
        ys, xs = np.nonzero(m > 0.05)
        m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        img = Image.fromarray((np.clip(m * 1.15, 0, 1) * 255).astype(np.uint8), "L")
        img.thumbnail((size, size), Image.LANCZOS)
        img = img.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
        save_mask(np.asarray(img, float) / 255.0, out / f"{name}.webp")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
