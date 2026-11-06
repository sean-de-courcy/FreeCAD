# SPDX-License-Identifier: LGPL-2.1-or-later

"""Model edges and vertices picked first in the sketch editor, then a constraint (ops#634).

Onshape lets a sketch constrain to any part's edge or vertex, picked before or after the constraint
tool, and nothing is left behind once the constraint goes. FreeCAD-CH: in plain edit mode a model
edge or vertex the sketch may link is selectable (ModelPickSelection), additive like the sketch's
own picks; a select-first constraint command turns it into external geometry, and the pick and the
constraint are one undo step (a temporary booking the command's own transaction renames). A
command that makes no constraint, and a constraint tool left without one, leave no link.

Designed geometry: a 20 x 10 x 5 box Pad from the origin, and a sketch on the XY plane offset to
z 5 (the box's top) with one line from (2, 2) to (8, 2)."""

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui, QtCore, QtGui, SketcherGuiTestCase

V = FreeCAD.Vector
TOL = 1e-6
SKETCHER_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher"


class TestSketchModelPicksGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        FreeCADGui.activateWorkbench("PartDesignWorkbench")
        self.doc = FreeCAD.newDocument("TestSketchModelPicksGui")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        xy = self.body.Origin.OriginFeatures[3]

        base = self.body.newObject("Sketcher::SketchObject", "Base")
        base.AttachmentSupport = [(xy, "")]
        base.MapMode = "FlatFace"
        corners = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 10, 0)]
        for i in range(4):
            base.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            base.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        self.doc.recompute()

        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = base
        self.pad.Length = 5.0
        self.doc.recompute()

        self.sketch = self.body.newObject("Sketcher::SketchObject", "Sketch")
        self.sketch.AttachmentSupport = [(xy, "")]
        self.sketch.MapMode = "FlatFace"
        self.sketch.AttachmentOffset = FreeCAD.Placement(V(0, 0, 5), FreeCAD.Rotation())
        self.sketch.addGeometry(Part.LineSegment(V(2, 2, 0), V(8, 2, 0)))
        self.doc.recompute()
        self.answerers = []
        # the measured value stays, with no value field to answer
        self.params = FreeCAD.ParamGet(SKETCHER_PARAMS)
        self.had_dialog = "ShowDialogOnDistanceConstraint" in self.params.GetBools()
        self.old_dialog = self.params.GetBool("ShowDialogOnDistanceConstraint", True)
        self.params.SetBool("ShowDialogOnDistanceConstraint", False)

    def tearDown(self):
        for state in self.answerers:
            state["stop"] = True
        FreeCADGui.Selection.clearSelection()
        try:
            super().tearDown()
        finally:
            if self.had_dialog:
                self.params.SetBool("ShowDialogOnDistanceConstraint", self.old_dialog)
            else:
                self.params.RemBool("ShowDialogOnDistanceConstraint")

    # Geometry ----------------------------------------------------------------------------------

    def vertex_at(self, obj, point):
        for i, vertex in enumerate(obj.Shape.Vertexes):
            if vertex.Point.distanceToPoint(point) < TOL:
                return "Vertex%d" % (i + 1)
        self.fail("No vertex of %s at %s" % (obj.Name, point))

    def edge_between(self, obj, a, b):
        for i, edge in enumerate(obj.Shape.Edges):
            ends = [v.Point for v in edge.Vertexes]
            if len(ends) == 2 and (
                (ends[0].distanceToPoint(a) < TOL and ends[1].distanceToPoint(b) < TOL)
                or (ends[0].distanceToPoint(b) < TOL and ends[1].distanceToPoint(a) < TOL)
            ):
                return "Edge%d" % (i + 1)
        self.fail("No edge of %s from %s to %s" % (obj.Name, a, b))

    def line_point(self, pos):
        """The sketch line's start (1) or end (2), in sketch coordinates."""
        return self.sketch.getPoint(0, pos)

    # The editor --------------------------------------------------------------------------------

    def start_edit(self):
        FreeCADGui.getMainWindow().show()
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.pump(200)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")
        self.view = FreeCADGui.ActiveDocument.ActiveView
        self.view.viewTop()
        self.view.fitAll()
        self.flush_gui(100)
        self.viewport = self.view.graphicsView().viewport()
        # The task dialog's open transaction counts in UndoCount: read it after setEdit
        self.undo_start = self.doc.UndoCount

    def select(self, *picks):
        FreeCADGui.Selection.clearSelection()
        for obj, sub in picks:
            FreeCADGui.Selection.addSelection(self.doc.Name, obj.Name, sub)

    def selected(self):
        return {
            (sel.ObjectName, sub)
            for sel in FreeCADGui.Selection.getSelectionEx(self.doc.Name)
            for sub in sel.SubElementNames
        }

    def run_command(self, command):
        FreeCADGui.runCommand(command)
        self.flush_gui(100)

    def screen_point(self, point):
        return self.viewport_to_qpoint(self.view, self.viewport, self.view.getPointOnScreen(point))

    def answer_modals(self, timeout_ms=4000):
        """Rejects modal windows (a "Wrong selection" box) as they open, and records them."""
        state = {"seen": [], "waited": 0, "stop": False}
        self.answerers.append(state)

        def poll():
            if state["stop"]:
                return
            modal = QtGui.QApplication.activeModalWidget()
            if modal is not None and not modal.property("answeredByTest"):
                modal.setProperty("answeredByTest", True)
                state["seen"].append(modal.windowTitle())
                modal.reject()
            state["waited"] += 50
            if state["waited"] < timeout_ms:
                QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)
        return state

    def constraints_of(self, kind):
        return [c for c in self.sketch.Constraints if c.Type == kind]

    # Clicks in the 3D view ---------------------------------------------------------------------

    def require_picking(self):
        """Skips unless a click in the 3D view picks here (off screen it often doesn't): a click
        on the box's top front edge, before the editor opens."""
        FreeCADGui.getMainWindow().show()
        view = FreeCADGui.ActiveDocument.ActiveView
        view.viewTop()
        view.fitAll()
        self.flush_gui(200)
        viewport = view.graphicsView().viewport()
        at = self.viewport_to_qpoint(view, viewport, view.getPointOnScreen(V(15, 0, 5)))
        FreeCADGui.Selection.clearSelection()
        self.click(viewport, at)
        picked = self.selected()
        FreeCADGui.Selection.clearSelection()
        if not picked:
            self.skipTest("the 3D view doesn't pick here (off screen without OpenGL)")

    def mouse_at(self, point):
        self.move(self.viewport, self.screen_point(point))

    def click_at(self, point):
        at = self.screen_point(point)
        self.move(self.viewport, at)
        self.click(self.viewport, at)

    def drag(self, start, end):
        """A box drawn with the left button from one world point to another."""
        a, b = self.screen_point(start), self.screen_point(end)
        self.move(self.viewport, a)
        self.send_mouse(
            self.viewport, QtCore.QEvent.MouseButtonPress, a, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton
        )
        self.pump(60)
        for i in range(1, 6):
            step = QtCore.QPoint(a.x() + (b.x() - a.x()) * i // 5, a.y() + (b.y() - a.y()) * i // 5)
            self.send_mouse(
                self.viewport, QtCore.QEvent.MouseMove, step, QtCore.Qt.NoButton, QtCore.Qt.LeftButton
            )
            self.pump(40)
        self.send_mouse(
            self.viewport, QtCore.QEvent.MouseButtonRelease, b, QtCore.Qt.LeftButton, QtCore.Qt.NoButton
        )
        self.pump(120)

    def preselected(self):
        pre = FreeCADGui.Selection.getPreselection()
        if pre is None or not pre.ObjectName:
            return None
        return (pre.ObjectName, pre.SubElementNames[0] if pre.SubElementNames else "")

    # Tests -------------------------------------------------------------------------------------

    def test_plain_edit_takes_model_edges_and_vertices_not_faces(self):
        """In plain edit mode a model edge and vertex can be selected beside a sketch element;
        a model face can't (the gate)."""
        self.start_edit()
        edge = self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))
        vertex = self.vertex_at(self.pad, V(20, 10, 5))
        self.select((self.sketch, "Edge1"), (self.pad, edge), (self.pad, vertex), (self.pad, "Face1"))
        self.assertEqual(
            self.selected(), {("Sketch", "Edge1"), ("Pad", edge), ("Pad", vertex)}
        )

    def test_coincident_on_a_model_vertex_is_one_undo_step(self):
        """The line's end and the box's top corner, then Coincident: the end moves to (20, 10),
        one link, one undo step; undo leaves neither the constraint nor the link."""
        self.start_edit()
        self.select((self.sketch, "Vertex2"), (self.pad, self.vertex_at(self.pad, V(20, 10, 5))))
        self.run_command("Sketcher_ConstrainCoincidentUnified")

        self.assertEqual(len(self.sketch.ExternalGeometry), 1)
        self.assertEqual(len(self.constraints_of("Coincident")), 1)
        end = self.line_point(2)
        self.assertAlmostEqual(end.x, 20, places=6)
        self.assertAlmostEqual(end.y, 10, places=6)
        self.assertEqual(self.doc.UndoCount, self.undo_start + 1)

        self.doc.undo()
        self.flush_gui(100)
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)
        self.assertEqual(len(self.constraints_of("Coincident")), 0)

    def test_distance_to_a_model_edge_is_one_undo_step(self):
        """The line's start and the box's top front edge (y 0), then Distance: 2, one step."""
        self.start_edit()
        edge = self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))
        self.select((self.sketch, "Vertex1"), (self.pad, edge))
        self.run_command("Sketcher_ConstrainDistance")

        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertAlmostEqual(distances[0].Value, 2.0, places=6)
        self.assertEqual(len(self.sketch.ExternalGeometry), 1)
        self.assertEqual(self.doc.UndoCount, self.undo_start + 1)

    def test_a_refused_selection_leaves_no_link(self):
        """Two model edges (both fixed) for Coincident: no constraint, no link, no undo step."""
        self.start_edit()
        self.select(
            (self.pad, self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))),
            (self.pad, self.edge_between(self.pad, V(20, 0, 5), V(20, 10, 5))),
        )
        self.answer_modals()
        self.run_command("Sketcher_ConstrainCoincidentUnified")

        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)
        self.assertEqual(self.doc.UndoCount, self.undo_start)

    def test_a_constraint_tool_left_after_a_model_pick_leaves_no_link(self):
        """The Coincident tool, a model vertex picked (it waits for a second pick), then Esc: the
        link goes with the tool. (Distance would not do: one external edge alone is a complete
        Distance, its length.)"""
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        vertex = self.vertex_at(self.pad, V(20, 10, 5))
        FreeCADGui.Selection.addSelection(self.doc.Name, self.pad.Name, vertex)
        self.flush_gui(100)
        self.assertEqual(len(self.sketch.ExternalGeometry), 1, "Expected the tool to link the pick")
        self.assertEqual(len(self.sketch.Constraints), 0)

        self.key_click(self.viewport, QtCore.Qt.Key_Escape)
        self.flush_gui(100)
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)
        self.assertEqual(self.doc.UndoCount, self.undo_start)

    def test_delete_keeps_a_model_pick_s_object(self):
        """A model edge selected in the sketch editor, then Delete: the Pad stays."""
        self.start_edit()
        self.select((self.pad, self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))))
        self.run_command("Std_Delete")
        self.assertIsNotNone(self.doc.getObject("Pad"))

    def test_a_sibling_part_s_edge_is_taken_another_part_s_isnt(self):
        """A Body beside this one (one studio) can be picked; a Body in an App::Part can't."""
        sibling = self.doc.addObject("PartDesign::Body", "Sibling")
        box = sibling.newObject("PartDesign::AdditiveBox", "SiblingBox")
        part = self.doc.addObject("App::Part", "OtherPart")
        other = self.doc.addObject("PartDesign::Body", "Other")
        part.addObject(other)
        far = other.newObject("PartDesign::AdditiveBox", "OtherBox")
        self.doc.recompute()

        self.start_edit()
        self.select((box, "Edge1"), (far, "Edge1"))
        self.assertEqual(self.selected(), {("SiblingBox", "Edge1")})

    # Clicks (skipped where the off-screen view doesn't pick) -----------------------------------

    def test_hover_and_click_pick_a_model_edge_beside_the_sketch_selection(self):
        """Hover on the box's top front edge preselects it; a click adds it to the selected line
        end; a later click on the sketch line adds the line (no rubber band after the pick)."""
        self.require_picking()
        self.start_edit()
        edge = self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))
        self.select((self.sketch, "Vertex1"))

        self.mouse_at(V(15, 0, 5))
        self.assertEqual(self.preselected(), ("Pad", edge))
        self.click_at(V(15, 0, 5))
        self.assertEqual(self.selected(), {("Sketch", "Vertex1"), ("Pad", edge)})

        self.mouse_at(V(10, 5, 5))
        self.click_at(V(5, 2, 5))
        self.assertEqual(
            self.selected(), {("Sketch", "Vertex1"), ("Pad", edge), ("Sketch", "Edge1")}
        )

    def test_a_click_on_a_sketch_line_over_a_model_edge_is_the_sketch_s(self):
        """A sketch line on the box's top back edge (y 10): hover and click take the line, not
        the edge behind it."""
        self.sketch.addGeometry(Part.LineSegment(V(4, 10, 0), V(16, 10, 0)))
        self.doc.recompute()
        self.require_picking()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()

        self.mouse_at(V(10, 10, 5))
        pre = self.preselected()
        self.assertTrue(pre is None or pre[0] != "Pad", pre)
        self.click_at(V(10, 10, 5))
        self.assertEqual(self.selected(), {("Sketch", "Edge2")})

    def test_box_selection_stays_sketch_only(self):
        """A box from the box's top face around the sketch line selects sketch elements only."""
        self.require_picking()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.drag(V(1, 6, 5), V(9, 1, 5))
        picked = self.selected()
        self.assertIn(("Sketch", "Edge1"), picked)
        self.assertEqual({name for name, _ in picked}, {"Sketch"}, picked)

    def test_an_empty_click_clears_a_model_pick(self):
        """A model edge picked, then a click where only the box's top face (refused) lies: the
        selection is cleared, as for the sketch's own picks."""
        self.require_picking()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(15, 0, 5))
        self.assertEqual(len(self.selected()), 1)
        self.click_at(V(14, 6, 5))
        self.assertEqual(self.selected(), set())
