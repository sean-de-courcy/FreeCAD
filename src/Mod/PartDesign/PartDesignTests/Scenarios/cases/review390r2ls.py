# SPDX-License-Identifier: LGPL-2.1-or-later
"""Corpus cases (class A, ops#468): the trace review of fork PR 390 round 2ls (decision 241, the
unmoved role hit saved among twins goes through the count stop).
Model P (review390r2d's): a plate 200 x 100 x 5, a through pocket of a circle of radius 1 at
(ax, 0.5), A, crossing the top front edge (y = 0, z = 5) at ax -+ 0.866; datum points on A's crossings;
optionally B (another circle). Each expectation is the vertex at its place on the edited model, else
BROKEN."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
HALF = math.sqrt(1 - 0.5**2)


def drawnTheOtherWay(sketch, index=0):
    geometry = sketch.Geometry
    line = geometry[index]
    start, end = V(line.StartPoint), V(line.EndPoint)
    line.StartPoint, line.EndPoint = V(1e4, 1e4, 0), V(2e4, 2e4, 0)
    line.StartPoint, line.EndPoint = end, start
    sketch.Geometry = geometry


class R2lsCase(Scenario):
    abstract = True
    area = "twins"
    CLASSES = ("A",)
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2ls"
    TIER = "F"


class R2lsPlate(R2lsCase):
    abstract = True
    AXES = ("M1", "E1", "E4", "X4:600")
    SIZE, SCALE = 200, 3
    REFS = ("left", "right")
    ax0, ax1, bx0, bx1 = 100.0, 100.0, None, None
    x0, x1 = 0.0, 200.0  # the plate's ends after the edit
    flip, moveA, moveB = False, False, False
    b = None  # None, "other" (another sketch and Pocket) or "same" (in A's sketch)
    steps = ("edit",)

    def crossing(self, side):
        x = self.ax + side * HALF
        lo, hi = (self.x0, self.x1) if self.edited else (0.0, 200.0)
        return vertex(at=self.s(x, 0, 5)) if lo + 1e-6 < x < hi - 1e-6 else BROKEN

    def build(self, doc):
        self.ax = self.ax0
        self.edited = False
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, self.profile, self.s(5))
        circles = [m.circle(*self.s(self.ax0, 0.5, 1))]
        if self.b == "same":
            circles.append(m.circle(*self.s(self.bx0, 0.5, 1)))
        self.holeA = m.sketch(doc, "HoleA", circles, body)
        last = body.newObject("PartDesign::Pocket", "PocketA")
        last.Profile, last.Type, last.Midplane = self.holeA, 1, True
        if self.b == "other":
            self.holeB = m.sketch(doc, "HoleB", [m.circle(*self.s(self.bx0, 0.5, 1))], body)
            last = body.newObject("PartDesign::Pocket", "PocketB")
            last.Profile, last.Type, last.Midplane = self.holeB, 1, True
        doc.recompute()
        for name, side in (("left", -1), ("right", 1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(last, self.names(last, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        doc.recompute()

    def edit(self, doc):
        self.edited = True
        if self.flip:
            drawnTheOtherWay(self.profile)
        if self.moveA:
            self.holeA.moveGeometry(0, 3, V(*self.s(self.ax1, 0.5, 0)), False)
            self.ax = self.ax1
        if self.moveB:
            sk, gid = (self.holeA, 1) if self.b == "same" else (self.holeB, 0)
            sk.moveGeometry(gid, 3, V(*self.s(self.bx1, 0.5, 0)), False)
        if (self.x0, self.x1) != (0.0, 200.0):
            m.moveRectangle(self.profile, *self.s(self.x0, 0, self.x1, 100))
        doc.recompute()


# --- the count-kept swap: both crossings stay on the edge, the circle moves by the spacing, flipped
class R2lsSwapRight(R2lsPlate):
    """A from 100 to 101.732, flipped: the old right place is the new left crossing."""
    ax1, flip, moveA = 100.0 + 2 * HALF, True, True


class R2lsSwapLeft(R2lsPlate):
    """A from 100 to 98.268, flipped."""
    ax1, flip, moveA = 100.0 - 2 * HALF, True, True


class R2lsSwapRightNoFlip(R2lsPlate):
    """The control, no flip."""
    ax1, flip, moveA = 100.0 + 2 * HALF, False, True


class R2lsSwapRightBesideB(R2lsSwapRight):
    """With B (another hole, far)."""
    b, bx0, bx1 = "other", 50.0, 50.0


# --- a flip alone, with B beside
class R2lsFlipBesideB(R2lsPlate):
    b, bx0, bx1, flip = "other", 50.0, 50.0, True


# --- another hole B gains / loses a crossing on the same edge; A untouched
class R2lsBGainsOther(R2lsPlate):
    """B (own pocket) from (1.5): two crossings, to (0.3): one."""
    b, bx0, bx1, moveB = "other", 1.5, 0.3, True


class R2lsBGainsSame(R2lsPlate):
    """The same, B in A's sketch."""
    b, bx0, bx1, moveB = "same", 1.5, 0.3, True


class R2lsBLoses(R2lsPlate):
    """B from 0.3 (one crossing) to 1.5 (two), own pocket."""
    b, bx0, bx1, moveB = "other", 0.3, 1.5, True


class R2lsBLosesSame(R2lsPlate):
    b, bx0, bx1, moveB = "same", 0.3, 1.5, True


class R2lsBNearA(R2lsPlate):
    """B far from A on the edge but in the middle; both crossings stay, moved by 10."""
    b, bx0, bx1, moveB = "other", 50.0, 60.0, True


class R2lsBNearASame(R2lsPlate):
    b, bx0, bx1, moveB = "same", 50.0, 60.0, True


# --- the plate's ends moved past one of A's crossings (an unmoved survivor)
class R2lsLeftEndPastLeft(R2lsPlate):
    """The profile's left end 0 -> 99.5: A's left crossing (99.134) gone, the right (100.866) stays."""
    x0 = 99.5


class R2lsRightEndPastRight(R2lsPlate):
    """The right end 200 -> 100.5: the right crossing gone, the left stays."""
    x1 = 100.5


class R2lsLeftEndPastLeftFlip(R2lsLeftEndPastLeft):
    flip = True


# --- the lone crossing lands at (or near) its gone twin's place, flipped: the stop's own ground
class R2lsLoneBase(R2lsPlate):
    abstract = True
    flip, moveA = True, True
    redraw = False

    def edit(self, doc):
        if self.redraw:
            self.edited = True
            if self.flip:
                drawnTheOtherWay(self.profile)
            self.holeA.delGeometry(0)
            self.holeA.addGeometry(m.circle(*self.s(self.ax1, 0.5, 1)))
            self.ax = self.ax1
            doc.recompute()
        else:
            super().edit(doc)


class R2lsLoneRight0(R2lsLoneBase):
    ax0, ax1 = 198.5, 198.5 + 2 * HALF


class R2lsLoneRightD01(R2lsLoneBase):
    ax0, ax1 = 198.5, 198.5 + 2 * HALF + 0.01


class R2lsLoneRightD03(R2lsLoneBase):
    ax0, ax1 = 198.5, 198.5 + 2 * HALF + 0.3


class R2lsLoneRightD1(R2lsLoneBase):
    ax0, ax1 = 198.5, 198.5 + 2 * HALF + 1.0


class R2lsLoneRightD4(R2lsLoneBase):
    ax0, ax1 = 198.5, 198.5 + 2 * HALF + 4.0


class R2lsLoneRightRedrawn(R2lsLoneBase):
    ax0, ax1, redraw = 198.5, 198.5 + 2 * HALF, True


class R2lsLoneRightBesideB(R2lsLoneBase):
    ax0, ax1, b, bx0, bx1 = 198.5, 198.5 + 2 * HALF, "other", 50.0, 50.0


class R2lsLoneRightSameB(R2lsLoneBase):
    ax0, ax1, b, bx0, bx1 = 198.5, 198.5 + 2 * HALF, "same", 50.0, 50.0


class R2lsLoneLeft0(R2lsLoneBase):
    ax0, ax1 = 1.5, 1.5 - 2 * HALF


class R2lsLoneLeftD1(R2lsLoneBase):
    ax0, ax1 = 1.5, 1.5 - 2 * HALF - 1.0


class R2lsLoneLeftRedrawn(R2lsLoneBase):
    ax0, ax1, redraw = 1.5, 1.5 - 2 * HALF, True


class R2lsLoneLeftNoFlip(R2lsLoneBase):
    ax0, ax1, flip = 1.5, 1.5 - 2 * HALF, False


# --- a later feature's pocket removes one of A's two crossings (an unmoved survivor); no edge change
class R2lsCutter(R2lsPlate):
    """A, then a through pocket C (a rectangle) in the plate's middle; the edit moves C over the
    left (or right) crossing of A, across the front edge."""

    abstract = True
    cover = -1  # -1: over the left crossing, +1: over the right
    flip = False

    def crossing(self, side):
        if self.edited and side == self.cover:
            return BROKEN
        return vertex(at=self.s(self.ax + side * HALF, 0, 5))

    def build(self, doc):
        self.ax = self.ax0
        self.edited = False
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, self.profile, self.s(5))
        self.holeA = m.sketch(doc, "HoleA", [m.circle(*self.s(self.ax0, 0.5, 1))], body)
        pocketA = body.newObject("PartDesign::Pocket", "PocketA")
        pocketA.Profile, pocketA.Type, pocketA.Midplane = self.holeA, 1, True
        self.cutter = m.sketch(doc, "Cutter", m.rectangle(*self.s(150, 40, 155, 50)), body)
        last = body.newObject("PartDesign::Pocket", "PocketC")
        last.Profile, last.Type, last.Midplane = self.cutter, 1, True
        doc.recompute()
        for name, side in (("left", -1), ("right", 1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(last, self.names(last, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        doc.recompute()

    def edit(self, doc):
        self.edited = True
        if self.flip:
            drawnTheOtherWay(self.profile)
        x = self.ax0 + self.cover * (HALF + 1.0)  # a 2 wide strip ending 1 beyond the crossing
        lo, hi = (x - 4.0, x + 1.0 + 0) if self.cover < 0 else (x - 1.0, x + 4.0)
        # the strip lies over the crossing and away from the other one
        if self.cover < 0:
            lo, hi = self.ax0 - HALF - 4.0, self.ax0 - HALF + 0.5
        else:
            lo, hi = self.ax0 + HALF - 0.5, self.ax0 + HALF + 4.0
        m.moveRectangle(self.cutter, *self.s(lo, -1, hi, 3))
        doc.recompute()


class R2lsCutsLeft(R2lsCutter):
    cover = -1


class R2lsCutsRight(R2lsCutter):
    cover = 1


class R2lsCutsLeftFlip(R2lsCutter):
    cover, flip = -1, True


class R2lsCutsRightFlip(R2lsCutter):
    cover, flip = 1, True


class R2lsNoEdit(R2lsPlate):
    """The control: the edit changes nothing."""


class R2lsFlipNoB(R2lsPlate):
    """Flip only, no B."""
    flip = True


class R2lsFlipBNear(R2lsPlate):
    """Flip only, B at 102.5 (review390r2d's R2dFlipOnlyBesideB)."""
    b, bx0, bx1, flip = "other", 102.5, 102.5, True


class R2lsFlipBFar150(R2lsPlate):
    b, bx0, bx1, flip = "other", 150.0, 150.0, True


class R2lsFlipBSame50(R2lsPlate):
    b, bx0, bx1, flip = "same", 50.0, 50.0, True


class R2lsFlipB5(R2lsPlate):
    b, bx0, bx1, flip = "other", 5.0, 5.0, True


# --- a decoy vertex (a static notch's corner) near the place where the lone crossing lands
class R2lsDecoy(R2lsPlate):
    """Like R2lsLoneRight: A from 198.5 to 200.232, flipped, so the left crossing lands at 199.366,
    the right one gone off the plate's end. A static through pocket C removes the plate's corner
    from x = 199.366 + gap, which leaves a vertex of its own `gap` from the landing place."""

    abstract = True
    ax0, ax1, flip, moveA = 198.5, 198.5 + 2 * HALF, True, True
    gap = 0.13

    def build(self, doc):
        self.ax = self.ax0
        self.edited = False
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, self.profile, self.s(5))
        self.cutter = m.sketch(
            doc, "Cutter", m.rectangle(*self.s(199.366 + self.gap, -1, 205, 3)), body
        )
        notch = body.newObject("PartDesign::Pocket", "PocketC")
        notch.Profile, notch.Type, notch.Midplane = self.cutter, 1, True
        self.holeA = m.sketch(doc, "HoleA", [m.circle(*self.s(self.ax0, 0.5, 1))], body)
        last = body.newObject("PartDesign::Pocket", "PocketA")
        last.Profile, last.Type, last.Midplane = self.holeA, 1, True
        doc.recompute()
        for name, side in (("left", -1), ("right", 1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(last, self.names(last, self.crossing(side))[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", lambda s=side: self.crossing(s), Attached())
        doc.recompute()

    def crossing(self, side):
        x = self.ax + side * HALF
        end = 199.366 + self.gap if self.edited else 205.0
        if self.edited:
            return vertex(at=self.s(x, 0, 5)) if 0 < x < end - 1e-6 else BROKEN
        return vertex(at=self.s(x, 0, 5)) if x < end - 1e-6 else BROKEN


class R2lsDecoyG013(R2lsDecoy):
    gap = 0.13


class R2lsDecoyG05(R2lsDecoy):
    gap = 0.5


class R2lsDecoyG15(R2lsDecoy):
    gap = 1.5

