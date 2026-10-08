# SPDX-License-Identifier: LGPL-2.1-or-later

# **************************************************************************
#   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
#                                                                         *
#   This file is part of the FreeCAD CAx development system.              *
#                                                                         *
#   This program is free software; you can redistribute it and/or modify  *
#   it under the terms of the GNU Lesser General Public License (LGPL)    *
#   as published by the Free Software Foundation; either version 2 of     *
#   the License, or (at your option) any later version.                   *
#   for detail see the LICENCE text file.                                 *
#                                                                         *
#   FreeCAD is distributed in the hope that it will be useful,            *
#   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
#   GNU Library General Public License for more details.                  *
#                                                                         *
#   You should have received a copy of the GNU Library General Public     *
#   License along with FreeCAD; if not, write to the Free Software        *
#   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
#   USA                                                                   *
# **************************************************************************

import FreeCAD
import FreeCADGui
import os
import sys
import unittest
import Sketcher
import Part
import PartDesign
import PartDesignGui
import tempfile

from PySide import QtGui, QtCore
from PySide.QtGui import QApplication

from PartDesignTests.TestMaterial import TestMaterial
from PartDesignTests.TestActiveObject import TestActiveObject
from PartDesignTests.TestSuppressed import TestSuppressedStrikethrough
from PartDesignTests.TestPreviewPython import TestPreviewPython
from PartDesignTests.TestProfileLinkDialog import TestProfileLinkDialog
from PartDesignTests.TestReferencePickerGui import TestReferencePickerGui
from PartDesignTests.TestRollBackBarGui import TestRollBackBarGui
from PartDesignTests.TestParkedMarkingGui import TestParkedMarkingGui
from PartDesignTests.TestSelectionFilterGui import TestSelectionFilterGui
from PartDesignTests.TestExpressionFieldsGui import TestExpressionFieldsGui
from PartDesignTests.TestPanelFixesGui import TestPanelFixesGui
from PartDesignTests.TestStalePreviewGui import TestStalePreviewGui
from PartDesignTests.TestDressUpDeleteKeyGui import TestDressUpDeleteKeyGui
from PartDesignTests.TestReferenceFieldGui import TestReferenceFieldGui
from PartDesignTests.TestTreeItemsGui import TestTreeItemsGui


# timer runs this class in order to access modal dialog
class CallableCheckWorkflow:
    def __init__(self, test):
        self.test = test

    def __call__(self):
        dialog = QApplication.activeModalWidget()
        self.test.assertIsNotNone(dialog, "Dialog box could not be found")
        if dialog is not None:
            dialogcheck = CallableCheckDialogWasClosed(self.test)
            QtCore.QTimer.singleShot(500, dialogcheck)
            QtCore.QTimer.singleShot(0, dialog, QtCore.SLOT("accept()"))


class CallableCheckDialogWasClosed:
    def __init__(self, test):
        self.test = test

    def __call__(self):
        dialog = QApplication.activeModalWidget()
        self.test.assertIsNone(dialog, "Dialog box was not closed by accept()")


class CallableCheckWarning:
    def __init__(self, test):
        self.test = test

    def __call__(self):
        dialog = QApplication.activeModalWidget()
        self.test.assertIsNotNone(dialog, "Input dialog box could not be found")
        if dialog is not None:
            QtCore.QTimer.singleShot(0, dialog, QtCore.SLOT("accept()"))


class CallableComboBox:
    def __init__(self, test):
        self.test = test

    def __call__(self):
        dialog = QApplication.activeModalWidget()
        self.test.assertIsNotNone(dialog, "Warning dialog box could not be found")
        if dialog is not None:
            cbox = dialog.findChild(QtGui.QComboBox)
            self.test.assertIsNotNone(cbox, "ComboBox widget could not be found")
            if cbox is not None:
                QtCore.QTimer.singleShot(0, dialog, QtCore.SLOT("accept()"))


class CallableCheckExemptionDialog:
    def __init__(self, test):
        self.test = test

    def __call__(self):
        dialog = QApplication.activeModalWidget()
        if dialog is not None:
            dialogcheck = CallableCheckExemptionDialogWasClosed(self.test)
            QtCore.QTimer.singleShot(100, dialogcheck)
            QtCore.QTimer.singleShot(0, dialog, QtCore.SLOT("accept()"))


class CallableCheckExemptionDialogWasClosed:
    def __init__(self, test):
        self.test = test

    def __call__(self):
        dialog = QApplication.activeModalWidget()
        self.test.assertIsNone(dialog, "Dialog box was not closed by accept()")


App = FreeCAD
Gui = FreeCADGui


# ---------------------------------------------------------------------------
# define the test cases to test the FreeCAD PartDesign module
# ---------------------------------------------------------------------------
class PartDesignGuiTestCases(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("SketchGuiTest")

    def testRefuseToMoveSingleFeature(self):
        FreeCAD.Console.PrintMessage(
            "Testing refuse to move the feature with dependencies from one body to another\n"
        )
        self.BodySource = self.Doc.addObject("PartDesign::Body", "Body")
        Gui.activateView("Gui::View3DInventor", True)
        Gui.activeView().setActiveObject("pdbody", self.BodySource)

        self.BoxObj = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.BoxObj.Length = 10.0
        self.BoxObj.Width = 10.0
        self.BoxObj.Height = 10.0
        self.BodySource.addObject(self.BoxObj)

        App.ActiveDocument.recompute()

        self.Sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        self.Sketch.AttachmentSupport = (self.BoxObj, ("Face3",))
        self.Sketch.MapMode = "FlatFace"
        self.BodySource.addObject(self.Sketch)

        geoList = []
        geoList.append(Part.LineSegment(App.Vector(2.0, 8.0, 0), App.Vector(8.0, 8.0, 0)))
        geoList.append(Part.LineSegment(App.Vector(8.0, 8.0, 0), App.Vector(8.0, 2.0, 0)))
        geoList.append(Part.LineSegment(App.Vector(8.0, 2.0, 0), App.Vector(2.0, 2.0, 0)))
        geoList.append(Part.LineSegment(App.Vector(2.0, 2.0, 0), App.Vector(2.0, 8.0, 0)))
        self.Sketch.addGeometry(geoList, False)
        conList = []
        conList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        conList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        conList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        conList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        conList.append(Sketcher.Constraint("Horizontal", 0))
        conList.append(Sketcher.Constraint("Horizontal", 2))
        conList.append(Sketcher.Constraint("Vertical", 1))
        conList.append(Sketcher.Constraint("Vertical", 3))
        self.Sketch.addConstraint(conList)

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.Sketch
        self.Pad.Length = 10.000000
        self.Pad.Length2 = 100.000000
        self.Pad.Type = 0
        self.Pad.UpToFace = None
        self.Pad.Reversed = 0
        self.Pad.SideType = "One side"
        self.Pad.Offset = 0.000000

        self.BodySource.addObject(self.Pad)

        self.Doc.recompute()
        Gui.ActiveDocument.ActiveView.sendMessage("ViewFit")

        self.BodyTarget = self.Doc.addObject("PartDesign::Body", "Body")

        Gui.Selection.addSelection(App.ActiveDocument.Pad)
        cobj = CallableCheckWarning(self)
        QtCore.QTimer.singleShot(500, cobj)
        Gui.runCommand("PartDesign_MoveFeature")
        # assert dependencies of the Sketch
        self.assertEqual(len(self.BodySource.Group), 3, "Source body feature count is wrong")
        self.assertEqual(len(self.BodyTarget.Group), 0, "Target body feature count is wrong")

    def testMoveSingleFeature(self):
        FreeCAD.Console.PrintMessage("Testing moving one feature from one body to another\n")
        self.BodySource = self.Doc.addObject("PartDesign::Body", "Body")
        Gui.activateView("Gui::View3DInventor", True)
        Gui.activeView().setActiveObject("pdbody", self.BodySource)

        self.Sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        self.BodySource.addObject(self.Sketch)
        self.Sketch.AttachmentSupport = (self.BodySource.Origin.OriginFeatures[3], [""])
        self.Sketch.MapMode = "FlatFace"

        geoList = []
        geoList.append(
            Part.LineSegment(
                App.Vector(-10.000000, 10.000000, 0), App.Vector(10.000000, 10.000000, 0)
            )
        )
        geoList.append(
            Part.LineSegment(
                App.Vector(10.000000, 10.000000, 0), App.Vector(10.000000, -10.000000, 0)
            )
        )
        geoList.append(
            Part.LineSegment(
                App.Vector(10.000000, -10.000000, 0), App.Vector(-10.000000, -10.000000, 0)
            )
        )
        geoList.append(
            Part.LineSegment(
                App.Vector(-10.000000, -10.000000, 0), App.Vector(-10.000000, 10.000000, 0)
            )
        )
        self.Sketch.addGeometry(geoList, False)
        conList = []
        conList.append(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        conList.append(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        conList.append(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        conList.append(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        conList.append(Sketcher.Constraint("Horizontal", 0))
        conList.append(Sketcher.Constraint("Horizontal", 2))
        conList.append(Sketcher.Constraint("Vertical", 1))
        conList.append(Sketcher.Constraint("Vertical", 3))
        self.Sketch.addConstraint(conList)

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.BodySource.addObject(self.Pad)
        self.Pad.Profile = self.Sketch
        self.Pad.Length = 10.000000
        self.Pad.Length2 = 100.000000
        self.Pad.Type = 0
        self.Pad.UpToFace = None
        self.Pad.Reversed = 0
        self.Pad.SideType = "One side"
        self.Pad.Offset = 0.000000

        self.Doc.recompute()
        Gui.ActiveDocument.ActiveView.sendMessage("ViewFit")

        self.BodyTarget = self.Doc.addObject("PartDesign::Body", "Body")

        Gui.Selection.addSelection(App.ActiveDocument.Pad)
        cobj = CallableComboBox(self)
        QtCore.QTimer.singleShot(500, cobj)
        Gui.runCommand("PartDesign_MoveFeature")
        # assert dependencies of the Sketch
        self.Doc.recompute()

        self.assertFalse(
            self.Sketch.AttachmentSupport[0][0] in self.BodySource.Origin.OriginFeatures
        )
        self.assertTrue(
            self.Sketch.AttachmentSupport[0][0] in self.BodyTarget.Origin.OriginFeatures
        )
        self.assertEqual(len(self.BodySource.Group), 0, "Source body feature count is wrong")
        self.assertEqual(len(self.BodyTarget.Group), 2, "Target body feature count is wrong")

    def tearDown(self):
        FreeCAD.closeDocument("SketchGuiTest")


class PartDesignTransformed(unittest.TestCase):
    def setUp(self):
        self.Doc = App.newDocument("PartDesignTransformed")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.BoxObj = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.BoxObj.Length = 10.0
        self.BoxObj.Width = 10.0
        self.BoxObj.Height = 10.0
        App.ActiveDocument.recompute()
        # not adding box to the body to imitate undertermined workflow
        tempDir = tempfile.gettempdir()
        self.TempDoc = os.path.join(tempDir, "PartDesignTransformed.FCStd")
        if os.path.exists(self.TempDoc):
            os.remove(self.TempDoc)
        App.ActiveDocument.saveAs(self.TempDoc)
        App.closeDocument("PartDesignTransformed")

    def tearDown(self):
        # closing doc
        if App.ActiveDocument is not None and App.ActiveDocument.Name == PartDesignTransformed:
            App.closeDocument("PartDesignTransformed")
        # print ("omit closing document for debugging")

    def testMultiTransformCase(self):
        App.Console.PrintMessage("Testing applying MultiTransform to the Box outside the body\n")
        App.open(self.TempDoc)
        App.setActiveDocument("PartDesignTransformed")
        Gui.Selection.addSelection(App.ActiveDocument.Box)

        workflowcheck = CallableCheckWorkflow(self)
        QtCore.QTimer.singleShot(500, workflowcheck)
        Gui.runCommand("PartDesign_MultiTransform")

        App.closeDocument("PartDesignTransformed")


class CreateSketch(unittest.TestCase):

    def testPDCreateSketch(self):
        App.Console.PrintMessage("Testing the creation of a sketch\n")
        param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        useAttachmentSaved = param.GetBool("NewSketchUseAttachmentDialog", False)
        param.SetBool("NewSketchUseAttachmentDialog", False)
        App.newDocument()
        App.activeDocument().addObject("PartDesign::Body", "Body")
        App.ActiveDocument.getObject("Body").Label = "Body"
        App.ActiveDocument.getObject("Body").AllowCompound = True
        FreeCADGui.activateView("Gui::View3DInventor", True)
        FreeCADGui.activeView().setActiveObject("pdbody", App.activeDocument().Body)
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("Std_OrthographicCamera", 1)
        workflowcheck = CallableCheckExemptionDialog(self)
        QtCore.QTimer.singleShot(100, workflowcheck)
        FreeCADGui.runCommand("PartDesign_CompSketches", 0)
        activeDialog = FreeCADGui.Control.activeDialog()
        self.assertIsNotNone(activeDialog)
        if activeDialog is not None:
            FreeCADGui.Control.closeDialog()
        App.closeDocument(App.ActiveDocument.Name)
        param.SetBool("NewSketchUseAttachmentDialog", useAttachmentSaved)


# class PartDesignGuiTestCases(unittest.TestCase):
#   def setUp(self):
#       self.Doc = FreeCAD.newDocument("SketchGuiTest")
#
#   def testBoxCase(self):
#       self.Box = self.Doc.addObject('PartDesign::SketchObject','SketchBox')
#       self.Box.addGeometry(Part.LineSegment(App.Vector(-99.230339,36.960674,0),App.Vector(69.432587,36.960674,0)))
#       self.Box.addGeometry(Part.LineSegment(App.Vector(69.432587,36.960674,0),App.Vector(69.432587,-53.196629,0)))
#       self.Box.addGeometry(Part.LineSegment(App.Vector(69.432587,-53.196629,0),App.Vector(-99.230339,-53.196629,0)))
#       self.Box.addGeometry(Part.LineSegment(App.Vector(-99.230339,-53.196629,0),App.Vector(-99.230339,36.960674,0)))
#
#   def tearDown(self):
#       #closing doc
#       FreeCAD.closeDocument("SketchGuiTest")


class TestShapeBinder(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestShapeBinder")

    def testDefaultColor(self):
        """
        A shape binder uses a different default color than a Part feature.
        This color must still be set after its creation.
        """
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Doc.recompute()
        binder = self.Doc.addObject("PartDesign::ShapeBinder", "ShapeBinder")
        binder.Support = [(self.Box, "Face1")]

        grp = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        packed_color = grp.GetUnsigned("DefaultDatumColor", 0xFFD70099)
        r, g, b, a = binder.ViewObject.ShapeColor
        color = (
            int(r * 255.0 + 0.5) << 24
            | int(g * 255.0 + 0.5) << 16
            | int(b * 255.0 + 0.5) << 8
            | int(a * 255.0 + 0.5)
        )

        self.assertEqual(packed_color, color)

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)


class TestSubShapeBinder(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestSubShapeBinder")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def testDefaultColor(self):
        """
        A sub-shape binder uses a different default color than a Part feature.
        This color must still be set after its creation.
        """
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        body.addObject(box)

        self.Doc.recompute()
        binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(box, ("Face1"))]

        grp = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        packed_color = grp.GetUnsigned("DefaultDatumColor", 0xFFD70099)
        r, g, b, a = binder.ViewObject.ShapeColor
        color = (
            int(r * 255.0 + 0.5) << 24
            | int(g * 255.0 + 0.5) << 16
            | int(b * 255.0 + 0.5) << 8
            | int(a * 255.0 + 0.5)
        )

        self.assertEqual(packed_color, color)


class TestDatumPlane(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestDatumPlane")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def testDefaultColor(self):
        """
        A datum object uses a different default color than a Part feature.
        This color must still be set after its creation.
        """
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        body.addObject(box)

        self.Doc.recompute()
        datum = body.newObject("PartDesign::Plane", "DatumPlane")
        datum.AttachmentSupport = [(box, "Face6")]
        datum.MapMode = "FlatFace"
        self.Doc.recompute()

        grp = App.ParamGet("User parameter:BaseApp/Preferences/Mod/PartDesign")
        packed_color = grp.GetUnsigned("DefaultDatumColor", 0xFFD70099)
        r, g, b, a = datum.ViewObject.ShapeColor
        color = (
            int(r * 255.0 + 0.5) << 24
            | int(g * 255.0 + 0.5) << 16
            | int(b * 255.0 + 0.5) << 8
            | int(a * 255.0 + 0.5)
        )

        self.assertEqual(packed_color, color)


class TestDressUpPanelAfterInsert(unittest.TestCase):
    """ops#84: a boss inserted between a block and a chamfer on the block's back top edge. The
    chamfer's BaseFeature is the boss. Since ops#127 the insert reroutes Base onto the boss with
    the same edge (TestChamfer); before, Base still named the block and opening the panel moved it.
    Either way the panel shows, highlights and selects on the boss, and OK used to write the
    block's index names onto the boss (another edge, silently). A block without an element map
    keeps Base on the block."""

    BACK_TOP = ((0, 10, 10), (20, 10, 10))

    def setUp(self):
        self.Doc = App.newDocument("PartDesignDressUpPanel")

    def tearDown(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCAD.closeDocument(self.Doc.Name)

    @staticmethod
    def edgeName(shape, a, b):
        a, b = App.Vector(*a), App.Vector(*b)
        for index, edge in enumerate(shape.Edges):
            ends = [vertex.Point for vertex in edge.Vertexes]
            if len(ends) == 2 and (
                (ends[0].isEqual(a, 1e-6) and ends[1].isEqual(b, 1e-6))
                or (ends[0].isEqual(b, 1e-6) and ends[1].isEqual(a, 1e-6))
            ):
                return "Edge" + str(index + 1)
        return None

    def addPad(self, body, name, x0, y0, x1, y1, z, length):
        V = App.Vector
        sketch = self.Doc.addObject("Sketcher::SketchObject", name + "Sketch")
        body.addObject(sketch)
        sketch.Placement = App.Placement(V(0, 0, z), App.Rotation())
        corners = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        sketch.addGeometry(
            [Part.LineSegment(a, b) for a, b in zip(corners, corners[1:] + corners[:1])], False
        )
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = sketch
        pad.Length = length
        self.Doc.recompute()
        return pad

    def build(self, mapless=False):
        """The block (a pad, or an AdditiveBox, which has no element map), the chamfer and the
        inserted boss. Returns (block, boss, chamfer)."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        if mapless:
            block = body.newObject("PartDesign::AdditiveBox", "Block")
            block.Length, block.Width, block.Height = 20, 10, 10
            self.Doc.recompute()
        else:
            block = self.addPad(body, "Block", 0, 0, 20, 10, 0, 10)
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (block, [self.edgeName(block.Shape, *self.BACK_TOP)])
        chamfer.Size = 1
        self.Doc.recompute()
        body.Tip = block
        boss = self.addPad(body, "Boss", 5, 3, 9, 7, 10, 3)
        body.Tip = chamfer
        self.Doc.recompute()
        self.assertEqual(chamfer.BaseFeature, boss)
        if mapless:
            self.assertEqual(chamfer.Base[0], block)
        else:
            # The insert reroutes Base onto the boss, with the same edge (ops#127)
            self.assertEqual(
                chamfer.Base, (boss, [self.edgeName(boss.Shape, *self.BACK_TOP)])
            )
        return block, boss, chamfer

    def expectedVolume(self, boss):
        edge = boss.Shape.getElement(self.edgeName(boss.Shape, *self.BACK_TOP))
        return boss.Shape.makeChamfer(1, [edge]).Volume

    def openPanel(self, chamfer):
        FreeCADGui.ActiveDocument.setEdit(chamfer.Name)
        FreeCADGui.updateGui()
        dialog = FreeCADGui.Control.activeTaskDialog()
        self.assertIsNotNone(dialog)
        return dialog

    def testOkKeepsTheEdge(self):
        block, boss, chamfer = self.build()
        volume = self.expectedVolume(boss)
        self.assertAlmostEqual(chamfer.Shape.Volume, volume, places=6)
        dialog = self.openPanel(chamfer)
        bossEdge = self.edgeName(boss.Shape, *self.BACK_TOP)
        self.assertEqual(chamfer.Base, (boss, [bossEdge]))
        dialog.accept()
        FreeCADGui.updateGui()
        self.assertFalse(FreeCADGui.Control.activeDialog())
        self.Doc.recompute()
        self.assertEqual(chamfer.Base, (boss, [bossEdge]))
        self.assertEqual(chamfer.BaseFeature, boss)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertAlmostEqual(chamfer.Shape.Volume, volume, places=6)

    def testCancelRestoresBase(self):
        block, boss, chamfer = self.build()
        base, volume, undo = chamfer.Base, chamfer.Shape.Volume, self.Doc.UndoCount
        dialog = self.openPanel(chamfer)
        self.assertEqual(chamfer.Base[0], boss)
        dialog.reject()
        FreeCADGui.updateGui()
        self.assertFalse(FreeCADGui.Control.activeDialog())
        self.Doc.recompute()
        self.assertEqual(chamfer.Base, base)
        self.assertEqual(chamfer.BaseFeature, boss)
        self.assertEqual(self.Doc.UndoCount, undo)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertAlmostEqual(chamfer.Shape.Volume, volume, places=6)

    def testUnmappedBaseLeftAlone(self):
        # The block's edge has no mapped name: no guess, Base stays on the block, and OK keeps it
        block, boss, chamfer = self.build(mapless=True)
        base = chamfer.Base
        dialog = self.openPanel(chamfer)
        self.assertEqual(chamfer.Base, base)
        dialog.accept()
        FreeCADGui.updateGui()
        self.assertEqual(chamfer.Base, base)
        self.assertEqual(chamfer.BaseFeature, boss)


class TestDressUpPanelBrokenReference(unittest.TestCase):
    """ops#66, in a document with the reference solver on (ops#7, Task 2 PR 5): a fillet on a
    pad's vertical edge at (20, 0), whose sketch corner is then cut off, so the edge is gone and
    the solver leaves the reference broken. Opening the fillet's task panel used to replace the
    broken reference with a guess (guessNewLink) and recompute; with the solver on it stays
    broken until the user picks another edge."""

    def setUp(self):
        from PartDesignTests.Scenarios import models

        self.models = models
        self.Doc = models.newDocument("PartDesignDressUpBroken")
        self.Doc.HistoryAlgorithm = "V2"
        self.Doc.ReferenceSolver = True

    def tearDown(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCAD.closeDocument(self.Doc.Name)

    def testPanelKeepsTheBrokenReference(self):
        from PartDesignTests.Scenarios.harness import Z, edge

        models = self.models
        body = models.body(self.Doc)
        profile = models.sketch(self.Doc, "Profile", models.rectangle(0, 0, 20, 10), body)
        pad = models.pad(body, profile, 10)
        self.Doc.recompute()
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (pad, edge("line", direction=Z, through=(20, 0, 0)).one(pad.Shape))
        fillet.Radius = 1
        self.Doc.recompute()
        self.assertTrue(fillet.isValid())
        models.setLines(profile, {0: ((0, 0), (19, 0)), 1: ((20, 1), (20, 10))})
        profile.addGeometry(models.polyline([(19, 0), (20, 1)]), False)
        self.Doc.recompute()
        self.assertFalse(fillet.isValid())
        base = fillet.Base
        self.assertTrue(base[1][0].startswith("?Edge"), base)

        FreeCADGui.ActiveDocument.setEdit(fillet.Name)
        FreeCADGui.updateGui()
        dialog = FreeCADGui.Control.activeTaskDialog()
        self.assertIsNotNone(dialog)
        self.assertEqual(fillet.Base, base)
        dialog.reject()
        FreeCADGui.updateGui()
        self.Doc.recompute()
        self.assertEqual(fillet.Base, base)
        self.assertFalse(fillet.isValid())
