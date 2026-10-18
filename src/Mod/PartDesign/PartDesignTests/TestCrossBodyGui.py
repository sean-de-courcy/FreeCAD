# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Sub-Shape Binder command on a pick in another Body (FreeCAD-CH ops#308 T2): it binds the
feature, not the Body. Designed geometry. Off screen: QT_QPA_PLATFORM=offscreen, a fresh
FREECAD_USER_HOME (notes/build.md)."""

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
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
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, source.Name, sub)
        before = {o.Name for o in self.doc.Objects}
        # the command's error box (a cyclic reference, ops#321) is closed and recorded: left
        # open, it held the test until the run's timeout
        modals = []
        answering = [True]

        def poll():
            if not answering[0]:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if isinstance(widget, QtWidgets.QMessageBox):
                modals.append(widget.text())
                widget.accept()
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)
        try:
            Gui.runCommand("PartDesign_SubShapeBinder")
            pump(0.2)
        finally:
            answering[0] = False
        self.assertEqual(modals, [])
        [binder] = [
            o for o in self.doc.Objects
            if o.Name not in before and o.TypeId == "PartDesign::SubShapeBinder"
        ]
        self.doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        return binder

    def assertOnTheTop(self, binder, at=(100, 50, 5)):
        """The binder lies on the pad's top, where the pad is in the document: the 20 x 10
        rectangle from at."""
        self.assertAlmostEqual(binder.Shape.Area, 200, places=6)
        shape = binder.Shape.copy()
        container = binder.getParentGeoFeatureGroup()
        if container:
            shape = shape.transformed(container.getGlobalPlacement().toMatrix())
        box = shape.BoundBox
        x, y, z = at
        for got, expected in zip((box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax),
                                 (x, y, z, x + 20, y + 10, z)):
            self.assertAlmostEqual(got, expected, places=6)

    def bodyInPart(self, name, part, at):
        """A Body named name at at in part, with a pad 20 x 10 x 5; returns the Body, the pad and
        its top."""
        body = self.doc.addObject("PartDesign::Body", name)
        body.Placement.Base = at
        part.addObject(body)
        sketch = models.sketch(self.doc, name + "Sk", models.rectangle(0, 0, 20, 10), body)
        feature = models.pad(body, sketch, 5)
        self.doc.recompute()
        [top] = [
            f"Face{i}"
            for i, f in enumerate(feature.Shape.Faces, 1)
            if abs(f.normalAt(0, 0).z - 1) < 1e-9 and abs(f.CenterOfMass.z - 5) < 1e-6
        ]
        return body, feature, top

    def placedPart(self, name, at):
        part = self.doc.addObject("App::Part", name)
        part.Placement.Base = at
        return part

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

    def testBinderOfAFaceThroughAPartBindsTheFeature(self):
        """ops#321: a Body at (70, 50) in an App::Part at z 30; in a second, active Body at the
        top level, the command on the pad's top as picked in 3D through the Part,
        (P1, "Source.Pad.FaceN"). The binder binds (Pad, "FaceN"), as for a pick through the Body
        alone: through the Part it depended on everything in it. It lies on the pad's top, where
        the pad is in the document, at z 35."""
        p1 = self.placedPart("P1", V(0, 0, 30))
        source, pad, top = self.bodyInPart("Source", p1, V(70, 50, 0))
        target = self.doc.addObject("PartDesign::Body", "Target")
        self.doc.recompute()
        binder = self.bind(target, p1, "%s.%s.%s" % (source.Name, pad.Name, top))
        self.assertIn(binder, target.Group)
        self.assertEqual(binder.Support, [(pad, (top,))])
        self.assertOnTheTop(binder, at=(70, 50, 35))

    def testBindersOfEachOtherThroughPartsBuild(self):
        """ops#321: two Bodies, each in its own App::Part (P1 at z 30, P2 at x 200), bind each
        other's pads through the Parts, interleaved: B's binder of A's top, then A's binder of
        B's top. Through the Parts, each binder depended on the other Part, so on the other
        binder: a cyclic dependency, and the document didn't recompute. Of the features, both
        build, each on the other pad's top."""
        p1 = self.placedPart("P1", V(0, 0, 30))
        p2 = self.placedPart("P2", V(200, 0, 0))
        bodyA, padA, topA = self.bodyInPart("BodyA", p1, V(70, 50, 0))
        bodyB, padB, topB = self.bodyInPart("BodyB", p2, V(10, 20, 0))
        binderB = self.bind(bodyB, p1, "%s.%s.%s" % (bodyA.Name, padA.Name, topA))
        binderA = self.bind(bodyA, p2, "%s.%s.%s" % (bodyB.Name, padB.Name, topB))
        self.assertIn(binderB, bodyB.Group)
        self.assertIn(binderA, bodyA.Group)
        self.assertEqual(binderB.Support, [(padA, (topA,))])
        self.assertEqual(binderA.Support, [(padB, (topB,))])
        self.doc.recompute()
        for obj in (binderA, binderB, padA, padB):
            self.assertTrue(obj.isValid(), "%s: %s" % (obj.Name, obj.getStatusString()))
        self.assertOnTheTop(binderB, at=(70, 50, 35))
        self.assertOnTheTop(binderA, at=(210, 20, 5))

    def testBinderOfAFaceOfAnotherBodyInTheSamePart(self):
        """ops#321: both Bodies in one App::Part at z 30, the source at (70, 50) in it. The
        command in the target, on the pad's top picked through the Part, (P, "Source.Pad.FaceN"),
        binds (Pad, "FaceN"), on the pad's top at z 35. A guard: the pick, resolved from the
        Part the active Body is in, came through the Body alone before ops#321 too."""
        part = self.placedPart("P", V(0, 0, 30))
        source, pad, top = self.bodyInPart("Source", part, V(70, 50, 0))
        target = self.doc.addObject("PartDesign::Body", "Target")
        part.addObject(target)
        self.doc.recompute()
        binder = self.bind(target, part, "%s.%s.%s" % (source.Name, pad.Name, top))
        self.assertIn(binder, target.Group)
        self.assertEqual(binder.Support, [(pad, (top,))])
        self.assertOnTheTop(binder, at=(70, 50, 35))


def globalBox(feature):
    """The global bounding box of a feature's own solid (its AddSubShape, in its own frame:
    notes/studio-gates.md, PR 302 round 1)."""
    return feature.AddSubShape.transformed(feature.getGlobalPlacement().toMatrix()).BoundBox


class ResultBoxGuiCase(unittest.TestCase):
    """The fixture and helpers of the Result box tests: a document with undo, the PartDesign
    workbench, the panel's widgets."""

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

    def featurePanel(self, command):
        """The command on the lid sketch; returns the feature it made, with its panel open."""
        before = {o.Name for o in self.doc.Objects}
        self.runCommand(command, self.lidSk)
        [feature] = [
            o
            for o in self.doc.Objects
            if o.Name not in before and o.isDerivedFrom("PartDesign::FeatureAddSub")
        ]
        return feature

    def otherPart(self):
        """A second part beside the enclosure, so the box shows for a subtractive feature."""
        other = self.doc.addObject("PartDesign::Body", "Other")
        pad(other, "Cube", sketch(other, "CubeSk", xyPlane(other), (50, 0, 60, 10)), 10)
        self.doc.recompute()

    def assertAdditiveBox(self, command):
        self.enclosure()
        feature = self.featurePanel(command)
        self.assertEqual(self.items(self.combo()), ["Add to Enclosure", "New part"])
        return feature

    def assertSubtractiveBox(self, command):
        self.enclosure()
        self.otherPart()
        self.featurePanel(command)
        self.assertEqual(
            self.items(self.combo()), ["Remove from Enclosure", "Intersect with Enclosure"]
        )

    def activate(self, doc):
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        pump(0.3)
        self.doc = doc


class TestResultBoxGui(ResultBoxGuiCase):
    """The panel's Result box (ops#325, B+ Stage 1 session 2b; notes/bplus-stage1-design.md 2.3):
    New part moves the feature to a new Body while the panel is open, and the edit goes on there;
    Add to moves it back; Cancel aborts it all. Designed geometry, A1's: the enclosure 40 x 40 x 10
    (16000) and a lid sketch 30 x 30 on its top face; the pad's default length is 10 (9000)."""

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

    def testNewPartWhenEditingAnUnusedTip(self):
        """PR 303 round 2: an existing lid pad, the enclosure's tip that nothing uses, edited by
        a double click. New part is offered and, chosen at once, moves the pad; OK leaves the lid
        alone in the new Body (9000) and the enclosure 16000. The move's guard asks for an open
        transaction, booked or pending (the panel's opening writes, so it is pending here)."""
        self.enclosure()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        lid.ViewObject.doubleClicked()
        self.waitForPanel()
        combo = self.combo()
        model = combo.model()
        self.assertTrue(model.flags(model.index(1, 0)) & QtCore.Qt.ItemIsEnabled)
        self.choose("New part")
        part = lid.getParentGeoFeatureGroup()
        self.assertNotEqual(part, self.body)
        self.close(ok=True)
        self.assertIs(lid.getParentGeoFeatureGroup(), part)
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)

    def testRevolutionPanelNewPart(self):
        """PR 303 round 1, the panels the 2b tests didn't open: Revolution shows the box, and New
        part works there. The lid square (sketch x 0 to 30) turned about the sketch's V axis is a
        cylinder of radius 30 and height 30, alone in the new Body; the enclosure is 16000."""
        revolution = self.assertAdditiveBox("PartDesign_Revolution")
        self.choose("New part")
        self.close(ok=True)
        part = revolution.getParentGeoFeatureGroup()
        self.assertNotEqual(part, self.body)
        self.assertEqual(part.Group, [self.lidSk, revolution])
        self.assertAlmostEqual(part.Shape.Volume, math.pi * 30**2 * 30, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)

    def testLoftPanelHasTheBox(self):
        self.assertAdditiveBox("PartDesign_AdditiveLoft")

    def testPipePanelHasTheBox(self):
        self.assertAdditiveBox("PartDesign_AdditivePipe")

    def testHelixPanelHasTheBox(self):
        self.assertAdditiveBox("PartDesign_AdditiveHelix")

    def testGroovePanelHasTheBox(self):
        self.assertSubtractiveBox("PartDesign_Groove")

    def testHolePanelHasTheBox(self):
        self.assertSubtractiveBox("PartDesign_Hole")

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


class TestSiblingsGui(ResultBoxGuiCase):
    """Remove from several parts in the panel (ops#325, B+ Stage 1 session 3a;
    notes/bplus-stage1-design.md 2.4): the Result box of a subtractive feature lists the studio's
    other parts, those its tool touches first; OK makes the ticked parts' siblings. A sibling's
    panel is read-only, says whom it follows and offers Unlink. Designed geometry: the enclosure
    with its lid sketch (30 x 30 on its top), a part "Below" (40 x 40 x 10 under the enclosure)
    and a part "Far" (100 away)."""

    def part(self, name, rect, z):
        body = self.doc.addObject("PartDesign::Body", name)
        body.Label = name
        pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), rect, z=z), 10)
        self.doc.recompute()
        return body

    def parts(self):
        self.enclosure()
        self.below = self.part("Below", (0, 0, 40, 40), -10)
        self.far = self.part("Far", (100, 0, 140, 40), 0)

    def partsList(self):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QListWidget, "partsList")
            if w.isVisible()
        ]
        return found[0] if found else None

    def partItems(self):
        """(text, ticked, enabled) of each row of the parts list"""
        rows = self.partsList()
        self.assertIsNotNone(rows, "no parts list")
        return [
            (
                rows.item(i).text(),
                rows.item(i).checkState() == QtCore.Qt.Checked,
                bool(rows.item(i).flags() & QtCore.Qt.ItemIsEnabled),
            )
            for i in range(rows.count())
        ]

    def visible(self, cls, name):
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def throughAll(self):
        """A pocket of the lid sketch through all, and its sibling in Below, from Python."""
        pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.lidSk
        pocket.Type = "ThroughAll"
        self.doc.recompute()
        [sibling] = PartDesign.makeSiblings(pocket, [self.below])
        self.doc.recompute()
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        return pocket, sibling

    def edit(self, obj):
        self.doc.openTransaction("Edit " + obj.Name)
        Gui.getDocument(self.doc.Name).setEdit(obj.Name)
        self.waitForPanel()

    def testSiblingFromThePartsList(self):
        """R-t1 in the panel: a pocket of the lid sketch, 5 deep, lists Enclosure (ticked, fixed),
        then Below and Far, which it doesn't touch. Its length set to 20 in the panel: once the
        preview settles, Below is touched. Below ticked, OK: Below holds a pocket that follows
        this one (length 20), and both parts lose the 30 x 30 x 10 they share with the tool
        (7000 each). One undo step removes both."""
        self.parts()
        before = sorted(o.Name for o in self.doc.Objects)
        pocket = self.featurePanel("PartDesign_Pocket")
        self.assertEqual(
            self.partItems(),
            [
                ("Enclosure", True, False),
                ("Below (doesn't touch)", False, True),
                ("Far (doesn't touch)", False, True),
            ],
        )
        self.visible(QtWidgets.QWidget, "lengthEdit").setProperty("rawValue", 20.0)
        self.assertTrue(
            waitFor(lambda: self.partsList().item(1).text() == "Below"), self.partItems()
        )
        self.assertEqual(self.partsList().item(2).text(), "Far (doesn't touch)")
        self.partsList().item(1).setCheckState(QtCore.Qt.Checked)
        self.close(ok=True)
        [sibling] = PartDesign.siblingsOf(pocket)
        self.assertIn(sibling, self.below.Group)
        self.assertIs(self.below.Tip, sibling)
        self.assertEqual(sibling.Length.Value, 20)
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.assertAlmostEqual(self.below.Shape.Volume, 7000, places=3)
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=3)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)

    def testSiblingPanelIsReadOnlyUntilUnlink(self):
        """A sibling's panel: the box says it follows Pocket and offers Unlink; Remove from and
        the pocket's own fields are read-only. Unlink: the panel opens again editable, and OK
        keeps the sibling independent (no SiblingOf, no expressions), its cut as it was."""
        self.parts()
        pocket, sibling = self.throughAll()
        self.edit(sibling)
        note = self.visible(QtWidgets.QLabel, "followsNote")
        self.assertIsNotNone(note, "no note")
        self.assertIn("Follows Pocket", note.text())
        self.assertFalse(self.combo().isEnabled())
        self.assertFalse(self.visible(QtWidgets.QComboBox, "sidesMode").isEnabled())
        self.visible(QtWidgets.QPushButton, "unlinkButton").click()
        self.assertTrue(
            waitFor(
                lambda: self.visible(QtWidgets.QLabel, "followsNote") is None
                and self.visible(QtWidgets.QComboBox, "sidesMode") is not None
                and self.visible(QtWidgets.QComboBox, "sidesMode").isEnabled()
            ),
            "the panel stays read-only",
        )
        self.assertIsNone(sibling.SiblingOf)
        self.assertTrue(self.doc.HasPendingTransaction)
        self.close(ok=True)
        self.assertIsNone(sibling.SiblingOf)
        self.assertEqual(sibling.ExpressionEngine, [])
        self.assertEqual(PartDesign.siblingsOf(pocket), [])
        self.assertAlmostEqual(self.below.Shape.Volume, 7000, places=3)

    def testPrimaryPanelShowsItsSiblings(self):
        """Editing the primary shows Below ticked again. Unticked, OK: the sibling is gone and
        Below is whole (16000)."""
        self.parts()
        pocket, sibling = self.throughAll()
        name = sibling.Name
        self.edit(pocket)
        self.assertEqual(
            self.partItems(),
            [
                ("Enclosure", True, False),
                ("Below", True, True),
                ("Far (doesn't touch)", False, True),
            ],
        )
        self.partsList().item(1).setCheckState(QtCore.Qt.Unchecked)
        self.close(ok=True)
        self.assertEqual(PartDesign.siblingsOf(pocket), [])
        self.assertIsNone(self.doc.getObject(name))
        self.assertAlmostEqual(self.below.Shape.Volume, 16000, places=3)


class TestMergeGui(ResultBoxGuiCase):
    """Merge in the panel (ops#325, B+ Stage 1 session 3b; notes/bplus-stage1-design.md 2.5): an
    additive feature's Result box lists the studio's other parts under Merge with, unticked; a
    touching one left out gets a plain line, a ticked one the yellow banner, and OK merges it. The
    Merge's panel offers Accept; the tree marks an unaccepted Merge while it is held; the Merge
    Parts command merges after the fact. Designed geometry: the enclosure with its lid sketch
    (30 x 30 on its top; the pad's default length is 10), a part "Panel" 40 x 30 x 10 from
    (20, 0, 10), which the lid pad overlaps in 10 x 30 x 10, and a part "Far" (100 away)."""

    def part(self, name, rect, z):
        body = self.doc.addObject("PartDesign::Body", name)
        body.Label = name
        pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), rect, z=z), 10)
        self.doc.recompute()
        return body

    def parts(self):
        self.enclosure()
        self.panel = self.part("Panel", (20, 0, 60, 30), 10)
        self.far = self.part("Far", (100, 0, 140, 40), 0)

    def visible(self, cls, name):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def mergeItems(self):
        rows = self.visible(QtWidgets.QListWidget, "mergeList")
        self.assertIsNotNone(rows, "no Merge with list")
        return [
            (rows.item(i).text(), rows.item(i).checkState() == QtCore.Qt.Checked)
            for i in range(rows.count())
        ]

    def treeIcon(self, obj):
        """The image of obj's icon in the tree."""
        for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
            for item in tree.findItems(obj.Label, QtCore.Qt.MatchExactly | QtCore.Qt.MatchRecursive):
                return item.icon(0).pixmap(16, 16).toImage()
        self.fail(f"{obj.Label} isn't in the tree")

    def testMergeFromTheResultBox(self):
        """M-t1 in the panel: Pad on the lid sketch lists Panel (touched) and Far, unticked, with
        the plain line "Touches Panel (not merged)" and no banner. Panel ticked: the banner says
        what merging does, the line goes. OK: a Merge right after the pad, the Enclosure's Tip,
        fuses Panel's pad (16000 + 9000 + 12000 - 3000 = 34000); Panel is hidden and merged, and
        the Merge warns. One undo step removes the pad and the Merge."""
        self.parts()
        before = sorted(o.Name for o in self.doc.Objects)
        lid = self.featurePanel("PartDesign_Pad")
        self.assertEqual(self.mergeItems(), [("Panel", False), ("Far (doesn't touch)", False)])
        note = self.visible(QtWidgets.QLabel, "mergeNote")
        self.assertIsNotNone(note, "no plain line")
        self.assertEqual(note.text(), "Touches Panel (not merged)")
        self.assertIsNone(self.visible(QtWidgets.QLabel, "mergeBanner"))
        self.visible(QtWidgets.QListWidget, "mergeList").item(0).setCheckState(QtCore.Qt.Checked)
        banner = self.visible(QtWidgets.QLabel, "mergeBanner")
        self.assertIsNotNone(banner, "no banner")
        self.assertTrue(banner.text().startswith("Merges Panel into Enclosure. Panel stops"))
        self.assertIsNone(self.visible(QtWidgets.QLabel, "mergeNote"))
        self.close(ok=True)
        merge = self.panel.MergedInto
        self.assertIsNotNone(merge)
        group = self.body.Group
        self.assertEqual(group.index(merge), group.index(lid) + 1)
        self.assertIs(self.body.Tip, merge)
        self.assertFalse(self.panel.Visibility)
        self.assertIn("Merged Panel into Enclosure", merge.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 34000, places=3)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertTrue(self.panel.Visibility)

    def testAcceptInTheMergePanelAndTheTreeMark(self):
        """M-t2 in the Gui: held (the Enclosure rolled back above it), the Merge isn't
        recomputed and keeps its warning, so the tree marks it. Failed (Panel's pad of length
        0), the document has cleared its warning, yet the tree marks it until accepted. Its
        panel says what it merges, keeps the tools fixed, and offers Accept: OK, and the Merge
        is accepted, without a warning."""
        self.parts()
        merge = PartDesign.makeMerge(self.body, [self.panel])
        self.doc.recompute()
        self.assertIn("Warning", merge.State)
        self.body.Tip = self.base
        self.doc.recompute()
        self.assertIn("Warning", merge.State)
        self.body.Tip = merge
        self.doc.recompute()

        panelPad = self.panel.Tip
        panelPad.Length = 0
        self.doc.recompute()
        pump(0.3)
        self.assertFalse(merge.isValid())
        self.assertNotIn("Warning", merge.State)
        marked = self.treeIcon(merge)
        merge.MergeAccepted = True
        pump(0.3)
        self.assertNotEqual(self.treeIcon(merge), marked, "no mark while failed")
        merge.MergeAccepted = False
        panelPad.Length = 10
        self.doc.recompute()
        pump(0.3)
        self.assertIn("Warning", merge.State)

        self.doc.openTransaction("Edit Merge")
        Gui.getDocument(self.doc.Name).setEdit(merge.Name)
        self.waitForPanel()
        note = self.visible(QtWidgets.QLabel, "mergeNote")
        self.assertIsNotNone(note, "no note")
        self.assertEqual(note.text(), "A Merge of Panel: delete it to unmerge")
        self.assertFalse(self.visible(QtWidgets.QToolButton, "buttonBodyAdd").isEnabled())
        self.visible(QtWidgets.QPushButton, "acceptMergeButton").click()
        self.close(ok=True)
        self.assertTrue(merge.MergeAccepted)
        self.assertNotIn("Warning", merge.State)

    def testMergePartsCommand(self):
        """Merge Parts after the fact: the Enclosure picked, then Panel: a Merge at the
        Enclosure's Tip (16000 + 12000, no overlap), in one undo step."""
        self.parts()
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.body.Name)
        Gui.Selection.addSelection(self.doc.Name, self.panel.Name)
        Gui.runCommand("PartDesign_MergeParts")
        pump(0.2)
        merge = self.panel.MergedInto
        self.assertIsNotNone(merge)
        self.assertIs(self.body.Tip, merge)
        self.assertEqual(merge.Group, [self.panel.Tip])
        self.assertAlmostEqual(self.body.Shape.Volume, 28000, places=3)
        name = merge.Name
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)


class TestSplitGui(ResultBoxGuiCase):
    """Split Part (ops#325, B+ Stage 1 session 4; notes/bplus-stage1-design.md 2.7): the part and a
    plane picked, the command splits it and opens the original's Split, whose panel says which
    side stays and offers a Flip; OK keeps both halves in one undo step, Cancel takes both away.
    Designed geometry: S4's shroud, a box 20 x 10 x 8 hollowed by 18 x 8 x 7 from (1, 1, 1)
    (592), and a datum plane at y = 3, normal +Y: front 364, back 228."""

    def shroud(self):
        body = self.doc.addObject("PartDesign::Body", "Shroud")
        body.Label = "Shroud"
        outer = body.newObject("PartDesign::AdditiveBox", "Outer")
        outer.Length, outer.Width, outer.Height = 20, 10, 8
        inner = body.newObject("PartDesign::SubtractiveBox", "Inner")
        inner.Length, inner.Width, inner.Height = 18, 8, 7
        inner.Placement = App.Placement(V(1, 1, 1), App.Rotation())
        plane = body.newObject("PartDesign::Plane", "SplitPlane")
        plane.Label = "SplitPlane"
        plane.MapMode = "Deactivated"
        plane.Placement = App.Placement(V(0, 3, 0), App.Rotation(V(0, 0, 1), V(0, 1, 0)))
        self.doc.recompute()
        self.assertAlmostEqual(body.Shape.Volume, 592, places=6)
        self.body, self.plane = body, plane

    def visible(self, cls, name):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def newParts(self):
        return [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body" and o != self.body]

    def testSplitPartFlipAndOk(self):
        """The shroud and the plane picked: the panel says Shroud keeps the front and Shroud001
        gets the back (364 and 228); Flip swaps them; OK keeps them, and one undo takes the
        split away."""
        self.shroud()
        self.runCommand("PartDesign_Split", self.body, self.plane)
        split = self.body.Tip
        self.assertEqual(split.TypeId, "PartDesign::Split")
        [part] = self.newParts()
        self.assertEqual(part.Label, "Shroud001")
        sides = self.visible(QtWidgets.QLabel, "labelSides")
        self.assertIsNotNone(sides, "no Split panel")
        self.assertIn("Shroud keeps the front side", sides.text())
        self.assertIn("Shroud001 gets the back side", sides.text())
        self.assertAlmostEqual(self.body.Shape.Volume, 364, places=6)
        self.assertAlmostEqual(part.Shape.Volume, 228, places=6)

        self.visible(QtWidgets.QCheckBox, "checkBoxFlip").setChecked(True)
        self.assertTrue(waitFor(lambda: abs(part.Shape.Volume - 364) < 1e-6), "no flip")
        self.assertEqual(split.Side, "Back")
        self.assertIn("Shroud keeps the back side", sides.text())
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 228, places=6)
        self.assertAlmostEqual(part.Shape.Volume, 364, places=6)

        name = part.Name
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(self.body.Tip.Name, "Inner")
        self.assertAlmostEqual(self.body.Shape.Volume, 592, places=6)

    def testCancelLeavesNoSplit(self):
        """Cancel: neither the Split nor the new part stays, and the shroud is whole."""
        self.shroud()
        self.runCommand("PartDesign_Split", self.body, self.plane)
        self.assertEqual(len(self.newParts()), 1)
        self.close(ok=False)
        self.assertEqual(self.newParts(), [])
        self.assertFalse([o for o in self.doc.Objects if o.TypeId == "PartDesign::Split"])
        self.assertAlmostEqual(self.body.Shape.Volume, 592, places=6)

    def testPlanePickedAfterAFace(self):
        """A face of the shroud picked first, then the plane: the plane is the tool, in any order
        (the face, the cavity's wall at y = 1, would give 432 and 160)."""
        self.shroud()
        face = None
        for i, f in enumerate(self.body.Shape.Faces, 1):
            if abs(f.CenterOfMass.y - 1) < 1e-9 and abs(f.normalAt(0, 0).y - 1) < 1e-9:
                face = f"Face{i}"
        self.assertIsNotNone(face)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, face)
        Gui.Selection.addSelection(self.doc.Name, self.plane.Name)
        Gui.runCommand("PartDesign_Split")
        self.waitForPanel()
        self.assertIs(self.body.Tip.Tool[0], self.plane)
        [part] = self.newParts()
        self.assertAlmostEqual(self.body.Shape.Volume, 364, places=6)
        self.assertAlmostEqual(part.Shape.Volume, 228, places=6)
        self.close(ok=True)

    def testNewHalfPanelFollows(self):
        """The new half's Split, edited: its panel names the Split it follows, and its Flip is
        the original's to make (disabled)."""
        self.shroud()
        self.runCommand("PartDesign_Split", self.body, self.plane)
        self.close(ok=True)
        [part] = self.newParts()
        Gui.getDocument(self.doc.Name).setEdit(part.Tip.Name, 0)
        self.waitForPanel()
        self.assertFalse(self.visible(QtWidgets.QCheckBox, "checkBoxFlip").isEnabled())
        sides = self.visible(QtWidgets.QLabel, "labelSides")
        self.assertIn("Flip it in Shroud's Split", sides.text())
        self.close(ok=True)


if __name__ == "__main__":
    unittest.main()
