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

    def testPadOnASketchAttachedInABodyPlacedElsewhere(self):
        """T4: a Pad on a sketch attached to the top of a pad in another Body placed at
        (100, 50): the attachment read that face in its own Body's coordinates, so the Pad sat
        at the origin, silently, and then failed here. The attachment now maps the face
        (ops#318): the Pad stands on it, from the support's origin."""
        _, source = self.plate(at=V(100, 50, 0))
        body = self.body("Body")
        sketch = self.sketch(body, "Sk", [(source, self.topFace(source, 5))], (2, 2, 8, 8))
        pad = self.pad(body, "Pad", sketch, 3)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertBox(pad.Shape, 102, 52, 5, 108, 58, 8)

    def boxAndBinder(self, inLid=True):
        """A box Body at (100, 50) padded 40 x 40 x 10, and a binder of the pad's top: in a Lid
        Body at the origin, or at the document's top level."""
        box = self.body("Box", V(100, 50, 0))
        boxPad = self.pad(box, "BoxPad", self.sketch(box, "BoxSk", self.onXY(box),
                                                     (0, 0, 40, 40)), 10)
        self.doc.recompute()
        if inLid:
            binder = self.body("Lid").newObject("PartDesign::SubShapeBinder", "BoxTop")
        else:
            binder = self.doc.addObject("PartDesign::SubShapeBinder", "BoxTop")
        binder.Support = [(boxPad, (self.topFace(boxPad, 10),))]
        return box, binder

    def assertBinderFollowsTheBox(self, box, binder):
        self.doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertBox(binder.Shape, 100, 50, 10, 140, 90, 10)
        box.Placement.Base = V(-20, 0, 3)
        self.doc.recompute()
        self.assertBox(binder.Shape, -20, 0, 13, 20, 40, 13)

    def testTopLevelBinderFollowsItsSourceBodysPlacement(self):
        """F1: a binder at the document's top level, of a face of a feature in a Body at
        (100, 50), lies on the box and follows it. It lay at the origin: with no parent to
        resolve the path from, no container placement applied."""
        self.assertBinderFollowsTheBox(*self.boxAndBinder(inLid=False))

    def testAbsoluteBinderFollowsItsSourceBodysPlacement(self):
        """F4: a binder with Relative off, in the Lid, lies on the box and follows it. It lay at
        the origin: with Relative off, the face's own placement was dropped too."""
        box, binder = self.boxAndBinder()
        binder.Relative = False
        self.assertBinderFollowsTheBox(box, binder)

    def assertGlobalBox(self, obj, *box):
        """obj's shape, in the document's coordinates, has this bounding box."""
        shape = obj.Shape.copy()
        container = obj.getParentGeoFeatureGroup()
        if container:
            shape = shape.transformed(container.getGlobalPlacement().toMatrix())
        self.assertBox(shape, *box)

    def bindersInAnotherDocument(self, folder):
        """A box Body at (100, 50) padded 40 x 40 x 10 in a second document, both documents
        saved in folder, and four binders of the pad's top in this one: at the top level with
        Relative on and off, and in a Lid Body at (0, 0, 20) with Relative on and off. Returns
        the second document and the binders."""
        import os

        other = FreeCAD.newDocument("PartDesignTestCrossBodyOther")
        box = other.addObject("PartDesign::Body", "Box")
        box.Placement.Base = V(100, 50, 0)
        boxPad = self.pad(box, "BoxPad", self.sketch(box, "BoxSk", self.onXY(box),
                                                     (0, 0, 40, 40)), 10)
        other.recompute()
        other.saveAs(os.path.join(folder, "CrossBodyOther.FCStd"))
        self.doc.saveAs(os.path.join(folder, "CrossBodyMain.FCStd"))
        lid = self.body("Lid", V(0, 0, 20))
        face = self.topFace(boxPad, 10)
        binders = []
        for container, relative in ((None, True), (None, False), (lid, True), (lid, False)):
            if container:
                binder = container.newObject("PartDesign::SubShapeBinder", "BoxTop")
            else:
                binder = self.doc.addObject("PartDesign::SubShapeBinder", "BoxTop")
            binder.Support = [(boxPad, (face,))]
            binder.Relative = relative
            binders.append(binder)
        self.doc.recompute()
        for binder in binders:
            self.assertTrue(binder.isValid(), binder.getStatusString())
            self.assertGlobalBox(binder, 100, 50, 10, 140, 90, 10)
        return other, binders

    def closeIfOpen(self, name):
        if name in FreeCAD.listDocuments():
            FreeCAD.closeDocument(name)

    def testBinderFollowsABodyInAnotherDocument(self):
        """R2-1: binders (bindersInAnotherDocument) of a face of a Body in another document
        follow that Body to the origin once both documents recompute, and the next recompute
        has nothing to do. They stayed at (100, 50): only the binder's own document was heard
        when a support's Body recomputed."""
        import tempfile

        other, binders = self.bindersInAnotherDocument(tempfile.mkdtemp())
        try:
            other.getObject("Box").Placement.Base = V(0, 0, 0)
            other.recompute()
            self.doc.recompute()
            for binder in binders:
                self.assertTrue(binder.isValid(), binder.getStatusString())
                self.assertGlobalBox(binder, 0, 0, 10, 40, 40, 10)
            self.assertEqual(self.doc.recompute(), 0)
        finally:
            self.closeIfOpen(other.Name)

    def testBinderFollowsABodyMovedInAnotherDocumentWhileClosed(self):
        """R2-1: the Body of bindersInAnotherDocument moves while this document is closed, and
        its document stays open. This document, reopened and recomputed, puts its binders on
        the moved Body; they stayed at (100, 50), since nothing touched them. (When reopening
        this document opens the other, the binders already follow.)"""
        import os
        import tempfile

        folder = tempfile.mkdtemp()
        other, _ = self.bindersInAnotherDocument(folder)
        try:
            self.doc.save()
            FreeCAD.closeDocument(self.doc.Name)
            other.getObject("Box").Placement.Base = V(0, 0, 0)
            other.recompute()
            self.doc = FreeCAD.openDocument(os.path.join(folder, "CrossBodyMain.FCStd"))
            self.doc.recompute()
            binders = [o for o in self.doc.Objects if o.isDerivedFrom("PartDesign::SubShapeBinder")]
            self.assertEqual(len(binders), 4)
            for binder in binders:
                self.assertTrue(binder.isValid(), binder.getStatusString())
                self.assertGlobalBox(binder, 0, 0, 10, 40, 40, 10)
            self.assertEqual(self.doc.recompute(), 0)
        finally:
            self.closeIfOpen(other.Name)

    def freezeAndChangeTheBox(self, box, boxPad, binders, docs):
        """Freezes the binders, pads the box to 15 and moves its Body by (5, 0, 0); the binders
        stay on the box's old top, (100, 50, 10)-(140, 90, 10) in the document."""
        for binder in binders:
            binder.BindMode = "Frozen"
        for doc in docs:
            doc.recompute()
        boxPad.Length = 15
        for doc in docs:
            doc.recompute()
        box.Placement.Base = box.Placement.Base + V(5, 0, 0)
        for doc in docs:
            doc.recompute()
        for binder in binders:
            self.assertGlobalBox(binder, 100, 50, 10, 140, 90, 10)

    def testFrozenBinderStaysWhenItsSourceChangesAndMoves(self):
        """r3 F1: Frozen binders of the box's top, in a Lid and at the top level, keep their
        shape when the box is padded higher and its Body moves. Since round 1 they took the new
        top at z 15, moved, as soon as the box's Body recomputed."""
        box, inLid = self.boxAndBinder()
        topLevel = self.doc.addObject("PartDesign::SubShapeBinder", "BoxTopLevel")
        topLevel.Support = inLid.Support
        self.doc.recompute()
        self.freezeAndChangeTheBox(box, self.doc.getObject("BoxPad"), [inLid, topLevel], [self.doc])

    def testFrozenBinderOfABodyInAnotherDocumentStays(self):
        """r3 F1: the same for the four binders of bindersInAnotherDocument."""
        import tempfile

        other, binders = self.bindersInAnotherDocument(tempfile.mkdtemp())
        try:
            self.freezeAndChangeTheBox(other.getObject("Box"), other.getObject("BoxPad"), binders,
                                       [other, self.doc])
        finally:
            self.closeIfOpen(other.Name)

    def testUnchangedBindersReopenWithNothingToDo(self):
        """r3 F2: binders of a face of a Body at a placement with many digits (at the top level
        with Relative on and off, in a turned Lid with Relative on and off), saved after a
        recompute and reopened: the document has nothing to recompute. Some reran: the saved
        matrices differ from recomputed ones in the 15th digit, and were compared exactly."""
        import os
        import tempfile

        rotation = FreeCAD.Rotation(V(0, 0, 1), 17.3)
        box = self.body("Box", V(100.1234567, 50.7654321, 3.3333333))
        box.Placement.Rotation = rotation
        boxPad = self.pad(box, "BoxPad", self.sketch(box, "BoxSk", self.onXY(box),
                                                     (0.3, 0.7, 40.1, 40.9)), 10.01)
        self.doc.recompute()
        lid = self.body("Lid", V(0.7, 1.9, 20.1))
        lid.Placement.Rotation = FreeCAD.Rotation(V(0.2, 0.1, 1), 11.1)
        face = self.topFace(boxPad, 10.01)
        for container, relative in ((None, True), (None, False), (lid, True), (lid, False)):
            if container:
                binder = container.newObject("PartDesign::SubShapeBinder", "BoxTop")
            else:
                binder = self.doc.addObject("PartDesign::SubShapeBinder", "BoxTop")
            binder.Support = [(boxPad, (face,))]
            binder.Relative = relative
        self.doc.recompute()
        self.assertEqual(self.doc.recompute(), 0)
        path = os.path.join(tempfile.mkdtemp(), "CrossBodyDigits.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        self.assertFalse(self.doc.mustExecute())
        self.assertEqual(self.doc.recompute(), 0)

    def upper(self, at=V(0, 0, 50)):
        """Upper, a Body at z 50 with a pad 20 x 10 x 15; Lower, a Body at the origin with a pad
        20 x 10 x 5. Returns Upper, its pad, Lower and its pad."""
        upper = self.body("Upper", at)
        upperPad = self.pad(upper, "UpperPad", self.sketch(upper, "UpSk", self.onXY(upper),
                                                           (0, 0, 20, 10)), 15)
        lower = self.body("Lower")
        lowerPad = self.pad(lower, "LowerPad", self.sketch(lower, "LowSk", self.onXY(lower),
                                                           (0, 0, 20, 10)), 5)
        self.doc.recompute()
        return upper, upperPad, lower, lowerPad

    def assertFailsUntilTheBodiesAgree(self, upper, feature, check):
        """The feature fails while Upper is placed elsewhere; with Upper at the origin, check()
        holds on it."""
        self.doc.recompute()
        self.assertFalse(feature.isValid())
        self.assertIn("placed elsewhere", feature.getStatusString())
        upper.Placement.Base = V(0, 0, 0)
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        check(feature.Shape)

    def padUpTo(self, kind):
        """A Pad in Lower, up to the top of Upper's pad (kind: UpToFace or UpToShape): it stopped
        at z 15, where that top would be in Lower, silently. It now fails; with the Bodies placed
        alike it stops at z 15."""
        upper, upperPad, lower, lowerPad = self.upper()
        sketch = self.sketch(lower, "UpSk", [(lowerPad, self.topFace(lowerPad, 5))], (2, 2, 6, 6))
        pad = self.pad(lower, "UpTo", sketch, 1)
        pad.Type = kind
        setattr(pad, kind, (upperPad, [self.topFace(upperPad, 15)]))
        self.assertFailsUntilTheBodiesAgree(
            upper, pad, lambda shape: self.assertAlmostEqual(shape.BoundBox.ZMax, 15, places=6))

    def testPadUpToAFaceOfABodyPlacedElsewhereFails(self):
        """F2: UpToFace (padUpTo)."""
        self.padUpTo("UpToFace")

    def testPadUpToAShapeOfABodyPlacedElsewhereFails(self):
        """F2: UpToShape (padUpTo)."""
        self.padUpTo("UpToShape")

    def testLoftToASectionInABodyPlacedElsewhereFails(self):
        """F2: a Loft in Lower to a section sketched 20 above Upper's XY plane, Upper at z 50,
        reached z 20, silently. It now fails; with the Bodies placed alike it reaches z 20."""
        upper = self.body("Upper", V(0, 0, 50))
        section = self.sketch(upper, "Section", self.onXY(upper), (0, 0, 10, 10))
        section.AttachmentOffset = FreeCAD.Placement(V(0, 0, 20), FreeCAD.Rotation())
        lower = self.body("Lower")
        loft = lower.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = self.sketch(lower, "Base", self.onXY(lower), (0, 0, 10, 10))
        loft.Sections = [section]
        self.assertFailsUntilTheBodiesAgree(
            upper, loft, lambda shape: self.assertAlmostEqual(shape.Volume, 2000, places=6))

    def testPipeAlongASpineInABodyPlacedElsewhereFails(self):
        """F2: a Pipe in Lower along a spine sketched in Upper, Upper at z 50, ran from z 0 to
        30, silently. It now fails; with the Bodies placed alike it runs from z 0 to 30."""
        upper = self.body("Upper", V(0, 0, 50))
        spine = upper.newObject("Sketcher::SketchObject", "Spine")
        spine.AttachmentSupport = [(upper.Origin.OriginFeatures[4], "")]
        spine.MapMode = "FlatFace"
        spine.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 30, 0)))
        lower = self.body("Lower")
        pipe = lower.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.sketch(lower, "Prof", self.onXY(lower), (-2, -2, 2, 2))
        pipe.Spine = (spine, ["Edge1"])
        self.assertFailsUntilTheBodiesAgree(
            upper, pipe, lambda shape: self.assertBox(shape, -2, -2, 0, 2, 2, 30))

    def testProfileElsewhereClearsAfterReopening(self):
        """F5: the Pocket's error, saved and reopened, clears once the Bodies agree. It stuck:
        nothing touched the Pocket in the reopened file."""
        import os
        import tempfile

        upper, pocket = self.stackedHole(V(5, 0, 10))
        self.assertFalse(pocket.isValid())
        path = os.path.join(tempfile.mkdtemp(), "elsewhere.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)
        self.doc.getObject("Upper").Placement.Base = V(0, 0, 0)
        self.doc.recompute()
        pocket = self.doc.getObject("HoleLower")
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(pocket.Shape.Volume, 16000 - 160, places=6)

    def testSuppressedFeatureWithAProfileElsewhereSettles(self):
        """F6: a suppressed Pocket whose profile is in a Body placed elsewhere doesn't fail, and
        the next recompute has nothing to do. It was run on every recompute."""
        upper, pocket = self.stackedHole(V(5, 0, 10))
        pocket.Suppressed = True
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertEqual(self.doc.recompute(), 0)

    def testFeatureWithAProfileElsewhereSettles(self):
        """R2-2: a Pocket whose profile is in a Body placed elsewhere fails, and the next
        recompute has nothing to do while the Bodies stay apart. It was run on every recompute."""
        upper, pocket = self.stackedHole(V(5, 0, 10))
        self.assertFalse(pocket.isValid())
        self.assertEqual(self.doc.recompute(), 0)
        self.assertFalse(pocket.isValid())
        self.assertIn("placed elsewhere", pocket.getStatusString())

    def testFeatureFailingOnAProfileInAnotherBodySettles(self):
        """R2-2: a Pad of length zero on a sketch in another Body placed alike fails for its own
        reason, and the next recompute has nothing to do. Any failed feature that read another
        Body was run on every recompute."""
        source = self.body("Source")
        sketch = self.sketch(source, "Sk", self.onXY(source), (0, 0, 5, 5))
        pad = self.pad(self.body("Body"), "Pad", sketch, 0)
        self.doc.recompute()
        self.assertFalse(pad.isValid())
        self.assertNotIn("placed elsewhere", pad.getStatusString())
        self.assertEqual(self.doc.recompute(), 0)

    def testFirstSubtractiveFeatureFails(self):
        """F8: a Body's first Pocket, with nothing to cut, returned its tool as material (a first
        Pocket on another Body's face does since T1). It now fails and says why. A first
        subtractive box already failed, with its own message."""
        body = self.body("Body")
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.sketch(body, "Sk", self.onXY(body), (2, 2, 6, 6))
        pocket.Length = 2
        self.doc.recompute()
        self.assertFalse(pocket.isValid())
        self.assertIn("Nothing to cut", pocket.getStatusString())
        other = self.body("Other")
        box = other.newObject("PartDesign::SubtractiveBox", "Box")
        self.doc.recompute()
        self.assertFalse(box.isValid())
        self.assertIn("without base feature", box.getStatusString())

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

    # ops#322: the copy follows its source ----------------------------------------------------

    def touched(self):
        return [o.Name for o in self.doc.Objects if "Touched" in o.State]

    def basedOnBox(self):
        """placedFeatures(), and Body B at (100, 0, 0) based on its box: the copy at x 35..45."""
        a, box, pad = self.placedFeatures()
        b = self.body("B", V(100, 0, 0))
        b.BaseFeature = box
        self.doc.recompute()
        self.assertBox(b.Shape, 35, 5, 5, 45, 15, 15)
        return a, box, b

    def reopen(self, name):
        """Saves the document in a temporary folder (removed after the test) and reopens it."""
        import os
        import shutil
        import tempfile

        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, name)
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        self.doc = FreeCAD.openDocument(path)

    def assertSameVertices(self, shape, other, tolerance=1e-6):
        """Every vertex of `shape` within `tolerance` of the vertex of `other` nearest to it."""
        points = [v.Point for v in other.Vertexes]
        self.assertEqual(len(shape.Vertexes), len(points))
        for vertex in shape.Vertexes:
            nearest = min((vertex.Point - p).Length for p in points)
            self.assertLess(nearest, tolerance, vertex.Point)

    def testBaseFeatureCopyFollowsItsSourceBody(self):
        """ops#322: Body A moved by +10 in x, then put back at (30, 0, 0) turned 90 degrees about
        z: each plain recompute moves the copy with the box (turned, the box's x 5..15 and y 5..15
        go to x 30-15..30-5, y 5..15). Nothing is left to recompute."""
        a, box, b = self.basedOnBox()
        a.Placement.Base = V(40, 0, 0)
        self.doc.recompute()
        self.assertBox(b.Shape, 45, 5, 5, 55, 15, 15)
        self.assertEqual(self.touched(), [])
        a.Placement = FreeCAD.Placement(V(30, 0, 0), FreeCAD.Rotation(V(0, 0, 1), 90))
        self.doc.recompute()
        self.assertBox(b.Shape, 15, 5, 5, 25, 15, 15)
        self.assertEqual(self.doc.recompute(), 0)

    def testBaseFeatureCopyMovesWithItsOwnBody(self):
        """ops#322, PLAN decision 82: B holds a 10 mm AdditiveBox at (-60, 10, 10) on the copy (x
        40..50, y 10..20, z 10..20). B moved by +50 in x, then turned 90 degrees about z there: the
        copy and the box move with B as one piece. Then A moved by +10 in y: the copy follows A's
        move, by +10 in y."""
        a, box, b = self.basedOnBox()
        extra = b.newObject("PartDesign::AdditiveBox", "Extra")
        extra.Length = extra.Width = extra.Height = 10
        extra.Placement.Base = V(-60, 10, 10)
        self.doc.recompute()
        copy = lambda: b.Group[0].Shape.transformed(b.Placement.toMatrix())
        self.assertBox(b.Shape, 35, 5, 5, 50, 20, 20)
        b.Placement.Base = V(150, 0, 0)
        self.doc.recompute()
        self.assertBox(copy(), 85, 5, 5, 95, 15, 15)
        self.assertBox(b.Shape, 85, 5, 5, 100, 20, 20)
        b.Placement = FreeCAD.Placement(V(150, 0, 0), FreeCAD.Rotation(V(0, 0, 1), 90))
        self.doc.recompute()
        self.assertBox(copy(), 135, -65, 5, 145, -55, 15)
        self.assertBox(b.Shape, 130, -65, 5, 145, -50, 20)
        a.Placement.Base = V(30, 10, 0)
        self.doc.recompute()
        self.assertBox(copy(), 135, -55, 5, 145, -45, 15)
        self.assertBox(b.Shape, 130, -60, 5, 145, -45, 20)
        self.assertEqual(self.doc.recompute(), 0)

    def testBaseFeatureCopyFollowsAMoveByAnExpression(self):
        """ops#322 with ops#342's container moves: A's x set by an expression on a VarSet; after
        each change of the variable one recompute moves the copy and leaves nothing touched."""
        a, box, b = self.basedOnBox()
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyDistance", "X")
        variables.X = 30
        a.setExpression(".Placement.Base.x", "Variables.X")
        self.doc.recompute()
        self.assertBox(b.Shape, 35, 5, 5, 45, 15, 15)
        for x in (50, -20):
            with self.subTest(x=x):
                variables.X = x
                self.doc.recompute()
                self.assertBox(b.Shape, x + 5, 5, 5, x + 15, 15, 15)
                self.assertEqual(self.touched(), [])

    def testBaseFeatureCopyFollowsUndoAndRedo(self):
        """ops#322: a move of A by +10 in x, undone and redone, each followed by a recompute: the
        copy is at x 35..45, then 45..55."""
        self.doc.UndoMode = 1
        a, box, b = self.basedOnBox()
        self.doc.openTransaction("move")
        a.Placement.Base = V(40, 0, 0)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertBox(b.Shape, 45, 5, 5, 55, 15, 15)
        for step, x in ((self.doc.undo, 35), (self.doc.redo, 45)):
            with self.subTest(step=step.__name__):
                step()
                self.doc.recompute()
                self.assertBox(b.Shape, x, 5, 5, x + 10, 15, 15)
                self.assertEqual(self.doc.recompute(), 0)

    def testBaseFeatureCopyFollowsAfterAReopen(self):
        """ops#322: A moved by +10 in x, saved and reopened: the copy is at x 45..55 and nothing
        needs a recompute. A moved back by -20 after the reopen: the copy follows, to 25..35."""
        a, box, b = self.basedOnBox()
        a.Placement.Base = V(40, 0, 0)
        self.doc.recompute()
        self.reopen("CrossBodyBaseFeature.FCStd")
        a, b = self.doc.getObject("A"), self.doc.getObject("B")
        self.assertBox(b.Shape, 45, 5, 5, 55, 15, 15)
        self.assertFalse(self.doc.mustExecute())
        self.assertEqual(self.doc.recompute(), 0)
        a.Placement.Base = V(20, 0, 0)
        self.doc.recompute()
        self.assertBox(b.Shape, 25, 5, 5, 35, 15, 15)

    def testHandPlacedBaseFeatureKeepsItsOffsetToTheSource(self):
        """ops#322: a FeatureBase added by hand, Placement (5, 0, 0), copies a 10 mm Part box at
        x 20 to x 5..15 (the box's own placement left out). The box moved to x 30: the copy keeps
        its offset, at 15..25. Then based on a second box at x 60: the copy doesn't jump."""
        box = self.doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 10
        box.Placement.Base = V(20, 0, 0)
        b = self.body("B")
        base = self.doc.addObject("PartDesign::FeatureBase", "BaseFeature")
        b.addObject(base)
        base.BaseFeature = box
        base.Placement.Base = V(5, 0, 0)
        self.doc.recompute()
        self.assertBox(b.Shape, 5, 0, 0, 15, 10, 10)
        box.Placement.Base = V(30, 0, 0)
        self.doc.recompute()
        self.assertBox(b.Shape, 15, 0, 0, 25, 10, 10)
        other = self.doc.addObject("Part::Box", "Other")
        other.Length = other.Width = other.Height = 10
        other.Placement.Base = V(60, 0, 0)
        base.BaseFeature = other
        self.doc.recompute()
        self.assertBox(b.Shape, 15, 0, 0, 25, 10, 10)


    def testBaseFeatureCopyFollowsASmallTurn(self):
        """ops#322 review round 1: the box 1000 mm from A's origin, A turned 0.01 degrees about z:
        the box's far corner moves 0.17 mm, and the copy's vertices stay on the box's to 1e-6.
        A frame comparison by Placement.isSame took turns below 0.036 degrees as no move."""
        a = self.body("A")
        box = a.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = box.Width = box.Height = 10
        box.Placement.Base = V(1000, 0, 0)
        b = self.body("B", V(100, 0, 0))
        b.BaseFeature = box
        self.doc.recompute()
        a.Placement.Rotation = FreeCAD.Rotation(V(0, 0, 1), 0.01)
        self.doc.recompute()
        self.assertSameVertices(b.Shape, box.Shape.transformed(a.Placement.toMatrix()))

    def testBaseFeatureCopyFollowsMovedParts(self):
        """ops#322 review round 1, PLAN decision 82: A in App::Part PA, B put in App::Part PB at
        (0, 50, 0), which moves B and the copy by +50 in y. PA moved by +10 in x: the copy follows,
        x 45..55. PB moved by +10 in x: the copy moves with B, x 55..65."""
        a, box, b = self.basedOnBox()
        partA = self.doc.addObject("App::Part", "PA")
        partA.addObject(a)
        partB = self.doc.addObject("App::Part", "PB")
        partB.Placement.Base = V(0, 50, 0)
        partB.addObject(b)
        self.doc.recompute()
        copy = lambda: b.Shape.transformed(partB.Placement.toMatrix())
        self.assertBox(copy(), 35, 55, 5, 45, 65, 15)
        partA.Placement.Base = V(10, 0, 0)
        self.doc.recompute()
        self.assertBox(copy(), 45, 55, 5, 55, 65, 15)
        partB.Placement.Base = V(10, 50, 0)
        self.doc.recompute()
        self.assertBox(copy(), 55, 55, 5, 65, 65, 15)
        self.assertEqual(self.doc.recompute(), 0)

    def testBaseFeatureCopyStaysWithAPartHoldingBoth(self):
        """ops#322, PLAN decision 82: A and B in one App::Part, turned 90 degrees about z: both
        Bodies turn, and the copy stays on the box (box and copy at x -15..-5, y 35..45)."""
        a, box, b = self.basedOnBox()
        part = self.doc.addObject("App::Part", "Both")
        part.addObject(a)
        part.addObject(b)
        part.Placement.Rotation = FreeCAD.Rotation(V(0, 0, 1), 90)
        self.doc.recompute()
        self.assertBox(b.Shape.transformed(part.Placement.toMatrix()), -15, 35, 5, -5, 45, 15)
        self.assertEqual(self.doc.recompute(), 0)

    def testBaseFeatureCopyOfABodyFollowsIt(self):
        """ops#322 review round 1: B based on Body A itself (its box at x 35..45 and its Pad,
        x 30..40, z 30..35): A moved by +10 in x moves the whole copy, x 40..55."""
        a, box, pad = self.placedFeatures()
        b = self.body("B", V(100, 0, 0))
        b.BaseFeature = a
        self.doc.recompute()
        self.assertBox(b.Shape, 30, 0, 5, 45, 15, 35)
        a.Placement.Base = V(40, 0, 0)
        self.doc.recompute()
        self.assertBox(b.Shape, 40, 0, 5, 55, 15, 35)

    def testHandPlacedBaseFeatureTurnsWithItsSource(self):
        """ops#322 review round 1: a FeatureBase added by hand, Placement (5, 0, 0), on a 10 mm Part
        box at x 20: the copy is 15 mm along -x from the box. The box turned 90 degrees about z
        (at x 20, now over x 10..20, y 0..10): the offset turns with it, to 15 mm along -y."""
        box = self.doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 10
        box.Placement.Base = V(20, 0, 0)
        b = self.body("B")
        base = self.doc.addObject("PartDesign::FeatureBase", "BaseFeature")
        b.addObject(base)
        base.BaseFeature = box
        base.Placement.Base = V(5, 0, 0)
        self.doc.recompute()
        self.assertBox(b.Shape, 5, 0, 0, 15, 10, 10)
        box.Placement.Rotation = FreeCAD.Rotation(V(0, 0, 1), 90)
        self.doc.recompute()
        self.assertBox(box.Shape, 10, 0, 0, 20, 10, 10)
        self.assertBox(b.Shape, 10, -15, 0, 20, -5, 10)

    def testTurnedBaseFeatureCopyReopensUnmoved(self):
        """ops#322 review round 1: A and B placed with turns about skew axes and many digits,
        saved and reopened: nothing needs a recompute, and a recompute moves nothing."""
        a, box, pad = self.placedFeatures()
        a.Placement = FreeCAD.Placement(V(30.1234567, 1.7654321, 3.3333333),
                                        FreeCAD.Rotation(V(0.2, 0.1, 1), 17.3))
        b = self.body("B", V(100.7, 1.9, 20.1))
        b.Placement.Rotation = FreeCAD.Rotation(V(1, 0.3, 0.2), 11.1)
        b.BaseFeature = box
        self.doc.recompute()
        expected = b.Shape.copy()
        self.reopen("CrossBodyBaseFeatureTurned.FCStd")
        b = self.doc.getObject("B")
        self.assertFalse(self.doc.mustExecute())
        self.assertEqual(self.doc.recompute(), 0)
        self.assertSameVertices(b.Shape, expected, 1e-9)

    def testBaseFeatureCopyMovesWithItsOwnBodyByAnExpression(self):
        """ops#322, PLAN decision 82: B's x set by an expression on a VarSet; changed from 100 to
        130, one recompute moves the copy with B, to x 65..75, with nothing touched."""
        a, box, b = self.basedOnBox()
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyDistance", "X")
        variables.X = 100
        b.setExpression(".Placement.Base.x", "Variables.X")
        self.doc.recompute()
        variables.X = 130
        self.doc.recompute()
        self.assertBox(b.Shape, 65, 5, 5, 75, 15, 15)
        self.assertEqual(self.touched(), [])

if __name__ == "__main__":
    unittest.main()
