# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r4s (class E, E1; ops#264 e2): attacks on a face link's pairing aimed at what
round 4s changes: inner loops, replaced lines, a second link in the sketch (slot remapping),
perpendicular faces (no Source), arcs, slots, thin members.

Every model is designed geometry: a profile padded 10 high, a sketch at z = 0 projecting the
pad's top face (or the link the case names), and circles r 1 held by PointOnObject on one
projected geometry each. The reference judged is the sketch's ExternalGeometry; its outcome is
where each constraint is after the edit."""

import math

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Pieces, Scenario, X, Z, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6

SQUARE = [(0, 0), (20, 0), (20, 20), (0, 20)]


def matches(g, spec):
    """spec: ("x"|"y", value, (lo, hi)), ("ends", a, b), ("arc", centre, radius)."""
    if spec[0] == "arc":
        if not hasattr(g, "Radius") or not hasattr(g, "FirstParameter"):
            return False
        return g.Center.isEqual(V(*spec[1], 0), TOL) and abs(g.Radius - spec[2]) < TOL
    if not hasattr(g, "StartPoint"):
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


class Union(Pieces):
    """The elements of several predicates, for a sketch with several links."""

    def __init__(self, *predicates):
        self.predicates = predicates

    def select(self, shape):
        return [n for p in self.predicates for n in p.select(shape)]

    def __repr__(self):
        return f"union{self.predicates}"


class HeldBy(Outcome):
    """Each PointOnObject constraint (in the order they were added) names the projected geometry
    `before()[i]` before the edit and `after()[i]` after it, with its circle's centre on it."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        specs = self.before() if scenario.stepName is None else self.after()
        cons = [c for c in consumer.Constraints if c.Type == "PointOnObject"]
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
    FOUND_BY = "review pr384-r4s"
    TIER = "F"
    AXES = ("M8", "E5")
    SIZE = 40
    SCALE = 1.0
    REFS = ("circles_on_geometry",)
    height = 10
    sideFace = None  # x of the pad's right side face, where the link is to it

    def profileGeometry(self):
        s = self.s
        return m.polygon([s(*p) for p in SQUARE])

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def linkPredicates(self, pad):
        """The (predicate) of each link, in the order they are added."""
        return [self.topFace()]

    def linkExpectation(self):
        return self.topFace

    def expectation(self):
        return self.linkExpectation()

    def target(self, doc, body, pad):
        """The object whose face the sketch links."""
        return pad

    def sketchHost(self, doc, body):
        return body

    def build(self, doc):
        s = self.s
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", self.profileGeometry(), body)
        pad = m.pad(body, profile, s(self.height))
        doc.recompute()
        target = self.target(doc, body, pad)
        sketch = m.sketch(doc, "OnTop", [], self.sketchHost(doc, body))
        self.attach(sketch, target)
        for predicate in self.linkPredicates(pad):
            sketch.addExternal(target.Name, self.names(target, predicate)[0])
        doc.recompute()
        for spec in self.before():
            line = findExternal(sketch, spec)
            x, y = anchorPoint(spec)
            circle = sketch.addGeometry(m.circle(x, y, s(1)), False)
            sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
            sketch.addConstraint(Sketcher.Constraint("Radius", circle, s(1)))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.linkExpectation(),
                 HeldBy(self.before, self.afterEdit))

    def attach(self, sketch, target):
        pass

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


# ---- inner loops -----------------------------------------------------------------------------


class InnerSquareMixin:
    def profileGeometry(self):
        s = self.s
        outer = m.polygon([s(*p) for p in [(0, 0), (40, 0), (40, 40), (0, 40)]])
        inner = m.polygon([s(*p) for p in [(10, 10), (20, 10), (20, 20), (10, 20)]])
        return outer + inner

    def before(self):
        return [("x", self.s(10), self.s(10, 20))]

    def slideHole(self, doc):
        self.moveLines(
            doc,
            {
                4: ((20, 10), (30, 10)),
                5: ((30, 10), (30, 20)),
                6: ((30, 20), (20, 20)),
                7: ((20, 20), (20, 10)),
            },
        )


class ReviewHoleLineSlidByWidth(InnerSquareMixin, Review):
    """A 40 x 40 plate with a 10 x 10 square hole; a circle on the hole's left line (x = 10). The
    hole's four lines move +10 in x (its width), keeping their IDs: the left line lands on the old
    right line's place. Right: the left line is at x = 20."""

    AXES = ("M8", "E5", "E3")

    def afterEdit(self):
        return [("x", self.s(20), self.s(10, 20))]

    def edit(self, doc):
        self.slideHole(doc)


class ReviewHoleLineSlidByWidthCornerCut(InnerSquareMixin, Review):
    """The same with the plate's front-left corner cut 5 x 5 in the same edit (the count
    changes)."""

    AXES = ("M8", "E5", "E3", "E1")

    def afterEdit(self):
        return [("x", self.s(20), self.s(10, 20))]

    def edit(self, doc):
        self.slideHole(doc)
        self.moveLines(doc, {0: ((5, 0), (40, 0)), 3: ((0, 40), (0, 5))})
        self.addLines(doc, [(0, 5), (5, 0)])


class ReviewOuterLineHoleSlidCornerCut(InnerSquareMixin, Review):
    """The plate with a hole; a circle on the plate's left line x = 0; the hole slid its width
    and the front-left corner cut: the outer line stays x = 0 (5..40)."""

    AXES = ("M8", "E5", "E3", "E1")

    def before(self):
        return [("x", 0, self.s(0, 40))]

    def afterEdit(self):
        return [("x", 0, self.s(5, 40))]

    def edit(self, doc):
        self.slideHole(doc)
        self.moveLines(doc, {0: ((5, 0), (40, 0)), 3: ((0, 40), (0, 5))})
        self.addLines(doc, [(0, 5), (5, 0)])


# ---- a line replaced ---------------------------------------------------------------------------


class ReviewLeftReplacedAtOldRightPlace(Review):
    """The 20 x 20 square, a circle on the left line (x = 0). The square moves 20 to the left: the
    front, right and back lines move (the right line lands on x = 0, the left line's old place),
    and the left line is deleted and a new one drawn at x = -20 (a new ID). Right: the new left
    line, or a break; never the line at x = 0 (the old right line)."""

    AXES = ("M8", "E2", "E5")

    def before(self):
        return [("x", 0, self.s(0, 20))]

    def afterEdit(self):
        return [("x", self.s(-20), self.s(0, 20))]

    def edit(self, doc):
        doc.Profile.delGeometry(3)
        self.moveLines(
            doc,
            {0: ((0, 0), (-20, 0)), 1: ((0, 0), (0, 20)), 2: ((0, 20), (-20, 20))},
        )
        self.addLines(doc, [(-20, 20), (-20, 0)])


class ReviewCutRedrawnLeftInPlace(Review):
    """The left line deleted and a shorter one drawn at x = 0 from (0, 20) to (0, 5), the front line
    shortened and a chamfer added between (a new ID for the new left line: its ends differ). A
    circle on the left line: it stays on the line at x = 0 (5..20)."""

    AXES = ("M8", "E2", "E5", "E1")

    def before(self):
        return [("x", 0, self.s(0, 20))]

    def afterEdit(self):
        return [("x", 0, self.s(5, 20))]

    def edit(self, doc):
        doc.Profile.delGeometry(3)
        self.moveLines(doc, {0: ((5, 0), (20, 0))})
        self.addLines(doc, [(0, 20), (0, 5)])
        self.addLines(doc, [(0, 5), (5, 0)])


# ---- a second link ------------------------------------------------------------------------------


class TwoLinks(Review):
    """The 20 x 20 square; the sketch links the top face and the pad's bottom right edge
    (x = 20, z = 0); a circle on the face's left line (x = 0) and one on the edge's line (x = 20).
    The front-left corner is cut: the face gains a line before the constrained one. Both circles
    stay on their lines."""

    abstract = True
    AXES = ("M8", "E5", "E1")
    edgeFirst = False

    def edgeLink(self):
        return edge("line", direction=(0, 1, 0), through=self.s(20, 0, 0))

    def linkPredicates(self, pad):
        links = [self.topFace(), self.edgeLink()]
        return links[::-1] if self.edgeFirst else links

    def linkExpectation(self):
        return lambda: Union(self.topFace(), self.edgeLink())

    def before(self):
        return [("x", 0, self.s(0, 20)), ("x", self.s(20), self.s(0, 20))]

    def afterEdit(self):
        return [("x", 0, self.s(5, 20)), ("x", self.s(20), self.s(0, 20))]

    def edit(self, doc):
        self.moveLines(doc, {0: ((5, 0), (20, 0)), 3: ((0, 20), (0, 5))})
        self.addLines(doc, [(0, 5), (5, 0)])


class ReviewTwoLinksFaceFirstCut(TwoLinks):
    edgeFirst = False


class ReviewTwoLinksEdgeFirstCut(TwoLinks):
    edgeFirst = True


class TwoLinksOrderedByEdge(TwoLinks):
    """The constrained face line is the right one (x = 20) and the edge is the bottom left edge
    (x = 0, z = 0); the front-left corner is cut: the edge link's geometry is before or after the
    face's."""

    abstract = True

    def edgeLink(self):
        return edge("line", direction=(0, 1, 0), through=self.s(0, 0, 0))

    def before(self):
        return [("x", self.s(20), self.s(0, 20)), ("x", 0, self.s(0, 20))]

    def afterEdit(self):
        return [("x", self.s(20), self.s(0, 20)), ("x", 0, self.s(5, 20))]


class ReviewTwoLinksFaceFirstEdgeCutRight(TwoLinksOrderedByEdge):
    """The edge link's line x = 0 is the cut one: its edge is shortened (its name survives)."""

    edgeFirst = False


class ReviewTwoLinksEdgeFirstEdgeCutRight(TwoLinksOrderedByEdge):
    edgeFirst = True


# ---- a perpendicular face -----------------------------------------------------------------------


class SideLink(Review):
    """The sketch links the pad's right side face (x = 20), perpendicular to it: its projection is
    a line on x = 20 (a face with no source names). A circle on that line."""

    abstract = True
    AXES = ("M8", "E5", "E2")
    xr = 20

    def sideFace(self):
        return face("plane", normal=X, through=(self.s(self.xr), 0, 0))

    def linkPredicates(self, pad):
        return [self.sideFace()]

    def linkExpectation(self):
        return self.sideFace


class ReviewSideFaceWidened(SideLink):
    """The square widened to 30: the side face is at x = 30. The circle stays on its line."""

    def before(self):
        return [("x", self.s(20), self.s(0, 20))]

    def afterEdit(self):
        return [("x", self.s(30), self.s(0, 20))]

    def edit(self, doc):
        self.xr = 30
        self.moveLines(
            doc, {0: ((0, 0), (30, 0)), 1: ((30, 0), (30, 20)), 2: ((30, 20), (0, 20))}
        )


class ReviewSideFaceCornerCut(SideLink):
    """The back-right corner cut 5 x 5: the side face is still at x = 20, now 0..15."""

    def before(self):
        return [("x", self.s(20), self.s(0, 20))]

    def afterEdit(self):
        return [("x", self.s(20), self.s(0, 15))]

    def edit(self, doc):
        self.moveLines(doc, {1: ((20, 0), (20, 15)), 2: ((15, 20), (0, 20))})
        self.addLines(doc, [(20, 15), (15, 20)])


# ---- arcs ---------------------------------------------------------------------------------------


class RoundedCornerMixin:
    def profileGeometry(self):
        s = self.s
        arc = Part.ArcOfCircle(Part.Circle(V(*s(15, 5), 0), V(0, 0, 1), s(5)), -math.pi / 2, 0)
        return [
            Part.LineSegment(V(*s(0, 0), 0), V(*s(15, 0), 0)),
            arc,
            Part.LineSegment(V(*s(20, 5), 0), V(*s(20, 20), 0)),
            Part.LineSegment(V(*s(20, 20), 0), V(*s(0, 20), 0)),
            Part.LineSegment(V(*s(0, 20), 0), V(*s(0, 0), 0)),
        ]

    def widenRadius(self, doc):
        s = self.s
        geometry = doc.Profile.Geometry
        geometry[1].Center = V(*s(12, 8), 0)
        geometry[1].Radius = s(8)
        geometry[0].EndPoint = V(*s(12, 0), 0)
        geometry[2].StartPoint = V(*s(20, 8), 0)
        doc.Profile.Geometry = geometry


class ReviewArcRadiusChanged(RoundedCornerMixin, Review):
    """The front-right corner rounded (r 5); a circle on the arc; the radius becomes 8 (the arc's
    centre moves, its ID stays). The circle stays on the arc."""

    AXES = ("M8", "E5", "E6")

    def before(self):
        return [("arc", self.s(15, 5), self.s(5))]

    def afterEdit(self):
        return [("arc", self.s(12, 8), self.s(8))]

    def edit(self, doc):
        self.widenRadius(doc)


class ReviewArcRadiusChangedFrontLine(RoundedCornerMixin, Review):
    """The same, with the circle on the front line (y = 0, 0..15): 0..12 after."""

    AXES = ("M8", "E5", "E6")

    def before(self):
        return [("y", 0, self.s(0, 15))]

    def afterEdit(self):
        return [("y", 0, self.s(0, 12))]

    def edit(self, doc):
        self.widenRadius(doc)


class SlotMixin:
    """A slot: bottom line (10, 0)-(30, 0), the right arc (centre (30, 10), r 10), the top line
    (30, 20)-(10, 20) and the left arc (centre (10, 10))."""

    def profileGeometry(self):
        s = self.s
        circle = lambda x, y: Part.Circle(V(*s(x, y), 0), V(0, 0, 1), s(10))
        return [
            Part.LineSegment(V(*s(10, 0), 0), V(*s(30, 0), 0)),
            Part.ArcOfCircle(circle(30, 10), -math.pi / 2, math.pi / 2),
            Part.LineSegment(V(*s(30, 20), 0), V(*s(10, 20), 0)),
            Part.ArcOfCircle(circle(10, 10), math.pi / 2, 3 * math.pi / 2),
        ]

    def move(self, doc, dx):
        s = self.s
        geometry = doc.Profile.Geometry
        for i in (0, 2):
            a, b = geometry[i].StartPoint, geometry[i].EndPoint
            geometry[i].StartPoint = V(-777, -777, 0)
            geometry[i].EndPoint = V(b.x + s(dx), b.y, 0)
            geometry[i].StartPoint = V(a.x + s(dx), a.y, 0)
        for i in (1, 3):
            geometry[i].Center = V(geometry[i].Center.x + s(dx), geometry[i].Center.y, 0)
        doc.Profile.Geometry = geometry


class ReviewSlotMovedByLengthRightArc(SlotMixin, Review):
    """A slot moved +20 in x (the distance between its centres), IDs kept: the left arc lands on
    the old right arc's place. A circle on the right arc: its centre goes to (50, 10)."""

    AXES = ("M8", "E5", "E3")

    def before(self):
        return [("arc", self.s(30, 10), self.s(10))]

    def afterEdit(self):
        return [("arc", self.s(50, 10), self.s(10))]

    def edit(self, doc):
        self.move(doc, 20)


class ReviewSlotMovedByLengthLeftArc(SlotMixin, Review):
    """The same with the circle on the left arc: its centre goes to (30, 10)."""

    AXES = ("M8", "E5", "E3")

    def before(self):
        return [("arc", self.s(10, 10), self.s(10))]

    def afterEdit(self):
        return [("arc", self.s(30, 10), self.s(10))]

    def edit(self, doc):
        self.move(doc, 20)


class ReviewSlotMovedHalfLengthRightArc(SlotMixin, Review):
    """The slot moved +5: the arcs and lines overlap their old places but none coincides."""

    AXES = ("M8", "E5")

    def before(self):
        return [("arc", self.s(30, 10), self.s(10))]

    def afterEdit(self):
        return [("arc", self.s(35, 10), self.s(10))]

    def edit(self, doc):
        self.move(doc, 5)


# ---- a thin member ------------------------------------------------------------------------------


class ReviewThinWallMovedByWidthCut(Review):
    """A 2 x 40 wall (x 0..2, y 0..40); the circle on its right line (x = 2). The wall moves +2
    (the left line lands on the old right line) and its front-left corner is cut 1 x 1. Right: the
    right line is at x = 4."""

    AXES = ("M8", "E5", "E1", "X4")
    SIZE = 40

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in [(0, 0), (2, 0), (2, 40), (0, 40)]])

    def before(self):
        return [("x", self.s(2), self.s(0, 40))]

    def afterEdit(self):
        return [("x", self.s(4), self.s(0, 40))]

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def edit(self, doc):
        self.moveLines(
            doc,
            {
                0: ((3, 0), (4, 0)),
                1: ((4, 0), (4, 40)),
                2: ((4, 40), (2, 40)),
                3: ((2, 40), (2, 1)),
            },
        )
        self.addLines(doc, [(2, 1), (3, 0)])


# ---- where the sketch and the body are ------------------------------------------------------------


class ReviewSketchAttachedToTheLinkedFaceCut(Review):
    """The sketch is attached (FlatFace) to the top face it also projects; a circle on the left line.
    The front-left corner is cut."""

    AXES = ("M8", "E5", "E1")

    def attach(self, sketch, target):
        sketch.AttachmentSupport = [(target, self.names(target, self.topFace())[0])]
        sketch.MapMode = "FlatFace"

    def before(self):
        return [("x", 0, self.s(0, 20))]

    def afterEdit(self):
        return [("x", 0, self.s(5, 20))]

    def edit(self, doc):
        self.moveLines(doc, {0: ((5, 0), (20, 0)), 3: ((0, 20), (0, 5))})
        self.addLines(doc, [(0, 5), (5, 0)])


class ReviewBodyPlacedCornerCut(Review):
    """The body is turned 90 degrees about z and moved; the sketch is in the body, attached to
    nothing: its plane is the body's. A circle on the right line (x = 20 in the profile's frame);
    the front-right corner is cut. The projected lines are in the sketch's frame."""

    AXES = ("M8", "E5", "E1", "E7")

    def placement(self):
        return App.Placement(V(*self.s(7, 3, 0)), App.Rotation(V(0, 0, 1), 90))

    def sketchHost(self, doc, body):
        body.Placement = self.placement()
        return body

    def before(self):
        return [("x", self.s(20), self.s(0, 20))]

    def afterEdit(self):
        return [("x", self.s(20), self.s(5, 20))]

    def edit(self, doc):
        self.moveLines(doc, {0: ((0, 0), (15, 0)), 1: ((20, 5), (20, 20))})
        self.addLines(doc, [(15, 0), (20, 5)])


class ReviewOtherBodyLinkMovedBodyCornerCut(Review):
    """The sketch is outside the body and links its pad (the body is moved by (7, 3) and turned 90
    degrees: a profile point (x, y) is at (7 - y, 3 + x)); a circle on the right line (x = 20 in the
    profile: y = 23 here, x from -13 to 7); the front-right corner is cut."""

    AXES = ("M8", "E5", "E1", "E7")

    def sketchHost(self, doc, body):
        body.Placement = App.Placement(V(*self.s(7, 3, 0)), App.Rotation(V(0, 0, 1), 90))
        return None

    def before(self):
        return [("y", self.s(23), self.s(-13, 7))]

    def afterEdit(self):
        return [("y", self.s(23), self.s(-13, 2))]

    def edit(self, doc):
        self.moveLines(doc, {0: ((0, 0), (15, 0)), 1: ((20, 5), (20, 20))})
        self.addLines(doc, [(15, 0), (20, 5)])


# ---- a dress-up's face ---------------------------------------------------------------------------


class FilletedMixin:
    """The pad's back-right vertical edge (20, 20) filleted (r 3); the sketch links the fillet's
    top face: four lines and an arc. Fillet.Radius becomes 5."""

    def target(self, doc, body, pad):
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, edge("line", direction=Z, through=self.s(20, 20, 0))))
        fillet.Radius = self.s(3)
        doc.recompute()
        return fillet

    def edit(self, doc):
        doc.Fillet.Radius = self.s(5)


class ReviewFilletRadiusArc(FilletedMixin, Review):
    AXES = ("M8", "E6")

    def before(self):
        return [("arc", self.s(17, 17), self.s(3))]

    def afterEdit(self):
        return [("arc", self.s(15, 15), self.s(5))]


class ReviewFilletRadiusRightLine(FilletedMixin, Review):
    AXES = ("M8", "E6")

    def before(self):
        return [("x", self.s(20), self.s(0, 17))]

    def afterEdit(self):
        return [("x", self.s(20), self.s(0, 15))]


# ---- redrawn lines whose names are gone ------------------------------------------------------------


class Shifted(Review):
    """The 20 x 20 square redrawn 20 to the left and 1 up (the lines get no old line's ends, so no old
    ID): `keep` lines of the old profile are kept (moved, their IDs and names stay), the others are
    deleted and drawn again in their new places. The new right line is at x = 0, on the old left
    line's place (0..20 against 1..21). Where the constraint is on the old left line, the intent is
    the new left line (x = -20); never the new right line (an old place, a different line)."""

    abstract = True
    AXES = ("M8", "E2", "E5", "E3")
    keep = ()
    on = "L"
    order = None

    def before(self):
        return [("x", 0, self.s(0, 20))] if self.on == "L" else [("x", self.s(20), self.s(0, 20))]

    def afterEdit(self):
        return (
            [("x", self.s(-20), self.s(1, 21))]
            if self.on == "L"
            else [("x", 0, self.s(1, 21))]
        )

    def edit(self, doc):
        new = [((0, 1), (-20, 1)), ((0, 1), (0, 21)), ((0, 21), (-20, 21)), ((-20, 21), (-20, 1))]
        gone = [i for i in range(4) if i not in self.keep]
        doc.Profile.delGeometries(gone)
        kept = {n: i for n, i in zip(self.keep, range(len(self.keep)))}
        self.moveLines(doc, {kept[i]: new[i] for i in self.keep})
        for i in (self.order or gone):
            self.addLines(doc, list(new[i]))


class ReviewFrontKeptRestRedrawnLeft(Shifted):
    keep = (0,)
    on = "L"


class ReviewFrontKeptRestRedrawnRight(Shifted):
    keep = (0,)
    on = "R"


class ReviewAllRedrawnLeft(Shifted):
    keep = ()
    on = "L"


class ReviewAllRedrawnRight(Shifted):
    keep = ()
    on = "R"


class ReviewFrontAndBackKeptRestRedrawnLeft(Shifted):
    keep = (0, 2)
    on = "L"


class ReviewRightKeptRestRedrawnLeft(Shifted):
    keep = (1,)
    on = "L"


def _orders():
    import itertools

    for keep in ((0,), (0, 2), (1,), (2,), (3,), ()):
        gone = [i for i in range(4) if i not in keep]
        for order in itertools.permutations(gone):
            if list(order) == gone:
                continue
            for on in ("L", "R"):
                name = "ReviewShiftedKeep%sDraw%sOn%s" % (
                    "".join(map(str, keep)) or "None",
                    "".join(map(str, order)),
                    on,
                )
                globals()[name] = type(
                    name, (Shifted,), {"keep": keep, "order": order, "on": on, "__module__": __name__}
                )


_orders()


# ---- periodic profiles ---------------------------------------------------------------------------

COMB = [(0, 0), (30, 0), (30, 10), (25, 10), (25, 5), (20, 5), (20, 10), (15, 10), (15, 5),
        (10, 5), (10, 10), (5, 10), (5, 5), (0, 5)]


class Comb(Review):
    """A comb: base (0,0)-(30,0), crenellations with period 10 (tops y = 10 over [5,10], [15,20],
    [25,30]; floors y = 5). Slid +10 in x with every line keeping its ID (the edit is a drag of the
    whole profile). A circle on the middle tooth's top (y = 10, 15..20): it follows its line to
    25..30."""

    abstract = True
    AXES = ("M8", "E3", "E5")

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in COMB])

    def slide(self, doc, dx):
        lines = {}
        for i in range(len(COMB)):
            a, b = COMB[i], COMB[(i + 1) % len(COMB)]
            lines[i] = ((a[0] + dx, a[1]), (b[0] + dx, b[1]))
        self.moveLines(doc, lines)


class ReviewCombSlidByPeriodTop(Comb):
    def before(self):
        return [("y", self.s(10), self.s(15, 20))]

    def afterEdit(self):
        return [("y", self.s(10), self.s(25, 30))]

    def edit(self, doc):
        self.slide(doc, 10)


class ReviewCombSlidByPeriodWall(Comb):
    """The circle on the wall x = 15 (5..10) (the middle tooth's left wall): x = 25 after."""

    def before(self):
        return [("x", self.s(15), self.s(5, 10))]

    def afterEdit(self):
        return [("x", self.s(25), self.s(5, 10))]

    def edit(self, doc):
        self.slide(doc, 10)


class ReviewCombSlidByHalfPeriodTop(Comb):
    """Slid +5 (half a period: the tops land on the floors' places)."""

    def before(self):
        return [("y", self.s(10), self.s(15, 20))]

    def afterEdit(self):
        return [("y", self.s(10), self.s(20, 25))]

    def edit(self, doc):
        self.slide(doc, 5)


# ---- a rigid motion of the profile --------------------------------------------------------------


class Turned(Review):
    """The square's profile sketch turned about the square's centre (10, 10) by `degrees` (its
    Placement), every line keeping its ID. A circle on the right line (x = 20). A person who turned
    the part expects the circle to go with the line (its new place), or a break; a turn by 180
    leaves the square where it was with every line on another's place."""

    abstract = True
    AXES = ("M8", "E7", "E3")
    degrees = 180

    def before(self):
        return [("x", self.s(20), self.s(0, 20))]

    def turnedPoint(self, p):
        r = App.Rotation(V(0, 0, 1), self.degrees)
        c = V(*self.s(10, 10), 0)
        return r.multVec(V(*self.s(*p), 0) - c) + c

    def afterEdit(self):
        a, b = self.turnedPoint((20, 0)), self.turnedPoint((20, 20))
        return [("ends", (a.x, a.y), (b.x, b.y))]

    def edit(self, doc):
        c = V(*self.s(10, 10), 0)
        r = App.Rotation(V(0, 0, 1), self.degrees)
        doc.Profile.Placement = App.Placement(c - r.multVec(c), r)


class ReviewSquareTurned180(Turned):
    degrees = 180


class ReviewSquareTurned90(Turned):
    degrees = 90


class ReviewSquareTurned30(Turned):
    degrees = 30


# ---- across a save -------------------------------------------------------------------------------


class ReviewCutReopenedThenMovedByWidth(Review):
    """The square's front-left corner cut; the document saved, closed and opened again (the saved
    geometry's source names are read back); then the profile moved +20 in x (its Placement): the
    left line lands on the old right line's place. A circle on the right line (x = 20): x = 40
    after both steps (y 0..20)."""

    AXES = ("M8", "E1", "E7", "E9")
    steps = ("cut", "reopen", "move")

    def before(self):
        return [("x", self.s(20), self.s(0, 20))]

    def afterEdit(self):
        return [("x", self.s(20), self.s(0, 20))] if self.stepName in ("cut", "reopen") else [
            ("x", self.s(40), self.s(0, 20))
        ]

    def cut(self, doc):
        self.moveLines(doc, {0: ((5, 0), (20, 0)), 3: ((0, 20), (0, 5))})
        self.addLines(doc, [(0, 5), (5, 0)])

    def reopen(self, doc):
        import os
        import tempfile

        self.folder = tempfile.mkdtemp(prefix="NamingScenario")
        path = os.path.join(self.folder, doc.Name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        self.doc = self.openDocument(path)

    def move(self, doc):
        p = doc.Profile.Placement
        p.Base += V(self.s(20), 0, 0)
        doc.Profile.Placement = p

    def cleanup(self):
        import shutil

        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


# ---- a circle on every line ----------------------------------------------------------------------

SQUARE_LINES = [((0, 0), (20, 0)), ((20, 0), (20, 20)), ((20, 20), (0, 20)), ((0, 20), (0, 0))]


class AllFour(Review):
    """The 20 x 20 square, a circle on each of its four lines (front, right, back, left), each line
    keeping its ID through the edit `new` ({index: (start, end)}) plus the lines `added`: every
    circle must be on its own line's new place (or the sketch breaks)."""

    abstract = True
    AXES = ("M8", "E5", "E1")
    new = {}
    added = ()

    def before(self):
        return [("ends", a, b) for a, b in [tuple(self.s(*p) for p in l) for l in SQUARE_LINES]]

    def afterEdit(self):
        out = []
        for i, line in enumerate(SQUARE_LINES):
            a, b = self.new.get(i, line)
            out.append(("ends", self.s(*a), self.s(*b)))
        return out

    def edit(self, doc):
        self.moveLines(doc, self.new)
        for points in self.added:
            self.addLines(doc, list(points))


class ReviewAllFourCutFrontLeft(AllFour):
    new = {0: ((5, 0), (20, 0)), 3: ((0, 20), (0, 5))}
    added = (((0, 5), (5, 0)),)


class ReviewAllFourCutBackRightMovedByWidth(AllFour):
    new = {0: ((20, 0), (40, 0)), 1: ((40, 0), (40, 15)), 2: ((35, 20), (20, 20)),
           3: ((20, 20), (20, 0))}
    added = (((40, 15), (35, 20)),)


class ReviewAllFourCutFrontLeftMovedByWidth(AllFour):
    new = {0: ((25, 0), (40, 0)), 1: ((40, 0), (40, 20)), 2: ((40, 20), (20, 20)),
           3: ((20, 20), (20, 5))}
    added = (((20, 5), (25, 0)),)


class ReviewAllFourWidenedFromLeft(AllFour):
    """The square widened to the left (its left line goes to x = -10, the front and back stretch)."""

    new = {0: ((-10, 0), (20, 0)), 2: ((20, 20), (-10, 20)), 3: ((-10, 20), (-10, 0))}


class ReviewAllFourMovedByWidthOnly(AllFour):
    new = {0: ((20, 0), (40, 0)), 1: ((40, 0), (40, 20)), 2: ((40, 20), (20, 20)),
           3: ((20, 20), (20, 0))}


class ReviewAllFourCutAllCorners(AllFour):
    """Every corner cut 3 x 3: eight lines."""

    new = {0: ((3, 0), (17, 0)), 1: ((20, 3), (20, 17)), 2: ((17, 20), (3, 20)),
           3: ((0, 17), (0, 3))}
    added = (((17, 0), (20, 3)), ((20, 17), (17, 20)), ((3, 20), (0, 17)), ((0, 3), (3, 0)))


# ---- geometry saved before E1 (no source names) --------------------------------------------------
import os
import re
import tempfile
import zipfile


def reopenWithoutSources(scenario, doc):
    """The document saved, closed and opened again (scenario.openDocument()) with every external
    geometry's source name removed from its Document.xml: geometry as a build before ops#264 e2
    saved it (no `Source` attribute). Setting the facade's Source from Python doesn't reach the
    geometry a sketch holds, so a file is the only way to get it (the class E ruling, R9). The
    folder is scenario.folder (the scenario removes it). Returns the opened document."""
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
    # a build before E1 saves no source names: its file is already one
    if count == 0 and hasattr(Sketcher.ExternalGeometryFacade, "Source"):
        raise RuntimeError("no external geometry with a source name in the saved file")
    files["Document.xml"] = xml.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return scenario.openDocument(path)



class SavedBeforeE1:
    """The model saved, its source names removed from the file, and opened again before the edit
    (listed before the case's class)."""

    def edit(self, doc):
        self.doc = doc = reopenWithoutSources(self, doc)
        super().edit(doc)

    def cleanup(self):
        import shutil

        super().cleanup()
        shutil.rmtree(getattr(self, "folder", ""), ignore_errors=True)


class ReviewCombSlidByPeriodTopNoSource(SavedBeforeE1, ReviewCombSlidByPeriodTop):
    AXES = ("M8", "E3", "E5", "E9")


class ReviewSquareTurned90NoSource(SavedBeforeE1, ReviewSquareTurned90):
    AXES = ("M8", "E7", "E3", "E9")


class ReviewSquareTurned180NoSource(SavedBeforeE1, ReviewSquareTurned180):
    AXES = ("M8", "E7", "E3", "E9")


class ReviewFrontKeptRestRedrawnLeftNoSource(SavedBeforeE1, ReviewFrontKeptRestRedrawnLeft):
    AXES = ("M8", "E2", "E5", "E9")


class ReviewHoleLineSlidByWidthNoSource(SavedBeforeE1, ReviewHoleLineSlidByWidth):
    AXES = ("M8", "E3", "E5", "E9")


class ReviewHoleLineSlidByWidthCornerCutNoSource(SavedBeforeE1, ReviewHoleLineSlidByWidthCornerCut):
    AXES = ("M8", "E1", "E3", "E5", "E9")


class ReviewAllFourCutBackRightMovedByWidthNoSource(SavedBeforeE1, ReviewAllFourCutBackRightMovedByWidth):
    AXES = ("M8", "E1", "E5", "E9")


class ReviewAllFourCutAllCornersNoSource(SavedBeforeE1, ReviewAllFourCutAllCorners):
    AXES = ("M8", "E1", "E9")


class ReviewLeftReplacedAtOldRightPlaceNoSource(SavedBeforeE1, ReviewLeftReplacedAtOldRightPlace):
    AXES = ("M8", "E2", "E5", "E9")


class ReviewSlotMovedByLengthRightArcNoSource(SavedBeforeE1, ReviewSlotMovedByLengthRightArc):
    AXES = ("M8", "E3", "E5", "E9")


class ReviewArcRadiusChangedNoSource(SavedBeforeE1, ReviewArcRadiusChanged):
    AXES = ("M8", "E5", "E6", "E9")


class ReviewCutRedrawnLeftInPlaceNoSource(SavedBeforeE1, ReviewCutRedrawnLeftInPlace):
    AXES = ("M8", "E2", "E5", "E1", "E9")


class ReviewAllFourWidenedFromLeftNoSource(SavedBeforeE1, ReviewAllFourWidenedFromLeft):
    AXES = ("M8", "E5", "E9")


class ReviewAllFourMovedByWidthOnlyNoSource(SavedBeforeE1, ReviewAllFourMovedByWidthOnly):
    AXES = ("M8", "E5", "E9")


