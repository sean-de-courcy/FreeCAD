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

"""Corpus cases (ops#503, class D): the seam vertex of a hole across a pad's top edge.

A pad 20 x 10 x 10 and a refined pocket, through all and symmetric, of a circle of radius 0.5
centred on the top edge's height at x = 10, in an XZ sketch: the cylinder's seam is the circle's
start point, (10.5, 0, 10) on the front face. A datum point sits on that vertex. The pad gets
taller, and the circle moves along x. Ported from `work/394/probe_block.py` (`blockr`, `blockm`;
`corpus/predicted/D.json`: block)."""

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Scenario, vertex
from PartDesignTests.Scenarios import models as m

HEIGHT = 10
RADIUS = 0.5


class BlockSeamVertex(Scenario):
    """The model and its datum point on the seam vertex; a subclass raises the pad."""

    abstract = True
    area = "block-seam"
    CLASSES = ("D",)
    AXES = ("M1", "E1")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("seam_vertex",)
    steps = ("raise_", "back")
    cx = 10.0  # the circle's centre now
    raiseBy, moveBy = 1, 0

    def seam(self):
        return vertex(at=(self.cx + RADIUS, 0, HEIGHT))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        self.pad = m.pad(body, profile, HEIGHT)
        xz = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 90))
        self.hole = m.sketch(
            doc, "Hole", [m.circle(self.cx, HEIGHT, RADIUS)], body, placement=xz
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 1
        pocket.Midplane = True
        pocket.Refine = True
        doc.recompute()
        point = body.newObject("PartDesign::Point", "OnSeam")
        point.AttachmentSupport = [(pocket, self.names(pocket, self.seam())[0])]
        point.MapMode = "Vertex"
        self.ref("seam_vertex", point, "AttachmentSupport", self.seam, Attached())

    def moveCircle(self, x):
        geometry = self.hole.Geometry
        geometry[0].Center = App.Vector(x, HEIGHT, 0)
        self.hole.Geometry = geometry
        self.cx = x

    def raise_(self, doc):
        self.pad.Length = HEIGHT + self.raiseBy
        self.moveCircle(10.0 + self.moveBy)

    def back(self, doc):
        self.pad.Length = HEIGHT
        self.moveCircle(10.0)


class BlockSeamPadRaised(BlockSeamVertex):
    """The pad 10 -> 11: the hole is inside the pad now, a full circle in the front face, and the
    seam vertex stays at its place (the other crossing is gone)."""

    raiseBy, moveBy = 1, 0


class BlockSeamPadRaisedHoleMoved(BlockSeamVertex):
    """The pad 10 -> 13 and the circle 2 mm along x: the seam vertex is the new seam, 2 mm on."""

    raiseBy, moveBy = 3, 2
