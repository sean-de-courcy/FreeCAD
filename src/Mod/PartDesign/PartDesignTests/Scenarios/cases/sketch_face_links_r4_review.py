# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r4 (class E, E1; ops#264 e2): a face link's projected geometry after edits aimed
at the pairing's switch points: geometry with no source name (a face without an element map)
under a count change, a hole loop moved by its width, rounded corners, a thin channel moved by
its wall. Every model is designed geometry; the expectation is where the constraint must be on
the edited model."""

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6


def onLine(g, axis, value, span):
    """Whether g is a line on axis = value spanning span (lo, hi) in the other coordinate."""
    if not hasattr(g, "StartPoint") or hasattr(g, "Radius"):
        return False
    other = "y" if axis == "x" else "x"
    ends = (g.StartPoint, g.EndPoint)
    if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
        return False
    lo, hi = sorted(getattr(p, other) for p in ends)
    return abs(lo - span[0]) < TOL and abs(hi - span[1]) < TOL


def geoIdOf(sketch, match):
    found = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and match(g)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected geometries match")
    return found[0]


class CircleOnLine(Outcome):
    """The sketch computes, its PointOnObject constraint names the projected line `before()`
    before the edit and `after()` after it, and the circle's centre lies on that line."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        if not consumer.isValid():
            return False, consumer.getStatusString()
        line = self.before() if scenario.stepName is None else self.after()
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        held = consumer.ExternalGeo[-constraint.Second - 1]
        if not onLine(held, *line):
            return False, f"the constraint is on {held.StartPoint} - {held.EndPoint}"
        centre = consumer.Geometry[constraint.First].Center
        if centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class ReviewR4FaceLink(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r4"
    TIER = "F"
    AXES = ("M8", "E5")
    SIZE = 40
    SCALE = 1.0
    REFS = ("circle_on_line",)
    height = 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def constrain(self, doc, target):
        """The sketch at z = 0 projecting target's top face, a circle r 1 on the line
        `before()` at `circleAt()`."""
        sketch = doc.addObject("Sketcher::SketchObject", "OnTop")
        if getattr(self, "body", None) is not None:
            self.body.addObject(sketch)
        sketch.addExternal(target.Name, self.names(target, self.topFace())[0])
        doc.recompute()
        line = geoIdOf(sketch, lambda g: onLine(g, *self.before()))
        circle = sketch.addGeometry(m.circle(*self.circleAt(), self.s(1)), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, self.s(1)))
        self.ref("circle_on_line", sketch, "ExternalGeometry", self.topFace,
                 CircleOnLine(self.before, self.afterEdit))

    def moveGeometry(self, sketch, dx):
        """Every geometry of the sketch moved dx along x (unscaled), keeping its geometry ID."""
        d = V(self.s(dx), 0, 0)
        geometry = sketch.Geometry
        for g in geometry:
            if hasattr(g, "Radius"):
                g.Center = g.Center + d
            else:
                s, e = g.StartPoint + d, g.EndPoint + d
                g.StartPoint = V(*self.s(-777, -777), 0)
                g.EndPoint = e
                g.StartPoint = s
        sketch.Geometry = geometry


# ---- a face without an element map: no source names -------------------------------------------


class ReviewUnmappedFaceCornerCutMovedByWidth(ReviewR4FaceLink):
    """A Part::Feature whose shape is a planar face (no element map, so its projected geometry
    has no source name, now or later: an imported face), the 20 x 20 square at z = 10; the circle
    on its right line x = 20. In one edit the face is moved 20 to the right and its back-left
    corner cut 5 x 5, its wire starting at the same corner: the old right line's place now holds
    the left line (x = 20, 0..15), and the count changes, so position says nothing. Place alone
    pairs the slide. Right: the circle on the right line, x = 40."""

    AXES = ("M8", "E1", "E5")

    def square(self, points):
        s = self.s
        wire = Part.makePolygon([V(*s(*p), s(self.height)) for p in points + [points[0]]])
        return Part.Face(wire)

    def before(self):
        return ("x", self.s(20), self.s(0, 20))

    def circleAt(self):
        return self.s(20, 5)

    def afterEdit(self):
        return ("x", self.s(40), self.s(0, 20))

    def build(self, doc):
        self.body = None
        self.target = m.feature(doc, "Plate", self.square([(0, 0), (20, 0), (20, 20), (0, 20)]))
        doc.recompute()
        self.constrain(doc, self.target)

    def edit(self, doc):
        self.target.Shape = self.square([(20, 0), (40, 0), (40, 20), (25, 20), (20, 15)])


class ReviewUnmappedFaceMovedByWidth(ReviewUnmappedFaceCornerCutMovedByWidth):
    """The control: the same face moved 20 to the right, no corner cut (the count is unchanged,
    so position votes for geometry without a name). Right: x = 40."""

    AXES = ("M8", "E5")

    def edit(self, doc):
        self.target.Shape = self.square([(20, 0), (40, 0), (40, 20), (20, 20)])


class ReviewUnmappedFaceCornerCut(ReviewUnmappedFaceCornerCutMovedByWidth):
    """The control: the back-left corner cut in place (nothing slides). Right: x = 20."""

    AXES = ("M8", "E1")

    def afterEdit(self):
        return ("x", self.s(20), self.s(0, 20))

    def edit(self, doc):
        self.target.Shape = self.square([(0, 0), (20, 0), (20, 20), (5, 20), (0, 15)])


# ---- PartDesign models ---------------------------------------------------------------------------


class PadCase(ReviewR4FaceLink):
    abstract = True
    profile = ()

    def profileGeometry(self):
        return m.polygon([self.s(*p) for p in self.profile])

    def extra(self, doc, body):
        pass

    def build(self, doc):
        self.body = body = m.body(doc)
        m.sketch(doc, "Profile", self.profileGeometry(), body)
        self.pad = m.pad(body, doc.Profile, self.s(self.height))
        self.extra(doc, body)
        doc.recompute()
        self.constrain(doc, body.Tip)


class ReviewHoleLoopMovedByWidth(PadCase):
    """A 40 x 20 plate with a 10 x 10 square hole (5..15, 5..15) pocketed through; the circle on
    the hole's right wall x = 15. The hole's sketch moved 10 to the right (its lines keep their
    IDs): its left wall lands on the old right wall's place. The count is unchanged. Right: the
    hole's right wall, x = 25 (5..15)."""

    profile = [(0, 0), (40, 0), (40, 20), (0, 20)]

    def extra(self, doc, body):
        s = self.s
        hole = m.sketch(doc, "Hole", m.rectangle(*s(5, 5, 15, 15)), body, z=s(self.height))
        m.pocketThroughAll(body, hole)

    def before(self):
        return ("x", self.s(15), self.s(5, 15))

    def circleAt(self):
        return self.s(15, 10)

    def afterEdit(self):
        return ("x", self.s(25), self.s(5, 15))

    def edit(self, doc):
        self.moveGeometry(doc.Hole, 10)


class ReviewHoleLoopMovedByWidthCornerCut(ReviewHoleLoopMovedByWidth):
    """The same with the plate's back-right corner cut 5 x 5 in the same edit (the count
    changes). Right: x = 25 (5..15)."""

    AXES = ("M8", "E1", "E5")

    def edit(self, doc):
        super().edit(doc)
        s = self.s
        geometry = doc.Profile.Geometry
        for index, (a, b) in {1: ((40, 0), (40, 15)), 2: ((35, 20), (0, 20))}.items():
            line = geometry[index]
            line.StartPoint = V(*s(-777, -777), 0)
            line.EndPoint = V(*s(*b), 0)
            line.StartPoint = V(*s(*a), 0)
        doc.Profile.Geometry = geometry
        doc.Profile.addGeometry(m.polyline([s(40, 15), s(35, 20)]), False)


class ReviewRoundedSquareMovedByWidth(PadCase):
    """A 20 x 20 square with its corners rounded r 2 (four lines and four arcs); the circle on
    the right line x = 20 (2..18). The profile moved 20 to the right, every geometry keeping its
    ID: the left line lands on the old right line's place. Right: x = 40 (2..18)."""

    def profileGeometry(self):
        s = self.s
        r = s(2)
        lines = [((2, 0), (18, 0)), ((20, 2), (20, 18)), ((18, 20), (2, 20)), ((0, 18), (0, 2))]
        arcs = [((18, 2), -90, 0), ((18, 18), 0, 90), ((2, 18), 90, 180), ((2, 2), 180, 270)]
        geometry = []
        for (a, b), (c, d0, d1) in zip(lines, arcs):
            geometry.append(Part.LineSegment(V(*s(*a), 0), V(*s(*b), 0)))
            circle = Part.Circle(V(*s(*c), 0), V(0, 0, 1), r)
            geometry.append(Part.ArcOfCircle(circle, d0 * 3.141592653589793 / 180,
                                             d1 * 3.141592653589793 / 180))
        return geometry

    def before(self):
        return ("x", self.s(20), self.s(2, 18))

    def circleAt(self):
        return self.s(20, 5)

    def afterEdit(self):
        return ("x", self.s(40), self.s(2, 18))

    def edit(self, doc):
        self.moveGeometry(doc.Profile, 20)


class ReviewThinChannelMovedByWall(PadCase):
    """A U channel 20 wide and 15 high with 1 mm walls; the circle on the outer left wall x = 0
    (0..15). The profile moved 1 to the right (its wall), its lines keeping their IDs: the outer
    left wall lands on the old inner left wall's place, the inner right wall on the old outer
    right wall's. Right: x = 1 (0..15)."""

    SIZE = 21
    profile = [(0, 0), (20, 0), (20, 15), (19, 15), (19, 1), (1, 1), (1, 15), (0, 15)]

    def before(self):
        return ("x", self.s(0), self.s(0, 15))

    def circleAt(self):
        return self.s(0, 5)

    def afterEdit(self):
        return ("x", self.s(1), self.s(0, 15))

    def edit(self, doc):
        self.moveGeometry(doc.Profile, 1)


# ---- a body on a history-less base feature: index-borrowed source names (IDX) ------------------


class ReviewBaseFeatureCornerCutMovedByWidth(ReviewUnmappedFaceCornerCutMovedByWidth):
    """The same edit on a PartDesign body whose BaseFeature is a Part::Feature solid (the square
    face extruded 10, no element map: an imported part); the sketch projects the body's top face,
    whose edges are named by the base's edge indexes (`Edge7;...;IDX,SRC`). In one edit the base
    solid is moved 20 to the right and its back-left corner cut 5 x 5 (its edges re-indexed).
    Right: the circle on the right line, x = 40."""

    def solid(self, points):
        s = self.s
        wire = Part.makePolygon([V(*s(*p), 0) for p in points + [points[0]]])
        prism = Part.Face(wire).extrude(V(0, 0, s(self.height)))
        # the top face first, so its index (Face1) holds through the count change: the face
        # reference stays on it, and only the pairing of its geometry is judged
        top = max(prism.Faces, key=lambda f: f.CenterOfMass.z)
        faces = [top] + [f for f in prism.Faces if not f.isSame(top)]
        return Part.Solid(Part.Shell(faces))

    def build(self, doc):
        self.base = m.feature(doc, "Base", self.solid([(0, 0), (20, 0), (20, 20), (0, 20)]))
        self.body = body = m.body(doc)
        body.BaseFeature = self.base
        doc.recompute()
        self.constrain(doc, body.Tip)

    def edit(self, doc):
        self.base.Shape = self.solid([(20, 0), (40, 0), (40, 20), (25, 20), (20, 15)])


class ReviewBaseFeatureMovedByWidth(ReviewBaseFeatureCornerCutMovedByWidth):
    """The control: the base solid moved 20 to the right, no corner cut. Right: x = 40."""

    AXES = ("M8", "E5")

    def edit(self, doc):
        self.base.Shape = self.solid([(20, 0), (40, 0), (40, 20), (20, 20)])


class ReviewBaseFeatureCornerCut(ReviewBaseFeatureCornerCutMovedByWidth):
    """The control: the base solid's back-left corner cut in place. Right: x = 20."""

    AXES = ("M8", "E1")

    def afterEdit(self):
        return ("x", self.s(20), self.s(0, 20))

    def edit(self, doc):
        self.base.Shape = self.solid([(0, 0), (20, 0), (20, 20), (5, 20), (0, 15)])
