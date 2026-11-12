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


"""A datum plane at an edge's middle (FreeCAD-CH ops#673, selection parity 11): Onshape's Plane
takes an edge's midpoint as its point (SP10-Q10, "Edge point"). In the fork a midpoint pick in the
Plane dialog stores "Normal to edge" on that edge with MapPathParameter 0.5 (the dialog's part is
in TestPlaneEdgePointGui). These tests pin what 0.5 gives: the exact middle of a line and of a
circular arc (their parameters run with length), and for a B-spline the parametric middle, which
is not the half-length point (documented, not Onshape's: ops#682 has the general Point normal).

Designed geometry: a 20 x 20 x 10 box (its top edge on y = 0 from (0,0,10) to (20,0,10)), a quarter
arc r 5 about the z axis, and a B-spline through four points."""

import math
import unittest

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector
TOL = 1e-7


def edgeName(shape, a, b):
    """The name of shape's edge from a to b (either way)."""
    for i, edge in enumerate(shape.Edges, 1):
        ends = [v.Point for v in edge.Vertexes]
        if len(ends) == 2 and (
            ((ends[0] - a).Length < TOL and (ends[1] - b).Length < TOL)
            or ((ends[0] - b).Length < TOL and (ends[1] - a).Length < TOL)
        ):
            return "Edge%d" % i
    raise AssertionError("no edge from %s to %s" % (a, b))


class TestPlaneEdgePoint(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PlaneEdgePoint")
        self.body = self.doc.addObject("PartDesign::Body", "Body")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def planeAtMiddle(self, obj, sub):
        plane = self.body.newObject("PartDesign::Plane", "EdgePoint")
        plane.AttachmentSupport = [(obj, sub)]
        plane.MapMode = "NormalToEdge"
        plane.MapPathParameter = 0.5
        self.doc.recompute()
        self.assertNotIn("Invalid", plane.State)
        return plane

    @staticmethod
    def normal(plane):
        return plane.Placement.Rotation.multVec(V(0, 0, 1))

    def assertVector(self, actual, expected, tol=TOL):
        self.assertLess((actual - expected).Length, tol, "%s, not %s" % (actual, expected))

    def testLineMiddle(self):
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 20, 20, 10
        self.doc.recompute()
        plane = self.planeAtMiddle(box, edgeName(box.Shape, V(0, 0, 10), V(20, 0, 10)))
        self.assertVector(plane.Placement.Base, V(10, 0, 10))
        self.assertAlmostEqual(abs(self.normal(plane).x), 1.0, places=9)

    def testArcMiddle(self):
        arc = self.doc.addObject("Part::Feature", "Arc")
        circle = Part.Circle(V(0, 0, 0), V(0, 0, 1), 5)
        arc.Shape = Part.ArcOfCircle(circle, 0, math.pi / 2).toShape()
        self.doc.recompute()
        plane = self.planeAtMiddle(arc, "Edge1")
        half = 5 * math.sqrt(0.5)
        self.assertVector(plane.Placement.Base, V(half, half, 0))
        # normal to the arc there: its tangent, along (-1, 1, 0) either way
        n = self.normal(plane)
        self.assertAlmostEqual(abs(n.x), math.sqrt(0.5), places=9)
        self.assertAlmostEqual(abs(n.y), math.sqrt(0.5), places=9)
        self.assertAlmostEqual(n.z, 0.0, places=9)

    def testSplineGetsItsParametricMiddle(self):
        """Documented: 0.5 is the spline's parametric middle, not its half-length point."""
        curve = Part.BSplineCurve()
        curve.interpolate([V(0, 0, 0), V(1, 2, 0), V(6, 3, 0), V(10, 0, 0)])
        spline = self.doc.addObject("Part::Feature", "Spline")
        spline.Shape = curve.toShape()
        self.doc.recompute()
        plane = self.planeAtMiddle(spline, "Edge1")
        edge = spline.Shape.Edges[0]
        first, last = edge.ParameterRange
        self.assertVector(plane.Placement.Base, edge.valueAt((first + last) / 2))
        halfLength = edge.valueAt(edge.getParameterByLength(edge.Length / 2))
        self.assertGreater((plane.Placement.Base - halfLength).Length, 0.01)
