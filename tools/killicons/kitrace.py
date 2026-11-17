"""Dependency-free vectoriser + effect layers + SVG writer for kill icons.

Tracer: pixel-crack boundary following (every boundary loop is walked with the filled region on
the same side, so outer outlines and holes get opposite windings and the default nonzero fill
rule renders holes correctly), collinear-run collapse, then closed-loop Ramer-Douglas-Peucker.

Effects are original shapes drawn in the stock manner (half-opacity layer, class cls-1), not copies
of TF2C's stock polygons: a muzzle burst fanning right for guns, a spiky impact star for melee and
thrown items, a flame tongue for flamethrowers, a zig-zag bolt for beam weapons, a sine band for
healing beams. Seeded by the icon name, so a re-run gives the same file.

SVG subset (what the stock files use and lunasvg 5205 renders): svg/defs/style/g/path, class
selectors only, no fill on body paths (the HUD's injected CSS tints them), opacity .5 for effects.
"""
import hashlib
import math

import numpy as np


# ---------------------------------------------------------------- tracing

def trace(mask):
    """Closed boundary loops of a boolean mask in pixel-corner coordinates (x right, y down)."""
    M = np.pad(mask.astype(bool), 1)
    H, W = M.shape
    edges = []
    ys, xs = np.nonzero(M[1:-1, 1:-1])
    ys = ys + 1
    xs = xs + 1
    up = ~M[ys - 1, xs]
    dn = ~M[ys + 1, xs]
    lf = ~M[ys, xs - 1]
    rt = ~M[ys, xs + 1]
    for sel, (dx0, dy0, dx1, dy1) in ((up, (1, 0, 0, 0)), (lf, (0, 0, 0, 1)), (dn, (0, 1, 1, 1)), (rt, (1, 1, 1, 0))):
        X, Y = xs[sel], ys[sel]
        edges.append(np.stack([X + dx0, Y + dy0, X + dx1, Y + dy1], 1))
    E = np.concatenate(edges)
    out = {}
    for i, (a, b, c, d) in enumerate(E.tolist()):
        out.setdefault((a, b), []).append(i)
    used = np.zeros(len(E), bool)
    loops = []
    El = E.tolist()
    for s in range(len(E)):
        if used[s]:
            continue
        loop = []
        i = s
        while not used[i]:
            used[i] = True
            a, b, c, d = El[i]
            loop.append((a, b))
            cands = [j for j in out.get((c, d), []) if not used[j]]
            if not cands:
                break
            if len(cands) > 1:
                # diagonal touch: turn so that pixels touching only at a corner stay separate
                dx, dy = c - a, d - b
                best = None
                for j in cands:
                    ex, ey = El[j][2] - El[j][0], El[j][3] - El[j][1]
                    cr = dx * ey - dy * ex
                    if best is None or cr > best[0]:
                        best = (cr, j)
                i = best[1]
            else:
                i = cands[0]
        if len(loop) >= 4:
            loops.append(np.array(loop, float) - 1.0)   # undo the pad
    return loops


def _collapse(P):
    keep = []
    n = len(P)
    for k in range(n):
        a, b, c = P[k - 1], P[k], P[(k + 1) % n]
        if abs((b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])) > 1e-9:
            keep.append(b)
    return np.array(keep) if len(keep) >= 3 else P


def _rdp(P, eps):
    if len(P) < 3:
        return P
    a, b = P[0], P[-1]
    ab = b - a
    L = np.hypot(*ab)
    if L < 1e-12:
        d = np.hypot(*(P - a).T)
    else:
        d = np.abs(ab[0] * (P[:, 1] - a[1]) - ab[1] * (P[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > eps:
        return np.vstack([_rdp(P[:i + 1], eps)[:-1], _rdp(P[i:], eps)])
    return np.vstack([a, b])


def simplify(loop, eps):
    P = _collapse(loop)
    if len(P) < 4:
        return P
    # split the closed loop at its two mutually farthest points
    i = int(np.argmax(np.hypot(*(P - P[0]).T)))
    j = int(np.argmax(np.hypot(*(P - P[i]).T)))
    i, j = sorted((i, j))
    A = _rdp(P[i:j + 1], eps)
    B = _rdp(np.vstack([P[j:], P[:i + 1]]), eps)
    Q = np.vstack([A[:-1], B[:-1]])
    return Q


def area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def fmt(v):
    s = "%.2f" % v
    s = s.rstrip("0").rstrip(".") if "." in s else s
    if s.startswith("0."):
        s = s[1:]
    elif s.startswith("-0."):
        s = "-" + s[2:]
    return "0" if s in ("", "-0", "-") else s


def path_d(loops):
    """Relative-coordinate path data, like the stock (Illustrator-exported) files."""
    parts = []
    cur = (0.0, 0.0)
    for P in loops:
        P = np.round(P, 2)
        x0, y0 = P[0]
        seg = ["M%s,%s" % (fmt(x0), fmt(y0)) if not parts else "M%s,%s" % (fmt(x0), fmt(y0))]
        px, py = x0, y0
        rel = []
        for x, y in P[1:]:
            dx, dy = round(x - px, 2), round(y - py, 2)
            rel.append(fmt(dx) + ("," if not fmt(dy).startswith("-") else "") + fmt(dy))
            px, py = px + dx, py + dy
        seg.append("l" + " ".join(rel).replace(" -", "-") + "Z")
        parts.append("".join(seg))
        cur = (x0, y0)
    del cur
    return "".join(parts)


def mask_to_loops(mask, px, eps_px=0.9, min_area_units=0.6):
    loops = []
    for L in trace(mask):
        Q = simplify(L, eps_px)
        if len(Q) < 3 or abs(area(Q)) < min_area_units * px * px:
            continue
        loops.append(Q / px)
    return loops


# ---------------------------------------------------------------- effects (original shapes)

def _rng(name, salt):
    h = hashlib.sha1((name + "|" + salt).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "little"))


def muzzle_burst(name, x, y, size, top_room=None, bot_room=None, vscale=0.62):
    """Jagged burst fanning rightward from the muzzle point (x, y), its base exactly on (x, y).
    The upper / lower halves are squashed independently to stay inside the canvas rows
    (top_room / bot_room units above / below y), so the burst never drifts off the barrel."""
    r = _rng(name, "muzzle")
    n = 5
    angs = np.linspace(-68, 68, n) + r.uniform(-6, 6, n)
    pts = [(x, y - 0.14 * size)]
    for k, a in enumerate(angs):
        R = size * (r.uniform(0.85, 1.0) if k % 2 == 0 else r.uniform(0.62, 0.8))
        ar = math.radians(a)
        pts.append((x + R * math.cos(ar), y - R * math.sin(ar) * vscale))
        if k < n - 1:
            ai = math.radians((a + angs[k + 1]) / 2)
            Ri = size * r.uniform(0.42, 0.55)
            pts.append((x + Ri * math.cos(ai), y - Ri * math.sin(ai) * vscale))
    pts.append((x, y + 0.14 * size))
    P = np.array(pts[::-1])
    dy = P[:, 1] - y
    if top_room is not None and -dy.min() > top_room:
        dy = np.where(dy < 0, dy * top_room / -dy.min(), dy)
    if bot_room is not None and dy.max() > bot_room:
        dy = np.where(dy > 0, dy * bot_room / dy.max(), dy)
    P[:, 1] = y + dy
    return P


def impact_star(name, x, y, size, fan=(-80, 150)):
    """Spiky star centred at (x, y); spikes only inside the angular fan (degrees, CCW from +x)."""
    r = _rng(name, "impact")
    n = 7
    a0, a1 = fan
    angs = np.linspace(a0, a1, n) + r.uniform(-6, 6, n)
    pts = [(x, y)]
    for k, a in enumerate(angs):
        R = size * (r.uniform(0.85, 1.0) if k % 2 == 0 else r.uniform(0.6, 0.85))
        ar = math.radians(a)
        pts.append((x + R * math.cos(ar), y - R * math.sin(ar)))
        if k < n - 1:
            ai = math.radians((a + angs[k + 1]) / 2)
            Ri = size * r.uniform(0.28, 0.4)
            pts.append((x + Ri * math.cos(ai), y - Ri * math.sin(ai)))
    return np.array(pts)


def flame(name, x, y, length, h):
    r = _rng(name, "flame")
    top, bot = [], []
    n = 7
    for k in range(n + 1):
        t = k / n
        w = h * (0.25 + 0.75 * math.sin(math.pi * min(1.0, t * 1.15)) ** 0.8) * (1 - 0.55 * t)
        wob = r.uniform(-0.12, 0.12) * h
        xx = x + t * length
        top.append((xx, y - w / 2 + wob - 0.35 * h * t))
        bot.append((xx, y + w / 2 + wob * 0.5 - 0.15 * h * t))
    tip = (x + length * 1.08, y - 0.55 * h)
    return np.array(bot + [tip] + top[::-1])


def bolt(name, x, y, length, h, thick=1.5):
    r = _rng(name, "bolt")
    n = 6
    xs = np.linspace(x, x + length, n + 1)
    ys = y + np.array([0] + [(h / 2) * (1 if k % 2 else -1) * r.uniform(0.6, 1.0) for k in range(1, n)] + [0])
    top = [(a, b - thick / 2) for a, b in zip(xs, ys)]
    bot = [(a, b + thick / 2) for a, b in zip(xs, ys)]
    return np.array(bot + [(x + length + 2.5, y)] + top[::-1])


def heal_band(name, x, y, length, amp=2.2, thick=2.0):
    n = 24
    xs = np.linspace(x, x + length, n + 1)
    ys = y + amp * np.sin(np.linspace(0, 2.5 * math.pi, n + 1))
    top = [(a, b - thick / 2) for a, b in zip(xs, ys)]
    bot = [(a, b + thick / 2) for a, b in zip(xs, ys)]
    return np.array(bot + top[::-1])


def orient(P, positive):
    """Give polygon P the same winding sign as the body's outer loops."""
    if (area(P) > 0) != positive:
        return P[::-1]
    return P


# ---------------------------------------------------------------- svg

def write_svg(path, width, body_loops, layers):
    """layers: [(loops, kind)] drawn before the body; kind 'half' = stock .cls{opacity:.5},
    or a literal colour '#rrggbb' = stock .cls{fill:#rrggbb} (flamethrower flame #e17800, taser
    zap #00e1ff): a class selector outranks the HUD's injected `svg *` fill, so it stays coloured."""
    w = fmt(width)
    css, cls_of, out = [], {}, []
    for loops, kind in layers:
        if not loops:
            continue
        if kind not in cls_of:
            cls_of[kind] = "cls-%d" % (len(cls_of) + 1)
            css.append(".%s{%s}" % (cls_of[kind], "opacity:.5" if kind == "half" else "fill:" + kind))
        out.append('<path d="%s" class="%s"/>' % (path_d(loops), cls_of[kind]))
    out.append('<path d="%s"/>' % path_d(body_loops))
    defs = "<defs><style>%s</style></defs>" % "".join(css) if css else ""
    svg = ('<?xml version="1.0" encoding="UTF-8"?><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s 32">'
           '%s%s</svg>' % (w, defs, "".join(out)))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(svg)
    return len(svg.encode())
