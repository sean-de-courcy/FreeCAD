# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#325, B+ Stage 1 session 3b)

"""Merge: one part absorbs another (PartDesign.makeMerge, notes/bplus-stage1-design.md 2.5 and 2.6,
M-t1 to M-t7; M-t8, a Boolean whose tools are all deleted, is TestBoolean's ops#314 test). The
Merge is a Fuse in the surviving Body whose tool is the absorbed Body's last solid feature; the
absorbed Body gets a hidden MergedInto link and is hidden, and a solid added to it after the merged
feature fails. Designed geometry, S3's bracket and panel: the bracket 40 x 40 x 10 at the origin
(16000), the panel 40 x 30 x 10 from (20, 0) (12000), overlapping in 20 x 30 x 10 (6000), so the
union is 22000. Oracles are volumes and point membership."""

import os
import tempfile
import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests.TestStudio import faceAt, inside, pad, sketch, xyPlane

V = App.Vector

UNION = 16000 + 12000 - 6000
LOCKED = "Panel is merged into Bracket at PanelPad; this feature doesn't reach the merge"


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestMerge")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def model(self):
        doc = self.doc
        self.bracket = doc.addObject("PartDesign::Body", "Bracket")
        self.bracket.Label = "Bracket"
        bracketSk = sketch(self.bracket, "BracketSk", xyPlane(self.bracket), (0, 0, 40, 40))
        self.bracketPad = pad(self.bracket, "BracketPad", bracketSk, 10)
        self.panel = doc.addObject("PartDesign::Body", "Panel")
        self.panel.Label = "Panel"
        self.panelSk = sketch(self.panel, "PanelSk", xyPlane(self.panel), (20, 0, 60, 30))
        self.panelPad = pad(self.panel, "PanelPad", self.panelSk, 10)
        doc.recompute()
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)
        self.assertAlmostEqual(self.panel.Shape.Volume, 12000, places=6)

    def merge(self, at=None):
        merge = PartDesign.makeMerge(at or self.bracket, [self.panel])
        self.doc.recompute()
        self.assertTrue(merge.isValid(), merge.getStatusString())
        return merge

    def later(self, name="Later"):
        """A pad on top of the panel, 10 x 10 x 5 at (45, 10), after the merged feature."""
        sk = sketch(self.panel, name + "Sk", xyPlane(self.panel), (45, 10, 55, 20), z=10)
        return pad(self.panel, name, sk, 5)

    def assertLocked(self, feature):
        self.assertFalse(feature.isValid())
        self.assertIn(LOCKED, feature.getStatusString())

    def testMergeAndItsLock(self):
        """M-t1: the panel merged into the bracket: the bracket is the union (22000), the Merge
        is a Fuse of PanelPad after BracketPad and the bracket's Tip, and the panel is hidden
        with MergedInto set. A later panel feature added from Python fails red with the lock's
        message, and the bracket is unchanged. An earlier edit flows: PanelPad 10 -> 12 gives
        24400. Deleting the Merge shows the panel again, and its later feature computes (from
        z 10, it adds 10 x 10 x 3 above the panel's 12: 14400 + 300)."""
        self.model()
        merge = self.merge()
        self.assertEqual(merge.TypeId, "PartDesign::Boolean")
        self.assertEqual(merge.Label, "Merge")
        self.assertEqual(merge.Type, "Fuse")
        self.assertEqual(merge.Group, [self.panelPad])
        self.assertIs(merge.BaseFeature, self.bracketPad)
        self.assertIs(self.bracket.Tip, merge)
        self.assertIs(self.panel.MergedInto, merge)
        self.assertFalse(self.panel.Visibility)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)
        self.assertTrue(inside(self.bracket.Shape, V(50, 15, 5)))

        later = self.later()
        self.doc.recompute()
        self.assertLocked(later)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)

        self.panelPad.Length = 12
        self.doc.recompute()
        self.assertLocked(later)
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000 + 14400 - 6000, places=6)

        self.bracket.removeObject(merge)
        self.doc.removeObject(merge.Name)
        self.doc.recompute()
        self.assertIsNone(self.panel.MergedInto)
        self.assertTrue(self.panel.Visibility)
        self.assertTrue(later.isValid(), later.getStatusString())
        self.assertAlmostEqual(self.panel.Shape.Volume, 14400 + 300, places=6)
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)

    def testLockByAGroupEdit(self):
        """M-t1: a pad put after the merged feature by an edit of the panel's Group (and made
        its Tip) fails red with the lock's message; the bracket is unchanged."""
        self.model()
        self.merge()
        sk = sketch(self.panel, "ExtraSk", xyPlane(self.panel), (45, 10, 55, 20), z=10)
        extra = self.doc.addObject("PartDesign::Pad", "Extra")
        extra.Profile = sk
        extra.Length = 5
        self.panel.Group = self.panel.Group + [extra]
        self.panel.Tip = extra
        self.doc.recompute()
        self.assertLocked(extra)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)

    def testLockByAReorder(self):
        """M-t1: a solid before the merged feature computes (a 10 x 10 x 1 pad under PanelPad,
        inside its footprint); reordered after it (and made the Tip), it fails red with the
        lock's message, and the Merge still computes the union."""
        self.model()
        firstSk = sketch(self.panel, "FirstSk", xyPlane(self.panel), (20, 0, 30, 10))
        first = pad(self.panel, "First", firstSk, 1)
        for obj in (first, firstSk):
            self.panel.removeObject(obj)
        for obj in (firstSk, first):
            self.panel.insertObject(obj, self.panelSk, False)
        self.panel.Tip = self.panelPad
        self.doc.recompute()
        self.assertIs(self.panelPad.BaseFeature, first)
        merge = self.merge()
        self.assertTrue(first.isValid(), first.getStatusString())
        self.panel.removeObject(first)
        self.panel.insertObject(first, self.panelPad, True)
        self.panel.Tip = first
        self.doc.recompute()
        self.assertLocked(first)
        self.assertTrue(merge.isValid(), merge.getStatusString())
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)

    def testMergeAfterAFeature(self):
        """The Merge goes right after the feature it is made at, not at the Tip: a bracket pad on
        top (10 x 10 x 5 at (5, 5, 10)) stays after it, its base now the Merge."""
        self.model()
        topSk = sketch(self.bracket, "TopSk", xyPlane(self.bracket), (5, 5, 15, 15), z=10)
        top = pad(self.bracket, "Top", topSk, 5)
        self.doc.recompute()
        merge = self.merge(at=self.bracketPad)
        group = self.bracket.Group
        self.assertEqual(group.index(merge), group.index(self.bracketPad) + 1)
        self.assertIs(top.BaseFeature, merge)
        self.assertIs(self.bracket.Tip, top)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION + 500, places=6)

    def testWarningUntilAccepted(self):
        """M-t2: the Merge warns "Merged Panel into Bracket" from its first recompute; the
        warning is saved and restored with the file; MergeAccepted clears it. A held input's
        warning (the panel rolled back above PanelPad, after the merge) shows beside it."""
        self.model()
        merge = self.merge()
        self.assertIn("Warning", merge.State)
        self.assertIn("Merged Panel into Bracket", merge.getStatusString())
        self.assertFalse(merge.MergeAccepted)

        # a second warning on the same feature: its input held by the panel's bar
        self.panel.Tip = self.panelSk
        self.doc.recompute()
        status = merge.getStatusString()
        self.assertIn("Merged Panel into Bracket", status)
        self.assertIn("PanelPad", status.replace("Merged Panel into Bracket", ""))
        self.panel.Tip = self.panelPad
        self.doc.recompute()

        path = os.path.join(tempfile.mkdtemp(prefix="TestMerge"), "merge.FCStd")
        self.doc.saveAs(path)
        name = merge.Name
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        merge = self.doc.getObject(name)
        panel = self.doc.getObject("Panel")
        self.assertIs(panel.MergedInto, merge)
        self.assertIn("Merged Panel into Bracket", merge.getStatusString())

        merge.MergeAccepted = True
        self.doc.recompute()
        self.assertNotIn("Warning", merge.State)
        self.assertNotIn("Merged", merge.getStatusString())
        self.assertAlmostEqual(self.doc.getObject("Bracket").Shape.Volume, UNION, places=6)

    def testFailedMergedFeature(self):
        """M-t3: PanelPad fails (its sketch opened, one edge deleted): the Merge is red, naming
        it, and passes the bracket through (16000)."""
        self.model()
        merge = self.merge()
        self.panelSk.delGeometry(3)
        self.doc.recompute()
        self.assertFalse(self.panelPad.isValid())
        self.assertFalse(merge.isValid())
        self.assertIn("PanelPad", merge.getStatusString())
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)

    def testAbsorbedBodyDeleted(self):
        """M-t4: the panel deleted from Python: the Merge is red, its part gone, and passes the
        bracket through."""
        self.model()
        merge = self.merge()
        self.panel.removeObjectsFromDocument()
        self.doc.removeObject(self.panel.Name)
        self.doc.recompute()
        self.assertFalse(merge.isValid())
        self.assertIn("the merged part is gone", merge.getStatusString())
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)

    def testRefusedWhileRolledBack(self):
        """M-t5: the panel rolled back above PanelPad: the merge is refused, and nothing
        changes."""
        self.model()
        self.panel.Tip = self.panelSk
        self.doc.recompute()
        before = sorted(o.Name for o in self.doc.Objects)
        with self.assertRaisesRegex(Exception, "Roll Panel to the end first"):
            PartDesign.makeMerge(self.bracket, [self.panel])
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertFalse(hasattr(self.panel, "MergedInto"))

    def testAbsorbedBodyMoved(self):
        """M-t6: the panel's Placement set to (10, 0, 0), then a plain recompute: the Merge
        recomputes, and the bracket is the union at the panel's new place (overlap 10 x 30 x 10:
        25000), solid at (65, 15, 5)."""
        self.model()
        merge = self.merge()
        self.panel.Placement = App.Placement(V(10, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertTrue(merge.isValid(), merge.getStatusString())
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000 + 12000 - 3000, places=6)
        self.assertTrue(inside(self.bracket.Shape, V(65, 15, 5)))

    def sheet(self, **cells):
        """A spreadsheet with one aliased cell per keyword, in A1, A2, ..."""
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        for row, (alias, value) in enumerate(cells.items(), 1):
            sheet.set(f"A{row}", str(value))
            sheet.setAlias(f"A{row}", alias)
        self.doc.recompute()
        return sheet

    def testAbsorbedBodyMovedByAnExpression(self):
        """M-t6, the Placement driven by a spreadsheet (PR 305 round 1): the panel's x and its
        angle about z come from cells, so the panel moves in the middle of the recompute, after
        the Merge may have run. One plain recompute after each cell change is enough: dx 10 gives
        25000 (solid at (65, 15, 5)); then 90 degrees about the origin puts the panel at x -30..0,
        y 20..60, clear of the bracket: 28000, solid at (-15, 40, 5)."""
        self.model()
        sheet = self.sheet(dx=0, angle=0)
        self.panel.Placement = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 0))
        self.panel.setExpression(".Placement.Base.x", "Sheet.dx")
        self.panel.setExpression(".Placement.Rotation.Angle", "Sheet.angle * 1 deg")
        self.doc.recompute()
        merge = self.merge()
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)

        sheet.set("dx", "10")
        self.doc.recompute()
        self.assertAlmostEqual(self.panel.Placement.Base.x, 10)
        self.assertTrue(merge.isValid(), merge.getStatusString())
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000 + 12000 - 3000, places=6)
        self.assertTrue(inside(self.bracket.Shape, V(65, 15, 5)))

        sheet.set("dx", "0")
        sheet.set("angle", "90")
        self.doc.recompute()
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000 + 12000, places=6)
        self.assertTrue(inside(self.bracket.Shape, V(-15, 40, 5)))
        self.assertNotIn("Touched", self.doc.getObject("Merge").State)

    def testMovedByAnExpressionInAPart(self):
        """M-t6 in a rotated App::Part (PR 305 round 1): both parts in it, the panel's x from a
        cell. dx 10 and one recompute: 25000, solid at (65, 15, 5) in the Part."""
        self.model()
        part = self.doc.addObject("App::Part", "Part")
        part.Placement = App.Placement(V(-30, 7, 4), App.Rotation(V(0, 1, 1), 50))
        part.addObject(self.bracket)
        part.addObject(self.panel)
        sheet = self.sheet(dx=0)
        self.panel.setExpression(".Placement.Base.x", "Sheet.dx")
        self.doc.recompute()
        self.merge()
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)
        sheet.set("dx", "10")
        self.doc.recompute()
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000 + 12000 - 3000, places=6)
        self.assertTrue(inside(self.bracket.Shape, V(65, 15, 5)))

    def testSurvivorMovedByAnExpression(self):
        """The surviving part moved by a cell (PR 305 round 1): the Merge, in the bracket, runs
        in the same recompute. Bracket x 10: the panel sits at -10..30 in the bracket's frame,
        overlapping 30 x 30 x 10: 19000, solid to x 60 and no further (a Merge left at the old
        frames would reach x 70)."""
        self.model()
        sheet = self.sheet(dx=0)
        self.bracket.setExpression(".Placement.Base.x", "Sheet.dx")
        self.doc.recompute()
        self.merge()
        sheet.set("dx", "10")
        self.doc.recompute()
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000 + 12000 - 9000, places=6)
        self.assertTrue(inside(self.bracket.Shape, V(55, 15, 5)))
        self.assertFalse(inside(self.bracket.Shape, V(65, 15, 5)))
        self.assertNotIn("Touched", self.doc.getObject("Merge").State)

    def testStaleMergeReopened(self):
        """A Merge saved stale (its part moved, the Merge left untouched, as an expression could
        leave it before round 1) runs on the first recompute after reopening: the frames it last
        computed with are saved (PR 305 round 1)."""
        self.model()
        merge = self.merge()
        self.panel.Placement = App.Placement(V(10, 0, 0), App.Rotation())
        merge.purgeTouched()
        path = os.path.join(tempfile.mkdtemp(prefix="TestMerge"), "stale.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.doc.recompute()
        bracket = self.doc.getObject("Bracket")
        self.assertAlmostEqual(bracket.Shape.Volume, 16000 + 12000 - 3000, places=6)
        self.assertTrue(inside(bracket.Shape, V(65, 15, 5)))

    def testRefusedCycle(self):
        """M-t7: the panel's sketch sits on a bracket pad that comes after the Merge's place
        (Top, on BracketPad): merging at BracketPad would feed Top from PanelPad, which depends
        on Top, so it is refused, naming Top. At the Tip (after Top) it is allowed."""
        self.model()
        topSk = sketch(self.bracket, "TopSk", xyPlane(self.bracket), (0, 0, 40, 40), z=10)
        top = pad(self.bracket, "Top", topSk, 5)
        self.doc.recompute()
        self.panelSk.AttachmentSupport = [(top, faceAt(top, 15))]
        self.panelSk.AttachmentOffset = App.Placement()
        self.doc.recompute()
        self.assertTrue(self.panelPad.isValid(), self.panelPad.getStatusString())
        before = sorted(o.Name for o in self.doc.Objects)
        cycle = "PanelPad depends on Top, which comes after the Merge"
        with self.assertRaisesRegex(Exception, cycle):
            PartDesign.makeMerge(self.bracketPad, [self.panel])
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        merge = self.merge(at=top)
        self.assertIs(self.bracket.Tip, merge)

    def testRefusedTargets(self):
        """A part outside the studio (placed elsewhere), the part itself, a part already merged,
        and a target that is neither a solid feature nor a part are refused, with the reason."""
        self.model()
        away = self.doc.addObject("PartDesign::Body", "Away")
        away.Placement.Base = V(0, 0, 50)
        pad(away, "AwayPad", sketch(away, "AwaySk", xyPlane(away), (0, 0, 10, 10)), 10)
        self.doc.recompute()
        with self.assertRaisesRegex(Exception, "studio"):
            PartDesign.makeMerge(self.bracket, [away])
        with self.assertRaisesRegex(Exception, "itself"):
            PartDesign.makeMerge(self.bracket, [self.bracket])
        with self.assertRaisesRegex(Exception, "neither a solid feature"):
            PartDesign.makeMerge(self.panelSk, [self.bracket])
        self.merge()
        with self.assertRaisesRegex(Exception, "merged into Bracket already"):
            PartDesign.makeMerge(self.bracket, [self.panel])
        with self.assertRaisesRegex(Exception, "Panel is merged into Bracket; merge into that"):
            PartDesign.makeMerge(self.panel, [self.bracket])

    def testUndoRemovesTheMerge(self):
        """The merge made in one transaction: one undo removes the Merge, shows the panel again
        and leaves the bracket whole."""
        self.model()
        self.doc.openTransaction("Merge")
        PartDesign.makeMerge(self.bracket, [self.panel])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("Merge"))
        self.assertIs(self.bracket.Tip, self.bracketPad)
        self.assertTrue(self.panel.Visibility)
        self.assertIsNone(getattr(self.panel, "MergedInto", None))
        self.assertAlmostEqual(self.bracket.Shape.Volume, 16000, places=6)

    def testUndoOfTheUnmerge(self):
        """Undo and redo of deleting the Merge (PR 305 round 1): a later panel feature, locked,
        computes once the Merge is deleted; undo brings the Merge back and locks it again (red,
        not in the union); redo frees it again."""
        self.model()
        self.doc.openTransaction("Merge")
        merge = PartDesign.makeMerge(self.bracket, [self.panel])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.doc.openTransaction("Later")
        later = self.later()
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertLocked(later)

        self.doc.openTransaction("Unmerge")
        self.bracket.removeObject(merge)
        self.doc.removeObject(merge.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertTrue(later.isValid(), later.getStatusString())
        self.assertAlmostEqual(self.panel.Shape.Volume, 12000 + 500, places=6)

        self.doc.undo()
        self.doc.recompute()
        merge = self.doc.getObject("Merge")
        self.assertIs(self.panel.MergedInto, merge)
        self.assertFalse(self.panel.Visibility)
        self.assertLocked(later)
        self.assertAlmostEqual(self.bracket.Shape.Volume, UNION, places=6)

        self.doc.redo()
        self.doc.recompute()
        self.assertIsNone(self.panel.MergedInto)
        self.assertTrue(self.panel.Visibility)
        self.assertTrue(later.isValid(), later.getStatusString())
        self.assertAlmostEqual(self.panel.Shape.Volume, 12000 + 500, places=6)


if __name__ == "__main__":
    unittest.main()
