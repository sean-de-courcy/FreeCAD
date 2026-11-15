# SPDX-License-Identifier: LGPL-2.1-or-later

"""Onshape's sketch behaviour, round 3 of the experiment (FreeCAD-CH ops#640).

Designed geometry only: a 20 x 10 x 5 box Pad from the origin, and sketches on its top (z 5).
Expected values are geometric (the box's corners and edges)."""

import math

import FreeCAD
import Part
import Sketcher
from PySide import QtCore, QtGui
from SketcherTests.GuiTestCase import FreeCADGui, SketcherGuiTestCase

V = FreeCAD.Vector
TOL = 1e-6

SKETCHER_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher"
TOOLS_PARAMS = SKETCHER_PARAMS + "/Tools"

# A top view centred on (10, 5), 30 mm high (as TestAutoConstraintsGui's)
TOP_VIEW_CAMERA = """#Inventor V2.1 ascii
OrthographicCamera {
  viewportMapping ADJUST_CAMERA
  position 10 5 100
  orientation 0 0 1 0
  nearDistance 1
  farDistance 200
  aspectRatio 1
  focalDistance 100
  height 30
}
"""


class Round3GuiCase(SketcherGuiTestCase):
    """The box, a sketch on its top, and drawing by clicks in a top view."""

    on_face = False  # True: the sketch is attached to the box's top face, else to XY at z 5
    rounded_corner = False  # True: the box's corner (20, 10) is rounded r5 (an arc edge on top)

    def setUp(self):
        super().setUp()
        if not QtGui.QFontDatabase.families():
            self.skipTest("Qt has no fonts; off screen, set QT_QPA_FONTDIR")
        self.saved_params = []
        self.set_param(SKETCHER_PARAMS, "Bool", "ContinuousCreationMode", False)
        self.set_param(TOOLS_PARAMS, "Int", "OnViewParameterVisibility", 0)

        FreeCADGui.activateWorkbench("PartDesignWorkbench")
        self.doc = FreeCAD.newDocument(type(self).__name__)
        self.doc.UndoMode = 1  # the conflict refusal undoes with the constraint's command
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        xy = self.body.Origin.OriginFeatures[3]
        base = self.body.newObject("Sketcher::SketchObject", "Base")
        base.AttachmentSupport = [(xy, "")]
        base.MapMode = "FlatFace"
        if self.rounded_corner:
            # the corner (20, 10) rounded r5: an arc centre (15, 5) from (20, 5) to (15, 10)
            base.addGeometry(Part.LineSegment(V(0, 0, 0), V(20, 0, 0)))
            base.addGeometry(Part.LineSegment(V(20, 0, 0), V(20, 5, 0)))
            base.addGeometry(
                Part.ArcOfCircle(Part.Circle(V(15, 5, 0), V(0, 0, 1), 5), 0, math.pi / 2)
            )
            base.addGeometry(Part.LineSegment(V(15, 10, 0), V(0, 10, 0)))
            base.addGeometry(Part.LineSegment(V(0, 10, 0), V(0, 0, 0)))
            for i in range(5):
                base.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 5, 1))
        else:
            corners = [V(0, 0, 0), V(20, 0, 0), V(20, 10, 0), V(0, 10, 0)]
            for i in range(4):
                base.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
            for i in range(4):
                base.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
        self.doc.recompute()
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = base
        self.pad.Length = 5.0
        self.doc.recompute()

        self.sketch = self.body.newObject("Sketcher::SketchObject", "Sketch")
        if self.on_face:
            self.sketch.AttachmentSupport = [(self.pad, self.top_face())]
            self.sketch.MapMode = "FlatFace"
        else:
            self.sketch.AttachmentSupport = [(xy, "")]
            self.sketch.MapMode = "FlatFace"
            self.sketch.AttachmentOffset = FreeCAD.Placement(V(0, 0, 5), FreeCAD.Rotation())
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

    # The model -----------------------------------------------------------------------------

    def top_face(self):
        for i, face in enumerate(self.pad.Shape.Faces):
            if abs(face.CenterOfMass.z - 5) < TOL and abs(face.normalAt(0, 0).z - 1) < TOL:
                return "Face%d" % (i + 1)
        self.fail("No top face on the pad")

    def pad_vertex_at(self, point):
        for i, vertex in enumerate(self.pad.Shape.Vertexes):
            if vertex.Point.distanceToPoint(point) < TOL:
                return "Vertex%d" % (i + 1)
        self.fail("No pad vertex at %s" % point)

    def pad_edge_between(self, a, b):
        for i, edge in enumerate(self.pad.Shape.Edges):
            ends = [v.Point for v in edge.Vertexes]
            if len(ends) == 2 and (
                (ends[0].distanceToPoint(a) < TOL and ends[1].distanceToPoint(b) < TOL)
                or (ends[0].distanceToPoint(b) < TOL and ends[1].distanceToPoint(a) < TOL)
            ):
                return "Edge%d" % (i + 1)
        self.fail("No pad edge from %s to %s" % (a, b))

    def world(self, point):
        """A sketch point in world coordinates."""
        return self.sketch.getGlobalPlacement().multVec(point)

    def links(self):
        objects = self.sketch.ExternalGeometry
        return [(obj.Name, sub) for obj, subs in objects for sub in subs] if objects else []

    # The editor ----------------------------------------------------------------------------

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

    def click_tolerance(self):
        """How far a click can land from the world point aimed at: a click is on a whole pixel
        (1.5 pixels of the view in model units)."""
        a = self.view.getPointOnFocalPlane((100, 100))
        size = max(
            (self.view.getPointOnFocalPlane((101, 100)) - a).Length,
            (self.view.getPointOnFocalPlane((100, 101)) - a).Length,
        )
        return 1.5 * size

    def screen_point(self, x, y):
        """The viewport point of world (x, y) in the top view, corrected as
        TestAutoConstraintsGui's screen_point is."""
        target = V(x, y, 5)
        guess = V(target)
        for _ in range(20):
            hit = self.view.getPointOnFocalPlane(self.view.getPointOnScreen(guess))
            error = V(target.x - hit.x, target.y - hit.y, 0)
            if error.Length < 1e-6:
                break
            guess += error
        return self.viewport_to_qpoint(self.view, self.viewport, self.view.getPointOnScreen(guess))

    def draw(self, command, points, added=1):
        """Run a drawing tool and click at each world (x, y) in turn."""
        before = self.sketch.GeometryCount
        FreeCADGui.runCommand(command)
        self.flush_gui(150)
        for x, y in points:
            self.move(self.viewport, self.screen_point(x, y))
            self.flush_gui(200)
            point = self.screen_point(x, y)
            self.move(self.viewport, point)
            self.click(self.viewport, point)
            self.flush_gui(200)
        self.assertTrue(
            self.wait_until(lambda: self.sketch.GeometryCount == before + added, 2000),
            "Expected %s to add %d geometries" % (command, added),
        )
        self.flush_gui(150)

    def describe(self):
        return [
            (c.Type, c.First, c.FirstPos, c.Second, c.SecondPos) for c in self.sketch.Constraints
        ] + [self.links()]


class TestSketchModelInferenceGui(Round3GuiCase):
    """Rank 18's first slice: a drawing tool's point placed over a model vertex or edge in the
    sketch plane snaps to it and gets the model element as external geometry and a Coincident or
    Point on object to it, as Onshape's inference onto existing features does (gap S17). Here the
    sketch is on XY at z 5, so the box (the Body's solid before the sketch) is what it snaps to."""

    def external_constraint(self, kind, geo, pos):
        for c in self.sketch.Constraints:
            if c.Type != kind:
                continue
            if c.First == geo and c.FirstPos == pos and c.Second <= -3:
                return c
            if kind == "Coincident" and c.Second == geo and c.SecondPos == pos and c.First <= -3:
                return c
        return None

    def test_a_line_started_near_a_model_corner_snaps_and_is_coincident_with_it(self):
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(20.04, 9.97), (12, 4)])
        start = self.world(self.sketch.Geometry[0].StartPoint)
        self.assertLess((start - V(20, 10, 5)).Length, 1e-6, "The start snapped to the corner")
        self.assertIn(("Pad", self.pad_vertex_at(V(20, 10, 5))), self.links(), self.describe())
        self.assertIsNotNone(
            self.external_constraint("Coincident", 0, 1),
            "Expected the start coincident with the linked corner: %s" % self.describe(),
        )

    def test_a_line_ended_on_a_model_edge_is_on_it(self):
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(5, 3), (12, 10.04)])
        end = self.world(self.sketch.Geometry[0].EndPoint)
        self.assertLess(abs(end.y - 10), 1e-6, "The end snapped onto the edge y = 10")
        edge = self.pad_edge_between(V(0, 10, 5), V(20, 10, 5))
        self.assertIn(("Pad", edge), self.links(), self.describe())
        self.assertIsNotNone(
            self.external_constraint("PointOnObject", 0, 2),
            "Expected the end on the linked edge: %s" % self.describe(),
        )

    def symmetric_on_external(self, geo, pos):
        for c in self.sketch.Constraints:
            if c.Type != "Symmetric":
                continue
            if c.First <= -3 and c.Second == c.First and c.FirstPos == 1 and c.SecondPos == 2:
                if c.Third == geo and c.ThirdPos == pos:
                    return c
        return None

    def test_a_line_ended_near_a_model_edge_s_middle_snaps_to_it_and_is_symmetric(self):
        """SQ2: Onshape's model edge midpoint is a pickable point within about 8 px along the edge
        of its middle (the edge itself within about 5 px). The top edge y = 10 runs x 0..20, its
        middle (10, 10); the click is 0.15 mm along it (about 4.5 px in a 30 mm view, nearer than
        the midpoint radius, but off it by more than the sketch's confusion)."""
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(5, 3), (10.15, 10.04)])
        end = self.world(self.sketch.Geometry[0].EndPoint)
        self.assertLess((end - V(10, 10, 5)).Length, 1e-6, "The end snapped to the middle")
        edge = self.pad_edge_between(V(0, 10, 5), V(20, 10, 5))
        self.assertIn(("Pad", edge), self.links(), self.describe())
        self.assertIsNotNone(
            self.symmetric_on_external(0, 2),
            "Expected the end symmetric about the linked edge's ends: %s" % self.describe(),
        )
        self.assertIsNone(self.external_constraint("PointOnObject", 0, 2), self.describe())

    def test_a_line_ended_on_a_model_edge_beyond_its_middle_s_radius_is_on_it(self):
        """0.4 mm along the edge from its middle (about 12 px) is the edge, not the middle."""
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(5, 3), (10.4, 10.04)])
        end = self.world(self.sketch.Geometry[0].EndPoint)
        # the click lands on a pixel: x within a pixel or two of 10.4, y on the edge
        self.assertLess(abs(end.y - 10), 1e-6, "The end snapped onto the edge")
        self.assertLess(abs(end.x - 10.4), 0.1, "The end stayed where it was clicked along the edge")
        self.assertIsNotNone(self.external_constraint("PointOnObject", 0, 2), self.describe())
        self.assertIsNone(self.symmetric_on_external(0, 2), self.describe())

    def test_a_point_away_from_the_model_links_nothing(self):
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(5, 3), (12, 6)])
        self.assertEqual(self.links(), [], self.describe())

    def test_shift_suppresses_the_inference_onto_the_model(self):
        """Onshape: Shift held suppresses inferences (as rank 58 for the sketch's own). Shift is
        held as TestSketchShiftInferenceGui holds it (a QTest press; released in tearDown)."""
        from PySide6 import QtTest

        self.start_edit()
        self.shift_held = True
        QtTest.QTest.keyPress(
            FreeCADGui.getMainWindow().windowHandle(), QtCore.Qt.Key_Shift, QtCore.Qt.ShiftModifier
        )
        self.draw("Sketcher_CreateLine", [(20.04, 9.97), (12, 4)])
        self.assertEqual(self.links(), [], self.describe())
        start = self.world(self.sketch.Geometry[0].StartPoint)
        self.assertGreater((start - V(20, 10, 5)).Length, 1e-3, "No snap with Shift held")

    def tearDown(self):
        if getattr(self, "shift_held", False):
            from PySide6 import QtTest

            QtTest.QTest.keyRelease(
                FreeCADGui.getMainWindow().windowHandle(), QtCore.Qt.Key_Shift
            )
        super().tearDown()


class TestSketchModelInferenceOnFaceGui(TestSketchModelInferenceGui):
    """The same, with the sketch attached to the box's top face (the support is the snap
    source)."""

    on_face = True


class TestSketchModelArcMidpointGui(Round3GuiCase):
    """SQ2 on an arc (selection parity 10, item c): the box's corner (20, 10) is rounded r5, so
    its top has an arc edge, centre (15, 5), from (20, 5) to (15, 10); its middle is at 45 deg,
    (15 + 5 cos 45, 5 + 5 sin 45). A line ended near that middle snaps to it and gets a Midpoint
    to the linked arc (Onshape's MIDPOINT with an arc, facts SK9), not a Point on object."""

    rounded_corner = True
    external_constraint = TestSketchModelInferenceGui.external_constraint

    CENTRE = V(15, 5, 5)
    RADIUS = 5.0

    def arc_point(self, along, out=0.0):
        """The world (x, y) `along` mm along the arc from its middle (counter-clockwise), `out`
        mm outside it."""
        angle = math.pi / 4 + along / self.RADIUS
        r = self.RADIUS + out
        return (self.CENTRE.x + r * math.cos(angle), self.CENTRE.y + r * math.sin(angle))

    def arc_edge(self):
        return self.pad_edge_between(V(20, 5, 5), V(15, 10, 5))

    def test_a_line_ended_near_a_model_arc_s_middle_snaps_to_it_and_is_midpoint(self):
        """0.15 mm along the arc and 0.04 mm outside it, as the straight edge's test."""
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(5, 3), self.arc_point(0.15, 0.04)])
        end = self.world(self.sketch.Geometry[0].EndPoint)
        middle = V(*self.arc_point(0.0), 5)
        self.assertLess((end - middle).Length, 1e-6, "The end snapped to the arc's middle")
        self.assertIn(("Pad", self.arc_edge()), self.links(), self.describe())
        self.assertIsNotNone(
            self.external_constraint("Midpoint", 0, 2),
            "Expected the end at the linked arc's midpoint: %s" % self.describe(),
        )
        self.assertIsNone(self.external_constraint("PointOnObject", 0, 2), self.describe())

    def test_a_line_ended_on_a_model_arc_beyond_its_middle_s_radius_is_on_it(self):
        """0.4 mm along the arc from its middle (about 12 px) is the arc, not its middle."""
        self.start_edit()
        self.draw("Sketcher_CreateLine", [(5, 3), self.arc_point(0.4, 0.04)])
        end = self.world(self.sketch.Geometry[0].EndPoint)
        self.assertLess(
            abs((end - self.CENTRE).Length - self.RADIUS), 1e-6, "The end snapped onto the arc"
        )
        self.assertGreater(
            (end - V(*self.arc_point(0.0), 5)).Length, 0.2, "The end did not go to the middle"
        )
        self.assertIn(("Pad", self.arc_edge()), self.links(), self.describe())
        self.assertIsNotNone(self.external_constraint("PointOnObject", 0, 2), self.describe())
        self.assertIsNone(self.external_constraint("Midpoint", 0, 2), self.describe())


class TestSketchModelArcMidpointOnFaceGui(TestSketchModelArcMidpointGui):
    """The same, with the sketch attached to the box's top face."""

    on_face = True


class TestSketchConflictKeptGui(Round3GuiCase):
    """ops#640 (sketch conflicts; rank 45 before it): a constraint that conflicts is kept, as
    Onshape keeps it (PL1d): the solve leaves it out and solves the rest, so no line shrinks to a
    point (gap S9), and the conflict list names it for the red marks. Lines 0 and 1 are
    horizontal, 10 long, 5 apart; a Perpendicular between them can only hold with a line of
    length 0."""

    def setUp(self):
        super().setUp()
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(0, 5, 0), V(10, 5, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 1))
        self.doc.recompute()

    def constrain(self, command, *subs):
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        for sub in subs:
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, sub)
        FreeCADGui.runCommand(command)
        self.flush_gui(300)

    def lengths(self):
        return [geo.length() for geo in self.sketch.Geometry]

    def test_a_perpendicular_between_two_horizontal_lines_is_kept(self):
        self.constrain("Sketcher_ConstrainPerpendicular", "Edge1", "Edge2")
        self.assertEqual(
            [c.Type for c in self.sketch.Constraints],
            ["Horizontal", "Horizontal", "Perpendicular"],
            self.describe(),
        )
        self.assertIn(3, self.sketch.ConflictingConstraints, self.describe())
        for length in self.lengths():
            self.assertAlmostEqual(length, 10.0, places=6)

    def test_a_parallel_between_a_horizontal_and_a_vertical_line_is_kept(self):
        """Parallel has no pre-check of its own (Vertical on a Horizontal line has one), so the
        solver sees it: line 2 is vertical, 10 long, and only a line of length 0 is both."""
        self.sketch.addGeometry(Part.LineSegment(V(15, 0, 0), V(15, 10, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Vertical", 2))
        self.doc.recompute()
        self.constrain("Sketcher_ConstrainParallel", "Edge1", "Edge3")
        self.assertEqual(
            [c.Type for c in self.sketch.Constraints],
            ["Horizontal", "Horizontal", "Vertical", "Parallel"],
            self.describe(),
        )
        self.assertIn(4, self.sketch.ConflictingConstraints, self.describe())
        for length in self.lengths():
            self.assertAlmostEqual(length, 10.0, places=6)

    def test_a_kept_conflict_is_one_undo_step(self):
        """The kept constraint is an ordinary step: Undo takes it away, Redo puts it back."""
        self.constrain("Sketcher_ConstrainPerpendicular", "Edge1", "Edge2")
        self.assertEqual(self.sketch.ConstraintCount, 3, self.describe())
        FreeCADGui.runCommand("Std_Undo")
        self.flush_gui(300)
        self.assertEqual(
            [c.Type for c in self.sketch.Constraints], ["Horizontal", "Horizontal"], self.describe()
        )
        FreeCADGui.runCommand("Std_Redo")
        self.flush_gui(300)
        self.assertEqual(self.sketch.ConstraintCount, 3, self.describe())

    def test_the_sketch_with_a_kept_conflict_recomputes_as_a_warning(self):
        self.constrain("Sketcher_ConstrainPerpendicular", "Edge1", "Edge2")
        self.doc.recompute()
        self.assertNotIn("Invalid", self.sketch.State, self.describe())
        self.assertIn("Warning", self.sketch.State, self.describe())

    def test_a_conflicting_value_typed_into_a_dimension(self):
        """Oracle 10b q-b (PL1d): line 0 has a length 10 and a horizontal distance 10 between its
        ends (they agree); 12 typed into the length conflicts. As in Onshape the value is kept,
        the line stays as drawn, its entity is red and the messages line reads "Sketch could not
        be solved." (the way EditDatumDialog sets it: setDatum in a transaction, then a solve)."""
        from PySide import QtWidgets

        length = self.sketch.addConstraint(Sketcher.Constraint("Distance", 0, 10.0))
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 10.0))
        self.doc.recompute()
        self.start_edit()
        self.doc.openTransaction("Change value")
        self.sketch.setDatum(length, FreeCAD.Units.Quantity("12 mm"))
        self.doc.commitTransaction()
        self.sketch.solve()
        self.flush_gui(300)
        self.assertAlmostEqual(self.sketch.Constraints[length].Value, 12.0, places=6)
        self.assertIn(length + 1, self.sketch.ConflictingConstraints, self.describe())
        for size in self.lengths():
            self.assertAlmostEqual(size, 10.0, places=6)
        texts = [label.text() for label in FreeCADGui.getMainWindow().findChildren(QtWidgets.QLabel)]
        self.assertTrue(any("Sketch could not be solved." in text for text in texts), texts)
        colours = TestSketchOverdefinedRedGui.curve_colours(self)
        red = TestSketchOverdefinedRedGui.RED
        self.assertTrue(TestSketchOverdefinedRedGui.near(colours[0], red), colours)
        self.assertFalse(TestSketchOverdefinedRedGui.near(colours[1], red), colours)

    def test_a_constraint_that_fits_is_kept(self):
        """Control: an Equal between the two lines holds without collapsing anything."""
        self.constrain("Sketcher_ConstrainEqual", "Edge1", "Edge2")
        self.assertEqual(self.sketch.ConstraintCount, 3, self.describe())


class TestSketchOverdefinedRedGui(Round3GuiCase):
    """Rank 51: only the over-defined entities are red, not the whole sketch orange (gap S31).
    Line 0 carries two Horizontal constraints (one redundant); lines 1 and 2 are free."""

    RED = (0.87, 0.12, 0.12)

    @staticmethod
    def edge_colour():
        """An under-constrained edge's colour: the preferences' (a theme pack, as the first start
        applies, sets one), else the default blue (0.24, 0.55, 1.0)."""
        packed = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned(
            "EditedEdgeColor", 0x3D8CFFFF
        )
        return tuple(((packed >> shift) & 0xFF) / 255.0 for shift in (24, 16, 8))

    def setUp(self):
        super().setUp()
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(0, 5, 0), V(10, 8, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(0, 9, 0), V(4, 12, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", 0))
        self.doc.recompute()

    def curve_colours(self):
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
        return [tuple(c.getValue()) for c in path.getTail().diffuseColor.getValues()]

    @staticmethod
    def near(colour, expected):
        return all(abs(a - e) < 0.02 for a, e in zip(colour, expected))

    def test_only_the_redundant_line_is_red(self):
        colours = self.curve_colours()
        self.assertEqual(sum(self.near(c, self.RED) for c in colours), 1, colours)
        self.assertEqual(sum(self.near(c, self.edge_colour()) for c in colours), 2, colours)


class TestSketchOnshapeConstraintsGui(Round3GuiCase):
    """Rank 44's rest: Symmetric axis first and for two lines or circles (gaps S5, S6), Fix on a
    vertex (S7), Normal (Shift+K, S30). Picks first, by selection, then the command."""

    def constrain(self, command, *subs):
        self.doc.recompute()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        for sub in subs:
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, sub)
        FreeCADGui.runCommand(command)
        self.flush_gui(300)
        self.sketch.solve()

    def types(self):
        return sorted(c.Type for c in self.sketch.Constraints)

    @staticmethod
    def mirror_x(point):
        return V(-point.x, point.y, 0)

    def test_symmetric_axis_first_two_lines_mirror(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, -10, 0), V(0, 10, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(2, 1, 0), V(6, 3, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(-5.5, 3.2, 0), V(-2.2, 1.1, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.constrain("Sketcher_ConstrainSymmetric", "Edge1", "Edge2", "Edge3")
        self.assertEqual(self.types(), ["Block", "Symmetric", "Symmetric"], self.describe())
        a, b = self.sketch.Geometry[1], self.sketch.Geometry[2]
        for end in (a.StartPoint, a.EndPoint):
            mirrored = self.mirror_x(end)
            self.assertLess(
                min((mirrored - b.StartPoint).Length, (mirrored - b.EndPoint).Length), 1e-6
            )

    def test_symmetric_axis_and_two_circles_mirror_and_match(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, -10, 0), V(0, 10, 0)))
        self.sketch.addGeometry(Part.Circle(V(3, 2, 0), V(0, 0, 1), 1))
        self.sketch.addGeometry(Part.Circle(V(-3.3, 2.1, 0), V(0, 0, 1), 1.4))
        self.sketch.addConstraint(Sketcher.Constraint("Block", 0))
        self.constrain("Sketcher_ConstrainSymmetric", "Edge1", "Edge2", "Edge3")
        self.assertEqual(self.types(), ["Block", "Equal", "Symmetric"], self.describe())
        c1, c2 = self.sketch.Geometry[1], self.sketch.Geometry[2]
        self.assertAlmostEqual(c1.Radius, c2.Radius, places=6)
        self.assertLess((self.mirror_x(c1.Center) - c2.Center).Length, 1e-6)

    def test_fix_on_a_line_end_fixes_that_point(self):
        self.sketch.addGeometry(Part.LineSegment(V(1, 2, 0), V(7, 5, 0)))
        self.constrain("Sketcher_ConstrainBlock", "Vertex1")
        self.assertEqual(self.types(), ["DistanceX", "DistanceY"], self.describe())
        self.assertLess((self.sketch.Geometry[0].StartPoint - V(1, 2, 0)).Length, 1e-6)

    def test_fix_on_a_sketch_point_blocks_it(self):
        self.sketch.addGeometry(Part.Point(V(3, 4, 0)))
        self.constrain("Sketcher_ConstrainBlock", "Vertex1")
        self.assertEqual(self.types(), ["Block"], self.describe())

    def test_normal_puts_the_line_through_the_circle_s_centre(self):
        self.sketch.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5))
        self.sketch.addGeometry(Part.LineSegment(V(6, 1, 0), V(12, 4, 0)))
        self.constrain("Sketcher_ConstrainNormal", "Edge2", "Edge1")
        self.assertIn("Perpendicular", self.types(), self.describe())
        line = self.sketch.Geometry[1]
        direction = (line.EndPoint - line.StartPoint).normalize()
        offset = line.StartPoint - self.sketch.Geometry[0].Center
        self.assertLess(abs(offset.x * direction.y - offset.y * direction.x), 1e-6)


class TestSketchOnshapeShapesGui(Round3GuiCase):
    """Rank 49: the aligned rectangle stays a rectangle (gap S26); arc length by the arc's two
    ends and the arc (S11). Rank 47: Offset tool first, one side of an open line (S21)."""

    def clicks(self, points):
        for x, y in points:
            self.move(self.viewport, self.screen_point(x, y))
            self.flush_gui(200)
            point = self.screen_point(x, y)
            self.move(self.viewport, point)
            self.click(self.viewport, point)
            self.flush_gui(250)

    def test_the_aligned_rectangle_is_square_cornered(self):
        self.start_edit()
        self.draw("Sketcher_CreateRectangle_Aligned", [(1, 1), (9, 3), (5, 8)], added=4)
        lines = self.sketch.Geometry
        for i in range(4):
            a = lines[i].EndPoint - lines[i].StartPoint
            b = lines[(i + 1) % 4].EndPoint - lines[(i + 1) % 4].StartPoint
            self.assertLess(abs(a.dot(b)) / (a.Length * b.Length), 1e-6, self.describe())
        self.assertIn("Perpendicular", [c.Type for c in self.sketch.Constraints])
        # the first side is the two clicks (to the pixel)
        start = self.world(lines[0].StartPoint)
        self.assertLess((start - V(1, 1, 5)).Length, self.click_tolerance(), start)

    def test_arc_length_from_the_two_ends_and_the_arc(self):
        import math

        self.set_param(SKETCHER_PARAMS, "Bool", "ShowDialogOnDistanceConstraint", False)
        self.sketch.addGeometry(
            Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5), 0, math.pi / 2)
        )
        self.doc.recompute()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        for sub in ("Vertex1", "Vertex2", "Edge1"):
            FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, sub)
        FreeCADGui.runCommand("Sketcher_Dimension")
        self.flush_gui(300)
        self.key_click(self.viewport, QtCore.Qt.Key_Return)
        self.flush_gui(200)
        distances = [c for c in self.sketch.Constraints if c.Type == "Distance"]
        self.assertEqual(len(distances), 1, self.describe())
        self.assertEqual(distances[0].First, 0)
        self.assertAlmostEqual(distances[0].Value, 5 * math.pi / 2, places=5)

    def offset_lines(self):
        return [
            g
            for i, g in enumerate(self.sketch.Geometry)
            if i > 0 and not self.sketch.getConstruction(i) and hasattr(g, "StartPoint")
        ]

    def check_one_sided_offset(self, y=3.0):
        lines = self.offset_lines()
        self.assertEqual(len(lines), 1, self.describe())
        # the distance is the click's (to the pixel); both ends at it: one-sided and parallel.
        # To 1e-5 mm: an end can carry the click's float32 coordinate (3.0125 came back as
        # 3.0125010013580322), so 6 places failed one test or another by the click's pixel
        self.assertAlmostEqual(lines[0].StartPoint.y, lines[0].EndPoint.y, places=5)
        self.assertAlmostEqual(lines[0].StartPoint.y, y, delta=self.click_tolerance())

    def test_offset_of_a_selected_open_line_is_one_sided(self):
        self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.doc.recompute()
        self.start_edit()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.sketch.Name, "Edge1")
        FreeCADGui.runCommand("Sketcher_Offset")
        self.flush_gui(200)
        self.clicks([(5, 3)])
        self.check_one_sided_offset()

    def test_offset_starts_with_nothing_selected(self):
        # the line is off the sketch's H axis, so the first click picks the line, not the axis
        self.sketch.addGeometry(Part.LineSegment(V(0, 2, 0), V(10, 2, 0)))
        self.doc.recompute()
        self.start_edit()
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.runCommand("Sketcher_Offset")
        self.flush_gui(200)
        self.clicks([(5, 2), (5, 5)])
        self.check_one_sided_offset(5.0)
