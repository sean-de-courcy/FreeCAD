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


def waitFor(condition, timeout=5.0):
    """Pumps events until condition() holds, or the timeout passes. Instead of fixed waits, which
    can pass for nothing on a slow machine."""
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


def deleteActions():
    return Gui.Command.get("Std_Delete").getAction()


def pressDelete():
    """Delete as the window system delivers it: to the main window, through the shortcut map, then
    to the focus widget. (QTest's QWidget overload skips the window's shortcut handling.)"""
    QtTest.QTest.keyClick(Gui.getMainWindow().windowHandle(), QtCore.Qt.Key_Delete)


def reportText():
    """The Report view's text, where Std_Delete's warnings go."""
    for edit in Gui.getMainWindow().findChildren(QtWidgets.QTextEdit):
        if edit.metaObject().className() == "Gui::DockWnd::ReportOutput":
            return edit.toPlainText()
    return None


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
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
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
        self.assertTrue(waitFor(lambda: self.rows(refs) == EDGES[1:]), "the row stays")

        self.checkModelIntact(feature)
        self.assertEqual(self.rows(refs), EDGES[1:])
        self.assertEqual(feature.Base[1], EDGES[1:])

        # OK keeps the removal as one undo step, and undo brings the edge back
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok)
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
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

    def view3d(self):
        """The document's 3D view, made the active sub-window. (activeSubWindow() can be None off
        screen, and the current one can be another window, e.g. the Start page.)"""
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        views = [
            subWindow
            for subWindow in mdi.subWindowList()
            if subWindow.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertEqual(len(views), 1, "the document's 3D view")
        # held: PySide drops the view's wrapper with the sub-window's
        self.viewWindow = views[0]
        mdi.setActiveSubWindow(self.viewWindow)
        return self.viewWindow.widget()

    def deleteInView(self, done=None):
        """Presses Delete with the focus in the 3D view and waits until Std_Delete has run, or
        until done() holds. The command's actions are enabled on a timer from the selection, and
        the key reaches them later than its own events: a check right after the key could pass
        for nothing."""
        actions = deleteActions()
        self.assertTrue(actions)
        self.assertTrue(
            waitFor(lambda: all(action.isEnabled() for action in actions)),
            "Std_Delete stays disabled",
        )
        self.assertTrue(focus(self.view3d()), "the 3D view doesn't take the focus")
        ran = []

        def onTriggered(*args):  # after the command's own slot: the command has run
            ran.append(True)

        for action in actions:
            action.triggered.connect(onTriggered)
        try:
            pressDelete()
            if done:
                self.assertTrue(waitFor(done), "Delete did nothing")
            else:
                self.assertTrue(waitFor(lambda: ran), "Std_Delete didn't run")
        finally:
            for action in actions:
                action.triggered.disconnect(onTriggered)
        pump(0.1)

    def assertWarned(self, reportBefore, *kept):
        """Std_Delete said, in the Report view, that it kept these objects."""

        def warning():
            report = reportText()
            self.assertIsNotNone(report, "no Report view")
            new = report[len(reportBefore) :]
            return new.split("is being edited", 1)[1] if "is being edited" in new else None

        self.assertTrue(waitFor(warning, 2.0), "no warning")
        for obj in kept:
            self.assertIn(obj.Label, warning())

    def testDeleteInViewKeepsBody(self):
        """The row's highlight is selected and the focus is in the 3D view: the Body stays (it
        was deleted, with everything in it)."""
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        refs = self.openList(fillet)
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        reportBefore = reportText() or ""
        self.deleteInView()
        self.checkModelIntact(fillet)
        self.assertEqual(self.rows(refs), EDGES)
        self.assertEqual(fillet.Base[1], EDGES)
        self.assertEqual(self.doc.UndoCount, undoCount)
        self.assertWarned(reportBefore, self.body)

    def deleteInEdit(self, feature, sub=""):
        """Selects the feature in edit (or a sub-element of it) and presses Delete in the 3D view."""
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog())
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, feature.Name, sub)
        reportBefore = reportText() or ""
        self.deleteInView()
        self.checkModelIntact(feature)
        self.assertEqual(feature.Base[1], EDGES)
        self.assertEqual(self.doc.UndoCount, undoCount)
        self.assertWarned(reportBefore, feature)

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
        self.deleteInView()
        self.assertIsNone(self.doc.getObject("Other"))
        self.checkModelIntact(fillet)

    def testDeleteEditedSubElementAndOtherObject(self):
        """An edge of the fillet in edit and another object: the other object is deleted, and the
        fillet stays, with a warning (ops#160). The edge took the in-edit path, which handed it to
        the fillet and skipped the rest of the selection: nothing deleted, nothing said."""
        other = self.doc.addObject("Part::Box", "Other")
        self.doc.recompute()
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        Gui.getDocument(self.doc.Name).setEdit(fillet.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, fillet.Name, "Edge3")
        Gui.Selection.addSelection(other)
        reportBefore = reportText() or ""
        self.deleteInView()
        self.assertIsNone(self.doc.getObject("Other"), "the other object wasn't deleted")
        self.checkModelIntact(fillet)
        self.assertEqual(fillet.Base[1], EDGES)
        self.assertWarned(reportBefore, fillet)

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
            reportBefore = reportText() or ""
            self.deleteInView()
            for name in ("Group", "Part"):
                self.assertIsNotNone(self.doc.getObject(name), f"{name} deleted")
            self.checkModelIntact(fillet)
            self.assertWarned(reportBefore, container)
        self.assertEqual(self.doc.UndoCount, undoCount)

    def testDeleteEditRootInEdit(self):
        """The fillet edited through a Link to its Body (Link.Fillet): the Link, and a group
        holding it, stay while it's in edit (ops#160). Deleting the Link reset the edit under the
        open dialog."""
        group = self.doc.addObject("App::DocumentObjectGroup", "LinkGroup")
        link = self.doc.addObject("App::Link", "Link")
        link.LinkedObject = self.body
        group.addObject(link)
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        guiDoc = Gui.getDocument(self.doc.Name)
        guiDoc.setEdit(link, 0, "Fillet.")
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "no dress-up dialog")
        inEdit = guiDoc.getInEdit()
        self.assertIsNotNone(inEdit)
        self.assertEqual(inEdit.Object, fillet)
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        for container in (link, group):
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(container)
            reportBefore = reportText() or ""
            self.deleteInView()
            for name in ("Link", "LinkGroup"):
                self.assertIsNotNone(self.doc.getObject(name), f"{name} deleted")
            self.checkModelIntact(fillet)
            self.assertIsNotNone(guiDoc.getInEdit(), "the edit was reset")
            self.assertWarned(reportBefore, container)
        self.assertEqual(self.doc.UndoCount, undoCount)

    def testSketchGeometryStillDeletedInEdit(self):
        """In a sketch in edit (in the Body), Delete still deletes the selected geometry: the
        Sketcher's own key handling, and Std_Delete's in-edit path, which hands the Sketcher its
        sub-elements and which the guard leaves alone."""
        import Part

        sketch = self.body.newObject("Sketcher::SketchObject", "Sketch")
        for start, end in (((0, 0), (10, 0)), ((10, 0), (10, 10))):
            sketch.addGeometry(Part.LineSegment(App.Vector(*start, 0), App.Vector(*end, 0)))
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).setEdit(sketch.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, sketch.Name, "Edge1")
        self.deleteInView(done=lambda: sketch.GeometryCount == 1)
        self.assertIsNotNone(self.doc.getObject("Sketch"))
        self.assertIn(sketch, self.body.Group)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, sketch.Name, "Edge1")
        Gui.runCommand("Std_Delete")
        self.assertTrue(waitFor(lambda: sketch.GeometryCount == 0), "Std_Delete deleted nothing")
        self.assertIsNotNone(self.doc.getObject("Sketch"))
        self.assertIn(sketch, self.body.Group)
        Gui.getDocument(self.doc.Name).resetEdit()
        pump()
