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

import os
import sys
import unittest
import FreeCAD
import FreeCADGui
import Part
import PartGui
import Sketcher
from PySide import QtWidgets


def findDockWidget(name):
    """Get a dock widget by name"""
    mw = FreeCADGui.getMainWindow()
    dws = mw.findChildren(QtWidgets.QDockWidget)
    for dw in dws:
        if dw.objectName() == name:
            return dw
    return None


"""
#---------------------------------------------------------------------------
# define the test cases to test the FreeCAD Part module
#---------------------------------------------------------------------------
"""
from parttests.ColorPerFaceTest import ColorPerFaceTest
from parttests.ColorTransparencyTest import ColorTransparencyTest
from parttests.TaskFaceAppearancesTest import TaskFaceAppearancesGuiTest


# class PartGuiTestCases(unittest.TestCase):
#    def setUp(self):
#        self.Doc = FreeCAD.newDocument("PartGuiTest")
#
#    def testBoxCase(self):
#        self.Box = self.Doc.addObject('Part::SketchObject','SketchBox')
#        self.Box.addGeometry(Part.LineSegment(App.Vector(-99.230339,36.960674,0),App.Vector(69.432587,36.960674,0)))
#        self.Box.addGeometry(Part.LineSegment(App.Vector(69.432587,36.960674,0),App.Vector(69.432587,-53.196629,0)))
#        self.Box.addGeometry(Part.LineSegment(App.Vector(69.432587,-53.196629,0),App.Vector(-99.230339,-53.196629,0)))
#        self.Box.addGeometry(Part.LineSegment(App.Vector(-99.230339,-53.196629,0),App.Vector(-99.230339,36.960674,0)))
#
#    def tearDown(self):
#        #closing doc
#        FreeCAD.closeDocument("PartGuiTest")
class PartGuiViewProviderTestCases(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartGuiTest")

    def testCanDropObject(self):
        # https://github.com/FreeCAD/FreeCAD/pull/6850
        box = self.Doc.addObject("Part::Box", "Box")
        with self.assertRaises(TypeError):
            box.ViewObject.canDragObject(0)
        with self.assertRaises(TypeError):
            box.ViewObject.canDropObject(0)
        box.ViewObject.canDropObject()
        with self.assertRaises(TypeError):
            box.ViewObject.dropObject(box, 0)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartGuiTest")


class ProjectionOnSurfaceTestCases(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("ProjectionOnSurface")

    def testSketchInternalFaceAsSupportFace(self):
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        sketch.MakeInternals = True
        sketch.addGeometry(
            [
                Part.LineSegment(FreeCAD.Vector(0, 0), FreeCAD.Vector(10, 0)),
                Part.LineSegment(FreeCAD.Vector(10, 0), FreeCAD.Vector(10, 10)),
                Part.LineSegment(FreeCAD.Vector(10, 10), FreeCAD.Vector(0, 10)),
                Part.LineSegment(FreeCAD.Vector(0, 10), FreeCAD.Vector(0, 0)),
            ],
            False,
        )
        self.Doc.recompute()

        FreeCADGui.activateWorkbench("PartWorkbench")
        FreeCADGui.updateGui()
        FreeCADGui.runCommand("Part_ProjectionOnSurface")
        FreeCADGui.updateGui()

        taskDialog = FreeCADGui.Control.activeTaskDialog()
        self.assertIsNotNone(taskDialog)
        supportButton = None
        for widget in taskDialog.getDialogContent():
            supportButton = widget.findChild(QtWidgets.QPushButton, "pushButtonAddProjFace")
            if supportButton:
                break
        self.assertIsNotNone(supportButton)
        supportButton.click()
        FreeCADGui.Selection.addSelection(sketch, "InternalFace1")

        projection = self.Doc.getObject("Projection")
        self.assertIsNotNone(projection)
        self.assertEqual(projection.SupportFace[0], sketch)
        self.assertEqual(projection.SupportFace[1], ["InternalFace1"])

    def _openDialogInAddWireMode(self):
        FreeCADGui.activateWorkbench("PartWorkbench")
        FreeCADGui.updateGui()
        FreeCADGui.runCommand("Part_ProjectionOnSurface")
        FreeCADGui.updateGui()
        taskDialog = FreeCADGui.Control.activeTaskDialog()
        self.assertIsNotNone(taskDialog)
        wireButton = None
        for widget in taskDialog.getDialogContent():
            wireButton = widget.findChild(QtWidgets.QPushButton, "pushButtonAddWire")
            if wireButton:
                break
        self.assertIsNotNone(wireButton)
        wireButton.click()
        projection = self.Doc.getObject("Projection")
        self.assertIsNotNone(projection)
        return projection

    def _statusBarTexts(self):
        statusBar = FreeCADGui.getMainWindow().statusBar()
        return [label.text() for label in statusBar.findChildren(QtWidgets.QLabel)]

    @staticmethod
    def _wiresContaining(shape, edge):
        return [i for i, wire in enumerate(shape.Wires, 1) if any(edge.isSame(e) for e in wire.Edges)]

    def testAddWireRefusesEdgeOnTwoWires(self):
        """An edge shared by two faces' wires names no single wire: nothing is added (ops#250)"""
        box = self.Doc.addObject("Part::Box", "Box")
        self.Doc.recompute()
        # Every edge of a closed box bounds two faces, so it lies on two wires.
        self.assertEqual(len(self._wiresContaining(box.Shape, box.Shape.Edge1)), 2)

        projection = self._openDialogInAddWireMode()
        FreeCADGui.Selection.addSelection(box, "Edge1")
        FreeCADGui.updateGui()

        self.assertEqual(projection.Projection, [])
        self.assertTrue(
            any("Edge1" in text and "2 wires" in text for text in self._statusBarTexts()),
            self._statusBarTexts(),
        )

    def testAddWireRefusesEdgeOutsideAnyWire(self):
        """A lone edge lies on no wire: nothing is added, and the dialog says so (ops#250)"""
        line = self.Doc.addObject("Part::Feature", "Line")
        line.Shape = Part.makeLine(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(10, 0, 0))
        self.Doc.recompute()
        self.assertEqual(len(line.Shape.Wires), 0)

        projection = self._openDialogInAddWireMode()
        FreeCADGui.Selection.addSelection(line, "Edge1")
        FreeCADGui.updateGui()

        self.assertEqual(projection.Projection, [])
        self.assertTrue(
            any("Edge1" in text and "no wire" in text for text in self._statusBarTexts()),
            self._statusBarTexts(),
        )

    def testAddWireAddsTheOnlyWire(self):
        """An edge on exactly one wire adds that wire, the one whose edges contain it (ops#250)"""

        def square(x0):
            points = [
                FreeCAD.Vector(x0, 0, 0),
                FreeCAD.Vector(x0 + 10, 0, 0),
                FreeCAD.Vector(x0 + 10, 10, 0),
                FreeCAD.Vector(x0, 10, 0),
                FreeCAD.Vector(x0, 0, 0),
            ]
            return Part.makePolygon(points)

        wires = self.Doc.addObject("Part::Feature", "Wires")
        wires.Shape = Part.Compound([square(0), square(20)])
        self.Doc.recompute()
        # The picked edge: the one of the square at x = 20..30 that runs along y = 10.
        edgeIndex = next(
            i
            for i, e in enumerate(wires.Shape.Edges, 1)
            if e.BoundBox.XMin > 15 and abs(e.BoundBox.YMin - 10) < 1e-7
        )
        edge = wires.Shape.Edges[edgeIndex - 1]
        self.assertEqual(len(self._wiresContaining(wires.Shape, edge)), 1)

        projection = self._openDialogInAddWireMode()
        FreeCADGui.Selection.addSelection(wires, "Edge{}".format(edgeIndex))
        FreeCADGui.updateGui()

        self.assertEqual(len(projection.Projection), 1)
        obj, subs = projection.Projection[0]
        self.assertEqual(obj, wires)
        self.assertEqual(len(subs), 1)
        added = wires.Shape.getElement(subs[0])
        self.assertEqual(added.ShapeType, "Wire")
        self.assertTrue(any(edge.isSame(e) for e in added.Edges))
        self.assertAlmostEqual(added.BoundBox.XMin, 20.0)
        self.assertAlmostEqual(added.BoundBox.XMax, 30.0)

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        guiDocument = FreeCADGui.getDocument("ProjectionOnSurface")
        if FreeCADGui.Control.activeDialog(guiDocument):
            FreeCADGui.Control.closeDialog(guiDocument)
        FreeCAD.closeDocument("ProjectionOnSurface")


class PartMirrorGuiTestCases(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartMirrorGuiTest")

    def tearDown(self):
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(self.Doc.Name)

    def mirrorBoxWithLabel(self, label):
        if not FreeCAD.GuiUp:
            self.skipTest("This test requires a graphical user interface (GUI).")

        box = self.Doc.addObject("Part::Box", "Box")
        box.Label = label
        self.Doc.recompute()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.Doc.Name, box.Name)
        FreeCADGui.runCommand("Part_Mirror")
        self.assertTrue(FreeCADGui.Control.activeDialog(), "Part Mirror task dialog did not open.")

        FreeCADGui.Control.activeTaskDialog().accept()
        QtWidgets.QApplication.processEvents()

        mirrors = [obj for obj in self.Doc.Objects if obj.isDerivedFrom("Part::Mirroring")]
        self.assertEqual(1, len(mirrors))
        return mirrors[0].Label

    def testMirrorLabelWithUnicodeIsNotDoubleEscaped(self):
        self.assertEqual("caf\u00e9 (Mirror #1)", self.mirrorBoxWithLabel("caf\u00e9"))

    def testMirrorLabelEscapesQuotesBeforePythonCommand(self):
        label = 'a");print("Erasing your hard drive, please stand by....")'
        self.assertEqual(f"{label} (Mirror #1)", self.mirrorBoxWithLabel(label))

    def testMirrorLabelWithNewlinesIsNotMangled(self):
        label = "a\nb\nc"
        self.assertEqual(f"{label} (Mirror #1)", self.mirrorBoxWithLabel(label))


class SectionCutTestCases(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("SectionCut")

    def testOpenDialog(self):
        box = self.Doc.addObject("Part::Box", "SectionCutBoxX")
        comp = self.Doc.addObject("Part::Compound", "SectionCutCompound")
        comp.Links = box
        grp = self.Doc.addObject("App::DocumentObjectGroup", "SectionCutX")
        grp.addObject(comp)
        self.Doc.recompute()

        FreeCADGui.runCommand("Part_SectionCut")
        dw = findDockWidget("Section Cutting")
        if dw:
            box = dw.findChild(QtWidgets.QDialogButtonBox)
            button = box.button(QtWidgets.QDialogButtonBox.Close)
            button.click()
        else:
            print("No section cutting panel found")

    def tearDown(self):
        FreeCAD.closeDocument("SectionCut")
