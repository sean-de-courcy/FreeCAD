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

    # Fix 1 (report 27 by Split, probe P1): a circle-to-circle distance survives two splits as a
    # circle-to-circle distance, and the cuts move nothing.
    def testSplitKeepsConcentricOffset(self):
        self._concentric_pair()
        self.sk.split(1, V(11, 0, 0))
        self.doc.recompute()
        self.sk.split(1, V(-11, 0, 0))
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

    def testSplitCircleOnceStaysClosed(self):
        self._split_once_stays_closed(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10), V(0, 12, 0))

    def testSplitEllipseOnceStaysClosed(self):
        self._split_once_stays_closed(Part.Ellipse(V(0, 0, 0), 10, 5), V(0, 7, 0))

    # A closed curve split twice is two pieces that close the loop at both cuts.
    def _split_twice_stays_closed(self, geo, drag_to):
        sk = self.sk
        sk.addGeometry(geo)
        self.doc.recompute()
        sk.split(0, geo.value(geo.FirstParameter + 0.3))
        sk.split(0, geo.value(geo.FirstParameter + 3.5))
        self.doc.recompute()
        self._healthy()
        self.assertEqual(len(sk.Geometry), 2)
        sk.moveGeometry(0, 1, drag_to, False)
        self.doc.recompute()
        a, b = sk.Geometry[0], sk.Geometry[1]
        ends = [a.StartPoint, a.EndPoint, b.StartPoint, b.EndPoint]
        for p in ends:
            self.assertAlmostEqual(min((p - q).Length for q in ends if q is not p), 0.0, delta=TOL,
                                   msg="the profile opened")

    def testSplitCircleTwiceStaysClosed(self):
        self._split_twice_stays_closed(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10), V(0, 12, 0))

    def testSplitEllipseTwiceStaysClosed(self):
        self._split_twice_stays_closed(Part.Ellipse(V(0, 0, 0), 10, 5), V(0, 7, 0))

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

if __name__ == "__main__":
    unittest.main()
