# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2h (the fix after the rebase's review, 9a37b6ba5e): review pr390-r2h's probes
of tier 3's pick without a structural candidate, now `!lacks && (twinClause || (nearest.index < 0
&& !redrawn)) && lostOldSource(pick)`: under the twin clause, a pick D2 calls drawn again breaks
(T1''s source test), where integration let it resolve. A reference that breaks takes no part in
its owner's forced matching, so another reference of the same owner that wanted the same element
is no longer contested.

The model: a Pad (Refine off) from an unattached sketch (rectangle x -3..3, y -0.5..0.5) up to a
Part::Feature shell at z = 10: the plate x -10..20, y -10..10 with a rectangular hole x -1..1,
y -2..2 and its fill (B-spline faces), so the Pad's far edge y 0.5 comes in pieces L (x -3..-1),
M (the fill, -1..1) and R (1..3). Pocket circles r 0.3 centred at y 0.6 (half chord H =
sqrt(0.08) on y 0.5), one sketch, one Pocket, length 2:
- A at (-1.82, 0.6): two crossings of L, twins; `a_right` holds the right one (-1.5372).
- B at (-1.2, 0.6): spans x -1, one crossing on L (-1.4828, `b_left`, no twin on L) and one on
  M; it cuts the L/M vertex away.
- C at (2, 0.6): a sibling, unchanged.
The Pocket's diagonal is 11.7 (d_max 0.117); b_left's place is 0.054 from a_right's, every other
vertex 0.48 or more away.

One edit: B deleted, A deleted and drawn again where it was (a new geometry ID). a_right's
crossing is drawn again at its place: it follows or breaks (decision 227 accepts the break).
b_left's circle is gone: it breaks (policy D); the crossing 0.054 away is another circle's.
"""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HEIGHT = 10.0
R = 0.3
CY = 0.6
H = (R * R - (CY - 0.5) ** 2) ** 0.5
AX = -1.82
BX = -1.2
CX = 2.0


class Base(Scenario):
    abstract = True
    AXES = ("M5", "E1")
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2h"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    REFS = ("a_right", "b_left")
    BEFORE = {"a_right": (AX + H, 0.5), "b_left": (BX - H, 0.5)}
    HOLES = ((-1, -2, 1, 2),)
    ONE_OWNER = True
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
            [m.circle(self.S(x), self.S(CY), self.S(R)) for x in (AX, BX, CX)],
            body,
            z=self.S(HEIGHT),
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 0
        pocket.Length = self.S(2)
        pocket.Refine = False
        doc.recompute()
        subA = self.names(pocket, self.place(*self.BEFORE["a_right"]))[0]
        subB = self.names(pocket, self.place(*self.BEFORE["b_left"]))[0]
        if self.ONE_OWNER:
            # One owner holding both: the sketch attached at a_right, b_left its external vertex
            probe = body.newObject("Sketcher::SketchObject", "Probe")
            probe.AttachmentSupport = [(pocket, subA)]
            probe.MapMode = "Translate"
            probe.addExternal(pocket.Name, subB)
            self.ref("a_right", probe, "AttachmentSupport", self.expectation("a_right"), Attached())
            self.ref("b_left", probe, "ExternalGeometry", self.expectation("b_left"))
        else:
            for name, sub in (("a_right", subA), ("b_left", subB)):
                point = body.newObject("PartDesign::Point", "On" + name)
                point.AttachmentSupport = [(pocket, sub)]
                point.MapMode = "CenterOfMass"
                self.ref(name, point, "AttachmentSupport", self.expectation(name), Attached())
        body.Tip = pocket

    def after(self, name):
        if name == "a_right":
            return OwnOrBroken(self.place(*self.BEFORE["a_right"]))
        return BROKEN

    def expectation(self, name):
        def expect():
            if not self.edited:
                return self.place(*self.BEFORE[name])
            return self.after(name)

        return expect

    def change(self, doc):
        self.hole.delGeometry(1)  # B
        self.hole.delGeometry(0)  # A
        self.hole.addGeometry(m.circle(self.S(AX), self.S(CY), self.S(R)), False)

    def edit(self, doc):
        self.change(doc)
        self.edited = True


class R2hContestedRedrawOneOwner(Base):
    """a_right and b_left in one owner (a sketch attached at a_right, b_left its external vertex).
    On integration a_right's pick (D2: drawn again) and b_left's tier 3 nearest are the same
    crossing: the forced matching leaves both ambiguous (broken). With the fix a_right breaks by
    T1''s source test before the matching, and b_left alone holds the crossing of A: wrong."""


class R2hContestedRedrawTwoOwners(Base):
    """As R2hContestedRedrawOneOwner, each reference in its own datum point: no contest on either
    build, so b_left's tier 3 nearest stands alone on both (the control: wrong on both is debt)."""

    ONE_OWNER = False
