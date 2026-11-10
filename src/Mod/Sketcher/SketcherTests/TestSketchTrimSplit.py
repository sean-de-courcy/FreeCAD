# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#656): Trim and Split keep what a sketch's dimensions measure.
#
# Every test builds the smallest sketch that shows the behaviour, makes the cut, and then drives a
# dimension: the geometry must follow as it would have before the cut. The expectations are geometric
# (radii, points on lines), never a constraint list.

import math
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector
TOL = 1e-6


def _circle(sk, r, x=0.0, y=0.0):
    return sk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r))


def _line(sk, a, b):
    return sk.addGeometry(Part.LineSegment(V(a[0], a[1], 0), V(b[0], b[1], 0)))


def _arcs(sk):
    return [(i, g) for i, g in enumerate(sk.Geometry) if isinstance(g, (Part.ArcOfCircle, Part.Circle))]


def _endpoints(g):
    return (V(g.StartPoint), V(g.EndPoint))


def _named(sk, name):
    for i, c in enumerate(sk.Constraints):
        if c.Name == name:
            return i
    return None


class TestSketchTrimSplit(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TrimSplit")
        self.sk = self.doc.addObject("Sketcher::SketchObject", "Sketch")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _healthy(self):
        self.assertEqual(self.sk.solve(), 0, "the sketch must solve")
        self.assertEqual(list(self.sk.ConflictingConstraints), [])
        self.assertEqual(list(self.sk.RedundantConstraints), [])
        self.assertEqual(list(self.sk.MalformedConstraints), [])

    def _concentric_pair(self):
        sk = self.sk
        _circle(sk, 10)  # 0 inner
        _circle(sk, 11)  # 1 outer
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 1, 3, 0, 3))
        sk.addConstraint(Sketcher.Constraint("Radius", 0, 10))
        d = sk.addConstraint(Sketcher.Constraint("Distance", 0, 1, 1.0))
        sk.renameConstraint(d, "offset")
        self.doc.recompute()

    def _assert_outer_pieces_at(self, radius, inner=0):
        pieces = [g for i, g in _arcs(self.sk) if i != inner]
        self.assertTrue(pieces)
        for g in pieces:
            self.assertAlmostEqual(g.Radius, radius, delta=TOL)
            self.assertAlmostEqual(g.Center.Length, 0.0, delta=TOL)

    # Fix 1 (report 27 by Split, probe P1): a curve-to-curve distance survives a split as a curve-to-curve
    # distance, and the cut moves nothing. (A whole circle can't be split at one point: below.)
    def testSplitKeepsConcentricOffset(self):
        sk = self.sk
        _circle(sk, 10)  # 0 inner
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 11), 0.3, 2.8))  # 1 outer
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 1, 3, 0, 3))
        sk.addConstraint(Sketcher.Constraint("Radius", 0, 10))
        d = sk.addConstraint(Sketcher.Constraint("Distance", 0, 1, 1.0))
        sk.renameConstraint(d, "offset")
        self.doc.recompute()
        self.sk.split(1, V(0, 11, 0))
        self.doc.recompute()
        self._healthy()
        self._assert_outer_pieces_at(11.0)
        i = _named(self.sk, "offset")
        self.assertIsNotNone(i, "the offset dimension must survive the splits")
        self.sk.setDatum(i, App.Units.Quantity("2 mm"))
        self.doc.recompute()
        self._healthy()
        self._assert_outer_pieces_at(12.0)

    # Fix 1 and fix 5 (report 27 by Trim, probe P5): the offset survives a two-piece trim; Blocked lines
    # don't move, at the cut or when the offset changes; the arcs' ends stay on the lines.
    def testTrimKeepsConcentricOffsetAndBlock(self):
        self._concentric_pair()
        sk = self.sk
        _line(sk, (-5, -15), (-5, 15))  # 2: x = -5
        _line(sk, (5, -15), (5, 15))  # 3: x = 5
        sk.addConstraint(Sketcher.Constraint("Block", 2))
        sk.addConstraint(Sketcher.Constraint("Block", 3))
        self.doc.recompute()
        lines = [_endpoints(sk.Geometry[2]), _endpoints(sk.Geometry[3])]
        sk.trim(1, V(0, 11, 0))
        self.doc.recompute()
        sk.trim(1, V(0, -11, 0))
        self.doc.recompute()
        self._healthy()
        self._assert_outer_pieces_at(11.0)
        i = _named(sk, "offset")
        self.assertIsNotNone(i, "the offset dimension must survive the trims")
        sk.setDatum(i, App.Units.Quantity("2 mm"))
        self.doc.recompute()
        self._healthy()
        self._assert_outer_pieces_at(12.0)
        for k, gi in enumerate((2, 3)):
            for p, q in zip(lines[k], _endpoints(sk.Geometry[gi])):
                self.assertAlmostEqual((p - q).Length, 0.0, delta=TOL, msg="a Blocked line moved")
        for _, g in _arcs(sk)[1:]:
            for p in _endpoints(g):
                self.assertAlmostEqual(abs(p.x), 5.0, delta=TOL, msg="an arc end left its line")

    # Fix 2 (probe P3): a circle trimmed into two arcs keeps one radius for both.
    def testTrimTwoArcsKeepRadius(self):
        sk = self.sk
        _circle(sk, 10)
        _line(sk, (-5, -15), (-5, 15))
        _line(sk, (5, -15), (5, 15))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        r = sk.addConstraint(Sketcher.Constraint("Radius", 0, 10))
        sk.renameConstraint(r, "radius")
        sk.addConstraint(Sketcher.Constraint("Block", 1))
        sk.addConstraint(Sketcher.Constraint("Block", 2))
        self.doc.recompute()
        sk.trim(0, V(0, 10, 0))
        self.doc.recompute()
        sk.trim(0, V(0, -10, 0))
        self.doc.recompute()
        self.assertEqual(len(_arcs(sk)), 2)
        self._healthy()
        self.assertEqual(sk.DoF, 0, "the two arcs are as defined as the circle was")
        sk.setDatum(_named(sk, "radius"), App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self._healthy()
        for _, g in _arcs(sk):
            self.assertAlmostEqual(g.Radius, 12.0, delta=TOL)
            for p in _endpoints(g):
                self.assertAlmostEqual(abs(p.x), 5.0, delta=TOL)

    # Fix 2: an Equal between a circle and another circle holds for every piece.
    def testTrimTwoArcsKeepEqual(self):
        sk = self.sk
        _circle(sk, 10)  # 0, trimmed
        _circle(sk, 10, 30, 0)  # 1, its equal
        _line(sk, (-5, -15), (-5, 15))
        _line(sk, (5, -15), (5, 15))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Equal", 0, 1))
        r = sk.addConstraint(Sketcher.Constraint("Radius", 1, 10))
        sk.renameConstraint(r, "radius")
        sk.addConstraint(Sketcher.Constraint("Block", 2))
        sk.addConstraint(Sketcher.Constraint("Block", 3))
        self.doc.recompute()
        sk.trim(0, V(0, 10, 0))
        sk.trim(0, V(0, -10, 0))
        self.doc.recompute()
        self._healthy()
        sk.setDatum(_named(sk, "radius"), App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self._healthy()
        for i, g in _arcs(sk):
            self.assertAlmostEqual(g.Radius, 12.0, delta=TOL)

    # Fix 3 (probe P7): a closed curve split at one point stays closed.
    def _split_once_stays_closed(self, geo, drag_to, extra_dof=1):
        sk = self.sk
        sk.addGeometry(geo)
        self.doc.recompute()
        self.assertEqual(sk.solve(), 0)
        dof = sk.DoF
        sk.split(0, geo.value(geo.FirstParameter + 0.3))
        self.doc.recompute()
        self._healthy()
        g = sk.Geometry[0]
        self.assertAlmostEqual((g.StartPoint - g.EndPoint).Length, 0.0, delta=TOL)
        if extra_dof is not None:
            self.assertEqual(sk.DoF, dof + extra_dof, "one more parameter: where the closed curve is cut")
        sk.moveGeometry(0, 1, drag_to, False)
        self.doc.recompute()
        g = sk.Geometry[0]
        self.assertAlmostEqual((g.StartPoint - g.EndPoint).Length, 0.0, delta=TOL, msg="the profile opened")

    # A circle or an ellipse has no ends: one cut leaves it whole, so Split refuses (loudly) and the
    # curve stays closed, with its constraints.
    def _split_refused(self, geo, kind):
        sk = self.sk
        sk.addGeometry(geo)
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        self.doc.recompute()
        with self.assertRaises(ValueError):
            sk.split(0, geo.value(geo.FirstParameter + 0.3))
        self.doc.recompute()
        self._healthy()
        self.assertEqual(len(sk.Geometry), 1)
        self.assertIsInstance(sk.Geometry[0], kind)
        self.assertEqual(len(sk.Constraints), 1)

    def testSplitCircleOnceRefused(self):
        self._split_refused(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10), Part.Circle)

    def testSplitEllipseOnceRefused(self):
        self._split_refused(Part.Ellipse(V(0, 0, 0), 10, 5), Part.Ellipse)

    def testSplitPeriodicBSplineOnceStaysClosed(self):
        poles = [V(10, 0, 0), V(0, 10, 0), V(-10, 0, 0), V(0, -10, 0)]
        bs = Part.BSplineCurve()
        bs.buildFromPolesMultsKnots(poles, [1] * 5, [0, 1, 2, 3, 4], True, 3)
        self._split_once_stays_closed(bs, V(3, 9, 0), extra_dof=None)

    # Fix 5: a Blocked curve that is trimmed stays Blocked: its pieces can't be dragged.
    def testTrimBlockedCircleStaysBlocked(self):
        sk = self.sk
        _circle(sk, 10)  # 0
        _line(sk, (-5, -15), (-5, 15))  # 1
        _line(sk, (5, -15), (5, 15))  # 2
        sk.addConstraint(Sketcher.Constraint("Block", 0))
        self.doc.recompute()
        sk.trim(0, V(0, 10, 0))
        sk.trim(0, V(0, -10, 0))
        self.doc.recompute()
        self._healthy()
        arcs = [i for i, _ in _arcs(sk)]
        self.assertEqual(len(arcs), 2)
        for i in arcs:
            sk.moveGeometry(i, 3, V(3, 3, 0), False)
            self.doc.recompute()
            for _, g in _arcs(sk):
                self.assertAlmostEqual(g.Radius, 10.0, delta=TOL, msg="a Blocked circle's piece changed size")
                self.assertAlmostEqual(g.Center.Length, 0.0, delta=TOL, msg="a Blocked circle's piece moved")

    # Fix 5: a Blocked line that a trimmed circle ends on stays where it is when the circle's
    # radius changes; the arc's ends slide along it.
    def testTrimNextToBlockedLine(self):
        sk = self.sk
        _circle(sk, 10)  # 0
        _line(sk, (-15, 2), (15, 2))  # 1: y = 2
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        r = sk.addConstraint(Sketcher.Constraint("Radius", 0, 10))
        sk.renameConstraint(r, "radius")
        sk.addConstraint(Sketcher.Constraint("Block", 1))
        self.doc.recompute()
        line = _endpoints(sk.Geometry[1])
        sk.trim(0, V(0, 10, 0))
        self.doc.recompute()
        self._healthy()
        sk.setDatum(_named(sk, "radius"), App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self._healthy()
        for p, q in zip(line, _endpoints(sk.Geometry[1])):
            self.assertAlmostEqual((p - q).Length, 0.0, delta=TOL, msg="the Blocked line moved")
        g = sk.Geometry[0]
        self.assertAlmostEqual(g.Radius, 12.0, delta=TOL)
        for p in _endpoints(g):
            self.assertAlmostEqual(p.y, 2.0, delta=TOL)

    # Review r2 (case rv2_arcs_joint_concentric): two arcs a user drew meeting at a common centre look like
    # Split's pieces, so Trim ties nothing when it cuts their joint away (as upstream): the second arc keeps
    # its radius. (Split, then Trim at the joint, of an arc is the same debt: ops#656.)
    def testTrimAtArcJointTiesNothing(self):
        sk = self.sk
        C = Part.Circle(V(0, 0, 0), V(0, 0, 1), 10)
        sk.addGeometry(Part.ArcOfCircle(C, math.radians(20), math.radians(90)))  # 0
        sk.addGeometry(Part.ArcOfCircle(C, math.radians(90), math.radians(160)))  # 1
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 1, 3, 0, 3))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        r = sk.addConstraint(Sketcher.Constraint("Radius", 0, 10))
        sk.renameConstraint(r, "radius")
        _line(sk, (3, -15), (3, 15))
        sk.addConstraint(Sketcher.Constraint("Block", 2))
        self.doc.recompute()
        sk.trim(0, V(1.5, 9.887, 0))
        self.doc.recompute()
        self._healthy()
        sk.setDatum(_named(sk, "radius"), App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self._healthy()
        self.assertAlmostEqual(sk.Geometry[0].Radius, 12.0, delta=TOL)
        self.assertAlmostEqual(sk.Geometry[1].Radius, 10.0, delta=0.05)  # free, not tied (12 if tied)

    # The same for a line: the pieces stay collinear.
    def testSplitThenTrimAtJointKeepsLine(self):
        sk = self.sk
        _line(sk, (-20, 0), (20, 0))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 0))
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, -20))
        sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, 0.5))
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 2, 20))
        self.doc.recompute()
        sk.split(0, V(0, 0.5, 0))
        _line(sk, (-5, -15), (-5, 15))
        sk.addConstraint(Sketcher.Constraint("Block", len(sk.Geometry) - 1))
        self.doc.recompute()
        dof = sk.DoF
        sk.trim(0, V(-2, 0.5, 0))
        self.doc.recompute()
        self._healthy()
        self.assertLessEqual(sk.DoF, dof)
        sk.moveGeometry(1, 1, V(3, 4, 0), False)
        self.doc.recompute()
        for g in sk.Geometry[:2]:
            self.assertAlmostEqual(g.StartPoint.y, 0.5, delta=TOL, msg="a piece left the line")
            self.assertAlmostEqual(g.EndPoint.y, 0.5, delta=TOL, msg="a piece left the line")

    # Review r1 (case rv_polyline_joint_free): a user's polyline vertex is not a Split joint. Trimming it
    # away ties nothing: the trimmed line doesn't follow its neighbour.
    def testTrimPolylineVertexTiesNothing(self):
        sk = self.sk
        _line(sk, (-20, 1), (0, 1))  # 0
        _line(sk, (0, 1), (20, 1))  # 1
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 1, -20))
        sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 1, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 2, 1, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 1))
        h = sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 1, 2, 1))
        sk.renameConstraint(h, "h")
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 1, 2, 20))
        _line(sk, (-5, -15), (-5, 15))
        sk.addConstraint(Sketcher.Constraint("Block", 2))
        self.doc.recompute()
        sk.trim(0, V(-2, 1, 0))
        self.doc.recompute()
        self._healthy()
        sk.setDatum(_named(sk, "h"), App.Units.Quantity("4 mm"))
        self.doc.recompute()
        self._healthy()
        g = sk.Geometry[0]
        self.assertAlmostEqual(g.EndPoint.y, 1.0, delta=TOL, msg="the trimmed line followed its neighbour")

    # Skeptic find 8: a line trimmed where it crosses a circle at the circle's parameter-0 point gets a
    # point-on-object there, not a coincidence with a "start" the circle doesn't have.
    def testTrimLineAtCircleSeam(self):
        sk = self.sk
        _line(sk, (-20, 0), (20, 0))
        _circle(sk, 3, -6, 0)
        _circle(sk, 3, 6, 0)
        sk.addConstraint(Sketcher.Constraint("Block", 1))
        sk.addConstraint(Sketcher.Constraint("Block", 2))
        self.doc.recompute()
        sk.trim(0, V(0, 0, 0))
        self.doc.recompute()
        self._healthy()

    # Skeptic find 5: Split keeps the expression on a dimension it re-creates: the radius still follows
    # the dimension it is bound to.
    def testSplitKeepsExpression(self):
        sk = self.sk
        sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 8), 0.3, 2.8))
        _line(sk, (20, 0), (24, 0))
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 1, 1, 20))
        sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 1, 1, 0.5))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 1))
        b = sk.addConstraint(Sketcher.Constraint("Distance", 1, 4))
        sk.renameConstraint(b, "base")
        r = sk.addConstraint(Sketcher.Constraint("Radius", 0, 8))
        sk.renameConstraint(r, "rad")
        sk.setExpression("Constraints.rad", "Constraints.base * 2")
        self.doc.recompute()
        sk.split(0, V(0, 8, 0))
        self.doc.recompute()
        sk.setDatum(_named(sk, "base"), App.Units.Quantity("5 mm"))
        self.doc.recompute()
        self._healthy()
        for _, g in _arcs(sk):
            self.assertAlmostEqual(g.Radius, 10.0, delta=TOL, msg="the radius lost its expression")

    # Skeptic find 4: a construction curve split stays construction.
    def testSplitKeepsConstruction(self):
        sk = self.sk
        bs = Part.BSplineCurve()
        bs.buildFromPolesMultsKnots([V(10, 0, 0), V(0, 10, 0), V(-10, 0, 0), V(0, -10, 0)], [1] * 5,
                                    [0, 1, 2, 3, 4], True, 3)
        sk.addGeometry(bs, True)
        self.doc.recompute()
        sk.split(0, bs.value(0.3))
        self.doc.recompute()
        self.assertTrue(sk.getConstruction(0))


if __name__ == "__main__":
    unittest.main()
