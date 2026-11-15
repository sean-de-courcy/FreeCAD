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

"""Enter with the focus in a pick list accepts the dialog (FreeCAD-CH, ops#640 gaps3 row 5, ops#627).

Onshape (oracle 24, G3-3, fact UI1): open Fillet, pick an edge, and with the focus still in the
edges list Enter accepts the feature. A ReferenceField's list says so with the property
enterAccepts, which TaskView::keyPressEvent reads; a list whose Enter opens its item
(MultiTransform's) keeps it. The sketch editor's lists are guarded by
TestOnshapeStudioGui.testEnterInTheSketchEditorKeepsItOpen.

Designed model: a 10 x 10 x 10 additive box (1000 mm^3); a dress-up on its edges removes or adds
material, so its volume differs from the box's."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets
from PySide6 import QtTest

from PartDesignTests.TestDressUpDeleteKeyGui import focus, pump, waitFor

BOX = 10.0
EDGE_A = "Edge1"
EDGE_B = "Edge3"


def referenceLists():
    """The visible ReferenceField lists of the open dialog."""
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    return [
        widget.findChild(QtWidgets.QListWidget, "entries")
        for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget)
        if widget.metaObject().className() == "PartDesignGui::ReferenceField"
        and widget.isVisible()
    ]


def visibleChild(name):
    for widget in Gui.getMainWindow().findChildren(QtWidgets.QWidget, name):
        if widget.isVisible():
            return widget
    return None


class DressUpCase(unittest.TestCase):
    """A Body with a 10 mm additive box, and a dress-up made the user's way: one edge selected,
    then the command (its dialog opens with the edges list armed and focused, Q2/rank 14)."""

    def setUp(self):
        self.doc = App.newDocument("EnterInPickList")
        self.doc.UndoMode = 1
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.box = self.doc.addObject("PartDesign::AdditiveBox", "Box")
        self.body.addObject(self.box)
        for prop in ("Length", "Width", "Height"):
            setattr(self.box, prop, BOX)
        self.doc.recompute()
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        Gui.activateWorkbench("PartDesignWorkbench")
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        pump()

    def newDressUp(self, command):
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, f"{self.box.Name}.{EDGE_A}")
        Gui.runCommand(command)
        self.assertTrue(waitFor(lambda: len(referenceLists()) == 1), "no edges list")
        # the dialog's late switch back to the Model tab hides the task view (TestDressUpDeleteKeyGui)
        pump(0.3)
        Gui.Control.showTaskView()
        self.assertTrue(waitFor(lambda: len(referenceLists()) == 1), "the edges list is hidden")
        edges = referenceLists()[0]
        self.assertTrue(focus(edges), "the edges list doesn't take the focus")
        return edges

    def pickSecondEdge(self):
        """A pick in the 3D view, as the armed field takes it (the selection, not the mouse)."""
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, f"{self.box.Name}.{EDGE_B}")
        pump(0.5)

    def dressUps(self, typeName):
        return [o for o in self.doc.Objects if o.isDerivedFrom(typeName)]


class TestEnterInPickListGui(DressUpCase):
    """Row 5 (ops#627): Enter with the focus in a pick list accepts, as Onshape's Enter (PL3c,
    G3-3). Lists whose Enter opens their item keep it (MultiTransform; the sketch editor's guard
    is TestOnshapeStudioGui.testEnterInTheSketchEditorKeepsItOpen)."""

    def testEnterInTheFilletEdgesListAccepts(self):
        edges = self.newDressUp("PartDesign_Fillet")
        self.pickSecondEdge()
        self.assertTrue(focus(edges))
        QtTest.QTest.keyClick(edges, QtCore.Qt.Key_Return)
        pump(0.5)
        self.assertFalse(Gui.Control.activeDialog(), "Enter in the edges list left the dialog open")
        fillets = self.dressUps("PartDesign::Fillet")
        self.assertEqual(len(fillets), 1)
        self.assertTrue(fillets[0].isValid(), fillets[0].getStatusString())
        self.assertEqual(sorted(fillets[0].Base[1]), sorted([EDGE_A, EDGE_B]))
        self.assertLess(fillets[0].Shape.Volume, BOX**3)

    def testKeypadEnterInTheChamferEdgesListAccepts(self):
        edges = self.newDressUp("PartDesign_Chamfer")
        QtTest.QTest.keyClick(edges, QtCore.Qt.Key_Enter, QtCore.Qt.KeypadModifier)
        pump(0.5)
        self.assertFalse(Gui.Control.activeDialog())
        chamfers = self.dressUps("PartDesign::Chamfer")
        self.assertEqual(len(chamfers), 1)
        self.assertLess(chamfers[0].Shape.Volume, BOX**3)

    def testEnterInAnEditsEdgesListAccepts(self):
        edges = self.newDressUp("PartDesign_Fillet")
        QtTest.QTest.keyClick(edges, QtCore.Qt.Key_Return)
        pump(0.5)
        fillet = self.dressUps("PartDesign::Fillet")[0]
        fillet.Radius = 2.0  # changed under the closed dialog: the edit must keep it
        self.doc.recompute()
        Gui.ActiveDocument.setEdit(fillet.Name)
        self.assertTrue(waitFor(lambda: len(referenceLists()) == 1))
        pump(0.3)
        Gui.Control.showTaskView()
        self.assertTrue(waitFor(lambda: len(referenceLists()) == 1))
        edges = referenceLists()[0]
        self.assertTrue(focus(edges))
        QtTest.QTest.keyClick(edges, QtCore.Qt.Key_Return)
        pump(0.5)
        self.assertFalse(Gui.Control.activeDialog())
        self.assertAlmostEqual(fillet.Radius.Value, 2.0)

    def testEnterInMultiTransformsListOpensItsItem(self):
        """The carve-out: the list's Enter opens the transformation's sub-task, the dialog stays."""
        mirror = self.doc.addObject("PartDesign::MultiTransform", "MultiTransform")
        self.body.addObject(mirror)
        mirror.Originals = [self.box]
        mirrored = self.doc.addObject("PartDesign::Mirrored", "Mirrored")
        self.body.addObject(mirrored)
        mirrored.MirrorPlane = (self.body.Origin.OriginFeatures[4], [""])  # the YZ plane
        mirror.Transformations = [mirrored]
        self.doc.recompute()
        Gui.ActiveDocument.setEdit(mirror.Name)
        pump(1.0)
        listWidget = visibleChild("listTransformFeatures")
        self.assertIsNotNone(listWidget)
        listWidget.setCurrentRow(0)
        self.assertTrue(focus(listWidget))
        QtTest.QTest.keyClick(listWidget, QtCore.Qt.Key_Return)
        pump(0.5)
        self.assertTrue(Gui.Control.activeDialog(), "Enter in MultiTransform's list accepted it")


if __name__ == "__main__":
    unittest.main()
