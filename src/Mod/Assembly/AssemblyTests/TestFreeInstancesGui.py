# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#683, design group C slice C4): instances that carry no mate, in the 3D view,
# as Onshape's (notes/assemblies-design.md section 4; notes/onshape-facts.md GB11, B7).
#
# - A mouse drag of a free instance moves it, in one undo step, and the move is kept through a
#   save and a reopen.
# - A member of a rigid group (Onshape's Group, GB11: "a group moves as one rigid body") dragged
#   by the mouse or moved by the triad's typed value moves the whole group by the same amount,
#   in one undo step.
# - A hidden instance (hidden from the tree, as Hide does) stays hidden after a save and a
#   reopen, and still counts in the assembly's mass properties (B7: the hidden instance counts;
#   GE-D4: the volume counts every part).
# Designed geometry: free 10 mm cubes, A at the origin and B 40 mm along X, in an assembly at
# identity; the view from the top. Expected placements are the drag's own vector (read from the
# dragged cube) applied to the others; expected volumes are the cubes' sums.

import os
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
TOL = 1e-6


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


class FreeInstancesGuiCase(unittest.TestCase):
    docName = "FreeInstancesGui"
    inEdit = True

    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.tmpdir = None
        self.doc = App.newDocument(self.docName)
        Gui.activateWorkbench("AssemblyWorkbench")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.jointgroup = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = self.cube("A", V(0, 0, 0))
        self.b = self.cube("B", V(40, 0, 0))
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        if self.inEdit:
            self.edit()

    def edit(self):
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        self.vp = self.assembly.ViewObject
        Gui.getMainWindow().show()
        self.view = Gui.ActiveDocument.ActiveView
        # a landscape view, the camera lifted, as TestSnapModeGui does: off screen the view is
        # portrait (400 x 587) and getPointOnScreen is then off from the view's own pick, and the
        # fitted camera can sit inside the cubes' height (notes/assemblies-design.md, C3 and C9)
        Gui.getMainWindow().resize(1400, 900)
        pump(0.3)
        self.view.viewTop()
        self.view.fitAll()
        pump()
        camera = self.view.getCameraNode()
        x, y, _z = camera.position.getValue().getValue()
        camera.position.setValue(x, y, 1000.0)
        camera.nearDistance = 0.01
        camera.farDistance = 1.0e5
        pump(0.3)
        self.viewport = self.view.graphicsView().viewport()

    def tearDown(self):
        Gui.Selection.clearSelection()
        Gui.Control.closeDialog()
        pump()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        pump()
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        pump()
        if self.tmpdir:
            self.tmpdir.cleanup()

    def cube(self, name, at):
        box = self.assembly.newObject("Part::Box", name)
        box.Length = box.Width = box.Height = 10
        box.Placement = App.Placement(at, App.Rotation())
        return box

    def rigidGroup(self, *members):
        import JointObject

        group = self.jointgroup.newObject("App::FeaturePython", "RigidGroup")
        JointObject.RigidGroupJoint(group, list(members))
        self.doc.recompute()
        pump()
        return group

    # Mouse events in the 3D view, as TestTriadGui's TestTriadMouseGui sends them
    def send_mouse(self, kind, pos, button, buttons, modifiers=QtCore.Qt.NoModifier):
        event = QtGui.QMouseEvent(kind, pos, self.viewport.mapToGlobal(pos), button, buttons, modifiers)
        QtWidgets.QApplication.sendEvent(self.viewport, event)

    def screen(self, point):
        vp_point = self.view.getPointOnScreen(point)
        _, height = self.view.getSize()
        scale = self.viewport.devicePixelRatioF()
        return QtCore.QPoint(
            int(round(vp_point[0] / scale)), int(round((height - vp_point[1] - 1) / scale))
        )

    def drag(self, start, end, steps=12):
        pump(QtWidgets.QApplication.doubleClickInterval() / 1000.0 + 0.15)
        self.send_mouse(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        pump(0.05)
        for i in range(1, steps + 1):
            p = QtCore.QPoint(
                start.x() + (end.x() - start.x()) * i // steps,
                start.y() + (end.y() - start.y()) * i // steps,
            )
            self.send_mouse(QtCore.QEvent.MouseMove, p, QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
            pump(0.03)
        self.send_mouse(QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        pump(0.3)

    def dragFace(self, at, dx, dy, name="A"):
        # The press lands on the part: the test checks the drag, not the screen mapping
        info = self.view.getObjectInfo(self.view.getPointOnScreen(at))
        self.assertIsNotNone(info, f"nothing under {at}")
        self.assertIn(name + ".", (info.get("SubName") or "") + "|" + info.get("Object", "") + ".", info)
        start = self.screen(at)
        self.drag(start, QtCore.QPoint(start.x() + dx, start.y() + dy))

    def assertAt(self, obj, plc, what, tol=TOL):
        got = obj.Placement
        self.assertLess((got.Base - plc.Base).Length, tol, f"{what}: {obj.Name} at {got.Base}, not {plc.Base}")
        self.assertTrue(got.Rotation.isSame(plc.Rotation, tol), f"{what}: {obj.Name} turned")

    def saveAndReopen(self):
        Gui.Selection.clearSelection()
        if Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        pump()
        self.tmpdir = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmpdir.name, "free-instances.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        pump()
        self.doc = App.openDocument(path)
        pump()
        return self.doc


class TestFreeInstancesGui(FreeInstancesGuiCase):
    def testDragMovesInOneUndoStepAndPersists(self):
        undo0 = self.doc.UndoCount
        self.dragFace(V(5, 5, 10), 0, 30)
        moved = self.a.Placement
        self.assertGreater(moved.Base.Length, 0.5, "the drag moved nothing")
        self.assertAlmostEqual(moved.Base.z, 0, 6, "a drag in the top view moved A off its plane")
        self.assertAt(self.b, App.Placement(V(40, 0, 0), App.Rotation()), "the other cube")
        self.assertEqual(self.doc.UndoCount, undo0 + 1, "the drag is not one undo step")
        self.assertEqual(
            [o for o in self.jointgroup.Group if hasattr(o, "JointType")], [], "the drag made a mate"
        )

        self.doc.undo()
        pump()
        self.assertAt(self.a, App.Placement(), "undo")
        self.doc.redo()
        pump()
        self.assertAt(self.a, moved, "redo")

        doc = self.saveAndReopen()
        self.assertAt(doc.getObject("A"), moved, "after the reopen")

    def testDraggedGroupMemberMovesTheGroup(self):
        """A and B in a rigid group: a mouse drag of A moves B by the same vector."""
        self.rigidGroup(self.a, self.b)
        undo0 = self.doc.UndoCount
        self.dragFace(V(5, 5, 10), 0, 30)
        by = self.a.Placement.Base
        self.assertGreater(by.Length, 0.5, "the drag moved nothing")
        self.assertAt(self.b, App.Placement(V(40, 0, 0) + by, App.Rotation()), "B did not move with A")
        self.assertEqual(self.doc.UndoCount, undo0 + 1, "the group's drag is not one undo step")
        self.doc.undo()
        pump()
        self.assertAt(self.a, App.Placement(), "undo: A")
        self.assertAt(self.b, App.Placement(V(40, 0, 0), App.Rotation()), "undo: B")

    def testTriadMoveOfAGroupMemberMovesTheGroup(self):
        """A and B in a rigid group: A picked, the triad's typed 12 mm on X moves both by 12."""
        self.rigidGroup(self.a, self.b)
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "A.Face6", 3, 4, 10)
        pump()
        self.assertTrue(waitFor(lambda: self.vp.DraggerVisibility), "no triad on a group member")
        self.vp.dragTriad("TranslateX", App.Placement(V(5, 4, 10), App.Rotation()))
        self.assertTrue(self.vp.applyTriadValue("12 mm"))
        pump()
        self.assertAt(self.a, App.Placement(V(12, 0, 0), App.Rotation()), "A")
        self.assertAt(self.b, App.Placement(V(52, 0, 0), App.Rotation()), "B did not move with A")


class TestHiddenInstanceGui(FreeInstancesGuiCase):
    docName = "HiddenInstanceGui"
    inEdit = False

    def hide(self, obj):
        """Hide as the tree's Hide does: the instance selected under its assembly, Space."""
        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, obj.Name + ".")
        pump()
        Gui.runCommand("Std_ToggleVisibility")
        pump()
        Gui.Selection.clearSelection()

    def shown(self, doc, name):
        return bool(doc.getObject(name).Visibility) and bool(
            doc.getObject("Assembly").isElementVisible(name) != 0
        )

    def testHiddenStaysHiddenAfterReopen(self):
        self.hide(self.b)
        self.assertFalse(self.shown(self.doc, "B"), "Hide did not hide B")
        self.assertTrue(self.shown(self.doc, "A"))
        doc = self.saveAndReopen()
        self.assertFalse(self.shown(doc, "B"), "the hidden instance came back shown")
        self.assertTrue(self.shown(doc, "A"), "the shown instance came back hidden")
        self.assertFalse(doc.getObject("B").ViewObject.Visibility)

    def volume(self, *names):
        """The Mass Properties panel's volume, in mm^3, for the selected objects."""
        Gui.Selection.clearSelection()
        pump()
        Gui.runCommand("Std_MassProperties")
        pump(0.5)
        for name in names:
            Gui.Selection.addSelection(self.doc.Name, name)
            pump(0.2)
        pump(0.5)
        edits = [
            w for w in Gui.getMainWindow().findChildren(QtWidgets.QLineEdit) if w.objectName() == "volumeEdit"
        ]
        self.assertEqual(len(edits), 1, "the panel's volume field")
        text = edits[0].text()
        self.assertTrue(text, "no volume shown for " + ", ".join(names))
        value = App.Units.Quantity(text.split(" (")[0]).getValueAs("mm^3").Value
        Gui.Control.closeDialog()
        pump()
        return value

    def testHiddenInstanceCountsInTheMass(self):
        """B7: A and B shown: 2000 mm^3; B hidden: still 2000; a third cube hidden too: 3000."""
        self.assertAlmostEqual(self.volume("Assembly"), 2000, delta=0.5)
        self.hide(self.b)
        self.assertAlmostEqual(self.volume("Assembly"), 2000, delta=0.5, msg="the hidden B is not counted")
        self.cube("C", V(0, 40, 0))
        self.doc.recompute()
        self.hide(self.doc.getObject("C"))
        self.assertAlmostEqual(self.volume("Assembly"), 3000, delta=0.5, msg="a hidden C is not counted")


if __name__ == "__main__":
    unittest.main()
