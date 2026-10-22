# SPDX-License-Identifier: LGPL-2.1-or-later

"""Part Sweep with Frenet on along spines whose curvature passes through zero inside an edge
(FreeCAD-CH, ops#421).

OCCT's Frenet normal points towards the centre of curvature, so it turns over at an inflection of a
planar wave, and MakePipeShell twisted the lateral face half a turn there: a self-intersecting
solid, reported valid, 1.3 mm off the tube and up to -58 % in volume. The spines are designed: a
planar wave x = 1.5 (1 - cos(2 pi z / 20)) (smallest radius of curvature 6.75 mm, above the
profile's 2 mm, so the tube doesn't fold), a lead line and a corner before it, and a B-spline that
is planar around its inflections and leaves the plane further on. A circle swept with its centre on
the spine and its plane normal to it is the tube of points at r from the spine, of volume A L
(Pappus)."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector
R = 2.0
A = math.pi * R * R


def wave_edge(start=V(0, 0, 0), direction=V(0, 0, 1), side=V(1, 0, 0), waves=1, step=1.0):
    """A cubic B-spline through the wave's points, every `step` mm along `direction` from `start`,
    with the wave's offset along `side` (both in the XZ plane)."""
    length = 20.0 * waves
    n = int(round(length / step))
    points = []
    for i in range(n + 1):
        s = length * i / n
        points.append(start + direction * s + side * (1.5 * (1 - math.cos(2 * math.pi * s / 20.0))))
    curve = Part.BSplineCurve()
    curve.interpolate(points)
    return curve.toShape()


def corner_spine(angle=60.0, lead=30.0, waves=1):
    """A lead line up Z, then the wave after a corner of `angle` degrees in the XZ plane."""
    t = math.radians(angle)
    corner = V(0, 0, lead)
    direction = V(math.sin(t), 0, math.cos(t))
    side = V(math.cos(t), 0, -math.sin(t))
    return Part.Wire([Part.makeLine(V(0, 0, 0), corner), wave_edge(corner, direction, side, waves)])


def off_plane_spine():
    """A cubic B-spline whose first three spans have their poles in the XZ plane and zigzag, so its
    curvature passes through zero there, and whose last two spans rise along Y"""
    poles = [
        V(0, 0, 0),
        V(0, 0, 5),
        V(3, 0, 10),
        V(0, 0, 15),
        V(-3, 0, 20),
        V(0, 0, 25),
        V(0, 6, 30),
        V(0, 12, 35),
    ]
    curve = Part.BSplineCurve()
    curve.buildFromPolesMultsKnots(poles, [4, 1, 1, 1, 1, 4], [0, 1, 2, 3, 4, 5], False, 3)
    return Part.Wire([curve.toShape()])


def distance_from_tube(shape, spine, samples=200):
    """The largest | distance from the spine - R | over points of the shape's lateral faces"""
    worst = 0.0
    for face in shape.Faces:
        if face.Surface.TypeId != "Part::GeomBSplineSurface":
            continue
        u0, u1, v0, v1 = face.ParameterRange
        for i in range(samples):
            v = v0 + (v1 - v0) * (i + 0.5) / samples
            for j in range(8):
                p = face.valueAt(u0 + (u1 - u0) * j / 8, v)
                worst = max(worst, abs(spine.distToShape(Part.Vertex(p))[0] - R))
    return worst


class SweepFrenetTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SweepFrenetTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sweep(self, wire, frenet=True, radius=R):
        spine = self.doc.addObject("Part::Feature", "Spine")
        spine.Shape = wire
        circle = self.doc.addObject("Part::Circle", "Profile")
        circle.Radius = radius
        sweep = self.doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [circle]
        sweep.Spine = (spine, ["Edge%d" % (i + 1) for i in range(len(wire.Edges))])
        sweep.Solid = True
        sweep.Frenet = frenet
        sweep.Transition = "Transformed"
        self.doc.recompute()
        return sweep

    def assertSound(self, shape):
        self.assertTrue(shape.isValid())
        shape.check(True)  # raises on BOP errors: the twisted face self-intersected

    def testFrenetThroughInflectionsFollowsTheTube(self):
        """A planar wave with two inflections, as one edge: the Part Sweep and Wire.makePipeShell
        give the tube"""
        wire = Part.Wire([wave_edge()])
        sweep = self.sweep(wire)
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        self.assertSound(sweep.Shape)
        self.assertLess(distance_from_tube(sweep.Shape, wire), 1e-3)
        self.assertAlmostEqual(sweep.Shape.Volume / (A * wire.Length), 1.0, delta=1e-4)

        shape = wire.makePipeShell([Part.Wire([Part.makeCircle(R)])], True, True)
        self.assertSound(shape)
        self.assertLess(distance_from_tube(shape, wire), 1e-3)

    def testFrenetAfterCornerIsSound(self):
        """The issue's spine: a lead line, a 60-degree corner, 10 waves (200 spans). Before, the
        solid had edge tolerances of about 10 mm; a constant binormal, the same frame, left 0.16 mm.
        On a planar spine Frenet's frame, kept continuous, is the corrected Frenet one"""
        wire = corner_spine(waves=10)
        frenet = self.sweep(wire, frenet=True)
        corrected = self.sweep(wire, frenet=False)
        self.assertTrue(frenet.isValid(), frenet.getStatusString())
        self.assertSound(frenet.Shape)
        self.assertLess(frenet.Shape.getTolerance(1), 1e-3)
        self.assertAlmostEqual(frenet.Shape.Volume / corrected.Shape.Volume, 1.0, delta=1e-9)

    def testFrenetWithoutTurnOverIsUnchanged(self):
        """A planar arc, a helix and a wave that leaves its plane keep OCCT's Frenet law: the same
        solid as MakePipeShell's own Frenet mode"""
        t = math.radians(60)
        arc = Part.Wire(
            [
                Part.Arc(
                    V(0, 0, 0),
                    V(10 * (1 - math.cos(t / 2)), 0, 10 * math.sin(t / 2)),
                    V(10 * (1 - math.cos(t)), 0, 10 * math.sin(t)),
                ).toShape()
            ]
        )
        helix = Part.Wire(Part.makeHelix(10.0, 30.0, 6.0).Edges)
        points = [
            V(1.5 * (1 - math.cos(2 * math.pi * z / 20)), 0.01 * (z - 5) ** 3, z) for z in range(21)
        ]
        lifted = Part.BSplineCurve()
        lifted.interpolate(points)
        for wire in (arc, helix, Part.Wire([lifted.toShape()])):
            sweep = self.sweep(wire)
            pipe = Part.BRepOffsetAPI.MakePipeShell(wire)
            pipe.setFrenetMode(True)
            pipe.add(Part.Wire([Part.makeCircle(R)]), False, False)
            pipe.build()
            pipe.makeSolid()
            self.assertAlmostEqual(sweep.Shape.Volume, pipe.shape().Volume, places=9)
            self.assertEqual(len(sweep.Shape.Faces), len(pipe.shape().Faces))

    def testFrenetTurnOverOffThePlaneIsRefused(self):
        """Where Frenet's frame turns over on a spine that isn't planar, no frame keeps it: the
        sweep fails, saying where"""
        sweep = self.sweep(off_plane_spine(), radius=0.5)
        self.assertFalse(sweep.isValid())
        self.assertIn("Frenet frame turns over", sweep.getStatusString())
        # Frenet off sweeps it
        corrected = self.sweep(off_plane_spine(), frenet=False, radius=0.5)
        self.assertTrue(corrected.isValid(), corrected.getStatusString())


if __name__ == "__main__":
    unittest.main()
