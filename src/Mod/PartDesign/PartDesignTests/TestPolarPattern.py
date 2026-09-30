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
