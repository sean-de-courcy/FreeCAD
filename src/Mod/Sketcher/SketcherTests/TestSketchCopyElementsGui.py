# SPDX-License-Identifier: LGPL-2.1-or-later

"""Carbon copy and Merge Sketches remap every element of a constraint (ops#247).

Both shifted only First/Second/Third, the legacy view of a constraint's first three elements. A
Group holds more: its later elements kept the source sketch's GeoIds and named whatever geometry
has those indices in the destination. Designed geometry: a Group of four lines; each copied
element must name a geometry equal to its source line."""

import math
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
