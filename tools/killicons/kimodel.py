"""Model access, side-profile pose and orthographic raster buffers for kill-icon generation.

Read-only: models come from the TF2 Classified server's search path (loose dirs + VPKs) through a
tiny VPK reader (paths from config.json, see tools/iconcfg.py); nothing is written anywhere
except the local model cache.

Pose ("from the weapon's axis"):
  forward f : the muzzle attachment's X axis (guns), else the first principal axis of the vertices,
              signed toward the muzzle attachment / the wider end (melee head), or by override
  view      : the thinnest direction orthogonal to f (true side profile)
  up u      : the remaining axis; for guns signed so the barrel (muzzle) sits above the mass
              centre (grip and magazine hang down)
  screen    : x = f (muzzle right), y = u (up); camera looks along -(f x u) so it is not mirrored
Melee and tools are then rotated so the head points up-right (default 28 deg, like stock bat / axe).

Buffers at `px` pixels per icon unit (32 units = icon height): mask, part id (welded mesh component
* 64 + material), depth (model units, nearer = smaller) and interpolated vertex normals.
"""
import os
import struct
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import iconcfg  # noqa: E402  (game paths from config.json)
import srcmodel as S  # noqa: E402  (read-only MDL/VVD/VTX loader)


def _cstr(f):
    b = bytearray()
    while True:
        c = f.read(1)
        if c in (b"\0", b""):
            return b.decode("latin-1")
        b += c


class VPK:
    def __init__(self, path):
        self.path, self.ents = path, {}
        with open(path, "rb") as f:
            _sig, ver, tree = struct.unpack("<III", f.read(12))
            if ver == 2:
                f.read(16)
            self.base = f.tell() + tree
            while True:
                ext = _cstr(f)
                if not ext:
                    break
                while True:
                    d = _cstr(f)
                    if not d:
                        break
                    while True:
                        n = _cstr(f)
                        if not n:
                            break
                        _crc, pre, arc, off, ln, _t = struct.unpack("<IHHIIH", f.read(18))
                        pd = f.read(pre)
                        p = ((d + "/") if d.strip() else "") + n + "." + ext
                        self.ents[p.lower()] = (arc, off, ln, pd)

    def read(self, rel):
        e = self.ents.get(rel.lower())
        if e is None:
            return None
        arc, off, ln, pd = e
        if not ln:
            return pd
        ap = self.path if arc == 0x7FFF else self.path[:-8] + "_%03d.vpk" % arc
        with open(ap, "rb") as f:
            f.seek(self.base + off if arc == 0x7FFF else off)
            return pd + f.read(ln)


class FS:
    def __init__(self, order=None):
        self.src = []
        for kind, p in order or iconcfg.search_order():
            if kind == "dir" and os.path.isdir(p):
                self.src.append(("dir", p))
            elif kind == "vpk" and os.path.exists(p):
                self.src.append(("vpk", VPK(p)))

    def read(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        for kind, s in self.src:
            if kind == "dir":
                fp = os.path.join(s, rel)
                if os.path.isfile(fp):
                    with open(fp, "rb") as f:
                        return f.read()
            else:
                d = s.read(rel)
                if d is not None:
                    return d
        return None

    def where(self, rel):
        rel = rel.replace("\\", "/").lstrip("/")
        for kind, s in self.src:
            if kind == "dir" and os.path.isfile(os.path.join(s, rel)):
                return s
            if kind == "vpk" and rel.lower() in s.ents:
                return s.path
        return None


def fetch_model(fs, rel, cache):
    """Copy .mdl/.vvd/.vtx of `rel` into the cache and return the local .mdl path."""
    out = os.path.join(cache, rel.replace("/", "__"))
    os.makedirs(cache, exist_ok=True)
    for ext in (".mdl", ".vvd", ".dx90.vtx"):
        b = fs.read(rel[:-4] + ext)
        if b is None and ext == ".dx90.vtx":
            b = fs.read(rel[:-4] + ".vtx")
        if b is None:
            raise FileNotFoundError(rel[:-4] + ext)
        with open(out[:-4] + ext, "wb") as f:
            f.write(b)
    return out


# ---------------------------------------------------------------- geometry selection

def select(m, spec):
    """Triangles (N,3 vertex ids) + per-triangle material, honouring bodygroups / material drops /
    an optional vertex clip box (model space) from the manifest entry."""
    drop = [d.lower() for d in spec.get("drop_mats", [])] + ["nodraw"]
    bg = {int(k): v for k, v in spec.get("bodygroups", {}).items()}
    ranges = []
    for i, bp in enumerate(m.bodyparts):
        if bp["name"].lower().startswith("illum"):
            continue
        if i in spec.get("drop_bodyparts", []):
            continue
        md = bp["models"][bg.get(i, 0)]
        if md["nverts"] == 0:
            # an empty default (e.g. a hidden shell) stays hidden unless a bodygroup asks for it
            continue
        ranges.append((md["vstart"], md["vstart"] + md["nverts"]))
    skin0 = m.skins[0] if m.skins else list(range(len(m.textures)))
    tris, mats = [], []
    lod_vstart = None
    for mat, t in m.tris:
        tex = m.textures[skin0[mat] if mat < len(skin0) else mat].lower().replace("\\", "/")
        if any(d in tex for d in drop):
            continue
        tris.append(t)
        mats.append(np.full(len(t), mat))
    if not tris:
        raise ValueError("no triangles")
    T = np.concatenate(tris)
    MT = np.concatenate(mats)
    # bodypart ranges are logical (pre-fixup) ids; tris are raw ids after lod0_map. Map ranges.
    if ranges:
        logical = np.arange(len(m.lod0_map))
        keep_raw = np.zeros(m.nraw, bool)
        for lo, hi in ranges:
            keep_raw[m.lod0_map[logical[lo:hi]]] = True
        sel = keep_raw[T].all(1)
        T, MT = T[sel], MT[sel]
    clip = spec.get("clip")
    if clip:
        P = m.raw_pos
        lo, hi = np.array(clip[0], float), np.array(clip[1], float)
        inb = ((P >= lo) & (P <= hi)).all(1)
        sel = inb[T].all(1)
        T, MT = T[sel], MT[sel]
    del lod_vstart
    return T, MT


def components(P, T):
    """Welded connected-component id per triangle (parts modelled separately: barrel, stock...)."""
    key = np.round(P / 0.02).astype(np.int64)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    inv = inv.ravel()
    parent = np.arange(inv.max() + 1)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    W = inv[T]
    for a, b, c in W:
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    roots = np.array([find(a) for a in W[:, 0]])
    _, cid = np.unique(roots, return_inverse=True)
    return cid.ravel()


# ---------------------------------------------------------------- pose

def _unit(v):
    v = np.asarray(v, float)
    return v / (np.linalg.norm(v) + 1e-12)


def _snap(v, ortho=None, deg=15.0):
    """Source models are built axis-aligned: snap a direction to the nearest model axis if close."""
    best = max(range(3), key=lambda i: abs(v[i]))
    e = np.zeros(3)
    e[best] = np.sign(v[best])
    if e @ v > np.cos(np.radians(deg)) and (ortho is None or abs(e @ ortho) < 1e-6):
        return e
    return v


def muzzle_world(m):
    W = S.rest_world(m)
    mz = [a for a in m.attachments if a["name"].lower() in ("muzzle", "muzzle_flash")]
    if not mz:
        return None, None
    A = W[mz[0]["bone"]] @ mz[0]["local"]
    return A[:3, 3], _unit(A[:3, 0])


def pose(m, T, spec, family):
    """Return (R 3x3 rows = screen x, screen y(up), toward viewer; roll degrees; muzzle point or None)."""
    used = np.unique(T)
    P = m.raw_pos[used]
    c = P.mean(0)
    Pc = P - c
    mpos, mdir = muzzle_world(m)
    axis_mode = spec.get("axis", "muzzle" if (mdir is not None and family not in ("melee", "thrown")) else "pca")
    pcs = np.linalg.svd(Pc, full_matrices=False)[2]
    if axis_mode == "muzzle" and mdir is not None:
        f = mdir
    elif axis_mode in ("x", "y", "z"):
        f = np.eye(3)["xyz".index(axis_mode)]
    elif isinstance(axis_mode, list):
        f = _unit(axis_mode)
    else:
        f = pcs[0]
        if mpos is not None and family not in ("melee", "thrown"):
            if (mpos - c) @ f < 0:
                f = -f
        else:
            # head = the end with the larger cross-section
            t = Pc @ f
            r = np.linalg.norm(Pc - np.outer(t, f), axis=1)
            q1, q3 = np.quantile(t, [0.2, 0.8])
            if r[t >= q3].mean() < r[t <= q1].mean():
                f = -f
    if spec.get("flip_f"):
        f = -f
    f = _snap(f)
    # side view: thinnest direction orthogonal to f (SVD of the points flattened along f: the
    # first two singular vectors span the plane, the second is the thin one)
    Q = Pc - np.outer(Pc @ f, f)
    ev = np.linalg.svd(Q, full_matrices=False)[2]
    view = _unit(ev[1] - (ev[1] @ f) * f) if spec.get("view") != "wide" else _unit(ev[0] - (ev[0] @ f) * f)
    if spec.get("view") in ("x", "y", "z"):
        e = np.eye(3)["xyz".index(spec["view"])]
        view = _unit(e - (e @ f) * f)
    view = _snap(view, f)
    u = _unit(np.cross(view, f))
    if family not in ("melee", "thrown"):
        ref = mpos if mpos is not None else c + f * (Pc @ f).max()
        # barrel on top: grip / magazine / stock hang below the muzzle, so there is more model
        # below the muzzle than above it
        t = Pc @ u
        r = (ref - c) @ u
        if (t.max() - r) > (r - t.min()):
            u = -u
    elif "up_hint" in spec:
        u = u if u @ np.array(spec["up_hint"], float) >= 0 else -u
    if spec.get("flip_u"):
        u = -u
    z = np.cross(f, u)
    R = np.stack([f, u, z])
    ang = spec.get("roll", 28.0 if family == "melee" else 0.0)
    return R, ang, (mpos if (mpos is not None and family not in ("melee", "thrown")) else None)


def rollmat(ang):
    a = np.radians(ang)
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])


# ---------------------------------------------------------------- raster

def raster(m, T, MT, R, px_per_model, origin, size):
    """Orthographic z-buffer raster. origin = model-space screen coords (x,y) of the canvas'
    left/bottom; size = (W,H) pixels. Returns mask, id, depth, normal buffers."""
    W, H = size
    P = m.raw_pos @ R.T
    N = m.raw_nrm @ np.linalg.inv(R)  # inverse-transpose (R may carry a stretch)
    sx = (P[:, 0] - origin[0]) * px_per_model
    sy = H - (P[:, 1] - origin[1]) * px_per_model
    dz = -P[:, 2]                                   # nearer = smaller
    cid = components(m.raw_pos, T)
    ids = cid * 64 + (MT % 64)
    zbuf = np.full((H, W), np.inf)
    idb = np.full((H, W), -1, np.int64)
    nb = np.zeros((H, W, 3))
    for k, (a, b, c) in enumerate(T):
        xa, xb, xc = sx[a], sx[b], sx[c]
        ya, yb, yc = sy[a], sy[b], sy[c]
        x0 = max(0, int(np.floor(min(xa, xb, xc))))
        x1 = min(W - 1, int(np.ceil(max(xa, xb, xc))))
        y0 = max(0, int(np.floor(min(ya, yb, yc))))
        y1 = min(H - 1, int(np.ceil(max(ya, yb, yc))))
        if x1 < x0 or y1 < y0:
            continue
        den = (yb - yc) * (xa - xc) + (xc - xb) * (ya - yc)
        if abs(den) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((yb - yc) * (gx - xc) + (xc - xb) * (gy - yc)) / den
        w1 = ((yc - ya) * (gx - xc) + (xa - xc) * (gy - yc)) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * dz[a] + w1 * dz[b] + w2 * dz[c]
        zb = zbuf[y0:y1 + 1, x0:x1 + 1]
        win = inside & (z < zb)
        if not win.any():
            continue
        zb[win] = z[win]
        idb[y0:y1 + 1, x0:x1 + 1][win] = ids[k]
        n = w0[..., None] * N[a] + w1[..., None] * N[b] + w2[..., None] * N[c]
        nb[y0:y1 + 1, x0:x1 + 1][win] = n[win]
    nb /= np.linalg.norm(nb, axis=2, keepdims=True) + 1e-9
    mask = np.isfinite(zbuf)
    return mask, idb, np.where(mask, zbuf, 0.0), nb


def projected_bounds(m, T, R):
    P = m.raw_pos[np.unique(T)] @ R.T
    return P[:, 0].min(), P[:, 0].max(), P[:, 1].min(), P[:, 1].max(), P
