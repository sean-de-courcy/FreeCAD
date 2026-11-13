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
from freecad.variables import copies

from PySide import QtCore, QtGui, QtWidgets

Tabs = App.DocumentTabs
GuiTabs = Gui.DocumentTabs
V = App.Vector

NAME, TYPE, EXPRESSION, VALUE, DESCRIPTION = range(5)
KIND_ROLE = QtCore.Qt.UserRole + 1
HOLDER_ROLE = QtCore.Qt.UserRole + 3
HEADER_KIND = 0
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

    def testAddOffersNoMeasuredVariable(self):
        """Onshape's MV5: a Variable Studio holds no measured variable (no geometry to measure):
        its Add offers none, and the measured variable dialog won't start there."""
        name, view = self.studio()
        self.action(view, "addVariable").trigger()
        found = waitFor(lambda: [w for w in QtWidgets.QApplication.topLevelWidgets()
                                 if w.objectName() == "addVariableDialog" and w.isVisible()])
        self.assertTrue(found, "no Add variable dialog")
        typeBox = found[0].findChild(QtWidgets.QComboBox, "type")
        texts = [typeBox.itemText(i) for i in range(typeBox.count())]
        self.assertTrue(texts)
        self.assertFalse([t for t in texts if t.startswith("Measured")], texts)
        found[0].reject()
        pump(0.1)
        from freecad.variables import measuredgui

        self.assertIn("Part Studio", measuredgui.start(self.doc, "w", "Length"))
        self.assertIsNone(measuredgui.current)

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


    # -- references (ops#721 G2, ops#722 G3; notes/variable-studio-references.md section 2) --
    def sourceFile(self, name, **values):
        """A saved file @a name.FCStd whose Variable Studio "Studio" holds @a values (mm)."""
        if not self.tmp:
            self.tmp = tempfile.mkdtemp(prefix="TestVariableStudioGui")
        doc = App.newDocument("TestVariableStudioGuiSource")
        studio = doc.addObject("App::VarSet", "Studio")
        for var, mm in values.items():
            studio.addProperty("App::PropertyLength", var)
            setattr(studio, var, mm)
        Tabs.setVariableStudio(studio, True)
        doc.recompute()
        path = os.path.join(self.tmp, name + ".FCStd")
        doc.saveAs(path)
        App.closeDocument(doc.Name)
        pump(0.1)
        return path

    def headers(self, view):
        """[(text, holder name or None)] of the table's header rows, in order."""
        pump(0.3)
        model = self.tree(view).model()
        result = []
        for row in range(model.rowCount()):
            index = model.index(row, NAME)
            if model.data(index, KIND_ROLE) == HEADER_KIND:
                result.append((model.data(index), model.data(index, HOLDER_ROLE)))
        return result

    def child(self, view, holder, name):
        """The item of variable @a name under @a holder's header row."""
        model = self.tree(view).model()
        for row in range(model.rowCount()):
            index = model.index(row, NAME)
            if model.data(index, HOLDER_ROLE) == holder and model.data(index, KIND_ROLE) == HEADER_KIND:
                for sub in range(model.rowCount(index)):
                    item = model.index(sub, NAME, index)
                    if model.data(item) == name:
                        return item
        self.fail(f"no row {name} under {holder}")

    def topRows(self, view):
        """[(kind, text)] of the table's top-level rows, in order."""
        pump(0.3)
        model = self.tree(view).model()
        return [(model.data(model.index(row, NAME), KIND_ROLE), model.data(model.index(row, NAME)))
                for row in range(model.rowCount())]

    def testReferencesListedInOrder(self):
        """Onshape's order (VR9): the referenced tables in list order at the top, then the studio's
        own rows (ending with the new row), then the document's other copies under "Other copies
        in this document"; moving a reference reorders the headers; the reference actions exist."""
        name, view = self.studio()
        tab = self.doc.getObject(name)
        tab.addProperty("App::PropertyLength", "w")
        tab.w = 5
        b = copies.reference_from_fcstd(tab, self.sourceFile("B", h=10), "Studio")
        c = copies.reference_from_fcstd(tab, self.sourceFile("C", q=2), "Studio")
        loose = copies.copy_from_fcstd(self.doc, self.sourceFile("D", r=3), "Studio")
        self.doc.recompute()
        holders = [holder for _, holder in self.headers(view)]
        texts = [text for text, _ in self.headers(view)]
        self.assertEqual(holders[:2], [b.Name, c.Name])
        other = texts.index("Other copies in this document")
        self.assertLess(other, holders.index(loose.Name))
        top = self.topRows(view)
        kinds = [kind for kind, _ in top]
        own = [text for kind, text in top].index("w")
        self.assertEqual(kinds[:2], [HEADER_KIND, HEADER_KIND])
        self.assertEqual(kinds[own], VARSET_KIND)
        self.assertEqual(kinds[own + 1], NEW_KIND)
        self.assertGreater(own, 1)
        self.assertGreater([text for _, text in top].index("Other copies in this document"), own)
        copies.move_reference(c, 0)
        holders = [holder for _, holder in self.headers(view)]
        self.assertEqual(holders[:2], [c.Name, b.Name])
        for action in ("moveReferenceUp", "moveReferenceDown", "removeReference", "addReference"):
            self.action(view, action)
        # On the first reference's header: down and remove, not up; on the loose copy: add only
        tree = self.tree(view)
        model = tree.model()

        def select(holder):
            for row in range(model.rowCount()):
                index = model.index(row, NAME)
                if model.data(index, HOLDER_ROLE) == holder:
                    tree.setCurrentIndex(index)
                    pump(0.1)
                    return
            self.fail("no header " + holder)

        select(c.Name)
        enabled = {a: self.action(view, a).isEnabled()
                   for a in ("moveReferenceUp", "moveReferenceDown", "removeReference", "addReference")}
        self.assertEqual(enabled, {"moveReferenceUp": False, "moveReferenceDown": True,
                                   "removeReference": True, "addReference": False})
        select(loose.Name)
        self.assertTrue(self.action(view, "addReference").isEnabled())
        self.assertFalse(self.action(view, "removeReference").isEnabled())

    def testShadowedReferenceMarked(self):
        """Onshape's marking (VR9): with references B (w 20, h 10) and C (w 40) and an own w = 30,
        B's w and C's w carry an information icon with the tooltip "Overwritten in another
        variable table."; B's h doesn't; no row is dimmed (all referenced rows are drawn alike).
        Without the own w only B's w is marked."""
        overwritten = "Overwritten in another variable table."
        name, view = self.studio()
        tab = self.doc.getObject(name)
        b = copies.reference_from_fcstd(tab, self.sourceFile("B", w=20, h=10), "Studio")
        c = copies.reference_from_fcstd(tab, self.sourceFile("C", w=40), "Studio")
        self.doc.recompute()
        pump(0.3)

        def marked(holder, var):
            item = self.child(view, holder, var)
            tip = item.data(QtCore.Qt.ToolTipRole) or ""
            icon = item.data(QtCore.Qt.DecorationRole)
            return overwritten in tip and icon is not None and not icon.isNull()

        self.assertTrue(marked(b.Name, "w"))
        self.assertFalse(marked(c.Name, "w"))
        self.assertFalse(marked(b.Name, "h"))
        tab.addProperty("App::PropertyLength", "w")
        tab.w = 30
        self.doc.recompute()
        pump(0.3)
        self.assertTrue(marked(b.Name, "w"))
        self.assertTrue(marked(c.Name, "w"))
        self.assertFalse(marked(b.Name, "h"))
        fore = lambda holder, var: self.child(view, holder, var).data(QtCore.Qt.ForegroundRole)
        self.assertEqual(fore(b.Name, "w"), fore(b.Name, "h"), "a shadowed row is drawn differently")


if __name__ == "__main__":
    unittest.main()
