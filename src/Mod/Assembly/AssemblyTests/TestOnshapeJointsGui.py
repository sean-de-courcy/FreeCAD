# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, rank 60): the joint (mate) dialog and the insert as Onshape has them.
#
# - Onshape's mate dialog opens with one empty connectors field and its check disabled until two
#   connectors are picked (hands-on E5); the check commits the mate and starts a new one without
#   closing the dialog (Onshape help, Mates).
# - Planar is a mate of its own name; here the Distance joint between two planes.
# - No modal and no grounding on the first insert (hands-on E4).
# - A mate that overdefines the assembly is marked (E3): the joint's error overlay.
# Designed geometry: two 10 mm cubes 40 mm apart along X.

import time
import unittest
from unittest import mock

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

import CommandCreateJoint
import CommandInsertLink
import JointObject
import Preferences


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


class TestOnshapeJointsGui(unittest.TestCase):
    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.doc = App.newDocument("OnshapeJointsGui")
        Gui.activateWorkbench("AssemblyWorkbench")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        # as Assembly_CreateAssembly makes it: the joint code reads a Type-less one as a Part
        self.assembly.Type = "Assembly"
        self.jointgroup = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = self.cube("A", App.Vector(0, 0, 0))
        self.b = self.cube("B", App.Vector(40, 0, 0))
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))

    def tearDown(self):
        if JointObject.activeTask is not None:
            JointObject.activeTask.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        App.closeDocument(self.doc.Name)

    def cube(self, name, at):
        box = self.assembly.newObject("Part::Box", name)
        box.Length = box.Width = box.Height = 10
        box.Placement = App.Placement(at, App.Rotation())
        return box

    def joints(self):
        return [o for o in self.jointgroup.Group if hasattr(o, "JointType")]

    def complete(self):
        return [j for j in self.joints() if j.Reference1 and j.Reference2]

    def openJoint(self, index, label=None):
        CommandCreateJoint.activateJoint(index, label)
        self.assertTrue(waitFor(lambda: JointObject.activeTask is not None), "no joint dialog")
        self.assertTrue(Gui.Control.activeDialog())
        return JointObject.activeTask

    def pickTops(self):
        # Near the (0, 0) corner of each cube's top face (Face6, z = 10)
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "A.Face6", 1, 1, 10)
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "B.Face6", 41, 1, 10)
        pump()

    def test_fastened_opens_empty_with_check_disabled(self):
        panel = self.openJoint(0)
        self.assertEqual(panel.jType, "Fixed")
        self.assertEqual(panel.jForm.featureList.count(), 0, "one empty connectors field")
        self.assertIsNotNone(panel.okButton, "no OK button")
        self.assertFalse(panel.okButton.isEnabled(), "OK enabled with nothing picked")
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "A.Face6", 1, 1, 10)
        pump()
        self.assertEqual(len(panel.refs), 1)
        self.assertFalse(panel.okButton.isEnabled(), "OK enabled with one pick")
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, "B.Face6", 41, 1, 10)
        pump()
        self.assertEqual(len(panel.refs), 2)
        self.assertTrue(panel.okButton.isEnabled(), "OK disabled with two picks")

    def test_ok_starts_the_next_joint(self):
        panel = self.openJoint(0)
        self.pickTops()
        self.assertEqual(len(panel.refs), 2)
        panel.okButton.click()
        pump()
        self.assertTrue(Gui.Control.activeDialog(), "OK closed the dialog")
        self.assertIs(JointObject.activeTask, panel)
        self.assertEqual(len(self.complete()), 1, "the joint was not committed")
        committed = self.complete()[0]
        self.assertIsNot(panel.joint, committed, "no next joint")
        self.assertEqual(panel.refs, [])
        self.assertEqual(panel.jForm.featureList.count(), 0)
        self.assertFalse(panel.okButton.isEnabled())
        self.assertEqual(panel.joint.JointType, "Fixed", "the next joint keeps the type")

        # Cancel drops only the joint in progress
        box = panel.okButton.parent()
        box.button(QtWidgets.QDialogButtonBox.Cancel).click()
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()), "Cancel left the dialog")
        self.assertEqual(self.joints(), [committed])
        self.assertTrue(committed.Reference1 and committed.Reference2, "the committed joint lost a pick")

    def test_planar_by_name(self):
        panel = self.openJoint(5, "Planar")
        self.assertEqual(panel.jType, "Distance")
        self.assertTrue(panel.joint.Label.startswith("Planar"), panel.joint.Label)
        self.assertEqual(panel.jForm.distanceLabel.text(), "Offset")
        self.assertIsNotNone(Gui.Command.get("Assembly_CreateJointPlanar"))
        self.pickTops()
        panel.okButton.click()
        pump()
        planar = self.complete()
        self.assertEqual(len(planar), 1)
        self.assertTrue(planar[0].Label.startswith("Planar"))
        self.assertEqual(planar[0].JointType, "Distance")

    def test_first_insert_asks_nothing(self):
        pref = Preferences.preferences()
        old = pref.GetInt("GroundFirstPart", 0)
        pref.SetInt("GroundFirstPart", 0)
        try:
            stub = mock.MagicMock()
            stub.insertionStack = [{"addedObject": self.a, "translation": App.Vector()}]
            with mock.patch.object(
                CommandInsertLink.QtWidgets, "QMessageBox", side_effect=AssertionError("a modal")
            ):
                CommandInsertLink.TaskAssemblyInsertLink.handleFirstInsertion(stub)
        finally:
            pref.SetInt("GroundFirstPart", old)
        grounded = [o for o in self.jointgroup.Group if hasattr(o, "ObjectToGround")]
        self.assertEqual(grounded, [], "the first insert grounded a part")
        self.assertFalse(self.assembly.isPartGrounded(self.a))

    def test_redundant_joint_marked(self):
        made = []
        for name in ("First", "Second"):
            joint = self.jointgroup.newObject("App::FeaturePython", name)
            JointObject.Joint(joint, 0)
            JointObject.ViewProviderJoint(joint.ViewObject)
            joint.Proxy.setJointConnectors(
                joint, [[self.a, ["Face6", "Vertex7"]], [self.b, ["Face6", "Vertex7"]]]
            )
            made.append(joint)
        self.assembly.solve()
        redundant = self.assembly.RedundantJoints
        self.assertTrue(redundant, "the solve found no redundant joint")
        for joint in made:
            overlays = joint.ViewObject.Proxy.getOverlayIcons()
            marked = "overlay_error" in overlays.values()
            self.assertEqual(marked, joint.Name in redundant, joint.Name)


if __name__ == "__main__":
    unittest.main()
