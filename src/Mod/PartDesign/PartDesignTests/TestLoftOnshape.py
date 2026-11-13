# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: PartDesign Loft as Onshape's (ops#655, notes/loft-options.md).
#
# Designed geometry only. The expected values are Onshape's (oracle facts GB12, notes/onshape-facts.md), which
# are closed forms where the loft is ruled: the frustum, the cone frustum and the pyramid.

import math
import unittest

import FreeCAD
import Part

from PartDesignTests.Scenarios import models

App = FreeCAD
V = App.Vector
H = 30.0


def square(side):
    h = side / 2
    return models.rectangle(-h, -h, h, h)


class LoftCase(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PartDesignTestLoftOnshape")
        self.body = models.body(self.doc)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def loft(self, bottom, top, height=H, **properties):
        """bottom and top: lists of sketch geometry; the top sketch sits `height` above the bottom one."""
        profile = models.sketch(self.doc, "Bottom", bottom, self.body)
        section = models.sketch(self.doc, "Top", top, self.body, z=height)
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = profile
        loft.Sections = [section]
        for name, value in properties.items():
            setattr(loft, name, value)
        self.doc.recompute()
        return loft

    def assertLoft(self, loft, volume, area, faces, delta=0.02):
        self.assertTrue(loft.isValid(), loft.getStatusString())
        shape = loft.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, delta=delta)
        self.assertAlmostEqual(shape.Area, area, delta=delta)
        self.assertEqual(len(shape.Faces), faces)

    def assertStops(self, loft, *words):
        self.assertFalse(loft.isValid(), "expected a stop")
        message = loft.getStatusString()
        for word in words:
            self.assertIn(word.lower(), message.lower(), message)


class TestLoftOnshapePlain(LoftCase):
    """GB12 (a)-(d): Onshape's plain two-profile loft, 30 apart, concentric."""

    def testSquareToSquareIsTheFrustum(self):
        loft = self.loft(square(20), square(10))
        # h/3 (A1 + A2 + sqrt(A1 A2)) = 10 (400 + 100 + 200)
        self.assertLoft(loft, 7000.0, 2324.83, 6)

    def testCircleToCircleIsTheConeFrustum(self):
        loft = self.loft([models.circle(0, 0, 10)], [models.circle(0, 0, 5)])
        self.assertLoft(loft, math.pi * H / 3 * (100 + 25 + 50), 1825.92, 3)

    def testSquareToCircleMatchesOnshape(self):
        # Onshape cuts the circle at the corners' angles and pairs each side with a quarter circle,
        # both parameterised by arc length (V 6586.031 by integration of that ruled surface)
        loft = self.loft(square(20), [models.circle(0, 0, 5)])
        self.assertLoft(loft, 6586.04, 2157.64, 6)
        self.assertEqual(len(loft.Shape.Edges), 12)

    def testCircleToSquareMatchesOnshape(self):
        """The circle first: its cap takes the moved seam too (no vertex left at the sketch's 0 degrees)."""
        loft = self.loft([models.circle(0, 0, 5)], square(20))
        self.assertLoft(loft, 6586.04, 2157.64, 6)
        self.assertEqual(len(loft.Shape.Edges), 12)
        self.assertEqual(len(loft.Shape.Vertexes), 8)

    def testRuledSquareToCircleHasFourSides(self):
        loft = self.loft(square(20), [models.circle(0, 0, 5)], Ruled=True)
        self.assertLoft(loft, 6586.04, 2157.64, 6)
        self.assertEqual(len(loft.Shape.Edges), 12)

    def testSquareToPointIsThePyramid(self):
        loft = self.loft(square(20), [Part.Point(V(0, 0, 0))])
        self.assertLoft(loft, 400 * H / 3, 1664.91, 5)


class TestLoftOnshapeThreeSections(LoftCase):
    """Circle r 5, square 8 at z 15, circle r 3 at z 30. The seam moves only where the surface stays the same
    (two profiles, or ruled); a smooth loft through 3+ sections keeps OCCT's plain loft (deferred, ops#655)."""

    def loft3(self, **properties):
        sketches = [
            models.sketch(self.doc, "Bottom", [models.circle(0, 0, 5)], self.body),
            models.sketch(self.doc, "Middle", square(8), self.body, z=15),
            models.sketch(self.doc, "Top", [models.circle(0, 0, 3)], self.body, z=30),
        ]
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = sketches[0]
        loft.Sections = sketches[1:]
        for name, value in properties.items():
            setattr(loft, name, value)
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        plain = Part.makeLoft([s.Shape.Wires[0] for s in sketches], True, loft.Ruled)
        return loft.Shape, plain

    def testSmoothKeepsThePlainLoft(self):
        shape, plain = self.loft3()
        self.assertAlmostEqual(shape.Volume, plain.Volume, delta=plain.Volume * 1e-9)
        self.assertAlmostEqual(shape.Area, plain.Area, delta=plain.Area * 1e-9)
        # the circles' seam vertex at 0 degrees splits the square's x = 4 side: 5 sides, as OCCT gives
        self.assertEqual(len(shape.Faces), len(plain.Faces))
        self.assertEqual(len(shape.Faces), 7)

    def testRuledPairsTheVertices(self):
        shape, plain = self.loft3(Ruled=True)
        self.assertAlmostEqual(shape.Volume, plain.Volume, delta=plain.Volume * 1e-9)
        # 4 sides per span and the two caps (the plain loft has 5 per span)
        self.assertEqual(len(shape.Faces), 10)


class TestLoftOnshapeConditions(LoftCase):
    """GB12 (e): start condition Normal to profile."""

    def testConditionsDefaultToNone(self):
        loft = self.loft(square(20), square(10))
        self.assertEqual(loft.StartCondition, "None")
        self.assertEqual(loft.EndCondition, "None")
        self.assertEqual(loft.StartMagnitude, 1.0)
        self.assertEqual(loft.EndMagnitude, 1.0)

    def testStartNormalToProfileSquareToCircle(self):
        loft = self.loft(square(20), [models.circle(0, 0, 5)], StartCondition="Normal to profile")
        self.assertLoft(loft, 7894.77, 2350.04, 6, delta=0.1)  # Onshape: 2 decimals, a fitted surface
        box = loft.Shape.BoundBox
        for got, want in [
            (box.XMin, -10),
            (box.XMax, 10),
            (box.YMin, -10),
            (box.YMax, 10),
            (box.ZMin, 0),
            (box.ZMax, H),
        ]:
            self.assertAlmostEqual(got, want, delta=1e-4)

    def testStartIsNormalToTheProfile(self):
        """The side faces leave the start profile along its normal: vertical at z = 0."""
        loft = self.loft(square(20), [models.circle(0, 0, 5)], StartCondition="Normal to profile")
        for face in loft.Shape.Faces:
            if abs(face.BoundBox.ZLength - H) > 1e-6:
                continue  # the caps
            u0, u1, v0, v1 = face.ParameterRange
            for u in (u0 + (u1 - u0) * k / 4 for k in range(5)):
                for v in (v0, v1):
                    point = face.valueAt(u, v)
                    if abs(point.z) < 1e-6:
                        normal = face.normalAt(u, v)
                        self.assertAlmostEqual(normal.z, 0, delta=1e-6)

    def testStartNormalSquareToSquareKeepsSixFaces(self):
        loft = self.loft(square(20), square(10), StartCondition="Normal to profile")
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual(len(loft.Shape.Faces), 6)
        # bulges outward from the frustum: more volume, same base and top
        self.assertGreater(loft.Shape.Volume, 7000.0 + 1)
        self.assertAlmostEqual(loft.Shape.BoundBox.XMax, 10, delta=1e-4)

    def testEndNormalMirrorsStartNormal(self):
        """A circle d10 at z = 0 to a square 20 at z = 30 with the end normal is the start case upside down."""
        loft = self.loft([models.circle(0, 0, 5)], square(20), EndCondition="Normal to profile")
        self.assertLoft(loft, 7894.77, 2350.04, 6, delta=0.1)  # Onshape: 2 decimals, a fitted surface

    def testALargerMagnitudeBulgesMore(self):
        loft = self.loft(square(20), square(10), StartCondition="Normal to profile")
        one = loft.Shape.Volume
        loft.StartMagnitude = 2.0
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertGreater(loft.Shape.Volume, one + 1)
        self.assertAlmostEqual(loft.Shape.BoundBox.XMax, 10, delta=1e-4)

    @staticmethod
    def places(shape):
        """Each face's and edge's mapped name -> where it is: cap or side, and its centre's angle."""
        out = {}
        for kind, elements in (("Face", shape.Faces), ("Edge", shape.Edges)):
            for i, element in enumerate(elements, 1):
                centre = element.CenterOfMass
                flat = element.BoundBox.ZLength < 1e-6
                place = ("bottom" if centre.z < H / 2 else "top") if flat else "side"
                if math.hypot(centre.x, centre.y) > 1e-6:
                    place += " %d" % (round(math.degrees(math.atan2(centre.y, centre.x))) % 360)
                out[shape.getElementMappedName("%s%d" % (kind, i))] = (kind, place)
        return out

    def assertNamesKept(self, loft, condition):
        """Switching the condition on keeps every face's and edge's mapped name on the same face or edge,
        so a later feature's reference (stored as the mapped name) still lands where it pointed."""
        plain = self.places(loft.Shape)
        self.assertEqual(len(plain), 6 + 12)  # every element named, no two alike
        self.assertNotIn("", plain)
        setattr(loft, condition, "Normal to profile")
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        after = self.places(loft.Shape)
        for mapped, place in plain.items():
            self.assertEqual(after.get(mapped), place, mapped)

    def testNamesMatchThePlainLoft(self):
        self.assertNamesKept(self.loft(square(20), [models.circle(0, 0, 5)]), "StartCondition")

    def testNamesMatchThePlainLoftCircleFirst(self):
        self.assertNamesKept(self.loft([models.circle(0, 0, 5)], square(20)), "EndCondition")

    def testPointProfileStops(self):
        loft = self.loft(square(20), [Part.Point(V(0, 0, 0))], EndCondition="Normal to profile")
        self.assertStops(loft, "normal to profile", "point")



def sides(shape):
    """The side faces of a conditioned loft: the B-splines with one cubic span across (4 rows)."""
    out = [f for f in shape.Faces if isinstance(f.Surface, Part.BSplineSurface)]
    for face in out:
        assert face.Surface.NbVPoles == 4, face.Surface.NbVPoles
    return out


def squareVolume(s0, s1, h, k0=0.0, k1=0.0):
    """Square half-side s0 at z 0 to s1 at z h (concentric) with Onshape's cubic rows: tangent k0 along the
    normal at the start, k1 at the end, a natural (zero second derivative) end where none is set. The
    section at every height is a square, so V = integral of 4 s(v)^2 z'(v) dv (notes/loft-end-conditions.md T1)."""
    q = s0 * s0 + s0 * s1 + s1 * s1
    if k0 and k1:
        return 2 * (70 * h * q + k0 * (25 * s0 * s0 - 8 * s0 * s1 - 17 * s1 * s1)
                    + k1 * (-17 * s0 * s0 - 8 * s0 * s1 + 25 * s1 * s1)) / 105
    if k0:
        return (140 * h * q + k0 * (64 * s0 * s0 - 23 * s0 * s1 - 41 * s1 * s1)) / 105
    return (140 * h * q + k1 * (-41 * s0 * s0 - 23 * s0 * s1 + 64 * s1 * s1)) / 105


class TestLoftEndConditions(LoftCase):
    """Normal to profile as Onshape builds it (decision 396; oracle 17 LE2-LE8, notes/loft-end-conditions.md):
    each side face is one cubic span across, leaving (or reaching) the profile along its normal with tangent
    length k, natural at a free end. The expected volumes are closed forms in k, and k is read from the side
    faces' rows, so these tests hold whatever rule gives k (the rule has its own tests)."""

    def k(self, shape, normal, end=False):
        """3 |R1 - R0| (start) or 3 |R3 - R2| (end) along `normal`, the same on every row of every side."""
        values = []
        for face in sides(shape):
            for row in face.Surface.getPoles():
                step = (row[3] - row[2]) if end else (row[1] - row[0])
                values.append(3 * step.dot(normal))
                # along the normal only: the side meets the profile's plane at 90 degrees
                self.assertLess((step - normal * step.dot(normal)).Length, 1e-9)
        self.assertLess(max(values) - min(values), 1e-9)
        return values[0]

    def assertNatural(self, shape, end):
        """The free end has a zero second derivative across: R1 - 2 R2 + R3 = 0 (or R0 - 2 R1 + R2)."""
        for face in sides(shape):
            for r in face.Surface.getPoles():
                second = (r[1] - r[2] * 2 + r[3]) if end else (r[0] - r[1] * 2 + r[2])
                self.assertLess(second.Length, 1e-9)

    def testStartSquareClosedForm(self):
        loft = self.loft(square(20), square(10), StartCondition="Normal to profile")
        self.assertTrue(loft.isValid(), loft.getStatusString())
        k = self.k(loft.Shape, V(0, 0, 1))
        # Onshape's rule (oracle 17): 0.9 h + 0.1 times the corner rail's length (Onshape's surface: 30.082206)
        self.assertAlmostEqual(k, 0.9 * H + 0.1 * math.sqrt(H * H + 50), delta=1e-9)
        self.assertAlmostEqual(loft.Shape.Volume, squareVolume(10, 5, H, k0=k), delta=1e-6 * 8000)
        self.assertEqual(len(loft.Shape.Faces), 6)
        self.assertNatural(loft.Shape, end=True)
        box = loft.Shape.BoundBox
        for got, want in [(box.XMax, 10), (box.YMin, -10), (box.ZMin, 0), (box.ZMax, H)]:
            self.assertAlmostEqual(got, want, delta=1e-6)

    def testStartSquareMiddlePoint(self):
        """The side through (0, -10, 0) at the middle of its span: (0, -(5.5 s0 + 2.5 s1)/8, (1.5 k + 2.5 h)/8)."""
        loft = self.loft(square(20), square(10), StartCondition="Normal to profile")
        k = self.k(loft.Shape, V(0, 0, 1))
        face = min(sides(loft.Shape), key=lambda f: f.CenterOfMass.y)
        u, _ = face.Surface.parameter(V(0, -10, 0))
        point = face.Surface.value(u, 0.5)
        want = V(0, -(5.5 * 10 + 2.5 * 5) / 8, (1.5 * k + 2.5 * H) / 8)
        self.assertLess((point - want).Length, 1e-7, (point, want))

    def testEndSquareClosedForm(self):
        loft = self.loft(square(20), square(10), EndCondition="Normal to profile")
        self.assertTrue(loft.isValid(), loft.getStatusString())
        k = self.k(loft.Shape, V(0, 0, 1), end=True)
        self.assertAlmostEqual(loft.Shape.Volume, squareVolume(10, 5, H, k1=k), delta=1e-6 * 8000)
        self.assertNatural(loft.Shape, end=False)

    def testBothSquareClosedForm(self):
        loft = self.loft(
            square(20), square(10), StartCondition="Normal to profile", EndCondition="Normal to profile"
        )
        self.assertTrue(loft.isValid(), loft.getStatusString())
        k0 = self.k(loft.Shape, V(0, 0, 1))
        k1 = self.k(loft.Shape, V(0, 0, 1), end=True)
        self.assertAlmostEqual(k0, k1, delta=1e-9)  # one length per profile pair (LE2)
        self.assertAlmostEqual(loft.Shape.Volume, squareVolume(10, 5, H, k0, k1), delta=1e-6 * 8000)

    def testMagnitudeScalesTheTangent(self):
        """Linear in the magnitude (LE3: m 0.5 gives k / 2)."""
        loft = self.loft(square(20), square(10), StartCondition="Normal to profile")
        one = self.k(loft.Shape, V(0, 0, 1))
        loft.StartMagnitude = 0.5
        self.doc.recompute()
        self.assertAlmostEqual(self.k(loft.Shape, V(0, 0, 1)), one / 2, delta=1e-9)

    def testCircleClosedForm(self):
        """Concentric circles: the section is a circle, V = pi/4 times the square's form with s = r."""
        loft = self.loft(
            [models.circle(0, 0, 10)], [models.circle(0, 0, 5)], StartCondition="Normal to profile"
        )
        self.assertTrue(loft.isValid(), loft.getStatusString())
        k = self.k(loft.Shape, V(0, 0, 1))
        want = math.pi / 4 * squareVolume(10, 5, H, k0=k)
        self.assertAlmostEqual(loft.Shape.Volume, want, delta=1e-6 * want)
        self.assertEqual(len(loft.Shape.Faces), 3)

    def testRemoveIntoABlock(self):
        """Liquid feeder base #8's class (T3): a Remove loft from a rectangle on a block's face to a smaller one
        8 inside, end Normal to profile. The removed volume is the rectangles' closed form in k."""
        box = self.body.newObject("PartDesign::AdditiveBox", "Box")
        box.Length, box.Width, box.Height = 40, 20, 20
        box.Placement = App.Placement(V(-20, 0, 0), App.Rotation())
        turn = App.Rotation(V(1, 0, 0), 90)  # sketch (x, y) -> (x, 0, y)
        front = models.sketch(self.doc, "Front", models.rectangle(-6, 4, 6, 10), self.body,
                              placement=App.Placement(V(0, 0, 0), turn))
        back = models.sketch(self.doc, "Back", models.rectangle(-3, 5, 3, 9), self.body,
                             placement=App.Placement(V(0, 8, 0), turn))
        cut = self.body.newObject("PartDesign::SubtractiveLoft", "Cut")
        cut.Profile = front
        cut.Sections = [back]
        cut.EndCondition = "Normal to profile"
        self.doc.recompute()
        self.assertTrue(cut.isValid(), cut.getStatusString())
        k = self.k(cut.AddSubShape, V(0, 1, 0), end=True)
        w0, h0, w1, h1, h = 12, 6, 6, 4, 8
        removed = (h * (h0 * w0 / 3 + (h0 * w1 + h1 * w0) / 6 + h1 * w1 / 3)
                   + k * (-41 * h0 * w0 / 420 - 23 * (h0 * w1 + h1 * w0) / 840 + 16 * h1 * w1 / 105))
        self.assertAlmostEqual(16000 - cut.Shape.Volume, removed, delta=1e-6 * 16000)
        self.assertAlmostEqual(16000 - cut.Shape.Volume, 322.284258, delta=1e-4 * 322.284258)  # Onshape (LE9 Q9c)
        self.assertTrue(cut.Shape.isValid())
        self.assertEqual(len(cut.Shape.Faces), 11)

    def testZeroMagnitudeIsNone(self):
        """LE3: magnitude 0 is exactly the plain loft, names included."""
        loft = self.loft(square(20), [models.circle(0, 0, 5)])
        plain = (loft.Shape.Volume, loft.Shape.Area, TestLoftOnshapeConditions.places(loft.Shape))
        loft.StartMagnitude = 0.0
        loft.StartCondition = "Normal to profile"
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertAlmostEqual(loft.Shape.Volume, plain[0], delta=1e-9)
        self.assertAlmostEqual(loft.Shape.Area, plain[1], delta=1e-9)
        self.assertEqual(TestLoftOnshapeConditions.places(loft.Shape), plain[2])

    def testZeroMagnitudesBetweenPerpendicularProfilesAreNone(self):
        """LE8's check: square 20 on Top to square 10 on the plane x = 30 with N 0 at both ends is the plain loft."""
        profile = models.sketch(self.doc, "Bottom", square(20), self.body)
        side = App.Placement(V(30, 0, 15), App.Rotation(V(0, 1, 0), 90))  # sketch normal -> +x
        section = models.sketch(self.doc, "Side", square(10), self.body, placement=side)
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = profile
        loft.Sections = [section]
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        plain = (loft.Shape.Volume, loft.Shape.Area, len(loft.Shape.Faces))
        loft.StartCondition = loft.EndCondition = "Normal to profile"
        loft.StartMagnitude = loft.EndMagnitude = 0.0
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertEqual((loft.Shape.Volume, loft.Shape.Area, len(loft.Shape.Faces)), plain)

    def testNegativeMagnitudeOnANarrowingLoftStops(self):
        """LE3: m -1 on square 20 -> square 10 is LOFT_INVALID: the side dips through the bottom face."""
        loft = self.loft(square(20), square(10), StartCondition="Normal to profile", StartMagnitude=-1.0)
        self.assertStops(loft, "crosses", "LOFT_INVALID")
        # a small negative magnitude dips only near the profile (until v ~ 2 |k| / 3 h): still a crossing
        loft.StartMagnitude = -0.01
        self.doc.recompute()
        self.assertStops(loft, "crosses", "LOFT_INVALID")

    def testNegativeMagnitudeOnAWideningLoftBuilds(self):
        """The fork's rule (Onshape's result for this shape is not known): square 10 -> square 20 with m -1 bulges
        below the bottom plane outside its face, a valid solid, so it builds; V is the closed form in k < 0."""
        loft = self.loft(square(10), square(20), StartCondition="Normal to profile", StartMagnitude=-1.0)
        self.assertTrue(loft.isValid(), loft.getStatusString())
        k = self.k(loft.Shape, V(0, 0, 1))
        self.assertLess(k, 0)
        self.assertTrue(loft.Shape.isValid())
        self.assertAlmostEqual(loft.Shape.Volume, squareVolume(5, 10, H, k0=k), delta=1e-6 * 8000)

    def tiltedLoft(self, **properties):
        """Square 20 on z = 0 to square 10 centred (0, 0, 30) on a plane turned 20 degrees about x (LE4)."""
        profile = models.sketch(self.doc, "Bottom", square(20), self.body)
        tilted = App.Placement(V(0, 0, H), App.Rotation(V(1, 0, 0), 20))
        section = models.sketch(self.doc, "Top", square(10), self.body, placement=tilted)
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = profile
        loft.Sections = [section]
        for name, value in properties.items():
            setattr(loft, name, value)
        self.doc.recompute()
        return loft

    def testTiltedEndMatchesOnshape(self):
        """LE4: each end gets its own tangent length (0.9 times the rail's reach along that end's normal plus 0.1
        times its length): Onshape's V and A for start, end and both (its own surface is a fit, about 2e-5)."""
        for properties, volume, area in [
            ({"StartCondition": "Normal to profile"}, 8117.689839, 2467.162109),
            ({"EndCondition": "Normal to profile"}, 6082.240752, 2207.998341),
            ({"StartCondition": "Normal to profile", "EndCondition": "Normal to profile"}, 7193.441817, 2348.021243),
        ]:
            loft = self.tiltedLoft(**properties)
            self.assertTrue(loft.isValid(), loft.getStatusString())
            self.assertEqual(len(loft.Shape.Faces), 6)
            self.assertAlmostEqual(loft.Shape.Volume, volume, delta=1e-4 * volume)
            self.assertAlmostEqual(loft.Shape.Area, area, delta=1e-5 * area)
            self.body = models.body(self.doc)  # the next case in a body of its own

    def testOnshapeSquaresAndCircles(self):
        """LE2 and LE9: Onshape's V and A (its surfaces are fits: about 5e-5 on short lofts and circles)."""
        for bottom, top, height, volume, area in [
            (square(20), square(10), 30, 8210.440033, 2478.711034),
            (square(20), square(10), 10, 2744.895049, 1230.105156),
            (square(20), square(4), 30, 6621.738887, 2151.989674),
            ([models.circle(0, 0, 10)], [models.circle(0, 0, 5)], 30, 6446.964332, 1946.606814),
            ([models.circle(0, 0, 10)], [models.circle(0, 0, 5)], 3, 653.515612, 685.526108),
            ([models.circle(0, 0, 10)], [models.circle(0, 0, 2.5)], 6, 1089.594130, 752.259803),
        ]:
            loft = self.loft(bottom, top, height, StartCondition="Normal to profile")
            self.assertTrue(loft.isValid(), loft.getStatusString())
            self.assertAlmostEqual(loft.Shape.Volume, volume, delta=1e-4 * volume)
            self.assertAlmostEqual(loft.Shape.Area, area, delta=2e-5 * area)
            self.body = models.body(self.doc)  # the next case in a body of its own

    def testOffsetRectanglesTakeEachCornersLength(self):
        """LE9 (Q9c): rectangle 12 x 6 on y = 0 to 6 x 4 centred (1.5, 7.5) on y = 8, end N: each face's tangent length
        runs from one corner rail's value to the other's (Onshape, on one face: 8.027646 .. 8.130057), V and A as Onshape's."""
        turn = App.Rotation(V(1, 0, 0), 90)  # sketch (x, y) -> (x, 0, y)
        front = models.sketch(self.doc, "Front", models.rectangle(-6, 4, 6, 10), self.body,
                              placement=App.Placement(V(0, 0, 0), turn))
        back = models.sketch(self.doc, "Back", models.rectangle(-1.5, 5.5, 4.5, 9.5), self.body,
                             placement=App.Placement(V(0, 8, 0), turn))
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = front
        loft.Sections = [back]
        loft.EndCondition = "Normal to profile"
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        self.assertAlmostEqual(loft.Shape.Volume, 322.114317, delta=1e-4 * 322.114317)
        self.assertAlmostEqual(loft.Shape.Area, 313.398104, delta=1e-5 * 313.398104)
        n = V(0, 1, 0)
        rule = lambda p, q: 0.9 * (q - p).dot(n) + 0.1 * (q - p).Length
        seen = []
        for face in sides(loft.Shape):
            poles = face.Surface.getPoles()
            for row in (poles[0], poles[-1]):
                self.assertAlmostEqual(3 * (row[3] - row[2]).dot(n), rule(row[0], row[3]), delta=1e-9)
                seen.append(rule(row[0], row[3]))
        self.assertAlmostEqual(max(seen), 0.9 * 8 + 0.1 * math.sqrt(64 + 22.5), delta=1e-9)
        # the corners' in-plane offsets squared are 22.5, 4.5, 2.5, 20.5; Onshape read 8.027646 .. 8.130057 on the
        # face whose corners are 22.5 and 4.5
        self.assertAlmostEqual(min(seen), 0.9 * 8 + 0.1 * math.sqrt(64 + 2.5), delta=1e-9)

    def testThreeProfilesStop(self):
        sketches = [
            models.sketch(self.doc, "Bottom", [models.circle(0, 0, 5)], self.body),
            models.sketch(self.doc, "Middle", square(8), self.body, z=15),
            models.sketch(self.doc, "Top", [models.circle(0, 0, 3)], self.body, z=30),
        ]
        loft = self.body.newObject("PartDesign::AdditiveLoft", "Loft")
        loft.Profile = sketches[0]
        loft.Sections = sketches[1:]
        loft.StartCondition = "Normal to profile"
        self.doc.recompute()
        self.assertStops(loft, "normal to profile", "two profiles")

    def testNamesKeptWithBothConditions(self):
        loft = self.loft(square(20), [models.circle(0, 0, 5)])
        plain = TestLoftOnshapeConditions.places(loft.Shape)
        loft.StartCondition = loft.EndCondition = "Normal to profile"
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        after = TestLoftOnshapeConditions.places(loft.Shape)
        for mapped, place in plain.items():
            self.assertEqual(after.get(mapped), place, mapped)


if __name__ == "__main__":
    unittest.main()
