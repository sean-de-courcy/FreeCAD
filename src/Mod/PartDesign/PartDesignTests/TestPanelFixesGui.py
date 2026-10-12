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

    # -- ops#276: Migrate relinks the links to a legacy feature ---------------------------------

    def namedFace(self, shape, name):
        """The face's centre and normal: what a link to it names, geometrically."""
        found = shape.getElement(name)
        return found.CenterOfMass, found.normalAt(0, 0)

    def assertSameFace(self, shape, name, expected):
        centre, normal = self.namedFace(shape, name)
        self.assertLess((centre - expected[0]).Length, 1e-6, name)
        self.assertLess((normal - expected[1]).Length, 1e-6, name)

    def migrate(self):
        """Runs Migrate, answering any modal; asserts none was shown."""
        Gui.activateWorkbench("PartDesignWorkbench")
        self.answerModals()
        Gui.runCommand("PartDesign_Migrate")
        pump()
        self.answering = False
        self.assertEqual(self.modals, [])
        self.doc.recompute()

    def testMigrateRelinksElementLinks(self):
        """ops#276 (fork PR 255 review): two legacy boxes outside a body, the second on the first,
        and a FeaturePython linking them by a PropertyLinkSubList, a PropertyLinkSub and two
        PropertyXLinkSub. The link to the first box (not a PartDesign object) makes Migrate split
        the chain: a body per box. Each link moves to its box's body with its element: the
        PropertyLinkSub was written without its object and refused (an error box, the link left on
        the box), and a PropertyXLinkSub, which derives from PropertyLink, moved as a whole object
        and lost its element. Each element names the same face after a recompute (fork PR 274
        review, M1)."""
        box1 = self.doc.addObject("PartDesign::AdditiveBox", "Box1")
        box2 = self.doc.addObject("PartDesign::AdditiveBox", "Box2")
        box2.BaseFeature = box1
        box2.Placement = App.Placement(App.Vector(5, 0, 0), App.Rotation())
        user = self.doc.addObject("App::FeaturePython", "User")
        user.addProperty("App::PropertyLinkSubList", "Many")
        user.addProperty("App::PropertyLinkSub", "One")
        user.addProperty("App::PropertyXLinkSub", "Cross")
        user.addProperty("App::PropertyXLinkSub", "CrossLast")
        user.Many = [(box1, "Face3"), (box2, "")]
        user.One = (box2, "Face1")
        user.Cross = (box1, ["Face2"])
        user.CrossLast = (box2, ["Face4"])
        self.doc.recompute()
        before = {
            "Face3": self.namedFace(box1.Shape, "Face3"),
            "Face2": self.namedFace(box1.Shape, "Face2"),
            "Face1": self.namedFace(box2.Shape, "Face1"),
            "Face4": self.namedFace(box2.Shape, "Face4"),
        }
        self.migrate()
        body1 = self.doc.getObject("Box1Body")
        body2 = self.doc.getObject("Box2Body")
        self.assertIsNotNone(body1)
        self.assertIsNotNone(body2)
        self.assertIn(box1, body1.Group)
        self.assertIn(box2, body2.Group)
        many = [(obj.Name, sub) for obj, subs in user.Many for sub in subs]
        self.assertEqual(many, [(body1.Name, "Face3"), (body2.Name, "")])
        self.assertEqual((user.One[0].Name, list(user.One[1])), (body2.Name, ["Face1"]))
        self.assertEqual((user.Cross[0].Name, list(user.Cross[1])), (body1.Name, ["Face2"]))
        self.assertEqual(
            (user.CrossLast[0].Name, list(user.CrossLast[1])), (body2.Name, ["Face4"])
        )
        self.assertSameFace(body1.Shape, "Face3", before["Face3"])
        self.assertSameFace(body1.Shape, "Face2", before["Face2"])
        self.assertSameFace(body2.Shape, "Face1", before["Face1"])
        self.assertSameFace(body2.Shape, "Face4", before["Face4"])

    def testMigrateKeepsAnElementOfAFeatureBeforeTheLast(self):
        """Fork PR 274 review, M2: a group's PropertyXLinkSub names Face3 of the first of two
        legacy boxes, the second on the first. A group doesn't split the chain, so both boxes go
        into one body, whose shape is the second box's: its Face3 would be another face. The link
        stays on the first box, naming the same face, with a warning."""
        box1 = self.doc.addObject("PartDesign::AdditiveBox", "Box1")
        box2 = self.doc.addObject("PartDesign::AdditiveBox", "Box2")
        box2.BaseFeature = box1
        box2.Placement = App.Placement(App.Vector(5, 0, 0), App.Rotation())
        group = self.doc.addObject("App::DocumentObjectGroupPython", "Group")
        group.addProperty("App::PropertyXLinkSub", "Cross")
        group.Cross = (box1, ["Face3"])
        self.doc.recompute()
        before = self.namedFace(box1.Shape, "Face3")
        self.migrate()
        body = box1.getParentGeoFeatureGroup()
        self.assertIsNotNone(body)
        self.assertIs(box2.getParentGeoFeatureGroup(), body)
        self.assertEqual((group.Cross[0].Name, list(group.Cross[1])), (box1.Name, ["Face3"]))
        self.assertSameFace(box1.Shape, "Face3", before)
        report = reportText()
        self.assertIsNotNone(report, "no Report view")
        self.assertIn("Group.Cross keeps its link to", report)

    def testMigrateKeepsAWholeLinkToAFeatureBeforeTheLast(self):
        """Fork PR 274 round 1 verification: a group's PropertyLink, PropertyXLink (without
        elements) and PropertyLinkList name the first of two legacy boxes, the second on the
        first. A group doesn't split the chain, so both boxes go into one body, whose shape is the
        second box's: on the body, each link would name both boxes. They stay on the first box,
        whose shape is as before, with a warning each."""
        box1 = self.doc.addObject("PartDesign::AdditiveBox", "Box1")
        box2 = self.doc.addObject("PartDesign::AdditiveBox", "Box2")
        box2.BaseFeature = box1
        box2.Placement = App.Placement(App.Vector(5, 0, 0), App.Rotation())
        group = self.doc.addObject("App::DocumentObjectGroupPython", "Group")
        group.addProperty("App::PropertyLink", "Whole")
        group.addProperty("App::PropertyXLink", "WholeX")
        group.addProperty("App::PropertyLinkList", "Several")
        group.Whole = box1
        group.WholeX = box1
        group.Several = [box1]
        self.doc.recompute()
        self.assertAlmostEqual(box1.Shape.Volume, 1000, places=6)
        self.migrate()
        body = box1.getParentGeoFeatureGroup()
        self.assertIsNotNone(body)
        self.assertIs(box2.getParentGeoFeatureGroup(), body)
        self.assertAlmostEqual(body.Shape.Volume, 1500, places=6)
        self.assertIs(group.Whole, box1)
        self.assertIs(group.WholeX, box1)
        self.assertEqual(group.Several, [box1])
        self.assertAlmostEqual(group.Whole.Shape.Volume, 1000, places=6)
        report = reportText()
        self.assertIsNotNone(report, "no Report view")
        for name in ("Whole", "WholeX", "Several"):
            self.assertIn(f"Group.{name} keeps its link to", report)

    def testMigrateRelinksAnAppLinkToAnElement(self):
        """Fork PR 274 review, L3: an App::Link whose LinkedObject (a plain PropertyXLink) names
        Face1 of a legacy box. Migrate moves it to the box's body with its element, which names
        the same face; it became a link to the whole body, without a message."""
        box = self.doc.addObject("PartDesign::AdditiveBox", "Box1")
        link = self.doc.addObject("App::Link", "Lnk")
        link.LinkedObject = (box, ["Face1"])
        self.doc.recompute()
        before = self.namedFace(box.Shape, "Face1")
        self.migrate()
        body = box.getParentGeoFeatureGroup()
        self.assertIsNotNone(body)
        target, subs = link.LinkedObject
        subs = [subs] if isinstance(subs, str) else list(subs)
        self.assertEqual((target.Name, subs), (body.Name, ["Face1"]))
        self.assertSameFace(body.Shape, "Face1", before)

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
        body moved by (5, 0, 0). Make dependent copy: no false stop, and the pipe sweeps the
        2 x 2 profile 10 up: V = 40. Since ops#244 the copy traces its support, so its edge is
        where the box's is, globally at x = 5 (both are compared globally)."""
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
        self.assertTrue(pipe.Spine[0].TraceSupport)
        self.assertCopiedEdgeAt(pipe, V(5, 0, 5))

    def testPipeDependentCopyIntoAPlacedBody(self):
        """PR 244 review H1: testPipeDependentCopyInAPlacedBody's model with the pipe's body moved
        by (1, 2, 10) and turned 30 degrees about X, and its 2 x 2 profile placed in it at the
        bottom of the spine (globally the square around (5, 0, 0) in the plane z = 0). The panel
        recomputes the copy at the root, then adds it to the body: it kept the place it had at
        the root, so the spine sat off by the body's placement, silently. Its edge is where the
        box's is, globally at x = 5, and the pipe sweeps the profile 10 up: V = 40, as OK leaves
        it."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        self.body = models.body(self.doc)
        self.body.Placement = App.Placement(V(1, 2, 10), App.Rotation(V(1, 0, 0), 30))
        bottom = self.body.Placement.inverse().multiply(App.Placement(V(5, 0, 0), App.Rotation()))
        self.profile = models.sketch(
            self.doc, "Profile", models.rectangle(-1, -1, 1, 1), self.body, placement=bottom
        )
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
        self.assertIsNot(pipe.Spine[0], box)
        self.assertTrue(pipe.Spine[0].TraceSupport)
        # as OK leaves it (PR 244 verification 1: the pipe was built along the copy's place at
        # the root, and the copy was left touched)
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])
        self.assertAlmostEqual(pipe.Shape.Volume, 40, places=3)
        swept = pipe.Shape.copy()
        swept.Placement = self.body.getGlobalPlacement().multiply(swept.Placement)
        box = swept.BoundBox
        for got, want in zip(
            (box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax), (4, 6, -1, 1, 0, 10)
        ):
            self.assertAlmostEqual(got, want, places=6, msg=box)
        self.assertCopiedEdgeAt(pipe, V(5, 0, 5))

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

    def visible(self, obj):
        return obj.ViewObject.Visibility

    def testPipeRecomputeFailureWithoutCopyKeepsTheEdit(self):
        """ops#253 (PR 226 review L1 and test gap): the Rod (all in the body), its spine and
        profile hidden, as after the pipe's creation; in the edit the profile is opened, so OK
        fails on the pipe with no copy step: the message says the edit is still open (no word
        of a copy), the panel and the edit's transaction stay open, and the spine and profile are
        still shown (they went back to hidden under the open panel). Cancel restores the closed
        profile and hides them again, with nothing to undo."""
        pipe = self.rod()
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.spine.ViewObject.Visibility = False
        self.profile.ViewObject.Visibility = False
        undos = self.doc.UndoCount
        self.edit(pipe)
        self.assertTrue(self.visible(self.spine))
        self.assertTrue(self.visible(self.profile))
        self.openProfile()
        self.answerModals()
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: len(self.modals) >= 1, 5.0), self.modals)
        self.answering = False
        pump(0.2)
        self.assertEqual(len(self.modals), 1, self.modals)
        self.assertIn("Wire is not closed.", self.modals[0])
        self.assertIn("The edit is still open.", self.modals[0])
        self.assertNotIn("copy", self.modals[0])
        self.assertIsNotNone(Gui.Control.activeDialog(), "OK closed the panel")
        self.assertNotEqual(self.doc.getBookedTransactionID(), 0, "the edit's transaction ended")
        self.assertTrue(self.visible(self.spine), "the spine went back to hidden")
        self.assertTrue(self.visible(self.profile), "the profile went back to hidden")
        self.close(ok=False)
        self.doc.recompute()
        self.assertEqual(len(self.profile.Shape.Edges), 4)
        self.assertFalse(self.visible(self.spine))
        self.assertFalse(self.visible(self.profile))
        self.assertEqual(self.doc.UndoCount, undos)
        self.assertTrue(pipe.isValid(), pipe.getStatusString())

    def testPipeCopyStopShowsTheSpine(self):
        """ops#253 (PR 226 review L1): as failAfterTheCopy with the Rod's spine and profile
        hidden: after the stop the picked spine and the profile are shown."""
        pipe = self.rod()
        self.doc.recompute()
        outer = self.outerSpine()
        self.spine.ViewObject.Visibility = False
        self.profile.ViewObject.Visibility = False
        outer.ViewObject.Visibility = False
        self.edit(pipe)
        pipe.Spine = (outer, ["Edge1", "Edge2"])
        self.openProfile()
        self.assertOkStops(pipe, "Wire is not closed.", edit=False)
        self.assertIs(pipe.Spine[0], outer)
        self.assertTrue(self.visible(outer), "the spine is hidden under the open panel")
        self.assertTrue(self.visible(self.profile), "the profile is hidden under the open panel")

    def testPipeRecomputeFailureRestoresTheSpinesGuess(self):
        """ops#253 (PR 226 review test gap): the spine outside the body is found again by
        geometry (testPipeCopyKeepsTheSpinesGuess), and the profile is opened in the edit. OK
        copies the spine, then fails on the pipe: the restored spine is the original with its
        guess. With the profile closed again the pipe recomputes with the same warning and
        report entries."""
        pipe = self.rod(spineInBody=False)
        self.doc.recompute()
        self.spine.deleteAllGeometry()
        self.spine.addGeometry([line(0, 10, 0, 30), line(0, 0, 0, 10)], False)
        self.doc.recompute()
        self.assertIn("Warning", pipe.State)
        subs = pipe.Spine[1]
        report = [(r["property"], r["index"]) for r in App.getReferenceReport(pipe)]
        self.assertEqual({prop for prop, _ in report}, {"Spine"})
        self.edit(pipe)
        self.openProfile()
        self.assertOkStops(pipe, "Wire is not closed.", edit=False)
        self.assertIs(pipe.Spine[0], self.spine)
        self.assertEqual(pipe.Spine[1], subs)
        self.assertFalse([o for o in self.doc.Objects if o.Name.startswith("Copy")])
        self.closeProfile()
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)
        self.assertIn("Warning", pipe.State)
        self.assertEqual([(r["property"], r["index"]) for r in App.getReferenceReport(pipe)], report)

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
        """ops#243 L3: another document is active when OK is pressed; the pipe's document has an
        object of the copy's name. The stop of testPipeCopyStopKeepsTheEdit removes the copy from
        its own document (the pipe's since ops#244 P4, under another name), and the pipe's
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

    def testPipeCopyGoesIntoItsBodysDocument(self):
        """ops#244 P4: another document is active when OK is pressed (as in
        testPipeCopyStopInAnotherActiveDocument), and the spine outside the body is copied: the
        copy is made in the pipe's document, in its body (it was made in the active one, and the
        body's addObject failed). The other document stays empty; the pipe sweeps the Rod's
        V = 120."""
        pipe = self.rod()
        self.doc.recompute()
        outer = self.outerSpine()
        other = App.newDocument("PanelFixesOther", hidden=True)
        try:
            App.setActiveDocument(self.doc.Name)
            self.edit(pipe)
            pipe.Spine = (outer, ["Edge1", "Edge2"])
            ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
            App.setActiveDocument(other.Name)
            self.answerModals()
            ok.click()
            self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), self.modals)
            pump(0.2)
            self.answering = False
            self.assertEqual(self.modals, ["DlgReference"])
            self.assertEqual([o.Name for o in other.Objects], [])
            copy = pipe.Spine[0]
            self.assertIsNot(copy, outer)
            self.assertIs(copy.Document, self.doc)
            self.assertTrue(self.body.hasObject(copy))
        finally:
            App.setActiveDocument(self.doc.Name)
            App.closeDocument(other.Name)
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        self.assertAlmostEqual(pipe.Shape.Volume, 120, places=3)

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

    def testPipeCopyOfAPrimitiveOnABase(self):
        """ops#234 round (PR 219 review F1), ops#244 P5: the spine is an edge of a box in another
        body that is fused with a base box. A primitive copy took no BaseFeature, so its shape was
        the box alone, where that index is another edge (or none), and OK stopped. The copy is a
        shape binder of the fused shape, which has the edge under its index: OK copies it, and
        the pipe sweeps along it. Model: a base box 20 x 20 x 10 and a box 10 x 10 x 20, both at
        the origin; the spine is the fused shape's vertical edge at x = 20, y = 0 (z 0..10), which
        the box alone hasn't; the profile is a 2 x 2 square around its foot."""
        other = models.body(self.doc)
        base = other.newObject("PartDesign::AdditiveBox", "Base")
        base.Length = 20
        base.Width = 20
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Height = 20
        self.doc.recompute()
        self.assertTrue(box.isValid(), box.getStatusString())
        pipe = self.pipeOnAnOutsideEdge(box, V(20, 0, 5), 20, 0)
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        copy = self.copySpineIn(pipe)
        self.assertIndependentPrimitiveCopy(copy, box)
        self.assertCopiedEdgeAt(pipe, V(20, 0, 5))

    def testIndependentCopyOfAPrimitiveStaysAsCopied(self):
        """ops#244 P3, P5 (the user's answer, 2026-10-11): the spine is a vertical edge of a box
        in another body turned 90 degrees about Z and moved by (5, 0, 0), Make independent copy.
        The copy is a shape binder of the box's shape where the box is, without a link back; one
        undo takes it back with the pipe's change, one redo puts it back; the box lengthened
        afterwards leaves the copy and the pipe as they were. The box's edge x = 0, y = 0 along Z
        is globally at (5, 0, 5)."""
        other = models.body(self.doc)
        other.Placement = App.Placement(V(5, 0, 0), App.Rotation(Z, 90))
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        box.Width = 20
        self.doc.recompute()
        pipe = self.pipeOnAnOutsideEdge(box, V(0, 0, 5), 5, 0)
        before = self.body.Group
        copy = self.copySpineIn(pipe)
        self.assertIndependentPrimitiveCopy(copy, box)
        self.assertCopiedEdgeAt(pipe, V(5, 0, 5))

        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("CopyBox"))
        self.assertIs(pipe.Spine[0], box)
        self.assertEqual(self.body.Group, before)
        self.doc.redo()
        self.doc.recompute()
        copy = self.doc.getObject("CopyBox")
        self.assertIs(pipe.Spine[0], copy)
        self.assertIndependentPrimitiveCopy(copy, box)

        volume = copy.Shape.Volume
        bounds = copy.Shape.BoundBox
        box.Length = 30
        self.doc.recompute()
        self.assertAlmostEqual(box.Shape.Volume, 30 * 20 * 10, places=6)
        self.assertTrue(copy.isValid(), copy.getStatusString())
        self.assertAlmostEqual(copy.Shape.Volume, volume, places=6)
        for bound in ["XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"]:
            self.assertAlmostEqual(
                getattr(copy.Shape.BoundBox, bound), getattr(bounds, bound), places=6
            )
        self.assertNotIn(box, copy.OutListRecursive)
        self.assertCopiedEdgeAt(pipe, V(5, 0, 5))

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

    def runNewSketchOnCopiedFace(self, feature, face, choice="radioIndependent"):
        """Runs New Sketch on `face` of feature (in another body) and answers the copy dialog with
        `choice` (Make independent copy), and any message box; the answers go to self.modals."""
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
        self.answerModals(choice)
        Gui.runCommand("PartDesign_NewSketch")

    def newSketchOnCopiedFace(self, feature, face="Face1", choice="radioIndependent"):
        """New Sketch on `face` of feature (in another body), answered with `choice` (Make
        independent copy); returns the sketch, left edit."""
        guiDoc = Gui.getDocument(self.doc.Name)
        self.runNewSketchOnCopiedFace(feature, face, choice)
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

    def assertSameShape(self, copy, original):
        """copy's shape is original's, globally: the same volume, faces and bounding box."""
        def placed(obj):
            shape = obj.Shape.copy()
            shape.Placement = obj.getGlobalPlacement()
            return shape

        shape, expected = placed(copy), placed(original)
        self.assertAlmostEqual(shape.Volume, expected.Volume, places=6)
        self.assertEqual(len(shape.Faces), len(expected.Faces))
        box, expectedBox = shape.BoundBox, expected.BoundBox
        for bound in ["XMin", "YMin", "ZMin", "XMax", "YMax", "ZMax"]:
            self.assertAlmostEqual(
                getattr(box, bound), getattr(expectedBox, bound), places=6, msg=(box, expectedBox)
            )

    def assertIndependentPrimitiveCopy(self, copy, primitive):
        """ops#244 P3, P5 (the user's answer, 2026-10-11): an independent copy of a primitive is a
        shape binder of its shape, without a support or a link back, out of the body's solid
        chain, where the primitive is."""
        self.assertEqual(copy.TypeId, "PartDesign::ShapeBinder")
        self.assertEqual(copy.Support, [])
        self.assertNotIn(primitive, copy.OutListRecursive)
        self.assertNotIn(copy, primitive.InListRecursive)
        self.assertIsNot(self.body.Tip, copy)
        self.assertTrue(
            copy.getGlobalPlacement().isSame(primitive.getGlobalPlacement(), 1e-9),
            (copy.getGlobalPlacement(), primitive.getGlobalPlacement()),
        )
        self.assertSameShape(copy, primitive)

    def testNewSketchOnACopiedPrimitiveOnABase(self):
        """PR 223 review M1, ops#244 P5: as testNewSketchOnAFaceCopiedFromAnotherBody, on Box,
        which sits on Base. A primitive copy took the body's Tip as its BaseFeature (none here),
        so the command's recompute made it the bare box, and the sketch's Face1 (the plane x = -5
        picked) was lost, loudly. The copy is a shape binder of Box's shape (fused with Base), and
        stays so: the sketch is on the picked plane, valid, without a warning."""
        box, _ = self.primitivesOnABase()
        before = len(reportText() or "")
        sketch = self.newSketchOnCopiedFace(box)
        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertIndependentPrimitiveCopy(copy, box)
        # PR 261 review: said, since the user may expect the box alone
        self.assertIn(
            "The copy 'CopyBox' of 'Box' is the body's solid at 'Box' (on 'Base'), not 'Box' alone",
            (reportText() or "")[before:],
        )
        self.assertNotIn("isn't up to date", (reportText() or "")[before:])
        self.assertEqual(sketch.AttachmentSupport, [(copy, ("Face1",))])
        self.doc.recompute()
        self.assertTrue(copy.isValid(), copy.getStatusString())
        self.assertSameShape(copy, box)
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertNotIn("Warning", sketch.State)
        self.assertAlmostEqual(sketch.getGlobalPlacement().Base.x, -5, places=6)

    def testNewSketchOnACopiedSubtractivePrimitive(self):
        """PR 223 review M2, ops#244 P5: New Sketch on a face of Cut (a subtractive box on Box),
        Make independent copy. A primitive copy failed in the body without a base ("Cannot
        subtract primitive feature without base feature"). The copy is a shape binder of Cut's
        shape and recomputes."""
        _, cut = self.primitivesOnABase()
        before = len(reportText() or "")
        self.newSketchOnCopiedFace(cut)
        copy = self.doc.getObject("CopyCut")
        self.assertIsNotNone(copy)
        self.assertIndependentPrimitiveCopy(copy, cut)
        self.doc.recompute()
        self.assertTrue(copy.isValid(), copy.getStatusString())
        self.assertSameShape(copy, cut)
        self.assertNotIn("doesn't recompute", (reportText() or "")[before:])
        self.assertIn(
            "The copy 'CopyCut' of 'Cut' is the body's solid at 'Cut' (on 'Box'), not 'Cut' alone",
            (reportText() or "")[before:],
        )

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

    def testNewSketchOnAStaleCopiedBoxWarns(self):
        """PR 223 review N1, ops#244 P5: the box was lengthened to 20 and not recomputed. A
        primitive copy recomputed itself in makeCopy, and New Sketch stopped, since the picked
        face (the end x = 10) was another face on it. The copy, a shape binder, takes the box's
        shape as shown (x 0..10): the sketch is on the picked face, and the Report view says that
        the box isn't up to date. The box's recompute leaves the copy as it is."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        self.doc.recompute()
        end = self.boxElement(box, "Face", lambda p: abs(p.x - 10) < 1e-6)
        box.Length = 20
        before = len(reportText() or "")
        sketch = self.newSketchOnCopiedFace(box, end)
        self.assertIn(
            "'Box' isn't up to date: its copy 'CopyBox' takes its shape as last computed",
            (reportText() or "")[before:],
        )
        copy = self.doc.getObject("CopyBox")
        self.assertEqual(sketch.AttachmentSupport, [(copy, (end,))])
        self.doc.recompute()
        self.assertAlmostEqual(box.Shape.BoundBox.XMax, 20, places=6)
        self.assertAlmostEqual(copy.Shape.BoundBox.XMax, 10, places=6)
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertAlmostEqual(sketch.getGlobalPlacement().Base.x, 10, places=6)

    def testNewSketchOnACopiedBoxOnAStaleBaseWarns(self):
        """PR 261 review L1: primitivesOnABase, with Base lengthened to 30 and not recomputed. Box
        itself is unchanged, but its recompute would fuse it with the longer base: New Sketch on
        Box's top face (z = 20), Make independent copy, says that Box isn't up to date (only Box's
        own properties were checked)."""
        box, _ = self.primitivesOnABase()
        top = self.boxElement(box, "Face", lambda p: abs(p.z - 20) < 1e-6)
        box.BaseFeature.Length = 30
        self.assertNotIn("Touched", box.State)
        before = len(reportText() or "")
        sketch = self.newSketchOnCopiedFace(box, top)
        copy = self.doc.getObject("CopyBox")
        self.assertEqual(sketch.AttachmentSupport, [(copy, (top,))])
        self.assertIn(
            "'Box' isn't up to date: its copy 'CopyBox' takes its shape as last computed",
            (reportText() or "")[before:],
        )
        self.assertAlmostEqual(copy.Shape.BoundBox.XMax, 15, places=6)

    def testNewSketchOnACopiedPadWithAStaleSketchWarns(self):
        """PR 261 review L1 and nit: a 10 mm pad of a square sketch in another body; the sketch
        widened to 20 and not recomputed. New Sketch on the pad's top face (z = 10), Make
        independent copy (a shape binder of that face), says that the pad isn't up to date: the
        warning isn't the primitives' alone, and it reads what the pad is made from."""
        other = models.body(self.doc)
        square = models.sketch(self.doc, "Square", models.rectangle(0, 0, 10, 10), other)
        pad = models.pad(other, square, 10)
        self.body = models.body(self.doc)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        top = self.boxElement(pad, "Face", lambda p: abs(p.z - 10) < 1e-6)
        models.moveRectangle(square, 0, 0, 20, 10)
        self.assertNotIn("Touched", pad.State)
        before = len(reportText() or "")
        sketch = self.newSketchOnCopiedFace(pad, top)
        copy = self.doc.getObject("CopyPad")
        self.assertEqual(sketch.AttachmentSupport, [(copy, ("Face1",))])
        self.assertIn(
            "'Pad' isn't up to date: its copy 'CopyPad' takes its shape as last computed",
            (reportText() or "")[before:],
        )
        self.assertAlmostEqual(copy.Shape.BoundBox.XMax, 10, places=6)

    def testNewSketchOnACopiedTouchedBoxDoesntWarn(self):
        """PR 261 review L3: a box in another body only touched (no property changed, no
        recompute enforced: touch("")): a recompute wouldn't execute it, so New Sketch on its top
        face, Make independent copy, says nothing about it being out of date. A box without a
        base: no note about one either."""
        other = models.body(self.doc)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        self.body = models.body(self.doc)
        self.doc.recompute()
        top = self.boxElement(box, "Face", lambda p: abs(p.z - 10) < 1e-6)
        box.touch("")
        self.assertIn("Touched", box.State)
        before = len(reportText() or "")
        sketch = self.newSketchOnCopiedFace(box, top)
        copy = self.doc.getObject("CopyBox")
        self.assertEqual(sketch.AttachmentSupport, [(copy, (top,))])
        self.assertNotIn("isn't up to date", (reportText() or "")[before:])
        self.assertNotIn("is the body's solid", (reportText() or "")[before:])

    def testNewSketchOnACopiedBoxAcrossPlacedParts(self):
        """PR 261 review L4: the box's body sits in an App::Part turned 90 degrees about Z and
        moved by (5, 0, 0), the body itself moved by (0, 2, 0); the sketch's body sits in another
        App::Part turned 30 degrees about X and moved by (0, 0, 7), the body moved by (1, 0, 0).
        New Sketch on the box's end face x = 20 (box coordinates), Make independent copy: the
        copy is globally where the box is, and the sketch on the face's plane, globally."""
        source = self.doc.addObject("App::Part", "SourcePart")
        source.Placement = App.Placement(V(5, 0, 0), App.Rotation(Z, 90))
        other = models.body(self.doc)
        source.addObject(other)
        other.Placement.Base = V(0, 2, 0)
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        target = self.doc.addObject("App::Part", "TargetPart")
        target.Placement = App.Placement(V(0, 0, 7), App.Rotation(V(1, 0, 0), 30))
        self.body = models.body(self.doc)
        target.addObject(self.body)
        self.body.Placement.Base = V(1, 0, 0)
        self.doc.recompute()
        end = self.boxElement(box, "Face", lambda p: abs(p.x - 20) < 1e-6)
        sketch = self.newSketchOnCopiedFace(box, end)
        copy = self.doc.getObject("CopyBox")
        self.assertIsNotNone(copy)
        self.assertTrue(self.body.hasObject(copy))
        self.assertIndependentPrimitiveCopy(copy, box)
        self.assertEqual(sketch.AttachmentSupport, [(copy, (end,))])
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        # the box's end face, globally: through the point (20, 5, 5) of the box, along its X
        boxGlobal = box.getGlobalPlacement()
        point = boxGlobal.multVec(V(20, 5, 5))
        normal = boxGlobal.Rotation.multVec(V(1, 0, 0))
        sketchGlobal = sketch.getGlobalPlacement()
        self.assertAlmostEqual(abs(sketchGlobal.Rotation.multVec(Z).dot(normal)), 1, places=6)
        self.assertAlmostEqual((point - sketchGlobal.Base).dot(normal), 0, places=6)

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
        Edge1 whatever edge was picked; it is the picked edge, the same line on the copy.
        ops#244 P3: a primitive copy went after the Revolution in the body with the Revolution as
        its BaseFeature, a cycle that broke the axis, loudly. The copy is a shape binder, out of
        the solid chain: OK keeps the axis, and the revolution recomputes.
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
        self.assertIndependentPrimitiveCopy(copy, box)
        self.assertEqual(revolution.ReferenceAxis, (copy, [edge]))
        picked = copy.Shape.getElement(edge)
        self.assertAlmostEqual(picked.CenterOfMass.distanceToPoint(V(10, 0, 5)), 0, places=6)
        self.assertAlmostEqual(abs(picked.Curve.Direction.z), 1, places=6)
        self.close(ok=True)
        self.doc.recompute()
        self.assertIs(self.body.Tip, revolution)
        self.assertEqual(revolution.ReferenceAxis, (copy, [edge]))
        self.assertTrue(copy.isValid(), copy.getStatusString())
        self.assertNotIn("Touched", copy.State)
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(App.getReferenceReport(revolution), [])
        # the ring (x 1..3, z 0..2) turned about the line x = 10: radii 7..9, height 2
        self.assertAlmostEqual(revolution.Shape.Volume, math.pi * (81 - 49) * 2, places=3)

    def revolutionBesideAnAxisSketch(self):
        """revolutionBesideABox with a sketch in the other body instead of the box: Axis, the
        line x = 10, z 0..10 (on XZ). Returns the sketch and the revolution."""
        other = models.body(self.doc)
        axis = models.sketch(self.doc, "Axis", [line(10, 0, 10, 10)], other, placement=XZ)
        self.body = models.body(self.doc)
        ring = models.sketch(self.doc, "Ring", models.rectangle(1, 0, 3, 2), self.body, placement=XZ)
        revolution = self.body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = ring
        revolution.ReferenceAxis = (ring, ["V_Axis"])
        revolution.Angle = 360
        self.doc.recompute()
        return axis, revolution

    def testRevolutionAxisOnAStaleCopiedSketchStops(self):
        """PR 223 verification L3 (getReferencedSelection's check): the axis picked on Edge1 of
        a sketch in another body, Make independent copy, the sketch's line moved from x = 10 to
        x = 20 and not recomputed: its copy, recomputed in makeCopy, has the line at x = 20, so
        the picked edge would be another line there. The pick stops with a message, leaves no
        copy and the axis as it was, and the field stays armed: once the sketch is recomputed,
        the same pick links the copy's edge. (A stale box no longer stops: its copy is a shape
        binder of the shape shown, ops#244 P3.)"""
        axis, revolution = self.revolutionBesideAnAxisSketch()
        axis.Geometry = [line(20, 0, 20, 10)]
        self.edit(revolution)
        self.armAxisField()
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, axis.Name, "Edge1")
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: Edge1"), self.modals)
        self.assertEqual(
            [o.Name for o in self.doc.Objects if o.Name.startswith("CopyAxis")], []
        )
        self.assertEqual(revolution.ReferenceAxis[1], ["V_Axis"])

        self.doc.recompute()
        Gui.Selection.clearSelection()
        self.modals = []
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, axis.Name, "Edge1")
        self.assertTrue(waitFor(lambda: self.modals), "the field isn't armed")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copy = revolution.ReferenceAxis[0]
        self.assertTrue(copy.Name.startswith("CopyAxis"), copy.Name)
        self.assertEqual(revolution.ReferenceAxis[1], ["Edge1"])
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
        (x, y) in the body (on its XY plane, or at `placement`); recomputed."""
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

    def testNewSketchOnADependentCopyFromAPlacedBody(self):
        """ops#244 (your answer, 2026-10-11): New Sketch on the end face x = 20 of a 20 x 10 x 10
        box in another body, Make dependent copy, the two bodies placed differently (the box's
        turned 90 degrees about Z and moved by (5, 0, 0), the sketch's moved by (0, 3, 2) and
        turned 30 degrees about X). The shape binder's face is where the box's face is,
        globally, and stays there when either body moves afterwards. It took the box's place in
        its own body: the face shifted by the bodies' difference, silently."""
        other = models.body(self.doc)
        other.Placement = App.Placement(V(5, 0, 0), App.Rotation(Z, 90))
        box = other.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 20
        self.body = models.body(self.doc)
        self.body.Placement = App.Placement(V(0, 3, 2), App.Rotation(V(1, 0, 0), 30))
        self.doc.recompute()
        end = self.boxElement(box, "Face", lambda p: abs(p.x - 20) < 1e-6)
        sketch = self.newSketchOnCopiedFace(box, end, "radioDependent")
        binder = self.doc.getObject("ReferenceBox")
        self.assertIsNotNone(binder)
        self.assertEqual(binder.TypeId, "PartDesign::ShapeBinder")
        self.assertTrue(self.body.hasObject(binder))
        self.assertEqual(binder.Support, [(box, (end,))])
        self.assertTrue(binder.TraceSupport)
        self.assertEqual(sketch.AttachmentSupport, [(binder, ("Face1",))])

        def assertWhereTheBoxFaceIs(step):
            self.doc.recompute()
            self.assertTrue(binder.isValid(), binder.getStatusString())
            self.assertTrue(sketch.isValid(), sketch.getStatusString())
            source = box.Shape.getElement(end)
            sourceCentre = other.getGlobalPlacement().multVec(source.CenterOfMass)
            sourceNormal = other.getGlobalPlacement().Rotation.multVec(source.normalAt(0, 0))
            [face] = binder.Shape.Faces
            centre = self.body.getGlobalPlacement().multVec(face.CenterOfMass)
            self.assertLess((centre - sourceCentre).Length, 1e-6, f"{step}: {centre}")
            # the sketch lies in the face's plane
            placement = sketch.getGlobalPlacement()
            normal = placement.Rotation.multVec(Z)
            self.assertAlmostEqual(abs(normal.dot(sourceNormal)), 1, places=6, msg=step)
            self.assertAlmostEqual((placement.Base - sourceCentre).dot(sourceNormal), 0, places=6,
                                   msg=step)

        assertWhereTheBoxFaceIs("made")
        # globally (0, 20, 5): the end's centre (20, 5, 5) turned 90 degrees, moved by (5, 0, 0)
        self.assertLess(
            (other.getGlobalPlacement().multVec(box.Shape.getElement(end).CenterOfMass)
             - V(0, 20, 5)).Length,
            1e-6,
        )
        other.Placement = App.Placement(V(-4, 1, 0), App.Rotation(Z, 45))
        assertWhereTheBoxFaceIs("the box's body moved")
        self.body.Placement = App.Placement(V(2, -1, 0), App.Rotation(V(0, 1, 0), 20))
        assertWhereTheBoxFaceIs("the sketch's body moved")

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
        # a shape binder since ops#244 P3, P5, unattached
        self.assertIndependentPrimitiveCopy(copy, box)
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

    def testDatumOnAStaleCopiedSketchStops(self):
        """ops#244 P2, the check: a datum plane normal to Edge1 of a sketch in another body (the
        line x = 10, z 0..10 on XZ), the line moved to x = 20 and not recomputed, so the picked
        edge is another line on the sketch's copy, recomputed in makeCopy. OK stops with a
        message, the panel stays, and no copy is left. (A stale box no longer stops: its copy is
        a shape binder of the shape shown, ops#244 P5.)"""
        other = models.body(self.doc)
        axis = models.sketch(self.doc, "Axis", [line(10, 0, 10, 10)], other, placement=XZ)
        self.body = models.body(self.doc)
        datum = self.body.newObject("PartDesign::Plane", "Datum")
        datum.AttachmentSupport = [(axis, "Edge1")]
        datum.MapMode = "NormalToEdge"
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        axis.Geometry = [line(20, 0, 20, 10)]
        self.edit(datum)
        self.answerModals()
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: Edge1"), self.modals)
        self.assertIsNotNone(Gui.Control.activeDialog())
        self.assertEqual([o.Name for o in self.doc.Objects if o.Name.startswith("CopyAxis")], [])
        self.assertEqual(datum.AttachmentSupport, [(axis, ("Edge1",))])

    def testNewSketchOnTheTopFaceOfACopiedPrimitiveOnABase(self):
        """ops#244 P1: New Sketch on Box's top face (z = 20, not Face1) in primitivesOnABase,
        Make independent copy. The sketch went on the copy's Face1 (the base's side, x = -5)
        whatever face was picked. It links the picked face, the same index on the copy (a shape
        binder of Box's shape since ops#244 P5)."""
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
        the copy, also once OK closes the panel (a shape binder since ops#244 P3)."""
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
        self.close(ok=True)
        self.doc.recompute()
        self.assertEqual(revolution.ReferenceAxis, (copy, [edge]))
        self.assertTrue(revolution.isValid(), revolution.getStatusString())
        self.assertEqual(App.getReferenceReport(revolution), [])

    def padOfAFreeSketch(self, sketch):
        """Pad with nothing selected, and in its pick dialog `sketch` (outside any body), Make
        independent copy, into self.body; the pad panel closed with OK. Returns the pad and the
        copy."""
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
        return pad, copy

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
        pad, copy = self.padOfAFreeSketch(sketch)
        self.assertEqual(copy.MapMode, "FlatFace")
        self.doc.recompute()
        self.assertTrue(copy.getGlobalPlacement().isSame(sketch.getGlobalPlacement(), 1e-9))
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 1000, places=3)

    def testPadOfAnXZSketchCopiedIntoABody(self):
        """ops#244 L6: a 10 x 10 square sketch outside any body on XZ, moved by (2, 3, 5) and
        turned in its plane, Pad through the pick dialog, Make independent copy: the copy is
        attached to the body's XZ plane (it was XY, with a 90 degree offset), where the sketch
        is."""
        sketch = models.sketch(
            self.doc,
            "Free",
            models.rectangle(0, 0, 10, 10),
            None,
            placement=App.Placement(V(2, 3, 5), XZ.Rotation * App.Rotation(Z, 15)),
        )
        self.body = models.body(self.doc)
        self.doc.recompute()
        pad, copy = self.padOfAFreeSketch(sketch)
        self.assertEqual(copy.MapMode, "FlatFace")
        [(plane, _)] = copy.AttachmentSupport
        self.assertEqual(plane.Role, "XZ_Plane")
        self.assertTrue(self.body.Origin.hasObject(plane))
        self.doc.recompute()
        self.assertTrue(copy.getGlobalPlacement().isSame(sketch.getGlobalPlacement(), 1e-9))
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 1000, places=3)

    def testDatumOnADependentCopyAcrossPlacedBodiesStops(self):
        """PR 227 review M1: datumPointAcross's placed bodies, Make dependent copy. Attached to
        the point, the copy would take the point's place in its own body, (1, 2, 3), in this
        body: globally (1, 2, 13), not (3, 1, 3), silently. OK stops with a message pointing to
        the independent copy; the panel stays, no copy is left, the support is as it was."""
        other = models.body(self.doc)
        other.Placement = App.Placement(V(5, 0, 0), App.Rotation(Z, 90))
        point = other.newObject("PartDesign::Point", "Point")
        point.Placement.Base = V(1, 2, 3)
        self.body = models.body(self.doc)
        self.body.Placement.Base = V(0, 0, 10)
        datum = self.body.newObject("PartDesign::Point", "Datum")
        datum.AttachmentSupport = [(point, "")]
        datum.MapMode = "Vertex"
        self.doc.recompute()
        self.edit(datum)
        self.answerModals("radioDependent")
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: A dependent copy"), self.modals)
        self.assertIsNotNone(Gui.Control.activeDialog())
        self.assertIsNone(self.doc.getObject("ReferencePoint"))
        self.assertEqual(datum.AttachmentSupport, [(point, ("",))])

    # -- ops#244 follow-ups (fork PR for fix/244-copy-followups) ---------------------------------

    def okOnDatumStops(self, datum, choice):
        """OK on the datum's panel answered with `choice` stops with a message box, which is
        returned; the panel stays."""
        self.doc.recompute()
        self.edit(datum)
        self.answerModals(choice)
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: "), self.modals)
        self.assertIsNotNone(Gui.Control.activeDialog())
        return self.modals[1]

    def testDatumOnADependentCopyOfASlightlyTurnedBodyStops(self):
        """PR 227 verification (1): the M1 check's tolerance. The point's body is turned 0.01
        degrees about Z, so the point at (100, 0, 0) sits 0.017 mm off where a dependent copy in
        this body (at the origin) would put it. The quaternions' scalar product within
        Precision::Confusion let the turn through, silently; OK stops."""
        other = models.body(self.doc)
        other.Placement = App.Placement(V(0, 0, 0), App.Rotation(Z, 0.01))
        point = other.newObject("PartDesign::Point", "Point")
        point.Placement.Base = V(100, 0, 0)
        self.body = models.body(self.doc)
        datum = self.body.newObject("PartDesign::Point", "Datum")
        datum.AttachmentSupport = [(point, "")]
        datum.MapMode = "Vertex"
        text = self.okOnDatumStops(datum, "radioDependent")
        self.assertIn("A dependent copy of 'Point'", text)
        self.assertIsNone(self.doc.getObject("ReferencePoint"))
        self.assertEqual(datum.AttachmentSupport, [(point, ("",))])

    def sketchAxisAcross(self):
        """A 10 x 10 square sketch in another body moved by (5, 0, 0), and in this body (at the
        origin) a datum line attached to the sketch's V axis: globally the line x = 5 along Y."""
        other = models.body(self.doc)
        other.Placement.Base = V(5, 0, 0)
        square = models.sketch(self.doc, "Square", models.rectangle(0, 0, 10, 10), other)
        self.body = models.body(self.doc)
        datum = self.body.newObject("PartDesign::Line", "Datum")
        datum.AttachmentSupport = [(square, "V_Axis")]
        datum.MapMode = "TwoPointLine"
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        return square, datum

    def assertAlongTheSketchAxis(self, datum):
        placement = datum.getGlobalPlacement()
        self.assertAlmostEqual(abs(placement.Rotation.multVec(Z).y), 1, places=6)
        self.assertAlmostEqual(placement.Base.x, 5, places=6)
        self.assertAlmostEqual(placement.Base.z, 0, places=6)

    def testDatumOnADependentCopyOfASketchAxisStops(self):
        """ops#244 L4: the datum line on another body's sketch's V axis, Make dependent copy. The
        copy was a shape binder of "V_Axis", which isn't in the sketch's shape (it bound nothing),
        and the datum went on its "V_Axis1", which names nothing: it failed, with no word why.
        OK stops with a message pointing to the independent copy; no copy is left."""
        square, datum = self.sketchAxisAcross()
        text = self.okOnDatumStops(datum, "radioDependent")
        self.assertIn("V_Axis of 'Square' isn't part of the sketch's shape", text)
        self.assertIsNone(self.doc.getObject("ReferenceSquare"))
        self.assertEqual(datum.AttachmentSupport, [(square, ("V_Axis",))])

    def testDatumOnAnIndependentCopyOfASketchAxis(self):
        """ops#244 L4, Make independent copy: the copy is a sketch, which has the V axis; the
        datum is on it, where the original's axis is."""
        square, datum = self.sketchAxisAcross()
        self.edit(datum)
        self.answerModals()
        self.close(ok=True)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copy = self.doc.getObject("CopySquare")
        self.assertIsNotNone(copy)
        self.assertEqual(datum.AttachmentSupport, [(copy, ("V_Axis",))])
        self.doc.recompute()
        self.assertTrue(datum.isValid(), datum.getStatusString())
        self.assertAlongTheSketchAxis(datum)

    def testRevolutionAxisOnTheOtherDiagonalStops(self):
        """ops#244 L5: sameElement compared size and centre only. The axis sketch outside the body
        has one line from (-1, 0) to (-3, 5) on XZ, then drawn from (-3, 0) to (-1, 5) without a
        recompute: the same length and centre, the other direction. Its independent copy
        (recomputed) has the new line, and the pick of Edge1 linked it, silently. The pick stops
        with a message; no copy is left and the axis is as it was."""
        self.body = models.body(self.doc)
        ring = models.sketch(self.doc, "Ring", models.rectangle(1, 0, 3, 2), self.body, placement=XZ)
        axis = models.sketch(self.doc, "Axis", [line(-1, 0, -3, 5)], None, placement=XZ)
        self.doc.recompute()
        revolution = self.body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = ring
        revolution.ReferenceAxis = (ring, ["V_Axis"])
        revolution.Angle = 360
        self.doc.recompute()
        axis.Geometry = [line(-3, 0, -1, 5)]
        self.edit(revolution)
        self.armAxisField()
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, axis.Name, "Edge1")
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: Edge1 of 'Axis'"), self.modals)
        self.assertEqual([o.Name for o in self.doc.Objects if o.Name.startswith("CopyAxis")], [])
        self.assertEqual(revolution.ReferenceAxis, (ring, ["V_Axis"]))

    def originPlaneIntoAPlacedBody(self, choice):
        """testDatumOnACopiedOriginPlane's model (another body's XZ plane, globally the plane
        x = 5 along X) with this body moved by (0, 3, 2) and turned 30 degrees about X."""
        other = models.body(self.doc)
        other.Placement = App.Placement(V(5, 0, 0), App.Rotation(Z, 90))
        xz = models.originFeature(other, "XZ_Plane")
        self.body = models.body(self.doc)
        self.body.Placement = App.Placement(V(0, 3, 2), App.Rotation(V(1, 0, 0), 30))
        self.doc.recompute()
        datum = self.attachDatumAcross("PartDesign::Plane", [(xz, "")], "FlatFace", choice)
        copy = datum.AttachmentSupport[0][0]
        self.assertEqual(copy.TypeId, "PartDesign::ShapeBinder")
        self.assertTrue(self.body.hasObject(copy))
        # PR 246 review M1: right straight after OK, with nothing left to compute
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])
        for _ in range(2):
            self.assertTrue(datum.isValid(), datum.getStatusString())
            placement = datum.getGlobalPlacement()
            self.assertAlmostEqual(abs(placement.Rotation.multVec(Z).x), 1, places=6)
            self.assertAlmostEqual(placement.Base.x, 5, places=6)
            self.doc.recompute()
        return copy

    def testDatumOnAnOriginPlaneCopiedIntoAPlacedBody(self):
        """ops#244 L7: an independent copy of an origin plane into a placed body is where the
        plane is (decision 40)."""
        copy = self.originPlaneIntoAPlacedBody("radioIndependent")
        self.assertEqual(copy.Support, [])

    def testDatumOnADependentOriginPlaneCopyInAPlacedBody(self):
        """ops#244 L7 (PR 244 review, Low): a dependent copy of an origin plane (App::Plane) is a
        shape binder that traces it, so it is where the plane is too."""
        copy = self.originPlaneIntoAPlacedBody("radioDependent")
        self.assertTrue(copy.TraceSupport)
        self.assertEqual(len(copy.Support), 1)

    def testRevolutionAxisOnAnEdgeOfACopiedPad(self):
        """ops#244 L7: the Revolution's axis picked on a vertical edge (x = 10, y = 0) of a 10 x
        10 x 10 pad in another body, Make independent copy: the copy is a shape binder of that
        edge, and the axis is its Edge1, the same line. Checked at the pick."""
        other = models.body(self.doc)
        base = models.sketch(self.doc, "Base", models.rectangle(0, 0, 10, 10), other)
        pad = other.newObject("PartDesign::Pad", "Pad")
        pad.Profile = base
        pad.Length = 10
        self.body = models.body(self.doc)
        ring = models.sketch(self.doc, "Ring", models.rectangle(1, 0, 3, 2), self.body, placement=XZ)
        self.doc.recompute()
        [edge] = [
            f"Edge{i}"
            for i, e in enumerate(pad.Shape.Edges, 1)
            if (e.CenterOfMass - V(10, 0, 5)).Length < 1e-6
        ]
        self.assertNotEqual(edge, "Edge1")
        revolution = self.body.newObject("PartDesign::Revolution", "Revolution")
        revolution.Profile = ring
        revolution.ReferenceAxis = (ring, ["V_Axis"])
        revolution.Angle = 360
        self.doc.recompute()
        self.edit(revolution)
        self.armAxisField()
        self.answerModals()
        Gui.Selection.addSelection(self.doc.Name, pad.Name, edge)
        self.assertTrue(waitFor(lambda: self.modals), "no copy dialog")
        pump(0.3)
        self.answering = False
        self.assertEqual(self.modals, ["DlgReference"])
        copy = self.doc.getObject("CopyPad")
        self.assertIsNotNone(copy)
        self.assertEqual(copy.TypeId, "PartDesign::ShapeBinder")
        self.assertEqual(revolution.ReferenceAxis, (copy, ["Edge1"]))
        [picked] = copy.Shape.Edges
        self.assertLess((picked.CenterOfMass - V(10, 0, 5)).Length, 1e-6)
        self.assertAlmostEqual(abs(picked.Curve.Direction.z), 1, places=6)
        self.close(ok=False)

    def testDatumOnALegacyCoordinateSystemStops(self):
        """PR 227 review L1: a datum plane attached to a (legacy) PartDesign coordinate system in
        another body, Make independent copy: OK stops with makeCopy's message; no copy is left."""
        other = models.body(self.doc)
        cs = other.newObject("PartDesign::CoordinateSystem", "CS")
        self.body = models.body(self.doc)
        datum = self.body.newObject("PartDesign::Plane", "Datum")
        datum.AttachmentSupport = [(cs, "")]
        datum.MapMode = "ObjectXY"
        text = self.okOnDatumStops(datum, "radioIndependent")
        self.assertIn("'CS' can't be copied", text)
        self.assertEqual([o.Name for o in self.doc.Objects if o.Name.startswith("CopyCS")], [])

    def datumPlaneInAPlacedBody(self):
        """A datum plane at z = 4 in another body moved by (0, 0, 6): globally the plane z = 10;
        this body at the origin."""
        other = models.body(self.doc)
        other.Placement.Base = V(0, 0, 6)
        plane = other.newObject("PartDesign::Plane", "DatumPlane")
        plane.Placement.Base = V(0, 0, 4)
        self.body = models.body(self.doc)
        self.doc.recompute()
        return plane

    def testNewSketchOnAnIndependentCopyOfADatumPlane(self):
        """PR 227 review L7 (ops#244 P6 through New Sketch): New Sketch on a datum plane's face in
        another, placed body (the whole plane is matched in the active body only), Make
        independent copy: the copy is a datum plane where the plane is, and the sketch is on it,
        globally z = 10."""
        plane = self.datumPlaneInAPlacedBody()
        sketch = self.newSketchOnCopiedFace(plane, "Face1")
        copy = self.doc.getObject("CopyDatumPlane")
        self.assertIsNotNone(copy)
        self.assertEqual(copy.TypeId, "PartDesign::Plane")
        self.assertEqual(sketch.AttachmentSupport[0][0], copy)
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertAlmostEqual(sketch.getGlobalPlacement().Base.z, 10, places=6)

    def testNewSketchOnADependentCopyOfADatumPlaneStops(self):
        """PR 227 review M1 (New Sketch): as testNewSketchOnAnIndependentCopyOfADatumPlane with
        Make dependent copy. Attached to the plane, the copy would sit at z = 4 in this body, not
        z = 10, silently. New Sketch stops with a message and leaves no copy and no sketch."""
        plane = self.datumPlaneInAPlacedBody()
        self.runNewSketchOnCopiedFace(plane, "Face1", "radioDependent")
        self.assertTrue(waitFor(lambda: len(self.modals) >= 2), f"modals {self.modals}")
        self.answering = False
        self.assertEqual(self.modals[0], "DlgReference")
        self.assertTrue(self.modals[1].startswith("QMessageBox: A dependent copy"), self.modals)
        pump(0.3)
        self.assertIsNone(Gui.getDocument(self.doc.Name).getInEdit())
        self.assertIsNone(self.doc.getObject("ReferenceDatumPlane"))
        self.assertEqual(
            [o for o in self.doc.Objects if o.isDerivedFrom("Sketcher::SketchObject")], []
        )

    # -- ops#251: the ShapeBinder panel and command bind no more and no less than picked ---------
    #
    # Designed model: two 10 mm boxes, Box at the origin and Box001 at x = 20, each in its own
    # body; the binder in a third body. Box's top face is the one at z = 10, its side face the one
    # at x = 0.

    def binderModel(self, subs=("top",)):
        """The two boxes and a ShapeBinder on Box's faces named in subs ("top", "side");
        returns (box, other box, binder, {role: face name})."""
        boxes = []
        for x in (0, 20):
            body = models.body(self.doc)
            box = body.newObject("PartDesign::AdditiveBox", "Box")
            box.Length = box.Width = box.Height = 10
            box.Placement.Base = V(x, 0, 0)
            boxes.append(box)
        self.body = models.body(self.doc)
        self.doc.recompute()
        box = boxes[0]
        names = {
            "top": self.faceAt(box, V(5, 5, 10)),
            "side": self.faceAt(box, V(0, 5, 5)),
        }
        binder = self.body.newObject("PartDesign::ShapeBinder", "ShapeBinder")
        binder.Support = [(box, tuple(names[r] for r in subs))]
        self.doc.recompute()
        self.assertTrue(binder.isValid(), binder.getStatusString())
        return box, boxes[1], binder, names

    @staticmethod
    def faceAt(feature, center):
        [name] = [
            f"Face{i}"
            for i, f in enumerate(feature.Shape.Faces, 1)
            if (f.CenterOfMass - center).Length < 1e-6
        ]
        return name

    @staticmethod
    def support(binder):
        return [(obj.Name, tuple(subs)) for obj, subs in binder.Support]

    @staticmethod
    def statusTexts():
        statusBar = Gui.getMainWindow().statusBar()
        return [label.text() for label in statusBar.findChildren(QtWidgets.QLabel)]

    def assertBindsTopFace(self, binder, box, names):
        self.assertEqual(self.support(binder), [(box.Name, (names["top"],))])
        shape = binder.Shape
        self.assertEqual(len(shape.Faces), 1)
        self.assertEqual(len(shape.Solids), 0)
        self.assertAlmostEqual(shape.Area, 100, places=6)
        self.assertAlmostEqual(shape.BoundBox.ZMin, 10, places=6)
        self.assertAlmostEqual(shape.BoundBox.ZMax, 10, places=6)

    def testShapeBinderRemoveModeKeepsTheLastElement(self):
        """Remove Geometry on the binder's only face is refused: the binder keeps the face (not
        the whole box, as Support.setValue(obj, []) stored) and the status bar says why."""
        box, _, binder, names = self.binderModel()
        self.edit(binder)
        self.widget(QtWidgets.QToolButton, "buttonRefRemove").click()
        Gui.Selection.addSelection(self.doc.Name, box.Name, names["top"])
        pump(0.2)
        self.assertBindsTopFace(binder, box, names)
        self.assertEqual(self.widget(QtWidgets.QListWidget, "listWidgetReferences").count(), 1)
        self.assertTrue(any("last element" in t for t in self.statusTexts()), self.statusTexts())

    def testShapeBinderDeleteKeepsTheLastRow(self):
        """The list's Remove (Delete) on the only row is refused the same way."""
        box, _, binder, names = self.binderModel()
        self.edit(binder)
        refs = self.widget(QtWidgets.QListWidget, "listWidgetReferences")
        refs.setCurrentRow(0)
        [remove] = refs.actions()
        remove.trigger()
        pump(0.2)
        self.assertBindsTopFace(binder, box, names)
        self.assertEqual(refs.count(), 1)
        self.assertTrue(any("last element" in t for t in self.statusTexts()), self.statusTexts())

    def testShapeBinderRemoveModeRemovesOneOfTwo(self):
        """Removing one of two faces still works: the binder keeps the other one."""
        box, _, binder, names = self.binderModel(("top", "side"))
        self.edit(binder)
        self.widget(QtWidgets.QToolButton, "buttonRefRemove").click()
        Gui.Selection.addSelection(self.doc.Name, box.Name, names["side"])
        pump(0.2)
        self.assertBindsTopFace(binder, box, names)

    def testShapeBinderAddOnAnotherObjectSaysWhy(self):
        """Add Geometry on the other box's face adds nothing (one object per binder), and the
        status bar says so instead of ignoring the click."""
        box, other, binder, names = self.binderModel()
        self.edit(binder)
        self.widget(QtWidgets.QToolButton, "buttonRefAdd").click()
        Gui.Selection.addSelection(self.doc.Name, other.Name, self.faceAt(other, V(25, 5, 10)))
        pump(0.2)
        self.assertBindsTopFace(binder, box, names)
        self.assertTrue(
            any(other.Label in t and box.Label in t for t in self.statusTexts()), self.statusTexts()
        )

    def testShapeBinderAddModeRefusesTheWholeObject(self):
        """Add Geometry on the bound object itself (a tree click: no element) beside its face is
        refused: it wrote Support [(Box, Face6), (Box, "")], which fails (PR 232 review M1)."""
        box, _, binder, names = self.binderModel()
        self.edit(binder)
        self.widget(QtWidgets.QToolButton, "buttonRefAdd").click()
        Gui.Selection.addSelection(self.doc.Name, box.Name)
        pump(0.2)
        self.assertBindsTopFace(binder, box, names)
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertTrue(
            any("Use Object" in t and box.Label in t for t in self.statusTexts()),
            self.statusTexts(),
        )

    def testShapeBinderCommandRefusesTwoObjects(self):
        """PartDesign_ShapeBinder on faces of both boxes makes no binder (it would bind Box's face
        only) and says why in a message box."""
        box, other, binder, names = self.binderModel()
        other.Label = "Right box"
        self.doc.removeObject(binder.Name)
        self.doc.recompute()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        guiDoc = Gui.getDocument(self.doc.Name)
        guiDoc.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.addSelection(self.doc.Name, box.Name, names["top"])
        Gui.Selection.addSelection(self.doc.Name, other.Name, self.faceAt(other, V(25, 5, 10)))
        self.answerModals()
        Gui.runCommand("PartDesign_ShapeBinder")
        self.assertTrue(waitFor(lambda: self.modals, 5.0), "no message box")
        self.answering = False
        binders = [o.Name for o in self.doc.Objects if o.isDerivedFrom("PartDesign::ShapeBinder")]
        self.assertEqual(binders, [])
        self.assertEqual(len(self.modals), 1, self.modals)
        # by its label, not its name (PR 232 review L3, ops#266)
        self.assertIn("'Right box'", self.modals[0])
        self.assertNotIn(other.Name, self.modals[0])
        # the refusal comes before the command's transaction (PR 232 review L5)
        self.assertIsNone(App.getActiveTransaction())
        self.assertFalse(self.doc.HasPendingTransaction)

    def testShapeBinderNonPartPickSaysWhy(self):
        """Object on an origin plane (not a Part feature) binds nothing, and the status bar says
        why instead of ignoring the click (PR 232 review L1, ops#266)."""
        box, _, binder, names = self.binderModel()
        [plane] = [f for f in self.body.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        self.edit(binder)
        self.widget(QtWidgets.QToolButton, "buttonBase").click()
        Gui.Selection.addSelection(self.doc.Name, plane.Name)
        pump(0.2)
        self.assertBindsTopFace(binder, box, names)
        self.assertTrue(
            any(plane.Label in t and "isn't a Part feature" in t for t in self.statusTexts()),
            self.statusTexts(),
        )

    def testShapeBinderPanelNamesAFailingSupport(self):
        """A binder whose Support (set from Python) holds Box's top face and a face of the other
        box fails. Its panel says so when it opens, by labels: it showed only Box's face, and an
        edit then set Support to it without a word. After an edit (Add Box's side face) Support
        is Box's two faces, the binder recomputes, and the note is gone (PR 232 review L2,
        ops#266)."""
        box, other, binder, names = self.binderModel()
        other.Label = "Right box"
        binder.Support = [(box, names["top"]), (other, self.faceAt(other, V(25, 5, 10)))]
        self.doc.recompute()
        self.assertFalse(binder.isValid())
        self.edit(binder)
        note = self.widget(QtWidgets.QLabel, "droppedNote")
        self.assertTrue(note.isVisible())
        self.assertIn("'Right box'", note.text())
        self.assertIn("an edit here sets Support", note.text())
        self.widget(QtWidgets.QToolButton, "buttonRefAdd").click()
        Gui.Selection.addSelection(self.doc.Name, box.Name, names["side"])
        pump(0.2)
        self.assertEqual(self.support(binder), [(box.Name, (names["top"], names["side"]))])
        self.assertTrue(binder.isValid(), binder.getStatusString())
        self.assertFalse(note.isVisible())

    def testShapeBinderPanelNoteFollowsSupportSetElsewhere(self):
        """PR 245 review L4: with the panel open on a good binder, Support set from Python to a
        failing one (Box's top face and two faces of the other box) shows the note, naming the
        other box once; set back to Box's top face, the note is gone. It changed only after an
        edit in the panel."""
        box, other, binder, names = self.binderModel()
        other.Label = "Right box"
        self.edit(binder)
        note = self.widget(QtWidgets.QLabel, "droppedNote")
        self.assertFalse(note.isVisible())
        binder.Support = [
            (box, names["top"]),
            (other, (self.faceAt(other, V(25, 5, 10)), self.faceAt(other, V(25, 5, 0)))),
        ]
        pump(0.2)
        self.assertTrue(note.isVisible())
        self.assertEqual(note.text().count("'Right box'"), 1, note.text())
        binder.Support = [(box, names["top"])]
        pump(0.2)
        self.assertFalse(note.isVisible())

    def referenceTexts(self):
        widget = self.widget(QtWidgets.QListWidget, "listWidgetReferences")
        return [widget.item(row).text() for row in range(widget.count())]

    def testShapeBinderPanelListFollowsSupportSetElsewhere(self):
        """ops#276: with the panel open on Box's top face, Support set from Python to Box's side
        face, then to the other box's top face: the list and the object field show each, and OK
        keeps the last. Only the note followed; the list kept the top face."""
        box, other, binder, names = self.binderModel()
        other.Label = "Right box"
        otherTop = self.faceAt(other, V(25, 5, 10))
        self.edit(binder)
        self.assertEqual(self.referenceTexts(), [names["top"]])
        binder.Support = [(box, names["side"])]
        pump(0.2)
        self.assertEqual(self.referenceTexts(), [names["side"]])
        binder.Support = [(other, otherTop)]
        pump(0.2)
        self.assertEqual(self.referenceTexts(), [otherTop])
        self.assertEqual(self.widget(QtWidgets.QLineEdit, "baseEdit").text(), "Right box")
        self.close(ok=True)
        self.assertEqual(self.support(binder), [(other.Name, (otherTop,))])

    def testShapeBinderPanelOkAfterSupportClearedElsewhere(self):
        """ops#276: Support cleared from Python with the panel open empties the object field and
        the list, and OK leaves it empty. The field kept Box's label, and OK bound the whole box
        again."""
        box, _, binder, names = self.binderModel()
        self.edit(binder)
        binder.Support = []
        pump(0.2)
        self.assertEqual(self.widget(QtWidgets.QLineEdit, "baseEdit").text(), "")
        self.assertEqual(self.referenceTexts(), [])
        self.close(ok=True)
        self.assertEqual(self.support(binder), [])

    def testShapeBinderPanelHasNoNoteOnAGoodSupport(self):
        """The panel on a binder that binds its Support shows no note (ops#266)."""
        box, _, binder, names = self.binderModel()
        self.edit(binder)
        self.assertFalse(self.widget(QtWidgets.QLabel, "droppedNote").isVisible())

    # -- ops#252: Draft and Thickness leave out every pick they don't take -----------------------

    def dressUpOnEdgesAndAFace(self, command, typeId):
        """A 10 mm box in a body; Edge1, Edge2 and its top face picked, then `command`: the
        feature's Base is the face alone, and the status bar names both edges. The erase in the
        command's loop skipped the pick after each one it left out, so Edge2 stayed."""
        self.body = models.body(self.doc)
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        self.doc.recompute()
        top = self.faceAt(box, V(5, 5, 10))
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body)
        for sub in ("Edge1", "Edge2", top):
            Gui.Selection.addSelection(self.doc.Name, box.Name, sub)
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        [feature] = [o for o in self.doc.Objects if o.TypeId == typeId]
        self.assertIs(feature.Base[0], box)
        self.assertEqual(list(feature.Base[1]), [top])
        self.assertTrue(
            any("Edge1" in t and "Edge2" in t for t in self.statusTexts()), self.statusTexts()
        )

    def testDraftLeavesOutEveryEdge(self):
        self.dressUpOnEdgesAndAFace("PartDesign_Draft", "PartDesign::Draft")

    def testThicknessLeavesOutEveryEdge(self):
        self.dressUpOnEdgesAndAFace("PartDesign_Thickness", "PartDesign::Thickness")

    # -- ops#252: transforms and profile features say which picks they leave out ----------------

    def activeBodyWithBoxAndSketches(self):
        """A 10 mm box in the active body, and two sketches on its top: squares 2 apart."""
        self.body = models.body(self.doc)
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        sketches = []
        for name, x in (("First", 1), ("Second", 5)):
            sketch = models.sketch(self.doc, name, models.rectangle(x, 1, x + 2, 3), self.body, z=10)
            sketch.Label = name + " sketch"
            sketches.append(sketch)
        # the box is the solid a whole-shape transform takes
        self.body.Tip = box
        self.doc.recompute()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body)
        return box, sketches

    def testMirrorOfABoxAndASketchSaysTheSketchIsLeftOut(self):
        """The box and a sketch selected, then Mirror: the box is the original, and the status
        bar names the sketch as left out (it said nothing; a sketch alone made a "Whole shape"
        mirror, the same way. Not tested alone: the new mirror's first recompute then fails, and
        the notification area off screen fails the command, notes/build.md)."""
        box, (sketch, _) = self.activeBodyWithBoxAndSketches()
        Gui.Selection.addSelection(self.doc.Name, box.Name)
        Gui.Selection.addSelection(self.doc.Name, sketch.Name)
        Gui.runCommand("PartDesign_Mirrored")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        [mirror] = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Mirrored"]
        self.assertEqual(mirror.Originals, [box])
        self.assertTrue(
            any("left out of the selection: 'First sketch'." in t for t in self.statusTexts()),
            self.statusTexts(),
        )

    def testPadOfTwoSketchesSaysWhichIsLeftOut(self):
        """Two sketches selected, then Pad: the first is the profile, and the status bar names
        both, the second as left out (it was dropped without a word)."""
        _, (first, second) = self.activeBodyWithBoxAndSketches()
        Gui.Selection.addSelection(self.doc.Name, first.Name)
        Gui.Selection.addSelection(self.doc.Name, second.Name)
        Gui.runCommand("PartDesign_Pad")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        [pad] = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Pad"]
        self.assertIs(pad.Profile[0], first)
        self.assertTrue(
            any(
                "'First sketch'" in t and "Left out of the selection: 'Second sketch'" in t
                for t in self.statusTexts()
            ),
            self.statusTexts(),
        )

    # -- ops#252: Move Feature To / After take the row chosen, not the first with its text -------

    def chooseInListDialog(self, row):
        """Until self.answering is False: chooses `row` in the next list dialog (QInputDialog)
        and accepts it; records its items in self.modals."""
        self.answering = True

        def poll():
            if not self.answering:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if isinstance(widget, QtWidgets.QInputDialog):
                combo = widget.findChild(QtWidgets.QComboBox)
                self.modals.append([combo.itemText(i) for i in range(combo.count())])
                combo.setCurrentIndex(row)
                widget.accept()
                return
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)

    def testMoveFeatureAfterAFeatureLabelledLikeTheBeginning(self):
        """Three boxes in a body, the first labelled "Beginning of the body". Move Feature After
        on the third, with the first chosen (row 1): the third goes after it. It went to the
        beginning: the row was looked up by its text, which row 0 has too. The first's row shows
        its name, so the two rows differ."""
        self.body = models.body(self.doc)
        boxes = []
        for i in range(3):
            box = self.body.newObject("PartDesign::AdditiveBox", f"Box{i}")
            box.Placement.Base = V(20 * i, 0, 0)
            boxes.append(box)
        self.doc.recompute()
        boxes[0].Label = "Beginning of the body"
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.addSelection(self.doc.Name, boxes[2].Name)
        self.chooseInListDialog(1)
        Gui.runCommand("PartDesign_MoveFeatureInTree")
        self.assertTrue(waitFor(lambda: self.modals, 5.0), "no list dialog")
        self.answering = False
        pump(0.2)
        # the feature's row has its name too (PR 245 review L2: two identical rows)
        self.assertEqual(
            self.modals[0][:2], ["Beginning of the body", "Beginning of the body (Box0)"]
        )
        self.assertEqual(
            [o.Name for o in self.body.Group if o in boxes], ["Box0", "Box2", "Box1"]
        )

    def testMoveFeatureToShowsRepeatedLabelsWithTheirNames(self):
        """Two other bodies labelled alike: Move Feature To lists them with their names, and the
        second chosen gets the feature (the first with its text got it)."""
        source = models.body(self.doc)
        box = source.newObject("PartDesign::AdditiveBox", "Box")
        targets = [models.body(self.doc) for _ in range(2)]
        self.doc.recompute()
        App.ParamGet("User parameter:BaseApp/Preferences/Document").SetBool("DuplicateLabels", True)
        try:
            for target in targets:
                target.Label = "Target"
        finally:
            App.ParamGet("User parameter:BaseApp/Preferences/Document").RemBool("DuplicateLabels")
        self.assertEqual([t.Label for t in targets], ["Target", "Target"])
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.Selection.addSelection(self.doc.Name, box.Name)
        self.chooseInListDialog(1)
        Gui.runCommand("PartDesign_MoveFeature")
        self.assertTrue(waitFor(lambda: self.modals, 5.0), "no list dialog")
        self.answering = False
        pump(0.2)
        self.assertEqual(
            self.modals[0], [f"Target ({targets[0].Name})", f"Target ({targets[1].Name})"]
        )
        self.assertTrue(targets[1].hasObject(box))
        self.assertFalse(targets[0].hasObject(box))

    def testMoveFeatureToSaysATracedOriginBinderKeepsItsPlane(self):
        """ops#244 (PR 246 verification): a traced binder of its own body's XZ plane moved to
        another body with Move Object To keeps binding that plane, where it is (PR 246 review L2),
        which showed only in its Support. The Report view says so, naming the binder, the target,
        the plane and the source body."""
        source = models.body(self.doc)
        source.Label = "Source"
        [xz] = [f for f in source.Origin.OriginFeatures if f.Role == "XZ_Plane"]
        binder = self.doc.addObject("PartDesign::ShapeBinder", "Reference")
        binder.Support = [(xz, "")]
        binder.TraceSupport = True
        source.addObject(binder)
        target = models.body(self.doc)
        target.Label = "Target"
        self.doc.recompute()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.Selection.addSelection(self.doc.Name, binder.Name)
        before = len(reportText() or "")
        self.chooseInListDialog(0)
        Gui.runCommand("PartDesign_MoveFeature")
        self.assertTrue(waitFor(lambda: self.modals, 5.0), "no list dialog")
        self.answering = False
        pump(0.2)
        self.assertTrue(target.hasObject(binder))
        self.assertEqual(binder.Support[0][0], xz)
        self.assertIn(
            f"'{binder.Label}' moved to 'Target' still binds '{xz.Label}' of 'Source', where it was",
            (reportText() or "")[before:],
        )
