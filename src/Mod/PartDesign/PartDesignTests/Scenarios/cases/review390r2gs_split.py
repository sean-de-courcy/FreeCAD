# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r2gs (PLAN decision 214): pieces of a split face (the MOD path's connected
elements) under the widened twin test. A block 0..40 x 0..20 x 10; a slot pocket (depth 3) across
the full width in y from x = s0 to s1 splits the top face into pieces. Refs: a datum plane on a
top piece (FlatFace)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
L, W, H = 40, 20, 10


def piece(x0, x1):
    a, b = max(x0, 0), min(x1, L)
    if b - a < 1e-6:
        return BROKEN
    return face("plane", normal=Z, through=V(0, 0, H), contains=V((a + b) / 2, 10, H))


class Slot(Scenario):
    abstract = True
    area = "split"
    CLASSES = ("A",)
    AXES = ("M2", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r2gs"
    TIER = "F"
    REFS = ("left", "right")
    s0, s1 = 15, 25
    t0, t1 = 5, 12

    def pieceNow(self, which):
        a, b = self.cur
        return piece(0, a) if which == "left" else piece(b, L)

    def build(self, doc):
        self.cur = (self.s0, self.s1)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, W), body)
        m.pad(body, profile, H)
        self.sk = m.sketch(doc, "SlotSketch", m.rectangle(self.s0, -1, self.s1, W + 1), body, z=H)
        pocket = m.pocket(body, self.sk, 3, "Slot")
        doc.recompute()
        for which in self.REFS:
            d = body.newObject("PartDesign::Plane", which + "Plane")
            d.AttachmentSupport = [(pocket, self.names(pocket, self.pieceNow(which)))]
            d.MapMode = "FlatFace"
            self.ref(which, d, "AttachmentSupport", (lambda w: lambda: self.pieceNow(w))(which), Attached())
        doc.recompute()

    def edit(self, doc):
        self.cur = (self.t0, self.t1)
        m.moveRectangle(self.sk, self.t0, -1, self.t1, W + 1)


class LeftPieceGoes(Slot):
    t0, t1 = -1, 10


class RightPieceGoes(Slot):
    t0, t1 = 30, 41


class BothStay(Slot):
    pass


class LeftPieceGoesLoneRef(Slot):
    REFS = ("right",)
    t0, t1 = -1, 10


class RightPieceGoesLoneRef(Slot):
    REFS = ("left",)
    t0, t1 = 30, 41


class LoneBuiltPieceAppears(Slot):
    REFS = ("right",)
    s0, s1 = -1, 10
    t0, t1 = 14, 22


class LoneBuiltLeftAppears(Slot):
    REFS = ("left",)
    s0, s1 = 30, 41
    t0, t1 = 18, 26
