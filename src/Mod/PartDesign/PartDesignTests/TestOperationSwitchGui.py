# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640 round 5, the Onshape experiment's operation switches)

"""Switching an Extrude's operation when later features build on it, or when it merges other parts,
as Onshape's (hands-on B5-3 and B5-4, work/sd03f/hands-on-1.md, Batch 5).

- B5-3: a boss Add with a fillet on its edges switched to New part: the boss goes to a new part with
  the fillet (PartDesign.newPartFrom moves what works on its material, in order); the part it left
  is whole again, and Add brings them back. A later feature that can't be told apart keeps New part
  greyed, its reason the tooltip.
- B5-4: an Add that merged two parts switched to Remove (the Merge goes; the cut goes through both
  parts, a sibling in the other) and then to New (both parts whole, the tool a part of its own), in
  one edit: one undo step. Add merges the kept scope again. Unticking the whole scope in the open
  dialog frees the rows a later feature on the Merge held.

Designed geometry, closed-form volumes: the enclosure 40 x 40 x 10 (16000); a boss 20 x 20 x 5 on
its top from (10, 10) (2000), its four top edges filleted r = 1 (each 20 long: 20 (1 - pi/4) removed
per edge, less the overlap of two edges' fillets at each of the four corners, 5/3 - pi/2: the two
quarter-round grooves meet in a mitre); a part Right 40 x 40 x 10 beside the enclosure (x 40..80) and
a slot 20 x 20 x 10 across their seam (x 30..50, y 10..30), padded up from their tops (4000), half
over each part."""

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestCrossBodyGui import ROWS, ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestStudio import faceAt, pad, rect, sketch, xyPlane

FILLET = 4 * 20 * (1 - math.pi / 4) - 4 * (5 / 3 - math.pi / 2)  # what the fillet removes
BOSS = 2000 - FILLET  # the filleted boss alone
WITH_BOSS = 16000 + BOSS  # the enclosure with it
SLOT = 4000
HALF = SLOT / 2  # the slot's half over each part


class OperationSwitchCase(ResultBoxGuiCase):
    def bossWithFillet(self):
        """The enclosure, the boss on it (Boss, from BossSk on the enclosure's top) and Fillet on
        the boss's four top edges; returns (boss sketch, boss, fillet)."""
        self.enclosure()
        bossSk = self.body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(self.base, faceAt(self.base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, 10, 10, 30, 30)
        boss = pad(self.body, "Boss", bossSk, 5)
        self.doc.recompute()
        edges = [
            f"Edge{i}"
            for i, edge in enumerate(boss.Shape.Edges, 1)
            if all(abs(v.Point.z - 15) < 1e-6 for v in edge.Vertexes)
        ]
        self.assertEqual(len(edges), 4)
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, edges)
        fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, WITH_BOSS, places=3)
        return bossSk, boss, fillet

    def openEdit(self, feature):
        """The feature's edit as a double click opens it; self.undos is the undo count before."""
        self.assertFalse(self.doc.HasPendingTransaction)
        self.undos = len(self.doc.UndoNames)
        feature.ViewObject.doubleClicked()
        self.waitForPanel()
        combo = self.combo()
        self.assertIsNotNone(combo, "no Result box")
        return combo

    def rows(self, combo=None):
        """(text, enabled, tooltip) of each row"""
        combo = combo or self.combo()
        model = combo.model()
        return [
            (
                combo.itemText(i),
                bool(model.flags(model.index(i, 0)) & QtCore.Qt.ItemIsEnabled),
                combo.itemData(i, QtCore.Qt.ToolTipRole) or "",
            )
            for i in range(combo.count())
        ]

    def assertOffered(self, text):
        [row] = [row for row in self.rows() if row[0] == text]
        self.assertTrue(row[1], row)

    def assertRefused(self, text, why):
        [row] = [row for row in self.rows() if row[0] == text]
        self.assertFalse(row[1], row)
        self.assertIn(why, row[2])

    def assertValid(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    def assertOneUndoStep(self):
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(len(self.doc.UndoNames), self.undos + 1, self.doc.UndoNames)

    def bodiesBut(self, *known):
        names = {b.Name for b in known}
        return [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body" and o.Name not in names]


class TestOperationSwitchGui(OperationSwitchCase):
    def testABossWithAFilletGoesToANewPart(self):
        """B5-3: the boss, a fillet on its edges, edited: New part is offered. Chosen, the boss, its
        sketch and the fillet go to a new part in order; the enclosure is whole (16000), its Tip its
        base again; the new part is the filleted boss (BOSS), the fillet valid on it. OK: one undo
        step, which brings the boss back into the enclosure (WITH_BOSS)."""
        bossSk, boss, fillet = self.bossWithFillet()
        self.openEdit(boss)
        self.assertEqual(self.items(self.combo()), ROWS)
        self.assertEqual(self.combo().currentText(), "Add to Enclosure")
        self.assertOffered("New part")
        self.choose("New part")
        [part] = self.bodiesBut(self.body)
        self.assertEqual(part.Group, [bossSk, boss, fillet])
        self.assertIs(part.Tip, fillet)
        self.assertEqual(self.body.Group, [self.doc.getObject("BaseSk"), self.base, self.lidSk])
        self.assertIs(self.body.Tip, self.base)
        self.assertIs(Gui.getDocument(self.doc.Name).getInEdit().Object, boss)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertIs(fillet.BaseFeature, boss)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(part.Shape.Volume, BOSS, places=3)
        self.assertTrue(fillet.Visibility)
        self.assertTrue(self.base.Visibility)
        self.assertOneUndoStep()
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.bodiesBut(self.body), [])
        self.assertIs(self.body.Tip, fillet)
        self.assertAlmostEqual(self.body.Shape.Volume, WITH_BOSS, places=3)

    def testNewThenAddBringsThemBack(self):
        """B5-3's way back: New part, then Add to Enclosure in the same dialog: the boss, its sketch
        and the fillet are where they were, the chain and the Tip as before, the new part gone. OK:
        WITH_BOSS, everything valid."""
        bossSk, boss, fillet = self.bossWithFillet()
        group = self.body.Group
        self.openEdit(boss)
        self.choose("New part")
        self.choose("Add to Enclosure")
        self.assertEqual(self.body.Group, group)
        self.assertEqual(self.bodiesBut(self.body), [])
        self.assertIs(self.body.Tip, fillet)
        self.assertIs(boss.BaseFeature, self.base)
        self.assertIs(fillet.BaseFeature, boss)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(self.body.Shape.Volume, WITH_BOSS, places=3)
        self.assertTrue(fillet.Visibility)
        self.assertFalse(boss.Visibility)

    def testCancelRestoresEverything(self):
        """New part, then Cancel: the enclosure as it was (its members, its Tip, WITH_BOSS), no new
        part, no undo step."""
        bossSk, boss, fillet = self.bossWithFillet()
        group = self.body.Group
        self.openEdit(boss)
        self.choose("New part")
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(self.body.Group, group)
        self.assertEqual(self.bodiesBut(self.body), [])
        self.assertIs(self.body.Tip, fillet)
        self.assertAlmostEqual(self.body.Shape.Volume, WITH_BOSS, places=3)
        self.assertEqual(len(self.doc.UndoNames), self.undos)

    def testACutAwayFromTheBossStays(self):
        """A pocket 5 x 5 x 5 in the enclosure's corner after the fillet, its sketch on the
        enclosure's top, nowhere near the boss: New part takes the boss and the fillet, the pocket
        stays and closes over them, on the base (16000 - 125)."""
        bossSk, boss, fillet = self.bossWithFillet()
        cornerSk = self.body.newObject("Sketcher::SketchObject", "CornerSk")
        cornerSk.AttachmentSupport = [(self.base, faceAt(self.base, 10))]
        cornerSk.MapMode = "FlatFace"
        rect(cornerSk, 0, 0, 5, 5)
        corner = self.body.newObject("PartDesign::Pocket", "Corner")
        corner.Profile = cornerSk
        corner.Length = 5
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, WITH_BOSS - 125, places=3)
        self.openEdit(boss)
        self.assertOffered("New part")
        self.choose("New part")
        [part] = self.bodiesBut(self.body)
        self.assertEqual(part.Group, [bossSk, boss, fillet])
        self.assertIs(corner.BaseFeature, self.base)
        self.assertIs(self.body.Tip, corner)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(self.body.Shape.Volume, 16000 - 125, places=3)
        self.assertAlmostEqual(part.Shape.Volume, BOSS, places=3)

    def testAnExtrudeOnTheBossIsRefused(self):
        """A pad on the boss's top (its sketch on that face) after the fillet: it would stay with
        the enclosure (Onshape's merge scope) and change without a word, so New part stays greyed,
        the tooltip naming the sketch; Add, Remove and Intersect stay offered."""
        bossSk, boss, fillet = self.bossWithFillet()
        topSk = self.body.newObject("Sketcher::SketchObject", "TopSk")
        topSk.AttachmentSupport = [(fillet, faceAt(fillet, 15))]
        topSk.MapMode = "FlatFace"
        rect(topSk, 15, 15, 25, 25)
        pad(self.body, "Top", topSk, 5)
        self.doc.recompute()
        self.assertValid()
        self.openEdit(boss)
        self.assertRefused("New part", "'TopSk' uses 'Fillet'")
        for text in ROWS[2:]:
            self.assertOffered(text)

    def testAFilletOnTheEnclosureIsRefused(self):
        """A fillet on the enclosure's bottom edges right after the boss (its Base the boss): its
        edges aren't the boss's own, so New part stays greyed, naming it."""
        self.enclosure()
        bossSk = self.body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(self.base, faceAt(self.base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, 10, 10, 30, 30)
        boss = pad(self.body, "Boss", bossSk, 5)
        self.doc.recompute()
        edges = [
            f"Edge{i}"
            for i, edge in enumerate(boss.Shape.Edges, 1)
            if all(abs(v.Point.z) < 1e-6 for v in edge.Vertexes)
        ]
        fillet = self.body.newObject("PartDesign::Fillet", "Bottom")
        fillet.Base = (boss, edges)
        fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.openEdit(boss)
        self.assertRefused("New part", "'Bottom' works on 'Boss''s material and on the rest")
        self.assertEqual(
            PartDesign.newPartRefusal(boss),
            "'Bottom' works on 'Boss''s material and on the rest of 'Enclosure', or on what can't "
            "be told apart",
        )


class TestMergedSwitchGui(OperationSwitchCase):
    def mergedSlot(self, later=False):
        """The enclosure, Right beside it and the slot across them, merging Right (36000). With
        `later`, a pocket 5 x 5 x 5 in the enclosure's far corner after the Merge (35875)."""
        self.enclosure()
        self.right = self.part("Right", (40, 0, 80, 40), 0)
        slotSk = sketch(self.body, "SlotSk", xyPlane(self.body), (30, 10, 50, 30), z=10)
        slot = pad(self.body, "Slot", slotSk, 10)
        self.doc.recompute()
        self.merge = PartDesign.setMergeScope(slot, [self.right])
        self.doc.recompute()
        self.assertTrue(self.merge.isValid(), self.merge.getStatusString())
        total = 16000 + 16000 + SLOT
        if later:
            cornerSk = sketch(self.body, "CornerSk", xyPlane(self.body), (0, 0, 5, 5), z=10)
            corner = self.body.newObject("PartDesign::Pocket", "Corner")
            corner.Profile = cornerSk
            corner.Length = 5
            self.doc.recompute()
            self.assertTrue(corner.isValid(), corner.getStatusString())
            self.corner = corner
            total -= 125
        self.assertAlmostEqual(self.body.Shape.Volume, total, places=3)
        return slot

    def testRemoveCutsBothThenNewLeavesThemWhole(self):
        """B5-4: the merged slot edited: Remove and New part offered. Remove from Enclosure: the
        Merge goes, the slot cuts down through both parts (a sibling in Right): 16000 - HALF each.
        New part in the same dialog: both parts whole again (16000 each), the slot a part of its
        own (SLOT). OK: one undo step, which brings the merge back."""
        slot = self.mergedSlot()
        mergeName = self.merge.Name
        self.openEdit(slot)
        self.assertEqual(self.combo().currentText(), "Add to Enclosure")
        for text in ("New part", "Remove from Enclosure", "Intersect with Enclosure"):
            self.assertOffered(text)
        self.choose("Remove from Enclosure")
        self.assertIsNone(self.doc.getObject(mergeName))
        self.assertIsNone(self.right.MergedInto)
        self.assertEqual(slot.Operation, "Subtraction")
        [sibling] = PartDesign.siblingsOf(slot)
        self.assertIs(sibling.getParentGeoFeatureGroup(), self.right)
        self.assertEqual(
            [row for row in self.partItems() if row[0].startswith("Right")], [("Right", True, True)]
        )
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 16000 - HALF, places=3)
        self.assertAlmostEqual(self.right.Shape.Volume, 16000 - HALF, places=3)
        self.choose("New part")
        self.assertEqual(PartDesign.siblingsOf(slot), [])
        [part] = self.bodiesBut(self.body, self.right)
        self.assertIs(slot.getParentGeoFeatureGroup(), part)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertEqual(slot.Operation, "Union")
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(self.right.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(part.Shape.Volume, SLOT, places=3)
        self.assertTrue(self.right.Visibility)
        self.assertOneUndoStep()
        self.doc.undo()
        self.doc.recompute()
        merge = PartDesign.mergeAfter(slot)
        self.assertIsNotNone(merge)
        self.assertAlmostEqual(merge.Shape.Volume, 36000, places=3)

    def testNewThenAddMergesAgain(self):
        """B5-3's way back with a merge: New part, then Add to Enclosure: the slot is back in the
        enclosure, merging Right again (the scope kept while it was New). OK: 36000."""
        slot = self.mergedSlot()
        self.openEdit(slot)
        self.choose("New part")
        self.assertIsNone(PartDesign.mergeAfter(slot))
        self.assertIsNone(self.right.MergedInto)
        self.choose("Add to Enclosure")
        self.assertEqual(self.bodiesBut(self.body, self.right), [])
        merge = PartDesign.mergeAfter(slot)
        self.assertIsNotNone(merge)
        self.assertIs(PartDesign.mergeAfter(slot), merge)
        self.assertEqual(self.right.MergedInto, merge)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertIs(self.body.Tip, merge)
        self.assertAlmostEqual(self.body.Shape.Volume, 36000, places=3)

    def testIntersectKeepsWhatEachShares(self):
        """Intersect with Enclosure on the merged slot: the Merge goes, each part keeps what it
        shares with the slot's tool (turned down into them): HALF each."""
        slot = self.mergedSlot()
        self.openEdit(slot)
        self.choose("Intersect with Enclosure")
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertEqual(slot.Operation, "Common")
        self.assertAlmostEqual(self.body.Shape.Volume, HALF, places=3)
        self.assertAlmostEqual(self.right.Shape.Volume, HALF, places=3)

    def testUntickingTheScopeFreesTheRows(self):
        """A pocket after the Merge builds on it: New part, Remove and Intersect greyed, naming it.
        Unticking Right in the open dialog offers them at once; New part then leaves Right whole,
        the pocket in the enclosure (16000 - 125), the slot a part of its own."""
        slot = self.mergedSlot(later=True)
        self.openEdit(slot)
        why = "'Corner' builds on 'Merge'"
        for text in ("New part", "Remove from Enclosure", "Intersect with Enclosure"):
            self.assertRefused(text, why)
        merge = self.visible(QtWidgets.QListWidget, "mergeList")
        self.assertIsNotNone(merge)
        merge.item(0).setCheckState(QtCore.Qt.Unchecked)
        pump(0.2)
        for text in ("New part", "Remove from Enclosure", "Intersect with Enclosure"):
            self.assertOffered(text)
        self.choose("New part")
        [part] = self.bodiesBut(self.body, self.right)
        self.assertIs(slot.getParentGeoFeatureGroup(), part)
        self.assertIs(self.corner.BaseFeature, self.base)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(self.body.Shape.Volume, 16000 - 125, places=3)
        self.assertAlmostEqual(self.right.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(part.Shape.Volume, SLOT, places=3)
