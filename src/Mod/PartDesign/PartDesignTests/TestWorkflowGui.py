# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Workflow in the Part Studio, as Onshape (FreeCAD-CH ops#640 round 7).

- Delete part is a feature with a dialog (ranked list 30, blind tests F48, F50): Delete on a part
  opens "Entities to delete" prefilled with it, OK makes the Delete part feature in one undo step,
  Cancel nothing; a pick adds a part or takes a listed one out, an x takes it out; the row's Edit
  reopens it. Deleting the feature that made a New part removes its Body in the same step, its
  sketch staying in the list. FreeCAD's keymap keeps the immediate delete.
- A dragged feature row moves alone (ranked list 31, F31): its sketch stays and keeps its plane;
  above its own sketch the drop is refused with a message.
- A dress-up whose base is gone opens its dialog red (ranked list 12, F19), with no modal; the
  missing picks show in its field, "Clear missing references" takes them out, OK commits it red.

Designed geometry: Body1 a 20 x 10 x 5 block (1000 mm^3) at the origin, Body2 a 10 x 10 x 3 block
(300 mm^3) at y = 20; a New part (a 10 x 10 x 4 block at x = 40) made from Body1. Off screen:
QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import sys
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtGui, QtWidgets
from PySide6 import QtTest

from PartDesignTests.TestDressUpDeleteKeyGui import focus
from PartDesignTests.TestExpressionFieldsGui import taskButton
from PartDesignTests.TestFeaturesViewGui import BAR, DEFAULT, mouse, pump, waitFor
from PartDesignTests.TestStudioSequence import faceAt, sketch

KEYMAP = "User parameter:BaseApp/Preferences/General"
PARAM = "User parameter:BaseApp/Preferences/Mod/PartDesign"


class TestWorkflowGui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        group = App.ParamGet(KEYMAP)
        cls.savedKeymap = group.GetString("Keymap") if "Keymap" in group.GetStrings() else None

    @classmethod
    def tearDownClass(cls):
        group = App.ParamGet(KEYMAP)
        if cls.savedKeymap is None:
            group.RemString("Keymap")
        else:
            group.SetString("Keymap", cls.savedKeymap)
        pump()

    def setUp(self):
        App.ParamGet(KEYMAP).RemString("Keymap")  # the fork's keymap, Onshape, is the default
        self.doc = App.newDocument("WorkflowGui")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        self.param = App.ParamGet(PARAM)
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        Gui.activateWorkbench("PartDesignWorkbench")
        if self.param.GetBool("ShowModelTree", False):
            Gui.runCommand("PartDesign_ToggleModelTree")
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.assertTrue(waitFor(lambda: self.view() is not None and self.view().isVisible()))
        self.list = self.view().findChild(QtWidgets.QListWidget, "featureList")
        self.parts = self.view().findChild(QtWidgets.QTreeWidget, "partsList")
        doc = self.doc
        self.body1 = doc.addObject("PartDesign::Body", "Body1")
        self.skA = sketch(self.body1, "SkA", (0, 0, 20, 10))
        self.padA = self.pad(self.body1, "PadA", self.skA, 5)
        self.body2 = doc.addObject("PartDesign::Body", "Body2")
        self.skB = sketch(self.body2, "SkB", (0, 20, 10, 30))
        self.padB = self.pad(self.body2, "PadB", self.skB, 3)
        doc.recompute()
        self.modals = []
        self._watching = True
        self.addCleanup(setattr, self, "_watching", False)
        QtCore.QTimer.singleShot(50, self.closeModals)

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        if self.param.GetBool("ShowModelTree", False) != self.savedTree:
            Gui.runCommand("PartDesign_ToggleModelTree")
        pump()

    # ------------------------------------------------------------------------------- helpers

    def closeModals(self):
        """Every modal box is recorded and closed: none should open."""
        box = QtWidgets.QApplication.activeModalWidget()
        if isinstance(box, QtWidgets.QMessageBox):
            self.modals.append(box.text())
            box.buttons()[0].click()
        if self._watching:
            QtCore.QTimer.singleShot(50, self.closeModals)

    def pad(self, body, name, profile, length):
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = profile
        pad.Length = length
        return pad

    def newPart(self):
        """Body1's 10 x 10 x 4 block at x = 40, made a New part."""
        skC = sketch(self.body1, "SkC", (40, 0, 50, 10))
        padC = self.pad(self.body1, "PadC", skC, 4)
        body3 = PartDesign.newPartFrom(padC)
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", body3.Label]))
        return body3

    def view(self):
        return Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")

    def visible(self, cls, name):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def partRows(self):
        return [self.parts.topLevelItem(i).text(0) for i in range(self.parts.topLevelItemCount())]

    def rows(self):
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(DEFAULT):
                continue
            out.append("|" if item.type() == BAR else item.text())
        return out

    def rowRect(self, label):
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.type() != BAR and item.text() == label:
                return self.list.visualItemRect(item)
        raise AssertionError(f"no row {label}: {self.rows()}")

    def menuAction(self, label, name):
        """Opens the row's context menu and triggers its action name."""
        triggered = []

        def answer():
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                QtCore.QTimer.singleShot(50, answer)
                return
            for action in menu.actions():
                if action.objectName() == name:
                    triggered.append(action.isEnabled())
                    action.trigger()
            menu.close()

        QtCore.QTimer.singleShot(50, answer)
        self.list.customContextMenuRequested.emit(self.rowRect(label).center())
        pump(0.3)
        return triggered

    def message(self):
        bar = Gui.getMainWindow().statusBar()
        return " ".join([bar.currentMessage()] + [l.text() for l in bar.findChildren(QtWidgets.QLabel)])

    def deleteSelected(self, *names):
        Gui.Selection.clearSelection()
        for name in names:
            Gui.Selection.addSelection(self.doc.Name, name)
        Gui.runCommand("Std_Delete")
        pump(0.3)

    def entities(self):
        rows = self.visible(QtWidgets.QListWidget, "deletePartEntities")
        self.assertIsNotNone(rows, "no Delete part dialog")
        return [rows.item(i).text() for i in range(rows.count())]

    def waitDialog(self, name="deletePartEntities"):
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no dialog")
        Gui.Control.showTaskView()
        self.assertTrue(waitFor(lambda: self.visible(QtWidgets.QWidget, name) is not None))
        pump(0.2)

    def close(self, ok):
        which = QtWidgets.QDialogButtonBox.Ok if ok else QtWidgets.QDialogButtonBox.Cancel
        taskButton(which).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.3)

    def deleters(self, body):
        return [o.Name for o in body.Group if o.TypeId == "PartDesign::DeletePart"]

    # ------------------------------------------------------------- Delete part (rank 30, F48)

    def testDeleteOpensTheDialogPrefilled(self):
        """Delete on a part opens the dialog with the part listed and changes nothing; OK makes
        the Delete part feature in one undo step; Undo brings the part back."""
        body3 = self.newPart()
        undo = self.doc.UndoCount
        self.deleteSelected(body3.Name)
        self.waitDialog()
        self.assertEqual(self.entities(), [body3.Label])
        self.assertEqual(self.deleters(body3), [])
        self.assertEqual(self.doc.UndoCount, undo)
        self.close(ok=True)
        self.assertEqual(body3.Tip.TypeId, "PartDesign::DeletePart")
        self.assertTrue(body3.Shape.isNull())
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]), self.partRows())
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.doc.UndoNames[0], "Delete part")
        self.assertEqual(self.modals, [])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.deleters(body3), [])
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", body3.Label]))

    def testCancelChangesNothing(self):
        body3 = self.newPart()
        undo = self.doc.UndoCount
        self.deleteSelected(body3.Name)
        self.waitDialog()
        self.close(ok=False)
        self.assertEqual(self.deleters(body3), [])
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertAlmostEqual(body3.Shape.Volume, 400, places=6)

    def testSeveralPartsInOneDelete(self):
        """Two parts deleted at once: one dialog lists both; OK deletes both in one step."""
        body3 = self.newPart()
        undo = self.doc.UndoCount
        self.deleteSelected(self.body2.Name, body3.Name)
        self.waitDialog()
        self.assertEqual(sorted(self.entities()), sorted(["Body2", body3.Label]))
        self.close(ok=True)
        self.assertEqual(len(self.deleters(self.body2)), 1)
        self.assertEqual(len(self.deleters(body3)), 1)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1"]), self.partRows())

    def testThePlatformsDeleteKeyTakesTheCurrentEntryOut(self):
        """The delete key takes the current entry out of the list: on a Mac that key sends
        Backspace, which is the shortcut there, as everywhere in FreeCAD (Gui::QtTools::
        deleteKeySequence(); fn+delete, which sends Delete, isn't, ops#652). The key pressed is the
        platform's."""
        body3 = self.newPart()
        self.deleteSelected(self.body2.Name, body3.Name)
        self.waitDialog()
        rows = self.visible(QtWidgets.QListWidget, "deletePartEntities")
        self.assertEqual(rows.count(), 2)
        remove = [a for a in rows.actions() if a.text() == "Remove"]
        self.assertEqual(len(remove), 1)
        standard = (
            QtGui.QKeySequence.StandardKey.Backspace
            if sys.platform == "darwin"
            else QtGui.QKeySequence.StandardKey.Delete
        )
        self.assertEqual(remove[0].shortcut(), QtGui.QKeySequence(standard))
        key = QtCore.Qt.Key_Backspace if sys.platform == "darwin" else QtCore.Qt.Key_Delete
        rows.setCurrentRow(0)
        kept = rows.item(1).text()
        self.assertTrue(focus(rows))
        # to the window, as the window system delivers it: QTest's QWidget overload skips the
        # shortcut map (TestDressUpDeleteKeyGui.pressDelete)
        QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), key)
        self.assertTrue(waitFor(lambda: self.entities() == [kept]), self.entities())
        self.close(ok=False)

    def testPicksAndTheXChangeTheList(self):
        """A pick of a face adds its part, a pick of a listed part takes it out, its x takes it
        out too; OK with the list empty keeps the dialog with a message and changes nothing."""
        body3 = self.newPart()
        self.deleteSelected(body3.Name)
        self.waitDialog()
        face = faceAt(self.padB, 3)
        Gui.Selection.addSelection(self.doc.Name, self.body2.Name, "PadB." + face)
        pump(0.3)
        self.assertEqual(self.entities(), [body3.Label, "Body2"])
        Gui.Selection.addSelection(self.doc.Name, body3.Name, "PadC." + faceAt(self.doc.getObject("PadC"), 4))
        pump(0.3)
        self.assertEqual(self.entities(), ["Body2"])
        rows = self.visible(QtWidgets.QListWidget, "deletePartEntities")
        rows.findChild(QtWidgets.QToolButton, "removeEntity").click()
        pump(0.3)
        self.assertEqual(self.entities(), [])
        undo = self.doc.UndoCount
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog())
        note = self.visible(QtWidgets.QLabel, "deletePartMessage")
        self.assertIsNotNone(note)
        self.assertIn("Pick the parts", note.text())
        self.assertEqual(self.doc.UndoCount, undo)
        self.close(ok=False)
        self.assertEqual(self.doc.findObjects("PartDesign::DeletePart"), [])

    def testEditReopensTheRow(self):
        """The Delete part row's Edit lists its part; its part taken out and another picked, OK
        brings the first part back and deletes the other, in one undo step; Undo reverses it."""
        body3 = self.newPart()
        self.deleteSelected(body3.Name)
        self.waitDialog()
        self.close(ok=True)
        row = self.doc.getObject(self.deleters(body3)[0])
        self.assertTrue(waitFor(lambda: row.Label in self.rows()), self.rows())
        undo = self.doc.UndoCount
        self.assertEqual(self.menuAction(row.Label, "featureEdit"), [True])
        self.waitDialog()
        self.assertEqual(self.entities(), [body3.Label])
        # OK unchanged: no step
        self.close(ok=True)
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertEqual(self.menuAction(row.Label, "featureEdit"), [True])
        self.waitDialog()
        self.visible(QtWidgets.QListWidget, "deletePartEntities").findChild(
            QtWidgets.QToolButton, "removeEntity"
        ).click()
        pump(0.3)
        Gui.Selection.addSelection(self.doc.Name, self.body2.Name, "PadB." + faceAt(self.padB, 3))
        pump(0.3)
        self.assertEqual(self.entities(), ["Body2"])
        self.close(ok=True)
        self.doc.recompute()
        self.assertEqual(self.deleters(body3), [])
        self.assertEqual(body3.Tip.Name, "PadC")
        self.assertAlmostEqual(body3.Shape.Volume, 400, places=6)
        self.assertEqual(len(self.deleters(self.body2)), 1)
        self.assertTrue(self.body2.Shape.isNull())
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.doc.UndoNames[0], "Edit Delete part")
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(len(self.deleters(body3)), 1)
        self.assertEqual(self.deleters(self.body2), [])
        self.assertAlmostEqual(self.body2.Shape.Volume, 300, places=6)

    def testFreeCADKeymapDeletesAtOnce(self):
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        pump()
        body3 = self.newPart()
        self.deleteSelected(body3.Name)
        self.assertFalse(Gui.Control.activeDialog())
        self.assertEqual(body3.Tip.TypeId, "PartDesign::DeletePart")

    def testDeletingANewPartsFeatureRemovesItsBody(self):
        """F50: the New part's Pad deleted from the list: its Body goes in the same step, its
        sketch stays a row, now in Body1 after its block; Undo brings the Body back with both."""
        body3 = self.newPart()
        name, label = body3.Name, body3.Label
        undo = self.doc.UndoCount
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "PadC")
        self.assertEqual(self.menuAction("PadC", "featureDelete"), [True])
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("PadC"))
        self.assertIsNone(self.doc.getObject(name))
        skC = self.doc.getObject("SkC")
        self.assertIs(skC.getParentGeoFeatureGroup(), self.body1)
        self.assertEqual([o.Name for o in self.body1.Group], ["SkA", "PadA", "SkC"])
        self.assertTrue(skC.isValid())
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]), self.partRows())
        self.assertIn("SkC", self.rows())
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        body3 = self.doc.getObject(name)
        self.assertIsNotNone(body3)
        self.assertEqual([o.Name for o in body3.Group], ["SkC", "PadC"])
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", label]))

    # ------------------------------------------------------------ the drag (rank 31, F31)

    def holeBlock(self):
        """On Body1's block: a boss sketch and a hole sketch on its top face, the boss Pad, and a
        Pocket through all from the hole sketch, which misses the boss."""
        top = [(self.padA, faceAt(self.padA, 5))]
        bossSk = sketch(self.body1, "BossSk", (2, 2, 6, 6), support=top)
        self.holeSk = sketch(self.body1, "HoleSk", (14, 4, 16, 6), support=top)
        self.doc.recompute()
        self.pad(self.body1, "BossPad", bossSk, 2)
        self.pocket = self.body1.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.holeSk
        self.pocket.Type = "ThroughAll"
        self.doc.recompute()
        self.assertAlmostEqual(self.body1.Shape.Volume, 1000 + 32 - 20, places=3)
        self.assertTrue(waitFor(lambda: "Pocket" in self.rows()), self.rows())

    def dragRowTo(self, label, target, below):
        viewport = self.list.viewport()
        start = self.rowRect(label).center()
        rect = self.rowRect(target)
        end = QtCore.QPoint(rect.center().x(), rect.bottom() - 1 if below else rect.top() + 1)
        far = QtCore.QPoint(start.x(), start.y() + QtWidgets.QApplication.startDragDistance() + 2)
        mouse(viewport, QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseMove, far, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseMove, end, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.NoButton)
        pump(0.3)

    def testADraggedRowMovesAlone(self):
        """The Pocket dragged above the boss Pad: only its row moves, its sketch stays above it
        with its face reference, in one undo step; the part is the same."""
        self.holeBlock()
        support = [(o.Name, subs) for o, subs in self.holeSk.AttachmentSupport]
        undo = self.doc.UndoCount
        self.dragRowTo("Pocket", "BossPad", below=False)
        expected = ["SkA", "PadA", "BossSk", "HoleSk", "Pocket", "BossPad"]
        own = lambda: [r for r in self.rows() if r not in ("SkB", "PadB", "|")]  # noqa: E731
        self.assertTrue(waitFor(lambda: own() == expected), self.rows())
        self.assertEqual([o.Name for o in self.body1.Group], expected)
        self.assertEqual([(o.Name, subs) for o, subs in self.holeSk.AttachmentSupport], support)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(self.body1.Shape.Volume, 1000 + 32 - 20, places=3)

    def testAboveItsSketchIsRefused(self):
        """The Pocket dragged above its own sketch: refused with a message naming both; nothing
        changes."""
        self.holeBlock()
        before = self.rows()
        undo = self.doc.UndoCount
        self.dragRowTo("Pocket", "HoleSk", below=False)
        self.assertTrue(waitFor(lambda: "'Pocket' uses 'HoleSk'" in self.message()), self.message())
        self.assertEqual(self.rows(), before)
        self.assertEqual(self.doc.UndoCount, undo)

    # ------------------------------------------------ a broken dress-up (rank 12 part, F19)

    def field(self):
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
            if widget.metaObject().className() == "PartDesignGui::ReferenceField" and widget.isVisible():
                return widget
        return None

    def titleInError(self):
        return [
            b.property("featureInError")
            for b in Gui.getMainWindow().findChildren(QtWidgets.QToolButton)
            if b.isVisible() and b.property("featureInError") is not None
        ]

    def edgesAt(self, feature, z):
        return [
            f"Edge{i}"
            for i, e in enumerate(feature.Shape.Edges, 1)
            if all(abs(v.Point.z - z) < 1e-9 for v in e.Vertexes)
        ]

    def testAFilletWhoseBaseIsGoneOpensRed(self):
        """J7: the block's Pad deleted under a fillet of its top edge: the fillet's Edit opens
        its dialog (no modal), red, its field saying the base is gone; OK commits it red."""
        fillet = self.body1.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (self.padA, self.edgesAt(self.padA, 5)[:1])
        fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertTrue(waitFor(lambda: "Fillet" in self.rows()), self.rows())
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "PadA")
        self.assertEqual(self.menuAction("PadA", "featureDelete"), [True])
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("PadA"))
        self.assertFalse(fillet.isValid())
        self.assertEqual(self.menuAction("Fillet", "featureEdit"), [True])
        self.waitDialog("entries")
        self.assertEqual(self.modals, [])
        self.assertIn(True, self.titleInError())
        field = self.field()
        self.assertIsNotNone(field)
        self.assertIn("gone", " ".join(l.text() for l in field.findChildren(QtWidgets.QLabel)))
        self.close(ok=True)
        self.assertIsNotNone(self.doc.getObject("Fillet"))
        self.assertFalse(fillet.isValid())

    def testABrokenThicknessOpensRed(self):
        """Review R7W-2: as the fillet's, a Thickness whose Pad was deleted opens its dialog red
        (its gizmos read the base silently), no modal."""
        thickness = self.body1.newObject("PartDesign::Thickness", "Thickness")
        thickness.Base = (self.padA, faceAt(self.padA, 5))
        thickness.Value = 0.5
        self.doc.recompute()
        self.assertTrue(thickness.isValid(), thickness.getStatusString())
        self.assertTrue(waitFor(lambda: "Thickness" in self.rows()), self.rows())
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "PadA")
        self.assertEqual(self.menuAction("PadA", "featureDelete"), [True])
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("PadA"))
        self.assertFalse(thickness.isValid())
        self.assertEqual(self.menuAction("Thickness", "featureEdit"), [True])
        self.waitDialog("entries")
        self.assertEqual(self.modals, [])
        self.assertIn(True, self.titleInError())
        self.close(ok=True)
        self.assertIsNotNone(self.doc.getObject("Thickness"))

    def testMissingPicksShowAndClear(self):
        """The boss under a fillet deleted: the fillet's dialog opens red with its picks broken in
        the field; Clear missing references takes them out in one write; OK commits it red."""
        top = [(self.padB, faceAt(self.padB, 3))]
        boss = self.pad(self.body2, "Boss", sketch(self.body2, "BossSk", (2, 22, 6, 26), support=top), 2)
        self.doc.recompute()
        fillet = self.body2.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, self.edgesAt(boss, 5)[:2])
        fillet.Radius = 0.5
        self.doc.recompute()
        self.assertTrue(fillet.isValid())
        self.assertTrue(waitFor(lambda: "Fillet" in self.rows()), self.rows())
        self.body2.removeObject(boss)
        self.doc.removeObject("Boss")
        self.doc.recompute()
        self.assertTrue(all(s.startswith("?") for s in fillet.Base[1]), fillet.Base)
        self.assertEqual(self.menuAction("Fillet", "featureEdit"), [True])
        self.waitDialog("entries")
        self.assertEqual(self.modals, [])
        self.assertIn(True, self.titleInError())
        field = self.field()
        self.assertEqual(field.property("state"), "broken")
        action = Gui.getMainWindow().findChild(QtGui.QAction, "clearMissingReferences")
        self.assertIsNotNone(action)
        action.trigger()
        pump(0.3)
        self.assertEqual(fillet.Base[1] if fillet.Base else [], [])
        self.close(ok=True)
        self.assertIsNotNone(self.doc.getObject("Fillet"))
        self.assertFalse(fillet.isValid())

