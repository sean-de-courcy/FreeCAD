# SPDX-License-Identifier: LGPL-2.1-or-later

"""The sketch fillet's and chamfer's steps (FreeCAD-CH, ops#640, rank 42), without the GUI.

The Fillet tool (DrawSketchHandlerFillet.h) runs these Python calls in one transaction: fillet()
with the radius typed and then a Radius dimension on the new arc, as Onshape's sketch fillet has;
a chamfer at an angle other than the corner's even one is fillet()'s even chamfer whose
construction arc is deleted, its ends tied to the lines by Coincident, and the second line's end
moved by the solver to where the angle puts it. This replays the same calls on designed geometry.

Designed geometry: a right-angle corner at (2, 2), line 0 to (12, 2) and line 1 to (2, 12), their
starts coincident. A fillet of radius 3 has its centre at (5, 5); with the radius set to 4, at
(6, 6). A chamfer of distance 3 from the corner along line 0, at 30 degrees to it, meets line 1 at
3 sin 30 / sin(90 + 30) = sqrt(3) from the corner: it runs from (5, 2) to (2, 2 + sqrt(3)).
"""

import math
import unittest

import FreeCAD
import Part
import Sketcher

V = FreeCAD.Vector


def chamfer_sizes(distance, angle_deg, corner_deg=90.0):
    """DrawSketchHandlerFillet::chamferSizes: the even fillet's radius, and the distance along
    the second line."""
    alpha = math.radians(corner_deg)
    phi = math.radians(angle_deg)
    return distance * math.tan(alpha / 2), distance * math.sin(phi) / math.sin(alpha + phi)


class TestSketchCornerSteps(unittest.TestCase):
    def setUp(self):
        self.doc = FreeCAD.newDocument("TestSketchCornerSteps")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.LineSegment(V(2, 2, 0), V(12, 2, 0)), False)
        self.sketch.addGeometry(Part.LineSegment(V(2, 2, 0), V(2, 12, 0)), False)
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, 1, 1))
        self.doc.recompute()

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def assert_point(self, actual, x, y, places=6):
        self.assertAlmostEqual(actual.x, x, places=places)
        self.assertAlmostEqual(actual.y, y, places=places)

    def line_ends(self, index):
        line = self.sketch.Geometry[index]
        return line.StartPoint, line.EndPoint

    def assert_line_between(self, index, a, b, places=6):
        start, end = self.line_ends(index)
        if (start - V(*a, 0)).Length > (start - V(*b, 0)).Length:
            start, end = end, start
        self.assert_point(start, *a, places=places)
        self.assert_point(end, *b, places=places)

    def test_fillet_with_its_radius_dimension(self):
        highest = self.sketch.GeometryCount - 1
        self.sketch.fillet(0, 1, 3.0, True, True, False)
        arc_id = highest + 1
        arc = self.sketch.Geometry[arc_id]
        self.assertIsInstance(arc, Part.ArcOfCircle)
        self.sketch.addConstraint(Sketcher.Constraint("Radius", arc_id, arc.Radius))
        self.assertEqual(self.sketch.solve(), 0)
        arc = self.sketch.Geometry[arc_id]
        self.assertAlmostEqual(arc.Radius, 3.0, places=9)
        self.assert_point(arc.Center, 5, 5)

        # the dimension drives the fillet: radius 4, still tangent to both lines
        radius = [i for i, c in enumerate(self.sketch.Constraints) if c.Type == "Radius"][0]
        self.sketch.setDatum(radius, FreeCAD.Units.Quantity("4 mm"))
        self.assertEqual(self.sketch.solve(), 0)
        arc = self.sketch.Geometry[arc_id]
        self.assertAlmostEqual(arc.Radius, 4.0, places=6)
        self.assert_point(arc.Center, 6, 6)

    def test_even_chamfer(self):
        radius, second = chamfer_sizes(3.0, 45.0)
        self.assertAlmostEqual(second, 3.0, places=12)  # even: no uneven step
        self.sketch.fillet(0, 1, radius, True, True, True)
        self.assertEqual(self.sketch.solve(), 0)
        chamfer = self.sketch.GeometryCount - 1
        self.assertIsInstance(self.sketch.Geometry[chamfer], Part.LineSegment)
        self.assert_line_between(chamfer, (5, 2), (2, 5))

    def uneven_chamfer(self, preserve_corner):
        radius, second = chamfer_sizes(3.0, 30.0)
        self.assertAlmostEqual(second, math.sqrt(3.0), places=12)
        highest = self.sketch.GeometryCount - 1
        self.sketch.fillet(0, 1, radius, True, preserve_corner, True)
        arc_id = highest + 1
        chamfer = self.sketch.GeometryCount - 1
        self.assertIsInstance(self.sketch.Geometry[arc_id], Part.ArcOfCircle)

        # DrawSketchHandlerFillet::makeChamferUneven
        corner = V(2, 2, 0)
        on_first = V(5, 2, 0)
        on_second = V(2, 2 + second, 0)
        self.sketch.delGeometry(arc_id)
        chamfer -= 1

        def nearest_end(geo_id, point):
            start, end = self.line_ends(geo_id)
            return 1 if (start - point).Length <= (end - point).Length else 2

        chamfer_at_first = nearest_end(chamfer, on_first)
        chamfer_at_second = 2 if chamfer_at_first == 1 else 1
        self.sketch.addConstraint(
            Sketcher.Constraint("Coincident", 0, nearest_end(0, corner), chamfer, chamfer_at_first)
        )
        self.sketch.addConstraint(
            Sketcher.Constraint("Coincident", 1, nearest_end(1, corner), chamfer, chamfer_at_second)
        )
        self.sketch.moveGeometry(1, nearest_end(1, corner), on_second, False)
        self.assertEqual(self.sketch.solve(), 0)

        self.assert_line_between(chamfer, (5, 2), (2, 2 + second), places=5)
        # the lines stay on their lines, trimmed to the chamfer
        self.assert_line_between(0, (5, 2), (12, 2), places=5)
        self.assert_line_between(1, (2, 2 + second), (2, 12), places=5)
        self.assertEqual(
            [g for g in self.sketch.Geometry if isinstance(g, Part.ArcOfCircle)], []
        )
        # the angle to the first line is the one typed
        start, end = self.line_ends(chamfer)
        along = (end - start) if start.y < end.y else (start - end)
        self.assertAlmostEqual(math.degrees(math.atan2(along.y, -along.x)), 30.0, places=4)

    def test_uneven_chamfer_without_the_corner(self):
        self.uneven_chamfer(False)

    def test_uneven_chamfer_keeping_the_corner(self):
        self.uneven_chamfer(True)
