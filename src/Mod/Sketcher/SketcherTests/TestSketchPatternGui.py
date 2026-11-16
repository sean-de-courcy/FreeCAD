# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: the sketch pattern tools (Onshape's circular and linear sketch patterns, GA3-28,
# 28b, 28c; notes/sketch-patterns-design.md item 4; ops#725).
#
# The tools start with nothing selected: each click on the sketch's own geometry picks a seed (a
# second click unpicks it), and the pattern shows at once, 3 instances, as real geometry in an
# open transaction. A click on empty canvas or Enter commits it as one undo step; Esc leaves
# nothing. "Edit pattern" is offered for the geometry of a pattern.
#
# Designed geometry: ToolFirstCase's four entities (0: a blocked line x = 10; 1: a line
# (2, 2)-(6, 4); 2: a circle, radius 1, at (4, 7); 3: a line (1, 8)-(3, 9)). Expected places are
# computed: a circular copy is its seed turned by 120 and 240 degrees about the origin, a linear
# copy its seed moved by 1 and 2 along X.

import math

import FreeCAD
from PySide import QtCore

from SketcherTests.GuiTestCase import FreeCADGui
from SketcherTests.TestSketchRound4Gui import ToolFirstCase

V = FreeCAD.Vector
TOL = 1e-6
CIRCLE = 2
CIRCLE_EDGE = (5, 7)  # the circle's rightmost point
LINE = 1
LINE_MIDDLE = (4, 3)
EMPTY = (14, 2)


def turned(x, y, degrees):
    a = math.radians(degrees)
    return V(x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a), 0)


class TestSketchPatternToolsGui(ToolFirstCase):
    def patterns(self):
        return [i for i, c in enumerate(self.sketch.Constraints) if c.Type == "Pattern"]

    def record(self):
        (index,) = self.patterns()
        return self.sketch.getPattern(index)

    def enter(self):
        graphics_view = self.view.graphicsView()
        graphics_view.setFocus(QtCore.Qt.OtherFocusReason)
        self.pump(100)
        self.key_click(graphics_view, QtCore.Qt.Key_Return)
        self.flush_gui(300)

    def start(self, command):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.flush_gui(200)
        FreeCADGui.runCommand(command)
        self.flush_gui(200)

    def assert_centre(self, geoId, expected):
        centre = self.sketch.Geometry[geoId].Center
        self.assertLess((centre - expected).Length, TOL, (geoId, centre, expected))

    def test_the_tools_are_active_with_nothing_selected(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.flush_gui(200)
        for name in ("Sketcher_CircularPattern", "Sketcher_LinearPattern"):
            self.assertTrue(FreeCADGui.isCommandActive(name), name)
        self.assertFalse(FreeCADGui.isCommandActive("Sketcher_EditPattern"))

    def test_a_pick_shows_three_instances_and_a_click_on_empty_canvas_commits(self):
        self.start("Sketcher_CircularPattern")
        self.assertEqual(self.sketch.GeometryCount, 4, "Expected the tool alone to change nothing")
        self.clicks([CIRCLE_EDGE])
        record = self.record()
        self.assertEqual(record["Kind"], "Circular")
        self.assertEqual(record["Seeds"], [CIRCLE])
        self.assertEqual(record["Counts"], (3, 1))
        # the pivot and two copies
        self.assertEqual(self.sketch.GeometryCount, 7)
        pivot = self.sketch.getPoint(record["Pivot"], 1)
        self.assertLess(pivot.Length, TOL, "Expected the pivot on the sketch's origin")
        for k, degrees in ((1, 120), (2, 240)):
            self.assert_centre(record["Instances"][(0, k, 0)], turned(4, 7, degrees))
        self.clicks([EMPTY])
        self.assertEqual(len(self.patterns()), 1, "Expected the click on empty canvas to commit")
        self.assertEqual(self.sketch.GeometryCount, 7)
        # the tool has ended: a further click on the other line picks no seed
        self.clicks([LINE_MIDDLE])
        self.assertEqual(self.record()["Seeds"], [CIRCLE])
        self.assertEqual(self.sketch.GeometryCount, 7)
        # one undo step
        self.doc.undo()
        self.flush_gui(200)
        self.assertEqual(self.patterns(), [])
        self.assertEqual(self.sketch.GeometryCount, 4)

    def test_escape_leaves_nothing(self):
        self.start("Sketcher_CircularPattern")
        self.clicks([CIRCLE_EDGE])
        self.assertEqual(self.sketch.GeometryCount, 7)
        self.escape()
        self.assertEqual(self.patterns(), [])
        self.assertEqual(self.sketch.GeometryCount, 4)
        self.assert_centre(CIRCLE, V(4, 7, 0))

    def test_a_second_pick_adds_a_seed_and_a_click_on_it_again_drops_it(self):
        self.start("Sketcher_CircularPattern")
        self.clicks([CIRCLE_EDGE, LINE_MIDDLE])
        self.assertEqual(self.record()["Seeds"], [CIRCLE, LINE])
        # the pivot and two copies of each seed
        self.assertEqual(self.sketch.GeometryCount, 9)
        self.clicks([LINE_MIDDLE])
        self.assertEqual(self.record()["Seeds"], [CIRCLE])
        self.assertEqual(self.sketch.GeometryCount, 7)
        self.clicks([CIRCLE_EDGE])
        self.assertEqual(self.patterns(), [], "Expected no pattern with no seed left")
        self.assertEqual(self.sketch.GeometryCount, 4)
        self.escape()
        self.assertEqual(self.sketch.GeometryCount, 4)

    def test_the_linear_tool_makes_three_along_x_and_enter_commits(self):
        self.start("Sketcher_LinearPattern")
        self.clicks([CIRCLE_EDGE])
        record = self.record()
        self.assertEqual(record["Kind"], "Linear")
        self.assertEqual(record["Counts"], (3, 1))
        # the direction line and two copies
        self.assertEqual(self.sketch.GeometryCount, 7)
        for a in (1, 2):
            self.assert_centre(record["Instances"][(0, a, 0)], V(4 + a, 7, 0))
        self.enter()
        self.assertEqual(len(self.patterns()), 1, "Expected Enter to commit")
        self.clicks([LINE_MIDDLE])
        self.assertEqual(self.record()["Seeds"], [CIRCLE], "Expected the tool to have ended")

    def test_a_selection_is_the_first_seed(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, f"Edge{CIRCLE + 1}")
        self.flush_gui(200)
        FreeCADGui.runCommand("Sketcher_CircularPattern")
        self.flush_gui(300)
        self.assertEqual(self.record()["Seeds"], [CIRCLE])
        self.escape()
        self.assertEqual(self.patterns(), [])

    def test_edit_pattern_is_offered_for_a_patterns_geometry_only(self):
        self.start("Sketcher_CircularPattern")
        self.clicks([CIRCLE_EDGE, EMPTY])
        record = self.record()
        copy = record["Instances"][(0, 1, 0)]
        for geoId, offered in ((copy, True), (CIRCLE, True), (record["Pivot"], True), (3, False)):
            FreeCADGui.Selection.clearSelection()
            name = f"Edge{geoId + 1}"
            if self.sketch.Geometry[geoId].TypeId == "Part::GeomPoint":
                vertex = next(
                    i for i in range(64) if self.sketch.getGeoVertexIndex(i) == (geoId, 1)
                )
                name = f"Vertex{vertex + 1}"
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, name)
            self.flush_gui(200)
            self.assertEqual(FreeCADGui.isCommandActive("Sketcher_EditPattern"), offered, name)
        FreeCADGui.Selection.clearSelection()
        (index,) = self.patterns()
        FreeCADGui.Selection.addSelection(
            self.doc.Name, self.sketch.Name, f"Constraint{index + 1}"
        )
        self.flush_gui(200)
        self.assertTrue(FreeCADGui.isCommandActive("Sketcher_EditPattern"))
