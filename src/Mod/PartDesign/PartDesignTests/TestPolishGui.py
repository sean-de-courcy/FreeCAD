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

"""Onshape's look and feel, polish 1 (FreeCAD-CH, ops#640; notes/onshape-gui-plan.md "Polish 1").

One class per item of the plan's table (P1, P3, ...). Designed model: a Body with a Pad of a
10 x 10 square on XY, seen from the top, so the middle of the view shows the pad's top face.
The fork's keymap, Onshape, is the default (no General/Keymap value); a test that needs FreeCAD's
behaviour as the control sets General/Keymap = FreeCAD and removes it again."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
import Sketcher

from PySide import QtCore, QtGui, QtWidgets

KEYMAP = "User parameter:BaseApp/Preferences/General"  # the preference Keymap (ForkKeymap)


def pump(seconds=0.1):
    end = time.monotonic() + seconds
    while True:
        QtWidgets.QApplication.processEvents()
        if time.monotonic() >= end:
            break
        time.sleep(0.01)


def squareSketch(body, size, name):
    """A sketch of a size x size square on the body's XY plane, its corners coincident."""
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.AttachmentSupport = (body.Origin.OriginFeatures[3], [""])  # XY_Plane
    sketch.MapMode = "FlatFace"
    corners = [(0, 0), (size, 0), (size, size), (0, size)]
    for (ax, ay), (bx, by) in zip(corners, corners[1:] + corners[:1]):
        sketch.addGeometry(Part.LineSegment(App.Vector(ax, ay, 0), App.Vector(bx, by, 0)), False)
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    return sketch


class PolishCase(unittest.TestCase):
    """The pad model in a shown main window, the keymap's saved value restored afterwards."""

    @classmethod
    def setUpClass(cls):
        Gui.getMainWindow().show()
        Gui.activateWorkbench("PartDesignWorkbench")
        group = App.ParamGet(KEYMAP)
        cls.savedKeymap = group.GetString("Keymap") if "Keymap" in group.GetStrings() else None
        pump()

    @classmethod
    def tearDownClass(cls):
        group = App.ParamGet(KEYMAP)
        if cls.savedKeymap is None:
            group.RemString("Keymap")
        else:
            group.SetString("Keymap", cls.savedKeymap)
        pump()

    def setUp(self):
        App.ParamGet(KEYMAP).RemString("Keymap")
        self.doc = App.newDocument(type(self).__name__)
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.sketch = squareSketch(self.body, 10, "Sketch")
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.sketch
        self.pad.Length = 5
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        self.view = Gui.ActiveDocument.ActiveView
        self.view.setAnimationEnabled(False)
        self.view.viewTop()
        self.view.fitAll()
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        pump(0.2)

    def tearDown(self):
        App.ParamGet(KEYMAP).RemString("Keymap")
        Gui.Selection.clearSelection()
        Gui.Selection.clearPreselection()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        App.closeDocument(self.doc.Name)
        pump()

    def middle(self):
        width, height = self.view.getSize()
        return QtCore.QPoint(width // 2, height // 2)

    def hover(self, point):
        """Moves the pointer over the view to the widget point, as the motion event a real
        pointer sends: the view's hover pick sets the preselection (SoFCUnifiedSelection)."""
        viewport = self.view.graphicsView().viewport()
        event = QtGui.QMouseEvent(
            QtCore.QEvent.MouseMove,
            QtCore.QPointF(point),
            QtCore.QPointF(viewport.mapToGlobal(point)),
            QtCore.Qt.NoButton,
            QtCore.Qt.NoButton,
            QtCore.Qt.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(viewport, event)
        pump(0.1)

    def preselectedElement(self):
        sel = Gui.Selection.getPreselection()
        if not sel.ObjectName:
            return None
        return sel.SubElementNames[0].split(".")[-1]


class TestHoverStatusGui(PolishCase):
    """P3: Onshape shows nothing technical at the bottom of the window on hover; FreeCAD prints
    "Preselected: <doc>.<object>.<element> (x, y, z)" for every element under the pointer. Under
    the Onshape keymap the hover still preselects (the tint) but writes no such message."""

    def statusAfterHover(self):
        statusBar = Gui.getMainWindow().statusBar()
        statusBar.clearMessage()
        Gui.Selection.clearPreselection()
        pump()
        self.hover(QtCore.QPoint(5, 5))  # off the pad first, so the next move is a new hover
        self.hover(self.middle())
        self.assertEqual(self.preselectedElement(), "Face6", "the hover pick must find the top face")
        return statusBar.currentMessage()

    def testOnshapeHoverWritesNoPreselectedMessage(self):
        self.assertNotIn("Preselected", self.statusAfterHover())

    def testFreeCADKeymapKeepsTheMessage(self):
        """The control: the same hover under FreeCAD's keymap prints FreeCAD's message."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        self.assertIn("Preselected", self.statusAfterHover())


SKETCHER_GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"


class TestShowConstraintsGui(PolishCase):
    """P1: inside a sketch Onshape draws no constraint glyph until the sketch dialog's "Show
    constraints" is on; the dimensions are always drawn, and so are a selected entity's own
    constraints. What is drawn is read from the sketch's constraint switchboard (the node
    "ConstraintGroup", one switch per constraint), the one the change drives. The pad's sketch
    gets a Distance and a Horizontal on line 0 after its four corner coincidents (0 to 3):
    coincidents 0 (line 0's end) and 3 (line 0's start) are line 0's, 1 and 2 are not."""

    def setUp(self):
        super().setUp()
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowConstraints")
        self.distance = self.sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10.0))
        self.horizontal = self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.doc.recompute()

    def tearDown(self):
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
            pump(0.2)
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowConstraints")
        super().tearDown()

    def openSketch(self):
        Gui.ActiveDocument.setEdit(self.sketch.Name)
        pump(0.3)
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit(), "the sketch must be in edit")

    def drawn(self):
        """Whether each constraint is drawn: its switch in the switchboard."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setName("ConstraintGroup")
        search.setSearchingAll(True)
        search.apply(self.sketch.ViewObject.RootNode)
        path = search.getPath()
        self.assertIsNotNone(path, "Expected the sketch's constraint switchboard in edit")
        enable = [bool(v) for v in path.getTail().getField("enable").getValues()]
        self.assertEqual(len(enable), len(self.sketch.Constraints))
        return enable

    def testOnshapeDrawsOnlyTheDimensions(self):
        self.openSketch()
        drawn = self.drawn()
        self.assertTrue(drawn[self.distance], "a dimension is always drawn")
        self.assertFalse(drawn[self.horizontal], "Onshape draws no horizontal glyph by default")
        self.assertEqual(drawn[:4], [False] * 4, "nor the coincidents")

    def testSelectedLineDrawsItsOwnConstraints(self):
        self.openSketch()
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge1")
        pump()
        drawn = self.drawn()
        self.assertTrue(drawn[self.horizontal], "the selected line's horizontal is drawn")
        self.assertTrue(drawn[self.distance])
        self.assertEqual(drawn[:4], [True, False, False, True], "the line's own coincidents only")
        Gui.Selection.clearSelection()
        pump()
        drawn = self.drawn()
        self.assertFalse(drawn[self.horizontal], "hidden again once the line is unselected")
        self.assertEqual(drawn[:4], [False] * 4)

    def testSelectedConstraintIsDrawn(self):
        self.openSketch()
        constraint = f"Constraint{self.horizontal + 1}"
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, constraint)
        pump()
        drawn = self.drawn()
        self.assertTrue(drawn[self.horizontal])
        self.assertEqual(drawn[:4], [False] * 4)

    def testShowConstraintsDrawsAll(self):
        App.ParamGet(SKETCHER_GENERAL).SetBool("ShowConstraints", True)
        self.openSketch()
        self.assertTrue(all(self.drawn()))

    def testPreferenceChangeRedrawsTheOpenSketch(self):
        self.openSketch()
        self.assertFalse(self.drawn()[self.horizontal])
        App.ParamGet(SKETCHER_GENERAL).SetBool("ShowConstraints", True)
        pump()
        self.assertTrue(all(self.drawn()))
        App.ParamGet(SKETCHER_GENERAL).SetBool("ShowConstraints", False)
        pump()
        self.assertFalse(self.drawn()[self.horizontal])

    def testCheckboxInTheSketchDialog(self):
        """The "Show constraints" box under the solver's message, bound to the preference."""
        self.openSketch()
        box = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "showConstraints")
        self.assertIsNotNone(box, "Expected the Show constraints box in the Sketch Edit panel")
        self.assertFalse(box.isChecked())
        box.setChecked(True)
        pump()
        self.assertTrue(App.ParamGet(SKETCHER_GENERAL).GetBool("ShowConstraints", False))
        self.assertTrue(all(self.drawn()))

    def testFreeCADKeymapDrawsAll(self):
        """The control: FreeCAD's keymap keeps FreeCAD's every glyph drawn."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        self.openSketch()
        self.assertTrue(all(self.drawn()))
