"""SVG rasteriser used to measure / preview kill icons (nonzero winding, classes, transforms).
Unchanged (apart from this docstring) from the 2026-11-16 kill-icon research, where it measured
the 96 stock TF2 Classified death-notice icons."""
import re, math, numpy as np, xml.etree.ElementTree as ET
NUM = r'[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?'


def toks(d):
    return re.findall(r'[MmLlHhVvCcSsQqTtAaZz]|' + NUM, d)


def arc_pts(x1, y1, rx, ry, phi, fa, fs, x2, y2, n=16):
    if rx == 0 or ry == 0:
        return [(x2, y2)]
    phi = math.radians(phi); c, s = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    xp = c * dx + s * dy; yp = -s * dx + c * dy
    rx, ry = abs(rx), abs(ry)
    L = xp * xp / (rx * rx) + yp * yp / (ry * ry)
    if L > 1:
        rx *= math.sqrt(L); ry *= math.sqrt(L)
    num = rx * rx * ry * ry - rx * rx * yp * yp - ry * ry * xp * xp
    den = rx * rx * yp * yp + ry * ry * xp * xp
    k = math.sqrt(max(0, num / den)) if den else 0
    if fa == fs:
        k = -k
    cxp = k * rx * yp / ry; cyp = -k * ry * xp / rx
    cx = c * cxp - s * cyp + (x1 + x2) / 2; cy = s * cxp + c * cyp + (y1 + y2) / 2

    def ang(ux, uy, vx, vy):
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    t1 = ang(1, 0, (xp - cxp) / rx, (yp - cyp) / ry)
    dt = ang((xp - cxp) / rx, (yp - cyp) / ry, (-xp - cxp) / rx, (-yp - cyp) / ry)
    if not fs and dt > 0: dt -= 2 * math.pi
    if fs and dt < 0: dt += 2 * math.pi
    out = []
    for i in range(1, n + 1):
        t = t1 + dt * i / n
        out.append((cx + rx * math.cos(t) * c - ry * math.sin(t) * s,
                    cy + rx * math.cos(t) * s + ry * math.sin(t) * c))
    return out


def bez(p0, p1, p2, p3, n=12):
    p0, p1, p2, p3 = map(np.array, (p0, p1, p2, p3))
    return [tuple((1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3)
            for t in np.linspace(0, 1, n + 1)[1:]]


def path_polys(d):
    T = toks(d); st = {'i': 0}
    x = y = sx = sy = 0.0; polys = []; cur = []; lc = lq = None; cmd = None

    def num():
        v = float(T[st['i']]); st['i'] += 1; return v

    def flag():
        t = T[st['i']]
        if len(t) > 1 and t[0] in '01' and not t.startswith('0.') and not t.startswith('1.'):
            T[st['i']] = t[1:]; return int(t[0])
        st['i'] += 1; return int(float(t))
    while st['i'] < len(T):
        if re.match(r'[A-Za-z]', T[st['i']]):
            cmd = T[st['i']]; st['i'] += 1
        rel = cmd.islower(); C = cmd.upper()
        if C == 'Z':
            if cur: polys.append(cur)
            cur = []; x, y = sx, sy; lc = lq = None
            continue
        if C == 'M':
            if cur: polys.append(cur)
            nx, ny = num(), num()
            if rel: nx += x; ny += y
            x, y = nx, ny; sx, sy = x, y; cur = [(x, y)]
            cmd = 'l' if rel else 'L'; lc = lq = None
            continue
        if C == 'L':
            nx, ny = num(), num()
            if rel: nx += x; ny += y
            x, y = nx, ny; cur.append((x, y)); lc = lq = None
        elif C == 'H':
            nx = num(); x = nx + x if rel else nx; cur.append((x, y)); lc = lq = None
        elif C == 'V':
            ny = num(); y = ny + y if rel else ny; cur.append((x, y)); lc = lq = None
        elif C in 'CS':
            if C == 'C':
                x1, y1 = num(), num()
                if rel: x1 += x; y1 += y
            else:
                x1, y1 = (2 * x - lc[0], 2 * y - lc[1]) if lc else (x, y)
            x2, y2, nx, ny = num(), num(), num(), num()
            if rel: x2 += x; y2 += y; nx += x; ny += y
            cur += bez((x, y), (x1, y1), (x2, y2), (nx, ny)); lc = (x2, y2); x, y = nx, ny; lq = None
        elif C in 'QT':
            if C == 'Q':
                qx, qy = num(), num()
                if rel: qx += x; qy += y
            else:
                qx, qy = (2 * x - lq[0], 2 * y - lq[1]) if lq else (x, y)
            nx, ny = num(), num()
            if rel: nx += x; ny += y
            c1 = (x + 2 / 3 * (qx - x), y + 2 / 3 * (qy - y)); c2 = (nx + 2 / 3 * (qx - nx), ny + 2 / 3 * (qy - ny))
            cur += bez((x, y), c1, c2, (nx, ny)); lq = (qx, qy); x, y = nx, ny; lc = None
        elif C == 'A':
            rx, ry, ph = num(), num(), num(); fa = flag(); fs = flag(); nx, ny = num(), num()
            if rel: nx += x; ny += y
            cur += arc_pts(x, y, rx, ry, ph, fa, fs, nx, ny); x, y = nx, ny; lc = lq = None
    if cur: polys.append(cur)
    return polys


def ellipse(cx, cy, rx, ry, n=48):
    return [[(cx + rx * math.cos(t), cy + ry * math.sin(t)) for t in np.linspace(0, 2 * math.pi, n, endpoint=False)]]


def parse_css(svg):
    css = {}
    for st in svg.iter('{http://www.w3.org/2000/svg}style'):
        for sel, body in re.findall(r'([^{}]+)\{([^}]*)\}', st.text or ''):
            props = dict((a.strip(), b.strip()) for a, b in (p.split(':', 1) for p in body.split(';') if ':' in p))
            for s in sel.split(','):
                s = s.strip()
                if s.startswith('.'):
                    css.setdefault(s[1:], {}).update(props)
    return css


def parse_tf(t):
    M = np.eye(3)
    for name, args in re.findall(r'(\w+)\(([^)]*)\)', t or ''):
        a = [float(v) for v in re.findall(NUM, args)]
        if name == 'translate':
            m = np.array([[1, 0, a[0]], [0, 1, a[1] if len(a) > 1 else 0], [0, 0, 1]])
        elif name == 'scale':
            m = np.array([[a[0], 0, 0], [0, a[1] if len(a) > 1 else a[0], 0], [0, 0, 1]])
        elif name == 'rotate':
            r = math.radians(a[0]); c, s = math.cos(r), math.sin(r)
            m = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
            if len(a) == 3:
                m = np.array([[1, 0, a[1]], [0, 1, a[2]], [0, 0, 1]]) @ m @ np.array([[1, 0, -a[1]], [0, 1, -a[2]], [0, 0, 1]])
        elif name == 'matrix':
            m = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        else:
            m = np.eye(3)
        M = M @ m
    return M


def shapes(path):
    svg = ET.parse(path).getroot(); css = parse_css(svg)
    vb = [float(v) for v in svg.get('viewBox').replace(',', ' ').split()]
    out = []

    def walk(el, M, inh):
        tag = el.tag.split('}')[-1]
        if tag in ('defs', 'style', 'linearGradient', 'radialGradient'):
            return
        M = M @ parse_tf(el.get('transform'))
        props = dict(inh)
        for c in (el.get('class') or '').split():
            props.update(css.get(c, {}))
        if el.get('fill'): props['fill'] = el.get('fill')
        if el.get('opacity'): props['opacity'] = el.get('opacity')
        P = None
        if tag == 'path':
            P = path_polys(el.get('d'))
        elif tag in ('polygon', 'polyline'):
            v = [float(t) for t in re.findall(NUM, el.get('points'))]; P = [list(zip(v[::2], v[1::2]))]
        elif tag == 'rect':
            x, y, w, h = [float(el.get(k, 0)) for k in ('x', 'y', 'width', 'height')]
            P = [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
        elif tag == 'circle':
            P = ellipse(float(el.get('cx', 0)), float(el.get('cy', 0)), float(el.get('r')), float(el.get('r')))
        elif tag == 'ellipse':
            P = ellipse(float(el.get('cx', 0)), float(el.get('cy', 0)), float(el.get('rx')), float(el.get('ry')))
        if P:
            P = [[tuple((M @ np.array([px, py, 1]))[:2]) for px, py in p] for p in P]
            f = props.get('fill', ''); op = float(props.get('opacity', 1))
            layer = 'gradient' if f.startswith('url') else ('color' if f.startswith('#') else ('half' if op < 1 else 'solid'))
            out.append((P, layer, op))
        for ch in el:
            walk(ch, M, props)
    walk(svg, np.eye(3), {})
    return vb, out


def raster(polys, W, H, scale, ss=4):
    w, h = int(math.ceil(W * scale)), int(math.ceil(H * scale))
    acc = np.zeros((h * ss, w * ss), np.float32)
    edges = []
    for p in polys:
        if len(p) < 2: continue
        q = np.array(p) * scale * ss
        edges.append(np.hstack([q, np.roll(q, -1, 0)]))
    if not edges:
        return np.zeros((h, w))
    E = np.vstack(edges); E = E[E[:, 1] != E[:, 3]]
    for row in range(h * ss):
        yc = row + 0.5
        y0, y1 = E[:, 1], E[:, 3]
        m = ((y0 <= yc) & (y1 > yc)) | ((y1 <= yc) & (y0 > yc))
        if not m.any(): continue
        e = E[m]; t = (yc - e[:, 1]) / (e[:, 3] - e[:, 1]); xi = e[:, 0] + t * (e[:, 2] - e[:, 0])
        dirn = np.where(e[:, 3] > e[:, 1], 1, -1)
        o = np.argsort(xi); xi = xi[o]; dirn = dirn[o]
        wind = np.cumsum(dirn)
        for k in range(len(xi) - 1):
            if wind[k] != 0:
                a = int(math.ceil(xi[k] - 0.5)); b = int(math.ceil(xi[k + 1] - 0.5))
                acc[row, max(a, 0):max(min(b, w * ss), 0)] = 1
    return acc.reshape(h, ss, w, ss).mean(axis=(1, 3))


def render(path, scale=10, ss=4):
    vb, sh = shapes(path); W, H = vb[2], vb[3]
    layers = {}
    for P, layer, op in sh:
        P = [[(x - vb[0], y - vb[1]) for x, y in p] for p in P]
        cov = raster(P, W, H, scale, ss)
        layers.setdefault(layer, np.zeros_like(cov))
        layers[layer] = np.maximum(layers[layer], cov)
    return vb, layers
