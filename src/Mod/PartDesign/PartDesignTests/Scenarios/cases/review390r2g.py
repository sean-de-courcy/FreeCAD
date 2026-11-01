# SPDX-License-Identifier: LGPL-2.1-or-later
"""Fork PR 390 round 2g review (decision 214's fix): the notch's twin lines, one told apart by a
connected vertex and the other placed alone, under moves that take either line away, bring a
lone line back to two, or land the survivor on the gone line's place.

A block 0..40 x 0..20 x 0..10 (all lengths times the scale); a pocket through all from a circle
radius r at (cx, -3) in an unattached sketch at z = 10: a notch in the front face (y = 0) whose
sides are vertical lines at x = cx -+ sqrt(r^2 - 9). A line off the block (x <= 0 or x >= 40) is
gone: its references must break. A line that stays is the same side of the notch (left or right)
and must be followed.
"""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Filleted, Scenario, Z, edge
from PartDesignTests.Scenarios import models as m

V = App.Vector
L, W, H, CY = 40.0, 20.0, 10.0, -3.0


class R2gNotch(Scenario):
    abstract = True
    area = "split"
    CLASSES = ("A",)
    AXES = ("M1", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2g"
    TIER = "F"
    SIZE = 40
    REFS = ("datum_left_line", "datum_right_line", "fillet_line")
    cx, r = 20.0, 5.0
    filletLeft = True
    byPlacement = False

    def half(self):
        return math.sqrt(self.r * self.r - CY * CY)

    def line(self, x):
        if x <= 1e-6 or x >= L - 1e-6:
            return BROKEN
        return edge("line", direction=Z, through=V(*self.s(x, 0, 0)))

    def leftLine(self):
        return self.line(self.cx - self.half())

    def rightLine(self):
        return self.line(self.cx + self.half())

    def build(self, doc):
        self.cx0 = self.cx
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, *self.s(L, W)), body)
        m.pad(body, profile, self.s(H))
        self.notchSketch = m.sketch(
            doc, "NotchSketch", [m.circle(*self.s(self.cx, CY, self.r))], body, z=self.s(H)
        )
        pocket = m.pocketThroughAll(body, self.notchSketch, "Notch")
        doc.recompute()
        refs = []
        if self.leftLine() is not BROKEN:
            refs.append(("datum_left_line", "LeftLinePlane", self.leftLine))
        if self.rightLine() is not BROKEN:
            refs.append(("datum_right_line", "RightLinePlane", self.rightLine))
        for key, name, which in refs:
            datum = body.newObject("PartDesign::Plane", name)
            datum.AttachmentSupport = [(pocket, self.names(pocket, which()))]
            datum.MapMode = "NormalToEdge"
            refs_owner = datum
            self.ref(key, refs_owner, "AttachmentSupport", which, Attached())
        doc.recompute()
        filleted = self.leftLine if self.filletLeft else self.rightLine
        if filleted() is not BROKEN:
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (pocket, self.names(pocket, filleted()))
            fillet.Radius = self.s(0.5)
            self.ref("fillet_line", fillet, "Base", filleted, Filleted(self.s(0.5)))

    def moveTo(self, cx, r=None):
        dx = cx - self.cx
        self.cx = cx
        if r is not None:
            self.r = r
        if self.byPlacement and r is None:
            p = self.notchSketch.Placement
            self.notchSketch.Placement = App.Placement(p.Base + V(self.s(dx), 0, 0), p.Rotation)
            return
        geometry = self.notchSketch.Geometry
        geometry[0].Center = V(*self.s(self.cx, CY), 0)
        geometry[0].Radius = self.s(self.r)
        self.notchSketch.Geometry = geometry


# G1: the right line goes (the mirror of r2f's left-goes): the left line, keyed by its connected
# vertex, becomes the lone line, named like the right one was.
class R2gRightGoes(R2gNotch):
    abstract = False

    def edit(self, doc):
        self.moveTo(37.0)


class R2gRightGoesByPlacement(R2gRightGoes):
    byPlacement = True


class R2gRightGoesFilletRight(R2gRightGoes):
    filletLeft = False


# G2: the right line goes and the left one lands where the right one was (circle moved and
# widened: half-chord 5 at cx 37, left line at 32 = the old right line).
class R2gRightGoesLeftLands(R2gNotch):
    abstract = False
    cx = 28.0

    def edit(self, doc):
        self.moveTo(37.0, math.sqrt(34.0))


class R2gRightGoesLeftLandsFilletRight(R2gRightGoesLeftLands):
    filletLeft = False


# G3: mirror of G2: the left line goes and the right one lands where the left one was.
class R2gLeftGoesRightLands(R2gNotch):
    abstract = False
    cx = 12.0

    def edit(self, doc):
        self.moveTo(3.0, math.sqrt(34.0))


class R2gLeftGoesRightLandsFilletRight(R2gLeftGoesRightLands):
    filletLeft = False


# G4: 1 -> 2: the notch over the right end (left line alone at 33) comes back to cx 20; the lone
# line is the notch's left side, now at 16.
class R2gLoneLeftComesBack(R2gNotch):
    abstract = False
    cx = 37.0
    REFS = ("datum_left_line", "fillet_line")

    def edit(self, doc):
        self.moveTo(20.0)


class R2gLoneLeftComesBackByPlacement(R2gLoneLeftComesBack):
    byPlacement = True


# G5: 1 -> 2 mirrored: the notch over the left end (right line alone at 7) comes back; the lone
# line is the right side, now at 24.
class R2gLoneRightComesBack(R2gNotch):
    abstract = False
    cx = 3.0
    filletLeft = False
    REFS = ("datum_right_line", "fillet_line")

    def edit(self, doc):
        self.moveTo(20.0)


# G6: 2 -> 2, the notch slid by its own width (8): the right line lands where... no line goes;
# the left line lands on the old right line's place (a twin trade by place).
class R2gSlideByWidth(R2gNotch):
    abstract = False
    cx = 14.0

    def edit(self, doc):
        self.moveTo(22.0)


# The modified stage: a slot across the block (a pocket through all, x in gx..gx+4) splits its top
# face into a left and a right piece, twins of one face, told apart by connected names or their
# place. The slot moves over an end: the piece there is gone, the other is the lone piece.
from PartDesignTests.Scenarios.harness import face  # noqa: E402


class R2gSlot(Scenario):
    abstract = True
    area = "split"
    CLASSES = ("A",)
    AXES = ("M1", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2g"
    TIER = "F"
    SIZE = 40
    REFS = ("top_left", "top_right")
    gx = 18.0
    SW = 4.0

    def piece(self, x0, x1):
        if x1 - x0 <= 1e-6:
            return BROKEN
        return face("plane", normal=Z, contains=V(*self.s((x0 + x1) / 2, W / 2, H)))

    def leftPiece(self):
        return self.piece(0.0, max(0.0, self.gx))

    def rightPiece(self):
        return self.piece(min(L, self.gx + self.SW), L)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, *self.s(L, W)), body)
        m.pad(body, profile, self.s(H))
        self.slotSketch = m.sketch(
            doc, "SlotSketch",
            m.rectangle(*self.s(self.gx, -1, self.gx + self.SW, W + 1)), body, z=self.s(H))
        pocket = m.pocketThroughAll(body, self.slotSketch, "Slot")
        doc.recompute()
        for key, name, which in (("top_left", "LeftPlane", self.leftPiece),
                                 ("top_right", "RightPlane", self.rightPiece)):
            datum = body.newObject("PartDesign::Plane", name)
            datum.AttachmentSupport = [(pocket, self.names(pocket, which()))]
            datum.MapMode = "FlatFace"
            self.ref(key, datum, "AttachmentSupport", which, Attached())
        doc.recompute()

    def moveTo(self, gx):
        dx = gx - self.gx
        self.gx = gx
        p = self.slotSketch.Placement
        self.slotSketch.Placement = App.Placement(p.Base + V(self.s(dx), 0, 0), p.Rotation)


class R2gSlotLeftGoes(R2gSlot):
    abstract = False

    def edit(self, doc):
        self.moveTo(-2.0)


class R2gSlotRightGoes(R2gSlot):
    abstract = False

    def edit(self, doc):
        self.moveTo(38.0)


class R2gSlotSlideByWidth(R2gSlot):
    abstract = False

    def edit(self, doc):
        self.moveTo(22.0)
