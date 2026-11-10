# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (asm-patterns): assembly instance patterns, as Onshape's assembly Linear and Circular
# pattern (AssemblyPattern.py; notes/assembly-patterns-design.md in the ops repo).
#
# Designed geometry: a 10 mm cube "Block" (the seed's part), a 300 x 200 x 5 plate "Plate" (the
# frame), a cylinder "Hub" (an axis). The seed is held by a Fixed joint on the plate, as the team's
# patterned instances are held by Fastened mates. Every expected placement is defined geometrically:
# copy i = Translate(i * distance * d) * seed, d the plate's X edge turned with the plate; circular
# copy i = Rotate(hub axis, i * step) * seed.

import os
import shutil
import tempfile
import time
import unittest

import FreeCAD as App
import Part

import AssemblyPattern
import JointObject
import UtilsAssembly

from AssemblyTests.TestCore import AssemblyTestBase

X = App.Vector(1, 0, 0)


class TestAssemblyPatterns(AssemblyTestBase):
    def setUp(self):
        super().setUp()
        # An assembly as Assembly_CreateAssembly makes it (TestFloatingSolve)
        self.assembly.Type = "Assembly"
        doc = self.doc
        self.block = doc.addObject("Part::Box", "Block")
        self.block.Length = self.block.Width = self.block.Height = 10
        self.plateSrc = doc.addObject("Part::Box", "Plate")
        self.plateSrc.Length, self.plateSrc.Width, self.plateSrc.Height = 300, 200, 5
        self.hubSrc = doc.addObject("Part::Cylinder", "Hub")
        self.hubSrc.Radius, self.hubSrc.Height = 5, 20
        doc.recompute()
        self.plate = self.instance(self.plateSrc)
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedJoint")
        JointObject.GroundedJoint(ground, self.plate)
        self.seed = self.instance(self.block)
        self.fix = self.fixedJoint(self.seed, self.plate, App.Vector(20, 30, 0))
        doc.recompute()

    # --- helpers ----------------------------------------------------------------------------------

    def instance(self, source, placement=None):
        link = self.assembly.newObject("App::Link", source.Name)
        link.LinkedObject = source
        link.Label = AssemblyPattern.instanceLabel(self.assembly, source)
        if placement is not None:
            link.Placement = placement
        return link

    def fixedJoint(self, moving, staying, offset=App.Vector(), name="Fixed"):
        """A Fixed joint picked as the dialog does: the moving part's top face onto the staying one's"""
        joint = self.jointgroup.newObject("App::FeaturePython", name)
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(
            joint, [[moving, ["Face6", "Vertex2"]], [staying, ["Face6", "Vertex2"]]]
        )
        joint.Offset2 = App.Placement(offset, App.Rotation())
        return joint

    def edgeAlong(self, shape, direction):
        """The name of shape's straight edge through its origin along direction (local geometry);
        the pattern goes from the edge's first vertex to its last, so self.alongX is that way"""
        for i, edge in enumerate(shape.Edges):
            p0, p1 = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
            along = (p1 - p0).normalize()
            if min(p0.Length, p1.Length) < 1e-9 and abs(abs(along.dot(direction)) - 1) < 1e-12:
                self.alongX = along
                return f"Edge{i + 1}"
        self.fail("no such edge")

    def linear(self, count=5, distance=20.0, seeds=None):
        edge = self.edgeAlong(self.plateSrc.Shape, X)
        pattern = AssemblyPattern.makePattern(
            self.assembly, "Linear", seeds or [self.seed], (self.plate, [edge])
        )
        pattern.Count = count
        pattern.Distance = distance
        self.doc.recompute()
        return pattern

    def plateX(self):
        """The plate's X edge direction in the assembly"""
        self.edgeAlong(self.plateSrc.Shape, X)
        return self.plate.Placement.Rotation.multVec(self.alongX)

    def assertPlacement(self, obj, plc, what):
        self.assertTrue(
            obj.Placement.isSame(plc, 1e-6), f"{what}: {obj.Label} at {obj.Placement}, not {plc}"
        )

    def assertLinear(self, pattern, seed, count, distance, direction):
        copies = [c for c in pattern.Instances if c.PatternSeed == seed]
        self.assertEqual(len(copies), count - 1, "copies of " + seed.Label)
        for copy in copies:
            i = copy.PatternIndex
            expected = App.Placement(direction * (distance * i), App.Rotation()).multiply(seed.Placement)
            self.assertPlacement(copy, expected, f"copy {i}")
        return copies

    def copiesInAssembly(self):
        return [o for o in self.assembly.Group if AssemblyPattern.isPatternCopy(o)]

    # --- tests ------------------------------------------------------------------------------------

    def test_linear_copies(self):
        """Count 5, Distance 20 along the plate's X edge: 4 copies, each 20 mm further, named as
        Insert names instances, solved with the seed's Fixed joint"""
        pattern = self.linear(5, 20.0)
        self.assertEqual(pattern.Label, "Linear pattern 1")
        copies = self.assertLinear(pattern, self.seed, 5, 20.0, self.plateX())
        self.assertEqual([c.Label for c in copies], [f"Block <{n}>" for n in range(2, 6)])
        self.assertEqual(self.copiesInAssembly(), copies)
        self.assertNotIn("Invalid", pattern.State)
        self.assertEqual(self.assembly.solve(), 0)
        self.assertLinear(pattern, self.seed, 5, 20.0, self.plateX())

    def test_count_and_distance_change(self):
        """A count lowered removes the last copies; raised, adds them; a distance change moves them"""
        pattern = self.linear(5, 20.0)
        removed = [c.Name for c in pattern.Instances][2:]
        pattern.Count = 3
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 3, 20.0, self.plateX())
        for name in removed:
            self.assertIsNone(self.doc.getObject(name), name + " stays")
        pattern.Count = 7
        pattern.Distance = 12.5
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 7, 12.5, self.plateX())
        self.assertEqual(len(self.copiesInAssembly()), 6)
        pattern.Reversed = True
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 7, 12.5, -self.plateX())

    def test_variables_drive_count_and_distance(self):
        """Distance and Count bound to variables (expressions) follow them"""
        variables = self.doc.addObject("App::VarSet", "Variables")
        variables.addProperty("App::PropertyLength", "Spacing")
        variables.addProperty("App::PropertyInteger", "Number")
        variables.Spacing = 15
        variables.Number = 4
        pattern = self.linear()
        pattern.setExpression("Distance", "Variables.Spacing")
        pattern.setExpression("Count", "Variables.Number")
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 15.0, self.plateX())
        variables.Spacing = 30
        variables.Number = 6
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 6, 30.0, self.plateX())
        self.assertFalse([o.Name for o in self.doc.Objects if "Touched" in o.State], "left touched")

    def test_copies_follow_the_seed(self):
        """The plate moves and turns: the seed follows its joint, the copies follow the seed along
        the plate's turned edge"""
        pattern = self.linear(4, 25.0)
        self.plate.Placement = App.Placement(App.Vector(10, -40, 7), App.Rotation(30, 0, 0))
        self.assertEqual(self.assembly.solve(), 0)
        self.assertLinear(pattern, self.seed, 4, 25.0, self.plateX())
        # The joint's offset moves the seed on the plate
        self.fix.Offset2 = App.Placement(App.Vector(60, 10, 0), App.Rotation(0, 0, 0))
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 25.0, self.plateX())

    def test_direction_on_another_part(self):
        """The direction is on a rail that stays while the seed's plate turns: the copies go along
        the rail, not along the turned plate (placed again after the solve)"""
        rail = self.instance(self.plateSrc, App.Placement(App.Vector(0, 0, -100), App.Rotation()))
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedRail")
        JointObject.GroundedJoint(ground, rail)
        # The plate hangs on a free carrier fastened to the ground plate (turnable by its offset)
        edge = self.edgeAlong(self.plateSrc.Shape, X)
        self.doc.recompute()
        pattern = AssemblyPattern.makePattern(self.assembly, "Linear", [self.seed], (rail, [edge]))
        pattern.Count, pattern.Distance = 3, 20.0
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 3, 20.0, self.alongX)
        self.fix.Offset2 = App.Placement(App.Vector(20, 30, 0), App.Rotation(40, 0, 0))
        self.doc.recompute()
        copies = self.assertLinear(pattern, self.seed, 3, 20.0, self.alongX)
        self.assertFalse(copies[0].Placement.Rotation.isSame(App.Rotation(), 1e-6), "the seed turned")

    def test_mate_to_a_copy(self):
        """A peg fastened to copy 3 sits on it, and follows it when the distance changes"""
        pattern = self.linear(4, 20.0)
        third = [c for c in pattern.Instances if c.PatternIndex == 3][0]
        peg = self.instance(self.block, App.Placement(App.Vector(-50, -50, 40), App.Rotation(10, 20, 30)))
        self.fixedJoint(peg, third, name="PegOnCopy")
        self.doc.recompute()
        self.assertPlacement(peg, third.Placement, "the peg on copy 3")
        pattern.Distance = 35.0
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 35.0, self.plateX())
        self.assertPlacement(peg, third.Placement, "the peg follows copy 3")
        self.assertEqual(self.assembly.RedundantJoints, [])

    def test_copy_moved_by_hand_goes_back(self):
        """A copy moved by hand is put back by the next solve, and its seed stays"""
        pattern = self.linear(3, 20.0)
        seed_plc = self.seed.Placement
        copy = pattern.Instances[0]
        copy.Placement = App.Placement(App.Vector(0, 0, 33), App.Rotation())
        self.assertEqual(self.assembly.solve(), 0)
        self.assertPlacement(self.seed, seed_plc, "the seed stays")
        self.assertLinear(pattern, self.seed, 3, 20.0, self.plateX())

    def test_several_seeds(self):
        """Two seeds, each with its own copies"""
        second = self.instance(self.block)
        self.fixedJoint(second, self.plate, App.Vector(20, 120, 0), name="Fixed2")
        self.doc.recompute()
        pattern = self.linear(3, 20.0, seeds=[self.seed, second])
        self.assertLinear(pattern, self.seed, 3, 20.0, self.plateX())
        self.assertLinear(pattern, second, 3, 20.0, self.plateX())
        self.assertEqual(len(pattern.Proxy.clusters(pattern)), 2)

    def test_circular(self):
        """4 instances around the hub's axis, spread over 360 degrees; then 30 degrees apart"""
        hub = self.instance(self.hubSrc, App.Placement(App.Vector(100, 100, 5), App.Rotation(0, 0, 0)))
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedHub")
        JointObject.GroundedJoint(ground, hub)
        self.doc.recompute()
        face = [f"Face{i + 1}" for i, f in enumerate(self.hubSrc.Shape.Faces) if type(f.Surface).__name__ == "Cylinder"][0]
        pattern = AssemblyPattern.makePattern(self.assembly, "Circular", [self.seed], (hub, [face]))
        pattern.Count = 4
        self.doc.recompute()
        self.assertEqual(pattern.Label, "Circular pattern 1")
        axis = hub.Placement.Rotation.multVec(App.Vector(0, 0, 1))
        center = hub.Placement.Base

        def check(step):
            copies = [c for c in pattern.Instances]
            self.assertEqual(len(copies), 3)
            for copy in copies:
                turn = App.Placement(App.Vector(), App.Rotation(axis, step * copy.PatternIndex), center)
                self.assertPlacement(copy, turn.multiply(self.seed.Placement), f"copy {copy.PatternIndex}")

        check(90.0)
        pattern.EqualSpacing = False
        pattern.Angle = 30
        self.doc.recompute()
        check(30.0)
        pattern.EqualSpacing = True
        pattern.Angle = 180
        self.doc.recompute()
        check(60.0)  # 180 spread over 4 instances: 3 steps

    def test_save_and_reopen(self):
        """The copies, their placements and the pattern survive save and reopen, and the pattern
        still acts after it"""
        pattern = self.linear(4, 20.0)
        expected = {c.Name: c.Placement for c in pattern.Instances}
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "pattern.FCStd")
            self.doc.saveAs(path)
            names = pattern.Name, self.seed.Name, self.plate.Name
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            pattern, seed, plate = (self.doc.getObject(n) for n in names)
            self.assertEqual({c.Name for c in pattern.Instances}, set(expected))
            for copy in pattern.Instances:
                self.assertPlacement(copy, expected[copy.Name], "reopened")
            self.assertTrue(AssemblyPattern.isPattern(pattern))
            pattern.Count = 6
            self.doc.recompute()
            self.assertLinear(pattern, seed, 6, 20.0, plate.Placement.Rotation.multVec(self.alongX))
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_bom_counts_copies(self):
        """The BOM (made as Assembly_CreateBom makes it) counts the seed and its copies as one row
        of 5 blocks"""
        self.linear(5, 20.0)
        bom = UtilsAssembly.getBomGroup(self.assembly).newObject("Assembly::BomObject", "BOM")
        bom.columnsNames = ["Index", "Name", "Quantity"]
        self.doc.recompute()
        rows = [(bom.getContents(f"B{r}").lstrip("'"), bom.getContents(f"C{r}").lstrip("'")) for r in range(2, 20)]
        self.assertIn(("Block", "5"), rows)

    def test_lost_direction(self):
        """The direction's edge disappears: the pattern is in error with a message naming it, and
        the copies don't move"""
        rail = self.instance(self.plateSrc, App.Placement(App.Vector(0, 0, -100), App.Rotation()))
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedRail")
        JointObject.GroundedJoint(ground, rail)
        self.doc.recompute()
        pattern = AssemblyPattern.makePattern(self.assembly, "Linear", [self.seed], (rail, ["Edge12"]))
        pattern.Count, pattern.Distance = 3, 20.0
        self.doc.recompute()
        before = {c.Name: c.Placement for c in pattern.Instances}
        self.assertEqual(len(before), 2)
        rail.LinkedObject = self.hubSrc  # a cylinder has 3 edges: Edge12 is gone
        self.doc.recompute()
        self.assertIn("Invalid", pattern.State)
        with self.assertRaisesRegex(RuntimeError, "is gone"):
            pattern.Proxy.transforms(pattern)
        for copy in pattern.Instances:
            self.assertPlacement(copy, before[copy.Name], "a copy of the broken pattern")
        # The solve still runs, and the copies stay
        self.assertEqual(self.assembly.solve(), 0)
        for copy in pattern.Instances:
            self.assertPlacement(copy, before[copy.Name], "a copy after the solve")

    def test_delete_and_suppress(self):
        """A copy deleted by hand comes back; the seed deleted takes its copies; suppressing removes
        the copies and unsuppressing makes them again; deleting the pattern deletes its copies"""
        pattern = self.linear(4, 20.0)
        gone = pattern.Instances[1]
        self.doc.removeObject(gone.Name)
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 20.0, self.plateX())
        pattern.Suppressed = True
        self.doc.recompute()
        self.assertEqual(self.copiesInAssembly(), [])
        pattern.Suppressed = False
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 20.0, self.plateX())
        self.doc.removeObject(pattern.Name)
        self.assertEqual(self.copiesInAssembly(), [])
        # The seed deleted: its copies go, and the pattern says why
        pattern = self.linear(3, 20.0)
        self.doc.removeObject(self.seed.Name)
        self.doc.recompute()
        self.assertEqual(self.copiesInAssembly(), [])
        self.assertIn("Invalid", pattern.State)

    def test_undo_and_redo(self):
        """The pattern made in one transaction (as the command does) goes with its copies on undo
        and comes back on redo"""
        self.doc.UndoMode = 1
        self.doc.openTransaction("Linear pattern")
        pattern = self.linear(4, 20.0)
        self.doc.commitTransaction()
        name = pattern.Name
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(self.copiesInAssembly(), [])
        self.doc.redo()
        self.doc.recompute()
        pattern = self.doc.getObject(name)
        self.assertLinear(pattern, self.seed, 4, 20.0, self.plateX())

    def test_grounded_seed(self):
        """A fixed (grounded) seed stays where it is through solves, and so do its copies (before the
        fix the cluster's body was fixed at each member's placement and drifted at every solve)"""
        self.doc.removeObject(self.fix.Name)
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedSeed")
        JointObject.GroundedJoint(ground, self.seed)
        self.seed.Placement = App.Placement(App.Vector(98, 0, 0), App.Rotation(20, 0, 0))
        self.doc.recompute()
        pattern = self.linear(6, 12.0)
        seed_plc = self.seed.Placement
        for _ in range(3):
            self.assertEqual(self.assembly.solve(), 0)
            self.assertPlacement(self.seed, seed_plc, "the grounded seed")
            self.assertLinear(pattern, self.seed, 6, 12.0, self.plateX())

    def test_count_kept_for_a_mated_copy(self):
        """A count that would remove a copy a mate uses is refused: the pattern names the mate and
        nothing changes (Onshape's mate fails; ours would have lost its part without an error)"""
        pattern = self.linear(4, 20.0)
        last = [c for c in pattern.Instances if c.PatternIndex == 3][0]
        peg = self.instance(self.block, App.Placement(App.Vector(0, 0, 50), App.Rotation()))
        joint = self.fixedJoint(peg, last, name="PegOnLast")
        joint.Label = "Fastened 9"
        self.doc.recompute()
        names = [c.Name for c in pattern.Instances]
        pattern.Count = 3
        self.doc.recompute()
        self.assertIn("Invalid", pattern.State)
        self.assertEqual([c.Name for c in pattern.Instances], names)
        refs = [joint.Reference1[0] if joint.Reference1 else None, joint.Reference2[0] if joint.Reference2 else None]
        self.assertIn(last, refs, f"the mate keeps its part: {[r.Name if r else None for r in refs]}")
        pattern.Suppressed = True
        self.doc.recompute()
        self.assertEqual([c.Name for c in pattern.Instances], names, "suppressed: the same rule")
        pattern.Suppressed = False
        self.doc.removeObject(joint.Name)
        pattern.Count = 3
        self.doc.recompute()
        self.assertNotIn("Invalid", pattern.State)
        self.assertLinear(pattern, self.seed, 3, 20.0, self.plateX())

    def test_undo_of_a_recompute_outside_its_transaction(self):
        """A count lowered, committed, then recomputed (a Ctrl+R after a property edit) makes two
        undo steps. Undone twice, the pattern has Count - 1 copies again, none stacked on another
        (before, the restored copy went unlisted and a new one was made in its place)"""
        self.doc.UndoMode = 1
        self.doc.openTransaction("make")
        pattern = self.linear(4, 20.0)
        self.doc.commitTransaction()
        for between in (False, True):
            self.doc.openTransaction("count")
            pattern.Count = 3
            self.doc.commitTransaction()
            self.doc.recompute()
            self.doc.undo()
            if between:
                self.doc.recompute()
                owned = [o.PatternIndex for o in self.assembly.Group if getattr(o, "PatternOwner", None) == pattern]
                self.assertEqual(len(owned), len(set(owned)), "two copies with one number")
            self.doc.undo()
            self.doc.recompute()
            owned = [o for o in self.assembly.Group if getattr(o, "PatternOwner", None) == pattern]
            self.assertEqual(int(pattern.Count), 4)
            self.assertEqual(sorted(o.PatternIndex for o in owned), [1, 2, 3], [o.Name for o in owned])
            self.assertLinear(pattern, self.seed, 4, 20.0, self.plateX())

    def test_time_four_patterns_of_thirty(self):
        """4 seeds fastened to the plate, each patterned 30 times (120 copies, 124 instances): the
        recompute that makes them, a distance change and a solve stay well under a second each"""
        seeds = [self.seed]
        for k in range(1, 4):
            seed = self.instance(self.block)
            self.fixedJoint(seed, self.plate, App.Vector(20, 30 + 40 * k, 0), name=f"Fixed{k}")
            seeds.append(seed)
        self.doc.recompute()
        edge = self.edgeAlong(self.plateSrc.Shape, X)
        patterns = []
        start = time.perf_counter()
        for seed in seeds:
            pattern = AssemblyPattern.makePattern(self.assembly, "Linear", [seed], (self.plate, [edge]))
            pattern.Count, pattern.Distance = 30, 9.0
            patterns.append(pattern)
        self.doc.recompute()
        made = time.perf_counter() - start
        for pattern, seed in zip(patterns, seeds):
            self.assertLinear(pattern, seed, 30, 9.0, self.plateX())
        start = time.perf_counter()
        for pattern in patterns:
            pattern.Distance = 9.5
        self.doc.recompute()
        changed = time.perf_counter() - start
        self.plate.Placement = App.Placement(App.Vector(5, 5, 5), App.Rotation(15, 0, 0))
        start = time.perf_counter()
        self.assertEqual(self.assembly.solve(), 0)
        solved = time.perf_counter() - start
        for pattern, seed in zip(patterns, seeds):
            self.assertLinear(pattern, seed, 30, 9.5, self.plateX())
        App.Console.PrintWarning(
            f"asm-patterns timing: make 120 copies {made:.3f} s, distance change {changed:.3f} s, "
            f"solve {solved:.3f} s\n"
        )
        self.assertLess(made, 10.0)
        self.assertLess(changed, 2.0)
        self.assertLess(solved, 2.0)


if __name__ == "__main__":
    unittest.main()
