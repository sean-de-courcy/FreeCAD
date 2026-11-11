# SPDX-License-Identifier: LGPL-2.1-or-later
# ***************************************************************************
# *   Copyright (c) 2026 FreeCAD-CH contributors                            *
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# ***************************************************************************

"""Onshape's Face pattern (FreeCAD-CH ops#655 T8, notes/face-pattern-design.md).

The expected results are Onshape's (`notes/onshape-facts.md` "Face pattern, FP1-FP5, FP8"):
- FP2: a boss's five faces, +x 20, count 3: 12540, one solid. Its top alone, or its sides alone:
  the feature fails and the part is unchanged.
- FP3: a pocket's five faces, +x 20, 3: 11568.
- FP4: an instance entirely off the part is dropped silently (12360). An instance partly off the
  part: Onshape stretches its sides down (11720); the route can't, so the feature fails
  (decision 150).
- FP5: overlapping instances: the feature fails.
- FP8: a circular pattern of a through hole (its cylinder) and of a blind hole (cylinder and floor),
  4 over 360 degrees.

Designed models, built by each test (mm, volumes in mm^3):
- Plate: x 0..60, y 0..20, z 0..10 (12000). Boss: x 2..8, y 7..13, z 10..15 (180).
  Pocket: x 2..8, y 7..13, z 6..10 (144).
- Disc: radius 40, z 0..10, about Z. Hole: radius 3 at (20, 0), through or 5 deep.
"""

import math
import unittest

import FreeCAD as App

from PartDesignTests.Scenarios import models

V = App.Vector
TOL = 1e-6

PLATE = 60 * 20 * 10
BOSS = 6 * 6 * 5
POCKET = 6 * 6 * 4
DISC = math.pi * 40**2 * 10
THROUGH_HOLE = math.pi * 3**2 * 10
BLIND_HOLE = math.pi * 3**2 * 5


def inBox(point, x0, x1, y0, y1, z0, z1):
    return (
        x0 - TOL <= point.x <= x1 + TOL
        and y0 - TOL <= point.y <= y1 + TOL
        and z0 - TOL <= point.z <= z1 + TOL
    )


class TestFacePattern(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("PartDesignTestFacePattern")
        App.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # -- models ----------------------------------------------------------------------------------

    def plate(self, x0=0, x1=60):
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "PlateSketch", models.rectangle(x0, 0, x1, 20), self.body)
        return models.pad(self.body, sketch, 10, name="Plate")

    def boss(self, x0=2, x1=8):
        sketch = models.sketch(
            self.doc, "BossSketch", models.rectangle(x0, 7, x1, 13), self.body, z=10
        )
        return models.pad(self.body, sketch, 5, name="Boss")

    def pocket(self):
        sketch = models.sketch(self.doc, "PocketSketch", models.rectangle(2, 7, 8, 13), self.body, z=10)
        return models.pocket(self.body, sketch, 4, name="Pocket")

    def disc(self, depth=None):
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "DiscSketch", [models.circle(0, 0, 40)], self.body)
        models.pad(self.body, sketch, 10, name="Disc")
        hole = models.sketch(self.doc, "HoleSketch", [models.circle(20, 0, 3)], self.body, z=10)
        if depth is None:
            return models.pocketThroughAll(self.body, hole, name="Hole")
        return models.pocket(self.body, hole, depth, name="Hole")

    def faces(self, feature, test):
        """The names of the feature's faces whose centre passes `test`."""
        self.doc.recompute()
        names = [
            "Face%d" % (i + 1)
            for i, face in enumerate(feature.Shape.Faces)
            if test(face.CenterOfMass, face)
        ]
        self.assertTrue(names, "no face picked")
        return names

    def bossFaces(self, feature, x0=2, x1=8, z=10):
        return self.faces(feature, lambda c, f: inBox(c, x0, x1, 7, 13, z + 1e-3, z + 5))

    def pocketFaces(self, feature):
        return self.faces(feature, lambda c, f: inBox(c, 2, 8, 7, 13, 6, 10 - 1e-3))

    def holeFaces(self, feature, floor=False):
        def test(c, f):
            if f.Surface.__class__.__name__ == "Cylinder":
                return f.Surface.Radius < 4
            return floor and abs(c.z - 5) < TOL and inBox(c, 17, 23, -3, 3, 5, 5)

        return self.faces(feature, test)

    def linear(self, base, faces, spacing, count, name="FacePattern"):
        pattern = self.body.newObject("PartDesign::FaceLinearPattern", name)
        pattern.Base = (base, faces)
        pattern.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        pattern.Mode = "Extent"
        pattern.Occurrences = count
        pattern.Length = spacing * (count - 1)
        return pattern

    def polar(self, base, faces, count):
        pattern = self.body.newObject("PartDesign::FacePolarPattern", "FacePolarPattern")
        pattern.Base = (base, faces)
        pattern.Axis = (models.originFeature(self.body, "Z_Axis"), [""])
        pattern.Angle = 360
        pattern.Occurrences = count
        return pattern

    def assertSolid(self, feature, volume):
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        self.assertEqual(len(shape.Solids), 1)
        self.assertTrue(shape.isValid())
        self.assertAlmostEqual(shape.Volume, volume, places=3)

    def assertFails(self, feature):
        self.doc.recompute()
        self.assertFalse(feature.isValid())

    def topsAt(self, shape, z):
        """The x of the centres of the shape's 6 x 6 planar faces facing +z at height z."""
        return sorted(
            round(face.CenterOfMass.x, 6)
            for face in shape.Faces
            if face.Surface.__class__.__name__ == "Plane"
            and abs(face.CenterOfMass.z - z) < TOL
            and abs(face.Area - 36) < TOL
        )

    # -- FP2: a boss ------------------------------------------------------------------------------

    def testBossLinear(self):
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 20, 3)
        self.assertSolid(pattern, PLATE + 3 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [5, 25, 45])

    def testTopFaceAloneFails(self):
        self.plate()
        boss = self.boss()
        top = self.faces(boss, lambda c, f: inBox(c, 2, 8, 7, 13, 15, 15))
        self.assertFails(self.linear(boss, top, 20, 3))

    def testSidesAloneFail(self):
        self.plate()
        boss = self.boss()
        sides = self.faces(boss, lambda c, f: inBox(c, 2, 8, 7, 13, 12.5, 12.5))
        self.assertEqual(len(sides), 4)
        self.assertFails(self.linear(boss, sides, 20, 3))

    def testNoFacesFails(self):
        self.plate()
        boss = self.boss()
        pattern = self.body.newObject("PartDesign::FaceLinearPattern", "FacePattern")
        pattern.Base = (boss, [])
        self.assertFails(pattern)

    # -- FP3: a pocket ----------------------------------------------------------------------------

    def testPocketLinear(self):
        self.plate()
        pocket = self.pocket()
        pattern = self.linear(pocket, self.pocketFaces(pocket), 20, 3)
        self.assertSolid(pattern, PLATE - 3 * POCKET)
        self.assertEqual(self.topsAt(pattern.Shape, 6), [5, 25, 45])

    # -- FP4: instances off the part --------------------------------------------------------------

    def testInstanceOffThePartIsDropped(self):
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 30, 3)  # the third at x 62..68
        self.assertSolid(pattern, PLATE + 2 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [5, 35])

    def testPocketOffThePartIsDropped(self):
        self.plate()
        pocket = self.pocket()
        pattern = self.linear(pocket, self.pocketFaces(pocket), 30, 3)
        self.assertSolid(pattern, PLATE - 2 * POCKET)

    def testInstancePartlyOffThePartFails(self):
        # Onshape stretches the overhang's sides down to the plate's bottom (11720); the copy
        # can't, so the feature stops with an error rather than give 11540 (decision 150)
        self.plate(x1=55)
        boss = self.boss()
        self.assertFails(self.linear(boss, self.bossFaces(boss), 25, 3))  # the third at x 52..58

    # -- FP5: overlaps ----------------------------------------------------------------------------

    def testOverlappingInstancesFail(self):
        self.plate()
        boss = self.boss()
        self.assertFails(self.linear(boss, self.bossFaces(boss), 4, 3))

    def testTouchingInstancesMerge(self):
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 6, 3)  # x 2..8, 8..14, 14..20
        self.assertSolid(pattern, PLATE + 3 * BOSS)

    # -- FP8: circular, holes ---------------------------------------------------------------------

    def holeCentres(self, shape):
        return sorted(
            (round(f.Surface.Center.x, 6) + 0.0, round(f.Surface.Center.y, 6) + 0.0)
            for f in shape.Faces
            if f.Surface.__class__.__name__ == "Cylinder" and f.Surface.Radius < 4
        )

    def testThroughHoleCircular(self):
        hole = self.disc()
        pattern = self.polar(hole, self.holeFaces(hole), 4)
        self.assertSolid(pattern, DISC - 4 * THROUGH_HOLE)
        self.assertEqual(self.holeCentres(pattern.Shape), [(-20, 0), (0, -20), (0, 20), (20, 0)])

    def testBlindHoleCircular(self):
        hole = self.disc(depth=5)
        pattern = self.polar(hole, self.holeFaces(hole, floor=True), 4)
        self.assertSolid(pattern, DISC - 4 * BLIND_HOLE)

    # -- Skip, mirror -----------------------------------------------------------------------------

    def testSkip(self):
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 20, 3)
        pattern.SkippedInstances = [1, 0]  # the first copy (index 0 is the seed, as CP8)
        self.assertSolid(pattern, PLATE + 2 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [5, 45])

    def testMirror(self):
        self.plate(x0=-30, x1=30)
        boss = self.boss(x0=-28, x1=-22)
        pattern = self.body.newObject("PartDesign::FaceMirrored", "FaceMirrored")
        pattern.Base = (boss, self.bossFaces(boss, x0=-28, x1=-22))
        pattern.MirrorPlane = (models.originFeature(self.body, "YZ_Plane"), [""])
        self.assertSolid(pattern, PLATE + 2 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [-25, 25])

    # -- the copy meets a different neighbour (FP6, oracle-sb5 pending) ---------------------------

    def testCopyOntoAHigherStepIsTrimmed(self):
        self.plate()
        step = models.sketch(self.doc, "StepSketch", models.rectangle(30, 0, 60, 20), self.body, z=10)
        models.pad(self.body, step, 2, name="Step")
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 40, 2)  # the copy at x 42..48 on z 12
        self.assertSolid(pattern, PLATE + 30 * 20 * 2 + BOSS + 6 * 6 * 3)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [5, 45])


if __name__ == "__main__":
    unittest.main()
