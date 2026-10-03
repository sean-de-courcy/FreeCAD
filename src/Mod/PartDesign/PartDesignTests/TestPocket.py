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


class TestPocket(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPocket")

    def testPocketDimensionCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "PadSketch")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Pad.Reversed = 1
        self.Doc.recompute()
        self.PocketSketch = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch)
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch, (2.5, 2.5), (5, 5))
        self.Doc.recompute()
        self.Pocket = self.Doc.addObject("PartDesign::Pocket", "Pocket")
        self.Body.addObject(self.Pocket)
        self.Pocket.Profile = self.PocketSketch
        self.Pocket.Length = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pocket.Shape.Volume, 75.0)

    def testStartOffset(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "PadSketch")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Pad.Reversed = 1
        self.Doc.recompute()

        self.PocketSketch = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch)
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch, (2.5, 2.5), (5, 5))
        self.Doc.recompute()
        self.Pocket = self.Doc.addObject("PartDesign::Pocket", "Pocket")
        self.Body.addObject(self.Pocket)
        self.Pocket.Profile = self.PocketSketch
        self.Pocket.StartType = "Offset"
        self.Pocket.StartOffset = 0.5
        self.Pocket.Length = 0.25
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pocket.Shape.Volume, 93.75)

    def testPocketThroughAllCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "PadSketch")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Pad.Reversed = 1
        self.Doc.recompute()
        self.PocketSketch = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch)
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch, (2.5, 2.5), (5, 5))
        self.Doc.recompute()
        self.Pocket = self.Doc.addObject("PartDesign::Pocket", "Pocket")
        self.Body.addObject(self.Pocket)
        self.Pocket.Profile = self.PocketSketch
        self.Pocket.Length = 1
        self.Doc.recompute()
        self.PocketSketch1 = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch1)
        self.PocketSketch1.MapMode = "FlatFace"
        self.PocketSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch1, (2.5, -0.75), (5, 0.50))
        self.Doc.recompute()
        self.Pocket001 = self.Doc.addObject("PartDesign::Pocket", "Pocket001")
        self.Body.addObject(self.Pocket001)
        self.Pocket001.Profile = self.PocketSketch1
        self.Pocket001.Type = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pocket001.Shape.Volume, 62.5)

    def testPocketToFirstCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "PadSketch")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Pad.Reversed = 1
        self.Doc.recompute()
        self.PocketSketch = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch)
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch, (2.5, 2.5), (5, 5))
        self.Doc.recompute()
        self.Pocket = self.Doc.addObject("PartDesign::Pocket", "Pocket")
        self.Body.addObject(self.Pocket)
        self.Pocket.Profile = self.PocketSketch
        self.Pocket.Length = 1
        self.Doc.recompute()
        self.PocketSketch1 = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch1)
        self.PocketSketch1.MapMode = "FlatFace"
        self.PocketSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch1, (2.5, -1), (5, 1))
        self.Doc.recompute()
        self.Pocket001 = self.Doc.addObject("PartDesign::Pocket", "Pocket001")
        self.Body.addObject(self.Pocket001)
        self.Pocket001.Profile = self.PocketSketch1
        self.Pocket001.Type = 2
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pocket001.Shape.Volume, 62.5)

    def testPocketToFaceCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "PadSketch")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (10, 10))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Pad.Reversed = 1
        self.Doc.recompute()
        self.PocketSketch = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch)
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch, (2.5, 2.5), (5, 5))
        self.Doc.recompute()
        self.Pocket = self.Doc.addObject("PartDesign::Pocket", "Pocket")
        self.Body.addObject(self.Pocket)
        self.Pocket.Profile = self.PocketSketch
        self.Pocket.Length = 1
        self.Doc.recompute()
        self.PocketSketch1 = self.Doc.addObject("Sketcher::SketchObject", "PocketSketch")
        self.Body.addObject(self.PocketSketch1)
        self.PocketSketch1.MapMode = "FlatFace"
        self.PocketSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PocketSketch1, (0, -1), (10, 1))
        self.Doc.recompute()
        self.Pocket001 = self.Doc.addObject("PartDesign::Pocket", "Pocket001")
        self.Body.addObject(self.Pocket001)
        self.Pocket001.Profile = self.PocketSketch1
        self.Pocket001.Type = 3
        # Handle face-naming inconsistency in OCC < 7
        self.FaceNumber = 7
        self.Pocket001.UpToFace = (self.Pocket, ["Face" + str(self.FaceNumber)])
        self.Doc.recompute()
        while (
            "Invalid" in self.Pocket001.State or round(self.Pocket001.Shape.Volume, 7) != 50.0
        ) and self.FaceNumber < 11:
            self.FaceNumber += 1
            self.Pocket001.UpToFace = (self.Pocket, ["Face" + str(self.FaceNumber)])
            self.Doc.recompute()
        self.assertAlmostEqual(self.Pocket001.Shape.Volume, 50.0)

    def testTwoSidedPocketUpToFaceBehindSide(self):
        """ops#73: a side of a two-sided Pocket whose up-to face lies behind it is an error naming
        that side. It used to be turned around silently, and the XOR of the sides then cancelled
        the overlap: a valid Pocket that removes nothing, or the wrong part."""
        # A 20 x 20 x 20 block, z -10..10, and a 5 x 5 square on XY centred on the origin.
        # Side 1 cuts towards -z, side 2 towards +z. Above: plane z = 10 (Face5 of a box at
        # z 10..15). Below: plane z = -10 (Face6 of a box at z -15..-10).
        top = self.Doc.addObject("Part::Box", "Above")
        top.Placement.Base = FreeCAD.Vector(-5, -5, 10)
        bottom = self.Doc.addObject("Part::Box", "Below")
        bottom.Placement.Base = FreeCAD.Vector(-5, -5, -15)
        for box in (top, bottom):
            box.Length, box.Width, box.Height = 10, 10, 5

        def pocket(side1, side2):
            body = self.Doc.addObject("PartDesign::Body", "Body")
            block = self.Doc.addObject("PartDesign::AdditiveBox", "Block")
            body.addObject(block)
            block.Length = block.Width = block.Height = 20
            block.Placement.Base = FreeCAD.Vector(-10, -10, -10)
            sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
            body.addObject(sketch)
            TestSketcherApp.CreateRectangleSketch(sketch, (-2.5, -2.5), (5, 5))
            self.Doc.recompute()
            feature = self.Doc.addObject("PartDesign::Pocket", "Pocket")
            body.addObject(feature)
            feature.Profile = sketch
            feature.SideType = "Two sides"
            for typeProp, lengthProp, faceProp, (kind, arg) in (
                ("Type", "Length", "UpToFace", side1),
                ("Type2", "Length2", "UpToFace2", side2),
            ):
                setattr(feature, typeProp, kind)
                if kind == "Length":
                    setattr(feature, lengthProp, arg)
                else:
                    setattr(feature, faceProp, (arg[0], [arg[1]]))
            self.Doc.recompute()
            return feature

        above = ("UpToFace", (top, "Face5"))
        below = ("UpToFace", (bottom, "Face6"))
        with self.subTest("control: each face ahead of its side"):
            control = pocket(below, above)
            self.assertTrue(control.isValid(), control.getStatusString())
            self.assertAlmostEqual(control.Shape.Volume, 8000 - 25 * 20, places=4)
        for name, side1, side2 in (
            ("both down to the face below (two prisms)", below, below),
            ("side 1 by length, side 2 to the face below (one prism)", ("Length", 5.0), below),
        ):
            with self.subTest(name):
                feature = pocket(side1, side2)
                self.assertFalse(feature.isValid())
                self.assertIn("Side 2 can't reach its face", feature.getStatusString())

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPocket")
        # print ("omit closing document for debugging")
