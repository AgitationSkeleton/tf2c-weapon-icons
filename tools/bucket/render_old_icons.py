"""Render HUD-bucket / armory icons framed like the old TF2 Classic and Open Fortress bucket
sprites, with CustomSlop's v2 renderer (https://github.com/AgitationSkeleton/tf2c-customslop,
tools/render.py: render(v2=True), Source-like shading from each material's VMT via
vmrender.materials_for). CustomSlop is used read-only, from the folder in config key
"customslop_tools".

Camera: the old TF2C / OF bucket sprites are three-quarter shots of the world model, muzzle to the
left, about 22 deg yaw and 10 deg pitch, filling a 256x128 frame. A silhouette fit against another
weapon's sprite gave tilted poses for these models, so the weapon axis is chosen per model (muzzle
attachment position or forward vector, or the principal axis) with an optional vertical flip /
roll that levels the barrel; the result is framed like the old sprites.

Output per icon in <out_dir>/bucket/:
  <name>.png        256x128 RGBA (the old sprites' frame)
  <name>.vtf        256x128 RGBA8888, one mip (the old sprites' layout)
  <name>_512.vtf    the format TF2 Classified's armory needs: the 256x128 band padded to a square,
                    upscaled to 512x512 (premultiplied) and stored as DXT5 with clamp flags
  <name>_512.png    a preview of that square texture

  python -B tools/bucket/render_old_icons.py [--config F] [name ...]
(-B: no __pycache__ written into the CustomSlop checkout)
"""
import argparse
import os
import struct
import sys
import types

import numpy as np
from PIL import Image, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import iconcfg  # noqa: E402

# name: (world model, weapon axis: pos | fwd | fwd- | svd | svd-, vertical flip, roll deg)
ICONS = {
    # MarxVee Machine Gun (v2), old-Merc Heavy Artillery (beta 2), snubnose Six-Shooter (beta 4)
    "bucket_machinegun_v2": ("models/tf2cc/marxvee/weapons/customclasses/w_models/w_machinegun_merc.mdl", "fwd", False, 0),
    "bucket_heavyartillery_b2": ("models/tf2cc/oldmerc/w_heavyartillery_b2.mdl", "fwd", False, 0),
    "bucket_snubnose_b4": ("models/tf2cc/oldmerc/w_snubnose_b4.mdl", "fwd", True, 5),
}

RD = S = VFS = vmrender = None
STAGE = OUT = None


def setup():
    """Import CustomSlop's renderer and resolve the configured folders (idempotent)."""
    global RD, S, VFS, vmrender, STAGE, OUT
    if RD is not None:
        return
    cs = iconcfg.need("customslop_tools")
    if not os.path.exists(os.path.join(cs, "render.py")):
        raise SystemExit("customslop_tools=%r has no render.py (point it at tf2c-customslop/tools)" % cs)
    sys.path.insert(0, cs)
    import render as _rd
    import srcmodel as _s
    import vfs as _vfs
    import vmrender as _vm
    RD, S, VFS, vmrender = _rd, _s, _vfs, _vm
    STAGE = iconcfg.need("staging_dir")
    OUT = os.path.join(iconcfg.out_dir(), "bucket")
    os.makedirs(OUT, exist_ok=True)


def new_fs():
    setup()
    return VFS.VFS(iconcfg.search_order(first=[("dir", STAGE)]))


def model_file(fs, rel, tmp):
    """The model (+ .vvd/.vtx) as local files: staged ones in place, others from the VFS."""
    p = os.path.join(STAGE, rel)
    if os.path.exists(p):
        return p
    os.makedirs(tmp, exist_ok=True)
    out = os.path.join(tmp, os.path.basename(rel))
    for ext in (".mdl", ".vvd", ".dx90.vtx"):
        b = fs.read(rel[:-4] + ext)
        if b is None:
            raise SystemExit("model part missing: " + rel[:-4] + ext)
        open(out[:-4] + ext, "wb").write(b)
    return out


def versioned(rel):
    """The staged path of a model if the build renamed it with a content hash (name_<hash8>.mdl)."""
    if os.path.exists(os.path.join(STAGE, rel)):
        return rel
    d, base = os.path.split(rel)
    stem = base[:-4]
    sd = os.path.join(STAGE, d)
    if os.path.isdir(sd):
        for f in sorted(os.listdir(sd)):
            if f.startswith(stem + "_") and f.endswith(".mdl") and len(f) == len(stem) + 13:
                return d + "/" + f
    return rel


def weapon_axis(m, kind):
    if kind == "pos":
        return None                                   # render.py's own: the muzzle's position
    if kind.startswith("fwd"):
        W = S.rest_world(m)
        mz = [a for a in m.attachments if a["name"].lower() == "muzzle"]
        ax = (W[mz[0]["bone"]] @ mz[0]["local"])[:3, 0]
    else:
        ax = np.linalg.svd(m.raw_pos - m.raw_pos.mean(0))[2][0]
    return -ax if kind.endswith("-") else ax


def frame(img):
    """Crop to the alpha bbox and fit into 256x128 like the old sprites (about 240x116)."""
    bb = img.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    crop = img.crop(bb)
    s = min(240 / crop.width, 116 / crop.height)
    crop = crop.resize((max(1, round(crop.width * s)), max(1, round(crop.height * s))), Image.LANCZOS)
    band = Image.new("RGBA", (256, 128), (0, 0, 0, 0))
    band.alpha_composite(crop, ((256 - crop.width) // 2, (128 - crop.height) // 2))
    return band


def write_rgba_vtf(path, img):
    """256x128 RGBA8888 (format 0) VTF 7.2, one mip, no thumbnail. Uncompressed: a DXT5 encode
    at 256x128 left magenta blocks on thin parts (measured on the Heavy Artillery's handles)."""
    w, h = img.size
    hdr = bytearray(80)
    struct.pack_into("<4sIII", hdr, 0, b"VTF\0", 7, 2, 80)
    struct.pack_into("<HHIHH", hdr, 16, w, h, 0x2300, 1, 0)
    struct.pack_into("<fff", hdr, 32, 0.5, 0.5, 0.5)
    struct.pack_into("<f", hdr, 48, 1.0)
    struct.pack_into("<iBiBBH", hdr, 52, 0, 1, -1, 0, 0, 1)
    open(path, "wb").write(bytes(hdr) + img.convert("RGBA").tobytes())


def square512(band):
    """The armory format: pad to a square, upscale premultiplied (no dark fringes) to 512x512."""
    sq = Image.new("RGBA", (band.width, band.width), (0, 0, 0, 0))
    sq.alpha_composite(band, (0, (band.width - band.height) // 2))
    return sq.convert("RGBa").resize((512, 512), Image.LANCZOS).convert("RGBA")


def render(name, fs):
    import dxt
    rel, axis, flip, roll = ICONS[name]
    rel = versioned(rel)
    m = S.load(model_file(fs, rel, os.path.join(OUT, "_tmp")))
    ctx = types.SimpleNamespace(fs=fs)
    tex = vmrender.textures_for(ctx, m, STAGE)
    mats = vmrender.materials_for(ctx, m, STAGE)
    img = RD.render(m, [STAGE], size=512, yaw=22, pitch=10, axis=weapon_axis(m, axis), textures=tex, mats=mats, v2=True)
    if flip:
        img = ImageOps.flip(img)
    if roll:
        img = img.rotate(roll, resample=Image.BICUBIC)
    band = frame(img)
    band.save(os.path.join(OUT, name + ".png"))
    write_rgba_vtf(os.path.join(OUT, name + ".vtf"), band)
    sq = square512(band)
    sq.save(os.path.join(OUT, name + "_512.png"))
    open(os.path.join(OUT, name + "_512.vtf"), "wb").write(dxt.icon_vtf(np.asarray(sq)))
    return dict(name=name, model=rel, axis=axis, flip=flip, roll=roll)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="icons to render (default: all in ICONS)")
    ap.add_argument("--config", help="config file (default: config.json in the repo root)")
    a = ap.parse_args()
    if a.config:
        iconcfg.use(a.config)
    fs = new_fs()
    for n in a.names or list(ICONS):
        print(render(n, fs))


if __name__ == "__main__":
    main()
