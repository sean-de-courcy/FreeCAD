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

"""Corpus cases (ops#500, class A): a sketch's external geometry by its geoId (class E, ops#264 e2).

A 20 x 20 square is padded 10 high. A sketch on the XY plane projects the pad's whole top face
(one external-geometry link, four projected lines). A circle of radius 1, centre (0, 5), sits
PointOnObject on the projected edge at x = 0. The profile then gains a chamfer at (20, 20) with its
line IDs kept: lines 1 and 2 are shortened and a new line joins their ends, so the top face has
five edges, the order of the projected lines shifts, and the constraint's geoId (-6) is now the
chamfered back edge. The constraint must stay on the edge at x = 0 and the circle's centre at
x = 0; the circle sliding to the back edge (centre (0, 20)) is a silent move.
Ported from `work/504/proto_e1b.py` (variants `proto_e1.py`, `proto_e1c.py`;
`corpus/predicted/A.json`: ops264|e2_sketcher_external_ids)."""

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios.harness import Outcome, Scenario, Z, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


class ConstraintOnEdgeAtX0(Outcome):
    """The sketch's PointOnObject constraint: its second element is an external line lying on the
    plane x = 0 (end to end), and the circle's centre is on x = 0."""

    def compare(self, scenario, consumer, target, expectation):
        constraint = next(c for c in consumer.Constraints if c.Type == "PointOnObject")
        geoId = constraint.Second
        if geoId >= -2:
            return False, f"the constraint is on geometry {geoId}, not on an external line"
        line = consumer.ExternalGeo[-geoId - 1]
        if not isinstance(line, Part.LineSegment):
            return False, f"the constraint's edge {geoId} is {type(line).__name__}"
        placement = consumer.getGlobalPlacement()
        ends = [placement.multVec(p) for p in (line.StartPoint, line.EndPoint)]
        if any(abs(p.x) > 1e-6 for p in ends):
            return False, f"the constraint's edge {geoId} runs {ends[0]} to {ends[1]}, not on x = 0"
        centre = placement.multVec(consumer.Geometry[scenario.circle].Center)
        if abs(centre.x) > 1e-6:
            return False, f"the circle's centre is {centre}, not on x = 0"
        return True, ""


class SketchExternalIdsAfterChamfer(Scenario):
    """The profile's corner at (20, 20) is chamfered, the line IDs kept."""

    area = "external-ids"
    CLASSES = ("A",)
    AXES = ("M8", "E1")
    ISSUE = "ops#500"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("external_top",)

    def top(self):
        return face("plane", normal=Z, through=(0, 0, 10))

    def build(self, doc):
        body = m.body(doc)
        self.profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 20), body)
        pad = m.pad(body, self.profile, 10)
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "OnTop")
        sketch.AttachmentSupport = [(m.originFeature(body, "XY_Plane"), [""])]
        sketch.MapMode = "FlatFace"
        doc.recompute()
        sketch.addExternal(pad.Name, self.names(pad, self.top())[0])
        doc.recompute()
        # the projected line on x = 0 (the last two ExternalGeo entries before it are the axes)
        edges = [
            -(i + 1)
            for i, g in enumerate(sketch.ExternalGeo)
            if i >= 2
            and isinstance(g, Part.LineSegment)
            and abs(g.StartPoint.x) < 1e-6
            and abs(g.EndPoint.x) < 1e-6
        ]
        if len(edges) != 1:
            raise RuntimeError(f"{len(edges)} projected lines on x = 0")
        self.circle = sketch.addGeometry(Part.Circle(V(0, 5, 0), V(0, 0, 1), 1))
        sketch.addConstraint(Sketcher.Constraint("PointOnObject", self.circle, 3, edges[0]))
        sketch.addConstraint(Sketcher.Constraint("Radius", self.circle, 1.0))
        doc.recompute()
        self.ref("external_top", sketch, "ExternalGeometry", self.top, ConstraintOnEdgeAtX0())

    def edit(self, doc):
        # chamfer at (20, 20): line 1 ends at (20, 15), line 2 starts at (15, 20), a new line
        m.setLines(
            self.profile,
            {1: ((20, 0), (20, 15)), 2: ((15, 20), (0, 20))},
        )
        self.profile.addGeometry(Part.LineSegment(V(20, 15, 0), V(15, 20, 0)), False)
