# SPDX-License-Identifier: LGPL-2.1-or-later

"""Automatic constraints of a drawing tool in a sketch the solver already finds redundant
(ops#199).

The tool diagnoses the sketch with its new automatic constraints appended and drops those the
solver names as redundant. When the solver named a constraint that was already in the sketch,
it dropped every automatic constraint and threw: in a sketch that was already redundant, no
drawing tool kept its automatic constraints. Now only the automatic constraints that bring a new
redundancy are dropped.

Each test draws a line with Sketcher_CreateLine, two clicks, the first on an end point of line 0
(an automatic Coincident), the second where the new line is vertical or horizontal (an
automatic Vertical or Horizontal).
"""

import FreeCAD
import Part
import Sketcher
from PySide import QtGui
from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

V = FreeCAD.Vector

SKETCHER_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher"
TOOLS_PARAMS = SKETCHER_PARAMS + "/Tools"

# A top view centred on (5, 5) of the sketch (XY plane), 30 mm high, as in
# TestDimensionInPlaceGui.
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


class TestAutoConstraintsGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        if not QtGui.QFontDatabase.families():
            # Off screen without QT_QPA_FONTDIR: drawing the constraint icons throws
            # (notes/build.md).
            self.skipTest("Qt has no fonts; off screen, set QT_QPA_FONTDIR")

        self.saved_params = []
        self.set_param(SKETCHER_PARAMS, "Bool", "ContinuousCreationMode", False)
        self.set_param(TOOLS_PARAMS, "Int", "OnViewParameterVisibility", 0)  # no OVP fields

        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.doc = FreeCAD.newDocument("TestAutoConstraintsGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.doc.recompute()

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            for path, kind, name, had, value in reversed(getattr(self, "saved_params", [])):
                group = FreeCAD.ParamGet(path)
                if had:
                    getattr(group, "Set" + kind)(name, value)
                else:
                    getattr(group, "Rem" + kind)(name)

    def set_param(self, path, kind, name, value):
        group = FreeCAD.ParamGet(path)
        had = name in getattr(group, "Get" + kind + "s")()
        old = getattr(group, "Get" + kind)(name) if had else None
        self.saved_params.append((path, kind, name, had, old))
        getattr(group, "Set" + kind)(name, value)

    # The sketch editor -----------------------------------------------------------------------

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
        """The viewport point (widget coordinates) of sketch point (x, y), mapped now: the
        viewport changes size when a tool's panel opens or closes.

        getPointOnScreen and the mouse events disagree in a viewport taller than wide (off
        screen, 534 x 641: ADJUST_CAMERA widens the view by the aspect ratio): correct the
        point until a click there lands on (x, y), as the events map it."""
        target = V(x, y, 0)
        guess = V(target)
        for _ in range(20):
            hit = self.view.getPointOnFocalPlane(self.view.getPointOnScreen(guess))
            error = V(target.x - hit.x, target.y - hit.y, 0)
            if error.Length < 1e-6:
                break
            guess += error
        return self.viewport_to_qpoint(self.view, self.viewport, self.view.getPointOnScreen(guess))

    def draw_line(self, start, end):
        """Sketcher_CreateLine from sketch point start to end, by two clicks."""
        before = self.sketch.GeometryCount
        FreeCADGui.runCommand("Sketcher_CreateLine")
        self.flush_gui(150)
        for x, y in (start, end):
            # The first move can change the tool's panel and with it the viewport's size: map
            # again after it settles.
            self.move(self.viewport, self.screen_point(x, y))
            self.flush_gui(200)
            point = self.screen_point(x, y)
            self.move(self.viewport, point)
            self.click(self.viewport, point)
            self.flush_gui(200)
        self.assertTrue(
            self.wait_until(lambda: self.sketch.GeometryCount == before + 1, 2000),
            "Expected the line tool to add a line",
        )
        self.flush_gui(150)

    # Reading the result ----------------------------------------------------------------------

    def has_constraint(self, kind, first, first_pos=None, second=None, second_pos=None):
        """Whether the sketch has a constraint of this kind on these elements, in either order
        for a Coincident."""
        wanted = [(first, first_pos, second, second_pos)]
        if kind == "Coincident":
            wanted.append((second, second_pos, first, first_pos))
        for c in self.sketch.Constraints:
            if c.Type != kind:
                continue
            for f, fp, s, sp in wanted:
                if c.First != f or (fp is not None and c.FirstPos != fp):
                    continue
                if s is not None and (c.Second != s or (sp is not None and c.SecondPos != sp)):
                    continue
                return True
        return False

    def describe(self):
        """The constraints and the lines' ends, for failure messages."""
        return [
            (c.Type, c.First, c.FirstPos, c.Second, c.SecondPos) for c in self.sketch.Constraints
        ] + [(g.StartPoint, g.EndPoint) for g in self.sketch.Geometry]

    # Models ----------------------------------------------------------------------------------

    def add_horizontal_line(self, horizontal_constraints):
        """Line 0 from (0, 2) to (10, 2) with this many Horizontal constraints (two make the
        sketch redundant)."""
        self.sketch.addGeometry(Part.LineSegment(V(0, 2, 0), V(10, 2, 0)), False)
        for _ in range(horizontal_constraints):
            self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.doc.recompute()

    # Tests -----------------------------------------------------------------------------------

    def check_vertical_line_from_the_end(self):
        """Line 1 from line 0's end (10, 2) up to (10, 9): it starts on that end (Coincident)
        and is vertical (Vertical), and both automatic constraints are in the sketch."""
        self.start_edit()
        self.draw_line((10, 2), (10, 9))

        line = self.sketch.Geometry[1]
        self.assertLess((line.StartPoint - V(10, 2, 0)).Length, 1e-7, "Line 1's start")
        self.assertTrue(
            self.has_constraint("Coincident", 1, 1, 0, 2),
            f"Expected line 1's start coincident with line 0's end, got {self.describe()}",
        )
        self.assertTrue(
            self.has_constraint("Vertical", 1),
            f"Expected line 1 vertical, got {self.describe()}",
        )

    def test_a1_autoconstraints_in_a_sound_sketch(self):
        """A1: the reference case, a sketch with no redundancy: the automatic constraints are
        added (this passed before the fix too)."""
        self.add_horizontal_line(1)
        self.check_vertical_line_from_the_end()
        self.assertEqual(len(self.sketch.Constraints), 3)

    def test_a2_autoconstraints_in_an_already_redundant_sketch(self):
        """A2: line 0 has two Horizontal constraints, so the sketch is redundant before the
        tool runs. The new line's Coincident and Vertical bring no new redundancy and are
        added; the sketch keeps its own (old) redundancy, nothing more."""
        self.add_horizontal_line(2)
        self.assertEqual(len(self.sketch.RedundantConstraints), 1)
        old_redundant = list(self.sketch.RedundantConstraints)

        self.check_vertical_line_from_the_end()
        self.assertEqual(len(self.sketch.Constraints), 4)
        self.sketch.solve()
        self.assertEqual(list(self.sketch.RedundantConstraints), old_redundant)

    def test_a3_redundant_autoconstraint_is_dropped_alone(self):
        """A3: line 0 with one Horizontal, then line 1 drawn over it from its start (0, 2) to
        its end (10, 2): two automatic Coincidents and an automatic Horizontal. With the
        Horizontal on line 0, the two Coincidents make line 1 horizontal already, so one of
        the two Horizontal constraints is redundant. The solver names line 1's (an automatic
        constraint, so this passed before the fix too): only it is dropped, the Coincidents
        are added, and the sketch ends without redundancy."""
        self.add_horizontal_line(1)
        self.start_edit()
        self.draw_line((0, 2), (10, 2))

        self.assertTrue(
            self.has_constraint("Coincident", 1, 1, 0, 1),
            f"Expected line 1's start on line 0's start, got {self.describe()}",
        )
        self.assertTrue(
            self.has_constraint("Coincident", 1, 2, 0, 2),
            f"Expected line 1's end on line 0's end, got {self.describe()}",
        )
        self.assertFalse(self.has_constraint("Horizontal", 1), f"Got {self.describe()}")
        self.sketch.solve()
        self.assertEqual(list(self.sketch.RedundantConstraints), [])

    def test_a4_redundant_autoconstraint_dropped_in_an_already_redundant_sketch(self):
        """A4 (ops#204): line 0 with two Horizontal constraints (redundant before the tool
        runs), then line 1 drawn over it from (0, 2) to (10, 2): two automatic Coincidents and
        an automatic Horizontal. The solver names an old Horizontal, so the tool tries the
        automatic constraints one at a time, the one-equation Horizontal last: both Coincidents
        are kept, the Horizontal brings a new redundancy and is dropped, and the sketch keeps
        its own (old) redundancy, nothing more."""
        self.add_horizontal_line(2)
        old_redundant = list(self.sketch.RedundantConstraints)
        self.assertEqual(len(old_redundant), 1)
        self.start_edit()
        self.draw_line((0, 2), (10, 2))

        self.assertTrue(
            self.has_constraint("Coincident", 1, 1, 0, 1),
            f"Expected line 1's start on line 0's start, got {self.describe()}",
        )
        self.assertTrue(
            self.has_constraint("Coincident", 1, 2, 0, 2),
            f"Expected line 1's end on line 0's end, got {self.describe()}",
        )
        self.assertFalse(self.has_constraint("Horizontal", 1), f"Got {self.describe()}")
        self.assertEqual(len(self.sketch.Constraints), 4, f"Got {self.describe()}")
        self.sketch.solve()
        self.assertEqual(list(self.sketch.RedundantConstraints), old_redundant)

    def test_a5_single_autoconstraint_in_an_already_redundant_sketch(self):
        """A5 (ops#223, the one-diagnosis skip of ops#204): line 0 with two Horizontal
        constraints, then a vertical line 1 from (15, 3) to (15, 9), away from line 0: one
        automatic Vertical. The solver names only the old Horizontal and the DoF falls, so it
        is kept without trying it alone; the sketch keeps its own redundancy."""
        self.add_horizontal_line(2)
        old_redundant = list(self.sketch.RedundantConstraints)
        self.start_edit()
        self.draw_line((15, 3), (15, 9))

        self.assertTrue(self.has_constraint("Vertical", 1), f"Got {self.describe()}")
        self.assertEqual(len(self.sketch.Constraints), 3, f"Got {self.describe()}")
        self.sketch.solve()
        self.assertEqual(list(self.sketch.RedundantConstraints), old_redundant)

    def test_a6_independent_point_on_object_kept_when_the_solver_renames_an_old_redundancy(self):
        """A6 (ops#223): line 0 with three Horizontal constraints (the sketch names one of them
        redundant), then line 1 from (3, 2), on line 0 (not its midpoint, which would give a Symmetric), to
        (7, 9): an automatic PointOnObject
        of line 1's start on line 0. It fixes the start's height, an equation of its own, but
        with it the solver names another of line 0's Horizontals. A one-equation constraint
        that lowers the DoF by one is kept whatever old constraint the solver names. Drawn
        this way the drawing tool's diagnosis names the same Horizontal as before (a full
        solve with the constraint appended names another), so the one-diagnosis skip keeps it:
        this guards the outcome, not yet the renamed case."""
        self.add_horizontal_line(3)
        self.assertEqual(len(self.sketch.RedundantConstraints), 1)
        self.start_edit()
        self.draw_line((3, 2), (7, 9))

        self.assertTrue(
            self.has_constraint("PointOnObject", 1, 1, 0),
            f"Expected line 1's start on line 0, got {self.describe()}",
        )
        self.assertEqual(len(self.sketch.Constraints), 4, f"Got {self.describe()}")
        self.sketch.solve()
        self.assertEqual(len(self.sketch.RedundantConstraints), 1, f"Got {self.describe()}")
        self.assertEqual(list(self.sketch.ConflictingConstraints), [])
