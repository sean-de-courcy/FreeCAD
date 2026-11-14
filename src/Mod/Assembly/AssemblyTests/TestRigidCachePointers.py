# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#778): the assembly's rigid-cluster caches (rigidRepByPart, rigidMembersByRep)
# are rebuilt only by a solve, but getGroundedParts and getConnectedParts read them at any time.
# A member deleted after the solve stayed there as a dangling pointer: isPartGrounded then read it
# (getFullName), the use-after-free of ops#683, and an object the heap put at the freed address was
# reported grounded through the deleted member's rigid group.
#
# Designed model: box A (grounded) and box B in a rigid group, box C free. After a solve, B is
# deleted with undo off, so it is freed at once; new boxes are made right after, the first of the
# same size usually at B's address. None of them is in a rigid group or a joint, so none may be
# grounded or connected. A and the rigid group's survivors answer as before.

import unittest

import FreeCAD as App

import JointObject

NEW_BOXES = 24


class TestRigidCachePointers(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("RigidCachePointers")
        self.doc.UndoMode = 0  # a deleted object is freed at once, not kept for undo
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.joints = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = self.box("A", App.Vector(0, 0, 0))
        self.b = self.box("B", App.Vector(20, 0, 0))
        self.c = self.box("C", App.Vector(40, 0, 0))
        ground = self.joints.newObject("App::FeaturePython", "GroundedA")
        JointObject.GroundedJoint(ground, self.a)
        self.group = self.joints.newObject("App::FeaturePython", "RigidAB")
        JointObject.RigidGroupJoint(self.group, [self.a, self.b])
        self.doc.recompute()
        self.assertEqual(self.assembly.solve(), 0)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def box(self, name, at):
        box = self.assembly.newObject("Part::Box", name)
        box.Length = box.Width = box.Height = 10
        box.Placement = App.Placement(at, App.Rotation())
        return box

    def test_control_rigid_group_grounds_its_members(self):
        """Control: B is grounded through its rigid group with A; C is free."""
        self.assertTrue(self.assembly.isPartGrounded(self.b))
        self.assertTrue(self.assembly.isPartConnected(self.b))
        self.assertFalse(self.assembly.isPartGrounded(self.c))
        self.assertFalse(self.assembly.isPartConnected(self.c))

    def assertNoneGrounded(self, boxes):
        grounded = [b.Name for b in boxes if self.assembly.isPartGrounded(b)]
        connected = [b.Name for b in boxes if self.assembly.isPartConnected(b)]
        self.assertEqual(grounded, [], "Expected no new box grounded")
        self.assertEqual(connected, [], "Expected no new box connected")

    def test_deleted_member_leaves_the_rigid_answers(self):
        """B deleted after the solve, no solve since: the new boxes (one usually at B's address)
        are neither grounded nor connected, A still is, C still isn't."""
        self.doc.removeObject("B")
        boxes = [self.box(f"New{i}", App.Vector(0, 20 + 20 * i, 0)) for i in range(NEW_BOXES)]
        self.assertNoneGrounded(boxes)
        self.assertTrue(self.assembly.isPartGrounded(self.a))
        self.assertFalse(self.assembly.isPartGrounded(self.c))
        self.assertFalse(self.assembly.isPartConnected(self.c))

    def test_deleted_member_then_a_joint(self):
        """As ops#778's sequence: B deleted, then a Fastened mate between C and a new box D. The
        joint's checks (isPartConnected, via ensureUnconnectedIsSecondRef) read the rigid caches
        before any solve: D and C are connected to nothing grounded."""
        self.doc.removeObject("B")
        d = self.box("D", App.Vector(60, 0, 0))
        joint = self.joints.newObject("App::FeaturePython", "Fastened")
        JointObject.Joint(joint, 0)
        joint.Reference1 = [self.assembly, ["C.Face2", "C.Vertex6"]]
        joint.Reference2 = [self.assembly, ["D.Face1", "D.Vertex1"]]
        self.assertFalse(self.assembly.isPartConnected(d))
        self.assertFalse(self.assembly.isPartConnected(self.c))
        self.assertFalse(self.assembly.isPartGrounded(d))
        boxes = [self.box(f"New{i}", App.Vector(0, 20 + 20 * i, 0)) for i in range(NEW_BOXES)]
        self.assertNoneGrounded(boxes)

    def test_solve_after_the_delete(self):
        """After a new solve the caches are rebuilt from the rigid group (A alone now): the new
        boxes are free, A is grounded."""
        self.doc.removeObject("B")
        self.doc.recompute()
        self.assertEqual(self.assembly.solve(), 0)
        boxes = [self.box(f"New{i}", App.Vector(0, 20 + 20 * i, 0)) for i in range(NEW_BOXES)]
        self.assertNoneGrounded(boxes)
        self.assertTrue(self.assembly.isPartGrounded(self.a))
