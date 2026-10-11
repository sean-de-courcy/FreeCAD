# SPDX-License-Identifier: LGPL-2.1-or-later

"""Carbon copy and Merge Sketches remap every element of a constraint (ops#247).

Both shifted only First/Second/Third, the legacy view of a constraint's first three elements. A
Group holds more: its later elements kept the source sketch's GeoIds and named whatever geometry
has those indices in the destination. Designed geometry: a Group of four lines; each copied
element must name a geometry equal to its source line."""

import math
import os
import re
import shutil
import tempfile
import zipfile

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

V = FreeCAD.Vector
TOL = 1e-9

# the source's four lines, a 10 x 10 square; the Group lists them in this order
SQUARE = [((0, 0), (10, 0)), ((10, 0), (10, 10)), ((10, 10), (0, 10)), ((0, 10), (0, 0))]


def element_geo_ids(constraint):
    """Every element's GeoId, read from the constraint's saved form (Python sees only the first
    three)."""
    found = re.search(r'ElementIds="([^"]*)"', constraint.Content)
    return [int(n) for n in found.group(1).split()]


class TestSketchCopyElementsGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("TestSketchCopyElementsGui")
        self.source = self.doc.addObject("Sketcher::SketchObject", "Source")
        for start, end in SQUARE:
            self.source.addGeometry(Part.LineSegment(V(*start, 0), V(*end, 0)), False)
        self.source.addConstraint(Sketcher.Constraint("Group", [0, 0, 1, 0, 2, 0, 3, 0]))
        # the destination holds one line apart from the square
        self.dest = self.doc.addObject("Sketcher::SketchObject", "Dest")
        self.dest.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)), False)
        self.doc.recompute()
        self.assertEqual(element_geo_ids(self.source.Constraints[0]), [0, 1, 2, 3])

    def assert_group_on_the_square(self, sketch):
        groups = [c for c in sketch.Constraints if c.Type == "Group"]
        self.assertEqual(len(groups), 1)
        ids = element_geo_ids(groups[0])
        self.assertEqual(len(ids), len(SQUARE))
        for geo_id, (start, end) in zip(ids, SQUARE):
            self.assertGreaterEqual(geo_id, 0)
            line = sketch.Geometry[geo_id]
            self.assertLess((line.StartPoint - V(*start, 0)).Length, TOL, (ids, geo_id))
            self.assertLess((line.EndPoint - V(*end, 0)).Length, TOL, (ids, geo_id))

    def merge(self, *sketches):
        """Merge Sketches of `sketches` in this order; the merged sketch."""
        FreeCADGui.Selection.clearSelection()
        for sketch in sketches:
            FreeCADGui.Selection.addSelection(self.doc.Name, sketch.Name)
        before = set(o.Name for o in self.doc.Objects)
        FreeCADGui.runCommand("Sketcher_MergeSketches")
        self.doc.recompute()
        merged = [o for o in self.doc.Objects if o.Name not in before]
        self.assertEqual(len(merged), 1, [o.Name for o in merged])
        return merged[0]

    def merge_dest_and_source(self):
        """Merge Sketches of Dest then Source; the merged sketch."""
        return self.merge(self.dest, self.source)

    def add_line(self, sketch, y):
        """A line 10 long at height y, right of the square; its GeoId"""
        return sketch.addGeometry(Part.LineSegment(V(20, y, 0), V(30, y, 0)), False)

    def add_length(
        self, sketch, geo_id, name="", expression=None, path="Constraints[%d]", value=10
    ):
        """A driving distance on the line `geo_id` (each line here is 10 long), named and driven
        by `expression` when given; its index. An unnamed one's expression is bound by `path`:
        "Constraints[%d]" as the dimension dialog does, ".Constraints[%d]" as Python can."""
        index = sketch.addConstraint(Sketcher.Constraint("Distance", geo_id, value))
        if name:
            sketch.renameConstraint(index, name)
        if expression:
            sketch.setExpression(".Constraints." + name if name else path % index, expression)
        return index

    @staticmethod
    def expressions(sketch):
        return {path: expr for path, expr in sketch.ExpressionEngine}

    def line_length(self, sketch, geo_id):
        line = sketch.Geometry[geo_id]
        return (line.EndPoint - line.StartPoint).Length

    def test_merge_copies_expressions(self):
        """ops#261: the expressions of the copied dimensions come along (the copy loop never
        ran). Dest's length gives the merged constraint 0, Source's constraint 2 (after the
        Group). Source's expression is bound by the path Python can give, ".Constraints[1]"."""
        self.add_length(self.dest, 0, expression="5 + 5")
        self.add_length(self.source, 0, expression="2 * 5", path=".Constraints[%d]")
        self.doc.recompute()
        self.assertEqual(self.expressions(self.source), {".Constraints[1]": "2 * 5"})
        merged = self.merge_dest_and_source()
        self.assertEqual(
            self.expressions(merged), {"Constraints[0]": "5 + 5", "Constraints[2]": "2 * 5"}
        )

    def test_merge_renames_a_taken_name_and_keeps_each_expression(self):
        """Dest and Source both have a length named width, driven by different expressions.
        The copy of Source's is renamed width2, and each keeps its own expression: bound by
        name, Source's went to Dest's width."""
        self.add_length(self.dest, 0, "width", "5 + 5")
        self.add_length(self.source, 0, "width", "2 * 5")
        self.doc.recompute()
        merged = self.merge_dest_and_source()
        self.assertEqual([c.Name for c in merged.Constraints], ["width", "", "width2"])
        self.assertEqual(
            self.expressions(merged),
            {".Constraints.width": "5 + 5", ".Constraints.width2": "2 * 5"},
        )

    def test_merge_expression_names_the_merged_constraint(self):
        """Source's b is driven by its own a (Constraints.a). In the merged sketch b follows the
        merged a, not Source's: a set to 14 there makes both merged lines 14 long, and Source's
        stay 10."""
        self.add_length(self.source, 0, "a")
        self.add_length(self.source, 1, "b", "Constraints.a")
        self.doc.recompute()
        merged = self.merge_dest_and_source()
        self.assertEqual(self.expressions(merged), {".Constraints.b": ".Constraints.a"})
        merged.setDatum("a", FreeCAD.Units.Quantity("14 mm"))
        self.doc.recompute()
        # Dest's line is merged geometry 0, Source's lines 1 to 4
        self.assertAlmostEqual(self.line_length(merged, 1), 14, delta=1e-7)
        self.assertAlmostEqual(self.line_length(merged, 2), 14, delta=1e-7)
        self.assertAlmostEqual(self.line_length(self.source, 0), 10, delta=1e-7)
        self.assertAlmostEqual(self.line_length(self.source, 1), 10, delta=1e-7)

    def test_merge_rewrites_a_reference_to_a_renamed_constraint(self):
        """Dest has a length named a too, so Source's a is renamed a2: Source's b, driven by
        Constraints.a, is driven by Constraints.a2 in the merged sketch, not by Dest's a (ops#267;
        before, its expression wasn't copied). a2 set to 14 makes b's line 14 long."""
        self.add_length(self.dest, 0, "a", "5 + 5")
        self.add_length(self.source, 0, "a")
        self.add_length(self.source, 1, "b", "Constraints.a")
        self.doc.recompute()
        merged = self.merge_dest_and_source()
        self.assertEqual([c.Name for c in merged.Constraints], ["a", "", "a2", "b"])
        self.assertEqual(
            self.expressions(merged),
            {".Constraints.a": "5 + 5", ".Constraints.b": ".Constraints.a2"},
        )
        merged.setDatum("a2", FreeCAD.Units.Quantity("14 mm"))
        self.doc.recompute()
        # Dest's line is merged geometry 0, Source's lines 1 to 4
        self.assertAlmostEqual(self.line_length(merged, 2), 14, delta=1e-7)
        self.assertAlmostEqual(self.line_length(merged, 0), 10, delta=1e-7)

    def test_merge_renames_clear_of_the_sources_later_names(self):
        """PR 237 review L2: Dest has a; Source has a and a2. Source's a is renamed a3, not a2,
        which Source's own a2 keeps, and each reference follows its constraint: b (Constraints.a2)
        the merged a2, c (Constraints.a) the merged a3."""
        self.add_length(self.dest, 0, "a", "5 + 5")
        self.add_length(self.source, 0, "a", value=6)
        self.add_length(self.source, 1, "a2", value=7)
        self.add_length(self.source, 2, "b", "Constraints.a2")
        self.add_length(self.source, 3, "c", "Constraints.a")
        self.doc.recompute()
        merged = self.merge_dest_and_source()
        self.assertEqual([c.Name for c in merged.Constraints], ["a", "", "a3", "a2", "b", "c"])
        self.assertEqual(
            self.expressions(merged),
            {
                ".Constraints.a": "5 + 5",
                ".Constraints.b": ".Constraints.a2",
                ".Constraints.c": ".Constraints.a3",
            },
        )
        # Source's lines are merged geometry 1 to 4: 6, 7, then b = 7 and c = 6
        self.assertEqual(
            [round(self.line_length(merged, g), 6) for g in range(1, 5)], [6, 7, 7, 6]
        )

    def body_dest_with_a_skipped_constraint(self):
        """Puts Dest in a Body with a box, and gives it constraint 0: a horizontal distance from
        the box's edge on the x axis to Dest's line 0. Merge can't import the edge (out of scope
        for a merged sketch outside the Body), so it skips constraint 0. The distance."""
        import PartDesign  # noqa: F401  (registers the PartDesign types)

        body = self.doc.addObject("PartDesign::Body", "Body")
        box = body.newObject("PartDesign::AdditiveBox", "Box")
        self.doc.recompute()
        body.addObject(self.dest)
        # the box's edge on the x axis, (0, 0, 0) to (10, 0, 0)
        (edge,) = [
            "Edge%d" % (i + 1)
            for i, e in enumerate(box.Shape.Edges)
            if all(abs(v.Point.y) < TOL and abs(v.Point.z) < TOL for v in e.Vertexes)
        ]
        self.dest.addExternal(box.Name, edge)
        # from the edge's start to Dest's first line: 20 or 10, whichever end the edge starts at
        distance = 20 - self.dest.getPoint(-3, 1).x
        self.assertEqual(
            self.dest.addConstraint(Sketcher.Constraint("DistanceX", -3, 1, 0, 1, distance)), 0
        )
        return distance

    def test_merge_index_references_after_a_skipped_constraint(self):
        """PR 237 review M1 and ops#267 F1: Merge deletes the constraints it skips, and the
        deletion renamed a reference to an index only partly. Dest's constraint 0 is skipped
        (body_dest_with_a_skipped_constraint); constraint 1 is a length of 7; constraint 2 a
        length driven by Constraints[0]; constraint 3 a length driven by Constraints[1] * 2.
        Constraint 2's reference names a constraint that isn't copied: its expression isn't
        copied (with a warning), and it keeps its value. Constraint 3's names constraint 1, which
        is merged constraint 0: its expression is Constraints[0] * 2, and its line 14 long."""
        distance = self.body_dest_with_a_skipped_constraint()
        for y in (5, 10, 15):
            self.add_line(self.dest, y)
        self.assertEqual(self.add_length(self.dest, 1, value=7), 1)
        self.assertEqual(self.add_length(self.dest, 2, expression="Constraints[0]"), 2)
        self.assertEqual(self.add_length(self.dest, 3, expression="Constraints[1] * 2"), 3)
        self.doc.recompute()
        self.assertAlmostEqual(self.line_length(self.dest, 2), distance, delta=1e-7)
        self.assertAlmostEqual(self.line_length(self.dest, 3), 14, delta=1e-7)
        merged = self.merge_dest_and_source()
        self.assertEqual([c.Type for c in merged.Constraints][:3], ["Distance"] * 3)
        self.assertEqual(self.expressions(merged), {"Constraints[2]": "Constraints[0] * 2"})
        self.assertAlmostEqual(merged.Constraints[1].Value, distance, delta=1e-7)
        # Dest's lines are merged geometry 0 to 3
        self.assertAlmostEqual(self.line_length(merged, 1), 7, delta=1e-7)
        self.assertAlmostEqual(self.line_length(merged, 2), distance, delta=1e-7)
        self.assertAlmostEqual(self.line_length(merged, 3), 14, delta=1e-7)

    def test_merge_rewrites_index_references_of_each_sketch(self):
        """ops#267 F1: an unnamed constraint can be referenced only by its index, and each
        sketch's constraints move by the ones merged before them. Dest: constraint 0 a length of
        10, constraint 1 driven by Constraints[0] + 1. Source (after its Group): constraint 1 a
        length of 6, constraint 2 driven by Constraints[1] * 2. Third: constraint 0 a length of
        3, constraint 1 driven by Constraints[0]. In the merged sketch (Dest's 2, Source's 3,
        Third's 2) each names its own sketch's copy, and the lines are 10, 11, 6, 12, 3, 3."""
        self.add_line(self.dest, 5)
        self.add_length(self.dest, 0)
        self.add_length(self.dest, 1, expression="Constraints[0] + 1")
        self.add_length(self.source, 0, value=6)
        self.add_length(self.source, 1, expression="Constraints[1] * 2")
        third = self.doc.addObject("Sketcher::SketchObject", "Third")
        self.add_line(third, 40)
        self.add_line(third, 45)
        self.add_length(third, 0, value=3)
        self.add_length(third, 1, expression="Constraints[0]")
        self.doc.recompute()
        merged = self.merge(self.dest, self.source, third)
        self.assertEqual(
            self.expressions(merged),
            {
                "Constraints[1]": "Constraints[0] + 1",
                "Constraints[4]": "Constraints[3] * 2",
                "Constraints[6]": "Constraints[5]",
            },
        )
        # Dest's lines are merged geometry 0 and 1, Source's 2 to 5, Third's 6 and 7
        lengths = [round(self.line_length(merged, g), 6) for g in (0, 1, 2, 3, 6, 7)]
        self.assertEqual(lengths, [10, 11, 6, 12, 3, 3])

    def test_merge_maps_an_explicit_reference_to_the_source(self):
        """PR 237 review L3: Source's b is driven by Source.Constraints.a, which names Source
        itself. In the merged sketch it names the merged a, as Constraints.a would (a set to 14
        there makes b's line 14 long, and Source's stay 10). Source's c is driven by
        Source.Placement.Base.x + 4: it still names Source (with a warning), and is 4."""
        self.add_length(self.source, 0, "a")
        self.add_length(self.source, 1, "b", "Source.Constraints.a")
        self.add_length(self.source, 2, "c", "Source.Placement.Base.x + 4")
        self.doc.recompute()
        self.assertAlmostEqual(self.line_length(self.source, 2), 4, delta=1e-7)
        merged = self.merge_dest_and_source()
        expressions = self.expressions(merged)
        self.assertEqual(set(expressions), {".Constraints.b", ".Constraints.c"})
        self.assertNotIn("Source", expressions[".Constraints.b"])
        self.assertIn("Source", expressions[".Constraints.c"])
        merged.setDatum("a", FreeCAD.Units.Quantity("14 mm"))
        self.doc.recompute()
        self.assertAlmostEqual(self.line_length(merged, 2), 14, delta=1e-7)
        self.assertAlmostEqual(self.line_length(merged, 3), 4, delta=1e-7)
        self.assertAlmostEqual(self.line_length(self.source, 1), 10, delta=1e-7)

    def test_merge_keeps_a_reference_to_another_object(self):
        """A reference to a spreadsheet cell names the same cell in the merged sketch: Source's
        length driven by Sheet.A1 (8) is driven by it there too."""
        sheet = self.doc.addObject("Spreadsheet::Sheet", "Sheet")
        sheet.set("A1", "8")
        self.add_length(self.source, 0, "a", "Sheet.A1")
        self.doc.recompute()
        merged = self.merge_dest_and_source()
        self.assertEqual(self.expressions(merged), {".Constraints.a": "Sheet.A1"})
        sheet.set("A1", "9")
        self.doc.recompute()
        self.assertAlmostEqual(self.line_length(merged, 1), 9, delta=1e-7)

    def test_carbon_copy_remaps_every_element(self):
        """Carbon copy of the Source into Dest: the Group's four elements name the copied lines
        (the old code left the fourth on GeoId 3, the third copied line)."""
        self.dest.carbonCopy(self.source.Name, False)
        self.doc.recompute()
        self.assertEqual(len(self.dest.Geometry), 5)
        self.assert_group_on_the_square(self.dest)

    def test_merge_remaps_every_element(self):
        """Merge Sketches of Dest then Source: the merged Group names Source's lines, which come
        after Dest's line."""
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.dest.Name)
        FreeCADGui.Selection.addSelection(self.doc.Name, self.source.Name)
        before = set(o.Name for o in self.doc.Objects)
        FreeCADGui.runCommand("Sketcher_MergeSketches")
        self.doc.recompute()
        merged = [o for o in self.doc.Objects if o.Name not in before]
        self.assertEqual(len(merged), 1, [o.Name for o in merged])
        self.assertEqual(len(merged[0].Geometry), 5)
        self.assert_group_on_the_square(merged[0])

    def test_merge_skips_a_group_whose_fourth_element_is_unmerged(self):
        """PR 229 review L2: only a Group's fourth element names geometry Merge can't import
        (Dest's external, out of scope). The whole Group is skipped (with a message naming the
        element), not kept with that element on other geometry; Source's Group is merged."""
        self.body_dest_with_a_skipped_constraint()
        for y in (5, 10):
            self.add_line(self.dest, y)
        self.dest.addConstraint(Sketcher.Constraint("Group", [0, 0, 1, 0, 2, 0, -3, 1]))
        self.doc.recompute()
        merged = self.merge_dest_and_source()
        self.assertEqual(len(merged.Geometry), 3 + 4)
        groups = [c for c in merged.Constraints if c.Type == "Group"]
        self.assertEqual(len(groups), 1)
        # Source's lines are merged geometry 3 to 6
        self.assertEqual(element_geo_ids(groups[0]), [3, 4, 5, 6])


# the slant of the box in TestMergeExternalPairingGui, about the x axis
SLANT = 30.0


class TestMergeExternalPairingGui(SketcherGuiTestCase):
    """Merge Sketches pairs external geometry by link and geometry, not by position (ops#248).

    A 10 mm box tilted 30 degrees about the x axis, so that its face F (the one through the x
    axis, y = 0 before the tilt) is slanted. A sketch in the plane z = 5 that links F as an
    intersection gets one line, F's section, at y = -5 tan 30; a sketch that links F as a
    projection gets F's outline, the rectangle 0 <= x <= 10, -5 <= y <= 0. The two links have the
    same ref; the old merge reused the projection for the intersection and paired them in order,
    so a constraint on the section moved onto an outline edge."""

    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("TestMergeExternalPairingGui")
        self.box = self.doc.addObject("Part::Box", "Box")
        self.box.Placement = FreeCAD.Placement(V(0, 0, 0), FreeCAD.Rotation(V(1, 0, 0), SLANT))
        self.doc.recompute()
        # F's centre: (5, 0, 5) before the tilt
        centre = self.box.Placement.multVec(V(5, 0, 5))
        self.face = next(
            "Face%d" % (i + 1)
            for i, f in enumerate(self.box.Shape.Faces)
            if (f.CenterOfMass - centre).Length < 1e-6
        )
        self.section_y = -5 * math.tan(math.radians(SLANT))

    def make_sketch(self, name, z):
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        sketch.Placement = FreeCAD.Placement(V(0, 0, z), FreeCAD.Rotation())
        return sketch

    def make_section_sketch(self):
        """S1: F as an intersection, and a line whose start lies on the section"""
        s1 = self.make_sketch("S1", 5)
        s1.addExternal(self.box.Name, self.face, False, True)
        s1.addGeometry(Part.LineSegment(V(5, self.section_y, 0), V(5, 5, 0)), False)
        self.doc.recompute()
        self.assertEqual(len(s1.ExternalGeo), 2 + 1)
        self.assert_is_section(s1.ExternalGeo[2])
        s1.addConstraint(Sketcher.Constraint("PointOnObject", 0, 1, -3))
        self.doc.recompute()
        return s1

    def assert_is_section(self, geo):
        self.assertIsInstance(geo, Part.LineSegment)
        ends = sorted([(geo.StartPoint.x, geo.StartPoint.y), (geo.EndPoint.x, geo.EndPoint.y)])
        expected = [(0, self.section_y), (10, self.section_y)]
        for (x, y), (ex, ey) in zip(ends, expected):
            self.assertAlmostEqual(x, ex, places=6)
            self.assertAlmostEqual(y, ey, places=6)

    def merge(self, *sketches):
        FreeCADGui.Selection.clearSelection()
        for sketch in sketches:
            FreeCADGui.Selection.addSelection(self.doc.Name, sketch.Name)
        before = set(o.Name for o in self.doc.Objects)
        FreeCADGui.runCommand("Sketcher_MergeSketches")
        self.doc.recompute()
        merged = [o for o in self.doc.Objects if o.Name not in before]
        self.assertEqual(len(merged), 1, [o.Name for o in merged])
        return merged[0]

    def test_merge_keeps_an_intersection_apart_from_a_projection(self):
        """S2 links F as a projection (four lines), S1 as an intersection. Merging S2 then S1:
        S1's constraint names the merged section line, and the merged link is both kinds."""
        s1 = self.make_section_sketch()
        s2 = self.make_sketch("S2", 5)
        s2.addExternal(self.box.Name, self.face)
        s2.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)), False)
        self.doc.recompute()
        self.assertEqual(len(s2.ExternalGeo), 2 + 4)

        merged = self.merge(s2, s1)
        on_object = [c for c in merged.Constraints if c.Type == "PointOnObject"]
        self.assertEqual(len(on_object), 1)
        geo_id = on_object[0].Second
        self.assertLessEqual(geo_id, -3)
        self.assert_is_section(merged.ExternalGeo[-geo_id - 1])
        self.assertEqual(len(merged.ExternalGeometry), 1)
        self.assertEqual(list(merged.ExternalTypes), [2])  # projection and intersection

    def test_merge_skips_a_constraint_whose_external_has_no_match(self):
        """S3 lies in z = 6 and comes first, so the merged sketch does too: F's section there is
        another line. S1's constraint on its section is skipped, not moved."""
        s1 = self.make_section_sketch()
        s3 = self.make_sketch("S3", 6)
        s3.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)), False)
        self.doc.recompute()

        merged = self.merge(s3, s1)
        self.assertEqual(merged.Placement.Base.z, 6)
        self.assertEqual([c for c in merged.Constraints if c.Type == "PointOnObject"], [])
        # the merged link gives F's section in z = 6 (PR 233 review L4)
        self.assertEqual(len(merged.ExternalGeo), 2 + 1)
        section = merged.ExternalGeo[2]
        y6 = -6 * math.tan(math.radians(SLANT))
        self.assertAlmostEqual(section.StartPoint.y, y6, places=6)
        self.assertAlmostEqual(section.EndPoint.y, y6, places=6)

    def test_merge_in_the_other_order(self):
        """PR 233 review L4: S1 (the intersection) merged before S2 (the projection): S1's
        constraint still names the section, and S2's constraint on a projected edge names that
        edge's merged copy."""
        s1 = self.make_section_sketch()
        s2 = self.make_sketch("S2", 5)
        s2.addExternal(self.box.Name, self.face)
        s2.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)), False)
        s2.addConstraint(Sketcher.Constraint("Parallel", 0, -4))
        self.doc.recompute()
        merged = self.merge(s1, s2)
        on_object = [c for c in merged.Constraints if c.Type == "PointOnObject"]
        self.assertEqual(len(on_object), 1)
        self.assert_is_section(merged.ExternalGeo[-on_object[0].Second - 1])
        parallel = [c for c in merged.Constraints if c.Type == "Parallel"]
        self.assertEqual(len(parallel), 1)
        self.assert_same_line(
            merged.ExternalGeo[-parallel[0].Second - 1], s2.ExternalGeo[-(-4) - 1]
        )

    def assert_same_line(self, a, b):
        self.assertLess((a.StartPoint - b.StartPoint).Length, 1e-7)
        self.assertLess((a.EndPoint - b.EndPoint).Length, 1e-7)

    def test_merge_keeps_constraints_on_a_projection_and_the_axes(self):
        """PR 233 review L4: S2 (merged second) links F as a projection only, after S5's link to
        another object; S2's line is on its projected edge 2 and horizontal to the H axis, and
        S2's other line is perpendicular to the V axis. In the merged sketch the first names the
        merged copy of that edge, and the axis constraints the axes."""
        post = self.doc.addObject("Part::Box", "Post")
        post.Placement = FreeCAD.Placement(V(40, 0, 0), FreeCAD.Rotation())
        self.doc.recompute()
        s5 = self.make_sketch("S5", 5)
        s5.addExternal(post.Name, self.post_edge(post))
        self.doc.recompute()
        s2 = self.make_sketch("S2", 5)
        s2.addExternal(self.box.Name, self.face)
        self.doc.recompute()
        edge = s2.ExternalGeo[3]
        s2.addGeometry(Part.LineSegment(edge.StartPoint, edge.EndPoint), False)
        s2.addGeometry(Part.LineSegment(V(20, 0, 0), V(20, 10, 0)), False)
        s2.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -4, 1))
        s2.addConstraint(Sketcher.Constraint("PointOnObject", 1, 1, -1))
        s2.addConstraint(Sketcher.Constraint("Parallel", 1, -2))
        self.doc.recompute()
        merged = self.merge(s5, s2)
        by_type = {c.Type: c for c in merged.Constraints}
        coincident = by_type["Coincident"]
        self.assertLessEqual(coincident.Second, -4)  # after S5's external
        self.assert_same_line(merged.ExternalGeo[-coincident.Second - 1], edge)
        self.assertEqual(by_type["PointOnObject"].Second, -1)
        self.assertEqual(by_type["Parallel"].Second, -2)

    @staticmethod
    def post_edge(post):
        """The Post's bottom edge x = 40 (along y), which projects onto a line of its own"""
        return next(
            "Edge%d" % (i + 1)
            for i, e in enumerate(post.Shape.Edges)
            if all(abs(v.Point.x - 40) < 1e-6 and abs(v.Point.z) < 1e-6 for v in e.Vertexes)
        )

    def test_merge_pairs_an_intersection_with_the_intersection_not_an_equal_projection(self):
        """PR 233 review M1: F' is the face y = 0 of an untilted box, perpendicular to the
        plane z = 5. Its projection there collapses onto the same line as its section, in the
        same direction (for the faces x = const the two run opposite ways). SA links F' as a
        projection, SB as an intersection with a constraint on the section. Merging SA then SB:
        SB's constraint names a geometry of the merged link's intersection (the slots after the
        projection's), not the equal projected line."""
        box = self.doc.addObject("Part::Box", "Upright")
        box.Placement = FreeCAD.Placement(V(20, 0, 0), FreeCAD.Rotation())
        self.doc.recompute()
        face = next(
            "Face%d" % (i + 1)
            for i, f in enumerate(box.Shape.Faces)
            if (f.CenterOfMass - V(25, 0, 5)).Length < 1e-6
        )
        sa = self.make_sketch("SA", 5)
        sa.addExternal(box.Name, face)
        sa.addGeometry(Part.LineSegment(V(40, 0, 0), V(50, 0, 0)), False)
        self.doc.recompute()
        projected = len(sa.ExternalGeo) - 2
        self.assertGreater(projected, 0)
        sb = self.make_sketch("SB", 5)
        sb.addExternal(box.Name, face, False, True)
        sb.addGeometry(Part.LineSegment(V(25, 0, 0), V(25, 5, 0)), False)
        self.doc.recompute()
        self.assertEqual(len(sb.ExternalGeo), 2 + 1)
        section = sb.ExternalGeo[2]
        # the section shares its shape with a projected line: the case M1 is about
        self.assertTrue(
            any(
                isinstance(g, Part.LineSegment)
                and (g.StartPoint - section.StartPoint).Length < 1e-7
                and (g.EndPoint - section.EndPoint).Length < 1e-7
                for g in sa.ExternalGeo[2:]
            )
        )
        sb.addConstraint(Sketcher.Constraint("PointOnObject", 0, 1, -3))
        self.doc.recompute()

        merged = self.merge(sa, sb)
        self.assertEqual(list(merged.ExternalTypes), [2])
        on_object = [c for c in merged.Constraints if c.Type == "PointOnObject"]
        self.assertEqual(len(on_object), 1)
        slot = -on_object[0].Second - 1
        self.assertGreaterEqual(slot, 2 + projected, (slot, projected))
        geo = merged.ExternalGeo[slot]
        self.assertLess((geo.StartPoint - section.StartPoint).Length, 1e-7)
        self.assertLess((geo.EndPoint - section.EndPoint).Length, 1e-7)

    # --- ops#261: Merge carries the Defining and Frozen states over ---

    def make_plain_sketch(self):
        """S2: a sketch in z = 5 with one line and no externals, merged first"""
        s2 = self.make_sketch("S2", 5)
        s2.addGeometry(Part.LineSegment(V(20, 0, 0), V(30, 0, 0)), False)
        self.doc.recompute()
        return s2

    def section_edges(self, sketch, y):
        """The edges of the sketch's Shape that are F's section at y (in the plane z = 5)"""
        ends = [(V(0, y, 5), V(10, y, 5)), (V(10, y, 5), V(0, y, 5))]
        return [
            e
            for e in sketch.Shape.Edges
            if any(
                (e.Vertexes[0].Point - a).Length < 1e-6
                and (e.Vertexes[-1].Point - b).Length < 1e-6
                for a, b in ends
            )
        ]

    def tilt_box(self, degrees):
        """Tilts the box to `degrees`; F's section in z = 5 is then at y = -5 tan(degrees)"""
        self.box.Placement = FreeCAD.Placement(V(0, 0, 0), FreeCAD.Rotation(V(1, 0, 0), degrees))
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        return -5 * math.tan(math.radians(degrees))

    def reopen_with_frozen_externals(self, sketch_name):
        """Saves the document, sets the Frozen flag of `sketch_name`'s external geometries in the
        file (there is no command for it here; files from other builds can have it), and opens
        it again. Python's copies of external geometry don't carry the flag."""
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "Frozen.FCStd")
        self.doc.saveAs(path)
        FreeCAD.closeDocument(self.doc.Name)
        with zipfile.ZipFile(path) as archive:
            entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for info, data in entries:
                if info.filename == "Document.xml":
                    data = freeze_externals(data, sketch_name)
                archive.writestr(info, data)
        self.doc = FreeCAD.openDocument(path)
        self.box = self.doc.getObject("Box")
        return self.doc.getObject(sketch_name)

    def test_merge_keeps_a_defining_external_defining(self):
        """S1 links F as a defining intersection: its Shape holds the section. Merged after S2,
        the merged Shape holds it too (the merge added every link non-defining)."""
        s1 = self.make_sketch("S1", 5)
        s1.addExternal(self.box.Name, self.face, True, True)
        s1.addGeometry(Part.LineSegment(V(5, 0, 0), V(5, 5, 0)), False)
        self.doc.recompute()
        self.assertEqual(len(self.section_edges(s1, self.section_y)), 1)
        merged = self.merge(self.make_plain_sketch(), s1)
        self.assertEqual(len(self.section_edges(merged, self.section_y)), 1)
        # S2's line, S1's line, the section
        self.assertEqual(len(merged.Shape.Edges), 3)

    def test_merge_keeps_a_non_defining_external_out_of_the_shape(self):
        """The guard: S1's section is construction, so the merged Shape doesn't hold it."""
        s1 = self.make_section_sketch()
        merged = self.merge(self.make_plain_sketch(), s1)
        self.assertEqual(self.section_edges(merged, self.section_y), [])

    def test_merge_keeps_a_frozen_link_frozen(self):
        """S1's link is frozen. After the merge, the box tilted to 45 degrees moves neither S1's
        section nor the merged one (before ops#261 the merge made it live); S1's constraint is
        on it."""
        self.make_section_sketch()
        self.make_plain_sketch()
        s1 = self.reopen_with_frozen_externals("S1")
        merged = self.merge(self.doc.getObject("S2"), s1)
        self.tilt_box(45)
        self.assert_is_section(s1.ExternalGeo[2])
        on_object = [c for c in merged.Constraints if c.Type == "PointOnObject"]
        self.assertEqual(len(on_object), 1)
        self.assert_is_section(merged.ExternalGeo[-on_object[0].Second - 1])

    def test_merge_keeps_a_frozen_link_frozen_after_other_externals(self):
        """PR 238 review L1: the first sketch S6 has its own external (an edge of the Post), so
        S1's frozen section moves to another GeoId in the merged sketch; S7 links the Post's face
        y = 0 as a live intersection. Tilting the box to 45 degrees moves neither S1's section nor
        its merged copy, which S1's constraint names; moving the Post moves the merged section of
        S7's live link."""
        post = self.doc.addObject("Part::Box", "Post")
        post.Placement = FreeCAD.Placement(V(40, 0, 0), FreeCAD.Rotation())
        self.doc.recompute()
        post_face = next(
            "Face%d" % (i + 1)
            for i, f in enumerate(post.Shape.Faces)
            if (f.CenterOfMass - V(45, 0, 5)).Length < 1e-6
        )
        self.make_section_sketch()
        s6 = self.make_sketch("S6", 5)
        s6.addExternal(post.Name, self.post_edge(post))
        s7 = self.make_sketch("S7", 5)
        s7.addExternal(post.Name, post_face, False, True)
        self.doc.recompute()
        self.assertEqual(len(s7.ExternalGeo), 2 + 1)
        s1 = self.reopen_with_frozen_externals("S1")
        post = self.doc.getObject("Post")
        merged = self.merge(self.doc.getObject("S6"), s1, self.doc.getObject("S7"))
        self.tilt_box(45)
        self.assert_is_section(s1.ExternalGeo[2])
        on_object = [c for c in merged.Constraints if c.Type == "PointOnObject"]
        self.assertEqual(len(on_object), 1)
        self.assertLessEqual(on_object[0].Second, -4)
        self.assert_is_section(merged.ExternalGeo[-on_object[0].Second - 1])
        # S7's section: the line y = 0 from x = 40 to 50; moved to y = 3 with the Post
        def post_sections(y):
            return [
                g
                for g in merged.ExternalGeo[2:]
                if isinstance(g, Part.LineSegment)
                and abs(g.StartPoint.y - y) < 1e-6
                and abs(g.EndPoint.y - y) < 1e-6
                and min(g.StartPoint.x, g.EndPoint.x) > 39
            ]
        self.assertEqual(len(post_sections(0)), 1)
        post.Placement = FreeCAD.Placement(V(40, 3, 0), FreeCAD.Rotation())
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        self.assertEqual(len(post_sections(3)), 1)
        self.assert_is_section(merged.ExternalGeo[-on_object[0].Second - 1])

    def test_merge_of_a_link_frozen_in_one_source_only_follows_the_model(self):
        """S1 has F's intersection frozen, S4 has it live: the merged link can't be both, and
        follows the model (with a message). Tilted to 45 degrees, its section is at y = -5."""
        self.make_section_sketch()
        s4 = self.make_sketch("S4", 5)
        s4.addExternal(self.box.Name, self.face, False, True)
        self.doc.recompute()
        s1 = self.reopen_with_frozen_externals("S1")
        merged = self.merge(s1, self.doc.getObject("S4"))
        y = self.tilt_box(45)
        self.assert_is_section(s1.ExternalGeo[2])
        self.assertEqual(len(merged.ExternalGeo), 2 + 1)
        self.assertAlmostEqual(merged.ExternalGeo[2].StartPoint.y, y, places=6)

    def test_merge_of_a_frozen_link_whose_source_moved(self):
        """S1's link is frozen and the box is then tilted to 45 degrees: S1 keeps the old
        section, which the merged link (at y = -5) no longer gives. S1's constraint is skipped,
        not moved, and the merged link follows the model."""
        self.make_section_sketch()
        self.make_plain_sketch()
        s1 = self.reopen_with_frozen_externals("S1")
        y = self.tilt_box(45)
        self.assert_is_section(s1.ExternalGeo[2])
        merged = self.merge(self.doc.getObject("S2"), s1)
        self.assertEqual([c for c in merged.Constraints if c.Type == "PointOnObject"], [])
        self.assertAlmostEqual(merged.ExternalGeo[2].StartPoint.y, y, places=6)
        self.tilt_box(60)
        self.assertAlmostEqual(
            merged.ExternalGeo[2].StartPoint.y, -5 * math.tan(math.radians(60)), places=6
        )


def freeze_externals(document_xml, sketch_name):
    """Sets the Frozen flag (2) of every external geometry of the object `sketch_name` in a
    Document.xml"""
    data = document_xml.index(b"<ObjectData")
    start = document_xml.index(b'<Object name="' + sketch_name.encode() + b'"', data)
    end = document_xml.find(b"<Object name=", start + 1)
    end = len(document_xml) if end < 0 else end
    part, count = re.subn(
        rb'(Ref="[^"]+" Flags=")(\d+)"',
        lambda m: m.group(1) + str(int(m.group(2)) | 2).encode() + b'"',
        document_xml[start:end],
    )
    assert count > 0, "no external geometry of %s in the file" % sketch_name
    return document_xml[:start] + part + document_xml[end:]
