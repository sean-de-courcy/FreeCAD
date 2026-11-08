# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Extrude dialog's fields in Onshape's order and words (FreeCAD-CH ops#640, rank 22): the end
types Blind, Up to next, Up to face, Up to part, Up to vertex, Through all, a Pocket's too (Up to
last, which Onshape hasn't,
hidden unless a feature ends so); Symmetric and Second end position as checkboxes for the Sides
box; Starting offset as a checkbox for the Start box; a Draft checkbox for the taper; no Recompute
on change. The saved enums are unchanged. Designed geometry: a 10 x 10 square on XY padded 10.
Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

from PySide import QtCore, QtWidgets

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PartDesignTests.Scenarios import models
from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor


class TestExtrudeFieldsGui(ResultBoxGuiCase):
    def plate(self, base=False, **values):
        """The square padded 10, its dialog open; with `base`, on a 20 x 20 x 20 block around it
        (z 0..20), for the end types that need a solid to end at."""
        self.body = models.body(self.doc)
        if base:
            block = models.sketch(self.doc, "Block", models.rectangle(-5, -5, 15, 15), self.body)
            models.pad(self.body, block, 20, "BlockPad")
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, profile, 10)
        for name, value in values.items():
            setattr(pad, name, value)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        pad.ViewObject.doubleClicked()
        self.waitForPanel()
        return pad

    def box(self, cls, name):
        """The open panel's widget, shown or not."""
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
        found = Gui.getMainWindow().findChildren(cls, name)
        self.assertTrue(found, "no " + name)
        return found[0]

    def testEndTypesInOnshapesWords(self):
        """Blind, Up to next, Up to face, Up to part, Up to vertex, Through all shown; Up to last
        listed but hidden and unpickable on a Blind pad."""
        self.plate()
        combo = self.box(QtWidgets.QComboBox, "changeMode")
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())],
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
        self.assertEqual(combo.currentText(), "Blind")
        self.assertTrue(combo.view().isRowHidden(1))
        self.assertFalse(combo.model().item(1).isEnabled())
        self.assertFalse(combo.view().isRowHidden(5))
        self.assertFalse(combo.view().isRowHidden(6))

    def choose(self, combo, text):
        index = combo.findText(text)
        self.assertGreaterEqual(index, 0, text)
        combo.setCurrentIndex(index)
        pump(0.3)

    def testUpToVertexPicksAVertex(self):
        """Up to vertex (ops#640 rank 22): its field shows and arms, the face's stays hidden; a pick
        of a marker sketch's vertex at z 25 pads the 10 x 10 square up to z 25 (2500); OK keeps
        Type UpToVertex and the vertex. Blind again hides the field."""
        self.body = models.body(self.doc)
        marker = models.sketch(
            self.doc, "Marker", [Part.LineSegment(App.Vector(20, 0, 0), App.Vector(21, 2, 0))],
            self.body, z=25,
        )
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, profile, 10)
        self.doc.recompute()
        [vertex] = [
            "Vertex%d" % (i + 1)
            for i, v in enumerate(marker.Shape.Vertexes)
            if v.Point.distanceToPoint(App.Vector(20, 0, 25)) < 1e-7
        ]
        pad.ViewObject.doubleClicked()
        self.waitForPanel()
        combo = self.box(QtWidgets.QComboBox, "changeMode")
        self.choose(combo, "Up to vertex")
        self.assertEqual(pad.Type, "UpToVertex")
        field = self.box(QtWidgets.QWidget, "fieldUpToVertex")
        self.assertTrue(waitFor(lambda: field.isVisible() and bool(field.property("armed"))))
        self.assertIsNone(self.visible(QtWidgets.QWidget, "fieldUpToFace"))
        Gui.Selection.addSelection(self.doc.Name, marker.Name, vertex)
        pump(0.3)
        self.assertIsNotNone(pad.UpToFace)
        self.assertEqual(pad.UpToFace[0].Name, marker.Name)
        self.assertEqual([s for s in pad.UpToFace[1] if s], [vertex])
        self.assertAlmostEqual(pad.Shape.Volume, 2500, places=6)
        self.close(ok=True)
        self.assertEqual(pad.Type, "UpToVertex")
        self.assertEqual(pad.UpToFace[0].Name, marker.Name)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 2500, places=6)
        pad.ViewObject.doubleClicked()
        self.waitForPanel()
        combo = self.box(QtWidgets.QComboBox, "changeMode")
        self.assertEqual(combo.currentText(), "Up to vertex")
        self.choose(combo, "Blind")
        self.assertIsNone(self.visible(QtWidgets.QWidget, "fieldUpToVertex"))
        self.close(ok=True)
        self.assertEqual(pad.Type, "Length")
        self.assertIsNone(pad.UpToFace)

    def testPocketEndTypesInOnshapesOrder(self):
        """A Pocket (the older class, rank 22 item 3): Blind, Up to next, Up to face, Up to part, Up
        to vertex, Through all, Up to last hidden; Through all chosen writes ThroughAll."""
        self.body = models.body(self.doc)
        block = models.sketch(self.doc, "Block", models.rectangle(-5, -5, 15, 15), self.body)
        models.pad(self.body, block, 30, "BlockPad")
        top = models.sketch(self.doc, "Top", models.rectangle(0, 0, 10, 10), self.body, z=30)
        pocket = models.pocket(self.body, top, 5)
        self.doc.recompute()
        pocket.ViewObject.doubleClicked()
        self.waitForPanel()
        combo = self.box(QtWidgets.QComboBox, "changeMode")
        self.assertEqual(
            [combo.itemText(i) for i in range(combo.count())],
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
        self.assertTrue(combo.view().isRowHidden(6))
        self.assertEqual(combo.currentText(), "Blind")
        self.choose(combo, "Through all")
        self.assertEqual(pocket.Type, "ThroughAll")
        self.close(ok=True)
        self.assertEqual(pocket.Type, "ThroughAll")

    def testAnOlderUpToLastStaysShown(self):
        """A pad that ends Up to last (an older file) shows it, and keeps it on OK. On the block:
        Up to last needs a solid to end at."""
        pad = self.plate(base=True, Type="UpToLast")
        combo = self.box(QtWidgets.QComboBox, "changeMode")
        self.assertEqual(combo.currentText(), "Up to last")
        self.assertFalse(combo.view().isRowHidden(1))
        self.close(ok=True)
        self.assertEqual(pad.Type, "UpToLast")

    def testSymmetricAndSecondEndAreCheckboxes(self):
        """The Sides box is hidden; Symmetric writes SideType Symmetric (the 10 deep pad centred
        on the sketch: z -5..5, volume 1000) and hides Second end position; Second end position
        writes Two sides and shows the second end's fields."""
        pad = self.plate()
        self.assertIsNone(self.visible(QtWidgets.QComboBox, "sidesMode"))
        symmetric = self.visible(QtWidgets.QCheckBox, "checkBoxSymmetric")
        secondEnd = self.visible(QtWidgets.QCheckBox, "checkBoxSecondEnd")
        self.assertIsNotNone(symmetric, "no Symmetric")
        self.assertIsNotNone(secondEnd, "no Second end position")
        self.assertIsNone(self.visible(QtWidgets.QComboBox, "changeMode2"))
        symmetric.setChecked(True)
        pump(0.3)
        self.assertEqual(pad.SideType, "Symmetric")
        self.assertIsNone(self.visible(QtWidgets.QCheckBox, "checkBoxSecondEnd"))
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, -5, places=6)
        self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 5, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 1000, places=6)
        symmetric.setChecked(False)
        pump(0.3)
        self.assertEqual(pad.SideType, "One side")
        secondEnd = self.visible(QtWidgets.QCheckBox, "checkBoxSecondEnd")
        self.assertIsNotNone(secondEnd)
        secondEnd.setChecked(True)
        pump(0.3)
        self.assertEqual(pad.SideType, "Two sides")
        self.assertIsNotNone(self.visible(QtWidgets.QComboBox, "changeMode2"))
        self.assertIsNone(self.visible(QtWidgets.QCheckBox, "checkBoxSymmetric"))
        self.close(ok=False)

    def testDraftShowsTheAngle(self):
        """No taper: Draft unticked and the angle hidden. Ticked, the angle shows; unticked
        again, the taper goes back to 0."""
        pad = self.plate()
        draft = self.visible(QtWidgets.QCheckBox, "checkBoxDraft")
        self.assertIsNotNone(draft, "no Draft")
        self.assertFalse(draft.isChecked())
        self.assertIsNone(self.visible(QtWidgets.QWidget, "taperEdit"))
        draft.setChecked(True)
        pump(0.3)
        taper = self.visible(QtWidgets.QWidget, "taperEdit")
        self.assertIsNotNone(taper, "the draft angle stays hidden")
        pad.TaperAngle = 5
        pad.recompute()
        draft.setChecked(False)
        pump(0.3)
        self.assertAlmostEqual(pad.TaperAngle.Value, 0, places=9)
        self.assertIsNone(self.visible(QtWidgets.QWidget, "taperEdit"))
        self.close(ok=False)

    def testDraftUntickedDropsATaperExpression(self):
        """A taper bound to an expression (5 deg): unticking Draft clears the expression too, so
        the next recompute keeps the 0 (the expression would put 5 back)."""
        pad = self.plate(TaperAngle=5)
        pad.setExpression("TaperAngle", "5 deg")
        self.doc.recompute()
        draft = self.visible(QtWidgets.QCheckBox, "checkBoxDraft")
        self.assertTrue(draft.isChecked())
        draft.setChecked(False)
        pump(0.3)
        self.close(ok=True)
        self.doc.recompute()
        self.assertNotIn("TaperAngle", dict(pad.ExpressionEngine))
        self.assertAlmostEqual(pad.TaperAngle.Value, 0, places=9)
        self.assertAlmostEqual(pad.Shape.Volume, 1000, places=6)

    def testATaperedPadOpensWithDraftTicked(self):
        pad = self.plate(TaperAngle=5)
        draft = self.visible(QtWidgets.QCheckBox, "checkBoxDraft")
        self.assertTrue(draft.isChecked())
        self.assertIsNotNone(self.visible(QtWidgets.QWidget, "taperEdit"))
        self.close(ok=True)
        self.assertAlmostEqual(pad.TaperAngle.Value, 5, places=9)

    def testStartingOffsetIsACheckbox(self):
        """The Start box is hidden; Starting offset writes the Offset start and shows its depth;
        unticked, the profile plane again."""
        pad = self.plate()
        self.assertIsNone(self.visible(QtWidgets.QComboBox, "startMode"))
        start = self.visible(QtWidgets.QCheckBox, "checkBoxStartingOffset")
        self.assertIsNotNone(start, "no Starting offset")
        start.setChecked(True)
        pump(0.3)
        self.assertEqual(pad.StartType, "Offset")
        self.assertIsNotNone(self.visible(QtWidgets.QWidget, "startOffsetEdit"))
        start.setChecked(False)
        pump(0.3)
        self.assertEqual(pad.StartType, "Profile plane")
        self.close(ok=False)

    def testNoRecomputeOnChange(self):
        self.plate()
        self.assertIsNone(self.visible(QtWidgets.QCheckBox, "checkBoxUpdateView"))
        self.assertTrue(self.box(QtWidgets.QCheckBox, "checkBoxUpdateView").isChecked())
