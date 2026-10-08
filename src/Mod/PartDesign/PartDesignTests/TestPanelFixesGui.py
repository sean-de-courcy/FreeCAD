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

from PartDesignTests.Scenarios import models
from PartDesignTests.Scenarios.harness import Z, face
from PartDesignTests.TestDressUpDeleteKeyGui import reportText
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor

V = App.Vector
XZ = App.Placement(V(0, 0, 0), App.Rotation(V(1, 0, 0), 90))  # sketch y -> global z


def line(x0, y0, x1, y1):
    return Part.LineSegment(V(x0, y0, 0), V(x1, y1, 0))


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

    def edit(self, obj):
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
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        self.assertIn("Warning", pipe.State)
        self.assertEqual([(r["property"], r["index"]) for r in App.getReferenceReport(pipe)], report)

    def testPipeCopyThatFailsIsNamed(self):
        """ops#234: the spine outside the body has conflicting constraints (its first line 10 and
        20 long), so its copy doesn't recompute either. OK names the copy and why in the Report
        view. The copy's result was ignored."""
        import Sketcher

        pipe = self.rod(spineInBody=False)
        self.spine.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 10))
        self.spine.addConstraint(Sketcher.Constraint("DistanceY", 0, 1, 0, 2, 20))
        self.doc.recompute()
        self.assertFalse(self.spine.isValid())
        reportStart = len(reportText() or "")
        self.edit(pipe)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        self.assertIn(
            "Pipe: the copy 'CopySpine' of 'Spine' doesn't recompute: Sketch with conflicting",
            (reportText() or "")[reportStart:],
        )

    def testPipeCopyAbortedWithThePipe(self):
        """ops#234 (PR 211 review): the profile is open (three sides of the square), so the pipe
        fails. OK copies the spine from outside the body, recomputes it, then fails on the pipe
        (Input Error) and aborts: the copy is gone, the spine is the original again and the body
        is as before."""
        pipe = self.rod(spineInBody=False)
        self.profile.deleteAllGeometry()
        self.profile.addGeometry(models.polyline([(-1, -1), (1, -1), (1, 1), (-1, 1)]), False)
        self.doc.recompute()
        self.assertFalse(pipe.isValid())
        before = self.body.Group
        self.edit(pipe)
        self.answerModals()
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2, 5.0), self.modals)
        self.answering = False
        pump(0.2)
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: "), self.modals)
        self.assertIsNone(self.doc.getObject("CopySpine"))
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(self.body.Group, before)

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
