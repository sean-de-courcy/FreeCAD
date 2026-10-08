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
        """A Groove with nothing to cut gives its tool as the body's first solid, as a Groove by
        angle and a Pocket do (ops#239): the same quarter ring, 4 pi."""
        groove = self.revolveUpToWall("One side", core=False, kind="Groove")
        self.assertAlmostEqual(groove.Shape.Volume, 4 * math.pi, places=6)
        self.assertQuarter(groove.Shape, positiveY=True)

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
