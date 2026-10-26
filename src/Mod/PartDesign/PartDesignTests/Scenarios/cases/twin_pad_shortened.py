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


"""Corpus cases (ops#503, class D): the pad shortened from the left past the left crossing.

The model of twin_crossings.py: a pad 20 x 10 x 5 with a through pocket of a circle of radius 1 at
(10, 0.5), which crosses the front face (y = 0) at two vertical lines and the top front edge at
two vertices, x = 10 -+ 0.866. A datum point sits on each top crossing and a fillet on the right
vertical line. The edit moves the pad's left side from x = 0 to x = 9.5, past the left crossing
(9.134) and short of the right one (10.866): the two crossings become one, a legitimate 2 -> 1
with an unmoved survivor. The right point and the right line's fillet keep the survivor (it did
not move: a correct reference holds it); the left point's vertex is gone, so it must break.
From the record alone this edit looks like twin_crossings' edge form (a shrunk twin group, the
survivor renumbered into the vanished twin's name): only the edit's own motion tells them apart.
Ported from the class D design's section 1.5 (`corpus/predicted/D.json`: pad_shortened)."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Filleted,
    Scenario,
    edge,
    vertex,
)
from PartDesignTests.Scenarios import models as m

RADIUS = 1.0


class PadShortenedPastLeftCrossing(Scenario):
    """TwinCrossings' model; the pad's left side goes to x = 9.5."""

    area = "twin-crossings"
    CLASSES = ("D",)
    AXES = ("M4", "E1")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("left_point", "right_point", "right_line")
    width, depth, top = 20, 10, 5  # the pad
    cx, cy = 10.0, 0.5  # the circle's centre; the crossings are at cx -+ sqrt(1 - cy^2)
    left = 0.0  # the pad's left side
    shortenedTo = 9.5

    def span(self):
        return math.sqrt(1 - self.cy**2)

    def leftCrossing(self):
        return vertex(at=(self.cx - self.span(), 0, self.top))

    def rightCrossing(self):
        return vertex(at=(self.cx + self.span(), 0, self.top))

    def rightLine(self):
        # the straight vertical edge of the front face at the right crossing
        x = self.cx + self.span()
        return edge(
            where=lambda e: (e.CenterOfMass - App.Vector(x, 0, self.top / 2)).Length < 1e-6
            and abs(e.Length - self.top) < 1e-6
        )

    def leftExpectation(self):
        # after the edit the left crossing is outside the pad: nothing of it is left
        return BROKEN if self.left > self.cx - self.span() else self.leftCrossing()

    def build(self, doc):
        body = m.body(doc)
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(self.left, 0, self.width, self.depth), body
        )
        m.pad(body, self.profile, self.top)
        hole = m.sketch(doc, "Hole", [m.circle(self.cx, self.cy, RADIUS)], body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 1
        pocket.Midplane = True
        doc.recompute()
        for name, crossing, expect in (
            ("left_point", self.leftCrossing, self.leftExpectation),
            ("right_point", self.rightCrossing, self.rightCrossing),
        ):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(pocket, self.names(pocket, crossing())[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", expect, Attached())
        fillet = body.newObject("PartDesign::Fillet", "FilletRight")
        fillet.Base = (pocket, self.names(pocket, self.rightLine()))
        fillet.Radius = 0.3
        doc.recompute()
        self.ref("right_line", fillet, "Base", self.rightLine, Filleted(0.3))

    def edit(self, doc):
        self.left = self.shortenedTo
        m.moveRectangle(self.profile, self.left, 0, self.width, self.depth)
