# SPDX-License-Identifier: LGPL-2.1-or-later

import FreeCAD
from FreeCAD import Vector, Base, newDocument, closeDocument
import Part

import itertools
import math
import os

if "BUILD_SKETCHER" in FreeCAD.__cmake__:
    import Sketcher

import unittest


class RegressionTests(unittest.TestCase):

    # pylint: disable=attribute-defined-outside-init

    def setUp(self):
        """Create a document for each test in the test suite"""
        self.Doc = newDocument("PartRegressionTest." + self._testMethodName)
        self.KeepTestDoc = False

    def test_issue_4456(self):
        """
        0004456: Regression : Part.Plane.Intersect does not accept plane as argument
        """
        p1 = Part.Plane()
        p2 = Part.Plane(Vector(0, 0, 0), Vector(1, 0, 0))

        result = p1.intersect(p2)
        line = result.pop()
        self.assertEqual(line.Location, Vector(0, 0, 0))
        self.assertEqual(line.Direction, Vector(0, 1, 0))
        # We should now have empty list...
        with self.assertRaises(IndexError):
            result.pop()

    def test_issue_15735(self):
        """
        15735: Point in sketch as loft profile won't work in dev, but works in stable
        The following test is a simplified version of the issue, but the outcome is the same
        """

        if "BUILD_SKETCHER" in FreeCAD.__cmake__:
            # Arrange
            ArcSketch = self.Doc.addObject("Sketcher::SketchObject", "ArcSketch")
            ArcSketch.Placement = Base.Placement(
                Base.Vector(0.000000, 0.000000, 0.000000),
                Base.Rotation(0.500000, 0.500000, 0.500000, 0.500000),
            )
            ArcSketch.MapMode = "Deactivated"

            geoList = []
            geoList.append(
                Part.ArcOfCircle(
                    Part.Circle(
                        Base.Vector(0.000000, 0.000000, 0.000000),
                        Base.Vector(0.000000, 0.000000, 1.000000),
                        10.000000,
                    ),
                    3.141593,
                    6.283185,
                )
            )
            ArcSketch.addGeometry(geoList, False)
            del geoList

            constraintList = []
            ArcSketch.addConstraint(Sketcher.Constraint("Radius", 0, 10.000000))
            constraintList.append(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
            constraintList.append(Sketcher.Constraint("PointOnObject", 0, 2, -1))
            constraintList.append(Sketcher.Constraint("PointOnObject", 0, 1, -1))
            ArcSketch.addConstraint(constraintList)
            del constraintList

            self.Doc.recompute()

            PointSketch = self.Doc.addObject("Sketcher::SketchObject", "PointSketch")
            PointSketch.Placement = Base.Placement(
                Base.Vector(-10.000000, 0.000000, 0.000000),
                Base.Rotation(0.500000, 0.500000, 0.500000, 0.500000),
            )
            PointSketch.MapMode = "Deactivated"

            PointSketch.addGeometry(Part.Point(Base.Vector(0.000000, 0.000000, 0)))

            PointSketch.addConstraint(Sketcher.Constraint("Coincident", 0, 1, -1, 1))

            self.Doc.recompute()

            Loft = self.Doc.addObject("Part::Loft", "Loft")
            Loft.Sections = [
                ArcSketch,
                PointSketch,
            ]
            Loft.Solid = False
            Loft.Ruled = False
            Loft.Closed = False

            # Act
            self.Doc.recompute()

            # Assert
            self.assertTrue(Loft.isValid())
            self.KeepTestDoc = not Loft.isValid()

    def test_OptimalBox(self):
        box = Part.makeBox(1, 1, 1)
        self.assertTrue(box.optimalBoundingBox(True, False).isValid())

    def test_CircularReference(self):

        cube = self.Doc.addObject("Part::Box", "Cube")
        cube.setExpression("Length", "Width + 10mm")
        with self.assertRaises(RuntimeError) as context:
            cube.setExpression("Width", "Length + 10mm")
        assert "Width reference creates a cyclic dependency." in str(context.exception)

        cube.setExpression(".Placement.Base.x", ".Placement.Base.y + 10mm")
        with self.assertRaises(RuntimeError) as context:
            cube.setExpression(".Placement.Base.y", ".Placement.Base.x + 10mm")
        assert ".Placement.Base.y reference creates a cyclic dependency." in str(context.exception)

        cube.recompute()
        v1 = cube.Placement.Base
        cube.recompute()
        assert cube.Placement.Base.isEqual(v1, 1e-6)

    def test_TangentMode3_Issue24254(self):
        """In FreeCAD 1.1 we changed the behavior of the mmTangentPlane, but added code to handle old files
        that relied upon the original tangent plane behavior. This test ensures that old files open with the expected
        tangent plane setup."""

        location = os.path.dirname(os.path.realpath(__file__))
        FreeCAD.openDocument(os.path.join(location, "TestTangentMode3-0.21.FCStd"), True)

        def check_plane(name, expected_pos, expected_normal, expected_xaxis):
            obj = FreeCAD.ActiveDocument.getObject(name)
            if not obj:
                FreeCAD.Console.PrintError(f"{name}: object not found\n")
                return

            pos = obj.Placement.Base
            rot = obj.Placement.Rotation
            normal = rot.multVec(FreeCAD.Vector(0, 0, 1))
            xaxis = rot.multVec(FreeCAD.Vector(1, 0, 0))

            # position
            self.assertAlmostEqual((pos - expected_pos).Length, 0)

            # normal
            self.assertAlmostEqual(normal.getAngle(expected_normal), 0)

            # tangent x-axis
            self.assertAlmostEqual(xaxis.getAngle(expected_xaxis), 0)

        r = 10.0
        rad30 = math.radians(30)
        cos30 = math.cos(rad30)
        sin30 = math.sin(rad30)

        expected_planes = [
            (
                "Sketch001",
                FreeCAD.Vector(-1 * r, 0, 0),  # position
                FreeCAD.Vector(1, 0, 0),  # normal
                FreeCAD.Vector(0, -1, 0),
            ),  # tangent x-axis
            (
                "Sketch002",
                FreeCAD.Vector(sin30 * r, cos30 * cos30 * (-r), cos30 * sin30 * r),
                FreeCAD.Vector(sin30, cos30 * cos30 * (-1), cos30 * sin30),
                FreeCAD.Vector(0, sin30, cos30),
            ),
            (
                "Sketch003",
                FreeCAD.Vector(cos30 * cos30 * r, sin30 * r, cos30 * sin30 * r),
                FreeCAD.Vector(cos30 * cos30, sin30, cos30 * sin30),
                FreeCAD.Vector(sin30, 0, -cos30),
            ),
        ]

        for name, pos, normal, xaxis in expected_planes:
            check_plane(name, pos, normal, xaxis)

    def test_issue_29733_transformShape_bakes_in_transformation(self):
        """
        29733: transformShape(matrix, True) must bake the transformation into the
        underlying geometry, leaving the shape's Placement untouched. Part Explode
        Compound and many third-party addons depend on this behavior.
        """
        sphere = Part.makeSphere(5.0)
        move = FreeCAD.Placement(FreeCAD.Vector(10, 0, 0), FreeCAD.Rotation()).toMatrix()

        returned = sphere.transformShape(move, True)

        self.assertIs(returned, sphere)
        self.assertAlmostEqual(sphere.Placement.Base.x, 0.0)
        self.assertAlmostEqual(sphere.Placement.Base.y, 0.0)
        self.assertAlmostEqual(sphere.Placement.Base.z, 0.0)
        self.assertAlmostEqual(sphere.CenterOfGravity.x, 10.0, places=5)
        self.assertAlmostEqual(sphere.CenterOfGravity.y, 0.0, places=5)
        self.assertAlmostEqual(sphere.CenterOfGravity.z, 0.0, places=5)

    def test_transformed_returns_independent_baked_in_copy(self):
        """
        transformed() must return a new shape with the transformation baked into
        the geometry, leaving the original shape unchanged.
        """
        sphere = Part.makeSphere(5.0)
        move = FreeCAD.Placement(FreeCAD.Vector(10, 0, 0), FreeCAD.Rotation()).toMatrix()

        moved = sphere.transformed(move, copy=True)

        self.assertIsNot(moved, sphere)
        self.assertAlmostEqual(sphere.CenterOfGravity.x, 0.0, places=5)
        self.assertAlmostEqual(moved.Placement.Base.x, 0.0)
        self.assertAlmostEqual(moved.CenterOfGravity.x, 10.0, places=5)

    def test_issue_15716_AttacherEngine_sync(self):
        """
        15716: AttacherType and AttacherEngine property conflict

        When creating a Part2DObject (like a Sketch), the AttacherEngine property
        should be synchronized with AttacherType. Previously, AttacherType was
        correctly set to "Attacher::AttachEnginePlane" but AttacherEngine stayed
        at the default "Engine 3D" instead of "Engine Plane".
        """
        if "BUILD_SKETCHER" in FreeCAD.__cmake__:
            # Create a new sketch (which inherits from Part2DObject)
            sketch = self.Doc.addObject("Sketcher::SketchObject", "TestSketch")
            self.Doc.recompute()

            # The visible AttacherEngine property should match the actual engine type
            # AttacherType is the internal type name, AttacherEngine is the user-visible enum
            attacher_type = sketch.AttacherType
            attacher_engine = sketch.AttacherEngine

            # For a sketch, AttacherType should be AttachEnginePlane
            self.assertEqual(attacher_type, "Attacher::AttachEnginePlane")

            # AttacherEngine should show "Engine Plane" (not "Engine 3D")
            self.assertEqual(attacher_engine, "Engine Plane")

    def test_getSortedClusters(self):
        "Part.getSortedClusters() may crash with short edges"
        poly = self.Doc.addObject("Part::RegularPolygon", "RegularPolygon")
        poly.Circumradius = 1
        for i in range(3, 1004, 50):
            poly.Polygon = i
            poly.recompute()
            clusters = Part.getSortedClusters(poly.Shape.Edges)

            # should be only one cluster
            self.assertEqual(len(clusters), 1)

            # cluster should contain all edges
            self.assertEqual(len(clusters[0]), i)

    def test_fillet_chamfer_missing_edge_link(self):
        """ops#74: a Part::Fillet or Part::Chamfer whose first edge is gone after an edit reports
        that edge and keeps its edge list (the check used to erase from the list it iterated)."""
        if "BUILD_SKETCHER" not in FreeCAD.__cmake__:
            self.skipTest("needs Sketcher")

        def outline(sketch, points):
            sketch.deleteAllGeometry()
            for a, b in zip(points, points[1:] + points[:1]):
                sketch.addGeometry(Part.LineSegment(Vector(*a, 0), Vector(*b, 0)), False)
            n = len(points)
            for k in range(n):
                sketch.addConstraint(Sketcher.Constraint("Coincident", k, 2, (k + 1) % n, 1))

        def verticalEdgeAt(shape, x, y):
            for i, edge in enumerate(shape.Edges, 1):
                box = edge.BoundBox
                if box.XLength < 1e-6 and box.YLength < 1e-6 and box.ZLength > 9:
                    if abs(box.XMin - x) < 1e-6 and abs(box.YMin - y) < 1e-6:
                        return i
            return None

        # Solver off: Part::Fillet's own check reports the edge. Solver on (ops#7): the solver
        # finds no candidate and marks the reference broken, so nothing is filleted either.
        for solver, feature in itertools.product((False, True), ("Fillet", "Chamfer")):
            with self.subTest(feature=feature, solver=solver):
                if not hasattr(self.Doc, "ReferenceSolver"):
                    if solver:
                        continue
                else:
                    # Explicitly, also when off: new documents start with it on.
                    self.Doc.ReferenceSolver = solver
                # A 20 x 10 x 10 block from a sketch; the vertical edges at (20, 0), listed
                # first, and (0, 0) get the fillet or chamfer. Cutting the corner (20, 0) off
                # the sketch leaves no vertical edge there.
                sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch" + feature)
                outline(sketch, [(0, 0), (20, 0), (20, 10), (0, 10)])
                block = self.Doc.addObject("Part::Extrusion", "Block" + feature)
                block.Base = sketch
                block.DirMode = "Custom"
                block.Dir = Vector(0, 0, 1)
                block.LengthFwd = 10
                block.Solid = True
                self.Doc.recompute()
                first = verticalEdgeAt(block.Shape, 20, 0)
                second = verticalEdgeAt(block.Shape, 0, 0)
                rounded = self.Doc.addObject("Part::" + feature, feature)
                rounded.Base = block
                rounded.Edges = [(first, 1.0, 1.0), (second, 1.0, 1.0)]
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                edges = rounded.Edges

                outline(sketch, [(0, 0), (18, 0), (20, 2), (20, 10), (0, 10)])
                self.Doc.recompute()
                self.assertIsNone(verticalEdgeAt(block.Shape, 20, 0))
                self.assertFalse(rounded.isValid())
                if solver:
                    status = rounded.getStatusString()
                    self.assertEqual(status.count("Missing edge reference"), 1, status)
                    self.assertIn("EdgeLinks[0]", status)
                    links = rounded.EdgeLinks[1]
                    self.assertTrue(links[0].startswith("?"), links)
                    self.assertFalse(links[1].startswith("?"), links)
                else:
                    self.assertEqual(rounded.getStatusString().count("Missing edge link"), 1)
                self.assertEqual(rounded.Edges, edges)

    @staticmethod
    def _cornerCut(shape, x, y, centre=(5, 5)):
        """Whether the solid lacks its corner at (x, y), half way up: a point 0.1 mm inside
        both faces of the corner (towards the cube's centre) lies outside a fillet or chamfer of
        radius 1."""
        inward = Vector(0.1 if x < centre[0] else -0.1, 0.1 if y < centre[1] else -0.1, 0)
        return not shape.isInside(Vector(x, y, 5) + inward, 1e-7, True)

    @staticmethod
    def _verticalEdgeAt(shape, x, y):
        for i, edge in enumerate(shape.Edges, 1):
            box = edge.BoundBox
            if box.XLength < 1e-6 and box.YLength < 1e-6 and box.ZLength > 9:
                if abs(box.XMin - x) < 1e-6 and abs(box.YMin - y) < 1e-6:
                    return i
        return None

    def test_fillet_chamfer_base_set_by_hand(self):
        """ops#257: a Part::Fillet or Part::Chamfer whose Base is set to another object by hand
        keeps each edge where it was, on the new base, or the edge goes missing and the
        recompute fails. Its old index used to name whichever edge of the new base had it.

        Three 10 mm cubes: A at the origin, B in the same place but turned 90 degrees about
        its z axis (its edge numbers sit at other corners), C 20 mm over in x (no edge where
        A's was). The feature is on A's vertical edge at (10, 0)."""
        corners = [(0, 0), (10, 0), (10, 10), (0, 10)]
        for solver, feature in itertools.product((False, True), ("Fillet", "Chamfer")):
            with self.subTest(feature=feature, solver=solver):
                if not hasattr(self.Doc, "ReferenceSolver"):
                    if solver:
                        continue
                else:
                    self.Doc.ReferenceSolver = solver
                cubes = {}
                for name in ("A", "B", "C"):
                    cube = self.Doc.addObject("Part::Box", name + feature)
                    cube.Length = cube.Width = cube.Height = 10
                    cubes[name] = cube
                cubes["B"].Placement = Base.Placement(
                    Vector(10, 0, 0), Base.Rotation(Vector(0, 0, 1), 90)
                )
                cubes["C"].Placement.Base = Vector(20, 0, 0)
                self.Doc.recompute()
                onA = self._verticalEdgeAt(cubes["A"].Shape, 10, 0)
                onB = self._verticalEdgeAt(cubes["B"].Shape, 10, 0)
                self.assertNotEqual(onA, onB)  # the designed model: B numbers it otherwise
                rounded = self.Doc.addObject("Part::" + feature, feature)
                rounded.Base = cubes["A"]
                rounded.Edges = [(onA, 1.0, 1.0)]
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())

                # B has the edge at the same place: the feature follows it there.
                rounded.Base = cubes["B"]
                self.assertEqual(rounded.EdgeLinks[1], ["Edge{}".format(onB)])
                self.assertEqual([e[0] for e in rounded.Edges], [onB])
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                cut = [c for c in corners if self._cornerCut(rounded.Shape, *c)]
                self.assertEqual(cut, [(10, 0)])

                # C has no edge there: the link goes missing, and nothing is rounded.
                rounded.Base = cubes["C"]
                [link] = rounded.EdgeLinks[1]
                self.assertTrue(link.startswith("?"), link)
                self.Doc.recompute()
                self.assertFalse(rounded.isValid())
                self.assertIn("Missing edge", rounded.getStatusString())

                # The same index written again is a new pick on C (PR 236 review, H1): the
                # feature rounds C's edge with that index.
                stored = rounded.Edges[0][0]
                rounded.Edges = rounded.Edges
                self.assertEqual(rounded.EdgeLinks[1], ["Edge{}".format(stored)])
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                corner = cubes["C"].Shape.Edges[stored - 1].Vertexes[0].Point
                cCorners = [(20, 0), (30, 0), (30, 10), (20, 10)]
                cut = [c for c in cCorners if self._cornerCut(rounded.Shape, *c, centre=(25, 5))]
                self.assertEqual(cut, [(round(corner.x), round(corner.y))])

    def test_fillet_chamfer_keep_guess(self):
        """ops#258: a Part::Fillet or Part::Chamfer edge that the reference solver guessed stays
        a guess through the feature's recomputes and through a write of the same edges (the edit
        dialog's OK) or of new radii; the guess snaps back when the original edge returns. The
        feature used to write its edges back on every recompute, which made the links anew.

        A 20 x 10 x 10 block extruded from a sketch, the feature on the vertical edge at
        (20, 0). The sketch's right side is drawn again 0.5 mm over: the edge at (20.5, 0) is
        the guess (the original's sketch survives; policy D). Undoing the redraw brings the original
        back."""
        if "BUILD_SKETCHER" not in FreeCAD.__cmake__:
            self.skipTest("needs Sketcher")
        if not hasattr(self.Doc, "ReferenceSolver"):
            self.skipTest("needs the reference solver")

        def outline(sketch, points):
            sketch.deleteAllGeometry()
            for a, b in zip(points, points[1:] + points[:1]):
                sketch.addGeometry(Part.LineSegment(Vector(*a, 0), Vector(*b, 0)), False)
            n = len(points)
            for k in range(n):
                sketch.addConstraint(Sketcher.Constraint("Coincident", k, 2, (k + 1) % n, 1))

        def guessed(feature):
            return [
                entry["guess_kind"]
                for entry in FreeCAD.getReferenceReport(feature)
                if entry.get("status") == "guessed"
            ]

        self.Doc.ReferenceSolver = True
        self.Doc.UndoMode = 1
        for feature in ("Fillet", "Chamfer"):
            with self.subTest(feature=feature):
                sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch" + feature)
                outline(sketch, [(0, 0), (20, 0), (20, 10), (0, 10)])
                block = self.Doc.addObject("Part::Extrusion", "Block" + feature)
                block.Base = sketch
                block.DirMode = "Custom"
                block.Dir = Vector(0, 0, 1)
                block.LengthFwd = 10
                block.Solid = True
                self.Doc.recompute()
                original = self._verticalEdgeAt(block.Shape, 20, 0)
                rounded = self.Doc.addObject("Part::" + feature, feature)
                rounded.Base = block
                rounded.Edges = [(original, 1.0, 1.0)]
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())

                self.Doc.openTransaction("Redraw")
                outline(sketch, [(0, 0), (20.5, 0), (20.5, 10), (0, 10)])
                self.Doc.commitTransaction()
                self.Doc.recompute()
                moved = self._verticalEdgeAt(block.Shape, 20.5, 0)
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual([e[0] for e in rounded.Edges], [moved])
                self.assertEqual(len(guessed(rounded)), 1, rounded.getStatusString())

                # Recomputed again, written with the same edges, and with new radii
                rounded.touch()
                self.Doc.recompute()
                self.assertEqual(len(guessed(rounded)), 1)
                rounded.Edges = rounded.Edges
                self.Doc.recompute()
                self.assertEqual(len(guessed(rounded)), 1)
                rounded.Edges = [(moved, 0.5, 0.5)]
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual(len(guessed(rounded)), 1)

                # Another edge added, before and after it (PR 236 review, M2 and L6): the guess
                # stays with its edge.
                other = self._verticalEdgeAt(block.Shape, 0, 0)
                for edges in ([(moved, 0.5, 0.5), (other, 0.5, 0.5)],
                              [(other, 0.5, 0.5), (moved, 0.5, 0.5)]):
                    rounded.Edges = edges
                    self.Doc.recompute()
                    self.assertTrue(rounded.isValid(), rounded.getStatusString())
                    self.assertEqual(len(guessed(rounded)), 1, edges)
                    [entry] = [
                        e for e in FreeCAD.getReferenceReport(rounded) if e.get("status") == "guessed"
                    ]
                    self.assertEqual(entry["index"], [e[0] for e in edges].index(moved))
                rounded.Edges = [(moved, 0.5, 0.5)]
                self.Doc.recompute()
                self.assertEqual(len(guessed(rounded)), 1)

                # The redraw undone, the original edge returns: the guess snaps back to it.
                self.Doc.undo()
                self.Doc.recompute()
                self.assertTrue(rounded.isValid(), rounded.getStatusString())
                self.assertEqual(guessed(rounded), [])
                self.assertEqual(
                    [e[0] for e in rounded.Edges], [self._verticalEdgeAt(block.Shape, 20, 0)]
                )

    def tearDown(self):
        """Clean up our test, optionally preserving the test document"""
        # This flag allows doing something like this:
        #   self.KeepTestDoc = True
        #   import TestApp
        #   TestApp.Test("TestPartApp.RegressionTests.test_issue_15735")
        # to leave the test document(s) around for further examination in an interactive setting.
        if hasattr(self, "KeepTestDoc") and self.KeepTestDoc:
            return
        closeDocument(self.Doc.Name)
