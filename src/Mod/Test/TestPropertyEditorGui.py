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

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtGui, QtWidgets


def pump(seconds=0.5):
    """Processes events for a while: the property view fills on a timer."""
    end = time.monotonic() + seconds
    while True:
        QtWidgets.QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def findRow(model, parent, name):
    for row in range(model.rowCount(parent)):
        index = model.index(row, 0, parent)
        # a group can have a property's name: take a leaf
        if str(model.data(index)) == name and model.rowCount(index) == 0:
            return index
        found = findRow(model, index, name)
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
