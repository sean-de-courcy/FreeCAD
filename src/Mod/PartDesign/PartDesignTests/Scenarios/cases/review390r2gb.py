# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2g (the rebase onto integration): review pr390-r2g's probes of the conflict
resolution in tier 3's pick without a structural candidate, `!lacks && !redrawn && (twinClause ||
nearest.index < 0) && lostOldSource(pick)`: D2's verdict that the pick is the old element drawn
again at the saved place (Quiet or Normal) exempts it from T1''s source test for a record that saved
two twins or more, as integration exempts it for a twin survivor.

review390r2er.py's model: a Pad (Refine off) from an unattached sketch (rectangle x -3..3, y
-0.5..0.5) up to a Part::Feature shell at z = 10 (SIZE 30 at scale 1): the plate x -10..20, y
-10..10 with a rectangular hole x -1..1, y -2..2 and its fill (B-spline faces), so the Pad's far
edge y 0.5 comes in pieces L (x -3..-1), M (the fill) and R (1..3). Pocket circles r 0.3 at
z 10 (one sketch, one Pocket, length 2): circle A at (-2, 0.7) crosses L's far edge twice, at
-2 -+ D (D = sqrt(0.05)), saved as two twins ("first", "second").

The expected element is the crossing the reference held where it lies after the edit; a circle
deleted and drawn again in the same sketch is re-bound (policy D's redraw); a crossing of a
circle that still exists but no longer crosses L there is gone and breaks.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
D = 0.05**0.5
R = 0.3


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2g"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("first", "second")
    CIRCLES = ((-2, 0.7),)
    BEFORE = {"first": (-2 - D, 0.5), "second": (-2 + D, 0.5)}
    HOLES = ((-1, -2, 1, 2),)
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x, y):
        return vertex(self.P(x, y))

    def poly(self, points, z=HEIGHT):
        c = [self.P(x, y, z) for x, y in points]
        return Part.makePolygon(c + c[:1])

    def shell(self):
        outer = self.poly([(-10, -10), (20, -10), (20, 10), (-10, 10)])
        wires = [outer]
        fills = []
        for hx0, hy0, hx1, hy1 in self.HOLES:
            wires.append(self.poly([(hx0, hy0), (hx0, hy1), (hx1, hy1), (hx1, hy0)]))
            fills.append(
                Part.Face(self.poly([(hx0, hy0), (hx1, hy0), (hx1, hy1), (hx0, hy1)]))
                .toNurbs()
                .Faces[0]
            )
        plate = Part.Face(Part.Plane(self.P(0, 0), V(0, 0, 1)), wires).toNurbs().Faces[0]
        return Part.Shell([plate] + fills)

    def build(self, doc):
        self.edited = False
        body = m.body(doc)
        self.plate = m.feature(doc, "Plate", self.shell())
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(self.S(-3), self.S(-0.5), self.S(3), self.S(0.5)), body
        )
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self.profile
        pad.Type = "UpToShape"
        pad.UpToShape = (self.plate, ["Face%d" % (i + 1) for i in range(len(self.plate.Shape.Faces))])
        pad.Refine = False
        doc.recompute()
        self.hole = m.sketch(
            doc,
            "Circles",
            [m.circle(self.S(x), self.S(y), self.S(R)) for x, y in self.CIRCLES],
            body,
            z=self.S(HEIGHT),
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            sub = self.names(pocket, self.place(*self.BEFORE[name]))[0]
            point.AttachmentSupport = [(pocket, sub)]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket

    def after(self, name):
        """The expectation on the edited model (a predicate, BROKEN, or OwnOrBroken)."""
        raise NotImplementedError

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            return self.after(name)

        return expect

    def addCircle(self, x, y, r=R):
        self.hole.addGeometry(m.circle(self.S(x), self.S(y), self.S(r)), False)

    def redrawCircle(self, index, x, y, r=R):
        self.hole.delGeometry(index)
        self.addCircle(x, y, r)

    def moveCircle(self, index, x, y):
        geometry = self.hole.Geometry
        geometry[index].Center = V(self.S(x), self.S(y), 0)
        self.hole.Geometry = geometry

    def edit(self, doc):
        self.change(doc)
        self.edited = True


class R2gbRedrawnInPlaceBesideSibling(Base):
    """The control: circles A (-2, 0.7) and B (2, 0.7); A deleted and drawn again where it was (a
    new geometry ID), B unchanged. Both of A's crossings are drawn again at their saved places,
    with their sides: both follow (round 2f broke them, T1''s source test; D2 calls them drawn
    again)."""

    CIRCLES = ((-2, 0.7), (2, 0.7))

    def after(self, name):
        return self.place(*self.BEFORE[name])

    def change(self, doc):
        self.redrawCircle(0, -2, 0.7)


class R2gbMovedOffNewCircleAtPlace(Base):
    """Circles A (-2, 0.7) and B (2, 0.7). One edit: A moves to (-1.1, 0.7) (its first crossing
    on L at -1.1 - D, its second on the fill's piece M) and a new circle C (a new geometry ID) is
    drawn at A's old place (-2, 0.7). A still exists: its second crossing of L is gone, and C's
    crossing at its saved place is another circle's (D2's marks call it drawn again: every
    unshared source is new). second must break; first follows A or breaks (C's crossing sits at
    its old place)."""

    CIRCLES = ((-2, 0.7), (2, 0.7))

    def after(self, name):
        if name == "first":
            return OwnOrBroken(self.place(-1.1 - D, 0.5))
        return BROKEN

    def change(self, doc):
        self.moveCircle(0, -1.1, 0.7)
        self.addCircle(-2, 0.7)


class R2gbMovedClearNewCircleAtPlace(Base):
    """As R2gbMovedOffNewCircleAtPlace with A moved to (-2, 1.5), clear of the Pad (it cuts
    nothing and crosses nothing), and C drawn at A's old place: no twin survives on L, the record
    saved two. A still exists in the sketch: both of its crossings are gone, and C's crossings at
    their saved places are another circle's. Both must break."""

    CIRCLES = ((-2, 0.7), (2, 0.7))

    def after(self, name):
        return BROKEN

    def change(self, doc):
        self.moveCircle(0, -2, 1.5)
        self.addCircle(-2, 0.7)


class R2gbRedrawnOntoOtherCrossing(Base):
    """A deleted and drawn again at (-2 - 2D, 0.7): its right crossing lies at first's saved place
    (-2 - D), its left at -2 - 3D; nothing at second's saved place. The pick at first's place is
    the other crossing (D2's sides: the arc leaves it the other way). Each reference follows the
    redrawn circle's crossing on its own side or breaks."""

    def after(self, name):
        if name == "first":
            return OwnOrBroken(self.place(-2 - 3 * D, 0.5))
        return OwnOrBroken(self.place(-2 - D, 0.5))

    def change(self, doc):
        self.redrawCircle(0, -2 - 2 * D, 0.7)


# A circle of radius 1 tangent to A at first's saved crossing P = (-2 - D, 0.5): its centre on the
# ray from P through A's centre, so the arc leaves P in the same direction (D2's sides agree)
BIG = 1.0
BIG_CX = -2 - D + BIG * D / R
BIG_CY = 0.5 + BIG * 0.2 / R
BIG_OTHER = 2 * BIG_CX - (-2 - D)  # its other crossing of y 0.5, on the fill's piece M (-0.733)


class R2gbRedrawnLargerTangent(Base):
    """A deleted and drawn again with radius 1, tangent to the old circle at first's saved
    crossing P: the new circle crosses L once, at P, with the old crossing's sides; its other
    crossing (x -0.733) lies on the fill's piece M. A redraw at the identical place: first follows
    (I-A2: a count change decides by place, XP re-binds there); second's crossing left L for M:
    it follows that crossing or breaks."""

    def after(self, name):
        if name == "first":
            return self.place(-2 - D, 0.5)
        return OwnOrBroken(self.place(BIG_OTHER, 0.5))

    def change(self, doc):
        self.hole.delGeometry(0)
        self.addCircle(BIG_CX, BIG_CY, BIG)
