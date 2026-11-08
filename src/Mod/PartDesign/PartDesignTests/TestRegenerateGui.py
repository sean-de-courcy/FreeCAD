# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Undo, redo and regeneration in the Gui (FreeCAD-CH ops#640; work/sd03f/regen-design.md
section 7, plan items 1, 2 and 4).

Onshape's behaviour is the bar (decision 276; notes/onshape-experiment.md section 6): with a
feature dialog open Ctrl+Z does nothing, OK leaves one step, Cancel leaves none and nothing to
redo; an edit regenerates the model when it is committed, and so do Suppress, the attachment
editor's OK, undo and redo.

- J1 replayed (F6, J1's block, F35): Std_Undo from the 3D view with the block's dialog open is
  inactive and reverts nothing; OK leaves one step "Edit Block" with nothing pending and the
  model regenerated; a second dialog's Cancel leaves no Redo entry.
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
from PartDesignTests.TestRegenerate import RegenerateModel, total

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

    def testJ1UndoWithTheDialogOpenDoesNothing(self):
        """J1: the block's dialog open, Length 15 typed (the preview applied), Std_Undo from the
        view: inactive, and running it changes nothing (the field, the block, the undo names).
        OK: one step "Edit Block", nothing pending, nothing to recompute, Refresh greyed, the
        model at 15 mm. A second dialog, Length 20, Std_Undo, Cancel: the block back at 15, no
        Redo entry (F6: the first Ctrl+Z committed and undid the edit, the second undid Make
        Fillet; J1:140-143: OK then left Length 15 with no step; F35: Cancel left a Redo entry)."""
        self.openDialog(self.block)
        field = self.setLength(self.block, 15)
        pending = self.doc.UndoNames
        self.assertEqual(pending, ["Edit Block", "Make Fillet"])
        self.assertFalse(self.isActive("Std_Undo"), "Std_Undo is active with the dialog open")
        self.assertFalse(self.isActive("Std_Redo"))

        self.runFromView("Std_Undo")
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
        self.assertAlmostEqual(field.property("rawValue"), 15, places=6)
        self.assertAlmostEqual(self.block.Length.Value, 15, places=6)
        self.assertEqual(self.doc.UndoNames, pending)
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertIsNotNone(self.doc.getObject("Fillet"))

        self.close(OK)
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Make Fillet"])
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertRegenerated(total(length=15))
        self.assertFalse(self.isActive("Std_Refresh"), "Refresh lit after OK")
        self.assertTrue(self.isActive("Std_Undo"))

        self.openDialog(self.block)
        self.setLength(self.block, 20)
        self.runFromView("Std_Undo")
        self.assertAlmostEqual(self.block.Length.Value, 20, places=6)
        self.close(CANCEL)
        self.assertAlmostEqual(self.block.Length.Value, 15, places=6)
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Make Fillet"])
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertFalse(self.isActive("Std_Redo"), "a Redo entry after Cancel")
        self.assertRegenerated(total(length=15))

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
        from the cancelled sketch. The other document's commit leaves it touched."""
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
            Gui.getDocument(self.doc.Name).resetEdit()
            pump()
            self.assertTrue(self.doc.RegenerateOnCommit)
            self.assertTrue(other.RegenerateOnCommit)
            other.openTransaction("Length")
            box.Length = 14
            other.commitTransaction()
            self.assertNotIn("Touched", box.State)
            self.assertAlmostEqual(box.Shape.Volume, 14 * 10 * 10, places=6)
        finally:
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
