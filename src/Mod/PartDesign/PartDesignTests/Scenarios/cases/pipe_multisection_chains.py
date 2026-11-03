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

"""Corpus cases (review pr404-r4s, class B): multisection Pipes with sections at exact right angles
(ops#396, fork PR 404's `sectionTiltsAlong`), aimed at round 4's changes.

Every pipe is a polygonal spine from the origin, one corner after another turning towards a target
direction; the profile is an n-gon of circumradius 2 at the origin; sections are n-gons centred on
the spine, normal to their leg. `cap_solid` is a sketch on the far cap whose expectation also asks
that the pipe be the solid turned with the spine: its volume within 1e-3 of the same pipe's with
each corner 1e-4 rad under its angle (a scratch document); otherwise it expects the start cap, which
the reference does not hold, so a silent wrong solid scores `wrong` and a failed pipe `broken`."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, ScenarioError, face
from PartDesignTests.Scenarios import models as m

V = App.Vector


def frame(normal, turn):
    normal = V(normal).normalize()
    return App.Rotation(normal, turn).multiply(App.Rotation(V(0, 0, 1), normal))


def ngon(n, h, turn=0.0):
    return m.polygon(
        [
            (
                h * math.cos(math.radians(turn + 360.0 / n * k)),
                h * math.sin(math.radians(turn + 360.0 / n * k)),
            )
            for k in range(n)
        ]
    )


class Probe(Scenario):
    abstract = True
    area = "pipe_multisection_chains"
    CLASSES = ("B",)
    AXES = ("M3", "E4")
    ISSUE = "ops#396"
    FOUND_BY = "review pr404-r4s"
    TIER = "F"
    SIZE = 80
    SCALE = 7.5
    REFS = ("cap_solid",)
    FIRST = (0, 0, 1)
    TARGETS = ((1, 0, 0), (0, 1, 0), (0, 0, -1))
    LENGTHS = (30, 20, 20, 40)
    SECTIONS = ((1, 0.5, 6, 3.0, 0.0), (2, 0.5, 6, 3.0, 0.0), (3, 1.0, 6, 3.0, 30.0))
    SIDES = 6  # the profile's
    TRANSITION = "Transformed"
    START = 80.0
    EDITED = 90.0
    ROT = None  # (axis, degrees) applied to the whole model

    def rotation(self):
        if self.ROT is None:
            return App.Placement()
        return App.Placement(V(0, 0, 0), App.Rotation(V(*self.ROT[0]), self.ROT[1]))

    def directions(self, deg, under=0.0):
        a = math.radians(deg) - under
        ds = [V(*self.FIRST)]
        for e in self.TARGETS:
            d = ds[-1]
            e = (V(*e) - d * V(*e).dot(d)).normalize()
            ds.append(d * math.cos(a) + e * math.sin(a))
        return ds

    def points(self, deg, under=0.0):
        pts = [V(0, 0, 0)]
        for d, length in zip(self.directions(deg, under), self.LENGTHS):
            pts.append(pts[-1] + d * self.s(length))
        return pts

    def placements(self, deg, under=0.0):
        rp = self.rotation()
        ds, pts = self.directions(deg, under), self.points(deg, under)
        out = [rp.multiply(App.Placement(V(0, 0, 0), frame(ds[0], 0)))]
        for leg, fr, n, h, turn in self.SECTIONS:
            at = pts[leg] + (pts[leg + 1] - pts[leg]) * fr
            out.append(rp.multiply(App.Placement(at, frame(ds[leg], turn))))
        return [rp.multVec(p) for p in pts], out

    def makePipe(self, doc, body, deg, under=0.0):
        pts, places = self.placements(deg, under)
        path = doc.addObject("Part::Feature", "Path")
        path.Shape = Part.makePolygon(pts)
        profile = m.sketch(doc, "Profile", ngon(self.SIDES, self.s(2)), body, placement=places[0])
        sections = []
        for i, ((leg, fr, n, h, turn), place) in enumerate(zip(self.SECTIONS, places[1:])):
            sections.append(
                m.sketch(doc, f"Section{i}", ngon(n, self.s(h)), body, placement=place)
            )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transformation = "Multisection"
        pipe.Sections = sections
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        doc.recompute()
        return pipe

    def limitVolume(self, deg):
        scratch = App.newDocument("PipeR4sLimit")
        try:
            pipe = self.makePipe(scratch, m.body(scratch), deg, under=1e-4)
            if not pipe.isValid():
                raise ScenarioError(f"the limit pipe is invalid: {pipe.getStatusString()}")
            return pipe.Shape.Volume
        finally:
            App.closeDocument(scratch.Name)

    def tol(self):
        return 1e-6 * max(1.0, self.scale)

    def endTest(self, f):
        rp = self.rotation()
        n, h = self.SECTIONS[-1][2], self.s(self.SECTIONS[-1][3])
        centre = rp.multVec(self.points(self.deg)[-1])
        normal = rp.Rotation.multVec(self.directions(self.deg)[-1])
        area = 0.5 * n * h * h * math.sin(2 * math.pi / n)
        return (
            abs(abs(f.Surface.Axis.dot(normal)) - 1) < 1e-9
            and (f.CenterOfMass - centre).Length < self.tol()
            and abs(f.Area - area) < 1e-6 * area
        )

    def startTest(self, f):
        h = self.s(2)
        area = 0.5 * self.SIDES * h * h * math.sin(2 * math.pi / self.SIDES)
        first = self.rotation().Rotation.multVec(V(*self.FIRST))
        return (
            abs(abs(f.Surface.Axis.dot(first)) - 1) < 1e-9
            and f.CenterOfMass.Length < self.tol()
            and abs(f.Area - area) < 1e-6 * area
        )

    def capOfRightSolid(self):
        def expected(f):
            volume = self.doc.getObject("Pipe").Shape.Volume
            if abs(volume - self.limit) < 1e-3 * abs(self.limit):
                return self.endTest(f)
            return self.startTest(f)

        return face("plane", where=expected)

    def build(self, doc):
        self.deg = self.START
        self.doc = doc
        self.limit = self.limitVolume(self.deg)
        body = m.body(doc)
        pipe = self.makePipe(doc, body, self.deg)
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        cap = body.newObject("Sketcher::SketchObject", "On_cap")
        cap.AttachmentSupport = [(pipe, self.names(pipe, face("plane", where=self.endTest))[0])]
        cap.MapMode = "FlatFace"
        self.ref("cap_solid", cap, "AttachmentSupport", self.capOfRightSolid, Attached())

    def edit(self, doc):
        self.deg = self.EDITED
        self.limit = self.limitVolume(self.deg)
        pts, places = self.placements(self.deg)
        doc.Path.Shape = Part.makePolygon(pts)
        doc.Profile.Placement = places[0]
        for i, place in enumerate(places[1:]):
            doc.getObject(f"Section{i}").Placement = place
        doc.recompute()


class HelixRoundCornerTurned30(Probe):
    """The hexagon helix of right angles (+Z, +X, +Y, -Z; sections at the middle of the second and
    third legs and the end, the last turned 30 degrees) joined "Round corner": the round corner
    turns the sweep's frame at each corner, no tie is there, and integration builds the solid
    turned with the spine (the limit). Turned 1e-9 mm, the sections gave a wrong solid (round 4,
    stopping for "Transformed" only, not pushed), so PR 404 stops every chain of right angles at
    corners out of one plane whatever the transition (decision 228): right -> loud, under the PR's
    Decision 120 (4) line."""

    TRANSITION = "Round corner"


class HelixRoundCornerSquareTurn0(HelixRoundCornerTurned30):
    """The same with square sections, none turned: integration builds a wrong solid; the PR
    stops."""

    SIDES = 4
    SECTIONS = ((1, 0.5, 4, 3.0, 0.0), (2, 0.5, 4, 3.0, 0.0), (3, 1.0, 4, 3.0, 0.0))


class ZRotatedSquaresTurned30(Probe):
    """Control: a planar Z (+Z, +X, +Z) turned about the general axis (1, 2, 3) by 37.3 degrees,
    square sections (the last turned 30 degrees about its leg). Integration builds a solid a
    seventh of the right one's volume without a warning; PR 404 builds the right one."""

    TARGETS = ((1, 0, 0), (0, 0, 1))
    LENGTHS = (30, 20, 30)
    SIDES = 4
    SECTIONS = ((1, 0.5, 4, 2.6, 0.0), (2, 1.0, 4, 3.0, 30.0))
    ROT = ((1, 2, 3), 37.3)
