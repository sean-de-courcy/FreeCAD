# SPDX-License-Identifier: LGPL-2.1-or-later

"""Carbon copy and Merge Sketches remap every element of a constraint (ops#247).

Both shifted only First/Second/Third, the legacy view of a constraint's first three elements. A
Group holds more: its later elements kept the source sketch's GeoIds and named whatever geometry
has those indices in the destination. Designed geometry: a Group of four lines; each copied
element must name a geometry equal to its source line."""

import re

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

    def merge_dest_and_source(self):
        """Merge Sketches of Dest then Source; the merged sketch."""
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.dest.Name)
        FreeCADGui.Selection.addSelection(self.doc.Name, self.source.Name)
        before = set(o.Name for o in self.doc.Objects)
        FreeCADGui.runCommand("Sketcher_MergeSketches")
        self.doc.recompute()
        merged = [o for o in self.doc.Objects if o.Name not in before]
        self.assertEqual(len(merged), 1, [o.Name for o in merged])
        return merged[0]

    def add_length(self, sketch, geo_id, name="", expression=None, path="Constraints[%d]"):
        """A driving distance on the line `geo_id` (each line here is 10 long), named and driven
        by `expression` when given; its index. An unnamed one's expression is bound by `path`:
        "Constraints[%d]" as the dimension dialog does, ".Constraints[%d]" as Python can."""
        index = sketch.addConstraint(Sketcher.Constraint("Distance", geo_id, 10))
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

    def test_merge_skips_an_expression_whose_reference_would_move(self):
        """Dest has a length named a too, so Source's a is renamed a2: Source's b, driven by
        Constraints.a, would follow Dest's a in the merged sketch. Its expression isn't copied
        (with a warning), and b keeps its value, 10."""
        self.add_length(self.dest, 0, "a", "5 + 5")
        self.add_length(self.source, 0, "a")
        self.add_length(self.source, 1, "b", "Constraints.a")
        self.doc.recompute()
        merged = self.merge_dest_and_source()
        self.assertEqual([c.Name for c in merged.Constraints], ["a", "", "a2", "b"])
        self.assertEqual(self.expressions(merged), {".Constraints.a": "5 + 5"})
        self.assertAlmostEqual(merged.getDatum("b").Value, 10, delta=1e-7)

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
