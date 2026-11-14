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

The expected results are Onshape's (`notes/onshape-facts.md` "Face pattern", FP1-FP19):
- FP2: a boss's five faces, +x 20, count 3: 12540, one solid. Its top alone, or its sides alone:
  the feature fails and the part is unchanged.
- FP3: a pocket's five faces, +x 20, 3: 11568.
- FP4: an instance entirely off the part is dropped silently (12360). An instance partly off the
  part: Onshape stretches its sides down (11720); the route can't, so the feature fails
  (decision 150).
- FP5, FP16: overlapping or touching instances (the seed included): the feature fails.
- FP6: a copy over a lower step: Onshape stretches it down (13632); the route can't, so the feature
  fails (debt). FP7: picks on two parts: an error for now (the parts hub's T1a).
- FP8: a circular pattern of a through hole (its cylinder) and of a blind hole (cylinder and floor),
  4 over 360 degrees.
- FP9: Skip, index 0 the seed. FP10: Mirror.
- FP11-FP18: picks that don't close against the part fail (a counterbore without its hole, a tube boss
  without its bore, a blind pocket onto a thinner section, a boss copy inside a taller step, a corner
  boss along an edge, a side's merged face picked). A through hole onto a thicker step: Onshape extends
  it (17151.77); the route can't, so the feature fails (debt).
- FP19: a pocket copy partly off the part's edge cuts what it meets (10640), a notch open there.

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

    def assertFails(self, feature, why=None):
        self.doc.recompute()
        self.assertFalse(feature.isValid())
        if why:
            self.assertIn(why, feature.getStatusString())

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
        pattern = self.linear(boss, self.bossFaces(boss), 4, 3)
        self.assertFails(pattern, "instance 2 touches or overlaps instance 1")

    def testTouchingInstancesFail(self):
        # FP16: Onshape fails with PATTERN_FACE_FAILED, as for an overlap (the seed included)
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 6, 3)  # x 2..8, 8..14, 14..20
        self.assertFails(pattern, "instance 2 touches or overlaps instance 1")

    def testCopiesTouchingAlongAnEdgeFail(self):
        # Two directions, pitch = the boss's size: diagonal neighbours share an edge
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 6, 2)
        pattern.Direction2 = (models.originFeature(self.body, "Y_Axis"), [""])
        pattern.Mode2 = "Extent"
        pattern.Occurrences2 = 2
        pattern.Length2 = 6
        pattern.SkippedInstances = [1, 0, 0, 1]  # the seed and its diagonal one, x 8..14, y 13..19
        self.assertFails(pattern, "instance 4 touches or overlaps instance 1")

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
        # FP9: count 4, distance 15, index1 1 skipped: bosses at x 2, 32, 47 (12540; index 0 is the
        # seed, as CP8)
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 15, 4)
        pattern.SkippedInstances = [1, 0]
        self.assertSolid(pattern, PLATE + 3 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [5, 35, 50])

    def testMirror(self):
        # FP10: Onshape's boss at x 2..8 mirrored about x = 30 (12360); here the same, shifted by -30
        self.plate(x0=-30, x1=30)
        boss = self.boss(x0=-28, x1=-22)
        pattern = self.body.newObject("PartDesign::FaceMirrored", "FaceMirrored")
        pattern.Base = (boss, self.bossFaces(boss, x0=-28, x1=-22))
        pattern.MirrorPlane = (models.originFeature(self.body, "YZ_Plane"), [""])
        self.assertSolid(pattern, PLATE + 2 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [-25, 25])

    # -- Centered and the second direction (ops#655; notes/patterns-design.md section 10) ----------
    # Onshape's Centered counts per side, the seed included: count n makes 2n - 1 instances along
    # that direction (oracle 9j Q-D1, Q-D6). A direction in use with no reference: "Select a
    # pattern direction." (Q-D3). Model: the plate at x -30..30, the boss at x -3..3, y 7..13.

    def centredBoss(self):
        self.plate(x0=-30, x1=30)
        return self.boss(x0=-3, x1=3)

    def testCenteredCountsPerSide(self):
        # Count 2, spacing 15, centered: 3 bosses, at x -15, 0, 15
        boss = self.centredBoss()
        pattern = self.linear(boss, self.bossFaces(boss, x0=-3, x1=3), 15, 2)
        pattern.Centered = True
        self.assertSolid(pattern, PLATE + 3 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [-15, 0, 15])

    def testCenteredSecondDirection(self):
        # Direction 1 count 1; direction 2 along Y, spacing 7, count 2, centered: 3 bosses at
        # y 3, 10, 17 (y 0..6, 7..13, 14..20, 1 apart)
        boss = self.centredBoss()
        pattern = self.linear(boss, self.bossFaces(boss, x0=-3, x1=3), 15, 1)
        pattern.Length = 0
        pattern.Direction2 = (models.originFeature(self.body, "Y_Axis"), [""])
        pattern.Mode2 = "Spacing"
        pattern.Offset2 = 7
        pattern.Occurrences2 = 2
        pattern.Centered2 = True
        self.assertSolid(pattern, PLATE + 3 * BOSS)
        tops = sorted(
            round(face.CenterOfMass.y, 6)
            for face in pattern.Shape.Faces
            if abs(face.CenterOfMass.z - 15) < TOL and abs(face.Area - 36) < TOL
        )
        self.assertEqual(tops, [3, 10, 17])

    def testCenteredSkipCountsTheWholeRow(self):
        # Count 2 centered: indexes 0, 1, 2 from the negative end, 1 the seed; skip 0 (x -15)
        boss = self.centredBoss()
        pattern = self.linear(boss, self.bossFaces(boss, x0=-3, x1=3), 15, 2)
        pattern.Centered = True
        pattern.SkippedInstances = [0, 0]
        self.assertSolid(pattern, PLATE + 2 * BOSS)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [0, 15])

    def testCenteredCircular(self):
        # Count 2 over 90 degrees, centered: the hole at -90, 0, +90 about Z
        hole = self.disc()
        pattern = self.polar(hole, self.holeFaces(hole), 2)
        pattern.Mode = "Extent"
        pattern.Angle = 90
        pattern.Centered = True
        self.assertSolid(pattern, DISC - 3 * THROUGH_HOLE)
        self.assertEqual(self.holeCentres(pattern.Shape), [(0, -20), (0, 20), (20, 0)])

    def testUsedDirectionWithoutReferenceFails(self):
        # The second direction at count 2 with no Direction2: Onshape's error, no copies on the seed
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 20, 1)
        pattern.Length = 0
        pattern.Direction2 = None
        pattern.Occurrences2 = 2
        self.assertFails(pattern, "Select a pattern direction.")

    def testUnusedSecondDirectionNeedsNoReference(self):
        self.plate()
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 20, 3)
        pattern.Direction2 = None
        self.assertSolid(pattern, PLATE + 3 * BOSS)

    # -- picks that can't be lifted cleanly (the desktop's condition (d)) --------------------------

    def lBoss(self):
        """An L-shaped boss on the plate: x 2..8, y 7..13 and x 8..14, y 7..10, z 10..15 (270)."""
        self.plate()
        sketch = models.sketch(
            self.doc,
            "LSketch",
            models.polygon([(2, 7), (14, 7), (14, 10), (8, 10), (8, 13), (2, 13)]),
            self.body,
            z=10,
        )
        return models.pad(self.body, sketch, 5, name="LBoss")

    def testPicksTakingANeighbourFail(self):
        # The square part's sides and the L's top and long side: defeaturing removes the whole L,
        # whose short arm's faces, unpicked, would be copied too
        boss = self.lBoss()
        picks = self.faces(
            boss,
            lambda c, f: f.BoundBox.ZMax > 10 + 1e-6
            and (f.BoundBox.XMax < 8 + 1e-6 or abs(c.z - 15) < TOL or abs(c.y - 7) < TOL),
        )
        self.assertFails(self.linear(boss, picks, 20, 2), "lifted cleanly")

    def testPicksReshapingThePartFail(self):
        # The L's top and one side: the heal cuts into the plate down to its bottom
        boss = self.lBoss()
        picks = self.faces(
            boss, lambda c, f: f.BoundBox.ZMax > 10 + 1e-6 and (abs(c.z - 15) < TOL or abs(c.x - 2) < TOL)
        )
        self.assertFails(self.linear(boss, picks, 20, 2), "lifted cleanly")

    # -- faces flush with the part's own sides, unpicked inner loops (the skeptic's items 1, 4) ----

    def testFullWidthRib(self):
        # A rib across the plate (x 20..26, y 0..20): its ends, merged into the plate's sides, are
        # flush faces, and each copy's ends continue those sides
        self.plate()
        sketch = models.sketch(self.doc, "RibSketch", models.rectangle(20, 0, 26, 20), self.body, z=10)
        rib = models.pad(self.body, sketch, 5, name="Rib")
        rib.Refine = True
        picks = self.faces(rib, lambda c, f: inBox(c, 20, 26, 0.1, 19.9, 10.1, 15))
        self.assertEqual(len(picks), 3)
        pattern = self.linear(rib, picks, 12, 3)
        self.assertSolid(pattern, PLATE + 3 * 6 * 20 * 5)

    def testBossAgainstASide(self):
        # A boss against the plate's y = 0 side (x 2..8, y 0..6), that side of it merged into the
        # plate's: a flush face, and each copy along +x continues the plate's side
        self.plate()
        sketch = models.sketch(self.doc, "SideSketch", models.rectangle(2, 0, 8, 6), self.body, z=10)
        boss = models.pad(self.body, sketch, 5, name="SideBoss")
        boss.Refine = True
        picks = self.faces(boss, lambda c, f: inBox(c, 2, 8, 0.1, 6, 10.1, 15))
        self.assertEqual(len(picks), 4)
        pattern = self.linear(boss, picks, 20, 3)
        self.assertSolid(pattern, PLATE + 3 * BOSS)

    def testCornerBossAlongAnEdgeFails(self):
        # A boss at the corner (x 0..6, y 0..6) patterned along +x: its copies' x side, flush with
        # the plate's end at the seed, stands free. Onshape's result isn't known (asked); the copy
        # would make a face the seed doesn't have, so the feature stops (decision 150)
        self.plate()
        sketch = models.sketch(self.doc, "CornerSketch", models.rectangle(0, 0, 6, 6), self.body, z=10)
        boss = models.pad(self.body, sketch, 5, name="CornerBoss")
        boss.Refine = True
        picks = self.faces(boss, lambda c, f: inBox(c, 0.1, 6, 0.1, 6, 10.1, 15))
        self.assertEqual(len(picks), 3)
        self.assertFails(self.linear(boss, picks, 20, 3), "doesn't sit on the part")

    def testCornerBossWithItsMergedFacesFails(self):
        # FP18: the corner boss's own faces and the plate's two sides they merge into: Onshape fails
        self.plate()
        sketch = models.sketch(self.doc, "CornerSketch", models.rectangle(0, 0, 6, 6), self.body, z=10)
        boss = models.pad(self.body, sketch, 5, name="CornerBoss")
        boss.Refine = True
        picks = self.faces(
            boss,
            lambda c, f: inBox(c, 0.1, 6, 0.1, 6, 10.1, 15) or abs(c.x) < TOL or abs(c.y) < TOL,
        )
        self.assertEqual(len(picks), 5)
        self.assertFails(self.linear(boss, picks, 20, 3))

    def testBossAgainstASideWithItsMergedFaceFails(self):
        # FP18: the side boss's own 4 faces build (testBossAgainstASide); with the plate's y = 0 side,
        # which its outer side merges into, picked too, Onshape fails
        self.plate()
        sketch = models.sketch(self.doc, "SideSketch", models.rectangle(10, 0, 16, 6), self.body, z=10)
        boss = models.pad(self.body, sketch, 5, name="SideBoss")
        boss.Refine = True
        picks = self.faces(boss, lambda c, f: inBox(c, 10, 16, 0.1, 6, 10.1, 15) or abs(c.y) < TOL)
        self.assertEqual(len(picks), 5)
        self.assertFails(self.linear(boss, picks, 20, 3))

    def testCounterboreWithoutItsHoleFails(self):
        # A counterbore r6, 3 deep, over a through hole r3 at (20, 10); its wall and floor picked but
        # not the hole: the copies would be grooves with a pin in them
        self.plate()
        hole = models.sketch(self.doc, "HoleSketch", [models.circle(20, 10, 3)], self.body, z=10)
        models.pocketThroughAll(self.body, hole, name="Hole")
        bore = models.sketch(self.doc, "BoreSketch", [models.circle(20, 10, 6)], self.body, z=10)
        counterbore = models.pocket(self.body, bore, 3, name="Counterbore")
        picks = self.faces(
            counterbore,
            lambda c, f: (f.Surface.__class__.__name__ == "Cylinder" and f.Surface.Radius > 5)
            or (abs(c.z - 7) < TOL and f.Area < 200),
        )
        self.assertEqual(len(picks), 2)
        self.assertFails(self.linear(counterbore, picks, 20, 2), "doesn't open onto the part")

    def testTubeBossWithoutItsBoreFails(self):
        # A tube boss r6, 5 high, at (20, 10), bored r3 through it and the plate; its side and top
        # picked, not the bore: the copies would have no hole in the plate
        self.plate()
        sketch = models.sketch(self.doc, "TubeSketch", [models.circle(20, 10, 6)], self.body, z=10)
        models.pad(self.body, sketch, 5, name="Tube")
        bore = models.sketch(self.doc, "BoreSketch", [models.circle(20, 10, 3)], self.body, z=15)
        tube = models.pocketThroughAll(self.body, bore, name="Bore")
        picks = self.faces(
            tube,
            lambda c, f: (f.Surface.__class__.__name__ == "Cylinder" and f.Surface.Radius > 5)
            or abs(c.z - 15) < TOL,
        )
        self.assertEqual(len(picks), 2)
        self.assertFails(self.linear(tube, picks, 20, 2), "doesn't sit on the part")

    # -- the copy meets a different neighbour (the desktop's conditions (b), (c)) ------------------

    def step(self):
        """The plate with its x 30..60 half raised to z 12."""
        self.plate()
        sketch = models.sketch(self.doc, "StepSketch", models.rectangle(30, 0, 60, 20), self.body, z=10)
        return models.pad(self.body, sketch, 2, name="Step")

    def testPocketOntoAHigherStepFails(self):
        # The copy's lid would be inside the step: a closed void, where Onshape opens the pocket
        self.step()
        pocket = self.pocket()
        self.assertFails(self.linear(pocket, self.pocketFaces(pocket), 40, 2))

    def testBossOverALowerStepFails(self):
        # FP6: seed on the high step (z 12..17), the copy over the low one. Onshape stretches it down
        # to z 10 (13632); the copy can't, so the feature stops naming the instance (debt)
        self.step()
        sketch = models.sketch(self.doc, "HighSketch", models.rectangle(32, 7, 38, 13), self.body, z=12)
        boss = models.pad(self.body, sketch, 5, name="HighBoss")
        pattern = self.linear(boss, self.bossFaces(boss, x0=32, x1=38, z=12), 30, 2)
        pattern.Reversed = True
        self.assertFails(pattern, "instance 2 stands over the part")

    def testPocketPartlyOffThePartsEdgeCutsANotch(self):
        # FP19: the third pocket, x 52..58 on a plate ending at x 55. Its x 58 wall, a picked face,
        # lies wholly beside the part; Onshape cuts what the copy meets, a 3 x 6 x 4 notch open at
        # the plate's end: 11000 - 2 x 144 - 72 = 10640, one part, no warning
        self.plate(x1=55)
        pocket = self.pocket()
        pattern = self.linear(pocket, self.pocketFaces(pocket), 25, 3)
        self.assertSolid(pattern, 55 * 20 * 10 - 2 * POCKET - 3 * 6 * 4)
        floors = [
            face
            for face in pattern.Shape.Faces
            if face.Surface.__class__.__name__ == "Plane"
            and abs(face.CenterOfMass.z - 6) < TOL
            and inBox(face.CenterOfMass, 52, 55, 7, 13, 6, 6)
        ]
        self.assertEqual(len(floors), 1)
        self.assertAlmostEqual(floors[0].Area, 3 * 6, places=6)
        self.assertAlmostEqual(floors[0].BoundBox.XMax, 55, places=6)

    def testPocketPartlyOffBesideAPartBeyondItFails(self):
        # The FP19 exemption holds only where the whole part lies inside the missing face's plane:
        # here a tab y 15..20 runs on to x 65, past the copy's x 58 wall, so the wall's plane cuts
        # the part and the copy errors as before (loud; Onshape not asked)
        self.body = models.body(self.doc)
        outline = [(0, 0), (55, 0), (55, 15), (65, 15), (65, 20), (0, 20)]
        sketch = models.sketch(self.doc, "PlateSketch", models.polygon(outline), self.body)
        models.pad(self.body, sketch, 10, name="Plate")
        pocket = self.pocket()
        pattern = self.linear(pocket, self.pocketFaces(pocket), 25, 3)
        self.assertFails(pattern, "instance 3 has a picked face missing")

    def testCopyOntoAHigherStepIsTrimmed(self):
        self.plate()
        step = models.sketch(self.doc, "StepSketch", models.rectangle(30, 0, 60, 20), self.body, z=10)
        models.pad(self.body, step, 2, name="Step")
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 40, 2)  # the copy at x 42..48 on z 12
        self.assertSolid(pattern, PLATE + 30 * 20 * 2 + BOSS + 6 * 6 * 3)
        self.assertEqual(self.topsAt(pattern.Shape, 15), [5, 45])

    # -- each picked face's image in each instance (FP15, FP17), two parts (FP7), FP14 ------------

    def thinSection(self, z0):
        """The plate's x 0..30 half, 10 thick, and an x 30..60 section 3 thick at z0..z0 + 3; a blind
        pocket x 7..13, y 7..13, z 5..10 in the thick half (base 7620)"""
        self.plate(x1=30)
        sketch = models.sketch(self.doc, "ThinSketch", models.rectangle(30, 0, 60, 20), self.body, z=z0)
        models.pad(self.body, sketch, 3, name="Thin")
        sketch = models.sketch(self.doc, "PocketSketch", models.rectangle(7, 7, 13, 13), self.body, z=10)
        pocket = models.pocket(self.body, sketch, 5, name="Pocket")
        picks = self.faces(pocket, lambda c, f: inBox(c, 7, 13, 7, 13, 5, 10 - 1e-3))
        self.assertEqual(len(picks), 5)
        return pocket, picks

    def testBlindPocketOverAThinnerSectionFails(self):
        # FP15 (x 30..60 is z 0..3): the copy at x 32..38, z 5..10 lies over the section, not in it.
        # Onshape: PATTERN_FACE_FAILED; dropping it would be silent
        pocket, picks = self.thinSection(0)
        self.assertFails(self.linear(pocket, picks, 25, 2), "instance 2 lies over the part")

    def testBlindPocketOntoAThinnerLedgeFails(self):
        # FP15's rule on a ledge at z 7..10: the copy would cut through it, its floor in the air (a
        # through pocket where the seed is blind)
        pocket, picks = self.thinSection(7)
        self.assertFails(self.linear(pocket, picks, 25, 2), "instance 2 has a picked face missing")

    def testBossCopyInsideATallerStepFails(self):
        # FP17: step x 20..60, z 10..25 (base 24180), the copy at x 22..28, z 10..15 inside it.
        # Onshape: PATTERN_NOT_ON_BODY; the fuse would silently do nothing
        self.plate()
        sketch = models.sketch(self.doc, "StepSketch", models.rectangle(20, 0, 60, 20), self.body, z=10)
        models.pad(self.body, sketch, 15, name="Step")
        boss = self.boss()
        pattern = self.linear(boss, self.bossFaces(boss), 20, 2)
        self.assertFails(pattern, "instance 2 has a picked face missing")

    def testThroughHoleOntoAThickerStepFails(self):
        # FP14: step x 30..60, z 10..20 (base 17717.2567), hole r3 at (10, 10) through 10, +x 25.
        # Onshape extends the copy through all 20 (17151.77); the copy can't, so it fails (debt)
        self.plate()
        sketch = models.sketch(self.doc, "StepSketch", models.rectangle(30, 0, 60, 20), self.body, z=10)
        models.pad(self.body, sketch, 10, name="Step")
        hole = models.sketch(self.doc, "HoleSketch", [models.circle(10, 10, 3)], self.body, z=10)
        hole = models.pocketThroughAll(self.body, hole, name="Hole")
        picks = self.faces(hole, lambda c, f: f.Surface.__class__.__name__ == "Cylinder")
        self.assertEqual(len(picks), 1)
        self.assertFails(self.linear(hole, picks, 25, 2), "instance 2 doesn't open onto the part")

    def testPicksOnTwoPartsFail(self):
        # FP7: Onshape patterns each part's faces in it; here an error for now (the parts hub's T1a)
        self.body = models.body(self.doc)
        plates = models.rectangle(0, 0, 60, 20) + models.rectangle(0, 30, 60, 50)
        sketch = models.sketch(self.doc, "PlatesSketch", plates, self.body)
        models.pad(self.body, sketch, 10, name="Plates")
        bosses = models.rectangle(2, 7, 8, 13) + models.rectangle(2, 37, 8, 43)
        sketch = models.sketch(self.doc, "BossesSketch", bosses, self.body, z=10)
        boss = models.pad(self.body, sketch, 5, name="Bosses")
        self.doc.recompute()
        self.assertEqual(len(boss.Shape.Solids), 2)
        picks = self.faces(boss, lambda c, f: c.z > 10 + 1e-3)
        self.assertEqual(len(picks), 10)
        self.assertFails(self.linear(boss, picks, 20, 3), "pick faces of one part")


if __name__ == "__main__":
    unittest.main()
