# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Loft connections as Onshape's (ops#640, notes/loft-connections.md).
#
# Designed geometry only. A connection joins one vertex of the profile to one vertex of the section. The expected values
# are Onshape's where the oracle measured them (GB12g, notes/onshape-facts.md) and otherwise closed forms: a two-profile
# loft between polygons with the same vertex count is ruled between paired vertices, so its section at height t is the
# polygon of the interpolated vertices, its area is quadratic in t and Simpson's rule gives the volume exactly.

import math
import unittest

import FreeCAD
import Part

from PartDesignTests.Scenarios import models

App = FreeCAD
V = App.Vector
H = 30.0
S = 10 * math.sqrt(0.5)  # the turned square 10's corner distance from its centre


def square(side):
    h = side / 2
    return models.rectangle(-h, -h, h, h)


def turnedSquare(side):
    """A square of the side turned 45 degrees: corners on the axes."""
    r = side * math.sqrt(0.5)
    return models.polygon([(r, 0), (0, r), (-r, 0), (0, -r)])


def ruledVolume(bottom, top, height=H):
    """The ruled loft's volume between two polygons whose vertices pair in order."""

    def area(points):
        n = len(points)
        return 0.5 * sum(points[i][0] * points[(i + 1) % n][1] - points[(i + 1) % n][0] * points[i][1] for i in range(n))

    def at(t):
        return area([((1 - t) * p[0] + t * q[0], (1 - t) * p[1] + t * q[1]) for p, q in zip(bottom, top)])

    return height * (at(0) + 4 * at(0.5) + at(1)) / 6


def ruledByArcLength(bottom, top, height=H, n=400):
    """The ruled loft's volume between two loops of edges paired in order, points paired by arc length on each edge
    pair (bottom, top: Part geometries in traversal order)."""
    a, b = [], []
    for e, f in zip(bottom, top):
        a += [(p.x, p.y) for p in e.toShape().discretize(Number=n + 1)[:-1]]
        b += [(p.x, p.y) for p in f.toShape().discretize(Number=n + 1)[:-1]]
    return ruledVolume(a, b, height)


ONSHAPE_SURFACE = 0.002
"""Onshape's surface between a paired arc and line is not ruled by arc length: its V and A differ by about 0.1 % (LC1:
-0.72 and -5.19 on ~4800) while the joins and the faces agree; the fork's loft is the arc-length ruled model."""


class ConnectionCase(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PartDesignTestLoftConnections")
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def loft(self, bottom, top, connections=(), height=H, **properties):
        """bottom, top: sketch geometry; connections: ((x, y) on the bottom, (x, y) on the top) pairs."""
        self.profile = models.sketch(self.doc, "Bottom", bottom, self.body)
        self.section = models.sketch(self.doc, "Top", top, self.body, z=height)
        self.doc.recompute()
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = self.profile
        loft.Sections = [self.section]
        self.connect(loft, connections)
        for name, value in properties.items():
            setattr(loft, name, value)
        self.doc.recompute()
        return loft

    def vertexName(self, sketch, xy):
        for i, vertex in enumerate(sketch.Shape.Vertexes, 1):
            if (vertex.Point - sketch.Placement.multVec(V(xy[0], xy[1], 0))).Length < 1e-6:
                return "Vertex%d" % i
        self.fail("no vertex of %s at %s" % (sketch.Name, xy))

    def connect(self, loft, connections):
        links = []
        for a, b in connections:
            links.append((self.profile, self.vertexName(self.profile, a)))
            links.append((self.section, self.vertexName(self.section, b)))
        loft.Connections = links

    def assertLoft(self, loft, volume, area=None, faces=None, delta=0.02, areaDelta=None):
        self.assertTrue(loft.isValid(), loft.getStatusString())
        shape = loft.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, delta=delta)
        if area is not None:
            self.assertAlmostEqual(shape.Area, area, delta=areaDelta or delta)
        if faces is not None:
            self.assertEqual(len(shape.Faces), faces)

    def assertNearOnshape(self, loft, volume, area):
        shape = loft.Shape
        self.assertAlmostEqual(shape.Volume, volume, delta=ONSHAPE_SURFACE * volume)
        self.assertAlmostEqual(shape.Area, area, delta=ONSHAPE_SURFACE * area)

    def assertJoined(self, loft, a, b, height=H, straight=True):
        """The loft has a side edge from (a, 0) to (b, height): the connected vertices are joined."""
        p, q = V(a[0], a[1], 0), V(b[0], b[1], height)
        for edge in loft.Shape.Edges:
            ends = [v.Point for v in edge.Vertexes]
            if len(ends) != 2:
                continue
            if {(ends[0] - p).Length < 1e-6, (ends[1] - q).Length < 1e-6} == {True} or {
                (ends[1] - p).Length < 1e-6,
                (ends[0] - q).Length < 1e-6,
            } == {True}:
                if straight:
                    self.assertAlmostEqual(edge.Length, (q - p).Length, delta=1e-6)
                return
        self.fail("no side edge joins %s to %s" % (a, b))

    def assertBilinearSides(self, loft, sides=4):
        """The side faces are the ruled surface itself: bilinear patches (degree 1 by 1, 2 x 2 poles). With the
        volume this pins the geometry; OCCT's default area integration reads a patch twisted by 135 degrees about
        0.02 high (324.302 where a fine integration gives 324.281), so the twisted areas carry a wider delta."""
        patches = [f for f in loft.Shape.Faces if f.Surface.TypeId != "Part::GeomPlane"]
        self.assertEqual(len(patches), sides)
        for face in patches:
            surface = face.Surface
            self.assertEqual((surface.UDegree, surface.VDegree, surface.NbUPoles, surface.NbVPoles), (1, 1, 2, 2))

    def assertStops(self, loft, *words):
        self.assertFalse(loft.isValid(), "expected a stop")
        message = loft.getStatusString()
        for word in words:
            self.assertIn(word.lower(), message.lower(), message)


class TestLoftConnectionsTwist(ConnectionCase):
    """Square 20 at z 0 to square 10 turned 45 degrees at z 30 (GB12g)."""

    BOTTOM = [(10, 10), (-10, 10), (-10, -10), (10, -10)]

    def top(self, degrees):
        """The top corners in the bottom's order, the first at `degrees`."""
        return [
            (S * math.cos(math.radians(degrees + 90 * i)), S * math.sin(math.radians(degrees + 90 * i)))
            for i in range(4)
        ]

    def twisted(self, degrees):
        return self.loft(square(20), turnedSquare(10), [((10, 10), self.top(degrees)[0])])

    def testConnectionsDefaultToNone(self):
        loft = self.loft(square(20), turnedSquare(10))
        self.assertEqual(loft.Connections, [])
        self.assertLoft(loft, 6414.2136, 2252.6702, 6)

    def testFortyFiveDegreesEitherWayIsTheDefault(self):
        for degrees in (0, 90):
            with self.subTest(degrees=degrees):
                loft = self.twisted(degrees)
                self.assertLoft(loft, 6414.2136, 2252.6702, 6)
                self.assertJoined(loft, (10, 10), self.top(degrees)[0])
                self.tearDown()
                self.setUp()

    def testOppositeCornerTwistsAHundredThirtyFive(self):
        loft = self.twisted(180)
        self.assertLoft(loft, 3585.7864, 1797.1225, 6, areaDelta=0.1)
        self.assertBilinearSides(loft)
        self.assertJoined(loft, (10, 10), (-S, 0))
        self.assertAlmostEqual(ruledVolume(self.BOTTOM, self.top(180)), 3585.7864, delta=1e-4)

    def testTheOtherOppositeCornerMirrors(self):
        loft = self.twisted(270)
        self.assertLoft(loft, 3585.7864, 1797.1225, 6, areaDelta=0.1)
        self.assertBilinearSides(loft)
        self.assertJoined(loft, (10, 10), (0, -S))

    def testTwoConnectionsThatAgree(self):
        top = self.top(180)
        loft = self.loft(square(20), turnedSquare(10), [((10, 10), top[0]), ((-10, -10), top[2])])
        self.assertLoft(loft, 3585.7864, 1797.1225, 6, areaDelta=0.1)
        self.assertBilinearSides(loft)

    def testFourConnectionsThatAgree(self):
        top = self.top(180)
        loft = self.loft(square(20), turnedSquare(10), list(zip(self.BOTTOM, top)))
        self.assertLoft(loft, 3585.7864, 1797.1225, 6, areaDelta=0.1)
        self.assertBilinearSides(loft)

    def testCrossedConnectionsStop(self):
        # two connections always keep one cyclic order; three can cross: bottom corners 0, 1, 2 to top 0, 2, 1
        top = self.top(180)
        pairs = [((10, 10), top[0]), ((-10, 10), top[2]), ((-10, -10), top[1])]
        loft = self.loft(square(20), turnedSquare(10), pairs)
        self.assertStops(loft, "connection")

    def testTwoCrossedConnectionsStop(self):
        """Oracle 14 LC4: (10, 10) -> (-7.07, 0) and (-10, 10) -> (7.07, 0), Onshape's LOFT_INVALID."""
        loft = self.loft(square(20), turnedSquare(10), [((10, 10), (-S, 0)), ((-10, 10), (S, 0))])
        self.assertStops(loft, "connection")

    def testAVertexConnectedTwiceStops(self):
        top = self.top(180)
        loft = self.loft(square(20), turnedSquare(10), [((10, 10), top[0]), ((10, 10), top[1])])
        self.assertStops(loft, "connection")

    def testBothEndsOnOneProfileStop(self):
        loft = self.loft(square(20), turnedSquare(10))
        loft.Connections = [(self.profile, "Vertex1"), (self.profile, "Vertex2")]
        self.doc.recompute()
        self.assertStops(loft, "connection")

    def testAVertexOffTheProfileStops(self):
        geometry = square(20) + [Part.Point(V(3, 3, 0))]
        loft = self.loft(geometry, turnedSquare(10))
        loft.Connections = [(self.profile, self.vertexName(self.profile, (3, 3))), (self.section, "Vertex1")]
        self.doc.recompute()
        self.assertStops(loft, "connection")

    def testSquareToSquareQuarterTurn(self):
        """Square 20 to square 20, corner (10, 10) to (-10, 10): a 90 degree twist, V 8000 by the closed form."""
        top = self.BOTTOM[1:] + self.BOTTOM[:1]
        loft = self.loft(square(20), square(20), [((10, 10), (-10, 10))])
        self.assertAlmostEqual(ruledVolume(self.BOTTOM, top), 8000.0, delta=1e-9)
        self.assertLoft(loft, 8000.0, 2848.143703, 6)  # oracle 14 LC5
        self.assertJoined(loft, (10, 10), (-10, 10))

    def testSubtractiveLoftCutsTheTwist(self):
        """A REMOVE loft (the team's well cuts): a 40 cube from z -5 minus the 135 degree loft."""
        self.profile = models.sketch(self.doc, "Bottom", square(20), self.body)
        self.section = models.sketch(self.doc, "Top", turnedSquare(10), self.body, z=H)
        block = self.body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length = block.Width = 40
        block.Height = H
        block.Placement = App.Placement(V(-20, -20, 0), App.Rotation())
        self.doc.recompute()
        cut = self.body.newObject("PartDesign::SubtractiveLoft", "Cut")
        cut.Profile = self.profile
        cut.Sections = [self.section]
        self.connect(cut, [((10, 10), (-S, 0))])
        self.doc.recompute()
        self.assertTrue(cut.isValid(), cut.getStatusString())
        self.assertAlmostEqual(cut.Shape.Volume, 40 * 40 * H - 3585.7864, delta=0.02)

    def testConnectionsWithStartNormal(self):
        loft = self.loft(square(20), turnedSquare(10), [((10, 10), (-S, 0))], StartCondition="Normal to profile")
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), 6)
        self.assertJoined(loft, (10, 10), (-S, 0), straight=False)

    def testConnectionFollowsASketchEdit(self):
        loft = self.twisted(180)
        models.moveRectangle(self.profile, -11, -11, 11, 11)
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertJoined(loft, (11, 11), (-S, 0))
        bottom = [(11, 11), (-11, 11), (-11, -11), (11, -11)]
        self.assertAlmostEqual(loft.Shape.Volume, ruledVolume(bottom, self.top(180)), delta=0.02)

    def testConnectionsSurviveSaveAndLoad(self):
        import os
        import tempfile

        loft = self.twisted(180)
        path = os.path.join(tempfile.mkdtemp(), "connections.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        loft = self.doc.getObject("Loft")
        self.assertEqual(len(loft.Connections), 2)
        self.doc.recompute()
        self.assertAlmostEqual(loft.Shape.Volume, 3585.7864, delta=0.02)


class TestLoftConnectionsUnequal(ConnectionCase):
    """The team's shapes in their simplest form. Where the profiles' vertex counts differ, the split is FreeCAD's
    (arc length between connections, notes/loft-connections.md) until the oracle answers; the tests check only what the
    geometry fixes: the result is one valid solid and a straight side edge joins each connected pair."""

    # 6 edges: a 20 x 12 rectangle with its two right corners rounded r 3 (4 lines, 2 arcs)
    def sixEdges(self):
        g = models.polyline([(7, 6), (-10, 6), (-10, -6), (7, -6)])
        g.append(Part.ArcOfCircle(Part.Circle(V(7, -3, 0), V(0, 0, 1), 3), -math.pi / 2, 0))
        g.append(Part.LineSegment(V(10, -3, 0), V(10, 3, 0)))
        g.append(Part.ArcOfCircle(Part.Circle(V(7, 3, 0), V(0, 0, 1), 3), 0, math.pi / 2))
        return g

    RECT = staticmethod(lambda: models.rectangle(-6, -4, 6, 4))

    def testSixEdgesCornerToCornerIsOnshapesDefault(self):
        """Oracle 14 LC1: (-10, -6) -> (-6, -4) is Onshape's default; the arc ends take the rectangle's thirds."""
        loft = self.loft(self.sixEdges(), self.RECT(), [((-10, -6), (-6, -4))])
        self.assertJoined(loft, (10, -3), (6, -4 / 3))
        self.assertJoined(loft, (10, 3), (6, 4 / 3))
        g = self.sixEdges()  # (7, 6) -> (-10, 6), left, bottom, arc, right, arc
        L = lambda p, q: Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
        y = 4 / 3
        top = [L((6, 4), (-6, 4)), L((-6, 4), (-6, -4)), L((-6, -4), (6, -4)), L((6, -4), (6, -y)), L((6, -y), (6, y))]
        top.append(L((6, y), (6, 4)))
        self.assertLoft(loft, ruledByArcLength(g, top), faces=8)
        self.assertNearOnshape(loft, 4811.584195, 1847.092629)  # oracle 14 LC1

    def testSixEdgesArcEndToACorner(self):
        """Oracle 14 LC1: (10, -3) -> (6, -4); the leftovers take their edges' midpoints."""
        loft = self.loft(self.sixEdges(), self.RECT(), [((10, -3), (6, -4))])
        self.assertJoined(loft, (7, -6), (0, -4))
        self.assertJoined(loft, (10, 3), (6, 0))
        g = self.sixEdges()  # (7, 6) -> (-10, 6), left, bottom, arc, right, arc
        L = lambda p, q: Part.LineSegment(V(p[0], p[1], 0), V(q[0], q[1], 0))
        top = [L((6, 4), (-6, 4)), L((-6, 4), (-6, -4)), L((-6, -4), (0, -4)), L((0, -4), (6, -4)), L((6, -4), (6, 0))]
        top.append(L((6, 0), (6, 4)))
        self.assertLoft(loft, ruledByArcLength(g, top), faces=8)
        self.assertNearOnshape(loft, 4781.672715, 1841.389255)  # oracle 14 LC1

    def testSixEdgesHalfTurnStops(self):
        """Oracle 14 LC1: (-10, -6) -> (6, 4) is a half-turn wrap, Onshape's LOFT_INVALID."""
        loft = self.loft(self.sixEdges(), self.RECT(), [((-10, -6), (6, 4))])
        self.assertStops(loft, "connection")

    def testEightEdgesToARectangleFourConnections(self):
        # oracle 14 LC2: Onshape builds V 4751.303503, A 1799.865681, F 8: 6 side faces, the rounded corners' arc ends
        # (7, +-6) unmatched (a side face spans the arc and the line against the rectangle's top or bottom edge), the
        # chamfer vertices (-10, +-4) to (-6, +-4/3) (ops#1046: no plane beside the arc ends under the conditions).
        # 8 edges: a 20 x 12 rectangle with the right corners rounded r 3 and the left corners cut 2 x 2 (6 lines, 2 arcs)
        g = models.polyline([(7, 6), (-8, 6), (-10, 4), (-10, -4), (-8, -6), (7, -6)])
        g.append(Part.ArcOfCircle(Part.Circle(V(7, -3, 0), V(0, 0, 1), 3), -math.pi / 2, 0))
        g.append(Part.LineSegment(V(10, -3, 0), V(10, 3, 0)))
        g.append(Part.ArcOfCircle(Part.Circle(V(7, 3, 0), V(0, 0, 1), 3), 0, math.pi / 2))
        pairs = [((-8, 6), (-6, 4)), ((-8, -6), (-6, -4)), ((10, -3), (6, -4)), ((10, 3), (6, 4))]
        loft = self.loft(
            g,
            models.rectangle(-6, -4, 6, 4),
            pairs,
            StartCondition="Normal to profile",
            EndCondition="Normal to profile",
        )
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), 8)
        self.assertNearOnshape(loft, 4751.303503, 1799.865681)
        for a, b in pairs:
            self.assertJoined(loft, a, b, straight=False)

    def testEightLinesToARectangleFourConnections(self):
        """LC2 with all four corners cut 2 x 2 (8 lines, sharp joints) and no end conditions: each chain's extra vertices
        divide the rectangle's edge equally (LC1, LC2), and the loft is the ruled model."""
        g = models.polygon([(8, 6), (-8, 6), (-10, 4), (-10, -4), (-8, -6), (8, -6), (10, -4), (10, 4)])
        pairs = [((-8, 6), (-6, 4)), ((-8, -6), (-6, -4)), ((10, -4), (6, -4)), ((10, 4), (6, 4))]
        loft = self.loft(g, models.rectangle(-6, -4, 6, 4), pairs)
        y = 4 / 3
        extra = [((8, 6), (0, 4)), ((-10, 4), (-6, y)), ((-10, -4), (-6, -y)), ((8, -6), (0, -4))]
        for a, b in pairs + extra:
            self.assertJoined(loft, a, b)
        bottom = [(8, 6), (-8, 6), (-10, 4), (-10, -4), (-8, -6), (8, -6), (10, -4), (10, 4)]
        top = [(0, 4), (-6, 4), (-6, y), (-6, -y), (-6, -4), (0, -4), (6, -4), (6, 4)]
        self.assertLoft(loft, ruledVolume(bottom, top), faces=10)

    def slotAndRoundedRectangle(self):
        # bottom: a slot, lines y = +-5 from x -10..10, half circles r 5 (4 edges); top: a 16 x 8 rectangle with
        # corners rounded r 2 (8 edges)
        slot = [
            Part.LineSegment(V(-10, -5, 0), V(10, -5, 0)),
            Part.ArcOfCircle(Part.Circle(V(10, 0, 0), V(0, 0, 1), 5), -math.pi / 2, math.pi / 2),
            Part.LineSegment(V(10, 5, 0), V(-10, 5, 0)),
            Part.ArcOfCircle(Part.Circle(V(-10, 0, 0), V(0, 0, 1), 5), math.pi / 2, 3 * math.pi / 2),
        ]
        rounded = models.polyline([(-6, -4), (6, -4)]) + models.polyline([(8, -2), (8, 2)])
        rounded += models.polyline([(6, 4), (-6, 4)]) + models.polyline([(-8, 2), (-8, -2)])
        for cx, cy, a0 in ((6, -2, -90), (6, 2, 0), (-6, 2, 90), (-6, -2, 180)):
            rounded.append(
                Part.ArcOfCircle(Part.Circle(V(cx, cy, 0), V(0, 0, 1), 2), math.radians(a0), math.radians(a0 + 90))
            )
        return slot, rounded

    def testSlotToARoundedRectangleStopsAtTangentJoints(self):
        # oracle 14 LC3: Onshape builds this, leaving the tangent joints unmatched (V 5831.449304,
        # A 2131.481057, F 6; side edges (10, 5) -> (6, 4), (-10, -5) -> (-6, -4), (10, -5) -> (6, -4),
        # (0, 5) -> (-6, 4)). No chain-local rule gives that answer (ops#1046 D): a stop until the oracle rows land.
        slot, rounded = self.slotAndRoundedRectangle()
        loft = self.loft(slot, rounded, [((10, 5), (6, 4)), ((-10, -5), (-6, -4))])
        self.assertStops(loft, "tangent")

    def testSlotToARoundedRectangleOneConnection(self):
        # oracle 14 LC3, one connection (10, 5) -> (6, 4): V 5923.449580, A 2149.140963, F 6 in Onshape: the four
        # edges where the flat sides end stay, each half circle's side is one face against arc, line, arc
        slot, rounded = self.slotAndRoundedRectangle()
        loft = self.loft(slot, rounded, [((10, 5), (6, 4))])
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), 6)
        self.assertNearOnshape(loft, 5923.449580, 2149.140963)
        for a, b in (((10, 5), (6, 4)), ((-10, 5), (-6, 4)), ((-10, -5), (-6, -4)), ((10, -5), (6, -4))):
            self.assertJoined(loft, a, b)


class TestLoftConnectionsSplitLines(ConnectionCase):
    """ops#729, its exact part: a vertex that only splits a straight line in two is no corner to match. Between two
    connections the bottom runs line, arc, line, line, the last two collinear (the vertex (0, 5) splits the line
    (5, 5) -> (-10, 5)); the top runs line, arc, line with tangent joints. Merged, both are line, arc, line, and the
    split line's partner (2, 4) -> (-6, 4) is parallel to it, so the side face between them is one plane wherever the
    split vertex pairs: the solid is the one of the unsplit bottom, which pairs edge for edge."""

    PAIRS = [((-10, -5), (-6, -4)), ((-10, 5), (-6, 4))]

    def bottom(self, split=(0, 5), end=(-10, 5)):
        g = models.polyline([end, (-10, -5), (5, -5)])
        g.append(Part.ArcOfCircle(Part.Circle(V(5, 0, 0), V(0, 0, 1), 5), -math.pi / 2, math.pi / 2))
        g += models.polyline([(5, 5), split, end] if split else [(5, 5), end])
        return g

    def top(self):
        g = models.polyline([(-6, 4), (-6, -4), (2, -4)])
        g.append(Part.ArcOfCircle(Part.Circle(V(2, 0, 0), V(0, 0, 1), 4), -math.pi / 2, math.pi / 2))
        g += models.polyline([(2, 4), (-6, 4)])
        return g

    def testASplitLineIsNoCorner(self):
        # unsplit, the chains have equal edge counts and pair edge for edge (this builds without the fix)
        whole = self.loft(self.bottom(split=None), self.top(), self.PAIRS)
        self.assertLoft(whole, ruledByArcLength(self.bottom(split=None), self.top()))
        volume, area = whole.Shape.Volume, whole.Shape.Area
        self.body = models.body(self.doc)
        split = self.loft(self.bottom(), self.top(), self.PAIRS)
        self.assertLoft(split, volume, area=area, delta=1e-6)
        # the split vertex pairs a third of the way along the top line, from (2, 4)
        self.assertJoined(split, (0, 5), (2 - 8 / 3, 4))
        for a, b in self.PAIRS + [((5, -5), (2, -4)), ((5, 5), (2, 4))]:
            self.assertJoined(split, a, b)

    def testASkewPartnerMergesTheSplit(self):
        # the split line runs (5, 5) -> (-10, 6): not parallel to the top line (2, 4) -> (-6, 4), so no side face
        # beside the split vertex is a plane and its side edge goes (ops#1046's rule): one side face spans the split
        # line against the top line, and the top line keeps no vertex for it
        loft = self.loft(self.bottom(split=(0, 5 + 1 / 3), end=(-10, 6)), self.top(), [((-10, -5), (-6, -4)), ((-10, 6), (-6, 4))])
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertTrue(loft.Shape.isValid())
        self.assertEqual(len(loft.Shape.Solids), 1)
        split = V(0, 5 + 1 / 3, 0)
        for edge in loft.Shape.Edges:
            ends = [v.Point for v in edge.Vertexes]
            if len(ends) == 2 and abs(ends[0].z - ends[1].z) > H - 1e-6:
                self.assertTrue(all((p - split).Length > 1e-6 for p in ends), "a side edge at the split vertex")
        for vertex in loft.Shape.Vertexes:
            self.assertFalse(abs(vertex.Point.z - H) < 1e-6 and abs(vertex.Point.y - 4) < 1e-6
                             and -6 + 1e-6 < vertex.Point.x < 2 - 1e-6, "a new vertex on the top line")


class TestLoftTangentRuns(ConnectionCase):
    """ops#1046: chains of different edge counts between connections, with tangent joints (sk1126's rows, Onshape's
    answers RB44/RB47, notes/onshape-facts.md). Vertices match by arc-length fraction, leftovers by equal division; a
    side edge with both ends smooth (a tangent joint or a new vertex inside an edge) stays only where a planar side face
    ends on it, otherwise one side face spans the run and the new vertex is gone (notes/loft-tangent-joints-1046.md).

    Profiles: A at z 0 from the left corner (-20, 10), B at z 30 from (-12, 6); a span from the left corner to the right
    corner, then the right side down, the bottom and the left side (S3t: its right side runs (15, 0) to (20, -10))."""

    C30 = math.cos(math.radians(30))

    @staticmethod
    def arc(c, r, a0, a1):
        lo, hi = sorted((a0, a1))
        return Part.ArcOfCircle(Part.Circle(V(c[0], c[1], 0), V(0, 0, 1), r), math.radians(lo), math.radians(hi))

    def spanA(self, name):
        """A's span: (geometry, right corner, the right side's bottom end)."""
        if name == "S1":
            return models.polyline([(-20, 10), (20, 10)]), (20, 10), (20, -10)
        if name == "S2s":
            return models.polyline([(-20, 10), (0, 14), (20, 10)]), (20, 10), (20, -10)
        if name == "S2t":
            e = (10 + 10 * self.C30, 5)
            return models.polyline([(-20, 10), (10, 10)]) + [self.arc((10, 0), 10, 90, 30)], e, (e[0], -10)
        if name == "S3s":
            return models.polyline([(-20, 10), (-8, 14), (8, 14), (20, 10)]), (20, 10), (20, -10)
        if name == "S3m":
            e = (10 + 10 * self.C30, 9)
            return models.polyline([(-20, 10), (-8, 14), (10, 14)]) + [self.arc((10, 4), 10, 90, 30)], e, (e[0], -10)
        if name == "S3t":
            g = models.polyline([(-20, 10), (10, 10)]) + [self.arc((10, 5), 5, 90, 0)] + models.polyline([(15, 5), (15, 0)])
            return g, (15, 0), (20, -10)
        raise ValueError(name)

    def spanB(self, name):
        if name == "S1":
            return models.polyline([(-12, 6), (12, 6)]), (12, 6), (12, -6)
        if name == "S2s":
            return models.polyline([(-12, 6), (0, 9), (12, 6)]), (12, 6), (12, -6)
        if name == "S2t":
            e = (6 + 6 * self.C30, 3)
            return models.polyline([(-12, 6), (6, 6)]) + [self.arc((6, 0), 6, 90, 30)], e, (e[0], -6)
        raise ValueError(name)

    def row(self, a, b, connections="2c", extra=(), **properties):
        sa, ea, ba = self.spanA(a)
        sb, eb, bb = self.spanB(b)
        A = sa + models.polyline([ea, ba, (-20, -10), (-20, 10)])
        B = sb + models.polyline([eb, bb, (-12, -6), (-12, 6)])
        self.corners = [((-20, 10), (-12, 6)), (ea, eb), ((-20, -10), (-12, -6)), (ba, bb)]
        pairs = [] if connections == "0c" else self.corners[:2] + (self.corners[2:] if connections == "4c" else [])
        return self.loft(A, B, pairs + list(extra), **properties)

    def sideEdges(self, loft, height=H):
        res = []
        for e in loft.Shape.Edges:
            zs = sorted(v.Point.z for v in e.Vertexes)
            if len(zs) == 2 and abs(zs[0]) < 1e-6 and abs(zs[1] - height) < 1e-6:
                res.append(e)
        return res

    def assertRow(self, loft, faces, volume, area, extra, straight=True):
        self.assertTrue(loft.isValid(), loft.getStatusString())
        shape = loft.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(len(shape.Faces), faces)
        self.assertNearOnshape(loft, volume, area)
        expected = self.corners + list(extra)
        self.assertEqual(len(self.sideEdges(loft)), len(expected), [tuple(v.Point for v in e.Vertexes) for e in self.sideEdges(loft)])
        for a, b in expected:
            self.assertJoined(loft, a, b, straight=straight)

    def assertNoVertexAt(self, loft, xy, z=H):
        p = V(xy[0], xy[1], z)
        for v in loft.Shape.Vertexes:
            self.assertGreater((v.Point - p).Length, 1e-4, "a vertex at %s" % (xy,))

    def assertRoundTrip(self, loft):
        import os
        import tempfile

        before = (len(loft.Shape.Faces), loft.Shape.Volume)
        name = loft.Name
        path = os.path.join(tempfile.mkdtemp(), "tangent-runs.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        loft = self.doc.getObject(name)
        loft.touch()
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), before[0])
        self.assertAlmostEqual(loft.Shape.Volume, before[1], delta=1e-6 * before[1])

    # rows A's group: the joints pair one to one or a sharp vertex takes a new partner; every side edge stays
    def testRow1TangentJointsOnBothChains(self):
        loft = self.row("S3m", "S2t")
        self.assertRow(loft, 8, 16588.334755, 4043.865441, [((-8, 14), (-3, 6)), ((10, 14), (6, 6))])

    def testRow3TangentJointOnTheShorterChain(self):
        loft = self.row("S3s", "S2t")
        self.assertRow(loft, 8, 16842.832261, 4103.876271, [((-8, 14), (-3, 6)), ((8, 14), (6, 6))])

    def testRow7RoundedEndAgainstOneEdge(self):
        loft = self.row("S2t", "S1")
        self.assertRow(loft, 7, 15090.177832, 3874.203534, [((10, 10), (0, 6))])

    def testRow18FourConnections(self):
        loft = self.row("S3m", "S2t", "4c")
        self.assertRow(loft, 8, 16588.33491, 4043.865475, [((-8, 14), (-3, 6)), ((10, 14), (6, 6))])

    def testRow20NormalToProfileKeepsSharpToTangent(self):
        loft = self.row("S3s", "S2t", StartCondition="Normal to profile", EndCondition="Normal to profile")
        self.assertRow(loft, 8, 17059.789228, 4119.612117, [((-8, 14), (-3, 6)), ((8, 14), (6, 6))], straight=False)

    def testRow21TangentJointsConnectedByHand(self):
        loft = self.row("S3m", "S2t", extra=[((10, 14), (6, 6))])
        self.assertRow(loft, 8, 16588.33491, 4043.865475, [((-8, 14), (-3, 6)), ((10, 14), (6, 6))])

    def testRows15To17And23Unchanged(self):
        for a, b, faces, volume, area, extra in (
            ("S2t", "S2t", 7, 14908.015301, 3820.907058, [((10, 10), (6, 6))]),
            ("S2t", "S2s", 7, 15758.561505, 3920.606202, [((10, 10), (0, 9))]),
            ("S2s", "S2t", 7, 16391.309314, 4055.750412, [((0, 14), (6, 6))]),
            ("S3s", "S1", 8, 17120.0, 4165.960772, [((-8, 14), (-4, 6)), ((8, 14), (4, 6))]),
        ):
            with self.subTest(a=a, b=b):
                self.assertRow(self.row(a, b), faces, volume, area, extra)
                self.tearDown()
                self.setUp()

    # rows B + C's group: a smooth-smooth side edge with no plane beside it goes, one face spans the run
    def testRow5LeftoverTangentJointGetsNoEdge(self):
        loft = self.row("S3m", "S2s")
        self.assertRow(loft, 7, 17510.305981, 4142.190099, [((-8, 14), (0, 9))])
        self.assertNoVertexAt(loft, (6, 7.5))
        self.assertRoundTrip(loft)

    def testRow8NormalToProfileDropsTheJoint(self):
        loft = self.row("S2t", "S1", StartCondition="Normal to profile", EndCondition="Normal to profile")
        self.assertRow(loft, 6, 15236.904857, 3885.03611, [], straight=False)
        self.assertNoVertexAt(loft, (0, 6))

    def testRow10RoundedCornerAgainstOneEdge(self):
        loft = self.row("S3t", "S1")
        self.assertRow(loft, 7, 14334.72272, 3782.144556, [((10, 10), (-4, 6))])
        self.assertNoVertexAt(loft, (4, 6))

    def testRow12TwoTangentJointsAgainstOneSharp(self):
        loft = self.row("S3t", "S2s")
        self.assertRow(loft, 7, 15087.551194, 3840.974099, [((10, 10), (0, 9))])
        self.assertNoVertexAt(loft, (6, 7.5))

    def testRow13TwoTangentJointsAgainstOne(self):
        loft = self.row("S3t", "S2t")
        self.assertRow(loft, 7, 14354.963591, 3755.351934, [((10, 10), (6, 6))])
        mid = (6 + 6 * math.cos(math.radians(60)), 6 * math.sin(math.radians(60)))
        self.assertNoVertexAt(loft, mid)
        # a hole through the merged face
        face = [f for f in loft.Shape.Faces if f.Surface.TypeId != "Part::GeomPlane" and len(f.Edges) > 4][0]
        u0, u1, v0, v1 = face.ParameterRange
        p = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
        n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
        cut = loft.Shape.cut(Part.makeCylinder(1.0, 8.0, p - n * 4, n))
        self.assertTrue(cut.isValid())
        self.assertEqual(len(cut.Solids), 1)
        self.assertRoundTrip(loft)

    def testRow19NormalToProfileDropsTangentToTangent(self):
        loft = self.row("S3m", "S2t", StartCondition="Normal to profile", EndCondition="Normal to profile")
        self.assertRow(loft, 7, 16792.185449, 4058.176207, [((-8, 14), (-3, 6))], straight=False)

    def testRow22SharpConnectedToTheTangentJoint(self):
        loft = self.row("S3m", "S2t", extra=[((-8, 14), (6, 6))])
        self.assertRow(loft, 7, 16462.892528, 4040.917779, [((-8, 14), (6, 6))])

    def testAVerticalPlaneUnderConditionsKeepsItsEdge(self):
        """sk1046 case 5: the face between the top lines lies in y = 10 (Normal to profile at both ends keeps it a
        plane), so the smooth-smooth side edge (10, 10) > (6, 10) at its end stays."""
        sa, ea, ba = self.spanA("S2t")
        A = sa + models.polyline([ea, ba, (-20, -10), (-20, 10)])
        e = (6 + 6 * self.C30, 7)
        B = models.polyline([(-12, 10), (6, 10)]) + [self.arc((6, 4), 6, 90, 30)]
        B += models.polyline([e, (e[0], -6), (-12, -6), (-12, 10)])
        loft = self.loft(A, B, [((-20, 10), (-12, 10)), (ea, e)],
                         StartCondition="Normal to profile", EndCondition="Normal to profile")
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), 7)
        self.assertJoined(loft, (10, 10), (6, 10), straight=False)
        planes = [f for f in loft.Shape.Faces if f.Surface.TypeId == "Part::GeomPlane"
                  and all(abs(v.Point.y - 10) < 1e-6 for v in f.Vertexes)]
        self.assertEqual(len(planes), 1)

    def testTheCensusShapeBuildsOneFacePerRun(self):
        """The Well Drain class in designed form: a loop with two line, tangent arc, line chains and two single edges,
        sharp at the four connections, to a rectangle in a vertical plane at 45 degrees below it: each long chain's
        side face is one face (no plane anywhere), F 6."""
        c = math.sqrt(0.5)
        A = models.polyline([(0, 20), (0, 14), (10, 14)]) + [self.arc((10, 12), 2, 90, 0)]
        A += models.polyline([(12, 12), (12, 0), (20, 0), (20, 10)]) + [self.arc((10, 10), 10, 0, 90)]
        A += models.polyline([(10, 20), (0, 20)])
        placement = App.Placement(App.Matrix(c, 0, -c, 10, -c, 0, -c, 10, 0, 1, 0, 0, 0, 0, 0, 1))
        self.profile = models.sketch(self.doc, "Bottom", A, self.body)
        self.section = models.sketch(self.doc, "Top", models.rectangle(-3, -4, 3, -2), self.body, placement=placement)
        self.doc.recompute()
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = self.profile
        loft.Sections = [self.section]
        self.connect(loft, [((0, 14), (-3, -2)), ((0, 20), (-3, -4)), ((12, 0), (3, -2)), ((20, 0), (3, -4))])
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        shape = loft.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(len(shape.Faces), 6)

    def scaledRow(self, a, b, scale):
        sa, ea, ba = self.spanA(a)
        sb, eb, bb = self.spanB(b)
        A = sa + models.polyline([ea, ba, (-20, -10), (-20, 10)])
        B = sb + models.polyline([eb, bb, (-12, -6), (-12, 6)])
        for g in A + B:
            g.scale(V(0, 0, 0), scale)
        s = lambda p: (p[0] * scale, p[1] * scale)
        return self.loft(A, B, [(s((-20, 10)), s((-12, 6))), (s(ea), s(eb))], height=H * scale)

    def testTheSidesDontDependOnTheModelsSize(self):
        """Review r1f finding 1: the flat-side test is relative to the face's size: rows 7, 13 and 15 keep Onshape's F
        at 600 mm and 4 m (scale 15 and 100)."""
        for a, b, faces, volume in (("S2t", "S1", 7, 15090.177832), ("S3t", "S2t", 7, 14354.963591),
                                    ("S2t", "S2t", 7, 14908.015301)):
            for scale in (15, 100):
                with self.subTest(a=a, b=b, scale=scale):
                    loft = self.scaledRow(a, b, scale)
                    self.assertTrue(loft.isValid(), loft.getStatusString())
                    self.assertTrue(loft.Shape.isValid())
                    self.assertEqual(len(loft.Shape.Faces), faces)
                    self.assertAlmostEqual(loft.Shape.Volume / scale**3, volume, delta=ONSHAPE_SURFACE * volume)
                    self.tearDown()
                    self.setUp()

    def slot(self, half=10, r=5):
        return [Part.LineSegment(V(-half, -r, 0), V(half, -r, 0)), self.arc((half, 0), r, -90, 90),
                Part.LineSegment(V(half, r, 0), V(-half, r, 0)), self.arc((-half, 0), r, 90, 270)]

    def testEqualChainsEveryJointTangentBuildAsBefore(self):
        """Review r1f finding 2: a slot to a smaller slot turned 20 degrees, one connection: every joint tangent, no side
        flat, no new vertex. Onshape makes one closed side face (rule 5, not built yet); the loft builds as before
        ops#1046, every side edge kept (F 6)."""
        self.profile = models.sketch(self.doc, "Bottom", self.slot(), self.body)
        turned = App.Placement(V(0, 0, H), App.Rotation(V(0, 0, 1), 20))
        self.section = models.sketch(self.doc, "Top", self.slot(6, 3), self.body, placement=turned)
        self.doc.recompute()
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = self.profile
        loft.Sections = [self.section]
        self.connect(loft, [((10, -5), (6, -3))])
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), 6)

    def teardrop(self, d, r):
        th = math.degrees(math.acos(r / d))
        t = (r * math.cos(math.radians(th)), r * math.sin(math.radians(th)))
        return [self.arc((0, 0), r, th, 360 - th)] + models.polyline([(t[0], -t[1]), (d, 0), t])

    def testAWideArcInARunFits(self):
        """Review r1f finding 3 (and r2f T3): a teardrop to a blunter one merges a run over a 240 degree arc, which
        needs more than 41 samples to fit; rule 3 leaves one side face (F 3)."""
        loft = self.loft(self.teardrop(20, 10), self.teardrop(8, 2), [((20, 0), (8, 0))])
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertTrue(loft.Shape.isValid())
        self.assertEqual(len(loft.Shape.Solids), 1)
        self.assertEqual(len(loft.Shape.Faces), 3)

    @staticmethod
    def straightSpline(p, q):
        """A straight edge that isn't a line: a B-spline of degree 1 with two poles."""
        curve = Part.BSplineCurve()
        curve.buildFromPolesMultsKnots([V(p[0], p[1], 0), V(q[0], q[1], 0)], [2, 2], [0.0, 1.0], False, 1)
        return curve

    def testAStraightSplineSideKeepsItsEdge(self):
        """Review r2f T1: row 15 with each top line drawn as a straight B-spline: the side between them is still a
        plane, so its side edge (10,10)>(6,6) stays (F 7, as with lines)."""
        ea, eb = (10 + 10 * self.C30, 5), (6 + 6 * self.C30, 3)
        A = [self.straightSpline((-20, 10), (10, 10)), self.arc((10, 0), 10, 90, 30)]
        A += models.polyline([ea, (ea[0], -10), (-20, -10), (-20, 10)])
        B = [self.straightSpline((-12, 6), (6, 6)), self.arc((6, 0), 6, 90, 30)]
        B += models.polyline([eb, (eb[0], -6), (-12, -6), (-12, 6)])
        loft = self.loft(A, B, [((-20, 10), (-12, 6)), (ea, eb)])
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), 7)
        self.assertTrue(any(e.Vertexes[0].Point.distanceToPoint(V(10, 10, 0)) < 1e-6
                            and e.Vertexes[-1].Point.distanceToPoint(V(6, 6, H)) < 1e-6
                            or e.Vertexes[-1].Point.distanceToPoint(V(10, 10, 0)) < 1e-6
                            and e.Vertexes[0].Point.distanceToPoint(V(6, 6, H)) < 1e-6 for e in loft.Shape.Edges))

    def testASplitLineEveryJointTangentWithConditionsBuildsAsBefore(self):
        """Review r2 T1, r2f T2: a slot whose bottom line is split (ops#729) to a smaller slot, one connection, Normal
        to profile: every joint tangent and no side flat. The split vertex isn't matched by fraction, so the loft
        builds as before ops#1046 (F 7), at both ends and the start only."""
        split = models.polyline([(-10, -5), (0, -5), (10, -5)]) + [self.arc((10, 0), 5, -90, 90)]
        split += models.polyline([(10, 5), (-10, 5)]) + [self.arc((-10, 0), 5, 90, 270)]
        for properties in ({"StartCondition": "Normal to profile", "EndCondition": "Normal to profile"},
                           {"StartCondition": "Normal to profile"}):
            with self.subTest(**properties):
                loft = self.loft(split, self.slot(6, 3), [((10, -5), (6, -3))], **properties)
                self.assertTrue(loft.isValid(), loft.getStatusString())
                self.assertTrue(loft.Shape.isValid())
                self.assertEqual(len(loft.Shape.Faces), 7)
                self.tearDown()
                self.setUp()

    def testASplineCornerFitsAtSize(self):
        """Review r2 T2: a rectangle 600 x 300 whose corner is a sketch B-spline (cubic through the quarter circle)
        to a smaller one, one connection, the top turned 8 degrees: the run over line, B-spline, line merges and
        fits (arc length measured tightly, limits relative to the run's length)."""
        scale = 15

        def corner(x, y, r):
            c = (x - r, -y + r)
            points = [V((c[0] + r * math.cos(math.radians(270 + 90 * i / 8))) * scale,
                        (c[1] + r * math.sin(math.radians(270 + 90 * i / 8))) * scale, 0) for i in range(9)]
            curve = Part.BSplineCurve()
            curve.interpolate(Points=points, InitialTangent=V(1, 0, 0), FinalTangent=V(0, 1, 0))
            s = lambda ps: [(px * scale, py * scale) for px, py in ps]
            return models.polyline(s([(-x, y), (-x, -y), (x - r, -y)])) + [curve] + models.polyline(
                s([(x, -y + r), (x, y), (-x, y)]))

        self.profile = models.sketch(self.doc, "Bottom", corner(20, 10, 6), self.body)
        turned = App.Placement(V(0, 0, H * scale), App.Rotation(V(0, 0, 1), 8))
        self.section = models.sketch(self.doc, "Top", corner(12, 6, 3), self.body, placement=turned)
        self.doc.recompute()
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = self.profile
        loft.Sections = [self.section]
        self.connect(loft, [((-20 * scale, 10 * scale), (-12 * scale, 6 * scale))])
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertTrue(loft.Shape.isValid())
        self.assertEqual(len(loft.Shape.Solids), 1)

    def testACircleRunEndingAtTheSeam(self):
        """Review r1f finding 4: a circle against a rectangle with one rounded corner, connected at the circle's seam:
        the run that ends at the seam joins its pieces back by their own parameters."""
        rounded = models.polyline([(6, 4), (-6, 4), (-6, -2)]) + [self.arc((-4, -2), 2, 180, 270)]
        rounded += models.polyline([(-4, -4), (6, -4), (6, 4)])
        loft = self.loft([Part.Circle(V(0, 0, 0), V(0, 0, 1), 10)], rounded, [((10, 0), (6, -4))])
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertTrue(loft.Shape.isValid())
        self.assertEqual(len(loft.Shape.Solids), 1)

    # refusals
    def testEveryJointSmoothWithNoPlaneStops(self):
        """sk1046 case 6: circle r 10 (vertices at 0 and 180 degrees) to circle r 6 (0, 90, 180, 270), one connection:
        every side edge would go. Onshape builds one closed side face (the frustum); not yet here."""

        def circle(r, degrees):
            d = list(degrees) + [degrees[0] + 360]
            return [self.arc((0, 0), r, a, b) for a, b in zip(d, d[1:])]

        loft = self.loft(circle(10, [0, 180]), circle(6, [0, 90, 180, 270]), [((10, 0), (6, 0))])
        self.assertStops(loft, "tangent")

    def testUnmatchedTangentRunsWithTwoConnectionsStop(self):
        """sk1046 change 1 (D): LC3 with two connections isn't reproduced by the rule; it stays a stop."""
        slot, rounded = TestLoftConnectionsUnequal.slotAndRoundedRectangle(self)
        loft = self.loft(slot, rounded, [((10, 5), (6, 4)), ((-10, -5), (-6, -4))])
        self.assertStops(loft, "connection", "tangent")


class TestLoftElbowPairing(unittest.TestCase):
    """ops#933: two polygon profiles on planes that are not parallel, lofted without connections, paired half a turn
    apart for about half of the sketches' vertex orders (the side faces crossed and the loft stopped). Designed: the
    square x 0..4, y 6..10 on z = 30 and the rectangle x 0..4, z 2..14 on the plane y = 0. Onshape builds the loft that
    doesn't turn: each section x = const is the quadrilateral (y, z) = (6, 30), (10, 30), (0, 2), (0, 14), area 92, so
    V = 4 x 92 = 368 with 6 planar faces, whatever order the sketches' vertices come in."""

    def setUp(self):
        self.doc = models.newDocument("PartDesignTestLoftElbowPairing")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    @staticmethod
    def orders(points):
        out = []
        for r in range(len(points)):
            q = points[r:] + points[:r]
            out.append(("ccw%d" % r, q))
            out.append(("cw%d" % r, [q[0]] + q[:0:-1]))
        return out

    def loop(self, body, name, placement, points):
        import Sketcher

        sketch = body.newObject("Sketcher::SketchObject", name)
        sketch.Placement = placement
        n = len(points)
        for k in range(n):
            sketch.addGeometry(Part.LineSegment(V(*points[k], 0), V(*points[(k + 1) % n], 0)))
        for k in range(n):
            sketch.addConstraint(Sketcher.Constraint("Coincident", k, 2, (k + 1) % n, 1))
        return sketch

    def testEveryVertexOrderBuildsThePrism(self):
        square = [(0, 6), (4, 6), (4, 10), (0, 10)]
        rectangle = [(0, 2), (4, 2), (4, 14), (0, 14)]  # Rotation(0, 0, 90): local (x, y) is global (x, 0, y)
        wrong = []
        for (ta, a), (tb, b) in [(x, y) for x in self.orders(square) for y in self.orders(rectangle)]:
            body = self.doc.addObject("PartDesign::Body", "Body")
            top = self.loop(body, "Top", App.Placement(V(0, 0, 30), App.Rotation()), a)
            wall = self.loop(body, "Wall", App.Placement(V(0, 0, 0), App.Rotation(0, 0, 90)), b)
            self.doc.recompute()
            loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
            loft.Profile = top
            loft.Sections = [wall]
            loft.Refine = True
            self.doc.recompute()
            shape = loft.Shape
            planes = sum(1 for f in shape.Faces if f.Surface.TypeId == "Part::GeomPlane")
            if not (
                loft.isValid()
                and shape.isValid()
                and len(shape.Solids) == 1
                and abs(shape.Volume - 368) < 1e-6
                and len(shape.Faces) == 6
                and planes == 6
            ):
                wrong.append("%s/%s: %s V %.6f" % (ta, tb, loft.getStatusString(), shape.Volume if not shape.isNull() else 0))
        self.assertEqual(wrong, [], "%d of 64 vertex orders" % len(wrong))

    def testParallelSquaresKeepTheirPairing(self):
        # between parallel planes the compatibility step's pairing doesn't turn: kept (a 10 square to a 6 square, 30
        # above, the frustum's volume 30 / 3 x (100 + 36 + 60) = 1960)
        body = self.doc.addObject("PartDesign::Body", "Body")
        bottom = self.loop(body, "Bottom", App.Placement(), [(-5, -5), (5, -5), (5, 5), (-5, 5)])
        top = self.loop(body, "Top", App.Placement(V(0, 0, 30), App.Rotation()), [(3, 3), (-3, 3), (-3, -3), (3, -3)])
        self.doc.recompute()
        loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = bottom
        loft.Sections = [top]
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertAlmostEqual(loft.Shape.Volume, 1960, delta=1e-6)


if __name__ == "__main__":
    unittest.main()
