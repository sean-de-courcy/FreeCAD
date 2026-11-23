# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Delete part (FreeCAD-CH ops#635; notes/part-history-design.md 3.2).

Onshape's Delete part is a feature in the history: the part is gone from its place on, its features
stay, rolling the bar above it or deleting it brings the part back, and later features that use the
deleted part break. Designed geometry: a 10 mm cube (Body), a 6 x 6 x 3 boss on its top face in a
second Body made before the delete, and a third Body's boss on the same face made after it."""

import os
import tempfile
import unittest

import FreeCAD as App
import PartDesign
import Sketcher

from PartDesignTests.TestStudioSequence import faceAt, sketch


class TestDeletePart(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestDeletePart")
        self.doc.UndoMode = 1
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.pad = self.pad_(self.body, "Pad", sketch(self.body, "Sketch", (0, 0, 10, 10)), 10)
        self.doc.recompute()
        self.other = self.doc.addObject("PartDesign::Body", "Other")
        self.boss = self.bossOn(self.other, "Boss")
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=6)
        self.assertAlmostEqual(self.other.Shape.Volume, 108, places=6)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def pad_(self, body, name, profile, length):
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = profile
        pad.Length = length
        return pad

    def bossOn(self, body, name):
        support = [(self.pad, faceAt(self.pad, 10))]
        return self.pad_(body, name, sketch(body, name + "Sketch", (2, 2, 8, 8), support=support), 3)

    def delete(self):
        self.doc.openTransaction("Delete")
        feature = PartDesign.deletePart(self.body)
        self.doc.commitTransaction()
        self.doc.recompute()
        return feature

    def testThePartIsEmptyAndValid(self):
        feature = self.delete()
        self.assertEqual(feature.TypeId, "PartDesign::DeletePart")
        self.assertIs(self.body.Tip, feature)
        self.assertIs(feature.BaseFeature, self.pad)
        self.assertEqual(self.body.Group[-1], feature)
        self.assertTrue(self.body.isValid(), self.body.getStatusString())
        self.assertTrue(self.body.Shape.isNull())
        # Its features stay
        self.assertTrue(self.pad.isValid())
        self.assertAlmostEqual(self.pad.Shape.Volume, 1000, places=6)
        self.assertEqual(PartDesign.studioSequence(self.doc)[-1], feature)

    def testTheBarAboveBringsItBack(self):
        feature = self.delete()
        PartDesign.rollStudioTo(self.doc, self.boss)
        self.doc.recompute()
        # The bar shows the part at its Tip; the rolled-back Body itself is held and keeps its
        # last shape for what reads it (R7, as for any bar move)
        self.assertIs(self.body.Tip, self.pad)
        self.assertTrue(self.body.holds(feature))
        self.assertTrue(self.pad.isValid())
        self.assertAlmostEqual(self.pad.Shape.Volume, 1000, places=6)
        PartDesign.rollStudioToEnd(self.doc)
        self.doc.recompute()
        self.assertIs(self.body.Tip, feature)
        self.assertTrue(self.body.Shape.isNull())

    def testDeletingTheFeatureBringsItBack(self):
        feature = self.delete()
        self.body.removeObject(feature)
        self.doc.removeObject(feature.Name)
        self.doc.recompute()
        self.assertIs(self.body.Tip, self.pad)
        self.assertTrue(self.body.isValid())
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=6)

    def testUndo(self):
        self.delete()
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.doc.findObjects("PartDesign::DeletePart"), [])
        self.assertIs(self.body.Tip, self.pad)
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=6)

    def testASolidAfterItFails(self):
        feature = self.delete()
        later = self.pad_(self.body, "Later", sketch(self.body, "LaterSketch", (0, 0, 3, 3)), 2)
        self.doc.recompute()
        self.assertFalse(later.isValid())
        self.assertIn("was deleted by", later.getStatusString())
        self.assertIn(feature.Label, later.getStatusString())

    def testReferencesBeforeStayAfterBreak(self):
        """Onshape: what was built on the part before the delete stays; a later feature that uses
        it breaks."""
        feature = self.delete()
        self.assertTrue(self.boss.isValid(), self.boss.getStatusString())
        self.assertAlmostEqual(self.other.Shape.Volume, 108, places=6)
        third = self.doc.addObject("PartDesign::Body", "Third")
        late = self.bossOn(third, "LateBoss")
        self.doc.recompute()
        sequence = PartDesign.studioSequence(self.doc)
        self.assertLess(sequence.index(feature), sequence.index(late))
        self.assertFalse(late.isValid())
        self.assertIn("deleted before it", late.getStatusString())
        self.assertIn(self.pad.Label, late.getStatusString())
        # The delete undone: it computes
        self.body.removeObject(feature)
        self.doc.removeObject(feature.Name)
        self.doc.recompute()
        self.assertTrue(late.isValid(), late.getStatusString())

    def lateBoss(self):
        third = self.doc.addObject("PartDesign::Body", "Third")
        late = self.bossOn(third, "LateBoss")
        self.doc.recompute()
        return late

    def testDeletedAtTheBarThenRolledToEnd(self):
        """Reviews prs464e2-r1 (Opus T1, Sonnet T8): deleted at a rolled-back bar, then rolled to the
        end, the Tip is the solid after the Delete part; the part stays deleted."""
        pad2 = self.pad_(self.body, "Pad2", sketch(self.body, "Sketch2", (0, 0, 2, 2), z=10), 1)
        self.doc.recompute()
        PartDesign.rollStudioTo(self.doc, self.pad)
        self.doc.recompute()
        feature = self.delete()
        self.assertEqual([o.Name for o in self.body.Group if o.Name.startswith(("Pad", "Delete"))],
                         ["Pad", feature.Name, "Pad2"])
        PartDesign.rollStudioToEnd(self.doc)
        self.doc.recompute()
        self.assertIs(self.body.Tip, pad2)
        self.assertFalse(pad2.isValid())
        self.assertIn("was deleted by", pad2.getStatusString())
        late = self.lateBoss()
        self.assertFalse(late.isValid())
        self.assertIn("deleted before it", late.getStatusString())

    def testADragAcrossTheReaderRelocks(self):
        """Review prs464e2-r1 (Sonnet T1, T2): the Delete part dragged above a reader of the part
        made before it breaks the reader with no other edit; dragged back, the reader computes."""
        feature = self.delete()
        self.assertTrue(self.boss.isValid())
        PartDesign.moveInStudio(self.doc, [feature], self.pad)
        self.doc.recompute()
        sequence = PartDesign.studioSequence(self.doc)
        self.assertLess(sequence.index(feature), sequence.index(self.boss))
        self.assertFalse(self.boss.isValid())
        self.assertIn("deleted before it", self.boss.getStatusString())
        PartDesign.moveInStudio(self.doc, [feature], self.boss)
        self.doc.recompute()
        self.assertTrue(self.boss.isValid(), self.boss.getStatusString())
        self.assertAlmostEqual(self.other.Shape.Volume, 108, places=6)

    def testALockAfterAValidBaseClears(self):
        """Review prs464e2-r1 (Sonnet T2): a locked feature after a valid solid of its Body runs
        again when the Delete part goes."""
        feature = self.delete()
        third = self.doc.addObject("PartDesign::Body", "Third")
        self.pad_(third, "Base", sketch(third, "BaseSketch", (20, 0, 30, 10)), 2)
        late = self.bossOn(third, "LateBoss")
        self.doc.recompute()
        self.assertFalse(late.isValid())
        self.body.removeObject(feature)
        self.doc.removeObject(feature.Name)
        self.doc.recompute()
        self.assertTrue(late.isValid(), late.getStatusString())

    def testAReaderOfTheWholeBodyFails(self):
        """Review prs464e2-r1 (Sonnet T3): a Boolean whose tool is the deleted Body reads its empty
        end, whenever it was made: it fails, naming the Body."""
        fuse = self.doc.addObject("PartDesign::Boolean", "Fuse")
        self.other.addObject(fuse)
        fuse.setObjects([self.body])
        fuse.Type = 0
        self.doc.recompute()
        self.assertTrue(fuse.isValid(), fuse.getStatusString())
        self.delete()
        self.assertFalse(fuse.isValid())
        self.assertIn("uses the whole of", fuse.getStatusString())

    def testAnOlderSketchKeepsItsReference(self):
        """Review prs464e2-r1 (Opus T5): a Pad made after the delete on a sketch made before it, on
        the deleted part's face, computes (the read is the sketch's, before the delete)."""
        support = [(self.pad, faceAt(self.pad, 10))]
        older = sketch(self.other, "OlderSketch", (3, 3, 7, 7), support=support)
        self.doc.recompute()
        self.delete()
        late = self.pad_(self.other, "LatePad", older, 1)
        self.doc.recompute()
        self.assertTrue(late.isValid(), late.getStatusString())

    def testSuppressedDeletesNothing(self):
        """Review prs464e2-r1 (Sonnet T6, Opus T7): a suppressed Delete part brings the part back."""
        feature = self.delete()
        feature.Suppressed = True
        later = self.pad_(self.body, "Later", sketch(self.body, "LaterSketch", (0, 0, 3, 3), z=10), 2)
        self.doc.recompute()
        self.assertTrue(later.isValid(), later.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 1018, places=6)
        late = self.lateBoss()
        self.assertTrue(late.isValid(), late.getStatusString())

    def testAMergedPartIsRefused(self):
        """Review prs464e2-r1 (Sonnet T7): a part merged into another is gone already."""
        PartDesign.makeMerge(self.boss, [self.body])
        self.doc.recompute()
        with self.assertRaises(ValueError):
            PartDesign.deletePart(self.body)

    def testRefused(self):
        self.delete()
        with self.assertRaises(ValueError):
            PartDesign.deletePart(self.body)
        empty = self.doc.addObject("PartDesign::Body", "Empty")
        with self.assertRaises(ValueError):
            PartDesign.deletePart(empty)
        with self.assertRaises(TypeError):
            PartDesign.deletePart(self.pad)

    def testSavedAndReopened(self):
        self.delete()
        path = os.path.join(tempfile.gettempdir(), "TestDeletePart.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        try:
            body = self.doc.getObject("Body")
            self.assertEqual(body.Tip.TypeId, "PartDesign::DeletePart")
            self.doc.recompute()
            self.assertTrue(body.isValid(), body.getStatusString())
            self.assertTrue(body.Shape.isNull())
        finally:
            os.remove(path)

    # ---------------------------------------- a New part's empty Body (ops#640 rank 30, F50)

    def deleteFeature(self, feature):
        """The Features list's delete of a feature: out of its Body, then out of the document."""
        body = feature.getParentGeoFeatureGroup()
        body.removeObject(feature)
        self.doc.removeObject(feature.Name)

    def testAnEmptiedPartsSketchGoesToThePartItIsOn(self):
        """The boss deleted from Other (its only solid): its sketch, on the cube's top face, goes
        to the cube's Body after the cube's Pad, keeps its face reference and place, and Other is
        removed with its origin, in the delete's step; undo brings Other back as it was."""
        name = self.other.Name
        originName = self.other.Origin.Name
        bossSketch = self.boss.Profile[0]
        support = [(o.Name, subs) for o, subs in bossSketch.AttachmentSupport]
        placement = bossSketch.Placement
        self.doc.openTransaction("Delete")
        self.deleteFeature(self.boss)
        taker = PartDesign.removeEmptyPart(self.other)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIs(taker, self.body)
        self.assertIsNone(self.doc.getObject(name))
        self.assertIsNone(self.doc.getObject(originName))
        self.assertEqual([o.Name for o in self.body.Group], ["Sketch", "Pad", bossSketch.Name])
        self.assertIs(self.body.Tip, self.pad)
        self.assertEqual([(o.Name, subs) for o, subs in bossSketch.AttachmentSupport], support)
        self.assertTrue(bossSketch.Placement.isSame(placement, 1e-9))
        self.assertTrue(bossSketch.isValid())
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=6)
        self.assertEqual([o.Name for o in PartDesign.studioSequence(self.doc)][-1], bossSketch.Name)

        self.doc.undo()
        self.doc.recompute()
        other = self.doc.getObject(name)
        self.assertIsNotNone(other)
        self.assertEqual([o.Name for o in other.Group], [bossSketch.Name, "Boss"])
        self.assertEqual([o.Name for o in self.body.Group], ["Sketch", "Pad"])
        self.assertAlmostEqual(other.Shape.Volume, 108, places=6)

    def testASketchOnItsOwnOriginIsRelinked(self):
        """A New part drawn on its own Body's XY plane: emptied, its sketch goes to the cube's
        Body on that Body's XY plane, in the same place."""
        third = self.doc.addObject("PartDesign::Body", "Third")
        sk = sketch(third, "ThirdSketch", (20, 0, 24, 4))
        self.pad_(third, "ThirdPad", sk, 2)
        self.doc.recompute()
        placement = sk.Placement
        self.deleteFeature(self.doc.getObject("ThirdPad"))
        self.assertIs(PartDesign.removeEmptyPart(third), self.body)
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("Third"))
        self.assertIs(sk.getParentGeoFeatureGroup(), self.body)
        self.assertIs(sk.AttachmentSupport[0][0], self.body.Origin.OriginFeatures[3])
        self.assertTrue(sk.Placement.isSame(placement, 1e-9))
        self.assertTrue(sk.isValid())

    def testAPlacedPartsSketchStaysWhereItIs(self):
        """Review R7W-1: a New part whose Body is placed 50 mm up, emptied: no other Body has its
        placement, so it stays (its sketch isn't relinked to another frame, where it would move
        50 mm in the world); its sketch keeps its place."""
        import FreeCAD as App

        third = self.doc.addObject("PartDesign::Body", "Third")
        third.Placement = App.Placement(App.Vector(0, 0, 50), App.Rotation())
        sk = sketch(third, "ThirdSketch", (20, 0, 24, 4))
        self.pad_(third, "ThirdPad", sk, 2)
        self.doc.recompute()
        world = sk.getGlobalPlacement()
        self.deleteFeature(self.doc.getObject("ThirdPad"))
        self.assertIsNone(PartDesign.removeEmptyPart(third))
        self.doc.recompute()
        self.assertIsNotNone(self.doc.getObject("Third"))
        self.assertIs(sk.getParentGeoFeatureGroup(), third)
        self.assertTrue(sk.getGlobalPlacement().isSame(world, 1e-9))

    def testAPartWithASolidOrTheOnlyBodyStays(self):
        """A Body with a solid feature, or the studio's only one, isn't removed."""
        self.assertIsNone(PartDesign.removeEmptyPart(self.other))
        self.assertIsNotNone(self.doc.getObject("Other"))
        self.deleteFeature(self.boss)
        self.deleteFeature(self.pad)
        self.doc.removeObject("Other")
        self.doc.recompute()
        self.assertIsNone(PartDesign.removeEmptyPart(self.body))
        self.assertIsNotNone(self.doc.getObject("Body"))

    # ops#991 (Onshape DB5): a sketch is no part, so a deleted part's sketches stay readable; what
    # the sketch reads is judged at its own place (notes/ops991-delete-part-sketches.md)

    def laterPart(self, profile, length, name="Late"):
        """A Body made after the delete, padding profile by length"""
        third = self.doc.addObject("PartDesign::Body", "Third")
        late = self.pad_(third, name, profile, length)
        self.doc.recompute()
        return third, late

    def assertBox(self, shape, xmin, ymin, zmin, xmax, ymax, zmax):
        box = shape.BoundBox
        for got, want in zip(
            (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax),
            (xmin, ymin, zmin, xmax, ymax, zmax),
        ):
            self.assertAlmostEqual(got, want, places=6)

    def testALaterPartFromTheDeletedPartsSketch(self):
        """ops#991: the deleted part's own sketch (10 x 10 on XY) padded 4 by a later part: 400."""
        feature = self.delete()
        profile = self.doc.getObject("Sketch")
        third, late = self.laterPart(profile, 4)
        sequence = PartDesign.studioSequence(self.doc)
        self.assertLess(sequence.index(feature), sequence.index(late))
        self.assertTrue(late.isValid(), late.getStatusString())
        self.assertAlmostEqual(third.Shape.Volume, 400, places=6)
        self.assertBox(third.Shape, 0, 0, 0, 10, 10, 4)
        # The deleted part stays deleted
        self.assertTrue(self.body.Shape.isNull() or self.body.Shape.Volume == 0)

    def testASketchOnTheDeletedSolidsFaceMadeBefore(self):
        """ops#991: a sketch of the deleted Body on its solid's top face (z 10), made before the
        delete, keeps its plane: a later part pads its 6 x 6 by 3, z 10..13, 108."""
        top = sketch(self.body, "TopSketch", (2, 2, 8, 8), support=[(self.pad, faceAt(self.pad, 10))])
        self.doc.recompute()
        feature = self.delete()
        sequence = PartDesign.studioSequence(self.doc)
        self.assertLess(sequence.index(top), sequence.index(feature))
        third, late = self.laterPart(top, 3)
        self.assertTrue(late.isValid(), late.getStatusString())
        self.assertAlmostEqual(third.Shape.Volume, 108, places=6)
        self.assertBox(third.Shape, 2, 2, 10, 8, 8, 13)

    def testAnExpressionOnTheDeletedPartsSketch(self):
        """ops#991 (ops#980's live copies): a later part's length bound to the deleted part's sketch
        dimension (its width, 10) builds: its own 4 x 4 by 10, 160."""
        profile = self.doc.getObject("Sketch")
        width = profile.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 10))
        profile.renameConstraint(width, "w")
        self.doc.recompute()
        self.delete()
        third = self.doc.addObject("PartDesign::Body", "Third")
        late = self.pad_(third, "Late", sketch(third, "LateSketch", (20, 0, 24, 4)), 1)
        late.setExpression("Length", "Sketch.Constraints.w")
        self.doc.recompute()
        self.assertTrue(late.isValid(), late.getStatusString())
        self.assertAlmostEqual(late.Length.Value, 10, places=6)
        self.assertAlmostEqual(third.Shape.Volume, 160, places=6)

    def testAnExpressionOnTheDeletedSolidStillFails(self):
        """ops#991: the deleted part's solid feature stays deleted: a later length bound to the
        deleted Pad's Length fails, naming the Pad."""
        self.delete()
        third = self.doc.addObject("PartDesign::Body", "Third")
        late = self.pad_(third, "Late", sketch(third, "LateSketch", (20, 0, 24, 4)), 1)
        late.setExpression("Length", "Pad.Length")
        self.doc.recompute()
        self.assertFalse(late.isValid())
        self.assertIn("deleted before it", late.getStatusString())
        self.assertIn(self.pad.Label, late.getStatusString())

    def testASketchOnTheDeletedFaceMadeAfterFailsItsReader(self):
        """ops#991 (DB1): a sketch of the deleted Body made after the delete on its solid's face
        reads a face that is gone at its place: a later part from it fails, naming the Pad."""
        feature = self.delete()
        after = sketch(self.body, "AfterSketch", (2, 2, 8, 8), support=[(self.pad, faceAt(self.pad, 10))])
        self.doc.recompute()
        sequence = PartDesign.studioSequence(self.doc)
        self.assertLess(sequence.index(feature), sequence.index(after))
        third, late = self.laterPart(after, 3)
        self.assertFalse(late.isValid())
        self.assertIn("deleted before it", late.getStatusString())
        self.assertIn(self.pad.Label, late.getStatusString())
        self.assertIn(after.Label, late.getStatusString())

    def testTheDeletedPartsSketchSavedAndReopened(self):
        """ops#991: saved and reopened, the later part from the deleted part's sketch still builds."""
        self.delete()
        third, late = self.laterPart(self.doc.getObject("Sketch"), 4)
        self.assertTrue(late.isValid(), late.getStatusString())
        name = late.Name
        path = os.path.join(tempfile.mkdtemp(), "TestDeletePart991.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        try:
            self.doc.recompute()
            late = self.doc.getObject(name)
            self.assertTrue(late.isValid(), late.getStatusString())
            self.assertAlmostEqual(self.doc.getObject("Third").Shape.Volume, 400, places=6)
        finally:
            os.remove(path)

    def twoSketchReader(self, profileFirst):
        """A later feature reading two sketches of its own Body on the deleted solid's top face, one
        made before the delete and one after (its 'x' read by the Length): the after one locks it,
        whichever the profile is (skeptic 1: one read path must not hide the other)."""
        third = self.doc.addObject("PartDesign::Body", "Third")
        face = [(self.pad, faceAt(self.pad, 10))]
        before = sketch(third, "Before", (2, 2, 8, 8), support=face)
        self.doc.recompute()
        self.delete()
        after = sketch(third, "After", (3, 3, 7, 7), support=face)
        x = after.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 4))
        after.renameConstraint(x, "x")
        width = before.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 6))
        before.renameConstraint(width, "x")
        profile, bound = (before, after) if profileFirst else (after, before)
        late = self.pad_(third, "Late", profile, 1)
        late.setExpression("Length", bound.Name + ".Constraints.x")
        self.doc.recompute()
        self.assertFalse(late.isValid())
        self.assertIn("deleted before it", late.getStatusString())
        self.assertIn(after.Label, late.getStatusString())

    def testTwoReadPathsBeforeProfile(self):
        self.twoSketchReader(True)

    def testTwoReadPathsAfterProfile(self):
        self.twoSketchReader(False)

    def testTheDeletePartDraggedAboveTheSketchRelocksItsReader(self):
        """ops#991 (skeptic 5): the deleted Body's sketch on its solid's face, made before the delete,
        feeds a later part; the Delete part dragged above the sketch locks the reader (the sketch's
        read of the face is after the delete now); dragged back, it builds again."""
        top = sketch(self.body, "TopSketch", (2, 2, 8, 8), support=[(self.pad, faceAt(self.pad, 10))])
        self.doc.recompute()
        feature = self.delete()
        third, late = self.laterPart(top, 3)
        self.assertTrue(late.isValid(), late.getStatusString())
        PartDesign.moveInStudio(self.doc, [feature], self.pad)
        self.doc.recompute()
        sequence = PartDesign.studioSequence(self.doc)
        self.assertLess(sequence.index(feature), sequence.index(top))
        self.assertFalse(late.isValid())
        self.assertIn("deleted before it", late.getStatusString())
        self.assertIn(top.Label, late.getStatusString())
        PartDesign.moveInStudio(self.doc, [feature], top)
        self.doc.recompute()
        self.assertTrue(late.isValid(), late.getStatusString())
        self.assertAlmostEqual(third.Shape.Volume, 108, places=6)

    def testALiveBodysSketchOnTheDeletedFaceMadeAfterFailsItsReader(self):
        """ops#991 (skeptic 2): a sketch belongs to no part, so a sketch of a Body that isn't deleted,
        made after the delete on the deleted solid's face, is judged at its place too: a later part
        of a third Body from it fails, naming the sketch and the Pad (Onshape DB1: the sketch fails)."""
        self.delete()
        live = sketch(self.other, "LiveSketch", (2, 2, 8, 8), support=[(self.pad, faceAt(self.pad, 10))])
        self.doc.recompute()
        third, late = self.laterPart(live, 3)
        self.assertFalse(late.isValid())
        self.assertIn("deleted before it", late.getStatusString())
        self.assertIn(live.Label, late.getStatusString())
        self.assertIn(self.pad.Label, late.getStatusString())
        # The live Body's own solids stay readable through its sketch
        boss = self.boss.Profile[0]
        third2, late2 = self.laterPart(boss, 1, "FromBossSketch")
        self.assertTrue(late2.isValid(), late2.getStatusString())
