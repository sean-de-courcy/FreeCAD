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
