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

"""Corpus cases (ops#386, PR 366 round 8): far cap pieces of a Pad up to a shell of plates. A Pad
from below up to B-spline plates leaves a cap piece on each plate it reaches; a datum point on
each. The profile moves wholly onto one plate: the other plate's piece is gone and its datum must
break, never land on the cap made whole on the next plate (the round 7 verification's silent case,
`ridgeB/m0.6`).

The `Placement` cases move the profile through its sketch's Placement (an unattached sketch; the
Pad's Placement follows it) instead of its attachment offset. Their gone pieces' datums go quietly
to the cap made whole on PR 366 (round 8): debt the PR introduces (its made-whole rule judges the
saved point in the Pad's own frame, which moved with the profile), loud on integration. PR 366
doesn't merge until they break."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


def ridgePlate(x0, x1, height):
    """The plane polygon over x0..x1, y -10..10 at z = height(x), as a B-spline face."""
    corners = [V(x, y, height(x)) for x, y in ((x0, -10), (x1, -10), (x1, 10), (x0, 10))]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


def upToPlates(case, doc, profileGeometry, refs):
    """A Pad of the profile up to the shell of case.plates(), from a sketch on the XY plane, or an
    unattached one if case.byPlacement; a datum point at the centre of mass of the cap piece each
    of `refs` ({name: expectation}) gives, as the reference `name`."""
    body = m.body(doc)
    faces = case.plates()
    plate = m.feature(doc, "Plate", Part.Shell(faces))
    profile = m.sketch(doc, "Profile", profileGeometry, body)
    if not case.byPlacement:
        profile.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
        profile.MapMode = "FlatFace"
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Type = "UpToShape"
    pad.UpToShape = (plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
    pad.Refine = False
    doc.recompute()
    for name, expect in refs.items():
        point = body.newObject("PartDesign::Point", name.capitalize())
        point.AttachmentSupport = [(pad, case.names(pad, expect())[0])]
        point.MapMode = "CenterOfMass"
        case.ref(name, point, "AttachmentSupport", expect, Attached())
    body.Tip = pad


def moveOntoPlates(case, doc, move):
    """The profile moved by `move` ((dx, dy)): its attachment offset, or its Placement if
    case.byPlacement; the shell rebuilt from case.plates() in case.order."""
    placement = App.Placement(V(move[0], move[1], 0), App.Rotation())
    if case.byPlacement:
        doc.Profile.Placement = placement
    else:
        doc.Profile.AttachmentOffset = placement
    faces = case.plates()
    doc.Plate.Shape = Part.Shell([faces[i] for i in case.order])
    doc.Pad.UpToShape = (doc.Plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
    case.moved = True


class RidgeEdit(Scenario):
    """Plates z = 10 + 2x (x -4..0) and z = 10 - 2x (x 0..4.5), meeting at 53 degrees, as one
    shell (UpToShape); the rectangle x -0.5..3, y 0..8 in a sketch on the XY plane, padded up to
    them. Its cap has a strip on the first plate (centre (-0.25, 4, 9.5)) and a piece on the
    second ((1.5, 4, 7)), a datum point at the centre of mass of each. The edit moves the profile
    by `move` along x (the sketch's attachment offset) and rebuilds the shell in `order`."""

    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E5", "E2")
    ISSUE = "ops#386"
    FOUND_BY = "review pr366-r7"
    TIER = "G"
    REFS = ("strip", "piece")
    move = 0.0
    order = (0, 1)
    moved = False
    byPlacement = False

    def plates(self):
        return [ridgePlate(-4, 0, lambda x: 10 + 2 * x), ridgePlate(0, 4.5, lambda x: 10 - 2 * x)]

    def onCap(self, x):
        """The cap piece over (x, 4): the face holding the plates' point there."""
        z = 10 + 2 * x if x < 0 else 10 - 2 * x
        return face(contains=(x, 4, z))

    def strip(self):
        x0 = -0.5 + (self.move if self.moved else 0)
        if x0 >= 0:
            return BROKEN
        return self.onCap(x0 / 2)

    def piece(self):
        x0 = max(0, -0.5 + (self.move if self.moved else 0))
        x1 = 3 + (self.move if self.moved else 0)
        return self.onCap((x0 + x1) / 2)

    def build(self, doc):
        upToPlates(
            self, doc, m.rectangle(-0.5, 0, 3, 8), {"strip": self.strip, "piece": self.piece}
        )

    def edit(self, doc):
        moveOntoPlates(self, doc, (self.move, 0))


class RidgeStripGone(RidgeEdit):
    """Moved by 0.6: the strip is gone; the piece is the whole cap now."""

    move = 0.6


class RidgeStripGoneReordered(RidgeEdit):
    """Moved by 0.6 and the shell rebuilt the other way round."""

    move = 0.6
    order = (1, 0)


class RidgeStripShrinks(RidgeEdit):
    """Moved by 0.3: the strip is a thinner strip (x -0.2..0), the piece grows."""

    move = 0.3


class RidgePlacementStripGone(RidgeStripGone):
    """As RidgeStripGone, the profile moved through its sketch's Placement: debt PR 366 introduces
    (its strip's datum goes quietly to the cap made whole), loud on integration."""

    FOUND_BY = "review pr366-r8"
    byPlacement = True


class RidgePlacementStripGoneReordered(RidgeStripGoneReordered):
    """As RidgeStripGoneReordered, the profile moved through its sketch's Placement (debt, as
    RidgePlacementStripGone)."""

    FOUND_BY = "review pr366-r8"
    byPlacement = True


class NotchPlacementLGone(Scenario):
    """Plates at z = 10, B-spline faces: an L-shaped one (x -10..4, y -10..10 without the square
    x 1..4, y 1..10), that square, and x 4..20; the square x 0.5..2.5, y 0.5..2.5 padded up to
    them has an L piece (datum `l_piece`, through (0.75, 2)) and a square piece (`square`, through
    (2, 2)). The profile moved by (0.5, 0.5) through its sketch's Placement, wholly onto the square
    plate: the L piece is gone and its datum must break. On PR 366 (round 8) it goes quietly to the
    cap made whole (debt the PR introduces, as RidgePlacementStripGone); loud on integration."""

    area = "uptoface"
    CLASSES = ("A",)
    AXES = ("M2", "E5")
    ISSUE = "ops#386"
    FOUND_BY = "review pr366-r8"
    TIER = "G"
    REFS = ("l_piece", "square")
    order = (0, 1, 2)
    moved = False
    byPlacement = True

    def plates(self):
        outlines = (
            ((-10, -10), (4, -10), (4, 1), (1, 1), (1, 10), (-10, 10)),
            ((1, 1), (4, 1), (4, 10), (1, 10)),
            ((4, -10), (20, -10), (20, 10), (4, 10)),
        )
        faces = []
        for outline in outlines:
            corners = [V(x, y, 10) for x, y in outline]
            faces.append(Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0])
        return faces

    def lPiece(self):
        return BROKEN if self.moved else face(contains=(0.75, 2, 10))

    def square(self):
        return face(contains=(2, 2, 10))

    def build(self, doc):
        upToPlates(
            self,
            doc,
            m.rectangle(0.5, 0.5, 2.5, 2.5),
            {"l_piece": self.lPiece, "square": self.square},
        )

    def edit(self, doc):
        moveOntoPlates(self, doc, (0.5, 0.5))
