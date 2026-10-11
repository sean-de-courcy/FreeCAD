# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Pipe and Hole task-panel fixes (FreeCAD-CH ops#170; notes/ops170-panel-fixes.md).

Each test drives the panel as a user does and fails on the old panel code:
- Pipe orientation: the Binormal spin boxes load the property; Clear of the auxiliary spine
  recomputes;
- Pipe scaling: choosing Multisection recomputes;
- Pipe OK: both spines outside the body are copied; a missing auxiliary spine with a section
  outside the body copies the section and adds no null object;
- Hole: OK keeps the thread class when the size combo is blank, and a BaseProfileType the combo
  doesn't list.
Follow-ups (ops#180): opening a pipe recomputes nothing; the Binormal boxes keep six decimals;
OK makes one copy of an object used as both spines, and keeps an outside object it can't copy
(an App::Link).

Designed models (notes/reference-list-widget.md 11.7):
- Rod: a 2 x 2 square on XY at z = 0 (A = 4), swept along a spine on XZ of two collinear lines
  along Z, 10 and 20 long: V = 120. Sections: 4 x 4 at z = 10, 2 x 2 at z = 30.
- Plate: a 20 x 20 x 10 box; on its top two circles r = 1 and one point. Each hole through all
  removes 10 pi.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets
from PySide6 import QtTest

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import Z, face
from PartDesignTests.TestDressUpDeleteKeyGui import reportText
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # sketch y -> global z


def line(x0, y0, x1, y1):
    return Part.LineSegment(V(x0, y0, 0), V(x1, y1, 0))


def expressions(obj):
    """obj's expressions as (path without its leading ".", expression)."""
    return [(path.lstrip("."), text) for path, text in obj.ExpressionEngine]


def sliceArea(shape, z):
    """The area of the shape's section at height z."""
    wires = shape.slice(V(0, 0, 1), z)
    return sum(Part.Face(w).Area for w in wires)


class TestPanelFixesGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PanelFixes")
        self.doc.UndoMode = 1
        self.modals = []
        self.answering = False
        Gui.Selection.clearSelection()

    def tearDown(self):
        self.answering = False
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
        pump()

    # -- models ----------------------------------------------------------------------------------

    def rod(self, spineInBody=True):
        """The Rod's body, profile and spine (in the body, or in the document's root)."""
        self.body = models.body(self.doc)
        self.profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body)
        self.spine = models.sketch(
            self.doc,
            "Spine",
            [line(0, 0, 0, 10), line(0, 10, 0, 30)],
            self.body if spineInBody else None,
            placement=XZ,
        )
        self.doc.recompute()
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (self.spine, ["Edge1", "Edge2"])
        return pipe

    def sections(self, inBody=True):
        body = self.body if inBody else None
        lower = models.sketch(self.doc, "Lower", models.rectangle(-2, -2, 2, 2), body, z=10)
        upper = models.sketch(self.doc, "Upper", models.rectangle(-1, -1, 1, 1), body, z=30)
        return lower, upper

    def auxiliarySpine(self, inBody=True):
        """A line parallel to the spine, 5 beside it."""
        return models.sketch(
            self.doc, "AuxSpine", [line(5, 0, 5, 30)], self.body if inBody else None, placement=XZ
        )

    def plate(self):
        """The Plate and its hole sketch; returns the box and the sketch."""
        self.body = models.body(self.doc)
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        box.Height = 10
        geometry = [models.circle(5, 5, 1), models.circle(15, 5, 1), Part.Point(V(10, 15, 0))]
        sketch = models.sketch(self.doc, "Holes", geometry, self.body, z=10)
        self.doc.recompute()
        return box, sketch

    # -- the panel -------------------------------------------------------------------------------

    def edit(self, obj, transaction=True):
        """Opens the panel on obj, in a new transaction unless transaction is False (the caller
        opened one, as the creation commands do)."""
        if transaction:
            self.doc.openTransaction("Edit " + obj.Name)
        Gui.getDocument(self.doc.Name).setEdit(obj.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        # the Tasks panel can still be hidden (the first dialog of a process, in the right-hand
        # overlay; or the Model tab, notes/build.md): its buttons count as hidden until it shows
        pump(0.3)
        Gui.Control.showTaskView()
        ok = QtWidgets.QDialogButtonBox.Ok
        self.assertTrue(
            waitFor(lambda: taskButton(ok) is not None, 5.0), "the Tasks panel stays hidden"
        )

    def widget(self, cls, name):
        found = Gui.getMainWindow().findChild(cls, name)
        self.assertIsNotNone(found, "no " + name)
        return found

    def close(self, ok):
        which = QtWidgets.QDialogButtonBox.Ok if ok else QtWidgets.QDialogButtonBox.Cancel
        button = taskButton(which)
        self.assertIsNotNone(button)
        button.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays")
        pump(0.2)

    def answerModals(self, choice="radioIndependent"):
        """Until self.answering is False: answers the copy dialog (DlgReference) with `choice`
        (default its default, Make independent copy), and closes any message box; records each in
        self.modals."""
        self.answering = True

        def poll():
            if not self.answering:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is not None:
                radio = widget.findChild(QtWidgets.QRadioButton, choice)
                if radio is not None:
                    self.modals.append("DlgReference")
                    radio.setChecked(True)
                    widget.accept()
                elif isinstance(widget, QtWidgets.QMessageBox):
                    self.modals.append("QMessageBox: " + widget.text())
                    widget.accept()
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)

    # -- ops#170 1-3: the Pipe's orientation and scaling panels ----------------------------------

    def testPipeBinormalLoaded(self):
        """1: the Binormal boxes show the property; editing X keeps Y and Z; Cancel restores."""
        pipe = self.rod()
        pipe.Mode = "Binormal"
        pipe.Binormal = V(1, 0, 1)
        self.doc.recompute()
        self.edit(pipe)
        boxes = [self.widget(QtWidgets.QDoubleSpinBox, "doubleSpinBox" + c) for c in "XYZ"]
        self.assertEqual([b.value() for b in boxes], [1, 0, 1])
        boxes[0].setValue(0.5)
        pump()
        self.assertEqual(pipe.Binormal, V(0.5, 0, 1))
        self.close(ok=False)
        self.assertEqual(pipe.Binormal, V(1, 0, 1))

    def testPipeScalingRecomputes(self):
        """2: choosing Multisection recomputes at once (no OK): the section at z = 10 is the
        4 x 4 section's 16, not the profile's 4. (The feature in edit stays Touched after the
        panel's recompute, so the shape is the oracle.)"""
        pipe = self.rod()
        pipe.Sections = list(self.sections())
        pipe.Transformation = "Constant"
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(sliceArea(pipe.Shape, 10), 4, places=3)
        self.edit(pipe)
        self.widget(QtWidgets.QComboBox, "comboBoxScaling").setCurrentIndex(1)  # Multisection
        pump()
        self.assertEqual(pipe.Transformation, "Multisection")
        self.assertAlmostEqual(sliceArea(pipe.Shape, 10), 16, places=3)

    def testPipeAuxClearRecomputes(self):
        """3: Clear of the auxiliary spine recomputes: in Mode Auxiliary the pipe fails at once
        ("No auxiliary spine linked."), not at OK."""
        pipe = self.rod()
        pipe.Mode = "Auxiliary"
        pipe.AuxiliarySpine = (self.auxiliarySpine(), ["Edge1"])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.edit(pipe)
        spinX = self.widget(QtWidgets.QDoubleSpinBox, "doubleSpinBoxX")
        panel = spinX.parentWidget()
        while (
            panel is not None
            and panel.findChild(QtWidgets.QToolButton, "buttonProfileClear") is None
        ):
            panel = panel.parentWidget()
        self.assertIsNotNone(panel, "no orientation panel")
        panel.findChild(QtWidgets.QToolButton, "buttonProfileClear").click()
        pump()
        self.assertIsNone(pipe.AuxiliarySpine)
        self.assertIn("Invalid", pipe.State)

    def stale(self, pipe):
        """Changes the pipe's spine to its first edge without a recompute: a recompute of the pipe
        would sweep 10 instead of 30 (V = 40, not 120). Returns the volume before."""
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        volume = pipe.Shape.Volume
        pipe.Spine = (pipe.Spine[0], ["Edge1"])
        return volume

    def assertOpensWithoutRecompute(self, pipe):
        volume = self.stale(pipe)
        self.edit(pipe)
        pump(0.5)  # the panels' queued updateUI
        self.assertNotIn("Invalid", pipe.State)
        self.assertAlmostEqual(pipe.Shape.Volume, volume, places=3)

    def testPipeOpensWithoutRecompute(self):
        """ops#180: opening a pipe's panel recomputes nothing. The curvilinear box (checked in
        every pipe by default, not in the .ui) wrote its value and recomputed the pipe at every
        open."""
        self.assertOpensWithoutRecompute(self.rod())

    def testPipeInAnotherModeOpensWithoutRecompute(self):
        """ops#180: likewise a pipe whose Mode isn't the first (Binormal): the mode combo wrote its
        value and recomputed; the mode's page still shows (the blocked combo no longer turns it)."""
        pipe = self.rod()
        pipe.Mode = "Binormal"
        pipe.Binormal = V(0, 1, 0)
        pipe.AuxiliaryCurvilinear = False
        self.assertOpensWithoutRecompute(pipe)
        pages = self.widget(QtWidgets.QComboBox, "comboBoxMode").parentWidget()
        stack = pages.findChild(QtWidgets.QStackedWidget, "stackedWidget")
        self.assertIsNotNone(stack)
        self.assertEqual(stack.currentIndex(), 4)
        self.assertEqual(self.widget(QtWidgets.QComboBox, "comboBoxMode").currentIndex(), 4)

    def testMultisectionPipeOpensWithoutRecompute(self):
        """ops#170/ops#180: a Multisection pipe opens without a recompute (its scaling combo is
        blocked since ops#170, the orientation panel's widgets since ops#180)."""
        pipe = self.rod()
        pipe.Sections = list(self.sections())
        pipe.Transformation = "Multisection"
        self.assertOpensWithoutRecompute(pipe)

    def testPipeWithRoundCornersOpensWithoutRecompute(self):
        """ops#180 round: likewise a pipe whose Transition isn't the first (Round corner): the
        transition combo wrote its value and recomputed; it still shows the pipe's transition."""
        pipe = self.rod()
        pipe.Transition = "Round corner"
        pipe.AuxiliaryCurvilinear = False
        self.assertOpensWithoutRecompute(pipe)
        self.assertEqual(self.widget(QtWidgets.QComboBox, "comboBoxTransition").currentIndex(), 2)

    def testPipeBinormalSixDecimals(self):
        """ops#180: a binormal of thirds shows to 6 decimals, and editing X writes Y and Z back
        rounded to 6 decimals (the .ui's two decimals made them 0.67)."""
        pipe = self.rod()
        pipe.Mode = "Binormal"
        pipe.Binormal = V(1 / 3, 2 / 3, 2 / 3)
        self.doc.recompute()
        self.edit(pipe)
        boxes = [self.widget(QtWidgets.QDoubleSpinBox, "doubleSpinBox" + c) for c in "XYZ"]
        for box, value in zip(boxes, (1 / 3, 2 / 3, 2 / 3)):
            self.assertAlmostEqual(box.value(), value, places=6)
        boxes[0].setValue(0.5)
        pump()
        self.assertAlmostEqual(pipe.Binormal.x, 0.5, places=6)
        self.assertAlmostEqual(pipe.Binormal.y, 2 / 3, places=6)
        self.assertAlmostEqual(pipe.Binormal.z, 2 / 3, places=6)

    # -- ops#170 4: the Pipe's OK copies what is outside the body ---------------------------------

    def testPipeCopiesBothExternalSpines(self):
        """4: spine and auxiliary spine both outside the body: OK copies both into it (Make
        independent copy), not only the spine; the spine's copy keeps its edges. Mode Standard
        (the auxiliary spine unused), so the sweep is the Rod's exact V = 120."""
        pipe = self.rod(spineInBody=False)
        aux = self.auxiliarySpine(inBody=False)
        pipe.AuxiliarySpine = (aux, ["Edge1"])
        self.doc.recompute()
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        self.assertTrue(self.body.hasObject(pipe.Spine[0]))
        self.assertTrue(self.body.hasObject(pipe.AuxiliarySpine[0]))
        self.assertIsNot(pipe.Spine[0], self.spine)
        self.assertIsNot(pipe.AuxiliarySpine[0], aux)
        self.assertEqual(pipe.Spine[1], ["Edge1", "Edge2"])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        # ops#225: the copies' edges are found by name, not again by geometry with a warning
        self.assertNotIn("Warning", pipe.State)
        self.assertEqual(App.getReferenceReport(pipe), [])

    def testPipeCopiesASpineUsedTwiceOnce(self):
        """ops#180: the spine outside the body is the auxiliary spine too: OK makes one copy, used
        by both (it made two)."""
        pipe = self.rod(spineInBody=False)
        pipe.AuxiliarySpine = (self.spine, ["Edge1", "Edge2"])
        self.doc.recompute()
        before = set(self.body.Group)
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        added = [obj for obj in self.body.Group if obj not in before]
        self.assertEqual(len(added), 1, [obj.Name for obj in added])
        self.assertIs(pipe.Spine[0], added[0])
        self.assertIs(pipe.AuxiliarySpine[0], added[0])
        self.doc.recompute()
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)

    def testPipeKeepsAnOutsideObjectItCannotCopy(self):
        """ops#180: an auxiliary spine outside the body that the copy dialog can't copy (an
        App::Link to a sketch): OK keeps the link and closes. It was set to nothing, and adding
        that nothing to the body failed after the commit ("Input Error")."""
        pipe = self.rod()
        link = self.doc.addObject("App::Link", "AuxLink")
        link.LinkedObject = self.auxiliarySpine(inBody=False)
        pipe.AuxiliarySpine = (link, ["Edge1"])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        reportStart = len(reportText() or "")
        self.edit(pipe)
        written = []

        class Observer:
            def slotChangedObject(self, obj, prop):
                if obj == pipe and prop in ("Spine", "AuxiliarySpine", "Sections"):
                    written.append(prop)

        observer = Observer()
        App.addDocumentObserver(observer)
        try:
            self.answerModals()
            self.close(ok=True)
            self.answering = False
        finally:
            App.removeDocumentObserver(observer)
        self.assertEqual(self.modals, ["DlgReference"])
        self.assertIs(pipe.AuxiliarySpine[0], link)
        self.assertFalse(self.body.hasObject(link))
        # ops#180 round: the link kept is not written back (a write drops the property's shadows
        # and its ops#127 guess record); ops#225: nor are the sections, none of them copied
        self.assertEqual(written, [])
        # ops#225: the Report view says the link was kept
        self.assertIn(
            "'AuxLink' can't be copied into the body", (reportText() or "")[reportStart:]
        )

    def testPipeCopiesASectionWithoutAuxiliarySpine(self):
        """4, the null: spine in the body, no auxiliary spine, one section outside the body. OK
        copies the section into the body and closes; the old code added a null copy and warned
        "Body: object is not allowed" after the commit."""
        pipe = self.rod()
        lower, upper = self.sections()
        outside = models.sketch(self.doc, "Outside", models.rectangle(-2, -2, 2, 2), None, z=10)
        self.doc.removeObject(lower.Name)
        pipe.Sections = [outside, upper]
        pipe.Transformation = "Multisection"
        self.doc.recompute()
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        [(copy, _), (kept, _)] = pipe.Sections
        self.assertIsNot(copy, outside)
        self.assertTrue(self.body.hasObject(copy))
        self.assertIs(kept, upper)
        self.assertIsNone(pipe.AuxiliarySpine)

    def testPipeDependentCopyOfASpineUsedTwice(self):
        """ops#225: as testPipeCopiesASpineUsedTwiceOnce, with Make dependent copy: one binder,
        used by both, and the sweep is the Rod's V = 120."""
        pipe = self.rod(spineInBody=False)
        pipe.AuxiliarySpine = (self.spine, ["Edge1", "Edge2"])
        self.doc.recompute()
        before = set(self.body.Group)
        self.edit(pipe)
        self.answerModals("radioDependent")
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        added = [obj for obj in self.body.Group if obj not in before]
        self.assertEqual(len(added), 1, [obj.Name for obj in added])
        self.assertIs(pipe.Spine[0], added[0])
        self.assertIs(pipe.AuxiliarySpine[0], added[0])
        self.assertEqual(pipe.Spine[1], ["Edge1", "Edge2"])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        # ops#225: the copies' edges are found by name, not again by geometry with a warning
        self.assertNotIn("Warning", pipe.State)
        self.assertEqual(App.getReferenceReport(pipe), [])

    def testPipeCopyKeepsASectionsGuess(self):
        """ops#225: OK copies the spine from outside the body; the section, a face in the body
        found again by geometry (the pad's rectangle drawn again the other way round), keeps its
        guess and warning. OK wrote every section back with plain names, which dropped both."""
        self.body = models.body(self.doc)
        base = models.sketch(self.doc, "Base", models.rectangle(-2, -2, 2, 2), self.body)
        pad = models.pad(self.body, base, 10)
        profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body)
        spine = models.sketch(self.doc, "Spine", [line(0, 0, 0, 10)], None, placement=XZ)
        self.doc.recompute()
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1"])
        top = face("plane", normal=Z, through=(0, 0, 10)).one(pad.Shape)
        pipe.Sections = [(pad, top)]
        pipe.Transformation = "Multisection"
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        base.deleteAllGeometry()
        base.addGeometry(models.polygon([(2, 2), (2, -2), (-2, -2), (-2, 2)]), False)
        self.doc.recompute()
        self.assertIn("Warning", pipe.State)
        self.assertEqual([r["property"] for r in App.getReferenceReport(pipe)], ["Sections"])
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        self.assertIsNot(pipe.Spine[0], spine)
        self.assertTrue(self.body.hasObject(pipe.Spine[0]))
        self.doc.recompute()
        self.assertIn("Warning", pipe.State)
        self.assertEqual([r["property"] for r in App.getReferenceReport(pipe)], ["Sections"])
        # 2 x 2 at z = 0 to 4 x 4 at z = 10, ruled: a frustum, 10 / 3 (4 + 16 + 8)
        self.assertAlmostEqual(pipe.AddSubShape.Volume, 280 / 3, places=3)

    # -- ops#234: the copy step, PR 211's review follow-ups --------------------------------------

    def testPipeCopyBesideAKeptSectionsGuess(self):
        """ops#234: two sections, the top face of a pad in the body found again by geometry (kept,
        with its guess) and a sketch outside the body (copied). OK writes only the copied entry:
        the kept one keeps its warning and report entry, the copied one is found by name. All
        three shapes are 2 x 2 squares on a straight spine 20 long: a prism, V = 80."""
        self.body = models.body(self.doc)
        base = models.sketch(self.doc, "Base", models.rectangle(-1, -1, 1, 1), self.body)
        pad = models.pad(self.body, base, 10)
        profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body)
        spine = models.sketch(self.doc, "Spine", [line(0, 0, 0, 20)], self.body, placement=XZ)
        outside = models.sketch(self.doc, "Outside", models.rectangle(-1, -1, 1, 1), None, z=20)
        self.doc.recompute()
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1"])
        top = face("plane", normal=Z, through=(0, 0, 10)).one(pad.Shape)
        pipe.Sections = [(pad, top), outside]
        pipe.Transformation = "Multisection"
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        base.deleteAllGeometry()
        base.addGeometry(models.polygon([(1, 1), (1, -1), (-1, -1), (-1, 1)]), False)
        self.doc.recompute()
        self.assertIn("Warning", pipe.State)
        guessed = [(r["property"], r["index"]) for r in App.getReferenceReport(pipe)]
        self.assertEqual(guessed, [("Sections", 0)])
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        [(kept, _), (copy, _)] = pipe.Sections
        self.assertIs(kept, pad)
        self.assertIsNot(copy, outside)
        self.assertTrue(self.body.hasObject(copy))
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertIn("Warning", pipe.State)
        self.assertEqual([(r["property"], r["index"]) for r in App.getReferenceReport(pipe)], guessed)
        self.assertAlmostEqual(pipe.AddSubShape.Volume, 80, places=3)

    def testPipeCopyKeepsTheSpinesGuess(self):
        """ops#234 (PR 211 review S2): the spine outside the body is found again by geometry (its
        two lines drawn again), so the pipe warns. OK copies the spine; the
        copy's lines are found by name, but the guess is still the pipe's, so its warning and
        report entries stay. They disappeared: the copy hid a guess."""
        pipe = self.rod(spineInBody=False)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.spine.deleteAllGeometry()
        self.spine.addGeometry([line(0, 10, 0, 30), line(0, 0, 0, 10)], False)
        self.doc.recompute()
        self.assertIn("Warning", pipe.State)
        subs = pipe.Spine[1]
        report = [(r["property"], r["index"]) for r in App.getReferenceReport(pipe)]
        self.assertEqual({prop for prop, _ in report}, {"Spine"})
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        self.assertIsNot(pipe.Spine[0], self.spine)
        self.assertTrue(self.body.hasObject(pipe.Spine[0]))
        self.assertEqual(pipe.Spine[1], subs)
        self.doc.recompute()
        # the copy's edges, in order, are the spine's: 10 then 20 long
        lengths = [pipe.Spine[0].getSubObject(sub).Length for sub in pipe.Spine[1]]
        self.assertEqual([round(length, 6) for length in lengths], [10, 20])
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        self.assertIn("Warning", pipe.State)
        self.assertEqual([(r["property"], r["index"]) for r in App.getReferenceReport(pipe)], report)

    def testPipeCopyThatFailsIsNamed(self):
        """ops#234: the spine outside the body has conflicting constraints (its first line 10 and
        20 long), so its copy doesn't recompute either. OK stops with a message naming the
        original and why: the copy is gone, the spine is the original, the body as before. The
        copy's result was ignored (round 1 of PR 219: it named it only in the Report view, and OK
        went on)."""
        import Sketcher

        pipe = self.rod(spineInBody=False)
        self.spine.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 10))
        self.spine.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 20))
        self.doc.recompute()
        self.assertFalse(self.spine.isValid())
        before = self.body.Group
        self.assertOkStops(
            pipe, "Pipe: a copy of 'Spine' doesn't recompute: Sketch with conflicting"
        )
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(self.body.Group, before)

    def assertOkStops(self, pipe, text, edit=True, transaction=True, ok=None):
        """OK answered Make independent copy shows a message box with text and leaves the panel
        open, with the edit's transaction still open and no new object left (round 2 of PR 219:
        the stop aborted the whole edit under the open panel). edit=False: the panel is open
        already. ok: the OK button, found earlier (the panel is hidden)."""
        if edit:
            self.edit(pipe, transaction)
        objects = self.doc.Objects
        self.answerModals()
        (ok or taskButton(QtWidgets.QDialogButtonBox.Ok)).click()
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2, 5.0), self.modals)
        self.answering = False
        pump(0.2)
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: "), self.modals)
        self.assertIn(text, self.modals[1])
        self.assertIn("No copy was kept, and the edit is still open.", self.modals[1])
        self.assertIsNotNone(Gui.Control.activeDialog(), "OK closed the panel")
        self.assertNotEqual(self.doc.getBookedTransactionID(), 0, "the edit's transaction ended")
        self.assertEqual([o for o in self.doc.Objects if o not in objects], [])

    def staleOuterSpine(self):
        """The Rod's spine as a sketch "Outer" beside the body, recomputed, then its first line
        made 20 long without a recompute: on an independent copy (recomputed) Edge1 is 20 long,
        on the original still 10."""
        outer = models.sketch(
            self.doc, "Outer", [line(0, 0, 0, 10), line(0, 10, 0, 30)], None, placement=XZ
        )
        self.doc.recompute()
        outer.Geometry = [line(0, 0, 0, 20), line(0, 20, 0, 30)]
        self.assertAlmostEqual(outer.Shape.Edges[0].Length, 10, places=6)
        return outer

    def testPipeCopyStopKeepsTheEdit(self):
        """ops#234 round 2 (PR 219 review H1): in the edit of a pipe whose spine is in the body,
        the spine is picked again on a sketch beside the body, edited without a recompute. OK
        (Make independent copy) stops on Edge1, which is 20 long on the copy and 10 on the
        original: the spine is still the picked one and the edit's transaction is open. Cancel
        then restores the spine from before the edit."""
        pipe = self.rod()
        self.doc.recompute()
        outer = self.staleOuterSpine()
        before = self.body.Group
        self.edit(pipe)
        pipe.Spine = (outer, ["Edge1", "Edge2"])
        self.assertOkStops(
            pipe, "Pipe: Spine 'Edge1' of 'Outer' would name another element", edit=False
        )
        self.assertIs(pipe.Spine[0], outer)
        self.assertEqual(pipe.Spine[1], ["Edge1", "Edge2"])
        self.close(ok=False)
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(pipe.Spine[1], ["Edge1", "Edge2"])
        self.assertEqual(self.body.Group, before)

    def testPipeCopyStopThenRetry(self):
        """ops#234 round 2: after the stop of testPipeCopyStopKeepsTheEdit, the outside sketch is
        recomputed, the spine picked again and OK pressed again: one copy, the pipe sweeps it
        (V = 120 along the 30 long spine), and the edit is one transaction: one undo removes the
        copy and restores the spine."""
        pipe = self.rod()
        self.doc.recompute()
        outer = self.staleOuterSpine()
        before = self.body.Group
        undos = self.doc.UndoCount
        self.edit(pipe)
        pipe.Spine = (outer, ["Edge1", "Edge2"])
        self.assertOkStops(
            pipe, "Pipe: Spine 'Edge1' of 'Outer' would name another element", edit=False
        )
        # as the message says: recompute the sketch and pick the spine again (the pick drops the
        # records the recompute left on the old pick: the edited edges are missing there)
        outer.recompute()
        pipe.Spine = (outer, ["Edge1", "Edge2"])
        self.modals = []
        self.answerModals()
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), self.modals)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copies = [o for o in self.doc.Objects if o.Name.startswith("Copy")]
        self.assertEqual(len(copies), 1, [o.Name for o in copies])
        self.assertIs(pipe.Spine[0], copies[0])
        self.assertTrue(self.body.hasObject(copies[0]))
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        self.assertEqual(self.doc.UndoCount, undos + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse([o for o in self.doc.Objects if o.Name.startswith("Copy")])
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(self.body.Group, before)

    def testNewPipeCopyStopKeepsThePipe(self):
        """ops#234 round 2: as testPipeCopyStopKeepsTheEdit for a new pipe (its creation is the
        open transaction, as Make AdditivePipe opens it): the stop keeps the pipe and the panel,
        and Cancel removes the pipe."""
        self.body = models.body(self.doc)
        self.profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body)
        self.doc.recompute()
        outer = self.staleOuterSpine()
        self.doc.openTransaction("Make AdditivePipe")
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (outer, ["Edge1", "Edge2"])
        self.assertOkStops(
            pipe, "Pipe: Spine 'Edge1' of 'Outer' would name another element", transaction=False
        )
        self.assertIs(self.doc.getObject("Pipe"), pipe)
        self.close(ok=False)
        self.assertIsNone(self.doc.getObject("Pipe"))

    def testPipeCopyOfAMissingElementStops(self):
        """ops#234 round 2 (PR 219 review M1): the spine is Edge2 of a sketch beside the body that
        has one line; a second line is then added without a recompute. The original can't read
        Edge2, its copy can: written by index, the pipe would sweep the new line, silently. OK
        stops."""
        self.body = models.body(self.doc)
        self.profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body)
        outer = models.sketch(self.doc, "Outer", [line(0, 0, 0, 10)], None, placement=XZ)
        self.doc.recompute()
        outer.Geometry = [line(0, 0, 0, 10), line(0, 10, 0, 30)]
        self.assertEqual(len(outer.Shape.Edges), 1)
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (outer, ["Edge2"])
        self.assertOkStops(pipe, "Pipe: Spine 'Edge2' of 'Outer' would name another element")
        self.assertIs(pipe.Spine[0], outer)

    def testPipeDependentCopyInAPlacedBody(self):
        """ops#234 round 2 (PR 219 review L5): the spine is a vertical edge of a box in another
        body moved by (5, 0, 0). Make dependent copy: no false stop (both shapes are compared in
        their container's frame), and the pipe sweeps the 2 x 2 profile 10 up: V = 40."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        self.body = models.body(self.doc)
        self.profile = models.sketch(self.doc, "Profile", models.rectangle(4, -1, 6, 1), self.body)
        self.doc.recompute()
        [sub] = [
            f"Edge{i}"
            for i, e in enumerate(box.Shape.Edges, 1)
            if (e.CenterOfMass - V(0, 0, 5)).Length < 1e-6
        ]
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (box, [sub])
        self.doc.recompute()
        self.edit(pipe)
        self.answerModals("radioDependent")
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        self.assertTrue(self.body.hasObject(pipe.Spine[0]))
        self.assertIsNot(pipe.Spine[0], box)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 40, places=3)

    def testPipeCopyAbortedWithThePipe(self):
        """ops#234 (PR 211 review), ops#243: the profile is open (three sides of the square), so
        the pipe fails. OK copies the spine from outside the body, recomputes it, then fails on
        the pipe (Input Error): the copy is gone, the spine is the original again, the body is as
        before, and the panel and the edit's transaction are still open."""
        pipe = self.rod(spineInBody=False)
        self.openProfile()
        self.doc.recompute()
        self.assertFalse(pipe.isValid())
        before = self.body.Group
        self.edit(pipe)
        self.assertOkStops(pipe, "Wire is not closed.", edit=False)
        self.assertIsNone(self.doc.getObject("CopySpine"))
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(self.body.Group, before)

    def openProfile(self):
        """The Rod's profile as three sides of its square: the pipe fails."""
        self.profile.deleteAllGeometry()
        self.profile.addGeometry(models.polyline([(-1, -1), (1, -1), (1, 1), (-1, 1)]), False)

    def closeProfile(self):
        self.profile.deleteAllGeometry()
        self.profile.addGeometry(models.rectangle(-1, -1, 1, 1), False)

    def outerSpine(self):
        """The Rod's spine as a sketch "Outer" beside the body, recomputed."""
        outer = models.sketch(
            self.doc, "Outer", [line(0, 0, 0, 10), line(0, 10, 0, 30)], None, placement=XZ
        )
        self.doc.recompute()
        return outer

    def failAfterTheCopy(self):
        """ops#243 (PR 219 verification P1): in the edit of the Rod (spine in the body) the spine
        is picked again on a sketch beside the body and the profile opened. OK (Make independent
        copy) copies the spine, and the pipe then fails: only the copy step is undone. The copy is
        gone, the spine is the picked one again, the panel and the edit's transaction are open
        (the abort undid the whole edit under the open panel, and OK again committed the old
        spine, outside undo)."""
        pipe = self.rod()
        self.doc.recompute()
        outer = self.outerSpine()
        self.before = self.body.Group
        self.undos = self.doc.UndoCount
        self.edit(pipe)
        pipe.Spine = (outer, ["Edge1", "Edge2"])
        self.openProfile()
        self.assertOkStops(pipe, "Wire is not closed.", edit=False)
        self.assertIs(pipe.Spine[0], outer)
        self.assertEqual(pipe.Spine[1], ["Edge1", "Edge2"])
        self.assertEqual(self.body.Group, self.before)
        return pipe, outer

    def testPipeRecomputeFailureThenRetry(self):
        """ops#243: after failAfterTheCopy the profile is closed again and OK pressed again: one
        copy, the pipe sweeps it (V = 120), and the edit is one transaction: one undo removes the
        copy and restores the spine and the profile."""
        pipe, outer = self.failAfterTheCopy()
        self.closeProfile()
        self.modals = []
        self.answerModals()
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), self.modals)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copies = [o for o in self.doc.Objects if o.Name.startswith("Copy")]
        self.assertEqual(len(copies), 1, [o.Name for o in copies])
        self.assertIs(pipe.Spine[0], copies[0])
        self.assertTrue(self.body.hasObject(copies[0]))
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        self.assertEqual(self.doc.UndoCount, self.undos + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse([o for o in self.doc.Objects if o.Name.startswith("Copy")])
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(self.body.Group, self.before)
        self.assertEqual(len(self.profile.Shape.Edges), 4)
        self.assertTrue(pipe.isValid(), pipe.getStatusString())

    def testPipeRecomputeFailureThenCancel(self):
        """ops#243: after failAfterTheCopy, Cancel restores the state from before the edit: the
        spine in the body, the closed profile, no copy, nothing to undo."""
        pipe, outer = self.failAfterTheCopy()
        self.close(ok=False)
        self.doc.recompute()
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(pipe.Spine[1], ["Edge1", "Edge2"])
        self.assertFalse([o for o in self.doc.Objects if o.Name.startswith("Copy")])
        self.assertEqual(self.body.Group, self.before)
        self.assertEqual(len(self.profile.Shape.Edges), 4)
        self.assertEqual(self.doc.UndoCount, self.undos)
        self.assertTrue(pipe.isValid(), pipe.getStatusString())

    def testPipeCopyOfALostElementStops(self):
        """ops#243 L4: the spine is Edge2 of a sketch beside the body, valid when picked; the
        sketch then loses its second line and is recomputed. Neither the original nor its copy
        can read Edge2: OK stops in the copy step (it passed the check, and the pipe's failure
        then took the abort path)."""
        self.body = models.body(self.doc)
        self.profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body)
        outer = models.sketch(
            self.doc, "Outer", [line(0, 0, 0, 10), line(0, 10, 0, 30)], None, placement=XZ
        )
        self.doc.recompute()
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (outer, ["Edge2"])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        outer.Geometry = [line(0, 0, 0, 10)]
        outer.recompute()
        self.assertEqual(len(outer.Shape.Edges), 1)
        self.assertOkStops(pipe, "would name another element on a copy")
        self.assertIs(pipe.Spine[0], outer)

    def testPipeCopyStopInAnotherActiveDocument(self):
        """ops#243 L3: another document is active when OK is pressed, so makeCopy makes the copy
        there; the pipe's document has an object of the copy's name. The stop of
        testPipeCopyStopKeepsTheEdit removes the copy from its own document, and the pipe's
        document keeps its object (the stop removed by name from the pipe's document)."""
        pipe = self.rod()
        self.doc.recompute()
        outer = self.staleOuterSpine()
        mine = self.doc.addObject("App::FeaturePython", "CopyOuter")
        # hidden, so its view doesn't take over the GUI's active document (setEdit then fails);
        # makeCopy goes by the App's active document
        other = App.newDocument("PanelFixesOther", hidden=True)
        try:
            App.setActiveDocument(self.doc.Name)
            self.edit(pipe)
            pipe.Spine = (outer, ["Edge1", "Edge2"])
            # the Tasks panel shows the active document's dialog only, so a user can't press OK
            # here; the button is clicked while hidden (the removal by document is defensive)
            ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
            App.setActiveDocument(other.Name)
            self.assertOkStops(
                pipe,
                "Pipe: Spine 'Edge1' of 'Outer' would name another element",
                edit=False,
                ok=ok,
            )
            self.assertIs(self.doc.getObject("CopyOuter"), mine)
            self.assertEqual([o.Name for o in other.Objects], [])
        finally:
            App.setActiveDocument(self.doc.Name)
            App.closeDocument(other.Name)

    def testPipeCopyUndoRedo(self):
        """ops#234 (PR 211 review): OK copies the spine from outside the body, recomputed and
        added to the body; one undo takes all of it back (the copy gone, the spine the original,
        the body as before), one redo puts it all back, V = 120."""
        pipe = self.rod(spineInBody=False)
        self.doc.recompute()
        before = self.body.Group
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        copy = pipe.Spine[0]
        self.assertTrue(self.body.hasObject(copy))
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("CopySpine"))
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(self.body.Group, before)
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.doc.redo()
        self.doc.recompute()
        copy = self.doc.getObject("CopySpine")
        self.assertIsNotNone(copy)
        self.assertIs(pipe.Spine[0], copy)
        self.assertTrue(self.body.hasObject(copy))
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)

    def testPipeCopyOfAnotherShapeStops(self):
        """ops#234 round (PR 219 review F1): the spine is an edge of a box in another body that
        is fused with a base box. The independent copy takes no BaseFeature, so its shape is the
        box alone, where that index is another edge (or none): written by index, the spine moved
        silently. OK now stops and names the reference. Model: a base box 20 x 20 x 10 and a box
        10 x 10 x 20, both at the origin; the spine is the fused shape's vertical edge at
        x = 20, y = 0 (z 0..10), which the box alone hasn't; the profile is a 2 x 2 square around
        its foot."""
        other = models.body(self.doc)
        base = other.newObject("PartDesign::AdditiveBox", "Base")
        base.Length = 20
        base.Width = 20
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Height = 20
        self.body = models.body(self.doc)
        self.profile = models.sketch(
            self.doc, "Profile", models.rectangle(19, -1, 21, 1), self.body
        )
        self.doc.recompute()
        self.assertTrue(box.isValid(), box.getStatusString())
        # the base's vertical edge at x = 20, y = 0, by geometry
        [sub] = [
            f"Edge{i}"
            for i, e in enumerate(box.Shape.Edges, 1)
            if (e.CenterOfMass - V(20, 0, 5)).Length < 1e-6
        ]
        alone = Part.makeBox(10, 10, 20)
        index = int(sub[4:])
        if index <= len(alone.Edges):
            self.assertGreater((alone.Edges[index - 1].CenterOfMass - V(20, 0, 5)).Length, 1)
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (box, [sub])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertOkStops(pipe, f"Pipe: Spine '{sub}' of 'Box' would name another element")
        self.assertIs(pipe.Spine[0], box)
        self.assertEqual(pipe.Spine[1], [sub])

    def testPipeCopyKeepsAnOutsideSectionsGuess(self):
        """ops#234 round (PR 219 review, test gap): the section is the top face of a pad in
        another body, found again by geometry (the pad's rectangle drawn again the other way
        round), so the pipe warns. OK copies it (a ShapeBinder of the pad's shape): the copied
        entry is written by its index name and keeps its guess, so the warning and the report
        entry stay. 2 x 2 at z = 0 to 4 x 4 at z = 10, ruled: a frustum, V = 280 / 3."""
        other = models.body(self.doc)
        base = models.sketch(self.doc, "Base", models.rectangle(-2, -2, 2, 2), other)
        pad = models.pad(other, base, 10)
        self.body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body)
        spine = models.sketch(self.doc, "Spine", [line(0, 0, 0, 10)], self.body, placement=XZ)
        self.doc.recompute()
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = profile
        pipe.Spine = (spine, ["Edge1"])
        top = face("plane", normal=Z, through=(0, 0, 10)).one(pad.Shape)
        pipe.Sections = [(pad, top)]
        pipe.Transformation = "Multisection"
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        base.deleteAllGeometry()
        base.addGeometry(models.polygon([(2, 2), (2, -2), (-2, -2), (-2, 2)]), False)
        self.doc.recompute()
        self.assertIn("Warning", pipe.State)
        guessed = [(r["property"], r["index"]) for r in App.getReferenceReport(pipe)]
        self.assertEqual(guessed, [("Sections", 0)])
        sub = pipe.Sections[0][1][0]
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        [(copy, subs)] = pipe.Sections
        self.assertIsNot(copy, pad)
        self.assertTrue(self.body.hasObject(copy))
        self.assertEqual(subs, (sub,))
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertIn("Warning", pipe.State)
        self.assertEqual([(r["property"], r["index"]) for r in App.getReferenceReport(pipe)], guessed)
        self.assertAlmostEqual(pipe.AddSubShape.Volume, 280 / 3, places=3)

    def testPipeWidgetsWriteAfterLoad(self):
        """ops#225: the widgets loaded under signal blockers (ops#180) still write once the panel
        is open: the curvilinear box (and the pipe recomputes: the stale pipe sweeps 10, V = 40),
        the Mode combo, the Transition combo."""
        pipe = self.rod()
        self.stale(pipe)
        self.edit(pipe)
        pump(0.5)
        curvilinear = self.widget(QtWidgets.QCheckBox, "curvilinear")
        was = pipe.AuxiliaryCurvilinear
        curvilinear.setChecked(not curvilinear.isChecked())
        pump()
        self.assertNotEqual(pipe.AuxiliaryCurvilinear, was)
        self.assertAlmostEqual(pipe.Shape.Volume, 40, places=3)
        self.widget(QtWidgets.QComboBox, "comboBoxMode").setCurrentIndex(1)
        pump()
        self.assertEqual(pipe.Mode, "Fixed")
        self.widget(QtWidgets.QComboBox, "comboBoxTransition").setCurrentIndex(1)
        pump()
        self.assertEqual(pipe.Transition, "Right corner")

    # -- ops#170 5, 6: the Hole -----------------------------------------------------------------

    def testHoleThreadClassGetter(self):
        """5: OK writes the thread class from its own combo (the getter tested the size combo): a
        blank size combo wrote the class as 0. No user path to the state is known: OK writes
        ThreadType and ThreadSize first, and each write reloads the combos from the object, so
        the test makes both read-only (apply() skips those) to reach the getter."""
        box, sketch = self.plate()
        hole = self.body.newObject("PartDesign::Hole", "Hole")
        hole.Profile = sketch
        hole.DepthType = "ThroughAll"
        hole.Threaded = True
        hole.ThreadType = "ISOMetricProfile"
        hole.ThreadSize = 0
        hole.ThreadClass = 2
        self.doc.recompute()
        classes = hole.getEnumerationsOfProperty("ThreadClass")
        self.assertEqual(classes.index(hole.ThreadClass), 2)
        self.edit(hole)
        hole.setEditorMode("ThreadType", ["ReadOnly"])
        hole.setEditorMode("ThreadSize", ["ReadOnly"])
        size = self.widget(QtWidgets.QComboBox, "ThreadSize")
        size.blockSignals(True)
        size.setCurrentIndex(-1)
        size.blockSignals(False)
        self.close(ok=True)
        self.assertEqual(classes.index(hole.ThreadClass), 2)

    def unlistedBaseProfileType(self, value, holes):
        box, sketch = self.plate()
        hole = self.body.newObject("PartDesign::Hole", "Hole")
        hole.Profile = sketch
        hole.Diameter = 2
        hole.DepthType = "ThroughAll"
        hole.BaseProfileType = value
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        removed = holes * 10 * math.pi
        self.assertAlmostEqual(box.Shape.Volume - hole.Shape.Volume, removed, places=3)
        self.edit(hole)
        self.close(ok=True)
        self.assertEqual(hole.BaseProfileType, value)
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.assertAlmostEqual(box.Shape.Volume - hole.Shape.Volume, removed, places=3)

    def testHoleUnlistedBaseProfileTypeKept(self):
        """6: BaseProfileType 2 (circles only), which the combo doesn't list: OK keeps it (it
        wrote 0, no positions)."""
        self.unlistedBaseProfileType(2, holes=2)

    def testHoleUnlistedPointsAndCirclesKept(self):
        """6: the same for 3 (points and circles): three holes."""
        self.unlistedBaseProfileType(3, holes=3)

    # -- ops#233: an independent copy leaves the original alone ---------------------------------

    def guidedSpine(self, defining=False):
        """The Rod with its spine outside the body; the spine projects a guide line (x 0..5 at
        z = 10, GeoId -3) and has three constraints, all holding as drawn: its first line's end on
        the guide's start (external), its start on the H axis (-1), and its two lines joined."""
        import Sketcher

        pipe = self.rod(spineInBody=False)
        guide = self.doc.addObject("Part::Feature", "Guide")
        guide.Shape = Part.makeLine(V(0, 0, 10), V(5, 0, 10))
        self.spine.addExternal(guide.Name, "Edge1", defining)
        self.spine.addConstraint(Sketcher.Constraint("Coincident", 0, 2, -3, 1))
        self.spine.addConstraint(Sketcher.Constraint("PointOnObject", 0, 1, -1))
        self.spine.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        self.doc.recompute()
        self.assertTrue(self.spine.isValid(), self.spine.getStatusString())
        return pipe

    def constraints(self, sketch):
        return [(c.Type, c.First, c.Second) for c in sketch.Constraints]

    def edges(self, shape):
        """Each edge's end points, rounded, in order."""

        def point(v):
            return tuple(round(c, 9) for c in v.Point)

        return sorted((point(e.Vertexes[0]), point(e.Vertexes[-1])) for e in shape.Edges)

    def copySpine(self, pipe):
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copy = pipe.Spine[0]
        self.assertIsNot(copy, self.spine)
        return copy

    def assertIndependentCopy(self, copy, constraints, lines, edges, dof=3):
        """The copy links nothing outside, keeps the original's constraints (all of them in
        force: the guided spine's 8 degrees of freedom less 5), lines and shape, and solves."""
        self.assertEqual(copy.ExternalGeometry, [])
        self.assertEqual(copy.ExternalTypes, [])
        self.assertEqual(len(copy.ExternalGeo), 3)  # the axes and the detached projection
        self.assertEqual(self.constraints(copy), constraints)
        self.assertTrue(copy.isValid(), copy.getStatusString())
        self.assertEqual(copy.DoF, dof)
        self.assertEqual([(g.StartPoint, g.EndPoint) for g in copy.Geometry], lines)
        self.assertEqual(self.edges(copy.Shape), edges)

    def testPipeCopyKeepsTheOriginalsExternalConstraints(self):
        """ops#233: OK copies the guided spine (Make independent copy). The original keeps its
        three constraints and its lines. The copy keeps them too, on its projection detached (no
        reference, so its recompute doesn't link the guide outside the body again), and solves to
        the same lines. The old code deleted the original's external constraint (once per
        property), and the copy linked the guide again."""
        import Sketcher

        pipe = self.guidedSpine()
        constraints = self.constraints(self.spine)
        self.assertEqual(
            constraints, [("Coincident", 0, -3), ("PointOnObject", 0, -1), ("Coincident", 0, 1)]
        )
        lines = [(g.StartPoint, g.EndPoint) for g in self.spine.Geometry]
        edges = self.edges(self.spine.Shape)
        copy = self.copySpine(pipe)
        self.doc.recompute()
        self.assertEqual(self.constraints(self.spine), constraints)
        self.assertTrue(self.spine.isValid(), self.spine.getStatusString())
        self.assertEqual([(g.StartPoint, g.EndPoint) for g in self.spine.Geometry], lines)
        self.assertEqual(len(self.spine.ExternalGeometry), 1)
        self.assertEqual(self.spine.DoF, 3)
        self.assertIndependentCopy(copy, constraints, lines, edges)
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        # a constraint added to the copy keeps the pasted ones (an invalid list read as empty,
        # and the add dropped them all)
        copy.addConstraint(Sketcher.Constraint("Vertical", 1))
        self.doc.recompute()
        self.assertEqual(self.constraints(copy)[:3], constraints)
        self.assertEqual(len(copy.Constraints), 4)
        self.assertEqual(copy.DoF, 2)

    def testPipeCopyKeepsADefiningExternalEdge(self):
        """ops#233 round: the guide is projected as defining geometry, so it is an edge of the
        spine's shape (ExternalEdge1). The copy's shape has the same edges, the guide's
        included; trimming the projection dropped it."""
        pipe = self.guidedSpine(defining=True)
        edges = self.edges(self.spine.Shape)
        self.assertEqual(len(edges), 3)
        lines = [(g.StartPoint, g.EndPoint) for g in self.spine.Geometry]
        constraints = self.constraints(self.spine)
        copy = self.copySpine(pipe)
        self.doc.recompute()
        self.assertIndependentCopy(copy, constraints, lines, edges)

    def testPipeCopySavedAndRestored(self):
        """ops#233 round: the copy saved and opened again still links nothing, keeps its
        constraints and lines, and solves."""
        import os
        import tempfile

        pipe = self.guidedSpine()
        lines = [(g.StartPoint, g.EndPoint) for g in self.spine.Geometry]
        edges = self.edges(self.spine.Shape)
        constraints = self.constraints(self.spine)
        copy = self.copySpine(pipe)
        self.doc.recompute()
        path = os.path.join(tempfile.mkdtemp(), "CopyRestored.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        copy = self.doc.getObject("CopySpine")
        self.assertIsNotNone(copy)
        self.doc.recompute()
        self.assertIndependentCopy(copy, constraints, lines, edges)
        pipe = self.doc.getObject("Pipe")
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)

    def testPipeCopyUndoneLeavesTheOriginal(self):
        """ops#233 round: undoing the OK that made the copy removes the copy and leaves the
        original's constraints as they were."""
        pipe = self.guidedSpine()
        constraints = self.constraints(self.spine)
        self.copySpine(pipe)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("CopySpine"))
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(self.constraints(self.spine), constraints)
        self.assertTrue(self.spine.isValid(), self.spine.getStatusString())

    # -- ops#230: makeCopy's independent copy is recomputed before a caller links it ----------------

    def chooseInPopup(self, combo, index):
        """An entry of a combo box chosen through its popup, as a user does (as
        TestReferenceFieldGui.choose)."""
        combo.showPopup()
        view = combo.view()

        def placed():
            rect = view.visualRect(view.model().index(index, 0))
            return view.isVisible() and rect.isValid() and not rect.isEmpty()

        self.assertTrue(waitFor(placed), "the popup's entry isn't placed")
        pump(0.05)
        rect = view.visualRect(view.model().index(index, 0))
        QtTest.QTest.mouseClick(
            view.viewport(), QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, rect.center()
        )
        self.assertTrue(waitFor(lambda: not view.isVisible()), "the popup stays")
        pump(0.1)

    def testRevolutionAxisCopiedFromOutside(self):
        """ops#230 (getReferencedSelection): the Revolution's axis picked on a sketch outside the
        body, Make independent copy. The axis links (CopyAxis, Edge1) at once; the copy was not
        recomputed then, so the name mapped in its pasted shape was lost at its first recompute
        and the axis came back resolved by geometry, with a Warning. Model: the Ring profile
        (x 1..3, z 0..2 on XZ) turned 360 degrees about a line x = -1 along Z outside the body:
        radii 2..4, V = 2 pi (16 - 4) = 24 pi."""
        self.body = models.body(self.doc)
        ring = models.sketch(self.doc, "Ring", models.rectangle(1, 0, 3, 2), self.body, placement=XZ)
        axis = models.sketch(self.doc, "Axis", [line(-1, 0, -1, 5)], None, placement=XZ)
        self.doc.recompute()
        revolution = self.body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = ring
        revolution.ReferenceAxis = (ring, ["V_Axis"])
        revolution.Angle = 360
        self.doc.recompute()
        self.assertAlmostEqual(revolution.Shape.Volume, 16 * math.pi, places=3)

        self.edit(revolution)
        combo = self.widget(QtWidgets.QComboBox, "axis")
        [index] = [
            i for i in range(combo.count()) if combo.itemText(i).startswith("Select reference")
        ]
        self.chooseInPopup(combo, index)
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, axis.Name, "Edge1")
        self.assertTrue(waitFor(lambda: self.modals), "no copy dialog")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        self.close(ok=True)

        copy = self.doc.getObject("CopyAxis")
        self.assertIsNotNone(copy)
        self.assertIn(copy, self.body.Group)
        self.assertEqual(revolution.ReferenceAxis[0], copy)
        self.assertEqual(revolution.ReferenceAxis[1], ["Edge1"])
        self.doc.recompute()
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertNotIn("Warning", revolution.State)
        self.assertEqual(App.getReferenceReport(revolution), [])
        self.assertAlmostEqual(revolution.Shape.Volume, 24 * math.pi, places=3)

    def runNewSketchOnCopiedFace(self, feature, face):
        """Runs New Sketch on `face` of feature (in another body) and answers Make independent
        copy, and any message box; the answers go to self.modals."""
        # the command is active only in its workbench (an earlier unit can leave another one)
        Gui.activateWorkbench("PartDesignWorkbench")
        guiDoc = Gui.getDocument(self.doc.Name)
        # the command acts on the active document: this one's view in front (the suite's earlier
        # units can leave theirs open)
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        self.assertEqual(Gui.ActiveDocument.Document.Name, self.doc.Name)
        guiDoc.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.addSelection(self.doc.Name, feature.Name, face)
        # New Sketch with Shift held goes to the attachment dialog: a guard against a unit that
        # leaves the application's modifier state at Shift (TestForkKeymapGui did, off screen)
        self.assertEqual(
            QtWidgets.QApplication.queryKeyboardModifiers(), QtCore.Qt.KeyboardModifier.NoModifier
        )
        self.answerModals()
        Gui.runCommand("PartDesign_NewSketch")

    def newSketchOnCopiedFace(self, feature, face="Face1"):
        """New Sketch on `face` of feature (in another body), answered Make independent copy;
        returns the sketch, left edit."""
        guiDoc = Gui.getDocument(self.doc.Name)
        self.runNewSketchOnCopiedFace(feature, face)
        self.assertTrue(
            waitFor(lambda: guiDoc.getInEdit() is not None, 10.0),
            f"no sketch in edit; modals {self.modals}, workbench {Gui.activeWorkbench().name()}",
        )
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        guiDoc.resetEdit()
        pump(0.3)
        [sketch] = [o for o in self.body.Group if o.isDerivedFrom("Sketcher::SketchObject")]
        return sketch

    def testNewSketchOnAFaceCopiedFromAnotherBody(self):
        """ops#230 (SketchWorkflow): New Sketch on a face of a box in another body, Make
        independent copy. The sketch's support links (CopyBox, Face1) before the copy's first
        recompute, so the name mapped in its pasted shape was lost and the support came back
        resolved by geometry, with a Warning. Model: a 10 mm box at the origin in the other body;
        its Face1, the face picked, is the plane x = 0, so the sketch's normal is along X at
        x = 0."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        self.doc.recompute()
        sketch = self.newSketchOnCopiedFace(box)

        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertIn(copy, self.body.Group)
        self.assertEqual(sketch.AttachmentSupport, [(copy, ("Face1",))])
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertNotIn("Warning", sketch.State)
        self.assertEqual(App.getReferenceReport(sketch), [])
        normal = sketch.Placement.Rotation.multVec(Z)
        self.assertAlmostEqual(abs(normal.x), 1, places=6)
        self.assertAlmostEqual(sketch.Placement.Base.x, 0, places=6)

    def primitivesOnABase(self):
        """Another body: Base, a 20 x 20 x 10 box at (-5, -5, 0); Box, a 10 x 10 x 20 box at the
        origin on it; Cut, a 2 mm subtractive box at the origin on Box. The fused shape's Face1
        is the plane x = -5 (the base's side), the bare box's Face1 the plane x = 0."""
        other = models.body(self.doc)
        base = other.newObject("PartDesign::AdditiveBox", "Base")
        base.Length = 20
        base.Width = 20
        base.Placement.Base = V(-5, -5, 0)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Height = 20
        cut = other.newObject("PartDesign::SubtractiveBox", "Cut")
        cut.Length = 2
        cut.Width = 2
        cut.Height = 2
        self.body = models.body(self.doc)
        self.doc.recompute()
        self.assertIs(box.BaseFeature, base)
        self.assertAlmostEqual(box.Shape.Faces[0].CenterOfMass.x, -5, places=6)
        return box, cut

    def testNewSketchOnACopiedPrimitiveOnABase(self):
        """PR 223 review M1: as testNewSketchOnAFaceCopiedFromAnotherBody, on Box, which sits on
        Base. Its copy has no BaseFeature, so a recompute in makeCopy made it the bare box before
        the sketch linked its Face1, and the sketch went on the bare box's Face1 (x = 0), another
        plane than the Face1 picked (x = -5), silently. The copy keeps its pasted shape until the
        command's recompute (which still makes it the bare box, ops#244 P5): the sketch is on the
        picked plane, or flagged; never valid elsewhere without a warning."""
        box, _ = self.primitivesOnABase()
        sketch = self.newSketchOnCopiedFace(box)
        self.doc.recompute()
        onPicked = abs(sketch.Placement.Base.x + 5) < 1e-6
        flagged = "Warning" in sketch.State or not sketch.isValid()
        self.assertTrue(onPicked or flagged, (sketch.Placement, sketch.State))

    def testNewSketchOnACopiedSubtractivePrimitive(self):
        """PR 223 review M2: New Sketch on a face of Cut (a subtractive box on Box), Make
        independent copy. Recomputed without a base, the copy failed ("Cannot subtract primitive
        feature without base feature") and makeCopy reported it. It keeps its pasted shape (the
        command's own recompute then fails it in the body, as before ops#230: ops#244 P5)."""
        _, cut = self.primitivesOnABase()
        before = len(reportText() or "")
        self.newSketchOnCopiedFace(cut)
        self.assertIsNotNone(self.doc.getObject("CopyCut"))
        self.assertNotIn("doesn't recompute", (reportText() or "")[before:])

    def boxElement(self, box, kind, where):
        """The index name of the box's element of `kind` ("Face" or "Edge") whose centre of mass
        satisfies where(point); asserted not to be the first one, which the copies linked
        whatever was picked (ops#244 P1)."""
        elements = box.Shape.Faces if kind == "Face" else box.Shape.Edges
        [name] = [
            f"{kind}{i + 1}" for i, e in enumerate(elements) if where(e.CenterOfMass)
        ]
        self.assertNotEqual(name, kind + "1")
        return name

    def testNewSketchOnTheTopFaceOfACopiedBox(self):
        """PR 223 review N1: New Sketch on the top face of a box in another body (no base), Make
        independent copy. makeCopy recomputes such a copy, so it has its own element names, and
        the sketch went on the copy's Face1 (the plane x = 0) whatever face was picked, valid and
        silent. It links the picked face, which the recomputed copy has under the same index.
        Model: a 10 mm box at the origin; its top face is the plane z = 10."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        self.doc.recompute()
        top = self.boxElement(box, "Face", lambda p: abs(p.z - 10) < 1e-6)
        sketch = self.newSketchOnCopiedFace(box, top)

        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertEqual(sketch.AttachmentSupport, [(copy, (top,))])
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertNotIn("Warning", sketch.State)
        self.assertEqual(App.getReferenceReport(sketch), [])
        normal = sketch.Placement.Rotation.multVec(Z)
        self.assertAlmostEqual(abs(normal.z), 1, places=6)
        self.assertAlmostEqual(sketch.Placement.Base.z, 10, places=6)

    def testNewSketchOnAStaleCopiedBoxStops(self):
        """PR 223 review N1, the check: the box was lengthened and not recomputed, so its copy,
        recomputed in makeCopy, is longer, and the picked face (the end x = 10) is another face
        there. New Sketch stops with a message and leaves no copy and no sketch."""
        self.newSketchOnAStaleCopiedBox()

    def newSketchOnAStaleCopiedBox(self):
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        self.doc.recompute()
        end = self.boxElement(box, "Face", lambda p: abs(p.x - 10) < 1e-6)
        box.Length = 20
        self.runNewSketchOnCopiedFace(box, end)
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: " + end), self.modals)
        pump(0.3)
        self.assertIsNone(Gui.getDocument(self.doc.Name).getInEdit())
        self.assertIsNone(self.doc.getObject("CopyBox"))
        self.assertEqual(
            [o for o in self.doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")], []
        )

    def revolutionBesideABox(self):
        """A 10 mm box at the origin in another body, and in this one the Ring profile (x 1..3,
        z 0..2 on XZ) turned about its own V axis; returns the box, the revolution and the box's
        edge x = 10, y = 0 along Z."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        ring = models.sketch(self.doc, "Ring", models.rectangle(1, 0, 3, 2), self.body, placement=XZ)
        self.doc.recompute()
        edge = self.boxElement(
            box, "Edge", lambda p: abs(p.x - 10) < 1e-6 and abs(p.y) < 1e-6 and abs(p.z - 5) < 1e-6
        )
        revolution = self.body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = ring
        revolution.ReferenceAxis = (ring, ["V_Axis"])
        revolution.Angle = 360
        self.doc.recompute()
        return box, revolution, edge

    def armAxisField(self):
        """Chooses "Select reference..." in the open Revolution panel's axis box."""
        combo = self.widget(QtWidgets.QComboBox, "axis")
        [index] = [
            i for i in range(combo.count()) if combo.itemText(i).startswith("Select reference")
        ]
        self.chooseInPopup(combo, index)

    def testRevolutionAxisOnAnEdgeOfACopiedBox(self):
        """PR 223 review N1 (getReferencedSelection): the Revolution's axis picked on an edge of
        a box in another body (no base), Make independent copy. The axis went to the copy's
        Edge1 whatever edge was picked; it is the picked edge, the same line on the copy. Checked
        at the pick: once the panel closes, the copy sits after the Revolution in the body with
        the Revolution as its BaseFeature, a cycle that breaks the axis, loudly (ops#244 P3).
        Model: a 10 mm box at the origin; the axis is its edge x = 10, y = 0 along Z."""
        box, revolution, edge = self.revolutionBesideABox()
        self.edit(revolution)
        self.armAxisField()
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, box.Name, edge)
        self.assertTrue(waitFor(lambda: self.modals), "no copy dialog")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])

        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertEqual(revolution.ReferenceAxis, (copy, [edge]))
        picked = copy.Shape.getElement(edge)
        self.assertAlmostEqual(picked.CenterOfMass.distanceToPoint(V(10, 0, 5)), 0, places=6)
        self.assertAlmostEqual(abs(picked.Curve.Direction.z), 1, places=6)
        self.close(ok=False)

    def testRevolutionAxisOnAStaleCopiedBoxStops(self):
        """PR 223 verification L3 (getReferencedSelection's check): as
        testRevolutionAxisOnAnEdgeOfACopiedBox, with the box lengthened to 20 and not
        recomputed, so the picked edge (x = 10) is at x = 20 on the copy. The pick stops with a
        message, leaves no copy and the axis as it was, and the field stays armed: once the box
        is recomputed, the same pick links the copy's edge."""
        box, revolution, edge = self.revolutionBesideABox()
        box.Length = 20
        self.edit(revolution)
        self.armAxisField()
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, box.Name, edge)
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: " + edge), self.modals)
        self.assertEqual(
            [o.Name for o in self.doc.Objects if o.Name.startswith("CopyBox")], []
        )
        self.assertEqual(revolution.ReferenceAxis[1], ["V_Axis"])

        self.doc.recompute()
        Gui.Selection.clearSelection()
        self.modals = []
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, box.Name, edge)
        self.assertTrue(waitFor(lambda: self.modals), "the field isn't armed")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copy = revolution.ReferenceAxis[0]
        self.assertTrue(copy.Name.startswith("CopyBox"), copy.Name)
        self.assertEqual(revolution.ReferenceAxis[1], [edge])
        self.close(ok=False)

    # -- ops#236, ops#241: makeCopy's independent copy -------------------------------------------

    def copySpineIn(self, pipe):
        """OK on the pipe's panel, answered Make independent copy; returns the spine's copy."""
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copy = pipe.Spine[0]
        self.assertTrue(self.body.hasObject(copy))
        return copy

    def copyOwnsItsExpression(self, text):
        """ops#236: the Rod's spine outside the body has constraints: an unrelated one first
        (index 0), "Len" (the first line's height, 10), and the second line's height driven by
        the expression `text` (Len * 2). On its independent copy the expression belongs to the
        copy: it reads the copy's Len, and it follows its constraint when constraint 0 is
        deleted. The pasted keys and expressions kept the original as their owner."""
        import Sketcher

        pipe = self.rod(spineInBody=False)
        spine = self.spine
        spine.Label = "Spine label"
        spine.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        spine.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 10))
        spine.renameConstraint(1, "Len")
        spine.addConstraint(Sketcher.Constraint("DistanceY", 1, 1, 1, 2, 20))
        spine.setExpression("Constraints[2]", text)
        self.doc.recompute()
        self.assertTrue(spine.isValid(), spine.getStatusString())
        copy = self.copySpineIn(pipe)
        self.assertIsNot(copy, spine)
        self.assertEqual([path for path, _ in expressions(copy)], ["Constraints[2]"])
        # it names the copy, not the original
        self.assertNotIn(spine, copy.OutList)
        # the copy's own Len drives it
        copy.setDatum("Len", App.Units.Quantity("5 mm"))
        copy.recompute()
        self.assertTrue(copy.isValid(), copy.getStatusString())
        self.assertAlmostEqual(copy.Shape.Edges[1].Length, 10, places=6)
        self.assertAlmostEqual(spine.Shape.Edges[1].Length, 20, places=6)
        # deleting constraint 0 renumbers the expression's key with its constraint
        copy.delConstraint(0)
        self.assertEqual([path for path, _ in expressions(copy)], ["Constraints[1]"])
        copy.recompute()
        self.assertTrue(copy.isValid(), copy.getStatusString())
        self.assertAlmostEqual(copy.Shape.Edges[1].Length, 10, places=6)
        # an expression naming its own object prints as .Constraints.Len, whatever its spelling
        self.assertEqual(expressions(spine), [("Constraints[2]", ".Constraints.Len * 2")])
        return copy

    def testIndependentCopyOwnsItsExpressions(self):
        """ops#236: copyOwnsItsExpression with the owner's own spelling."""
        copy = self.copyOwnsItsExpression(".Constraints.Len * 2")
        self.assertEqual(expressions(copy), [("Constraints[1]", ".Constraints.Len * 2")])

    def testIndependentCopyOwnsItsNamedExpressions(self):
        """PR 224 review M1: copyOwnsItsExpression with the spine named (Spine.Constraints.Len).
        The expression is made again from its text, which names its own object as
        .Constraints.Len: it reads the copy, not the original."""
        self.copyOwnsItsExpression("Spine.Constraints.Len * 2")

    def testIndependentCopyOwnsItsLabelledExpressions(self):
        """PR 224 review M1: as testIndependentCopyOwnsItsNamedExpressions, by label."""
        self.copyOwnsItsExpression("<<Spine label>>.Constraints.Len * 2")

    def pipeOnAnOutsideEdge(self, feature, where, x, y, placement=None):
        """A Pipe in self.body (made if missing) whose spine is feature's edge with its centre of
        mass at `where` (in its container's frame: feature.Shape is placed), and whose profile is a 2 x 2 square around
        (x, y) in the body (on its XY plane, or at `placement`); recomputed. The square overlaps a primitive copy, which fuses with the
        pipe once it's in the body (ops#244 P3)."""
        self.body = self.body if getattr(self, "body", None) else models.body(self.doc)
        self.profile = models.sketch(
            self.doc,
            "Profile",
            models.rectangle(x - 1, y - 1, x + 1, y + 1),
            self.body,
            placement=placement,
        )
        self.doc.recompute()
        [sub] = [
            f"Edge{i}"
            for i, e in enumerate(feature.Shape.Edges, 1)
            if (e.CenterOfMass - where).Length < 1e-6
        ]
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (feature, [sub])
        self.doc.recompute()
        return pipe

    def assertCopiedEdgeAt(self, pipe, globalCentre):
        """The pipe's spine is a copy in its body whose edge has its centre at globalCentre, and
        the pipe sweeps the 2 x 2 profile 10 along it: V = 40."""
        copy = pipe.Spine[0]
        self.assertTrue(self.body.hasObject(copy))
        edge = copy.getSubObject(pipe.Spine[1][0])
        centre = self.body.getGlobalPlacement().multVec(edge.CenterOfMass)
        self.assertLess((centre - globalCentre).Length, 1e-6, centre)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 40, places=3)

    def testIndependentCopyInAPlacedBody(self):
        """PR 224 review M2 (ops#241): testPipeDependentCopyInAPlacedBody's model (the spine a
        vertical edge of a box in another body moved by (5, 0, 0)) with Make independent copy.
        The copy keeps the box's global place: its edge is the picked one, at x = 5 (the copy
        kept the box's Placement in its own body, at the origin: the edge at x = 0, silently)."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        self.doc.recompute()
        pipe = self.pipeOnAnOutsideEdge(box, V(0, 0, 5), 5, 0)
        copy = self.copySpineIn(pipe)
        self.assertTrue(copy.Placement.isSame(other.Placement, 1e-9), copy.Placement)
        self.assertCopiedEdgeAt(pipe, V(5, 0, 5))

    def testIndependentCopyWithAPlacementExpression(self):
        """PR 224 round 2 (verification 1): as testIndependentCopyInAPlacedBody, the box placed by
        the expression Placement.Base.x = 1 mm: globally at x = 6. The copy's Placement is
        converted to its body, so the expression isn't made again on it (its recompute moved the
        copy back to x = 1, silently): its edge is at x = 6."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        box.setExpression(".Placement.Base.x", "1 mm")
        self.doc.recompute()
        pipe = self.pipeOnAnOutsideEdge(box, V(1, 0, 5), 6, 0)
        copy = self.copySpineIn(pipe)
        self.assertEqual(expressions(copy), [])
        self.assertCopiedEdgeAt(pipe, V(6, 0, 5))

    def testIndependentCopyOfAPadInAPlacedBody(self):
        """PR 224 round 2 (verification 2, decision 40): the spine is a vertical edge of a pad in
        another body moved by (5, 0, 0). Its independent copy is a shape binder, which kept the
        pad's Placement in its own body: the edge at x = 0. It lands where picked, x = 5."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        sketch = models.sketch(self.doc, "Base", models.rectangle(0, 0, 20, 20), other)
        pad = other.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        pipe = self.pipeOnAnOutsideEdge(pad, V(0, 0, 5), 5, 0)
        copy = self.copySpineIn(pipe)
        self.assertEqual(copy.TypeId, "PartDesign::ShapeBinder")
        self.assertCopiedEdgeAt(pipe, V(5, 0, 5))

    def testIndependentCopyIntoAPlacedBody(self):
        """PR 224 round 2 (verification 4): the box's body is turned 90 degrees about X and moved
        by (0, 0, 7), the pipe's body turned 90 degrees about Z and moved by (3, 0, 0). The copy's
        Placement is the box's global one in the pipe's body's frame (T^-1 * G; G * T^-1, the
        wrong order, passed with the box's body at the origin): its edge is globally where
        picked. The box's edge x = 20, y = 0 along Z (centre (20, 0, 5)) is globally along -Y,
        centre (20, -5, 7)."""
        other = models.body(self.doc)
        other.Placement = App.Placement(V(0, 0, 7), App.Rotation(V(1, 0, 0), 90))
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        self.body = models.body(self.doc)
        self.body.Placement = App.Placement(V(3, 0, 0), App.Rotation(Z, 90))
        self.doc.recompute()
        self.assertLess((other.Placement.multVec(V(20, 0, 5)) - V(20, -5, 7)).Length, 1e-9)
        # the profile across the edge at its start, (20, 0, 7) globally, in the pipe's body
        profile = self.body.Placement.inverse() * App.Placement(
            V(20, 0, 7), App.Rotation(V(1, 0, 0), 90)
        )
        pipe = self.pipeOnAnOutsideEdge(box, V(20, 0, 5), 0, 0, profile)
        copy = self.copySpineIn(pipe)
        self.assertTrue(
            (self.body.Placement * copy.Placement).isSame(
                other.Placement * box.Placement, 1e-9
            ),
            copy.Placement,
        )
        self.assertCopiedEdgeAt(pipe, V(20, -5, 7))

    def testIndependentCopyOfAPadIntoARotatedBody(self):
        """PR 224 round 2 (verification 4): testIndependentCopyOfAPadInAPlacedBody with the
        pipe's body turned 90 degrees about Z and moved by (3, 0, 0): the shape binder's
        Placement takes the target's inverse (its T^-1 was never run with a target at the
        origin). The pad's edge (0, 0, 0..10) of its body at (5, 0, 0) is globally at x = 5."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        sketch = models.sketch(self.doc, "Base", models.rectangle(0, 0, 20, 20), other)
        pad = other.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        self.body = models.body(self.doc)
        self.body.Placement = App.Placement(V(3, 0, 0), App.Rotation(Z, 90))
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        start = self.body.Placement.inverse().multVec(V(5, 0, 0))
        pipe = self.pipeOnAnOutsideEdge(pad, V(0, 0, 5), start.x, start.y)
        copy = self.copySpineIn(pipe)
        self.assertEqual(copy.TypeId, "PartDesign::ShapeBinder")
        self.assertCopiedEdgeAt(pipe, V(5, 0, 5))

    def testNewSketchOnACopiedBoxFromAPlacedBody(self):
        """PR 224 review M2: New Sketch on the end face x = 20 of a 20 x 10 x 10 box in another
        body moved by (5, 0, 0), Make independent copy: the sketch is on the picked plane,
        globally x = 25 (the copy sat at x = 0 in its own body, so the sketch went on x = 20)."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        self.body = models.body(self.doc)
        self.doc.recompute()
        end = self.boxElement(box, "Face", lambda p: abs(p.x - 20) < 1e-6)
        sketch = self.newSketchOnCopiedFace(box, end)
        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertEqual(sketch.AttachmentSupport, [(copy, (end,))])
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        normal = sketch.getGlobalPlacement().Rotation.multVec(Z)
        self.assertAlmostEqual(abs(normal.x), 1, places=6)
        self.assertAlmostEqual(sketch.getGlobalPlacement().Base.x, 25, places=6)

    def testIndependentCopyWithADynamicProperty(self):
        """ops#236 (PR 215 verification N2): the spine outside the body has a dynamic property
        (Extra = 3), listed before the static ones. The copy's properties are paired by name: the
        copy gets Extra = 3 and the spine's geometry (V = 120). The two lists were walked side by
        side, so every property was pasted one place off."""
        pipe = self.rod(spineInBody=False)
        self.spine.addProperty("App::PropertyFloat", "Extra", "Test")
        self.spine.Extra = 3
        self.doc.recompute()
        copy = self.copySpineIn(pipe)
        self.assertEqual(copy.Extra, 3)
        self.assertEqual(len(copy.Geometry), 2)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)

    def testIndependentCopyOfAPlacedPrimitive(self):
        """ops#241: the spine is a vertical edge of a 10 mm box at (5, 5, 10) in another body.
        The independent copy keeps the box's place: OK closes, and the copy's edge is the box's,
        from (5, 5, 10) to (5, 5, 20). With 7801f7c453's makeCopy the Pipe panel stopped on Edge1
        ("would name another element on a copy"); Placement has no group, so it was never
        skipped with the Attachment group (PR 224 review L1)."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Placement.Base = V(5, 5, 10)
        self.body = models.body(self.doc)
        self.profile = models.sketch(self.doc, "Profile", models.rectangle(4, 4, 6, 6), self.body, z=10)
        self.doc.recompute()
        [sub] = [
            f"Edge{i}"
            for i, e in enumerate(box.Shape.Edges, 1)
            if (e.CenterOfMass - V(5, 5, 15)).Length < 1e-6
        ]
        pipe = self.body.newObject("PartDesign::AdditivePipe", "Pipe")
        pipe.Profile = self.profile
        pipe.Spine = (box, [sub])
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        copy = self.copySpineIn(pipe)
        self.assertIsNot(copy, box)
        self.assertEqual(copy.MapMode, "Deactivated")
        self.assertTrue(copy.Placement.isSame(box.Placement, 1e-9), copy.Placement)
        edge = copy.getSubObject(pipe.Spine[1][0])
        self.assertLess((edge.CenterOfMass - V(5, 5, 15)).Length, 1e-6)
        self.assertAlmostEqual(edge.Length, 10, places=6)

    # -- ops#244, ops#245: copies of a datum, of a sketch outside any body, picked elements -----

    def attachDatumAcross(self, datumType, support, mode, choice="radioIndependent"):
        """A datum of datumType in self.body attached to `support` (a list of (object, sub)) in
        another body by `mode`, then OK on its panel answered with `choice`: the support is copied
        into the body (TaskDatumParameters' accept). Returns the datum."""
        datum = self.body.newObject(datumType, "Datum")
        datum.AttachmentSupport = support
        datum.MapMode = mode
        self.doc.recompute()
        self.edit(datum)
        self.answerModals(choice)
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        return datum

    def datumPointAcross(self, choice, placed=True):
        """ops#244 P6: a datum point in this body (at (0, 0, 10) if placed) attached to a datum
        point at (1, 2, 3) in another body (if placed, turned 90 degrees about Z and moved by
        (5, 0, 0): globally (3, 1, 3)). makeCopy's datum branch made an abstract Part::Datum
        (nothing) and dereferenced it. The copy is a datum point in this body, and the datum is
        where the point is."""
        other = models.body(self.doc)
        point = other.newObject("PartDesign::Point", "Point")
        point.Placement.Base = V(1, 2, 3)
        self.body = models.body(self.doc)
        where = V(1, 2, 3)
        if placed:
            other.Placement = App.Placement(V(5, 0, 0), App.Rotation(Z, 90))
            self.body.Placement.Base = V(0, 0, 10)
            where = V(3, 1, 3)
        self.doc.recompute()
        self.assertLess((point.getGlobalPlacement().Base - where).Length, 1e-9)
        datum = self.attachDatumAcross("PartDesign::Point", [(point, "")], "Vertex", choice)
        copy = self.doc.getObject("CopyPoint" if choice == "radioIndependent" else "ReferencePoint")
        self.assertIsNotNone(copy)
        self.assertEqual(copy.TypeId, "PartDesign::Point")
        self.assertTrue(self.body.hasObject(copy))
        self.assertEqual(datum.AttachmentSupport, [(copy, ("",))])
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        self.assertLess((copy.getGlobalPlacement().Base - where).Length, 1e-6)
        self.assertLess((datum.getGlobalPlacement().Base - where).Length, 1e-6)
        return copy, point

    def testDatumOnAnIndependentCopyOfADatumPoint(self):
        """ops#244 P6, Make independent copy: the copy isn't attached."""
        copy, _ = self.datumPointAcross("radioIndependent")
        self.assertEqual(copy.MapMode, "Deactivated")

    def testDatumOnADependentCopyOfADatumPoint(self):
        """ops#244 P6, Make dependent copy: the copy is attached to the point. With the bodies at
        the origin: attached across bodies, a dependent copy takes the point's place in its own
        body as its place in this one, as the dependent shape binder does (listed on ops#244)."""
        copy, point = self.datumPointAcross("radioDependent", placed=False)
        self.assertEqual(copy.AttachmentSupport, [(point, ("",))])

    def testDatumOnACopiedOriginPlane(self):
        """ops#244 P6: a datum plane in this body attached to the XZ plane of another body's
        origin (the body turned 90 degrees about Z and moved by (5, 0, 0): globally the plane
        x = 5, normal along X), Make independent copy. The copy, a shape binder, was built from
        itself (empty), so the datum had nothing to attach to. It holds the plane where it is."""
        other = models.body(self.doc)
        other.Placement = App.Placement(V(5, 0, 0), App.Rotation(Z, 90))
        xz = models.originFeature(other, "XZ_Plane")
        self.body = models.body(self.doc)
        self.doc.recompute()
        datum = self.attachDatumAcross("PartDesign::Plane", [(xz, "")], "FlatFace")
        copy = datum.AttachmentSupport[0][0]
        self.assertEqual(copy.TypeId, "PartDesign::ShapeBinder")
        self.assertTrue(self.body.hasObject(copy))
        self.assertEqual(len(copy.Shape.Faces), 1)
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        placement = datum.getGlobalPlacement()
        self.assertAlmostEqual(abs(placement.Rotation.multVec(Z).x), 1, places=6)
        self.assertAlmostEqual(placement.Base.x, 5, places=6)

    def testDatumOnAFaceOfACopiedBox(self):
        """ops#244 P2: a datum plane attached to the top face (z = 10, not Face1) of a 10 mm box
        in another body, Make independent copy. The datum's sub on the copy was empty: it lost
        the picked face. It is the picked face on the copy."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        self.doc.recompute()
        top = self.boxElement(box, "Face", lambda p: abs(p.z - 10) < 1e-6)
        datum = self.attachDatumAcross("PartDesign::Plane", [(box, top)], "FlatFace")
        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertEqual(datum.AttachmentSupport, [(copy, (top,))])
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        placement = datum.getGlobalPlacement()
        self.assertAlmostEqual(abs(placement.Rotation.multVec(Z).z), 1, places=6)
        self.assertAlmostEqual(placement.Base.z, 10, places=6)

    def testDatumOnAFaceOfACopiedPad(self):
        """ops#244 P2: as testDatumOnAFaceOfACopiedBox on the top face of a 20 x 20 x 10 pad,
        whose copy is a shape binder of that face alone: the datum is on its Face1."""
        other = models.body(self.doc)
        sketch = models.sketch(self.doc, "Base", models.rectangle(0, 0, 20, 20), other)
        pad = other.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        self.body = models.body(self.doc)
        self.doc.recompute()
        [top] = [
            f"Face{i}"
            for i, f in enumerate(pad.Shape.Faces, 1)
            if abs(f.CenterOfMass.z - 10) < 1e-6
        ]
        datum = self.attachDatumAcross("PartDesign::Plane", [(pad, top)], "FlatFace")
        copy = datum.AttachmentSupport[0][0]
        self.assertEqual(copy.TypeId, "PartDesign::ShapeBinder")
        self.assertEqual(datum.AttachmentSupport, [(copy, ("Face1",))])
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        self.assertAlmostEqual(datum.getGlobalPlacement().Base.z, 10, places=6)

    def testDatumOnAStaleCopiedBoxStops(self):
        """ops#244 P2, the check: the box was lengthened to 20 and not recomputed, so the picked
        face (the end x = 10) is at x = 20 on its recomputed copy. OK stops with a message, the
        panel stays, and no copy is left."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        self.doc.recompute()
        end = self.boxElement(box, "Face", lambda p: abs(p.x - 10) < 1e-6)
        datum = self.body.newObject("PartDesign::Plane", "Datum")
        datum.AttachmentSupport = [(box, end)]
        datum.MapMode = "FlatFace"
        self.doc.recompute()
        box.Length = 20
        self.edit(datum)
        self.answerModals()
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: " + end), self.modals)
        self.assertIsNotNone(Gui.Control.activeDialog())
        self.assertEqual([o.Name for o in self.doc.Objects if o.Name.startswith("CopyBox")], [])
        self.assertEqual(datum.AttachmentSupport, [(box, (end,))])

    def testNewSketchOnTheTopFaceOfACopiedPrimitiveOnABase(self):
        """ops#244 P1: New Sketch on Box's top face (z = 20, not Face1) in primitivesOnABase,
        Make independent copy. The copy keeps its pasted shape (not recomputed: a primitive on a
        base), and the sketch went on its Face1 (the base's side, x = -5) whatever face was
        picked. It links the picked face, the same index on the copy; the command's recompute
        then makes the copy the bare box (ops#244 P5), whose top face is the same plane."""
        box, _ = self.primitivesOnABase()
        top = self.boxElement(box, "Face", lambda p: abs(p.z - 20) < 1e-6)
        sketch = self.newSketchOnCopiedFace(box, top)
        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertEqual(sketch.AttachmentSupport[0][0], copy)
        self.doc.recompute()
        normal = sketch.getGlobalPlacement().Rotation.multVec(Z)
        self.assertAlmostEqual(abs(normal.z), 1, places=6)
        self.assertAlmostEqual(sketch.getGlobalPlacement().Base.z, 20, places=6)

    def testRevolutionAxisOnAnEdgeOfACopiedPrimitiveOnABase(self):
        """ops#244 P1 (getReferencedSelection): the Revolution's axis picked on Box's edge
        x = 10, y = 0 along Z (not Edge1) in primitivesOnABase, Make independent copy. The axis
        went to the copy's Edge1 whatever edge was picked; it is the picked edge, the same line on
        the copy (checked at the pick: ops#244 P3)."""
        box, _ = self.primitivesOnABase()
        ring = models.sketch(self.doc, "Ring", models.rectangle(1, 0, 3, 2), self.body, placement=XZ)
        self.doc.recompute()
        edge = self.boxElement(
            box, "Edge", lambda p: abs(p.x - 10) < 1e-6 and abs(p.y) < 1e-6 and p.z > 10
        )
        revolution = self.body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = ring
        revolution.ReferenceAxis = (ring, ["V_Axis"])
        revolution.Angle = 360
        self.doc.recompute()
        self.edit(revolution)
        self.armAxisField()
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, box.Name, edge)
        self.assertTrue(waitFor(lambda: self.modals), "no copy dialog")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertEqual(revolution.ReferenceAxis, (copy, [edge]))
        picked = copy.Shape.getElement(edge)
        self.assertAlmostEqual(picked.CenterOfMass.x, 10, places=6)
        self.assertAlmostEqual(picked.CenterOfMass.y, 0, places=6)
        self.assertAlmostEqual(abs(picked.Curve.Direction.z), 1, places=6)
        self.close(ok=False)

    def testPadOfASketchCopiedIntoARotatedBody(self):
        """ops#245: Pad with nothing selected, and in its pick dialog a sketch outside any body
        (a 10 x 10 square at (2, 3, 5), turned 15 degrees about Z), Make independent copy, into a
        body turned 30 degrees about X. fixSketchSupport threw ("Sketch plane cannot be
        migrated"), and the dialog's worker called front() on the empty list. The copy is
        attached to the body's XY plane with an offset that keeps it where the sketch is
        (decision 40; fixSketchSupport also dropped the offset and turn in the plane), and the pad
        is 10 x 10 x 10 on it."""
        sketch = models.sketch(
            self.doc,
            "Free",
            models.rectangle(0, 0, 10, 10),
            None,
            placement=App.Placement(V(2, 3, 5), App.Rotation(Z, 15)),
        )
        self.body = models.body(self.doc)
        self.body.Placement.Rotation = App.Rotation(V(1, 0, 0), 30)
        self.doc.recompute()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body)
        Gui.runCommand("PartDesign_Pad")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no pick dialog")
        pump(0.3)
        Gui.Control.showTaskView()
        self.widget(QtWidgets.QCheckBox, "checkOtherPart").setChecked(True)
        listWidget = self.widget(QtWidgets.QListWidget, "listWidget")
        [item] = [
            listWidget.item(i)
            for i in range(listWidget.count())
            if listWidget.item(i).text().startswith("Free ")
        ]
        self.assertFalse(item.isHidden())
        item.setSelected(True)
        self.assertTrue(self.widget(QtWidgets.QRadioButton, "radioIndependent").isChecked())
        self.answerModals()
        ok = QtWidgets.QDialogButtonBox.Ok
        self.assertTrue(waitFor(lambda: taskButton(ok) is not None, 5.0), "no OK")
        taskButton(ok).click()
        self.assertTrue(
            waitFor(lambda: self.doc.getObject("Pad") is not None, 5.0),
            f"no pad; modals {self.modals}",
        )
        pad = self.doc.getObject("Pad")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog(), 5.0), "no pad panel")
        pump(0.3)
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, [])
        copy = pad.Profile[0]
        self.assertIsNot(copy, sketch)
        self.assertTrue(self.body.hasObject(copy))
        self.assertEqual(copy.MapMode, "FlatFace")
        self.doc.recompute()
        self.assertTrue(copy.getGlobalPlacement().isSame(sketch.getGlobalPlacement(), 1e-9))
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 1000, places=3)
