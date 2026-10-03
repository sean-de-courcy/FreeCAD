# SPDX-License-Identifier: LGPL-2.1-or-later

"""A sketch whose external geometry lost its element (ops#72).

The sketch fails, names the source and the missing element, and keeps the link in
`ExternalGeometry` (so it still depends on the source) and the frozen geometry (so it still
shows, and the constraints on it still solve). Before, it stayed valid on the frozen geometry and
dropped the link. Every model is designed geometry; results are judged geometrically."""

import unittest

import FreeCAD
import Part
import Sketcher

App = FreeCAD
V = App.Vector
TOL = 1e-6


def add_lines(sketch, points):
    """Line segments through the points, open (no constraints: a pad only needs the wire)."""
    for p, q in zip(points, points[1:]):
        sketch.addGeometry(Part.LineSegment(V(*p, 0), V(*q, 0)), False)


def edge_between(shape, a, b):
    """The name of the shape's edge from point a to point b (either way)."""
    a, b = V(*a), V(*b)
    for i, edge in enumerate(shape.Edges, 1):
        ends = [v.Point for v in edge.Vertexes]
        if len(ends) == 2 and (
            (ends[0].isEqual(a, TOL) and ends[1].isEqual(b, TOL))
            or (ends[0].isEqual(b, TOL) and ends[1].isEqual(a, TOL))
        ):
            return f"Edge{i}"
    raise AssertionError(f"no edge from {a} to {b}")


def face_at_x(shape, x):
    """The name of the shape's planar face lying in the plane at x."""
    for i, face in enumerate(shape.Faces, 1):
        box = face.BoundBox
        if abs(box.XMin - x) < TOL and abs(box.XMax - x) < TOL:
            return f"Face{i}"
    raise AssertionError(f"no face at x = {x}")


def external_lines(sketch):
    """The sketch's external geometry after the two axes, as global (start, end) pairs."""
    placement = sketch.getGlobalPlacement()
    lines = []
    for geo in list(sketch.ExternalGeo)[2:]:
        lines.append(
            (placement.multVec(geo.StartPoint), placement.multVec(geo.EndPoint))
        )
    return lines


class TestSketchMissingExternal(unittest.TestCase):
    """A 20 x 20 x 10 pad from a sketch at z = 0. Sketch2 on the XY plane projects the pad's top
    edge at x = 20 and has a circle r 2 centred on it at y = 10. The edit deletes the profile's
    line at x = 20 and draws a V, (20, 0)-(25, 10)-(20, 20), so the side face at x = 20 and its
    edges are gone."""

    solver = False

    def setUp(self):
        if "BUILD_PART_DESIGN" not in App.__cmake__:
            self.skipTest("needs PartDesign")
        self.doc = App.newDocument("TestSketchMissingExternal")
        if self.solver and not hasattr(self.doc, "ReferenceSolver"):
            self.skipTest("needs the reference solver")
        if hasattr(self.doc, "ReferenceSolver"):
            # Explicitly, also when off: new documents start with it on (ops#7 Q7).
            self.doc.ReferenceSolver = self.solver
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.profile = self.body.newObject("Sketcher::SketchObject", "Profile")
        add_lines(self.profile, [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)])
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Length = 10
        self.doc.recompute()

        self.sketch = self.body.newObject("Sketcher::SketchObject", "OnRight")
        self.sketch.AttachmentSupport = [(self.xyPlane(), "")]
        self.sketch.MapMode = "FlatFace"
        self.doc.recompute()
        self.topEdge = edge_between(self.pad.Shape, (20, 0, 10), (20, 20, 10))
        self.sketch.addExternal(self.pad.Name, self.topEdge)
        circle = self.sketch.addGeometry(Part.Circle(V(20, 10, 0), V(0, 0, 1), 2), False)
        self.sketch.addConstraint(Sketcher.Constraint("PointOnObject", circle, 3, -3))
        self.sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, circle, 3, 10))
        self.sketch.addConstraint(Sketcher.Constraint("Radius", circle, 2))
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())

    def tearDown(self):
        if hasattr(self, "doc"):
            App.closeDocument(self.doc.Name)

    def xyPlane(self):
        return [f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]

    def replaceRightSide(self):
        self.profile.delGeometry(1)
        add_lines(self.profile, [(20, 0), (25, 10), (20, 20)])
        self.doc.recompute()
        # the edit did what it should: the pad reaches x = 25, and no edge is left at x = 20, z = 10
        self.assertAlmostEqual(self.pad.Shape.BoundBox.XMax, 25, delta=TOL)
        with self.assertRaises(AssertionError):
            edge_between(self.pad.Shape, (20, 0, 10), (20, 20, 10))

    def assertFrozenAtX20(self):
        lines = external_lines(self.sketch)
        self.assertEqual(len(lines), 1)
        start, end = lines[0]
        self.assertTrue(
            {(round(p.x, 6), round(p.y, 6), round(p.z, 6)) for p in (start, end)}
            == {(20, 0, 0), (20, 20, 0)},
            f"external line {start} - {end}, expected the frozen (20, 0, 0) - (20, 20, 0)",
        )
        self.assertTrue(self.sketch.Geometry[0].Center.isEqual(V(20, 10, 0), TOL))

    def testMissingReferenceFailsAndNamesIt(self):
        self.replaceRightSide()
        self.assertFalse(self.sketch.isValid())
        self.assertIn(
            f"Missing external geometry reference: Pad.{self.topEdge} (ExternalEdge1)",
            self.sketch.getStatusString(),
        )

    def testLinkAndFrozenGeometryKept(self):
        self.replaceRightSide()
        self.assertEqual(self.sketch.ExternalGeometry, [(self.pad, ("?" + self.topEdge,))])
        self.assertIn(self.sketch, self.pad.InList)  # still depends on the pad
        self.assertFrozenAtX20()

    def testStaysFailedOnTheNextRecompute(self):
        self.replaceRightSide()
        self.sketch.touch()
        self.doc.recompute()
        self.assertFalse(self.sketch.isValid())
        self.assertEqual(self.sketch.ExternalGeometry, [(self.pad, ("?" + self.topEdge,))])
        self.assertFrozenAtX20()

    def testAddingExternalGeometryKeepsTheMissingLink(self):
        """Adding another external edge rebuilds the external geometry outside a recompute: the
        missing link and its frozen geometry stay (it was erased there too)."""
        self.replaceRightSide()
        frontEdge = edge_between(self.pad.Shape, (0, 0, 10), (20, 0, 10))
        self.sketch.addExternal(self.pad.Name, frontEdge)
        self.assertEqual(
            self.sketch.ExternalGeometry,
            [(self.pad, ("?" + self.topEdge, frontEdge))],
        )
        self.doc.recompute()
        self.assertFalse(self.sketch.isValid())
        lines = external_lines(self.sketch)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1][0].isEqual(V(0, 0, 0), TOL) or lines[1][1].isEqual(V(0, 0, 0), TOL))
        self.assertAlmostEqual((lines[1][1] - lines[1][0]).Length, 20, delta=TOL)

    def testFaceLinkNamesEachGeometry(self):
        """A missing face projected onto a parallel plane named its four edges."""
        sketch = self.body.newObject("Sketcher::SketchObject", "OnSide")
        sketch.AttachmentSupport = [
            ([f for f in self.body.Origin.OriginFeatures if f.Role == "YZ_Plane"][0], "")
        ]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        face = face_at_x(self.pad.Shape, 20)
        sketch.addExternal(self.pad.Name, face)
        self.doc.recompute()
        self.assertTrue(sketch.isValid(), sketch.getStatusString())
        self.assertEqual(len(sketch.ExternalGeo), 6)

        self.replaceRightSide()
        self.assertFalse(sketch.isValid())
        self.assertIn(
            f"Pad.{face} (ExternalEdge1, ExternalEdge2, ExternalEdge3, ExternalEdge4)",
            sketch.getStatusString(),
        )
        self.assertEqual(sketch.ExternalGeometry, [(self.pad, ("?" + face,))])


class TestSketchMissingExternalSolver(TestSketchMissingExternal):
    """The same in a document with the reference solver on (ops#7). There the solver breaks
    the reference (its One policy) and the recompute check fails the sketch first, naming the
    candidates; the sketch must keep the broken link, as it does in other documents."""

    solver = True

    def testMissingReferenceFailsAndNamesIt(self):
        self.replaceRightSide()
        self.assertFalse(self.sketch.isValid())
        self.assertIn("ExternalGeometry[0]", self.sketch.getStatusString())

    def testFaceLinkNamesEachGeometry(self):
        self.skipTest("the solver's recompute check names the break, not the sketch")


class TestSketchMissingExternalReturns(unittest.TestCase):
    """The missing element comes back: Sketch2 projects the pocket's top edge at x = 20 (a pad
    20 x 20 x 10 with a 2 x 2 corner pocket at the origin). The pocket is widened to x 15..25,
    which takes the edge away, then put back, which brings it back under its old name. The link
    is pointed at the element again and the sketch is valid."""

    solver = False

    def setUp(self):
        if "BUILD_PART_DESIGN" not in App.__cmake__:
            self.skipTest("needs PartDesign")
        self.doc = App.newDocument("TestSketchMissingExternalReturns")
        if self.solver and not hasattr(self.doc, "ReferenceSolver"):
            self.skipTest("needs the reference solver")
        if hasattr(self.doc, "ReferenceSolver"):
            # Explicitly, also when off: new documents start with it on (ops#7 Q7).
            self.doc.ReferenceSolver = self.solver
        body = self.doc.addObject("PartDesign::Body", "Body")
        profile = body.newObject("Sketcher::SketchObject", "Profile")
        add_lines(profile, [(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)])
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = profile
        pad.Length = 10
        self.cut = body.newObject("Sketcher::SketchObject", "Cut")
        self.cut.Placement = App.Placement(V(0, 0, 10), App.Rotation())
        self.setCut([(-1, -1), (2, -1), (2, 2), (-1, 2), (-1, -1)])
        self.pocket = body.newObject("PartDesign::Pocket", "Pocket")
        self.pocket.Profile = self.cut
        self.pocket.Type = "ThroughAll"
        self.doc.recompute()
        self.assertTrue(self.pocket.isValid(), self.pocket.getStatusString())
        self.assertLess(self.pocket.Shape.Volume, 4000)
        self.sketch = body.newObject("Sketcher::SketchObject", "OnRight")
        self.doc.recompute()
        self.topEdge = edge_between(self.pocket.Shape, (20, 0, 10), (20, 20, 10))
        self.sketch.addExternal(self.pocket.Name, self.topEdge)
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())

    def tearDown(self):
        if hasattr(self, "doc"):
            App.closeDocument(self.doc.Name)

    def setCut(self, points):
        self.cut.deleteAllGeometry()
        add_lines(self.cut, points)

    def testElementBackRelinks(self):
        self.setCut([(15, -1), (25, -1), (25, 21), (15, 21), (15, -1)])
        self.doc.recompute()
        self.assertFalse(self.sketch.isValid())
        self.assertTrue(self.sketch.ExternalGeometry[0][1][0].startswith("?"))

        self.setCut([(-1, -1), (2, -1), (2, 2), (-1, 2), (-1, -1)])
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        name = edge_between(self.pocket.Shape, (20, 0, 10), (20, 20, 10))
        self.assertEqual(self.sketch.ExternalGeometry, [(self.pocket, (name,))])
        lines = external_lines(self.sketch)
        self.assertEqual(len(lines), 1)
        self.assertAlmostEqual(lines[0][0].x, 20, delta=TOL)
        self.assertAlmostEqual(lines[0][1].x, 20, delta=TOL)


class TestSketchMissingExternalReturnsSolver(TestSketchMissingExternalReturns):
    """The same with the reference solver on: the solver, not the sketch, resolves the returned
    element (exactly, by its old name)."""

    solver = True
