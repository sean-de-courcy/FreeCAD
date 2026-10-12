# SPDX-License-Identifier: LGPL-2.1-or-later
"""Cross-Body traps (FreeCAD-CH ops#308, from the ops#305 probes): features and binders that use
another Body's geometry. Each was silent-wrong; each now comes out right or fails loudly.
Designed geometry, geometric oracles (volumes, solid counts, bounding boxes)."""

import unittest

import FreeCAD
import Part
import Sketcher

V = FreeCAD.Vector


def rectangle(sketch, x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    first = len(sketch.Geometry)
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1)
        )


class TestCrossBody(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("PartDesignTestCrossBody")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def body(self, name, at=V(0, 0, 0)):
        body = self.doc.addObject("PartDesign::Body", name)
        body.Placement.Base = at
        return body

    def sketch(self, body, name, support, *rects):
        sketch = body.newObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = support
        sketch.MapMode = "FlatFace"
        for rect in rects:
            rectangle(sketch, *rect)
        return sketch

    def onXY(self, body):
        return [(body.Origin.OriginFeatures[3], "")]

    def pad(self, body, name, sketch, length):
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = sketch
        pad.Length = length
        return pad

    def topFace(self, feature, z):
        [name] = [
            f"Face{i}"
            for i, f in enumerate(feature.Shape.Faces, 1)
            if abs(f.normalAt(0, 0).z - 1) < 1e-9 and abs(f.CenterOfMass.z - z) < 1e-6
        ]
        return name

    def plate(self, name="Plate", at=V(0, 0, 0)):
        """A Body with a pad 20 x 10 x 5 from its XY plane; returns the Body and the pad."""
        body = self.body(name, at)
        pad = self.pad(body, name + "Pad", self.sketch(body, name + "Sk", self.onXY(body),
                                                       (0, 0, 20, 10)), 5)
        self.doc.recompute()
        return body, pad

    def assertBox(self, shape, xmin, ymin, zmin, xmax, ymax, zmax):
        box = shape.BoundBox
        for got, expected in zip(
            (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax),
            (xmin, ymin, zmin, xmax, ymax, zmax),
        ):
            self.assertAlmostEqual(got, expected, places=6)

    # T1 ------------------------------------------------------------------------------------

    def testFirstPadOnAFaceOfAnotherBodyTakesNoBase(self):
        """T1: a Body's first Pad, on a sketch attached to the top of a pad in another Body,
        takes no base: its Body is the pad's 6 x 6 x 3 alone. It took the other pad as its base
        and came out as both (1000 + 108)."""
        _, source = self.plate()
        body = self.body("Body")
        sketch = self.sketch(body, "Sk", [(source, self.topFace(source, 5))], (2, 2, 8, 8))
        pad = self.pad(body, "Pad", sketch, 3)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertIsNone(pad.BaseFeature)
        self.assertEqual(len(body.Shape.Solids), 1)
        self.assertAlmostEqual(body.Shape.Volume, 108, places=6)
        self.assertBox(body.Shape, 2, 2, 5, 8, 8, 8)

    def testFirstPadOfAFaceOfAnotherBodyTakesNoBase(self):
        """T1, the other path: a Body's first Pad whose Profile is the top face of a pad in
        another Body takes no base: its Body is the face padded 3 up, 20 x 10 x 3. It took the
        face's owner as its base and came out as both."""
        _, source = self.plate()
        body = self.body("Body")
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = (source, [self.topFace(source, 5)])
        pad.Length = 3
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertIsNone(pad.BaseFeature)
        self.assertEqual(len(body.Shape.Solids), 1)
        self.assertAlmostEqual(body.Shape.Volume, 600, places=6)
        self.assertBox(body.Shape, 0, 0, 5, 20, 10, 8)

    def testPadWithNoBaseOnAFaceOfItsOwnBodyKeepsIt(self):
        """T1, kept for legacy files: a Pad with no BaseFeature, on a sketch attached to a face of
        a feature of its own Body, still starts from that feature."""
        body, source = self.plate()
        sketch = self.sketch(body, "Sk", [(source, self.topFace(source, 5))], (2, 2, 8, 8))
        pad = self.pad(body, "Pad", sketch, 3)
        pad.BaseFeature = None
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 1000 + 108, places=6)

    # T2 ------------------------------------------------------------------------------------

    def interleaved(self, viaBody):
        """Body1's pad, Body2's pad on its top through a binder, then a binder of Body2's pad's
        bottom in Body1: bound to the features, or through their Bodies (as the binder command
        stored a 3D pick in another Body)."""
        body1, padA = self.plate("Body1")
        body2 = self.body("Body2")
        top = self.topFace(padA, 5)
        bindTop = body2.newObject("PartDesign::SubShapeBinder", "BindTop")
        bindTop.Support = [(body1, ("%s.%s" % (padA.Name, top),))] if viaBody else [(padA, (top,))]
        padB = self.pad(body2, "PadB", self.sketch(body2, "SkB", [(bindTop, "Face1")],
                                                   (2, 2, 8, 8)), 3)
        self.doc.recompute()
        [bottom] = [
            f"Face{i}"
            for i, f in enumerate(padB.Shape.Faces, 1)
            if abs(f.normalAt(0, 0).z + 1) < 1e-9 and abs(f.CenterOfMass.z - 5) < 1e-6
        ]
        bindB = body1.newObject("PartDesign::SubShapeBinder", "BindB")
        bindB.Support = (
            [(body2, ("%s.%s" % (padB.Name, bottom),))] if viaBody else [(padB, (bottom,))]
        )
        self.doc.recompute()
        return bindTop, bindB

    def testBindersOfFeaturesInEachOthersBodiesSettle(self):
        """T2: binders of features in each other's Bodies make no cycle: the next recompute
        has nothing to do."""
        bindTop, bindB = self.interleaved(viaBody=False)
        self.assertEqual(self.doc.recompute(), 0)
        self.assertTrue(bindTop.isValid() and bindB.isValid())
        self.assertAlmostEqual(bindB.Shape.Area, 36, places=6)

    def testBindersThroughEachOthersBodiesFailAsACycle(self):
        """T2: bound through the Bodies, each Body depends on the other's binder: a cycle. It
        failed nothing and left objects touched after every recompute; both binders now fail on
        every recompute and say why. Bound to the feature instead, one binder breaks the cycle,
        and everything settles."""
        bindTop, bindB = self.interleaved(viaBody=True)
        for _ in range(2):
            self.doc.recompute()
            for binder in (bindTop, bindB):
                self.assertFalse(binder.isValid())
                self.assertIn("Cyclic dependency", binder.getStatusString())
            # The cycle has no order, so its objects stay touched; each carries an error (a
            # Body shows none of its own: its Tip, PadB, has one)
            for obj in self.doc.Objects:
                if "Touched" in obj.State and obj.TypeId != "PartDesign::Body":
                    self.assertFalse(obj.isValid(), obj.Name)
        padA = self.doc.getObject("Body1Pad")
        bindTop.Support = [(padA, (self.topFace(padA, 5),))]
        self.doc.recompute()
        self.assertEqual(self.doc.recompute(), 0)
        for obj in self.doc.Objects:
            self.assertTrue(obj.isValid(), "%s: %s" % (obj.Name, obj.getStatusString()))
        self.assertAlmostEqual(bindB.Shape.Area, 36, places=6)

    # T3 ------------------------------------------------------------------------------------

    def twoSolidsAndACommon(self, length):
        body = self.body("Body")
        self.pad(body, "TwoPads", self.sketch(body, "Sk", self.onXY(body), (0, 0, 5, 5),
                                              (10, 0, 15, 5)), 5)
        common = body.newObject("PartDesign::SubtractiveBox", "Keep")
        common.Length = length
        common.Width = common.Height = 3
        common.Operation = "Common"
        self.doc.recompute()
        self.assertTrue(common.isValid(), common.getStatusString())
        return common

    def testCommonThatRemovesAWholeSolidWarns(self):
        """T3: a subtractive Common over one of a Body's two solids keeps 3 x 3 x 3 of it and
        removes the other whole: a warning says so. It was silent."""
        common = self.twoSolidsAndACommon(3)
        self.assertEqual(len(common.Shape.Solids), 1)
        self.assertAlmostEqual(common.Shape.Volume, 27, places=6)
        self.assertIn("Warning", common.State)

    def testCommonOverEverySolidDoesNotWarn(self):
        """T3: a Common over both solids removes no solid whole: no warning."""
        common = self.twoSolidsAndACommon(15)
        self.assertEqual(len(common.Shape.Solids), 2)
        self.assertAlmostEqual(common.Shape.Volume, 2 * 45, places=6)
        self.assertNotIn("Warning", common.State)

    # T4 ------------------------------------------------------------------------------------

    def testBinderFollowsItsSourceBodysPlacement(self):
        """T4: a binder of the top of a box whose Body sits at (100, 50) lies on the box, and
        follows it when that Body moves; a lid padded on it sits on the box. The binder stayed
        at the origin, and the lid with it in height. (A FlatFace sketch's origin is the Lid's
        origin projected onto the face, so the lid's rectangle is in the Lid's coordinates.)"""
        box = self.body("Box", V(100, 50, 0))
        boxPad = self.pad(box, "BoxPad", self.sketch(box, "BoxSk", self.onXY(box),
                                                     (0, 0, 40, 40)), 10)
        self.doc.recompute()
        lid = self.body("Lid")
        binder = lid.newObject("PartDesign::SubShapeBinder", "BoxTop")
        binder.Support = [(boxPad, (self.topFace(boxPad, 10),))]
        self.pad(lid, "LidPad", self.sketch(lid, "LidSk", [(binder, "Face1")],
                                            (105, 55, 135, 85)), 5)
        self.doc.recompute()
        self.assertBox(binder.Shape, 100, 50, 10, 140, 90, 10)
        self.assertAlmostEqual(lid.Shape.Volume, 4500, places=6)
        self.assertBox(lid.Shape, 105, 55, 10, 135, 85, 15)
        box.Placement.Base = V(102, 52, 3)
        self.doc.recompute()
        self.assertBox(binder.Shape, 102, 52, 13, 142, 92, 13)
        self.assertBox(lid.Shape, 105, 55, 13, 135, 85, 18)

    def stackedHole(self, upperAt):
        lower = self.body("Lower")
        self.pad(lower, "LowerPad", self.sketch(lower, "LowSk", self.onXY(lower),
                                                (0, 0, 40, 40)), 10)
        upper = self.body("Upper", upperAt)
        self.pad(upper, "UpperPad", self.sketch(upper, "UpSk", self.onXY(upper),
                                                (0, 0, 40, 40)), 5)
        holeSketch = self.sketch(upper, "HoleSk", self.onXY(upper), (18, 18, 22, 22))
        self.doc.recompute()
        pocket = lower.newObject("PartDesign::Pocket", "HoleLower")
        pocket.Profile = holeSketch
        pocket.Type = "ThroughAll"
        pocket.Midplane = True
        self.doc.recompute()
        return upper, pocket

    def testProfileInABodyPlacedElsewhereFails(self):
        """T4: a Pocket in one Body on a sketch of another Body placed at (5, 0, 10): the
        sketch is read in its own Body's coordinates, so the hole was cut 5 mm off, silently.
        The Pocket now fails and says why; with the Bodies placed alike it cuts the hole."""
        upper, pocket = self.stackedHole(V(5, 0, 10))
        self.assertFalse(pocket.isValid())
        self.assertIn("placed elsewhere", pocket.getStatusString())
        upper.Placement.Base = V(0, 0, 0)
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(pocket.Shape.Volume, 16000 - 160, places=6)

    def testPadOnASketchAttachedInABodyPlacedElsewhereFails(self):
        """T4: a Pad on a sketch attached to the top of a pad in another Body placed at
        (100, 50): the attachment reads that face in its own Body's coordinates, so the Pad sat
        at the origin, silently. The Pad now fails and says why."""
        _, source = self.plate(at=V(100, 50, 0))
        body = self.body("Body")
        sketch = self.sketch(body, "Sk", [(source, self.topFace(source, 5))], (2, 2, 8, 8))
        pad = self.pad(body, "Pad", sketch, 3)
        self.doc.recompute()
        self.assertFalse(pad.isValid())
        self.assertIn("placed elsewhere", pad.getStatusString())

    # T5 ------------------------------------------------------------------------------------

    def placedFeatures(self):
        """Body A at (30, 0, 0): a 10 mm AdditiveBox at (5, 5, 5), then a Pad 5 up from a sketch
        30 above the XY plane. Both features carry a Placement of their own."""
        a = self.body("A", V(30, 0, 0))
        box = a.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        box.Placement = FreeCAD.Placement(V(5, 5, 5), FreeCAD.Rotation())
        sketch = self.sketch(a, "Sk", self.onXY(a), (0, 0, 10, 10))
        sketch.AttachmentOffset = FreeCAD.Placement(V(0, 0, 30), FreeCAD.Rotation())
        pad = self.pad(a, "Pad", sketch, 5)
        self.doc.recompute()
        return a, box, pad

    def testBodyBasedOnAPlacedFeatureOfAnotherBodyStaysInPlace(self):
        """T5: a Body at (100, 0, 0) whose BaseFeature is the box, then one whose BaseFeature is
        the Pad: each copy sits where its feature is in the document. The feature's own
        Placement was applied twice: shifted by (5, 5, 5)."""
        a, box, pad = self.placedFeatures()
        self.assertBox(box.Shape.transformed(a.Placement.toMatrix()), 35, 5, 5, 45, 15, 15)
        for feature, expected in ((box, (35, 5, 5, 45, 15, 15)), (pad, (30, 0, 5, 45, 15, 35))):
            body = self.body("From" + feature.Name, V(100, 0, 0))
            body.BaseFeature = feature
            self.doc.recompute()
            self.assertTrue(body.Group[0].isValid(), body.Group[0].getStatusString())
            self.assertBox(body.Shape, *expected)


if __name__ == "__main__":
    unittest.main()
