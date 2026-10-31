# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r5f (class E, E1; ops#264 e2): attacks on round 5f's fix, the exact areas of arcs
of hyperbolas and parabolas (`sweptArea`) and their common move (`movedTogether`), aimed at what
the PR's own tests don't reach: an arc whose parameter range doesn't contain 0, a conic whose
normal is -Z (a reversed conic), and a side that isn't symmetric about the conic's axis.

Model: a quadrilateral (0, 0), (20, 0), (24, 20), (0, 20) whose right side, from (20, 0) to
(24, 20), is an arc of a hyperbola (axis along x, t in [0.3, 1.2]) or of a parabola (axis along x,
u in [5, 25]); with `reversed`, the same point set from a conic whose normal is -Z (range
[-1.2, -0.3] or [-25, -5]; only on the Part::Feature face: a Sketcher profile holding such a conic
gave no pad face here). Optionally a hole in a 64 x 40 plate. Padded 10 (or a Part::Feature
face at z = 10 without names). A sketch at z = 0 projects the top face and holds a circle r 1 on
each of the lines F (front), B (back) and L (left), PointOnObject. The edit moves the outline by
(dx, dy) keeping every Id (the conic translated) and cuts the front-left corner by 3; with
`redrawn`, the conic is deleted and drawn again (a new Id, so no name vote for it).
Expected (geometric): each circle on the edited copy of its own line, or the sketch breaks."""

import math

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6


def matches(g, spec):
    if g.TypeId != "Part::GeomLineSegment":
        return False
    s, e = g.StartPoint, g.EndPoint
    a, b = V(*spec[1], 0), V(*spec[2], 0)
    tol = TOL * max(1.0, a.Length, b.Length)
    return (s.isEqual(a, tol) and e.isEqual(b, tol)) or (s.isEqual(b, tol) and e.isEqual(a, tol))


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
            if centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL * max(
                    1.0, centre.Length):
                return False, f"circle centre at {centre}"
        return True, ""


class ConicSide(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r5f"
    TIER = "F"
    AXES = ("M8", "E5", "E2")
    SIZE = 64
    SCALE = 1.0
    REFS = ("circles_on_geometry",)
    kind = "hyperbola"
    reversed = False
    hole = False
    named = True
    redrawn = False
    dx = dy = 0
    cutAfter = True

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(10)))

    def curve(self, x0, y0):
        s = self.scale
        if self.kind == "hyperbola":
            t0, t1 = 0.3, 1.2
            a = 4 / (math.cosh(t1) - math.cosh(t0))
            b = 20 / (math.sinh(t1) - math.sinh(t0))
            h = Part.Hyperbola()
            h.MajorRadius = a * s
            h.MinorRadius = b * s
            h.Center = V((20 - a * math.cosh(t0) + x0) * s, (-b * math.sinh(t0) + y0) * s, 0)
            h.Axis = V(0, 0, -1 if self.reversed else 1)
            h.XAxis = V(1, 0, 0)
            if self.reversed:
                return Part.ArcOfHyperbola(h, -t1, -t0)
            return Part.ArcOfHyperbola(h, t0, t1)
        # x = vx + u^2 / 4f, y = vy + u: (20, 0) at u = 5, (24, 20) at u = 25
        f = 37.5
        p = Part.Parabola()
        p.Focal = f * s
        p.Center = V((20 - 25 / (4 * f) + x0) * s, (-5 + y0) * s, 0)
        p.Axis = V(0, 0, -1 if self.reversed else 1)
        p.XAxis = V(1, 0, 0)
        if self.reversed:
            return Part.ArcOfParabola(p, -25 * s, -5 * s)
        return Part.ArcOfParabola(p, 5 * s, 25 * s)

    def lines(self, x0, y0, cut):
        f = ((x0 + (3 if cut else 0), y0), (x0 + 20, y0))
        b = ((x0 + 24, y0 + 20), (x0, y0 + 20))
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
                (((-20, -10), (44, -10)), ((44, -10), (44, 30)), ((44, 30), (-20, 30)),
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
        for index in (0, 1, 2, 3):
            g = geometry[index]
            if index == 1:
                g.translate(V(*self.s(self.dx, self.dy), 0))
            else:
                g.StartPoint = V(-7777, -7777, 0)
                g.EndPoint = new[index].EndPoint
                g.StartPoint = new[index].StartPoint
        sk.Geometry = geometry
        if self.redrawn:
            sk.delGeometry(1)
            sk.addGeometry(new[1], False)
        if self.cutAfter:
            sk.addGeometry(new[4], False)


class ReviewHyperbolaOffAxisSideMovedCut(ConicSide):
    """The hyperbola side (range [0.3, 1.2]); the outline moved (20, 5) with its Ids, the corner
    cut: the common move must hold through the hyperbola."""

    dx, dy = 20, 5


class ReviewHyperbolaOffAxisHoleMovedCut(ConicSide):
    """The outline a hole (two loops: the hyperbola's area decides the side); moved (5, 3), cut."""

    hole = True
    dx, dy = 5, 3


class ReviewHyperbolaOffAxisHoleCut(ConicSide):
    hole = True


class ReviewParabolaOffAxisSideMovedCut(ConicSide):
    kind = "parabola"
    dx, dy = 20, 5


class ReviewParabolaOffAxisHoleMovedCut(ConicSide):
    kind = "parabola"
    hole = True
    dx, dy = 5, 3


class ReviewUnmappedReversedHyperbolaHoleCut(ConicSide):
    """A Part::Feature plate without names whose hole's right side is a hyperbola with normal -Z
    (range [-1.2, -0.3]); the hole's corner cut: place votes only, the side from the exact areas."""

    hole = True
    named = False
    reversed = True


class ReviewUnmappedReversedParabolaHoleCut(ConicSide):
    kind = "parabola"
    hole = True
    named = False
    reversed = True


class ReviewUnmappedReversedHyperbolaHoleMoved(ConicSide):
    """The unmapped plate's hole moved (5, 3), no cut: position votes (the list unchanged)."""

    hole = True
    named = False
    reversed = True
    cutAfter = False
    dx, dy = 5, 3


class ReviewUnmappedReversedParabolaHoleMovedCut(ConicSide):
    """The unmapped plate's hole moved (5, 3) and cut: nothing anchors by place or position."""

    kind = "parabola"
    hole = True
    named = False
    reversed = True
    dx, dy = 5, 3


class ReviewHyperbolaRedrawnSideMovedCut(ConicSide):
    """The outline moved (20, 5), the hyperbola drawn again (a new Id), the corner cut."""

    redrawn = True
    dx, dy = 20, 5


class ReviewParabolaRedrawnHoleMovedCut(ConicSide):
    kind = "parabola"
    redrawn = True
    hole = True
    dx, dy = 5, 3


class ReviewUnmappedParabolaHoleMovedCut(ConicSide):
    """The control for the reversed one: the same parabola with normal +Z."""

    kind = "parabola"
    hole = True
    named = False
    dx, dy = 5, 3
