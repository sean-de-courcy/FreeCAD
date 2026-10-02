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
import TestSketcherApp
from PartDesignTests.Scenarios import harness


class TestLinearPattern(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestLinearPattern")

    def testXAxisLinearPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.LinearPattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        self.LinearPattern.Originals = [self.Box]
        self.LinearPattern.Direction = (self.Doc.X_Axis, [""])
        self.LinearPattern.Length = 90.0
        self.LinearPattern.Occurrences = 10
        self.LinearPattern.Refine = False
        self.Body.addObject(self.LinearPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(1, 0, 0))

    def testYAxisLinearPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.LinearPattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        self.LinearPattern.Originals = [self.Box]
        self.LinearPattern.Direction = (self.Doc.Y_Axis, [""])
        self.LinearPattern.Length = 90.0
        self.LinearPattern.Occurrences = 10
        self.LinearPattern.Refine = False
        self.Body.addObject(self.LinearPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(0, 1, 0))

    def testZAxisLinearPattern(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.LinearPattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        self.LinearPattern.Originals = [self.Box]
        self.LinearPattern.Direction = (self.Doc.Z_Axis, [""])
        self.LinearPattern.Length = 90.0
        self.LinearPattern.Occurrences = 10
        self.LinearPattern.Refine = False
        self.Body.addObject(self.LinearPattern)
        self.Doc.recompute()
        self.checkPattern(self.Box, FreeCAD.Vector(0, 0, 1))

    def testNormalSketchAxisLinearPattern(self):
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
        self.LinearPattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        self.LinearPattern.Originals = [self.Pad]
        self.LinearPattern.Direction = (self.PadSketch, ["N_Axis"])
        self.LinearPattern.Length = 90.0
        self.LinearPattern.Occurrences = 10
        self.LinearPattern.Refine = False
        self.Body.addObject(self.LinearPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(0, 0, 1))

    def testVerticalSketchAxisLinearPattern(self):
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
        self.LinearPattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        self.LinearPattern.Originals = [self.Pad]
        self.LinearPattern.Direction = (self.PadSketch, ["V_Axis"])
        self.LinearPattern.Length = 90.0
        self.LinearPattern.Occurrences = 10
        self.LinearPattern.Refine = False
        self.Body.addObject(self.LinearPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(0, 1, 0))

    def testHorizontalSketchAxisLinearPattern(self):
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
        self.LinearPattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        self.LinearPattern.Originals = [self.Pad]
        self.LinearPattern.Direction = (self.PadSketch, ["H_Axis"])
        self.LinearPattern.Length = 90.0
        self.LinearPattern.Occurrences = 10
        self.LinearPattern.Refine = False
        self.Body.addObject(self.LinearPattern)
        self.Doc.recompute()
        self.checkPattern(self.Pad, FreeCAD.Vector(1, 0, 0))

    def checkPattern(self, original, direction):
        """The instances on the unrefined result, then the names of the refined one. Length 90
        and 10 occurrences put the instances 10 apart along the direction, touching."""
        pattern = self.LinearPattern
        placements = [
            FreeCAD.Placement(direction * (10.0 * k), FreeCAD.Rotation()) for k in range(10)
        ]
        with self.subTest("unrefined"):
            harness.assertEveryElementNamed(pattern.Shape)
            harness.assertInstancesDistinct(pattern.Shape, original.Shape, placements)
        pattern.Refine = True
        self.Doc.recompute()
        self.assertAlmostEqual(pattern.Shape.Volume, 1e4)
        harness.assertEveryElementNamed(pattern.Shape)
        harness.assertDistinctNames(pattern.Shape)

    def testInstanceNumbersPerDirection(self):
        """V2 numbers the instances of a LinearPattern with a second direction per direction
        (ops#6): block (i, j) is `i:j`, so an edit of either count leaves every other block's
        number alone. With one occurrence along Direction2 the numbers are those of a plain
        pattern."""
        if hasattr(self.Doc, "HistoryAlgorithm"):
            self.Doc.HistoryAlgorithm = "V2"
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        pattern = self.Doc.addObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [box]
        pattern.Direction = (self.Doc.X_Axis, [""])
        pattern.Mode = "Spacing"
        pattern.Offset = 30
        pattern.Direction2 = (self.Doc.Y_Axis, [""])
        pattern.Mode2 = "Spacing"
        pattern.Spacings2 = []  # a new pattern's is [0.0], a gap of 0 (ops#93)
        pattern.Offset2 = 30
        pattern.Refine = False
        body.addObject(pattern)
        for xCount, yCount in ((3, 2), (2, 2), (3, 2), (3, 1), (3, 2), (1, 2), (3, 2)):
            pattern.Occurrences = xCount
            pattern.Occurrences2 = yCount
            self.Doc.recompute()
            self.assertEqual(
                harness.topFaceInstances(pattern.Shape, 10),
                harness.gridInstances(xCount, yCount, 30, 10),
                f"Occurrences {xCount}, Occurrences2 {yCount}",
            )

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestLinearPattern")
        # print ("omit closing document for debugging")
