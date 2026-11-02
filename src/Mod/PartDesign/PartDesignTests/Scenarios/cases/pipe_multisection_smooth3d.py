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

"""Corpus cases (review pr404-r4, class B): a multisection Pipe along a smooth spine that isn't in
one plane, with consecutive sections at right angles (ops#396, fork PR 404's `sectionTiltsAlong`,
round 4's stop for turns about other axes, decision 228).

The spine is a Part feature's wire of three tangent-continuous edges and no corner: a quarter arc
of radius 20 in the XY plane from the origin, heading +X, to (20, 20, 0) heading +Y; a line of 20
along +Y; a quarter arc of radius 20 in the plane x = 20, from (20, 40, 0) heading +Y to
(20, 60, 20) heading +Z. The profile is a square of half-width 2 at the origin, normal to the spine
(+X); there is a section of half-width 3 at the middle of the line and one at the spine's end, each
normal to the spine there (+Y, +Z). Built with the middle section's sketch turned `START` degrees
about Z off the spine's normal plane; the edit turns it back, normal to the spine: the three
sections are then pairwise at right angles, the turns from one to the next about Z and then X.

The spine has no corner, so no corner of 90 degrees and no tie: integration builds the solid, the
same within 1e-8 relative as the pipe with the middle section 1e-4 rad off. The first build of
round 4 stopped it with "Sections at right angles along a spine that isn't in one plane aren't
supported"; the stop is for right angles at corners now (review pr404-r4 L1).

References: a sketch on the far cap and datum points on its vertices, each expected at the last
section's place; and `cap_solid`, as in `pipe_multisection_helix`: the far cap only if the pipe's
volume is within 1e-4 of the same pipe's with the middle section 1e-4 rad off normal (built in a
scratch document), else the start cap, which the reference doesn't hold."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, ScenarioError, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector


def frame(normal, turn=0.0):
    normal = V(normal).normalize()
    return App.Rotation(normal, turn).multiply(App.Rotation(V(0, 0, 1), normal))


def square(h):
    return m.polygon([(h, h), (-h, h), (-h, -h), (h, -h)])


def hexagon(h):
    return m.polygon(
        [(h * math.cos(math.radians(60 * k)), h * math.sin(math.radians(60 * k))) for k in range(6)]
    )


class SmoothSpineSquaresToRightAngles(Scenario):
    """Squares, Standard mode (see the module's docstring)."""

    area = "pipe_multisection_smooth3d"
    CLASSES = ("B",)
    AXES = ("M3", "E4")
    ISSUE = "ops#396"
    FOUND_BY = "review pr404-r4"
    TIER = "F"
    SIZE = 60
    SCALE = 10.0
    REFS = ("cap", "cap_solid") + tuple(f"cap_v{i}" for i in range(4))
    START = 5.0  # degrees the middle section's sketch is off the spine's normal plane, built
    MODE = "Standard"
    SHAPE = staticmethod(square)
    NV = 4
    SIZES = (2.0, 3.0, 3.0)

    def spine(self):
        R, L = self.s(20), self.s(20)
        s2 = math.sqrt(0.5)
        a1 = Part.Arc(V(0, 0, 0), V(R * s2, R - R * s2, 0), V(R, R, 0)).toShape()
        l2 = Part.LineSegment(V(R, R, 0), V(R, R + L, 0)).toShape()
        a3 = Part.Arc(
            V(R, R + L, 0), V(R, R + L + R * s2, R - R * s2), V(R, 2 * R + L, R)
        ).toShape()
        return Part.Wire([a1, l2, a3])

    def end(self):
        return V(self.s(20), self.s(60), self.s(20))

    def middlePlacement(self, rad):
        normal = V(0, 1, 0)
        if rad:
            normal = App.Rotation(V(0, 0, 1), math.degrees(rad)).multVec(normal)
        return App.Placement(V(self.s(20), self.s(30), 0), frame(normal))

    def endPlacement(self):
        return App.Placement(self.end(), frame(V(0, 0, 1)))

    def makePipe(self, doc, body, rad):
        path = doc.addObject("Part::Feature", "Path")
        path.Shape = self.spine()
        profile = m.sketch(
            doc, "Profile", self.SHAPE(self.s(self.SIZES[0])), body,
            placement=App.Placement(V(0, 0, 0), frame(V(1, 0, 0))),
        )
        middle = m.sketch(
            doc,
            "Section0",
            self.SHAPE(self.s(self.SIZES[1])),
            body,
            placement=self.middlePlacement(rad),
        )
        last = m.sketch(
            doc, "Section1", self.SHAPE(self.s(self.SIZES[2])), body, placement=self.endPlacement()
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transformation = "Multisection"
        pipe.Sections = [middle, last]
        pipe.Transition = "Transformed"
        pipe.Mode = self.MODE
        pipe.Refine = False
        doc.recompute()
        return pipe

    def limitVolume(self):
        scratch = App.newDocument("PipeSmooth3dLimit")
        try:
            pipe = self.makePipe(scratch, m.body(scratch), 1e-4)
            if not pipe.isValid():
                raise ScenarioError(f"the limit pipe is invalid: {pipe.getStatusString()}")
            return pipe.Shape.Volume
        finally:
            App.closeDocument(scratch.Name)

    def build(self, doc):
        self.doc = doc
        self.limit = None
        body = m.body(doc)
        pipe = self.makePipe(doc, body, math.radians(self.START))
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        for key, target in (("cap", self.capFace), ("cap_solid", self.capFaceOfRightSolid)):
            cap = body.newObject("Sketcher::SketchObject", "On_" + key)
            cap.AttachmentSupport = [(pipe, self.names(pipe, self.capFace())[0])]
            cap.MapMode = "FlatFace"
            self.ref(key, cap, "AttachmentSupport", target, Attached())
        for i in range(self.NV):
            key = f"cap_v{i}"
            point = body.newObject("PartDesign::Point", "On_" + key)
            point.AttachmentSupport = [(pipe, self.names(pipe, self.capVertex(i))[0])]
            point.MapMode = "Vertex"
            self.ref(key, point, "AttachmentSupport", lambda i=i: self.capVertex(i), Attached())

    def tol(self):
        return 1e-6 * max(1.0, self.scale)

    def capArea(self):
        h = self.s(self.SIZES[2])
        return 4 * h * h if self.NV == 4 else 1.5 * math.sqrt(3) * h * h

    def capTest(self, f):
        return (
            abs(abs(f.Surface.Axis.z) - 1) < 1e-9
            and (f.CenterOfMass - self.end()).Length < self.tol()
            and abs(f.Area - self.capArea()) < 1e-6 * self.capArea()
        )

    def capFace(self):
        return face("plane", where=self.capTest)

    def startCapTest(self, f):
        h = self.s(self.SIZES[0])
        area = 4 * h * h if self.NV == 4 else 1.5 * math.sqrt(3) * h * h
        return (
            abs(abs(f.Surface.Axis.x) - 1) < 1e-9
            and f.CenterOfMass.Length < self.tol()
            and abs(f.Area - area) < 1e-6 * area
        )

    def capFaceOfRightSolid(self):
        def expected(f):
            volume = self.doc.getObject("Pipe").Shape.Volume
            limit = self.limit if self.limit is not None else volume
            if abs(volume - limit) < 1e-4 * abs(limit):
                return self.capTest(f)
            return self.startCapTest(f)

        return face("plane", where=expected)

    def capVertex(self, i):
        h = self.s(self.SIZES[2])
        if self.NV == 4:
            u, v = ((h, h), (-h, h), (-h, -h), (h, -h))[i]
        else:
            a = math.radians(60 * i)
            u, v = h * math.cos(a), h * math.sin(a)
        return vertex(self.endPlacement().multVec(V(u, v, 0)))

    def edit(self, doc):
        self.limit = self.limitVolume()
        doc.getObject("Section0").Placement = self.middlePlacement(0.0)
        doc.recompute()


class SmoothSpineHexagonsToRightAngles(SmoothSpineSquaresToRightAngles):
    """Hexagons (a vertex on each sketch's +X), Standard mode."""

    SHAPE = staticmethod(hexagon)
    NV = 6
    REFS = ("cap", "cap_solid") + tuple(f"cap_v{i}" for i in range(6))


class SmoothSpineSquaresFrenetToRightAngles(SmoothSpineSquaresToRightAngles):
    """Squares, Frenet mode."""

    MODE = "Frenet"


class CornerChainHexagonsRoundCornerToRightAngles(SmoothSpineSquaresToRightAngles):
    """Not smooth: a Part feature's polygon of legs 30, 20, 20 from +Z at the origin, its corners
    turning `deg` degrees towards +X and then +Y (80 when built, 90 after the edit: +Z, +X, +Y),
    joined "Round corner". Hexagons of circumradius 2, 3 and 3: the profile at the origin, a
    section at the middle of the second leg and one at the end, each normal to its leg. With
    "Round corner" the sweep's frame turns at the corners, and integration builds the solid of
    the limit 1e-4 rad under 90 (within 1e-6 relative, at 60 mm and 600 mm). The PR stops it, as
    decision 228 rules for right angles at corners out of one plane, whatever joins them: with
    "Round corner" the 1e-9 mm turn alone gave a wrong solid for the review's hexagon helix
    (review pr404-r4s). Right -> loud, under the PR's Decision 120 (4) line."""

    SIZE = 40
    SCALE = 15.0
    SHAPE = staticmethod(hexagon)
    NV = 6
    REFS = ("cap", "cap_solid") + tuple(f"cap_v{i}" for i in range(6))
    TRANSITION = "Round corner"

    def directions(self, deg, under=0.0):
        if deg == 90 and under == 0:
            return [V(0, 0, 1), V(1, 0, 0), V(0, 1, 0)]
        a = math.radians(deg) - under
        ds = [V(0, 0, 1)]
        for e in (V(1, 0, 0), V(0, 1, 0)):
            d = ds[-1]
            e = (e - d * e.dot(d)).normalize()
            ds.append(d * math.cos(a) + e * math.sin(a))
        return ds

    def points(self, deg, under=0.0):
        pts = [V(0, 0, 0)]
        for d, length in zip(self.directions(deg, under), (30, 20, 20)):
            pts.append(pts[-1] + d * self.s(length))
        return pts

    def end(self):
        return self.points(self.deg)[-1]

    def endPlacement(self):
        return App.Placement(self.end(), frame(self.directions(self.deg)[-1]))

    def makeCornered(self, doc, body, deg, under=0.0):
        pts, ds = self.points(deg, under), self.directions(deg, under)
        path = doc.addObject("Part::Feature", "Path")
        path.Shape = Part.makePolygon(pts)
        profile = m.sketch(doc, "Profile", self.SHAPE(self.s(self.SIZES[0])), body)
        middle = m.sketch(
            doc, "Section0", self.SHAPE(self.s(self.SIZES[1])), body,
            placement=App.Placement(pts[1] + ds[1] * self.s(10), frame(ds[1])),
        )
        last = m.sketch(
            doc, "Section1", self.SHAPE(self.s(self.SIZES[2])), body,
            placement=App.Placement(pts[3], frame(ds[2])),
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transformation = "Multisection"
        pipe.Sections = [middle, last]
        pipe.Transition = self.TRANSITION
        pipe.Refine = False
        doc.recompute()
        return pipe

    def makePipe(self, doc, body, rad):
        return self.makeCornered(doc, body, self.deg)

    def limitVolume(self):
        scratch = App.newDocument("PipeCornerChainLimit")
        try:
            pipe = self.makeCornered(scratch, m.body(scratch), 90.0, under=1e-4)
            if not pipe.isValid():
                raise ScenarioError(f"the limit pipe is invalid: {pipe.getStatusString()}")
            return pipe.Shape.Volume
        finally:
            App.closeDocument(scratch.Name)

    def startCapTest(self, f):
        h = self.s(self.SIZES[0])
        area = 1.5 * math.sqrt(3) * h * h
        return (
            abs(abs(f.Surface.Axis.z) - 1) < 1e-9
            and f.CenterOfMass.Length < self.tol()
            and abs(f.Area - area) < 1e-6 * area
        )

    def capTest(self, f):
        normal = self.directions(self.deg)[-1]
        return (
            abs(abs(f.Surface.Axis.dot(normal)) - 1) < 1e-9
            and (f.CenterOfMass - self.end()).Length < self.tol()
            and abs(f.Area - self.capArea()) < 1e-6 * self.capArea()
        )

    def build(self, doc):
        self.deg = 80.0
        super().build(doc)

    def edit(self, doc):
        self.limit = self.limitVolume()
        self.deg = 90.0
        doc.Path.Shape = Part.makePolygon(self.points(90.0))
        pts, ds = self.points(90.0), self.directions(90.0)
        middle = App.Placement(pts[1] + ds[1] * self.s(10), frame(ds[1]))
        doc.getObject("Section0").Placement = middle
        doc.getObject("Section1").Placement = App.Placement(pts[3], frame(ds[2]))
        doc.recompute()
