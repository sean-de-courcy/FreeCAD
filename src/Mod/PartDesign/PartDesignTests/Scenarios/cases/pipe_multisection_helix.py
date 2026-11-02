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

"""Corpus cases (review pr404-r3, class B): a multisection Pipe ("Transformed") of hexagons along
a spine whose right angles don't lie in one plane (ops#396, fork PR 404's `sectionTiltsAlong`;
found by its round 3 review).

The spine is a Part feature's polygon of four legs, 30, 20, 20 and 40 long, from +Z at the
origin, each corner turning `deg` degrees towards +X, +Y and -Z in turn (80 when built). The edit
turns all three corners to 90 degrees: a helix of right angles, +Z, +X, +Y, -Z. The profile is a
hexagon of circumradius 2 in the XY plane at the origin (a vertex on the sketch's +X), and there
is a section at the middle of the second and third legs and one at the spine's end, each normal to
its leg, the last one's sketch turned `TURN` degrees about its leg.

OCCT's pairing of the sections changes by itself between 1e-7 and 1e-8 rad under each corner, on
integration as with PR 404 (the review's probe with a last leg 30 long: 1677.62 at 1e-7 rad, 1521.09
at 1e-8). Integration fails at exactly 90 degrees ("isn't a valid solid"); PR 404's round 3 turned
the sections 1e-9 mm, inside the other pairing's band, and built 1521.09, 9 % short, silently.
Decision 228: sections at right angles along a spine not in one plane stop the pipe, the same on
every system.

References: a sketch on the far cap and datum points on its vertices, each expected at the last
section's own corner where its sketch puts it; and `cap_solid`, a sketch on the far cap whose
expectation also asks that the pipe be the solid turned with the spine: its volume within 1e-3 of
the same pipe's with each corner 1e-4 rad under the edited angle (built in a scratch document);
otherwise it expects the start cap, which the reference doesn't hold, so a silent wrong solid
scores `wrong`. A pipe that fails breaks them all."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, ScenarioError, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


def frame(normal, turn):
    """The rotation taking the sketch's Z to `normal`, the sketch then turned `turn` degrees
    about it"""
    normal = V(normal).normalize()
    return App.Rotation(normal, turn).multiply(App.Rotation(V(0, 0, 1), normal))


def hexagon(h, turn=0.0):
    """The hexagon of circumradius `h`, a vertex `turn` degrees from +X"""
    return m.polygon(
        [
            (h * math.cos(math.radians(turn + 60 * k)), h * math.sin(math.radians(turn + 60 * k)))
            for k in range(6)
        ]
    )


class HexagonHelix(Scenario):
    """The helix with the last section's sketch turned 30 degrees (see the module's docstring)."""

    area = "pipe_multisection_helix"
    CLASSES = ("B",)
    AXES = ("M3", "E4")
    ISSUE = "ops#396"
    FOUND_BY = "review pr404-r3"
    TIER = "F"
    SIZE = 80
    SCALE = 7.5
    REFS = ("cap", "cap_solid") + tuple(f"cap_v{i}" for i in range(6))
    START = 80.0  # each corner's angle when built
    TURN = 30.0  # the last section's sketch turned about its leg
    SIZES = (3.0, 3.0, 3.0)  # the sections' circumradii

    def directions(self, deg, under=0.0):
        """The legs' directions, each corner turning `deg` degrees less `under` radians (exact
        vectors at 90)"""
        if deg == 90 and under == 0:
            return [V(0, 0, 1), V(1, 0, 0), V(0, 1, 0), V(0, 0, -1)]
        a = math.radians(deg) - under
        ds = [V(0, 0, 1)]
        for e in (V(1, 0, 0), V(0, 1, 0), V(0, 0, -1)):
            d = ds[-1]
            e = (e - d * e.dot(d)).normalize()  # the turn's way: e made perpendicular to the leg
            ds.append(d * math.cos(a) + e * math.sin(a))
        return ds

    def points(self, deg, under=0.0):
        pts = [V(0, 0, 0)]
        for d, length in zip(self.directions(deg, under), (30, 20, 20, 40)):
            pts.append(pts[-1] + d * self.s(length))
        return pts

    def endPlacement(self, deg, under=0.0):
        direction = self.directions(deg, under)[-1]
        return App.Placement(self.points(deg, under)[-1], frame(direction, self.TURN))

    def sectionPlacements(self, deg, under=0.0):
        pts, ds = self.points(deg, under), self.directions(deg, under)
        return [
            App.Placement(pts[1] + ds[1] * self.s(10), frame(ds[1], 0)),
            App.Placement(pts[2] + ds[2] * self.s(10), frame(ds[2], 0)),
            self.endPlacement(deg, under),
        ]

    def makePipe(self, doc, body, deg, under=0.0):
        path = doc.addObject("Part::Feature", "Path")
        path.Shape = Part.makePolygon(self.points(deg, under))
        profile = m.sketch(doc, "Profile", hexagon(self.s(2)), body)
        sections = [
            m.sketch(doc, f"Section{i}", hexagon(self.s(h)), body, placement=placement)
            for i, (placement, h) in enumerate(zip(self.sectionPlacements(deg, under), self.SIZES))
        ]
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transformation = "Multisection"
        pipe.Sections = sections
        pipe.Transition = "Transformed"
        pipe.Refine = False
        doc.recompute()
        return pipe

    def limitVolume(self, deg):
        """The volume of the same pipe with each corner 1e-4 rad under `deg`, where OCCT's
        pairing has no tie"""
        scratch = App.newDocument("PipeMultisectionHelixLimit")
        try:
            pipe = self.makePipe(scratch, m.body(scratch), deg, under=1e-4)
            if not pipe.isValid():
                raise ScenarioError(f"the limit pipe is invalid: {pipe.getStatusString()}")
            return pipe.Shape.Volume
        finally:
            App.closeDocument(scratch.Name)

    def build(self, doc):
        self.deg = self.START
        self.doc = doc
        self.limit = self.limitVolume(self.deg)
        body = m.body(doc)
        pipe = self.makePipe(doc, body, self.deg)
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        for key, target in (("cap", self.capFace), ("cap_solid", self.capFaceOfRightSolid)):
            cap = body.newObject("Sketcher::SketchObject", "On_" + key)
            cap.AttachmentSupport = [(pipe, self.names(pipe, self.capFace())[0])]
            cap.MapMode = "FlatFace"
            self.ref(key, cap, "AttachmentSupport", target, Attached())
        for i in range(6):
            key = f"cap_v{i}"
            point = body.newObject("PartDesign::Point", "On_" + key)
            point.AttachmentSupport = [(pipe, self.names(pipe, self.capVertex(i))[0])]
            point.MapMode = "Vertex"
            self.ref(key, point, "AttachmentSupport", lambda i=i: self.capVertex(i), Attached())

    # The far end's elements where the last section's sketch puts them (at the current angle)

    def tol(self):
        return 1e-6 * max(1.0, self.scale)

    def local(self, u, v):
        return self.endPlacement(self.deg).multVec(V(u, v, 0))

    def capTest(self, f):
        h = self.s(self.SIZES[-1])
        centre, normal = self.local(0, 0), self.directions(self.deg)[-1]
        area = 1.5 * math.sqrt(3) * h * h
        return (
            abs(abs(f.Surface.Axis.dot(normal)) - 1) < 1e-9
            and (f.CenterOfMass - centre).Length < self.tol()
            and abs(f.Area - area) < 1e-6 * area
        )

    def capFace(self):
        return face("plane", where=self.capTest)

    def startCapTest(self, f):
        h = self.s(2)
        area = 1.5 * math.sqrt(3) * h * h
        return (
            abs(abs(f.Surface.Axis.z) - 1) < 1e-9
            and f.CenterOfMass.Length < self.tol()
            and abs(f.Area - area) < 1e-6 * area
        )

    def capFaceOfRightSolid(self):
        """The far cap where the pipe is the solid turned with the spine; otherwise the start cap,
        an element the reference doesn't hold, so that a silent wrong solid scores `wrong` (and a
        failed pipe `broken`)"""

        def expected(f):
            volume = self.doc.getObject("Pipe").Shape.Volume
            if abs(volume - self.limit) < 1e-3 * abs(self.limit):
                return self.capTest(f)
            return self.startCapTest(f)

        return face("plane", where=expected)

    def capVertex(self, i):
        h = self.s(self.SIZES[-1])
        a = math.radians(60 * i)
        return vertex(self.local(h * math.cos(a), h * math.sin(a)))

    def edit(self, doc):
        self.deg = 90.0
        self.limit = self.limitVolume(self.deg)
        doc.Path.Shape = Part.makePolygon(self.points(self.deg))
        for i, placement in enumerate(self.sectionPlacements(self.deg)):
            doc.getObject(f"Section{i}").Placement = placement
        doc.recompute()


class HexagonHelixSquareTurnedToRightAngles(HexagonHelix):
    """The last section's sketch turned 0 degrees: round 3 built the solid turned with the spine
    at 90 degrees; integration fails at 600 mm and 4 m and builds a wrong solid at 60 mm. It stops
    now, like every chain of right angles out of one plane."""

    TURN = 0.0


class HexagonHelixSectionTurned90ToRightAngles(HexagonHelix):
    """The last section's sketch turned 90 degrees: round 3 built the same wrong solid as at 30,
    integration fails."""

    TURN = 90.0


class HexagonHelixGrowingToRightAngles(HexagonHelix):
    """Turned 30 degrees with sections growing 2.5, 3, 3.5 (the probe at the 30-long last leg:
    the limit 1614.40, round 3 1461.77; integration fails at 60 mm and 4 m and builds round 3's
    wrong solid at 600 mm)."""

    SIZES = (2.5, 3.0, 3.5)
