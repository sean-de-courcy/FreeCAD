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

Designed model: Cube, a 10 x 10 x 10 additive box at the origin (1000).
"""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

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


class TestPatternDefaultsGui(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
