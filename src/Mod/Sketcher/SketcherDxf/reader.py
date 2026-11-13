# SPDX-License-Identifier: LGPL-2.1-or-later
"""A DXF reader for sketch import (FreeCAD-CH): the model space flattened into 2D curves.

Pure Python, no FreeCAD import: `read(path)` returns a `Drawing` whose `items` are curves in the
file's units, in the XY plane of the world coordinate system:
- `Line(p, q)`;
- `Conic(c, u, v, t0, t1, full)`: the points c + u cos t + v sin t for t from t0 to t1, which is
  an arc, a circle or an ellipse (u and v need not be perpendicular: an affine map of a conic is
  this form again, so blocks with any scale, mirror or rotation stay exact);
- `Spline(degree, poles, knots, weights)` (knots as the full flat vector) or `FitSpline(points)`;
- `Point(p)`.
Blocks are expanded (nested, mirrored, rotated, scaled, arrayed); layers are flattened. Entities
outside the XY plane are projected onto it, which is exact for every kind here (a parallel
projection maps a conic to a conic and a spline's poles to its poles). What is not geometry
(text, dimensions, hatches, images) is counted in `skipped` and not imported.
"""

import math
import re

# $INSUNITS codes -> millimetres per unit (0 = unitless: none)
INSUNITS_MM = {
    1: 25.4,  # inches
    2: 304.8,  # feet
    3: 1609344.0,  # miles
    4: 1.0,  # millimetres
    5: 10.0,  # centimetres
    6: 1000.0,  # metres
    7: 1.0e6,  # kilometres
    8: 25.4e-6,  # microinches
    9: 0.0254,  # mils
    10: 914.4,  # yards
    11: 1.0e-7,  # angstroms
    12: 1.0e-6,  # nanometres
    13: 1.0e-3,  # microns
    14: 100.0,  # decimetres
    15: 1.0e4,  # decametres
    16: 1.0e5,  # hectometres
    17: 1.0e12,  # gigametres
}
UNIT_NAMES = {1: "in", 2: "ft", 4: "mm", 5: "cm", 6: "m", 9: "mil", 10: "yd", 13: "um", 14: "dm"}


class DxfError(Exception):
    """A file this reader can't read (binary DXF, DWG, a broken group structure)."""


class Line:
    __slots__ = ("p", "q")

    def __init__(self, p, q):
        self.p, self.q = p, q


class Conic:
    __slots__ = ("c", "u", "v", "t0", "t1", "full")

    def __init__(self, c, u, v, t0, t1, full):
        self.c, self.u, self.v, self.t0, self.t1, self.full = c, u, v, t0, t1, full

    def at(self, t):
        ct, st = math.cos(t), math.sin(t)
        return (self.c[0] + self.u[0] * ct + self.v[0] * st, self.c[1] + self.u[1] * ct + self.v[1] * st)


class Spline:
    __slots__ = ("degree", "poles", "knots", "weights")

    def __init__(self, degree, poles, knots, weights):
        self.degree, self.poles, self.knots, self.weights = degree, poles, knots, weights


class FitSpline:
    __slots__ = ("points",)

    def __init__(self, points):
        self.points = points


class Point:
    __slots__ = ("p",)

    def __init__(self, p):
        self.p = p


class Drawing:
    def __init__(self):
        self.items = []
        self.insunits = None  # the header's $INSUNITS, None when absent
        self.skipped = {}  # entity type -> count, of what is not imported
        self.paperspace = 0  # entities of a layout (paper space), not imported
        self.projected = 0  # entities not in the XY plane, projected onto it
        self.missing_blocks = set()
        self.version = None

    @property
    def mm_per_unit(self):
        return INSUNITS_MM.get(self.insunits) if self.insunits else None

    def skip(self, kind):
        self.skipped[kind] = self.skipped.get(kind, 0) + 1


# ---------------------------------------------------------------------------------------------
# 3D affine maps as 3x4 row-major tuples (rows: x, y, z), points as 3-tuples

IDENTITY = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))


def apply(m, p):
    x, y, z = p
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z + m[0][3],
        m[1][0] * x + m[1][1] * y + m[1][2] * z + m[1][3],
        m[2][0] * x + m[2][1] * y + m[2][2] * z + m[2][3],
    )


def apply_vec(m, v):
    x, y, z = v
    return (
        m[0][0] * x + m[0][1] * y + m[0][2] * z,
        m[1][0] * x + m[1][1] * y + m[1][2] * z,
        m[2][0] * x + m[2][1] * y + m[2][2] * z,
    )


def compose(a, b):
    """a after b"""
    rows = []
    for i in range(3):
        row = []
        for j in range(4):
            s = sum(a[i][k] * b[k][j] for k in range(3))
            if j == 3:
                s += a[i][3]
            row.append(s)
        rows.append(tuple(row))
    return tuple(rows)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])
    if n == 0.0:
        raise DxfError("a zero extrusion direction")
    return (a[0] / n, a[1] / n, a[2] / n)


def ocs_matrix(n):
    """The arbitrary axis algorithm: the map from an entity's object coordinates to the world's"""
    if n is None or (abs(n[0]) < 1e-12 and abs(n[1]) < 1e-12 and n[2] > 0):
        return IDENTITY
    n = _unit(n)
    if abs(n[0]) < 1.0 / 64.0 and abs(n[1]) < 1.0 / 64.0:
        ax = _unit(_cross((0.0, 1.0, 0.0), n))
    else:
        ax = _unit(_cross((0.0, 0.0, 1.0), n))
    ay = _unit(_cross(n, ax))
    return (
        (ax[0], ay[0], n[0], 0.0),
        (ax[1], ay[1], n[1], 0.0),
        (ax[2], ay[2], n[2], 0.0),
    )


# ---------------------------------------------------------------------------------------------
# group pairs


def _pairs(path):
    with open(path, "rb") as f:
        data = f.read()
    if data.startswith(b"AutoCAD Binary DXF"):
        raise DxfError("a binary DXF: save it as an ASCII DXF")
    if data.startswith(b"AC10") or data.startswith(b"AC1."):
        raise DxfError("a DWG file, not a DXF: save it as DXF")
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        text = data.decode("utf-16", errors="replace")
    else:
        text = data.decode("utf-8", errors="replace")
    text = text.lstrip("\ufeff")
    # only CR, LF and CRLF end a line (str.splitlines also splits at form feeds and U+0085,
    # which a TEXT value may hold)
    lines = re.split(r"\r\n|\n|\r", text)
    pairs = []
    n = len(lines) - 1
    i = 0
    while i < n:
        code = lines[i].strip()
        if not code:
            i += 1
            continue
        try:
            c = int(code)
        except ValueError as exc:
            raise DxfError(f"line {i + 1}: a group code was expected, found {code[:20]!r}") from exc
        pairs.append((c, lines[i + 1].strip()))
        i += 2
    return pairs


def _f(v):
    try:
        return float(v)
    except ValueError as exc:
        raise DxfError(f"a number was expected, found {v[:20]!r}") from exc


def _i(v):
    try:
        return int(float(v))
    except ValueError as exc:
        raise DxfError(f"an integer was expected, found {v[:20]!r}") from exc


class _Entity:
    """One entity: its type and its groups in order"""

    __slots__ = ("kind", "groups")

    def __init__(self, kind):
        self.kind = kind
        self.groups = []

    def get(self, code, default=None):
        for c, v in self.groups:
            if c == code:
                return v
        return default

    def f(self, code, default=0.0):
        v = self.get(code)
        return default if v is None else _f(v)

    def i(self, code, default=0):
        v = self.get(code)
        return default if v is None else _i(v)

    def point(self, code):
        return (self.f(code), self.f(code + 10), self.f(code + 20))

    def extrusion(self):
        if self.get(210) is None:
            return None
        return (self.f(210), self.f(220), self.f(230, 1.0))


def _entities(pairs, start, end_kinds):
    """Entities from pairs[start] (a 0 group) until a 0 group whose value is in end_kinds"""
    out = []
    i = start
    n = len(pairs)
    cur = None
    while i < n:
        c, v = pairs[i]
        if c == 0:
            if v in end_kinds:
                if cur is not None:
                    out.append(cur)
                return out, i
            if cur is not None:
                out.append(cur)
            cur = _Entity(v)
        elif cur is not None:
            cur.groups.append((c, v))
        i += 1
    if cur is not None:
        out.append(cur)
    return out, i


def _sections(pairs):
    """name -> (first index, last index) of each SECTION"""
    secs = {}
    i, n = 0, len(pairs)
    while i < n:
        c, v = pairs[i]
        if c == 0 and v == "SECTION" and i + 1 < n and pairs[i + 1][0] == 2:
            name = pairs[i + 1][1]
            j = i + 2
            while j < n and not (pairs[j][0] == 0 and pairs[j][1] == "ENDSEC"):
                j += 1
            secs[name] = (i + 2, j)
            i = j + 1
        else:
            i += 1
    return secs


# ---------------------------------------------------------------------------------------------


NOT_GEOMETRY = {
    "TEXT",
    "MTEXT",
    "ATTRIB",
    "ATTDEF",
    "DIMENSION",
    "LEADER",
    "MLEADER",
    "MULTILEADER",
    "HATCH",
    "IMAGE",
    "WIPEOUT",
    "SOLID",
    "TRACE",
    "3DFACE",
    "3DSOLID",
    "REGION",
    "BODY",
    "MESH",
    "TOLERANCE",
    "VIEWPORT",
    "OLE2FRAME",
    "ACAD_TABLE",
    "RAY",
    "XLINE",
    "SHAPE",
}


class _Reader:
    def __init__(self, drawing, blocks):
        self.d = drawing
        self.blocks = blocks  # name -> (base point, [entities])
        self.depth = 0

    def emit_line(self, m, p, q):
        a, b = apply(m, p), apply(m, q)
        if abs(a[2] - b[2]) > 1e-9 * (1.0 + abs(a[2])):
            self.d.projected += 1
        self.d.items.append(Line((a[0], a[1]), (b[0], b[1])))

    def emit_conic(self, m, c, u, v, t0, t1, full):
        cw = apply(m, c)
        uw = apply_vec(m, u)
        vw = apply_vec(m, v)
        if abs(uw[2]) > 1e-9 * math.hypot(uw[0], uw[1]) or abs(vw[2]) > 1e-9 * math.hypot(vw[0], vw[1]):
            self.d.projected += 1
        self.d.items.append(Conic((cw[0], cw[1]), (uw[0], uw[1]), (vw[0], vw[1]), t0, t1, full))

    def bulge_segment(self, m, p, q, bulge):
        """A polyline segment from p to q (object coordinates) with its bulge"""
        dx, dy = q[0] - p[0], q[1] - p[1]
        chord = math.hypot(dx, dy)
        if chord < 1e-15:
            return
        # straight when the arc's sagitta (about bulge x chord / 2) is below a nanometre: a
        # radius of thousands of kilometres, whose ends computed from angles miss its vertices
        if abs(bulge) * chord * 0.5 < 1e-9:
            self.emit_line(m, p, q)
            return
        theta = 4.0 * math.atan(bulge)  # included angle, positive counterclockwise
        r = chord / (2.0 * math.sin(abs(theta) / 2.0))
        # the centre: from the chord's midpoint along its left normal (right for a negative bulge)
        h = r * math.cos(theta / 2.0)  # signed distance, + for bulge in (0, 1)
        mx, my = (p[0] + q[0]) / 2.0, (p[1] + q[1]) / 2.0
        nx, ny = -dy / chord, dx / chord
        sgn = 1.0 if bulge > 0 else -1.0
        cx, cy = mx + sgn * h * nx, my + sgn * h * ny
        a0 = math.atan2(p[1] - cy, p[0] - cx)
        z = p[2]
        if bulge > 0:
            u, v = (r, 0.0, 0.0), (0.0, r, 0.0)
            t0 = a0
            t1 = a0 + theta
        else:
            # clockwise in the object's plane: c + r cos t x - r sin t y, t from -a0
            u, v = (r, 0.0, 0.0), (0.0, -r, 0.0)
            t0 = -a0
            t1 = -a0 - theta
        self.emit_conic(m, (cx, cy, z), u, v, t0, t1, False)

    def entity(self, e, m):
        k = e.kind
        if e.i(67) == 1:
            self.d.paperspace += 1
            return
        if k == "LINE":
            self.emit_line(m, e.point(10), e.point(11))
        elif k == "POINT":
            p = apply(m, e.point(10))
            self.d.items.append(Point((p[0], p[1])))
        elif k in ("CIRCLE", "ARC"):
            mo = compose(m, ocs_matrix(e.extrusion()))
            c = e.point(10)
            r = e.f(40)
            if r <= 0.0:
                self.d.skip(k + " of radius 0")
                return
            if k == "CIRCLE":
                self.emit_conic(mo, c, (r, 0.0, 0.0), (0.0, r, 0.0), 0.0, 2.0 * math.pi, True)
            else:
                a0 = math.radians(e.f(50))
                a1 = math.radians(e.f(51))
                while a1 <= a0:
                    a1 += 2.0 * math.pi
                full = a1 - a0 >= 2.0 * math.pi - 1e-12
                self.emit_conic(mo, c, (r, 0.0, 0.0), (0.0, r, 0.0), a0, a1, full)
        elif k == "ELLIPSE":
            c = e.point(10)
            mj = e.point(11)
            ratio = e.f(40, 1.0)
            n = e.extrusion() or (0.0, 0.0, 1.0)
            n = _unit(n)
            mn = _cross(n, mj)
            mn = (mn[0] * ratio, mn[1] * ratio, mn[2] * ratio)
            t0 = e.f(41, 0.0)
            t1 = e.f(42, 2.0 * math.pi)
            while t1 <= t0:
                t1 += 2.0 * math.pi
            full = t1 - t0 >= 2.0 * math.pi - 1e-9
            self.emit_conic(m, c, mj, mn, t0, t1, full)
        elif k == "LWPOLYLINE":
            self.lwpolyline(e, m)
        elif k == "SPLINE":
            self.spline(e, m)
        elif k == "INSERT":
            self.insert(e, m)
        elif k in NOT_GEOMETRY:
            self.d.skip(k)
        elif k in ("SEQEND", "VERTEX"):
            pass
        else:
            self.d.skip(k)

    def lwpolyline(self, e, m):
        mo = compose(m, ocs_matrix(e.extrusion()))
        closed = e.i(70) & 1
        z = e.f(38)
        verts = []  # (x, y, bulge)
        cur = None
        for c, v in e.groups:
            if c == 10:
                if cur is not None:
                    verts.append(cur)
                cur = [_f(v), 0.0, 0.0]
            elif c == 20 and cur is not None:
                cur[1] = _f(v)
            elif c == 42 and cur is not None:
                cur[2] = _f(v)
        if cur is not None:
            verts.append(cur)
        self.poly(mo, [(x, y, z) for x, y, _ in verts], [b for _, _, b in verts], closed)

    def poly(self, m, pts, bulges, closed):
        n = len(pts)
        if n < 2:
            if n == 1:
                self.d.skip("polyline of one vertex")
            return
        for k in range(n - 1 + (1 if closed else 0)):
            p, q = pts[k], pts[(k + 1) % n]
            if p[0] == q[0] and p[1] == q[1] and p[2] == q[2]:
                continue
            self.bulge_segment(m, p, q, bulges[k])

    def polyline(self, head, vertices, m):
        """An old-style POLYLINE with its VERTEX entities"""
        flags = head.i(70)
        if flags & (16 | 64):
            self.d.skip("POLYLINE mesh")
            return
        is3d = flags & 8
        mo = m if is3d else compose(m, ocs_matrix(head.extrusion()))
        pts, bulges = [], []
        z = head.f(30) if not is3d else 0.0
        for v in vertices:
            vf = v.i(70)
            if vf & 16:  # a spline frame's control point
                continue
            p = v.point(10)
            if not is3d:
                p = (p[0], p[1], z)
            pts.append(p)
            bulges.append(v.f(42))
        self.poly(mo, pts, bulges, flags & 1)

    def spline(self, e, m):
        degree = e.i(71, 3)
        knots, poles, weights, fits = [], [], [], []
        cur = None
        fcur = None
        for c, v in e.groups:
            if c == 40:
                knots.append(_f(v))
            elif c == 41:
                weights.append(_f(v))
            elif c == 10:
                cur = [_f(v), 0.0, 0.0]
                poles.append(cur)
            elif c == 20 and cur is not None:
                cur[1] = _f(v)
            elif c == 30 and cur is not None:
                cur[2] = _f(v)
            elif c == 11:
                fcur = [_f(v), 0.0, 0.0]
                fits.append(fcur)
            elif c == 21 and fcur is not None:
                fcur[1] = _f(v)
            elif c == 31 and fcur is not None:
                fcur[2] = _f(v)
        if poles:
            if len(knots) != len(poles) + degree + 1:
                self.d.skip("SPLINE with an inconsistent knot vector")
                return
            if weights and len(weights) != len(poles):
                weights = []
            wp = [apply(m, tuple(p)) for p in poles]
            if any(abs(p[2] - wp[0][2]) > 1e-9 * (1.0 + abs(p[2])) for p in wp):
                self.d.projected += 1
            self.d.items.append(Spline(degree, [(p[0], p[1]) for p in wp], knots, weights or None))
        elif len(fits) >= 2:
            wp = [apply(m, tuple(p)) for p in fits]
            self.d.items.append(FitSpline([(p[0], p[1]) for p in wp]))
        else:
            self.d.skip("SPLINE without control or fit points")

    def insert(self, e, m):
        name = e.get(2)
        block = self.blocks.get(name)
        if block is None:
            self.d.missing_blocks.add(name)
            return
        if self.depth > 32:
            raise DxfError(f"blocks nested more than 32 deep (block {name!r})")
        base, ents = block
        ins = e.point(10)
        sx, sy, sz = e.f(41, 1.0), e.f(42, 1.0), e.f(43, 1.0)
        rot = math.radians(e.f(50))
        cols, rows = max(1, e.i(70, 1)), max(1, e.i(71, 1))
        dcol, drow = e.f(44), e.f(45)
        ocs = ocs_matrix(e.extrusion())
        cr, sr = math.cos(rot), math.sin(rot)
        for i in range(rows):
            for j in range(cols):
                # in the OCS: translate(ins + R(offset)) * R * S * translate(-base)
                ox = j * dcol
                oy = i * drow
                tx = ins[0] + cr * ox - sr * oy
                ty = ins[1] + sr * ox + cr * oy
                local = (
                    (cr * sx, -sr * sy, 0.0, 0.0),
                    (sr * sx, cr * sy, 0.0, 0.0),
                    (0.0, 0.0, sz, 0.0),
                )
                local = compose(local, ((1, 0, 0, -base[0]), (0, 1, 0, -base[1]), (0, 0, 1, -base[2])))
                local = compose(((1, 0, 0, tx), (0, 1, 0, ty), (0, 0, 1, ins[2])), local)
                mm = compose(m, compose(ocs, local))
                self.depth += 1
                try:
                    self.run(ents, mm)
                finally:
                    self.depth -= 1

    def run(self, ents, m):
        i, n = 0, len(ents)
        while i < n:
            e = ents[i]
            if e.kind == "POLYLINE":
                j = i + 1
                verts = []
                while j < n and ents[j].kind == "VERTEX":
                    verts.append(ents[j])
                    j += 1
                if j < n and ents[j].kind == "SEQEND":
                    j += 1
                if e.i(67) == 1:
                    self.d.paperspace += 1
                else:
                    self.polyline(e, verts, m)
                i = j
                continue
            self.entity(e, m)
            i += 1


def read(path):
    """The DXF at path, flattened (see the module's doc)"""
    pairs = _pairs(path)
    if not pairs:
        raise DxfError("an empty file")
    d = Drawing()
    secs = _sections(pairs)
    if "ENTITIES" not in secs:
        raise DxfError("no ENTITIES section: not a DXF drawing")
    if "HEADER" in secs:
        a, b = secs["HEADER"]
        var = None
        for c, v in pairs[a:b]:
            if c == 9:
                var = v
            elif var == "$INSUNITS" and c == 70:
                d.insunits = _i(v) or None
            elif var == "$ACADVER" and c == 1:
                d.version = v
    blocks = {}
    if "BLOCKS" in secs:
        a, b = secs["BLOCKS"]
        i = a
        while i < b:
            c, v = pairs[i]
            if c == 0 and v == "BLOCK":
                head, j = _entities(pairs, i, {"ENDBLK", "ENDSEC"})
                # head[0] is the BLOCK entity itself
                blk = head[0]
                name = blk.get(2)
                blocks[name] = (blk.point(10), head[1:])
                i = j + 1
            else:
                i += 1
    a, b = secs["ENTITIES"]
    ents, _ = _entities(pairs, a, {"ENDSEC"})
    _Reader(d, blocks).run(ents, IDENTITY)
    return d
