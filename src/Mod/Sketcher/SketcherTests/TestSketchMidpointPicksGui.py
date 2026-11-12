# SPDX-License-Identifier: LGPL-2.1-or-later

"""A model edge's midpoint as a pickable point, without a drawing tool and in 3D (FreeCAD-CH,
selection parity 10, item b; Onshape's behaviour: notes/onshape-facts.md, SP10-Q6..Q11).

- In the 3D view and on a sketch's model picks, hovering a model edge within about 8 px of its
  middle shows a small marker there (SP10-Q8, Q9); a whole circle has none (Q11), and a sketch's own
  curves in edit get none (Q6).
- In plain sketch edit mode, a model edge clicked at its middle is that point: with a sketch point,
  Coincident keeps the point at the middle (Q8; stored as the drawing tools' inference stores it:
  Symmetric about a line's ends, Midpoint of an arc). Away from the middle the edge is the edge
  (Point on object), and a sketch's own line is always the line (Q6).

Designed geometry: ModelPicksGuiCase's 20 x 10 x 5 box Pad and a sketch at z 5 with the line
(2, 2)-(8, 2), seen from above in an orthographic top view (TestSketchRound3Gui's camera), so a
click lands where it is aimed."""

import math

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui
from SketcherTests.TestSketchModelPicksGui import ModelPicksGuiCase

V = FreeCAD.Vector
TOL = 1e-6


def marker_state(view):
    """(shown, point) of the midpoint marker in the view's scene graph; (False, None) without one."""
    from pivy import coin

    def find(name):
        action = coin.SoSearchAction()
        action.setName(coin.SbName(name))
        action.setInterest(coin.SoSearchAction.FIRST)
        action.setSearchingAll(True)
        action.apply(view.getSceneGraph())
        path = action.getPath()
        if path is None:
            return None
        tail = path.getTail()
        return coin.cast(tail, tail.getTypeId().getName().getString())

    switch = find("EdgeMidpointMarker")
    if switch is None:
        return (False, None)
    coordinate = find("EdgeMidpointMarkerPoint")
    point = None
    if coordinate is not None and coordinate.point.getNum() > 0:
        point = V(*coordinate.point[0].getValue())
    return (switch.whichChild.getValue() == 0, point)


class MidpointCase(ModelPicksGuiCase):
    def setUp(self):
        super().setUp()
        self.top_edge = self.edge_between(self.pad, V(0, 10, 5), V(20, 10, 5))

    def view_from_above(self):
        """The 3D view (no edit) in TestSketchRound3Gui's orthographic top view."""
        from SketcherTests.TestSketchRound3Gui import TOP_VIEW_CAMERA

        FreeCADGui.getMainWindow().show()
        self.view = FreeCADGui.ActiveDocument.ActiveView
        self.view.setCamera(TOP_VIEW_CAMERA)
        self.flush_gui(100)
        self.viewport = self.view.graphicsView().viewport()
        self.corrected_points = True

    def start_edit_from_above(self):
        """The editor in the same orthographic top view (as TestSketchModelPicksGui's)."""
        from SketcherTests.TestSketchRound3Gui import TOP_VIEW_CAMERA

        self.start_edit()
        self.view.setCamera(TOP_VIEW_CAMERA)
        self.flush_gui(100)
        self.corrected_points = True

    def assertMarkerAt(self, point):
        shown, at = marker_state(self.view)
        self.assertTrue(shown, "Expected the midpoint marker at %s" % point)
        self.assertLess((at - point).Length, 1e-4, "The marker is at %s, not %s" % (at, point))

    def assertNoMarker(self, why):
        shown, at = marker_state(self.view)
        self.assertFalse(shown, "%s (a marker shows at %s)" % (why, at))


class TestModelEdgeMidpointMarkerGui(MidpointCase):
    """SP10-Q9, Q11, Q8 and Q6: the marker on hover."""

    def test_hovering_a_model_edge_s_middle_shows_the_marker(self):
        """3D, no dialog: the box's top front edge y = 0 (x 0..20), 0.15 mm from its middle
        (about 3 px): the marker at (10, 0, 5)."""
        self.require_picking()
        self.view_from_above()
        self.mouse_at(V(10.15, 0, 5))
        self.flush_gui(100)
        self.assertEqual(self.preselected()[1] if self.preselected() else None,
                         self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5)))
        self.assertMarkerAt(V(10, 0, 5))

    def test_moving_along_the_edge_out_of_the_middle_s_radius_hides_it(self):
        """The same edge, 4 mm from its middle (about 85 px): preselected, no marker; back at
        the middle along the same edge (no new preselection): the marker."""
        self.require_picking()
        self.view_from_above()
        self.mouse_at(V(14, 0, 5))
        self.flush_gui(100)
        self.assertIsNotNone(self.preselected(), "The edge is preselected")
        self.assertNoMarker("4 mm from the middle")
        self.mouse_at(V(10.1, 0, 5))
        self.flush_gui(100)
        self.assertMarkerAt(V(10, 0, 5))
        self.mouse_at(V(30, 30, 5))
        self.flush_gui(100)
        self.assertNoMarker("The cursor left the edge")

    def test_a_whole_circle_has_no_midpoint_marker(self):
        """SP10-Q11: a cylinder r2 at (3, -6), 5 high: its top circle hovered anywhere shows none."""
        cylinder = self.doc.addObject("Part::Cylinder", "Cylinder")
        cylinder.Radius = 2
        cylinder.Height = 5
        cylinder.Placement.Base = V(3, -6, 0)
        self.doc.recompute()
        self.require_picking()
        self.view_from_above()
        for angle in (0.0, math.pi / 2, math.pi):
            self.mouse_at(V(3 + 2 * math.cos(angle), -6 + 2 * math.sin(angle), 5))
            self.flush_gui(100)
            pre = self.preselected()
            self.assertIsNotNone(pre, "The circle is preselected")
            self.assertEqual(pre[0], "Cylinder")
            self.assertNoMarker("A whole circle has no middle")

    def test_a_model_edge_s_middle_shows_the_marker_in_plain_sketch_edit(self):
        """SP10-Q8: the sketch open, no tool, the box's top back edge y = 10 at its middle."""
        self.require_picking()
        self.start_edit_from_above()
        self.mouse_at(V(10.12, 10, 5))
        self.flush_gui(100)
        self.assertMarkerAt(V(10, 10, 5))

    def test_a_sketch_s_own_line_has_no_midpoint_marker_in_edit(self):
        """SP10-Q6: the sketch's line (2, 2)-(8, 2) hovered at its middle: no marker."""
        self.require_picking()
        self.start_edit_from_above()
        self.mouse_at(V(5.05, 2, 5))
        self.flush_gui(100)
        self.assertNoMarker("A sketch's own curve has no midpoint pick")


class TestSketchModelMidpointPickGui(MidpointCase):
    """SP10-Q8 and Q6: a model edge clicked at its middle in plain edit mode, then Coincident."""

    def symmetric_about_external(self, geo, pos):
        return [
            c
            for c in self.constraints_of("Symmetric")
            if c.First <= -3 and c.Second == c.First and c.FirstPos == 1 and c.SecondPos == 2
            and c.Third == geo and c.ThirdPos == pos
        ]

    def test_coincident_with_a_model_edge_picked_at_its_middle_keeps_the_point_there(self):
        """The line's start, then the top back edge clicked 0.15 mm from its middle, then
        Coincident: the start goes to (10, 10), symmetric about the linked edge's ends, one link,
        one undo step, no Point on object."""
        self.require_picking()
        self.start_edit_from_above()
        self.select((self.sketch, "Vertex1"))
        self.click_at(V(10.15, 10, 5))
        self.assertEqual(self.selected(), {("Sketch", "Vertex1"), ("Pad", self.top_edge)})
        self.run_command("Sketcher_ConstrainCoincidentUnified")

        self.assertEqual(len(self.symmetric_about_external(0, 1)), 1, self.sketch.Constraints)
        self.assertEqual(self.constraints_of("PointOnObject"), [])
        start = self.line_point(1)
        self.assertLess((start - V(10, 10, 0)).Length, 1e-6, "The start went to the middle")
        self.assertEqual(len(self.sketch.ExternalGeometry), 1)
        self.assertEqual(self.doc.UndoCount, self.undo_start + 1)

    def test_the_middle_picked_first_then_the_point(self):
        """The same in the other order: the edge's middle clicked, then the sketch point added."""
        self.require_picking()
        self.start_edit_from_above()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(9.88, 10, 5))
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Vertex1")
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        self.assertEqual(len(self.symmetric_about_external(0, 1)), 1, self.sketch.Constraints)
        self.assertLess((self.line_point(1) - V(10, 10, 0)).Length, 1e-6)

    def test_a_model_edge_clicked_away_from_its_middle_is_point_on_object(self):
        """4 mm from the middle: the start goes onto the edge (y 10), Point on object."""
        self.require_picking()
        self.start_edit_from_above()
        self.select((self.sketch, "Vertex1"))
        self.click_at(V(14, 10, 5))
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        self.assertEqual(len(self.constraints_of("PointOnObject")), 1, self.sketch.Constraints)
        self.assertEqual(self.constraints_of("Symmetric"), [])
        self.assertAlmostEqual(self.line_point(1).y, 10, places=6)

    def test_a_sketch_line_clicked_at_its_middle_is_the_line(self):
        """SP10-Q6: a free point (5, 6), then the sketch's line clicked at its middle (5, 2),
        then Coincident: Point on object (the point onto the line), no Symmetric."""
        self.sketch.addGeometry(Part.Point(V(5, 6, 0)))
        self.doc.recompute()
        self.require_picking()
        self.start_edit_from_above()
        point = "Vertex3"  # the line's two ends are Vertex1 and Vertex2
        self.select((self.sketch, point))
        self.click_at(V(5.05, 2, 5))
        self.assertIn(("Sketch", "Edge1"), self.selected())
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        self.assertEqual(len(self.constraints_of("PointOnObject")), 1, self.sketch.Constraints)
        self.assertEqual(self.constraints_of("Symmetric"), [])


class TestSketchModelArcMidpointPickGui(MidpointCase):
    """SP10-Q8 on an arc: the box's corner (20, 10) rounded r5 (centre (15, 5)); the arc's middle
    is at 45 deg. Clicked there with the line's start, Coincident gives a Midpoint of the linked
    arc (SP10-Q12's MIDPOINT, as the drawing tools make it)."""

    CENTRE = V(15, 5, 5)

    def setUp(self):
        super().setUp()
        base = self.doc.getObject("Base")
        base.deleteAllGeometry()
        base.addGeometry(Part.LineSegment(V(0, 0, 0), V(20, 0, 0)))
        base.addGeometry(Part.LineSegment(V(20, 0, 0), V(20, 5, 0)))
        base.addGeometry(Part.ArcOfCircle(Part.Circle(V(15, 5, 0), V(0, 0, 1), 5), 0, math.pi / 2))
        base.addGeometry(Part.LineSegment(V(15, 10, 0), V(0, 10, 0)))
        base.addGeometry(Part.LineSegment(V(0, 10, 0), V(0, 0, 0)))
        for i in range(5):
            base.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 5, 1))
        self.doc.recompute()
        self.arc_edge = self.edge_between(self.pad, V(20, 5, 5), V(15, 10, 5))

    def arc_point(self, along):
        angle = math.pi / 4 + along / 5.0
        return V(self.CENTRE.x + 5 * math.cos(angle), self.CENTRE.y + 5 * math.sin(angle), 5)

    def test_coincident_with_a_model_arc_picked_at_its_middle_is_its_midpoint(self):
        self.require_picking()
        self.start_edit_from_above()
        self.select((self.sketch, "Vertex1"))
        self.click_at(self.arc_point(0.12))
        self.assertEqual(self.selected(), {("Sketch", "Vertex1"), ("Pad", self.arc_edge)})
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        midpoints = [
            c for c in self.constraints_of("Midpoint")
            if c.First == 0 and c.FirstPos == 1 and c.Second <= -3
        ]
        self.assertEqual(len(midpoints), 1, self.sketch.Constraints)
        self.assertEqual(self.constraints_of("PointOnObject"), [])
        middle = self.arc_point(0.0)
        self.assertLess((self.line_point(1) - V(middle.x, middle.y, 0)).Length, 1e-6)

    def test_hovering_the_arc_s_middle_shows_the_marker(self):
        """SP10-Q11: an open arc has a midpoint marker (3D, no dialog)."""
        self.require_picking()
        self.view_from_above()
        self.mouse_at(self.arc_point(0.1))
        self.flush_gui(100)
        self.assertMarkerAt(self.arc_point(0.0))
