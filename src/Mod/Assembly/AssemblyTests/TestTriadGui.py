# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, design group C slice C8): the triad's typed moves, as Onshape's
# (notes/assemblies-design.md 4b; notes/onshape-facts.md GC-T1 to GC-T5, GC-T8).
#
# - Clicking a free instance puts the triad at the clicked point, aligned with the assembly's axes.
# - After an arrow or a ring is released, a box holds the distance or angle moved since the drag
#   started; a typed value replaces the move by exactly that value, measured from the drag's start;
#   the box stays open for the next value and takes expressions. A plane square gets no box.
# - Each drag and each typed value is one undo step ("Move part"); nothing is stored on the instance
#   and no mate is made.
# - Several selected instances share one triad, at the first click point, and move by the same amount.
# - Drags are smooth (no 1 mm or 22.5 degree steps).
# Designed geometry: two free 10 mm cubes, A at the origin and B 40 mm along X; the assembly at
# identity. Expected placements are computed from the triad's origin and the typed values.

import os
import tempfile
import time
import unittest

import FreeCAD as App
import FreeCADGui as Gui

from PySide import QtCore, QtGui, QtWidgets

V = App.Vector
TOL = 1e-9


def pump(seconds=0.2):
    app = QtWidgets.QApplication.instance()
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def waitFor(condition, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if condition():
            return True
        pump(0.05)
    return bool(condition())


def turnedAbout(pivot, rotation):
    """The placement that turns by @rotation about @pivot: what a ring does to a part at identity."""
    return App.Placement(pivot, rotation) * App.Placement(-pivot, App.Rotation())


class TriadGuiCase(unittest.TestCase):
    docName = "TriadGui"

    def setUp(self):
        if "AssemblyWorkbench" not in Gui.listWorkbenches():
            self.skipTest("no Assembly")
        self.doc = App.newDocument(self.docName)
        Gui.activateWorkbench("AssemblyWorkbench")
        self.assembly = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        self.assembly.Type = "Assembly"
        self.jointgroup = self.assembly.newObject("Assembly::JointGroup", "Joints")
        self.a = self.cube("A", V(0, 0, 0))
        self.b = self.cube("B", V(40, 0, 0))
        self.doc.recompute()
        Gui.ActiveDocument = Gui.getDocument(self.doc.Name)
        Gui.ActiveDocument.setEdit(self.assembly.Name)
        self.assertTrue(waitFor(lambda: Gui.ActiveDocument.getInEdit() is not None))
        self.vp = self.assembly.ViewObject
        self.tmpdir = None

    def tearDown(self):
        Gui.Selection.clearSelection()
        pump()
        if Gui.ActiveDocument and Gui.ActiveDocument.getInEdit():
            Gui.ActiveDocument.resetEdit()
        pump()
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        if self.tmpdir:
            self.tmpdir.cleanup()

    def cube(self, name, at):
        box = self.assembly.newObject("Part::Box", name)
        box.Length = box.Width = box.Height = 10
        box.Placement = App.Placement(at, App.Rotation())
        return box

    def pick(self, obj, sub, point):
        Gui.Selection.addSelection(self.doc.Name, self.assembly.Name, obj.Name + "." + sub, *point)
        pump()

    def assertPlacement(self, obj, expected, tol=TOL):
        got = obj.Placement
        self.assertLess((got.Base - expected.Base).Length, tol, f"{obj.Name} at {got.Base}")
        self.assertTrue(
            got.Rotation.isSame(expected.Rotation, tol),
            f"{obj.Name} turned {got.Rotation.toEuler()}, expected {expected.Rotation.toEuler()}",
        )

    def moved(self, placement, by):
        return App.Placement(placement.Base + by, placement.Rotation)

    def joints(self):
        return [o for o in self.jointgroup.Group if hasattr(o, "JointType")]


class TestTriadGui(TriadGuiCase):
    def test_triad_at_the_clicked_point_aligned_with_the_assembly(self):
        self.pick(self.a, "Face6", (3, 4, 10))
        self.assertTrue(self.vp.DraggerVisibility, "no triad on a free instance")
        triad = self.vp.getTriadPlacement()
        self.assertLess((triad.Base - V(3, 4, 10)).Length, TOL, triad.Base)
        self.assertTrue(triad.Rotation.isNull() or triad.Rotation.isSame(App.Rotation(), TOL))

    def test_typed_distance_replaces_the_drag_from_its_start(self):
        start_props = sorted(self.a.PropertiesList)
        objects = len(self.doc.Objects)
        self.pick(self.a, "Face6", (3, 4, 10))
        undo0 = self.doc.UndoCount

        # An arrow dragged by 6.858 mm along X (GC-T2), then the box
        self.vp.dragTriad("TranslateX", App.Placement(V(3 + 6.858, 4, 10), App.Rotation()))
        self.assertEqual(self.vp.getTriadHandle(), "TranslateX")
        self.assertTrue(self.vp.isTriadBoxOpen(), "no box after an arrow drag")
        self.assertAlmostEqual(self.vp.getTriadValue(), 6.858, places=9)
        self.assertPlacement(self.a, App.Placement(V(6.858, 0, 0), App.Rotation()))
        self.assertEqual(self.doc.UndoCount, undo0 + 1, "the drag is one undo step")

        # 12 mm typed: 12 from where the drag started, not from 6.858
        self.assertTrue(self.vp.applyTriadValue("12 mm"))
        self.assertPlacement(self.a, App.Placement(V(12, 0, 0), App.Rotation()))
        self.assertTrue(self.vp.isTriadBoxOpen(), "the box stays open for the next value")
        # An expression, evaluated once
        self.assertTrue(self.vp.applyTriadValue("10 mm + 5 mm"))
        self.assertPlacement(self.a, App.Placement(V(15, 0, 0), App.Rotation()))
        self.assertEqual(self.doc.UndoCount, undo0 + 3, "each typed value is one undo step")
        self.assertPlacement(self.b, App.Placement(V(40, 0, 0), App.Rotation()))

        # Nothing stored, no mate (GC-T2, GC-S1)
        self.assertEqual(sorted(self.a.PropertiesList), start_props)
        self.assertEqual(len(self.doc.Objects), objects)
        self.assertEqual(self.joints(), [])

        # Ctrl+Z goes back one typed value at a time: 15 -> 12 -> 6.858 -> 0
        for x in (12, 6.858, 0):
            self.doc.undo()
            pump()
            self.assertPlacement(self.a, App.Placement(V(x, 0, 0), App.Rotation()))

    def test_typed_angle_turns_about_the_triad_origin(self):
        pivot = V(5, 5, 10)
        self.pick(self.a, "Face6", pivot)
        undo0 = self.doc.UndoCount
        self.vp.dragTriad("RotateZ", App.Placement(pivot, App.Rotation(V(0, 0, 1), 25)))
        self.assertEqual(self.vp.getTriadHandle(), "RotateZ")
        self.assertTrue(self.vp.isTriadBoxOpen(), "no box after a ring drag")
        self.assertAlmostEqual(self.vp.getTriadValue(), 25, places=9)

        self.assertTrue(self.vp.applyTriadValue("30 deg"))
        self.assertPlacement(self.a, turnedAbout(pivot, App.Rotation(V(0, 0, 1), 30)))
        self.assertEqual(self.doc.UndoCount, undo0 + 2)
        # A negative angle, and a ring about X: the same pivot
        self.assertTrue(self.vp.applyTriadValue("-40 deg"))
        self.assertPlacement(self.a, turnedAbout(pivot, App.Rotation(V(0, 0, 1), -40)))

        # The triad keeps the assembly's axes after a ring turn (design 4b's reading; Onshape
        # unverified): the X ring turns about the assembly's X through the triad's origin
        shown = self.vp.getTriadPlacement()
        self.assertLess((shown.Base - pivot).Length, 1e-9, shown.Base)
        self.assertTrue(shown.Rotation.isSame(App.Rotation(), 1e-12), shown.Rotation)
        self.vp.dragTriad("RotateX", App.Placement(pivot, App.Rotation(V(1, 0, 0), 15)))
        self.assertAlmostEqual(self.vp.getTriadValue(), 15, places=9)
        self.assertPlacement(
            self.a,
            turnedAbout(pivot, App.Rotation(V(1, 0, 0), 15))
            * turnedAbout(pivot, App.Rotation(V(0, 0, 1), -40)),
        )
        self.assertTrue(self.vp.getTriadPlacement().Rotation.isSame(App.Rotation(), 1e-12))
        self.assertTrue(self.vp.applyTriadValue("90 deg"))
        expected = turnedAbout(pivot, App.Rotation(V(1, 0, 0), 90)) * turnedAbout(
            pivot, App.Rotation(V(0, 0, 1), -40)
        )
        self.assertPlacement(self.a, expected)

        # Undo: the typed value, then the X ring's drag
        self.doc.undo()
        pump()
        self.assertPlacement(
            self.a,
            turnedAbout(pivot, App.Rotation(V(1, 0, 0), 15))
            * turnedAbout(pivot, App.Rotation(V(0, 0, 1), -40)),
        )
        self.doc.undo()
        pump()
        self.assertPlacement(self.a, turnedAbout(pivot, App.Rotation(V(0, 0, 1), -40)))

    def test_a_length_for_a_ring_or_text_that_does_not_evaluate_is_refused(self):
        self.pick(self.a, "Face6", (3, 4, 10))
        self.vp.dragTriad("RotateZ", App.Placement(V(3, 4, 10), App.Rotation(V(0, 0, 1), 10)))
        before = self.a.Placement
        undo = self.doc.UndoCount
        self.assertFalse(self.vp.applyTriadValue("5 mm"))
        self.assertFalse(self.vp.applyTriadValue("not a value"))
        self.assertPlacement(self.a, before)
        self.assertEqual(self.doc.UndoCount, undo)
        self.assertTrue(self.vp.isTriadBoxOpen())

    def test_a_bare_number_is_mm_or_degrees(self):
        self.pick(self.a, "Face6", (3, 4, 10))
        self.vp.dragTriad("TranslateY", App.Placement(V(3, 5, 10), App.Rotation()))
        self.assertTrue(self.vp.applyTriadValue("7"))
        self.assertPlacement(self.a, App.Placement(V(0, 7, 0), App.Rotation()))

    def test_plane_square_moves_without_a_box(self):
        self.pick(self.a, "Face6", (3, 4, 10))
        undo0 = self.doc.UndoCount
        self.vp.dragTriad("Plane", App.Placement(V(3 + 2.286, 4 + 2.794, 10), App.Rotation()))
        self.assertFalse(self.vp.isTriadBoxOpen(), "a plane square gets no box (GC-T4)")
        self.assertPlacement(self.a, App.Placement(V(2.286, 2.794, 0), App.Rotation()))
        self.assertEqual(self.doc.UndoCount, undo0 + 1)

    def test_two_instances_share_the_triad_and_move_the_same_amount(self):
        self.pick(self.a, "Face6", (3, 4, 10))
        self.pick(self.b, "Face6", (43, 4, 10))
        triad = self.vp.getTriadPlacement()
        self.assertLess((triad.Base - V(3, 4, 10)).Length, TOL, "one triad, at the first click (GC-T8)")
        undo0 = self.doc.UndoCount
        self.vp.dragTriad("TranslateX", App.Placement(V(8, 4, 10), App.Rotation()))
        self.assertTrue(self.vp.applyTriadValue("12 mm"))
        self.assertPlacement(self.a, App.Placement(V(12, 0, 0), App.Rotation()))
        self.assertPlacement(self.b, App.Placement(V(52, 0, 0), App.Rotation()))
        self.assertEqual(self.doc.UndoCount, undo0 + 2)
        self.doc.undo()
        self.doc.undo()
        pump()
        self.assertPlacement(self.a, App.Placement(V(0, 0, 0), App.Rotation()))
        self.assertPlacement(self.b, App.Placement(V(40, 0, 0), App.Rotation()))

    def test_a_new_click_moves_the_triad_and_closes_the_box(self):
        self.pick(self.a, "Face6", (3, 4, 10))
        self.vp.dragTriad("TranslateX", App.Placement(V(5, 4, 10), App.Rotation()))
        self.assertTrue(self.vp.isTriadBoxOpen())
        Gui.Selection.clearSelection()
        pump()
        self.assertFalse(self.vp.isTriadBoxOpen())
        self.assertFalse(self.vp.DraggerVisibility)
        self.pick(self.b, "Face6", (45, 6, 10))
        triad = self.vp.getTriadPlacement()
        self.assertLess((triad.Base - V(45, 6, 10)).Length, TOL)

    def test_grounded_instance_gets_no_triad(self):
        ground = self.jointgroup.newObject("App::FeaturePython", "GroundedJoint")
        import JointObject

        JointObject.GroundedJoint(ground, self.a)
        self.doc.recompute()
        pump()
        self.pick(self.a, "Face6", (3, 4, 10))
        self.assertFalse(self.vp.DraggerVisibility, "a grounded instance got a triad")

    def test_typed_move_survives_save_and_reopen(self):
        self.pick(self.a, "Face6", (3, 4, 10))
        self.vp.dragTriad("TranslateZ", App.Placement(V(3, 4, 11), App.Rotation()))
        self.assertTrue(self.vp.applyTriadValue("12.5 mm"))
        self.assertPlacement(self.a, App.Placement(V(0, 0, 12.5), App.Rotation()))
        Gui.Selection.clearSelection()
        Gui.ActiveDocument.resetEdit()
        pump()
        self.tmpdir = tempfile.TemporaryDirectory()
        path = os.path.join(self.tmpdir.name, "triad.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        pump()
        self.doc = App.openDocument(path)
        pump()
        a = self.doc.getObject("A")
        self.assertPlacement(a, App.Placement(V(0, 0, 12.5), App.Rotation()))
        self.assertEqual(
            [o for o in self.doc.Objects if hasattr(o, "JointType")], [], "a mate was saved"
        )


class TestTriadOriginGui(TriadGuiCase):
    """C10 (ops#640): the triad alone onto a point, then a ring turns the parts about it."""

    docName = "TriadOriginGui"

    def edge_name(self, obj, p, q):
        """The name of @obj's straight edge from @p to @q (designed geometry, found by its ends)."""
        for i, edge in enumerate(obj.Shape.Edges, 1):
            ends = [v.Point for v in edge.Vertexes]
            if len(ends) == 2 and (
                ((ends[0] - p).Length < TOL and (ends[1] - q).Length < TOL)
                or ((ends[0] - q).Length < TOL and (ends[1] - p).Length < TOL)
            ):
                return f"Edge{i}"
        self.fail(f"no edge {p} to {q} on {obj.Name}")

    def assertTriadAt(self, point):
        shown = self.vp.getTriadPlacement()
        self.assertLess((shown.Base - point).Length, 1e-9, shown.Base)
        self.assertTrue(shown.Rotation.isSame(App.Rotation(), 1e-12), shown.Rotation)

    def test_triad_moves_alone_onto_a_point_and_a_ring_turns_about_it(self):
        self.pick(self.a, "Face6", V(5, 5, 10))
        start = self.a.Placement
        undo0 = self.doc.UndoCount
        corner = V(10, 10, 10)
        self.vp.moveTriadOriginTo(corner)
        # only the triad moved: the part, the selection's triad and the undo stack are as before
        self.assertPlacement(self.a, start)
        self.assertEqual(self.doc.UndoCount, undo0)
        self.assertTriadAt(corner)
        self.assertTrue(self.vp.DraggerVisibility)

        self.vp.dragTriad("RotateZ", App.Placement(corner, App.Rotation(V(0, 0, 1), 90)))
        self.assertPlacement(self.a, turnedAbout(corner, App.Rotation(V(0, 0, 1), 90)))
        self.assertTriadAt(corner)
        self.assertTrue(self.vp.applyTriadValue("45 deg"))
        self.assertPlacement(self.a, turnedAbout(corner, App.Rotation(V(0, 0, 1), 45)))
        self.assertEqual(self.doc.UndoCount, undo0 + 2)
        self.doc.undo()
        pump()
        self.assertPlacement(self.a, turnedAbout(corner, App.Rotation(V(0, 0, 1), 90)))

    def test_a_moved_part_turns_about_the_new_origin_from_where_it_is(self):
        self.pick(self.a, "Face6", V(5, 5, 10))
        self.vp.dragTriad("TranslateX", App.Placement(V(17, 5, 10), App.Rotation()))
        shifted = App.Placement(V(12, 0, 0), App.Rotation())
        self.assertPlacement(self.a, shifted)
        self.assertTrue(self.vp.isTriadBoxOpen())

        corner = V(22, 0, 0)  # the moved box's corner
        self.vp.moveTriadOriginTo(corner)
        self.assertFalse(self.vp.isTriadBoxOpen(), "the box of the earlier drag stays open")
        self.assertPlacement(self.a, shifted)
        self.vp.dragTriad("RotateZ", App.Placement(corner, App.Rotation(V(0, 0, 1), 90)))
        self.assertPlacement(self.a, turnedAbout(corner, App.Rotation(V(0, 0, 1), 90)) * shifted)
        # typed values are measured from the ring drag's start, about the new origin
        self.assertTrue(self.vp.applyTriadValue("-30 deg"))
        self.assertPlacement(self.a, turnedAbout(corner, App.Rotation(V(0, 0, 1), -30)) * shifted)

    def test_two_instances_turn_about_the_new_origin(self):
        self.pick(self.a, "Face6", V(5, 5, 10))
        self.pick(self.b, "Face6", V(45, 5, 10))
        pivot = V(40, 0, 0)  # B's corner
        self.vp.moveTriadOriginTo(pivot)
        turn = turnedAbout(pivot, App.Rotation(V(0, 0, 1), 90))
        self.vp.dragTriad("RotateZ", App.Placement(pivot, App.Rotation(V(0, 0, 1), 90)))
        self.assertPlacement(self.a, turn)
        self.assertPlacement(self.b, turn * App.Placement(V(40, 0, 0), App.Rotation()))

    def test_the_origin_snaps_to_an_edge_end_near_the_cursor(self):
        self.pick(self.a, "Face6", V(5, 5, 10))
        edge = "A." + self.edge_name(self.a, V(10, 0, 10), V(10, 10, 10))
        # within 0.15 of the edge's length (10) of its end: the end (the Transform dialog's snap)
        self.vp.moveTriadOriginTo(V(10, 1, 10), edge)
        self.assertTriadAt(V(10, 0, 10))
        self.vp.moveTriadOriginTo(V(10, 9.2, 10), edge)
        self.assertTriadAt(V(10, 10, 10))
        # mid-edge, or a face: the point itself
        self.vp.moveTriadOriginTo(V(10, 5, 10), edge)
        self.assertTriadAt(V(10, 5, 10))
        self.vp.moveTriadOriginTo(V(9, 1, 10), "A.Face6")
        self.assertTriadAt(V(9, 1, 10))
        self.assertPlacement(self.a, App.Placement())

    def test_moving_the_origin_needs_the_triad(self):
        self.assertFalse(self.vp.DraggerVisibility)
        with self.assertRaises(RuntimeError):
            self.vp.moveTriadOriginTo(V(0, 0, 0))


class TestTriadMouseGui(TriadGuiCase):
    """The triad driven by mouse events in the 3D view (a real window)."""

    docName = "TriadMouseGui"

    def setUp(self):
        super().setUp()
        Gui.getMainWindow().show()
        # as TestSnapModeGui: a landscape window (a portrait one, off screen 400 x 587, puts the
        # view's getPointOnViewport off its own pick) and the fitted camera lifted out of the
        # cubes' height (off screen it can sit inside them: the picks landed at z 0, ops#683)
        Gui.getMainWindow().resize(1400, 900)
        pump(0.3)
        self.view = Gui.ActiveDocument.ActiveView
        self.view.viewTop()
        self.view.fitAll()
        pump()
        camera = self.view.getCameraNode()
        x, y, _z = camera.position.getValue().getValue()
        camera.position.setValue(x, y, 1000.0)
        camera.nearDistance = 0.01
        camera.farDistance = 1.0e5
        pump(0.3)
        self.viewport = self.view.graphicsView().viewport()

    def send_mouse(self, kind, pos, button, buttons, modifiers=QtCore.Qt.NoModifier):
        event = QtGui.QMouseEvent(kind, pos, self.viewport.mapToGlobal(pos), button, buttons, modifiers)
        QtWidgets.QApplication.sendEvent(self.viewport, event)

    def to_widget(self, vp_point):
        _, height = self.view.getSize()
        scale = self.viewport.devicePixelRatioF()
        return QtCore.QPoint(
            int(round(vp_point[0] / scale)), int(round((height - vp_point[1] - 1) / scale))
        )

    def screen(self, point):
        return self.to_widget(self.view.getPointOnScreen(point))

    def click(self, pos):
        self.send_mouse(QtCore.QEvent.MouseButtonPress, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        self.send_mouse(QtCore.QEvent.MouseButtonRelease, pos, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        pump(0.3)

    def drag(self, start, end, steps=12):
        # A press within the double-click interval of the last click is held back by the navigation
        # style until the release (NavigationStyle::processClickEvent), which makes it a click: a
        # drag starts after the interval, as a hand's does
        pump(QtWidgets.QApplication.doubleClickInterval() / 1000.0 + 0.15)
        self.send_mouse(QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        pump(0.05)
        for i in range(1, steps + 1):
            p = QtCore.QPoint(
                start.x() + (end.x() - start.x()) * i // steps,
                start.y() + (end.y() - start.y()) * i // steps,
            )
            self.send_mouse(QtCore.QEvent.MouseMove, p, QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
            pump(0.03)
        self.send_mouse(QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        pump(0.3)

    def arrow_pixel(self, part, origin, direction):
        """A widget point on the triad's @part, searched from @origin along @direction (pixels)."""
        from pivy import coin

        dragger = self.vp.getDragger()
        child = dragger.getPart(part, False)
        self.assertIsNotNone(child)
        viewer = self.view.getViewer()
        manager = viewer.getSoRenderManager()
        scene = manager.getSceneGraph()
        _, height = self.view.getSize()
        scale = self.viewport.devicePixelRatioF()
        for step in range(4, 400, 2):
            w = QtCore.QPoint(origin.x() + direction[0] * step, origin.y() + direction[1] * step)
            vx = int(round(w.x() * scale))
            vy = int(round(height - 1 - w.y() * scale))
            action = coin.SoRayPickAction(manager.getViewportRegion())
            action.setPoint(coin.SbVec2s(vx, vy))
            action.setRadius(2)
            action.apply(scene)
            picked = action.getPickedPoint()
            if picked and picked.getPath().containsNode(child):
                return w
        self.fail(f"no pixel on {part}")

    def test_click_puts_the_triad_at_the_clicked_point(self):
        target = V(3, 4, 10)
        self.click(self.screen(target))
        self.assertTrue(waitFor(lambda: self.vp.DraggerVisibility), "no triad after a click")
        triad = self.vp.getTriadPlacement()
        # within a pixel or two of the aimed point, on the top face
        self.assertLess((triad.Base - target).Length, 0.5, triad.Base)
        self.assertAlmostEqual(triad.Base.z, 10, places=4)

    def test_arrow_drag_is_smooth_one_undo_step_and_opens_the_box(self):
        self.click(self.screen(V(3, 4, 10)))
        self.assertTrue(waitFor(lambda: self.vp.DraggerVisibility))
        undo0 = self.doc.UndoCount
        origin = self.to_widget(self.view.getPointOnScreen(self.vp.getTriadPlacement().Base))
        start = self.arrow_pixel("xTranslatorDragger", origin, (1, 0))
        self.drag(start, QtCore.QPoint(start.x() + 37, start.y()))

        self.assertEqual(self.vp.getTriadHandle(), "TranslateX")
        value = self.vp.getTriadValue()
        self.assertGreater(value, 0.5)
        self.assertGreater(abs(value - round(value)), 1e-6, f"{value}: still in 1 mm steps")
        self.assertLess((self.a.Placement.Base - V(value, 0, 0)).Length, 1e-6, self.a.Placement.Base)
        self.assertEqual(self.doc.UndoCount, undo0 + 1, "the drag is one undo step")

        box = Gui.getMainWindow().findChild(QtWidgets.QLineEdit, "AssemblyTriadValue")
        self.assertIsNotNone(box, "no value box after the drag")
        self.assertTrue(box.isVisible())
        # Typed into the box: Enter applies and keeps the box; Esc closes it and keeps the move
        box.setText("12 mm")
        QtWidgets.QApplication.sendEvent(
            box, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
        )
        pump()
        self.assertLess((self.a.Placement.Base - V(12, 0, 0)).Length, 1e-9, self.a.Placement.Base)
        self.assertTrue(self.vp.isTriadBoxOpen())
        self.assertEqual(self.doc.UndoCount, undo0 + 2)
        QtWidgets.QApplication.sendEvent(
            box, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)
        )
        pump()
        self.assertFalse(self.vp.isTriadBoxOpen())
        self.assertIsNotNone(Gui.ActiveDocument.getInEdit(), "Esc in the box left the assembly")
        self.assertLess((self.a.Placement.Base - V(12, 0, 0)).Length, 1e-9)

        self.doc.undo()
        self.doc.undo()
        pump()
        self.assertLess(self.a.Placement.Base.Length, 1e-9, self.a.Placement.Base)

    def test_body_drag_still_moves_a_part_with_the_triad_shown(self):
        self.click(self.screen(V(7, 7, 10)))
        self.assertTrue(waitFor(lambda: self.vp.DraggerVisibility))
        triad0 = self.vp.getTriadPlacement().Base
        # A press on the face away from the triad's handles (they reach towards +x and +y), then a drag
        start = self.screen(V(1.5, 1.5, 10))
        self.drag(start, QtCore.QPoint(start.x(), start.y() + 30))
        moved = self.a.Placement.Base
        self.assertGreater(moved.Length, 0.5, "the body drag moved nothing")
        self.assertTrue(waitFor(lambda: self.vp.DraggerVisibility), "the triad did not come back")
        triad = self.vp.getTriadPlacement().Base
        self.assertLess((triad - (triad0 + moved)).Length, 1e-6, "the triad did not follow the part")

    def test_alt_click_moves_the_triad_alone(self):
        # C10 (ops#640): Alt (Option) + click on a point of another part, the triad showing
        self.click(self.screen(V(3, 4, 10)))
        self.assertTrue(waitFor(lambda: self.vp.DraggerVisibility))
        selected = [(s.ObjectName, s.SubElementNames) for s in Gui.Selection.getSelectionEx()]
        undo0 = self.doc.UndoCount
        target = V(45, 4, 10)  # B's top face
        pos = self.screen(target)
        pump(QtWidgets.QApplication.doubleClickInterval() / 1000.0 + 0.15)
        self.send_mouse(QtCore.QEvent.MouseMove, pos, QtCore.Qt.NoButton, QtCore.Qt.NoButton)
        pump(0.2)
        alt = QtCore.Qt.AltModifier
        QtWidgets.QApplication.sendEvent(
            self.viewport, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Alt, alt)
        )
        self.send_mouse(
            QtCore.QEvent.MouseButtonPress, pos, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton, alt
        )
        self.send_mouse(
            QtCore.QEvent.MouseButtonRelease, pos, QtCore.Qt.LeftButton, QtCore.Qt.NoButton, alt
        )
        QtWidgets.QApplication.sendEvent(
            self.viewport,
            QtGui.QKeyEvent(QtCore.QEvent.KeyRelease, QtCore.Qt.Key_Alt, QtCore.Qt.NoModifier),
        )
        pump(0.3)
        triad = self.vp.getTriadPlacement()
        self.assertLess((triad.Base - target).Length, 0.5, triad.Base)
        self.assertAlmostEqual(triad.Base.z, 10, places=4)
        # the parts and the selection stay
        self.assertPlacement(self.a, App.Placement())
        self.assertPlacement(self.b, App.Placement(V(40, 0, 0), App.Rotation()))
        self.assertEqual(
            [(s.ObjectName, s.SubElementNames) for s in Gui.Selection.getSelectionEx()], selected
        )
        self.assertEqual(self.doc.UndoCount, undo0)
