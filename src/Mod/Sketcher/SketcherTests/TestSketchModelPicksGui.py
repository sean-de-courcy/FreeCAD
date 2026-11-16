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
# Outside the box (whose top face is imprinted as a region of the sketch on it) and every region
OUTSIDE = V(-3, 5, 5)


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
        self.fix_view_height(self.view)
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
        if getattr(self, "corrected_points", False):
            # getPointOnScreen is off from where a click lands; corrected through the focal
            # plane as TestSketchRound3Gui's screen_point is (orthographic top view only)
            target = V(point)
            guess = V(point)
            for _ in range(20):
                hit = self.view.getPointOnFocalPlane(self.view.getPointOnScreen(guess))
                error = V(target.x - hit.x, target.y - hit.y, 0)
                if error.Length < 1e-6:
                    break
                guess += error
            point = guess
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
        a model face parallel to the sketch plane (the box's top) can't (the gate; ops#640 rank 19
        lets a perpendicular face through: TestSketchModelFacesGui)."""
        self.start_edit()
        edge = self.edge_between(self.pad, V(0, 0, 5), V(20, 0, 5))
        vertex = self.vertex_at(self.pad, V(20, 10, 5))
        top = None
        for i, face in enumerate(self.pad.Shape.Faces):
            if abs(face.BoundBox.ZMin - 5) < TOL and abs(face.BoundBox.ZMax - 5) < TOL:
                top = "Face%d" % (i + 1)
        self.assertIsNotNone(top)
        self.select((self.sketch, "Edge1"), (self.pad, edge), (self.pad, vertex), (self.pad, top))
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

    def add_rectangle(self, x0, y0, x1, y1):
        corners = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        first = len(self.sketch.Geometry)
        for i in range(4):
            self.sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            self.sketch.addConstraint(
                Sketcher.Constraint("Coincident", first + i, 2, first + (i + 1) % 4, 1)
            )
        self.doc.recompute()

    def region_at(self, x, y):
        """The sketch's InternalFaceN holding the sketch point (x, y), found geometrically."""
        for i, face in enumerate(self.sketch.InternalShape.Faces):
            if face.isInside(V(x, y, 0), TOL, True):
                return "InternalFace%d" % (i + 1)
        self.fail("No region of the sketch at (%s, %s)" % (x, y))

    def selected_regions(self):
        return {sub for name, sub in self.selected() if "InternalFace" in sub}

    def start_edit_from_above(self):
        """The editor in an orthographic top view of the box (fitAll's camera puts a click a
        millimetre or more off the point aimed at, which a region's inside doesn't need, but its
        test does)."""
        from SketcherTests.TestSketchRound3Gui import TOP_VIEW_CAMERA

        self.start_edit()
        self.view.setCamera(TOP_VIEW_CAMERA)
        self.flush_gui(100)
        self.corrected_points = True

    def test_a_click_inside_a_closed_profile_selects_its_region(self):
        """Selection parity SQ11 (oracle 8): with the sketch open, a click inside a rectangle
        selects its region; a second click there removes it, as for the sketch's other elements.
        A click outside every region (only the box's refused top face) still clears."""
        self.add_rectangle(12, 2, 18, 8)
        region = self.region_at(15, 5)
        self.start_edit_from_above()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(15, 5, 5))
        self.assertEqual(self.selected_regions(), {region}, self.selected())
        self.click_at(V(15, 5, 5))
        self.assertEqual(self.selected_regions(), set(), self.selected())
        self.click_at(V(15, 5, 5))
        self.assertEqual(self.selected_regions(), {region}, self.selected())
        self.click_at(V(10, 8, 5))
        self.assertEqual(self.selected(), set())

    def test_a_region_drawn_in_the_open_sketch_is_pickable_at_once(self):
        """A rectangle added while the sketch is open (no document recompute) is a region at once,
        as in Onshape."""
        self.start_edit_from_above()
        corners = [V(12, 2, 0), V(18, 2, 0), V(18, 8, 0), V(12, 8, 0)]
        for i in range(4):
            self.sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            self.sketch.addConstraint(Sketcher.Constraint("Coincident", 1 + i, 2, 1 + (i + 1) % 4, 1))
        self.pump(200)
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(15, 5, 5))
        self.assertEqual(len(self.selected_regions()), 1, self.selected())
        self.assertEqual(self.selected_regions(), {self.region_at(15, 5)})

    def test_a_click_on_a_region_s_side_takes_the_side_not_the_region(self):
        self.add_rectangle(12, 2, 18, 8)
        self.start_edit_from_above()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(15, 2, 5))
        self.assertEqual(self.selected(), {("Sketch", "Edge2")})

    def preselected_element(self):
        pre = self.preselected()
        return pre[1].split(".")[-1] if pre else None

    def test_hover_inside_a_closed_profile_preselects_its_region(self):
        """Polish P7 (selection parity P6, Onshape keymap): the pointer inside a rectangle, on
        none of its elements, preselects its region; on a side the side is; outside every region
        nothing is."""
        self.add_rectangle(12, 2, 18, 8)
        region = self.region_at(15, 5)
        self.start_edit_from_above()
        self.mouse_at(V(15, 5, 5))
        self.flush_gui(100)
        self.assertEqual(self.preselected_element(), region)
        self.mouse_at(V(15, 2, 5))
        self.flush_gui(100)
        self.assertEqual(self.preselected_element(), "Edge2")
        self.mouse_at(V(15, 5, 5))
        self.flush_gui(100)
        self.assertEqual(self.preselected_element(), region)
        self.mouse_at(V(6, 8, 5))
        self.flush_gui(100)
        self.assertNotEqual(self.preselected_element(), region)

    def test_freecad_keymap_tints_no_region_on_hover(self):
        """The control: FreeCAD's keymap keeps the hover on the sketch's elements only."""
        general = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General")
        saved = general.GetString("Keymap") if "Keymap" in general.GetStrings() else None
        general.SetString("Keymap", "FreeCAD")
        try:
            self.add_rectangle(12, 2, 18, 8)
            region = self.region_at(15, 5)
            self.start_edit_from_above()
            self.mouse_at(V(15, 5, 5))
            self.flush_gui(100)
            self.assertNotEqual(self.preselected_element(), region)
        finally:
            if saved is None:
                general.RemString("Keymap")
            else:
                general.SetString("Keymap", saved)

    def curve_colours(self):
        """The open sketch's curve colours, one per curve of its first layer."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setName("CurvesMaterials0")
        search.setSearchingAll(True)
        search.apply(self.view.getViewer().getSoRenderManager().getSceneGraph())
        path = search.getPath()
        self.assertIsNotNone(path, "Expected the sketch's curve materials")
        values = path.getTail().diffuseColor.getValues()
        return [tuple(round(v, 3) for v in c.getValue()) for c in values]

    def colours_at(self, point):
        self.mouse_at(point)
        self.flush_gui(100)
        return self.curve_colours()

    @staticmethod
    def changed(rest, colours):
        return {i: c for i, (r, c) in enumerate(zip(rest, colours)) if r != c}

    def test_hover_inside_a_closed_profile_turns_its_boundary_curves_hover_coloured(self):
        """Polish P7 corrected (SP10-Q1, oracle 9e): the pointer inside a rectangle turns its four
        sides the hover colour (a side's colour with the pointer on it) and no other curve; the
        region's fill is not tinted."""
        self.add_rectangle(12, 2, 18, 8)
        self.start_edit_from_above()
        rest = self.colours_at(OUTSIDE)
        side = self.changed(rest, self.colours_at(V(15, 2, 5)))
        self.assertEqual(len(side), 1, side)
        hover = next(iter(side.values()))
        inside = self.changed(rest, self.colours_at(V(15, 5, 5)))
        self.assertEqual(len(inside), 4, inside)
        self.assertEqual(set(inside.values()), {hover})
        self.assertEqual(self.changed(rest, self.colours_at(OUTSIDE)), {})

    def test_hovering_a_selected_region_changes_nothing(self):
        """SP10-Q4: a selected region hovered: no curve changes colour and the region isn't
        preselected again."""
        self.add_rectangle(12, 2, 18, 8)
        region = self.region_at(15, 5)
        self.start_edit_from_above()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(15, 5, 5))
        self.assertEqual(self.selected_regions(), {region}, self.selected())
        rest = self.colours_at(OUTSIDE)
        self.assertEqual(self.changed(rest, self.colours_at(V(15, 5, 5))), {})
        self.assertNotEqual(self.preselected_element(), region)

    def test_a_tool_shows_no_region_hover_and_ends_one_begun_before(self):
        """SP10-Q2: a hover begun before the Line tool ends when the tool starts, and with the
        tool active a region shows none."""
        self.add_rectangle(12, 2, 18, 8)
        region = self.region_at(15, 5)
        self.start_edit_from_above()
        rest = self.colours_at(OUTSIDE)
        self.assertEqual(len(self.changed(rest, self.colours_at(V(15, 5, 5)))), 4)
        self.run_command("Sketcher_CreateLine")
        self.assertEqual(self.changed(rest, self.curve_colours()), {})
        self.assertNotEqual(self.preselected_element(), region)
        self.assertEqual(self.changed(rest, self.colours_at(V(15.5, 5.5, 5))), {})
        self.assertNotEqual(self.preselected_element(), region)

    def start_3d_from_above(self):
        """The sketch closed, in an orthographic top view, the box hidden (its top face is the
        sketch's plane)."""
        from SketcherTests.TestSketchRound3Gui import TOP_VIEW_CAMERA

        FreeCADGui.getMainWindow().show()
        self.pad.Visibility = False
        self.sketch.Visibility = True
        self.doc.recompute()
        self.view = FreeCADGui.ActiveDocument.ActiveView
        self.fix_view_height(self.view)
        self.view.setCamera(TOP_VIEW_CAMERA)
        self.flush_gui(100)
        self.viewport = self.view.graphicsView().viewport()
        self.corrected_points = True

    def region_hover_curves(self):
        """How many curves the closed sketches' region hover draws."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setName("RegionHoverEdges")
        search.setInterest(coin.SoSearchAction.ALL)
        search.setSearchingAll(True)
        search.apply(self.view.getViewer().getSoRenderManager().getSceneGraph())
        paths = search.getPaths()
        count = 0
        for i in range(paths.getLength()):
            switch = paths[i].getTail()
            if switch.whichChild.getValue() == 0:
                count += switch.getChild(0).getChild(4).numVertices.getNum()
        return count

    def hover_3d(self, point):
        self.mouse_at(point)
        self.flush_gui(100)
        pre = self.preselected_element()
        if pre is None and point.x == 15:
            self.skipTest("the 3D view doesn't pick here (off screen without OpenGL)")
        return pre

    def test_hover_over_a_region_of_the_closed_sketch_draws_its_boundary_curves(self):
        """SP10-Q5: the sketch closed, the 3D view with no dialog: the pointer inside the
        rectangle preselects its region and draws its four sides in the hover colour (the fill
        isn't tinted); outside, nothing; a selected region hovered draws nothing."""
        self.add_rectangle(12, 2, 18, 8)
        region = self.region_at(15, 5)
        self.start_3d_from_above()
        self.assertEqual(self.hover_3d(V(15, 5, 5)), region)
        self.assertEqual(self.region_hover_curves(), 4)
        self.hover_3d(OUTSIDE)
        self.assertEqual(self.region_hover_curves(), 0)
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(15, 5, 5))
        self.assertTrue(
            any(sub.endswith(region) for sub in self.selected_regions()), self.selected()
        )
        self.hover_3d(OUTSIDE)
        self.hover_3d(V(15, 5, 5))
        self.assertEqual(self.region_hover_curves(), 0)

    def test_hover_over_a_region_with_an_extrude_profile_field_armed(self):
        """SP10-Q5: with a new Extrude's Profile field armed, the same hover."""
        self.add_rectangle(12, 2, 18, 8)
        region = self.region_at(15, 5)
        self.start_3d_from_above()
        self.view.setActiveObject("pdbody", self.body)
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("PartDesign_Pad")
        try:
            self.flush_gui(300)
            self.assertTrue(FreeCADGui.Control.activeDialog(), "no Extrude dialog")
            from SketcherTests.TestSketchRound3Gui import TOP_VIEW_CAMERA

            self.view.setCamera(TOP_VIEW_CAMERA)  # the dialog's opening may move the camera
            self.flush_gui(100)
            self.assertEqual(self.hover_3d(V(15, 5, 5)), region)
            self.assertEqual(self.region_hover_curves(), 4)
        finally:
            FreeCADGui.Control.closeDialog()
            self.flush_gui(100)

    def test_escape_keeps_the_selection_and_the_sketch_open(self):
        """Selection parity P7 (oracle 8, SQ7): Esc in the sketch editor with a sketch line and a
        model edge selected clears neither, and the sketch stays open (default
        LeaveSketchWithEscape off)."""
        self.require_picking()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(5, 2, 5))
        self.click_at(V(20, 5, 5), QtCore.Qt.ControlModifier)
        before = self.selected()
        self.assertIn(("Sketch", "Edge1"), before)
        self.assertGreaterEqual(len(before), 2, before)
        self.viewport.setFocus(QtCore.Qt.OtherFocusReason)
        self.pump(60)
        self.key_click(self.viewport, QtCore.Qt.Key_Escape)
        self.pump(100)
        self.assertEqual(self.selected(), before, "Esc changed the selection")
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Esc closed the sketch")

    def test_a_double_click_on_a_sketch_line_selects_nothing(self):
        """Selection parity P6 (oracle 8, SQ9): a double click on a line of a chain selects
        nothing (the fork selected the whole closed chain)."""
        self.sketch.addGeometry(Part.LineSegment(V(8, 2, 0), V(8, 6, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        self.doc.recompute()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.mouse_at(V(5, 2, 5))
        at = self.screen_point(V(5, 2, 5))
        left, none = QtCore.Qt.LeftButton, QtCore.Qt.NoButton
        for kind, button, buttons in (
            (QtCore.QEvent.MouseButtonPress, left, left),
            (QtCore.QEvent.MouseButtonRelease, left, none),
            (QtCore.QEvent.MouseButtonPress, left, left),
            (QtCore.QEvent.MouseButtonRelease, left, none),
        ):
            event = QtGui.QMouseEvent(
                kind, at, self.viewport.mapToGlobal(at), button, buttons, QtCore.Qt.NoModifier
            )
            QtGui.QApplication.sendEvent(self.viewport, event)
        self.pump(150)
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
        """Hover on the box's top right edge (x 20) preselects it; a click adds it to the selected
        line end; a later click on the sketch line adds the line (no rubber band after the pick).
        Not the top front edge: it lies under the sketch's H axis, which a click there picks."""
        self.require_picking()
        self.start_edit()
        edge = self.edge_between(self.pad, V(20, 0, 5), V(20, 10, 5))
        self.select((self.sketch, "Vertex1"))

        self.mouse_at(V(20, 5, 5))
        self.assertEqual(self.preselected(), ("Pad", edge))
        self.click_at(V(20, 5, 5))
        self.assertEqual(self.selected(), {("Sketch", "Vertex1"), ("Pad", edge)})

        self.mouse_at(V(10, 5, 5))
        self.click_at(V(5, 2, 5))
        self.assertEqual(
            self.selected(), {("Sketch", "Vertex1"), ("Pad", edge), ("Sketch", "Edge1")}
        )

    def test_a_constraint_right_after_a_model_edge_click_is_made(self):
        """Selection parity P3 (journey S3b): the line's start selected, the box's top right edge
        (x 20) clicked with Ctrl, then Point On Object with the mouse still on the edge (a key):
        the command is active, the start moves onto the edge (x 20), one link, one undo step. The
        click's release went to the 3D view's selection, so the sketch stayed in its rubber-band
        press state, and every constraint command was inactive until the mouse moved."""
        self.require_picking()
        self.start_edit()
        edge = self.edge_between(self.pad, V(20, 0, 5), V(20, 10, 5))
        self.select((self.sketch, "Vertex1"))
        self.click_at(V(20, 5, 5), QtCore.Qt.ControlModifier)
        self.assertEqual(self.selected(), {("Sketch", "Vertex1"), ("Pad", edge)})
        command = FreeCADGui.Command.get("Sketcher_ConstrainPointOnObject")
        self.assertTrue(command.isActive(), "Point On Object is inactive after the model pick")
        self.run_command("Sketcher_ConstrainPointOnObject")

        self.assertEqual(len(self.constraints_of("PointOnObject")), 1)
        self.assertEqual(len(self.sketch.ExternalGeometry), 1)
        self.assertAlmostEqual(self.line_point(1).x, 20, places=6)
        self.assertEqual(self.doc.UndoCount, self.undo_start + 1)

    def test_a_constraint_right_after_a_plain_model_edge_click_is_made(self):
        """The same with a plain click on the edge after the line's start (additive in plain
        edit mode): Point On Object is active and made."""
        self.require_picking()
        self.start_edit()
        edge = self.edge_between(self.pad, V(20, 0, 5), V(20, 10, 5))
        self.select((self.sketch, "Vertex1"))
        self.click_at(V(20, 5, 5))
        self.assertEqual(self.selected(), {("Sketch", "Vertex1"), ("Pad", edge)})
        self.assertTrue(FreeCADGui.Command.get("Sketcher_ConstrainPointOnObject").isActive())
        self.run_command("Sketcher_ConstrainPointOnObject")
        self.assertEqual(len(self.constraints_of("PointOnObject")), 1)
        self.assertAlmostEqual(self.line_point(1).x, 20, places=6)

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
        self.click_at(V(20, 5, 5))
        self.assertEqual(len(self.selected()), 1)
        self.click_at(V(14, 6, 5))
        self.assertEqual(self.selected(), set())

    def test_a_second_click_on_a_model_pick_removes_it_with_no_rubber_band(self):
        """Review prsd154-r1 (Sonnet) F2: a click on a selected model edge removes it; the next
        click on the sketch line selects the line alone (no box left following the cursor)."""
        self.require_picking()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.click_at(V(20, 5, 5))
        self.assertEqual(len(self.selected()), 1)
        self.click_at(V(20, 5, 5))
        self.assertEqual(self.selected(), set())
        self.mouse_at(V(10, 5, 5))
        self.click_at(V(5, 2, 5))
        self.assertEqual(self.selected(), {("Sketch", "Edge1")})
