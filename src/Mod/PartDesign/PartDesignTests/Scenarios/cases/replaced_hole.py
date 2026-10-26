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


"""Corpus cases (ops#503, class D): a pocketed hole replaced by an identical one from another sketch.

A pad 20 x 10 x 5 with a through pocket of a circle of radius 2 at (10, 5), drawn in the sketch
`Hole`. The edit switches the Pocket's Profile to a second sketch `HoleAgain` holding the same
circle at the same place; the first sketch is kept. The new hole is made by another source (another
sketch's edges), but its rim and its seam vertex are exactly where the old ones were. References: a
datum point on the rim's seam vertex and a fillet on the top rim. The right element is the one at the
same place, which a reference solver may hold only with a warning (the quiet `same-place` level is
for a pick that shares the old element's source; XP's source condition, I-S6), so the expectation is
a warned pick of it and not a plain stand.
Ported from the class D design's section 1.5 and 5.1 item 5 (`corpus/predicted/D.json`: XP)."""

from PartDesignTests.Scenarios.harness import (
    Attached,
    Filleted,
    Guessed,
    Scenario,
    edge,
    vertex,
)
from PartDesignTests.Scenarios import models as m


class ReplacedHoleSamePlace(Scenario):
    """The pocket's Profile switched to an identical circle in another sketch."""

    area = "replaced-hole"
    CLASSES = ("D",)
    AXES = ("M1", "E3")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("seam_vertex", "rim_fillet")
    width, depth, top = 20, 10, 5
    cx, cy, radius = 10.0, 5.0, 2.0

    def seam(self):
        # the circle's start point, (cx + r, cy), on the pad's top face
        return vertex(at=(self.cx + self.radius, self.cy, self.top))

    def rim(self):
        return edge("circle", center=(self.cx, self.cy, self.top), radius=self.radius)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.width, self.depth), body)
        m.pad(body, profile, self.top)
        hole = m.sketch(doc, "Hole", [m.circle(self.cx, self.cy, self.radius)], body)
        self.again = m.sketch(doc, "HoleAgain", [m.circle(self.cx, self.cy, self.radius)], body)
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = hole
        self.pocket.Type = 1
        self.pocket.Midplane = True
        doc.recompute()
        point = body.newObject("PartDesign::Point", "OnSeam")
        point.AttachmentSupport = [(self.pocket, self.names(self.pocket, self.seam())[0])]
        point.MapMode = "Vertex"
        self.ref("seam_vertex", point, "AttachmentSupport", self.guessedSeam, Attached())
        fillet = body.newObject("PartDesign::Fillet", "FilletRim")
        fillet.Base = (self.pocket, self.names(self.pocket, self.rim()))
        fillet.Radius = 0.3
        doc.recompute()
        self.ref("rim_fillet", fillet, "Base", self.guessedRim, Filleted(0.3))

    def guessedSeam(self):
        return Guessed(self.seam())

    def guessedRim(self):
        return Guessed(self.rim())

    def edit(self, doc):
        self.pocket.Profile = self.again
