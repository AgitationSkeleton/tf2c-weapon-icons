"""TF2 Classified (5205) kill-feed icon generator for tf2cc / old Merc / old-class / MarxVee /
April Fools items. (CustomSlop weapons reuse their donor item's icon name; no icons of their own.)

  python -B tools/killicons/killicons.py build  [--config F] [--out DIR] [key ...]  render + vectorise + validate
  python -B tools/killicons/killicons.py review [--out DIR] [--stock DIR]          previews, contact sheet, index.html
  python -B tools/killicons/killicons.py check  FILE.svg ...                       subset + metric check only

Game paths come from config.json (tools/iconcfg.py). --out defaults to <out_dir>/killicons.
--stock: optional folder of the game's own death-notice SVGs (extracted from your install, e.g.
resource/svgs/deathnotice/ in tf2c_assets_dir.vpk) shown next to each icon for comparison.

How the client uses the files (client.dll 5205, see the review report): the death-notice HUD scans
resource/svgs/deathnotice/*.svg once at startup; the file stem is the icon name. The event's weapon
name X is looked up as d_X (normal) and dneg_X (when the local player is involved); both prefixes
are stripped and resolve to the SAME file X.svg, rendered twice with injected CSS fills
(SVGIconColor 236 227 187 / SVGIconColorNegative 63 57 35). Crit / mini-crit / tranq / australium
badges (d_crit, d_minicrit, d_tranquilized, d_australium) and the headshot / backstab /
deflect_* / huntsman_* overrides are generic or keyed to hard-coded stock names, so one SVG per
weapon is the complete set.

Pipeline per icon: model (world model, else the viewmodel's weapon meshes) -> side-profile pose
(kimodel) -> 16 px/unit ortho buffers -> stylise (kistyle: cuts at part / depth / crease
boundaries, thin-part inflation, cleanup, rounding) -> crack trace + RDP (kitrace) -> effect layer
-> SVG -> validation against the stock metrics (svgras).
"""
import argparse
import html
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as nd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import iconcfg  # noqa: E402
import kimodel as KM  # noqa: E402
import kistyle as KS  # noqa: E402
import kitrace as KT  # noqa: E402
import svgras  # noqa: E402

PX = 16                     # working pixels per icon unit
ICON_H = 32.0
NORMAL = dict(bg=(46, 43, 42, 220), fg=(236, 227, 187))
LOCAL = dict(bg=(245, 229, 196, 200), fg=(63, 57, 35))
GUNS = ("gun", "flame", "beam", "heal")

STOCK_RANGES = {            # metric: (lo, hi) accepted, from the 96 stock files (research §2.10)
    "vbh": (32, 32), "vbw": (32, 135), "fill_ratio_bbox": (0.12, 0.65), "parts": (1, 21),
    "part_thick_median": (1.2, 9.0), "pad_l": (0, 6), "bytes": (0, 12288),
}


def load_manifest():
    with open(os.path.join(HERE, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- build

def build_icon(entry, out_svg, fs=None, cache=None, debug_dir=None):
    """Render one icon. `entry`: dict(name, model, family, spec{}). Returns a metrics dict.
    With entry["of_icon"] the icon is OF's own kill-feed sprite vectorised (ofref.vectorise)."""
    t0 = time.time()
    if entry.get("of_icon"):
        import ofref
        w, body_loops, layers = ofref.vectorise(entry["of_icon"], PX, **entry.get("of_spec", {}))
        nbytes = KT.write_svg(out_svg, w, body_loops, layers)
        met = measure(out_svg)
        met.update(bytes=nbytes, cuts=[], seconds=round(time.time() - t0, 1), source="OF sprite " + entry["of_icon"])
        return met
    fs = fs or KM.FS()
    cache = cache or os.path.join(iconcfg.out_dir(), "killicons", "_work", "models")
    spec = entry.get("spec", {})
    fam = entry["family"]
    m = KM.S.load(KM.fetch_model(fs, entry["model"], cache))
    T, MT = KM.select(m, spec)
    R0, roll, mpos = KM.pose(m, T, spec, fam)
    # true proportions: one uniform scale only (round 2: "never scale X/Y independently")
    R = KM.rollmat(roll) @ R0
    x0, x1, y0, y1, Pp = KM.projected_bounds(m, T, R)
    w, h = x1 - x0, y1 - y0
    model_len = max(w, h)
    dual = spec.get("dual")                              # (dx, dy) units: second copy behind
    ddx, ddy = (abs(dual[0]), abs(dual[1])) if dual else (0.0, 0.0)
    max_w = spec.get("max_w", 100.0 if fam in GUNS else 84.0) - ddx
    max_h = spec.get("max_h", ICON_H if fam in GUNS else 30.0) - ddy
    k = min(max_h / h, max_w / w)                       # icon units per model unit
    body_w, body_h = w * k, h * k
    pad_l = 2.0 + ddx
    Wpx = int(np.ceil((body_w + pad_l + 2.0) * PX))
    Hpx = int(ICON_H * PX)
    ppm = k * PX
    # vertical placement: bottom-aligned guns, centred others
    yoff = (ICON_H - body_h) / 2 if fam not in GUNS else (ICON_H - body_h)
    origin = (x0 - pad_l / k, y0 - (ICON_H - body_h - yoff) / k)
    mask, idb, depth, nb = KM.raster(m, T, MT, R, ppm, origin, (Wpx, Hpx))
    body, info = KS.stylize(mask, idb, depth, nb, PX, model_len, weapon_axis_deg=roll,
                            max_cuts=spec.get("max_cuts", KS.MAX_CUTS), crease_deg=spec.get("crease", 70.0),
                            min_thick=spec.get("min_thick", 2.6 if fam == "melee" else KS.MIN_THICK),
                            max_gap=spec.get("max_gap", 2.2), hole_fill=spec.get("hole_fill", KS.HOLE_FILL))
    emb = spec.get("emblem")
    if emb:                                             # medical / holy cross cut into a flat face
        lab, n = nd.label(body)
        big = lab == (1 + int(np.argmax(nd.sum(body, lab, range(1, n + 1)))))
        inner = KS.disk_erode(big, 1.5 * PX)
        yy, xx = np.nonzero(inner)
        cy, cx = yy.mean(), xx.mean()
        sz = 0.42 * min(np.ptp(yy), np.ptp(xx))
        th = 0.32 * sz
        Y, X = np.mgrid[0:body.shape[0], 0:body.shape[1]]
        if emb == "latin":
            cy0 = cy - 0.25 * sz
            shape = ((abs(X - cx) <= th / 2) & (abs(Y - cy) <= sz * 0.75)) | \
                    ((abs(Y - cy0) <= th / 2) & (abs(X - cx) <= sz * 0.45))
        else:
            shape = ((abs(X - cx) <= th / 2) & (abs(Y - cy) <= sz / 2)) | \
                    ((abs(Y - cy) <= th / 2) & (abs(X - cx) <= sz / 2))
        if spec.get("panel"):
            # solid cross on a panel: a gap ring around the cross and a panel-edge gap ring inset
            # from the outline (stock-style negative-space lines, ~CUT_W wide)
            cw = KS.CUT_W * PX
            inset = spec["panel"] * PX
            ring = KS.disk_erode(big, inset) & ~KS.disk_erode(big, inset + cw)
            body = body & ~ring & ~(KS.disk_dilate(shape, cw) & ~shape)
        else:
            body = body & ~shape
    if dual:                                            # e.g. akimbo: a second copy behind the first
        dx, dy = int(round(dual[0] * PX)), int(round(-dual[1] * PX))
        back = np.zeros_like(body)                      # shift WITHOUT wrap-around (no bleed)
        H_, W_ = body.shape
        back[max(dy, 0):H_ + min(dy, 0), max(dx, 0):W_ + min(dx, 0)] = \
            body[max(-dy, 0):H_ + min(-dy, 0), max(-dx, 0):W_ + min(-dx, 0)]
        back &= ~KS.disk_dilate(body, spec.get("dual_gap", 1.4) * PX)
        back = KS.opening(back, 0.42 * PX)
        body = body | KS.drop_islands(back, KS.ISLAND_MIN * PX * PX)
    ys, xs = np.nonzero(body)
    bx0, bx1 = xs.min() / PX, (xs.max() + 1) / PX
    # trim / shift so the ink starts at 2 units
    shift = bx0 - 2.0
    body_loops = KT.mask_to_loops(body, PX)
    body_loops = [L - [shift, 0] for L in body_loops]
    bx1 -= shift
    big = max(body_loops, key=lambda L: abs(KT.area(L)))
    pos = KT.area(big) > 0                              # winding sign of the outlines
    eff = []
    width = bx1 + 1.0
    name = entry["name"]
    X = xs / PX - shift
    Y = ys / PX
    if spec.get("fx") == "none":
        pass
    elif fam in GUNS:
        # muzzle: the attachment's height (or the rightmost ink's), then snapped to the barrel
        # tip = the rightmost ink in a 1.2-unit band around that height
        if mpos is not None and not spec.get("muzzle_auto"):
            q = R @ mpos
            mya = ICON_H - (q[1] - origin[1]) * k
        else:
            mya = Y[X >= X.max() - 1.5].mean()
        mya += spec.get("muzzle_dy", 0.0)
        band = np.abs(Y + 0.5 / PX - mya) <= 1.2
        if not band.any():
            band = np.ones_like(X, bool)
        tip = X[band].max()
        sel = band & (X >= tip - 0.8)
        mx = tip + 1.0 / PX + spec.get("muzzle_dx", 0.25)
        my = Y[sel].mean() + 0.5 / PX
        if spec.get("muzzle_center"):
            # the barrel axis: centre of the full ink run at the tip (not just the attachment band)
            col = (X >= tip - 0.8) & (np.abs(Y - mya) <= 3.0)
            my = (Y[col].min() + Y[col].max() + 1.0 / PX) / 2
        if fam == "gun":
            size = spec.get("fx_size", 10.0 if body_w < 70 else 13.0)
            P = KT.muzzle_burst(name, mx, my, size, top_room=my - 0.2, bot_room=ICON_H - my - 0.2)
            eff.append(([KT.orient(P, pos)], spec.get("fx_color", "half")))
            width = max(width, P[:, 0].max() + 1.0)
        elif fam == "flame":
            L = spec.get("fx_size", 22.0)
            P = KT.flame(name, mx, my, L, min(13.0, 2 * min(my, ICON_H - my) - 1))
            P = np.clip(P, [0, 0], [1e9, ICON_H])
            eff.append(([KT.orient(P, pos)], spec.get("fx_color", "#e17800")))   # stock flamethrower
            width = max(width, P[:, 0].max() + 1.0)
        elif fam == "beam":
            L = spec.get("fx_size", 20.0)
            P = KT.bolt(name, mx, my, L, min(8.0, 2 * min(my, ICON_H - my) - 3))
            P = np.clip(P, [0, 0], [1e9, ICON_H])
            eff.append(([KT.orient(P, pos)], spec.get("fx_color", "#00e1ff")))   # stock taser zap
            width = max(width, P[:, 0].max() + 1.0)
        else:
            L = spec.get("fx_size", 18.0)
            P = KT.heal_band(name, mx, my, L)
            eff.append(([KT.orient(np.clip(P, [0, 0], [1e9, ICON_H]), pos)], "half"))
            width = max(width, mx + L + 1.0)
    elif fam in ("melee", "thrown"):
        # head tip = extreme ink point along the head direction (up-right for melee, right for thrown)
        ang = np.radians(spec.get("fx_angle", 30.0 if fam == "melee" else 0.0))
        d = np.array([np.cos(ang), -np.sin(ang)])
        i = int(np.argmax(X * d[0] + Y * d[1]))
        size = spec.get("fx_size", 12.0)
        cx = X[i] + spec.get("fx_dx", 1.0)
        cy = Y[i] + spec.get("fx_dy", 3.0 if fam == "melee" else 0.0)
        cy = min(max(cy, size * 0.75), ICON_H - size * 0.75) if not spec.get("fx_exact") else cy
        P = KT.impact_star(name, cx, cy, size, fan=tuple(spec.get("fx_fan", (-75, 75))))
        P = np.clip(P, [0, 0], [1e9, ICON_H])
        eff.append(([KT.orient(P, pos)], "half"))
        width = max(width, P[:, 0].max() + 1.0)
    width = float(np.ceil(max(width, 32.0)))          # stock minimum width
    nbytes = KT.write_svg(out_svg, width, body_loops, eff)
    met = measure(out_svg)
    met.update(bytes=nbytes, cuts=info["cuts"], seconds=round(time.time() - t0, 1))
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        dbg = np.zeros(mask.shape + (3,), np.uint8)
        dbg[mask] = (90, 90, 90)
        dbg[info["silhouette"]] = (140, 140, 140)
        dbg[body] = (236, 227, 187)
        Image.fromarray(dbg).save(os.path.join(debug_dir, name + "_dbg.png"))
    return met


# ---------------------------------------------------------------- metrics / checks

ALLOWED_TAGS = {"svg", "defs", "style", "path", "g"}


def check_subset(path):
    import xml.etree.ElementTree as ET
    errs = []
    root = ET.parse(path).getroot()
    vb = root.get("viewBox", "").split()
    if len(vb) != 4 or float(vb[3]) != 32 or float(vb[0]) or float(vb[1]):
        errs.append("viewBox must be 0 0 W 32")
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ALLOWED_TAGS:
            errs.append("tag " + tag)
        for a in el.attrib:
            if a not in ("viewBox", "d", "class", "xmlns") and not a.startswith("{"):
                errs.append("attr %s on %s" % (a, tag))
        if tag == "path" and el.get("class") not in (None, "cls-1", "cls-2"):
            errs.append("class " + str(el.get("class")))
    if os.path.getsize(path) > 12288:
        errs.append("size > 12 KB")
    return errs


def measure(path, sc=10):
    vb, L = svgras.render(path, sc, 3)
    r = dict(vbw=vb[2], vbh=vb[3])
    solid = L.get("solid")
    if solid is None:
        r["error"] = "no body"
        return r
    m = solid > 0.5
    ys, xs = np.nonzero(m)
    r.update(pad_l=round(xs.min() / sc, 2), pad_t=round(ys.min() / sc, 2), pad_b=round((m.shape[0] - 1 - ys.max()) / sc, 2),
             ink_w=round((xs.max() - xs.min() + 1) / sc, 1), ink_h=round((ys.max() - ys.min() + 1) / sc, 1))
    r["fill_ratio_bbox"] = round(float(m.sum() / ((ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1))), 3)
    closed = nd.binary_closing(np.pad(m, 30), structure=np.ones((25, 25)))[30:-30, 30:-30]
    closed = nd.binary_fill_holes(closed | m)
    gaps = closed & ~m
    dt = nd.distance_transform_edt(gaps)
    ridge = (dt > 0) & (dt == nd.maximum_filter(dt, size=3))
    gw = 2 * dt[ridge] / sc
    r["gap_w_median"] = round(float(np.median(gw)), 2) if gw.size else None
    dti = nd.distance_transform_edt(m)
    ridge2 = (dti > 0) & (dti == nd.maximum_filter(dti, size=3))
    r["part_thick_median"] = round(float(np.median(2 * dti[ridge2] / sc)), 2)
    r["part_thick_p10"] = round(float(np.percentile(2 * dti[ridge2] / sc, 10)), 2)
    r["parts"] = int(nd.label(m)[1])
    r["half_area"] = round(float((L["half"] > 0.3).sum() / sc / sc), 1) if "half" in L else 0.0
    return r


def verdict(met, errs):
    warn = list(errs)
    for k, (lo, hi) in STOCK_RANGES.items():
        v = met.get(k)
        if v is None:
            continue
        if not (lo <= v <= hi):
            warn.append("%s=%s outside stock %s..%s" % (k, v, lo, hi))
    return warn


# ---------------------------------------------------------------- previews

def icon_rgba(svg, scale, fg, crit=None):
    vb, L = svgras.render(svg, scale, 4)
    shape = next(iter(L.values())).shape
    solid = L.get("solid", np.zeros(shape))
    half = L.get("half", np.zeros(shape)) * 0.5
    grad = L.get("gradient", np.zeros(shape))
    colr = L.get("color", np.zeros(shape))
    a = np.clip(solid + half * (1 - solid) + grad * 0.8 * (1 - solid), 0, 1)
    rgb = np.zeros(shape + (3,))
    rgb[:] = fg
    # literal-colour layers keep their own colour in both looks (class fill beats the HUD's `svg *`)
    import re as _re
    lit = _re.findall(r"fill:#([0-9a-fA-F]{6})", open(svg, encoding="utf-8").read())
    lc = np.array([int(lit[0][i:i + 2], 16) for i in (0, 2, 4)]) if lit else np.array([255, 160, 0])
    rgb = np.where(colr[..., None] > 0.3, lc, rgb)
    a = np.maximum(a, colr)
    img = np.dstack([rgb, a * 255]).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


def glow(w, h, color):
    yy, xx = np.mgrid[0:h, 0:w]
    r = np.hypot((xx + 0.5 - w / 2) / (w / 2), (yy + 0.5 - h / 2) / (h / 2))
    a = np.clip(1 - r, 0, 1) ** 1.2 * 0.75
    img = np.zeros((h, w, 4), np.uint8)
    img[..., :3] = color
    img[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(img, "RGBA")


def notice(svg, scale, look, badge=None):
    ic = icon_rgba(svg, scale, look["fg"])
    pad = int(4 * scale)
    W, H = ic.width + 2 * pad, ic.height + 2 * pad
    base = Image.new("RGBA", (W, H), (30, 30, 30, 255))
    bg = Image.new("RGBA", (W, H), look["bg"])
    base.alpha_composite(bg)
    if badge:
        base.alpha_composite(glow(ic.width, ic.height, badge), (pad, pad))
    base.alpha_composite(ic, (pad, pad))
    return base.convert("RGB")


def of_preview(name, h=96):
    """OF's own d_ sprite on the normal kill-feed background, scaled to the 3x preview height."""
    import ofref
    sp = Image.fromarray(ofref.crop(name), "RGBA")
    bg = Image.new("RGBA", sp.size, NORMAL["bg"][:3] + (255,))
    bg.alpha_composite(sp)
    im = bg.convert("RGB").resize((max(1, round(sp.width * h / sp.height)), h), Image.LANCZOS)
    pad = 12
    out = Image.new("RGB", (im.width + 2 * pad, h + 2 * pad), NORMAL["bg"][:3])
    out.paste(im, (pad, pad))
    return out


def review(out, results, stock_dir=None):
    sv = os.path.join(out, "svg")
    pv = os.path.join(out, "png")
    stock_dir = stock_dir or os.path.join(out, "stock_svg")
    os.makedirs(pv, exist_ok=True)
    rows = []
    sheet_items = []
    for r in results:
        n = r["name"]
        svg = os.path.join(sv, n + ".svg")
        files = {}
        for tag, look, sc, badge in (("normal", NORMAL, 3, None), ("local", LOCAL, 3, None),
                                     ("normal_1x", NORMAL, 1, None), ("local_1x", LOCAL, 1, None),
                                     ("crit", NORMAL, 3, (214, 52, 34)), ("minicrit", NORMAL, 3, (255, 162, 0))):
            fp = os.path.join(pv, "%s_%s.png" % (n, tag))
            notice(svg, sc, look, badge).save(fp)
            files[tag] = "png/%s_%s.png" % (n, tag)
        if r.get("of_ref"):
            fp = os.path.join(pv, "of_%s.png" % r["of_ref"])
            if not os.path.exists(fp):
                of_preview(r["of_ref"]).save(fp)
            files["of"] = "png/of_%s.png" % r["of_ref"]
        if r.get("prev") and os.path.exists(os.path.join(sv, r["prev"] + ".svg")):
            fp = os.path.join(pv, "%s_normal.png" % r["prev"])
            if not os.path.exists(fp):
                notice(os.path.join(sv, r["prev"] + ".svg"), 3, NORMAL).save(fp)
            files["prev"] = "png/%s_normal.png" % r["prev"]
        cmp_ = r.get("compare")
        if cmp_ and os.path.exists(os.path.join(stock_dir, cmp_ + ".svg")):
            fp = os.path.join(pv, "stock_%s_normal.png" % cmp_)
            if not os.path.exists(fp):
                notice(os.path.join(stock_dir, cmp_ + ".svg"), 3, NORMAL).save(fp)
            files["stock"] = "png/stock_%s_normal.png" % cmp_
        rows.append((r, files))
        sheet_items.append((r, os.path.join(pv, "%s_normal.png" % n), files.get("stock") and os.path.join(out, files["stock"])))
    contact_sheet(sheet_items, os.path.join(out, "contact_sheet.png"))
    write_plan(out, results)
    write_html(out, rows)


def write_plan(out, results):
    """Schema item_iconname changes + downloads.txt lines + FastDL paths (nothing is applied)."""
    man = load_manifest()
    lines = ["# kill-icon integration plan (generated; nothing applied)", "",
             "## schema: item_iconname per defindex (tf2cc gen_schema / AF pack merge)"]
    ship = [r for r in results if not (r.get("choice") or "").startswith("B")]
    for r in ship:
        for d in r["defindex"]:
            lines.append('%s\t"item_iconname"\t"%s"' % (d, r["name"]))
    lines += ["", "## schema: switch to a stock icon name (no custom file)"]
    for s_ in man.get("stock_names", []):
        for d in s_["defindex"]:
            lines.append('%s	"item_iconname"	"%s"	// %s' % (d, s_["item_iconname"], s_["why"]))
    lines += ["", "## no kill icon (no item_iconname change)"]
    lines += ["%s: %s (%s)" % (",".join(map(str, s_["defindex"])), s_["title"], s_["why"]) for s_ in man.get("no_icon", [])]
    lines += ["", "## downloads.txt (configs/tf2cc_tf2c/downloads.txt) and FastDL paths"]
    lines += ["resource/svgs/deathnotice/%s.svg" % r["name"] for r in ship]
    lines += ["", "## superseded in round 5 (keep the old files on FastDL and in downloads.txt: players cache them)"]
    lines += ["%s -> %s" % (x["old"], x["new"]) for x in man.get("superseded", [])]
    lines += ["", "## user's choice pending (not shipped unless picked)"]
    lines += ["%s: %s" % (r["name"], r["choice"]) for r in results if (r.get("choice") or "").startswith("B")]
    lines += ["", "## skipped"] + ["%s: %s" % (",".join(map(str, s["defindex"])), s["why"]) for s in man["skipped"]]
    lines += ["", "## CustomSlop", man.get("customslop", "")]
    with open(os.path.join(out, "integration_plan.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def contact_sheet(items, path):
    tiles = []
    try:
        font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for r, ours, stock in items:
        a = Image.open(ours)
        b = Image.open(stock) if stock else None
        w = a.width + (b.width + 20 if b else 0) + 20
        h = max(a.height, b.height if b else 0) + 34
        t = Image.new("RGB", (w, h), (24, 23, 22))
        d = ImageDraw.Draw(t)
        d.text((10, 6), "%s  (%s)  vs stock %s" % (r["name"], ",".join(map(str, r["defindex"])), r.get("compare")),
               fill=(200, 200, 200), font=font)
        t.paste(a, (10, 30))
        if b:
            t.paste(b, (a.width + 30, 30))
        tiles.append(t)
    cols = 2
    colw = max(t.width for t in tiles)
    rowsz = [max(t.height for t in tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    S = Image.new("RGB", (cols * colw, sum(rowsz)), (16, 16, 16))
    y = 0
    for ri, i in enumerate(range(0, len(tiles), cols)):
        for c, t in enumerate(tiles[i:i + cols]):
            S.paste(t, (c * colw, y))
        y += rowsz[ri]
    S.save(path)


def write_html(out, rows):
    e = html.escape
    parts = ["""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TF2C Kill Icons Review</title>
<style>
:root{--bg:#1b1a19;--fg:#e8e2cf;--mut:#9b958a;--card:#262422;--line:#3a3734;--ok:#7fb069;--warn:#e0a030}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--bg:#f3efe6;--fg:#1f1d1a;--mut:#6b655a;--card:#fffdf8;--line:#ddd6c8}}
body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,Segoe UI,sans-serif}
main{max-width:1200px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0}
.note{color:var(--mut);max-width:900px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0}
.hd{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:baseline}
.hd b{font-size:16px}.hd code{color:var(--mut)}
.row{display:flex;flex-wrap:wrap;gap:12px;margin-top:8px;align-items:flex-start}
figure{margin:0}figcaption{font-size:12px;color:var(--mut)}
img{max-width:100%;height:auto;image-rendering:auto;display:block}
.ok{color:var(--ok)}.warn{color:var(--warn)}
details{margin-top:6px;color:var(--mut);font-size:12px}
.r2{background:#e0a030;color:#1b1a19;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
.chg{margin:6px 0 0;font-size:13px}
.r5{background:#c77dd8;color:#1b1a19;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
.ch{background:#e05050;color:#fff;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
.r4{background:#6aa9e0;color:#1b1a19;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
.r3{background:#7fb069;color:#1b1a19;border-radius:4px;padding:0 6px;font-size:12px;font-weight:600}
table{border-collapse:collapse;width:100%;font-size:13px}td,th{border-bottom:1px solid var(--line);padding:4px 6px;text-align:left;vertical-align:top}
</style></head><body><main>
<h1>TF2 Classified kill-feed icons: review</h1>
<p class="note">One SVG per weapon. The client looks up <code>d_NAME</code> (normal) and <code>dneg_NAME</code>
(local player involved); both strip the prefix and load the same <code>resource/svgs/deathnotice/NAME.svg</code>,
tinted by injected CSS (236 227 187 normal, 63 57 35 negative). Crit and mini-crit glows are separate generic
icons drawn behind; shown here approximately. Left: ours (normal / local-player at 3x, then 1x actual size).
Right: the closest stock icon (when --stock is given).</p>
<p class="note">Delivery: each icon ships as
<code>resource/svgs/deathnotice/NAME.svg</code> via FastDL and the downloads list. The client scans that folder only at
startup, so a player sees a new icon after <b>one game restart</b> following the first download (text until then).
Names are versioned (<code>_v1</code>) and never reused once published, because clients never re-download an existing path.</p>
"""]
    man = load_manifest()
    parts.append('<section class="card"><b>Round 2: no custom icon, use a stock name</b> '
                 '<span class="r2">changed in round 2</span><table><tr><th>defindex</th><th>item</th><th>item_iconname</th><th>why</th></tr>')
    for s_ in man.get("stock_names", []):
        parts.append("<tr><td>%s</td><td>%s</td><td><code>%s</code></td><td>%s</td></tr>" % (
            e(", ".join(map(str, s_["defindex"]))), e(s_["title"]), e(s_["item_iconname"]), e(s_["why"])))
    parts.append('</table></section><section class="card"><b>Round 2: no kill icon at all</b> '
                 '<span class="r2">changed in round 2</span><table><tr><th>defindex</th><th>item</th><th>why</th></tr>')
    for s_ in man.get("no_icon", []):
        parts.append("<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (
            e(", ".join(map(str, s_["defindex"]))), e(s_["title"]), e(s_["why"])))
    parts.append("</table></section>")
    for r, f in rows:
        warn = r.get("warnings", [])
        st = '<span class="ok">metrics within stock ranges</span>' if not warn else \
            '<span class="warn">%s</span>' % e("; ".join(warn))
        parts.append('<section class="card"><div class="hd"><b>%s</b><span class="r2">changed in round 2</span>'
                     '<code>%s.svg</code><span>defindex %s</span><span>%s</span></div>'
                     % (e(r["title"]), e(r["name"]), e(", ".join(map(str, r["defindex"]))), st))
        if r.get("choice"):
            parts.append('<p class="chg"><span class="ch">choice for the user</span> %s</p>' % e(r["choice"]))
        if r.get("round5"):
            badge = '<span class="r5">changed in round 5</span> ' if r.get("round5_changed", True) else ""
            parts.append('<p class="chg">%s%s</p>' % (badge, e(r["round5"])))
        if r.get("of_ref"):
            parts.append('<div class="row">')
            parts.append('<figure><img src="%s" alt="OF d_%s" loading="lazy"><figcaption>OF d_%s (reference)</figcaption></figure>'
                         % (f["of"], e(r["of_ref"]), e(r["of_ref"])))
            if "prev" in f:
                parts.append('<figure><img src="%s" alt="live %s" loading="lazy"><figcaption>currently live: %s</figcaption></figure>'
                             % (f["prev"], e(r["prev"]), e(r["prev"])))
            parts.append('<figure><img src="%s" alt="proposed %s" loading="lazy"><figcaption>%s: %s</figcaption></figure>'
                         % (f["normal"], e(r["name"]), "proposed" if (r.get("prev") or r.get("round5_new")) else "live (unchanged)", e(r["name"])))
            parts.append('</div>')
        if r.get("round4"):
            parts.append('<p class="chg"><span class="r4">changed in round 4</span> %s</p>' % e(r["round4"]))
        if r.get("round3"):
            parts.append('<p class="chg"><span class="r3">changed in round 3</span> %s</p>' % e(r["round3"]))
        if r.get("round2"):
            parts.append('<p class="chg">Round 2: %s</p>' % e(r["round2"]))
        parts.append('<div class="row">')
        for tag, cap in (("normal", "normal (d_)"), ("local", "local player (dneg_)"), ("crit", "crit glow"),
                         ("minicrit", "mini-crit glow")):
            parts.append('<figure><img src="%s" alt="%s %s" loading="lazy"><figcaption>%s</figcaption></figure>'
                         % (f[tag], e(r["name"]), tag, cap))
        if "stock" in f:
            parts.append('<figure><img src="%s" alt="stock %s" loading="lazy"><figcaption>stock: %s</figcaption></figure>'
                         % (f["stock"], e(r["compare"]), e(r["compare"])))
        parts.append('</div><div class="row">')
        for tag in ("normal_1x", "local_1x"):
            parts.append('<figure><img src="%s" alt="%s 1x"><figcaption>%s</figcaption></figure>' % (f[tag], e(r["name"]), tag))
        parts.append('<figure><figcaption><a href="svg/%s.svg">SVG file</a> (%d bytes) &middot; model <code>%s</code></figcaption></figure>'
                     % (e(r["name"]), r["metrics"].get("bytes", 0), e(r["model"])))
        parts.append('</div><details><summary>metrics</summary><code>%s</code></details></section>'
                     % e(json.dumps({k: v for k, v in r["metrics"].items() if k != "cuts"})))
    parts.append("</main></body></html>")
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


# ---------------------------------------------------------------- cli

def idle_priority():
    """Run batch work at Windows Idle priority so live game servers on this box keep the CPU."""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)
    except Exception:
        pass


def main():
    idle_priority()
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "review", "check"])
    ap.add_argument("keys", nargs="*")
    ap.add_argument("--config", help="config file (default: config.json in the repo root)")
    ap.add_argument("--out", help="output folder (default: <out_dir>/killicons)")
    ap.add_argument("--stock", help="folder with the game's stock death-notice SVGs (review only)")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if a.config:
        iconcfg.use(a.config)
    a.out = a.out or os.path.join(iconcfg.out_dir(), "killicons")
    if a.cmd == "check":
        for p in a.keys:
            met = measure(p)
            print(p, verdict(met, check_subset(p)), met)
        return
    man = load_manifest()
    res_path = os.path.join(a.out, "results.json")
    results = {}
    if os.path.exists(res_path):
        with open(res_path, encoding="utf-8") as f:
            results = {r["name"]: r for r in json.load(f)}
    if a.cmd == "build":
        fs = KM.FS()
        os.makedirs(os.path.join(a.out, "svg"), exist_ok=True)
        for ent in man["icons"]:
            if a.keys and ent["name"] not in a.keys:
                continue
            svg = os.path.join(a.out, "svg", ent["name"] + ".svg")
            try:
                met = build_icon(ent, svg, fs, debug_dir=os.path.join(a.out, "_work", "debug") if a.debug else None)
            except Exception as ex:  # keep going; report at the end
                print("FAIL", ent["name"], repr(ex))
                import traceback
                traceback.print_exc()
                continue
            warn = verdict(met, check_subset(svg))
            results[ent["name"]] = dict(name=ent["name"], title=ent["title"], defindex=ent["defindex"],
                                        model=ent.get("model") or ("OF sprite " + ent.get("of_icon", "")), family=ent["family"], compare=ent.get("compare"),
                                        round2=ent.get("round2_note"), round3=ent.get("round3_note"),
                                        round4=ent.get("round4_note"), round5=ent.get("round5_note"),
                                        of_ref=ent.get("of_ref"), prev=ent.get("prev"), choice=ent.get("choice"),
                                        round5_changed=ent.get("round5_changed", True), round5_new=ent.get("round5_new"),
                                        metrics=met, warnings=warn)
            print("%-44s %5.1fs w=%-5s parts=%-3s fill=%-5s gap=%-5s %s" % (
                ent["name"], met["seconds"], met.get("vbw"), met.get("parts"), met.get("fill_ratio_bbox"),
                met.get("gap_w_median"), "; ".join(warn) or "ok"))
        order = [e["name"] for e in man["icons"]]
        with open(res_path, "w", encoding="utf-8") as f:
            json.dump(sorted(results.values(), key=lambda r: order.index(r["name"]) if r["name"] in order else 999),
                      f, indent=1)
    else:
        order = [e["name"] for e in man["icons"]]
        rs = sorted([r for r in results.values() if r["name"] in order], key=lambda r: order.index(r["name"]))
        review(a.out, rs, a.stock)
        print("review:", os.path.join(a.out, "index.html"), len(rs), "icons")


if __name__ == "__main__":
    main()
