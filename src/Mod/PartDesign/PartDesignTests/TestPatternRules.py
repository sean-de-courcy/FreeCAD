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
- Reapply on: an original that makes nothing at every instance contributes nothing, with no
  message, while another original is made; a pattern that makes nothing at all is refused
  (ops#640, a replica's circular pattern; Onshape builds it).

Designed models, built by each test:
- Block: a 40 x 20 x 10 pad, x -20..20, y -10..10, z 0..10: 8000.
- Boss: a 5 x 5 x 5 pad on the block's top, x 9..14, y -2.5..2.5, z 10..15: 125. Its copies along
  X 10 apart are at x 19..24 (on the block's top for x 19..20: merged) and x 29..34 (in the air).
- Stub: a 4 x 4 x 5 pad on the block's top centred at the origin, z 10..15: 80.
- Square: a 40 x 40 x 10 pad centred at the origin (16000) with a 4 x 4 x 5 boss at x 12..16,
  y -2..2 (80), for the circular pattern about Z.
- Tunnelled block: a 40 x 40 x 5 block with a slot, a tunnel up to the slot's wall and a hole, for
  a half-turn pattern whose tunnel instance has no length (tunnelled()).
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
        """The square's boss, 90 deg over 3 occurrences, Centered: Onshape's count is per side,
        the seed included, the angle the extent each way (oracle 9j): 0, +-45 and +-90 deg, five
        bosses, none at 180."""
        boss = self.squareWithBoss()
        pattern = self.polar(boss, 90, 3)
        pattern.Centered = True
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(SQUARE + 5 * STUB)
        r = 14 / math.sqrt(2)
        for x, y in ((r, r), (r, -r), (0, 14), (0, -14)):
            self.assertTrue(self.inside(x, y, 12.5), (x, y))
        self.assertFalse(self.inside(-14, 0, 12.5))

    def testCenteredCircularPatternWithAnEvenCount(self):
        """The square's boss, 120 deg over 4 occurrences, Centered: +-40, +-80, +-120 deg around
        the seed (oracle 9j's case), seven bosses, none at 180."""
        boss = self.squareWithBoss()
        pattern = self.polar(boss, 120, 4)
        pattern.Centered = True
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(SQUARE + 7 * STUB)
        for degrees in (-120, -80, -40, 40, 80, 120):
            a = math.radians(degrees)
            self.assertTrue(self.inside(14 * math.cos(a), 14 * math.sin(a), 12.5), degrees)
        self.assertFalse(self.inside(-14, 0, 12.5))

    # -- Reapply: an original that makes nothing at every instance (ops#640) ---------------------

    def tunnelled(self):
        """A block x, y -20..20, z 0..5 (8000) with a through-all slot x 12..18, y -12..-10 (-60).
        The slot's wall on y = -10 is the Tunnel's up-to face: a 2 x 2 rectangle x
        14..16, z 1..3 in a sketch on the plane y = 10 (its normal -y), a Pocket up to that wall,
        y -10..10 (-80). The Hole: a through-all 2 x 2 square at (0, 15), on z = 5 (-20)."""
        self.block(-20, -20, 20, 20)
        self.blockPad.Length = 5
        slotSketch = models.sketch(
            self.doc, "SlotSketch", models.rectangle(12, -12, 18, -10), self.body, z=5
        )
        self.slot = models.pocketThroughAll(self.body, slotSketch, name="Slot")
        self.recompute()
        self.assertBody(8000 - 60)
        wall = [
            index + 1
            for index, face in enumerate(self.slot.Shape.Faces)
            if abs(face.CenterOfMass.y + 10) < 1e-9 and abs(face.CenterOfMass.x - 15) < 1e-9
        ]
        self.assertEqual(len(wall), 1)
        tunnelSketch = models.sketch(
            self.doc,
            "TunnelSketch",
            models.rectangle(14, 1, 16, 3),
            self.body,
            placement=App.Placement(V(0, 10, 0), App.Rotation(V(1, 0, 0), 90)),
        )
        self.tunnel = self.body.newObject("PartDesign::Pocket", "Tunnel")
        self.tunnel.Profile = tunnelSketch
        self.tunnel.Type = "UpToFace"
        self.tunnel.UpToFace = (self.slot, [f"Face{wall[0]}"])
        self.recompute()
        self.assertValid(self.tunnel)
        self.assertBody(8000 - 60 - 80)
        self.assertFalse(self.inside(15, 0, 2))
        holeSketch = models.sketch(
            self.doc, "HoleSketch", models.rectangle(-1, 14, 1, 16), self.body, z=5
        )
        self.hole = models.pocketThroughAll(self.body, holeSketch, name="Hole")
        self.recompute()
        self.assertBody(8000 - 60 - 80 - 20)
        self.seeded = self.body.Shape.Volume

    def halfTurn(self, originals, reapply):
        """A polar pattern of the originals about Z (a datum line at the origin), 360 deg, 2
        occurrences: instance 2 is the originals turned 180 deg. The Tunnel's sketch lies there on
        y = -10, the plane of its up-to face, so its re-run there has no length."""
        line = self.body.newObject("PartDesign::Line", "ZLine")
        pattern = self.body.newObject("PartDesign::PolarPattern", "PolarPattern")
        pattern.Originals = originals
        pattern.Axis = (line, [""])
        pattern.Mode = "Extent"
        pattern.Angle = 360
        pattern.Occurrences = 2
        pattern.Reapply = reapply
        self.body.Tip = pattern
        self.recompute()
        return pattern

    def testReapplyOriginalMakingNothingAtEveryInstanceIsDropped(self):
        """Onshape (ops#640, a replica's circular pattern): with Reapply on, an original whose
        re-run fails at every instance contributes nothing there, with no message, while another
        original is made. Tunnel and Hole turned 180 deg: the Hole at (0, -15), -20; the Tunnel's
        instance makes nothing (before: refused, "can't be made at any instance")."""
        self.tunnelled()
        pattern = self.halfTurn([self.tunnel, self.hole], reapply=True)
        self.assertValid(pattern)
        self.assertBody(self.seeded - 20)
        self.assertFalse(self.inside(0, -15, 2.5))
        self.assertTrue(self.inside(-15, 0, 2))

    def testReapplyOriginalMakingNothingControls(self):
        """The Hole alone, Reapply on: -20 (the same as above). Tunnel and Hole with Reapply off:
        the Tunnel's prism is copied, x -16..-14, y -10..10 (-80), with the Hole's (-20)."""
        self.tunnelled()
        pattern = self.halfTurn([self.hole], reapply=True)
        self.assertValid(pattern)
        self.assertBody(self.seeded - 20)
        pattern.Originals = [self.tunnel, self.hole]
        pattern.Reapply = False
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(self.seeded - 100)
        self.assertFalse(self.inside(-15, 0, 2))
        self.assertFalse(self.inside(0, -15, 2.5))

    def testReapplyPatternMakingNothingAtAllFailsLoudly(self):
        """With Reapply on, a pattern none of whose originals is made at any instance stays
        refused: the Tunnel alone turned 180 deg."""
        self.tunnelled()
        pattern = self.halfTurn([self.tunnel], reapply=True)
        self.assertFailed(pattern, "can't be made at any instance")
        self.assertFailed(pattern, "instance 2")


if __name__ == "__main__":
    unittest.main()
