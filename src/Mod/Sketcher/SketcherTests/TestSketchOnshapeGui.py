# SPDX-License-Identifier: LGPL-2.1-or-later

"""The sketch works as Onshape's does (FreeCAD-CH, ops#640, the sketch area).

- Esc with no tool running keeps the sketch open: Onshape's Esc leaves the running tool only, and
  the sketch closes with its check (preference LeaveSketchWithEscape, now off by default).
- Midpoint (ops#645, the user's report 14): a point and a line, in either order, or two points and
  then the point between them. The point is kept at the middle; a point and an arc of circle keep
  the point at the arc's own middle (Sketcher's Midpoint, ops#656).

Designed geometry: a line from (0, 0) to (10, 4) and a free point at (3, 7), in an unattached
sketch; the midpoint is (5, 2)."""

import math

import FreeCAD
import Part
import Sketcher

from SketcherTests.GuiTestCase import FreeCADGui, QtCore, QtGui, SketcherGuiTestCase

V = FreeCAD.Vector
SKETCHER = "User parameter:BaseApp/Preferences/Mod/Sketcher"


class SketchOnshapeTestCase(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument(type(self).__name__)
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 4, 0)), False)
        self.sketch.addGeometry(Part.Point(V(3, 7, 0)), False)
        self.doc.recompute()

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        super().tearDown()

    def edit(self):
        FreeCADGui.getMainWindow().show()  # as the first GUI test of a process too
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(100)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit())

    def in_edit(self):
        return FreeCADGui.ActiveDocument.getInEdit() is not None

    def select(self, *names):
        FreeCADGui.Selection.clearSelection()
        for name in names:
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, name)


class TestSketchEscapeGui(SketchOnshapeTestCase):
    def tearDown(self):
        FreeCAD.ParamGet(SKETCHER).RemBool("LeaveSketchWithEscape")
        super().tearDown()

    def press_escape_in_view(self):
        view = FreeCADGui.ActiveDocument.ActiveView
        self.key_click(view.graphicsView(), QtCore.Qt.Key_Escape)
        self.flush_gui(100)

    def test_escape_with_no_tool_keeps_the_sketch_open(self):
        """No tool running: Esc in the 3D view leaves the sketch open and its dialog shown."""
        self.edit()
        self.press_escape_in_view()
        self.assertTrue(self.in_edit())
        self.assertIsNotNone(FreeCADGui.Control.activeDialog())

    def test_escape_leaves_the_sketch_with_the_preference_on(self):
        """The preference still works: with LeaveSketchWithEscape on, Esc closes the sketch (the
        check that the key reaches the sketch at all)."""
        FreeCAD.ParamGet(SKETCHER).SetBool("LeaveSketchWithEscape", True)
        self.edit()
        self.press_escape_in_view()
        self.assertTrue(self.wait_until(lambda: not self.in_edit(), timeout_ms=1000))


class TestSketchMidpointGui(SketchOnshapeTestCase):
    # Edge1 is the line; Vertex1 and Vertex2 its ends; Vertex3 the free point
    def run_midpoint(self, *names):
        self.edit()
        self.select(*names)
        FreeCADGui.runCommand("Sketcher_ConstrainMidpoint")
        self.flush_gui(100)
        self.assertEqual(self.sketch.solve(), 0)

    def assert_point_at_the_middle(self):
        self.assertEqual(self.sketch.ConstraintCount, 1)
        point = self.sketch.getPoint(1, 1)
        self.assertAlmostEqual(point.x, 5, places=6)
        self.assertAlmostEqual(point.y, 2, places=6)
        line = self.sketch.Geometry[0]
        middle = (line.StartPoint + line.EndPoint) * 0.5
        self.assertAlmostEqual((point - middle).Length, 0, places=6)

    def test_the_command_exists(self):
        self.assertIsNotNone(FreeCADGui.Command.get("Sketcher_ConstrainMidpoint"))

    def test_point_then_line(self):
        self.run_midpoint("Vertex3", "Edge1")
        self.assert_point_at_the_middle()

    def test_line_then_point(self):
        self.run_midpoint("Edge1", "Vertex3")
        self.assert_point_at_the_middle()

    def test_two_points_then_the_midpoint(self):
        """Onshape's three-point way: the line's start, its end, then the point between."""
        self.run_midpoint("Vertex1", "Vertex2", "Vertex3")
        self.assert_point_at_the_middle()

    def test_the_point_stays_at_the_middle_when_the_line_moves(self):
        self.run_midpoint("Vertex3", "Edge1")
        self.sketch.moveGeometry(0, 2, V(20, 10, 0), False)  # the line's end, by the solver
        self.assertEqual(self.sketch.solve(), 0)
        point = self.sketch.getPoint(1, 1)
        line = self.sketch.Geometry[0]
        middle = (line.StartPoint + line.EndPoint) * 0.5
        self.assertAlmostEqual((point - middle).Length, 0, places=6)

    def test_one_undo_step(self):
        self.doc.UndoMode = 1
        self.run_midpoint("Vertex3", "Edge1")
        self.assertEqual(self.doc.UndoNames[0], "Add midpoint constraint")
        self.doc.undo()
        self.assertEqual(self.sketch.ConstraintCount, 0)

    def test_an_arcs_middle(self):
        """A point and an arc (ops#656): the point goes to the middle of the arc itself, at the mean
        of its end angles (not the middle of its chord), and the arc stays; it follows when an end
        of the arc moves. The arc: centre (0, -20), radius 5, from 0.5 to 2.5 rad."""
        arc = Part.ArcOfCircle(Part.Circle(V(0, -20, 0), V(0, 0, 1), 5), 0.5, 2.5)
        self.sketch.addGeometry(arc, False)
        self.doc.recompute()
        self.run_midpoint("Vertex3", "Edge3")
        self.assertEqual(self.sketch.ConstraintCount, 1)
        self.assertEqual(self.sketch.Constraints[0].Type, "Midpoint")
        point = self.sketch.getPoint(1, 1)
        self.assertAlmostEqual(point.x, 5 * math.cos(1.5), places=6)
        self.assertAlmostEqual(point.y, -20 + 5 * math.sin(1.5), places=6)
        self.assertAlmostEqual(self.sketch.Geometry[2].Radius, 5, places=6)
        self.sketch.moveGeometry(2, 1, V(5, -20, 0), False)  # the arc's start, by the solver
        self.assertEqual(self.sketch.solve(), 0)
        g = self.sketch.Geometry[2]
        u = (g.FirstParameter + g.LastParameter) / 2
        point = self.sketch.getPoint(1, 1)
        self.assertAlmostEqual((point - g.value(u)).Length, 0, places=6)

    def test_a_lines_own_end_is_refused(self):
        self.run_midpoint("Vertex1", "Edge1")
        self.assertEqual(self.sketch.ConstraintCount, 0)


class TestSketchOverdefiningDimensionGui(SketchOnshapeTestCase):
    """A new dimension that would overdefine the sketch is made driven, as Onshape does: the line
    already has its horizontal distance 10, and a second one is placed on it."""

    def setUp(self):
        super().setUp()
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 10))
        self.doc.recompute()
        params = FreeCAD.ParamGet(SKETCHER)
        self.show = params.GetBool("ShowDialogOnDistanceConstraint", True)
        params.SetBool("ShowDialogOnDistanceConstraint", False)

    def tearDown(self):
        FreeCAD.ParamGet(SKETCHER).SetBool("ShowDialogOnDistanceConstraint", self.show)
        super().tearDown()

    def dimension(self, command, *names):
        self.edit()
        self.select(*names)
        FreeCADGui.runCommand(command)
        self.flush_gui(100)

    def test_a_second_horizontal_distance_is_driven(self):
        self.dimension("Sketcher_ConstrainDistanceX", "Edge1")
        self.assertEqual(self.sketch.ConstraintCount, 2)
        self.assertFalse(self.sketch.Constraints[1].Driving)
        self.assertEqual(self.sketch.solve(), 0)

    def test_a_dimension_that_adds_a_constraint_stays_driving(self):
        self.dimension("Sketcher_ConstrainDistanceY", "Edge1")
        self.assertEqual(self.sketch.ConstraintCount, 2)
        self.assertTrue(self.sketch.Constraints[1].Driving)
        self.assertEqual(self.sketch.solve(), 0)

    def test_an_already_overdefined_sketch_keeps_the_new_dimension_driving(self):
        """The sketch is redundant before (two horizontal distances); a vertical distance adds a
        constraint, so it stays driving, and the old redundancy is left as it was."""
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 10))
        self.doc.recompute()
        self.dimension("Sketcher_ConstrainDistanceY", "Edge1")
        self.assertEqual(self.sketch.ConstraintCount, 3)
        self.assertTrue(self.sketch.Constraints[2].Driving)

    def test_the_driven_dimension_is_one_undo_step(self):
        self.doc.UndoMode = 1
        self.dimension("Sketcher_ConstrainDistanceX", "Edge1")
        self.doc.undo()
        self.assertEqual(self.sketch.ConstraintCount, 1)
        self.assertTrue(self.sketch.Constraints[0].Driving)


class TestSketchDeleteGui(SketcherGuiTestCase):
    """Deleting a line deletes the constraints on it alone, as Onshape does (blind test F14): its
    own horizontal distance doesn't move onto the neighbours' points. Designed geometry: a bottom
    line from (0, 0) to (32, 0) between two upright side lines, joined at the bottom corners."""

    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("TestSketchDeleteGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(32, 0, 0)), False)
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 10, 0)), False)
        self.sketch.addGeometry(Part.LineSegment(V(32, 0, 0), V(32, 10, 0)), False)
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, 1, 1))
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 2, 1))
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 32))
        self.sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
        self.doc.recompute()

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        super().tearDown()

    def delete_bottom_line(self):
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(100)
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge1")
        FreeCADGui.runCommand("Std_Delete")
        self.flush_gui(100)

    def test_the_lines_own_dimension_goes_with_it(self):
        self.delete_bottom_line()
        self.assertEqual(self.sketch.GeometryCount, 2)
        types = [c.Type for c in self.sketch.Constraints]
        self.assertNotIn("DistanceX", types)
        self.assertEqual(types, ["Vertical"])

    def test_redrawing_and_dimensioning_the_line_solves(self):
        """The journey of F14: the line is drawn again and dimensioned 32; the sketch solves with no
        redundancy (it went redundant when the old dimension had moved onto the side lines)."""
        self.delete_bottom_line()
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(32, 0, 0)), False)
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 2, 1, 0, 1))
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 1, 1))
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 2, 1, 2, 2, 32))
        self.assertEqual(self.sketch.solve(), 0)


# A top view centred on (5, 5) of the sketch (XY plane), 30 mm high, as in TestAutoConstraintsGui
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


class TestSketchShiftInferenceGui(SketcherGuiTestCase):
    """Shift held while drawing suppresses the inferences, as in Onshape: a line drawn from the
    end of line 0 to the right, level with it, gets a Coincident at its start and a Horizontal
    without Shift, and neither with Shift. Designed geometry: line 0 from (0, 2) to (4, 2)."""

    def setUp(self):
        super().setUp()
        if not QtGui.QFontDatabase.families():
            self.skipTest("Qt has no fonts; off screen, set QT_QPA_FONTDIR")
        self.params = []
        self.set_param(SKETCHER, "Bool", "ContinuousCreationMode", False)
        self.set_param(SKETCHER + "/Tools", "Int", "OnViewParameterVisibility", 0)
        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.doc = FreeCAD.newDocument("TestSketchShiftInferenceGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.LineSegment(V(0, 2, 0), V(4, 2, 0)), False)
        self.doc.recompute()

    def tearDown(self):
        from PySide6 import QtTest

        # a release without modifiers clears the application's modifier state, which a QTest press
        # with a modifier leaves "held" for every later test of the process (notes/build.md)
        QtTest.QTest.keyRelease(FreeCADGui.getMainWindow().windowHandle(), QtCore.Qt.Key_Shift)
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

    def draw_line(self, points):
        FreeCADGui.runCommand("Sketcher_CreateLine")
        self.flush_gui(150)
        for x, y in points:
            self.move(self.viewport, self.screen_point(x, y))
            self.flush_gui(200)
            point = self.screen_point(x, y)
            self.move(self.viewport, point)
            self.click(self.viewport, point)
            self.flush_gui(200)
        self.assertTrue(self.wait_until(lambda: self.sketch.GeometryCount == 2, 2000))
        self.flush_gui(150)

    def types(self):
        return sorted(c.Type for c in self.sketch.Constraints)

    def test_without_shift_the_line_is_inferred(self):
        self.start_edit()
        self.draw_line([(4, 2), (9, 2.05)])
        self.assertIn("Coincident", self.types())
        self.assertIn("Horizontal", self.types())

    def test_shift_held_suppresses_the_inferences(self):
        """Shift is held through the whole line: the Sketcher reads the application's modifier
        state (QGuiApplication.keyboardModifiers), which a QTest press of Shift with the Shift
        modifier sets off screen too; the synthetic mouse events carry no modifier."""
        from PySide6 import QtTest

        self.start_edit()
        QtTest.QTest.keyPress(
            FreeCADGui.getMainWindow().windowHandle(), QtCore.Qt.Key_Shift, QtCore.Qt.ShiftModifier
        )
        self.assertTrue(
            QtGui.QGuiApplication.keyboardModifiers() & QtCore.Qt.ShiftModifier,
            "Expected the application to see Shift held",
        )
        self.draw_line([(4, 2), (9, 2.05)])
        self.assertEqual(self.types(), [])


VIEW = "User parameter:BaseApp/Preferences/View"


class TestSketchColoursGui(SketcherGuiTestCase):
    """Onshape's sketch colours, with no colour set in the preferences (a theme pack sets its own):
    an under-constrained line is blue, a fully constrained sketch black on a light 3D view
    background and white on a dark one. Designed geometry: one line, blocked to constrain it."""

    BLUE = (0.24, 0.55, 1.0)
    BLACK = (0.13, 0.15, 0.16)
    WHITE = (0.95, 0.95, 0.96)

    def setUp(self):
        super().setUp()
        self.view_params = FreeCAD.ParamGet(VIEW)
        self.saved = {
            "Gradient": ("Bool", "Gradient" in self.view_params.GetBools(), self.view_params.GetBool("Gradient", True)),
            "RadialGradient": ("Bool", "RadialGradient" in self.view_params.GetBools(), self.view_params.GetBool("RadialGradient", False)),
            "BackgroundColor": ("Unsigned", "BackgroundColor" in self.view_params.GetUnsigneds(), self.view_params.GetUnsigned("BackgroundColor", 0)),
        }
        for name in ("EditedEdgeColor", "FullyConstrainedColor", "FullyConstraintElementColor"):
            if name in self.view_params.GetUnsigneds():
                self.skipTest("a colour is set in the preferences: " + name)
        self.doc = FreeCAD.newDocument("TestSketchColoursGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 4, 0)), False)
        self.doc.recompute()

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            for name, (kind, had, value) in self.saved.items():
                if had:
                    getattr(self.view_params, "Set" + kind)(name, value)
                else:
                    getattr(self.view_params, "Rem" + kind)(name)

    def background(self, packed):
        self.view_params.SetBool("Gradient", False)
        self.view_params.SetBool("RadialGradient", False)
        self.view_params.SetUnsigned("BackgroundColor", packed)

    def line_colour(self):
        from pivy import coin

        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(150)
        search = coin.SoSearchAction()
        search.setName("CurvesMaterials0")
        search.setSearchingAll(True)
        view = FreeCADGui.ActiveDocument.ActiveView
        search.apply(view.getViewer().getSoRenderManager().getSceneGraph())
        path = search.getPath()
        self.assertIsNotNone(path, "Expected the sketch's curve materials")
        colour = path.getTail().diffuseColor.getValues()[0]
        return tuple(colour.getValue())

    def assert_colour(self, actual, expected):
        for a, e in zip(actual, expected):
            self.assertAlmostEqual(a, e, delta=0.01, msg=(actual, expected))

    def test_an_under_constrained_line_is_blue(self):
        self.assert_colour(self.line_colour(), self.BLUE)

    def test_fully_constrained_is_black_on_a_light_background(self):
        self.background(0xFFFFFFFF)
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.doc.recompute()
        self.assert_colour(self.line_colour(), self.BLACK)

    def test_fully_constrained_is_white_on_a_dark_background(self):
        self.background(0x1F1F1FFF)
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.doc.recompute()
        self.assert_colour(self.line_colour(), self.WHITE)

    # Onshape's dimensions (PL1c): black text and arrows, white on a dark background like the
    # fully constrained curves; a driven dimension grey.
    GREY = (0.525, 0.557, 0.588)

    def dimension_colours(self):
        from pivy import coin

        for name in ("ConstrainedDimColor", "NonDrivingConstrDimColor", "ExprBasedConstrDimColor"):
            if name in self.view_params.GetUnsigneds():
                self.skipTest("a colour is set in the preferences: " + name)
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(150)
        datum_type = coin.SoType.fromName("SoDatumLabel")
        labels = []

        def visit(node):
            if node.isOfType(datum_type):
                labels.append(node)
            if node.isOfType(coin.SoGroup.getClassTypeId()):
                for index in range(node.getNumChildren()):
                    visit(node.getChild(index))

        visit(FreeCADGui.ActiveDocument.ActiveView.getViewer().getSoRenderManager().getSceneGraph())
        return [tuple(label.textColor.getValue().getValue()) for label in labels]

    def test_a_dimension_is_black_on_a_light_background(self):
        self.background(0xFFFFFFFF)
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 10.0))
        self.doc.recompute()
        colours = self.dimension_colours()
        self.assertEqual(len(colours), 1, colours)
        self.assert_colour(colours[0], self.BLACK)

    def test_a_dimension_is_white_on_a_dark_background(self):
        self.background(0x1F1F1FFF)
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 10.0))
        self.doc.recompute()
        colours = self.dimension_colours()
        self.assertEqual(len(colours), 1, colours)
        self.assert_colour(colours[0], self.WHITE)

    def test_a_driven_dimension_is_grey(self):
        self.background(0xFFFFFFFF)
        index = self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 10.0))
        self.sketch.setDriving(index, False)
        self.doc.recompute()
        colours = self.dimension_colours()
        self.assertEqual(len(colours), 1, colours)
        self.assert_colour(colours[0], self.GREY)


class TestSketchClosestMatchGui(SketcherGuiTestCase):
    """A missing sketch reference offers its closest match from inside the sketch (ops#644, the
    user's report 13), as Onshape's repair does: the sketch's status line says so, and its link
    (the command Sketcher_UseClosestReferenceMatches) takes the match in one undo step.

    Designed geometry, as TestSketchMissingExternal.testUnmappedSlotClosedFloor: a 30 x 30 U
    face, its slot (10..20) from y = 10 to the back, taken whole as external geometry; then the
    slot's mouth is closed, a square with a 10 x 15 hole. The link breaks with the face as its
    candidate."""

    def setUp(self):
        super().setUp()
        self.doc = FreeCAD.newDocument("TestSketchClosestMatchGui")
        self.doc.UndoMode = 1
        self.plate = self.doc.addObject("Part::Feature", "Plate")
        self.plate.Shape = Part.Face(
            self.wire([(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10), (10, 30), (0, 30)])
        )
        self.doc.recompute()
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "OnPlate")
        self.sketch.addExternal(self.plate.Name, "Face1")
        self.doc.recompute()
        self.plate.Shape = Part.makeFace(
            [
                self.wire([(0, 0), (30, 0), (30, 30), (0, 30)]),
                self.wire([(10, 10), (20, 10), (20, 25), (10, 25)]),
            ],
            "Part::FaceMakerBullseye",
        )
        self.doc.recompute()

    def tearDown(self):
        FreeCADGui.Selection.clearSelection()
        super().tearDown()

    @staticmethod
    def wire(points):
        return Part.makePolygon([V(x, y, 10) for x, y in points + points[:1]])

    def status_texts(self):
        from PySide import QtWidgets

        return [
            label.text()
            for label in FreeCADGui.getMainWindow().findChildren(QtWidgets.QLabel)
            if label.isVisible() or label.text()
        ]

    def test_the_status_line_offers_the_closest_match(self):
        self.assertFalse(self.sketch.isValid())
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(150)
        texts = self.status_texts()
        self.assertTrue(any("Missing references" in t for t in texts), texts)
        self.assertTrue(any("Use the closest match" in t for t in texts), texts)

    def test_the_closest_match_repairs_the_sketch_in_one_step(self):
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(150)
        FreeCADGui.runCommand("Sketcher_UseClosestReferenceMatches")
        self.flush_gui(150)
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertEqual(self.doc.UndoNames[0], "Use closest reference matches")
        texts = self.status_texts()
        self.assertFalse(any("Missing references" in t for t in texts), texts)
