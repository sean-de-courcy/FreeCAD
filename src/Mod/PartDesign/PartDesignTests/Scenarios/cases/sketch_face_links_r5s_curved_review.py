# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r5s (class E, E1; ops#264 e2): attacks on a face link's pairing aimed at round 5's
two changes: the place vote's same-side test (`sameSide`, a midpoint normal) and the batch check
that rejects a batch which empties one arc of a loop while another fills.

Every model is designed geometry: a profile padded 10 high, a sketch at z = 0 projecting the pad's
top face, and circles r 1 held by PointOnObject on projected geometry. The outcome is where each
constraint is after the edit (on the new copy of its own line, or the sketch breaks)."""

import math
import random

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6

SQUARE = [(0, 0), (20, 0), (20, 20), (0, 20)]
SQUARE_LINES = [((0, 0), (20, 0)), ((20, 0), (20, 20)), ((20, 20), (0, 20)), ((0, 20), (0, 0))]


def matches(g, spec):
    """spec: ("x"|"y", value, (lo, hi)), ("ends", a, b), ("arc", centre, radius)."""
    if spec[0] == "arc":
        if not hasattr(g, "Radius") or not hasattr(g, "FirstParameter"):
            return False
        return g.Center.isEqual(V(*spec[1], 0), TOL) and abs(g.Radius - spec[2]) < TOL
    if not hasattr(g, "StartPoint") or hasattr(g, "Radius"):
        return False
    s, e = g.StartPoint, g.EndPoint
    if spec[0] == "ends":
        a, b = V(*spec[1], 0), V(*spec[2], 0)
        return (s.isEqual(a, TOL) and e.isEqual(b, TOL)) or (s.isEqual(b, TOL) and e.isEqual(a, TOL))
    axis, value, (lo, hi) = spec
    other = "y" if axis == "x" else "x"
    if not all(abs(getattr(p, axis) - value) < TOL for p in (s, e)):
        return False
    a, b = sorted(getattr(p, other) for p in (s, e))
    return abs(a - lo) < TOL and abs(b - hi) < TOL


def findExternal(sketch, spec):
    found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and matches(g, spec)]
    if len(found) < 1:
        raise AssertionError(f"no projected geometry matches {spec}")
    return found[0]


def anchorPoint(spec):
    if spec[0] == "arc":
        return (spec[1][0] + spec[2], spec[1][1])
    if spec[0] == "ends":
        return tuple((a + b) / 2 for a, b in zip(spec[1], spec[2]))
    axis, value, (lo, hi) = spec
    return (value, (lo + hi) / 2) if axis == "x" else ((lo + hi) / 2, value)


def lineSpec(a, b):
    """An axis-aligned line's spec."""
    if abs(a[0] - b[0]) < TOL:
        return ("x", a[0], tuple(sorted((a[1], b[1]))))
    return ("y", a[1], tuple(sorted((a[0], b[0]))))


class HeldBy(Outcome):
    """Each PointOnObject constraint (in the order they were added) names the projected geometry
    `before()[i]` before the edit and `after()[i]` after it, with its circle's centre on it."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        specs = self.before() if scenario.stepName is None else self.after()
        cons = [c for c in consumer.Constraints if c.Type == "PointOnObject"]
        if not consumer.isValid():
            return False, consumer.getStatusString()
        if len(cons) != len(specs):
            return False, f"{len(cons)} constraints for {len(specs)} specs"
        for c, spec in zip(cons, specs):
            held = consumer.ExternalGeo[-c.Second - 1]
            if not matches(held, spec):
                return False, f"a constraint is on {held.TypeId} {held}, not {spec}"
            centre = consumer.Geometry[c.First].Center
            if spec[0] == "arc":
                if abs((centre - held.Center).Length - held.Radius) > TOL:
                    return False, f"circle centre at {centre}"
            elif centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
                return False, f"circle centre at {centre}"
        return True, ""


class Review(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r5s"
    TIER = "F"
    AXES = ("M8", "E5")
    SIZE = 40
    SCALE = 1.0
    REFS = ("circles_on_geometry",)
    height = 10

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in SQUARE])

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def expectation(self):
        return self.topFace

    def build(self, doc):
        s = self.s
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.profileGeometry(), body)
        pad = m.pad(body, profile, s(self.height))
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        for spec in self.before():
            line = findExternal(sketch, spec)
            x, y = anchorPoint(spec)
            circle = sketch.addGeometry(m.circle(x, y, s(1)), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, s(1)))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 HeldBy(self.before, self.afterEdit))

    def moveLines(self, doc, lines):
        s = self.s
        geometry = doc.Profile.Geometry
        for index, (a, b) in lines.items():
            line = geometry[index]
            line.StartPoint = V(*s(-777, -777), 0)
            line.EndPoint = V(*s(*b), 0)
            line.StartPoint = V(*s(*a), 0)
        doc.Profile.Geometry = geometry

    def addLines(self, doc, points):
        doc.Profile.addGeometry(m.polyline([self.s(*p) for p in points]), False)


# ---- a profile translated; kept / redrawn / flipped lines; a cut (the place vote's side) -----------

SHAPES = {
    "Sq": [(0, 0), (20, 0), (20, 20), (0, 20)],
    "L": [(0, 0), (30, 0), (30, 10), (10, 10), (10, 30), (0, 30)],
    "U": [(0, 0), (30, 0), (30, 20), (20, 20), (20, 8), (10, 8), (10, 20), (0, 20)],
    "N": [(0, 0), (50, 0), (50, 20), (20, 20), (20, 8), (10, 8), (10, 20), (0, 20)],
}


def outLines(points, dx, dy, cut, size=3):
    """The translated profile's lines (start, end), the ends shortened by a cut at the end of
    line `cut` (the corner after it); and the cut line, or None."""
    n = len(points)
    lines = [
        [[points[i][0] + dx, points[i][1] + dy],
         [points[(i + 1) % n][0] + dx, points[(i + 1) % n][1] + dy]]
        for i in range(n)
    ]
    cutLine = None
    if cut is not None:
        i, j = cut, (cut + 1) % n
        a, b = lines[i]
        c, d = lines[j]
        ub = (b[0] - a[0], b[1] - a[1])
        k = math.hypot(*ub)
        newEnd = [b[0] - size * ub[0] / k, b[1] - size * ub[1] / k]
        uc = (d[0] - c[0], d[1] - c[1])
        k = math.hypot(*uc)
        newStart = [c[0] + size * uc[0] / k, c[1] + size * uc[1] / k]
        lines[i][1] = newEnd
        lines[j][0] = newStart
        cutLine = (newEnd, newStart)
    return lines, cutLine


# ---- geometry saved before E1 (no source names) --------------------------------------------------
import os
import re
import tempfile
import zipfile


def reopenWithoutSources(scenario, doc):
    """The document saved, closed and opened again with every external geometry's source name
    removed from its Document.xml (geometry saved by a build before E1)."""
    scenario.folder = tempfile.mkdtemp(prefix="NamingScenario")
    path = os.path.join(scenario.folder, doc.Name + ".FCStd")
    doc.saveAs(path)
    App.closeDocument(doc.Name)
    with zipfile.ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    xml = files["Document.xml"].decode("utf-8")
    count = 0

    def strip(match):
        nonlocal count
        tag, n = re.subn(r' Source="[^"]*"', "", match.group(0))
        count += n
        return tag

    xml = re.sub(r'<GeoExtension [^>]*Sketcher::ExternalGeometryExtension[^>]*>', strip, xml)
    if count == 0 and hasattr(Sketcher.ExternalGeometryFacade, "Source"):
        raise RuntimeError("no external geometry with a source name in the saved file")
    files["Document.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return scenario.openDocument(path)


# ======================================================================================
# curved faces: an elliptical or B-spline edge in the loop (the exact swept area, the common move)
# ======================================================================================
import math as _math


def _near(a, b, tol=1e-6):
    return abs(a - b) <= tol


def isLine(g, a, b):
    if not hasattr(g, "StartPoint") or hasattr(g, "Radius") or hasattr(g, "MajorRadius"):
        return False
    if type(g).__name__ != "LineSegment":
        return False
    s, e = g.StartPoint, g.EndPoint
    A, B = V(*a, 0), V(*b, 0)
    return (s.isEqual(A, 1e-6) and e.isEqual(B, 1e-6)) or (s.isEqual(B, 1e-6) and e.isEqual(A, 1e-6))


def isEllipseArc(g, centre, major, minor):
    return (
        type(g).__name__ == "ArcOfEllipse"
        and g.Center.isEqual(V(*centre, 0), 1e-6)
        and _near(g.MajorRadius, major)
        and _near(g.MinorRadius, minor)
    )


def isSpline(g, poles):
    if type(g).__name__ != "BSplineCurve":
        return False
    got = g.getPoles()
    if len(got) != len(poles):
        return False
    fwd = all(p.isEqual(V(*q, 0), 1e-6) for p, q in zip(got, poles))
    rev = all(p.isEqual(V(*q, 0), 1e-6) for p, q in zip(got, reversed(poles)))
    return fwd or rev


class HeldOnEach(Outcome):
    """`items` before and after: (predicate on the external geometry the constraint names)."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        preds = self.before() if scenario.stepName is None else self.after()
        cons = [c for c in consumer.Constraints if c.Type == "PointOnObject"]
        if not consumer.isValid():
            return False, consumer.getStatusString()
        if len(cons) != len(preds):
            return False, f"{len(cons)} constraints for {len(preds)} expectations"
        for c, pred in zip(cons, preds):
            held = consumer.ExternalGeo[-c.Second - 1]
            if not pred(held):
                return False, f"a constraint is on {type(held).__name__} {held}"
            centre = consumer.Geometry[c.First].Center
            name = type(held).__name__
            if name == "LineSegment":
                d = centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint)
            elif name == "ArcOfParabola":
                r = centre - held.Location
                X = held.XAxis
                Y = held.Axis.cross(X)
                u, v = r.dot(X), r.dot(Y)
                d = abs(u - v * v / (4 * held.Focal))
            elif name == "ArcOfEllipse":
                X = held.XAxis
                Y = held.Axis.cross(X)
                r = centre - held.Center
                d = abs((r.dot(X) / held.MajorRadius) ** 2 + (r.dot(Y) / held.MinorRadius) ** 2 - 1.0) * held.MinorRadius
            else:
                d = held.toShape().distToShape(Part.Vertex(centre))[0]
            if d > 1e-5:
                return False, f"circle centre {d} from the curve"
        return True, ""


class Curved(Scenario):
    """A profile with a curved edge on its right (lines: 0 bottom, 2 top, 3 left; the curve is 1),
    padded 10; the sketch projects the top face and has circles on every projected edge. The edit
    moves the profile (sketch Placement by (dx, dy)), optionally cutting the front-left corner
    (a new line); every geometry keeps its ID."""

    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r5s"
    TIER = "F"
    AXES = ("M8", "E5", "E2")
    REFS = ("circles_on_geometry",)
    dx, dy = 20, 5
    cut = True
    hole = False
    kind = "ellipse"
    curveShift = (0, 0)

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def expectation(self):
        return self.topFace

    # the curve: from (20, 4) to (20, 16), bulging to the right
    def curve(self, p):
        if self.kind == "ellipse":
            return Part.ArcOfEllipse(
                Part.Ellipse(V(20 + p[0], 10 + p[1], 0), 10, 6), -_math.pi / 2, _math.pi / 2
            )
        if self.kind == "parabola":
            pb = Part.Parabola()
            pb.Location = V(30, 10, 0)
            pb.Focal = 0.9
            pb.Axis = V(0, 0, 1)
            pb.XAxis = V(-1, 0, 0)
            return Part.ArcOfParabola(pb, -6, 6)
        bs = Part.BSplineCurve()
        bs.buildFromPoles([V(20, 4, 0), V(30, 6, 0), V(30, 14, 0), V(20, 16, 0)], False, 3)
        if self.kind == "rational":
            bs = Part.BSplineCurve()
            bs.buildFromPolesMultsKnots(
                [V(20, 4, 0), V(30, 6, 0), V(30, 14, 0), V(20, 16, 0)], [4, 4], [0, 1], False, 3,
                [1.0, 1.5, 1.5, 1.0],
            )
        return bs

    def curvePred(self, shift):
        if self.kind == "ellipse":
            return lambda g: isEllipseArc(g, (20 + shift[0], 10 + shift[1]), 10, 6)
        if self.kind == "parabola":
            return lambda g: type(g).__name__ == "ArcOfParabola" and g.Location.isEqual(V(30 + shift[0], 10 + shift[1], 0), 1e-6)
        return lambda g: isSpline(
            g, [(20 + shift[0], 4 + shift[1]), (30 + shift[0], 6 + shift[1]),
                (30 + shift[0], 14 + shift[1]), (20 + shift[0], 16 + shift[1])]
        )

    def holeLines(self):
        return [((5, 7), (10, 7)), ((10, 7), (10, 13)), ((10, 13), (5, 13)), ((5, 13), (5, 7))]

    def roles(self):
        """(before predicate, after predicate) per projected edge of the profile."""
        dx, dy = self.dx, self.dy
        sh = (dx, dy)

        def line(a, b, a2=None, b2=None):
            a2 = a2 or a
            b2 = b2 or b
            return (
                lambda g: isLine(g, a, b),
                lambda g: isLine(g, (a2[0] + dx, a2[1] + dy), (b2[0] + dx, b2[1] + dy)),
            )

        out = [
            line((0, 4), (20, 4), *(((3, 4), (20, 4)) if self.cut else ())),
            (self.curvePred((0, 0)), self.curvePred(sh)),
            line((20, 16), (0, 16)),
            line((0, 16), (0, 4), *(((0, 16), (0, 7)) if self.cut else ())),
        ]
        if self.hole:
            for a, b in self.holeLines():
                out.append(line(a, b))
        return out

    def build(self, doc):
        body = m.body(doc)
        geos = [
            Part.LineSegment(V(0, 4, 0), V(20, 4, 0)),
            self.curve((0, 0)),
            Part.LineSegment(V(20, 16, 0), V(0, 16, 0)),
            Part.LineSegment(V(0, 16, 0), V(0, 4, 0)),
        ]
        if self.hole:
            geos += [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in self.holeLines()]
        profile = m.sketch(doc, "Profile", geos, body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        roles = self.roles()
        self.afterList = []
        self.beforeList = []
        for i in range(2, len(sketch.ExternalGeo)):
            geoId = -i - 1
            g = sketch.ExternalGeo[i]
            role = [r for r in roles if r[0](g)]
            if len(role) != 1:
                raise AssertionError(f"projected edge {i} {g} matches {len(role)} roles")
            if self.kind == "rational" and type(g).__name__ == "BSplineCurve":
                continue
            self.beforeList.append(role[0][0])
            self.afterList.append(role[0][1])
            mid = g.value(g.FirstParameter + (g.LastParameter - g.FirstParameter) / 2)
            circle = sketch.addGeometry(m.circle(mid.x, mid.y, 0.5), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, geoId))
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, 0.5))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 HeldOnEach(lambda: self.beforeList, lambda: self.afterList))

    def edit(self, doc):
        doc.Profile.Placement = App.Placement(V(self.dx, self.dy, 0), App.Rotation())
        if self.cut:
            m.setLines(doc.Profile, {0: ((3, 4), (20, 4)), 3: ((0, 16), (0, 7))})
            doc.Profile.addGeometry(Part.LineSegment(V(0, 7, 0), V(3, 4, 0)), False)


class ReviewEllipseFaceMovedCut(Curved):
    kind = "ellipse"


class ReviewEllipseFaceMovedNoCut(Curved):
    kind = "ellipse"
    cut = False


class ReviewSplineFaceMovedCut(Curved):
    kind = "spline"


class ReviewSplineFaceMovedNoCut(Curved):
    kind = "spline"
    cut = False


class ReviewRationalFaceMovedCut(Curved):
    kind = "rational"


class ReviewEllipseHoleFaceMovedCut(Curved):
    kind = "ellipse"
    hole = True


class ReviewSplineHoleFaceMovedCut(Curved):
    kind = "spline"
    hole = True


class ReviewRationalHoleFaceMovedCut(Curved):
    kind = "rational"
    hole = True


class ReviewEllipseHoleFaceMovedNoCut(Curved):
    kind = "ellipse"
    hole = True
    cut = False


class ReviewRationalHoleFaceMovedNoCut(Curved):
    kind = "rational"
    hole = True
    cut = False


class ReviewParabolaFaceMovedCut(Curved):
    kind = "parabola"


class ReviewParabolaFaceMovedNoCut(Curved):
    kind = "parabola"
    cut = False


class ReviewParabolaHoleFaceMovedCut(Curved):
    kind = "parabola"
    hole = True
