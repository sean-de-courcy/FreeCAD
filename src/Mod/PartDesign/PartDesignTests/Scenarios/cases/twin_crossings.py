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

"""Corpus cases (ops#503, class D): the two crossings of a hole's cylinder with the front face.

A pad 20 x 10 x 5 with a through pocket of a circle of radius 1 at (cx, cy) crosses the front face
(y = 0) at two vertical lines and the top front edge at two vertices, x = cx -+ sqrt(1 - cy^2),
told apart by the Index field of their names (ops#468). The cylinder's seam is at the circle's
start point (cx + 1, cy). A datum point sits on each top crossing and a fillet on the right
vertical line. The circle moves; each reference follows the crossing on its side.
Ported from the class D design's probes (`work/503-r2/probe2.py`, `work/503/composed.py`;
`corpus/predicted/D.json`: CC1, CC2, seam, shift)."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import Attached, Filleted, Scenario, edge, vertex
from PartDesignTests.Scenarios import models as m

RADIUS = 1.0


class TwinCrossings(Scenario):
    """The model and its references; a subclass moves the circle."""

    abstract = True
    area = "twin-crossings"
    CLASSES = ("D",)
    AXES = ("M4", "E1")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("left_point", "right_point", "right_line")
    width, depth, top = 20, 10, 5  # the pad
    cx, cy = 10.0, 0.5  # the circle's centre; the crossings are at cx -+ sqrt(1 - cy^2)
    turn = 0  # the hole's sketch turned about the circle's centre, in degrees

    def span(self):
        return math.sqrt(1 - self.cy**2)

    def left(self):
        return vertex(at=(self.cx - self.span(), 0, self.top))

    def right(self):
        return vertex(at=(self.cx + self.span(), 0, self.top))

    def rightLine(self):
        # a straight vertical edge of the front face; at the seam it is the cylinder's seam
        # edge, a BSpline curve, so the test is by place and length and not by curve type
        x = self.cx + self.span()
        return edge(
            where=lambda e: (e.CenterOfMass - App.Vector(x, 0, self.top / 2)).Length < 1e-6
            and abs(e.Length - self.top) < 1e-6
        )

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, self.width, self.depth), body)
        m.pad(body, profile, self.top)
        self.home = (self.cx, self.cy)
        center = App.Vector(self.cx, self.cy, 0)
        rotation = App.Rotation(App.Vector(0, 0, 1), self.turn)
        placement = App.Placement(center - rotation.multVec(center), rotation)
        self.hole = m.sketch(
            doc, "Hole", [m.circle(self.cx, self.cy, RADIUS)], body, placement=placement
        )
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.hole
        pocket.Type = 1
        pocket.Midplane = True
        doc.recompute()
        for name, crossing in (("left_point", self.left), ("right_point", self.right)):
            point = body.newObject("PartDesign::Point", "On" + name)
            point.AttachmentSupport = [(pocket, self.names(pocket, crossing())[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", crossing, Attached())
        fillet = body.newObject("PartDesign::Fillet", "FilletRight")
        fillet.Base = (pocket, self.names(pocket, self.rightLine()))
        fillet.Radius = 0.3
        doc.recompute()
        self.ref("right_line", fillet, "Base", self.rightLine, Filleted(0.3))

    def moveCircle(self, x, y):
        """The circle's centre to the global (x, y), the geometry kept."""
        local = self.hole.Placement.inverse().multVec(App.Vector(x, y, 0))
        self.hole.moveGeometry(0, 3, local, False)
        self.cx, self.cy = x, y


class TwinCrossingAtSavedPlace(TwinCrossings):
    """The circle moves to (11.866, 0): the left crossing lands exactly where the right one was
    (x = 10.866) and the right one goes to 12.866, the seam vertex. Each reference must follow
    its side (class D, CC1)."""

    steps = ("move", "back")

    def move(self, doc):
        self.moveCircle(self.cx + self.span() + 1.0, 0.0)

    def back(self, doc):
        self.moveCircle(*self.home)


class TwinCrossingBecomesSeam(TwinCrossings):
    """The circle's y goes 0.5 -> 0: the crossings go to x = 9 and 11, and the right one becomes
    the cylinder's seam vertex (decision 132); then back."""

    steps = ("move", "back")

    def move(self, doc):
        self.moveCircle(self.home[0], 0.0)

    def back(self, doc):
        self.moveCircle(*self.home)


class TwinCrossingBecomesSeamTurned(TwinCrossings):
    """As TwinCrossingBecomesSeam with the hole's sketch turned 180 degrees: the seam is on the
    left, the left crossing becomes the seam vertex and the right one, alone, is renumbered from
    Index 1 to 0 (class D, CC2)."""

    turn = 180
    steps = ("move", "back")

    def move(self, doc):
        self.moveCircle(self.home[0], 0.0)

    def back(self, doc):
        self.moveCircle(*self.home)


class TwinCrossingsShifted(TwinCrossings):
    """The circle moves along x by 0.5, 1.0, the crossings' spacing (the left crossing lands
    where the right one was) and 3.0, each time and then back."""

    steps = (
        "shift_half",
        "back",
        "shift_one",
        "back",
        "shift_chord",
        "back",
        "shift_three",
        "back",
    )

    def shift(self, dx):
        self.moveCircle(self.home[0] + dx, self.home[1])

    def shift_half(self, doc):
        self.shift(0.5)

    def shift_one(self, doc):
        self.shift(1.0)

    def shift_chord(self, doc):
        self.shift(2.0 * math.sqrt(1 - 0.5**2))

    def shift_three(self, doc):
        self.shift(3.0)

    def back(self, doc):
        self.moveCircle(*self.home)


class TwinCrossingBecomesSeamAtScale(TwinCrossingBecomesSeam):
    """TwinCrossingBecomesSeam on a pad 2000 x 1000 x 500 (a diagonal of 2291 mm) with the same
    hole of radius 1 at (1000, 0.5): the solver's reach by distance grows with the model."""

    AXES = ("M4", "E1", "X4:2000")
    width, depth, top = 2000, 1000, 500
    cx = 1000.0
