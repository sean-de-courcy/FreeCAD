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

import FreeCAD

App = FreeCAD


class TestDatumPoint(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestDatumPoint")

    def testOriginDatumPoint(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.DatumPoint = self.Doc.addObject("PartDesign::Point", "DatumPoint")
        self.DatumPoint.AttachmentSupport = [(self.Doc.XY_Plane, "")]
        self.DatumPoint.MapMode = "ObjectOrigin"
        self.Body.addObject(self.DatumPoint)
        self.Doc.recompute()
        self.assertEqual(self.DatumPoint.AttachmentOffset.Base, App.Vector(0))

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestDatumPoint")
        # print ("omit closing document for debugging")


class TestDatumLine(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestDatumLine")

    def testXAxisDatumLine(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.DatumLine = self.Doc.addObject("PartDesign::Line", "DatumLine")
        self.DatumLine.AttachmentSupport = [(self.Doc.XY_Plane, "")]
        self.DatumLine.MapMode = "ObjectX"
        self.Body.addObject(self.DatumLine)
        self.Doc.recompute()
        self.assertNotIn("Invalid", self.DatumLine.State)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestDatumLine")
        # print ("omit closing document for debugging")


class TestDatumPlane(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestDatumPlane")

    def testXYDatumPlane(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.DatumPlane = self.Doc.addObject("PartDesign::Plane", "DatumPlane")
        self.DatumPlane.AttachmentSupport = [(self.Doc.XY_Plane, "")]
        self.DatumPlane.MapMode = "FlatFace"
        self.Body.addObject(self.DatumPlane)
        self.Doc.recompute()
        self.DatumPlaneNormal = self.DatumPlane.Shape.Surface.Axis
        self.assertEqual(abs(self.DatumPlaneNormal.dot(App.Vector(0, 0, 1))), 1)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestDatumPlane")
        # print ("omit closing document for debugging")


class TestAttachedToACoordinateSystem(unittest.TestCase):
    """Datums and a sketch attached to an element of a coordinate system, linked bare, as
    (element, ""): placed in the coordinate system (FreeCAD-CH ops#200). The coordinate system
    sits in the body at (3, 4, 5), turned 90 degrees about X: its XY plane faces -Y, its origin
    is (3, 4, 5). The (coordinate system, "XY_Plane") link always gave that; the bare link gave
    the element's own placement in the coordinate system, at the body's origin."""

    bodyPlacement = FreeCAD.Placement()
    lcsPlacement = FreeCAD.Placement(
        FreeCAD.Vector(3, 4, 5), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
    )

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestAttachedToLCS")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Body.Placement = self.bodyPlacement
        self.Lcs = self.Doc.addObject("Part::LocalCoordinateSystem", "LCS")
        self.Body.addObject(self.Lcs)
        self.Lcs.Placement = self.lcsPlacement
        self.Doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def element(self, role):
        [feature] = [f for f in self.Lcs.OriginFeatures if f.Role == role]
        return feature

    def attach(self, typeName, support, mode):
        feature = self.Body.newObject(typeName, "Attached")
        feature.AttachmentSupport = support
        feature.MapMode = mode
        self.Doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        return feature

    def assertPlacement(self, placement, expected):
        self.assertTrue(placement.isSame(expected, 1e-9), "%s != %s" % (placement, expected))

    def testPlaneFlatFace(self):
        plane = self.attach("PartDesign::Plane", [(self.element("XY_Plane"), "")], "FlatFace")
        self.assertPlacement(plane.Placement, self.lcsPlacement)

    def testPlaneObjectXY(self):
        plane = self.attach("PartDesign::Plane", [(self.element("XY_Plane"), "")], "ObjectXY")
        self.assertPlacement(plane.Placement, self.lcsPlacement)

    def testPlaneMidPoint(self):
        plane = self.attach("PartDesign::Plane", [(self.element("XY_Plane"), "")], "MidPoint")
        self.assertPlacement(plane.Placement, self.lcsPlacement)

    def testSketchFlatFace(self):
        """As the link through the coordinate system gives it."""
        sketch = self.attach(
            "Sketcher::SketchObject", [(self.element("XY_Plane"), "")], "FlatFace"
        )
        reference = self.attach(
            "Sketcher::SketchObject", [(self.Lcs, self.element("XY_Plane").Name)], "FlatFace"
        )
        self.assertPlacement(reference.Placement, self.lcsPlacement)
        self.assertPlacement(sketch.Placement, self.lcsPlacement)

    def testPointOnTheOrigin(self):
        point = self.attach("PartDesign::Point", [(self.element("Origin"), "")], "Vertex")
        self.assertLess(point.Placement.Base.distanceToPoint(FreeCAD.Vector(3, 4, 5)), 1e-9)

    def testMirroredOnAMovedElement(self):
        """The coordinate system's XY plane moved 1 along its own Z (in the coordinate system):
        in the body that is 1 along -Y, so the plane is y = 3. A 2 x 3 x 2 box at the body's
        origin mirrored on it reaches y = 6. Adding the move without turning it gave y = 4, and
        y = 8 (PR 175 review, Low 6: DatumElement::getBasePoint)."""
        plane = self.element("XY_Plane")
        plane.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 1), FreeCAD.Rotation())
        box = self.Body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Height = 2
        box.Width = 3
        self.Doc.recompute()
        # As TestMirrored makes it: added to the body once its originals are set
        mirrored = self.Doc.addObject("PartDesign::Mirrored", "Mirrored")
        mirrored.Originals = [box]
        mirrored.MirrorPlane = (plane, [""])
        self.Body.addObject(mirrored)
        self.Doc.recompute()
        self.assertTrue(mirrored.isValid(), mirrored.getStatusString())
        self.assertAlmostEqual(mirrored.Shape.BoundBox.YMax, 6, places=6)

    def testBodyOriginPlane(self):
        """Unchanged: the body's own XY plane, at the body's origin."""
        [xy] = [f for f in self.Body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        plane = self.attach("PartDesign::Plane", [(xy, "")], "FlatFace")
        self.assertPlacement(plane.Placement, FreeCAD.Placement())

    def testOriginPlacedFromPython(self):
        """The body's Origin is at identity unless its read-only Placement is set from Python:
        then its planes follow it alike for the Attacher and a Mirrored. Lifted 2, the XY plane
        is z = 2 and a 2 x 3 x 2 box mirrored on it reaches z = 4. The Mirrored took the
        Origin's plane at z = 0 (PR 177 review, Low 1: DatumElement::getBasePoint)."""
        origin = self.Body.Origin
        origin.setPropertyStatus("Placement", "-ReadOnly")
        origin.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 2), FreeCAD.Rotation())
        [xy] = [f for f in origin.OriginFeatures if f.Role == "XY_Plane"]
        plane = self.attach("PartDesign::Plane", [(xy, "")], "FlatFace")
        self.assertPlacement(plane.Placement, origin.Placement)
        box = self.Body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Height = 2
        box.Width = 3
        self.Doc.recompute()
        mirrored = self.Doc.addObject("PartDesign::Mirrored", "Mirrored")
        mirrored.Originals = [box]
        mirrored.MirrorPlane = (xy, [""])
        self.Body.addObject(mirrored)
        self.Doc.recompute()
        self.assertTrue(mirrored.isValid(), mirrored.getStatusString())
        self.assertAlmostEqual(mirrored.Shape.BoundBox.ZMin, 0, places=6)
        self.assertAlmostEqual(mirrored.Shape.BoundBox.ZMax, 4, places=6)

    def testLineIntersection(self):
        """A datum line on the coordinate system's XY and XZ planes (IntersectionLine): its X
        axis, through its origin. The line engine puts the line's base at the foot of the
        reference's origin on it, which is (3, 4, 5) taken in the coordinate system and
        (0, 4, 5) taken as the element's own (PR 177 review, Low 2: AttachEngineLine)."""
        line = self.attach(
            "PartDesign::Line",
            [(self.element("XY_Plane"), ""), (self.element("XZ_Plane"), "")],
            "IntersectionLine",
        )
        direction = line.Placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
        self.assertLess(direction.cross(FreeCAD.Vector(1, 0, 0)).Length, 1e-9)
        self.assertLess(line.Placement.Base.distanceToPoint(FreeCAD.Vector(3, 4, 5)), 1e-9)

    # The coordinate system moved after the attachment: whatever links its elements bare follows
    # it at the next recompute (FreeCAD-CH ops#206). Nothing else touched them: their links name
    # the elements, which the move leaves unchanged.
    movedPlacement = FreeCAD.Placement(
        FreeCAD.Vector(-2, 6, 1), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)
    )

    def testPlaneFollowsTheMove(self):
        plane = self.attach("PartDesign::Plane", [(self.element("XY_Plane"), "")], "FlatFace")
        self.Lcs.Placement = self.movedPlacement
        self.Doc.recompute()
        self.assertPlacement(plane.Placement, self.movedPlacement)

    def testSketchFollowsTheMove(self):
        sketch = self.attach(
            "Sketcher::SketchObject", [(self.element("XY_Plane"), "")], "FlatFace"
        )
        self.Lcs.Placement = self.movedPlacement
        self.Doc.recompute()
        self.assertPlacement(sketch.Placement, self.movedPlacement)

    def testMirroredFollowsTheMove(self):
        """A 2 x 3 x 2 box at the body's origin, mirrored on the coordinate system's XZ plane:
        at (3, 4, 5) turned about X that is the plane z = 5, so the mirror reaches z = 10. Moved
        to (-2, 6, 1) turned about Z, the plane is x = -2, and the mirror reaches x = -6."""
        box = self.Body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Height = 2
        box.Width = 3
        self.Doc.recompute()
        mirrored = self.Doc.addObject("PartDesign::Mirrored", "Mirrored")
        mirrored.Originals = [box]
        mirrored.MirrorPlane = (self.element("XZ_Plane"), [""])
        self.Body.addObject(mirrored)
        self.Doc.recompute()
        self.assertTrue(mirrored.isValid(), mirrored.getStatusString())
        self.assertAlmostEqual(mirrored.Shape.BoundBox.ZMax, 10, places=6)
        self.Lcs.Placement = self.movedPlacement
        self.Doc.recompute()
        self.assertTrue(mirrored.isValid(), mirrored.getStatusString())
        self.assertAlmostEqual(mirrored.Shape.BoundBox.XMin, -6, places=6)
        self.assertAlmostEqual(mirrored.Shape.BoundBox.ZMax, 2, places=6)

    def testUndoOfTheMove(self):
        self.Doc.UndoMode = 1
        plane = self.attach("PartDesign::Plane", [(self.element("XY_Plane"), "")], "FlatFace")
        self.Doc.openTransaction("Move")
        self.Lcs.Placement = self.movedPlacement
        self.Doc.commitTransaction()
        self.Doc.recompute()
        self.assertPlacement(plane.Placement, self.movedPlacement)
        self.Doc.undo()
        self.Doc.recompute()
        self.assertPlacement(plane.Placement, self.lcsPlacement)
        self.Doc.redo()
        self.Doc.recompute()
        self.assertPlacement(plane.Placement, self.movedPlacement)

    def testCoordinateSystemOnAnAttachedOne(self):
        """A second coordinate system attached bare to the XY plane of a first that is itself
        attached (to the body's XY plane, offset to (3, 4, 5) turned about X). Nothing orders
        the second after the first; after the first's offset changes, a recompute must still
        leave the second on it."""
        [xy] = [f for f in self.Body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        first = self.Body.newObject("Part::LocalCoordinateSystem", "First")
        first.AttachmentSupport = [(xy, "")]
        first.MapMode = "FlatFace"
        first.AttachmentOffset = self.lcsPlacement
        self.Doc.recompute()
        [firstXY] = [f for f in first.OriginFeatures if f.Role == "XY_Plane"]
        second = self.attach("Part::LocalCoordinateSystem", [(firstXY, "")], "FlatFace")
        self.assertPlacement(second.Placement, self.lcsPlacement)
        first.AttachmentOffset = self.movedPlacement
        self.Doc.recompute()
        self.assertPlacement(first.Placement, self.movedPlacement)
        self.assertPlacement(second.Placement, self.movedPlacement)
        self.assertNotIn("Touched", second.State)


class TestAttachedToACoordinateSystemInAPlacedBody(TestAttachedToACoordinateSystem):
    """The same in a body moved and turned: the attached placements are in the body."""

    bodyPlacement = FreeCAD.Placement(
        FreeCAD.Vector(5, -4, 9), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 0), 30)
    )
