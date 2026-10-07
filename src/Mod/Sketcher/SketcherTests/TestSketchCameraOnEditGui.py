# SPDX-License-Identifier: LGPL-2.1-or-later

"""The camera on sketch edit (ops#145): turning the view to the sketch is a preference,
Mod/Sketcher/General/OrientViewOnEdit, off by default. Off, opening a sketch doesn't move the
view at all (no turn, no fit); Sketcher_ViewSketch turns it on demand."""

import re

import FreeCAD
import Part
from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

V = FreeCAD.Vector

GENERAL_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"
VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"

TOLERANCE = 1e-6


class TestSketchCameraOnEditGui(SketcherGuiTestCase):
    def setUp(self):
        super().setUp()
        self.saved_params = []
        # Camera reads mustn't land mid-animation.
        self.set_param(VIEW_PARAMS, "Bool", "UseNavigationAnimations", False)

        self.doc = FreeCAD.newDocument("TestSketchCameraOnEditGui")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.sketch.Placement = FreeCAD.Placement(V(0, 0, 5), FreeCAD.Rotation(V(1, 0, 0), 30))
        self.doc.recompute()

        FreeCADGui.getMainWindow().show()
        self.view = FreeCADGui.ActiveDocument.ActiveView

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

    def add_line(self, start, end):
        self.sketch.addGeometry(Part.LineSegment(start, end), False)
        self.doc.recompute()

    # The camera ------------------------------------------------------------------------------

    def camera(self):
        """Orientation (a Rotation), position (a Vector), the camera type, and its height or
        height angle and focal distance, read from the view."""
        text = self.view.getCamera()

        def field(name):
            match = re.search(r"\b" + name + r"\s+([-0-9.eE+ ]+)", text)
            return [float(v) for v in match.group(1).split()] if match else None

        return {
            "orientation": self.view.getCameraOrientation(),
            "position": V(*field("position")[:3]),
            "type": self.view.getCameraType(),
            "height": (field("height") or field("heightAngle") or [None])[0],
            "focal": field("focalDistance")[0],
        }

    def start_from_isometric(self):
        self.view.viewIsometric()
        self.view.fitAll()
        self.flush_gui(100)
        return self.camera()

    def set_edit(self):
        FreeCADGui.ActiveDocument.setEdit(self.sketch.Name)
        self.flush_gui(200)
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected sketch edit mode")

    def assert_same_rotation(self, actual, expected, message):
        """Quaternions up to sign."""
        a = actual.Q
        b = expected.Q
        same = all(abs(x - y) < TOLERANCE for x, y in zip(a, b))
        opposite = all(abs(x + y) < TOLERANCE for x, y in zip(a, b))
        self.assertTrue(same or opposite, f"{message}: expected {b}, got {a}")

    def assert_camera_unchanged(self, before, after):
        self.assert_same_rotation(
            after["orientation"], before["orientation"], "Expected the same orientation"
        )
        self.assertLess(
            (after["position"] - before["position"]).Length,
            TOLERANCE,
            f"Expected the same position {before['position']}, got {after['position']}",
        )
        self.assertAlmostEqual(after["height"], before["height"], delta=TOLERANCE)
        self.assertAlmostEqual(after["focal"], before["focal"], delta=TOLERANCE)

    # C1-C4 -------------------------------------------------------------------------------------

    def test_c1_preference_on_turns_the_view(self):
        """C1: with OrientViewOnEdit on, the view turns to the sketch's rotation."""
        self.set_param(GENERAL_PARAMS, "Bool", "OrientViewOnEdit", True)
        self.add_line(V(0, 0, 0), V(10, 0, 0))
        self.start_from_isometric()

        self.set_edit()
        self.assert_same_rotation(
            self.camera()["orientation"], self.sketch.Placement.Rotation, "Expected the turn"
        )

    def test_c2_preference_off_keeps_the_view(self):
        """C2: with it off (the default), the camera doesn't change on edit. Align View to
        Sketch then turns it to the sketch."""
        self.set_param(GENERAL_PARAMS, "Bool", "OrientViewOnEdit", False)
        self.add_line(V(0, 0, 0), V(10, 0, 0))
        before = self.start_from_isometric()

        self.set_edit()
        self.assert_camera_unchanged(before, self.camera())

        FreeCADGui.runCommand("Sketcher_ViewSketch")
        self.flush_gui(200)
        self.assert_same_rotation(
            self.camera()["orientation"],
            self.sketch.Placement.Rotation,
            "Expected Align View to Sketch to turn the view",
        )

    def test_c2_default_is_off(self):
        """The preference's default is off: without the entry, the camera doesn't change."""
        group = FreeCAD.ParamGet(GENERAL_PARAMS)
        if "OrientViewOnEdit" in group.GetBools():
            self.set_param(GENERAL_PARAMS, "Bool", "OrientViewOnEdit", False)
            group.RemBool("OrientViewOnEdit")
        self.add_line(V(0, 0, 0), V(10, 0, 0))
        before = self.start_from_isometric()

        self.set_edit()
        self.assert_camera_unchanged(before, self.camera())

    def test_c3_force_ortho_and_restore_still_work(self):
        """C3: off, with RestoreCamera and ForceOrtho: in edit the camera is orthographic at
        the same orientation; after the edit, the recorded type and orientation are back."""
        self.set_param(GENERAL_PARAMS, "Bool", "OrientViewOnEdit", False)
        self.add_line(V(0, 0, 0), V(10, 0, 0))
        self.sketch.ViewObject.RestoreCamera = True
        self.sketch.ViewObject.ForceOrtho = True
        self.view.setCameraType("Perspective")
        self.flush_gui(50)
        before = self.start_from_isometric()
        self.assertEqual(before["type"], "Perspective")

        self.set_edit()
        during = self.camera()
        self.assertEqual(during["type"], "Orthographic")
        self.assert_same_rotation(
            during["orientation"], before["orientation"], "Expected the same orientation in edit"
        )

        FreeCADGui.ActiveDocument.resetEdit()
        self.flush_gui(200)
        after = self.camera()
        self.assertEqual(after["type"], "Perspective")
        self.assert_same_rotation(
            after["orientation"], before["orientation"], "Expected the orientation restored"
        )

    def test_c4_no_fit_to_far_geometry(self):
        """C4 (Q5: no view change at all): off, a sketch whose only line is far outside the
        view doesn't make the view fit it."""
        self.set_param(GENERAL_PARAMS, "Bool", "OrientViewOnEdit", False)
        helper = self.doc.addObject("Part::Box", "Box")
        self.doc.recompute()
        before = self.start_from_isometric()  # fits the box only

        self.add_line(V(1000, 1000, 0), V(1010, 1000, 0))
        self.flush_gui(50)
        self.set_edit()
        self.assert_camera_unchanged(before, self.camera())
        self.assertIsNotNone(helper)
