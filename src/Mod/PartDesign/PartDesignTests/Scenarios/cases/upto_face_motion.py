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

"""Corpus cases (ops#503, class D): an up-to shell's face moves, or a face is added under a cap piece.

Both cases are a Pad up to a nameless shell (a `Part::Feature` of B-spline faces at z = 10, whose
faces are known only by their index), whose far cap is in pieces, one per plate; a datum point sits
on a piece's centre of mass.

- ops#481 (`UpToHoleFillShift...`): a plate with a round hole (radius 3, centre (8, 3)) and the
  hole's fill; the Pad's profile is a disc (radius 3, centre (3, 3)) partly over the hole, so its
  cap is two pieces, the lens on the fill (M, 1 wide and 3.3 high) and the crescent on the plate
  (P). The edit shifts the hole and the disc together by more than M's size. M and P are the same
  pieces, moved rigidly by the shift: each reference must follow its piece (the design:
  `notes/ops481-upto-face-motion.md`, the support record and rules R1/R2; the probe was `p_r3twins`
  of the PR 340 batteries, 51 results).
- ops#483 (`ShellFaceAddedUnderCapPiece...`): two plates L (x -8..1) and R (x 1..18); the Pad's
  profile has two rectangles A (x 0..2) and B (x 5..8), so A's cap is CL on L (x 0..1) and CR on R
  (x 1..2). The shell is rebuilt with a narrow plate M (x 0.2..0.8) in the middle of L, in the
  order M, L', R', so the new plate takes Face1, the index CL's name was built on. CL's name now
  lands on A's piece on M, which holds CL's old centre (0.5, 1). The right answer is the piece on
  L' (x 0..0.2, its own plate) or a loud break, never the piece on M
  (`notes/upto-split-488-483-466.md` section 2: Q1). Variants: M appended last (the control: CL's
  name stays on L''s piece); Q2, the plates meeting at x 0 and 0.8 with the count kept; Q3, Q1
  with A moved left by 0.5 so its piece on L' reaches outside CL's old place. Q2 and Q3 are
  ambiguous on purpose, so a break is the only right answer there.
Ported from the class D design (`corpus/predicted/D.json`: ops481, ops483)."""

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    OwnOrBroken,
    Scenario,
    face,
)
from PartDesignTests.Scenarios import models as m

V = App.Vector
TOP = 10.0  # the shell's height


def bspline(x0, x1, y0, y1, z=TOP):
    """A B-spline face over a rectangle (no names, as `toNurbs()` shells have none)."""
    c = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    return Part.Face(Part.makePolygon(c + c[:1])).toNurbs().Faces[0]


def holedShell(cx, cy, radius, z=TOP):
    """A plate x, y -30..30 with a round hole, and the hole's fill, as one shell without names."""
    hole = Part.Circle(V(cx, cy, z), V(0, 0, 1), radius).toShape()
    c = [V(-30, -30, z), V(30, -30, z), V(30, 30, z), V(-30, 30, z)]
    # the plate's hole is the fill's boundary run the other way round (the same edge, reversed)
    plate = (
        Part.Face(
            Part.Plane(V(0, 0, z), V(0, 0, 1)),
            [Part.makePolygon(c + c[:1]), Part.Wire([hole.reversed()])],
        )
        .toNurbs()
        .Faces[0]
    )
    fill = Part.Face(Part.Wire([hole])).toNurbs().Faces[0]
    return Part.Shell([plate, fill])


def padUpToShell(doc, body, profile, shell, name="Plate"):
    """A Pad of the profile up to the whole `Part::Feature` holding the shell."""
    plate = m.feature(doc, name, shell)
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = profile
    pad.Type = "UpToShape"
    pad.UpToShape = (plate, [])
    pad.Refine = False
    doc.recompute()
    return plate, pad


def datumOn(body, pad, name, subName):
    point = body.newObject("PartDesign::Point", name)
    point.AttachmentSupport = [(pad, subName)]
    point.MapMode = "CenterOfMass"
    body.Tip = pad
    return point


class UpToHoleFillShift(Scenario):
    """ops#481: the hole and the disc shift together; M (on the fill) and P (on the plate) move
    with them."""

    abstract = True
    area = "upto-face-motion"
    CLASSES = ("D",)
    AXES = ("M2", "E4")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("fill_piece", "plate_piece")
    disc = (3.0, 3.0, 3.0)  # centre and radius of the profile
    hole = (8.0, 3.0, 3.0)
    shift = (0.0, 0.0)
    shiftBy = (5.0, 0.0)

    def lens(self):
        # the lens x 5..6 around (5.5, 3), on the fill: the one cap face holding this point
        dx, dy = self.shift
        return face(contains=(5.5 + dx, 3.0 + dy, TOP))

    def crescent(self):
        # the disc minus the hole: the cap face holding the disc's left part
        dx, dy = self.shift
        return face(contains=(1.0 + dx, 3.0 + dy, TOP))

    def build(self, doc):
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", [m.circle(*self.disc)], body)
        self.plate, pad = padUpToShell(doc, body, self.profile, holedShell(*self.hole))
        for name, where in (("fill_piece", self.lens), ("plate_piece", self.crescent)):
            point = datumOn(body, pad, "On" + name, self.names(pad, where())[0])
            self.ref(name, point, "AttachmentSupport", where, Attached())
        doc.recompute()

    def moveTo(self, dx, dy):
        self.shift = (dx, dy)
        centre = V(self.disc[0] + dx, self.disc[1] + dy, 0)
        self.profile.moveGeometry(0, 3, centre, False)
        self.plate.Shape = holedShell(self.hole[0] + dx, self.hole[1] + dy, self.hole[2])

    def edit(self, doc):
        self.moveTo(*self.shiftBy)


class UpToHoleFillShiftedAlongX(UpToHoleFillShift):
    """Hole and disc shifted by (5, 0)."""

    shiftBy = (5.0, 0.0)


class UpToHoleFillShiftedDiagonally(UpToHoleFillShift):
    """Hole and disc shifted by (3, 3)."""

    shiftBy = (3.0, 3.0)


class UpToHoleFillShiftedDown(UpToHoleFillShift):
    """Hole and disc shifted by (0, -3.5)."""

    shiftBy = (0.0, -3.5)


class ShellFaceAddedUnderCapPiece(Scenario):
    """ops#483: a narrow face M is added to the shell and takes the first index; CL's name
    lands on A's piece on M."""

    abstract = True
    area = "upto-face-added"
    CLASSES = ("D",)
    AXES = ("M2", "E4")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("cl_centre",)

    def before(self):
        return Part.Shell([bspline(-8, 1, -8, 9), bspline(1, 18, -8, 9)])

    def after(self):
        """The faces of the rebuilt shell, the new one first."""
        return Part.Shell(
            [bspline(0.2, 0.8, -8, 9), bspline(-8, 0.2, -8, 9), bspline(0.8, 18, -8, 9)]
        )

    def cl(self):
        return face(contains=(0.5, 1.0, TOP))

    def expectation(self):
        raise NotImplementedError

    def brokenAfterEdit(self):
        """BROKEN once the shell is rebuilt (the reference is judged correct before)."""
        return BROKEN if self.stepName == "edit" else self.cl()

    def build(self, doc):
        body = m.body(doc)
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(0, 0, 2, 2) + m.rectangle(5, 0, 8, 3), body
        )
        self.plate, pad = padUpToShell(doc, body, self.profile, self.before())
        point = datumOn(body, pad, "OnCL", self.names(pad, self.cl())[0])
        self.ref("cl_centre", point, "AttachmentSupport", self.expectation, Attached())
        doc.recompute()

    def edit(self, doc):
        self.plate.Shape = self.after()


class ShellFaceAddedUnderCapPieceQ1(ShellFaceAddedUnderCapPiece):
    """Q1: L' x -8..0.2, M x 0.2..0.8, R' x 0.8..18, in the order M, L', R'. A has three pieces
    now; CL's own is the one on L' (x 0..0.2, centre (0.1, 1))."""

    def expectation(self):
        return OwnOrBroken(face(contains=(0.1, 1.0, TOP)))


class ShellFaceAddedUnderCapPieceLast(ShellFaceAddedUnderCapPiece):
    """Q1 with M appended last (it takes Face3; L' keeps Face1): CL's name stays on L''s
    piece, which is its own."""

    def after(self):
        return Part.Shell(
            [bspline(-8, 0.2, -8, 9), bspline(0.8, 18, -8, 9), bspline(0.2, 0.8, -8, 9)]
        )

    def expectation(self):
        return OwnOrBroken(face(contains=(0.1, 1.0, TOP)))


class ShellFaceAddedUnderCapPieceCountKept(ShellFaceAddedUnderCapPiece):
    """Q2: the plates meet at x 0 and 0.8 (L' x -8..0, M x 0..0.8, R' x 0.8..18), order M, L',
    R'. A has two pieces, on M and R', as before; CL's name lands on M's piece, which holds CL's
    centre, but A has no piece on L' any more: nothing is CL's own, so a break is the answer."""

    def after(self):
        return Part.Shell([bspline(0, 0.8, -8, 9), bspline(-8, 0, -8, 9), bspline(0.8, 18, -8, 9)])

    def expectation(self):
        return self.brokenAfterEdit()


class ShellFaceAddedUnderCapPieceAndMoved(ShellFaceAddedUnderCapPiece):
    """Q3: Q1's shell and A moved left by 0.5 (x -0.5..1.5): its piece on L' (x -0.5..0.2) reaches
    outside CL's old place, so it is not obviously CL's: a break is the answer."""

    def expectation(self):
        return self.brokenAfterEdit()

    def edit(self, doc):
        super().edit(doc)
        m.moveRectangle(self.profile, -0.5, 0, 1.5, 2)
