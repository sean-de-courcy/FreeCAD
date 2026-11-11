# SPDX-License-Identifier: LGPL-2.1-or-later
# **************************************************************************
#   Copyright (c) 2026 FreeCAD-CH contributors                             *
#                                                                          *
#   This file is part of the FreeCAD CAx development system.               *
#                                                                          *
#   This library is free software; you can redistribute it and/or          *
#   modify it under the terms of the GNU Library General Public            *
#   License as published by the Free Software Foundation; either           *
#   version 2 of the License, or (at your option) any later version.       *
#                                                                          *
#   This library  is distributed in the hope that it will be useful,       *
#   but WITHOUT ANY WARRANTY; without even the implied warranty of         *
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the          *
#   GNU Library General Public License for more details.                   *
# **************************************************************************

"""Onshape's Curve pattern (FreeCAD-CH ops#655, T6), on designed geometry.

The model: a slab z -2..0 under everything, and the seed, a 10 mm cube x 45..55, y -5..5,
z 0..10, standing on it. The path is a sketch on the XY plane. Each instance is the seed moved by
the motion that takes the path's frame at its start (the point, the tangent, the sketch's normal)
to the frame at the instance's arc length; instances are equally spaced by arc length, the first
the seed, and a closed path shares its whole length among them. Each test states the expected
instances as placements of the seed, and checks that the result holds every expected cube whole,
holds nothing else (its volume), and that skipped instances are absent.
"""

import math
import unittest

import FreeCAD
import Part
from FreeCAD import Placement, Rotation, Vector

SLAB = 260.0 * 260.0 * 2.0
CUBE = 1000.0
SEED = Vector(45, -5, 0)


class TestCurvePattern(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestCurvePattern")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        slab = self.Doc.addObject("PartDesign::AdditiveBox", "Slab")
        self.Body.addObject(slab)
        slab.Length = 260
        slab.Width = 260
        slab.Height = 2
        slab.AttachmentOffset = Placement(Vector(-110, -110, -2), Rotation())
        slab.Placement = Placement(Vector(-110, -110, -2), Rotation())
        self.Seed = self.Doc.addObject("PartDesign::AdditiveBox", "Seed")
        self.Body.addObject(self.Seed)
        self.Seed.Length = 10
        self.Seed.Width = 10
        self.Seed.Height = 10
        self.Seed.AttachmentOffset = Placement(SEED, Rotation())
        self.Seed.Placement = Placement(SEED, Rotation())
        self.Doc.recompute()
        self.assertAlmostEqual(self.Seed.Shape.Volume, SLAB + CUBE, places=3)

    def tearDown(self):
        FreeCAD.closeDocument("PartDesignTestCurvePattern")

    # -- the model's pieces -------------------------------------------------------------------

    def sketch(self, *geometry):
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Path")
        self.Body.addObject(sketch)
        for geo in geometry:
            sketch.addGeometry(geo, False)
        self.Doc.recompute()
        return sketch

    def pattern(self, path, subs, count, **props):
        pattern = self.Doc.addObject("PartDesign::CurvePattern", "CurvePattern")
        self.Body.addObject(pattern)
        pattern.Originals = [self.Seed]
        pattern.Path = (path, subs)
        pattern.Occurrences = count
        pattern.Refine = False
        for name, value in props.items():
            setattr(pattern, name, value)
        self.Doc.recompute()
        return pattern

    @staticmethod
    def frameMotion(p0, angle0, p, angle):
        """The planar motion taking the frame at p0 (tangent at angle0, in degrees) to the frame
        at p (tangent at angle): x' = p + R(angle - angle0) (x - p0)."""
        return Placement(p - p0, Rotation(Vector(0, 0, 1), angle - angle0), p0)

    @staticmethod
    def cube(placement):
        box = Part.makeBox(10, 10, 10, SEED)
        return box.transformGeometry(placement.toMatrix())

    def assertInstances(self, pattern, placements, absent=()):
        """The result is the slab plus the cubes at `placements`, each whole; none at `absent`."""
        self.assertTrue(pattern.isValid(), pattern.getStatusString())
        shape = pattern.Shape
        self.assertAlmostEqual(shape.Volume, SLAB + CUBE * len(placements), delta=1e-2)
        for index, placement in enumerate(placements):
            with self.subTest(instance=index):
                common = shape.common(self.cube(placement)).Volume
                self.assertAlmostEqual(common, CUBE, delta=1e-2)
        for index, placement in enumerate(absent):
            with self.subTest(absent=index):
                self.assertLess(shape.common(self.cube(placement)).Volume, 1e-2)

    # -- the paths -------------------------------------------------------------------------------

    def testLineTranslates(self):
        """A line (20,0)-(80,0), 3 instances: the seed, +30, +60 along x."""
        path = self.sketch(Part.LineSegment(Vector(20, 0, 0), Vector(80, 0, 0)))
        pattern = self.pattern(path, ["Edge1"], 3)
        self.assertInstances(pattern, [Placement(Vector(30 * k, 0, 0), Rotation()) for k in range(3)])

    def testLineReversed(self):
        """Reversed runs from (80,0): the instances go -30 and -60 along x."""
        path = self.sketch(Part.LineSegment(Vector(20, 0, 0), Vector(80, 0, 0)))
        pattern = self.pattern(path, ["Edge1"], 3, Reversed=True)
        self.assertInstances(pattern, [Placement(Vector(-30 * k, 0, 0), Rotation()) for k in range(3)])

    def testWholeSketchIsItsEdges(self):
        """A sketch picked whole is the path of its edges."""
        path = self.sketch(Part.LineSegment(Vector(20, 0, 0), Vector(80, 0, 0)))
        pattern = self.pattern(path, [], 3)
        self.assertInstances(pattern, [Placement(Vector(30 * k, 0, 0), Rotation()) for k in range(3)])

    def testArcFollowsTangent(self):
        """A quarter arc about the origin, (50,0) to (0,50), 3 instances: the seed turned 0, 45
        and 90 degrees about the arc's centre (the tangent turns as the radius does)."""
        arc = Part.ArcOfCircle(Part.Circle(Vector(0, 0, 0), Vector(0, 0, 1), 50), 0, math.pi / 2)
        path = self.sketch(arc)
        pattern = self.pattern(path, ["Edge1"], 3)
        self.assertInstances(
            pattern,
            [Placement(Vector(), Rotation(Vector(0, 0, 1), 45 * k)) for k in range(3)],
        )

    def testArcKeepOrientation(self):
        """Keep orientation: the seed only moves, by the arc's points' offsets from its start."""
        arc = Part.ArcOfCircle(Part.Circle(Vector(0, 0, 0), Vector(0, 0, 1), 50), 0, math.pi / 2)
        path = self.sketch(arc)
        pattern = self.pattern(path, ["Edge1"], 3, Orientation="Keep orientation")
        start = Vector(50, 0, 0)
        points = [Vector(50 * math.cos(a), 50 * math.sin(a), 0) for a in (0, math.pi / 4, math.pi / 2)]
        self.assertInstances(pattern, [Placement(p - start, Rotation()) for p in points])

    def testClosedCircleSharesItsLength(self):
        """A closed circle of radius 50, 4 instances: 90 degrees apart, none on the seed."""
        path = self.sketch(Part.Circle(Vector(0, 0, 0), Vector(0, 0, 1), 50))
        pattern = self.pattern(path, ["Edge1"], 4)
        self.assertInstances(
            pattern,
            [Placement(Vector(), Rotation(Vector(0, 0, 1), 90 * k)) for k in range(4)],
        )

    def testSplineEqualArcLength(self):
        """A spline through (20,0) (40,20) (60,0) (80,20), 4 instances: at equal arc lengths,
        each turned by its tangent's angle from the start tangent's."""
        spline = Part.BSplineCurve()
        spline.interpolate([Vector(20, 0, 0), Vector(40, 20, 0), Vector(60, 0, 0), Vector(80, 20, 0)])
        path = self.sketch(spline)
        pattern = self.pattern(path, ["Edge1"], 4)
        edge = path.Shape.Edges[0]
        frames = []
        for k in range(4):
            u = edge.getParameterByLength(edge.Length * k / 3)
            t = edge.tangentAt(u)
            frames.append((edge.valueAt(u), math.degrees(math.atan2(t.y, t.x))))
        p0, a0 = frames[0]
        self.assertInstances(pattern, [self.frameMotion(p0, a0, p, a) for p, a in frames])

    def testChainTurnsAtTheCorner(self):
        """Two lines (20,0)-(80,0) and (80,0)-(80,40), picked last first: one chain of length 100,
        5 instances 25 apart; past the corner the seed is turned 90 degrees, as the tangent is."""
        path = self.sketch(
            Part.LineSegment(Vector(20, 0, 0), Vector(80, 0, 0)),
            Part.LineSegment(Vector(80, 0, 0), Vector(80, 40, 0)),
        )
        pattern = self.pattern(path, ["Edge2", "Edge1"], 5)
        p0 = Vector(20, 0, 0)
        expected = [
            self.frameMotion(p0, 0, Vector(20, 0, 0), 0),
            self.frameMotion(p0, 0, Vector(45, 0, 0), 0),
            self.frameMotion(p0, 0, Vector(70, 0, 0), 0),
            self.frameMotion(p0, 0, Vector(80, 15, 0), 90),
            self.frameMotion(p0, 0, Vector(80, 40, 0), 90),
        ]
        self.assertInstances(pattern, expected)

    # -- Skip, and the errors ------------------------------------------------------------------

    def testSkip(self):
        """Skip 1: the seed and instance 2 are made, instance 1 isn't; 0 (the seed) can't be skipped."""
        path = self.sketch(Part.LineSegment(Vector(20, 0, 0), Vector(80, 0, 0)))
        pattern = self.pattern(path, ["Edge1"], 3, SkippedInstances=[0, 1])
        self.assertInstances(
            pattern,
            [Placement(Vector(), Rotation()), Placement(Vector(60, 0, 0), Rotation())],
            absent=[Placement(Vector(30, 0, 0), Rotation())],
        )

    def testCountOneIsTheSeed(self):
        path = self.sketch(Part.LineSegment(Vector(20, 0, 0), Vector(80, 0, 0)))
        pattern = self.pattern(path, ["Edge1"], 1)
        self.assertInstances(pattern, [Placement()])

    def testNoPathFails(self):
        pattern = self.Doc.addObject("PartDesign::CurvePattern", "CurvePattern")
        self.Body.addObject(pattern)
        pattern.Originals = [self.Seed]
        self.Doc.recompute()
        self.assertFalse(pattern.isValid())
        self.assertIn("Select a path", pattern.getStatusString())

    def testDisconnectedEdgesFail(self):
        """Two edges with a gap between them are no chain: a loud error, not a pattern."""
        path = self.sketch(
            Part.LineSegment(Vector(20, 0, 0), Vector(40, 0, 0)),
            Part.LineSegment(Vector(60, 0, 0), Vector(80, 0, 0)),
        )
        pattern = self.pattern(path, ["Edge1", "Edge2"], 3)
        self.assertFalse(pattern.isValid())
        self.assertIn("connected chain", pattern.getStatusString())

    def testBranchFails(self):
        """Three edges meeting at one point are no chain."""
        path = self.sketch(
            Part.LineSegment(Vector(20, 0, 0), Vector(50, 0, 0)),
            Part.LineSegment(Vector(50, 0, 0), Vector(80, 0, 0)),
            Part.LineSegment(Vector(50, 0, 0), Vector(50, 30, 0)),
        )
        pattern = self.pattern(path, [], 3)
        self.assertFalse(pattern.isValid())
        self.assertIn("connected chain", pattern.getStatusString())


if __name__ == "__main__":
    unittest.main()
