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


class ModelPicksGuiCase(SketcherGuiTestCase):
    """The designed model and the editor's helpers (TestSketchHelpersGui uses them too)."""

    def setUp(self):
        super().setUp()
        FreeCADGui.activateWorkbench("PartDesignWorkbench")
        self.doc = FreeCAD.newDocument(type(self).__name__)
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

    def click_at(self, point, modifiers=QtCore.Qt.NoModifier):
        """A left click where the world point shows, with the modifiers held."""
        at = self.screen_point(point)
        left, none = QtCore.Qt.LeftButton, QtCore.Qt.NoButton
        for kind, button, buttons in (
            (QtCore.QEvent.MouseMove, none, none),
            (QtCore.QEvent.MouseButtonPress, left, left),
            (QtCore.QEvent.MouseButtonRelease, left, none),
        ):
            event = QtGui.QMouseEvent(
                kind, at, self.viewport.mapToGlobal(at), button, buttons, modifiers
            )
            QtGui.QApplication.sendEvent(self.viewport, event)
            self.pump(80)
        self.pump(80)

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

    def report_text(self):
        """The Report view's text, or None without one."""
        for widget in FreeCADGui.getMainWindow().findChildren(QtGui.QTextEdit):
            if widget.metaObject().className() == "Gui::DockWnd::ReportOutput":
                return widget.toPlainText()
        return None

    def assertNoIllegalAccess(self, action):
        """Review prs3220-r2 (Opus) L2: a selection observer's access violation is caught and
        reported ("Illegal storage access"), not raised: read the Report view around the action."""
        before = self.report_text()
        if before is None:
            self.skipTest("no Report view to read")
        action()
        self.flush_gui(100)
        self.assertNotIn("Illegal storage access", self.report_text()[len(before) :])

    # Mouse events through the scene graph (review prs3220-r2 (Sonnet) F1). They reach the 3D view's
    # selection node before the sketch's event callback, as a real mouse's do, with no OpenGL: off
    # screen fitAll leaves the camera below the box's top, so the camera is put back above it

    def raise_camera(self):
        camera = self.view.getCameraNode()
        x, y, _ = camera.position.getValue().getValue()
        camera.position.setValue(x, y, 40.0)
        camera.nearDistance.setValue(0.0)
        camera.farDistance.setValue(100.0)
        self.pump(50)

    def coin_event(self, kind, point):
        from pivy import coin

        width, height = self.view.getSize()
        region = coin.SbViewportRegion(width, height)
        camera = self.view.getCameraNode()
        volume = camera.getViewVolume(region.getViewportAspectRatio())
        screen = volume.projectToScreen(coin.SbVec3f(point.x, point.y, point.z))
        if kind == "move":
            event = coin.SoLocation2Event()
        else:
            event = coin.SoMouseButtonEvent()
            event.setButton(coin.SoMouseButtonEvent.BUTTON1)
            event.setState(coin.SoButtonEvent.DOWN if kind == "down" else coin.SoButtonEvent.UP)
        event.setPosition(coin.SbVec2s(int(screen[0] * width), int(screen[1] * height)))
        event.setTime(coin.SbTime.getTimeOfDay())
        root = coin.SoSeparator()
        root.ref()
        root.addChild(camera)
        root.addChild(self.view.getSceneGraph())
        action = coin.SoHandleEventAction(region)
        action.setEvent(event)
        action.apply(root)
        root.unref()
        self.pump(30)

    def coin_drag(self, start, end, steps=6):
        """The left button pressed at one world point, moved in steps and released at another."""
        self.coin_event("move", start)
        self.coin_event("down", start)
        for i in range(1, steps + 1):
            self.coin_event("move", start + (end - start) * (i / steps))
        self.coin_event("up", end)
        self.flush_gui(100)

    def preselected(self):
        pre = FreeCADGui.Selection.getPreselection()
        if pre is None or not pre.ObjectName:
            return None
        return (pre.ObjectName, pre.SubElementNames[0] if pre.SubElementNames else "")


class TestSketchModelPicksGui(ModelPicksGuiCase):
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
        """Two model edges (both fixed) for Coincident: no constraint, no link, no undo step, and
        the two edges stay selected as picked (review prsd154-r1 (Opus) T2: the aborted links'
        ExternalEdge names were left selected, and the next command refused)."""
        self.start_edit()
        picks = {
            ("Pad", self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))),
            ("Pad", self.edge_between(self.pad, V(20, 0, 5), V(20, 10, 5))),
        }
        self.select(*[(self.pad, sub) for _, sub in sorted(picks)])
        self.answer_modals()
        self.assertNoIllegalAccess(lambda: self.run_command("Sketcher_ConstrainCoincidentUnified"))

        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)
        self.assertEqual(self.doc.UndoCount, self.undo_start)
        self.assertEqual(self.selected(), picks)

    def test_a_pick_that_cant_be_linked_books_nothing(self):
        """Review prsd154-r1 (Opus) T1: the line and the Body's origin point (a whole object, no
        element), then Distance: the origin isn't dropped to make the line's length; no link,
        no Distance, as before."""
        self.start_edit()
        origin_point = [f for f in self.body.Origin.OriginFeatures if f.Role == "Origin"][0]
        self.select((self.sketch, "Edge1"), (origin_point, ""))
        self.answer_modals()
        self.run_command("Sketcher_ConstrainDistance")
        self.key_click(self.viewport, QtCore.Qt.Key_Escape)
        self.flush_gui(100)

        self.assertEqual(self.constraints_of("Distance"), [])
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)

    def test_another_document_s_picks_pass_the_gate(self):
        """Review prsd154-r1 (Opus) T4: the gate is global; a face of a box in another document
        can still be selected while the sketch is edited."""
        # hidden: no view of its own, so this document's view stays the active one
        other = FreeCAD.newDocument("TestSketchModelPicksOther", hidden=True)
        try:
            other.addObject("Part::Box", "Box")
            other.recompute()
            FreeCAD.setActiveDocument(self.doc.Name)
            self.start_edit()
            FreeCADGui.Selection.addSelection(other.Name, "Box", "Face1")
            names = [
                sub for sel in FreeCADGui.Selection.getSelectionEx(other.Name)
                for sub in sel.SubElementNames
            ]
            self.assertEqual(names, ["Face1"])
        finally:
            FreeCADGui.Selection.clearSelection()
            FreeCAD.closeDocument(other.Name)

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

    def test_delete_in_another_document_is_unaffected_by_the_sketch_edit(self):
        """Review prs3220-r2 (Opus) L1: with the sketch edited here, a box's face selected in
        another (active) document, then Delete: the box goes, as with no sketch in edit."""
        other = FreeCAD.newDocument("TestSketchModelPicksOther", hidden=True)
        try:
            other.addObject("Part::Box", "Box")
            other.recompute()
            FreeCAD.setActiveDocument(self.doc.Name)
            self.start_edit()
            FreeCAD.setActiveDocument(other.Name)
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelection(other.Name, "Box", "Face1")
            self.run_command("Std_Delete")
            self.assertIsNone(other.getObject("Box"))
        finally:
            FreeCADGui.Selection.clearSelection()
            FreeCAD.setActiveDocument(self.doc.Name)
            FreeCAD.closeDocument(other.Name)

    def test_a_command_that_aborts_its_own_transaction_restores_the_picks(self):
        """Review prs3220-r2 (Opus) L3: a model vertex and a model edge (both fixed) for
        Coincident, whose point-on-object branch opens its own transaction and aborts it: no link
        is left, the picks are selected again, and two sketch lines then take Parallel."""
        self.sketch.addGeometry(Part.LineSegment(V(2, 6, 0), V(8, 7, 0)))
        self.doc.recompute()
        self.start_edit()
        picks = {
            ("Pad", self.vertex_at(self.pad, V(20, 10, 5))),
            ("Pad", self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))),
        }
        self.select(*[(self.pad, sub) for _, sub in sorted(picks)])
        self.answer_modals()
        self.assertNoIllegalAccess(lambda: self.run_command("Sketcher_ConstrainCoincidentUnified"))

        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)
        self.assertEqual(self.doc.UndoCount, self.undo_start)
        self.assertEqual(self.selected(), picks)

        self.select((self.sketch, "Edge1"), (self.sketch, "Edge2"))
        self.run_command("Sketcher_ConstrainParallel")
        self.assertEqual(len(self.constraints_of("Parallel")), 1)

    def test_a_refused_model_pick_command_keeps_a_redundant_constraint(self):
        """Review prs3220-r3s R1: with redundant constraints removed automatically, two model
        edges refused by Coincident: the sketch's two Horizontal constraints on its line both stay
        (the abort's redraw is a solve, with no removal outside a transaction), and no undo step."""
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.doc.recompute()
        had = "AutoRemoveRedundants" in self.params.GetBools()
        old = self.params.GetBool("AutoRemoveRedundants", False)
        self.params.SetBool("AutoRemoveRedundants", True)
        try:
            self.start_edit()
            self.select(
                (self.pad, self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))),
                (self.pad, self.edge_between(self.pad, V(20, 0, 5), V(20, 10, 5))),
            )
            self.answer_modals()
            self.run_command("Sketcher_ConstrainCoincidentUnified")
            self.assertEqual(len(self.constraints_of("Horizontal")), 2)
            self.assertEqual(self.doc.UndoCount, self.undo_start)
        finally:
            if had:
                self.params.SetBool("AutoRemoveRedundants", old)
            else:
                self.params.RemBool("AutoRemoveRedundants")

    def test_the_constraint_tool_whose_command_aborts_reports_no_access_violation(self):
        """Review prs3220-r3s T1: the Coincident tool, a model vertex, then a model edge (both
        fixed: the command aborts its own transaction): no link left, nothing reported."""
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.answer_modals()
        self.run_command("Sketcher_ConstrainCoincidentUnified")
        vertex = self.vertex_at(self.pad, V(20, 10, 5))
        edge = self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))

        def picks():
            FreeCADGui.Selection.addSelection(self.doc.Name, self.pad.Name, vertex)
            self.flush_gui(100)
            FreeCADGui.Selection.addSelection(self.doc.Name, self.pad.Name, edge)
            self.flush_gui(150)
            FreeCADGui.Selection.clearSelection()

        self.assertNoIllegalAccess(picks)
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)

    def test_a_pick_whose_link_fails_leaves_the_selection(self):
        """Review prs3220-r3s T2: the line, a model edge and an edge the Pad hasn't (no link):
        Coincident fails to link, and the picks stay selected. (In continuous mode, the default,
        Coincident then starts its tool on a selection that isn't the sketch's alone, and the tool
        clears it, as on integration.)"""
        had = "ContinuousConstraintMode" in self.params.GetBools()
        old = self.params.GetBool("ContinuousConstraintMode", True)
        self.params.SetBool("ContinuousConstraintMode", False)
        try:
            self.start_edit()
            edge = self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))
            self.select((self.sketch, "Edge1"), (self.pad, edge), (self.pad, "Edge99"))
            self.answer_modals()
            self.assertNoIllegalAccess(
                lambda: self.run_command("Sketcher_ConstrainCoincidentUnified")
            )
            self.assertLessEqual({("Sketch", "Edge1"), ("Pad", edge)}, self.selected())
        finally:
            if had:
                self.params.SetBool("ContinuousConstraintMode", old)
            else:
                self.params.RemBool("ContinuousConstraintMode")
        self.assertEqual(len(self.sketch.ExternalGeometry), 0)
        self.assertEqual(len(self.sketch.Constraints), 0)

    def test_a_drag_of_a_sketch_line_moves_it(self):
        """Review prs3220-r2 (Sonnet) F1: the 3D view's preselection of the box's face under the
        cursor removed the sketch's own on the first move, so a drag of the line did nothing. The
        line follows the drag, in one undo step, and nothing is selected after it."""
        self.start_edit()
        self.raise_camera()
        FreeCADGui.Selection.clearSelection()
        before = self.line_point(1)
        self.coin_drag(V(5, 2, 5), V(12, 4, 5))
        self.assertGreater((self.line_point(1) - before).Length, 1.0, "Expected the line to move")
        self.assertEqual(self.doc.UndoCount, self.undo_start + 1)

    def test_a_drag_of_a_line_end_released_over_a_model_edge_picks_nothing(self):
        """The line's end dragged onto the box's right top edge: the end moves there, and the edge
        under the release isn't picked (no model pick during a drag)."""
        self.start_edit()
        self.raise_camera()
        FreeCADGui.Selection.clearSelection()
        self.coin_drag(V(8, 2, 5), V(20, 5, 5))
        end = self.line_point(2)
        self.assertGreater((end - V(8, 2, 0)).Length, 1.0, "Expected the line's end to move")
        self.assertEqual({name for name, _ in self.selected()} - {"Sketch"}, set())

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

    # Clicks on the sketch's own elements (off screen too) --------------------------------------

    def test_ctrl_click_adds_a_sketch_element(self):
        """Review prsd154-r1 (Sonnet) F1: with the 3D view's selection on in plain edit mode, a
        Ctrl+click on a second sketch line still adds it (its release reaches the sketch)."""
        self.sketch.addGeometry(Part.LineSegment(V(2, 6, 0), V(8, 6, 0)))
        self.doc.recompute()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(5, 2, 5))
        self.assertEqual(self.selected(), {("Sketch", "Edge1")})
        self.click_at(V(5, 6, 5), QtCore.Qt.ControlModifier)
        self.assertEqual(self.selected(), {("Sketch", "Edge1"), ("Sketch", "Edge2")})

    def test_an_empty_click_clears_the_sketch_selection(self):
        """A click on no sketch element (only the box's top face, refused) clears it."""
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(5, 2, 5))
        self.assertEqual(self.selected(), {("Sketch", "Edge1")})
        self.click_at(V(14, 6, 5))
        self.assertEqual(self.selected(), set())

    def test_box_selection_stays_sketch_only(self):
        """A box from the box's top face around the sketch line selects sketch elements only."""
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.drag(V(1, 6, 5), V(9, 1, 5))
        picked = self.selected()
        self.assertIn(("Sketch", "Edge1"), picked)
        self.assertEqual({name for name, _ in picked}, {"Sketch"}, picked)

    # Clicks on model elements (skipped where the off-screen view doesn't pick) -----------------

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

    def test_a_second_click_on_a_model_pick_removes_it_with_no_rubber_band(self):
        """Review prsd154-r1 (Sonnet) F2: a click on a selected model edge removes it; the next
        click on the sketch line selects the line alone (no box left following the cursor)."""
        self.require_picking()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(15, 0, 5))
        self.assertEqual(len(self.selected()), 1)
        self.click_at(V(15, 0, 5))
        self.assertEqual(self.selected(), set())
        self.mouse_at(V(10, 5, 5))
        self.click_at(V(5, 2, 5))
        self.assertEqual(self.selected(), {("Sketch", "Edge1")})
