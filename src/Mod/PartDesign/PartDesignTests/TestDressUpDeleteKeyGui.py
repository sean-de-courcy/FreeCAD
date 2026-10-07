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

"""The Delete key while a dress-up's dialog is open (FreeCAD-CH, ops#143; upstream issue 29180).

In the panel's reference list, Delete removes the selected reference, as the list's "Remove" does.
Anywhere else it is Std_Delete, and the row's highlight selects the edge on the Body: Std_Delete
deleted the whole Body under the open dialog. Std_Delete now leaves the object in edit and the
groups holding it alone, and a PartDesign feature in edit doesn't leave its Body when its own
sub-elements are deleted.

Designed model: a 10 x 10 x 10 additive box with a dress-up on three of its edges. Keys go through
the window (QTest's QWindow overload), so the shortcut map sees them as it sees a user's."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets
from PySide6 import QtTest

EDGES = ["Edge1", "Edge2", "Edge3"]


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


def focus(widget):
    """Off screen, one activateWindow() and setFocus() aren't always enough (notes: TestMeasureGui).
    The 3D view hands its focus on to its viewer, a child."""
    for _ in range(20):
        widget.window().activateWindow()
        widget.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.05)
        focused = QtWidgets.QApplication.focusWidget()
        if focused is not None and (focused is widget or widget.isAncestorOf(focused)):
            return True
    return False


def pressDelete():
    """Delete as the window system delivers it: to the main window, through the shortcut map, then
    to the focus widget. (QTest's QWidget overload skips the window's shortcut handling.)"""
    QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Delete)
    pump(0.5)


def view3d():
    return Gui.getMainWindow().findChild(QtWidgets.QMdiArea).activeSubWindow().widget()


class TestDressUpDeleteKeyGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("DressUpDeleteKey")
        self.doc.UndoMode = 1
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.box = self.doc.addObject("PartDesign::AdditiveBox", "Box")
        self.body.addObject(self.box)
        for prop in ("Length", "Width", "Height"):
            setattr(self.box, prop, 10)
        self.doc.recompute()
        Gui.Selection.clearSelection()

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    def makeDressUp(self, typeName, **props):
        self.featureName = typeName.split("::")[1]
        feature = self.doc.addObject(typeName, self.featureName)
        self.body.addObject(feature)
        feature.Base = (self.box, EDGES)
        for name, value in props.items():
            setattr(feature, name, value)
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        return feature

    def openList(self, feature):
        """Opens the feature's dialog and clicks the list's first row, as a user would."""
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "no dress-up dialog")
        lists = [
            widget
            for widget in Gui.getMainWindow().findChildren(
                QtWidgets.QListWidget, "listWidgetReferences"
            )
            if widget.isVisible()
        ]
        self.assertEqual(len(lists), 1, "the dialog's reference list")
        refs = lists[0]
        self.assertEqual(self.rows(refs), EDGES)
        self.assertTrue(focus(refs), "the reference list doesn't take the focus")
        rect = refs.visualItemRect(refs.item(0))
        QtTest.QTest.mouseClick(
            refs.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center()
        )
        pump(0.2)
        self.assertEqual(refs.currentRow(), 0)
        self.assertTrue(refs.hasFocus())
        # the row's highlight: the edge, selected on the Body
        self.assertEqual(
            [(s.ObjectName, s.SubElementNames) for s in Gui.Selection.getSelectionEx(self.doc.Name)],
            [("Body", ("Edge1",))],
        )
        return refs

    @staticmethod
    def rows(refs):
        return [refs.item(i).text() for i in range(refs.count())]

    def checkModelIntact(self, feature):
        for name in ("Body", "Box", self.featureName):  # a deleted feature's Name is None
            self.assertIsNotNone(self.doc.getObject(name), f"{name} deleted")
        self.assertEqual(self.body.Group, [self.box, feature])
        self.assertEqual(self.body.Tip, feature)
        self.assertTrue(Gui.Control.activeDialog(), "the dialog closed")

    def checkListDelete(self, feature):
        undoCount = self.doc.UndoCount
        refs = self.openList(feature)
        pressDelete()

        self.checkModelIntact(feature)
        self.assertEqual(self.rows(refs), EDGES[1:])
        self.assertEqual(feature.Base[1], EDGES[1:])

        # OK keeps the removal as one undo step, and undo brings the edge back
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok)
        ok.click()
        pump(0.5)
        self.assertFalse(Gui.Control.activeDialog())
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertEqual(feature.Base[1], EDGES[1:])
        self.assertEqual(self.doc.UndoCount, undoCount + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(feature.Base[1], EDGES)
        self.assertEqual(self.body.Group, [self.box, feature])

    def testFilletListDelete(self):
        self.checkListDelete(self.makeDressUp("PartDesign::Fillet", Radius=1))

    def testChamferListDelete(self):
        self.checkListDelete(self.makeDressUp("PartDesign::Chamfer", Size=1))

    def testDeleteInViewKeepsBody(self):
        """The row's highlight is selected and the focus is in the 3D view: the Body stays (it
        was deleted, with everything in it)."""
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        refs = self.openList(fillet)
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        pump(0.5)  # Std_Delete's action is enabled on a timer
        self.assertTrue(focus(view3d()), "the 3D view doesn't take the focus")
        pressDelete()
        self.checkModelIntact(fillet)
        self.assertEqual(self.rows(refs), EDGES)
        self.assertEqual(fillet.Base[1], EDGES)
        self.assertEqual(self.doc.UndoCount, undoCount)

    def deleteInEdit(self, feature, sub=""):
        """Selects the feature in edit (or a sub-element of it) and presses Delete in the 3D view."""
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog())
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, feature.Name, sub)
        pump(0.5)  # Std_Delete's action is enabled on a timer
        self.assertTrue(focus(view3d()), "the 3D view doesn't take the focus")
        pressDelete()
        self.checkModelIntact(feature)
        self.assertEqual(feature.Base[1], EDGES)
        self.assertEqual(self.doc.UndoCount, undoCount)

    def testDeleteEditedFeatureKeepsIt(self):
        """The fillet in edit, selected: not deleted under its dialog."""
        self.deleteInEdit(self.makeDressUp("PartDesign::Fillet", Radius=1))

    def testDeleteEditedSubElementKeepsItInBody(self):
        """An edge of the fillet in edit: the fillet stayed in the document but left its Body,
        and the Tip went back to the box, under the open dialog."""
        self.deleteInEdit(self.makeDressUp("PartDesign::Fillet", Radius=1), "Edge3")

    def testDeleteOtherObjectInEdit(self):
        """Objects outside the edited one's Body are still deleted while it's in edit."""
        other = self.doc.addObject("Part::Box", "Other")
        self.doc.recompute()
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        Gui.getDocument(self.doc.Name).setEdit(fillet.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(other)
        pump(0.5)  # Std_Delete's action is enabled on a timer
        self.assertTrue(focus(view3d()))
        pressDelete()
        self.assertIsNone(self.doc.getObject("Other"))
        self.checkModelIntact(fillet)

    def testDeleteContainersInEdit(self):
        """The Body, and an App::Part and a plain group holding it, stay while the fillet is in
        edit."""
        group = self.doc.addObject("App::DocumentObjectGroup", "Group")
        part = self.doc.addObject("App::Part", "Part")
        part.addObject(self.body)
        group.addObject(part)
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        Gui.getDocument(self.doc.Name).setEdit(fillet.Name)
        pump(0.5)
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        for container in (self.body, part, group):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(container)
            pump(0.5)  # Std_Delete's action is enabled on a timer
            self.assertTrue(focus(view3d()))
            pressDelete()
            for name in ("Group", "Part"):
                self.assertIsNotNone(self.doc.getObject(name), f"{name} deleted")
            self.checkModelIntact(fillet)
        self.assertEqual(self.doc.UndoCount, undoCount)

    def testSketchGeometryStillDeletedInEdit(self):
        """In a sketch in edit (in the Body), Delete still deletes the selected geometry: the
        Sketcher takes it through the in-edit path, which the guard leaves alone."""
        import Part

        sketch = self.body.newObject("Sketcher::SketchObject", "Sketch")
        for start, end in (((0, 0), (10, 0)), ((10, 0), (10, 10))):
            sketch.addGeometry(Part.LineSegment(App.Vector(*start, 0), App.Vector(*end, 0)))
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).setEdit(sketch.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, sketch.Name, "Edge1")
        pump(0.5)  # Std_Delete's action is enabled on a timer
        self.assertTrue(focus(view3d()))
        pressDelete()
        self.assertEqual(sketch.GeometryCount, 1)
        self.assertIsNotNone(self.doc.getObject("Sketch"))
        self.assertIn(sketch, self.body.Group)
        Gui.getDocument(self.doc.Name).resetEdit()
        pump()
