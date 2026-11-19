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
import Part
import Sketcher
import TestSketcherApp
from PartDesignTests.Scenarios import harness


class TestPolarPattern(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPolarPattern")

    def testXAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Box]
        self.PolarPattern.Axis = (self.Doc.X_Axis, [""])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(1, 0, 0))

    def testYAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Box]
        self.PolarPattern.Axis = (self.Doc.Y_Axis, [""])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(0, 1, 0))

    def testZAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Box]
        self.PolarPattern.Axis = (self.Doc.Z_Axis, [""])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(0, 0, 1))

    def testNormalSketchAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 10
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Pad]
        self.PolarPattern.Axis = (self.PadSketch, ["N_Axis"])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(0, 0, 1))

    def testVerticalSketchAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 10
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Pad]
        self.PolarPattern.Axis = (self.PadSketch, ["V_Axis"])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(0, 1, 0))

    def testHorizontalSketchAxisPolarPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 10
        self.Doc.recompute()
        self.PolarPattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.PolarPattern.Originals = [self.Pad]
        self.PolarPattern.Axis = (self.PadSketch, ["H_Axis"])
        self.PolarPattern.Angle = 360
        self.PolarPattern.Occurrences = 4
        self.PolarPattern.Refine = False
        self.Body.addObject(self.PolarPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(1, 0, 0))

    def checkPattern(self, original, axis):
        """The instances on the unrefined result, then the names of the refined one. Angle 360
        and 4 occurrences put the instances 90 degrees apart about the axis through the origin,
        one per quadrant."""
        pattern = self.PolarPattern
        placements = [
            FreeCAD.Placement(FreeCAD.Vector(), FreeCAD.Rotation(axis, 90.0 * k)) for k in range(4)
        ]
        with self.subTest("unrefined"):
            harness.assertEveryElementNamed(pattern.Shape)
            harness.assertInstancesDistinct(pattern.Shape, original.Shape, placements)
        pattern.Refine = True
        self.Doc.recompute()
        self.assertAlmostEqual(pattern.Shape.Volume, 4000)
        harness.assertEveryElementNamed(pattern.Shape)
        harness.assertDistinctNames(pattern.Shape)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPolarPattern")
        # print ("omit closing document for debugging")


class TestPolarPatternOverlappingCuts(unittest.TestCase):
    """FreeCAD-CH ops#901: a polar pattern of a subtractive loft whose copies overlap their
    neighbours in a small wedge. Each loft ends "Normal to profile", so two neighbours' top faces
    are tangent at the corner and cross at well under a degree; OCCT 8.0.1 finds no curve for that
    crossing, and the one cut over all copies leaves an open shell that checkResult() refuses
    (fork-1.0.2: Invalid, "a shell's faces are not oriented consistently"). Onshape builds such a
    pattern, so the expected result is the plate less the union of the 8 cutouts. All dimensions
    are chosen here (notes/polar-pattern-901.md section 5)."""

    plate = 40.0
    thickness = 10.0
    copies = 8

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPolarPatternOverlappingCuts")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def rectangle(self, name, placement, x0, x1, y0, y1):
        sketch = self.Doc.addObject("Sketcher::SketchObject", name)
        self.body.addObject(sketch)
        sketch.MapMode = "Deactivated"
        sketch.Placement = placement
        corners = [
            FreeCAD.Vector(x0, y0, 0),
            FreeCAD.Vector(x1, y0, 0),
            FreeCAD.Vector(x1, y1, 0),
            FreeCAD.Vector(x0, y1, 0),
        ]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        return sketch

    def makeModel(self, halfWidth):
        """Plate 40 x 40 x 10 on the origin; a loft cutout from a section 3 outside the wall
        (x -6..6, z 1..9 at y = -23) to one inside (x -halfWidth..halfWidth, z 1..4 at y = -6),
        its inner end normal to the profile; 8 copies about the plate's axis. The 8-gon's half
        side at the inner end is 6 tan(22.5 deg) = 2.485: a wider inner end overlaps its
        neighbours."""
        self.body = self.Doc.addObject("PartDesign::Body", "Body")
        half = self.plate / 2
        square = self.rectangle("Square", FreeCAD.Placement(), -half, half, -half, half)
        self.pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.body.addObject(self.pad)
        self.pad.Profile = square
        self.pad.Length = self.thickness
        self.pad.Refine = False
        upright = FreeCAD.Rotation(0, 0, 90)
        outer = self.rectangle(
            "Outer", FreeCAD.Placement(FreeCAD.Vector(0, -23, 0), upright), -6, 6, 1, 9
        )
        inner = self.rectangle(
            "Inner",
            FreeCAD.Placement(FreeCAD.Vector(0, -6, 0), upright),
            -halfWidth,
            halfWidth,
            1,
            4,
        )
        self.loft = self.Doc.addObject("PartDesign::SubtractiveLoft", "Loft")
        self.body.addObject(self.loft)
        self.loft.Profile = outer
        self.loft.Sections = [inner]
        self.loft.Ruled = False
        self.loft.EndCondition = "Normal to profile"
        self.loft.Refine = False
        self.Doc.recompute()
        self.assertTrue(self.loft.isValid(), self.loft.getStatusString())
        # Set up before it joins the body (added the other way round it stays Touched)
        self.pattern = self.Doc.addObject("PartDesign::PolarPattern", "PolarPattern")
        self.pattern.Originals = [self.loft]
        self.pattern.Axis = (square, ["N_Axis"])
        self.pattern.Angle = 360
        self.pattern.Occurrences = self.copies
        self.pattern.Refine = False
        self.body.addObject(self.pattern)
        self.Doc.recompute()

    def removedByEachCopy(self):
        """The volume each of the 8 cutouts removes from the plate on its own (a single cut,
        which OCCT gets right): the diagonal ones reach less far past the square's wall"""
        plate = self.pad.Shape
        tool = self.loft.AddSubShape
        removed = []
        for k in range(self.copies):
            copy = tool.copy()
            copy.rotate(FreeCAD.Vector(), FreeCAD.Vector(0, 0, 1), 360.0 / self.copies * k)
            removed.append(plate.Volume - plate.cut(copy).Volume)
        return removed

    def assertSoundPattern(self, overlaps):
        """One valid solid centred on the axis (the square plate and the 8 copies share a
        quarter turn) that removed the union of the 8 cutouts: the sum of what each removes
        alone where they don't overlap; where they do, less than the sum (each wedge is removed
        once) by far less than one cutout"""
        shape = self.pattern.Shape
        self.assertTrue(self.pattern.isValid(), self.pattern.getStatusString())
        self.assertEqual(len(shape.Solids), 1)
        self.assertTrue(shape.isValid())
        centre = shape.Solids[0].CenterOfMass
        self.assertAlmostEqual(centre.x / self.plate, 0, places=7)
        self.assertAlmostEqual(centre.y / self.plate, 0, places=7)
        each = self.removedByEachCopy()
        removed = self.pad.Shape.Volume - shape.Volume
        if not overlaps:
            self.assertAlmostEqual(removed / sum(each), 1, places=7)
        else:
            self.assertLess(removed, sum(each))
            self.assertGreater(removed, sum(each) - 0.05 * min(each))

    def testOverlappingCopiesAreCut(self):
        for halfWidth in (2.6, 2.7, 2.8):
            with self.subTest(halfWidth=halfWidth):
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestPolarPatternOverlappingCuts")
                self.makeModel(halfWidth)
                self.assertSoundPattern(overlaps=True)
                harness.assertEveryElementNamed(self.pattern.Shape)
                harness.assertDistinctNames(self.pattern.Shape)

    def testCopiesApartAreCut(self):
        """The control: copies apart from each other (inner half width 2.0) build today"""
        self.makeModel(2.0)
        self.assertSoundPattern(overlaps=False)
