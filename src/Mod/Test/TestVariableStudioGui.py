# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************/

"""The Variable Studio tab, Onshape style (FreeCAD-CH, ops#640, tabs slice 4).

notes/onshape-tabs-design.md, "Slice 4: the Variable Studio tab". A Variable Studio tab opens its
own window, a table of that studio's variables (Gui/VariableStudioView.cpp), with no 3D view and
no Part Design tools; Part Studios use its variables by #name.

Designed model: Part Studio 1 (the document's top level) holds a Body with a 10 x 10 sketch padded
by #w; the Variable Studio holds w (a Length). The pad's volume is 100 * w mm^3.
"""

import os
import shutil
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtCore, QtGui, QtWidgets
from PySide6.QtTest import QTest

Tabs = App.DocumentTabs
GuiTabs = Gui.DocumentTabs
V = App.Vector

NAME, TYPE, EXPRESSION, VALUE, DESCRIPTION = range(5)
KIND_ROLE = QtCore.Qt.UserRole + 1
VARSET_KIND = 1
NEW_KIND = 3


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


def rectangle(x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    return [Part.LineSegment(p, q) for p, q in zip(points, points[1:] + points[:1])]


def activeWidget():
    """The widget of the MDI area's active window."""
    area = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
    window = area.activeSubWindow() if area else None
    return window.widget() if window else None


def studioViews():
    return [
        w
        for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget, "VariableStudioView")
        if w.parentWidget() is not None
    ]


class TestVariableStudioGui(unittest.TestCase):
    def setUp(self):
        if not GuiTabs.isOn():
            self.skipTest("the typed tabs are on under the Onshape keymap only")
        self.startWorkbench = Gui.activeWorkbench().name()
        self.docs = []
        self.tmp = None
        self.doc = self.newDocument("TestVariableStudioGui")

    def tearDown(self):
        for dialog in QtWidgets.QApplication.topLevelWidgets():
            if isinstance(dialog, (QtWidgets.QDialog, QtWidgets.QMessageBox)) and dialog.isVisible():
                dialog.reject()
        pump(0.1)
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        Gui.activateWorkbench(self.startWorkbench)
        pump(0.1)
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)

    # -- helpers ------------------------------------------------------------------------------

    def newDocument(self, name):
        doc = App.newDocument(name)
        doc.UndoMode = 1
        self.docs.append(doc.Name)
        pump(0.1)
        return doc

    def studio(self):
        """A Variable Studio tab made by "+", shown; returns (its name, its view)."""
        name = GuiTabs.create(self.doc, "VariableStudio")
        pump(0.3)
        self.assertTrue(name)
        view = waitFor(lambda: activeWidget() if activeWidget() is not None
                       and activeWidget().objectName() == "VariableStudioView" else None)
        self.assertIsNotNone(view, "the Variable Studio tab shows no view of its own")
        return name, view

    def tree(self, view):
        tree = view.findChild(QtWidgets.QTreeView, "variablesTree")
        self.assertIsNotNone(tree)
        return tree

    def rows(self, view):
        """{name: (type, expression, value)} of the view's rows, which are all top level."""
        pump(0.3)
        model = self.tree(view).model()
        result = {}
        for row in range(model.rowCount()):
            index = model.index(row, NAME)
            if model.data(index, KIND_ROLE) == NEW_KIND:
                self.assertEqual(row, model.rowCount() - 1, "the new row is not last")
                continue
            self.assertEqual(model.data(index, KIND_ROLE), VARSET_KIND, "a header row in the studio's table")
            result[model.data(index)] = tuple(
                model.data(model.index(row, column)) for column in (TYPE, EXPRESSION, VALUE)
            )
        return result

    def index(self, view, name, column):
        model = self.tree(view).model()
        for row in range(model.rowCount()):
            if model.data(model.index(row, NAME)) == name:
                return model.index(row, column)
        self.fail("no row " + name)

    def action(self, view, name):
        found = view.findChildren(QtGui.QAction, name)
        self.assertTrue(found, name)
        return found[0]

    def add(self, view, name, value, type_="Length"):
        """The view's Add: a variable @a name of @a type_ = @a value, OK pressed."""
        self.action(view, "addVariable").trigger()
        found = waitFor(lambda: [w for w in QtWidgets.QApplication.topLevelWidgets()
                                 if w.objectName() == "addVariableDialog" and w.isVisible()])
        self.assertTrue(found, "no Add variable dialog")
        dialog = found[0]
        dialog.findChild(QtWidgets.QLineEdit, "name").setText(name)
        typeBox = dialog.findChild(QtWidgets.QComboBox, "type")
        typeBox.setCurrentIndex(typeBox.findText(type_))
        dialog.findChild(QtWidgets.QLineEdit, "value").setText(value)
        dialog.findChild(QtWidgets.QDialogButtonBox).button(QtWidgets.QDialogButtonBox.Ok).click()
        pump(0.4)
        # The dialog deletes itself on close
        self.assertFalse([w for w in QtWidgets.QApplication.topLevelWidgets()
                          if w.objectName() == "addVariableDialog" and w.isVisible()],
                         "the Add dialog stayed open")

    def padStudio(self):
        """Part Studio 1: a 10 x 10 sketch padded #w."""
        doc = self.doc
        body = doc.addObject("PartDesign::Body", "Body")
        profile = doc.addObject("Sketcher::SketchObject", "Profile")
        body.addObject(profile)
        profile.addGeometry(rectangle(0, 0, 10, 10), False)
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.setExpression("Length", "#w")
        doc.recompute()
        GuiTabs.reconcile(doc)
        pump(0.2)
        return body, pad

    def undo(self):
        Gui.runCommand("Std_Undo")
        pump(0.3)

    def redo(self):
        Gui.runCommand("Std_Redo")
        pump(0.3)

    # -- the tab's window ---------------------------------------------------------------------

    def testTabOpensItsOwnTable(self):
        """A new Variable Studio tab shows its own window: a table, not a 3D view; the Part
        Design toolbars and the Features list are gone; the Variables dock is not raised for it.
        Back on Part Studio 1 its 3D view and Part Design return."""
        self.padStudioless()
        name, view = self.studio()
        self.assertEqual(GuiTabs.activeTab(self.doc), name)
        self.assertEqual(activeWidget().metaObject().className(), "Gui::VariableStudioView")
        self.assertEqual(Gui.activeWorkbench().name(), "VariableStudioWorkbench")
        bars = [b.objectName() for b in Gui.getMainWindow().findChildren(QtWidgets.QToolBar)
                if b.isVisible() and b.parentWidget() is Gui.getMainWindow()]
        self.assertFalse([b for b in bars if "Part Design" in b or "Sketcher" in b], bars)
        self.assertIn(self.doc.getObject(name).Label, view.windowTitle())
        # Its toolbar
        for action in ("addVariable", "deleteVariable", "showUses", "copyFromFreeCAD", "refreshCopy"):
            self.action(view, action)
        self.assertEqual(self.action(view, "copyFromFreeCAD").text(), "Insert Variable Studio...")
        self.assertTrue(GuiTabs.switchTo(self.doc, "*")[0])
        pump(0.3)
        self.assertEqual(activeWidget().metaObject().className(), "Gui::View3DInventor")
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        # Back again: the same window, not a second one
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        self.assertIs(activeWidget(), view)
        self.assertEqual(len([v for v in studioViews() if v is view or v.isVisible()]), 1)

    def padStudioless(self):
        """Part Studio 1 with one Body, so the document has a 3D tab to leave."""
        self.doc.addObject("PartDesign::Body", "Body")
        self.doc.recompute()
        GuiTabs.reconcile(self.doc)
        pump(0.2)

    def testTableShowsOnlyItsStudio(self):
        """The table lists the studio's own variables only, flat: another Variable Studio's and
        the Variables tool's VarSet are not in it."""
        name, view = self.studio()
        varset = self.doc.getObject(name)
        varset.addProperty("App::PropertyDistance", "w")
        varset.w = 10
        other = self.doc.addObject("App::VarSet", "Variables")
        other.addProperty("App::PropertyDistance", "q")
        self.doc.recompute()
        self.assertEqual(set(self.rows(view)), {"w"})
        self.assertEqual(self.rows(view)["w"][0], "Length")

    def testAddEditFollowedByPartStudio(self):
        """Add w = 10 mm in the view (one undo step), a Pad of #w is 1000 mm^3; w set to 15 mm in
        the table makes it 1500; undo and redo of the edit and of the add."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        varset = self.doc.getObject(name)
        self.assertIn("w", varset.PropertiesList)
        self.assertEqual(self.rows(view)["w"][0], "Length")
        _body, pad = self.padStudio()
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        model = self.tree(view).model()
        self.assertTrue(model.setData(self.index(view, "w", EXPRESSION), "15 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1500, 6)
        self.undo()
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)
        self.redo()
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1500, 6)

    def testRenameAndDelete(self):
        """Rename w -> width in the table: the Pad's expression follows. Delete n (unused): gone,
        and undo brings it back."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        self.add(view, "n", "3", "Number")
        _body, pad = self.padStudio()
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        model = self.tree(view).model()
        self.assertTrue(model.setData(self.index(view, "w", NAME), "width"))
        pump(0.3)
        self.assertEqual(set(self.rows(view)), {"width", "n"})
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)
        self.assertIn("width", dict(pad.ExpressionEngine)["Length"])
        tree = self.tree(view)
        tree.setCurrentIndex(self.index(view, "n", NAME))
        self.action(view, "deleteVariable").trigger()
        pump(0.3)
        self.assertNotIn("n", self.doc.getObject(name).PropertiesList)
        self.assertEqual(set(self.rows(view)), {"width"})
        self.undo()
        self.assertIn("n", self.doc.getObject(name).PropertiesList)
        self.assertEqual(set(self.rows(view)), {"width", "n"})

    def newRow(self, view):
        model = self.tree(view).model()
        index = model.index(model.rowCount() - 1, NAME)
        self.assertEqual(model.data(index, KIND_ROLE), NEW_KIND, "no new row at the table's end")
        return index

    def testInlineAdd(self):
        """Onshape's VS3: a name typed in the table's last row adds a Length with no value, one
        undo step; a duplicate name and one starting with a digit add nothing (VS Q3)."""
        name, view = self.studio()
        varset = self.doc.getObject(name)
        model = self.tree(view).model()
        self.assertTrue(model.setData(self.newRow(view), "w"))
        pump(0.4)
        self.assertIn("w", varset.PropertiesList)
        self.assertEqual(varset.getTypeIdOfProperty("w"), "App::PropertyDistance")
        self.assertEqual(self.rows(view)["w"][0], "Length")
        self.assertFalse(model.setData(self.newRow(view), "w"))
        self.assertFalse(model.setData(self.newRow(view), "2x"))
        pump(0.4)
        self.assertEqual(set(self.rows(view)), {"w"})
        self.assertNotIn("2x", varset.PropertiesList)
        self.undo()
        self.assertNotIn("w", varset.PropertiesList)
        self.assertEqual(set(self.rows(view)), set())

    def testAddGoesToTheStudio(self):
        """With another VarSet in the document, the view's Add puts the variable in its studio."""
        other = self.doc.addObject("App::VarSet", "Variables")
        self.doc.recompute()
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        self.assertIn("w", self.doc.getObject(name).PropertiesList)
        self.assertNotIn("w", other.PropertiesList)

    def testDeleteTabClosesItsView(self):
        """Deleting the studio closes its window; undo brings the tab back, and a click opens a
        window again."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        self.doc.openTransaction("Delete")
        self.doc.removeObject(name)
        self.doc.commitTransaction()
        pump(0.4)
        self.assertFalse([v for v in studioViews() if v.isVisible()])
        self.undo()
        pump(0.3)
        self.assertIsNotNone(self.doc.getObject(name))
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        again = activeWidget()
        self.assertEqual(again.objectName(), "VariableStudioView")
        self.assertEqual(set(self.rows(again)), {"w"})

    def testSaveAndReopen(self):
        """Saved and reopened: the tab is a Variable Studio, its window lists w, and the Pad of #w
        still follows it."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        self.padStudio()
        self.tmp = tempfile.mkdtemp(prefix="vstudio")
        path = os.path.join(self.tmp, "studio.FCStd")
        self.doc.saveAs(path)
        docName = self.doc.Name
        App.closeDocument(docName)
        pump(0.3)
        self.doc = App.openDocument(path)
        self.docs.append(self.doc.Name)
        pump(0.5)
        self.assertTrue(Tabs.isVariableStudio(self.doc.getObject(name)))
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.4)
        view = activeWidget()
        self.assertEqual(view.objectName(), "VariableStudioView")
        self.assertEqual(set(self.rows(view)), {"w"})
        model = self.tree(view).model()
        self.assertTrue(model.setData(self.index(view, "w", EXPRESSION), "20 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(self.doc.getObject("Pad").Shape.Volume, 2000, 6)

    # -- polish 13 (ops#640, decision 361): Onshape's Variable Studio rows P14-P19 ---------------

    def dockPanel(self):
        """The Variables dock, shown; returns its tree."""
        panel = Gui.getMainWindow().findChild(QtWidgets.QWidget, "Variables")
        self.assertIsNotNone(panel, "no Variables panel")
        dock = panel
        while dock is not None and not isinstance(dock, QtWidgets.QDockWidget):
            dock = dock.parentWidget()
        self.assertIsNotNone(dock)
        dock.show()
        self.addCleanup(dock.hide)
        pump(0.4)
        return panel, panel.findChild(QtWidgets.QTreeView, "variablesTree")

    def headerTexts(self, tree):
        pump(0.4)
        model = tree.model()
        return [model.data(model.index(row, NAME)) for row in range(model.rowCount())]

    def headerTip(self, tree, label):
        model = tree.model()
        for row in range(model.rowCount()):
            index = model.index(row, NAME)
            if model.data(index) == label:
                return model.data(index, QtCore.Qt.ToolTipRole)
        self.fail("no header " + label)

    def testOneValueCell(self):
        """P15, Onshape's VS1 and Q7: one Value cell. The Expression column is hidden; h = #w * 2
        with w = 10 mm shows its value, 20 mm; the cell's editor holds the expression; typing
        #w * 3 there makes h 30 mm (one undo step)."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        self.add(view, "h", "#w * 2")
        varset = self.doc.getObject(name)
        self.assertAlmostEqual(varset.h.Value, 20, 9)
        tree = self.tree(view)
        self.assertTrue(tree.isColumnHidden(EXPRESSION), "the Expression column shows")
        self.assertFalse(tree.isColumnHidden(VALUE))
        index = self.index(view, "h", VALUE)
        self.assertAlmostEqual(App.Units.Quantity(index.data()).Value, 20, 6)
        self.assertTrue(index.flags() & QtCore.Qt.ItemIsEditable, "the Value cell can't be edited")
        tree.setCurrentIndex(index)
        tree.edit(index)
        editor = waitFor(lambda: tree.indexWidget(index))
        self.assertIsNotNone(editor, "no editor on the Value cell")
        self.assertEqual(editor.objectName(), "expressionEditor")
        self.assertIn("#w", editor.text())
        self.assertIn("2", editor.text())
        editor.setText("#w * 3")
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        pump(0.4)
        self.assertAlmostEqual(varset.h.Value, 30, 9)
        self.assertAlmostEqual(App.Units.Quantity(self.index(view, "h", VALUE).data()).Value, 30, 6)
        # A plain value in w's Value cell
        index = self.index(view, "w", VALUE)
        tree.setCurrentIndex(index)
        tree.edit(index)
        editor = waitFor(lambda: tree.indexWidget(index))
        self.assertIsNotNone(editor)
        editor.setText("15 mm")
        QTest.keyClick(editor, QtCore.Qt.Key_Return)
        pump(0.4)
        self.doc.recompute()
        self.assertAlmostEqual(varset.w.Value, 15, 9)
        self.assertAlmostEqual(varset.h.Value, 45, 9)
        self.undo()
        self.doc.recompute()
        self.assertAlmostEqual(varset.w.Value, 10, 9)
        self.assertAlmostEqual(varset.h.Value, 30, 9)

    def testPartStudioPanelStacksTheStudiosFirst(self):
        """P19, Onshape's Q10: in a Part Studio the Variables panel shows one table per Variable
        Studio first, in the tabs' order, headed by the studio's name ("Automatically referenced
        Variable Studio"), then the other holders, here the Variables set made before them."""
        plain = self.doc.addObject("App::VarSet", "Variables")
        plain.addProperty("App::PropertyDistance", "q")
        self.padStudioless()
        first, view1 = self.studio()
        self.add(view1, "a", "1 mm")
        second, view2 = self.studio()
        self.add(view2, "b", "2 mm")
        self.doc.getObject(first).Label = "Dims"
        self.doc.getObject(second).Label = "Holes"
        self.assertTrue(GuiTabs.switchTo(self.doc, "*")[0])
        pump(0.3)
        _panel, tree = self.dockPanel()
        self.assertEqual(self.headerTexts(tree), ["Dims", "Holes", "Variables"])
        self.assertTrue(self.headerTip(tree, "Dims").startswith("Automatically referenced Variable Studio"))
        # The tabs' order decides: Holes moved before Dims
        order = Tabs.order(self.doc)
        order.remove(second)
        order.insert(order.index(first), second)
        Tabs.setOrder(self.doc, order)
        self.doc.recompute()
        self.assertTrue(GuiTabs.switchTo(self.doc, second)[0])
        pump(0.2)
        self.assertTrue(GuiTabs.switchTo(self.doc, "*")[0])
        self.assertEqual(self.headerTexts(tree), ["Holes", "Dims", "Variables"])

    def testDeleteWithoutWarning(self):
        """P14, Onshape's VS Q5: Delete in a Variable Studio removes a used variable at once, with
        no warning; the Pad of #w goes in error; undo brings both back."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        _body, pad = self.padStudio()
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        boxes = []

        def closeBoxes():
            for widget in QtWidgets.QApplication.topLevelWidgets():
                if isinstance(widget, QtWidgets.QMessageBox) and widget.isVisible():
                    boxes.append(widget.objectName())
                    widget.reject()

        timer = QtCore.QTimer()
        timer.timeout.connect(closeBoxes)
        timer.start(200)
        try:
            tree = self.tree(view)
            tree.setCurrentIndex(self.index(view, "w", NAME))
            self.action(view, "deleteVariable").trigger()
            pump(0.5)
        finally:
            timer.stop()
        self.assertEqual(boxes, [], "Delete asked first")
        self.assertNotIn("w", self.doc.getObject(name).PropertiesList)
        self.doc.recompute()
        self.assertFalse(pad.isValid(), "the Pad of #w stayed valid")
        self.undo()
        self.doc.recompute()
        self.assertIn("w", self.doc.getObject(name).PropertiesList)
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)

    def testInsertEverywhereSwitch(self):
        """P18, Onshape's VS8 and Q9: the switch shows on, by default. Off, the studio is absent
        from Part Studio 1's panel and #z is refused there; Insert Variable Studio in the panel
        brings it in (header "Variable Studio"), and #z works."""
        self.padStudioless()
        name, view = self.studio()
        self.add(view, "z", "4 mm")
        switch = view.findChild(QtWidgets.QCheckBox, "insertEverywhere")
        self.assertIsNotNone(switch, "no Insert into all Part Studios and Assemblies switch")
        self.assertEqual(switch.text(), "Insert into all Part Studios and Assemblies")
        self.assertTrue(switch.isChecked())
        switch.click()
        pump(0.2)
        self.assertFalse(Tabs.insertsEverywhere(self.doc.getObject(name)))
        label = self.doc.getObject(name).Label
        self.assertTrue(GuiTabs.switchTo(self.doc, "*")[0])
        pump(0.3)
        panel, tree = self.dockPanel()
        self.assertNotIn(label, self.headerTexts(tree))
        body = self.doc.getObject("Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        with self.assertRaises(Exception):
            box.setExpression("Length", "#z")
        menu = panel.findChild(QtWidgets.QMenu, "insertStudioMenu")
        self.assertIsNotNone(menu, "no Insert Variable Studio menu")
        menu.aboutToShow.emit()
        entries = [a for a in menu.actions() if a.objectName() == name]
        self.assertEqual(len(entries), 1, [a.text() for a in menu.actions()])
        self.assertFalse(entries[0].isChecked())
        entries[0].trigger()
        pump(0.4)
        self.assertEqual(Tabs.insertedStudios(self.doc, "*"), [name])
        self.assertIn(label, self.headerTexts(tree))
        self.assertTrue(self.headerTip(tree, label).startswith("Variable Studio"))
        box.setExpression("Length", "#z")
        box.Width = box.Height = 10
        self.doc.recompute()
        self.assertAlmostEqual(box.Shape.Volume, 400, 6)
        # Back on: the switch shows it
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        switch.click()
        pump(0.2)
        self.assertTrue(Tabs.insertsEverywhere(self.doc.getObject(name)))

    def order(self, view):
        """The table's own rows, top to bottom."""
        pump(0.3)
        model = self.tree(view).model()
        names = []
        for row in range(model.rowCount()):
            index = model.index(row, NAME)
            if model.data(index, KIND_ROLE) == VARSET_KIND:
                names.append(model.data(index))
        return names

    def testTypeDropdownPerRow(self):
        """P16, Onshape's VS1: the type is a dropdown in the row. n (a Number, 3) set to Length
        becomes 3 mm in its place; the Pad of #w + #k (1500 mm^3) is unchanged; one undo step
        takes it back."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        self.add(view, "n", "3", "Number")
        self.add(view, "k", "5 mm")
        _body, pad = self.padStudio()
        pad.setExpression("Length", "#w + #k")
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1500, 6)
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        varset = self.doc.getObject(name)
        tree = self.tree(view)
        index = self.index(view, "n", TYPE)
        self.assertTrue(index.flags() & QtCore.Qt.ItemIsEditable, "the Type cell can't be edited")
        tree.setCurrentIndex(index)
        tree.edit(index)
        box = waitFor(lambda: tree.indexWidget(index))
        self.assertIsInstance(box, QtWidgets.QComboBox)
        items = [box.itemText(i) for i in range(box.count())]
        for label in ("Length", "Angle", "Number"):
            self.assertIn(label, items)
        self.assertEqual(box.currentText(), "Number")
        box.setCurrentIndex(box.findText("Length"))
        box.activated.emit(box.currentIndex())
        pump(0.5)
        self.assertEqual(varset.getTypeIdOfProperty("n"), "App::PropertyDistance")
        self.assertAlmostEqual(varset.n.Value, 3, 9)
        self.assertEqual(self.order(view), ["w", "n", "k"])
        self.assertEqual(self.rows(view)["n"][0], "Length")
        self.doc.recompute()
        self.assertTrue(pad.isValid())
        self.assertAlmostEqual(pad.Shape.Volume, 1500, 6)
        self.undo()
        self.assertEqual(varset.getTypeIdOfProperty("n"), "App::PropertyFloat")
        self.assertEqual(self.order(view), ["w", "n", "k"])

    def testMoveUpDownAndTheOrderRule(self):
        """P17, Onshape's VS Q5: Move up / Move down in the row menu, and the order matters: h =
        #w * 2 moved above w fails the studio and the Pad of #h / 2 (ERROR); w moved up again
        heals both (1000 mm^3). Each move is one undo step."""
        name, view = self.studio()
        self.add(view, "w", "10 mm")
        self.add(view, "h", "#w * 2")
        _body, pad = self.padStudio()
        pad.setExpression("Length", "#h / 2")
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)
        self.assertTrue(GuiTabs.switchTo(self.doc, name)[0])
        pump(0.3)
        varset = self.doc.getObject(name)
        tree = self.tree(view)
        up = self.action(view, "moveUp")
        down = self.action(view, "moveDown")
        self.assertIn(up, tree.actions(), "Move up is not in the row menu")
        self.assertIn(down, tree.actions())
        tree.setCurrentIndex(self.index(view, "w", NAME))
        pump(0.1)
        self.assertFalse(up.isEnabled(), "Move up on the first row")
        self.assertTrue(down.isEnabled())
        tree.setCurrentIndex(self.index(view, "h", NAME))
        pump(0.1)
        self.assertTrue(up.isEnabled())
        self.assertFalse(down.isEnabled(), "Move down on the last row")
        up.trigger()
        pump(0.5)
        self.assertEqual(self.order(view), ["h", "w"])
        self.doc.recompute()
        self.assertIn("Invalid", varset.State)
        self.assertFalse(pad.isValid(), "the Pad of #h stayed valid with h above w")
        # The current row followed h: w is below it, Move down on w heals it
        tree.setCurrentIndex(self.index(view, "w", NAME))
        pump(0.1)
        up.trigger()
        pump(0.5)
        self.assertEqual(self.order(view), ["w", "h"])
        self.doc.recompute()
        self.assertNotIn("Invalid", varset.State)
        self.assertTrue(pad.isValid())
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)
        self.undo()
        self.assertEqual(self.order(view), ["h", "w"])
        self.undo()
        self.assertEqual(self.order(view), ["w", "h"])
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1000, 6)


if __name__ == "__main__":
    unittest.main()
