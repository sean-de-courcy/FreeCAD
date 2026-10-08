# SPDX-License-Identifier: LGPL-2.1-or-later

"""The Variables panel (FreeCAD-CH, ops#152, notes/variables-design.md section 3.6).

A dock window lists the active document's VarSet variables and sheet aliases under one header row
per source. Editing a row's Name renames the variable and editing its Expression sets the value or
the expression, each as one undo step; Add and Delete work from its toolbar. G1-G7, G9, G17 and G18
of the design note. Each test builds its own document."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets
from PySide6.QtTest import QTest

# VariablesModel's roles and columns (src/Gui/VariablesView.h)
KindRole = QtCore.Qt.UserRole + 1
VariableRole = QtCore.Qt.UserRole + 4
EditTextRole = QtCore.Qt.UserRole + 6
NAME, EXPRESSION, VALUE, SOURCE = range(4)


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
        """G18. The "Variables" dock exists and is hidden; its toggle action is in View > Panels,
        and triggering it shows the dock."""
        dock = dockOf(self.panel)
        self.assertIsNotNone(dock)
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
        stays, one undo step; Undo brings the name and the texts back. Bad names change nothing."""
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

        for bad in ("mm", "Height", "A1"):
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
        """G5. Delete lists the uses (T10's set), deletes on OK, and the Box fails at recompute;
        Undo restores the variable and the Box is valid at 40 mm."""
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
        doc.recompute()
        self.assertIn("Invalid", self.box.State)

        doc.undo()
        self.assertIn("Width", self.varSet.PropertiesList)
        doc.recompute()
        self.assertNotIn("Invalid", self.box.State)
        self.assertAlmostEqual(self.box.Length.Value, 40)

    def openAddDialog(self):
        self.action("addVariable").trigger()
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
        """G6. In an empty document, Add creates the "Variables" VarSet in its own undo step, and
        the dialog adds Height = 12 mm (Length, the default type) in a second one."""
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
        doc.recompute()
        self.assertIn("Invalid", self.box.State)

    def test_delete_own_use(self):
        """`Depth = .Width * 2` in the VarSet itself: Delete lists VarSet.Depth, and the VarSet
        fails at the next recompute."""
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
        doc.recompute()
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
        self.assertEqual(doc.UndoCount, undoCount + 1)
        self.assertEqual(doc.UndoNames[0], "Outer")

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
