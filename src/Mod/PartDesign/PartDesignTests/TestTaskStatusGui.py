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

"""The edited feature's error at the top of its task panel (FreeCAD-CH, ops#151).

While a feature is edited, its task panel shows the error the tree's tooltip shows, refreshed
after each recompute and hidden while the feature is fine. The panel is Gui::TaskView's, so this
holds for every dialog but the sketch editor, whose solver messages already say why a sketch
fails (PLAN decision 30); the tests use PartDesign's.

Designed models, each built by the test:
- Plate: a 10 x 10 rectangle padded 10 as the Body's first feature (1000 mm^3). Its "To last"
  type has no solid to reach and fails; "Dimension" computes again.
- Pocket: a 2 x 2 square on the Plate's top, pocketed "Up to face" with no face picked; it fails.
- Conflicting sketch: one 10 mm line constrained to both 5 and 7 mm; the sketch fails.

Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Sketcher
from PySide import QtCore, QtGui, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor


def statusBanners():
    """The status labels of the open task panels."""
    return Gui.getMainWindow().findChildren(QtWidgets.QLabel, "TaskEditStatus")


def plainText(label):
    document = QtGui.QTextDocument()
    document.setHtml(label.text())
    return document.toPlainText()


class TestTaskStatusGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("TaskStatus")
        Gui.Selection.clearSelection()

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
        App.closeDocument(self.doc.Name)
        pump()

    def edit(self, feature):
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "the dialog didn't open")
        pump()

    def banner(self):
        banners = statusBanners()
        self.assertEqual(len(banners), 1, "one task panel, one status label")
        return banners[0]

    def setMode(self, label):
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "changeMode")
        index = combo.findText(label)
        self.assertGreaterEqual(index, 0, f"no mode {label!r}")
        combo.setCurrentIndex(index)
        pump()

    def plate(self):
        self.body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, profile, 10)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1000, places=6)
        return pad

    def checkShowsError(self, feature):
        banner = self.banner()
        self.assertTrue(waitFor(banner.isVisible), "the feature's error isn't shown")
        text = plainText(banner)
        self.assertTrue(text.startswith("Error:"), text)
        status = feature.getStatusString().strip()
        self.assertTrue(status, "the feature has no error text")
        self.assertIn(status, text)

    def testWorkingFeatureShowsNothing(self):
        pad = self.plate()
        self.edit(pad)
        banner = self.banner()
        self.assertFalse(banner.isVisible())
        self.assertEqual(banner.text(), "")

    def testErrorFollowsTheRecomputes(self):
        """The Plate: "To last" fails and its error shows; "Dimension" clears it; failing again
        shows it again."""
        pad = self.plate()
        self.edit(pad)
        banner = self.banner()
        self.assertFalse(banner.isVisible())

        self.setMode("To last")
        self.assertIn("Invalid", pad.State)
        self.checkShowsError(pad)
        # It shows the error without taking the focus from the panel's fields
        self.assertEqual(banner.focusPolicy(), QtCore.Qt.NoFocus)

        self.setMode("Dimension")
        self.assertNotIn("Invalid", pad.State)
        self.assertTrue(waitFor(lambda: not banner.isVisible()), "the error stays")
        self.assertEqual(banner.text(), "")

        self.setMode("To last")
        self.checkShowsError(pad)

    def testOpenedInError(self):
        """A feature that already fails shows its error as soon as its panel opens; fixing it in
        the panel clears it."""
        pad = self.plate()
        pad.Type = "UpToLast"
        self.doc.recompute()
        self.assertIn("Invalid", pad.State)
        self.edit(pad)
        self.checkShowsError(pad)
        self.setMode("Dimension")
        self.assertTrue(waitFor(lambda: not self.banner().isVisible()), "the error stays")

    def testPocketUpToNoFace(self):
        self.plate()
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), self.body, z=10)
        pocket = models.pocket(self.body, square, 3)
        pocket.Type = "UpToFace"
        self.doc.recompute()
        self.assertIn("Invalid", pocket.State)
        self.edit(pocket)
        self.checkShowsError(pocket)

    def testClosedPanelLeavesNoLabel(self):
        pad = self.plate()
        self.edit(pad)
        self.assertEqual(len(statusBanners()), 1)
        cancel = QtWidgets.QDialogButtonBox.Cancel
        self.assertTrue(waitFor(lambda: taskButton(cancel) is not None), "no Cancel button")
        taskButton(cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog didn't close")
        pump()
        self.assertEqual(statusBanners(), [])

    def testSketchEditorShowsNothing(self):
        """The sketch editor has no status label, even for a sketch in error."""
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "Conflict", models.polyline([(0, 0), (10, 0)]), self.body)
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 5.0))
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 7.0))
        self.doc.recompute()
        self.assertIn("Invalid", sketch.State)
        self.edit(sketch)
        pump()
        self.assertEqual(statusBanners(), [])
