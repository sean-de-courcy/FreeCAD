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
- Redrawn fillet: a 20 x 10 rectangle padded 10 with a fillet of radius 1 on its vertical edge at
  (20, 0); the rectangle drawn again the other way round. The fillet finds its edge by geometry
  only and computes with a warning (the reference solver on, V2).
- Linked box: a 10 mm Part box in a second document, linked from the first and edited in place
  there; a length of 0 fails it.

Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import os
import shutil
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Sketcher
from PySide import QtCore, QtGui, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import Z, edge
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
        self.otherDocs = []
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
        for doc in self.otherDocs:
            App.closeDocument(doc.Name)
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

    # -- PR 173 review round 1 -------------------------------------------------------------------

    def testShownWhileAnotherViewIsActive(self):
        """The edit's own 3D view needn't be the active one (a spreadsheet driving the length, a
        second view): the error is still shown."""
        pad = self.plate()
        self.edit(pad)
        Gui.runCommand("Std_ViewCreate", 0)
        pump()
        guiDoc = Gui.getDocument(self.doc.Name)
        self.assertIsNone(guiDoc.getInEdit(), "the edit's view is still the active one")
        pad.Type = "UpToLast"
        self.doc.recompute()
        self.assertIn("Invalid", pad.State)
        self.checkShowsError(pad)

    def testWarningIsShown(self):
        """The redrawn fillet computes with a warning: the label shows it, as the tree does."""
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        self.body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 20, 10), self.body)
        pad = models.pad(self.body, profile, 10)
        self.doc.recompute()
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape))
        fillet.Radius = 1
        self.doc.recompute()
        profile.deleteAllGeometry()
        profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        self.doc.recompute()
        self.assertIn("Warning", fillet.State)
        self.assertNotIn("Invalid", fillet.State)
        self.edit(fillet)
        banner = self.banner()
        self.assertTrue(waitFor(banner.isVisible), "the feature's warning isn't shown")
        text = plainText(banner)
        self.assertTrue(text.startswith("Warning:"), text)
        self.assertIn(fillet.getStatusString()[len("Warning: ") :].strip(), text)

    def testInPlaceEditOfAnotherDocument(self):
        """A box of a second document, edited in place through a link in the first: its error
        comes from its own document's recompute, with its own text."""
        other = App.newDocument("TaskStatusOther")
        self.otherDocs.append(other)
        box = other.addObject("Part::Box", "Box")
        other.recompute()
        # A link to another document needs both documents saved
        folder = tempfile.mkdtemp(prefix="TaskStatus")
        self.addCleanup(shutil.rmtree, folder, True)
        other.saveAs(os.path.join(folder, "Other.FCStd"))
        self.doc.saveAs(os.path.join(folder, "Main.FCStd"))
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        link = self.doc.addObject("App::Link", "Link")
        link.LinkedObject = box
        self.doc.recompute()
        pump()
        Gui.getDocument(self.doc.Name).setEdit(link, 0)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "the dialog didn't open")
        pump()
        banner = self.banner()
        self.assertFalse(banner.isVisible())

        box.Length = 0
        other.recompute()
        self.assertIn("Invalid", box.State)
        self.checkShowsError(box)

        box.Length = 10
        other.recompute()
        self.assertTrue(waitFor(lambda: not banner.isVisible()), "the error stays")

    def testQuickFailAndFixDoesNotFlash(self):
        """A failing value replaced within the show delay ("0.5" passes through "0") never shows
        the label."""
        pad = self.plate()
        self.edit(pad)
        banner = self.banner()
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "changeMode")
        combo.setCurrentIndex(combo.findText("To last"))
        QtWidgets.QApplication.processEvents()
        self.assertIn("Invalid", pad.State)
        shown = banner.isVisible()
        combo.setCurrentIndex(combo.findText("Dimension"))
        for _ in range(40):
            pump(0.02)
            shown = shown or banner.isVisible()
        self.assertNotIn("Invalid", pad.State)
        self.assertFalse(shown, "the label flashed")

    # -- PR 173 follow-ups (ops#202) -------------------------------------------------------------

    def testShowDelayRestartsOnEachFailingRefresh(self):
        """The label shows 300 ms after the *last* failing refresh: a feature failing, failing
        again 200 ms later, and fixed 400 ms after the first failure (200 after the second)
        never shows it. (Timed from the first failure, the label showed at 300 ms and hid again
        at 400.) The recomputes are made through the document, to keep the times tight."""
        pad = self.plate()
        self.edit(pad)
        banner = self.banner()
        start = time.monotonic()
        log = []

        def watch(until):
            while time.monotonic() - start < until:
                pump(0.01)
                if banner.isVisible():
                    log.append(round(time.monotonic() - start, 3))

        pad.Type = "UpToLast"
        self.doc.recompute()  # t = 0: fails
        self.assertIn("Invalid", pad.State)
        watch(0.2)
        pad.touch()
        self.doc.recompute()  # t = 0.2: fails again
        self.assertIn("Invalid", pad.State)
        watch(0.4)
        pad.Type = "Length"
        self.doc.recompute()  # t = 0.4: fixed
        fixed = round(time.monotonic() - start, 3)
        self.assertNotIn("Invalid", pad.State)
        watch(1.0)
        self.assertEqual(log, [], f"the label flashed (fixed at {fixed} s)")
        self.assertEqual(banner.text(), "")

    def testShowsAfterTheDelayOfTheLastFailure(self):
        """The restarted delay still ends: a failure that stays shows the label."""
        pad = self.plate()
        self.edit(pad)
        banner = self.banner()
        self.setMode("To last")
        pump(0.2)
        pad.touch()
        self.doc.recompute()
        self.assertTrue(waitFor(banner.isVisible), "the error isn't shown")

    def testUndoAndRedoRefreshTheLabel(self):
        """The edited feature failing in a transaction of its own: undo clears the label, redo
        brings it back."""
        pad = self.plate()
        self.edit(pad)
        banner = self.banner()
        self.doc.openTransaction("Fail")
        pad.Type = "UpToLast"
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIn("Invalid", pad.State)
        self.checkShowsError(pad)

        self.doc.undo()
        self.doc.recompute()
        self.assertNotIn("Invalid", pad.State)
        self.assertTrue(waitFor(lambda: not banner.isVisible()), "the error stays after undo")
        self.assertEqual(banner.text(), "")

        self.doc.redo()
        self.doc.recompute()
        self.assertIn("Invalid", pad.State)
        self.checkShowsError(pad)
