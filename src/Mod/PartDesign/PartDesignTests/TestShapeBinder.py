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
import os
import tempfile

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

    def _twoBoxesAndBinder(self):
        """Two 10 mm Part boxes, the second at x = 20, and a ShapeBinder in a body."""
        box = self.Doc.addObject("Part::Box", "Box")
        other = self.Doc.addObject("Part::Box", "Box001")
        other.Placement.Base = FreeCAD.Vector(20, 0, 0)
        body = self.Doc.addObject("PartDesign::Body", "Body")
        binder = body.newObject("PartDesign::ShapeBinder", "ShapeBinder")
        return box, other, binder

    def _assertStillTopFace(self, binder):
        """The binder's shape is still the box's top face: the failed recompute left it."""
        self.assertEqual(len(binder.Shape.Faces), 1)
        self.assertAlmostEqual(binder.Shape.Area, 100, places=6)
        self.assertAlmostEqual(binder.Shape.BoundBox.ZMin, 10, places=6)
        self.assertAlmostEqual(binder.Shape.BoundBox.ZMax, 10, places=6)

    def testSupportOnTwoObjectsFails(self):
        """A binder binds one object: a Support on two fails its recompute and names the one
        it would drop, instead of binding the first object's face alone (ops#251)."""
        box, other, binder = self._twoBoxesAndBinder()
        binder.Support = [(box, "Face6")]
        self.Doc.recompute()
        binder.Support = [(box, "Face6"), (other, "Face6")]
        self.Doc.recompute()
        self.assertFalse(binder.isValid())
        self.assertIn("Box001", binder.getStatusString())
        self._assertStillTopFace(binder)

    def _assertMixedSupportFails(self, subs):
        box, _, binder = self._twoBoxesAndBinder()
        binder.Support = [(box, "Face6")]
        self.Doc.recompute()
        binder.Support = [(box, sub) for sub in subs]
        self.Doc.recompute()
        self.assertFalse(binder.isValid())
        self.assertIn("Face6", binder.getStatusString())
        self._assertStillTopFace(binder)

    def testSupportWithWholeObjectAndElementsFails(self):
        """The whole box and one of its faces: neither reading is the user's, so the recompute
        fails instead of binding the whole box (ops#251)."""
        self._assertMixedSupportFails(["", "Face6"])

    def testSupportWithElementsAndWholeObjectFails(self):
        """The same with the face first, which bound the face alone (PR 232 review L4)."""
        self._assertMixedSupportFails(["Face6", ""])

    def testFailureNamesObjectsByLabel(self):
        """The failure names the objects by their labels, as the user knows them (PR 232 review
        L3, ops#266)."""
        box, other, binder = self._twoBoxesAndBinder()
        box.Label = "Left box"
        other.Label = "Right box"
        binder.Support = [(box, "Face6"), (other, "Face6")]
        self.Doc.recompute()
        self.assertFalse(binder.isValid())
        status = binder.getStatusString()
        self.assertIn("'Left box'", status)
        self.assertIn("'Right box'", status)
        self.assertNotIn("Box001", status)

    def testSupportOnADatumsElementFails(self):
        """An origin plane is bound as a whole, so (XY_Plane, "X") fails, and says so: it read
        "both as a whole and by its elements" (PR 232 review L6, ops#266)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        [plane] = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        binder = body.newObject("PartDesign::ShapeBinder", "ShapeBinder")
        binder.Support = [(plane, "X")]
        self.Doc.recompute()
        self.assertFalse(binder.isValid())
        status = binder.getStatusString()
        self.assertIn("datum '" + plane.Label + "' by its elements ('X')", status)
        self.assertNotIn("both as a whole", status)
        binder.Support = [(plane, "")]
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertEqual(len(binder.Shape.Faces), 1)

    def testSupportOnOneObjectBindsItsFaces(self):
        """Two faces of one box still bind: the 10 x 10 faces at z = 0 and z = 10 (ops#251)."""
        box, _, binder = self._twoBoxesAndBinder()
        binder.Support = [(box, ("Face5", "Face6"))]
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertEqual(len(binder.Shape.Faces), 2)
        self.assertAlmostEqual(binder.Shape.Area, 200, places=6)
        self.assertEqual(sorted(round(f.CenterOfMass.z, 6) for f in binder.Shape.Faces), [0, 10])

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

    def testGlobalPlacementOfTheElement(self):
        """An element's global placement goes through its coordinate system: body, coordinate
        system, element (FreeCAD-CH ops#210). It skipped the coordinate system."""
        [element] = [f for f in self.Lcs.OriginFeatures if f.Role == "Y_Axis"]
        expected = self.bodyPlacement.multiply(self.Lcs.Placement).multiply(element.Placement)
        self.assertTrue(element.getGlobalPlacement().isSame(expected, 1e-9))
        # The body's own origin: at identity in the body
        [axis] = [f for f in self.Body.Origin.OriginFeatures if f.Role == "Z_Axis"]
        expected = self.bodyPlacement.multiply(axis.Placement)
        self.assertTrue(axis.getGlobalPlacement().isSame(expected, 1e-9))
        # A coordinate system at the document root, in no group: coordinate system, element
        # (FreeCAD-CH ops#227)
        free = self.Doc.addObject("Part::LocalCoordinateSystem", "FreeLCS")
        free.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-2, 6, 1), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 30)
        )
        [element] = [f for f in free.OriginFeatures if f.Role == "Z_Axis"]
        expected = free.Placement.multiply(element.Placement)
        self.assertTrue(element.getGlobalPlacement().isSame(expected, 1e-9))

    def testTracedBinderInAnotherBody(self):
        """A traced ShapeBinder of the plane, in a second body placed elsewhere: the plane stays
        where it is in the document, whichever body moves. The trace composes the element's
        global placement with its placement in the body, so it stays single (FreeCAD-CH
        ops#210)."""
        other = self.Doc.addObject("PartDesign::Body", "Other")
        other.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-7, 2, 1), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 1), 50)
        )
        [element] = [f for f in self.Lcs.OriginFeatures if f.Role == "XY_Plane"]
        binder = other.newObject("PartDesign::ShapeBinder", "Traced")
        binder.TraceSupport = True
        binder.Support = [(element, "")]
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())

        def inDocument():
            shape = binder.Shape.copy()
            shape.Placement = other.Placement.multiply(shape.Placement)
            return shape

        self.assertPlaneAt(inDocument(), self.bodyPlacement)
        self.Doc.recompute()
        self.assertPlaneAt(inDocument(), self.bodyPlacement)
        other.Placement = FreeCAD.Placement(FreeCAD.Vector(4, 0, -3), FreeCAD.Rotation())
        self.Doc.recompute()
        self.assertPlaneAt(inDocument(), self.bodyPlacement)


class TestTracedBinderAcrossBodies(unittest.TestCase):
    """A traced ShapeBinder (as Make dependent copy makes it, FreeCAD-CH ops#244) of the top face
    of a 20 x 10 x 10 box in a body turned 90 degrees about Z and moved by (5, 0, 0): globally
    the face is the plane z = 10, centred at (0, 10, 10). The binder's face stays there whichever
    container it is in, including after it enters or leaves one (PR 244 review H1, M1: a Group
    change touched nothing, so it kept the place it had in its old container, silently), and
    after one recompute when a body's Placement is driven by a spreadsheet (M2)."""

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestTracedBinder")
        self.Source = self.Doc.addObject("PartDesign::Body", "Source")
        self.Source.Placement = FreeCAD.Placement(
            FreeCAD.Vector(5, 0, 0), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)
        )
        self.Box = self.Source.newObject("PartDesign::AdditiveBox", "Box")
        self.Box.Length = 20
        self.Doc.recompute()
        [self.Top] = [
            f"Face{i}"
            for i, f in enumerate(self.Box.Shape.Faces, 1)
            if abs(f.CenterOfMass.z - 10) < 1e-9
        ]
        self.Target = self.placedBody("Target", (0, 3, 2), (1, 0, 0), 30)

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def placedBody(self, name, base, axis, angle):
        body = self.Doc.addObject("PartDesign::Body", name)
        body.Placement = FreeCAD.Placement(
            FreeCAD.Vector(*base), FreeCAD.Rotation(FreeCAD.Vector(*axis), angle)
        )
        return body

    def tracedBinder(self, container):
        binder = self.Doc.addObject("PartDesign::ShapeBinder", "Reference")
        binder.TraceSupport = True
        binder.Support = [(self.Box, self.Top)]
        if container:
            container.addObject(binder)
        return binder

    def assertWhereTheTopIs(self, binder, step):
        """After one recompute: nothing is left touched, and the binder's face is where the
        box's top face is, globally."""
        self.Doc.recompute()
        self.assertEqual([o.Name for o in self.Doc.Objects if "Touched" in o.State], [], step)
        self.assertTrue(binder.isValid(), binder.getStatusString())
        source = self.Box.Shape.getElement(self.Top)
        sourceCentre = self.Source.getGlobalPlacement().multVec(source.CenterOfMass)
        [face] = binder.Shape.Faces
        container = binder.getGlobalPlacement().multiply(binder.Placement.inverse())
        centre = container.multVec(face.CenterOfMass)
        self.assertLess((centre - sourceCentre).Length, 1e-6, f"{step}: {centre}")
        normal = container.Rotation.multVec(face.normalAt(0, 0))
        sourceNormal = self.Source.getGlobalPlacement().Rotation.multVec(source.normalAt(0, 0))
        self.assertAlmostEqual(abs(normal.dot(sourceNormal)), 1, places=9, msg=step)

    def testInABody(self):
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "made")
        sourceCentre = self.Source.getGlobalPlacement().multVec(
            self.Box.Shape.getElement(self.Top).CenterOfMass
        )
        self.assertLess((sourceCentre - FreeCAD.Vector(0, 10, 10)).Length, 1e-9)

    def testAddedToABodyAfterItsFirstRecompute(self):
        """H1: the Pipe panel recomputes its copy at the root, then adds it to the body."""
        binder = self.tracedBinder(None)
        self.assertWhereTheTopIs(binder, "at the root")
        self.Target.addObject(binder)
        self.assertWhereTheTopIs(binder, "added to the body")

    def testMovedToAnotherBody(self):
        """M1: moved as PartDesign_MoveFeature moves it (removeObjects, then addObjects), into a
        body placed otherwise, then out of any body."""
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "made")
        other = self.placedBody("Other", (-4, 1, 7), (0, 1, 1), 50)
        self.Target.removeObjects([binder])
        other.addObjects([binder])
        self.assertWhereTheTopIs(binder, "moved to another body")
        other.removeObjects([binder])
        self.assertIsNone(binder.getParentGeoFeatureGroup())
        self.assertWhereTheTopIs(binder, "moved to the root")

    def placedPart(self, *members):
        part = self.Doc.addObject("App::Part", "Part")
        part.Placement = FreeCAD.Placement(
            FreeCAD.Vector(2, -6, 3), FreeCAD.Rotation(FreeCAD.Vector(1, 2, 0), 40)
        )
        for member in members:
            part.addObject(member)
        return part

    def testTargetBodyOutOfAPlacedPart(self):
        """PR 244 verification 2(a): the binder's body is in a placed Part, then dragged out of it
        to the root: only the Part's Group changes."""
        part = self.placedPart(self.Target)
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "in the Part")
        part.removeObject(self.Target)
        self.assertIsNone(self.Target.getParentGeoFeatureGroup())
        self.assertWhereTheTopIs(binder, "out of the Part")

    def testSourceBodyIntoAPlacedPart(self):
        """PR 244 verification 2(b): the box's body is dragged into a placed Part, then out of it
        again: the box moves, and only the Part's Group changes."""
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "made")
        part = self.placedPart(self.Source)
        self.assertWhereTheTopIs(binder, "the box's body in the Part")
        part.removeObject(self.Source)
        self.assertWhereTheTopIs(binder, "the box's body out of the Part")

    def testInNestedPlacedParts(self):
        """PR 244 verification 2 (optional test): the binder's body in a placed Part inside
        another placed Part; the inner Part is dragged out of the outer one, then the body out of
        the inner one."""
        inner = self.placedPart(self.Target)
        outer = self.Doc.addObject("App::Part", "Outer")
        outer.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-3, 4, 1), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 70)
        )
        outer.addObject(inner)
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "in two Parts")
        outer.removeObject(inner)
        self.assertWhereTheTopIs(binder, "the inner Part out of the outer one")
        inner.removeObject(self.Target)
        self.assertWhereTheTopIs(binder, "the body out of the inner Part")

    def testGroupChangeAfterReopening(self):
        """PR 244 verification 2 (optional test, L1): saved and opened again, the binder has no
        frames from a recompute; its body is then put into a placed Part. It follows. (L1 itself,
        that the shape isn't built again on each Group change after the open, saves work only:
        this test passes without it, PR 246 review L8.)"""
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "made")
        path = os.path.join(tempfile.mkdtemp(), "traced.FCStd")
        self.Doc.saveAs(path)
        FreeCAD.closeDocument(self.Doc.Name)
        self.Doc = FreeCAD.openDocument(path)
        self.Source = self.Doc.getObject("Source")
        self.Target = self.Doc.getObject("Target")
        self.Box = self.Doc.getObject("Box")
        binder = self.Doc.getObject("Reference")
        self.assertWhereTheTopIs(binder, "opened")
        self.placedPart(self.Target)
        self.assertWhereTheTopIs(binder, "the body put into a Part")

    def testBinderOfAnotherBodysOriginPlane(self):
        """ops#244 L7: a traced binder of another body's XZ plane (as Make dependent copy makes
        it: Support set, then added to the body). Body::addObject relinked it to this body's own
        XZ plane, so it bound another plane, silently. It binds the other body's plane, where
        that one is: globally the plane y = 0 turned 90 degrees about Z, x = 5 along X."""
        [xz] = [f for f in self.Source.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        binder = self.Doc.addObject("PartDesign::ShapeBinder", "Reference")
        binder.Support = [(xz, "")]
        binder.TraceSupport = True
        self.Target.addObject(binder)
        self.assertEqual(binder.Support[0][0], xz)
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        [face] = binder.Shape.Faces
        container = self.Target.getGlobalPlacement()
        normal = container.Rotation.multVec(face.Surface.Axis)
        self.assertAlmostEqual(abs(normal.x), 1, places=9)
        self.assertAlmostEqual(container.multVec(face.Surface.Position).x, 5, places=9)

    def testBinderOfItsOwnBodysOriginPlaneMovedToAnotherBody(self):
        """PR 246 review L2: a traced binder of its own body's XZ plane, moved to another body as
        PartDesign_MoveFeature moves it (removeObjects, then addObjects), keeps binding that
        plane, where it is: globally the plane y = 0 turned 90 degrees about Z, x = 5 along X.
        It isn't relinked to the new body's plane, which would move it, silently."""
        [xz] = [f for f in self.Source.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        binder = self.Doc.addObject("PartDesign::ShapeBinder", "Reference")
        binder.Support = [(xz, "")]
        binder.TraceSupport = True
        self.Source.addObject(binder)
        self.Doc.recompute()
        self.Source.removeObjects([binder])
        self.Target.addObjects([binder])
        self.assertTrue(self.Target.hasObject(binder))
        self.assertEqual(binder.Support[0][0], xz)
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        [face] = binder.Shape.Faces
        container = self.Target.getGlobalPlacement()
        normal = container.Rotation.multVec(face.Surface.Axis)
        self.assertAlmostEqual(abs(normal.x), 1, places=9)
        self.assertAlmostEqual(container.multVec(face.Surface.Position).x, 5, places=9)

    def testBinderOfABodysOriginPlaneIntoAPlacedPart(self):
        """ops#273: a traced binder of a body's XZ plane put into a placed App::Part (a tree drag
        calls addObject). App::OriginGroupExtension::addObjects relinked it to the Part's own XZ
        plane, so it bound another plane, silently. It keeps binding the body's plane, where that
        one is: globally the plane y = 0 turned 90 degrees about Z, x = 5 along X."""
        [xz] = [f for f in self.Source.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        binder = self.Doc.addObject("PartDesign::ShapeBinder", "Reference")
        binder.Support = [(xz, "")]
        binder.TraceSupport = True
        self.Doc.recompute()
        part = self.Doc.addObject("App::Part", "Part")
        part.Placement = FreeCAD.Placement(
            FreeCAD.Vector(7, -2, 4), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 40)
        )
        part.addObject(binder)
        self.assertTrue(part.hasObject(binder))
        self.assertEqual(binder.Support[0][0], xz)
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        [face] = binder.Shape.Faces
        container = binder.getGlobalPlacement().multiply(binder.Placement.inverse())
        normal = container.Rotation.multVec(face.Surface.Axis)
        self.assertAlmostEqual(abs(normal.x), 1, places=9)
        self.assertAlmostEqual(container.multVec(face.Surface.Position).x, 5, places=9)

    def testUntracedLinksToABodysOriginPlaneIntoAPart(self):
        """ops#273, the relink kept: a binder that doesn't trace its support, and an attached Part
        plane, both on a body's XZ plane, put into an App::Part, are relinked to the Part's own XZ
        plane as before (they are placed in the container they're in)."""
        [xz] = [f for f in self.Source.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        binder = self.Doc.addObject("PartDesign::ShapeBinder", "Untraced")
        binder.Support = [(xz, "")]
        plane = self.Doc.addObject("Part::Plane", "Attached")
        plane.AttachmentSupport = [(xz, "")]
        plane.MapMode = "FlatFace"
        self.Doc.recompute()
        part = self.Doc.addObject("App::Part", "Part")
        part.addObjects([binder, plane])
        [partXZ] = [f for f in part.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        self.assertEqual(binder.Support[0][0], partXZ)
        self.assertEqual(plane.AttachmentSupport[0][0], partXZ)

    def testATraceSupportPropertyAloneKeepsTheRelink(self):
        """ops#282 (PR 252 review): a Python feature with its own true TraceSupport property and
        a link to a body's XZ plane, put into an App::Part, is relinked to the Part's own XZ plane
        like any other object. The skip went by the property alone, so it kept the body's plane,
        silently; it is for a shape binder that traces its support."""
        [xz] = [f for f in self.Source.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        feature = self.Doc.addObject("App::FeaturePython", "Traced")
        feature.addProperty("App::PropertyBool", "TraceSupport")
        feature.TraceSupport = True
        feature.addProperty("App::PropertyLinkSub", "Plane")
        feature.Plane = (xz, [])
        part = self.Doc.addObject("App::Part", "Part")
        part.addObject(feature)
        [partXZ] = [f for f in part.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        self.assertEqual(feature.Plane[0], partXZ)

    def testBinderOfAPartsOriginPlaneIntoAnotherPlacedPart(self):
        """ops#282 (PR 252 review): a traced binder in App::Part A (placed as Source: turned 90
        degrees about Z, moved by (5, 0, 0)) of A's XZ plane, put into a placed Part B (a tree
        drag calls addObject). It keeps binding A's plane, where that one is: globally the plane
        y = 0 turned 90 degrees about Z, x = 5 along X (as a body's, ops#273)."""
        partA = self.Doc.addObject("App::Part", "PartA")
        partA.Placement = self.Source.Placement
        [xz] = [f for f in partA.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        binder = self.Doc.addObject("PartDesign::ShapeBinder", "Reference")
        binder.Support = [(xz, "")]
        binder.TraceSupport = True
        partA.addObject(binder)
        self.Doc.recompute()
        partB = self.Doc.addObject("App::Part", "PartB")
        partB.Placement = FreeCAD.Placement(
            FreeCAD.Vector(7, -2, 4), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 40)
        )
        partB.addObject(binder)
        self.assertTrue(partB.hasObject(binder))
        self.assertFalse(partA.hasObject(binder))
        self.assertEqual(binder.Support[0][0], xz)
        self.Doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        [face] = binder.Shape.Faces
        container = binder.getGlobalPlacement().multiply(binder.Placement.inverse())
        self.assertTrue(container.isSame(partB.Placement, 1e-9), container)
        normal = container.Rotation.multVec(face.Surface.Axis)
        self.assertAlmostEqual(abs(normal.x), 1, places=9)
        self.assertAlmostEqual(container.multVec(face.Surface.Position).x, 5, places=9)

    def placementFromASheet(self, body):
        sheet = self.Doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "2")
        sheet.setAlias("A1", "Height")
        body.setExpression(".Placement.Base.z", "Sheet.Height")
        return sheet

    def testTargetBodyPlacedByASpreadsheet(self):
        """M2: the binder's body's height is a spreadsheet cell; the cell changes."""
        sheet = self.placementFromASheet(self.Target)
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "made")
        sheet.set("Height", "9")
        self.assertWhereTheTopIs(binder, "the cell changed")
        self.assertAlmostEqual(self.Target.Placement.Base.z, 9, places=9)

    def testSourceBodyPlacedByASpreadsheet(self):
        """M2: the box's body's height is a spreadsheet cell; the cell changes."""
        sheet = self.placementFromASheet(self.Source)
        binder = self.tracedBinder(self.Target)
        self.assertWhereTheTopIs(binder, "made")
        sheet.set("Height", "9")
        self.assertWhereTheTopIs(binder, "the cell changed")
        self.assertAlmostEqual(self.Source.Placement.Base.z, 9, places=9)


class TestShapeBinderOfACoordinateSystemInAPlacedBody(TestShapeBinderOfACoordinateSystem):
    """The same in a body moved and turned: the binder's shape is in the body."""

    bodyPlacement = FreeCAD.Placement(
        FreeCAD.Vector(5, -4, 9), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 0), 30)
    )
