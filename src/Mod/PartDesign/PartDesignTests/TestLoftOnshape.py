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
        self.assertLoft(loft, 7894.77, 2350.04, 6)
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
        self.assertLoft(loft, 7894.77, 2350.04, 6)

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


if __name__ == "__main__":
    unittest.main()
