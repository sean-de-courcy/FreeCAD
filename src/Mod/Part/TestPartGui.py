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

import math
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
from parttests.ForkReleaseGuiTest import ForkReleaseGuiTest


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
        return [
            i for i, wire in enumerate(shape.Wires, 1) if any(edge.isSame(e) for e in wire.Edges)
        ]

    @staticmethod
    def _reportText():
        """The Report view's text, where the dialog's console warnings go."""
        for edit in FreeCADGui.getMainWindow().findChildren(QtWidgets.QTextEdit):
            if edit.metaObject().className() == "Gui::DockWnd::ReportOutput":
                return edit.toPlainText()
        return ""

    def _selected(self, obj):
        return [
            sub
            for sel in FreeCADGui.Selection.getSelectionEx(self.Doc.Name)
            if sel.Object == obj
            for sub in sel.SubElementNames
        ]

    @staticmethod
    def _square(x0, y0=0):
        points = [
            FreeCAD.Vector(x0, y0, 0),
            FreeCAD.Vector(x0 + 10, y0, 0),
            FreeCAD.Vector(x0 + 10, y0 + 10, 0),
            FreeCAD.Vector(x0, y0 + 10, 0),
            FreeCAD.Vector(x0, y0, 0),
        ]
        return Part.makePolygon(points)

    def testAddWireRefusesEdgeOnTwoWires(self):
        """An edge shared by two faces' wires names no single wire: nothing is added (ops#250)"""
        box = self.Doc.addObject("Part::Box", "Box")
        self.Doc.recompute()
        # Every edge of a closed box bounds two faces, so it lies on two wires.
        self.assertEqual(len(self._wiresContaining(box.Shape, box.Shape.Edge1)), 2)

        projection = self._openDialogInAddWireMode()
        warned = self._reportText().count("2 wires, so the wire to project is ambiguous")
        FreeCADGui.Selection.addSelection(box, "Edge1")
        FreeCADGui.updateGui()

        self.assertEqual(projection.Projection, [])
        # the advice can be followed on a solid (ops#256)
        self.assertTrue(
            any(
                "Edge1" in text and "2 wires" in text and "Add face" in text
                for text in self._statusBarTexts()
            ),
            self._statusBarTexts(),
        )
        # the refused edge doesn't stay selected, as if added (ops#256)
        self.assertEqual(self._selected(box), [])
        # and the warning reaches the Report view (ops#256)
        self.assertEqual(
            self._reportText().count("2 wires, so the wire to project is ambiguous"), warned + 1
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
            any(
                "Edge1" in text and "no wire" in text and "Add edge" in text
                for text in self._statusBarTexts()
            ),
            self._statusBarTexts(),
        )
        self.assertEqual(self._selected(line), [])

    def testAddWireAddsTheOnlyWire(self):
        """An edge on exactly one wire adds that wire, the one whose edges contain it (ops#250)"""
        wires = self.Doc.addObject("Part::Feature", "Wires")
        wires.Shape = Part.Compound([self._square(0), self._square(20)])
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

    def testAddWireRefusalKeepsTheAddedWire(self):
        """A refused pick after a valid one leaves exactly the valid one's wire (ops#256): a
        square wire, then an edge of a box (on two wires)."""
        wire = self.Doc.addObject("Part::Feature", "Wire")
        wire.Shape = self._square(20)
        box = self.Doc.addObject("Part::Box", "Box")
        self.Doc.recompute()

        projection = self._openDialogInAddWireMode()
        FreeCADGui.Selection.addSelection(wire, "Edge1")
        FreeCADGui.updateGui()
        self.assertEqual(projection.Projection, [(wire, ("Wire1",))])
        FreeCADGui.Selection.addSelection(box, "Edge1")
        FreeCADGui.updateGui()
        self.assertEqual(projection.Projection, [(wire, ("Wire1",))])
        self.assertEqual(self._selected(box), [])

    def testAddWireNumbersWiresAsTheShapeDoes(self):
        """The added wire's number names the wire the edge lies on, in a compound of a face, that
        face's outer wire again, and a second wire (ops#256: the numbering from ops#250). The
        face's wire and its copy are one wire."""
        face = Part.Face(self._square(0))
        compound = self.Doc.addObject("Part::Feature", "Compound")
        compound.Shape = Part.Compound([face, face.OuterWire, self._square(20, 20)])
        self.Doc.recompute()
        self.assertEqual(len(compound.Shape.Wires), 2)

        projection = self._openDialogInAddWireMode()
        for x0 in (0, 20):
            edgeIndex = next(
                i
                for i, e in enumerate(compound.Shape.Edges, 1)
                if abs(e.BoundBox.XMin - x0) < 1e-7 and abs(e.BoundBox.XMax - x0 - 10) < 1e-7
            )
            edge = compound.Shape.Edges[edgeIndex - 1]
            FreeCADGui.Selection.addSelection(compound, "Edge{}".format(edgeIndex))
            FreeCADGui.updateGui()
            added = compound.Shape.getElement(projection.Projection[-1][1][-1])
            self.assertEqual(added.ShapeType, "Wire")
            self.assertTrue(any(edge.isSame(e) for e in added.Edges))
            self.assertAlmostEqual(added.BoundBox.XMin, x0)
        self.assertEqual(sum(len(subs) for _, subs in projection.Projection), 2)

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        guiDocument = FreeCADGui.getDocument("ProjectionOnSurface")
        if FreeCADGui.Control.activeDialog(guiDocument):
            FreeCADGui.Control.closeDialog(guiDocument)
        FreeCAD.closeDocument("ProjectionOnSurface")


class FilletEdgesEditTestCases(unittest.TestCase):
    """The Fillet/Chamfer edit dialog ticks the stored edges where the base has them now (ops#249)

    The base is a 10 mm box with a 2 x 2 mm tool box cut through it. The fillet's edge is the
    box's vertical edge at x = y = 10, found by its centre (10, 10, 5).

    New documents start with the reference solver on (ops#7), and these tests rely on that, except
    the guess tests, which turn it on themselves.
    """

    target = FreeCAD.Vector(10, 10, 5)

    def setUp(self):
        self.Doc = FreeCAD.newDocument("FilletEdgesEdit")
        box = self.Doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 10
        self.tool = self.Doc.addObject("Part::Box", "Tool")
        self.tool.Length = self.tool.Width = 2
        self.tool.Height = 20
        self.tool.Placement.Base = FreeCAD.Vector(20, 20, -5)  # away from the box: no cut yet
        self.cut = self.Doc.addObject("Part::Cut", "Cut")
        self.cut.Base = box
        self.cut.Tool = self.tool
        self.Doc.recompute()

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        guiDocument = FreeCADGui.getDocument("FilletEdgesEdit")
        if FreeCADGui.Control.activeDialog(guiDocument):
            FreeCADGui.Control.closeDialog(guiDocument)
        FreeCAD.closeDocument("FilletEdgesEdit")

    def _edgesAt(self, point):
        edges = self.cut.Shape.Edges
        return [i for i, e in enumerate(edges, 1) if (e.CenterOfMass - point).Length < 1e-6]

    def _makeFeature(self, typeName):
        feature = self.Doc.addObject(typeName, typeName.split("::")[1])
        feature.Base = self.cut
        feature.Edges = [(self._edgesAt(self.target)[0], 1.0, 1.0)]
        self.Doc.recompute()
        return feature

    def _openEdit(self, feature):
        FreeCADGui.getDocument(self.Doc.Name).setEdit(feature.Name)
        FreeCADGui.updateGui()
        taskDialog = FreeCADGui.Control.activeTaskDialog()
        self.assertIsNotNone(taskDialog)
        for widget in taskDialog.getDialogContent():
            tree = widget.findChild(QtWidgets.QTreeView, "treeView")
            if tree:
                return taskDialog, widget, tree
        self.fail("no edge list in the edit dialog")

    @staticmethod
    def _tickedEdges(tree):
        from PySide import QtCore

        model = tree.model()
        ticked = []
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            state = index.data(QtCore.Qt.CheckStateRole)
            if int(getattr(state, "value", state) or 0) == 2:  # Qt.Checked
                ticked.append(index.data(QtCore.Qt.UserRole))
        return ticked

    @staticmethod
    def _tick(tree, edge):
        from PySide import QtCore

        model = tree.model()
        for row in range(model.rowCount()):
            index = model.index(row, 0)
            if index.data(QtCore.Qt.UserRole) == edge:
                model.setData(index, QtCore.Qt.Checked, QtCore.Qt.CheckStateRole)
                return
        raise AssertionError("Edge{} isn't listed".format(edge))

    @staticmethod
    def _cornerRounded(shape, x, y, inward):
        """Whether the solid lacks its vertical corner at (x, y), half way up: a point 0.1 mm
        inside both faces of the corner (towards `inward`) is outside a fillet of radius >= 0.5."""
        dx = 0.1 if inward[0] > x else -0.1
        dy = 0.1 if inward[1] > y else -0.1
        return not shape.isInside(FreeCAD.Vector(x + dx, y + dy, 5), 1e-7, True)

    def _moveToolTo(self, x, y):
        self.tool.Placement.Base = FreeCAD.Vector(x, y, -5)
        self.Doc.recompute()

    def testEditTicksRenumberedEdge(self):
        """A cut at the opposite corner renumbers the edges: the dialog ticks the edge at its new
        index, and OK keeps the fillet on it"""
        fillet = self._makeFeature("Part::Fillet")
        before = self._edgesAt(self.target)[0]
        self._moveToolTo(-1, -1)
        now = self._edgesAt(self.target)
        self.assertEqual(len(now), 1)
        self.assertNotEqual(now[0], before)

        taskDialog, widget, tree = self._openEdit(fillet)
        self.assertEqual(self._tickedEdges(tree), now)

        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertEqual([e[0] for e in fillet.Edges], now)
        self.assertEqual(fillet.EdgeLinks[1], ["Edge{}".format(now[0])])

    def _checkRemovedEdgeIsNotTicked(self, typeName):
        feature = self._makeFeature(typeName)
        self._moveToolTo(-1, -1)  # renumber first: the stored index follows the edge
        stored = feature.Edges[0][0]
        self._moveToolTo(9, 9)  # then cut the edge away
        self.assertEqual(self._edgesAt(self.target), [])
        # The stored index now names another edge of the base.
        self.assertLessEqual(stored, len(self.cut.Shape.Edges))

        taskDialog, widget, tree = self._openEdit(feature)
        self.assertEqual(self._tickedEdges(tree), [])
        label = widget.findChild(QtWidgets.QLabel, "labelMissingEdges")
        self.assertIsNotNone(label)
        self.assertFalse(label.isHidden())
        self.assertIn("Edge{}".format(stored), label.text())

    def testEditDoesNotTickRemovedFilletEdge(self):
        """The fillet's edge is cut away: the dialog ticks no edge and says the edge is missing"""
        self._checkRemovedEdgeIsNotTicked("Part::Fillet")

    def testEditDoesNotTickRemovedChamferEdge(self):
        """The same for a chamfer, which shares the dialog"""
        self._checkRemovedEdgeIsNotTicked("Part::Chamfer")

    def testEditOkKeepsGuessedEdge(self):
        """OK on a fillet whose edge the reference solver guessed keeps the guess (ops#258): the
        edges are written as they were, which no longer makes the links anew.

        A 20 x 10 x 10 block extruded from a sketch, the fillet on the vertical edge at
        (20, 0); the sketch's right side drawn again 0.5 mm over, so the edge at (20.5, 0) is
        the guess."""
        self.Doc.ReferenceSolver = True
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")

        def outline(points):
            sketch.deleteAllGeometry()
            for a, b in zip(points, points[1:] + points[:1]):
                sketch.addGeometry(
                    Part.LineSegment(FreeCAD.Vector(*a, 0), FreeCAD.Vector(*b, 0)), False
                )
            n = len(points)
            for k in range(n):
                sketch.addConstraint(Sketcher.Constraint("Coincident", k, 2, (k + 1) % n, 1))

        def verticalAt(shape, point):
            return [
                i for i, e in enumerate(shape.Edges, 1) if (e.CenterOfMass - point).Length < 1e-6
            ]

        def guesses(feature):
            report = FreeCAD.getReferenceReport(feature)
            return [entry for entry in report if entry.get("status") == "guessed"]

        outline([(0, 0), (20, 0), (20, 10), (0, 10)])
        block = self.Doc.addObject("Part::Extrusion", "Block")
        block.Base = sketch
        block.DirMode = "Custom"
        block.Dir = FreeCAD.Vector(0, 0, 1)
        block.LengthFwd = 10
        block.Solid = True
        self.Doc.recompute()
        fillet = self.Doc.addObject("Part::Fillet", "Fillet")
        fillet.Base = block
        fillet.Edges = [(verticalAt(block.Shape, FreeCAD.Vector(20, 0, 5))[0], 1.0, 1.0)]
        self.Doc.recompute()
        outline([(0, 0), (20.5, 0), (20.5, 10), (0, 10)])
        self.Doc.recompute()
        moved = verticalAt(block.Shape, FreeCAD.Vector(20.5, 0, 5))
        self.assertEqual([e[0] for e in fillet.Edges], moved)
        self.assertEqual(len(guesses(fillet)), 1, fillet.getStatusString())

        taskDialog, widget, tree = self._openEdit(fillet)
        self.assertEqual(self._tickedEdges(tree), moved)
        # The guessed row is marked, and the label names it (ops#262).
        from PySide import QtCore

        model = tree.model()
        row = [i for i in range(model.rowCount())
               if model.index(i, 0).data(QtCore.Qt.UserRole) == moved[0]][0]
        self.assertTrue(model.index(row, 0).data(QtCore.Qt.FontRole).italic())
        self.assertIn("guessed", model.index(row, 0).data(QtCore.Qt.ToolTipRole))
        # no other row is marked (PR 242 review, L5)
        for other in range(model.rowCount()):
            if other != row:
                font = model.index(other, 0).data(QtCore.Qt.FontRole)
                self.assertFalse(font is not None and font.italic(), other)
                self.assertFalse(model.index(other, 0).data(QtCore.Qt.ToolTipRole), other)
        label = widget.findChild(QtWidgets.QLabel, "labelMissingEdges")
        self.assertFalse(label.isHidden())
        self.assertIn(
            "Edge{} is not the stored edge but the reference solver's pick".format(moved[0]),
            label.text(),
        )
        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual([e[0] for e in fillet.Edges], moved)
        self.assertEqual(len(guesses(fillet)), 1)

        # OK with another edge ticked too (PR 236 review, M2): the guess stays with its edge.
        other = verticalAt(block.Shape, FreeCAD.Vector(0, 0, 5))
        taskDialog, widget, tree = self._openEdit(fillet)
        self._tick(tree, other[0])
        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(sorted(e[0] for e in fillet.Edges), sorted(moved + other))
        [entry] = guesses(fillet)
        self.assertEqual(fillet.Edges[entry["index"]][0], moved[0])
        # both corners rounded (PR 236 verification)
        self.assertTrue(self._cornerRounded(fillet.Shape, 20.5, 0, (10, 5)))
        self.assertTrue(self._cornerRounded(fillet.Shape, 0, 0, (10, 5)))
        self.assertFalse(self._cornerRounded(fillet.Shape, 20.5, 10, (10, 5)))

    def testEditRepicksMissingEdge(self):
        """The fillet's Base set to a moved copy of the cut: no edge is where the old one was, so
        the link goes missing and the dialog lists it (ops#257). Ticking the copy's edge with the
        same index and OK makes it the fillet's edge (PR 236 review, H1)."""
        fillet = self._makeFeature("Part::Fillet")
        stored = fillet.Edges[0][0]
        copy = self.Doc.addObject("Part::Feature", "Copy")
        copy.Shape = self.cut.Shape
        copy.Placement.Base = FreeCAD.Vector(30, 0, 0)
        self.Doc.recompute()
        fillet.Base = copy
        self.assertTrue(fillet.EdgeLinks[1][0].startswith("?"), fillet.EdgeLinks)
        self.Doc.recompute()
        self.assertFalse(fillet.isValid())

        taskDialog, widget, tree = self._openEdit(fillet)
        self.assertEqual(self._tickedEdges(tree), [])
        self._tick(tree, stored)
        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(fillet.EdgeLinks[1], ["Edge{}".format(stored)])
        # rounded at the copy's corner (40, 10): a point just inside it is outside the solid
        self.assertFalse(fillet.Shape.isInside(FreeCAD.Vector(39.9, 9.9, 5), 1e-7, True))


    def testEditOkOneEdgeGoneOneKept(self):
        """Two edges with different radii; the cut takes one away. The dialog ticks the other
        with its own radius and lists the gone one; OK keeps the other with its radius (ops#262).
        The second edge is the box's vertical edge at (0, 10)."""
        corner = FreeCAD.Vector(0, 10, 5)
        fillet = self._makeFeature("Part::Fillet")
        fillet.Edges = [
            (self._edgesAt(self.target)[0], 1.0, 1.0),
            (self._edgesAt(corner)[0], 0.5, 0.5),
        ]
        self.Doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        gone = fillet.Edges[0][0]
        self._moveToolTo(9, 9)  # cuts the edge at (10, 10) away
        self.assertEqual(self._edgesAt(self.target), [])
        kept = self._edgesAt(corner)

        taskDialog, widget, tree = self._openEdit(fillet)
        self.assertEqual(self._tickedEdges(tree), kept)
        from PySide import QtCore

        model = tree.model()
        row = [i for i in range(model.rowCount())
               if model.index(i, 0).data(QtCore.Qt.UserRole) == kept[0]][0]
        self.assertAlmostEqual(model.index(row, 1).data(QtCore.Qt.EditRole).Value, 0.5)
        label = widget.findChild(QtWidgets.QLabel, "labelMissingEdges")
        self.assertIn("Edge{}".format(gone), label.text())
        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertEqual(
            [(e[0], round(e[1], 6), round(e[2], 6)) for e in fillet.Edges], [(kept[0], 0.5, 0.5)]
        )
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertTrue(self._cornerRounded(fillet.Shape, 0, 10, (5, 5)))

    def testEditListsDuplicateEntries(self):
        """Two stored entries on the same edge: the dialog ticks the edge once, shows the later
        entry's radius, and says that OK keeps it once, listing both entries' radii (ops#262).
        OK keeps one entry with the radius shown (PR 242 review, L4 and L5)."""
        from PySide import QtCore

        fillet = self._makeFeature("Part::Fillet")
        edge = fillet.Edges[0][0]
        fillet.Edges = [(edge, 1.0, 1.0), (edge, 0.5, 0.5)]
        taskDialog, widget, tree = self._openEdit(fillet)
        self.assertEqual(self._tickedEdges(tree), [edge])
        model = tree.model()
        row = [i for i in range(model.rowCount())
               if model.index(i, 0).data(QtCore.Qt.UserRole) == edge][0]
        self.assertAlmostEqual(model.index(row, 1).data(QtCore.Qt.EditRole).Value, 0.5)
        label = widget.findChild(QtWidgets.QLabel, "labelMissingEdges")
        self.assertFalse(label.isHidden())
        self.assertIn("Edge{} is stored more than once, with radii 1, 0.5".format(edge), label.text())
        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertEqual(
            [(e[0], round(e[1], 6), round(e[2], 6)) for e in fillet.Edges], [(edge, 0.5, 0.5)]
        )
        self.Doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertTrue(self._cornerRounded(fillet.Shape, 10, 10, (5, 5)))

    def testEditLinksOnOtherObjectRefusesOk(self):
        """The fillet's edge links on another object than its Base: the box is locked with no
        shape, the label says where the links are, and OK changes nothing (PR 242 review, L1)."""
        fillet = self._makeFeature("Part::Fillet")
        fillet.EdgeLinks = (self.tool, ["Edge1"])
        self.assertEqual(fillet.Base, self.cut)
        self.assertEqual(fillet.EdgeLinks[0], self.tool)
        edges = fillet.Edges

        taskDialog, widget, tree = self._openEdit(fillet)
        box = widget.findChild(QtWidgets.QComboBox, "shapeObject")
        self.assertFalse(box.isEnabled())
        self.assertEqual(box.currentIndex(), 0)
        self.assertEqual(tree.model().rowCount(), 0)
        label = widget.findChild(QtWidgets.QLabel, "labelMissingEdges")
        self.assertFalse(label.isHidden())
        self.assertIn("its edge links are on Tool, not on its base Cut", label.text())
        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertEqual(fillet.Edges, edges)
        self.assertEqual(fillet.EdgeLinks[0], self.tool)

    def testEditUnlistedBaseRefusesOk(self):
        """The fillet's Base is an App::Link, which the shape box doesn't list: the box is locked
        with no shape, and OK changes nothing (ops#262). It used to stay open, so OK could write
        another shape's edge numbers against the link."""
        fillet = self._makeFeature("Part::Fillet")
        link = self.Doc.addObject("App::Link", "Link")
        link.LinkedObject = self.cut
        fillet.Base = link
        self.Doc.recompute()
        edges = fillet.Edges
        FreeCADGui.Selection.addSelection(self.tool)  # a shape the box would otherwise pick

        taskDialog, widget, tree = self._openEdit(fillet)
        box = widget.findChild(QtWidgets.QComboBox, "shapeObject")
        self.assertFalse(box.isEnabled())
        self.assertEqual(box.currentIndex(), 0)
        self.assertEqual(tree.model().rowCount(), 0)
        label = widget.findChild(QtWidgets.QLabel, "labelMissingEdges")
        self.assertFalse(label.isHidden())
        self.assertIn("can't be edited here", label.text())
        taskDialog.accept()
        FreeCADGui.updateGui()
        self.assertEqual(fillet.Edges, edges)
        self.assertEqual(fillet.Base, link)


class FilletReplaceBaseTestCases(unittest.TestCase):
    """A Part Fillet/Chamfer's Base replaced as a tree drag does it (ViewObject.replaceObject):
    each edge goes to the new base's edge at the same place, or its link goes missing and the
    recompute fails (ops#265). The replace pastes Base, whose change follows the edges, and then
    the edge links copied before it, which put the old base's edge numbers on the new base.

    Three 10 mm cubes: A at the origin, B in the same place turned 90 degrees about its z axis
    (its edge numbers sit at other corners), C 20 mm over in x. The feature is on A's vertical
    edge at (10, 0)."""

    corners = [(0, 0), (10, 0), (10, 10), (0, 10)]

    def setUp(self):
        self.Doc = FreeCAD.newDocument("FilletReplaceBase")
        self.Doc.UndoMode = 1

    def tearDown(self):
        FreeCAD.closeDocument("FilletReplaceBase")

    @staticmethod
    def _verticalEdgeAt(shape, x, y):
        for i, edge in enumerate(shape.Edges, 1):
            box = edge.BoundBox
            if box.XLength < 1e-6 and box.YLength < 1e-6 and box.ZLength > 9:
                if abs(box.XMin - x) < 1e-6 and abs(box.YMin - y) < 1e-6:
                    return i
        return None

    def _cutCorners(self, shape):
        """The cube's corners a fillet or chamfer of radius 1 took off, half way up."""
        cut = []
        for x, y in self.corners:
            inward = FreeCAD.Vector(0.1 if x < 5 else -0.1, 0.1 if y < 5 else -0.1, 0)
            if not shape.isInside(FreeCAD.Vector(x, y, 5) + inward, 1e-7, True):
                cut.append((x, y))
        return cut

    def testReplaceFollowsEdges(self):
        for feature in ("Fillet", "Chamfer"):
            with self.subTest(feature=feature):
                cubes = {}
                for name in ("A", "B", "C"):
                    cube = self.Doc.addObject("Part::Box", name + feature)
                    cube.Length = cube.Width = cube.Height = 10
                    cubes[name] = cube
                cubes["B"].Placement = FreeCAD.Placement(
                    FreeCAD.Vector(10, 0, 0), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)
                )
                cubes["C"].Placement.Base = FreeCAD.Vector(20, 0, 0)
                self.Doc.recompute()
                onA = self._verticalEdgeAt(cubes["A"].Shape, 10, 0)
                onB = self._verticalEdgeAt(cubes["B"].Shape, 10, 0)
                self.assertNotEqual(onA, onB)  # the designed model
                rounded = self.Doc.addObject("Part::" + feature, feature)
                rounded.Base = cubes["A"]
                rounded.Edges = [(onA, 1.0, 1.0)]
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())

                # B has the edge at the same place: the feature follows it there.
                self.Doc.openTransaction("Replace")
                self.assertEqual(rounded.ViewObject.replaceObject(cubes["A"], cubes["B"]), 1)
                self.Doc.commitTransaction()
                self.assertEqual(rounded.Base, cubes["B"])
                self.assertEqual(rounded.EdgeLinks[1], ["Edge{}".format(onB)])
                self.assertEqual([e[0] for e in rounded.Edges], [onB])
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual(self._cutCorners(rounded.Shape), [(10, 0)])

                # Undone, the feature is on A's edge again; redone, on B's.
                self.Doc.undo()
                self.assertEqual(rounded.Base, cubes["A"])
                self.assertEqual(rounded.EdgeLinks[1], ["Edge{}".format(onA)])
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual(self._cutCorners(rounded.Shape), [(10, 0)])
                self.Doc.redo()
                self.assertEqual(rounded.Base, cubes["B"])
                self.assertEqual(rounded.EdgeLinks[1], ["Edge{}".format(onB)])
                self.Doc.recompute()
                self.assertEqual(self._cutCorners(rounded.Shape), [(10, 0)])

                # C has no edge there: the link goes missing, and the recompute fails.
                rounded.ViewObject.replaceObject(cubes["B"], cubes["C"])
                self.assertEqual(rounded.Base, cubes["C"])
                [link] = rounded.EdgeLinks[1]
                self.assertTrue(link.startswith("?"), link)
                self.Doc.recompute()
                self.assertFalse(rounded.isValid())
                self.assertIn("Missing edge", rounded.getStatusString())

    def testReplaceSwapFollowsEdges(self):
        """ops#268: the swap on a real feature. The feature is on B's edge at (10, 0), and the
        replace is A -> B: its Base swaps to A, and its edge goes to A's edge at the same place
        (Base's change moved EdgeLinks to A; their swap copy, still on B's numbers, isn't
        pasted over it)."""
        for feature in ("Fillet", "Chamfer"):
            with self.subTest(feature=feature):
                cubes = {}
                for name in ("A", "B"):
                    cube = self.Doc.addObject("Part::Box", name + feature)
                    cube.Length = cube.Width = cube.Height = 10
                    cubes[name] = cube
                cubes["B"].Placement = FreeCAD.Placement(
                    FreeCAD.Vector(10, 0, 0), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 90)
                )
                self.Doc.recompute()
                onA = self._verticalEdgeAt(cubes["A"].Shape, 10, 0)
                onB = self._verticalEdgeAt(cubes["B"].Shape, 10, 0)
                self.assertNotEqual(onA, onB)  # the designed model
                rounded = self.Doc.addObject("Part::" + feature, feature)
                rounded.Base = cubes["B"]
                rounded.Edges = [(onB, 1.0, 1.0)]
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual(rounded.ViewObject.replaceObject(cubes["A"], cubes["B"]), 1)
                self.assertEqual(rounded.Base, cubes["A"])
                self.assertEqual(rounded.EdgeLinks[1], ["Edge{}".format(onA)])
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual(self._cutCorners(rounded.Shape), [(10, 0)])

    def testReplaceKeepsGuess(self):
        """A guessed edge stays a guess through the replace (PR 240 review, M3): the replace no
        longer pastes the edge links over what Base's change made of them, records included.

        A 20 x 10 x 10 block from a sketch, the feature on the vertical edge at (20, 0); the
        sketch's right side redrawn 0.5 mm over makes the edge at (20.5, 0) a guess. The block is
        replaced by a copy of its shape turned 180 degrees about its centre."""
        if "BUILD_SKETCHER" not in FreeCAD.__cmake__:
            self.skipTest("needs Sketcher")
        import Sketcher

        def outline(sketch, points):
            sketch.deleteAllGeometry()
            for a, b in zip(points, points[1:] + points[:1]):
                sketch.addGeometry(
                    Part.LineSegment(FreeCAD.Vector(*a, 0), FreeCAD.Vector(*b, 0)), False
                )
            n = len(points)
            for k in range(n):
                sketch.addConstraint(Sketcher.Constraint("Coincident", k, 2, (k + 1) % n, 1))

        def guesses(feature):
            report = FreeCAD.getReferenceReport(feature)
            return [entry for entry in report if entry.get("status") == "guessed"]

        self.Doc.ReferenceSolver = True
        for feature in ("Fillet", "Chamfer"):
            with self.subTest(feature=feature):
                sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch" + feature)
                outline(sketch, [(0, 0), (20, 0), (20, 10), (0, 10)])
                block = self.Doc.addObject("Part::Extrusion", "Block" + feature)
                block.Base = sketch
                block.DirMode = "Custom"
                block.Dir = FreeCAD.Vector(0, 0, 1)
                block.LengthFwd = 10
                block.Solid = True
                self.Doc.recompute()
                rounded = self.Doc.addObject("Part::" + feature, feature)
                rounded.Base = block
                rounded.Edges = [(self._verticalEdgeAt(block.Shape, 20, 0), 1.0, 1.0)]
                self.Doc.recompute()
                outline(sketch, [(0, 0), (20.5, 0), (20.5, 10), (0, 10)])
                self.Doc.recompute()
                self.assertEqual(len(guesses(rounded)), 1, rounded.getStatusString())

                turned = self.Doc.addObject("Part::Feature", "Turned" + feature)
                turned.Shape = block.Shape.copy()
                turned.Placement = FreeCAD.Placement(
                    FreeCAD.Vector(20.5, 10, 0), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 180)
                )
                self.Doc.recompute()
                onTurned = self._verticalEdgeAt(turned.Shape, 20.5, 0)
                self.assertNotEqual(onTurned, rounded.Edges[0][0])  # the designed model
                self.assertEqual(rounded.ViewObject.replaceObject(block, turned), 1)
                self.assertEqual(rounded.Base, turned)
                self.assertEqual(rounded.EdgeLinks[1], ["Edge{}".format(onTurned)])
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual(len(guesses(rounded)), 1)
                # rounded at (20.5, 0), not at the turned copy's other corners
                inside = [
                    rounded.Shape.isInside(FreeCAD.Vector(*p, 5), 1e-7, True)
                    for p in ((20.4, 0.1), (0.1, 0.1), (20.4, 9.9), (0.1, 9.9))
                ]
                self.assertEqual(inside, [False, True, True, True])


class _ReplaceOwner:
    """A Python feature whose Base change also changes its Dep link, as set by `then`."""

    def __init__(self, obj):
        obj.Proxy = self
        obj.addProperty("App::PropertyLink", "Base")
        obj.addProperty("App::PropertyLinkSub", "Dep")
        obj.addProperty("App::PropertyLinkList", "Deps")
        obj.addProperty("App::PropertyLinkSubList", "DepSubs")
        self.then = None

    def onChanged(self, obj, prop):
        if prop == "Base" and getattr(self, "then", None):
            self.then(obj)

    def execute(self, obj):
        pass


class ReplaceObjectOwnerChangeTestCases(unittest.TestCase):
    """ViewObject.replaceObject when pasting one copy changes another of the owner's links
    (PR 240 round 2, ops#265). Base is pasted before Dep (property order). A Dep that Base's
    change moved to the object its copy links, off the object the copy replaces, keeps that
    change; a Dep that it cleared or set to something else gets its copy, as before.

    Three boxes A, B, C; the owner's Base is A."""

    def setUp(self):
        self.Doc = FreeCAD.newDocument("ReplaceObjectOwnerChange")
        self.boxes = {}
        for name in ("A", "B", "C"):
            self.boxes[name] = self.Doc.addObject("Part::Box", name)
        self.Doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument("ReplaceObjectOwnerChange")

    def _owner(self, dep, then):
        A = self.boxes["A"]
        owner = self.Doc.addObject("App::FeaturePython", "Owner")
        proxy = _ReplaceOwner(owner)
        owner.Base = A
        owner.Dep = dep
        proxy.then = then
        return owner

    def _replace(self, owner):
        self.assertEqual(owner.ViewObject.replaceObject(self.boxes["A"], self.boxes["B"]), 1)
        self.assertEqual(owner.Base, self.boxes["B"])

    def testClearedLinkGetsItsCopy(self):
        """The Sonnet review's finding 1: before round 2 the cleared Dep stayed empty."""

        def clear(obj):
            obj.Dep = None

        owner = self._owner((self.boxes["A"], ["Edge2"]), clear)
        self._replace(owner)
        self.assertEqual(owner.Dep, (self.boxes["B"], ["Edge2"]))

    def testLinkSetElsewhereGetsItsCopy(self):
        def toC(obj):
            obj.Dep = (self.boxes["C"], ["Edge3"])

        owner = self._owner((self.boxes["A"], ["Edge2"]), toC)
        self._replace(owner)
        self.assertEqual(owner.Dep, (self.boxes["B"], ["Edge2"]))

    def testFollowedLinkKeepsItsChange(self):
        def follow(obj):
            obj.Dep = (obj.Base, ["Edge5"])

        owner = self._owner((self.boxes["A"], ["Edge2"]), follow)
        self._replace(owner)
        self.assertEqual(owner.Dep, (self.boxes["B"], ["Edge5"]))

    def testSwapCompletes(self):
        """Dep on B, the replace's new object: its copy swaps it to A. A Base change that sets
        Dep elsewhere doesn't stop the swap (the round 1 verification's swap Low)."""

        def toC(obj):
            obj.Dep = (self.boxes["C"], ["Edge3"])

        owner = self._owner((self.boxes["B"], ["Edge2"]), toC)
        self._replace(owner)
        self.assertEqual(owner.Dep, (self.boxes["A"], ["Edge2"]))

    def testSwapFollowedKeepsItsChange(self):
        def toA(obj):
            obj.Dep = (self.boxes["A"], ["Edge5"])

        owner = self._owner((self.boxes["B"], ["Edge2"]), toA)
        self._replace(owner)
        self.assertEqual(owner.Dep, (self.boxes["A"], ["Edge5"]))

    def testListRewriteKeepsItsOtherLinks(self):
        """The PR 247 review's L1: Base's change rewrote a list [A, C] to [B]. That isn't the
        copy [B, C], so the copy is pasted and C kept; before, the list was taken as followed and
        C silently lost."""
        A, B, C = self.boxes["A"], self.boxes["B"], self.boxes["C"]

        def rewrite(obj):
            obj.Deps = [B]

        owner = self._owner(None, rewrite)
        owner.Deps = [A, C]
        self._replace(owner)
        self.assertEqual(owner.Deps, [B, C])

    def testSubListFollowedWithAnEntryDroppedKeepsItsChange(self):
        """The PR 248 review's L1: a sub list names its object once per sub. Base's change moved
        [A.Edge1, A.Edge2] to [B.Edge5]: the same object as the copy [B.Edge1, B.Edge2], so the
        change stands and the stale copy isn't pasted."""
        A, B = self.boxes["A"], self.boxes["B"]

        def follow(obj):
            obj.DepSubs = [(obj.Base, ["Edge5"])]

        owner = self._owner(None, follow)
        owner.DepSubs = [(A, ["Edge1", "Edge2"])]
        self._replace(owner)
        self.assertEqual(owner.DepSubs, [(B, ("Edge5",))])

    def testListLinkingBothSwaps(self):
        """ops#268: a list property that links both the old and the new object (a compound of A
        and B), replace A -> B: its copy swaps them, and nothing changed the list before its
        paste, so the copy is pasted."""
        A, B = self.boxes["A"], self.boxes["B"]
        compound = self.Doc.addObject("Part::Compound", "Compound")
        compound.Links = [A, B]
        self.Doc.recompute()
        self.assertEqual(compound.ViewObject.replaceObject(A, B), 1)
        self.assertEqual(compound.Links, [B, A])


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


class PartGuiPickEdgeTestCases(unittest.TestCase):
    """A 3D pick names the edge under the cursor when an earlier edge has no polygon on its
    face's mesh (ops#389). The line set left such edges out, and a pick read its line index plus
    one as the edge: every later edge got the name of one before it."""

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartGuiPickEdge")

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def _pickedEdges(self, vp, point, direction):
        """The element names of the lines a ray pick finds at <point> looking along <direction>,
        in an orthographic view 40 high of 400 x 400 pixels, within 3 pixels."""
        from pivy import coin

        root = coin.SoSeparator()
        root.ref()
        camera = coin.SoOrthographicCamera()
        camera.height = 40
        camera.position = coin.SbVec3f(*(point - direction * 50))
        up = coin.SbVec3f(0, 0, 1) if abs(direction.z) < 0.9 else coin.SbVec3f(0, 1, 0)
        camera.pointAt(coin.SbVec3f(*point), up)
        camera.nearDistance = 1
        camera.farDistance = 200
        root.addChild(camera)
        root.addChild(vp.RootNode)
        pick = coin.SoRayPickAction(coin.SbViewportRegion(400, 400))
        pick.setPoint(coin.SbVec2s(200, 200))
        pick.setRadius(3)
        pick.setPickAll(True)
        pick.apply(root)
        names = set()
        for picked in pick.getPickedPointList():
            detail = picked.getDetail()
            if detail and detail.getTypeId() == coin.SoLineDetail.getClassTypeId():
                names.add(vp.getElementPicked(picked))
        root.unref()
        return names

    def testPickAfterAnEdgeWithoutPolygon(self):
        # A quarter cylinder face whose edges have no curves on its surface: the mesher can't
        # triangulate it, and the view meshes its surface's bounds instead, without its edges
        # (as some imported faces). Then a box, whose edges 5 to 16 come after the face's.
        V = FreeCAD.Vector
        arcs = [
            Part.ArcOfCircle(Part.Circle(V(0, 0, z), V(0, 0, 1), 5), 0, math.pi / 2).toShape()
            for z in (0, 4)
        ]
        sides = [Part.makeLine(V(0, 5, 0), V(0, 5, 4)), Part.makeLine(V(5, 0, 4), V(5, 0, 0))]
        wire = Part.Wire(Part.__sortEdges__([arcs[0], sides[0], arcs[1], sides[1]]))
        shape = Part.makeCompound(
            [Part.Face(Part.Cylinder(), wire), Part.makeBox(4, 4, 4, V(10, 0, 0))]
        )
        feature = self.Doc.addObject("Part::Feature", "Shape")
        feature.Shape = shape
        self.Doc.recompute()
        FreeCADGui.updateGui()

        wrong = []
        for i, edge in enumerate(shape.Edges[4:], 5):
            middle = edge.valueAt(0.5 * (edge.FirstParameter + edge.LastParameter))
            direction = edge.tangentAt(0.5 * (edge.FirstParameter + edge.LastParameter))
            direction = direction.cross(V(0.3, 0.5, 0.8))
            direction.normalize()
            names = self._pickedEdges(feature.ViewObject, middle, direction)
            if names != {"Edge" + str(i)}:
                wrong.append(("Edge" + str(i), sorted(names)))
        self.assertEqual(wrong, [])
