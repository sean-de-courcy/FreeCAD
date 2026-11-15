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

"""Editing a feature of a part the user hid (FreeCAD-CH, ops#640 gaps3 row 7, ops#637).

Onshape (oracle 24, G3-6, fact UI1): hide the part from its Parts row, edit its Extrude; the
part shows as the dialog's preview during the edit and is hidden again after OK. Here the Parts
row's Hide hides the Body: the edit shows the Body and hides it again on OK or Cancel. A Tip
the user hid with its own eye (ops#637, no Onshape counterpart) leaves the Body showing nothing
after the edit, as before it.

Designed model: a Base pad 40 x 40 x 10 and a Lid pad 20 x 20 x 5 on its top (z = 10), Lid the
Tip; Base + Lid is 18000 mm^3."""

import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

from PartDesignTests.Scenarios import models
from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor


class TestHiddenPartEditGui(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("HiddenPartEdit")
        self.body = models.body(self.doc)
        base = models.sketch(self.doc, "BaseSketch", models.rectangle(0, 0, 40, 40), self.body)
        models.pad(self.body, base, 10, name="Base")
        lid = models.sketch(self.doc, "LidSketch", models.rectangle(10, 10, 30, 30), self.body, z=10)
        self.lid = models.pad(self.body, lid, 5, name="Lid")
        self.doc.recompute()
        self.assertAlmostEqual(self.lid.Shape.Volume, 18000.0, places=3)
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        Gui.activateWorkbench("PartDesignWorkbench")
        pump(0.3)

    def tearDown(self):
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
            pump()
        App.closeDocument(self.doc.Name)
        pump()

    def state(self):
        """The Body's eye and the solid features shown in it."""
        shown = [
            o.Name
            for o in self.body.Group
            if o.isDerivedFrom("PartDesign::Feature") and o.ViewObject.Visibility
        ]
        return self.body.ViewObject.Visibility, shown

    def edit(self, button):
        """Opens Lid's dialog, then clicks OK or Cancel. Returns the state during the edit."""
        Gui.ActiveDocument.setEdit(self.lid.Name)
        self.assertTrue(waitFor(lambda: bool(Gui.Control.activeDialog())), "no Lid dialog")
        pump(0.5)
        during = self.state()
        taskButton(button).click()
        pump(0.5)
        self.assertFalse(Gui.Control.activeDialog())
        return during

    def testAHiddenPartShowsForTheEditAndIsHiddenAfterOk(self):
        self.body.ViewObject.Visibility = False
        pump()
        bodyShown, _ = self.edit(QtWidgets.QDialogButtonBox.Ok)
        self.assertTrue(bodyShown, "the hidden part isn't shown during its edit")
        self.assertEqual(self.state(), (False, ["Lid"]))
        self.assertAlmostEqual(self.lid.Shape.Volume, 18000.0, places=3)

    def testAHiddenPartIsHiddenAfterCancel(self):
        self.body.ViewObject.Visibility = False
        pump()
        bodyShown, _ = self.edit(QtWidgets.QDialogButtonBox.Cancel)
        self.assertTrue(bodyShown)
        self.assertEqual(self.state(), (False, ["Lid"]))

    def testATipHiddenByItsEyeStaysHidden(self):
        """ops#637: the edit's preview of Base doesn't stay shown after OK."""
        self.lid.ViewObject.Visibility = False
        pump()
        self.edit(QtWidgets.QDialogButtonBox.Ok)
        self.assertEqual(self.state(), (True, []))

    def testAShownPartStaysShown(self):
        """The control (ops#212, ops#218): nothing hidden, Lid shown after the edit."""
        self.edit(QtWidgets.QDialogButtonBox.Ok)
        self.assertEqual(self.state(), (True, ["Lid"]))


if __name__ == "__main__":
    unittest.main()
