# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Undo, redo and regeneration in the Gui (FreeCAD-CH ops#640; work/sd03f/regen-design.md
section 7, plan items 1, 2, 4 and 7, and round 2's dialog history).

Onshape's behaviour is the bar (decision 276; notes/onshape-experiment.md section 6, hands-on R1,
R1b, R9, R14): with a feature dialog open Ctrl+Z steps back through the dialog's own edits and
never past its start, Ctrl+Y redoes them, OK leaves one step, Cancel leaves none and nothing to
redo; inside a sketch Ctrl+Z steps its actions and stops at the sketch's start, and a closed
sketch is one step; an edit regenerates the model when it is committed, and so do Suppress, the
attachment editor's OK, undo and redo.

- J1 replayed (F6, J1's block, F35): Std_Undo from the 3D view with the block's dialog open
  undoes the dialog's edit inside the dialog, never the step before it; OK leaves one step
  "Edit Block" with nothing pending and the model regenerated; a second dialog's Cancel leaves
  no Redo entry.
- A new Pad's dialog: depth 10 -> 15 -> 20, two Std_Undo give 10 in the dialog, a third does
  nothing; OK, then one document undo removes the Pad.
- A new sketch with three lines: Std_Undo inside removes them one at a time and stops at the
  sketch's start; closed, one Std_Undo removes the sketch, one Std_Redo brings it back whole.
- With a dialog open, Delete of another row (Std_Delete, the Features list's row menu) and a
  roll-back bar move are refused.
- Suppress from the Features list's row menu regenerates before the next event (F32); the
  attachment editor's OK on the hole's sketch moves the hole (F17); undo and redo regenerate
  and keep a feature shown (F33, F35).
- Refresh is synchronous by default (the async worker off, F5), and J7's sequence (delete the
  block, undo, Refresh, delete the fillet, open the boss's dialog) finishes with the worker off.
  The run with the worker on, which shows the hang, is the hub's manual check.

The model is TestRegenerate's (designed: the 20 x 20 x 10 block, the 4 x 4 x 5 boss and the
radius-2 hole on its top, the radius-1 fillet on its edge at (20, 0)); the fillet is made in a
"Make Fillet" step so that something stands before the dialog's. Off screen:
QT_QPA_PLATFORM=offscreen (notes/build.md)."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestRegenerate import RegenerateModel, topFace, total

V = App.Vector
BAR = QtWidgets.QListWidgetItem.UserType + 1  # FeatureList::BarType
DOCUMENT_PREFS = "User parameter:BaseApp/Preferences/Document"
OK = QtWidgets.QDialogButtonBox.Ok
CANCEL = QtWidgets.QDialogButtonBox.Cancel


def mouse(widget, kind, pos, buttons):
    button = QtCore.Qt.LeftButton if kind != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton
    event = QtGui.QMouseEvent(
        kind,
        QtCore.QPointF(pos),
        QtCore.QPointF(widget.mapToGlobal(pos)),
        button,
        buttons,
        QtCore.Qt.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(widget, event)


def visible(cls, name):
    for widget in Gui.getMainWindow().findChildren(cls, name):
        if widget.isVisible():
            return widget
    return None


class TestRegenerateGui(RegenerateModel, unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("RegenerateGui")
        self.doc.UndoMode = 1
        # item 4's switch: every Gui document regenerates on commit (Gui::Document's constructor)
        self.assertTrue(self.doc.RegenerateOnCommit, "a Gui document doesn't regenerate on commit")
        self.modals = []
        self.answering = False
        Gui.Selection.clearSelection()
        self.param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        self.prefs = App.ParamGet(DOCUMENT_PREFS)
        self.savedAsync = (
            self.prefs.GetBool("AsyncRecomputeWorker")
            if "AsyncRecomputeWorker" in self.prefs.GetBools()
            else None
        )
        Gui.activateWorkbench("PartDesignWorkbench")
        # The Features list in place of the tree (the row menu and the bar)
        self.showTree(False)
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.build(fillet=False)
        self.doc.openTransaction("Make Fillet")
        self.fillet = self.addFillet()
        self.doc.commitTransaction()
        self.doc.recompute()  # nothing to do once commits regenerate
        self.assertRegenerated(total())
        self.assertEqual(self.doc.UndoNames, ["Make Fillet"])
        self.activate()
        self.assertTrue(
            waitFor(lambda: self.view() is not None and self.view().isVisible()), "no Features list"
        )
        self.list = self.view().findChild(QtWidgets.QListWidget, "featureList")
        self.assertTrue(waitFor(lambda: "Fillet" in self.rows()), self.rows())

    def tearDown(self):
        self.answering = False
        if Gui.Control.activeDialog():
            cancel = taskButton(CANCEL)
            if cancel is not None:
                cancel.click()
                pump()
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        if self.savedAsync is None:
            self.prefs.RemBool("AsyncRecomputeWorker")
        else:
            self.prefs.SetBool("AsyncRecomputeWorker", self.savedAsync)
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(self.savedTree)
        pump()

    # -- the window ------------------------------------------------------------------------------

    def showTree(self, tree):
        if self.param.GetBool("ShowModelTree", False) != tree:
            Gui.runCommand("PartDesign_ToggleModelTree")

    def view(self):
        return Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")

    def activate(self):
        """The document active and its 3D view the active window (Std_Undo, Std_Redo and
        Std_Refresh go to the active view's document)."""
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        for sub in area.subWindowList():
            if sub.windowTitle().startswith(self.doc.Label + " "):
                area.setActiveSubWindow(sub)
        pump(0.1)
        self.assertIs(Gui.ActiveDocument.Document, self.doc)

    def isActive(self, command):
        """Whether the command is active with this document's view the active window."""
        self.activate()
        return Gui.Command.get(command).isActive()

    def message(self):
        """The status bar's text: MainWindow::showMessage writes to a label in it."""
        bar = Gui.getMainWindow().statusBar()
        return " ".join([bar.currentMessage()] + [l.text() for l in bar.findChildren(QtWidgets.QLabel)])

    def runFromView(self, command):
        self.activate()
        Gui.runCommand(command)
        pump(0.1)

    def select(self, *objects):
        Gui.Selection.clearSelection()
        for obj in objects:
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
        pump(0.1)

    def answerModals(self, button=QtWidgets.QMessageBox.Yes):
        """Until self.answering is False: answers each message box with `button` (else closes
        it) and records its text in self.modals, so a question can't block."""
        self.answering = True

        def poll():
            if not self.answering:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if isinstance(widget, QtWidgets.QMessageBox):
                self.modals.append(widget.text())
                chosen = widget.button(button)
                if chosen is not None:
                    chosen.click()
                else:
                    widget.reject()
            elif widget is not None:
                self.modals.append(type(widget).__name__)
                widget.reject()
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)

    def deleteSelected(self, *objects):
        """Std_Delete on the objects, a dependency question answered Yes."""
        self.select(*objects)
        self.answerModals()
        Gui.runCommand("Std_Delete")
        pump(0.3)
        self.answering = False
        pump(0.1)

    # -- the dialog ------------------------------------------------------------------------------

    def openDialog(self, feature):
        """The feature's dialog, opened as a double-click on its row does ("Edit <label>")."""
        Gui.Selection.clearSelection()
        feature.ViewObject.doubleClicked()
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), f"no dialog for {feature.Name}")
        # the Tasks panel can still be hidden (the first dialog of a process): its buttons count
        # as hidden until it shows
        pump(0.3)
        Gui.Control.showTaskView()
        pump(0.05)
        self.assertIsNotNone(taskButton(OK), "no OK button")

    def setLength(self, feature, length):
        """Types the length into the dialog's field and waits for the preview."""
        field = visible(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(field, "no length field")
        field.setProperty("rawValue", float(length))
        self.assertTrue(
            waitFor(lambda: abs(feature.Length.Value - length) < 1e-6), "the field didn't apply"
        )
        pump(0.2)
        return field

    def close(self, which):
        button = taskButton(which)
        self.assertIsNotNone(button, "no dialog button")
        button.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.2)

    # -- the Features list -----------------------------------------------------------------------

    def rows(self):
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            out.append("|" if item.type() == BAR else item.text())
        return out

    def rowRect(self, label):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.type() != BAR and item.text() == label:
                return self.list.visualItemRect(item)
        raise AssertionError(f"no row {label}")

    def barRect(self):
        for i in range(self.list.count()):
            if self.list.item(i).type() == BAR:
                return self.list.visualItemRect(self.list.item(i))
        raise AssertionError("no bar row")

    def dragBarAfter(self, label):
        viewport = self.list.viewport()
        start = self.barRect().center()
        target = self.rowRect(label)
        end = QtCore.QPoint(target.center().x(), target.bottom() - 1)
        mouse(viewport, QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseMove, end, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.NoButton)
        pump(0.2)

    def menuAction(self, label, name, after=None):
        """Opens the row's context menu and triggers its action `name`; returns the action's
        enabled state and, when given, what after() returned right after the trigger, before any
        further event."""
        triggered = []

        def answer():
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                QtCore.QTimer.singleShot(50, answer)
                return
            for action in menu.actions():
                if action.objectName() == name:
                    enabled = action.isEnabled()
                    action.trigger()
                    triggered.append((enabled, after() if after else None))
            menu.close()

        QtCore.QTimer.singleShot(50, answer)
        self.list.customContextMenuRequested.emit(self.rowRect(label).center())
        pump(0.2)
        return triggered

    # -- item 1: the dialog holds one step (J1, F6, F35) ------------------------------------------

    def lengthField(self):
        field = visible(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(field, "no length field")
        return field

    def enterLength(self, feature, length):
        """Types the length and finishes the field (Tab, Enter or a click elsewhere): one edit
        of the dialog's history. The field has the focus when the dialog opens, and a field's
        typing is one edit until it finishes."""
        field = self.setLength(feature, length)
        field.editingFinished.emit()
        pump(0.05)
        return field

    def testJ1UndoWithTheDialogOpenStaysInTheDialog(self):
        """J1: the block's dialog open, Std_Undo inactive (no edit yet); Length 15 typed (the
        preview applied): Std_Undo is active and undoes the edit inside the dialog (the field
        and the block back at 10, the dialog open, Make Fillet kept); a second Std_Undo does
        nothing; Std_Redo brings 15 back. OK: one step "Edit Block", nothing pending, nothing to
        recompute, Refresh greyed, the model at 15 mm. A second dialog, Length 20, Std_Undo,
        Cancel: the block back at 15, no Redo entry (F6: the first Ctrl+Z committed and undid the
        edit, the second undid Make Fillet; J1:140-143: OK then left Length 15 with no step;
        F35: Cancel left a Redo entry; hands-on R1: the dialog's own history)."""
        self.openDialog(self.block)
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo is active in a dialog with no edit")
        self.setLength(self.block, 15)
        pending = self.doc.UndoNames
        self.assertEqual(pending, ["Edit Block", "Make Fillet"])
        self.assertTrue(self.isActive("Std_Undo"), "Std_Undo is inactive after the dialog's edit")
        self.assertFalse(self.isActive("Std_Redo"))

        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertAlmostEqual(self.block.Length.Value, 10, places=6)
        self.assertAlmostEqual(self.lengthField().property("rawValue"), 10, places=6)
        self.assertIsNotNone(self.doc.getObject("Fillet"))
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo past the dialog's start")
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertIsNotNone(self.doc.getObject("Fillet"), "an undo past the dialog's start")
        self.assertAlmostEqual(self.block.Length.Value, 10, places=6)

        self.assertTrue(self.isActive("Std_Redo"))
        self.runFromView("Std_Redo")
        pump(0.2)
        self.assertAlmostEqual(self.block.Length.Value, 15, places=6)
        self.assertAlmostEqual(self.lengthField().property("rawValue"), 15, places=6)
        self.assertFalse(self.isActive("Std_Redo"))

        self.close(OK)
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Make Fillet"])
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertRegenerated(total(length=15))
        self.assertFalse(self.isActive("Std_Refresh"), "Refresh lit after OK")
        self.assertTrue(self.isActive("Std_Undo"))

        self.openDialog(self.block)
        self.enterLength(self.block, 20)
        self.enterLength(self.block, 25)
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertAlmostEqual(self.block.Length.Value, 20, places=6)
        self.close(CANCEL)
        self.assertAlmostEqual(self.block.Length.Value, 15, places=6)
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Make Fillet"])
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertFalse(self.isActive("Std_Redo"), "a Redo entry after Cancel")
        self.assertRegenerated(total(length=15))

    def testNewPadDialogUndoStepsItsEdits(self):
        """A new Pad (its "Make Pad" step pending, as PartDesign_Pad leaves it) on a 3 x 3 square
        on the block's top: depth 10 -> 15 -> 20 in the dialog; two Std_Undo give 15, then 10,
        with the dialog open; a third is inactive and does nothing (the Pad stays, Make Fillet
        stays). Std_Redo gives 15, Std_Undo 10 again. OK: the Pad at 10, one step "Make Pad";
        one Std_Undo removes the Pad (hands-on R1, R1b)."""
        self.doc.openTransaction("Make PadSketch")
        sketch = self.sketchOnTop("PadSketch", models.rectangle(14, 3, 17, 6))
        self.doc.commitTransaction()
        names = self.doc.UndoNames
        self.assertEqual(names, ["Make PadSketch", "Make Fillet"])
        self.doc.openTransaction("Make Pad")
        pad = models.pad(self.body, sketch, 10, "NewPad")
        self.doc.recompute()
        self.activate()
        Gui.getDocument(self.doc.Name).setEdit(pad.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no dialog for the pad")
        pump(0.3)
        Gui.Control.showTaskView()
        pump(0.05)
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo is active in a dialog with no edit")

        self.enterLength(pad, 15)
        self.enterLength(pad, 20)
        for length in (15, 10):
            self.assertTrue(self.isActive("Std_Undo"), f"Std_Undo inactive before {length}")
            self.runFromView("Std_Undo")
            pump(0.2)
            self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
            self.assertAlmostEqual(pad.Length.Value, length, places=6)
            self.assertAlmostEqual(self.lengthField().property("rawValue"), length, places=6)
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo past the dialog's start")
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertIsNotNone(self.doc.getObject("NewPad"), "an undo removed the new pad")
        self.assertIsNotNone(self.doc.getObject("Fillet"), "an undo past the dialog's start")
        self.assertAlmostEqual(pad.Length.Value, 10, places=6)

        self.runFromView("Std_Redo")
        pump(0.2)
        self.assertAlmostEqual(pad.Length.Value, 15, places=6)
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertAlmostEqual(pad.Length.Value, 10, places=6)

        self.close(OK)
        self.assertEqual(self.doc.UndoNames, ["Make Pad"] + names)
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertAlmostEqual(pad.Length.Value, 10, places=6)
        self.assertVolume(self.body, total() + 9 * 10)

        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertIsNone(self.doc.getObject("NewPad"), "one undo left the pad")
        self.assertEqual(self.doc.UndoNames, names)
        self.assertVolume(self.body, total())

    def testLinkPickedBackLeavesNoStep(self):
        """The block's dialog, its Profile switched to another sketch of the same square and the
        switch undone in the dialog (Std_Undo), then OK: no step, and the Redo entry made before
        the dialog stays (an unchanged accept leaves no step; App's no-op rule keeps any recorded
        link as a change). The same with the Profile switched and switched back by hand."""
        self.doc.openTransaction("Make AltSketch")
        alt = models.sketch(self.doc, "AltSketch", models.rectangle(0, 0, 20, 20), self.body)
        # the direction a Pad made in the Gui has (the panel's "Sketch normal"), which its OK
        # writes over an empty one
        self.block.ReferenceAxis = (self.blockSketch, ["N_Axis"])
        self.doc.commitTransaction()
        self.doc.openTransaction("Boss length")
        self.boss.Length = 6
        self.doc.commitTransaction()
        self.assertTrue(self.doc.undo())
        names = self.doc.UndoNames
        self.assertEqual(names, ["Make AltSketch", "Make Fillet"])
        self.assertEqual(self.doc.RedoNames, ["Boss length"])
        self.assertRegenerated(total())
        profile = self.block.Profile

        self.openDialog(self.block)
        self.block.Profile = (alt, [""])
        pump(0.2)
        self.assertIs(self.block.Profile[0], alt)
        self.assertTrue(self.isActive("Std_Undo"), "the Profile switch is no edit of the dialog")
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertIs(self.block.Profile[0], self.blockSketch)
        self.close(OK)
        self.assertEqual(self.doc.UndoNames, names, "the OK left a step")
        self.assertEqual(self.doc.RedoNames, ["Boss length"], "the OK cleared the Redo stack")
        self.assertIs(self.block.Profile[0], self.blockSketch)
        self.assertRegenerated(total())

        self.openDialog(self.block)
        self.block.Profile = (alt, [""])
        pump(0.2)
        self.block.Profile = profile  # as it was, no subname
        pump(0.2)
        self.close(OK)
        self.assertEqual(self.doc.UndoNames, names, "the OK left a step")
        self.assertEqual(self.doc.RedoNames, ["Boss length"], "the OK cleared the Redo stack")
        self.assertRegenerated(total())

        # A real switch still is a step
        self.openDialog(self.block)
        self.block.Profile = (alt, [""])
        pump(0.2)
        self.close(OK)
        self.assertEqual(self.doc.UndoNames, ["Edit Block"] + names)
        self.assertIs(self.block.Profile[0], alt)

    def patternOfTheBoss(self):
        """A linear pattern of the boss, two copies 10 mm apart along x (the second at x 11..15,
        clear of the hole), its own step."""
        self.doc.openTransaction("Make Pattern")
        pattern = self.body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        pattern.Length = 10
        pattern.Occurrences = 2
        pattern.Originals = [self.boss]
        self.body.Tip = pattern  # newObject leaves a pattern past the roll-back bar
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume(self.body, total() + 16 * 5)
        return pattern

    def testPatternDialogUndoStepsItsEdits(self):
        """The pattern's dialog: Occurrences 2 -> 3, then Length 10 -> 4 (each its own edit);
        Std_Undo gives Length 10 and then Occurrences 2 with the dialog open, rebuilt (the
        occurrences field reads 2), a third does nothing; Std_Redo gives 3 again (field and
        feature). Cancel: back at 2, no step, nothing to redo (hands-on R1 on a pattern)."""
        pattern = self.patternOfTheBoss()
        names = self.doc.UndoNames
        self.openDialog(pattern)
        pattern.Occurrences = 3
        pump(0.2)
        pattern.Length = 4
        pump(0.2)
        self.runFromView("Std_Undo")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertAlmostEqual(pattern.Length.Value, 10, places=6)
        self.assertEqual(pattern.Occurrences, 3)
        self.runFromView("Std_Undo")
        pump(0.3)
        self.assertEqual(pattern.Occurrences, 2)
        field = visible(QtWidgets.QSpinBox, "spinOccurrences")
        self.assertIsNotNone(field, "no occurrences field")
        # a Gui::UIntSpinBox: QSpinBox::value() is shifted (the unsigned range), the text is not
        self.assertEqual(field.cleanText(), "2", "the rebuilt dialog shows the old count")
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo past the dialog's start")
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertIsNotNone(self.doc.getObject("Pattern"), "an undo past the dialog's start")
        self.runFromView("Std_Redo")
        pump(0.3)
        self.assertEqual(pattern.Occurrences, 3)
        self.assertEqual(visible(QtWidgets.QSpinBox, "spinOccurrences").cleanText(), "3")
        self.close(CANCEL)
        self.assertEqual(pattern.Occurrences, 2)
        self.assertAlmostEqual(pattern.Length.Value, 10, places=6)
        self.assertEqual(self.doc.UndoNames, names)
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertRegenerated(total() + 16 * 5)

    def testHoleDialogUndoStepsItsEdits(self):
        """A 2 mm hole 4 deep on the block's top at (5, 15), its own step; its dialog: Depth
        4 -> 6; Std_Undo gives 4 with the dialog open and its Depth field at 4; Std_Redo 6, and
        the field too; Cancel: the hole at 4, no step (hands-on R1 on a hole). Not OK: the Hole
        panel's OK writes its thread fields (CosmeticThread, ThreadFit) over a hole made in
        Python, a step of its own."""
        self.doc.openTransaction("Make Drill")
        sketch = self.sketchOnTop("DrillSketch", [models.circle(5, 15, 1)])
        hole = self.body.newObject("PartDesign::Hole", "Drill")
        hole.Profile = sketch
        hole.Diameter = 2
        hole.DepthType = "Dimension"
        hole.Depth = 4
        hole.DrillPoint = "Flat"
        self.body.Tip = hole
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        names = self.doc.UndoNames
        self.openDialog(hole)
        hole.Depth = 6
        pump(0.2)
        self.assertTrue(self.isActive("Std_Undo"))
        self.runFromView("Std_Undo")
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertAlmostEqual(hole.Depth.Value, 4, places=6)
        field = visible(QtWidgets.QWidget, "Depth")
        self.assertIsNotNone(field, "no depth field")
        self.assertAlmostEqual(field.property("rawValue"), 4, places=6)
        self.runFromView("Std_Redo")
        pump(0.3)
        self.assertAlmostEqual(hole.Depth.Value, 6, places=6)
        self.assertAlmostEqual(visible(QtWidgets.QWidget, "Depth").property("rawValue"), 6, places=6)
        self.close(CANCEL)
        self.assertEqual(self.doc.UndoNames, names)
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertAlmostEqual(hole.Depth.Value, 4, places=6)
        self.assertFalse(self.doc.mustExecute())

    # -- item 7: the sketch session is one step (hands-on R9, R14) --------------------------------

    def addLines(self, sketch, points):
        """Each line in its own transaction, as a sketch tool commits it (Gui::Command's
        openCommand and commitCommand: App's active transaction)."""
        import Part

        for a, b in zip(points, points[1:]):
            App.setActiveTransaction("Add sketch line")
            sketch.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)), False)
            App.closeActiveTransaction()
            pump(0.05)

    def testClosedNewSketchIsOneStep(self):
        """A new sketch on the block's top, its "New Sketch" transaction still open when its edit
        starts (SketchWorkflow): Std_Undo is inactive and does nothing in the empty sketch; three
        lines, each its own transaction (a tool's); Std_Undo removes them one at a time, and a
        fourth does nothing: the sketch stays, in edit; Std_Redo brings them back. Closed: one
        Std_Undo removes the whole sketch, one Std_Redo brings it back with its three lines."""
        import Sketcher  # noqa: F401  (the sketch's type)

        names = self.doc.UndoNames
        self.doc.openTransaction("New Sketch")
        sketch = self.body.newObject("Sketcher::SketchObject", "NewSketch")
        sketch.AttachmentSupport = [(self.block, topFace(self.block, 10))]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        guiDoc = Gui.getDocument(self.doc.Name)
        self.activate()
        guiDoc.setEdit(sketch.Name)
        pump(0.3)
        self.assertIsNotNone(guiDoc.getInEdit(), "no sketch edit")
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo is active in an empty new sketch")
        self.runFromView("Std_Undo")
        self.assertIsNotNone(self.doc.getObject("NewSketch"), "an undo removed the sketch in edit")
        self.assertIsNotNone(guiDoc.getInEdit(), "the sketch's edit closed")

        self.addLines(sketch, [(14, 3), (17, 3), (17, 6), (14, 6)])
        self.assertEqual(len(sketch.Geometry), 3)
        for count in (2, 1, 0):
            self.assertTrue(self.isActive("Std_Undo"), f"Std_Undo inactive before {count} lines")
            self.runFromView("Std_Undo")
            self.assertEqual(len(sketch.Geometry), count)
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo past the sketch's start")
        self.runFromView("Std_Undo")
        self.assertIsNotNone(self.doc.getObject("NewSketch"), "an undo removed the sketch in edit")
        self.assertIsNotNone(guiDoc.getInEdit(), "the sketch's edit closed")
        self.assertIsNotNone(self.doc.getObject("Fillet"), "an undo past the sketch's start")
        for count in (1, 2, 3):
            self.runFromView("Std_Redo")
            self.assertEqual(len(sketch.Geometry), count)

        guiDoc.resetEdit()
        pump(0.3)
        self.assertIsNone(guiDoc.getInEdit())
        self.assertTrue(self.isActive("Std_Undo"))
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertIsNone(self.doc.getObject("NewSketch"), "one undo left the closed sketch")
        self.assertEqual(self.doc.UndoNames, names)
        self.assertIsNotNone(self.doc.getObject("Fillet"))
        self.runFromView("Std_Redo")
        pump(0.2)
        sketch = self.doc.getObject("NewSketch")
        self.assertIsNotNone(sketch, "one redo didn't bring the sketch back")
        self.assertEqual(len(sketch.Geometry), 3)
        self.assertEqual(self.doc.RedoCount, 0)

    def testClosedSketchReEditIsOneStep(self):
        """A sketch that nothing uses (one line, its own step) edited again, two lines added
        (two transactions), closed: one Std_Undo removes both and leaves the sketch and the
        step before."""
        self.doc.openTransaction("Make FreeSketch")
        sketch = self.sketchOnTop("FreeSketch", [])
        self.addLines(sketch, [(2, 15), (6, 15)])
        self.doc.commitTransaction()
        names = self.doc.UndoNames
        self.assertEqual(len(sketch.Geometry), 1)
        guiDoc = Gui.getDocument(self.doc.Name)
        self.activate()
        guiDoc.setEdit(sketch.Name)
        pump(0.3)
        self.assertIsNotNone(guiDoc.getInEdit(), "no sketch edit")
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo past the sketch's start")
        self.addLines(sketch, [(6, 15), (6, 18), (2, 18)])
        self.assertEqual(len(sketch.Geometry), 3)
        guiDoc.resetEdit()
        pump(0.3)
        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertEqual(len(sketch.Geometry), 1, "one undo left a line")
        self.assertEqual(self.doc.UndoNames, names)
        self.assertIsNotNone(self.doc.getObject("FreeSketch"))

    def testSketchOfMoreStrokesThanTheUndoLimitIsOneStep(self):
        """A new sketch of 25 lines, each its own transaction, more than the undo limit (20 steps
        by default, the MaxUndoSize preference): closed, one Std_Undo removes the whole sketch
        and leaves the step before it, one Std_Redo brings it back with its 25 lines (hands-on
        R9). Counted by transactions, the limit took the "New Sketch" opener and the first lines
        off the stack, and the undo left the sketch with them. Then 20 small steps: the sketch's
        step is pushed off whole, the "New Sketch" opener with it, and no line of it is left to
        undo on its own."""
        import Sketcher  # noqa: F401  (the sketch's type)

        limit = App.ParamGet(DOCUMENT_PREFS).GetInt("MaxUndoSize", 20)
        self.assertEqual(limit, 20, "the test's home has another undo limit")
        names = self.doc.UndoNames
        self.doc.openTransaction("New Sketch")
        sketch = self.body.newObject("Sketcher::SketchObject", "LongSketch")
        sketch.AttachmentSupport = [(self.block, topFace(self.block, 10))]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        guiDoc = Gui.getDocument(self.doc.Name)
        self.activate()
        guiDoc.setEdit(sketch.Name)
        pump(0.3)
        self.assertIsNotNone(guiDoc.getInEdit(), "no sketch edit")
        points = [(1 + 0.5 * i, 7 + (i % 2)) for i in range(26)]
        self.addLines(sketch, points)
        self.assertEqual(len(sketch.Geometry), 25)
        guiDoc.resetEdit()
        pump(0.3)
        self.assertIsNone(guiDoc.getInEdit())
        self.assertEqual(self.doc.UndoNames[-len(names) :], names, "the steps before were lost")

        self.runFromView("Std_Undo")
        pump(0.2)
        self.assertIsNone(self.doc.getObject("LongSketch"), "one undo left part of the sketch")
        self.assertEqual(self.doc.UndoNames, names)
        self.assertIsNotNone(self.doc.getObject("Fillet"))
        self.runFromView("Std_Redo")
        pump(0.2)
        sketch = self.doc.getObject("LongSketch")
        self.assertIsNotNone(sketch, "one redo didn't bring the sketch back")
        self.assertEqual(len(sketch.Geometry), 25)

        for i in range(20):
            self.doc.openTransaction(f"Boss {i}")
            self.boss.Length = 5 + 0.01 * (i + 1)
            self.doc.commitTransaction()
        self.assertEqual(len(self.doc.UndoNames), 20, self.doc.UndoNames)
        self.assertNotIn("New Sketch", self.doc.UndoNames)
        self.assertNotIn("Add sketch line", self.doc.UndoNames, "a stroke left alone")

    def testDeleteOfAnotherRowIsRefused(self):
        """The block's dialog open, the fillet selected: Std_Delete is greyed, and neither it nor
        the Features list's row menu deletes the fillet; the dialog stays, no step is added."""
        self.openDialog(self.block)
        names = self.doc.UndoNames
        self.select(self.fillet)
        self.assertFalse(self.isActive("Std_Delete"), "Delete is active with the dialog open")
        self.deleteSelected(self.fillet)
        self.assertIsNotNone(self.doc.getObject("Fillet"), "Std_Delete deleted the fillet")
        # refused visibly (design section 3): Command::invoke's status message
        self.assertIn("Finish the open dialog first", self.message())
        self.select(self.fillet)
        self.answerModals()
        self.menuAction("Fillet", "featureDelete")
        self.answering = False
        self.assertIsNotNone(self.doc.getObject("Fillet"), "the row menu deleted the fillet")
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertEqual(self.doc.UndoNames, names)
        self.close(CANCEL)
        self.assertRegenerated(total())

    def testBarMoveIsRefusedWithADialogOpen(self):
        """A guard, not a test of item 1: it passes on the old build too, where
        ViewProviderBody::isEditLocked already refuses both (FeaturesView.cpp:1022-1023). The
        block's dialog open: dragging the bar and the row menu's Roll to here change no Tip and
        add no step."""
        self.openDialog(self.block)
        names = self.doc.UndoNames
        self.dragBarAfter("Boss")
        self.assertIs(self.body.Tip, self.fillet)
        self.assertEqual(self.menuAction("Boss", "featureRollTo"), [(False, None)])
        self.assertIs(self.body.Tip, self.fillet)
        self.assertEqual(self.doc.UndoNames, names)
        self.close(CANCEL)

    # -- item 4: regeneration (F32, F17, F33, F35) ------------------------------------------------

    def testSuppressFromTheRowMenuRegeneratesAtOnce(self):
        """Suppress from the Features list's row menu: right after the action, before any event,
        nothing is left to recompute and the Body has no boss; Unsuppress brings it back the same
        way (F32: the model stayed as it was until Refresh)."""
        state = lambda: (self.doc.mustExecute(), self.body.Shape.Volume)  # noqa: E731
        self.select(self.boss)
        [(enabled, (touched, volume))] = self.menuAction("Boss", "featureToggleSuppress", state)
        self.assertTrue(enabled)
        self.assertTrue(self.boss.Suppressed)
        self.assertFalse(touched, "Suppress left the model to recompute")
        self.assertAlmostEqual(volume, total(withBoss=False), delta=1e-4)
        self.assertEqual(self.doc.UndoNames[0], "Toggle suppress")

        self.select(self.boss)
        [(enabled, (touched, volume))] = self.menuAction("Boss", "featureToggleSuppress", state)
        self.assertFalse(self.boss.Suppressed)
        self.assertFalse(touched, "Unsuppress left the model to recompute")
        self.assertAlmostEqual(volume, total(), delta=1e-4)
        self.assertRegenerated(total())

    def holeAxis(self):
        """(x, y) of the hole's axis in the Body's shape: its one radius-2 cylinder."""
        axes = [
            (f.Surface.Center.x, f.Surface.Center.y)
            for f in self.body.Shape.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - 2) < 1e-6
        ]
        self.assertEqual(len(axes), 1, axes)
        return axes[0]

    def treeItem(self, label):
        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
            if not tree.isVisible():
                continue
            found = tree.findItems(label, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive, 0)
            if found:
                return tree, found[0]
        return None, None

    def testAttachmentEditorOkRegenerates(self):
        """The attachment editor on the hole's sketch (the tree's Edit Attachment), its X offset
        set to 3, OK: the hole in the Body moves with the sketch at once and nothing is left to
        recompute (F17: the sketch moved, the pocket stayed until Refresh)."""
        self.showTree(True)
        self.assertTrue(waitFor(lambda: self.treeItem("HoleSketch")[1] is not None), "no tree row")
        x, y = self.holeAxis()
        self.assertAlmostEqual(x, 12, places=6)
        self.assertAlmostEqual(y, 12, places=6)

        self.select(self.holeSketch)
        tree, item = self.treeItem("HoleSketch")
        parents = []  # held: PySide drops a child's wrapper with its parent's
        parent = item.parent()
        while parent is not None:
            parents.append(parent)
            parent.setExpanded(True)
            parent = parent.parent()
        pump(0.1)
        tree.scrollToItem(item)
        pump(0.1)
        pos = tree.visualItemRect(item).center()
        texts = []

        def answer():
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                QtCore.QTimer.singleShot(50, answer)
                return
            for action in menu.actions():
                texts.append(action.text().replace("&", ""))
                if texts[-1] == "Edit Attachment":
                    action.trigger()
            menu.close()

        QtCore.QTimer.singleShot(50, answer)
        viewport = tree.viewport()
        event = QtGui.QContextMenuEvent(QtGui.QContextMenuEvent.Mouse, pos, viewport.mapToGlobal(pos))
        QtWidgets.QApplication.sendEvent(viewport, event)
        pump(0.3)
        self.assertIn("Edit Attachment", texts)
        self.assertTrue(waitFor(lambda: visible(QtWidgets.QWidget, "attachmentOffsetX")), "no attacher")
        pump(0.3)
        Gui.Control.showTaskView()
        pump(0.05)
        visible(QtWidgets.QWidget, "attachmentOffsetX").setProperty("rawValue", 3.0)
        pump(0.3)
        self.close(OK)

        self.assertAlmostEqual(self.holeSketch.AttachmentOffset.Base.x, 3, places=6)
        centre = self.holeSketch.getGlobalPlacement().multVec(self.holeSketch.Geometry[0].Center)
        x, y = self.holeAxis()
        self.assertAlmostEqual(x, centre.x, places=6)
        self.assertAlmostEqual(y, centre.y, places=6)
        self.assertAlmostEqual(abs(x - 12) + abs(y - 12), 3, places=6)
        self.assertRegenerated(total())

    def testUndoAndRedoRegenerate(self):
        """An edit made in the dialog, then Std_Undo and Std_Redo from the view: each leaves the
        model regenerated with nothing pending and Refresh greyed (F33)."""
        self.openDialog(self.block)
        self.setLength(self.block, 15)
        self.close(OK)
        self.runFromView("Std_Undo")
        self.assertAlmostEqual(self.block.Length.Value, 10, places=6)
        self.assertRegenerated(total(), "after Std_Undo")
        self.runFromView("Std_Redo")
        self.assertAlmostEqual(self.block.Length.Value, 15, places=6)
        self.assertRegenerated(total(length=15), "after Std_Redo")
        self.assertFalse(self.isActive("Std_Refresh"))

    def shownFeatures(self):
        return [
            obj.Name
            for obj in self.body.Group
            if obj.isDerivedFrom("PartDesign::Feature") and obj.Visibility
        ]

    def hideAll(self):
        for obj in self.body.Group:
            if obj.isDerivedFrom("PartDesign::Feature"):
                obj.Visibility = False

    def testRedoThatHidesEverythingShowsTheTip(self):
        """F35: a step that hid every feature (with a Length change, so it is a step) undone and
        redone: the redo restores the hiding, and the Body, then showing none of its features,
        shows its Tip (ViewProviderBody::afterUndoRedo)."""
        self.doc.openTransaction("Hide and edit")
        self.block.Length = 12
        self.hideAll()
        self.doc.commitTransaction()
        self.assertEqual(self.shownFeatures(), [])  # the step's own state: the user's hiding
        self.runFromView("Std_Undo")
        self.assertTrue(self.fillet.Visibility)
        self.runFromView("Std_Redo")
        pump(0.1)
        self.assertAlmostEqual(self.block.Length.Value, 12, places=6)
        self.assertEqual(self.shownFeatures(), ["Fillet"], "Std_Redo left the Body showing nothing")
        self.assertEqual(self.doc.UndoNames, ["Hide and edit", "Make Fillet"])
        self.assertRegenerated(total(length=12))

    def testUndoThatHidesEverythingShowsTheTip(self):
        """Every feature hidden outside any step, then a step that shows the boss and changes its
        Length: its undo hides the boss again, and the Body, showing none of its features, shows
        its Tip. An undo of a step that changed nothing shown leaves the hiding alone (Onshape's
        undo doesn't touch hide/show)."""
        self.hideAll()
        self.doc.openTransaction("Edit Block")
        self.block.Length = 12
        self.doc.commitTransaction()
        self.runFromView("Std_Undo")
        pump(0.1)
        self.assertEqual(self.shownFeatures(), [], "an undo that changed nothing shown showed the Tip")
        self.runFromView("Std_Redo")
        pump(0.1)

        self.doc.openTransaction("Show Boss")
        self.boss.Visibility = True
        self.boss.Length = 6
        self.doc.commitTransaction()
        self.assertEqual(self.shownFeatures(), ["Boss"])
        self.runFromView("Std_Undo")
        pump(0.1)
        self.assertAlmostEqual(self.boss.Length.Value, 5, places=6)
        self.assertEqual(self.shownFeatures(), ["Fillet"], "Std_Undo left the Body showing nothing")
        self.assertRegenerated(total(length=12))

    # -- item 2: one regeneration at a time, on the Gui thread (F5) -------------------------------

    def testRefreshIsSynchronousByDefault(self):
        """With no preference set, Refresh recomputes before it returns: the async worker is off
        by default (F5)."""
        self.prefs.RemBool("AsyncRecomputeWorker")
        self.block.Length = 12  # no transaction is open: nothing regenerates
        self.assertTrue(self.doc.mustExecute())
        self.assertTrue(self.isActive("Std_Refresh"))
        self.activate()
        Gui.runCommand("Std_Refresh")
        self.assertFalse(self.doc.mustExecute(), "Refresh queued the recompute")
        self.assertRegenerated(total(length=12))

    def testJ7SequenceFinishes(self):
        """J7 with the worker off: delete the block (Yes to the question), undo, Refresh, delete
        the fillet, open the boss's dialog: the dialog opens (F5 hung here with the worker on, the
        hub's manual check), and the model is whole after each step but the deletes."""
        self.prefs.SetBool("AsyncRecomputeWorker", False)
        started = time.monotonic()
        self.deleteSelected(self.block)
        self.assertIsNone(self.doc.getObject("Block"), self.modals)
        self.runFromView("Std_Undo")
        self.block = self.doc.getObject("Block")
        self.assertIsNotNone(self.block)
        self.assertRegenerated(total(), "after the undo of the delete (F34)")
        self.runFromView("Std_Refresh")
        self.deleteSelected(self.fillet)
        self.assertIsNone(self.doc.getObject("Fillet"), self.modals)
        self.fillet = None
        self.assertFalse(self.doc.mustExecute())
        self.assertAlmostEqual(self.body.Shape.Volume, total(withFillet=False), delta=1e-4)
        self.openDialog(self.boss)
        self.close(CANCEL)
        self.assertLess(time.monotonic() - started, 60)
        self.assertRegenerated(total(withFillet=False))

    def testSketchEditHoldsRegeneration(self):
        """A sketch in edit (an edit that holds no step) holds the regeneration on commit of every
        Gui document until it ends, as the Variables panel's recompute (ops#599 R1-1, R1b-3): its
        Cancel restores the sketch from a backup, and a model regenerated meanwhile would be built
        from the cancelled sketch. The other document's commit leaves it touched, and so does a
        commit in the sketch's own document; the edit's end regenerates both (the hold's release
        left them touched: a silent stale model)."""
        other = models.newDocument("RegenerateGuiOther")
        try:
            other.UndoMode = 1
            box = other.addObject("Part::Box", "Box")
            other.recompute()
            self.assertTrue(other.RegenerateOnCommit)
            Gui.getDocument(self.doc.Name).setEdit(self.holeSketch.Name)
            pump()
            self.assertIsNotNone(Gui.getDocument(self.doc.Name).getInEdit(), "no sketch edit")
            self.assertFalse(self.doc.RegenerateOnCommit)
            self.assertFalse(other.RegenerateOnCommit)
            other.openTransaction("Length")
            box.Length = 12
            other.commitTransaction()
            self.assertIn("Touched", box.State)
            self.doc.openTransaction("Boss")
            self.boss.Length = 8
            self.doc.commitTransaction()
            self.assertTrue(self.doc.mustExecute(), "a commit regenerated during the sketch edit")
            self.assertVolume(self.body, total())
            Gui.getDocument(self.doc.Name).resetEdit()
            pump()
            self.assertTrue(self.doc.RegenerateOnCommit)
            self.assertTrue(other.RegenerateOnCommit)
            # the held commits regenerated at the edit's end
            self.assertNotIn("Touched", box.State)
            self.assertAlmostEqual(box.Shape.Volume, 12 * 10 * 10, places=6)
            self.assertRegenerated(total(boss=8))
            other.openTransaction("Length")
            box.Length = 14
            other.commitTransaction()
            self.assertNotIn("Touched", box.State)
            self.assertAlmostEqual(box.Shape.Volume, 14 * 10 * 10, places=6)
        finally:
            App.closeDocument(other.Name)

    def testFeatureDialogOkRegeneratesBesideASketchEdit(self):
        """A sketch in edit in another document holds the regeneration of the documents, but not
        of one whose feature dialog is open (its step lock): the block's dialog OK, while the
        other document's sketch is in edit, regenerates the model at once (it was held, and OK
        left the Body touched at the old length). The hold takes the document again after the
        dialog and lets it go with the sketch's edit."""
        import Sketcher  # noqa: F401  (the sketch's type)

        other = models.newDocument("RegenerateGuiOtherSketch")
        try:
            sketch = other.addObject("Sketcher::SketchObject", "Sketch")
            other.recompute()
            Gui.getDocument(other.Name).setEdit(sketch.Name)
            pump()
            self.assertIsNotNone(Gui.getDocument(other.Name).getInEdit(), "no sketch edit")
            self.assertFalse(self.doc.RegenerateOnCommit)
            self.activate()
            self.openDialog(self.block)
            self.assertTrue(self.doc.RegenerateOnCommit, "the dialog's document is held")
            self.setLength(self.block, 15)
            self.close(OK)
            self.assertEqual(self.doc.UndoNames, ["Edit Block", "Make Fillet"])
            self.assertRegenerated(total(length=15))
            self.assertFalse(self.doc.RegenerateOnCommit, "the sketch edit no longer holds")
            Gui.getDocument(other.Name).resetEdit()
            pump()
            self.assertTrue(self.doc.RegenerateOnCommit)
        finally:
            if Gui.getDocument(other.Name).getInEdit():
                Gui.getDocument(other.Name).resetEdit()
                pump()
            App.closeDocument(other.Name)

    def testUndoOfADeleteInAHeldDocumentHealsAtTheRelease(self):
        """The block deleted (its sketches lose their face, the boss becomes the first solid),
        then a sketch in another document in edit, which holds this document's regeneration, and
        the delete undone here: nothing regenerates yet; the sketch's edit ends and the release
        regenerates the whole model, every dependant valid (F34's heal: the undo's enforce of
        what it changed, which App skips while the regeneration is held, was missing, and the
        release, which regenerates what must execute, found nothing to do)."""
        import Sketcher  # noqa: F401  (the sketch's type)

        self.doc.openTransaction("Delete")
        self.body.removeObject(self.block)
        self.doc.removeObject(self.block.Name)
        self.doc.commitTransaction()
        self.assertIsNone(self.doc.getObject("Block"))
        other = models.newDocument("RegenerateGuiHeldUndo")
        try:
            sketch = other.addObject("Sketcher::SketchObject", "Sketch")
            other.recompute()
            Gui.getDocument(other.Name).setEdit(sketch.Name)
            pump()
            self.assertIsNotNone(Gui.getDocument(other.Name).getInEdit(), "no sketch edit")
            self.assertFalse(self.doc.RegenerateOnCommit, "the sketch edit doesn't hold")
            self.assertTrue(self.doc.undo())
            self.block = self.doc.getObject("Block")
            self.assertIsNotNone(self.block)
            Gui.getDocument(other.Name).resetEdit()
            pump()
            self.assertTrue(self.doc.RegenerateOnCommit)
            self.assertRegenerated(total(), "the release left the undo's dependants stale")
            self.assertIs(self.body.Tip, self.fillet)

            # The unsuppress (J13): suppressed and unsuppressed, then held, undone (suppressed)
            # and redone (unsuppressed)
            for state in (True, False):
                self.doc.openTransaction("Toggle suppress")
                self.block.Suppressed = state
                self.doc.commitTransaction()
            self.assertRegenerated(total())
            Gui.getDocument(other.Name).setEdit(sketch.Name)
            pump()
            self.assertFalse(self.doc.RegenerateOnCommit, "the sketch edit doesn't hold")
            self.assertTrue(self.doc.undo())
            self.assertTrue(self.block.Suppressed)
            self.assertTrue(self.doc.redo())
            self.assertFalse(self.block.Suppressed)
            Gui.getDocument(other.Name).resetEdit()
            pump()
            self.assertRegenerated(total(), "the release left the redo's dependants stale")
        finally:
            if Gui.getDocument(other.Name).getInEdit():
                Gui.getDocument(other.Name).resetEdit()
                pump()
            App.closeDocument(other.Name)

    def testCloseWithAViewProviderChangePending(self):
        """A document closed while its open transaction holds a view provider's change: closing
        doesn't read the deleted view provider (the commit's no-op test did, and crashed FreeCAD
        when a sketch's attachment dialog was closed without OK or Cancel: testPDCreateSketch)."""
        self.doc.openTransaction("Line width")
        Gui.getDocument(self.doc.Name).getObject(self.fillet.Name).LineWidth = 3
        self.assertTrue(self.doc.HasPendingTransaction)
        name = self.doc.Name
        App.closeDocument(name)
        pump()
        self.assertNotIn(name, App.listDocuments())
        self.doc = models.newDocument("RegenerateGui")  # for tearDown
