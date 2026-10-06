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

"""The References panel (FreeCAD-CH, ops#127 P7; design note N2 section 6): a feature's guessed,
partly resolved or broken references, with Accept, Use this one, Mark broken and Re-pick, from the
tree's "Repair References…" and at the top of the feature's own dialog; and the Pad's profile
picked again in its own dialog (ops#125).

Designed models: a pad whose rectangle is drawn again (the filleted corner edge found again by
geometry, tier 3), the datum point on a split face (TestNamingSolver's), and the Pad made from two
sketch regions that are drawn again (TestPad's). The App calls the buttons make have their own
tests (TestNamingSolver); these check that the panel makes them, on the right reference, and what
it shows."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import Z, edge, face
from PartDesignTests.TestPad import (
    REGIONS,
    REGION_PAD_VOLUME,
    makeRegionPad,
    redrawBosses,
)


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


class Panel:
    """The References panel's widgets in the task view."""

    def __init__(self, test):
        mainWindow = Gui.getMainWindow()
        self.tree = mainWindow.findChild(QtWidgets.QTreeWidget, "references")
        test.assertIsNotNone(self.tree, "no References panel")
        self.header = mainWindow.findChild(QtWidgets.QLabel, "header")
        self.message = mainWindow.findChild(QtWidgets.QLabel, "message")
        self.accept = mainWindow.findChild(QtWidgets.QPushButton, "buttonAccept")
        self.use = mainWindow.findChild(QtWidgets.QPushButton, "buttonUse")
        self.broken = mainWindow.findChild(QtWidgets.QPushButton, "buttonBroken")
        self.pick = mainWindow.findChild(QtWidgets.QPushButton, "buttonPick")

    def rows(self):
        """(reference, state, element, original) per row."""
        return [
            tuple(self.tree.topLevelItem(i).text(c) for c in range(4))
            for i in range(self.tree.topLevelItemCount())
        ]

    def children(self, row=0):
        """(element, disabled) per candidate or alternative of a row. Read here: PySide drops a
        child's wrapper with its parent's."""
        item = self.tree.topLevelItem(row)
        return [
            (item.child(i).text(2), item.child(i).isDisabled()) for i in range(item.childCount())
        ]

    def selectChild(self, index, row=0):
        item = self.tree.topLevelItem(row)
        self.tree.setCurrentItem(item.child(index))
        pump()

    def click(self, button):
        button.click()
        pump()


class TestReferencePickerGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PickerGui")
        self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = True
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        pump()
        App.closeDocument(self.doc.Name)

    # -- models ---------------------------------------------------------------------------------

    def redrawnFillet(self):
        """A pad of a rectangle 0..20 x 0..10, 10 high, a fillet, radius 1, on its vertical edge
        at (20, 0); the rectangle drawn again the other way round: the edge is found again by
        geometry (tier 3) and the fillet computes with a warning. Returns (pad, fillet, the
        reference's index before the redraw, the corner edge's index now)."""
        doc = self.doc
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        corner = edge("line", direction=Z, through=(20, 0, 0))
        fillet.Base = (pad, corner.one(pad.Shape))
        fillet.Radius = 1
        doc.recompute()
        original = fillet.Base[1][0]
        doc.Profile.deleteAllGeometry()
        doc.Profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertIn("Warning", fillet.State)
        [now] = corner.one(pad.Shape)
        return pad, fillet, original, now

    def openPanel(self, obj):
        """The panel opened as the tree's context menu does: the object selected, the command
        run."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, obj.Name)
        pump()
        self.assertTrue(Gui.Command.get("PartDesign_RepairReferences").isActive())
        Gui.runCommand("PartDesign_RepairReferences")
        pump()
        self.assertTrue(Gui.Control.activeDialog())
        return Panel(self)

    def close(self, which):
        button = taskButton(which)
        self.assertIsNotNone(button, "no task panel button")
        button.click()
        pump()
        self.assertFalse(Gui.Control.activeDialog())

    def visible(self, obj):
        return obj.ViewObject.Visibility

    # -- the panel ------------------------------------------------------------------------------

    def testPanelListsTheGuessAndHighlightsIt(self):
        """One row: Base[0], found by geometry, the element it holds and the original. Selected,
        the element is highlighted on the pad, which shows instead of the fillet; Cancel puts
        the view back and changes nothing."""
        pad, fillet, original, corner = self.redrawnFillet()
        warning = fillet.getStatusString()

        panel = self.openPanel(fillet)

        [(reference, state, element, held)] = panel.rows()
        self.assertEqual((reference, element, held), ("Base[0]", corner, original))
        self.assertIn("tier 3", state)
        self.assertIn(original, panel.header.text())
        self.assertTrue(panel.accept.isEnabled())
        self.assertTrue(panel.broken.isEnabled())
        self.assertFalse(panel.use.isEnabled())
        [selected] = Gui.Selection.getSelectionEx(self.doc.Name)
        self.assertEqual((selected.ObjectName, selected.SubElementNames), ("Pad", (corner,)))
        self.assertTrue(self.visible(pad))
        self.assertFalse(self.visible(fillet))

        self.close(QtWidgets.QDialogButtonBox.Cancel)
        self.assertTrue(self.visible(fillet))
        self.assertFalse(self.visible(pad))
        self.assertEqual(fillet.getStatusString(), warning)

    def testAcceptIsKeptByOkAndUndone(self):
        """Accept: the warning goes and the row with it; OK keeps it, and Undo brings the
        warning back (the panel runs in one transaction)."""
        pad, fillet, original, corner = self.redrawnFillet()
        panel = self.openPanel(fillet)

        panel.click(panel.accept)

        self.assertEqual(panel.rows(), [])
        self.assertNotIn("Warning", fillet.State)
        self.assertEqual(fillet.Base[1], [corner])
        self.close(QtWidgets.QDialogButtonBox.Ok)
        self.assertEqual(App.getReferenceReport(fillet), [])

        self.doc.undo()
        self.doc.recompute()
        self.assertIn("Warning", fillet.State)
        self.assertEqual(App.getReferenceReport(fillet)[0]["original"]["index"], original)

    def testCancelUndoesTheAccept(self):
        pad, fillet, original, corner = self.redrawnFillet()
        panel = self.openPanel(fillet)
        panel.click(panel.accept)
        self.assertNotIn("Warning", fillet.State)

        self.close(QtWidgets.QDialogButtonBox.Cancel)

        self.assertIn("Warning", fillet.State)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual(entry["original"]["index"], original)

    def testMarkBrokenThenRepick(self):
        """Mark broken: the fillet fails, the row shows the rejection with the rejected edge
        disabled. Re-pick: the gate takes only an edge of the pad, and the picked edge repairs
        the reference."""
        pad, fillet, original, corner = self.redrawnFillet()
        panel = self.openPanel(fillet)

        panel.click(panel.broken)

        self.assertFalse(fillet.isValid())
        [(reference, state, element, held)] = panel.rows()
        self.assertEqual((reference, element, held), ("Base[0]", "?" + original, original))
        self.assertIn("rejected", state)
        self.assertEqual(panel.children(), [(corner, True)])
        self.assertFalse(panel.accept.isEnabled())
        self.assertFalse(panel.broken.isEnabled())

        panel.click(panel.pick)
        self.assertTrue(panel.pick.isChecked())
        #   a face isn't an edge: refused
        [top] = face("plane", normal=Z, through=(0, 0, 10)).one(pad.Shape)
        Gui.Selection.addSelection(self.doc.Name, "Pad", top)
        pump()
        self.assertTrue(panel.pick.isChecked())
        self.assertFalse(fillet.isValid())
        Gui.Selection.addSelection(self.doc.Name, "Pad", corner)
        pump()

        self.assertFalse(panel.pick.isChecked())
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertNotIn("Warning", fillet.State)
        self.assertEqual(fillet.Base[1], [corner])
        self.assertEqual(panel.rows(), [])
        self.close(QtWidgets.QDialogButtonBox.Ok)

    def testUseThisOneTakesACandidate(self):
        """TestNamingSolver's split face: a datum point at the centre of a pad's top face, which a
        groove then splits into halves. The point breaks with the halves as candidates; Use this
        one on a half repairs it."""
        doc = self.doc
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        models.pad(body, profile, 10)
        sketch = models.sketch(doc, "GrooveSketch", models.rectangle(16, 2, 18, 4), body, z=10)
        groove = models.pocket(body, sketch, 4, "Groove")
        doc.recompute()
        top = face("plane", normal=Z, through=(0, 0, 10))
        point = body.newObject("PartDesign::Point", "Centre")
        point.AttachmentSupport = [(groove, top.one(groove.Shape)[0])]
        point.MapMode = "CenterOfMass"
        doc.recompute()
        models.moveRectangle(sketch, 9, -1, 11, 11)
        doc.recompute()
        self.assertFalse(point.isValid())
        halves = top.select(groove.Shape)

        panel = self.openPanel(point)
        [(reference, state, element, held)] = panel.rows()
        self.assertEqual(reference, "AttachmentSupport[0]")
        candidates = [element for element, disabled in panel.children()]
        self.assertEqual(sorted(candidates[:2]), sorted(halves))
        panel.selectChild(0)
        self.assertTrue(panel.use.isEnabled())
        [selected] = Gui.Selection.getSelectionEx(doc.Name)
        self.assertEqual(selected.SubElementNames, (candidates[0],))

        panel.click(panel.use)

        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertEqual(point.AttachmentSupport, [(groove, (candidates[0],))])
        self.close(QtWidgets.QDialogButtonBox.Ok)

    # -- the feature's own dialog ---------------------------------------------------------------

    def testFeatureDialogShowsTheReferences(self):
        """The fillet's own dialog has the References panel at the top. Accepted there, OK on the
        dialog keeps it: the fillet's list shows Base again, and nothing writes the old value
        back."""
        pad, fillet, original, corner = self.redrawnFillet()
        Gui.ActiveDocument.setEdit(fillet)
        pump()
        panel = Panel(self)
        self.assertEqual([r[0] for r in panel.rows()], ["Base[0]"])
        references = Gui.getMainWindow().findChildren(QtWidgets.QListWidget, "listWidgetReferences")
        self.assertTrue(references)

        panel.click(panel.accept)
        self.assertEqual([references[0].item(i).text() for i in range(references[0].count())], [corner])
        self.close(QtWidgets.QDialogButtonBox.Ok)

        self.assertTrue(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        self.assertEqual(fillet.Base[1], [corner])
        self.assertEqual(App.getReferenceReport(fillet), [])

    def testFeatureDialogWithoutWarningsHasNoPanel(self):
        doc = self.doc
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        doc.recompute()
        Gui.ActiveDocument.setEdit(pad)
        pump()
        self.assertIsNone(Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references"))
        self.close(QtWidgets.QDialogButtonBox.Cancel)

    def testPadProfileIsPickedAgain(self):
        """ops#125: the Pad of two sketch regions, the regions drawn again elsewhere: the Pad
        breaks. In its own dialog the Profile row shows the missing regions; Select, then the
        two new regions picked in the 3D view, replace the profile, and the Pad is whole again."""
        sketch, pad, fillet = makeRegionPad(self.doc)
        redrawBosses(sketch)
        self.doc.recompute()
        self.assertFalse(pad.isValid())

        Gui.ActiveDocument.setEdit(pad)
        pump()
        mainWindow = Gui.getMainWindow()
        line = mainWindow.findChild(QtWidgets.QLineEdit, "lineProfile")
        button = mainWindow.findChild(QtWidgets.QPushButton, "buttonProfile")
        self.assertIn("?InternalFace1", line.text())
        #   the References panel lists the Profile too
        self.assertIn("Profile[0]", [r[0] for r in Panel(self).rows()])

        button.click()
        pump()
        self.assertTrue(button.isChecked())
        self.assertTrue(sketch.ViewObject.Visibility)
        for region in REGIONS:
            Gui.Selection.addSelection(self.doc.Name, "Body", sketch.Name + "." + region)
            pump()
        button.click()
        pump()

        self.assertEqual(pad.Profile[1], REGIONS)
        self.assertEqual(line.text(), "%s: %s" % (sketch.Label, ", ".join(REGIONS)))
        self.close(QtWidgets.QDialogButtonBox.Ok)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, REGION_PAD_VOLUME, places=4)
