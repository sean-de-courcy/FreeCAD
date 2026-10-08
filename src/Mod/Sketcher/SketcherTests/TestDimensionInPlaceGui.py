# SPDX-License-Identifier: LGPL-2.1-or-later

"""A dimension's value typed in place (ops#145).

After a driving dimension is placed, or on a double-click on its label, a frameless value field
(the popup "SketcherDatumInPlace") opens at the label. Enter applies the value, Tab moves to the
next field of the same placement (a lock's DistanceY), Esc keeps the measured value. A typed
spreadsheet alias becomes the constraint's expression. A placement is one undo step.

The popup runs its own event loop, so each test arms a timer that answers the fields as they
open (answer_fields) before running the command.
"""

import math

import FreeCAD
import Part
import Sketcher
from PySide import QtCore, QtGui
from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

try:
    from PySide6.QtTest import QTest
except ImportError:
    QTest = None

V = FreeCAD.Vector

SKETCHER_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher"
DIMENSIONING_PARAMS = SKETCHER_PARAMS + "/dimensioning"
AUTO_SCALE_NEVER = 1  # SketcherGui::AutoScaleMode::Never

POPUP_NAME = "SketcherDatumInPlace"
POPUP_VALUE_NAME = "SketcherDatumInPlaceValue"

# A top view centred on (5, 5) of the sketch (XY plane), 30 mm high: everything the tests draw
# is inside it, away from the edges.
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


class TestDimensionInPlaceGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        if QTest is None:
            self.skipTest("PySide6.QtTest isn't available")
        if not QtGui.QFontDatabase.families():
            # Off screen without QT_QPA_FONTDIR: drawing the constraint icons throws, and the
            # run deadlocks instead of failing (notes/build.md).
            self.skipTest("Qt has no fonts; off screen, set QT_QPA_FONTDIR")

        self.saved_params = []
        self.set_param(SKETCHER_PARAMS, "Bool", "ShowDialogOnDistanceConstraint", True)
        self.set_param(SKETCHER_PARAMS, "Bool", "DimensionValueInPlace", True)
        self.set_param(SKETCHER_PARAMS, "Bool", "ContinuousCreationMode", False)
        self.set_param(DIMENSIONING_PARAMS, "Int", "AutoScaleMode", AUTO_SCALE_NEVER)
        self.set_param(DIMENSIONING_PARAMS, "Bool", "DimensioningDiameter", False)
        self.set_param(DIMENSIONING_PARAMS, "Bool", "DimensioningRadius", True)

        self.answerers = []
        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.doc = FreeCAD.newDocument("TestDimensionInPlaceGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.doc.recompute()

    def tearDown(self):
        try:
            for state in getattr(self, "answerers", []):
                state["stop"] = True
            super().tearDown()
        finally:
            for path, kind, name, had, value in reversed(getattr(self, "saved_params", [])):
                group = FreeCAD.ParamGet(path)
                if had:
                    getattr(group, "Set" + kind)(name, value)
                else:
                    getattr(group, "Rem" + kind)(name)

    # Preferences ---------------------------------------------------------------------------

    def set_param(self, path, kind, name, value):
        group = FreeCAD.ParamGet(path)
        names = getattr(group, "Get" + kind + "s")()
        had = name in names
        old = getattr(group, "Get" + kind)(name) if had else None
        self.saved_params.append((path, kind, name, had, old))
        getattr(group, "Set" + kind)(name, value)

    # Models ----------------------------------------------------------------------------------

    def add_line(self, start=V(0, 0, 0), end=V(10, 0, 0), *, anchored=True, blocked=False):
        """Line 0. Anchored: its start on the origin and horizontal, so only its end moves.
        Blocked: both ends fixed by a Block constraint."""
        sketch = self.sketch
        sketch.addGeometry(Part.LineSegment(start, end), False)
        if blocked:
            sketch.addConstraint(Sketcher.Constraint("Block", 0))
        elif anchored:
            sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
            sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.doc.recompute()

    def add_sheet(self, cell_value, alias="width", name="Sheet"):
        sheet = self.doc.addObject("Spreadsheet::Sheet", name)
        sheet.set("B1", cell_value)
        sheet.setAlias("B1", alias)
        self.doc.recompute()
        return sheet

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
        # The task dialog's open transaction counts in UndoCount: read it after setEdit.
        self.undo_start = self.doc.UndoCount

    def screen_point(self, x, y):
        """The viewport point (widget coordinates) of sketch point (x, y)."""
        return self.viewport_to_qpoint(
            self.view, self.viewport, self.view.getPointOnScreen(V(x, y, 0))
        )

    def run_with_selection(self, subelements, command):
        FreeCADGui.Selection.clearSelection()
        for sub in subelements:
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, sub)
        FreeCADGui.runCommand(command)
        self.flush_gui(100)

    def answer_fields(self, steps, timeout_ms=6000, allowed_modal=None):
        """Answers the value fields as they open, one step each: a dict with "text" to type
        (replacing the selection; None types nothing), "act" (a function of the popup and its
        line edit, for keys sent by hand), "key" to send, and "window" to type
        through the popup's window (shortcut map first, as a user's key). Any other modal
        window is rejected, so a failure doesn't hang the run. Returns the state, whose "seen"
        list records, per step, the popup's id, its global centre, the field's text and tooltip
        and whether the popup was still open after the key. (Python may reuse a closed popup's
        id for the next one: compare ids only while the first is still open.) A modal window
        whose object name is allowed_modal is left to the test."""
        state = {
            "stop": False,
            "seen": [],
            "rejected": [],
            "steps": list(steps),
            "done": not steps,
            "waited": 0,
        }
        self.answerers.append(state)

        def poll():
            if state["stop"] or state["done"]:
                return
            popup = QtGui.QApplication.activePopupWidget()
            if popup is not None and popup.objectName() == POPUP_NAME:
                step = state["steps"].pop(0)
                self.answer(popup, step, state)
                if not state["steps"]:
                    state["done"] = True
                    return
            else:
                modal = QtGui.QApplication.activeModalWidget()
                if modal is not None and modal.objectName() != allowed_modal:
                    state["rejected"].append(modal.metaObject().className())
                    modal.reject()
                state["waited"] += 50
                if state["waited"] > timeout_ms:
                    state["stop"] = True
                    return
            QtCore.QTimer.singleShot(50, poll)

        QtCore.QTimer.singleShot(50, poll)
        return state

    def answer(self, popup, step, state):
        box = popup.findChild(QtGui.QAbstractSpinBox, POPUP_VALUE_NAME)
        edit = box.findChild(QtGui.QLineEdit)
        record = {
            "popup": id(popup),
            "centre": popup.geometry().center(),
            "text_before": edit.text(),
        }
        if "before" in step:
            step["before"](popup, record)

        text = step.get("text")
        if text is not None:
            edit.selectAll()
            if step.get("window"):
                window = popup.windowHandle()
                for char in text:
                    QTest.keyClick(window, char)
            else:
                QTest.keyClicks(edit, text)
        act = step.get("act")
        if act is not None:
            act(popup, edit)
        key = step.get("key")
        if key is not None:
            modifier = step.get("modifier", QtCore.Qt.NoModifier)
            if step.get("window"):
                QTest.keyClick(popup.windowHandle(), key, modifier)
            else:
                QTest.keyClick(edit, key, modifier)

        record["open_after"] = QtGui.QApplication.activePopupWidget() is popup
        record["tooltip"] = box.toolTip()
        state["seen"].append(record)

    def wait_answered(self, state, count):
        self.assertTrue(
            self.wait_until(lambda: len(state["seen"]) >= count or state["stop"], 6000),
            f"Expected {count} value field(s) to open",
        )
        self.assertEqual(state["rejected"], [], "Expected no other modal window")
        self.assertEqual(len(state["seen"]), count, "Expected the value fields to open")

    def assert_no_field(self, state):
        self.flush_gui(400)
        state["stop"] = True
        self.assertEqual(state["seen"], [], "Expected no value field")
        self.assertEqual(state["rejected"], [], "Expected no modal window")
        self.assertIsNone(QtGui.QApplication.activePopupWidget())

    # Reading the result ----------------------------------------------------------------------

    def constraints_of(self, kind):
        return [c for c in self.sketch.Constraints if c.Type == kind]

    def assert_point(self, actual, x, y, tolerance=1e-7):
        self.assertLess(
            (actual - V(x, y, 0)).Length,
            tolerance,
            f"Expected ({x}, {y}), got {actual}",
        )

    def line_end(self):
        self.doc.recompute()
        return self.sketch.Geometry[0].EndPoint

    def expressions(self):
        return dict(self.sketch.ExpressionEngine)

    def assert_one_undo_step(self):
        self.assertFalse(self.doc.HasPendingTransaction, "Expected no transaction left open")
        self.assertEqual(self.doc.UndoCount, self.undo_start + 1, "Expected one undo step")

    def place_distance(self, steps, allowed_modal=None):
        """Line 0 anchored at the origin, then Distance on it with the given answers."""
        self.add_line()
        self.start_edit()
        state = self.answer_fields(steps, allowed_modal=allowed_modal)
        self.run_with_selection(["Edge1"], "Sketcher_ConstrainDistance")
        return state

    # D1-D8: the individual tools ---------------------------------------------------------------

    def test_d1_enter_applies_the_typed_value(self):
        """D1: typing 25 and Enter sets the new Distance to 25 and moves the free end to
        (25, 0). The placement is one undo step; undo removes the constraint and the end goes
        back to (10, 0)."""
        state = self.place_distance([{"text": "25", "key": QtCore.Qt.Key_Return}])
        self.wait_answered(state, 1)

        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertTrue(distances[0].Driving)
        self.assertAlmostEqual(distances[0].Value, 25.0, places=9)
        self.assert_point(self.line_end(), 25, 0)
        self.assert_one_undo_step()

        self.doc.undo()
        self.assertEqual(self.constraints_of("Distance"), [])
        self.assert_point(self.line_end(), 10, 0)

    def test_d2_escape_keeps_the_measured_value(self):
        """D2: Esc keeps the new Distance at its measured 10 (the dialog deleted it)."""
        state = self.place_distance([{"text": "25", "key": QtCore.Qt.Key_Escape}])
        self.wait_answered(state, 1)

        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertAlmostEqual(distances[0].Value, 10.0, places=9)
        self.assert_point(self.line_end(), 10, 0)
        self.assert_one_undo_step()

    def test_d3_field_opens_at_the_label(self):
        """D3: the field is centred on the label's text. For the horizontal Distance from
        (0, 0) to (10, 0), with label distance d and label position p, the text centre is at
        (5 + p, d) in the sketch, which is inside the view."""
        expected = {}

        def measure(popup, record):
            distance = self.constraints_of("Distance")[0]
            point = self.screen_point(5 + distance.LabelPosition, distance.LabelDistance)
            expected["inside"] = self.viewport.rect().contains(point)
            expected["centre"] = self.viewport.mapToGlobal(point)

        state = self.place_distance([{"before": measure, "key": QtCore.Qt.Key_Escape}])
        self.wait_answered(state, 1)

        self.assertTrue(expected["inside"], "Expected the label inside the view")
        centre = state["seen"][0]["centre"]
        offset = centre - expected["centre"]
        self.assertLessEqual(
            math.hypot(offset.x(), offset.y()),
            20,
            f"Expected the field at the label's text {expected['centre']}, got {centre}",
        )

    def test_d4_alias_stays_linked(self):
        """D4: typing a spreadsheet alias links the Distance to the cell: the end goes to the
        cell's 40 mm, the expression engine holds the alias, and a new cell value of 55 mm moves
        the end to (55, 0) at the next recompute."""
        sheet = self.add_sheet("40 mm")
        state = self.place_distance([{"text": "Sheet.width", "key": QtCore.Qt.Key_Return}])
        self.wait_answered(state, 1)

        self.assert_point(self.line_end(), 40, 0)
        self.assertIn("width", " ".join(self.expressions().values()))
        self.assert_one_undo_step()

        sheet.set("B1", "55 mm")
        self.doc.recompute()
        self.assert_point(self.line_end(), 55, 0)

    def test_d4_unitless_alias_stays_linked(self):
        """D4 with a unitless cell: 40 is read as 40 mm."""
        sheet = self.add_sheet("40")
        state = self.place_distance([{"text": "Sheet.width", "key": QtCore.Qt.Key_Return}])
        self.wait_answered(state, 1)

        self.assert_point(self.line_end(), 40, 0)
        self.assertIn("width", " ".join(self.expressions().values()))

        sheet.set("B1", "55")
        self.doc.recompute()
        self.assert_point(self.line_end(), 55, 0)

    def test_d5_arithmetic_is_a_value(self):
        """D5: 10+5 sets 15, with no expression."""
        state = self.place_distance([{"text": "10+5", "key": QtCore.Qt.Key_Return}])
        self.wait_answered(state, 1)

        self.assertAlmostEqual(self.constraints_of("Distance")[0].Value, 15.0, places=9)
        self.assertEqual(self.expressions(), {})
        self.assert_point(self.line_end(), 15, 0)

    def test_d6_alias_letters_are_not_shortcuts(self):
        """D6: an alias spelled with letters that start Sketcher shortcuts (g, l, ...), typed
        through the window as a user's keys go, stays in the field: the Distance is linked as
        in D4, and nothing else ran (same geometry, still in edit)."""
        self.add_sheet("40 mm", alias="glen", name="sh")
        state = self.place_distance(
            [{"text": "sh.glen", "key": QtCore.Qt.Key_Return, "window": True}]
        )
        self.wait_answered(state, 1)

        self.assertEqual(state["seen"][0]["open_after"], False)
        self.assertEqual(self.sketch.GeometryCount, 1)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit())
        self.assert_point(self.line_end(), 40, 0)
        self.assertIn("glen", " ".join(self.expressions().values()))

    def test_d7_invalid_value_keeps_the_field_open(self):
        """D7: 0 is no distance: Enter keeps the field open with the reason in its tooltip,
        and the Distance stays 10. Then 5 and Enter sets 5."""
        state = self.place_distance(
            [
                {"text": "0", "key": QtCore.Qt.Key_Return},
                {"text": "5", "key": QtCore.Qt.Key_Return},
            ]
        )
        self.wait_answered(state, 2)

        first, second = state["seen"]
        self.assertTrue(first["open_after"], "Expected the field to stay open after 0")
        self.assertIn("zero", first["tooltip"].lower())
        self.assertEqual(first["popup"], second["popup"], "Expected the same field")
        self.assertFalse(second["open_after"])
        self.assertAlmostEqual(self.constraints_of("Distance")[0].Value, 5.0, places=9)
        self.assert_point(self.line_end(), 5, 0)
        self.assert_one_undo_step()

    def test_d8_reference_dimension_gets_no_field(self):
        """D8: a Distance on a blocked line is a Reference: no field, value 10, one step."""
        self.add_line(blocked=True)
        self.start_edit()
        state = self.answer_fields([{"key": QtCore.Qt.Key_Escape}], timeout_ms=1000)
        self.run_with_selection(["Edge1"], "Sketcher_ConstrainDistance")
        self.assert_no_field(state)

        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertFalse(distances[0].Driving)
        self.assertAlmostEqual(distances[0].Value, 10.0, places=9)
        self.assert_one_undo_step()

    # D9-D11: the Dimension tool -----------------------------------------------------------------

    def place_lock(self, steps, arm=None):
        """Point (2, 1); the Dimension tool on it in lock mode (M), finished by a click in empty
        space. The fields are answered with steps, or by arm() if given. Returns the answering
        state."""
        self.sketch.addGeometry(Part.Point(V(2, 1, 0)), False)
        self.doc.recompute()
        self.start_edit()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Vertex1")
        FreeCADGui.runCommand("Sketcher_Dimension")
        self.flush_gui(150)

        empty = self.screen_point(8, 9)
        self.move(self.viewport, empty)
        self.key_click(self.viewport, QtCore.Qt.Key_M, "m")
        self.assertTrue(
            self.wait_until(
                lambda: len(self.constraints_of("DistanceX")) == 1
                and len(self.constraints_of("DistanceY")) == 1,
                2000,
            ),
            f"Expected M to switch the tool to a lock, got "
            f"{[c.Type for c in self.sketch.Constraints]}",
        )

        state = arm() if arm else self.answer_fields(steps)
        self.move(self.viewport, empty)
        self.click(self.viewport, empty)
        return state

    def point(self):
        self.doc.recompute()
        return self.sketch.getPoint(0, 1)

    def test_d9_lock_tab_moves_to_the_second_field(self):
        """D9: 3, Tab, 4, Enter: DistanceX = 3 and DistanceY = 4, the point at (3, 4), in one
        undo step; undo restores (2, 1) with no constraints."""
        state = self.place_lock(
            [
                {"text": "3", "key": QtCore.Qt.Key_Tab},
                {"text": "4", "key": QtCore.Qt.Key_Return},
            ]
        )
        self.wait_answered(state, 2)

        self.assertAlmostEqual(self.constraints_of("DistanceX")[0].Value, 3.0, places=9)
        self.assertAlmostEqual(self.constraints_of("DistanceY")[0].Value, 4.0, places=9)
        self.assert_point(self.point(), 3, 4)
        self.assert_one_undo_step()

        self.doc.undo()
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assert_point(self.point(), 2, 1)

    def test_d10_lock_escape_keeps_the_rest_measured(self):
        """D10: 3, Tab, Esc: DistanceX = 3 and DistanceY keeps its measured 1."""
        state = self.place_lock(
            [
                {"text": "3", "key": QtCore.Qt.Key_Tab},
                {"key": QtCore.Qt.Key_Escape},
            ]
        )
        self.wait_answered(state, 2)

        self.assertAlmostEqual(self.constraints_of("DistanceX")[0].Value, 3.0, places=9)
        self.assertAlmostEqual(self.constraints_of("DistanceY")[0].Value, 1.0, places=9)
        self.assert_point(self.point(), 3, 1)
        self.assert_one_undo_step()

    def answer_dialogs(self, texts):
        """Fills in and accepts the modal datum dialog once per text, in order."""
        state = {"stop": False, "answered": [], "waited": 0}
        self.answerers.append(state)
        texts = list(texts)

        def fill():
            if state["stop"] or not texts:
                return
            dialog = QtGui.QApplication.activeModalWidget()
            spinbox = dialog.findChild(QtGui.QAbstractSpinBox, "labelEdit") if dialog else None
            if spinbox is not None and id(dialog) not in [a[0] for a in state["answered"]]:
                text = texts.pop(0)
                line_edit = spinbox.findChild(QtGui.QLineEdit)
                line_edit.selectAll()
                line_edit.insert(text)
                state["answered"].append((id(dialog), text))
                dialog.accept()
            else:
                state["waited"] += 50
                if state["waited"] > 6000:
                    return
            QtCore.QTimer.singleShot(50, fill)

        QtCore.QTimer.singleShot(50, fill)
        return state

    def test_d9_dialog_lock_is_one_step(self):
        """D9 with the dialog (DimensionValueInPlace off): both of the lock's values (3 and 3,
        so their order doesn't matter here; D9 checks it) land in the placement's one undo
        step: undo goes back to (2, 1), redo to (3, 3). The report that redo lost the second
        value didn't reproduce on the base (the order was reversed, which D9 checks); this
        stays as a regression test."""
        self.set_param(SKETCHER_PARAMS, "Bool", "DimensionValueInPlace", False)
        state = self.place_lock(None, arm=lambda: self.answer_dialogs(["3 mm", "3 mm"]))
        self.assertTrue(
            self.wait_until(lambda: len(state["answered"]) == 2, 6000),
            "Expected two dialogs",
        )
        self.flush_gui(100)

        self.assert_point(self.point(), 3, 3)
        self.assert_one_undo_step()

        self.doc.undo()
        self.assertEqual(len(self.sketch.Constraints), 0)
        self.assert_point(self.point(), 2, 1)

        self.doc.redo()
        values = sorted(c.Value for c in self.sketch.Constraints if c.Type.startswith("Distance"))
        self.assertEqual(len(values), 2)
        self.assertAlmostEqual(values[0], 3.0, places=9)
        self.assertAlmostEqual(values[1], 3.0, places=9)
        self.assert_point(self.point(), 3, 3)

    def test_d11_dimension_tool_radius(self):
        """D11: the Dimension tool on a circle of radius 5 (radius mode), 7 and Enter: r = 7."""
        self.sketch.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5), False)
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        self.doc.recompute()
        self.start_edit()

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge1")
        FreeCADGui.runCommand("Sketcher_Dimension")
        self.flush_gui(150)
        self.assertEqual(len(self.constraints_of("Radius")), 1)

        state = self.answer_fields([{"text": "7", "key": QtCore.Qt.Key_Return}])
        empty = self.screen_point(12, 12)
        self.move(self.viewport, empty)
        self.click(self.viewport, empty)
        self.wait_answered(state, 1)

        self.doc.recompute()
        self.assertAlmostEqual(self.sketch.Geometry[0].Radius, 7.0, places=7)
        self.assert_one_undo_step()

    # D12: angle --------------------------------------------------------------------------------

    def test_d12_angle(self):
        """D12: lines from (0, 0) along 0 deg (blocked) and 30 deg; Angle, 45 and Enter: the
        second line's direction is at 45 deg."""
        sketch = self.sketch
        cos30, sin30 = math.cos(math.radians(30)), math.sin(math.radians(30))
        sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)), False)
        sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10 * cos30, 10 * sin30, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Block", 0))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, 1, 1))
        self.doc.recompute()
        self.start_edit()

        state = self.answer_fields([{"text": "45", "key": QtCore.Qt.Key_Return}])
        self.run_with_selection(["Edge1", "Edge2"], "Sketcher_ConstrainAngle")
        self.wait_answered(state, 1)

        self.doc.recompute()
        line = self.sketch.Geometry[1]
        direction = line.EndPoint - line.StartPoint
        self.assertAlmostEqual(math.atan2(direction.y, direction.x), math.radians(45), places=9)
        self.assert_one_undo_step()

    # D13-D16 -----------------------------------------------------------------------------------

    def test_d13_double_click_edits_in_place(self):
        """D13: a double-click on the label of a Distance of 25 opens the field there; 30 and
        Enter set 30 in one "Modify sketch constraints" step."""
        self.add_line(end=V(25, 0, 0))
        self.sketch.addConstraint(Sketcher.Constraint("Distance", 0, 25.0))
        self.doc.recompute()
        self.start_edit()

        # Double-click edits the preselected constraint: look around the label's text centre
        # for a point that preselects the Distance, as TestConstraintPreselectionGui does.
        import SketcherGui

        distance = self.sketch.Constraints[2]
        centre = self.view.getPointOnViewport(
            V(12.5 + distance.LabelPosition, distance.LabelDistance, 0)
        )
        label = None
        for radius in range(0, 41, 2):
            for dy in range(-radius, radius + 1, 2):
                for dx in range(-radius, radius + 1, 2):
                    if max(abs(dx), abs(dy)) != radius:
                        continue
                    coin = (int(centre[0]) + dx, int(centre[1]) + dy)
                    info = SketcherGui.getActiveSketchPreselection(coin)
                    if info and "Constraint3" in (info.get("SubElementNames") or []):
                        label = self.viewport_to_qpoint(self.view, self.viewport, coin)
                        break
                if label is not None:
                    break
            if label is not None:
                break
        if label is None:
            # Off screen the label has no pick area: SoDatumLabel sizes it when it is first
            # rendered (drawImage), and the off-screen view never renders.
            self.skipTest("The datum label isn't pickable here (off screen, never rendered)")
        self.move(self.viewport, label)
        presel = FreeCADGui.Selection.getPreselection()
        self.assertEqual(list(presel.SubElementNames), ["Constraint3"])

        state = self.answer_fields([{"text": "30", "key": QtCore.Qt.Key_Return}])
        self.click(self.viewport, label)
        self.click(self.viewport, label)
        self.wait_answered(state, 1)

        self.assertAlmostEqual(self.sketch.Constraints[2].Value, 30.0, places=9)
        self.assert_point(self.line_end(), 30, 0)
        self.assert_one_undo_step()
        self.assertEqual(self.doc.UndoNames[0], "Modify sketch constraints")

    def test_d14_dialog_when_in_place_is_off(self):
        """D14: with DimensionValueInPlace off, the modal dialog opens, not the field."""
        self.set_param(SKETCHER_PARAMS, "Bool", "DimensionValueInPlace", False)
        self.add_line()
        self.start_edit()

        seen = {"dialog": False}

        def fill():
            dialog = QtGui.QApplication.activeModalWidget()
            spinbox = dialog.findChild(QtGui.QAbstractSpinBox, "labelEdit") if dialog else None
            if spinbox is None:
                QtCore.QTimer.singleShot(50, fill)
                return
            seen["dialog"] = True
            seen["popup"] = QtGui.QApplication.activePopupWidget()
            line_edit = spinbox.findChild(QtGui.QLineEdit)
            line_edit.selectAll()
            line_edit.insert("20 mm")
            dialog.accept()

        QtCore.QTimer.singleShot(50, fill)
        self.run_with_selection(["Edge1"], "Sketcher_ConstrainDistance")
        self.assertTrue(self.wait_until(lambda: seen["dialog"], 3000), "Expected the dialog")
        self.assertIsNone(seen["popup"])
        self.assertAlmostEqual(self.constraints_of("Distance")[0].Value, 20.0, places=9)
        self.assert_one_undo_step()

    def test_d15_no_editor_when_asking_is_off(self):
        """D15: with ShowDialogOnDistanceConstraint off, no editor: the measured 10 stays."""
        self.set_param(SKETCHER_PARAMS, "Bool", "ShowDialogOnDistanceConstraint", False)
        state = self.place_distance([{"key": QtCore.Qt.Key_Escape}])
        self.assert_no_field(state)

        self.assertAlmostEqual(self.constraints_of("Distance")[0].Value, 10.0, places=9)
        self.assert_one_undo_step()

    def test_d16_conflicting_sketch_commits(self):
        """D16: in a sketch with a conflict (two DistanceX on one line, 10 and 12), a new
        Distance gets no field and its transaction is closed: one undo step."""
        sketch = self.sketch
        sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 10.0))
        sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 12.0))
        self.doc.recompute()
        self.start_edit()

        state = self.answer_fields([{"key": QtCore.Qt.Key_Escape}], timeout_ms=1000)
        self.run_with_selection(["Edge1"], "Sketcher_ConstrainDistance")
        self.assert_no_field(state)

        self.assertEqual(len(self.constraints_of("Distance")), 1)
        self.assert_one_undo_step()

    # D17-D19: the review of fork PR 139 --------------------------------------------------------

    def add_triangle(self):
        """Right triangle (0, 0), (4, 0), (0, 3): line 0 (4 long, horizontal from the origin),
        line 1 (from (4, 0) to (0, 3), the hypotenuse, 5 long), line 2 (3 long, back down to
        the origin), closed by coincidences; the legs fixed at 4 and 3. The hypotenuse can take
        any length from 1 to 7 by turning the right angle, never 100."""
        sketch = self.sketch
        sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(4, 0, 0)), False)
        sketch.addGeometry(Part.LineSegment(V(4, 0, 0), V(0, 3, 0)), False)
        sketch.addGeometry(Part.LineSegment(V(0, 3, 0), V(0, 0, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))
        sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 1, 2, 2, 1))
        sketch.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 0, 1))
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 4.0))
        sketch.addConstraint(Sketcher.Constraint("Distance", 2, 3.0))
        self.doc.recompute()

    def test_d17_retry_after_a_solver_failure(self):
        """D17: on the triangle's hypotenuse, 100 fails in the solver (the legs allow 1 to 7):
        the field stays open. Then 6 and Enter sets 6. The failed setDatum replaced the
        constraint objects; the retry must not use the old one."""
        self.add_triangle()
        self.start_edit()
        state = self.answer_fields(
            [
                {"text": "100", "key": QtCore.Qt.Key_Return},
                {"text": "6", "key": QtCore.Qt.Key_Return},
            ]
        )
        self.run_with_selection(["Edge2"], "Sketcher_ConstrainDistance")
        self.wait_answered(state, 2)

        first, second = state["seen"]
        self.assertTrue(first["open_after"], "Expected the field to stay open after 100")
        self.assertFalse(second["open_after"])
        new = self.sketch.Constraints[-1]
        self.assertEqual(new.Type, "Distance")
        self.assertAlmostEqual(new.Value, 6.0, places=9)
        self.doc.recompute()
        self.assertAlmostEqual(self.sketch.Geometry[1].length(), 6.0, places=7)
        self.assert_one_undo_step()

    def test_d18_failed_link_then_escape_keeps_the_measured_value(self):
        """D18: the cell Sheet.width reads the sketch's Distance "a" (10); linking a new
        Distance to it would make the sketch depend on itself, so the link fails and the field
        stays open. Esc then keeps the new Distance at its measured 7, with no expression
        (the cell's 10 was applied before the link failed)."""
        sketch = self.sketch
        self.add_line()  # line 0, (0, 0) to (10, 0)
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10.0))
        sketch.renameConstraint(len(sketch.Constraints) - 1, "a")
        sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(0, 7, 0)), False)
        sketch.addConstraint(Sketcher.Constraint("Coincident", 1, 1, -1, 1))
        sketch.addConstraint(Sketcher.Constraint("Vertical", 1))
        self.doc.recompute()
        sheet = self.add_sheet("=Sketch.Constraints.a")
        self.assertAlmostEqual(sheet.width.Value, 10.0)

        self.start_edit()
        state = self.answer_fields(
            [
                {"text": "Sheet.width", "key": QtCore.Qt.Key_Return},
                {"key": QtCore.Qt.Key_Escape},
            ]
        )
        self.run_with_selection(["Edge2"], "Sketcher_ConstrainDistance")
        self.wait_answered(state, 2)

        first, second = state["seen"]
        self.assertTrue(first["open_after"], "Expected the cyclic link to keep the field open")
        self.assertFalse(second["open_after"])
        new = self.sketch.Constraints[-1]
        self.assertEqual(new.Type, "Distance")
        self.assertAlmostEqual(new.Value, 7.0, places=9)
        self.doc.recompute()
        self.assertAlmostEqual(self.sketch.Geometry[1].length(), 7.0, places=7)
        self.assertNotIn("width", " ".join(self.expressions().values()))
        self.assert_one_undo_step()

    def origin_marker_is_hollow(self):
        """The origin marker is hollow while a drawing tool is active (TestOnViewParameterGui)."""
        from pivy import coin

        search = coin.SoSearchAction()
        search.setName("OriginPointSet")
        search.setSearchingAll(True)
        search.apply(self.view.getViewer().getSoRenderManager().getSceneGraph())
        path = search.getPath()
        self.assertIsNotNone(path, "Expected the origin marker in the scene graph")
        index = path.getTail().markerIndex.getValues()[0]
        sizes = (5, 7, 9, 11, 13, 15, 20, 25, 30)
        return index in {FreeCADGui.getMarkerIndex("CIRCLE_LINE", size) for size in sizes}

    def test_d19_escape_keeps_the_dimension_tool_in_continuous_mode(self):
        """D19: with ContinuousCreationMode on, Esc in the field keeps the measured value and
        the Dimension tool stays active (the next Esc leaves it). The key's press and release
        go where Qt sends them: to the field while it's open, else to the 3D view, where the
        tools quit on Esc's release. The release comes a moment later, as a user's does: after
        the field's own event loop has ended."""
        self.set_param(SKETCHER_PARAMS, "Bool", "ContinuousCreationMode", True)
        self.add_line()
        self.start_edit()

        def escape(popup, edit):
            def key_event(kind):
                return QtGui.QKeyEvent(kind, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)

            def release():
                open_now = QtGui.QApplication.activePopupWidget() is popup
                target = edit if open_now else self.viewport
                QtGui.QApplication.sendEvent(target, key_event(QtCore.QEvent.KeyRelease))

            QtGui.QApplication.sendEvent(edit, key_event(QtCore.QEvent.KeyPress))
            QtCore.QTimer.singleShot(100, release)

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge1")
        FreeCADGui.runCommand("Sketcher_Dimension")
        self.flush_gui(150)
        self.assertTrue(self.origin_marker_is_hollow(), "Expected the Dimension tool active")

        state = self.answer_fields([{"text": "25", "act": escape}])
        empty = self.screen_point(8, 9)
        self.move(self.viewport, empty)
        self.click(self.viewport, empty)
        self.wait_answered(state, 1)
        self.assertTrue(
            self.wait_until(lambda: QtGui.QApplication.activePopupWidget() is None, 2000),
            "Expected Esc to close the field",
        )
        self.flush_gui(300)

        new = self.sketch.Constraints[-1]
        self.assertIn(new.Type, ("Distance", "DistanceX"))
        self.assertAlmostEqual(new.Value, 10.0, places=9)
        self.assertTrue(
            self.origin_marker_is_hollow(), "Expected the Dimension tool to stay active after Esc"
        )

    # D20: the dialog's OK after a Reference toggle (ops#172) -----------------------------------

    def test_d20_dialog_reference_toggled_then_diameter(self):
        """D20 (ops#172): in the dialog for a new Radius of 5, Reference on and off again,
        Diameter chosen and 14 typed: OK gives one driving Diameter of 14, the circle's radius
        is 7, in one undo step. Each Reference toggle replaces the constraint objects
        (setDriving); OK used to change the type through the old, deleted object, so the
        sketch kept a Radius and set it to 14."""
        self.set_param(SKETCHER_PARAMS, "Bool", "DimensionValueInPlace", False)
        self.sketch.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5), False)
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        self.doc.recompute()
        self.start_edit()

        seen = {"dialog": False}

        def fill():
            dialog = QtGui.QApplication.activeModalWidget()
            spinbox = dialog.findChild(QtGui.QAbstractSpinBox, "labelEdit") if dialog else None
            if spinbox is None:
                QtCore.QTimer.singleShot(50, fill)
                return
            seen["dialog"] = True
            reference = dialog.findChild(QtGui.QCheckBox, "cbDriving")
            reference.setChecked(True)
            seen["reference"] = not self.sketch.Constraints[-1].Driving
            reference.setChecked(False)
            dialog.findChild(QtGui.QRadioButton, "rbDiameter").setChecked(True)
            line_edit = spinbox.findChild(QtGui.QLineEdit)
            line_edit.selectAll()
            line_edit.insert("14 mm")
            dialog.accept()

        QtCore.QTimer.singleShot(50, fill)
        self.run_with_selection(["Edge1"], "Sketcher_ConstrainRadius")
        self.assertTrue(self.wait_until(lambda: seen["dialog"], 3000), "Expected the dialog")
        self.assertTrue(seen["reference"], "Expected the toggle to make the Radius a reference")

        self.assertEqual(self.constraints_of("Radius"), [])
        diameters = self.constraints_of("Diameter")
        self.assertEqual(len(diameters), 1)
        self.assertTrue(diameters[0].Driving)
        self.assertAlmostEqual(diameters[0].Value, 14.0, places=9)
        self.doc.recompute()
        self.assertAlmostEqual(self.sketch.Geometry[0].Radius, 7.0, places=7)
        self.assert_one_undo_step()

    # D21-D23: the review of fork PR 139, the gaps (ops#175) ------------------------------------

    def click_outside(self, popup, edit):
        """A click outside the field, as a user's: the open popup gets the mouse press."""
        QTest.mouseClick(
            popup, QtCore.Qt.LeftButton, QtCore.Qt.NoModifier, QtCore.QPoint(-20, -20)
        )

    def test_d21_click_outside_applies(self):
        """D21: 25 typed, then a click outside the field: the Distance is 25 and the free end
        at (25, 0), in one undo step."""
        state = self.place_distance([{"text": "25", "act": self.click_outside}])
        self.wait_answered(state, 1)

        self.assertFalse(state["seen"][0]["open_after"], "Expected the click to close the field")
        self.assertAlmostEqual(self.constraints_of("Distance")[0].Value, 25.0, places=9)
        self.assert_point(self.line_end(), 25, 0)
        self.assert_one_undo_step()

    def test_d22_click_outside_keeps_the_measured_value_on_invalid_input(self):
        """D22: 0 (no distance) typed, then a click outside: the field closes and the Distance
        keeps its measured 10, in one undo step."""
        state = self.place_distance([{"text": "0", "act": self.click_outside}])
        self.wait_answered(state, 1)

        self.assertFalse(state["seen"][0]["open_after"], "Expected the click to close the field")
        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertAlmostEqual(distances[0].Value, 10.0, places=9)
        self.assert_point(self.line_end(), 10, 0)
        self.assert_one_undo_step()

    def test_d23_lock_shift_tab_goes_back(self):
        """D23: the lock's fields: 3, Tab; 4, Shift+Tab back to the first field, which shows
        the applied 3; 5, Tab; the second field shows the applied 4; Enter. DistanceX = 5 and
        DistanceY = 4, the point at (5, 4), in one undo step."""
        state = self.place_lock(
            [
                {"text": "3", "key": QtCore.Qt.Key_Tab},
                {
                    "text": "4",
                    "key": QtCore.Qt.Key_Backtab,
                    "modifier": QtCore.Qt.ShiftModifier,
                },
                {"text": "5", "key": QtCore.Qt.Key_Tab},
                {"key": QtCore.Qt.Key_Return},
            ]
        )
        self.wait_answered(state, 4)

        self.assertTrue(state["seen"][2]["text_before"].startswith("3"), state["seen"][2])
        self.assertTrue(state["seen"][3]["text_before"].startswith("4"), state["seen"][3])
        self.assertAlmostEqual(self.constraints_of("DistanceX")[0].Value, 5.0, places=9)
        self.assertAlmostEqual(self.constraints_of("DistanceY")[0].Value, 4.0, places=9)
        self.assert_point(self.point(), 5, 4)
        self.assert_one_undo_step()

    def formula_editor(self):
        """The formula editor (DlgExpressionInput) on screen, or None."""
        for widget in QtGui.QApplication.topLevelWidgets():
            if widget.objectName() == "DlgExpressionInput" and widget.isVisible():
                return widget
        return None

    def answer_formula_editor(self, formula, text="Sheet.width", button="accept"):
        """Answers the formula editor when it opens: types `text` (None types nothing), then
        presses `button` ("accept" for OK, "reject" for Cancel and Esc, "reset" for Reset).
        `formula` records "opened" and "field_open". An editor that is on screen but never
        becomes modal is rejected after a while, so a failure can't leave it blocking the run."""
        formula["waited"] = formula.get("waited", 0)

        def poll():
            dialog = self.formula_editor()
            if dialog is None or QtGui.QApplication.activeModalWidget() is not dialog:
                formula["waited"] += 20
                if formula["waited"] < 6000:
                    QtCore.QTimer.singleShot(20, poll)
                elif dialog is not None:
                    dialog.reject()
                return
            formula["opened"] = True
            formula["field_open"] = QtGui.QApplication.activePopupWidget() is not None
            if text is not None:
                dialog.findChild(QtGui.QPlainTextEdit, "expression").setPlainText(text)
                self.pump(100)
            if button == "accept":
                dialog.accept()
            elif button == "reject":
                dialog.reject()
            else:
                box = dialog.findChild(QtGui.QDialogButtonBox, "buttonBox")
                box.button(QtGui.QDialogButtonBox.Reset).click()

        QtCore.QTimer.singleShot(20, poll)

    def type_equals(self, formula, **options):
        """A step's "act": = typed through the window, as a user's key, with the formula editor
        answered as `options` say."""

        def act(popup, edit):
            self.answer_formula_editor(formula, **options)
            QTest.keyClick(popup.windowHandle(), "=")

        return act

    def test_d24_equals_opens_the_formula_editor(self):
        """D24 (ops#203): = typed in the field (through the window, as a user's key) opens the
        formula editor, and the field waits behind it; Sheet.width there and OK brings the
        field back showing 40, then Enter: the Distance is linked to the cell, the free end at
        (40, 0), in one undo step; the cell set to 55 mm moves it to (55, 0)."""
        sheet = self.add_sheet("40 mm")
        formula = {}
        state = self.place_distance(
            [{"act": self.type_equals(formula)}, {"key": QtCore.Qt.Key_Return}],
            allowed_modal="DlgExpressionInput",
        )
        self.wait_answered(state, 2)

        self.assertTrue(formula.get("opened"), "Expected = to open the formula editor, modal")
        self.assertFalse(formula.get("field_open"), "Expected the field hidden under the editor")
        self.assertIsNone(self.formula_editor(), "Expected OK to close the formula editor")
        self.assertTrue(state["seen"][1]["text_before"].startswith("40"), state["seen"][1])
        self.assertFalse(state["seen"][1]["open_after"], "Expected Enter to close the field")
        self.assert_point(self.line_end(), 40, 0)
        self.assertIn("Sheet.width", " ".join(self.expressions().values()))
        self.assert_one_undo_step()

        sheet.set("B1", "55 mm")
        self.doc.recompute()
        self.assert_point(self.line_end(), 55, 0)

    def test_d25_escape_after_a_formula_keeps_the_measured_value(self):
        """D25 (ops#203 review M1): = and Sheet.width, OK; the field comes back showing 40, and
        Esc: nothing of the formula is kept. The new Distance stays at its measured 10, with no
        expression, the free end at (10, 0), in one undo step."""
        self.add_sheet("40 mm")
        formula = {}
        state = self.place_distance(
            [{"act": self.type_equals(formula)}, {"key": QtCore.Qt.Key_Escape}],
            allowed_modal="DlgExpressionInput",
        )
        self.wait_answered(state, 2)

        self.assertTrue(formula.get("opened"), "Expected = to open the formula editor")
        self.assertTrue(state["seen"][1]["text_before"].startswith("40"), state["seen"][1])
        self.assertFalse(state["seen"][1]["open_after"], "Expected Esc to close the field")
        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertAlmostEqual(distances[0].Value, 10.0, places=9)
        self.assertEqual(self.expressions(), {})
        self.assert_point(self.line_end(), 10, 0)
        self.assert_one_undo_step()

    def test_d26_cancel_in_the_editor_keeps_the_typed_text(self):
        """D26 (ops#203 review): 12 typed, = and Cancel in the formula editor: the field comes
        back showing 12, and Enter applies 12, with no expression."""
        self.add_sheet("40 mm")
        formula = {}
        state = self.place_distance(
            [
                {"text": "12", "act": self.type_equals(formula, button="reject")},
                {"key": QtCore.Qt.Key_Return},
            ],
            allowed_modal="DlgExpressionInput",
        )
        self.wait_answered(state, 2)

        self.assertTrue(formula.get("opened"), "Expected = to open the formula editor")
        self.assertTrue(state["seen"][1]["text_before"].startswith("12"), state["seen"][1])
        self.assertAlmostEqual(self.constraints_of("Distance")[0].Value, 12.0, places=9)
        self.assertEqual(self.expressions(), {})
        self.assert_point(self.line_end(), 12, 0)
        self.assert_one_undo_step()

    def test_d27_reset_in_the_editor_gives_a_plain_value(self):
        """D27 (ops#203 review): Reset in the formula editor takes the formula away: the field
        comes back with a plain number, which typing replaces (it is selected, not appended
        to)."""
        self.add_sheet("40 mm")
        formula = {}
        state = self.place_distance(
            [
                {"act": self.type_equals(formula, text=None, button="reset")},
                {"text": "7", "key": QtCore.Qt.Key_Return},
            ],
            allowed_modal="DlgExpressionInput",
        )
        self.wait_answered(state, 2)

        self.assertTrue(formula.get("opened"), "Expected = to open the formula editor")
        self.assertAlmostEqual(self.constraints_of("Distance")[0].Value, 7.0, places=9)
        self.assertEqual(self.expressions(), {})
        self.assert_point(self.line_end(), 7, 0)

    def test_d28_a_formula_giving_no_distance_is_refused(self):
        """D28 (ops#203 review M2): the cell holds 0 mm: = and Sheet.width, OK, Enter: the
        field stays open with the reason in its tooltip, and nothing is applied. Esc then keeps
        the measured 10 and no expression."""
        self.add_sheet("0 mm")
        formula = {}
        state = self.place_distance(
            [
                {"act": self.type_equals(formula)},
                {"key": QtCore.Qt.Key_Return},
                {"key": QtCore.Qt.Key_Escape},
            ],
            allowed_modal="DlgExpressionInput",
        )
        self.wait_answered(state, 3)

        second = state["seen"][1]
        self.assertTrue(second["open_after"], "Expected the field to stay open on a zero")
        self.assertIn("zero", second["tooltip"].lower())
        distances = self.constraints_of("Distance")
        self.assertEqual(len(distances), 1)
        self.assertAlmostEqual(distances[0].Value, 10.0, places=9)
        self.assertEqual(self.expressions(), {})
        self.assert_point(self.line_end(), 10, 0)
        self.assert_one_undo_step()
