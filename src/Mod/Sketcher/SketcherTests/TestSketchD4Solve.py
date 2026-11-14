# SPDX-License-Identifier: LGPL-2.1-or-later

"""Sketcher D4 rows 3 and 4 (FreeCAD-CH ops#656, ops#658): two solves that went wrong on designed
geometry.

Row 3: an Angle change that moves geometry far was not reached. An arc of r 4 m with its Angle
changed 270 -> 72 degrees needs its end to travel about 14 m; the solver's steps leave the circle,
so its trust region stays a few mm and its 100 iterations run out. The Angle was then left out as
"in conflict" (the arc kept 270 degrees with a warning; before the conflict work it was refused).
Onshape takes the change. The cure ramps the changed datum from the value the drawn geometry was
solved with, only when the solve fails.

Row 4: a cycle of angle constraints that disagrees by a hair (H, Angle 30, Angle 60.00001,
Perpendicular) "converged" by shrinking a line (planegcs's Perpendicular is a dot product): valid
and silent, or a conflict, at random with the solver's path. A Perpendicular or Parallel met only
by shrinking its lines is now a conflict, as a collapsed curve is (Onshape keeps the lines, PL1d).

Every model is designed geometry; results are judged geometrically."""

import math
import unittest

import FreeCAD
import Part
import Sketcher

App = FreeCAD
V = App.Vector


def sweep(arc):
    return math.degrees(arc.LastParameter - arc.FirstParameter)


class TestSketchDatumAtScale(unittest.TestCase):
    """An arc centred on the origin, its start on the X axis, of radius r and Angle 270 degrees;
    the Angle is changed. Expected: the arc's sweep is the new Angle, its radius and start
    unchanged, the sketch valid with no warning."""

    def setUp(self):
        self.doc = App.newDocument("TestSketchDatumAtScale")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def arc(self, r, degrees=270, endOnYAxis=False):
        sk = self.doc.addObject("Sketcher::SketchObject", "Arc")
        a = sk.addGeometry(
            Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), r), 0, math.radians(degrees)),
            False,
        )
        sk.addConstraint(Sketcher.Constraint("Coincident", a, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", a, 1, -1))
        sk.addConstraint(Sketcher.Constraint("Radius", a, r))
        angle = sk.addConstraint(Sketcher.Constraint("Angle", a, math.radians(degrees)))
        if endOnYAxis:
            sk.addConstraint(Sketcher.Constraint("PointOnObject", a, 2, -2))
        self.doc.recompute()
        self.assertTrue(sk.isValid(), sk.getStatusString())
        return sk, a, angle

    def assertArc(self, sk, a, r, degrees):
        self.assertTrue(sk.isValid(), sk.getStatusString())
        self.assertNotIn("Warning", sk.State, sk.getStatusString())
        arc = sk.Geometry[a]
        self.assertAlmostEqual(sweep(arc), degrees, delta=1e-7)
        self.assertAlmostEqual(arc.Radius, r, delta=1e-7 * r)
        self.assertTrue(arc.StartPoint.isEqual(V(r, 0, 0), 1e-7 * r), arc.StartPoint)

    def testAngleChangedBySetDatum(self):
        for r in (40, 600, 4000):
            for start, to in ((270, 72), (72, 270), (270, 300), (100, 72)):
                with self.subTest(r=r, start=start, to=to):
                    sk, a, angle = self.arc(r, start)
                    sk.setDatum(angle, App.Units.Quantity(f"{to} deg"))
                    self.doc.recompute()
                    self.assertArc(sk, a, r, to)
                    self.doc.removeObject(sk.Name)

    def testAngleChangedByAnExpression(self):
        """The path of a #variable: the expression engine sets the value, the recompute solves."""
        sk, a, angle = self.arc(4000)
        sk.setExpression(f"Constraints[{angle}]", "72 deg")
        self.doc.recompute()
        self.assertArc(sk, a, 4000, 72)
        sk.setExpression(f"Constraints[{angle}]", "250 deg")
        self.doc.recompute()
        self.assertArc(sk, a, 4000, 250)

    def testLineAngleAtFourMetres(self):
        """A 4 m line from the origin, its end on an arc of r 4 m: Angle 60 -> 50 degrees."""
        sk = self.doc.addObject("Sketcher::SketchObject", "Line")
        r = 4000
        arc = sk.addGeometry(
            Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), r), 0, math.radians(90)), False
        )
        end = V(r * math.cos(math.radians(60)), r * math.sin(math.radians(60)), 0)
        line = sk.addGeometry(Part.LineSegment(V(0, 0, 0), end), False)
        sk.addConstraint(Sketcher.Constraint("Coincident", arc, 3, -1, 1))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", arc, 1, -1))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", arc, 2, -2))
        sk.addConstraint(Sketcher.Constraint("Radius", arc, r))
        sk.addConstraint(Sketcher.Constraint("Coincident", line, 1, -1, 1))
        sk.addConstraint(Sketcher.Constraint("PointOnObject", line, 2, arc))
        angle = sk.addConstraint(Sketcher.Constraint("Angle", line, math.radians(60)))
        self.doc.recompute()
        sk.setDatum(angle, App.Units.Quantity("50 deg"))
        self.doc.recompute()
        self.assertTrue(sk.isValid(), sk.getStatusString())
        self.assertNotIn("Warning", sk.State)
        seg = sk.Geometry[line]
        self.assertTrue(
            seg.EndPoint.isEqual(V(r * math.cos(math.radians(50)), r * math.sin(math.radians(50)), 0), 1e-6),
            seg.EndPoint,
        )

    def testAChangeThatConflictsStillDoes(self):
        """Control: the end on the Y axis allows only 90 or 270 degrees, so 72 conflicts. The
        continuation finds no solution either: the Angle is left out with a warning and the arc
        stays at 270 degrees, as before."""
        sk, a, angle = self.arc(4000, endOnYAxis=True)
        sk.setDatum(angle, App.Units.Quantity("72 deg"))
        self.doc.recompute()
        self.assertIn("Warning", sk.State)
        self.assertAlmostEqual(sweep(sk.Geometry[a]), 270, delta=1e-7)


class TestSketchAngleCycle(unittest.TestCase):
    """Three lines of 10 from the origin at 0, 30 and 90 degrees: L0 Horizontal, Angle(L0, L1) =
    30, Angle(L1, L2) = 60 + eps, Perpendicular(L0, L2). The cycle disagrees by eps degrees."""

    RUNS = 20

    def cycle(self, eps):
        doc = App.newDocument("TestSketchAngleCycle")
        try:
            sk = doc.addObject("Sketcher::SketchObject", "Cycle")
            lines = []
            for deg in (0, 30, 90):
                d = V(math.cos(math.radians(deg)), math.sin(math.radians(deg)), 0)
                lines.append(sk.addGeometry(Part.LineSegment(V(0, 0, 0), d * 10), False))
            sk.addConstraint(Sketcher.Constraint("Horizontal", lines[0]))
            sk.addConstraint(
                Sketcher.Constraint("Angle", lines[0], 1, lines[1], 1, math.radians(30))
            )
            sk.addConstraint(
                Sketcher.Constraint("Angle", lines[1], 1, lines[2], 1, math.radians(60 + eps))
            )
            sk.addConstraint(Sketcher.Constraint("Perpendicular", lines[0], lines[2]))
            doc.recompute()
            lengths = [sk.Geometry[i].length() for i in lines]
            return sk.isValid(), "Warning" in sk.State, min(lengths)
        finally:
            App.closeDocument(doc.Name)

    def testAHairsDisagreementIsAConflictEveryTime(self):
        """1e-5 degrees (1.7e-7 rad, over the 1e-7 bar): a conflict on every run, with a warning,
        and every line keeps its length (none is shrunk to meet the Perpendicular)."""
        for run in range(self.RUNS):
            with self.subTest(run=run):
                valid, warned, shortest = self.cycle(1e-5)
                self.assertTrue(valid)
                self.assertTrue(warned)
                self.assertGreater(shortest, 9.99)

    def testAgreementWithinTheBarSolves(self):
        """1e-6 degrees (1.7e-8 rad, under the bar): the cycle agrees; it solves with no warning
        and no line shrinks."""
        for run in range(self.RUNS):
            with self.subTest(run=run):
                valid, warned, shortest = self.cycle(1e-6)
                self.assertTrue(valid)
                self.assertFalse(warned)
                self.assertGreater(shortest, 9.99)

    def testALegitimateShrinkStaysSolved(self):
        """Control (review of the row 4 check): a 100 x 100 square turned 30 degrees, its corners
        Perpendicular, one side's length set to 0.1. The lines shrink 1000 times legitimately:
        the sketch solves with no warning, a 100 x 0.1 rectangle whose corners stay square."""
        doc = App.newDocument("TestSketchShrink")
        try:
            sk = doc.addObject("Sketcher::SketchObject", "Square")
            rot = App.Rotation(V(0, 0, 1), 30)
            pts = [rot.multVec(V(*p, 0)) for p in ((0, 0), (100, 0), (100, 100), (0, 100))]
            lines = [
                sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]), False) for i in range(4)
            ]
            for i in range(4):
                sk.addConstraint(Sketcher.Constraint("Coincident", lines[i], 2, lines[(i + 1) % 4], 1))
            for i in range(3):
                sk.addConstraint(Sketcher.Constraint("Perpendicular", lines[i], lines[i + 1]))
            sk.addConstraint(Sketcher.Constraint("Coincident", lines[0], 1, -1, 1))
            sk.addConstraint(Sketcher.Constraint("Angle", lines[0], math.radians(30)))
            sk.addConstraint(Sketcher.Constraint("Distance", lines[0], 100))
            side = sk.addConstraint(Sketcher.Constraint("Distance", lines[1], 100))
            doc.recompute()
            self.assertTrue(sk.isValid(), sk.getStatusString())
            sk.setDatum(side, App.Units.Quantity("0.1 mm"))
            doc.recompute()
            self.assertTrue(sk.isValid(), sk.getStatusString())
            self.assertNotIn("Warning", sk.State, sk.getStatusString())
            self.assertAlmostEqual(sk.Geometry[lines[0]].length(), 100, delta=1e-7)
            self.assertAlmostEqual(sk.Geometry[lines[1]].length(), 0.1, delta=1e-9)
            a = sk.Geometry[lines[0]].EndPoint - sk.Geometry[lines[0]].StartPoint
            b = sk.Geometry[lines[1]].EndPoint - sk.Geometry[lines[1]].StartPoint
            self.assertLess(abs(a.dot(b)) / (a.Length * b.Length), 1e-7)
        finally:
            App.closeDocument(doc.Name)

    def testAClearDisagreementIsAConflict(self):
        valid, warned, shortest = self.cycle(0.01)
        self.assertTrue(valid)
        self.assertTrue(warned)
        self.assertGreater(shortest, 9.99)


if __name__ == "__main__":
    unittest.main()
