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

"""GUI tests for the Measure module's task panels, and Quick Measure (ops#153)."""

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


def quickMeasureModel(doc):
    """Designed shapes for Quick Measure (ops#153), each with known distances:
    - boxes A (10 mm cube at the origin) and B (10 mm cube at x = 20);
    - a sphere S, r = 5 at the origin, and a vertex P at (20, 0, 0);
    - a cylinder Z, r = 5, h = 10, axis along z through (100, 0, 0), and a vertex Q at
      (101, 0, -10), off the axis;
    - two arcs r = 3, a quarter each, centered at (0, 50, 0) and (8, 56, 0) (centers 10 apart);
    - a 2 mm cube I at (4, 4, 4), inside A;
    - two B-spline spheres r = 5 at (0, -50, 0) and (20, -50, 0).
    """
    import math

    import Part

    def feature(name, shape):
        obj = doc.addObject("Part::Feature", name)
        obj.Shape = shape
        return obj

    feature("A", Part.makeBox(10, 10, 10))
    feature("B", Part.makeBox(10, 10, 10, App.Vector(20, 0, 0)))
    feature("S", Part.makeSphere(5))
    feature("P", Part.Vertex(App.Vector(20, 0, 0)))
    feature("Z", Part.makeCylinder(5, 10, App.Vector(100, 0, 0)))
    feature("Q", Part.Vertex(App.Vector(101, 0, -10)))
    for name, center in (("Arc1", App.Vector(0, 50, 0)), ("Arc2", App.Vector(8, 56, 0))):
        circle = Part.Circle(center, App.Vector(0, 0, 1), 3)
        feature(name, Part.ArcOfCircle(circle, 0, math.pi / 2).toShape())
    feature("I", Part.makeBox(2, 2, 2, App.Vector(4, 4, 4)))
    for name, x in (("N1", 0), ("N2", 20)):
        sphere = Part.makeSphere(5, App.Vector(x, -50, 0)).Faces[0].toNurbs()
        feature(name, sphere)
    doc.recompute()


class TestQuickMeasureDistances(unittest.TestCase):
    """Measure.Measurement's distances() and sums() (ops#153), on quickMeasureModel. Needs no
    GUI, but lives here with Quick Measure's other tests."""

    def setUp(self):
        self.doc = App.newDocument("QuickMeasureDistances")
        quickMeasureModel(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def measure(self, *refs):
        import Measure

        App.setActiveDocument(self.doc.Name)
        measurement = Measure.Measurement()
        for obj, sub in refs:
            measurement.addReference3D(obj, sub)
        return measurement

    def testBoxes(self):
        result = self.measure(("A", ""), ("B", "")).distances()
        self.assertAlmostEqual(result["Min"], 10)
        self.assertAlmostEqual(result["Max"], 1100**0.5)  # (0,0,0)-(30,10,10), two vertices
        self.assertTrue(result["MaxExact"])
        self.assertAlmostEqual(result["Center"], 20)
        self.assertFalse(result["Inside"])
        self.assertFalse(result["TimedOut"])

    def testFacingFaces(self):
        result = self.measure(("A", "Face2"), ("B", "Face1")).distances()  # x = 10 and x = 20
        self.assertAlmostEqual(result["Min"], 10)
        self.assertAlmostEqual(result["Max"], 300**0.5)
        self.assertTrue(result["MaxExact"])
        self.assertAlmostEqual(result["Center"], 10)

    def testPointToSphere(self):
        result = self.measure(("P", "Vertex1"), ("S", "Face1")).distances()
        self.assertAlmostEqual(result["Min"], 15)
        self.assertAlmostEqual(result["Max"], 25, places=5)  # the refinement's far point
        self.assertTrue(result["MaxExact"])
        self.assertAlmostEqual(result["Center"], 20)  # the sphere's center

    def testPointToCylinderFace(self):
        result = self.measure(("Q", "Vertex1"), ("Z", "Face1")).distances()
        self.assertAlmostEqual(result["Min"], 116**0.5)  # (105, 0, 0) on the bottom rim
        self.assertAlmostEqual(result["Max"], 436**0.5)  # (95, 0, 10) on the top rim
        self.assertTrue(result["MaxExact"])
        self.assertAlmostEqual(result["Center"], 226**0.5)  # the face's center of mass, z = 5

    def testLinkWithPlacement(self):
        """Review round 1: a Link with its own placement measures in global coordinates."""
        link = self.doc.addObject("App::Link", "L")
        link.LinkedObject = self.doc.getObject("A")
        link.Placement.Base = App.Vector(40, 0, 0)
        self.doc.recompute()
        result = self.measure(("L", "Face1"), ("B", "Face2")).distances()  # x = 40 and x = 30
        self.assertAlmostEqual(result["Min"], 10)
        self.assertAlmostEqual(result["Max"], 300**0.5)
        self.assertAlmostEqual(result["Center"], 10)
        result = self.measure(("L", ""), ("B", "")).distances()
        self.assertAlmostEqual(result["Min"], 10)
        self.assertAlmostEqual(result["Max"], 1100**0.5)
        self.assertAlmostEqual(result["Center"], 20)

    def testPointOnTorusCoreCircle(self):
        """Review round 2: from a point on a torus' core circle the farthest point is on the
        opposite meridian; Max may be called exact only if it is that point."""
        import Part

        torus = self.doc.addObject("Part::Feature", "T")
        torus.Shape = Part.makeTorus(10, 2, App.Vector(0, 0, 200))
        core = self.doc.addObject("Part::Feature", "C")
        core.Shape = Part.Vertex(App.Vector(10, 0, 200))
        self.doc.recompute()
        result = self.measure(("C", "Vertex1"), ("T", "Face1")).distances()
        if result["MaxExact"]:
            self.assertAlmostEqual(result["Max"], 22)
        else:
            self.assertAlmostEqual(result["Max"], 22, delta=0.05)

    def testDecimatedMaxIsApproximate(self):
        """Review round 1: above 2000 candidates every k-th is kept, so even a polyhedral pair's
        Max is no longer exact."""
        import math

        import Part

        points = [
            App.Vector(5 * math.cos(t), 5 * math.sin(t), 0)
            for t in (2 * math.pi * i / 2100 for i in range(2100))
        ]
        polygon = self.doc.addObject("Part::Feature", "Polygon")
        polygon.Shape = Part.makePolygon(points + points[:1])
        self.doc.recompute()
        result = self.measure(("Polygon", ""), ("B", "")).distances()
        self.assertFalse(result["MaxExact"])
        # The circle's point opposite (30, 10, 10) in xy: ((sqrt(1000) + 5)^2 + 10^2)^0.5
        self.assertLessEqual(result["Max"], ((1000**0.5 + 5) ** 2 + 100) ** 0.5 + 1e-6)
        self.assertGreater(result["Max"], ((1000**0.5 + 5) ** 2 + 100) ** 0.5 - 0.01)

    def testPointToBSplineMaxIsApproximate(self):
        """Review round 1: Extrema samples a B-spline face, so Max isn't exact."""
        result = self.measure(("P", "Vertex1"), ("N1", "Face1")).distances()
        self.assertFalse(result["MaxExact"])
        self.assertAlmostEqual(result["Max"], 2900**0.5 + 5, delta=0.05)

    def testTimeLimitBoundsBSplineBodies(self):
        """Review round 1: the time limit bounds every step, not only BRepExtrema. Two bodies of
        fused spheres made B-spline take about 0.75 s unbounded (Windows); at each limit, the
        measure returns within it plus one face's step, whichever step it stops in. The margin
        is wide (at least 0.25 s, or half the limit): local runs share the machine with builds."""
        import time

        import Part

        for name, x in (("F1", 0), ("F2", 30)):
            body = Part.makeSphere(5, App.Vector(x, 100, 0))
            for i in range(6):
                center = App.Vector(x + 4 * (i % 3 - 1), 100 + 4 * (i // 3) - 2, 4)
                body = body.fuse(Part.makeSphere(3, center))
            obj = self.doc.addObject("Part::Feature", name)
            obj.Shape = body.removeSplitter().toNurbs()
        self.doc.recompute()
        for limit in (50, 150, 300, 600):
            with self.subTest(limit=limit):
                measurement = self.measure(("F1", ""), ("F2", ""))
                start = time.monotonic()
                result = measurement.distances(limit)
                elapsed = time.monotonic() - start
                self.assertLess(elapsed, limit / 1000 + max(0.25, 0.5 * limit / 1000))
                self.assertTrue("Max" not in result or not result["MaxExact"])

    def testArcCenters(self):
        result = self.measure(("Arc1", "Edge1"), ("Arc2", "Edge1")).distances()
        self.assertAlmostEqual(result["Center"], 10)

    def testInside(self):
        result = self.measure(("I", ""), ("A", "")).distances()
        self.assertAlmostEqual(result["Min"], 0)
        self.assertTrue(result["Inside"])

    def testBSplineMaxIsApproximate(self):
        result = self.measure(("N1", "Face1"), ("N2", "Face1")).distances()
        self.assertAlmostEqual(result["Min"], 10, places=4)
        self.assertFalse(result["MaxExact"])
        # A lower bound within the sampling deflection (1e-3 of the diagonal, about 0.03 mm)
        self.assertLessEqual(result["Max"], 30 + 1e-6)
        self.assertGreater(result["Max"], 30 - 0.05)
        self.assertAlmostEqual(result["Center"], 20, places=4)

    def testTimeLimit(self):
        result = self.measure(("N1", "Face1"), ("N2", "Face1")).distances(0)
        self.assertTrue(result["TimedOut"])
        self.assertNotIn("Max", result)

    def testOnlyTwoReferences(self):
        result = self.measure(("A", "Face1"), ("A", "Face2"), ("B", "Face1")).distances()
        self.assertNotIn("Min", result)

    def testSums(self):
        result = self.measure(
            ("A", "Edge1"), ("A", "Edge2"), ("A", "Edge3"), ("B", "Face1"), ("B", "Face2")
        ).sums()
        self.assertAlmostEqual(result["Length"], 30)
        self.assertAlmostEqual(result["Area"], 200)
        self.assertEqual((result["Edges"], result["Faces"], result["Vertices"]), (3, 2, 0))

    def testSumsWithVertex(self):
        result = self.measure(("A", "Vertex1"), ("A", "Edge1"), ("A", "Edge2")).sums()
        self.assertAlmostEqual(result["Length"], 20)
        self.assertEqual(result["Vertices"], 1)


class TestQuickMeasureV2(unittest.TestCase):
    """A V2 split face measures the same through its indexed and its mapped subname (which
    contains '|'): Quick Measure hands the whole subname to Part::Feature::getShape. Model as
    in TestMassPropertiesRemoveItem."""

    def testSplitFaceMappedName(self):
        import Measure

        doc = App.newDocument("QuickMeasureV2")
        try:
            doc.HistoryAlgorithm = "V2"
            a = doc.addObject("Part::Box", "A")
            b = doc.addObject("Part::Box", "B")
            b.Length, b.Width, b.Height = 2, 12, 10
            b.Placement.Base = App.Vector(4, -1, 5)
            c = doc.addObject("Part::Box", "C")
            c.Placement.Base = App.Vector(20, 0, 0)
            cut = doc.addObject("Part::Cut", "BF")
            cut.Base, cut.Tool = a, b
            doc.recompute()
            indexed, mapped = sorted(
                (indexed, mapped)
                for mapped, indexed in cut.Shape.ElementMap.items()
                if indexed.startswith("Face") and "|" in mapped
            )[0]
            App.setActiveDocument(doc.Name)
            results = []
            for sub in (indexed, f";{mapped}.{indexed}"):
                measurement = Measure.Measurement()
                measurement.addReference3D("BF", sub)
                measurement.addReference3D("C", "Face1")
                results.append(measurement.distances())
            for key in ("Min", "Max", "Center"):
                self.assertIn(key, results[0])
                self.assertIn(key, results[1])
                self.assertAlmostEqual(results[0][key], results[1][key], msg=key)
        finally:
            App.closeDocument(doc.Name)


class TestQuickMeasureGui(unittest.TestCase):
    """The status bar's Quick Measure label and tooltip (ops#153) for designed selections."""

    def setUp(self):
        if not App.GuiUp:
            self.skipTest("needs the GUI")
        self.doc = App.newDocument("QuickMeasureGui")
        quickMeasureModel(self.doc)
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.Selection.clearSelection()
        self.params = App.ParamGet("User parameter:BaseApp/Preferences/Mod/Measure")

    def tearDown(self):
        if not App.GuiUp:
            return
        self.params.RemInt("QuickMeasureTimeLimit")
        Gui.Selection.clearSelection()
        App.closeDocument(self.doc.Name)
        TestMassPropertiesRemoveItem.pump()

    @staticmethod
    def length(value):
        return App.Units.Quantity(value, App.Units.Length).UserString

    def select(self, *refs):
        """Selects refs and returns the label's text and tooltip once Quick Measure has run
        (100 ms after the selection changes)."""
        import time

        Gui.Selection.clearSelection()
        for obj, sub in refs:
            Gui.Selection.addSelection(self.doc.Name, obj, sub)
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.02)
        label = Gui.getMainWindow().statusBar().findChild(QtWidgets.QLabel, "rightSideLabel")
        self.assertIsNotNone(label, "no Quick Measure label")
        return label.text(), label.toolTip()

    def testTwoBoxes(self):
        text, tip = self.select(("A", ""), ("B", ""))
        self.assertIn("Min: " + self.length(10), text)
        self.assertIn("Max: " + self.length(1100**0.5), text)
        self.assertIn("Center: " + self.length(20), text)
        self.assertIn("ΔX: " + self.length(10), tip)

    def testParallelFacesShowNominalNotMin(self):
        text, _ = self.select(("A", "Face2"), ("B", "Face1"))
        self.assertIn("Nominal distance: " + self.length(10), text)
        self.assertNotIn("Min:", text)
        self.assertIn("Max: " + self.length(300**0.5), text)

    def testApproximateMax(self):
        text, tip = self.select(("N1", "Face1"), ("N2", "Face1"))
        self.assertIn("Max: ≈ ", text)
        self.assertIn("approximate", tip)

    def testThreeItemsShowSums(self):
        """One vertex and two edges showed "Minimum distance: 0" before ops#153."""
        text, _ = self.select(("A", "Vertex1"), ("A", "Edge1"), ("A", "Edge2"))
        self.assertEqual(text, "Total length: " + self.length(20))

    def testTimeLimit(self):
        self.params.SetInt("QuickMeasureTimeLimit", 0)
        text, tip = self.select(("N1", "Face1"), ("N2", "Face1"))
        self.assertIn("Min: –", text)
        self.assertIn("Skipped", tip)

    def testOneVertexTooltip(self):
        text, tip = self.select(("P", "Vertex1"))
        self.assertEqual(text, "")
        self.assertIn("X: " + self.length(20), tip)

    # FreeCAD-CH (ops#673, selection parity 11): an edge picked at its middle (the midpoint
    # marker's 8 px) measures as that point, as in Onshape (SP10-Q9: "Point", then "Min dist"
    # 10 mm with a corner). Box A's top edge on y = 0 runs from (0,0,10) to (10,0,10).
    def topEdge(self):
        shape = self.doc.getObject("A").Shape
        for i, edge in enumerate(shape.Edges, 1):
            ends = {tuple(round(c, 6) for c in v.Point) for v in edge.Vertexes}
            if ends == {(0.0, 0.0, 10.0), (10.0, 0.0, 10.0)}:
                return "Edge%d" % i
        self.fail("no top edge on y = 0")

    def corner(self):
        shape = self.doc.getObject("A").Shape
        for i, vertex in enumerate(shape.Vertexes, 1):
            if (vertex.Point - App.Vector(0, 0, 10)).Length < 1e-9:
                return "Vertex%d" % i
        self.fail("no corner (0,0,10)")

    def selectPicked(self, *picks):
        """Like select, with picks (obj, sub, point or None) made in the 3D view."""
        import time

        view = Gui.ActiveDocument.ActiveView
        view.viewIsometric()
        view.fitAll()
        Gui.Selection.clearSelection()
        for obj, sub, point in picks:
            if point is None:
                Gui.Selection.addSelection(self.doc.Name, obj, sub)
            else:
                Gui.Selection.addSelection(self.doc.Name, obj, sub, point.x, point.y, point.z)
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.02)
        label = Gui.getMainWindow().statusBar().findChild(QtWidgets.QLabel, "rightSideLabel")
        self.assertIsNotNone(label, "no Quick Measure label")
        return label.text(), label.toolTip()

    def testEdgeMiddleIsAPoint(self):
        text, tip = self.selectPicked(("A", self.topEdge(), App.Vector(5, 0, 10)))
        self.assertEqual(text, "")
        self.assertIn("X: " + self.length(5), tip)
        self.assertIn("Z: " + self.length(10), tip)

    def testEdgeMiddleAndCorner(self):
        text, _ = self.selectPicked(
            ("A", self.topEdge(), App.Vector(5, 0, 10)), ("A", self.corner(), None)
        )
        self.assertIn("Distance: " + self.length(5), text)

    def testEdgeAwayFromMiddleIsTheEdge(self):
        # 4 mm from the middle is far more than 8 px with the model fitted
        text, _ = self.selectPicked(("A", self.topEdge(), App.Vector(1, 0, 10)))
        self.assertIn("Length: " + self.length(10), text)

    def testEdgeWithoutPickIsTheEdge(self):
        # a selection made without a 3D pick carries (0,0,0)
        text, _ = self.selectPicked(("A", self.topEdge(), None))
        self.assertIn("Length: " + self.length(10), text)

    # Selection parity 11 (2): a tree or Python selection has no picked point. Its (0,0,0) lies on
    # every edge through the origin, and zoomed out it is within 8 px of a short edge's middle, so
    # it must not count as a pick. Designed: a 1 mm cube at the origin and one 2000 mm away,
    # fitted, so its edges' 0.5 mm from end to middle is well under a pixel.
    def zoomedOutCube(self):
        import Part

        tiny = self.doc.addObject("Part::Feature", "Tiny")
        tiny.Shape = Part.makeBox(1, 1, 1)
        far = self.doc.addObject("Part::Feature", "Far")
        far.Shape = Part.makeBox(1, 1, 1, App.Vector(2000, 2000, 2000))
        self.doc.recompute()

        def edge(end):
            for i, e in enumerate(tiny.Shape.Edges, 1):
                ends = {tuple(round(c, 6) for c in v.Point) for v in e.Vertexes}
                if ends == {(0.0, 0.0, 0.0), end}:
                    return "Edge%d" % i
            self.fail("no edge from the origin to %s" % (end,))

        for i, v in enumerate(tiny.Shape.Vertexes, 1):
            if (v.Point - App.Vector(1, 1, 1)).Length < 1e-9:
                corner = "Vertex%d" % i
        return edge((1.0, 0.0, 0.0)), edge((0.0, 1.0, 0.0)), corner

    def testEdgeThroughTheOriginWithoutPickIsTheEdge(self):
        alongX, _, _ = self.zoomedOutCube()
        text, _ = self.selectPicked(("Tiny", alongX, None))
        self.assertIn("Length: " + self.length(1), text)

    def testThreeItemsThroughTheOriginShowSums(self):
        alongX, alongY, corner = self.zoomedOutCube()
        text, _ = self.selectPicked(("Tiny", corner, None), ("Tiny", alongX, None), ("Tiny", alongY, None))
        self.assertEqual(text, "Total length: " + self.length(2))

    def testPickAtTheOriginOnAShortEdgeIsItsMiddle(self):
        # a real pick at (0,0,0) is a pick: 0.5 mm from the middle is under a pixel here
        alongX, _, _ = self.zoomedOutCube()
        text, tip = self.selectPicked(("Tiny", alongX, App.Vector(0, 0, 0)))
        self.assertEqual(text, "")
        self.assertIn("X: " + self.length(0.5), tip)


class TestMassPropertiesNoMaterial(unittest.TestCase):
    """Rank 16 (ops#640, hands-on D-3): a part with no material is not weighed as water.

    Onshape's mass properties with a part that has no material show the volume and the surface
    area, leave mass, centre of mass and inertia blank, and say "One or more parts do not have a
    material defined". The panel does the same: no mass, density, centre of gravity or inertia,
    the note above the physical properties, the volume and the centre of volume as before.

    Model: box S 10 x 10 x 10 at the origin in Steel (Generic), box N 20 x 10 x 10 at (20, 0, 0)
    with no material (the "Default" one). Both: volume 3000 mm^3, the centre of volume at
    x = (1000 * 5 + 2000 * 30) / 3000 = 21.667 mm. S alone: mass = Steel's density * 1000 mm^3.
    """

    STEEL = "3eeccaf6-847b-46b0-aff8-5ffe08b7fdb7"  # Steel (Generic), Machining library

    def setUp(self):
        if not App.GuiUp:
            self.skipTest("needs the GUI")
        import Materials

        self.doc = App.newDocument("MassPropertiesNoMaterial")
        steel = self.doc.addObject("Part::Box", "S")
        none = self.doc.addObject("Part::Box", "N")
        none.Length = 20
        none.Placement.Base = App.Vector(20, 0, 0)
        self.material = Materials.MaterialManager().getMaterial(self.STEEL)
        steel.ShapeMaterial = self.material
        self.doc.recompute()
        Gui.Selection.clearSelection()
        TestMassPropertiesRemoveItem.pump()
        Gui.runCommand("Std_MassProperties")
        TestMassPropertiesRemoveItem.pump(20)

    def tearDown(self):
        if not App.GuiUp:
            return
        Gui.Selection.clearSelection()
        Gui.Control.closeDialog()
        TestMassPropertiesRemoveItem.pump()
        App.closeDocument(self.doc.Name)
        TestMassPropertiesRemoveItem.pump()

    def field(self, name):
        edits = [w for w in Gui.getMainWindow().findChildren(QtWidgets.QLineEdit) if w.objectName() == name]
        self.assertEqual(len(edits), 1, "the panel's field " + name)
        return edits[0].text()

    def note(self):
        """The note's text where it is shown, else None."""
        for label in Gui.getMainWindow().findChildren(QtWidgets.QLabel):
            if label.objectName() == "materialNote" and label.isVisibleTo(label.window()):
                return label.text()
        return None

    def measure(self, *names):
        for name in names:
            Gui.Selection.addSelection(self.doc.Name, name)
            TestMassPropertiesRemoveItem.pump(10)
        TestMassPropertiesRemoveItem.pump(20)

    @staticmethod
    def value(text, unit):
        return App.Units.Quantity(text.split(" (")[0]).getValueAs(unit).Value

    def testAPartWithoutMaterialBlanksTheMass(self):
        self.measure("S", "N")
        self.assertEqual(self.note(), "One or more parts do not have a material defined")
        self.assertAlmostEqual(self.value(self.field("volumeEdit"), "mm^3"), 3000, delta=0.5)
        self.assertAlmostEqual(self.value(self.field("surfaceAreaEdit"), "mm^2"), 600 + 1000, delta=0.5)
        for name in ("massEdit", "densityEdit", "cogXText", "inertiaJoxText", "inertiaJxText"):
            self.assertEqual(self.field(name), "", name + " shows a figure without a material")
        self.assertAlmostEqual(self.value(self.field("covXText"), "mm"), 65000 / 3000, delta=0.01)

    def testAllPartsWithMaterialAreWeighed(self):
        self.measure("S")
        self.assertIsNone(self.note(), "the note shows with every part's material set")
        density = self.material.getPhysicalValue("Density").getValueAs("kg/mm^3").Value
        self.assertGreater(density, 0)
        mass = self.value(self.field("massEdit"), "kg")
        self.assertAlmostEqual(mass, density * 1000, delta=density * 1000 * 0.01)
        self.assertAlmostEqual(self.value(self.field("cogXText"), "mm"), 5, delta=0.01)
