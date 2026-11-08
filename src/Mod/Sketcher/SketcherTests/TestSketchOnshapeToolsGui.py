# SPDX-License-Identifier: LGPL-2.1-or-later

"""Onshape's sketch tools, round 2 (FreeCAD-CH, ops#640, the sketch area, C-tools).

- Rank 46: "Toggle Driving/Reference" acts on the selected dimensions only. With nothing selected
  it used to switch every later dimension to a reference (a sticky mode); now it changes nothing.
- Rank 43: the Dimension tool on a single sloped line gives its aligned length wherever the label
  goes (hands-on C-2); two points keep the horizontal and vertical zones.
- Rank 41: a tangent arc from the end of the last segment of a line chain (Onshape's L): Shift+A,
  back on the end and away again, or a click-drag from the end.
- Rank 42: the sketch fillet has a radius field, the last value typed is the default, and the
  fillet gets a radius dimension; the chamfer has a distance and an angle field (45 degrees).

Designed geometry, closed-form expectations:
- a line from (0, 0) to (12, 5): length 13, projections 12 and 5;
- a chain whose first segment runs from (1, 1) to (9, 1): the tangent arc to (9, 9) has its
  centre at (9, 5) and radius 4;
- a right-angle corner at (2, 2), lines to (12, 2) and (2, 12): a fillet of radius 3 has its
  centre at (5, 5) and meets the lines at (5, 2) and (2, 5); a chamfer of distance 3 at 45 degrees
  joins those points; at 30 degrees off the first line it meets the second at 3 sin 30 / sin 120
  = sqrt(3) from the corner.
"""

import math

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui, QtCore, QtGui, SketcherGuiTestCase

V = FreeCAD.Vector
SKETCHER = "User parameter:BaseApp/Preferences/Mod/Sketcher"
TOOLS = SKETCHER + "/Tools"

# A top view centred on (5, 5) of the sketch (XY plane), 30 mm high (TestDimensionInPlaceGui).
TOP_VIEW_CAMERA = """#Inventor V2.1 ascii
OrthographicCamera {
  viewportMapping ADJUST_CAMERA
  position 5 5 100
  orientation 0 0 1 0
  nearDistance 1
  farDistance 200
  aspectRatio 1
  focalDistance 100
  height 30
}
"""

# a click lands on the nearest pixel: about 0.05 mm here
CLICK_TOLERANCE = 0.15


class SketchToolsTestCase(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        if not QtGui.QFontDatabase.families():
            # off screen without QT_QPA_FONTDIR, drawing the constraint icons throws
            self.skipTest("Qt has no fonts; off screen, set QT_QPA_FONTDIR")
        self.params = []
        self.answerers = []
        self.set_param(SKETCHER, "Bool", "ContinuousCreationMode", False)
        self.set_param(SKETCHER, "Bool", "ContinuousConstraintMode", False)
        self.set_param(TOOLS, "Int", "OnViewParameterVisibility", 0)
        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.doc = FreeCAD.newDocument(type(self).__name__)
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.build()
        self.doc.recompute()

    def build(self):
        pass

    def tearDown(self):
        for state in self.answerers:
            state["stop"] = True
        FreeCADGui.Selection.clearSelection()
        try:
            super().tearDown()
        finally:
            for path, kind, name, had, value in reversed(self.params):
                group = FreeCAD.ParamGet(path)
                if had:
                    getattr(group, "Set" + kind)(name, value)
                else:
                    getattr(group, "Rem" + kind)(name)

    def set_param(self, path, kind, name, value):
        group = FreeCAD.ParamGet(path)
        had = name in getattr(group, "Get" + kind + "s")()
        old = getattr(group, "Get" + kind)(name) if had else None
        self.params.append((path, kind, name, had, old))
        getattr(group, "Set" + kind)(name, value)

    def start_edit(self):
        FreeCADGui.getMainWindow().show()
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.pump(200)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")
        self.view = FreeCADGui.ActiveDocument.ActiveView
        self.view.setCamera(TOP_VIEW_CAMERA)
        self.flush_gui(100)
        self.viewport = self.view.graphicsView().viewport()

    def screen_point(self, x, y):
        """The viewport point of sketch point (x, y), corrected until the events map it there
        (TestAutoConstraintsGui.screen_point)."""
        target = V(x, y, 0)
        guess = V(target)
        for _ in range(20):
            hit = self.view.getPointOnFocalPlane(self.view.getPointOnScreen(guess))
            error = V(target.x - hit.x, target.y - hit.y, 0)
            if error.Length < 1e-6:
                break
            guess += error
        return self.viewport_to_qpoint(self.view, self.viewport, self.view.getPointOnScreen(guess))

    def select(self, *names):
        FreeCADGui.Selection.clearSelection()
        for name in names:
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, name)

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

    def move_to(self, x, y):
        self.move(self.viewport, self.screen_point(x, y))
        self.flush_gui(60)

    def click_at(self, x, y):
        point = self.screen_point(x, y)
        self.move(self.viewport, point)
        self.click(self.viewport, point)
        self.flush_gui(100)

    def assert_near(self, actual, x, y, what, tolerance=CLICK_TOLERANCE):
        self.assertLess(
            (V(actual.x, actual.y, 0) - V(x, y, 0)).Length,
            tolerance,
            f"Expected {what} at ({x}, {y}), got {actual}",
        )


class TestSketchToggleDrivingGui(SketchToolsTestCase):
    """Rank 46. Designed geometry: a free point at (3, 7) and a line from (0, 0) to (10, 4)."""

    def build(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 4, 0)), False)
        self.sketch.addGeometry(Part.Point(V(3, 7, 0)), False)

    def lock_the_point(self):
        """Sketcher_ConstrainLock on the free point: a DistanceX and a DistanceY, driving unless
        the tool is in a reference mode (no value is asked for)."""
        self.select("Vertex3")
        FreeCADGui.runCommand("Sketcher_ConstrainLock")
        self.flush_gui(100)
        self.assertEqual(self.sketch.ConstraintCount, 2)
        return [self.sketch.getDriving(i) for i in range(2)]

    def test_nothing_selected_changes_no_mode(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        state = self.answer_modals()
        FreeCADGui.runCommand("Sketcher_ToggleDrivingConstraint")
        self.flush_gui(300)
        state["stop"] = True
        self.assertEqual(self.lock_the_point(), [True, True])

    def test_a_point_selected_changes_no_mode(self):
        """Geometry but no constraint selected: the same, no mode."""
        self.start_edit()
        self.select("Vertex1")
        state = self.answer_modals()
        FreeCADGui.runCommand("Sketcher_ToggleDrivingConstraint")
        self.flush_gui(300)
        state["stop"] = True
        self.assertEqual(self.lock_the_point(), [True, True])

    def test_a_selected_dimension_is_toggled(self):
        self.sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10.0))
        self.doc.recompute()
        self.start_edit()
        self.select("Constraint1")
        FreeCADGui.runCommand("Sketcher_ToggleDrivingConstraint")
        self.flush_gui(100)
        self.assertFalse(self.sketch.getDriving(0))
        self.select("Constraint1")
        FreeCADGui.runCommand("Sketcher_ToggleDrivingConstraint")
        self.flush_gui(100)
        self.assertTrue(self.sketch.getDriving(0))


class TestSketchSlopedLineDimensionGui(SketchToolsTestCase):
    """Rank 43. Designed geometry: line 0 from (0, 0) to (12, 5), length 13."""

    def build(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(12, 5, 0)), False)

    def dimension_with_cursor_at(self, names, x, y):
        """Starts the Dimension tool with \a names selected, moves the cursor to (x, y) and
        returns the type and value of the dimension the tool is placing."""
        self.start_edit()
        self.select(*names)
        FreeCADGui.runCommand("Sketcher_Dimension")
        self.flush_gui(150)
        self.move_to(x + 0.5, y + 0.5)
        self.move_to(x, y)
        self.assertGreater(self.sketch.ConstraintCount, 0, "Expected the tool's dimension")
        last = self.sketch.Constraints[-1]
        return last.Type, last.Value

    def test_line_below_its_span_gives_the_length(self):
        """Upstream gave DistanceX 12 here (just below the line, inside its x span)."""
        kind, value = self.dimension_with_cursor_at(["Edge1"], 6, -3)
        self.assertEqual(kind, "Distance")
        self.assertAlmostEqual(value, 13.0, places=6)

    def test_line_beside_its_span_gives_the_length(self):
        """Upstream gave DistanceY 5 here (right of the line, inside its y span)."""
        kind, value = self.dimension_with_cursor_at(["Edge1"], 15, 2.5)
        self.assertEqual(kind, "Distance")
        self.assertAlmostEqual(value, 13.0, places=6)

    def test_two_points_keep_the_horizontal_zone(self):
        """Onshape's two endpoints with the cursor below the span: horizontal (C-2)."""
        kind, value = self.dimension_with_cursor_at(["Vertex1", "Vertex2"], 6, -3)
        self.assertEqual(kind, "DistanceX")
        self.assertAlmostEqual(abs(value), 12.0, places=6)

    def test_two_points_beside_the_span_give_the_vertical(self):
        """Onshape's two endpoints with the cursor right of the span: vertical, 5 (C-2)."""
        kind, value = self.dimension_with_cursor_at(["Vertex1", "Vertex2"], 15, 2.5)
        self.assertEqual(kind, "DistanceY")
        self.assertAlmostEqual(abs(value), 5.0, places=6)

    def test_two_points_across_the_line_give_the_aligned_length(self):
        """Onshape's two endpoints with the cursor in the band perpendicular to the line (here
        up and left of the span, (-2, 6): its projection on the line falls between the ends):
        the aligned length, 13 (C-2).

        These three two-point cases are the observed ones, and upstream's rectangular zones give
        them. They do not prove the zones match Onshape's regions everywhere: Onshape's aligned
        region is the band perpendicular to the line, upstream's the bounding box's diagonals, so
        for a sloped line some cursor places differ (rare, not chased: decision 276)."""
        kind, value = self.dimension_with_cursor_at(["Vertex1", "Vertex2"], -2, 6)
        self.assertEqual(kind, "Distance")
        self.assertAlmostEqual(value, 13.0, places=6)


class TestSketchTangentArcGui(SketchToolsTestCase):
    """Rank 41. A chain from (1, 1) to (9, 1), then a tangent arc to (9, 9): centre (9, 5),
    radius 4, tangent to the line at (9, 1)."""

    def tearDown(self):
        from PySide6 import QtTest

        # a QTest press with a modifier leaves it "held" for later tests (notes/build.md)
        QtTest.QTest.keyRelease(FreeCADGui.getMainWindow().windowHandle(), QtCore.Qt.Key_Shift)
        super().tearDown()

    def start_chain(self):
        self.start_edit()
        FreeCADGui.runCommand("Sketcher_CreatePolyline")
        self.flush_gui(150)
        self.click_at(1, 1)
        self.click_at(9, 1)
        self.assertTrue(
            self.wait_until(lambda: self.sketch.GeometryCount == 1, 2000), "Expected the first line"
        )

    def finish_chain(self):
        """A right-click ends the chain; a second leaves the tool. With continuous creation off
        (setUp) the first one already leaves it, and the second opens the sketch's context menu,
        whose exec() blocks the test: a popup that opens is closed."""
        point = self.screen_point(9, 9)
        self.right_click(self.viewport, point)
        self.flush_gui(60)
        state = {"waited": 0}

        def closePopup():
            popup = QtGui.QApplication.activePopupWidget()
            if popup is not None:
                popup.close()
                return
            state["waited"] += 50
            if state["waited"] < 2000:
                QtCore.QTimer.singleShot(50, closePopup)

        QtCore.QTimer.singleShot(50, closePopup)
        self.right_click(self.viewport, point)
        self.flush_gui(150)

    def assert_tangent_arc(self):
        self.assertEqual(self.sketch.GeometryCount, 2, "Expected the line and one arc")
        arc = self.sketch.Geometry[1]
        self.assertIsInstance(arc, Part.ArcOfCircle)
        self.assert_near(arc.Center, 9, 5, "the arc's centre")
        self.assertAlmostEqual(arc.Radius, 4, delta=CLICK_TOLERANCE)
        tangents = [c for c in self.sketch.Constraints if c.Type == "Tangent"]
        self.assertTrue(tangents, "Expected the arc tangent to the line")
        self.assertEqual(self.sketch.solve(), 0)
        line = self.sketch.Geometry[0]
        # tangent at the shared end: the radius there is perpendicular to the line
        end = line.EndPoint
        radius = arc.Center - end
        direction = line.EndPoint - line.StartPoint
        self.assertAlmostEqual(radius.normalize().dot(direction.normalize()), 0, places=6)

    def test_shift_a_makes_a_tangent_arc(self):
        from PySide6 import QtTest

        self.start_chain()
        self.move_to(9, 5)
        window = FreeCADGui.getMainWindow().windowHandle()
        QtTest.QTest.keyPress(window, QtCore.Qt.Key_Shift, QtCore.Qt.ShiftModifier)
        self.key_click(self.view.graphicsView(), QtCore.Qt.Key_A, "A", QtCore.Qt.ShiftModifier)
        QtTest.QTest.keyRelease(window, QtCore.Qt.Key_Shift)
        self.flush_gui(60)
        self.click_at(9, 9)
        self.finish_chain()
        self.assert_tangent_arc()

    TOOLS = "User parameter:BaseApp/Preferences/Mod/Sketcher/Tools"

    def back_and_away(self):
        self.start_chain()
        self.move_to(12, 4)  # away from the end just clicked
        self.move_to(9, 1)  # back on it
        self.move_to(9, 3)  # and away
        self.click_at(9, 9)
        self.finish_chain()

    def test_back_on_the_end_and_away_makes_a_tangent_arc(self):
        """With the preference TangentArcByHover on (the hover form is a guess, C-3)."""
        group = FreeCAD.ParamGet(self.TOOLS)
        group.SetBool("TangentArcByHover", True)
        try:
            self.back_and_away()
        finally:
            group.RemBool("TangentArcByHover")
        self.assert_tangent_arc()

    def test_back_on_the_end_and_away_is_a_line_by_default(self):
        """The hover form is off by default: the same moves give a line."""
        FreeCAD.ParamGet(self.TOOLS).RemBool("TangentArcByHover")
        self.back_and_away()
        self.assertEqual(self.sketch.GeometryCount, 2)
        self.assertIsInstance(self.sketch.Geometry[1], Part.LineSegment)

    def test_without_the_gesture_the_chain_goes_on_with_a_line(self):
        self.start_chain()
        self.move_to(12, 4)
        self.click_at(9, 9)
        self.finish_chain()
        self.assertEqual(self.sketch.GeometryCount, 2)
        self.assertIsInstance(self.sketch.Geometry[1], Part.LineSegment)

    def test_click_drag_from_the_end_makes_a_tangent_arc(self):
        self.start_chain()
        self.move_to(12, 4)
        start = self.screen_point(9, 1)
        self.move(self.viewport, start)
        self.send_mouse(
            self.viewport, QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton
        )
        self.flush_gui(60)
        for y in (2, 4, 7, 9):
            self.send_mouse(
                self.viewport,
                QtCore.QEvent.MouseMove,
                self.screen_point(9, y),
                QtCore.Qt.NoButton,
                QtCore.Qt.LeftButton,
            )
            self.flush_gui(60)
        self.send_mouse(
            self.viewport,
            QtCore.QEvent.MouseButtonRelease,
            self.screen_point(9, 9),
            QtCore.Qt.LeftButton,
            QtCore.Qt.NoButton,
        )
        self.flush_gui(150)
        self.finish_chain()
        self.assert_tangent_arc()


class TestSketchFilletFieldsGui(SketchToolsTestCase):
    """Rank 42. Designed geometry: a right-angle corner at (2, 2), line 0 to (12, 2) and line 1 to
    (2, 12), their starts coincident."""

    def build(self):
        self.sketch.addGeometry(Part.LineSegment(V(2, 2, 0), V(12, 2, 0)), False)
        self.sketch.addGeometry(Part.LineSegment(V(2, 2, 0), V(2, 12, 0)), False)
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, 1, 1))

    def size_boxes(self):
        """The tool's visible size fields, by label: {"Radius": box} or {"Distance": .., "Angle": ..}."""
        boxes = {}
        window = FreeCADGui.getMainWindow()
        for name, label_name in (("parameterOne", "label"), ("parameterTwo", "label2")):
            for box in window.findChildren(QtGui.QAbstractSpinBox, name):
                if not box.isVisible():
                    continue
                # the label beside it, in the same tool widget (SketcherToolDefaultWidget.ui)
                labels = [
                    label
                    for label in box.parentWidget().findChildren(QtGui.QLabel, label_name)
                    if label.isVisible()
                ]
                boxes[labels[0].text() if labels else name] = box
        return boxes

    def start_tool(self, command):
        self.start_edit()
        FreeCADGui.runCommand(command)
        self.flush_gui(200)

    def corner_click(self):
        """Hovers and clicks the corner; skips where the 3D view doesn't preselect off screen."""
        self.move_to(2.3, 2.3)
        self.move_to(2, 2)
        names = []
        try:
            names = list(FreeCADGui.Selection.getPreselection().SubElementNames)
        except Exception:  # no preselection
            pass
        if not any(name.startswith("Vertex") for name in names):
            self.skipTest("the 3D view doesn't preselect here (off screen without OpenGL)")
        self.click_at(2, 2)

    def lines_ending_at(self, a, b, tolerance=1e-6):
        found = []
        for index, geo in enumerate(self.sketch.Geometry):
            if not isinstance(geo, Part.LineSegment) or self.sketch.getConstruction(index):
                continue
            ends = (geo.StartPoint, geo.EndPoint)
            for p, q in ((a, b), (b, a)):
                if (ends[0] - p).Length < tolerance and (ends[1] - q).Length < tolerance:
                    found.append(index)
        return found

    def test_the_fillet_field_shows_the_last_radius_and_keeps_a_new_one(self):
        self.set_param(TOOLS, "Float", "FilletRadius", 2.5)
        self.start_tool("Sketcher_CreateFillet")
        boxes = self.size_boxes()
        self.assertIn("Radius", boxes)
        self.assertAlmostEqual(boxes["Radius"].property("rawValue"), 2.5, places=6)
        boxes["Radius"].setProperty("rawValue", 4.0)
        self.flush_gui(50)
        self.assertAlmostEqual(FreeCAD.ParamGet(TOOLS).GetFloat("FilletRadius"), 4.0, places=6)

    def test_the_chamfer_fields(self):
        self.set_param(TOOLS, "Float", "ChamferDistance", 3.0)
        self.set_param(TOOLS, "Float", "ChamferAngle", 45.0)
        self.start_tool("Sketcher_CreateChamfer")
        boxes = self.size_boxes()
        self.assertIn("Distance", boxes)
        self.assertIn("Angle", boxes)
        self.assertAlmostEqual(boxes["Distance"].property("rawValue"), 3.0, places=6)
        self.assertAlmostEqual(boxes["Angle"].property("rawValue"), 45.0, places=6)
        boxes["Angle"].setProperty("rawValue", 30.0)
        self.flush_gui(50)
        self.assertAlmostEqual(FreeCAD.ParamGet(TOOLS).GetFloat("ChamferAngle"), 30.0, places=6)

    def arcs(self):
        return [g for g in self.sketch.Geometry if isinstance(g, Part.ArcOfCircle)]

    def test_a_vertex_fillet_has_the_radius_typed_and_a_radius_dimension(self):
        """Hands-on C-4: the corner picked is previewed (nothing made yet); Enter makes it."""
        self.set_param(TOOLS, "Float", "FilletRadius", 3.0)
        self.start_tool("Sketcher_CreateFillet")
        self.corner_click()
        self.assertEqual(self.arcs(), [], "the fillet was made before Enter (Onshape previews it)")
        self.key_click(self.viewport, QtCore.Qt.Key_Return)
        self.flush_gui(150)
        arcs = [
            (i, g) for i, g in enumerate(self.sketch.Geometry) if isinstance(g, Part.ArcOfCircle)
        ]
        self.assertEqual(len(arcs), 1, "Expected one fillet arc")
        index, arc = arcs[0]
        self.assertAlmostEqual(arc.Radius, 3.0, places=6)
        self.assert_near(arc.Center, 5, 5, "the fillet's centre", tolerance=1e-6)
        radii = [(i, c) for i, c in enumerate(self.sketch.Constraints) if c.Type == "Radius"]
        self.assertEqual(len(radii), 1, "Expected the fillet's radius dimension")
        radius_index, radius = radii[0]
        self.assertEqual(radius.First, index)
        self.assertAlmostEqual(radius.Value, 3.0, places=6)
        self.assertTrue(self.sketch.getDriving(radius_index))
        self.assertEqual(self.sketch.solve(), 0)

    def test_a_click_makes_the_previewed_fillet(self):
        """After the corner's preview, a click makes it too, at the radius typed. [guess]: hands-on
        C-4 observed Enter only; whether Onshape's click makes the previewed fillet is not known."""
        self.set_param(TOOLS, "Float", "FilletRadius", 3.0)
        self.start_tool("Sketcher_CreateFillet")
        self.corner_click()
        self.assertEqual(self.arcs(), [])
        self.click_at(6, 6)
        arcs = self.arcs()
        self.assertEqual(len(arcs), 1, "Expected one fillet arc")
        self.assertAlmostEqual(arcs[0].Radius, 3.0, places=6)

    def test_esc_drops_the_previewed_fillet(self):
        """Esc after the corner's preview makes nothing."""
        self.set_param(TOOLS, "Float", "FilletRadius", 3.0)
        self.start_tool("Sketcher_CreateFillet")
        self.corner_click()
        self.key_click(self.viewport, QtCore.Qt.Key_Escape)
        self.flush_gui(150)
        self.assertEqual(self.arcs(), [])

    def test_an_even_chamfer_has_the_distance_typed(self):
        self.set_param(TOOLS, "Float", "ChamferDistance", 3.0)
        self.set_param(TOOLS, "Float", "ChamferAngle", 45.0)
        self.start_tool("Sketcher_CreateChamfer")
        self.corner_click()
        self.assertEqual(len(self.lines_ending_at(V(5, 2, 0), V(2, 5, 0))), 1, "Expected the chamfer")
        self.assertEqual(self.sketch.solve(), 0)

    def test_an_uneven_chamfer_meets_the_second_line_by_the_angle(self):
        self.set_param(TOOLS, "Float", "ChamferDistance", 3.0)
        self.set_param(TOOLS, "Float", "ChamferAngle", 30.0)
        self.start_tool("Sketcher_CreateChamfer")
        self.corner_click()
        self.assertEqual(self.sketch.solve(), 0)
        root3 = math.sqrt(3.0)
        # the first line is the vertex's first edge, either of the two
        found = self.lines_ending_at(V(5, 2, 0), V(2, 2 + root3, 0), 1e-5) + self.lines_ending_at(
            V(2, 5, 0), V(2 + root3, 2, 0), 1e-5
        )
        self.assertEqual(len(found), 1, f"Expected the chamfer, got {self.sketch.Geometry}")
        arcs = [g for g in self.sketch.Geometry if isinstance(g, Part.ArcOfCircle)]
        self.assertEqual(arcs, [], "Expected the even chamfer's construction arc gone")
