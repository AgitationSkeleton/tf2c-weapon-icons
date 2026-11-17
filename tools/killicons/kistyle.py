"""Turn raster buffers into a TF2C-style kill-icon body mask (flat silhouette, negative-space cuts).

Measured stock targets (96 stock SVGs, research metrics.json): cut ("gap") width median 1.17 units
(p25 0.8, p75 1.4), part thickness median 3.0 (thin rods >= ~1.2), 3-21 parts (median 5), slightly
rounded corners (radius 0.3-0.7), very few tiny holes. All lengths below are in icon units
(32 units = icon height) and converted with `px` pixels per unit.
"""
import numpy as np
from scipy import ndimage as nd

CUT_W = 1.1          # gap width
MIN_THICK = 1.6      # thin parts are inflated to at least this
MIN_CUT_LEN = 3.0    # shorter candidate cut lines are ignored
MAX_CUTS = 8
HOLE_FILL = 1.5      # internal holes smaller than this (units^2) are filled
ISLAND_MIN = 3.0     # fragments smaller than this (units^2) are dropped
ROUND_R = 0.35       # corner rounding radius


def disk_dilate(a, r):
    return nd.distance_transform_edt(~a) <= r


def disk_erode(a, r):
    return nd.distance_transform_edt(a) > r


def opening(a, r):
    return disk_dilate(disk_erode(a, r), r)


def closing(a, r):
    pad = int(np.ceil(r)) + 2
    b = np.pad(a, pad)
    return disk_erode(disk_dilate(b, r), r)[pad:-pad, pad:-pad]


def fill_small_holes(m, max_area_px):
    holes = nd.binary_fill_holes(m) & ~m
    lab, n = nd.label(holes)
    if n:
        sizes = nd.sum(holes, lab, range(1, n + 1))
        small = np.isin(lab, 1 + np.nonzero(sizes < max_area_px)[0])
        m = m | small
    return m


def drop_islands(m, min_area_px):
    lab, n = nd.label(m)
    if not n:
        return m
    sizes = nd.sum(m, lab, range(1, n + 1))
    return np.isin(lab, 1 + np.nonzero(sizes >= min_area_px)[0])


def keep_attached(body, sil, px, max_gap=2.2):
    """Drop geometry that floats free of the weapon (e.g. a stray bit behind a launcher).
    Decided on the UNCUT silhouette: silhouette pieces farther than max_gap units from the main
    piece are removed, while parts that our own cut lines separated always stay (round 3: judging
    on the cut body dropped whole cut-off sections where parallel cuts merged into wide gaps)."""
    lab, n = nd.label(sil)
    if n <= 1:
        return body
    sizes = nd.sum(sil, lab, range(1, n + 1))
    keep = lab == (1 + int(np.argmax(sizes)))
    while True:
        near = disk_dilate(keep, max_gap * px)
        add = np.isin(lab, np.unique(lab[near & sil & ~keep]))
        add &= lab > 0
        if not (add & ~keep).any():
            return body & keep
        keep |= add


def thicken(m, px, min_thick=MIN_THICK):
    """Inflate parts thinner than MIN_THICK (rods, trigger guards, hoses) without fattening bulk."""
    r0 = min_thick * px / 2
    core = opening(m, r0)
    # convex corners of bulky parts also vanish under the opening; they lie within ~0.33 r0 of
    # the opened shape, so only pixels farther away than that count as thin parts
    thin = m & ~disk_dilate(core, 0.45 * r0)
    thin = drop_islands(thin, 0.3 * px * px)
    if not thin.any():
        return m
    return m | disk_dilate(thin, max(0.5, min_thick / 2 - 0.3) * px)


def edge_candidates(mask, idb, depth, nb, model_len, px, crease_deg=62.0, depth_frac=0.02):
    """Boolean map of cut-line candidates inside the silhouette."""
    E = np.zeros_like(mask)
    inside = mask.copy()
    for ax in (0, 1):
        a = np.s_[:-1, :] if ax == 0 else np.s_[:, :-1]
        b = np.s_[1:, :] if ax == 0 else np.s_[:, 1:]
        both = inside[a] & inside[b]
        idc = both & (idb[a] != idb[b])
        dc = both & (np.abs(depth[a] - depth[b]) > depth_frac * model_len)
        cosang = (nb[a] * nb[b]).sum(-1)
        cc = both & (cosang < np.cos(np.radians(crease_deg)))
        e = idc | dc | cc
        # mark the nearer-to-viewer side's neighbour (the farther pixel) so cuts sit "behind" parts
        far_a = depth[a] > depth[b]
        Ea = E[a]
        Eb = E[b]
        Ea |= e & far_a
        Eb |= e & ~far_a
    return E


def select_cuts(E, mask, px, weapon_axis_deg=0.0, max_cuts=MAX_CUTS):
    """Keep the longest, most axis-perpendicular cut segments; drop lines hugging the outline."""
    border_d = nd.distance_transform_edt(mask)
    core = E & (border_d > 1.0 * px)
    core = nd.binary_dilation(core, iterations=1)
    lab, n = nd.label(core, structure=np.ones((3, 3)))
    if not n:
        return np.zeros_like(E), []
    scored = []
    for i, sl in enumerate(nd.find_objects(lab), 1):
        comp = lab[sl] == i
        ys, xs = np.nonzero(comp)
        npx = len(ys)
        # length ~ extent along the principal direction
        pts = np.stack([xs, ys], 1).astype(float)
        pts -= pts.mean(0)
        if npx < 3:
            continue
        ev, evec = np.linalg.eigh(pts.T @ pts / npx)
        length = 4 * np.sqrt(max(ev[-1], 0)) + 1
        if length < MIN_CUT_LEN * px:
            continue
        d = evec[:, -1]
        ang = np.degrees(np.arctan2(-d[1], d[0])) - weapon_axis_deg
        perp = abs(np.sin(np.radians(ang)))
        score = length * (0.6 + 0.8 * perp)
        scored.append((score, i, sl, length, perp))
    scored.sort(reverse=True)
    keep = np.zeros_like(E)
    info = []
    for score, i, sl, length, perp in scored[:max_cuts]:
        keep[sl] |= lab[sl] == i
        info.append(dict(len_units=round(length / px, 1), perp=round(perp, 2)))
    # re-grow the kept lines back to the outline so they really separate parts
    keep = E & disk_dilate(keep, 1.3 * px) | keep
    return keep, info


def stylize(mask, idb, depth, nb, px, model_len, weapon_axis_deg=0.0, max_cuts=MAX_CUTS, extra_cuts=None,
            crease_deg=70.0, min_thick=MIN_THICK, max_gap=2.2, hole_fill=HOLE_FILL):
    m = closing(mask, 0.5 * px)
    m = fill_small_holes(m, hole_fill * px * px)
    m = thicken(m, px, min_thick)
    E = edge_candidates(mask, idb, depth, nb, model_len, px, crease_deg=crease_deg)
    E &= m
    cuts, info = select_cuts(E, m, px, weapon_axis_deg, max_cuts)
    if extra_cuts is not None:
        cuts |= extra_cuts
    cutw = disk_dilate(cuts, CUT_W * px / 2) if cuts.any() else cuts
    body = m & ~cutw
    body = opening(body, 0.42 * px)              # slivers < ~0.85 units go, corners round
    body = closing(body, ROUND_R * px) & ~cutw   # soften concave corners, keep the gaps open
    body = drop_islands(body, ISLAND_MIN * px * px)
    body = keep_attached(body, m, px, max_gap)
    return body, dict(cuts=info, silhouette=m)
