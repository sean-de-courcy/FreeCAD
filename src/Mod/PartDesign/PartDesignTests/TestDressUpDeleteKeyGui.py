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
deleted the whole Body under the open dialog. Std_Delete then left the object in edit and the
groups holding it alone (ops#143, ops#160, ops#164). Since ops#640 (the step lock, Onshape's rule:
with a feature dialog open the other rows take no Delete) Std_Delete is refused outright while a
PartDesign feature's dialog is open: it reads disabled, the key does nothing, and the command run by
name says why in the status bar. The in-edit path stays for the edits that hold no step: a Part
primitive's panel and the sketch editor.

Designed model: a 10 x 10 x 10 additive box with a dress-up on three of its edges. Keys go through
the window (QTest's QWindow overload), so the shortcut map sees them as it sees a user's."""

import contextlib
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets
from PySide6 import QtTest

from PartDesignTests.TestExpressionFieldsGui import liveButtonBoxes

EDGES = ["Edge1", "Edge2", "Edge3"]


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def taskButton(which):
    """The task panel's OK or Cancel button (dead wrappers: TestExpressionFieldsGui.liveButtonBoxes)."""
    for box in liveButtonBoxes():
        try:
            button = box.button(which)
            if button is None or not button.isVisible():
                continue
            parent = box.parentWidget()
            while parent is not None:
                if parent.metaObject().className() == "Gui::TaskView::TaskView":
                    return button
                parent = parent.parentWidget()
        except RuntimeError:  # a box (or a parent) deleted under its wrapper: not the panel's
            continue
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


def warnings():
    """Std_Delete's "Not deleted while ... is being edited" lines in the Report view."""
    return [line for line in (reportText() or "").splitlines() if "is being edited" in line]


def statusText():
    """The status bar's text: MainWindow::showMessage writes to a label in it."""
    bar = Gui.getMainWindow().statusBar()
    labels = [label.text() for label in bar.findChildren(QtWidgets.QLabel)]
    return " ".join([bar.currentMessage()] + labels)


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
        """Opens the feature's dialog and clicks the first row of its reference field, as a user
        would. The click arms the field (ops#150)."""
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)

        def visibleLists():
            # a closed dialog's field counts until its deferred delete (processEvents() leaves it)
            QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
            return [
                widget.findChild(QtWidgets.QListWidget, "entries")
                for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
                if widget.metaObject().className() == "PartDesignGui::ReferenceField"
                and widget.isVisible()
            ]

        # the first panel of a session takes longer to show (ops#164)
        self.assertTrue(waitFor(lambda: len(visibleLists()) == 1), "the dialog's reference list")
        self.assertTrue(Gui.Control.activeDialog(), "no dress-up dialog")
        # the panel's queued focus on its value field lands first, and the last dialog's late
        # switch back to the Model tab, which hides the task view off screen
        pump(0.3)
        Gui.Control.showTaskView()
        pump(0.05)
        lists = visibleLists()
        refs = lists[0]
        self.field = refs.parentWidget()
        self.assertEqual(self.rows(refs), EDGES)
        self.assertTrue(focus(refs), "the reference list doesn't take the focus")
        rect = refs.visualItemRect(refs.item(0))
        QtTest.QTest.mouseClick(
            refs.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center()
        )
        pump(0.2)
        self.assertEqual(refs.currentRow(), 0)
        self.assertTrue(refs.hasFocus())
        # the row's highlight goes through the field's own colours, not the selection (ops#150)
        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])
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

    def views3d(self):
        """The document's 3D views' sub-windows, oldest first. (activeSubWindow() can be None
        off screen, and the current one can be another window, e.g. the Start page.)"""
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        # held: PySide drops a view's wrapper with its sub-window's
        self.viewWindows = [
            subWindow
            for subWindow in mdi.subWindowList()
            if subWindow.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        return self.viewWindows

    def view3d(self, index=0):
        """The document's 3D view (the first one by default), made the active sub-window."""
        views = self.views3d()
        self.assertGreater(len(views), index, "the document's 3D view")
        Gui.getMainWindow().findChild(QtWidgets.QMdiArea).setActiveSubWindow(views[index])
        return views[index].widget()

    def deleteInView(self, done=None, view=0):
        """Presses Delete with the focus in a 3D view and waits until Std_Delete has run, or
        until done() holds. The command's actions are enabled on a timer from the selection, and
        the key reaches them later than its own events: a check right after the key could pass
        for nothing."""
        actions = deleteActions()
        self.assertTrue(actions)
        self.assertTrue(
            waitFor(lambda: all(action.isEnabled() for action in actions)),
            "Std_Delete stays disabled",
        )
        self.assertTrue(focus(self.view3d(view)), "the 3D view doesn't take the focus")
        ran = []

        def onTriggered(*args):  # after the command's own slot: the command has run
            ran.append(True)

        for action in actions:
            action.triggered.connect(onTriggered)
        try:
            with self.noModal():
                pressDelete()
                if done:
                    self.assertTrue(waitFor(done), "Delete did nothing")
                else:
                    self.assertTrue(waitFor(lambda: ran), "Std_Delete didn't run")
                pump(0.1)
        finally:
            for action in actions:
                action.triggered.disconnect(onTriggered)

    @contextlib.contextmanager
    def noModal(self):
        """A protected object let through would open the modal Object Dependencies box and stop
        the run until its timeout: closes any modal box while the block runs, and fails."""
        modals = []

        def rejectModal():
            modal = QtWidgets.QApplication.activeModalWidget()
            if modal is not None:
                modals.append(modal.windowTitle())
                modal.reject()

        modalGuard = QtCore.QTimer()
        modalGuard.timeout.connect(rejectModal)
        modalGuard.start(100)
        try:
            yield
        finally:
            modalGuard.stop()
        self.assertEqual(modals, [], "Std_Delete asked")

    def testABrokenEditLeavesNoUndoStep(self):
        """Journey J7: the box deleted, its fillet is broken. Its "Edit Fillet" command was left
        open by a refused edit and became an undo step, so the first Undo after the delete did
        nothing visible. A broken fillet's dialog now opens, with no modal (ops#640 rank 12, F19);
        its Cancel leaves the undo stack as after the delete, and one Undo brings the box back."""
        from PartDesignTests.TestExpressionFieldsGui import taskButton, waitFor

        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        self.doc.openTransaction("Delete")
        self.doc.removeObject(self.box.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        names = self.doc.UndoNames
        modals = []

        def closeModal():
            modal = QtWidgets.QApplication.activeModalWidget()
            if isinstance(modal, QtWidgets.QMessageBox):
                modals.append(modal.text())
                modal.accept()

        guard = QtCore.QTimer()
        guard.timeout.connect(closeModal)
        guard.start(50)
        try:
            fillet.ViewObject.doubleClicked()
            pump(0.3)
            self.assertEqual(modals, [])
            self.assertIsNotNone(Gui.getDocument(self.doc.Name).getInEdit())
            Gui.Control.showTaskView()
            self.assertTrue(waitFor(lambda: taskButton(QtWidgets.QDialogButtonBox.Cancel) is not None))
            taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
            self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
            pump(0.3)
        finally:
            guard.stop()
        self.assertEqual(modals, [])
        self.assertIsNone(Gui.getDocument(self.doc.Name).getInEdit())
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(self.doc.UndoNames, names)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNotNone(self.doc.getObject("Box"), "one Undo didn't bring the box back")

    def deleteRefusedInView(self, view=0):
        """Delete with the focus in a 3D view while the feature's dialog is open: refused
        (ops#640, the step lock; Onshape: no Delete of other rows with a dialog open). Std_Delete
        reads disabled, so the key reaches no command, and the command run by name says why in the
        status bar. Nothing asks (a protected object let through would open a modal box)."""
        actions = deleteActions()
        self.assertTrue(actions)
        self.assertTrue(
            waitFor(lambda: not any(action.isEnabled() for action in actions)),
            "Std_Delete is enabled with the dialog open",
        )
        self.assertTrue(focus(self.view3d(view)), "the 3D view doesn't take the focus")
        ran = []

        def onTriggered(*args):
            ran.append(True)

        for action in actions:
            action.triggered.connect(onTriggered)
        try:
            with self.noModal():
                pressDelete()
                pump(0.3)
                self.assertEqual(ran, [], "the Delete key ran Std_Delete")
                Gui.runCommand("Std_Delete")
                pump(0.2)
        finally:
            for action in actions:
                action.triggered.disconnect(onTriggered)
        self.assertIn("Finish the open dialog first", statusText())

    def runDelete(self, done):
        """Runs Std_Delete as a command and waits until done() holds. In sketch edit the Sketcher
        handles the Delete key itself: only the command goes through the in-edit path."""
        with self.noModal():
            Gui.runCommand("Std_Delete")
            self.assertTrue(waitFor(done), "Std_Delete deleted nothing")
            pump(0.1)

    def assertWarned(self, warningsBefore, *kept):
        """Std_Delete said, in the Report view, that it kept these objects. (Counted in lines:
        the Report view's text needn't only grow.)"""
        self.assertIsNotNone(reportText(), "no Report view")
        self.assertTrue(waitFor(lambda: len(warnings()) > warningsBefore, 2.0), "no warning")
        last = warnings()[-1].split("is being edited", 1)[1]
        for obj in kept:
            self.assertIn(obj.Label, last)

    def testDeleteInViewKeepsBody(self):
        """An edge of the Body is selected, as the row's highlight selected it before ops#150, and
        the focus is in the 3D view: the Body stays (it was deleted, with everything in it); the
        Delete is refused (ops#640)."""
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        refs = self.openList(fillet)
        self.field.setProperty("armed", False)  # its gate would refuse the Body
        Gui.Selection.addSelection(self.doc.Name, "Body", "Edge1")
        self.assertEqual(
            [(s.ObjectName, s.SubElementNames) for s in Gui.Selection.getSelectionEx(self.doc.Name)],
            [("Body", ("Edge1",))],
        )
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        self.deleteRefusedInView()
        self.checkModelIntact(fillet)
        self.assertEqual(self.rows(refs), EDGES)
        self.assertEqual(fillet.Base[1], EDGES)
        self.assertEqual(self.doc.UndoCount, undoCount)

    def deleteInEdit(self, feature, sub=""):
        """Selects the feature in edit (or a sub-element of it) and presses Delete in the 3D view:
        refused (ops#640)."""
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog())
        undoCount = self.doc.UndoCount  # with the dialog's transaction
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, feature.Name, sub)
        self.deleteRefusedInView()
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
        """An object outside the edited one's Body, while it's in edit: not deleted either
        (ops#640, Onshape: no Delete of other rows with a dialog open; it was deleted before)."""
        other = self.doc.addObject("Part::Box", "Other")
        self.doc.recompute()
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        Gui.getDocument(self.doc.Name).setEdit(fillet.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(other)
        self.deleteRefusedInView()
        self.assertIsNotNone(self.doc.getObject("Other"), "the other object was deleted")
        self.checkModelIntact(fillet)

    def testDeleteEditedSubElementAndOtherObject(self):
        """An edge of the fillet in edit and another object: neither is deleted, and the refusal
        is said (ops#640; ops#160 deleted the other object and warned about the fillet; before
        it the edge took the in-edit path and nothing was deleted or said)."""
        other = self.doc.addObject("Part::Box", "Other")
        self.doc.recompute()
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        Gui.getDocument(self.doc.Name).setEdit(fillet.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, fillet.Name, "Edge3")
        Gui.Selection.addSelection(other)
        self.deleteRefusedInView()
        self.assertIsNotNone(self.doc.getObject("Other"), "the other object was deleted")
        self.checkModelIntact(fillet)
        self.assertEqual(fillet.Base[1], EDGES)

    def testDeleteContainersInEdit(self):
        """The Body, and an App::Part and a plain group holding it, stay while the fillet is in
        edit: the Delete is refused (ops#640)."""
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
            self.deleteRefusedInView()
            for name in ("Group", "Part"):
                self.assertIsNotNone(self.doc.getObject(name), f"{name} deleted")
            self.checkModelIntact(fillet)
        self.assertEqual(self.doc.UndoCount, undoCount)

    def testDeleteEditRootInEdit(self):
        """The fillet edited through a Link to its Body (Link.Fillet): the Link, and a group
        holding it, stay while it's in edit (ops#160; refused since ops#640). Deleting the Link
        reset the edit under the open dialog."""
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
            self.deleteRefusedInView()
            for name in ("Link", "LinkGroup"):
                self.assertIsNotNone(self.doc.getObject(name), f"{name} deleted")
            self.checkModelIntact(fillet)
            self.assertIsNotNone(guiDoc.getInEdit(), "the edit was reset")
        self.assertEqual(self.doc.UndoCount, undoCount)

    def testDeleteBodyFromSecondView(self):
        """The fillet in edit in one 3D view, the Body selected and Delete pressed in a second view
        of the document: the Body stays (ops#164; refused since ops#640). getInEdit() is null
        while another view is active, so the guard saw no edit and the Body was deleted under the
        dialog."""
        fillet = self.makeDressUp("PartDesign::Fillet", Radius=1)
        guiDoc = Gui.getDocument(self.doc.Name)
        self.view3d(0)
        guiDoc.setEdit(fillet.Name)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog())
        Gui.runCommand("Std_ViewCreate")
        self.assertTrue(waitFor(lambda: len(self.views3d()) == 2), "no second 3D view")
        try:
            self.view3d(1)
            self.assertTrue(
                waitFor(lambda: guiDoc.getInEdit() is None), "the edit's view is active"
            )
            undoCount = self.doc.UndoCount  # with the dialog's transaction
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(self.body)
            self.deleteRefusedInView(view=1)
            self.checkModelIntact(fillet)
            self.assertEqual(self.doc.UndoCount, undoCount)
        finally:
            # tearDown resets the edit only where getInEdit() sees it, in the edit's own view
            views = self.views3d()
            if len(views) > 1:
                views[1].close()
                pump()
            self.view3d(0)
        self.assertTrue(waitFor(lambda: guiDoc.getInEdit() is not None), "the edit is gone")

    def testDeletePrimitiveSubElementAndOtherObject(self):
        """A Part box in edit (its primitive's panel), one of its faces and another object
        selected: the other object is deleted, and the box stays, with a warning (ops#164). The
        face went to the box's onDelete through the in-edit path, which skipped the rest of the
        selection, silently. A Part shape's sub-elements now take the general path."""
        box = self.doc.addObject("Part::Box", "PartBox")
        other = self.doc.addObject("Part::Box", "Other")
        other.Placement.Base = App.Vector(20, 0, 0)
        self.doc.recompute()
        Gui.getDocument(self.doc.Name).setEdit(box.Name)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "no primitive panel")
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, box.Name, "Face1")
        Gui.Selection.addSelection(other)
        warningsBefore = len(warnings())
        self.deleteInView()
        self.assertIsNone(self.doc.getObject("Other"), "the other object wasn't deleted")
        self.assertIsNotNone(self.doc.getObject("PartBox"))
        self.assertTrue(Gui.Control.activeDialog(), "the panel closed")
        self.assertWarned(warningsBefore, box)

    def makeSketch(self, name, points, closed=False):
        """A sketch in the Body, with line segments through the points."""
        import Part

        sketch = self.body.newObject("Sketcher::SketchObject", name)
        ends = points[1:] + points[:1] if closed else points[1:]
        for start, end in zip(points, ends):
            sketch.addGeometry(Part.LineSegment(App.Vector(*start, 0), App.Vector(*end, 0)))
        self.doc.recompute()
        return sketch

    def testSketchGeometryStillDeletedInEdit(self):
        """In a sketch in edit (in the Body), Delete still deletes the selected geometry: the
        Sketcher's own key handling, and Std_Delete's in-edit path, which hands the Sketcher its
        sub-elements and which the guard leaves alone."""
        sketch = self.makeSketch("Sketch", [(0, 0), (10, 0), (10, 10)])
        Gui.getDocument(self.doc.Name).setEdit(sketch.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, sketch.Name, "Edge1")
        self.deleteInView(done=lambda: sketch.GeometryCount == 1)
        self.assertIsNotNone(self.doc.getObject("Sketch"))
        self.assertIn(sketch, self.body.Group)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, sketch.Name, "Edge1")
        self.runDelete(lambda: sketch.GeometryCount == 0)
        self.assertIsNotNone(self.doc.getObject("Sketch"))
        self.assertIn(sketch, self.body.Group)
        Gui.getDocument(self.doc.Name).resetEdit()
        pump()

    def testSketchGeometryAndTreeSelectedPad(self):
        """In sketch edit, a Pad selected in the tree (the Sketcher keeps tree clicks) and a line
        of the sketch: Delete deletes the line, and the Pad stays, with a warning (ops#164
        review). The in-edit path is the Sketcher's alone; the Pad was deleted with the line."""
        profile = self.makeSketch("Profile", [(0, 0), (5, 0), (5, 5), (0, 5)], closed=True)
        pad = self.body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Length = 5
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        sketch = self.makeSketch("Sketch", [(0, 0), (10, 0), (10, 10)])
        self.assertEqual(self.body.Tip, pad)
        Gui.getDocument(self.doc.Name).setEdit(sketch.Name)
        pump(0.5)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(pad)
        Gui.Selection.addSelection(self.doc.Name, sketch.Name, "Edge1")
        warningsBefore = len(warnings())
        self.runDelete(lambda: sketch.GeometryCount == 1)
        self.assertIsNotNone(self.doc.getObject("Pad"), "the Pad was deleted")
        self.assertIn(pad, self.body.Group)
        self.assertEqual(self.body.Tip, pad)
        self.assertWarned(warningsBefore, pad)
        self.assertIn(f"{sketch.Label} is being edited", warnings()[-1])
        Gui.getDocument(self.doc.Name).resetEdit()
        pump()
