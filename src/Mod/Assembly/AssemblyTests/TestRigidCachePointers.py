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
        questions a new joint asks (isPartConnected, as ensureUnconnectedIsSecondRef does; asked
        here directly) read the rigid caches before any solve: neither D nor C is connected."""
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


class TestRigidCacheUndo(unittest.TestCase):
    """As TestRigidCachePointers with undo on: a deleted object stays alive in the undo stack, so
    these answers are deterministic (no reuse of freed memory). Review R1 and R2 of ops#778."""

    def setUp(self):
        self.doc = App.newDocument("RigidCacheUndo")
        self.doc.UndoMode = 1
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.joints = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = TestRigidCachePointers.box(self, "A", App.Vector(0, 0, 0))
        self.b = TestRigidCachePointers.box(self, "B", App.Vector(20, 0, 0))
        ground = self.joints.newObject("App::FeaturePython", "GroundedA")
        JointObject.GroundedJoint(ground, self.a)
        self.group = self.joints.newObject("App::FeaturePython", "RigidAB")
        JointObject.RigidGroupJoint(self.group, [self.a, self.b])
        self.doc.recompute()
        self.assertEqual(self.assembly.solve(), 0)
        self.assertTrue(self.assembly.isPartGrounded(self.b))

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def delete(self, name):
        self.doc.openTransaction("Delete " + name)
        self.doc.removeObject(name)
        self.doc.commitTransaction()

    def test_deleted_member_is_not_grounded(self):
        """B deleted (kept for undo), no solve: B is no longer in the document, so it is neither
        grounded nor connected; before, the stale cluster still grounded it."""
        self.delete("B")
        self.assertFalse(self.assembly.isPartGrounded(self.b))
        self.assertFalse(self.assembly.isPartConnected(self.b))
        self.assertTrue(self.assembly.isPartGrounded(self.a))

    def test_undo_brings_the_member_back_grounded(self):
        """B deleted, asked about, then the delete undone, no solve: B is in its rigid group with
        the grounded A again, so it is grounded and connected again."""
        self.delete("B")
        self.assertFalse(self.assembly.isPartGrounded(self.b))
        self.doc.undo()
        self.assertIn(self.b, self.group.ObjectsToRigidGroup)
        self.assertTrue(self.assembly.isPartGrounded(self.b))
        self.assertTrue(self.assembly.isPartConnected(self.b))

    def test_deleted_rigid_group_frees_its_members(self):
        """The rigid group deleted, no solve: B is grounded through nothing now (review O2);
        undo brings the group, and B's grounding, back."""
        self.delete("RigidAB")
        self.assertFalse(self.assembly.isPartGrounded(self.b))
        self.assertFalse(self.assembly.isPartConnected(self.b))
        self.doc.undo()
        self.assertTrue(self.assembly.isPartGrounded(self.b))


class TestRigidCacheInputs(unittest.TestCase):
    """ops#789: the rigid caches follow a change of their inputs with nothing deleted and no solve:
    a rigid group suppressed or its members edited, a pattern suppressed. The joint dialog, the
    drag check and Select unconnected ask getGroundedParts / getConnectedParts before a solve.

    Designed model: boxes A (grounded), B and C; rigid group RigidAB = [A, B], C free. After a
    solve B is grounded through the group, C is free. Each test changes one input and asks again
    without a recompute or a solve."""

    def setUp(self):
        self.doc = App.newDocument("RigidCacheInputs")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.joints = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = TestRigidCachePointers.box(self, "A", App.Vector(0, 0, 0))
        self.b = TestRigidCachePointers.box(self, "B", App.Vector(20, 0, 0))
        self.c = TestRigidCachePointers.box(self, "C", App.Vector(40, 0, 0))
        ground = self.joints.newObject("App::FeaturePython", "GroundedA")
        JointObject.GroundedJoint(ground, self.a)
        self.group = self.joints.newObject("App::FeaturePython", "RigidAB")
        JointObject.RigidGroupJoint(self.group, [self.a, self.b])
        self.doc.recompute()
        self.assertEqual(self.assembly.solve(), 0)
        self.assertTrue(self.assembly.isPartGrounded(self.b))
        self.assertFalse(self.assembly.isPartGrounded(self.c))

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertState(self, part, grounded):
        word = "grounded" if grounded else "free"
        self.assertEqual(self.assembly.isPartGrounded(part), grounded, f"{part.Name} {word}")
        self.assertEqual(self.assembly.isPartConnected(part), grounded, f"{part.Name} {word}")

    def test_suppressed_rigid_group_frees_its_members(self):
        """RigidAB suppressed, no solve: B is grounded through nothing (CONFIRMED stale before);
        unsuppressed again, B is grounded again. A stays grounded throughout."""
        self.group.Suppressed = True
        self.assertState(self.b, False)
        self.assertState(self.a, True)
        self.group.Suppressed = False
        self.assertState(self.b, True)

    def test_member_removed_from_the_group(self):
        """RigidAB's members edited from [A, B] to [A, C], no solve: B is free, C is grounded."""
        self.group.ObjectsToRigidGroup = [self.a, self.c]
        self.assertState(self.b, False)
        self.assertState(self.c, True)

    def test_member_added_to_the_group(self):
        """RigidAB's members edited from [A, B] to [A, B, C], no solve: C is grounded too."""
        self.group.ObjectsToRigidGroup = [self.a, self.b, self.c]
        self.assertState(self.b, True)
        self.assertState(self.c, True)

    def test_group_that_drops_below_two_members(self):
        """RigidAB's members edited to [A] alone (no group acts), no solve: B is free."""
        self.group.ObjectsToRigidGroup = [self.a]
        self.assertState(self.b, False)
        self.assertState(self.a, True)

    def test_unchanged_inputs_keep_the_answers(self):
        """Control: asked many times with nothing changed, the answers stay (the signature is stable)."""
        for _ in range(3):
            self.assertState(self.b, True)
            self.assertState(self.c, False)


class TestRigidCachePatternInputs(unittest.TestCase):
    """ops#789, patterns: a grounded seed's pattern copies share its solver body, so they read
    grounded after a solve. Designed model: a 300 x 200 x 5 plate and a 10 mm cube seed, both
    grounded, a Linear pattern of the seed along the plate's X edge (3 copies). The pattern
    suppressed, no recompute or solve: the copies are grounded through nothing."""

    def setUp(self):
        import AssemblyPattern

        self.doc = App.newDocument("RigidCachePatternInputs")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.joints = self.assembly.newObject("Assembly::JointGroup", "Joints")
        plate = self.assembly.newObject("Part::Box", "Plate")
        plate.Length, plate.Width, plate.Height = 300, 200, 5
        self.seed = TestRigidCachePointers.box(self, "Seed", App.Vector(20, 30, 5))
        for name, part in (("GroundedPlate", plate), ("GroundedSeed", self.seed)):
            JointObject.GroundedJoint(self.joints.newObject("App::FeaturePython", name), part)
        self.doc.recompute()
        edge = self.edgeAlongX(plate.Shape)
        self.pattern = AssemblyPattern.makePattern(self.assembly, "Linear", [self.seed], (plate, [edge]))
        self.pattern.Count = 4
        self.pattern.Distance = 20.0
        self.doc.recompute()
        self.assertEqual(self.assembly.solve(), 0)
        self.copies = [c for c in self.pattern.Instances if c.PatternSeed == self.seed]
        self.assertEqual(len(self.copies), 3)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def edgeAlongX(self, shape):
        for i, edge in enumerate(shape.Edges):
            p0, p1 = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
            if min(p0.Length, p1.Length) < 1e-9 and abs(abs((p1 - p0).normalize().x) - 1) < 1e-12:
                return f"Edge{i + 1}"
        self.fail("no edge along X")

    def grounded(self):
        return [c.Name for c in self.copies if self.assembly.isPartGrounded(c)]

    def test_control_copies_grounded_with_their_seed(self):
        """Control: after the solve each copy is grounded through its seed's cluster."""
        self.assertEqual(self.grounded(), [c.Name for c in self.copies])

    def test_suppressed_pattern_frees_its_copies(self):
        """The pattern suppressed, no recompute or solve: no copy is grounded; unsuppressed, they
        are again."""
        self.pattern.Suppressed = True
        self.assertEqual(self.grounded(), [])
        self.pattern.Suppressed = False
        self.assertEqual(self.grounded(), [c.Name for c in self.copies])
