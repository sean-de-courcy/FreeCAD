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
- Reapply on: an original that makes nothing at every instance contributes nothing, with a
  warning (Onshape gives none), while another original is made; a pattern that makes nothing at
  all is refused (ops#640, a replica's circular pattern; Onshape builds it).
- Reapply on, an up-to face or vertex another original of the pattern made (ops#963 A): each
  instance reads its own copy of it; a maker listed after its reader is a warning; a face made
  together with an earlier feature is that feature's, outside (ops#992); an outside face stays
  the same face at every instance (Onshape O6).

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
import Part

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
        re-run fails at every instance contributes nothing there, while another original is made.
        Onshape gives no message; the fork warns (ops#963 A: never silent about a dropped
        instance). Tunnel and Hole turned 180 deg: the Hole at (0, -15), -20; the Tunnel's
        instance makes nothing (before: refused, "can't be made at any instance")."""
        self.tunnelled()
        pattern = self.halfTurn([self.tunnel, self.hole], reapply=True)
        self.assertValid(pattern)
        self.assertWarning(pattern, "isn't made at 1 of 1 instances")
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


    # -- Reapply: an up-to reference another original made (ops#963 A) ---------------------------

    def walled(self, half=50):
        """The plate 100 x 2 half x 10 about the origin, z 0..10 (100000 for half 50), and the
        Pocket 10 x 10, x 30..40, y -5..5, 6 deep from the top (-600): its walls x = 30 and x = 40,
        y = +-5, its floor z = 4. self.wall is the Pocket's wall on x = 30 (60 = 10 x 6)."""
        self.block(-50, -half, 50, half)
        pocketSketch = models.sketch(
            self.doc, "PocketSketch", models.rectangle(30, -5, 40, 5), self.body, z=10
        )
        self.pocket = models.pocket(self.body, pocketSketch, 6, name="WallPocket")
        self.recompute()
        self.assertBody(100 * 2 * half * 10 - 600)
        self.wall = self.faceOf(self.pocket, V(30, 0, 7), 60)

    def faceOf(self, feature, centre, area):
        faces = [
            index + 1
            for index, face in enumerate(feature.Shape.Faces)
            if (face.CenterOfMass - centre).Length < 1e-9 and abs(face.Area - area) < 1e-6
        ]
        self.assertEqual(len(faces), 1, f"{feature.Name}: {faces}")
        return f"Face{faces[0]}"

    def xSketch(self, name, x, geometry):
        """A sketch on the plane x = x: sketch x along y, sketch y along z, its normal +x."""
        return models.sketch(
            self.doc,
            name,
            geometry,
            self.body,
            placement=App.Placement(V(x, 0, 0), App.Rotation(V(1, 1, 1), 120)),
        )

    def barUpTo(self, link, kind="UpToFace", added=40):
        """The Bar: a 4 x 2 pad (y -2..2, z 6..8) from the plane x = 35 towards -x, up to link
        (the Pocket's wall x = 30): x 30..35 inside the Pocket, +40. Reversed is whichever way
        this build's sketch normal needs."""
        sketch = self.xSketch("BarSketch", 35, models.rectangle(-2, 6, 2, 8))
        bar = self.body.newObject("PartDesign::Pad", "Bar")
        bar.Profile = sketch
        bar.Type = kind
        bar.UpToFace = link
        before = self.body.Shape.Volume
        for reversed_ in (True, False):
            bar.Reversed = reversed_
            self.recompute()
            if bar.isValid() and abs(self.body.Shape.Volume - before - added) < 1e-6:
                break
        self.assertValid(bar)
        self.assertBody(before + added)
        return bar

    def quarterTurns(self, originals, reapply=True):
        """A polar pattern about Z, 4 over 360 deg, refined."""
        pattern = self.body.newObject("PartDesign::PolarPattern", "PolarPattern")
        pattern.Originals = originals
        pattern.Axis = self.axis("Z_Axis")
        pattern.Angle = 360
        pattern.Occurrences = 4
        pattern.Refine = True
        pattern.Reapply = reapply
        self.body.Tip = pattern
        self.recompute()
        return pattern

    def assertNoWarning(self, feature):
        self.assertNotIn("Warning", feature.State, feature.getStatusString())

    def assertWarning(self, feature, *texts):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertIn("Warning", feature.State)
        for text in texts:
            self.assertIn(text, feature.getStatusString())

    def testReapplyUpToAWallAnotherOriginalMade(self):
        """ops#963 A (scripts/repro_963_reapply_upto_face.py): the Bar ends on the Pocket's wall;
        both turned a quarter four times, Reapply on. Each instance's Bar ends on its own
        instance's wall, as Onshape's Reapply features (the team's studio): 100000 - 4 x 600 +
        4 x 40 = 97760, 6 + 4 x (5 of the pocket + 5 of the bar) = 46 faces, no warning. Before:
        97680 and 36 faces (the instances at 90 and 270 deg dropped, silently)."""
        self.walled()
        bar = self.barUpTo((self.pocket, [self.wall]))
        pattern = self.quarterTurns([self.pocket, bar])
        self.assertValid(pattern)
        self.assertNoWarning(pattern)
        self.assertBody(97760)
        self.assertEqual(len(self.body.Shape.Faces), 46)
        for x, y in ((32.5, 0), (0, 32.5), (-32.5, 0), (0, -32.5)):
            self.assertTrue(self.inside(x, y, 7), f"no bar at ({x}, {y})")

    def testReapplyUpToAWallControlOff(self):
        """The same with Reapply off (each instance a copy): 97760 too."""
        self.walled()
        bar = self.barUpTo((self.pocket, [self.wall]))
        pattern = self.quarterTurns([self.pocket, bar], reapply=False)
        self.assertValid(pattern)
        self.assertBody(97760)

    def testReapplyUpToAFloorControl(self):
        """A column up to the Pocket's floor (a 4 x 4 pad x 33..37, y -2..2 from the top down to
        z = 4, +96), which a turn about Z leaves in its plane: 100000 - 2400 + 4 x 96 = 97984,
        Reapply on, as before ops#963."""
        self.walled()
        floor = self.faceOf(self.pocket, V(35, 0, 4), 100)
        sketch = models.sketch(
            self.doc, "ColumnSketch", models.rectangle(33, -2, 37, 2), self.body, z=10
        )
        column = self.body.newObject("PartDesign::Pad", "Column")
        column.Profile = sketch
        column.Type = "UpToFace"
        column.UpToFace = (self.pocket, [floor])
        self.body.Tip = column
        for reversed_ in (True, False):
            column.Reversed = reversed_
            self.recompute()
            if column.isValid() and abs(column.Shape.Volume - 100000 + 600 - 96) < 1e-6:
                break
        self.assertBody(100000 - 600 + 96)
        pattern = self.quarterTurns([self.pocket, column])
        self.assertValid(pattern)
        self.assertNoWarning(pattern)
        self.assertBody(97984)

    def testReapplyUpToTheWallPickedOnALaterFeature(self):
        """The wall picked on a later feature's shape (the usual pick in the GUI: the tip), here a
        stud padded elsewhere after the Pocket (4 x 4 x 5 at x -32..-28, y -2..2, +80): the face's
        maker is still the Pocket, so each instance's Bar ends on its own wall: 97760 + 80."""
        self.walled()
        stud = self.topPad("Stud", -32, -2, -28, 2)
        self.recompute()
        self.assertBody(100000 - 600 + 80)
        wall = self.faceOf(stud, V(30, 0, 7), 60)
        sketch = self.xSketch("BarSketch", 35, models.rectangle(-2, 6, 2, 8))
        bar = self.body.newObject("PartDesign::Pad", "Bar")
        bar.Profile = sketch
        bar.Type = "UpToFace"
        bar.UpToFace = (stud, [wall])
        for reversed_ in (True, False):
            bar.Reversed = reversed_
            self.recompute()
            if bar.isValid() and abs(self.body.Shape.Volume - 100000 + 600 - 80 - 40) < 1e-6:
                break
        self.assertBody(100000 - 600 + 80 + 40)
        pattern = self.quarterTurns([self.pocket, bar])
        self.assertValid(pattern)
        self.assertNoWarning(pattern)
        self.assertBody(97760 + 80)

    def testReapplyUpToAVertexAnotherOriginalMade(self):
        """Up to a vertex the Pocket made, its wall's corner (30, 5, 4): the plane x = 30 at each
        instance, as the wall: 97760, no warning (the own path and its guard, FeatureExtrude.cpp
        distanceTo). Integration gets 97760 here too: the vertex it carries back gives a plane
        (x = +-5, -30) whose longer bar runs only through solid."""
        self.walled()
        vertices = [
            index + 1
            for index, vertex in enumerate(self.pocket.Shape.Vertexes)
            if (vertex.Point - V(30, 5, 4)).Length < 1e-9
        ]
        self.assertEqual(len(vertices), 1)
        bar = self.barUpTo((self.pocket, [f"Vertex{vertices[0]}"]), kind="UpToVertex")
        pattern = self.quarterTurns([self.pocket, bar])
        self.assertValid(pattern)
        self.assertNoWarning(pattern)
        self.assertBody(97760)

    def testReapplyMakerMissingAtAnInstanceWarns(self):
        """The plate 100 x 50 (y -25..25, 50000): turned a quarter, the Pocket lies off it (y
        30..40) and cuts nothing, so that instance has no wall and its Bar isn't made there (the
        guard: the instance's own copy of the wall must be on the part). The pattern warns (Onshape:
        that instance's feature fails and contributes nothing). The Pocket and the Bar at 0 and 180
        deg: 50000 - 2 x 600 + 2 x 40 = 48880. (The Originals are read in the Body's order, so a
        maker can't be listed after its reader. With the plate's edge at y = 30, in the turned
        wall's plane, the guard finds the wall on the plate's side and the bar runs to it.)"""
        self.walled(half=25)
        bar = self.barUpTo((self.pocket, [self.wall]))
        pattern = self.quarterTurns([self.pocket, bar])
        self.assertWarning(pattern, "isn't made at 2 of 3", "isn't there")
        self.assertBody(48880)
        self.assertTrue(self.inside(-32.5, 0, 7))
        self.assertFalse(self.inside(0, 32.5, 7))

    def testReapplyUpToAFaceMadeTogetherWithTheBaseIsOutside(self):
        """ops#992 (the team's mirrored case walls): a face refine merged from an original's face
        and an earlier feature's is the earlier feature's, as Onshape names it, so it stays outside
        (the same face at every instance, Onshape O6). The plate x -50..50, y -50..50, z 0..10
        (100000) and the Wall on it, x -50..50, y 40..50, z 10..20 (10000): its front y = 40. The
        Step on the Wall, x 20..30, y 40..50, z 20..25 (500, refined): its front merges with the
        Wall's into one face. The Rib, x 22..28, z 12..14, from the plane y = 30 up to that face
        (y 30..40, 120). Mirrored across YZ with Reapply: the Step and the Rib at x -30..-20, the Rib
        up to the mirrored part's y = 40: 100000 + 10000 + 2 x (500 + 120) = 111240, no warning.
        Before: refused ("made together")."""
        self.block(-50, -50, 50, 50)
        wallSketch = models.sketch(
            self.doc, "WallSketch", models.rectangle(-50, 40, 50, 50), self.body, z=10
        )
        models.pad(self.body, wallSketch, 10, name="Wall")
        stepSketch = models.sketch(
            self.doc, "StepSketch", models.rectangle(20, 40, 30, 50), self.body, z=20
        )
        step = models.pad(self.body, stepSketch, 5, name="Step")
        step.Refine = True
        self.recompute()
        self.assertBody(110500)
        front = self.faceOf(step, V(50 * 25 / 1050, 40, (1000 * 15 + 50 * 22.5) / 1050), 1050)
        # A sketch on the plane y = 30: sketch x along x, sketch y along z, its normal -y
        sketch = models.sketch(
            self.doc,
            "RibSketch",
            models.rectangle(22, 12, 28, 14),
            self.body,
            placement=App.Placement(V(0, 30, 0), App.Rotation(V(1, 0, 0), 90)),
        )
        rib = self.body.newObject("PartDesign::Pad", "Rib")
        rib.Profile = sketch
        rib.Type = "UpToFace"
        rib.UpToFace = (step, [front])
        for reversed_ in (True, False):
            rib.Reversed = reversed_
            self.recompute()
            if rib.isValid() and abs(self.body.Shape.Volume - 110620) < 1e-6:
                break
        self.assertValid(rib)
        self.assertBody(110620)
        mirrored = self.body.newObject("PartDesign::Mirrored", "Mirrored")
        mirrored.Originals = [step, rib]
        mirrored.MirrorPlane = self.axis("YZ_Plane")
        mirrored.Refine = True
        mirrored.Reapply = True
        self.body.Tip = mirrored
        self.recompute()
        self.assertValid(mirrored)
        self.assertNoWarning(mirrored)
        self.assertBody(111240)
        for x in (25, -25):
            self.assertTrue(self.inside(x, 35, 13), f"no rib at x = {x}")
            self.assertTrue(self.inside(x, 45, 22.5), f"no step at x = {x}")

    def ribToMergedSide(self):
        """Review pr992-r1: the plate x -50..50, y -50..50, z 0..10 and the Boss x 40..50, y -5..5,
        z 10..15 (refined: its side x = 50 merges with the plate's). The Rib, y -2..2, z 11..13,
        from the plane x = 60 up to that face: x 50..60 (+80): 100000 + 500 + 80."""
        self.block(-50, -50, 50, 50)
        boss = self.topPad("Boss", 40, -5, 50, 5)
        boss.Refine = True
        self.recompute()
        side = self.faceOf(boss, V(50, 0, (1000 * 5 + 50 * 12.5) / 1050), 1050)
        rib = self.barUpToFrom(60, (boss, [side]), 80)
        return boss, rib

    def barUpToFrom(self, x, link, added):
        sketch = self.xSketch("RibSketch", x, models.rectangle(-2, 11, 2, 13))
        rib = self.body.newObject("PartDesign::Pad", "Rib")
        rib.Profile = sketch
        rib.Type = "UpToFace"
        rib.UpToFace = link
        before = self.body.Shape.Volume
        for reversed_ in (True, False):
            rib.Reversed = reversed_
            self.recompute()
            if rib.isValid() and abs(self.body.Shape.Volume - before - added) < 1e-6:
                break
        self.assertValid(rib)
        self.assertBody(before + added)
        return rib

    def testReapplyMirrorMovingAMergedFaceOffItselfIsRefused(self):
        """Review pr992-r1 MadeTogetherMirrorAcross: mirrored across YZ, the merged face x = 50 goes
        to x = -50. Read as outside, the mirrored Rib would run from x = -60 across the plate to
        x = 50 (101800); read as its own, to the mirrored Boss's side (101160). Which one Onshape
        takes isn't known: refused ("can't tell"), never either guess."""
        boss, rib = self.ribToMergedSide()
        mirrored = self.body.newObject("PartDesign::Mirrored", "Mirrored")
        mirrored.Originals = [boss, rib]
        mirrored.MirrorPlane = self.axis("YZ_Plane")
        mirrored.Refine = True
        mirrored.Reapply = True
        self.body.Tip = mirrored
        self.recompute()
        self.assertFailed(mirrored, "can't tell")

    def testReapplyTurnAboutALineInTheMergedFaceIsRefused(self):
        """Review pr992-r2 MadeTogetherDiscOnAxis: two half discs r 50, z 0..10 (x >= 0, then
        x <= 0 refined: their tops merge into one face, whose only vertices (0, +-50, 10) and centre
        lie on the line along y through (0, 0, 10)). The Rib, x -25..-15, y 15..25, from z = 30 down
        to that face (+2000). Turned 30 deg about that line with Reapply, the merged face tilts:
        read as outside the turned Rib would end on z = 10, as its own on the tilted copy. Refused,
        though every point a sample would test stays on the face's plane."""
        self.body = models.body(self.doc)

        def half(name, start):
            arc = Part.ArcOfCircle(Part.Circle(V(0, 0, 0), V(0, 0, 1), 50), start, start + math.pi)
            line = Part.LineSegment(arc.EndPoint, arc.StartPoint)
            sketch = models.sketch(self.doc, name + "Sketch", [arc, line], self.body)
            return models.pad(self.body, sketch, 10, name=name)

        half("Half1", -math.pi / 2)
        half2 = half("Half2", math.pi / 2)
        half2.Refine = True
        self.recompute()
        disc = math.pi * 50 * 50 * 10
        self.assertBody(disc)
        top = self.faceOf(half2, V(0, 0, 10), math.pi * 50 * 50)
        sketch = models.sketch(
            self.doc, "RibSketch", models.rectangle(-25, 15, -15, 25), self.body, z=30
        )
        rib = self.body.newObject("PartDesign::Pad", "Rib")
        rib.Profile = sketch
        rib.Type = "UpToFace"
        rib.UpToFace = (half2, [top])
        for reversed_ in (True, False):
            rib.Reversed = reversed_
            self.recompute()
            if rib.isValid() and abs(self.body.Shape.Volume - disc - 2000) < 1e-6:
                break
        self.assertValid(rib)
        self.assertBody(disc + 2000)
        hinge = self.body.newObject("PartDesign::Line", "Hinge")
        hinge.MapMode = "Deactivated"
        hinge.Placement = App.Placement(V(0, 0, 10), App.Rotation(V(1, 0, 0), -90))
        pattern = self.body.newObject("PartDesign::PolarPattern", "PolarPattern")
        pattern.Originals = [half2, rib]
        pattern.Axis = (hinge, [""])
        pattern.Mode = "Extent"
        pattern.Angle = 30
        pattern.Occurrences = 2
        pattern.Refine = True
        pattern.Reapply = True
        self.body.Tip = pattern
        self.recompute()
        self.assertFailed(pattern, "can't tell")

    def testReapplyQuarterTurnsMovingAMergedFaceOffItselfAreRefused(self):
        """Review pr992-r1 MadeTogetherQuarterTurns: the same turned a quarter four times: at each
        instance the merged face moves off itself, so refused, as the mirror."""
        boss, rib = self.ribToMergedSide()
        pattern = self.quarterTurns([boss, rib])
        self.assertFailed(pattern, "can't tell")

    def testReapplyUpToAnOutsideFaceWithATurnedTwin(self):
        """Onshape O6q (oracle963b, 11-22): an outside face stays the same face at every instance
        of a quarter turn too, even on a part the turn maps onto itself. The plate is square, so a quarter turn maps
        its side x = 50 onto y = 50. A pad up to the plate's side (an outside face: the plate made
        it) from x = 35 in the Pocket (y -2..2, z 6..8; x 35..40 in the Pocket's air, +40) stays
        outside: at each instance it re-runs up to the seed's face carried back, never its turned
        twin. At 90 and 270 deg that face is parallel to the pad: not made, with a warning (Onshape
        makes the whole pattern an error there, PATTERN_FEATURE_FAILED; the same geometry: only
        the seed's bar). With the twin read as own every instance would have its bar (97760)."""
        self.walled()
        side = self.faceOf(self.blockPad, V(50, 0, 5), 1000)
        bar = self.barUpTo((self.blockPad, [side]), added=40)
        pattern = self.quarterTurns([self.pocket, bar])
        self.assertWarning(pattern, "isn't made at 2 of 3", "parallel")
        self.assertNotAlmostEqual(self.body.Shape.Volume, 97760, places=4)
        self.assertFalse(self.inside(0, 37.5, 7))

    def testReapplyHoleUpToAWallAnotherOriginalMade(self):
        """A hole up to the Pocket's wall: d 2, from the plane x = 20 at (y 0, z 5) towards +x, up
        to x = 30 (pi x 10 removed). Each instance's hole ends on its own wall: 100000 - 2400 -
        4 x 10 pi, no warning."""
        self.walled()
        sketch = self.xSketch("HoleSketch", 20, [models.circle(0, 5, 1)])
        hole = self.body.newObject("PartDesign::Hole", "Hole")
        hole.Profile = sketch
        hole.Diameter = 2
        hole.DrillPoint = "Flat"
        hole.DepthType = "UpToFace"
        hole.UpToFace = (self.pocket, [self.wall])
        want = 100000 - 600 - 10 * math.pi
        for reversed_ in (False, True):
            hole.Reversed = reversed_
            self.recompute()
            if hole.isValid() and abs(self.body.Shape.Volume - want) < 1e-6:
                break
        self.assertBody(want)
        pattern = self.quarterTurns([self.pocket, hole])
        self.assertValid(pattern)
        self.assertNoWarning(pattern)
        self.assertBody(100000 - 2400 - 40 * math.pi)

    def testReapplyUpToARingCapAnotherOriginalMade(self):
        """Review pr963a-r1 T1: an ellipse pad (centre (30, 20), semi-axes 4 and 2) from the
        plate's top up to the top of a ring Boss (radii 8 and 4 about (30, 0), z 10..20), both
        turned a quarter four times, Reapply on. An ellipse takes the up-to plane's blind shortcut
        (ops#751), and the ring's top plane has its origin at the ring's centre, in its hole, off
        the face: the face itself is on each instance's part, so every instance's pad is made,
        no warning: 100000 + 4 x 480 pi (rings) + 4 x 80 pi (pads). Before: the point guard ran
        on the plane's origin and dropped the instances at 90, 180 and 270 deg."""
        self.block(-50, -50, 50, 50)
        ringSketch = models.sketch(
            self.doc,
            "RingSketch",
            [models.circle(30, 0, 8), models.circle(30, 0, 4)],
            self.body,
            z=10,
        )
        ring = models.pad(self.body, ringSketch, 10, name="Ring")
        self.recompute()
        top = self.faceOf(ring, V(30, 0, 20), 48 * math.pi)
        ellipse = Part.Ellipse(V(34, 20, 0), V(30, 22, 0), V(30, 20, 0))
        sketch = models.sketch(self.doc, "EllipseSketch", [ellipse], self.body, z=10)
        pad = self.body.newObject("PartDesign::Pad", "EllipsePad")
        pad.Profile = sketch
        pad.Type = "UpToFace"
        pad.UpToFace = (ring, [top])
        self.recompute()
        self.assertValid(pad)
        self.assertBody(100000 + 480 * math.pi + 80 * math.pi)
        pattern = self.quarterTurns([ring, pad])
        self.assertValid(pattern)
        self.assertNoWarning(pattern)
        self.assertBody(100000 + 4 * 480 * math.pi + 4 * 80 * math.pi)
        for x, y in ((30, 20), (-20, 30), (-30, -20), (20, -30)):
            self.assertTrue(self.inside(x, y, 15), f"no pad at ({x}, {y})")

    def testReapplyUpToAWholeDatumPlaneAfterAnOriginal(self):
        """Review pr963a-r1 T2: a 10 x 10 pad (x -40..-30, y 20..30) from the plate's top up to a
        datum plane z = 25 as a whole object (UpToShape), the datum made after the Pocket (x
        -40..-30, y -5..5, 6 deep); both patterned along X, 3 over 40, Reapply on. The pattern
        neither makes nor moves the datum plane, so it is outside: each instance's pad ends on z =
        25, no warning: 100000 + 3 x (1500 - 600). Before: refused as a whole object made after
        an original."""
        self.block(-50, -50, 50, 50)
        pocketSketch = models.sketch(
            self.doc, "PocketSketch", models.rectangle(-40, -5, -30, 5), self.body, z=10
        )
        pocket = models.pocket(self.body, pocketSketch, 6, name="Pocket")
        datum = self.body.newObject("PartDesign::Plane", "DatumPlane")
        datum.AttachmentSupport = [(models.originFeature(self.body, "XY_Plane"), "")]
        datum.MapMode = "FlatFace"
        datum.AttachmentOffset = App.Placement(V(0, 0, 25), App.Rotation())
        sketch = models.sketch(
            self.doc, "PadSketch", models.rectangle(-40, 20, -30, 30), self.body, z=10
        )
        pad = self.body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Type = "UpToShape"
        pad.UpToShape = [(datum, [""])]
        self.recompute()
        self.assertValid(pad)
        self.assertBody(100000 - 600 + 1500)
        pattern = self.body.newObject("PartDesign::LinearPattern", "LinearPattern")
        pattern.Originals = [pocket, pad]
        pattern.Direction = self.axis("X_Axis")
        pattern.Mode = "Extent"
        pattern.Length = 40
        pattern.Occurrences = 3
        pattern.Reapply = True
        self.body.Tip = pattern
        self.recompute()
        self.assertValid(pattern)
        self.assertNoWarning(pattern)
        self.assertBody(100000 + 3 * (1500 - 600))
        for x in (-35, -15, 5):
            self.assertTrue(self.inside(x, 25, 20), f"no pad at x {x}")


    def testReapplyUpToAnOwnFaceThePatternMoves(self):
        """Review pr963a-r2 SideCap: a Block (x -10..10, y -30..-20, z 10..20) and a pad from the
        plane y = -50 along +y up to the Block's side y = -30 (20 long; an ellipse, semi-axes 4 and
        2 about (x 0, z 15): the blind shortcut; a 10 x 6 rectangle: the up-to prism), both patterned
        along Y, 2 over 60, Reapply on. The second instance's pad ends on its own Block's side (y =
        30): 100000 + 2 x 2000 + 2 x 20 x area, no warning. Integration carries the seed's face to
        the instance and the pad runs to y = -30 there, the wrong length (105256.6 against 105005.3
        for the ellipse)."""
        for ellipse in (True, False):
            with self.subTest(ellipse=ellipse):
                if hasattr(self, "body"):
                    App.closeDocument(self.doc.Name)
                    self.doc = App.newDocument("PartDesignTestPatternRules")
                self.block(-50, -50, 50, 50)
                block = self.topPad("SideBlock", -10, -30, 10, -20)
                block.Length = 10
                self.recompute()
                side = self.faceOf(block, V(0, -30, 15), 200)
                if ellipse:
                    geometry = [Part.Ellipse(V(4, -15, 0), V(0, -13, 0), V(0, -15, 0))]
                    area = 8 * math.pi
                else:
                    geometry = models.rectangle(-5, -18, 5, -12)
                    area = 60
                sketch = models.sketch(
                    self.doc,
                    "SideSketch",
                    geometry,
                    self.body,
                    placement=App.Placement(V(0, -50, 0), App.Rotation(V(1, 0, 0), -90)),
                )
                pad = self.body.newObject("PartDesign::Pad", "SidePad")
                pad.Profile = sketch
                pad.Type = "UpToFace"
                pad.UpToFace = (block, [side])
                want = 100000 + 2000 + 20 * area
                for reversed_ in (False, True):
                    pad.Reversed = reversed_
                    self.recompute()
                    if pad.isValid() and abs(self.body.Shape.Volume - want) < 1e-6:
                        break
                self.assertBody(want)
                pattern = self.body.newObject("PartDesign::LinearPattern", "LinearPattern")
                pattern.Originals = [block, pad]
                pattern.Direction = self.axis("Y_Axis")
                pattern.Mode = "Extent"
                pattern.Length = 60
                pattern.Occurrences = 2
                pattern.Reapply = True
                self.body.Tip = pattern
                self.recompute()
                self.assertValid(pattern)
                self.assertNoWarning(pattern)
                self.assertBody(100000 + 2 * 2000 + 2 * 20 * area)
                self.assertTrue(self.inside(0, 20, 15), "no pad at the second instance")


if __name__ == "__main__":
    unittest.main()
