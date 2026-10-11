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
