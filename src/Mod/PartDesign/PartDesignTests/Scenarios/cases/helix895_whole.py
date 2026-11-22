# SPDX-License-Identifier: LGPL-2.1-or-later
"""ops#895: references on a helix's faces and edges through edits of its turns and pitch. A helix
has one side face per profile edge, as Onshape's (fork PR for ops#895); before, one per turn. Each
reference is made on the first turn, at a point a sixth of a turn from the start, and expected
after the edit on the face or edge through that point as the edit moved it: on a per-turn build
turn 1's face, on a whole-face build the whole face. These replace review pr390-r1s's and
pr390-r1's per-turn cases (review390s_helix, review390), whose references on turn 2 and 3 have no
counterpart once the turns are one face."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class HelixWhole(Scenario):
    """A core (cylinder radius 9 about Z, z -2 .. 28) and an AdditiveHelix about Z of a square
    profile (x 9..12, z 0..2 in an XZ sketch), pitch `pitch0`, `turns0` turns. The references, on
    the first turn at a sixth of a turn (60 degrees) from the start: the outer face (r 12), the
    top face (z 2 above the helix's start), the outer top edge (r 12, z 2), and the start cap (the
    profile's plane, y = 0 at x 9..12). The edit sets the turns, the pitch or the hand."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M4", "E2")
    ISSUE = "ops#895"
    FOUND_BY = "review pr895-r1"
    TIER = "F"
    SIZE = 30
    SCALE = 1.0
    turns0 = 2
    turns1 = 3
    pitch0 = 6.0
    pitch1 = 6.0
    left0 = False
    left1 = False
    REFS = ("outer", "top", "top_edge", "start_cap")
    ANGLE = math.pi / 3

    def at(self, r, z):
        """The point at radius r and height z above the profile's start, a sixth of a turn on."""
        s = self.scale
        angle = -self.ANGLE if self.left else self.ANGLE
        rise = self.pitch * self.ANGLE / (2 * math.pi)
        return V(r * math.cos(angle) * s, r * math.sin(angle) * s, (z + rise) * s)

    def predicate(self, name):
        s = self.scale
        if name == "outer":
            return face(surface="bsplinesurface", contains=self.at(12, 1))
        if name == "top":
            return face(surface="bsplinesurface", contains=self.at(10.5, 2))
        if name == "top_edge":
            return edge(contains=self.at(12, 2))
        return face(surface="plane", contains=V(10.5 * s, 0, 1 * s))

    def expect(self, name):
        return lambda: self.predicate(name)

    def build(self, doc):
        s = self.scale
        self.turns, self.pitch, self.left = self.turns0, self.pitch0, self.left0
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
        self.helix.LeftHanded = self.left
        doc.recompute()
        for name in self.REFS:
            pt = body.newObject("PartDesign::Point", name)
            pt.AttachmentSupport = [(self.helix, self.names(self.helix, self.predicate(name))[0])]
            pt.MapMode = "CenterOfMass"
            self.ref(name, pt, "AttachmentSupport", self.expect(name))
        doc.recompute()

    def edit(self, doc):
        s = self.scale
        self.turns, self.pitch, self.left = self.turns1, self.pitch1, self.left1
        self.helix.Pitch = self.pitch * s
        self.helix.Turns = self.turns
        self.helix.LeftHanded = self.left
        doc.recompute()


class HelixWholeTurnAdded(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " 2 -> 3 turns."
    abstract = False


class HelixWholeTurnRemoved(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " 3 -> 2 turns."
    abstract = False
    turns0, turns1 = 3, 2


class HelixWholeOneToTwo(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " 1 -> 2 turns: the cuts per turn begin."
    abstract = False
    turns0, turns1 = 1, 2


class HelixWholeTwoToOne(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " 2 -> 1 turn: the cuts per turn end."
    abstract = False
    turns0, turns1 = 2, 1


class HelixWholeFromPartOfATurn(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " 0.6 -> 3.4 turns."
    abstract = False
    turns0, turns1 = 0.6, 3.4


class HelixWholeToPartOfATurn(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " 3.4 -> 0.6 turns."
    abstract = False
    turns0, turns1 = 3.4, 0.6


class HelixWholePitchLonger(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " Pitch 6 -> 6.5, 2 turns: every point moves up."
    abstract = False
    turns1 = 2
    pitch1 = 6.5


class HelixWholeMadeLeftHanded(HelixWhole):
    __doc__ = HelixWhole.__doc__ + " The helix is made left handed: the points turn the other way."
    abstract = False
    turns1 = 2
    left1 = True
