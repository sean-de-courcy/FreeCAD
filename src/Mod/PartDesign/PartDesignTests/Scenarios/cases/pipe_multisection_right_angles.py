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

"""Corpus cases (review pr404-r1, class B): a multisection Pipe ("Transformed") whose consecutive
sections come to lie in perpendicular planes when a corner of its spine is turned to exactly 90
degrees (ops#396, fork PR 404's `sectionTiltsAlong`; found by its round 1 review).

The spine is a sketch in the XZ plane. The profile is the square -2..2 in the XY plane at the
origin. Each section is a square sketch centred on the spine, normal to its leg there.
- `U*`: a U, up 30, then 20 along +X, then 30 down, its last leg turned from straight down
  towards +X by `90 - deg` degrees (deg = 80 when built). A middle section (half width
  `MIDDLE`) at the middle of the second leg, the last (half width 3) at the spine's end. At
  deg = 90 both corners are right angles: the profile and the middle section are perpendicular,
  and the middle section and the last one.
- `L*`: an L, up 30 then 20 turned `deg` degrees from +Z (80 when built), the last section (half
  width 3) at its end, its sketch turned `TURN` degrees about the leg.
The edit turns the corner to exactly 90 degrees (the last section's sketch moves with the leg).
The references are a sketch on the far end's cap and datum points on its four edges and four
vertices; the expectation is each at the last section's own line or corner, where its sketch now
puts it (the cap is the section's square: which solid the sweep builds between the sections
doesn't move it). A pipe that fails to recompute at 90 degrees breaks them all."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Scenarios.harness import Attached, Scenario, ScenarioError, edge, face, vertex
from PartDesignTests.Scenarios import models as m

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
CORNERS = ((-1, -1), (1, -1), (1, 1), (-1, 1))


def frame(normal, turn):
    """The rotation taking the sketch's Z to `normal`, the sketch then turned `turn` degrees
    about it"""
    normal = V(normal).normalize()
    return App.Rotation(normal, turn).multiply(App.Rotation(V(0, 0, 1), normal))


class RightAngleSections(Scenario):
    """The pipe and its far end's references (see the module's docstring)."""

    abstract = True
    area = "pipe_multisection_right_angles"
    CLASSES = ("B",)
    AXES = ("M3", "E4")
    ISSUE = "ops#396"
    FOUND_BY = "review pr404-r1"
    TIER = "F"
    SIZE = 80
    SCALE = 1.0
    REFS = ("cap",) + tuple(f"cap_e{i}" for i in range(4)) + tuple(f"cap_v{i}" for i in range(4))
    START = 80  # the corner's angle when built
    TURN = 0  # the last section's sketch turned about its leg
    END = 3  # the last section's half width
    MIDDLE = None  # the middle section's half width (the U only)
    EDITED = 90  # the corner's angle after the edit
    LAST_FIRST = False  # the Sections list holds the last section first (the U only)

    def points(self, deg):
        """The spine's points in the XZ sketch (x, z), unscaled"""
        raise NotImplementedError

    def lastLeg(self, deg):
        a, b = self.points(deg)[-2:]
        return V(b[0] - a[0], 0, b[1] - a[1]).normalize()

    def endPlacement(self, deg):
        x, z = self.points(deg)[-1]
        return App.Placement(V(*self.s(x, 0, z)), frame(self.lastLeg(deg), self.TURN))

    def build(self, doc):
        self.deg = self.START
        body = m.body(doc)
        pts = [self.s(*p) for p in self.points(self.deg)]
        path = m.sketch(doc, "Path", m.polyline(pts), body, placement=XZ)
        profile = m.sketch(doc, "Profile", m.rectangle(*self.s(-2, -2, 2, 2)), body)
        sections = []
        if self.MIDDLE:
            h = self.MIDDLE
            (x0, z0), (x1, z1) = self.points(self.deg)[1:3]
            at = V(*self.s((x0 + x1) / 2, 0, (z0 + z1) / 2))
            sections.append(
                m.sketch(
                    doc,
                    "Middle",
                    m.rectangle(*self.s(-h, -h, h, h)),
                    body,
                    placement=App.Placement(at, frame(V(x1 - x0, 0, z1 - z0), 0)),
                )
            )
        h = self.END
        sections.append(
            m.sketch(
                doc,
                "Section",
                m.rectangle(*self.s(-h, -h, h, h)),
                body,
                placement=self.endPlacement(self.deg),
            )
        )
        if self.LAST_FIRST:
            sections.reverse()
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (path, [])
        pipe.Transformation = "Multisection"
        pipe.Sections = sections
        pipe.Transition = "Transformed"
        pipe.Refine = False
        doc.recompute()
        if not pipe.isValid():
            raise ScenarioError(f"the pipe is invalid: {pipe.getStatusString()}")
        cap = body.newObject("Sketcher::SketchObject", "On_cap")
        cap.AttachmentSupport = [(pipe, self.names(pipe, self.capFace())[0])]
        cap.MapMode = "FlatFace"
        self.ref("cap", cap, "AttachmentSupport", self.capFace, Attached())
        for i in range(4):
            for kind, target in (("e", self.capEdge), ("v", self.capVertex)):
                key = f"cap_{kind}{i}"
                point = body.newObject("PartDesign::Point", "On_" + key)
                point.AttachmentSupport = [(pipe, self.names(pipe, target(i))[0])]
                point.MapMode = "Vertex" if kind == "v" else "CenterOfMass"
                self.ref(key, point, "AttachmentSupport", lambda t=target, i=i: t(i), Attached())

    # The far end's elements where the last section's sketch puts them (at the current angle)

    def local(self, u, v):
        return self.endPlacement(self.deg).multVec(V(*self.s(u * self.END, v * self.END, 0)))

    def tol(self):
        return 1e-6 * max(1.0, self.scale)

    def capFace(self):
        centre, normal = self.local(0, 0), self.lastLeg(self.deg)
        area = (2 * self.s(self.END)) ** 2
        return face(
            "plane",
            where=lambda f: abs(abs(f.Surface.Axis.dot(normal)) - 1) < 1e-9
            and (f.CenterOfMass - centre).Length < self.tol()
            and abs(f.Area - area) < 1e-6 * area,
        )

    def capEdge(self, i):
        (u0, v0), (u1, v1) = CORNERS[i], CORNERS[(i + 1) % 4]
        mid = self.local((u0 + u1) / 2, (v0 + v1) / 2)
        length = 2 * self.s(self.END)
        # the sweep's caps take their edges as B-splines: the place and the length decide
        return edge(
            where=lambda e: (e.CenterOfMass - mid).Length < self.tol()
            and abs(e.Length - length) < self.tol(),
        )

    def capVertex(self, i):
        return vertex(self.local(*CORNERS[i]))

    def edit(self, doc):
        self.deg = self.EDITED
        pts = [self.s(*p) for p in self.points(self.deg)]
        m.setLines(doc.Path, {i: (a, b) for i, (a, b) in enumerate(zip(pts, pts[1:]))})
        doc.Section.Placement = self.endPlacement(self.deg)


class U(RightAngleSections):
    abstract = True
    MIDDLE = 2.5

    def points(self, deg):
        tilt = math.radians(90 - deg)
        return ((0, 0), (0, 30), (20, 30), (20 + 30 * math.sin(tilt), 30 - 30 * math.cos(tilt)))


class UMiddleSectionSmallerTurnedToRightAngles(U):
    """The U with a middle section of half width 2.5 (the last 3), its last leg turned from 80 to
    90 degrees: two right angles in one plane. The middle section is turned towards the profile,
    and the last one towards the middle section as turned, each by 1e-9 mm at its farthest point:
    the solid turned with the spine (the limit of 1447.091 at 1e-4 rad under each corner). Round 1
    turned the last one towards the middle section's unturned plane: the smaller middle section
    turns more, the last was then past 90 degrees to it (sin(1e-9 / (3 sqrt 2) - 1e-9 / (2.5 sqrt
    2)) < 0), OCCT paired it against the spine and the pipe failed."""


class UEqualSectionsTurnedOverToRightAngles(U):
    """The same with the middle section as large as the last (3) and the last section's sketch
    turned 180 degrees about its leg (the same square). Round 1's turns of the two sections
    cancelled, the tie was back and rounding chose again: the pipe failed at 90 degrees with the
    sketch turned 180 or 270 degrees, depending on the scale. Each pair now keeps its own margin."""

    MIDDLE = 3
    TURN = 180


class UMiddleSectionLargerTurnedToRightAngles(U):
    """Control: the middle section larger (3.5) than the last: the last section turns more than
    the middle one, both corners stay under 90 degrees, and the pipe is the solid turned with
    the spine (2087.172)."""

    MIDDLE = 3.5


class L(RightAngleSections):
    abstract = True

    def points(self, deg):
        a = math.radians(deg)
        return ((0, 0), (0, 30), (20 * math.sin(a), 30 + 20 * math.cos(a)))


class LSectionTurnedToRightAngle(L):
    """The L with the last section's sketch turned 90 degrees about its leg, its corner turned
    from 80 to 90 degrees: the case fork PR 404 fixes (before it, the pipe failed at 90 degrees
    on Windows with the sketch turned 90, 180 or 270 degrees)."""

    TURN = 90


class UMiddleSectionTwelveTimesSmallerTurnedToRightAngles(U):
    """The U with a middle section of half width 0.25 and the last 3 (12 times larger). Measured
    against the middle section as turned, the last one starts 1e-9 * 12 mm past perpendicular,
    beyond the 1e-8 mm reach: round 2 left it unturned and the pipe failed. The reach is read
    from the sections as placed, the turn against the middle one as turned: the solid turned with
    the spine (the limit of 567.716 at 1e-4 rad under each corner)."""

    FOUND_BY = "review pr404-r2"
    MIDDLE = 0.25


class UMiddleSectionTenTimesSmallerTurnedToRightAngles(U):
    """The same with the middle section 0.3 (the last exactly 10 times larger): on round 2 the
    last section sat on the reach's edge and rounding decided (the pipe failed at 600 mm)."""

    FOUND_BY = "review pr404-r2"
    MIDDLE = 0.3


class UMiddleSectionFiveTimesSmallerTurnedToRightAngles(U):
    """Control: the middle section 0.6 (the last 5 times larger), inside the reach on every
    round: the solid turned with the spine."""

    FOUND_BY = "review pr404-r2"
    MIDDLE = 0.6


class UMiddleSectionTwelveTimesSmallerTurnedNearlyToRightAngles(U):
    """The U with a middle section of half width 0.25, the last 3 with its sketch turned 90
    degrees, its last corner turned to 1e-9 rad under 90 degrees (as a sketch's solver leaves a
    right angle). The middle section, turned towards the profile, brings the last one, placed
    about 4e-9 mm past perpendicular to it, short of the margin against it as turned: round 3 left
    it as placed (it read the band's near side as placed too) and the pipe failed. It is turned: the
    solid turned with the spine."""

    FOUND_BY = "review pr404-r3s"
    MIDDLE = 0.25
    TURN = 90
    EDITED = 90 - math.degrees(1e-9)


class USectionsListedLastFirstTurnedToRightAngles(U):
    """The U with a middle section of half width 2.5, the Sections list holding the last section
    first. OCCT sweeps the sections in their order along the spine; round 3 paired them as
    listed, turned the wrong pairs and the pipe failed at 90 degrees. Each is turned against the
    one before it along the spine: the solid of the U listed in order."""

    FOUND_BY = "review pr404-r3s"
    MIDDLE = 2.5
    LAST_FIRST = True
