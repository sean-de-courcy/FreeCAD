# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""Task panel previews that went stale (FreeCAD-CH, ops#148).

- A dress-up's preview takes the error colour while the feature fails, and loses it with the
  next good recompute, whatever made it: "Use all edges" on a Chamfer or Fillet made with
  nothing selected left the preview red until a value was edited, though OK made a good feature.
- A Pad or Pocket switched to a type that can't compute yet (To last with nothing below it, Up to
  face before a face is picked) showed the last good preview; it shows nothing until the feature
  computes again.

Designed models, each built by the test:
- Box: a 10 x 10 x 10 additive box. A Chamfer or Fillet made with nothing selected has no edges
  and fails. The chamfer of all 12 edges, size 1, is the cube cut by the 12 planes |x| + |y| = 9
  (centred): 12 prisms of 5 mm^3 off, less each corner's three pairwise overlaps of 1/3 mm^3,
  plus their common part, 1/3 mm^3: 945.33 mm^3 left.
- Plate: a 10 x 10 rectangle padded 10 as the Body's first feature: To last and To first have
  no solid to reach, Up to face and Up to shape nothing picked; all four fail.
- Pocket: a 2 x 2 square on the box's top, pocketed 3 (988 mm^3 left); Up to face and Up to
  shape fail with nothing picked.

Off screen: QT_QPA_PLATFORM=offscreen, a fresh FREECAD_USER_HOME (notes/build.md)."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui
from PySide import QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestExpressionFieldsGui import pump, taskButton, waitFor

CHAMFERED_BOX = 1000 - (12 * 5 - 8 * (3 * 1 / 3) + 8 * 1 / 3)


def previewNodes(feature):
    """The feature's preview shapes in scene order: its preview shape, then (a pocket) the tool
    shape, then (a sketch-based feature) the profile."""
    from pivy import coin

    search = coin.SoSearchAction()
    search.setType(coin.SoType.fromName("SoPreviewShape"))
    search.setInterest(coin.SoSearchAction.ALL)
    search.setSearchingAll(True)
    search.apply(feature.ViewObject.PreviewRootNode)
    return [path.getTail() for path in search.getPaths()]


def drawn(node):
    """How much of a preview shape is drawn: the face and line indices under it (a stale preview
    keeps its last shape's)."""
    from pivy import coin

    count = 0
    for type_ in (coin.SoIndexedFaceSet.getClassTypeId(), coin.SoIndexedLineSet.getClassTypeId()):
        search = coin.SoSearchAction()
        search.setType(type_, True)
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(node)
        count += sum(path.getTail().coordIndex.getNum() for path in search.getPaths())
    return count


def color(node):
    return tuple(round(c, 3) for c in node.getField("color").getValue().getValue())


class TestStalePreviewGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("StalePreview")
        Gui.Selection.clearSelection()

    def tearDown(self):
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

    def box(self):
        self.body = models.body(self.doc)
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length = 10
        box.Width = 10
        box.Height = 10
        self.doc.recompute()
        return box

    def edit(self, feature):
        Gui.getDocument(self.doc.Name).setEdit(feature.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "the dialog didn't open")
        pump()

    def newDressUp(self, command, name):
        """The box, and a new dress-up made as the command makes one with nothing selected: no
        edges, so it fails, its dialog open."""
        self.box()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "the dialog didn't open")
        pump()
        feature = self.doc.getObject(name)
        self.assertIsNotNone(feature)
        self.assertEqual(feature.Base[1], [])
        self.assertIn("Invalid", feature.State)
        return feature

    def setMode(self, label):
        combo = Gui.getMainWindow().findChild(QtWidgets.QComboBox, "changeMode")
        index = combo.findText(label)
        self.assertGreaterEqual(index, 0, f"no mode {label!r}")
        combo.setCurrentIndex(index)
        pump()

    # -- a dress-up's error colour ---------------------------------------------------------------

    def checkUseAllEdges(self, feature):
        """Red while the dress-up fails; "Use all edges" makes it good and the preview takes the
        dress-up colour; unticked it fails again and is red again."""
        errorColor = color(previewNodes(feature)[0])
        goodColor = tuple(round(c, 3) for c in feature.ViewObject.PreviewColor[:3])
        self.assertNotEqual(errorColor, goodColor, "the failing dress-up isn't shown as failing")

        useAll = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "checkBoxUseAllEdges")
        useAll.setChecked(True)
        self.assertTrue(waitFor(lambda: "Invalid" not in feature.State), feature.State)
        pump()
        self.assertEqual(color(previewNodes(feature)[0]), goodColor)
        self.assertGreater(drawn(previewNodes(feature)[0]), 0)

        useAll.setChecked(False)
        self.assertTrue(waitFor(lambda: "Invalid" in feature.State), feature.State)
        pump()
        self.assertEqual(color(previewNodes(feature)[0]), errorColor)

    def testChamferUseAllEdges(self):
        chamfer = self.newDressUp("PartDesign_Chamfer", "Chamfer")
        self.checkUseAllEdges(chamfer)
        useAll = Gui.getMainWindow().findChild(QtWidgets.QCheckBox, "checkBoxUseAllEdges")
        useAll.setChecked(True)
        pump()
        taskButton(QtWidgets.QDialogButtonBox.Ok).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog didn't close")
        self.assertAlmostEqual(chamfer.Shape.Volume, CHAMFERED_BOX, places=3)

    def testFilletUseAllEdges(self):
        fillet = self.newDressUp("PartDesign_Fillet", "Fillet")
        self.checkUseAllEdges(fillet)

    # -- a Pad or Pocket that can't compute ------------------------------------------------------

    def testPadTypesWithoutResult(self):
        """The Plate: each type that fails shows no preview; Dimension shows it again."""
        self.body = models.body(self.doc)
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 10, 10), self.body)
        pad = models.pad(self.body, profile, 10)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 1000, places=6)
        self.edit(pad)
        self.assertGreater(drawn(previewNodes(pad)[0]), 0)

        for label in ("To last", "To first", "Up to face", "Up to shape"):
            with self.subTest(label):
                self.setMode(label)
                self.assertIn("Invalid", pad.State)
                self.assertEqual(drawn(previewNodes(pad)[0]), 0, "the last good preview stays")
                self.setMode("Dimension")
                self.assertNotIn("Invalid", pad.State)
                self.assertGreater(drawn(previewNodes(pad)[0]), 0)

    def testPocketUpToFaceWithoutFace(self):
        """The Pocket: Up to face and Up to shape show neither the removed volume nor the tool
        until they compute; Dimension shows both again."""
        self.box()
        square = models.sketch(self.doc, "Square", models.rectangle(2, 2, 4, 4), self.body, z=10)
        pocket = models.pocket(self.body, square, 3)
        self.doc.recompute()
        self.assertAlmostEqual(pocket.Shape.Volume, 988, places=3)
        self.edit(pocket)
        shape, tool = previewNodes(pocket)[:2]
        self.assertGreater(drawn(shape), 0)
        self.assertGreater(drawn(tool), 0)

        for label in ("Up to face", "Up to shape"):
            with self.subTest(label):
                self.setMode(label)
                self.assertIn("Invalid", pocket.State)
                self.assertEqual((drawn(shape), drawn(tool)), (0, 0), "the last good preview stays")
                self.setMode("Dimension")
                self.assertNotIn("Invalid", pocket.State)
                self.assertGreater(drawn(shape), 0)
                self.assertGreater(drawn(tool), 0)
