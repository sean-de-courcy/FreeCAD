# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr384-r3 (class E, E1; ops#264 e2): a face link's projected lines where the
unchanged-list stage can't run (a step's wall turns round, or the face gains an edge) and the
place stage then sees an edge sitting on another edge's old place.

Every edit is a plain move of the profile's lines (they keep their geometry IDs; added lines are
appended), so the face resolves by history. The reference judged is the sketch's face link; its
outcome is where the circle is (the line its PointOnObject constraint names, spanning the
expected range, and the circle's centre on it)."""

import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

TOL = 1e-6


def lineOn(sketch, axis, value, span):
    """The GeoId of the sketch's one projected line on axis = value spanning span (lo, hi)."""
    other = "y" if axis == "x" else "x"
    found = []
    for i, g in enumerate(sketch.ExternalGeo):
        if i < 2 or not hasattr(g, "StartPoint"):
            continue
        ends = (g.StartPoint, g.EndPoint)
        if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
            continue
        lo, hi = sorted(getattr(p, other) for p in ends)
        if abs(lo - span[0]) > TOL or abs(hi - span[1]) > TOL:
            continue
        found.append(-i - 1)
    if len(found) != 1:
        raise AssertionError(f"{len(found)} projected lines on {axis} = {value} over {span}")
    return found[0]


class CircleOnLine(Outcome):
    """The sketch computes, its PointOnObject constraint names the projected line on axis =
    value (`on` before the edit, `after` after it) spanning `span` (lo, hi) in the other
    coordinate, and the circle's centre lies on that line's axis value."""

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


class FaceLinkR3(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r3"
    TIER = "F"
    AXES = ("M8", "E5")
    SIZE = 40
    SCALE = 1.0
    height = 10

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, self.s(self.height)))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.polygon(self.profileLines()), body)
        pad = m.pad(body, profile, self.s(self.height))
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        axis, value, span = self.before()
        line = lineOn(sketch, axis, value, span)
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


# The Z profile: front (0,0)-(10,0), step wall x = 10 (0..5), step y = 5 (10..20), right
# x = 20 (5..10), back y = 10, left x = 0. Six lines, padded 10.
def zProfile(s):
    return [s(0, 0), s(10, 0), s(10, 5), s(20, 5), s(20, 10), s(0, 10)]


class ExternalFaceStepTurnedMovedByWidth(FaceLinkR3):
    """The Z profile; a circle on the right line x = 20 (5..10) at (20, 7.5). Composed edit (two
    dimensions, one recompute): the profile moves 20 to the right (x 20..40) and its step goes
    down instead of up (the step wall x = 30 now runs 0..-5, the step y = -5). The step wall
    turns round, so the face's ends no longer agree with the old ones and the whole-list
    position stage doesn't run; the left line (x = 20) now lies on the old right line's place.
    Right: the circle on the right line x = 40 (-5..10)."""

    REFS = ("circle_on_right",)

    def profileLines(self):
        return zProfile(self.s)

    def circleAt(self):
        return self.s(20, 7.5)

    def before(self):
        return ("x", self.s(20), self.s(5, 10))

    def afterEdit(self):
        return ("x", self.s(40), self.s(-5, 10))

    def edit(self, doc):
        s = self.s
        m.setLines(
            doc.Profile,
            {
                0: (s(20, 0), s(30, 0)),
                1: (s(30, 0), s(30, -5)),
                2: (s(30, -5), s(40, -5)),
                3: (s(40, -5), s(40, 10)),
                4: (s(40, 10), s(20, 10)),
                5: (s(20, 10), s(20, 0)),
            },
        )


class ExternalFaceStepTurned(FaceLinkR3):
    """The Z profile; a circle on the step y = 5 (10..20) at (15, 5). Edit (a dimension): the
    step goes down instead of up (wall x = 10 runs 0..-5, the step at y = -5), nothing else
    moves. Right: the circle on the step, y = -5 (10..20): the same sketch line, moved."""

    REFS = ("circle_on_step",)

    def profileLines(self):
        return zProfile(self.s)

    def circleAt(self):
        return self.s(15, 5)

    def before(self):
        return ("y", self.s(5), self.s(10, 20))

    def afterEdit(self):
        return ("y", self.s(-5), self.s(10, 20))

    def edit(self, doc):
        s = self.s
        m.setLines(
            doc.Profile,
            {
                1: (s(10, 0), s(10, -5)),
                2: (s(10, -5), s(20, -5)),
                3: (s(20, -5), s(20, 10)),
            },
        )


class ExternalFaceStepTurnedWall(ExternalFaceStepTurned):
    """The same edit, the circle on the step wall x = 10 (0..5) at (10, 2.5). Right: the wall,
    x = 10 (-5..0)."""

    REFS = ("circle_on_wall",)

    def circleAt(self):
        return self.s(10, 2.5)

    def before(self):
        return ("x", self.s(10), self.s(0, 5))

    def afterEdit(self):
        return ("x", self.s(10), self.s(-5, 0))


class ExternalFaceCornerCutMovedByWidth(FaceLinkR3):
    """The 20 x 20 square (front, right x = 20, back, left x = 0); a circle on the right line at
    (20, 5). Composed edit: the square moves 20 to the right (x 20..40) and its front-left corner
    is cut (a line (20, 5) - (25, 0) appended to the profile). The face gains an edge, so the
    whole-list stage doesn't run; the left line (x = 20, 5..20) lies on the old right line's
    place. Right: the circle on the right line x = 40 (0..20)."""

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
                0: (s(25, 0), s(40, 0)),
                1: (s(40, 0), s(40, 20)),
                2: (s(40, 20), s(20, 20)),
                3: (s(20, 20), s(20, 5)),
            },
        )
        doc.Profile.addGeometry(m.polyline([s(20, 5), s(25, 0)]), False)


class ExternalFaceCornerCutMovedByWidthBackRight(ExternalFaceCornerCutMovedByWidth):
    """The same move, the cut at the back-right corner instead (the right line (40, 0) - (40, 15),
    the back line (35, 20) - (20, 20), a line (40, 15) - (35, 20) appended). Right: the circle on
    x = 40 (0..15)."""

    def afterEdit(self):
        return ("x", self.s(40), self.s(0, 15))

    def edit(self, doc):
        s = self.s
        m.setLines(
            doc.Profile,
            {
                0: (s(20, 0), s(40, 0)),
                1: (s(40, 0), s(40, 15)),
                2: (s(35, 20), s(20, 20)),
                3: (s(20, 20), s(20, 0)),
            },
        )
        doc.Profile.addGeometry(m.polyline([s(40, 15), s(35, 20)]), False)


class ExternalFaceCornerCutWidened(ExternalFaceCornerCutMovedByWidth):
    """The 20 x 20 square, the circle on the right line at (20, 5). Composed edit: the square is
    widened to 30 (the right line moves to x = 30, keeping its ID) and its front-left corner cut
    (a line (0, 5) - (5, 0) appended). The face gains an edge and the right line has moved, so
    neither the place nor the position stage pairs it, though its source edge's name is the same.
    Right: the circle on the right line x = 30 (0..20)."""

    def afterEdit(self):
        return ("x", self.s(30), self.s(0, 20))

    def edit(self, doc):
        s = self.s
        m.setLines(
            doc.Profile,
            {
                0: (s(5, 0), s(30, 0)),
                1: (s(30, 0), s(30, 20)),
                2: (s(30, 20), s(0, 20)),
                3: (s(0, 20), s(0, 5)),
            },
        )
        doc.Profile.addGeometry(m.polyline([s(0, 5), s(5, 0)]), False)
