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
        self.assertIs(self.body.Tip, self.pad)
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=6)
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
