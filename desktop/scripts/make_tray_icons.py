"""Generate the tray icons (desktop/resources/tray.ico, tray.png, tray@2x.png).

The app icon is a fine line engraving that turns into a faint grey smudge at
16 px in the notification area. The tray uses the bold silhouette mask
(webui/public/brand/logo-mask-bold.png) knocked out of a solid navy coin, the
same idea as the "solid" home-screen medallion, so it reads on light and dark
taskbars alike.

Run from the repo root:  python desktop/scripts/make_tray_icons.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MASK = ROOT / "namma_agent" / "webui" / "public" / "brand" / "logo-mask-bold.png"
OUT = ROOT / "desktop" / "resources"

COIN = (44, 56, 104, 255)      # --logo-ink (light theme)
RIM = (178, 192, 238, 255)     # --logo-ink (dark theme), a thin rim that lifts it off dark taskbars
FACE = (247, 245, 239, 255)    # the coin face colour used in dark mode
BIG = 512


def render(size: int) -> Image.Image:
    img = Image.new("RGBA", (BIG, BIG), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, BIG - 1, BIG - 1), fill=RIM)
    rim = max(2, BIG // 28)
    d.ellipse((rim, rim, BIG - 1 - rim, BIG - 1 - rim), fill=COIN)
    mask = Image.open(MASK).convert("RGBA").getchannel("A")
    h = int(BIG * 0.80)
    w = int(mask.width * h / mask.height)
    mask = mask.resize((w, h), Image.LANCZOS)
    face = Image.new("RGBA", (w, h), FACE)
    img.paste(face, ((BIG - w) // 2, int(BIG * 0.11)), mask)
    # Keep the silhouette inside the coin.
    circle = Image.new("L", (BIG, BIG), 0)
    ImageDraw.Draw(circle).ellipse((0, 0, BIG - 1, BIG - 1), fill=255)
    img.putalpha(ImageChops.darker(img.getchannel("A"), circle))
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    sizes = [16, 20, 24, 32, 40, 48, 64, 256]
    frames = [render(s) for s in sizes]
    frames[-1].save(OUT / "tray.ico", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    frames[0].save(OUT / "tray.png")
    frames[3].save(OUT / "tray@2x.png")
    print("wrote", OUT / "tray.ico", OUT / "tray.png", OUT / "tray@2x.png")


if __name__ == "__main__":
    main()
