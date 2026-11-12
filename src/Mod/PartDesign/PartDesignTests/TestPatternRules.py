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

"""Onshape's pattern and mirror rules (FreeCAD-CH ops#640, B3-3b, A-2' d, B3-6, E-1).

- A copy entirely off the part is dropped silently: no lump, no new part, no error; a copy that
  reaches the part, even partly, merges (B3-3b, Reapply features off).
- When no copy reaches the part (a mirror whose image is entirely off it), the feature is red,
  "Could not create all instances as entered.", and adds nothing (A-2' d).
- A feature that makes a part of its own (the first feature, or one touching nothing) keeps its
  copies: each is a part.
- A pattern or mirror with no features is red ("Select features to pattern." / "... to mirror.")
  and adds nothing; a MultiTransform's step, which has none of its own, stays valid.
- Centered and Skip instances (rank 8, E-1); Distance as the spacing keeps it when the count
  changes (B3-6).

Designed models, built by each test:
- Block: a 40 x 20 x 10 pad, x -20..20, y -10..10, z 0..10: 8000.
- Boss: a 5 x 5 x 5 pad on the block's top, x 9..14, y -2.5..2.5, z 10..15: 125. Its copies along
  X 10 apart are at x 19..24 (on the block's top for x 19..20: merged) and x 29..34 (in the air).
- Stub: a 4 x 4 x 5 pad on the block's top centred at the origin, z 10..15: 80.
- Square: a 40 x 40 x 10 pad centred at the origin (16000) with a 4 x 4 x 5 boss at x 12..16,
  y -2..2 (80), for the circular pattern about Z.
"""

import math
import unittest

import FreeCAD as App

from PartDesignTests.Scenarios import models

V = App.Vector

BLOCK = 40 * 20 * 10
BOSS = 5 * 5 * 5
STUB = 4 * 4 * 5
SQUARE = 40 * 40 * 10


class TestPatternRules(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("PartDesignTestPatternRules")
        App.ConfigSet("SuppressRecomputeRequiredDialog", "True")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    # -- models ----------------------------------------------------------------------------------

    def block(self, x0=-20, y0=-10, x1=20, y1=10):
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "BlockSketch", models.rectangle(x0, y0, x1, y1), self.body)
        self.blockPad = models.pad(self.body, sketch, 10, name="Block")
        return self.blockPad

    def topPad(self, name, x0, y0, x1, y1):
        sketch = models.sketch(
            self.doc, name + "Sketch", models.rectangle(x0, y0, x1, y1), self.body, z=10
        )
        return models.pad(self.body, sketch, 5, name=name)

    def bossed(self):
        self.block()
        self.boss = self.topPad("Boss", 9, -2.5, 14, 2.5)
        self.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, places=6)
        return self.boss

    def stubbed(self):
        self.block()
        self.stub = self.topPad("Stub", -2, -2, 2, 2)
        self.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + STUB, places=6)
        return self.stub

    def axis(self, role):
        return (models.originFeature(self.body, role), [""])

    def linear(self, original, length, occurrences, name="LinearPattern"):
        """A linear pattern along X, Extent mode: `occurrences` over `length`."""
        pattern = self.body.newObject("PartDesign::LinearPattern", name)
        pattern.Originals = [original]
        pattern.Direction = self.axis("X_Axis")
        pattern.Mode = "Extent"
        pattern.Length = length
        pattern.Occurrences = occurrences
        self.body.Tip = pattern
        return pattern

    def spaced(self, original, offset, occurrences, name="LinearPattern"):
        """A linear pattern along X, Spacing mode: neighbours `offset` apart."""
        pattern = self.body.newObject("PartDesign::LinearPattern", name)
        pattern.Originals = [original]
        pattern.Direction = self.axis("X_Axis")
        pattern.Mode = "Spacing"
        pattern.Offset = offset
        pattern.Occurrences = occurrences
        self.body.Tip = pattern
        return pattern

    def mirror(self, original, plane, name="Mirrored"):
        mirrored = self.body.newObject("PartDesign::Mirrored", name)
        mirrored.Originals = [original]
        mirrored.MirrorPlane = self.axis(plane)
        self.body.Tip = mirrored
        return mirrored

    def recompute(self):
        self.doc.recompute()

    def assertValid(self, feature):
        self.assertTrue(feature.isValid(), f"{feature.Name}: {feature.getStatusString()}")

    def assertFailed(self, feature, text):
        self.assertFalse(feature.isValid(), f"{feature.Name} is valid")
        self.assertIn(text, feature.getStatusString())

    def assertBody(self, volume, solids=1):
        self.assertAlmostEqual(self.body.Shape.Volume, volume, places=4)
        self.assertEqual(len(self.body.Shape.Solids), solids)

    def inside(self, x, y, z):
        return self.body.Shape.isInside(V(x, y, z), 1e-7, True)

    # -- off the part (B3-3b, A-2' d) ------------------------------------------------------------

    def testCopyEntirelyOffThePartIsDropped(self):
        """The boss, 3 occurrences 10 apart: the copy at x 19..24 reaches the block's top and
        merges; the one at x 29..34 is in the air and is dropped. Valid, one part, 8000 + 2 x 125."""
        boss = self.bossed()
        pattern = self.linear(boss, 20, 3)
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(BLOCK + 2 * BOSS)
        self.assertTrue(self.inside(21.5, 0, 12.5))
        self.assertFalse(self.inside(31.5, 0, 12.5))

    def testPatternWithEveryCopyOffThePartFails(self):
        """The boss, 3 occurrences 30 apart: both copies (x 39..44, 69..74) are in the air. No copy
        is made: red, Onshape's message, and the Body is the block and the boss."""
        boss = self.bossed()
        pattern = self.linear(boss, 60, 3)
        self.recompute()
        self.assertFailed(pattern, "Could not create all instances as entered.")
        self.assertBody(BLOCK + BOSS)

    def testMirrorImageOffThePartFails(self):
        """The boss mirrored in the XY plane: its image (z -15..-10) touches nothing. Red, no lump,
        no new part (A-2' d)."""
        boss = self.bossed()
        mirrored = self.mirror(boss, "XY_Plane")
        self.recompute()
        self.assertFailed(mirrored, "Could not create all instances as entered.")
        self.assertBody(BLOCK + BOSS)
        self.assertFalse(self.inside(11.5, 0, -12.5))

    def testMirrorImageOnThePartMerges(self):
        """The boss mirrored in the YZ plane: its image (x -14..-9) sits on the block. Valid."""
        boss = self.bossed()
        mirrored = self.mirror(boss, "YZ_Plane")
        self.recompute()
        self.assertValid(mirrored)
        self.assertBody(BLOCK + 2 * BOSS)
        self.assertTrue(self.inside(-11.5, 0, 12.5))

    def testPatternOfAPartOfItsOwnKeepsItsCopies(self):
        """The block itself (the first feature), 2 occurrences 50 apart: the copy (x 30..70) is a
        part of its own, as the block is. Valid, two parts, 2 x 8000."""
        block = self.block()
        self.recompute()
        pattern = self.linear(block, 50, 2)
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(2 * BLOCK, solids=2)

    # -- no features -----------------------------------------------------------------------------

    def testPatternsAndMirrorWithNoFeaturesAreRed(self):
        """A linear pattern, a circular pattern and a mirror with nothing to pattern: each red,
        with Onshape's kind of message, and the Body is unchanged (they add nothing)."""
        self.bossed()
        linear = self.body.newObject("PartDesign::LinearPattern", "LinearPattern")
        linear.Direction = self.axis("X_Axis")
        polar = self.body.newObject("PartDesign::PolarPattern", "PolarPattern")
        polar.Axis = self.axis("Z_Axis")
        mirrored = self.body.newObject("PartDesign::Mirrored", "Mirrored")
        mirrored.MirrorPlane = self.axis("YZ_Plane")
        self.recompute()
        self.assertFailed(linear, "Select features to pattern.")
        self.assertFailed(polar, "Select features to pattern.")
        self.assertFailed(mirrored, "Select features to mirror.")
        self.assertEqual(self.body.Tip, self.boss)
        self.assertValid(self.body)
        self.assertBody(BLOCK + BOSS)

        # Given its feature, the linear pattern computes
        linear.Originals = [self.boss]
        linear.Length = 10
        linear.Occurrences = 2
        self.body.Tip = linear
        self.recompute()
        self.assertValid(linear)
        self.assertBody(BLOCK + 2 * BOSS)

    def testMultiTransformStepWithNoFeaturesOfItsOwnStaysValid(self):
        """A MultiTransform of the boss with one linear step (10 along X): the step has no
        Originals of its own and is valid; the copy at x 19..24 merges."""
        boss = self.bossed()
        multi = self.body.newObject("PartDesign::MultiTransform", "MultiTransform")
        multi.Originals = [boss]
        self.body.Tip = multi
        step = self.body.newObject("PartDesign::LinearPattern", "Step")
        step.Direction = self.axis("X_Axis")
        step.Length = 10
        step.Occurrences = 2
        multi.Transformations = [step]
        self.recompute()
        self.assertValid(step)
        self.assertValid(multi)
        self.assertBody(BLOCK + 2 * BOSS)

    # -- Direction: a cylindrical face (rank 27, E-2) --------------------------------------------

    def testCylindricalFaceDirectionStepsAlongItsAxis(self):
        """A post (circle r 2 at (-10, 0) padded 10 on the block's top: its side face's axis is Z)
        and the boss; the boss patterned along the post's side face, Spacing 5, 2 occurrences: the
        copy steps along Z (onto the boss, x 9..14, z 15..20, or, if the axis points down, into
        the block), never along X or Y. Valid."""
        import Part

        self.block()
        postSketch = models.sketch(self.doc, "PostSketch", [models.circle(-10, 0, 2)], self.body, z=10)
        post = models.pad(self.body, postSketch, 10, name="Post")
        boss = self.topPad("Boss", 9, -2.5, 14, 2.5)
        self.recompute()
        side = None
        for index, face in enumerate(post.Shape.Faces, 1):
            if isinstance(face.Surface, Part.Cylinder):
                side = f"Face{index}"
        self.assertIsNotNone(side)
        pattern = self.body.newObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [boss]
        pattern.Direction = (post, [side])
        pattern.Mode = "Spacing"
        pattern.Offset = 5
        pattern.Occurrences = 2
        self.body.Tip = pattern
        self.recompute()
        self.assertValid(pattern)
        post_volume = math.pi * 2 * 2 * 10
        up = self.inside(11.5, 0, 17.5)
        if up:
            self.assertBody(BLOCK + post_volume + 2 * BOSS)
        else:
            self.assertBody(BLOCK + post_volume + BOSS)
        self.assertFalse(self.inside(16.5, 0, 12.5))
        self.assertFalse(self.inside(11.5, 5, 12.5))

    # -- Centered, Skip, Distance as spacing (rank 8) --------------------------------------------

    def testDistanceAsSpacingKeepsItWhenTheCountChanges(self):
        """The stub, Spacing 10, 2 occurrences, then 3: the pattern gets longer (x 0, 10, 20);
        the spacing stays 10 (B3-6)."""
        stub = self.stubbed()
        pattern = self.spaced(stub, 10, 2)
        self.recompute()
        self.assertBody(BLOCK + 2 * STUB)
        pattern.Occurrences = 3
        self.recompute()
        self.assertValid(pattern)
        self.assertAlmostEqual(pattern.Offset.Value, 10)
        self.assertBody(BLOCK + 3 * STUB)
        self.assertTrue(self.inside(10, 0, 12.5))
        self.assertTrue(self.inside(19, 0, 12.5))

    def testCenteredLinearPatternRunsBothWays(self):
        """The stub, Spacing 8, 3 occurrences, Centered: Onshape's count is per side, the seed
        included (oracle 9j), so x -16, -8, 0, 8, 16: five stubs, none at 24."""
        stub = self.stubbed()
        pattern = self.spaced(stub, 8, 3)
        pattern.Centered = True
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(BLOCK + 5 * STUB)
        for x in (-16, -8, 8, 16):
            self.assertTrue(self.inside(x, 0, 12.5), x)
        self.assertFalse(self.inside(-12, 0, 12.5))

    def testCenteredLinearPatternWithAnEvenCount(self):
        """The stub, Spacing 5, 4 occurrences, Centered: seven stubs, x -15 to 15, the seed the
        middle one (oracle 9j: count 4 gives 7), nothing past either end."""
        stub = self.stubbed()
        pattern = self.spaced(stub, 5, 4)
        pattern.Centered = True
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(BLOCK + 7 * STUB)
        for x in (-15, -10, -5, 5, 10, 15):
            self.assertTrue(self.inside(x, 0, 12.5), x)
        self.assertFalse(self.inside(-18, 0, 12.5))
        self.assertFalse(self.inside(18, 0, 12.5))

    def testSkippedLinearInstanceIsNotMade(self):
        """The stub, Spacing 10, 3 occurrences, instance (1, 0) skipped: x 0 and 20 only."""
        stub = self.stubbed()
        pattern = self.spaced(stub, 10, 3)
        pattern.SkippedInstances = [1, 0]
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(BLOCK + 2 * STUB)
        self.assertFalse(self.inside(10, 0, 12.5))
        self.assertTrue(self.inside(19, 0, 12.5))

        # The original is never skipped; a pair out of range is ignored
        pattern.SkippedInstances = [0, 0, 7, 0]
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(BLOCK + 3 * STUB)

    def squareWithBoss(self):
        self.block(-20, -20, 20, 20)
        self.squareBoss = self.topPad("Boss", 12, -2, 16, 2)
        self.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, SQUARE + STUB, places=6)
        return self.squareBoss

    def polar(self, original, angle, occurrences):
        pattern = self.body.newObject("PartDesign::PolarPattern", "PolarPattern")
        pattern.Originals = [original]
        pattern.Axis = self.axis("Z_Axis")
        pattern.Mode = "Extent"
        pattern.Angle = angle
        pattern.Occurrences = occurrences
        self.body.Tip = pattern
        return pattern

    def testSkippedCircularInstanceIsNotMade(self):
        """The square's boss, 360 deg, 4 occurrences, instance 2 (at 180 deg) skipped."""
        boss = self.squareWithBoss()
        pattern = self.polar(boss, 360, 4)
        pattern.SkippedInstances = [2]
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(SQUARE + 3 * STUB)
        self.assertTrue(self.inside(0, 14, 12.5))
        self.assertTrue(self.inside(0, -14, 12.5))
        self.assertFalse(self.inside(-14, 0, 12.5))

    def testCenteredCircularPatternRunsBothWays(self):
        """The square's boss, 90 deg over 3 occurrences, Centered: at -45, 0 and 45 deg, not 90."""
        boss = self.squareWithBoss()
        pattern = self.polar(boss, 90, 3)
        pattern.Centered = True
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(SQUARE + 3 * STUB)
        r = 14 / math.sqrt(2)
        self.assertTrue(self.inside(r, r, 12.5))
        self.assertTrue(self.inside(r, -r, 12.5))
        self.assertFalse(self.inside(0, 14, 12.5))


if __name__ == "__main__":
    unittest.main()
