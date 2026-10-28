# SPDX-License-Identifier: LGPL-2.1-or-later

"""A sketch whose external geometry lost its element (ops#72).

The sketch fails, names the source and the missing element, and keeps the link in
`ExternalGeometry` (so it still depends on the source) and the frozen geometry (so it still
shows, and the constraints on it still solve). Before, it stayed valid on the frozen geometry and
dropped the link. Every model is designed geometry; results are judged geometrically."""

import math
import os
import unittest

import FreeCAD
import Part
import Sketcher

# Tests whose only purpose is files from upstream FreeCAD (V1 names) or from fork builds before the
# reference solver (the solver off) run only with FREECAD_OLD_FILE_TESTS set (PLAN decision 179)
OLD_FILE_TESTS = bool(os.environ.get("FREECAD_OLD_FILE_TESTS"))
OLD_FILE_SKIP = "a solver-off or V1 file only: FREECAD_OLD_FILE_TESTS=1 runs it (decision 179)"

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
    # Run without the solver also when FREECAD_OLD_FILE_TESTS isn't set: the solver's class skips them
    OFF_ONLY = ("testFaceLinkNamesEachGeometry",)

    def setUp(self):
        if "BUILD_PART_DESIGN" not in App.__cmake__:
            self.skipTest("needs PartDesign")
        if not self.solver and not OLD_FILE_TESTS and self._testMethodName not in self.OFF_ONLY:
            self.skipTest(OLD_FILE_SKIP)
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

    def addFrontEdge(self):
        """After the edit, another external edge, the pad's top front edge, which resolves."""
        self.replaceRightSide()
        frontEdge = edge_between(self.pad.Shape, (0, 0, 10), (20, 0, 10))
        self.sketch.addExternal(self.pad.Name, frontEdge)
        self.assertEqual(
            self.sketch.ExternalGeometry,
            [(self.pad, ("?" + self.topEdge, frontEdge))],
        )
        self.doc.recompute()

    def assertBothLinesKept(self):
        lines = external_lines(self.sketch)
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[1][0].isEqual(V(0, 0, 0), TOL) or lines[1][1].isEqual(V(0, 0, 0), TOL))
        self.assertAlmostEqual((lines[1][1] - lines[1][0]).Length, 20, delta=TOL)

    def testAddingExternalGeometryKeepsTheMissingLink(self):
        """Adding another external edge rebuilds the external geometry outside a recompute: the
        missing link and its frozen geometry stay (it was erased there too)."""
        self.addFrontEdge()
        self.assertFalse(self.sketch.isValid())
        self.assertBothLinesKept()

    def testDeletingAnotherSourceKeepsTheMissingLink(self):
        """A datum point at (0, 30, 0) gives a second link. After the edit, deleting the datum
        drops its link outside the sketch (PropertyLinkSubList::breakLink): the missing link
        keeps its shadow, so it still names the pad's top edge, with its frozen line and the
        three constraints of the circle (ops#140)."""
        datum = self.body.newObject("PartDesign::Point", "Datum")
        datum.Placement = App.Placement(V(0, 30, 0), App.Rotation())
        self.doc.recompute()
        self.sketch.addExternal(datum.Name, "")
        self.doc.recompute()
        self.replaceRightSide()
        self.doc.removeObject(datum.Name)
        self.assertEqual(self.sketch.ExternalGeometry, [(self.pad, ("?" + self.topEdge,))])
        self.sketch.touch()
        self.doc.recompute()
        self.assertEqual(self.sketch.ExternalGeometry, [(self.pad, ("?" + self.topEdge,))])
        lines = [g for g in list(self.sketch.ExternalGeo)[2:] if isinstance(g, Part.LineSegment)]
        self.assertEqual(len(lines), 1)
        self.assertEqual(
            {(round(p.x, 6), round(p.y, 6)) for p in (lines[0].StartPoint, lines[0].EndPoint)},
            {(20, 0), (20, 20)},
        )
        self.assertEqual(len(self.sketch.Constraints), 3)
        self.assertTrue(self.sketch.Geometry[0].Center.isEqual(V(20, 10, 0), TOL))

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

    def testAddingExternalGeometryKeepsTheMissingLink(self):
        """With the solver, one of the two links still resolving, the sketch computes with a
        warning naming the missing one (ops#127, Onshape's rule); the missing link and its
        frozen geometry stay."""
        self.addFrontEdge()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.assertIn("Warning", self.sketch.State)
        message = self.sketch.getStatusString()
        self.assertIn("ExternalGeometry[0]", message)
        self.assertTrue(message.endswith("computed on 1 of 2 edges"), message)
        self.assertBothLinesKept()


class TestSketchMissingExternalReturns(unittest.TestCase):
    """The missing element comes back: Sketch2 projects the pocket's top edge at x = 20 (a pad
    20 x 20 x 10 with a 2 x 2 corner pocket at the origin). The pocket is widened to x 15..25,
    which takes the edge away, then put back, which brings it back under its old name. The link
    is pointed at the element again and the sketch is valid."""

    solver = False
    OFF_ONLY = ()

    def setUp(self):
        if "BUILD_PART_DESIGN" not in App.__cmake__:
            self.skipTest("needs PartDesign")
        if not self.solver and not OLD_FILE_TESTS and self._testMethodName not in self.OFF_ONLY:
            self.skipTest(OLD_FILE_SKIP)
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


class TestSketchFaceLinkPairing(unittest.TestCase):
    """A link to a whole face gives one geometry per edge of the face. After an edit of its
    source, each one takes the Id of its predecessor that came from the same source edge (by
    the edge's name), else from the same place (by geometry), and by position only when the
    face resolved by history (ops#264 e2, class E's E1). Before, the k-th new geometry took the
    k-th old Id, so the constraints on it could move to another edge, silently.

    A 20 x 20 square padded 10 high (scaled by `scale`; its lines, kept by their geometry IDs:
    front y = 0, right x = 20, back y = 20, left x = 0); a sketch on the XY plane projects the
    pad's top face (four lines) and has a circle r 1 whose centre is on one of the projected
    lines (PointOnObject; nothing else holds it, so a constraint moved to another line moves the
    circle without a conflict). After each edit the circle must be on the line it was put on, or
    the sketch must fail, naming the projected line whose source is gone, its constraint kept on
    it (never on another line)."""

    solver = True
    scale = 1.0

    def setUp(self):
        if "BUILD_PART_DESIGN" not in App.__cmake__:
            self.skipTest("needs PartDesign")
        self.makeModel([(0, 0), (20, 0), (20, 20), (0, 20)])

    def makeModel(self, corners, holes=(), geometry=None):
        """The profile: a closed polygon through the corners and circles r 3 at the holes'
        centres (unscaled; the circles' geometry indexes follow the lines'), or the `geometry`
        given (scaled), padded 10 high; the sketch on top projects the pad's top face."""
        if hasattr(self, "doc"):
            App.closeDocument(self.doc.Name)
            del self.doc
        doc = App.newDocument("TestSketchFaceLinkPairing")
        if self.solver and not hasattr(doc, "ReferenceSolver"):
            App.closeDocument(doc.Name)
            self.skipTest("needs the reference solver")
        self.doc = doc
        if hasattr(self.doc, "ReferenceSolver"):
            # Explicitly, also when off: new documents start with it on (ops#7 Q7).
            self.doc.ReferenceSolver = self.solver
        s = self.scale
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.profile = self.body.newObject("Sketcher::SketchObject", "Profile")
        if geometry is None:
            self.addLines(corners + corners[:1])
        else:
            self.profile.addGeometry(geometry, False)
        for x, y in holes:
            self.profile.addGeometry(Part.Circle(V(x * s, y * s, 0), V(0, 0, 1), 3 * s), False)
        self.pad = self.body.newObject("PartDesign::Pad", "Pad")
        self.pad.Profile = self.profile
        self.pad.Length = 10 * s
        self.doc.recompute()
        self.sketch = self.body.newObject("Sketcher::SketchObject", "OnTop")
        self.sketch.AttachmentSupport = [
            ([f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane"][0], "")
        ]
        self.sketch.MapMode = "FlatFace"
        self.doc.recompute()
        self.sketch.addExternal(self.pad.Name, self.topFace())
        self.doc.recompute()
        if geometry is None:
            self.assertEqual(len(self.lines()), len(corners))
        self.assertEqual(len(self.circles()), len(holes))

    def tearDown(self):
        if hasattr(self, "doc"):
            App.closeDocument(self.doc.Name)

    def topFace(self):
        top = 10 * self.scale
        for i, face in enumerate(self.pad.Shape.Faces, 1):
            box = face.BoundBox
            if abs(box.ZMin - top) < TOL and abs(box.ZMax - top) < TOL:
                return f"Face{i}"
        raise AssertionError("no top face")

    def lines(self):
        """The projected lines: {geoId: (start, end)} in sketch coordinates."""
        return {
            -i - 1: (g.StartPoint, g.EndPoint)
            for i, g in enumerate(self.sketch.ExternalGeo)
            if i >= 2 and isinstance(g, Part.LineSegment)
        }

    def circles(self):
        """The projected circles: {geoId: centre} in sketch coordinates."""
        return {
            -i - 1: g.Center
            for i, g in enumerate(self.sketch.ExternalGeo)
            if i >= 2 and isinstance(g, Part.Circle)
        }

    @staticmethod
    def onLine(line, axis, value, span=None):
        """Whether the line (start, end) lies on x = value (axis "x") or y = value, spanning
        `span` (lo, hi) in the other coordinate if given."""
        if not all(abs(getattr(p, axis) - value) < TOL for p in line):
            return False
        if span is None:
            return True
        other = "y" if axis == "x" else "x"
        lo, hi = sorted(getattr(p, other) for p in line)
        return abs(lo - span[0]) < TOL and abs(hi - span[1]) < TOL

    def lineOn(self, axis, value, span=None):
        found = [g for g, line in self.lines().items() if self.onLine(line, axis, value, span)]
        self.assertEqual(len(found), 1, f"projected lines on {axis} = {value}: {self.lines()}")
        return found[0]

    def constrainCircle(self, axis, value, span=None, at=5):
        """The circle, its centre on the projected line at axis = value (spanning `span`), `at`
        along it (unscaled)."""
        s = self.scale
        geoId = self.lineOn(axis, value * s, span and (span[0] * s, span[1] * s))
        centre = V(value * s, at * s, 0) if axis == "x" else V(at * s, value * s, 0)
        self.circle = self.sketch.addGeometry(Part.Circle(centre, V(0, 0, 1), s), False)
        self.sketch.addConstraint(Sketcher.Constraint("PointOnObject", self.circle, 3, geoId))
        self.sketch.addConstraint(Sketcher.Constraint("Radius", self.circle, s))
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        self.oldLine = self.lines()[geoId]

    def constrainedGeoId(self):
        return [c for c in self.sketch.Constraints if c.Type == "PointOnObject"][0].Second

    def assertStaysOn(self, axis, value, span=None):
        """The sketch computes, its constraint is on the projected line at axis = value (spanning
        `span`), and so is the circle's centre."""
        value *= self.scale
        span = span and (span[0] * self.scale, span[1] * self.scale)
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        geoId = self.constrainedGeoId()
        self.assertIn(geoId, self.lines())
        self.assertTrue(
            self.onLine(self.lines()[geoId], axis, value, span),
            f"the constraint is on {self.lines()[geoId]}, not on {axis} = {value} {span}",
        )
        centre = self.sketch.Geometry[self.circle].Center
        self.assertAlmostEqual(getattr(centre, axis), value, delta=TOL)

    def assertBreaks(self):
        """The sketch fails naming the projected line that lost its source edge; the constraint
        stays on that line, at its old place and flagged missing: never on another line."""
        self.assertFalse(self.sketch.isValid())
        message = self.sketch.getStatusString()
        geoId = self.constrainedGeoId()
        self.assertIn(f"ExternalEdge{-geoId - 2}", message)
        self.assertIn("no longer gives", message)
        self.assertNotIn("fewer geometries", message)
        line = self.lines()[geoId]
        self.assertTrue(
            all((p - q).Length < TOL for p, q in zip(line, self.oldLine)),
            f"the constraint's line moved: {self.oldLine} -> {line}",
        )
        facade = Sketcher.ExternalGeometryFacade(self.sketch.ExternalGeo[-geoId - 1])
        self.assertTrue(facade.testFlag("Missing"))

    def setLines(self, lines):
        """Moves the profile's lines {index: ((x0, y0), (x1, y1))} (unscaled), keeping their
        geometry IDs, as a re-dimension does."""
        s = self.scale
        geometry = self.profile.Geometry
        for index, (a, b) in lines.items():
            geometry[index] = Part.LineSegment(V(a[0] * s, a[1] * s, 0), V(b[0] * s, b[1] * s, 0))
        self.profile.Geometry = geometry

    def addLines(self, points):
        s = self.scale
        add_lines(self.profile, [(x * s, y * s) for x, y in points])

    def redraw(self, points):
        """The profile's lines deleted and a closed polygon through the points drawn instead."""
        self.profile.delGeometries(list(range(len(self.profile.Geometry))))
        self.addLines(points + points[:1])

    def cutCorner(self):
        """A 5 x 5 corner cut at (20, 20): the right line ends at (20, 15), the back line starts
        at (15, 20), and a new line joins them. The top face's edges, in its order: front,
        right, the cut, back, left."""
        self.setLines({1: ((20, 0), (20, 15)), 2: ((15, 20), (0, 20))})
        self.addLines([(20, 15), (15, 20)])
        self.doc.recompute()
        self.assertEqual(len(self.lines()), 5)

    def testCornerCutBeforeTheConstrainedEdge(self):
        """The prototype's case (row 149): the circle on the left edge moved to the back edge,
        (0, 5) -> (0, 20), the sketch valid and no warning."""
        self.constrainCircle("x", 0)
        self.cutCorner()
        self.assertStaysOn("x", 0)
        centre = self.sketch.Geometry[self.circle].Center
        self.assertTrue(centre.isEqual(V(0, 5 * self.scale, 0), TOL), centre)

    def testCornerCutAfterTheConstrainedEdge(self):
        """The baseline: the front edge comes before the cut, so it kept its Id before too."""
        self.constrainCircle("y", 0)
        self.cutCorner()
        self.assertStaysOn("y", 0)

    def testCornerCutKeepsEachLinesFlags(self):
        """Row N1: the flags go with the Id, so they follow the pairing. The left line alone is
        made defining (toggleConstruction): after the cut it still is, and the back line isn't."""
        self.constrainCircle("x", 0)
        self.sketch.toggleConstruction(self.lineOn("x", 0))
        self.doc.recompute()

        def defining(geoId):
            return Sketcher.ExternalGeometryFacade(
                self.sketch.ExternalGeo[-geoId - 1]
            ).testFlag("Defining")

        self.assertTrue(defining(self.lineOn("x", 0)))
        self.cutCorner()
        self.assertTrue(defining(self.lineOn("x", 0)))
        self.assertFalse(defining(self.lineOn("y", 20 * self.scale)))

    def testCornerCutKeepsTheIdsOrderedAsBuilt(self):
        """The cut's line goes between the right and back lines in ExternalGeo, as the face gives
        it: the next rebuild compares positions in that order."""
        self.constrainCircle("x", 0)
        self.cutCorner()
        order = [line for _, line in sorted(self.lines().items(), reverse=True)]
        diagonal = [
            k for k, (a, b) in enumerate(order) if abs(a.x - b.x) > TOL and abs(a.y - b.y) > TOL
        ]
        self.assertEqual(len(diagonal), 1)
        right = [k for k, line in enumerate(order) if self.onLine(line, "x", 20 * self.scale)]
        back = [k for k, line in enumerate(order) if self.onLine(line, "y", 20 * self.scale)]
        self.assertEqual(diagonal[0], right[0] + 1)
        self.assertEqual(back[0], diagonal[0] + 1)
        self.assertStaysOn("x", 0)

    def testCornerCutStaysThroughRecomputes(self):
        self.constrainCircle("x", 0)
        self.cutCorner()
        self.sketch.touch()
        self.doc.recompute()
        self.assertStaysOn("x", 0)

    def testConstrainedEdgeRemoved(self):
        """Row 149': the right side replaced by a V, (20, 0)-(25, 10)-(20, 20): the projected
        line at x = 20 has no counterpart. Its constraint must not move to another line."""
        self.constrainCircle("x", 20)
        self.profile.delGeometry(1)
        self.addLines([(20, 0), (25, 10), (20, 20)])
        self.doc.recompute()
        self.assertBreaks()

    def testDimensionEdit(self):
        """Row 149'', review case a: the right side moves to x = 25, its lines keeping their IDs
        (the front, right and back edges get new names). The face resolves by history."""
        self.constrainCircle("x", 0)
        self.setLines({0: ((0, 0), (25, 0)), 1: ((25, 0), (25, 20)), 2: ((25, 20), (0, 20))})
        self.doc.recompute()
        self.assertStaysOn("x", 0)

    def testDimensionEditMovesTheConstrainedEdge(self):
        """The same, the circle on the right edge, which moves: its name and line both change,
        so only its position pairs it (the face resolved by history: the dimension edit's case
        that `Exact` alone would break)."""
        self.constrainCircle("x", 20)
        self.setLines({0: ((0, 0), (25, 0)), 1: ((25, 0), (25, 20)), 2: ((25, 20), (0, 20))})
        self.doc.recompute()
        self.assertStaysOn("x", 25)

    def testRedrawSameSquare(self):
        """Review case c (row 149''''): the same square redrawn from another corner. Every edge
        gets a new name and the order turns; geometry pairs all four."""
        self.constrainCircle("x", 0)
        self.redraw([(20, 20), (20, 0), (0, 0), (0, 20)])
        self.doc.recompute()
        self.assertStaysOn("x", 0)

    def testRedrawResized(self):
        """Review case b: a 25 x 20 rectangle redrawn from (25, 20), the other way round. The
        solver finds no top face for the reference (a candidate 2.5 mm off), so the sketch
        fails on the face, as before; its geometry and the constraint stay as they were. (The
        class note predicted `correct` from the probe's pairing of the old geometry with
        itself: the pairing never runs, the face being gone.)"""
        self.constrainCircle("x", 0)
        self.redraw([(25, 20), (25, 0), (0, 0), (0, 20)])
        self.doc.recompute()
        self.assertFalse(self.sketch.isValid())
        self.assertIn("ExternalGeometry[0]", self.sketch.getStatusString())
        geoId = self.constrainedGeoId()
        self.assertTrue(self.onLine(self.lines()[geoId], "x", 0))

    def testNotchBeforeTheConstrainedEdge(self):
        """Review case d (row 149v): a notch 4 wide and 3 deep in the back edge, the old lines
        keeping their IDs: four more edges before the left one, which keeps its name."""
        self.constrainCircle("x", 0)
        self.setLines({2: ((20, 20), (12, 20))})
        self.addLines([(12, 20), (12, 17), (8, 17), (8, 20), (0, 20)])
        self.doc.recompute()
        self.assertEqual(len(self.lines()), 8)
        self.assertStaysOn("x", 0)

    def redrawCentred(self):
        """Review cases f and g (row 149'''): a 24 x 24 square redrawn centred on the old one,
        from another corner: every edge's name and line change, the count and types don't, and
        the face is found by its place (a tier 3 guess), so its edge order is no evidence."""
        self.redraw([(-2, 22), (22, 22), (22, -2), (-2, -2)])
        self.doc.recompute()

    def testRedrawCentredBreaksTheLeftEdge(self):
        """Case f: right before by luck (positional), broken now: the accepted cost."""
        self.constrainCircle("x", 0)
        self.redrawCentred()
        self.assertBreaks()

    def testRedrawCentredBreaksTheFrontEdge(self):
        """Case g: the circle on the front edge moved to the back one, (0, 0) -> (0, 22), with
        only the face's own warning."""
        self.constrainCircle("y", 0)
        self.redrawCentred()
        self.assertBreaks()

    def testSourceNamesTheEdge(self):
        """Each projected line records its source edge's mapped name, and the names are the
        face's edges'."""
        names = set()
        for i, geo in enumerate(self.sketch.ExternalGeo):
            if i < 2:
                continue
            source = Sketcher.ExternalGeometryFacade(geo).Source
            self.assertTrue(source)
            names.add(source)
        self.assertEqual(len(names), 4)
        top = self.pad.Shape.getElement(self.topFace())
        edges = {
            self.pad.Shape.getElementMappedName(f"Edge{i}")
            for i, e in enumerate(self.pad.Shape.Edges, 1)
            if any(e.isSame(f) for f in top.Edges)
        }
        self.assertEqual(names, edges)

    # Round 4 (the class note's ruling of 2026-10-27): the source name, the place and (for
    # geometry without a source name) the position are votes, and the face's loops arbitrate
    # between the pairs already settled.

    Z_PROFILE = [(0, 0), (10, 0), (10, 5), (20, 5), (20, 10), (0, 10)]
    """Front (0, 0)-(10, 0), the step wall x = 10 (0..5), the step y = 5 (10..20), the right line
    x = 20 (5..10), the back line y = 10, the left line x = 0: lines 0 to 5."""

    def moveLines(self, lines):
        """Moves the end points of the profile's lines {index: ((x0, y0), (x1, y1))} (unscaled)
        in place, so they keep their geometry IDs (a line may turn round)."""
        s = self.scale
        geometry = self.profile.Geometry
        for index, (a, b) in lines.items():
            line = geometry[index]
            line.StartPoint = V(-777 * s, -777 * s, 0)  # away from both ends first
            line.EndPoint = V(b[0] * s, b[1] * s, 0)
            line.StartPoint = V(a[0] * s, a[1] * s, 0)
        self.profile.Geometry = geometry

    def stepTurned(self):
        """The Z profile's step goes down instead of up (the wall x = 10 runs 0..-5, the step is
        at y = -5), a dimension edit."""
        self.moveLines({1: ((10, 0), (10, -5)), 2: ((10, -5), (20, -5)), 3: ((20, -5), (20, 10))})

    def stepTurnedMovedByWidth(self):
        """The Z profile moved 20 to the right and its step turned, in one recompute: the left
        line (x = 20) lies on the old right line's place."""
        self.moveLines(
            {
                0: ((20, 0), (30, 0)),
                1: ((30, 0), (30, -5)),
                2: ((30, -5), (40, -5)),
                3: ((40, -5), (40, 10)),
                4: ((40, 10), (20, 10)),
                5: ((20, 10), (20, 0)),
            }
        )

    def cutFrontLeft(self):
        """The square's front-left corner cut 5 x 5 (a line (0, 5)-(5, 0) appended)."""
        self.moveLines({0: ((5, 0), (20, 0)), 3: ((0, 20), (0, 5))})
        self.addLines([(0, 5), (5, 0)])

    def cutBackRight(self):
        """The square's back-right corner cut 5 x 5 (a line (20, 15)-(15, 20) appended)."""
        self.moveLines({1: ((20, 0), (20, 15)), 2: ((15, 20), (0, 20))})
        self.addLines([(20, 15), (15, 20)])

    def testStepTurnedMovedByWidth(self):
        """Round 3's silent find: the circle on the right line x = 20 (5..10) went to the left
        line, which slid onto its place. The right line keeps its name; the slide is outside the
        arc between the anchors. Right: x = 40 (-5..10)."""
        self.makeModel(self.Z_PROFILE)
        self.constrainCircle("x", 20, (5, 10), 7.5)
        self.stepTurnedMovedByWidth()
        self.doc.recompute()
        self.assertStaysOn("x", 40, (-5, 10))

    def testStepTurnedMovedByWidthWall(self):
        """The same edit, the circle on the step wall x = 10 (0..5): the wall x = 30 (-5..0)."""
        self.makeModel(self.Z_PROFILE)
        self.constrainCircle("x", 10, (0, 5), 2.5)
        self.stepTurnedMovedByWidth()
        self.doc.recompute()
        self.assertStaysOn("x", 30, (-5, 0))

    def testStepTurned(self):
        """Round 3: the step turned alone, the circle on the step y = 5 (10..20). Loud on round
        3's head (the turned wall failed the ends check); the step keeps its name: y = -5."""
        self.makeModel(self.Z_PROFILE)
        self.constrainCircle("y", 5, (10, 20), 15)
        self.stepTurned()
        self.doc.recompute()
        self.assertStaysOn("y", -5, (10, 20))

    def testStepTurnedWall(self):
        """Round 3's control: the same edit, the circle on the wall: x = 10 (-5..0)."""
        self.makeModel(self.Z_PROFILE)
        self.constrainCircle("x", 10, (0, 5), 2.5)
        self.stepTurned()
        self.doc.recompute()
        self.assertStaysOn("x", 10, (-5, 0))

    def testCornerCutMovedByWidth(self):
        """Round 3's silent find: the square moved 20 to the right and its front-left corner cut;
        the left line (x = 20, 5..20) lies on the old right line's place. Right: x = 40."""
        self.constrainCircle("x", 20)
        self.moveLines(
            {
                0: ((25, 0), (40, 0)),
                1: ((40, 0), (40, 20)),
                2: ((40, 20), (20, 20)),
                3: ((20, 20), (20, 5)),
            }
        )
        self.addLines([(20, 5), (25, 0)])
        self.doc.recompute()
        self.assertStaysOn("x", 40, (0, 20))

    def testCornerCutMovedByWidthBackRight(self):
        """Round 3's silent find, the cut at the back-right corner: x = 40 (0..15)."""
        self.constrainCircle("x", 20)
        self.moveLines(
            {
                0: ((20, 0), (40, 0)),
                1: ((40, 0), (40, 15)),
                2: ((35, 20), (20, 20)),
                3: ((20, 20), (20, 0)),
            }
        )
        self.addLines([(40, 15), (35, 20)])
        self.doc.recompute()
        self.assertStaysOn("x", 40, (0, 15))

    def testCornerCutWidened(self):
        """Round 3: the square widened to 30 and its front-left corner cut. Loud on round 3's head
        (neither place nor position paired the moved right line); its name pairs it: x = 30."""
        self.constrainCircle("x", 20)
        self.moveLines(
            {
                0: ((5, 0), (30, 0)),
                1: ((30, 0), (30, 20)),
                2: ((30, 20), (0, 20)),
                3: ((0, 20), (0, 5)),
            }
        )
        self.addLines([(0, 5), (5, 0)])
        self.doc.recompute()
        self.assertStaysOn("x", 30, (0, 20))

    def preparePath(self, path):
        """The profile made movable by `path`: its Placement as it is ("placement"), attached to
        the XY plane ("attachment", its AttachmentOffset then moves it) or attached to a datum
        plane on the XY plane ("support", the plane then moves it)."""
        xy = [f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
        if path == "attachment":
            placement = self.profile.Placement
            self.profile.AttachmentSupport = [(xy, "")]
            self.profile.MapMode = "FlatFace"
            self.profile.AttachmentOffset = placement
        elif path == "support":
            plane = self.doc.addObject("PartDesign::Plane", "Support")
            self.body.insertObject(plane, self.profile, False)
            plane.AttachmentSupport = [(xy, "")]
            plane.MapMode = "FlatFace"
            plane.AttachmentOffset = self.profile.Placement
            self.profile.AttachmentSupport = [(plane, "")]
            self.profile.MapMode = "FlatFace"
            self.profile.AttachmentOffset = App.Placement()
            self.support = plane
        self.doc.recompute()

    def moveProfile(self, path, dx):
        """The profile moved dx (unscaled) along x through `path` (preparePath)."""
        owner, name = {
            "placement": (self.profile, "Placement"),
            "attachment": (self.profile, "AttachmentOffset"),
            "support": (getattr(self, "support", None), "AttachmentOffset"),
        }[path]
        placement = getattr(owner, name)
        placement.Base += V(dx * self.scale, 0, 0)
        setattr(owner, name, placement)

    def assertComposedEditThrough(self, path, edit, axis, value, span):
        """Round 3's composed edits with the move of 20 made by the sketch's Placement, its
        AttachmentOffset or its support instead of its geometry (the attack set's paths, ops#519):
        the Ids, and so the names, are untouched, and the loops are read from the projection."""
        self.preparePath(path)
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        edit()
        self.moveProfile(path, 20)
        self.doc.recompute()
        self.assertStaysOn(axis, value, span)

    def testCornerCutMovedByPlacement(self):
        self.constrainCircle("x", 20)
        self.assertComposedEditThrough("placement", self.cutFrontLeft, "x", 40, (0, 20))

    def testCornerCutMovedByAttachmentOffset(self):
        self.constrainCircle("x", 20)
        self.assertComposedEditThrough("attachment", self.cutFrontLeft, "x", 40, (0, 20))

    def testCornerCutMovedBySupport(self):
        self.constrainCircle("x", 20)
        self.assertComposedEditThrough("support", self.cutFrontLeft, "x", 40, (0, 20))

    def testCornerCutBackRightMovedByPlacement(self):
        self.constrainCircle("x", 20)
        self.assertComposedEditThrough("placement", self.cutBackRight, "x", 40, (0, 15))

    def testCornerCutBackRightMovedByAttachmentOffset(self):
        self.constrainCircle("x", 20)
        self.assertComposedEditThrough("attachment", self.cutBackRight, "x", 40, (0, 15))

    def testCornerCutBackRightMovedBySupport(self):
        self.constrainCircle("x", 20)
        self.assertComposedEditThrough("support", self.cutBackRight, "x", 40, (0, 15))

    def testStepTurnedMovedByPlacement(self):
        self.makeModel(self.Z_PROFILE)
        self.constrainCircle("x", 20, (5, 10), 7.5)
        self.assertComposedEditThrough("placement", self.stepTurned, "x", 40, (-5, 10))

    def testStepTurnedMovedByAttachmentOffset(self):
        self.makeModel(self.Z_PROFILE)
        self.constrainCircle("x", 20, (5, 10), 7.5)
        self.assertComposedEditThrough("attachment", self.stepTurned, "x", 40, (-5, 10))

    def testStepTurnedMovedBySupport(self):
        self.makeModel(self.Z_PROFILE)
        self.constrainCircle("x", 20, (5, 10), 7.5)
        self.assertComposedEditThrough("support", self.stepTurned, "x", 40, (-5, 10))

    def constrainPointOnHole(self, x, y):
        """A point Coincident with the centre of the projected hole at (x, y) (unscaled)."""
        s = self.scale
        hole = [g for g, c in self.circles().items() if c.isEqual(V(x * s, y * s, 0), TOL)]
        self.assertEqual(len(hole), 1, self.circles())
        self.point = self.sketch.addGeometry(Part.Point(V(x * s, y * s, 0)), False)
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", self.point, 1, hole[0], 3))
        self.doc.recompute()
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())

    def assertPointOnHole(self, x, y):
        s = self.scale
        self.assertTrue(self.sketch.isValid(), self.sketch.getStatusString())
        constraint = [c for c in self.sketch.Constraints if c.Type == "Coincident"][0]
        centre = self.circles()[constraint.Second]
        self.assertTrue(centre.isEqual(V(x * s, y * s, 0), TOL), f"on the hole at {centre}")
        point = self.sketch.Geometry[self.point]
        self.assertTrue(V(point.X, point.Y, 0).isEqual(V(x * s, y * s, 0), TOL), point)

    def holeRowMovedByPitch(self):
        """A 40 x 20 plate's holes r 3 at (10, 10) and (20, 10) moved +10, keeping their IDs: the
        left hole lands on the right hole's old place."""
        s = self.scale
        geometry = self.profile.Geometry
        geometry[4].Center = V(20 * s, 10 * s, 0)
        geometry[5].Center = V(30 * s, 10 * s, 0)
        self.profile.Geometry = geometry

    def testHoleRowMovedByPitch(self):
        """The cloud review's model A: the point follows its hole to (30, 10)."""
        self.makeModel([(0, 0), (40, 0), (40, 20), (0, 20)], holes=[(10, 10), (20, 10)])
        self.constrainPointOnHole(20, 10)
        self.holeRowMovedByPitch()
        self.doc.recompute()
        self.assertPointOnHole(30, 10)

    def testHoleRowMovedByPitchCornerCut(self):
        """The cloud review's leftover risk: the row moved by its pitch and a corner cut in the
        same edit (the count changes, so position says nothing). Silent on round 3's head and on
        integration; a hole's name outranks its look-alike's place: (30, 10)."""
        self.makeModel([(0, 0), (40, 0), (40, 20), (0, 20)], holes=[(10, 10), (20, 10)])
        self.constrainPointOnHole(20, 10)
        self.holeRowMovedByPitch()
        self.moveLines({1: ((40, 0), (40, 15)), 2: ((35, 20), (0, 20))})
        self.addLines([(40, 15), (35, 20)])
        self.doc.recompute()
        self.assertPointOnHole(30, 10)

    def testFirstLineRedrawnInPlace(self):
        """The front line deleted and drawn again in place (its ID comes back by the point
        clusters), so the face's wire may start from another edge. Silent on integration (a new
        find); the circle on the left line stays at x = 0."""
        self.constrainCircle("x", 0)
        self.profile.delGeometry(0)
        self.addLines([(0, 0), (20, 0)])
        self.doc.recompute()
        self.assertStaysOn("x", 0)

    def testVerticalFlipSidesRedrawnBreaks(self):
        """The front and back lines kept but swapped and reversed, the sides deleted and drawn
        again in place: the new right line takes the left line's ID. Nothing is where it wasn't
        and every signal is contested, so nothing settles the left line: loud."""
        self.constrainCircle("x", 0)
        self.profile.delGeometries([1, 3])  # 0: front, 1: back
        self.moveLines({0: ((20, 20), (0, 20)), 1: ((0, 0), (20, 0))})
        self.addLines([(20, 0), (20, 20)])
        self.addLines([(0, 20), (0, 0)])
        self.doc.recompute()
        self.assertBreaks()

    def testRedrawSidesNeighboursReversedMovedOutBreaks(self):
        """Round 1's reissue with the front and back lines also moved off their lines (y = -3 and
        23): nothing is at its old place, and the new right line takes the deleted left line's
        ID. The names alone put the loop's edges in an order it doesn't have: loud."""
        self.constrainCircle("x", 20)
        self.profile.delGeometries([1, 3])
        self.moveLines({0: ((25, -3), (-5, -3)), 1: ((-5, 23), (25, 23))})
        self.addLines([(25, -3), (25, 23)])
        self.addLines([(-5, 23), (-5, -3)])
        self.doc.recompute()
        self.assertBreaks()

    def testRedrawnAcrossTheFaceBreaks(self):
        """Review pr384-r4s: the square moved 20 left and 1 up, its front line kept and the others
        deleted and drawn again, the back line first: the new right line (x = 0) takes the deleted
        left line's ID, and so its name, and lies on the left line's old place facing the other
        way. The left line's arc around the front line empties while the other fills: loud, never
        the new right line."""
        self.constrainCircle("x", 0)
        self.profile.delGeometries([1, 2, 3])
        self.moveLines({0: ((0, 1), (-20, 1))})
        self.addLines([(0, 21), (-20, 21)])
        self.addLines([(0, 1), (0, 21)])
        self.addLines([(-20, 21), (-20, 1)])
        self.doc.recompute()
        self.assertBreaks()

    def redrawLeftThenCut(self, flip):
        """Review pr384-r4vs: the square moved (20, 5), the front, right and back lines kept (the
        right and back ones turned round if `flip`), the left line deleted and drawn again, then
        the front-left corner cut by a line drawn last, from the front line to the left one. The
        Sketcher gives the cut line the deleted left line's ID, and so its name; the arc between
        the back and front lines gains a line. The left line's name alone settles nothing: it
        breaks (PLAN decision 167), never the cut line (silent before, right on integration by
        position)."""
        self.constrainCircle("x", 0)
        self.profile.delGeometries([3])
        self.moveLines(
            {
                0: ((23, 5), (40, 5)),
                1: ((40, 25), (40, 5)) if flip else ((40, 5), (40, 25)),
                2: ((20, 25), (40, 25)) if flip else ((40, 25), (20, 25)),
            }
        )
        self.addLines([(20, 25), (20, 8)])
        self.addLines([(23, 5), (20, 8)])
        self.doc.recompute()
        self.assertBreaks()

    def testLeftRedrawnThenCutBreaks(self):
        self.redrawLeftThenCut(True)

    def testLeftRedrawnThenCutNoFlipBreaks(self):
        self.redrawLeftThenCut(False)

    def testMovedWithAnAngleEditAndACutBreaks(self):
        """PLAN decision 167: the square moved 20 to the right, its right line slanted (its top
        end to (35, 20)) and the front-right corner cut. The right line keeps only its name, its
        arc gains the cut, and it isn't its old line moved with the others: loud, never a
        guess."""
        self.constrainCircle("x", 20)
        self.moveLines(
            {
                0: ((20, 0), (35, 0)),
                1: ((40, 5), (35, 20)),
                2: ((35, 20), (20, 20)),
                3: ((20, 20), (20, 0)),
            }
        )
        self.addLines([(35, 0), (40, 5)])
        self.doc.recompute()
        self.assertBreaks()

    def testMovedWithOnlyParallelNamesBreaks(self):
        """PLAN decision 167: a stadium (the left line x = 0 and the right line x = 20, 0..20,
        joined by arcs r 10 below and above) moved 30 to the right, every geometry keeping its
        ID, the right line shortened to (50, 9)-(50, 20) and new lines below it with a notch:
        (50, 0)-(50, 5)-(48, 7)-(50, 9). The only lines with names are parallel, so the move
        isn't fixed (arcs don't fix it), and the right line, whose arc gains the new lines,
        breaks."""
        s = self.scale

        def arc(cx, cy, a0, a1):
            return Part.ArcOfCircle(Part.Circle(V(cx * s, cy * s, 0), V(0, 0, 1), 10 * s), a0, a1)

        self.makeModel(
            [],
            geometry=[
                Part.LineSegment(V(0, 20 * s, 0), V(0, 0, 0)),
                arc(10, 0, math.pi, 2 * math.pi),
                Part.LineSegment(V(20 * s, 0, 0), V(20 * s, 20 * s, 0)),
                arc(10, 20, 0, math.pi),
            ],
        )
        self.constrainCircle("x", 20)
        geometry = self.profile.Geometry
        geometry[1].Center = V(40 * s, 0, 0)
        geometry[3].Center = V(40 * s, 20 * s, 0)
        self.profile.Geometry = geometry
        self.moveLines({0: ((30, 20), (30, 0)), 2: ((50, 9), (50, 20))})
        self.addLines([(50, 0), (50, 5), (48, 7), (50, 9)])
        self.doc.recompute()
        self.assertBreaks()

    def cutCornerMoved(self, side, lines):
        """The square with its corner at (20, 20) cut (line 2), the circle on the side x = side;
        the profile's lines then moved to `lines`, keeping their IDs."""
        self.makeModel([(0, 0), (20, 0), (20, 15), (15, 20), (0, 20)])
        self.constrainCircle("x", side)
        self.moveLines(lines)
        self.doc.recompute()
        self.assertEqual(len(self.lines()), 5)

    def testCornerCutMovedToTheOppositeCorner(self):
        """Review pr384-r4v (T1): the cut moved from (20, 20) to (0, 0), every line keeping its ID.
        The sides keep their names and places while the cut's arc empties and another fills: no
        swap, and the circle stays on the left side."""
        self.cutCornerMoved(
            0,
            {
                0: ((5, 0), (20, 0)),
                1: ((20, 0), (20, 20)),
                2: ((0, 5), (5, 0)),
                3: ((20, 20), (0, 20)),
                4: ((0, 20), (0, 5)),
            },
        )
        self.assertStaysOn("x", 0)

    def testCornerCutMovedToTheOppositeCornerRight(self):
        """The same with the circle on the right side, x = 20 (right on integration)."""
        self.cutCornerMoved(
            20,
            {
                0: ((5, 0), (20, 0)),
                1: ((20, 0), (20, 20)),
                2: ((0, 5), (5, 0)),
                3: ((20, 20), (0, 20)),
                4: ((0, 20), (0, 5)),
            },
        )
        self.assertStaysOn("x", 20)

    def testCornerCutMovedToTheNextCorner(self):
        """Review pr384-r4v (T1): the cut slid from (20, 20) to (20, 0), the circle on the left
        side (right on integration)."""
        self.cutCornerMoved(
            0,
            {
                0: ((0, 0), (15, 0)),
                1: ((20, 5), (20, 20)),
                2: ((15, 0), (20, 5)),
                3: ((20, 20), (0, 20)),
                4: ((0, 20), (0, 0)),
            },
        )
        self.assertStaysOn("x", 0)

    def testUnmappedSlotClosedFloor(self):
        """Review pr384-r4v (T2): a Part::Feature's planar face without names, a 30 x 30 U whose
        slot (10..20, from y = 10 to the back) gets its mouth closed: the square with a 10 x 15
        hole. The slot's floor y = 10 keeps its place and the face's side, but moves from the
        outer loop to the hole's, which runs the other way round the face: the circle on it
        stays (right on integration)."""
        s = self.scale

        def wire(points):
            return Part.makePolygon([V(x * s, y * s, 10 * s) for x, y in points + points[:1]])

        plate = self.doc.addObject("Part::Feature", "Plate")
        plate.Shape = Part.Face(
            wire([(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10), (10, 30), (0, 30)])
        )
        self.doc.recompute()
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "OnPlate")
        self.sketch.addExternal(plate.Name, "Face1")
        self.doc.recompute()
        self.assertEqual(len(self.lines()), 8)
        self.constrainCircle("y", 10, (10, 20), at=15)
        plate.Shape = Part.makeFace(
            [
                wire([(0, 0), (30, 0), (30, 30), (0, 30)]),
                wire([(10, 10), (20, 10), (20, 25), (10, 25)]),
            ],
            "Part::FaceMakerBullseye",
        )
        self.doc.recompute()
        self.assertEqual(len(self.lines()), 8)
        self.assertStaysOn("y", 10, (10, 20))

    def slotClosed(self, axis, value, at):
        """The pad's profile a 30 x 30 U, its slot (10..20) from y = 10 to the back, the circle on
        the projected line at axis = value; then the profile's lines moved, keeping their IDs, to
        the square with a 10 x 15 hole (10..20 x 10..25): the top face's one loop splits in two."""
        self.makeModel([(0, 0), (30, 0), (30, 30), (20, 30), (20, 10), (10, 10), (10, 30), (0, 30)])
        self.constrainCircle(axis, value, at=at)
        self.moveLines(
            {
                2: ((30, 30), (0, 30)),
                3: ((20, 25), (20, 10)),
                5: ((10, 10), (10, 25)),
                6: ((10, 25), (20, 25)),
            }
        )
        self.doc.recompute()
        self.assertEqual(len(self.lines()), 8)

    def testSlotClosedKeepsTheWall(self):
        """Review pr384-r4v: the slot's right wall (x = 20) becomes the hole's right line; the
        circle stays on it (silent on integration, which gives the wall's ID to the left side)."""
        self.slotClosed("x", 20, 20)
        self.assertStaysOn("x", 20, (10, 25))

    def testSlotClosedKeepsTheOuterSide(self):
        """The same with the circle on the left side (x = 0), on the outer loop throughout."""
        self.slotClosed("x", 0, 5)
        self.assertStaysOn("x", 0, (0, 30))

    def testMirroredKeepsTheSide(self):
        """The square mirrored about x = 10, its lines keeping their IDs: the right line's ID is
        now at x = 0 and the left line's at x = 20. Two edges on each other's old places; the
        face's structure (the front and back lines in place) puts the constraint on the side it
        was on, x = 20, where integration followed the ID across the face (the ruling's R7
        reading: a user who meant the line's ID re-picks)."""
        self.constrainCircle("x", 20)
        self.moveLines(
            {
                0: ((20, 0), (0, 0)),
                1: ((0, 0), (0, 20)),
                2: ((0, 20), (20, 20)),
                3: ((20, 20), (20, 0)),
            }
        )
        self.doc.recompute()
        self.assertStaysOn("x", 20)

    def testProfileReversed(self):
        """The attack set's find (ops#519): the square's four lines drawn from their other ends,
        IDs kept. Silent on integration (the reversed wire lists the edges in another order)."""
        self.constrainCircle("x", 20)
        self.moveLines(
            {
                0: ((20, 0), (0, 0)),
                1: ((20, 20), (20, 0)),
                2: ((0, 20), (20, 20)),
                3: ((0, 0), (0, 20)),
            }
        )
        self.doc.recompute()
        self.assertStaysOn("x", 20)


class TestSketchFaceLinkPairingNoSolver(TestSketchFaceLinkPairing):
    """The same without the reference solver: no report entry, so the face counts as resolved
    by history. The redraws lose the face (its name is gone), which fails the sketch as a
    missing reference."""

    solver = False

    def testRedrawSameSquare(self):
        self.skipTest("without the solver the redrawn face is missing")

    def testRedrawResized(self):
        self.skipTest("without the solver the redrawn face is missing")

    def testRedrawCentredBreaksTheLeftEdge(self):
        self.skipTest("without the solver the redrawn face is missing")

    def testRedrawCentredBreaksTheFrontEdge(self):
        self.skipTest("without the solver the redrawn face is missing")


class TestSketchFaceLinkPairing4m(TestSketchFaceLinkPairing):
    """Review case e: the same at 200 times the size, a 4 m square (row 149'')."""

    scale = 200.0
