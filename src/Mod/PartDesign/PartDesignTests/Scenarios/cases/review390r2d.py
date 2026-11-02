# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corpus cases (class A, ops#468): fork PR 390 round 2d's fix-trace review (pr390-r2d). Round 2d
lets TestNamingSolver's lone-twin tests take a quiet exact hit on a crossing's saved name (A2's
side roles: a lone crossing keeps `in`/`out` when its twin goes) and drops the seam tests'
expectedFailure marks. These cases compose that 2 -> 1 change with the side role's switch point
(I-A6): the crossed edge's sketch line drawn the other way (`flip`), the solid as it was.
Model P (the lone-twin tests'): a plate 200 x 100 x 5 (scale 1), a through pocket of a circle of
radius 1 at (ax, 0.5), A, crossing the top front edge (y = 0, z = 5) at ax -+ 0.866; optionally B
at (bx, 0.5) from another sketch and Pocket or from A's sketch; datum points on A's crossings.
Model S (the seam tests'): a pad 20 x 10 x 5, a through pocket of a circle of radius 1 at
(10, 0.5), its sketch turned by `turn`, the centre moved onto the edge, so the crossing on the
seam's side becomes the seam vertex; points on both crossings, a Fillet on one front vertical
line. Each expectation is the element at its place on the edited model, else BROKEN."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Filleted, Scenario, edge, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HALF = math.sqrt(1 - 0.5**2)


def drawnTheOtherWay(sketch, index=0):
    """Line `index` of the sketch drawn the other way, its geometry id kept."""
    geometry = sketch.Geometry
    line = geometry[index]
    start, end = V(line.StartPoint), V(line.EndPoint)
    line.StartPoint, line.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
    line.StartPoint, line.EndPoint = end, start
    sketch.Geometry = geometry


class R2dCase(Scenario):
    abstract = True
    area = "twins"
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2d"
    TIER = "F"


class R2dPlate(R2dCase):
    """Model P: A moves from ax0 to ax1 (moved, or with `redraw` deleted and drawn again)."""

    abstract = True
    AXES = ("M1", "E1", "E4", "X4:600")
    SIZE, SCALE = 200, 3
    REFS = ("left", "right")
    ax0, ax1, bx = 100.0, 0.3, 102.5
    b = None  # None, "other" (another sketch and Pocket after A's) or "same" (in A's sketch)
    flip, redraw, move = True, False, True
    steps = ("edit",)

    def crossing(self, side):
        x = self.ax + side * HALF
        return vertex(at=self.s(x, 0, 5)) if 1e-6 < x < 200 - 1e-6 else BROKEN

    def pocket(self, doc, body, name, circles):
        sketch = m.sketch(doc, "Hole" + name, circles, body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket" + name)
        pocket.Profile, pocket.Type, pocket.Midplane = sketch, 1, True
        return sketch, pocket

    def build(self, doc):
        self.ax = self.ax0
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, self.profile, self.s(5))
        circles = [m.circle(*self.s(self.ax0, 0.5, 1))]
        if self.b == "same":
            circles.append(m.circle(*self.s(self.bx, 0.5, 1)))
        self.holeA, last = self.pocket(doc, body, "A", circles)
        if self.b == "other":
            _, last = self.pocket(doc, body, "B", [m.circle(*self.s(self.bx, 0.5, 1))])
        doc.recompute()
        for name, side in (("left", -1), ("right", 1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(last, self.names(last, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        doc.recompute()

    def moveA(self):
        if self.redraw:  # a new geometry id
            self.holeA.delGeometry(0)
            self.holeA.addGeometry(m.circle(*self.s(self.ax1, 0.5, 1)))
        else:
            self.holeA.moveGeometry(0, 3, V(*self.s(self.ax1, 0.5, 0)), False)
        self.ax = self.ax1

    def edit(self, doc):
        if self.flip:
            drawnTheOtherWay(self.profile)
        if self.move:
            self.moveA()
        doc.recompute()

    def flipFirst(self, doc):
        drawnTheOtherWay(self.profile)
        doc.recompute()

    def moveOnly(self, doc):
        self.moveA()
        doc.recompute()


class R2dLoneRightFlipped(R2dPlate):
    """A to (0.3, 0.5), flipped: the left crossing leaves the edge, the right one stays alone with
    its side flipped. Left breaks; right stays on A's crossing (1.166)."""


class R2dLoneRightFlippedBesideB(R2dLoneRightFlipped):
    """With B from another sketch (testLoneTwinIsNotAnotherHolesCrossing's model)."""
    b = "other"


class R2dLoneRightFlippedSibling(R2dLoneRightFlipped):
    """With B in A's sketch (testLoneTwinIsNotASiblingCirclesCrossing's model)."""
    b = "same"


class R2dLoneRightFlipThenMove(R2dLoneRightFlippedBesideB):
    """The flip and the move as two edits, each recomputed."""
    steps = ("flipFirst", "moveOnly")


class R2dFlipOnlyBesideB(R2dPlate):
    """Only the flip, with B from another sketch: each point stays on its crossing."""
    AXES = ("M1", "E4", "X4:600")
    b, move = "other", False


class R2dFlipOnly(R2dFlipOnlyBesideB):
    """Only the flip, without B."""
    b = None


class R2dLoneAtLeftsPlaceFlipped(R2dPlate):
    """A from (1.5, 0.5) by -1.732: the left crossing leaves the edge's start, the right one lands
    exactly where the left one was (0.634); flipped. Left breaks; right follows."""
    ax0, ax1 = 1.5, 1.5 - 2 * HALF


class R2dLoneAtLeftsPlace(R2dLoneAtLeftsPlaceFlipped):
    """The control, no flip."""
    flip = False


class R2dLoneAtLeftsPlaceFlippedSibling(R2dLoneAtLeftsPlaceFlipped):
    """With B in A's sketch at (4, 0.5)."""
    b, bx = "same", 4.0


class R2dLoneAtRightsPlaceFlipped(R2dPlate):
    """The far end: A from (198.5, 0.5) by +1.732: the right crossing leaves the edge, the left one
    lands exactly where the right one was (199.366); flipped. Right breaks; left follows."""
    ax0, ax1 = 198.5, 198.5 + 2 * HALF


class R2dLoneAtRightsPlace(R2dLoneAtRightsPlaceFlipped):
    """The control, no flip."""
    flip = False


class R2dLoneRightRedrawn(R2dPlate):
    """A's circle deleted and drawn again at (0.3, 0.5), beside B, no flip."""
    AXES = ("M1", "E2", "X4:600")
    b, flip, redraw = "other", False, True


class R2dSeam(R2dCase):
    """Model S; the circle's centre moved onto the edge (y 0.5 -> 0), with `flip`."""

    abstract = True
    AXES = ("M4", "E1", "E4")
    SIZE, SCALE = 20, 1
    REFS = ("left_point", "right_point", "line")
    turn, flip = 0, True
    filletSide = 1  # the front face's vertical line the Fillet is on: -1 left, 1 right
    cx, cy = 10.0, 0.5

    def crossing(self, side):
        return vertex(at=self.s(self.cx + side * math.sqrt(1 - self.cy**2), 0, 5))

    def line(self):
        x, z, top = self.s(self.cx + self.filletSide * math.sqrt(1 - self.cy**2), 2.5, 5)
        tol = 1e-6 * max(1, self.scale)
        return edge(
            where=lambda e: (e.CenterOfMass - V(x, 0, z)).Length < tol and abs(e.Length - top) < tol
        )

    def build(self, doc):
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 20, 10)), body)
        m.pad(body, self.profile, self.s(5))
        centre = V(*self.s(self.cx, self.cy, 0))
        rotation = App.Rotation(V(0, 0, 1), self.turn)
        placement = App.Placement(centre - rotation.multVec(centre), rotation)
        self.hole = m.sketch(
            doc, "Hole", [m.circle(*self.s(self.cx, self.cy, 1))], body, placement=placement
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile, pocket.Type, pocket.Midplane = self.hole, 1, True
        doc.recompute()
        for name, side in (("left_point", -1), ("right_point", 1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(pocket, self.names(pocket, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, self.line()))
        fillet.Radius = self.s(0.3)
        doc.recompute()
        self.ref("line", fillet, "Base", self.line, Filleted(self.s(0.3)))

    def edit(self, doc):
        if self.flip:
            drawnTheOtherWay(self.profile)
        self.hole.moveGeometry(
            0, 3, self.hole.Placement.inverse().multVec(V(*self.s(self.cx, 0, 0))), False
        )
        self.cy = 0.0
        doc.recompute()


class R2dSeamFlipped(R2dSeam):
    """Seam on the right, flipped: the right crossing becomes the seam vertex (11, 0, 5), the left
    one stays alone (9, 0, 5), its side flipped. Fillet on the right line
    (testFilletOnATwinEdgeIsLoudWhenItsTwinGoes's model)."""


class R2dSeamFlippedFilletLeft(R2dSeamFlipped):
    """The fillet on the left line, the one that stays."""
    filletSide = -1


class R2dSeamFilletLeft(R2dSeamFlippedFilletLeft):
    """The control, no flip."""
    flip = False


class R2dSeamTurnedFlipped(R2dSeam):
    """Turned 180 degrees (seam on the left), flipped: the left crossing becomes the seam vertex
    (9, 0, 5), the right one stays alone (11, 0, 5), its side flipped
    (testCrossingWhoseTwinBecameTheSeamVertexIsLoud's model). Fillet on the right line."""
    turn = 180


class R2dSeamTurnedFlippedFilletLeft(R2dSeamTurnedFlipped):
    """The fillet on the left line, the one that becomes the seam's."""
    filletSide = -1


class R2dSeamTurnedFilletLeft(R2dSeamTurnedFlippedFilletLeft):
    """The control, no flip: the mirror of testFilletOnATwinEdgeIsLoudWhenItsTwinGoes."""
    flip = False
