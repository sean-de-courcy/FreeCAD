# SPDX-License-Identifier: LGPL-2.1-or-later

"""Onshape's sketch behaviour, round 4 of the experiment (FreeCAD-CH ops#640): from the sketch to
the feature.

Rank 73 (gap W7): under Onshape's keymap the sketch toolbar ends with Extrude and Revolve, which
accept the sketch in edit and open with it as their profile. Rank 48 (gap S22): the sketch Mirror
starts with nothing selected: the mirror line, then each entity, mirrored at its pick. Rank 18's
second slice (gap S17): drawing snaps to another part of the studio, never to one that depends on
the sketch.

Designed geometry only: round 3's 20 x 10 x 5 box and a sketch at z 5 above it (Round3GuiCase).
Expected positions are computed: a mirror about the line x = 10 takes (x, y) to (20 - x, y)."""

import FreeCAD
import Part
import Sketcher
from PySide import QtCore

from SketcherTests.GuiTestCase import FreeCADGui
from SketcherTests.TestSketchRound3Gui import Round3GuiCase
from SketcherTests.TestSketchToolbarGui import SEP, commands, drop_toolbar, toolbar

V = FreeCAD.Vector
TOL = 1e-6

GENERAL = "User parameter:BaseApp/Preferences/General"
FEATURE_BUTTONS = [SEP, "PartDesign_Pad", "PartDesign_Revolution"]


def onshape_keymap():
    return FreeCAD.ParamGet(GENERAL).GetString("Keymap", "Onshape") != "FreeCAD"


def rebuild_sketch_toolbar():
    """The toolbar is built when the workbench is activated: leave it, drop the toolbar, and come
    back, so that it is built with the preferences as they are now."""
    FreeCADGui.activateWorkbench("PartWorkbench")
    drop_toolbar("Sketch")
    FreeCADGui.activateWorkbench("PartDesignWorkbench")


class TestSketchToolbarFeaturesGui(Round3GuiCase):
    """Rank 73, gap W7: Extrude and Revolve on the sketch toolbar accept the sketch."""

    def setUp(self):
        super().setUp()
        if not onshape_keymap():
            self.skipTest("Onshape's keymap is not the active one")
        # a closed 6 x 4 rectangle inside the box's top
        corners = [V(2, 2, 0), V(8, 2, 0), V(8, 6, 0), V(2, 6, 0)]
        for i in range(4):
            self.sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            self.sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        self.doc.recompute()

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            self.restore_keymap()

    def restore_keymap(self):
        saved = getattr(self, "saved_keymap", None)
        if saved is None:
            return
        group = FreeCAD.ParamGet(GENERAL)
        if saved:
            group.SetString("Keymap", saved)
        else:
            group.RemString("Keymap")
        self.saved_keymap = None
        rebuild_sketch_toolbar()

    def button(self, name):
        tb = toolbar("Sketch")
        self.assertIsNotNone(tb, "Expected the Sketch toolbar in a sketch")
        found = [a for a in tb.actions() if a.objectName() == name]
        self.assertEqual(len(found), 1, commands(tb))
        return found[0]

    def features(self, type_id):
        return [o for o in self.doc.Objects if o.TypeId == type_id]

    def press(self, name):
        """Click the toolbar button of the sketch in edit."""
        self.start_edit()
        action = self.button(name)
        self.assertTrue(action.isEnabled(), "Expected %s enabled in the sketch" % name)
        action.trigger()
        self.flush_gui(400)

    def assert_opened_on_the_sketch(self, type_id):
        made = [f for f in self.features(type_id) if f != self.pad]
        self.assertEqual(len(made), 1, [o.Name for o in self.doc.Objects])
        feature = made[0]
        self.assertEqual(feature.Profile[0], self.sketch)
        in_edit = FreeCADGui.ActiveDocument.getInEdit()
        self.assertIsNotNone(in_edit, "Expected the feature's dialog open")
        self.assertEqual(in_edit.Object, feature, "Expected the sketch accepted and the feature in edit")
        self.assertIsNotNone(FreeCADGui.Control.activeDialog())
        return feature

    def test_the_sketch_toolbar_ends_with_extrude_and_revolve(self):
        self.start_edit()
        self.assertEqual(commands(toolbar("Sketch"))[-3:], FEATURE_BUTTONS)

    def test_extrude_accepts_the_sketch_and_opens_with_it_as_its_profile(self):
        self.press("PartDesign_Pad")
        pad = self.assert_opened_on_the_sketch("PartDesign::Pad")
        FreeCADGui.ActiveDocument.resetEdit()
        self.flush_gui(200)
        if FreeCADGui.Control.activeDialog():
            FreeCADGui.Control.closeDialog()
            self.flush_gui(200)
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        # the 6 x 4 rectangle, 10 mm up (the command's default length) from the box's top; measured on
        # the Body: on the listed path (ops#654 list on first use) the Pad is an owner whose result is
        # the Body's apply feature, and its own Shape is empty
        added = self.body.Shape.Volume - self.pad.Shape.Volume
        self.assertAlmostEqual(added, 6 * 4 * 10, places=3)

    def test_revolve_accepts_the_sketch_and_opens_with_it_as_its_profile(self):
        self.press("PartDesign_Revolution")
        self.assert_opened_on_the_sketch("PartDesign::Revolution")

    def test_the_buttons_are_onshapes_only(self):
        group = FreeCAD.ParamGet(GENERAL)
        self.saved_keymap = group.GetString("Keymap", "")
        group.SetString("Keymap", "FreeCAD")
        rebuild_sketch_toolbar()
        self.start_edit()
        names = commands(toolbar("Sketch"))
        self.assertNotIn("PartDesign_Pad", names)
        self.assertNotIn("PartDesign_Revolution", names)


class ToolFirstCase(Round3GuiCase):
    """Four entities on round 3's sketch, and clicks and keys in the view, for the tools that
    start with nothing selected."""

    def setUp(self):
        super().setUp()
        if not onshape_keymap():
            self.skipTest("Onshape's keymap is not the active one")
        # 0: the mirror line x = 10 (off the sketch's axes); 1: a line; 2: a circle; 3: a line
        # left alone
        self.sketch.addGeometry(Part.LineSegment(V(10, 1, 0), V(10, 9, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(2, 2, 0), V(6, 4, 0)))
        self.sketch.addGeometry(Part.Circle(V(4, 7, 0), V(0, 0, 1), 1))
        self.sketch.addGeometry(Part.LineSegment(V(1, 8, 0), V(3, 9, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.doc.recompute()

    @staticmethod
    def mirrored(point):
        return V(20 - point.x, point.y, 0)

    def clicks(self, points):
        for x, y in points:
            self.move(self.viewport, self.screen_point(x, y))
            self.flush_gui(200)
            point = self.screen_point(x, y)
            self.move(self.viewport, point)
            self.click(self.viewport, point)
            self.flush_gui(250)

    def escape(self):
        graphics_view = self.view.graphicsView()
        graphics_view.setFocus(QtCore.Qt.OtherFocusReason)
        self.pump(100)
        self.key_click(graphics_view, QtCore.Qt.Key_Escape)
        self.flush_gui(200)

    def symmetric(self):
        return [
            (c.First, c.Second, c.Third) for c in self.sketch.Constraints if c.Type == "Symmetric"
        ]

    def assert_line_mirrored(self, original, copy):
        expected = [self.mirrored(original.StartPoint), self.mirrored(original.EndPoint)]
        for end in (copy.StartPoint, copy.EndPoint):
            self.assertLess(min((end - e).Length for e in expected), TOL, (end, expected))


class TestSketchMirrorToolFirstGui(ToolFirstCase):
    """Rank 48, gap S22: Mirror with nothing selected takes the mirror line, then the entities."""

    def test_mirror_with_nothing_selected_takes_the_line_then_the_entities(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("Sketcher_Symmetry")
        self.flush_gui(200)
        # the mirror line, the line's middle, the circle's right edge
        self.clicks([(10, 5)])
        self.assertEqual(self.sketch.GeometryCount, 4, "Expected the mirror line pick to add nothing")
        self.clicks([(4, 3)])
        self.assertTrue(
            self.wait_until(lambda: self.sketch.GeometryCount == 5, 2000),
            "Expected the line mirrored at its pick",
        )
        self.clicks([(5, 7)])
        self.assertTrue(
            self.wait_until(lambda: self.sketch.GeometryCount == 6, 2000),
            "Expected the circle mirrored at its pick",
        )
        self.sketch.solve()
        geometry = self.sketch.Geometry
        self.assert_line_mirrored(geometry[1], geometry[4])
        self.assertLess((geometry[5].Center - self.mirrored(geometry[2].Center)).Length, TOL)
        self.assertAlmostEqual(geometry[5].Radius, 1.0, places=6)
        # the originals stay where they were
        self.assertLess((geometry[1].StartPoint - V(2, 2, 0)).Length, TOL)
        self.assertLess((geometry[2].Center - V(4, 7, 0)).Length, TOL)
        # Symmetric constraints about the mirror line: both ends of the line, the circle's centre
        symmetric = self.symmetric()
        self.assertEqual(symmetric.count((1, 4, 0)), 2, symmetric)
        self.assertEqual(symmetric.count((2, 5, 0)), 1, symmetric)

        # One Esc ends the tool; the sketch stays open and a pick mirrors nothing more
        self.escape()
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected the sketch open")
        self.clicks([(2, 8.5)])
        self.flush_gui(300)
        self.assertEqual(self.sketch.GeometryCount, 6, "Expected the tool ended by one Esc")

    def test_an_entity_is_mirrored_once_and_a_copy_not_back(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("Sketcher_Symmetry")
        self.flush_gui(200)
        self.clicks([(10, 5), (4, 3)])
        self.assertTrue(self.wait_until(lambda: self.sketch.GeometryCount == 5, 2000))
        # the same line again, then its mirrored copy: nothing more
        self.clicks([(4, 3), (16, 3)])
        self.flush_gui(300)
        self.assertEqual(self.sketch.GeometryCount, 5)
        self.escape()

    def test_mirror_with_a_selection_first_still_takes_the_line_after(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge2")
        FreeCADGui.runCommand("Sketcher_Symmetry")
        self.flush_gui(200)
        self.clicks([(10, 5)])
        self.assertTrue(
            self.wait_until(lambda: self.sketch.GeometryCount == 5, 2000),
            "Expected the selected line mirrored about the picked line",
        )
        self.sketch.solve()
        self.assert_line_mirrored(self.sketch.Geometry[1], self.sketch.Geometry[4])
        self.assertEqual(self.symmetric().count((1, 4, 0)), 2, self.symmetric())


class TestSketchTransformToolFirstGui(ToolFirstCase):
    """Sketch tools item 6: under Onshape's keymap Move, Rotate and Scale start with nothing
    selected, as Offset and Mirror do: each click picks (or unpicks) the sketch's geometry, shown as
    the selection, and Enter hands the picks to the tool. The same four entities as the mirror's;
    the mirror line is blocked and is not picked here."""

    def picked(self):
        names = []
        for selection in FreeCADGui.Selection.getSelectionEx():
            names += [name.split(".")[-1] for name in selection.SubElementNames]
        return sorted(names)

    def enter(self):
        graphics_view = self.view.graphicsView()
        graphics_view.setFocus(QtCore.Qt.OtherFocusReason)
        self.pump(100)
        self.key_click(graphics_view, QtCore.Qt.Key_Return)
        self.flush_gui(300)

    def test_the_tools_are_active_with_nothing_selected(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        self.flush_gui(200)
        for name in ("Sketcher_Translate", "Sketcher_Rotate", "Sketcher_Scale"):
            self.assertTrue(FreeCADGui.isCommandActive(name), name)

    def test_move_with_nothing_selected_picks_then_moves(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("Sketcher_Translate")
        self.flush_gui(200)
        # the line, the circle's right edge, the other line, that line again (unpicked)
        self.clicks([(4, 3), (5, 7), (2, 8.5)])
        self.assertEqual(self.picked(), ["Edge2", "Edge3", "Edge4"])
        self.clicks([(2, 8.5)])
        self.assertEqual(self.picked(), ["Edge2", "Edge3"], "Expected a second click to unpick")
        self.assertEqual(self.sketch.GeometryCount, 4, "Expected picking to change nothing")
        self.enter()
        self.assertEqual(self.picked(), [], "Expected Enter to hand the picks to Move")
        line, circle, other = (self.sketch.Geometry[i] for i in (1, 2, 3))
        # Move's two clicks: from, to (in open space, away from the geometry)
        self.clicks([(13, 2), (15, 3)])

        # (a move replaces the picks by moved geometry at new ids: found by type and place)
        def circles():
            return [g for g in self.sketch.Geometry if isinstance(g, Part.Circle)]

        def moved():
            self.sketch.solve()
            return len(circles()) == 1 and (circles()[0].Center - circle.Center).Length > 0.5

        self.assertTrue(self.wait_until(moved, 2000), "Expected the picks moved")
        self.assertEqual(self.sketch.GeometryCount, 4, "Expected a move, not a copy")
        shift = circles()[0].Center - circle.Center
        lines = [g for g in self.sketch.Geometry if isinstance(g, Part.LineSegment)]

        def has_line(start, end):
            return any(
                (g.StartPoint - start).Length < TOL and (g.EndPoint - end).Length < TOL
                for g in lines
            )

        self.assertTrue(has_line(line.StartPoint + shift, line.EndPoint + shift), "moved line")
        self.assertTrue(has_line(other.StartPoint, other.EndPoint), "the unpicked line stays")

    def test_enter_with_nothing_picked_does_nothing_and_esc_ends(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("Sketcher_Rotate")
        self.flush_gui(200)
        self.enter()
        self.clicks([(13, 2), (15, 3)])
        self.assertEqual(self.picked(), [])
        self.assertEqual(self.sketch.GeometryCount, 4)
        self.escape()
        self.assertIsNotNone(FreeCADGui.ActiveDocument.getInEdit(), "Expected the sketch open")
        self.clicks([(4, 3)])
        self.assertEqual(self.picked(), ["Edge2"], "Expected the tool ended: a plain selection")

    def test_scale_takes_its_picks_on_enter(self):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("Sketcher_Scale")
        self.flush_gui(200)
        self.clicks([(5, 7)])
        self.assertEqual(self.picked(), ["Edge3"])
        self.enter()
        self.assertEqual(self.picked(), [], "Expected Enter to hand the pick to Scale")
        self.escape()


class TestSketchOtherPartSnapGui(Round3GuiCase):
    """Rank 18's second slice (gap S17): while drawing, a point also snaps to the vertices and
    edges of another part of the studio (another Body's Tip) and links them, as Onshape infers
    onto any part made before the sketch; never onto a part that depends on the sketch (a cycle),
    nor onto a hidden one. Here the sketch is in a second Body, on XY at z 5: the box is the
    first Body's."""

    def setUp(self):
        super().setUp()
        self.doc.removeObject(self.sketch.Name)
        self.body2 = self.doc.addObject("PartDesign::Body", "Body001")
        xy = self.body2.Origin.OriginFeatures[3]
        self.sketch = self.body2.newObject("Sketcher::SketchObject", "Sketch2")
        self.sketch.AttachmentSupport = [(xy, "")]
        self.sketch.MapMode = "FlatFace"
        self.sketch.AttachmentOffset = FreeCAD.Placement(V(0, 0, 5), FreeCAD.Rotation())
        self.doc.recompute()

    def external_coincident(self, geo, pos):
        for c in self.sketch.Constraints:
            if c.Type != "Coincident":
                continue
            if (c.First == geo and c.FirstPos == pos and c.Second <= -3) or (
                c.Second == geo and c.SecondPos == pos and c.First <= -3
            ):
                return c
        return None

    def test_a_line_started_near_another_part_s_corner_snaps_and_links_it(self):
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(20.04, 9.97), (12, 4)])
        start = self.world(self.sketch.Geometry[0].StartPoint)
        self.assertLess((start - V(20, 10, 5)).Length, 1e-6, "The start snapped to the corner")
        self.assertIn(("Pad", self.pad_vertex_at(V(20, 10, 5))), self.links(), self.describe())
        self.assertIsNotNone(self.external_coincident(0, 1), self.describe())

    def test_a_hidden_part_is_not_snapped_to(self):
        self.body.Visibility = False
        self.doc.recompute()
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(20.04, 9.97), (12, 4)])
        self.assertEqual(self.links(), [], self.describe())

    def test_a_part_that_depends_on_the_sketch_is_not_snapped_to(self):
        # the sketch's one line (index 0), away from everything; a third Body's 4 x 2 box at
        # x 2..6, y 12..14, z 0..5, whose sketch links that line: its part depends on the sketch
        self.sketch.addGeometry(Part.LineSegment(V(-4, -3, 0), V(-2, -3, 0)))
        self.doc.recompute()
        body3 = self.doc.addObject("PartDesign::Body", "Body002")
        profile = body3.newObject("Sketcher::SketchObject", "Profile3")
        profile.AttachmentSupport = [(body3.Origin.OriginFeatures[3], "")]
        profile.MapMode = "FlatFace"
        corners = [V(2, 12, 0), V(6, 12, 0), V(6, 14, 0), V(2, 14, 0)]
        for i in range(4):
            profile.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            profile.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        profile.addExternal(self.sketch.Name, "Edge1")
        self.doc.recompute()
        pad3 = body3.newObject("PartDesign::Pad", "Pad3")
        pad3.Profile = profile
        pad3.Length = 5.0
        self.doc.recompute()
        self.assertTrue(pad3.isValid(), pad3.getStatusString())
        self.assertIn(self.sketch, pad3.OutListRecursive, "Expected the third part to use the sketch")

        self.start_edit()
        self.draw("Sketcher_CreateLine", [(6.04, 13.97), (9, 17)])
        self.assertEqual(self.links(), [], self.describe())
        start = self.world(self.sketch.Geometry[1].StartPoint)
        self.assertGreater((start - V(6, 14, 5)).Length, 1e-3, "No snap to the dependent part")
