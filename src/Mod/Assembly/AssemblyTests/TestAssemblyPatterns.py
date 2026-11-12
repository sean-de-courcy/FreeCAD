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
Y = App.Vector(0, 1, 0)


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

    # second direction (ops#640 C7): the plate's X edge and its Y edge, a grid of cells (i, j)

    def grid(self, count, distance, count2, distance2, seeds=None):
        """A linear pattern along the plate's X edge with a second direction along its Y edge, all
        set before the first recompute (as the dialog's OK makes it)"""
        edge = self.edgeAlong(self.plateSrc.Shape, X)
        edge2 = self.edgeAlong(self.plateSrc.Shape, Y)
        pattern = AssemblyPattern.makePattern(self.assembly, "Linear", seeds or [self.seed], (self.plate, [edge]))
        pattern.Count, pattern.Distance = count, distance
        pattern.SecondDirection = True
        pattern.Direction2 = (self.plate, [edge2])
        pattern.Count2, pattern.Distance2 = count2, distance2
        self.doc.recompute()
        return pattern

    def localXY(self):
        """The plate's X and Y edge directions in its own frame (first vertex to last)"""
        self.edgeAlong(self.plateSrc.Shape, Y)
        along = self.alongX
        self.edgeAlong(self.plateSrc.Shape, X)
        return self.alongX, along

    def plateY(self):
        """The plate's Y edge direction in the assembly"""
        self.edgeAlong(self.plateSrc.Shape, Y)
        along = self.alongX
        self.edgeAlong(self.plateSrc.Shape, X)  # self.alongX stays the X edge's for the other helpers
        return self.plate.Placement.Rotation.multVec(along)

    def assertGrid(self, pattern, seed, count, distance, count2, distance2, d1, d2):
        """count x count2 instances, the seed's (0, 0) included: copy (i, j) at
        Translate(i * distance * d1 + j * distance2 * d2) * seed, each cell once"""
        copies = [c for c in pattern.Instances if c.PatternSeed == seed]
        self.assertEqual(len(copies), count * count2 - 1, "copies of " + seed.Label)
        cells = sorted(AssemblyPattern.cellOf(c) for c in copies)
        expectedCells = sorted((i, j) for i in range(count) for j in range(count2) if (i, j) != (0, 0))
        self.assertEqual(cells, expectedCells)
        for copy in copies:
            i, j = AssemblyPattern.cellOf(copy)
            offset = d1 * (distance * i) + d2 * (distance2 * j)
            expected = App.Placement(offset, App.Rotation()).multiply(seed.Placement)
            self.assertPlacement(copy, expected, f"copy ({i}, {j})")
        return copies

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

    def test_deleted_pattern_keeps_a_mated_copy(self):
        """Deleting the pattern deletes its copies but one a mate uses: that one stays, a plain
        instance where it was, and its mate keeps its part"""
        pattern = self.linear(4, 20.0)
        third = [c for c in pattern.Instances if c.PatternIndex == 3][0]
        others = [c.Name for c in pattern.Instances if c != third]
        where = third.Placement
        peg = self.instance(self.block)
        joint = self.fixedJoint(peg, third, name="PegOnCopy")
        self.doc.recompute()
        self.doc.removeObject(pattern.Name)
        self.doc.recompute()
        for name in others:
            self.assertIsNone(self.doc.getObject(name), name)
        self.assertIsNotNone(self.doc.getObject(third.Name))
        self.assertFalse(AssemblyPattern.isPatternCopy(third))
        self.assertPlacement(third, where, "the kept copy")
        refs = [joint.Reference1[0] if joint.Reference1 else None, joint.Reference2[0] if joint.Reference2 else None]
        self.assertIn(third, refs, "the mate keeps its part")

    def test_copies_follow_a_relinked_seed(self):
        """The seed relinked to another part, its copies link to it too (the BOM counts it)"""
        pattern = self.linear(3, 20.0)
        other = self.doc.addObject("Part::Box", "Bigger")
        other.Length = other.Width = other.Height = 30
        self.doc.recompute()
        self.seed.LinkedObject = other
        self.doc.recompute()
        self.assertEqual([c.LinkedObject for c in pattern.Instances], [other, other])

    def test_refusals(self):
        """A copy of another pattern as seed, and a fixed copy, are said, not dropped or moved"""
        first = self.linear(3, 20.0)
        copy = first.Instances[0]
        edge = self.edgeAlong(self.plateSrc.Shape, X)
        second = AssemblyPattern.makePattern(self.assembly, "Linear", [copy], (self.plate, [edge]))
        self.doc.recompute()
        self.assertIn("Invalid", second.State)
        with self.assertRaisesRegex(RuntimeError, "is a copy of"):
            second.Proxy.execute(second)
        self.doc.removeObject(second.Name)
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedCopy")
        JointObject.GroundedJoint(ground, copy)
        first.touch()
        self.doc.recompute()
        self.assertIn("Invalid", first.State)
        with self.assertRaisesRegex(RuntimeError, "is fixed"):
            first.Proxy.execute(first)

    def test_disagreeing_mate_moves_no_grounded_part(self):
        """Copy 1 fastened to the grounded plate where the pattern doesn't put it: the solve fails
        and nothing moves (it turned the grounded plate and reported success)"""
        pattern = self.linear(3, 20.0)
        plate_plc = self.plate.Placement
        copy = [c for c in pattern.Instances if c.PatternIndex == 1][0]
        self.fixedJoint(copy, self.plate, App.Vector(150, 150, 0), name="CopyOnPlate")
        self.doc.recompute()
        self.assertEqual(self.assembly.solve(), -1)
        self.assertPlacement(self.plate, plate_plc, "the grounded plate")

    def test_rigid_group_with_a_copy(self):
        """A copy in a rigid group is refused (the group would stop holding its other member to the
        copy when the pattern moves it, review asm-r1-rigid-group-copy)"""
        pattern = self.linear(4, 20.0)
        third = [c for c in pattern.Instances if c.PatternIndex == 3][0]
        partner = self.instance(self.block, App.Placement(third.Placement.Base + App.Vector(0, 0, 10), App.Rotation()))
        self.doc.recompute()
        group = self.jointgroup.newObject("App::FeaturePython", "RigidGroup")
        JointObject.RigidGroupJoint(group, [third, partner])
        pattern.Distance = 35.0
        self.doc.recompute()
        self.assertIn("Invalid", pattern.State)
        with self.assertRaisesRegex(RuntimeError, "rigid group"):
            pattern.Proxy.execute(pattern)

    def test_pasted_copy_is_a_plain_instance(self):
        """A copy duplicated into the assembly (its pattern properties copied too) stays, a plain
        instance where it was put, through the pattern's next edit (it was deleted without a word,
        review asm-r1-pasted-copy)"""
        pattern = self.linear(3, 20.0)
        first = [c for c in pattern.Instances if c.PatternIndex == 1][0]
        twin = self.doc.copyObject(first)
        self.assembly.addObject(twin)
        where = App.Placement(App.Vector(0, 100, 50), App.Rotation())
        twin.Placement = where
        self.doc.recompute()
        pattern.Distance = 30.0
        self.doc.recompute()
        self.assertIsNotNone(self.doc.getObject(twin.Name))
        self.assertFalse(AssemblyPattern.isPatternCopy(twin))
        self.assertPlacement(twin, where, "the pasted instance")
        self.assertNotIn(twin, list(pattern.Instances))
        self.assertLinear(pattern, self.seed, 3, 30.0, self.plateX())

    def test_pasted_copy_survives_count_down_and_suppress(self):
        """A pasted copy stays a plain instance when the next edit lowers the count past it or
        suppresses the pattern (review asm-r1b-paste-count-down, asm-r1b-paste-suppress)"""
        for edit in ("count", "suppress"):
            pattern = self.linear(3, 20.0)
            second = [c for c in pattern.Instances if c.PatternIndex == 2][0]
            twin = self.doc.copyObject(second)
            self.assembly.addObject(twin)
            where = App.Placement(App.Vector(0, 100, 50), App.Rotation())
            twin.Placement = where
            self.doc.recompute()
            if edit == "count":
                pattern.Count = 2
            else:
                pattern.Suppressed = True
            self.doc.recompute()
            self.assertIsNotNone(self.doc.getObject(twin.Name), edit)
            self.assertFalse(AssemblyPattern.isPatternCopy(twin), edit)
            self.assertPlacement(twin, where, "the pasted instance after " + edit)
            self.doc.removeObject(pattern.Name)
            self.doc.removeObject(twin.Name)
            self.doc.recompute()

    # --- second direction (ops#640 C7; Onshape's enableDirection2, all 21 of the team's linear
    # assembly patterns use it) -------------------------------------------------------------------

    def test_second_direction_grid(self):
        """3 x 2 at 20 mm along the plate's X edge and 15 mm along its Y edge: 5 copies on the grid,
        the seed counted once, named on as Insert names instances, solved with the seed's joint;
        the plate turned, the grid turns with it"""
        pattern = self.grid(3, 20.0, 2, 15.0)
        self.assertNotIn("Invalid", pattern.State)
        copies = self.assertGrid(pattern, self.seed, 3, 20.0, 2, 15.0, self.plateX(), self.plateY())
        self.assertEqual(sorted(c.Label for c in copies), sorted(f"Block <{n}>" for n in range(2, 7)))
        self.assertEqual(sorted(c.Name for c in self.copiesInAssembly()), sorted(c.Name for c in copies))
        # The seed's own row first, as a one-direction pattern's, then the next row
        self.assertEqual([AssemblyPattern.cellOf(c) for c in pattern.Instances], [(1, 0), (2, 0), (0, 1), (1, 1), (2, 1)])
        self.assertEqual(self.assembly.solve(), 0)
        self.assertGrid(pattern, self.seed, 3, 20.0, 2, 15.0, self.plateX(), self.plateY())
        self.plate.Placement = App.Placement(App.Vector(10, -40, 7), App.Rotation(30, 0, 0))
        self.assertEqual(self.assembly.solve(), 0)
        self.assertGrid(pattern, self.seed, 3, 20.0, 2, 15.0, self.plateX(), self.plateY())
        # One solver body per seed: the seed and its 5 copies
        clusters = pattern.Proxy.clusters(pattern)
        self.assertEqual([len(c) for c in clusters], [6])

    def test_second_direction_counts_distances_and_flips(self):
        """A count or distance changed in either direction moves, adds or removes copies on the
        grid; the copies that stay keep their cells and names; Flip reverses each direction alone"""
        pattern = self.grid(3, 20.0, 2, 15.0)
        names = {AssemblyPattern.cellOf(c): c.Name for c in pattern.Instances}
        pattern.Count2 = 3
        self.doc.recompute()
        copies = self.assertGrid(pattern, self.seed, 3, 20.0, 3, 15.0, self.plateX(), self.plateY())
        for copy in copies:
            cell = AssemblyPattern.cellOf(copy)
            if cell in names:
                self.assertEqual(copy.Name, names[cell], f"cell {cell} kept its copy")
        pattern.Distance2 = 40.0
        self.doc.recompute()
        self.assertGrid(pattern, self.seed, 3, 20.0, 3, 40.0, self.plateX(), self.plateY())
        gone = [c.Name for c in pattern.Instances if AssemblyPattern.cellOf(c)[0] == 2]
        pattern.Count = 2
        pattern.Distance = 30.0
        self.doc.recompute()
        self.assertGrid(pattern, self.seed, 2, 30.0, 3, 40.0, self.plateX(), self.plateY())
        for name in gone:
            self.assertIsNone(self.doc.getObject(name), name + " stays")
        pattern.Reversed2 = True
        self.doc.recompute()
        self.assertGrid(pattern, self.seed, 2, 30.0, 3, 40.0, self.plateX(), -self.plateY())
        pattern.Reversed, pattern.Reversed2 = True, False
        self.doc.recompute()
        self.assertGrid(pattern, self.seed, 2, 30.0, 3, 40.0, -self.plateX(), self.plateY())
        self.assertEqual(len(self.copiesInAssembly()), 5)

    def test_second_direction_off_is_one_direction(self):
        """Unticked (or at count 1) the second direction changes nothing: the seed's row stays, the
        other rows go; ticked again, they come back"""
        pattern = self.grid(4, 20.0, 3, 15.0)
        row = sorted(c.Name for c in pattern.Instances if AssemblyPattern.cellOf(c)[1] == 0)
        pattern.SecondDirection = False
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 20.0, self.plateX())
        self.assertEqual(sorted(c.Name for c in pattern.Instances), row)
        self.assertEqual(len(self.copiesInAssembly()), 3)
        pattern.SecondDirection = True
        self.doc.recompute()
        self.assertGrid(pattern, self.seed, 4, 20.0, 3, 15.0, self.plateX(), self.plateY())
        pattern.Count2 = 1
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 20.0, self.plateX())
        self.assertEqual(sorted(c.Name for c in pattern.Instances), row)

    def test_one_direction_pattern_unchanged(self):
        """A one-direction pattern is as before: its second direction off at count 1, its copies
        with no second index; a second count set while the box is off changes nothing"""
        pattern = self.linear(4, 20.0)
        self.assertFalse(pattern.SecondDirection)
        self.assertEqual((int(pattern.Count2), pattern.Distance2.Value), (1, 25.0))
        for copy in pattern.Instances:
            self.assertFalse(hasattr(copy, "PatternIndex2"), copy.Label)
        names = [c.Name for c in pattern.Instances]
        pattern.Count2 = 3
        pattern.Direction2 = (self.plate, [self.edgeAlong(self.plateSrc.Shape, Y)])
        self.doc.recompute()
        self.assertLinear(pattern, self.seed, 4, 20.0, self.plateX())
        self.assertEqual([c.Name for c in pattern.Instances], names)

    def test_second_direction_alone(self):
        """Count 1 in the first direction, 3 in the second: copies along the second direction only
        (the first direction needs no reference then)"""
        pattern = self.grid(1, 20.0, 3, 15.0)
        self.assertGrid(pattern, self.seed, 1, 20.0, 3, 15.0, self.plateX(), self.plateY())
        pattern.Direction = None
        self.doc.recompute()
        self.assertNotIn("Invalid", pattern.State)
        self.assertGrid(pattern, self.seed, 1, 20.0, 3, 15.0, self.plateX(), self.plateY())

    def test_second_direction_needs_its_reference(self):
        """Ticked with no second direction: fine at count 1 (the first direction's copies only); at
        count 2 the pattern says to pick one and its copies stay (Onshape: "Select a pattern
        direction.", the field red)"""
        pattern = self.linear(3, 20.0)
        pattern.SecondDirection = True
        self.doc.recompute()
        self.assertNotIn("Invalid", pattern.State)
        self.assertLinear(pattern, self.seed, 3, 20.0, self.plateX())
        names = [c.Name for c in pattern.Instances]
        pattern.Count2 = 2
        self.doc.recompute()
        self.assertIn("Invalid", pattern.State)
        with self.assertRaisesRegex(RuntimeError, "second direction"):
            pattern.Proxy.transforms(pattern)
        self.assertEqual([c.Name for c in pattern.Instances], names)
        pattern.Direction2 = (self.plate, [self.edgeAlong(self.plateSrc.Shape, Y)])
        self.doc.recompute()
        self.assertNotIn("Invalid", pattern.State)
        self.assertGrid(pattern, self.seed, 3, 20.0, 2, 25.0, self.plateX(), self.plateY())

    def test_second_direction_several_seeds(self):
        """Two seeds on a 2 x 2 grid: 3 copies each, one solver body each"""
        second = self.instance(self.block)
        self.fixedJoint(second, self.plate, App.Vector(150, 30, 0), name="Fixed2")
        self.doc.recompute()
        pattern = self.grid(2, 20.0, 2, 50.0, seeds=[self.seed, second])
        for seed in (self.seed, second):
            self.assertGrid(pattern, seed, 2, 20.0, 2, 50.0, self.plateX(), self.plateY())
        self.assertEqual([len(c) for c in pattern.Proxy.clusters(pattern)], [4, 4])

    def test_second_direction_mate_to_a_copy(self):
        """A peg fastened to the copy at (1, 1) follows it when the second distance changes; a
        second count that would remove it is refused"""
        pattern = self.grid(2, 20.0, 2, 15.0)
        corner = [c for c in pattern.Instances if AssemblyPattern.cellOf(c) == (1, 1)][0]
        peg = self.instance(self.block, App.Placement(App.Vector(-50, -50, 40), App.Rotation(10, 20, 30)))
        self.fixedJoint(peg, corner, name="PegOnCorner")
        self.doc.recompute()
        self.assertPlacement(peg, corner.Placement, "the peg on (1, 1)")
        pattern.Distance2 = 45.0
        self.doc.recompute()
        self.assertGrid(pattern, self.seed, 2, 20.0, 2, 45.0, self.plateX(), self.plateY())
        self.assertPlacement(peg, corner.Placement, "the peg follows (1, 1)")
        pattern.Count2 = 1
        self.doc.recompute()
        self.assertIn("Invalid", pattern.State)
        self.assertIsNotNone(self.doc.getObject(corner.Name), "the mated copy stays")

    def test_second_direction_save_and_reopen(self):
        """The grid's copies, their cells and placements survive save and reopen, and its counts
        still act after it"""
        pattern = self.grid(3, 20.0, 2, 15.0)
        expected = {c.Name: (AssemblyPattern.cellOf(c), c.Placement) for c in pattern.Instances}
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "grid.FCStd")
            local = self.localXY()
            self.doc.saveAs(path)
            names = pattern.Name, self.seed.Name, self.plate.Name
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            pattern, seed, plate = (self.doc.getObject(n) for n in names)
            self.assertTrue(pattern.SecondDirection)
            self.assertEqual({c.Name for c in pattern.Instances}, set(expected))
            for copy in pattern.Instances:
                cell, plc = expected[copy.Name]
                self.assertEqual(AssemblyPattern.cellOf(copy), cell)
                self.assertPlacement(copy, plc, "reopened")
            pattern.Count2 = 3
            self.doc.recompute()
            d1, d2 = (plate.Placement.Rotation.multVec(v) for v in local)
            self.assertGrid(pattern, seed, 3, 20.0, 3, 15.0, d1, d2)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def test_pattern_saved_without_second_direction(self):
        """A pattern saved before the second direction (its properties removed) reopens with them,
        off, and its copies where they were; ticked, it makes the grid"""
        pattern = self.linear(3, 20.0)
        for name in ("SecondDirection", "Direction2", "Distance2", "Count2", "Reversed2"):
            pattern.removeProperty(name)
        self.assertFalse(hasattr(pattern, "SecondDirection"))
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "old.FCStd")
            local = self.localXY()
            edge2 = self.edgeAlong(self.plateSrc.Shape, Y)
            self.doc.saveAs(path)
            names = pattern.Name, self.seed.Name, self.plate.Name
            App.closeDocument(self.doc.Name)
            self.doc = App.openDocument(path)
            pattern, seed, plate = (self.doc.getObject(n) for n in names)
            self.assertFalse(pattern.SecondDirection)
            self.assertEqual(int(pattern.Count2), 1)
            d1, d2 = (plate.Placement.Rotation.multVec(v) for v in local)
            self.assertLinear(pattern, seed, 3, 20.0, d1)
            pattern.SecondDirection = True
            pattern.Direction2 = (plate, [edge2])
            pattern.Count2 = 2
            self.doc.recompute()
            self.assertGrid(pattern, seed, 3, 20.0, 2, 25.0, d1, d2)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

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
