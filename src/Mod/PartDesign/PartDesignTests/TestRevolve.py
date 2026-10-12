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

import math
import unittest

import FreeCAD
import Part
import Sketcher
from PartDesignTests.Scenarios import harness


class TestRevolve(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestRevolve")

    def testRevolveFace(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.Revolution = self.Doc.addObject("PartDesign::Revolution", "Revolution")
        self.Revolution.Profile = (self.Box, ["Face6"])
        self.Revolution.ReferenceAxis = (self.Doc.Y_Axis, [""])
        self.Revolution.Angle = 180.0
        self.Revolution.Reversed = 1
        self.Body.addObject(self.Revolution)
        self.Doc.recompute()
        # depending on if refinement is done we expect 8 or 10 faces
        self.assertIn(len(self.Revolution.Shape.Faces), (8, 10))

    def testGrooveFace(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.Groove = self.Doc.addObject("PartDesign::Groove", "Groove")
        self.Groove.Profile = (self.Box, ["Face6"])
        self.Groove.ReferenceAxis = (self.Doc.X_Axis, [""])
        self.Groove.Angle = 180.0
        self.Groove.Reversed = 1
        self.Body.addObject(self.Groove)
        self.Doc.recompute()
        self.assertEqual(len(self.Groove.Shape.Faces), 5)

    def testRevolutionStartOffsetAndReference(self):
        profile = self.Doc.addObject("Sketcher::SketchObject", "Profile")
        points = [
            FreeCAD.Vector(2, 0),
            FreeCAD.Vector(3, 0),
            FreeCAD.Vector(3, 1),
            FreeCAD.Vector(2, 1),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            profile.addGeometry(Part.LineSegment(start, end), False)

        axis = self.Doc.addObject("Part::Feature", "Axis")
        axis.Shape = Part.makeLine(FreeCAD.Vector(0, -1, 0), FreeCAD.Vector(0, 2, 0))

        revolution = self.Doc.addObject("PartDesign::Revolution", "OffsetRevolution")
        revolution.Profile = profile
        revolution.ReferenceAxis = (axis, ["Edge1"])
        revolution.Angle = 30
        revolution.StartType = "Offset"
        revolution.StartOffset = 105
        self.Doc.recompute()

        direct_bounds = revolution.AddSubShape.BoundBox
        direct_values = (
            direct_bounds.XMin,
            direct_bounds.XMax,
            direct_bounds.YMin,
            direct_bounds.YMax,
            direct_bounds.ZMin,
            direct_bounds.ZMax,
        )
        self.assertLess(direct_bounds.XMax, -0.5)
        self.assertLess(direct_bounds.ZMax, -1.4)

        reference = self.Doc.addObject("Part::Feature", "StartReference")
        reference.Shape = Part.Face(
            Part.makePolygon(
                [
                    FreeCAD.Vector(0, -1, -1),
                    FreeCAD.Vector(0, 2, -1),
                    FreeCAD.Vector(0, 2, -4),
                    FreeCAD.Vector(0, -1, -4),
                    FreeCAD.Vector(0, -1, -1),
                ]
            )
        )
        revolution.StartReference = (reference, ["Face1"])
        revolution.StartType = "Reference"
        revolution.StartOffset = 15
        self.Doc.recompute()

        reference_bounds = revolution.AddSubShape.BoundBox
        reference_values = (
            reference_bounds.XMin,
            reference_bounds.XMax,
            reference_bounds.YMin,
            reference_bounds.YMax,
            reference_bounds.ZMin,
            reference_bounds.ZMax,
        )
        for actual, expected in zip(reference_values, direct_values):
            self.assertAlmostEqual(actual, expected)

    def revolveUpToWall(
        self,
        sideType,
        core,
        kind="Revolution",
        reversed=False,
        offset=0,
        wall="datum",
        scale=1,
        wallHeight=0,
        valid=True,
    ):
        """A Revolution or Groove up to a wall, as the body's first solid or after a core cylinder
        (ops#191, ops#239). The profile is the rectangle x in [1, 3] * scale + offset,
        z in [0, 2] * scale on XZ (area 4 * scale^2, centroid 2 * scale from the axis), revolved
        about the vertical line x = offset, y = 0: the sketch's V axis when offset is 0, else a
        datum line. The wall is the plane x = offset, a quarter turn away on either side: a datum
        plane with its origin at z = wallHeight, or (wall="binder" or "part") the bounded face
        y in [0.5, 4], z in [-1, 3] of a Part::Plane outside the body, through a ShapeBinder or
        linked directly. The bounded face lies on the y > 0 side only: a face that the sweep
        crosses on both sides gives the region between the two crossings instead (the based path
        does that too)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        if core:
            cylinder = body.newObject("PartDesign::AdditiveCylinder", "Core")
            cylinder.Radius = scale
            cylinder.Height = 2 * scale
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        points = [
            FreeCAD.Vector(1 * scale + offset, 0),
            FreeCAD.Vector(3 * scale + offset, 0),
            FreeCAD.Vector(3 * scale + offset, 2 * scale),
            FreeCAD.Vector(1 * scale + offset, 2 * scale),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        wallPlacement = FreeCAD.Placement(
            FreeCAD.Vector(offset, 0, wallHeight), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90)
        )
        if wall == "datum":
            wallObject = body.newObject("PartDesign::Plane", "Wall")
            wallObject.MapMode = "Deactivated"
            wallObject.Placement = wallPlacement
            upToFace = (wallObject, [""])
        else:
            # The plane's length runs along its local X, which the rotation turns to -Z.
            plane = self.Doc.addObject("Part::Plane", "WallFace")
            plane.Length = 4
            plane.Width = 3.5
            plane.Placement = FreeCAD.Placement(
                FreeCAD.Vector(offset, 0.5, 3), wallPlacement.Rotation
            )
            if wall == "binder":
                binder = body.newObject("PartDesign::ShapeBinder", "Wall")
                binder.Support = [(plane, ["Face1"])]
                upToFace = (binder, ["Face1"])
            else:
                upToFace = (plane, ["Face1"])
        revolution = body.newObject("PartDesign::" + kind, kind)
        revolution.Profile = sketch
        if offset:
            axis = body.newObject("PartDesign::Line", "Axis")
            axis.MapMode = "Deactivated"
            axis.Placement = FreeCAD.Placement(FreeCAD.Vector(offset, 0, 0), FreeCAD.Rotation())
            revolution.ReferenceAxis = (axis, [""])
        else:
            revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.Reversed = reversed
        revolution.SideType = sideType
        revolution.Type = "UpToFace"
        revolution.UpToFace = upToFace
        if sideType == "Two sides":
            revolution.Type2 = "UpToFace"
            revolution.UpToFace2 = upToFace
        self.Doc.recompute()
        if not valid:
            return revolution
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)
        return revolution

    def assertQuarter(self, shape, positiveY, offset=0, scale=1):
        """One quarter of the ring: x from offset to offset + 3 * scale and z in [0, 2] * scale on
        the given side of the profile plane y = 0. The axis runs along +Z, so a positive turn
        carries +X to +Y; Reversed turns the other way."""
        bounds = shape.BoundBox
        self.assertAlmostEqual(bounds.XMin, offset, places=6)
        self.assertAlmostEqual(bounds.XMax, offset + 3 * scale, places=6)
        self.assertAlmostEqual(bounds.ZMin, 0, places=6)
        self.assertAlmostEqual(bounds.ZMax, 2 * scale, places=6)
        if positiveY:
            self.assertAlmostEqual(bounds.YMin, 0, places=6)
            self.assertAlmostEqual(bounds.YMax, 3 * scale, places=6)
        else:
            self.assertAlmostEqual(bounds.YMin, -3 * scale, places=6)
            self.assertAlmostEqual(bounds.YMax, 0, places=6)

    # Pappus: a full turn of the profile sweeps 2 pi * 2 * 4 = 16 pi, so a quarter turn 4 pi and
    # a half turn 8 pi. The core cylinder adds pi * 1^2 * 2 = 2 pi.

    def testRevolutionUpToFaceFirstSolid(self):
        revolution = self.revolveUpToWall("One side", core=False)
        self.assertAlmostEqual(revolution.Shape.Volume, 4 * math.pi, places=6)
        bounds = revolution.Shape.BoundBox
        self.assertAlmostEqual(bounds.XMin, 0, places=6)
        self.assertAlmostEqual(bounds.ZMax, 2, places=6)

    def testRevolutionUpToFaceTwoSidesFirstSolid(self):
        revolution = self.revolveUpToWall("Two sides", core=False)
        self.assertAlmostEqual(revolution.Shape.Volume, 8 * math.pi, places=6)
        bounds = revolution.Shape.BoundBox
        self.assertAlmostEqual(bounds.XMin, 0, places=6)
        self.assertAlmostEqual(bounds.ZMax, 2, places=6)

    def testRevolutionUpToFaceSymmetricFirstSolid(self):
        revolution = self.revolveUpToWall("Symmetric", core=False)
        self.assertAlmostEqual(revolution.Shape.Volume, 8 * math.pi, places=6)

    def testRevolutionUpToFaceAfterCore(self):
        revolution = self.revolveUpToWall("One side", core=True)
        self.assertAlmostEqual(revolution.Shape.Volume, 6 * math.pi, places=6)

    def testRevolutionUpToFaceTwoSidesAfterCore(self):
        revolution = self.revolveUpToWall("Two sides", core=True)
        self.assertAlmostEqual(revolution.Shape.Volume, 10 * math.pi, places=6)

    def testRevolutionUpToFaceFirstSolidSide(self):
        revolution = self.revolveUpToWall("One side", core=False)
        self.assertQuarter(revolution.Shape, positiveY=True)

    def testRevolutionUpToFaceFirstSolidReversed(self):
        revolution = self.revolveUpToWall("One side", core=False, reversed=True)
        self.assertAlmostEqual(revolution.Shape.Volume, 4 * math.pi, places=6)
        self.assertQuarter(revolution.Shape, positiveY=False)

    def testRevolutionUpToFaceFirstSolidOffAxis(self):
        """The axis is the line x = 5: the box beyond the sweep follows the axis, not the origin."""
        revolution = self.revolveUpToWall("One side", core=False, offset=5)
        self.assertAlmostEqual(revolution.Shape.Volume, 4 * math.pi, places=6)
        self.assertQuarter(revolution.Shape, positiveY=True, offset=5)

    def testRevolutionUpToFaceFirstSolidOffAxisReversed(self):
        revolution = self.revolveUpToWall("One side", core=False, reversed=True, offset=5)
        self.assertAlmostEqual(revolution.Shape.Volume, 4 * math.pi, places=6)
        self.assertQuarter(revolution.Shape, positiveY=False, offset=5)

    def testRevolutionUpToBinderFaceFirstSolid(self):
        """A bounded face goes to BRepFeat itself, with the box as its base."""
        revolution = self.revolveUpToWall("One side", core=False, wall="binder")
        self.assertAlmostEqual(revolution.Shape.Volume, 4 * math.pi, places=6)
        self.assertQuarter(revolution.Shape, positiveY=True)

    def testRevolutionUpToPartFaceFirstSolid(self):
        revolution = self.revolveUpToWall("One side", core=False, wall="part")
        self.assertAlmostEqual(revolution.Shape.Volume, 4 * math.pi, places=6)
        self.assertQuarter(revolution.Shape, positiveY=True)

    def testRevolutionUpToBinderFaceAfterCore(self):
        revolution = self.revolveUpToWall("One side", core=True, wall="binder")
        self.assertAlmostEqual(revolution.Shape.Volume, 6 * math.pi, places=6)

    def testGrooveUpToFaceFirstSolid(self):
        """A Groove with nothing to cut fails and says so, as every subtractive feature does
        (ops#308 F8). It gave its tool as the body's first solid (ops#239), which put material
        where a cut was asked for."""
        groove = self.revolveUpToWall("One side", core=False, kind="Groove", valid=False)
        self.assertFalse(groove.isValid())
        self.assertIn("Nothing to cut", groove.getStatusString())

    # Scaled by 10 (ops#239): a full turn sweeps 2 pi * 20 * 400 = 16000 pi, a quarter 4000 pi.
    # Without a base, BRepFeat trims the unbounded wall to a square set by the box it gets as its
    # base; a small box near the axis made the square miss the sweep: from about 2.5 a nearly
    # full ring for a quarter (Reversed, the second side), from about 3 a loud failure.

    def testRevolutionUpToFaceFirstSolidScaled(self):
        revolution = self.revolveUpToWall("One side", core=False, scale=10)
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 4000, places=4)
        self.assertQuarter(revolution.Shape, positiveY=True, scale=10)

    def testRevolutionUpToFaceFirstSolidScaledReversed(self):
        revolution = self.revolveUpToWall("One side", core=False, reversed=True, scale=10)
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 4000, places=4)
        self.assertQuarter(revolution.Shape, positiveY=False, scale=10)

    def testRevolutionUpToFaceFirstSolidSmallReversed(self):
        """At 2.5 the old box gave a nearly full ring (15.87 pi * 2.5^3) without an error."""
        revolution = self.revolveUpToWall("One side", core=False, reversed=True, scale=2.5)
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 4 * 2.5**3, places=6)
        self.assertQuarter(revolution.Shape, positiveY=False, scale=2.5)

    def testRevolutionUpToFaceTwoSidesFirstSolidScaled(self):
        revolution = self.revolveUpToWall("Two sides", core=False, scale=10)
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 8000, places=4)
        self.assertAlmostEqual(revolution.Shape.BoundBox.XMin, 0, places=6)

    def testRevolutionUpToFaceSymmetricFirstSolidScaled(self):
        revolution = self.revolveUpToWall("Symmetric", core=False, scale=10)
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 8000, places=4)
        self.assertAlmostEqual(revolution.Shape.BoundBox.XMin, 0, places=6)

    def testRevolutionUpToFaceFirstSolidFarWallOrigin(self):
        """The wall's origin 100000 above the profile does not matter. (Probed with and without
        the wall origin in the box's size, ops#239: OCCT's trim of the wall doesn't sit around
        the wall's origin, so the term is only a margin.)"""
        revolution = self.revolveUpToWall(
            "One side", core=False, reversed=True, scale=10, wallHeight=100000
        )
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 4000, places=4)
        self.assertQuarter(revolution.Shape, positiveY=False, scale=10)

    def testRevolutionUpToFaceScaledAfterCore(self):
        """With a base there is no box: the core cylinder (radius 10, height 20, 2000 pi) plus the
        quarter."""
        revolution = self.revolveUpToWall("One side", core=True, reversed=True, scale=10)
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 6000, places=4)

    def testRevolutionUpToFaceNegativeAxis(self):
        """A datum line along -X: the profile x in [0, 20], z in [10, 30] on XZ (area 400, centroid
        20 from the axis), up to the XY plane. A positive turn about -X carries +Z to +Y."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        points = [
            FreeCAD.Vector(0, 10),
            FreeCAD.Vector(20, 10),
            FreeCAD.Vector(20, 30),
            FreeCAD.Vector(0, 30),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        axis = body.newObject("PartDesign::Line", "Axis")
        axis.MapMode = "Deactivated"
        axis.Placement = FreeCAD.Placement(
            FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), -90)
        )
        [xy] = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (axis, [""])
        revolution.Type = "UpToFace"
        revolution.UpToFace = (xy, [""])
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 4000, places=4)
        bounds = revolution.Shape.BoundBox
        self.assertAlmostEqual(bounds.XMin, 0, places=6)
        self.assertAlmostEqual(bounds.XMax, 20, places=6)
        self.assertAlmostEqual(bounds.YMin, 0, places=6)
        self.assertAlmostEqual(bounds.YMax, 30, places=6)
        self.assertAlmostEqual(bounds.ZMin, 0, places=6)
        self.assertAlmostEqual(bounds.ZMax, 30, places=6)

    def testRevolutionUpToInfiniteCylinderFirstSolid(self):
        """The up-to face is a whole cylinder surface (unbounded along its axis): radius 100, its
        axis parallel to Z through (100, 0), so it passes through the revolution axis. The profile
        x in [1, 3], z in [0, 2] on XZ about Z: the point at radius r meets it after the angle
        acos(r / 200), and the volume is 2 * the integral of r * acos(r / 200) from 1 to 3. Its
        bounding box (about 1e100) must not size the box BRepFeat gets without a base."""
        cylinder = Part.Cylinder()
        cylinder.Radius = 100
        cylinder.Center = FreeCAD.Vector(100, 0, 0)
        wall = self.Doc.addObject("Part::Feature", "WallFace")
        wall.Shape = Part.Face(cylinder)
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        points = [
            FreeCAD.Vector(1, 0),
            FreeCAD.Vector(3, 0),
            FreeCAD.Vector(3, 2),
            FreeCAD.Vector(1, 2),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.Type = "UpToFace"
        revolution.UpToFace = (wall, ["Face1"])
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)

        k = 200

        def antiderivative(r):
            # integral of r * acos(r / k) dr
            return (
                r**2 / 2 * math.acos(r / k)
                + k**2 / 4 * math.asin(r / k)
                - r / 4 * math.sqrt(k**2 - r**2)
            )

        expected = 2 * (antiderivative(3) - antiderivative(1))
        self.assertAlmostEqual(revolution.Shape.Volume, expected, places=6)
        self.assertAlmostEqual(revolution.Shape.BoundBox.YMin, 0, places=6)

    def revolveAroundSmallCore(self, sideType, reversed=False, kind="Revolution"):
        """A Revolution up to the YZ origin plane after a small core (ops#242): the cylinder of
        radius 1 and height 2 at the origin, and the profile x in [0, 50], z in [0, 50] on XZ
        about Z (area 2500, centroid 25 from the axis: a full turn is 125000 pi). BRepFeat trims
        the unbounded plane by the size of the base it gets; the core alone made that square
        about 20 across, and a quarter came out as a nearly full ring without an error."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        core = body.newObject("PartDesign::AdditiveCylinder", "Core")
        core.Radius = 1
        core.Height = 2
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        points = [
            FreeCAD.Vector(0, 0),
            FreeCAD.Vector(50, 0),
            FreeCAD.Vector(50, 50),
            FreeCAD.Vector(0, 50),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        [yz] = [f for f in body.Origin.OriginFeatures if f.Role == "YZ_Plane"]
        revolution = body.newObject("PartDesign::" + kind, kind)
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.Reversed = reversed
        revolution.SideType = sideType
        revolution.Type = "UpToFace"
        revolution.UpToFace = (yz, [""])
        if sideType == "Two sides":
            revolution.Type2 = "UpToFace"
            revolution.UpToFace2 = (yz, [""])
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)
        return revolution

    # A quarter is 125000 pi / 4 = 31250 pi; the core's part outside it adds 3/4 * 2 pi = 1.5 pi.
    # A half is 62500 pi, and the core's other half adds pi.

    @staticmethod
    def exactBounds(shape):
        """The shape's bounding box from its geometry (ops#259). Shape.BoundBox reads the
        triangulation when the shape has one: in the GUI process the view providers mesh the
        shapes, and the core's extreme at x = -1 then read -0.9966 (a mesh node inside the
        circle)."""
        return shape.optimalBoundingBox(False, False)

    def testRevolutionUpToFaceAroundSmallCore(self):
        revolution = self.revolveAroundSmallCore("One side")
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 31251.5, places=3)
        bounds = self.exactBounds(revolution.Shape)
        self.assertAlmostEqual(bounds.XMin, -1, places=6)
        self.assertAlmostEqual(bounds.YMin, -1, places=6)
        self.assertAlmostEqual(bounds.YMax, 50, places=6)

    def testRevolutionUpToFaceAroundSmallCoreReversed(self):
        revolution = self.revolveAroundSmallCore("One side", reversed=True)
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 31251.5, places=3)
        bounds = self.exactBounds(revolution.Shape)
        self.assertAlmostEqual(bounds.YMin, -50, places=6)
        self.assertAlmostEqual(bounds.YMax, 1, places=6)

    def testRevolutionUpToFaceTwoSidesAroundSmallCore(self):
        revolution = self.revolveAroundSmallCore("Two sides")
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 62501, places=3)
        self.assertAlmostEqual(self.exactBounds(revolution.Shape).XMin, -1, places=6)

    def testRevolutionUpToFaceSymmetricAroundSmallCore(self):
        revolution = self.revolveAroundSmallCore("Symmetric")
        self.assertAlmostEqual(revolution.Shape.Volume / math.pi, 62501, places=3)
        self.assertAlmostEqual(self.exactBounds(revolution.Shape).XMin, -1, places=6)

    def testGrooveUpToFaceAroundSmallCore(self):
        """The same quarter as a Groove: it removes a quarter of the core, leaving 3/4 * 2 pi."""
        groove = self.revolveAroundSmallCore("One side", kind="Groove")
        self.assertAlmostEqual(groove.Shape.Volume / math.pi, 1.5, places=6)
        bounds = self.exactBounds(groove.Shape)
        self.assertAlmostEqual(bounds.XMin, -1, places=6)
        self.assertAlmostEqual(bounds.YMin, -1, places=6)
        self.assertAlmostEqual(bounds.YMax, 1, places=6)

    def revolveUpToBaseFace(self, upToFirst):
        """A bounded up-to face that belongs to the base: the box x in [-4, 0], y in [0, 4],
        z in [0, 2], and the profile x in [1, 3], z in [0, 2] on XZ about Z, whose quarter ends
        on the box's face x = 0. Up to that face, or Up to first. The box isn't trimmed by
        BRepFeat, so the far box isn't added (ops#242): 32 plus the quarter, 4 pi."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 4
        block.Height = 2
        block.Placement = FreeCAD.Placement(FreeCAD.Vector(-4, 0, 0), FreeCAD.Rotation())
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        points = [
            FreeCAD.Vector(1, 0),
            FreeCAD.Vector(3, 0),
            FreeCAD.Vector(3, 2),
            FreeCAD.Vector(1, 2),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        self.Doc.recompute()
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(block.Shape.Faces)
            if abs(face.BoundBox.XMin) < 1e-9 and abs(face.BoundBox.XMax) < 1e-9
        ]
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        if upToFirst:
            revolution.Type = "UpToFirst"
        else:
            revolution.Type = "UpToFace"
            revolution.UpToFace = (block, [wall])
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)
        self.assertAlmostEqual(revolution.Shape.Volume, 32 + 4 * math.pi, places=6)
        bounds = revolution.Shape.BoundBox
        self.assertAlmostEqual(bounds.XMin, -4, places=6)
        self.assertAlmostEqual(bounds.XMax, 3, places=6)
        self.assertAlmostEqual(bounds.YMin, 0, places=6)
        self.assertAlmostEqual(bounds.YMax, 4, places=6)

    def testRevolutionUpToBaseFace(self):
        self.revolveUpToBaseFace(upToFirst=False)

    def testRevolutionUpToFirstBaseFace(self):
        self.revolveUpToBaseFace(upToFirst=True)

    def revolveTwoFaces(self, kind, sideType="One side", upToType="UpToFace"):
        """A profile of two separate rectangles, x in [1, 2] and [3, 4], z in [0, 2] on XZ about Z,
        up to the face x = 0 of a box (x in [-6, 0] for a Revolution, [0, 6] for a Groove,
        y in [-6, 6], z in [0, 3]: 216), or up to the first face. Each face is revolved on its own
        up to its face and the tools are fused (ops#263): a quarter ring per face, 5 pi in all, or
        a half ring per face for Symmetric, 10 pi, or for Two sides with both sides up to the box's
        face (or up to the first face), which reaches across the profile plane. Refine is off:
        each ring's two cylinders are faces of their own (two per side for Symmetric and Two
        sides), named from the profile's lines, and no two elements share a name."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 6
        block.Width = 12
        block.Height = 3
        x0 = -6 if kind == "Revolution" else 0
        block.Placement = FreeCAD.Placement(FreeCAD.Vector(x0, -6, 0), FreeCAD.Rotation())
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        for x0, x1 in ((1, 2), (3, 4)):
            points = [
                FreeCAD.Vector(x0, 0),
                FreeCAD.Vector(x1, 0),
                FreeCAD.Vector(x1, 2),
                FreeCAD.Vector(x0, 2),
            ]
            for start, end in zip(points, points[1:] + points[:1]):
                sketch.addGeometry(Part.LineSegment(start, end), False)
        self.Doc.recompute()
        revolution = body.newObject("PartDesign::" + kind, kind)
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.Refine = False
        revolution.SideType = sideType
        revolution.Type = upToType
        if upToType == "UpToFace":
            revolution.UpToFace = (block, [self.wallAtXZero(block)])
        if sideType == "Two sides":
            revolution.Type2 = upToType
            if upToType == "UpToFace":
                revolution.UpToFace2 = (block, [self.wallAtXZero(block)])
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)

        sides = 1 if sideType == "One side" else 2
        rings = sides * math.pi / 4 * ((2**2 - 1**2) + (4**2 - 3**2)) * 2
        if kind == "Revolution":
            self.assertAlmostEqual(revolution.Shape.Volume, 216 + rings, places=6)
            tool = revolution.Shape.cut(block.Shape)
        else:
            self.assertAlmostEqual(revolution.Shape.Volume, 216 - rings, places=6)
            tool = block.Shape.cut(revolution.Shape)
        self.assertAlmostEqual(tool.Volume, rings, places=6)
        bounds = tool.BoundBox
        self.assertAlmostEqual(bounds.XMin, 0, places=6)
        self.assertAlmostEqual(bounds.XMax, 4, places=6)
        self.assertAlmostEqual(bounds.YMax - bounds.YMin, 4 * sides, places=6)
        self.assertAlmostEqual(bounds.ZMin, 0, places=6)
        self.assertAlmostEqual(bounds.ZMax, 2, places=6)

        reverse = revolution.Shape.ElementReverseMap
        for radius in (1, 2, 3, 4):
            cylinders = [
                "Face%d" % (i + 1)
                for i, face in enumerate(revolution.Shape.Faces)
                if isinstance(face.Surface, Part.Cylinder)
                and abs(face.Surface.Radius - radius) < 1e-6
            ]
            self.assertEqual(len(cylinders), sides, radius)
            for name in cylinders:
                mapped = reverse.get(name)
                mapped = [mapped] if isinstance(mapped, str) else list(mapped or [])
                self.assertTrue(mapped, name)
                for each in mapped:
                    self.assertIn(f";{sketch.ID}^;SKT^;", FreeCAD.expandMappedName(each), name)
        harness.assertEveryElementNamed(revolution.Shape)
        harness.assertDistinctNames(revolution.Shape)

    def testRevolutionTwoFacesUpToFace(self):
        self.revolveTwoFaces("Revolution")

    def testGrooveTwoFacesUpToFace(self):
        self.revolveTwoFaces("Groove")

    def testRevolutionTwoFacesUpToFirst(self):
        """Up to first for each face on its own: each face's first face is the box's x = 0
        (ops#263; before, the first face was looked for once, for the whole profile)."""
        self.revolveTwoFaces("Revolution", upToType="UpToFirst")

    def testGrooveTwoFacesUpToFirst(self):
        self.revolveTwoFaces("Groove", upToType="UpToFirst")

    def testRevolutionTwoFacesSymmetric(self):
        self.revolveTwoFaces("Revolution", sideType="Symmetric")

    def testGrooveTwoFacesSymmetric(self):
        self.revolveTwoFaces("Groove", sideType="Symmetric")

    def testRevolutionTwoFacesTwoSides(self):
        self.revolveTwoFaces("Revolution", sideType="Two sides")

    def testGrooveTwoFacesTwoSides(self):
        self.revolveTwoFaces("Groove", sideType="Two sides")

    def testRevolutionTwoFacesTwoSidesUpToFirst(self):
        self.revolveTwoFaces("Revolution", sideType="Two sides", upToType="UpToFirst")

    def revolveAcrossTheAxis(self, angle2=None):
        """The profile of testRevolutionTwoFacesAcrossTheAxis() revolved up to the wall's face;
        with `angle2`, Two sides, side 2 by that angle."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        wall = body.newObject("PartDesign::AdditiveBox", "Wall")
        wall.Length = 1
        wall.Width = 30
        wall.Height = 3
        wall.Placement = FreeCAD.Placement(FreeCAD.Vector(-1, 0, 0), FreeCAD.Rotation())
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        for x0, x1 in ((10, 14), (-16, -12)):
            points = [
                FreeCAD.Vector(x0, 0),
                FreeCAD.Vector(x1, 0),
                FreeCAD.Vector(x1, 2),
                FreeCAD.Vector(x0, 2),
            ]
            for start, end in zip(points, points[1:] + points[:1]):
                sketch.addGeometry(Part.LineSegment(start, end), False)
        self.Doc.recompute()
        [zAxis] = [f for f in body.Origin.OriginFeatures if f.Role == "Z_Axis"]
        [face] = [
            "Face%d" % (i + 1)
            for i, f in enumerate(wall.Shape.Faces)
            if abs(f.BoundBox.XMin) < 1e-9 and abs(f.BoundBox.XMax) < 1e-9
        ]
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (zAxis, [""])
        revolution.Refine = False
        revolution.Type = "UpToFace"
        revolution.UpToFace = (wall, [face])
        if angle2 is not None:
            revolution.SideType = "Two sides"
            revolution.Type2 = "Angle"
            revolution.Angle2 = angle2
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)
        return wall, sketch, revolution

    def testRevolutionTwoFacesAcrossTheAxis(self):
        """Faces on opposite sides of the axis whose sweeps overlap give the union of the sweeps
        (ops#263, decision 44). The profile on XZ: A, x in [10, 14], and B, x in [-16, -12],
        z in [0, 2], revolved about the origin's Z axis up to the face x = 0 of a wall x in
        [-1, 0], y in [0, 30], z in [0, 3] (90). A sweeps 90 degrees, from 0 to the wall;
        B sweeps 270, from 180 through 270 and 0 to the wall, across A's quarter at radii 12..14.
        The tools are fused: A + B - their overlap."""
        wall, sketch, revolution = self.revolveAcrossTheAxis()
        a = math.pi / 4 * (14**2 - 10**2) * 2
        b = 3 * math.pi / 4 * (16**2 - 12**2) * 2
        overlap = math.pi / 4 * (14**2 - 12**2) * 2
        tool = revolution.Shape.cut(wall.Shape)
        self.assertAlmostEqual(tool.Volume, a + b - overlap, places=6)
        self.assertAlmostEqual(revolution.Shape.Volume, 90 + a + b - overlap, places=6)
        # B's quarter from 180 to 270 is there, and nothing from 90 to 180 (only the wall)
        self.assertTrue(revolution.Shape.isInside(FreeCAD.Vector(-10, -10, 1), 1e-7, True))
        self.assertFalse(revolution.Shape.isInside(FreeCAD.Vector(-10, 10, 1), 1e-7, True))
        harness.assertEveryElementNamed(revolution.Shape)
        harness.assertDistinctNames(revolution.Shape)

    def revolveAcrossTheAxisTwoSides(self, angle2, sweeps):
        """Two sides across the axis, side 1 up to the wall's face, side 2 by `angle2` degrees
        (PR 259 round 1, M1). B's side 1 crosses A's start face, the seam at 0 degrees, at
        radii 12..14, so the fusion of side 1's tools splits the seam's elements there. Side 1's
        seam is marked (CPY;1) on each face's tool before the fusion: every name from the profile
        on an element of the seam plane (y = 0, x in [10, 14]) carries this feature's copy
        section, side 1's or side 2's. Marked after the fusion, the split pieces kept the
        profile's names unmarked. `sweeps` is the tool's volume over 2 (the profile's height)."""
        wall, sketch, revolution = self.revolveAcrossTheAxis(angle2)
        tool = revolution.Shape.cut(wall.Shape)
        self.assertAlmostEqual(tool.Volume, 2 * sweeps, places=6)
        reverse = revolution.Shape.ElementReverseMap
        seam = []
        for kind, elements in (
            ("Face", revolution.Shape.Faces),
            ("Edge", revolution.Shape.Edges),
            ("Vertex", revolution.Shape.Vertexes),
        ):
            for i, element in enumerate(elements):
                bounds = element.BoundBox
                if abs(bounds.YMin) < 1e-7 and abs(bounds.YMax) < 1e-7 and bounds.XMin > 9:
                    seam.append("%s%d" % (kind, i + 1))
        self.assertTrue(seam)
        profile = f";{sketch.ID};SKT;"
        marked = f";{revolution.ID};CPY;"
        fromProfile = []
        for name in seam:
            mapped = reverse.get(name)
            mapped = [mapped] if isinstance(mapped, str) else list(mapped or [])
            self.assertTrue(mapped, name)
            for each in mapped:
                expanded = FreeCAD.expandMappedName(each).replace("^", "")
                if profile in expanded:
                    fromProfile.append(name)
                    self.assertIn(marked, expanded, name)
        # Without a name from the profile on the seam, the check above holds vacuously (PR 259
        # verification 1, L1).
        self.assertTrue(fromProfile)
        harness.assertEveryElementNamed(revolution.Shape)
        harness.assertDistinctNames(revolution.Shape)

    @staticmethod
    def sector(r0, r1, degrees):
        """The area of the ring sector from radius r0 to r1 over `degrees`."""
        return math.radians(degrees) / 2 * (r1**2 - r0**2)

    def testRevolutionTwoFacesAcrossTheAxisTwoSides(self):
        """Side 2 by 30 degrees: A from -30 to 0 and B from 150 to 180, A's across B's side 1
        at radii 12..14. The seam lies inside, its edges on the outside."""
        side1 = self.sector(10, 14, 90) + self.sector(12, 16, 270) - self.sector(12, 14, 90)
        side2 = self.sector(10, 14, 30) + self.sector(12, 16, 30) - self.sector(12, 14, 30)
        self.revolveAcrossTheAxisTwoSides(30, side1 + side2)

    def testRevolutionTwoFacesAcrossTheAxisTwoSidesSameWay(self):
        """Side 2 by -20 degrees, within side 1: the seam's piece at radii 10..12 is a face of
        the result."""
        side1 = self.sector(10, 14, 90) + self.sector(12, 16, 270) - self.sector(12, 14, 90)
        self.revolveAcrossTheAxisTwoSides(-20, side1)

    def profileAcross(self, body):
        """The profile x in [1, 3], z in [0, 2] on XZ, revolved about Z (its V axis) in the tests
        of an up-to face across the profile plane (ops#254)."""
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        points = [
            FreeCAD.Vector(1, 0),
            FreeCAD.Vector(3, 0),
            FreeCAD.Vector(3, 2),
            FreeCAD.Vector(1, 2),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        self.Doc.recompute()
        return sketch

    def revolveAcross(self, body, kind, sideType, upTo, upToType="UpToFace"):
        """A `kind` of profileAcross() up to `upTo` (a link and its sub-names) on both sides."""
        revolution = body.newObject("PartDesign::" + kind, kind)
        sketch = self.profileAcross(body)
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.SideType = sideType
        revolution.Type = upToType
        if upToType == "UpToFace":
            revolution.UpToFace = upTo
        if sideType == "Two sides":
            revolution.Type2 = upToType
            if upToType == "UpToFace":
                revolution.UpToFace2 = upTo
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)
        return revolution

    def assertHalfRing(self, tool):
        """The tool of profileAcross() is the half ring from -90 to +90 degrees, 8 pi, on the
        side x >= 0. Symmetric revolved the second side the long way round, from +90 to +270,
        when the up-to face mirrors onto itself (ops#254)."""
        self.assertAlmostEqual(tool.Volume, 8 * math.pi, places=6)
        bounds = tool.BoundBox
        self.assertAlmostEqual(bounds.XMin, 0, places=6)
        self.assertAlmostEqual(bounds.XMax, 3, places=6)
        self.assertAlmostEqual(bounds.YMin, -3, places=6)
        self.assertAlmostEqual(bounds.YMax, 3, places=6)
        self.assertAlmostEqual(bounds.ZMin, 0, places=6)
        self.assertAlmostEqual(bounds.ZMax, 2, places=6)

    def wallAtXZero(self, feature):
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(feature.Shape.Faces)
            if abs(face.BoundBox.XMin) < 1e-9 and abs(face.BoundBox.XMax) < 1e-9
        ]
        return wall

    def revolveUpToFaceAcross(self, kind, sideType, upToType="UpToFace"):
        """A face of the base that reaches across the profile plane, so that it mirrors onto
        itself (ops#254): the box x in [-4, 0], y in [-4, 4], z in [0, 2] (Revolution: 64), or
        x in [0, 4], y in [-4, 4], z in [0, 3] (Groove: 96, its top layer keeps it one solid).
        The profileAcross() goes up to the box's face x = 0 on both sides (or up to the first
        face): assertHalfRing()."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 8
        block.Height = 2 if kind == "Revolution" else 3
        x0 = -4 if kind == "Revolution" else 0
        block.Placement = FreeCAD.Placement(FreeCAD.Vector(x0, -4, 0), FreeCAD.Rotation())
        self.Doc.recompute()
        upTo = (block, [self.wallAtXZero(block)])
        revolution = self.revolveAcross(body, kind, sideType, upTo, upToType)
        expected = 64 + 8 * math.pi if kind == "Revolution" else 96 - 8 * math.pi
        self.assertAlmostEqual(revolution.Shape.Volume, expected, places=6)
        if kind == "Revolution":
            self.assertHalfRing(revolution.Shape.cut(block.Shape))
        else:
            self.assertHalfRing(block.Shape.cut(revolution.Shape))

    def testRevolutionUpToFaceAcrossSymmetric(self):
        self.revolveUpToFaceAcross("Revolution", "Symmetric")

    def testRevolutionUpToFaceAcrossTwoSides(self):
        self.revolveUpToFaceAcross("Revolution", "Two sides")

    def testGrooveUpToFaceAcrossSymmetric(self):
        self.revolveUpToFaceAcross("Groove", "Symmetric")

    def testRevolutionUpToFirstAcrossSymmetric(self):
        self.revolveUpToFaceAcross("Revolution", "Symmetric", "UpToFirst")

    def testGrooveUpToFirstAcrossSymmetric(self):
        self.revolveUpToFaceAcross("Groove", "Symmetric", "UpToFirst")

    def testRevolutionUpToHoledFaceAcrossSymmetric(self):
        """The box of revolveUpToFaceAcross() with a window through it at y in [-2.5, -1.5],
        z in [0.5, 1.5]: its face x = 0 has a symmetric outline but not a symmetric hole, so it
        doesn't mirror onto itself. The second side goes up to the mirrored face, solid where it
        lands (the window would sit there in the face itself): assertHalfRing()."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 8
        block.Height = 2
        block.Placement = FreeCAD.Placement(FreeCAD.Vector(-4, -4, 0), FreeCAD.Rotation())
        window = body.newObject("PartDesign::SubtractiveBox", "Window")
        window.Length = 6
        window.Width = 1
        window.Height = 1
        window.Placement = FreeCAD.Placement(FreeCAD.Vector(-5, -2.5, 0.5), FreeCAD.Rotation())
        self.Doc.recompute()
        upTo = (window, [self.wallAtXZero(window)])
        revolution = self.revolveAcross(body, "Revolution", "Symmetric", upTo)
        self.assertAlmostEqual(revolution.Shape.Volume, 60 + 8 * math.pi, places=6)
        self.assertHalfRing(revolution.Shape.cut(window.Shape))

    def testRevolutionUpToDiskAcrossSymmetric(self):
        """The end disk of a cylinder along X (x in [-4, 0], radius 4 about y = 0, z = 1), across
        the profile plane: a face that mirrors onto itself, though its seam vertex at the top
        mirrors elsewhere. assertHalfRing()."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        pin = body.newObject("PartDesign::AdditiveCylinder", "Pin")
        pin.Radius = 4
        pin.Height = 4
        pin.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-4, 0, 1), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90)
        )
        self.Doc.recompute()
        upTo = (pin, [self.wallAtXZero(pin)])
        revolution = self.revolveAcross(body, "Revolution", "Symmetric", upTo)
        self.assertAlmostEqual(revolution.Shape.Volume, 64 * math.pi + 8 * math.pi, places=6)
        self.assertHalfRing(revolution.Shape.cut(pin.Shape))

    def pipeToolAcross(self, start, length, sideType):
        """The tool of profileAcross() up to the wall of a pipe along Y (radius 5 about x = -5,
        z = 1, y in [start, start + length]): the Revolution minus the pipe."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        pipe = body.newObject("PartDesign::AdditiveCylinder", "Pipe")
        pipe.Radius = 5
        pipe.Height = length
        pipe.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-5, start, 1), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90)
        )
        self.Doc.recompute()
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(pipe.Shape.Faces)
            if isinstance(face.Surface, Part.Cylinder)
        ]
        revolution = self.revolveAcross(body, "Revolution", sideType, (pipe, [wall]))
        return revolution.Shape.cut(pipe.Shape)

    def assertMirroredPipeTool(self, start, length):
        """Symmetric up to the wall of pipeToolAcross(): the second side mirrors the first, so the
        tool is symmetric about the profile plane, twice One side's tool, and spans y in [-3, 3].
        The sweep enters the wall at x <= 0, so it isn't a half ring."""
        oneSide = self.pipeToolAcross(start, length, "One side")
        tool = self.pipeToolAcross(start, length, "Symmetric")
        mirrored = tool.mirror(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0))
        self.assertGreater(oneSide.Volume, 4 * math.pi)
        self.assertAlmostEqual(tool.Volume, 2 * oneSide.Volume, places=6)
        self.assertAlmostEqual(tool.cut(mirrored).Volume, 0, places=6)
        self.assertAlmostEqual(tool.BoundBox.YMin, -3, places=6)
        self.assertAlmostEqual(tool.BoundBox.YMax, 3, places=6)

    def testRevolutionUpToPipeWallAcrossSymmetric(self):
        """A pipe y in [-5, 5]: a curved face that mirrors onto itself, though its axis mirrors
        to -Y."""
        self.assertMirroredPipeTool(-5, 10)

    def testRevolutionUpToLongerPipeWallAcrossSymmetric(self):
        """A pipe longer on one side of the profile plane, y in [-5, 3] or [-1, 5]: its wall
        crosses the plane and shares its surface with its image, but not its points. The second
        side lost its tool silently (the first) or failed (the second); it goes up to the whole
        cylinder now (ops#272)."""
        for start, length in ((-5, 8), (-1, 6)):
            with self.subTest(start=start):
                self.assertMirroredPipeTool(start, length)

    def testRevolutionUpToDatumAcrossSymmetric(self):
        """The origin YZ plane, unbounded, across the profile plane, as the up-to face of the
        first feature: assertHalfRing()."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        [yz] = [f for f in body.Origin.OriginFeatures if f.Role == "YZ_Plane"]
        revolution = self.revolveAcross(body, "Revolution", "Symmetric", (yz, [""]))
        self.assertHalfRing(revolution.Shape)

    def ringSector(self, start, span):
        """The sweep of profileAcross() from `start` degrees about Z over `span` degrees: the ring
        r in [1, 3], z in [0, 2], 8 per radian."""
        up = FreeCAD.Vector(0, 0, 1)
        sector = Part.makeCylinder(3, 2, FreeCAD.Vector(), up, span).cut(
            Part.makeCylinder(1, 2, FreeCAD.Vector(), up, span)
        )
        sector.rotate(FreeCAD.Vector(), up, start)
        return sector

    def assertSameSolid(self, shape, expected, delta=1e-6):
        self.assertAlmostEqual(shape.Volume, expected.Volume, delta=delta)
        self.assertAlmostEqual(shape.cut(expected).Volume, 0, delta=delta)
        self.assertAlmostEqual(expected.cut(shape).Volume, 0, delta=delta)

    def revolveUpToTurnedWallAcross(self, kind, degrees, delta=1e-6):
        """The box of revolveUpToFaceAcross() turned about the axis by `degrees`: its face through
        the axis crosses the profile plane and isn't symmetric about it, so its image crosses it
        there. BRepFeat then lost the second side silently, at any angle (ops#272). Both sides
        turn 90 + degrees, the second up to the image's plane: the sweep is the ring from
        -(90 + degrees) to 90 + degrees, added to or cut from the box."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 8
        block.Height = 2 if kind == "Revolution" else 3
        x0 = -4 if kind == "Revolution" else 0
        turn = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), degrees)
        block.Placement = FreeCAD.Placement(turn.multVec(FreeCAD.Vector(x0, -4, 0)), turn)
        self.Doc.recompute()
        normal = turn.multVec(FreeCAD.Vector(1, 0, 0))
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(block.Shape.Faces)
            if abs(abs(face.normalAt(0, 0).dot(normal)) - 1) < 1e-9
            and abs(face.CenterOfMass.dot(normal)) < 1e-6
        ]
        revolution = self.revolveAcross(body, kind, "Symmetric", (block, [wall]))
        sweep = self.ringSector(-90 - degrees, 180 + 2 * degrees)
        if kind == "Revolution":
            self.assertSameSolid(revolution.Shape, block.Shape.fuse(sweep), delta)
        else:
            self.assertSameSolid(revolution.Shape, block.Shape.cut(sweep), delta)

    def testRevolutionUpToTurnedWallAcrossSymmetric(self):
        self.revolveUpToTurnedWallAcross("Revolution", 20)

    def testGrooveUpToTurnedWallAcrossSymmetric(self):
        self.revolveUpToTurnedWallAcross("Groove", 20)

    def testRevolutionUpToNearlySymmetricWallAcrossSymmetric(self):
        """Turned by 1e-5 and 1e-3 degrees: the wall's far end lies 7e-7 and 7e-5 off its image,
        too far to count as the same face (ops#272, the PR 239 review's L1). The results agree
        with the expected sweep to within the wall's offset over its area (8 * 7e-7)."""
        for kind in ("Revolution", "Groove"):
            for degrees in (1e-5, 1e-3):
                with self.subTest(kind=kind, degrees=degrees):
                    self.revolveUpToTurnedWallAcross(kind, degrees, delta=1e-5)

    def testRevolutionUpToShortWallAcrossSymmetric(self):
        """The box x in [-4, 0], y in [-4, 1]: its face x = 0 crosses the profile plane, but the
        first side meets the plane x = 0 at y = r in [1, 3], beyond the face, and only meets the
        face itself half a turn later. The image's whole plane would stop the second side a
        quarter turn out, so the feature fails with an error instead (ops#272)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 5
        block.Height = 2
        block.Placement = FreeCAD.Placement(FreeCAD.Vector(-4, -4, 0), FreeCAD.Rotation())
        self.Doc.recompute()
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        sketch = self.profileAcross(body)
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.SideType = "Symmetric"
        revolution.Type = "UpToFace"
        revolution.UpToFace = (block, [self.wallAtXZero(block)])
        self.Doc.recompute()
        self.assertFalse(revolution.isValid())
        self.assertIn("Use Two sides", revolution.getStatusString())

    def testRevolutionUpToPartFaceSymmetricFirstSolid(self):
        """The bounded face y in [0.5, 4] of revolveUpToWall(), on the plane x = 0 through the
        axis, on one side of the profile plane: its image shares its plane, so the second side
        goes up to the whole plane, through the box BRepFeat gets as its base (ops#272)."""
        revolution = self.revolveUpToWall("Symmetric", core=False, wall="part")
        self.assertSameSolid(revolution.Shape, self.ringSector(-90, 180))

    def testRevolutionUpToLastAcrossSymmetric(self):
        self.revolveUpToFaceAcross("Revolution", "Symmetric", "UpToLast")

    def testGrooveUpToHoledFaceAcrossSymmetric(self):
        """The Groove of testRevolutionUpToHoledFaceAcrossSymmetric(): the box x in [0, 4],
        y in [-4, 4], z in [0, 3] with the window through it at y in [-2.5, -1.5],
        z in [0.5, 1.5]. The groove cuts the half ring from -90 to 90 degrees (ops#272)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 8
        block.Height = 3
        block.Placement = FreeCAD.Placement(FreeCAD.Vector(0, -4, 0), FreeCAD.Rotation())
        window = body.newObject("PartDesign::SubtractiveBox", "Window")
        window.Length = 6
        window.Width = 1
        window.Height = 1
        window.Placement = FreeCAD.Placement(FreeCAD.Vector(-1, -2.5, 0.5), FreeCAD.Rotation())
        self.Doc.recompute()
        upTo = (window, [self.wallAtXZero(window)])
        groove = self.revolveAcross(body, "Groove", "Symmetric", upTo)
        self.assertSameSolid(groove.Shape, window.Shape.cut(self.ringSector(-90, 180)))

    def testRevolutionUpToPlaneThroughProfileSymmetric(self):
        """The face x = 2 of the box x in [2, 6], y in [-4, 4], z in [0, 2], symmetric about the
        profile plane and across the profile itself (x in [1, 3]): Symmetric passes the face
        itself to both sides, as Two sides does, and gives the same result (ops#272). Today both
        are valid and add nothing, without an error (ops#289)."""
        results = {}
        for sideType in ("Two sides", "Symmetric"):
            body = self.Doc.addObject("PartDesign::Body", "Body")
            block = body.newObject("PartDesign::AdditiveBox", "Block")
            block.Length = 4
            block.Width = 8
            block.Height = 2
            block.Placement = FreeCAD.Placement(FreeCAD.Vector(2, -4, 0), FreeCAD.Rotation())
            self.Doc.recompute()
            [face] = [
                "Face%d" % (i + 1)
                for i, f in enumerate(block.Shape.Faces)
                if abs(f.BoundBox.XMin - 2) < 1e-9 and abs(f.BoundBox.XMax - 2) < 1e-9
            ]
            revolution = body.newObject("PartDesign::Revolution", "Revolution")
            sketch = self.profileAcross(body)
            revolution.Profile = sketch
            revolution.ReferenceAxis = (sketch, ["V_Axis"])
            revolution.SideType = sideType
            revolution.Type = "UpToFace"
            revolution.UpToFace = (block, [face])
            if sideType == "Two sides":
                revolution.Type2 = "UpToFace"
                revolution.UpToFace2 = (block, [face])
            self.Doc.recompute()
            results[sideType] = (revolution.isValid(), revolution.Shape)
        self.assertEqual(results["Symmetric"][0], results["Two sides"][0])
        if results["Two sides"][0]:
            self.assertSameSolid(results["Symmetric"][1], results["Two sides"][1])

    def assertSymmetricFails(self, body, upTo, kind="Revolution"):
        """A `kind` of profileAcross() Symmetric up to `upTo` fails with an error that names Two
        sides."""
        revolution = body.newObject("PartDesign::" + kind, kind)
        sketch = self.profileAcross(body)
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.SideType = "Symmetric"
        revolution.Type = "UpToFace"
        revolution.UpToFace = upTo
        self.Doc.recompute()
        self.assertFalse(revolution.isValid())
        self.assertIn("Use Two sides", revolution.getStatusString())

    def testRevolutionUpToSplineWallAcrossSymmetric(self):
        """A Pad along Z of the region x in [-4, 0] bounded by a B-spline wall from (0, -4) to
        (0, 4) that winds across x = 0 (through (0.3, -2), (0, 0.5), (-0.3, 2)): the wall crosses
        the profile plane, and its surface (an extrusion of the spline) ends where the face ends,
        so it can't stop the second side at the wall's image. The feature fails, naming Two sides
        (the PR 268 review's High; before, "Could not revolve the sketch")."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "WallSketch")
        [xy] = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        sketch.AttachmentSupport = (xy, [""])
        sketch.MapMode = "FlatFace"
        spline = Part.BSplineCurve()
        spline.interpolate(
            [
                FreeCAD.Vector(0, -4, 0),
                FreeCAD.Vector(0.3, -2, 0),
                FreeCAD.Vector(0, 0.5, 0),
                FreeCAD.Vector(-0.3, 2, 0),
                FreeCAD.Vector(0, 4, 0),
            ]
        )
        sketch.addGeometry(spline, False)
        corners = [
            FreeCAD.Vector(0, 4, 0),
            FreeCAD.Vector(-4, 4, 0),
            FreeCAD.Vector(-4, -4, 0),
            FreeCAD.Vector(0, -4, 0),
        ]
        for start, end in zip(corners, corners[1:]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 2
        self.Doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(pad.Shape.Faces)
            if not isinstance(face.Surface, Part.Plane)
        ]
        self.assertSymmetricFails(body, (pad, [wall]))

    def testRevolutionUpToSphereAcrossSymmetric(self):
        """A sphere of radius 5 about (-4.5, 1, 1), across the profile plane, not symmetric about
        it: its whole surface as the second side's face gave less than the mirror of the first
        side (tool 14.71 instead of 22.43), silently (the PR 268 review's High, sphere probed).
        The feature fails, naming Two sides."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        ball = body.newObject("PartDesign::AdditiveSphere", "Ball")
        ball.Radius = 5
        ball.Placement = FreeCAD.Placement(FreeCAD.Vector(-4.5, 1, 1), FreeCAD.Rotation())
        self.Doc.recompute()
        self.assertSymmetricFails(body, (ball, ["Face1"]))

    def testRevolutionUpToNotchedWallAcrossSymmetric(self):
        """The box of revolveUpToFaceAcross() with a small window through it at y in [1.7, 1.95],
        z in [0.75, 0.95], on the first side's half of its face x = 0: the first side's sweep
        passes through it, so the face's whole plane would not stop the second side where the
        first one's mirror ends. The feature was valid with the two sides unequal, silently (the
        PR 268 review's M2: the old check sampled points the window missed). It fails now,
        naming Two sides."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 8
        block.Height = 2
        block.Placement = FreeCAD.Placement(FreeCAD.Vector(-4, -4, 0), FreeCAD.Rotation())
        window = body.newObject("PartDesign::SubtractiveBox", "Window")
        window.Length = 6
        window.Width = 0.25
        window.Height = 0.2
        window.Placement = FreeCAD.Placement(FreeCAD.Vector(-5, 1.7, 0.75), FreeCAD.Rotation())
        self.Doc.recompute()
        self.assertSymmetricFails(body, (window, [self.wallAtXZero(window)]))

    def trimmedTubeWall(self, trimmed):
        """The part of the tube of radius 2 about the vertical line x = -1, y = 1.5 from 60 to
        300 degrees about it, z in [-1, 3], as a face of a Part::Feature, on a trimmed cylinder
        (Geom_RectangularTrimmedSurface, as STEP files can give) or on the cylinder itself. The
        BREP text gets the trimmed surface: FreeCAD's Python makes faces on the basis surface."""
        cylinder = Part.Cylinder()
        cylinder.Center = FreeCAD.Vector(-1, 1.5, -1)
        cylinder.Radius = 2
        first, last = math.radians(60), math.radians(300)
        text = cylinder.toShape(first, last, 0, 4).exportBrepToString()
        record = "2 -1 1.5 -1 0 0 1 1 0 0 0 1 0 2"
        self.assertEqual(text.count(record), 1)
        if trimmed:
            # 10: Geom_RectangularTrimmedSurface, its bounds, then its basis surface.
            text = text.replace(record, "10 %.17g %.17g 0 4\n%s" % (first, last, record))
        shape = Part.Shape()
        shape.importBrepFromString(text)
        self.assertEqual("\n10 " in shape.exportBrepToString(), trimmed)
        wall = self.Doc.addObject("Part::Feature", "TubeWall")
        wall.Shape = shape.Faces[0]
        return wall

    def testRevolutionUpToTrimmedCylinderAcrossSymmetric(self):
        """trimmedTubeWall(): the profile's path first crosses the tube outside the face (at
        about 6 to 48 degrees about the tube's line, or 334 at radius 1), then meets the face; the
        face crosses the profile plane (at x = -2.32). The whole tube would stop the second side
        at the first crossing's mirror, short of the first side's. The old check intersected
        the trimmed surface, which ends where the face does, so it missed the first crossing: the
        two sides were unequal, silently (the PR 268 review's M1). Both faces fail, naming Two
        sides."""
        for trimmed in (False, True):
            with self.subTest(trimmed=trimmed):
                wall = self.trimmedTubeWall(trimmed)
                body = self.Doc.addObject("PartDesign::Body", "Body")
                self.assertSymmetricFails(body, (wall, ["Face1"]))

    def secondCapTopEdge(self, shape, degrees):
        """The top edge (z = 2) of the second side's end cap, on the ray at -(90 + degrees)."""
        angle = math.radians(-90 - degrees)
        ray = FreeCAD.Vector(math.cos(angle), math.sin(angle), 0)
        [edge] = [
            "Edge%d" % (i + 1)
            for i, edge in enumerate(shape.Edges)
            if isinstance(edge.Curve, Part.Line)
            and (edge.CenterOfMass - ray * 2 - FreeCAD.Vector(0, 0, 2)).Length < 1e-6
        ]
        return edge

    def assertFilletAlong(self, fillet, degrees):
        """The fillet's round face runs along the ray at -(90 + degrees)."""
        angle = math.radians(-90 - degrees)
        ray = FreeCAD.Vector(math.cos(angle), math.sin(angle), 0)
        rounds = [
            face
            for face in fillet.Shape.Faces
            if isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Radius - 0.1) < 1e-6
        ]
        self.assertEqual(len(rounds), 1)
        self.assertAlmostEqual(abs(rounds[0].Surface.Axis.dot(ray)), 1, places=6)

    def testRevolutionUpToTurnedWallSecondCapFillet(self):
        """A plate x in [-0.1, 0], y in [-4, 4], z in [0, 2] turned 10 degrees about Z; Symmetric
        up to its face through the axis: the second side goes up to the image's whole plane and
        ends at -100 degrees, outside the plate, in an end cap. A fillet on the top edge of that
        cap follows it when the plate turns to 20 degrees (-110): the cap keeps its names from
        the profile on the whole-plane route (the PR 268 review's L3)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        plate = body.newObject("PartDesign::AdditiveBox", "Plate")
        plate.Length = 0.1
        plate.Width = 8
        plate.Height = 2

        def turn(degrees):
            rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), degrees)
            plate.Placement = FreeCAD.Placement(
                rotation.multVec(FreeCAD.Vector(-0.1, -4, 0)), rotation
            )
            self.Doc.recompute()
            normal = rotation.multVec(FreeCAD.Vector(1, 0, 0))
            [wall] = [
                "Face%d" % (i + 1)
                for i, face in enumerate(plate.Shape.Faces)
                if abs(abs(face.normalAt(0, 0).dot(normal)) - 1) < 1e-9
                and abs(face.CenterOfMass.dot(normal)) < 1e-6
            ]
            return wall

        revolution = self.revolveAcross(body, "Revolution", "Symmetric", (plate, [turn(10)]))
        self.assertSameSolid(revolution.Shape, plate.Shape.fuse(self.ringSector(-100, 200)))
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (revolution, [self.secondCapTopEdge(revolution.Shape, 10)])
        fillet.Radius = 0.1
        self.Doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertFilletAlong(fillet, 10)
        self.assertEqual(turn(20), revolution.UpToFace[1][0])
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertSameSolid(revolution.Shape, plate.Shape.fuse(self.ringSector(-110, 220)))
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertFilletAlong(fillet, 20)

    def slantedWallBase(self, body, kind):
        """A Pad of a polygon on XY with a slanted wall on the plane x - 0.5 y = -1, from
        (-3.5, -5) to (-0.75, 0.5), across the profile plane. Revolution (height 2): the region A
        left of the wall below y = 0.5, joined to B, x in [-5, 0.5], y in [0.5, 4] (the PR 268
        verification's High). Groove (height 3): the region right of the wall below y = 0.5, up
        to x = 4, which holds the profile. Returns the Pad and the wall's name."""
        sketch = body.newObject("Sketcher::SketchObject", "BaseSketch")
        [xy] = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        sketch.AttachmentSupport = (xy, [""])
        sketch.MapMode = "FlatFace"
        if kind == "Revolution":
            corners = [(-5, -5), (-3.5, -5), (-0.75, 0.5), (0.5, 0.5), (0.5, 4), (-5, 4)]
        else:
            corners = [(-3.5, -5), (4, -5), (4, 0.5), (-0.75, 0.5)]
        points = [FreeCAD.Vector(x, y, 0) for x, y in corners]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 2 if kind == "Revolution" else 3
        self.Doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        normal = FreeCAD.Vector(1, -0.5, 0).normalize()
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(pad.Shape.Faces)
            if isinstance(face.Surface, Part.Plane)
            and abs(abs(face.normalAt(0, 0).dot(normal)) - 1) < 1e-9
        ]
        return pad, wall

    def testRevolutionUpToSlantedWallThroughBaseSymmetric(self):
        """slantedWallBase(): the first side passes the wall's plane at y >= 0.8, inside B, and
        meets the wall itself at about 180 to 226 degrees. The tools up to the wall and up to its
        whole plane are the same, since what lies between is base; the second side stopped at
        the mirror of the plane's first hit (-81 to -127 degrees), and the result lacked 7.42
        that the mirror of the first side holds, silently (the PR 268 verification's High). It
        fails now, naming Two sides. So does a Groove whose first side runs through empty space
        there (the base right of the wall): its second side left material that the mirror of
        the first side removes."""
        for kind in ("Revolution", "Groove"):
            with self.subTest(kind=kind):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                pad, wall = self.slantedWallBase(body, kind)
                self.assertSymmetricFails(body, (pad, [wall]), kind=kind)

    def coneToolAcross(self, sideType):
        """The tool of profileAcross() up to the wall of a cone along Y, radius 4 at y = -5 to 6
        at y = 5 about x = -5, z = 1 (5 at the profile plane, which its wall crosses at x = 0):
        the Revolution minus the cone."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        cone = body.newObject("PartDesign::AdditiveCone", "Cone")
        cone.Radius1 = 4
        cone.Radius2 = 6
        cone.Height = 10
        cone.Placement = FreeCAD.Placement(
            FreeCAD.Vector(-5, -5, 1), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90)
        )
        self.Doc.recompute()
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(cone.Shape.Faces)
            if isinstance(face.Surface, Part.Cone)
        ]
        revolution = self.revolveAcross(body, "Revolution", sideType, (cone, [wall]))
        return revolution.Shape.cut(cone.Shape)

    def testRevolutionUpToConeWallAcrossSymmetric(self):
        """A cone wall across the profile plane, not symmetric about it: the second side goes up
        to the image's whole cone. The image cone is wider on the second side than the cone
        itself, so the tool is the first side's sweep and its mirror: symmetric about the profile
        plane, twice One side's tool."""
        oneSide = self.coneToolAcross("One side")
        tool = self.coneToolAcross("Symmetric")
        mirrored = tool.mirror(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0))
        self.assertGreater(oneSide.Volume, 2 * math.pi)
        self.assertAlmostEqual(tool.Volume, 2 * oneSide.Volume, places=6)
        self.assertAlmostEqual(tool.cut(mirrored).Volume, 0, places=6)

    def grooveToolInCylinder(self, sideType):
        """The volume a Groove of profileAcross() removes from a cylinder along Y, radius 5 about
        x = 5, z = 1, y in [-5, 4] (it holds the profile), up to its wall: longer on one side
        of the profile plane, so the wall crosses the plane and isn't symmetric about it."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        drum = body.newObject("PartDesign::AdditiveCylinder", "Drum")
        drum.Radius = 5
        drum.Height = 9
        drum.Placement = FreeCAD.Placement(
            FreeCAD.Vector(5, -5, 1), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), -90)
        )
        self.Doc.recompute()
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(drum.Shape.Faces)
            if isinstance(face.Surface, Part.Cylinder)
        ]
        groove = self.revolveAcross(body, "Groove", sideType, (drum, [wall]))
        return drum.Shape.cut(groove.Shape)

    def testGrooveUpToCylinderWallAcrossSymmetric(self):
        """The Groove on the whole-cylinder route: the second side goes up to the image's whole
        cylinder (the cylinder itself, mirrored), so the removed volume is symmetric about the
        profile plane, twice One side's."""
        oneSide = self.grooveToolInCylinder("One side")
        removed = self.grooveToolInCylinder("Symmetric")
        mirrored = removed.mirror(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0))
        self.assertGreater(oneSide.Volume, 2 * math.pi)
        # The booleans on the drum's curved wall leave about 7e-7 of noise.
        self.assertAlmostEqual(removed.Volume, 2 * oneSide.Volume, delta=1e-5)
        self.assertAlmostEqual(removed.cut(mirrored).Volume, 0, delta=1e-5)

    def testRevolutionOfThinRingUpToTurnedWallAcrossSymmetric(self):
        """A thin ring profile on XZ, the circles of radius 0.9 and 0.72 about x = 2, z = 1,
        revolved Symmetric up to the box wall of revolveUpToTurnedWallAcross() turned by 20
        degrees. The first side's sweep ends in a ring on the wall whose hole holds the 3 x 3
        grid of points the check sampled inside the ring's bounds (wall under 0.29 of the
        radius), so the end face was skipped rather than checked: here the feature failed,
        naming Two sides; with a second end piece it could pass with side 2 wrong (the PR 268
        round 2 verification's finding 1). The end face is now judged by its edges too: the
        result is the box and the tube from -110 to 110 degrees, hollow inside."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = 4
        block.Width = 8
        block.Height = 2
        degrees = 20
        turn = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), degrees)
        block.Placement = FreeCAD.Placement(turn.multVec(FreeCAD.Vector(-4, -4, 0)), turn)
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        for radius in (0.9, 0.72):
            sketch.addGeometry(
                Part.Circle(FreeCAD.Vector(2, 1, 0), FreeCAD.Vector(0, 0, 1), radius), False
            )
        self.Doc.recompute()
        normal = turn.multVec(FreeCAD.Vector(1, 0, 0))
        [wall] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(block.Shape.Faces)
            if abs(abs(face.normalAt(0, 0).dot(normal)) - 1) < 1e-9
            and abs(face.CenterOfMass.dot(normal)) < 1e-6
        ]
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.SideType = "Symmetric"
        revolution.Type = "UpToFace"
        revolution.UpToFace = (block, [wall])
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        ring = Part.Face(
            [
                Part.Wire(
                    Part.Circle(FreeCAD.Vector(2, 0, 1), FreeCAD.Vector(0, 1, 0), radius).toShape()
                )
                for radius in (0.9, 0.72)
            ]
        )
        up = FreeCAD.Vector(0, 0, 1)
        tube = ring.revolve(FreeCAD.Vector(), up, 180 + 2 * degrees)
        tube.rotate(FreeCAD.Vector(), up, -90 - degrees)
        self.assertGreater(tube.Volume, 2.5)
        self.assertSameSolid(revolution.Shape, block.Shape.fuse(tube))

    def testRevolutionUpToFaceNeverMet(self):
        """The plane y = 100, parallel to the profile plane: the sweep about the Z axis never
        reaches it. The feature fails with an error and gives no solid."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        [xz] = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        sketch.AttachmentSupport = (xz, [""])
        sketch.MapMode = "FlatFace"
        points = [
            FreeCAD.Vector(1, 0),
            FreeCAD.Vector(3, 0),
            FreeCAD.Vector(3, 2),
            FreeCAD.Vector(1, 2),
        ]
        for start, end in zip(points, points[1:] + points[:1]):
            sketch.addGeometry(Part.LineSegment(start, end), False)
        wall = body.newObject("PartDesign::Plane", "Wall")
        wall.MapMode = "Deactivated"
        wall.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 100, 0), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
        )
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.Type = "UpToFace"
        revolution.UpToFace = (wall, [""])
        self.Doc.recompute()
        self.assertFalse(revolution.isValid())
        self.assertIn("Could not revolve the sketch", revolution.getStatusString())
        self.assertTrue(revolution.Shape.isNull())

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestRevolve")
        # print ("omit closing document for debugging")
