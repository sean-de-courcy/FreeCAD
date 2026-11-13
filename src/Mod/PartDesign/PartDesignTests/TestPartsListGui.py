# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (P5 GUI, P6a): the Parts list shows live parts only, and Boolean between parts
#
# In a studio with a history list, a part a Boolean consumed (Keep tools off) is no part from the
# Boolean's place on (notes/onshape-facts.md O3): the Parts list doesn't show it, default names
# renumber positionally (O9: "Part 3" becomes "Part 2" when Part 2 goes), rolling the bar above
# the Boolean shows it again, and no dialog offers it as a target (report 26). PartDesign_Boolean
# makes a Boolean studio feature in one transaction, its dialog ticking targets and tools among the
# live parts.
#
# Designed geometry only: 10 mm boxes A (x 0..10), B (x 5..15, overlapping A by 500) and C
# (x 40..50) at the document's top level, labelled "Part 1", "Part 2", "Part 3".

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests import TestFeaturesViewGui as fv
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestStudio import pad, sketch, xyPlane

PARTS = (("A", 0, "Part 1"), ("B", 5, "Part 2"), ("C", 40, "Part 3"))
PARAM = "User parameter:BaseApp/Preferences/Mod/PartDesign"


class TestPartsListGui(unittest.TestCase):
    showTree = fv.TestFeaturesViewGui.showTree
    view = fv.TestFeaturesViewGui.view

    def setUp(self):
        self.doc = App.newDocument("PartsListGui")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        self.param = App.ParamGet(PARAM)
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        self.savedKeep = self.param.GetBool("BooleanKeepTools", False)
        self.param.SetBool("BooleanKeepTools", False)
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.assertTrue(waitFor(lambda: self.view() is not None and self.view().isVisible()))
        self.parts = self.view().findChild(QtWidgets.QTreeWidget, "partsList")
        for name, x, label in PARTS:
            body = self.doc.addObject("PartDesign::Body", name)
            body.Label = label
            pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), (x, 0, x + 10, 10)), 10)
        self.doc.recompute()
        self.list = PartDesign.studioList(self.doc, True)
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        self.showTree(self.savedTree)
        self.param.SetBool("BooleanKeepTools", self.savedKeep)
        pump()

    # ------------------------------------------------------------------------------ helpers
    def body(self, name):
        return self.doc.getObject(name)

    def rows(self):
        """The Parts list as (shown name, object name)."""
        return [
            (self.parts.topLevelItem(i).text(0),
             bytes(self.parts.topLevelItem(i).data(0, QtCore.Qt.UserRole)).decode())
            for i in range(self.parts.topLevelItemCount())
        ]

    def assertRows(self, rows):
        self.assertTrue(waitFor(lambda: self.rows() == rows), self.rows())
        self.assertEqual(self.parts.headerItem().text(0), f"Parts ({len(rows)})")

    def boolean(self, keep=False):
        """Subtract target A, tool B, made through the Python API."""
        self.doc.openTransaction("boolean")
        b = self.doc.addObject("PartDesign::Boolean", "Bool")
        b.Type = "Cut"
        b.KeepTools = keep
        b.StudioScope = ["A"]
        b.StudioTools = ["B"]
        PartDesign.studioInsert(b, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertTrue(b.isValid(), b.getStatusString())
        return b

    def setBar(self, index):
        self.doc.openTransaction("bar")
        PartDesign.studioSetBar(self.list, index)
        self.doc.commitTransaction()
        self.doc.recompute()

    def waitForPanel(self):
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.3)
        Gui.Control.showTaskView()
        ok = QtWidgets.QDialogButtonBox.Ok
        self.assertTrue(waitFor(lambda: taskButton(ok) is not None), "the Tasks panel stays hidden")

    def visible(self, cls, name):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def ticks(self, name):
        rows = self.visible(QtWidgets.QListWidget, name)
        if rows is None:
            return None
        return [
            (rows.item(i).text(), rows.item(i).data(QtCore.Qt.UserRole),
             rows.item(i).checkState() == QtCore.Qt.Checked)
            for i in range(rows.count())
        ]

    def tick(self, name, part, on):
        rows = self.visible(QtWidgets.QListWidget, name)
        self.assertIsNotNone(rows, name)
        for i in range(rows.count()):
            if rows.item(i).data(QtCore.Qt.UserRole) == part:
                rows.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
                pump(0.3)
                return
        raise AssertionError(f"no tick {part} in {name}: {self.ticks(name)}")

    def close(self, ok):
        which = QtWidgets.QDialogButtonBox.Ok if ok else QtWidgets.QDialogButtonBox.Cancel
        taskButton(which).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.2)

    def runBoolean(self, active="A", selected=("B",)):
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", self.body(active) if active else None)
        Gui.Selection.clearSelection()
        for name in selected:
            Gui.Selection.addSelection(self.doc.Name, name)
        before = {o.Name for o in self.doc.Objects}
        Gui.runCommand("PartDesign_Boolean")
        self.waitForPanel()
        made = [self.doc.getObject(n) for n in {o.Name for o in self.doc.Objects} - before
                if self.doc.getObject(n).TypeId == "PartDesign::Boolean"]
        self.assertEqual(len(made), 1, [o.Name for o in made])
        return made[0]

    # ------------------------------------------------------------------------------ the Parts list
    def testConsumedPartLeavesTheListAndNamesRenumber(self):
        """B consumed: two rows, and C, "Part 3", shows as "Part 2" (O9, positional)."""
        self.assertRows([("Part 1", "A"), ("Part 2", "B"), ("Part 3", "C")])
        self.boolean()
        self.assertRows([("Part 1", "A"), ("Part 2", "C")])
        self.assertFalse(self.body("B").Visibility)
        self.assertEqual(self.body("C").Label, "Part 3")  # the label itself stays

    def testKeptToolStaysListed(self):
        self.boolean(keep=True)
        self.assertRows([("Part 1", "A"), ("Part 2", "B"), ("Part 3", "C")])

    def testBarAboveTheBooleanListsItsTool(self):
        b = self.boolean()
        self.assertRows([("Part 1", "A"), ("Part 2", "C")])
        self.setBar(list(self.list.Entries).index(b))
        self.assertRows([("Part 1", "A"), ("Part 2", "B"), ("Part 3", "C")])
        self.assertTrue(self.body("B").Visibility)
        self.setBar(-1)
        self.assertRows([("Part 1", "A"), ("Part 2", "C")])

    def testResultBoxOffersNoConsumedPart(self):
        """An Extrude (remove) after the Boolean ticks only the live parts: B has no row."""
        self.boolean()
        s = sketch(self.body("A"), "Cut", xyPlane(self.body("A")), (2, 2, 8, 8), z=10)
        self.doc.recompute()
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", self.body("A"))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, s.Name)
        Gui.runCommand("PartDesign_Pocket")
        self.waitForPanel()
        ticks = self.ticks("studioScopeList")
        self.assertIsNotNone(ticks, "no part ticks")
        self.assertEqual([(t[0], t[1]) for t in ticks], [("Part 1", "A"), ("Part 2", "C")])
        self.close(ok=False)

    def testAssemblyInsertSkipsAConsumedPart(self):
        """The assembly's Insert list leaves a consumed part out (no ghost part)."""
        import UtilsAssembly

        self.boolean()
        self.assertTrue(UtilsAssembly.isConsumedPart(self.body("B")))
        self.assertFalse(UtilsAssembly.isConsumedPart(self.body("A")))
        self.setBar(list(self.list.Entries).index(self.doc.getObject("Bool")))
        self.assertFalse(UtilsAssembly.isConsumedPart(self.body("B")))

    # ------------------------------------------------------------------------------ the Boolean dialog
    def testBooleanCommandMakesAStudioFeature(self):
        """Active A, B selected: a Union owner (A first), outside every Body; Subtract makes A the
        target and B the tool; OK cuts A (500) and consumes B, one undo step."""
        undo = self.doc.UndoCount
        b = self.runBoolean()
        self.assertFalse([o.Name for o in self.doc.Objects
                          if o.TypeId == "PartDesign::Body" and b in o.Group])
        self.assertIn(b, self.list.Entries)
        self.assertEqual(b.Type, "Fuse")
        self.assertEqual(list(b.StudioTools), ["A", "B"])
        self.assertIsNone(self.visible(QtWidgets.QListWidget, "studioTargetList"))
        self.assertEqual(self.ticks("studioToolList"),
                         [("Part 1", "A", True), ("Part 2", "B", True), ("Part 3", "C", False)])
        subtract = self.visible(QtWidgets.QPushButton, "buttonSubtract")
        self.assertIsNotNone(subtract)
        subtract.click()
        pump(0.3)
        self.assertEqual(b.Type, "Cut")
        self.assertEqual(list(b.StudioScope), ["A"])
        self.assertEqual(list(b.StudioTools), ["B"])
        self.assertTrue(waitFor(lambda: self.ticks("studioTargetList") is not None))
        self.assertEqual(self.ticks("studioTargetList"),
                         [("Part 1", "A", True), ("Part 2", "B", False), ("Part 3", "C", False)])
        self.close(ok=True)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertAlmostEqual(self.body("A").Shape.Volume, 500, places=3)
        self.assertFalse(self.body("B").Visibility)
        self.assertRows([("Part 1", "A"), ("Part 2", "C")])

    def testBooleanCancelLeavesNothing(self):
        before = sorted(o.Name for o in self.doc.Objects)
        entries = [e.Name for e in self.list.Entries]
        undo = self.doc.UndoCount
        self.runBoolean()
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertEqual([e.Name for e in self.list.Entries], entries)
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertAlmostEqual(self.body("A").Shape.Volume, 1000, places=3)

    def testBooleanEditAgain(self):
        """Double-click: Subtract, A ticked as target, B as tool; Keep tools on and OK: B a part
        again; the consumed tool is never offered as a target after the Boolean."""
        b = self.boolean()
        undo = self.doc.UndoCount
        b.ViewObject.doubleClicked()
        self.waitForPanel()
        self.assertTrue(self.visible(QtWidgets.QPushButton, "buttonSubtract").isChecked())
        # At its own place B is live: offered, and ticked as the tool
        self.assertEqual(self.ticks("studioTargetList"),
                         [("Part 1", "A", True), ("Part 2", "B", False), ("Part 3", "C", False)])
        self.assertEqual(self.ticks("studioToolList"),
                         [("Part 1", "A", False), ("Part 2", "B", True), ("Part 3", "C", False)])
        keep = self.visible(QtWidgets.QCheckBox, "checkKeepTools")
        keep.setChecked(True)
        pump(0.3)
        self.close(ok=True)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(b.KeepTools)
        self.assertTrue(self.body("B").Visibility)
        self.assertRows([("Part 1", "A"), ("Part 2", "B"), ("Part 3", "C")])
        self.assertAlmostEqual(self.body("A").Shape.Volume, 500, places=3)

    # -------------------------------------------------------------- 3D picks (selection parity P4)
    # Onshape's Boolean (SQ14, SQ15): Tools is active when the dialog opens and stays active; a pick
    # on a part adds it (again: removes it); a click on Targets makes Targets the active field; a
    # sketch element, a plane or a part not live at the Boolean's place is refused.
    def armed(self, name):
        rows = self.visible(QtWidgets.QListWidget, name)
        return bool(rows is not None and rows.property("armed"))

    def pick(self, obj, sub=""):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, obj, sub)
        pump(0.3)

    def clickList(self, name):
        from PySide6 import QtTest

        rows = self.visible(QtWidgets.QListWidget, name)
        self.assertIsNotNone(rows, name)
        rect = rows.visualItemRect(rows.item(0))
        QtTest.QTest.mouseClick(rows.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier,
                                QtCore.QPoint(rect.right() - 4, rect.center().y()))
        pump(0.2)

    def testBooleanToolsArmedPickTogglesAPart(self):
        """A Union opens with Tools armed; a face of C ticks C, a face again unticks it; the
        selection is cleared and Tools stays armed."""
        b = self.runBoolean()
        self.assertTrue(self.armed("studioToolList"))
        self.pick("CPad", "Face1")
        self.assertEqual(list(b.StudioTools), ["A", "B", "C"])
        self.assertEqual(self.ticks("studioToolList"),
                         [("Part 1", "A", True), ("Part 2", "B", True), ("Part 3", "C", True)])
        self.assertTrue(waitFor(lambda: not Gui.Selection.getSelectionEx()))
        self.assertTrue(self.armed("studioToolList"))
        self.pick("C", "CPad.Edge1")  # a pick through the part, as the 3D view gives it
        self.assertEqual(list(b.StudioTools), ["A", "B"])
        self.pick("B")  # the part itself (a Parts list or tree click)
        self.assertEqual(list(b.StudioTools), ["A"])
        self.close(ok=False)

    def testBooleanTargetsArmByClick(self):
        """Subtract: Tools armed; a click on Targets arms it, and a pick of C makes C a target;
        a click on Tools arms Tools again."""
        b = self.runBoolean()
        self.visible(QtWidgets.QPushButton, "buttonSubtract").click()
        pump(0.3)
        self.assertTrue(waitFor(lambda: self.ticks("studioTargetList") is not None))
        self.assertTrue(self.armed("studioToolList"))
        self.assertFalse(self.armed("studioTargetList"))
        self.clickList("studioTargetList")
        self.assertTrue(self.armed("studioTargetList"))
        self.assertFalse(self.armed("studioToolList"))
        self.assertEqual(list(b.StudioScope), ["A"])  # the click ticked nothing
        self.pick("CPad", "Face1")
        self.assertEqual(list(b.StudioScope), ["A", "C"])
        self.assertEqual(list(b.StudioTools), ["B"])
        self.assertTrue(self.armed("studioTargetList"))
        self.clickList("studioToolList")
        self.assertTrue(self.armed("studioToolList"))
        self.pick("CPad", "Face2")
        self.assertEqual(list(b.StudioTools), ["B", "C"])
        self.close(ok=False)

    def testBooleanUnionArmsToolsAgain(self):
        """Targets armed, then Union: Targets is hidden, so Tools is armed."""
        self.runBoolean()
        self.visible(QtWidgets.QPushButton, "buttonSubtract").click()
        pump(0.3)
        self.assertTrue(waitFor(lambda: self.ticks("studioTargetList") is not None))
        self.clickList("studioTargetList")
        self.assertTrue(self.armed("studioTargetList"))
        self.visible(QtWidgets.QPushButton, "buttonUnion").click()
        pump(0.3)
        self.assertTrue(waitFor(lambda: self.ticks("studioTargetList") is None))
        self.assertTrue(self.armed("studioToolList"))
        self.close(ok=False)

    def testBooleanRefusesSketchPlaneAndStaysArmed(self):
        """A sketch edge and an origin plane are refused: nothing selected, no tick, still armed."""
        b = self.runBoolean()
        tools = list(b.StudioTools)
        self.pick("CSk", "Edge1")
        self.assertFalse(Gui.Selection.getSelectionEx())
        plane = self.body("C").Origin.OriginFeatures[3]  # XY_Plane
        self.pick(plane.Name)
        self.assertFalse(Gui.Selection.getSelectionEx())
        self.assertEqual(list(b.StudioTools), tools)
        self.assertTrue(self.armed("studioToolList"))
        self.close(ok=False)

    def testBooleanRefusesAConsumedPart(self):
        """After a Subtract consumed B, a second Boolean refuses a pick on B (not live there)."""
        self.boolean()
        b = self.runBoolean(active="A", selected=("C",))
        tools = list(b.StudioTools)
        self.assertNotIn("B", [t[1] for t in self.ticks("studioToolList")])
        self.pick("BPad", "Face1")
        self.assertFalse(Gui.Selection.getSelectionEx())
        self.assertEqual(list(b.StudioTools), tools)
        self.close(ok=False)

    def testBooleanGateGoesWithTheDialog(self):
        """After the dialog closes, a sketch edge is selectable again."""
        self.runBoolean()
        self.close(ok=False)
        self.pick("CSk", "Edge1")
        self.assertTrue(Gui.Selection.getSelectionEx())


if __name__ == "__main__":
    unittest.main()
