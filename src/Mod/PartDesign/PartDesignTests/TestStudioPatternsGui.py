# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (slice 8): the pattern panel in a listed studio
#
# A Linear pattern, Polar pattern or Mirror made in a part of a listed studio joins the studio's
# list at the bar, and its Features field takes studio features: an owner row (a Features-list
# row), or a face of the part that the owner's step made, which stands for the owner. A pattern
# that can't copy an original (one acting on two parts, an Up to last one...) says why in its
# Features field (TestStudioPatterns has the rules).
#
# T1a (notes/parts-design.md 10.16): the pattern a command makes in a listed studio is a studio
# feature (an owner) outside every Body, in one step with its list entry and its steps (Cancel
# leaves nothing); its native panel edits the owner: Features takes studio features and members of
# any part of the studio, the direction or plane offers the studio's own origin, and there is no
# merge-scope field. A step that can't pattern its part says why in the Features field.
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
ACROSS = 4 * 15 * 3  # Across's cut in each plate


def isOwnerPattern(obj, typeId="PartDesign::LinearPattern"):
    """A pattern of typeId that is no step (a T1a owner, or an in-Body pattern of an unlisted
    document)."""
    return obj.TypeId == typeId and getattr(obj, "StudioOwner", None) is None


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

    def pattern(self, typeId="PartDesign::LinearPattern"):
        found = [o for o in self.doc.Objects if isOwnerPattern(o, typeId)]
        self.assertEqual(len(found), 1, [o.Name for o in found])
        return found[0]

    def cancel(self):
        cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
        self.assertIsNotNone(cancel, "no Cancel button")
        cancel.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays open")
        self.doc.recompute()

    def step(self, owner, part):
        return PartDesign.studioStepOf(owner, self.doc.getObject(part))

    def assertTip(self, part, volume):
        body = self.doc.getObject(part)
        self.assertTrue(body.Tip.isValid(), f"{body.Tip.Name}: {body.Tip.getStatusString()}")
        self.assertAlmostEqual(body.Tip.Shape.Volume, volume, places=3, msg=part)

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
        # T1a: a studio feature; its step in P is P's Tip
        self.assertEqual(self.P.Tip, self.step(pattern, "P"))
        self.assertTip("P", PLATE - 2 * HOLE - ACROSS)

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
        """T1a: Bosses (an Add on P and on Q) picked: the pattern takes it and fails in Onshape's
        words (Q2: an Add over two parts with Reapply off), and its Features field says why;
        accepted red, an edit again says it too."""
        sk = studioSketch(
            self.doc, self.S, "BossesSk", rects=((40, 5, 44, 9), (40, 45, 44, 49)), z=10
        )
        bosses = makeOwner(self.doc, self.S, "Pad", "Bosses", sk, ("P", "Q"), Length=2)
        self.doc.recompute()
        self.runTool("PartDesign_LinearPattern")
        pattern = self.pattern()
        field = self.field()
        self.assertTrue(waitFor(lambda: armed(field)))
        self.pick(bosses)
        self.assertEqual(pattern.Originals, [bosses])
        self.assertFalse(pattern.isValid())
        self.assertIn("Bosses", statusOf(field))
        self.assertIn("2 parts", statusOf(field))
        self.assertIn('Try selecting "Reapply features" option.', statusOf(field))
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
        volume = self.P.Shape.Volume
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
        self.assertAlmostEqual(self.P.Shape.Volume, volume, places=4)

    # ------------------------------------------------------------------------------ T1a
    def testCommandMakesAnOwnerOverParts(self):
        """Across (on P and Q) selected, Linear pattern: a studio feature outside every Body, last
        in the list, its direction the studio's X axis; OK: a step in each part, each plate cut
        twice (O7); one undo step, whose undo leaves the document as it was."""
        undo = self.doc.UndoCount
        names = sorted(o.Name for o in self.doc.Objects)
        before = {p: self.doc.getObject(p).Shape.Volume for p in "PQ"}
        self.runTool("PartDesign_LinearPattern", self.across)
        pattern = self.pattern()
        self.assertEqual(pattern.getParentGeoFeatureGroup(), self.S)
        self.assertIsNone(pattern.getParentGeoFeatureGroup().getParentGeoFeatureGroup())
        self.assertEqual(list(studioList(self.doc).Entries)[-1], pattern)
        self.assertEqual(pattern.Originals, [self.across])
        self.assertEqual(pattern.Direction[0], self.S.Origin.OriginFeatures[0])
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        for part in "PQ":
            step = self.step(pattern, part)
            self.assertIsNotNone(step, part)
            self.assertEqual(step.TypeId, "PartDesign::LinearPattern")
            self.assertEqual(self.doc.getObject(part).Tip, step)
        # Onshape's defaults: two instances 25 apart along x
        self.assertTip("P", PLATE - HOLE - 2 * ACROSS)
        self.assertTip("Q", PLATE - 2 * ACROSS)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        for p in "PQ":
            self.assertAlmostEqual(self.doc.getObject(p).Shape.Volume, before[p], places=4)
        self.doc.redo()
        self.doc.recompute()
        self.assertTip("Q", PLATE - 2 * ACROSS)

    def testCancelLeavesNothing(self):
        """Hole selected, Linear pattern, Cancel: no object, no list entry, no undo step."""
        undo = self.doc.UndoCount
        names = sorted(o.Name for o in self.doc.Objects)
        entries = [e.Name for e in studioList(self.doc).Entries]
        self.runTool("PartDesign_LinearPattern", self.hole)
        self.pattern()
        self.cancel()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertEqual([e.Name for e in studioList(self.doc).Entries], entries)
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertTip("P", PLATE - HOLE - ACROSS)

    def testFeaturesTakesAFeatureOfAnotherPart(self):
        """Made on the Hole (P), the Features field takes the Hole on Q (a Features-list row);
        OK: a step in each part, each patterning only its own original."""
        sk = studioSketch(self.doc, self.S, "HoleQSk", z=10, circles=((10, 50, 3),))
        holeQ = makeOwner(self.doc, self.S, "Pocket", "HoleQ", sk, ("Q",), Length=5)
        self.doc.recompute()
        self.runTool("PartDesign_LinearPattern", self.hole)
        pattern = self.pattern()
        field = self.field()
        field.setProperty("armed", True)
        pump(0.1)
        self.assertTrue(waitFor(lambda: armed(field)), "the field isn't armed")
        self.pick(holeQ)
        self.assertEqual(pattern.Originals, [self.hole, holeQ])
        self.assertEqual(
            [entries(field).item(i).text() for i in range(entries(field).count())],
            ["Hole", "HoleQ"],
        )
        self.accept()
        pattern.Offset = 15  # the copies clear of Across (x 30..34)
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertEqual(list(self.step(pattern, "P").Originals), [self.step(self.hole, "P")])
        self.assertEqual(list(self.step(pattern, "Q").Originals), [self.step(holeQ, "Q")])
        self.assertTip("P", PLATE - 2 * HOLE - ACROSS)
        self.assertTip("Q", PLATE - 2 * HOLE - ACROSS)

    def testPanelOnTheOwner(self):
        """The Linear panel on the owner: its direction box offers the studio's axes, and there
        is no merge-scope field (no Result box); the Mirror panel offers the studio's planes."""
        self.runTool("PartDesign_LinearPattern", self.hole)
        self.pattern()
        main = Gui.getMainWindow()
        combo = main.findChild(QtWidgets.QComboBox, "comboDirection")
        self.assertIsNotNone(combo, "no direction box")
        texts = [combo.itemText(i) for i in range(combo.count())]
        self.assertTrue(any("X" in t for t in texts), texts)
        self.assertTrue(any("Y" in t for t in texts), texts)
        for name in ("studioScopeList", "resultCombo", "studioMergeAll"):
            widget = main.findChild(QtWidgets.QWidget, name)
            self.assertTrue(widget is None or not widget.isVisible(), name)
        self.cancel()
        self.runTool("PartDesign_Mirrored", self.hole)
        mirror = self.pattern("PartDesign::Mirrored")
        self.assertEqual(mirror.getParentGeoFeatureGroup(), self.S)
        combo = main.findChild(QtWidgets.QComboBox, "comboPlane")
        self.assertIsNotNone(combo, "no plane box")
        texts = [combo.itemText(i) for i in range(combo.count())]
        self.assertGreaterEqual(sum(1 for t in texts if "plane" in t.lower()), 3, texts)
        self.cancel()

    def testEditAgainAfterAnOriginalIsDeleted(self):
        """Hole and Across patterned; Across deleted: the owner keeps the Hole, and an edit again
        lists the Hole after a "Missing feature" row (T1b, fact U5), the pattern valid."""
        self.runTool("PartDesign_LinearPattern", self.hole, self.across)
        pattern = self.pattern()
        self.assertEqual(sorted(o.Name for o in pattern.Originals), ["Across", "Hole"])
        self.accept()
        self.doc.openTransaction("delete Across")
        PartDesign.studioRemove(self.across)
        self.doc.removeObject("Across")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(pattern.Originals, [self.hole])
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        Gui.getDocument(self.doc.Name).setEdit(pattern.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()))
        settle()
        field = self.field()
        self.assertEqual(
            [entries(field).item(i).text() for i in range(entries(field).count())],
            ["Missing feature", "Hole"],
        )
        self.cancel()
        self.assertTip("P", PLATE - 2 * HOLE)

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
                pattern = self.pattern(typeId)
                self.assertEqual(pattern.getParentGeoFeatureGroup(), self.S)  # T1a: an owner
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
        pattern.Direction = (self.S.Origin.OriginFeatures[0], [""])
        pattern.Mode = "Extent"
        pattern.Length = 30
        pattern.Occurrences = 2
        self.doc.recompute()
        # T1a: the owner computes; its step in P refuses the copy, and the field says why
        step = self.step(pattern, "P")
        self.assertFalse(step.isValid())
        self.assertIn("Up to last", step.getStatusString())
        self.assertTrue(waitFor(lambda: reapplyBox() is not None))
        reapplyBox().click()
        pump(0.2)
        self.assertTrue(pattern.Reapply)
        self.assertTrue(step.isValid(), step.getStatusString())
        self.assertNotIn("Up to last", statusOf(field))
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertTrue(step.isValid(), step.getStatusString())

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

    # ------------------------------------------------------------------------------ T1b
    # Merging, New and split seeds (10.16 settled 2, 3, 7): their instances make parts or split
    # one, which only the command makes (P6p); the dialog's OK is that command.
    def liveParts(self):
        return PartDesign.studioLiveParts(studioList(self.doc))

    def madeBy(self, owner):
        return [o for o in self.doc.Objects
                if o.TypeId == "PartDesign::Body" and getattr(o, "StudioMadeBy", None) == owner]

    def newSeed(self):
        """N: a New Pad 10 x 10 x 5 (500) at x 0..10, y 70..80, its own part."""
        sk = studioSketch(self.doc, self.S, "NSk", rects=((0, 70, 10, 80),), z=0)
        n = makeOwner(self.doc, self.S, "Pad", "N", sk, (), Length=5)
        self.doc.openTransaction("new part")
        PartDesign.studioNewPart(n)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertTrue(n.isValid(), n.getStatusString())
        return n

    def slot(self):
        """Slot: a 4 wide Remove through both plates at x 30..34 (over Across), splitting each;
        its pieces made: four parts."""
        sk = studioSketch(self.doc, self.S, "SlotSk", rects=((30, -5, 34, 65),), z=10)
        slot = makeOwner(self.doc, self.S, "Pocket", "Slot", sk, ("P", "Q"), Length=10)
        self.doc.recompute()
        self.doc.openTransaction("pieces")
        PartDesign.studioMakePieces(slot)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(len(self.liveParts()), 4)
        return slot

    def bosses(self):
        """Bosses: an Add on P and on Q, 4 x 4 x 2 on top of each plate at x 40..44."""
        sk = studioSketch(
            self.doc, self.S, "BossesSk", rects=((40, 5, 44, 9), (40, 45, 44, 49)), z=10
        )
        bosses = makeOwner(self.doc, self.S, "Pad", "Bosses", sk, ("P", "Q"), Length=2)
        self.doc.recompute()
        return bosses

    def tickReapply(self):
        self.assertTrue(waitFor(lambda: reapplyBox() is not None), "no Reapply box")
        box = reapplyBox()
        self.assertTrue(box.isEnabled())
        self.assertFalse(box.isChecked())
        box.click()
        pump(0.3)

    def testOkMakesTheNewSeedsParts(self):
        """Acceptance 6 through the panel (settled 3): the New seed patterned (two instances 25
        apart along x): OK makes the instance a part of its own, made by the pattern, 500 at
        x 25..35, with no second step; the pattern valid; one undo step takes the pattern and
        its part back; redo brings them again."""
        n = self.newSeed()
        undo, names = self.doc.UndoCount, sorted(o.Name for o in self.doc.Objects)
        live = len(self.liveParts())
        self.runTool("PartDesign_LinearPattern", n)
        pattern = self.pattern()
        self.assertEqual(pattern.Originals, [n])
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        made = self.madeBy(pattern)
        self.assertEqual(len(made), 1, [b.Name for b in made])
        self.assertAlmostEqual(made[0].Shape.Volume, 500, places=3)
        self.assertAlmostEqual(made[0].Shape.BoundBox.Center.x, 30, places=6)
        self.assertEqual(len(self.liveParts()), live + 1)
        self.assertTip("P", PLATE - HOLE - ACROSS)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertEqual(len(self.liveParts()), live)
        self.doc.redo()
        self.doc.recompute()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.assertEqual(len(self.madeBy(pattern)), 1)

    def testCancelOnANewSeedLeavesNothing(self):
        """The New seed's pattern cancelled: no object, no part, no undo step."""
        n = self.newSeed()
        undo, names = self.doc.UndoCount, sorted(o.Name for o in self.doc.Objects)
        live = len(self.liveParts())
        self.runTool("PartDesign_LinearPattern", n)
        self.pattern()
        self.cancel()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertEqual(len(self.liveParts()), live)
        self.assertEqual(self.doc.UndoCount, undo)

    def testSplitSeedRefusedUntilReapplyThenOkMakesThePieces(self):
        """Acceptance 5 through the panel (settled 7, facts U6): the Slot that split both plates,
        patterned: with Reapply off the Features field shows Onshape's words; Reapply ticked,
        the live preview clears them; OK cuts every piece at the instance (x 55..59) and makes
        the pieces parts: six, valid; one undo step takes them back to the Slot's four."""
        slot = self.slot()
        undo, names = self.doc.UndoCount, sorted(o.Name for o in self.doc.Objects)
        self.runTool("PartDesign_LinearPattern", slot)
        pattern = self.pattern()
        field = self.field()
        self.assertFalse(pattern.isValid())
        self.assertIn("Could not create all instances as entered.", statusOf(field))
        self.assertIn('Try selecting "Reapply features" option.', statusOf(field))
        self.tickReapply()
        self.assertTrue(pattern.Reapply)
        self.assertNotIn("Could not create all instances", statusOf(field))
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        volumes = sorted(round(b.Shape.Volume, 3) for b in self.liveParts())
        self.assertEqual(
            volumes, sorted([round(6000 - HOLE, 3), 6000.0, 4200.0, 4200.0, 200.0, 200.0])
        )
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), names)
        self.assertEqual(len(self.liveParts()), 4)

    def testAddOnTwoPartsRefusedUntilReapplyThenOkMakesItsParts(self):
        """Settled 2 and Q7 through the panel: Bosses (an Add on P and Q) patterned, Reapply off:
        Onshape's words in the field; ticked, they go; the instances (x 65..69) join no part, and
        OK makes each a part of its own (32 each), the pattern valid, the plates untouched."""
        bosses = self.bosses()
        before = {p: self.doc.getObject(p).Tip.Shape.Volume for p in "PQ"}
        self.runTool("PartDesign_LinearPattern", bosses)
        pattern = self.pattern()
        field = self.field()
        self.assertIn("Could not create all instances as entered.", statusOf(field))
        self.tickReapply()
        self.assertNotIn("Could not create all instances", statusOf(field))
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        made = self.madeBy(pattern)
        self.assertEqual(len(made), 2, [b.Name for b in made])
        for body in made:
            self.assertAlmostEqual(body.Shape.Volume, 32, places=3)
        for p in "PQ":
            self.assertAlmostEqual(self.doc.getObject(p).Tip.Shape.Volume, before[p], places=3)

    def lateOnQ(self):
        """HoleQ, an r3 hole in Q at (10, 50), then Late, a boss on Q after it: Q's Tip is
        Late's step, whose hole wall HoleQ made."""
        sk = studioSketch(self.doc, self.S, "HoleQSk", z=10, circles=((10, 50, 3),))
        holeQ = makeOwner(self.doc, self.S, "Pocket", "HoleQ", sk, ("Q",), Length=5)
        sk = studioSketch(self.doc, self.S, "LateSk", rects=((50, 45, 55, 50),), z=10)
        late = makeOwner(self.doc, self.S, "Pad", "Late", sk, ("Q",), Length=2)
        self.doc.recompute()
        self.assertEqual(self.doc.getObject("Q").Tip, self.step(late, "Q"))
        return holeQ, late

    def testFaceOfAnotherPartPicksTheFeatureThatMadeIt(self):
        """T1b cross-part picks: with P active, a pick of the hole wall in Q's solid adds HoleQ
        (the feature that made the face), not Late (Q's last feature)."""
        holeQ, late = self.lateOnQ()
        self.runTool("PartDesign_LinearPattern", self.hole)
        pattern = self.pattern()
        field = self.field()
        field.setProperty("armed", True)
        pump(0.1)
        self.assertTrue(waitFor(lambda: armed(field)), "the field isn't armed")
        qTip = self.doc.getObject("Q").Tip
        self.pick(qTip, self.holeFace(qTip))
        self.assertEqual(pattern.Originals, [self.hole, holeQ])

    def testPartsListRowIsRefused(self):
        """A pick of a part (a Parts-list row: its Body) is no original: refused with a status
        line, the Features list unchanged."""
        from PartDesignTests.TestDressUpDeleteKeyGui import statusText

        self.runTool("PartDesign_LinearPattern", self.hole)
        pattern = self.pattern()
        field = self.field()
        field.setProperty("armed", True)
        pump(0.1)
        self.assertTrue(waitFor(lambda: armed(field)), "the field isn't armed")
        self.pick(self.doc.getObject("Q"))
        self.assertEqual(pattern.Originals, [self.hole])
        self.assertEqual(entries(field).count(), 1)
        text = statusText() + " " + statusOf(field)
        self.assertIn("not a part", text)

    def testAPartGivenAStepInTheDialogIsPreviewed(self):
        """T1b preview: the Hole patterned, then HoleQ added in the open dialog: Q gets a step,
        which the edit's roll-back doesn't hold, so Q shows it computed, as P shows its own."""
        sk = studioSketch(self.doc, self.S, "HoleQSk", z=10, circles=((10, 50, 3),))
        holeQ = makeOwner(self.doc, self.S, "Pocket", "HoleQ", sk, ("Q",), Length=5)
        self.doc.recompute()
        self.runTool("PartDesign_LinearPattern", self.hole)
        pattern = self.pattern()
        field = self.field()
        field.setProperty("armed", True)
        pump(0.1)
        self.assertTrue(waitFor(lambda: armed(field)), "the field isn't armed")
        self.pick(holeQ)
        pump(0.3)
        for part in "PQ":
            with self.subTest(part):
                step = self.step(pattern, part)
                self.assertIsNotNone(step, part)
                body = self.doc.getObject(part)
                self.assertFalse(body.isRolledBack(), f"{part} holds its step")
                self.assertTrue(step.isValid(), step.getStatusString())
                self.assertNotIn("Touched", step.State, f"{part}'s step isn't computed")
        # the copy 25 along x (at (35, 50), partly in Across's cut) takes more of Q
        self.assertLess(self.step(pattern, "Q").Shape.Volume, PLATE - HOLE - ACROSS - 10)
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())

    def deleteOwner(self, owner):
        self.doc.openTransaction("delete " + owner.Name)
        PartDesign.studioRemove(owner)
        self.doc.removeObject(owner.Name)
        self.doc.commitTransaction()
        self.doc.recompute()

    def testDeletedSeedIsAMissingFeatureRowUntilRemoved(self):
        """Fact U5: Hole and Across patterned, Across deleted: the pattern stays valid on the
        Hole; its Features list shows a red "Missing feature" row and the Hole; the row taken
        out (Delete), it is gone, also after OK and an edit again."""
        from PartDesignTests.TestReferenceFieldGui import clickRow, key, texts

        self.runTool("PartDesign_LinearPattern", self.hole, self.across)
        pattern = self.pattern()
        self.accept()
        self.deleteOwner(self.across)
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.editAgain(pattern)
        field = self.field()
        self.assertEqual(texts(field), ["Missing feature", "Hole"])
        row = entries(field).item(0)
        self.assertGreater(row.background().color().red(), 200)
        self.assertEqual(row.background().color().green(), 0)
        clickRow(field, 0)
        key(QtCore.Qt.Key_Delete)
        self.assertTrue(waitFor(lambda: texts(field) == ["Hole"]), texts(field))
        self.assertEqual(pattern.Originals, [self.hole])
        self.accept()
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        self.editAgain(pattern)
        self.assertEqual(texts(self.field()), ["Hole"])
        self.cancel()

    def testEverySeedDeletedIsTwoMissingRowsAndTheError(self):
        """Fact U5: both originals deleted: Onshape's error ("Select features to pattern.") and
        two "Missing feature" rows."""
        from PartDesignTests.TestReferenceFieldGui import texts

        self.runTool("PartDesign_LinearPattern", self.hole, self.across)
        pattern = self.pattern()
        self.accept()
        self.deleteOwner(self.across)
        self.deleteOwner(self.hole)
        self.assertFalse(pattern.isValid())
        self.assertIn("Select features to pattern", pattern.getStatusString())
        self.editAgain(pattern)
        field = self.field()
        self.assertEqual(texts(field), ["Missing feature", "Missing feature"])
        self.assertIn("Select features to pattern", statusOf(field))
        self.cancel()

    def testSuppressedSeedRowIsGreyedAndStruckThrough(self):
        """Fact U7: the only original suppressed: the App's error in the field, and its row
        greyed and struck through."""
        self.runTool("PartDesign_LinearPattern", self.hole)
        pattern = self.pattern()
        self.accept()
        self.hole.Suppressed = True
        self.doc.recompute()
        self.assertFalse(pattern.isValid())
        self.editAgain(pattern)
        field = self.field()
        row = entries(field).item(0)
        self.assertEqual(row.text(), "Hole")
        self.assertTrue(row.font().strikeOut())
        self.assertEqual(row.foreground().color().name(), "#808080")
        self.assertIn("Selected features do not create any geometry", statusOf(field))
        self.cancel()


if __name__ == "__main__":
    unittest.main()
