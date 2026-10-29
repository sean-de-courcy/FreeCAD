# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review cases for fork PR 390 round 1 (ops#468): twins in the maker's order without ORD
(decision 173 (2)). An AdditiveHelix of a 1 x 1 square profile (x 2..3, y 0..1 at scale 1)
about the sketch's V axis: OCCT splits each swept face per turn, so the outer face (radius 3)
is a group of twins, one per turn, in the spine's order. References are datum points at a
turn's outer face's centre of mass; the expected face is the outer face of the same turn
(counted from the profile) on the edited model, or a break where that turn is gone."""

from PartDesignTests.Scenarios.harness import BROKEN, Scenario, face
from PartDesignTests.Scenarios import models as m


class HelixTurnsCase(Scenario):
    """An AdditiveHelix of a 1 x 1 square profile (x 2..3, y 0..1, scale 1) about the V axis,
    pitch 3: the outer face is one twin per turn; references on a turn's outer face."""

    abstract = True
    area = "twins"
    CLASSES = ("A",)
    AXES = ("M2", "E1")
    ISSUE = "ops#468"
    FOUND_BY = "review pr390-r1"
    TIER = "F"
    SIZE = 10
    SCALE = 60
    pitch0 = pitch1 = 3.0
    height0 = height1 = 6.0
    REFS = ("t0", "t1")
    dy0 = dy1 = 0.0  # the profile's offset along the axis
    rx0 = rx1 = 0.0  # the profile's offset away from the axis
    redraw = False
    leftHanded = False

    def outer(self, turn):
        """The outer face (every vertex at radius 3) of turn `turn` (0 from the profile): its
        lowest vertex at turn * pitch along the axis; BROKEN where the helix has no such turn."""
        r = self.s(3.0 + self.rx)
        y0 = self.s(self.dy + turn * self.pitch)
        tol = 1e-6 * self.s(10.0) + 1e-7
        if turn * self.pitch > self.height - 1e-9:
            return BROKEN

        def test(f):
            if not f.Vertexes:
                return False
            radii = [(v.Point.x**2 + v.Point.z**2) ** 0.5 for v in f.Vertexes]
            if max(abs(x - r) for x in radii) > tol:
                return False
            return abs(min(v.Point.y for v in f.Vertexes) - y0) < tol

        return face(where=test)

    def build(self, doc):
        self.pitch, self.height = self.pitch0, self.height0
        self.dy, self.rx = self.dy0, self.rx0
        body = m.body(doc)
        profile = m.sketch(
            doc, "Profile", m.rectangle(*self.s(2 + self.rx, self.dy, 3 + self.rx, 1 + self.dy)), body
        )
        self.profile = profile
        self.helix = body.newObject("PartDesign::AdditiveHelix", "Helix")
        self.helix.Profile = profile
        self.helix.ReferenceAxis = (profile, ["V_Axis"])
        self.helix.Pitch = self.s(self.pitch)
        self.helix.Height = self.s(self.height)
        doc.recompute()
        for name in self.REFS:
            turn = int(name[1:])
            point = doc.addObject("Part::DatumPoint", name)
            point.AttachmentSupport = [
                (self.helix, self.names(self.helix, self.outer(turn))[0])
            ]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", lambda turn=turn: self.outer(turn))
        doc.recompute()

    def edit(self, doc):
        self.pitch, self.height = self.pitch1, self.height1
        self.dy, self.rx = self.dy1, self.rx1
        corners = self.s(2 + self.rx, self.dy, 3 + self.rx, 1 + self.dy)
        if self.redraw:
            self.profile.deleteAllGeometry()
            self.profile.addGeometry(m.rectangle(*corners), False)
        elif (self.dy0, self.rx0) != (self.dy1, self.rx1):
            m.moveRectangle(self.profile, *corners)
        self.helix.Pitch = self.s(self.pitch)
        self.helix.Height = self.s(self.height)
        if self.leftHanded:
            self.helix.LeftHanded = True
        doc.recompute()


class HelixTurnAddedAtTheEnd(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " Height 6 -> 9 (2 -> 3 turns, pitch 3): turns 0 and 1 stay."
    height1 = 9.0


class HelixTurnRemovedAtTheEnd(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " Height 9 -> 6 (3 -> 2 turns): turn 2 goes, 0 and 1 stay."
    REFS = ("t0", "t1", "t2")
    height0, height1 = 9.0, 6.0


class HelixPitchDownTurnAdded(HelixTurnsCase):
    __doc__ = (
        HelixTurnsCase.__doc__
        + " Pitch 3 -> 2 at height 6 (2 -> 3 turns): each turn moves down; turn 1's old place"
        + " (y 3..7) is nearer turn 2's new one (y 4..7) than turn 1's (y 2..5)."
    )
    pitch1 = 2.0


class HelixPitchUpTurnRemoved(HelixTurnsCase):
    __doc__ = (
        HelixTurnsCase.__doc__
        + " Pitch 2 -> 3 at height 6 (3 -> 2 turns): turn 2 goes, turn 1 moves up onto about"
        + " where turn 2 was."
    )
    REFS = ("t0", "t1", "t2")
    pitch0, pitch1 = 2.0, 3.0


class HelixPitchDownSameTurns(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " Pitch 3 -> 2, height 6 -> 4: still 2 turns, both move down."
    pitch1, height1 = 2.0, 4.0


class HelixDownToOneTurn(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " Height 6 -> 3 (2 -> 1 turn): turn 1 goes, turn 0 stays alone."
    height1 = 3.0


class HelixUpFromOneTurn(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " Height 3 -> 6 (1 -> 2 turns): the lone turn 0 stays turn 0."
    REFS = ("t0",)
    height0, height1 = 3.0, 6.0


class HelixPitchUpTurnLandsOnTheOld(HelixTurnsCase):
    __doc__ = (
        HelixTurnsCase.__doc__
        + " Pitch 2 -> 4, height 6 -> 8 (3 -> 2 turns): turn 2 goes, and turn 1 now starts where"
        + " turn 2 started (y 4)."
    )
    REFS = ("t0", "t1", "t2")
    pitch0, pitch1 = 2.0, 4.0
    height1 = 8.0


class HelixProfileUpOnePitch(HelixTurnsCase):
    __doc__ = (
        HelixTurnsCase.__doc__
        + " The profile moved 3 up the axis (one pitch, its lines kept): turn 0 now sits where"
        + " turn 1 was; each turn's reference follows its turn."
    )
    dy1 = 3.0


class HelixProfileUpHalfPitch(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " The profile moved 1.5 up the axis: each turn follows."
    dy1 = 1.5


class HelixProfileOutward(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " The profile moved 0.5 away from the axis: each turn follows."
    rx1 = 0.5


class HelixProfileRedrawn(HelixTurnsCase):
    __doc__ = (
        HelixTurnsCase.__doc__
        + " The profile's rectangle deleted and drawn again at the same place (new geometry ids)."
    )
    redraw = True


class HelixProfileRedrawnUpOnePitch(HelixProfileRedrawn):
    __doc__ = HelixProfileRedrawn.__doc__ + " One pitch (3) higher up the axis."
    dy1 = 3.0


class HelixMadeLeftHanded(HelixTurnsCase):
    __doc__ = HelixTurnsCase.__doc__ + " LeftHanded set: each turn is mirrored in place and follows."
    leftHanded = True


class HelixMadeLeftHandedTurnAdded(HelixMadeLeftHanded):
    __doc__ = HelixMadeLeftHanded.__doc__ + " And height 6 -> 9 (2 -> 3 turns)."
    height1 = 9.0
