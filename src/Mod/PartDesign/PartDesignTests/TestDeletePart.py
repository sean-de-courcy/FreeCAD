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
