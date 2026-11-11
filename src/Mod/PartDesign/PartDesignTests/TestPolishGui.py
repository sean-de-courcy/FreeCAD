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


class SketchCase(PolishCase):
    """The pad's sketch with a Distance (10) and a Horizontal on line 0 after its four corner
    coincidents (0 to 3), opened by openSketch(); the sketch preferences tests set are removed."""

    def setUp(self):
        super().setUp()
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowConstraints")
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowErrors")
        self.distance = self.sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10.0))
        self.horizontal = self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.doc.recompute()

    def tearDown(self):
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
            pump(0.2)
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowConstraints")
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowErrors")
        super().tearDown()

    def openSketch(self):
        Gui.ActiveDocument.setEdit(self.sketch.Name)
        pump(0.3)
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit(), "the sketch must be in edit")


class TestShowConstraintsGui(SketchCase):
    """P1, P1b: inside a sketch Onshape draws no constraint glyph until the sketch dialog's "Show
    constraints" is on; the dimensions are always drawn, and so are a hovered entity's own
    constraints (not a selected one's: notes/onshape-facts.md PL1b), kept a moment after the hover
    leaves; the conflicting ones only with "Show errors" on (PL1d). What is drawn is read from the sketch's constraint switchboard (the node
    "ConstraintGroup", one switch per constraint), the one the change drives. The pad's sketch
    gets a Distance and a Horizontal on line 0 after its four corner coincidents (0 to 3):
    coincidents 0 (line 0's end) and 3 (line 0's start) are line 0's, 1 and 2 are not."""

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

    def screenPoint(self, sketchPoint):
        """The view's widget point over a point of the sketch's plane."""
        global_point = self.sketch.getGlobalPlacement().multVec(sketchPoint)
        x, y = self.view.getPointOnViewport(global_point)
        viewport = self.view.graphicsView().viewport()
        ratio = viewport.devicePixelRatioF()
        return QtCore.QPoint(round(x / ratio), round(viewport.height() - y / ratio))

    def hoverLine0(self):
        """Hovers line 0 a quarter along it (its dimension's label sits at its middle)."""
        line = self.sketch.Geometry[0]
        self.hover(QtCore.QPoint(5, 5))
        self.hover(self.screenPoint(line.StartPoint + (line.EndPoint - line.StartPoint) * 0.25))

    def testHoveredLineDrawsItsOwnConstraints(self):
        self.openSketch()
        self.hoverLine0()
        drawn = self.drawn()
        self.assertTrue(drawn[self.horizontal], "the hovered line's horizontal is drawn")
        self.assertTrue(drawn[self.distance])
        self.assertEqual(drawn[:4], [True, False, False, True], "the line's own coincidents only")
        self.hover(QtCore.QPoint(5, 5))
        self.assertTrue(self.drawn()[self.horizontal], "kept a moment after the hover leaves")
        pump(1.2)
        drawn = self.drawn()
        self.assertFalse(drawn[self.horizontal], "hidden again once the hover is gone")
        self.assertEqual(drawn[:4], [False] * 4)

    def testSelectedLineDrawsNoGlyph(self):
        """Onshape: selecting a line shows none of its constraints (only hovering does)."""
        self.openSketch()
        Gui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge1")
        pump()
        drawn = self.drawn()
        self.assertFalse(drawn[self.horizontal])
        self.assertEqual(drawn[:4], [False] * 4)

    def testShowErrorsDrawsTheConflictingConstraints(self):
        """A Vertical on the horizontal line 0 conflicts: its glyphs only with Show errors on."""
        vertical = self.sketch.addConstraint(Sketcher.Constraint("Vertical", 0))
        self.doc.recompute()
        conflicting = [n - 1 for n in self.sketch.ConflictingConstraints]
        self.assertTrue(conflicting, "Expected the solver to report the conflict")
        self.assertTrue(set(conflicting) <= {self.horizontal, vertical})
        self.openSketch()
        drawn = self.drawn()
        self.assertFalse(drawn[self.horizontal] or drawn[vertical], "Show errors is off")
        App.ParamGet(SKETCHER_GENERAL).SetBool("ShowErrors", True)
        pump()
        drawn = self.drawn()
        self.assertTrue(all(drawn[i] for i in conflicting), "the conflicting glyphs are drawn")
        self.assertEqual(drawn[:4], [False] * 4, "the other glyphs stay hidden")

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


class TestSketchDialogCheckboxesGui(SketchCase):
    """P4, P1b: Onshape's sketch dialog holds, in this order, Disable imprinting, Show
    constraints, Show expressions and Show errors. Disable imprinting is the sketch's own (its
    property DisableImprinting, one undo step; what it does to the regions is in
    TestProfileRegions); Show expressions is the user's (Mod/Sketcher/General/ShowExpressions,
    off by default): a dimension set by an expression then reads the expression, not its value.
    The pad's sketch gets the Distance of line 0 bound to "4 mm * 2.5"."""

    def setUp(self):
        super().setUp()
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowExpressions")
        self.sketch.setExpression(f"Constraints[{self.distance}]", "4 mm * 2.5")
        self.doc.recompute()

    def tearDown(self):
        App.ParamGet(SKETCHER_GENERAL).RemBool("ShowExpressions")
        super().tearDown()

    def box(self, name):
        box = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, name)
        self.assertIsNotNone(box, f"Expected the {name} box in the Sketch Edit panel")
        return box

    def labels(self):
        """The texts of the sketch's datum labels (one per dimension), as one string."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoType.fromName("SoDatumLabel"))
        search.setSearchingAll(True)
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(self.sketch.ViewObject.RootNode)
        paths = search.getPaths()
        texts = [paths[i].getTail().getField("string").get() for i in range(paths.getLength())]
        self.assertTrue(texts, "Expected the Distance's datum label in edit")
        return " | ".join(texts)

    def testBoxesInOnshapesOrder(self):
        self.openSketch()
        names = ["disableImprinting", "showConstraints", "showExpressions", "showErrors"]
        boxes = [self.box(name) for name in names]
        layout = boxes[0].parentWidget().layout()
        self.assertEqual([layout.indexOf(b) for b in boxes], sorted(layout.indexOf(b) for b in boxes))
        self.assertEqual([b.isChecked() for b in boxes], [False] * 4, "Onshape's defaults: all off")

    def testDisableImprintingSetsTheSketchsProperty(self):
        self.openSketch()
        box = self.box("disableImprinting")
        box.setChecked(True)
        pump()
        self.assertTrue(self.sketch.DisableImprinting)
        self.assertEqual(self.doc.UndoNames[0], "Disable imprinting", "one undo step")
        box.setChecked(False)
        pump()
        self.assertFalse(self.sketch.DisableImprinting)

    def testValueShownByDefault(self):
        self.openSketch()
        labels = self.labels()
        self.assertIn("10", labels)
        self.assertNotIn("*", labels)

    def testShowExpressionsShowsTheExpression(self):
        self.openSketch()
        self.box("showExpressions").setChecked(True)
        pump()
        self.assertTrue(App.ParamGet(SKETCHER_GENERAL).GetBool("ShowExpressions", False))
        labels = self.labels()
        self.assertIn("* 2.5", labels, "the open sketch redraws its label with the expression tag")
        tag, _, value = labels.partition("
")
        self.assertIn("* 2.5", tag, "the expression is the tag, the first line")
        self.assertIn("10", value, "Onshape keeps the value under the tag (PL5a)")
        self.box("showExpressions").setChecked(False)
        pump()
        self.assertNotIn("*", self.labels())


class TestShellWordsGui(PolishCase):
    """P10: Onshape's Shell dialog reads "Faces to remove", Thickness, then "Opposite direction",
    unticked for the default inward wall (FreeCAD's "Make thickness inwards" was ticked for it).
    The shell removes the pad's top face (Face6), 1 mm inwards (Reversed)."""

    def setUp(self):
        super().setUp()
        self.shell = self.body.newObject("PartDesign::Thickness", "Shell")
        self.shell.Base = (self.pad, ["Face6"])
        self.shell.Value = 1
        self.shell.Reversed = True
        self.doc.recompute()
        Gui.ActiveDocument.setEdit(self.shell.Name)
        pump(0.3)

    def widget(self, cls, name):
        dialog = Gui.Control.activeDialog()
        self.assertTrue(dialog, "Expected the Shell dialog open")
        found = Gui.getMainWindow().findChild(cls, name)
        self.assertIsNotNone(found, f"Expected {name} in the Shell dialog")
        return found

    def testOnshapesWords(self):
        field = self.widget(QtWidgets.QWidget, "fieldBase")
        self.assertEqual(field.findChild(QtWidgets.QLabel, "label").text(), "Faces to remove")
        box = self.widget(QtWidgets.QCheckBox, "checkReverse")
        self.assertEqual(box.text(), "Opposite direction")
        self.assertFalse(box.isChecked(), "the default inward wall: Opposite direction unticked")
        value = self.widget(QtWidgets.QWidget, "Value")
        mode = self.widget(QtWidgets.QComboBox, "modeComboBox")
        top = lambda w: w.mapTo(Gui.getMainWindow(), QtCore.QPoint(0, 0)).y()
        self.assertLess(top(value), top(box), "Thickness, then Opposite direction")
        self.assertLess(top(box), top(mode), "before FreeCAD's own Mode")

    def testOppositeDirectionGrowsOutwards(self):
        inward = self.shell.Shape.Volume
        self.widget(QtWidgets.QCheckBox, "checkReverse").setChecked(True)
        pump(0.2)
        self.assertFalse(self.shell.Reversed)
        self.assertGreater(self.shell.Shape.Volume, inward)


class TestWindowLeftoversGui(PolishCase):
    """P9: Onshape's window has no Properties panel beside the Feature list, a short Help menu,
    and no command boxes in the panel when no dialog is open (FreeCAD's PartDesign task watchers,
    e.g. the face tools for a selected face). The menu and the watchers are built when the
    workbench is activated, so the keymap is set first and the workbench activated again."""

    def reactivate(self, keymap=None):
        if keymap:
            App.ParamGet(KEYMAP).SetString("Keymap", keymap)
        Gui.activateWorkbench("NoneWorkbench")
        pump()
        Gui.activateWorkbench("PartDesignWorkbench")
        pump(0.2)

    def tearDown(self):
        super().tearDown()
        self.reactivate()  # the default keymap's menu and watchers for the next tests

    def helpCommands(self):
        for action in Gui.getMainWindow().menuBar().actions():
            menu = action.menu()
            if menu and action.text().replace("&", "") == "Help":
                return [a.objectName() for a in menu.actions() if not a.isSeparator()]
        self.fail("Expected a Help menu")

    def watcherBoxes(self):
        """The task panel's visible boxes while no dialog is open."""
        self.assertIsNone(Gui.Control.activeDialog())
        boxes = []
        for widget in QtWidgets.QApplication.allWidgets():
            name = widget.metaObject().className()
            if name.endswith("TaskBox") and widget.isVisible():
                boxes.append(widget)
        return boxes

    def selectTopFace(self):
        Gui.Selection.addSelection(self.doc.Name, self.pad.Name, "Face6")
        pump(0.3)

    def testOnshapeHelpMenuIsShort(self):
        self.reactivate()
        commands = self.helpCommands()
        self.assertIn("Std_About", commands)
        for command in ("Std_WhatsThis", "Std_FreeCADDonation", "Std_DevHandbook"):
            self.assertNotIn(command, commands)

    def testFreeCADKeymapKeepsTheHelpMenu(self):
        self.reactivate("FreeCAD")
        commands = self.helpCommands()
        self.assertIn("Std_WhatsThis", commands)
        self.assertIn("Std_FreeCADDonation", commands)

    def testOnshapeShowsNoWatcherBoxes(self):
        self.reactivate()
        self.selectTopFace()
        self.assertEqual(self.watcherBoxes(), [], "no command boxes with no dialog open")

    def testFreeCADKeymapShowsTheFaceTools(self):
        """The control: FreeCAD's keymap shows its watcher boxes for a selected face."""
        self.reactivate("FreeCAD")
        self.selectTopFace()
        self.assertTrue(self.watcherBoxes(), "Expected FreeCAD's watcher boxes for a face")

    def testNoPropertyPanelInTheModelPanel(self):
        """The left panel's property editor is hidden. The combo view is built at start-up,
        under the keymap of the test's user home: the default, Onshape's."""
        combos = [
            w for w in QtWidgets.QApplication.allWidgets()
            if w.metaObject().className().endswith("ComboView")
        ]
        self.assertTrue(combos, "Expected the Model panel (combo view)")
        props = [
            w for w in combos[0].findChildren(QtWidgets.QWidget)
            if w.metaObject().className() == "Gui::PropertyView"
        ]
        self.assertTrue(props, "Expected the combo view's property editor")
        self.assertTrue(props[0].isHidden())
