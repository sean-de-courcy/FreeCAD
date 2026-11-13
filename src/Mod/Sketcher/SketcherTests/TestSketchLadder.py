# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, ops#656 D4 row 1, decision 428): the ladder at recompute.
# When a dimension's value changes (a #variable through an expression, or a typed edit), an
# under-defined sketch moves the dimension's own entity, least motion, and holds everything else
# exactly, as Onshape does (notes/onshape-facts.md SF-E4, SF-B6..B10; notes/sketcher-feel-design.md
# 3.1, 3.2). Designed geometry: each case builds the smallest sketch showing the behaviour, and the
# expected positions are defined geometrically from the constraints.

import math
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector

EXACT = 1e-9  # what must not move at all
SOLVED = 1e-6  # where the solver puts what moves


class TestSketchLadder(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SketchLadder")
        self.sk = self.doc.addObject("Sketcher::SketchObject", "Sketch")
        self.vars = self.doc.addObject("App::VarSet", "Variables")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # helpers

    def _line(self, a, b):
        return self.sk.addGeometry(Part.LineSegment(V(*a, 0), V(*b, 0)), False)

    def _variable(self, name, value):
        self.vars.addProperty("App::PropertyLength", name)
        setattr(self.vars, name, value)

    def _drive(self, constraint, name):
        """Constraint `constraint` takes its value from the variable `name`."""
        self.sk.setExpression("Constraints[{}]".format(constraint), "Variables." + name)

    def _hold(self, geo, pos):
        """Holds a point where it is with two dimensions to the origin (Onshape's FIX in SF-B7,
        SF-B8); returns nothing."""
        p = self._point(geo, pos)
        self.sk.addConstraint(Sketcher.Constraint("DistanceX", geo, pos, p.x))
        self.sk.addConstraint(Sketcher.Constraint("DistanceY", geo, pos, p.y))

    def _point(self, geo, pos):
        g = self.sk.Geometry[geo]
        return {1: g.StartPoint, 2: g.EndPoint, 3: getattr(g, "Center", None)}[pos]

    def _recompute(self):
        self.doc.recompute()
        self.assertNotIn("Invalid", self.sk.State)
        self.assertTrue(self.sk.isValid())

    def assertAt(self, point, xy, tol):
        self.assertLess(
            (point - V(xy[0], xy[1], 0)).Length,
            tol,
            "at ({:.9f}, {:.9f}), expected ({}, {})".format(point.x, point.y, xy[0], xy[1]),
        )

    def assertUnchanged(self, geo, before):
        g = self.sk.Geometry[geo]
        self.assertAt(g.StartPoint, (before.StartPoint.x, before.StartPoint.y), EXACT)
        self.assertAt(g.EndPoint, (before.EndPoint.x, before.EndPoint.y), EXACT)

    # SF-E4: a DISTANCE between two lines, the variable changed: the second line moves

    def _twoLines(self, parallel):
        """A (0,100)-(20,100) picked first, B (0,110)-(20,110) picked second, 10 apart. The
        Dimension tool stores the distance as B's start to the line A (First = B, start)."""
        a = self._line((0, 100), (20, 100))
        b = self._line((0, 110), (20, 110))
        if parallel:
            self.sk.addConstraint(Sketcher.Constraint("Parallel", a, b))
        d = self.sk.addConstraint(Sketcher.Constraint("Distance", b, 1, a, 10.0))
        self._variable("e4", 10.0)
        self._drive(d, "e4")
        self._recompute()
        return a, b, d

    def testDistanceMovesTheSecondLine(self):
        # SF-E4 with the Parallel the Dimension tool will store (design 3.1): B translates to
        # y 115, A stays exactly
        a, b, _ = self._twoLines(parallel=True)
        a0 = self.sk.Geometry[a].copy()
        self.vars.e4 = 15.0
        self._recompute()
        self.assertUnchanged(a, a0)
        self.assertAt(self.sk.Geometry[b].StartPoint, (0, 115), SOLVED)
        self.assertAt(self.sk.Geometry[b].EndPoint, (20, 115), SOLVED)

    def testDistanceWithoutParallelMovesOnlyTheMeasuredPoint(self):
        # a stored point-to-line distance: only B's start is measured, so only it moves (design
        # 3.1, "what stays a difference"); A and B's end stay exactly
        a, b, _ = self._twoLines(parallel=False)
        a0 = self.sk.Geometry[a].copy()
        self.vars.e4 = 15.0
        self._recompute()
        self.assertUnchanged(a, a0)
        self.assertAt(self.sk.Geometry[b].StartPoint, (0, 115), SOLVED)
        self.assertAt(self.sk.Geometry[b].EndPoint, (20, 110), EXACT)

    def testDistanceWithTheSecondLineHeldMovesTheFirst(self):
        # SF-E4 / SF-B7: B's ends held, A moves instead (y 100 -> 95), silently
        a, b, _ = self._twoLines(parallel=True)
        self._hold(b, 1)
        self._hold(b, 2)
        self._recompute()
        b0 = self.sk.Geometry[b].copy()
        self.vars.e4 = 15.0
        self._recompute()
        self.assertUnchanged(b, b0)
        self.assertAt(self.sk.Geometry[a].StartPoint, (0, 95), SOLVED)
        self.assertAt(self.sk.Geometry[a].EndPoint, (20, 95), SOLVED)

    def testTypedDistanceMovesTheSecondLine(self):
        # SF-B6: the same rule for a value typed into the dimension (setDatum)
        a = self._line((0, 55), (20, 55))
        b = self._line((0, 65), (20, 65))
        self.sk.addConstraint(Sketcher.Constraint("Parallel", a, b))
        d = self.sk.addConstraint(Sketcher.Constraint("Distance", b, 1, a, 10.0))
        self._recompute()
        a0 = self.sk.Geometry[a].copy()
        self.sk.setDatum(d, App.Units.Quantity("15 mm"))
        self._recompute()
        self.assertUnchanged(a, a0)
        self.assertAt(self.sk.Geometry[b].StartPoint, (0, 70), SOLVED)
        self.assertAt(self.sk.Geometry[b].EndPoint, (20, 70), SOLVED)

    # SF-E4 / SF-B8: a LENGTH, the variable changed: the start stays, the end moves along the line

    def _lengthCase(self, stored):
        start, end = (40.0, 100.0), (55.0, 105.0)
        line = self._line(start, end)
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if stored == "points":  # the Dimension tool's form: line start to line end
            c = Sketcher.Constraint("Distance", line, 1, line, 2, length)
        else:  # the classic Length command's form: the line alone
            c = Sketcher.Constraint("Distance", line, length)
        d = self.sk.addConstraint(c)
        self._variable("e4L", length)
        self._drive(d, "e4L")
        self._recompute()
        return line, start, end, length

    def _checkLength(self, line, start, end, length, new):
        ux, uy = (end[0] - start[0]) / length, (end[1] - start[1]) / length
        self.assertAt(self.sk.Geometry[line].StartPoint, start, EXACT)
        self.assertAt(
            self.sk.Geometry[line].EndPoint, (start[0] + new * ux, start[1] + new * uy), SOLVED
        )

    def testLengthMovesTheEnd(self):
        line, start, end, length = self._lengthCase("points")
        self.vars.e4L = 20.0
        self._recompute()
        self._checkLength(line, start, end, length, 20.0)

    def testClassicLengthMovesTheEnd(self):
        line, start, end, length = self._lengthCase("line")
        self.vars.e4L = 20.0
        self._recompute()
        self._checkLength(line, start, end, length, 20.0)

    def testLengthWithTheStartHeld(self):
        # SF-B8: the start held, the end moves along the line's direction
        line, start, end, length = self._lengthCase("points")
        self._hold(line, 1)
        self._recompute()
        self.vars.e4L = 20.0
        self._recompute()
        self._checkLength(line, start, end, length, 20.0)

    # SF-B10: a RADIUS on a free arc: the centre stays, the ends move out radially

    def testRadiusKeepsTheCentre(self):
        arc = self.sk.addGeometry(
            Part.ArcOfCircle(Part.Circle(V(190, 55, 0), V(0, 0, 1), 10.0), 0.0, math.pi / 2),
            False,
        )
        r = self.sk.addConstraint(Sketcher.Constraint("Radius", arc, 10.0))
        self._variable("rad", 10.0)
        self._drive(r, "rad")
        self._recompute()
        self.vars.rad = 15.0
        self._recompute()
        g = self.sk.Geometry[arc]
        self.assertAt(g.Center, (190, 55), EXACT)
        self.assertAlmostEqual(g.Radius, 15.0, delta=SOLVED)
        self.assertAt(g.StartPoint, (205, 55), SOLVED)
        self.assertAt(g.EndPoint, (190, 70), SOLVED)

    # GA3-29: a point to a line, the point moves, the line stays

    def testPointToLineMovesThePoint(self):
        line = self._line((0, 0), (30, 0))
        point = self.sk.addGeometry(Part.Point(V(10, 15, 0)), False)
        d = self.sk.addConstraint(Sketcher.Constraint("Distance", point, 1, line, 15.0))
        self._variable("gap", 15.0)
        self._drive(d, "gap")
        self._recompute()
        l0 = self.sk.Geometry[line].copy()
        self.vars.gap = 25.0
        self._recompute()
        self.assertUnchanged(line, l0)
        self.assertAt(V(self.sk.Geometry[point].X, self.sk.Geometry[point].Y, 0), (10, 25), SOLVED)

    # a circle moved by a distance translates: its radius stays (review finding 1)

    def testCircleToLineDistanceTranslatesTheCircle(self):
        line = self._line((0, 0), (30, 0))
        circle = self.sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), 5.0), False)
        # the Dimension tool stores a circle and a line with the circle First
        d = self.sk.addConstraint(Sketcher.Constraint("Distance", circle, line, 5.0))
        self._variable("gap", 5.0)
        self._drive(d, "gap")
        self._recompute()
        l0 = self.sk.Geometry[line].copy()
        self.vars.gap = 7.0
        self._recompute()
        self.assertUnchanged(line, l0)
        g = self.sk.Geometry[circle]
        self.assertAlmostEqual(g.Radius, 5.0, delta=EXACT)
        self.assertAt(g.Center, (10, 12), SOLVED)

    # GA3-29 by hand: an angle's new value turns the second-picked line

    def testAngleTurnsTheSecondLine(self):
        a = self._line((0, 0), (20, 0))
        end = (20 * math.cos(math.radians(30)), 20 * math.sin(math.radians(30)))
        b = self._line((0, 0), end)
        self.sk.addConstraint(Sketcher.Constraint("Coincident", a, 1, b, 1))
        c = self.sk.addConstraint(Sketcher.Constraint("Angle", a, b, math.radians(30)))
        self.vars.addProperty("App::PropertyAngle", "turn")
        self.vars.turn = 30.0
        self._drive(c, "turn")
        self._recompute()
        a0 = self.sk.Geometry[a].copy()
        self.vars.turn = 45.0
        self._recompute()
        self.assertUnchanged(a, a0)
        g = self.sk.Geometry[b]
        self.assertAt(g.StartPoint, (0, 0), EXACT)
        self.assertAlmostEqual(
            math.degrees(math.atan2(g.EndPoint.y, g.EndPoint.x)), 45.0, delta=SOLVED
        )

    # what must not change

    def testFullyDefinedSketchIsUnaffected(self):
        # one solution: the ladder can only land where today's solve lands
        a = self._line((0, 0), (20, 0))
        b = self._line((20, 0), (20, 10))
        self.sk.addConstraint(Sketcher.Constraint("Coincident", a, 2, b, 1))
        self.sk.addConstraint(Sketcher.Constraint("Coincident", a, 1, -1, 1))
        self.sk.addConstraint(Sketcher.Constraint("Horizontal", a))
        self.sk.addConstraint(Sketcher.Constraint("Vertical", b))
        w = self.sk.addConstraint(Sketcher.Constraint("Distance", a, 20.0))
        self.sk.addConstraint(Sketcher.Constraint("Distance", b, 10.0))
        self._variable("w", 20.0)
        self._drive(w, "w")
        self._recompute()
        self.assertTrue(self.sk.FullyConstrained)
        self.vars.w = 30.0
        self._recompute()
        self.assertAt(self.sk.Geometry[a].StartPoint, (0, 0), SOLVED)
        self.assertAt(self.sk.Geometry[a].EndPoint, (30, 0), SOLVED)
        self.assertAt(self.sk.Geometry[b].EndPoint, (30, 10), SOLVED)

    def testUnchangedRecomputeMovesNothing(self):
        # nothing changed: nothing moves, not even within the solver's tolerance
        a, b, _ = self._twoLines(parallel=True)
        a0, b0 = self.sk.Geometry[a].copy(), self.sk.Geometry[b].copy()
        self.sk.touch()
        self._recompute()
        self.assertUnchanged(a, a0)
        self.assertUnchanged(b, b0)

    def testMoverBoundToTheOthersFallsToTheNextRung(self):
        # a rectangle's right side moved by a width: rung 1 (the side alone) cannot keep the
        # corners joined, so the next rung moves it with the top and bottom stretching; the left
        # side (the reference) stays exactly
        pts = [(0, 0), (20, 0), (20, 10), (0, 10)]
        ids = [self._line(pts[i], pts[(i + 1) % 4]) for i in range(4)]
        for i in range(4):
            self.sk.addConstraint(Sketcher.Constraint("Coincident", ids[i], 2, ids[(i + 1) % 4], 1))
        self.sk.addConstraint(Sketcher.Constraint("Horizontal", ids[0]))
        self.sk.addConstraint(Sketcher.Constraint("Horizontal", ids[2]))
        self.sk.addConstraint(Sketcher.Constraint("Vertical", ids[1]))
        self.sk.addConstraint(Sketcher.Constraint("Vertical", ids[3]))
        # the width as the Dimension tool stores two parallel lines: the right side (picked
        # second) by its start, to the left side
        w = self.sk.addConstraint(Sketcher.Constraint("Distance", ids[1], 1, ids[3], 20.0))
        self._variable("w", 20.0)
        self._drive(w, "w")
        self._recompute()
        left = self.sk.Geometry[ids[3]].copy()
        self.vars.w = 30.0
        self._recompute()
        self.assertUnchanged(ids[3], left)
        self.assertAt(self.sk.Geometry[ids[1]].StartPoint, (30, 0), SOLVED)
        self.assertAt(self.sk.Geometry[ids[1]].EndPoint, (30, 10), SOLVED)


if __name__ == "__main__":
    unittest.main()
