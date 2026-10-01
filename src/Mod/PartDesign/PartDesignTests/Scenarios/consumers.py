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

"""Consumers that lose an element: a SubShapeBinder, a Hole, a Helix, a Loft and a Pipe whose
referenced element is deleted. Each should fail; each used to carry on without the element, or
with something else in its place (ops#69, ops#70, ops#71)."""

import FreeCAD as App
import Part

from .harness import BROKEN, Bound, Scenario, edge, face, faceNormal, pieces, vertex
from . import models as m

V = App.Vector


def wall(x):
    """The planar face of the slot's wall at x (normal along X)."""

    def side(f):
        n = faceNormal(f)
        return abs(abs(n.x) - 1) < 1e-9 and abs(f.Surface.Position.x - x) < 1e-9

    return face("plane", where=side)


class BinderFacesRemoved(Scenario):
    """A block 0..20 x 0..10 x 0..10 with a slot (x 8..12, y 4..6) through it; binder A binds
    the slot's left (x = 8) and right (x = 12) walls, binder B its right wall only. The slot
    becomes a step along the whole right side (x 8..21): the right wall is gone, the left one
    stays, and both binders should fail. A used to bind the left wall alone, and B kept its old
    face, with no error (ops#69)."""

    area = "consumers"
    REFS = ("binder_both", "binder_right")
    gone = False

    def both(self):
        return BROKEN if self.gone else pieces(face("plane", where=self.walls))

    def right(self):
        return BROKEN if self.gone else wall(12)

    @staticmethod
    def walls(f):
        return wall(8).matches(f, 1e-7) or wall(12).matches(f, 1e-7)

    def build(self, doc):
        body = m.body(doc)
        profile = m.sketch(doc, "Profile", m.rectangle(0, 0, 20, 10), body)
        m.pad(body, profile, 10)
        sketch = m.sketch(doc, "SlotSketch", m.rectangle(8, 4, 12, 6), body, z=10)
        slot = m.pocketThroughAll(body, sketch, "Slot")
        doc.recompute()
        for name, expect in (("binder_both", self.both), ("binder_right", self.right)):
            binder = doc.addObject("PartDesign::SubShapeBinder", name)
            binder.Support = [(slot, tuple(expect().select(slot.Shape)))]
            self.ref(name, binder, "Support", expect, Bound())

    def edit(self, doc):
        m.moveRectangle(doc.SlotSketch, 8, 4, 21, 6)
        self.gone = True


class HoleProfileCircleRemoved(Scenario):
    """A plate (0..30 x 0..30 x 0..5); a Hole, diameter 3 through all, whose Profile is the two
    circles (radius 1.5 at (8, 15) and (22, 15)) of a sketch on the top face. The second circle
    is deleted and a new one drawn at (22, 20): its edge is gone, and the hole should fail. It
    used to drill the first hole alone, with no error (ops#70)."""

    area = "consumers"
    MULTI = True
    REFS = ("hole_profile",)
    gone = False

    def circles(self):
        return BROKEN if self.gone else pieces(edge("circle", radius=1.5))

    def build(self, doc):
        body = m.body(doc)
        plate = m.sketch(doc, "Plate", m.rectangle(0, 0, 30, 30), body)
        m.pad(body, plate, 5)
        circles = [m.circle(8, 15, 1.5), m.circle(22, 15, 1.5)]
        sketch = m.sketch(doc, "HoleSketch", circles, body, z=5)
        doc.recompute()
        hole = body.newObject("PartDesign::Hole", "Hole")
        hole.Profile = (sketch, self.circles().select(sketch.Shape))
        hole.Diameter = 3
        hole.DepthType = "ThroughAll"
        self.ref("hole_profile", hole, "Profile", self.circles)

    def edit(self, doc):
        doc.HoleSketch.delGeometry(1)
        doc.HoleSketch.addGeometry(m.circle(22, 20, 1.5), False)
        self.gone = True


class HelixProfileCircleRemoved(Scenario):
    """A core (cylinder radius 9 about Z, z -2..14) and a Helix about Z, pitch 5, height 10,
    whose Profile is a ring: the two circles (radius 1.5 and 0.5, centred at x = 10, z = 0) of a
    sketch on the XZ plane, which make a tube. The inner circle is deleted and a new one drawn at
    x = 10.3: its edge is gone, and the helix should fail. It used to sweep the outer circle alone, a solid
    coil, with no error (ops#70)."""

    area = "consumers"
    MULTI = True
    REFS = ("helix_profile",)
    gone = False

    def circles(self):
        return BROKEN if self.gone else pieces(edge("circle", center=(10, 0, 0)))

    def build(self, doc):
        body = m.body(doc)
        core = m.sketch(doc, "Core", [m.circle(0, 0, 9)], body, z=-2)
        m.pad(body, core, 16)
        xz = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # sketch y along Z
        sketch = m.sketch(
            doc, "HelixSketch", [m.circle(10, 0, 1.5), m.circle(10, 0, 0.5)], body, placement=xz
        )
        doc.recompute()
        helix = body.newObject("PartDesign::AdditiveHelix", "Helix")
        helix.Profile = (sketch, self.circles().select(sketch.Shape))
        helix.ReferenceAxis = (sketch, ["V_Axis"])
        helix.Mode = "pitch-height-angle"
        helix.Pitch = 5
        helix.Height = 10
        self.ref("helix_profile", helix, "Profile", self.circles)

    def edit(self, doc):
        doc.HelixSketch.delGeometry(1)
        doc.HelixSketch.addGeometry(m.circle(10.3, 0, 0.5), False)
        self.gone = True


class LoftToRemovedPoint(Scenario):
    """A Loft from a square (-10..10, z = 0) to a point: its section is the first of the two
    points of a sketch at z = 30, P1 (0, 0) and P2 (5, 5). P1 is deleted: the section's vertex
    is gone, and the loft should fail. It used to take the whole sketch, so its apex moved to
    P2 (5, 5, 30), with no error (ops#71)."""

    area = "consumers"
    REFS = ("loft_section",)
    gone = False
    kind = "PartDesign::AdditiveLoft"

    def apex(self):
        return BROKEN if self.gone else vertex((0, 0, 30))

    def points(self, doc, body):
        return m.sketch(
            doc, "Points", [Part.Point(V(0, 0, 0)), Part.Point(V(5, 5, 0))], body, z=30
        )

    def build(self, doc):
        body = m.body(doc)
        square = m.sketch(doc, "Square", m.rectangle(-10, -10, 10, 10), body)
        points = self.points(doc, body)
        doc.recompute()
        feature = body.newObject(self.kind, "Feature")
        self.setUp(doc, body, feature, square)
        feature.Sections = [(points, tuple(self.names(points, self.apex())))]
        self.ref(self.REFS[0], feature, "Sections", self.apex)

    def setUp(self, doc, body, feature, square):
        feature.Profile = square

    def edit(self, doc):
        doc.Points.delGeometry(0)
        self.gone = True


class PipeToRemovedPoint(LoftToRemovedPoint):
    """As LoftToRemovedPoint, with a Pipe along a line from (0, 0, 0) to (0, 0, 30), its last
    section the point (multisection). The pipe used to take the whole sketch, so it ended on
    P2 (ops#71)."""

    REFS = ("pipe_section",)
    kind = "PartDesign::AdditivePipe"

    def setUp(self, doc, body, feature, square):
        xz = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
        spine = m.sketch(doc, "Spine", m.polyline([(0, 0), (0, 30)]), body, placement=xz)
        feature.Profile = square
        feature.Spine = (spine, ["Edge1"])
        feature.Transformation = "Multisection"


class PipeFromRemovedPoint(Scenario):
    """A Pipe along a line from (0, 0, 0) to (0, 0, 30) whose profile is the first of two points
    of a sketch at z = 0, P1 (0, 0) and P2 (5, 5), and whose section is a square (-10..10,
    z = 30). P1 is deleted: the profile's vertex is gone, and the pipe should fail. It used to
    take the whole sketch, starting at P2 (ops#71)."""

    area = "consumers"
    REFS = ("pipe_profile",)
    gone = False

    def start(self):
        return BROKEN if self.gone else vertex((0, 0, 0))

    def build(self, doc):
        body = m.body(doc)
        points = m.sketch(doc, "Points", [Part.Point(V(0, 0, 0)), Part.Point(V(5, 5, 0))], body)
        square = m.sketch(doc, "Square", m.rectangle(-10, -10, 10, 10), body, z=30)
        xz = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))
        spine = m.sketch(doc, "Spine", m.polyline([(0, 0), (0, 30)]), body, placement=xz)
        doc.recompute()
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = (points, self.names(points, self.start()))
        pipe.Spine = (spine, ["Edge1"])
        pipe.Transformation = "Multisection"
        pipe.Sections = [square]
        self.ref("pipe_profile", pipe, "Profile", self.start)

    def edit(self, doc):
        doc.Points.delGeometry(0)
        self.gone = True
