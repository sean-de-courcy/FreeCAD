# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r5 (class E, E1; ops#264 e2): targeted attacks on round 5's changes to
`pairGeometries` for curves other than lines: the exact loop areas (`sweptArea`: arcs of
ellipses, polynomial B-splines exactly, rational B-splines sampled), the common move that now
covers ellipse arcs and B-splines, and the `sideUnknown` rule (a link with several closed loops,
one of them sampled, gives no place votes).

Model: a 20 x 20 square (front F, right R, back B, left L) whose right side is a curve bulging out
by 6 (a polynomial B-spline, an arc of an ellipse or a rational B-spline), optionally inside a
larger plate as a hole; padded 10 (or a Part::Feature face at z = 10 without names). A sketch at
z = 0 projects the top face and holds a circle r 1 on each of the lines F, B and L (PointOnObject).
Expected: each circle on the edited copy of its own line, or the sketch breaks."""

import math

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6


def matches(g, spec):
    if not hasattr(g, "StartPoint") or g.TypeId != "Part::GeomLineSegment":
        return False
    s, e = g.StartPoint, g.EndPoint
    a, b = V(*spec[1], 0), V(*spec[2], 0)
    return (s.isEqual(a, TOL) and e.isEqual(b, TOL)) or (s.isEqual(b, TOL) and e.isEqual(a, TOL))


class HeldBy(Outcome):
    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        specs = self.before() if scenario.stepName is None else self.after()
        cons = [c for c in consumer.Constraints if c.Type == "PointOnObject"]
        if not consumer.isValid():
            return False, consumer.getStatusString()
        for c, spec in zip(cons, specs):
            held = consumer.ExternalGeo[-c.Second - 1]
            if not matches(held, spec):
                return False, f"a constraint is on {held.TypeId} {held}, not {spec}"
            centre = consumer.Geometry[c.First].Center
            if centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
                return False, f"circle centre at {centre}"
        return True, ""


class CurvedSide(Scenario):
    """The square at (x0, y0) with its right side the curve `kind`; `cut`: the front-left corner
    cut by 3 (F starts at x0 + 3, L ends at y0 + 3, a new line between)."""

    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r5"
    TIER = "F"
    AXES = ("M8", "E5", "E2")
    SIZE = 40
    SCALE = 1.0
    REFS = ("circles_on_geometry",)
    kind = "bspline"
    hole = False      # the square is a hole in a 60 x 40 plate from (-20, -10)
    named = True      # False: a Part::Feature face without names
    dx = dy = 0       # the edit's move
    cutAfter = True   # the edit cuts the front-left corner

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(10)))

    def curve(self, x0, y0):
        s = self.s
        if self.kind == "bspline":
            c = Part.BSplineCurve()
            poles = [V(*s(20 + x0, y0), 0), V(*s(28 + x0, 6 + y0), 0),
                     V(*s(28 + x0, 14 + y0), 0), V(*s(20 + x0, 20 + y0), 0)]
            c.buildFromPolesMultsKnots(poles, [4, 4], [0.0, 1.0], False, 3)
            return c
        if self.kind == "rational":
            arc = Part.ArcOfCircle(Part.Circle(V(*s(14 + x0, 10 + y0), 0), V(0, 0, 1), s(math.hypot(6, 10))),
                                   -math.atan2(10, 6), math.atan2(10, 6))
            return arc.toBSpline()
        if self.kind == "parabola":
            # vertex (26, 10) + (x0, y0), opening to -x, through the square's right corners
            f = s(100.0 / 24.0)
            par = Part.Parabola()
            par.Focal = f
            par.XAxis = V(-1, 0, 0)
            par.Center = V(*s(26 + x0, 10 + y0), 0)
            arc = Part.ArcOfParabola(par, -s(10), s(10))
            return arc
        # an arc of an ellipse: centre (20, 10) + (x0, y0), major 10 along y, minor 6 along x
        e = Part.Ellipse(V(*s(20 + x0, 20 + y0), 0), V(*s(26 + x0, 10 + y0), 0),
                         V(*s(20 + x0, 10 + y0), 0))
        return Part.ArcOfEllipse(e, math.pi, 2 * math.pi)

    def lines(self, x0, y0, cut):
        """F, B, L and the cut line (or None), as point pairs, unscaled."""
        f = ((x0 + (3 if cut else 0), y0), (x0 + 20, y0))
        b = ((x0 + 20, y0 + 20), (x0, y0 + 20))
        l = ((x0, y0 + 20), (x0, y0 + (3 if cut else 0)))
        c = ((x0, y0 + 3), (x0 + 3, y0)) if cut else None
        return f, b, l, c

    def specs(self, x0, y0, cut):
        f, b, l, _ = self.lines(x0, y0, cut)
        return [("ends", self.s(*p), self.s(*q)) for p, q in (f, b, l)]

    def before(self):
        return self.specs(0, 0, False)

    def afterEdit(self):
        return self.specs(self.dx, self.dy, self.cutAfter)

    def geometry(self, x0, y0, cut):
        f, b, l, c = self.lines(x0, y0, cut)
        seg = lambda pq: Part.LineSegment(V(*self.s(*pq[0]), 0), V(*self.s(*pq[1]), 0))
        geo = [seg(f), self.curve(x0, y0), seg(b), seg(l)]
        if c:
            geo.append(seg(c))
        return geo

    def plate(self):
        return [Part.LineSegment(V(*self.s(*p), 0), V(*self.s(*q), 0)) for p, q in
                (((-20, -10), (40, -10)), ((40, -10), (40, 30)), ((40, 30), (-20, 30)),
                 ((-20, 30), (-20, -10)))]

    def faceShape(self, x0, y0, cut):
        z = App.Placement(V(0, 0, self.s(10)), App.Rotation())
        inner = Part.Wire(Part.sortEdges([g.toShape() for g in self.geometry(x0, y0, cut)])[0])
        wires = [inner]
        if self.hole:
            wires = [Part.Wire(Part.sortEdges([g.toShape() for g in self.plate()])[0]), inner]
        shape = Part.makeFace(wires, "Part::FaceMakerBullseye")
        shape.Placement = z
        return shape

    def build(self, doc):
        if self.named:
            body = m.body(doc)
            geo = self.geometry(0, 0, False)
            if self.hole:
                geo = geo + self.plate()
            profile = m.sketch(doc, "Profile", geo, body)
            target = m.pad(body, profile, self.s(10))
            doc.recompute()
            sketch = m.sketch(doc, "OnTop", [], body)
        else:
            target = m.feature(doc, "Plate", self.faceShape(0, 0, False))
            doc.recompute()
            sketch = doc.addObject("Sketcher::SketchObject", "OnTop")
        sketch.addExternal(target.Name, self.names(target, self.topFace())[0])
        doc.recompute()
        for spec in self.before():
            found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and matches(g, spec)]
            if not found:
                raise AssertionError(f"no projected line matches {spec}")
            x = (spec[1][0] + spec[2][0]) / 2
            y = (spec[1][1] + spec[2][1]) / 2
            circle = sketch.addGeometry(m.circle(x, y, self.s(1)), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, found[0]))
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, self.s(1)))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 HeldBy(self.before, self.afterEdit))

    def edit(self, doc):
        if not self.named:
            doc.Plate.Shape = self.faceShape(self.dx, self.dy, self.cutAfter)
            return
        sk = doc.Profile
        new = self.geometry(self.dx, self.dy, self.cutAfter)
        geometry = sk.Geometry
        # the four sides keep their IDs: lines by their ends, the curve by its translated copy
        for index in (0, 1, 2, 3):
            g = geometry[index]
            if index == 1:
                g.translate(V(*self.s(self.dx, self.dy), 0))
            else:
                g.StartPoint = V(-7777, -7777, 0)
                g.EndPoint = new[index].EndPoint
                g.StartPoint = new[index].StartPoint
        sk.Geometry = geometry
        if self.cutAfter:
            sk.addGeometry(new[4], False)


class ReviewBsplineSideMovedCut(CurvedSide):
    """A polynomial B-spline side; the square moved (20, 5) with its IDs, a corner cut added."""

    dx, dy = 20, 5


class ReviewBsplineSideCut(CurvedSide):
    """The same without the move (place votes)."""


class ReviewEllipseSideMovedCut(CurvedSide):
    kind = "ellipse"
    dx, dy = 20, 5


class ReviewEllipseSideCut(CurvedSide):
    kind = "ellipse"


class ReviewRationalSideMovedCut(CurvedSide):
    kind = "rational"
    dx, dy = 20, 5


class ReviewRationalSideCut(CurvedSide):
    kind = "rational"


class ReviewRationalHoleMovedCut(CurvedSide):
    """The square a hole in a plate (two loops, one sampled: the side is unknown); the hole moved
    (20, 5) with its IDs and its corner cut."""

    kind = "rational"
    hole = True
    dx, dy = 5, 3


class ReviewRationalHoleCut(CurvedSide):
    kind = "rational"
    hole = True


class ReviewBsplineHoleMovedCut(CurvedSide):
    hole = True
    dx, dy = 5, 3


class ReviewEllipseHoleMovedCut(CurvedSide):
    kind = "ellipse"
    hole = True
    dx, dy = 5, 3


class ReviewUnmappedRationalHoleCut(CurvedSide):
    """A Part::Feature plate without names whose hole has a rational side; the hole's corner cut
    (place votes only, and the side unknown)."""

    kind = "rational"
    hole = True
    named = False


class ReviewUnmappedBsplineHoleCut(CurvedSide):
    hole = True
    named = False


class ReviewUnmappedRationalSideCut(CurvedSide):
    kind = "rational"
    named = False


class ReviewUnmappedRationalHoleMoved(CurvedSide):
    """The unmapped plate's hole moved (5, 3), no cut: the list is unchanged (position votes)."""

    kind = "rational"
    hole = True
    named = False
    dx, dy = 5, 3
    cutAfter = False


class ReviewBsplineSideMovedCut4m(ReviewBsplineSideMovedCut):
    SCALE = 100.0


class ReviewEllipseSideMovedCut4m(ReviewEllipseSideMovedCut):
    SCALE = 100.0


class ReviewRationalHoleMovedCut4m(ReviewRationalHoleMovedCut):
    SCALE = 100.0


# ---- a corner cut deleted: the circle on it must break (decision 167 reads only gaining arcs) ----


class MustBreak(Outcome):
    """The PointOnObject constraints on geometry that is gone: the sketch must not stay valid
    with them on another line."""

    def __init__(self, before):
        self.before = before

    def compare(self, scenario, consumer, target, expectation):
        cons = [c for c in consumer.Constraints if c.Type == "PointOnObject"]
        if scenario.stepName is None:
            for c, spec in zip(cons, self.before()):
                held = consumer.ExternalGeo[-c.Second - 1]
                if not matches(held, spec):
                    return False, f"before: on {held}, not {spec}"
            return True, ""
        if not consumer.isValid():
            return True, ""
        held = [str(consumer.ExternalGeo[-c.Second - 1]) for c in cons]
        return False, f"the cut is gone but its constraint holds {held}"


CUT_SQUARE = [((3, 0), (20, 0)), ((20, 0), (20, 20)), ((20, 20), (0, 20)), ((0, 20), (0, 3)),
              ((0, 3), (3, 0))]


class CutGone(Scenario):
    """The 20 x 20 square with its front-left corner cut 3 x 3 (F, R, B, L, C: IDs 0-4), padded
    10; a circle on C. The edit deletes C (and maybe L, drawn again), optionally moving the rest
    by (dx, dy). C's edge is gone: its constraint must break, not move to another line."""

    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r5"
    TIER = "F"
    AXES = ("M8", "E5", "E2")
    REFS = ("circle_on_cut",)
    dx = dy = 0
    redrawLeft = True

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def before(self):
        a, b = CUT_SQUARE[4]
        return [("ends", a, b)]

    def build(self, doc):
        body = m.body(doc)
        geo = [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in CUT_SQUARE]
        profile = m.sketch(doc, "Profile", geo, body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        spec = self.before()[0]
        found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and matches(g, spec)]
        circle = sketch.addGeometry(m.circle(1.5, 1.5, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, found[0]))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace, MustBreak(self.before))

    def edit(self, doc):
        sk = doc.Profile
        dx, dy = self.dx, self.dy
        P = lambda x, y: V(x + dx, y + dy, 0)
        sk.delGeometries([3, 4] if self.redrawLeft else [4])
        geometry = sk.Geometry
        ends = {0: ((0, 0), (20, 0)), 1: ((20, 0), (20, 20)), 2: ((20, 20), (0, 20)),
                3: ((0, 20), (0, 0))}
        for index in range(len(geometry)):
            (a, b) = ends[index]
            g = geometry[index]
            g.StartPoint = V(-7777, -7777, 0)
            g.EndPoint = P(*b)
            g.StartPoint = P(*a)
        sk.Geometry = geometry
        if self.redrawLeft:
            sk.addGeometry(Part.LineSegment(P(0, 20), P(0, 0)), False)


class ReviewCutGoneLeftRedrawn(CutGone):
    pass


class ReviewCutGoneLeftRedrawnMoved(CutGone):
    dx, dy = 20, 5


class ReviewCutGoneLeftKept(CutGone):
    redrawLeft = False


class ReviewCutGoneLeftKeptMoved(CutGone):
    redrawLeft = False
    dx, dy = 20, 5


class ReviewParabolaHoleCut(CurvedSide):
    """The hole's right side an arc of a parabola (its area sampled: two loops, the side
    unknown, no place votes); the hole's corner cut."""

    kind = "parabola"
    hole = True


class ReviewParabolaHoleMovedCut(ReviewParabolaHoleCut):
    dx, dy = 5, 3


class ReviewUnmappedParabolaHoleCut(ReviewParabolaHoleCut):
    named = False


class ReviewUnmappedParabolaHoleMoved(ReviewParabolaHoleCut):
    named = False
    dx, dy = 5, 3
    cutAfter = False


class ReviewParabolaSideMovedCut(CurvedSide):
    kind = "parabola"
    dx, dy = 20, 5
