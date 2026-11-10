# SPDX-License-Identifier: LGPL-2.1-or-later
"""DXF into a sketch (FreeCAD-CH): `insert(sketch, path, ...)`.

The file's model space lands in the sketch's plane, its origin on the sketch's origin and its X
and Y on the sketch's, at 1:1 in the file's units ($INSUNITS); a file without units needs
`units=` (the command asks). Blocks and layers are flattened; lines, arcs, circles, ellipses and
splines stay what they are. With `fit` (the default), chains of short segments become lines, arcs
and B-splines within `tolerance` millimetres (`fitting.py`), corners sharper than `corner` degrees
kept. The imported curves are held by one Block constraint each (`hold="block"`, the default) or
left free (`hold="free"`): the solver then has nothing of theirs to solve.
"""

import math
import time

import FreeCAD
import Part

from . import fitting, reader
from .reader import DxfError

V = FreeCAD.Vector

UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8, "um": 1e-3, "mil": 0.0254}

DEFAULT_TOLERANCE = 0.01  # mm
DEFAULT_CORNER = 30.0  # degrees


class DxfUnitsMissing(DxfError):
    """The file states no units, and none were given"""


class Report:
    def __init__(self):
        self.units = None  # e.g. "mm"
        self.units_from_file = False
        self.entities = 0  # curves read
        self.segments = 0  # line segments among them
        self.curves = 0  # geometries added to the sketch
        self.kinds = {}
        self.fit = False
        self.tolerance = None
        self.max_deviation = 0.0
        self.gaps_joined = 0
        self.ends_joined = 0
        self.open_ends = 0
        self.snap = None
        self.skipped = {}
        self.paperspace = 0
        self.projected = 0
        self.missing_blocks = []
        self.first_geo = None
        self.seconds = 0.0

    def lines(self):
        """The report in words, one finding a line"""
        out = [
            f"{self.entities} curves read ({self.segments} line segments), "
            f"{self.curves} sketch curves added: "
            + ", ".join(f"{n} {k}" for k, n in sorted(self.kinds.items()) if n)
        ]
        src = "from the file" if self.units_from_file else "chosen (the file states none)"
        out.append(f"Units: {self.units}, {src}")
        if self.fit:
            out.append(
                f"Fitted within {self.tolerance:g} mm: largest deviation {self.max_deviation:.4g} mm"
            )
        if self.gaps_joined:
            out.append(f"{self.gaps_joined} gaps under the tolerance closed")
        if self.ends_joined:
            out.append(f"{self.ends_joined} curve ends moved to meet another (under {self.snap:g} mm)")
        if self.open_ends:
            out.append(f"{self.open_ends} curve ends meet no other curve: an outline is open")
        else:
            out.append("Every curve end meets another: the outlines are closed")
        if self.projected:
            out.append(f"{self.projected} entities outside the XY plane projected onto it")
        if self.paperspace:
            out.append(f"{self.paperspace} paper-space entities not imported")
        for k, n in sorted(self.skipped.items()):
            out.append(f"{n} {k} not imported")
        if self.missing_blocks:
            out.append("Blocks missing from the file: " + ", ".join(sorted(map(str, self.missing_blocks))))
        return out

    def __str__(self):
        return "\n".join(self.lines())


def _scale(items, k):
    if k == 1.0:
        return items

    def s(p):
        return (p[0] * k, p[1] * k)

    out = []
    for it in items:
        if isinstance(it, reader.Line):
            out.append(reader.Line(s(it.p), s(it.q)))
        elif isinstance(it, reader.Conic):
            out.append(reader.Conic(s(it.c), s(it.u), s(it.v), it.t0, it.t1, it.full))
        elif isinstance(it, reader.Spline):
            out.append(reader.Spline(it.degree, [s(p) for p in it.poles], it.knots, it.weights))
        elif isinstance(it, reader.FitSpline):
            out.append(reader.FitSpline([s(p) for p in it.points]))
        elif isinstance(it, reader.Point):
            out.append(reader.Point(s(it.p)))
    return out


# ---------------------------------------------------------------------------------------------
# items -> Part geometry (sketch coordinates)


def _arc_ccw(center, r, a0, a1):
    """The arc of the circle (center, r) counterclockwise from angle a0 to a1"""
    while a1 <= a0:
        a1 += 2.0 * math.pi
    circ = Part.Circle(V(center[0], center[1], 0), V(0, 0, 1), r)
    return Part.ArcOfCircle(circ, a0, a1)


def conic_geometry(it):
    """A Conic as Part.Circle / ArcOfCircle / Ellipse / ArcOfEllipse, counterclockwise about +Z"""
    c, u, v, t0, t1 = it.c, it.u, it.v, it.t0, it.t1
    cross = u[0] * v[1] - u[1] * v[0]
    if abs(cross) < 1e-300:
        return None  # degenerate (a conic squashed to a line by a projection)
    if cross < 0:
        v = (-v[0], -v[1])
        t0, t1 = -t1, -t0
    uu = u[0] * u[0] + u[1] * u[1]
    vv = v[0] * v[0] + v[1] * v[1]
    uv = u[0] * v[0] + u[1] * v[1]
    s = 0.5 * math.atan2(2.0 * uv, uu - vv)
    cs, sn = math.cos(s), math.sin(s)
    a = (u[0] * cs + v[0] * sn, u[1] * cs + v[1] * sn)  # major semi-axis
    b = (-u[0] * sn + v[0] * cs, -u[1] * sn + v[1] * cs)  # minor
    t0, t1 = t0 - s, t1 - s
    ra, rb = math.hypot(*a), math.hypot(*b)
    if abs(ra - rb) <= 1e-9 * ra:
        r = 0.5 * (ra + rb)
        phi = math.atan2(a[1], a[0])
        if it.full:
            return Part.Circle(V(c[0], c[1], 0), V(0, 0, 1), r)
        return _arc_ccw(c, r, phi + t0, phi + t1)
    if rb > ra:  # cannot happen after the choice of s, kept for safety
        a, b, ra, rb = b, (-a[0], -a[1]), rb, ra
        t0, t1 = t0 - math.pi / 2, t1 - math.pi / 2
    C = V(c[0], c[1], 0)
    ell = Part.Ellipse(C + V(a[0], a[1], 0), C + V(b[0], b[1], 0), C)
    if it.full:
        return ell
    return Part.ArcOfEllipse(ell, t0, t1)


def spline_geometry(it):
    if isinstance(it, reader.FitSpline):
        pts = [V(p[0], p[1], 0) for p in it.points]
        c = Part.BSplineCurve()
        c.interpolate(pts)
        return c
    flat = it.knots
    knots, mults = [], []
    for k in flat:
        if knots and abs(k - knots[-1]) <= 1e-12 * (1.0 + abs(k)):
            mults[-1] += 1
        else:
            knots.append(k)
            mults.append(1)
    deg = it.degree
    # OCCT allows at most degree+1 at the ends and degree inside
    mults = [min(m, deg + 1) if i in (0, len(mults) - 1) else min(m, deg) for i, m in enumerate(mults)]
    poles = [V(p[0], p[1], 0) for p in it.poles]
    if sum(mults) != len(poles) + deg + 1:
        raise DxfError("a SPLINE whose knots don't match its control points")
    c = Part.BSplineCurve()
    if it.weights:
        c.buildFromPolesMultsKnots(poles, mults, knots, False, deg, it.weights)
    else:
        c.buildFromPolesMultsKnots(poles, mults, knots, False, deg)
    if mults[0] < deg + 1 or mults[-1] < deg + 1:
        # an unclamped spline: clamped at its own domain, the same curve
        c.segment(c.FirstParameter, c.LastParameter)
    return c


def piece_geometry(pc):
    if pc.kind == "line":
        p, q = pc.pts
        return Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
    if pc.kind == "arc":
        p, m, q = pc.pts
        cr = fitting._circle3(p, m, q)
        (cx, cy), r = cr
        orient = (m[0] - p[0]) * (q[1] - m[1]) - (m[1] - p[1]) * (q[0] - m[0])
        ap = math.atan2(p[1] - cy, p[0] - cx)
        aq = math.atan2(q[1] - cy, q[0] - cx)
        if orient > 0:
            return _arc_ccw((cx, cy), r, ap, aq)
        return _arc_ccw((cx, cy), r, aq, ap)
    if pc.kind == "circle":
        (cx, cy), r = pc.pts
        return Part.Circle(V(cx, cy, 0), V(0, 0, 1), r)
    return pc.curve


def _kind(g):
    return {
        "Part::GeomLineSegment": "lines",
        "Part::GeomArcOfCircle": "arcs",
        "Part::GeomCircle": "circles",
        "Part::GeomEllipse": "ellipses",
        "Part::GeomArcOfEllipse": "elliptical arcs",
        "Part::GeomBSplineCurve": "splines",
        "Part::GeomPoint": "points",
    }.get(g.TypeId, g.TypeId)


def geometry(drawing, mm_per_unit, fit=True, tolerance=DEFAULT_TOLERANCE, corner=DEFAULT_CORNER, report=None):
    """Part geometries for the drawing's items, in millimetres, and the report"""
    rep = report or Report()
    items = _scale(drawing.items, mm_per_unit)
    geos = []
    segs = []
    other_ends = []
    for it in items:
        if isinstance(it, reader.Line):
            if it.p != it.q:
                segs.append((it.p, it.q))
            continue
        if isinstance(it, reader.Conic):
            g = conic_geometry(it)
            if g is None:
                rep.skipped["degenerate ellipse"] = rep.skipped.get("degenerate ellipse", 0) + 1
                continue
        elif isinstance(it, (reader.Spline, reader.FitSpline)):
            try:
                g = spline_geometry(it)
            except Exception:
                rep.skipped["SPLINE that can't be built"] = rep.skipped.get("SPLINE that can't be built", 0) + 1
                continue
        elif isinstance(it, reader.Point):
            g = Part.Point(V(it.p[0], it.p[1], 0))
        else:
            continue
        geos.append(g)
        if not isinstance(g, (Part.Point, Part.Circle, Part.Ellipse)):
            sp, ep = g.StartPoint, g.EndPoint
            other_ends.append((sp.x, sp.y))
            other_ends.append((ep.x, ep.y))
    rep.entities = len(drawing.items)
    rep.segments = len(segs)
    if fit and segs:
        rep.fit = True
        rep.tolerance = tolerance
        join = max(1e-6, tolerance * 1e-3)
        # gaps under half the tolerance are joined, and their chains fitted within the other
        # half: a point of an original segment is then within (gap + the fit's deviation) of the
        # result, which is what the report says
        chains, joined, widest = fitting.chains(segs, other_ends, join, 0.5 * tolerance)
        rep.gaps_joined = joined
        fitted = []
        for pts, closed, joins in chains:
            breaks = [j[0] for j in joins]
            gap = max((math.hypot(j[0][0] - j[1][0], j[0][1] - j[1][1]) for j in joins), default=0.0)
            t = tolerance - gap if joins else tolerance
            pieces = fitting.fit_chain(pts, closed, t, corner, breaks)
            fitted.append([pts, closed, pieces, t, breaks, gap])
        _keep_clearance(fitted, [g.toShape() for g in geos if not isinstance(g, Part.Point)], corner)
        for pts, closed, pieces, t, breaks, gap in fitted:
            dev = max((pc.dev for pc in pieces), default=0.0)
            rep.max_deviation = max(rep.max_deviation, dev + gap)
            for pc in pieces:
                geos.append(piece_geometry(pc))
    else:
        for p, q in segs:
            geos.append(Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0)))
    # curve ends that miss each other by less than the snap distance meet (a writer's rounding
    # of LINE and ARC ends: 6 decimals of a rotated drawing miss by about 1e-7)
    snap = min(tolerance, SNAP) if tolerance else SNAP
    geos, rep.ends_joined, moved, rep.open_ends = snap_ends(geos, snap)
    rep.max_deviation = max(rep.max_deviation, moved)
    rep.snap = snap
    for g in geos:
        k = _kind(g)
        rep.kinds[k] = rep.kinds.get(k, 0) + 1
    rep.curves = len(geos)
    return geos, rep


SNAP = 0.001  # mm: the most a curve's end is moved to meet another's


def _ends(g):
    if isinstance(g, (Part.Point, Part.Circle, Part.Ellipse)):
        return None
    if isinstance(g, Part.BSplineCurve) and g.isClosed():
        return None
    return g.StartPoint, g.EndPoint


_RANK = {
    "Part::GeomArcOfEllipse": 0,
    "Part::GeomArcOfCircle": 1,
    "Part::GeomBSplineCurve": 2,
    "Part::GeomLineSegment": 3,
}


def _moved(g, start, end):
    """g with its ends at start and end (vectors), or None if it can't be"""
    if isinstance(g, Part.LineSegment):
        if (end - start).Length == 0.0:
            return None
        return Part.LineSegment(start, end)
    if isinstance(g, Part.ArcOfCircle):
        m = g.value(0.5 * (g.FirstParameter + g.LastParameter))
        pc = fitting.Piece("arc", ((start.x, start.y), (m.x, m.y), (end.x, end.y)), 0.0, 0)
        if fitting._circle3(*pc.pts) is None:
            return None
        return piece_geometry(pc)
    if isinstance(g, Part.BSplineCurve) and not g.isPeriodic():
        mults = g.getMultiplicities()
        if mults[0] != g.Degree + 1 or mults[-1] != g.Degree + 1:
            return None
        c = g.copy()
        c.setPole(1, start)
        c.setPole(c.NbPoles, end)
        return c
    return None


def snap_ends(geos, snap):
    """Curve ends within snap of each other moved to one point: (geometries, ends moved, the
    largest move, ends that meet no other). The point is an end of the curve least able to move
    (an elliptical arc, then an arc, a spline, a line)."""
    ends = []  # (geo index, 0 start / 1 end, point)
    for i, g in enumerate(geos):
        e = _ends(g)
        if e is not None:
            ends.append((i, 0, e[0]))
            ends.append((i, 1, e[1]))
    if not ends:
        return geos, 0, 0.0, 0
    parent = list(range(len(ends)))

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    cell = max(snap, 1e-12)
    grid = {}
    for k, (_, _, p) in enumerate(ends):
        grid.setdefault((math.floor(p.x / cell), math.floor(p.y / cell)), []).append(k)
    for k, (_, _, p) in enumerate(ends):
        kx, ky = math.floor(p.x / cell), math.floor(p.y / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for o in grid.get((kx + dx, ky + dy), ()):
                    if o > k and (ends[o][2] - p).Length <= snap:
                        ra, rb = root(k), root(o)
                        if ra != rb:
                            parent[ra] = rb
    clusters = {}
    for k in range(len(ends)):
        clusters.setdefault(root(k), []).append(k)
    target = {}  # (geo, which) -> new point
    groups = []  # (members, target point) of the clusters of two or more ends
    open_ends = 0
    for members in clusters.values():
        if len(members) == 1:
            open_ends += 1
            continue
        best = min(members, key=lambda k: (_RANK.get(geos[ends[k][0]].TypeId, 9), k))
        tp = ends[best][2]
        groups.append((members, tp))
        for k in members:
            i, w, p = ends[k]
            if (p - tp).Length > 0.0:
                target[(i, w)] = tp
    out = list(geos)
    moved, largest = 0, 0.0
    for i in sorted(set(i for i, _ in target)):
        g = geos[i]
        s, e = _ends(g)
        ns, ne = target.get((i, 0), s), target.get((i, 1), e)
        ng = _moved(g, ns, ne)
        if ng is None:
            continue
        out[i] = ng
        for old, new in ((s, ns), (e, ne)):
            d = (new - old).Length
            if d > 1e-9:  # not the 1e-15 of an arc's ends computed from its angles
                moved += 1
                largest = max(largest, d)
    # an end that could not move (an elliptical arc's) still misses: it and, if nothing else met
    # it, the target end are open
    for members, tp in groups:
        missed = 0
        for k in members:
            i, w, _ = ends[k]
            if (_ends(out[i])[w] - tp).Length > 1e-9:
                missed += 1
        if missed:
            open_ends += missed + (1 if missed == len(members) - 1 else 0)
    return out, moved, largest, open_ends


def _keep_clearance(fitted, fixed, corner):
    """Refits chains whose fit changed how they meet their neighbours (a fitted chain against
    another, or against a curve of the file):
    - outlines apart by d >= SNAP that the fit brought closer than d / 2: the fitted ones refitted
      within d / 4, which keeps at least d / 2 whatever the fit (each stays within its tolerance);
    - outlines that touch or cross (d < SNAP): refitted once within a quarter of their tolerance
      when the fitted pair meets at a point farther than ten tolerances from every point where the
      original pair meets and from the chains' ends (a crossing the drawing already has moves by
      about the deviation over the crossing's sine; where a chain meets a tangent arc, the fit may
      cross it near the junction: both are kept as they are).
    Chains the fit left as their own segments are skipped. fitted: [[pts, closed, pieces, tol,
    breaks, gap]]; fixed: shapes of the file's other curves."""
    nf = len(fitted)
    if nf == 0 or nf + len(fixed) < 2:
        return

    def changed(k):
        return k < nf and any(pc.count > 1 or pc.kind != "line" for pc in fitted[k][2])

    live = [k for k in range(nf) if changed(k)]
    if not live:
        return

    def bbox_pts(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def fit_shape(k):
        if k < nf:
            return Part.Compound([piece_geometry(pc).toShape() for pc in fitted[k][2]])
        return fixed[k - nf]

    def raw(k):
        if k < nf:
            return Part.makePolygon([V(p[0], p[1], 0) for p in fitted[k][0]])
        return fixed[k - nf]

    boxes = [bbox_pts(f[0]) for f in fitted]
    for sh in fixed:
        bb = sh.BoundBox
        boxes.append((bb.XMin, bb.YMin, bb.XMax, bb.YMax))
    grow = 2.0 * max(f[3] for f in fitted)
    order = sorted(range(len(boxes)), key=lambda k: boxes[k][0])
    pairs = []
    active = []
    for k in order:
        x0 = boxes[k][0]
        active = [o for o in active if boxes[o][2] + grow >= x0]
        for o in active:
            if (changed(o) or changed(k)) and boxes[o][1] <= boxes[k][3] + grow and boxes[k][1] <= boxes[o][3] + grow:
                pairs.append((min(o, k), max(o, k)))
        active.append(k)

    def refit(k, t):
        pts, closed, _, tol, breaks, gap = fitted[k]
        if t >= tol:
            return
        fitted[k][2] = fitting.fit_chain(pts, closed, t, corner, breaks) if t > 1e-9 else [
            fitting.Piece("line", (pts[j], pts[j + 1]), 0.0, 1) for j in range(len(pts) - 1)
        ]
        fitted[k][3] = t

    def chain_ends(k):
        if k >= nf or fitted[k][1]:
            return []
        a, b = fitted[k][0][0], fitted[k][0][-1]
        return [V(a[0], a[1], 0), V(b[0], b[1], 0)]

    retried = set()
    for a, b in pairs:
        ta = fitted[a][3] if a < nf else 0.0
        tb = fitted[b][3] if b < nf else 0.0
        wa, wb = fit_shape(a), fit_shape(b)
        df = wa.distToShape(wb)[0]
        if df >= ta + tb:
            continue  # farther apart than both deviations: the fit can't have made them meet
        ra, rb = raw(a), raw(b)
        draw = ra.distToShape(rb)[0]
        if draw >= SNAP:
            if df < 0.5 * draw:
                for k in (a, b):
                    if k < nf:
                        refit(k, 0.25 * draw)
            continue
        if (a, b) in retried:
            continue
        old = [v.Point for v in ra.section(rb).Vertexes] + chain_ends(a) + chain_ends(b)
        reach = 10.0 * max(ta, tb)
        new = [v.Point for v in wa.section(wb).Vertexes]
        if all(any((p - q).Length <= reach for q in old) for p in new):
            continue
        retried.add((a, b))
        for k in (a, b):
            if k < nf:
                refit(k, 0.25 * fitted[k][3])


def resolve_units(drawing, units=None):
    """(mm per unit, name, from the file); units overrides the file's"""
    if units is not None:
        if isinstance(units, str):
            if units not in UNITS:
                raise DxfError(f"unknown units {units!r}: one of {', '.join(UNITS)}")
            return UNITS[units], units, False
        return float(units), f"{float(units):g} mm", False
    k = drawing.mm_per_unit
    if k is None:
        raise DxfUnitsMissing("the file states no units ($INSUNITS): choose them")
    return k, reader.UNIT_NAMES.get(drawing.insunits, f"code {drawing.insunits}"), True


def insert(sketch, path, units=None, fit=True, tolerance=DEFAULT_TOLERANCE, corner=DEFAULT_CORNER, hold="block"):
    """Insert the DXF at path into the sketch; returns the Report.

    units: None for the file's; "mm", "in", ... or millimetres per unit to choose them.
    hold: "block" (one Block constraint per curve) or "free"."""
    if hold not in ("block", "free"):
        raise ValueError(f"hold must be 'block' or 'free', not {hold!r}")
    t = time.perf_counter()
    drawing = reader.read(path)
    k, name, from_file = resolve_units(drawing, units)
    rep = Report()
    rep.units, rep.units_from_file = name, from_file
    rep.skipped = dict(drawing.skipped)
    rep.paperspace = drawing.paperspace
    rep.projected = drawing.projected
    rep.missing_blocks = sorted(drawing.missing_blocks, key=str)
    geos, rep = geometry(drawing, k, fit, tolerance, corner, rep)
    if geos:
        first = sketch.GeometryCount
        sketch.addGeometry(geos, False)
        rep.first_geo = first
        if hold == "block":
            sketch.addConstraint(
                [_sketcher().Constraint("Block", i) for i in range(first, first + len(geos))]
            )
    rep.seconds = time.perf_counter() - t
    return rep


def _sketcher():
    import Sketcher

    return Sketcher
