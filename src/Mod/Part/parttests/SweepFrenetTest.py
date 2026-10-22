# SPDX-License-Identifier: LGPL-2.1-or-later

"""Part Sweep with Frenet on along spines whose curvature passes through zero inside an edge
(FreeCAD-CH, ops#421).

OCCT's Frenet normal points towards the centre of curvature, so it turns over at an inflection of a
planar wave, and MakePipeShell twisted the lateral face half a turn there: a self-intersecting
solid, reported valid, 1.3 mm off the tube and up to -58 % in volume. Lifted a few micrometres out
of its plane, the wave's frame turns half a turn within micrometres instead, with the same results.
The spines are designed: a planar wave x = 1.5 (1 - cos(2 pi z / 20)) (smallest radius of
curvature 6.75 mm, above the profile's 2 mm, so the tube doesn't fold), the same wave lifted along
Y by eps (z - 5)^3, a lead line and a corner before it, a B-spline that is planar around its
inflections and rises after them, and a Bezier curve with a flat point that doesn't reverse its
normal. A circle swept with its centre on the spine and its plane normal to it is the tube of
points at r from the spine, of volume A L (Pappus)."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector
R = 2.0
A = math.pi * R * R


def wave_edge(start=V(0, 0, 0), direction=V(0, 0, 1), side=V(1, 0, 0), waves=1, lift=0.0):
    """A cubic B-spline through the wave's points, every mm along `direction` from `start`, with
    the wave's offset along `side` (both in the XZ plane) and `lift` (z - 5)^3 along Y"""
    length = 20.0 * waves
    points = []
    for i in range(int(length) + 1):
        s = float(i)
        offset = side * (1.5 * (1 - math.cos(2 * math.pi * s / 20.0)))
        points.append(start + direction * s + offset + V(0, lift * (s - 5) ** 3, 0))
    curve = Part.BSplineCurve()
    curve.interpolate(points)
    return curve.toShape()


def corner_spine(angle=60.0, lead=30.0, waves=1):
    """A lead line up Z, then the wave after a corner of `angle` degrees in the XZ plane"""
    t = math.radians(angle)
    corner = V(0, 0, lead)
    direction = V(math.sin(t), 0, math.cos(t))
    side = V(math.cos(t), 0, -math.sin(t))
    return Part.Wire([Part.makeLine(V(0, 0, 0), corner), wave_edge(corner, direction, side, waves)])


def zigzag_spine():
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


def flat_point_spine(shift=0.0):
    """One degree-5 Bezier curve z = 20 t, x = 2e-4 (z - 10 - shift)^4, y = 1e-5 (z - 10 - shift)^5:
    its curvature is zero at z = 10 + shift, but its normal doesn't reverse there (fork PR 358
    round 1, R1: with the flat point at the edge's middle parameter, a sample, it was refused)"""
    c = 10.0 + shift

    def poles(coefficients):
        coefficients = list(coefficients) + [0.0] * (6 - len(coefficients))
        return [
            sum(math.comb(i, k) / math.comb(5, k) * coefficients[k] for k in range(i + 1))
            for i in range(6)
        ]

    x = poles([2e-4 * math.comb(4, j) * (-c) ** (4 - j) * 20**j for j in range(5)])
    y = poles([1e-5 * math.comb(5, j) * (-c) ** (5 - j) * 20**j for j in range(6)])
    z = poles([0.0, 20.0])
    curve = Part.BezierCurve()
    curve.setPoles([V(x[i], y[i], z[i]) for i in range(6)])
    return Part.Wire([curve.toShape()])


def start_frame(wire):
    edge = wire.Edges[0]
    return edge.valueAt(edge.FirstParameter), edge.tangentAt(edge.FirstParameter)


def circle_at_start(wire, radius=R):
    """A circle centred on the spine's start, normal to it there"""
    point, tangent = start_frame(wire)
    return Part.Wire([Part.makeCircle(radius, point, tangent)])


def rectangle_at_start(wire):
    """A 1 x 2 rectangle in the plane normal to the spine's start, beside the spine"""
    point, tangent = start_frame(wire)
    side = V(0, 1, 0) if abs(tangent.y) < 0.9 else V(1, 0, 0)
    side = (side - tangent * side.dot(tangent)).normalize()
    other = tangent.cross(side)
    corners = [
        point + side * a + other * b for a, b in ((0.5, -0.5), (2.5, -0.5), (2.5, 0.5), (0.5, 0.5))
    ]
    return Part.makePolygon(corners + [corners[0]])


def distance_from_tube(shape, spine, radius=R, samples=200):
    """The largest | distance from the spine - radius | over points of the shape's lateral faces"""
    worst = 0.0
    for face in shape.Faces:
        if face.Surface.TypeId not in ("Part::GeomBSplineSurface", "Part::GeomBezierSurface"):
            continue
        u0, u1, v0, v1 = face.ParameterRange
        for i in range(samples):
            v = v0 + (v1 - v0) * (i + 0.5) / samples
            for j in range(8):
                p = face.valueAt(u0 + (u1 - u0) * j / 8, v)
                worst = max(worst, abs(spine.distToShape(Part.Vertex(p))[0] - radius))
    return worst


class SweepFrenetTest(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SweepFrenetTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sweep(self, wire, profile=None, frenet=True):
        """A Part Sweep along `wire` of `profile` (a shape; by default a Part::Circle of radius R at
        the origin, normal to Z)"""
        spine = self.doc.addObject("Part::Feature", "Spine")
        spine.Shape = wire
        if profile is None:
            section = self.doc.addObject("Part::Circle", "Profile")
            section.Radius = R
        else:
            section = self.doc.addObject("Part::Feature", "Profile")
            section.Shape = profile
        sweep = self.doc.addObject("Part::Sweep", "Sweep")
        sweep.Sections = [section]
        sweep.Spine = (spine, ["Edge%d" % (i + 1) for i in range(len(wire.Edges))])
        sweep.Solid = True
        sweep.Frenet = frenet
        sweep.Transition = "Transformed"
        self.doc.recompute()
        return sweep

    def assertSound(self, shape):
        self.assertTrue(shape.isValid())
        shape.check(True)  # raises on BOP errors: the twisted face self-intersected

    def assertTube(self, wire, radius=R):
        """The Part Sweep of a circle normal to the spine's start is the tube"""
        sweep = self.sweep(wire, circle_at_start(wire, radius))
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        self.assertTrue(sweep.Shape.isValid())
        self.assertLess(distance_from_tube(sweep.Shape, wire, radius), 1e-3)
        return sweep

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
        solid had edge tolerances of about 10 mm; a constant binormal left 0.16 mm. The profile
        crosses the corner unturned, so after it the section is the circle sheared by 60 degrees:
        the volume is A (30 + cos 60 L), up to the overlap of the sheared sections where the wave
        bends (+0.5 % here, as Frenet off). The largest edge tolerance is 1e-4 on Windows and 1.6e-3
        on macOS (fork PR 358 round 1's CI)"""
        wire = corner_spine(waves=10)
        sweep = self.sweep(wire)
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        self.assertSound(sweep.Shape)
        self.assertLess(sweep.Shape.getTolerance(1), 1e-2)
        expected = A * (30.0 + math.cos(math.radians(60)) * wire.Edges[1].Length)
        self.assertAlmostEqual(sweep.Shape.Volume / expected, 1.0, delta=1e-2)

    def testFrenetAlongNearlyPlanarWaves(self):
        """The wave lifted out of its plane by micrometres: one wave lifted by 1e-8 (z - 5)^3 (34
        nm at most) and three waves lifted by 3e-8 (z - 5)^3 (5 um). The frame turns half a turn
        within nanometres; before, the tubes were 0.014 and 1.8 mm off (fork PR 358 round 1, R2)"""
        self.assertTube(Part.Wire([wave_edge(lift=1e-8)]))
        self.assertTube(Part.Wire([wave_edge(waves=3, lift=3e-8)]))

    def testFrenetTurnOverOffThePlane(self):
        """Where Frenet's frame turns over on a spine that isn't planar, no frame keeps Frenet's
        meaning. A circle about the spine sweeps the same surface in any frame: the tube. Any other
        profile would fold (a rectangle beside the lifted wave flipped to the other side): the sweep
        fails, saying where, and sweeps with Frenet off"""
        for wire in (zigzag_spine(), Part.Wire([wave_edge(lift=1e-2)])):
            self.assertTube(wire, 0.5)
            sweep = self.sweep(wire, rectangle_at_start(wire))
            self.assertFalse(sweep.isValid())
            self.assertIn("Frenet frame turns over", sweep.getStatusString())
            corrected = self.sweep(wire, rectangle_at_start(wire), frenet=False)
            self.assertTrue(corrected.isValid(), corrected.getStatusString())

    def testFrenetWithoutTurnOverIsUnchanged(self):
        """A planar arc, a helix and a Bezier curve with a flat point that doesn't reverse its
        normal (at a sample, and off it) keep OCCT's Frenet law: the tube, and the same solid as
        MakePipeShell's own Frenet mode"""
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
        for wire, radius in (
            (arc, R),
            (helix, R),
            (flat_point_spine(), 1.0),
            (flat_point_spine(0.37), 1.0),
        ):
            sweep = self.assertTube(wire, radius)
            pipe = Part.BRepOffsetAPI.MakePipeShell(wire)
            pipe.setFrenetMode(True)
            pipe.add(circle_at_start(wire, radius), False, False)
            pipe.build()
            pipe.makeSolid()
            self.assertAlmostEqual(sweep.Shape.Volume, pipe.shape().Volume, places=9)
            self.assertEqual(len(sweep.Shape.Faces), len(pipe.shape().Faces))


if __name__ == "__main__":
    unittest.main()
