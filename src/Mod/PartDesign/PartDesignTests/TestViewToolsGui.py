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

"""The view tools of Onshape's View menu (FreeCAD-CH, ops#640): the section view, named views,
display styles and the camera.

Designed model: one 20 x 20 x 20 box at the origin. The oracles are data: what the view reports
(section plane, camera string, camera type), what the document stores (named views), the menu
entries and the commands' checked state. What the screen shows (the cap, the dashed hidden
edges) is not asserted here."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets


def pump(seconds=0.3):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


def menuActions(menuTitle):
    """The objectNames of the actions of the menu-bar menu with this title, in order."""
    for menu in Gui.getMainWindow().menuBar().findChildren(QtWidgets.QMenu):
        if menu.title().replace("&", "") == menuTitle:
            return [a.objectName() for a in menu.actions()]
    return None


class ViewToolsCase(unittest.TestCase):
    """A document with a box and its 3D view, active."""

    docName = "ViewToolsGui"

    @classmethod
    def setUpClass(cls):
        import PartGui  # noqa: F401

        Gui.activateWorkbench("PartDesignWorkbench")
        pump()

    def setUp(self):
        self.doc = App.newDocument(self.docName)
        box = self.doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 20
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        mdi = Gui.getMainWindow().findChild(QtWidgets.QMdiArea)
        windows = [
            w
            for w in mdi.subWindowList()
            if w.widget().metaObject().className() == "Gui::View3DInventor"
        ]
        self.assertTrue(windows, "the document's 3D view")
        mdi.setActiveSubWindow(windows[-1])
        self.viewWindows = windows  # held: PySide drops a view's wrapper with its sub-window's
        self.view = Gui.ActiveDocument.ActiveView
        pump()

    def tearDown(self):
        App.closeDocument(self.doc.Name)
        pump(0.1)


class TestSectionViewGui(ViewToolsCase):
    """Std_SectionView: a view-only section (ops#640, view tools 1)."""

    docName = "SectionViewGui"

    def tearDown(self):
        self.view.clearSectionView()
        Gui.runCommand("Std_SectionView", 0)
        pump(0.1)
        super().tearDown()

    def assertVec(self, got, want):
        self.assertEqual(len(got), 3)
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=4)

    def testNoSectionAtFirst(self):
        self.assertIsNone(self.view.sectionView())

    def testSetQueryAndClear(self):
        self.view.setSectionView(origin=(1, 2, 3), normal=(0, 0, 2))
        origin, normal = self.view.sectionView()
        self.assertVec(origin, (1, 2, 3))
        self.assertVec(normal, (0, 0, 1))  # the normal comes back unit length
        self.view.setSectionView(origin=(0, 5, 0), normal=(App.Vector(0, -1, 0)))
        origin, normal = self.view.sectionView()
        self.assertVec(origin, (0, 5, 0))
        self.assertVec(normal, (0, -1, 0))
        self.view.clearSectionView()
        self.assertIsNone(self.view.sectionView())
        self.view.clearSectionView()  # nothing to clear is fine

    def testNormalNeedsALength(self):
        with self.assertRaises(ValueError):
            self.view.setSectionView(origin=(0, 0, 0), normal=(0, 0, 0))
        self.assertIsNone(self.view.sectionView())

    def testSectionIsViewOnly(self):
        """Nothing goes into the document: no object, no touched flag."""
        count = len(self.doc.Objects)
        self.doc.recompute()
        self.assertEqual(self.doc.getObject("Box").State.count("Touched"), 0)
        self.view.setSectionView(origin=(0, 0, 10), normal=(0, 0, 1))
        pump()
        self.assertEqual(len(self.doc.Objects), count)
        self.assertEqual(self.doc.getObject("Box").State.count("Touched"), 0)

    def testCommandIsRegisteredAndCheckable(self):
        cmd = Gui.Command.get("Std_SectionView")
        self.assertIsNotNone(cmd)
        actions = cmd.getAction()
        self.assertTrue(actions)
        self.assertTrue(actions[0].isCheckable())

    def testCommandTogglesTheSectionAndItsCheck(self):
        action = Gui.Command.get("Std_SectionView").getAction()[0]
        Gui.runCommand("Std_SectionView", 1)
        pump()
        section = self.view.sectionView()
        self.assertIsNotNone(section, "the command starts a section")
        self.assertVec(section[0], (0, 0, 0))  # through the origin
        self.assertVec(section[1], (0, -1, 0))  # the front plane, the viewer's side is cut
        self.assertTrue(action.isChecked())
        Gui.runCommand("Std_SectionView", 0)
        pump()
        self.assertIsNone(self.view.sectionView())
        self.assertFalse(action.isChecked())

    def testCheckFollowsASectionSetFromPython(self):
        action = Gui.Command.get("Std_SectionView").getAction()[0]
        self.view.setSectionView(origin=(0, 0, 5), normal=(1, 0, 0))
        Gui.runCommand("Std_SectionView", 1)  # the panel keeps the section that is there
        pump()
        origin, normal = self.view.sectionView()
        self.assertVec(origin, (0, 0, 5))
        self.assertVec(normal, (1, 0, 0))
        self.assertTrue(action.isChecked())

    def testSectionViewIsInTheViewMenu(self):
        entries = menuActions("View")
        self.assertIsNotNone(entries, "the View menu")
        self.assertIn("Std_SectionView", entries)
        self.assertIn("Std_ToggleClipPlane", entries)  # the clipping dialog stays


if __name__ == "__main__":
    unittest.main()
