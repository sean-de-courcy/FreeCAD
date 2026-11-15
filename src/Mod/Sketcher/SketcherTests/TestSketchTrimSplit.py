# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#656): Trim and Split keep what a sketch's dimensions measure.
#
# Every test builds the smallest sketch that shows the behaviour, makes the cut, and then drives a
# dimension: the geometry must follow as it would have before the cut. The expectations are geometric
# (radii, points on lines), never a constraint list.

import math
import os
import tempfile
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

    # ops#656 F3 (rehearsal 3; Onshape SK11): a whole circle splits at two points into two arcs of that
    # circle, joined end to end at both points. They stay one closed circle through a radius change, and
    # the cut points slide on it (2 more degrees of freedom), with nothing repeated.
    def _split_circle_twice(self, p1, p2):
        sk = self.sk
        _circle(sk, 5, 60, 20)  # the rehearsal's circle
        sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 60))
        sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 20))
        r = sk.addConstraint(Sketcher.Constraint("Radius", 0, 5))
        sk.renameConstraint(r, "radius")
        self.doc.recompute()
        self.assertEqual(sk.DoF, 0)
        sk.split(0, p1, p2)
        self.doc.recompute()
        self._healthy()
        arcs = _arcs(sk)
        self.assertEqual(len(arcs), 2)
        self.assertTrue(all(isinstance(g, Part.ArcOfCircle) for _, g in arcs))
        self.assertEqual(sk.DoF, 2, "the two cut points slide on the circle; nothing else is free")
        self._assert_closed_circle(5.0)
        sk.setDatum(_named(sk, "radius"), App.Units.Quantity("7 mm"))
        self.doc.recompute()
        self._healthy()
        self._assert_closed_circle(7.0)

    def _assert_closed_circle(self, radius):
        (_, a), (_, b) = _arcs(self.sk)
        for g in (a, b):
            self.assertAlmostEqual(g.Radius, radius, delta=TOL, msg="an arc left the circle")
            self.assertAlmostEqual((g.Center - V(60, 20, 0)).Length, 0.0, delta=TOL)
        self.assertAlmostEqual((a.EndPoint - b.StartPoint).Length, 0.0, delta=TOL, msg="the circle opened")
        self.assertAlmostEqual((b.EndPoint - a.StartPoint).Length, 0.0, delta=TOL, msg="the circle opened")
        self.assertAlmostEqual(_face_area(self.sk), math.pi * radius**2, delta=1e-5)

    def testSplitCircleAtTwoOppositePoints(self):
        self._split_circle_twice(V(65, 20, 0), V(55, 20, 0))

    def testSplitCircleAtTwoPoints(self):
        self._split_circle_twice(V(60, 25, 0), V(65, 20, 0))

    def testSplitCircleAtTwoPointsKeepsTangentLine(self):
        sk = self.sk
        _circle(sk, 10)  # 0
        _line(sk, (-20, 10), (20, 10))  # 1, tangent on top
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Tangent", 0, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", 1))
        r = sk.addConstraint(Sketcher.Constraint("Radius", 0, 10))
        sk.renameConstraint(r, "radius")
        self.doc.recompute()
        sk.split(0, V(10, 0, 0), V(-10, 0, 0))
        self.doc.recompute()
        self._healthy()
        sk.setDatum(_named(sk, "radius"), App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self._healthy()
        self.assertAlmostEqual(sk.Geometry[1].StartPoint.y, 12.0, delta=TOL, msg="the line lost its tangency")

    def testSplitCircleAtOnePointTwiceRefused(self):
        sk = self.sk
        _circle(sk, 10)
        self.doc.recompute()
        with self.assertRaises(ValueError):
            sk.split(0, V(10, 0, 0), V(10, 0, 0))
        self.assertEqual(len(sk.Geometry), 1)

    def testSplitEllipseAtTwoPointsRefused(self):
        sk = self.sk
        sk.addGeometry(Part.Ellipse(V(0, 0, 0), 10, 5))
        self.doc.recompute()
        with self.assertRaises(ValueError):
            sk.split(0, V(10, 0, 0), V(-10, 0, 0))
        self.assertIsInstance(sk.Geometry[0], Part.Ellipse)

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

    # ops#656 trim then radius (Onshape SK10): a circle trimmed between two free lines becomes two arcs of
    # one circle; a radius change moves both arcs, and every arc end stays on its line (the profile stays
    # closed: the lines move instead, as in Onshape, where they went to x = +-6).
    def testTrimCircleBetweenFreeLinesThenRadius(self):
        sk = self.sk
        _circle(sk, 10)  # 0
        lines = [_line(sk, (-5, -15), (-5, 15)), _line(sk, (5, -15), (5, 15))]
        sk.addConstraint(Sketcher.Constraint("Coincident", 0, 3, -1, 1))
        r = sk.addConstraint(Sketcher.Constraint("Radius", 0, 10))
        sk.renameConstraint(r, "radius")
        self.doc.recompute()
        sk.trim(0, V(0, 10, 0))
        self.doc.recompute()
        sk.trim(0, V(0, -10, 0))
        self.doc.recompute()
        self.assertEqual(len(_arcs(sk)), 2)
        self._healthy()
        sk.setDatum(_named(sk, "radius"), App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self._healthy()

        def off_line(p):
            return min(
                abs((V(p) - sk.Geometry[i].StartPoint).cross(sk.Geometry[i].EndPoint - sk.Geometry[i].StartPoint).Length)
                / (sk.Geometry[i].EndPoint - sk.Geometry[i].StartPoint).Length
                for i in lines
            )

        for _, g in _arcs(sk):
            self.assertAlmostEqual(g.Radius, 12.0, delta=TOL, msg="an arc kept the old radius")
            self.assertAlmostEqual(g.Center.Length, 0.0, delta=TOL)
            for p in _endpoints(g):
                self.assertLess(off_line(p), TOL, "an arc end left its line: the profile opened")

    # ops#656 trim then radius (Onshape SK10b): a line trimmed between two free lines keeps its pieces
    # collinear: pulling one piece's outer end off the old line tilts the other piece with it.
    def testTrimLineBetweenFreeLinesStaysCollinear(self):
        sk = self.sk
        _line(sk, (-15, 0), (15, 0))  # 0
        _line(sk, (-5, -10), (-5, 10))  # 1
        _line(sk, (5, -10), (5, 10))  # 2
        self.doc.recompute()
        sk.trim(0, V(0, 0, 0))
        self.doc.recompute()
        self._healthy()
        pieces = [i for i, g in enumerate(sk.Geometry) if isinstance(g, Part.LineSegment) and i not in (1, 2)]
        self.assertEqual(len(pieces), 2)
        left, right = sorted(pieces, key=lambda i: sk.Geometry[i].StartPoint.x + sk.Geometry[i].EndPoint.x)
        outer = lambda i: max((1, 2), key=lambda pos: abs(sk.getPoint(i, pos).x))  # noqa: E731
        sk.addConstraint(Sketcher.Constraint("DistanceY", left, outer(left), right, outer(right), 4))
        self.doc.recompute()
        self._healthy()
        a, b = sk.getPoint(left, outer(left)), sk.getPoint(right, outer(right))
        self.assertAlmostEqual(b.y - a.y, 4.0, delta=TOL)
        d = (b - a).normalize()
        for i in pieces:
            for pos in (1, 2):
                self.assertLess((sk.getPoint(i, pos) - a).cross(d).Length, TOL, "the pieces are no longer collinear")

    # ops#656 trim then radius (the TNP test testRectanglewithArcChangeinGlobalCenter, in designed
    # geometry): a rectangle's bottom edge trimmed between the ends of an arc standing on it. The pieces
    # are collinear, so an Equal of the two sides then repeats what the sketch imposes; it is accepted
    # (TestSketchRepeatedConstraints), and the arc's radius can then be dimensioned and changed.
    def testTrimRectangleEdgeThenEqualAndRadius(self):
        sk = self.sk
        top = _line(sk, (-50, 25), (50, 25))
        right = _line(sk, (50, 25), (50, -25))
        bottom = _line(sk, (50, -25), (-50, -25))
        left = _line(sk, (-50, -25), (-50, 25))
        for a, b in ((top, right), (right, bottom), (bottom, left), (left, top)):
            sk.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))
        for i in (top, bottom):
            sk.addConstraint(Sketcher.Constraint("Horizontal", i))
        for i in (right, left):
            sk.addConstraint(Sketcher.Constraint("Vertical", i))
        sk.addConstraint(Sketcher.Constraint("DistanceX", bottom, 2, -50))
        sk.addConstraint(Sketcher.Constraint("DistanceY", bottom, 2, -25))
        a1 = math.asin(35.0 / 40.0)  # an arc of r40 about (0, -60) with both ends on y = -25
        arc = sk.addGeometry(Part.ArcOfCircle(Part.Circle(V(0, -60, 0), V(0, 0, 1), 40), a1, math.pi - a1))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", arc, 3, -2))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", arc, 1, bottom))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", arc, 2, bottom))
        self.doc.recompute()
        sk.trim(bottom, V(0, -25, 0))
        self.doc.recompute()
        self._healthy()
        sk.addConstraint(Sketcher.Constraint("Equal", left, right))
        rad = sk.addConstraint(Sketcher.Constraint("Radius", arc, 30))
        sk.setDatum(rad, App.Units.Quantity("25 mm"))  # raised "Datum ... is invalid" on the line (b24d855144)
        self.doc.recompute()
        self.assertEqual(list(sk.ConflictingConstraints), [])
        self.assertTrue(sk.isValid())
        g = sk.Geometry[arc]
        self.assertAlmostEqual(g.Radius, 25.0, delta=TOL)
        for p in _endpoints(g):
            self.assertAlmostEqual(p.y, -25.0, delta=TOL, msg="an arc end left the bottom edge")
        bottoms = [i for i, x in enumerate(sk.Geometry) if isinstance(x, Part.LineSegment) and i not in (top, right, left)]
        self.assertEqual(len(bottoms), 2)
        for i in bottoms:
            for pos in (1, 2):
                self.assertAlmostEqual(sk.getPoint(i, pos).y, -25.0, delta=TOL, msg="a bottom piece moved off its line")


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------------------------------
# Sketcher round 2 (ops#656): repeated constraints, and the midpoint of an arc.
#
# Repeated constraints: a constraint that repeats what the others already impose, and agrees with them,
# is accepted as Onshape accepts it: the sketch solves, its geometry is written, its dimensions can be
# changed and the features built on it recompute. A constraint that contradicts the others still fails.
#
# Midpoint on an arc (the user's report 14, ops#645): Sketcher.Constraint('Midpoint', point, pos, arc)
# keeps the point on the arc's circle at the mean of its end angles: the middle of the arc itself, not
# of its chord, for arcs over 180 degrees too.


def _rectangle(sk, w, h):
    """Four lines drawn as a w x h rectangle at the origin, joined end to end, the corner fixed."""
    pts = [(0, 0), (w, 0), (w, h), (0, h)]
    ids = [_line(sk, pts[i], pts[(i + 1) % 4]) for i in range(4)]
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", ids[i], 2, ids[(i + 1) % 4], 1))
    sk.addConstraint(Sketcher.Constraint("Coincident", ids[0], 1, -1, 1))
    return ids


def _face_area(sk):
    return Part.Face(Part.Wire(Part.__sortEdges__(sk.Shape.Edges))).Area


class TestSketchRepeatedConstraints(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("Repeated")
        self.sk = self.doc.addObject("Sketcher::SketchObject", "Sketch")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _repeated_rectangle(self):
        """A rectangle drawn 19 x 9 whose constraints make it 20 x 10, with a Horizontal on both the
        bottom and the top and a Vertical on both sides, and the bottom's and the top's length both
        20: with both sides vertical the top's length repeats the bottom's."""
        sk = self.sk
        b, r, t, l = _rectangle(sk, 19, 9)
        for i in (b, t):
            sk.addConstraint(Sketcher.Constraint("Horizontal", i))
        for i in (r, l):
            sk.addConstraint(Sketcher.Constraint("Vertical", i))
        sk.addConstraint(Sketcher.Constraint("DistanceX", b, 1, b, 2, 20))
        sk.addConstraint(Sketcher.Constraint("DistanceX", t, 2, t, 1, 20))
        side = sk.addConstraint(Sketcher.Constraint("DistanceY", r, 1, r, 2, 10))
        return side

    def testConsistentRepeatsAreAccepted(self):
        self._repeated_rectangle()
        ext = self.doc.addObject("Part::Extrusion", "Extrude")
        ext.Base = self.sk
        ext.Dir = V(0, 0, 5)
        ext.Solid = True
        self.doc.recompute()
        self.assertTrue(self.sk.RedundantConstraints, "the design must have repeated constraints")
        self.assertEqual(list(self.sk.ConflictingConstraints), [])
        self.assertNotIn("Invalid", self.sk.State)
        self.assertTrue(self.sk.isValid())
        # the solved geometry is written: 20 x 10, not the 19 x 9 drawn
        self.assertAlmostEqual(self.sk.Geometry[0].length(), 20.0, delta=TOL)
        self.assertAlmostEqual(self.sk.Geometry[1].length(), 10.0, delta=TOL)
        self.assertAlmostEqual(_face_area(self.sk), 200.0, delta=1e-5)
        self.assertTrue(ext.isValid())
        self.assertAlmostEqual(ext.Shape.Volume, 1000.0, delta=1e-4)

    def testDimensionChangesInARepeatedSketch(self):
        side = self._repeated_rectangle()
        self.doc.recompute()
        self.sk.setDatum(side, App.Units.Quantity("12 mm"))
        self.doc.recompute()
        self.assertTrue(self.sk.isValid())
        self.assertAlmostEqual(self.sk.Geometry[1].length(), 12.0, delta=TOL)
        self.assertAlmostEqual(_face_area(self.sk), 240.0, delta=1e-5)

    def testContradictingRepeatIsKept(self):
        """ops#640 (Onshape SK8b): a repeat set to contradict keeps its value; the pair is left
        out of the solve, the width stays where it was, and the sketch is a warning."""
        self._repeated_rectangle()
        self.doc.recompute()
        bottom = 9  # the bottom's DistanceX (four coincidences, the corner, two H, two V before it)
        self.assertEqual(self.sk.Constraints[bottom].Type, "DistanceX")
        self.sk.setDatum(bottom, App.Units.Quantity("25 mm"))
        self.doc.recompute()
        self.assertTrue(self.sk.isValid(), self.sk.State)
        self.assertIn("Warning", self.sk.State)
        self.assertAlmostEqual(self.sk.Constraints[bottom].Value, 25.0, delta=TOL)
        self.assertAlmostEqual(self.sk.Geometry[0].length(), 20.0, delta=TOL)

    def testConflictSolvesTheRest(self):
        """ops#640 (Onshape SK7): the conflicting pair is left out, the line keeps its drawn 20,
        the recompute goes on as a warning."""
        sk = self.sk
        b, r, t, l = _rectangle(sk, 20, 10)
        sk.addConstraint(Sketcher.Constraint("Horizontal", b))
        sk.addConstraint(Sketcher.Constraint("DistanceX", b, 1, b, 2, 20))
        sk.addConstraint(Sketcher.Constraint("DistanceX", b, 1, b, 2, 30))
        self.doc.recompute()
        self.assertTrue(sk.ConflictingConstraints)
        self.assertTrue(sk.isValid(), sk.State)
        self.assertIn("Warning", sk.State)
        self.assertAlmostEqual(sk.Geometry[b].length(), 20.0, delta=TOL)

    def testDuplicateConstraintIsAccepted(self):
        """The same Horizontal twice on one line, the rehearsals' commonest case."""
        sk = self.sk
        i = _line(sk, (0, 0), (10, 1))
        sk.addConstraint(Sketcher.Constraint("Horizontal", i))
        sk.addConstraint(Sketcher.Constraint("Horizontal", i))
        self.doc.recompute()
        self.assertEqual(len(sk.RedundantConstraints), 1)
        self.assertTrue(sk.isValid())
        g = sk.Geometry[i]
        self.assertAlmostEqual(g.StartPoint.y, g.EndPoint.y, delta=TOL)
        self.assertAlmostEqual(sk.Shape.Edges[0].Vertexes[0].Point.y,
                               sk.Shape.Edges[0].Vertexes[1].Point.y, delta=TOL)


    def testRepeatsHoldingOnlyAtTheSolution(self):
        """Skeptic 11-10, 3: the whole rectangle's constraints added at once to the 19 x 9 drawing,
        so the repeated length holds only once the geometry has moved: accepted, 20 x 10."""
        sk = self.sk
        pts = [(0, 0), (19, 0), (19, 9), (0, 9)]
        ids = [_line(sk, pts[i], pts[(i + 1) % 4]) for i in range(4)]
        b, r, t, l = ids
        cs = [Sketcher.Constraint("Coincident", ids[i], 2, ids[(i + 1) % 4], 1) for i in range(4)]
        cs += [Sketcher.Constraint("Coincident", b, 1, -1, 1)]
        cs += [Sketcher.Constraint("Horizontal", i) for i in (b, t)]
        cs += [Sketcher.Constraint("Vertical", i) for i in (r, l)]
        cs += [Sketcher.Constraint("DistanceX", b, 1, b, 2, 20),
               Sketcher.Constraint("DistanceX", t, 2, t, 1, 20),
               Sketcher.Constraint("DistanceY", r, 1, r, 2, 10)]
        sk.addConstraint(cs)
        self.doc.recompute()
        self.assertTrue(sk.RedundantConstraints)
        self.assertTrue(sk.isValid())
        self.assertAlmostEqual(sk.Geometry[b].length(), 20.0, delta=TOL)
        self.assertAlmostEqual(sk.Geometry[t].length(), 20.0, delta=TOL)

    def testRepeatedDimensionsDrivenTogether(self):
        """Skeptic 11-10, 3: the bottom's and the top's length both bound to one spreadsheet cell;
        the cell 20 -> 30: both follow (they repeat each other at every value)."""
        import Spreadsheet  # noqa: F401  (the module's type)

        sheet = self.doc.addObject("Spreadsheet::Sheet", "Params")
        sheet.set("A1", "20")
        sheet.setAlias("A1", "width")
        self.doc.recompute()
        self._repeated_rectangle()
        self.sk.setExpression("Constraints[9]", "Params.width")
        self.sk.setExpression("Constraints[10]", "Params.width")
        self.doc.recompute()
        self.assertTrue(self.sk.isValid())
        sheet.set("A1", "30")
        self.doc.recompute()
        self.assertTrue(self.sk.isValid())
        self.assertAlmostEqual(self.sk.Geometry[0].length(), 30.0, delta=TOL)
        self.assertAlmostEqual(self.sk.Geometry[2].length(), 30.0, delta=TOL)

class TestSketchArcMidpoint(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("ArcMidpoint")
        self.sk = self.doc.addObject("Sketcher::SketchObject", "Sketch")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def _arc(self, a0, a1, r=10.0):
        return self.sk.addGeometry(
            Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), r), a0, a1))

    def _point(self, x, y):
        return self.sk.addGeometry(Part.Point(V(x, y, 0)))

    def _at(self, gid):
        p = self.sk.Geometry[gid]
        return V(p.X, p.Y, 0)

    def _driven_arc(self, sweep):
        """An arc centred on the origin, radius 10, its start on the positive x axis, its sweep set
        by an Angle; returns (arc, point, angle constraint) with the point kept at its middle."""
        sk = self.sk
        arc = self._arc(0, sweep)
        sk.addConstraint(Sketcher.Constraint("Coincident", arc, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Radius", arc, 10))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", arc, 1, -1))
        ang = sk.addConstraint(Sketcher.Constraint("Angle", arc, sweep))
        pt = self._point(2, 1)
        sk.addConstraint(Sketcher.Constraint("Midpoint", pt, 1, arc))
        return arc, pt, ang

    def _assert_at_angle(self, gid, degrees, r=10.0):
        a = math.radians(degrees)
        p = self._at(gid)
        self.assertAlmostEqual(p.x, r * math.cos(a), delta=TOL)
        self.assertAlmostEqual(p.y, r * math.sin(a), delta=TOL)

    def testPointGoesToTheArcsMiddle(self):
        arc, pt, ang = self._driven_arc(math.pi / 2)
        self.assertEqual(self.sk.solve(), 0)
        self.doc.recompute()
        self.assertTrue(self.sk.isValid())
        self.assertEqual(self.sk.Constraints[-1].Type, "Midpoint")
        self._assert_at_angle(pt, 45)
        self.assertTrue(self.sk.FullyConstrained)

    def testMiddleFollowsTheArcPast180(self):
        """At 270 degrees the arc's middle is at 135 degrees on the arc; the chord's middle would be
        inside the circle and the far side of the circle at -45 degrees."""
        arc, pt, ang = self._driven_arc(math.pi / 2)
        self.doc.recompute()
        for sweep, middle in ((math.pi, 90), (1.5 * math.pi, 135), (0.4 * math.pi, 36)):
            self.sk.setDatum(ang, App.Units.Quantity("%.12f rad" % sweep))
            self.doc.recompute()
            self.assertTrue(self.sk.isValid())
            self._assert_at_angle(pt, middle)

    def testRadiusChangeKeepsTheMiddle(self):
        sk = self.sk
        arc, pt, ang = self._driven_arc(math.pi / 3)
        self.doc.recompute()
        sk.setDatum(1, App.Units.Quantity("25 mm"))
        self.doc.recompute()
        self._assert_at_angle(pt, 30, r=25.0)

    def testLineEndAtTheMiddle(self):
        """A line's end, not a lone point, kept at the middle of a blocked arc from 30 to 150 deg."""
        sk = self.sk
        arc = self._arc(math.radians(30), math.radians(150))
        sk.addConstraint(Sketcher.Constraint("Block", arc))
        ln = _line(sk, (0, 0), (1, 5))
        sk.addConstraint(Sketcher.Constraint("Coincident", ln, 1, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Midpoint", ln, 2, arc))
        self.doc.recompute()
        self.assertTrue(sk.isValid())
        end = sk.Geometry[ln].EndPoint
        self.assertAlmostEqual(end.x, 0.0, delta=TOL)
        self.assertAlmostEqual(end.y, 10.0, delta=TOL)
        self.assertTrue(sk.FullyConstrained)

    def testSavedAndReopened(self):
        arc, pt, ang = self._driven_arc(math.pi / 2)
        self.doc.recompute()
        path = os.path.join(tempfile.mkdtemp(), "midpoint.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        sk = self.doc.getObject("Sketch")
        self.assertEqual(sk.Constraints[-1].Type, "Midpoint")
        sk.setDatum(ang, App.Units.Quantity("%.12f rad" % math.pi))
        self.doc.recompute()
        self.sk = sk
        self._assert_at_angle(pt, 90)

    def testOnlyArcsOfCircles(self):
        sk = self.sk
        ln = _line(sk, (0, 0), (10, 0))
        pt = self._point(3, 3)
        sk.addConstraint(Sketcher.Constraint("Midpoint", pt, 1, ln))
        self.doc.recompute()
        self.assertTrue(sk.MalformedConstraints)
        self.assertFalse(sk.isValid())

    def testDeletingTheArcDeletesTheConstraint(self):
        arc, pt, ang = self._driven_arc(math.pi / 2)
        self.doc.recompute()
        self.sk.delGeometry(arc)
        self.doc.recompute()
        self.assertFalse([c for c in self.sk.Constraints if c.Type == "Midpoint"])
        self.assertTrue(self.sk.isValid())

    def testRepeatedMidpointFollowsTheArc(self):
        """Review sketcher-2 r1, L1: the same Midpoint twice on one point; the arc's sweep 100 ->
        150 degrees: the point follows to 75 degrees (the repeat agrees at every sweep)."""
        arc, pt, ang = self._driven_arc(math.radians(100))
        self.sk.addConstraint(Sketcher.Constraint("Midpoint", pt, 1, arc))
        self.doc.recompute()
        self.assertTrue(self.sk.isValid())
        self.sk.setDatum(ang, App.Units.Quantity("150 deg"))
        self.doc.recompute()
        self.assertTrue(self.sk.isValid())
        self._assert_at_angle(pt, 75)

    def testDragAnEndThroughTheStart(self):
        """Skeptic 11-10, 2: the arc's end dragged back through its start, by the solver, in
        steps. Whatever each step does (refused, or moved), the point stays at the middle of the
        arc as written: never on the far side of the circle."""
        sk = self.sk
        arc = self._arc(0, math.radians(60))
        sk.addConstraint(Sketcher.Constraint("Coincident", arc, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Radius", arc, 10))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", arc, 1, -1))
        pt = self._point(2, 1)
        sk.addConstraint(Sketcher.Constraint("Midpoint", pt, 1, arc))
        self.doc.recompute()
        for deg in (30, 10, 2, -2, -10, -90):
            a = math.radians(deg)
            try:
                sk.moveGeometry(arc, 2, V(10 * math.cos(a), 10 * math.sin(a), 0), False)
            except Exception:
                pass
            g = sk.Geometry[arc]
            middle = g.value((g.FirstParameter + g.LastParameter) / 2)
            self.assertLess((self._at(pt) - middle).Length, 1e-6, "after the step to %d" % deg)

    def testFilletAtTheCornerDropsTheMidpoint(self):
        """Skeptic 11-10, 1: a corner of two lines kept at an arc's middle, then filleted: the
        corner is gone, so its Midpoint goes as a Point on object would, and the second line keeps
        its direction (26.57 degrees)."""
        sk = self.sk
        arc = self._arc(0, math.pi)
        sk.addConstraint(Sketcher.Constraint("Coincident", arc, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("Radius", arc, 10))
        l1 = _line(sk, (0, -10), (0, 10))
        l2 = _line(sk, (0, 10), (10, 15))
        sk.addConstraint(Sketcher.Constraint("Coincident", l1, 2, l2, 1))
        sk.addConstraint(Sketcher.Constraint("Midpoint", l1, 2, arc))
        self.doc.recompute()
        sk.fillet(l1, 2, 1.0)
        self.doc.recompute()
        g = sk.Geometry[l2]
        angle = math.degrees(math.atan2(g.EndPoint.y - g.StartPoint.y, g.EndPoint.x - g.StartPoint.x))
        self.assertAlmostEqual(angle, math.degrees(math.atan2(5, 10)), delta=1e-6)
