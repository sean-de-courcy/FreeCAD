# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, the Onshape experiment, ranks 1 and 3a)

"""The merge scope of a feature, as Onshape's Extrude has it (ops#640 rank 1), and an empty scope
(rank 3a). PartDesign.setMergeScope(feature, bodies) merges the bodies right after the feature in
an accepted Merge (no Warning), changes that Merge in place, or deletes it with no bodies. An Add,
Remove or Intersect with an empty scope and Merge with all off fails red, "No merge scope
selected", and adds nothing; MergeWithAll and EmptyMergeScope are new properties that default off,
so a feature made before them computes as it did.

Designed geometry, TestMerge's bracket and panel: the bracket 40 x 40 x 10 at the origin (16000),
the panel 40 x 30 x 10 from (20, 0) (12000), overlapping in 20 x 30 x 10 (6000), so their union is
22000; a part Far 40 x 40 x 10 from (100, 0) (16000), touching neither. Oracles are volumes and
point membership."""

import os
import tempfile
import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests.TestStudio import inside, pad, sketch, xyPlane

V = App.Vector

UNION = 16000 + 12000 - 6000
NO_SCOPE = "No merge scope selected"


def volume(shape):
    return 0 if shape.isNull() else shape.Volume


class TestMergeScope(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestMergeScope")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def part(self, name, rect, z=0, height=10):
        body = self.doc.addObject("PartDesign::Body", name)
        body.Label = name
        feature = pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), rect, z=z), height)
        return body, feature

    def model(self):
        self.bracket, self.bracketPad = self.part("Bracket", (0, 0, 40, 40))
        self.panel, self.panelPad = self.part("Panel", (20, 0, 60, 30))
        self.far, self.farPad = self.part("Far", (100, 0, 140, 40))
        self.doc.recompute()
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)
        self.assertAlmostEqual(self.panel.Shape.Volume, 12000, places=6)
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=6)

    def assertValid(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    # -- rank 1: the scope -----------------------------------------------------------------------

    def testNewPropertiesDefaultOff(self):
        """A feature made now, as one read from a file saved before the properties, has
        MergeWithAll and EmptyMergeScope off: a first pad is a new part (16000), valid."""
        self.model()
        for feature in (self.bracketPad, self.panelPad, self.farPad):
            self.assertFalse(feature.MergeWithAll)
            self.assertFalse(feature.EmptyMergeScope)
        self.assertValid()

    def testScopeMakesAnAcceptedMerge(self):
        """The panel in the bracket pad's scope: a Merge right after the pad, its Tip, fuses the
        panel's pad (22000); the panel is hidden and merged; the Merge is accepted, with no
        Warning (Onshape's merge is a plain feature, P50). mergeAfter names it."""
        self.model()
        merge = PartDesign.setMergeScope(self.bracketPad, [self.panel])
        self.doc.recompute()
        self.assertIsNotNone(merge)
        self.assertIs(PartDesign.mergeAfter(self.bracketPad), merge)
        self.assertIs(merge.BaseFeature, self.bracketPad)
        self.assertEqual(merge.Group, [self.panelPad])
        self.assertIs(self.bracket.Tip, merge)
        self.assertTrue(merge.MergeAccepted)
        self.assertNotIn("Warning", merge.State)
        self.assertIs(self.panel.MergedInto, merge)
        self.assertFalse(self.panel.Visibility)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)
        self.assertTrue(inside(self.bracket.Shape, V(50, 15, 5)))
        self.assertValid()

    def testUntickUnmergesInPlace(self):
        """Panel and Far in the scope (22000 + 16000), then the panel only: the same Merge, Far
        a part again (shown, 16000, not merged), the bracket 22000. A pad after the Merge, on the
        bracket's top (10 x 10 x 5 at the origin, +500), still reads it."""
        self.model()
        merge = PartDesign.setMergeScope(self.bracketPad, [self.panel, self.far])
        later = pad(self.bracket, "Later", sketch(self.bracket, "LaterSk", xyPlane(self.bracket),
                                                  (0, 0, 10, 10), z=10), 5)
        self.doc.recompute()
        self.assertIs(later.BaseFeature, merge)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION + 16000 + 500, places=6)
        name = merge.Name
        again = PartDesign.setMergeScope(self.bracketPad, [self.panel])
        self.doc.recompute()
        self.assertIs(again, merge)
        self.assertEqual(merge.Name, name)
        self.assertEqual(merge.Group, [self.panelPad])
        self.assertIsNone(self.far.MergedInto)
        self.assertTrue(self.far.Visibility)
        self.assertIs(self.panel.MergedInto, merge)
        self.assertIs(later.BaseFeature, merge)
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=6)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION + 500, places=6)
        self.assertValid()

    def testEmptyScopeDeletesTheMerge(self):
        """Every part unticked: the Merge goes, the panel is a part again (shown, 12000), the
        bracket 16000; setMergeScope returns None, and None again with nothing to delete."""
        self.model()
        merge = PartDesign.setMergeScope(self.bracketPad, [self.panel])
        self.doc.recompute()
        name = merge.Name
        self.assertIsNone(PartDesign.setMergeScope(self.bracketPad, []))
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertIsNone(PartDesign.mergeAfter(self.bracketPad))
        self.assertIsNone(self.panel.MergedInto)
        self.assertTrue(self.panel.Visibility)
        self.assertIs(self.bracket.Tip, self.bracketPad)
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)
        self.assertAlmostEqual(self.panel.Shape.Volume, 12000, places=6)
        self.assertIsNone(PartDesign.setMergeScope(self.bracketPad, []))
        self.assertValid()

    def testScopeAcceptsAnUnacceptedMerge(self):
        """A Merge Parts made (unaccepted, it warns) and set again through the scope with the
        same part: accepted, no Warning."""
        self.model()
        merge = PartDesign.makeMerge(self.bracketPad, [self.panel])
        self.doc.recompute()
        self.assertIn("Warning", merge.State)
        self.assertIs(PartDesign.setMergeScope(self.bracketPad, [self.panel]), merge)
        self.doc.recompute()
        self.assertTrue(merge.MergeAccepted)
        self.assertNotIn("Warning", merge.State)

    def testRefusals(self):
        """Refused with the reason, before anything changes: the feature's own part, a part
        merged elsewhere, a rolled-back part, and an object that isn't a solid feature."""
        self.model()
        with self.assertRaisesRegex(Exception, "can't merge into itself"):
            PartDesign.setMergeScope(self.bracketPad, [self.bracket])
        PartDesign.setMergeScope(self.farPad, [self.panel])
        self.doc.recompute()
        with self.assertRaisesRegex(Exception, "is merged into Far already"):
            PartDesign.setMergeScope(self.bracketPad, [self.panel])
        PartDesign.setMergeScope(self.farPad, [])
        self.doc.recompute()
        self.panel.Tip = self.panel.Group[0]  # the bar above its pad, after its sketch
        with self.assertRaisesRegex(Exception, "Roll Panel to the end first"):
            PartDesign.setMergeScope(self.bracketPad, [self.panel])
        self.panel.Tip = self.panelPad
        with self.assertRaisesRegex(Exception, "isn't a solid feature"):
            PartDesign.setMergeScope(self.bracketPad.Profile[0], [self.panel])
        self.assertIsNone(PartDesign.mergeAfter(self.bracketPad))
        self.doc.recompute()
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)

    def testMergeWithAllIsStoredAndSaved(self):
        """MergeWithAll and EmptyMergeScope are saved and read back."""
        self.model()
        self.bracketPad.MergeWithAll = True
        self.farPad.EmptyMergeScope = True
        path = os.path.join(tempfile.mkdtemp(), "MergeScope.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        self.assertTrue(self.doc.getObject("BracketPad").MergeWithAll)
        self.assertTrue(self.doc.getObject("FarPad").EmptyMergeScope)
        self.assertFalse(self.doc.getObject("PanelPad").MergeWithAll)

    # -- rank 3a: an empty scope ------------------------------------------------------------------

    def testAnAddWithAnEmptyScopeFails(self):
        """Far's pad, its part's first solid, as an Add with an empty scope: red, "No merge
        scope selected", and Far has no material (R7(a)). Merge with all on: a new part again,
        16000, valid (R8). Both off: New, 16000."""
        self.model()
        self.farPad.EmptyMergeScope = True
        self.doc.recompute()
        self.assertFalse(self.farPad.isValid())
        self.assertIn(NO_SCOPE, self.farPad.getStatusString())
        self.assertEqual(volume(self.far.Shape), 0)
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)
        self.farPad.MergeWithAll = True
        self.doc.recompute()
        self.assertTrue(self.farPad.isValid(), self.farPad.getStatusString())
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=6)
        self.farPad.MergeWithAll = False
        self.farPad.EmptyMergeScope = False
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=6)

    def testAnEmptyScopeIsSaidBeforeTheRunsFailure(self):
        """Round 8 (J20): Far's pad as an Add with an empty scope and "Up to next" (UpToFirst),
        which finds no face with nothing before it: red with "No merge scope selected", not the
        extrusion's "No faces found in this direction"; Far has no material."""
        self.model()
        self.farPad.EmptyMergeScope = True
        self.farPad.Type = "UpToFirst"
        self.doc.recompute()
        self.assertFalse(self.farPad.isValid())
        self.assertIn(NO_SCOPE, self.farPad.getStatusString())
        self.assertNotIn("No faces found", self.farPad.getStatusString())
        self.assertEqual(volume(self.far.Shape), 0)
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)

    def testAnEmptyScopeKeepsTheRunsOtherFailures(self):
        """Review R8-4: an Add with an empty scope whose run fails for another reason, a length of
        zero, keeps the run's words, not "No merge scope selected"."""
        self.model()
        self.farPad.EmptyMergeScope = True
        self.farPad.Length = 0
        self.doc.recompute()
        self.assertFalse(self.farPad.isValid())
        self.assertNotIn(NO_SCOPE, self.farPad.getStatusString())

    def testAnAddWithItsOwnPartIgnoresTheFlag(self):
        """EmptyMergeScope on a pad with a solid before it in its part: its scope holds its part,
        so it adds there. A 10 x 10 x 5 block on the bracket's top: 16000 + 500, valid."""
        self.model()
        top = pad(self.bracket, "Top", sketch(self.bracket, "TopSk", xyPlane(self.bracket),
                                              (0, 0, 10, 10), z=10), 5)
        top.EmptyMergeScope = True
        self.doc.recompute()
        self.assertTrue(top.isValid(), top.getStatusString())
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16500, places=6)

    def testACutWithAnEmptyScopeFails(self):
        """Far's pad set to Subtraction, then Common: nothing before it, so its scope is empty:
        red, "No merge scope selected" first, then F8's "Nothing to cut", and no material. With
        Merge with all (nothing to cut for it either), F8's words alone."""
        self.model()
        for operation in ("Subtraction", "Common"):
            self.farPad.Operation = operation
            self.doc.recompute()
            self.assertFalse(self.farPad.isValid(), operation)
            status = self.farPad.getStatusString()
            self.assertIn(NO_SCOPE, status, operation)
            self.assertIn("Nothing to cut", status, operation)
            self.assertLess(status.index(NO_SCOPE), status.index("Nothing to cut"), operation)
            self.assertEqual(volume(self.far.Shape), 0, operation)
        self.farPad.MergeWithAll = True
        self.doc.recompute()
        self.assertFalse(self.farPad.isValid())
        self.assertNotIn(NO_SCOPE, self.farPad.getStatusString())
        self.assertIn("Nothing to cut", self.farPad.getStatusString())

    def topBlock(self, name, rect):
        """A 10 x 10 x 5 block (500) on the bracket's top."""
        return pad(self.bracket, name, sketch(self.bracket, name + "Sk", xyPlane(self.bracket),
                                              rect, z=10), 5)

    def deleteFeature(self, feature):
        """As Std_Delete does it (ViewProvider::onDelete): out of its Body, then the document."""
        name = feature.Name
        self.bracket.removeObject(feature)
        self.doc.removeObject(name)

    def testDeletingTheFeatureDeletesItsScope(self):
        """The bracket's top block with the panel in its scope, a second block after the Merge
        (UNION + 1000). Deleting the first block deletes its Merge too, as deleting an Onshape
        Extrude removes its merge: the panel is a part again (shown, 12000), the second block
        reads the bracket's pad, and the bracket is 16000 + 500."""
        self.model()
        top = self.topBlock("Top", (0, 0, 10, 10))
        merge = PartDesign.setMergeScope(top, [self.panel])
        later = self.topBlock("Later", (30, 30, 40, 40))
        self.doc.recompute()
        self.assertIs(later.BaseFeature, merge)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION + 1000, places=6)
        name = merge.Name
        self.deleteFeature(top)
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertIsNone(self.panel.MergedInto)
        self.assertTrue(self.panel.Visibility)
        self.assertIs(later.BaseFeature, self.bracketPad)
        self.assertIs(self.bracket.Tip, later)
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000 + 500, places=6)
        self.assertAlmostEqual(self.panel.Shape.Volume, 12000, places=6)
        self.assertValid()

    def testDeletingTheFeatureKeepsAMergePartsMerge(self):
        """A Merge that Merge Parts made after the block and nobody accepted is its own feature:
        deleting the block leaves it, on the bracket's pad, the panel still merged (UNION)."""
        self.model()
        top = self.topBlock("Top", (0, 0, 10, 10))
        merge = PartDesign.makeMerge(top, [self.panel])
        self.doc.recompute()
        self.assertFalse(merge.MergeAccepted)
        self.deleteFeature(top)
        self.doc.recompute()
        self.assertIs(self.doc.getObject(merge.Name), merge)
        self.assertIs(merge.BaseFeature, self.bracketPad)
        self.assertIs(self.panel.MergedInto, merge)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)

    def testNewPartClearsTheScope(self):
        """PartDesign.newPartFrom makes Onshape's New: the moved feature's MergeWithAll and
        EmptyMergeScope go off. The bracket's top block (10 x 10 x 5), both set, moved to a new
        part: valid, 500, the bracket 16000."""
        self.model()
        top = pad(self.bracket, "Top", sketch(self.bracket, "TopSk", xyPlane(self.bracket),
                                              (0, 0, 10, 10), z=10), 5)
        self.doc.recompute()
        top.EmptyMergeScope = True
        top.MergeWithAll = True
        part = PartDesign.newPartFrom(top)
        self.doc.recompute()
        self.assertIsNot(part, self.bracket)
        self.assertFalse(top.EmptyMergeScope)
        self.assertFalse(top.MergeWithAll)
        self.assertTrue(top.isValid(), top.getStatusString())
        self.assertAlmostEqual(part.Shape.Volume, 500, places=6)
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)


if __name__ == "__main__":
    unittest.main()
