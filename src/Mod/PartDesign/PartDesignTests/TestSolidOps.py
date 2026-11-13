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

    def xzPad(self, body):
        """A 20 x 10 rectangle on the Body's XZ plane padded 5: x 0..20, y -5..0, z 0..10 (round 3, SO1)."""
        plane = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"][0]
        sk = body.newObject("Sketcher::SketchObject", "XZSketch")
        sk.AttachmentSupport = [(plane, "")]
        sk.MapMode = "FlatFace"
        pts = [App.Vector(0, 0, 0), App.Vector(20, 0, 0), App.Vector(20, 10, 0), App.Vector(0, 10, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        pad = body.newObject("PartDesign::Pad", "XZPad")
        pad.Profile = sk
        pad.Length = 5
        self.doc.recompute()
        self.assertBox(pad.Shape, 0, 20, -5, 0, 0, 10)
        return pad

    def faceAtZ(self, feature, z):
        for i, f in enumerate(feature.Shape.Faces):
            if abs(f.BoundBox.ZMin - z) < 1e-6 and abs(f.BoundBox.ZMax - z) < 1e-6:
                return (feature, ["Face%d" % (i + 1)])
        raise AssertionError("no face at z = %g" % z)

    def globalBox(self, feature, body, *box):
        shape = feature.Shape.copy()
        shape.Placement = body.Placement.multiply(shape.Placement)
        self.assertBox(shape, *box)

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
    def testFaceOfAPlacedBodyThickensInPlace(self):
        """SO3: the face's own Body is placed; the slab lies on the face, in a part at the origin
        and in a placed one (Onshape has no Body placement)."""
        self.src.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        self.doc.recompute()
        t = S.make_thicken(self.newPart(), [self.top()], 2.0, 0.0)
        part2 = self.newPart()
        part2.Placement = App.Placement(App.Vector(0, 50, 0), App.Rotation())
        t2 = S.make_thicken(part2, [self.top()], 2.0, 0.0)
        self.doc.recompute()
        self.assertBox(t.Shape, 100, 120, 0, 20, 10, 12)
        self.globalBox(t2, part2, 100, 120, 0, 20, 10, 12)

    def testFaceOfAnXZPadThickensInPlace(self):
        pad = self.xzPad(self.addBody("XZ"))
        t = S.make_thicken(self.newPart(), [self.faceAtZ(pad, 10)], 2.0, 0.0)
        self.doc.recompute()
        self.assertBox(t.Shape, 0, 20, -5, 0, 10, 12)

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


class TestThickenOnshapeOptions(SolidOpsBase):
    def testDefaultIsFiveAlongTheNormal(self):
        t = S.make_thicken(self.newPart(), [self.top()])
        self.doc.recompute()
        self.assertBox(t.Shape, 0, 20, 0, 20, 10, 15)

    def testFlipPutsThicknessOneAgainstTheNormal(self):
        t = S.make_thicken(self.newPart(), [self.top()], 2.0, 3.0)
        t.Flip = True
        self.doc.recompute()
        self.assertBox(t.Shape, 0, 20, 0, 20, 8, 13)

    def testMidplaneUsesTheTotalThickness(self):
        t = S.make_thicken(self.newPart(), [self.top()])
        t.Midplane = True
        t.Thickness = 4.0
        self.doc.recompute()
        self.assertBox(t.Shape, 0, 20, 0, 20, 8, 12)


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
    def testScaleOfAPadOnTheXZPlaneStaysInPlace(self):
        """SO1: the Pad's Placement is the XZ sketch's; factor 1 changes nothing, 2 doubles about
        the origin, (2, 1, 1) stretches along x only."""
        for factors, box in (
            ((1.0, 1.0, 1.0), (0, 20, -5, 0, 0, 10)),
            ((2.0, 2.0, 2.0), (0, 40, -10, 0, 0, 20)),
            ((2.0, 1.0, 1.0), (0, 40, -5, 0, 0, 10)),
        ):
            with self.subTest(factors=factors):
                body = self.addBody("XZ")
                self.xzPad(body)
                if factors[0] == factors[1] == factors[2]:
                    s = S.make_scale(body, App.Vector(), factor=factors[0])
                else:
                    s = S.make_scale(body, App.Vector(), factors=factors)
                self.doc.recompute()
                self.assertEqual(s.State, ["Up-to-date"])
                self.assertBox(s.Shape, *box)
                self.assertBox(body.Shape, *box)

    def testPocketThroughANonUniformlyScaledCylinder(self):
        """Rehearsal 3's F1 against Onshape (oracle 5): cylinder r10 h20 scaled (2, 1, 1) about the
        origin, then a Pocket through all of a slot x 15..25, |y| < 5 and a hole r3. Onshape: valid,
        11174.645, x max 17.321 (the ellipse at y = 5). The geometry is exact; the volume is checked on
        a fine tessellation, since OCCT's volume integral of a rational B-spline is about 0.9 % high."""
        body = self.addBody("Ellipse")
        cyl = self.doc.addObject("PartDesign::AdditiveCylinder", "Round")
        cyl.Radius, cyl.Height = 10, 20
        body.addObject(cyl)
        S.make_scale(body, App.Vector(), factors=(2.0, 1.0, 1.0))
        plane = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
        sk = body.newObject("Sketcher::SketchObject", "Cuts")
        sk.AttachmentSupport = [(plane, "")]
        sk.MapMode = "FlatFace"
        pts = [App.Vector(15, -5, 0), App.Vector(25, -5, 0), App.Vector(25, 5, 0), App.Vector(15, 5, 0)]
        for i in range(4):
            sk.addGeometry(Part.LineSegment(pts[i], pts[(i + 1) % 4]))
        sk.addGeometry(Part.Circle(App.Vector(), App.Vector(0, 0, 1), 3))
        pocket = body.newObject("PartDesign::Pocket", "Through")
        pocket.Profile = sk
        pocket.Type = "ThroughAll"
        pocket.Midplane = True
        self.doc.recompute()
        self.assertEqual(pocket.State, ["Up-to-date"])
        shape = pocket.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        # exact: the ellipse x = 20 sqrt(1 - y^2 / 100), less the slot beyond x = 15 for |y| < 5, less the hole
        slot = 200 * (0.5 * math.sqrt(0.75) + math.asin(0.5)) - 150
        want = 20 * (math.pi * 200 - slot - math.pi * 9)
        pts, tris = shape.tessellate(0.001)
        got = sum(pts[a].dot(pts[b].cross(pts[c])) for a, b, c in tris) / 6
        self.assertAlmostEqual(got, want, delta=1e-4 * want)
        self.assertAlmostEqual(want, 11174.645, delta=0.5)  # Onshape's figure
        self.assertAlmostEqual(shape.optimalBoundingBox().XMax, 20 * math.sqrt(0.75), delta=1e-3)

    def testZeroFactorFails(self):
        s = S.make_scale(self.src, App.Vector(), 0.0)
        self.assertInvalid(s, "must be between")

    def testFactorRangeIsOnshapes(self):
        for factor, ok in ((1e-6, False), (2e5, False), (1e-4, True), (1e5, True)):
            part = self.newPart()
            b = self.doc.addObject("PartDesign::AdditiveBox", "B3")
            part.addObject(b)
            sc = S.make_scale(part, None, factor)
            self.doc.recompute()
            self.assertEqual("Invalid" not in sc.State, ok, "%g: %s" % (factor, sc.getStatusString()))

    def testNegativeFactorFails(self):
        s = S.make_scale(self.src, App.Vector(), factors=(1.0, -1.0, 1.0))
        self.assertInvalid(s, "must be between")

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

    def testNegativeDistanceIsRejected(self):
        o = S.make_offset_surface(self.newPart(), [self.top()], -3.0)
        self.assertInvalid(o, "negative")

    def testZeroDistanceIsACopy(self):
        o = S.make_offset_surface(self.newPart(), [self.top()], 0.0)
        self.doc.recompute()
        self.assertEqual(o.State, ["Up-to-date"])
        self.assertBox(o.Shape, 0, 20, 0, 20, 10, 10)

    def testDefaultDistanceIsFive(self):
        o = S.make_offset_surface(self.newPart(), [self.top()])
        self.doc.recompute()
        self.assertBox(o.Shape, 0, 20, 0, 20, 15, 15)

    def testAdjacentFacesAreOneSharpSheet(self):
        """Onshape OS2: top + front, 2: one sheet, the faces extended to meet (20x22 + 20x12 = 680)."""
        faces = self.box.Shape
        front = [
            "Face%d" % (i + 1)
            for i, f in enumerate(faces.Faces)
            if abs(f.CenterOfMass.y) < 1e-6 and f.Surface.__class__.__name__ == "Plane"
        ][0]
        o = S.make_offset_surface(self.newPart(), [(self.box, [top_face_name(faces), front])], 2.0)
        self.doc.recompute()
        self.assertEqual(o.State, ["Up-to-date"], o.getStatusString())
        self.assertEqual(len(o.Shape.Faces), 2)
        self.assertAlmostEqual(o.Shape.Area, 680.0, 3)

    def testCylinderOutAndIn(self):
        o = S.make_offset_surface(self.newPart(), [self.lateral()], 2.0)
        i = S.make_offset_surface(self.newPart(), [self.lateral()], 2.0, flip=True)
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
    def testNoFaceFails(self):
        o = S.make_offset_surface(self.newPart(), [], 1.0)
        self.assertInvalid(o, "select a face")

    def testZeroDistanceCopyOfAnXZPadFaceStaysInPlace(self):
        """SO2: a copy (distance 0) and an offset (3) of the top of a Pad on the XZ plane."""
        pad = self.xzPad(self.addBody("XZ"))
        copy = S.make_offset_surface(self.newPart(), [self.faceAtZ(pad, 10)], 0.0)
        moved = S.make_offset_surface(self.newPart(), [self.faceAtZ(pad, 10)], 3.0)
        self.doc.recompute()
        self.assertBox(copy.Shape, 0, 20, -5, 0, 10, 10)
        self.assertBox(moved.Shape, 0, 20, -5, 0, 13, 13)

    def testFaceOfAPlacedBodyOffsetsInPlace(self):
        """SO3 for Offset surface: the sheet lies above the face, wherever the two Bodies are."""
        self.src.Placement = App.Placement(App.Vector(100, 0, 0), App.Rotation())
        part = self.newPart()
        part.Placement = App.Placement(App.Vector(0, 50, 0), App.Rotation())
        o = S.make_offset_surface(part, [self.top()], 3.0)
        self.doc.recompute()
        self.globalBox(o, part, 100, 120, 0, 20, 13, 13)

    def testLinksToAnotherBodyAreInScope(self):
        """Rehearsal 3's F4: the face of another Body is a global link, so no out-of-scope warning."""
        o = S.make_offset_surface(self.newPart(), [self.top()], 3.0)
        t = S.make_thicken(self.newPart(), [self.top()], 3.0)
        for f in (o, t):
            self.assertEqual(f.getTypeIdOfProperty("Base"), "App::PropertyLinkSubListGlobal")

    def testInwardBeyondTheRadiusFails(self):
        o = S.make_offset_surface(self.newPart(), [self.lateral()], 12.0, flip=True)
        self.doc.recompute()
        self.assertIn("Invalid", o.State, "a cylinder offset inward past its radius must fail")


def suite():
    s = unittest.TestSuite()
    for cls in (TestThicken, TestThickenOnshapeOptions, TestScale, TestOffsetSurface):
        s.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(cls))
    return s


if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite())


class TestSolidOpsExpressions(SolidOpsBase):
    """Variables drive the main length of each feature, and keep driving it after save and reopen."""

    def addVariables(self):
        vs = self.doc.addObject("App::VarSet", "Variables")
        vs.addProperty("App::PropertyLength", "Thick")
        vs.addProperty("App::PropertyLength", "Dist")
        vs.addProperty("App::PropertyFloat", "Scl")
        vs.Thick, vs.Dist, vs.Scl = 2.0, 3.0, 2.0
        return vs

    def reopen(self):
        import os, tempfile

        path = os.path.join(tempfile.mkdtemp(), "e.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        return self.doc

    def testThickenExpression(self):
        vs = self.addVariables()
        t = S.make_thicken(self.newPart(), [self.top()], 1.0, 0.0)
        t.setExpression("Thickness1", "Variables.Thick")
        self.doc.recompute()
        self.assertAlmostEqual(t.Shape.Volume, 800.0, 4)
        vs.Thick = 5.0
        self.doc.recompute()
        self.assertAlmostEqual(t.Shape.Volume, 2000.0, 4)

    def testScaleExpression(self):
        vs = self.addVariables()
        part = self.newPart()
        b = self.doc.addObject("PartDesign::AdditiveBox", "B2")
        b.Length, b.Width, b.Height = 10, 10, 10
        part.addObject(b)
        sc = S.make_scale(part)
        sc.setExpression("Factor", "Variables.Scl")
        self.doc.recompute()
        self.assertAlmostEqual(sc.Shape.Volume, 8000.0, 2)
        vs.Scl = 3.0
        self.doc.recompute()
        self.assertAlmostEqual(sc.Shape.Volume, 27000.0, 2)

    def testScalePointComponentExpression(self):
        self.addVariables()
        part = self.newPart()
        b = self.doc.addObject("PartDesign::AdditiveBox", "B2")
        b.Length, b.Width, b.Height = 10, 10, 10
        part.addObject(b)
        sc = S.make_scale(part, None, 2.0)
        sc.setExpression("Point.x", "Variables.Thick * 5")  # 10 mm
        self.doc.recompute()
        self.assertAlmostEqual(sc.Shape.BoundBox.XMin, -10.0, 4)  # about x = 10: 0 -> -10, 10 stays

    def testOffsetExpression(self):
        vs = self.addVariables()
        o = S.make_offset_surface(self.newPart(), [self.top()], 1.0)
        o.setExpression("Distance", "Variables.Dist")
        self.doc.recompute()
        self.assertAlmostEqual(o.Shape.BoundBox.ZMin, 13.0, 5)
        vs.Dist = 4.0
        self.doc.recompute()
        self.assertAlmostEqual(o.Shape.BoundBox.ZMin, 14.0, 5)

    def testExpressionsSurviveSaveAndReopen(self):
        vs = self.addVariables()
        t = S.make_thicken(self.newPart(), [self.top()], 1.0, 0.0)
        t.setExpression("Thickness1", "Variables.Thick")
        part = self.newPart()
        b = self.doc.addObject("PartDesign::AdditiveBox", "B2")
        b.Length, b.Width, b.Height = 10, 10, 10
        part.addObject(b)
        sc = S.make_scale(part)
        sc.setExpression("Factor", "Variables.Scl")
        o = S.make_offset_surface(self.newPart(), [self.top()], 1.0)
        o.setExpression("Distance", "Variables.Dist")
        self.doc.recompute()
        self.reopen()
        vs = self.doc.getObject("Variables")
        t, sc, o = (self.doc.getObject(n) for n in ("Thicken", "Scale", "OffsetSurface"))
        for f, prop in ((t, "Thickness1"), (sc, "Factor"), (o, "Distance")):
            self.assertIn(prop, [p for p, _ in f.ExpressionEngine])
        # a changed variable recomputes each feature: the proxies are back
        vs.Thick, vs.Scl, vs.Dist = 5.0, 3.0, 4.0
        self.doc.recompute()
        for f in (t, sc, o):
            self.assertEqual(f.State, ["Up-to-date"], f.getStatusString())
        self.assertAlmostEqual(t.Shape.Volume, 2000.0, 4)
        self.assertAlmostEqual(sc.Shape.Volume, 27000.0, 2)
        self.assertAlmostEqual(o.Shape.BoundBox.ZMin, 14.0, 5)


# ---------------------------------------------------------------- Thicken of a bent bore (ops#640)


def ring_moment(R, d):
    """The integral of (d - x) over the part of the disc of radius R (centre at x = 0) with x <= d:
    the revolved volume per radian of that part about the line x = d (Pappus)."""
    if R <= d:
        return math.pi * R * R * d
    s = math.sqrt(R * R - d * d)
    area = d * s + R * R * math.asin(d / R) + R * R * math.pi / 2
    return d * area + 2.0 / 3.0 * s ** 3


def ring_moment_past(R, d):
    """The integral of (x - d) over the part of the same disc with x > d: the revolved volume per
    radian of the disc's part past the line x = d."""
    return max(0.0, ring_moment(R, d) - math.pi * R * R * d)


def annular_tube(centre, axis, r_in, r_out, length):
    t = Part.makeCylinder(r_out, length, centre, axis)
    return t.cut(Part.makeCylinder(r_in, length, centre, axis))


class TestThickenBend(unittest.TestCase):
    """A bore of radius 4 in a 40 x 30 x 20 box: down from the top, a bend about a line at distance
    `major` from the bore's centre, then a straight leg. The sheet is the bore's three faces (offset
    surface at 0); their normals point toward the bore's axis. At major 4 the bend is a horn torus.

    The rule (Onshape, notes/onshape-facts.md TK1-TK4): the result is the union of the ring swept along
    the bore, filled up to the bend's axis and nothing beyond it. Its volume: the two straight annular
    tubes, plus the near side of the ring revolved through the bend (Pappus, ring_moment), minus the
    tubes' overlap at the inner corner (their parts past the axis)."""

    def setUp(self):
        self.doc = App.newDocument("ThickenBend")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def bore(self, major, angle=90.0, leg=40.0):
        V = App.Vector
        z0 = 6.0 + major
        self.geo = (major, angle, leg, z0)
        ap, ad = V(15 + major, 0, z0), V(0, -1, 0)
        rot = App.Rotation(ad, angle)
        self.legStart = ap + rot.multVec(V(15, 15, z0) - ap)
        self.legDir = rot.multVec(V(0, 0, -1))
        disc = lambda c, n: Part.Face(Part.Wire(Part.makeCircle(4.0, c, n)))
        cut = [disc(V(15, 15, 20), V(0, 0, 1)).extrude(V(0, 0, z0 - 20)),
               disc(V(15, 15, z0), V(0, 0, 1)).revolve(ap, ad, angle),
               disc(self.legStart, self.legDir).extrude(self.legDir * leg)]
        a = self.doc.addObject("Part::Feature", "A")
        a.Shape = Part.makeBox(40, 30, 20).cut(cut).removeSplitter()
        names = tuple("Face%d" % (k + 1) for k, f in enumerate(a.Shape.Faces) if f.Surface.__class__.__name__ != "Plane")
        self.assertEqual(len(names), 3)
        srf = S.make_offset_surface(self.doc.addObject("PartDesign::Body", "S"), [(a, names)], 0.0, name="Srf")
        return srf

    def thicken(self, srf, t1=0.0, t2=0.0, midplane=None):
        t = S.make_thicken(self.doc.addObject("PartDesign::Body", "T"), [(srf, "")], 0.75, 0.0, name="Thk")
        if midplane is not None:
            t.Midplane, t.Thickness = True, midplane
        else:
            t.Thickness1, t.Thickness2 = t1, t2
        self.doc.recompute()
        self.assertEqual(srf.State, ["Up-to-date"], srf.getStatusString())
        return t

    def expected(self, r_in, r_out):
        major, angle, leg, z0 = self.geo
        V = App.Vector
        a = annular_tube(V(15, 15, z0), V(0, 0, 1), r_in, r_out, 20 - z0)
        b = annular_tube(self.legStart, self.legDir, r_in, r_out, 40 - (15 + major) if angle == 90.0 else leg)
        bend = math.radians(angle) * (ring_moment(r_out, major) - ring_moment(r_in, major))
        return a.Volume + b.Volume + bend - a.common(b).Volume

    def assertOneSolid(self, t, volume):
        self.assertEqual(t.State, ["Up-to-date"], t.getStatusString())
        s = t.Shape
        self.assertTrue(s.isValid())
        self.assertEqual(len(s.Solids), 1)
        self.assertAlmostEqual(s.Volume, volume, delta=2e-3)

    def assertBox(self, shape, *box):
        b = shape.optimalBoundingBox()  # BoundBox is loose on the B-spline caps
        for got, want in zip((b.XMin, b.XMax, b.YMin, b.YMax, b.ZMin, b.ZMax), box):
            self.assertAlmostEqual(got, want, delta=1e-4)

    def testFormulaGivesOnshapesVolume(self):
        self.bore(4.0)
        self.assertAlmostEqual(self.expected(3.25, 4.75), 1405.2049, delta=2e-3)  # TK1
        self.assertAlmostEqual(self.expected(3.25, 4.0), 636.8867, delta=2e-3)  # TK2
        self.assertAlmostEqual(self.expected(4.0, 4.75), 768.3182, delta=2e-3)  # TK3

    def testHornMidplaneIsTheSweptRing(self):
        t = self.thicken(self.bore(4.0), midplane=1.5)
        self.assertOneSolid(t, 1405.2049)  # Onshape TK1
        self.assertBox(t.Shape, 10.25, 40, 10.25, 19.75, 1.25, 20)
        # Onshape: 8 faces, 2 planes, 4 cylinders, 2 tori (the caps are planar B-splines here, as before)
        faces = t.Shape.Faces
        self.assertEqual(len(faces), 8)
        self.assertEqual(sum(1 for f in faces if f.findPlane() is not None), 2)
        self.assertEqual(sum(1 for f in faces if f.Surface.__class__.__name__ == "Cylinder"), 4)

    def testHornThinMidplane(self):
        t = self.thicken(self.bore(4.0), midplane=0.5)
        self.assertOneSolid(t, self.expected(3.75, 4.25))
        self.assertBox(t.Shape, 10.75, 40, 10.75, 19.25, 1.75, 20)

    def testHornTowardTheAxis(self):
        t = self.thicken(self.bore(4.0), t1=0.75)
        self.assertOneSolid(t, 636.8867)  # Onshape TK2
        self.assertBox(t.Shape, 11, 40, 11, 19, 2, 20)

    def testHornIntoTheMaterial(self):
        t = self.thicken(self.bore(4.0), t2=0.75)
        self.assertOneSolid(t, 768.3182)  # Onshape TK3
        self.assertBox(t.Shape, 10.25, 40, 10.25, 19.75, 1.25, 20)

    def testHornFlipIsTheOtherSide(self):
        t = self.thicken(self.bore(4.0), t1=0.75)
        t.Flip = True
        self.doc.recompute()
        self.assertOneSolid(t, 768.3182)

    def testHornAtSixtyDegrees(self):
        t = self.thicken(self.bore(4.0, angle=60.0, leg=5.0), midplane=1.5)
        self.assertOneSolid(t, self.expected(3.25, 4.75))

    def testRingPastTheAxisIsNotFolded(self):
        # major 4.5, 0.75 into the material: the outer ring (4.75) passes the axis. The whole-sheet offset
        # passed as valid though it folds over itself near the axis (764.2319, the union is 764.2100).
        t = self.thicken(self.bore(4.5), t2=0.75)
        self.assertOneSolid(t, self.expected(4.0, 4.75))
        self.assertBox(t.Shape, 10.25, 40, 10.25, 19.75, 1.25, 20)

    def testRingTorusIsUnchanged(self):
        t = self.thicken(self.bore(8.0), midplane=1.5)
        self.assertOneSolid(t, 1340.8206)  # Onshape TK4; pi (4.75^2 - 3.25^2) (6 + 4 pi + 17)

    def testSharpSheetWithABendAtItsAxisFails(self):
        srf = self.bore(4.0)
        a = self.doc.getObject("A")
        top = [k for k, f in enumerate(a.Shape.Faces) if abs(f.BoundBox.ZMin - 20) < 1e-6][0]
        srf.Base = [(a, srf.Base[0][1] + ("Face%d" % (top + 1),))]
        t = self.thicken(srf, midplane=1.5)
        self.assertIn("Invalid", t.State, "a sharp edge next to the bend must fail loudly")
        self.assertIn("sharp edge", t.getStatusString())

    def testUndoRedo(self):
        self.doc.UndoMode = 1
        t = self.thicken(self.bore(4.0), midplane=1.5)
        self.doc.openTransaction("thinner")
        t.Thickness = 0.5
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertOneSolid(t, self.expected(3.75, 4.25))
        self.doc.undo()
        self.doc.recompute()
        self.assertOneSolid(t, 1405.2049)
        self.doc.redo()
        self.doc.recompute()
        self.assertOneSolid(t, self.expected(3.75, 4.25))

    def testSurvivesSaveAndReopen(self):
        import os, tempfile

        self.thicken(self.bore(4.0), midplane=1.5)
        path = os.path.join(tempfile.mkdtemp(), "bend.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        t = self.doc.getObject("Thk")
        self.assertAlmostEqual(t.Shape.Volume, 1405.2049, delta=2e-3)
        t.touch()
        self.doc.recompute()
        self.assertOneSolid(t, 1405.2049)

    def testHornBoreFacesPickedDirectly(self):
        # review r1 T4: the bore's faces picked off the solid, no Offset surface between
        self.bore(4.0)
        a = self.doc.getObject("A")
        names = tuple("Face%d" % (k + 1) for k, f in enumerate(a.Shape.Faces) if f.Surface.__class__.__name__ != "Plane")
        t = S.make_thicken(self.doc.addObject("PartDesign::Body", "T"), [(a, names)], 0.75, 0.0, name="Thk")
        t.Midplane, t.Thickness = True, 1.5
        self.doc.recompute()
        self.assertOneSolid(t, 1405.2049)  # Onshape TK1


class TestThickenPipe(unittest.TestCase):
    """The lateral faces of a solid pipe of radius 4 (normals away from the tube's axis): legs of
    `leg` along z down to the bend and out of it, a bend through `angle` about the line x = 0, z = 0
    (direction -y) at distance `major` from the tube's axis. Expected volumes as TestThickenBend: with
    legs, the union of the two annular tubes and the ring's near side revolved (the ring's part past the
    axis sweeps inside the first leg); a lone bend, both sides of the ring revolved apart."""

    def setUp(self):
        self.doc = App.newDocument("ThickenPipe")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def pipe(self, major, angle, leg, along=False):
        """along: the bend's profile disc faces along the motion, which gives OCC's torus the other frame."""
        V = App.Vector
        ax = V(0, -1, 0)
        self.geo = (major, angle, leg)
        self.c0 = V(-major, 0, 0)
        rot = App.Rotation(ax, angle)
        self.c1, self.d1 = rot.multVec(self.c0), rot.multVec(V(0, 0, -1))
        disc = lambda c, n: Part.Face(Part.Wire(Part.makeCircle(4.0, c, n)))
        sol = disc(self.c0, V(0, 0, -1 if along else 1)).revolve(V(0, 0, 0), ax, angle)
        if leg:
            sol = sol.fuse([disc(self.c0 + V(0, 0, leg), V(0, 0, -1)).extrude(V(0, 0, -leg)),
                            disc(self.c1, self.d1).extrude(self.d1 * leg)]).removeSplitter()
        self.assertTrue(sol.isValid())
        p = self.doc.addObject("Part::Feature", "P")
        p.Shape = Part.Shell([f for f in sol.Faces if f.Surface.__class__.__name__ != "Plane"])
        return p

    def thicken(self, sheet, t1=0.0, t2=0.0, midplane=None):
        t = S.make_thicken(self.doc.addObject("PartDesign::Body", "T"), [(sheet, "")], 0.75, 0.0, name="Thk")
        if midplane is not None:
            t.Midplane, t.Thickness = True, midplane
        else:
            t.Thickness1, t.Thickness2 = t1, t2
        self.doc.recompute()
        return t

    def expected(self, r_in, r_out):
        major, angle, leg = self.geo
        near = ring_moment(r_out, major) - ring_moment(r_in, major)
        if not leg:
            far = ring_moment_past(r_out, major) - ring_moment_past(r_in, major)
            return math.radians(angle) * (near + far)
        a = annular_tube(self.c0, App.Vector(0, 0, 1), r_in, r_out, leg)
        b = annular_tube(self.c1, self.d1, r_in, r_out, leg)
        return a.Volume + b.Volume + math.radians(angle) * near - a.common(b).Volume

    def assertOneSolid(self, t, volume):
        self.assertEqual(t.State, ["Up-to-date"], t.getStatusString())
        self.assertTrue(t.Shape.isValid())
        self.assertEqual(len(t.Shape.Solids), 1)
        self.assertAlmostEqual(t.Shape.Volume, volume, delta=2e-3)

    def assertRightOrLoud(self, t, volume):
        """Never a valid-looking wrong solid (decision 150: where a case can't be kept right, it stops)."""
        if "Invalid" in t.State:
            text = t.getStatusString()
            self.assertTrue("Thicken failed" in text or "time limit" in text, text)
            return
        self.assertOneSolid(t, volume)

    def testACollapsedFuseIsRefused(self):
        # review r1 T1: at 150 degrees with 5 mm legs (whose rings collide), a list fuse collapsed into one
        # valid solid of 66.64 for 349.71, and it passed. Now each try must hold points inside every piece.
        # (That case now ends at the geometry time limit, leaving a fuse running: it is not run here.)
        V = App.Vector
        a, b = Part.makeBox(10, 10, 10), Part.makeBox(10, 10, 10, V(10, 0, 0))
        res = S._fused([a, b], [V(5, 5, 5), V(15, 5, 5)])
        self.assertFalse(S._self_intersects(res, False))
        self.assertAlmostEqual(res.Volume, 2000.0, 6)
        with self.assertRaises(S.SolidOpsError):
            S._fused([a, b], [V(5, 5, 5), V(25, 5, 5)])  # a point the union misses: refused

    def testHornAtSeveralAngles(self):
        for angle in (90.0, 120.0, 135.0):
            for t1, t2 in ((0.75, 0.75), (0.75, 0.0), (0.0, 0.75)):
                with self.subTest(angle=angle, t1=t1, t2=t2):
                    t = self.thicken(self.pipe(4.0, angle, 5.0), t1=t1, t2=t2)
                    self.assertOneSolid(t, self.expected(4.0 - t2, 4.0 + t1))
                    App.closeDocument(self.doc.Name)
                    self.doc = App.newDocument("ThickenPipe")

    def testUTurnBendsAreRightOrLoud(self):
        # review r2: from about 165 degrees with legs, a fuse self-intersected yet passed isValid and the
        # probes (179 degrees outward: 457.6411 for 457.6189); BOPAlgo's check now refuses it
        for angle, t1, t2 in ((179.0, 0.75, 0.0), (175.0, 0.75, 0.75), (165.0, 0.75, 0.0)):
            with self.subTest(angle=angle, t1=t1, t2=t2):
                t = self.thicken(self.pipe(4.0, angle, 5.0), t1=t1, t2=t2)
                self.assertRightOrLoud(t, self.expected(4.0 - t2, 4.0 + t1))
                if "Invalid" not in t.State:
                    self.assertFalse(S._self_intersects(t.Shape, False))
                App.closeDocument(self.doc.Name)
                self.doc = App.newDocument("ThickenPipe")

    def testLoneHornBendCrossingItsAxisIsNotCutShort(self):
        # review r1 T2: with no leg beside it, the ring's part past the axis was dropped (238.1069 for
        # 239.3432). At 90 degrees the two sides' sweeps meet only along the axis: two solids, so it fails.
        t = self.thicken(self.pipe(4.0, 90.0, 0.0), midplane=1.5)
        self.assertIn("Invalid", t.State)
        self.assertIn("not one valid solid", t.getStatusString())
        t = self.thicken(self.pipe(4.0, 180.0, 0.0), midplane=1.5)
        self.assertRightOrLoud(t, self.expected(3.25, 4.75))

    def testLoneHornBendTowardTheCentre(self):
        # the ring touches the axis at a point only: one solid, the ring revolved
        t = self.thicken(self.pipe(4.0, 90.0, 0.0), t2=0.75)
        self.assertOneSolid(t, self.expected(3.25, 4.0))

    def testBendWithReversedTorusFrame(self):
        # review r3 TK-R3-HAND: with the profile facing along the motion, the torus's Axis is the sweep's
        # reversed; the ring was revolved the mirrored way (loud at 90 degrees; from about 240 degrees a
        # valid wrong solid, 513.1220 for 564.5646 at 270). The bend's ring just touches its axis here.
        axes = []
        for angle in (90.0, 270.0):
            for along in (False, True):
                with self.subTest(angle=angle, along=along):
                    p = self.pipe(4.75, angle, 0.0, along)
                    axes.append(p.Shape.Faces[0].Surface.Axis.y)
                    t = self.thicken(p, t1=0.75)
                    self.assertOneSolid(t, self.expected(4.0, 4.75))
                    V = App.Vector
                    # the wall's middle, 9.125 from the bend's axis: inside at 45 degrees, outside past the bend
                    at = lambda a: App.Rotation(V(0, -1, 0), a).multVec(V(-9.125, 0, 0))
                    self.assertTrue(t.Shape.isInside(at(45.0), 1e-6, True))
                    self.assertFalse(t.Shape.isInside(at(angle + 45.0), 1e-6, True))
                    App.closeDocument(self.doc.Name)
                    self.doc = App.newDocument("ThickenPipe")
        self.assertTrue(min(axes) < 0 < max(axes), axes)  # both torus frames were met

    def testObliqueLoneBendTouchingItsAxis(self):
        # review r4 TK-R4-OBLIQUE: a lone bend whose ring touches its axis, turned 30 degrees about x and
        # moved, came out one valid solid of 654.0505 for 461.4811 (OCC's revolve about the oblique axis).
        # Each revolved piece must now hold its exact (Pappus) volume: right, or it stops.
        V = App.Vector
        pl = App.Placement(V(7, -3, 11), App.Rotation(V(1, 0, 0), 30))
        o, ax = V(4.75, 0, 0), V(0, 1, 0)
        at = lambda a: pl.multVec(o + App.Rotation(ax, a).multVec(V(-9.125, 0, 0)))  # the wall's middle
        for angle in (270.0, 200.0):
            for baked in (True, False):
                with self.subTest(angle=angle, baked=baked):
                    disc = Part.Face(Part.Wire(Part.makeCircle(4.0, V(0, 0, 0), V(0, 0, 1))))
                    sol = disc.revolve(o, ax, angle)
                    sheet = Part.Shell([f for f in sol.Faces if f.Surface.__class__.__name__ != "Plane"])
                    a = self.doc.addObject("Part::Feature", "A")
                    if baked:
                        sheet.transformShape(pl.toMatrix(), True)
                        a.Shape = sheet
                    else:
                        part = self.doc.addObject("App::Part", "Part")
                        part.Placement = pl
                        a.Shape = sheet
                        part.addObject(a)
                    t = self.thicken(a, t1=0.75)
                    volume = math.radians(angle) * math.pi * 4.75 * (4.75 ** 2 - 16)
                    self.assertRightOrLoud(t, volume)
                    if "Invalid" not in t.State:
                        self.assertTrue(t.Shape.isInside(at(0.5 * angle), 1e-6, True))
                        self.assertFalse(t.Shape.isInside(at(0.5 * (angle + 360.0)), 1e-6, True))
                    App.closeDocument(self.doc.Name)
                    self.doc = App.newDocument("ThickenPipe")

    def testSelfCheckThatCannotRunRefuses(self):
        # review r3 F-OPEN: a BOPAlgo check that aborts or gives no report must not pass the fuse
        class Stub:
            def __init__(self, text):
                self.text = text

            def check(self, _):
                if self.text is not None:
                    raise RuntimeError(self.text)

        head = "BOP check found the following errors:\n"
        self.assertFalse(S._self_intersects(Stub(None), False))
        self.assertTrue(S._self_intersects(Stub("Standard_Failure"), False))
        self.assertTrue(S._self_intersects(Stub(head), False))
        self.assertTrue(S._self_intersects(Stub(head + "Error in Face: BOPAlgo OperationAborted"), True))
        self.assertTrue(S._self_intersects(Stub(head + "Error in Solid: BOPAlgo CheckUnknown"), True))
        self.assertTrue(S._self_intersects(Stub(head + "Error in Face: BOPAlgo SelfIntersect"), True))
        self.assertTrue(S._self_intersects(Stub(head + "Error in Edge: BOPAlgo SelfIntersect"), False))
        self.assertFalse(S._self_intersects(Stub(head + "Error in Edge: BOPAlgo SelfIntersect"), True))
        self.assertFalse(S._self_intersects(Stub(head + "Error in Edge: BOPAlgo_InvalidCurveOnSurface"), False))

    def testHornTorusWithItsSeamAwayFromTheAxis(self):
        # review r1 T3: the face's middle (in v) is the horn's apex, where it has no normal
        V = App.Vector
        c = Part.Circle(V(4, 0, 0), V(0, -1, 0), 4.0)
        c.XAxis = V(1, 0, 0)  # the seam at the point farthest from the axis
        surf = c.toShape().revolve(V(0, 0, 0), V(0, 0, 1), 360).Faces[0].Surface
        f = self.doc.addObject("Part::Feature", "F")
        f.Shape = surf.toShape(0, math.pi / 2, 0, 2 * math.pi)
        self.geo = (4.0, 90.0, 0.0)
        face = f.Shape.Faces[0]
        p = face.valueAt(math.pi / 4, 0.0)  # the seam, farthest from the axis
        outward = face.normalAt(math.pi / 4, 0.0).dot(p - V(4 * math.cos(math.pi / 4), 4 * math.sin(math.pi / 4), 0)) > 0
        t = self.thicken(f, t1=0.0 if outward else 0.75, t2=0.75 if outward else 0.0)  # toward the ring's centre
        self.assertOneSolid(t, self.expected(3.25, 4.0))


class TestThickenObliqueLeg(unittest.TestCase):
    """A straight leg of a bent bore that ends obliquely (#90, ops#640), beside a horn bend, so that
    Thicken builds the sheet face by face. The leg's piece is a cylinder face thickened alone. Its exact
    volume (Steiner): the layer at signed distance s from the face (s > 0 away from the axis) has the face's
    area times (R + s) / R, so a piece from s = a to s = b holds area (b - a) (1 + (a + b) / (2 R)).

    On the replica (#90), OCC's offset of such a leg (a full turn whose free end is two edges meeting at a
    degree-1 B-spline seam) built twisted caps along the end: a valid-looking 763.83 for 279.17, then
    "folds over itself". Here the guard is tested with a wrong offset put in OCC's place and the direct
    construction for exactness on designed oblique legs; TestThickenSeamLeg builds that seam itself."""

    R = 4.0

    def setUp(self):
        self.doc = App.newDocument("ThickenOblique")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def bore(self, tilt, ridge=True):
        """The bore of TestThickenBend at major 4 (a horn bend), its leg leaving through a wall at x = 40
        made of two planes meeting along the line through the leg's axis (y direction): each turned by
        `tilt` degrees from x = 40, the lower one the other way round when ridge (a "<" wall), else one
        tilted plane. The circles' x axes are fixed so the faces' seams are reproducible."""
        V = App.Vector
        R, major = self.R, 4.0
        z0 = 6.0 + major
        ap, ad = V(15 + major, 0, z0), V(0, -1, 0)
        rot = App.Rotation(ad, 90.0)
        ls = ap + rot.multVec(V(15, 15, z0) - ap)
        ld = rot.multVec(V(0, 0, -1))
        self.leg = (ls, ld)

        def disc(c, n, x):
            ci = Part.Circle(c, n, R)
            ci.XAxis = x
            return Part.Face(Part.Wire(ci.toShape()))

        cut = [disc(V(15, 15, 20), V(0, 0, 1), V(1, 0, 0)).extrude(V(0, 0, z0 - 20)),
               disc(V(15, 15, z0), V(0, 0, 1), V(0, -1, 0)).revolve(ap, ad, 90.0),
               disc(ls, ld, V(0, -1, 0)).extrude(ld * 40)]
        zc, h = ls.z, 30.0
        dx = h * math.tan(math.radians(tilt))
        pts = [V(40, -1, zc), V(40 + dx, -1, zc + h), V(100, -1, zc + h), V(100, -1, zc - h),
               V(40 + (dx if ridge else -dx), -1, zc - h), V(40, -1, zc)]
        self.wedge = Part.Face(Part.makePolygon(pts)).extrude(V(0, 32, 0))
        a = self.doc.addObject("Part::Feature", "A")
        a.Shape = Part.makeBox(80, 30, 20).cut(self.wedge).cut(cut)
        names = tuple("Face%d" % (k + 1) for k, f in enumerate(a.Shape.Faces) if f.Surface.__class__.__name__ != "Plane")
        self.assertEqual(len(names), 4)  # the two legs, and the bend split in two by these seams
        return a, names

    def legFace(self, a, names):
        legs = [a.Shape.getElement(n) for n in names
                if a.Shape.getElement(n).Surface.__class__.__name__ == "Cylinder"
                and any(e.Curve.__class__.__name__ == "Ellipse" for e in a.Shape.getElement(n).Edges)]
        self.assertEqual(len(legs), 1)
        return legs[0]

    def steiner(self, face, t1, t2):
        """The exact volume of the face's piece; a bore's faces point toward the axis, so t1 goes inward."""
        a, b = -t1, t2
        return face.Area * (b - a) * (1.0 + (a + b) / (2.0 * self.R))

    def testDirectPieceIsExact(self):
        for tilt, ridge in ((20.0, True), (3.6, True), (20.0, False)):
            leg = self.legFace(*self.bore(tilt, ridge))
            for t1, t2 in ((0.75, 0.75), (0.75, 0.0), (0.0, 0.75), (1.5, 0.25)):
                with self.subTest(tilt=tilt, ridge=ridge, t1=t1, t2=t2):
                    _, out = S._cylinder_piece_volume(leg, t1, t2)
                    self.assertEqual(out, -1.0)  # a bore's face points toward its axis
                    p = S._ruled_cylinder_piece(leg, t1, t2, out)
                    self.assertTrue(p.isValid())
                    self.assertEqual(len(p.Solids), 1)
                    self.assertAlmostEqual(p.Volume, self.steiner(leg, t1, t2), delta=1e-6)
                    # each cap is ruled along the face's normals: the end edge's points moved radially
                    for e in leg.Edges:
                        if e.Curve.__class__.__name__ != "Ellipse":
                            continue
                        q = e.valueAt(0.5 * (e.FirstParameter + e.LastParameter))
                        foot = self.leg[0] + self.leg[1] * (q - self.leg[0]).dot(self.leg[1])
                        mid = foot + (q - foot) * ((self.R + 0.5 * (t2 - t1)) / self.R)
                        self.assertLess(p.distToShape(Part.Vertex(mid))[0], 1e-6)

    def testAWrongOffsetIsRebuilt(self):
        leg = self.legFace(*self.bore(20.0))
        real = S._offset_piece
        try:
            # OCC's twisted caps on the replica: one valid solid of the wrong volume; then one that throws
            for wrong in (lambda f, t1, t2: Part.makeBox(5, 5, 5), lambda f, t1, t2: Part.Shape().makeOffsetShape(1, 1)):
                with self.subTest(wrong=wrong):
                    S._offset_piece = wrong
                    p = S._leg_piece(leg, 0.75, 0.75)
                    self.assertTrue(p.isValid())
                    self.assertAlmostEqual(p.Volume, self.steiner(leg, 0.75, 0.75), delta=1e-6)
        finally:
            S._offset_piece = real

    def testARightOffsetIsKept(self):
        leg = self.legFace(*self.bore(20.0))
        p = S._leg_piece(leg, 0.75, 0.75)
        self.assertAlmostEqual(p.Volume, self.steiner(leg, 0.75, 0.75), delta=1e-6)
        self.assertEqual(len(p.Faces), len(S._offset_piece(leg, 0.75, 0.75).Faces))

    def testAWrongPieceThatCantBeRebuiltFails(self):
        leg = self.legFace(*self.bore(20.0))
        real, direct = S._offset_piece, S._ruled_cylinder_piece
        try:
            S._offset_piece = lambda f, t1, t2: Part.makeBox(5, 5, 5)
            S._ruled_cylinder_piece = lambda f, t1, t2, out: Part.makeBox(6, 6, 6)
            with self.assertRaises(S.SolidOpsError):
                S._leg_piece(leg, 0.75, 0.75)
        finally:
            S._offset_piece, S._ruled_cylinder_piece = real, direct

    def testHornBendWithAVShapedLegEnd(self):
        # the sheet thickened face by face (the bend's ring reaches its axis). Expected: the two annular
        # tubes (the leg's cut by the "<" wall) and the bend's near side revolved (TestThickenBend), less
        # the tubes' overlap; the leg's end caps follow its normals, not the wall's planes, which takes
        # 8/3 t^3 tan(tilt) off the cut tube (each ruling keeps the end's x; integrated over both halves)
        tilt, t = 3.6, 0.75
        a, names = self.bore(tilt)
        th = S.make_thicken(self.doc.addObject("PartDesign::Body", "T"), [(a, names)], 0.75, 0.0, name="Thk")
        th.Midplane, th.Thickness = True, 2 * t
        self.doc.recompute()
        self.assertEqual(th.State, ["Up-to-date"], th.getStatusString())
        V = App.Vector
        ls, ld = self.leg
        z0 = 10.0
        A = annular_tube(V(15, 15, z0), V(0, 0, 1), self.R - t, self.R + t, 20 - z0)
        B = annular_tube(ls, ld, self.R - t, self.R + t, 60).cut(self.wedge)
        bend = math.radians(90) * (ring_moment(self.R + t, 4.0) - ring_moment(self.R - t, 4.0))
        want = A.Volume + B.Volume + bend - A.common(B).Volume - 8.0 / 3.0 * t ** 3 * math.tan(math.radians(tilt))
        s = th.Shape
        self.assertTrue(s.isValid())
        self.assertEqual(len(s.Solids), 1)
        self.assertAlmostEqual(s.Volume, want, delta=2e-3)


class TestThickenSeamLeg(unittest.TestCase):
    """A bore's straight leg cut as two half cylinders, so that removeSplitter leaves one full-turn face
    whose seam is a degree-1 B-spline, ending in an oblique plane (ops#640 remote brief 2). OCC's offset of
    that face comes out invalid, alone (the whole-sheet path) and beside a horn bend (face by face).
    Box 60 x 40 x 30, its +x end cut by a vertical plane through (50, 20, 8) turned `tilt` degrees about z.
    Bore r 4: down from (20, 20, 30), a 90 degree bend about a -y line `major` from the bore's axis, a leg
    along +x at z = 8 out through that plane (major None: a straight bore along x from x = 0).

    Expected: the ring swept along the sheet; a plane end cut leaves the volume at the ring's area times the
    axis length (the end is ruled along the sheet's normals: x max = 50 + r tan(tilt)), a bend adds the
    ring's area times the arc of its centroid (Pappus). The bore's faces point toward its axis: t1 goes
    inward. Onshape (oracle 16, TK5-TK6) builds the horn bend thickened 0.75 inward: V 858.957221, tight box
    16, 16, 4 .. 52.3094, 24, 30; it fails the same bend at midplane 1.5, which stays loud here."""

    def setUp(self):
        self.doc = App.newDocument("ThickenSeamLeg")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sheet(self, major, tilt=30.0, halves=True):
        V = App.Vector
        box = Part.makeBox(60, 40, 30)
        h = Part.makeBox(200, 200, 200, V(0, -100, -100))
        h.Placement = App.Placement(V(50, 20, 8), App.Rotation(V(0, 0, 1), tilt))
        s, x0 = box.cut(h), -5.0
        if major is not None:
            disc = Part.Face(Part.Wire(Part.makeCircle(4.0, V(20, 20, 8 + major), V(0, 0, 1))))
            top = Part.Face(Part.Wire(Part.makeCircle(4.0, V(20, 20, 30), V(0, 0, 1))))
            s = s.cut(top.extrude(V(0, 0, major - 22))).cut(disc.revolve(V(20 + major, 0, 8 + major), V(0, -1, 0), 90))
            x0 = 20 + major
        c = Part.makeCylinder(4.0, 80, V(x0, 20, 8), V(1, 0, 0))
        hb = Part.makeBox(100, 20, 20, V(-10, 20, -2))
        for t in ([c.common(hb), c.cut(hb)] if halves else [c]):
            s = s.cut(t)
        a = self.doc.addObject("Part::Feature", "A")
        a.Shape = s.removeSplitter()
        bore = tuple("Face%d" % (k + 1) for k, f in enumerate(a.Shape.Faces) if f.Surface.__class__.__name__ != "Plane")
        srf = S.make_offset_surface(self.doc.addObject("PartDesign::Body", "S"), [(a, bore)], 0.0, False, name="Srf")
        self.doc.recompute()
        leg = [f for f in srf.Shape.Faces if f.Surface.__class__.__name__ == "Cylinder" and abs(f.Surface.Axis.x) > 0.99]
        self.assertEqual(len(leg), 1)
        if halves:  # the seam the brief describes
            self.assertIn("BSplineCurve", [e.Curve.__class__.__name__ for e in leg[0].Edges])
        return srf, leg[0]

    def thicken(self, srf, t1, t2, midplane=False):
        th = S.make_thicken(self.doc.addObject("PartDesign::Body", "T"), [(srf, "")], t1, t2, "Union", name="Thk")
        if midplane:
            th.Midplane, th.Thickness = True, t1 + t2
        self.doc.recompute()
        self.assertEqual(th.State, ["Up-to-date"], th.getStatusString())
        s = th.Shape
        self.assertTrue(s.isValid())
        self.assertEqual(len(s.Solids), 1)
        self.assertExactEdges(s)
        return s

    def assertExactEdges(self, s):
        # every edge valid and the box computable on an untessellated copy (remote brief 3: an edge whose range
        # lies outside its curve breaks a later feature's result check, Geom_BSplineCurve::Segment)
        self.assertEqual([k + 1 for k, e in enumerate(s.Edges) if not e.isValid()], [])
        self.assertTrue(s.copy().BoundBox.isValid())

    def testLegPieceEdgesAreExact(self):
        # the leg's own piece, rebuilt where OCC's offset is wrong (_ruled_cylinder_piece), on brief 2's oblique leg
        for t1, t2 in ((0.75, 0.0), (0.0, 0.75), (0.75, 0.75)):
            with self.subTest(t1=t1, t2=t2):
                _, leg = self.sheet(None)
                p = S._leg_piece(leg, t1, t2)
                self.assertTrue(p.isValid())
                self.assertExactEdges(p)

    def assertBox(self, s, lo, hi):
        b = s.optimalBoundingBox(False, False)
        for got, want in zip((b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax), lo + hi):
            self.assertAlmostEqual(got, want, delta=1e-3)

    def testOffsetOfTheSeamLegIsInvalid(self):
        # the trigger, kept visible: if OCC ever builds this offset right, the guards below are moot
        _, leg = self.sheet(None)
        p = S._offset_piece(leg, 0.75, 0.75)
        self.assertFalse(p.isValid())

    def testHornBendInwardIsOnshapes(self):
        srf, _ = self.sheet(4.0)
        s = self.thicken(srf, 0.75, 0.0)
        self.assertAlmostEqual(s.Volume, 858.957221, delta=1e-3)  # = pi (4^2 - 3.25^2) (18 + 26 + 2 pi)
        self.assertBox(s, (16, 16, 4), (50 + 4 * math.tan(math.radians(30)), 24, 30))

    def testHornBendInwardCutsAsASolid(self):
        # a later feature's boolean on the thick tube works (ops#640, rb 93: the top ring cap rebuilt on a plane
        # kept its seam edge, a slit there, and every boolean on the solid came back empty). The half space
        # x > 45 takes the leg's end: the rulings keep x, so that part is the ring times 5 whatever the tilt
        srf, _ = self.sheet(4.0)
        s = self.thicken(srf, 0.75, 0.0)
        for f in s.Faces:
            if isinstance(f.Surface, Part.Plane):
                self.assertEqual([k for k, e in enumerate(f.Edges) if e.isSeam(f)], [])
        half = Part.makeBox(100, 100, 100, App.Vector(45, -30, -30))
        cut, common = s.cut(half), s.common(half)
        self.assertEqual((len(cut.Solids), len(common.Solids)), (1, 1))
        self.assertAlmostEqual(common.Volume, 5 * math.pi * (16 - 3.25 ** 2), delta=1e-4)
        self.assertAlmostEqual(cut.Volume + common.Volume, s.Volume, delta=1e-4)
        # the refined cut keeps its volume (on the leg's C0 NURBS radius faces a refine merged faces wrongly)
        self.assertAlmostEqual(cut.removeSplitter().Volume, cut.Volume, delta=1e-6)

    def testLegPieceRadiusFacesAreCylinders(self):
        # the rebuilt leg piece's faces at the two radii are exact cylinders, coaxial with the leg
        _, leg = self.sheet(None)
        for t1, t2 in ((0.75, 0.0), (0.0, 0.75), (0.75, 0.75)):
            with self.subTest(t1=t1, t2=t2):
                p = S._ruled_cylinder_piece(leg, t1, t2, S._cylinder_piece_volume(leg, t1, t2)[1])
                radii = sorted(round(f.Surface.Radius, 9) for f in p.Faces if isinstance(f.Surface, Part.Cylinder))
                self.assertEqual(radii, [4.0 - t1, 4.0 + t2])  # the bore's normal points to its axis: t1 inward
                exact = S._cylinder_piece_volume(leg, t1, t2)[0]
                self.assertAlmostEqual(p.Volume, exact, delta=1e-6 * exact)  # _leg_piece's own bound

    def testStraightBore(self):
        for tilt, t1, t2, mid, ring in ((30.0, 0.75, 0.75, True, 12 * math.pi),
                                        (10.0, 0.0, 1.5, False, math.pi * (5.5 ** 2 - 16))):
            with self.subTest(tilt=tilt, t1=t1, t2=t2):
                srf, _ = self.sheet(None, tilt)
                s = self.thicken(srf, t1, t2, mid)
                self.assertAlmostEqual(s.Volume, ring * 50, delta=1e-3)
                r = 4 + t2
                self.assertBox(s, (0, 20 - r, 8 - r), (50 + 4 * math.tan(math.radians(tilt)), 20 + r, 8 + r))  # rulings keep x

    def testRingBendInward(self):
        # the face-by-face fuse here comes closest to the pieces' sum check (review r6: 9.4e-7 relative)
        srf, _ = self.sheet(8.0)
        s = self.thicken(srf, 0.75, 0.0)
        self.assertAlmostEqual(s.Volume, math.pi * (16 - 3.25 ** 2) * (14 + 22 + 4 * math.pi), delta=1e-3)
        self.assertBox(s, (16, 16, 4), (50 + 4 * math.tan(math.radians(30)), 24, 30))

    def testRingBendMidplane(self):
        # the whole-sheet path (the ring stays off its axis): legs 14 and 22, the bend's centroid arc 4 pi
        srf, _ = self.sheet(8.0)
        s = self.thicken(srf, 0.75, 0.75, True)
        self.assertAlmostEqual(s.Volume, 12 * math.pi * (14 + 22 + 4 * math.pi), delta=1e-3)
        self.assertBox(s, (15.25, 15.25, 3.25), (50 + 4 * math.tan(math.radians(30)), 24.75, 30))


class TestThickenPlanarCaps(unittest.TestCase):
    """A thickened sheet's end caps that lie in a plane are Plane faces, as in Onshape (ops#640, #69: the
    replica's harness finds a profile face by its class). OCC's offset builds them as planar B-splines.
    Models: a bore of radius 4 straight through a 40 x 30 x 20 box (the sheet is its full-turn cylinder face,
    normal toward the axis), and a half cylinder of radius 10, height 20. Expected: the caps lie in z = 0
    and z = 20, normal out of the solid (-z, +z), on a Plane; the volume is the annulus times the height."""

    def setUp(self):
        self.doc = App.newDocument("ThickenPlanarCaps")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def thicken(self, shape, t1=0.0, t2=0.0, midplane=None):
        a = self.doc.addObject("Part::Feature", "A")
        a.Shape = shape
        names = tuple("Face%d" % (k + 1) for k, f in enumerate(shape.Faces) if isinstance(f.Surface, Part.Cylinder))
        self.assertEqual(len(names), 1)
        t = S.make_thicken(self.doc.addObject("PartDesign::Body", "T"), [(a, names)], 0.75, 0.0, name="Thk")
        if midplane is not None:
            t.Midplane, t.Thickness = True, midplane
        else:
            t.Thickness1, t.Thickness2 = t1, t2
        self.doc.recompute()
        self.assertEqual(t.State, ["Up-to-date"], t.getStatusString())
        self.assertTrue(t.Shape.isValid())
        self.assertEqual(len(t.Shape.Solids), 1)
        self.feat = t
        return t.Shape

    def assertNamesKept(self, s):
        # the same Thicken recomputed without the rebuild (OCC's B-spline caps) gives every face the same name
        from unittest import mock

        with mock.patch.object(S, "_plane_caps", lambda tool: tool):
            self.feat.touch()
            self.doc.recompute()
            ref = self.feat.Shape
        self.assertNotEqual([f.Surface.__class__.__name__ for f in ref.Faces], [f.Surface.__class__.__name__ for f in s.Faces])
        self.assertEqual(len(ref.Faces), len(s.Faces))
        for k in range(len(s.Faces)):
            name = "Face%d" % (k + 1)
            self.assertTrue(s.getElementMappedName(name))
            self.assertEqual(s.getElementMappedName(name), ref.getElementMappedName(name), name)

    def assertCaps(self, s):
        caps = [(k, f) for k, f in enumerate(s.Faces) if f.findPlane() is not None
                and abs(abs(f.findPlane().Axis.z) - 1) < 1e-9]
        self.assertEqual(len(caps), 2)
        for k, f in caps:
            self.assertEqual(f.Surface.__class__.__name__, "Plane")
            z = f.CenterOfMass.z
            self.assertTrue(abs(z) < 1e-9 or abs(z - 20) < 1e-9, z)
            u0, u1, v0, v1 = f.ParameterRange
            n = f.normalAt(0.5 * (u0 + u1), 0.5 * (v0 + v1))
            self.assertAlmostEqual(n.z, 1.0 if z > 10 else -1.0, places=9)  # out of the solid

    def testBoreCapsArePlanes(self):
        box = Part.makeBox(40, 30, 20).cut(Part.makeCylinder(4, 20, App.Vector(15, 15, 0))).removeSplitter()
        s = self.thicken(box, t1=1.0)  # toward the axis: radii 3 to 4
        self.assertAlmostEqual(s.Volume, math.pi * (16 - 9) * 20, delta=1e-6)
        self.assertCaps(s)
        self.assertNamesKept(s)
        self.assertEqual(sum(1 for f in s.Faces if isinstance(f.Surface, Part.Cylinder)), 2)

    def testHalfCylinderMidplaneCapsArePlanes(self):
        half = Part.makeCylinder(10, 20, App.Vector(0, 0, 0), App.Vector(0, 0, 1), 180)
        s = self.thicken(half, midplane=3.0)  # radii 8.5 to 11.5
        self.assertAlmostEqual(s.Volume, 0.5 * math.pi * (11.5 ** 2 - 8.5 ** 2) * 20, delta=1e-6)
        self.assertCaps(s)
        self.assertNamesKept(s)
        # the side faces in y = 0 were planes already: every planar face is a Plane
        self.assertEqual([f.Surface.__class__.__name__ for f in s.Faces if f.findPlane() is not None], ["Plane"] * 4)
