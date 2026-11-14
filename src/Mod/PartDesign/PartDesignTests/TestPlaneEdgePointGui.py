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


"""The Plane dialog takes an edge's midpoint (FreeCAD-CH ops#673, selection parity 11): Onshape's
Plane takes the point the midpoint marker shows, in the dialog or preselected, and the entry
reads "Edge point" (SP10-Q10). In the fork, an edge picked within the marker's 8 px of its middle
as the only reference of "Normal to edge" stores MapPathParameter 0.5 (TestPlaneEdgePoint pins
where that puts the plane); a pick away from the middle keeps 0, the edge's start, as before.

Designed geometry: a 20 x 20 x 10 box in a Body; its top edge on y = 0 runs from (0,0,10) to
(20,0,10), middle (10,0,10). Picks are Gui.Selection.addSelection with the picked point, as the 3D
view makes them."""

from PySide import QtWidgets

import FreeCAD as App
import FreeCADGui as Gui

from PartDesignTests.TestCrossBodyGui import ResultBoxGuiCase
from PartDesignTests.TestExpressionFieldsGui import pump, waitFor
from PartDesignTests.TestPlaneEdgePoint import edgeName

V = App.Vector
MIDDLE = V(10, 0, 10)


class TestPlaneEdgePointGui(ResultBoxGuiCase):
    def setUp(self):
        super().setUp()
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        self.box.Length, self.box.Width, self.box.Height = 20, 20, 10
        self.doc.recompute()
        self.edge = edgeName(self.box.Shape, V(0, 0, 10), V(20, 0, 10))
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", self.body)
        view.viewIsometric()
        view.fitAll()
        pump(0.2)

    def pick(self, point):
        Gui.Selection.addSelection(
            self.doc.Name, self.body.Name, self.box.Name + "." + self.edge, point.x, point.y, point.z
        )
        pump(0.3)

    def openPlane(self):
        Gui.runCommand("PartDesign_Plane")
        self.waitForPanel()
        planes = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Plane"]
        self.assertEqual(len(planes), 1)
        return planes[0]

    def refLine(self):
        line = Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "lineRef1")
        self.assertIsNotNone(line, "no reference field")
        return line.text()

    def assertAtMiddle(self, plane):
        self.assertEqual(plane.MapMode, "NormalToEdge")
        self.assertAlmostEqual(plane.MapPathParameter, 0.5)
        self.assertEqual(self.refLine(), "Edge point")
        self.close(ok=True)
        self.doc.recompute()
        self.assertLess((plane.Placement.Base - MIDDLE).Length, 1e-7, str(plane.Placement.Base))
        self.assertAlmostEqual(plane.MapPathParameter, 0.5)

    def testMidpointPickedInTheDialog(self):
        Gui.Selection.clearSelection()
        plane = self.openPlane()
        self.pick(MIDDLE)
        self.assertAtMiddle(plane)

    def testMidpointPreselected(self):
        Gui.Selection.clearSelection()
        self.pick(MIDDLE)
        self.assertAtMiddle(self.openPlane())

    def testPickAwayFromTheMiddleIsTheEdge(self):
        # 6 mm from the middle is far more than 8 px with the box fitted
        Gui.Selection.clearSelection()
        plane = self.openPlane()
        self.pick(V(4, 0, 10))
        self.assertEqual(plane.MapMode, "NormalToEdge")
        self.assertAlmostEqual(plane.MapPathParameter, 0.0)
        self.assertNotEqual(self.refLine(), "Edge point")

    def testOtherModeRestoresTheParameter(self):
        Gui.Selection.clearSelection()
        plane = self.openPlane()
        self.pick(MIDDLE)
        self.assertAlmostEqual(plane.MapPathParameter, 0.5)
        modes = Gui.getMainWindow().findChild(QtWidgets.QListWidget, "listOfModes")
        self.assertIsNotNone(modes)
        selected = modes.selectedItems()
        self.assertEqual(len(selected), 1, "no mode row selected")
        for row in range(modes.count()):
            if modes.item(row) is not selected[0]:
                modes.setCurrentRow(row)
                break
        pump(0.2)
        self.assertNotEqual(plane.MapMode, "NormalToEdge")
        self.assertAlmostEqual(plane.MapPathParameter, 0.0)


class TestPlaneEdgePointNoPickGui(ResultBoxGuiCase):
    """Selection parity 11 (2): a tree or Python selection has no picked point. Its (0,0,0) lies on
    every edge through the origin, and zoomed out within 8 px of the edge's middle, so it must not
    count as a pick. Designed: the box's bottom edge on y = 0 runs from (0,0,0) to (20,0,0); a cube
    20000 mm away, fitted, puts its 10 mm from end to middle well under a pixel."""

    openPlane = TestPlaneEdgePointGui.openPlane
    refLine = TestPlaneEdgePointGui.refLine

    def setUp(self):
        super().setUp()
        import Part

        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        self.box.Length, self.box.Width, self.box.Height = 20, 20, 10
        far = self.doc.addObject("Part::Feature", "Far")
        far.Shape = Part.makeBox(1, 1, 1, V(20000, 20000, 20000))
        self.doc.recompute()
        self.origin = edgeName(self.box.Shape, V(0, 0, 0), V(20, 0, 0))
        view = Gui.getDocument(self.doc.Name).ActiveView
        view.setActiveObject("pdbody", self.body)
        view.viewIsometric()
        view.fitAll()
        pump(0.2)

    def selectWithoutPick(self):
        Gui.Selection.addSelection(self.doc.Name, self.body.Name, self.box.Name + "." + self.origin)
        pump(0.3)

    def assertIsTheEdge(self, plane):
        self.assertEqual(plane.MapMode, "NormalToEdge")
        self.assertAlmostEqual(plane.MapPathParameter, 0.0)
        self.assertNotEqual(self.refLine(), "Edge point")

    def testEdgeWithoutPickInTheDialog(self):
        Gui.Selection.clearSelection()
        plane = self.openPlane()
        self.selectWithoutPick()
        self.assertIsTheEdge(plane)

    def testEdgeWithoutPickPreselected(self):
        Gui.Selection.clearSelection()
        self.selectWithoutPick()
        self.assertIsTheEdge(self.openPlane())

    def testPickAtTheOriginIsTheMiddle(self):
        # a real pick at (0,0,0) is a pick: 10 mm from the middle is under a pixel here
        Gui.Selection.clearSelection()
        plane = self.openPlane()
        Gui.Selection.addSelection(
            self.doc.Name, self.body.Name, self.box.Name + "." + self.origin, 0.0, 0.0, 0.0
        )
        pump(0.3)
        self.assertEqual(plane.MapMode, "NormalToEdge")
        self.assertAlmostEqual(plane.MapPathParameter, 0.5)
        self.assertEqual(self.refLine(), "Edge point")
