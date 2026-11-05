# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""The Features and Parts lists in PartDesign (FreeCAD-CH ops#602; notes/features-dock-design.md).

In PartDesign the Model panel shows the studio's features in history order with one roll-back
bar, and the studio's parts, in place of the tree; leaving PartDesign brings the tree back. The
order and the bar are PartDesign.studioSequence and rollStudioTo, which TestStudioSequence covers;
these tests drive the lists: the panel swap and its toggle, the rows and the bar row, dragging the
bar (one undo step), the context menu, selection both ways, an edit locking the bar, and the Parts
list's rows and eye.

The model is TestStudioSequence's interleaved one (designed: two Bodies, a box on the other's
face, pockets from the other Body's sketch). Off screen: QT_QPA_PLATFORM=offscreen
(notes/build.md)."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from PartDesignTests.TestStudioSequence import faceAt, sketch

V = App.Vector
BAR = QtWidgets.QListWidgetItem.UserType + 1  # FeatureList::BarType


def pump(seconds=0.1):
    end = time.monotonic() + seconds
    while True:
        QtWidgets.QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


def mouse(widget, kind, pos, buttons, modifiers=QtCore.Qt.NoModifier):
    button = QtCore.Qt.LeftButton if kind != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton
    event = QtGui.QMouseEvent(
        kind,
        QtCore.QPointF(pos),
        QtCore.QPointF(widget.mapToGlobal(pos)),
        button,
        buttons,
        modifiers,
    )
    QtWidgets.QApplication.sendEvent(widget, event)


class TestFeaturesViewGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("FeaturesView")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        self.param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        self.param.SetBool("ShowModelTree", False)
        Gui.activateWorkbench("PartDesignWorkbench")
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        self.assertTrue(waitFor(lambda: self.view() is not None and self.view().isVisible()))
        self.list = self.view().findChild(QtWidgets.QListWidget, "featureList")
        self.parts = self.view().findChild(QtWidgets.QTreeWidget, "partsList")
        self.build()
        self.assertTrue(waitFor(lambda: self.rows() == self.expected))

    def tearDown(self):
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        self.param.SetBool("ShowModelTree", self.savedTree)
        pump()

    def view(self):
        return Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")

    def treePanel(self):
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget):
            if widget.metaObject().className() == "Gui::TreePanel":
                parent = widget.parentWidget()
                if parent is self.view().parentWidget():
                    return widget
        return None

    def build(self):
        doc = self.doc
        self.body1 = doc.addObject("PartDesign::Body", "Body1")
        self.body2 = doc.addObject("PartDesign::Body", "Body2")
        self.skA = sketch(self.body1, "SkA", (0, 0, 20, 10))
        self.padA = self.body1.newObject("PartDesign::Pad", "PadA")
        self.padA.Profile = self.skA
        self.padA.Length = 5
        doc.recompute()
        self.box = self.body2.newObject("PartDesign::AdditiveBox", "Box")
        self.box.Length = self.box.Width = 6
        self.box.Height = 3
        self.box.AttachmentSupport = [(self.padA, faceAt(self.padA, 5))]
        self.box.MapMode = "FlatFace"
        self.box.AttachmentOffset = App.Placement(V(2, 2, 0), App.Rotation())
        doc.recompute()
        self.skB = sketch(self.body2, "SkB", (6, 2, 12, 6), z=8)
        self.pocket1 = self.body1.newObject("PartDesign::Pocket", "Pocket1")
        self.pocket1.Profile = self.skB
        self.pocket1.Type = "ThroughAll"
        self.pocket1.SideType = "Symmetric"
        self.pocketB = self.body2.newObject("PartDesign::Pocket", "PocketB")
        self.pocketB.Profile = self.skB
        self.pocketB.Type = "ThroughAll"
        self.pocketB.SideType = "Symmetric"
        doc.recompute()
        self.expected = ["SkA", "PadA", "Box", "SkB", "Pocket1", "PocketB", "|"]

    def rows(self):
        """The rows' labels, the bar as "|"."""
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            out.append("|" if item.type() == BAR else item.text())
        return out

    def tips(self):
        return [b.Tip.Name if b.Tip else None for b in (self.body1, self.body2)]

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
        pump(0.2)
        return triggered

    # ------------------------------------------------------------------------------ the panel

    def testListsReplaceTheTreeInPartDesign(self):
        tree = self.treePanel()
        self.assertIsNotNone(tree)
        self.assertFalse(tree.isVisible())
        Gui.activateWorkbench("PartWorkbench")
        self.assertTrue(waitFor(lambda: tree.isVisible() and not self.view().isVisible()))
        Gui.activateWorkbench("PartDesignWorkbench")
        self.assertTrue(waitFor(lambda: self.view().isVisible() and not tree.isVisible()))

    def testToggleModelTree(self):
        tree = self.treePanel()
        Gui.runCommand("PartDesign_ToggleModelTree")
        self.assertTrue(waitFor(lambda: tree.isVisible() and not self.view().isVisible()))
        self.assertTrue(self.param.GetBool("ShowModelTree", False))
        # Remembered: PartDesign shows the tree the next time too
        Gui.activateWorkbench("PartWorkbench")
        Gui.activateWorkbench("PartDesignWorkbench")
        pump(0.2)
        self.assertTrue(tree.isVisible())
        self.assertFalse(self.view().isVisible())
        Gui.runCommand("PartDesign_ToggleModelTree")
        self.assertTrue(waitFor(lambda: self.view().isVisible() and not tree.isVisible()))

    # ------------------------------------------------------------------------- rows and bar

    def testRowsInHistoryOrder(self):
        self.assertEqual(self.rows(), self.expected)
        # The tooltip names the row's Body
        self.assertIn("Body2", self.list.item(2).toolTip())

    def testDragTheBar(self):
        undo = self.doc.UndoCount
        self.dragBarAfter("Box")
        self.assertEqual(self.tips(), ["PadA", "Box"])
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(
            waitFor(lambda: self.rows() == ["SkA", "PadA", "Box", "|", "SkB", "Pocket1", "PocketB"])
        )
        # Held rows are italic
        italic = {self.list.item(i).text(): self.list.item(i).font().italic()
                  for i in range(self.list.count()) if self.list.item(i).type() != BAR}
        self.assertFalse(italic["Box"])
        self.assertTrue(italic["Pocket1"])
        self.assertTrue(italic["PocketB"])
        # One undo step takes both Bodies back
        self.doc.undo()
        self.assertEqual(self.tips(), ["Pocket1", "PocketB"])
        self.assertTrue(waitFor(lambda: self.rows() == self.expected))

    def testDragTheBarToTheTop(self):
        viewport = self.list.viewport()
        start = self.barRect().center()
        end = QtCore.QPoint(self.rowRect("SkA").center().x(), self.rowRect("SkA").top() + 1)
        mouse(viewport, QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseMove, end, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.NoButton)
        pump(0.2)
        self.assertEqual(self.tips(), [None, None])
        self.assertTrue(waitFor(lambda: self.rows()[0] == "|"))

    def testMenuRolls(self):
        self.assertEqual(self.menuAction("Pocket1", "featureRollTo"), [True])
        self.assertEqual(self.tips(), ["Pocket1", "Box"])
        self.assertTrue(waitFor(lambda: self.rows().index("|") == 5))
        self.assertEqual(self.menuAction("SkA", "featureRollToEnd"), [True])
        self.assertEqual(self.tips(), ["Pocket1", "PocketB"])
        self.assertTrue(waitFor(lambda: self.rows() == self.expected))

    def testEditLocksTheBar(self):
        guiDoc = Gui.getDocument(self.doc.Name)
        guiDoc.setEdit(self.padA, 0)
        pump(0.3)
        undo = self.doc.UndoCount
        self.dragBarAfter("PadA")
        self.assertEqual(self.tips(), ["Pocket1", "PocketB"])
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertEqual(self.menuAction("PadA", "featureRollTo"), [False])

    # ---------------------------------------------------------------------------- selection

    def testSelectionBothWays(self):
        rect = self.rowRect("Box")
        viewport = self.list.viewport()
        mouse(viewport, QtCore.QEvent.MouseButtonPress, rect.center(), QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, rect.center(), QtCore.Qt.NoButton)
        pump(0.1)
        self.assertEqual([o.Name for o in Gui.Selection.getSelection()], ["Box"])
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "Body1", "Pocket1.")
        self.assertTrue(
            waitFor(lambda: [i.text() for i in self.list.selectedItems()] == ["Pocket1"])
        )

    def testSelectionAcrossLists(self):
        """Review props602s-r1, finding 1: a click in one list deselects the other's rows."""
        self.assertTrue(waitFor(lambda: self.parts.topLevelItemCount() == 2))
        rect = self.parts.visualItemRect(self.parts.topLevelItem(0))
        viewport = self.parts.viewport()
        mouse(viewport, QtCore.QEvent.MouseButtonPress, rect.center(), QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, rect.center(), QtCore.Qt.NoButton)
        pump(0.1)
        self.assertEqual([o.Name for o in Gui.Selection.getSelection()], ["Body1"])
        rect = self.rowRect("Box")
        viewport = self.list.viewport()
        mouse(viewport, QtCore.QEvent.MouseButtonPress, rect.center(), QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, rect.center(), QtCore.Qt.NoButton)
        self.assertTrue(waitFor(lambda: not self.parts.selectedItems()))
        self.assertEqual([o.Name for o in Gui.Selection.getSelection()], ["Box"])

    def testShiftSelectionShrinks(self):
        """Review props602-r1fix R2: the rows follow the app's selection without committing a
        Shift range, so a second Shift+click shrinks it."""
        viewport = self.list.viewport()

        def click(label, modifiers=QtCore.Qt.NoModifier):
            # QTest sets the application's modifiers, which a Shift range reads
            QTest.mouseClick(viewport, QtCore.Qt.LeftButton, modifiers, self.rowRect(label).center())
            pump(0.1)

        click("SkA")
        click("Pocket1", QtCore.Qt.ShiftModifier)
        click("Box", QtCore.Qt.ShiftModifier)
        self.assertEqual([i.text() for i in self.list.selectedItems()], ["SkA", "PadA", "Box"])
        self.assertEqual(
            sorted(o.Name for o in Gui.Selection.getSelection()), ["Box", "PadA", "SkA"]
        )

    def testEmptyStudioHasNoBar(self):
        """Review props602s-r1, finding 2: a document with no Body shows no bar row."""
        other = App.newDocument("FeaturesViewEmpty")
        try:
            Gui.getDocument(other.Name)
            App.setActiveDocument(other.Name)
            Gui.ActiveDocument = Gui.getDocument(other.Name)
            self.assertTrue(waitFor(lambda: self.list.count() == 0))
        finally:
            App.closeDocument(other.Name)

    # ---------------------------------------------------------------------------- the parts

    def testPartsList(self):
        def partRows():
            return [self.parts.topLevelItem(i).text(0) for i in range(self.parts.topLevelItemCount())]

        self.assertTrue(waitFor(lambda: partRows() == ["Body1", "Body2"]))
        loose = self.doc.addObject("Part::Box", "Loose")
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: partRows() == ["Body1", "Body2", "Loose"]))
        # A Cut's tools are part of the Cut
        tool = self.doc.addObject("Part::Box", "Tool")
        cut = self.doc.addObject("Part::Cut", "Cut")
        cut.Base = loose
        cut.Tool = tool
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: partRows() == ["Body1", "Body2", "Cut"]))
        # The eye shows and hides
        item = self.parts.topLevelItem(0)
        self.assertTrue(self.body1.Visibility)
        rect = self.parts.visualItemRect(item)
        eye = QtCore.QPoint(self.parts.header().sectionPosition(1) + 4, rect.center().y())
        viewport = self.parts.viewport()
        mouse(viewport, QtCore.QEvent.MouseButtonPress, eye, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, eye, QtCore.Qt.NoButton)
        self.assertTrue(waitFor(lambda: not self.body1.Visibility))
