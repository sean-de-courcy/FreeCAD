# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *   Copyright (c) 2026 FreeCAD-CH contributors                            *
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
# ***************************************************************************

"""Pattern dialogs as Onshape's (FreeCAD-CH ops#640, ranks 8 and 89, B3-6, E-1).

- A new linear pattern: Distance is the spacing between neighbours (Mode Spacing), count 2,
  Centered off, nothing skipped. A new circular pattern: 360 deg, count 4, Equal spacing on
  (Mode Extent), Centered off, nothing skipped. The defaults come from the commands; the
  constructors keep upstream's, so files saved before compute as they did.
- The dialogs have Centered and Skip instances fields; the skip list writes SkippedInstances.
- A fresh pattern dialog with nothing picked has its OK enabled, and OK accepts the pattern red
  ("Select features to pattern."): it adds nothing (rank 89).
- The second direction as Onshape's (ops#655, oracle 9j Q-D1..Q-D5; TestPatternSecondDirectionGui):
  a Second direction box, unticked on a new pattern, whose Direction is empty (the command fills
  none); a tick shows count 1, an untick sets count 1 and a new tick gives the count back; the
  Direction field is outlined red while empty at count > 1, and OK then commits the pattern red
  ("Select a pattern direction."); its own Centered and flip; a blue banner for a second direction
  parallel to the first; Skip instances puts a dot on every grid instance but the seed (2n - 1
  along a centered direction), and a click on one skips its instance or makes it again.

Designed model: Cube, a 10 x 10 x 10 additive box at the origin (1000).
"""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor


def flushDeletes():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def visible(cls, name):
    flushDeletes()
    for widget in Gui.getMainWindow().findChildren(cls, name):
        if widget.isVisible():
            return widget
    return None


def secondGroup():
    """The Second direction group, when ticked."""
    flushDeletes()
    for group in Gui.getMainWindow().findChildren(QtWidgets.QGroupBox):
        if group.isVisible() and group.title() == "Second direction":
            return group
    return None


def pick(combo, text):
    """Picks an entry of a Direction field, as a click on it does."""
    index = combo.findText(text)
    assert index >= 0, "no %r in %s" % (text, [combo.itemText(i) for i in range(combo.count())])
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    pump()


def setCount(spin, count):
    """Sets a count field (Gui::UIntSpinBox keeps an unsigned value shifted into int's range)."""
    spin.setValue(count - 2**31)
    pump()


def secondDirection(case, direction=None, count=None):
    """Ticks Second direction, then picks its direction and sets its count when given; returns
    the group's Direction and count fields."""
    box = visible(QtWidgets.QCheckBox, "enableCheckbox")
    case.assertIsNotNone(box, "no Second direction box")
    case.assertEqual(box.text(), "Second direction")
    box.click()
    pump()
    group = secondGroup()
    case.assertIsNotNone(group, "the tick shows no Second direction group")
    combo = group.findChild(QtWidgets.QComboBox, "comboDirection")
    spin = group.findChild(QtWidgets.QSpinBox, "spinOccurrences")
    if direction:
        pick(combo, direction)
    if count:
        setCount(spin, count)
    return combo, spin


class PatternPanelCase(unittest.TestCase):
    """The designed Cube in a Body, and the pattern dialogs' helpers."""

    def setUp(self):
        self.doc = models.newDocument("PatternDefaults")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        self.body = models.body(self.doc)
        self.box = self.doc.addObject("PartDesign::AdditiveBox", "Cube")
        self.body.addObject(self.box)
        for prop in ("Length", "Width", "Height"):
            setattr(self.box, prop, 10)
        self.doc.recompute()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body)

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        guiDoc = Gui.getDocument(self.doc.Name)
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        flushDeletes()
        App.closeDocument(self.doc.Name)

    def runTool(self, command, *selection):
        Gui.Selection.clearSelection()
        for obj in selection:
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.5)

    def only(self, typeId):
        found = [o for o in self.doc.Objects if o.TypeId == typeId]
        self.assertEqual(len(found), 1, [o.Name for o in found])
        return found[0]

    def accept(self):
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok, "no OK button")
        self.assertTrue(ok.isEnabled(), "OK is disabled")
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays open")


class TestPatternDefaultsGui(PatternPanelCase):
    # -- defaults (rank 8, B3-6) -----------------------------------------------------------------

    def testNewLinearPatternDefaults(self):
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        self.assertEqual(pattern.Mode, "Spacing")
        self.assertEqual(pattern.Occurrences, 2)
        self.assertFalse(pattern.Centered)
        self.assertEqual(pattern.SkippedInstances, [])
        self.assertIsNotNone(visible(QtWidgets.QCheckBox, "checkCentered"))
        self.assertIsNotNone(visible(QtWidgets.QCheckBox, "checkSkip"))
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())

    def testNewLinearPatternSecondDirectionDefaults(self):
        """The second direction has Onshape's defaults: Distance a spacing of 25 (Onshape's one
        distance default), count 1 (its box unticked), no Direction; with Y picked, count 2 puts
        the row 25 away along Y, not 100 (ops#655). The 2 x 2 grid splits the Body into four
        pieces, which only OK makes parts, so the result is checked after OK."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        self.assertEqual(pattern.Mode2, "Spacing")
        self.assertAlmostEqual(pattern.Offset2.Value, 25)
        self.assertEqual(pattern.Occurrences2, 1)
        self.assertIsNone(pattern.Direction2)
        secondDirection(self, "Base Y-axis", 2)
        self.accept()
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        box = pattern.Shape.BoundBox
        self.assertAlmostEqual(box.YMax, 35)
        self.assertAlmostEqual(box.XMax, 35)

    def testLinearCountChangeKeepsTheSpacing(self):
        """Count 2 -> 3 on a new linear pattern: Offset (the spacing) stays as it was."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        offset = pattern.Offset.Value
        pattern.Occurrences = 3
        self.doc.recompute()
        self.assertAlmostEqual(pattern.Offset.Value, offset)
        self.accept()

    def testNewCircularPatternDefaults(self):
        self.runTool("PartDesign_PolarPattern", self.box)
        pattern = self.only("PartDesign::PolarPattern")
        self.assertEqual(pattern.Mode, "Extent")
        self.assertAlmostEqual(pattern.Angle.Value, 360)
        self.assertEqual(pattern.Occurrences, 4)
        self.assertFalse(pattern.Centered)
        self.assertEqual(pattern.SkippedInstances, [])
        self.accept()

    # -- Skip instances field (E-1) --------------------------------------------------------------

    def testSkipListWritesTheInstances(self):
        """Skip instances ticked, "(1, 0)" typed in the list and OK: instance (1, 0) is skipped,
        so only the cube is left (1000)."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        skip = visible(QtWidgets.QCheckBox, "checkSkip")
        skip.setChecked(True)
        pump()
        field = visible(QtWidgets.QLineEdit, "editSkipped")
        self.assertIsNotNone(field, "no Instances to skip field")
        field.setText("(1, 0)")
        self.accept()
        self.assertEqual(pattern.SkippedInstances, [1, 0])
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=4)

    # -- rank 89: OK enabled, a failing pattern accepted red -------------------------------------

    def testFreshPatternWithNothingPickedIsAcceptedRed(self):
        """Linear pattern with nothing selected: OK is enabled; OK commits it red, with
        "Select features to pattern.", and the Body is still the cube."""
        self.runTool("PartDesign_LinearPattern")
        pattern = self.only("PartDesign::LinearPattern")
        self.assertEqual(pattern.Originals, [])
        self.accept()
        self.doc.recompute()
        self.assertFalse(pattern.isValid())
        self.assertIn("Select features to pattern.", pattern.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=4)

    def testFreshMirrorWithNothingPickedIsAcceptedRed(self):
        self.runTool("PartDesign_Mirrored")
        mirrored = self.only("PartDesign::Mirrored")
        self.accept()
        self.doc.recompute()
        self.assertFalse(mirrored.isValid())
        self.assertIn("Select features to mirror.", mirrored.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=4)


class TestPatternSecondDirectionGui(PatternPanelCase):
    """The second direction as Onshape's (ops#655). The Cube's centre is (5, 5, 5); direction 1 is
    the command's, X at a spacing of 25, count 2."""

    def secondLook(self):
        """A top view with the whole grid and its dots in the viewport."""
        self.view = Gui.getDocument(self.doc.Name).ActiveView
        self.viewport = self.view.graphicsView().viewport()
        self.view.setAnimationEnabled(False)
        self.view.viewTop()
        self.view.fitAll()
        width, height = self.view.getSize()
        camera = self.view.getCameraNode()
        camera.height.setValue(camera.height.getValue() * max(1.0, height / width) * 1.5)
        pump(0.4)

    def click(self, x, y, z):
        """A left click on the 3D view at a world point."""
        sx, sy = self.view.getPointOnScreen(App.Vector(x, y, z))
        _, height = self.view.getSize()
        scale = self.viewport.devicePixelRatioF()
        at = QtCore.QPoint(int(round(sx / scale)), int(round((height - sy - 1) / scale)))
        self.assertTrue(self.viewport.rect().contains(at), "(%g, %g, %g) is off the viewport" % (x, y, z))
        left, none = QtCore.Qt.LeftButton, QtCore.Qt.NoButton
        for kind, button, buttons in (
            (QtCore.QEvent.MouseMove, none, none),
            (QtCore.QEvent.MouseButtonPress, left, left),
            (QtCore.QEvent.MouseButtonRelease, left, none),
        ):
            event = QtGui.QMouseEvent(
                kind, QtCore.QPointF(at), QtCore.QPointF(self.viewport.mapToGlobal(at)),
                button, buttons, QtCore.Qt.NoModifier,
            )
            QtWidgets.QApplication.sendEvent(self.viewport, event)
            pump(0.05)
        pump(0.3)

    def testNewPatternHasTheBoxUntickedAndNoDirection(self):
        """A new pattern: Second direction unticked, its Direction empty; OK writes none (the
        first axis isn't filled in) and makes direction 1's copies only (2000)."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        self.assertIsNone(pattern.Direction2)
        self.assertIsNone(secondGroup())
        box = visible(QtWidgets.QCheckBox, "enableCheckbox")
        self.assertIsNotNone(box)
        self.assertFalse(box.isChecked())
        self.accept()
        self.doc.recompute()
        self.assertIsNone(pattern.Direction2)
        self.assertEqual(pattern.Occurrences2, 1)
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 2000, places=4)

    def testTickShowsCountOneAndUntickKeepsTheCount(self):
        """Onshape (Q-D2): a tick shows count 1 and an empty Direction, not direction 1's values.
        Count 3, untick: count 1; a new tick gives 3 back."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        combo, spin = secondDirection(self)
        self.assertEqual(pattern.Occurrences2, 1)
        self.assertEqual(combo.currentText(), "Select reference…")
        self.assertIsNone(pattern.Direction2)
        setCount(spin, 3)
        self.assertEqual(pattern.Occurrences2, 3)
        secondGroup().setChecked(False)
        pump()
        self.assertEqual(pattern.Occurrences2, 1)
        self.assertIsNone(secondGroup())
        box = visible(QtWidgets.QCheckBox, "enableCheckbox")
        box.click()
        pump()
        self.assertEqual(pattern.Occurrences2, 3)
        self.assertIsNotNone(secondGroup())

    def testEmptyDirectionAtCountTwoIsRedAndOkCommitsItRed(self):
        """Onshape (Q-D3): ticked with no direction, count 1 is fine; count 2 outlines the
        Direction field red, and OK commits the pattern red: "Select a pattern direction."."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        combo, spin = secondDirection(self)
        self.assertFalse(combo.property("missing"))
        setCount(spin, 2)
        self.assertTrue(combo.property("missing"))
        first = visible(QtWidgets.QComboBox, "comboDirection")
        self.assertIsNot(first, combo)
        self.assertFalse(first.property("missing"))
        self.accept()
        self.doc.recompute()
        self.assertIsNone(pattern.Direction2)
        self.assertFalse(pattern.isValid())
        self.assertIn("Select a pattern direction.", pattern.getStatusString())

    def testSecondDirectionHasItsOwnFlip(self):
        """The second direction's flip: Y count 2 flipped puts the row at -25 (4000)."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        combo, _ = secondDirection(self, "Base Y-axis", 2)
        self.assertFalse(combo.property("missing"))
        flip = secondGroup().findChild(QtWidgets.QToolButton, "PushButtonReverse")
        flip.click()
        pump()
        self.assertTrue(pattern.Reversed2)
        self.assertFalse(pattern.Reversed)
        self.accept()
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        box = pattern.Shape.BoundBox
        self.assertAlmostEqual(box.YMin, -25)
        self.assertAlmostEqual(box.YMax, 10)
        self.assertAlmostEqual(box.XMax, 35)

    def testSecondDirectionHasItsOwnCentered(self):
        """The second direction's Centered (Onshape's isCenteredTwo): Y count 2 centered is 3
        along Y, -25..+25; direction 1 stays uncentered: the 2 x 3 grid, X 0..35, Y -25..35."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        secondDirection(self, "Base Y-axis", 2)
        centered2 = secondGroup().findChild(QtWidgets.QCheckBox, "checkCentered2")
        self.assertIsNotNone(centered2, "no Centered in the Second direction group")
        centered2.click()
        pump()
        self.assertTrue(pattern.Centered2)
        self.assertFalse(pattern.Centered)
        self.accept()
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        box = pattern.Shape.BoundBox
        self.assertAlmostEqual(box.XMin, 0)
        self.assertAlmostEqual(box.XMax, 35)
        self.assertAlmostEqual(box.YMin, -25)
        self.assertAlmostEqual(box.YMax, 35)

    def testParallelDirectionsShowTheBanner(self):
        """Onshape (Q-D4): X picked for both directions shows the blue banner "Parallel directions
        selected for first and second direction."; Y instead hides it."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        self.assertIsNone(visible(QtWidgets.QLabel, "parallelBanner"))
        combo, _ = secondDirection(self, "Base X-axis", 2)
        self.assertTrue(
            waitFor(lambda: visible(QtWidgets.QLabel, "parallelBanner") is not None), "no banner"
        )
        banner = visible(QtWidgets.QLabel, "parallelBanner")
        self.assertEqual(banner.text(), "Parallel directions selected for first and second direction.")
        pick(combo, "Base Y-axis")
        self.assertTrue(waitFor(lambda: visible(QtWidgets.QLabel, "parallelBanner") is None), "the banner stays")
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())

    def testSkipDotsCoverTheCenteredGridButTheSeed(self):
        """Onshape (Q-D5): Skip instances puts a dot on every grid instance but the seed. Centered
        count 2 along X is 3 (i 0..2, the seed i = 1), Y count 2 (j 0..1): five dots."""
        self.runTool("PartDesign_LinearPattern", self.box)
        secondDirection(self, "Base Y-axis", 2)
        visible(QtWidgets.QCheckBox, "checkCentered").click()
        pump()
        skip = visible(QtWidgets.QCheckBox, "checkSkip")
        self.assertEqual(skip.property("dots") or "", "")
        skip.setChecked(True)
        pump()
        self.assertEqual(skip.property("dots"), "(0, 0), (0, 1), (1, 1), (2, 0), (2, 1)")
        skip.setChecked(False)
        pump()
        self.assertEqual(skip.property("dots") or "", "")

    def testClickingADotSkipsItsInstance(self):
        """A click on instance (1, 0)'s dot, at the centre of the copy (30, 5, 5), skips it: the
        list shows (1, 0) and the dot is hollow; a second click makes it again; a third and OK
        leave the cube (1000)."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        self.secondLook()
        skip = visible(QtWidgets.QCheckBox, "checkSkip")
        skip.setChecked(True)
        pump()
        self.assertEqual(skip.property("dots"), "(1, 0)")
        field = visible(QtWidgets.QLineEdit, "editSkipped")
        self.click(30, 5, 5)
        self.assertEqual(pattern.SkippedInstances, [1, 0])
        self.assertEqual(field.text(), "(1, 0)")
        self.assertEqual(skip.property("dots"), "(1, 0)*")
        self.click(30, 5, 5)
        self.assertEqual(pattern.SkippedInstances, [])
        self.assertEqual(field.text(), "")
        self.click(30, 5, 5)
        self.assertEqual(Gui.Selection.getSelectionEx(), [])
        self.accept()
        self.doc.recompute()
        self.assertEqual(pattern.SkippedInstances, [1, 0])
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 1000, places=4)

    def testClickingACenteredReversedSecondDirectionDot(self):
        """Y count 2 centered and flipped: three rows along Y, at -25, 0 and +25. The flip makes
        direction 2's step -Y, so geometric row j = 0 (one step back) is the +Y row. A click on the
        dot at the centre of the copy (5, 30, 5) skips (0, 0): after OK that copy is gone, the one
        at (5, -20, 5) stays, and the 2 x 3 grid less one is 5000."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        secondDirection(self, "Base Y-axis", 2)
        group = secondGroup()
        group.findChild(QtWidgets.QCheckBox, "checkCentered2").click()
        pump()
        group.findChild(QtWidgets.QToolButton, "PushButtonReverse").click()
        pump()
        self.assertTrue(pattern.Centered2)
        self.assertTrue(pattern.Reversed2)
        self.doc.recompute()
        self.secondLook()
        skip = visible(QtWidgets.QCheckBox, "checkSkip")
        skip.setChecked(True)
        pump()
        self.assertEqual(skip.property("dots"), "(0, 0), (0, 2), (1, 0), (1, 1), (1, 2)")
        self.click(5, 30, 5)
        self.assertEqual(pattern.SkippedInstances, [0, 0])
        self.assertEqual(skip.property("dots"), "(0, 0)*, (0, 2), (1, 0), (1, 1), (1, 2)")
        self.accept()
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        shape = self.body.Shape
        self.assertFalse(shape.isInside(App.Vector(5, 30, 5), 1e-6, True))
        self.assertTrue(shape.isInside(App.Vector(5, -20, 5), 1e-6, True))
        self.assertTrue(shape.isInside(App.Vector(30, 30, 5), 1e-6, True))
        self.assertAlmostEqual(shape.Volume, 5000, places=4)

    def testReopeningAPatternWithASecondDirectionShowsIt(self):
        """A pattern saved with Y count 3: reopened, Second direction is ticked, its Direction is
        Y and its count 3."""
        self.runTool("PartDesign_LinearPattern", self.box)
        pattern = self.only("PartDesign::LinearPattern")
        secondDirection(self, "Base Y-axis", 3)
        self.accept()
        self.doc.recompute()
        self.assertEqual(pattern.Occurrences2, 3)
        Gui.getDocument(self.doc.Name).setEdit(pattern, 0)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.5)
        group = secondGroup()
        self.assertIsNotNone(group, "Second direction isn't ticked on reopening")
        combo = group.findChild(QtWidgets.QComboBox, "comboDirection")
        spin = group.findChild(QtWidgets.QSpinBox, "spinOccurrences")
        self.assertEqual(combo.currentText(), "Base Y-axis")
        self.assertEqual(spin.value() + 2**31, 3)
        self.accept()
        self.assertEqual(pattern.Occurrences2, 3)


if __name__ == "__main__":
    unittest.main()
