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

    def answerModals(self):
        """Until self.answering is False: answers the copy dialog (DlgReference) with its default,
        Make independent copy, and closes any message box; records each in self.modals."""
        self.answering = True

        def poll():
            if not self.answering:
                return
            widget = QtWidgets.QApplication.activeModalWidget()
            if widget is not None:
                independent = widget.findChild(QtWidgets.QRadioButton, "radioIndependent")
                if independent is not None:
                    self.modals.append("DlgReference")
                    independent.setChecked(True)
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

    # -- ops#170 4: the Pipe's OK copies what is outside the body ---------------------------------

    def testPipeCopiesBothExternalSpines(self):
        """4: spine and auxiliary spine both outside the body: OK copies both into it (Make
        independent copy), not only the spine."""
        pipe = self.rod(spineInBody=False)
        aux = self.auxiliarySpine(inBody=False)
        pipe.Mode = "Auxiliary"
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
        self.doc.recompute()
        self.assertTrue(pipe.isValid(), pipe.getStatusString())
        # swept along the whole spine (Auxiliary mode turns the profile, so no exact volume)
        box = pipe.Shape.BoundBox
        self.assertAlmostEqual(box.ZMin, 0, places=3)
        self.assertAlmostEqual(box.ZMax, 30, places=3)

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
