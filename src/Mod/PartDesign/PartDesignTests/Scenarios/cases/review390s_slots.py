# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r1s (ops#468): the two pieces of a plate's top face either side of a through slot
(twins of one source face, in (u, v) order, with ORD); the slot's rectangle is redrawn."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class SlotPieces(Scenario):
    """A plate (x 0..100, y 0..60, z 0..20) padded from a sketch; a pocket through all of a
    rectangle (x `x0`..`x1`, y -10..70) splits its top face into a left and a right piece. A
    datum point sits at the centre of each (`L`, `R`); the edit redraws the rectangle."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r1s"
    TIER = "F"
    SIZE = 100
    SCALE = 1.0
    REFS = ("L", "R")
    slot0 = (40.0, 50.0)
    slot1 = (40.0, 50.0)
    extra = None  # a second rectangle drawn in the edit

    def piece(self, which):
        s = self.scale
        a, b = self.slot
        if which == "L":
            lo, hi = 0.0, a
        else:
            lo, hi = b, 100.0
        xs = [(lo + hi) / 2 * s]
        if self.second and which == "R":
            # the second rectangle cuts the old right piece in two: the piece next to the first
            # slot is the one `R` stands for
            lo2, hi2 = self.second
            hi = lo2
            xs = [(lo + hi) / 2 * s]
        if hi - lo < 1e-6:
            return BROKEN
        return face(normal=V(0, 0, 1), through=V(0, 0, 20 * s), contains=V(xs[0], 30 * s, 20 * s))

    second = None

    def build(self, doc):
        s = self.scale
        self.slot = self.slot0
        self.second = None
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 100 * s, 60 * s), body)
        m.pad(body, plate, 20 * s)
        a, b = self.slot
        self.cutter = m.sketch(doc, "Slot", m.rectangle(a * s, -10 * s, b * s, 70 * s), body)
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.cutter
        self.pocket.Type = 1
        self.pocket.Midplane = True
        doc.recompute()
        for name in self.REFS:
            pt = body.newObject("PartDesign::Point", name)
            pt.AttachmentSupport = [(self.pocket, self.names(self.pocket, self.piece(name))[0])]
            pt.MapMode = "CenterOfMass"
            self.ref(name, pt, "AttachmentSupport", lambda name=name: self.piece(name))
        doc.recompute()

    def edit(self, doc):
        s = self.scale
        self.slot = self.slot1
        a, b = self.slot
        m.moveRectangle(self.cutter, a * s, -10 * s, b * s, 70 * s)
        if self.extra:
            lo, hi = self.extra
            for g in m.rectangle(lo * s, -10 * s, hi * s, 70 * s):
                self.cutter.addGeometry(g, False)
            self.second = self.extra
        doc.recompute()


class SlotToTheLeftEdge(SlotPieces):
    __doc__ = SlotPieces.__doc__ + " The slot moves to x 0..10: the left piece is gone, the right stays."
    slot1 = (0.0, 10.0)


class SlotToTheRightEdge(SlotPieces):
    __doc__ = SlotPieces.__doc__ + " The slot moves to x 90..100: the right piece is gone."
    slot1 = (90.0, 100.0)


class SlotWider(SlotPieces):
    __doc__ = SlotPieces.__doc__ + " The slot is widened to x 35..55: both pieces stay."
    slot1 = (35.0, 55.0)


class SlotPastTheCentre(SlotPieces):
    __doc__ = SlotPieces.__doc__ + " The slot moves to x 60..70: the left piece is the larger."
    slot1 = (60.0, 70.0)


class SecondSlotDrawn(SlotPieces):
    __doc__ = SlotPieces.__doc__ + " A second rectangle x 70..75 is drawn in the sketch: three pieces; `L` stays, `R` is the piece next to the first slot."
    extra = (70.0, 75.0)
    REFS = ("L",)


class SecondSlotDrawnAtTheLeft(SlotPieces):
    __doc__ = SlotPieces.__doc__ + " A second rectangle x 10..15 is drawn: three pieces; `R` stays; `L` is the piece next to the first slot."
    extra = (10.0, 15.0)
    REFS = ("R",)

    def piece(self, which):
        s = self.scale
        a, b = self.slot
        if which == "R":
            lo, hi = b, 100.0
        else:
            lo, hi = 0.0, a
            if self.second:
                lo = self.second[1]
        return face(normal=V(0, 0, 1), through=V(0, 0, 20 * s), contains=V((lo + hi) / 2 * s, 30 * s, 20 * s))
