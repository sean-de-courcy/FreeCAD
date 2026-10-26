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

"""Corpus cases (ops#503, class D): a hole across a pipe's joint when the first leg gets longer.

A refined "Transformed" pipe of a 4 x 4 square along a spine in the XZ plane (up 30, then 20 turned
40 degrees, then 20 turned 20 degrees more); a refined, symmetric, through pocket of a circle of
radius 0.5 at height 30 across the first joint, its axis along x. The hole meets the joint's
square at four vertices (x = -+2, y = -+0.5, z = 30). The first leg is dragged from 30 to 31 (the
spine's lines keep their geometry IDs): the hole is inside the first leg now and the joint is a
millimetre above it, so the four vertices are gone. The circle's seam is at y = +0.5: the new
seam vertices of the hole's circles in the faces x = -+2 sit at the places of two of the old
vertices, which the solver may hold only with a loud result. Ported from `work/394/probe_drag.py`
(`CASE=leg`; `corpus/predicted/D.json`: ops467)."""

import math

import FreeCAD as App

from PartDesignTests.Scenarios.harness import (
    BROKEN,
    Attached,
    OwnOrBroken,
    Scenario,
    vertex,
)
from PartDesignTests.Scenarios import models as m

XZ = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 90))
JOINT = 30


def spine(first, second, extra=0.0):
    """In an XZ sketch: up 30 + extra, then 20 turned `first` degrees from +Z towards +X, then 20
    turned `second` degrees more."""
    points = [(0.0, 0.0), (0.0, JOINT + extra)]
    heading = 0.0
    for turn in (first, second):
        heading += turn
        x, z = points[-1]
        a = math.radians(heading)
        points.append((x + 20 * math.sin(a), z + 20 * math.cos(a)))
    return points


class PipeHoleAcrossJoint(Scenario):
    """The pipe and a datum point on each vertex of the hole on the first joint."""

    abstract = True
    area = "pipe-hole"
    CLASSES = ("D",)
    AXES = ("M3", "E1")
    ISSUE = "ops#503"
    FOUND_BY = "port"
    TIER = "F"
    REFS = ("vertex_xm_ym", "vertex_xm_yp", "vertex_xp_ym", "vertex_xp_yp")
    extra = 0.0  # how much longer the first leg is now

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(-2, -2, 2, 2), body)
        self.path = m.sketch(doc, "Path", m.polyline(spine(40, 20)), body, placement=XZ)
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (self.path, [])
        pipe.Transition = "Transformed"
        pipe.Refine = True
        # the hole's sketch is turned so that its normal is +x
        placement = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 1, 1), 120))
        hole = m.sketch(doc, "Hole", [m.circle(0, JOINT, 0.5)], body, placement=placement)
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = hole
        pocket.Type = 1
        pocket.Midplane = True
        pocket.Refine = True
        doc.recompute()
        for name, (sx, sy) in zip(self.REFS, ((-1, -1), (-1, 1), (1, -1), (1, 1))):
            at = vertex(at=(2 * sx, 0.5 * sy, JOINT))
            point = body.newObject("PartDesign::Point", "On_" + name)
            point.AttachmentSupport = [(pocket, self.names(pocket, at)[0])]
            point.MapMode = "Vertex"
            self.ref(name, point, "AttachmentSupport", self.expectation(sy, at), Attached())

    def expectation(self, sy, at):
        """The vertex while the first leg is 30 long; once longer, the vertex is gone: a break (or,
        at y = +0.5, where a new seam vertex sits at its place, that vertex or a break)."""

        def expect():
            if not self.extra:
                return at
            return OwnOrBroken(at) if sy > 0 else BROKEN

        return expect


class PipeHoleFirstLegLonger(PipeHoleAcrossJoint):
    """The first leg 30 -> 31 (the joint moves up with the rest of the spine), then back."""

    steps = ("longer", "back")

    def drag(self, extra):
        self.extra = extra
        points = spine(40, 20, extra)
        m.setLines(self.path, {i: (p, q) for i, (p, q) in enumerate(zip(points, points[1:]))})

    def longer(self, doc):
        self.drag(1.0)

    def back(self, doc):
        self.drag(0.0)
