# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#325, B+ Stage 1 session 4)

"""Split: a part split in two by a plane (PartDesign.split, notes/bplus-stage1-design.md 2.7,
S-t1 to S-t8). The original part gets a Split at its end that keeps one side of the plane; a new
part, placed as the original, starts with a Split that reads its partner's base, plane and side
and keeps the other side.

Designed geometry, S4's shroud: a box 20 x 10 x 8 hollowed by a box 18 x 8 x 7 from (1, 1, 1),
open at the top, walls 1 thick (1600 - 1008 = 592). The plane is a datum plane offset from XZ,
y = 3, normal +Y: its front (y > 3) holds 20 x 7 x 8 - 18 x 6 x 7 = 364, its back (y < 3)
20 x 3 x 8 - 18 x 2 x 7 = 228. Oracles are volumes, bounding boxes and face counts."""

import math
import unittest

import FreeCAD as App
import Part
import PartDesign

V = App.Vector

WHOLE = 592
FRONT = 364
BACK = 228


def box(shape):
    return shape.optimalBoundingBox(False, False)


class TestSplit(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestSplit")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def shroud(self, z=0):
        """The shroud, its outer box at (0, 0, z), and the plane y = 3."""
        doc = self.doc
        self.body = doc.addObject("PartDesign::Body", "Shroud")
        self.body.Label = "Shroud"
        self.outer = self.body.newObject("PartDesign::AdditiveBox", "Outer")
        self.outer.Length, self.outer.Width, self.outer.Height = 20, 10, 8
        self.outer.Placement = App.Placement(V(0, 0, z), App.Rotation())
        self.inner = self.body.newObject("PartDesign::SubtractiveBox", "Inner")
        self.inner.Length, self.inner.Width, self.inner.Height = 18, 8, 7
        self.inner.Placement = App.Placement(V(1, 1, z + 1), App.Rotation())
        self.plane = self.body.newObject("PartDesign::Plane", "SplitPlane")
        self.plane.Label = "SplitPlane"
        self.plane.MapMode = "Deactivated"
        self.placePlane(3)
        doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, WHOLE, places=6)
        return self.body

    def placePlane(self, y):
        # Offset from XZ, the normal +Y (the plane's Z turned onto Y)
        self.plane.Placement = App.Placement(V(0, y, 0), App.Rotation(V(0, 0, 1), V(0, 1, 0)))

    def split(self, tool=None, side="Front"):
        part = PartDesign.split(self.body, tool or self.plane, side)
        self.doc.recompute()
        self.original = self.body.Tip
        self.half = part.Tip
        for split in (self.original, self.half):
            self.assertEqual(split.TypeId, "PartDesign::Split")
            self.assertTrue(split.isValid(), split.getStatusString())
        return part

    def assertHalves(self, front, back):
        self.assertAlmostEqual(self.original.Shape.Volume, front, places=6)
        self.assertAlmostEqual(self.half.Shape.Volume, back, places=6)

    def testShroudSplit(self):
        """S-t1: the shroud split at y = 3: the original keeps the front (364, y from 3), the new
        part "Shroud001", placed as the shroud, the back (228, y to 3). They sum to the whole
        and don't overlap (their common volume is 0). The original's Split is its Tip after
        Inner; the new half's Split is its new part's first feature, with no base, its Partner
        the original's."""
        self.shroud()
        part = self.split()
        self.assertEqual(part.Label, "Shroud001")
        self.assertEqual(part.Placement, self.body.Placement)
        self.assertIs(self.original.BaseFeature, self.inner)
        self.assertEqual(part.Group, [self.half])
        self.assertIsNone(self.half.BaseFeature)
        self.assertIs(self.half.Partner, self.original)
        self.assertTrue(self.half.NewHalf)
        self.assertFalse(self.original.NewHalf)
        self.assertHalves(FRONT, BACK)
        self.assertAlmostEqual(self.body.Shape.Volume, FRONT, places=6)
        self.assertAlmostEqual(part.Shape.Volume, BACK, places=6)
        self.assertAlmostEqual(self.original.Shape.common(self.half.Shape).Volume, 0, places=6)
        front, back = box(self.original.Shape), box(self.half.Shape)
        self.assertAlmostEqual(front.YMin, 3, places=6)
        self.assertAlmostEqual(front.YMax, 10, places=6)
        self.assertAlmostEqual(back.YMin, 0, places=6)
        self.assertAlmostEqual(back.YMax, 3, places=6)
        # A U in section either way: one solid, and each half has the cut's two faces (the wall
        # ends) besides its own: 10 faces each, as the probe found
        for split in (self.original, self.half):
            self.assertEqual(len(split.Shape.Solids), 1)
            self.assertEqual(len(split.Shape.Faces), 10)

    def testCutFaceIsNamedByItsBoolean(self):
        """S-t1: the new half's cut faces, at y = 3, have mapped names from its own boolean, and
        the names hold through a wall-thickness edit (S-t2)."""
        self.shroud()
        self.split()

        def cutFaces():
            names = {}
            for i, face in enumerate(self.half.Shape.Faces, 1):
                if abs(face.normalAt(0, 0).y - 1) < 1e-9 and abs(face.CenterOfMass.y - 3) < 1e-6:
                    names[f"Face{i}"] = self.half.Shape.ElementReverseMap.get(f"Face{i}")
            return names

        before = cutFaces()
        self.assertEqual(len(before), 1)  # the U's end, one face at y = 3
        mapped = next(iter(before.values()))
        self.assertTrue(mapped and mapped != next(iter(before)), before)
        self.inner.Length = 16
        self.inner.Placement = App.Placement(V(2, 1, 1), App.Rotation())
        self.doc.recompute()
        after = cutFaces()
        self.assertEqual(list(after.values()), [mapped])

    def testEditBeforeTheSplitReachesBoth(self):
        """S-t2: thicker walls (Inner 16 x 6 x 6 from (2, 2, 2), whole 1600 - 576 = 1024): both
        halves follow, front 20 x 7 x 8 - 16 x 5 x 6 = 640, back 20 x 3 x 8 - 16 x 1 x 6 = 384."""
        self.shroud()
        self.split()
        self.inner.Length, self.inner.Width, self.inner.Height = 16, 6, 6
        self.inner.Placement = App.Placement(V(2, 2, 2), App.Rotation())
        self.doc.recompute()
        self.assertTrue(self.half.isValid(), self.half.getStatusString())
        self.assertHalves(640, 384)

    def testPlacedBaseHasNoShift(self):
        """S-t3: the shroud's boxes start at z = 5: the new half's bounding box is the original's
        other side, z from 5 to 13, no shift; so in a Body placed at (0, 0, 7) both go along."""
        self.shroud(z=5)
        part = self.split()
        self.assertHalves(FRONT, BACK)
        front, back = box(self.original.Shape), box(self.half.Shape)
        for b in (front, back):
            self.assertAlmostEqual(b.ZMin, 5, places=6)
            self.assertAlmostEqual(b.ZMax, 13, places=6)
            self.assertAlmostEqual(b.XMin, 0, places=6)
            self.assertAlmostEqual(b.XMax, 20, places=6)
        self.assertAlmostEqual(back.YMax, 3, places=6)
        # Both Bodies placed alike: each half in its Body's frame, the halves still apart
        for body in (self.body, part):
            body.Placement = App.Placement(V(0, 0, 7), App.Rotation())
        self.doc.recompute()
        self.assertHalves(FRONT, BACK)
        self.assertAlmostEqual(box(self.half.Shape).ZMin, 5, places=6)
        self.assertAlmostEqual(box(part.Shape).ZMin, 12, places=6)
        self.assertAlmostEqual(self.body.Shape.common(part.Shape).Volume, 0, places=6)

    def testPartnerMovedFollows(self):
        """S-t3: the original Body moved alone to (0, 0, 7): nothing the new half links changed,
        and it still reads the original's base where it now is: the back half, in the new Body's
        frame, from z 7 (polled, as a Merge's tools)."""
        self.shroud()
        part = self.split()
        self.body.Placement = App.Placement(V(0, 0, 7), App.Rotation())
        self.doc.recompute()
        self.assertAlmostEqual(self.half.Shape.Volume, BACK, places=6)
        self.assertAlmostEqual(box(part.Shape).ZMin, 7, places=6)
        self.assertAlmostEqual(box(part.Shape).YMax, 3, places=6)

    def testLaterFeatureStaysInItsHalf(self):
        """S-t4: a flange 20 x 2 x 1 on the front half, from (0, 10, 0), after the Split: the
        front gains 40, the back is unchanged."""
        self.shroud()
        part = self.split()
        flange = self.body.newObject("PartDesign::AdditiveBox", "Flange")
        flange.Length, flange.Width, flange.Height = 20, 2, 1
        flange.Placement = App.Placement(V(0, 10, 0), App.Rotation())
        self.doc.recompute()
        self.assertIs(self.body.Tip, flange)
        self.assertAlmostEqual(self.body.Shape.Volume, FRONT + 40, places=6)
        self.assertAlmostEqual(part.Shape.Volume, BACK, places=6)

    def testPlaneThatMissesFailsBoth(self):
        """S-t5: the plane moved to y = 20 misses the shroud: both Splits fail red, "SplitPlane
        doesn't cut Shroud"; moved back to y = 3, both recover. A split by a plane that misses is
        refused before anything changes, and so is one along a face (y = 10, the back wall's
        outside: one side would be empty)."""
        self.shroud()
        self.split()
        self.placePlane(20)
        self.doc.recompute()
        for split in (self.original, self.half):
            self.assertFalse(split.isValid())
            self.assertIn("SplitPlane doesn't cut Shroud", split.getStatusString())
        self.placePlane(3)
        self.doc.recompute()
        for split in (self.original, self.half):
            self.assertTrue(split.isValid(), split.getStatusString())
        self.assertHalves(FRONT, BACK)

        for y in (20, 10):
            self.placePlane(y)
            self.doc.recompute()
            count = len(self.doc.Objects)
            with self.assertRaisesRegex(ValueError, "SplitPlane doesn't cut Shroud"):
                PartDesign.split(self.body, self.plane)
            self.assertEqual(len(self.doc.Objects), count)

    def testPlaneMovedAndSideFlipped(self):
        """S-t6: the plane moved to y = 6: both follow, front 20 x 4 x 8 - 18 x 3 x 7 = 262, back
        20 x 6 x 8 - 18 x 5 x 7 = 330. The original's Side set to Back from Python flips both:
        the original 330 (y to 6), the new half 262 (y from 6)."""
        self.shroud()
        self.split()
        self.placePlane(6)
        self.doc.recompute()
        self.assertHalves(262, 330)
        self.original.Side = "Back"
        self.doc.recompute()
        self.assertTrue(self.half.isValid(), self.half.getStatusString())
        self.assertHalves(330, 262)
        self.assertAlmostEqual(box(self.original.Shape).YMax, 6, places=6)
        self.assertAlmostEqual(box(self.half.Shape).YMin, 6, places=6)

    def testInsertBeforeTheSplitReachesBoth(self):
        """S-t7: the shroud rolled back to Inner, a fillet (r 0.5) inserted on the bottom edge
        along Y at x = 0, rolled to its end: both halves have their share of it. The fillet takes
        r^2 (1 - pi/4) per unit of length: 7 of the edge in the front, 3 in the back. While the
        shroud is rolled back, the original's Split is held and the new half waits with it, at
        its old shape."""
        self.shroud()
        part = self.split()
        self.body.Tip = self.inner
        self.doc.recompute()
        edge = None
        for i, e in enumerate(self.inner.Shape.Edges, 1):
            ends = {tuple(round(c, 6) for c in v.Point) for v in e.Vertexes}
            if ends == {(0, 0, 0), (0, 10, 0)}:
                edge = f"Edge{i}"
        self.assertIsNotNone(edge)
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (self.inner, [edge])
        fillet.Radius = 0.5
        self.doc.recompute()
        self.assertIs(self.original.BaseFeature, fillet)
        self.assertIs(self.body.Tip, fillet)
        cut = 0.25 * (1 - math.pi / 4)
        self.assertAlmostEqual(fillet.Shape.Volume, WHOLE - 10 * cut, places=4)
        # Rolled back: both wait
        self.assertAlmostEqual(self.half.Shape.Volume, BACK, places=6)
        self.assertAlmostEqual(part.Shape.Volume, BACK, places=6)

        self.body.Tip = self.original
        self.doc.recompute()
        self.assertTrue(self.half.isValid(), self.half.getStatusString())
        self.assertHalves(FRONT - 7 * cut, BACK - 3 * cut)

    def testPartnerDeleted(self):
        """The partner deleted: the new half fails red, "Its partner Split was deleted", and the
        new part has nothing."""
        self.shroud()
        part = self.split()
        name = self.original.Name
        self.body.removeObject(self.original)
        self.doc.removeObject(name)
        self.doc.recompute()
        self.assertFalse(self.half.isValid())
        self.assertIn("Its partner Split was deleted", self.half.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, WHOLE, places=6)

    def testRefusals(self):
        """A rolled-back part, a plane that isn't one (a curved face), and a part merged into
        another are refused before anything changes, with the reason."""
        self.shroud()
        self.body.Tip = self.outer
        self.doc.recompute()
        count = len(self.doc.Objects)
        with self.assertRaisesRegex(ValueError, "Roll Shroud to the end first"):
            PartDesign.split(self.body, self.plane)
        self.assertEqual(len(self.doc.Objects), count)
        self.body.Tip = self.inner
        self.doc.recompute()
        cyl = self.body.newObject("PartDesign::AdditiveCylinder", "Post")
        cyl.Radius, cyl.Height = 1, 4
        cyl.Placement = App.Placement(V(10, 5, 1), App.Rotation())
        self.doc.recompute()
        curved = None
        for i, face in enumerate(cyl.Shape.Faces, 1):
            if face.Surface.__class__.__name__ == "Cylinder":
                curved = f"Face{i}"
        count = len(self.doc.Objects)
        with self.assertRaisesRegex(ValueError, "isn't planar"):
            PartDesign.split(self.body, (cyl, curved))
        self.assertEqual(len(self.doc.Objects), count)

        other = self.doc.addObject("PartDesign::Body", "Other")
        other.newObject("PartDesign::AdditiveBox", "OtherBox")
        self.doc.recompute()
        PartDesign.makeMerge(self.body, [other])
        self.doc.recompute()
        count = len(self.doc.Objects)
        with self.assertRaisesRegex(ValueError, "Other is merged into Shroud; split that part"):
            PartDesign.split(other, self.plane)
        self.assertEqual(len(self.doc.Objects), count)

    def testOriginPlaneAndFace(self):
        """The tool as an origin plane: the shroud's XY plane lies along its bottom, so it doesn't
        cut and is refused. As a planar face of another part of the studio: the face at y = 3
        (normal +Y) of a slab 20 x 3 x 1 from (0, 0, -1), under the shroud: the S-t1 split."""
        self.shroud()
        xy = self.body.Origin.OriginFeatures[3]
        with self.assertRaisesRegex(ValueError, "doesn't cut Shroud"):
            PartDesign.split(self.body, xy)
        slab = self.doc.addObject("PartDesign::Body", "Slab")
        slabBox = slab.newObject("PartDesign::AdditiveBox", "SlabBox")
        slabBox.Length, slabBox.Width, slabBox.Height = 20, 3, 1
        slabBox.Placement = App.Placement(V(0, 0, -1), App.Rotation())
        self.doc.recompute()
        face = None
        for i, f in enumerate(slabBox.Shape.Faces, 1):
            if abs(f.normalAt(0, 0).y - 1) < 1e-9:
                face = f"Face{i}"
        self.assertIsNotNone(face)
        self.split(tool=(slabBox, face))
        self.assertHalves(FRONT, BACK)

    def testProbeHalfSpace(self):
        """S-t8, the probe as a test: a half-space Common, at shape level, through
        makeElementBoolean and refine, on the shroud and on a sphere with B-spline faces: valid
        shapes, and halves that sum to the whole (the sphere's within its volume integration)."""
        shroud = Part.makeBox(20, 10, 8).cut(Part.makeBox(18, 8, 7, V(1, 1, 1)))
        sphere = Part.makeSphere(5).toNurbs()
        for shape, origin, normal, rel in (
            (shroud, V(0, 3, 0), V(0, 1, 0), 1e-9),
            (sphere, V(0, 0, 1), V(0, 0, 1), 5e-3),
        ):
            halves = []
            for side in (1, -1):
                space = Part.Face(Part.Plane(origin, normal)).makeHalfSpace(origin + normal * side)
                half = shape.common(space).removeSplitter()
                self.assertTrue(half.isValid())
                self.assertEqual(len(half.Solids), 1)
                halves.append(half.Volume)
            self.assertAlmostEqual(sum(halves) / shape.Volume, 1, delta=rel)
        # The sphere, split in a Body: its halves' Splits are valid and sum likewise
        body = self.doc.addObject("PartDesign::Body", "Ball")
        ball = body.newObject("PartDesign::AdditiveSphere", "BallSphere")
        ball.Radius = 5
        self.doc.recompute()
        part = PartDesign.split(body, body.Origin.OriginFeatures[3])
        self.doc.recompute()
        self.assertTrue(body.Tip.isValid(), body.Tip.getStatusString())
        self.assertTrue(part.Tip.isValid(), part.Tip.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, part.Shape.Volume, delta=1e-6)
        self.assertAlmostEqual(
            (body.Shape.Volume + part.Shape.Volume) / ball.Shape.Volume, 1, delta=1e-6
        )


if __name__ == "__main__":
    unittest.main()
