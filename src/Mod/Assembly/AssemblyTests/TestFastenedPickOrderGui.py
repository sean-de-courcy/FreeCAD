# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#772, walk find 5): a Fastened mate takes its two picks in either order, as
# Onshape's does, also when the second pick is on the grounded part. Before, picking the free part
# first and the grounded part second dropped the first pick: the panel kept one reference and OK
# stayed disabled.
#
# Designed geometry: box A 40 x 20 x 10 at the origin (free), box B 20 x 10 x 5 at x 60..80
# (grounded in the order tests). A's top face (Face6) is picked at its centre (20, 10, 10), B's at
# (70, 5, 5). Whatever the order, the mate holds both picks, OK is enabled, B stays where it was
# (it is grounded) and A's top-face centre lands on B's top-face centre.

import gc
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtWidgets

import CommandCreateJoint
import JointObject


def pump(seconds=0.2):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def settle():
    """Lets deleted dialog widgets go (deleteLater) and their Python wrappers with them, so a new
    dialog's widget at a reused address doesn't meet a stale wrapper ("Signal source has been
    deleted", seen in TestAssemblyWorkbenchGui runs; TestMateOffsetsGui does the same)."""
    for _ in range(3):
        pump(0.1)
        gc.collect()
    pump(0.1)


def waitFor(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


A_TOP = ("A.Face6", App.Vector(20, 10, 10))
B_TOP = ("B.Face6", App.Vector(70, 5, 5))
B_AT = App.Vector(60, 0, 0)
C_AT = App.Vector(0, 40, 0)
C_TOP = ("C.Face6", App.Vector(5, 45, 10))
A_BOTTOM = ("A.Face5", App.Vector(20, 10, 0))


class TestFastenedPickOrderGui(unittest.TestCase):
    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        settle()  # the previous test's dialog widgets gone before this one's are made
        self.doc = App.newDocument("FastenedPickOrderGui")
        Gui.activateWorkbench("AssemblyWorkbench")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.jointgroup = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = self.box("A", 40, 20, 10, App.Vector())
        self.b = self.box("B", 20, 10, 5, B_AT)
        self.c = self.box("C", 10, 10, 10, C_AT)  # a third part, for a rejected third pick
        self.doc.recompute()

    def tearDown(self):
        if JointObject.activeTask is not None:
            JointObject.activeTask.reject()
        if Gui.Control.activeDialog():
            Gui.Control.closeDialog()
        pump()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        App.closeDocument(self.doc.Name)
        Gui.doCommand("panel = None")  # activateJoint's console reference to the last dialog
        settle()

    def box(self, name, length, width, height, at):
        """An instance, as Insert makes one: an App::Link in the assembly to a box outside it
        (the walk's parts were instances of Part Studio bodies)."""
        source = self.doc.addObject("PartDesign::Body", name + "Body")
        feature = source.newObject("PartDesign::AdditiveBox", name + "Box")
        feature.Length, feature.Width, feature.Height = length, width, height
        instance = self.assembly.newObject("App::Link", name)
        instance.LinkedObject = source
        instance.Placement = App.Placement(at, App.Rotation())
        return instance

    def ground(self, part):
        ground = self.jointgroup.newObject("App::FeaturePython", "Grounded" + part.Name)
        JointObject.GroundedJoint(ground, part)
        self.doc.recompute()

    def openFastened(self):
        """The Fastened dialog. In a full TestAssemblyWorkbenchGui run, opening it sometimes meets
        a stale PySide wrapper left by an earlier class ("Signal source has been deleted",
        ops#790): then the half-made dialog is dropped (its transaction aborted) and it opens
        once more."""
        for attempt in (1, 2):
            try:
                CommandCreateJoint.activateJoint(0)
                return
            except RuntimeError as error:
                if attempt == 2 or "Signal source has been deleted" not in str(error):
                    raise
                JointObject.activeTask = None
                if Gui.Control.activeDialog():
                    Gui.Control.closeDialog()
                Gui.ActiveDocument.abortCommand()
                settle()

    def mate(self, first, second):
        """Opens the Fastened dialog in assembly edit and picks `first`, then `second`, as the
        view sends a click. Returns the panel."""
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        self.openFastened()
        self.assertTrue(waitFor(lambda: JointObject.activeTask is not None), "no joint dialog")
        panel = JointObject.activeTask
        self.assertEqual(panel.jType, "Fixed")
        for sub, point in (first, second):
            Gui.Selection.addSelection(
                self.doc.Name, self.assembly.Name, sub, point.x, point.y, point.z
            )
            pump()
        return panel

    def assertMated(self, panel, b_moves):
        names = sorted(ref[0].Name + "." + ref[1][0] for ref in panel.refs)
        self.assertEqual(len(panel.refs), 2, f"Expected both picks kept, got {names}")
        self.assertTrue(panel.okButton.isEnabled(), "Expected OK enabled with two picks")
        if not b_moves:
            self.assertTrue(
                self.b.Placement.isSame(App.Placement(B_AT, App.Rotation()), 1e-9),
                f"Expected the grounded B to stay, got {self.b.Placement}",
            )
        # A's top-face centre on B's, wherever the solve put the parts
        rel = App.Placement(B_AT, App.Rotation()) * self.b.Placement.inverse() * self.a.Placement
        centre = rel.multVec(A_TOP[1])
        self.assertTrue(
            centre.isEqual(B_TOP[1], 1e-6), f"Expected A's top centre at {B_TOP[1]}, got {centre}"
        )
        # unflipped, as Onshape's new Fastened mate (GC-B1): A turned as B
        self.assertTrue(
            rel.Rotation.isSame(App.Rotation(), 1e-9), f"Expected A unturned, got {rel.Rotation}"
        )

    def pick(self, sub, point):
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, sub, point.x, point.y, point.z)
        pump()

    def pickNames(self, panel):
        return sorted(ref[0].Name + "." + ref[1][0] for ref in panel.refs)

    def commit(self, panel):
        panel.okButton.click()
        pump()
        if Gui.Control.activeDialog() and JointObject.activeTask:
            JointObject.activeTask.reject()  # the next joint, empty
        self.assertTrue(waitFor(lambda: not Gui.Control.activeDialog()))
        joints = [j for j in self.jointgroup.Group if getattr(j, "Reference2", None)]
        self.assertEqual(len(joints), 1)
        return joints[0]

    def test_grounded_part_picked_second(self):
        """The failing order (3 of 3 on the walk): B grounded, A's face first, B's second."""
        self.ground(self.b)
        panel = self.mate(A_TOP, B_TOP)
        self.assertMated(panel, b_moves=False)

    def test_grounded_part_picked_first(self):
        """Control: B grounded, B's face first, A's second (kept before the fix too)."""
        self.ground(self.b)
        panel = self.mate(B_TOP, A_TOP)
        self.assertMated(panel, b_moves=False)

    def test_nothing_grounded(self):
        """Control: nothing grounded, A's face first, B's second."""
        panel = self.mate(A_TOP, B_TOP)
        self.assertMated(panel, b_moves=True)

    def test_rejected_picks_keep_the_two(self):
        """After the two picks, a third part's face and a second face of A are refused: the two
        picks stay, OK stays enabled and the mate is where it was (each refused pick's removal
        is swallowed, none drops a pick)."""
        self.ground(self.b)
        panel = self.mate(A_TOP, B_TOP)
        before = self.pickNames(panel)
        self.pick(*C_TOP)
        self.pick(*A_BOTTOM)
        self.assertEqual(self.pickNames(panel), before)
        self.assertEqual(panel.addition_rejected, 0, "Expected each refused removal swallowed")
        self.assertMated(panel, b_moves=False)

    def test_edit_click_on_its_own_face_keeps_both(self):
        """An edited mate (B grounded, A then B): a click on A's picked face, a new selection entry
        beside the joint's tip-name one, is refused and drops nothing."""
        self.ground(self.b)
        joint = self.commit(self.mate(A_TOP, B_TOP))
        panel = JointObject.TaskAssemblyCreateJoint(0, joint)
        Gui.Control.showDialog(panel)
        pump()
        try:
            self.assertEqual(len(panel.refs), 2)
            self.pick(*A_TOP)
            self.assertEqual(len(panel.refs), 2, f"Expected both kept, got {self.pickNames(panel)}")
            self.assertTrue(panel.okButton.isEnabled())
            self.assertEqual(panel.addition_rejected, 0)
        finally:
            panel.reject()
            pump()

    def test_grounded_part_picked_second_commits(self):
        """B grounded, A's face first, B's second, then OK: one Fastened joint between A and B,
        with A's top-face centre on B's."""
        self.ground(self.b)
        panel = self.mate(A_TOP, B_TOP)
        self.assertMated(panel, b_moves=False)
        joint = self.commit(panel)
        parts = sorted(movingPartName(ref) for ref in (joint.Reference1, joint.Reference2))
        self.assertEqual(parts, ["A", "B"])


def movingPartName(ref):
    import UtilsAssembly

    return UtilsAssembly.getMovingPart(ref).Name
