"""Build this repository's showcase images from the shipped icons (no game files needed).

  python -B tools/make_showcase.py

Reads icons/killicons/svg/*.svg and icons/bucket/*.png and writes:
  icons/killicons/png/<name>_normal.png   kill-feed look (cream icon on the dark notice), 3x
  icons/killicons/png/<name>_local.png    local-player look (dark icon on the light notice), 3x
  docs/killicons_contact_sheet.png        every kill icon, both looks, labelled
  docs/bucket_contact_sheet.png           every bucket icon (whole 512x512 canvas) over the HUD grey
"""
import glob
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "killicons"))
import killicons as KI  # noqa: E402


def font(size):
    for f in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def killicons():
    svgs = sorted(glob.glob(os.path.join(REPO, "icons", "killicons", "svg", "*.svg")))
    pv = os.path.join(REPO, "icons", "killicons", "png")
    os.makedirs(pv, exist_ok=True)
    tiles = []
    f = font(18)
    for svg in svgs:
        n = os.path.basename(svg)[:-4]
        a = KI.notice(svg, 3, KI.NORMAL)
        b = KI.notice(svg, 3, KI.LOCAL)
        a.save(os.path.join(pv, n + "_normal.png"))
        b.save(os.path.join(pv, n + "_local.png"))
        t = Image.new("RGB", (a.width + b.width + 30, a.height + 34), (24, 23, 22))
        ImageDraw.Draw(t).text((10, 6), n, fill=(200, 200, 200), font=f)
        t.paste(a, (10, 30))
        t.paste(b, (a.width + 20, 30))
        tiles.append(t)
    sheet(tiles, 2, os.path.join(REPO, "docs", "killicons_contact_sheet.png"))
    return len(svgs)


def buckets():
    pngs = sorted(glob.glob(os.path.join(REPO, "icons", "bucket", "*.png")))
    tiles = []
    f = font(16)
    for p in pngs:
        img = Image.open(p).convert("RGBA").resize((256, 256), Image.LANCZOS)   # whole canvas: true HUD scale
        t = Image.new("RGBA", (272, 290), (40, 40, 40, 255))
        t.alpha_composite(img, (8, 28))
        ImageDraw.Draw(t).text((8, 6), os.path.basename(p)[:-4], fill=(210, 210, 210), font=f)
        tiles.append(t.convert("RGB"))
    sheet(tiles, 5, os.path.join(REPO, "docs", "bucket_contact_sheet.png"))
    return len(pngs)


def sheet(tiles, cols, path):
    colw = max(t.width for t in tiles)
    rows = [tiles[i:i + cols] for i in range(0, len(tiles), cols)]
    hs = [max(t.height for t in r) for r in rows]
    S = Image.new("RGB", (cols * colw, sum(hs)), (16, 16, 16))
    y = 0
    for r, h in zip(rows, hs):
        for c, t in enumerate(r):
            S.paste(t, (c * colw, y))
        y += h
    os.makedirs(os.path.dirname(path), exist_ok=True)
    S.save(path, optimize=True)


if __name__ == "__main__":
    print("kill icons:", killicons(), "  bucket icons:", buckets())
