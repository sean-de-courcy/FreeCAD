# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, design C9, notes/assemblies-design.md section 4b): Onshape's Snap mode.
# With it on, a free instance dragged onto another instance's connector point lands there, with
# no mate made (GC-S1), in one undo step; released away from any point it is a plain drag; with
# it off nothing changes (GC-S6); it is kept nowhere (GC-S4).
#
# Designed geometry: box A 40 x 20 x 10 at the origin, fixed; box B 20 x 10 x 5 at x 60..80, free.
# Both are Part::Box, so their top faces' connector frames are alike and a snap turns nothing
# (an unflipped Fastened mate's presolve between two equal frames is a pure translation). The
# view looks down the Z axis, fitted. The drags are synthetic: press, move and release through
# the Snap mode handler with the screen positions of designed points.

import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

import CommandCreateJoint
import CommandSnapMode
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


class TestSnapModeGui(unittest.TestCase):
    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.doc = App.newDocument("SnapModeGui")
        Gui.activateWorkbench("AssemblyWorkbench")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = self.assembly.newObject("Part::Box", "A")
        self.a.Length, self.a.Width, self.a.Height = 40, 20, 10
        self.b = self.assembly.newObject("Part::Box", "B")
        self.b.Length, self.b.Width, self.b.Height = 20, 10, 5
        self.b.Placement = App.Placement(App.Vector(60, 0, 0), App.Rotation())
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        self.ground = CommandCreateJoint.createGroundedJoint(self.a)
        self.doc.recompute()
        self.view = Gui.ActiveDocument.activeView()
        # a landscape view: in a portrait one (the off-screen default, 400 x 587) the view's
        # getPointOnViewport is off from its own pick by the height/width ratio
        Gui.getMainWindow().resize(1400, 900)
        pump(0.3)
        self.view.viewTop()
        self.view.fitAll()
        pump()
        # off screen the fitted camera can sit inside the boxes' height (the picks saw B's top at
        # z = 5 but not A's at z = 10): lift it along its view axis, which changes nothing in an
        # orthographic top view's projection, and open the clipping planes
        camera = self.view.getCameraNode()
        x, y, _z = camera.position.getValue().getValue()
        camera.position.setValue(x, y, 1000.0)
        camera.nearDistance = 0.01
        camera.farDistance = 1.0e5
        pump()
        self.aStart = App.Placement(self.a.Placement)
        CommandSnapMode.setSnapMode(True)
        self.snap = CommandSnapMode.activeSnap()
        self.assertIsNotNone(self.snap)

    def tearDown(self):
        CommandSnapMode.setSnapMode(False)
        pump()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        App.closeDocument(self.doc.Name)

    def screen(self, x, y, z):
        px, py = self.view.getPointOnViewport(App.Vector(x, y, z))
        return (int(round(px)), int(round(py)))

    def jointCount(self):
        return len(UtilsAssembly.getJointGroup(self.assembly).Group)

    def drag(self, start, *path):
        self.assertTrue(self.snap.press(self.screen(*start)), "no snap drag started")
        for point in path[:-1]:
            self.snap.moveTo(self.screen(*point))
        self.snap.release(self.screen(*path[-1]))
        pump()

    def assertPlacement(self, obj, base, msg=""):
        plc = obj.Placement
        self.assertTrue(plc.Base.isEqual(App.Vector(*base), 1e-6), f"{msg}: {plc.Base}, expected {base}")
        self.assertTrue(plc.Rotation.isIdentity(1e-9), f"{msg}: turned {plc.Rotation}")

    # --- snapping ---------------------------------------------------------------------------

    def test_corner_onto_corner(self):
        """B's top-face corner (60, 0, 5) dragged onto A's top-face corner (40, 0, 10)."""
        joints = self.jointCount()
        self.drag((60.1, 0.1, 5), (30, 5, 10), (39.9, 0.1, 10))
        self.assertPlacement(self.b, (40, 0, 5), "corner onto corner")
        self.assertEqual(self.jointCount(), joints, "a mate was made")
        self.assertEqual(self.a.Placement, self.aStart, "the fixed target moved")

    def test_centre_onto_centre(self):
        """A plain spot on B's top face grabs its centre (70, 5, 5); dropped on A's centre."""
        self.drag((65, 7.5, 5), (20, 10, 10))
        self.assertPlacement(self.b, (10, 5, 5), "centre onto centre")

    def test_points_drawn_while_hovering(self):
        self.assertTrue(self.snap.press(self.screen(70, 5, 5)))
        self.snap.moveTo(self.screen(20, 10, 10))
        ref = [self.a, [self.topFace(self.a)]]
        self.assertEqual(self.snap.pointsShown(), len(UtilsAssembly.connectorCandidates(ref)))
        self.snap.release(self.screen(20, 10, 10))
        self.assertEqual(self.snap.pointsShown(), 0)

    def test_one_undo_step(self):
        before = self.doc.UndoCount
        self.drag((70, 5, 5), (30, 10, 10), (20, 10, 10))
        self.assertEqual(self.doc.UndoCount, before + 1)
        self.doc.undo()
        self.doc.recompute()
        self.assertPlacement(self.b, (60, 0, 0), "after undo")

    def test_release_in_empty_space_is_a_plain_drag(self):
        start, end = self.screen(70, 5, 5), self.screen(70, 40, 5)
        startPoint = self.view.getPoint(*start)
        endPoint = self.view.getPoint(*end)
        self.drag((70, 5, 5), (70, 40, 5))
        expected = App.Vector(60, 0, 0) + (endPoint - startPoint)
        self.assertPlacement(self.b, (expected.x, expected.y, expected.z), "a plain drag")
        self.assertEqual(self.snap.pointsShown(), 0)

    def test_fixed_instance_is_not_snap_dragged(self):
        self.assertFalse(self.snap.press(self.screen(20, 10, 10)))
        self.assertTrue(self.assembly.ViewObject.EnableMovement)

    def test_assembly_drag_restored_after_release(self):
        self.drag((70, 5, 5), (20, 10, 10))
        self.assertTrue(self.assembly.ViewObject.EnableMovement)

    def test_real_mouse_drag(self):
        """Qt mouse events on the 3D view's viewport reach Snap mode (press, move with the button
        held, release): B's corner lands on A's corner."""
        from PySide import QtCore, QtGui

        viewport = self.view.graphicsView().viewport()
        _w, height = self.view.getSize()

        def at(x, y, z):
            px, py = self.screen(x, y, z)
            return QtCore.QPointF(px, height - py - 1)

        def send(kind, point, button, buttons):
            event = QtGui.QMouseEvent(
                kind, point, viewport.mapToGlobal(point.toPoint()), button, buttons,
                QtCore.Qt.NoModifier,
            )
            QtWidgets.QApplication.sendEvent(viewport, event)
            pump(0.05)

        left, none = QtCore.Qt.LeftButton, QtCore.Qt.NoButton
        before = self.doc.UndoCount
        send(QtCore.QEvent.MouseMove, at(60.1, 0.1, 5), none, none)
        send(QtCore.QEvent.MouseButtonPress, at(60.1, 0.1, 5), left, left)
        for point in ((50, 2, 10), (30, 5, 10), (39.9, 0.1, 10)):
            send(QtCore.QEvent.MouseMove, at(*point), none, left)
        send(QtCore.QEvent.MouseButtonRelease, at(39.9, 0.1, 10), left, none)
        pump()
        self.assertPlacement(self.b, (40, 0, 5), "a real drag, corner onto corner")
        self.assertTrue(self.assembly.ViewObject.EnableMovement, "the release ended no drag")
        self.assertEqual(self.doc.UndoCount, before + 1, "not one undo step")

    # --- the toggle -------------------------------------------------------------------------

    def test_off_after_leaving_edit(self):
        """Kept nowhere: leaving the assembly's edit turns it off (GC-S4: off after a reload)."""
        self.assertTrue(CommandSnapMode.isSnapModeOn())
        Gui.ActiveDocument.resetEdit()
        pump()
        CommandSnapMode.CommandToggleSnapMode().IsActive()  # the toolbar's polling notices
        self.assertFalse(CommandSnapMode.isSnapModeOn())

    def test_off_leaves_the_drag_alone(self):
        CommandSnapMode.setSnapMode(False)
        self.assertIsNone(CommandSnapMode.activeSnap())
        self.assertTrue(self.assembly.ViewObject.EnableMovement)

    def topFace(self, box):
        for i, face in enumerate(box.Shape.Faces):
            if abs(face.normalAt(0, 0).z - 1) < 1e-9:
                return "Face" + str(i + 1)
        self.fail("no top face")


if __name__ == "__main__":
    unittest.main()
