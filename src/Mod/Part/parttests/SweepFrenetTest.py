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
inflections and rises after them, a Bezier curve with a flat point that doesn't reverse its
normal, a Bezier curve whose normal turns over within micrometres, a long lead line, the wave
and an arc leaving the wave's plane by 10 degrees, the waves turned off the main planes, and a
Part.makeHelix helix. A circle swept with its centre on the spine and
its plane normal to it is the tube of points at r from the spine, of volume A L (Pappus)."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector
R = 2.0
A = math.pi * R * R


def wave_edge(
    start=V(0, 0, 0), direction=V(0, 0, 1), side=V(1, 0, 0), waves=1, lift=0.0, rotation=None
):
    """A cubic B-spline through the wave's points, every mm along `direction` from `start`, with
    the wave's offset along `side` (both in the XZ plane) and `lift` (z - 5)^3 along Y, the points
    turned by `rotation` about the origin"""
    length = 20.0 * waves
    points = []
    for i in range(int(length) + 1):
        s = float(i)
        offset = side * (1.5 * (1 - math.cos(2 * math.pi * s / 20.0)))
        point = start + direction * s + offset + V(0, lift * (s - 5) ** 3, 0)
        points.append(rotation.multVec(point) if rotation else point)
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


def narrow_turn_spine(eps):
    """One cubic Bezier curve z = 20 t - 10, x = 0.01 z^3, y = eps z^2: its normal turns from -X to
    +X through +Y within about eps / 0.03 mm of z = 0, the edge's middle parameter (fork PR 358
    round 2's verification, finding 2: with a sample inside the turn, it went undetected)"""

    def poles(coefficients):
        coefficients = list(coefficients) + [0.0] * (4 - len(coefficients))
        return [
            sum(math.comb(i, k) / math.comb(3, k) * coefficients[k] for k in range(i + 1))
            for i in range(4)
        ]

    x = poles([0.01 * math.comb(3, j) * (-10.0) ** (3 - j) * 20**j for j in range(4)])
    y = poles([eps * math.comb(2, j) * (-10.0) ** (2 - j) * 20**j for j in range(3)])
    z = poles([-10.0, 20.0])
    curve = Part.BezierCurve()
    curve.setPoles([V(x[i], y[i], z[i]) for i in range(4)])
    return Part.Wire([curve.toShape()])


def leaving_plane_spine():
    """A 1000 mm lead line up Z, the planar wave (two inflections, in XZ), then an arc of radius 50
    mm turning 10 degrees towards +Y: within a thousandth of its size of the XZ plane, but its
    tangent leaves the plane by 10 degrees (fork PR 358 round 2's verification, finding 1)"""
    end = V(0, 0, 20)
    a = math.radians(10)
    arc = Part.Arc(
        end,
        end + V(0, 50 * (1 - math.cos(a / 2)), 50 * math.sin(a / 2)),
        end + V(0, 50 * (1 - math.cos(a)), 50 * math.sin(a)),
    )
    return Part.Wire([Part.makeLine(V(0, 0, -1000), V(0, 0, 0)), wave_edge(), arc.toShape()])


def s_curve_edge(ratio=30.0, width=0.02, count=300):
    """A planar S-curve in XY as one cubic B-spline through `count` points: its curvature runs
    -1 + (1 + 1 / ratio) (1 + tanh((s - s0) / width)) / 2 along the arc length s: -1 until the
    curve has turned by 120 degrees, then 1 / ratio the other way for 20 mm (or 60 degrees, if
    shorter). It passes through zero within about `width` of s0, between two of the sweep's
    samples (fork PR 358 round 6's verification, finding 1)"""
    a = 1.0
    b = a / ratio
    s0 = 2 * math.pi / 3 / a
    length = s0 + min(math.pi / 3 / b, 20.0)
    steps = 40000
    ds = length / steps
    x = y = angle = 0.0
    points = [V(0, 0, 0)]
    for i in range(steps):
        s = (i + 0.5) * ds
        angle += ((b - a) / 2 + (a + b) / 2 * math.tanh((s - s0) / width)) * ds
        x += math.cos(angle) * ds
        y += math.sin(angle) * ds
        if (i + 1) % (steps // count) == 0:
            points.append(V(x, y, 0))
    curve = Part.BSplineCurve()
    curve.interpolate(points)
    return curve.toShape()


def trimmed_s_curve_edge(share):
    """s_curve_edge() trimmed to start before its inflection by `share` of the sweep's first sample
    interval (8 per knot span): an inflection within a 64th of an interval from the end sample (fork
    PR 358 round 7's verification, finding 1)"""
    full = s_curve_edge()
    curve = full.Curve
    last = full.LastParameter

    def signed_curvature(u):
        d1 = full.derivative1At(u)
        d2 = full.derivative2At(u)
        return (d1.x * d2.y - d1.y * d2.x) / d1.Length**3

    # the inflection: where the curvature turns from -1 to positive
    steps = 4000
    us = [full.FirstParameter + (last - full.FirstParameter) * i / steps for i in range(steps + 1)]
    i = next(i for i in range(steps) if signed_curvature(us[i]) < 0 <= signed_curvature(us[i + 1]))
    below, above = us[i], us[i + 1]
    for _ in range(80):
        middle = (below + above) / 2
        if signed_curvature(middle) < 0:
            below = middle
        else:
            above = middle
    inflection = (below + above) / 2
    # the first interval depends on the start: a few fixed-point steps
    start = inflection
    for _ in range(10):
        spans = len([k for k in curve.getKnots() if start < k < last]) + 1
        start = inflection - share * (last - start) / max(64, 8 * spans)
    return Part.Edge(curve, start, last)


def bezier_cubic_edge(x0, x1):
    """y = x^3 in XY between x0 and x1 as a cubic Bezier curve, linear in x: its inflection is at
    x = 0"""
    curve = Part.BezierCurve()
    curve.setPoles(
        [
            V(x0, x0**3, 0),
            V((2 * x0 + x1) / 3, x0**2 * x1, 0),
            V((x0 + 2 * x1) / 3, x0 * x1**2, 0),
            V(x1, x1**3, 0),
        ]
    )
    return curve.toShape()


def arc_s_edge(radius=3.0, line=0.0):
    """Two tangent arcs in XY bending opposite ways, joined into one B-spline: radius 1 turning 120
    degrees, then `radius` turning 60 degrees back. The inflection is at an inner knot where the
    curve is only C1, and its curvature jumps from 1 to -1 / radius there (fork PR 358 round 6's
    verification, finding 2). With a `line` between them, of that length, the knots are C2 or C3
    at a line of 5e-6 to 3e-5 (round 7's verification, finding 2)"""
    first = Part.ArcOfCircle(
        Part.Circle(V(0, 1, 0), V(0, 0, 1), 1), -math.pi / 2, -math.pi / 2 + 2 * math.pi / 3
    )
    end = first.value(first.LastParameter)
    tangent = V(first.tangent(first.LastParameter)[0]).normalize()
    curve = first.toBSpline()
    if line > 0:
        curve.join(Part.LineSegment(end, end + tangent * line).toBSpline())
        end = end + tangent * line
    centre = end - V(-tangent.y, tangent.x, 0) * radius
    start = math.atan2(end.y - centre.y, end.x - centre.x)

    def at(angle):
        return centre + V(radius * math.cos(angle), radius * math.sin(angle), 0)

    second = Part.Arc(at(start), at(start - math.pi / 6), at(start - math.pi / 3))
    curve.join(second.toBSpline())
    return curve.toShape()


def helix_edge(pitch, height, radius, angle=0.0):
    """A right-handed helix about Z from (radius, 0, 0), on a cone of `angle` degrees widening
    upwards, as Part.makeHelix makes it, but as one B-spline of degree 6 continuous in its fourth
    derivative everywhere: one interval for the sweep's sampling, so 64 samples over the whole edge
    (6.4 a turn over ten turns, as makeHelix's curves gave before ops#447)"""
    turns = height / pitch
    count = int(64 * turns)
    points = []
    for i in range(count + 1):
        t = 2 * math.pi * turns * i / count
        z = height * i / count
        r = radius + z * math.tan(math.radians(angle))
        points.append(V(r * math.cos(t), r * math.sin(t), z))
    curve = Part.BSplineCurve()
    curve.approximate(Points=points, DegMin=6, DegMax=6, Continuity="C3", Tolerance=1e-6 * radius)
    return curve.toShape()


def rectangle_on_side(wire, side, scale):
    """A rectangle in the plane normal to the spine's start, `scale` (0.5 to 2.5) from the spine
    along `side` and `scale` (-0.5 to 0.5) across"""
    point, tangent = start_frame(wire)
    side = (side - tangent * side.dot(tangent)).normalize()
    other = tangent.cross(side)
    corners = [
        point + (side * a + other * b) * scale
        for a, b in ((0.5, -0.5), (2.5, -0.5), (2.5, 0.5), (0.5, 0.5))
    ]
    return Part.makePolygon(corners + [corners[0]])


def end_offset(shape, wire, axis):
    """The offset along `axis` of the end cap's centre of mass from the spine's end"""
    end = wire.OrderedVertexes[-1].Point
    caps = [face for face in shape.Faces if face.Surface.TypeId == "Part::GeomPlane"]
    cap = min(caps, key=lambda face: (face.CenterOfMass - end).Length)
    return (cap.CenterOfMass - end).dot(axis)


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

    def testFrenetNarrowTurnOnASample(self):
        """A turn of the normal so narrow that a sample lands inside it, half-way round, so that
        neither neighbouring pair of samples is more than a right angle apart. Off the plane (eps =
        1e-3) a circle about the spine gives the tube and a rectangle beside it is refused; nearly
        planar (eps = 1e-5), the rectangle beside the spine on +Y stays there. Before, both
        rectangles ended on the other side, -1.5 mm (fork PR 358 round 2's verification,
        finding 2)"""
        wire = narrow_turn_spine(1e-3)
        self.assertTube(wire, 0.5)
        sweep = self.sweep(wire, rectangle_at_start(wire))
        self.assertFalse(sweep.isValid())
        self.assertIn("Frenet frame turns over", sweep.getStatusString())

        wire = narrow_turn_spine(1e-5)
        sweep = self.sweep(wire, rectangle_at_start(wire))
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        self.assertAlmostEqual(end_offset(sweep.Shape, wire, V(0, 1, 0)), 1.5, delta=1e-3)
        self.assertSound(sweep.Shape)

    def testFrenetNearlyPlanarSpineLeavingItsPlane(self):
        """A spine within a thousandth of its size of a plane, whose tangent still leaves it by 10
        degrees. The plane's normal as a constant binormal tilts the sections there and swept the
        circle 1.5e-2 mm out of round, r (1 / cos 10 - 1). The circle gives the tube; a rectangle
        beside the spine is refused, as on the same spine without the lead line (fork PR 358 round
        2's verification, finding 1)"""
        wire = leaving_plane_spine()
        self.assertTube(wire, 1.0)
        sweep = self.sweep(wire, rectangle_at_start(wire))
        self.assertFalse(sweep.isValid())
        self.assertIn("Frenet frame turns over", sweep.getStatusString())

    def testFrenetLiftedWavesFailLoudly(self):
        """Ten waves lifted out of their plane by 1e-11 (z - 5)^3 (75 nm at most): OCCT's Frenet and
        corrected Frenet fail there, and the plane's normal as a constant binormal left vertices
        with tolerances of 0.15 mm and the tube 1.1e-2 mm off. The sweep fails, saying why, in Part
        Sweep and in Wire.makePipeShell (fork PR 358 round 2's verification, finding 1)"""
        wire = Part.Wire([wave_edge(waves=10, lift=1e-11)])
        sweep = self.sweep(wire, circle_at_start(wire))
        self.assertFalse(sweep.isValid())
        self.assertIn("Frenet frame turns over", sweep.getStatusString())
        with self.assertRaises(Part.OCCError):
            wire.makePipeShell([circle_at_start(wire)], True, True)

    def testFrenetPlanarWavesOffTheMainPlanes(self):
        """Ten exactly planar waves turned 45 degrees about X, as a sketch on a tilted plane: in
        place of Frenet, corrected Frenet left vertices with tolerances of 0.15 mm and the tube
        1.6e-2 mm off, where the same waves in XZ come out within 5e-5. The sweep gives the tube
        or fails, saying why (fork PR 358 round 3's verification, finding 1)"""
        wire = Part.Wire([wave_edge(waves=10, rotation=App.Rotation(V(1, 0, 0), 45.0))])
        sweep = self.sweep(wire, circle_at_start(wire))
        if sweep.isValid():
            self.assertLess(distance_from_tube(sweep.Shape, wire), 1e-3)
        else:
            self.assertIn("Frenet frame turns over", sweep.getStatusString())

    def assertFrenetHelix(self, pitch, height, radius, angle=0.0, make=Part.makeHelix):
        """A thread-like triangle beside a helix made by `make` (Part.makeHelix, or helix_edge()
        for one sampling interval), its tip pointing away from the axis, keeps OCCT's Frenet law:
        the same solid as MakePipeShell's own Frenet mode. Frenet's normal points to the centre of
        curvature, towards the axis, so the triangle stays outside: sliced normal to the helix a
        quarter, a half and three quarters of a turn into the first, second, middle and last turns,
        the section's centre of mass is 2/3 of the triangle's size from the helix against the
        curve's normal"""
        wire = Part.Wire([make(pitch, height, radius, angle)])
        point, tangent = start_frame(wire)
        # Away from the centre of curvature: from the axis, tilted on a steep cone
        radial = -wire.Edges[0].normalAt(wire.Edges[0].FirstParameter)
        other = tangent.cross(radial)
        size = min(0.1, radius / 10)
        corners = [point - other * size, point + radial * 2 * size, point + other * size]
        triangle = Part.makePolygon(corners + [corners[0]])
        sweep = self.sweep(wire, triangle)
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        edge = wire.Edges[0]
        turns = int(round(height / pitch))
        for turn in sorted({0, 1, turns // 2, turns - 1}):
            for fraction in (0.25, 0.5, 0.75):
                u = edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * (
                    turn + fraction
                ) / turns
                point = edge.valueAt(u)
                tangent = edge.tangentAt(u)
                outward = -edge.normalAt(u)
                centres = [
                    Part.Face(section).CenterOfMass
                    for section in sweep.Shape.slice(tangent, point.dot(tangent))
                ]
                centre = min(centres, key=lambda c: (c - point).Length)
                self.assertAlmostEqual(
                    (centre - point).dot(outward) / size, 2 / 3, delta=0.1, msg="at %s" % point
                )
        pipe = Part.BRepOffsetAPI.MakePipeShell(wire)
        pipe.setFrenetMode(True)
        pipe.add(triangle, False, False)
        pipe.build()
        pipe.makeSolid()
        self.assertAlmostEqual(sweep.Shape.Volume, pipe.shape().Volume, places=9)
        self.assertEqual(len(sweep.Shape.Faces), len(pipe.shape().Faces))

    def testFrenetAlongAHelixWithoutSampling(self):
        """A helix sampled 6.4 times a turn (helix_edge(), as Part.makeHelix's curves were before
        ops#447): neighbouring normals 56 degrees apart, two apart 113, while the frame turns about
        the tangent by 1 degree. Before, the sweep was refused, saying the frame turns over (fork
        PR 358 round 3's verification, finding 2)"""
        self.assertFrenetHelix(2.0, 20.0, 10.0, make=helix_edge)

    def testFrenetAlongASteepHelix(self):
        """A steep helix's Frenet frame really turns about the tangent, by 360 c / sqrt(r^2 + c^2)
        degrees a turn (c = pitch / 2 pi): 249 degrees at a pitch of 6 r, 343 at 20 r. Sampled 6.4
        times a turn, neighbouring frames are 41 to 56 degrees apart and two apart 92 to 112, a
        steady twist and not a turn-over. Before, both sweeps were refused (fork PR 358 round 4's
        verification, finding 1)"""
        self.assertFrenetHelix(6.0, 60.0, 1.0)
        self.assertFrenetHelix(20.0, 200.0, 1.0)

    def testFrenetAlongALongSteepHelix(self):
        """A helix of 100 turns at a pitch of 100 times its radius: the frame twists by 360 degrees
        a turn. Part.makeHelix makes it of 128 even knot spans, continuous only in the tangent at
        the knots, sampled about 10 times a turn (36 degrees apart), so the edge is sampled again
        more densely. Until ops#447 it made 30 spans, the last of them half the helix, where the
        curve strayed from it, and the frame jumped by 47 degrees at the knot before it, with its
        curvature steady. Before, that was taken for a turn-over and the spine for a planar one,
        and the triangle beside it was swept in corrected Frenet: a half turn on, it was on the
        axis's side (fork PR 358 round 5's verification, finding 1)"""
        self.assertFrenetHelix(10.0, 1000.0, 0.1)

    def testFrenetAlongASteepConicalHelix(self):
        """Steep helices on cones of 3 and 5 degrees, sampled 6.4 times a turn (helix_edge()): the
        frame twists fast where the cone is narrow and steep, by up to 52 and 74 degrees between
        neighbouring samples and by more than a right angle two apart there, with the curvature
        steady, and by 9 to 14 degrees along the rest, so the edge isn't sampled again. Before,
        that was taken for a turn-over, and they were refused (fork PR 358 round 5's verification,
        finding 2)"""
        self.assertFrenetHelix(10.0, 100.0, 1.0, 3.0, make=helix_edge)
        self.assertFrenetHelix(10.0, 100.0, 1.0, 5.0, make=helix_edge)

    def testFrenetAlongAFewTurnsOfASteepConicalHelix(self):
        """Ten turns at a pitch of 100 times the radius on a cone of 3 degrees, sampled 6.4 times a
        turn (helix_edge()): the curvature rises from the edge's start along the cone, where a turn
        of the frame is flagged with no samples before it. Before, that was read as a dip, and the
        sweep was refused (fork PR 358 round 6's verification, finding 3)"""
        self.assertFrenetHelix(100.0, 1000.0, 1.0, 3.0, make=helix_edge)

    def assertStaysOnItsSide(self, edge):
        """A rectangle beside a planar spine in XY, on its +Z side, its binormal's: the spine's
        Frenet frame turns over at the inflection, and the rectangle stays on +Z"""
        wire = Part.Wire([edge])
        sweep = self.sweep(wire, rectangle_on_side(wire, V(0, 0, 1), 0.02))
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        self.assertGreater(sweep.Shape.BoundBox.ZMin, 0)

    def testFrenetInflectionBetweenSamples(self):
        """An S-curve whose curvature passes through zero between two samples, with 0.0714 and
        0.0585 on either side and a median of 0.0503 after them: the lowest curvature is looked for
        between the samples. Before, the inflection was missed, and the rectangle beside the spine
        flipped to -0.22 (fork PR 358 round 6's verification, finding 1)"""
        self.assertStaysOnItsSide(s_curve_edge())

    def testFrenetInflectionAtAKnot(self):
        """Two tangent arcs bending opposite ways, joined into one B-spline: the curvature jumps
        from 1 to -1/3 at a knot instead of dipping, and the normals on either side of it are half
        a turn apart. Before, the inflection was missed, and the rectangle beside the spine flipped
        to -0.20 (fork PR 358 round 6's verification, finding 2)"""
        self.assertStaysOnItsSide(arc_s_edge())

    def testFrenetInflectionNextToAnEndSample(self):
        """Inflections within a 64th of a sample interval from an edge's end sample: y = x^3 from
        x = -1.5627e-4 to 1 and from -1 to 1.5627e-4, and the S-curve trimmed to start 0.01 and
        0.003 of an interval before its inflection. The end sample was the nearest of the even
        steps to the zero of the curvature, so the lowest curvature was the end's, which isn't a
        dip; the point where the frame turns over is now looked for too. Before, the rectangle
        beside the spine flipped to -0.22, -0.14 and -0.17 (fork PR 358 round 7's verification,
        finding 1)"""
        self.assertStaysOnItsSide(bezier_cubic_edge(-1.5627e-4, 1.0))
        self.assertStaysOnItsSide(bezier_cubic_edge(-1.0, 1.5627e-4))
        for share in (0.01, 0.003):
            self.assertStaysOnItsSide(trimmed_s_curve_edge(share))

    def testFrenetInflectionAcrossAShortLine(self):
        """Two tangent arcs bending opposite ways with a line of 1e-5 between them, joined into one
        B-spline: its knots are C2 and C3, so the normal's jump there isn't looked at, and the
        curvature crosses zero between the even steps. Before, the inflection was missed, and the
        rectangle beside the spine flipped to -0.19 (fork PR 358 round 7's verification, finding
        2)"""
        self.assertStaysOnItsSide(arc_s_edge(line=1e-5))

    def testFrenetWithoutTurnOverIsUnchanged(self):
        """A planar arc, a helix and a Bezier curve with a flat point that doesn't reverse its
        normal (at a sample, and off it) keep OCCT's Frenet law: the tube, and the same solid as
        MakePipeShell's own Frenet mode (with the sweep's degree and segments, ops#448)"""
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
            pipe.setMaxDegree(14)
            pipe.setMaxSegments(1000)
            pipe.add(circle_at_start(wire, radius), False, False)
            pipe.build()
            pipe.makeSolid()
            self.assertAlmostEqual(sweep.Shape.Volume, pipe.shape().Volume, places=9)
            self.assertEqual(len(sweep.Shape.Faces), len(pipe.shape().Faces))


class SweepApproximationTest(unittest.TestCase):
    """Part Sweep with Frenet off (corrected Frenet) along planar waves whose plane isn't one of
    the main planes, as on a sketch attached to a tilted plane (ops#448, ops#440). At OCCT's
    default degree and segments the approximation of the swept surface depended on the rounding
    noise of the orientation: the same ten waves came out within 8e-7 mm of the tube in XZ, but
    1.9e-2 mm off when turned 45 degrees about X, or failed to build; two and three tilted waves
    failed to build. A circle centred on the spine and normal to it sweeps the tube, as in
    SweepFrenetTest."""

    def setUp(self):
        self.doc = App.newDocument("SweepApproximationTest")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    sweep = SweepFrenetTest.sweep

    def assertTubeFrenetOff(self, wire):
        sweep = self.sweep(wire, circle_at_start(wire), frenet=False)
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        self.assertNotIn("Warning", sweep.getStatusString())
        self.assertTrue(sweep.Shape.isValid())
        self.assertLess(distance_from_tube(sweep.Shape, wire), 1e-4)
        return sweep

    def testLongPlanarWavesOffTheMainPlanes(self):
        """Ten waves (200 spans) in XZ, then their points turned 45 degrees about X and 37 degrees
        about (1, 2, 3) before the interpolation, and the XZ spine turned 45 degrees about X by the
        spine object's placement. Before, the tubes were 1.9e-2 and 1.6e-4 mm off with vertex
        tolerances of 0.15 and 5.4e-3 mm, and the placed spine failed ("command not done"); now
        each is the XZ sweep turned: the tube, vertex tolerances of 5e-5 and the same volume. The
        volume is compared with the XZ sweep's, since Shape.Volume's default integration is itself
        0.3 % off on such long sweeps (ops#414)"""
        control = self.assertTubeFrenetOff(Part.Wire([wave_edge(waves=10)]))
        self.assertLess(control.Shape.getTolerance(1), 1e-3)
        placed = Part.Wire([wave_edge(waves=10)])
        placed.rotate(V(), V(1, 0, 0), 45.0)
        for wire in (
            Part.Wire([wave_edge(waves=10, rotation=App.Rotation(V(1, 0, 0), 45.0))]),
            Part.Wire([wave_edge(waves=10, rotation=App.Rotation(V(1, 2, 3), 37.0))]),
            placed,
        ):
            sweep = self.assertTubeFrenetOff(wire)
            self.assertLess(sweep.Shape.getTolerance(1), 1e-3)
            self.assertAlmostEqual(sweep.Shape.Volume / control.Shape.Volume, 1.0, delta=1e-5)

    def testTiltedWaves(self):
        """ops#440's tilted waves: two waves in a plane turned 37 degrees about (1, 2, 3) and three
        turned 45 degrees about X (40 and 60 spans). Before, both failed to build ("command not
        done"); now they are the tube"""
        self.assertTubeFrenetOff(
            Part.Wire([wave_edge(waves=2, rotation=App.Rotation(V(1, 2, 3), 37.0))])
        )
        self.assertTubeFrenetOff(
            Part.Wire([wave_edge(waves=3, rotation=App.Rotation(V(1, 0, 0), 45.0))])
        )

    def testLooseResultWarns(self):
        """A profile whose edges and vertices have a tolerance of 0.5 mm makes the sweep's own as
        loose: the sweep builds, with a warning naming the tolerance"""
        wire = Part.Wire([wave_edge()])
        profile = circle_at_start(wire)
        profile.fixTolerance(0.5)
        sweep = self.sweep(wire, profile, frenet=False)
        self.assertTrue(sweep.isValid(), sweep.getStatusString())
        self.assertGreaterEqual(sweep.Shape.getTolerance(1), 0.5)
        self.assertIn("Warning", sweep.getStatusString())
        self.assertIn("tolerance of 0.5", sweep.getStatusString())


if __name__ == "__main__":
    unittest.main()
