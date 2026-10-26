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

"""Corpus cases (ops#394, class D): a board redrawn one thickness over, so that another of its
edges lands exactly on the chamfered edge's saved place.

The chamfered edge's line is drawn again (new geometry IDs: no name relates the old edge to the
new one) while the board moves by its own thickness. The exact place (XP, fork PR 379) takes the
one element at the saved place, which is the board's other top edge. The class D design accepts
that pick, quietly (`notes/naming-class-D.md` 3.1, row 173, "a rigid move by the part's own
dimension": the element at the identical place is taken where the old element's hit is gone;
decision 141), so these cases expect the edge at the saved place. A person may expect the chamfer
to follow the board instead: that reading is the design's accepted cost, recorded here so a change
either way shows. Found by PR 379's review round 1 (Opus R2, `xp_thin_member_swap.py`; Sonnet,
`r1s_xp.py`)."""

from PartDesignTests.Scenarios.harness import Chamfered, Scenario, X, edge
from PartDesignTests.Scenarios import models as m


class ThinBoardRedrawnAndShiftedByItsThickness(Scenario):
    """A board 3600 x 30, 235 high; a Chamfer (3) on its top front edge (y = 0). In one
    recompute the rectangle moves by -30 in y, its right, back and left lines keeping their IDs,
    and the front line is deleted and drawn again at y = -30. The top back edge now lies where the
    chamfered edge was."""

    area = "exact-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:3600")
    ISSUE = "ops#394"
    FOUND_BY = "review pr379-r1"
    TIER = "F"
    SIZE = 3600
    REFS = ("chamfer_front_top",)
    length, thickness, height, size = 3600, 30, 235, 3

    def atSavedPlace(self):
        L, H = self.s(self.length, self.height)
        return edge("line", direction=X, through=(0, 0, H), contains=(L / 2, 0, H))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, L, T), body)
        pad = m.pad(body, profile, H)
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.atSavedPlace()))
        chamfer.Size = self.s(self.size)
        self.ref("chamfer_front_top", chamfer, "Base", self.atSavedPlace, Chamfered(self.s(self.size)))

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        sketch = doc.Profile
        m.setLines(sketch, {1: ((L, -T), (L, 0)), 2: ((L, 0), (0, 0)), 3: ((0, 0), (0, -T))})
        sketch.delGeometry(0)
        sketch.addGeometry(m.polyline([(0, -T), (L, -T)]), False)


class RimRedrawn(Scenario):
    """Two rims 3600 x 45, 235 high, 4045 apart, padded from one sketch; a Chamfer (5) on the
    first rim's top edge at y = `chamfered`. The first rim's four lines are deleted and drawn again
    as `redraw` gives them."""

    abstract = True
    area = "exact-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#394"
    FOUND_BY = "review pr379-r1"
    TIER = "F"
    SIZE = 4090
    REFS = ("chamfer",)
    length, thickness, height, pitch = 3600, 45, 235, 4045
    chamfered = 0  # the chamfered edge's y, in thicknesses

    def atSavedPlace(self):
        y, H = self.s(self.chamfered * self.thickness, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def build(self, doc):
        L, T, H, P = self.s(self.length, self.thickness, self.height, self.pitch)
        body = m.body(doc)
        geometry = m.rectangle(0, 0, L, T) + m.rectangle(0, P, L, P + T)
        profile = m.sketch(doc, "Profile", geometry, body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.atSavedPlace()))
        chamfer.Size = self.s(5)
        self.ref("chamfer", chamfer, "Base", self.atSavedPlace, Chamfered(self.s(5)))

    def redraw(self):
        raise NotImplementedError

    def edit(self, doc):
        doc.Profile.delGeometries([0, 1, 2, 3])
        doc.Profile.addGeometry(m.polygon(self.redraw()), False)


class RimRedrawnInPlace(RimRedrawn):
    """The control: the rim drawn again where it was; its outer edge is at the saved place."""

    def redraw(self):
        L, T = self.s(self.length, self.thickness)
        return [(L, T), (L, 0), (0, 0), (0, T)]


class RimRedrawnOutwardByThickness(RimRedrawn):
    """The rim drawn again one thickness outward (y -45..0): the saved place (y = 0) holds the
    rim's inner top edge now."""

    def redraw(self):
        L, T = self.s(self.length, self.thickness)
        return [(L, 0), (L, -T), (0, -T), (0, 0)]


class RimBackEdgeRedrawnInward(RimRedrawn):
    """The Chamfer on the rim's inner top edge (y = 45); the rim drawn again one thickness inward
    (y 45..90): the saved place holds the rim's new outer top edge."""

    chamfered = 1

    def redraw(self):
        L, T = self.s(self.length, self.thickness)
        return [(L, 2 * T), (L, T), (0, T), (0, 2 * T)]
