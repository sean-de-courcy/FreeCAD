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

"""Corpus cases (ops#500, class A; also class D, ops#503): a sweep up to a shell of tilted plates,
datums on a later feature (PR 366 round 6, F2 = ops#498).

Four B-spline plates side by side along X make an up-to shell (all of y -10..10): x -3..1 rises
one in height per unit (height 10 at x = 1), x 1..1.2 is steep (it drops from 10 to 8), and x 1.2..20
is flat at height 8. A Pad of a 2 x 2 square at the origin (z = 0), with a 2 x 3 rectangle at
x 12..14 in the same sketch, goes up to the shell; a SubtractiveBox sits after the Pad. On the
Tip's far end the square leaves a cap piece on each plate it crosses (x 0..1, 1..1.2, 1.2..2)
and a piece of its bottom and top edges on each; the left edge (x = 0) and the right edge (x = 2)
are single pieces. A datum point (CenterOfMass) is attached to each of these 11 pieces on the Tip
(the SubtractiveBox). The profile then moves by 2 in X (its sketch's AttachmentOffset), so it
leaves the first two plates and covers the third (x 2..3) and the fourth (x 3..4): a datum must
end on the piece of the same profile edge (or the cap) on the same plate, a whole edge follows the
profile, and the pieces on the plates the profile left must break.
`SweepFoldMoveReorder` also rebuilds the shell with its faces in another order.
Ported from `work/pr366-r6v/p_r6x.py` (`X_SET=fold`, `X_TIP=subbox`, the sq profile, the move
(2, 0); `p_v3.py`; `corpus/predicted/A.json`: ops498|sweep_from_a_later_feature_row251)."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, edge, face
from PartDesignTests.Scenarios import models as m

V = App.Vector

TOP = 10.0  # the height of the shell at x = 1
STEP = -2.0  # the drop over the steep plate
XS = (-3.0, 1.0, 1.2, 3.0, 20.0)  # the plates' x ranges
SIDE = 2.0  # the square
TOL = 1e-6


def height(i, x):
    """The height of plate i at x."""
    return (
        TOP + (x - 1.0),
        TOP + STEP * (x - 1.0) / 0.2,
        TOP + STEP,
        TOP + STEP,
    )[i]


def plate(i):
    xa, xb = XS[i], XS[i + 1]
    corners = [(xa, -10.0), (xb, -10.0), (xb, 10.0), (xa, 10.0)]
    points = [V(x, y, height(i, x)) for x, y in corners]
    return Part.Face(Part.makePolygon(points + points[:1])).toNurbs().Faces[0]


def shell(order=(0, 1, 2, 3)):
    faces = [plate(i) for i in range(4)]
    return Part.Shell([faces[i] for i in order])


class SweepFold(Scenario):
    """The model and its references; a subclass moves the profile (and maybe reorders the shell)."""

    abstract = True
    area = "sweep-later-feature"
    CLASSES = ("A", "D")
    AXES = ("M2", "E4")
    ISSUE = "ops#500"
    FOUND_BY = "port"
    TIER = "F"
    # E<j>_p<i>: the piece of the square's edge j (0 bottom, 1 right, 2 top, 3 left) on plate i
    # before the edit; C_p<i>: its cap on plate i
    REFS = (
        "E0_p0",
        "E0_p1",
        "E0_p2",
        "E1_p2",
        "E2_p0",
        "E2_p1",
        "E2_p2",
        "E3_p0",
        "C_p0",
        "C_p1",
        "C_p2",
    )
    PIECES = {  # ref: (profile edge, plate), edge None for the cap
        "E0_p0": (0, 0),
        "E0_p1": (0, 1),
        "E0_p2": (0, 2),
        "E1_p2": (1, 2),
        "E2_p0": (2, 0),
        "E2_p1": (2, 1),
        "E2_p2": (2, 2),
        "E3_p0": (3, 0),
        "C_p0": (None, 0),
        "C_p1": (None, 1),
        "C_p2": (None, 2),
    }
    move = 2.0  # the profile's offset in X after the edit
    order = None  # the shell's face order after the edit

    def __init__(self, config):
        super().__init__(config)
        self.dx = 0.0  # the profile's offset in X now

    # Geometry of the pieces at the profile's offset dx

    def span(self, plateIndex):
        """The x range of the square over plate i at the current offset, or None."""
        x0, x1 = max(self.dx, XS[plateIndex]), min(self.dx + SIDE, XS[plateIndex + 1])
        return (x0, x1) if x1 - x0 > TOL else None

    def horizontal(self, y, plateIndex):
        span = self.span(plateIndex)
        if span is None:
            return None
        points = [V(x, y, height(plateIndex, x)) for x in span]
        centre = (points[0] + points[1]) * 0.5
        length = (points[1] - points[0]).Length
        return edge(
            where=lambda e: (e.CenterOfMass - centre).Length < TOL and abs(e.Length - length) < TOL
        )

    def vertical(self, x):
        """The square's left or right edge (a whole edge, wherever the plates carry it)."""
        plateIndex = next(i for i in range(4) if XS[i] + TOL < x < XS[i + 1] - TOL)
        centre = V(x, SIDE / 2, height(plateIndex, x))
        return edge(
            where=lambda e: (e.CenterOfMass - centre).Length < TOL and abs(e.Length - SIDE) < TOL
        )

    def cap(self, plateIndex):
        span = self.span(plateIndex)
        if span is None:
            return None
        x0, x1 = span
        centre = V((x0 + x1) / 2, SIDE / 2, height(plateIndex, (x0 + x1) / 2))
        slope = (height(plateIndex, x1) - height(plateIndex, x0)) / (x1 - x0)
        area = (x1 - x0) * SIDE * math.sqrt(1 + slope**2)
        return face(
            where=lambda f: (f.CenterOfMass - centre).Length < TOL and abs(f.Area - area) < 1e-5
        )

    def expected(self, name):
        """The predicate of the piece, or BROKEN where the profile has left the plate."""
        edgeIndex, plateIndex = self.PIECES[name]
        if edgeIndex is None:
            piece = self.cap(plateIndex)
        elif edgeIndex in (1, 3):
            piece = self.vertical(self.dx + (SIDE if edgeIndex == 1 else 0.0))
        else:
            piece = self.horizontal(0.0 if edgeIndex == 0 else SIDE, plateIndex)
        return BROKEN if piece is None else piece

    def build(self, doc):
        body = m.body(doc)
        self.shape = doc.addObject("Part::Feature", "Plates")
        self.shape.Shape = shell()
        self.sketch = body.newObject("Sketcher::SketchObject", "Profile")
        self.sketch.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), [""])]
        self.sketch.MapMode = "FlatFace"
        self.sketch.addGeometry(m.rectangle(0, 0, SIDE, SIDE) + m.rectangle(12, 0, 14, 3), False)
        self.pad = m.pad(body, self.sketch, 1)
        self.pad.Type = "UpToShape"
        self.pad.UpToShape = (self.shape, [f"Face{i + 1}" for i in range(4)])
        doc.recompute()
        tip = body.newObject("PartDesign::SubtractiveBox", "Tip")
        tip.Length = tip.Width = tip.Height = 0.5
        tip.MapMode = "Deactivated"
        tip.AttachmentOffset = App.Placement()
        tip.Placement = App.Placement(V(12.75, 1, 2), App.Rotation())
        doc.recompute()
        for name in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(tip, self.names(tip, self.expected(name))[0])]
            point.MapMode = "CenterOfMass"
            body.Tip = tip
            self.ref(
                name,
                point,
                "AttachmentSupport",
                lambda name=name: self.expected(name),
                Attached(),
            )

    def edit(self, doc):
        self.dx = self.move
        self.sketch.AttachmentOffset = App.Placement(V(self.move, 0, 0), App.Rotation())
        if self.order:
            self.shape.Shape = shell(self.order)
            self.pad.UpToShape = (self.shape, [f"Face{i + 1}" for i in range(4)])


class SweepFoldMove(SweepFold):
    """The profile moves by 2 in X."""


class SweepFoldMoveReorder(SweepFold):
    """The profile moves by 2 in X and the shell's faces are rebuilt in the order 2, 1, 0, 3."""

    AXES = ("M2", "E2", "E4")
    order = (2, 1, 0, 3)
