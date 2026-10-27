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

"""Corpus cases (ops#503, class D): a hole's crossing whose twin goes, beside another hole.

A plate 200 x 100, 5 high (at scale 1), with two through pockets of circles of radius 1 that cross
its top front edge (y = 0, z = 5): A at (100, 0.5) and B, from another sketch, at (102.5, 0.5).
Each crossing pair is told apart by the Index field of its names only (`CUT;0;V`, `CUT;1;V`). A
datum point sits on each of A's two crossings, x = 100 -+ 0.866. Circle A moves near the plate's
left end: its left crossing falls off the edge, and the right one, now alone, is renumbered.
The right point follows A's crossing; the left point's crossing is gone, so it breaks.
B's left crossing lies 0.77 from the right point's saved place, within tier 3's reach: after the
twin clause (fork PR 379, D1), geometry decided over the whole pool and took it, warned, until
the pick had to share the old name's source and maker (PR 379 round 2).
Found by PR 379's review round 1 (Opus, R1; `work/pr379-r1/cases/twin_lone_neighbour.py`).
With both circles in one sketch and one Pocket, B's crossings share that origin too: the pick
must keep the old name's sources as well (T1''s test; round 2's cloud review, F1)."""

import math

from PartDesignTests.Scenarios.harness import BROKEN, Attached, Scenario, vertex
from PartDesignTests.Scenarios import models as m

RADIUS = 1.0
CY = 0.5
HALF = math.sqrt(RADIUS**2 - CY**2)


class LoneTwinBesideAnotherHole(Scenario):
    """Hole A moved to (0.3, 0.5): its right crossing, alone, at x = 1.166."""

    area = "twin-neighbours"
    CLASSES = ("D",)
    AXES = ("M1", "E1", "X4:600")
    ISSUE = "ops#503"
    FOUND_BY = "review pr379-r1"
    TIER = "F"
    SIZE = 200
    SCALE = 3
    REFS = ("right_crossing", "left_crossing")
    withB = True
    ax0, ax1 = 100.0, 0.3  # hole A's centre before and after
    bx = 102.5

    def crossing(self, x):
        return vertex(at=self.s(x, 0, 5))

    def pocket(self, doc, body, name, x):
        sketch = m.sketch(doc, "Hole" + name, [m.circle(*self.s(x, CY, RADIUS))], body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket" + name)
        pocket.Profile = sketch
        pocket.Type = 1  # through all
        pocket.Midplane = True
        return pocket

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, profile, self.s(5))
        last = self.pocket(doc, body, "A", self.ax0)
        if self.withB:
            last = self.pocket(doc, body, "B", self.bx)
        doc.recompute()
        self.points(body, last)

    def points(self, body, last):
        self.ax = self.ax0
        for name, side in (("right_crossing", 1), ("left_crossing", -1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(last, self.names(last, self.crossing(self.ax0 + side * HALF))[0])]
            point.MapMode = "Vertex"
            if side > 0:
                expect = lambda: self.crossing(self.ax + HALF)
            else:
                expect = lambda: BROKEN if self.ax != self.ax0 else self.crossing(self.ax - HALF)
            self.ref(name, point, "AttachmentSupport", expect, Attached())

    def edit(self, doc):
        doc.HoleA.moveGeometry(0, 3, m.V(*self.s(self.ax1, CY, 0)), False)
        self.ax = self.ax1


class LoneTwinAlone(LoneTwinBesideAnotherHole):
    """The control: no hole B. Geometry finds nothing within reach; the right point breaks (the
    twin count 2 -> 1, decision 137 (2)'s cost) or follows its crossing."""

    withB = False


class LoneTwinBesideASiblingCircle(LoneTwinBesideAnotherHole):
    """F1 (PR 379 round 2's cloud review): both circles in one sketch, cut by one Pocket. B's
    left crossing, 0.77 from the right point's saved place, shares the old name's sketch and
    maker; it comes from another circle of the sketch, so it is no pick."""

    FOUND_BY = "review pr379-r2-cloud"
    bx1 = None  # hole B's centre after the edit (None: unmoved)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, profile, self.s(5))
        circles = [m.circle(*self.s(x, CY, RADIUS)) for x in (self.ax0, self.bx)]
        sketch = m.sketch(doc, "HoleA", circles, body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = sketch
        pocket.Type = 1  # through all
        pocket.Midplane = True
        doc.recompute()
        self.points(body, pocket)

    def edit(self, doc):
        super().edit(doc)
        if self.bx1 is not None:
            doc.HoleA.moveGeometry(1, 3, m.V(*self.s(self.bx1, CY, 0)), False)


class LoneTwinBesideASiblingCircleAtThePlace(LoneTwinBesideASiblingCircle):
    """F1's quiet form: the same edit moves B too, its left crossing exactly at the right point's
    saved place. Taken there, it was given the same-place level, with no warning."""

    bx1 = 100.0 + 2 * HALF
