# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#655, notes/loft-options.md)

"""The panels' fields for the loft end conditions and tangent propagation, as Onshape's panels.

Loft: "Start condition" and "End condition" (None / Normal to profile) after the Profile and Sections
fields, each with a "Magnitude" that shows only while its condition is set. Fillet and Chamfer: a
"Tangent propagation" check box after the edges field, ticked by default.

Designed models, built by the test, with Onshape's results (oracle facts GB12 and GB13, the same as
TestLoftOnshape and TestFilletPropagation): a square 20 at z 0 lofted to a circle r 5 at z 30 with the
start Normal to profile, V 7894.77, 6 faces (plain: V 6586.04); a square 20 to a square 10, whose end
end condition pulls it in below the frustum's 7000; a slot (lines y = +-5 from x -10..10, round ends r 5)
padded 10 (2785.398), its top y = 5 line filleted r 2 with tangent propagation off, V 2765.061, 7
faces (on: the whole top loop, 2726.504), or chamfered 2 off, V 2736.279, 7 faces (on: 2650.944).
"""

import math
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor

V = App.Vector
H = 30.0
SLOT = 10 * (20 * 10 + math.pi * 25)  # 2785.398


def widget(cls, name):
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    found = [w for w in Gui.getMainWindow().findChildren(cls, name) if w.isVisible()]
    return found[0] if found else None


def square(side):
    h = side / 2
    return models.rectangle(-h, -h, h, h)


def slot():
    return [
        Part.LineSegment(V(-10, 5, 0), V(10, 5, 0)),
        Part.ArcOfCircle(Part.Circle(V(10, 0, 0), V(0, 0, 1), 5), -math.pi / 2, math.pi / 2),
        Part.LineSegment(V(10, -5, 0), V(-10, -5, 0)),
        Part.ArcOfCircle(Part.Circle(V(-10, 0, 0), V(0, 0, 1), 5), math.pi / 2, 3 * math.pi / 2),
    ]


class PanelCase(unittest.TestCase):
    def setUp(self):
        self.docs = []
        Gui.activateWorkbench("PartDesignWorkbench")
        Gui.Selection.clearSelection()

    def tearDown(self):
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump(0.2)
        Gui.Selection.clearSelection()
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        pump(0.2)

    def document(self, name):
        doc = models.newDocument(name)
        self.docs.append(doc.Name)
        self.doc = doc
        self.body = models.body(doc)
        return doc

    def activate(self):
        self.doc.recompute()
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)

    def edit(self, feature):
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        pump(0.3)

    def ok(self):
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stayed open")
        pump(0.2)

    def cancel(self):
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stayed open")
        pump(0.2)

    def assertResult(self, feature, volume, faces, delta=0.02):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, delta=delta)
        self.assertEqual(len(shape.Faces), faces)


class TestLoftConditionsGui(PanelCase):
    def loft(self, bottom, top, **properties):
        self.document("LoftConditionsGui")
        profile = models.sketch(self.doc, "Bottom", bottom, self.body)
        section = models.sketch(self.doc, "Top", top, self.body, z=H)
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = profile
        loft.Sections = [section]
        for name, value in properties.items():
            setattr(loft, name, value)
        self.activate()
        return loft

    def combo(self, which):
        return widget(QtWidgets.QComboBox, "combo%sCondition" % which)

    def magnitude(self, which):
        return widget(QtWidgets.QDoubleSpinBox, "spin%sMagnitude" % which)

    def testConditionsShowNoneAndNoMagnitude(self):
        """A plain loft's panel: both conditions None, with Onshape's two choices, and no magnitude."""
        self.edit(self.loft(square(20), [models.circle(0, 0, 5)]))
        for which in ("Start", "End"):
            combo = self.combo(which)
            self.assertIsNotNone(combo, "no %s condition" % which)
            self.assertEqual(combo.currentIndex(), 0)
            self.assertEqual(
                [combo.itemText(i) for i in range(combo.count())], ["None", "Normal to profile"]
            )
            self.assertIsNone(self.magnitude(which), "%s magnitude shows for None" % which)
            self.assertIsNone(widget(QtWidgets.QLabel, "label%sMagnitude" % which))

    def testStartNormalToProfileFromThePanel(self):
        """Picking Normal to profile sets the property, shows the magnitude at 1, and OK keeps
        Onshape's GB12 (e) loft."""
        loft = self.loft(square(20), [models.circle(0, 0, 5)])
        self.assertAlmostEqual(loft.Shape.Volume, 6586.04, delta=0.02)
        self.edit(loft)
        self.combo("Start").setCurrentIndex(1)
        pump(0.3)
        self.assertEqual(loft.StartCondition, "Normal to profile")
        self.assertEqual(loft.EndCondition, "None")
        spin = self.magnitude("Start")
        self.assertIsNotNone(spin, "no start magnitude after the pick")
        self.assertAlmostEqual(spin.value(), 1.0)
        self.assertIsNone(self.magnitude("End"))
        self.ok()
        self.assertEqual(loft.StartCondition, "Normal to profile")
        self.assertResult(loft, 7894.77, 6)

    def testEndMagnitudeFromThePanel(self):
        """The end condition and its magnitude: arriving normal to the smaller top square pulls the sides
        in below the frustum's 7000, and 2 pulls them in more than 1."""
        loft = self.loft(square(20), square(10))
        self.edit(loft)
        self.combo("End").setCurrentIndex(1)
        pump(0.3)
        self.assertEqual(loft.EndCondition, "Normal to profile")
        self.assertTrue(loft.isValid(), loft.getStatusString())
        one = loft.Shape.Volume
        self.assertLess(one, 7000.0 - 1)
        self.magnitude("End").setValue(2.0)
        pump(0.3)
        self.assertAlmostEqual(loft.EndMagnitude, 2.0)
        self.ok()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertLess(loft.Shape.Volume, one - 1)
        self.assertEqual(len(loft.Shape.Faces), 6)

    def testNoneHidesTheMagnitudeAgain(self):
        loft = self.loft(square(20), square(10))
        self.edit(loft)
        self.combo("Start").setCurrentIndex(1)
        pump(0.3)
        self.assertIsNotNone(self.magnitude("Start"))
        self.combo("Start").setCurrentIndex(0)
        pump(0.3)
        self.assertEqual(loft.StartCondition, "None")
        self.assertIsNone(self.magnitude("Start"))
        self.ok()
        self.assertResult(loft, 7000.0, 6)

    def testPanelOpensOnTheSavedConditions(self):
        self.edit(
            self.loft(
                square(20),
                square(10),
                StartCondition="Normal to profile",
                StartMagnitude=1.5,
            )
        )
        self.assertEqual(self.combo("Start").currentIndex(), 1)
        self.assertAlmostEqual(self.magnitude("Start").value(), 1.5)
        self.assertEqual(self.combo("End").currentIndex(), 0)
        self.assertIsNone(self.magnitude("End"))

    def testCancelPutsTheConditionBack(self):
        loft = self.loft(square(20), [models.circle(0, 0, 5)])
        self.edit(loft)
        self.combo("Start").setCurrentIndex(1)
        pump(0.3)
        self.assertEqual(loft.StartCondition, "Normal to profile")
        self.cancel()
        self.assertEqual(loft.StartCondition, "None")
        self.assertResult(loft, 6586.04, 6)


class TestTangentPropagationGui(PanelCase):
    def dressUp(self, kind, size=2.0, **properties):
        self.document("TangentPropagationGui")
        sketch = models.sketch(self.doc, "Slot", slot(), self.body)
        pad = models.pad(self.body, sketch, 10)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, SLOT, delta=1e-3)
        feature = self.body.newObject("PartDesign::" + kind, kind)
        feature.Base = (pad, [self.topLine(pad.Shape)])
        if kind == "Fillet":
            feature.Radius = size
        else:
            feature.Size = size
        for name, value in properties.items():
            setattr(feature, name, value)
        self.activate()
        return feature

    def topLine(self, shape):
        """The top edge of the y = 5 side."""
        names = [
            "Edge%d" % (i + 1)
            for i, edge in enumerate(shape.Edges)
            if isinstance(edge.Curve, Part.Line)
            and abs(edge.BoundBox.ZMin - 10) < 1e-6
            and abs(edge.BoundBox.ZMax - 10) < 1e-6
            and abs(edge.BoundBox.YMin - 5) < 1e-6
            and abs(edge.BoundBox.YMax - 5) < 1e-6
        ]
        self.assertEqual(len(names), 1, names)
        return names[0]

    def box(self):
        return widget(QtWidgets.QCheckBox, "checkBoxTangentPropagation")

    def testFilletPanelHasTangentPropagationTicked(self):
        fillet = self.dressUp("Fillet")
        self.assertResult(fillet, 2726.504, 10)
        self.edit(fillet)
        box = self.box()
        self.assertIsNotNone(box, "no Tangent propagation box")
        self.assertEqual(box.text(), "Tangent propagation")
        self.assertTrue(box.isChecked())

    def testUntickingRunsTheFilletStraightOn(self):
        """GB13: off, the fillet runs on through the round ends: V 2765.061, 7 faces."""
        fillet = self.dressUp("Fillet")
        self.edit(fillet)
        self.box().click()
        pump(0.3)
        self.assertFalse(fillet.TangentPropagation)
        self.ok()
        self.assertFalse(fillet.TangentPropagation)
        self.assertResult(fillet, 2765.061, 7)

    def testFilletPanelOpensUnticked(self):
        self.edit(self.dressUp("Fillet", TangentPropagation=False))
        self.assertFalse(self.box().isChecked())

    def testUntickingRunsTheChamferStraightOn(self):
        """GB13: off, the chamfer runs on through the round ends: V 2736.279, 7 faces."""
        chamfer = self.dressUp("Chamfer")
        self.assertResult(chamfer, 2650.944, 10)
        self.edit(chamfer)
        box = self.box()
        self.assertIsNotNone(box, "no Tangent propagation box")
        self.assertTrue(box.isChecked())
        box.click()
        pump(0.3)
        self.assertFalse(chamfer.TangentPropagation)
        self.ok()
        self.assertResult(chamfer, 2736.279, 7)

    def testCancelPutsTangentPropagationBack(self):
        chamfer = self.dressUp("Chamfer")
        self.edit(chamfer)
        self.box().click()
        pump(0.3)
        self.assertFalse(chamfer.TangentPropagation)
        self.cancel()
        self.assertTrue(chamfer.TangentPropagation)
        self.assertResult(chamfer, 2650.944, 10)
