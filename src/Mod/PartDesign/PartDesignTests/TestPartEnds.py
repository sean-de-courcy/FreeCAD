# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""A Remove that takes its whole part ends the part (FreeCAD-CH ops#1065;
notes/part-ends-1065-design.md, skeptic sk1065's cases A-O).

Onshape: a Remove through all whose tool holds all of its part is OK with no message and the part is
gone; a later feature scoped to the gone part errors. The fork: the feature is Valid, its Shape null,
PartEnded true, and the Body is an empty part as after a Delete part. A feature whose result is
empty while its tool does not provably hold the part is the kernel's error, never an end.

Designed geometry only (INSTRUCTIONS 19): a 10 x 10 x 2 block (volume 200) and cuts defined by
their rectangles. `PartDesign._testEmptyResult` empties a feature's result after its execute, as
OCCT's boolean does when it loses a part (no designed geometry does that on demand)."""

import os
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign
import Sketcher

from PartDesignTests.TestStudioSequence import rect, sketch
from PartDesignTests.TestStudioList import newStudio, studioList
from PartDesignTests.TestStudioOwner import makeOwner, studioSketch

V = App.Vector
LOST = "The geometry kernel lost the part"
LOCK = "was deleted by"


def ended(feature):
    return feature.PartEnded and feature.Shape.isNull() and feature.isValid()


class TestPartEnds(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestPartEnds")
        self.doc.UndoMode = 1
        self.emptied = []

    def tearDown(self):
        for feature in self.emptied:
            PartDesign._testEmptyResult(feature, False)
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestPartEnds"):
                App.closeDocument(doc.Name)

    # -- models ----------------------------------------------------------------------------------

    def block(self, body=None, x1=10, y1=10, height=2, name="Body"):
        body = body or self.doc.addObject("PartDesign::Body", name)
        pad = body.newObject("PartDesign::Pad", name + "Block")
        pad.Profile = sketch(body, name + "BlockSketch", (0, 0, x1, y1))
        pad.Length = height
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        return body, pad

    def pocket(self, body, *rects, z=2, through=True, name="Pocket"):
        pocket = body.newObject("PartDesign::Pocket", name)
        pocket.Profile = sketch(body, name + "Sketch", *rects, z=z)
        if through:
            pocket.Type = "ThroughAll"
        else:
            pocket.Length = 5
        self.doc.recompute()
        return pocket

    def padAfter(self, body, name="Next"):
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = sketch(body, name + "Sketch", (2, 2, 4, 4), z=2)
        pad.Length = 1
        self.doc.recompute()
        return pad

    def emptyResult(self, feature):
        PartDesign._testEmptyResult(feature, True)
        self.emptied.append(feature)
        feature.touch()
        self.doc.recompute()

    def assertEnded(self, feature, body):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertTrue(feature.PartEnded)
        self.assertTrue(feature.Shape.isNull())
        self.assertTrue(body.isValid(), body.getStatusString())
        self.assertTrue(body.Shape.isNull())

    def assertLost(self, feature):
        self.assertFalse(feature.isValid())
        self.assertIn(LOST, feature.getStatusString())
        self.assertFalse(feature.PartEnded)

    # -- design cases 1-4, 8, 9 ------------------------------------------------------------------

    def testThroughAllEndsThePart(self):
        """Case 1: a Pocket through all of a square around the block, both AllowCompound modes,
        and a blind length 5 (deeper than the block)."""
        for allow in (False, True):
            for through in (True, False):
                with self.subTest(allow=allow, through=through):
                    body, _ = self.block(name="B%d%d" % (allow, through))
                    body.AllowCompound = allow
                    pocket = self.pocket(body, (-10, -10, 20, 20), through=through, name="P%d%d" % (allow, through))
                    self.assertEnded(pocket, body)

    def testHalfLeftThenEndedThenBack(self):
        """Case 2: the square over half the block leaves volume 100; the sketch edited to cover
        all of it ends the part, and edited back the half is there again, a later Pad too."""
        body, _ = self.block()
        pocket = self.pocket(body, (5, -10, 20, 20))
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertFalse(pocket.PartEnded)
        self.assertAlmostEqual(body.Shape.Volume, 100, places=6)
        half = pocket.Profile[0]
        full = sketch(body, "FullSketch", (-10, -10, 20, 20), z=2)
        pocket.Profile = full
        self.doc.recompute()
        self.assertEnded(pocket, body)
        pad = self.padAfter(body)
        self.assertFalse(pad.isValid())
        self.assertIn(LOCK, pad.getStatusString())
        self.assertIn("'Pocket'", pad.getStatusString())
        pocket.Profile = half
        self.doc.recompute()
        self.assertFalse(pocket.PartEnded)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        # the Pad's 2 x 2 x 1 on the half left (x 0..5)
        self.assertAlmostEqual(body.Shape.Volume, 104, places=6)

    def testLaterPadRefusedThenPocketSuppressedOrRolledBack(self):
        """Case 3: a Pad after the ending Pocket fails naming it and the Body stays empty; the
        Pocket suppressed, or the bar above it, brings the block back and the Pad builds."""
        body, block = self.block()
        pocket = self.pocket(body, (-10, -10, 20, 20))
        pad = self.padAfter(body)
        self.assertFalse(pad.isValid())
        self.assertIn("'Body' was deleted by 'Pocket'", pad.getStatusString())
        self.assertTrue(body.Shape.isNull())
        pocket.Suppressed = True
        self.doc.recompute()
        self.assertFalse(pocket.PartEnded)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 204, places=6)
        pocket.Suppressed = False
        self.doc.recompute()
        self.assertTrue(pocket.PartEnded)
        self.assertFalse(pad.isValid())
        # The bar above the Pocket, as TestDeletePart's testTheBarAboveBringsItBack: the Tip is the
        # block, the Pocket is held, and the part ends again at the end
        PartDesign.rollStudioTo(self.doc, block)
        self.doc.recompute()
        self.assertIs(body.Tip, block)
        self.assertTrue(body.holds(pocket))
        self.assertAlmostEqual(block.Shape.Volume, 200, places=6)
        PartDesign.rollStudioToEnd(self.doc)
        self.doc.recompute()
        self.assertTrue(pocket.PartEnded)
        self.assertTrue(body.Shape.isNull())

    def testReopenKeepsTheEndAndTheLock(self):
        """Cases 4 and F: saved and reopened with no recompute, the states are the same; the Pad,
        touched and recomputed, is still refused naming the Pocket; the Pocket suppressed, both
        build."""
        body, _ = self.block()
        pocket = self.pocket(body, (-10, -10, 20, 20))
        pad = self.padAfter(body)
        self.assertFalse(pad.isValid())
        path = os.path.join(tempfile.mkdtemp(), "ended.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        body = self.doc.getObject("Body")
        pocket = self.doc.getObject("Pocket")
        pad = self.doc.getObject("Next")
        self.assertTrue(pocket.PartEnded)
        self.assertTrue(pocket.Shape.isNull())
        self.assertTrue(body.Shape.isNull())
        self.assertFalse(pad.isValid())
        pad.touch()
        self.doc.recompute()
        self.assertFalse(pad.isValid())
        self.assertIn("'Body' was deleted by 'Pocket'", pad.getStatusString())
        self.assertTrue(body.Shape.isNull())
        pocket.Suppressed = True
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 204, places=6)

    def testEmptiedResultsAreTheKernelsError(self):
        """Case 8 and M: a Pad, a Fillet, and cuts over half the block (Pocket, Groove, Hole) whose
        results are emptied fail with the kernel's message, never ended."""
        body, block = self.block()
        pad = self.padAfter(body, "Pad")
        self.emptyResult(pad)
        self.assertLost(pad)
        PartDesign._testEmptyResult(pad, False)
        pad.touch()
        self.doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())

        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (block, ["Edge1"])
        fillet.Radius = 0.5
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.emptyResult(fillet)
        self.assertLost(fillet)

        other, _ = self.block(name="Half")
        half = self.pocket(other, (5, -10, 20, 20), name="HalfPocket")
        self.assertTrue(half.isValid(), half.getStatusString())
        self.emptyResult(half)
        self.assertLost(half)

        third, _ = self.block(name="Holed")
        hole = third.newObject("PartDesign::Hole", "Hole")
        hs = third.newObject("Sketcher::SketchObject", "HoleSketch")
        hs.AttachmentSupport = [(third.Origin.OriginFeatures[3], "")]
        hs.MapMode = "FlatFace"
        hs.AttachmentOffset = App.Placement(V(0, 0, 2), App.Rotation())
        hs.addGeometry(Part.Circle(V(5, 5, 0), V(0, 0, 1), 2))
        hole.Profile = hs
        hole.Diameter = 4
        hole.DepthType = "ThroughAll"
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        self.emptyResult(hole)
        self.assertLost(hole)

        fourth, _ = self.block(name="Grooved")
        groove = fourth.newObject("PartDesign::Groove", "Groove")
        gs = fourth.newObject("Sketcher::SketchObject", "GrooveSketch")
        gs.AttachmentSupport = [(fourth.Origin.OriginFeatures[4], "")]  # XZ plane
        gs.MapMode = "FlatFace"
        rect(gs, 2, 0.5, 3, 1.5)
        groove.Profile = gs
        groove.ReferenceAxis = (gs, ["V_Axis"])
        groove.Angle = 360
        self.doc.recompute()
        self.assertTrue(groove.isValid(), groove.getStatusString())
        self.emptyResult(groove)
        self.assertLost(groove)

    def testToolsOverBothEndsOnly(self):
        """Case 9 (the confirmation): a bar 30 x 2 x 2 with a cut over each end and none over its
        middle, emptied: the long faces' inner points are outside: the kernel's error."""
        body, _ = self.block(x1=30, y1=2, height=2)
        pocket = self.pocket(body, (-1, -1, 5, 3), (25, -1, 31, 3))
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 80, places=6)
        self.emptyResult(pocket)
        self.assertLost(pocket)

    def testToolWithHoleIsNotAnEnd(self):
        """Review pr1065-r1 T1: a Pocket through all of -1..11 with a hole 1.0..1.6 leaves a pin
        (0.6 x 0.6 x 2); emptied, the tool's hole walls inside the block say it is no end: the
        kernel's error, at 10 mm and at 4 m."""
        for scale in (1, 400):
            with self.subTest(scale=scale):
                s = scale
                body, _ = self.block(x1=10 * s, y1=10 * s, height=2 * s, name="Pin%d" % s)
                pocket = self.pocket(body, (-1 * s, -1 * s, 11 * s, 11 * s), (1.0 * s, 1.0 * s, 1.6 * s, 1.6 * s),
                                     z=2 * s, name="PinPocket%d" % s)
                self.assertTrue(pocket.isValid(), pocket.getStatusString())
                self.assertFalse(pocket.PartEnded)
                self.assertAlmostEqual(body.Shape.Volume, 0.72 * s**3, delta=1e-6 * s**3)
                self.emptyResult(pocket)
                self.assertLost(pocket)

    def testOutOfStepSiblingDoesNotHoldThePartOff(self):
        """Review pr1065-r1 F1: a sibling that ended B, then out of step with its primary (fails
        before it runs): B is back, and a Pad after the sibling is not refused for a gone part."""
        a, ablock = self.block(name="A")
        b, _ = self.block(name="B")
        pocket = self.pocket(a, (-10, -10, 20, 20))
        [sibling] = PartDesign.makeSiblings(pocket, [b])
        self.doc.recompute()
        self.assertEnded(sibling, b)
        pocket.UpToFace = (ablock, ["Face1"])
        self.doc.recompute()
        self.assertFalse(sibling.isValid())
        self.assertFalse(sibling.PartEnded)
        pad = self.padAfter(b, "AfterSibling")
        self.assertNotIn(LOCK, pad.getStatusString())

    def testBooleanBeingSetUpIsNotAKernelError(self):
        """Review pr1065-r1 F2: a new Boolean before its first tool (its command recomputes it
        before the panel opens) is no kernel error, whatever its Type."""
        for kind in ("Fuse", "Cut", "Common"):
            with self.subTest(kind=kind):
                body, _ = self.block(name="Set" + kind)
                boolean = body.newObject("PartDesign::Boolean", "Bool" + kind)
                boolean.Type = kind
                self.doc.recompute()
                self.assertNotIn(LOST, boolean.getStatusString())
                self.assertFalse(boolean.PartEnded)

    def testHeldEnderRecomputedKeepsItsEnd(self):
        """Review pr1065-r1 F3: the ending Pocket held by the bar and recomputed directly keeps
        its end; at the end of the history a Pad after it is still refused."""
        body, block = self.block()
        pocket = self.pocket(body, (-10, -10, 20, 20))
        PartDesign.rollStudioTo(self.doc, block)
        self.doc.recompute()
        pocket.recompute()
        self.assertTrue(pocket.PartEnded)
        PartDesign.rollStudioToEnd(self.doc)
        self.doc.recompute()
        self.assertTrue(pocket.PartEnded)
        pad = self.padAfter(body)
        self.assertFalse(pad.isValid())
        self.assertIn(LOCK, pad.getStatusString())

    def testToolWithAnUnsampledHoleIsNotAnEnd(self):
        """Review pr1065-r1 F4: a Pocket through all of -10..20 with a round hole r 0.4 at
        (1.3, 1.7), between the block's samples, leaves a cylinder; emptied, the hole's wall
        inside the block says it is no end: the kernel's error."""
        body, _ = self.block()
        pocket = body.newObject("PartDesign::Pocket", "HolePocket")
        sk = sketch(body, "HolePocketSketch", (-10, -10, 20, 20), z=2)
        sk.addGeometry(Part.Circle(V(1.3, 1.7, 0), V(0, 0, 1), 0.4))
        pocket.Profile = sk
        pocket.Type = "ThroughAll"
        self.doc.recompute()
        self.assertTrue(pocket.isValid(), pocket.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 3.14159265 * 0.16 * 2, places=5)
        self.emptyResult(pocket)
        self.assertLost(pocket)

    # -- sk1065's cases --------------------------------------------------------------------------

    def testToolEqualToThePart(self):
        """A: a Pocket through all of the block's own square: everything ON the tool: ended."""
        body, _ = self.block()
        pocket = self.pocket(body, (0, 0, 10, 10))
        self.assertEnded(pocket, body)

    def booleanTool(self, name, shape):
        source = self.doc.addObject("Part::Feature", name + "Shape")
        source.Shape = shape
        tool = self.doc.addObject("PartDesign::Body", name)
        tool.BaseFeature = source
        self.doc.recompute()
        return tool

    def testClosedCavityIsNotAnEnd(self):
        """B: a box 30^3 with a closed 10^3 cavity around the block (Boolean Cut), its result
        emptied: on the tool is not in it: the kernel's error."""
        body, _ = self.block(height=10)
        outer = Part.makeBox(30, 30, 30, V(-10, -10, -10))
        cavity = outer.cut(Part.makeBox(10, 10, 10, V(0, 0, 0)))
        self.assertEqual(len(cavity.Shells), 2)
        tool = self.booleanTool("Cavity", cavity)
        cut = body.newObject("PartDesign::Boolean", "Cut")
        cut.setObjects([tool])
        cut.Type = "Cut"
        self.doc.recompute()
        self.emptyResult(cut)
        self.assertLost(cut)

    def testSlabThroughACylinderIsNotAnEnd(self):
        """C: a cylinder r 5, h 10, and a Pocket of a slab y -0.1..0.1 through its axis, emptied:
        the boxes reject it: the kernel's error."""
        body = self.doc.addObject("PartDesign::Body", "Body")
        cs = body.newObject("Sketcher::SketchObject", "CircleSketch")
        cs.AttachmentSupport = [(body.Origin.OriginFeatures[3], "")]
        cs.MapMode = "FlatFace"
        cs.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), 5))
        pad = body.newObject("PartDesign::Pad", "Cylinder")
        pad.Profile = cs
        pad.Length = 10
        body.AllowCompound = True
        self.doc.recompute()
        pocket = self.pocket(body, (-6, -0.1, 6, 0.1), z=10)
        self.assertFalse(pocket.PartEnded)
        self.emptyResult(pocket)
        self.assertLost(pocket)

    def testPlacedAndTurnedBody(self):
        """D: case 1 in a Body at (100, 50, 20) turned 30 degrees about z: ended; case 2: 100."""
        place = App.Placement(V(100, 50, 20), App.Rotation(V(0, 0, 1), 30))
        body, _ = self.block()
        body.Placement = place
        pocket = self.pocket(body, (-10, -10, 20, 20))
        self.assertEnded(pocket, body)
        other, _ = self.block(name="Other")
        other.Placement = place
        half = self.pocket(other, (5, -10, 20, 20), name="Half")
        self.assertFalse(half.PartEnded)
        self.assertAlmostEqual(other.Shape.Volume, 100, places=6)

    def testBrokenSketchBringsThePartBack(self):
        """E: the ended Pocket's profile broken (a side deleted: an open wire): the Pocket in
        error, PartEnded false, the block back (volume 200)."""
        body, _ = self.block()
        pocket = self.pocket(body, (-10, -10, 20, 20))
        self.assertTrue(pocket.PartEnded)
        sk = pocket.Profile[0]
        sk.delGeometry(0)
        self.doc.recompute()
        self.assertFalse(pocket.isValid())
        self.assertFalse(pocket.PartEnded)
        self.assertAlmostEqual(body.Shape.Volume, 200, places=6)

    def testUndoAndRedo(self):
        """G: undo of the edit that ended the part: volume 100 and the later Pad builds; redo:
        ended and refused."""
        body, _ = self.block()
        pocket = self.pocket(body, (5, -10, 20, 20))
        full = sketch(body, "FullSketch", (-10, -10, 20, 20), z=2)
        pad = self.padAfter(body)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.doc.openTransaction("End it")
        pocket.Profile = full
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertTrue(pocket.PartEnded)
        self.assertFalse(pad.isValid())
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse(pocket.PartEnded)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.doc.redo()
        self.doc.recompute()
        self.assertTrue(pocket.PartEnded)
        self.assertFalse(pad.isValid())
        self.assertIn(LOCK, pad.getStatusString())

    def testAbuttingToolsEndThePart(self):
        """Review pr1065-r2 R2-1: a Boolean Cut by two tool Bodies that meet at x 5 inside the
        block, and by one tool Body made of two touching boxes: each holds all of it: ended."""
        body, _ = self.block()
        left = self.booleanTool("Left", Part.makeBox(6, 12, 4, V(-1, -1, -1)))
        right = self.booleanTool("Right", Part.makeBox(6, 12, 4, V(5, -1, -1)))
        cut = body.newObject("PartDesign::Boolean", "Cut")
        cut.setObjects([left, right])
        cut.Type = "Cut"
        self.doc.recompute()
        self.assertEnded(cut, body)

        other, _ = self.block(name="Other")
        pair = Part.makeCompound([Part.makeBox(6, 12, 4, V(-1, -1, -1)), Part.makeBox(6, 12, 4, V(5, -1, -1))])
        tool = self.booleanTool("Pair", pair)
        cut2 = other.newObject("PartDesign::Boolean", "Cut2")
        cut2.setObjects([tool])
        cut2.Type = "Cut"
        self.doc.recompute()
        self.assertEnded(cut2, other)

    def testBooleanIntersectOfDisjointBodies(self):
        """H: a Boolean Intersect of two disjoint Bodies leaves nothing: ended; with Keep tools
        both as they were."""
        body, _ = self.block()
        tool = self.booleanTool("Far", Part.makeBox(5, 5, 5, V(50, 0, 0)))
        common = body.newObject("PartDesign::Boolean", "Common")
        common.setObjects([tool])
        common.Type = "Common"
        self.doc.recompute()
        self.assertEnded(common, body)
        common.KeepTools = True
        self.doc.recompute()
        self.assertTrue(common.isValid(), common.getStatusString())
        self.assertFalse(common.PartEnded)
        self.assertAlmostEqual(body.Shape.Volume, 200, places=6)
        self.assertAlmostEqual(tool.Shape.Volume, 125, places=6)

    def testIntersectToolInsideIsNotAnEnd(self):
        """I: a Boolean Intersect with a 2^3 tool inside a 10^3 base, emptied: the kernel's error
        (the mirror test both ways)."""
        body, _ = self.block(height=10)
        tool = self.booleanTool("Inner", Part.makeBox(2, 2, 2, V(4, 4, 4)))
        common = body.newObject("PartDesign::Boolean", "Common")
        common.setObjects([tool])
        common.Type = "Common"
        self.doc.recompute()
        self.assertTrue(common.isValid(), common.getStatusString())
        self.assertAlmostEqual(body.Shape.Volume, 8, places=6)
        self.emptyResult(common)
        self.assertLost(common)

    def testKeepToolsBooleanReadsTheEndedPartWhole(self):
        """K: Body A used whole by a keep-tools Boolean in Body B; a Pocket that takes all of A
        ends A, and B's Boolean reads the whole-part lock (the known difference, ops#1065 note 5)."""
        a, _ = self.block(name="A")
        b, _ = self.block(name="B", x1=30, y1=30)
        b.Placement = App.Placement(V(-10, -10, -1), App.Rotation())
        self.doc.recompute()
        fuse = b.newObject("PartDesign::Boolean", "Fuse")
        fuse.setObjects([a])
        fuse.KeepTools = True
        self.doc.recompute()
        self.assertTrue(fuse.isValid(), fuse.getStatusString())
        pocket = self.pocket(a, (-10, -10, 20, 20))
        self.assertEnded(pocket, a)
        self.assertFalse(fuse.isValid())
        self.assertIn("uses the whole of 'A'", fuse.getStatusString())

    def testPatternWhoseSecondInstanceTakesTheRest(self):
        """L: a Pocket through x 0..5 and its linear pattern at 5 (Reapply off): the second
        instance takes the rest: ended. The same pattern with an additive original, emptied:
        the kernel's error."""
        body, _ = self.block()
        pocket = self.pocket(body, (-1, -1, 5, 11))
        self.assertAlmostEqual(body.Shape.Volume, 100, places=6)
        pattern = body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [pocket]
        pattern.Direction = (body.Origin.OriginFeatures[0], [""])
        pattern.Length = 5
        pattern.Occurrences = 2
        if hasattr(pattern, "Reapply"):
            pattern.Reapply = False
        body.Tip = pattern
        self.doc.recompute()
        self.assertEnded(pattern, body)

        other, _ = self.block(name="Mixed")
        cut = self.pocket(other, (-1, -1, 5, 11), name="MixedPocket")
        boss = other.newObject("PartDesign::Pad", "Boss")
        boss.Profile = sketch(other, "BossSketch", (6, 6, 8, 8), z=2)
        boss.Length = 1
        self.doc.recompute()
        mixed = other.newObject("PartDesign::LinearPattern", "MixedPattern")
        mixed.Originals = [cut, boss]
        mixed.Direction = (other.Origin.OriginFeatures[0], [""])
        mixed.Length = 1
        mixed.Occurrences = 2
        other.Tip = mixed
        self.doc.recompute()
        self.assertTrue(mixed.isValid(), mixed.getStatusString())
        self.emptyResult(mixed)
        self.assertLost(mixed)

    def testThinBar(self):
        """O: a bar 30 x 2 x 0.001 under a covering cut: ended; under a cut over half: 0.03 left."""
        body, _ = self.block(x1=30, y1=2, height=0.001)
        pocket = self.pocket(body, (-1, -1, 31, 3), z=0.001)
        self.assertEnded(pocket, body)
        other, _ = self.block(name="Half", x1=30, y1=2, height=0.001)
        half = self.pocket(other, (15, -1, 31, 3), z=0.001, name="HalfPocket")
        self.assertFalse(half.PartEnded)
        self.assertAlmostEqual(other.Shape.Volume, 0.03, places=9)


class TestPartEndsStudio(unittest.TestCase):
    """Cases 5, 6 and J in a studio of three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50)."""

    def setUp(self):
        self.doc, self.studio = newStudio("TestPartEndsStudio")
        studioList(self.doc)
        self.emptied = []

    def tearDown(self):
        for feature in self.emptied:
            PartDesign._testEmptyResult(feature, False)
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestPartEndsStudio"):
                App.closeDocument(doc.Name)

    def owner(self, name, rects, scope, kind="Pocket", **values):
        sk = studioSketch(self.doc, self.studio, name + "Sk", rects, z=10)
        values.setdefault("Type", "ThroughAll")
        owner = makeOwner(self.doc, self.studio, kind, name, sk, scope, **values)
        self.doc.recompute()
        return owner

    def live(self):
        return sorted(b.Name for b in PartDesign.studioLiveParts(self.doc.getObject("A")))

    def testStudioRemoveEndsOnePart(self):
        """Case 5: a studio Remove over all of B: the owner Valid, B ended, A and C unchanged, B no
        longer offered."""
        remove = self.owner("RemoveB", ((19, -1, 31, 11),), ("B",))
        step = PartDesign.studioStepOf(remove, self.doc.getObject("B"))
        self.assertTrue(remove.isValid(), remove.getStatusString())
        self.assertTrue(step.isValid(), step.getStatusString())
        self.assertTrue(step.PartEnded)
        self.assertTrue(self.doc.getObject("B").Shape.isNull())
        self.assertAlmostEqual(self.doc.getObject("A").Shape.Volume, 1000, places=6)
        self.assertAlmostEqual(self.doc.getObject("C").Shape.Volume, 1000, places=6)
        self.assertEqual(self.live(), ["A", "C"])

    def testMergeWithAllAfterAnEnd(self):
        """Cases 6 and J: after B ended, a Remove with Merge with all over A and B: the owner
        Valid, A cut, B's step Valid with nothing and B empty; scoped to B alone: B's step fails
        on the lock."""
        self.owner("RemoveB", ((19, -1, 31, 11),), ("B",))
        later = self.owner("Later", ((5, 2, 25, 8),), ("A", "B"), Type="Length", Length=3)
        PartDesign.studioSetMergeAll(later, True)
        self.doc.recompute()
        b = self.doc.getObject("B")
        self.assertTrue(later.isValid(), later.getStatusString())
        stepA = PartDesign.studioStepOf(later, self.doc.getObject("A"))
        self.assertTrue(stepA.isValid(), stepA.getStatusString())
        self.assertAlmostEqual(self.doc.getObject("A").Shape.Volume, 1000 - 5 * 6 * 3, places=6)
        stepB = PartDesign.studioStepOf(later, b)
        if stepB is not None:
            self.assertTrue(stepB.isValid(), stepB.getStatusString())
            self.assertTrue(stepB.Shape.isNull())
            self.assertFalse(stepB.PartEnded)
        self.assertTrue(b.Shape.isNull())
        PartDesign.studioSetMergeAll(later, False)
        later.StudioScope = ["B"]
        PartDesign.studioSetScopeIds(later, ["B"])
        self.doc.recompute()
        stepB = PartDesign.studioStepOf(later, b)
        self.assertIsNotNone(stepB)
        self.assertFalse(stepB.isValid())
        self.assertIn(LOCK, stepB.getStatusString())
        self.assertTrue(b.Shape.isNull())


if __name__ == "__main__":
    unittest.main()
