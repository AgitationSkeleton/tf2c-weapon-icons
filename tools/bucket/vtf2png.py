"""Decode a single-mip-or-more VTF item icon (RGBA8888, BGRA8888 or DXT5) to a PNG: the top mip,
which Source stores last in the file.

  python tools/bucket/vtf2png.py ICON.vtf OUT.png [--crop]

--crop trims the transparent padding (the game's square textures pad the 256x128 sprites).
"""
import argparse
import os
import struct
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dxt  # noqa: E402

BPP = {0: 4, 12: 4, 15: 1}       # bytes per pixel: RGBA8888, BGRA8888, DXT5 (16 bytes / 4x4 block)


def vtf_rgba(data):
    if data[:4] != b"VTF\0":
        raise SystemExit("not a VTF file")
    w, h = struct.unpack_from("<HH", data, 16)
    fmt = struct.unpack_from("<i", data, 52)[0]
    if fmt not in BPP:
        raise SystemExit("unsupported VTF format %d (only RGBA8888 / BGRA8888 / DXT5)" % fmt)
    pix = data[len(data) - w * h * BPP[fmt]:]
    if fmt == 12:
        return np.frombuffer(pix, np.uint8).reshape(h, w, 4)[..., [2, 1, 0, 3]].copy()
    return dxt.decode(pix, w, h, fmt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vtf")
    ap.add_argument("png")
    ap.add_argument("--crop", action="store_true")
    a = ap.parse_args()
    img = Image.fromarray(vtf_rgba(open(a.vtf, "rb").read()), "RGBA")
    if a.crop:
        bb = img.getchannel("A").getbbox()
        if bb:
            img = img.crop(bb)
    img.save(a.png)
    print(a.png, img.size)


if __name__ == "__main__":
    main()
