# SPDX-License-Identifier: LGPL-2.1-or-later
# ****************************************************************************
# *                                                                          *
# *   This file is part of FreeCAD.                                          *
# *                                                                          *
# *   FreeCAD is free software: you can redistribute it and/or modify it     *
# *   under the terms of the GNU Lesser General Public License as            *
# *   published by the Free Software Foundation, either version 2.1 of the   *
# *   License, or (at your option) any later version.                        *
# *                                                                          *
# *   FreeCAD is distributed in the hope that it will be useful, but         *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of             *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU       *
# *   Lesser General Public License for more details.                        *
# *                                                                          *
# *   You should have received a copy of the GNU Lesser General Public       *
# *   License along with FreeCAD. If not, see                                *
# *   <https://www.gnu.org/licenses/>.                                       *
# *                                                                          *
# ***************************************************************************/

"""The mode buttons Part Studio / Assembly / Drawing (FreeCAD-CH, ops#640, rank 58).

Onshape's tab is a Part Studio, an Assembly or a Drawing, and the toolbar follows it. Under the
Onshape keymap a "Modes" toolbar (MainWindow.cpp) switches the workbench and makes the active
document's assembly or drawing when it has none; the button of the active mode is checked. The
workbench list stays in View > Workbench.
"""

import os
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

KEYMAP = "User parameter:BaseApp/Preferences/General"  # the preference Keymap (ForkKeymap)


def techDrawTemplateReadable():
    """Whether TechDraw_PageDefault finds a template (Preferences::defaultTemplate): without one
    it shows a modal message box, which would stop the test."""
    default = os.path.join(
        App.getResourceDir(), "Mod", "TechDraw", "Templates", "Default_Template_A4_Landscape.svg"
    )
    files = App.ParamGet("User parameter:BaseApp/Preferences/Mod/TechDraw/Files")
    chosen = files.GetString("TemplateFile", default) or default
    return os.access(chosen, os.R_OK) or os.access(default, os.R_OK)


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class TestModeToolBarGui(unittest.TestCase):
    def setUp(self):
        self.mw = Gui.getMainWindow()
        self.bar = self.mw.findChild(QtWidgets.QToolBar, "FreeCADCH_Modes")
        self.startWorkbench = Gui.activeWorkbench().name()
        self.doc = App.newDocument("TestModeToolBarGui")
        pump(0.1)

    def tearDown(self):
        # Assembly_CreateAssembly opens the new assembly in edit mode
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump(0.1)
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        Gui.activateWorkbench(self.startWorkbench)
        pump(0.1)

    def action(self, workbench):
        for action in self.bar.actions():
            if action.objectName() == workbench:
                return action
        self.fail("no mode button for " + workbench)

    def objectsOf(self, typeId):
        return [o for o in self.doc.Objects if o.TypeId == typeId]

    def test_the_buttons(self):
        self.assertIsNotNone(self.bar, "no Modes toolbar")
        self.assertEqual(
            [a.text() for a in self.bar.actions()], ["Part Studio", "Assembly", "Drawing"]
        )
        Gui.activateWorkbench("PartDesignWorkbench")
        pump()
        onshape = App.ParamGet(KEYMAP).GetString("Keymap", "Onshape") != "FreeCAD"
        self.assertEqual(not self.bar.isHidden(), onshape)
        self.assertTrue(self.action("PartDesignWorkbench").isChecked())
        self.assertFalse(self.action("AssemblyWorkbench").isChecked())
        # Another workbench, from View > Workbench: no mode is checked
        Gui.activateWorkbench("PartWorkbench")
        pump()
        self.assertFalse(any(a.isChecked() for a in self.bar.actions()))

    def test_assembly_made_once(self):
        """Assembly: the workbench, and one assembly in the document, made by the first click."""
        self.assertIsNotNone(self.bar)
        self.action("AssemblyWorkbench").trigger()
        pump()
        self.assertEqual(Gui.activeWorkbench().name(), "AssemblyWorkbench")
        self.assertEqual(len(self.objectsOf("Assembly::AssemblyObject")), 1)
        self.assertTrue(self.action("AssemblyWorkbench").isChecked())
        self.action("PartDesignWorkbench").trigger()
        pump()
        self.assertEqual(Gui.activeWorkbench().name(), "PartDesignWorkbench")
        self.assertTrue(self.action("PartDesignWorkbench").isChecked())
        self.action("AssemblyWorkbench").trigger()
        pump()
        self.assertEqual(len(self.objectsOf("Assembly::AssemblyObject")), 1)
        # Clicking the checked mode again keeps it checked
        self.action("AssemblyWorkbench").trigger()
        pump()
        self.assertTrue(self.action("AssemblyWorkbench").isChecked())

    def test_assembly_made_when_its_workbench_is_active(self):
        """Assembly clicked while the Assembly workbench is active already, in a document with no
        assembly: the assembly is made all the same (activateWorkbench returns false there)."""
        self.assertIsNotNone(self.bar)
        Gui.activateWorkbench("AssemblyWorkbench")
        pump()
        self.assertEqual(len(self.objectsOf("Assembly::AssemblyObject")), 0)
        self.action("AssemblyWorkbench").trigger()
        pump()
        self.assertEqual(len(self.objectsOf("Assembly::AssemblyObject")), 1)
        self.assertTrue(self.action("AssemblyWorkbench").isChecked())

    @unittest.skipUnless(techDrawTemplateReadable(), "no readable TechDraw template")
    def test_drawing_made_once(self):
        """Drawing: the workbench, and one drawing page in the document."""
        self.assertIsNotNone(self.bar)
        self.action("TechDrawWorkbench").trigger()
        pump()
        self.assertEqual(Gui.activeWorkbench().name(), "TechDrawWorkbench")
        self.assertEqual(len(self.objectsOf("TechDraw::DrawPage")), 1)
        self.action("TechDrawWorkbench").trigger()
        pump()
        self.assertEqual(len(self.objectsOf("TechDraw::DrawPage")), 1)


if __name__ == "__main__":
    unittest.main()
