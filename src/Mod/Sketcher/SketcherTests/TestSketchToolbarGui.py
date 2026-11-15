# SPDX-License-Identifier: LGPL-2.1-or-later

"""The single Sketch toolbar in Onshape's order (FreeCAD-CH, ops#605 brief C).

Inside a sketch there is one "Sketch" toolbar (notes/onshape-gui-plan.md 2.2, 2c(i)) in place of
the Geometries and Constraints toolbars. Sketcher Tools, B-Spline Tools and Visual Helpers are
still there but hidden until the user shows them from the toolbar menu. Outside a sketch none of
them is available, as before.

The oracle is written out here, independently of the C++ lists, and read from the toolbars the
ToolBarManager built in the main window after the toolbar settings were cleared, as on a fresh
settings folder, with the sketcher's toolbar preferences at their defaults."""

import FreeCAD
import FreeCADGui
import Part

from PySide import QtCore, QtWidgets

from SketcherTests.GuiTestCase import SketcherGuiTestCase

TOOLBARS = "User parameter:BaseApp/MainWindow/Toolbars"
SKETCHER = "User parameter:BaseApp/Preferences/Mod/Sketcher"

SEP = "|"

# Onshape's order, 2c(i)
SKETCH = [
    "Sketcher_CompLine",
    "Sketcher_CompCreateRectangles",
    "Sketcher_CompCreateConic",
    "Sketcher_CompCreateArc",
    "Sketcher_CompCreateRegularPolygon",
    "Sketcher_CompSlot",
    "Sketcher_CompCreateBSpline",
    "Sketcher_CreatePoint",
    "Sketcher_CreateText",
    "Sketcher_CompCreateFillets",
    "Sketcher_CompCurveEdition",
    "Sketcher_Offset",
    "Sketcher_Symmetry",
    "Sketcher_CompExternal",
    "Sketcher_InsertDxf",  # FreeCAD-CH, the DXF lane: SketcherDxfGui's manipulator puts it here
    "Sketcher_ToggleConstruction",
    SEP,
    "Sketcher_CompDimensionTools",
    "Sketcher_ConstrainCoincidentUnified",
    "Sketcher_ConstrainConcentric",  # ops#640, rank 44
    "Sketcher_CompHorVer",
    "Sketcher_ConstrainParallel",
    "Sketcher_ConstrainPerpendicular",
    "Sketcher_ConstrainTangent",
    "Sketcher_ConstrainEqual",
    "Sketcher_ConstrainMidpoint",
    "Sketcher_ConstrainPierce",  # Onshape's Pierce
    "Sketcher_ConstrainSymmetric",
    "Sketcher_ConstrainBlock",
]

# Under Onshape's keymap the toolbar ends with Extrude and Revolve, Part Design's (ops#640, rank 73,
# gap W7); setUp loads Part Design's commands
FEATURES = [SEP, "PartDesign_Pad", "PartDesign_Revolution"]


def sketch_toolbar():
    keymap = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/General").GetString(
        "Keymap", "Onshape"
    )
    return SKETCH + (FEATURES if keymap != "FreeCAD" else [])


EDIT_MODE = ["Sketcher_LeaveSketch", "Sketcher_ViewSketch", "Sketcher_ViewSection"]

# Kept, hidden by default, listed in the toolbar menu while a sketch is open
HIDDEN_IN_SKETCH = ["Sketcher Tools", "B-Spline Tools", "Visual Helpers"]

# Preferences > Sketcher > Dimensioning tools: the dimension part of the Sketch toolbar, which
# follows the same two flags as the Constraints toolbar it replaces (single tool, separated tools,
# both)
SEPARATE_DIMENSIONS = [
    "Sketcher_ConstrainDistanceX",
    "Sketcher_ConstrainDistanceY",
    "Sketcher_ConstrainDistance",
    "Sketcher_CompConstrainRadDia",
    "Sketcher_ConstrainAngle",
    "Sketcher_ConstrainLock",
]
DIMENSION_MODES = {
    "single": (True, False, ["Sketcher_CompDimensionTools"]),
    "separated": (False, True, SEPARATE_DIMENSIONS),
    "both": (True, True, ["Sketcher_Dimension"] + SEPARATE_DIMENSIONS),
}

# The toolbars this one replaces
REPLACED = ["Geometries", "Constraints"]

# The toolbar preferences that decide the lists above; their defaults are what the oracle assumes
DEFAULTS = {
    "Commands": ["UnifiedLineCommands"],
    "dimensioning": ["SingleDimensioningTool", "SeparatedDimensioningTools"],
    "Constraints": ["UnifiedCoincident", "AutoHorVer"],
}


def toolbar(name):
    found = [
        t for t in FreeCADGui.getMainWindow().findChildren(QtWidgets.QToolBar)
        if t.objectName() == name
    ]
    return found[0] if found else None


def commands(tb):
    return [SEP if a.isSeparator() else a.objectName() for a in tb.actions()]


def drop_toolbar(name):
    """The preferences are read when a toolbar is built, at the start of a session, and a rebuilt
    toolbar keeps the order of its old actions: delete it so that it is built anew."""
    old = toolbar(name)
    if old is not None:
        old.setParent(None)
        old.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


class TestSketchToolbarGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        import PartDesignGui  # noqa: F401  the Extrude and Revolve buttons' commands

        # leaving a workbench saves its toolbars' visibility: leave first, then forget what was saved
        FreeCADGui.activateWorkbench("PartWorkbench")
        self.saved_toolbars = {}
        group = FreeCAD.ParamGet(TOOLBARS)
        for name in group.GetBools():
            self.saved_toolbars[name] = group.GetBool(name)
            group.RemBool(name)
        self.saved_prefs = []
        for sub, names in DEFAULTS.items():
            group = FreeCAD.ParamGet(f"{SKETCHER}/{sub}")
            for name in names:
                if name in group.GetBools():
                    self.saved_prefs.append((sub, name, group.GetBool(name)))
                    group.RemBool(name)

        self.doc = FreeCAD.newDocument("TestSketchToolbarGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.addGeometry(
            Part.LineSegment(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(10, 0, 0)), False
        )
        self.doc.recompute()
        FreeCADGui.getMainWindow().show()
        # Workbench toolbars are built on activation
        drop_toolbar("Sketch")
        FreeCADGui.activateWorkbench("SketcherWorkbench")
        self.flush_gui(100)

    def tearDown(self):
        try:
            super().tearDown()
            self.flush_gui(100)
        finally:
            group = FreeCAD.ParamGet(TOOLBARS)
            for name in group.GetBools():
                group.RemBool(name)
            for name, value in self.saved_toolbars.items():
                group.SetBool(name, value)
            for sub, names in DEFAULTS.items():
                group = FreeCAD.ParamGet(f"{SKETCHER}/{sub}")
                for name in names:
                    if name in group.GetBools():
                        group.RemBool(name)
            for sub, name, value in self.saved_prefs:
                FreeCAD.ParamGet(f"{SKETCHER}/{sub}").SetBool(name, value)

    def edit(self):
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(300)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")

    def test_the_sketch_toolbar_is_onshapes_order(self):
        self.edit()
        tb = toolbar("Sketch")
        self.assertIsNotNone(tb, "Expected a toolbar named Sketch in a sketch")
        self.assertEqual(commands(tb), sketch_toolbar())
        self.assertFalse(tb.isHidden(), "Expected the Sketch toolbar shown in a sketch")

    def test_the_dimensioning_tools_preference_is_honoured(self):
        expected_toolbar = sketch_toolbar()
        start = expected_toolbar.index("Sketcher_CompDimensionTools")
        for mode, (single, separated, tools) in DIMENSION_MODES.items():
            with self.subTest(mode):
                FreeCADGui.activateWorkbench("PartWorkbench")
                drop_toolbar("Sketch")
                group = FreeCAD.ParamGet(f"{SKETCHER}/dimensioning")
                group.SetBool("SingleDimensioningTool", single)
                group.SetBool("SeparatedDimensioningTools", separated)
                FreeCADGui.activateWorkbench("SketcherWorkbench")
                self.flush_gui(100)
                self.edit()
                expected = expected_toolbar[:start] + tools + expected_toolbar[start + 1 :]
                self.assertEqual(commands(toolbar("Sketch")), expected)
                FreeCADGui.ActiveDocument.resetEdit()
                self.flush_gui(300)

    def test_the_edit_mode_toolbar_stays(self):
        self.edit()
        tb = toolbar("Edit Mode")
        self.assertIsNotNone(tb)
        self.assertEqual(commands(tb), EDIT_MODE)
        self.assertFalse(tb.isHidden())

    def test_geometries_and_constraints_are_replaced(self):
        self.edit()
        for name in REPLACED:
            tb = toolbar(name)
            self.assertTrue(
                tb is None or tb.isHidden(), f"Expected no {name} toolbar in a sketch"
            )

    def test_the_other_toolbars_are_hidden_but_listed_in_a_sketch(self):
        self.edit()
        for name in HIDDEN_IN_SKETCH:
            with self.subTest(name):
                tb = toolbar(name)
                self.assertIsNotNone(tb, f"Expected the {name} toolbar to exist")
                self.assertTrue(tb.isHidden(), f"Expected {name} hidden by default")
                self.assertTrue(
                    tb.toggleViewAction().isVisible(),
                    f"Expected {name} to be listed in the toolbar menu in a sketch",
                )

    def test_nothing_of_it_is_available_outside_a_sketch(self):
        for name in ["Sketch"] + HIDDEN_IN_SKETCH:
            with self.subTest(name):
                tb = toolbar(name)
                self.assertIsNotNone(tb, f"Expected the {name} toolbar to exist")
                self.assertTrue(tb.isHidden(), f"Expected {name} hidden outside a sketch")
                self.assertFalse(
                    tb.toggleViewAction().isVisible(),
                    f"Expected {name} unavailable outside a sketch",
                )

    def test_a_toolbar_the_user_showed_is_shown_in_the_next_sketch(self):
        self.edit()
        FreeCADGui.ActiveDocument.resetEdit()
        self.flush_gui(300)
        FreeCAD.ParamGet(TOOLBARS).SetBool("Visual Helpers", True)
        self.edit()
        self.assertFalse(toolbar("Visual Helpers").isHidden())
        self.assertTrue(toolbar("Sketcher Tools").isHidden())
