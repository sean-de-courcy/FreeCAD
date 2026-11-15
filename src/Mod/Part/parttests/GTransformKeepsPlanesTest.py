# SPDX-License-Identifier: LGPL-2.1-or-later

"""A plane under a general transform (a scale per axis, a shear) is a plane (FreeCAD-CH ops#640,
FMCVW Case Base's Under-Acrylic Carveout).

OCCT's BRepBuilderAPI_GTransform turns every surface into a B-spline, a plane into a bilinear patch
(degree 1 x 1, 2 x 2 poles): the same points, but no plane to anything that reads a face's type. On
Case Base a tool body scaled (1, 1, 0.2) was cut from the part, and the next feature's profile, the
tool's flat cap left in the part, was not found as a plane; Onshape keeps it a plane.

Designed models, expected in closed form:
- a 10 mm cube scaled (1, 1, 0.2) about the origin: 6 plane faces, 10 x 10 x 2, volume 200, area
  280; the same mirrored, scaled (1, 1, -0.5): volume 500; sheared by x += z / 2: volume 1000 (the
  shear's determinant is 1), 6 planes, the two slanted ones with normal (2, 0, -1) / sqrt(5);
- half a ball of radius 4 (the half x > 0, a flat cap in x = 0) scaled to a fifth along z about its
  centre: the cap a plane face, an ellipse 8 x 1.6 of area pi * 4 * 0.8; the volume a fifth of the
  half ball's; moved to x = 1 and cut from a block, the cap left in the block is a plane face of the
  same area, and the block's volume is its own less the tool's."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector


def general(shape, matrix):
    result = shape.copy()
    result.transformShape(matrix, False, True)
    return result


def scaling(point, sx, sy, sz):
    return App.Matrix(
        sx, 0, 0, (1 - sx) * point.x,
        0, sy, 0, (1 - sy) * point.y,
        0, 0, sz, (1 - sz) * point.z,
        0, 0, 0, 1,
    )  # fmt: skip


def kinds(shape):
    return sorted(f.Surface.__class__.__name__ for f in shape.Faces)


class GTransformKeepsPlanesTest(unittest.TestCase):
    def assertOutward(self, solid):
        """Every plane face's normal points out of the solid"""
        for face in solid.Faces:
            if face.Surface.__class__.__name__ != "Plane":
                continue
            u0, u1, v0, v1 = face.ParameterRange
            at = face.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
            normal = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
            self.assertFalse(solid.isInside(at + normal * 1e-3, 1e-9, False))
            self.assertTrue(solid.isInside(at - normal * 1e-3, 1e-9, False))

    def testACubeScaledPerAxis(self):
        cube = Part.makeBox(10, 10, 10)
        for factor, volume, area in ((0.2, 200.0, 280.0), (-0.5, 500.0, 400.0)):
            with self.subTest(factor=factor):
                scaled = general(cube, scaling(V(0, 0, 0), 1, 1, factor))
                self.assertTrue(scaled.isValid())
                self.assertEqual(kinds(scaled), ["Plane"] * 6)
                self.assertAlmostEqual(scaled.Volume, volume, places=9)
                self.assertAlmostEqual(scaled.Area, area, places=9)
                self.assertOutward(scaled.Solids[0])

    def testACubeSheared(self):
        shear = App.Matrix(1, 0, 0.5, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        sheared = general(Part.makeBox(10, 10, 10), shear)
        self.assertTrue(sheared.isValid())
        self.assertEqual(kinds(sheared), ["Plane"] * 6)
        self.assertAlmostEqual(sheared.Volume, 1000.0, places=9)
        slanted = [f for f in sheared.Faces if abs(abs(f.Surface.Axis.x) - 2 / math.sqrt(5)) < 1e-9]
        self.assertEqual(len(slanted), 2)
        for face in slanted:
            self.assertAlmostEqual(abs(face.Surface.Axis.z), 1 / math.sqrt(5), places=9)
            self.assertAlmostEqual(face.Area, 10 * 10 * math.sqrt(5) / 2, places=9)
        self.assertOutward(sheared.Solids[0])

    def testTheFlatCapOfAScaledToolCutFromABlock(self):
        half = Part.makeSphere(4, V(0, 0, 5)).common(Part.makeBox(4, 8, 8, V(0, -4, 1)))
        halfVolume = 2.0 / 3.0 * math.pi * 4**3
        self.assertAlmostEqual(half.Volume, halfVolume, places=6)
        tool = general(half, scaling(V(0, 0, 5), 1, 1, 0.2))
        self.assertTrue(tool.isValid())
        self.assertAlmostEqual(tool.Volume, halfVolume / 5, places=6)
        caps = [f for f in tool.Faces if abs(f.BoundBox.XMax) < 1e-6]
        self.assertEqual(len(caps), 1)
        self.assertEqual(caps[0].Surface.__class__.__name__, "Plane")
        self.assertAlmostEqual(caps[0].Area, math.pi * 4 * 0.8, places=6)
        # the round faces stay what the transform made them: an ellipsoid is no elementary surface
        self.assertEqual(kinds(tool).count("Plane"), 1)

        tool.translate(V(1, 0, 0))
        block = Part.makeBox(12, 12, 10, V(-2, -6, 0))
        cut = block.cut(tool)
        self.assertTrue(cut.isValid())
        self.assertAlmostEqual(cut.Volume, 12 * 12 * 10 - halfVolume / 5, places=6)
        left = [
            f for f in cut.Faces if abs(f.BoundBox.XMin - 1) < 1e-6 and abs(f.BoundBox.XMax - 1) < 1e-6
        ]
        self.assertEqual(len(left), 1)
        self.assertEqual(left[0].Surface.__class__.__name__, "Plane")
        self.assertAlmostEqual(left[0].Area, math.pi * 4 * 0.8, places=6)
