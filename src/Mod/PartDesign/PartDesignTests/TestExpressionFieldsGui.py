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

from PySide import QtWidgets


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
        self.sheet.set("A1", "15")
        self.doc.recompute()
        pump()
        self.assertAlmostEqual(widget.property("rawValue"), 12.0, places=6)
        self.assertAlmostEqual(self.pad.Length.Value, 12.0, places=6)
        self.assertFalse(widget.property("readOnly"))
