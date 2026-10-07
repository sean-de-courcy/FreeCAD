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
        App.closeDocument(self.doc.Name)
        pump()

    def selectable(self, obj, sub):
        """Whether a pick of obj.sub is taken by the selection (then cleared again)."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        taken = any(sub in s.SubElementNames for s in Gui.Selection.getSelectionEx(self.doc.Name))
        Gui.Selection.clearSelection()
        return taken

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
        """Std_ClarifySelection ("select other" under the cursor) is on one key, as in Onshape."""
        self.assertEqual(Gui.Command.get("Std_ClarifySelection").getShortcut(), "`")
