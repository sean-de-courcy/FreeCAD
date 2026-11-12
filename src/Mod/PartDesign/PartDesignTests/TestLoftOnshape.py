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

    def testSquareToPointIsThePyramid(self):
        loft = self.loft(square(20), [Part.Point(V(0, 0, 0))])
        self.assertLoft(loft, 400 * H / 3, 1664.91, 5)


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

    def testNamesMatchThePlainLoft(self):
        """The condition keeps the side faces' names (a later feature's reference survives switching it on)."""
        loft = self.loft(square(20), [models.circle(0, 0, 5)])
        plain = sorted(name for name in loft.Shape.ElementReverseMap if name.startswith("Face"))
        mapped = {name: loft.Shape.getElementMappedName(name) for name in plain}
        loft.StartCondition = "Normal to profile"
        self.doc.recompute()
        self.assertTrue(loft.isValid(), loft.getStatusString())
        after = {name: loft.Shape.getElementMappedName(name) for name in plain}
        self.assertEqual(set(m[0] for m in mapped.values() if m), set(m[0] for m in after.values() if m))

    def testPointProfileStops(self):
        loft = self.loft(square(20), [Part.Point(V(0, 0, 0))], EndCondition="Normal to profile")
        self.assertStops(loft, "normal to profile", "point")


if __name__ == "__main__":
    unittest.main()
