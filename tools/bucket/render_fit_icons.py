"""HUD-bucket / armory icons rendered with CustomSlop's v2 renderer and posed to match a stock
TF2 Classified icon (https://github.com/AgitationSkeleton/tf2c-customslop, used read-only from the
folder in config key "customslop_tools": iconfit.fit_v2 silhouette fit, iconfit.render_icon with
the calibrated v2 light rig srcshade.rig(), srcshade.stats colour metrics).

FIT: name -> (world model, reference, skins)
  reference: a stock icon's VMT path (searched through the game, e.g. "vgui/loadout/weapons/bottle"),
             "staged:<materials path stem>" (an icon in staging_dir), "vtf:<file>" (any VTF), or
             "upright:<yaw>" (no fit: model z up, turned about z by yaw degrees)
  skins None: one icon <name>.png; a list of 4 skin families: <name>_red/_blue/_green/_yellow.png
  (TF2C draws team n with skin family n: GetTeamSkin()).
Output in <out_dir>/bucket/: <name>[_<team>].png (512x512 RGBA), the same as <name>[_<team>].vtf
(512x512 DXT5, clamp flags: the armory format), <name>_metrics.json and <name>_compare.png
(reference | new render(s) over the HUD grey).

  python -B tools/bucket/render_fit_icons.py [--config F] [name ...]
  (env CP_YAW / FRAG_YAW override the upright yaw of the coffee pot / frag grenade, default 30)
"""
import argparse
import json
import os
import random
import re
import sys
import types

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import iconcfg  # noqa: E402
import render_old_icons as ROI  # noqa: E402

TEAMS = ("red", "blue", "green", "yellow")

FIT = {
    # Beta Cyclops 30306: compared for orientation and lighting with the stock grenade launcher icon
    "bucket_cyclops_b4v2": ("models/tf2cc/oldclass/w_cyclops_b4.mdl", "vgui/loadout/weapons/grenade_launcher", None),
    # Chainsaw (Classic) 30204: posed like Open Fortress's chainsaw sprite (as staged by tf2cc)
    "bucket_chainsaw_b4v2": ("models/tf2cc/oldmerc/w_chainsaw_b4.mdl", "staged:tf2cc/of/bucket/bucket_chainsaw", None),
    # Coffee Pot 30226: no stock pose fits; a fixed upright view framed like the bottle icon
    "bucket_coffeepot_b4v2": ("models/tf2cc/oldmerc/w_coffeepot_4rdm.mdl", "upright:%s" % os.environ.get("CP_YAW", "30"), None),
    # Frag Grenade 30211: upright, one icon per team skin
    "team_frag_b4": ("models/tf2cc/oldmerc/w_frag_b4.mdl", "upright:%s" % os.environ.get("FRAG_YAW", "30"), [0, 1, 2, 3]),
}
# renders mirrored left-right after the fit (to face the same way as the stock icons)
MIRROR = set()
# Upright renders fill the canvas; on the HUD they then dwarf the other buckets. Fit them into this
# fraction of the canvas height, centred. Measured on stock 5205 icons: bottle h 0.32 / area 0.155,
# sandvich 0.31 / 0.147, pistol 0.39 / 0.146.
FIT_HEIGHT = {"team_frag_b4": 0.45,
              # the Coffee Pot to about the stock Jarate icon's area (backpack art: w 0.56 h 0.63,
              # area 0.35; the unscaled pot filled 0.90 x 0.82, area 0.74)
              "bucket_coffeepot_b4v2": 0.50}

IF = S = SS = VFS = vmrender = dxt = None
FS = None


def setup():
    global IF, S, SS, VFS, vmrender, dxt
    ROI.setup()
    import iconfit as _if
    import srcmodel as _s
    import srcshade as _ss
    import vfs as _vfs
    import vmrender as _vm
    import dxt as _dxt
    IF, S, SS, VFS, vmrender, dxt = _if, _s, _ss, _vfs, _vm, _dxt


def vtf_rgba(data):
    import struct
    w, h = struct.unpack_from("<HH", data, 16)
    fmt = struct.unpack_from("<i", data, 52)[0]
    bpp = {15: 1, 0: 4, 12: 4, 13: 0.5}[fmt]
    pix = data[len(data) - int(w * h * bpp):]
    if fmt == 12:
        return np.frombuffer(pix, np.uint8).reshape(h, w, 4)[..., [2, 1, 0, 3]].copy()
    return dxt.decode(pix, w, h, fmt)


def stock_icon(ref):
    """RGBA of a reference icon (its VMT's $basetexture, top mip), squared to 512 like iconfit wants."""
    if ref.startswith("vtf:"):
        return IF.square_icon(vtf_rgba(open(ref[4:], "rb").read()))
    if ref.startswith("staged:"):
        d, b = os.path.split(os.path.join(ROI.STAGE, "materials", ref[7:]))
        cands = sorted(x for x in os.listdir(d) if x.startswith(b) and x.endswith(".vtf") and "_large" not in x)
        if not cands:
            raise SystemExit("no staged VTF for " + ref)
        return IF.square_icon(vtf_rgba(open(os.path.join(d, cands[0]), "rb").read()))
    vmt = None
    for suf in ("", "_large", "_red"):                 # team-coloured stock icons ship only _<team>
        vmt = FS.read("materials/%s%s.vmt" % (ref, suf))
        if vmt:
            break
    if not vmt:
        raise SystemExit("reference icon not found: materials/%s.vmt" % ref)
    bt = re.search(r'"?\$basetexture"?\s+"([^"]+)"', vmt.decode("latin-1"), re.I).group(1).replace("\\", "/")
    return IF.square_icon(vtf_rgba(FS.read("materials/%s.vtf" % bt)))


def fit_height(img, frac):
    """Scale the drawn object (alpha bbox) to `frac` of the canvas height, centred, premultiplied."""
    a = np.asarray(img.convert("RGBA")).astype(np.float32) / 255
    ys, xs = np.where(a[..., 3] > 0.03)
    crop = a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    k = frac * img.height / crop.shape[0]
    pre = np.dstack([crop[..., :3] * crop[..., 3:4], crop[..., 3:4]])
    w, h = max(1, round(crop.shape[1] * k)), max(1, round(crop.shape[0] * k))
    small = np.asarray(Image.fromarray((pre * 255).astype(np.uint8), "RGBA").resize((w, h), Image.LANCZOS)).astype(np.float32) / 255
    rgb = small[..., :3] / np.maximum(small[..., 3:4], 1e-4)
    out = np.zeros((img.height, img.width, 4), np.float32)
    x0, y0 = (img.width - w) // 2, (img.height - h) // 2
    out[y0:y0 + h, x0:x0 + w] = np.dstack([np.clip(rgb, 0, 1), small[..., 3]])
    return Image.fromarray((out * 255 + 0.5).astype(np.uint8), "RGBA")


def load_model(fs, rel):
    rel = ROI.versioned(rel)
    return rel, S.load(ROI.model_file(fs, rel, os.path.join(ROI.OUT, "_tmp")))


def with_skin(m, k):
    m.skins = [m.skins[k]] + [s for i, s in enumerate(m.skins) if i != k]
    return m


def metrics(img, ref):
    a = np.asarray(img)
    st, rs = SS.stats(a), SS.stats(ref)
    return dict(iou=round(float(IF.iou(a[..., 3].astype(np.float32) / 255, ref[..., 3].astype(np.float32) / 255)), 3),
                sat=round(st["sat"], 3), near_black=round(st["near_black"], 3), luma=round(st["luma"], 1),
                ref_sat=round(rs["sat"], 3), ref_near_black=round(rs["near_black"], 3), ref_luma=round(rs["luma"], 1))


def over_grey(img):
    bg = Image.new("RGBA", img.size, (40, 40, 40, 255))
    bg.alpha_composite(img)
    return bg


def run(name, fs, rig):
    rel, ref_path, skins = FIT[name]
    rel, m = load_model(fs, rel)
    ctx = types.SimpleNamespace(fs=fs)
    if ref_path.startswith("upright:"):
        ref = stock_icon("vgui/loadout/weapons/bottle")          # for the colour metrics only
        f = dict(R=IF.rot(float(ref_path[8:]), 0.0, 0.0).tolist(), mirror=False, scale=None, centre=None, persp=None,
                 scores={"pose": "upright, yaw %s" % ref_path[8:]})
    else:
        ref = stock_icon(ref_path)
        f = IF.fit_v2(m, ref, random.Random(7))
    out = {"model": rel, "reference": ref_path, "fit_scores": f["scores"], "icons": {}}
    renders = []
    for k, team in ([(None, None)] if skins is None else list(zip(skins, TEAMS))):
        mm = with_skin(S.load(m.path), k) if k is not None else m
        tex = vmrender.textures_for(ctx, mm, ROI.STAGE)
        mats = vmrender.materials_for(ctx, mm, ROI.STAGE)
        for v in (mats.values() if isinstance(mats, dict) else []):
            v["selfillum"] = False          # a self-illum mask is tinted by a runtime proxy (glow colour); not lit on an icon
        img = IF.render_icon(mm, tex, f, mats=mats, rig=rig)
        if name in MIRROR:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if name in FIT_HEIGHT:
            img = fit_height(img, FIT_HEIGHT[name])
        fn = name + ("_" + team if team else "")
        img.save(os.path.join(ROI.OUT, fn + ".png"))
        open(os.path.join(ROI.OUT, fn + ".vtf"), "wb").write(dxt.icon_vtf(np.asarray(img.convert("RGBA"))))
        out["icons"][fn] = metrics(img, ref)
        renders.append(img)
    sheet = Image.new("RGBA", (512 * (1 + len(renders)), 512), (40, 40, 40, 255))
    sheet.alpha_composite(over_grey(Image.fromarray(ref, "RGBA")), (0, 0))
    for i, r in enumerate(renders):
        sheet.alpha_composite(over_grey(r), (512 * (i + 1), 0))
    sheet.save(os.path.join(ROI.OUT, name + "_compare.png"))
    with open(os.path.join(ROI.OUT, name + "_metrics.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    return out


def main():
    global FS
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="icons to render (default: all in FIT)")
    ap.add_argument("--config", help="config file (default: config.json in the repo root)")
    a = ap.parse_args()
    if a.config:
        iconcfg.use(a.config)
    setup()
    fs = FS = ROI.new_fs()
    rig = SS.rig()
    for n in a.names or list(FIT):
        print(json.dumps(run(n, fs, rig)))


if __name__ == "__main__":
    main()
