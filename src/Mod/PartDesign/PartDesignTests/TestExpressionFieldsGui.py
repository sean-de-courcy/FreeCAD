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
# ***************************************************************************

"""Expression-bound fields in the feature task panels (FreeCAD-CH, ops#155).

A field bound to a property with an expression showed the number read when the panel opened: a
recompute that changed the property while the panel was open (the panel's own recompute on open,
or a Sheet change) didn't refresh it. Designed models: a 20 x 10 rectangle padded by a Sheet alias,
a fillet and a pocket on it, each with its dimension on a Sheet alias. The oracle is the property's
value, which the field must show."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtCore, QtWidgets
from PySide6 import QtTest


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def taskButton(which):
    """The task panel's OK or Cancel button."""
    for box in Gui.getMainWindow().findChildren(QtWidgets.QDialogButtonBox):
        button = box.button(which)
        if button is None or not button.isVisible():
            continue
        parent = box.parentWidget()
        while parent is not None:
            if parent.metaObject().className() == "Gui::TaskView::TaskView":
                return button
            parent = parent.parentWidget()
    return None


def waitFor(condition, timeout=5.0):
    """Pumps events until condition() holds, or the timeout passes."""
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


def rectangleSketch(body, name, x0, y0, x1, y1, z=0.0):
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.AttachmentSupport = (body.Origin.OriginFeatures[3], [""])  # XY_Plane
    sketch.MapMode = "FlatFace"
    sketch.AttachmentOffset = App.Placement(App.Vector(0, 0, z), App.Rotation())
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        sketch.addGeometry(Part.LineSegment(App.Vector(ax, ay, 0), App.Vector(bx, by, 0)), False)
    return sketch


class RecomputeCounter:
    """Counts each object's recomputes (a document observer)."""

    def __init__(self):
        self.counts = {}

    def slotRecomputedObject(self, obj):
        self.counts[obj.Name] = self.counts.get(obj.Name, 0) + 1


class TestExpressionFieldsGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ExpressionFieldsGui")
        self.doc.UndoMode = 1
        self.sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        for cell, value, alias in (("A1", "10", "L"), ("A2", "2", "R"), ("A3", "3", "P")):
            self.sheet.set(cell, value)
            self.sheet.setAlias(cell, alias)
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        sketch = rectangleSketch(self.body, "Sketch", 0, 0, 20, 10)
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = sketch
        self.pad.setExpression("Length", "Sheet.L")
        self.doc.recompute()
        self.counter = None

    def tearDown(self):
        if self.counter is not None:
            App.removeDocumentObserver(self.counter)
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump()
        App.closeDocument(self.doc.Name)

    def openPanel(self, obj):
        Gui.Selection.clearSelection()
        obj.ViewObject.doubleClicked()
        pump()
        self.assertTrue(Gui.Control.activeDialog(), f"no panel for {obj.Name}")

    def field(self, name):
        widget = Gui.getMainWindow().findChild(QtWidgets.QWidget, name)
        self.assertIsNotNone(widget, f"no field {name}")
        return widget

    def assertShows(self, name, value):
        widget = self.field(name)
        self.assertAlmostEqual(widget.property("rawValue"), value, places=6)
        self.assertTrue(widget.property("readOnly"), f"{name} is editable with an expression")

    def setFormula(self, widget, text):
        """Sets an expression through the field's f(x) dialog, as a user would."""

        def formulaDialog():  # the open one: a closed one is deleted later
            for dialog in widget.findChildren(QtWidgets.QDialog, "DlgExpressionInput"):
                if dialog.isVisible():
                    return dialog
            return None

        # the field's f(x) icon
        icons = [
            label
            for label in widget.findChildren(QtWidgets.QLabel)
            if label.metaObject().className() == "ExpressionLabel"
        ]
        self.assertEqual(len(icons), 1, "the field's f(x) icon")
        QtTest.QTest.mouseClick(icons[0], QtCore.Qt.LeftButton)
        self.assertTrue(waitFor(lambda: formulaDialog() is not None), "no f(x) dialog")
        dialog = formulaDialog()
        edit = dialog.findChild(QtWidgets.QPlainTextEdit, "expression")
        self.assertIsNotNone(edit)
        edit.setPlainText(text)
        pump(0.1)
        ok = dialog.findChild(QtWidgets.QDialogButtonBox, "buttonBox").button(
            QtWidgets.QDialogButtonBox.Ok
        )
        self.assertTrue(ok.isEnabled(), f"the f(x) dialog doesn't take {text}")
        ok.click()
        self.assertTrue(waitFor(lambda: formulaDialog() is None), "the f(x) dialog stays")

    def assertUnit(self, name, unit="mm"):
        text = self.field(name).text()
        self.assertTrue(text.endswith(unit), f"{name} shows {text!r}, not in {unit}")

    def addFillet(self):
        # The vertical edge at (20, 10)
        edges = [
            i
            for i, e in enumerate(self.pad.Shape.Edges, 1)
            if abs(e.BoundBox.XMin - 20) < 1e-6
            and abs(e.BoundBox.YMin - 10) < 1e-6
            and e.BoundBox.ZLength > 1
        ]
        self.assertEqual(len(edges), 1)
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (self.pad, [f"Edge{edges[0]}"])
        fillet.setExpression("Radius", "Sheet.R")
        self.doc.recompute()
        self.assertAlmostEqual(fillet.Radius.Value, 2.0, places=6)
        return fillet

    def addPocket(self):
        sketch = rectangleSketch(self.body, "PocketSketch", 5, 2, 15, 8, z=10.0)
        pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = sketch
        pocket.setExpression("Length", "Sheet.P")
        self.doc.recompute()
        self.assertAlmostEqual(pocket.Length.Value, 3.0, places=6)
        return pocket

    def testCellChangeWhilePanelOpen(self):
        # B1: the field follows a Sheet change made while the Pad's panel is open
        self.openPanel(self.pad)
        self.assertShows("lengthEdit", 10.0)

        self.sheet.set("A1", "15")
        self.doc.recompute()
        pump()
        self.assertAlmostEqual(self.pad.Length.Value, 15.0, places=6)
        self.assertShows("lengthEdit", 15.0)

    def testStalePadPanelOpen(self):
        # B2: the Pad is stale when its panel opens; the panel's own recompute changes the
        # property, and the field shows the new value
        self.sheet.set("A1", "15")
        self.doc.recompute([self.sheet])
        self.assertAlmostEqual(self.pad.Length.Value, 10.0, places=6)

        self.openPanel(self.pad)
        self.assertAlmostEqual(self.pad.Length.Value, 15.0, places=6)
        self.assertShows("lengthEdit", 15.0)

    def testRefreshDoesNotLoop(self):
        # B3: the refresh doesn't write the property back: one recompute of the Pad per change,
        # nothing left to recompute, and no entries in the undo list
        self.openPanel(self.pad)
        undo = list(self.doc.UndoNames)
        self.counter = RecomputeCounter()
        App.addDocumentObserver(self.counter)

        self.sheet.set("A1", "15")
        self.doc.recompute()
        pump(0.5)
        self.assertEqual(self.counter.counts.get("Pad", 0), 1)
        self.assertEqual(self.doc.recompute(), 0)
        self.assertEqual(list(self.doc.UndoNames), undo)
        self.assertShows("lengthEdit", 15.0)

    def testFilletAndPocket(self):
        # B4: the Fillet's radius and the Pocket's length, the same as B1
        fillet = self.addFillet()
        self.openPanel(fillet)
        self.assertShows("filletRadius", 2.0)
        self.sheet.set("A2", "3")
        self.doc.recompute()
        pump()
        self.assertAlmostEqual(fillet.Radius.Value, 3.0, places=6)
        self.assertShows("filletRadius", 3.0)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        pump()

        pocket = self.addPocket()
        self.openPanel(pocket)
        self.assertShows("lengthEdit", 3.0)
        self.sheet.set("A3", "4")
        self.doc.recompute()
        pump()
        self.assertAlmostEqual(pocket.Length.Value, 4.0, places=6)
        self.assertShows("lengthEdit", 4.0)

    def testFieldWithoutExpressionKeepsTypedValue(self):
        # B5: a field without an expression keeps the value typed into it through a recompute
        self.pad.setExpression("Length", None)
        self.pad.Length = 10
        self.doc.recompute()
        self.openPanel(self.pad)
        widget = self.field("lengthEdit")
        self.assertFalse(widget.property("readOnly"))

        widget.setProperty("rawValue", 12.0)
        pump()
        self.assertAlmostEqual(self.pad.Length.Value, 12.0, places=6)
        # a change of the bound property itself (B5 never changed it, ops#159): the field keeps
        # the user's value
        self.pad.Length = 14
        self.doc.recompute()
        pump()
        self.assertAlmostEqual(self.pad.Length.Value, 14.0, places=6)
        self.assertAlmostEqual(widget.property("rawValue"), 12.0, places=6)
        self.assertFalse(widget.property("readOnly"))

    def testFormulaWithoutUnitShowsFieldUnit(self):
        # B6 (ops#157): the f(x) dialog sets an expression whose result has no unit (a Sheet cell
        # without one): the field showed "20.00", not "20.00 mm", until the panel was reopened.
        # Also after a refresh (B1's path)
        self.openPanel(self.pad)
        self.assertUnit("lengthEdit")
        self.setFormula(self.field("lengthEdit"), "Sheet.L * 2")
        self.assertAlmostEqual(self.field("lengthEdit").property("rawValue"), 20.0, places=6)
        self.assertUnit("lengthEdit")
        self.sheet.set("A1", "15")
        self.doc.recompute()
        pump()
        self.assertShows("lengthEdit", 30.0)
        self.assertUnit("lengthEdit")

    def testToggleEditModeCancelRevertsExpression(self):
        # B7 (ops#156): Edit > Toggle edit mode (Std_Edit) opened the panel without a transaction,
        # so an expression set in it went into its own committed transaction: Cancel kept it
        undo = list(self.doc.UndoNames)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.pad)
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        views = [
            subWindow
            for subWindow in mdi.subWindowList()
            if subWindow.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertEqual(len(views), 1, "the document's 3D view")
        mdi.setActiveSubWindow(views[0])  # Std_Edit acts on the active 3D view
        pump(0.1)
        Gui.runCommand("Std_Edit")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "Std_Edit opened no panel")
        self.setFormula(self.field("lengthEdit"), "Sheet.L * 2")
        self.assertEqual(self.pad.ExpressionEngine, [("Length", "Sheet.L * 2")])

        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the panel stays")
        self.assertEqual(self.pad.ExpressionEngine, [("Length", "Sheet.L")])
        self.doc.recompute()
        self.assertAlmostEqual(self.pad.Length.Value, 10.0, places=6)
        self.assertEqual(list(self.doc.UndoNames), undo)

    # ops#146 (upstream issue 23518): Esc that closes the expression editor opened with '=' in a
    # field also closed the panel. The press closes the editor; focus then lands on the 3D view,
    # and the view took the key's release as an Esc of its own.

    def view3d(self):
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        # held: PySide drops a view's wrapper with its sub-window's
        self.viewWindows = [
            subWindow
            for subWindow in mdi.subWindowList()
            if subWindow.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertEqual(len(self.viewWindows), 1, "the document's 3D view")
        return self.viewWindows[0].widget()

    def focus(self, widget):
        """Off screen, one activateWindow() and setFocus() aren't always enough."""
        for _ in range(20):
            widget.window().activateWindow()
            widget.setFocus(QtCore.Qt.OtherFocusReason)
            pump(0.05)
            focused = QtWidgets.QApplication.focusWidget()
            if focused is not None and (focused is widget or widget.isAncestorOf(focused)):
                return
        self.fail(f"no focus on {widget.objectName() or widget.metaObject().className()}")

    def openEqualsEditor(self):
        """Types '=' in the Pad's Taper field, which opens the expression editor."""
        self.openPanel(self.pad)
        pump(0.3)
        Gui.Control.showTaskView()  # the last dialog's late switch to the Model tab hides it
        taper = self.field("taperEdit")
        self.assertTrue(taper.isVisible() and taper.isEnabled(), "the Taper field")
        self.focus(taper)
        QtTest.QTest.keyClick(taper, QtCore.Qt.Key_Equal)

        def editor():
            for dialog in taper.findChildren(QtWidgets.QDialog, "DlgExpressionInput"):
                if dialog.isVisible():
                    return dialog
            return None

        self.assertTrue(waitFor(lambda: editor() is not None), "'=' opened no expression editor")
        return editor()

    def testEscInExpressionEditorKeepsPanel(self):
        for releaseIn in ("focus", "view"):
            with self.subTest(releaseIn=releaseIn):
                dialog = self.openEqualsEditor()
                edit = dialog.findChild(QtWidgets.QPlainTextEdit, "expression")
                QtTest.QTest.keyPress(edit, QtCore.Qt.Key_Escape)
                self.assertTrue(waitFor(lambda: not dialog.isVisible()), "the editor stays")
                pump(0.3)
                if releaseIn == "view":
                    # Where upstream's focus went (the 3D view) whatever it does off screen
                    self.focus(self.view3d())
                QtTest.QTest.keyRelease(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Escape)
                pump(0.5)
                self.assertTrue(Gui.Control.activeDialog(), "Esc in the editor closed the panel")
                self.assertEqual(self.pad.ExpressionEngine, [("Length", "Sheet.L")])
                taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
                self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))

    def testEscInViewStillClosesPanel(self):
        # The view's own Esc, pressed and released there, still cancels the panel
        self.openPanel(self.pad)
        self.focus(self.view3d())
        QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Escape)
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Esc in the view")
