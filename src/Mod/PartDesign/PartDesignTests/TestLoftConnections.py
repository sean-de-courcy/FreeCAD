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
        self.assertLoft(loft, 8000.0, 2848.1431, 6)
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

    def testSixEdgesToARectangleOneConnection(self):
        loft = self.loft(self.sixEdges(), models.rectangle(-6, -4, 6, 4), [((-10, -6), (6, 4))])
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Solids), 1)
        self.assertJoined(loft, (-10, -6), (6, 4))

    def testEightEdgesToARectangleFourConnections(self):
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
        self.assertEqual(len(loft.Shape.Solids), 1)
        for a, b in pairs:
            self.assertJoined(loft, a, b, straight=False)

    def testSlotToARoundedRectangleTwoConnections(self):
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
        pairs = [((10, 5), (6, 4)), ((-10, -5), (-6, -4))]
        loft = self.loft(slot, rounded, pairs)
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Solids), 1)
        for a, b in pairs:
            self.assertJoined(loft, a, b)


if __name__ == "__main__":
    unittest.main()
