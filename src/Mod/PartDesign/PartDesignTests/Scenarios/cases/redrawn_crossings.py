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

"""Corpus cases (ops#394, class D): a hole's circle drawn again, then moved along the edge it
crosses.

A pad `length` x 10 x 5 and a through pocket of two circles (radius 2) of one sketch, centred 1
inside the front edge (y = 0): A at (10, 1), B at (22, 1). A's rim crosses the bottom and top front
edges at x = cx -+ 1.732; a datum point on each of A's four crossings. Circle A is deleted and
drawn again where it was (a new geometry ID: no name relates its crossings to the old ones), then
moved 4 mm along x, so that its left crossing lands 0.54 mm from the right one's saved place.
Each point is on its own crossing or breaks; never on the other crossing. Found by PR 379 round
4's attack set (`ACrossings|redrawn-then-move`, ops repo `corpus/attacks/models/a_crossings.py`).
There, on the round's first head, tier 3's nearest at the place broke too, and the move's guess
took the other crossing (`guessed-wrong`); gtest `redrawnCrossingMovedPastHalfItsSpacingBreaks`
pins the order test (the saved twin record) that breaks such a guess. Here, 40 mm long, tier 3
takes each crossing at the redraw (PLAN decision 165) and the name follows the move. 400 mm long,
tier 3's d_max (4) exceeds the crossings' spacing (3.46): the redraw breaks at the exact place
(decision 155), and the move's guess reaches both crossings, so the points stay broken."""

import math

from PartDesignTests.Scenarios.harness import BROKEN, Attached, OwnOrBroken, Scenario, vertex
from PartDesignTests.Scenarios import models as m

R = 2.0
CY = 1.0
HALF = math.sqrt(R * R - CY * CY)


class HoleRedrawnThenMovedAlongTheEdge(Scenario):
    """Circle A drawn again in place, then moved by `shift` along x."""

    area = "redrawn-crossings"
    CLASSES = ("D",)
    AXES = ("M1", "E1", "E5")
    ISSUE = "ops#394"
    FOUND_BY = "attack pr379-r4"
    TIER = "F"
    REFS = ("lo_z0", "hi_z0", "lo_z5", "hi_z5")
    steps = ("redraw", "move")
    shift = 4.0
    length = 40

    def crossing(self, side, z):
        x = self.cx + side * HALF
        return OwnOrBroken(vertex((x, 0, z))) if 0 < x < self.length else BROKEN

    def build(self, doc):
        body = m.body(doc)
        block = m.sketch(doc, "Block", m.rectangle(0, 0, self.length, 10), body)
        m.pad(body, block, 5, "BlockPad")
        holes = m.sketch(doc, "Holes", [m.circle(10, CY, R), m.circle(22, CY, R)], body, z=5)
        pocket = m.pocketThroughAll(body, holes)
        doc.recompute()
        self.cx = 10.0
        for name, side, z in (("lo_z0", -1, 0), ("hi_z0", 1, 0), ("lo_z5", -1, 5), ("hi_z5", 1, 5)):
            point = body.newObject("PartDesign::Point", "Point_" + name)
            point.AttachmentSupport = [(pocket, self.names(pocket, vertex((10 + side * HALF, 0, z)))[0])]
            point.MapMode = "Vertex"
            expect = lambda side=side, z=z: self.crossing(side, z)  # noqa: E731
            self.ref(name, point, "AttachmentSupport", expect, Attached())

    def redraw(self, doc):
        holes = doc.Holes
        circle = holes.Geometry[0].copy()
        holes.delGeometry(0)
        holes.addGeometry(circle, False)  # now geometry 1, a new ID

    def move(self, doc):
        doc.Holes.moveGeometry(1, 3, m.V(self.cx + self.shift, CY, 0), False)
        self.cx += self.shift


class HoleRedrawnThenMovedAlongALongEdge(HoleRedrawnThenMovedAlongTheEdge):
    """The same on a pad 400 long: the crossings lie within tier 3's d_max of each other."""

    length = 400
