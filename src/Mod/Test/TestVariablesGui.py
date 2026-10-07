# SPDX-License-Identifier: LGPL-2.1-or-later

"""Variables in the GUI: `#name` at the display and editor sites (FreeCAD-CH, ops#152).

notes/variables-design.md section 8: wherever the GUI shows an expression's text, or lets the user
edit it, a reference to a variable reads `#Width`; what is stored, recorded or copied out stays the
full path. Each test builds a document with a VarSet `VarSet` (Width = 20 mm), a Box whose Length is
`VarSet.Width * 2`, and whatever else it needs. G11-G16 of the design note."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets
from PySide6.QtTest import QTest


def pump(seconds=0.5):
    """Processes events for a while: the property view fills on a timer."""
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


def widgetsOfClass(parent, cls, className):
    return [w for w in parent.findChildren(cls) if w.metaObject().className() == className]


class PaintCounter(QtCore.QObject):
    """Counts the paint and update requests a widget gets."""

    def __init__(self):
        super().__init__()
        self.count = 0

    def eventFilter(self, obj, event):
        if event.type() in (QtCore.QEvent.Paint, QtCore.QEvent.UpdateRequest):
            self.count += 1
        return False


class TestVariablesGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestVariablesGui")
        self.doc.UndoMode = 1
        self.varSet = self.doc.addObject("App::VarSet", "VarSet")
        self.varSet.addProperty("App::PropertyLength", "Width")
        self.varSet.Width = 20
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.setExpression("Length", "VarSet.Width * 2")
        self.doc.recompute()
        self.widgets = []

    def tearDown(self):
        for widget in self.widgets:
            widget.deleteLater()
        Gui.Selection.clearSelection()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        pump(0.2)
        App.closeDocument(self.doc.Name)

    # helpers

    def boundSpinBox(self, obj, prop):
        """A QuantitySpinBox bound to obj.<prop>, applying its expression as a task panel does."""
        spin = Gui.UiLoader().createWidget("Gui::QuantitySpinBox")
        self.widgets.append(spin)
        binding = Gui.ExpressionBinding(spin)
        binding.bind(obj, prop)
        binding.setAutoApply(True)
        self.binding = binding
        spin.show()
        pump(0.1)
        return spin

    def propertyRowText(self, obj, prop):
        """The value column's text of obj.<prop> in the property view's Data tab."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj.Document.Name, obj.Name)
        found = waitFor(lambda: self._propertyIndex(prop))
        self.assertTrue(found, "no %s row in the property view" % prop)
        editor, index = found
        return str(editor.model().data(index.sibling(index.row(), 1), QtCore.Qt.DisplayRole))

    def _propertyIndex(self, prop):
        for editor in widgetsOfClass(
            Gui.getMainWindow(), QtWidgets.QTreeView, "Gui::PropertyEditor::PropertyEditor"
        ):
            if editor.objectName() != "propertyEditorData":
                continue
            index = self._findRow(editor.model(), QtCore.QModelIndex(), prop)
            if index is not None:
                return editor, index
        return None

    @classmethod
    def _findRow(cls, model, parent, name):
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            if str(model.data(index)) == name and model.rowCount(index) == 0:
                return index
            found = cls._findRow(model, index, name)
            if found is not None:
                return found
        return None

    def consoleText(self):
        consoles = widgetsOfClass(Gui.getMainWindow(), QtWidgets.QPlainTextEdit, "Gui::PythonConsole")
        self.assertTrue(consoles, "no Python console")
        return consoles[0].toPlainText()

    # G11-G16

    def test_formula_dialog(self):
        """G11. The f(x) dialog opens with `#Width * 2`. OK with the text unchanged keeps the stored
        text and the value, and the command line it records has no `#`."""
        spin = self.boundSpinBox(self.box, "Length")
        QTest.keyClicks(spin, "=")
        dialog = waitFor(
            lambda: widgetsOfClass(spin, QtWidgets.QDialog, "Gui::Dialog::DlgExpressionInput")
        )
        self.assertTrue(dialog, "the f(x) dialog didn't open")
        dialog = dialog[0]
        editor = dialog.findChild(QtWidgets.QPlainTextEdit, "expression")
        self.assertEqual(editor.toPlainText(), "#Width * 2")

        before = len(self.consoleText())
        dialog.accept()
        pump(0.3)
        recorded = self.consoleText()[before:]
        self.assertIn("setExpression('Length', u'VarSet.Width * 2')", recorded)
        self.assertNotIn("#", recorded)
        self.assertEqual(expressionText(self.box, "Length"), "VarSet.Width * 2")
        self.doc.recompute()
        self.assertAlmostEqual(self.box.Length.Value, 40)

    def test_property_editor(self):
        """G12. The property editor's `value ( expr )` text."""
        self.assertIn("( #Width * 2 )", self.propertyRowText(self.box, "Length"))

    def test_spin_box_tooltip(self):
        """G13. The f(x) icon's tooltip in a spin box bound to Box.Length, with the line saying
        where the name lives."""
        spin = self.boundSpinBox(self.box, "Length")
        tips = [label.toolTip() for label in spin.findChildren(QtWidgets.QLabel) if label.toolTip()]
        self.assertEqual(len(tips), 1, tips)
        self.assertEqual(tips[0].split("\n"), ["Expression: #Width * 2", "#Width: VarSet.Width"])

    def test_spreadsheet(self):
        """G14. The cell editor and the content line show `=#Width`; committing that unchanged
        does nothing; an edit is stored with the full path; a plain-text copy is stored text."""
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("B1", "=#Width")
        self.doc.recompute()
        self.assertEqual(sheet.getContents("B1"), "=VarSet.Width")

        self.assertTrue(sheet.ViewObject.doubleClicked())
        tables = waitFor(
            lambda: [
                w
                for w in QtWidgets.QApplication.allWidgets()
                if w.metaObject().className() == "SpreadsheetGui::SheetTableView"
            ]
        )
        self.assertTrue(
            tables,
            "no sheet view: "
            + str(sorted({w.metaObject().className() for w in QtWidgets.QApplication.allWidgets()})),
        )
        table = tables[0]
        model = table.model()
        b1 = model.index(0, 1)
        self.assertEqual(model.data(b1, QtCore.Qt.EditRole), "=#Width")

        table.setCurrentIndex(b1)
        pump(0.2)
        lines = [
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QLineEdit, "cellContent")
            if w.isVisible()
        ]
        self.assertTrue(lines, "no content line")
        self.assertEqual(lines[0].text(), "=#Width")

        QtWidgets.QApplication.clipboard().clear()
        QtCore.QMetaObject.invokeMethod(table, "copySelection")
        pump(0.2)
        self.assertEqual(QtWidgets.QApplication.clipboard().text(), "=VarSet.Width")

        undoCount = self.doc.UndoCount
        model.setData(b1, "=#Width", QtCore.Qt.EditRole)
        pump(0.3)
        self.assertEqual(self.doc.UndoCount, undoCount)
        self.assertNotIn("Touched", sheet.State)
        # The stored text retyped is no change either (fork PR 153 review).
        model.setData(b1, "=VarSet.Width", QtCore.Qt.EditRole)
        pump(0.3)
        self.assertEqual(self.doc.UndoCount, undoCount)
        self.assertNotIn("Touched", sheet.State)

        model.setData(b1, "=#Width*3", QtCore.Qt.EditRole)
        pump(0.3)
        self.assertEqual(sheet.getContents("B1"), "=VarSet.Width * 3")
        self.assertEqual(self.doc.UndoCount, undoCount + 1)

    def test_formula_dialog_keeps_label_reference(self):
        """G11, a label reference (fork PR 153 review): OK with the shown text unchanged keeps
        `<<Variables>>.Width`, which parses back as `VarSet.Width`."""
        self.varSet.Label = "Variables"
        self.box.setExpression("Length", "<<Variables>>.Width * 2")
        self.doc.recompute()
        spin = self.boundSpinBox(self.box, "Length")
        QTest.keyClicks(spin, "=")
        dialog = waitFor(
            lambda: widgetsOfClass(spin, QtWidgets.QDialog, "Gui::Dialog::DlgExpressionInput")
        )
        self.assertTrue(dialog, "the f(x) dialog didn't open")
        dialog = dialog[0]
        editor = dialog.findChild(QtWidgets.QPlainTextEdit, "expression")
        self.assertEqual(editor.toPlainText(), "#Width * 2")
        dialog.accept()
        pump(0.3)
        self.assertEqual(expressionText(self.box, "Length"), "<<Variables>>.Width * 2")

    def test_input_field_keeps_expression(self):
        """An InputField bound to Box.Length shows `#Width * 2`, and showing it changes nothing:
        the stored text keeps its label reference, and there is no new undo entry (fork PR 153
        review, Medium)."""
        self.varSet.Label = "Variables"
        self.box.setExpression("Length", "<<Variables>>.Width * 2")
        self.doc.recompute()
        undoCount = self.doc.UndoCount
        field = Gui.UiLoader().createWidget("Gui::InputField")
        self.widgets.append(field)
        binding = Gui.ExpressionBinding(field)
        binding.bind(self.box, "Length")
        field.show()
        pump(0.1)
        self.assertEqual(field.text(), "#Width * 2")
        field.setProperty("unit", "mm")  # updateText() shows the text again
        pump(0.1)
        self.assertEqual(field.text(), "#Width * 2")
        self.assertEqual(expressionText(self.box, "Length"), "<<Variables>>.Width * 2")
        self.assertEqual(self.doc.UndoCount, undoCount)

    def test_property_view_repaints(self):
        """8.4: changes that make a name unique or ambiguous repaint the property view's Data tab:
        an alias set, a VarSet deleted, and its deletion undone (fork PR 153 review)."""
        other = self.doc.addObject("App::VarSet", "Other")
        other.addProperty("App::PropertyLength", "Width")
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        self.doc.recompute()
        self.assertIn("( VarSet.Width * 2 )", self.propertyRowText(self.box, "Length"))
        editor, _ = self._propertyIndex("Length")
        counter = PaintCounter()
        editor.viewport().installEventFilter(counter)
        pump(0.3)

        def repainted(change):
            counter.count = 0
            change()
            pump(0.3)
            return counter.count

        self.doc.openTransaction("Delete Other")
        self.assertGreater(repainted(lambda: self.doc.removeObject("Other")), 0, "delete")
        self.doc.commitTransaction()
        self.assertGreater(repainted(self.doc.undo), 0, "undo of the delete")
        self.assertIsNotNone(self.doc.getObject("Other"))
        self.assertGreater(repainted(lambda: sheet.setAlias("A1", "Depth")), 0, "alias")
        editor.viewport().removeEventFilter(counter)

    def test_live_ambiguity_change(self):
        """G15. A sheet alias `Width` makes the name ambiguous: the Length row falls back to the
        full path, while the Box stays selected."""
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        self.doc.recompute()
        self.assertIn("( #Width * 2 )", self.propertyRowText(self.box, "Length"))
        sheet.set("A1", "5 mm")
        sheet.setAlias("A1", "Width")
        self.doc.recompute()
        pump(0.3)
        editor, index = self._propertyIndex("Length")
        text = str(editor.model().data(index.sibling(index.row(), 1), QtCore.Qt.DisplayRole))
        self.assertIn("( VarSet.Width * 2 )", text)

    def test_sketcher_constraint_tooltip(self):
        """G16. A distance constraint bound to `#Width`: the constraint list's tooltip."""
        import Part
        import Sketcher

        sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.addGeometry(Part.LineSegment(App.Vector(0, 0, 0), App.Vector(10, 0, 0)))
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10))
        sketch.setExpression("Constraints[0]", "#Width")
        self.doc.recompute()
        self.assertEqual([text for _, text in sketch.ExpressionEngine], ["VarSet.Width"])

        Gui.ActiveDocument.setEdit(sketch)
        lists = waitFor(
            lambda: widgetsOfClass(Gui.getMainWindow(), QtWidgets.QListWidget, "SketcherGui::ConstraintView")
        )
        self.assertTrue(lists, "no constraint list")
        item = waitFor(lambda: lists[0].item(0))
        self.assertIsNotNone(item)
        self.assertEqual(
            str(item.data(QtCore.Qt.ToolTipRole)).split("\n"), ["#Width", "#Width: VarSet.Width"]
        )
