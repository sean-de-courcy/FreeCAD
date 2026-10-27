# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Corpus cases (ops#386, PR 366 rounds 8 and 9): far cap pieces of a Pad up to a shell of
plates. A Pad from below up to B-spline plates leaves a cap piece on each plate it reaches; a
datum point on each. The profile moves wholly onto one plate: the other plate's piece is gone and
its datum must break, never land on the cap made whole on the next plate (the round 7
verification's silent case, `ridgeB/m0.6`).

The `mover` says how the profile and the plates part: the profile through its sketch's
attachment offset ("offset"), through its unattached sketch's Placement ("placement"), through
the attachment offset of a datum plane its sketch is attached to ("datum"); or the plates the
other way, through their feature's Placement ("platesPlacement") or rebuilt there
("platesGeometry"). The Pad's Placement follows the sketch in "placement" and "datum", so in the
Pad's own frame every mover but "offset" leaves the profile where it was and moves the plates
under it. In round 8 the gone pieces' datums went quietly to the cap made whole in all four (debt
the PR introduced, loud on integration; the round 8 probes and the cloud review's S2). Round 9
(PLAN decision 152) refuses the made-whole rule for far caps: the gone pieces' datums break, and
so do the remaining pieces' (`piece`, `square`: right -> loud, as on integration) until ops#522
tells the plate under the cap.

The seam rib cases (round 9, the cloud review's S1): a long thin rib across a seam between two
plates at one height, its strip on the first plate gone when the rib moves wholly onto the
second; the whole cap's centre of mass lies within the strip's reach of its saved centre."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


def ridgePlate(x0, x1, height, dx=0.0):
    """The plane polygon over x0..x1, y -10..10 at z = height(x), as a B-spline face, moved by
    dx along x."""
    corners = [V(x + dx, y, height(x)) for x, y in ((x0, -10), (x1, -10), (x1, 10), (x0, 10))]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


def flatPlate(outline, dx=0.0, dy=0.0):
    """The polygon `outline` ((x, y) corners) at z = 10, moved by (dx, dy), as a B-spline face."""
    corners = [V(x + dx, y + dy, 10) for x, y in outline]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


class UpToPlates(Scenario):
    """A Pad of `profile()` up to the shell of `plates()` (UpToShape, Refine off), from a sketch
    on the XY plane, an unattached one (mover "placement"), or one on a datum plane DP on the XY
    plane (mover "datum"); a datum point at the centre of mass of the cap piece each reference
    gives. The edit moves the profile or the plates by `move` ((dx, dy)) as `mover` says and
    rebuilds the shell in `order`."""

    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    ISSUE = "ops#386"
    TIER = "G"
    move = (0.0, 0.0)
    order = (0, 1)
    moved = False
    mover = "offset"

    def profileShift(self):
        """How far the profile has moved, in the world: (dx, dy)."""
        if not self.moved or self.mover.startswith("plates"):
            return (0.0, 0.0)
        return self.move

    def plateShift(self):
        """How far the plates have moved, in the world: (dx, dy)."""
        if not self.moved or not self.mover.startswith("plates"):
            return (0.0, 0.0)
        return (-self.move[0], -self.move[1])

    def build(self, doc):
        body = m.body(doc)
        faces = self.plates()
        plate = m.feature(doc, "Plate", Part.Shell(faces))
        profile = m.sketch(doc, "Profile", self.profile(), body)
        xy = m.originFeature(body, "XY_Plane")
        if self.mover == "datum":
            datum = body.newObject("PartDesign::Plane", "DP")
            datum.AttachmentSupport = [(xy, "")]
            datum.MapMode = "FlatFace"
            profile.AttachmentSupport = [(datum, "")]
            profile.MapMode = "FlatFace"
        elif self.mover != "placement":
            profile.AttachmentSupport = [(xy, "")]
            profile.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
        pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            expect = getattr(self, self.expectation(name))
            point = body.newObject("PartDesign::Point", name.capitalize())
            point.AttachmentSupport = [(pad, self.names(pad, expect())[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        body.Tip = pad

    def expectation(self, name):
        """The method giving the reference `name`'s expected element."""
        return "".join(part if i == 0 else part.capitalize() for i, part in enumerate(name.split("_")))

    def edit(self, doc):
        shift = App.Placement(V(self.move[0], self.move[1], 0), App.Rotation())
        self.moved = True
        if self.mover == "offset":
            doc.Profile.AttachmentOffset = shift
        elif self.mover == "placement":
            doc.Profile.Placement = shift
        elif self.mover == "datum":
            doc.DP.AttachmentOffset = shift
        faces = self.plates()
        doc.Plate.Shape = Part.Shell([faces[i] for i in self.order])
        if self.mover == "platesPlacement":
            doc.Plate.Placement = shift.inverse()
        doc.Pad.UpToShape = (doc.Plate, ["Face%d" % i for i in range(1, len(faces) + 1)])

    def plates(self):
        """The plates, where the edit has put their geometry (moved only for "platesGeometry")."""
        dx, dy = self.plateShift() if self.mover == "platesGeometry" else (0.0, 0.0)
        return self.platesAt(dx, dy)


class RidgeEdit(UpToPlates):
    """Plates z = 10 + 2x (x -4..0) and z = 10 - 2x (x 0..4.5), meeting at 53 degrees, as one
    shell; the rectangle x -0.5..3, y 0..8 padded up to them. Its cap has a strip on the first
    plate (centre (-0.25, 4, 9.5)) and a piece on the second ((1.5, 4, 7)), a datum point at the
    centre of mass of each. The edit parts the profile and the plates by `move` along x."""

    abstract = True
    AXES = ("M2", "E5", "E2")
    FOUND_BY = "review pr366-r7"
    REFS = ("strip", "piece")
    move = (0.6, 0.0)

    def platesAt(self, dx, dy):
        return [
            ridgePlate(-4, 0, lambda x: 10 + 2 * x, dx),
            ridgePlate(0, 4.5, lambda x: 10 - 2 * x, dx),
        ]

    def profile(self):
        return m.rectangle(-0.5, 0, 3, 8)

    def onCap(self, x):
        """The cap piece over (x, 4): the face holding the plates' point there."""
        seam = self.plateShift()[0]
        z = 10 + 2 * (x - seam) if x < seam else 10 - 2 * (x - seam)
        return face(contains=(x, 4, z))

    def strip(self):
        seam = self.plateShift()[0]
        x0 = -0.5 + self.profileShift()[0]
        if x0 >= seam:
            return BROKEN
        return self.onCap((x0 + seam) / 2)

    def piece(self):
        seam = self.plateShift()[0]
        x0 = max(seam, -0.5 + self.profileShift()[0])
        x1 = 3 + self.profileShift()[0]
        return self.onCap((x0 + x1) / 2)


class RidgeStripGone(RidgeEdit):
    """Moved by 0.6: the strip is gone; the piece is the whole cap now."""


class RidgeStripGoneReordered(RidgeEdit):
    """Moved by 0.6 and the shell rebuilt the other way round."""

    order = (1, 0)


class RidgeStripShrinks(RidgeEdit):
    """Moved by 0.3: the strip is a thinner strip (x -0.2..0), the piece grows."""

    move = (0.3, 0.0)


class RidgePlacementStripGone(RidgeStripGone):
    """As RidgeStripGone, the profile moved through its unattached sketch's Placement."""

    FOUND_BY = "review pr366-r8"
    mover = "placement"


class RidgePlacementStripGoneReordered(RidgeStripGoneReordered):
    """As RidgeStripGoneReordered, the profile moved through its unattached sketch's Placement."""

    FOUND_BY = "review pr366-r8"
    mover = "placement"


class RidgeDatumStripGone(RidgeStripGone):
    """As RidgeStripGone, the profile moved through the datum plane its sketch is attached to (the
    round 8 cloud review's S2)."""

    FOUND_BY = "review pr366-r8"
    mover = "datum"


class RidgePlatesPlacedStripGone(RidgeStripGone):
    """As RidgeStripGone, the plates moved the other way through their feature's Placement."""

    FOUND_BY = "review pr366-r8"
    mover = "platesPlacement"


class RidgePlatesRebuiltStripGoneReordered(RidgeStripGoneReordered):
    """As RidgeStripGoneReordered, the plates rebuilt 0.6 the other way."""

    FOUND_BY = "review pr366-r8"
    mover = "platesGeometry"


class NotchEdit(UpToPlates):
    """Plates at z = 10, B-spline faces: an L-shaped one (x -10..4, y -10..10 without the square
    x 1..4, y 1..10), that square, and x 4..20; the square x 0.5..2.5, y 0.5..2.5 padded up to
    them has an L piece (datum `l_piece`, through (0.75, 2)) and a square piece (`square`, through
    (2, 2)). The profile and the plates part by (0.5, 0.5), the profile wholly on the square plate:
    the L piece is gone and its datum must break."""

    abstract = True
    AXES = ("M2", "E5")
    FOUND_BY = "review pr366-r8"
    REFS = ("l_piece", "square")
    order = (0, 1, 2)
    move = (0.5, 0.5)

    def platesAt(self, dx, dy):
        outlines = (
            ((-10, -10), (4, -10), (4, 1), (1, 1), (1, 10), (-10, 10)),
            ((1, 1), (4, 1), (4, 10), (1, 10)),
            ((4, -10), (20, -10), (20, 10), (4, 10)),
        )
        return [flatPlate(outline, dx, dy) for outline in outlines]

    def profile(self):
        return m.rectangle(0.5, 0.5, 2.5, 2.5)

    def lPiece(self):
        return BROKEN if self.moved else face(contains=(0.75, 2, 10))

    def square(self):
        return face(contains=(2, 2, 10))


class NotchPlacementLGone(NotchEdit):
    """The profile moved through its unattached sketch's Placement."""

    mover = "placement"


class NotchDatumLGoneReordered(NotchEdit):
    """The profile moved through the datum plane its sketch is attached to; the shell rebuilt with
    its first two plates swapped."""

    mover = "datum"
    order = (1, 0, 2)


class NotchPlatesRebuiltLGone(NotchEdit):
    """The plates rebuilt (0.5, 0.5) the other way."""

    mover = "platesGeometry"


class SeamRibEdit(UpToPlates):
    """Two plates at z = 10 meeting at a seam x = 0: x -10..0 and 0..10, y -12..12, B-spline faces
    (with plane faces the strip's cap is named by the bare projection, which the whole cap then
    takes: ops#513). The rib x -0.1..0.3, y -10..10 padded up to them has a strip on the
    first plate (datum `strip`, centre (-0.05, 0, 10), its reach 0.35) and a piece on the second
    (`piece`). The rib moved along x by `move` through its sketch's attachment offset: by 0.12 or
    0.2 it is wholly on the second plate, the strip gone, and the whole cap's centre of mass lies
    within the strip's reach of its saved centre (round 8 took that as holding it)."""

    abstract = True
    AXES = ("M2", "E5")
    FOUND_BY = "review pr366-r8"
    REFS = ("strip", "piece")
    move = (0.12, 0.0)

    def platesAt(self, dx, dy):
        return [
            flatPlate(((-10, -12), (0, -12), (0, 12), (-10, 12)), dx, dy),
            flatPlate(((0, -12), (10, -12), (10, 12), (0, 12)), dx, dy),
        ]

    def profile(self):
        return m.rectangle(-0.1, -10, 0.3, 10)

    def strip(self):
        x0 = -0.1 + self.profileShift()[0]
        return BROKEN if x0 >= 0 else face(contains=(x0 / 2, 0, 10))

    def piece(self):
        x0 = max(0, -0.1 + self.profileShift()[0])
        x1 = 0.3 + self.profileShift()[0]
        return face(contains=((x0 + x1) / 2, 0, 10))


class SeamRibStripGone(SeamRibEdit):
    """Moved by 0.12, B-spline plates."""


class SeamRibStripGoneFar(SeamRibEdit):
    """Moved by 0.3, beyond the strip's reach: the control."""

    move = (0.3, 0.0)
