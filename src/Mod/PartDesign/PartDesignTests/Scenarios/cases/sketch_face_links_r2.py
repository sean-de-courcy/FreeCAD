# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r2 (class E, E1; ops#264 e2): a face link's projected lines after a move of
the profile that puts one edge exactly where another edge of the same face was.

`pairGeometries()` pairs by place before position: a new line on the same supporting line as an
old one, overlapping it, takes its Id. When the profile (or a part of it) moves by its own
width, the edge on the leading side moves away and the trailing edge lands on its old place, so
the place pairs the old leading edge with the new trailing one, and a constraint on the
leading edge goes to the trailing edge. The edit is a plain move: every line keeps its geometry
ID, the face resolves by history, the face's edge order is unchanged.

The reference judged is the sketch's face link; its outcome is where the circle is (the line its
PointOnObject constraint names, and the circle's centre on it)."""

import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

TOL = 1e-6


def lineOn(sketch, axis, value, between=None):
    """The GeoId of the sketch's one projected line on axis = value (with `between`, (axis2, lo,
    hi), only a line whose other coordinate spans lo..hi)."""
    found = []
    for i, g in enumerate(sketch.ExternalGeo):
        if i < 2 or not hasattr(g, "StartPoint"):
            continue
        if abs(getattr(g.StartPoint, axis) - value) > TOL:
            continue
        if abs(getattr(g.EndPoint, axis) - value) > TOL:
            continue
        found.append(-i - 1)
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected lines on {axis} = {value}")
    return found[0]


class CircleOnLine(Outcome):
    """The sketch computes, its PointOnObject constraint names the projected line on axis =
    value (`on` before the edit, `after` after it) spanning `span` (lo, hi) in the other
    coordinate, and the circle's centre lies on it."""

    def __init__(self, on, after):
        self.on, self.after = on, after

    def compare(self, scenario, consumer, target, expectation):
        axis, value, span = self.on() if scenario.stepName is None else self.after()
        other = "y" if axis == "x" else "x"
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        line = consumer.ExternalGeo[-constraint.Second - 1]
        ends = (line.StartPoint, line.EndPoint)
        if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
            return False, f"the constraint is on the projected line {ends[0]} - {ends[1]}"
        lo, hi = sorted(getattr(p, other) for p in ends)
        if abs(lo - span[0]) > TOL or abs(hi - span[1]) > TOL:
            return False, f"the constraint is on the projected line {ends[0]} - {ends[1]}"
        centre = consumer.Geometry[constraint.First].Center
        if abs(getattr(centre, axis) - value) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class MovedFaceLink(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r2"
    TIER = "F"
    AXES = ("M8", "E5")
    height = 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def profileLines(self):
        raise NotImplementedError

    def circleAt(self):
        raise NotImplementedError

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.polygon(self.profileLines()), body)
        pad = m.pad(body, profile, self.s(self.height))
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        axis, value, _ = self.before()
        line = lineOn(sketch, axis, value)
        circle = sketch.addGeometry(m.circle(*self.circleAt(), self.s(1)), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, self.s(1)))
        self.ref(
            self.REFS[0],
            sketch,
            "ExternalGeometry",
            self.topFace,
            CircleOnLine(self.before, self.afterEdit),
        )


class ExternalFaceMovedByWidth(MovedFaceLink):
    """The 20 x 20 square (lines front, right x = 20, back, left x = 0) padded 10 high; a sketch
    at z = 0 projects the pad's top face, a circle r 1 on the right line at (20, 5). Edit: the
    square's four lines moved 20 to the right (x 20..40), keeping their IDs. The face's right
    edge is now at x = 40; its left edge lands on the old right line's place, x = 20.
    Right: the circle on x = 40. Place pairing puts it on the left edge, x = 20, silently."""

    SIZE = 40
    SCALE = 1.0
    REFS = ("circle_on_right",)

    def profileLines(self):
        return [self.s(0, 0), self.s(20, 0), self.s(20, 20), self.s(0, 20)]

    def circleAt(self):
        return self.s(20, 5)

    def before(self):
        return ("x", self.s(20), self.s(0, 20))

    def afterEdit(self):
        return ("x", self.s(40), self.s(0, 20))

    def edit(self, doc):
        s = self.s
        m.setLines(
            doc.Profile,
            {
                0: (s(20, 0), s(40, 0)),
                1: (s(40, 0), s(40, 20)),
                2: (s(40, 20), s(20, 20)),
                3: (s(20, 20), s(20, 0)),
            },
        )


class ExternalFaceMovedByWidthLeft(ExternalFaceMovedByWidth):
    """The same move, the circle on the left line (0, 5): right is x = 20, the left edge. The
    old left line has no counterpart by place (its place is empty), and the new left line was
    taken by the old right one."""

    REFS = ("circle_on_left",)

    def circleAt(self):
        return self.s(0, 5)

    def before(self):
        return ("x", self.s(0), self.s(0, 20))

    def afterEdit(self):
        return ("x", self.s(20), self.s(0, 20))


class ExternalFaceSlotMovedByWidth(MovedFaceLink):
    """A dimension edit: a U profile 40 x 20 with a slot 10 wide and 10 deep in its back edge,
    walls at x = 10 and 20, padded 10 high; a sketch projects the top face, a circle on the
    slot's right wall (20, 15). Edit: the slot's offset changes from 10 to 20 (walls at 20 and
    30), the lines keeping their IDs. Right: the circle on the slot's right wall, x = 30. Place
    pairing puts it on the slot's left wall, which is now at x = 20."""

    SIZE = 40
    SCALE = 1.0
    REFS = ("circle_on_slot_right_wall",)

    def profileLines(self):
        return [
            self.s(0, 0), self.s(40, 0), self.s(40, 20), self.s(20, 20),
            self.s(20, 10), self.s(10, 10), self.s(10, 20), self.s(0, 20),
        ]

    def circleAt(self):
        return self.s(20, 15)

    def before(self):
        return ("x", self.s(20), self.s(10, 20))

    def afterEdit(self):
        return ("x", self.s(30), self.s(10, 20))

    def edit(self, doc):
        s = self.s
        m.setLines(
            doc.Profile,
            {
                2: (s(40, 20), s(30, 20)),
                3: (s(30, 20), s(30, 10)),
                4: (s(30, 10), s(20, 10)),
                5: (s(20, 10), s(20, 20)),
                6: (s(20, 20), s(0, 20)),
            },
        )


class ExternalFaceMovedPartWidth(ExternalFaceMovedByWidth):
    """The square moved by 15, less than its width (x 15..35): no edge lands on another's
    place; the control. Right: the circle on x = 35."""

    REFS = ("circle_on_right",)

    def afterEdit(self):
        return ("x", self.s(35), self.s(0, 20))

    def edit(self, doc):
        s = self.s
        m.setLines(
            doc.Profile,
            {
                0: (s(15, 0), s(35, 0)),
                1: (s(35, 0), s(35, 20)),
                2: (s(35, 20), s(15, 20)),
                3: (s(15, 20), s(15, 0)),
            },
        )
