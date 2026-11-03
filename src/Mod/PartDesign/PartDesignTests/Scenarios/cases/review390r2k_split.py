# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2k (ops#468): stop 1 (D2's "drawn again" doesn't stand while another element
keeps the old name's sources) where the old source lives on and the pick at the place is still the
same element: a sketch circle split into two arcs (as Sketcher's Split does: one piece keeps the
circle's geometry ID, the other gets a new one). The hole is unchanged, point for point.

The model is review390r2js.py's: a Pad (Refine off) from an unattached sketch (rectangle x -3..3,
y -0.5..0.5) up to a Part::Feature shell at z = 10 (the plate x -10..20, y -10..10 with a hole
x -1..1, y -2..2 and its fill), so the Pad's far edge y 0.5 comes in pieces L (x -3..-1), M
(-1..1) and R (1..3). Pocket circles r 0.3 centred at y 0.6, one sketch, one Pocket 2 deep:
A at (-1.82, 0.6) (two crossings of L, twins), B at (-1.2, 0.6) (-1.4828 on L, a lone one, and
-0.9172 on M), C at (2, 0.6) (two on R).

Edits on B (the expectations follow the geometry, defined geometrically):
- Split: B replaced by its left and right half arcs (split at its top and bottom points); the
  piece holding the named crossing gets the new ID, the other keeps B's. The hole is the same:
  every reference holds its place.
- MoveOffNewAt: B moved clear of the edge (to y 1.5) and a new circle N drawn at B's old place:
  B's crossings are gone, b_left and b_right break (N's crossings are another circle's).
- MoveFarNewAt: B moved to (2.6, 0.6) (crossings on R at 2.3172 and 2.8828) and N at B's old
  place: b_left follows B's left crossing or breaks, never N's.
"""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
R0 = 0.3
CY = 0.6
START = {"A": (-1.82, CY), "B": (-1.2, CY), "C": (2.0, CY)}
H = (R0 * R0 - (CY - 0.5) ** 2) ** 0.5
REF_SIDE = {
    "a_left": ("A", -1),
    "a_right": ("A", 1),
    "b_left": ("B", -1),
    "b_right": ("B", 1),
}


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2k"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("b_left", "b_right")
    OWNERS = "datum"
    HOLES = ((-1, -2, 1, 2),)
    edited = False

    def S(self, v):
        return v * self.scale

    def P(self, x, y, z=HEIGHT):
        return V(self.S(x), self.S(y), self.S(z))

    def place(self, x):
        return vertex(self.P(x, 0.5))

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

    def before(self, name):
        tag, side = REF_SIDE[name]
        return START[tag][0] + side * H

    def build(self, doc):
        self.edited = False
        self.tags = ["A", "B", "C"]
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
            [m.circle(self.S(START[t][0]), self.S(START[t][1]), self.S(R0)) for t in self.tags],
            body,
            z=self.S(HEIGHT),
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        subs = {n: self.names(pocket, self.place(self.before(n)))[0] for n in self.REFS}
        if self.OWNERS == "pair":
            first, second = self.REFS
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(pocket, subs[first])]
            probe.MapMode = "Translate"
            probe.addExternal(pocket.Name, subs[second])
            self.ref(first, probe, "AttachmentSupport", self.expectation(first), Attached())
            self.ref(second, probe, "ExternalGeometry", self.expectation(second))
        else:
            for name in self.REFS:
                point = body.newObject("PartDesign::Point", "On" + name)
                point.AttachmentSupport = [(pocket, subs[name])]
                point.MapMode = "CenterOfMass"
                self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket

    def after(self, name):
        return self.place(self.before(name))

    def expectation(self, name):
        def expect():
            return self.after(name) if self.edited else self.place(self.before(name))

        return expect

    def edit(self, doc):
        self.change(doc)
        self.edited = True

    # operations
    def split(self, tag, newSide):
        """Replace circle \a tag by its left and right half arcs; the \a newSide piece (-1 left,
        1 right) gets a new geometry ID, the other keeps the circle's."""
        index = self.tags.index(tag)
        keep = self.hole.getGeometryId(index)
        x, y = START[tag]
        circle = Part.Circle(V(self.S(x), self.S(y), 0), V(0, 0, 1), self.S(R0))
        right = Part.ArcOfCircle(circle, -math.pi / 2, math.pi / 2)
        left = Part.ArcOfCircle(circle, math.pi / 2, 3 * math.pi / 2)
        self.hole.delGeometry(index)
        self.tags.remove(tag)
        first = self.hole.addGeometry(right, False)
        second = self.hole.addGeometry(left, False)
        self.tags += [tag + "r", tag + "l"]
        kept = second if newSide > 0 else first
        self.hole.setGeometryId(kept, keep)

    def moveTo(self, tag, x, y):
        geometry = self.hole.Geometry
        geometry[self.tags.index(tag)].Center = V(self.S(x), self.S(y), 0)
        self.hole.Geometry = geometry

    def add(self, x):
        self.hole.addGeometry(m.circle(self.S(x), self.S(CY), self.S(R0)), False)
        self.tags.append("N")


class R2kSplitBNewLeft(Base):
    """B split; its left half (b_left's crossing) gets the new ID. Both hold their places."""

    def change(self, doc):
        self.split("B", -1)


class R2kSplitBNewLeftPair(R2kSplitBNewLeft):
    OWNERS = "pair"


class R2kSplitBNewLeftSolo(R2kSplitBNewLeft):
    REFS = ("b_left",)


class R2kSplitBNewRight(Base):
    """B split; its right half (b_right's crossing on M) gets the new ID."""

    def change(self, doc):
        self.split("B", 1)


class R2kSplitBNewRightSolo(R2kSplitBNewRight):
    REFS = ("b_right",)


class R2kSplitANewRight(Base):
    """A split (twins on L); its right half (a_right's crossing) gets the new ID."""

    REFS = ("a_left", "a_right")

    def change(self, doc):
        self.split("A", 1)


class R2kSplitANewRightSolo(R2kSplitANewRight):
    REFS = ("a_right",)


class R2kMoveBOffNewAtB(Base):
    """B moved clear of the edge, N drawn at its old place: B's crossings are gone."""

    def after(self, name):
        return BROKEN

    def change(self, doc):
        self.moveTo("B", -1.2, 1.5)
        self.add(-1.2)


class R2kMoveBOffNewAtBSolo(R2kMoveBOffNewAtB):
    REFS = ("b_left",)


class R2kMoveBFarNewAtB(Base):
    """B moved onto R (2.6), N drawn at its old place: b_left follows B's left crossing on R
    (2.3172) or breaks; b_right (on M before) follows B's right one (2.8828) or breaks."""

    def after(self, name):
        tag, side = REF_SIDE[name]
        return OwnOrBroken(self.place(2.6 + side * H))

    def change(self, doc):
        self.moveTo("C", 2.0, 1.5)  # C clear of R first
        self.moveTo("B", 2.6, CY)
        self.add(-1.2)


class R2kMoveBFarNewAtBSolo(R2kMoveBFarNewAtB):
    REFS = ("b_left",)


class R2kMoveBInNewAtB(Base):
    """B moved inside the Pad's top face, clear of the far edge (to (-1.2, 0.0)), N drawn at its
    old place: B's crossings are gone (its hole's own edges and vertices keep its source), so
    b_left and b_right break; N's crossings are another circle's."""

    def after(self, name):
        return BROKEN

    def change(self, doc):
        self.moveTo("B", -1.2, 0.0)
        self.add(-1.2)


class R2kMoveBInNewAtBSolo(R2kMoveBInNewAtB):
    REFS = ("b_left",)


class R2kMoveBInNewAtBPair(R2kMoveBInNewAtB):
    OWNERS = "pair"


class R2kMoveBOntoMNewAtB(Base):
    """B moved onto piece M (to (0, 0.6): crossings at -0.2828 and 0.2828, both on M), N drawn at
    its old place: b_left follows B's left crossing or breaks, b_right B's right one; never N's."""

    def after(self, name):
        tag, side = REF_SIDE[name]
        return OwnOrBroken(self.place(0.0 + side * H))

    def change(self, doc):
        self.moveTo("B", 0.0, CY)
        self.add(-1.2)


class R2kMoveBOntoMNewAtBSolo(R2kMoveBOntoMNewAtB):
    REFS = ("b_left",)


class R2kMoveBOntoMNewAtBPair(R2kMoveBOntoMNewAtB):
    OWNERS = "pair"
