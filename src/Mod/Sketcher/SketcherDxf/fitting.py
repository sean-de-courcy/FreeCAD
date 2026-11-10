# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fitting chains of short line segments to lines, arcs and B-splines (FreeCAD-CH).

Logos reach a DXF as thousands of short segments. Each segment is an edge of every face and
boolean downstream, so a pocket, a fillet or a pattern of such a profile is slow in proportion
(about N^1.4: `notes/kernel-robustness.md`, probes 2 and 5). This module replaces such chains by
few curves within a stated tolerance:

1. **Chaining.** Segment ends closer than `join` are one node. A chain runs through nodes where
   exactly two segments meet and nothing else (an arc, a spline, a third segment) ends. Dangling
   ends closer to each other than the tolerance are joined first, nearest pairs first (so an
   outline that misses its start by less than the tolerance closes; a stroke shorter than four
   tolerances is never closed onto itself).
2. **Corners.** A chain is cut at a vertex that turns by more than `corner` degrees, and keeps
   turning by more than that between the points five tolerances back and ahead (so a staircase or
   noise finer than the tolerance is no corner); of a cluster of such vertices the sharpest. The
   corner's vertex is kept exactly, so corners stay sharp.
3. **Lines and arcs.** Each run between corners is cut greedily into the longest line or arc that
   stays within the tolerance of every vertex and every segment's midpoint. An arc runs from one
   vertex to another, its centre on their bisector at the least-squares fit of the vertices
   between (`_arc_center`). A closed run that is a circle within the tolerance becomes one.
4. **Splines.** Where three or more consecutive pieces are short (each covers fewer than
   `KEEP_POINTS` vertices), their vertices are approximated by one cubic B-spline (OCCT's
   GeomAPI_PointsToBSpline), kept only if its measured deviation is within the tolerance;
   otherwise the lines and arcs stay.

Every piece starts and ends on the chain's own vertices, exactly, so consecutive pieces share their
end points and closed outlines stay closed. The deviation reported is measured, not assumed: for
lines and arcs, the distance of each vertex and segment midpoint from the piece; for splines, the
distance of each vertex from the curve and of the curve, between the vertices' parameters, from
the segment it replaces.
"""

import math

KEEP_POINTS = 8  # a line or arc covering this many vertices stays itself


class Piece:
    """A fitted piece: kind 'line' (p, q), 'arc' (p, m, q: through three points) or 'spline'
    (points; curve is the Part.BSplineCurve)"""

    __slots__ = ("kind", "pts", "curve", "dev", "count", "span")

    def __init__(self, kind, pts, dev, count, curve=None, span=None):
        self.kind, self.pts, self.dev, self.count, self.curve = kind, pts, dev, count, curve
        self.span = span  # (first, last) vertex index in the run it was fitted to


# ---------------------------------------------------------------------------------------------


class _Nodes:
    """Points snapped to nodes on a grid of cell `join`"""

    def __init__(self, join):
        self.s = join
        self.grid = {}
        self.pos = []

    def key(self, p):
        return (math.floor(p[0] / self.s), math.floor(p[1] / self.s))

    def find(self, p):
        kx, ky = self.key(p)
        best, bd = None, self.s * self.s
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for n in self.grid.get((kx + dx, ky + dy), ()):
                    q = self.pos[n]
                    d = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
                    if d <= bd:
                        best, bd = n, d
        return best

    def add(self, p):
        n = self.find(p)
        if n is not None:
            return n
        n = len(self.pos)
        self.pos.append(p)
        self.grid.setdefault(self.key(p), []).append(n)
        return n


def chains(segments, other_ends, join, gap):
    """Chains of the segments: ([(points, closed, joins)], gaps joined, widest gap). joins lists, for
    each gap joined into the chain, (kept point, the moved end's original point, the original
    midpoint of the moved end's segment).

    segments: [(p, q)]; other_ends: end points of curves that are not segments (they end chains);
    join: the node tolerance; gap: dangling ends closer than this are joined (0: none)."""
    nodes = _Nodes(join)
    edges = []
    for p, q in segments:
        a, b = nodes.add(p), nodes.add(q)
        if a != b:
            edges.append((a, b))
    blocked = set(nodes.add(p) for p in other_ends)
    deg = [0] * len(nodes.pos)
    for a, b in edges:
        deg[a] += 1
        deg[b] += 1

    joined = 0
    widest = 0.0
    moved = {}  # kept node -> (original point of the end moved onto it, its segment's midpoint)
    if gap > 0.0:
        # join dangling ends pairwise, nearest first, found on a grid of cell `gap`
        dangling = [n for n in range(len(deg)) if deg[n] == 1 and n not in blocked]
        # each component's length: the two ends of a piece shorter than a few gaps are not
        # joined to each other (that would make a loop of nothing of a stray stroke)
        parent = list(range(len(nodes.pos)))

        def root(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        size = {}
        for a, b in edges:
            ra, rb = root(a), root(b)
            if ra != rb:
                parent[ra] = rb
        for a, b in edges:
            pa, pb = nodes.pos[a], nodes.pos[b]
            r = root(a)
            size[r] = size.get(r, 0.0) + math.hypot(pa[0] - pb[0], pa[1] - pb[1])
        grid = {}
        for n in dangling:
            p = nodes.pos[n]
            grid.setdefault((math.floor(p[0] / gap), math.floor(p[1] / gap)), []).append(n)
        cand = []
        for n in dangling:
            p = nodes.pos[n]
            kx, ky = math.floor(p[0] / gap), math.floor(p[1] / gap)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for o in grid.get((kx + dx, ky + dy), ()):
                        if o <= n:
                            continue
                        q = nodes.pos[o]
                        d = math.hypot(p[0] - q[0], p[1] - q[1])
                        if d > gap:
                            continue
                        r = root(n)
                        if r == root(o) and size.get(r, 0.0) < 4.0 * gap:
                            continue
                        cand.append((d, n, o))
        cand.sort()
        alias = {}
        used = set()
        for d, a, b in cand:
            if a in used or b in used:
                continue
            used.add(a)
            used.add(b)
            alias[b] = a
            joined += 1
            widest = max(widest, d)
            pb = nodes.pos[b]
            other = [y if x == b else x for x, y in edges if b in (x, y)]
            mid = pb
            if other:
                po = nodes.pos[other[0]]
                mid = ((pb[0] + po[0]) * 0.5, (pb[1] + po[1]) * 0.5)
            moved[a] = (pb, mid)
        if alias:
            edges = [(alias.get(a, a), alias.get(b, b)) for a, b in edges]
            edges = [(a, b) for a, b in edges if a != b]
            deg = [0] * len(nodes.pos)
            for a, b in edges:
                deg[a] += 1
                deg[b] += 1

    adj = [[] for _ in nodes.pos]
    for k, (a, b) in enumerate(edges):
        adj[a].append(k)
        adj[b].append(k)
    used = [False] * len(edges)

    def through(n):
        return deg[n] == 2 and n not in blocked

    out = []

    def _joins(seq):
        return [(nodes.pos[i],) + moved[i] for i in dict.fromkeys(seq) if i in moved]

    def walk(start, k):
        seq = [start]
        n = start
        while True:
            used[k] = True
            a, b = edges[k]
            n = b if a == n else a
            seq.append(n)
            if n == start or not through(n):
                break
            nxt = [e for e in adj[n] if not used[e]]
            if not nxt:
                break
            k = nxt[0]
        return seq

    for n in range(len(nodes.pos)):
        if through(n):
            continue
        for k in adj[n]:
            if not used[k]:
                seq = walk(n, k)
                out.append(([nodes.pos[i] for i in seq], False, _joins(seq)))
    for k in range(len(edges)):
        if not used[k]:
            start = edges[k][0]
            seq = walk(start, k)
            closed = seq[-1] == seq[0]
            out.append(([nodes.pos[i] for i in seq], closed, _joins(seq)))
    return out, joined, widest


# ---------------------------------------------------------------------------------------------
# geometry helpers


def _circle3(a, b, c):
    """Centre and radius of the circle through three points, None if collinear"""
    bx, by = b[0] - a[0], b[1] - a[1]
    cx, cy = c[0] - a[0], c[1] - a[1]
    d = 2.0 * (bx * cy - by * cx)
    if abs(d) < 1e-300:
        return None
    b2, c2 = bx * bx + by * by, cx * cx + cy * cy
    ux = (cy * b2 - by * c2) / d
    uy = (bx * c2 - cx * b2) / d
    return (a[0] + ux, a[1] + uy), math.hypot(ux, uy)


def _line_dev(pts, i, j, tol):
    """Largest distance of pts[i..j] from the chord, or None when over tol or not monotone"""
    p, q = pts[i], pts[j]
    dx, dy = q[0] - p[0], q[1] - p[1]
    L = math.hypot(dx, dy)
    if L == 0.0:
        return None
    ux, uy = dx / L, dy / L
    worst = 0.0
    last = -tol
    for k in range(i + 1, j):
        rx, ry = pts[k][0] - p[0], pts[k][1] - p[1]
        t = rx * ux + ry * uy
        d = abs(rx * uy - ry * ux)
        if d > tol or t < last - tol or t > L + tol:
            return None
        last = max(last, t)
        worst = max(worst, d)
    return worst


def _arc_center(pts, i, j):
    """The circle through pts[i] and pts[j] that fits pts[i..j] best: its centre on the chord's
    perpendicular bisector, at the least-squares solution of |P - C|^2 = R^2 (linear in the
    centre's offset along the bisector); (cx, cy, r) or None when the points are collinear"""
    a, c = pts[i], pts[j]
    mx, my = (a[0] + c[0]) * 0.5, (a[1] + c[1]) * 0.5
    dx, dy = c[0] - a[0], c[1] - a[1]
    L = math.hypot(dx, dy)
    if L == 0.0:
        return None
    nx, ny = -dy / L, dx / L
    h2 = (L * 0.5) ** 2
    num = den = 0.0
    for k in range(i + 1, j):
        px, py = pts[k][0] - mx, pts[k][1] - my
        ak = px * px + py * py - h2
        bk = 2.0 * (px * nx + py * ny)
        num += ak * bk
        den += bk * bk
    if den <= 1e-300:
        return None
    s_ = num / den
    cx, cy = mx + s_ * nx, my + s_ * ny
    return cx, cy, math.sqrt(h2 + s_ * s_)


def _arc_mid(pts, i, j):
    """A point in the middle of the fitted arc from pts[i] to pts[j]"""
    cx, cy, r = _arc_center(pts, i, j)
    b = pts[(i + j) // 2]
    d = math.hypot(b[0] - cx, b[1] - cy)
    return (cx + (b[0] - cx) * r / d, cy + (b[1] - cy) * r / d)


def _arc_dev(pts, i, j, tol, rmax):
    """Largest deviation of pts[i..j] and their segments' midpoints from the fitted arc from
    pts[i] to pts[j] (`_arc_center`); None when over tol, turning back, or nearly a line"""
    if j - i < 2:
        return None
    cr = _arc_center(pts, i, j)
    if cr is None:
        return None
    cx, cy, r = cr
    if r > rmax:
        return None
    a, b, c = pts[i], pts[(i + j) // 2], pts[j]
    orient = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
    if orient == 0.0:
        return None
    sgn = 1.0 if orient > 0 else -1.0
    worst = 0.0
    sweep = 0.0
    prev = math.atan2(a[1] - cy, a[0] - cx)
    for k in range(i + 1, j + 1):
        p = pts[k]
        d = abs(math.hypot(p[0] - cx, p[1] - cy) - r)
        if d > tol:
            return None
        q = pts[k - 1]
        mx, my = (p[0] + q[0]) * 0.5, (p[1] + q[1]) * 0.5
        dm = abs(math.hypot(mx - cx, my - cy) - r)
        if dm > tol:
            return None
        ang = math.atan2(p[1] - cy, p[0] - cx)
        step = (ang - prev + math.pi) % (2.0 * math.pi) - math.pi
        if step * sgn < -1e-12:
            return None
        sweep += abs(step)
        prev = ang
        worst = max(worst, d, dm)
    if sweep >= 2.0 * math.pi - 1e-9:
        return None
    return worst


def _longest(pts, i, n, test, first=1):
    """The largest j >= i + first such that test(i, j) is not None (growing, then bisecting)"""
    good, good_d = None, None
    if i + first > n:
        return good, good_d
    step = first
    while True:
        j = min(i + step, n)
        d = test(i, j)
        if d is None:
            bad = j
            break
        good, good_d = j, d
        if j == n:
            return good, good_d
        step *= 2
    lo = good if good is not None else i + first - 1
    while bad - lo > 1:
        mid = (lo + bad) // 2
        d = test(i, mid)
        if d is None:
            bad = mid
        else:
            lo, good, good_d = mid, mid, d
    return good, good_d


def _greedy(pts, tol, rmax):
    """Lines and arcs over pts (indices into pts, start to end)"""
    n = len(pts) - 1
    out = []
    i = 0
    while i < n:
        jl, dl = _longest(pts, i, n, lambda a, b: _line_dev(pts, a, b, tol))
        ja, da = _longest(pts, i, n, lambda a, b: _arc_dev(pts, a, b, tol, rmax), first=2)
        if jl is None:
            jl, dl = i + 1, 0.0
        if ja is not None and (ja > jl or (ja == jl and da < dl)):
            out.append(Piece("arc", (pts[i], _arc_mid(pts, i, ja), pts[ja]), da, ja - i, span=(i, ja)))
            i = ja
        else:
            out.append(Piece("line", (pts[i], pts[jl]), dl, jl - i, span=(i, jl)))
            i = jl
    return out


def _spline(pts, tol):
    """A cubic B-spline approximating pts within tol (Piece), or None"""
    import FreeCAD
    import Part

    V = FreeCAD.Vector
    vs = [V(p[0], p[1], 0.0) for p in pts]
    try:
        c = Part.BSplineCurve()
        c.approximate(
            Points=vs, DegMin=3, DegMax=3, Tolerance=tol * 0.5, Continuity="C2", ParamType="ChordLength"
        )
    except Exception:
        return None
    # the ends exactly on the chain's vertices
    np_ = c.NbPoles
    c.setPole(1, vs[0])
    c.setPole(np_, vs[-1])
    worst = 0.0
    params = []
    for v in vs:
        try:
            t = c.parameter(v)
        except Exception:
            return None
        params.append(t)
        d = (c.value(t) - v).Length
        if d > tol:
            return None
        worst = max(worst, d)
    for k in range(1, len(params)):
        if params[k] < params[k - 1] - 1e-12:
            return None
        # the curve between two vertices, against the segment it replaces
        for f in (0.25, 0.5, 0.75):
            w = c.value(params[k - 1] + f * (params[k] - params[k - 1]))
            a, b = pts[k - 1], pts[k]
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((w.x - a[0]) * dx + (w.y - a[1]) * dy) / L2))
            d = math.hypot(w.x - (a[0] + t * dx), w.y - (a[1] + t * dy))
            if d > tol:
                return None
            worst = max(worst, d)
    return Piece("spline", None, worst, len(pts) - 1, c)


def _fit_run(pts, tol, rmax):
    """Pieces for one run between corners (pts: points; pieces carry points, not indices)"""
    if len(pts) == 2:
        return [Piece("line", (pts[0], pts[1]), 0.0, 1)]
    greedy = _greedy(pts, tol, rmax)
    seglen = sorted(math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]) for k in range(1, len(pts)))
    median = seglen[len(seglen) // 2]

    def keeper(pc):
        if pc.count >= KEEP_POINTS:
            return True
        if pc.kind == "line":
            i, j = pc.span
            L = math.hypot(pts[j][0] - pts[i][0], pts[j][1] - pts[i][1])
            return L >= 5.0 * median * pc.count
        return False

    out = []
    cluster = []

    def flush():
        if len(cluster) >= 3:
            i0 = cluster[0].span[0]
            i1 = cluster[-1].span[1]
            sp = _spline(pts[i0 : i1 + 1], tol)
            if sp is not None:
                out.append(sp)
                cluster.clear()
                return
        for pc in cluster:
            out.append(pc)
        cluster.clear()

    for pc in greedy:
        if keeper(pc):
            flush()
            out.append(pc)
        else:
            cluster.append(pc)
    flush()
    return out


def _full_circle(ring, tol):
    """A 'circle' Piece (centre, radius) when the closed ring of points is one within tol"""
    m = len(ring)
    if m < 8:
        return None
    cr = _circle3(ring[0], ring[m // 3], ring[(2 * m) // 3])
    if cr is None:
        return None
    (cx, cy), r = cr
    worst = 0.0
    turned = 0.0
    prev = math.atan2(ring[0][1] - cy, ring[0][0] - cx)
    sgn = None
    for k in range(1, m + 1):
        p, q = ring[k % m], ring[k - 1]
        d = abs(math.hypot(p[0] - cx, p[1] - cy) - r)
        dm = abs(math.hypot((p[0] + q[0]) * 0.5 - cx, (p[1] + q[1]) * 0.5 - cy) - r)
        worst = max(worst, d, dm)
        if worst > tol:
            return None
        ang = math.atan2(p[1] - cy, p[0] - cx)
        step = (ang - prev + math.pi) % (2.0 * math.pi) - math.pi
        if sgn is None:
            sgn = 1.0 if step > 0 else -1.0
        if step * sgn <= 0:
            return None
        turned += abs(step)
        prev = ang
    if abs(turned - 2.0 * math.pi) > 1e-6:
        return None
    return Piece("circle", ((cx, cy), r), worst, m)


def _turn(a, b, c):
    d1x, d1y = b[0] - a[0], b[1] - a[1]
    d2x, d2y = c[0] - b[0], c[1] - b[1]
    return abs(math.atan2(d1x * d2y - d1y * d2x, d1x * d2x + d1y * d2y))


def _corners(pts, closed, corner, span):
    """Indices of the corner vertices, in order: a vertex turning by more than `corner` where the
    turn persists, measured between the points `span` back and ahead along the chain (so a
    staircase or noise finer than the tolerance is no corner), one per cluster (the sharpest)"""
    m = len(pts)
    if closed:

        def at(k):
            return pts[k % m]

        lo, hi = 0, m
    else:

        def at(k):
            return pts[k]

        lo, hi = 1, m - 1

    def reach(k, step):
        j = k
        dist = 0.0
        while True:
            nj = j + step
            if not closed and (nj < 0 or nj > m - 1):
                return at(j)
            if closed and abs(nj - k) >= m:
                return at(j)
            q, r = at(j), at(nj)
            dist += math.hypot(r[0] - q[0], r[1] - q[1])
            j = nj
            if dist >= span:
                return r

    def along(k0, k1):
        """Length along the chain from vertex k0 forward to k1, stopping at span"""
        gap = 0.0
        for j in range(k0, k1):
            q, r = at(j), at(j + 1)
            gap += math.hypot(r[0] - q[0], r[1] - q[1])
            if gap >= span:
                break
        return gap

    raw = []
    for k in range(lo, hi):
        t = _turn(at(k - 1), at(k), at(k + 1))
        if t <= corner:
            continue
        if _turn(reach(k, -1), at(k), reach(k, 1)) > corner:
            raw.append((k, t))
    # one per cluster: candidates closer than span along the chain keep the sharpest
    out = []
    for k, t in raw:
        if out and along(out[-1][0], k) < span:
            if t > out[-1][1]:
                out[-1] = (k, t)
            continue
        out.append((k, t))
    if closed and len(out) > 1 and along(out[-1][0], out[0][0] + m) < span:
        # the last and the first are one cluster across the seam
        if out[-1][1] > out[0][1]:
            out[0] = out[-1]
        out.pop()
        out.sort()
    return [k for k, _ in out]


def fit_chain(pts, closed, tol, corner_deg, breaks=()):
    """Pieces for a chain of points (closed: pts[-1] is pts[0]); breaks: points that must be the
    ends of pieces (where a gap was joined)"""
    breaks = set(breaks)
    # drop repeated points
    clean = [pts[0]]
    for p in pts[1:]:
        q = clean[-1]
        if p[0] != q[0] or p[1] != q[1]:
            clean.append(p)
    pts = clean
    if len(pts) < 2:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    rmax = 1.0e3 * max(max(xs) - min(xs), max(ys) - min(ys), tol)
    corner = math.radians(corner_deg)
    n = len(pts)
    if closed:
        ring = pts[:-1]
        m = len(ring)
        if m < 3:
            return _fit_run(pts, tol, rmax)
        corners = _corners(ring, True, corner, 5.0 * tol)
        if breaks:
            corners = sorted(set(corners) | {k for k in range(m) if ring[k] in breaks})
        if not corners:
            whole = _full_circle(ring, tol)
            if whole is not None:
                return [whole]

            def seglen(k):
                a, b = ring[k], ring[(k + 1) % m]
                return math.hypot(b[0] - a[0], b[1] - a[1])

            # two halves, so that no run closes on itself; the seams at the starts of the longest
            # segments (where a straight side begins), so that an arc isn't cut in two
            k0 = max(range(m), key=seglen)
            rot = ring[k0:] + ring[:k0] + [ring[k0]]
            h = max(range(m // 4, max(m // 4 + 1, 3 * m // 4)), key=lambda k: seglen((k0 + k) % m))
            return _fit_run(rot[: h + 1], tol, rmax) + _fit_run(rot[h:], tol, rmax)
        k0 = corners[0]
        rot = ring[k0:] + ring[:k0] + [ring[k0]]
        cut = [k - k0 if k >= k0 else k - k0 + m for k in corners] + [m]
        out = []
        for a, b in zip(cut, cut[1:]):
            out += _fit_run(rot[a : b + 1], tol, rmax)
        return out
    inner = set(_corners(pts, False, corner, 5.0 * tol))
    inner |= {k for k in range(1, n - 1) if pts[k] in breaks}
    cut = [0] + sorted(inner) + [n - 1]
    out = []
    for a, b in zip(cut, cut[1:]):
        out += _fit_run(pts[a : b + 1], tol, rmax)
    return out
