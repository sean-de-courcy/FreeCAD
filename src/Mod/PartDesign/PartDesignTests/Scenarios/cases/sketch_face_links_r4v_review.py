# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r4v (class E, E1): one edit that removes an edge between two kept sides of a
projected face and adds one between two other kept sides (a corner cut or a fillet moved to
another corner). The four sides keep their names and lie on their lines; between their anchors
one arc of the face's loop empties while another fills, which round 4's batch rule reads as the
anchors' sides swapped.

Model: a 20 x 20 profile (scaled by `k`) padded 10 high; a sketch at z = 0 projects the top face
and has a circle (r 1) whose centre is on one projected side (PointOnObject, nothing else holding
it). Expected: the circle stays on that side's line."""

import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, edge, face
from PartDesignTests.Scenarios import models as m

TOL = 1e-6


def lineOn(sketch, axis, value):
    found = [
        -i - 1
        for i, g in enumerate(sketch.ExternalGeo)
        if i >= 2
        and hasattr(g, "StartPoint")
        and abs(getattr(g.StartPoint, axis) - value) < TOL
        and abs(getattr(g.EndPoint, axis) - value) < TOL
    ]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected lines on {axis} = {value}")
    return found[0]


class CircleOnLine(Outcome):
    """The sketch computes, its PointOnObject constraint names a projected line on axis = value,
    and the circle's centre lies on it."""

    def __init__(self, axis, value):
        self.axis, self.value = axis, value

    def compare(self, scenario, consumer, target, expectation):
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        line = consumer.ExternalGeo[-constraint.Second - 1]
        if not hasattr(line, "StartPoint"):
            return False, f"the constraint is on {line}"
        ends = (line.StartPoint, line.EndPoint)
        if not all(abs(getattr(p, self.axis) - self.value) < TOL for p in ends):
            return False, f"the constraint is on the projected line {ends[0]} - {ends[1]}"
        centre = consumer.Geometry[constraint.First].Center
        if abs(getattr(centre, self.axis) - self.value) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class CutMoved(Scenario):
    """A corner cut (5 x 5) at (20, 20) moves to the corner (0, 0); every line keeps its Id
    (geometry 2 is the cut). The left side (x = 0) holds the circle."""

    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r4v"
    TIER = "F"
    AXES = ("M8", "E1", "E5")
    REFS = ("circle_on_side",)
    k = 1.0
    on = ("x", 0.0)

    def p(self, *xy):
        return tuple(v * self.k for v in xy)

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def profileGeometry(self):
        k = self.k
        return m.polygon([(0, 0), (20 * k, 0), (20 * k, 15 * k), (15 * k, 20 * k), (0, 20 * k)])

    def projected(self, doc, body):
        pad = m.pad(body, doc.Profile, 10)
        doc.recompute()
        return pad

    def build(self, doc):
        body = m.body(doc)
        m.sketch(doc, "Profile", self.profileGeometry(), body)
        target = self.projected(doc, body)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(target.Name, self.names(target, self.topFace())[0])
        doc.recompute()
        axis, value = self.on
        value *= self.k
        line = lineOn(sketch, axis, value)
        centre = (value, 10 * self.k) if axis == "x" else (10 * self.k, value)
        circle = sketch.addGeometry(m.circle(*centre, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace, CircleOnLine(axis, value))

    def edit(self, doc):
        p = self.p
        m.setLines(
            doc.Profile,
            {
                0: (p(5, 0), p(20, 0)),
                1: (p(20, 0), p(20, 20)),
                2: (p(0, 5), p(5, 0)),
                3: (p(20, 20), p(0, 20)),
                4: (p(0, 20), p(0, 5)),
            },
        )


class ReviewCutMovedToOppositeCorner(CutMoved):
    """The cut at (20, 20) moved to (0, 0), the circle on the left side."""


class ReviewCutMovedToOppositeCornerRight(CutMoved):
    """The same, the circle on the right side (x = 20)."""

    on = ("x", 20.0)


class ReviewCutMovedToOppositeCorner4m(CutMoved):
    """ReviewCutMovedToOppositeCorner at 4 m (k = 200)."""

    AXES = ("M8", "E1", "E5", "X4:4000")
    k = 200.0


class ReviewCutMovedToOppositeCorner60(CutMoved):
    """ReviewCutMovedToOppositeCorner at 60 mm (k = 3)."""

    AXES = ("M8", "E1", "E5", "X4:60")
    k = 3.0


class ReviewCutMovedToNextCorner(CutMoved):
    """The cut at (20, 20) slid to the corner (20, 0); the circle on the left side."""

    def edit(self, doc):
        p = self.p
        m.setLines(
            doc.Profile,
            {
                0: (p(0, 0), p(15, 0)),
                1: (p(20, 5), p(20, 20)),
                2: (p(15, 0), p(20, 5)),
                3: (p(20, 20), p(0, 20)),
                4: (p(0, 20), p(0, 0)),
            },
        )


class ReviewCutReplacedAtOppositeCorner(CutMoved):
    """The cut at (20, 20) deleted and a new one drawn at (0, 0) (a new Id); the circle on the
    left side."""

    def edit(self, doc):
        p = self.p
        m.setLines(
            doc.Profile,
            {
                0: (p(5, 0), p(20, 0)),
                1: (p(20, 0), p(20, 20)),
                3: (p(20, 20), p(0, 20)),
                4: (p(0, 20), p(0, 5)),
            },
        )
        doc.Profile.delGeometry(2)
        doc.Profile.addGeometry(m.polyline([p(0, 5), p(5, 0)]), False)


class ReviewFilletMovedToOppositeCorner(CutMoved):
    """A square 20 x 20 padded 10; a fillet r 3 on the vertical edge at (20, 20); the sketch
    projects the fillet's top face. The edit moves the fillet to the vertical edge at (0, 0) (its
    Base edited): one arc of the face's loop loses its fillet arc, another gains one."""

    def profileGeometry(self):
        return m.rectangle(0, 0, 20 * self.k, 20 * self.k)

    def corner(self, x, y):
        return edge("line", direction=Z, through=(x * self.k, y * self.k, 0))

    def projected(self, doc, body):
        pad = m.pad(body, doc.Profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, self.names(pad, self.corner(20, 20)))
        fillet.Radius = 3
        doc.recompute()
        return fillet

    def edit(self, doc):
        doc.Fillet.Base = (doc.Pad, self.names(doc.Pad, self.corner(0, 0)))


class ReviewFilletMovedToNextCorner(ReviewFilletMovedToOppositeCorner):
    """The fillet moved from (20, 20) to the neighbouring corner (20, 0)."""

    def edit(self, doc):
        doc.Fillet.Base = (doc.Pad, self.names(doc.Pad, self.corner(20, 0)))


class ReviewFilletAddedAtSecondCorner(ReviewFilletMovedToOppositeCorner):
    """Control: the fillet on (20, 20) extended to (0, 0) too (one arc fills, none empties)."""

    def edit(self, doc):
        doc.Fillet.Base = (
            doc.Pad,
            self.names(doc.Pad, self.corner(20, 20)) + self.names(doc.Pad, self.corner(0, 0)),
        )


# ---- round 4's swap check with the arcs it reads not empty ----------------------------------

import itertools

import FreeCAD as App

V = App.Vector


def matchesLine(g, spec):
    if not hasattr(g, "StartPoint"):
        return False
    axis, value, (lo, hi) = spec
    other = "y" if axis == "x" else "x"
    s, e = g.StartPoint, g.EndPoint
    if not all(abs(getattr(p, axis) - value) < TOL for p in (s, e)):
        return False
    a, b = sorted(getattr(p, other) for p in (s, e))
    return abs(a - lo) < TOL and abs(b - hi) < TOL


class HeldOn(Outcome):
    """The PointOnObject constraint names the projected line `before` before the edit and
    `after` after it, its circle's centre on it."""

    def __init__(self, before, after):
        self.before, self.after = before, after

    def compare(self, scenario, consumer, target, expectation):
        spec = self.before if scenario.stepName is None else self.after
        c = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        held = consumer.ExternalGeo[-c.Second - 1]
        if not matchesLine(held, spec):
            return False, f"the constraint is on {held}, not {spec}"
        centre = consumer.Geometry[c.First].Center
        if centre.distanceToLine(held.StartPoint, held.EndPoint - held.StartPoint) > TOL:
            return False, f"circle centre at {centre}"
        return True, ""


class ShiftedCut(Scenario):
    """Round 4s's Shifted family (the 20 x 20 square redrawn 20 to the left and 1 up, `keep`
    lines kept and moved, the others deleted and drawn again in `order`), with a 5 x 5 corner cut
    in one of the two arcs round 4's swap check reads: `cut = "old"`: the old profile has a cut at
    (0, 0) (between the left and front lines), deleted by the edit; `cut = "new"`: the new profile
    has one at its (0, 1) corner (between its front and right lines). Where the constraint is on
    the old left line the intent is the new left line (x = -20), never the new right line (x = 0,
    on the old left line's place, a different line)."""

    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r4v"
    TIER = "F"
    AXES = ("M8", "E2", "E5", "E3")
    REFS = ("circle_on_line",)
    keep = (0,)
    order = None
    on = "L"
    cut = "old"

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def before(self):
        if self.on == "L":
            return ("x", 0, (5, 20) if self.cut == "old" else (0, 20))
        return ("x", 20, (0, 20))

    def afterEdit(self):
        if self.on == "L":
            return ("x", -20, (1, 21))
        return ("x", 0, (4, 21) if self.cut == "new" else (1, 21))

    def build(self, doc):
        body = m.body(doc)
        if self.cut == "old":
            points = [(5, 0), (20, 0), (20, 20), (0, 20), (0, 5)]
        else:
            points = [(0, 0), (20, 0), (20, 20), (0, 20)]
        profile = m.sketch(doc, "Profile", m.polygon(points), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        spec = self.before()
        line = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and matchesLine(g, spec)][0]
        axis, value, (lo, hi) = spec
        centre = (value, (lo + hi) / 2)
        circle = sketch.addGeometry(m.circle(*centre, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 HeldOn(self.before(), self.afterEdit()))

    def edit(self, doc):
        if self.cut == "new":
            new = [((-3, 1), (-20, 1)), ((0, 4), (0, 21)), ((0, 21), (-20, 21)), ((-20, 21), (-20, 1))]
        else:
            new = [((0, 1), (-20, 1)), ((0, 1), (0, 21)), ((0, 21), (-20, 21)), ((-20, 21), (-20, 1))]
        gone = [i for i in range(4) if i not in self.keep]
        doc.Profile.delGeometries(gone + ([4] if self.cut == "old" else []))
        kept = {n: i for i, n in enumerate(self.keep)}
        geometry = doc.Profile.Geometry
        for n in self.keep:
            line = geometry[kept[n]]
            a, b = new[n]
            line.StartPoint = V(-777, -777, 0)
            line.EndPoint = V(*b, 0)
            line.StartPoint = V(*a, 0)
        doc.Profile.Geometry = geometry
        for i in self.order or gone:
            doc.Profile.addGeometry(m.polyline(list(new[i])), False)
        if self.cut == "new":
            doc.Profile.addGeometry(m.polyline([(-3, 1), (0, 4)]), False)


def _shiftedCuts():
    for cut in ("old", "new"):
        for keep in ((0,), (0, 2), (1,), (2,), (3,), ()):
            gone = [i for i in range(4) if i not in keep]
            for order in itertools.permutations(gone):
                for on in ("L", "R"):
                    name = "ReviewShiftedCut%s%sKeep%sDraw%sOn%s" % (
                        cut[0].upper(),
                        cut[1:],
                        "".join(map(str, keep)) or "None",
                        "".join(map(str, order)),
                        on,
                    )
                    globals()[name] = type(
                        name,
                        (ShiftedCut,),
                        {"keep": keep, "order": order, "on": on, "cut": cut, "__module__": __name__},
                    )


_shiftedCuts()


# ---- the face-side check on an edge that moves from the outer loop to a hole -----------------

import Part


class UnmappedSlotClosed(Scenario):
    """A Part::Feature whose shape is a planar face at z = 10 with no element map (no source
    names): a U, the 30 x 30 square with a 10 wide slot from the back down to y = 10 (walls x =
    10 and x = 20). The edit closes the slot's mouth: the face becomes the square with a 10 x 15
    hole (10..20 x 10..25). The slot's walls stay on their lines with the material on the same
    side, but they move from the outer loop (counter-clockwise) to the hole's loop (oriented
    counter-clockwise on its own, so its inside is the hole). The circle is on the left wall x =
    10; right: on the hole's left line x = 10."""

    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r4v"
    TIER = "F"
    AXES = ("M8", "E1", "E5")
    REFS = ("circle_on_line",)
    at = (10, 20)
    before = ("x", 10.0, (10.0, 30.0))
    after = ("x", 10.0, (10.0, 25.0))

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    @staticmethod
    def wire(points):
        return Part.makePolygon([V(x, y, 10) for x, y in points + [points[0]]])

    def uShape(self):
        return Part.Face(self.wire([(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10),
                                    (10, 30), (0, 30)]))

    def oShape(self):
        outer = self.wire([(0, 0), (30, 0), (30, 30), (0, 30)])
        hole = self.wire([(10, 10), (20, 10), (20, 25), (10, 25)])
        return Part.makeFace([outer, hole], "Part::FaceMakerBullseye")

    def build(self, doc):
        target = m.feature(doc, "Plate", self.uShape())
        doc.recompute()
        sketch = doc.addObject("Sketcher::SketchObject", "OnTop")
        sketch.addExternal(target.Name, self.names(target, self.topFace())[0])
        doc.recompute()
        spec = self.before
        line = [-i - 1 for i, g in enumerate(sketch.ExternalGeo) if i >= 2 and matchesLine(g, spec)][0]
        circle = sketch.addGeometry(m.circle(*self.at, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 HeldOn(self.before, self.after))

    def edit(self, doc):
        doc.Plate.Shape = self.oShape()


class ReviewUnmappedSlotClosedLeftWall(UnmappedSlotClosed):
    pass


class ReviewUnmappedSlotClosedFloor(UnmappedSlotClosed):
    """The same, the circle on the slot's floor y = 10 (on the hole's front line after)."""

    before = ("y", 10.0, (10.0, 20.0))
    after = ("y", 10.0, (10.0, 20.0))
    at = (15, 10)
