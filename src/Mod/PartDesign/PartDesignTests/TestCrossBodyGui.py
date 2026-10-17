# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Sub-Shape Binder command on a pick in another Body (FreeCAD-CH ops#308 T2): it binds the
feature, not the Body. Designed geometry. Off screen: QT_QPA_PLATFORM=offscreen, a fresh
FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestStudio import faceAt, pad, rect, sketch, xyPlane

V = App.Vector


class TestCrossBodyGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("CrossBodyGui")
        Gui.Selection.clearSelection()

    def tearDown(self):
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    def source(self):
        """A pad 20 x 10 x 5 in a Body at (100, 50); returns the Body, the pad and its top."""
        source = self.doc.addObject("PartDesign::Body", "Source")
        source.Placement.Base = V(100, 50, 0)
        sketch = models.sketch(self.doc, "Sk", models.rectangle(0, 0, 20, 10), source)
        pad = models.pad(source, sketch, 5)
        self.doc.recompute()
        [top] = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.normalAt(0, 0).z - 1) < 1e-9 and abs(f.CenterOfMass.z - 5) < 1e-6
        ]
        return source, pad, top

    def bind(self, active, source, sub):
        """The command on the pick (source, sub) as picked in 3D, with active as the active
        Body; returns the binder it made."""
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", active)
        Gui.Selection.addSelection(self.doc.Name, source.Name, sub)
        before = {o.Name for o in self.doc.Objects}
        Gui.runCommand("PartDesign_SubShapeBinder")
        pump(0.2)
        [binder] = [
            o for o in self.doc.Objects
            if o.Name not in before and o.TypeId == "PartDesign::SubShapeBinder"
        ]
        self.doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        return binder

    def assertOnTheTop(self, binder):
        """The binder lies on the pad's top, where the pad is in the document."""
        self.assertAlmostEqual(binder.Shape.Area, 200, places=6)
        box = binder.Shape.BoundBox
        for got, expected in zip((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax),
                                 (100, 50, 5, 120, 60, 5)):
            self.assertAlmostEqual(got, expected, places=6)

    def testBinderOfAFaceOfAnotherBodyBindsTheFeature(self):
        """In a second, active Body, the command on the pad's top as picked in 3D,
        (Body, "Pad.FaceN"). The binder binds (Pad, "FaceN"): a binder through the Body made the
        two Bodies depend on each other once the other Body bound something of this one, a
        cycle that never settled. It lies on the pad's top, where the pad is in the document."""
        source, pad, top = self.source()
        target = self.doc.addObject("PartDesign::Body", "Target")
        self.doc.recompute()
        binder = self.bind(target, source, "%s.%s" % (pad.Name, top))
        self.assertIn(binder, target.Group)
        self.assertEqual(binder.Support, [(pad, (top,))])
        self.assertOnTheTop(binder)

    def testBinderWithNoActiveBodyKeepsThePick(self):
        """With no active Body, the command makes the binder at the document's top level and
        keeps the pick as it is, (Body, "Pad.FaceN"): no cycle through a Body forms there. It lies
        on the pad's top. Converted to (Pad, "FaceN"), it lay at the origin (ops#308 F1)."""
        source, pad, top = self.source()
        self.doc.addObject("PartDesign::Body", "Other")
        self.doc.recompute()
        binder = self.bind(None, source, "%s.%s" % (pad.Name, top))
        self.assertIsNone(binder.getParentGeoFeatureGroup())
        self.assertEqual(binder.Support, [(source, ("%s.%s" % (pad.Name, top),))])
        self.assertOnTheTop(binder)


def globalBox(feature):
    """The global bounding box of a feature's own solid (its AddSubShape, in its own frame:
    notes/studio-gates.md, PR 302 round 1)."""
    return feature.AddSubShape.transformed(feature.getGlobalPlacement().toMatrix()).BoundBox


class TestResultBoxGui(unittest.TestCase):
    """The panel's Result box (ops#325, B+ Stage 1 session 2b; notes/bplus-stage1-design.md 2.3):
    New part moves the feature to a new Body while the panel is open, and the edit goes on there;
    Add to moves it back; Cancel aborts it all. Designed geometry, A1's: the enclosure 40 x 40 x 10
    (16000) and a lid sketch 30 x 30 on its top face; the pad's default length is 10 (9000)."""

    def setUp(self):
        self.doc = models.newDocument("ResultBoxGui")
        self.doc.UndoMode = 1
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

    def enclosure(self, container=None, placement=None):
        body = self.doc.addObject("PartDesign::Body", "Enclosure")
        body.Label = "Enclosure"
        if container:
            container.addObject(body)
        if placement:
            body.Placement = placement
        base = pad(body, "Base", sketch(body, "BaseSk", xyPlane(body), (0, 0, 40, 40)), 10)
        self.doc.recompute()
        lidSk = body.newObject("Sketcher::SketchObject", "LidSk")
        lidSk.AttachmentSupport = [(base, faceAt(base, 10))]
        lidSk.MapMode = "FlatFace"
        rect(lidSk, 0, 0, 30, 30)
        self.doc.recompute()
        self.body, self.base, self.lidSk = body, base, lidSk
        return body

    def runCommand(self, command, *selection, index=None):
        """The command (tool `index` of a group) with self.body active and `selection`
        selected; waits for its panel."""
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        for obj in selection:
            Gui.Selection.addSelection(self.doc.Name, obj.Name)
        if index is None:
            Gui.runCommand(command)
        else:
            Gui.runCommand(command, index)
        self.waitForPanel()

    def waitForPanel(self):
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.3)
        Gui.Control.showTaskView()
        ok = QtWidgets.QDialogButtonBox.Ok
        self.assertTrue(waitFor(lambda: taskButton(ok) is not None), "the Tasks panel stays hidden")

    def combo(self):
        """The open panel's Result box, or None."""
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [
            c
            for c in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "resultCombo")
            if c.isVisible()
        ]
        self.assertLessEqual(len(found), 1)
        return found[0] if found else None

    def items(self, combo):
        return [combo.itemText(i) for i in range(combo.count())]

    def choose(self, text):
        """Chooses `text` in the Result box; when that moves the feature, waits until the edit
        has restarted on it."""
        combo = self.combo()
        self.assertIsNotNone(combo, "no Result box")
        index = self.items(combo).index(text)
        combo.setCurrentIndex(index)
        self.assertTrue(
            waitFor(lambda: self.combo() is not None and self.combo().currentText() == text),
            f"the box doesn't show {text!r} again",
        )
        self.waitForPanel()

    def close(self, ok):
        which = QtWidgets.QDialogButtonBox.Ok if ok else QtWidgets.QDialogButtonBox.Cancel
        taskButton(which).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.2)

    def bodies(self):
        return sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body")

    def lidPad(self):
        before = {o.Name for o in self.doc.Objects}
        self.runCommand("PartDesign_Pad", self.lidSk)
        [lid] = [
            o for o in self.doc.Objects if o.Name not in before and o.TypeId == "PartDesign::Pad"
        ]
        return lid

    def testNewPartFromTheResultBox(self):
        """N-t1 in the panel: Pad on the lid sketch offers Add to Enclosure and New part. New
        part moves the pad and its sketch to a new Body at once, and the panel stays open on it,
        in the command's transaction. OK: the new Body holds the sketch and the pad, the lid is
        30 x 30 x 10 alone (9000), the enclosure is back to 16000, and one undo step removes it
        all."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        lid = self.lidPad()
        self.assertEqual(self.items(self.combo()), ["Add to Enclosure", "New part"])
        self.choose("New part")
        [part] = [b for b in self.doc.Objects if b.TypeId == "PartDesign::Body" and b != self.body]
        self.assertEqual(part.Group, [self.lidSk, lid])
        self.assertIs(Gui.getDocument(self.doc.Name).getInEdit().Object, lid)
        self.assertTrue(self.doc.HasPendingTransaction, "the restart committed the command")
        self.assertEqual(self.items(self.combo()), ["Add to Enclosure", "New part"])
        # the enclosure shows its own result while the panel is open
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.close(ok=True)
        self.assertEqual(lid.Length.Value, 10)
        self.assertEqual(part.Group, [self.lidSk, lid])
        self.assertIs(part.Tip, lid)
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)
        self.assertIs(self.body.Tip, self.base)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)

    def testCancelAfterNewPartLeavesNoBody(self):
        """N-t3 in the panel: New part, then Cancel: the document is as before the command (no
        pad, no new Body), the lid sketch is in the enclosure, whose Tip is the base (16000).
        The edit's restart commits the command's transaction unless it is locked: Cancel then
        left the pad in the new Body."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        self.lidPad()
        self.choose("New part")
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertIn(self.lidSk, self.body.Group)
        self.assertIs(self.body.Tip, self.base)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)

    def testToggleBackMovesItBack(self):
        """New part, then Add to Enclosure: the pad and its sketch are back where they were and
        the new Body is gone, while the panel stays open. OK: the enclosure with its lid, 25000,
        in one undo step."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        lid = self.lidPad()
        group = self.body.Group
        self.choose("New part")
        self.assertEqual(len(self.bodies()), 2)
        self.choose("Add to Enclosure")
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertEqual(self.body.Group, group)
        self.assertIs(self.body.Tip, lid)
        self.assertIs(lid.BaseFeature, self.base)
        self.assertTrue(self.doc.HasPendingTransaction)
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 25000, places=3)
        self.assertEqual([o.Name for o in self.doc.Objects if not o.isValid()], [])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)

    def testNewPartOfAPlacedBodyInAPart(self):
        """N-t2 and PR 302 round 1 in the panel: the enclosure at (100, 0, 0) turned 20 deg, in
        an App::Part. New part puts the new Body in that Part, placed as the enclosure, and the
        lid's global box is what it was in the enclosure."""
        studio = self.doc.addObject("App::Part", "Studio")
        placement = App.Placement(V(100, 0, 0), App.Rotation(V(0, 0, 1), 20))
        self.enclosure(studio, placement)
        lid = self.lidPad()
        before = globalBox(lid)
        self.assertGreater(before.XMin, 80)  # the enclosure's placement counts
        self.choose("New part")
        self.close(ok=True)
        part = lid.getParentGeoFeatureGroup()
        self.assertNotEqual(part, self.body)
        self.assertIs(part.getParentGeoFeatureGroup(), studio)
        self.assertTrue(part.Placement.isSame(placement, 1e-9))
        after = globalBox(lid)
        for corner in ("XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"):
            self.assertAlmostEqual(getattr(after, corner), getattr(before, corner), places=6)
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)

    def testNewPartIsRefusedForAUsedFeature(self):
        """In a studio with another part, the base's panel (a feature the lid uses) shows the box
        with New part disabled and the reason as its tooltip; outside a studio it has no box."""
        self.enclosure()
        pad(self.body, "Lid", self.lidSk, 5)
        self.doc.recompute()
        self.doc.openTransaction("Edit Base")
        Gui.getDocument(self.doc.Name).setEdit(self.base.Name)
        self.waitForPanel()
        self.assertIsNone(self.combo())
        self.close(ok=False)
        other = self.doc.addObject("PartDesign::Body", "Other")
        pad(other, "Cube", sketch(other, "CubeSk", xyPlane(other), (50, 0, 60, 10)), 10)
        self.doc.recompute()
        self.doc.openTransaction("Edit Base")
        Gui.getDocument(self.doc.Name).setEdit(self.base.Name)
        self.waitForPanel()
        combo = self.combo()
        self.assertEqual(self.items(combo), ["Add to Enclosure", "New part"])
        model = combo.model()
        self.assertFalse(model.flags(model.index(1, 0)) & QtCore.Qt.ItemIsEnabled)
        self.assertIn("tip that nothing uses", combo.itemData(1, QtCore.Qt.ToolTipRole))

    def testIntersectWith(self):
        """Subtractive, in a studio with another part: a pocket of the lid sketch (5 deep by
        default) offers Remove from and Intersect with Enclosure. Intersect with: Operation
        Common, and the enclosure is the 30 x 30 x 5 that the tool and it share (4500; removing
        left 11500)."""
        self.enclosure()
        other = self.doc.addObject("PartDesign::Body", "Other")
        pad(other, "Cube", sketch(other, "CubeSk", xyPlane(other), (50, 0, 60, 10)), 10)
        self.doc.recompute()
        before = {o.Name for o in self.doc.Objects}
        self.runCommand("PartDesign_Pocket", self.lidSk)
        [pocket] = [
            o for o in self.doc.Objects if o.Name not in before and o.TypeId == "PartDesign::Pocket"
        ]
        self.assertEqual(
            self.items(self.combo()), ["Remove from Enclosure", "Intersect with Enclosure"]
        )
        self.combo().setCurrentIndex(1)
        pump(0.2)
        self.assertEqual(pocket.Operation, "Common")
        self.close(ok=True)
        self.assertEqual(pocket.Operation, "Common")
        self.assertEqual(pocket.Length.Value, 5)
        self.assertAlmostEqual(self.body.Shape.Volume, 4500, places=3)

    def testNewPartFromAnAdditivePrimitive(self):
        """N-t4 in the panel: an additive box (10 x 10 x 10) from its command, then New part and
        OK: a new Body holds the box alone (1000); the enclosure is 16000."""
        self.enclosure()
        before = {o.Name for o in self.doc.Objects}
        self.runCommand("PartDesign_CompPrimitiveAdditive", index=0)
        [box] = [
            o
            for o in self.doc.Objects
            if o.Name not in before and o.TypeId == "PartDesign::AdditiveBox"
        ]
        self.choose("New part")
        self.close(ok=True)
        part = box.getParentGeoFeatureGroup()
        self.assertNotEqual(part, self.body)
        self.assertEqual(part.Group, [box])
        self.assertAlmostEqual(part.Shape.Volume, 1000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)

    def activate(self, doc):
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        pump(0.3)
        self.doc = doc

    def testTwoDocumentsKeepTheirOwnMoves(self):
        """PR 303 round 1: New part in document A's panel, then in document B's. Back in A, Add
        to Enclosure moves A's pad back, and B's stays in its new Body. One record for the open
        move was shared: B's replaced A's, so A's Add to did nothing while the box read Add to,
        and OK left the pad in the new Body."""
        self.enclosure()
        docA, bodyA = self.doc, self.body
        lidA = self.lidPad()
        self.choose("New part")
        docB = models.newDocument("ResultBoxGuiB")
        docB.UndoMode = 1
        try:
            self.activate(docB)
            self.enclosure()
            bodyB = self.body
            lidB = self.lidPad()
            self.choose("New part")
            partB = lidB.getParentGeoFeatureGroup()
            self.assertNotEqual(partB, bodyB)
            self.activate(docA)
            self.body = bodyA
            self.assertEqual(self.combo().currentText(), "New part")
            self.choose("Add to Enclosure")
            self.assertIs(lidA.getParentGeoFeatureGroup(), bodyA)
            self.assertEqual(self.bodies(), ["Enclosure"])
            self.close(ok=True)
            self.assertIs(lidA.getParentGeoFeatureGroup(), bodyA)
            self.assertAlmostEqual(bodyA.Shape.Volume, 25000, places=3)
            self.activate(docB)
            self.assertIs(lidB.getParentGeoFeatureGroup(), partB)
            self.assertEqual(self.combo().currentText(), "New part")
            self.close(ok=True)
            self.assertIs(lidB.getParentGeoFeatureGroup(), partB)
            self.assertAlmostEqual(partB.Shape.Volume, 9000, places=3)
            self.assertAlmostEqual(bodyB.Shape.Volume, 16000, places=3)
        finally:
            self.activate(docB)
            if Gui.Control.activeDialog():
                Gui.Control.closeDialog()
                pump()
            App.closeDocument(docB.Name)
            pump()
            self.activate(docA)

    def testOkBeforeTheMoveRuns(self):
        """PR 303 round 1: New part is chosen and OK is clicked before the queued move runs. OK
        commits the pad where it is, in the enclosure (25000), and the move then does nothing:
        it ran outside any transaction, so the pad sat in a new Body that no undo covered, and a
        panel opened again. One undo step removes the pad."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        lid = self.lidPad()
        self.combo().setCurrentIndex(1)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        pump(1.0)
        self.assertFalse(Gui.Control.activeDialog())
        self.assertIs(lid.getParentGeoFeatureGroup(), self.body)
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertAlmostEqual(self.body.Shape.Volume, 25000, places=3)
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(len(self.doc.UndoNames), 1, self.doc.UndoNames)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)


if __name__ == "__main__":
    unittest.main()
