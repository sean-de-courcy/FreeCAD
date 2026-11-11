# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (S4): the extrude-family dialog on a studio feature
#
# In a studio that has a list (PartDesign::StudioList), Extrude (PartDesign_Pad) and Extrude
# (remove) (PartDesign_Pocket) make a studio feature, the *owner*: a Pad or Pocket in the studio
# outside every Body, whose steps (PartDesign::FeatureApply) act on the parts of its scope
# (notes/parts-design.md 3.1, 3.5, 10.8-10.11). Its dialog is the usual extrude panel with the
# owner's Result box: New / Add / Remove / Intersect and one tick per part of the studio, the
# sketch's own part included (report 21). Edits are list edits in the dialog's one step.
#
# Designed geometry only: TestStudioList's three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50)
# in the studio S (an App::Part), each a Body with a sketch and a Pad, plus, where a test needs a
# face to stop at, a part D (x 60..70) 4 mm high. Sketches lie in Body A at z = 10 (A's top).
# Expected volumes come from the boxes: a cut of w x h in plan, d deep, removes w*h*d.

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestStudio import edgeAt, faceAt, pad, sketch, xyPlane
from PartDesignTests.TestStudioList import newStudio

CUT = (5, 2, 25, 8)  # 5 x 6 over A (x 5..10) and 5 x 6 over B (x 20..25)
OVER_A = (2, 2, 8, 8)  # 6 x 6 over A
OVER_B = (22, 2, 28, 8)  # 6 x 6 over B, the sketch still in A
ROWS = ["New", "Add", "Remove", "Intersect"]


class StudioDialog:
    """The helpers of a studio feature's dialog tests (setUp makes doc, studio and list)."""

    def openStudio(self, doc, studio):
        self.doc, self.studio = doc, studio
        self.list = PartDesign.studioList(self.studio, True)
        self.doc.recompute()
        Gui.Selection.clearSelection()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    # ------------------------------------------------------------------------------ helpers
    def body(self, name):
        return self.doc.getObject(name)

    def volume(self, name):
        return self.body(name).Shape.Volume

    def assertVolumes(self, **expected):
        for name, value in expected.items():
            self.assertAlmostEqual(self.volume(name), value, places=4, msg=name)

    def sketchInA(self, name, rect):
        """A sketch in Body A on its XY plane at z = 10 (A's top)."""
        s = sketch(self.body("A"), name, xyPlane(self.body("A")), rect, z=10)
        self.doc.recompute()
        return s

    def partD(self):
        """A part D, x 60..70, 4 mm high: its top face at z = 4."""
        body = self.doc.addObject("PartDesign::Body", "D")
        self.studio.addObject(body)
        dpad = pad(body, "DPad", sketch(body, "DSk", xyPlane(body), (60, 0, 70, 10)), 4)
        self.doc.recompute()
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        return dpad

    def entries(self):
        return [e.Name for e in self.list.Entries]

    def objects(self):
        return sorted(o.Name for o in self.doc.Objects)

    def waitForPanel(self):
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.3)
        Gui.Control.showTaskView()
        ok = QtWidgets.QDialogButtonBox.Ok
        self.assertTrue(waitFor(lambda: taskButton(ok) is not None), "the Tasks panel stays hidden")

    def runCommand(self, command, profile, active="B"):
        """The command with Body `active` active (None: none) and profile selected; returns the
        object it made, with its panel open."""
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", self.body(active) if active else None)
        Gui.Selection.clearSelection()
        if profile is not None:
            Gui.Selection.addSelection(self.doc.Name, profile.Name)
        before = set(self.objects())
        Gui.runCommand(command)
        self.waitForPanel()
        made = [
            self.doc.getObject(n)
            for n in set(self.objects()) - before
            if self.doc.getObject(n).TypeId in ("PartDesign::Pad", "PartDesign::Pocket")
            and not getattr(self.doc.getObject(n), "StudioOwner", None)
        ]
        self.assertEqual(len(made), 1, [o.Name for o in made])
        return made[0]

    def visible(self, cls, name):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def combo(self):
        return self.visible(QtWidgets.QComboBox, "resultCombo")

    def scopeList(self):
        return self.visible(QtWidgets.QListWidget, "studioScopeList")

    def ticks(self):
        rows = self.scopeList()
        self.assertIsNotNone(rows, "no part ticks")
        return [
            (rows.item(i).text(), rows.item(i).checkState() == QtCore.Qt.Checked)
            for i in range(rows.count())
        ]

    def tick(self, label, on):
        rows = self.scopeList()
        for i in range(rows.count()):
            if rows.item(i).text() == label:
                rows.item(i).setCheckState(QtCore.Qt.Checked if on else QtCore.Qt.Unchecked)
                pump(0.3)
                return
        raise AssertionError(f"no tick {label}: {self.ticks()}")

    def choose(self, text):
        combo = self.combo()
        self.assertIsNotNone(combo, "no Result box")
        index = [combo.itemText(i) for i in range(combo.count())].index(text)
        combo.setCurrentIndex(index)
        pump(0.3)
        self.assertTrue(waitFor(lambda: self.combo() is not None and self.combo().currentText() == text))

    def close(self, ok):
        which = QtWidgets.QDialogButtonBox.Ok if ok else QtWidgets.QDialogButtonBox.Cancel
        taskButton(which).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.2)

    def setLength(self, value):
        """The extrude's length typed in its field."""
        field = self.visible(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(field, "no length field")
        field.setProperty("rawValue", float(value))
        pump(0.3)

    def madeParts(self, owner):
        return [b for b in self.doc.Objects if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner]

    def note(self):
        label = self.visible(QtWidgets.QLabel, "studioScopeNote")
        return label.text() if label is not None else ""

    def waitForResult(self, text):
        self.assertTrue(
            waitFor(lambda: self.combo() is not None and self.combo().currentText() == text),
            f"the Result box shows {self.combo().currentText() if self.combo() else None}, not {text}",
        )
        pump(0.2)


class TestStudioFeatureGui(StudioDialog, unittest.TestCase):
    def setUp(self):
        self.openStudio(*newStudio("StudioFeatureGui"))

    def assertOwner(self, owner, scope):
        bodies = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]
        self.assertFalse([b.Name for b in bodies if owner in b.Group], "the owner is in a Body")
        self.assertIn(owner, self.studio.Group)
        self.assertIn(owner.Name, self.entries())
        self.assertEqual(PartDesign.studioScopeIds(owner), scope)
        for p in ("A", "B", "C"):
            step = PartDesign.studioStepOf(owner, self.body(p))
            self.assertEqual(step is not None, p in scope, p)

    # -------------------------------------------------------------------------------- tests
    def testPadMakesAnOwnerInItsSketchsPart(self):
        """Extrude on a sketch of A, with B active: an owner in the studio (no Body's member),
        listed, scope its sketch's part A, a step in A only. The dialog opens on it with the
        Result box: Add, a tick for each part (A ticked). OK: A 1000 + 6*6*10; one undo step;
        undo takes the owner and the step, redo brings them back."""
        s = self.sketchInA("Sk", OVER_A)
        undo = self.doc.UndoCount
        before = self.objects()
        owner = self.runCommand("PartDesign_Pad", s, active="B")
        self.assertEqual(owner.TypeId, "PartDesign::Pad")
        self.assertOwner(owner, ["A"])
        self.assertEqual([self.combo().itemText(i) for i in range(self.combo().count())], ROWS)
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertEqual(self.ticks(), [("A", True), ("B", False), ("C", False)])
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=1000 + 360, B=1000, C=1000)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.objects(), before)
        self.assertVolumes(A=1000, B=1000)
        self.doc.redo()
        self.doc.recompute()
        owner = self.doc.getObject(owner.Name)
        self.assertOwner(owner, ["A"])
        self.assertVolumes(A=1360, B=1000)

    def testRemoveLeavesOutItsOwnPart(self):
        """Report 21: Extrude (remove) 3 deep on a sketch of A over A and B. Its tool going the
        Extrude's way touches A and B, so it opens with no part ticked (Onshape oracle 6, Q1d);
        B ticked. OK: A untouched (1000), B 1000 - 5*6*3 = 910; no step in A."""
        s = self.sketchInA("Sk", CUT)
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.setLength(3)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertEqual(self.ticks(), [("A", False), ("B", False), ("C", False)])
        self.tick("B", True)
        self.tick("A", False)
        self.assertEqual(self.ticks(), [("A", False), ("B", True), ("C", False)])
        self.close(ok=True)
        self.assertOwner(owner, ["B"])
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=1000, B=910, C=1000)

    def testOKOfASplittingPocketMakesTwoParts(self):
        """P6p: a Remove 11 deep through A (x 4..6, y -1..11) splits it: the dialog's OK is the
        command that makes the two pieces parts (400 each) in the Parts list in place of A; one
        undo takes them away again."""
        s = self.sketchInA("Sk", (4, -1, 6, 11))
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.setLength(11)
        self.choose("Remove")
        for label, on in (("A", True), ("B", False), ("C", False)):
            self.tick(label, on)
        self.close(ok=True)
        made = self.madeParts(owner)
        self.assertEqual(len(made), 2)
        for b in made:
            self.assertAlmostEqual(b.Shape.Volume, 400, places=4, msg=b.Name)
            self.assertEqual(b.StudioParentId, "A")
        live = PartDesign.studioLiveParts(self.list)
        self.assertNotIn(self.body("A"), live)
        self.assertEqual(sorted(b.Name for b in live), sorted(["B", "C"] + [b.Name for b in made]))
        names = [b.Name for b in made]
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual([n for n in names if self.doc.getObject(n)], [])
        self.assertIn(self.body("A"), PartDesign.studioLiveParts(self.list))

    def testUnchangedOKMakesAPieceWhereARecordWent(self):
        """P6p: two slots (x 3..3.5 and 6..6.5) through A make three parts; the first slot is
        redrawn at x 8..8.5: the part left of it loses its record (the middle one's witness
        claims the big left solid) and x 8.5..10 is a new piece, so the count of Bodies is the
        same. The unchanged OK of the owner makes it a part all the same, in a step of its own:
        the owner is no longer red (review prline-b5-r1 T3)."""
        from PartDesignTests.TestStudio import rect

        s = self.sketchInA("Sk", (3, -1, 3.5, 11))
        rect(s, 6, -1, 6.5, 11)
        self.doc.recompute()
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.setLength(11)
        self.choose("Remove")
        for label, on in (("A", True), ("B", False), ("C", False)):
            self.tick(label, on)
        self.close(ok=True)
        self.assertEqual(len(self.madeParts(owner)), 3)
        self.doc.openTransaction("redraw")
        for i in (3, 2, 1, 0):
            s.delGeometry(i)
        rect(s, 8, -1, 8.5, 11)
        self.doc.commitTransaction()
        self.doc.recompute()
        step = PartDesign.studioStepOf(owner, self.body("A"))
        self.assertFalse(step.isValid())
        self.assertIn("2 are parts", step.getStatusString())
        bodies = len([o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"])
        undo = self.doc.UndoCount
        owner.ViewObject.doubleClicked()
        self.waitForPanel()
        self.close(ok=True)
        self.doc.recompute()
        self.assertEqual(len([o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]), bodies)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertTrue(step.isValid(), step.getStatusString())
        made = sorted(self.madeParts(owner), key=lambda b: b.Shape.BoundBox.XMin)
        self.assertEqual(len(made), 3)
        for b, (x0, x1) in zip(made, ((0, 6), (6.5, 8), (8.5, 10))):
            self.assertAlmostEqual(b.Shape.BoundBox.XMin, x0, places=6, msg=b.Name)
            self.assertAlmostEqual(b.Shape.Volume, (x1 - x0) * 100, places=4, msg=b.Name)

    def testBothPartsTicked(self):
        """The same cut with A and B ticked: each loses 5*6*3 (910 each)."""
        s = self.sketchInA("Sk", CUT)
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.setLength(3)
        self.tick("A", True)
        self.tick("B", True)
        self.close(ok=True)
        self.assertOwner(owner, ["A", "B"])
        self.assertVolumes(A=910, B=910, C=1000)

    def mergeAllBox(self):
        return self.visible(QtWidgets.QCheckBox, "studioMergeAll")

    def enabledRows(self):
        rows = self.scopeList()
        return [bool(rows.item(i).flags() & QtCore.Qt.ItemIsEnabled) for i in range(rows.count())]

    def testTickedRowsAreNumberedInScopeOrder(self):
        """10.13 (Onshape O9b): an Add over A and B (x 5..25 on their tops, 10 high). With two or
        more ticked, each ticked row shows its place in the scope's order (tick order); one tick
        keeps its plain name; unticking renumbers. B ticked first, then A: B survives; untick B
        and tick it again: A first. OK: B merged into A (2000 + 20*6*10), B no part, C untouched."""
        s = self.sketchInA("Sk", CUT)
        owner = self.runCommand("PartDesign_Pad", s, active=None)
        self.assertEqual(self.combo().currentText(), "New")  # Q1: two parts touched
        self.choose("Add")
        self.assertEqual(self.ticks(), [("A", False), ("B", False), ("C", False)])
        self.tick("B", True)
        self.assertEqual(self.ticks(), [("A", False), ("B", True), ("C", False)])
        self.tick("A", True)
        self.assertEqual(self.ticks(), [("2 A", True), ("1 B", True), ("C", False)])
        self.tick("1 B", False)
        self.assertEqual(self.ticks(), [("A", True), ("B", False), ("C", False)])
        self.tick("B", True)
        self.assertEqual(self.ticks(), [("1 A", True), ("2 B", True), ("C", False)])
        self.tick("C", True)
        self.assertEqual(self.ticks(), [("1 A", True), ("2 B", True), ("3 C", True)])
        self.tick("3 C", False)
        self.assertFalse(self.mergeAllBox().isChecked())
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), ["A", "B"])
        self.assertEqual(list(owner.StudioMergedParts), ["B -> A"])
        self.assertVolumes(A=2000 + 1200, C=1000)
        live = [b.Name for b in PartDesign.studioLiveParts(self.list)]
        self.assertEqual(live, ["A", "C"])
        self.assertIsNone(PartDesign.studioStepOf(owner, self.body("B")))

    def testMergeWithAll(self):
        """10.13 (Onshape Q1b, M3): Merge with all, off by default, makes the scope every live
        part, numbered by each part's first feature in the history (A, B, C), the ticks greyed.
        OK: the Add over A and B makes them one (A survives), C untouched. Off again (edit), the
        ticks are the feature's own again: none, "No merge scope selected"."""
        s = self.sketchInA("Sk", CUT)
        owner = self.runCommand("PartDesign_Pad", s, active=None)
        self.choose("Add")
        box = self.mergeAllBox()
        self.assertIsNotNone(box, "no Merge with all")
        self.assertFalse(box.isChecked())
        self.assertEqual(self.enabledRows(), [True, True, True])
        box.setChecked(True)
        pump(0.3)
        self.assertTrue(owner.StudioMergeAll)
        self.assertEqual(self.ticks(), [("1 A", True), ("2 B", True), ("3 C", True)])
        self.assertEqual(self.enabledRows(), [False, False, False])
        self.assertEqual(self.note(), "")
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(list(owner.StudioMergedParts), ["B -> A"])
        self.assertVolumes(A=2000 + 1200, C=1000)
        self.assertEqual([b.Name for b in PartDesign.studioLiveParts(self.list)], ["A", "C"])
        # Off: the feature's own (empty) scope again
        self.doc.openTransaction("off")
        PartDesign.studioSetMergeAll(owner, False)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertFalse(owner.isValid())
        self.assertIn("No merge scope selected", owner.getStatusString())
        self.assertEqual([b.Name for b in PartDesign.studioLiveParts(self.list)], ["A", "B", "C"])
        self.assertVolumes(A=1000, B=1000, C=1000)

    def testOneTargetThatIsNotTheSketchsPart(self):
        """The team's case (10.11): an Add on a sketch of A, over B, into B alone. B 1000 +
        6*6*10, A untouched."""
        s = self.sketchInA("Sk", OVER_B)
        owner = self.runCommand("PartDesign_Pad", s, active=None)
        self.tick("B", True)
        self.tick("A", False)
        self.close(ok=True)
        self.assertOwner(owner, ["B"])
        self.assertVolumes(A=1000, B=1360, C=1000)

    def testNewMakesAPart(self):
        """New: a part made by the owner (id '<owner>:1', in the studio), 6*6*10, nothing else
        changed; no ticks while New. Switched back to Add, the made part goes."""
        s = self.sketchInA("Sk", OVER_B)
        owner = self.runCommand("PartDesign_Pad", s)
        self.choose("New")
        self.assertIsNone(self.scopeList(), "ticks with New")
        made = [b for b in self.studio.Group if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner]
        self.assertEqual(len(made), 1)
        self.assertEqual(PartDesign.studioScopeIds(owner), [owner.Name + ":1"])
        self.choose("Add")
        pump(0.2)
        self.assertEqual(
            [b for b in self.doc.Objects if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner], []
        )
        self.choose("New")
        self.close(ok=True)
        [made] = [b for b in self.studio.Group if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner]
        self.assertEqual(PartDesign.studioScopeIds(owner), [made.StudioPartId])
        self.assertAlmostEqual(made.Shape.Volume, 360, places=4)
        self.assertVolumes(A=1000, B=1000, C=1000)

    def studioSketch(self, name, rect):
        """A sketch in the studio, outside every Body, at z = 10."""
        from PartDesignTests.TestStudioOwner import studioSketch

        s = studioSketch(self.doc, self.studio, name, rects=[rect], z=10)
        self.doc.recompute()
        return s

    def testDefaultScopesFollowTheTool(self):
        """The pre-fill is what the tool meets (Onshape oracle 6, Q1), never the active Body: a
        sketch outside every Body over A on A's top opens Add with A ticked, B active or not; over
        no part it opens New (a part made by it). Extrude (remove) over no part opens Remove with
        no part ticked and says "No merge scope selected"; over A, with B active, it opens on A."""
        s = self.studioSketch("Free", OVER_A)
        owner = self.runCommand("PartDesign_Pad", s, active="B")
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertEqual(self.ticks(), [("A", True), ("B", False), ("C", False)])
        self.close(ok=False)

        away = self.studioSketch("Away", (60, 2, 66, 8))
        owner = self.runCommand("PartDesign_Pad", away, active=None)
        self.assertEqual(self.combo().currentText(), "New")
        self.assertIsNone(self.scopeList())
        self.close(ok=True)
        [made] = self.madeParts(owner)
        self.assertAlmostEqual(made.Shape.Volume, 360, places=4)
        self.assertVolumes(A=1000)

        # Not over the part just made (its tool going up would meet it)
        away2 = self.studioSketch("Away2", (80, 2, 86, 8))
        pocket = self.runCommand("PartDesign_Pocket", away2, active="B")
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertEqual([t for t in self.ticks() if t[1]], [])
        self.assertEqual(self.note(), "No merge scope selected")
        self.close(ok=False)

        pocket = self.runCommand("PartDesign_Pocket", s, active="B")
        self.assertEqual(PartDesign.studioScopeIds(pocket), ["A"])
        self.assertIsNone(self.visible(QtWidgets.QLabel, "studioScopeNote"))
        self.close(ok=False)

    def testIntersect(self):
        """Intersect on A with a 6 x 6 tool 10 high from A's top down: A keeps 6*6*10."""
        s = self.sketchInA("Sk", OVER_A)
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.setLength(10)
        self.choose("Intersect")
        self.close(ok=True)
        self.assertEqual(owner.Operation, "Common")
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=360, B=1000)

    def testCancelLeavesNothing(self):
        """Cancel of a new owner: no object, no list entry, no undo step, the parts as before."""
        s = self.sketchInA("Sk", CUT)
        undo = self.doc.UndoCount
        before, entries = self.objects(), self.entries()
        self.runCommand("PartDesign_Pocket", s)
        self.tick("B", True)
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(self.objects(), before)
        self.assertEqual(self.entries(), entries)
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertVolumes(A=1000, B=1000, C=1000)

    def testEditAgain(self):
        """A Remove into B alone, edited again (the row's double-click): the dialog shows Remove
        with B ticked and A cleared; a tick on C and OK cut C too (one more undo step), and
        Cancel of a second edit changes nothing."""
        s = self.sketchInA("Sk", (5, 2, 45, 8))
        owner = self.runCommand("PartDesign_Pocket", s)
        self.setLength(3)
        self.tick("B", True)
        self.tick("A", False)
        self.close(ok=True)
        self.assertVolumes(A=1000, B=1000 - 10 * 6 * 3, C=1000)
        undo = self.doc.UndoCount
        owner.ViewObject.doubleClicked()
        self.waitForPanel()
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertEqual(self.ticks(), [("A", False), ("B", True), ("C", False)])
        self.tick("C", True)
        self.close(ok=True)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertOwner(owner, ["B", "C"])
        self.assertVolumes(A=1000, B=820, C=1000 - 5 * 6 * 3)
        owner.ViewObject.doubleClicked()
        self.waitForPanel()
        self.tick("A", True)
        self.close(ok=False)
        self.doc.recompute()
        self.assertOwner(owner, ["B", "C"])
        self.assertVolumes(A=1000, B=820, C=910)
        self.assertEqual(self.doc.UndoCount, undo + 1)

    def testEditAgainFromTheFeaturesList(self):
        """The owner has one row in the Features list (its step none); a double-click on it opens
        its dialog with its Result and ticks."""
        from PartDesignTests import TestFeaturesViewGui as fv

        param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        savedTree = param.GetBool("ShowModelTree", False)
        if savedTree:
            Gui.runCommand("PartDesign_ToggleModelTree")
        try:
            model = Gui.getMainWindow().findChild(QtWidgets.QDockWidget, "Model")
            if model is not None:
                model.show()
            s = self.sketchInA("Sk", CUT)
            owner = self.runCommand("PartDesign_Pocket", s, active="A")
            self.setLength(3)
            self.tick("B", True)
            self.tick("A", False)
            self.close(ok=True)
            view = lambda: Gui.getMainWindow().findChild(QtWidgets.QWidget, "FeaturesView")
            self.assertTrue(waitFor(lambda: view() is not None and view().isVisible()))
            rows = view().findChild(QtWidgets.QListWidget, "featureList")

            def row():
                found = [
                    rows.item(i)
                    for i in range(rows.count())
                    if rows.item(i).type() != fv.BAR and rows.item(i).text() == owner.Label
                ]
                return found

            self.assertTrue(waitFor(lambda: len(row()) == 1), [rows.item(i).text() for i in range(rows.count())])
            step = PartDesign.studioStepOf(owner, self.body("B"))
            self.assertFalse(
                [rows.item(i) for i in range(rows.count()) if rows.item(i).text() == step.Label],
                "the step has a row",
            )
            rows.itemDoubleClicked.emit(row()[0])
            self.waitForPanel()
            self.assertEqual(self.combo().currentText(), "Remove")
            self.assertEqual(self.ticks(), [("A", False), ("B", True), ("C", False)])
            self.close(ok=False)
            self.assertVolumes(A=1000, B=910)
        finally:
            if param.GetBool("ShowModelTree", False) != savedTree:
                Gui.runCommand("PartDesign_ToggleModelTree")

    def testTheDialogRollsThePartsBack(self):
        """While an owner's dialog is open every part is rolled back to the owner's place: A
        holds the owner's step (its bar after APad); a part ticked in the dialog holds its new
        step too. Cancel: nothing held, A as before."""
        s = self.sketchInA("Sk", OVER_A)
        owner = self.runCommand("PartDesign_Pad", s)
        self.close(ok=True)
        self.assertVolumes(A=1360)
        owner.ViewObject.doubleClicked()
        self.waitForPanel()
        step = PartDesign.studioStepOf(owner, self.body("A"))
        self.assertIsNotNone(step)
        self.assertTrue(self.body("A").holds(step), "A isn't rolled back to the owner")
        self.assertFalse(self.body("A").holds(self.doc.getObject("APad")))
        self.tick("B", True)
        stepB = PartDesign.studioStepOf(owner, self.body("B"))
        self.assertIsNotNone(stepB)
        self.assertTrue(self.body("B").holds(stepB), "B's new step isn't held")
        self.close(ok=False)
        self.doc.recompute()
        self.assertFalse(self.body("A").holds(step))
        self.assertIsNone(PartDesign.studioStepOf(owner, self.body("B")))
        self.assertVolumes(A=1360, B=1000)

    def testUpToFaceOfAnotherPart(self):
        """Extrude (remove) on a sketch of A over A, Up to face, the face picked on another part
        (D's top, z = 4): the pick is taken (UpToFace links D's Pad), and A loses 6*6*6."""
        dpad = self.partD()
        top = faceAt(dpad, 4)
        self.assertIsNotNone(top)
        s = self.sketchInA("Sk", OVER_A)
        owner = self.runCommand("PartDesign_Pocket", s)
        mode = self.visible(QtWidgets.QComboBox, "changeMode")
        self.assertIsNotNone(mode)
        index = mode.findText("Up to face")
        self.assertGreaterEqual(index, 0, [mode.itemText(i) for i in range(mode.count())])
        mode.setCurrentIndex(index)
        pump(0.3)
        field = Gui.getMainWindow().findChild(QtWidgets.QWidget, "fieldUpToFace")
        self.assertIsNotNone(field)
        self.assertTrue(waitFor(lambda: field.isVisible() and bool(field.property("armed"))))
        Gui.Selection.addSelection(self.doc.Name, dpad.Name, top)
        pump(0.5)
        self.assertIsNotNone(owner.UpToFace, "the pick of D's face was refused")
        self.assertEqual(owner.UpToFace[0].Name, dpad.Name)
        self.close(ok=True)
        self.assertEqual(owner.Type, "UpToFace")
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=1000 - 6 * 6 * 6, B=1000, D=400)

    def upToFaceField(self):
        mode = self.visible(QtWidgets.QComboBox, "changeMode")
        self.assertIsNotNone(mode)
        index = mode.findText("Up to face")
        self.assertGreaterEqual(index, 0, [mode.itemText(i) for i in range(mode.count())])
        mode.setCurrentIndex(index)
        pump(0.3)
        field = Gui.getMainWindow().findChild(QtWidgets.QWidget, "fieldUpToFace")
        self.assertIsNotNone(field)
        self.assertTrue(waitFor(lambda: field.isVisible() and bool(field.property("armed"))))
        return field

    def testUpToAStudioPlaneOrAPartsDatum(self):
        """Up to face takes the studio's own XY plane (the pick is taken: UpToFace links it) and
        then a datum plane of part B at z = 5, which replaces it: A loses 6*6*5."""
        b = self.body("B")
        datum = b.newObject("PartDesign::Plane", "DP")
        datum.AttachmentSupport = [(b.Origin.OriginFeatures[3], "")]
        datum.MapMode = "FlatFace"
        datum.AttachmentOffset = App.Placement(App.Vector(0, 0, 5), App.Rotation())
        self.doc.recompute()
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        xy = [f for f in self.studio.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
        s = self.sketchInA("Sk", OVER_A)
        owner = self.runCommand("PartDesign_Pocket", s)
        self.upToFaceField()
        Gui.Selection.addSelection(self.doc.Name, xy.Name)
        pump(0.5)
        self.assertIsNotNone(owner.UpToFace, "the pick of the studio's XY plane was refused")
        # The plane whole, or through its coordinate system (the face field's way)
        linked, subs = owner.UpToFace
        self.assertTrue(
            linked == xy or (linked == self.studio.Origin and xy.Name in subs), (linked.Name, subs)
        )
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, datum.Name)
        pump(0.5)
        self.assertEqual(owner.UpToFace[0].Name, datum.Name, "the pick of B's datum was refused")
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=1000 - 6 * 6 * 5, B=1000)

# ------------------------------------------------------------- the list on first use (decision 337)


class TestListOnFirstUseGui(StudioDialog, unittest.TestCase):
    """ops#654, the list on first use (notes/parts-design.md 10.8): the studio's list is the only
    truth, so in a studio without one the first studio command makes it, adopted from the derived
    order, in the command's own step (Cancel or one undo takes it back with the feature), and then
    takes the owner path. A studio whose adoption could change what the person sees without a word
    is refused loudly (studioListRefusal in Gui/Command.cpp): rolled back, or an in-Body Boolean
    using one of its parts as a tool."""

    def setUp(self):
        self.doc = None

    def tearDown(self):
        if self.doc is not None:
            super().tearDown()

    def openUnlisted(self, doc, studio):
        self.doc, self.studio, self.list = doc, studio, None
        self.doc.recompute()
        self.assertIsNone(PartDesign.studioList(self.studioArg()))
        Gui.Selection.clearSelection()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)

    def studioArg(self):
        return self.studio if self.studio is not None else self.doc

    def listed(self):
        self.list = PartDesign.studioList(self.studioArg())
        return self.list

    def fresh(self):
        """A fresh document: a Body A at its top level holding only a sketch (6 x 6 at z 0)."""
        doc = App.newDocument("ListOnFirstUseFresh")
        doc.UndoMode = 1
        body = doc.addObject("PartDesign::Body", "A")
        s = sketch(body, "Sk", xyPlane(body), OVER_A)
        self.openUnlisted(doc, None)
        return s

    def solidVolume(self):
        bodies = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]
        return sum(b.Shape.Volume for b in bodies if not b.Shape.isNull())

    def refused(self, command, profile, active, words):
        """command with profile selected and Body active is refused: no dialog, no list, nothing
        made, no undo step, and the status bar says why (words in it)."""
        before, undo = self.objects(), self.doc.UndoCount
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body(active))
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, profile.Name)
        Gui.runCommand(command)
        pump(0.5)
        self.assertFalse(Gui.Control.activeDialog(), "a dialog opened")
        self.assertIsNone(self.listed())
        self.assertEqual(self.objects(), before)
        self.assertEqual(self.doc.UndoCount, undo)
        # MainWindow::showMessage writes the status bar's action label
        bar = Gui.getMainWindow().statusBar()
        message = " | ".join(label.text() for label in bar.findChildren(QtWidgets.QLabel))
        self.assertIn(words, message)

    # -------------------------------------------------------------------------------- tests
    def testFirstPadOfAFreshDocumentMakesTheListAndAnOwner(self):
        """A fresh document's first Extrude: the list (of the document's top level) is made with
        the owner, the sketch adopted before it; the owner is no Body's member; OK makes the 6 x 6
        x 10 solid; one undo takes the owner, its part and the list, redo brings them back."""
        s = self.fresh()
        undo, before = self.doc.UndoCount, self.objects()
        owner = self.runCommand("PartDesign_Pad", s, active="A")
        self.assertIsNotNone(self.listed(), "no list made")
        self.assertEqual(self.entries(), ["Sk", owner.Name])
        bodies = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]
        self.assertFalse([b.Name for b in bodies if owner in b.Group], "the owner is in a Body")
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertAlmostEqual(self.solidVolume(), 360, places=4)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.listed())
        self.assertEqual(self.objects(), before)
        self.doc.redo()
        self.doc.recompute()
        self.assertIsNotNone(self.listed())
        self.assertEqual(self.entries(), ["Sk", owner.Name])
        self.assertAlmostEqual(self.solidVolume(), 360, places=4)

    def testCancelOfTheFirstPadLeavesNothing(self):
        """Cancel of a fresh document's first Extrude: no owner, no part, no list, no undo step."""
        s = self.fresh()
        undo, before = self.doc.UndoCount, self.objects()
        self.runCommand("PartDesign_Pad", s, active="A")
        self.assertIsNotNone(self.listed())
        self.close(ok=False)
        self.doc.recompute()
        self.assertIsNone(self.listed())
        self.assertEqual(self.objects(), before)
        self.assertEqual(self.doc.UndoCount, undo)

    def testFirstPocketAdoptsTheInBodyFeaturesInOrder(self):
        """A studio of in-Body features (A, B, C: sketch and Pad each, made without a list) and a
        sketch on A: the first Extrude (remove) adopts them in the derived order and puts its
        owner at the bar (the end); a Remove 3 deep into A cuts 6*6*3; one undo leaves the studio
        as it was, without a list."""
        self.openUnlisted(*newStudio("ListOnFirstUse"))
        s = self.sketchInA("Sk", OVER_A)
        order = [o.Name for o in PartDesign.studioSequence(self.studio)]
        self.assertEqual(order, ["ASk", "APad", "BSk", "BPad", "CSk", "CPad", "Sk"])
        undo, before = self.doc.UndoCount, self.objects()
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.assertIsNotNone(self.listed(), "no list made")
        self.assertEqual(self.entries(), order + [owner.Name])
        self.assertEqual(self.list.Bar, -1)
        self.setLength(3)
        self.choose("Remove")
        for label, on in (("A", True), ("B", False), ("C", False)):
            self.tick(label, on)
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), ["A"])
        self.assertVolumes(A=1000 - 6 * 6 * 3, B=1000, C=1000)
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.listed())
        self.assertEqual(self.objects(), before)
        self.assertVolumes(A=1000, B=1000, C=1000)

    def testFirstPadAddsIntoItsSketchsPart(self):
        """The first Extrude on a sketch of A with A active (the case that made an in-Body Pad
        before the list on first use): an owner adding into A, 1000 + 6*6*10."""
        self.openUnlisted(*newStudio("ListOnFirstUsePad"))
        s = self.sketchInA("Sk", OVER_A)
        owner = self.runCommand("PartDesign_Pad", s, active="A")
        self.assertIsNotNone(self.listed())
        self.assertEqual(self.combo().currentText(), "Add")
        self.close(ok=True)
        self.assertOwner(owner, ["A"])
        self.assertVolumes(A=1360, B=1000, C=1000)
        self.assertFalse([o.Name for o in self.body("A").Group if o.TypeId == "PartDesign::Pad"
                          and o.Name != "APad"], "an in-Body Pad")

    def assertOwner(self, owner, scope):
        TestStudioFeatureGui.assertOwner(self, owner, scope)

    def testARolledBackStudioIsRefusedLoudly(self):
        """A studio rolled back without a list (A's Tip moved back to its sketch): the derived bar
        could hold B's or C's rows below it, so the first studio command is refused with the
        reason, and nothing changes."""
        self.openUnlisted(*newStudio("ListOnFirstUseRolled"))
        a, b = self.body("A"), self.body("B")
        a.Tip = self.doc.getObject("ASk")
        s = sketch(b, "Sk", xyPlane(b), OVER_B, z=10)
        self.doc.recompute()
        self.assertTrue(a.isRolledBack())
        self.refused("PartDesign_Pad", s, "B", "rolled back")

    def testAnInBodyBooleanOfAStudioPartIsRefusedLoudly(self):
        """An in-Body Boolean in A whose tool is the part B: the list would see B as a live part,
        so the first studio command is refused with the reason, and nothing changes."""
        self.openUnlisted(*newStudio("ListOnFirstUseBoolean"))
        a, b, c = self.body("A"), self.body("B"), self.body("C")
        boolean = a.newObject("PartDesign::Boolean", "Bool")
        boolean.addObjects([b])
        s = sketch(c, "Sk", xyPlane(c), (42, 2, 48, 8), z=10)
        self.doc.recompute()
        self.assertEqual(PartDesign.studioOf(b), self.studio, "B left the studio")
        self.refused("PartDesign_Pad", s, "C", "Bool")


# ------------------------------------------------------------------ Onshape's pre-fill (oracle 6)

QA = 20 * 20 * 10  # each box's volume


def twoBoxStudio(name):
    """Oracle 6's parts: A = box x 0..20, B = box x 30..50, both y 0..20, z 0..10, in studio S."""
    doc = App.newDocument(name)
    doc.UndoMode = 1
    studio = doc.addObject("App::Part", "S")
    for p, x in (("A", 0), ("B", 30)):
        body = doc.addObject("PartDesign::Body", p)
        studio.addObject(body)
        pad(body, p + "Pad", sketch(body, p + "Sk", xyPlane(body), (x, 0, x + 20, 20)), 10)
    doc.recompute()
    return doc, studio


class TestExtrudePrefillGui(StudioDialog, unittest.TestCase):
    """Onshape's Extrude dialog picks its operation from what the tool meets (batch 6, Hub 3 Q1):
    exactly one part touched or intersected -> Add, scope that part; none or two -> New; picked
    again on every depth change until the person chooses. A hand switch from New fills no scope;
    Add -> Remove keeps it; Remove flips the direction. Extrude (remove) is the Extrude switched
    to Remove."""

    def setUp(self):
        self.openStudio(*twoBoxStudio("ExtrudePrefillGui"))

    def onBTop(self, name, rect):
        """A sketch in B on its top face plane (z = 10)."""
        s = sketch(self.body("B"), name, xyPlane(self.body("B")), rect, z=10)
        self.doc.recompute()
        return s

    def studioSketch(self, name, rect, z):
        from PartDesignTests.TestStudioOwner import studioSketch

        s = studioSketch(self.doc, self.studio, name, rects=[rect], z=z)
        self.doc.recompute()
        return s

    def testQ1aToolOnBsTopFace(self):
        """Q1a: on B's top face, x 35..45 y 5..15: Add, scope B (face contact counts). Blind 5:
        B 4500, still two parts."""
        owner = self.runCommand("PartDesign_Pad", self.onBTop("Sk", (35, 5, 45, 15)), active=None)
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertEqual(self.ticks(), [("A", False), ("B", True)])
        self.setLength(5)
        self.waitForResult("Add")
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), ["B"])
        self.assertEqual(self.madeParts(owner), [])
        self.assertVolumes(A=QA, B=QA + 10 * 10 * 5)

    def testQ1bToolOverBothIsNewAndAddFillsNoScope(self):
        """Q1b: on B's top plane, x 10..40, over both outlines (touching A's and B's top faces):
        New. A switch to Add leaves the scope empty: no part ticked, "No merge scope selected",
        the made part gone; OK commits it failed (Onshape: BOOLEAN_NEED_ONE_SOLID), nothing
        changes."""
        owner = self.runCommand("PartDesign_Pad", self.onBTop("Sk", (10, 5, 40, 15)), active=None)
        self.assertEqual(self.combo().currentText(), "New")
        self.assertEqual(len(self.madeParts(owner)), 1)
        self.choose("Add")
        self.assertEqual(self.ticks(), [("A", False), ("B", False)])
        self.assertEqual(self.note(), "No merge scope selected")
        self.assertEqual(self.madeParts(owner), [])
        self.assertEqual(PartDesign.studioScopeIds(owner), [])
        self.close(ok=True)
        self.assertFalse(owner.isValid())
        self.assertIn("No merge scope selected", owner.getStatusString())
        self.assertVolumes(A=QA, B=QA)

    def testQ1cToolThroughB(self):
        """Q1c: on the studio's Top plane, x 35..45, blind 15 through B: Add, scope B. B 4500."""
        owner = self.runCommand("PartDesign_Pad", self.studioSketch("Sk", (35, 5, 45, 15), 0), active=None)
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertEqual(self.ticks(), [("A", False), ("B", True)])
        self.setLength(15)
        self.waitForResult("Add")
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=QA, B=QA + 10 * 10 * 5)

    def testQ1dRemoveOverBothHasNoScope(self):
        """Q1d: Extrude (remove) on Top, x 10..40: going the Extrude's way (up) its tool meets
        both parts, so New, switched to Remove: no part ticked, "No merge scope selected", the
        direction down (the Pocket's own, into the material; misses both). Through both with
        Reversed still no scope: OK commits it failed, nothing changes."""
        owner = self.runCommand("PartDesign_Pocket", self.studioSketch("Sk", (10, 5, 40, 15), 0), active=None)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertEqual(self.ticks(), [("A", False), ("B", False)])
        self.assertEqual(self.note(), "No merge scope selected")
        self.assertFalse(owner.Reversed)
        self.assertEqual(self.madeParts(owner), [])
        self.setLength(15)
        self.close(ok=True)
        self.assertFalse(owner.isValid())
        self.assertIn("No merge scope selected", owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), [])
        self.assertVolumes(A=QA, B=QA)

    def testQ1eRemoveOnBsTopFaceKeepsB(self):
        """Q1e: Extrude (remove) on B's top face, x 35..45: the Extrude's tool meets B only, so
        Add/B switched to Remove keeps B and cuts into it. Blind 5: B 3500."""
        owner = self.runCommand("PartDesign_Pocket", self.onBTop("Sk", (35, 5, 45, 15)), active=None)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertEqual(self.ticks(), [("A", False), ("B", True)])
        self.setLength(5)
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=QA, B=QA - 10 * 10 * 5)

    def testQ1eAddSwitchedToRemoveKeepsTheScopeAndFlips(self):
        """Q1e by hand: an Extrude on B's top face opens Add/B; Remove keeps B and flips the
        direction into B (the panel's Reversed switch shows it). Blind 5: B 3500."""
        owner = self.runCommand("PartDesign_Pad", self.onBTop("Sk", (35, 5, 45, 15)), active=None)
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertFalse(owner.Reversed)
        self.choose("Remove")
        self.assertEqual(self.ticks(), [("A", False), ("B", True)])
        self.assertTrue(owner.Reversed)
        reversedBox = self.visible(QtWidgets.QCheckBox, "checkBoxReversed")
        self.assertIsNotNone(reversedBox)
        self.assertTrue(reversedBox.isChecked(), "the panel's Reversed switch isn't the owner's")
        self.setLength(5)
        self.close(ok=True)
        self.assertTrue(owner.Reversed)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(owner.Operation, "Subtraction")
        self.assertVolumes(A=QA, B=QA - 10 * 10 * 5)

    def testQ1fPickedAgainOnEveryDepthChange(self):
        """Q1f: a plane 5 mm below Top, x 35..45: the default 10 passes through B -> Add/B; 2 mm
        misses B -> New (a part made); 15 mm -> Add/B again (the made part gone). OK: B 4500
        (z -5..10), no made part."""
        owner = self.runCommand("PartDesign_Pad", self.studioSketch("Sk", (35, 5, 45, 15), -5), active=None)
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertEqual(self.ticks(), [("A", False), ("B", True)])
        self.setLength(2)
        self.waitForResult("New")
        self.assertEqual(len(self.madeParts(owner)), 1)
        self.setLength(15)
        self.waitForResult("Add")
        self.assertEqual(self.ticks(), [("A", False), ("B", True)])
        self.assertEqual(self.madeParts(owner), [])
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(self.madeParts(owner), [])
        self.assertVolumes(A=QA, B=QA + 10 * 10 * 5)

    def testAHandChosenOperationSurvivesADepthChange(self):
        """Q1f's sketch, New chosen by hand at depth 10 (where the pick is Add/B): 15 mm, which
        passes through B, keeps New. OK: a new part of 10*10*15, B untouched."""
        owner = self.runCommand("PartDesign_Pad", self.studioSketch("Sk", (35, 5, 45, 15), -5), active=None)
        self.assertEqual(self.combo().currentText(), "Add")
        self.choose("New")
        self.setLength(15)
        pump(0.5)
        self.waitForResult("New")
        self.close(ok=True)
        [made] = self.madeParts(owner)
        self.assertAlmostEqual(made.Shape.Volume, 10 * 10 * 15, places=4)
        self.assertVolumes(A=QA, B=QA)

    def testAHandTickStopsThePick(self):
        """Q1f's sketch, A ticked by hand at depth 10 (scope A and B): 2 mm keeps Add with both
        ticked, no part made."""
        owner = self.runCommand("PartDesign_Pad", self.studioSketch("Sk", (35, 5, 45, 15), -5), active=None)
        self.tick("A", True)
        self.setLength(2)
        pump(0.5)
        self.waitForResult("Add")
        # Two ticked: numbered in scope order (10.13), B (the pick's) first, A ticked after it
        self.assertEqual(self.ticks(), [("2 A", True), ("1 B", True)])
        self.assertEqual(self.madeParts(owner), [])
        self.close(ok=False)

    def testQ1gOverhangDoesNotMatter(self):
        """Q1g: on Top, x 25..35, half over the gap, half over B: Add/B. 15 mm: one B of 5000."""
        owner = self.runCommand("PartDesign_Pad", self.studioSketch("Sk", (25, 5, 35, 15), 0), active=None)
        self.assertEqual(self.combo().currentText(), "Add")
        self.assertEqual(self.ticks(), [("A", False), ("B", True)])
        self.setLength(15)
        self.waitForResult("Add")
        self.close(ok=True)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=QA, B=5000)


class TestLeavingNewGui(StudioDialog, unittest.TestCase):
    """Oracle 6, batch 6 Hub 3 Q2: an Extrude E made New (P = "Part 2"), then a Fillet r1 on P's
    vertical edge at (40, 10). Onshape keeps P when E goes to Add with a scope its tool doesn't
    touch (an info), merges P into A when it does (P's later features follow), and back to New
    brings P back. The fork refuses to leave New while P has later features (debt: the keep and
    the merge with following features are P6p/P5 work), and leaves it as before when P has none:
    P deleted, back to New makes it again with the same id."""

    PV = 10 * 10 * 10

    def setUp(self):
        doc = App.newDocument("LeavingNewGui")
        doc.UndoMode = 1
        studio = doc.addObject("App::Part", "S")
        body = doc.addObject("PartDesign::Body", "A")
        studio.addObject(body)
        pad(body, "APad", sketch(body, "ASk", xyPlane(body), (0, 0, 20, 20)), 10)
        doc.recompute()
        self.openStudio(doc, studio)

    def makeE(self, rect=(30, 0, 40, 10)):
        """E: an Extrude on Top, blind 10, New (over no part, else chosen by hand); returns
        (E, P)."""
        from PartDesignTests.TestStudioOwner import studioSketch

        s = studioSketch(self.doc, self.studio, "ESk", rects=[rect], z=0)
        self.doc.recompute()
        owner = self.runCommand("PartDesign_Pad", s, active=None)
        if self.combo().currentText() != "New":
            self.choose("New")
        self.close(ok=True)
        [made] = self.madeParts(owner)
        self.assertEqual(made.StudioPartId, owner.Name + ":1")
        self.assertAlmostEqual(made.Shape.Volume, (rect[2] - rect[0]) * (rect[3] - rect[1]) * 10, places=4)
        return owner, made

    def filletP(self, owner, made):
        """F: a Fillet r1 on P's vertical edge at (40, 10)."""
        step = PartDesign.studioStepOf(owner, made)
        edge = edgeAt(step, (40, 10, 0), (40, 10, 10))
        self.assertIsNotNone(edge)
        fillet = made.newObject("PartDesign::Fillet", "F")
        fillet.Base = (step, [edge])
        fillet.Radius = 1
        made.Tip = fillet
        self.doc.recompute()
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertAlmostEqual(made.Shape.Volume, self.PV - (1 - math.pi / 4) * 10, places=3)
        return fillet

    def editAgain(self, owner):
        owner.ViewObject.doubleClicked()
        self.waitForPanel()

    def assertRefused(self, owner, made, fillet, choice):
        undo = self.doc.UndoCount
        self.editAgain(owner)
        self.assertEqual(self.combo().currentText(), "New")
        self.choose_refused(choice)
        self.assertIn("has later features", self.note())
        self.assertIn(fillet.Label, self.note())
        self.assertIs(self.doc.getObject(made.Name), made)
        self.assertEqual(PartDesign.studioScopeIds(owner), [made.StudioPartId])
        self.close(ok=True)
        self.assertEqual(made.StudioPartId, owner.Name + ":1")
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertIn(undo, (self.doc.UndoCount, self.doc.UndoCount - 1))

    def choose_refused(self, text):
        combo = self.combo()
        index = [combo.itemText(i) for i in range(combo.count())].index(text)
        combo.setCurrentIndex(index)
        pump(0.3)
        self.waitForResult("New")

    def testQ2aAddWithAScopeItDoesNotTouchIsRefused(self):
        """Q2a: E New -> Add, the tool not touching A. Onshape: E OK with an info, P kept (same id
        and name), F follows. The fork: refused while P has F, said in the panel naming F; P, its
        id and F unchanged (Q2b: back to New then changes nothing either)."""
        owner, made = self.makeE()
        fillet = self.filletP(owner, made)
        self.assertRefused(owner, made, fillet, "Add")
        self.assertAlmostEqual(made.Shape.Volume, self.PV - (1 - math.pi / 4) * 10, places=3)
        self.assertVolumes(A=4000)

    def testQ2cAddOverlappingAIsRefused(self):
        """Q2c: E's rectangle x 15..40 overlapping A, New -> Add (Remove too). Onshape: P merges
        into A (A's id), F follows; back to New brings P back. The fork: refused while P has F."""
        owner, made = self.makeE(rect=(15, 0, 40, 10))
        self.assertAlmostEqual(made.Shape.Volume, 2500, places=4)
        step = PartDesign.studioStepOf(owner, made)
        edge = edgeAt(step, (40, 10, 0), (40, 10, 10))
        fillet = made.newObject("PartDesign::Fillet", "F")
        fillet.Base = (step, [edge])
        fillet.Radius = 1
        made.Tip = fillet
        self.doc.recompute()
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertRefused(owner, made, fillet, "Add")
        self.assertRefused(owner, made, fillet, "Remove")
        self.assertAlmostEqual(made.Shape.Volume, 2500 - (1 - math.pi / 4) * 10, places=3)
        self.assertVolumes(A=4000)

    def testLeavingNewWithoutLaterFeatures(self):
        """P without later features: New -> Add deletes P (scope empty, "No merge scope selected");
        back to New makes it again with the same id; OK. Then Add with A ticked (the tool apart
        from A): Onshape H1a makes the region a new part, and the OK is the command that makes it
        (P6p): a leftover part, its own undo step after the edit's; undo leaves the edit's loud
        failure, a second undo brings P back whole, redo takes it again."""
        owner, made = self.makeE()
        pid = made.StudioPartId
        undo = self.doc.UndoCount
        self.editAgain(owner)
        self.choose("Add")
        self.assertEqual(self.madeParts(owner), [])
        self.assertEqual(self.note(), "No merge scope selected")
        self.choose("New")
        [again] = self.madeParts(owner)
        self.assertEqual(again.StudioPartId, pid)
        self.close(ok=True)
        [again] = self.madeParts(owner)
        self.assertEqual(again.StudioPartId, pid)
        self.assertAlmostEqual(again.Shape.Volume, self.PV, places=4)
        self.assertTrue(owner.isValid(), owner.getStatusString())

        undo = self.doc.UndoCount
        self.editAgain(owner)
        self.choose("Add")
        self.tick("A", True)
        self.close(ok=True)
        self.assertEqual(self.doc.UndoCount, undo + 2)
        [left] = self.madeParts(owner)
        self.assertEqual(left.StudioParentId, "")
        self.assertAlmostEqual(left.Shape.Volume, self.PV, places=4)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=4000)

        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.madeParts(owner), [])
        self.assertFalse(owner.isValid())
        self.assertIn("touches no part", owner.getStatusString())
        self.assertVolumes(A=4000)
        self.doc.undo()
        self.doc.recompute()
        [back] = self.madeParts(owner)
        self.assertEqual(back.StudioPartId, pid)
        self.assertAlmostEqual(back.Shape.Volume, self.PV, places=4)
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertEqual(PartDesign.studioScopeIds(owner), [pid])
        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(self.madeParts(owner), [])
        self.assertFalse(owner.isValid())
        self.assertVolumes(A=4000)


if __name__ == "__main__":
    unittest.main()
