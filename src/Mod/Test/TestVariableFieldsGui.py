# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""`#name` typed into a numeric field, as Onshape takes it (FreeCAD-CH, ops#640).

- V23: `#Width` typed into a bound field (no `=`, no f(x) dialog) binds the field to the variable
  when the edit ends (Enter or leaving the field): before, today's value was stored, or
  `#Width * 1 mm`.
- Rank 55 (hands-on F10): an unknown `#name` keeps the field red, as typed, and nothing is
  committed; the `#` list offers "New variable...", which opens the Add dialog with the name and
  the field's value.
- Hands-on D-1: a variable made that way while a dialog's transaction is open stays when the
  dialog is cancelled, as its own undo step; when the dialog is accepted, it is in the dialog's.
- Rank 15: Std_AddVariable, the Variable tool, opens the same dialog.
- Rank 56: `3/4 in` typed is three quarters of an inch.

The model is a Part Box and a VarSet "Variables" with Width = 20 mm, built here; the fields are
spin boxes bound to Box.Length as a task panel binds them.
"""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest
import shiboken6


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, seconds=5.0):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    value = condition()
    while not value and time.time() < end:
        app.processEvents()
        time.sleep(0.01)
        value = condition()
    return value


def expressionText(obj, prop):
    for path, text in obj.ExpressionEngine:
        if path == prop:
            return text
    return None


def taskOkButton():
    """The open task dialog's OK button, through live wrappers only."""
    for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
        if not shiboken6.isValid(box):
            continue
        button = box.button(QtWidgets.QDialogButtonBox.Ok)
        if button is None or not button.isVisible():
            continue
        parent = box.parentWidget()
        while parent is not None:
            if parent.metaObject().className() == "Gui::TaskView::TaskView":
                return button
            parent = parent.parentWidget()
    return None


def addDialog():
    for widget in QtWidgets.QApplication.topLevelWidgets():
        if widget.objectName() == "addVariableDialog" and widget.isVisible():
            return widget
    return None


class TestVariableFieldsGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestVariableFieldsGui")
        self.doc.UndoMode = 1
        self.varSet = self.doc.addObject("App::VarSet", "Variables")
        self.varSet.addProperty("App::PropertyDistance", "Width")
        self.varSet.Width = 20
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.Length = 10
        self.doc.recompute()
        self.widgets = []

    def tearDown(self):
        dialog = addDialog()
        if dialog:
            dialog.reject()
        for widget in self.widgets:
            # a `#` list left open must not leak into the next test
            for completer in widget.findChildren(QtWidgets.QCompleter):
                if completer.popup():
                    completer.popup().hide()
            widget.deleteLater()
        pump(0.2)
        App.closeDocument(self.doc.Name)

    def field(self, prop="Length"):
        """A QuantitySpinBox bound to Box.Length (or `prop`), in mm, focused."""
        spin = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        self.widgets.append(spin)
        spin.setProperty("unit", "mm")
        # The value a task panel would load from Box.Length (binding loads none)
        spin.setProperty("rawValue", 10.0)
        binding = Gui.ExpressionBinding(spin)
        binding.bind(self.box, prop)
        self.binding = binding
        spin.show()
        spin.activateWindow()
        spin.setFocus()
        pump(0.1)
        return spin

    def type(self, spin, text):
        edit = spin.findChild(QtWidgets.QLineEdit)
        edit.selectAll()
        QTest.keyClicks(spin, text)
        pump(0.1)
        return edit

    def isRed(self, edit):
        return edit.palette().color(QtGui.QPalette.Active, QtGui.QPalette.Text) == QtGui.QColor(
            QtCore.Qt.red
        )

    def test_hash_name_binds_on_enter(self):
        spin = self.field()
        edit = self.type(spin, "#Width")
        self.assertFalse(self.isRed(edit))
        QTest.keyClick(spin, QtCore.Qt.Key_Return)
        pump()
        self.assertEqual(expressionText(self.box, "Length"), "Variables.Width")
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 20.0, places=9)
        # Bound: shown as the value, read-only, as after the f(x) dialog
        self.assertTrue(edit.isReadOnly())
        # and it follows the variable
        self.varSet.Width = 35
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 35.0, places=9)

    def test_hash_expression_binds_on_leaving_the_field(self):
        spin = self.field()
        self.type(spin, "#Width * 2")
        spin.clearFocus()
        pump()
        self.assertEqual(expressionText(self.box, "Length"), "Variables.Width * 2")
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 40.0, places=9)

    def test_a_value_out_of_range_still_types(self):
        """The field's range doesn't refuse the key that completes `#Width` (Width = 20 mm)."""
        spin = self.field()
        spin.setProperty("maximum", 5.0)
        edit = self.type(spin, "#Width")
        self.assertEqual(edit.text(), "#Width")

    def test_unknown_name_stays_red_and_uncommitted(self):
        spin = self.field()
        edit = self.type(spin, "#Depth")
        self.assertTrue(self.isRed(edit))
        self.assertTrue(spin.property("unresolvedVariable"))
        QTest.keyClick(spin, QtCore.Qt.Key_Return)
        spin.clearFocus()
        pump()
        self.assertIsNone(expressionText(self.box, "Length"))
        self.assertEqual(edit.text(), "#Depth")
        self.assertTrue(self.isRed(edit))
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 10.0, places=9)
        # Fixed by typing a known name: no longer red
        self.type(spin, "#Width")
        self.assertFalse(self.isRed(edit))
        self.assertFalse(spin.property("unresolvedVariable"))

    def test_new_variable_offered_and_made(self):
        spin = self.field()
        self.type(spin, "#Depth")
        completer = spin.findChild(QtWidgets.QCompleter)
        self.assertIsNotNone(completer, "no # completion on the field")
        model = completer.completionModel()
        rows = [model.data(model.index(row, 0)) for row in range(model.rowCount())]
        self.assertTrue(rows, "the # list is empty")
        self.assertEqual(rows[-1], "New variable...")
        completer.activated[QtCore.QModelIndex].emit(model.index(len(rows) - 1, 0))
        dialog = waitFor(addDialog)
        self.assertIsNotNone(dialog, "New variable... opened no Add dialog")
        self.assertEqual(dialog.findChild(QtWidgets.QLineEdit, "name").text(), "Depth")
        value = dialog.findChild(QtWidgets.QLineEdit, "value").text()
        self.assertAlmostEqual(App.Units.Quantity(value).Value, 10.0, places=6)
        dialog.findChild(QtWidgets.QDialogButtonBox).button(
            QtWidgets.QDialogButtonBox.Ok
        ).click()
        pump()
        self.assertIsNone(addDialog())
        self.assertIn("Depth", self.varSet.PropertiesList)
        self.assertAlmostEqual(self.varSet.Depth.Value, 10.0, places=6)
        # Back in the field, the name resolves; Enter binds it
        spin.activateWindow()
        spin.setFocus()
        self.type(spin, "#Depth")
        QTest.keyClick(spin, QtCore.Qt.Key_Return)
        pump()
        self.assertEqual(expressionText(self.box, "Length"), "Variables.Depth")
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 10.0, places=6)

    def makeDepthFromTheField(self):
        """`#Depth` typed into the field, then "New variable..." and OK in the Add dialog."""
        spin = self.field()
        self.type(spin, "#Depth")
        completer = spin.findChild(QtWidgets.QCompleter)
        self.assertIsNotNone(completer, "no # completion on the field")
        model = completer.completionModel()
        rows = [model.data(model.index(row, 0)) for row in range(model.rowCount())]
        self.assertTrue(rows, "the # list is empty")
        self.assertEqual(rows[-1], "New variable...")
        completer.activated[QtCore.QModelIndex].emit(model.index(len(rows) - 1, 0))
        dialog = waitFor(addDialog)
        self.assertIsNotNone(dialog, "New variable... opened no Add dialog")
        dialog.findChild(QtWidgets.QDialogButtonBox).button(
            QtWidgets.QDialogButtonBox.Ok
        ).click()
        pump()
        self.assertIsNone(addDialog())
        self.assertIn("Depth", self.varSet.PropertiesList)

    def test_new_variable_stays_when_the_dialog_is_cancelled(self):
        """Hands-on D-1: the feature dialog's transaction (booked, with its new feature in it)
        takes the variable; cancelling the dialog aborts it, and the variable is made again as
        its own undo step, "Add Depth", with the field's value."""
        undoCount = self.doc.UndoCount
        self.doc.openTransaction("Insert feature")
        self.assertNotEqual(self.doc.getBookedTransactionID(), 0)
        self.doc.addObject("Part::Box", "Feature")
        self.makeDepthFromTheField()
        self.doc.abortTransaction()
        self.assertIsNone(self.doc.getObject("Feature"))
        self.assertTrue(
            waitFor(lambda: "Depth" in self.varSet.PropertiesList, 2.0),
            "the variable went with the cancelled dialog",
        )
        self.assertAlmostEqual(self.varSet.Depth.Value, 10.0, places=6)
        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.assertEqual(self.doc.UndoNames[0], "Add Depth")
        # One set: the variable went back into "Variables", no new set
        self.assertEqual([o.Name for o in self.doc.findObjects("App::VarSet")], ["Variables"])

    def test_new_variable_is_in_the_accepted_dialogs_step(self):
        """Hands-on D-1's other half: accepted, the dialog's step holds the variable, and
        nothing is made again later."""
        undoCount = self.doc.UndoCount
        self.doc.openTransaction("Insert feature")
        self.doc.addObject("Part::Box", "Feature")
        self.makeDepthFromTheField()
        self.doc.commitTransaction()
        pump()
        self.assertIsNotNone(self.doc.getObject("Feature"))
        self.assertIn("Depth", self.varSet.PropertiesList)
        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.assertEqual(self.doc.UndoNames[0], "Insert feature")
        # A later cancelled dialog doesn't bring a record back
        self.doc.openTransaction("Other")
        self.doc.addObject("Part::Box", "Other")
        self.doc.abortTransaction()
        pump()
        self.assertEqual(self.doc.UndoCount, undoCount + 1)

    def test_unit_named_variable_binds(self):
        """Hands-on D-2 (rank 54): a variable named t (a unit name) works as `#t`: the field
        isn't red, Enter binds it, and the value follows; "New variable..." is offered for `#h`."""
        self.varSet.addProperty("App::PropertyDistance", "t")
        self.varSet.t = "0.75 in"
        self.doc.recompute()
        spin = self.field()
        edit = self.type(spin, "#t")
        self.assertFalse(self.isRed(edit))
        QTest.keyClick(spin, QtCore.Qt.Key_Return)
        pump()
        self.assertEqual(expressionText(self.box, "Length"), "Variables.t")
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 19.05, places=9)
        # another property: Length is bound now, and its field read-only
        other = self.field("Width")
        self.type(other, "#h")
        completer = other.findChild(QtWidgets.QCompleter)
        self.assertIsNotNone(completer)
        model = completer.completionModel()
        rows = [model.data(model.index(row, 0)) for row in range(model.rowCount())]
        self.assertIn("New variable...", rows)

    def test_known_name_offers_no_new_variable(self):
        spin = self.field()
        self.type(spin, "#Width")
        completer = spin.findChild(QtWidgets.QCompleter)
        self.assertIsNotNone(completer)
        model = completer.completionModel()
        rows = [model.data(model.index(row, 0)) for row in range(model.rowCount())]
        self.assertNotIn("New variable...", rows)
        self.assertTrue(any(str(row).startswith("Width") for row in rows), rows)

    def test_variable_tool_opens_the_add_dialog(self):
        """Rank 15: the Variable tool (Std_AddVariable) shows the panel and its Add dialog."""
        self.assertIsNotNone(Gui.Command.get("Std_AddVariable"))
        Gui.runCommand("Std_AddVariable", 0)
        dialog = waitFor(addDialog)
        self.assertIsNotNone(dialog)
        self.assertEqual(dialog.findChild(QtWidgets.QLineEdit, "name").text(), "")
        dialog.reject()
        pump()

    def test_unresolved_name_blocks_the_dialogs_check(self):
        """Hands-on F10, area B's half (TaskView.cpp): while a field of the open task dialog shows
        an unresolved `#name`, the dialog's OK is disabled and Enter in the 3D view doesn't
        accept it; once the name resolves, OK is enabled again."""
        test = self

        class Panel:
            def __init__(self):
                self.accepted = False
                self.form = QtWidgets.QWidget()
                layout = QtWidgets.QVBoxLayout(self.form)
                self.spin = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
                layout.addWidget(self.spin)
                self.spin.setProperty("unit", "mm")
                self.spin.setProperty("rawValue", 10.0)
                test.binding = Gui.ExpressionBinding(self.spin)
                test.binding.bind(test.box, "Length")

            def accept(self):
                self.accepted = True
                Gui.Control.closeDialog()
                return True

            def reject(self):
                Gui.Control.closeDialog()
                return True

        panel = Panel()
        Gui.Control.showDialog(panel)
        try:
            pump()
            ok = waitFor(taskOkButton)
            self.assertIsNotNone(ok, "no OK button in the task dialog")
            self.assertTrue(ok.isEnabled())
            spin = panel.spin
            spin.activateWindow()
            spin.setFocus()
            pump(0.1)
            self.type(spin, "#Depth")
            self.assertTrue(spin.property("unresolvedVariable"))
            self.assertTrue(
                waitFor(lambda: not ok.isEnabled(), 2.0), "OK stays enabled on an unresolved #name"
            )
            viewport = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
            viewport.setFocus(QtCore.Qt.FocusReason.OtherFocusReason)
            pump(0.1)
            QTest.keyClick(viewport, QtCore.Qt.Key_Return)
            pump()
            self.assertFalse(panel.accepted, "Enter in the 3D view accepted the dialog")
            self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")
            self.assertIsNone(expressionText(self.box, "Length"))
            spin.setFocus()
            pump(0.1)
            self.type(spin, "#Width")
            self.assertFalse(spin.property("unresolvedVariable"))
            self.assertTrue(
                waitFor(lambda: ok.isEnabled(), 2.0), "OK stays disabled once the name resolves"
            )
        finally:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
            pump()

    def test_three_quarters_of_an_inch_typed(self):
        """Rank 56: `3/4 in` typed into a field is 19.05 mm."""
        spin = self.field()
        self.type(spin, "3/4 in")
        QTest.keyClick(spin, QtCore.Qt.Key_Return)
        pump()
        self.assertAlmostEqual(spin.property("rawValue"), 19.05, places=6)
        self.assertIsNone(expressionText(self.box, "Length"))


if __name__ == "__main__":
    unittest.main()
