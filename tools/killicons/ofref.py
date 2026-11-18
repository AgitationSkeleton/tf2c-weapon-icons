"""Open Fortress kill-feed icons as references (read-only from the OF install).

OF keeps its death-notice icons as sprite rectangles in scripts/mod_textures.txt
("<name>" { "dfile" "HUD/d_images_of" "dnegfile" "HUD/dneg_images_of" x y width height }); the sheets
are DXT5 VTFs under materials/hud/. This module parses the table, decodes the sheets and crops one
weapon's d_ (normal) and dneg_ (local-player) sprite.

  python -B tools/killicons/ofref.py [--config F] OUTDIR name [name ...]
      writes <name>_d.png / <name>_dneg.png (for your own reference; OF's sprites are OF's art)

The OF install is config key "of_dir" (tools/iconcfg.py).

vectorise(name) turns one OF d_ sprite into TF2C stock-style layers: the sprite's rectangle height
maps to the 32-unit icon height; opaque blobs are the body (OF's 1-px transparent detail lines
become ~1-unit negative-space cuts, the stock TF2C look); separate half-alpha blobs are the effect
(muzzle / impact burst -> stock .cls{opacity:.5}); saturated pixels are a literal-colour layer
(e.g. the GIB's red burst, the lightning gun's zap -> .cls{fill:#rrggbb}).
"""
import os
import re
import struct
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "bucket"))
import iconcfg  # noqa: E402  (of_dir from config.json)
import dxt  # noqa: E402  (small numpy DXT5 decoder)
_sheets = {}
MAX_W = 130.0                                         # stock widths run 32..135


def table(of=None):
    of = of or iconcfg.need("of_dir")
    t = re.sub(r"//[^\n]*", "", open(os.path.join(of, "scripts", "mod_textures.txt"), encoding="latin-1").read())
    out = {}
    for name, body in re.findall(r'"([^"]+)"\s*\{([^{}]*)\}', t):
        kv = dict(re.findall(r'"(\w+)"\s*"([^"]*)"', body))
        if "dfile" in kv:
            out[name] = dict(dfile=kv["dfile"], dnegfile=kv.get("dnegfile"), x=int(kv["x"]), y=int(kv["y"]),
                             w=int(kv["width"]), h=int(kv["height"]))
    return out


def sheet(rel, of=None):
    of = of or iconcfg.need("of_dir")
    if rel not in _sheets:
        p = os.path.join(of, "materials", rel.replace("/", os.sep) + ".vtf")
        b = open(p, "rb").read()
        w, h = struct.unpack_from("<HH", b, 16)
        fmt = struct.unpack_from("<i", b, 52)[0]
        size = w * h if fmt == 15 else w * h * 4          # one mip (OF's HUD sheets have one)
        _sheets[rel] = dxt.decode(b[len(b) - size:], w, h, fmt)
    return _sheets[rel]


def crop(name, neg=False, tab=None):
    tab = tab or table()
    e = tab[name]
    s = sheet(e["dnegfile"] if neg else e["dfile"])
    return s[e["y"]:e["y"] + e["h"], e["x"]:e["x"] + e["w"]].copy()


def vectorise(name, px=16, tab=None, color_override=None, detail_alpha=0.72, min_line=3, smooth=0.45):
    """-> (width_units, body_loops, layers[(loops, kind)]) in icon units (32 tall)."""
    from scipy import ndimage as nd
    import kistyle as KS
    import kitrace as KT
    img = crop(name, False, tab).astype(np.float32)
    h, w = img.shape[:2]
    a = img[..., 3] / 255.0
    rgb = img[..., :3]
    sat = rgb.max(-1) - rgb.min(-1)
    colored = (sat > 90) & (a > 0.3)
    # body = solid ink (alpha > .75) plus anything dimmer within 1 px of it (AA rim, 1-px detail
    # lines); the burst has no solid core, so it stays out
    solid = a > 0.75
    near = nd.binary_dilation(solid, structure=np.ones((3, 3)))
    hull = (a > 0.3) & near & ~colored
    # OF's interior detail lines: dim pixels with solid ink on two opposite sides
    P = np.pad(solid, 1)
    between = (P[1:-1, :-2] & P[1:-1, 2:]) | (P[:-2, 1:-1] & P[2:, 1:-1])
    detail = hull & (a < detail_alpha) & between
    dl, dn = nd.label(detail, structure=np.ones((3, 3)))
    if dn:                                            # stray dim pixels would perforate the body
        sizes = nd.sum(detail, dl, range(1, dn + 1))
        detail = np.isin(dl, 1 + np.nonzero(sizes >= min_line)[0])
    lab, n = nd.label((a > 0.15) & ~hull & ~colored, structure=np.ones((3, 3)))
    eff = np.zeros_like(a, bool)
    for i in range(1, n + 1):
        c = lab == i
        if c.sum() < 4:
            continue
        # a dim panel hugging / enclosed by the body is part of the weapon, not the burst
        touch = (c & nd.binary_dilation(hull, structure=np.ones((3, 3)))).sum() / c.sum()
        inside = (c & nd.binary_fill_holes(nd.binary_closing(hull, structure=np.ones((5, 5))))).sum() / c.sum()
        if touch > 0.45 or inside > 0.5:
            hull |= c & (a > 0.3)
        else:
            eff |= c                                  # the half-alpha burst / streak
    s_u = min(32.0 / h, MAX_W / w)                    # icon units per sprite pixel (32 tall, <= MAX_W wide)
    k = s_u * px                                      # working pixels per sprite pixel
    W, H = int(round(w * k)), int(round(h * k))
    yoff = int(round((32 * px - H) / 2))              # centred when width-limited

    def up(x):
        im = Image.fromarray(np.clip(x * 255, 0, 255).astype(np.uint8), "L").resize((W, H), Image.BICUBIC)
        out = np.zeros((32 * px, W), np.float32)
        out[yoff:yoff + H] = np.asarray(im).astype(np.float32) / 255.0
        return out
    # smooth before thresholding: the sprites are ~32 px tall, so a plain upscale keeps the stairs
    sil = nd.gaussian_filter(up(hull.astype(np.float32)), smooth * k) > 0.5
    cut = nd.gaussian_filter(up(detail.astype(np.float32)), 0.3 * k) > 0.38
    body = sil & ~cut
    body = KS.opening(body, 0.25 * px)
    body = KS.closing(body, 0.2 * px) & sil & ~cut
    body = KS.drop_islands(body, 1.0 * px * px)
    layers = []
    if eff.any():
        e = nd.gaussian_filter(up(eff.astype(np.float32)), smooth * k) > 0.5
        e = KS.drop_islands(KS.opening(e, 0.2 * px), 1.0 * px * px) & ~body
        layers.append((KT.mask_to_loops(e, px), "half"))
    if colored.any():
        col = rgb[colored].mean(0)
        hexc = color_override or "#%02x%02x%02x" % tuple(int(round(v)) for v in col)
        c = nd.gaussian_filter(up(colored.astype(np.float32)), smooth * k) > 0.5
        c = KS.drop_islands(KS.opening(c, 0.2 * px), 1.0 * px * px) & ~body
        layers.append((KT.mask_to_loops(c, px), hexc))
    loops = KT.mask_to_loops(body, px)
    return max(32.0, float(np.ceil(w * s_u))), loops, layers


def main():
    args = sys.argv[1:]
    if args[:1] == ["--config"]:
        iconcfg.use(args[1])
        args = args[2:]
    sys.argv[1:] = args
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    tab = table()
    for n in sys.argv[2:]:
        for neg in (False, True):
            Image.fromarray(crop(n, neg, tab), "RGBA").save(os.path.join(out, "%s_%s.png" % (n, "dneg" if neg else "d")))


if __name__ == "__main__":
    main()
