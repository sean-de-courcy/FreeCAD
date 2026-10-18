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

    def testPocketUpToLinkOfTwoFaces(self):
        """ops#304: an up-to link naming two faces (the planes z = -5 and z = -8 of one box) is
        an error. The Pocket went down to the first face named alone, with no error: z = -8 for
        [Face5, Face6], past the nearer face z = -5. One face still works."""
        faces = self.Doc.addObject("Part::Box", "Faces")
        faces.Placement.Base = FreeCAD.Vector(-5, -5, -8)
        faces.Length, faces.Width, faces.Height = 10, 10, 3
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = self.Doc.addObject("PartDesign::AdditiveBox", "Block")
        body.addObject(block)
        block.Length = block.Width = block.Height = 20
        block.Placement.Base = FreeCAD.Vector(-10, -10, -10)
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        body.addObject(sketch)
        TestSketcherApp.CreateRectangleSketch(sketch, (-2.5, -2.5), (5, 5))
        self.Doc.recompute()
        pocket = self.Doc.addObject("PartDesign::Pocket", "Pocket")
        body.addObject(pocket)
        pocket.Profile = sketch
        pocket.Type = "UpToFace"
        pocket.UpToFace = (faces, ["Face6"])
        self.Doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(pocket.Shape.Volume, 8000 - 25 * 5, places=6)
        for names in (["Face5", "Face6"], ["Face6", "Face5"]):
            with self.subTest(faces=names):
                pocket.UpToFace = (faces, names)
                self.Doc.recompute()
                self.assertFalse(pocket.isValid())
                self.assertIn("names several faces", pocket.getStatusString())

    def testPocketUpToFaceLeavesTheBaseAlone(self):
        # ops#347: the up-to face is the base's, and BRepFeat raised it in place. The square is
        # outside the loft, so the pocket removes nothing
        from PartDesignTests.TestPad import LOFT_VOLUME_DELTA, upToTheLoftSide

        base, pocket = upToTheLoftSide(self, self.Doc, "Pocket")
        self.assertTrue(pocket.Shape.isValid())
        self.assertAlmostEqual(pocket.Shape.Volume, base.Shape.Volume, delta=LOFT_VOLUME_DELTA)
        self.assertAlmostEqual(base.Shape.common(pocket.AddSubShape).Volume, 0, places=6)

    def testRefinedPocketLeavesTheBaseAlone(self):
        # ops#354: the 4 x 4 square at x = 22 (y -2..2, z 5..9), outside the loft, and a Pocket
        # up to the loft's side: the cut removes nothing and splits the side. Refine tried to
        # merge the pieces back on the base's own circle and ellipse, and added a curve on surface
        # to them at every recompute (1, 2, 3, ...), in the base feature's stored shape and the
        # Part::Feature's. Refine runs on a copy now: both keep their edges, curve for curve and
        # in their saved text. Refine off is the control
        from PartDesignTests.TestPad import (
            LOFT_VOLUME_DELTA,
            assertBasesKept,
            squareUpToTheLoft,
            toleranceState,
        )

        for refine in (True, False):
            with self.subTest(refine=refine):
                doc = FreeCAD.newDocument("PartDesignTestPocketRefine")
                try:
                    base, pocket = squareUpToTheLoft(doc, "Pocket", 22, 5, 9, refine=refine)
                    self.assertTrue(pocket.isValid(), pocket.getStatusString())
                    loft = doc.getObject("Loft")
                    # The base as it was made: one curve on surface on the circle and the
                    # ellipse, two on the seam
                    for obj in (loft, base):
                        self.assertEqual(toleranceState(obj.Shape)[3], [1, 2, 1], obj.Name)
                    held = [
                        (o.Name, o.Shape, toleranceState(o.Shape), o.Shape.exportBrepToString())
                        for o in (loft, base)
                    ]
                    for _ in range(2):
                        pocket.touch()
                        doc.recompute()
                        self.assertTrue(pocket.isValid(), pocket.getStatusString())
                    assertBasesKept(self, [h[:3] for h in held])
                    for name, shape, _, text in held:
                        self.assertTrue(shape.exportBrepToString() == text, name)
                    self.assertAlmostEqual(
                        pocket.Shape.Volume, base.Shape.Volume, delta=LOFT_VOLUME_DELTA
                    )
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPocketUpToALoftedFace(self):
        # ops#353: BRepFeat gave an empty prism up to the loft's B-spline side, and the Pocket
        # was valid and removed nothing. The square is inside the loft, in the plane x = 0: the
        # Pocket removes what lies between it and the side (the loft is symmetric about x = 0,
        # so the same either way)
        from PartDesignTests.TestPad import (
            LOFT_VOLUME_DELTA,
            PRISM_VOLUME_RELATIVE,
            loftSideReach,
            squareUpToTheLoft,
        )

        expected = loftSideReach(0, -2, 2, 5, 9)
        base, pocket = squareUpToTheLoft(self.Doc, "Pocket", 0, 5, 9, False)
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertTrue(pocket.Shape.isValid())
        self.assertEqual(len(pocket.Shape.Solids), 1)
        self.assertAlmostEqual(
            pocket.AddSubShape.Volume, expected, delta=PRISM_VOLUME_RELATIVE * expected
        )
        self.assertAlmostEqual(
            pocket.Shape.Volume, base.Shape.Volume - expected, delta=LOFT_VOLUME_DELTA
        )

    def testPocketUpToALoftedFaceWhoseRimIsInTheWay(self):
        # ops#353 review H1: TestPad's tilted rectangle as a Pocket. The split's solid ran from
        # the rectangle through the near side's patch to the far side, and the Pocket cut the
        # loft's inside between its two sides. It fails, saying why
        from PartDesignTests.TestPad import squareUpToTheLoft

        base, pocket = squareUpToTheLoft(
            self.Doc, "Pocket", 22, 14.5, 17.5, False, FreeCAD.Vector(-1, 0, -0.15)
        )
        self.assertFalse(pocket.isValid())
        self.assertIn("lies in the profile's way", pocket.getStatusString())

    def testPocketUpToABaseWithNames(self):
        """ops#347, review of fork PR 321: a Pocket that cuts through the base, up to its far
        face, keeps the base's names and has the topology of the box less the hole."""
        from PartDesignTests.TestPad import tabOnNamedBase

        tabOnNamedBase(self, self.Doc, "Pocket", "UpToFace")

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPocket")
        # print ("omit closing document for debugging")
