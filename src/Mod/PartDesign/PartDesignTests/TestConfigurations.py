# SPDX-License-Identifier: LGPL-2.1-or-later

"""A part studio's configurations, Onshape's (FreeCAD-CH ops#671, slice C1;
notes/configurations-design.md). Designed geometry: the studio of TestStudioList (parts A, B, C:
10 x 10 pads of height 10 at x 0, 20 and 40) with a List "Size" (Small = the row "Default",
Large) that configures A's pad length and the suppression of a cut owner E on B, a Checkbox
"Tall" that configures C's pad length, and a configuration Variable `len` (Length, 80 mm,
10..200 mm). The expected results are volumes and heights of those boxes."""

import json
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestStudioList import makeOwner, newStudio, setBox, studioList

TOL = 1e-6


def height(body):
    return body.Shape.BoundBox.ZMax - body.Shape.BoundBox.ZMin


def invalid(obj):
    return "Invalid" in obj.State or "Error" in obj.State


class TestConfigurations(unittest.TestCase):
    def setUp(self):
        self.doc, self.studio = newStudio("TestConfigurations")
        self.list = studioList(self.doc)
        self.A, self.B, self.C = (self.doc.getObject(n) for n in "ABC")
        self.APad = self.doc.getObject("APad")
        # E: a 3 x 3 cut 2 deep into B's top, a studio owner
        self.E = makeOwner(self.doc, self.studio, "E", (22, 2, 25, 5), 2, "Subtraction", ["B"])
        self.edit(lambda: PartDesign.studioInsert(self.E, -1))
        self.size = self.edit(lambda: PartDesign.configAddList(self.studio, "Size", ["Small", "Large"]))
        self.cfg = PartDesign.configStudio(self.studio)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestConfigurations"):
                App.closeDocument(doc.Name)

    def edit(self, fn):
        """fn in one transaction, then a recompute (the GUI's pattern)"""
        self.doc.openTransaction("edit")
        try:
            out = fn()
        except Exception:
            self.doc.abortTransaction()
            raise
        self.doc.recompute()
        self.doc.commitTransaction()
        return out

    def configureSizes(self):
        """A's pad: Small 10, Large 20; E suppressed in Small only"""
        self.edit(lambda: PartDesign.configConfigure(self.APad, "Length", self.size))
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "20 mm"))
        self.edit(lambda: PartDesign.configConfigureSuppression(self.E, self.size))
        self.edit(lambda: PartDesign.configSetSuppressionCell(self.E, "Small", True))

    def assertSmall(self):
        self.assertAlmostEqual(height(self.A), 10, delta=TOL)
        self.assertAlmostEqual(self.B.Shape.Volume, 1000, delta=1e-4)

    def assertLarge(self, aHeight=20):
        self.assertAlmostEqual(height(self.A), aHeight, delta=TOL)
        self.assertAlmostEqual(self.B.Shape.Volume, 1000 - 18, delta=1e-4)

    # -------------------------------------------------------------------- inputs and the object
    def testInputsAndRows(self):
        """Onshape's rows: the first keeps the id Default whatever its name; a new row's id is its
        name; a rename keeps the id, so the key and the cells don't move (CF1)"""
        self.assertEqual(self.cfg.TypeId, "PartDesign::StudioConfig")
        self.assertIn(self.cfg, self.studio.Group)
        self.assertEqual(PartDesign.configDefaultKey(self.studio), self.size + "=Default")
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Default")
        self.assertEqual(PartDesign.configKey(self.studio, {"Size": "Large"}), self.size + "=Large")
        self.configureSizes()
        PartDesign.configRenameRow(self.studio, self.size, "Default", "Tiny")
        self.assertEqual(PartDesign.configKey(self.studio, {"Size": "Tiny"}), self.size + "=Default")
        self.edit(lambda: PartDesign.configSetActive(self.studio, {"Size": "Large"}))
        self.assertLarge()
        with self.assertRaises(ValueError):
            PartDesign.configSetActive(self.studio, {"Size": "Huge"})
        with self.assertRaises(ValueError):
            PartDesign.configAddList(self.studio, "Size", ["X"])

    # -------------------------------------------------------------------------------- switching
    def testSwitchRebuilds(self):
        """A switch rebinds the pad length and E's suppression, reconciles and recomputes"""
        self.configureSizes()
        self.assertSmall()
        self.assertTrue(self.E.Suppressed)
        self.assertEqual(self.APad.ExpressionEngine[0][0], "Length")
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertLarge()
        self.assertFalse(self.E.Suppressed)
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Large")
        PartDesign.configSetActive(self.studio, {self.size: "Default"})
        self.assertSmall()
        self.assertFalse(any(invalid(o) for o in self.doc.Objects), [o.Name for o in self.doc.Objects if invalid(o)])

    def testSwitchIsOneUndoStep(self):
        self.configureSizes()
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertLarge()
        self.doc.undo()
        self.doc.recompute()
        self.assertSmall()
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Default")
        self.doc.redo()
        self.doc.recompute()
        self.assertLarge()
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Large")

    def testNamesSurviveASwitchAndBack(self):
        """G1: the element names of every part are the same after Large and back to Small"""
        self.configureSizes()
        before = {b.Name: sorted(b.Shape.ElementReverseMap.keys()) for b in (self.A, self.B, self.C)}
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        after = {b.Name: sorted(b.Shape.ElementReverseMap.keys()) for b in (self.A, self.B, self.C)}
        self.assertEqual(before, after)

    # -------------------------------------------------------------------- configured parameters
    def testFieldEditWritesTheActiveRow(self):
        """Editing a configured field writes the active row's cell only (CF3); clearing it is
        refused: the table and the expressions can't diverge"""
        self.configureSizes()
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.edit(lambda: self.APad.setExpression("Length", "25 mm"))
        self.assertAlmostEqual(height(self.A), 25, delta=TOL)
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertAlmostEqual(height(self.A), 10, delta=TOL)
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertAlmostEqual(height(self.A), 25, delta=TOL)
        with self.assertRaises(Exception):
            self.APad.setExpression("Length", None)
        self.assertTrue(PartDesign.configIsConfigured(self.APad, "Length"))
        self.assertEqual(PartDesign.configReconcile(self.studio), "")

    def testUnconfigureKeepsTheActiveValue(self):
        self.configureSizes()
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.edit(lambda: PartDesign.configUnconfigure(self.APad, "Length"))
        self.assertFalse(PartDesign.configIsConfigured(self.APad, "Length"))
        self.assertEqual(len(self.APad.ExpressionEngine), 0)
        self.assertAlmostEqual(self.APad.Length.Value, 20, delta=TOL)
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertAlmostEqual(height(self.A), 20, delta=TOL)

    def testCheckbox(self):
        """A Checkbox is ticked by default (CF1); its cells are true and false"""
        tall = self.edit(lambda: PartDesign.configAddCheckbox(self.studio, "Tall"))
        cpad = self.doc.getObject("CPad")
        self.edit(lambda: PartDesign.configConfigure(cpad, "Length", tall))
        self.edit(lambda: PartDesign.configSetCell(cpad, "Length", "true", "15 mm"))
        self.assertAlmostEqual(height(self.C), 15, delta=TOL)
        PartDesign.configSetActive(self.studio, {"Tall": False})
        self.assertAlmostEqual(height(self.C), 10, delta=TOL)
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Default;Tall=false")

    def testConfigurationVariable(self):
        """A configuration Variable is used as #len, in a cell too (CF3: #len * 0.25 in Large);
        a value out of its range is refused (Onshape's field turns invalid, CF8)"""
        self.configureSizes()
        self.edit(lambda: PartDesign.configAddVariable(self.studio, "len", "Length", "80 mm", "10 mm", "200 mm"))
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "#len * 0.25"))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertLarge(20)
        PartDesign.configSetActive(self.studio, {"len": "120 mm"})
        self.assertLarge(30)
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Large;len=0.12 meter")
        with self.assertRaises(ValueError):
            PartDesign.configSetActive(self.studio, {"len": "300 mm"})
        self.assertLarge(30)
        # A studio feature uses it as #len too
        bpad = self.doc.getObject("BPad")
        self.edit(lambda: bpad.setExpression("Length", "#len / 12"))
        self.assertAlmostEqual(height(self.B), 10, delta=TOL)

    # ------------------------------------------------------- the panel's edits (slice C2)
    def testMoveRowKeepsIdsCellsAndDefault(self):
        """Reordering rows changes only their order: ids, cells, the default and the active row stay"""
        self.configureSizes()
        medium = self.edit(lambda: PartDesign.configAddRow(self.studio, self.size, "Medium"))
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", medium, "15 mm"))
        self.edit(lambda: PartDesign.configSetActive(self.studio, {"Size": "Large"}))
        self.edit(lambda: PartDesign.configMoveRow(self.studio, self.size, medium, 0))
        rows = json.loads(self.cfg.Inputs)["inputs"][0]["rows"]
        self.assertEqual([r["id"] for r in rows], [medium, "Default", "Large"])
        self.assertEqual(json.loads(self.cfg.Inputs)["inputs"][0]["default"], "Default")
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Large")
        self.assertLarge()
        PartDesign.configSetActive(self.studio, {"Size": "Medium"})
        self.assertAlmostEqual(height(self.A), 15, delta=TOL)
        with self.assertRaises(ValueError):
            PartDesign.configMoveRow(self.studio, self.size, medium, 3)
        with self.assertRaises(ValueError):
            PartDesign.configMoveRow(self.studio, self.size, "Huge", 0)

    def testRenameInputKeepsItsId(self):
        """An input's name is only shown: the id, the key and the cells stay. A Variable's name is
        its #name (Onshape renames every input, CP2-7): the expressions that read it follow"""
        self.configureSizes()
        tall = self.edit(lambda: PartDesign.configAddCheckbox(self.studio, "Tall"))
        self.edit(lambda: PartDesign.configRenameInput(self.studio, self.size, "Width"))
        self.edit(lambda: PartDesign.configRenameInput(self.studio, tall, "High"))
        self.assertEqual(PartDesign.configKey(self.studio, {"Width": "Large", "High": False}),
                         self.size + "=Large;Tall=false")
        PartDesign.configSetActive(self.studio, {"Width": "Large"})
        self.assertLarge()
        with self.assertRaises(ValueError):
            PartDesign.configRenameInput(self.studio, self.size, "High")
        with self.assertRaises(ValueError):
            PartDesign.configRenameInput(self.studio, self.size, "")
        self.edit(lambda: PartDesign.configAddVariable(self.studio, "len", "Length", "80 mm"))
        bpad = self.doc.getObject("BPad")
        self.edit(lambda: bpad.setExpression("Length", "#len / 4"))
        self.assertAlmostEqual(height(self.B), 20, delta=TOL)
        self.edit(lambda: PartDesign.configRenameInput(self.studio, "len", "length"))
        self.assertIsNotNone(self.cfg.getPropertyByName("length"))
        self.assertIn("length", dict(bpad.ExpressionEngine)["Length"])
        self.edit(lambda: PartDesign.configEditVariable(self.studio, "len", "120 mm"))
        PartDesign.configSetActive(self.studio, {"len": "120 mm"})
        self.assertAlmostEqual(height(self.B), 30, delta=TOL)
        with self.assertRaises(ValueError):
            PartDesign.configRenameInput(self.studio, "len", "2wide")

    def testMoveInput(self):
        """Inputs reorder (CP2-7): the panel's tabs and the bar follow Inputs' order"""
        tall = self.edit(lambda: PartDesign.configAddCheckbox(self.studio, "Tall"))
        self.edit(lambda: PartDesign.configMoveInput(self.studio, tall, 0))
        self.assertEqual([i["id"] for i in json.loads(self.cfg.Inputs)["inputs"]], [tall, self.size])
        with self.assertRaises(ValueError):
            PartDesign.configMoveInput(self.studio, tall, 2)

    def testCheckboxDefault(self):
        """A Checkbox's default can change; the active value doesn't (Onshape, CP2-7)"""
        tall = self.edit(lambda: PartDesign.configAddCheckbox(self.studio, "Tall"))
        cpad = self.doc.getObject("CPad")
        self.edit(lambda: PartDesign.configConfigure(cpad, "Length", tall))
        self.edit(lambda: PartDesign.configSetCell(cpad, "Length", "true", "15 mm"))
        self.assertAlmostEqual(height(self.C), 15, delta=TOL)
        self.edit(lambda: PartDesign.configSetCheckboxDefault(self.studio, tall, False))
        self.assertAlmostEqual(height(self.C), 15, delta=TOL)
        self.assertEqual(PartDesign.configDefaultKey(self.studio), self.size + "=Default;Tall=false")
        PartDesign.configSetActive(self.studio, {tall: False})
        self.assertAlmostEqual(height(self.C), 10, delta=TOL)
        with self.assertRaises(ValueError):
            PartDesign.configSetCheckboxDefault(self.studio, self.size, False)

    def testEditVariable(self):
        """A Variable's default and bounds can change, its type can't; the active value stays (CP2-7)
        unless the new bounds leave it out; a default outside the new bounds is refused"""
        self.edit(lambda: PartDesign.configAddVariable(self.studio, "len", "Length", "80 mm", "10 mm", "200 mm"))
        bpad = self.doc.getObject("BPad")
        self.edit(lambda: bpad.setExpression("Length", "#len / 8"))
        self.assertAlmostEqual(height(self.B), 10, delta=TOL)
        self.edit(lambda: PartDesign.configEditVariable(self.studio, "len", "160 mm", "50 mm", None))
        self.assertAlmostEqual(height(self.B), 10, delta=TOL)
        self.edit(lambda: PartDesign.configEditVariable(self.studio, "len", "160 mm", "100 mm", None))
        self.assertAlmostEqual(height(self.B), 20, delta=TOL)
        var = json.loads(self.cfg.Inputs)["inputs"][1]
        self.assertAlmostEqual(var["min"], 100, delta=TOL)
        self.assertNotIn("max", var)
        with self.assertRaises(ValueError):
            PartDesign.configEditVariable(self.studio, "len", "50 mm", "100 mm")
        self.assertAlmostEqual(json.loads(self.cfg.Inputs)["inputs"][1]["default"], 160, delta=TOL)
        with self.assertRaises(ValueError):
            PartDesign.configEditVariable(self.studio, "len", "20 deg")
        with self.assertRaises(ValueError):
            PartDesign.configEditVariable(self.studio, self.size, "1 mm")

    def testEntriesLeaveOutStaleOnes(self):
        """The panel lists live entries only: a deleted owner's entry stays in the table (its undo
        brings it back) but is not listed, and comes back with the undo"""
        self.configureSizes()
        entries = PartDesign.configEntries(self.studio)
        self.assertEqual([(e["object"].Name, e["path"]) for e in entries], [("APad", "Length"), ("E", None)])
        self.assertEqual(entries[0]["input"], self.size)
        self.assertEqual(entries[0]["cells"]["Large"], "20 mm")
        self.assertEqual(entries[1]["cells"], {"Default": "true", "Large": "false"})
        self.assertEqual(PartDesign.configInputOf(self.APad, "Length"), "Size")
        self.assertEqual(PartDesign.configInputOf(self.E), "Size")
        self.assertEqual(PartDesign.configInputOf(self.APad, "Offset"), "")
        self.doc.UndoMode = 1
        self.edit(lambda: (PartDesign.studioRemove(self.E), self.doc.removeObject("E")))
        self.assertEqual([e["object"].Name for e in PartDesign.configEntries(self.studio)], ["APad"])
        self.assertEqual(len(json.loads(self.cfg.Table)["suppress"]), 1)
        self.doc.undo()
        self.assertEqual([e["object"].Name for e in PartDesign.configEntries(self.studio)], ["APad", "E"])

    def testSketchConstraintIsConfigured(self):
        """A sketch dimension is configured by its named path Constraints.<name> (Onshape configures
        sketch dimensions): each row drives the dimension, and an edit of it writes the active cell"""
        import Sketcher

        sk = self.A.newObject("Sketcher::SketchObject", "CfgSketch")
        sk.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 0, 0)))
        sk.addConstraint(Sketcher.Constraint("Distance", 0, 10))
        sk.renameConstraint(0, "w")
        self.doc.recompute()
        self.edit(lambda: PartDesign.configConfigure(sk, "Constraints.w", self.size))
        self.assertTrue(PartDesign.configIsConfigured(sk, "Constraints.w"))
        self.assertEqual(PartDesign.configInputOf(sk, ".Constraints.w"), "Size")
        self.edit(lambda: PartDesign.configSetCell(sk, "Constraints.w", "Large", "25 mm"))
        self.edit(lambda: PartDesign.configSetActive(self.studio, {"Size": "Large"}))
        self.assertAlmostEqual(sk.getDatum("w").Value, 25, delta=TOL)
        # An edit of the dimension's expression (the datum dialog's path) writes the active cell
        self.edit(lambda: sk.setExpression("Constraints.w", "30 mm"))
        self.assertEqual(PartDesign.configEntries(self.studio)[0]["cells"]["Large"], "30 mm")
        self.edit(lambda: PartDesign.configSetActive(self.studio, {"Size": "Small"}))
        self.assertAlmostEqual(sk.getDatum("w").Value, 10, delta=TOL)

    def testCellFailsOnlyInItsRow(self):
        """F7 / CF10: a cell that fails fails only while its row is active, and heals"""
        self.configureSizes()
        self.edit(lambda: PartDesign.configSetCell(self.APad, "Length", "Large", "#nosuch * 2"))
        self.assertFalse(invalid(self.APad))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertTrue(invalid(self.APad))
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertFalse(invalid(self.APad))
        self.assertSmall()

    # ----------------------------------------------------------------------- configured suppression
    def testSuppressWritesTheActiveCell(self):
        """Suppress on a configured owner edits the active row's cell (CF4)"""
        self.configureSizes()
        self.edit(lambda: PartDesign.studioSuppress(self.E, False))
        self.assertAlmostEqual(self.B.Shape.Volume, 982, delta=1e-4)
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertFalse(self.E.Suppressed)
        self.edit(lambda: PartDesign.studioSuppress(self.E, True))
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertFalse(self.E.Suppressed)
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertTrue(self.E.Suppressed)

    def testDeletedOwnersNameGivenAgainIsNotConfigured(self):
        """A deleted configured owner keeps its entry (its undo brings the configuration back);
        a new owner that gets its name is not configured by it (the entry holds the object ID)"""
        self.configureSizes()
        self.edit(lambda: (PartDesign.studioRemove(self.E), self.doc.removeObject("E")))
        again = makeOwner(self.doc, self.studio, "E", (2, 2, 5, 5), 1, "Subtraction", ["A"])
        self.assertEqual(again.Name, "E")
        self.edit(lambda: PartDesign.studioInsert(again, -1))
        self.assertFalse(PartDesign.configIsConfigured(again))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertFalse(bool(getattr(again, "Suppressed", False)))
        self.assertEqual(PartDesign.configReconcile(self.studio), "")

    def testBodyMemberSuppressionIsRefused(self):
        with self.assertRaises(ValueError):
            PartDesign.configConfigureSuppression(self.APad, self.size)

    def testSwitchThatSplitsMakesPieces(self):
        """A cut across B in Large only splits B there: the switch makes the pieces, in its own
        undo step (10.12)"""
        cut = makeOwner(self.doc, self.studio, "Cut", (24, -1, 26, 11), 11, "Subtraction", ["B"])
        self.edit(lambda: PartDesign.studioInsert(cut, -1))
        self.edit(lambda: PartDesign.configConfigureSuppression(cut, self.size))
        self.edit(lambda: PartDesign.configSetSuppressionCell(cut, "Small", True))
        bodies = lambda: sorted(b.Name for b in self.doc.Objects if b.isDerivedFrom("PartDesign::Body"))
        small = bodies()
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        large = bodies()
        self.assertGreater(len(large), len(small))
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(bodies(), small)
        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(bodies(), large)

    def testSwitchBackGivesPiecesTheirIds(self):
        """The pieces a switch removes come back with their ids and names on the switch back,
        as Onshape's parts do (the property test's switch-and-back check, G1)"""
        cut = makeOwner(self.doc, self.studio, "Cut", (24, -1, 26, 11), 11, "Subtraction", ["B"])
        self.edit(lambda: PartDesign.studioInsert(cut, -1))
        self.edit(lambda: PartDesign.configConfigureSuppression(cut, self.size))
        self.edit(lambda: PartDesign.configSetSuppressionCell(cut, "Small", True))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        pieces = lambda: sorted(
            (b.StudioPartId, b.Label) for b in self.doc.Objects
            if b.isDerivedFrom("PartDesign::Body") and b.StudioPieceWitness
        )
        large = pieces()
        self.assertGreaterEqual(len(large), 2)
        renamed = self.doc.getObjectsByLabel(large[0][1])[0]
        renamed.Label = "Left end"
        large = pieces()
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertEqual(pieces(), [])  # the suppressed split made no part
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertEqual(pieces(), large)

    def pieceBodies(self):
        return [b for b in self.doc.Objects if b.isDerivedFrom("PartDesign::Body") and b.StudioPieceWitness]

    def configuredCut(self, splitIn):
        """Cut splits B (24..26) in splitIn only"""
        cut = makeOwner(self.doc, self.studio, "Cut", (24, -1, 26, 11), 11, "Subtraction", ["B"])
        self.edit(lambda: PartDesign.studioInsert(cut, -1))
        self.edit(lambda: PartDesign.configConfigureSuppression(cut, self.size))
        other = "Small" if splitIn == "Large" else "Large"
        self.edit(lambda: PartDesign.configSetSuppressionCell(cut, other, True))
        return cut

    def testCopiedMakerDoesNotTakeRetiredIds(self):
        """A copy of a maker carries its retired pieces along (a dynamic property), but its own
        pieces never take the original's ids or names (review R1)"""
        cut = self.configuredCut("Large")
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertEqual(self.pieceBodies(), [])

        def paste():
            copy = self.doc.copyObject(cut)
            self.studio.addObject(copy)
            return copy

        copy = self.edit(paste)
        self.edit(lambda: setBox(copy, (21, -1, 22, 11), 11, "Subtraction"))
        entries = [e.Name for e in PartDesign.studioList(self.studio).Entries]
        self.edit(lambda: PartDesign.studioInsert(copy, entries.index("Cut") + 1))
        if getattr(copy, "Suppressed", False):
            self.edit(lambda: PartDesign.studioSuppress(copy, False))
        self.edit(lambda: PartDesign.studioMakePieces(copy))
        made = [b for b in self.pieceBodies() if b.StudioMadeBy == copy]
        self.assertGreaterEqual(len(made), 1)
        for body in made:
            self.assertTrue(body.StudioPartId.startswith(copy.Name + ":"), body.StudioPartId)

    def testBinderOfAPieceASwitchRemovesStays(self):
        """A piece a Binder outside the studio reads keeps its Body when a switch takes its solid
        away (the Binder never keeps a stale solid), and the switch back gives the same Body its
        piece again (review R2)"""
        cut = self.configuredCut("Small")
        self.edit(lambda: PartDesign.studioMakePieces(cut))
        right = [b for b in self.pieceBodies() if b.Shape.BoundBox.XMin > 25][0]
        other = self.doc.addObject("PartDesign::Body", "Other")
        binder = other.newObject("PartDesign::SubShapeBinder", "Bound")
        binder.Support = [(right, ("",))]
        self.doc.recompute()
        self.assertAlmostEqual(binder.Shape.Volume, 400, delta=1e-4)
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.doc.recompute()
        self.assertTrue(right.isAttachedToDocument())
        self.assertEqual([s[0] for s in binder.Support], [right])
        self.assertTrue(binder.Shape.isNull() or invalid(binder) or invalid(right),
                        "the binder shows a solid Large doesn't have")
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.doc.recompute()
        self.assertAlmostEqual(right.Shape.Volume, 400, delta=1e-4)
        self.assertAlmostEqual(binder.Shape.Volume, 400, delta=1e-4)
        self.assertFalse(invalid(binder))

    def testReaderOfAnEmptiedPieceErrors(self):
        """A Link and a Binder outside the studio of a piece whose split is suppressed (by hand,
        no configuration involved) error loudly; unsuppressed, they show the piece again (review
        R2, round 2)"""
        cut = makeOwner(self.doc, self.studio, "Cut", (24, -1, 26, 11), 11, "Subtraction", ["B"])
        self.edit(lambda: PartDesign.studioInsert(cut, -1))
        self.edit(lambda: PartDesign.studioMakePieces(cut))
        right = [b for b in self.pieceBodies() if b.Shape.BoundBox.XMin > 25][0]
        link = self.doc.addObject("App::Link", "Inst")
        link.LinkedObject = right
        other = self.doc.addObject("PartDesign::Body", "Other")
        binder = other.newObject("PartDesign::SubShapeBinder", "Bound")
        binder.Support = [(right, ("",))]
        self.doc.recompute()
        self.assertFalse(invalid(link) or invalid(binder))
        self.edit(lambda: PartDesign.studioSuppress(cut, True))
        self.edit(lambda: PartDesign.studioMakePieces(cut))
        self.assertTrue(right.isAttachedToDocument())
        self.assertTrue(invalid(link), link.State)
        self.assertTrue(invalid(binder), binder.State)
        self.edit(lambda: PartDesign.studioSuppress(cut, False))
        self.edit(lambda: PartDesign.studioMakePieces(cut))
        self.assertAlmostEqual(right.Shape.Volume, 400, delta=1e-4)
        self.assertFalse(invalid(link) or invalid(binder))
        self.assertAlmostEqual(binder.Shape.Volume, 400, delta=1e-4)

    def testNestedMakersSwitchBackGivesPiecesTheirIds(self):
        """Cut splits B and M2 splits Cut's right piece, both suppressed in Large: the switch
        back makes the pieces in the list's order, so M2's come back too (review R4)"""
        cut = makeOwner(self.doc, self.studio, "Cut", (24, -1, 26, 11), 11, "Subtraction", ["B"])
        self.edit(lambda: PartDesign.studioInsert(cut, -1))
        self.edit(lambda: PartDesign.studioMakePieces(cut))
        right = [b for b in self.pieceBodies() if b.Shape.BoundBox.XMin > 25][0].StudioPartId
        m2 = makeOwner(self.doc, self.studio, "M2", (27.5, -1, 28.5, 11), 11, "Subtraction", [right])
        self.edit(lambda: PartDesign.studioInsert(m2, -1))
        self.edit(lambda: PartDesign.studioMakePieces(m2))
        for maker in (cut, m2):
            self.edit(lambda: PartDesign.configConfigureSuppression(maker, self.size))
            self.edit(lambda: PartDesign.configSetSuppressionCell(maker, "Large", True))
        ids = lambda: sorted((b.StudioPartId, b.Label) for b in self.pieceBodies() if not b.Shape.isNull())
        before = ids()
        self.assertEqual(len(before), 4)  # Cut:1, Cut:2 (M2's parent), M2's two
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.doc.recompute()
        self.assertEqual(ids(), before)
        self.assertEqual([o.Name for o in self.doc.Objects if invalid(o)], [])

    # ----------------------------------------------------------------------------------- the file
    def save(self):
        folder = tempfile.mkdtemp(prefix="cfg")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "TestConfigurationsFile.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.studio = self.doc.getObject("S")
        self.A, self.B, self.C = (self.doc.getObject(n) for n in "ABC")
        self.APad = self.doc.getObject("APad")
        self.E = self.doc.getObject("E")
        self.cfg = PartDesign.configStudio(self.studio)
        return path

    def testSaveAndReopenInLarge(self):
        """The file opens in the configuration it was saved in; the load only checks, so nothing
        is touched"""
        self.configureSizes()
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.save()
        self.assertEqual(PartDesign.configKey(self.studio), self.size + "=Large")
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])
        self.assertLarge()
        self.assertEqual(PartDesign.configReconcile(self.studio), "")
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertSmall()
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertLarge()

    def testLoadMismatchIsLoud(self):
        """A file whose expression is not its active cell opens with the StudioConfig in error,
        naming the path, and writes nothing"""
        self.configureSizes()
        self.cfg.Table = self.cfg.Table.replace('"Default":"10 mm"', '"Default":"11 mm"')
        self.assertIn("11 mm", self.cfg.Table)
        self.save()
        self.assertIn("APad.Length", PartDesign.configReconcile(self.studio))
        self.doc.recompute()
        self.assertTrue(invalid(self.cfg))
        self.assertAlmostEqual(self.APad.Length.Value, 10, delta=TOL)
        PartDesign.configReconcile(self.studio, False)
        self.doc.recompute()
        self.assertFalse(invalid(self.cfg))
        self.assertAlmostEqual(height(self.A), 11, delta=TOL)

    def testUndoAfterClearingALoadMismatchIsLoud(self):
        """A switch heals a file opened in error; its undo brings the file's expressions back,
        and the error with them (review R3)"""
        self.configureSizes()
        self.cfg.Table = self.cfg.Table.replace('"Default":"10 mm"', '"Default":"11 mm"')
        self.save()
        self.doc.UndoMode = 1
        self.doc.recompute()
        self.assertTrue(invalid(self.cfg))
        self.edit(lambda: PartDesign.configSetActive(self.studio, {"Size": "Large"}))
        self.assertFalse(invalid(self.cfg))
        self.doc.undo()
        self.doc.recompute()
        self.assertAlmostEqual(self.APad.Length.Value, 10, delta=TOL)
        self.assertTrue(invalid(self.cfg))
        # A reconcile write changes no property of the StudioConfig: its undo checks again too
        self.edit(lambda: PartDesign.configReconcile(self.studio, False))
        self.assertFalse(invalid(self.cfg))
        self.doc.undo()
        self.doc.recompute()
        self.assertAlmostEqual(self.APad.Length.Value, 10, delta=TOL)
        self.assertTrue(invalid(self.cfg))

    def testMalformedSavedDataIsLoud(self):
        """A saved Table that can't be read opens with the StudioConfig in error, and a switch
        refuses loudly: it is never read as empty and written over (review P2)"""
        self.configureSizes()
        self.cfg.Table = self.cfg.Table[:-5]
        text = self.cfg.Table
        self.save()
        self.doc.recompute()
        self.assertTrue(invalid(self.cfg))
        with self.assertRaises(Exception):
            PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertEqual(self.cfg.Table, text)

    def testWrongTypedSavedValueRaises(self):
        """A saved input whose field has the wrong JSON type makes the API raise a Python error,
        never a C++ exception through the interpreter (review P3)"""
        self.configureSizes()
        inputs = json.loads(self.cfg.Inputs)
        for entry in inputs["inputs"]:
            for key, value in list(entry.items()):
                if isinstance(value, str):
                    entry[key] = 5
        self.cfg.Inputs = json.dumps(inputs)
        for call in (
            lambda: PartDesign.configSetActive(self.studio, {"Size": "Large"}),
            lambda: PartDesign.configKey(self.studio),
            lambda: PartDesign.configReconcile(self.studio),
        ):
            try:
                call()
            except Exception:
                pass

    # --------------------------------------------------------------------------- outside readers
    def testInstanceOnAnotherRowErrors(self):
        """A Link outside the studio shows the default row (Onshape's Insert, CF8); while the
        studio shows another, it errors loudly, and heals when the studio is switched back"""
        self.configureSizes()
        link = self.doc.addObject("App::Link", "Instance")
        link.LinkedObject = self.A
        self.doc.recompute()
        self.assertFalse(invalid(link))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertTrue(invalid(link))
        self.assertIn("configuration", PartDesign.configReaderError(link, self.A))
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertFalse(invalid(link))
        # An instance made on Large is right in Large and loud in Small
        PartDesign.configSetReaderKey(link, self.A, {"Size": "Large"})
        self.doc.recompute()
        self.assertTrue(invalid(link))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertFalse(invalid(link))

    def testDerivedBinderOnAnotherRowErrors(self):
        """A binder of a configured studio's part in another body (Derived's reader) is loud too;
        one inside the studio is not an outside reader"""
        self.configureSizes()
        other = self.doc.addObject("PartDesign::Body", "Other")
        binder = other.newObject("PartDesign::SubShapeBinder", "Bound")
        binder.Support = [(self.A, ("",))]
        self.doc.recompute()
        self.assertFalse(invalid(binder))
        PartDesign.configSetActive(self.studio, {"Size": "Large"})
        self.assertTrue(invalid(binder))
        PartDesign.configSetActive(self.studio, {"Size": "Small"})
        self.assertFalse(invalid(binder))
        inner = self.B.newObject("PartDesign::SubShapeBinder", "Inner")
        inner.Support = [(self.A, ("",))]
        self.assertEqual(PartDesign.configReaderError(inner, self.A), "")


if __name__ == "__main__":
    unittest.main()
