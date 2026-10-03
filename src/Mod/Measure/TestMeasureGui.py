# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

################################################################################
#                                                                              #
#   FreeCAD is free software: you can redistribute it and/or modify            #
#   it under the terms of the GNU Lesser General Public License as             #
#   published by the Free Software Foundation, either version 2.1              #
#   of the License, or (at your option) any later version.                     #
#                                                                              #
#   FreeCAD is distributed in the hope that it will be useful,                 #
#   but WITHOUT ANY WARRANTY; without even the implied warranty                #
#   of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                    #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with FreeCAD. If not, see https://www.gnu.org/licenses       #
#                                                                              #
################################################################################

"""GUI tests for the Measure module's task panels."""

import unittest

import FreeCAD as App

if App.GuiUp:
    import FreeCADGui as Gui
    from PySide import QtCore, QtGui, QtWidgets


class TestMassPropertiesRemoveItem(unittest.TestCase):
    """Removing a row from the Mass Properties panel's "Objects to measure" list.

    Each row stores "doc|obj|sub". While the panel picks a custom coordinate system, a face
    pick is stored with its full subname, and a V2 mapped name of a split face contains '|'
    (its MOD section). Delete on such a row must still remove that selection and that row only.

    Model: box A 10x10x10 at the origin minus box B 2x12x10 at (4,-1,5), a groove across A's
    top face (Part::Cut "BF"), which splits the top face in two pieces; their V2 names have a
    '|'. Box C (10x10x10 at (20,0,0)) is the second row, so that Delete on BF's row doesn't
    take the panel's "every row selected" shortcut.
    """

    def setUp(self):
        if not App.GuiUp:
            self.skipTest("needs the GUI")
        self.doc = App.newDocument("MassPropertiesRemoveItem")
        self.doc.HistoryAlgorithm = "V2"
        a = self.doc.addObject("Part::Box", "A")
        b = self.doc.addObject("Part::Box", "B")
        b.Length, b.Width, b.Height = 2, 12, 10
        b.Placement.Base = App.Vector(4, -1, 5)
        c = self.doc.addObject("Part::Box", "C")
        c.Placement.Base = App.Vector(20, 0, 0)
        self.cut = self.doc.addObject("Part::Cut", "BF")
        self.cut.Base, self.cut.Tool = a, b
        self.doc.recompute()
        a.ViewObject.Visibility = False
        b.ViewObject.Visibility = False
        Gui.Selection.clearSelection()
        self.pump()

        Gui.runCommand("Std_MassProperties")
        self.pump(20)
        mw = Gui.getMainWindow()
        lists = [
            w for w in mw.findChildren(QtWidgets.QListWidget) if w.objectName() == "objectList"
        ]
        self.assertEqual(len(lists), 1, "the Mass Properties panel's object list")
        self.list = lists[0]

    def tearDown(self):
        if not App.GuiUp:
            return
        Gui.Selection.clearSelection()
        Gui.Control.closeDialog()
        self.pump()
        App.closeDocument(self.doc.Name)
        self.pump()

    @staticmethod
    def pump(n=5):
        for _ in range(n):
            QtWidgets.QApplication.processEvents()

    def splitFace(self):
        """An indexed face name of BF whose mapped name contains '|', and that mapped name."""
        faces = sorted(
            (indexed, mapped)
            for mapped, indexed in self.cut.Shape.ElementMap.items()
            if indexed.startswith("Face") and "|" in mapped
        )
        self.assertEqual(
            len(faces), 2, "the top face splits into two pieces with '|' in their names"
        )
        return faces[0]

    def rows(self):
        return [self.list.item(i).data(QtCore.Qt.UserRole) for i in range(self.list.count())]

    def selected(self):
        return sorted(s.ObjectName for s in Gui.Selection.getSelectionEx("", 0))

    def startCustomPick(self):
        mw = Gui.getMainWindow()
        mw.findChildren(QtWidgets.QRadioButton, "customRadioButton")[0].setChecked(True)
        self.pump()
        mw.findChildren(QtWidgets.QPushButton, "selectCustomButton")[0].click()
        self.pump()

    def selectBoth(self, sub):
        Gui.Selection.addSelection(self.doc.Name, "C")
        self.pump(10)
        Gui.Selection.addSelection(self.doc.Name, "BF", sub)
        self.pump(20)

    def focusList(self):
        # The panel acts on Delete only while the list has the focus, which a widget gets only
        # once its window is shown and active; the first time, that can take a few event loops.
        win = self.list.window()
        win.show()
        for _ in range(20):
            win.activateWindow()
            self.list.setFocus(QtCore.Qt.OtherFocusReason)
            self.pump()
            if self.list.hasFocus():
                return
            QtCore.QThread.msleep(20)

    def deleteRow(self, row):
        self.focusList()
        self.list.clearSelection()
        self.list.setCurrentRow(row)
        self.list.item(row).setSelected(True)
        self.pump()
        self.assertTrue(self.list.hasFocus(), "the list needs the focus for Delete to reach it")
        for kind in (QtCore.QEvent.ShortcutOverride, QtCore.QEvent.KeyPress):
            event = QtGui.QKeyEvent(kind, QtCore.Qt.Key_Delete, QtCore.Qt.NoModifier)
            QtWidgets.QApplication.sendEvent(self.list, event)
        self.pump(10)

    def checkDeleteRemovesSplitFace(self, sub):
        indexed, mapped = self.splitFace()
        self.startCustomPick()
        self.selectBoth(sub)
        rows = self.rows()
        doc = self.doc.Name
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual(rows[0], f"{doc}|C|")
        # The selection holds the mapped form, so the row does too, '|' and all.
        self.assertEqual(rows[1], f"{doc}|BF|;{mapped}.{indexed}")
        self.assertEqual(self.selected(), ["BF", "C"])

        self.deleteRow(1)

        self.assertEqual(self.rows(), [f"{doc}|C|"])
        self.assertEqual(self.selected(), ["C"])

    def testDeleteSplitFacePickedByIndexedName(self):
        """A 3D pick gives the indexed name (Face3)."""
        indexed, _ = self.splitFace()
        self.checkDeleteRemovesSplitFace(indexed)

    def testDeleteSplitFacePickedByMappedName(self):
        """A script can give the mapped subname (;<mapped>.Face3)."""
        indexed, mapped = self.splitFace()
        self.checkDeleteRemovesSplitFace(f";{mapped}.{indexed}")

    def testDeleteObjectRow(self):
        """Normal mode stores the object only ("doc|BF|"), with or without '|' in the pick."""
        indexed, _ = self.splitFace()
        self.selectBoth(indexed)
        doc = self.doc.Name
        self.assertEqual(self.rows(), [f"{doc}|C|", f"{doc}|BF|"])

        self.deleteRow(1)

        self.assertEqual(self.rows(), [f"{doc}|C|"])
        self.assertEqual(self.selected(), ["C"])
