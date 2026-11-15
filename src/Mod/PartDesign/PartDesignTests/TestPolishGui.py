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
        # MainWindow::showMessage writes to a label in the status bar, not its own message
        labels = Gui.getMainWindow().statusBar().findChildren(QtWidgets.QLabel)
        for label in labels:
            label.setText("")
        Gui.Selection.clearPreselection()
        pump()
        self.hover(QtCore.QPoint(5, 5))  # off the pad first, so the next move is a new hover
        self.hover(self.middle())
        self.assertEqual(self.preselectedElement(), "Face6", "the hover pick must find the top face")
        return " | ".join(label.text() for label in labels)

    def testOnshapeHoverWritesNoPreselectedMessage(self):
        self.assertNotIn("Preselected", self.statusAfterHover())

    def testFreeCADKeymapKeepsTheMessage(self):
        """The control: the same hover under FreeCAD's keymap prints FreeCAD's message."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        self.assertIn("Preselected", self.statusAfterHover())


SKETCHER_GENERAL = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"


def visibleBox(name):
    """The shown check box of that name: a closed dialog's widgets may linger until deleted."""
    boxes = [
        b for b in Gui.getMainWindow().findChildren(QtWidgets.QCheckBox, name) if b.isVisible()
    ]
    if not boxes:
        raise AssertionError(f"Expected the {name} box in the Sketch Edit panel")
    return boxes[-1]


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
        search.apply(self.view.getSceneGraph())  # the edit nodes are in the viewer's EditingRoot
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
        self.assertTrue({self.horizontal, vertical} & set(conflicting))
        dimensions = [i == self.distance for i in range(len(self.sketch.Constraints))]
        self.openSketch()
        self.assertEqual(self.drawn(), dimensions, "Show errors is off: the dimension only")
        App.ParamGet(SKETCHER_GENERAL).SetBool("ShowErrors", True)
        pump()
        expected = [d or i in conflicting for i, d in enumerate(dimensions)]
        self.assertEqual(self.drawn(), expected, "the dimension and the solver's conflicting ones")

    def iconPixels(self):
        """Every constraint glyph's pixels (r, g, b, a), from the constraints' SoImage nodes: pivy
        can't return an image's bytes, so each node is written as Inventor text (hex pixels)."""
        import os
        import re
        import tempfile

        from pivy import coin

        search = coin.SoSearchAction()
        search.setName("ConstraintGroup")
        search.setSearchingAll(True)
        search.apply(self.view.getSceneGraph())
        board = search.getPath().getTail()
        images = coin.SoSearchAction()
        images.setType(coin.SoImage.getClassTypeId())
        images.setInterest(coin.SoSearchAction.ALL)
        images.setSearchingAll(True)
        images.apply(board)
        pixels = []
        handle, path = tempfile.mkstemp(suffix=".iv")
        os.close(handle)
        try:
            for i in range(images.getPaths().getLength()):
                out = coin.SoOutput()
                self.assertTrue(out.openFile(path))
                coin.SoWriteAction(out).apply(images.getPaths()[i].getTail())
                out.closeFile()
                with open(path, encoding="latin-1") as text:
                    found = re.search(r"image\s+(\d+)\s+(\d+)\s+(\d+)([^}]*)", text.read())
                if not found or int(found.group(3)) != 4:
                    continue
                for value in re.findall(r"0x[0-9a-fA-F]+", found.group(4)):
                    v = int(value, 16)
                    pixels.append((v >> 24 & 255, v >> 16 & 255, v >> 8 & 255, v & 255))
        finally:
            os.remove(path)
        return pixels

    @staticmethod
    def badgeRed(pixels):
        """The pixels of Onshape's badge red (PL1d, about #D66E74), opaque."""
        return [p for p in pixels if p[3] > 200 and abs(p[0] - 0xD6) < 12 and abs(p[1] - 0x6E) < 12 and abs(p[2] - 0x74) < 12]

    def testShowErrorsDrawsTheConflictOnARedBadge(self):
        """Show errors draws a conflicting constraint's glyph white on a red-filled badge (PL1d);
        with Show errors off the glyphs (all drawn: Show constraints on) have no badge (ops#640)."""
        App.ParamGet(SKETCHER_GENERAL).SetBool("ShowConstraints", True)
        self.sketch.addConstraint(Sketcher.Constraint("Vertical", 0))
        self.doc.recompute()
        self.assertTrue(self.sketch.ConflictingConstraints, "Expected the solver to report the conflict")
        self.openSketch()
        pixels = self.iconPixels()
        self.assertTrue(pixels, "Expected the glyphs' images")
        self.assertEqual(self.badgeRed(pixels), [], "Show errors off: no badge")
        App.ParamGet(SKETCHER_GENERAL).SetBool("ShowErrors", True)
        pump()
        pixels = self.iconPixels()
        self.assertGreater(len(self.badgeRed(pixels)), 20, "the conflicting glyph's red badge")
        self.assertTrue(
            [p for p in pixels if p[3] > 200 and min(p[:3]) > 240], "its icon is drawn white"
        )

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
        box = visibleBox("showConstraints")
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


class TestSketchDialogTitleGui(SketchCase):
    """PL1d: under the Onshape keymap the sketch dialog's title reads red while the sketch could not
    be solved (a Vertical on the Horizontal line 0); removing the conflict brings the scheme's colour
    back; the FreeCAD keymap keeps it (ops#640)."""

    def title(self):
        for frame in Gui.getMainWindow().findChildren(QtWidgets.QFrame):
            if frame.metaObject().className() == "QSint::TaskHeader" and frame.isVisible():
                button = frame.findChild(QtWidgets.QToolButton)
                if button is not None and button.text() == "Sketch Edit":
                    return button
        self.fail("Expected the sketch dialog's title")

    def addConflict(self):
        vertical = self.sketch.addConstraint(Sketcher.Constraint("Vertical", 0))
        self.doc.recompute()
        self.assertIn(vertical + 1, self.sketch.ConflictingConstraints)
        return vertical

    def testConflictTurnsTheTitleRed(self):
        vertical = self.addConflict()
        self.openSketch()
        self.assertIn("#AA252D", self.title().styleSheet())
        self.sketch.delConstraint(vertical)
        self.sketch.solve()
        self.doc.recompute()
        pump(0.3)
        self.assertEqual(self.title().styleSheet(), "")

    def testSolvedSketchKeepsTheTitle(self):
        self.openSketch()
        self.assertEqual(self.title().styleSheet(), "")

    def testFreeCADKeymapKeepsTheTitle(self):
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        self.addConflict()
        self.openSketch()
        self.assertEqual(self.title().styleSheet(), "")


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
        return visibleBox(name)

    def labels(self):
        """The texts of the sketch's datum labels (one per dimension), as one string."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setType(coin.SoType.fromName("SoDatumLabel"))
        search.setSearchingAll(True)
        search.setInterest(coin.SoSearchAction.ALL)
        search.apply(self.view.getSceneGraph())  # the edit nodes are in the viewer's EditingRoot
        paths = search.getPaths()
        texts = []
        for i in range(paths.getLength()):
            text = paths[i].getTail().getField("string").get()  # an SbString: its text form
            texts.append(text.getString() if hasattr(text, "getString") else str(text))
        self.assertTrue(texts, "Expected the Distance's datum label in edit")
        return " | ".join(texts)

    def testBoxesInOnshapesOrder(self):
        self.openSketch()
        names = ["disableImprinting", "showConstraints", "showExpressions", "showErrors"]
        boxes = [self.box(name) for name in names]
        window = Gui.getMainWindow()
        tops = [b.mapTo(window, QtCore.QPoint(0, 0)).y() for b in boxes]
        self.assertEqual(tops, sorted(tops), "top to bottom in Onshape's order")
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
        tag, _, value = labels.partition("\n")
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
    """P9: Onshape's window has a short Help menu and no command boxes in the panel when no
    dialog is open (FreeCAD's PartDesign task watchers, e.g. the face tools for a selected face). The menu and the watchers are built when the
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
        self.assertFalse(Gui.Control.activeDialog())
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


class TestFlatFeatureDialogGui(PolishCase):
    """P5: under the Onshape keymap a feature dialog is one flat form under its title row: only
    the title box shows a header, the overlay switch is gone (its opacity is the Preview row), and
    Final is offered only while a later feature exists. FreeCAD's keymap keeps its boxes."""

    def openEdit(self, feature):
        Gui.ActiveDocument.setEdit(feature.Name)
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), f"Expected {feature.Name}'s dialog open")

    def visible(self, cls, name=None):
        found = Gui.getMainWindow().findChildren(cls, name) if name else Gui.getMainWindow().findChildren(cls)
        return [w for w in found if w.isVisible()]

    def headers(self):
        return [
            w for w in self.visible(QtWidgets.QFrame) if w.metaObject().className() == "QSint::TaskHeader"
        ]

    def testOnshapeShowsOneHeader(self):
        self.openEdit(self.pad)
        headers = self.headers()
        self.assertEqual(len(headers), 1, "only the title row")
        names = [b.text() for b in headers[0].findChildren(QtWidgets.QToolButton)]
        self.assertIn(self.pad.Label, names, "the title row is the feature's name")
        self.assertEqual(self.visible(QtWidgets.QCheckBox, "showTransparentPreviewCheckBox"), [])
        label = Gui.getMainWindow().findChild(QtWidgets.QLabel, "opacityLabel")
        self.assertTrue(label.isVisible())
        self.assertEqual(label.text(), "Preview")

    def testOnshapeOffersNoFinalOnTheLastFeature(self):
        self.openEdit(self.pad)
        self.assertEqual(self.visible(QtWidgets.QCheckBox, "showFinalCheckBox"), [], "the last feature: no Final")

    def testOnshapeOffersFinalMidList(self):
        later = self.body.newObject("PartDesign::Pocket", "Pocket")
        later.Profile = squareSketch(self.body, 4, "Sketch001")
        self.doc.recompute()
        self.openEdit(self.pad)
        final = self.visible(QtWidgets.QCheckBox, "showFinalCheckBox")
        self.assertEqual(len(final), 1, "a later feature: Final offered")
        self.assertEqual(final[0].text(), "Final")

    def testFreeCADKeymapKeepsTheBoxes(self):
        """The control: FreeCAD's keymap keeps the parameter, Result and Preview headers."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        self.openEdit(self.pad)
        self.assertGreater(len(self.headers()), 1)
        self.assertEqual(len(self.visible(QtWidgets.QCheckBox, "showTransparentPreviewCheckBox")), 1)


class TestTitleRenameGui(PolishCase):
    """P13 (notes/onshape-facts.md PL3a): Onshape renames a feature in its dialog. A pencil, hidden
    until the title row is hovered, turns the title into a text box: Enter renames, Esc keeps the
    name and the dialog. A feature in error: the title red (#AA252D) with the tooltip "<name> did
    not regenerate properly: <why>". FreeCAD's keymap has no pencil."""

    def openEdit(self, feature):
        Gui.ActiveDocument.setEdit(feature.Name)
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), f"Expected {feature.Name}'s dialog open")

    def titleRow(self):
        for frame in Gui.getMainWindow().findChildren(QtWidgets.QFrame):
            if frame.isVisible() and frame.metaObject().className() == "QSint::TaskHeader":
                return frame
        self.fail("Expected the dialog's title row")

    def pencil(self):
        return self.titleRow().findChild(QtWidgets.QToolButton, "FreeCAD-CH rename title")

    def titles(self):
        return [b.text() for b in self.titleRow().findChildren(QtWidgets.QToolButton) if b.isVisible()]

    def startRename(self):
        self.openEdit(self.pad)
        pencil = self.pencil()
        self.assertIsNotNone(pencil, "Expected the rename pencil in the title row")
        self.assertFalse(pencil.isVisible(), "hidden until the title row is hovered")
        QtWidgets.QApplication.sendEvent(self.titleRow(), QtCore.QEvent(QtCore.QEvent.Enter))
        pump()
        self.assertTrue(pencil.isVisible(), "shown while the title row is hovered")
        pencil.click()
        pump()
        box = self.titleRow().findChild(QtWidgets.QLineEdit, "FreeCAD-CH rename box")
        self.assertTrue(box.isVisible(), "the pencil opens the rename box")
        self.assertEqual(box.text(), "Pad")
        self.assertNotIn("Pad", self.titles(), "the box takes the title's place")
        return box

    def testEnterRenamesAndOkKeepsIt(self):
        from PySide6 import QtTest
        from PartDesignTests.TestExpressionFieldsGui import taskButton, waitFor

        box = self.startRename()
        box.selectAll()
        QtTest.QTest.keyClicks(box, "Lid")
        QtTest.QTest.keyClick(box, QtCore.Qt.Key_Return)
        pump(0.2)
        self.assertEqual(self.pad.Label, "Lid")
        self.assertFalse(box.isVisible())
        self.assertTrue(waitFor(lambda: "Lid" in self.titles()), "the title shows the new name")
        self.assertTrue(Gui.Control.activeDialog(), "Enter in the box doesn't accept the dialog")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        self.assertEqual(self.pad.Label, "Lid", "OK keeps the new name")

    def testEscKeepsTheNameAndTheDialog(self):
        from PySide6 import QtTest

        box = self.startRename()
        box.setText("Lid")
        QtTest.QTest.keyClick(box, QtCore.Qt.Key_Escape)
        pump(0.2)
        self.assertEqual(self.pad.Label, "Pad")
        self.assertFalse(box.isVisible())
        self.assertIn("Pad", self.titles())
        self.assertTrue(Gui.Control.activeDialog(), "Esc in the box doesn't close the dialog")

    def testFeatureInErrorHasOnshapesRedAndTooltip(self):
        self.pad.Length = 0
        self.doc.recompute()
        self.assertFalse(self.pad.isValid(), "a zero-length pad is in error")
        self.openEdit(self.pad)
        [title] = [
            b for b in self.titleRow().findChildren(QtWidgets.QToolButton)
            if b.isVisible() and b.text() == "Pad"
        ]
        self.assertIn("#AA252D", title.styleSheet())
        self.assertTrue(
            title.toolTip().startswith("Pad did not regenerate properly: "), title.toolTip()
        )

    def testFreeCADKeymapHasNoPencil(self):
        """The control: FreeCAD's keymap renames in the lists only."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        self.openEdit(self.pad)
        self.assertIsNone(
            Gui.getMainWindow().findChild(QtWidgets.QToolButton, "FreeCAD-CH rename title")
        )


class TestDoubleClickCreatorGui(PolishCase):
    """P8: under the Onshape keymap a double click on a face selects nothing and tints the feature
    that made it, and that feature's sketch, in the Features list (and the feature's faces in the
    view) until the selection changes. FreeCAD's keymap tints nothing."""

    def setUp(self):
        super().setUp()
        self.param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        self.savedTree = self.param.GetBool("ShowModelTree", False)
        if self.savedTree:
            Gui.runCommand("PartDesign_ToggleModelTree")  # the lists in place of the tree
        model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
        if model is not None:
            model.show()
        # A 4 x 4 boss on the 10 x 10 pad, up to z = 10: seen from the top its face lies at
        # (2, 2, 10) and the pad's own top face at (7, 7, 5)
        self.boss = self.body.newObject("PartDesign::Pad", "Pad001")
        self.boss.Profile = squareSketch(self.body, 4, "Sketch001")
        self.boss.Length = 10
        self.doc.recompute()
        self.view.viewTop()
        self.view.fitAll()
        pump(0.4)
        features = Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")
        self.assertIsNotNone(features)
        self.list = features.findChild(QtWidgets.QListWidget, "featureList")
        self.assertIsNotNone(self.list)

    def tearDown(self):
        if self.param.GetBool("ShowModelTree", False) != self.savedTree:
            Gui.runCommand("PartDesign_ToggleModelTree")
        super().tearDown()

    def point(self, x, y, z):
        viewport = self.view.graphicsView().viewport()
        sx, sy = self.view.getPointOnScreen(App.Vector(x, y, z))
        _, height = self.view.getSize()
        scale = viewport.devicePixelRatioF()
        return QtCore.QPoint(int(round(sx / scale)), int(round((height - sy - 1) / scale)))

    def send(self, kind, at, buttons):
        viewport = self.view.graphicsView().viewport()
        event = QtGui.QMouseEvent(
            kind,
            QtCore.QPointF(at),
            QtCore.QPointF(viewport.mapToGlobal(at)),
            QtCore.Qt.LeftButton,
            buttons,
            QtCore.Qt.NoModifier,
        )
        QtWidgets.QApplication.sendEvent(viewport, event)

    def doubleClick(self, at):
        """Press, release, press, release inside the double-click interval, as a user's."""
        self.hover(at)
        for _ in range(2):
            self.send(QtCore.QEvent.MouseButtonPress, at, QtCore.Qt.LeftButton)
            self.send(QtCore.QEvent.MouseButtonRelease, at, QtCore.Qt.NoButton)
        pump(0.3)

    def tinted(self):
        """The Features list's rows with a background, by object name."""
        names = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            name = item.data(QtCore.Qt.UserRole)
            if name and item.data(QtCore.Qt.BackgroundRole) is not None:
                names.append(bytes(name).decode())
        return sorted(names)

    def testOnshapeDoubleClickSelectsNothing(self):
        self.doubleClick(self.point(7, 7, 5))
        self.assertEqual(Gui.Selection.getSelectionEx(), [])

    def testOnshapeDoubleClickTintsTheBossAndItsSketch(self):
        self.doubleClick(self.point(2, 2, 10))
        self.assertEqual(self.tinted(), ["Pad001", "Sketch001"])

    def testOnshapeDoubleClickTintsThePadUnderTheBoss(self):
        self.doubleClick(self.point(7, 7, 5))
        self.assertEqual(self.tinted(), ["Pad", "Sketch"])

    def testSelectionChangeClearsTheTint(self):
        self.doubleClick(self.point(2, 2, 10))
        self.assertTrue(self.tinted())
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, "Pad001.Face1")
        pump(0.3)
        self.assertEqual(self.tinted(), [])

    def testFreeCADKeymapTintsNothing(self):
        """The control: FreeCAD's double click keeps its behaviour, no tint."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        pump()
        self.doubleClick(self.point(2, 2, 10))
        self.assertEqual(self.tinted(), [])


class TestCompactDialogGui(PolishCase):
    """P6: under the Onshape keymap the overlay panel that holds only the Tasks panel ends under
    the dialog's last box instead of running the view's full height; a dialog taller than the view
    keeps the full height and scrolls. FreeCAD's keymap keeps the full-height panel."""

    MARGIN = 40  # px below the last box: the panel's frame and spacing

    def setUp(self):
        # room for the tallest dialog here (the Sketch one): the offscreen window is short
        mainWindow = Gui.getMainWindow()
        self.savedMaximized = mainWindow.isMaximized()
        self.savedSize = mainWindow.size()
        mainWindow.showNormal()
        mainWindow.resize(1600, 1500)
        pump(0.3)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        mainWindow = Gui.getMainWindow()
        mainWindow.resize(self.savedSize)
        if self.savedMaximized:
            mainWindow.showMaximized()
        pump(0.5)

    def mdiBottom(self):
        return self.bottom(Gui.getMainWindow().findChild(QtWidgets.QMdiArea))

    def tasksOverlay(self):
        """The visible overlay panel holding the Tasks panel alone, else skip: the profile docks
        it otherwise."""
        tasks = Gui.getMainWindow().findChild(QtWidgets.QWidget, "Tasks")
        for panel in Gui.getMainWindow().findChildren(QtWidgets.QTabWidget):
            if panel.metaObject().className() != "Gui::OverlayTabWidget":
                continue
            if panel.isVisible() and tasks is not None and panel.isAncestorOf(tasks):
                if panel.count() != 1:
                    self.skipTest("the Tasks overlay holds other panels here")
                return panel
        self.skipTest("the Tasks panel is not an overlay here")

    def openDialog(self, opener):
        opener()
        Gui.Control.showTaskView()
        pump(0.6)
        self.assertTrue(Gui.Control.activeDialog())
        return self.tasksOverlay()

    def bottom(self, widget):
        return widget.mapToGlobal(QtCore.QPoint(0, widget.height())).y()

    def actionPanel(self):
        tasks = Gui.getMainWindow().findChild(QtWidgets.QWidget, "Tasks")
        panels = [
            w
            for w in tasks.findChildren(QtWidgets.QWidget)
            if w.metaObject().className() == "QSint::ActionPanel" and w.isVisible()
        ]
        self.assertTrue(panels, "a shown task panel")
        return panels[0]

    def contentBottom(self):
        boxes = [w for w in self.actionPanel().children() if isinstance(w, QtWidgets.QWidget) and w.isVisible()]
        return max(self.bottom(w) for w in boxes)

    def scrollRange(self):
        area = self.actionPanel().parentWidget().parentWidget()  # viewport, then the scroll area
        return area.verticalScrollBar().maximum()

    def assertFitsContent(self, panel):
        content = self.contentBottom()
        if content + self.MARGIN > self.mdiBottom():
            self.skipTest("the dialog is taller than the view here")
        self.assertLessEqual(self.bottom(panel), content + self.MARGIN, "the panel ends under its last box")
        self.assertEqual(self.scrollRange(), 0, "the boxes fit without scrolling")

    def testOnshapePadDialogEndsUnderItsLastBox(self):
        panel = self.openDialog(lambda: Gui.ActiveDocument.setEdit(self.pad.Name))
        self.assertFitsContent(panel)

    def testOnshapeSketchDialogEndsUnderItsLastBox(self):
        panel = self.openDialog(lambda: Gui.ActiveDocument.setEdit(self.sketch.Name))
        self.assertFitsContent(panel)

    def testOnshapeTallDialogScrolls(self):
        class Panel:
            def __init__(self):
                self.form = QtWidgets.QWidget()
                self.form.setMinimumHeight(4000)

        panel = self.openDialog(lambda: Gui.Control.showDialog(Panel()))
        self.assertLessEqual(self.bottom(panel), self.mdiBottom(), "capped at the view")
        self.assertGreater(self.scrollRange(), 0, "the boxes scroll")

    def testFreeCADKeymapKeepsTheFullHeight(self):
        """The control: FreeCAD's keymap keeps the panel's full height."""
        App.ParamGet(KEYMAP).SetString("Keymap", "FreeCAD")
        pump()
        panel = self.openDialog(lambda: Gui.ActiveDocument.setEdit(self.pad.Name))
        self.assertGreater(self.bottom(panel), self.contentBottom() + 100)


class TestCameraCommandsGui(PolishCase):
    """ops#695: the camera commands' isActive() reads the view's camera, and View3DInventor's
    getCamera() throws while the view has none (being built or torn down). An exception from
    isActive() leaves the main window's update timer, which aborts FreeCAD on macOS. Designed
    state: the pad model's 3D view with its render manager's camera taken away for the check."""

    COMMANDS = ("Std_OrthographicCamera", "Std_PerspectiveCamera")

    def testCameraCommandsReadInactiveWithoutACamera(self):
        manager = self.view.getViewer().getSoRenderManager()
        camera = manager.getCamera()
        self.assertIsNotNone(camera)
        camera.ref()
        try:
            manager.setCamera(None)
            for name in self.COMMANDS:
                # Before ops#695 this raised "Could not find reference to 3D View camera"
                self.assertFalse(Gui.Command.get(name).isActive(), name)
        finally:
            manager.setCamera(camera)
            camera.unref()
        pump(0.1)
        self.assertEqual(
            [Gui.Command.get(name).isActive() for name in self.COMMANDS], [True, True]
        )
