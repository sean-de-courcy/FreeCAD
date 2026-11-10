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

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestStudio import faceAt, pad, sketch, xyPlane
from PartDesignTests.TestStudioList import newStudio

CUT = (5, 2, 25, 8)  # 5 x 6 over A (x 5..10) and 5 x 6 over B (x 20..25)
OVER_A = (2, 2, 8, 8)  # 6 x 6 over A
OVER_B = (22, 2, 28, 8)  # 6 x 6 over B, the sketch still in A
ROWS = ["New", "Add", "Remove", "Intersect"]


class TestStudioFeatureGui(unittest.TestCase):
    def setUp(self):
        self.doc, self.studio = newStudio("StudioFeatureGui")
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
        """Report 21: Extrude (remove) 3 deep on a sketch of A over A and B; B ticked, A
        cleared. OK: A untouched (1000), B 1000 - 5*6*3 = 910; no step in A."""
        s = self.sketchInA("Sk", CUT)
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.setLength(3)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertEqual(self.ticks(), [("A", True), ("B", False), ("C", False)])
        self.tick("B", True)
        self.tick("A", False)
        self.assertEqual(self.ticks(), [("A", False), ("B", True), ("C", False)])
        self.close(ok=True)
        self.assertOwner(owner, ["B"])
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertVolumes(A=1000, B=910, C=1000)

    def testBothPartsTicked(self):
        """The same cut with A and B ticked: each loses 5*6*3 (910 each)."""
        s = self.sketchInA("Sk", CUT)
        owner = self.runCommand("PartDesign_Pocket", s, active="A")
        self.setLength(3)
        self.tick("B", True)
        self.close(ok=True)
        self.assertOwner(owner, ["A", "B"])
        self.assertVolumes(A=910, B=910, C=1000)

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

    def testDefaultScopes(self):
        """A sketch outside every Body: with no Body active Extrude opens New (a part made by it),
        Extrude (remove) opens Remove with no part ticked and says "No merge scope selected"
        (Onshape's); with B active, Extrude (remove) opens on B."""
        s = self.studioSketch("Free", OVER_A)
        owner = self.runCommand("PartDesign_Pad", s, active=None)
        self.assertEqual(self.combo().currentText(), "New")
        self.assertIsNone(self.scopeList())
        self.close(ok=True)
        [made] = [b for b in self.studio.Group if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner]
        self.assertAlmostEqual(made.Shape.Volume, 360, places=4)
        self.assertVolumes(A=1000)

        pocket = self.runCommand("PartDesign_Pocket", s, active=None)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertEqual([t for t in self.ticks() if t[1]], [])
        note = self.visible(QtWidgets.QLabel, "studioScopeNote")
        self.assertIsNotNone(note, "an empty scope isn't said")
        self.assertEqual(note.text(), "No merge scope selected")
        self.close(ok=False)

        pocket = self.runCommand("PartDesign_Pocket", s, active="B")
        self.assertEqual(PartDesign.studioScopeIds(pocket), ["B"])
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

    def testAStudioWithoutAListKeepsTodaysPath(self):
        """No list: Extrude on a sketch of A makes a Pad in A, as before."""
        doc, studio = newStudio("StudioFeatureGuiNoList")
        try:
            App.setActiveDocument(doc.Name)
            Gui.setActiveDocument(doc.Name)
            a = doc.getObject("A")
            s = sketch(a, "Sk", xyPlane(a), OVER_A, z=10)
            doc.recompute()
            Gui.getDocument(doc.Name).ActiveView.setActiveObject("pdbody", a)
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(doc.Name, s.Name)
            Gui.runCommand("PartDesign_Pad")
            self.waitForPanel()
            self.assertIsNone(PartDesign.studioList(studio))
            [made] = [o for o in a.Group if o.TypeId == "PartDesign::Pad" and o.Name != "APad"]
            self.close(ok=True)
            self.assertAlmostEqual(a.Shape.Volume, 1360, places=4)
        finally:
            App.closeDocument(doc.Name)
            App.setActiveDocument(self.doc.Name)
            Gui.setActiveDocument(self.doc.Name)


if __name__ == "__main__":
    unittest.main()
