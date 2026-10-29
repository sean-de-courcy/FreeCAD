# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 384 round 4v (class E, E1; ops#264 e2): a face link whose loops split or merge. A slot
whose mouth is closed makes a hole of it (one loop becomes two), and a hole opened to the edge makes
a slot (two become one); the slot's walls and floor keep their places and the face's side, and the
face's other edges stay. The loops are oriented with the face on their left (holes clockwise), and
a split loop's anchors go where each new loop holds its share in order.

Model: a 30 x 30 profile with a 10 wide slot from the back down to y = 10 (walls x = 10 and x =
20), padded 10 high, or as a Part::Feature face at z = 10 without names; closed, the slot is the
hole 10..20 x 10..25. A sketch projects the top face and has a circle (r 1) whose centre is on one
projected line (PointOnObject, nothing else holding it). Expected: the constraint stays on that
line."""

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOL = 1e-6

U = [(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10), (10, 30), (0, 30)]
U_LINES = {i: (a, b) for i, (a, b) in enumerate(zip(U, U[1:] + U[:1]))}
# the profile's lines 2, 3, 5 and 6 moved so that the slot is a hole (IDs kept)
O_LINES = dict(U_LINES)
O_LINES.update(
    {
        2: ((30, 30), (0, 30)),
        3: ((20, 25), (20, 10)),
        5: ((10, 10), (10, 25)),
        6: ((10, 25), (20, 25)),
    }
)


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
    """The PointOnObject constraint names the projected line `before` before the edit and `after`
    after it, its circle's centre on it."""

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


def plateFace(lines):
    """The profile's lines as a face at z = 10: one wire, or the square and the hole."""
    edges = [Part.LineSegment(V(*a, 10), V(*b, 10)).toShape() for a, b in lines.values()]
    wires = [Part.Wire(group) for group in Part.sortEdges(edges)]
    return Part.makeFace(wires, "Part::FaceMakerBullseye")


class SlotLoops(Scenario):
    abstract = True
    area = "external geometry"
    CLASSES = ("E",)
    ISSUE = "ops#264"
    FOUND_BY = "design pr384-r4v"
    TIER = "F"
    AXES = ("M8", "E1", "E5")
    REFS = ("circle_on_line",)
    named = True
    start, end = U_LINES, O_LINES
    at = (20, 20)
    before = ("x", 20.0, (10.0, 30.0))
    after = ("x", 20.0, (10.0, 25.0))

    def topFace(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        if self.named:
            body = m.body(doc)
            lines = [Part.LineSegment(V(*a, 0), V(*b, 0)) for a, b in self.start.values()]
            profile = m.sketch(doc, "Profile", lines, body)
            target = m.pad(body, profile, 10)
            doc.recompute()
            sketch = m.sketch(doc, "OnTop", [], body)
        else:
            target = m.feature(doc, "Plate", plateFace(self.start))
            doc.recompute()
            sketch = doc.addObject("Sketcher::SketchObject", "OnTop")
        sketch.addExternal(target.Name, self.names(target, self.topFace())[0])
        doc.recompute()
        line = [
            -i - 1
            for i, g in enumerate(sketch.ExternalGeo)
            if i >= 2 and matchesLine(g, self.before)
        ][0]
        circle = sketch.addGeometry(m.circle(*self.at, 1), False)
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, line))
        sketch.addConstraint(Sketcher.Constraint("Radius", circle, 1))
        held = HeldOn(self.before, self.after)
        self.ref(self.REFS[0], sketch, "ExternalGeometry", self.topFace, held)

    def edit(self, doc):
        if self.named:
            m.setLines(doc.Profile, {i: self.end[i] for i in (2, 3, 5, 6)})
        else:
            doc.Plate.Shape = plateFace(self.end)


class ExternalFaceSlotClosedWall(SlotLoops):
    """The slot's mouth closed: its right wall (x = 20) becomes the hole's right line."""


class ExternalFaceSlotClosedOuterSide(SlotLoops):
    """The slot's mouth closed, the circle on the left side (x = 0), on the outer loop
    throughout."""

    at = (0, 5)
    before = ("x", 0.0, (0.0, 30.0))
    after = ("x", 0.0, (0.0, 30.0))


class ExternalFaceSlotClosedUnmappedWall(SlotLoops):
    """ExternalFaceSlotClosedWall on a Part::Feature face without names (place votes only)."""

    named = False


class ExternalFaceSlotOpenedWall(SlotLoops):
    """The hole opened to the back: its right line (x = 20) becomes the slot's right wall."""

    start, end = O_LINES, U_LINES
    before = ("x", 20.0, (10.0, 25.0))
    after = ("x", 20.0, (10.0, 30.0))


class ExternalFaceSlotOpenedFloor(SlotLoops):
    """The hole opened to the back, the circle on its front line (y = 10), the slot's floor
    after."""

    start, end = O_LINES, U_LINES
    at = (15, 10)
    before = ("y", 10.0, (10.0, 20.0))
    after = ("y", 10.0, (10.0, 20.0))


class ExternalFaceSlotOpenedUnmappedFloor(ExternalFaceSlotOpenedFloor):
    """ExternalFaceSlotOpenedFloor on a Part::Feature face without names."""

    named = False
