# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, design C3, notes/assemblies-design.md section 3): Onshape's mate connector
# points. While a face or edge is hovered all its points are drawn (the centre, the corners, the
# midpoints of its straight edges, the centres of its circular edges); the one under the cursor is
# taken, and a click anywhere else on the face takes the centre (oracle 8, "Mates"). Before, the
# nearest point always won, and a face's straight edges offered no midpoint.
#
# What the team's 148 connectors sit on (GC-A1): a face's centre 66, the midpoint of a face's edge
# 20, of an edge alone 4, a circle's centre 9, a face's corner 4, a body vertex 4. The part's
# origin (17) and sketch vertices (21) wait for oracle questions A5 and A4.
#
# Designed geometry: box A 40 x 20 x 10 at the origin with a hole of radius 3 through its top at
# (30, 10); box B 20 x 10 x 5 at x 60..80. The view looks down the Z axis, fitted, so a point a few
# millimetres away from every candidate is many pixels from all of them.

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui
import Part

from PySide import QtWidgets

import CommandCreateJoint
import JointObject
import UtilsAssembly


def pump(seconds=0.2):
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


class TestConnectorPointsGui(unittest.TestCase):
    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.doc = App.newDocument("ConnectorPointsGui")
        Gui.activateWorkbench("AssemblyWorkbench")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.jointgroup = self.assembly.newObject("Assembly::JointGroup", "Joints")
        solid = Part.makeBox(40, 20, 10).cut(
            Part.makeCylinder(3, 10, App.Vector(30, 10, 0), App.Vector(0, 0, 1))
        )
        self.a = self.assembly.newObject("Part::Feature", "A")
        self.a.Shape = solid
        self.b = self.assembly.newObject("Part::Box", "B")
        self.b.Length, self.b.Width, self.b.Height = 20, 10, 5
        self.b.Placement = App.Placement(App.Vector(60, 0, 0), App.Rotation())
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        self.view = Gui.ActiveDocument.activeView()
        self.view.viewTop()
        self.view.fitAll()
        pump()
        self.top = self.topFace()

    def tearDown(self):
        if JointObject.activeTask is not None:
            JointObject.activeTask.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        App.closeDocument(self.doc.Name)

    def topFace(self):
        for i, face in enumerate(self.a.Shape.Faces):
            if face.Surface.TypeId == "Part::GeomPlane" and abs(face.CenterOfGravity.z - 10) < 1e-9:
                return "Face" + str(i + 1)
        self.fail("no top face")

    def ref(self, element):
        return [self.assembly, ["A." + element]]

    def openFastened(self):
        CommandCreateJoint.activateJoint(0)
        self.assertTrue(waitFor(lambda: JointObject.activeTask is not None), "no joint dialog")
        return JointObject.activeTask

    def pickA(self, panel, element, at):
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "A." + element, *at)
        pump()
        self.assertEqual(len(panel.refs), 1)
        ref = panel.refs[0]
        plc = UtilsAssembly.findPlacement(ref)
        return ref, UtilsAssembly.getJcsGlobalPlc(plc, ref).Base

    def assertPoint(self, got, expected, msg=""):
        self.assertTrue(got.isEqual(App.Vector(*expected), 1e-6), f"{msg}: {got}, expected {expected}")

    # --- the points offered ---------------------------------------------------------------

    def test_a_faces_points(self):
        cands = UtilsAssembly.connectorCandidates(self.ref(self.top))
        kinds = [k for _p, _n, k in cands]
        self.assertEqual(kinds[0], "centre")
        self.assertEqual(kinds.count("corner"), 4)
        self.assertEqual(kinds.count("midpoint"), 4)
        self.assertEqual(kinds.count("circle"), 1)
        mids = sorted((round(p.x, 6), round(p.y, 6)) for p, _n, k in cands if k == "midpoint")
        self.assertEqual(mids, [(0, 10), (20, 0), (20, 20), (40, 10)])
        circle = [p for p, _n, k in cands if k == "circle"][0]
        self.assertPoint(circle, (30, 10, 10), "the hole's centre")

    def test_each_point_is_where_the_connector_goes(self):
        """Every offered point, put in the reference, is the connector findPlacement makes."""
        for point, name, kind in UtilsAssembly.connectorCandidates(self.ref(self.top)):
            with self.subTest(kind=kind, name=name):
                ref = UtilsAssembly.addVertexToReference(self.ref(self.top), name)
                plc = UtilsAssembly.findPlacement(ref)
                self.assertPoint(plc.Base, (point.x, point.y, point.z), kind)
                # the face's frame (Z the face's normal) for every point but a corner of a
                # vertex pick; a face's corner keeps the face's frame
                z = plc.Rotation.multVec(App.Vector(0, 0, 1))
                self.assertAlmostEqual(abs(z.z), 1.0, places=6, msg=kind)

    def test_an_edges_points(self):
        # A's top edge along X at y = 0, z = 10
        edge = None
        for i, e in enumerate(self.a.Shape.Edges):
            pts = [v.Point for v in e.Vertexes]
            if len(pts) == 2 and all(abs(p.y) < 1e-9 and abs(p.z - 10) < 1e-9 for p in pts):
                edge = "Edge" + str(i + 1)
        self.assertIsNotNone(edge)
        cands = UtilsAssembly.connectorCandidates(self.ref(edge))
        self.assertEqual([k for _p, _n, k in cands], ["centre", "corner", "corner"])
        self.assertPoint(cands[0][0], (20, 0, 10), "the edge's midpoint")

    # --- what a click takes ---------------------------------------------------------------

    def test_click_on_a_corner_takes_the_corner(self):
        panel = self.openFastened()
        _ref, at = self.pickA(panel, self.top, (0.1, 0.1, 10))
        self.assertPoint(at, (0, 0, 10), "corner")

    def test_click_on_an_edge_midpoint_takes_it(self):
        panel = self.openFastened()
        _ref, at = self.pickA(panel, self.top, (20.1, 0.1, 10))
        self.assertPoint(at, (20, 0, 10), "a face's edge midpoint")

    def test_click_on_the_hole_rim_takes_its_centre(self):
        """A circular edge's centre is its connector (CENTER, 5 of the team's 9 on the edge)."""
        rim = None
        for i, e in enumerate(self.a.Shape.Edges):
            if e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Location.z - 10) < 1e-9:
                rim = "Edge" + str(i + 1)
        self.assertIsNotNone(rim)
        panel = self.openFastened()
        _ref, at = self.pickA(panel, rim, (33, 10, 10))
        self.assertPoint(at, (30, 10, 10), "the rim's centre")

    def test_click_elsewhere_takes_the_centre(self):
        """Near a corner but not on it took the corner before C3; Onshape takes the centre."""
        panel = self.openFastened()
        _ref, at = self.pickA(panel, self.top, (6, 5, 10))
        # the face's centroid (CENTROID in Onshape): the hole pulls it off (20, 10)
        c = self.a.Shape.getElement(self.top).CenterOfGravity
        self.assertPoint(at, (c.x, c.y, c.z), "a plain click on the face")
        self.assertLess(c.x, 20.0)

    def test_points_drawn_while_hovering(self):
        panel = self.openFastened()
        ref = self.ref(self.top)
        panel.showConnectorPoints(ref, App.Vector(6, 5, 10))
        vp = panel.joint.ViewObject.Proxy
        self.assertEqual(vp.connectorPointsShown(), len(UtilsAssembly.connectorCandidates(ref)))
        vp.showConnectorPoints(None)
        self.assertEqual(vp.connectorPointsShown(), 0)

    # --- the exploded view's "Align to..." takes the same points ----------------------------

    def viewTask(self):
        import CommandCreateView

        task = CommandCreateView.TaskAssemblyCreateView.__new__(
            CommandCreateView.TaskAssemblyCreateView
        )
        task.assembly = self.assembly
        task.blockDraggerMove = False
        return task

    def test_view_align_to_takes_the_corner(self):
        """CommandCreateView passed the assembly as the reference (a TypeError on every hover)."""
        task = self.viewTask()
        task.alignDraggerTo(self.ref(self.top), App.Vector(0.1, 0.1, 10), self.view)
        self.assertPoint(self.assembly.ViewObject.DraggerPlacement.Base, (0, 0, 10), "corner")

    def test_view_align_to_elsewhere_takes_the_centre(self):
        task = self.viewTask()
        task.alignDraggerTo(self.ref(self.top), App.Vector(6, 5, 10), self.view)
        c = self.a.Shape.getElement(self.top).CenterOfGravity
        self.assertPoint(
            self.assembly.ViewObject.DraggerPlacement.Base, (c.x, c.y, c.z), "a plain spot"
        )


if __name__ == "__main__":
    unittest.main()
