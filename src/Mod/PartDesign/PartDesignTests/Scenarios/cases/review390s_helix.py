# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review pr390-r1s (ops#468): faces of a helix told apart only by their turn (twins in the maker's
order, no ORD since decision 173 (2)); edits change the count of turns or the pitch."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class HelixTurns(Scenario):
    """A core (cylinder radius 9 about Z, z -2 .. 28) and an AdditiveHelix about Z of a square
    profile (x 9..12, z 0..2 in an XZ sketch), pitch 6, `turns0` turns. Each turn's outer face
    (radius 12, area ~ 150.8, centre z = 4 + 6 (k - 1) for the k-th turn) is a reference. The edit
    changes the number of turns, or the pitch."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E2")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r1s"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    turns0 = 2
    turns1 = 3
    pitch0 = 6.0
    pitch1 = 6.0
    shift = 0.0
    dir = 1
    REFS = ("t1_outer", "t2_outer")

    def outer(self, k):
        s = self.scale
        # centre z of the outer face of turn k: the profile's mid-height (1) plus the pitch's
        # share: (k - 1) turns plus half a turn
        z = (1 + self.shift + self.dir * (self.pitch * (k - 1) + self.pitch / 2)) * s
        area = 2 * math.pi * 12 * 2 * s * s

        def where(f):
            return (
                isinstance(f.Surface, Part.BSplineSurface)
                and abs(f.Area - area) < 0.02 * area
                and abs(f.CenterOfMass.z - z) < 0.25 * s
            )

        return face(where=where)

    def exists(self, k):
        return k <= self.turns

    def expect(self, k):
        return lambda: self.outer(k) if self.exists(k) else BROKEN

    def build(self, doc):
        s = self.scale
        self.turns, self.pitch = self.turns0, self.pitch0
        body = m.body(doc)
        core = m.sketch(doc, "Core", [m.circle(0, 0, 9 * s)], body, z=-2 * s)
        m.pad(body, core, 30 * s)
        xz = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
        sk = m.sketch(doc, "HS", m.rectangle(9 * s, 0, 12 * s, 2 * s), body, placement=xz)
        doc.recompute()
        self.helix = body.newObject("PartDesign::AdditiveHelix", "Helix")
        self.helix.Profile = sk
        self.helix.ReferenceAxis = (sk, ["V_Axis"])
        self.helix.Mode = "pitch-turns-angle"
        self.helix.Pitch = self.pitch * s
        self.helix.Turns = self.turns
        doc.recompute()
        # datum points on the outer faces (a datum point attached to a face's centre)
        for k in (1, 2, 3):
            name = f"t{k}_outer"
            if name in self.REFS:
                self.point(doc, name, k, body)
        doc.recompute()

    def point(self, doc, name, k, body):
        pt = body.newObject("PartDesign::Point", name)
        pt.AttachmentSupport = [(self.helix, self.names(self.helix, self.outer(k))[0])]
        pt.MapMode = "CenterOfMass"
        self.ref(name, pt, "AttachmentSupport", self.expect(k))

    def edit(self, doc):
        s = self.scale
        self.turns, self.pitch = self.turns1, self.pitch1
        self.helix.Pitch = self.pitch * s
        self.helix.Turns = self.turns
        self.change(doc)
        doc.recompute()

    def change(self, doc):
        pass


class HelixTurnsAdded(HelixTurns):
    __doc__ = HelixTurns.__doc__ + " 2 -> 3 turns: the first two turns' faces stay."
    REFS = ("t1_outer", "t2_outer")


class HelixTurnsRemoved(HelixTurns):
    __doc__ = HelixTurns.__doc__ + " 3 -> 2 turns: the third turn's face goes."
    turns0, turns1 = 3, 2
    REFS = ("t1_outer", "t2_outer", "t3_outer")


class HelixPitchLonger(HelixTurns):
    __doc__ = HelixTurns.__doc__ + " Pitch 6 -> 6.5, 2 turns: every turn's face moves up."
    turns0 = turns1 = 2
    pitch1 = 6.5
    REFS = ("t1_outer", "t2_outer")


class HelixTurnsTwoToOne(HelixTurns):
    __doc__ = HelixTurns.__doc__ + " 2 -> 1 turn: the second turn's face goes, the first stays."
    turns0, turns1 = 2, 1
    REFS = ("t1_outer", "t2_outer")


class HelixTurnsOneToTwo(HelixTurns):
    __doc__ = HelixTurns.__doc__ + " 1 -> 2 turns: the first turn's face stays."
    turns0, turns1 = 1, 2
    REFS = ("t1_outer",)


class HelixShiftedByAPitch(HelixTurns):
    __doc__ = HelixTurns.__doc__ + (
        " The profile sketch moves up by one pitch: the first turn is now where the second was"
        " (the old place of turn 2 is occupied by turn 1)."
    )
    turns0 = turns1 = 2
    REFS = ("t1_outer", "t2_outer")

    def change(self, doc):
        s = self.scale
        self.shift = 6.0
        doc.HS.Placement = App.Placement(V(0, 0, self.shift * s), doc.HS.Placement.Rotation)


class HelixLeftHanded(HelixTurns):
    __doc__ = HelixTurns.__doc__ + " The helix is made left handed: the turns keep their heights."
    turns0 = turns1 = 2
    REFS = ("t1_outer", "t2_outer")

    def change(self, doc):
        self.helix.LeftHanded = True


class HelixReversed(HelixTurns):
    __doc__ = HelixTurns.__doc__ + (
        " The helix is reversed: it runs down from the profile, the first turn first."
    )
    turns0 = turns1 = 2
    REFS = ("t1_outer", "t2_outer")

    def change(self, doc):
        self.dir = -1
        self.helix.Reversed = True
