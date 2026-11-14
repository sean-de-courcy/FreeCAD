# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (slice 8): the pattern panel in a listed studio
#
# A Linear pattern, Polar pattern or Mirror made in a part of a listed studio joins the studio's
# list at the bar, and its Features field takes studio features: an owner row (a Features-list
# row), or a face of the part that the owner's step made, which stands for the owner. A pattern
# that can't copy an original (one acting on two parts, an Up to last one...) says why in its
# Features field (TestStudioPatterns has the rules).
#
# Designed geometry only: two plates in the studio S, P (x 0..60, y 0..20) and Q (x 0..60,
# y 40..60), 10 high; Hole, an r3 cut 5 deep at (10, 10) on P; Across, a 4 x 50 cut 3 deep over
# both plates.

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor
from PartDesignTests.TestReferenceFieldGui import armed, entries, settle
from PartDesignTests.TestStudioList import studioList
from PartDesignTests.TestStudioOwner import makeOwner, studioSketch
from PartDesignTests.TestStudioPatterns import newStudio

PLATE = 60 * 20 * 10
HOLE = math.pi * 9 * 5


def flushDeletes():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def originalsField():
    flushDeletes()
    for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, "fieldOriginals"):
        if widget.isVisible():
            return widget
    return None


def reapplyBox():
    flushDeletes()
    for widget in Gui.getMainWindow().findChildren(QtWidgets.QCheckBox, "checkBoxReapply"):
        if widget.isVisible():
            return widget
    return None


def statusOf(field):
    label = field.findChild(QtWidgets.QLabel, "status")
    return label.text() if label is not None and label.isVisible() else ""


class TestStudioPatternsGui(unittest.TestCase):
    def setUp(self):
        self.doc, self.S = newStudio(
            "StudioPatternsGui", (("P", (0, 0, 60, 20), 10), ("Q", (0, 40, 60, 60), 10))
        )
        self.doc.UndoMode = 1
        sk = studioSketch(self.doc, self.S, "HoleSk", z=10, circles=((10, 10, 3),))
        self.hole = makeOwner(self.doc, self.S, "Pocket", "Hole", sk, ("P",), Length=5)
        sk = studioSketch(self.doc, self.S, "AcrossSk", rects=((30, 5, 34, 55),), z=10)
        self.across = makeOwner(self.doc, self.S, "Pocket", "Across", sk, ("P", "Q"), Length=3)
        self.doc.recompute()
        self.P = self.doc.getObject("P")
        Gui.Selection.clearSelection()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.P)

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

    # ------------------------------------------------------------------------------ helpers
    def runTool(self, command, *selection):
        Gui.Selection.clearSelection()
        for obj in selection:
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        settle()

    def pattern(self):
        found = [o for o in self.doc.Objects if o.TypeId == "PartDesign::LinearPattern"]
        self.assertEqual(len(found), 1, [o.Name for o in found])
        return found[0]

    def accept(self):
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok, "no OK button")
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays open")
        self.doc.recompute()

    def field(self):
        self.assertTrue(waitFor(lambda: originalsField() is not None), "no Features field")
        return originalsField()

    def pick(self, obj, sub=""):
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        pump(0.3)

    def holeFace(self, feature):
        """The hole's wall in feature's shape."""
        for i, face in enumerate(feature.Shape.Faces, 1):
            if face.Surface.__class__.__name__ == "Cylinder":
                return f"Face{i}"
        self.fail(f"no hole wall in {feature.Name}")

    # ------------------------------------------------------------------------------ tests
    def testOwnerRowMakesTheOriginal(self):
        """The Hole's row selected, Linear pattern: the original is the studio feature, the pattern
        joins the list at the bar, and OK makes two holes in P."""
        self.runTool("PartDesign_LinearPattern", self.hole)
        pattern = self.pattern()
        self.assertEqual(pattern.Originals, [self.hole])
        self.assertIn(pattern, list(studioList(self.doc).Entries))
        self.assertEqual(list(studioList(self.doc).Entries)[-1], pattern)
        self.accept()
        pattern.Mode = "Spacing"
        pattern.Offset = 10
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertEqual(self.P.Tip, pattern)
        self.assertAlmostEqual(pattern.Shape.Volume, PLATE - 2 * HOLE - 4 * 15 * 3, places=3)

    def testFacePickStandsForTheStudioFeature(self):
        """With nothing selected the Features field opens armed; a pick of the hole's wall in the
        part adds the Hole (the studio feature, not its step); a second pick takes it out."""
        base = self.P.Tip  # the solid before the pattern: the field's picks are in its shape
        self.runTool("PartDesign_LinearPattern")
        pattern = self.pattern()
        field = self.field()
        self.assertTrue(waitFor(lambda: armed(field)), "the empty Features field isn't armed")
        self.pick(base, self.holeFace(base))
        self.assertEqual(pattern.Originals, [self.hole])
        self.assertEqual(entries(field).count(), 1)
        self.pick(base, self.holeFace(base))
        self.assertEqual(pattern.Originals, [])

    def testRefusalShowsInTheField(self):
        """Across (on P and Q) picked: the pattern takes it, fails, and its Features field says why;
        accepted red, an edit again says it too."""
        self.runTool("PartDesign_LinearPattern")
        pattern = self.pattern()
        field = self.field()
        self.assertTrue(waitFor(lambda: armed(field)))
        self.pick(self.across)
        self.assertEqual(pattern.Originals, [self.across])
        self.assertFalse(pattern.isValid())
        self.assertIn("Across", statusOf(field))
        self.assertIn("2 parts", statusOf(field))
        self.accept()
        self.assertFalse(pattern.isValid())
        Gui.getDocument(self.doc.Name).setEdit(pattern.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()))
        settle()
        field = self.field()
        self.assertTrue(waitFor(lambda: "2 parts" in statusOf(field)), statusOf(field))

    def testEditAgain(self):
        """OK, then an edit again: the field lists the Hole; Cancel leaves the pattern as it was."""
        self.runTool("PartDesign_LinearPattern", self.hole)
        pattern = self.pattern()
        self.accept()
        volume = pattern.Shape.Volume
        Gui.getDocument(self.doc.Name).setEdit(pattern.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()))
        settle()
        field = self.field()
        self.assertEqual([entries(field).item(i).text() for i in range(entries(field).count())],
                         ["Hole"])
        cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
        cancel.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        self.doc.recompute()
        self.assertEqual(pattern.Originals, [self.hole])
        self.assertAlmostEqual(pattern.Shape.Volume, volume, places=4)

    # ------------------------------------------------------------------------------ Reapply (T3)
    def editAgain(self, pattern):
        Gui.getDocument(self.doc.Name).setEdit(pattern.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()))
        settle()
        self.assertTrue(waitFor(lambda: reapplyBox() is not None), "no Reapply box")
        return reapplyBox()

    def testReapplyBoxInEachPanel(self):
        """Linear, Polar and Mirror panels in a listed studio: a Reapply features box, off by
        default; ticked, the pattern's Reapply is on; OK, and an edit again shows it ticked."""
        kinds = (
            ("PartDesign_LinearPattern", "PartDesign::LinearPattern"),
            ("PartDesign_PolarPattern", "PartDesign::PolarPattern"),
            ("PartDesign_Mirrored", "PartDesign::Mirrored"),
        )
        for command, typeId in kinds:
            with self.subTest(command):
                self.runTool(command, self.hole)
                found = [o for o in self.doc.Objects if o.TypeId == typeId]
                self.assertEqual(len(found), 1)
                pattern = found[0]
                self.assertTrue(waitFor(lambda: reapplyBox() is not None), "no Reapply box")
                box = reapplyBox()
                self.assertFalse(box.isChecked())
                self.assertFalse(pattern.Reapply)
                box.click()
                pump(0.2)
                self.assertTrue(pattern.Reapply)
                self.accept()
                self.assertTrue(pattern.Reapply)
                box = self.editAgain(pattern)
                self.assertTrue(box.isChecked())
                taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
                self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
                self.assertTrue(pattern.Reapply)

    def testReapplyBoxTurnsARefusalIntoInstances(self):
        """An Up to last hole (its copies refused with Reapply off); the box ticked, the pattern
        computes each instance, and its Features field shows no refusal."""
        sk = studioSketch(self.doc, self.S, "NextSk", z=10, circles=((10, 10, 3),))
        nxt = makeOwner(self.doc, self.S, "Pocket", "Next", sk, ("P",), Type="UpToLast")
        self.doc.recompute()
        self.runTool("PartDesign_LinearPattern", nxt)
        pattern = self.pattern()
        field = self.field()
        # two instances on the plate: the seed's and one 30 along x
        pattern.Direction = (self.P.Origin.OriginFeatures[0], [""])
        pattern.Mode = "Extent"
        pattern.Length = 30
        pattern.Occurrences = 2
        self.doc.recompute()
        self.assertFalse(pattern.isValid())
        self.assertIn("Up to last", pattern.getStatusString())
        self.assertTrue(waitFor(lambda: reapplyBox() is not None))
        reapplyBox().click()
        pump(0.2)
        self.assertTrue(pattern.Reapply)
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertNotIn("Up to last", statusOf(field))
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())

    def testFirstPatternInAFreshStudioMakesTheList(self):
        """ops#654 list on first use: in a fresh document (a Body at the top level, its plate and
        boss made without a list) the first Linear pattern makes the studio's list in its own
        step, the Body's members adopted in order and the pattern at the bar, the boss its
        original; one undo takes the pattern and the list."""
        from PartDesignTests.TestStudio import pad, sketch, xyPlane

        doc = App.newDocument("FirstPattern")
        doc.UndoMode = 1
        try:
            body = doc.addObject("PartDesign::Body", "Body")
            pad(body, "Plate", sketch(body, "PlateSk", xyPlane(body), (0, 0, 60, 20)), 10)
            boss = pad(body, "Boss", sketch(body, "BossSk", xyPlane(body), (2, 7, 8, 13), z=10), 5)
            doc.recompute()
            self.assertIsNone(PartDesign.studioList(doc))
            App.setActiveDocument(doc.Name)
            Gui.setActiveDocument(doc.Name)
            pump(0.2)
            Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", body)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, boss.Name)
            undo, before = doc.UndoCount, sorted(o.Name for o in doc.Objects)
            Gui.runCommand("PartDesign_LinearPattern")
            self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
            settle()
            lst = PartDesign.studioList(doc)
            self.assertIsNotNone(lst, "no list made")
            pattern = next(o for o in doc.Objects if o.TypeId == "PartDesign::LinearPattern")
            self.assertEqual(
                [e.Name for e in lst.Entries], ["PlateSk", "Plate", "BossSk", "Boss", pattern.Name]
            )
            self.assertEqual(list(pattern.Originals), [boss])
            ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
            ok.click()
            self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
            doc.recompute()
            self.assertIn(pattern, PartDesign.studioList(doc).Entries)
            self.assertEqual(doc.UndoCount, undo + 1)
            doc.undo()
            doc.recompute()
            self.assertIsNone(PartDesign.studioList(doc))
            self.assertEqual(sorted(o.Name for o in doc.Objects), before)
            self.assertAlmostEqual(body.Shape.Volume, 60 * 20 * 10 + 6 * 6 * 5, places=4)
        finally:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
                pump()
            App.closeDocument(doc.Name)
            App.setActiveDocument(self.doc.Name)
            Gui.setActiveDocument(self.doc.Name)

    def testReapplyBoxInABody(self):
        """In a Body at a document's top level, the Linear panel has the box too, and it works
        (the document's list is made by the pattern since ops#654's list on first use)."""
        from PartDesignTests.TestStudio import pad, sketch, xyPlane

        doc = App.newDocument("ReapplyBody")
        try:
            body = doc.addObject("PartDesign::Body", "Body")
            pad(body, "Plate", sketch(body, "PlateSk", xyPlane(body), (0, 0, 60, 20)), 10)
            boss = pad(body, "Boss", sketch(body, "BossSk", xyPlane(body), (2, 7, 8, 13), z=10), 5)
            doc.recompute()
            App.setActiveDocument(doc.Name)
            Gui.setActiveDocument(doc.Name)
            pump(0.2)
            Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", body)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, boss.Name)
            Gui.runCommand("PartDesign_LinearPattern")
            self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
            settle()
            self.assertTrue(waitFor(lambda: reapplyBox() is not None), "no Reapply box")
            reapplyBox().click()
            pump(0.2)
            pattern = next(o for o in doc.Objects if o.TypeId == "PartDesign::LinearPattern")
            self.assertTrue(pattern.Reapply)
            ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
            ok.click()
            self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
            doc.recompute()
            self.assertTrue(pattern.isValid(), pattern.getStatusString())
            self.assertTrue(pattern.Reapply)
        finally:
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
                pump()
            App.closeDocument(doc.Name)
            App.setActiveDocument(self.doc.Name)
            Gui.setActiveDocument(self.doc.Name)


if __name__ == "__main__":
    unittest.main()
