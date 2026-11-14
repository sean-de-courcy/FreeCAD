# SPDX-License-Identifier: LGPL-2.1-or-later

"""The Variables panel (FreeCAD-CH, ops#152, notes/variables-design.md section 3.6).

A dock window lists the active document's VarSet variables and sheet aliases under one header row
per source. Editing a row's Name renames the variable and editing its Expression sets the value or
the expression, each as one undo step; Add and Delete work from its toolbar. G1-G7, G9, G17 and G18
of the design note; since ops#317 PR B the Type and Description columns and the panel's own Add
dialog (G-1 to G-3 of notes/variables-studio.md). Each test builds its own document."""

import json
import math
import os
import shutil
import tempfile
import time
import unittest
from unittest import mock

import shiboken6

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

# VariablesModel's roles and columns (src/Gui/VariablesView.h)
KindRole = QtCore.Qt.UserRole + 1
VariableRole = QtCore.Qt.UserRole + 4
EditTextRole = QtCore.Qt.UserRole + 6
NAME, TYPE, EXPRESSION, VALUE, DESCRIPTION, SOURCE = range(6)


# Clicks that may open a modal dialog are made directly (button.click()), never through
# QTimer.singleShot(0, button.click) and then pump() or waitFor(): on macOS (Qt 6.11, Cocoa
# event dispatcher) no timer fires inside a modal exec() entered from an event that a manual
# processEvents() delivered, so the timer that answers the dialog never runs and the test hangs.
def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, seconds=5.0):
    """Processes events until condition() holds, or the time is up; returns its last value."""
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


def panel():
    return Gui.getMainWindow().findChild(QtWidgets.QWidget, "Variables")


def dockOf(widget):
    while widget is not None and not isinstance(widget, QtWidgets.QDockWidget):
        widget = widget.parentWidget()
    return widget


class TestVariablesPanelGui(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.panel = panel()
        self.assertIsNotNone(self.panel, "no Variables panel")
        self.tree = self.panel.findChild(QtWidgets.QTreeView, "variablesTree")
        self.message = self.panel.findChild(QtWidgets.QLabel, "message")

    def tearDown(self):
        for dialog in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(dialog, QtWidgets.QDialog) and dialog.isVisible():
                dialog.reject()
        pump(0.1)
        for doc in self.docs:
            App.closeDocument(doc.Name)
        dock = dockOf(self.panel)
        if dock is not None:
            dock.hide()
        pump(0.1)

    # helpers

    def newDocument(self, name="TestVariablesPanel"):
        doc = App.newDocument(name)
        doc.UndoMode = 1
        self.docs.append(doc)
        return doc

    def showPanel(self):
        dock = dockOf(self.panel)
        self.assertIsNotNone(dock, "the panel is in no dock")
        dock.show()
        pump(0.3)

    def standardDocument(self):
        """VarSet `VarSet` (Width = 20 mm, Height = 10 mm), a Box whose Length is
        `VarSet.Width * 2`, and a sheet with A1 = 30 mm, alias `Depth`."""
        doc = self.newDocument()
        self.varSet = doc.addObject("App::VarSet", "VarSet")
        self.varSet.addProperty("App::PropertyLength", "Width")
        self.varSet.Width = 20
        self.varSet.addProperty("App::PropertyLength", "Height")
        self.varSet.Height = 10
        self.box = doc.addObject("Part::Box", "Box")
        self.box.setExpression("Length", "VarSet.Width * 2")
        self.sheet = doc.addObject("Spreadsheet::Sheet", "Sheet")
        self.sheet.set("A1", "30 mm")
        self.sheet.setAlias("A1", "Depth")
        doc.recompute()
        self.doc = doc
        self.showPanel()
        return doc

    def model(self):
        return self.tree.model()

    def headers(self):
        model = self.model()
        return [model.index(row, 0) for row in range(model.rowCount())]

    def rows(self):
        """{(header text, name): row index in column 0}, after the panel's rebuild."""
        pump(0.3)
        model = self.model()
        result = {}
        for header in self.headers():
            for row in range(model.rowCount(header)):
                index = model.index(row, NAME, header)
                result[(model.data(header), model.data(index))] = index
        return result

    def cell(self, source, name, column):
        index = self.rows()[(source, name)]
        return index.sibling(index.row(), column)

    def text(self, source, name, column):
        return self.model().data(self.cell(source, name, column))

    def commit(self, source, name, column, text):
        """Edits a cell through its editor as the user does: opens it, types, presses Return."""
        index = self.cell(source, name, column)
        self.tree.setCurrentIndex(index)
        self.tree.edit(index)
        editor = waitFor(lambda: self.tree.indexWidget(index))
        self.assertIsNotNone(editor, "no editor for %s.%s" % (name, column))
        editor.setText(text)
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        pump(0.3)

    def action(self, name):
        action = None
        for candidate in self.panel.findChildren(QtCore.QObject, name):
            if hasattr(candidate, "trigger"):
                action = candidate
        self.assertIsNotNone(action, "no action " + name)
        return action

    def answerNextBox(self, objectName, button, texts, before=None):
        """Answers the next message box named objectName with button, keeping its text; calls
        before() first, while the box is open."""

        def answer():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(widget, QtWidgets.QMessageBox) and widget.objectName() == objectName:
                    texts.append(widget.text())
                    if before:
                        before()
                    widget.button(button).click()
                    return
            QtCore.QTimer.singleShot(50, answer)

        QtCore.QTimer.singleShot(50, answer)

    # G18 first: the dock as a fresh FREECAD_USER_HOME has it

    def test_a_dock_hidden_by_default(self):
        """G18. The "Variables" dock exists; under the Onshape keymap (the fork's default) it is
        shown on the right from the start, as Onshape's variable table is (ops#640, rank 15, F13),
        else hidden. Its toggle action is in View > Panels, and triggering it shows the dock."""
        dock = dockOf(self.panel)
        self.assertIsNotNone(dock)
        keymap = App.ParamGet("User parameter:BaseApp/Preferences/General").GetString(
            "Keymap", "Onshape"
        )
        if keymap != "FreeCAD":
            # Shown once at the start (the one-time marker); whether it still shows depends on
            # the classes run before this one (TestVariablesImportGui comes first and its panel
            # is closed after), so the oracle is the marker and the side
            marker = App.ParamGet("User parameter:BaseApp/Preferences/DockWindows/VariablesView")
            self.assertTrue(marker.GetBool("ShownByKeymap", False))
            self.assertEqual(
                Gui.getMainWindow().dockWidgetArea(dock), QtCore.Qt.RightDockWidgetArea
            )
            dock.hide()
            pump(0.1)
        self.assertFalse(dock.isVisible())
        # The Panels menu has no parent widget: reach it through the menu bar's actions.
        panels = []
        menus = [a.menu() for a in Gui.getMainWindow().menuBar().actions() if a.menu()]
        while menus:
            menu = menus.pop()
            for action in menu.actions():
                if action.menu():
                    if action.text().replace("&", "") == "Panels":
                        panels.append(action.menu())
                    else:
                        menus.append(action.menu())
        self.assertTrue(panels, "no View > Panels menu")
        toggles = []
        for menu in panels:
            menu.aboutToShow.emit()  # the menu fills itself when shown
            toggles += [a for a in menu.actions() if a.text().replace("&", "") == "Variables"]
        self.assertTrue(toggles, "no Variables action in View > Panels")
        toggles[0].trigger()
        pump(0.2)
        self.assertTrue(dock.isVisible())

    # G1-G7, G9, G17

    def test_rows(self):
        """G1. Two VarSets (3 and 2 variables) and a sheet with 2 aliases give 7 rows under 3
        source headers, in document order; each Value is the property's user string."""
        doc = self.newDocument()
        first = doc.addObject("App::VarSet", "VarSet")
        for name, value in (("Width", 20), ("Height", 10), ("Thickness", 2)):
            first.addProperty("App::PropertyLength", name)
            setattr(first, name, value)
        second = doc.addObject("App::VarSet", "Angles")
        second.addProperty("App::PropertyAngle", "Tilt")
        second.Tilt = 30
        second.addProperty("App::PropertyLength", "Gap")
        second.Gap = 1.5
        sheet = doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "30 mm")
        sheet.setAlias("A1", "Depth")
        sheet.set("B2", "4 mm")
        sheet.setAlias("B2", "Margin")
        doc.recompute()
        self.showPanel()

        rows = self.rows()
        self.assertEqual(len(rows), 7)
        self.assertEqual(
            [self.model().data(h) for h in self.headers()], ["VarSet", "Angles", "Sheet"]
        )
        expected = {
            ("VarSet", "Width"): first.Width,
            ("VarSet", "Height"): first.Height,
            ("VarSet", "Thickness"): first.Thickness,
            ("Angles", "Tilt"): second.Tilt,
            ("Angles", "Gap"): second.Gap,
            ("Sheet", "Depth"): sheet.Depth,
            ("Sheet", "Margin"): sheet.Margin,
        }
        self.assertEqual(set(rows), set(expected))
        for (source, name), quantity in expected.items():
            self.assertEqual(self.text(source, name, VALUE), quantity.UserString, name)
        self.assertEqual(self.text("Sheet", "Margin", SOURCE), "Sheet B2")
        self.assertEqual(self.text("Sheet", "Margin", EXPRESSION), "4 mm")

    def test_expression_cell_value(self):
        """G2. Committing `30 mm` on Width (which has an expression) sets the value and clears
        the expression, as one undo step named "Set Width"; Undo gives the expression back."""
        doc = self.standardDocument()
        self.varSet.setExpression("Width", "10 mm * 2")
        doc.recompute()
        undoCount = doc.UndoCount
        self.commit("VarSet", "Width", EXPRESSION, "30 mm")
        self.assertAlmostEqual(self.varSet.Width.Value, 30)
        self.assertIsNone(expressionText(self.varSet, "Width"))
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(doc.UndoNames[0], "Set Width")
        self.assertEqual(self.text("VarSet", "Width", EXPRESSION), self.varSet.Width.UserString)
        doc.undo()
        doc.recompute()
        self.assertEqual(expressionText(self.varSet, "Width"), "10 mm * 2")
        self.assertAlmostEqual(self.varSet.Width.Value, 20)

    def test_expression_cell_expression(self):
        """G3. Committing `#Depth / 2` stores `Sheet.Depth / 2` (15 mm after a recompute);
        committing `#Nope` changes nothing, shows the message and keeps the editor open."""
        doc = self.standardDocument()
        undoCount = doc.UndoCount
        self.commit("VarSet", "Width", EXPRESSION, "#Depth / 2")
        self.assertEqual(expressionText(self.varSet, "Width"), "Sheet.Depth / 2")
        doc.recompute()
        self.assertAlmostEqual(self.varSet.Width.Value, 15)
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(self.text("VarSet", "Width", EXPRESSION), "#Depth / 2")

        self.commit("VarSet", "Width", EXPRESSION, "#Nope")
        self.assertEqual(expressionText(self.varSet, "Width"), "Sheet.Depth / 2")
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertTrue(self.message.isVisible())
        self.assertIn("Nope", self.message.text())
        index = self.cell("VarSet", "Width", EXPRESSION)
        editor = waitFor(lambda: self.tree.indexWidget(self.tree.currentIndex()))
        self.assertIsNotNone(editor, "the editor didn't stay open")
        self.assertEqual(editor.text(), "#Nope")
        self.assertEqual(self.tree.currentIndex().column(), index.column())

    def test_rename(self):
        """G4. Renaming Width to BoxWidth in place: the Box and a sheet cell follow, the value
        stays, one undo step; Undo brings the name and the texts back. Bad names change nothing
        (a unit name such as mm is a good one since rank 54, as Onshape takes t)."""
        doc = self.standardDocument()
        self.sheet.set("B1", "=VarSet.Width")
        doc.recompute()
        undoCount = doc.UndoCount
        self.commit("VarSet", "Width", NAME, "BoxWidth")
        self.assertIn("BoxWidth", self.varSet.PropertiesList)
        self.assertEqual(expressionText(self.box, "Length"), "VarSet.BoxWidth * 2")
        self.assertEqual(self.sheet.getContents("B1"), "=VarSet.BoxWidth")
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(doc.UndoNames[0], "Rename Width to BoxWidth")
        doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 40)
        self.assertIn(("VarSet", "BoxWidth"), self.rows())

        for bad in ("2w", "Height", "A1"):
            self.commit("VarSet", "BoxWidth", NAME, bad)
            self.assertEqual(doc.UndoCount, undoCount + 1, bad)
            self.assertTrue(self.message.isVisible(), bad)
            QTest.keyClick(self.tree.indexWidget(self.tree.currentIndex()), QtCore.Qt.Key_Escape)
            pump(0.2)

        doc.undo()
        self.assertIn("Width", self.varSet.PropertiesList)
        self.assertEqual(expressionText(self.box, "Length"), "VarSet.Width * 2")
        self.assertEqual(self.sheet.getContents("B1"), "=VarSet.Width")
        doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 40)

    def test_delete_with_uses(self):
        """G5. Delete lists the uses (T10's set), deletes on OK, and the Box fails at once
        (ops#599); Undo restores the variable and the Box is valid at 40 mm."""
        doc = self.standardDocument()
        self.sheet.set("B1", "=VarSet.Width")
        doc.recompute()
        undoCount = doc.UndoCount
        self.tree.setCurrentIndex(self.cell("VarSet", "Width", NAME))
        texts = []
        self.answerNextBox("deleteVariableUses", QtWidgets.QMessageBox.Ok, texts)
        self.action("deleteVariable").trigger()
        pump(0.3)
        self.assertEqual(len(texts), 1)
        listed = [line for line in texts[0].split("\n") if line in ("Box.Length", "Sheet.B1")]
        self.assertEqual(sorted(listed), ["Box.Length", "Sheet.B1"])
        self.assertNotIn("Width", self.varSet.PropertiesList)
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(doc.UndoNames[0], "Delete Width")
        self.assertIn("Invalid", self.box.State)

        doc.undo()
        self.assertIn("Width", self.varSet.PropertiesList)
        doc.recompute()
        self.assertNotIn("Invalid", self.box.State)
        self.assertAlmostEqual(self.box.Length.Value, 40)

    def openPanelAddDialog(self):
        """The panel's own Add dialog (ops#317, design section 1.3)."""
        self.action("addVariable").trigger()
        dialog = waitFor(
            lambda: [
                w
                for w in QtWidgets.QApplication.topLevelWidgets()
                if w.objectName() == "addVariableDialog" and w.isVisible()
            ]
        )
        self.assertTrue(dialog, "no Add variable dialog")
        return dialog[0]

    def openAddDialog(self):
        """The stock Add Property dialog, through the Add dialog's "Other..."."""
        panelDialog = self.openPanelAddDialog()
        other = panelDialog.findChild(QtWidgets.QPushButton, "other")
        self.assertIsNotNone(other, "no Other... button")
        other.click()
        dialog = waitFor(
            lambda: [
                w
                for w in QtWidgets.QApplication.topLevelWidgets()
                if w.metaObject().className() == "Gui::Dialog::DlgAddProperty" and w.isVisible()
            ]
        )
        self.assertTrue(dialog, "no Add Property dialog")
        return dialog[0]

    def setAddValue(self, dialog, value):
        editor = waitFor(lambda: dialog.findChild(QtWidgets.QWidget, "editor"))
        self.assertIsNotNone(editor, "no value editor")
        editor.setProperty("rawValue", value)
        pump(0.2)

    def assertAdded(self, doc):
        """The "Variables" VarSet holds Height = 12 mm, made in two undo steps."""
        varSet = doc.getObject("Variables")
        self.assertIsNotNone(varSet)
        self.assertEqual(varSet.TypeId, "App::VarSet")
        self.assertEqual(varSet.Label, "Variables")
        self.assertAlmostEqual(varSet.Height.Value, 12)
        self.assertEqual(doc.UndoCount, 2)
        self.assertEqual(doc.UndoNames, ["Add property", "Add variable"])
        self.assertIn(("Variables", "Height"), self.rows())

    def test_add(self):
        """G6. In an empty document, Add > Other... creates the "Variables" VarSet in its own undo
        step, and the stock dialog adds Height = 12 mm (Length, the default type) in a second
        one."""
        doc = self.newDocument()
        self.showPanel()
        dialog = self.openAddDialog()
        typeBox = dialog.findChild(QtWidgets.QComboBox, "comboBoxType")
        self.assertTrue(typeBox.currentText().endswith("PropertyLength"))
        dialog.findChild(QtWidgets.QLineEdit, "lineEditName").setText("Height")
        pump(0.2)
        self.setAddValue(dialog, 12.0)
        dialog.accept()
        dialog.reject()
        pump(0.3)
        self.assertAdded(doc)

    def test_add_typed(self):
        """G6, as typed: the dialog rebuilds its property on every key and type change, aborting
        its own transaction each time; the new VarSet survives it, and OK adds Height."""
        doc = self.newDocument()
        self.showPanel()
        dialog = self.openAddDialog()
        typeBox = dialog.findChild(QtWidgets.QComboBox, "comboBoxType")
        lengthType = typeBox.currentText()
        QTest.keyClicks(dialog.findChild(QtWidgets.QLineEdit, "lineEditName"), "Height")
        pump(0.2)
        self.assertIsNotNone(doc.getObject("Variables"), "typing the name removed the VarSet")
        typeBox.setCurrentText("App::PropertyAngle")
        pump(0.1)
        typeBox.setCurrentText(lengthType)
        pump(0.2)
        self.setAddValue(dialog, 12.0)
        dialog.accept()
        dialog.reject()
        pump(0.3)
        self.assertAdded(doc)

    def test_add_cancel(self):
        """Add, type a name, Cancel: the empty VarSet is taken out again, and no undo step is left."""
        doc = self.newDocument()
        self.showPanel()
        dialog = self.openAddDialog()
        QTest.keyClicks(dialog.findChild(QtWidgets.QLineEdit, "lineEditName"), "He")
        pump(0.2)
        dialog.reject()
        pump(0.3)
        self.assertEqual(doc.findObjects("App::VarSet"), [])
        self.assertEqual(doc.UndoCount, 0)
        self.assertEqual(self.rows(), {})
        # Taken out by Undo, so Redo would bring the empty VarSet back (design note 3.6).
        self.assertEqual(doc.RedoNames, ["Add variable"])

    # ops#317 PR B: the Type and Description columns and the Add dialog (G-1 to G-3 of
    # notes/variables-studio.md section 6)

    def editable(self, index):
        return bool(self.model().flags(index) & QtCore.Qt.ItemFlag.ItemIsEditable)

    def fillAddDialog(self, dialog, name, kind, value="", description="", varSet=None):
        dialog.findChild(QtWidgets.QLineEdit, "name").setText(name)
        typeBox = dialog.findChild(QtWidgets.QComboBox, "type")
        self.assertGreaterEqual(typeBox.findText(kind), 0, kind)
        typeBox.setCurrentIndex(typeBox.findText(kind))
        dialog.findChild(QtWidgets.QLineEdit, "value").setText(value)
        dialog.findChild(QtWidgets.QPlainTextEdit, "description").setPlainText(description)
        if varSet is not None:
            setBox = dialog.findChild(QtWidgets.QComboBox, "set")
            setBox.setCurrentIndex(setBox.findText(varSet))

    def pressOk(self, dialog):
        box = dialog.findChild(QtWidgets.QDialogButtonBox)
        box.button(QtWidgets.QDialogButtonBox.Ok).click()
        pump(0.3)

    def addDialogOpen(self):
        return any(
            w.objectName() == "addVariableDialog" and w.isVisible()
            for w in QtWidgets.QApplication.topLevelWidgets()
        )

    def answerDescription(self, text):
        """Answers the next description dialog with text."""

        def answer():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if (
                    isinstance(widget, QtWidgets.QInputDialog)
                    and widget.objectName() == "descriptionDialog"
                    and widget.isVisible()
                ):
                    widget.setTextValue(text)
                    widget.accept()
                    return
            QtCore.QTimer.singleShot(50, answer)

        QtCore.QTimer.singleShot(50, answer)

    def test_type_and_description_columns(self):
        """G-1. Type names each kind of variable; Description shows a VarSet variable's
        description, its first line in the cell and all of it in the tooltip. An alias's
        Description is empty and can't be edited; Type can't be edited."""
        doc = self.newDocument()
        varSet = doc.addObject("App::VarSet", "VarSet")
        types = [
            ("App::PropertyLength", "Width", "Length"),
            ("App::PropertyDistance", "Offset", "Length"),
            ("App::PropertyAngle", "Tilt", "Angle"),
            ("App::PropertyFloat", "Ratio", "Number"),
            ("App::PropertyInteger", "Count", "Integer"),
            ("App::PropertyBool", "Flag", "Yes/No"),
            ("App::PropertyString", "Note", "Text"),
            ("App::PropertyArea", "Face", "Area"),
        ]
        for propertyType, name, _shown in types:
            varSet.addProperty(propertyType, name)
        varSet.setDocumentationOfProperty("Width", "the width")
        varSet.setDocumentationOfProperty("Tilt", "first line\nsecond <&> line")
        sheet = doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "30 mm")
        sheet.setAlias("A1", "Depth")
        doc.recompute()
        self.showPanel()

        for _propertyType, name, shown in types:
            self.assertEqual(self.text("VarSet", name, TYPE), shown, name)
        self.assertEqual(self.text("Sheet", "Depth", TYPE), "Length")
        self.assertEqual(self.text("VarSet", "Width", DESCRIPTION), "the width")
        self.assertEqual(self.text("VarSet", "Tilt", DESCRIPTION), "first line …")
        tilt = self.cell("VarSet", "Tilt", DESCRIPTION)
        self.assertEqual(tilt.data(QtCore.Qt.ToolTipRole), "first line\nsecond <&> line")
        self.assertEqual(self.text("VarSet", "Ratio", DESCRIPTION), "")
        self.assertTrue(self.editable(self.cell("VarSet", "Ratio", DESCRIPTION)))
        self.assertFalse(self.editable(self.cell("VarSet", "Width", TYPE)))
        depth = self.cell("Sheet", "Depth", DESCRIPTION)
        self.assertEqual(self.model().data(depth), "")
        self.assertFalse(self.editable(depth))

    def test_add_dialog(self):
        """G-2. Add with the type Angle, a value and a description in a new document: one undo
        step makes the "Variables" VarSet and the variable, and one undo removes both."""
        doc = self.newDocument()
        self.showPanel()
        dialog = self.openPanelAddDialog()
        setBox = dialog.findChild(QtWidgets.QComboBox, "set")
        self.assertEqual(setBox.currentText(), "Variables (new)")
        self.fillAddDialog(dialog, "Tilt", "Angle", "30 deg", "the tilt\nof the roof")
        self.pressOk(dialog)
        self.assertFalse(self.addDialogOpen())

        varSet = doc.getObject("Variables")
        self.assertIsNotNone(varSet)
        self.assertEqual(varSet.TypeId, "App::VarSet")
        self.assertEqual(varSet.getTypeIdOfProperty("Tilt"), "App::PropertyAngle")
        self.assertAlmostEqual(varSet.Tilt.Value, 30)
        self.assertEqual(varSet.getDocumentationOfProperty("Tilt"), "the tilt\nof the roof")
        self.assertEqual(doc.UndoNames, ["Add Tilt"])
        self.assertEqual(self.text("Variables", "Tilt", TYPE), "Angle")
        self.assertEqual(self.text("Variables", "Tilt", DESCRIPTION), "the tilt …")

        doc.undo()
        self.assertIsNone(doc.getObject("Variables"))
        self.assertEqual(doc.UndoCount, 0)
        self.assertEqual(self.rows(), {})

    def test_add_dialog_expression_in_a_set(self):
        """Add to the selected row's VarSet: "Length" makes a Distance (a negative value stays),
        and the expression is stored as the Expression column stores it."""
        doc = self.standardDocument()
        self.tree.setCurrentIndex(self.cell("VarSet", "Width", NAME))
        dialog = self.openPanelAddDialog()
        self.assertEqual(dialog.findChild(QtWidgets.QComboBox, "set").currentText(), "VarSet")
        self.fillAddDialog(dialog, "Gap", "Length", "#Width / 4 - #Height")
        self.pressOk(dialog)
        self.assertFalse(self.addDialogOpen())
        self.assertEqual(self.varSet.getTypeIdOfProperty("Gap"), "App::PropertyDistance")
        self.assertNotIn("#", expressionText(self.varSet, "Gap"))
        doc.recompute()
        self.assertAlmostEqual(self.varSet.Gap.Value, -5)
        self.assertEqual(doc.UndoNames[0], "Add Gap")
        self.assertIsNone(doc.getObject("Variables"))

    def test_add_dialog_refuses(self):
        """Nothing is made, and the dialog says why and stays open: a unit or function name, a
        value whose unit doesn't fit the type, an expression whose unit doesn't fit (made in the
        transaction, then taken back with it)."""
        doc = self.standardDocument()
        undoCount = doc.UndoCount
        dialog = self.openPanelAddDialog()
        error = dialog.findChild(QtWidgets.QLabel, "error")
        cases = [
            ("2t", "Length", "2 mm", "isn't a name"),
            ("pow", "Number", "2", "is a function"),
            ("Label", "Number", "2", "property of every"),
            ("Ratio", "Number", "2 mm", "no unit"),
            ("Tilt", "Angle", "5 mm", "wrong unit"),
            ("Tilt", "Angle", "#Width * 2", "the type of Tilt is Angle"),
            ("Ratio", "Number", "#Width", "the type of Ratio is Number"),
            ("Size", "Length", "#Width * #Height", "the type of Size is Length"),
        ]
        for name, kind, value, fragment in cases:
            with self.subTest(name=name, value=value):
                self.fillAddDialog(dialog, name, kind, value)
                self.pressOk(dialog)
                self.assertTrue(self.addDialogOpen())
                self.assertTrue(error.isVisible())
                self.assertIn(fragment, error.text())
                self.assertIsNone(doc.getObject("Variables"))
                self.assertEqual(doc.UndoCount, undoCount)
                self.assertEqual(doc.getBookedTransactionID(), 0)
        dialog.reject()

    def test_add_dialog_unitless_expression(self):
        """An expression without a unit takes a Length's or an Angle's default unit, as App's
        checkPathUnit and the Expression column take it (PR 313 round 1)."""
        doc = self.standardDocument()
        for name, kind, value, expected in [
            ("Size", "Length", "#Width / #Height", 2),
            ("Turn", "Angle", "=15", 15),
        ]:
            with self.subTest(name=name):
                dialog = self.openPanelAddDialog()
                self.fillAddDialog(dialog, name, kind, value, varSet="VarSet")
                self.pressOk(dialog)
                self.assertFalse(self.addDialogOpen(), name)
                doc.recompute()
                self.assertAlmostEqual(getattr(self.varSet, name).Value, expected)
                self.assertEqual(doc.UndoNames[0], "Add " + name)

    def test_add_dialog_refuses_in_booked_transaction(self):
        """With another transaction booked (a task dialog's), a refused Add takes back what it
        made, by hand: no VarSet or variable is left, the booking stays open, and aborting it
        leaves nothing (PR 313 round 1)."""
        doc = self.standardDocument()
        undoCount = doc.UndoCount
        doc.openTransaction("Task")
        booked = doc.getBookedTransactionID()
        self.assertNotEqual(booked, 0)
        self.tree.setCurrentIndex(QtCore.QModelIndex())
        dialog = self.openPanelAddDialog()
        self.assertGreaterEqual(
            dialog.findChild(QtWidgets.QComboBox, "set").findText("Variables (new)"), 0
        )
        error = dialog.findChild(QtWidgets.QLabel, "error")
        for varSet in ["Variables (new)", "VarSet"]:
            with self.subTest(varSet=varSet):
                self.fillAddDialog(dialog, "Size", "Length", "#Width * #Height", varSet=varSet)
                self.pressOk(dialog)
                self.assertTrue(self.addDialogOpen())
                self.assertIn("the type of Size is Length", error.text())
                self.assertEqual([o.Name for o in doc.findObjects("App::VarSet")], ["VarSet"])
                self.assertNotIn("Size", self.varSet.PropertiesList)
                self.assertEqual(doc.getBookedTransactionID(), booked)
        dialog.reject()
        doc.abortTransaction()
        self.assertEqual(doc.getBookedTransactionID(), 0)
        self.assertEqual(doc.UndoCount, undoCount)
        self.assertEqual([o.Name for o in doc.findObjects("App::VarSet")], ["VarSet"])
        self.assertNotIn("Size", self.varSet.PropertiesList)

    def test_add_dialog_new_set_not_last(self):
        """The new "Variables" set is found by its name, not as the document's last object: an
        observer that adds an object as the set is made doesn't take the variable (PR 313
        round 1)."""
        doc = self.standardDocument()

        class AddsOne:
            def slotCreatedObject(self, obj):
                if obj.Document == doc and obj.TypeId == "App::VarSet":
                    doc.addObject("App::DocumentObjectGroup", "Extra")

        observer = AddsOne()
        App.addDocumentObserver(observer)
        try:
            self.tree.setCurrentIndex(QtCore.QModelIndex())
            dialog = self.openPanelAddDialog()
            self.fillAddDialog(dialog, "Depth2", "Length", "5 mm", varSet="Variables (new)")
            self.pressOk(dialog)
        finally:
            App.removeDocumentObserver(observer)
        self.assertFalse(self.addDialogOpen())
        varSet = doc.getObject("Variables")
        self.assertIsNotNone(varSet)
        self.assertIsNotNone(doc.getObject("Extra"))
        self.assertAlmostEqual(varSet.Depth2.Value, 5)

    def test_add_other_set_gone(self):
        """Other... with a set chosen that is deleted before the stock dialog opens: a message,
        and never a new "Variables" set in its place (PR 313 round 1)."""
        doc = self.standardDocument()
        dialog = self.openPanelAddDialog()
        setBox = dialog.findChild(QtWidgets.QComboBox, "set")
        setBox.setCurrentIndex(setBox.findText("VarSet"))
        other = dialog.findChild(QtWidgets.QPushButton, "other")

        def clickThenDelete():
            other.click()
            doc.removeObject("VarSet")

        clickThenDelete()
        pump(0.5)
        self.assertEqual(doc.findObjects("App::VarSet"), [])
        self.assertFalse(
            any(
                w.metaObject().className() == "Gui::Dialog::DlgAddProperty" and w.isVisible()
                for w in QtWidgets.QApplication.topLevelWidgets()
            )
        )
        self.assertTrue(self.message.isVisible())
        self.assertIn("VarSet", self.message.text())

    def test_describe(self):
        """G-3. A description typed in its cell is one undo step, "Describe Width"; Edit
        description... edits several lines, and a cell of several lines opens that dialog rather
        than a line editor. Undo gives each old text back."""
        doc = self.standardDocument()
        self.commit("VarSet", "Width", DESCRIPTION, "the width")
        self.assertEqual(self.varSet.getDocumentationOfProperty("Width"), "the width")
        self.assertEqual(doc.UndoNames[0], "Describe Width")
        self.assertEqual(self.text("VarSet", "Width", DESCRIPTION), "the width")

        self.tree.setCurrentIndex(self.cell("VarSet", "Width", NAME))
        self.answerDescription("the width\nof the frame")
        self.action("editDescription").trigger()
        pump(0.3)
        self.assertEqual(
            self.varSet.getDocumentationOfProperty("Width"), "the width\nof the frame"
        )
        self.assertEqual(self.text("VarSet", "Width", DESCRIPTION), "the width …")

        index = self.cell("VarSet", "Width", DESCRIPTION)
        self.answerDescription("short")
        self.tree.setCurrentIndex(index)
        self.tree.edit(index)
        waitFor(lambda: self.varSet.getDocumentationOfProperty("Width") == "short")
        self.assertEqual(self.varSet.getDocumentationOfProperty("Width"), "short")
        self.assertEqual(doc.UndoNames[:3], ["Describe Width"] * 3)

        doc.undo()
        self.assertEqual(
            self.varSet.getDocumentationOfProperty("Width"), "the width\nof the frame"
        )
        doc.undo()
        doc.undo()
        self.assertEqual(self.varSet.getDocumentationOfProperty("Width"), "")
        self.assertEqual(self.text("VarSet", "Width", DESCRIPTION), "")

    def test_live_update(self):
        """G7. Python changes show at once: addProperty adds a row, setExpression updates the
        Expression and Value, removeProperty removes the row; switching documents switches rows."""
        doc = self.standardDocument()
        self.varSet.addProperty("App::PropertyLength", "Depth2")
        self.assertIn(("VarSet", "Depth2"), self.rows())
        self.varSet.setExpression("Depth2", "VarSet.Height * 3")
        doc.recompute()
        self.assertEqual(self.text("VarSet", "Depth2", EXPRESSION), "#Height * 3")
        self.assertEqual(self.text("VarSet", "Depth2", VALUE), self.varSet.Depth2.UserString)
        self.varSet.removeProperty("Depth2")
        self.assertNotIn(("VarSet", "Depth2"), self.rows())

        other = self.newDocument("TestVariablesPanelOther")
        params = other.addObject("App::VarSet", "Params")
        params.addProperty("App::PropertyLength", "Pitch")
        Gui.setActiveDocument(other.Name)
        pump(0.3)
        self.assertEqual(set(self.rows()), {("Params", "Pitch")})
        Gui.setActiveDocument(doc.Name)
        pump(0.3)
        self.assertIn(("VarSet", "Width"), self.rows())

    def test_alias_rows(self):
        """G9. An alias's Expression sets the cell; renaming sets the alias and the Box's text
        follows; Delete removes the alias, the text becomes the cell address, the value stays."""
        doc = self.standardDocument()
        self.box.setExpression("Height", "Sheet.Depth")
        doc.recompute()

        self.commit("Sheet", "Depth", EXPRESSION, "#Width * 2")
        self.assertEqual(self.sheet.getContents("A1"), "=VarSet.Width * 2")
        self.commit("Sheet", "Depth", EXPRESSION, "35 mm")
        # A quantity cell: stock stores it as "=35 mm".
        self.assertEqual(self.sheet.getContents("A1"), "=35 mm")
        self.assertEqual(self.text("Sheet", "Depth", EXPRESSION), "35 mm")
        doc.recompute()

        self.commit("Sheet", "Depth", NAME, "Thick")
        self.assertEqual(self.sheet.getAlias("A1"), "Thick")
        self.assertEqual(expressionText(self.box, "Height"), "Sheet.Thick")

        self.tree.setCurrentIndex(self.cell("Sheet", "Thick", NAME))
        self.action("deleteVariable").trigger()
        pump(0.3)
        self.assertIsNone(self.sheet.getAlias("A1"))
        self.assertEqual(expressionText(self.box, "Height"), "Sheet.A1")
        doc.recompute()
        self.assertAlmostEqual(self.box.Height.Value, 35)

    def test_shown_form_round_trip(self):
        """G17. `Depth = .Width * 2` in the VarSet reads `#Width * 2`; committing it unchanged
        leaves the stored text as it was."""
        doc = self.standardDocument()
        self.varSet.addProperty("App::PropertyLength", "Depth")
        self.varSet.setExpression("Depth", ".Width * 2")
        doc.recompute()
        stored = expressionText(self.varSet, "Depth")
        undoCount = doc.UndoCount
        self.assertEqual(self.text("VarSet", "Depth", EXPRESSION), "#Width * 2")
        self.commit("VarSet", "Depth", EXPRESSION, "#Width * 2")
        self.assertEqual(expressionText(self.varSet, "Depth"), stored)
        self.assertEqual(doc.UndoCount, undoCount)

    # Review round 1 of fork PR 155

    def test_delete_rebuild_during_box(self):
        """The panel rebuilds while Delete's message box is open (a change elsewhere): OK still
        deletes Width, as one undo step, and touches its users."""
        doc = self.standardDocument()
        undoCount = doc.UndoCount
        self.tree.setCurrentIndex(self.cell("VarSet", "Width", NAME))

        def changeElsewhere():
            self.varSet.Height = 11
            pump(0.3)  # the rebuild timer fires inside the box

        texts = []
        self.answerNextBox("deleteVariableUses", QtWidgets.QMessageBox.Ok, texts, changeElsewhere)
        self.action("deleteVariable").trigger()
        pump(0.3)
        self.assertEqual(len(texts), 1)
        self.assertNotIn("Width", self.varSet.PropertiesList)
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(doc.UndoNames[0], "Delete Width")
        self.assertIn("Invalid", self.box.State)

    def test_delete_own_use(self):
        """`Depth = .Width * 2` in the VarSet itself: Delete lists VarSet.Depth, and the VarSet
        fails at once (ops#599)."""
        doc = self.standardDocument()
        self.box.clearExpression("Length")
        self.varSet.addProperty("App::PropertyLength", "Depth")
        self.varSet.setExpression("Depth", ".Width * 2")
        doc.recompute()
        self.assertNotIn("Invalid", self.varSet.State)
        self.tree.setCurrentIndex(self.cell("VarSet", "Width", NAME))
        texts = []
        self.answerNextBox("deleteVariableUses", QtWidgets.QMessageBox.Ok, texts)
        self.action("deleteVariable").trigger()
        pump(0.3)
        self.assertEqual(len(texts), 1)
        self.assertIn("VarSet.Depth", texts[0].split("\n"))
        self.assertNotIn("Width", self.varSet.PropertiesList)
        self.assertIn("Invalid", self.varSet.State)

    def test_text_values(self):
        """A text that isn't meant as an expression is the value: an alias holding `steel` edited
        to `bronze`, and a String variable; a Bool takes True or False and refuses other text."""
        doc = self.standardDocument()
        self.sheet.set("B1", "steel")
        self.sheet.setAlias("B1", "Material")
        self.varSet.addProperty("App::PropertyString", "Finish")
        self.varSet.Finish = "matte"
        self.varSet.addProperty("App::PropertyBool", "Hollow")
        self.varSet.Hollow = True
        doc.recompute()

        self.commit("Sheet", "Material", EXPRESSION, "bronze")
        # A text cell: stock shows its contents with a leading quote.
        self.assertEqual(self.sheet.getContents("B1"), "'bronze")
        doc.recompute()
        self.assertEqual(self.sheet.get("B1"), "bronze")
        self.commit("VarSet", "Finish", EXPRESSION, "gloss")
        self.assertEqual(self.varSet.Finish, "gloss")
        self.assertIsNone(expressionText(self.varSet, "Finish"))
        self.commit("VarSet", "Hollow", EXPRESSION, "False")
        self.assertFalse(self.varSet.Hollow)
        self.assertIsNone(expressionText(self.varSet, "Hollow"))

        undoCount = doc.UndoCount
        self.commit("VarSet", "Hollow", EXPRESSION, "maybe")
        self.assertFalse(self.varSet.Hollow)
        self.assertEqual(doc.UndoCount, undoCount)
        self.assertTrue(self.message.isVisible())
        QTest.keyClick(self.tree.indexWidget(self.tree.currentIndex()), QtCore.Qt.Key_Escape)
        pump(0.2)

        # Text that names what exists, or starts with '=', is still an expression.
        self.commit("Sheet", "Material", EXPRESSION, "=VarSet.Width * 2")
        self.assertEqual(self.sheet.getContents("B1"), "=VarSet.Width * 2")

    def test_numbers(self):
        """A Float takes 2.5; an Integer takes 3 and refuses 2.5 and 3 mm, changing nothing."""
        doc = self.standardDocument()
        self.varSet.addProperty("App::PropertyFloat", "Ratio")
        self.varSet.addProperty("App::PropertyInteger", "Count")
        self.varSet.Count = 1
        doc.recompute()

        self.commit("VarSet", "Ratio", EXPRESSION, "2.5")
        self.assertAlmostEqual(self.varSet.Ratio, 2.5)
        self.commit("VarSet", "Count", EXPRESSION, "3")
        self.assertEqual(self.varSet.Count, 3)
        self.assertEqual(self.text("VarSet", "Count", VALUE), "3")
        undoCount = doc.UndoCount
        for bad in ("2.5", "3 mm", "1e30"):
            self.commit("VarSet", "Count", EXPRESSION, bad)
            self.assertEqual(self.varSet.Count, 3, bad)
            self.assertEqual(doc.UndoCount, undoCount, bad)
            self.assertTrue(self.message.isVisible(), bad)
            QTest.keyClick(self.tree.indexWidget(self.tree.currentIndex()), QtCore.Qt.Key_Escape)
            pump(0.2)

    def test_edit_in_booked_transaction(self):
        """An edit while another transaction is booked joins it: no step of its own."""
        doc = self.standardDocument()
        undoCount = doc.UndoCount
        doc.openTransaction("Outer")
        self.commit("VarSet", "Width", EXPRESSION, "30 mm")
        doc.commitTransaction()
        self.assertAlmostEqual(self.varSet.Width.Value, 30)
        self.assertAlmostEqual(self.box.Length.Value, 60)  # recomputed in the booking (ops#599)
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(doc.UndoNames[0], "Outer")

    def padDocument(self):
        """VarSet `VarSet` (Size = 10 mm, Base = 15 mm) and a Pad of a 5 mm circle, Length
        `#Size`."""
        import Part
        import Sketcher

        doc = self.newDocument()
        self.varSet = doc.addObject("App::VarSet", "VarSet")
        self.varSet.addProperty("App::PropertyLength", "Size")
        self.varSet.Size = 10
        self.varSet.addProperty("App::PropertyLength", "Base")
        self.varSet.Base = 15
        body = doc.addObject("PartDesign::Body", "Body")
        sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 5))
        self.sketch = sketch
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = sketch
        self.pad.setExpression("Length", "#Size")
        doc.recompute()
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 25 * 10, places=6)
        self.doc = doc
        self.showPanel()
        return doc

    def assertRegenerated(self, length):
        """The Pad follows the edit at once, with no recompute of the test's own."""
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])
        self.assertAlmostEqual(self.pad.Length.Value, length)
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 25 * length, places=6)

    def test_value_edit_regenerates(self):
        """ops#599 (Onshape): a value set in the panel regenerates the Pad that uses it, in the
        edit's one undo step; one Undo gives back the length and the shape."""
        doc = self.padDocument()
        undoCount = doc.UndoCount
        self.commit("VarSet", "Size", EXPRESSION, "20 mm")
        self.assertRegenerated(20)
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(doc.UndoNames[0], "Set Size")
        doc.undo()
        self.assertAlmostEqual(self.varSet.Size.Value, 10)
        self.assertAlmostEqual(self.pad.Length.Value, 10)
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 25 * 10, places=6)

    def radiusDocument(self):
        """padDocument, and the sketch circle's radius `#Radius` (5 mm)."""
        import Sketcher

        doc = self.padDocument()
        self.varSet.addProperty("App::PropertyLength", "Radius")
        self.varSet.Radius = 5
        self.sketch.addConstraint(Sketcher.Constraint("Radius", 0, 5))
        self.sketch.setExpression("Constraints[0]", "#Radius")
        doc.recompute()
        return doc

    def assertCancelledThenRight(self, doc):
        """After the panel edit (Radius 8 mm) during the sketch's edit: nothing recomputed, the
        sketch's Cancel, then a recompute builds both at 8 mm."""
        self.assertIn("Touched", self.varSet.State)
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 25 * 10, places=6)
        # The sketch's Cancel acts in the editing view: the only view of its document.
        Gui.setActiveDocument(doc.Name)
        pump(0.3)
        Gui.runCommand("Sketcher_CancelSketch")
        pump(0.3)
        self.assertIsNone(Gui.getDocument(doc.Name).getInEdit())
        doc.recompute()
        self.assertAlmostEqual(self.sketch.Geometry[0].Radius, 8)
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 64 * 10, places=6)

    def test_edit_during_sketch_edit(self):
        """Review pr599-r1 R1-1: while a sketch is in edit, a panel edit doesn't recompute and
        the document stays touched. The sketch's Cancel restores it from its backup and untouches
        everything; a recompute there would have left the Pad built from the cancelled sketch."""
        doc = self.radiusDocument()
        Gui.ActiveDocument.setEdit(self.sketch.Name)
        pump(0.3)
        self.commit("VarSet", "Radius", EXPRESSION, "8 mm")
        self.assertIn("Touched", self.varSet.State)
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 25 * 10, places=6)
        Gui.runCommand("Sketcher_CancelSketch")
        pump(0.3)
        self.assertIsNone(Gui.ActiveDocument.getInEdit())
        doc.recompute()
        self.assertAlmostEqual(self.sketch.Geometry[0].Radius, 8)
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 64 * 10, places=6)

    def test_edit_during_sketch_edit_second_view(self):
        """Review pr599-r1b R1b-1: the same with another view of the document active (the
        editing view isn't, so its getInEdit() is empty)."""
        doc = self.radiusDocument()
        Gui.ActiveDocument.setEdit(self.sketch.Name)
        pump(0.3)
        Gui.runCommand("Std_ViewCreate")
        pump(0.5)
        second = Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow()
        self.assertIsNone(Gui.ActiveDocument.getInEdit())
        self.commit("VarSet", "Radius", EXPRESSION, "8 mm")
        second.close()
        pump(0.3)
        self.assertCancelledThenRight(doc)

    def test_toolbar_does_not_widen_the_panel(self):
        """ops#640 round 5: the toolbar's text actions (Copy from FreeCAD file..., Refresh...)
        don't set the panel's width: a dock 441 px wide took 185 px from the 3D view (and moved
        the 3D view's centre under the Tasks overlay). What doesn't fit goes to the toolbar's
        overflow button, and the list's context menu has every action."""
        toolBar = self.panel.findChild(QtWidgets.QToolBar)
        self.assertIsNotNone(toolBar)
        self.assertLess(self.panel.sizeHint().width(), toolBar.sizeHint().width())
        names = {action.objectName() for action in self.tree.actions()}
        for name in ("copyFromFreeCAD", "refreshCopy", "locateSource"):
            self.assertIn(name, names)

    def test_edit_during_other_document_sketch_edit(self):
        """Review pr599-r1b R1b-3: a sketch in another document, its radius the variable across
        documents, in edit there: the panel edit doesn't recompute, and that document's Cancel
        leaves nothing silently stale."""
        import Part
        import Sketcher

        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        doc = self.padDocument()
        self.varSet.addProperty("App::PropertyLength", "Radius")
        self.varSet.Radius = 5
        doc.recompute()
        doc.saveAs(os.path.join(folder, "a.FCStd"))
        other = self.newDocument("TestVariablesPanelOther")
        other.saveAs(os.path.join(folder, "b.FCStd"))
        body = other.addObject("PartDesign::Body", "Body")
        self.sketch = body.newObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.Circle(App.Vector(0, 0, 0), App.Vector(0, 0, 1), 5))
        self.sketch.addConstraint(Sketcher.Constraint("Radius", 0, 5))
        self.sketch.setExpression("Constraints[0]", doc.Name + "#VarSet.Radius")
        self.pad = body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.sketch
        self.pad.Length = 10
        other.recompute()
        Gui.getDocument(other.Name).setEdit(self.sketch.Name)
        pump(0.3)
        Gui.setActiveDocument(doc.Name)
        pump(0.3)
        self.commit("VarSet", "Radius", EXPRESSION, "8 mm")
        self.assertCancelledThenRight(other)

    def test_edit_after_refused_edit(self):
        """Review pr599-r1c R1c-a: an edit the view provider refuses (a frozen sketch, "a dialog
        is already open") leaves its document among the edit documents with nothing in edit; the
        panel still regenerates at once."""

        class Refuses:
            def __init__(self, vobj):
                vobj.Proxy = self

            def attach(self, vobj):
                pass

            def setEdit(self, vobj, mode=0):
                return False

            def unsetEdit(self, vobj, mode=0):
                return True

            def dumps(self):
                return None

            def loads(self, state):
                return None

        doc = self.padDocument()
        refuser = doc.addObject("App::FeaturePython", "Refuser")
        Refuses(refuser.ViewObject)
        doc.recompute()
        Gui.getDocument(doc.Name).setEdit(refuser.Name)
        pump(0.3)
        self.assertIsNone(Gui.ActiveDocument.getInEdit())
        self.commit("VarSet", "Size", EXPRESSION, "20 mm")
        self.assertRegenerated(20)

    def test_expression_edit_regenerates(self):
        """ops#599: the same for an expression: `#Base * 2` makes the Pad 30 mm long at once."""
        doc = self.padDocument()
        undoCount = doc.UndoCount
        self.commit("VarSet", "Size", EXPRESSION, "#Base * 2")
        self.assertEqual(expressionText(self.varSet, "Size"), "Base * 2")  # its own VarSet
        self.assertRegenerated(30)
        self.assertEqual(doc.UndoCount, undoCount + 1)
        doc.undo()
        self.assertIsNone(expressionText(self.varSet, "Size"))
        self.assertAlmostEqual(self.pad.Length.Value, 10)
        self.assertAlmostEqual(self.pad.Shape.Volume, math.pi * 25 * 10, places=6)

    def test_failed_commit_on_leaving(self):
        """A failed commit made by leaving the editor (another row made current) shows the message
        but doesn't reopen the editor; Return does reopen it (G3)."""
        doc = self.standardDocument()
        index = self.cell("VarSet", "Width", EXPRESSION)
        self.tree.setCurrentIndex(index)
        self.tree.edit(index)
        editor = waitFor(lambda: self.tree.indexWidget(index))
        self.assertIsNotNone(editor)
        editor.setText("#Nope")
        self.tree.setCurrentIndex(self.cell("VarSet", "Height", NAME))
        pump(0.3)
        self.assertTrue(self.message.isVisible())
        self.assertIn("Nope", self.message.text())
        self.assertIsNone(self.tree.indexWidget(self.cell("VarSet", "Width", EXPRESSION)))
        self.assertEqual(self.tree.currentIndex().data(VariableRole), "Height")
        self.assertEqual(expressionText(self.varSet, "Width"), None)

    def test_close_document(self):
        """Closing the document the panel shows empties it and shows the hint."""
        doc = self.standardDocument()
        self.assertTrue(self.rows())
        hint = self.panel.findChild(QtWidgets.QLabel, "hint")
        self.assertFalse(hint.isVisible())
        self.docs.remove(doc)
        App.closeDocument(doc.Name)
        pump(0.3)
        self.assertEqual(self.model().rowCount(), 0)
        self.assertTrue(hint.isVisible())

    def test_hidden_panel_waits(self):
        """While hidden, the panel doesn't rebuild on changes; shown, it has them."""
        doc = self.newDocument()
        self.showPanel()
        self.assertEqual(self.rows(), {})
        dockOf(self.panel).hide()
        pump(0.2)
        varSet = doc.addObject("App::VarSet", "VarSet")
        varSet.addProperty("App::PropertyLength", "Width")
        doc.recompute()
        pump(0.3)
        self.assertEqual(self.model().rowCount(), 0, "the hidden panel rebuilt")
        self.showPanel()
        self.assertEqual(set(self.rows()), {("VarSet", "Width")})

    # ops#188

    def test_text_values_hash_and_words(self):
        """Text with '#' that doesn't parse, a single word naming a property of the owner, and a
        number or quantity are a String's or an alias's text; '=' makes a reference. A Bool's text
        is trimmed."""
        doc = self.standardDocument()
        self.sheet.set("B1", "steel")
        self.sheet.setAlias("B1", "Material")
        self.varSet.addProperty("App::PropertyString", "Finish")
        self.varSet.Finish = "matte"
        self.varSet.addProperty("App::PropertyBool", "Hollow")
        doc.recompute()

        for text in ("Part #3", "Label", "Height", "12", "3 mm"):
            self.commit("VarSet", "Finish", EXPRESSION, text)
            self.assertEqual(self.varSet.Finish, text)
            self.assertIsNone(expressionText(self.varSet, "Finish"), text)
        self.commit("Sheet", "Material", EXPRESSION, "Part #3")
        doc.recompute()
        self.assertEqual(self.sheet.get("B1"), "Part #3")

        # Through the editor, whose validator would strip the '=' (fork PR 158 review).
        self.commit("VarSet", "Finish", EXPRESSION, "=Label")
        self.assertEqual(expressionText(self.varSet, "Finish"), "Label")
        self.commit("VarSet", "Finish", EXPRESSION, "=<<Part #3>>")
        self.assertEqual(expressionText(self.varSet, "Finish"), "<<Part #3>>")
        self.commit("Sheet", "Material", EXPRESSION, "=Label")
        self.assertEqual(self.sheet.getContents("B1"), "=Label")

        self.commit("VarSet", "Hollow", EXPRESSION, " True")
        self.assertTrue(self.varSet.Hollow)

    def test_text_values_unresolved_hash(self):
        """A '#' where the parser resolves a variable makes the text an expression: an unknown
        `#Widht` and an ambiguous `#Width` show their error, for a String and an alias alike.
        A '#' anywhere else leaves it text (fork PR 158 review)."""
        doc = self.standardDocument()
        self.sheet.set("B1", "steel")
        self.sheet.setAlias("B1", "Material")
        self.varSet.addProperty("App::PropertyString", "Finish")
        self.varSet.Finish = "matte"
        doc.recompute()

        other = doc.addObject("App::VarSet", "Other")
        other.addProperty("App::PropertyLength", "Width")
        doc.recompute()
        for source, name in (("VarSet", "Finish"), ("Sheet", "Material")):
            for text, error in (("#Widht", "Widht"), ("#Width", "ambiguous")):
                undoCount = doc.UndoCount
                self.commit(source, name, EXPRESSION, text)
                self.assertEqual(doc.UndoCount, undoCount, text)
                self.assertTrue(self.message.isVisible(), text)
                self.assertIn(error, self.message.text(), text)
                QTest.keyClick(self.tree.indexWidget(self.tree.currentIndex()), QtCore.Qt.Key_Escape)
                pump(0.2)
        self.assertEqual(self.varSet.Finish, "matte")
        self.assertIsNone(expressionText(self.varSet, "Finish"))
        doc.recompute()
        self.assertEqual(self.sheet.get("B1"), "steel")

        for text in ("# of", "#1", "Lot#A", "Part #A"):
            self.commit("VarSet", "Finish", EXPRESSION, text)
            self.assertEqual(self.varSet.Finish, text)
            self.assertIsNone(expressionText(self.varSet, "Finish"), text)

    def test_text_values_hash_hint(self):
        """A text value with '#' and a letter that fails as an expression (`#FF0000`) says how to
        write it as text, for a String and an alias; `=<<#FF0000>>` then stores it. An expression
        typed with '=', and a number variable's, get no hint (ops#192)."""
        doc = self.standardDocument()
        self.sheet.set("B1", "steel")
        self.sheet.setAlias("B1", "Material")
        self.varSet.addProperty("App::PropertyString", "Finish")
        self.varSet.Finish = "matte"
        doc.recompute()

        def failsWith(source, name, text):
            undoCount = doc.UndoCount
            self.commit(source, name, EXPRESSION, text)
            self.assertEqual(doc.UndoCount, undoCount, text)
            self.assertTrue(self.message.isVisible(), text)
            message = self.message.text()
            QTest.keyClick(self.tree.indexWidget(self.tree.currentIndex()), QtCore.Qt.Key_Escape)
            pump(0.2)
            return message

        for source, name in (("VarSet", "Finish"), ("Sheet", "Material")):
            message = failsWith(source, name, "#FF0000")
            self.assertIn("no variable named FF0000", message)
            self.assertIn("=<<#FF0000>>", message)
            self.assertIn("=<<...>>", failsWith(source, name, "#a >> b"))
            self.assertNotIn("=<<", failsWith(source, name, "=#FF0000"))
        self.assertNotIn("=<<", failsWith("VarSet", "Height", "#FF0000"))

        self.commit("VarSet", "Finish", EXPRESSION, "=<<#FF0000>>")
        doc.recompute()
        self.assertEqual(self.varSet.Finish, "#FF0000")
        self.commit("Sheet", "Material", EXPRESSION, "=<<#FF0000>>")
        doc.recompute()
        self.assertEqual(self.sheet.get("B1"), "#FF0000")

    def test_collapsed_per_document(self):
        """A header collapsed in one document stays collapsed there, and a header for an object
        of the same name in another document is not collapsed."""
        doc = self.standardDocument()
        header = [h for h in self.headers() if self.model().data(h) == "VarSet"][0]
        self.tree.setExpanded(header, False)
        other = self.newDocument("TestVariablesPanelOther")
        varSet = other.addObject("App::VarSet", "VarSet")
        varSet.addProperty("App::PropertyLength", "Pitch")
        Gui.setActiveDocument(other.Name)
        pump(0.3)
        self.assertEqual(set(self.rows()), {("VarSet", "Pitch")})
        self.assertTrue(self.tree.isExpanded(self.headers()[0]))
        Gui.setActiveDocument(doc.Name)
        pump(0.3)
        self.rows()
        header = [h for h in self.headers() if self.model().data(h) == "VarSet"][0]
        self.assertFalse(self.tree.isExpanded(header))


def writeExport(folder, name, variables):
    """A made-up Onshape export (notes/variables-studio.md section 0) of one studio entry:
    @a variables is a list of (type, name, expression)."""
    path = os.path.join(folder, name + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump([{"variableStudioReference": None, "variables": [
            {"type": kind, "name": var, "value": None, "description": "", "expression": text}
            for kind, var, text in variables]}], f)
    return path


class TestVariablesImportGui(unittest.TestCase):
    """The import dialog and the panel's "Import variables..." (ops#317 PR G1), with made-up
    exports: A uses #Gap, which only B defines (section 6, I-2, through the dialog)."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesImportGui")
        self.doc = App.newDocument("TestVariablesImport")
        self.doc.UndoMode = 1
        self.a = writeExport(self.folder, "Studio A", [("LENGTH", "Width", "#Gap * 2"),
                                                        ("LENGTH", "Height", "5 mm")])
        self.dialog = None

    def tearDown(self):
        from freecad.variables import copies

        copies._check_hook = None
        self.closeDialog()
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QDialog) and widget.isVisible():
                widget.reject()
        pump(0.1)
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        shutil.rmtree(self.folder, ignore_errors=True)

    def closeDialog(self):
        """Cancels the dialog if it is still there (it is deleted once closed)."""
        if self.dialog is not None and shiboken6.isValid(self.dialog):
            self.dialog.reject()
        self.dialog = None
        pump(0.1)

    def documentGap(self):
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyDistance", "Gap")
        variables.Gap = "7 mm"
        other = self.doc.addObject("App::VarSet", "Other")
        other.addProperty("App::PropertyDistance", "Alpha")
        self.doc.recompute()

    def open(self, paths):
        from freecad.variables import importgui

        self.dialog = importgui.run(self.doc, paths)
        self.assertIsNotNone(self.dialog)
        pump(0.1)
        return self.dialog

    def find(self, cls, name):
        widget = self.dialog.findChild(cls, name)
        self.assertIsNotNone(widget, name)
        return widget

    def choose(self, combo, data):
        index = combo.findData(data)
        self.assertGreaterEqual(index, 0, data)
        combo.setCurrentIndex(index)
        pump(0.05)

    def importNow(self):
        button = self.find(QtWidgets.QPushButton, "import")
        self.assertTrue(button.isEnabled(), self.find(QtWidgets.QPlainTextEdit, "report")
                        .toPlainText())
        button.click()
        self.assertTrue(waitFor(lambda: self.dialog.result is not None))
        pump(0.1)
        return self.dialog.result

    def test_use_document_variable(self):
        """A alone: Import is disabled and the report names #Gap and its user. The document
        variables are offered, Variables.Gap first, none preselected. Choosing it imports, and
        Bindings records it; one undo removes the copy."""
        self.documentGap()
        self.open([self.a])
        button = self.find(QtWidgets.QPushButton, "import")
        self.assertFalse(button.isEnabled())
        report = self.find(QtWidgets.QPlainTextEdit, "report").toPlainText()
        self.assertIn("#Gap is used by Width", report)
        choice = self.find(QtWidgets.QComboBox, "choice_Gap")
        self.assertIsNone(choice.currentData())
        variable = self.find(QtWidgets.QComboBox, "variable_Gap")
        offered = [variable.itemData(i) for i in range(variable.count())]
        self.assertEqual(offered, [None, "Variables.Gap", "Other.Alpha"])
        self.assertIsNone(variable.currentData())
        self.choose(choice, "use")
        self.assertFalse(button.isEnabled())  # chosen how, but not which
        self.choose(variable, "Variables.Gap")
        copy = self.importNow().copies[0]
        self.assertEqual(copy.Bindings, {"Gap": "Variables.Gap"})
        self.assertAlmostEqual(copy.Width.Value, 14)
        name = copy.Name
        self.doc.undo()
        self.assertIsNone(self.doc.getObject(name))

    def test_value_and_skip(self):
        """Enter a value: an input variable in a new "Variables" set. Skip: Width isn't
        imported, Height is."""
        self.open([self.a])
        self.choose(self.find(QtWidgets.QComboBox, "choice_Gap"), "value")
        self.choose(self.find(QtWidgets.QComboBox, "type_Gap"), "LENGTH")
        self.find(QtWidgets.QLineEdit, "value_Gap").setText("3 mm")
        pump(0.05)
        copy = self.importNow().copies[0]
        self.assertAlmostEqual(self.doc.getObject("Variables").Gap.Value, 3)
        self.assertAlmostEqual(copy.Width.Value, 6)
        self.doc.undo()
        self.assertEqual(self.doc.Objects, [])

        self.closeDialog()
        self.open([self.a])
        self.choose(self.find(QtWidgets.QComboBox, "choice_Gap"), "skip")
        copy = self.importNow().copies[0]
        self.assertNotIn("Width", copy.PropertiesList)
        self.assertAlmostEqual(copy.Height.Value, 5)
        self.assertEqual(copy.Skipped, ["Gap"])

    def test_several_files(self):
        """A and B together: no choice needed, A's Width uses B's Gap."""
        b = writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm")])
        self.open([self.a, b])
        copyA, copyB = self.importNow().copies
        self.assertAlmostEqual(copyA.Width.Value, 6)
        self.assertIn(copyB.Name + ".Gap", expressionText(copyA, "Width").replace(" ", ""))

    def test_provider(self):
        """A name two files define: Import waits for the file that provides it."""
        b = writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm")])
        c = writeExport(self.folder, "Studio C", [("LENGTH", "Gap", "4 mm")])
        self.open([self.a, b, c])
        self.assertFalse(self.find(QtWidgets.QPushButton, "import").isEnabled())
        self.choose(self.find(QtWidgets.QComboBox, "provider_Gap"), 2)
        copyA = self.importNow().copies[0]
        self.assertAlmostEqual(copyA.Width.Value, 8)

    def test_names(self):
        """Names FreeCAD can't use are listed with their proposals, editable: Label -> Lbl by
        hand; a name FreeCAD refuses (cos) disables Import. Unit names (t, H) aren't listed:
        they are usable as they are (ops#640, rank 54)."""
        path = writeExport(self.folder, "Units", [("LENGTH", "t", "2 mm"),
                                                   ("LENGTH", "H", "#t * 3"),
                                                   ("LENGTH", "Label", "3 mm"),
                                                   ("LENGTH", "Wall", "#Label * 4")])
        self.open([path])
        names = self.find(QtWidgets.QTableWidget, "names")
        table = {names.item(r, 0).text(): names.item(r, 1) for r in range(names.rowCount())}
        self.assertEqual({k: v.text() for k, v in table.items()}, {"Label": "Label_"})
        table["Label"].setText("cos")
        pump(0.05)
        self.assertFalse(self.find(QtWidgets.QPushButton, "import").isEnabled())
        table["Label"].setText("Lbl")
        copy = self.importNow().copies[0]
        self.assertEqual(copy.NameMap, {"Label": "Lbl"})
        self.assertAlmostEqual(copy.H.Value, 6)
        self.assertAlmostEqual(copy.Wall.Value, 12)

    def test_file_import_type(self):
        """File > Import knows "Onshape variables (*.json)"; its module opens the dialog."""
        self.assertIn("freecad.variables.importer", App.getImportType("json"))
        from freecad.variables import importer, importgui

        importer.insert(self.a, self.doc.Name)
        pump(0.1)
        self.dialog = importgui._open[-1]
        self.assertEqual(self.dialog.paths, [os.path.abspath(self.a)])
        self.assertTrue(self.dialog.isVisible())

    def test_panel(self):
        """The panel's "Import variables..." is enabled with a document; a copied variable's
        cells aren't editable, and Add doesn't put a variable in a copy."""
        b = writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm")])
        from freecad.variables import copies

        copies.import_studios(self.doc, [b])
        view = panel()
        dock = dockOf(view)
        dock.show()
        Gui.setActiveDocument(self.doc.Name)
        pump(0.3)
        action = view.findChild(QtGui.QAction, "importVariables")
        self.assertIsNotNone(action)
        self.assertTrue(action.isEnabled())
        tree = view.findChild(QtWidgets.QTreeView, "variablesTree")
        model = tree.model()
        self.assertTrue(waitFor(lambda: model.rowCount() == 1))
        header = model.index(0, 0)
        row = model.index(0, NAME, header)
        self.assertEqual(model.data(row), "Gap")
        for column in (NAME, EXPRESSION, DESCRIPTION):
            flags = model.flags(row.sibling(0, column))
            self.assertFalse(flags & QtCore.Qt.ItemIsEditable, column)
        dock.hide()

    # PR 317 round 1

    def clickImport(self):
        self.find(QtWidgets.QPushButton, "import").click()

    def test_failure_shown(self):
        """A failed check (the test hook moves Width's value), then any other error during the
        import (the hook raises): each is shown in a message box, nothing is left, no "Import"
        step is on the undo stack, and the dialog stays open (review 317, 4 and 10)."""
        from freecad.variables import copies

        b = writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm")])
        shown = []
        with mock.patch.object(QtWidgets.QMessageBox, "critical",
                               lambda *args: shown.append(args[2])):
            for hook in (lambda var, value: copies.Quantity(value.value * 2, value.dims),
                         lambda var, value: 1 / 0):
                copies._check_hook = hook
                self.open([self.a, b])
                self.clickImport()
                self.assertTrue(waitFor(lambda: len(shown) == 1), "no message box")
                self.assertEqual(self.doc.Objects, [])
                self.assertFalse([n for n in self.doc.UndoNames if n.startswith("Import")])
                self.assertTrue(shiboken6.isValid(self.dialog) and self.dialog.isVisible())
                self.assertIsNone(self.dialog.result)
                shown.clear()
                self.closeDialog()

    def test_same_named_providers(self):
        """Two exports of the same name in different folders both define #Gap: the provider's
        entries can be told apart (review 317, 3)."""
        paths = []
        for folder in ("one", "two"):
            os.mkdir(os.path.join(self.folder, folder))
            paths.append(writeExport(os.path.join(self.folder, folder), "Studio B",
                                     [("LENGTH", "Gap", "3 mm")]))
        self.open([self.a] + paths)
        combo = self.find(QtWidgets.QComboBox, "provider_Gap")
        texts = [combo.itemText(i) for i in range(1, combo.count())]
        self.assertEqual(len(texts), 2)
        self.assertNotEqual(texts[0], texts[1])
        for text, folder in zip(texts, ("one", "two")):
            self.assertIn("/" + folder + "/", text)

    def test_default_unit(self):
        """A Length without a unit waits for the Onshape document's default unit; choosing
        inches imports 5 as 127 mm (review 317, 5)."""
        path = writeExport(self.folder, "Plain", [("LENGTH", "Size", "5")])
        self.open([path])
        self.assertFalse(self.find(QtWidgets.QPushButton, "import").isEnabled())
        self.assertIn("default unit", self.find(QtWidgets.QPlainTextEdit, "report").toPlainText())
        self.choose(self.find(QtWidgets.QComboBox, "defaultUnit_LENGTH"), "in")
        copy = self.importNow().copies[0]
        self.assertAlmostEqual(copy.Size.Value, 127)

    def test_skip_refused(self):
        """A refused variable gets a Skip box; skipping it imports the rest (review 317, 5)."""
        path = writeExport(self.folder, "Mixed", [("NUMBER", "Bad", "round(2.5, 1)"),
                                                  ("LENGTH", "Good", "5 mm")])
        self.open([path])
        self.assertFalse(self.find(QtWidgets.QPushButton, "import").isEnabled())
        self.find(QtWidgets.QCheckBox, "skip_Bad").setChecked(True)
        pump(0.05)
        copy = self.importNow().copies[0]
        self.assertNotIn("Bad", copy.PropertiesList)
        self.assertAlmostEqual(copy.Good.Value, 5)
        self.assertEqual(copy.Skipped, ["Bad"])

    def test_skip_cycle(self):
        """A.x uses B.y and B.z uses A.w: x and z get Skip boxes; skipping z imports both
        copies (review 317, 5)."""
        a = writeExport(self.folder, "Cycle A", [("LENGTH", "x", "#y + 1 mm"),
                                                 ("LENGTH", "w", "2 mm")])
        b = writeExport(self.folder, "Cycle B", [("LENGTH", "y", "3 mm"),
                                                 ("LENGTH", "z", "#w * 2")])
        self.open([a, b])
        self.assertFalse(self.find(QtWidgets.QPushButton, "import").isEnabled())
        self.find(QtWidgets.QCheckBox, "skip_x")
        self.find(QtWidgets.QCheckBox, "skip_z").setChecked(True)
        pump(0.05)
        copyA, copyB = self.importNow().copies
        self.assertAlmostEqual(copyA.x.Value, 4)
        self.assertNotIn("z", copyB.PropertiesList)

    def test_value_for_unit_name(self):
        """A value for #Label, a name FreeCAD can't use (every set has a Label): the names table
        proposes Label_, editable, as for a copy's variable (review 317, 6). (#t, a unit name,
        is usable since ops#640 rank 54.)"""
        path = writeExport(self.folder, "Thin", [("LENGTH", "Width", "#Label * 2")])
        self.open([path])
        self.choose(self.find(QtWidgets.QComboBox, "choice_Label"), "value")
        self.choose(self.find(QtWidgets.QComboBox, "type_Label"), "LENGTH")
        self.find(QtWidgets.QLineEdit, "value_Label").setText("3 mm")
        pump(0.05)
        names = self.find(QtWidgets.QTableWidget, "names")
        self.assertTrue(names.isVisibleTo(self.dialog))
        table = {names.item(r, 0).text(): names.item(r, 1) for r in range(names.rowCount())}
        self.assertEqual({k: v.text() for k, v in table.items()}, {"Label": "Label_"})
        table["Label"].setText("Thick")
        pump(0.05)
        copy = self.importNow().copies[0]
        self.assertAlmostEqual(self.doc.getObject("Variables").Thick.Value, 3)
        self.assertEqual(copy.Bindings, {"Label": "Variables.Thick"})
        self.assertAlmostEqual(copy.Width.Value, 6)

    def test_dialog_freed(self):
        """A closed dialog is deleted and forgotten (review 317, 8)."""
        from freecad.variables import importgui

        dialog = self.open([self.a])
        self.assertIn(dialog, importgui._open)
        dialog.reject()
        self.assertTrue(waitFor(lambda: not shiboken6.isValid(dialog)), "not deleted")
        self.assertNotIn(dialog, importgui._open)
        self.dialog = None

    def test_open_cancelled(self):
        """File > Open of an export makes a document for it; cancelling the dialog closes that
        document again (review 317, 7)."""
        from freecad.variables import importer, importgui

        before = set(App.listDocuments())
        importer.open(self.a)
        pump(0.1)
        new = set(App.listDocuments()) - before
        self.assertEqual(len(new), 1)
        self.dialog = importgui._open[-1]
        self.closeDialog()
        self.assertTrue(waitFor(lambda: not (new & set(App.listDocuments()))),
                        "the new document is still open")

    def panelWithCopy(self):
        """The panel on a document with an attached copy of Studio B (Gap), its row current."""
        b = writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm")])
        from freecad.variables import copies

        copy = copies.import_studios(self.doc, [b]).copies[0]
        view = panel()
        dock = dockOf(view)
        dock.show()
        Gui.setActiveDocument(self.doc.Name)
        pump(0.3)
        tree = view.findChild(QtWidgets.QTreeView, "variablesTree")
        model = tree.model()
        self.assertTrue(waitFor(lambda: model.rowCount() == 1))
        tree.setCurrentIndex(model.index(0, NAME, model.index(0, 0)))
        pump(0.1)

        def action(name):
            found = [a for a in view.findChildren(QtGui.QAction, name)]
            self.assertTrue(found, name)
            return found[0]

        return view, tree, copy, action

    def test_panel_copy_rows_locked(self):
        """Delete and Edit description are disabled on an attached copy's variable; Show uses
        isn't (review 317, 2)."""
        view, _tree, _copy, action = self.panelWithCopy()
        self.assertFalse(action("deleteVariable").isEnabled())
        self.assertFalse(action("editDescription").isEnabled())
        self.assertTrue(action("showUses").isEnabled())
        dockOf(view).hide()

    def test_panel_add_refuses_copy(self):
        """An attached copy is no Add target: not among the Add dialog's sets, and refused if
        named anyway (review 317, 1)."""
        view, _tree, copy, action = self.panelWithCopy()
        action("addVariable").trigger()
        dialog = waitFor(lambda: [w for w in QtWidgets.QApplication.topLevelWidgets()
                                  if w.objectName() == "addVariableDialog" and w.isVisible()])
        self.assertTrue(dialog, "no Add variable dialog")
        dialog = dialog[0]
        setBox = dialog.findChild(QtWidgets.QComboBox, "set")
        self.assertEqual([setBox.itemText(i) for i in range(setBox.count())],
                         ["Variables (new)"])
        # named anyway (as a stale entry would): refused, nothing added
        setBox.addItem(copy.Label, copy.Name)
        setBox.setCurrentIndex(setBox.count() - 1)
        dialog.findChild(QtWidgets.QLineEdit, "name").setText("Extra")
        dialog.findChild(QtWidgets.QLineEdit, "value").setText("1 mm")
        dialog.findChild(QtWidgets.QDialogButtonBox).button(
            QtWidgets.QDialogButtonBox.Ok).click()
        pump(0.2)
        self.assertNotIn("Extra", copy.PropertiesList)
        self.assertIsNone(self.doc.getObject("Variables"))
        error = dialog.findChild(QtWidgets.QLabel, "error")
        self.assertTrue(error.isVisible())
        self.assertIn("copy", error.text())
        dialog.reject()
        dockOf(view).hide()


# The panel's roles on a copy's header (src/Gui/VariablesView.cpp, ops#640 round 5)
CopyStateRole = QtCore.Qt.UserRole + 20
CopyMessageRole = QtCore.Qt.UserRole + 21


class TestVariablesRefreshGui(unittest.TestCase):
    """A copy's state in the panel, the Refresh preview, Locate and "Copy from FreeCAD file..."
    (ops#317 PRs G2 and F, ops#640 round 5; notes/variables-studio.md 3.2-3.4, section 6 G-4).
    Every source is made up here."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesRefreshGui")
        self.doc = App.newDocument("TestVariablesRefreshGui")
        self.doc.UndoMode = 1
        self.other = App.newDocument("TestVariablesRefreshGuiOther")
        self.path = writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm")])
        from freecad.variables import copies

        self.copy = copies.import_studios(self.doc, [self.path]).copies[0]
        self.view = panel()
        self.dock = dockOf(self.view)
        self.dock.show()
        Gui.setActiveDocument(self.doc.Name)
        self.tree = self.view.findChild(QtWidgets.QTreeView, "variablesTree")
        self.model = self.tree.model()
        self.assertTrue(waitFor(lambda: self.model.rowCount() == 1))

    def tearDown(self):
        from freecad.variables import copies, importgui

        copies._check_hook = None
        for dialog in list(importgui._open):
            if shiboken6.isValid(dialog):
                dialog.reject()
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QDialog) and widget.isVisible():
                widget.reject()
        pump(0.1)
        for name in (self.doc.Name, self.other.Name):
            if name in App.listDocuments():
                App.closeDocument(name)
        self.dock.hide()
        pump(0.1)
        shutil.rmtree(self.folder, ignore_errors=True)

    def rewrite(self, variables):
        writeExport(self.folder, "Studio B", variables)
        later = os.stat(self.path).st_mtime + 10
        os.utime(self.path, (later, later))

    def recheck(self):
        """Another document active and back: the panel rebuilds and checks the states again."""
        Gui.setActiveDocument(self.other.Name)
        pump(0.2)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.3)

    def header(self):
        return self.model.index(0, 0)

    def action(self, name):
        found = self.view.findChildren(QtGui.QAction, name)
        self.assertTrue(found, name)
        return found[0]

    def planDialog(self):
        from freecad.variables import importgui

        self.assertTrue(waitFor(lambda: importgui._open and importgui._open[-1].isVisible()),
                        "no dialog")
        return importgui._open[-1]

    def apply(self, dialog):
        button = dialog.findChild(QtWidgets.QPushButton, "apply")
        self.assertTrue(button.isEnabled(),
                        dialog.findChild(QtWidgets.QPlainTextEdit, "report").toPlainText())
        button.click()
        self.assertTrue(waitFor(lambda: dialog.result is not None))
        pump(0.3)
        return dialog.result

    def test_states(self):
        """G-4. The header of an attached copy shows its state: up to date (the label alone),
        out of date after the JSON changed on disk, not found once it is gone; the message is
        its tooltip and a role."""
        self.assertEqual(self.model.data(self.header()), "Studio B")
        self.assertEqual(self.model.data(self.header(), CopyStateRole), "up to date")
        self.assertIn("Up to date with Studio B.json",
                      self.model.data(self.header(), QtCore.Qt.ToolTipRole))
        self.rewrite([("LENGTH", "Gap", "4 mm")])
        self.recheck()
        self.assertEqual(self.model.data(self.header()), "Studio B (out of date)")
        self.assertEqual(self.model.data(self.header(), CopyStateRole), "out of date")
        self.assertIn("changed since the last Refresh",
                      self.model.data(self.header(), CopyMessageRole))
        os.remove(self.path)
        self.recheck()
        self.assertEqual(self.model.data(self.header()), "Studio B (source not found)")
        self.assertIn("Locate", self.model.data(self.header(), CopyMessageRole))

    def test_actions_enabled(self):
        """Refresh and Locate need an attached copy's row; Copy from FreeCAD file a document."""
        self.tree.setCurrentIndex(self.model.index(0, NAME, self.header()))
        pump(0.1)
        self.assertTrue(self.action("refreshCopy").isEnabled())
        self.assertTrue(self.action("locateSource").isEnabled())
        self.assertTrue(self.action("copyFromFreeCAD").isEnabled())
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyLength", "Plain")
        self.doc.recompute()
        pump(0.3)
        for row in range(self.model.rowCount()):
            if self.model.data(self.model.index(row, 0)) == "Variables":
                self.tree.setCurrentIndex(self.model.index(row, 0))
        pump(0.1)
        self.assertFalse(self.action("refreshCopy").isEnabled())

    def test_refresh_preview(self):
        """The panel's Refresh shows the preview (the summary, each change); its Refresh button
        applies it as one undo step and the header is up to date again."""
        self.rewrite([("LENGTH", "Gap", "4 mm"), ("LENGTH", "Rail", "#Gap * 2")])
        self.recheck()
        self.tree.setCurrentIndex(self.header())
        pump(0.1)
        undo = self.doc.UndoCount
        self.action("refreshCopy").trigger()
        dialog = self.planDialog()
        self.assertEqual(dialog.findChild(QtWidgets.QLabel, "summary").text(),
                         "Added 1, changed 1")
        report = dialog.findChild(QtWidgets.QPlainTextEdit, "report").toPlainText()
        self.assertIn("Added: Rail", report)
        self.assertIn("Changed: Gap", report)
        self.apply(dialog)
        self.assertAlmostEqual(self.copy.Gap.Value, 4)
        self.assertAlmostEqual(self.copy.Rail.Value, 8)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(waitFor(
            lambda: self.model.data(self.model.index(0, 0), CopyStateRole) == "up to date"))

    def test_refresh_choice(self):
        """A variable added at the source using a name nothing defines: Refresh waits for a
        choice; Skip lets it go on."""
        self.rewrite([("LENGTH", "Gap", "3 mm"), ("LENGTH", "Far", "#Missing * 2")])
        from freecad.variables import importgui

        dialog = importgui.refresh(self.copy)
        pump(0.1)
        button = dialog.findChild(QtWidgets.QPushButton, "apply")
        self.assertFalse(button.isEnabled())
        choice = dialog.findChild(QtWidgets.QComboBox, "choice_Missing")
        self.assertIsNotNone(choice)
        choice.setCurrentIndex(choice.findData("skip"))
        pump(0.05)
        self.apply(dialog)
        self.assertNotIn("Far", self.copy.PropertiesList)
        self.assertEqual(self.copy.Skipped, ["Missing"])

    def test_orphan_flag(self):
        """A variable removed at the source that User still uses stays as an orphan, flagged in
        its row's Source column (design 3.4, D2)."""
        user = self.doc.addObject("App::VarSet", "User")
        user.addProperty("App::PropertyDistance", "Len")
        user.setExpression("Len", "Studio_B.Gap * 2")
        self.doc.recompute()
        self.rewrite([("LENGTH", "Other", "1 mm")])
        from freecad.variables import copies

        copies.refresh(self.copy)
        pump(0.3)
        self.recheck()
        found = None
        for row in range(self.model.rowCount(self.header())):
            if self.model.data(self.model.index(row, NAME, self.header())) == "Gap":
                found = self.model.data(self.model.index(row, SOURCE, self.header()))
        self.assertEqual(found, "Studio B: removed at the source; used by User")

    def test_locate(self):
        """Locate to a renamed copy of the file: the preview, then the copy follows that file."""
        moved = os.path.join(self.folder, "Studio B moved.json")
        shutil.copy(self.path, moved)
        os.remove(self.path)
        from freecad.variables import importgui

        dialog = importgui.locate(self.copy, moved)
        self.apply(dialog)
        self.assertEqual(self.copy.SourcePath, os.path.abspath(moved).replace(os.sep, "/"))
        self.recheck()
        self.assertEqual(self.model.data(self.model.index(0, 0), CopyStateRole), "up to date")

    def test_copy_from_freecad_file(self):
        """Copy from FreeCAD file: a saved document's VarSet, read without opening it; the dialog
        offers its saved value for a reference outside the set, and Copy makes the copy."""
        source = App.newDocument("TestVariablesRefreshGuiSource")
        dims = source.addObject("App::VarSet", "Dims")
        dims.addProperty("App::PropertyLength", "L")
        dims.L = 40
        master = source.addObject("App::VarSet", "Master")
        master.addProperty("App::PropertyDistance", "Depth")
        master.setExpression("Depth", "Dims.L / 2")
        source.recompute()
        path = os.path.join(self.folder, "Master.FCStd")
        source.saveAs(path)
        App.closeDocument(source.Name)
        from freecad.variables import importgui

        dialog = importgui.copy_from_file(self.doc, path, "Master")
        pump(0.1)
        self.assertFalse(dialog.findChild(QtWidgets.QPushButton, "apply").isEnabled())
        choice = dialog.findChild(QtWidgets.QComboBox, "choice_Dims.L")
        self.assertIsNotNone(choice)
        choice.setCurrentIndex(choice.findData("freeze"))
        pump(0.05)
        copy = self.apply(dialog)
        self.assertEqual(copy.SourceKind, "FreeCAD document")
        self.assertAlmostEqual(copy.Depth.Value, 20)
        self.assertNotIn(path.replace(os.sep, "/"),
                         [d.FileName for d in App.listDocuments().values()])


class TestVariablesClashGui(unittest.TestCase):
    """A local variable and an imported one of the same name (ops#640, decision 317): the
    panel's Add asks which one `#name` means before it makes the variable ("Use <source>", "Use
    local", "Pick...", Cancel); the import and Refresh dialogs list the clashing names with
    "Use <source>", "Use local" and "Pick" (per name), and wait for a choice. Made-up exports."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="TestVariablesClashGui")
        self.doc = App.newDocument("TestVariablesClashGui")
        self.doc.UndoMode = 1
        self.path = writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm")])
        self.view = panel()
        self.dock = dockOf(self.view)
        self.dock.show()
        Gui.setActiveDocument(self.doc.Name)
        self.tree = self.view.findChild(QtWidgets.QTreeView, "variablesTree")
        self.model = self.tree.model()
        pump(0.2)

    def tearDown(self):
        from freecad.variables import importgui

        for dialog in list(importgui._open):
            if shiboken6.isValid(dialog):
                dialog.reject()
        for widget in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(widget, QtWidgets.QDialog) and widget.isVisible():
                widget.reject()
        pump(0.1)
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        self.dock.hide()
        pump(0.1)
        shutil.rmtree(self.folder, ignore_errors=True)

    def imported(self):
        """Studio B (Gap = 3 mm) as a copy, and User.Len = Studio_B.Gap * 2 made before any
        clash."""
        from freecad.variables import copies

        copy = copies.import_studios(self.doc, [self.path]).copies[0]
        self.user = self.doc.addObject("App::VarSet", "User")
        self.user.addProperty("App::PropertyDistance", "Len")
        self.user.setExpression("Len", "#Gap * 2")
        self.doc.recompute()
        self.assertEqual(expressionText(self.user, "Len"), "Studio_B.Gap * 2")
        pump(0.3)
        return copy

    def shown(self, holder, name):
        """The panel's Expression cell of @a holder's (label) variable @a name."""
        pump(0.4)
        for row in range(self.model.rowCount()):
            header = self.model.index(row, 0)
            if self.model.data(header) != holder:
                continue
            for child in range(self.model.rowCount(header)):
                if self.model.data(self.model.index(child, NAME, header)) == name:
                    return self.model.data(self.model.index(child, EXPRESSION, header))
        return None

    def add(self, name, value, answer, pick=None):
        """The panel's Add with a Length @a name = @a value; the clash question answered with
        the button named @a answer ("Pick..." then picks the item containing @a pick). Returns
        the Add dialog and the question's text (None: not asked)."""
        self.action("addVariable").trigger()
        found = waitFor(lambda: [w for w in QtWidgets.QApplication.topLevelWidgets()
                                 if w.objectName() == "addVariableDialog" and w.isVisible()])
        self.assertTrue(found, "no Add variable dialog")
        dialog = found[0]
        dialog.findChild(QtWidgets.QLineEdit, "name").setText(name)
        typeBox = dialog.findChild(QtWidgets.QComboBox, "type")
        typeBox.setCurrentIndex(typeBox.findText("Length"))
        dialog.findChild(QtWidgets.QLineEdit, "value").setText(value)
        texts = []

        def answerPick():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(widget, QtWidgets.QInputDialog) and widget.isVisible():
                    items = [i for i in widget.comboBoxItems() if pick in i]
                    widget.setTextValue(items[0])
                    widget.accept()
                    return
            QtCore.QTimer.singleShot(50, answerPick)

        def answerBox(tries=[0]):
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(widget, QtWidgets.QMessageBox) and widget.objectName() == "nameClash":
                    texts.append(widget.text())
                    texts.append([b.text() for b in widget.buttons()])
                    if pick is not None:
                        QtCore.QTimer.singleShot(50, answerPick)
                    if answer == "cancel":
                        widget.button(QtWidgets.QMessageBox.Cancel).click()
                    else:
                        widget.findChild(QtWidgets.QPushButton, answer).click()
                    return
            tries[0] += 1
            if tries[0] < 40:
                QtCore.QTimer.singleShot(50, answerBox)

        if answer is not None:
            QtCore.QTimer.singleShot(50, answerBox)
        ok = dialog.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok)
        ok.click()  # direct: the name-clash box's exec() runs here, where answerBox's timer fires (see pump)
        if answer is not None:
            self.assertTrue(waitFor(lambda: texts), "no question about the name")
        pump(0.4)
        return dialog, (texts or [None, None])

    def action(self, name):
        found = self.view.findChildren(QtGui.QAction, name)
        self.assertTrue(found, name)
        return found[0]

    def probe(self, text="#Gap"):
        """The path a new expression's @a text gets."""
        probe = self.doc.getObject("Probe") or self.doc.addObject("App::VarSet", "Probe")
        if "Len" not in probe.PropertiesList:
            probe.addProperty("App::PropertyDistance", "Len")
        probe.setExpression("Len", text)
        return expressionText(probe, "Len")

    def test_add_use_local(self):
        """Adding Gap where Studio B defines it: asked first, naming the copy and its file;
        "Use local" makes it with the choice in one undo step. `#Gap` then means the local one
        and is shown so; User keeps Studio B's Gap, shown by its full path."""
        copy = self.imported()
        undo = self.doc.UndoCount
        _dialog, (text, buttons) = self.add("Gap", "7 mm", "useLocal")
        self.assertIn("#Gap is already imported: Studio B (Studio B.json)", text)
        self.assertIn("Existing expressions keep the variable they use", text)
        self.assertLessEqual({"Use Studio B.json", "Use local", "Pick..."}, set(buttons))
        local = self.doc.getObject("Variables")
        self.assertIsNotNone(local)
        self.assertAlmostEqual(local.Gap.Value, 7)
        self.assertEqual(copy.Bindings, {"#Gap": "Variables.Gap"})
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.probe(), "Variables.Gap")
        self.assertEqual(self.shown("Probe", "Len"), "#Gap")
        self.assertEqual(self.shown("User", "Len"), "Studio_B.Gap * 2")
        self.doc.removeObject("Probe")
        self.doc.undo()
        self.assertIsNone(self.doc.getObject("Variables"))
        self.assertEqual(copy.Bindings, {})
        self.assertEqual(self.shown("User", "Len"), "#Gap * 2")

    def test_add_use_import(self):
        """"Use Studio B.json": the local Gap is made, `#Gap` keeps meaning the copy's."""
        copy = self.imported()
        self.add("Gap", "7 mm", "useImport")
        self.assertAlmostEqual(self.doc.getObject("Variables").Gap.Value, 7)
        self.assertEqual(copy.Bindings, {"#Gap": "Studio_B.Gap"})
        self.assertEqual(self.probe(), "Studio_B.Gap")
        self.assertEqual(self.shown("User", "Len"), "#Gap * 2")
        self.assertEqual(self.shown("Probe", "Len"), "#Gap")

    def test_add_pick(self):
        """"Pick...": a list of the new local variable and the copy's; the copy picked."""
        copy = self.imported()
        self.add("Gap", "7 mm", "pick", pick="Studio B.json")
        self.assertIsNotNone(self.doc.getObject("Variables"))
        self.assertEqual(copy.Bindings, {"#Gap": "Studio_B.Gap"})

    def test_add_cancel(self):
        """Cancel: nothing is made, and the Add dialog stays open with what was typed."""
        copy = self.imported()
        undo = self.doc.UndoCount
        dialog, _text = self.add("Gap", "7 mm", "cancel")
        self.assertIsNone(self.doc.getObject("Variables"))
        self.assertEqual(copy.Bindings, {})
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.findChild(QtWidgets.QLineEdit, "name").text(), "Gap")
        dialog.reject()

    def test_add_no_clash(self):
        """A name no copy defines: no question."""
        self.imported()
        self.add("Rail", "2 mm", None)
        self.assertAlmostEqual(self.doc.getObject("Variables").Rail.Value, 2)
        self.assertFalse([w for w in QtWidgets.QApplication.topLevelWidgets()
                          if w.objectName() == "nameClash" and w.isVisible()])

    def localGap(self):
        local = self.doc.addObject("App::VarSet", "Variables")
        local.addProperty("App::PropertyDistance", "Gap")
        local.Gap = "7 mm"
        self.doc.recompute()
        return local

    def importDialog(self):
        from freecad.variables import importgui

        dialog = importgui.run(self.doc, [self.path])
        pump(0.2)
        return dialog

    def clickImport(self, dialog):
        button = dialog.findChild(QtWidgets.QPushButton, "import")
        self.assertTrue(button.isEnabled(),
                        dialog.findChild(QtWidgets.QPlainTextEdit, "report").toPlainText())
        button.click()
        self.assertTrue(waitFor(lambda: dialog.result is not None))
        pump(0.2)
        return dialog.result.copies[0]

    def test_import_use_local(self):
        """Importing Studio B where Variables defines Gap: the clash box lists it, Import waits
        for a choice; "Use local" imports with the choice recorded."""
        self.localGap()
        dialog = self.importDialog()
        box = dialog.findChild(QtWidgets.QGroupBox, "clashes")
        self.assertTrue(box.isVisible())
        self.assertIn("#Gap: Variables.Gap", dialog.findChild(QtWidgets.QLabel, "clashNote").text())
        self.assertEqual(dialog.findChild(QtWidgets.QRadioButton, "useImport").text(),
                         "Use Studio B.json")
        self.assertFalse(dialog.findChild(QtWidgets.QPushButton, "import").isEnabled())
        dialog.findChild(QtWidgets.QRadioButton, "useLocal").setChecked(True)
        pump(0.1)
        copy = self.clickImport(dialog)
        self.assertEqual(copy.Bindings, {"#Gap": "Variables.Gap"})
        self.assertEqual(self.probe(), "Variables.Gap")

    def test_import_pick(self):
        """"Pick": a row per name, Import waits until each has its choice."""
        self.localGap()
        dialog = self.importDialog()
        dialog.findChild(QtWidgets.QRadioButton, "pick").setChecked(True)
        pump(0.1)
        combo = dialog.findChild(QtWidgets.QComboBox, "clash_Gap")
        self.assertTrue(combo.isVisible())
        self.assertEqual([combo.itemData(i) for i in range(combo.count())],
                         [None, "Variables.Gap", "Studio_B.Gap"])
        self.assertFalse(dialog.findChild(QtWidgets.QPushButton, "import").isEnabled())
        combo.setCurrentIndex(combo.findData("Studio_B.Gap"))
        pump(0.1)
        copy = self.clickImport(dialog)
        self.assertEqual(copy.Bindings, {"#Gap": "Studio_B.Gap"})
        self.assertEqual(self.probe(), "Studio_B.Gap")

    def test_refresh_new_clash(self):
        """A Refresh that brings Rail, which Variables defines: the preview's clash box, and
        Refresh waits for a choice; "Use Studio B.json" records it."""
        copy = self.imported()
        local = self.doc.addObject("App::VarSet", "Variables")
        local.addProperty("App::PropertyDistance", "Rail")
        self.doc.recompute()
        writeExport(self.folder, "Studio B", [("LENGTH", "Gap", "3 mm"),
                                              ("LENGTH", "Rail", "#Gap * 3")])
        later = os.stat(self.path).st_mtime + 10
        os.utime(self.path, (later, later))
        from freecad.variables import importgui

        dialog = importgui.refresh(copy)
        pump(0.2)
        self.assertTrue(dialog.findChild(QtWidgets.QGroupBox, "clashes").isVisible())
        apply = dialog.findChild(QtWidgets.QPushButton, "apply")
        self.assertFalse(apply.isEnabled())
        dialog.findChild(QtWidgets.QRadioButton, "useImport").setChecked(True)
        pump(0.1)
        self.assertTrue(apply.isEnabled(),
                        dialog.findChild(QtWidgets.QPlainTextEdit, "report").toPlainText())
        apply.click()
        self.assertTrue(waitFor(lambda: dialog.result is not None))
        pump(0.2)
        self.assertEqual(copy.Bindings, {"#Rail": "Studio_B.Rail"})
        self.assertAlmostEqual(copy.Rail.Value, 9)
        self.assertEqual(self.probe("#Rail"), "Studio_B.Rail")
