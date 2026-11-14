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
import PartDesign
import Sketcher
from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

from PartDesignTests.TestStudioSequence import faceAt, sketch

V = App.Vector
BAR = QtWidgets.QListWidgetItem.UserType + 1  # FeatureList::BarType
EYE = QtCore.Qt.UserRole + 2  # FeatureList::EyeRole
DEFAULT = QtCore.Qt.UserRole + 3  # FeatureList::DefaultRole


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
        Gui.activateWorkbench("PartDesignWorkbench")
        # The list in place of the tree (the other GUI tests run with the tree: PartDesignTests)
        self.showTree(False)
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
        Gui.activateWorkbench("PartDesignWorkbench")
        self.showTree(self.savedTree)
        pump()

    def showTree(self, tree):
        if self.param.GetBool("ShowModelTree", False) != tree:
            Gui.runCommand("PartDesign_ToggleModelTree")

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
        """The rows' labels, the bar as "|", without the default geometry rows at the top."""
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(DEFAULT):
                continue
            out.append("|" if item.type() == BAR else item.text())
        return out

    def defaultRows(self):
        """The default geometry rows' labels (ops#640 rank 33)."""
        return [
            self.list.item(i).text()
            for i in range(self.list.count())
            if self.list.item(i).data(DEFAULT)
        ]

    def barItem(self):
        for i in range(self.list.count()):
            if self.list.item(i).type() == BAR:
                return self.list.item(i)
        raise AssertionError("no bar row")

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
        self.assertIn("Body2", self.item("Box").toolTip())

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

    def testFacePickHighlightsItsPart(self):
        """Selection parity SQ6: a face or edge picked highlights its feature's row and its part's
        row; the selection stays the element; a whole feature picked highlights no part."""
        self.assertTrue(waitFor(lambda: self.parts.topLevelItemCount() == 2))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "Body1", "Pocket1.Face1")
        self.assertTrue(waitFor(lambda: [i.text(0) for i in self.parts.selectedItems()] == ["Body1"]))
        self.assertEqual([i.text() for i in self.list.selectedItems()], ["Pocket1"])
        sel = Gui.Selection.getSelectionEx()
        self.assertEqual([(s.ObjectName, tuple(s.SubElementNames)) for s in sel], [("Pocket1", ("Face1",))])
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, "Box", "Edge1")
        self.assertTrue(waitFor(lambda: [i.text(0) for i in self.parts.selectedItems()] == ["Body2"]))
        Gui.Selection.clearSelection()
        self.assertTrue(waitFor(lambda: not self.parts.selectedItems()))
        Gui.Selection.addSelection(self.doc.Name, "Body1", "Pocket1.")
        self.assertTrue(waitFor(lambda: [i.text() for i in self.list.selectedItems()] == ["Pocket1"]))
        pump(0.3)
        self.assertEqual(self.parts.selectedItems(), [])

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

    # ------------------------------------------------------------------- dragging rows (ops#632)

    def dragRowTo(self, label, target, below):
        """Drags the row label onto target's lower (below) or upper half."""
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

    def message(self):
        """The status bar's text: MainWindow::showMessage writes to a label in it."""
        bar = Gui.getMainWindow().statusBar()
        return " ".join([bar.currentMessage()] + [l.text() for l in bar.findChildren(QtWidgets.QLabel)])

    def testDragARow(self):
        """Body2's Pocket dragged above Body1's: the list is the dropped order, in one undo step,
        and the shapes are unchanged."""
        undo = self.doc.UndoCount
        self.dragRowTo("PocketB", "Pocket1", below=False)
        moved = ["SkA", "PadA", "Box", "SkB", "PocketB", "Pocket1", "|"]
        self.assertTrue(waitFor(lambda: self.rows() == moved))
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.assertAlmostEqual(self.body1.Shape.Volume, (200 - 24) * 5, places=3)
        self.assertAlmostEqual(self.body2.Shape.Volume, 108 - 24, places=3)
        self.doc.undo()
        self.assertTrue(waitFor(lambda: self.rows() == self.expected))

    def testDragARowBelowTheBar(self):
        """Rolled back after Box: Body2's sketch dragged above the bar is listed there, and its
        Pocket dragged below the bar is held there."""
        self.dragBarAfter("Box")
        self.assertEqual(self.tips(), ["PadA", "Box"])
        self.dragRowTo("SkB", "Box", below=True)
        self.assertTrue(
            waitFor(lambda: self.rows() == ["SkA", "PadA", "Box", "SkB", "|", "Pocket1", "PocketB"])
        )
        # Dropped below the bar: held, where it was dropped
        self.dragRowTo("PocketB", "Pocket1", below=False)
        self.assertTrue(
            waitFor(lambda: self.rows() == ["SkA", "PadA", "Box", "SkB", "|", "PocketB", "Pocket1"])
        )
        self.assertEqual(self.tips(), ["PadA", "Box"])

    def testRefusedDropLeavesTheRows(self):
        """Body1's Pocket reads Body2's sketch: dragged to the top it is refused with a message
        naming both, and nothing changes."""
        undo = self.doc.UndoCount
        self.dragRowTo("Pocket1", "SkA", below=False)
        self.assertTrue(waitFor(lambda: "'Pocket1' uses 'SkB'" in self.message()))
        self.assertEqual(self.rows(), self.expected)
        self.assertEqual(self.doc.UndoCount, undo)

    def testDragSeveralRows(self):
        """Two selected rows dragged together: a click on one of them keeps the selection for the
        drag; rows of two Bodies are refused."""
        self.item("PadA").setSelected(True)
        self.item("Box").setSelected(True)
        pump()
        undo = self.doc.UndoCount
        self.dragRowTo("Box", "SkA", below=False)
        self.assertTrue(waitFor(lambda: "one part at a time" in self.message()))
        self.assertEqual(self.rows(), self.expected)
        self.assertEqual(self.doc.UndoCount, undo)
        # A click without a drag on a row of the selection selects it alone
        viewport = self.list.viewport()
        point = self.rowRect("Box").center()
        mouse(viewport, QtCore.QEvent.MouseButtonPress, point, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, point, QtCore.Qt.NoButton)
        pump()
        self.assertEqual([item.text() for item in self.list.selectedItems()], ["Box"])

    def partRows(self):
        return [self.parts.topLevelItem(i).text(0) for i in range(self.parts.topLevelItemCount())]

    def acceptDeletePart(self):
        """OK in the Delete part dialog a Delete on a part opens (ops#640 rank 30)."""
        from PartDesignTests.TestExpressionFieldsGui import taskButton

        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Delete part dialog")
        Gui.Control.showTaskView()
        self.assertTrue(waitFor(lambda: taskButton(QtWidgets.QDialogButtonBox.Ok) is not None))
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.2)

    def testPartFollowsTheHistory(self):
        """ops#635 (report 10): a Body is a part only while a solid feature above its bar makes it.
        Its new-part Pad deleted from the list, it leaves the Parts list, and its Body goes, the
        sketch staying in Body1 (ops#640 rank 30, F50); undo brings it back; the bar at the top
        leaves no part, as in Onshape."""
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]))
        self.doc.openTransaction("New part")
        skC = sketch(self.body1, "SkC", (40, 0, 50, 10))
        padC = self.body1.newObject("PartDesign::Pad", "PadC")
        padC.Profile = skC
        padC.Length = 4
        body3 = PartDesign.newPartFrom(padC)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual([o.Name for o in body3.Group], ["SkC", "PadC"])
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", body3.Label]))
        name, label = body3.Name, body3.Label

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, padC.Name)
        self.assertEqual(self.menuAction("PadC", "featureDelete"), [True])
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("PadC"))
        self.assertIsNone(self.doc.getObject(name))
        self.assertIs(skC.getParentGeoFeatureGroup(), self.body1)
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]), self.partRows())
        self.assertIn("SkC", self.rows())

        self.doc.undo()
        self.doc.recompute()
        body3 = self.doc.getObject(name)
        self.assertEqual([o.Name for o in body3.Group], ["SkC", "PadC"])
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", label]))

        # The bar at the top: no part exists yet; at the end, all three again
        self.dragBarAfter("SkA")
        self.assertTrue(waitFor(lambda: self.partRows() == []), self.partRows())
        self.assertEqual(self.menuAction("SkA", "featureRollToEnd"), [True])
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", body3.Label]))

    def testDeletePart(self):
        """ops#635 (report 11): Delete on a part makes a Delete part feature at the bar; the Body and
        its features stay; undo brings the part back."""
        skC = sketch(self.body1, "SkC", (40, 0, 50, 10))
        padC = self.body1.newObject("PartDesign::Pad", "PadC")
        padC.Profile = skC
        padC.Length = 4
        body3 = PartDesign.newPartFrom(padC)
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", body3.Label]))

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, body3.Name)
        Gui.runCommand("Std_Delete")
        self.acceptDeletePart()
        # The command recomputes (review prs464e2-r1, Sonnet T4, Opus T3)
        self.assertTrue(waitFor(lambda: body3.Shape.isNull() and "Touched" not in body3.State))
        self.assertIsNotNone(self.doc.getObject(body3.Name))
        self.assertEqual(body3.Tip.TypeId, "PartDesign::DeletePart")
        self.assertEqual([o.Name for o in body3.Group][:2], ["SkC", "PadC"])
        self.assertTrue(body3.Shape.isNull())
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]), self.partRows())
        self.assertIn(body3.Tip.Label, self.rows())

        self.doc.undo()
        self.doc.recompute()
        self.assertIs(body3.Tip, padC)
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2", body3.Label]))

    def testDeletePartForcedWithAnother(self, readFirst=False):
        """Reviews prs464e2-r2 R2-1, r3 R3-1: Std_Delete of two parts, one read whole by a binder;
        its "might break" dialog answered Yes removes that one with its features (as before), the
        other gets a Delete part, in either selection order, and no feature is left outside a
        Body."""
        skC = sketch(self.body1, "SkC", (40, 0, 50, 10))
        padC = self.body1.newObject("PartDesign::Pad", "PadC")
        padC.Profile = skC
        padC.Length = 4
        body3 = PartDesign.newPartFrom(padC)
        binder = self.doc.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(self.body2, "")]
        self.doc.recompute()
        names = (body3.Name, self.body2.Name)

        def answer():
            box = QtWidgets.QApplication.activeModalWidget()
            if not isinstance(box, QtWidgets.QMessageBox):
                QtCore.QTimer.singleShot(50, answer)
                return
            box.button(QtWidgets.QMessageBox.Yes).click()

        QtCore.QTimer.singleShot(50, answer)
        Gui.Selection.clearSelection()
        order = (self.body2.Name, body3.Name) if readFirst else names
        for name in order:
            Gui.Selection.addSelection(self.doc.Name, name)
        Gui.runCommand("Std_Delete")
        pump(0.3)
        self.acceptDeletePart()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(names[1]))
        self.assertIs(self.doc.getObject(names[0]), body3)
        self.assertEqual(body3.Tip.TypeId, "PartDesign::DeletePart")
        stray = [
            o.Name
            for o in self.doc.Objects
            if o.isDerivedFrom("PartDesign::Feature")
            and not (o.getParentGeoFeatureGroup() or o).isDerivedFrom("PartDesign::Body")
        ]
        self.assertEqual(stray, [])

    def newPart(self):
        skC = sketch(self.body1, "SkC", (40, 0, 50, 10))
        padC = self.body1.newObject("PartDesign::Pad", "PadC")
        padC.Profile = skC
        padC.Length = 4
        body3 = PartDesign.newPartFrom(padC)
        self.doc.recompute()
        return body3

    def testDeletePartWithAllItsFeatures(self, bodyFirst=True):
        """Review s33e2 F1: a Body selected with every one of its features (a range in the tree)
        is deleted outright, in either selection order: no Body or Delete part is left."""
        body3 = self.newPart()
        name = body3.Name
        members = [o.Name for o in body3.Group]
        Gui.Selection.clearSelection()
        order = [name] + members if bodyFirst else members + [name]
        for obj in order:
            Gui.Selection.addSelection(self.doc.Name, obj)
        Gui.runCommand("Std_Delete")
        pump(0.2)
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        for obj in members:
            self.assertIsNone(self.doc.getObject(obj))
        self.assertEqual(self.doc.findObjects("PartDesign::DeletePart"), [])

    def testDeletePartWithAllItsFeaturesBodyLast(self):
        self.testDeletePartWithAllItsFeatures(bodyFirst=False)

    def testDeleteADeletedPartAgain(self):
        """Review s33e2 F2: Delete on a part deleted already removes the Body with its features."""
        body3 = self.newPart()
        name = body3.Name
        for again in (False, True):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.doc.Name, name)
            Gui.runCommand("Std_Delete")
            pump(0.2)
            if not again:
                self.acceptDeletePart()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertIsNone(self.doc.getObject("PadC"))
        self.assertEqual(self.doc.findObjects("PartDesign::DeletePart"), [])

    def testDeletePartForcedWithAnotherFirst(self):
        """The same, the binder's Body selected first (review prs464e2-r3, R3-1)."""
        self.testDeletePartForcedWithAnother(readFirst=True)

    # ------------------------------------------------- the Onshape experiment (ops#640, sff13)

    def watchModals(self):
        """Closes (No) every modal box that opens from now on, and returns their texts."""
        seen = []

        def close():
            box = QtWidgets.QApplication.activeModalWidget()
            if isinstance(box, QtWidgets.QMessageBox):
                seen.append(box.text())
                box.button(QtWidgets.QMessageBox.No).click()
            if self._watching:
                QtCore.QTimer.singleShot(50, close)

        self._watching = True
        self.addCleanup(setattr, self, "_watching", False)
        QtCore.QTimer.singleShot(50, close)
        return seen

    def popupAction(self, widget, pos, name):
        """Sends a context-menu request at pos to widget (a list) and triggers the action name;
        returns the menu's action names."""
        names = []

        def answer():
            menu = QtWidgets.QApplication.activePopupWidget()
            if menu is None:
                QtCore.QTimer.singleShot(50, answer)
                return
            for action in menu.actions():
                names.append(action.objectName())
            for action in menu.actions():
                if action.objectName() == name:
                    action.trigger()
            menu.close()

        QtCore.QTimer.singleShot(50, answer)
        widget.customContextMenuRequested.emit(pos)
        pump(0.2)
        return names

    def partRect(self, label):
        for i in range(self.parts.topLevelItemCount()):
            item = self.parts.topLevelItem(i)
            if item.text(0) == label:
                return self.parts.visualItemRect(item)
        raise AssertionError(f"no part {label}")

    def item(self, label):
        for i in range(self.list.count()):
            if self.list.item(i).type() != BAR and self.list.item(i).text() == label:
                return self.list.item(i)
        raise AssertionError(f"no row {label}")

    def testListsStayWhileASketchIsEdited(self):
        """Onshape keeps its Feature list while a sketch is edited: opening a Body's sketch (the
        Sketcher workbench) keeps the lists in place of the tree; another workbench during the
        edit brings the tree back, and closing the sketch brings the lists again (survey 35)."""
        tree = self.treePanel()
        guiDoc = Gui.getDocument(self.doc.Name)
        guiDoc.setEdit(self.skA)
        self.assertTrue(waitFor(lambda: Gui.activeWorkbench().name() == "SketcherWorkbench"))
        pump(0.2)
        self.assertTrue(self.view().isVisible())
        self.assertFalse(tree.isVisible())
        # The edit rolls the studio back to the sketch, as Onshape's does: what comes after it is
        # held, and the bar stands right below the edited row
        self.assertEqual(self.rows(), ["SkA", "|", "PadA", "Box", "SkB", "Pocket1", "PocketB"])
        Gui.activateWorkbench("PartWorkbench")
        self.assertTrue(waitFor(lambda: tree.isVisible() and not self.view().isVisible()))
        Gui.activateWorkbench("SketcherWorkbench")
        self.assertTrue(waitFor(lambda: self.view().isVisible() and not tree.isVisible()))
        guiDoc.resetEdit()
        self.assertTrue(waitFor(lambda: Gui.activeWorkbench().name() == "PartDesignWorkbench"))
        self.assertTrue(waitFor(lambda: self.view().isVisible() and not tree.isVisible()))
        self.assertTrue(waitFor(lambda: self.rows() == self.expected), self.rows())

    def testHeaderCounts(self):
        """Onshape's 'Features (n)' and the Parts section's count (ref-D #14, #30)."""
        title = self.view().findChild(QtWidgets.QLabel, "featuresTitle")
        self.assertTrue(waitFor(lambda: title.text() == "Features (6)"))
        self.assertEqual(self.parts.headerItem().text(0), "Parts (2)")
        self.doc.removeObject(self.pocketB.Name)
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: title.text() == "Features (5)"))

    def testErrorRows(self):
        """A failed row's name is red and its hover gives the message, with the failure it comes
        from; the header's error icon counts the failed rows and, pressed, shows only them
        (blind test F38, F45; ref-D #24)."""
        errors = self.view().findChild(QtWidgets.QToolButton, "featuresErrors")
        self.assertFalse(errors.isVisible())
        normal = self.item("SkA").foreground().color()
        # The base pad fails on its own (no length); the box on its face fails through it
        self.padA.Length = 0
        self.doc.recompute()
        self.assertIn("Invalid", self.padA.State)
        self.assertIn("Invalid", self.box.State)
        failed = [o.Label for o in self.doc.Objects if "Invalid" in o.State and o.Label in self.expected]
        self.assertTrue(waitFor(lambda: errors.isVisible()))
        self.assertIn(str(len(failed)), errors.toolTip())
        pad = self.item("PadA")
        self.assertEqual(pad.foreground().color(), QtGui.QColor(0xD0, 0x30, 0x30))
        self.assertNotEqual(normal, pad.foreground().color())
        self.assertIn(self.padA.getStatusString(), pad.toolTip())
        self.assertIn("Caused by 'PadA'", self.item("Box").toolTip())
        self.assertNotIn("Caused by", self.item("SkA").toolTip())
        # Pressed: only the failed rows
        errors.click()
        pump()
        shown = [self.list.item(i).text() for i in range(self.list.count()) if not self.list.item(i).isHidden()]
        self.assertEqual(sorted(shown), sorted(failed))
        errors.click()
        pump()
        self.assertTrue(all(not self.list.item(i).isHidden() for i in range(self.list.count())))
        # Repaired: the icon goes, the text is the palette's again
        self.padA.Length = 5
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: not errors.isVisible()))
        self.assertEqual(self.item("PadA").foreground().color(), normal)

    def rename(self, view, oldLabel, newLabel):
        """Renames the current row of view through its F2 / Shift+N action."""
        action = view.findChild(QtGui.QAction, "renameAction")
        self.assertIsNotNone(action)
        keys = [s.toString() for s in action.shortcuts()]
        self.assertIn("F2", keys)
        self.assertIn("Shift+N", keys)
        action.trigger()
        pump()
        editor = view.viewport().findChild(QtWidgets.QLineEdit)
        self.assertIsNotNone(editor)
        self.assertEqual(editor.text(), oldLabel)
        editor.setText(newLabel)
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        pump(0.2)

    def testRenameInTheLists(self):
        """Onshape's Rename (Shift+N, or F2 as in the tree) in both lists, one undo step each
        (survey 36, ref-D #17)."""
        self.list.setCurrentItem(self.item("PadA"))
        self.item("PadA").setSelected(True)
        undo = self.doc.UndoCount
        self.rename(self.list, "PadA", "Base pad")
        self.assertTrue(waitFor(lambda: self.padA.Label == "Base pad"))
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.doc.UndoNames[0], "Rename")
        self.assertTrue(waitFor(lambda: "Base pad" in self.rows()))
        # A double-click still edits the feature, it doesn't rename
        self.assertEqual(self.list.editTriggers(), QtWidgets.QAbstractItemView.NoEditTriggers)
        # The Parts list
        for i in range(self.parts.topLevelItemCount()):
            if self.parts.topLevelItem(i).text(0) == "Body2":
                self.parts.setCurrentItem(self.parts.topLevelItem(i), 0)
        self.rename(self.parts, "Body2", "Bracket")
        self.assertTrue(waitFor(lambda: self.body2.Label == "Bracket"))
        self.assertTrue(waitFor(lambda: "Bracket" in self.partRows()))
        self.doc.undo()
        self.doc.undo()
        self.assertEqual((self.padA.Label, self.body2.Label), ("PadA", "Body2"))
        self.assertTrue(waitFor(lambda: self.rows() == self.expected))

    def testDeleteAsksNothing(self):
        """Onshape deletes a feature others use without a question: they stay and fail on the
        missing reference (ref-D #29; blind test F27, F28). A reader outside the Bodies (a
        spreadsheet) is still asked about."""
        seen = self.watchModals()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.body1.Name, "SkA.")
        Gui.runCommand("Std_Delete")
        pump(0.3)
        self.assertEqual(seen, [])
        self.assertIsNone(self.doc.getObject("SkA"))
        self.assertIn("Invalid", self.padA.State)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNotNone(self.doc.getObject("SkA"))
        # Deleting the box under Body2's pocket: nothing breaks, nothing asked (F28)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.body2.Name, "Box.")
        Gui.runCommand("Std_Delete")
        pump(0.3)
        self.assertEqual(seen, [])
        self.assertIsNone(self.doc.getObject("Box"))
        self.doc.undo()
        self.doc.recompute()
        # A spreadsheet reading the pad: asked (answered No), nothing deleted
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "=PadA.Length")
        self.doc.recompute()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.body1.Name, "PadA.")
        Gui.runCommand("Std_Delete")
        pump(0.3)
        self.assertEqual(len(seen), 1)
        self.assertIsNotNone(self.doc.getObject("PadA"))

    def testFeatureMenu(self):
        """The row menu has Onshape's Rename, Show dependencies and Zoom to; Show dependencies
        marks the parents and children (not the base it merges with); the bar row and the empty
        space below the rows offer Roll to end (survey 37, ref-D #16 and 3.11)."""
        names = self.popupAction(self.list, self.rowRect("Box").center(), "featureDependencies")
        for name in ("featureEdit", "featureRename", "featureRollTo", "featureDependencies", "featureZoom", "featureDelete"):
            self.assertIn(name, names)
        role = QtCore.Qt.UserRole + 1  # FeaturesView::DependencyRole
        marks = {self.list.item(i).text(): self.list.item(i).data(role) for i in range(self.list.count()) if self.list.item(i).type() != BAR}
        self.assertEqual(marks["PadA"], 1)  # the box sits on its face
        self.assertEqual(marks["SkA"], 0)
        # Pocket1: its profile is a parent, the pad it is merged with isn't
        self.popupAction(self.list, self.rowRect("Pocket1").center(), "featureDependencies")
        marks = {self.list.item(i).text(): self.list.item(i).data(role) for i in range(self.list.count()) if self.list.item(i).type() != BAR}
        self.assertEqual(marks["SkB"], 1)
        self.assertEqual(marks["PadA"], 0)
        # SkB: two children
        self.popupAction(self.list, self.rowRect("SkB").center(), "featureDependencies")
        marks = {self.list.item(i).text(): self.list.item(i).data(role) for i in range(self.list.count()) if self.list.item(i).type() != BAR}
        self.assertEqual((marks["Pocket1"], marks["PocketB"]), (2, 2))
        # A selection change clears the marks
        self.list.clearSelection()
        self.item("SkA").setSelected(True)
        pump()
        self.assertTrue(all(not self.list.item(i).data(role) for i in range(self.list.count()) if self.list.item(i).type() != BAR))
        # The bar row: Roll to end
        self.dragBarAfter("PadA")
        self.assertNotEqual(self.tips(), ["Pocket1", "PocketB"])
        names = self.popupAction(self.list, self.barRect().center(), "featureRollToEnd")
        self.assertEqual(names, ["featureRollToEnd"])
        self.assertEqual(self.tips(), ["Pocket1", "PocketB"])

    def testSketchThatCouldNotSolveIsRed(self):
        """Onshape's list reads a sketch with conflicting constraints red (PL1d), though the sketch
        solves the rest and its pad builds (a warning, not an error, to the document): SkA's bottom
        line held Horizontal and then Vertical. Removing the Vertical brings the palette's colour
        back (ops#640)."""
        normal = self.item("SkA").foreground().color()
        self.skA.addConstraint(Sketcher.Constraint("Horizontal", 0))
        vertical = self.skA.addConstraint(Sketcher.Constraint("Vertical", 0))
        self.doc.recompute()
        self.assertIn(vertical + 1, self.skA.ConflictingConstraints)
        self.assertNotIn("Invalid", self.skA.State)
        self.assertTrue(self.padA.isValid(), "the pad builds on the rest of the sketch")
        red = QtGui.QColor(0xD0, 0x30, 0x30)
        self.assertTrue(
            waitFor(lambda: self.item("SkA").foreground().color() == red),
            self.item("SkA").foreground().color().name(),
        )
        self.skA.delConstraint(vertical)
        self.doc.recompute()
        self.assertTrue(
            waitFor(lambda: self.item("SkA").foreground().color() == normal),
            self.item("SkA").foreground().color().name(),
        )

    def testSuppressedRowIsGreyAndNothingIsPending(self):
        """Round 8 (J13): PadA suppressed: its row's text is grey, as Onshape greys a suppressed
        row, and still struck through; the features that fail through it (the box on its face)
        are red, none is touched, and Refresh is grey, as Onshape has no needs-recompute state.
        Unsuppressed: the row has the palette's colour again and everything computes."""
        grey = self.list.palette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
        self.assertNotEqual(self.item("PadA").foreground().color(), grey)
        self.padA.Suppressed = True
        self.doc.recompute()
        self.assertTrue(
            waitFor(lambda: self.item("PadA").foreground().color() == grey),
            self.item("PadA").foreground().color().name(),
        )
        self.assertTrue(self.item("PadA").font().strikeOut())
        self.assertFalse(self.box.isValid())
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])
        pump()
        self.assertFalse(Gui.Command.get("Std_Refresh").isActive(), "Refresh is lit")
        self.padA.Suppressed = False
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.item("PadA").foreground().color() != grey))
        self.assertFalse(self.item("PadA").font().strikeOut())
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])

    def testPartsListShowsOnlyExistingParts(self):
        """Onshape lists a part only while its features make it: Body2 with its box suppressed
        makes nothing and isn't listed (blind test F37, report 10); merged into Body1 it isn't
        either, until the merge is undone (F26)."""
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]))
        self.box.Suppressed = True
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1"]), self.partRows())
        self.box.Suppressed = False
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]))
        self.doc.openTransaction("Merge")
        PartDesign.makeMerge(self.pocket1, [self.body2])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1"]), self.partRows())
        self.doc.undo()
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]))

    def testBarByKeyboard(self):
        """Onshape: a click selects the bar, and Up and Down step it one row, one undo step each
        (ref-D 3.11; survey 42)."""
        viewport = self.list.viewport()
        point = self.barRect().center()
        mouse(viewport, QtCore.QEvent.MouseButtonPress, point, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, point, QtCore.Qt.NoButton)
        pump()
        bar = self.barItem()
        self.assertTrue(bar.isSelected())
        self.assertEqual(self.tips(), ["Pocket1", "PocketB"])
        undo = self.doc.UndoCount
        QTest.keyClick(self.list, QtCore.Qt.Key_Up)
        pump(0.2)
        self.assertTrue(waitFor(lambda: self.rows().index("|") == 5))
        self.assertEqual(self.tips(), ["Pocket1", "Box"])
        self.assertEqual(self.doc.UndoCount, undo + 1)
        QTest.keyClick(self.list, QtCore.Qt.Key_Up)
        pump(0.2)
        self.assertTrue(waitFor(lambda: self.rows().index("|") == 4))
        self.assertEqual(self.tips(), ["PadA", "Box"])
        QTest.keyClick(self.list, QtCore.Qt.Key_Down)
        QTest.keyClick(self.list, QtCore.Qt.Key_Down)
        pump(0.2)
        self.assertTrue(waitFor(lambda: self.rows() == self.expected))
        self.assertEqual(self.tips(), ["Pocket1", "PocketB"])
        # A row clicked: the bar isn't selected, the arrows move the selection again
        point = self.rowRect("PadA").center()
        mouse(viewport, QtCore.QEvent.MouseButtonPress, point, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, point, QtCore.Qt.NoButton)
        pump()
        self.assertFalse(self.barItem().isSelected())

    def testPartsMenu(self):
        """A right-click on a part opens Onshape's part menu; Hide other parts hides every other
        part and nothing else (survey 38, blind test F47)."""
        self.assertTrue(waitFor(lambda: self.partRows() == ["Body1", "Body2"]))
        names = self.popupAction(self.parts, self.partRect("Body2").center(), "partHideOthers")
        for name in ("partRename", "partToggleVisibility", "partIsolate", "partHideOthers", "partAppearance", "partZoom", "partDelete"):
            self.assertIn(name, names)
        self.assertTrue(waitFor(lambda: not self.body1.Visibility))
        self.assertTrue(self.body2.Visibility)
        # The right-clicked row became the selection
        self.assertEqual([i.text(0) for i in self.parts.selectedItems()], ["Body2"])

    # --------------------------------------------- ops#640 round 3 (ranks 32, 33, 34, 35, 40)

    def eyePoint(self, label):
        """The centre of a row's eye (FeatureList::eyeRect: 16 px, 3 px from the right end)."""
        rect = self.rowRect(label)
        size = min(16, rect.height())
        return QtCore.QPoint(rect.right() - size - 3 + size // 2, rect.center().y())

    def clickEye(self, label):
        viewport = self.list.viewport()
        point = self.eyePoint(label)
        mouse(viewport, QtCore.QEvent.MouseButtonPress, point, QtCore.Qt.LeftButton)
        mouse(viewport, QtCore.QEvent.MouseButtonRelease, point, QtCore.Qt.NoButton)
        pump(0.2)

    def closeEdit(self):
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump(0.3)
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.3)

    def testEditRollsEveryPart(self):
        """Rank 32 (lists plan 8): editing Pocket1 (Body1) rolls Body2 back to it too, as Onshape
        rolls every part back to the feature edited: PocketB, after Pocket1 in the history, is
        held and leaves the view, and Box, Body2's solid before it, is shown. Nothing saved
        changes (the Tips, the Visibility properties). Final shows every part's end result;
        closing the edit puts everything back."""
        preview = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign/Preview")
        savedFinal = preview.GetBool("ShowFinal", False)
        preview.SetBool("ShowFinal", False)
        try:
            pocketB = self.pocketB.ViewObject
            box = self.box.ViewObject
            self.assertTrue(pocketB.isVisible())
            self.assertFalse(box.isVisible())
            Gui.getDocument(self.doc.Name).setEdit(self.pocket1, 0)
            pump(0.3)
            self.assertTrue(waitFor(lambda: self.body2.holds(self.pocketB)))
            self.assertFalse(self.body2.holds(self.box))
            self.assertEqual(self.tips(), ["Pocket1", "PocketB"])
            self.assertFalse(pocketB.isVisible())
            self.assertTrue(box.isVisible())
            self.assertTrue(self.pocketB.Visibility)
            self.assertFalse(self.box.Visibility)
            # The list: the bar right after the feature in edit, Body2's later row below it
            expected = ["SkA", "PadA", "Box", "SkB", "Pocket1", "|", "PocketB"]
            self.assertTrue(waitFor(lambda: self.rows() == expected), self.rows())
            # Final: every part's end result, and back
            final = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "showFinalCheckBox")
            self.assertIsNotNone(final)
            final.setChecked(True)
            pump(0.3)
            self.assertFalse(self.body2.holds(self.pocketB))
            self.assertTrue(pocketB.isVisible())
            self.assertFalse(box.isVisible())
            final.setChecked(False)
            pump(0.3)
            self.assertTrue(self.body2.holds(self.pocketB))
            self.assertFalse(pocketB.isVisible())
            # Closed: as before the edit
            self.closeEdit()
            self.assertFalse(self.body2.holds(self.pocketB))
            self.assertTrue(pocketB.isVisible())
            self.assertFalse(box.isVisible())
            self.assertEqual(self.tips(), ["Pocket1", "PocketB"])
            self.assertTrue(waitFor(lambda: self.rows() == self.expected), self.rows())
        finally:
            preview.SetBool("ShowFinal", savedFinal)

    def testEditedRowHighlighted(self):
        """Rank 40: the feature in edit is highlighted in the list (bold, a tinted background)
        until its edit closes."""
        self.assertFalse(self.item("PadA").font().bold())
        Gui.getDocument(self.doc.Name).setEdit(self.padA, 0)
        pump(0.3)
        self.assertTrue(waitFor(lambda: self.item("PadA").font().bold()))
        self.assertNotEqual(self.item("PadA").background().style(), QtCore.Qt.NoBrush)
        self.assertFalse(self.item("Box").font().bold())
        self.closeEdit()
        self.assertTrue(waitFor(lambda: not self.item("PadA").font().bold()))
        self.assertEqual(self.item("PadA").background().style(), QtCore.Qt.NoBrush)

    def testRowsBelowTheBarGreyed(self):
        """Rank 34 (blind test F43): every row below the bar is greyed and italic, the sketch
        waiting there with the held pockets too; rolled back without a drag, the bar takes the
        place a drag gives it (one place for one state), above that sketch. A sketch made while
        rolled back is listed at the bar, live (F42)."""
        grey = self.list.palette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
        PartDesign.rollStudioTo(self.doc, self.box)
        self.doc.recompute()
        self.assertTrue(
            waitFor(lambda: self.rows() == ["SkA", "PadA", "Box", "|", "SkB", "Pocket1", "PocketB"]),
            self.rows(),
        )
        for label in ("SkB", "Pocket1", "PocketB"):
            self.assertEqual(self.item(label).foreground().color(), grey, label)
            self.assertTrue(self.item(label).font().italic(), label)
        for label in ("SkA", "PadA", "Box"):
            self.assertNotEqual(self.item(label).foreground().color(), grey, label)
            self.assertFalse(self.item(label).font().italic(), label)
        # A new sketch of Body1 goes in at the bar, above the waiting sketch, and stays live
        sketch(self.body1, "SkN", (30, 0, 34, 4))
        self.doc.recompute()
        self.assertTrue(
            waitFor(lambda: self.rows() == ["SkA", "PadA", "Box", "SkN", "|", "SkB", "Pocket1", "PocketB"]),
            self.rows(),
        )
        self.assertNotEqual(self.item("SkN").foreground().color(), grey)

    def testAFailedRowBelowTheBarIsGreyAndThePartsNotItalic(self):
        """Round 6 (journeys J2, J22): Pocket1 failing (no length) is red; rolled back above it,
        its row is grey like the other rows below the bar, not red (nothing below the bar is
        evaluated [guess]), and the Parts rows aren't italic."""
        grey = self.list.palette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
        red = QtGui.QColor(0xD0, 0x30, 0x30)
        self.pocket1.Type = "Length"
        self.pocket1.Length = 0
        self.doc.recompute()
        self.assertIn("Invalid", self.pocket1.State)
        self.assertTrue(waitFor(lambda: self.item("Pocket1").foreground().color() == red))
        PartDesign.rollStudioTo(self.doc, self.box)
        self.doc.recompute()
        self.assertTrue(
            waitFor(lambda: self.rows() == ["SkA", "PadA", "Box", "|", "SkB", "Pocket1", "PocketB"]),
            self.rows(),
        )
        self.assertIn("Invalid", self.pocket1.State)
        self.assertEqual(self.item("Pocket1").foreground().color(), grey)
        self.assertTrue(self.item("Pocket1").font().italic())
        self.assertTrue(self.parts.topLevelItemCount() > 0)
        for i in range(self.parts.topLevelItemCount()):
            item = self.parts.topLevelItem(i)
            self.assertFalse(item.font(0).italic(), item.text(0))

    def testErrorButtonIgnoresRowsBelowTheBar(self):
        """Review R6-5: Pocket1 failing (no length) shows the header's error icon; rolled back
        above it, its row is grey and the icon goes (it counts the rows above the bar only);
        rolled to the end again, the icon is back."""
        errors = self.view().findChild(QtWidgets.QToolButton, "featuresErrors")
        grey = self.list.palette().color(QtGui.QPalette.Disabled, QtGui.QPalette.Text)
        self.pocket1.Type = "Length"
        self.pocket1.Length = 0
        self.doc.recompute()
        self.assertIn("Invalid", self.pocket1.State)
        self.assertTrue(waitFor(lambda: errors.isVisible()))
        PartDesign.rollStudioTo(self.doc, self.box)
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: self.item("Pocket1").foreground().color() == grey))
        self.assertIn("Invalid", self.pocket1.State)
        self.assertTrue(waitFor(lambda: not errors.isVisible()), errors.toolTip())
        PartDesign.rollStudioToEnd(self.doc)
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: errors.isVisible()))
        self.assertIn("1 feature", errors.toolTip())

    def testDefaultGeometryRows(self):
        """Rank 33: Onshape's default geometry at the top (Origin, Top, Front, Right): not in the
        history (a bar dropped among them is at the top), not renamed; the eye of the Top plane
        shows it alone with its Origin, and hides both again."""
        self.assertTrue(waitFor(lambda: self.defaultRows() == ["Origin", "Top", "Front", "Right"]))
        origin = self.body1.Origin
        plane = next(o for o in origin.OriginFeatures if o.Role == "XY_Plane")
        self.assertFalse(self.item("Top").flags() & QtCore.Qt.ItemIsEditable)
        self.assertFalse(origin.ViewObject.isVisible())
        self.assertEqual(self.item("Top").data(EYE), 2)
        self.clickEye("Top")
        self.assertTrue(waitFor(lambda: origin.ViewObject.isVisible() and plane.ViewObject.isVisible()))
        others = [o for o in origin.OriginFeatures if o != plane]
        self.assertTrue(all(not o.ViewObject.isVisible() for o in others))
        self.assertTrue(waitFor(lambda: self.item("Top").data(EYE) == 1))
        self.clickEye("Top")
        self.assertTrue(waitFor(lambda: not origin.ViewObject.isVisible()))
        # The bar dragged among them is at the top
        self.dragBarAfter("Front")
        self.assertEqual(self.tips(), [None, None])

    def testEyeOnSketchRows(self):
        """Rank 33: a sketch row has an eye (a solid's has none); a click on it shows or hides the
        sketch and leaves the selection."""
        self.assertTrue(waitFor(lambda: self.item("SkA").data(EYE) in (1, 2)))
        self.assertFalse(self.item("PadA").data(EYE))
        before = self.skA.Visibility
        self.clickEye("SkA")
        self.assertTrue(waitFor(lambda: self.skA.Visibility != before))
        self.assertEqual(self.list.selectedItems(), [])
        self.clickEye("SkA")
        self.assertTrue(waitFor(lambda: self.skA.Visibility == before))

    def testFilterBox(self):
        """Rank 33: Onshape's filter box: rows by name or type; ':errors' only the failed ones."""
        box = self.view().findChild(QtWidgets.QLineEdit, "featuresFilter")
        self.assertIsNotNone(box)

        def shown():
            return [
                self.list.item(i).text()
                for i in range(self.list.count())
                if not self.list.item(i).isHidden() and self.list.item(i).type() != BAR
            ]

        box.setText("pocket")
        pump()
        self.assertEqual(shown(), ["Pocket1", "PocketB"])
        box.setText("SketchObject")  # the type: Sketcher::SketchObject
        pump()
        self.assertEqual(shown(), ["SkA", "SkB"])
        box.setText(":errors")
        pump()
        self.assertEqual(shown(), [])
        self.padA.Length = 0
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: "PadA" in shown()))
        self.assertNotIn("SkA", shown())
        self.padA.Length = 5
        self.doc.recompute()
        box.clear()
        pump()
        self.assertTrue(waitFor(lambda: self.rows() == self.expected))
        self.assertTrue(all(not self.list.item(i).isHidden() for i in range(self.list.count())))

    def testHoverPreselects(self):
        """Rank 33: the hover over a Features or Parts row pre-highlights its object in the view,
        as the tree's; leaving the list ends it."""
        viewport = self.list.viewport()
        mouse(viewport, QtCore.QEvent.MouseMove, self.rowRect("PadA").center(), QtCore.Qt.NoButton)
        pump()
        presel = Gui.Selection.getPreselection()
        self.assertEqual(presel.ObjectName, "Body1")
        self.assertIn("PadA", "".join(presel.SubElementNames))
        QtWidgets.QApplication.sendEvent(viewport, QtCore.QEvent(QtCore.QEvent.Leave))
        pump()
        self.assertFalse(Gui.Selection.getPreselection().ObjectName)
        rect = self.partRect("Body2")
        mouse(self.parts.viewport(), QtCore.QEvent.MouseMove, rect.center(), QtCore.Qt.NoButton)
        pump()
        self.assertEqual(Gui.Selection.getPreselection().ObjectName, "Body2")
        QtWidgets.QApplication.sendEvent(self.parts.viewport(), QtCore.QEvent(QtCore.QEvent.Leave))
        pump()

    def testMessagesNameTheCause(self):
        """Rank 35 (blind test F45): a failure passed on names the failed input in plain words, not
        the link property ("AttachmentSupport links to ..."), and the cause's own message."""
        self.padA.Length = 0
        self.doc.recompute()
        self.assertTrue(waitFor(lambda: "Caused by 'PadA'" in self.item("Box").toolTip()))
        tip = self.item("Box").toolTip()
        self.assertNotIn("links to", tip)
        self.assertNotIn("which has an error", tip)
        self.padA.Length = 5
        self.doc.recompute()
