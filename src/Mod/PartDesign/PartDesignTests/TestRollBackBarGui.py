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


class Raiser:
    """A PartDesign::FeaturePython proxy that passes its base on, or raises while `fail` is set."""

    fail = False

    def __init__(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        if Raiser.fail:
            raise RuntimeError("raised in the tail")
        obj.Shape = obj.BaseFeature.Shape


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
        # Stops this test's pending modal and popup closers (they would answer the next test's)
        self.closing = False
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

    def answerModalSoon(self, button=None, tries=100):
        """Records the text of the next modal dialog and answers it with button (a QMessageBox
        standard button), else closes it, so a question or refusal can't block. Gives up after
        tries * 50 ms."""
        left = [tries]
        self.closing = True

        def answer():
            if not self.closing:
                return
            widget = QtGui.QApplication.activeModalWidget()
            if widget is None:
                left[0] -= 1
                if left[0] > 0:
                    QtCore.QTimer.singleShot(50, answer)
                return
            texts = [widget.text()] if hasattr(widget, "text") else []
            self.modal.append(" ".join(texts))
            chosen = widget.button(button) if button is not None and hasattr(widget, "button") else None
            if chosen:
                chosen.click()
            else:
                widget.reject()

        QtCore.QTimer.singleShot(50, answer)

    def closeModalSoon(self):
        self.answerModalSoon()

    def closePopupSoon(self, tries=40):
        """Closes the next popup (a context menu), recording its class in self.popups. Gives up
        after tries * 50 ms."""
        self.popups = []
        left = [tries]
        self.closing = True

        def close():
            if not self.closing:
                return
            popup = QtGui.QApplication.activePopupWidget()
            if popup is None:
                left[0] -= 1
                if left[0] > 0:
                    QtCore.QTimer.singleShot(50, close)
                return
            self.popups.append(type(popup).__name__)
            popup.close()

        QtCore.QTimer.singleShot(50, close)

    LOCKED = "a dialog or an edit is open"

    def statusLabels(self):
        return Gui.getMainWindow().statusBar().findChildren(QtGui.QLabel)

    def clearLockMessage(self):
        for label in self.statusLabels():
            if self.LOCKED in label.text():
                label.setText("")

    def lockMessageShown(self):
        return any(self.LOCKED in label.text() for label in self.statusLabels())

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

    # -- the edit roll-back and Final (5.4) ------------------------------------------------------

    END = ["Origin", "Block", "BossA", "BossB", "HoleC", "|"]
    AT_A = ["Origin", "Block", "BossA", "|", "BossB", "HoleC"]

    def openEdit(self, obj):
        """Opens obj's dialog as a double click on its row does (in an "Edit" transaction)."""
        Gui.getDocument(self.doc.Name).getObject(obj.Name).doubleClicked()
        processEvents()
        self.assertTrue(Gui.Control.activeDialog())
        return Gui.Control.activeTaskDialog()

    def closeEdit(self, dialog, ok):
        if ok:
            dialog.accept()
        else:
            dialog.reject()
        processEvents()
        self.assertFalse(Gui.Control.activeDialog())

    def taskButton(self, which):
        """The task panel's OK or Cancel button (TestReferencePickerGui.taskButton)."""
        for box in Gui.getMainWindow().findChildren(QtGui.QDialogButtonBox):
            button = box.button(which)
            if button is None or not button.isVisible():
                continue
            parent = box.parentWidget()
            while parent is not None:
                if parent.metaObject().className() == "Gui::TaskView::TaskView":
                    return button
                parent = parent.parentWidget()
        self.fail("no task panel button")

    def panelWidget(self, kind, name):
        widgets = Gui.getMainWindow().findChildren(kind, name)
        shown = [w for w in widgets if w.isVisible()]
        self.assertTrue(shown or widgets, f"no {name} in the task panel")
        return (shown or widgets)[-1]

    def setLength(self, value):
        """Types a length into the open Pad dialog (the dialog recomputes the Pad alone)."""
        self.panelWidget(QtGui.QWidget, "lengthEdit").setProperty("rawValue", value)
        processEvents()

    def setFinal(self, on):
        self.panelWidget(QtGui.QCheckBox, "showFinalCheckBox").setChecked(on)
        processEvents()

    def held(self):
        """The held solid features' labels."""
        return {
            o.Label
            for o in self.body.Group
            if o.isDerivedFrom("PartDesign::Feature") and self.body.holds(o)
        }

    def assertAtTheEnd(self, tip):
        self.assertIs(self.body.Tip, tip)
        self.assertFalse(self.body.isRolledBack())
        self.waitForRows(self.END)
        waitFor(lambda: not self.italic())
        self.assertEqual(self.italic(), set())

    def testEditHoldsTheFeaturesAfterIt(self):
        """Boss A's dialog rolls the Body back to boss A while it is open: boss B and hole C are
        held (italic, the bar row after boss A) and the Tip doesn't change; Cancel brings the
        end back."""
        block, a, b, c = self.chain()
        self.waitForRows(self.END)
        dialog = self.openEdit(a)
        self.assertIs(self.body.Tip, c)
        self.assertTrue(self.body.isRolledBack())
        self.assertEqual(self.held(), {"BossB", "HoleC"})
        self.waitForRows(self.AT_A)
        waitFor(lambda: self.italic() == {"BossB", "HoleC"})
        self.assertEqual(self.italic(), {"BossB", "HoleC"})
        # The bar's keys don't move it while the dialog holds it
        tree = self.tree()
        tree.setFocus()
        tree.setCurrentItem(self.barItem(), 0, QtCore.QItemSelectionModel.NoUpdate)
        processEvents()
        self.key(QtCore.Qt.Key_Up)
        self.assertIs(self.body.Tip, c)
        self.closeEdit(dialog, ok=False)
        self.assertAtTheEnd(c)

    def testOkComputesTheTailInOneStep(self):
        """Boss A made 8 high in its dialog: while it is open, boss A follows and the held hole C
        keeps the old shape (top at 15); OK computes the tail (the Body's top at 18) in one undo
        step, which undo takes back."""
        block, a, b, c = self.chain()
        self.assertAlmostEqual(self.body.Shape.BoundBox.ZMax, 15, places=6)
        undo = self.doc.UndoCount
        dialog = self.openEdit(a)
        self.setLength(8)
        self.assertAlmostEqual(a.Shape.BoundBox.ZMax, 18, places=6)
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 15, places=6)
        self.closeEdit(dialog, ok=True)
        self.assertAtTheEnd(c)
        self.assertTrue(c.isValid(), c.getStatusString())
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 18, places=6)
        self.assertAlmostEqual(self.body.Shape.BoundBox.ZMax, 18, places=6)
        self.assertFalse([o.Name for o in self.body.Group if "Touched" in o.State])
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertAlmostEqual(a.Length.Value, 5, places=6)
        self.assertAlmostEqual(self.body.Shape.BoundBox.ZMax, 15, places=6)

    def testFinalLiftsTheRollBack(self):
        """"Show final result" computes the tail with the dialog's value (the Body's end result,
        nothing held) and shows the Tip; unchecked, the Body is rolled back to boss A again.
        Cancel restores boss A and the tail."""
        block, a, b, c = self.chain()
        dialog = self.openEdit(a)
        self.setFinal(False)
        self.setLength(8)
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 15, places=6)
        self.setFinal(True)
        self.assertFalse(self.body.isRolledBack())
        self.assertEqual(self.held(), set())
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 18, places=6)
        self.assertTrue(c.ViewObject.Visibility)
        self.waitForRows(self.END)
        # In Final, the tail follows each change
        self.setLength(7)
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 17, places=6)
        self.setFinal(False)
        self.assertTrue(self.body.isRolledBack())
        self.assertEqual(self.held(), {"BossB", "HoleC"})
        self.waitForRows(self.AT_A)
        self.closeEdit(dialog, ok=False)
        self.assertAtTheEnd(c)
        self.assertAlmostEqual(a.Length.Value, 5, places=6)
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 15, places=6)

    def testEditingASketchRollsToBeforeItsFirstUser(self):
        """Boss B's sketch in the sketcher: the Body is rolled back to boss A, the solid before
        boss B (decision 17, Q3); closing the sketch brings the end back."""
        block, a, b, c = self.chain()
        sketch = self.doc.getObject("BossBSketch")
        gdoc = Gui.getDocument(self.doc.Name)
        gdoc.setEdit(sketch.Name)
        processEvents()
        self.assertIs(self.body.Tip, c)
        self.assertEqual(self.held(), {"BossB", "HoleC"})
        self.waitForRows(self.AT_A)
        gdoc.resetEdit()
        processEvents()
        self.assertAtTheEnd(c)

    def testEditingTheFirstSketchHoldsEverySolid(self):
        """The block's sketch is used by the first solid: editing it holds every solid (the top)."""
        block, a, b, c = self.chain()
        gdoc = Gui.getDocument(self.doc.Name)
        gdoc.setEdit("BlockSketch")
        processEvents()
        self.assertEqual(self.held(), {"Block", "BossA", "BossB", "HoleC"})
        self.waitForRows(["Origin", "|", "Block", "BossA", "BossB", "HoleC"])
        gdoc.resetEdit()
        processEvents()
        self.assertAtTheEnd(c)

    def testEditingAHeldFeatureRollsForward(self):
        """Rolled back to boss A, hole C's dialog rolls forward to hole C (nothing held while it
        is open); Cancel leaves the bar after boss A."""
        block, a, b, c = self.chain()
        self.body.rollTo(a)
        self.doc.recompute()
        self.waitForRows(self.AT_A)
        dialog = self.openEdit(c)
        self.assertIs(self.body.Tip, a)
        self.assertFalse(self.body.isRolledBack())
        self.waitForRows(self.END)
        self.closeEdit(dialog, ok=False)
        self.assertIs(self.body.Tip, a)
        self.assertEqual(self.held(), {"BossB", "HoleC"})
        self.waitForRows(self.AT_A)

    def testUndoWithThePanelOpenKeepsTheSavedBar(self):
        """Rolled to boss B, boss A's dialog open: an undo (which takes back the dialog's own
        step) leaves the saved bar after boss B and the dialog's roll-back in place; after
        Cancel, the Body is rolled back to boss B as before."""
        block, a, b, c = self.chain()
        self.select(b)
        Gui.runCommand("PartDesign_RollTo")
        processEvents()
        self.assertIs(self.body.Tip, b)
        dialog = self.openEdit(a)
        self.doc.undo()
        processEvents()
        self.assertIs(self.body.Tip, b)
        self.assertEqual(self.held(), {"BossB", "HoleC"})
        self.closeEdit(dialog, ok=False)
        self.assertIs(self.body.Tip, b)
        self.assertEqual(self.held(), {"HoleC"})
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "|", "HoleC"])

    def testFailedRecomputeInTheDialogLeavesTheBar(self):
        """Boss A made to fail inside its dialog (length 0) fails boss A alone and holds the
        rest; Cancel restores it and the Body ends where it was."""
        block, a, b, c = self.chain()
        dialog = self.openEdit(a)
        self.setLength(0)
        self.assertFalse(a.isValid())
        self.assertIs(self.body.Tip, c)
        self.assertEqual(self.held(), {"BossB", "HoleC"})
        self.closeEdit(dialog, ok=False)
        self.assertAtTheEnd(c)
        self.assertTrue(a.isValid(), a.getStatusString())
        self.assertTrue(c.isValid(), c.getStatusString())
        self.assertAlmostEqual(self.body.Shape.BoundBox.ZMax, 15, places=6)

    def testClosingTheDocumentWithThePanelOpen(self):
        """A document saved rolled back to boss B and closed with boss A's dialog open reopens
        rolled back to boss B (the edit's point is not saved)."""
        import os
        import tempfile

        block, a, b, c = self.chain()
        self.body.rollTo(b)
        self.doc.recompute()
        bodyName, docName = self.body.Name, self.doc.Name
        path = os.path.join(tempfile.mkdtemp(), "EditRollBack.FCStd")
        self.doc.saveAs(path)
        self.openEdit(a)
        App.closeDocument(docName)
        processEvents()
        self.assertFalse(Gui.Control.activeDialog())
        self.doc = App.openDocument(path)
        self.body = self.doc.getObject(bodyName)
        self.assertEqual(self.body.Tip.Name, "BossB")
        self.assertTrue(self.body.isRolledBack())
        self.assertEqual(self.held(), {"HoleC"})

    def testSavingWhileClosingWithThePanelOpen(self):
        """Rolled back to boss B, boss A made 8 high in its dialog, the window closed (the
        document's canClose) and the document saved there, during the edit: it reopens rolled
        back to boss B (the edit's point is not saved), boss A 8 high."""
        import os
        import tempfile

        block, a, b, c = self.chain()
        self.body.rollTo(b)
        self.doc.recompute()
        bodyName, docName = self.body.Name, self.doc.Name
        path = os.path.join(tempfile.mkdtemp(), "SavedInEdit.FCStd")
        self.doc.saveAs(path)
        self.openEdit(a)
        self.setLength(8)
        self.assertTrue(self.body.isRolledBack())
        self.answerModalSoon(QtGui.QMessageBox.Save)
        # Closing the document's 3D view asks its canClose
        area = Gui.getMainWindow().findChild(QtGui.QMdiArea)
        views = [w for w in area.subWindowList() if w.windowTitle().startswith(self.doc.Label)]
        self.assertTrue(views, [w.windowTitle() for w in area.subWindowList()])
        for view in views:
            view.close()
        waitFor(lambda: docName not in App.listDocuments())
        self.assertNotIn(docName, App.listDocuments())
        self.assertEqual(len(self.modal), 1, "no save question")
        self.assertFalse(Gui.Control.activeDialog())
        self.doc = App.openDocument(path)
        self.body = self.doc.getObject(bodyName)
        self.assertEqual(self.body.Tip.Name, "BossB")
        self.assertTrue(self.body.isRolledBack())
        self.assertEqual(self.held(), {"HoleC"})
        self.assertAlmostEqual(self.doc.getObject("BossA").Length.Value, 8, places=6)

    def testTheBarIsLockedDuringAnEdit(self):
        """In Final (no edit point) the bar's keys, drag and menu don't move it while boss A's
        dialog is open, and the roll commands are off: the status bar says why, and Cancel still
        takes the dialog's change back, leaving no undo step."""
        block, a, b, c = self.chain()
        self.waitForRows(self.END)
        undo = self.doc.UndoCount
        dialog = self.openEdit(a)
        self.setFinal(True)
        self.setLength(8)
        self.assertFalse(self.body.isRolledBack())
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 18, places=6)
        self.waitForRows(self.END)

        tree = self.tree()
        tree.setFocus()
        tree.setCurrentItem(self.barItem(), 0, QtCore.QItemSelectionModel.NoUpdate)
        processEvents()
        self.clearLockMessage()
        self.key(QtCore.Qt.Key_Up)
        self.assertIs(self.body.Tip, c)
        self.assertTrue(self.lockMessageShown(), "keys")

        # (the message is read at the press: moving over a row shows that row's status)
        self.clearLockMessage()
        start = self.rowRect("|").center()
        target = self.rowRect("BossA")
        lower = QtCore.QPoint(target.center().x(), target.bottom() - 2)
        self.mouse(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton)
        self.assertTrue(self.lockMessageShown(), "drag")
        self.mouse(QtCore.QEvent.MouseMove, lower, QtCore.Qt.LeftButton)
        self.mouse(QtCore.QEvent.MouseButtonRelease, lower, QtCore.Qt.NoButton)
        self.assertIs(self.body.Tip, c)

        self.clearLockMessage()
        self.closePopupSoon()
        viewport = tree.viewport()
        pos = self.rowRect("|").center()
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse, pos, viewport.mapToGlobal(pos)
        )
        QtGui.QApplication.sendEvent(viewport, event)
        processEvents()
        self.assertEqual(self.popups, [])
        self.assertTrue(self.lockMessageShown(), "menu")
        self.assertIs(self.body.Tip, c)

        self.assertFalse(Gui.Command.get("PartDesign_RollTo").isActive())
        self.assertFalse(Gui.Command.get("PartDesign_RollToEnd").isActive())

        self.closeEdit(dialog, ok=False)
        self.assertAtTheEnd(c)
        self.assertAlmostEqual(a.Length.Value, 5, places=6)
        self.assertAlmostEqual(c.Shape.BoundBox.ZMax, 15, places=6)
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertTrue(Gui.Command.get("PartDesign_RollToEnd").isActive())

    def testNoReorderDuringAnEdit(self):
        """With boss A's dialog open, a drag of boss B among the Body's rows is refused and the
        status bar says why; a drop that comes anyway is refused and changes nothing."""
        block, a, b, c = self.chain()
        self.waitForRows(self.END)
        dialog = self.openEdit(a)
        self.waitForRows(self.AT_A)
        group = list(self.body.Group)
        self.select(b)
        rect = self.rowRect("BossA")
        pos = QtCore.QPoint(rect.center().x(), rect.top() + 1)
        self.clearLockMessage()
        self.assertFalse(self.dragMoveAccepted(pos))
        self.assertTrue(self.lockMessageShown())
        self.closeModalSoon()
        self.drop(pos)
        processEvents(0.3)
        self.assertEqual(list(self.body.Group), group)
        if self.modal:
            self.assertIn(self.LOCKED, self.modal[0])
        self.closeEdit(dialog, ok=False)
        self.assertAtTheEnd(c)
        self.assertEqual(list(self.body.Group), group)

    def testShowFinalPreferenceStartsInFinal(self):
        """With the "Show final result" preference on, boss A's dialog opens in Final: its box
        checked, nothing held; unchecked, the Body is rolled back to boss A."""
        group = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign/Preview")
        had = group.GetBool("ShowFinal", False)
        group.SetBool("ShowFinal", True)
        try:
            block, a, b, c = self.chain()
            dialog = self.openEdit(a)
            self.assertTrue(self.panelWidget(QtGui.QCheckBox, "showFinalCheckBox").isChecked())
            self.assertFalse(self.body.isRolledBack())
            self.assertEqual(self.held(), set())
            self.waitForRows(self.END)
            self.setFinal(False)
            self.assertEqual(self.held(), {"BossB", "HoleC"})
            self.waitForRows(self.AT_A)
            self.closeEdit(dialog, ok=False)
            self.assertAtTheEnd(c)
        finally:
            group.SetBool("ShowFinal", had)

    def testEditingADatumRollsToBeforeItsFirstUser(self):
        """A datum plane on the block's top carries the sketch of a boss: its dialog rolls the
        Body back to the block (the boss held); Cancel, and OK, end the edit and bring the end
        back."""
        block = self.block()
        self.doc.recompute()
        top = faceName(block.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 10)))
        plane = self.body.newObject("PartDesign::Plane", "DatumP")
        plane.AttachmentSupport = [(block, top)]
        plane.MapMode = "FlatFace"
        self.doc.recompute()
        sketch = self.sketchOn("OnDatumSketch", plane, "", V(10, 10, 10), 2)
        boss = models.pad(self.body, sketch, 3, "OnDatum")
        self.doc.recompute()
        self.assertTrue(boss.isValid(), boss.getStatusString())
        dialog = self.openEdit(plane)
        self.assertIs(self.body.Tip, boss)
        self.assertEqual(self.held(), {"OnDatum"})
        # The attacher dialog leaves the edit on (upstream #25277); the datum dialog ends it
        gdoc = Gui.getDocument(self.doc.Name)
        self.taskButton(QtGui.QDialogButtonBox.Cancel).click()
        processEvents()
        self.assertFalse(Gui.Control.activeDialog())
        self.assertIsNone(gdoc.getInEdit())
        self.assertIs(self.body.Tip, boss)
        self.assertFalse(self.body.isRolledBack())
        self.assertEqual(self.held(), set())
        # OK too
        self.openEdit(plane)
        self.assertEqual(self.held(), {"OnDatum"})
        self.taskButton(QtGui.QDialogButtonBox.Ok).click()
        processEvents()
        self.assertFalse(Gui.Control.activeDialog())
        self.assertIsNone(gdoc.getInEdit())
        self.assertIs(self.body.Tip, boss)
        self.assertFalse(self.body.isRolledBack())
        self.assertEqual(self.held(), set())

    def testEditingASketchWithNoUsersHoldsNothing(self):
        """A sketch at the end that nothing uses: editing it holds nothing."""
        block, a, b, c = self.chain()
        self.freeSketch()
        self.doc.recompute()
        gdoc = Gui.getDocument(self.doc.Name)
        gdoc.setEdit("FreeSketch")
        processEvents()
        self.assertFalse(self.body.isRolledBack())
        self.assertEqual(self.held(), set())
        gdoc.resetEdit()
        processEvents()
        self.assertIs(self.body.Tip, c)
        self.assertFalse(self.body.isRolledBack())

    def testEditingASketchWithSeveralUsers(self):
        """A sketch used by a boss and, later, by a pocket: editing it rolls the Body back to
        before its first user (the block), holding both."""
        block = self.block()
        shared = models.sketch(self.doc, "SharedSketch", models.rectangle(1, 1, 5, 5), self.body, z=10)
        boss = models.pad(self.body, shared, 5, "BossS")
        b = self.boss("BossB", 15, 15)
        pocket = models.pocket(self.body, shared, 3, "PocketS")
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        gdoc = Gui.getDocument(self.doc.Name)
        gdoc.setEdit(shared.Name)
        processEvents()
        self.assertIs(self.body.Tip, pocket)
        self.assertEqual(self.held(), {"BossS", "BossB", "PocketS"})
        gdoc.resetEdit()
        processEvents()
        self.assertIs(self.body.Tip, pocket)
        self.assertFalse(self.body.isRolledBack())

    def testASecondEditFromTheFirst(self):
        """Boss A's dialog open, a double click on boss B closes it (the question answered) and
        opens boss B's: the Body is rolled back to boss B; Cancel brings the end back."""
        block, a, b, c = self.chain()
        self.openEdit(a)
        self.answerModalSoon(QtGui.QMessageBox.Yes)
        dialog = self.openEdit(b)
        self.assertEqual(self.held(), {"HoleC"})
        self.waitForRows(["Origin", "Block", "BossA", "BossB", "|", "HoleC"])
        self.closeEdit(dialog, ok=False)
        self.assertAtTheEnd(c)

    def testSketchOkComputesTheTail(self):
        """Boss B's sketch moved in the sketcher to stick out of the block: closing it computes
        the held tail (the Body's X extent 22), nothing left touched. The sketch commits its own
        steps before the tail computes, so undoing them and recomputing brings back the X extent
        20."""
        block, a, b, c = self.chain()
        self.assertAlmostEqual(self.body.Shape.BoundBox.XMax, 20, places=6)
        undo = self.doc.UndoCount
        sketch = self.doc.getObject("BossBSketch")
        gdoc = Gui.getDocument(self.doc.Name)
        gdoc.setEdit(sketch.Name)
        processEvents()
        self.assertEqual(self.held(), {"BossB", "HoleC"})
        self.doc.openTransaction("Move the boss")
        models.moveRectangle(sketch, 18, 15, 22, 19)
        self.doc.commitTransaction()
        gdoc.resetEdit()
        processEvents()
        self.assertAtTheEnd(c)
        self.assertTrue(c.isValid(), c.getStatusString())
        self.assertAlmostEqual(self.body.Shape.BoundBox.XMax, 22, places=6)
        self.assertFalse([o.Name for o in self.body.Group if "Touched" in o.State])
        self.assertGreater(self.doc.UndoCount, undo)
        while self.doc.UndoCount > undo:
            self.doc.undo()
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.BoundBox.XMax, 20, places=6)

    def testAnExceptionInTheTail(self):
        """A feature after hole C that raises when it computes: in Final the raise is reported
        and the dialog stays; OK closes the edit (the document leaves edit mode) and the
        feature is marked failed."""
        block, a, b, c = self.chain()
        raiser = self.body.newObject("PartDesign::FeaturePython", "Raiser")
        Raiser(raiser)
        self.doc.recompute()
        self.assertTrue(raiser.isValid(), raiser.getStatusString())
        dialog = self.openEdit(a)
        Raiser.fail = True
        try:
            self.setLength(8)
            self.setFinal(True)
            self.assertTrue(Gui.Control.activeDialog())
            self.assertFalse(raiser.isValid())
            self.closeEdit(dialog, ok=True)
        finally:
            Raiser.fail = False
        self.assertIsNone(Gui.getDocument(self.doc.Name).getInEdit())
        self.assertIs(self.body.Tip, raiser)
        self.assertFalse(self.body.isRolledBack())
        self.assertAlmostEqual(a.Length.Value, 8, places=6)
        self.assertFalse(raiser.isValid())


if __name__ == "__main__":
    unittest.main()
