# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD
import Part
import Sketcher
from PySide import QtCore, QtGui
from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

DIMENSIONING_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher/dimensioning"
AUTO_SCALE_ALWAYS = 0  # SketcherGui::AutoScaleMode::Always


class TestAutoScaleNamesGui(SketcherGuiTestCase):
    """Setting the first dimension of a sketch scales the whole sketch (auto-scale). The scale
    deletes and re-adds the geometry and its constraints; the constraints keep their names."""

    def setUp(self):
        super().setUp()
        if not QtGui.QFontDatabase.families():
            # Off screen without QT_QPA_FONTDIR: drawing the constraint icons throws, and the
            # run deadlocks instead of failing.
            self.skipTest("Qt has no fonts; off screen, set QT_QPA_FONTDIR")

        params = FreeCAD.ParamGet(DIMENSIONING_PARAMS)
        self.saved_mode = (
            params.GetInt("AutoScaleMode") if "AutoScaleMode" in params.GetInts() else None
        )
        params.SetInt("AutoScaleMode", AUTO_SCALE_ALWAYS)

        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.doc = FreeCAD.newDocument("TestAutoScaleNamesGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.doc.recompute()

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            params = FreeCAD.ParamGet(DIMENSIONING_PARAMS)
            if not hasattr(self, "saved_mode"):
                pass
            elif self.saved_mode is None:
                params.RemInt("AutoScaleMode")
            else:
                params.SetInt("AutoScaleMode", self.saved_mode)

    def build_sketch(self):
        """An L of two lines away from the origin with named constraints; the only dimension,
        "Width", is the base's length of 6."""
        V = FreeCAD.Vector
        sketch = self.sketch
        sketch.addGeometry(Part.LineSegment(V(2, 1, 0), V(8, 1, 0)), False)
        sketch.addGeometry(Part.LineSegment(V(8, 1, 0), V(8, 5, 0)), False)
        named = (
            ("Corner", Sketcher.Constraint("Coincident", 0, 2, 1, 1)),
            ("Base", Sketcher.Constraint("Horizontal", 0)),
            ("Side", Sketcher.Constraint("Vertical", 1)),
            ("Width", Sketcher.Constraint("Distance", 0, 6.0)),
        )
        for name, constraint in named:
            index = sketch.addConstraint(constraint)
            sketch.renameConstraint(index, name)
        self.doc.recompute()
        return {name: constraint.Type for name, constraint in named}

    def set_datum_in_dialog(self, text):
        """Fill in and accept the modal datum dialog once it opens. Any other modal window is
        rejected, so the test fails instead of waiting forever."""
        state = {"done": False, "tries": 0}

        def fill():
            dialog = QtGui.QApplication.activeModalWidget()
            spinbox = dialog.findChild(QtGui.QAbstractSpinBox, "labelEdit") if dialog else None
            if spinbox is None:
                if dialog is not None:
                    dialog.reject()
                state["tries"] += 1
                if state["tries"] < 60:
                    QtCore.QTimer.singleShot(50, fill)
                return
            line_edit = spinbox.findChild(QtGui.QLineEdit)
            line_edit.selectAll()
            line_edit.insert(text)
            dialog.accept()
            state["done"] = True

        QtCore.QTimer.singleShot(50, fill)
        return state

    def test_auto_scale_keeps_constraint_names(self):
        """Changing "Width" from 6 to 12 doubles the sketch about the origin. Afterwards every
        constraint still has its name and its kind, "Width" is 12, and the geometry is the L
        scaled by 2: base from (4, 2) to (16, 2), side from (16, 2) to (16, 10).

        Before the fix, the scale re-added the constraints without their names (FreeCAD issue
        32792).
        """
        expected_types = self.build_sketch()
        width_index = [c.Name for c in self.sketch.Constraints].index("Width")

        FreeCADGui.getMainWindow().show()
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.pump(200)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")

        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(
            self.doc.Name, self.sketch.Name, f"Constraint{width_index + 1}"
        )
        state = self.set_datum_in_dialog("12 mm")
        FreeCADGui.runCommand("Sketcher_ChangeDimensionConstraint")
        self.assertTrue(
            self.wait_until(lambda: state["done"], timeout_ms=3000),
            "Expected the datum dialog to open and accept the new value",
        )
        self.flush_gui(100)
        FreeCADGui.ActiveDocument.resetEdit()
        self.flush_gui(100)
        self.doc.recompute()

        constraints = self.sketch.Constraints
        names = {c.Name: c.Type for c in constraints if c.Name}
        self.assertEqual(
            names,
            expected_types,
            f"Expected the named constraints to survive the auto-scale, got "
            f"{[(c.Name, c.Type) for c in constraints]}",
        )
        width = next(c for c in constraints if c.Name == "Width")
        self.assertAlmostEqual(width.Value, 12.0, places=6)

        base, side = self.sketch.Geometry
        tolerance = 1e-6
        for actual, expected in (
            (base.StartPoint, FreeCAD.Vector(4, 2, 0)),
            (base.EndPoint, FreeCAD.Vector(16, 2, 0)),
            (side.StartPoint, FreeCAD.Vector(16, 2, 0)),
            (side.EndPoint, FreeCAD.Vector(16, 10, 0)),
        ):
            self.assertLess(
                (actual - expected).Length,
                tolerance,
                f"Expected the sketch scaled by 2 about the origin: {actual} != {expected}",
            )
