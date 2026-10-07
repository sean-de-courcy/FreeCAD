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

"""Repairing a broken Profile through the property editor's link dialog (FreeCAD-CH, ops#125).

A Pad made from two regions of a sketch breaks when the sketch's circles are drawn again
elsewhere. The Pad's task panel has no profile selector, so the regions are picked again in the
link dialog of its Profile property (the "..." button). The dialog listed the stale regions as
the sketch named them, "1" and "2", kept them beside the new picks, and wrote them back as the
sketch's edge1 and edge2: the Pad stayed broken."""

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtWidgets

from PartDesignTests.TestPad import (
    REGIONS,
    REGION_FILLET_VOLUME,
    REGION_PAD_VOLUME,
    bossCentres,
    bossTopEdges,
    makeRegionPad,
    redrawBosses,
)


def pump(seconds=0.5):
    """Processes events for a while: the property view fills on a timer."""
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


class LinkDialog:
    """The property view's link dialog of obj.<prop>, opened as a user does: select the object,
    edit the property's value cell, press its "..." button."""

    def __init__(self, test, obj, prop):
        self.obj = obj
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(obj.Document.Name, obj.Name)
        pump(1.0)
        mainWindow = Gui.getMainWindow()
        cell = None
        for editor in mainWindow.findChildren(QtWidgets.QTreeView):
            if editor.metaObject().className() != "Gui::PropertyEditor::PropertyEditor":
                continue
            # the Data tab's: the View tab can have a "Base" group too (it does after a dress-up
            # panel selected a reference row, ops#143)
            if editor.objectName() != "propertyEditorData":
                continue
            index = self._findRow(editor.model(), QtCore.QModelIndex(), prop)
            if index is not None:
                cell = (editor, index.sibling(index.row(), 1))
                break
        test.assertIsNotNone(cell, "no %s row in the property view" % prop)
        self.editor, self.cell = cell
        self.editor.setCurrentIndex(self.cell)
        self.editor.edit(self.cell)
        pump()
        labels = [
            w
            for w in self.editor.findChildren(QtWidgets.QWidget)
            if w.metaObject().className() == "Gui::PropertyEditor::LinkLabel" and w.isVisible()
        ]
        test.assertTrue(labels, "no link editor for %s" % prop)
        labels[-1].findChildren(QtWidgets.QPushButton)[0].click()
        pump()
        dialogs = [
            w
            for w in QtWidgets.QApplication.topLevelWidgets() + mainWindow.findChildren(QtWidgets.QDialog)
            if w.metaObject().className() == "Gui::Dialog::DlgPropertyLink" and w.isVisible()
        ]
        test.assertTrue(dialogs, "the link dialog didn't open")
        self.dialog = dialogs[0]
        self.tree = [
            t for t in self.dialog.findChildren(QtWidgets.QTreeWidget) if t.objectName() == "treeWidget"
        ][0]

    @staticmethod
    def _findRow(model, parent, name):
        for row in range(model.rowCount(parent)):
            index = model.index(row, 0, parent)
            # A property group can have the property's name (Base): take a leaf.
            if str(model.data(index)) == name and model.rowCount(index) == 0:
                return index
            found = LinkDialog._findRow(model, index, name)
            if found is not None:
                return found
        return None

    def elements(self, objName):
        """The element column of objName's item, as a list."""
        it = QtWidgets.QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            name = item.data(0, QtCore.Qt.UserRole)  # DlgDocumentObject::ObjectNameRole
            if not isinstance(name, str):
                name = bytes(name).decode()
            if name == objName:
                text = item.text(1)
                return text.split(",") if text else []
            it += 1
        return None

    def pick(self, objName, subname):
        """A pick in the 3D view: the object's path below the Body, as a click gives it."""
        Gui.Selection.addSelection(self.obj.Document.Name, "Body", objName + "." + subname)
        pump(0.2)

    def accept(self):
        Gui.Selection.clearSelection()
        pump(0.2)
        self.dialog.accept()
        pump()
        Gui.Selection.clearSelection()
        pump()


class TestProfileLinkDialog(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestProfileLinkDialog")
        self.sketch, self.pad, self.fillet = makeRegionPad(self.doc)
        self.assertTrue(self.pad.isValid(), self.pad.getStatusString())
        redrawBosses(self.sketch)
        self.doc.recompute()
        self.assertFalse(self.pad.isValid())
        pump()

    def tearDown(self):
        # A dialog a failed test left open blocks the property view's selection.
        for widget in QtWidgets.QApplication.topLevelWidgets() + Gui.getMainWindow().findChildren(
            QtWidgets.QDialog
        ):
            if widget.metaObject().className() == "Gui::Dialog::DlgPropertyLink" and widget.isVisible():
                widget.reject()
        Gui.Selection.clearSelection()
        pump(0.2)
        App.closeDocument(self.doc.Name)

    def testPickedRegionsReplaceTheStaleOnes(self):
        dialog = LinkDialog(self, self.pad, "Profile")
        # The stale regions are listed as they are stored, not as names the sketch makes up.
        self.assertEqual(dialog.elements("BossSketch"), ["?InternalFace1", "?InternalFace2"])
        # No Reset: picking the new regions replaces the stale ones.
        for region in REGIONS:
            dialog.pick("BossSketch", region)
        self.assertEqual(dialog.elements("BossSketch"), REGIONS)
        dialog.accept()
        self.assertEqual(self.pad.Profile[1], REGIONS)

        self.doc.recompute()
        self.assertTrue(self.pad.isValid(), self.pad.getStatusString())
        self.assertAlmostEqual(self.pad.Shape.Volume, REGION_PAD_VOLUME, places=4)
        self.assertEqual(bossCentres(self.pad.Shape), [(0.0, -5.0), (0.0, 5.0)])
        # The fillet's edges went with the old bosses: it breaks loudly.
        self.assertFalse(self.fillet.isValid())
        self.assertIn("Edge", self.fillet.getStatusString())

        # The fillet is repaired the same way, by picking the new bosses' top edges.
        dialog = LinkDialog(self, self.fillet, "Base")
        for edge in bossTopEdges(self.pad):
            dialog.pick("Bosses", edge)
        dialog.accept()
        self.doc.recompute()
        self.assertTrue(self.fillet.isValid(), self.fillet.getStatusString())
        self.assertAlmostEqual(self.fillet.Shape.Volume, REGION_FILLET_VOLUME, places=4)

    def testUnchangedDialogKeepsTheProfile(self):
        """OK without a pick leaves the broken Profile as it was: nothing changes silently."""
        before = self.pad.Profile[1]
        dialog = LinkDialog(self, self.pad, "Profile")
        dialog.accept()
        self.assertEqual(self.pad.Profile[1], before)
        self.doc.recompute()
        self.assertFalse(self.pad.isValid())
        self.assertIn("InternalFace", self.pad.getStatusString())
