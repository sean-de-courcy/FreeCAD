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

"""Corpus cases (ops#526, class D): a sibling of the old element's sketch at its vacated place.

The referenced element's sketch geometry is deleted, moved away or set to construction, and
another geometry of the same sketch, already in the model, is dragged so that one of its elements
lies exactly where the referenced one was. That element lost the old name's sources (T1''s test)
and sits at the saved place; nothing in the names tells it from the old geometry drawn again there
(ops#394's redraw), so the reference breaks (PLAN decision 155, fork PR 379 round 4) until D2
(ops#526) tells them apart. Found by PR 379's review round 3: Opus
(`work/pr379-r3/cases/r3_vacated_place.py`) and the cloud review's S1."""

import math

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    Chamfered,
    Filleted,
    Scenario,
    X,
    edge,
    vertex,
)
from PartDesignTests.Scenarios import models as m


class RimMovedIntoAVacatedPlace(Scenario):
    """Three rims 3600 x 45, 235 high, padded from one sketch, at y = 0, 2000 and 4045 (d_max
    ~54.5 while the rims are 45 thick); a Chamfer (5) on the first rim's outer top edge (y = 0).
    The first rim's four lines are deleted and the second rim's moved (IDs kept) to y = 0..45:
    its outer top edge lies at the saved place. Nothing of the first rim is left."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:4000")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r3"
    TIER = "F"
    SIZE = 4090
    REFS = ("chamfer",)
    length, thickness, height = 3600, 45, 235
    rims = (0, 2000, 4045)
    edited = False

    def topEdge(self, y):
        y, H = self.s(y, self.height)
        return edge("line", direction=X, through=(0, y, H))

    def build(self, doc):
        L, T, H = self.s(self.length, self.thickness, self.height)
        body = m.body(doc)
        geometry = []
        for y in self.rims:
            geometry += m.rectangle(0, self.s(y), L, self.s(y) + T)
        profile = m.sketch(doc, "Profile", geometry, body)
        pad = m.pad(body, profile, H, "Rims")
        doc.recompute()
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pad, self.names(pad, self.topEdge(0)))
        chamfer.Size = self.s(5)
        self.ref(
            "chamfer",
            chamfer,
            "Base",
            lambda: BROKEN if self.edited else self.topEdge(0),
            Chamfered(self.s(5)),
        )

    def edit(self, doc):
        L, T = self.s(self.length, self.thickness)
        m.moveRectangle(doc.Profile, 0, 0, L, T, first=4)
        doc.Profile.delGeometries([0, 1, 2, 3])
        self.edited = True


class HoleMovedIntoAVacatedPlace(Scenario):
    """A plate 200 x 100, 2 thick; one through Pocket of two circles (radius 4) of one sketch, A
    at (60, 50) and B at (140, 50); a Fillet (0.5) on A's top rim. Circle A is deleted and B
    dragged (ID kept) to A's place. The plate is thin, so B's bottom rim lies within d_max."""

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E4", "E5", "X4:600")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r3"
    TIER = "F"
    SIZE = 200
    SCALE = 3
    REFS = ("fillet",)
    thick = 2
    edited = False

    def rim(self, x):
        return edge("circle", center=self.s(x, 50, self.thick), radius=self.s(4))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, profile, self.s(self.thick))
        circles = [m.circle(*self.s(60, 50, 4)), m.circle(*self.s(140, 50, 4))]
        holes = m.sketch(doc, "Holes", circles, body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = holes
        pocket.Type = 1  # through all
        pocket.Midplane = True
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pocket, self.names(pocket, self.rim(60)))
        fillet.Radius = self.s(0.5)
        self.ref(
            "fillet",
            fillet,
            "Base",
            lambda: BROKEN if self.edited else self.rim(60),
            Filleted(self.s(0.5)),
        )

    def edit(self, doc):
        doc.Holes.moveGeometry(1, 3, m.V(*self.s(60, 50, 0)), False)
        doc.Holes.delGeometries([0])
        self.edited = True


RADIUS = 1.0
CY = 0.5
HALF = math.sqrt(RADIUS**2 - CY**2)


class SiblingCrossingAtThePlaceHoleOffThePlate(Scenario):
    """S1: a plate 200 x 100, 5 high, and one through Pocket of two circles (radius 1) of one
    sketch crossing its top front edge (y = 0, z = 5): A at (100, 0.5), B at (102.5, 0.5). A datum
    point on each of A's crossings. A moves off the plate (still in the sketch, cutting nothing)
    and B moves so that its left crossing lies at A's right crossing's place: both points break.
    """

    area = "vacated-place"
    CLASSES = ("D",)
    AXES = ("M1", "E1", "E5", "X4:600")
    ISSUE = "ops#526"
    FOUND_BY = "review pr379-r3-cloud"
    TIER = "F"
    SIZE = 200
    SCALE = 3
    REFS = ("right_crossing", "left_crossing")
    ax, bx = 100.0, 102.5
    edited = False

    def crossing(self, x):
        return vertex(at=self.s(x, 0, 5))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(0, 0, 200, 100)), body)
        m.pad(body, profile, self.s(5))
        circles = [m.circle(*self.s(x, CY, RADIUS)) for x in (self.ax, self.bx)]
        sketch = m.sketch(doc, "Holes", circles, body)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = sketch
        pocket.Type = 1  # through all
        pocket.Midplane = True
        doc.recompute()
        for name, side in (("right_crossing", 1), ("left_crossing", -1)):
            point = body.newObject("PartDesign::Point", "On" + name)
            at = self.crossing(self.ax + side * HALF)
            point.AttachmentSupport = [(pocket, self.names(pocket, at)[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", self.expect(at), Attached())

    def expect(self, at):
        return lambda: BROKEN if self.edited else at

    def leave(self, sketch):
        sketch.moveGeometry(0, 3, m.V(*self.s(self.ax, -50, 0)), False)

    def edit(self, doc):
        self.leave(doc.Holes)
        doc.Holes.moveGeometry(1, 3, m.V(*self.s(self.ax + 2 * HALF, CY, 0)), False)
        self.edited = True


class SiblingCrossingAtThePlaceHoleAsConstruction(SiblingCrossingAtThePlaceHoleOffThePlate):
    """S1's other form: circle A set to construction where it is, then B moved as above."""

    def leave(self, sketch):
        sketch.setConstruction(0, True)


class RimMovedIntoAVacatedPlaceThick(RimMovedIntoAVacatedPlace):
    """D2's debt (PLAN decision 165): rims 100 thick, beyond tier 3's d_max (~55), so tier 3's own
    nearest takes the moved rim's edge at the place, warned `normal`, on both builds."""

    thickness = 100
    rims = (0, 2000, 3990)


class HoleMovedIntoAVacatedPlaceThick(HoleMovedIntoAVacatedPlace):
    """D2's debt (PLAN decision 165): the plate 10 thick, so B's bottom rim lies beyond d_max and
    tier 3's own nearest takes B's top rim at the place, warned `normal`, on both builds."""

    thick = 10
