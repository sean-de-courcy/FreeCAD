# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""The property editor's context menu and the undo stack (FreeCAD-CH ops#163).

"Rename Property" books a transaction in the document before it asks for the new name. Cancelling
the name dialog left the booking in place, so the user's next change in the document was recorded
as "Rename property".

The model: a VarSet with a dynamic integer Width. Off screen: QT_QPA_PLATFORM=offscreen.

To run tests:
    FreeCAD -t TestPropertyEditorGui
"""

import sys
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets
from PySide6 import QtTest


def pump(seconds=0.5):
    """Processes events for a while: the property view fills on a timer."""
    end = time.monotonic() + seconds
    while True:
        QtWidgets.QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def findRow(model, parent, name, leaf=True):
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        # a group can have a property's name: take a leaf, or a property with rows (a Vector)
        hasRows = model.rowCount(index) != 0
        if str(model.data(index)) == name and (not hasRows if leaf else hasRows and parent.isValid()):
            return index
        found = findRow(model, index, name, leaf)
        if found is not None:
            return found
    return None


class TestPropertyEditorGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestPropertyEditorGui")
        self.doc.UndoMode = 1
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        self.doc.openTransaction("Make VarSet")
        self.obj = self.doc.addObject("App::VarSet", "VarSet")
        self.obj.addProperty("App::PropertyInteger", "Width", "Variables")
        self.obj.Width = 5
        self.doc.commitTransaction()
        self.seen = []

    def tearDown(self):
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)

    def dataEditor(self):
        for editor in Gui.getMainWindow().findChildren(QtWidgets.QTreeView):
            # the Data tab's: the View tab can have a group with the same name
            if editor.objectName() == "propertyEditorData":
                return editor
        self.fail("no propertyEditorData")

    def answerSoon(self, find, answer, tries=60):
        """Polls every 50 ms for a widget find() returns, records its class in self.seen and
        answers it. Gives up after tries * 50 ms."""
        left = [tries]

        def poll():
            widget = find()
            if widget is None:
                left[0] -= 1
                if left[0] > 0:
                    QtCore.QTimer.singleShot(50, poll)
                return
            self.seen.append(type(widget).__name__)
            answer(widget)

        QtCore.QTimer.singleShot(50, poll)

    def testCancelledRenameLeavesNothingBooked(self):
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.obj.Name)
        pump(1.0)
        editor = self.dataEditor()
        index = findRow(editor.model(), QtCore.QModelIndex(), "Width")
        self.assertIsNotNone(index, "no Width row in the property view")
        # the menu acts on the selected rows, not on the event's position
        editor.setCurrentIndex(index)
        editor.selectionModel().select(
            index,
            QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
        )

        def pickRename(menu):
            actions = [a for a in menu.actions() if a.text() == "Rename Property"]
            self.assertTrue(actions, "no Rename Property in the menu")
            menu.setActiveAction(actions[0])
            for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                event = QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
                QtWidgets.QApplication.sendEvent(menu, event)

        def nameDialog():
            widget = QtWidgets.QApplication.activeModalWidget()
            return widget if isinstance(widget, QtWidgets.QInputDialog) else None

        self.answerSoon(QtWidgets.QApplication.activePopupWidget, pickRename)
        self.answerSoon(nameDialog, lambda dialog: dialog.reject())
        undos = self.doc.UndoCount
        viewport = editor.viewport()
        pos = editor.visualRect(index).center()
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse, pos, viewport.mapToGlobal(pos)
        )
        QtWidgets.QApplication.sendEvent(viewport, event)
        pump()
        self.assertEqual(self.seen, ["QMenu", "QInputDialog"])
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)

        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.obj.Width = 7
        self.assertEqual(self.doc.UndoCount, undos)
        self.assertNotIn("Rename property", self.doc.UndoNames)

    # ops#178: Rename opened its transaction with a fresh ID, which committed one the document had
    # booked (a task dialog's), and committed with an ID of 0 when it had none of its own.

    def renameThroughMenu(self, name, newName, before=None):
        """Renames the VarSet's property name to newName through the Data tab's context menu and
        the name dialog, as a user does; before() runs once the row is selected."""

        def nameDialog():
            widget = QtWidgets.QApplication.activeModalWidget()
            return widget if isinstance(widget, QtWidgets.QInputDialog) else None

        def answer(dialog):
            dialog.setTextValue(newName)
            dialog.accept()

        self.throughMenu(name, "Rename Property", nameDialog, answer, before)
        self.assertEqual(self.seen, ["QMenu", "QInputDialog"])

    def throughMenu(self, name, action, findDialog=None, answer=None, before=None, objects=None):
        """Picks action in the Data tab's context menu on row name, as a user does, with objects
        (default: the VarSet) selected, and answers the dialog findDialog() returns with
        answer(dialog); before() runs once the row is selected."""
        self.seen = []
        Gui.Selection.clearSelection()
        for obj in objects or [self.obj]:
            Gui.Selection.addSelection(obj.Document.Name, obj.Name)
        pump(1.0)
        editor = self.dataEditor()
        index = findRow(editor.model(), QtCore.QModelIndex(), name)
        self.assertIsNotNone(index, "no %s row in the property view" % name)
        editor.setCurrentIndex(index)
        editor.selectionModel().select(
            index,
            QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
        )
        if before:
            before()

        def pick(menu):
            actions = [a for a in menu.actions() if a.text() == action]
            self.assertTrue(actions, "no %s in the menu" % action)
            menu.setActiveAction(actions[0])
            for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                event = QtGui.QKeyEvent(kind, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
                QtWidgets.QApplication.sendEvent(menu, event)

        self.answerSoon(QtWidgets.QApplication.activePopupWidget, pick)
        if findDialog:
            self.answerSoon(findDialog, answer)
        viewport = editor.viewport()
        pos = editor.visualRect(index).center()
        event = QtGui.QContextMenuEvent(
            QtGui.QContextMenuEvent.Mouse, pos, viewport.mapToGlobal(pos)
        )
        QtWidgets.QApplication.sendEvent(viewport, event)
        pump()

    def testRenameKeepsBookedTransactionOpen(self):
        """A transaction open in the document, as a task dialog keeps one, with a change to another
        property in it: the rename joins it, and aborting it takes back the change and the rename.
        (A value change and a rename of the same property in one transaction don't roll back:
        ops#229.)"""
        self.obj.addProperty("App::PropertyInteger", "Depth", "Variables")
        self.obj.Depth = 3
        undos = self.doc.UndoCount
        self.doc.openTransaction("Task")
        self.obj.Depth = 9
        tid = self.doc.getBookedTransactionID()
        self.renameThroughMenu("Width", "Wide")
        self.assertEqual(self.obj.getPropertyByName("Wide"), 5)
        self.assertEqual(self.doc.getBookedTransactionID(), tid)
        self.assertEqual(self.doc.UndoNames[0], "Task")

        self.doc.abortTransaction()
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)
        self.assertNotIn("Wide", self.obj.PropertiesList)
        self.assertEqual(self.obj.Depth, 3)
        self.assertEqual(self.doc.UndoCount, undos)

    def testRenameLeavesOtherDocumentsBooking(self):
        """The property's document has a booking, so the rename joins it and its tid is 0: it
        closes no transaction, not the active document's booking in another document either."""
        other = App.newDocument("TestPropertyEditorGuiOther")
        try:
            other.UndoMode = 1
            self.doc.openTransaction("Task")
            self.obj.Label2 = "task"

            def activateOther():
                Gui.ActiveDocument = Gui.getDocument(other.Name)
                App.setActiveDocument(other.Name)
                other.openTransaction("Other")
                other.addObject("App::VarSet", "Other")
                activateOther.tid = other.getBookedTransactionID()

            self.renameThroughMenu("Width", "Wide", activateOther)
            self.assertEqual(App.ActiveDocument.Name, other.Name)
            self.assertEqual(self.obj.getPropertyByName("Wide"), 5)
            self.assertEqual(other.getBookedTransactionID(), activateOther.tid)
            other.commitTransaction()
            self.assertEqual(other.UndoNames, ["Other"])
        finally:
            Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
            App.setActiveDocument(self.doc.Name)
            App.closeDocument(other.Name)

    def testRenameWithoutBookingIsOwnStep(self):
        """With nothing booked, the rename is its own undo step "Rename property", and undo takes
        it back."""
        undos = self.doc.UndoCount
        self.renameThroughMenu("Width", "Wide")
        self.assertEqual(self.obj.getPropertyByName("Wide"), 5)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos + 1)
        self.assertEqual(self.doc.UndoNames[0], "Rename property")
        self.doc.undo()
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)
        self.assertNotIn("Wide", self.obj.PropertiesList)

    def testRefusedRenameKeepsExpression(self):
        """Width = Depth * 2 (an expression), inside a booked transaction: a rename to a name in use
        is refused and Width keeps its expression; the same name through the menu changes
        nothing and reports no error (a refused rename through the menu reports one)."""
        self.obj.addProperty("App::PropertyInteger", "Depth", "Variables")
        self.obj.Depth = 4
        self.obj.setExpression("Width", "Depth * 2")
        self.doc.recompute()
        self.doc.openTransaction("Task")
        self.obj.Label2 = "task"
        with self.assertRaises(Exception):
            self.obj.renameProperty("Width", "Depth")
        self.assertEqual(dict(self.obj.ExpressionEngine).get("Width"), "Depth * 2")

        undos = self.doc.UndoCount
        errors = self.reportedErrors()
        self.renameThroughMenu("Width", "Depth")
        self.assertEqual(self.reportedErrors(), errors + 1, "the refused rename reported no error")
        self.renameThroughMenu("Width", "Width")
        self.assertEqual(self.reportedErrors(), errors + 1, "the same name reported an error")
        self.assertEqual(dict(self.obj.ExpressionEngine).get("Width"), "Depth * 2")
        self.assertEqual(self.doc.UndoCount, undos)
        self.doc.abortTransaction()
        self.assertEqual(dict(self.obj.ExpressionEngine).get("Width"), "Depth * 2")
        self.doc.recompute()
        self.assertEqual(self.obj.Width, 8)

    def reportedErrors(self):
        """How many "already exists" errors the Report view shows."""
        pump(0.2)
        report = next(
            (
                w
                for w in Gui.getMainWindow().findChildren(QtWidgets.QTextEdit)
                if w.metaObject().className() == "Gui::DockWnd::ReportOutput"
            ),
            None,
        )
        self.assertIsNotNone(report, "no Report view")
        return report.toPlainText().count("already exists")

    # ops#231: Delete, Move and Add Property opened their transactions as Rename did before ops#178
    # (committing a task dialog's booking), and a value editor's "Edit" booking replaced one with
    # nothing written yet.

    def openTask(self):
        """A task dialog's transaction: booked, with a change to Depth (3 -> 9) in it."""
        self.obj.addProperty("App::PropertyInteger", "Depth", "Variables")
        self.obj.Depth = 3
        self.doc.openTransaction("Task")
        self.obj.Depth = 9
        return self.doc.getBookedTransactionID()

    def assertTaskAborts(self, tid, undos):
        """The task's transaction is still the booked one, and aborting it takes back Depth."""
        self.assertEqual(self.doc.getBookedTransactionID(), tid)
        self.assertEqual(self.doc.UndoNames[0], "Task")
        self.doc.abortTransaction()
        self.assertEqual(self.obj.Depth, 3)
        self.assertEqual(self.doc.UndoCount, undos)

    def deleteRow(self, name):
        """Deletes the VarSet's property name with the Delete key in the Data tab."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.obj.Name)
        pump(1.0)
        editor = self.dataEditor()
        index = findRow(editor.model(), QtCore.QModelIndex(), name)
        self.assertIsNotNone(index, "no %s row in the property view" % name)
        editor.setCurrentIndex(index)
        editor.selectionModel().select(
            index,
            QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
        )
        editor.setFocus()
        QtTest.QTest.keyClick(editor, QtCore.Qt.Key_Delete)
        pump()

    def testDeleteJoinsBookedTransaction(self):
        undos = self.doc.UndoCount
        tid = self.openTask()
        self.deleteRow("Width")
        self.assertNotIn("Width", self.obj.PropertiesList)
        self.assertTaskAborts(tid, undos)
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)

    def testDeleteWithoutBookingIsOwnStep(self):
        undos = self.doc.UndoCount
        self.deleteRow("Width")
        self.assertNotIn("Width", self.obj.PropertiesList)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos + 1)
        self.assertEqual(self.doc.UndoNames[0], "Remove property")
        self.doc.undo()
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)

    def moveThroughMenu(self, name, target, objects=None):
        """Moves the property name of objects (default: the VarSet) to the object target with Move
        Property."""

        def objectDialog():
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is None or widget.findChild(QtWidgets.QTreeWidget, "typeTree") is None:
                return None
            return widget

        def answer(dialog):
            tree = dialog.findChild(QtWidgets.QTreeWidget, "treeWidget")
            for _ in range(40):
                items = tree.findItems(target.Label, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive)
                if items:
                    break
                for row in range(tree.topLevelItemCount()):
                    tree.topLevelItem(row).setExpanded(True)
                pump(0.05)
            self.assertTrue(items, "no %s in the object dialog" % target.Label)
            items[0].setSelected(True)
            dialog.accept()

        self.throughMenu(name, "Move Property", objectDialog, answer, objects=objects)
        self.assertEqual(self.seen, ["QMenu", "QDialog"])

    def testMoveJoinsBookedTransaction(self):
        target = self.doc.addObject("App::VarSet", "Target")
        undos = self.doc.UndoCount
        tid = self.openTask()
        self.moveThroughMenu("Width", target)
        self.assertNotIn("Width", self.obj.PropertiesList)
        self.assertEqual(target.getPropertyByName("Width"), 5)
        self.assertTaskAborts(tid, undos)
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)
        self.assertNotIn("Width", target.PropertiesList)

    def testMoveAfterValueEditAborts(self):
        """Review of fork PR 213 (M1, ops#235): in a task's transaction, Width edited 5 -> 9 and
        then moved to another VarSet; aborting the task brings Width back to the VarSet with 5."""
        target = self.doc.addObject("App::VarSet", "Target")
        undos = self.doc.UndoCount
        tid = self.openTask()
        widget = self.openValueEditor("Width")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QtTest.QTest.keyClicks(widget, "9")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Return)
        pump(0.3)
        self.assertEqual(self.obj.Width, 9)
        self.moveThroughMenu("Width", target)
        self.assertEqual(target.getPropertyByName("Width"), 9)
        self.assertTaskAborts(tid, undos)
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)
        self.assertNotIn("Width", target.PropertiesList)

    def testMoveWithoutBookingIsOwnStep(self):
        target = self.doc.addObject("App::VarSet", "Target")
        undos = self.doc.UndoCount
        self.moveThroughMenu("Width", target)
        self.assertEqual(target.getPropertyByName("Width"), 5)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos + 1)
        self.assertEqual(self.doc.UndoNames[0], "Move Property")
        self.doc.undo()
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)
        self.assertNotIn("Width", target.PropertiesList)

    def addThroughMenu(self, name):
        """Adds the property name (the dialog's default type) to the VarSet with Add Property,
        then closes the dialog."""

        def addDialog():
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is None or widget.findChild(QtWidgets.QLineEdit, "lineEditName") is None:
                return None
            return widget

        def answer(dialog):
            QtTest.QTest.keyClicks(dialog.findChild(QtWidgets.QLineEdit, "lineEditName"), name)
            pump(0.2)
            dialog.accept()
            dialog.reject()

        self.throughMenu("Width", "Add Property", addDialog, answer)
        self.assertEqual(self.seen, ["QMenu", "QDialog"])

    def testAddJoinsBookedTransaction(self):
        undos = self.doc.UndoCount
        tid = self.openTask()
        props = self.obj.PropertiesList
        self.addThroughMenu("Height")
        self.assertIn("Height", self.obj.PropertiesList)
        self.assertTaskAborts(tid, undos)
        # also no property of a partial name typed (H, He, ...)
        self.assertEqual(self.obj.PropertiesList, props)

    def testFailedMoveLeavesNothingBooked(self):
        """Review of fork PR 213 (L1): two VarSets with Width, both selected, Move Property to a
        third: the second Width is refused at the target. The move's own transaction is aborted
        (the first Width comes back), and nothing stays booked."""
        other = self.doc.addObject("App::VarSet", "Second")
        other.addProperty("App::PropertyInteger", "Width", "Variables")
        other.Width = 4
        target = self.doc.addObject("App::VarSet", "Target")
        undos = self.doc.UndoCount
        self.moveThroughMenu("Width", target, objects=[self.obj, other])
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)
        self.assertEqual(other.getPropertyByName("Width"), 4)
        self.assertNotIn("Width", target.PropertiesList)
        self.assertEqual(self.doc.UndoCount, undos)

    def testAddWithoutBookingIsOwnStep(self):
        undos = self.doc.UndoCount
        self.addThroughMenu("Height")
        self.assertIn("Height", self.obj.PropertiesList)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos + 1)
        self.assertEqual(self.doc.UndoNames[0], "Add property")
        self.doc.undo()
        self.assertNotIn("Height", self.obj.PropertiesList)

    def testValueEditJoinsBookingWithoutChanges(self):
        """L5: a task's transaction booked, nothing written in it yet: a value edit joins it, and
        aborting it takes the edit back."""
        undos = self.doc.UndoCount
        self.doc.openTransaction("Task")
        tid = self.doc.getBookedTransactionID()
        widget = self.openValueEditor("Width")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QtTest.QTest.keyClicks(widget, "9")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Return)
        pump(0.3)
        self.assertEqual(self.obj.Width, 9)
        self.assertEqual(self.doc.getBookedTransactionID(), tid)
        self.doc.abortTransaction()
        self.assertEqual(self.obj.Width, 5)
        self.assertEqual(self.doc.UndoCount, undos)

    def testEscapeInBookingKeepsIt(self):
        """Review of fork PR 213 (S9): a task's transaction with a change in it; a value typed and
        Esc: the value is back, and the task's transaction is still booked and aborts."""
        undos = self.doc.UndoCount
        tid = self.openTask()
        widget = self.openValueEditor("Width")
        self.typeThenEscape(widget, "9")
        self.assertEqual(self.obj.Width, 5)
        self.assertTaskAborts(tid, undos)

    def testValueEditLeavesActiveDocumentsBooking(self):
        """Review of fork PR 213 (L3'): "Edit" books in the active document. With a booking there
        and nothing written yet, an edit of an object in another document doesn't replace it."""
        other = App.newDocument("TestPropertyEditorGuiOther")
        try:
            other.UndoMode = 1
            varSet = other.addObject("App::VarSet", "Other")
            varSet.addProperty("App::PropertyInteger", "Width", "Variables")
            varSet.Width = 2
            Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
            App.setActiveDocument(self.doc.Name)
            self.doc.openTransaction("Task")
            tid = self.doc.getBookedTransactionID()
            widget = self.openValueEditor("Width", objects=[varSet])
            self.assertEqual(App.ActiveDocument.Name, self.doc.Name)
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
            QtTest.QTest.keyClicks(widget, "7")
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Return)
            pump(0.3)
            self.assertEqual(varSet.Width, 7)
            self.assertEqual(self.doc.getBookedTransactionID(), tid)
            self.doc.abortTransaction()
        finally:
            Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
            App.setActiveDocument(self.doc.Name)
            App.closeDocument(other.Name)

    # Review follow-ups of fork PR 213 (ops#231, in ops#235).

    def otherDocument(self):
        other = App.newDocument("TestPropertyEditorGuiOther")
        other.UndoMode = 1
        return other

    def testEditorCommitsInItsDocument(self):
        """N1: "Edit" booked in the VarSet's document, and the editor closed with Return while
        another document is active: the booking is committed where it was made, not left open
        (a task opened later there would take it as its own). Making another document active
        closes the editor already; Esc after that has nothing left to revert."""
        other = self.otherDocument()
        try:
            App.setActiveDocument(self.doc.Name)
            undos = self.doc.UndoCount
            widget = self.openValueEditor("Width")
            self.assertNotEqual(self.doc.getBookedTransactionID(), 0)
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
            QtTest.QTest.keyClicks(widget, "9")
            App.setActiveDocument(other.Name)
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Return)
            pump(0.3)
            self.assertEqual(self.obj.Width, 9)
            self.assertEqual(self.doc.getBookedTransactionID(), 0)
            self.assertEqual(self.doc.UndoCount, undos + 1)
            self.assertTrue(self.doc.UndoNames[0].startswith("Edit"), self.doc.UndoNames)
        finally:
            App.setActiveDocument(self.doc.Name)
            App.closeDocument(other.Name)

    def addWithFailedCreate(self, name, retryType=None):
        """Add Property from the menu: name typed, then a type that can't be made (an abstract
        one: the dialog shows an error), then retryType and OK if given; then the dialog closes."""

        def addDialog():
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is None or widget.findChild(QtWidgets.QLineEdit, "lineEditName") is None:
                return None
            return widget

        def errorBox():
            widget = QtWidgets.QApplication.activeModalWidget()
            return widget if isinstance(widget, QtWidgets.QMessageBox) else None

        boxes = []
        done = []

        def answerBoxes():
            box = errorBox()
            if box is not None:
                boxes.append(box.text())
                box.button(QtWidgets.QMessageBox.Ok).click()
            if len(boxes) < 10 and not done:
                QtCore.QTimer.singleShot(50, answerBoxes)

        def answer(dialog):
            QtTest.QTest.keyClicks(dialog.findChild(QtWidgets.QLineEdit, "lineEditName"), name)
            pump(0.2)
            QtCore.QTimer.singleShot(50, answerBoxes)
            typeBox = dialog.findChild(QtWidgets.QComboBox, "comboBoxType")
            typeBox.setCurrentText("App::PropertyLinkBase")
            pump(0.2)
            if retryType:
                typeBox.setCurrentText(retryType)
                pump(0.2)
                dialog.accept()
            dialog.reject()
            done.append(True)

        # the error is reported as well; the notification area's box can deadlock off screen
        # (build notes, ops#121)
        params = App.ParamGet("User parameter:BaseApp/Preferences/NotificationArea")
        enabled = params.GetBool("NotificationAreaEnabled", True)
        params.SetBool("NotificationAreaEnabled", False)
        try:
            self.throughMenu("Width", "Add Property", addDialog, answer)
        finally:
            params.SetBool("NotificationAreaEnabled", enabled)
        self.assertEqual(self.seen, ["QMenu", "QDialog"])
        self.assertTrue(any("Failed to add property" in text for text in boxes), boxes)

    def testFailedAddThenCancelLeavesNothingBooked(self):
        """N2: a property that couldn't be created, then Cancel: the dialog's booking is aborted."""
        undos = self.doc.UndoCount
        props = self.obj.PropertiesList
        self.addWithFailedCreate("Height")
        self.assertEqual(self.obj.PropertiesList, props)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos)

    def testFailedAddThenRetryIsOneStep(self):
        """L2: a property that couldn't be created, then another type and OK: one committed step."""
        undos = self.doc.UndoCount
        self.addWithFailedCreate("Height", "App::PropertyInteger")
        self.assertIn("Height", self.obj.PropertiesList)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos + 1)
        self.assertEqual(self.doc.UndoNames[0], "Add property")
        self.doc.undo()
        self.assertNotIn("Height", self.obj.PropertiesList)

    def testAddFromVarSetKeepsEditorBookingApart(self):
        """S3: a value editor open (its "Edit" booking), and Add Property opened from the VarSet
        (double click): the add doesn't join the editor's booking, and Esc in the editor doesn't
        take the property away."""
        undos = self.doc.UndoCount
        widget = self.openValueEditor("Width")
        self.assertNotEqual(self.doc.getBookedTransactionID(), 0)
        Gui.getDocument(self.doc.Name).getObject(self.obj.Name).doubleClicked()
        dialog = None
        for _ in range(40):
            pump(0.05)
            dialog = next(
                (
                    w
                    for w in QtWidgets.QApplication.topLevelWidgets()
                    if w.metaObject().className() == "Gui::Dialog::DlgAddProperty"
                    and w.isVisible()
                ),
                None,
            )
            if dialog:
                break
        self.assertIsNotNone(dialog, "no Add Property dialog")
        QtTest.QTest.keyClicks(dialog.findChild(QtWidgets.QLineEdit, "lineEditName"), "Height")
        pump(0.2)
        dialog.accept()
        dialog.reject()
        pump(0.3)
        self.assertIn("Height", self.obj.PropertiesList)
        try:
            alive = widget.isVisible()
        except RuntimeError:
            alive = False
        if alive:
            QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Escape)
            pump(0.3)
        self.assertIn("Height", self.obj.PropertiesList)
        self.assertEqual(self.obj.Width, 5)
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertIn("Add property", self.doc.UndoNames)
        self.assertEqual(self.doc.UndoCount - undos, self.doc.UndoNames.index("Add property") + 1)

    def testValueEditFailedMoveThenTaskCancel(self):
        """ops#235: in a task's transaction, Width edited 5 -> 9, then a Move of Width from two
        VarSets that the target refuses for the second; the task's Cancel brings back every value
        and leaves the target as it was."""
        other = self.doc.addObject("App::VarSet", "Second")
        other.addProperty("App::PropertyInteger", "Width", "Variables")
        other.Width = 4
        target = self.doc.addObject("App::VarSet", "Target")
        undos = self.doc.UndoCount
        tid = self.openTask()
        widget = self.openValueEditor("Width")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QtTest.QTest.keyClicks(widget, "9")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Return)
        pump(0.3)
        self.assertEqual(self.obj.Width, 9)
        self.moveThroughMenu("Width", target, objects=[self.obj, other])
        self.assertTaskAborts(tid, undos)
        self.assertEqual(self.obj.getPropertyByName("Width"), 5)
        self.assertEqual(other.getPropertyByName("Width"), 4)
        self.assertNotIn("Width", target.PropertiesList)

    # ops#146 (upstream issue 30992): Esc while editing a value reverted nothing. A number's editor
    # writes the property as it is typed, and Esc then committed the "Edit" transaction.

    def openValueEditor(self, *path, objects=None, leaf=None):
        """Opens the editor of the value at path (row names, e.g. "Offset", "x") with F2, as a
        user does, with objects (default: the VarSet) selected; returns the editor widget. A
        one-name path is a leaf row unless leaf is False (a Placement's own row)."""
        Gui.Selection.clearSelection()
        for obj in objects or [self.obj]:
            Gui.Selection.addSelection(obj.Document.Name, obj.Name)
        pump(1.0)
        editor = self.dataEditor()
        model = editor.model()
        index = findRow(
            model, QtCore.QModelIndex(), path[0], leaf=len(path) == 1 if leaf is None else leaf
        )
        if len(path) > 1:
            self.assertIsNotNone(index, "no %s row in the property view" % path[0])
            editor.expand(index)
            pump(0.2)
            index = next(
                model.index(row, 0, index)
                for row in range(model.rowCount(index))
                if str(model.data(model.index(row, 0, index))) == path[1]
            )
        self.assertIsNotNone(index, "no %s row in the property view" % (path,))
        value = index.siblingAtColumn(1)
        editor.setCurrentIndex(value)
        editor.setFocus()
        key = QtCore.Qt.Key_Return if sys.platform == "darwin" else QtCore.Qt.Key_F2
        QtTest.QTest.keyClick(editor, key)
        pump(0.3)
        widget = editor.indexWidget(value)
        self.assertIsNotNone(widget, "no editor for %s" % (path,))
        return widget

    def openOuter(self):
        """A transaction someone else opened and already wrote in: the editor books none of its
        own (nor for one only booked, with nothing written yet, since ops#231)."""
        self.doc.openTransaction("Outer")
        self.obj.Label2 = self.obj.Label2 + "."

    def typeThenEscape(self, widget, text):
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QtTest.QTest.keyClicks(widget, text)
        pump(0.2)
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Escape)
        pump(0.3)

    def testEscapeRevertsValue(self):
        self.obj.addProperty("App::PropertyFloat", "Ratio", "Variables")
        self.obj.Ratio = 1.5
        self.obj.addProperty("App::PropertyLength", "Depth", "Variables")
        self.obj.Depth = 10
        self.obj.addProperty("App::PropertyAngle", "Tilt", "Variables")
        self.obj.Tilt = 30
        self.obj.addProperty("App::PropertyString", "Finish", "Variables")
        self.obj.Finish = "matte"
        self.obj.addProperty("App::PropertyVector", "Offset", "Variables")
        self.obj.Offset = App.Vector(1, 2, 3)
        cases = (
            (("Width",), "9", lambda: self.obj.Width, 5),
            (("Ratio",), "7.25", lambda: self.obj.Ratio, 1.5),
            (("Depth",), "42", lambda: self.obj.Depth.Value, 10.0),
            (("Tilt",), "45", lambda: self.obj.Tilt.Value, 30.0),
            (("Finish",), "gloss", lambda: self.obj.Finish, "matte"),
            (("Offset", "x"), "8", lambda: self.obj.Offset.x, 1.0),
        )
        for path, text, read, before in cases:
            for outer in (False, True):
                with self.subTest(path=path, outer=outer):
                    if outer:
                        self.openOuter()
                    undos = self.doc.UndoCount
                    widget = self.openValueEditor(*path)
                    self.typeThenEscape(widget, text)
                    self.assertEqual(read(), before)
                    if outer:
                        self.doc.commitTransaction()
                    else:
                        self.assertEqual(self.doc.getBookedTransactionID(), 0)
                        self.assertEqual(self.doc.UndoCount, undos)

    def testReturnStillCommits(self):
        undos = self.doc.UndoCount
        widget = self.openValueEditor("Width")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QtTest.QTest.keyClicks(widget, "9")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Return)
        pump(0.3)
        self.assertEqual(self.obj.Width, 9)
        self.assertEqual(self.doc.UndoCount, undos + 1)

    def testEscapeKeepsDialogValue(self):
        """Review M2: an editor that writes on a dialog's OK (a color's button) keeps the value
        after Esc, and its Edit transaction is committed. Only editors that write as they are
        typed revert."""
        self.obj.addProperty("App::PropertyColor", "Tint", "Variables")
        self.obj.Tint = (0.0, 0.0, 1.0)
        undos = self.doc.UndoCount
        widget = self.openValueEditor("Tint")
        # As the color dialog's OK does (ColorButton::onColorChosen)
        widget.setProperty("color", QtGui.QColor(255, 0, 0))
        QtCore.QMetaObject.invokeMethod(widget, "changed")
        pump(0.2)
        self.assertEqual(tuple(self.obj.Tint)[:3], (1.0, 0.0, 0.0))
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Escape)
        pump(0.3)
        self.assertEqual(tuple(self.obj.Tint)[:3], (1.0, 0.0, 0.0), "Esc undid the dialog's OK")
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos + 1)

    def testEscapeWithSeveralObjects(self):
        """Review L3: without a transaction of its own to abort (here inside another one), Esc
        writes the old value back to every selected object only when they all had it. Two
        VarSets of the same Width get it back; of different Widths, neither gets the first one's."""
        other = self.doc.addObject("App::VarSet", "Other")
        other.addProperty("App::PropertyInteger", "Width", "Variables")
        for otherWidth, after in ((5, (5, 5)), (6, (9, 9))):
            with self.subTest(otherWidth=otherWidth):
                self.obj.Width = 5
                other.Width = otherWidth
                self.openOuter()
                widget = self.openValueEditor("Width", objects=[self.obj, other])
                QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
                QtTest.QTest.keyClicks(widget, "9")
                pump(0.2)
                self.assertEqual((self.obj.Width, other.Width), (9, 9), "typing wrote nothing")
                QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Escape)
                pump(0.3)
                self.assertEqual((self.obj.Width, other.Width), after)
                self.doc.commitTransaction()

    def testEscapeKeepsFormulaExpression(self):
        """Review round 2 (N2): '=' typed in a number's editor opens the f(x) dialog, whose OK
        sets the row's expression inside the editor's Edit transaction. Esc then keeps the
        expression (it aborted the transaction, so the expression was gone)."""
        widget = self.openValueEditor("Width")
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_A, QtCore.Qt.ControlModifier)
        QtTest.QTest.keyClicks(widget, "7")
        pump(0.2)
        # As the dialog's OK does (ExpressionBinding::setExpression), in the editor's transaction
        self.obj.setExpression("Width", "2 + 3")
        pump(0.2)
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Escape)
        pump(0.3)
        self.assertIn(("Width", "2 + 3"), self.obj.ExpressionEngine, "Esc removed the expression")
        self.assertEqual(self.doc.getBookedTransactionID(), 0)

    def testEscapeRevertsTypedList(self):
        """Review round 2 (L-a): a list row (StringList) writes as it is typed, in a line edit
        inside its editor; Esc reverts it."""
        self.obj.addProperty("App::PropertyStringList", "Tags", "Variables")
        self.obj.Tags = ["a", "b"]
        undos = self.doc.UndoCount
        widget = self.openValueEditor("Tags")
        lineEdit = widget if isinstance(widget, QtWidgets.QLineEdit) else widget.findChild(
            QtWidgets.QLineEdit
        )
        self.assertIsNotNone(lineEdit, "no line edit in the list's editor")
        lineEdit.setFocus()
        # The line edit shows "[a<newline>b]" and writes while the brackets are kept
        QtTest.QTest.keyClick(lineEdit, QtCore.Qt.Key_End)
        QtTest.QTest.keyClick(lineEdit, QtCore.Qt.Key_Left)
        QtTest.QTest.keyClicks(lineEdit, "c")
        pump(0.2)
        self.assertNotEqual(self.obj.Tags, ["a", "b"], "typing wrote nothing")
        QtTest.QTest.keyClick(lineEdit, QtCore.Qt.Key_Escape)
        pump(0.3)
        self.assertEqual(self.obj.Tags, ["a", "b"])
        self.assertEqual(self.doc.getBookedTransactionID(), 0)
        self.assertEqual(self.doc.UndoCount, undos)

    def testEscapeKeepsDialogValueAfterArrowKey(self):
        """Review round 3 (L-g): cursor keys in a File row's line edit aren't typing. The file
        its dialog then picks stays after Esc."""
        self.obj.addProperty("App::PropertyFile", "Source", "Variables")
        self.obj.Source = "C:/old.txt"
        widget = self.openValueEditor("Source")
        lineEdit = widget.findChild(QtWidgets.QLineEdit)
        self.assertIsNotNone(lineEdit, "no line edit in the file's editor")
        for key in (QtCore.Qt.Key_End, QtCore.Qt.Key_Left, QtCore.Qt.Key_Home):
            QtTest.QTest.keyClick(lineEdit, key)
        # As the file dialog's OK does (FileChooser::chooseFile)
        widget.setProperty("fileName", "C:/new.txt")
        QtCore.QMetaObject.invokeMethod(
            widget, "fileNameSelected", QtCore.Q_ARG(str, "C:/new.txt")
        )
        pump(0.2)
        self.assertEqual(self.obj.Source, "C:/new.txt", "the pick wrote nothing")
        QtTest.QTest.keyClick(lineEdit, QtCore.Qt.Key_Escape)
        pump(0.3)
        self.assertEqual(self.obj.Source, "C:/new.txt", "Esc undid the dialog's pick")

    def testEscapeRevertsSteppedSpinBox(self):
        """Review round 3 (L-k): the up/down keys, page keys and the wheel step a number row's
        spin box, which writes as it goes: they count as typing, and Esc reverts the value."""

        def wheel(widget):
            center = QtCore.QPointF(widget.rect().center())
            event = QtGui.QWheelEvent(
                center,
                QtCore.QPointF(widget.mapToGlobal(widget.rect().center())),
                QtCore.QPoint(),
                QtCore.QPoint(0, 120),
                QtCore.Qt.NoButton,
                QtCore.Qt.NoModifier,
                QtCore.Qt.NoScrollPhase,
                False,
            )
            QtWidgets.QApplication.sendEvent(widget, event)

        steps = (
            ("up", lambda w: QtTest.QTest.keyClick(w, QtCore.Qt.Key_Up)),
            ("down", lambda w: QtTest.QTest.keyClick(w, QtCore.Qt.Key_Down)),
            ("page up", lambda w: QtTest.QTest.keyClick(w, QtCore.Qt.Key_PageUp)),
            ("wheel", wheel),
        )
        for name, step in steps:
            with self.subTest(step=name):
                undos = self.doc.UndoCount
                widget = self.openValueEditor("Width")
                step(widget)
                pump(0.2)
                self.assertNotEqual(self.obj.Width, 5, "the step wrote nothing")
                QtTest.QTest.keyClick(widget, QtCore.Qt.Key_Escape)
                pump(0.3)
                self.assertEqual(self.obj.Width, 5)
                self.assertEqual(self.doc.getBookedTransactionID(), 0)
                self.assertEqual(self.doc.UndoCount, undos)

    def testEscapeKeepsEnumerationPick(self):
        """Review round 3 (L-j), the documented rule: an Enumeration row's combo box writes on
        every pick, and the arrow keys pick (QComboBox::activated), so Esc keeps the picked item,
        as it keeps a color or a file from a dialog."""
        self.obj.addProperty("App::PropertyEnumeration", "Mode", "Variables")
        self.obj.Mode = ["Thin", "Medium", "Thick"]
        self.obj.Mode = "Thin"
        widget = self.openValueEditor("Mode")
        combo = widget if isinstance(widget, QtWidgets.QComboBox) else widget.findChild(
            QtWidgets.QComboBox
        )
        self.assertIsNotNone(combo, "no combo box in the enumeration's editor")
        QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Down)
        pump(0.2)
        self.assertEqual(self.obj.Mode, "Medium", "the arrow key picked nothing")
        QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Escape)
        pump(0.3)
        self.assertEqual(self.obj.Mode, "Medium", "Esc undid the pick")
