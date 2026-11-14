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
        self.fix_view_height(self.view)
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
                # the label beside it, in the same tool widget (SketcherToolDefaultWidget.ui).
                # The tool widget's wrapper is held while its labels are used: a temporary one
                # takes the labels' wrappers with it when it goes ("Internal C++ object (QLabel)
                # already deleted")
                tool_widget = box.parentWidget()
                labels = [
                    label
                    for label in tool_widget.findChildren(QtGui.QLabel, label_name)
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


class TestSketchSplitCircleGui(SketchToolsTestCase):
    """ops#656 F3 (Onshape SK11): Split takes two clicks on a whole circle and leaves two arcs that
    stay one closed circle. Designed geometry: a circle of radius 5 centred on (5, 5); the clicks at
    (10, 5) and (0, 5) give two half circles."""

    def build(self):
        self.sketch.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 5), False)

    def click_on_edge(self, x, y):
        """Hovers and clicks the circle at (x, y); skips where the 3D view doesn't preselect off screen."""
        self.move_to(x + 0.3, y)
        self.move_to(x, y)
        names = []
        try:
            names = list(FreeCADGui.Selection.getPreselection().SubElementNames)
        except Exception:  # no preselection
            pass
        if not any(name.startswith("Edge") for name in names):
            self.skipTest("the 3D view doesn't preselect here (off screen without OpenGL)")
        self.click_at(x, y)

    def test_two_clicks_split_a_circle_into_two_closed_arcs(self):
        modals = self.answer_modals()
        self.start_edit()
        FreeCADGui.runCommand("Sketcher_Split")
        self.flush_gui(200)
        self.click_on_edge(10, 5)
        self.assertEqual(len(self.sketch.Geometry), 1, "the first click on a circle splits nothing")
        self.assertIsInstance(self.sketch.Geometry[0], Part.Circle)
        self.click_on_edge(0, 5)
        arcs = [g for g in self.sketch.Geometry if isinstance(g, Part.ArcOfCircle)]
        self.assertEqual(len(arcs), 2, f"Expected two arcs, got {self.sketch.Geometry}")
        a, b = arcs
        for arc in arcs:
            self.assertAlmostEqual(arc.Radius, 5, places=6)
            self.assert_near(arc.Center, 5, 5, "the arc's centre", 1e-6)
        self.assertLess((a.EndPoint - b.StartPoint).Length, 1e-6)
        self.assertLess((b.EndPoint - a.StartPoint).Length, 1e-6)
        ends = sorted(round(p.x, 3) for p in (a.StartPoint, a.EndPoint))
        self.assertEqual(ends, [0.0, 10.0], "Expected the cuts at the two clicks")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertEqual(modals["seen"], [])


class SketchSplitTestCase(SketchToolsTestCase):
    """Sketcher 3 (Ward's hand-check 6, Onshape SK11): helpers for the Split tool's picks."""

    def start_split(self):
        self.modals = self.answer_modals()
        self.start_edit()
        FreeCADGui.runCommand("Sketcher_Split")
        self.flush_gui(200)

    def trace(self, *points):
        """Moves the cursor through sketch points, as a hand approaching a pick along a curve."""
        for x, y in points:
            self.move_to(x, y)

    def preselected(self):
        try:
            return list(FreeCADGui.Selection.getPreselection().SubElementNames)
        except Exception:  # no preselection
            return []

    def require_preselection(self):
        if not self.preselected():
            self.skipTest("the 3D view doesn't preselect here (off screen without OpenGL)")

    def hint(self):
        """The status bar's text (the tool's hint line included)."""
        bar = FreeCADGui.getMainWindow().statusBar()
        labels = bar.findChildren(QtGui.QLabel)
        return " ".join([bar.currentMessage()] + [w.text() for w in labels])

    def markers(self):
        """The edit markers the tool draws, as sketch points."""
        from pivy import coin

        root = self.view.getViewer().getSoRenderManager().getSceneGraph()
        search = coin.SoSearchAction()
        search.setName("EditMarkersCoordinate")
        search.setSearchingAll(True)
        search.apply(root)
        path = search.getPath()
        self.assertIsNotNone(path, "Expected the edit markers in the scene graph")
        return [V(p[0], p[1], 0) for p in path.getTail().point.getValues()]

    def has_marker(self, x, y, tolerance=1e-6):
        return any((m - V(x, y, 0)).Length < tolerance for m in self.markers())

    def cursor_forbidden(self):
        widgets = [self.view.graphicsView(), self.viewport]
        return any(w.cursor().shape() == QtCore.Qt.ForbiddenCursor for w in widgets)

    def lines(self):
        return [g for g in self.sketch.Geometry if isinstance(g, Part.LineSegment)]

    def arcs(self):
        return [g for g in self.sketch.Geometry if isinstance(g, Part.ArcOfCircle)]

    def has_line(self, a, b, tolerance=1e-9):
        for line in self.lines():
            s, e = line.StartPoint, line.EndPoint
            if ((s - a).Length < tolerance and (e - b).Length < tolerance) or (
                (s - b).Length < tolerance and (e - a).Length < tolerance
            ):
                return True
        return False


class TestSketchSplitCirclePicksGui(SketchSplitTestCase):
    """Onshape SK11, SK16 and Ward's hand-check 6: the first pick on a whole circle is shown and
    waits; meanwhile another curve doesn't preselect and a click on it does nothing (no message), the
    first pick staying; Esc drops the pending pick and leaves the tool in one press. Designed geometry: a circle of radius 5 centred on (5, 5) and a line
    x = 12 (y 0..10), 2 mm right of the circle; the picks at (10, 5) and (0, 5) give two half
    circles."""

    def build(self):
        self.sketch.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 5), False)
        self.sketch.addGeometry(Part.LineSegment(V(12, 0, 0), V(12, 10, 0)), False)

    def pick_circle(self, x, y):
        self.move_to(x + 0.3, y)
        self.move_to(x, y)
        self.require_preselection()
        self.click_at(x, y)

    def assert_halves_at(self, xs):
        arcs = self.arcs()
        self.assertEqual(len(arcs), 2, f"Expected two arcs, got {self.sketch.Geometry}")
        # a pick off an intersection lands on the cursor's pixel
        ends = sorted(p.x for p in (arcs[0].StartPoint, arcs[0].EndPoint))
        for end, x in zip(ends, xs):
            self.assertAlmostEqual(end, x, delta=CLICK_TOLERANCE, msg=f"Expected the cuts at {xs}, got {ends}")
        self.assertLess((arcs[0].EndPoint - arcs[1].StartPoint).Length, 1e-6, "Expected the arcs joined")
        self.assertLess((arcs[1].EndPoint - arcs[0].StartPoint).Length, 1e-6, "Expected the arcs joined")
        self.assertTrue(self.has_line(V(12, 0, 0), V(12, 10, 0)), "Expected the line whole")

    def test_the_first_pick_is_shown_until_the_second(self):
        self.start_split()
        self.pick_circle(10, 5)
        self.assertEqual(len(self.sketch.Geometry), 2, "the first pick on a circle splits nothing")
        # the point is shown on the circle (snapped onto it, not the cursor's pixel)
        self.assertTrue(
            any(abs((m - V(5, 5, 0)).Length - 5) < 1e-6 and (m - V(10, 5, 0)).Length < 0.2
                for m in self.markers()),
            f"Expected a marker at the first pick, got {self.markers()}",
        )
        self.assertIn("second point", self.hint())
        self.pick_circle(0, 5)
        self.assert_halves_at([0.0, 10.0])
        self.assertFalse(
            any((m - V(10, 5, 0)).Length < 0.2 for m in self.markers()),
            "Expected the first pick's marker gone after the split",
        )
        self.assertEqual(self.modals["seen"], [])

    def test_a_second_pick_on_another_curve_does_nothing_and_the_first_stays(self):
        self.start_split()
        self.pick_circle(10, 5)
        self.trace((12.3, 3), (12, 3))
        self.assertFalse(
            any("Edge2" in name for name in self.preselected()), "Expected the line not to preselect"
        )
        self.click_at(12, 3)
        self.assertEqual(len(self.sketch.Geometry), 2, "Expected the line not split")
        self.assertTrue(self.has_line(V(12, 0, 0), V(12, 10, 0)), "Expected the line whole")
        self.assertNotIn("same circle", self.hint(), "Expected no message (Onshape SK16)")
        self.assertIn("second point", self.hint(), "Expected the first pick still pending")
        self.pick_circle(0, 5)
        self.assert_halves_at([0.0, 10.0])
        self.assertEqual(self.modals["seen"], [])

    def test_escape_drops_the_pending_pick_and_leaves_the_tool(self):
        self.start_split()
        self.pick_circle(10, 5)
        self.key_click(self.viewport, QtCore.Qt.Key_Escape)
        self.flush_gui(100)
        self.assertNotIn("second point", self.hint(), "Expected the pending pick dropped")
        self.assertNotIn("edge to split", self.hint(), "Expected the Split tool left (Onshape SK16)")
        # no tool: two clicks on the circle split nothing
        self.pick_circle(0, 5)
        self.pick_circle(10, 5)
        self.assertEqual(len(self.sketch.Geometry), 2, "Expected nothing split after Esc")
        self.assertEqual(self.modals["seen"], [])


class TestSketchSplitIntersectionGui(SketchSplitTestCase):
    """Ward's hand-check 6: Onshape picks the intersection of two curves easily and splits the
    curve the cursor traced on the way in; FreeCAD showed a "no" cursor there. Designed geometry,
    built per test: two lines crossing at (5, 5); a line y = 5 through a circle of radius 3 centred
    on (5, 5) (crossings at (2, 5) and (8, 5)); an upper half arc of radius 3 centred on (5, 5)
    whose end (2, 5) lies inside the line y = 5 (x 0..4), square to it. Cuts are expected exactly at the
    intersection, not at the cursor's pixel."""

    def add(self, *geometry):
        for g in geometry:
            self.sketch.addGeometry(g, False)
        self.doc.recompute()

    def test_crossing_lines_split_the_line_traced_on_the_way_in(self):
        self.add(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), Part.LineSegment(V(5, 0, 0), V(5, 10, 0)))
        self.start_split()
        self.trace((2, 5), (3.5, 5), (4.5, 5), (4.9, 5))
        self.require_preselection()
        self.move_to(5.04, 5.04)
        self.assertTrue(self.has_marker(5, 5), f"Expected the crossing shown, got {self.markers()}")
        self.assertFalse(self.cursor_forbidden(), "Expected no 'no' cursor at the crossing")
        self.click_at(5.04, 5.04)
        self.assertEqual(len(self.lines()), 3, f"Expected one line split, got {self.sketch.Geometry}")
        self.assertTrue(self.has_line(V(0, 5, 0), V(5, 5, 0)), "Expected y = 5 cut at x = 5")
        self.assertTrue(self.has_line(V(5, 5, 0), V(10, 5, 0)), "Expected y = 5 cut at x = 5")
        self.assertTrue(self.has_line(V(5, 0, 0), V(5, 10, 0)), "Expected x = 5 whole")
        self.assertEqual(self.modals["seen"], [])

    def test_crossing_lines_approached_along_the_other_split_that_one(self):
        self.add(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), Part.LineSegment(V(5, 0, 0), V(5, 10, 0)))
        self.start_split()
        self.trace((5, 2), (5, 3.5), (5, 4.5), (5, 4.9))
        self.require_preselection()
        self.click_at(5.04, 5.04)
        self.assertEqual(len(self.lines()), 3, f"Expected one line split, got {self.sketch.Geometry}")
        self.assertTrue(self.has_line(V(5, 0, 0), V(5, 5, 0)), "Expected x = 5 cut at y = 5")
        self.assertTrue(self.has_line(V(5, 5, 0), V(5, 10, 0)), "Expected x = 5 cut at y = 5")
        self.assertTrue(self.has_line(V(0, 5, 0), V(10, 5, 0)), "Expected y = 5 whole")

    def test_a_line_through_a_circle_splits_the_line_traced(self):
        self.add(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), Part.Circle(V(5, 5, 0), V(0, 0, 1), 3))
        self.start_split()
        self.trace((0.5, 5), (1.2, 5), (1.8, 5))
        self.require_preselection()
        self.click_at(2.04, 5.03)
        self.assertTrue(self.has_line(V(0, 5, 0), V(2, 5, 0)), "Expected the line cut at x = 2")
        self.assertTrue(self.has_line(V(2, 5, 0), V(10, 5, 0)), "Expected the line cut at x = 2")
        circles = [g for g in self.sketch.Geometry if isinstance(g, Part.Circle)]
        self.assertEqual(len(circles), 1, "Expected the circle whole")

    def test_a_circle_traced_to_both_crossings_splits_there(self):
        self.add(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), Part.Circle(V(5, 5, 0), V(0, 0, 1), 3))
        self.start_split()

        def on_circle(degrees):
            a = math.radians(degrees)
            return (5 + 3 * math.cos(a), 5 + 3 * math.sin(a))

        self.trace(on_circle(130), on_circle(150), on_circle(170))
        self.require_preselection()
        self.click_at(2.03, 5.04)
        self.assertTrue(self.has_marker(2, 5), f"Expected the first pick at (2, 5), got {self.markers()}")
        self.trace(on_circle(-30), on_circle(-15), on_circle(-6))
        self.click_at(7.97, 4.96)
        arcs = self.arcs()
        self.assertEqual(len(arcs), 2, f"Expected two arcs, got {self.sketch.Geometry}")
        for arc in arcs:
            for p in (arc.StartPoint, arc.EndPoint):
                self.assertTrue(
                    (p - V(2, 5, 0)).Length < 1e-9 or (p - V(8, 5, 0)).Length < 1e-9,
                    f"Expected the cuts at the crossings, got {p}",
                )
        self.assertTrue(self.has_line(V(0, 5, 0), V(10, 5, 0)), "Expected the line whole")
        # Onshape SK15: each new end on the line it lies on
        line = next(i for i, g in enumerate(self.sketch.Geometry) if isinstance(g, Part.LineSegment))
        on_line = [c for c in self.sketch.Constraints if c.Type == "PointOnObject" and c.Second == line]
        self.assertEqual(len(on_line), 2, f"Expected both cuts on the line, got {self.constraints()}")
        self.assertEqual(self.sketch.solve(), 0)

    def constraints(self):
        return [(c.Type, c.First, c.FirstPos, c.Second, c.SecondPos) for c in self.sketch.Constraints]

    def test_a_split_at_a_crossing_puts_the_new_end_on_the_other_line(self):
        """Onshape SK14 (S1b): A (0,5)-(10,5) split at its crossing with B (3,0)-(3,8): the new end
        on B (point on line), the pieces joined in line, B whole."""
        self.add(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), Part.LineSegment(V(3, 0, 0), V(3, 8, 0)))
        self.start_split()
        self.trace((0.5, 5), (1.5, 5), (2.5, 5), (2.9, 5))
        self.require_preselection()
        self.click_at(3.04, 5.03)
        self.assertTrue(
            self.has_line(V(0, 5, 0), V(3, 5, 0)), f"Expected A cut at x = 3: {self.sketch.Geometry}"
        )
        self.assertTrue(self.has_line(V(3, 0, 0), V(3, 8, 0)), "Expected B whole")
        b = next(
            i for i, g in enumerate(self.sketch.Geometry)
            if isinstance(g, Part.LineSegment)
            and abs(g.StartPoint.x - 3) < 1e-9 and abs(g.EndPoint.x - 3) < 1e-9
        )
        on_b = [c for c in self.sketch.Constraints if c.Type == "PointOnObject" and c.Second == b]
        self.assertEqual(len(on_b), 1, f"Expected the new end on B, got {self.constraints()}")
        self.assertEqual(self.sketch.solve(), 0)
        self.assertEqual(self.modals["seen"], [])

    def test_a_split_at_a_line_midpoint_keeps_the_halves_equal(self):
        """Onshape SK14 (S1): a split at a crossing that is also the line's midpoint gets a midpoint
        tie instead of the one with the other line (here the two halves equal), with no redundancy."""
        self.add(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), Part.LineSegment(V(5, 0, 0), V(5, 10, 0)))
        self.start_split()
        self.trace((2, 5), (3.5, 5), (4.5, 5), (4.9, 5))
        self.require_preselection()
        self.click_at(5.04, 5.04)
        self.assertTrue(self.has_line(V(0, 5, 0), V(5, 5, 0)), "Expected y = 5 cut at x = 5")
        types = [c.Type for c in self.sketch.Constraints]
        self.assertIn("Equal", types, f"Expected the halves equal, got {self.constraints()}")
        self.assertNotIn("PointOnObject", types, f"Expected no tie with x = 5, got {self.constraints()}")
        self.assertEqual(self.sketch.solve(), 0)

    def test_a_shared_corner_splits_nothing_and_says_nothing(self):
        """Onshape SK18 (S4): P (0,0)-(5,5) and Q (5,5)-(10,0) share (5,5): a click there along P
        does nothing, with no message."""
        self.add(Part.LineSegment(V(0, 0, 0), V(5, 5, 0)), Part.LineSegment(V(5, 5, 0), V(10, 0, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        self.doc.recompute()
        self.start_split()
        self.trace((3, 3), (4, 4), (4.7, 4.7))
        self.require_preselection()
        self.move_to(5.0, 5.0)
        self.assertFalse(self.cursor_forbidden(), "Expected no 'no' cursor at the corner")
        self.click_at(5.0, 5.0)
        self.assertEqual(len(self.sketch.Geometry), 2, "Expected nothing split at the corner")
        self.assertNotIn("Nothing to split", self.hint(), "Expected no message (Onshape SK18)")
        self.assertNotIn("Cannot split", self.hint(), "Expected no message (Onshape SK18)")
        self.assertEqual(self.modals["seen"], [])

    def test_a_b_spline_knot_splits_there(self):
        """A knot of a B-spline (poles (0, 0) (3, 6) (6, 0) (9, 6) (12, 0), degree 3, one inner knot
        at u = 1) splits the B-spline exactly at the knot, as before."""
        spline = Part.BSplineCurve()
        poles = [V(0, 0, 0), V(3, 6, 0), V(6, 0, 0), V(9, 6, 0), V(12, 0, 0)]
        spline.buildFromPolesMultsKnots(poles, [4, 1, 4], [0, 1, 2], False, 3)
        knot = spline.value(1)
        self.add(spline)
        self.sketch.exposeInternalGeometry(0)
        self.doc.recompute()
        self.start_split()
        self.trace((knot.x + 1.5, knot.y + 1.5), (knot.x + 0.04, knot.y + 0.03))
        self.require_preselection()
        self.click_at(knot.x + 0.04, knot.y + 0.03)
        pieces = [g for g in self.sketch.Geometry if isinstance(g, Part.BSplineCurve)]
        self.assertEqual(len(pieces), 2, f"Expected two B-splines, got {self.sketch.Geometry}")
        ends = [p for g in pieces for p in (g.StartPoint, g.EndPoint)]
        self.assertTrue(
            any((p - knot).Length < 1e-9 for p in ends), f"Expected a cut at the knot {knot}, got {ends}"
        )
        self.assertEqual(self.modals["seen"], [])

    def arc_on_a_line(self):
        self.add(
            Part.ArcOfCircle(Part.Circle(V(5, 5, 0), V(0, 0, 1), 3), 0, math.pi),
            Part.LineSegment(V(0, 5, 0), V(4, 5, 0)),
        )

    def test_an_arc_end_inside_a_line_splits_the_line_traced(self):
        self.arc_on_a_line()
        self.start_split()
        self.trace((0.3, 5), (1.0, 5), (1.6, 5))
        self.require_preselection()
        self.move_to(2.03, 4.97)
        self.assertFalse(self.cursor_forbidden(), "Expected no 'no' cursor at the arc's end")
        self.click_at(2.03, 4.97)
        self.assertTrue(self.has_line(V(0, 5, 0), V(2, 5, 0)), "Expected the line cut at x = 2")
        self.assertTrue(self.has_line(V(2, 5, 0), V(4, 5, 0)), "Expected the line cut at x = 2")
        self.assertEqual(len(self.arcs()), 1, "Expected the arc whole")
        self.assertEqual(self.modals["seen"], [])

    def test_an_arc_traced_to_its_own_end_is_refused_there(self):
        self.arc_on_a_line()
        self.start_split()

        def on_arc(degrees):
            a = math.radians(degrees)
            return (5 + 3 * math.cos(a), 5 + 3 * math.sin(a))

        self.trace(on_arc(150), on_arc(165), on_arc(172))
        self.require_preselection()
        self.click_at(2.0, 5.0)
        # Onshape SK17 splits the arc at its end, leaving a zero-length arc; FreeCAD can't make
        # one, so this one case is refused, loudly
        self.assertEqual(len(self.sketch.Geometry), 2, "Expected nothing split at the arc's own end")
        self.assertIn(
            "Cannot split a curve at its own end", self.hint(), "Expected the refusal in the hint line"
        )
        self.assertEqual(self.modals["seen"], [])


class TestSketchTrimCrossingGui(SketchSplitTestCase):
    """Onshape SK19, SK20, SK22 (S2b): Trim doesn't follow the traced curve at a crossing: a click
    at either crossing of the line y = 5 (x 0..10) with a circle of radius 3 centred on (5, 5), along
    the line or along the circle, trims the circle's upper arc, the line staying whole; the cursor
    rests on the crossing with the normal cursor. Away from crossings Trim trims the piece under the
    cursor, as before. On the line's free end (SK24) it shows no "no" cursor and trims the line's
    piece there."""

    def build(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), False)
        self.sketch.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 3), False)

    def start_trim(self):
        self.modals = self.answer_modals()
        self.start_edit()
        FreeCADGui.runCommand("Sketcher_Trimming")
        self.flush_gui(200)

    def test_a_click_at_the_crossing_along_the_line_trims_the_circles_upper_arc(self):
        self.start_trim()
        self.trace((0.5, 5), (1.2, 5), (1.8, 5))
        self.require_preselection()
        self.move_to(2.03, 5.0)
        self.assertFalse(self.cursor_forbidden(), "Expected no 'no' cursor at the crossing")
        self.assertTrue(self.has_marker(8, 5), f"Expected the circle's piece shown, got {self.markers()}")
        self.click_at(2.03, 5.0)
        self.assertTrue(
            self.has_line(V(0, 5, 0), V(10, 5, 0)), f"Expected the line whole: {self.sketch.Geometry}"
        )
        arcs = self.arcs()
        self.assertEqual(len(arcs), 1, f"Expected the circle trimmed to one arc, got {self.sketch.Geometry}")
        mid = arcs[0].value((arcs[0].FirstParameter + arcs[0].LastParameter) / 2)
        self.assertLess(mid.y, 5, f"Expected the lower arc kept, got {arcs[0]}")
        for p in (arcs[0].StartPoint, arcs[0].EndPoint):
            self.assertTrue(
                (p - V(2, 5, 0)).Length < 1e-9 or (p - V(8, 5, 0)).Length < 1e-9,
                f"Expected the arc's ends at the crossings, got {p}",
            )
        self.assertEqual(self.modals["seen"], [])

    def assert_upper_arc_trimmed(self):
        self.assertTrue(
            self.has_line(V(0, 5, 0), V(10, 5, 0)), f"Expected the line whole: {self.sketch.Geometry}"
        )
        arcs = self.arcs()
        self.assertEqual(len(arcs), 1, f"Expected the circle trimmed to one arc, got {self.sketch.Geometry}")
        mid = arcs[0].value((arcs[0].FirstParameter + arcs[0].LastParameter) / 2)
        self.assertLess(mid.y, 5, f"Expected the lower arc kept, got {arcs[0]}")

    def test_the_right_crossing_along_the_line_also_trims_the_upper_arc(self):
        """SK22: (8, 5) approached along the line from the right."""
        self.start_trim()
        self.trace((9.5, 5), (8.8, 5), (8.2, 5))
        self.require_preselection()
        self.click_at(7.97, 5.0)
        self.assert_upper_arc_trimmed()
        self.assertEqual(self.modals["seen"], [])

    def test_the_crossing_along_the_circle_trims_the_upper_arc(self):
        """SK20: (2, 5) approached along the circle's upper arc."""
        self.start_trim()

        def on_circle(degrees):
            a = math.radians(degrees)
            return (5 + 3 * math.cos(a), 5 + 3 * math.sin(a))

        self.trace(on_circle(140), on_circle(160), on_circle(172))
        self.require_preselection()
        self.click_at(2.0, 5.03)
        self.assert_upper_arc_trimmed()
        self.assertEqual(self.modals["seen"], [])

    def test_away_from_the_crossing_the_piece_under_the_cursor_is_trimmed(self):
        self.start_trim()
        self.trace((0.3, 5), (0.7, 5), (1.0, 5))
        self.require_preselection()
        self.click_at(1.0, 5.0)
        self.assertTrue(
            self.has_line(V(2, 5, 0), V(10, 5, 0)),
            f"Expected the line's left piece gone: {self.sketch.Geometry}",
        )
        circles = [g for g in self.sketch.Geometry if isinstance(g, Part.Circle)]
        self.assertEqual(len(circles), 1, "Expected the circle whole")

    def test_a_free_end_shows_no_forbidden_cursor_and_trims_its_piece(self):
        self.start_trim()
        self.trace((1.0, 5), (0.4, 5), (0.1, 5))
        self.require_preselection()
        self.move_to(0.0, 5.0)
        self.assertFalse(self.cursor_forbidden(), "Expected no 'no' cursor on the line's end")
        self.click_at(0.0, 5.0)
        self.assertTrue(
            self.has_line(V(2, 5, 0), V(10, 5, 0)), f"Expected the end's piece gone: {self.sketch.Geometry}"
        )
        circles = [g for g in self.sketch.Geometry if isinstance(g, Part.Circle)]
        self.assertEqual(len(circles), 1, "Expected the circle whole")
        self.assertEqual(self.modals["seen"], [])


class TestSketchTrimPointsGui(SketchSplitTestCase):
    """Onshape SK23-SK25: Trim at two crossing lines, at a corner, at a centre and at an arc's end
    inside a line. Designed geometry per test (Top plane, mm), as the oracle's studios."""

    def add(self, *geometry):
        for g in geometry:
            self.sketch.addGeometry(g, False)
        self.doc.recompute()

    def start_trim(self):
        self.modals = self.answer_modals()
        self.start_edit()
        FreeCADGui.runCommand("Sketcher_Trimming")
        self.flush_gui(200)

    def test_crossing_lines_along_one_trim_the_others_upper_piece(self):
        """SK23: A (0,5)-(10,5), B (3,0)-(3,8); along A to (3,5): B -> (3,0)-(3,5), A whole."""
        self.add(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)), Part.LineSegment(V(3, 0, 0), V(3, 8, 0)))
        self.start_trim()
        self.trace((0.5, 5), (1.5, 5), (2.5, 5), (2.9, 5))
        self.require_preselection()
        self.click_at(3.03, 5.0)
        self.assertTrue(self.has_line(V(0, 5, 0), V(10, 5, 0)), f"Expected A whole: {self.sketch.Geometry}")
        self.assertTrue(self.has_line(V(3, 0, 0), V(3, 5, 0)), f"Expected B's lower piece kept: {self.sketch.Geometry}")
        self.assertEqual(len(self.sketch.Geometry), 2)
        self.assertEqual(self.modals["seen"], [])

    def test_a_corner_along_one_line_deletes_the_other(self):
        """SK24: P (0,0)-(5,5) and Q (5,5)-(10,0) coincident at (5,5); along P to the corner: Q goes."""
        self.add(Part.LineSegment(V(0, 0, 0), V(5, 5, 0)), Part.LineSegment(V(5, 5, 0), V(10, 0, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        self.doc.recompute()
        self.start_trim()
        self.trace((3, 3), (4, 4), (4.7, 4.7))
        self.require_preselection()
        self.move_to(5.0, 5.0)
        self.assertFalse(self.cursor_forbidden(), "Expected no 'no' cursor at the corner")
        self.click_at(5.0, 5.0)
        self.assertEqual(len(self.sketch.Geometry), 1, f"Expected Q deleted: {self.sketch.Geometry}")
        self.assertTrue(self.has_line(V(0, 0, 0), V(5, 5, 0)), "Expected P kept")
        self.assertEqual(self.modals["seen"], [])

    def test_a_centre_trims_nothing(self):
        """SK24: a click on a circle's centre does nothing."""
        self.add(Part.Circle(V(5, 5, 0), V(0, 0, 1), 3))
        self.start_trim()
        self.trace((5.4, 5.3), (5.1, 5.05))
        self.move_to(5.0, 5.0)
        if not self.preselected():
            self.skipTest("the 3D view doesn't preselect here (off screen without OpenGL)")
        self.assertFalse(self.cursor_forbidden(), "Expected no 'no' cursor at the centre")
        self.click_at(5.0, 5.0)
        circles = [g for g in self.sketch.Geometry if isinstance(g, Part.Circle)]
        self.assertEqual(len(circles), 1, f"Expected the circle whole: {self.sketch.Geometry}")
        self.assertEqual(self.modals["seen"], [])

    def test_an_arc_end_inside_a_line_along_the_line_trims_the_lines_piece(self):
        """SK25: arc R (8,5)->(2,5) over the top, line M (0,5)-(5,5); along M to (2,5): M's left
        piece goes (M -> (2,5)-(5,5)), R whole."""
        self.add(
            Part.ArcOfCircle(Part.Circle(V(5, 5, 0), V(0, 0, 1), 3), 0, math.pi),
            Part.LineSegment(V(0, 5, 0), V(5, 5, 0)),
        )
        self.start_trim()
        self.trace((0.3, 5), (1.0, 5), (1.6, 5))
        self.require_preselection()
        self.click_at(1.97, 5.0)
        self.assertTrue(self.has_line(V(2, 5, 0), V(5, 5, 0)), f"Expected M's left piece gone: {self.sketch.Geometry}")
        self.assertEqual(len(self.arcs()), 1, "Expected R whole")
        self.assertEqual(self.modals["seen"], [])


class TestSketchExtendGui(SketchSplitTestCase):
    """Onshape GA3-25 (ops#640): Extend's first click picks the line, the second sets its end, but
    the end stops at the first curve in its way, where the end is put on that curve (PointOnObject);
    nothing in the way, it ends at the click and nothing is stored. Line A (0,5)-(6,5); line B
    (9,0)-(9,10) across A's path."""

    def build(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, 5, 0), V(6, 5, 0)), False)
        self.sketch.addGeometry(Part.LineSegment(V(9, 0, 0), V(9, 10, 0)), False)

    def start_extend(self):
        self.modals = self.answer_modals()
        self.start_edit()
        FreeCADGui.runCommand("Sketcher_Extend")
        self.flush_gui(200)

    def pick_a_near_its_end(self):
        self.trace((4.5, 5), (5.2, 5), (5.5, 5))
        self.require_preselection()
        self.click_at(5.5, 5.0)

    def test_a_click_past_a_line_stops_the_end_on_it(self):
        self.start_extend()
        self.pick_a_near_its_end()
        self.trace((7, 5), (10, 5), (12, 5))
        self.click_at(12.0, 5.0)
        end = self.sketch.getPoint(0, 2)
        self.assertLess((end - V(9, 5, 0)).Length, 1e-9, f"Expected A's end on B at (9, 5), got {end}")
        self.assertLess((self.sketch.getPoint(0, 1) - V(0, 5, 0)).Length, 1e-9, "Expected A's start kept")
        found = [(c.Type, c.First, c.FirstPos, c.Second) for c in self.sketch.Constraints]
        self.assertIn(("PointOnObject", 0, 2, 1), found)
        self.assertEqual(self.modals["seen"], [])

    def test_a_click_short_of_the_line_ends_there_and_stores_nothing(self):
        self.start_extend()
        self.pick_a_near_its_end()
        self.trace((7, 5), (7.5, 5))
        self.click_at(8.0, 5.0)
        self.assert_near(self.sketch.getPoint(0, 2), 8, 5, "A's end")
        self.assertEqual(len(self.sketch.Constraints), 0, f"Expected nothing stored: {self.sketch.Constraints}")
        self.assertEqual(self.modals["seen"], [])


class TestSketchTrimDragGui(SketchSplitTestCase):
    """Onshape GA3-25 and sketch tools 1 extra 3 (ops#640): Trim by dragging. One drag with the
    button held across several curves trims each to its boundaries, and a curve with no boundary is
    deleted whole. V (0,5)-(8,5) crosses G1-G3, x = 2, 4, 6 from y 0 to 10; F1 and F2, x = 12 and 14
    from y 0 to 10, cross nothing."""

    def build(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, 5, 0), V(8, 5, 0)), False)
        for x in (2, 4, 6, 12, 14):
            self.sketch.addGeometry(Part.LineSegment(V(x, 0, 0), V(x, 10, 0)), False)

    def start_trim(self):
        self.modals = self.answer_modals()
        self.start_edit()
        FreeCADGui.runCommand("Sketcher_Trimming")
        self.flush_gui(200)

    def drag(self, *points):
        """Presses at the first sketch point, moves through the others with the button held,
        releases at the last."""
        first = self.screen_point(*points[0])
        self.move(self.viewport, first)
        self.send_mouse(self.viewport, QtCore.QEvent.MouseButtonPress, first, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self.pump(80)
        for x, y in points[1:]:
            self.send_mouse(
                self.viewport,
                QtCore.QEvent.MouseMove,
                self.screen_point(x, y),
                QtCore.Qt.NoButton,
                QtCore.Qt.LeftButton,
            )
            self.pump(80)
        last = self.screen_point(*points[-1])
        self.send_mouse(self.viewport, QtCore.QEvent.MouseButtonRelease, last, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        self.flush_gui(150)

    def test_a_drag_across_three_lines_trims_each_back_to_the_crossing_line(self):
        self.start_trim()
        self.trace((1.0, 8), (1.5, 8))
        self.drag((1.0, 8), (1.6, 8), (2.0, 8), (2.4, 8), (3.6, 8), (4.0, 8), (4.4, 8), (5.6, 8), (6.0, 8), (6.4, 8), (7.0, 8))
        if self.has_line(V(2, 0, 0), V(2, 10, 0)) and self.has_line(V(4, 0, 0), V(4, 10, 0)):
            self.require_preselection()
        for x in (2, 4, 6):
            self.assertTrue(
                self.has_line(V(x, 0, 0), V(x, 5, 0)), f"Expected G at x={x} trimmed to (x,0)-(x,5): {self.sketch.Geometry}"
            )
        self.assertTrue(self.has_line(V(0, 5, 0), V(8, 5, 0)), "Expected V whole")
        self.assertEqual(len(self.lines()), 6, f"Expected nothing else changed: {self.sketch.Geometry}")
        self.assertEqual(self.modals["seen"], [])

    def test_a_drag_across_free_lines_deletes_them(self):
        self.start_trim()
        self.trace((11.0, 8), (11.5, 8))
        self.drag((11.0, 8), (11.6, 8), (12.0, 8), (12.4, 8), (13.6, 8), (14.0, 8), (14.4, 8), (15.0, 8))
        if self.has_line(V(12, 0, 0), V(12, 10, 0)) and self.has_line(V(14, 0, 0), V(14, 10, 0)):
            self.require_preselection()
        self.assertFalse(self.has_line(V(12, 0, 0), V(12, 10, 0)), f"Expected F1 deleted: {self.sketch.Geometry}")
        self.assertFalse(self.has_line(V(14, 0, 0), V(14, 10, 0)), f"Expected F2 deleted: {self.sketch.Geometry}")
        self.assertEqual(len(self.lines()), 4, f"Expected V and G1-G3 kept: {self.sketch.Geometry}")
        self.assertEqual(self.modals["seen"], [])
