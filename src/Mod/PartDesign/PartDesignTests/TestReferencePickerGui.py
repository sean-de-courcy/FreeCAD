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
from PartDesignTests.Scenarios.harness import X, Y, Z, edge, face
from PartDesignTests.TestPad import (
    REGIONS,
    REGION_PAD_VOLUME,
    makeRegionPad,
    redrawBosses,
)
from PartDesignTests.TestReferenceFieldGui import (
    armed,
    entries,
    fields,
    menuActions,
    openMenu,
    states,
    texts,
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

    def redrawnPad(self):
        """A pad of a rectangle 0..20 x 0..10, 10 high. Returns (body, pad)."""
        body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        self.doc.recompute()
        return body, pad

    def redraw(self):
        """The pad's rectangle drawn again the other way round: its edges and faces are numbered
        anew, and references to them are found again by geometry (tier 3), with a warning."""
        self.doc.Profile.deleteAllGeometry()
        self.doc.Profile.addGeometry(models.polygon([(20, 10), (20, 0), (0, 0), (0, 10)]), False)
        self.doc.recompute()

    def redrawnFillet(self, alsoAt=None):
        """A pad of a rectangle 0..20 x 0..10, 10 high, a fillet, radius 1, on its vertical edge
        at (20, 0) (and at `alsoAt`); the rectangle drawn again the other way round: the edge is
        found again by geometry (tier 3) and the fillet computes with a warning. Returns (pad,
        fillet, the reference's index before the redraw, the corner edge's index now)."""
        doc = self.doc
        body, pad = self.redrawnPad()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        corner = edge("line", direction=Z, through=(20, 0, 0))
        edges = corner.one(pad.Shape)
        if alsoAt:
            edges += edge("line", direction=Z, through=alsoAt).one(pad.Shape)
        fillet.Base = (pad, edges)
        fillet.Radius = 1
        doc.recompute()
        original = fillet.Base[1][0]
        self.redraw()
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
        #   the highlight goes with the panel
        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])

    def testOkLeavesNoHighlight(self):
        pad, fillet, original, corner = self.redrawnFillet()
        self.openPanel(fillet)
        self.assertTrue(Gui.Selection.getSelectionEx(self.doc.Name))

        self.close(QtWidgets.QDialogButtonBox.Ok)

        self.assertEqual(Gui.Selection.getSelectionEx(self.doc.Name), [])
        self.assertIn("Warning", fillet.State)

    def testPanelClosesWithItsDocument(self):
        """The dialog of "Repair References…" belongs to the object's document and closes with
        it: its panel is gone from the task view. (`activeDialog()` alone asks the active
        document, which is no longer the closed one; ops#130.)"""
        pad, fillet, original, corner = self.redrawnFillet()
        self.openPanel(fillet)
        mainWindow = Gui.getMainWindow()
        self.assertIsNotNone(mainWindow.findChild(QtWidgets.QTreeWidget, "references"))

        App.closeDocument(self.doc.Name)
        pump()

        self.assertIsNone(mainWindow.findChild(QtWidgets.QTreeWidget, "references"))
        self.assertFalse(Gui.Control.activeDialog())
        self.doc = models.newDocument("PickerGui")  # for tearDown

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
        """The fillet's own dialog: its only row is Base[0], which the edges field shows
        (guessed), so the References panel is left out (ops#150, 3.5). Accepted in the field's
        menu, OK keeps it, and nothing writes the old value back."""
        pad, fillet, original, corner = self.redrawnFillet()
        Gui.ActiveDocument.setEdit(fillet)
        pump()
        tree = Gui.getMainWindow().findChild(QtWidgets.QTreeWidget, "references")
        self.assertTrue(tree is None or not tree.isVisible(), "the References panel is shown")
        [field] = fields()
        self.assertEqual(states(field), ["guessed"])

        menu = openMenu(field, 0)
        self.assertIsNotNone(menu, "no context menu")
        menuActions(menu)["Accept guess"].trigger()
        menu.close()
        pump()
        self.assertEqual(texts(field), [corner])
        self.assertEqual(states(field), ["exact"])
        self.close(QtWidgets.QDialogButtonBox.Ok)

        self.assertTrue(fillet.isValid())
        self.assertNotIn("Warning", fillet.State)
        self.assertEqual(fillet.Base[1], [corner])
        self.assertEqual(App.getReferenceReport(fillet), [])

    def testRowClickEndsTheFieldsPicking(self):
        """Review B2, with the reference fields (ops#150): a second pad up to the first one's top
        face, along its vertical edge at (20, 0); after the redraw both are guesses. In its own
        dialog the face is in its field and the edge, whose field is hidden, in the panel. The
        face field armed, a click on the panel's row highlights the edge; the field disarms
        first and doesn't take the element as its pick (it would have replaced the face)."""
        body, pad = self.redrawnPad()
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), body)
        second = models.pad(body, square, 5, name="Second")
        second.Type = "UpToFace"
        second.UpToFace = (pad, face(normal=(0, 0, 1)).one(pad.Shape))
        second.ReferenceAxis = (pad, edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape))
        self.doc.recompute()
        self.assertTrue(second.isValid(), second.getStatusString())
        self.redraw()
        self.assertTrue(second.isValid(), second.getStatusString())
        upToFace = (second.UpToFace[0].Name, list(second.UpToFace[1]))
        Gui.ActiveDocument.setEdit(second)
        pump()
        panel = Panel(self)
        self.assertEqual([r[0] for r in panel.rows()], ["ReferenceAxis[0]"])
        [field] = fields()
        self.assertEqual(field.objectName(), "fieldUpToFace")
        field.setProperty("armed", True)
        pump()
        self.assertTrue(armed(field))

        panel.tree.setCurrentItem(None)
        pump()
        panel.tree.setCurrentItem(panel.tree.topLevelItem(0))
        pump()
        self.assertFalse(armed(field))
        self.assertEqual((second.UpToFace[0].Name, list(second.UpToFace[1])), upToFace)
        self.assertTrue(Gui.Selection.getSelectionEx(self.doc.Name))

        self.close(QtWidgets.QDialogButtonBox.Ok)
        self.assertEqual((second.UpToFace[0].Name, list(second.UpToFace[1])), upToFace)

    def testCancelUndoesTheRepairAndAListEdit(self):
        """ops#130 (review M5): the fillet's own dialog opened with no transaction booked, as
        Std_Edit opens it. Accept in the edges field's menu, then an edge added to the field, then
        Cancel: both are undone and the warning is back. (The list edit used to open a
        transaction of its own, which committed the accept.)"""
        pad, fillet, original, corner = self.redrawnFillet()
        self.assertFalse(self.doc.HasPendingTransaction)
        Gui.ActiveDocument.setEdit(fillet)
        pump()
        [field] = fields()
        menu = openMenu(field, 0)
        self.assertIsNotNone(menu, "no context menu")
        menuActions(menu)["Accept guess"].trigger()
        menu.close()
        pump()
        self.assertNotIn("Warning", fillet.State)
        field.setProperty("armed", True)
        pump()
        self.assertTrue(armed(field))
        [other] = edge("line", direction=Z, through=(0, 0, 0)).one(pad.Shape)
        Gui.Selection.addSelection(self.doc.Name, "Pad", other)
        pump()
        self.assertEqual(sorted(fillet.Base[1]), sorted([corner, other]))

        self.close(QtWidgets.QDialogButtonBox.Cancel)

        self.assertIn("Warning", fillet.State)
        [entry] = App.getReferenceReport(fillet)
        self.assertEqual(entry["original"]["index"], original)
        self.assertEqual(len(fillet.Base[1]), 1)

    def testPatternKeepsARepickOnOk(self):
        """Review B1: a linear pattern of a pocket along the pad's edge at y = 0; the rectangle
        drawn again, the direction is found again by geometry. In the pattern's own dialog the
        direction is picked again on the edge at y = 10; OK keeps that edge (the dialog's
        direction box, filled when it opened, isn't written back)."""
        doc = self.doc
        body, pad = self.redrawnPad()
        hole = models.sketch(doc, "HoleSketch", models.rectangle(2, 2, 4, 4), body, z=10)
        pocket = models.pocket(body, hole, 2, "Pocket")
        doc.recompute()
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [pocket]
        pattern.Direction = (pad, edge("line", direction=X, through=(0, 0, 0)).one(pad.Shape))
        pattern.Length = 10
        pattern.Occurrences = 2
        doc.recompute()
        self.redraw()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        [back] = edge("line", direction=X, through=(0, 10, 0)).one(pad.Shape)

        Gui.ActiveDocument.setEdit(pattern)
        pump()
        panel = Panel(self)
        self.assertEqual([r[0] for r in panel.rows()], ["Direction[0]"])
        panel.click(panel.pick)
        self.assertTrue(panel.pick.isChecked())
        Gui.Selection.addSelection(doc.Name, "Pad", back)
        pump()
        self.assertFalse(panel.pick.isChecked())
        self.assertEqual(pattern.Direction[1], [back])

        self.close(QtWidgets.QDialogButtonBox.Ok)

        self.assertEqual(pattern.Direction[1], [back])
        self.assertTrue(pattern.isValid(), pattern.getStatusString())

    def assertOkKeepsTheWarning(self, obj, prop):
        """OK on the object's own dialog, untouched, leaves its reference found by geometry as it
        was: written again with plain names it would lose its report entry and warning."""
        self.assertIn("Warning", obj.State)
        [row] = App.getReferenceReport(obj)
        self.assertEqual(row["property"], prop)
        Gui.ActiveDocument.setEdit(obj)
        pump()
        self.close(QtWidgets.QDialogButtonBox.Ok)
        self.doc.recompute()
        self.assertTrue(obj.isValid(), obj.getStatusString())
        self.assertIn("Warning", obj.State)
        self.assertEqual([r["property"] for r in App.getReferenceReport(obj)], [prop])

    def testDatumOkKeepsTheWarning(self):
        """Review B1: the attachment dialog (TaskDlgAttacher, through the datum's dialog) writes
        AttachmentSupport on OK only when it changed it."""
        body, pad = self.redrawnPad()
        point = body.newObject("PartDesign::Point", "Point")
        point.AttachmentSupport = [(pad, face("plane", normal=-Y, through=(0, 0, 0)).one(pad.Shape)[0])]
        point.MapMode = "CenterOfMass"
        self.doc.recompute()
        self.redraw()
        self.assertOkKeepsTheWarning(point, "AttachmentSupport")

    def testRevolutionOkKeepsTheWarning(self):
        """Review M7: P7's guard on Revolution: ReferenceAxis isn't written again on OK."""
        doc = self.doc
        body, pad = self.redrawnPad()
        sketch = models.sketch(doc, "RevSketch", models.rectangle(22, 0, 24, 4), body)
        revolution = body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = sketch
        revolution.ReferenceAxis = (pad, edge("line", direction=Y, through=(20, 0, 0)).one(pad.Shape))
        revolution.Angle = 90
        doc.recompute()
        self.redraw()
        self.assertOkKeepsTheWarning(revolution, "ReferenceAxis")

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
        #   the panel lists the rows again after the dialog's own write (review M3)
        self.assertNotIn("Profile[0]", [r[0] for r in Panel(self).rows()])
        self.close(QtWidgets.QDialogButtonBox.Ok)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, REGION_PAD_VOLUME, places=4)

    def assertProfileSwitchTakesTheNewNormal(self, onOldNormal):
        """A pad of a rectangle on XY, 10 high; in its own dialog the profile is picked again on
        a sketch on XZ. The direction box's "Sketch normal" is the new sketch's, and OK pads along
        it: 10 along Y. (It kept the old sketch's normal, Z, which lies in the new sketch's
        plane, and the pad failed.) `onOldNormal`: ReferenceAxis names the old sketch's normal,
        as after an earlier OK of the dialog, and follows the profile."""
        doc = self.doc
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        xz = App.Placement(App.Vector(), App.Rotation(App.Vector(1, 0, 0), 90))
        side = models.sketch(doc, "Side", models.rectangle(30, 0, 40, 5), body, placement=xz)
        if onOldNormal:
            pad.ReferenceAxis = (profile, ["N_Axis"])
        doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())

        Gui.ActiveDocument.setEdit(pad)
        pump()
        mainWindow = Gui.getMainWindow()
        combo = mainWindow.findChild(QtWidgets.QComboBox, "directionCB")
        button = mainWindow.findChild(QtWidgets.QPushButton, "buttonProfile")
        self.assertEqual(combo.currentIndex(), 0)
        button.click()
        pump()
        Gui.Selection.addSelection(doc.Name, side.Name)
        pump()
        button.click()
        pump()
        self.assertEqual(pad.Profile[0], side)
        self.assertEqual(combo.currentIndex(), 0)

        self.close(QtWidgets.QDialogButtonBox.Ok)

        self.assertTrue(pad.isValid(), pad.getStatusString())
        if pad.ReferenceAxis:
            self.assertEqual(pad.ReferenceAxis[0], side)
        box = pad.Shape.BoundBox
        self.assertAlmostEqual(box.YLength, 10, places=6)
        self.assertAlmostEqual(box.ZLength, 5, places=6)

    def testProfileSwitchTakesTheNewNormal(self):
        """ops#130 (review M6), a pad whose direction was never set."""
        self.assertProfileSwitchTakesTheNewNormal(False)

    def testProfileSwitchRetargetsTheOldNormal(self):
        """ops#130 (review M6), a pad along its sketch's normal by name."""
        self.assertProfileSwitchTakesTheNewNormal(True)

    def testProfileSwitchKeepsAnEdgeDirection(self):
        """ops#130 (PR 120's review): a boss on a block, padded along the block's vertical edge;
        its profile picked again on another sketch keeps that edge as its direction (only the old
        sketch's normal follows the profile)."""
        doc = self.doc
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        block = models.pad(body, profile, 10)
        boss = models.sketch(doc, "BossSketch", models.rectangle(2, 2, 6, 6), body, z=10)
        other = models.sketch(doc, "OtherSketch", models.rectangle(12, 2, 16, 6), body, z=10)
        pad = models.pad(body, boss, 5, "Boss")
        doc.recompute()
        [vertical] = edge("line", direction=Z, through=(20, 0, 0)).one(block.Shape)
        pad.ReferenceAxis = (block, [vertical])
        doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())

        Gui.ActiveDocument.setEdit(pad)
        pump()
        mainWindow = Gui.getMainWindow()
        combo = mainWindow.findChild(QtWidgets.QComboBox, "directionCB")
        button = mainWindow.findChild(QtWidgets.QPushButton, "buttonProfile")
        edgeEntry = combo.currentText()
        self.assertGreater(combo.currentIndex(), 2)
        button.click()
        pump()
        Gui.Selection.addSelection(doc.Name, other.Name)
        pump()
        button.click()
        pump()
        self.assertEqual(pad.Profile[0], other)
        self.assertEqual(combo.currentText(), edgeEntry)

        self.close(QtWidgets.QDialogButtonBox.Ok)

        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertEqual(pad.ReferenceAxis, (block, [vertical]))
        box = pad.Shape.BoundBox
        self.assertAlmostEqual(box.ZMax, 15, places=6)

    def testProfilePickSaysWhatItRefuses(self):
        """ops#130 (the review's ProfileGate nit): picking the profile again, a vertex of the solid
        before or of a sketch is refused with a reason on the status bar."""
        doc = self.doc
        body = models.body(doc)
        profile = models.sketch(doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        base = models.pad(body, profile, 10)
        top = models.sketch(doc, "Top", models.rectangle(5, 2, 15, 8), body, z=10)
        pad = models.pad(body, top, 5, "Boss")
        doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        Gui.ActiveDocument.setEdit(pad)
        pump()
        mainWindow = Gui.getMainWindow()
        button = mainWindow.findChild(QtWidgets.QPushButton, "buttonProfile")
        button.click()
        pump()
        self.assertTrue(button.isChecked())

        def statusTexts():
            return [label.text() for label in mainWindow.statusBar().findChildren(QtWidgets.QLabel)]

        for obj, reason in ((base, "faces or edges of the solid"), (top, "its regions or its edges")):
            mainWindow.showMessage("", 0)
            Gui.Selection.addSelection(doc.Name, obj.Name, "Vertex1")
            pump()
            self.assertEqual(Gui.Selection.getSelectionEx(doc.Name), [])
            self.assertTrue(any(reason in text for text in statusTexts()), statusTexts())
        self.assertEqual(pad.Profile[0], top)
        button.click()
        pump()
