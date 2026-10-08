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

"""The selection filter (Part_SelectFilter: vertex, edge, face) across operations and in the
dress-up tasks (FreeCAD-CH, ops#147; upstream issues 28305, 26645).

The filter was the one selection gate, which task panels replace and delete: it was gone after one
Pad or Fillet while its toolbar icon still showed it, and a Fillet's reference field let a face
through with the edge filter on. The filter is now kept apart from the tasks' gates, and a pick
must pass both. In a sketch in edit it doesn't apply, so the sketch's vertices and constraints
stay selectable.

Designed model: a Body with a 10 x 10 rectangle padded 10 mm (a cube). The oracle is whether a
pick of a face or an edge is taken: by the selection, or by the Fillet's edge list."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtCore, QtWidgets
from PySide6 import QtTest

VERTEX, EDGE, FACE, NONE = range(4)  # Part_SelectFilter's entries


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


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


def setFilter(entry):
    Gui.runCommand("Part_SelectFilter", entry)
    pump(0.05)


class TestSelectionFilterGui(unittest.TestCase):
    def setUp(self):
        import PartGui  # noqa: F401  the filter's commands

        self.doc = App.newDocument("SelectionFilterGui")
        self.doc.UndoMode = 1
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.sketch = self.body.newObject("Sketcher::SketchObject", "Sketch")
        self.sketch.AttachmentSupport = (self.body.Origin.OriginFeatures[3], [""])  # XY_Plane
        self.sketch.MapMode = "FlatFace"
        corners = [(0, 0), (10, 0), (10, 10), (0, 10)]
        for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
            self.sketch.addGeometry(
                Part.LineSegment(App.Vector(ax, ay, 0), App.Vector(bx, by, 0)), False
            )
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.sketch
        self.pad.Length = 10
        self.doc.recompute()
        self.assertTrue(self.pad.isValid())
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()

    def tearDown(self):
        # Review round 3 (L-l): through the status-bar button first, which also works with no 3D
        # view active (Part_SelectFilter then does nothing), so a test that failed with another
        # view in front doesn't leak its filter into later classes
        button = self.filterButton()
        if button is not None and not button.isHidden():
            button.click()
            pump(0.05)
        setFilter(NONE)
        guiDoc = Gui.getDocument(self.doc.Name)
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        # The filter has no Python access: check it is off, so it can't leak into later classes
        filterOff = self.selectable(self.pad, "Face1") and self.selectable(self.pad, "Edge1")
        App.closeDocument(self.doc.Name)
        pump()
        self.assertTrue(filterOff, "the filter is still on")

    def selectable(self, obj, sub):
        """Whether a pick of obj.sub is taken by the selection (then cleared again)."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        taken = any(sub in s.SubElementNames for s in Gui.Selection.getSelectionEx(self.doc.Name))
        Gui.Selection.clearSelection()
        return taken

    def objectSelectable(self, obj):
        """Whether a pick of the whole object (as in the tree) is taken, then cleared again."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, obj.Name)
        taken = any(s.ObjectName == obj.Name for s in Gui.Selection.getSelectionEx(self.doc.Name))
        Gui.Selection.clearSelection()
        return taken

    def filterButton(self):
        return Gui.getMainWindow().statusBar().findChild(
            QtWidgets.QToolButton, "userSelectionFilterButton"
        )

    def assertEdgeFilterOn(self, obj):
        self.assertTrue(self.selectable(obj, "Edge1"), "the edge filter refuses an edge")
        self.assertFalse(self.selectable(obj, "Face1"), "the edge filter is off")

    def newFillet(self):
        """A fillet made as the command makes one with nothing selected: an empty edge list, and
        its dialog open with the list's field armed."""
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_Fillet")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no fillet dialog")
        pump(0.3)
        Gui.Control.showTaskView()
        pump(0.05)
        fillet = self.doc.getObject("Fillet")
        self.assertIsNotNone(fillet)
        self.assertEqual(fillet.Base[1], [])
        return fillet

    def pick(self, obj, sub):
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        pump(0.2)

    def testFilterRefusesOtherElements(self):
        setFilter(EDGE)
        self.assertEdgeFilterOn(self.pad)
        setFilter(FACE)
        self.assertTrue(self.selectable(self.pad, "Face1"))
        self.assertFalse(self.selectable(self.pad, "Edge1"))
        setFilter(NONE)
        self.assertTrue(self.selectable(self.pad, "Face1"))
        self.assertTrue(self.selectable(self.pad, "Edge1"))

    def testFilterPassesNonElementPicks(self):
        """Review M3 (the user's answer): the filter restricts only element picks on shapes. With
        the face filter on, an origin plane, a datum plane, the whole sketch and the whole Pad
        are taken, as a Mirror's plane or a tree selection picks them; the Pad's edge is not."""
        datum = self.body.newObject("PartDesign::Plane", "DatumPlane")
        datum.AttachmentSupport = (self.body.Origin.OriginFeatures[4], [""])  # XZ_Plane
        datum.MapMode = "FlatFace"
        self.doc.recompute()
        setFilter(FACE)
        self.assertFalse(self.selectable(self.pad, "Edge1"), "the face filter is off")
        for obj in (self.body.Origin.OriginFeatures[3], datum, self.sketch, self.pad):
            with self.subTest(obj.Name):
                self.assertTrue(self.objectSelectable(obj), "a whole object is refused")
        # Round 2 (L-b): the edge filter, which would refuse a shape's face
        setFilter(EDGE)
        self.assertFalse(self.selectable(self.pad, "Face1"), "the edge filter is off")
        self.assertTrue(self.selectable(datum, "Face1"), "a datum's element is refused")

    def testStatusBarShowsAndClearsFilter(self):
        """Review M3: while a filter is on, the status bar shows it as a button, in any workbench;
        a click removes the filter and hides the button."""
        setFilter(FACE)
        button = self.filterButton()
        self.assertIsNotNone(button, "no filter button in the status bar")
        self.assertFalse(button.isHidden())
        self.assertIn("faces", button.text())
        setFilter(EDGE)
        self.assertIn("edges", button.text())
        button.click()
        pump(0.05)
        self.assertTrue(button.isHidden())
        self.assertTrue(self.selectable(self.pad, "Face1"), "the click left the filter on")

    def testStatusBarButtonClearsOutsideA3DView(self):
        """Review round 3 (M-A): with a spreadsheet's view in front (no 3D view active, where
        Part_SelectFilter can't run), the button still clears the filter."""
        import SpreadsheetGui  # noqa: F401  the sheet's view

        setFilter(FACE)
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        self.doc.recompute()
        sheet.ViewObject.doubleClicked()
        pump(0.3)
        self.assertFalse(
            hasattr(Gui.activeView(), "getCameraNode"), "the 3D view is still the active view"
        )
        button = self.filterButton()
        self.assertFalse(button.isHidden())
        button.click()
        pump(0.05)
        self.assertTrue(button.isHidden())
        self.assertTrue(self.selectable(self.pad, "Edge1"), "the click left the filter on")

    def testStatusBarButtonStaysHiddenAfterRelayout(self):
        """Review round 2 (N1): the status bar shows every registered item again whenever an item
        is added or removed (a workbench's first activation adds some). The cleared filter's
        button stays hidden through that."""
        setFilter(FACE)
        setFilter(NONE)
        button = self.filterButton()
        self.assertIsNotNone(button, "no filter button in the status bar")
        self.assertTrue(button.isHidden())
        mainWindow = Gui.getMainWindow()
        probe = QtWidgets.QLabel("probe")
        mainWindow.addStatusBarItem(probe, id="selectionFilterProbe", title="Probe")
        pump(0.05)
        self.assertTrue(button.isHidden(), "adding an item showed the cleared filter's button")
        mainWindow.removeStatusBarItem("selectionFilterProbe")
        probe.deleteLater()
        pump(0.05)
        self.assertTrue(button.isHidden(), "removing an item showed the cleared filter's button")

    def clickAt(self, point):
        """A left click in the 3D view where the world point shows."""
        view = Gui.getDocument(self.doc.Name).ActiveView
        viewport = view.graphicsView().viewport()
        x, y = view.getPointOnViewport(point)
        _, height = view.getSize()
        scale = viewport.devicePixelRatioF()
        at = QtCore.QPoint(int(round(x / scale)), int(round((height - y - 1) / scale)))
        QtTest.QTest.mouseClick(viewport, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, at)
        pump(0.2)
        return [
            (s.ObjectName, sub)
            for s in Gui.Selection.getSelectionEx(self.doc.Name)
            for sub in (s.SubElementNames or [""])
        ]

    def testFilterPicksThroughFrontObject(self):
        """Review M1: a pick the filter refuses on the front object goes on to what lies behind
        it. Seen from the top, a 4 x 4 x 1 plate floats 5 above the top edge (y = 0) of a 10 mm
        cube; a click on the plate over that edge selects the plate's face without a filter, and
        the cube's edge with the edge filter on (the plate's faces are refused)."""
        self.body.ViewObject.Visibility = False
        cube = self.doc.addObject("Part::Box", "Cube")
        cube.Placement.Base = App.Vector(20, 0, 0)
        plate = self.doc.addObject("Part::Box", "Plate")
        plate.Length, plate.Width, plate.Height = 4, 4, 1
        plate.Placement.Base = App.Vector(23, -2, 15)
        self.doc.recompute()
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.viewTop()
        view.fitAll()
        pump(0.3)
        target = App.Vector(25, 0, 16)

        picked = self.clickAt(target)
        Gui.Selection.clearSelection()
        if not picked:
            self.skipTest("the 3D view doesn't pick here (off screen without OpenGL)")
        self.assertEqual(picked, [("Plate", "Face6")])

        setFilter(EDGE)
        picked = self.clickAt(target)
        Gui.Selection.clearSelection()
        self.assertEqual(len(picked), 1, picked)
        self.assertEqual(picked[0][0], "Cube", "the pick stopped at the front object")
        self.assertTrue(picked[0][1].startswith("Edge"), picked)

    def testFilterSurvivesOperations(self):
        """28305: the filter stays on after a Fillet's dialog and a Pad's dialog are closed."""
        setFilter(EDGE)
        fillet = self.newFillet()
        self.pick(self.pad, "Edge1")
        self.assertEqual(fillet.Base[1], ["Edge1"])
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the fillet's dialog")
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEdgeFilterOn(fillet)

        Gui.Selection.clearSelection()
        self.pad.ViewObject.doubleClicked()
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no pad dialog")
        pump(0.3)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the pad's dialog")
        self.assertEdgeFilterOn(fillet)

    def testFilletTaskAppliesFilter(self):
        """26645: inside the Fillet task a face pick is refused while the edge filter is on, and an
        edge pick while the face filter is on. Without a filter the field takes both."""
        setFilter(EDGE)
        fillet = self.newFillet()
        self.pick(self.pad, "Face1")
        self.assertEqual(fillet.Base[1], [], "a face got through the edge filter")
        self.pick(self.pad, "Edge1")
        self.assertEqual(fillet.Base[1], ["Edge1"])

        setFilter(FACE)
        self.pick(self.pad, "Edge2")
        self.assertEqual(fillet.Base[1], ["Edge1"], "an edge got through the face filter")
        self.pick(self.pad, "Face1")
        self.assertEqual(fillet.Base[1], ["Edge1", "Face1"])

        setFilter(NONE)
        self.pick(self.pad, "Edge2")
        self.assertEqual(fillet.Base[1], ["Edge1", "Face1", "Edge2"])

    def testSketchInEditIgnoresFilter(self):
        """In a sketch in edit the filter doesn't apply: its vertices stay selectable with the edge
        filter on. It applies again once the sketch is closed."""
        setFilter(EDGE)
        self.assertFalse(self.selectable(self.sketch, "Vertex1"))
        Gui.getDocument(self.doc.Name).setEdit(self.sketch.Name)
        self.assertTrue(waitFor(lambda: Gui.getDocument(self.doc.Name).getInEdit()))
        pump(0.3)
        self.assertTrue(self.selectable(self.sketch, "Vertex1"), "the filter applies in the sketch")
        Gui.getDocument(self.doc.Name).resetEdit()
        pump(0.3)
        self.assertFalse(self.selectable(self.sketch, "Vertex1"))

    def testClarifySelectionKey(self):
        """Std_ClarifySelection ("select other" under the cursor) is on backtick in FreeCAD's
        keymap. The fork's keymap (Onshape's, ops#194) gives it no key: backtick goes to Select
        other (ops#194 PR C), and the context menu and long-press stay."""
        settings = App.ParamGet("User parameter:BaseApp/Preferences/General")
        before = settings.GetString("Keymap") if "Keymap" in settings.GetStrings() else None
        settings.RemString("Keymap")
        # the defaults: a key the user stored for it comes back afterwards
        shortcuts = App.ParamGet("User parameter:BaseApp/Preferences/Shortcut")
        stored = "Std_ClarifySelection" in shortcuts.GetStrings()
        storedKey = shortcuts.GetString("Std_ClarifySelection") if stored else None
        shortcuts.RemString("Std_ClarifySelection")
        pump(0.1)
        try:
            self.assertEqual(Gui.Command.get("Std_ClarifySelection").getShortcut(), "")
            settings.SetString("Keymap", "FreeCAD")
            pump(0.1)
            self.assertEqual(Gui.Command.get("Std_ClarifySelection").getShortcut(), "`")
        finally:
            if before is None:
                settings.RemString("Keymap")
            else:
                settings.SetString("Keymap", before)
            if stored:
                shortcuts.SetString("Std_ClarifySelection", storedKey)
            pump(0.1)
