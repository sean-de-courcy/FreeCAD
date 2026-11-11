# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (slice 9): the part mirror's command and dialog
#
# In a listed studio, Mirror with no Body active (or a part picked, whole or by a face) makes a
# part mirror (Onshape's Mirror, Part type): a studio feature with the picked part as the part to
# mirror and a New result. Its dialog: the Result box (New / Add / Remove / Intersect and the merge
# scope's ticks, as an Extrude owner's), the part to mirror (a tick per live part; a face click
# picks its part) and the mirror plane (armed once the part is set). Edit again keeps every field;
# Cancel leaves nothing. With a Body active and nothing picked, Mirror stays today's feature mirror.
#
# Designed geometry only: Src, a block x 0..10, y 0..20, z 0..5; P, a block x -20..-2 (1800).
# Src mirrored about its YZ plane is x -10..0: Remove leaves P x -20..-10 (1000).

import unittest

import FreeCAD as App
import FreeCADGui as Gui
import PartDesign
from PySide import QtCore, QtWidgets

from PartDesignTests.TestDressUpDeleteKeyGui import pump, taskButton, waitFor
from PartDesignTests.TestReferenceFieldGui import settle
from PartDesignTests.TestStudio import faceAt
from PartDesignTests.TestStudioPartMirror import boxPart, originPlane


def flushDeletes():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def visible(kind, name):
    flushDeletes()
    for widget in Gui.getMainWindow().findChildren(kind, name):
        if widget.isVisible():
            return widget
    return None


def item(listWidget, text):
    for i in range(listWidget.count()):
        if listWidget.item(i).text() == text:
            return listWidget.item(i)
    return None


class TestStudioPartMirrorGui(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("StudioPartMirrorGui")
        self.doc.UndoMode = 1
        self.S = self.doc.addObject("App::Part", "S")
        self.src = boxPart(self.doc, self.S, "Src", 0, 0, 10, 20, 0, 5)
        self.P = boxPart(self.doc, self.S, "P", -20, 0, -2, 20, 0, 5)
        self.doc.recompute()
        self.list = PartDesign.studioList(self.S, True)
        self.doc.recompute()
        Gui.Selection.clearSelection()
        Gui.activateWorkbench("PartDesignWorkbench")
        App.setActiveDocument(self.doc.Name)
        Gui.setActiveDocument(self.doc.Name)
        pump(0.2)
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", None)
        view.setActiveObject("part", self.S)

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
        flushDeletes()
        App.closeDocument(self.doc.Name)

    # ------------------------------------------------------------------------------ helpers
    def mirrors(self):
        return [o for o in self.doc.Objects if o.TypeId == "PartDesign::Mirrored"]

    def made(self, owner):
        return [
            b for b in self.doc.Objects
            if b.TypeId == "PartDesign::Body" and b.StudioMadeBy == owner
        ]

    def accept(self):
        ok = taskButton(QtWidgets.QDialogButtonBox.Ok)
        self.assertIsNotNone(ok, "no OK button")
        ok.click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "the dialog stays open")
        self.doc.recompute()

    def cancel(self):
        taskButton(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        self.doc.recompute()

    def runMirror(self, *selection):
        Gui.Selection.clearSelection()
        for obj, sub in selection:
            Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        Gui.runCommand("PartDesign_Mirrored")
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()), "no task dialog")
        settle()

    def pick(self, obj, sub=""):
        Gui.Selection.addSelection(self.doc.Name, obj.Name, sub)
        pump(0.4)

    def mirrorRemoveFromP(self):
        """Mirror with Src's top face picked; the plane picked (Src's YZ plane); Result Remove,
        P ticked; OK. Returns the owner."""
        pad = self.doc.getObject("SrcPad")
        self.runMirror((pad, faceAt(pad, 5)))
        [owner] = self.mirrors()
        self.assertFalse(
            [b.Name for b in self.doc.Objects
             if b.TypeId == "PartDesign::Body" and b.hasObject(owner)],
            "the part mirror is in no Body",
        )
        self.assertEqual(owner.PatternType, "Part")
        self.assertEqual(list(owner.StudioEntities), ["Src"])
        self.assertEqual(owner.Operation, "Union")
        self.assertEqual(len(self.made(owner)), 1, "New makes a part")
        self.assertIn(owner, self.list.Entries)
        planeButton = visible(QtWidgets.QPushButton, "studioMirrorPlaneButton")
        self.assertIsNotNone(planeButton, "no plane field")
        self.assertTrue(planeButton.isChecked(), "the plane is armed once the part is set")
        yz = originPlane(self.src, "YZ_Plane")
        self.pick(yz)
        self.assertTrue(waitFor(lambda: owner.MirrorPlane and owner.MirrorPlane[0] == yz))
        combo = visible(QtWidgets.QComboBox, "resultCombo")
        self.assertIsNotNone(combo, "no Result box")
        combo.setCurrentIndex(2)  # Remove
        pump(0.3)
        self.assertEqual(owner.Operation, "Subtraction")
        self.assertFalse(self.made(owner), "leaving New deletes its part")
        ticks = visible(QtWidgets.QListWidget, "studioScopeList")
        p = item(ticks, "P")
        self.assertIsNotNone(p, [ticks.item(i).text() for i in range(ticks.count())])
        p.setCheckState(QtCore.Qt.Checked)
        pump(0.3)
        self.assertEqual(list(owner.StudioScope), ["P"])
        self.accept()
        return owner

    # ------------------------------------------------------------------------------ tests
    def testCommandMakesAPartMirror(self):
        """The face pick gives the part; the plane, Remove and P set in the dialog: P loses the
        mirrored copy (1800 -> 1000), Src stays a live part, unchanged."""
        owner = self.mirrorRemoveFromP()
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertAlmostEqual(self.P.Shape.Volume, 1000, places=3)
        self.assertAlmostEqual(self.src.Shape.Volume, 1000, places=3)
        self.assertIn(self.src, PartDesign.studioLiveParts(self.list))

    def testEditAgainKeepsEveryField(self):
        owner = self.mirrorRemoveFromP()
        Gui.getDocument(self.doc.Name).setEdit(owner.Name)
        self.assertTrue(waitFor(lambda: Gui.Control.activeDialog()))
        settle()
        sources = visible(QtWidgets.QListWidget, "studioMirrorSourceList")
        self.assertIsNotNone(sources, "no part field")
        self.assertEqual(item(sources, "Src").checkState(), QtCore.Qt.Checked)
        self.assertEqual(item(sources, "P").checkState(), QtCore.Qt.Unchecked)
        planeButton = visible(QtWidgets.QPushButton, "studioMirrorPlaneButton")
        self.assertIn(originPlane(self.src, "YZ_Plane").Label, planeButton.text())
        self.assertFalse(planeButton.isChecked())
        self.assertEqual(visible(QtWidgets.QComboBox, "resultCombo").currentIndex(), 2)
        ticks = visible(QtWidgets.QListWidget, "studioScopeList")
        self.assertEqual(item(ticks, "P").checkState(), QtCore.Qt.Checked)
        self.cancel()
        self.assertAlmostEqual(self.P.Shape.Volume, 1000, places=3)
        self.assertEqual(owner.Operation, "Subtraction")

    def testCancelLeavesNothing(self):
        pad = self.doc.getObject("SrcPad")
        self.runMirror((pad, faceAt(pad, 5)))
        self.assertEqual(len(self.mirrors()), 1)
        self.cancel()
        self.assertEqual(self.mirrors(), [])
        self.assertEqual(
            sorted(b.Name for b in self.doc.Objects if b.TypeId == "PartDesign::Body"), ["P", "Src"]
        )

    def testABodyActiveKeepsTheFeatureMirror(self):
        """A Body active and nothing picked: today's mirror, in the Body."""
        Gui.getDocument(self.doc.Name).ActiveView.setActiveObject("pdbody", self.src)
        self.runMirror()
        [mirror] = self.mirrors()
        self.assertTrue(self.src.hasObject(mirror))
        self.assertEqual(mirror.PatternType, "Feature")
        self.assertIsNone(visible(QtWidgets.QPushButton, "studioMirrorPlaneButton"))


if __name__ == "__main__":
    unittest.main()
