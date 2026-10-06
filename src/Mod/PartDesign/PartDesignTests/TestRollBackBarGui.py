# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""The roll-back bar in the tree and drag reorder of a Body's features (FreeCAD-CH ops#127;
notes/reorder-rollback-design.md sections 5.1-5.3 and 5.5).

The Gui logic is thin over Body.rollTo/rollToEnd/reorderObject, which TestBodyReorder covers;
these tests drive the tree: the bar row's place, the commands, the arrow keys, dragging the bar,
dropping a feature among its siblings, a refused drop, and the held items' italic text.

Every model is designed here: a 20 x 20 x 10 block, 4 x 4 x 5 bosses on its top and a hole in it,
as in TestBodyReorder. Off screen: QT_QPA_PLATFORM=offscreen (notes/build.md)."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui

from PartDesignTests.Scenarios import models

V = App.Vector
BAR = 1002  # TreeWidget::BarType
OBJECT = 1001  # TreeWidget::ObjectType


def processEvents(seconds=0.0):
    end = time.monotonic() + seconds
    while True:
        QtGui.QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def waitFor(condition, timeout=3.0):
    """Processes events until condition() is true (the tree updates on a timer)."""
    end = time.monotonic() + timeout
    while True:
        QtGui.QApplication.processEvents()
        if condition():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(0.02)


def isPlaneFacing(face, normal, through):
    if face.Surface.TypeId != "Part::GeomPlane":
        return False
    n = face.normalAt(0, 0)
    return n.isEqual(normal, 1e-6) and abs((face.CenterOfMass - through).dot(normal)) < 1e-6


def faceName(shape, test):
    for i, face in enumerate(shape.Faces, 1):
        if test(face):
            return f"Face{i}"
    raise AssertionError("no such face")


class TestRollBackBarGui(unittest.TestCase):
    def setUp(self):
        if not App.GuiUp or Gui.getMainWindow() is None:
            self.skipTest("Requires the GUI")
        self.doc = models.newDocument("RollBackBarGui")
        if hasattr(self.doc, "HistoryAlgorithm"):
            self.doc.HistoryAlgorithm = "V2"
        self.doc.UndoMode = 1
        self.body = models.body(self.doc)
        Gui.activateView("Gui::View3DInventor", True)
        Gui.activeView().setActiveObject("pdbody", self.body)
        self.modal = []

    def tearDown(self):
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        processEvents()

    # -- the model -------------------------------------------------------------------------------

    def block(self):
        sketch = models.sketch(self.doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body)
        return models.pad(self.body, sketch, 10, "Block")

    def boss(self, name, x, y):
        sketch = models.sketch(
            self.doc, f"{name}Sketch", models.rectangle(x, y, x + 4, y + 4), self.body, z=10
        )
        return models.pad(self.body, sketch, 5, name)

    def hole(self, name="HoleC", x=10, y=10):
        sketch = models.sketch(self.doc, f"{name}Sketch", [models.circle(x, y, 2)], self.body, z=10)
        return models.pocket(self.body, sketch, 3, name)

    def chain(self):
        """Block, boss A, boss B, hole C."""
        block = self.block()
        a = self.boss("BossA", 1, 1)
        b = self.boss("BossB", 15, 15)
        c = self.hole()
        self.doc.recompute()
        self.assertTrue(self.body.isValid())
        return block, a, b, c

    def sketchOn(self, name, feature, face, centre, radius):
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(feature, face)]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        local = sketch.getGlobalPlacement().inverse().multVec(centre)
        sketch.addGeometry(models.circle(local.x, local.y, radius), False)
        return sketch

    # -- the tree --------------------------------------------------------------------------------

    def tree(self):
        for tree in Gui.getMainWindow().findChildren(QtGui.QTreeWidget):
            if self.bodyPath(tree):
                return tree
        self.fail("no tree shows the Body")

    def bodyPath(self, tree):
        """The items from a top-level item down to the Body's, or None. PySide invalidates a
        child item's wrapper when its parent's goes, so the caller holds the whole path."""
        for i in range(tree.topLevelItemCount()):
            top = tree.topLevelItem(i)
            for j in range(top.childCount()):
                docItem = top.child(j)
                if docItem.text(0) != self.doc.Label:
                    continue
                for k in range(docItem.childCount()):
                    item = docItem.child(k)
                    if item.text(0) == self.body.Label:
                        return [top, docItem, item]
            if top.text(0) == self.doc.Label:
                for k in range(top.childCount()):
                    item = top.child(k)
                    if item.text(0) == self.body.Label:
                        return [top, item]
        return None

    def bodyItem(self):
        """The Body's item; its parents' wrappers are kept in self.path."""
        self.path = self.bodyPath(self.tree())
        if not self.path:
            self.fail("no tree item for the Body")
        item = self.path[-1]
        if not item.isExpanded():
            item.setExpanded(True)
            processEvents()
        return item

    def rows(self):
        """The Body's rows as (type, text, italic), read at once (PySide invalidates child
        wrappers with their parent's)."""
        item = self.bodyItem()
        return [
            (item.child(i).type(), item.child(i).text(0), item.child(i).font(0).italic())
            for i in range(item.childCount())
        ]

    def labels(self):
        """The Body's rows as labels, the bar as '|'."""
        return ["|" if t == BAR else text for t, text, _ in self.rows()]

    def waitForRows(self, expected):
        ok = waitFor(lambda: self.labels() == expected)
        self.assertEqual(self.labels(), expected)
        return ok

    def italic(self):
        return {text for t, text, it in self.rows() if t == OBJECT and it}

    def rowRect(self, label):
        """The visual rect of the Body's row with this label ('|': the bar), in viewport
        coordinates."""
        tree = self.tree()
        item = self.bodyItem()
        for i in range(item.childCount()):
            child = item.child(i)
            if (label == "|" and child.type() == BAR) or (
                child.type() == OBJECT and child.text(0) == label
            ):
                tree.scrollToItem(child)
                processEvents()
                return tree.visualItemRect(child)
        self.fail(f"no row {label}")

    def barItem(self):
        item = self.bodyItem()
        for i in range(item.childCount()):
            if item.child(i).type() == BAR:
                return item.child(i)
        self.fail("no bar row")

    def select(self, *objects):
        Gui.Selection.clearSelection()
        for obj in objects:
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
        tree = self.tree()
        names = {obj.Label for obj in objects}
        waitFor(lambda: {i.text(0) for i in tree.selectedItems()} == names)
        self.assertEqual({i.text(0) for i in tree.selectedItems()}, names)

    def mouse(self, kind, pos, buttons):
        viewport = self.tree().viewport()
        event = QtGui.QMouseEvent(
            kind,
            QtCore.QPointF(pos),
            QtCore.QPointF(viewport.mapToGlobal(pos)),
            QtCore.Qt.LeftButton,
            buttons,
            QtCore.Qt.NoModifier,
        )
        QtGui.QApplication.sendEvent(viewport, event)
        processEvents()

    def key(self, key):
        tree = self.tree()
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, key, QtCore.Qt.NoModifier)
        QtGui.QApplication.sendEvent(tree, event)
        processEvents()

    ACTIONS = QtCore.Qt.MoveAction | QtCore.Qt.CopyAction | QtCore.Qt.LinkAction

    def dragEnter(self, pos):
        """Starts a drag of the tree's selection over pos. Qt sends DragMove and Drop only to the
        widget that accepted the DragEnter, which an item view accepts for its model's format."""
        viewport = self.tree().viewport()
        self.mime = QtCore.QMimeData()
        self.mime.setData("application/x-qabstractitemmodeldatalist", QtCore.QByteArray())
        event = QtGui.QDragEnterEvent(
            QtCore.QPoint(pos), self.ACTIONS, self.mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
        )
        QtGui.QApplication.sendEvent(viewport, event)
        self.assertTrue(event.isAccepted(), "the tree refused the drag")

    def dragLeave(self):
        """Ends the drag: the view leaves its dragging state, during which the tree postpones
        its updates (in a real drag, QAbstractItemView does this when the drag ends)."""
        QtGui.QApplication.sendEvent(self.tree().viewport(), QtGui.QDragLeaveEvent())
        processEvents()

    def drop(self, pos):
        """A drop of the tree's selection at pos (viewport coordinates)."""
        viewport = self.tree().viewport()
        self.dragEnter(pos)
        event = QtGui.QDropEvent(
            QtCore.QPointF(pos), self.ACTIONS, self.mime, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier
        )
        QtGui.QApplication.sendEvent(viewport, event)
        self.dragLeave()

    def dragMoveAccepted(self, pos):
        """Would the tree accept a drag of its selection moving over pos?"""
        viewport = self.tree().viewport()
        self.dragEnter(pos)
        mime = self.mime
        event = QtGui.QDragMoveEvent(
            QtCore.QPoint(pos),
            QtCore.Qt.MoveAction | QtCore.Qt.CopyAction | QtCore.Qt.LinkAction,
            mime,
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoModifier,
        )
        QtGui.QApplication.sendEvent(viewport, event)
        accepted = event.isAccepted()
        self.dragLeave()
        return accepted

    def closeModalSoon(self):
        """Records the text of the next modal dialog and closes it, so a refusal can't block."""

        def close():
            widget = QtGui.QApplication.activeModalWidget()
            if widget is None:
                QtCore.QTimer.singleShot(50, close)
                return
            texts = [widget.text()] if hasattr(widget, "text") else []
            self.modal.append(" ".join(texts))
            widget.reject()

        QtCore.QTimer.singleShot(50, close)

    # -- the bar row (5.1) -----------------------------------------------------------------------

    def testBarRowAtTheEnd(self):
        """Not rolled back, the bar is the last row; nothing is held."""
        self.chain()
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "HoleC", "|"])
        self.assertEqual(self.italic(), set())

    def testRollToHereAndToEnd(self):
        """"Roll to here" on boss A puts the bar after it, holds boss B and hole C (italic), shows
        boss A, in one undo step; "Roll to end" brings the bar back."""
        block, a, b, c = self.chain()
        undo = self.doc.UndoCount
        self.select(a)
        Gui.runCommand("PartDesign_RollTo")
        processEvents()
        self.assertIs(self.body.Tip, a)
        self.assertTrue(self.body.isRolledBack())
        self.waitForRows(["Origin", "Block", "BossA", "|", "BossB", "HoleC"])
        waitFor(lambda: self.italic() == {"BossB", "HoleC"})
        self.assertEqual(self.italic(), {"BossB", "HoleC"})
        self.assertTrue(a.Visibility)
        self.assertFalse(c.Visibility)
        self.assertEqual(self.doc.UndoCount, undo + 1)

        self.select(a)
        Gui.runCommand("PartDesign_RollToEnd")
        processEvents()
        self.assertIs(self.body.Tip, c)
        self.assertFalse(self.body.isRolledBack())
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "HoleC", "|"])
        waitFor(lambda: not self.italic())
        self.assertEqual(self.italic(), set())

        self.doc.undo()
        processEvents()
        self.assertIs(self.body.Tip, a)
        self.waitForRows(["Origin", "Block", "BossA", "|", "BossB", "HoleC"])

    def testRollToHereOnASketch(self):
        """On a sketch the bar goes before the sketch's first user (decision 17, Q3): on the
        hole's sketch, which sits on Pad2's top, after Pad2; on the block's sketch, to the top."""
        block = self.block()
        sketch2 = models.sketch(self.doc, "Pad2Sketch", models.rectangle(5, 5, 15, 15), self.body, z=10)
        pad2 = models.pad(self.body, sketch2, 5, "Pad2")
        self.doc.recompute()
        top = faceName(pad2.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 15)))
        onPad2 = self.sketchOn("OnPad2Sketch", pad2, top, V(10, 10, 15), 2)
        hole = models.pocket(self.body, onPad2, 2, "OnPad2")
        self.doc.recompute()
        self.assertTrue(hole.isValid())

        self.select(onPad2)
        Gui.runCommand("PartDesign_RollTo")
        processEvents()
        self.assertIs(self.body.Tip, pad2)

        self.select(self.doc.getObject("BlockSketch"))
        Gui.runCommand("PartDesign_RollTo")
        processEvents()
        self.assertIsNone(self.body.Tip)
        self.assertTrue(self.body.isRolledBack())
        self.waitForRows(["Origin", "|", "Block", "Pad2", "OnPad2"])

    def testArrowKeysMoveTheBar(self):
        """Up and Down move the bar one solid feature, Home to the top, End to the end; the bar
        stays the current row."""
        block, a, b, c = self.chain()
        tree = self.tree()
        tree.setFocus()
        tree.setCurrentItem(self.barItem(), 0, QtCore.QItemSelectionModel.NoUpdate)
        processEvents()

        self.key(QtCore.Qt.Key_Up)
        self.assertIs(self.body.Tip, b)
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "|", "HoleC"])
        self.assertEqual(tree.currentItem().type(), BAR)

        self.key(QtCore.Qt.Key_Up)
        self.assertIs(self.body.Tip, a)
        self.waitForRows(["Origin", "Block", "BossA", "|", "BossB", "HoleC"])
        self.assertEqual(tree.currentItem().type(), BAR)

        self.key(QtCore.Qt.Key_Down)
        self.assertIs(self.body.Tip, b)
        current = tree.currentItem()
        self.assertEqual(current.type(), BAR, f"current {current.text(0)} focus {tree.hasFocus()}")

        self.key(QtCore.Qt.Key_Home)
        self.assertIsNone(self.body.Tip)
        self.waitForRows(["Origin", "|", "Block", "BossA", "BossB", "HoleC"])

        self.key(QtCore.Qt.Key_Down)
        self.assertIs(self.body.Tip, block)

        self.key(QtCore.Qt.Key_End)
        self.assertIs(self.body.Tip, c)
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "HoleC", "|"])

    def testDragTheBar(self):
        """Dragging the bar onto the lower half of boss A's row rolls back to boss A; onto the
        upper half of the block's row, to the top."""
        block, a, b, c = self.chain()
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "HoleC", "|"])
        start = self.rowRect("|").center()
        target = self.rowRect("BossA")
        lower = QtCore.QPoint(target.center().x(), target.bottom() - 2)
        self.mouse(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
        self.mouse(QtCore.QEvent.MouseMove, lower, QtCore.Qt.LeftButton)
        self.mouse(QtCore.QEvent.MouseButtonRelease, lower, QtCore.Qt.NoButton)
        self.assertIs(self.body.Tip, a)
        self.waitForRows(["Origin", "Block", "BossA", "|", "BossB", "HoleC"])

        start = self.rowRect("|").center()
        target = self.rowRect("Block")
        upper = QtCore.QPoint(target.center().x(), target.top() + 2)
        self.mouse(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
        self.mouse(QtCore.QEvent.MouseMove, upper, QtCore.Qt.LeftButton)
        self.mouse(QtCore.QEvent.MouseButtonRelease, upper, QtCore.Qt.NoButton)
        self.assertIsNone(self.body.Tip)

    # -- drag reorder (5.3) ----------------------------------------------------------------------

    def testDropReordersThroughTheBody(self):
        """Boss B dropped above boss A: the Group and the chain change as Body.reorderObject
        makes them (the volume stays), in one undo step that restores both."""
        block, a, b, c = self.chain()
        volume = self.body.Shape.Volume
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "HoleC", "|"])
        undo = self.doc.UndoCount
        self.select(b)
        rect = self.rowRect("BossA")
        self.assertTrue(self.dragMoveAccepted(QtCore.QPoint(rect.center().x(), rect.top() + 1)))
        self.drop(QtCore.QPoint(rect.center().x(), rect.top() + 1))
        names = [o.Name for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")]
        self.assertEqual(names, ["Block", "BossB", "BossA", "HoleC"])
        self.assertIs(b.BaseFeature, block)
        self.assertIs(a.BaseFeature, b)
        self.assertIs(c.BaseFeature, a)
        self.assertIs(self.body.Tip, c)
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, volume, delta=1e-4)
        self.waitForRows(["Origin", "Block", "BossB", "BossA", "HoleC", "|"])
        self.assertEqual(self.doc.UndoCount, undo + 1)

        self.doc.undo()
        processEvents()
        names = [o.Name for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")]
        self.assertEqual(names, ["Block", "BossA", "BossB", "HoleC"])
        self.assertIs(a.BaseFeature, block)
        self.assertIs(b.BaseFeature, a)

    def testTwoFeaturesDroppedTogether(self):
        """Boss B and hole C, selected together, dropped above boss A keep their order."""
        block, a, b, c = self.chain()
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "HoleC", "|"])
        self.select(c, b)
        rect = self.rowRect("BossA")
        self.drop(QtCore.QPoint(rect.center().x(), rect.top() + 1))
        names = [o.Name for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")]
        self.assertEqual(names, ["Block", "BossB", "HoleC", "BossA"])
        self.assertIs(self.body.Tip, a)

    def testDropOnTheBodyRowInsertsAtTheBar(self):
        """Rolled back to boss A, hole C dropped on the Body's own row goes in at the bar, as a
        new feature would: right after boss A, and the bar follows it; boss B stays held. One
        undo step."""
        block, a, b, c = self.chain()
        self.select(a)
        Gui.runCommand("PartDesign_RollTo")
        processEvents()
        self.waitForRows(["Origin", "Block", "BossA", "|", "BossB", "HoleC"])
        undo = self.doc.UndoCount
        self.select(c)
        tree = self.tree()
        rect = tree.visualItemRect(self.bodyItem())
        self.drop(rect.center())
        names = [o.Name for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")]
        self.assertEqual(names, ["Block", "BossA", "HoleC", "BossB"])
        self.assertIs(c.BaseFeature, a)
        self.assertIs(b.BaseFeature, c)
        self.assertIs(self.body.Tip, c)
        self.assertTrue(self.body.holds(b))
        self.waitForRows(["Origin", "Block", "BossA", "HoleC", "|", "BossB"])
        self.assertEqual(self.doc.UndoCount, undo + 1)

    def freeSketch(self):
        """A sketch at the end of the Body that no feature uses: a row of its own."""
        return models.sketch(self.doc, "FreeSketch", models.rectangle(2, 2, 6, 6), self.body, z=20)

    def testHeldSketchAndDatumAreItalic(self):
        """A sketch and a datum plane after the bar that nothing above it uses are held (rule
        B1): rolled back to boss A, their rows are italic as boss B and hole C are; rolled to the
        end, none is."""
        block, a, b, c = self.chain()
        self.freeSketch()
        self.body.newObject("PartDesign::Plane", "FreePlane")
        self.doc.recompute()
        end = ["Origin", "Block", "BossA", "BossB", "HoleC", "FreeSketch", "FreePlane", "|"]
        self.waitForRows(end)
        self.select(a)
        Gui.runCommand("PartDesign_RollTo")
        processEvents()
        self.waitForRows(["Origin", "Block", "BossA", "|", "BossB", "HoleC", "FreeSketch", "FreePlane"])
        held = {"BossB", "HoleC", "FreeSketch", "FreePlane"}
        waitFor(lambda: self.italic() == held)
        self.assertEqual(self.italic(), held)
        self.select(a)
        Gui.runCommand("PartDesign_RollToEnd")
        processEvents()
        self.waitForRows(end)
        waitFor(lambda: not self.italic())
        self.assertEqual(self.italic(), set())

    def testSketchRowDropsThroughTheBody(self):
        """An own sketch row dropped above boss A moves through Body.reorderObject: it lands
        before boss A, no solid's chain or the Tip changes, in one undo step."""
        block, a, b, c = self.chain()
        self.freeSketch()
        self.doc.recompute()
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "HoleC", "FreeSketch", "|"])
        undo = self.doc.UndoCount
        self.select(self.doc.getObject("FreeSketch"))
        rect = self.rowRect("BossA")
        self.drop(QtCore.QPoint(rect.center().x(), rect.top() + 1))
        group = [o.Name for o in self.body.Group]
        self.assertGreater(group.index("FreeSketch"), group.index("Block"))
        self.assertLess(group.index("FreeSketch"), group.index("BossA"))
        self.assertIs(a.BaseFeature, block)
        self.assertIs(b.BaseFeature, a)
        self.assertIs(c.BaseFeature, b)
        self.assertIs(self.body.Tip, c)
        self.waitForRows(["Origin", "Block", "FreeSketch", "BossA", "BossB", "HoleC", "|"])
        self.assertEqual(self.doc.UndoCount, undo + 1)

    def testRefusedDropShowsWhyAndChangesNothing(self):
        """The hole's sketch sits on a binder outside the Body that binds Pad2's top: dropped
        above the block, the move is refused (a cycle); the message names it, nothing changes
        and no undo step is left."""
        block = self.block()
        sketch2 = models.sketch(self.doc, "Pad2Sketch", models.rectangle(5, 5, 15, 15), self.body, z=10)
        pad2 = models.pad(self.body, sketch2, 5, "Pad2")
        self.doc.recompute()
        top = faceName(pad2.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 15)))
        binder = self.doc.addObject("PartDesign::SubShapeBinder", "Outside")
        binder.Support = [(pad2, (top,))]
        self.doc.recompute()
        sketch = self.sketchOn("ViaBinder", binder, "Face1", V(10, 10, 15), 1)
        hole = models.pocket(self.body, sketch, 1, "ViaBinderHole")
        self.doc.recompute()
        self.assertTrue(hole.isValid())
        group = list(self.body.Group)
        undo = self.doc.UndoCount

        waitFor(lambda: "ViaBinderHole" in self.labels())
        self.select(hole)
        rect = self.rowRect("Block")
        self.closeModalSoon()
        self.drop(QtCore.QPoint(rect.center().x(), rect.top() + 1))
        waitFor(lambda: self.modal)
        self.assertEqual(len(self.modal), 1)
        self.assertIn("cycle", self.modal[0])
        self.assertEqual(list(self.body.Group), group)
        self.assertIs(self.body.Tip, hole)
        self.assertEqual(self.doc.UndoCount, undo)


if __name__ == "__main__":
    unittest.main()
