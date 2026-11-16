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

    def refusalNote(self):
        """The text of the line under the Result row that says why rows are greyed (round 9), or
        None while it is hidden"""
        note = self.visible(QtWidgets.QLabel, "refusalNote")
        return note.text() if note is not None else None

    def mirroredBoss(self, onDatum=None, datumFirst=False):
        """J17's variant B: Part1 40 x 30 x 10 over x -20..20 (12000); BossB 8 x 8 x 5 on its top
        at (-10, 15) (320), its sketch on that face; Mirrored of it about the Right plane, or about
        a datum plane: onDatum "origin" (on the Right plane), "face" (on Part1's +x side, offset
        20 back to x = 0) or "boss" (the same face picked on the boss's result, which is Part1's
        material: review R9-1); with datumFirst the plane is made before the boss. Returns (boss
        sketch, boss, mirror, datum or None); Part1 is 12640."""
        body = self.doc.addObject("PartDesign::Body", "Part1")
        base = pad(body, "Base", sketch(body, "BaseSk", xyPlane(body), (-20, 0, 20, 30)), 10)
        self.doc.recompute()
        boss = None
        right = body.Origin.OriginFeatures[5]
        datum = None

        def makeDatum():
            datum = body.newObject("PartDesign::Plane", "DatumPlane")
            if onDatum == "origin":
                datum.AttachmentSupport = [(right, "")]
            else:
                support = boss if onDatum == "boss" else base
                [side] = [
                    f"Face{i}"
                    for i, face in enumerate(support.Shape.Faces, 1)
                    if abs(face.normalAt(0, 0).x - 1) < 1e-9 and abs(face.CenterOfMass.x - 20) < 1e-6
                ]
                datum.AttachmentSupport = [(support, side)]
                datum.AttachmentOffset = App.Placement(App.Vector(0, 0, -20), App.Rotation())
            datum.MapMode = "FlatFace"
            self.doc.recompute()
            self.assertLess(abs(datum.Placement.Base.x), 1e-6)
            return datum

        if onDatum and datumFirst:
            datum = makeDatum()
        bossSk = body.newObject("Sketcher::SketchObject", "BossSk")
        bossSk.AttachmentSupport = [(base, faceAt(base, 10))]
        bossSk.MapMode = "FlatFace"
        rect(bossSk, -14, 11, -6, 19)
        boss = pad(body, "BossB", bossSk, 5)
        self.doc.recompute()
        if onDatum and not datumFirst:
            datum = makeDatum()
        mirror = body.newObject("PartDesign::Mirrored", "Mirrored")
        mirror.Originals = [boss]
        mirror.MirrorPlane = (datum or right, [""])
        body.Tip = mirror
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(body.Shape.Volume, 12640, places=3)
        self.body, self.base = body, base
        return bossSk, boss, mirror, datum

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
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertOffered("New")
        self.choose("New")
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
        self.choose("New")
        self.choose("Add")
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
        self.choose("New")
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
        self.assertOffered("New")
        self.choose("New")
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
        self.assertRefused("New", "'TopSk' uses 'Fillet'")
        for text in ROWS[2:]:
            self.assertOffered(text)

    def testAFilletOnTheEnclosureStays(self):
        """A fillet on the enclosure's bottom edges right after the boss (its Base the boss): none
        of its edges touches the boss, so New part is offered, and the fillet stays with the
        enclosure on the base (review R5-2; Onshape keeps it on Part 1)."""
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
        before = self.body.Shape.Volume
        self.openEdit(boss)
        self.assertOffered("New")
        self.choose("New")
        [part] = self.bodiesBut(self.body)
        self.assertEqual(part.Group, [bossSk, boss])
        self.assertIs(fillet.BaseFeature, self.base)
        self.assertIs(self.body.Tip, fillet)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(part.Shape.Volume, 2000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, before - 2000, places=3)


    def testANewPartWithItsMirrorGoesBackToAdd(self):
        """J17's variant B (round 9): BossB switched to New takes its mirror along (Part 2, 640).
        Edited again, Add is offered, no refusal shown; Cancel leaves both parts. Add, OK: one part,
        the mirror merged (12000 plus both bosses), in one undo step; undo: two parts again."""
        bossSk, boss, mirror, datum = self.mirroredBoss()
        self.openEdit(boss)
        self.choose("New")
        [part] = self.bodiesBut(self.body)
        self.assertEqual(part.Group, [bossSk, boss, mirror])
        self.close(ok=True)
        self.doc.recompute()
        self.assertAlmostEqual(part.Shape.Volume, 640, places=3)
        partName = part.Name
        for ok in (False, True):
            self.openEdit(boss)
            self.assertEqual(self.combo().currentText(), "New")
            for text in ROWS[1:]:
                self.assertOffered(text)
            self.assertIsNone(self.refusalNote())
            self.choose("Add")
            self.assertEqual(self.bodiesBut(self.body), [])
            self.assertIs(Gui.getDocument(self.doc.Name).getInEdit().Object, boss)
            self.close(ok=ok)
            self.doc.recompute()
            if not ok:
                self.assertEqual(len(self.doc.UndoNames), self.undos)
                self.assertEqual(self.doc.getObject(partName).Group, [bossSk, boss, mirror])
                self.assertEqual([o.Name for o in self.body.Group], ["BaseSk", "Base"])
        self.assertValid()
        self.assertOneUndoStep()
        self.assertIsNone(self.doc.getObject(partName))
        self.assertEqual(
            [o.Name for o in self.body.Group], ["BaseSk", "Base", "BossSk", "BossB", "Mirrored"]
        )
        self.assertIs(self.body.Tip, mirror)
        self.assertIs(mirror.MirrorPlane[0], self.body.Origin.OriginFeatures[5])
        self.assertTrue(mirror.Visibility)
        self.assertAlmostEqual(self.body.Shape.Volume, 12640, places=3)
        self.doc.undo()
        self.doc.recompute()
        part = self.doc.getObject(partName)
        self.assertIsNotNone(part)
        self.assertEqual(part.Group, [bossSk, boss, mirror])
        self.assertAlmostEqual(part.Shape.Volume, 640, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 12000, places=3)

    def testAFilletedNewPartGoesBackToAdd(self):
        """J8's change of mind (round 9): the boss and its fillet made a new part, then Add in a
        later edit: the enclosure holds them where they were (WITH_BOSS), the new part gone."""
        bossSk, boss, fillet = self.bossWithFillet()
        group = self.body.Group
        self.openEdit(boss)
        self.choose("New")
        [part] = self.bodiesBut(self.body)
        self.close(ok=True)
        partName = part.Name
        self.openEdit(boss)
        self.assertOffered("Add")
        self.choose("Add")
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertIsNone(self.doc.getObject(partName))
        self.assertEqual(self.body.Group, group)
        self.assertIs(self.body.Tip, fillet)
        self.assertIs(fillet.BaseFeature, boss)
        self.assertAlmostEqual(self.body.Shape.Volume, WITH_BOSS, places=3)

    def testADatumOnTheOriginGoesAlong(self):
        """Round 9 item 2: the mirror about a datum plane on Part1's Right plane: New is offered and
        takes the datum along (Part 2 is the two bosses, 640; Part1 12000)."""
        bossSk, boss, mirror, datum = self.mirroredBoss("origin")
        self.openEdit(boss)
        self.assertOffered("New")
        self.assertIsNone(self.refusalNote())
        self.choose("New")
        [part] = self.bodiesBut(self.body)
        self.assertEqual(part.Group, [bossSk, boss, datum, mirror])
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertIs(datum.AttachmentSupport[0][0], part.Origin.OriginFeatures[5])
        self.assertAlmostEqual(part.Shape.Volume, 640, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 12000, places=3)

    def testADatumOnTheBossFaceKeepsTheRefusalShown(self):
        """Review R9-1: the datum plane on the +x side face picked on the boss's result (Part1's
        material): New greyed, the line under the Result row saying why."""
        bossSk, boss, mirror, datum = self.mirroredBoss("boss")
        self.assertIs(datum.AttachmentSupport[0][0], boss)
        self.openEdit(boss)
        why = "'DatumPlane' uses 'BossB', which would go to the new part"
        self.assertRefused("New", why)
        self.assertEqual(self.refusalNote(), "Can't switch to New: " + why)

    def testADatumOnWhatStaysKeepsTheRefusalShown(self):
        """J17's refusal, kept and now shown: the mirror about a datum plane on Part1's side face,
        which stays: New greyed, and the line under the Result row says why (round 9 item 3)."""
        bossSk, boss, mirror, datum = self.mirroredBoss("face")
        self.openEdit(boss)
        why = "'Mirrored' uses 'DatumPlane', which stays in 'Part1'"
        self.assertRefused("New", why)
        self.assertEqual(self.refusalNote(), "Can't switch to New: " + why)


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
        self.assertEqual(self.combo().currentText(), "Add")
        for text in ("New", "Remove", "Intersect"):
            self.assertOffered(text)
        self.choose("Remove")
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
        self.choose("New")
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
        self.choose("New")
        self.assertIsNone(PartDesign.mergeAfter(slot))
        self.assertIsNone(self.right.MergedInto)
        self.choose("Add")
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
        self.choose("Intersect")
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
        for text in ("New", "Remove", "Intersect"):
            self.assertRefused(text, why)
        merge = self.visible(QtWidgets.QListWidget, "mergeList")
        self.assertIsNotNone(merge)
        note = self.refusalNote()
        self.assertTrue(note.startswith("Can't switch to New, Remove or Intersect: " + why), note)
        merge.item(0).setCheckState(QtCore.Qt.Unchecked)
        pump(0.2)
        for text in ("New", "Remove", "Intersect"):
            self.assertOffered(text)
        self.assertIsNone(self.refusalNote())
        self.choose("New")
        [part] = self.bodiesBut(self.body, self.right)
        self.assertIs(slot.getParentGeoFeatureGroup(), part)
        self.assertIs(self.corner.BaseFeature, self.base)
        self.close(ok=True)
        self.doc.recompute()
        self.assertValid()
        self.assertAlmostEqual(self.body.Shape.Volume, 16000 - 125, places=3)
        self.assertAlmostEqual(self.right.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(part.Shape.Volume, SLOT, places=3)
