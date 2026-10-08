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

    def revolveUpToWall(self, sideType, core):
        """An additive Revolution up to a datum plane, as the body's first solid or after a core
        cylinder (ops#191). The profile is the rectangle x in [1, 3], z in [0, 2] on XZ (area 4,
        centroid 2 from the axis), revolved about the global Z axis; the wall is the YZ plane, a
        quarter turn away on either side."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        if core:
            cylinder = body.newObject("PartDesign::AdditiveCylinder", "Core")
            cylinder.Radius = 1
            cylinder.Height = 2
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
            FreeCAD.Vector(), FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 90)
        )
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (sketch, ["V_Axis"])
        revolution.SideType = sideType
        revolution.Type = "UpToFace"
        revolution.UpToFace = (wall, [""])
        if sideType == "Two sides":
            revolution.Type2 = "UpToFace"
            revolution.UpToFace2 = (wall, [""])
        self.Doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(len(revolution.Shape.Solids), 1)
        return revolution

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

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestRevolve")
        # print ("omit closing document for debugging")
