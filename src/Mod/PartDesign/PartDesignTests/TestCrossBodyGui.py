# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Sub-Shape Binder command on a pick in another Body (FreeCAD-CH ops#308 T2): it binds the
feature, not the Body. Designed geometry. Off screen: QT_QPA_PLATFORM=offscreen, a fresh
FREECAD_USER_HOME (notes/build.md)."""

import functools
import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets
from PySide6 import QtTest

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor
from PartDesignTests.TestStudio import faceAt, pad, rect, sketch, xyPlane

V = App.Vector


def keepSiblingEraPath(case):
    """ops#654 list on first use: the studio commands make the studio's list and take the owner
    path. A test of the sibling-era in-Body path (kept in the code until R0 removes it) calls this
    in its setUp: the hidden test hook StudioListOnFirstUse off, restored at its cleanup, so a
    studio without a list keeps that path as before. Moving such a test to the listed behaviour
    drops the call."""
    param = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
    had = param.GetBool("StudioListOnFirstUse", True)
    param.SetBool("StudioListOnFirstUse", False)
    case.addCleanup(param.SetBool, "StudioListOnFirstUse", had)


def siblingEraPath(test):
    """A test method of the sibling-era in-Body path: keepSiblingEraPath() for it (ops#654)."""

    @functools.wraps(test)
    def run(self, *args, **kwargs):
        keepSiblingEraPath(self)
        return test(self, *args, **kwargs)

    return run


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


# A Revolve's error with no axis, Onshape's words (hands-on check R6, ops#640 H1)
AXIS_MISSING = "Select the axis to revolve around"

# A Pad's or a Pocket's rows in the enclosure (ops#640)
ROWS = ["New", "Add", "Remove", "Intersect"]


def shownFeatures(body):
    """The names of the Body's shown solid features (ViewProviderBody::getShownFeature's test)."""
    return [o.Name for o in body.Group if o.isDerivedFrom("PartDesign::Feature") and o.Visibility]


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

    def chooseAxis(self, text):
        """The axis box's entry chosen as a user does (ReferenceCombo takes activated)."""
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        [box] = [
            c for c in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "axis") if c.isVisible()
        ]
        index = box.findText(text)
        self.assertGreaterEqual(index, 0, [box.itemText(i) for i in range(box.count())])
        box.setCurrentIndex(index)
        box.activated.emit(index)
        pump(0.3)

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
        """Since ops#640 rank 20 a Revolve, Loft, Sweep and Helix have an Extrude's four rows."""
        self.enclosure()
        feature = self.featurePanel(command)
        self.assertEqual(self.items(self.combo()), ROWS)
        return feature

    def assertSubtractiveBox(self, command):
        """A Groove has the four rows too (rank 20); a Hole is still a cut, with its two."""
        self.enclosure()
        self.otherPart()
        self.featurePanel(command)
        expected = (
            ["Remove", "Intersect"]
            if command == "PartDesign_Hole"
            else ROWS
        )
        self.assertEqual(self.items(self.combo()), expected)

    def activate(self, doc):
        App.setActiveDocument(doc.Name)
        Gui.setActiveDocument(doc.Name)
        pump(0.3)
        self.doc = doc

    def part(self, name, rect, z):
        """A part `name`: a 10 thick pad of `rect` on its XY plane, raised by z."""
        body = self.doc.addObject("PartDesign::Body", name)
        body.Label = name
        pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), rect, z=z), 10)
        self.doc.recompute()
        return body

    def visible(self, cls, name):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
        return found[0] if found else None

    def partsList(self):
        return self.visible(QtWidgets.QListWidget, "partsList")

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

    def modalsDuring(self, action):
        """Runs action; every message box that opens meanwhile is recorded and closed (left open,
        it would hold the test until the run's timeout)."""
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

        QtCore.QTimer.singleShot(0, poll)
        try:
            action()
        finally:
            answering[0] = False
        return modals

    def lengthField(self):
        field = self.visible(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(field, "no length field")
        return field


class TestResultBoxGui(ResultBoxGuiCase):
    """The panel's Result box (ops#325, B+ Stage 1 session 2b; notes/bplus-stage1-design.md 2.3):
    New part moves the feature to a new Body while the panel is open, and the edit goes on there;
    Add to moves it back; Cancel aborts it all. Designed geometry, A1's: the enclosure 40 x 40 x 10
    (16000) and a lid sketch 30 x 30 on its top face; the pad's default length is 10 (9000)."""

    @siblingEraPath
    def testNewPartFromTheResultBox(self):
        """N-t1 in the panel: Pad on the lid sketch offers Add to Enclosure and New part. New
        part moves the pad and its sketch to a new Body at once, and the panel stays open on it,
        in the command's transaction. OK: the new Body holds the sketch and the pad, the lid is
        30 x 30 x 10 alone (9000), the enclosure is back to 16000, and one undo step removes it
        all."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        lid = self.lidPad()
        self.assertEqual(self.items(self.combo()), ROWS)
        self.choose("New")
        [part] = [b for b in self.doc.Objects if b.TypeId == "PartDesign::Body" and b != self.body]
        self.assertEqual(part.Group, [self.lidSk, lid])
        self.assertIs(Gui.getDocument(self.doc.Name).getInEdit().Object, lid)
        self.assertTrue(self.doc.HasPendingTransaction, "the restart committed the command")
        self.assertEqual(self.items(self.combo()), ROWS)
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
        self.choose("New")
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertIn(self.lidSk, self.body.Group)
        self.assertIs(self.body.Tip, self.base)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)

    @siblingEraPath
    def testToggleBackMovesItBack(self):
        """New part, then Add to Enclosure: the pad and its sketch are back where they were and
        the new Body is gone, while the panel stays open. OK: the enclosure with its lid, 25000,
        in one undo step."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        lid = self.lidPad()
        group = self.body.Group
        self.choose("New")
        self.assertEqual(len(self.bodies()), 2)
        self.choose("Add")
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

    @siblingEraPath
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
        self.choose("New")
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
        """F1 (ops#640): the lid pad, which a pad on its top uses, edited with no other part in
        the document: the box is there, on Add to Enclosure, with New part disabled and the reason
        as its tooltip: the top pad's sketch is on the lid, and the pad would stay in the enclosure
        (round 5 moves only what works on the lid's own material, TestOperationSwitchGui). The base, the enclosure's first solid, is on New part, touching no other
        part: Add, Remove and Intersect are all offered, with no reason; chosen, each has an
        empty merge scope and goes red, "No merge scope selected", as Onshape's (ops#640 rank 3a,
        hands-on checks R7(a) and R8; TestMergeScopeGui covers the red row)."""
        self.enclosure()
        lid = pad(self.body, "Lid", self.lidSk, 5)
        self.doc.recompute()
        topSk = self.body.newObject("Sketcher::SketchObject", "TopSk")
        topSk.AttachmentSupport = [(lid, faceAt(lid, 15))]
        topSk.MapMode = "FlatFace"
        rect(topSk, 0, 0, 10, 10)
        pad(self.body, "Top", topSk, 5)
        self.doc.recompute()
        self.doc.openTransaction("Edit Lid")
        Gui.getDocument(self.doc.Name).setEdit(lid.Name)
        self.waitForPanel()
        combo = self.combo()
        self.assertIsNotNone(combo, "no Result box")
        self.assertEqual(self.items(combo), ROWS)
        self.assertEqual(combo.currentText(), "Add")
        model = combo.model()
        self.assertFalse(model.flags(model.index(0, 0)) & QtCore.Qt.ItemIsEnabled)
        self.assertIn("'TopSk' uses 'Lid'", combo.itemData(0, QtCore.Qt.ToolTipRole))
        self.close(ok=False)
        self.doc.openTransaction("Edit Base")
        Gui.getDocument(self.doc.Name).setEdit(self.base.Name)
        self.waitForPanel()
        combo = self.combo()
        model = combo.model()
        self.assertEqual(self.items(combo), ["New", "Add", "Remove", "Intersect"])
        self.assertEqual(combo.currentText(), "New")
        self.assertTrue(model.flags(model.index(1, 0)) & QtCore.Qt.ItemIsEnabled)
        self.assertFalse(combo.itemData(1, QtCore.Qt.ToolTipRole))
        for row in (2, 3):
            self.assertTrue(model.flags(model.index(row, 0)) & QtCore.Qt.ItemIsEnabled, row)
            self.assertFalse(combo.itemData(row, QtCore.Qt.ToolTipRole), row)

    def testIntersectWith(self):
        """Subtractive, in a studio with another part: a pocket of the lid sketch (5 deep by
        default) lists the four rows (ROWS) and opens on Remove from Enclosure. Intersect with:
        Operation Common, and the enclosure is the 30 x 30 x 5 that the tool and it share (4500; removing
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
        self.assertEqual(self.items(self.combo()), ROWS)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.choose("Intersect")
        self.assertEqual(pocket.Operation, "Common")
        self.assertFalse(pocket.Reversed)  # both cut: the tool stays in the material
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
        self.choose("New")
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
        self.assertTrue(model.flags(model.index(0, 0)) & QtCore.Qt.ItemIsEnabled)
        self.choose("New")
        part = lid.getParentGeoFeatureGroup()
        self.assertNotEqual(part, self.body)
        self.close(ok=True)
        self.assertIs(lid.getParentGeoFeatureGroup(), part)
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        # ops#630: the enclosure shows its new tip, not nothing
        self.assertEqual(shownFeatures(self.body), ["Base"])

    @siblingEraPath
    def testNewPartKeepsTheEnclosureShown(self):
        """ops#630, Onshape's New part: the parts the feature leaves stay shown. The Pad command
        hides the enclosure's tip for the pad; New part takes the pad away, and the enclosure
        shows its tip again, while the panel is open and after OK. The new Body shows the pad."""
        self.enclosure()
        self.assertEqual(shownFeatures(self.body), ["Base"])
        lid = self.lidPad()
        self.choose("New")
        self.assertEqual(shownFeatures(self.body), ["Base"])
        self.close(ok=True)
        part = lid.getParentGeoFeatureGroup()
        self.assertEqual(shownFeatures(self.body), ["Base"])
        self.assertEqual(shownFeatures(part), [lid.Name])
        self.assertTrue(self.body.Visibility)
        self.assertTrue(part.Visibility)

    @siblingEraPath
    def testAddToShowsWhatThePadPanelShowed(self):
        """ops#630: New part, then Add to Enclosure: the enclosure shows what the Pad's panel
        showed before the move (the edit's own choice), and after OK the pad alone."""
        self.enclosure()
        lid = self.lidPad()
        inPanel = shownFeatures(self.body)
        self.choose("New")
        self.choose("Add")
        self.assertEqual(shownFeatures(self.body), inPanel)
        self.close(ok=True)
        self.assertEqual(shownFeatures(self.body), [lid.Name])

    def testCancelAfterNewPartOfAnUnusedTip(self):
        """ops#630: an existing lid pad, the enclosure's shown tip, edited; New part shows the
        base in the enclosure, and Cancel puts the pad back as the shown feature, the base
        hidden, as before the edit."""
        self.enclosure()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        lid.Visibility = True
        self.assertEqual(shownFeatures(self.body), ["Lid"])
        lid.ViewObject.doubleClicked()
        self.waitForPanel()
        self.choose("New")
        self.assertEqual(shownFeatures(self.body), ["Base"])
        self.close(ok=False)
        self.doc.recompute()
        self.assertIs(lid.getParentGeoFeatureGroup(), self.body)
        self.assertEqual(shownFeatures(self.body), ["Lid"])

    def testRevolutionPanelNewPart(self):
        """PR 303 round 1, the panels the 2b tests didn't open: Revolution shows the box, and New
        part works there. The lid square (sketch x 0 to 30) turned about the sketch's V axis is a
        cylinder of radius 30 and height 30, alone in the new Body; the enclosure is 16000."""
        revolution = self.assertAdditiveBox("PartDesign_Revolution")
        self.chooseAxis("Vertical sketch axis")
        self.choose("New")
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

    @siblingEraPath
    def testTwoDocumentsKeepTheirOwnMoves(self):
        """PR 303 round 1: New part in document A's panel, then in document B's. Back in A, Add
        to Enclosure moves A's pad back, and B's stays in its new Body. One record for the open
        move was shared: B's replaced A's, so A's Add to did nothing while the box read Add to,
        and OK left the pad in the new Body."""
        self.enclosure()
        docA, bodyA = self.doc, self.body
        lidA = self.lidPad()
        self.choose("New")
        docB = models.newDocument("ResultBoxGuiB")
        docB.UndoMode = 1
        try:
            self.activate(docB)
            self.enclosure()
            bodyB = self.body
            lidB = self.lidPad()
            self.choose("New")
            partB = lidB.getParentGeoFeatureGroup()
            self.assertNotEqual(partB, bodyB)
            self.activate(docA)
            self.body = bodyA
            self.assertEqual(self.combo().currentText(), "New")
            self.choose("Add")
            self.assertIs(lidA.getParentGeoFeatureGroup(), bodyA)
            self.assertEqual(self.bodies(), ["Enclosure"])
            self.close(ok=True)
            self.assertIs(lidA.getParentGeoFeatureGroup(), bodyA)
            self.assertAlmostEqual(bodyA.Shape.Volume, 25000, places=3)
            self.activate(docB)
            self.assertIs(lidB.getParentGeoFeatureGroup(), partB)
            self.assertEqual(self.combo().currentText(), "New")
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

    @siblingEraPath
    def testOkBeforeTheMoveRuns(self):
        """PR 303 round 1: New part is chosen and OK is clicked before the queued move runs. OK
        commits the pad where it is, in the enclosure (25000), and the move then does nothing:
        it ran outside any transaction, so the pad sat in a new Body that no undo covered, and a
        panel opened again. One undo step removes the pad."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        lid = self.lidPad()
        self.combo().setCurrentIndex(self.combo().findText("New"))
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

    def parts(self):
        self.enclosure()
        self.below = self.part("Below", (0, 0, 40, 40), -10)
        self.far = self.part("Far", (100, 0, 140, 40), 0)

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

    @siblingEraPath
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
        # the Sides box is Onshape's Symmetric checkbox (rank 22)
        self.assertFalse(self.visible(QtWidgets.QCheckBox, "checkBoxSymmetric").isEnabled())
        self.visible(QtWidgets.QPushButton, "unlinkButton").click()
        self.assertTrue(
            waitFor(
                lambda: self.visible(QtWidgets.QLabel, "followsNote") is None
                and self.visible(QtWidgets.QCheckBox, "checkBoxSymmetric") is not None
                and self.visible(QtWidgets.QCheckBox, "checkBoxSymmetric").isEnabled()
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

    def testListedStudioOffersNoSiblingRows(self):
        """R0 lite (ops#654, notes/parts-design.md 10.11 row 10): once the studio has its history
        list, its studio features act on other parts, so an in-Body pocket's Result box offers no
        parts list and an in-Body pad's no merge list; without the list both are there (the
        sibling path is kept for such studios)."""
        self.parts()
        pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.lidSk
        pocket.Type = "ThroughAll"
        self.doc.recompute()
        padSk = self.body.newObject("Sketcher::SketchObject", "PadSk")
        padSk.AttachmentSupport = [(self.base, faceAt(self.base, 10))]
        padSk.MapMode = "FlatFace"
        rect(padSk, 0, 0, 5, 5)
        lidPad = self.body.newObject("PartDesign::Pad", "LidPad")
        lidPad.Profile = padSk
        lidPad.Length = 2
        self.doc.recompute()
        mergeList = lambda: self.visible(QtWidgets.QListWidget, "mergeList")  # noqa: E731
        self.edit(pocket)
        self.assertIsNotNone(self.partsList(), "unlisted: the parts list")
        self.close(ok=False)
        self.edit(lidPad)
        self.assertIsNotNone(mergeList(), "unlisted: the merge list")
        self.close(ok=False)
        self.assertIsNotNone(PartDesign.studioList(None, True))
        self.doc.recompute()
        self.edit(pocket)
        self.assertIsNotNone(self.combo(), "the Result box stays")
        self.assertIsNone(self.partsList(), "listed: no parts list")
        self.close(ok=False)
        self.edit(lidPad)
        self.assertIsNone(mergeList(), "listed: no merge list")
        self.close(ok=False)


class TestMergeGui(ResultBoxGuiCase):
    """Merge in the panel (ops#325, B+ Stage 1 session 3b; notes/bplus-stage1-design.md 2.5): an
    additive feature's Result box lists the studio's other parts under Merge with, unticked; a
    touching one left out gets a plain line, a ticked one the yellow banner, and OK merges it. The
    Merge's panel offers Accept; the tree marks an unaccepted Merge while it is held; the Merge
    Parts command merges after the fact. Designed geometry: the enclosure with its lid sketch
    (30 x 30 on its top; the pad's default length is 10), a part "Panel" 40 x 30 x 10 from
    (20, 0, 10), which the lid pad overlaps in 10 x 30 x 10, and a part "Far" (100 away)."""

    def parts(self):
        self.enclosure()
        self.panel = self.part("Panel", (20, 0, 60, 30), 10)
        self.far = self.part("Far", (100, 0, 140, 40), 0)

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
        the plain line "Touches Panel (not merged)". Panel ticked: the line goes (no banner:
        Onshape's merge is a plain feature, ops#640 rank 1). OK: a Merge right after the pad, the
        Enclosure's Tip, fuses Panel's pad (16000 + 9000 + 12000 - 3000 = 34000); Panel is hidden
        and merged, and the Merge is accepted, with no Warning (P50). One undo step removes the
        Merge. The lid pad is edited: made by the command it would open as New, as it touches the
        Enclosure and Panel (hands-on check A-1)."""
        self.parts()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        before = sorted(o.Name for o in self.doc.Objects)
        lid.ViewObject.doubleClicked()
        self.waitForPanel()
        self.assertEqual(self.mergeItems(), [("Panel", False), ("Far (doesn't touch)", False)])
        note = self.visible(QtWidgets.QLabel, "mergeNote")
        self.assertIsNotNone(note, "no plain line")
        self.assertEqual(note.text(), "Touches Panel (not merged)")
        self.visible(QtWidgets.QListWidget, "mergeList").item(0).setCheckState(QtCore.Qt.Checked)
        self.assertIsNone(self.visible(QtWidgets.QLabel, "mergeNote"))
        self.close(ok=True)
        merge = self.panel.MergedInto
        self.assertIsNotNone(merge)
        group = self.body.Group
        self.assertEqual(group.index(merge), group.index(lid) + 1)
        self.assertIs(self.body.Tip, merge)
        self.assertFalse(self.panel.Visibility)
        self.assertTrue(merge.MergeAccepted)
        self.assertNotIn("Warning", merge.State)
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


class TestOperationRowGui(ResultBoxGuiCase):
    """One Extrude, Onshape's (ops#640, ops#646; the blind findings F1, F11, F12 and the user's
    report 15): a Pad's or a Pocket's Result box offers New part, Add, Remove and Intersect at its
    creation and at every edit, and a change keeps the feature. Between adding and cutting the
    tool flips into the material or out of it. Designed geometry: the enclosure 40 x 40 x 10
    (16000) with its lid sketch, 30 x 30 on its top face; in a studio, TestSiblingsGui's Below
    (40 x 40 x 10 under the enclosure) and Far (100 away)."""

    def openEdit(self, feature):
        """Opens feature's edit as a double click does. self.undos is the undo count before it: with
        the edit open, its pending transaction is listed first (Document::getAvailableUndoNames),
        so a count taken then is one too high."""
        self.assertFalse(self.doc.HasPendingTransaction)
        self.undos = len(self.doc.UndoNames)
        feature.ViewObject.doubleClicked()
        self.waitForPanel()

    def editLid(self, length=10):
        lid = pad(self.body, "Lid", self.lidSk, length)
        self.doc.recompute()
        self.openEdit(lid)
        return lid

    def assertOneUndoStep(self, volume):
        """The dialog closed: its work is one undo step (counted from self.undos), and undoing it
        gives the enclosure `volume`."""
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(len(self.doc.UndoNames), self.undos + 1, self.doc.UndoNames)
        self.doc.undo()
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, volume, places=3)

    def assertValid(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    def studio(self):
        self.enclosure()
        self.below = self.part("Below", (0, 0, 40, 40), -10)
        self.far = self.part("Far", (100, 0, 140, 40), 0)

    def previewColour(self, obj):
        return tuple(round(c, 3) for c in obj.ViewObject.PreviewColor[:3])

    def modeCombo(self):
        """The open panel's end type box (side 1)."""
        box = self.visible(QtWidgets.QComboBox, "changeMode")
        self.assertIsNotNone(box, "no end type box")
        return box

    def chooseMode(self, text):
        """Chooses `text` in the end type box as a user does; the panel sets Type and
        recomputes."""
        box = self.modeCombo()
        index = self.items(box).index(text)
        box.setCurrentIndex(index)
        self.assertTrue(waitFor(lambda: self.modeCombo().currentText() == text))
        pump(0.3)

    def testAnAddPadBecomesAHole(self):
        """F11: the lid pad, 10 up (25000), edited: on Add to Enclosure; Remove from Enclosure
        makes it a cut through the enclosure, the same feature reversed (7000). One undo step
        brings the boss back."""
        self.enclosure()
        lid = self.editLid()
        self.assertEqual(self.items(self.combo()), ROWS)
        self.assertEqual(self.combo().currentText(), "Add")
        self.choose("Remove")
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertTrue(lid.Reversed)
        self.assertIs(Gui.getDocument(self.doc.Name).getInEdit().Object, lid)
        self.close(ok=True)
        self.assertIn(lid, self.body.Group)
        self.assertIs(self.body.Tip, lid)
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.assertOneUndoStep(25000)
        self.assertEqual(lid.Operation, "Union")
        self.assertFalse(lid.Reversed)

    def testAPocketBecomesABoss(self):
        """A pocket of the lid sketch, 5 deep (11500), edited: Add to Enclosure flips it out of the
        material and puts the 30 x 30 x 5 plate on top instead (20500)."""
        self.enclosure()
        pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.lidSk
        pocket.Length = 5
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 11500, places=3)
        self.openEdit(pocket)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.choose("Add")
        self.assertEqual(pocket.Operation, "Union")
        self.assertTrue(pocket.Reversed)
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 20500, places=3)
        self.assertAlmostEqual(self.body.Shape.BoundBox.ZMax, 15, places=6)

    def testIntersectKeepsWhatTheyShare(self):
        """The lid pad, Intersect with Enclosure: the tool goes into the enclosure, which keeps
        the 30 x 30 x 10 they share (9000)."""
        self.enclosure()
        lid = self.editLid()
        self.choose("Intersect")
        self.assertEqual(lid.Operation, "Common")
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 9000, places=3)

    def testThePadsCommandOffersEveryRow(self):
        """At creation too: the Pad command's box has the four rows on Add to Enclosure, and
        Remove from Enclosure flips the tool and, after OK, cuts (7000). One undo step removes
        the pad (16000)."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        self.undos = len(self.doc.UndoNames)
        lid = self.lidPad()
        self.assertEqual(self.items(self.combo()), ROWS)
        self.choose("Remove")
        self.assertTrue(lid.Reversed)
        self.close(ok=True)
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.assertOneUndoStep(16000)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)

    @siblingEraPath
    def testANewPartGoesBackToAdd(self):
        """F12 and report 15: the lid pad made a new part and committed. Its edit is on New part,
        and Add to Enclosure (the part it touches) moves the pad and its sketch into the
        enclosure, where they were, and the new Body goes: one part, 25000, in one undo step."""
        self.enclosure()
        group = self.body.Group
        lid = self.lidPad()
        self.choose("New")
        self.close(ok=True)
        part = lid.getParentGeoFeatureGroup()
        self.assertNotEqual(part, self.body)
        partName = part.Name
        self.openEdit(lid)
        combo = self.combo()
        self.assertEqual(self.items(combo), ROWS)
        self.assertEqual(combo.currentText(), "New")
        self.assertIsNone(self.visible(QtWidgets.QListWidget, "mergeList"))
        self.choose("Add")
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertEqual(self.combo().currentText(), "Add")
        self.close(ok=True)
        self.assertEqual(self.body.Group, group + [lid])
        self.assertIs(self.body.Tip, lid)
        self.assertAlmostEqual(self.body.Shape.Volume, 25000, places=3)
        self.assertValid()
        self.assertOneUndoStep(16000)
        self.assertIsNotNone(self.doc.getObject(partName))
        self.assertAlmostEqual(self.doc.getObject(partName).Shape.Volume, 9000, places=3)

    @siblingEraPath
    def testCancelLeavesTheNewPart(self):
        """The same move, then Cancel: the new part is as it was (9000), the enclosure 16000, and
        no undo step."""
        self.enclosure()
        lid = self.lidPad()
        self.choose("New")
        self.close(ok=True)
        part = lid.getParentGeoFeatureGroup()
        self.openEdit(lid)
        self.choose("Add")
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(sorted(self.bodies()), sorted(["Enclosure", part.Name]))
        self.assertIs(lid.getParentGeoFeatureGroup(), part)
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertEqual(len(self.doc.UndoNames), self.undos, self.doc.UndoNames)

    @siblingEraPath
    def testANewPartBecomesAHole(self):
        """The lid as a new part, edited: Remove from Enclosure moves it into the enclosure as a
        cut through it (7000), the tool flipped, and the new Body goes."""
        self.enclosure()
        lid = self.lidPad()
        self.choose("New")
        self.close(ok=True)
        self.openEdit(lid)
        self.choose("Remove")
        self.close(ok=True)
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertTrue(lid.Reversed)
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)

    def testCancelAfterASwitchRestoresTheBoss(self):
        """The dialog's transaction holds the switch too (extrude-design.md): the lid pad (25000)
        edited, Remove from Enclosure (Operation, Reversed and a restart of the edit), then
        Cancel: Union, not reversed, 25000 again, and no undo step."""
        self.enclosure()
        lid = self.editLid()
        self.choose("Remove")
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertTrue(lid.Reversed)
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(lid.Operation, "Union")
        self.assertFalse(lid.Reversed)
        self.assertIs(self.body.Tip, lid)
        self.assertAlmostEqual(self.body.Shape.Volume, 25000, places=3)
        self.assertValid()
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(len(self.doc.UndoNames), self.undos, self.doc.UndoNames)

    def testASecondSwitchMakesItANewPart(self):
        """Two switches in one dialog: the lid pad edited, Remove from Enclosure (reversed), then
        New part: adding again, so the tool flips back, and the pad and its sketch go to a new
        Body, the dialog on it. OK: the lid alone (9000), the enclosure 16000; one undo step
        takes it all back (25000, one part)."""
        self.enclosure()
        lid = self.editLid()
        self.choose("Remove")
        self.assertTrue(lid.Reversed)
        self.choose("New")
        self.assertEqual(lid.Operation, "Union")
        self.assertFalse(lid.Reversed)
        part = lid.getParentGeoFeatureGroup()
        self.assertNotEqual(part, self.body)
        self.assertEqual(part.Group, [self.lidSk, lid])
        self.assertIs(Gui.getDocument(self.doc.Name).getInEdit().Object, lid)
        self.assertEqual(self.combo().currentText(), "New")
        self.close(ok=True)
        partName = part.Name
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)
        self.assertIs(self.body.Tip, self.base)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertValid()
        self.assertOneUndoStep(25000)
        self.assertIsNone(self.doc.getObject(partName))
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertEqual(lid.Operation, "Union")

    @siblingEraPath
    def testNewPartThenRemoveInTheSameDialog(self):
        """The creation dialog: New part, then Remove from Enclosure takes this dialog's move back
        and cuts: the pad and its sketch are in the enclosure again, the tool flipped. OK: 7000;
        one undo step removes the pad (16000)."""
        self.enclosure()
        before = sorted(o.Name for o in self.doc.Objects)
        self.undos = len(self.doc.UndoNames)
        lid = self.lidPad()
        self.choose("New")
        self.assertEqual(len(self.bodies()), 2)
        self.choose("Remove")
        self.assertEqual(self.bodies(), ["Enclosure"])
        self.assertIn(lid, self.body.Group)
        self.assertIn(self.lidSk, self.body.Group)
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertTrue(lid.Reversed)
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.assertValid()
        self.assertOneUndoStep(16000)
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)

    def testToLastFlipsToo(self):
        """D2 of the review (gui-1): every end bound to the direction flips, a Pad's To last too.
        A pad of a 30 x 30 square sketched 5 up inside the enclosure, To last: up to the top face,
        adding nothing (16000). Remove from Enclosure flips it: it cuts down to the bottom face,
        the lower 5 (11500), and the material above the sketch stays. Unflipped it cut the upper
        5."""
        self.enclosure()
        midSk = sketch(self.body, "MidSk", xyPlane(self.body), (0, 0, 30, 30), z=5)
        lid = pad(self.body, "Lid", midSk, 10)
        lid.Type = "UpToLast"
        self.doc.recompute()
        self.assertTrue(lid.isValid(), lid.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.openEdit(lid)
        self.choose("Remove")
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertEqual(lid.Type, "UpToLast")
        self.assertTrue(lid.Reversed)
        self.close(ok=True)
        self.assertTrue(lid.isValid(), lid.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 11500, places=3)
        self.assertTrue(self.body.Shape.isInside(V(15, 15, 7.5), 1e-6, True))
        self.assertFalse(self.body.Shape.isInside(V(15, 15, 2.5), 1e-6, True))

    def testAPadThroughAllCutsThroughWhenRemoving(self):
        """D1 of the review: one end-type list for Pad and Pocket, Onshape's. The lid pad, 5 up
        (20500), edited: its end type box offers Through all after Up to shape; chosen, Type is
        ThroughAll. Remove from Enclosure flips it and it cuts through the enclosure (7000; 5 deep
        it would leave 11500). The restarted panel shows Through all again."""
        self.enclosure()
        lid = self.editLid(length=5)
        self.assertEqual(
            self.items(self.modeCombo()),
            # Onshape's words (rank 22); Up to last stays in the box, hidden
            [
                "Blind",
                "Up to last",
                "Up to next",
                "Up to face",
                "Up to part",
                "Up to vertex",
                "Through all",
            ],
        )
        self.chooseMode("Through all")
        self.assertEqual(lid.Type, "ThroughAll")
        self.choose("Remove")
        self.assertEqual(lid.Operation, "Subtraction")
        self.assertEqual(lid.Type, "ThroughAll")
        self.assertTrue(lid.Reversed)
        self.assertEqual(self.modeCombo().currentText(), "Through all")
        self.close(ok=True)
        self.assertEqual(lid.Type, "ThroughAll")
        self.assertTrue(lid.isValid(), lid.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.assertFalse(self.body.Shape.isInside(V(15, 15, 0.5), 1e-6, True))

    def testAPocketToLastAddsUpToTheLastFace(self):
        """D1 of the review: a Pocket's end type box offers To last after Up to shape. A pocket, 2
        deep (14200), of a 30 x 30 square sketched 5 up inside the enclosure (testToLastFlipsToo's
        profile, its centre strictly inside the footprint): To last cuts down to the bottom face,
        the lower 5 under the square (11500). Add to Enclosure flips it: it adds up to the top
        face, adding nothing (16000), and the material under the sketch is back. The restarted
        panel shows To last again."""
        self.enclosure()
        midSk = sketch(self.body, "MidSk", xyPlane(self.body), (0, 0, 30, 30), z=5)
        pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = midSk
        pocket.Length = 2
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 14200, places=3)
        self.openEdit(pocket)
        self.assertEqual(
            self.items(self.modeCombo()),
            # Onshape's order (rank 22): Up to last, which it hasn't, at the end
            [
                "Blind",
                "Up to next",
                "Up to face",
                "Up to part",
                "Up to vertex",
                "Through all",
                "Up to last",
            ],
        )
        self.chooseMode("Up to last")
        self.assertEqual(pocket.Type, "UpToLast")
        # The panel recomputes the feature alone: during the edit the Body's Shape is the one of
        # the last document recompute, and the result is the tip's, the pocket's own Shape
        self.assertAlmostEqual(pocket.Shape.Volume, 11500, places=3)
        self.assertTrue(pocket.Shape.isInside(V(15, 15, 7.5), 1e-6, True))
        self.assertFalse(pocket.Shape.isInside(V(15, 15, 2.5), 1e-6, True))
        self.choose("Add")
        self.assertEqual(pocket.Operation, "Union")
        self.assertEqual(pocket.Type, "UpToLast")
        self.assertTrue(pocket.Reversed)
        self.assertEqual(self.modeCombo().currentText(), "Up to last")
        self.close(ok=True)
        self.assertEqual(pocket.Type, "UpToLast")
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertTrue(self.body.Shape.isInside(V(15, 15, 7.5), 1e-6, True))
        self.assertTrue(self.body.Shape.isInside(V(15, 15, 2.5), 1e-6, True))

    def testAPadThroughAllOpensOnThroughAll(self):
        """A Pad whose Type is ThroughAll (Type index 6), cutting through the enclosure (7000),
        opens with its end type box on Through all and the taper shown, as a Pocket's Through
        all; OK writes it back unchanged."""
        self.enclosure()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        lid.Type = "ThroughAll"
        lid.Operation = "Subtraction"
        lid.Reversed = True
        self.doc.recompute()
        self.assertTrue(lid.isValid(), lid.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.openEdit(lid)
        self.assertEqual(self.modeCombo().currentText(), "Through all")
        # the taper is Onshape's Draft: offered, its angle shown once ticked (rank 22)
        draft = self.visible(QtWidgets.QCheckBox, "checkBoxDraft")
        self.assertIsNotNone(draft, "no Draft box")
        draft.setChecked(True)
        pump(0.2)
        self.assertIsNotNone(self.visible(QtWidgets.QWidget, "taperEdit"), "no taper")
        self.assertIsNone(self.visible(QtWidgets.QWidget, "lengthEdit"))
        self.assertIsNone(self.visible(QtWidgets.QWidget, "offsetEdit"))
        self.close(ok=True)
        self.assertEqual(lid.Type, "ThroughAll")
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)

    def testThePreviewColourFollowsTheOperation(self):
        """D5 of the review (gui-3): the preview takes the colour of what the feature does now. The
        lid pad previews in the adding colour (a Pad's); Remove from Enclosure: in the cutting
        colour (a Pocket's); Add to Enclosure: the adding colour again. It was set once, from the
        class, when the view provider attached."""
        self.enclosure()
        reference = self.doc.addObject("PartDesign::Pocket", "ReferencePocket")
        cutting = self.previewColour(reference)
        self.doc.removeObject(reference.Name)
        lid = self.editLid()
        adding = self.previewColour(lid)
        self.assertNotEqual(adding, cutting)
        self.choose("Remove")
        self.assertEqual(self.previewColour(lid), cutting)
        self.choose("Add")
        self.assertEqual(self.previewColour(lid), adding)
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 25000, places=3)

    def statusMessage(self):
        return Gui.getMainWindow().statusBar().currentMessage()

    def testAnAddThatTouchesNothingStaysANewPart(self):
        """ops#640 H2 and rank 3a (hands-on checks R7(a) and R8): Onshape's Add that touches
        nothing has an empty merge scope, red, "No merge scope selected", until Merge with all,
        which makes it a new part, healthy. Far, a part of its own 100 away from the enclosure,
        edited: on New part; Add is offered and, chosen, leaves Far's pad where it is, red; Merge
        with all ticked: valid. OK: Far still holds its 16000, the enclosure its 16000, both
        valid, one Body each, Far's pad MergeWithAll."""
        self.studio()
        farPad = self.doc.getObject("FarPad")
        self.openEdit(farPad)
        combo = self.combo()
        self.assertEqual(combo.currentText(), "New")
        model = combo.model()
        self.assertTrue(model.flags(model.index(1, 0)) & QtCore.Qt.ItemIsEnabled)
        self.choose("Add")
        self.assertTrue(farPad.EmptyMergeScope)
        self.assertFalse(farPad.isValid())
        self.assertIn("No merge scope selected", farPad.getStatusString())
        self.assertIs(farPad.getParentGeoFeatureGroup(), self.far)
        self.assertEqual(farPad.Operation, "Union")
        self.assertFalse(farPad.Reversed)
        box = self.visible(QtWidgets.QCheckBox, "mergeWithAll")
        self.assertIsNotNone(box, "no Merge with all")
        box.click()
        self.assertTrue(waitFor(lambda: farPad.isValid()), farPad.getStatusString())
        self.close(ok=True)
        self.assertTrue(farPad.MergeWithAll)
        self.assertIs(farPad.getParentGeoFeatureGroup(), self.far)
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertEqual(self.bodies(), ["Below", "Enclosure", "Far"])
        self.assertValid()

    def testARemoveOfNothingIsNotOffered(self):
        """ops#640 rank 3a (hands-on checks R7(a) and R8): a new part's feature touching no other
        part may become a Remove or an Intersect, as in Onshape, where its empty merge scope makes
        it red, "No merge scope selected"
        (TestMergeScopeGui.testARemoveFromNewTouchingNothingIsRed). Far's pad, its part's first solid, edited: Add, Remove and Intersect offered, with no
        reason. Cancel: Far unchanged, 16000, valid. (The name is from before rank 3a.)"""
        self.studio()
        farPad = self.doc.getObject("FarPad")
        self.openEdit(farPad)
        combo = self.combo()
        self.assertEqual(combo.currentText(), "New")
        model = combo.model()
        self.assertTrue(model.flags(model.index(1, 0)) & QtCore.Qt.ItemIsEnabled)
        for row in (2, 3):
            self.assertTrue(model.flags(model.index(row, 0)) & QtCore.Qt.ItemIsEnabled, row)
            self.assertFalse(combo.itemData(row, QtCore.Qt.ToolTipRole), row)
        self.close(ok=False)
        self.assertEqual(farPad.Operation, "Union")
        self.assertAlmostEqual(self.far.Shape.Volume, 16000, places=3)
        self.assertValid()

    def testAPocketThatMissesKeepsThePart(self):
        """ops#640 H3 (hands-on checks R5 and R7): Onshape's Remove or Intersect that touches
        nothing is healthy, with the info "Selected tools and targets do not intersect", and
        changes no geometry. A pocket of a 10 x 10 square at x 100, beside the enclosure, 5 deep
        from z 10, edited: Remove from Enclosure, valid, with the note, the enclosure 16000;
        Intersect with Enclosure the same (an empty common failed before H3)."""
        self.enclosure()
        farSk = sketch(self.body, "FarSk", xyPlane(self.body), (100, 0, 110, 10), z=10)
        miss = self.body.newObject("PartDesign::Pocket", "Miss")
        miss.Profile = farSk
        miss.Length = 5
        self.doc.recompute()
        self.openEdit(miss)
        self.assertEqual(self.combo().currentText(), "Remove")
        self.assertTrue(miss.isValid(), miss.getStatusString())
        self.assertIn("Selected tools and targets do not intersect", miss.getStatusString())
        self.choose("Intersect")
        self.assertEqual(miss.Operation, "Common")
        self.close(ok=True)
        self.assertTrue(miss.isValid(), miss.getStatusString())
        self.assertIn("Selected tools and targets do not intersect", miss.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)

    def reversedBox(self):
        box = self.visible(QtWidgets.QCheckBox, "checkBoxReversed")
        self.assertIsNotNone(box, "no Reversed box")
        return box

    def testTheUsersFlipWinsOverTheSwitch(self):
        """ops#640 H4 (hands-on check R5): a switch between Add and Remove flips the direction
        only while the user hasn't flipped it in the dialog; after, every switch keeps the user's.
        The lid pad edited: Remove flips it (Reversed), Add flips it back; the user flips it
        (Reversed), Remove keeps it, the user flips it back, Add keeps it. The memory is the
        dialog's: OK, a new edit, and Remove flips again."""
        self.enclosure()
        lid = self.editLid()
        self.choose("Remove")
        self.assertTrue(lid.Reversed)
        self.choose("Add")
        self.assertFalse(lid.Reversed)
        self.reversedBox().click()
        pump(0.3)
        self.assertTrue(lid.Reversed)
        self.choose("Remove")
        self.assertTrue(lid.Reversed, "the switch flipped the user's direction")
        self.reversedBox().click()
        pump(0.3)
        self.assertFalse(lid.Reversed)
        self.choose("Add")
        self.assertFalse(lid.Reversed, "the switch flipped the user's direction")
        self.assertTrue(self.reversedBox().isChecked() == lid.Reversed)
        self.close(ok=True)
        self.openEdit(lid)
        self.choose("Remove")
        self.assertTrue(lid.Reversed, "a new dialog keeps the last one's memory")
        self.close(ok=False)

    def testLeavingACutDropsItsSiblings(self):
        """In a studio: a pocket of the lid sketch, 20 deep, removes from the enclosure and, by a
        sibling, from Below (7000 each). Edited, Add to Enclosure: the sibling goes and Below is
        whole (16000), the box shows Merge with instead of the parts list, and the tool, flipped,
        puts a 30 x 30 x 20 block on top (16000 + 18000). One undo step brings the cut and its
        sibling back."""
        self.studio()
        pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.lidSk
        pocket.Length = 20
        self.doc.recompute()
        [sibling] = PartDesign.makeSiblings(pocket, [self.below])
        self.doc.recompute()
        siblingName = sibling.Name
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.assertAlmostEqual(self.below.Shape.Volume, 7000, places=3)
        self.openEdit(pocket)
        self.assertIsNotNone(self.partsList(), "no parts list")
        self.choose("Add")
        self.assertEqual(pocket.Operation, "Union")
        self.assertTrue(pocket.Reversed)
        self.assertEqual(PartDesign.siblingsOf(pocket), [])
        self.assertIsNone(self.doc.getObject(siblingName))
        self.assertIsNone(self.partsList())
        self.assertIsNotNone(self.visible(QtWidgets.QListWidget, "mergeList"), "no Merge with")
        self.close(ok=True)
        self.assertAlmostEqual(self.below.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 34000, places=3)
        self.assertValid()
        self.assertOneUndoStep(7000)
        self.assertIsNotNone(self.doc.getObject(siblingName))
        self.assertAlmostEqual(self.below.Shape.Volume, 7000, places=3)

    def testRemoveInAStudioListsTheParts(self):
        """In a studio: the lid pad's edit shows Merge with; Remove from Enclosure rebuilds the box
        with the parts list, the enclosure ticked and fixed, Below and Far unticked. OK: the
        enclosure is cut (7000), Below untouched (16000), no sibling made."""
        self.studio()
        lid = self.editLid()
        self.assertIsNotNone(self.visible(QtWidgets.QListWidget, "mergeList"), "no Merge with")
        self.assertIsNone(self.partsList())
        self.choose("Remove")
        self.assertIsNone(self.visible(QtWidgets.QListWidget, "mergeList"))
        items = self.partItems()
        self.assertEqual(items[0], ("Enclosure", True, False))
        names = [text.split(" (")[0] for text, _, _ in items]
        self.assertEqual(names, ["Enclosure", "Below", "Far"])
        self.assertEqual([ticked for _, ticked, _ in items], [True, False, False])
        self.close(ok=True)
        self.assertAlmostEqual(self.body.Shape.Volume, 7000, places=3)
        self.assertAlmostEqual(self.below.Shape.Volume, 16000, places=3)
        self.assertEqual(PartDesign.siblingsOf(lid), [])


class TestOperationRefusalGui(ResultBoxGuiCase):
    """The rows the Result box refuses (ops#640, review finding tests-4): each greyed, with its
    reason as the tooltip. Onshape greys none (it does the moves FreeCAD-CH refuses), so the
    refusal and its reason are what the user sees; a refused row that came back enabled would make
    the switch throw inside the edit's restart, a silent no-op. Designed geometry: the enclosure
    (16000) with its lid sketch; Panel (40 x 30 x 10 from (20, 0, 10), overlapping the lid pad)
    and Below (under the enclosure)."""

    def newLid(self):
        """The lid pad, 10 up, made a part of its own from Python: (the pad, its part)."""
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        part = PartDesign.newPartFrom(lid)
        self.doc.recompute()
        self.assertAlmostEqual(part.Shape.Volume, 9000, places=3)
        return lid, part

    def openEdit(self, feature):
        feature.ViewObject.doubleClicked()
        self.waitForPanel()
        combo = self.combo()
        self.assertIsNotNone(combo, "no Result box")
        self.assertEqual(self.items(combo), ROWS)
        return combo

    def rows(self, combo):
        """(enabled, tooltip) of each row"""
        model = combo.model()
        return [
            (
                bool(model.flags(model.index(i, 0)) & QtCore.Qt.ItemIsEnabled),
                combo.itemData(i, QtCore.Qt.ToolTipRole) or "",
            )
            for i in range(combo.count())
        ]

    def assertAddRowsRefused(self, lid, why):
        """The new part's edit, on New part: Add, Remove and Intersect greyed, each with a tooltip
        that holds `why`, compared in lower case: the box shows PartDesign.addToPart's own reason
        (Body::addToPartRefusal, its first letter raised), so the two can't drift."""
        combo = self.openEdit(lid)
        self.assertEqual(combo.currentText(), "New")
        rows = self.rows(combo)
        for enabled, tip in rows[1:]:
            self.assertFalse(enabled, rows)
            self.assertTrue(tip, rows)
            self.assertIn(why, tip.lower(), rows)
        # round 9: the reason shows under the row too
        note = self.visible(QtWidgets.QLabel, "refusalNote")
        self.assertIsNotNone(note, "no refusal line")
        text = note.text().lower()
        self.assertTrue(text.startswith("can't switch to add, remove or intersect: "), text)
        self.assertIn(why, text)
        self.close(ok=False)

    def testANewPartThatSomethingUses(self):
        """A binder of the lid pad in the enclosure uses it from outside its part: it can't go into
        the enclosure (round 9: what uses it inside its part goes along instead)."""
        self.enclosure()
        lid, part = self.newLid()
        binder = self.body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(lid, ("",))]
        self.doc.recompute()
        self.assertAddRowsRefused(lid, "'binder' uses 'lid'")

    def testANewPartWithMoreFeatures(self):
        """Round 9 (journeys J8, J17): a second sketch in the new part, on its own plane, and a
        sketch on the lid's top no longer hold the switch: Add, Remove and Intersect are offered,
        and Add takes both along into the enclosure (25000); the new part goes."""
        self.enclosure()
        lid, part = self.newLid()
        loose = sketch(part, "LooseSk", xyPlane(part), (0, 0, 5, 5))
        topSk = part.newObject("Sketcher::SketchObject", "TopSk")
        topSk.AttachmentSupport = [(lid, faceAt(lid, 20))]
        topSk.MapMode = "FlatFace"
        rect(topSk, 0, 0, 10, 10)
        self.doc.recompute()
        partName = part.Name
        combo = self.openEdit(lid)
        self.assertEqual(combo.currentText(), "New")
        rows = self.rows(combo)
        self.assertTrue(all(enabled for enabled, tip in rows), rows)
        self.choose("Add")
        self.close(ok=True)
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(partName))
        self.assertEqual(self.body.Group[-4:], [self.lidSk, lid, loose, topSk])
        self.assertAlmostEqual(self.body.Shape.Volume, 25000, places=3)

    def testARolledBackTarget(self):
        """The enclosure rolled back to its base (a corner cut after it): the lid can't go in
        until the enclosure is rolled to its end."""
        self.enclosure()
        lid, part = self.newLid()
        cornerSk = sketch(self.body, "CornerSk", xyPlane(self.body), (35, 35, 40, 40))
        corner = self.body.newObject("PartDesign::Pocket", "Corner")
        corner.Profile = cornerSk
        corner.Type = "ThroughAll"
        corner.Reversed = True
        self.doc.recompute()
        self.body.Tip = self.base
        self.doc.recompute()
        self.assertAddRowsRefused(lid, "roll 'enclosure' to the end first")

    def testANewPartABooleanUses(self):
        """D6 of the review: a Boolean in the enclosure fuses the lid's part (its tool is that
        Body). Add would delete the Body under the Boolean, which would then go red: refused,
        with a reason."""
        self.enclosure()
        lid, part = self.newLid()
        fuse = self.doc.addObject("PartDesign::Boolean", "Fuse")
        self.body.addObject(fuse)
        fuse.setObjects([part])
        self.doc.recompute()
        self.assertTrue(fuse.isValid(), fuse.getStatusString())
        self.assertAddRowsRefused(lid, "which add to part would remove")

    def testAMergeAfterTheFeature(self):
        """The lid pad merged with Panel (the Merge right after it, nothing built on it): every row
        is offered, as Onshape's (hands-on B5-4: the switch drops the Merge, ops#640 round 5;
        TestMergedSwitchGui)."""
        self.enclosure()
        lid = pad(self.body, "Lid", self.lidSk, 10)
        self.doc.recompute()
        panel = self.part("Panel", (20, 0, 60, 30), 10)
        merge = PartDesign.makeMerge(lid, [panel])
        self.doc.recompute()
        self.assertTrue(merge.isValid(), merge.getStatusString())
        combo = self.openEdit(lid)
        self.assertEqual(combo.currentText(), "Add")
        rows = self.rows(combo)
        for enabled, tip in rows:
            self.assertTrue(enabled, rows)
        # No refusal: each row's tooltip is the part it acts on (round 6)
        self.assertEqual(
            [tip for _, tip in rows],
            ["", "Add to Enclosure", "Remove from Enclosure", "Intersect with Enclosure"],
        )

    def testACutWithSiblings(self):
        """A pocket of the lid sketch, 20 deep, with a sibling in Below: New part and Add are
        offered (the switch drops the sibling, ops#640 round 5). A sketch on the sibling's cut face
        uses it: both are refused, naming the user."""
        self.enclosure()
        below = self.part("Below", (0, 0, 40, 40), -10)
        pocket = self.body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self.lidSk
        pocket.Length = 20
        self.doc.recompute()
        [sibling] = PartDesign.makeSiblings(pocket, [below])
        self.doc.recompute()
        combo = self.openEdit(pocket)
        self.assertEqual(combo.currentText(), "Remove")
        rows = self.rows(combo)
        self.assertTrue(rows[0][0], rows)
        self.assertTrue(rows[1][0], rows)
        self.close(ok=False)
        userSk = below.newObject("Sketcher::SketchObject", "UserSk")
        userSk.AttachmentSupport = [(sibling, faceAt(sibling, 0))]
        userSk.MapMode = "FlatFace"
        rect(userSk, 32, 32, 38, 38)
        self.doc.recompute()
        self.assertTrue(userSk.isValid(), userSk.getStatusString())
        combo = self.openEdit(pocket)
        rows = self.rows(combo)
        for row in rows[:2]:
            self.assertFalse(row[0], rows)
            self.assertIn("is used by UserSk", row[1])


class TestOkInErrorGui(ResultBoxGuiCase):
    """F7 of the blind test (ops#640): OK commits a feature in error, as Onshape's check does; it
    stays in error, to be repaired later. Designed geometry: the enclosure (16000) and its lid
    sketch."""

    @siblingEraPath
    def testOkCommitsAPadInError(self):
        """The Pad command on the lid sketch, its length set to 0 (no pad of length zero): OK
        closes the dialog with no message box, the pad stays, in error, saying why, and the
        enclosure keeps its 16000 (the failed pad passes its base through). One undo step removes
        it; editing it again and setting 10 repairs it (25000)."""
        self.enclosure()
        undos = len(self.doc.UndoNames)
        lid = self.lidPad()
        self.lengthField().setProperty("rawValue", 0.0)
        pump(0.3)
        self.assertFalse(lid.isValid())
        self.assertEqual(self.modalsDuring(lambda: self.close(ok=True)), [])
        self.assertIn(lid, self.body.Group)
        self.assertFalse(lid.isValid())
        self.assertIn("length of zero", lid.getStatusString())
        self.assertAlmostEqual(lid.Shape.Volume, 16000, places=3)
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertEqual(len(self.doc.UndoNames), undos + 1, self.doc.UndoNames)
        lid.ViewObject.doubleClicked()
        self.waitForPanel()
        self.lengthField().setProperty("rawValue", 10.0)
        pump(0.3)
        self.close(ok=True)
        self.assertTrue(lid.isValid(), lid.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 25000, places=3)


class TestRevolveAxisGui(ResultBoxGuiCase):
    """Report 12 (ops#643): Revolve and Groove open waiting for their axis, as Onshape's Revolve
    does: no axis is set, the axis row shows armed and red, and the feature says what it needs, in
    Onshape's words. OK stays enabled, and Enter or OK commits the feature in error (hands-on check
    R6, ops#640 H1). Designed geometry: the enclosure and its lid sketch, the square from x 0 to
    30."""

    def axisField(self):
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = [
            w
            for w in Gui.getMainWindow().findChildren(QtWidgets.QWidget, "fieldReferenceAxis")
            if w.isVisible()
        ]
        return found[0] if found else None

    def assertWaitsForTheAxis(self, feature):
        """No axis, the row armed and shown missing (red), the feature in error with Onshape's
        words, and OK enabled with a hint as its tooltip (hands-on check R6, ops#640 H1: Onshape's
        check mark stays enabled with the axis field empty; round 1's D4 disabled OK)."""
        self.assertIsNone(feature.ReferenceAxis)
        self.assertTrue(
            waitFor(lambda: self.axisField() is not None and self.axisField().property("armed")),
            "the axis row isn't armed",
        )
        self.assertTrue(self.axisField().property("missing"), "the axis row isn't shown missing")
        self.assertFalse(feature.isValid())
        self.assertIn(AXIS_MISSING, feature.getStatusString())
        ok = QtWidgets.QDialogButtonBox.Ok
        self.assertTrue(
            waitFor(lambda: "pick a line or an edge" in taskButton(ok).toolTip().lower()),
            "OK's tooltip gives no hint",
        )
        self.assertTrue(taskButton(ok).isEnabled(), "OK is disabled")

    def testRevolutionWaitsForItsAxis(self):
        """The Revolution command on the lid sketch: no axis, the row armed, and the feature says
        what it needs. The sketch's V axis chosen: valid, and OK keeps the axis."""
        self.enclosure()
        revolution = self.featurePanel("PartDesign_Revolution")
        self.assertWaitsForTheAxis(revolution)
        self.chooseAxis("Vertical sketch axis")
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        # A choice of the axis box hides the field (ReferenceCombo::refresh): the box shows it
        self.assertTrue(
            waitFor(lambda: self.axisField() is None or not self.axisField().property("missing")),
            "the axis field stays missing",
        )
        [box] = [
            c for c in Gui.getMainWindow().findChildren(QtWidgets.QComboBox, "axis") if c.isVisible()
        ]
        self.assertEqual(box.currentText(), "Vertical sketch axis")
        ok = QtWidgets.QDialogButtonBox.Ok
        self.assertTrue(
            waitFor(lambda: "pick a line or an edge" not in taskButton(ok).toolTip().lower()),
            "OK's hint stays with the axis picked",
        )
        self.close(ok=True)
        self.assertEqual(revolution.ReferenceAxis, (self.lidSk, ["V_Axis"]))
        self.assertTrue(revolution.isValid(), revolution.getStatusString())

    def testGrooveWaitsForItsAxis(self):
        """The Groove command, the same (a second part makes the subtractive box show, as in
        TestResultBoxGui). Then the pick and OK (tests-8 of the review): the sketch's V axis
        chosen, OK enabled, and the full turn cuts the enclosure. The axis is the line x 0, z 10
        along Y, so the square sweeps a cylinder of radius 30 over y 0..30; inside the 40 x 40 x
        10 base it removes 30 times the area of x >= 0, z 0..10, x^2 + (z - 10)^2 <= 900, that
        is 30 (5 sqrt(800) + 450 asin(1/3)), about 8830."""
        self.enclosure()
        self.otherPart()
        groove = self.featurePanel("PartDesign_Groove")
        self.assertWaitsForTheAxis(groove)
        self.chooseAxis("Vertical sketch axis")
        self.assertTrue(groove.isValid(), groove.getStatusString())
        self.close(ok=True)
        self.assertEqual(groove.ReferenceAxis, (self.lidSk, ["V_Axis"]))
        self.assertTrue(groove.isValid(), groove.getStatusString())
        removed = 30 * (5 * math.sqrt(800) + 450 * math.asin(1 / 3))
        self.assertAlmostEqual(self.body.Shape.Volume, 16000 - removed, places=1)

    def testEnterAcceptsARevolutionWithNoAxis(self):
        """Hands-on check R6 (ops#640 H1): the Revolution command on the lid sketch, no axis
        picked; Enter in the graphics area closes the dialog, as Onshape's Enter does (in the
        angle field Enter only commits the value, ops#640 rank 38). The
        Revolution stays, in error with Onshape's words, the enclosure keeps its 16000 (the failed
        feature passes its base through), the sketch is hidden as for any accepted feature, and
        the whole is one undo step. Edited again, the dialog opens with the axis row armed and
        red; the V axis picked and OK repair it."""
        self.enclosure()
        undos = len(self.doc.UndoNames)
        revolution = self.featurePanel("PartDesign_Revolution")
        self.assertWaitsForTheAxis(revolution)
        # A full turn shows no angle (rank 21, as Onshape's Full revolve): the value field to
        # press Enter in comes with Full revolve off
        full = self.visible(QtWidgets.QCheckBox, "checkBoxFullRevolve")
        self.assertIsNotNone(full, "no Full revolve box")
        full.setChecked(False)
        pump(0.3)
        angle = self.visible(QtWidgets.QWidget, "revolveAngle")
        self.assertIsNotNone(angle, "no angle field")
        angle.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.3)
        QtTest.QTest.keyClick(angle, QtCore.Qt.Key_Return)
        pump(0.3)
        self.assertTrue(Gui.Control.activeDialog(), "Enter in the angle field closed the dialog")
        viewport = Gui.ActiveDocument.ActiveView.graphicsView().viewport()
        viewport.setFocus(QtCore.Qt.OtherFocusReason)
        pump(0.3)
        modals = self.modalsDuring(lambda: QtTest.QTest.keyClick(viewport, QtCore.Qt.Key_Return))
        self.assertEqual(modals, [])
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.2)
        self.assertIn(revolution, self.body.Group)
        self.assertFalse(revolution.isValid())
        self.assertIn(AXIS_MISSING, revolution.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertFalse(self.lidSk.Visibility, "the sketch stays shown")
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(len(self.doc.UndoNames), undos + 1, self.doc.UndoNames)
        revolution.ViewObject.doubleClicked()
        self.waitForPanel()
        self.assertWaitsForTheAxis(revolution)
        self.chooseAxis("Vertical sketch axis")
        self.close(ok=True)
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(revolution.ReferenceAxis, (self.lidSk, ["V_Axis"]))

    def testOkAcceptsAGrooveWithNoAxis(self):
        """The same with the check (OK) on a Groove: it closes the dialog with no message box,
        the Groove stays in error with Onshape's words, and the enclosure keeps its 16000."""
        self.enclosure()
        self.otherPart()
        groove = self.featurePanel("PartDesign_Groove")
        self.assertWaitsForTheAxis(groove)
        self.assertEqual(self.modalsDuring(lambda: self.close(ok=True)), [])
        self.assertIn(groove, self.body.Group)
        self.assertFalse(groove.isValid())
        self.assertIn(AXIS_MISSING, groove.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 16000, places=3)
        self.assertFalse(self.lidSk.Visibility, "the sketch stays shown")

    def testARevolutionWithItsAxisIsNotWaiting(self):
        """The axis row is required now, but only an empty one waits: a Revolution of the lid
        sketch, a quarter turn about its V axis, made from Python, opens with the axis box on
        Vertical sketch axis and the axis row under it hidden and not armed, and OK keeps the
        axis. Onshape's Revolve dialog on a finished revolve waits for nothing."""
        self.enclosure()
        revolution = self.body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = self.lidSk
        revolution.ReferenceAxis = (self.lidSk, ["V_Axis"])
        revolution.Angle = 90
        self.doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        revolution.ViewObject.doubleClicked()
        self.waitForPanel()
        # An axis among the box's entries shows in the box (ReferenceCombo::refresh): the row
        # stays hidden, so it is looked up whatever its visibility
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        fields = Gui.getMainWindow().findChildren(QtWidgets.QWidget, "fieldReferenceAxis")
        self.assertEqual(len(fields), 1, "not one axis row")
        field = fields[0]
        self.assertFalse(field.property("armed"))
        self.assertFalse(field.property("missing"), "the axis row is shown missing")
        self.assertIsNone(self.axisField(), "the axis row shows with the axis in the box")
        box = self.visible(QtWidgets.QComboBox, "axis")
        self.assertIsNotNone(box, "no axis box")
        self.assertEqual(box.currentText(), "Vertical sketch axis")
        pump(0.1)
        self.assertTrue(taskButton(QtWidgets.QDialogButtonBox.Ok).isEnabled(), "OK is disabled")
        self.close(ok=True)
        self.assertEqual(revolution.ReferenceAxis, (self.lidSk, ["V_Axis"]))
        self.assertTrue(revolution.isValid(), revolution.getStatusString())


if __name__ == "__main__":
    unittest.main()
