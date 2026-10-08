# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

import unittest
import math

import FreeCAD
from FreeCAD import Base
import Part
import Sketcher


class TestShapeBinder(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestShapeBinder")

    def testTwoBodyShapeBinderCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Box.Length = 1
        self.Box.Width = 1
        self.Box.Height = 1
        self.Body.addObject(self.Box)
        self.Doc.recompute()
        self.Body001 = self.Doc.addObject("PartDesign::Body", "Body001")
        self.ShapeBinder = self.Doc.addObject("PartDesign::ShapeBinder", "ShapeBinder")
        self.ShapeBinder.Support = [(self.Box, "Face1")]
        self.Body001.addObject(self.ShapeBinder)
        self.Doc.recompute()
        self.assertIn("Box", self.ShapeBinder.OutList[0].Label)
        self.assertIn("Body001", self.ShapeBinder.InList[0].Label)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestShapeBinder")
        # print ("omit closing document for debugging")


class TestSubShapeBinder(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestSubShapeBinder")

    def tearDown(self):
        FreeCAD.closeDocument("PartDesignTestSubShapeBinder")

    def testOffsetBinder(self):
        # See PR 7445
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        body.addObject(box)

        box.Length = 10.00000
        box.Width = 10.00000
        box.Height = 10.00000

        binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(box, ("Edge2", "Edge12", "Edge6", "Edge10"))]
        self.Doc.recompute()

        self.assertAlmostEqual(binder.Shape.Length, 40)

        binder.OffsetJoinType = "Tangent"
        binder.Offset = 5.00000
        self.Doc.recompute()

        self.assertAlmostEqual(binder.Shape.Length, 80)

    def testBinderBeforeOrAfterPad(self):
        """Test case for PR #8763"""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        sketch.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        sketch.MapMode = "FlatFace"
        self.Doc.recompute()

        geoList = []
        geoList.append(
            Part.LineSegment(
                Base.Vector(-21.762587, 19.904083, 0), Base.Vector(32.074337, 19.904083, 0)
            )
        )
        geoList.append(
            Part.LineSegment(
                Base.Vector(32.074337, 19.904083, 0), Base.Vector(32.074337, -27.458027, 0)
            )
        )
        geoList.append(
            Part.LineSegment(
                Base.Vector(32.074337, -27.458027, 0), Base.Vector(-21.762587, -27.458027, 0)
            )
        )
        geoList.append(
            Part.LineSegment(
                Base.Vector(-21.762587, -27.458027, 0), Base.Vector(-21.762587, 19.904083, 0)
            )
        )
        sketch.addGeometry(geoList, False)

        conList = []
        conList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        conList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        conList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        conList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        conList.append(Sketcher.Constraint("Horizontal", 0))
        conList.append(Sketcher.Constraint("Horizontal", 2))
        conList.append(Sketcher.Constraint("Vertical", 1))
        conList.append(Sketcher.Constraint("Vertical", 3))
        sketch.addConstraint(conList)
        del geoList, conList

        self.Doc.recompute()

        binder1 = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder1.Support = sketch
        self.Doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        self.Doc.recompute()
        pad.ReferenceAxis = (sketch, ["N_Axis"])
        sketch.Visibility = False
        self.Doc.recompute()

        binder2 = body.newObject("PartDesign::SubShapeBinder", "Binder001")
        binder2.Support = [pad, "Sketch."]
        self.Doc.recompute()

        self.assertAlmostEqual(binder1.Shape.BoundBox.XLength, binder2.Shape.BoundBox.XLength, 2)
        self.assertAlmostEqual(binder1.Shape.BoundBox.YLength, binder2.Shape.BoundBox.YLength, 2)
        self.assertAlmostEqual(binder1.Shape.BoundBox.ZLength, binder2.Shape.BoundBox.ZLength, 2)

        nor1 = binder1.Shape.Face1.normalAt(0, 0)
        nor2 = binder2.Shape.Face1.normalAt(0, 0)
        self.assertAlmostEqual(nor1.getAngle(nor2), 0.0, 2)

    def testBinderWithRevolution(self):
        doc = self.Doc
        body = doc.addObject("PartDesign::Body", "Body")
        doc.recompute()
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        geoList = []
        geoList.append(Part.LineSegment(Base.Vector(10, 10, 0), Base.Vector(30, 10, 0)))
        geoList.append(Part.LineSegment(Base.Vector(30, 10, 0), Base.Vector(30, 15, 0)))
        geoList.append(Part.LineSegment(Base.Vector(30, 15, 0), Base.Vector(10, 15, 0)))
        geoList.append(Part.LineSegment(Base.Vector(10, 15, 0), Base.Vector(10, 10, 0)))
        sketch.addGeometry(geoList, False)
        del geoList
        constraintList = []
        constraintList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        constraintList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        constraintList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        constraintList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        constraintList.append(Sketcher.Constraint("Horizontal", 0))
        constraintList.append(Sketcher.Constraint("Horizontal", 2))
        constraintList.append(Sketcher.Constraint("Vertical", 1))
        constraintList.append(Sketcher.Constraint("Vertical", 3))
        sketch.addConstraint(constraintList)
        del constraintList
        doc.recompute()
        binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = sketch
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = (
            binder,
            [
                "",
            ],
        )
        revolution.ReferenceAxis = (doc.getObject("Y_Axis"), [""])
        revolution.Angle = 360.0
        revolution.Reversed = 1
        doc.recompute()
        revolution.Angle2 = 60.0
        doc.recompute()
        self.assertAlmostEqual(binder.Shape.Area, 100)
        volume = 100 * math.pi * 2 * 20
        self.assertAlmostEqual(revolution.Shape.Volume, volume)


class TestShapeBinderOfACoordinateSystem(unittest.TestCase):
    """A ShapeBinder of an element of a coordinate system (as the command makes it: the element,
    no subname) is placed in the coordinate system (FreeCAD-CH ops#200). The coordinate system
    sits in the body at (3, 4, 5), turned 90 degrees about X: its XY plane faces -Y, its Y axis
    runs along +Z, its origin is (3, 4, 5). It was at the body's origin."""

    bodyPlacement = FreeCAD.Placement()

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestBinderOfLCS")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Body.Placement = self.bodyPlacement
        self.Lcs = self.Doc.addObject("Part::LocalCoordinateSystem", "LCS")
        self.Body.addObject(self.Lcs)
        self.Lcs.Placement = FreeCAD.Placement(
            FreeCAD.Vector(3, 4, 5), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
        )
        self.Doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def binder(self, role):
        [element] = [f for f in self.Lcs.OriginFeatures if f.Role == role]
        binder = self.Body.newObject("PartDesign::ShapeBinder", "Binder")
        binder.Support = [(element, "")]
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        return binder

    def testPlane(self):
        [face] = self.binder("XY_Plane").Shape.Faces
        plane = face.Surface
        self.assertLess(plane.Axis.cross(FreeCAD.Vector(0, -1, 0)).Length, 1e-9)
        self.assertLess(abs((FreeCAD.Vector(3, 4, 5) - plane.Position).dot(plane.Axis)), 1e-9)

    def testLine(self):
        [edge] = self.binder("Y_Axis").Shape.Edges
        line = edge.Curve
        self.assertLess(line.Direction.cross(FreeCAD.Vector(0, 0, 1)).Length, 1e-9)
        offset = line.Location.sub(FreeCAD.Vector(3, 4, 5))
        self.assertLess(offset.cross(line.Direction).Length, 1e-9)

    def testBodyAxis(self):
        """The body's Z axis: a line along Z through the origin. An App::Line runs along its
        placement's X; the binder's line ran along its Z."""
        [axis] = [f for f in self.Body.Origin.OriginFeatures if f.Role == "Z_Axis"]
        binder = self.Body.newObject("PartDesign::ShapeBinder", "BodyAxis")
        binder.Support = [(axis, "")]
        self.Doc.recompute()
        [edge] = binder.Shape.Edges
        line = edge.Curve
        self.assertLess(line.Direction.cross(FreeCAD.Vector(0, 0, 1)).Length, 1e-9)
        self.assertLess(line.Location.cross(line.Direction).Length, 1e-9)

    def testPoint(self):
        [vertex] = self.binder("Origin").Shape.Vertexes
        self.assertLess(vertex.Point.distanceToPoint(FreeCAD.Vector(3, 4, 5)), 1e-9)

    def assertPlaneAt(self, shape, placement):
        """The XY plane of the coordinate system, carried by placement: its normal is -Y, it
        passes through (3, 4, 5)."""
        [face] = shape.Faces
        plane = face.Surface
        axis = placement.Rotation.multVec(FreeCAD.Vector(0, -1, 0))
        self.assertLess(plane.Axis.cross(axis).Length, 1e-9)
        point = placement.multVec(FreeCAD.Vector(3, 4, 5))
        self.assertLess(abs((point - plane.Position).dot(plane.Axis)), 1e-9)

    def testPathThroughTheBody(self):
        """The plane reached through the body, (Body, "LCS.XY_Plane001."): in the coordinate
        system, as the coordinate system's own path gives it. It was at the body's origin
        (FreeCAD-CH ops#207: LocalCoordinateSystem::extensionGetSubObject)."""
        import Part

        [element] = [f for f in self.Lcs.OriginFeatures if f.Role == "XY_Plane"]
        path = "%s.%s." % (self.Lcs.Name, element.Name)
        self.assertPlaneAt(Part.getShape(self.Body, path, transform=False), FreeCAD.Placement())
        self.assertPlaneAt(Part.getShape(self.Body, path), self.bodyPlacement)
        # The coordinate system's own path, unchanged
        self.assertPlaneAt(
            Part.getShape(self.Lcs, element.Name + "."), FreeCAD.Placement()
        )
        placement = self.Body.getSubObject(path, retType=3)
        self.assertTrue(placement.isSame(self.bodyPlacement.multiply(self.Lcs.Placement), 1e-9))

    def testSubShapeBinderOfThePath(self):
        """A SubShapeBinder outside the body, of the plane through the body: where the plane
        is in the document."""
        [element] = [f for f in self.Lcs.OriginFeatures if f.Role == "XY_Plane"]
        binder = self.Doc.addObject("PartDesign::SubShapeBinder", "PathBinder")
        binder.Support = [(self.Body, "%s.%s." % (self.Lcs.Name, element.Name))]
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertPlaneAt(binder.Shape, self.bodyPlacement)

    def testPointFollowsTheMove(self):
        """The coordinate system moved after the binder was made: the binder follows it at the
        next recompute (FreeCAD-CH ops#206)."""
        binder = self.binder("Origin")
        self.Lcs.Placement = FreeCAD.Placement(FreeCAD.Vector(-2, 6, 1), FreeCAD.Rotation())
        self.Doc.recompute()
        [vertex] = binder.Shape.Vertexes
        self.assertLess(vertex.Point.distanceToPoint(FreeCAD.Vector(-2, 6, 1)), 1e-9)


class TestShapeBinderOfACoordinateSystemInAPlacedBody(TestShapeBinderOfACoordinateSystem):
    """The same in a body moved and turned: the binder's shape is in the body."""

    bodyPlacement = FreeCAD.Placement(
        FreeCAD.Vector(5, -4, 9), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 0), 30)
    )
