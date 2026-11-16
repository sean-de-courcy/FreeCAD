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

"""One Esc cancels a feature's dialog (FreeCAD-CH, ops#640 rank 25).

Onshape (hands-on R1): Esc, even with the cursor in the depth field, cancels a new Extrude at
once, with no prompt; the feature's row goes. Here one Esc cancels wherever the focus is in the
dialog or the 3D view, a reference field armed or not (decision 23 Q1 (a) had the first Esc only
disarm an armed field; that is reversed). An edit cancelled so is as before the edit.

Designed models, each built by the test:
- Square: a sketch of the square 0..10 x 0..10 at z = 0 in a Body. A Pad of it, 5 long, is
  500 mm^3; 7 long, 700.
- Box: a 10 x 10 x 10 additive box (1000 mm^3) and a new fillet on it, made by the command with
  nothing selected (its edge field armed); the box's top front edge picked.

Keys go through the window (QTest's QWindow overload), so the shortcut map sees them as it sees a
user's."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDressUpDeleteKeyGui import focus, pump, taskButton, waitFor
from PartDesignTests.TestReferenceFieldGui import (
    TOP_FRONT,
    armed,
    entries,
    fields,
    flushDeletes,
    key,
    settle,
    views3D,
)


class TestEscCancelsGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("EscCancels")
        self.doc.UndoMode = 1
        Gui.Selection.clearSelection()
        Gui.getMainWindow().activateWindow()

    def tearDown(self):
        guiDoc = Gui.getDocument(self.doc.Name)
        if Gui.Control.activeDialog():
            cancel = taskButton(QtWidgets.QDialogButtonBox.Cancel)
            if cancel is not None:
                cancel.click()
                pump()
        if guiDoc.getInEdit():
            guiDoc.resetEdit()
            pump()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        Gui.Selection.clearSelection()
        waitFor(lambda: not fields(), 3.0)
        for name in list(App.listDocuments()):
            if name.startswith("EscCancels"):
                App.closeDocument(name)
        pump()

    # -- models ---------------------------------------------------------------------------------

    def square(self):
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "Square", models.rectangle(0, 0, 10, 10), self.body)
        self.doc.recompute()
        return sketch

    def newPad(self):
        """The Square, selected, and PartDesign_Pad: a new pad, 10 long by default, its dialog
        open."""
        sketch = self.square()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, sketch.Name)
        Gui.runCommand("PartDesign_Pad")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Pad dialog")
        settle()
        pad = self.doc.getObject("Pad")
        self.assertIsNotNone(pad)
        return sketch, pad

    def newFillet(self):
        """The Box and a new fillet made with nothing selected: its edge field armed; the top
        front edge picked."""
        self.body = models.body(self.doc)
        box = self.doc.addObject("PartDesign::AdditiveBox", "Box")
        self.body.addObject(box)
        for prop in ("Length", "Width", "Height"):
            setattr(box, prop, 10)
        self.doc.recompute()
        Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", self.body)
        Gui.Selection.clearSelection()
        Gui.runCommand("PartDesign_Fillet")
        self.assertTrue(waitFor(lambda: len(fields()) == 1), "the fillet's reference field")
        settle()
        [field] = fields()
        self.assertTrue(waitFor(lambda: armed(field)), "a new fillet's field isn't armed")
        fillet = self.doc.getObject("Fillet")
        self.assertIsNotNone(fillet)
        [edge] = TOP_FRONT.one(box.Shape)
        Gui.Selection.addSelection(self.doc.Name, box.Name, edge)
        pump(0.2)
        self.assertTrue(waitFor(lambda: fillet.Base[1] == [edge]), fillet.Base)
        return box, fillet, field

    def assertCancelledAtOnce(self, name):
        """The dialog closed by the one Esc, the edit ended, the new feature `name` gone."""
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "one Esc left the dialog")
        pump(0.3)
        flushDeletes()
        self.assertIsNone(Gui.getDocument(self.doc.Name).getInEdit(), "the edit stays")
        self.assertIsNone(self.doc.getObject(name), "Esc left the new feature")

    def lengthField(self):
        edit = Gui.getMainWindow().findChild(QtWidgets.QWidget, "lengthEdit")
        self.assertIsNotNone(edit, "the Pad's length field")
        return edit

    # -- tests ----------------------------------------------------------------------------------

    def testEscInTheDepthFieldCancelsANewPad(self):
        """R1: a new Pad, a depth typed in its length field, Esc there: the Pad goes, the sketch
        shows again."""
        sketch, pad = self.newPad()
        length = self.lengthField()
        self.assertTrue(focus(length), "the length field doesn't take the focus")
        length.setProperty("rawValue", 7)
        pump(0.3)
        self.assertTrue(focus(length))
        key(QtCore.Qt.Key_Escape)
        self.assertCancelledAtOnce("Pad")
        self.assertTrue(sketch.ViewObject.Visibility, "the sketch stays hidden")

    def testEscInTheArmedFieldCancelsANewFillet(self):
        """A new fillet, its edge field armed with the focus in it and an edge picked: one Esc
        cancels; the box is whole."""
        box, fillet, field = self.newFillet()
        self.assertTrue(focus(entries(field)))
        self.assertTrue(armed(field))
        key(QtCore.Qt.Key_Escape)
        self.assertCancelledAtOnce("Fillet")
        self.assertAlmostEqual(box.Shape.Volume, 1000, places=6)

    def testEscInTheRadiusWithTheFieldArmedCancelsANewFillet(self):
        """The focus in the fillet's radius and the edge field armed (by its property, as a
        dialog arms it on opening): one Esc cancels."""
        box, fillet, field = self.newFillet()
        radius = Gui.getMainWindow().findChild(QtWidgets.QWidget, "filletRadius")
        self.assertIsNotNone(radius)
        self.assertTrue(focus(radius), "the radius doesn't take the focus")
        field.setProperty("armed", True)
        pump(0.1)
        self.assertTrue(armed(field))
        self.assertTrue(focus(radius))
        key(QtCore.Qt.Key_Escape)
        self.assertCancelledAtOnce("Fillet")

    def testEscInThe3DViewWithTheFieldArmedCancelsANewFillet(self):
        """The focus in the 3D view, where the picks come from, and the edge field armed: one Esc
        cancels (it only disarmed the field before)."""
        box, fillet, field = self.newFillet()
        [view] = views3D()
        self.assertTrue(focus(view), "the 3D view doesn't take the focus")
        self.assertTrue(armed(field), "the 3D view's focus disarmed the field")
        key(QtCore.Qt.Key_Escape)
        self.assertCancelledAtOnce("Fillet")
        self.assertAlmostEqual(box.Shape.Volume, 1000, places=6)

    def editPadTo7(self):
        """A Pad 5 long (500 mm^3), edited as a double click opens it (in a transaction Cancel
        aborts), its length set to 7 (700)."""
        sketch = self.square()
        pad = models.pad(self.body, sketch, 5)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 500, places=3)
        self.doc.openTransaction("Edit Pad")
        Gui.getDocument(self.doc.Name).setEdit(pad.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Pad dialog")
        settle()
        length = self.lengthField()
        length.setProperty("rawValue", 7)
        pump(0.3)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Shape.Volume, 700, places=3)
        return pad, length

    def assertPadAsBefore(self, pad):
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "one Esc left the dialog")
        pump(0.3)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Length.Value, 5, places=6)
        self.assertAlmostEqual(pad.Shape.Volume, 500, places=3)

    def testEscInThe3DViewCancelsAnEditWithTheProfileArmed(self):
        """Hands-on B-3: an edit's change, then Esc with the focus in the graphics: the dialog
        closes at once and the change is discarded; here with the profile field armed, which
        kept the dialog open before."""
        pad, length = self.editPadTo7()
        profile = Gui.getMainWindow().findChild(QtWidgets.QWidget, "fieldProfile")
        self.assertIsNotNone(profile, "the Pad's profile field")
        profile.setProperty("armed", True)
        pump(0.1)
        self.assertTrue(armed(profile), "the profile field isn't armed")
        [view] = views3D()
        self.assertTrue(focus(view), "the 3D view doesn't take the focus")
        self.assertTrue(armed(profile), "the 3D view's focus disarmed the field")
        key(QtCore.Qt.Key_Escape)
        self.assertPadAsBefore(pad)

    def testEscDiscardsATypedValueNotCommittedYet(self):
        """Journey J21 A0: an edit of a Pad 5 long, 12 typed in its length field with no Tab or
        Enter, one Esc there: the Pad is 5 long again, 500 mm^3, and no later event commits the
        typed 12 (the field's focus-out at the dialog's close did, into the previous step)."""
        sketch = self.square()
        pad = models.pad(self.body, sketch, 5)
        self.doc.recompute()
        self.doc.openTransaction("Edit Pad")
        Gui.getDocument(self.doc.Name).setEdit(pad.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no Pad dialog")
        settle()
        length = self.lengthField()
        self.assertTrue(focus(length), "the length field doesn't take the focus")
        line = length.findChild(QtWidgets.QLineEdit)
        line.selectAll()
        for ch in "12":
            key(getattr(QtCore.Qt, "Key_" + ch))
        pump(0.2)
        self.assertIn("12", line.text())
        self.assertAlmostEqual(pad.Length.Value, 5, places=6)
        key(QtCore.Qt.Key_Escape)
        self.assertPadAsBefore(pad)
        pump(0.5)
        self.doc.recompute()
        self.assertAlmostEqual(pad.Length.Value, 5, places=6, msg="the typed 12 came back")

    def testEscCancelsAnEdit(self):
        """An edit of a Pad 5 long, the length set to 7; one Esc in the length field: the Pad is
        5 long again, 500 mm^3 (hands-on B-3)."""
        pad, length = self.editPadTo7()
        self.assertTrue(focus(length), "the length field doesn't take the focus")
        key(QtCore.Qt.Key_Escape)
        self.assertPadAsBefore(pad)
