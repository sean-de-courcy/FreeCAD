# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Onshape's Extend and what bounds a Trim (ops#640, oracle 10b GA3-25/25b, sketch tools 1 extra 2). A line's end
# grows towards the click but stops at the first curve in its way: a sketch curve (construction
# lines included), a sketch point, the end point of a collinear line, or a Use'd (external) edge.
# The origin axes, a constraint's implicit model pick, and another curve's extension are not in the
# way. Stored: the end on the boundary curve (PointOnObject), or on the boundary point (Coincident);
# nothing when the end reaches the click in open space. sketch.extend(geo, increment, pos, True).
#
# The models are designed: line A (0,0)-(10,0) on the XY plane, extended at its end along +x
# (or at its start along -x), with boundaries placed at known x. The expectations are geometric.

import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector
TOL = 1e-7
NONE, START, END = 0, 1, 2  # PointPos


class TestSketchExtend(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestSketchExtend")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.a = self.addLine(0, 0, 10, 0)
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def addLine(self, x1, y1, x2, y2, construction=False):
        return self.sketch.addGeometry(Part.LineSegment(V(x1, y1, 0), V(x2, y2, 0)), construction)

    def addPoint(self, x, y):
        return self.sketch.addGeometry(Part.Point(V(x, y, 0)))

    def extend(self, increment, pos=END, geo=None):
        before = len(self.sketch.Constraints)
        self.sketch.extend(self.a if geo is None else geo, increment, pos, True)
        self.assertEqual(self.doc.recompute(), 1, "the sketch recomputes")
        self.assertNotIn("Invalid", self.sketch.State)
        return self.sketch.Constraints[before:]

    def assertAt(self, geoId, pos, x, y):
        p = self.sketch.getPoint(geoId, pos)
        self.assertAlmostEqual(p.x, x, delta=TOL, msg=f"x of {geoId}.{pos}: {p}")
        self.assertAlmostEqual(p.y, y, delta=TOL, msg=f"y of {geoId}.{pos}: {p}")

    def assertOnObject(self, added, curve, pos=END):
        self.assertEqual(len(added), 1, f"one constraint: {[c.Type for c in added]}")
        c = added[0]
        self.assertEqual(
            (c.Type, c.First, c.FirstPos, c.Second), ("PointOnObject", self.a, pos, curve)
        )

    def assertCoincident(self, added, geo, geoPos, pos=END):
        self.assertEqual(len(added), 1, f"one constraint: {[c.Type for c in added]}")
        c = added[0]
        self.assertEqual(
            (c.Type, c.First, c.FirstPos, c.Second, c.SecondPos),
            ("Coincident", self.a, pos, geo, geoPos),
        )

    def testTheEndStopsAtALineInTheWay(self):
        b = self.addLine(15, -5, 15, 5)
        added = self.extend(10)
        self.assertAt(self.a, END, 15, 0)
        self.assertAt(self.a, START, 0, 0)
        self.assertOnObject(added, b)

    def testNothingInTheWayEndsAtTheClick(self):
        added = self.extend(10)
        self.assertAt(self.a, END, 20, 0)
        self.assertEqual(added, [])

    def testTheFirstOfTwoBoundariesStopsIt(self):
        self.addLine(15, -5, 15, 5)
        d = self.addLine(12, -5, 12, 5)
        added = self.extend(10)
        self.assertAt(self.a, END, 12, 0)
        self.assertOnObject(added, d)

    def testABoundaryBeyondTheClickIsNotReached(self):
        self.addLine(25, -5, 25, 5)
        added = self.extend(10)
        self.assertAt(self.a, END, 20, 0)
        self.assertEqual(added, [])

    def testAConstructionLineStopsIt(self):
        b = self.addLine(15, -5, 15, 5, construction=True)
        added = self.extend(10)
        self.assertAt(self.a, END, 15, 0)
        self.assertOnObject(added, b)

    def testTheStartGrowsTheOtherWay(self):
        b = self.addLine(-4, -5, -4, 5)
        added = self.extend(10, START)
        self.assertAt(self.a, START, -4, 0)
        self.assertAt(self.a, END, 10, 0)
        self.assertOnObject(added, b, START)

    def testASlantedLineStopsAtTheCrossing(self):
        # the line through (14,-2) and (18,6) crosses y=0 at x=15
        b = self.addLine(14, -2, 18, 6)
        added = self.extend(10)
        self.assertAt(self.a, END, 15, 0)
        self.assertOnObject(added, b)

    def testACollinearLineStopsItAtItsEnd(self):
        c = self.addLine(18, 0, 30, 0)
        added = self.extend(30)
        self.assertAt(self.a, END, 18, 0)
        self.assertCoincident(added, c, START)

    def testACurveEndOnThePathIsAPoint(self):
        # a line ending on A's path: its end point is the boundary (Coincident, not PointOnObject)
        e = self.addLine(16, 0, 16, 7)
        added = self.extend(10)
        self.assertAt(self.a, END, 16, 0)
        self.assertCoincident(added, e, START)

    def testACircleStopsItAtItsNearSide(self):
        c = self.sketch.addGeometry(Part.Circle(V(20, 0, 0), V(0, 0, 1), 3))
        added = self.extend(20)
        self.assertAt(self.a, END, 17, 0)
        self.assertOnObject(added, c)

    def testAnArcStopsIt(self):
        # the arc of r 5 about (15,0) from -90 to 90 deg crosses the path at (20,0) only
        arc = self.sketch.addGeometry(
            Part.ArcOfCircle(Part.Circle(V(15, 0, 0), V(0, 0, 1), 5), -1.5707963267948966, 1.5707963267948966)
        )
        added = self.extend(20)
        self.assertAt(self.a, END, 20, 0)
        self.assertOnObject(added, arc)

    def testASketchPointStopsIt(self):
        p = self.addPoint(14, 0)
        added = self.extend(10)
        self.assertAt(self.a, END, 14, 0)
        self.assertCoincident(added, p, START)

    def testTheOriginAxesDoNotStopIt(self):
        a = self.addLine(-10, 3, -5, 3)
        added = self.extend(10, END, a)
        self.assertAt(a, END, 5, 3)
        self.assertEqual(added, [])

    def testACurveThroughTheOldEndDoesNotStopIt(self):
        self.addLine(10, -5, 10, 5)
        added = self.extend(10)
        self.assertAt(self.a, END, 20, 0)
        self.assertEqual(added, [])

    def testAnotherCurvesExtensionIsNotABoundary(self):
        # a short vertical line whose extension would cross the path at x=15
        self.addLine(15, 2, 15, 6)
        added = self.extend(10)
        self.assertAt(self.a, END, 20, 0)
        self.assertEqual(added, [])

    def testAUsedEdgeStopsIt(self):
        wall = self.doc.addObject("Part::Feature", "Wall")
        wall.Shape = Part.makeLine(V(15, -5, 0), V(15, 5, 0))
        self.doc.recompute()
        self.sketch.addExternal("Wall", "Edge1")
        self.doc.recompute()
        added = self.extend(10)
        self.assertAt(self.a, END, 15, 0)
        self.assertOnObject(added, -3)

    def testAnImplicitModelPickDoesNotStopIt(self):
        # a constraint's helper link (ops#634) is not a Use'd edge: Onshape's model edges don't bound
        wall = self.doc.addObject("Part::Feature", "Wall")
        wall.Shape = Part.makeLine(V(15, -5, 0), V(15, 50, 0))
        self.doc.recompute()
        self.sketch.addExternal("Wall", "Edge1", False, False, True)
        p = self.addPoint(15, 30)
        self.sketch.addConstraint(Sketcher.Constraint("PointOnObject", p, START, -3))
        self.doc.recompute()
        self.assertEqual(len(self.sketch.ExternalGeometry), 1, "the helper link stays")
        added = self.extend(10)
        self.assertAt(self.a, END, 20, 0)
        self.assertEqual(added, [])

    def testShrinkingIsUnbounded(self):
        self.addLine(5, -5, 5, 5)
        added = self.extend(-3)
        self.assertAt(self.a, END, 7, 0)
        self.assertEqual(added, [])

    def testWithoutTheFlagExtendIsUnchanged(self):
        self.addLine(15, -5, 15, 5)
        before = len(self.sketch.Constraints)
        self.sketch.extend(self.a, 10, END)
        self.doc.recompute()
        self.assertAt(self.a, END, 20, 0)
        self.assertEqual(len(self.sketch.Constraints), before)


class TestSketchTrimBounds(unittest.TestCase):
    """Onshape GA3-25/25b (ops#640): a point on the curve (a sketch point, a Use'd one) bounds a
    trim, with COINCIDENT(point, the kept piece's end); a constraint's helper link (a model pick)
    doesn't, a Use'd edge does. Line L (0,0)-(10,0), trimmed with a click at (2,0)."""

    def setUp(self):
        self.doc = App.newDocument("TestSketchTrimBounds")
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.line = self.sketch.addGeometry(Part.LineSegment(V(0, 0, 0), V(10, 0, 0)))
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def addModel(self, name, shape):
        obj = self.doc.addObject("Part::Feature", name)
        obj.Shape = shape
        self.doc.recompute()
        return obj

    def lines(self):
        return [g for g in self.sketch.Geometry if isinstance(g, Part.LineSegment)]

    def assertKept(self, x1, x2):
        lines = self.lines()
        self.assertEqual(len(lines), 1, f"one piece of L: {self.sketch.Geometry}")
        ends = sorted([lines[0].StartPoint.x, lines[0].EndPoint.x])
        self.assertAlmostEqual(ends[0], x1, delta=TOL)
        self.assertAlmostEqual(ends[1], x2, delta=TOL)

    def coincidentWith(self, geo):
        return [c for c in self.sketch.Constraints if c.Type == "Coincident" and geo in (c.First, c.Second)]

    def testASketchPointOnTheLineBoundsTheTrim(self):
        p = self.sketch.addGeometry(Part.Point(V(4, 0, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("PointOnObject", p, START, self.line))
        self.doc.recompute()
        self.sketch.trim(self.line, V(2, 0, 0))
        self.doc.recompute()
        self.assertKept(4, 10)
        self.assertEqual(len(self.coincidentWith(p)), 1, f"{[c.Type for c in self.sketch.Constraints]}")

    def testAFreePointOnTheLineBoundsTheTrim(self):
        p = self.sketch.addGeometry(Part.Point(V(4, 0, 0)))
        self.sketch.trim(self.line, V(2, 0, 0))
        self.doc.recompute()
        self.assertKept(4, 10)
        self.assertEqual(len(self.coincidentWith(p)), 1)

    def testAPointOffTheLineDoesNotBoundIt(self):
        self.sketch.addGeometry(Part.Point(V(4, 1, 0)))
        self.sketch.addGeometry(Part.LineSegment(V(6, -5, 0), V(6, 5, 0)))
        self.sketch.trim(self.line, V(2, 0, 0))
        self.doc.recompute()
        pieces = [g for g in self.lines() if abs(g.StartPoint.y) < TOL and abs(g.EndPoint.y) < TOL]
        self.assertEqual(len(pieces), 1, f"L trimmed back to the line at x=6: {self.sketch.Geometry}")
        self.assertAlmostEqual(min(pieces[0].StartPoint.x, pieces[0].EndPoint.x), 6, delta=TOL)

    def testAUsedPointBoundsTheTrim(self):
        self.addModel("Peg", Part.Vertex(V(4, 0, 0)))
        self.sketch.addExternal("Peg", "Vertex1")
        self.doc.recompute()
        self.sketch.trim(self.line, V(2, 0, 0))
        self.doc.recompute()
        self.assertKept(4, 10)
        self.assertEqual(len(self.coincidentWith(-3)), 1)

    def testAUsedEdgeBoundsTheTrim(self):
        self.addModel("Wall", Part.makeLine(V(4, -5, 0), V(4, 5, 0)))
        self.sketch.addExternal("Wall", "Edge1")
        self.doc.recompute()
        self.sketch.trim(self.line, V(2, 0, 0))
        self.doc.recompute()
        self.assertKept(4, 10)

    def testAModelPickDoesNotBoundTheTrim(self):
        # a helper link (implicit, ops#634) kept by a constraint on it: not a boundary, so the
        # line, with nothing else crossing it, goes whole
        self.addModel("Wall", Part.makeLine(V(4, -5, 0), V(4, 50, 0)))
        self.sketch.addExternal("Wall", "Edge1", False, False, True)
        p = self.sketch.addGeometry(Part.Point(V(4, 30, 0)))
        self.sketch.addConstraint(Sketcher.Constraint("PointOnObject", p, START, -3))
        self.doc.recompute()
        self.sketch.trim(self.line, V(2, 0, 0))
        self.doc.recompute()
        self.assertEqual(self.lines(), [], f"L deleted whole: {self.sketch.Geometry}")

    def testPointsOnACircleBoundItsTrim(self):
        self.sketch.delGeometry(self.line)
        c = self.sketch.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5))
        self.sketch.addGeometry(Part.Point(V(5, 0, 0)))
        self.sketch.addGeometry(Part.Point(V(-5, 0, 0)))
        self.doc.recompute()
        self.sketch.trim(c, V(0, 5, 0))
        self.doc.recompute()
        arcs = [g for g in self.sketch.Geometry if isinstance(g, Part.ArcOfCircle)]
        self.assertEqual(len(arcs), 1, f"the lower arc kept: {self.sketch.Geometry}")
        mid = arcs[0].value((arcs[0].FirstParameter + arcs[0].LastParameter) / 2)
        self.assertLess(mid.y, 0)
        for q in (arcs[0].StartPoint, arcs[0].EndPoint):
            self.assertAlmostEqual(abs(q.x), 5, delta=TOL)
            self.assertAlmostEqual(q.y, 0, delta=TOL)


if __name__ == "__main__":
    unittest.main()
