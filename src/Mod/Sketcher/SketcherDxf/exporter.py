# SPDX-License-Identifier: LGPL-2.1-or-later
"""DXF out of a planar face or a sketch (FreeCAD-CH), for laser cutting.

The file is an AutoCAD R12 DXF (AC1009: what every cutter's software reads) in millimetres
($INSUNITS 4, $MEASUREMENT 1), at 1:1, of LINE, ARC and CIRCLE entities: arcs and circles stay
true arcs. Curves that are neither (ellipses, splines) are written as arcs through their own points
within `tolerance` millimetres, the largest deviation measured and reported. With `polylines`,
each closed loop of lines and arcs is one closed POLYLINE with bulges instead (still true arcs).

- `export_face(face, path)`: the face's outer and inner loops, in the face's plane seen from
  outside the solid (its normal toward the viewer). In-plane axes: the world X when the face
  faces up or down, else the horizontal direction with the world Z up; the origin is the world
  origin's projection onto the plane.
- `export_sketch(sketch, path)`: the sketch's geometry that isn't construction, in the sketch's
  own coordinates.
- `export_selection(obj, sub, path)`: a sketch (sub empty) or a planar face (sub "FaceN").
"""

import math

import FreeCAD
import Part

V = FreeCAD.Vector

DEFAULT_TOLERANCE = 0.01  # mm


class ExportError(Exception):
    pass


class ExportReport:
    def __init__(self):
        self.entities = {"LINE": 0, "ARC": 0, "CIRCLE": 0, "POLYLINE": 0}
        self.loops = 0
        self.closed_loops = 0
        self.approximated = 0  # edges that were neither lines nor arcs
        self.max_deviation = 0.0
        self.tolerance = None
        self.path = None
        self.size = (0.0, 0.0)

    def lines(self):
        ents = ", ".join(f"{n} {k}" for k, n in self.entities.items() if n)
        out = [f"{self.path}: {ents}; {self.loops} loops ({self.closed_loops} closed), millimetres"]
        out.append(f"Extent {self.size[0]:.4g} x {self.size[1]:.4g} mm")
        if self.approximated:
            out.append(
                f"{self.approximated} curves written as arcs within {self.tolerance:g} mm "
                f"(largest deviation {self.max_deviation:.3g} mm)"
            )
        return out

    def __str__(self):
        return "\n".join(self.lines())


# ---------------------------------------------------------------------------------------------
# edges -> segments: ("L", p, q) or ("A", p, q, center, radius, sweep) with sweep the signed
# included angle (counterclockwise positive), or ("C", center, radius) for a whole circle


def _circle3(a, b, c):
    bx, by = b[0] - a[0], b[1] - a[1]
    cx, cy = c[0] - a[0], c[1] - a[1]
    d = 2.0 * (bx * cy - by * cx)
    if abs(d) < 1e-300:
        return None
    b2, c2 = bx * bx + by * by, cx * cx + cy * cy
    ux = (cy * b2 - by * c2) / d
    uy = (bx * c2 - cx * b2) / d
    return (a[0] + ux, a[1] + uy), math.hypot(ux, uy)


def _xy(v):
    return (v.x, v.y)


def _arc_segment(p, m, q):
    """("A", ...) through p, m, q; ("L", p, q) if they are collinear"""
    cr = _circle3(p, m, q)
    if cr is None:
        return ("L", p, q)
    c, r = cr
    a0 = math.atan2(p[1] - c[1], p[0] - c[0])
    am = math.atan2(m[1] - c[1], m[0] - c[0])
    a1 = math.atan2(q[1] - c[1], q[0] - c[0])
    ccw = ((m[0] - p[0]) * (q[1] - m[1]) - (m[1] - p[1]) * (q[0] - m[0])) > 0
    two = 2.0 * math.pi
    if ccw:
        sweep = (a1 - a0) % two
    else:
        sweep = -((a0 - a1) % two)
    del am
    return ("A", p, q, c, r, sweep)


def _seg_dev(seg, pt):
    if seg[0] == "L":
        p, q = seg[1], seg[2]
        dx, dy = q[0] - p[0], q[1] - p[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((pt[0] - p[0]) * dx + (pt[1] - p[1]) * dy) / L2))
        return math.hypot(pt[0] - p[0] - t * dx, pt[1] - p[1] - t * dy)
    c, r = seg[3], seg[4]
    return abs(math.hypot(pt[0] - c[0], pt[1] - c[1]) - r)


SAMPLES = 32  # points of the curve checked against each arc (each lies within one knot span)


def _knots(edge, f, l):
    """The curve's knots inside (f, l), a periodic curve's in every period the range covers"""
    c = edge.Curve
    if not hasattr(c, "getKnots"):
        return []
    try:
        ks = c.getKnots()
    except Exception:
        return []
    shifts = [0.0]
    if c.isPeriodic():
        period = c.LastParameter - c.FirstParameter
        n0 = int(math.floor((f - ks[-1]) / period)) - 1
        n1 = int(math.ceil((l - ks[0]) / period)) + 1
        shifts = [n * period for n in range(n0, n1 + 1)]
    return sorted({k + d for k in ks for d in shifts if f < k + d < l})


def _spans(edge, f, l):
    """[f, l] in four for a closed curve (each arc under a half turn), else whole"""
    if edge.isClosed():
        cuts = [f + (l - f) * k / 4.0 for k in range(5)]
        return list(zip(cuts, cuts[1:]))
    return [(f, l)]


def _samples(knots, f, l):
    """Parameters at which a piece from f to l is checked: SAMPLES evenly, and a quarter, half and
    three quarters of every knot span that meets the piece, so that a feature of the curve as
    narrow as one span can't fall between them unseen"""
    out = [f + (l - f) * k / SAMPLES for k in range(1, SAMPLES)]
    cuts = [f] + [k for k in knots if f < k < l] + [l]
    if len(cuts) > 2:
        for a, b in zip(cuts, cuts[1:]):
            out += [a + (b - a) * 0.25, a + (b - a) * 0.5, a + (b - a) * 0.75]
    return out


def _approximate(edge, f, l, tol, knots=(), depth=0):
    """Arcs through the edge's own points from parameter f to l, within tol: [(segment, dev)]"""
    p = _xy(edge.valueAt(f))
    m = _xy(edge.valueAt(0.5 * (f + l)))
    q = _xy(edge.valueAt(l))
    seg = _arc_segment(p, m, q)
    dev = 0.0
    for t in _samples(knots, f, l):
        dev = max(dev, _seg_dev(seg, _xy(edge.valueAt(t))))
    if seg[0] == "A" and abs(seg[5]) > math.pi:
        dev = max(dev, tol * 2.0)  # split arcs over a half turn: better conditioned
    if dev <= tol or depth > 30:
        return [(seg, dev)]
    h = 0.5 * (f + l)
    return _approximate(edge, f, h, tol, knots, depth + 1) + _approximate(edge, h, l, tol, knots, depth + 1)


def _edge_segments(edge, forward, tol, rep):
    """Segments of the edge in its traversal direction (forward: along its parameter)"""
    c = edge.Curve
    f, l = edge.FirstParameter, edge.LastParameter
    if isinstance(c, (Part.Line, Part.LineSegment)):
        p, q = _xy(edge.valueAt(f)), _xy(edge.valueAt(l))
        return [("L", p, q) if forward else ("L", q, p)]
    if isinstance(c, Part.Circle):
        ctr = _xy(c.Center)
        r = c.Radius
        if edge.isClosed() and abs((l - f) - 2.0 * math.pi) < 1e-9:
            return [("C", ctr, r)]
        sgn = 1.0 if c.Axis.z > 0 else -1.0
        sweep = sgn * (l - f)
        p, q = _xy(edge.valueAt(f)), _xy(edge.valueAt(l))
        if forward:
            return [("A", p, q, ctr, r, sweep)]
        return [("A", q, p, ctr, r, -sweep)]
    rep.approximated += 1
    parts = []
    knots = _knots(edge, f, l)
    for a, b in _spans(edge, f, l):
        parts += _approximate(edge, a, b, tol, knots)
    for _, d in parts:
        rep.max_deviation = max(rep.max_deviation, d)
    segs = [s for s, _ in parts]
    if forward:
        return segs
    out = []
    for s in reversed(segs):
        if s[0] == "L":
            out.append(("L", s[2], s[1]))
        else:
            out.append(("A", s[2], s[1], s[3], s[4], -s[5]))
    return out


def _wire_segments(wire, tol, rep):
    """Segments of the wire in loop order"""
    edges = wire.OrderedEdges
    verts = wire.OrderedVertexes
    out = []
    for k, e in enumerate(edges):
        start = verts[k].Point if k < len(verts) else None
        fwd = True
        if start is not None:
            fwd = (e.valueAt(e.FirstParameter) - start).Length <= (e.valueAt(e.LastParameter) - start).Length
        out += _edge_segments(e, fwd, tol, rep)
    return out


# ---------------------------------------------------------------------------------------------
# the R12 file


def _num(x):
    if abs(x) < 1e-13:
        x = 0.0
    return repr(float(round(x, 12)))


class _Writer:
    def __init__(self):
        self.out = []
        self.xmin = self.ymin = math.inf
        self.xmax = self.ymax = -math.inf

    def g(self, code, value):
        self.out.append(f"{code:>3}\n{value}\n")

    def ext(self, p, r=0.0):
        self.xmin = min(self.xmin, p[0] - r)
        self.ymin = min(self.ymin, p[1] - r)
        self.xmax = max(self.xmax, p[0] + r)
        self.ymax = max(self.ymax, p[1] + r)

    def ext_arc(self, s):
        """The tight extent of an arc segment: its ends and the quarter points it passes"""
        _, p, q, c, r, sweep = s
        self.ext(p)
        self.ext(q)
        a0 = math.atan2(p[1] - c[1], p[0] - c[0])
        if sweep < 0:
            a0, sweep = a0 + sweep, -sweep
        for k in range(4):
            a = k * math.pi / 2.0
            if (a - a0) % (2.0 * math.pi) <= sweep:
                self.ext((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))

    def pt(self, code, p):
        self.g(code, _num(p[0]))
        self.g(code + 10, _num(p[1]))
        self.g(code + 20, "0.0")

    def segment(self, s, rep):
        if s[0] == "L":
            self.g(0, "LINE")
            self.g(8, "0")
            self.pt(10, s[1])
            self.pt(11, s[2])
            self.ext(s[1])
            self.ext(s[2])
            rep.entities["LINE"] += 1
        elif s[0] == "C":
            self.g(0, "CIRCLE")
            self.g(8, "0")
            self.pt(10, s[1])
            self.g(40, _num(s[2]))
            self.ext(s[1], s[2])
            rep.entities["CIRCLE"] += 1
        else:
            _, p, q, c, r, sweep = s
            a0 = math.degrees(math.atan2(p[1] - c[1], p[0] - c[0]))
            a1 = math.degrees(math.atan2(q[1] - c[1], q[0] - c[0]))
            if sweep < 0:
                a0, a1 = a1, a0  # DXF arcs run counterclockwise
            a0 %= 360.0
            a1 %= 360.0
            self.g(0, "ARC")
            self.g(8, "0")
            self.pt(10, c)
            self.g(40, _num(r))
            self.g(50, _num(a0))
            self.g(51, _num(a1))
            self.ext_arc(s)
            rep.entities["ARC"] += 1

    def polyline(self, segs, rep):
        self.g(0, "POLYLINE")
        self.g(8, "0")
        self.g(66, "1")
        self.pt(10, (0.0, 0.0))
        self.g(70, "1")
        for s in segs:
            p = s[1]
            bulge = 0.0 if s[0] == "L" else math.tan(s[5] / 4.0)
            self.g(0, "VERTEX")
            self.g(8, "0")
            self.pt(10, p)
            if bulge:
                self.g(42, _num(bulge))
            self.ext(p)
            if s[0] == "A":
                self.ext_arc(s)
        self.g(0, "SEQEND")
        self.g(8, "0")
        rep.entities["POLYLINE"] += 1

    def text(self):
        head = []

        def h(code, value):
            head.append(f"{code:>3}\n{value}\n")

        h(0, "SECTION")
        h(2, "HEADER")
        h(9, "$ACADVER")
        h(1, "AC1009")
        h(9, "$INSUNITS")
        h(70, "4")
        h(9, "$MEASUREMENT")
        h(70, "1")
        if self.xmin <= self.xmax:
            h(9, "$EXTMIN")
            h(10, _num(self.xmin))
            h(20, _num(self.ymin))
            h(30, "0.0")
            h(9, "$EXTMAX")
            h(10, _num(self.xmax))
            h(20, _num(self.ymax))
            h(30, "0.0")
        h(0, "ENDSEC")
        h(0, "SECTION")
        h(2, "ENTITIES")
        return "".join(head) + "".join(self.out) + "  0\nENDSEC\n  0\nEOF\n"


def _write(wires, path, tol, polylines):
    rep = ExportReport()
    rep.tolerance = tol
    rep.path = path
    w = _Writer()
    for wire in wires:
        rep.loops += 1
        segs = _wire_segments(wire, tol, rep)
        closed = wire.isClosed()
        if closed:
            rep.closed_loops += 1
        if polylines and closed and segs and all(s[0] != "C" for s in segs):
            w.polyline(segs, rep)
        else:
            for s in segs:
                w.segment(s, rep)
    if w.xmin <= w.xmax:
        rep.size = (w.xmax - w.xmin, w.ymax - w.ymin)
    with open(path, "w", encoding="ascii", newline="\r\n") as f:
        f.write(w.text())
    return rep


# ---------------------------------------------------------------------------------------------


def face_frame(face):
    """The placement whose XY plane is the face's, normal toward the outside (see the module)"""
    try:
        plane = face.Surface if isinstance(face.Surface, Part.Plane) else face.findPlane()
    except Exception:
        plane = None
    if plane is None:
        raise ExportError("the face is not planar")
    u0, u1, v0, v1 = face.ParameterRange
    n = face.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
    n.normalize()
    if abs(n.z) > 1.0 - 1e-9:
        x = V(1, 0, 0)
    else:
        x = V(0, 0, 1).cross(n)
    x = x - n * x.dot(n)
    x.normalize()
    y = n.cross(x)
    p0 = face.Vertexes[0].Point if face.Vertexes else plane.Position
    o = n * p0.dot(n)
    m = FreeCAD.Matrix(x.x, y.x, n.x, o.x, x.y, y.y, n.y, o.y, x.z, y.z, n.z, o.z, 0, 0, 0, 1)
    return m


def export_face(face, path, tolerance=DEFAULT_TOLERANCE, polylines=False):
    """The planar face's loops to a DXF at path; returns the ExportReport"""
    if not isinstance(face, Part.Face):
        raise ExportError("a face was expected")
    m = face_frame(face)
    local = face.copy()
    local.transformShape(m.inverse())
    bb = local.BoundBox
    if abs(bb.ZMax) > 1e-6 * max(1.0, bb.DiagonalLength) or abs(bb.ZMin) > 1e-6 * max(1.0, bb.DiagonalLength):
        raise ExportError("the face is not planar")
    wires = [local.OuterWire] + [w for w in local.Wires if not w.isSame(local.OuterWire)]
    return _write(wires, path, tolerance, polylines)


def export_sketch(sketch, path, tolerance=DEFAULT_TOLERANCE, polylines=False):
    """The sketch's non-construction geometry to a DXF at path, in sketch coordinates"""
    edges = []
    for i, g in enumerate(sketch.Geometry):
        if sketch.getConstruction(i) or isinstance(g, Part.Point):
            continue
        edges.append(g.toShape())
    if not edges:
        raise ExportError("the sketch has no geometry that isn't construction")
    wires = [Part.Wire(group) for group in Part.sortEdges(edges)]
    return _write(wires, path, tolerance, polylines)


def export_selection(obj, sub, path, tolerance=DEFAULT_TOLERANCE, polylines=False):
    """A sketch (sub empty or one of its own elements) or a planar face of a shape"""
    if obj.isDerivedFrom("Sketcher::SketchObject") and not (sub or "").startswith("Face"):
        return export_sketch(obj, path, tolerance, polylines)
    if not sub or not sub.split(".")[-1].startswith("Face"):
        raise ExportError("select a planar face or a sketch")
    face = obj.getSubObject(sub)
    if face is None or face.isNull():
        raise ExportError(f"{obj.Label} has no {sub}")
    return export_face(face, path, tolerance, polylines)
