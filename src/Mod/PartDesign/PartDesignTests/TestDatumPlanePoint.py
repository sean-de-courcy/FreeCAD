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

"""A datum plane on a model's planar face and a vertex: Onshape's Plane point (FreeCAD-CH ops#640,
rank 6; hands-on check B3-5). The plane goes through the vertex, parallel to the face, whichever is
picked first. It is the mode suggested for the pair; Tangent stays offered, and stays the mode for
a curved face and a vertex.

The models are designed here: a 10 mm cube, and a wedge whose slanted side, from x = 0 at y = 0 to
x = 2 at y = 10, faces (-5, 1, 0) / sqrt(26)."""

import math
import unittest

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector
TOL = 1e-7


def elementWhere(elements, kind, test):
    found = [i + 1 for i, e in enumerate(elements) if test(e)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} {kind}s match, expected one")
    return f"{kind}{found[0]}"


def vertexAt(shape, point):
    return elementWhere(shape.Vertexes, "Vertex", lambda v: (v.Point - point).Length < TOL)


def planarFaceFacing(shape, normal):
    return elementWhere(
        shape.Faces,
        "Face",
        lambda f: f.Surface.__class__.__name__ == "Plane"
        and (f.normalAt(*f.Surface.parameter(f.CenterOfMass)) - normal).Length < 1e-6,
    )


class TestDatumPlanePoint(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("DatumPlanePoint")
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def cube(self):
        box = self.body.newObject("PartDesign::AdditiveBox", "Cube")
        box.Length = box.Width = box.Height = 10
        self.doc.recompute()
        self.assertTrue(box.isValid(), box.getStatusString())
        return box

    def wedge(self):
        wedge = self.body.newObject("PartDesign::AdditiveWedge", "Wedge")
        wedge.Xmin, wedge.Ymin, wedge.Zmin = 0, 0, 0
        wedge.Xmax, wedge.Ymax, wedge.Zmax = 10, 10, 10
        wedge.X2min, wedge.X2max, wedge.Z2min, wedge.Z2max = 2, 8, 2, 8
        self.doc.recompute()
        self.assertTrue(wedge.isValid(), wedge.getStatusString())
        return wedge

    def plane(self, support):
        plane = self.body.newObject("PartDesign::Plane", "PlanePoint")
        plane.AttachmentSupport = support
        return plane

    def suggestion(self, plane):
        engine = Part.AttachEngine(plane.AttacherType)
        engine.readParametersFromFeature(plane)
        return engine.suggestModes()

    def assertPlane(self, plane, normal, point):
        """The plane faces `normal` and goes through `point`."""
        self.doc.recompute()
        self.assertTrue(plane.isValid(), plane.getStatusString())
        placement = plane.Placement
        axis = placement.Rotation.multVec(V(0, 0, 1))
        self.assertLess((axis - normal).Length, 1e-9, (axis, normal))
        self.assertAlmostEqual((point - placement.Base).dot(normal), 0, delta=TOL)

    def testCubeFaceAndVertex(self):
        """The front face (y = 0, facing -y) and the far top corner: the plane y = 10, facing -y."""
        cube = self.cube()
        face = planarFaceFacing(cube.Shape, V(0, -1, 0))
        corner = V(10, 10, 10)
        plane = self.plane([(cube, face), (cube, vertexAt(cube.Shape, corner))])
        suggested = self.suggestion(plane)
        self.assertEqual(suggested["message"], "OK")
        self.assertEqual(suggested["bestFitMode"], "ParallelPlane")
        self.assertIn("TangentPlane", suggested["allApplicableModes"])
        plane.MapMode = suggested["bestFitMode"]
        self.assertPlane(plane, V(0, -1, 0), corner)
        self.assertAlmostEqual(plane.Placement.Base.y, 10, delta=TOL)

    def testVertexFirstGivesTheSamePlane(self):
        cube = self.cube()
        face = planarFaceFacing(cube.Shape, V(0, -1, 0))
        corner = V(10, 10, 10)
        plane = self.plane([(cube, vertexAt(cube.Shape, corner)), (cube, face)])
        suggested = self.suggestion(plane)
        self.assertEqual(suggested["bestFitMode"], "ParallelPlane")
        plane.MapMode = "ParallelPlane"
        self.assertPlane(plane, V(0, -1, 0), corner)
        self.assertAlmostEqual(plane.Placement.Base.y, 10, delta=TOL)

    def testDatumPointAndFace(self):
        """A datum point at (10, 10, 10), picked first, and the cube's front face: the same plane,
        y = 10 facing -y (the point's own placement doesn't orient it)."""
        cube = self.cube()
        point = self.body.newObject("PartDesign::Point", "Corner")
        point.MapMode = "Deactivated"
        point.Placement = App.Placement(V(10, 10, 10), App.Rotation(V(1, 0, 0), 30))
        self.doc.recompute()
        face = planarFaceFacing(cube.Shape, V(0, -1, 0))
        plane = self.plane([(point, ""), (cube, face)])
        plane.MapMode = "ParallelPlane"
        self.assertPlane(plane, V(0, -1, 0), V(10, 10, 10))
        self.assertAlmostEqual(plane.Placement.Base.y, 10, delta=TOL)

    def testTangentIsUnchanged(self):
        """Tangent on the same pair, chosen by hand, is still the face's own plane (y = 0)."""
        cube = self.cube()
        face = planarFaceFacing(cube.Shape, V(0, -1, 0))
        plane = self.plane([(cube, face), (cube, vertexAt(cube.Shape, V(10, 10, 10)))])
        plane.MapMode = "TangentPlane"
        self.doc.recompute()
        self.assertTrue(plane.isValid(), plane.getStatusString())
        axis = plane.Placement.Rotation.multVec(V(0, 0, 1))
        self.assertAlmostEqual(abs(axis.y), 1, delta=1e-9)
        self.assertAlmostEqual(plane.Placement.Base.y, 0, delta=TOL)

    def testWedgeSlantedFaceAndVertex(self):
        """The wedge's slanted side and the corner (10, 0, 0): the plane -5x + y = -50."""
        wedge = self.wedge()
        normal = V(-5, 1, 0) * (1 / math.sqrt(26))
        face = planarFaceFacing(wedge.Shape, normal)
        corner = V(10, 0, 0)
        plane = self.plane([(wedge, face), (wedge, vertexAt(wedge.Shape, corner))])
        self.assertEqual(self.suggestion(plane)["bestFitMode"], "ParallelPlane")
        plane.MapMode = "ParallelPlane"
        self.assertPlane(plane, normal, corner)
        self.assertAlmostEqual(plane.Placement.Base.dot(normal), -50 / math.sqrt(26), delta=TOL)

    def testCurvedFaceAndVertexStaysTangent(self):
        """A cylinder's side and a vertex on its top circle: Tangent, not Plane point."""
        cylinder = self.body.newObject("PartDesign::AdditiveCylinder", "Cylinder")
        cylinder.Radius = 3
        cylinder.Height = 5
        self.doc.recompute()
        side = elementWhere(
            cylinder.Shape.Faces, "Face", lambda f: f.Surface.__class__.__name__ == "Cylinder"
        )
        top = [i + 1 for i, v in enumerate(cylinder.Shape.Vertexes) if abs(v.Point.z - 5) < TOL]
        self.assertTrue(top)
        index = top[0]
        plane = self.plane([(cylinder, side), (cylinder, f"Vertex{index}")])
        suggested = self.suggestion(plane)
        self.assertEqual(suggested["bestFitMode"], "TangentPlane")
        self.assertNotIn("ParallelPlane", suggested["allApplicableModes"])


if __name__ == "__main__":
    unittest.main()
