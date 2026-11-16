# SPDX-License-Identifier: LGPL-2.1-or-later

"""Constraint tools as Onshape's (FreeCAD-CH, ops#640, rank 44; hands-on C-5).

- Coincident (i) on two lines makes them collinear: the second swings onto the first's line.
  FreeCAD-CH adds FreeCAD's tangency of two lines, which is that collinearity.
- Concentric is Shift+O: a circle and a point put the circle's centre on the point; two circles
  (or arcs, ellipses) share a centre.

Designed geometry, in a sketch on the XY plane:
- line 0 from (0, 0) to (10, 0), blocked, so the other geometry moves to it;
- line 1 from (2, 5) to (8, 7): collinear with line 0, both its ends lie on y = 0;
- circle 2 at (5, 5), radius 2: concentric with line 0's start (0, 0), its centre is (0, 0);
- circle 3 at (30, 30), radius 1, blocked: with circle 2 concentric, circle 2's centre is (30, 30).
"""

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

V = FreeCAD.Vector


class TestSketchConstraintToolsGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("SketchConstraintToolsGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(2, 5, 0), V(8, 7, 0)))
        self.sketch.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2))
        self.sketch.addGeometry(Part.Circle(V(30, 30, 0), V(0, 0, 1), 1))
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.sketch.addConstraint(Sketcher.Constraint("Block", 3))
        self.doc.recompute()
        FreeCADGui.getMainWindow().show()
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(200)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")

    def select(self, *subs):
        FreeCADGui.Selection.clearSelection()
        for sub in subs:
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, sub)
        self.flush_gui(50)

    def run_command(self, name):
        FreeCADGui.runCommand(name)
        self.flush_gui(100)
        self.doc.recompute()

    def constraints_of(self, kind):
        return [c for c in self.sketch.Constraints if c.Type == kind]

    def test_coincident_on_two_lines_makes_them_collinear(self):
        """Line 1 and the blocked line 0, Coincident: one Tangent (collinear) constraint, and
        line 1's ends lie on y = 0."""
        self.select("Edge2", "Edge1")
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        self.assertEqual(len(self.constraints_of("Tangent")), 1)
        self.assertEqual(len(self.constraints_of("Coincident")), 0)
        self.assertAlmostEqual(self.sketch.getPoint(1, 1).y, 0.0, places=6)
        self.assertAlmostEqual(self.sketch.getPoint(1, 2).y, 0.0, places=6)

    def test_concentric_puts_a_circle_s_centre_on_a_point(self):
        """Circle 2 and line 0's start (0, 0), Concentric: circle 2's centre is (0, 0), by one
        coincidence of its centre with the point."""
        self.select("Edge3", "Vertex1")
        self.run_command("Sketcher_ConstrainConcentric")
        coincident = self.constraints_of("Coincident")
        self.assertEqual(len(coincident), 1)
        centre = self.sketch.Geometry[2].Center
        self.assertAlmostEqual(centre.x, 0.0, places=6)
        self.assertAlmostEqual(centre.y, 0.0, places=6)

    def test_concentric_on_two_circles(self):
        """Circles 2 and 3 (blocked), Concentric: circle 2's centre is (30, 30); its radius stays."""
        self.select("Edge3", "Edge4")
        self.run_command("Sketcher_ConstrainConcentric")
        self.assertEqual(len(self.constraints_of("Coincident")), 1)
        circle = self.sketch.Geometry[2]
        self.assertAlmostEqual(circle.Center.x, 30.0, places=6)
        self.assertAlmostEqual(circle.Center.y, 30.0, places=6)
        self.assertAlmostEqual(circle.Radius, 2.0, places=6)

    def test_concentric_is_shift_o(self):
        """Onshape's key for Concentric."""
        command = FreeCADGui.Command.get("Sketcher_ConstrainConcentric")
        self.assertIsNotNone(command)
        self.assertEqual(command.getShortcut(), "Shift+O")
