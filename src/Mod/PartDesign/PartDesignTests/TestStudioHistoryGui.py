# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (S3): the Features list on the studio's list
#
# The Features list's rows are the studio's list (PartDesign::StudioList): one row per studio
# feature (owner), none for its steps; the bar, a drag, Suppress and Delete on a row are list edits
# in one undo step each (notes/parts-design.md 3.5).
#
# Designed geometry only: TestStudioList's three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50),
# here at the document's top level (the studio the Features list shows without an active Body), and
# two owners (a Part::Box with Operation and StudioScope): F1 cuts A and B, F2 cuts B and C. Expected
# volumes come from Part booleans of the boxes. Off screen: QT_QPA_PLATFORM=offscreen
# (notes/build.md).

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests import TestFeaturesViewGui as fv
from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestStudioList import NATIVES, PARTS, chainOf, isStep, setBox, toolBox

V = App.Vector
F1 = ([5, 2, 25, 8], 2, "Subtraction", ["A", "B"])
F2 = ([22, 2, 45, 8], 3, "Subtraction", ["B", "C"])
NATIVE_ROWS = ["ASk", "APad", "BSk", "BPad", "CSk", "CPad"]
EXPECTED = NATIVE_ROWS + ["F1", "F2", "|"]


def tool(rect, depth, op):
    length, width, height, corner = toolBox(rect, depth, op)
    return Part.makeBox(length, width, height, corner)


def partBox(part):
    return Part.makeBox(10, 10, 10, V(dict(PARTS)[part], 0, 0))


class TestStudioHistoryGui(unittest.TestCase):
    # The Features list's drivers (TestFeaturesViewGui's)
    showTree = fv.TestFeaturesViewGui.showTree
    view = fv.TestFeaturesViewGui.view
    rows = fv.TestFeaturesViewGui.rows
    rowRect = fv.TestFeaturesViewGui.rowRect
    barRect = fv.TestFeaturesViewGui.barRect
    dragBarAfter = fv.TestFeaturesViewGui.dragBarAfter
    dragRowTo = fv.TestFeaturesViewGui.dragRowTo
    menuAction = fv.TestFeaturesViewGui.menuAction

    def setUp(self):
        self.doc = App.newDocument("StudioHistoryGui")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        self.param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.assertTrue(fv.waitFor(lambda: self.view() is not None and self.view().isVisible()))
        self.list = self.view().findChild(QtWidgets.QListWidget, "featureList")
        for p, x in PARTS:
            body = self.doc.addObject("PartDesign::Body", p)
            pad(body, p + "Pad", sketch(body, p + "Sk", xyPlane(body), (x, 0, x + 10, 10)), 10)
        self.doc.recompute()
        self.f1 = self.owner("F1", *F1)
        self.f2 = self.owner("F2", *F2)
        self.assertTrue(fv.waitFor(lambda: self.rows() == EXPECTED), self.rows())

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            fv.pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(self.savedTree)
        fv.pump()

    def owner(self, name, rect, depth, op, scope):
        """A shape owner at the top level (TestStudioList's makeOwner, without an App::Part)."""
        box = self.doc.addObject("Part::Box", name)
        box.addProperty("App::PropertyString", "Operation", "Studio")
        box.Operation = op
        box.addProperty("App::PropertyStringList", "StudioScope", "Studio")
        box.StudioScope = list(scope)
        setBox(box, rect, depth, op)
        box.Visibility = False
        self.doc.openTransaction("insert " + name)
        PartDesign.studioInsert(box, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        return box

    def studioList(self):
        return PartDesign.studioList(self.doc)

    def entries(self):
        return [e.Name for e in self.studioList().Entries]

    def tips(self):
        out = {}
        for p, _ in PARTS:
            tip = self.doc.getObject(p).Tip
            out[p] = None if tip is None else tip.Name
        return out

    def italic(self, label):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.type() != fv.BAR and item.text() == label:
                return item.font().italic()
        raise AssertionError(f"no row {label}")

    def assertVolume(self, part, expected):
        self.assertAlmostEqual(self.doc.getObject(part).Shape.Volume, expected, places=4, msg=part)

    # -------------------------------------------------------------------------------- rows
    def testOneRowPerOwnerNoneForSteps(self):
        """The rows are the list's entries: F1 and F2 once each, though each has a step in two
        parts; no step has a row."""
        self.assertEqual(self.rows(), EXPECTED)
        steps = [o.Name for p, _ in PARTS for o in self.doc.getObject(p).Group if isStep(o)]
        self.assertEqual(sorted(steps), ["F1_at_A", "F1_at_B", "F2_at_B", "F2_at_C"])
        self.assertEqual([o.Label for o in self.studioList().Entries], EXPECTED[:-1])

    # ---------------------------------------------------------------------------------- bar
    def testTheBarActsOnTheList(self):
        """The bar dragged after F1: the list's bar, F1 computed in both its parts and F2 in
        neither (F2 italic), in one undo step; undo puts the bar and the Tips back."""
        undo = self.doc.UndoCount
        self.dragBarAfter("F1")
        self.assertEqual(self.studioList().Bar, NATIVES + 1)
        self.assertEqual(self.tips(), {"A": "F1_at_A", "B": "F1_at_B", "C": "CPad"})
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(
            fv.waitFor(lambda: self.rows() == NATIVE_ROWS + ["F1", "|", "F2"]), self.rows()
        )
        self.assertFalse(self.italic("F1"))
        self.assertTrue(self.italic("F2"))
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.studioList().Bar, -1)
        self.assertEqual(self.tips(), {"A": "F1_at_A", "B": "F2_at_B", "C": "F2_at_C"})
        self.assertTrue(fv.waitFor(lambda: self.rows() == EXPECTED), self.rows())

    # --------------------------------------------------------------------------------- drag
    def testDragActsOnTheList(self):
        """F2 dragged above F1: the list's order, and B (in both scopes) computes F2 then F1, in
        one undo step; undo brings the rows and B's chain back."""
        undo = self.doc.UndoCount
        self.dragRowTo("F2", "F1", below=False)
        moved = NATIVE_ROWS + ["F2", "F1", "|"]
        self.assertTrue(fv.waitFor(lambda: self.rows() == moved), self.rows())
        self.assertEqual(self.entries()[NATIVES:], ["F2", "F1"])
        self.assertEqual(chainOf(self.doc.getObject("B")), ["BSk", "BPad", "F2", "F1"])
        self.assertEqual(self.doc.UndoCount, undo + 1)
        tool1, tool2 = tool(*F1[:3]), tool(*F2[:3])
        self.assertVolume("B", partBox("B").cut(tool2).cut(tool1).Volume)
        self.doc.undo()
        self.doc.recompute()
        self.assertTrue(fv.waitFor(lambda: self.rows() == EXPECTED), self.rows())
        self.assertEqual(chainOf(self.doc.getObject("B")), ["BSk", "BPad", "F1", "F2"])

    # ---------------------------------------------------------------------- delete, suppress
    def testDeleteARowTakesItsSteps(self):
        """Delete on F1's row: F1 and its two steps go, nothing asked, in one undo step; undo brings
        the row and the steps back."""
        undo = self.doc.UndoCount
        self.assertEqual(self.menuAction("F1", "featureDelete"), [True])
        self.doc.recompute()
        for name in ("F1", "F1_at_A", "F1_at_B"):
            self.assertIsNone(self.doc.getObject(name), name)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(fv.waitFor(lambda: self.rows() == NATIVE_ROWS + ["F2", "|"]), self.rows())
        self.assertVolume("A", 1000)
        self.doc.undo()
        self.doc.recompute()
        self.assertTrue(fv.waitFor(lambda: self.rows() == EXPECTED), self.rows())
        self.assertIsNotNone(self.doc.getObject("F1_at_A"))
        self.assertVolume("A", partBox("A").cut(tool(*F1[:3])).Volume)

    def testBackspaceOnTheMacDeletesARow(self):
        """On the Mac (simulated through the hidden General/KeymapMacKeys, ops#640 polish)
        Backspace on F1's selected row deletes F1 and its steps as Delete does; without the Mac's
        keys Backspace deletes nothing."""
        from PySide6 import QtTest

        general = App.ParamGet("User parameter:BaseApp/Preferences/General")
        self.addCleanup(general.RemBool, "KeymapMacKeys")
        viewport = self.list.viewport()

        def backspaceOnF1():
            QtTest.QTest.mouseClick(
                viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, self.rowRect("F1").center()
            )
            self.list.setFocus()
            fv.pump()
            QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Backspace)
            fv.pump()

        backspaceOnF1()
        self.doc.recompute()
        self.assertIsNotNone(self.doc.getObject("F1"))
        general.SetBool("KeymapMacKeys", True)
        backspaceOnF1()
        self.doc.recompute()
        for name in ("F1", "F1_at_A", "F1_at_B"):
            self.assertIsNone(self.doc.getObject(name), name)
        self.assertTrue(fv.waitFor(lambda: self.rows() == NATIVE_ROWS + ["F2", "|"]), self.rows())

    def testSuppressARowSuppressesItsSteps(self):
        """Suppress on F1's row: both its steps pass their part through, in one undo step."""
        undo = self.doc.UndoCount
        self.assertEqual(self.menuAction("F1", "featureToggleSuppress"), [True])
        self.doc.recompute()
        self.assertTrue(self.f1.Suppressed)
        self.assertTrue(self.doc.getObject("F1_at_A").Suppressed)
        self.assertTrue(self.doc.getObject("F1_at_B").Suppressed)
        self.assertVolume("A", 1000)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse(self.doc.getObject("F1_at_A").Suppressed)
        self.assertVolume("A", partBox("A").cut(tool(*F1[:3])).Volume)


if __name__ == "__main__":
    unittest.main()
