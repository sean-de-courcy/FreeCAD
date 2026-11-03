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

"""Corpus cases (review pr404-r5s, class B): multisection Pipes whose right angles lie across a
spine corner and then a smooth stretch, or along a smooth spine only (ops#396, fork PR 404). Round
5 counted only turns across a corner for the stop (decision 228), and these built again: the
review found `SmoothFixedHexagons` 2.8 % off and `MixedRoundCornerSquares` 0.3 % off, on integration
too, and the same family in Standard and Frenet (`SmoothStandardHexagons`, `SmoothFrenetHexagons`,
right at 600 mm, wrong at 60 mm and 4 m). Round 6 withdraws the corner gate: every one of these
stops on the PR, right -> loud for those integration builds right.

MIXED: a Part feature's wire: a line of 30 along +Z, a line of 20 along +X (a corner of 90 degrees),
a quarter arc of radius 15 in the plane z = 30 from +X to +Y. Squares (or hexagons, the last turned
30) of half-width 2 at the origin (normal +Z), 3 at the middle of the X line (normal +X) and 3 at the
arc's end (normal +Y). SMOOTH: the PR's smooth3d spine (two quarter arcs and a line). Built with the
sections 1e-3 rad short of perpendicular to the one before (each turned towards it), the edit makes
them perpendicular. `cap_solid` expects the far cap only if the volume is within 1e-3 of the pipe with
1e-4 rad short (scratch document), else the start cap, which the reference does not hold."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, ScenarioError, face
from PartDesignTests.Scenarios import models as m

V = App.Vector
S2 = math.sqrt(0.5)


def frame(normal, turn=0.0):
    normal = V(normal).normalize()
    return App.Rotation(normal, turn).multiply(App.Rotation(V(0, 0, 1), normal))


def ngon(n, h):
    return m.polygon(
        [(h * math.cos(2 * math.pi * k / n), h * math.sin(2 * math.pi * k / n)) for k in range(n)]
    )


class Base(Scenario):
    abstract = True
    area = "pipe_multisection_mixed"
    CLASSES = ("B",)
    AXES = ("M3", "E4")
    ISSUE = "ops#396"
    FOUND_BY = "review pr404-r5s"
    TIER = "F"
    SIZE = 60
    SCALE = 10.0
    REFS = ("cap_solid",)
    MODE = "Standard"
    SIDES = 4
    LAST_TURN = 0.0
    TRANSITION = "Transformed"

    def spine(self):
        s = self.s
        if self.KIND == "mixed":
            r = s(15)
            poly = Part.makePolygon([V(0, 0, 0), V(0, 0, s(30)), V(s(20), 0, s(30))])
            arc = Part.Arc(
                V(s(20), 0, s(30)),
                V(s(20) + r * S2, r - r * S2, s(30)),
                V(s(20) + r, r, s(30)),
            ).toShape()
            return Part.Wire([poly.Edges[0], poly.Edges[1], arc])
        R = L = s(20)
        a1 = Part.Arc(V(0, 0, 0), V(R * S2, R - R * S2, 0), V(R, R, 0)).toShape()
        l2 = Part.LineSegment(V(R, R, 0), V(R, R + L, 0)).toShape()
        a3 = Part.Arc(V(R, R + L, 0), V(R, R + L + R * S2, R - R * S2), V(R, 2 * R + L, R)).toShape()
        return Part.Wire([a1, l2, a3])

    def places(self):
        s = self.s
        if self.KIND == "mixed":
            return [
                (V(0, 0, 0), V(0, 0, 1)),
                (V(s(10), 0, s(30)), V(1, 0, 0)),
                (V(s(35), s(15), s(30)), V(0, 1, 0)),
            ]
        return [
            (V(0, 0, 0), V(1, 0, 0)),
            (V(s(20), s(30), 0), V(0, 1, 0)),
            (V(s(20), s(60), s(20)), V(0, 0, 1)),
        ]

    def normals(self, under):
        out, prev = [], None
        for _, n in self.places():
            n = V(n)
            if prev is not None and under:
                axis = n.cross(prev)
                n = App.Rotation(axis, math.degrees(under)).multVec(n)
            out.append(n)
            prev = n
        return out

    def sizes(self):
        return (2.0, 3.0, 3.0)

    def placement(self, i, under):
        turn = self.LAST_TURN if i == 2 else 0.0
        return App.Placement(self.places()[i][0], frame(self.normals(under)[i], turn))

    def makePipe(self, doc, body, under):
        path = doc.addObject("Part::Feature", "Path")
        path.Shape = self.spine()
        sks = [
            m.sketch(
                doc,
                "Profile" if i == 0 else f"Section{i - 1}",
                ngon(self.SIDES, self.s(self.sizes()[i])),
                body,
                placement=self.placement(i, under),
            )
            for i in range(3)
        ]
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = sks[0]
        pipe.Spine = (path, [])
        pipe.Transformation = "Multisection"
        pipe.Sections = sks[1:]
        pipe.Transition = self.TRANSITION
        pipe.Mode = self.MODE
        pipe.Refine = False
        doc.recompute()
        return pipe

    def limitVolume(self):
        scratch = App.newDocument("PipeR5sLimit")
        try:
            pipe = self.makePipe(scratch, m.body(scratch), 1e-4)
            if not pipe.isValid():
                raise ScenarioError(f"the limit pipe is invalid: {pipe.getStatusString()}")
            return pipe.Shape.Volume
        finally:
            App.closeDocument(scratch.Name)

    def tol(self):
        return 1e-6 * max(1.0, self.scale)

    def area_(self, i):
        h = self.s(self.sizes()[i])
        return 0.5 * self.SIDES * h * h * math.sin(2 * math.pi / self.SIDES)

    def capTest(self, i):
        centre, normal = self.places()[i][0], self.places()[i][1]

        def test(f):
            return (
                abs(abs(f.Surface.Axis.dot(normal.normalize())) - 1) < 1e-6
                and (f.CenterOfMass - centre).Length < self.tol()
                and abs(f.Area - self.area_(i)) < 1e-6 * self.area_(i)
            )

        return test

    def expected(self):
        def test(f):
            volume = self.doc.getObject("Pipe").Shape.Volume
            limit = self.limit if self.limit is not None else volume
            if abs(volume - limit) < 1e-3 * abs(limit):
                return self.capTest(2)(f)
            return self.capTest(0)(f)

        return face("plane", where=test)

    def build(self, doc):
        self.doc = doc
        self.limit = None
        body = m.body(doc)
        pipe = self.makePipe(doc, body, 1e-3)
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        cap = body.newObject("Sketcher::SketchObject", "On_cap")
        cap.AttachmentSupport = [(pipe, self.names(pipe, face("plane", where=self.capTest(2)))[0])]
        cap.MapMode = "FlatFace"
        self.ref("cap_solid", cap, "AttachmentSupport", self.expected, Attached())

    def edit(self, doc):
        self.limit = self.limitVolume()
        for i in range(1, 3):
            doc.getObject(f"Section{i - 1}").Placement = self.placement(i, 0.0)
        doc.recompute()


class MixedStandardSquares(Base):
    """Corner (about Y) then smooth (about Z), Standard."""

    KIND = "mixed"


class MixedStandardHexagons(Base):
    KIND = "mixed"
    SIDES = 6
    LAST_TURN = 30.0


class MixedFixedSquares(Base):
    KIND = "mixed"
    MODE = "Fixed"


class MixedFixedHexagons(Base):
    KIND = "mixed"
    MODE = "Fixed"
    SIDES = 6
    LAST_TURN = 30.0


class MixedRoundCornerSquares(Base):
    KIND = "mixed"
    TRANSITION = "Round corner"


class SmoothFixedSquares(Base):
    """The PR's smooth3d spine in Fixed mode, whose frame never turns."""

    KIND = "smooth"
    MODE = "Fixed"


class SmoothFixedHexagons(Base):
    KIND = "smooth"
    MODE = "Fixed"
    SIDES = 6
    LAST_TURN = 30.0


class SmoothStandardHexagons(Base):
    """The smooth3d spine in Standard mode, hexagons, the last turned 30 (the probe of sfd71: right
    at 600 mm, 2.5 % off at 60 mm and 4 m, on integration too)."""

    KIND = "smooth"
    SIDES = 6
    LAST_TURN = 30.0


class SmoothFrenetHexagons(SmoothStandardHexagons):
    MODE = "Frenet"
