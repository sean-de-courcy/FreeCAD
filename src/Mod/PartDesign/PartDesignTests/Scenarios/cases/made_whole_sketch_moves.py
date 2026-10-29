# SPDX-License-Identifier: LGPL-2.1-or-later
"""Review prA1b-r1 (ops#522): a far cap made whole again on the NEXT plate, the profile moved
inside its sketch (moveRectangle: the lines keep their geometry IDs), so the Pad's Placement
stays and the gone piece's saved point stays over the plate it lay on. The face under the saved
point is then the saved one (sameUpToFaces passes), while the cap made whole lies on the other
plate and holds the saved point only within the reach tolerance (holdsSavedCentre). The gone
piece's datum must break.

The models are uptopieces.py's (SeamRib, Ridge, Notch), with the mover "sketch"."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


def ridgePlate(x0, x1, height):
    corners = [V(x, y, height(x)) for x, y in ((x0, -10), (x1, -10), (x1, 10), (x0, 10))]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


def flatPlate(outline):
    corners = [V(x, y, 10) for x, y in outline]
    return Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]


class SketchMovedPlates(Scenario):
    """A Pad of the rectangle `rect` (sketch on XY_Plane) up to the shell of `plates()`
    (UpToShape, Refine off); a datum point at the centre of mass of each cap piece. The edit
    moves the rectangle inside the sketch by `move`."""

    abstract = True
    area = "uptoface"
    CLASSES = ("A",)
    ISSUE = "ops#522"
    FOUND_BY = "review prA1b-r1"
    TIER = "F"
    move = (0.0, 0.0)
    moved = False

    def shift(self):
        return self.move if self.moved else (0.0, 0.0)

    def build(self, doc):
        body = m.body(doc)
        faces = self.plates()
        plate = m.feature(doc, "Plate", Part.Shell(faces))
        profile = m.sketch(doc, "Profile", m.rectangle(*self.rect), body)
        profile.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), "")]
        profile.MapMode = "FlatFace"
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Type = "UpToShape"
        pad.UpToShape = (plate, ["Face%d" % i for i in range(1, len(faces) + 1)])
        pad.Refine = False
        doc.recompute()
        for name in self.REFS:
            expect = getattr(self, "".join(p if i == 0 else p.capitalize() for i, p in enumerate(name.split("_"))))
            point = body.newObject("PartDesign::Point", name.capitalize())
            point.AttachmentSupport = [(pad, self.names(pad, expect())[0])]
            point.MapMode = "CenterOfMass"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        body.Tip = pad

    def edit(self, doc):
        self.moved = True
        x0, y0, x1, y1 = self.rect
        dx, dy = self.move
        m.moveRectangle(doc.Profile, x0 + dx, y0 + dy, x1 + dx, y1 + dy)


class SeamRibSketch(SketchMovedPlates):
    """Two plates at z = 10, x -10..0 and 0..10, y -12..12 (B-spline); the rib x -0.1..0.3,
    y -10..10: a strip on the first plate (centre (-0.05, 0)), a piece on the second. The rib
    moves in its sketch by 0.12 along x, wholly onto the second plate: the strip is gone."""

    abstract = True
    AXES = ("M2", "E1")
    REFS = ("strip", "piece")
    rect = (-0.1, -10, 0.3, 10)
    move = (0.12, 0.0)

    def plates(self):
        return [
            flatPlate(((-10, -12), (0, -12), (0, 12), (-10, 12))),
            flatPlate(((0, -12), (10, -12), (10, 12), (0, 12))),
        ]

    def strip(self):
        x0 = -0.1 + self.shift()[0]
        return BROKEN if x0 >= 0 else face(contains=(x0 / 2, 0, 10))

    def piece(self):
        x0 = max(0, -0.1 + self.shift()[0])
        x1 = 0.3 + self.shift()[0]
        return face(contains=((x0 + x1) / 2, 0, 10))


class SeamRibSketchStripGone(SeamRibSketch):
    """Moved in the sketch by 0.12: the strip gone, the whole cap at x 0.02..0.42."""


class SeamRibSketchStripGoneFar(SeamRibSketch):
    """Moved in the sketch by 0.6, beyond the strip's reach: the control."""

    move = (0.6, 0.0)


class RidgeSketchStripGone(SketchMovedPlates):
    """Plates z = 10 + 2x (x -4..0) and z = 10 - 2x (x 0..4.5); the rectangle x -0.5..3, y 0..8
    has a strip on the first plate and a piece on the second. Moved in its sketch by 0.6 along
    x: the strip is gone, the piece is the whole cap on the second plate."""

    AXES = ("M2", "E1")
    REFS = ("strip", "piece")
    rect = (-0.5, 0, 3, 8)
    move = (0.6, 0.0)

    def plates(self):
        return [
            ridgePlate(-4, 0, lambda x: 10 + 2 * x),
            ridgePlate(0, 4.5, lambda x: 10 - 2 * x),
        ]

    def onCap(self, x):
        z = 10 + 2 * x if x < 0 else 10 - 2 * x
        return face(contains=(x, 4, z))

    def strip(self):
        x0 = -0.5 + self.shift()[0]
        return BROKEN if x0 >= 0 else self.onCap(x0 / 2)

    def piece(self):
        x0 = max(0, -0.5 + self.shift()[0])
        x1 = 3 + self.shift()[0]
        return self.onCap((x0 + x1) / 2)


class NotchSketchLGone(SketchMovedPlates):
    """Plates at z = 10: an L (x -10..4, y -10..10 without x 1..4, y 1..10), the square x 1..4,
    y 1..10, and x 4..20. The square x 0.5..2.5, y 0.5..2.5 has an L piece and a square piece;
    moved in its sketch by (0.5, 0.5) it lies wholly on the square plate: the L piece is gone."""

    AXES = ("M2", "E1")
    REFS = ("l_piece", "square")
    rect = (0.5, 0.5, 2.5, 2.5)
    move = (0.5, 0.5)

    def plates(self):
        outlines = (
            ((-10, -10), (4, -10), (4, 1), (1, 1), (1, 10), (-10, 10)),
            ((1, 1), (4, 1), (4, 10), (1, 10)),
            ((4, -10), (20, -10), (20, 10), (4, 10)),
        )
        return [flatPlate(o) for o in outlines]

    def lPiece(self):
        return BROKEN if self.moved else face(contains=(0.75, 2, 10))

    def square(self):
        return face(contains=(2, 2, 10) if not self.moved else (2.5, 2.5, 10))
