# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases of fork PR 384, round 1 (class E, E1; ops#264 e2).

A 20 x 20 square (front y = 0, right x = 20, back y = 20, left x = 0) padded 10 high; a sketch at
z = 0 projects the pad's top face and has a circle r 1 whose centre is on one projected line
(PointOnObject, nothing else holding it). The edits delete the profile's left and right lines and
draw them again while the front and back lines are kept (they keep their geometry IDs) but end up
the other way round. The Sketcher's geometry history (`SketchObject::generateId`) gives a new line
the Id of a deleted line whose end points were in the same point clusters; the clusters follow the
kept lines' start and end, so with the neighbours reversed the new right line takes the deleted
LEFT line's Id (and its name `g<id>`), and the new left line the deleted right line's. The pad's
top-face edges, and so the projected lines' `Source`, follow those names. The expectation is
geometric: the circle stays on the side it was on (or the sketch breaks), never on the opposite
side."""

import Sketcher
import FreeCAD as App

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

TOL = 1e-6
V = App.Vector


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


def placeLine(sketch, index, start, end):
    """Moves line `index` to start -> end, keeping its geometry ID (either way round)."""
    geometry = sketch.Geometry
    line, start, end = geometry[index], V(*start, 0), V(*end, 0)
    line.StartPoint = V(-777, -777, 0)  # away from both, so no step makes a point
    line.EndPoint = end
    line.StartPoint = start
    sketch.Geometry = geometry


class CircleOnLine(Outcome):
    """The sketch computes, its PointOnObject constraint names the projected line on axis =
    value (`on` before the edit, `after` after it), and the circle's centre lies on it."""

    def __init__(self, on, after):
        self.on, self.after = on, after

    def compare(self, scenario, consumer, target, expectation):
        axis, value = self.on if scenario.stepName is None else self.after
        constraint = [c for c in consumer.Constraints if c.Type == "PointOnObject"][0]
        line = consumer.ExternalGeo[-constraint.Second - 1]
        ends = (line.StartPoint, line.EndPoint)
        if not all(abs(getattr(p, axis) - value) < TOL for p in ends):
            return False, f"the constraint is on the projected line {ends[0]} - {ends[1]}"
        centre = consumer.Geometry[constraint.First].Center
        if abs(getattr(centre, axis) - value) > TOL:
            return False, f"the circle's centre is at {centre}"
        return True, ""


class ReviewFaceLink(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "review pr384-r1"
    TIER = "F"
    AXES = ("M8", "E2")
    REFS = ("circle_on_x20",)
    on = ("x", 20)
    after = ("x", 25)

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 20), body)
        pad = m.pad(body, profile, 10)
        doc.recompute()
        sketch = m.sketch(doc, "OnTop", [], body)
        sketch.addExternal(pad.Name, self.names(pad, self.topFace())[0])
        doc.recompute()
        axis, value = self.on
        line = lineOn(sketch, axis, value)
        centre = (value, 5) if axis == "x" else (5, value)
        circle = sketch.addGeometry(m.circle(*centre, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace,
                 CircleOnLine(self.on, self.after))


class ExternalFaceRedrawSidesNeighboursReversed(ReviewFaceLink):
    """The square widened to x = -5 .. 25: the left and right lines deleted, the front and back
    lines stretched and left the other way round, a new right line (25, 0)-(25, 20) drawn, then
    a new left line (-5, 20)-(-5, 0). The face resolves exactly and its edges keep their
    positions in the face's order (integration's positional pairing keeps the circle on the
    right side, x = 25). The new right line took the deleted left line's Id, so its Source is
    the old left edge's: by Source the circle goes to the left side, x = -5, the sketch valid
    and silent."""

    def edit(self, doc):
        doc.Profile.delGeometries([1, 3])  # 0: front, 1: back
        placeLine(doc.Profile, 0, (25, 0), (-5, 0))
        placeLine(doc.Profile, 1, (-5, 20), (25, 20))
        doc.Profile.addGeometry(m.polyline([(25, 0), (25, 20)]), False)
        doc.Profile.addGeometry(m.polyline([(-5, 20), (-5, 0)]), False)


class ExternalFaceRedrawSidesNeighboursReversedLeft(ExternalFaceRedrawSidesNeighboursReversed):
    """The same edit, the circle on the left line: it must end on x = -5, not x = 25."""

    REFS = ("circle_on_x0",)
    on = ("x", 0)
    after = ("x", -5)


class ExternalFaceRedrawSidesInPlaceNeighboursReversed(ReviewFaceLink):
    """Nothing moves: the left and right lines deleted and drawn again in place (right first),
    the front and back lines reversed in place. Every projected line has a predecessor at
    exactly its place, but the new right line has the deleted left line's Id and Source."""

    AXES = ("M8", "E2", "E1")
    after = ("x", 20)

    def edit(self, doc):
        doc.Profile.delGeometries([1, 3])
        placeLine(doc.Profile, 0, (20, 0), (0, 0))
        placeLine(doc.Profile, 1, (0, 20), (20, 20))
        doc.Profile.addGeometry(m.polyline([(20, 0), (20, 20)]), False)
        doc.Profile.addGeometry(m.polyline([(0, 20), (0, 0)]), False)


class ExternalFaceRedrawSidesInPlaceFrontReversed(ReviewFaceLink):
    """Nothing moves: the left and right lines drawn again in place (right first), the front
    line alone reversed in place. The face's order turns (integration pairs by position and
    goes wrong too), and by Source the left line's circle goes to the right side; every line
    has a predecessor at exactly its place."""

    AXES = ("M8", "E2", "E1")
    REFS = ("circle_on_x0",)
    on = ("x", 0)
    after = ("x", 0)

    def edit(self, doc):
        doc.Profile.delGeometries([1, 3])
        placeLine(doc.Profile, 0, (20, 0), (0, 0))
        doc.Profile.addGeometry(m.polyline([(20, 0), (20, 20)]), False)
        doc.Profile.addGeometry(m.polyline([(0, 20), (0, 0)]), False)
