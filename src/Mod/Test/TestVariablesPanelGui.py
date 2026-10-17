# SPDX-License-Identifier: LGPL-2.1-or-later

"""The Variables panel (FreeCAD-CH, ops#152, notes/variables-design.md section 3.6).

A dock window lists the active document's VarSet variables and sheet aliases under one header row
per source. Editing a row's Name renames the variable and editing its Expression sets the value or
the expression, each as one undo step; Add and Delete work from its toolbar. G1-G7, G9, G17 and G18
of the design note; since ops#317 PR B the Type and Description columns and the panel's own Add
dialog (G-1 to G-3 of notes/variables-studio.md). Each test builds its own document."""

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
NAME, TYPE, EXPRESSION, VALUE, DESCRIPTION, SOURCE = range(6)


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
        QtCore.QTimer.singleShot(0, other.click)
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
            ("t", "Length", "2 mm", "is a unit"),
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
