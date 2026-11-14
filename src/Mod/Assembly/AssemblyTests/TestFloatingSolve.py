# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, rank 60): the Onshape behaviour of the assembly solver.
#
# Onshape fixes no instance on insert and solves mates between unfixed instances: the first-picked
# instance moves to the second (hands-on E4, E5). A mate that overdefines the assembly is reported
# on the mate (E3). Designed geometry: 10 mm cubes; the expected placements are exact (a Fixed
# joint between the same face and vertex of two equal cubes makes their placements equal).

import unittest

import FreeCAD as App

import JointObject

from AssemblyTests.TestCore import AssemblyTestBase


class TestFloatingSolve(AssemblyTestBase):
    def setUp(self):
        super().setUp()
        # An assembly as Assembly_CreateAssembly makes it: without the Type, the joint code takes
        # it for a Part (no solve on joint creation, the second pick pre-solved onto the first)
        self.assembly.Type = "Assembly"

    def cube(self, name, placement):
        box = self.assembly.newObject("Part::Box", name)
        box.Length = box.Width = box.Height = 10
        box.Placement = placement
        return box

    def fixedJoint(self, moving, staying, name="Fixed"):
        """A Fixed joint picked as the dialog does: moving first, staying second."""
        joint = self.jointgroup.newObject("App::FeaturePython", name)
        JointObject.Joint(joint, 0)
        refs = [
            [moving, ["Face6", "Vertex7"]],
            [staying, ["Face6", "Vertex7"]],
        ]
        joint.Proxy.setJointConnectors(joint, refs)
        return joint

    def assertPlacement(self, obj, plc, what):
        self.assertTrue(
            obj.Placement.isSame(plc, 1e-6), f"{what}: {obj.Label} at {obj.Placement}, not {plc}"
        )

    def test_no_grounded_part_needed(self):
        """Two unfixed cubes and one Fixed joint: the solve holds the joint (before rank 60 a
        joint between parts no grounded part reached was dropped from the solve)."""
        staying_plc = App.Placement(App.Vector(40, 50, 60), App.Rotation(45, 55, 65))
        moving = self.cube("Moving", App.Placement(App.Vector(10, 20, 30), App.Rotation(15, 25, 35)))
        staying = self.cube("Staying", staying_plc)
        self.assertEqual(
            [o for o in self.jointgroup.Group if hasattr(o, "ObjectToGround")], [], "a grounded part"
        )

        self.fixedJoint(moving, staying)
        self.assertPlacement(moving, staying_plc, "the first pick moves onto the second")
        self.assertPlacement(staying, staying_plc, "the second pick stays")

        # Move the first pick away: the next solve brings it back, the second pick stays
        moving.Placement = App.Placement(App.Vector(-100, 0, 0), App.Rotation(0, 0, 90))
        self.assertEqual(self.assembly.solve(), 0)
        self.assertPlacement(moving, staying_plc, "the solve holds the joint")
        self.assertPlacement(staying, staying_plc, "the solve keeps the second pick")
        self.assertEqual(self.assembly.RedundantJoints, [], "one joint is not redundant")

    def test_group_follows_its_anchor(self):
        """A chain of three unfixed cubes: the group is held by its first joint's second pick,
        so moving that cube moves the others onto it at the next solve."""
        a = self.cube("A", App.Placement(App.Vector(0, 0, 0), App.Rotation()))
        b = self.cube("B", App.Placement(App.Vector(30, 0, 0), App.Rotation(0, 0, 30)))
        c = self.cube("C", App.Placement(App.Vector(0, 30, 0), App.Rotation(20, 0, 0)))
        self.fixedJoint(a, b, "AB")  # A moves onto B
        self.fixedJoint(c, a, "CA")  # C moves onto A
        for obj in (a, c):
            self.assertPlacement(obj, b.Placement, "the chain closes on B")

        target = App.Placement(App.Vector(5, -7, 11), App.Rotation(10, 20, 30))
        b.Placement = target
        self.assertEqual(self.assembly.solve(), 0)
        for obj in (a, b, c):
            self.assertPlacement(obj, target, "the group follows B")

    def test_grounded_part_still_wins(self):
        """With a grounded part the old rule holds: the grounded part never moves."""
        ground_plc = App.Placement(App.Vector(40, 50, 60), App.Rotation(45, 55, 65))
        grounded = self.cube("Grounded", ground_plc)
        free = self.cube("Free", App.Placement(App.Vector(10, 20, 30), App.Rotation(15, 25, 35)))
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, grounded)
        # Picked with the grounded part first: still the free part moves
        self.fixedJoint(grounded, free)
        self.assertPlacement(grounded, ground_plc, "the grounded part stays")
        self.assertPlacement(free, ground_plc, "the free part moves")

    def test_redundant_joint_reported(self):
        """A second Fixed joint between the same two cubes overdefines the assembly (Onshape
        turns both mates red, hands-on E3): the solve reports it in RedundantJoints."""
        staying_plc = App.Placement(App.Vector(40, 0, 0), App.Rotation())
        moving = self.cube("Moving", App.Placement(App.Vector(0, 0, 0), App.Rotation()))
        staying = self.cube("Staying", staying_plc)
        first = self.fixedJoint(moving, staying, "First")
        self.assertEqual(self.assembly.RedundantJoints, [])
        second = self.fixedJoint(moving, staying, "Second")
        self.assertEqual(self.assembly.solve(), 0)
        redundant = self.assembly.RedundantJoints
        self.assertTrue(redundant, "no joint reported redundant")
        self.assertTrue(set(redundant) <= {first.Name, second.Name}, redundant)
        self.assertTrue(JointObject.jointIsRedundant(self.doc.getObject(redundant[0])))
        self.assertPlacement(moving, staying_plc, "the joints still hold")


if __name__ == "__main__":
    unittest.main()
