# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, the Onshape experiment, ranks 1 and 3a)

"""The merge scope in the Result box (ops#640 rank 1) and an empty scope (rank 3a), in the Gui. An
Add's box has Merge with all (MergeWithAll) and, while it is off, the Merge scope list of the
studio's other parts, a part merged by the feature ticked; OK sets the scope with
PartDesign.setMergeScope, whose Merge is accepted (no Warning) and has no row of its own in the
Features list. An Add, Remove or Intersect from New touching no part has an empty scope and is red,
"No merge scope selected"; Merge with all makes the Add a new part, and a tick in the scope moves
the feature into that part.

Designed geometry, TestMergeGui's: the enclosure 40 x 40 x 10 (16000) with its lid sketch (30 x 30
on its top; the pad's default length is 10, 9000), a part "Panel" 40 x 30 x 10 from (20, 0, 10)
(12000), which the lid pad overlaps in 10 x 30 x 10 (3000), and a part "Far" (100 away, 16000)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestStudio import pad

NO_SCOPE = "No merge scope selected"
LID = 16000 + 9000  # the enclosure with the lid pad
MERGED = LID + 12000 - 3000  # ...and Panel merged


class TestMergeScopeGui(ResultBoxGuiCase):
    def parts(self):
        self.enclosure()
        self.panel = self.part("Panel", (20, 0, 60, 30), 10)
        self.far = self.part("Far", (100, 0, 140, 40), 0)

    def openEdit(self, feature):
        self.assertFalse(self.doc.HasPendingTransaction)
        feature.ViewObject.doubleClicked()
        self.waitForPanel()

    def mergeWithAll(self):
        return self.visible(QtWidgets.QCheckBox, "mergeWithAll")

    def mergeList(self):
        return self.visible(QtWidgets.QListWidget, "mergeList")

    def mergeItems(self):
        rows = self.mergeList()
        self.assertIsNotNone(rows, "no Merge scope list")
        return [
            (rows.item(i).text(), rows.item(i).checkState() == QtCore.Qt.Checked)
            for i in range(rows.count())
        ]

    def testMergeWithAllMergesWhatTouches(self):
        """The lid pad's box: Merge with all, unticked, and the scope list (Panel touched first,
        then Far), nothing ticked. Merge with all ticked: the list hides. OK: Panel, which the
        tool touches, is merged in an accepted Merge right after the pad (no Warning); Far is
        not; MergeWithAll is stored. One undo step takes it all back. The lid pad is edited: made
        by the command it would open as New, as it touches two parts (hands-on check A-1)."""
        self.parts()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        before = sorted(o.Name for o in self.doc.Objects)
        self.openEdit(lid)
        box = self.mergeWithAll()
        self.assertIsNotNone(box, "no Merge with all")
        self.assertFalse(box.isChecked())
        self.assertEqual(self.mergeItems(), [("Panel", False), ("Far (doesn't touch)", False)])
        box.click()
        pump(0.3)
        self.assertIsNone(self.mergeList(), "the scope list stays with Merge with all")
        self.close(ok=True)
        merge = PartDesign.mergeAfter(lid)
        self.assertIsNotNone(merge)
        self.assertIs(self.panel.MergedInto, merge)
        self.assertIsNone(getattr(self.far, "MergedInto", None))
        self.assertTrue(lid.MergeWithAll)
        self.assertTrue(merge.MergeAccepted)
        self.assertNotIn("Warning", merge.State)
        self.assertAlmostEqual(self.body.Shape.Volume, MERGED, places=3)
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=3)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)

    def testATickMergesWithNoWarning(self):
        """Merge with all off, Panel ticked, OK: merged (MERGED), the Merge accepted, no
        Warning; MergeWithAll stays off. The lid pad is edited (A-1: the command opens it New)."""
        self.parts()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        self.openEdit(lid)
        self.mergeList().item(0).setCheckState(QtCore.Qt.Checked)
        self.close(ok=True)
        merge = PartDesign.mergeAfter(lid)
        self.assertIs(self.panel.MergedInto, merge)
        self.assertNotIn("Warning", merge.State)
        self.assertFalse(lid.MergeWithAll)
        self.assertAlmostEqual(self.body.Shape.Volume, MERGED, places=3)

    def testTheMergedPartShowsAfterOk(self):
        """Journey J18 (F4): Panel ticked, OK, the lid pad the last feature: the part shown is the
        Merge (the lid pad with Panel, MERGED), not the lid pad alone, whose edit's end showed it
        over the hidden Merge (Panel's material vanished from the view)."""
        self.parts()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        self.openEdit(lid)
        self.mergeList().item(0).setCheckState(QtCore.Qt.Checked)
        self.close(ok=True)
        merge = PartDesign.mergeAfter(lid)
        self.assertIsNotNone(merge)
        self.assertIs(self.body.Tip, merge)
        self.assertTrue(merge.Visibility, "the Merge, the part's result, is hidden")
        self.assertFalse(lid.Visibility, "the lid pad is drawn over the Merge")
        self.assertFalse(self.panel.Visibility)
        self.assertAlmostEqual(merge.Shape.Volume, MERGED, places=3)

    def testUntickUnmerges(self):
        """The lid pad with Panel in its scope, edited: Panel is listed ticked. Unticked, OK: the
        Merge is gone, Panel is a part again (shown, 12000), the enclosure LID."""
        self.parts()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        merge = PartDesign.setMergeScope(lid, [self.panel])
        self.doc.recompute()
        name = merge.Name
        self.openEdit(lid)
        self.assertEqual(self.mergeItems()[0], ("Panel", True))
        self.mergeList().item(0).setCheckState(QtCore.Qt.Unchecked)
        self.close(ok=True)
        self.assertIsNone(self.doc.getObject(name))
        self.assertIsNone(self.panel.MergedInto)
        self.assertTrue(self.panel.Visibility)
        self.assertAlmostEqual(self.panel.Shape.Volume, 12000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, LID, places=3)

    def testAnAddFromNewTouchingNothingIsRed(self):
        """Rank 3a (R7(a), R8): Far's pad, on New, set to Add: it touches no part, so its scope is
        empty: red, "No merge scope selected", Far empty; the box has Merge with all. Ticked:
        valid, a new part (16000). OK: Far 16000, valid, MergeWithAll stored."""
        self.parts()
        farPad = self.doc.getObject("FarPad")
        self.openEdit(farPad)
        self.assertEqual(self.combo().currentText(), "New")
        self.choose("Add")
        self.assertTrue(farPad.EmptyMergeScope)
        self.assertFalse(farPad.isValid())
        self.assertIn(NO_SCOPE, farPad.getStatusString())
        box = self.mergeWithAll()
        self.assertIsNotNone(box, "no Merge with all")
        box.click()
        self.assertTrue(waitFor(lambda: farPad.isValid()), farPad.getStatusString())
        self.close(ok=True)
        self.assertTrue(farPad.isValid(), farPad.getStatusString())
        self.assertTrue(farPad.MergeWithAll)
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=3)
        self.assertIs(farPad.getParentGeoFeatureGroup(), self.far)

    def testARemoveFromNewTouchingNothingIsRed(self):
        """Rank 3a: Far's pad, on New, set to Remove (offered now): red, "No merge scope
        selected". Cancel: Far as it was, 16000, valid."""
        self.parts()
        farPad = self.doc.getObject("FarPad")
        self.openEdit(farPad)
        combo = self.combo()
        model = combo.model()
        self.assertTrue(model.flags(model.index(2, 0)) & QtCore.Qt.ItemIsEnabled)
        self.choose("Remove")
        self.assertFalse(farPad.isValid())
        self.assertIn(NO_SCOPE, farPad.getStatusString())
        self.close(ok=False)
        self.doc.recompute()
        self.assertTrue(farPad.isValid(), farPad.getStatusString())
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=3)

    def testAnAddTouchingTwoPartsHasAnEmptyScope(self):
        """Hands-on check A-1 (c): a tool touching two parts merges neither by default. A part
        "Right" 40 x 40 x 10 from (40, 0), beside the enclosure: Panel's pad (on New) touches the
        enclosure and Right, so its Add row names no part, and Add is red, "No merge scope
        selected", the pad still in Panel; the enclosure and Right keep their 16000."""
        self.parts()
        right = self.part("Right", (40, 0, 80, 40), 0)
        panelPad = self.doc.getObject("PanelPad")
        self.openEdit(panelPad)
        self.assertEqual(self.combo().currentText(), "New")
        self.assertEqual(self.items(self.combo())[1], "Add")
        self.choose("Add")
        self.assertFalse(panelPad.isValid())
        self.assertIn(NO_SCOPE, panelPad.getStatusString())
        self.assertIs(panelPad.getParentGeoFeatureGroup(), self.panel)
        self.close(ok=False)
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(right.Shape.Volume, 16000, places=3)

    def testATickInAnEmptyScopeMovesTheFeature(self):
        """Far's pad as an Add with an empty scope (red); the enclosure ticked in the scope: the
        pad moves into the enclosure, its scope now (Add to Enclosure), valid; the enclosure holds
        both blocks (32000, apart), and Far goes."""
        self.parts()
        farPad = self.doc.getObject("FarPad")
        self.openEdit(farPad)
        self.choose("Add")
        rows = self.mergeList()
        self.assertIsNotNone(rows, "no Merge scope list")
        names = [rows.item(i).text().split(" (")[0] for i in range(rows.count())]
        rows.item(names.index("Enclosure")).setCheckState(QtCore.Qt.Checked)
        self.assertTrue(
            waitFor(lambda: self.combo() is not None
                    and self.combo().currentText() == "Add"),
            "the edit doesn't restart in the enclosure",
        )
        self.waitForPanel()
        self.assertIs(farPad.getParentGeoFeatureGroup(), self.body)
        self.assertFalse(farPad.EmptyMergeScope)
        self.assertTrue(farPad.isValid(), farPad.getStatusString())
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 32000, places=3)


class TestMergeScopeListGui(unittest.TestCase):
    """The Features list folds a Merge its feature's scope made into the feature's row (ops#640
    rank 1): no Merge row, and "Features (n)" doesn't count it. The bracket and panel of
    TestMergeScope, with the list in place of the tree as TestFeaturesViewGui has it."""

    def setUp(self):
        from PartDesignTests.TestStudio import sketch, xyPlane

        self.doc = App.newDocument("MergeScopeList")
        self.doc.UndoMode = 1
        self.param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.assertTrue(waitFor(lambda: self.view() is not None and self.view().isVisible()))
        self.list = self.view().findChild(QtWidgets.QListWidget, "featureList")
        self.title = self.view().findChild(QtWidgets.QLabel, "featuresTitle")
        doc = self.doc
        self.bracket = doc.addObject("PartDesign::Body", "Bracket")
        self.bracketPad = pad(
            self.bracket,
            "BracketPad",
            sketch(self.bracket, "BracketSk", xyPlane(self.bracket), (0, 0, 40, 40)),
            10,
        )
        self.panel = doc.addObject("PartDesign::Body", "Panel")
        self.panelPad = pad(
            self.panel,
            "PanelPad",
            sketch(self.panel, "PanelSk", xyPlane(self.panel), (20, 0, 60, 30)),
            10,
        )
        doc.recompute()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(doc.Name, self.bracket.Name)
        Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", self.bracket)
        pump(0.3)

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        self.showTree(self.savedTree)
        pump()

    def showTree(self, tree):
        if self.param.GetBool("ShowModelTree", False) != tree:
            Gui.runCommand("PartDesign_ToggleModelTree")

    def view(self):
        return Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")

    def rows(self):
        return [self.list.item(i).text() for i in range(self.list.count())]

    def partRows(self):
        parts = self.view().findChild(QtWidgets.QTreeWidget, "partsList")
        return [parts.topLevelItem(i).text(0) for i in range(parts.topLevelItemCount())]

    def testTheMergeHasNoRow(self):
        """Before: four rows (two sketches, two pads). The panel in the bracket pad's scope: the
        same four rows, no Merge row, "Features (4)". Unmerged: the same again."""
        self.assertTrue(waitFor(lambda: "BracketPad" in self.rows()), self.rows())
        self.assertTrue(waitFor(lambda: "Panel" in self.partRows()), self.partRows())
        count = self.title.text()
        merge = PartDesign.setMergeScope(self.bracketPad, [self.panel])
        self.doc.recompute()
        # The lists rebuilt: the merged panel left the Parts list (lists rank 9)
        self.assertTrue(waitFor(lambda: "Panel" not in self.partRows()), self.partRows())
        self.assertTrue(waitFor(lambda: self.title.text() == count), self.title.text())
        self.assertNotIn(merge.Label, self.rows())
        self.assertIn("BracketPad", self.rows())
        PartDesign.setMergeScope(self.bracketPad, [])
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: "Panel" in self.partRows()), self.partRows())
        self.assertTrue(waitFor(lambda: self.title.text() == count), self.title.text())


if __name__ == "__main__":
    unittest.main()
