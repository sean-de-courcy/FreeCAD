# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH lane solid-ops: Thicken, Scale and Offset surface as Body features.

Designed geometry only: a 20 x 20 x 10 box from the origin (top face at z = 10, area 400) and a
cylinder of radius 10, height 20 (lateral area 2 pi 10 20). Each expected value is geometric.
"""

import math
import unittest

import FreeCAD as App
import Part
import PartDesign

try:
    from PartDesign import SolidOpsFeatures as S
except ImportError:  # run with the source folder on the path
    import SolidOpsFeatures as S


def lateral_face_name(shape):
    for i, f in enumerate(shape.Faces):
        if f.Surface.__class__.__name__ == "Cylinder":
            return "Face%d" % (i + 1)
    raise AssertionError("no cylindrical face")


def top_face_name(shape):
    for i, f in enumerate(shape.Faces):
        if abs(f.CenterOfMass.z - shape.BoundBox.ZMax) < 1e-6 and f.Surface.__class__.__name__ == "Plane":
            return "Face%d" % (i + 1)
    raise AssertionError("no top face")


class SolidOpsBase(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("SolidOps")
        # Source part: the box
        self.src = self.addBody("Src")
        self.box = self.doc.addObject("PartDesign::AdditiveBox", "Box")
        self.box.Length, self.box.Width, self.box.Height = 20, 20, 10
        self.src.addObject(self.box)
        # Source part: the cylinder, far away
        self.cylBody = self.addBody("CylBody")
        self.cyl = self.doc.addObject("PartDesign::AdditiveCylinder", "Cyl")
        self.cyl.Radius, self.cyl.Height = 10, 20
        self.cylBody.addObject(self.cyl)
        self.cylBody.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        self.doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def addBody(self, name):
        return self.doc.addObject("PartDesign::Body", name)

    def top(self):
        return (self.box, [top_face_name(self.box.Shape)])

    def lateral(self):
        return (self.cyl, [lateral_face_name(self.cyl.Shape)])

    def newPart(self):
        return self.addBody("Part")

    def assertBox(self, shape, xmin, xmax, ymin, ymax, zmin, zmax, tol=1e-5):
        b = shape.BoundBox
        for got, want in ((b.XMin, xmin), (b.XMax, xmax), (b.YMin, ymin), (b.YMax, ymax), (b.ZMin, zmin), (b.ZMax, zmax)):
            self.assertAlmostEqual(got, want, delta=tol)

    def assertInvalid(self, feature, text):
        self.doc.recompute()
        self.assertIn("Invalid", feature.State, "expected a loud failure")
        self.assertIn(text.lower(), (feature.getStatusString() or "").lower())


class TestThicken(SolidOpsBase):
    def testPlanarOneSideIsAnExactSlab(self):
        part = self.newPart()
        t = S.make_thicken(part, [self.top()], 2.0, 0.0)
        self.doc.recompute()
        self.assertEqual(t.State, ["Up-to-date"])
        s = t.Shape
        self.assertAlmostEqual(s.Volume, 800.0, 5)
        self.assertAlmostEqual(s.Area, 960.0, 5)
        self.assertEqual(len(s.Faces), 6)
        self.assertBox(s, 0, 20, 0, 20, 10, 12)

    def testBothSides(self):
        part = self.newPart()
        t = S.make_thicken(part, [self.top()], 2.0, 1.0)
        self.doc.recompute()
        self.assertAlmostEqual(t.Shape.Volume, 1200.0, 5)
        self.assertBox(t.Shape, 0, 20, 0, 20, 9, 12)
        self.assertEqual(len(t.Shape.Faces), 6)

    def testOnlyTheOtherSide(self):
        part = self.newPart()
        t = S.make_thicken(part, [self.top()], 0.0, 3.0)
        self.doc.recompute()
        self.assertAlmostEqual(t.Shape.Volume, 1200.0, 5)
        self.assertBox(t.Shape, 0, 20, 0, 20, 7, 10)

    def testElementNamesAreMapped(self):
        part = self.newPart()
        t = S.make_thicken(part, [self.top()], 2.0, 0.0)
        self.doc.recompute()
        self.assertGreater(len(t.Shape.ElementMap), 6)
        self.assertTrue(any(";OFS" in k for k in t.Shape.ElementMap))

    def testCylinderOutAndIn(self):
        part = self.newPart()
        out = S.make_thicken(part, [self.lateral()], 1.0, 0.0)
        self.doc.recompute()
        self.assertAlmostEqual(out.Shape.Volume, math.pi * (121 - 100) * 20, 3)
        part2 = self.newPart()
        inn = S.make_thicken(part2, [self.lateral()], 0.0, 1.0)
        self.doc.recompute()
        self.assertAlmostEqual(inn.Shape.Volume, math.pi * (100 - 81) * 20, 3)

    def testAddMergesIntoThePart(self):
        part = self.addBody("AddPart")
        base = self.doc.addObject("PartDesign::AdditiveBox", "B2")
        base.Length, base.Width, base.Height = 20, 20, 10
        part.addObject(base)
        self.doc.recompute()
        t = S.make_thicken(part, [(base, [top_face_name(base.Shape)])], 2.0, 0.0)
        self.doc.recompute()
        self.assertEqual(t.State, ["Up-to-date"])
        self.assertAlmostEqual(t.Shape.Volume, 4800.0, 4)
        self.assertEqual(len(t.Shape.Solids), 1)
        self.assertEqual(len(t.Shape.Faces), 6)
        self.assertBox(t.Shape, 0, 20, 0, 20, 0, 12)

    def testRemoveCutsTheSlab(self):
        part = self.addBody("CutPart")
        base = self.doc.addObject("PartDesign::AdditiveBox", "B3")
        base.Length, base.Width, base.Height = 20, 20, 10
        part.addObject(base)
        self.doc.recompute()
        t = S.make_thicken(part, [(base, [top_face_name(base.Shape)])], 0.0, 2.0, "Subtraction")
        self.doc.recompute()
        self.assertEqual(t.State, ["Up-to-date"])
        self.assertAlmostEqual(t.Shape.Volume, 3200.0, 4)
        self.assertBox(t.Shape, 0, 20, 0, 20, 0, 8)

    def testIntersectKeepsTheOverlap(self):
        part = self.addBody("CommonPart")
        base = self.doc.addObject("PartDesign::AdditiveBox", "B4")
        base.Length, base.Width, base.Height = 20, 20, 10
        part.addObject(base)
        self.doc.recompute()
        t = S.make_thicken(part, [(base, [top_face_name(base.Shape)])], 2.0, 3.0, "Common")
        self.doc.recompute()
        self.assertAlmostEqual(t.Shape.Volume, 1200.0, 4)
        self.assertBox(t.Shape, 0, 20, 0, 20, 7, 10)

    def testTwoDisconnectedFaces(self):
        faces = self.box.Shape
        bottom = None
        for i, f in enumerate(faces.Faces):
            if abs(f.CenterOfMass.z) < 1e-6 and f.Surface.__class__.__name__ == "Plane":
                bottom = "Face%d" % (i + 1)
        part = self.newPart()
        t = S.make_thicken(part, [(self.box, [top_face_name(faces), bottom])], 1.0, 0.0)
        self.doc.recompute()
        self.assertEqual(t.State, ["Up-to-date"])
        self.assertAlmostEqual(t.Shape.Volume, 800.0, 4)
        self.assertEqual(len(t.Shape.Solids), 2)

    # ---- loud failures
    def testZeroThicknessFails(self):
        t = S.make_thicken(self.newPart(), [self.top()], 0.0, 0.0)
        self.assertInvalid(t, "thickness is zero")

    def testNoFaceFails(self):
        t = S.make_thicken(self.newPart(), [], 1.0, 0.0)
        self.assertInvalid(t, "select a face")

    def testNegativeThicknessFails(self):
        t = S.make_thicken(self.newPart(), [self.top()], 1.0, 0.0)
        with self.assertRaises(ValueError):
            t.Thickness1 = -1  # refused at the property, before any recompute

    def testRemoveWithNothingBeforeItFails(self):
        t = S.make_thicken(self.newPart(), [self.top()], 1.0, 0.0, "Subtraction")
        self.assertInvalid(t, "no merge scope selected")

    def testInwardBeyondTheRadiusFails(self):
        t = S.make_thicken(self.newPart(), [self.lateral()], 0.0, 12.0)
        self.doc.recompute()
        self.assertIn("Invalid", t.State, "a cylinder thickened inward past its radius must fail")

    def testSurvivesSaveAndReload(self):
        import os, tempfile

        part = self.newPart()
        S.make_thicken(part, [self.top()], 2.0, 1.0)
        self.doc.recompute()
        path = os.path.join(tempfile.mkdtemp(), "t.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        self.doc = App.openDocument(path)
        t = self.doc.getObject("Thicken")
        t.touch()
        self.doc.recompute()
        self.assertEqual(t.State, ["Up-to-date"])
        self.assertAlmostEqual(t.Shape.Volume, 1200.0, 4)
        self.assertEqual(t.Operation, "Union")
        t.Operation = "Subtraction"  # the widened list came back
        self.assertEqual(t.Operation, "Subtraction")


class TestScale(SolidOpsBase):
    def testUniformAboutAPoint(self):
        s = S.make_scale(self.src, App.Vector(5, 5, 5), 2.0)
        self.doc.recompute()
        self.assertEqual(s.State, ["Up-to-date"])
        self.assertAlmostEqual(s.Shape.Volume, 32000.0, 4)
        self.assertBox(s.Shape, -5, 35, -5, 35, -5, 15)
        self.assertEqual(len(s.Shape.Faces), 6)

    def testUniformAboutTheOriginKeepsTheCorner(self):
        s = S.make_scale(self.src, App.Vector(), 0.5)
        self.doc.recompute()
        self.assertAlmostEqual(s.Shape.Volume, 500.0, 5)
        self.assertBox(s.Shape, 0, 10, 0, 10, 0, 5)

    def testPerAxis(self):
        s = S.make_scale(self.src, App.Vector(), factors=(2.0, 1.0, 0.5))
        self.doc.recompute()
        self.assertAlmostEqual(s.Shape.Volume, 4000.0, 5)
        self.assertBox(s.Shape, 0, 40, 0, 20, 0, 5)
        self.assertAlmostEqual(s.Shape.Area, 2 * (40 * 20 + 40 * 5 + 20 * 5), 5)

    def testPerAxisAboutAPoint(self):
        s = S.make_scale(self.src, App.Vector(10, 10, 10), factors=(1.0, 2.0, 3.0))
        self.doc.recompute()
        self.assertBox(s.Shape, 0, 20, -10, 30, -20, 10)

    def testNamesSurvive(self):
        s = S.make_scale(self.src, App.Vector(), factors=(2.0, 1.0, 0.5))
        self.doc.recompute()
        self.assertGreater(len(s.Shape.ElementMap), 6)

    def testCylinderScalesAsAnEllipticCylinder(self):
        s = S.make_scale(self.cylBody, self.cyl.Shape.CenterOfMass, factors=(2.0, 1.0, 1.0))
        self.doc.recompute()
        # An ellipse of semi-axes 20 and 10: the volume integral of the NURBS the non-uniform
        # transform makes is good to about 1 %; the box is exact
        self.assertAlmostEqual(s.Shape.Volume, math.pi * 100 * 20 * 2, delta=0.015 * math.pi * 4000)
        c = self.cyl.Shape.CenterOfMass
        # BoundBox of a NURBS is its pole hull; the optimal box is the true extent
        b = s.Shape.optimalBoundingBox()
        for got, want in ((b.XMin, c.x - 20), (b.XMax, c.x + 20), (b.YMin, c.y - 10), (b.YMax, c.y + 10)):
            self.assertAlmostEqual(got, want, delta=1e-3)

    def testScaleAfterAnAddKeepsOnePart(self):
        t = S.make_thicken(self.src, [(self.box, [top_face_name(self.box.Shape)])], 2.0, 0.0)
        s = S.make_scale(self.src, App.Vector(), 2.0)
        self.doc.recompute()
        self.assertAlmostEqual(s.Shape.Volume, 4800.0 * 8, 3)

    # ---- loud failures
    def testZeroFactorFails(self):
        s = S.make_scale(self.src, App.Vector(), 0.0)
        self.assertInvalid(s, "greater than zero")

    def testNegativeFactorFails(self):
        s = S.make_scale(self.src, App.Vector(), factors=(1.0, -1.0, 1.0))
        self.assertInvalid(s, "greater than zero")

    def testNothingToScaleFails(self):
        s = S.make_scale(self.newPart(), App.Vector(), 2.0)
        self.assertInvalid(s, "nothing to scale")

    def testDependentFeatureFollowsTheScale(self):
        s = S.make_scale(self.src, App.Vector(), 2.0)
        pad = self.doc.addObject("PartDesign::AdditiveBox", "Late")
        pad.Length = pad.Width = pad.Height = 1
        pad.Placement = App.Placement(App.Vector(100, 100, 100), App.Rotation())
        self.src.addObject(pad)
        self.doc.recompute()
        self.assertAlmostEqual(self.src.Shape.Volume, 32000.0 + 1, 3)
        s.Factor = 3.0
        self.doc.recompute()
        self.assertAlmostEqual(self.src.Shape.Volume, 108000.0 + 1, 3)


class TestOffsetSurface(SolidOpsBase):
    def testPlanarOutAndFlipped(self):
        o = S.make_offset_surface(self.newPart(), [self.top()], 3.0)
        self.doc.recompute()
        self.assertEqual(o.State, ["Up-to-date"])
        self.assertAlmostEqual(o.Shape.Area, 400.0, 5)
        self.assertEqual(len(o.Shape.Faces), 1)
        self.assertBox(o.Shape, 0, 20, 0, 20, 13, 13)
        f = S.make_offset_surface(self.newPart(), [self.top()], 3.0, flip=True)
        self.doc.recompute()
        self.assertBox(f.Shape, 0, 20, 0, 20, 7, 7)

    def testNegativeDistance(self):
        o = S.make_offset_surface(self.newPart(), [self.top()], -3.0)
        self.doc.recompute()
        self.assertBox(o.Shape, 0, 20, 0, 20, 7, 7)

    def testCylinderOutAndIn(self):
        o = S.make_offset_surface(self.newPart(), [self.lateral()], 2.0)
        i = S.make_offset_surface(self.newPart(), [self.lateral()], -2.0)
        self.doc.recompute()
        self.assertAlmostEqual(o.Shape.Area, 2 * math.pi * 12 * 20, 3)
        self.assertAlmostEqual(i.Shape.Area, 2 * math.pi * 8 * 20, 3)

    def testTwoFaces(self):
        faces = self.box.Shape
        bottom = [
            "Face%d" % (i + 1)
            for i, f in enumerate(faces.Faces)
            if abs(f.CenterOfMass.z) < 1e-6 and f.Surface.__class__.__name__ == "Plane"
        ][0]
        o = S.make_offset_surface(self.newPart(), [(self.box, [top_face_name(faces), bottom])], 1.0)
        self.doc.recompute()
        self.assertAlmostEqual(o.Shape.Area, 800.0, 4)
        self.assertEqual(len(o.Shape.Faces), 2)

    def testNamesAreMapped(self):
        o = S.make_offset_surface(self.newPart(), [self.top()], 3.0)
        self.doc.recompute()
        self.assertTrue(any(";OFS" in k for k in o.Shape.ElementMap))

    def testFeatureAfterTheOffsetSeesTheSheet(self):
        part = self.newPart()
        o = S.make_offset_surface(part, [self.top()], 3.0)
        self.doc.recompute()
        self.assertEqual(part.Shape.ShapeType, "Shell")

    # ---- loud failures
    def testZeroDistanceFails(self):
        o = S.make_offset_surface(self.newPart(), [self.top()], 0.0)
        self.assertInvalid(o, "zero")

    def testNoFaceFails(self):
        o = S.make_offset_surface(self.newPart(), [], 1.0)
        self.assertInvalid(o, "select a face")

    def testInwardBeyondTheRadiusFails(self):
        o = S.make_offset_surface(self.newPart(), [self.lateral()], -12.0)
        self.doc.recompute()
        self.assertIn("Invalid", o.State, "a cylinder offset inward past its radius must fail")


def suite():
    s = unittest.TestSuite()
    for cls in (TestThicken, TestScale, TestOffsetSurface):
        s.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    return s


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite())
