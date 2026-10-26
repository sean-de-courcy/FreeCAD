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

"""Corpus cases (ops#500, class A): references to the edges and vertices of a Pipe's bends.

Two models, both a PartDesign AdditivePipe (a profile swept along a spine drawn in the XZ plane),
with a datum point on each element under test.

`PipeBendMirroredLeg`, `PipeBendProfileTurned80`: a 6 x 6 square with a round hole of radius 1,
swept along the L (0,0)-(0,30)-(20,30) with the "Right corner" transition. The hole's cylinders
of the two legs meet in the miter plane (through the corner, its normal the sum of the two legs'
directions) in ellipse arcs, four of them (the hole's quadrants), and a datum point sits on each.
A place on an arc is an angle about the spine: the point (cos t, sin t) of the hole in the
profile's plane, lifted along the leg onto the miter plane. The arcs are told apart by the places
at 45, 135, 225 and 315 degrees.
- Leg 2 is mirrored, (0,30)-(-20,30): the miter plane turns, the hole's edge there is the same
  circle of the profile lifted onto the new plane, and its pieces change: the second and third
  quadrants join into one half ellipse (four arcs become three). A datum point keeps its place
  in the profile, so each follows the arc that now holds the middle of its old arc (the first and
  fourth quadrants have arcs of their own; the second and third are both on the half ellipse).
  Ported from `work/469/r5v/orderprobe.py`, `MODE=edits`, `mirrorLeg2`
  (`corpus/predicted/A.json`: ops480 bend_arcs_4->3).
- The profile sketch is turned 80 degrees about the spine (its placement): the hole is the same
  cylinder, so the miter ellipse is the same curve and only its split points change (the circle's
  start point moves from 0 to 80 degrees; the quadrant ends 90, 180 and 270 stay). A datum point
  is on the same place of the hole's edge as before, so each follows the arc that now holds the
  middle of its old arc (the first quadrant is cut at 80 degrees and its larger part joins the
  fourth quadrant). The probe judged by "the nearest after rotating the expected place by 80
  degrees", rotating the centre of mass in 3D (off the miter plane); that place is not on the
  curve and was not kept, as the hole, a circle about the axis, does not turn with the sketch.
  Ported from the same probe, `protate80` (`corpus/predicted/A.json`: row329 protate80).

`ClosedSpineLineDrawnOtherWay`, `ClosedSpineReversedLineDrawnOtherWay`: a 2 x 2 square swept
along a closed spine of a line (0,0)-(0,10) and an arc through (-18.66025, 5) back to (0,0)
("Transformed", as "Right corner" does not make a valid solid of this spine), with the line
drawn the other way (in the second, built downwards and drawn upwards). The spine is the same
curve, but the direction around the loop is not, and the solid changes with it: the sweep carries
the profile through the arc's 300 degrees, so at the joint where the loop closes the two sections
differ by a turn of 60 degrees, and that joint moves from the bottom of the loop to its top. The
references are the elements whose places the edit does not change: a line edge of the straight
leg, the profile's plain section edge at each end of the line and the vertices at (1, 1) of those
sections. Each must stay at its place. Ported from `work/469/r5v/keyprobe.py` (`closedD`,
`closedDrev`; `corpus/predicted/A.json`: ops469 c1_closed_two_edge_spine_row322). The probe's
lens (two arcs) is not ported: its profile is not perpendicular to the spine, and the solid
itself changes when the arcs are swapped."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, edge, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # sketch (x, y) -> world (x, 0, y)
Y, Z = V(0, 1, 0), V(0, 0, 1)


class PipeBendArcs(Scenario):
    """The hole's bend arcs of a square-with-hole profile swept along an L; a subclass edits."""

    abstract = True
    area = "pipe-bend-arcs"
    CLASSES = ("A",)
    AXES = ("M3", "E1")
    ISSUE = "ops#500"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("arc_q1", "arc_q2", "arc_q3", "arc_q4")
    PLACES = {"arc_q1": 45, "arc_q2": 135, "arc_q3": 225, "arc_q4": 315}  # degrees, in the profile
    RADIUS = 1.0  # the hole
    CORNER = 30.0  # the corner of the spine is (0, 0, CORNER)
    leg = 1  # the second leg's direction along x: +1, or -1 once it is mirrored

    def place(self, ref):
        """The hole's point at the ref's angle, lifted onto the miter plane (through the corner,
        its normal the sum of the legs' directions, (leg, 0, 1)): leg * x + (z - corner) = 0."""
        t = math.radians(self.PLACES[ref])
        x, y = self.RADIUS * math.cos(t), self.RADIUS * math.sin(t)
        return (x, y, self.CORNER - self.leg * x)

    def arc(self, ref):
        """The bend edge that holds the ref's place."""
        return edge(contains=self.place(ref))

    def build(self, doc):
        body = m.body(doc)
        self.path = m.sketch(
            doc, "Path", m.polyline([(0, 0), (0, 30), (20, 30)]), body, placement=XZ
        )
        self.profile = m.sketch(
            doc, "Profile", m.rectangle(-3, -3, 3, 3) + [m.circle(0, 0, self.RADIUS)], body
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Right corner"
        doc.recompute()
        for ref in self.REFS:
            point = body.newObject("PartDesign::Point", "On" + ref)
            point.AttachmentSupport = [(pipe, self.names(pipe, self.arc(ref))[0])]
            point.MapMode = "CenterOfMass"
            self.ref(ref, point, "AttachmentSupport", lambda ref=ref: self.arc(ref), Attached())


class PipeBendMirroredLeg(PipeBendArcs):
    """Leg 2 mirrored to (0,30)-(-20,30): four arcs become three (class A, ops480)."""

    def edit(self, doc):
        m.setLines(self.path, {1: ((0, 30), (-20, 30))})
        self.leg = -1


class PipeBendProfileTurned80(PipeBendArcs):
    """The profile sketch turned 80 degrees about the spine's first leg (class A, row 329)."""

    def edit(self, doc):
        self.profile.Placement = App.Placement(V(), App.Rotation(Z, 80))


class ClosedSpine(Scenario):
    """A square swept along a closed line-and-arc spine; the line is drawn the other way."""

    abstract = True
    area = "pipe-closed-spine"
    CLASSES = ("A",)
    AXES = ("M3", "E1")
    ISSUE = "ops#500"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("line_edge", "bottom_edge", "top_edge", "bottom_vertex", "top_vertex")
    LENGTH = 10.0  # the line, from (0, 0) to (0, LENGTH)
    down = False  # the line is built from its top to its bottom

    def lineEdge(self):
        return edge(curve="line", direction=Z, through=(1, 1, self.LENGTH / 2))

    def bottomEdge(self):
        return edge(curve="line", direction=Y, contains=(1, 0, 0))

    def topEdge(self):
        return edge(curve="line", direction=Y, contains=(1, 0, self.LENGTH))

    def bottomVertex(self):
        return vertex(at=(1, 1, 0))

    def topVertex(self):
        return vertex(at=(1, 1, self.LENGTH))

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(-1, -1, 1, 1), body)
        top, bottom = (0, self.LENGTH), (0, 0)
        start, end = (top, bottom) if self.down else (bottom, top)
        self.path = m.sketch(
            doc,
            "Path",
            [
                Part.LineSegment(V(*start, 0), V(*end, 0)),
                Part.ArcOfCircle(V(0, self.LENGTH, 0), V(-18.66025, 5, 0), V(0, 0, 0)),
            ],
            body,
            placement=XZ,
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = False
        doc.recompute()
        for ref, expect, mode in (
            ("line_edge", self.lineEdge, "CenterOfMass"),
            ("bottom_edge", self.bottomEdge, "CenterOfMass"),
            ("top_edge", self.topEdge, "CenterOfMass"),
            ("bottom_vertex", self.bottomVertex, "Vertex"),
            ("top_vertex", self.topVertex, "Vertex"),
        ):
            point = body.newObject("PartDesign::Point", "On" + ref)
            point.AttachmentSupport = [(pipe, self.names(pipe, expect())[0])]
            point.MapMode = mode
            self.ref(ref, point, "AttachmentSupport", expect, Attached())

    def edit(self, doc):
        """The line drawn the other way, the same segment (its geometry id kept)."""
        geometry = self.path.Geometry
        line = geometry[0]
        start, end = V(line.StartPoint), V(line.EndPoint)
        line.EndPoint = V(7.5, -11.5, 0)  # off both ends, so the two points are never equal
        line.StartPoint = end
        line.EndPoint = start
        self.path.Geometry = geometry


class ClosedSpineLineDrawnOtherWay(ClosedSpine):
    """The line (0,0)-(0,10) drawn from (0,10) to (0,0) (class A, ops469 closedD)."""


class ClosedSpineReversedLineDrawnOtherWay(ClosedSpine):
    """The line built downwards, (0,10)-(0,0), drawn upwards (class A, ops469 closedDrev)."""

    down = True
