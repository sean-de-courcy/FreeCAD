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

    def testPocketUpToABallUnderAPlateOfElementaryFaces(self):
        # ops#361: the block x, y -9..9, z -15..5 with a cavity shaped as TestPad's ball under a
        # plate (planes and spheres only, so the Pocket goes by BRepFeat), and a Pocket from the
        # square x, y -6..6 on its bottom, along +z, up to the cavity's ball below the plate and
        # the plate's bottom. BRepFeat cut away the material in the band's shadow (0.00105): a
        # valid Pocket. It fails, saying why. The control, the square x, y -1..1, stops at the
        # ball's bottom and leaves the shadow alone
        import Part
        from PartDesignTests.TestPad import (
            PRISM_VOLUME_RELATIVE,
            ballAndPlateBottom,
            ballBandShadow,
            ballBottomReach,
            squareSketch,
        )

        V = FreeCAD.Vector
        cavity = Part.makeBox(16, 16, 2, V(-8, -8, 0)).fuse(Part.makeSphere(5, V(0, 0, -0.1)))
        mold = Part.makeBox(18, 18, 20, V(-9, -9, -15)).cut(cavity.removeSplitter())
        for half in (1, 6):
            with self.subTest(half=half):
                doc = FreeCAD.newDocument("PocketUpToABallUnderAPlateOfElementaryFaces")
                try:
                    base = doc.addObject("Part::Feature", "Base")
                    base.Shape = mold
                    body = doc.addObject("PartDesign::Body", "Body")
                    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
                    baseFeature.BaseFeature = base
                    doc.recompute()
                    placement = FreeCAD.Placement(V(0, 0, -15), FreeCAD.Rotation())
                    sketch = squareSketch(body, "Square", placement, [(-half, -half, half, half)])
                    pocket = body.newObject("PartDesign::Pocket", "Pocket")
                    pocket.Profile = sketch
                    pocket.Type = "UpToShape"
                    pocket.UpToShape = [(baseFeature, ballAndPlateBottom(baseFeature.Shape))]
                    pocket.Reversed = True
                    doc.recompute()
                    if half == 1:
                        self.assertTrue(pocket.isValid(), pocket.getStatusString())
                        expected = ballBottomReach(1)
                        self.assertAlmostEqual(
                            mold.Volume - pocket.Shape.Volume,
                            expected,
                            delta=PRISM_VOLUME_RELATIVE * expected,
                        )
                        shadow = ballBandShadow()
                        self.assertAlmostEqual(
                            pocket.Shape.common(shadow).Volume, shadow.Volume, places=9
                        )
                    else:
                        self.assertFalse(pocket.isValid())
                        self.assertIn("meets the face from behind", pocket.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPocketUpToATunnelOfElementaryFaces(self):
        # ops#450 (fork PR 359 review, finding 1): the block x, y, z -10..10 with a tunnel of
        # radius 5 about the x axis, and a Pocket from the square x, y -3..3 on its top, down to
        # the tunnel's (concave) cylinder face. It removes the material from the top down to the
        # tunnel's roof, z = sqrt(25 - y^2): 6 (60 - integral of sqrt(25 - y^2) over y -3..3) =
        # 6 (48 - 25 asin(0.6)), 191.47. BRepFeat removed nothing: a valid Pocket. fillsBehind()
        # sends it to the split, which builds it right
        import math
        import Part
        from PartDesignTests.TestPad import PRISM_VOLUME_RELATIVE, squareSketch

        V = FreeCAD.Vector
        block = Part.makeBox(20, 20, 20, V(-10, -10, -10)).cut(
            Part.makeCylinder(5, 20, V(-10, 0, 0), V(1, 0, 0))
        )
        doc = FreeCAD.newDocument("PocketUpToATunnelOfElementaryFaces")
        try:
            base = doc.addObject("Part::Feature", "Base")
            base.Shape = block
            body = doc.addObject("PartDesign::Body", "Body")
            baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
            baseFeature.BaseFeature = base
            doc.recompute()
            names = [
                "Face%d" % i
                for i, face in enumerate(baseFeature.Shape.Faces, 1)
                if face.Surface.TypeId == "Part::GeomCylinder"
            ]
            placement = FreeCAD.Placement(V(0, 0, 10), FreeCAD.Rotation())
            sketch = squareSketch(body, "Square", placement, [(-3, -3, 3, 3)])
            pocket = body.newObject("PartDesign::Pocket", "Pocket")
            pocket.Profile = sketch
            pocket.Type = "UpToFace"
            pocket.UpToFace = (baseFeature, names)
            doc.recompute()
            self.assertTrue(pocket.isValid(), pocket.getStatusString())
            expected = 6 * (48 - 25 * math.asin(0.6))
            self.assertAlmostEqual(
                block.Volume - pocket.Shape.Volume,
                expected,
                delta=PRISM_VOLUME_RELATIVE * expected,
            )
            self.assertEqual(len(pocket.Shape.Solids), 1)
        finally:
            FreeCAD.closeDocument(doc.Name)

    def testPocketUpToABaseWithNames(self):
        """ops#347, review of fork PR 321: a Pocket that cuts through the base, up to its far
        face, keeps the base's names and has the topology of the box less the hole."""
        from PartDesignTests.TestPad import tabOnNamedBase

        tabOnNamedBase(self, self.Doc, "Pocket", "UpToFace")

    def testUpToFaceOffsetBesideTheProfile(self):
        """FreeCAD-CH P3: a Pocket of a 20 x 20 square at z = 0 into the box x, y -15..15, z -20..0,
        up to a smaller face off the square's centre or on it (parallel at z = -10, or slanted,
        z = -10 + x / 4), offset by +2 and -2, as Onshape does (the Onshape facts U1 and U2): the
        end lies on the face's plane moved `offset` along the extrusion, shallower for +2
        (Onshape's default), deeper for -2. Before, +2 went deeper, and a face off the centre
        line turned the offset round once more."""
        import Part
        from PartDesignTests.TestPad import squareSketch, upToOffsetFace

        V = FreeCAD.Vector
        # span (-2, 2): the face on the square's centre line, (4, 8) off it
        for slanted in (False, True):
            for offset, span in ((2.0, (4, 8)), (-2.0, (4, 8)), (2.0, (-2, 2)), (-2.0, (-2, 2))):
                with self.subTest(slanted=slanted, offset=offset, span=span):
                    face = upToOffsetFace(self.Doc, slanted, -10.0, *span)
                    block = self.Doc.addObject("Part::Feature", "Block")
                    block.Shape = Part.makeBox(30, 30, 20, V(-15, -15, -20))
                    body = self.Doc.addObject("PartDesign::Body", "Body")
                    base = body.newObject("PartDesign::FeatureBase", "BaseFeature")
                    base.BaseFeature = block
                    sketch = squareSketch(body, "Square", FreeCAD.Placement(), [(-10, -10, 10, 10)])
                    pocket = body.newObject("PartDesign::Pocket", "Pocket")
                    pocket.Profile = sketch
                    pocket.Type = "UpToFace"
                    pocket.UpToFace = (face, ["Face1"])
                    pocket.Offset = offset
                    self.Doc.recompute()
                    self.assertTrue(pocket.isValid(), pocket.getStatusString())
                    # the plane's height at x = 0 is -10 (moved up by the offset), and
                    # the slant's x / 4 averages to 0 over the square
                    depth = 10.0 - offset
                    self.assertAlmostEqual(
                        pocket.Shape.Volume, 30 * 30 * 20 - 400.0 * depth, places=4
                    )
                    box = pocket.Shape.BoundBox
                    self.assertAlmostEqual(box.ZMin, -20.0, places=6)
                    self.assertAlmostEqual(box.ZMax, 0.0, places=6)

    def testUpToVertexOffsetSign(self):
        """FreeCAD-CH: a Pocket of a 20 x 20 square at z = 0 into the box x, y -15..15, z -20..0,
        up to a vertex at z = -10, offset by +2 and -2, as Onshape does (oracle 7c, UV1): the end
        on the vertex's plane moved `offset` along the cut, shallower for +2 (short of the vertex),
        deeper for -2. And side 2 (up, in a box z -20..20) up to a vertex at z = 6: 3 deep on
        side 1, `6 - offset` on side 2. Before, +2 went deeper."""
        import Part
        from PartDesignTests.TestPad import squareSketch, upToVertexMarker

        V = FreeCAD.Vector
        for offset in (2.0, -2.0):
            with self.subTest(case="one side", offset=offset):
                block = self.Doc.addObject("Part::Feature", "Block")
                block.Shape = Part.makeBox(30, 30, 20, V(-15, -15, -20))
                marker = upToVertexMarker(self.Doc, -10.0)
                body = self.Doc.addObject("PartDesign::Body", "Body")
                base = body.newObject("PartDesign::FeatureBase", "BaseFeature")
                base.BaseFeature = block
                sketch = squareSketch(body, "Square", FreeCAD.Placement(), [(-10, -10, 10, 10)])
                pocket = body.newObject("PartDesign::Pocket", "Pocket")
                pocket.Profile = sketch
                pocket.Type = "UpToVertex"
                pocket.UpToFace = (marker, ["Vertex1"])
                pocket.Offset = offset
                self.Doc.recompute()
                self.assertTrue(pocket.isValid(), pocket.getStatusString())
                depth = 10.0 - offset
                self.assertAlmostEqual(pocket.Shape.Volume, 30 * 30 * 20 - 400.0 * depth, places=4)
                self.assertFalse(pocket.Shape.isInside(V(0, 0, -depth + 0.5), 1e-6, True))
                self.assertTrue(pocket.Shape.isInside(V(0, 0, -depth - 0.5), 1e-6, True))
                self.Doc.removeObject("Body")
            with self.subTest(case="side 2", offset=offset):
                block = self.Doc.addObject("Part::Feature", "Block")
                block.Shape = Part.makeBox(30, 30, 40, V(-15, -15, -20))
                marker = upToVertexMarker(self.Doc, 6.0)
                body = self.Doc.addObject("PartDesign::Body", "Body")
                base = body.newObject("PartDesign::FeatureBase", "BaseFeature")
                base.BaseFeature = block
                sketch = squareSketch(body, "Square", FreeCAD.Placement(), [(-10, -10, 10, 10)])
                pocket = body.newObject("PartDesign::Pocket", "Pocket")
                pocket.Profile = sketch
                pocket.Type = "Length"
                pocket.Length = 3
                pocket.SideType = "Two sides"
                pocket.Type2 = "UpToVertex"
                pocket.UpToFace2 = (marker, ["Vertex1"])
                pocket.Offset2 = offset
                self.Doc.recompute()
                self.assertTrue(pocket.isValid(), pocket.getStatusString())
                height = 6.0 - offset
                self.assertAlmostEqual(
                    pocket.Shape.Volume, 30 * 30 * 40 - 400.0 * (3.0 + height), places=4
                )
                self.Doc.removeObject("Body")

    def testPocketUpToFaceOfManyRegionsTakesAboutAsLongAsByLength(self):
        """Sweep G5 (ops#640): 196 separate squares pocketed up to a face, with no base of the
        Pocket's own (each square's prism is its own base). The chained fuses grew with the square
        of the regions; now the extra over the Pocket by length is a fraction of its own time."""
        from PartDesignTests.TestPad import C_VOLUME, C_FACES, PIN_GAP, PIN_SIDE, cWithPins, pinSquares

        squares = pinSquares(14)
        found = {}
        for upTo in (False, True):
            _, _, pocket, found[upTo] = cWithPins(self.Doc, squares, kind="Pocket", upTo=upTo)
            self.assertTrue(pocket.isValid(), pocket.getStatusString())
            shape = pocket.Shape
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids), 1)
            self.assertAlmostEqual(
                shape.Volume, C_VOLUME - len(squares) * PIN_SIDE * PIN_SIDE * PIN_GAP, places=4
            )
            self.assertEqual(len(shape.Faces), C_FACES + 4 * len(squares))
            self.Doc.removeObject("Body")
        self.assertLess(found[True], 3 * found[False] + 2.0, found)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPocket")
        # print ("omit closing document for debugging")


class TestRefineKeepsAValidResult(unittest.TestCase):
    """FreeCAD-CH, replica repro (ops#640): Refine must not make a valid result invalid.

    Designed model: a sphere of radius R = 10, made by a Revolution of a semicircle and scaled
    non-uniformly by Part::Scale (z by P / R, P = 16): a spheroid with one B-spline face, the base of a
    second body. A Pocket, Refine on, cuts from the equator's plane (z = 0) the annulus R - W < r < Ro to
    the depth D = 1, W = 1. With Ro = R the tool's outer wall is tangent to the spheroid along its whole
    equator: Refine merges no face, but it rebuilds them all, and the upper spheroid face came out
    invalid ("Unorientable shape") although the unrefined result is valid.

    Expected, for Ro = R and for the non-tangent control Ro = R + 0.5 alike (the spheroid's radius is at
    most R in -D <= z <= 0, so the outer wall cuts nothing): one valid solid, 5 faces (the upper and lower
    spheroid pieces, the annuli at z = 0 and z = -D, the cylinder r = R - W), and
    V = 4/3 pi R^2 P - pi ((R^2 - (R - W)^2) D - R^2 D^3 / (3 P^2))."""

    R, P, W, D = 10.0, 16.0, 1.0, 1.0

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestRefineKeepsAValidResult")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def expectedVolume(self):
        R, P, W, D = self.R, self.P, self.W, self.D
        return 4.0 / 3.0 * math.pi * R * R * P - math.pi * (
            (R * R - (R - W) ** 2) * D - R * R * D**3 / (3 * P * P)
        )

    def build(self, outer):
        doc = self.Doc
        V = FreeCAD.Vector
        R = self.R
        sphereBody = doc.addObject("PartDesign::Body", "SphereBody")
        semi = sphereBody.newObject("Sketcher::SketchObject", "Semicircle")
        semi.MapMode = "Deactivated"
        semi.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), R), 0, math.pi))
        semi.addGeometry(Part.LineSegment(V(-R, 0, 0), V(R, 0, 0)))
        revolution = sphereBody.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = semi
        revolution.ReferenceAxis = (semi, ["Edge2"])
        revolution.Angle = 360
        doc.recompute()
        scale = doc.addObject("Part::Scale", "Scale")
        scale.Base = sphereBody
        scale.Uniform = False
        scale.XScale, scale.YScale, scale.ZScale = 1, 1, self.P / R
        body = doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = scale
        doc.recompute()
        ring = body.newObject("Sketcher::SketchObject", "Ring")
        ring.MapMode = "Deactivated"
        ring.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), outer))
        ring.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), R - self.W))
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = ring
        pocket.Length = self.D
        pocket.Refine = True
        doc.recompute()
        return pocket

    def checkResult(self, pocket):
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        shape = pocket.Shape
        self.assertTrue(shape.isValid(), "Refine left an invalid result")
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(len(shape.Faces), 5)
        expected = self.expectedVolume()
        self.assertLess(abs(shape.Volume - expected), 1e-6 * expected)

    def testTangentPocketStaysValid(self):
        self.checkResult(self.build(self.R))

    def testNonTangentPocketStaysValid(self):
        # The control: passes with or without the fix
        self.checkResult(self.build(self.R + 0.5))
