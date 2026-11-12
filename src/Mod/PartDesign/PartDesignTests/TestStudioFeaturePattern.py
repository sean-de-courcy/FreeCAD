# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 T1a (notes/parts-design.md 10.16 and its settled points): the feature pattern
# as an owner over parts
#
# In a listed studio a Linear pattern, Polar pattern or Mirror made outside every Body is a studio
# feature (an owner): one entry in the list, and one step of its own type in each part some
# original acts on (its scope is derived: settled 5, no following of absorbed parts). Reconcile
# copies the owner's Originals onto each step, each mapped to that part (an owner original to its
# step there, a member of another Body left out: T1.4); a step whose Originals differ fails loudly
# (settled 1). The transforms are the owner's, its references resolved in the document's frame
# once and conjugated into each step's Body (settled 4). The owner computes no shape (settled 6).
# Refused in Onshape's words: an Add seed whose scope has two or more parts with Reapply off
# (settled 2, oracle Q2), a seed that split its part with Reapply off (O7, settled 7), an original
# whose part was absorbed before the pattern (T1.9, Q8).
#
# T1b: with Reapply on, an Add seed over two or more parts merges instance by instance what its
# instances join (settled 2, Onshape Q2: one part with the first part's id; the pattern's own merge
# record, read by the list: settled 8); an instance joining no part is a new part (Q7). A New seed's
# instances are new parts, never in the seed's part (settled 3, Q1), made by the command (P6p, ids
# "<pattern>:k"). A seed that split its part, with Reapply on: every piece is cut at every
# instance (settled 7, O7 through: 8 parts); a piece an instance cuts further is split by the
# pattern, its pieces parts "<pattern>:k" made by the command (P6p). A pattern whose every original
# is suppressed fails in Onshape's words (oracle 9j).
#
# Designed geometry only: plates and bosses whose volumes come from their dimensions.

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestStudioList import booleanOwner, elementNames, studioList
from PartDesignTests.TestStudioOwner import makeOwner, studioSketch
from PartDesignTests.TestStudioPatterns import box, linear, newStudio

V = App.Vector
# Onshape's words for PATTERN_SWITCH_TO_PER_INSTANCE (onshape-facts U6)
SWITCH_WORDS = ("Could not create all instances as entered.", 'Try selecting "Reapply features" option.')
X_AXIS, Y_AXIS, Z_AXIS, XY_PLANE, XZ_PLANE, YZ_PLANE = range(6)
HOLE_R = 3.0
HOLE = math.pi * HOLE_R**2
PLATE = 60 * 20 * 10  # 12000


def origin(studio, index):
    """A feature of the studio's own origin (Top is XY_PLANE)."""
    return (studio.Origin.OriginFeatures[index], [""])


def ownerPattern(doc, studio, kind, name, originals, reapply=False, index=-1, **values):
    """A feature pattern made outside every Body (PartDesign::<kind>), listed at index, computed."""
    p = doc.addObject("PartDesign::" + kind, name)
    studio.addObject(p)
    p.Originals = list(originals)
    for key, value in values.items():
        setattr(p, key, value)
    p.Reapply = reapply
    PartDesign.studioInsert(p, index)
    doc.recompute()
    return p


def linearOwner(doc, studio, name, originals, length, count, direction=None, **kw):
    return ownerPattern(
        doc,
        studio,
        "LinearPattern",
        name,
        originals,
        Direction=direction or origin(studio, X_AXIS),
        Mode="Extent",
        Length=length,
        Occurrences=count,
        **kw,
    )


class TestStudioFeaturePattern(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.dir = None

    def tearDown(self):
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def studio(self, parts, name="TestStudioFeaturePattern"):
        doc, studio = newStudio(name, parts)
        self.docs.append(doc.Name)
        self.doc, self.S = doc, studio
        self.list = studioList(doc)
        return doc, studio

    def twoPlates(self, height=10):
        """A x 0..60, y 0..20 and B x 0..60, y 30..50, both z 0..height (O7)."""
        return self.studio(
            (("A", (0, 0, 60, 20), height), ("B", (0, 30, 60, 50), height))
        )

    def part(self, name):
        return self.doc.getObject(name)

    def step(self, owner, part):
        return PartDesign.studioStepOf(owner, self.part(part))

    def assertValid(self, *features):
        for f in features:
            self.assertTrue(f.isValid(), f"{f.Name}: {f.getStatusString()}")

    def assertRefused(self, feature, *words):
        self.assertFalse(feature.isValid(), f"{feature.Name} computed: no refusal")
        status = feature.getStatusString()
        for word in words:
            self.assertIn(word, status, status)

    def assertVolume(self, part, expected):
        body = self.part(part)
        self.assertAlmostEqual(body.Tip.Shape.Volume, expected, places=3, msg=part)

    def groove(self, depth=5, name="Groove"):
        """O7's seed: a groove x 2..8 across both plates, Remove depth deep, scope A, B."""
        sk = studioSketch(self.doc, self.S, name + "Sk", rects=((2, -5, 8, 55),), z=10)
        return makeOwner(self.doc, self.S, "Pocket", name, sk, ("A", "B"), Length=depth, Refine=True)

    def hole(self, part, x, y, name, depth=5):
        """A Remove owner on part: a circle r3 at (x, y) from z 10 down depth."""
        sk = studioSketch(self.doc, self.S, name + "Sk", z=10, circles=((x, y, HOLE_R),))
        return makeOwner(self.doc, self.S, "Pocket", name, sk, (part,), Length=depth, Refine=True)

    def boss(self, part, rect, name, length=5, z=10, scope=None):
        """An Add owner on part: a rectangle at z padded up by length."""
        sk = studioSketch(self.doc, self.S, name + "Sk", rects=(rect,), z=z)
        return makeOwner(
            self.doc, self.S, "Pad", name, sk, scope or (part,), Length=length, Refine=True
        )

    # ------------------------------------------------------------------------------- acceptance
    def testO7GrooveOverTwoPartsIsOneOwnerWithAStepInEach(self):
        """Acceptance 1 (O7): the groove over A and B patterned +x 20 x 3: one entry, a
        LinearPattern step in each part, each part 12000 - 3 x 6 x 20 x 5 = 10200, ids kept."""
        self.twoPlates()
        g = self.groove()
        self.doc.recompute()
        ids = (self.part("A").StudioPartId, self.part("B").StudioPartId)
        self.assertEqual(ids, ("A", "B"))
        lp = linearOwner(self.doc, self.S, "LP", [g], 40, 3)
        self.assertValid(g, lp)
        self.assertEqual([e.Name for e in self.list.Entries].count("LP"), 1)
        self.assertNotIn(lp, self.part("A").Group)
        for p in ("A", "B"):
            s = self.step(lp, p)
            self.assertIsNotNone(s, p)
            self.assertEqual(s.TypeId, "PartDesign::LinearPattern")
            self.assertEqual(list(s.Originals), [self.step(g, p)])
            self.assertValid(s)
            self.assertVolume(p, PLATE - 3 * 6 * 20 * 5)
        self.assertEqual((self.part("A").StudioPartId, self.part("B").StudioPartId), ids)
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 2)
        self.assertTrue(lp.Shape.isNull())

    def testEachPartTakesOnlyItsOwnInstances(self):
        """Acceptance 2: a boss on A and a hole on B in one pattern +x 20 x 3: A gains three
        bosses and B three holes; each step lists only its own part's original."""
        self.twoPlates()
        b = self.boss("A", (5, 5, 10, 10), "Boss")
        h = self.hole("B", 7.5, 40, "Hole")
        lp = linearOwner(self.doc, self.S, "LP", [b, h], 40, 3)
        self.assertValid(lp)
        self.assertEqual(list(self.step(lp, "A").Originals), [self.step(b, "A")])
        self.assertEqual(list(self.step(lp, "B").Originals), [self.step(h, "B")])
        self.assertVolume("A", PLATE + 3 * 125)
        self.assertVolume("B", PLATE - 3 * HOLE * 5)

    def testOriginalOnAnotherPartThanTheActiveOne(self):
        """Acceptance 3 (report 19): the original acts on B only: a step in B, none in A."""
        self.twoPlates()
        h = self.hole("B", 7.5, 40, "Hole")
        lp = linearOwner(self.doc, self.S, "LP", [h], 40, 3)
        self.assertValid(lp)
        self.assertIsNone(self.step(lp, "A"))
        self.assertVolume("A", PLATE)
        self.assertVolume("B", PLATE - 3 * HOLE * 5)

    def testR1BlockAsAnOwnerIsInstanceByInstance(self):
        """Acceptance 4 (R1): block 100 x 20 x 10, boss A and slot B, the pattern [A, B] +x 20 x 3
        as an owner: 22640 with Reapply off and on, boss 3 solid at (52.5, 10, 15)."""
        self.studio((("P", (0, 0, 100, 20), 10),))
        a = self.boss("P", (10, 5, 20, 15), "A", length=10)
        sk = self.doc.addObject("Sketcher::SketchObject", "BSk")
        self.S.addObject(sk)
        sk.Placement = App.Placement(V(15, 0, 0), App.Rotation(V(0, 1, 0), 90))
        from PartDesignTests.TestStudio import rect

        rect(sk, -18, 8, -12, 12)
        b = makeOwner(self.doc, self.S, "Pocket", "B", sk, ("P",), Length=20, Reversed=True)
        self.doc.recompute()
        lp = linearOwner(self.doc, self.S, "LP", [a, b], 40, 3)
        for reapply in (False, True):
            with self.subTest(reapply=reapply):
                lp.Reapply = reapply
                self.doc.recompute()
                self.assertValid(lp, self.step(lp, "P"))
                self.assertVolume("P", 22640)
                tip = self.part("P").Tip.Shape
                self.assertTrue(tip.isInside(V(52.5, 10, 15), 1e-6, True))
                self.assertFalse(tip.isInside(V(57.5, 10, 15), 1e-6, True))

    def splitPlates(self):
        """O7's variant: the groove cut through (10 deep) splits each plate; pieces made."""
        self.twoPlates()
        g = self.groove(depth=10)
        self.doc.recompute()
        self.doc.openTransaction("pieces")
        PartDesign.studioMakePieces(g)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 4)
        return g

    def testSplittingSeedWithReapplyOffIsRefusedInOnshapesWords(self):
        """Acceptance 5's refusal (O7, settled 7): a seed that split its parts, Reapply off:
        refused in Onshape's words for PATTERN_SWITCH_TO_PER_INSTANCE (fact U6)."""
        g = self.splitPlates()
        lp = linearOwner(self.doc, self.S, "LP", [g], 40, 3)
        self.assertRefused(lp, *SWITCH_WORDS)

    def liveParts(self):
        """Each live part's id -> its volume."""
        return {
            b.StudioPartId: b.Shape.Volume for b in PartDesign.studioLiveParts(self.list)
        }

    def assertParts(self, expected):
        """The live parts: per plate, the volumes expected (sorted), ids of the seed's pieces
        ("Groove:") or the pattern's ("LP:")."""
        parts = self.liveParts()
        self.assertEqual(len(parts), len(expected), parts)
        self.assertEqual(
            sorted(round(v, 3) for v in parts.values()), sorted(float(v) for v in expected), parts
        )
        return parts

    def splitPattern(self, length=40, count=3):
        """Acceptance 5's state: the through groove's pattern, Reapply on, its pieces made."""
        g = self.splitPlates()
        lp = linearOwner(self.doc, self.S, "LP", [g], length, count, reapply=True)
        return g, lp

    # Each plate's pieces with the through groove at x 2, 22, 42: x 0..2, 8..22, 28..42, 48..60
    EIGHT = (400, 2800, 2800, 2400) * 2

    def testSplittingSeedWithReapplyOnCutsEveryPiece(self):
        """Acceptance 5 (O7 through, settled 7): the pattern of a seed that split both plates,
        Reapply on: loud until the command (the instances split the x 8..60 pieces further), then
        8 parts. The x 0..2 pieces, which no instance reaches, keep the seed's ids; the pieces cut
        further are gone, their pieces new parts '<pattern>:k' (S1: both sides new ids)."""
        g, lp = self.splitPattern()
        self.assertValid(lp)
        cut = [b for b in PartDesign.studioLiveParts(self.list) if b.Shape.Volume > 1000]
        self.assertEqual(len(cut), 2)
        for body in cut:
            s = PartDesign.studioStepOf(lp, body)
            self.assertIsNotNone(s, body.StudioPartId)
            self.assertEqual(s.TypeId, "PartDesign::LinearPattern")
            self.assertEqual(list(s.Originals), [self.step(g, "A" if body.StudioParentId == "A" else "B")])
            self.assertRefused(s, "press OK")
        made = self.makePieces(lp)
        self.assertEqual(len(made), 6)
        self.assertValid(lp)
        parts = self.assertParts(self.EIGHT)
        seeds = sorted(i for i in parts if i.startswith("Groove:"))
        self.assertEqual(len(seeds), 2)
        for i in seeds:
            self.assertAlmostEqual(parts[i], 400, places=3)
        self.assertEqual(len([i for i in parts if i.startswith("LP:")]), 6)
        for body in made:
            self.assertEqual(body.StudioMadeBy, lp)
            self.assertIn(body.StudioParentId, [b.StudioPartId for b in cut])
        for body in cut:
            self.assertNotIn(body.StudioPartId, parts)

    def testSplitSeedPatternWithAnInstanceOffThePartMakesNoExtraPiece(self):
        """An instance that reaches no part (the 4th, x 62..68) cuts nothing and makes no piece:
        the same 8 parts, 6 made."""
        g, lp = self.splitPattern(length=60, count=4)
        self.assertEqual(len(self.makePieces(lp)), 6)
        self.assertValid(lp)
        self.assertParts(self.EIGHT)

    def testSplitSeedPatternCountChangeKeepsIds(self):
        """Count 4 -> 3 -> 4 at a spacing of 15 (unverified on Onshape; 10.12's rules): with 3
        the x 38..60 solid holds two records, the one whose walls it keeps holds it and the
        other is absorbed (Q14e, quiet); with 4 again every id is back on its side."""
        g, lp = self.splitPattern(length=45, count=4)
        self.makePieces(lp)
        self.assertValid(lp)
        four = self.assertParts((400, 1800, 1800, 1800, 1400) * 2)
        lp.Occurrences = 3
        lp.Length = 30
        self.doc.recompute()
        self.assertValid(lp)
        three = self.assertParts((400, 1800, 1800, 4400) * 2)
        self.assertLess(set(three), set(four))
        for i, v in three.items():
            if abs(v - 4400) > 1e-3:
                self.assertAlmostEqual(v, four[i], places=3)
        lp.Occurrences = 4
        lp.Length = 45
        self.doc.recompute()
        self.assertValid(lp)
        again = self.liveParts()
        self.assertEqual(set(again), set(four))
        for i, v in again.items():
            self.assertAlmostEqual(v, four[i], places=3, msg=i)

    def testSplitSeedStoppedByAnEditWithThePatternOverIt(self):
        """10.12's amendment ("a split that stops") under the pattern: the groove made 5 deep,
        the seed's split is gone and so are the pieces the pattern cut from its pieces: A and B
        are parts again, each grooved 3 times (12000 - 3 x 600), nothing failed. Through again,
        the 8 parts come back with their ids."""
        g, lp = self.splitPattern()
        self.makePieces(lp)
        eight = self.liveParts()
        g.Length = 5
        self.doc.recompute()
        self.assertValid(g, lp)
        parts = self.assertParts((PLATE - 3 * 600,) * 2)
        self.assertEqual(set(parts), {"A", "B"})
        for p in ("A", "B"):
            self.assertValid(self.step(lp, p))
        g.Length = 10
        self.doc.recompute()
        self.assertValid(g, lp)
        back = self.liveParts()
        self.assertEqual(set(back), set(eight))
        for i, v in back.items():
            self.assertAlmostEqual(v, eight[i], places=3, msg=i)

    def testSplitSeedPatternUndoRedoAndSaveReopen(self):
        """Acceptance 11 for a split seed: the pattern and its pieces made in one transaction go
        with undo (4 parts) and come back with redo (8); saved and opened again, the same parts
        with equal element names."""
        g = self.splitPlates()
        self.doc.openTransaction("pattern")
        lp = linearOwner(self.doc, self.S, "LP", [g], 40, 3, reapply=True)
        PartDesign.studioMakePieces(lp)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertParts(self.EIGHT)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("LP"))
        self.assertParts((400, 10400) * 2)
        self.doc.redo()
        self.doc.recompute()
        self.assertValid(self.doc.getObject("LP"))
        self.assertParts(self.EIGHT)

        def names():
            return {
                b.StudioPartId: elementNames(b.Shape)
                for b in PartDesign.studioLiveParts(self.list)
            }

        before = names()
        self.reopen()
        self.assertValid(self.doc.getObject("LP"))
        self.assertParts(self.EIGHT)
        self.assertEqual(names(), before)

    def testLaterFeatureScopedToTheSplitPartReachesEveryPiece(self):
        """A Remove scoped to A after the pattern (a groove along x, y 9..11, 2 deep) resolves to
        A's four pieces and cuts each (width x 2 x 2); B's untouched."""
        g, lp = self.splitPattern()
        self.makePieces(lp)
        sk = studioSketch(self.doc, self.S, "LongSk", rects=((-5, 9, 65, 11),), z=10)
        long = makeOwner(self.doc, self.S, "Pocket", "Long", sk, ("A",), Length=2, Refine=True)
        self.doc.recompute()
        self.assertValid(long)
        steps = [
            b for b in PartDesign.studioLiveParts(self.list)
            if PartDesign.studioStepOf(long, b) is not None
        ]
        self.assertEqual(len(steps), 4)
        self.assertParts(
            (400 - 2 * 4, 2800 - 14 * 4, 2800 - 14 * 4, 2400 - 12 * 4) + (400, 2800, 2800, 2400)
        )

    # ------------------------------------------------------------------------------- oracle 9j (d)
    def testEveryOriginalSuppressedIsAnError(self):
        """Onshape (oracle 9j, answer d): a feature pattern whose only original is suppressed
        fails in Onshape's words; its copies are gone with the seed."""
        self.twoPlates()
        g = self.groove()
        lp = linearOwner(self.doc, self.S, "LP", [g], 40, 3)
        self.assertValid(lp)
        g.Suppressed = True
        self.doc.recompute()
        self.assertRefused(lp, "Selected features do not create any geometry that may be patterned.")
        self.assertVolume("A", PLATE)
        self.assertVolume("B", PLATE)
        g.Suppressed = False
        self.doc.recompute()
        self.assertValid(lp)
        self.assertVolume("A", PLATE - 3 * 600)

    def testDeletedOriginalTurnsTheOwnerRed(self):
        """Acceptance 9 (H1 R2): the only original deleted: the owner is red in Onshape's words,
        and the part shows without the pattern."""
        self.twoPlates()
        h = self.hole("A", 7.5, 10, "Hole")
        lp = linearOwner(self.doc, self.S, "LP", [h], 40, 3)
        self.assertVolume("A", PLATE - 3 * HOLE * 5)
        self.doc.openTransaction("delete")
        PartDesign.studioRemove(h)
        self.doc.removeObject(h.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertRefused(lp, "Select features to pattern")
        self.assertVolume("A", PLATE)

    def testTopAsDirection(self):
        """Acceptance 10 (App half): the studio's Top plane as direction (its normal, +z): a boss
        5 high patterned up 5 x 2 stacks a second boss on the first."""
        self.twoPlates()
        b = self.boss("A", (5, 5, 10, 10), "Boss")
        lp = linearOwner(self.doc, self.S, "LP", [b], 5, 2, direction=origin(self.S, XY_PLANE))
        self.assertValid(lp)
        self.assertVolume("A", PLATE + 2 * 125)
        self.assertTrue(self.part("A").Tip.Shape.isInside(V(7.5, 7.5, 17.5), 1e-6, True))

    def testAnEdgeOfAnotherPartAsDirection(self):
        """Acceptance 10 and settled 4: an edge of B (along x) directs a pattern of a hole in A."""
        self.twoPlates()
        h = self.hole("A", 7.5, 10, "Hole")
        bpad = self.doc.getObject("BPad")
        edge = next(
            f"Edge{i}"
            for i, e in enumerate(bpad.Shape.Edges, 1)
            if abs(e.Vertexes[0].Point.y - e.Vertexes[1].Point.y) < 1e-9
            and abs(e.Vertexes[0].Point.z - e.Vertexes[1].Point.z) < 1e-9
        )
        lp = linearOwner(self.doc, self.S, "LP", [h], 40, 3, direction=(bpad, [edge]))
        self.assertValid(lp)
        self.assertVolume("A", PLATE - 3 * HOLE * 5)
        for x in (7.5, 27.5, 47.5):
            self.assertFalse(self.part("A").Tip.Shape.isInside(V(x, 10, 8), 1e-6, True), x)

    def testPlacedStudioAndPlacedPart(self):
        """Settled 4: the studio turned 90 degrees about z and moved, B placed 30 along y in it;
        the hole on B patterned along A's own x axis (a reference on another part): each instance
        lands along the studio's x, in B's frame at x 7.5, 27.5, 47.5."""
        self.studio((("A", (0, 0, 60, 20), 10), ("B", (0, 0, 60, 20), 10)))
        self.part("B").Placement = App.Placement(V(0, 30, 0), App.Rotation())
        self.S.Placement = App.Placement(V(100, 50, 0), App.Rotation(V(0, 0, 1), 90))
        self.doc.recompute()
        h = self.hole("B", 7.5, 40, "Hole")
        direction = (self.part("A").Origin.OriginFeatures[X_AXIS], [""])
        lp = linearOwner(self.doc, self.S, "LP", [h], 40, 3, direction=direction)
        self.assertValid(lp)
        self.assertVolume("B", PLATE - 3 * HOLE * 5)
        tip = self.part("B").Tip.Shape
        for x in (7.5, 27.5, 47.5):
            self.assertFalse(tip.isInside(V(x, 10, 8), 1e-6, True), x)

    def testUndoRedoAndSaveReopen(self):
        """Acceptance 11: made in a transaction, the owner and its steps go with undo and come
        back with redo; saved and opened again, the same volumes and element names."""
        self.twoPlates()
        g = self.groove()
        self.doc.recompute()
        self.doc.openTransaction("pattern")
        linearOwner(self.doc, self.S, "LP", [g], 40, 3)
        self.doc.commitTransaction()
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("LP"))
        self.assertIsNone(self.doc.getObject("LP_at_A"))
        self.assertVolume("A", PLATE - 6 * 20 * 5)
        self.doc.redo()
        self.doc.recompute()
        lp = self.doc.getObject("LP")
        self.assertValid(lp)
        self.assertVolume("B", PLATE - 3 * 6 * 20 * 5)
        before = {p: elementNames(self.part(p).Tip.Shape) for p in ("A", "B")}
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "pattern.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.docs.append(self.doc.Name)
        self.doc.recompute()
        self.assertValid(self.doc.getObject("LP"))
        for p in ("A", "B"):
            self.assertVolume(p, PLATE - 3 * 6 * 20 * 5)
            self.assertEqual(elementNames(self.part(p).Tip.Shape), before[p], p)

    # ------------------------------------------------------------------------------- settled 1
    def testAStepWhoseOriginalsDifferFailsLoudly(self):
        """Settled 1: a step's Originals edited away from the owner's: the step fails loudly
        (mustExecute runs it); reconcile writes them back."""
        self.twoPlates()
        g = self.groove()
        lp = linearOwner(self.doc, self.S, "LP", [g], 40, 3)
        s = self.step(lp, "A")
        s.Originals = [self.doc.getObject("APad")]
        self.doc.recompute()
        self.assertRefused(s, "differ")
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        self.assertValid(s)
        self.assertVolume("A", PLATE - 3 * 6 * 20 * 5)

    def testOwnerParametersReachTheSteps(self):
        """The steps read the owner's count when they run: 3 -> 2 changes both parts."""
        self.twoPlates()
        g = self.groove()
        lp = linearOwner(self.doc, self.S, "LP", [g], 40, 3)
        lp.Occurrences = 2
        self.doc.recompute()
        for p in ("A", "B"):
            self.assertVolume(p, PLATE - 2 * 6 * 20 * 5)

    # ------------------------------------------------------------------------------- refusals
    def testAddSeedOverTwoPartsWithReapplyOffIsRefused(self):
        """Settled 2 (Onshape Q2): an Add seed scoped {A, B}, Reapply off, refused in Onshape's
        words even though no instance bridges (Reapply on: the tests below)."""
        self.studio((("A", (0, 0, 20, 20), 10), ("B", (30, 0, 50, 20), 10)))
        b = self.boss("A", (12, 5, 18, 15), "Boss", scope=("A", "B"))
        self.doc.recompute()
        lp = linearOwner(self.doc, self.S, "LP", [b], 4, 2)
        self.assertRefused(lp, *SWITCH_WORDS)

    # ------------------------------------------------------------------------------- T1b: merges
    def gapPlates(self):
        """A x 0..20 and B x 30..50, y 0..20, z 0..10 (4000 each)."""
        return self.studio((("A", (0, 0, 20, 20), 10), ("B", (30, 0, 50, 20), 10)))

    def bridgeSeed(self):
        """An Add scoped {A, B}: a block x 20..25 against A's side, z 0..10 (1000)."""
        b = self.boss("A", (20, 0, 25, 20), "Boss", length=10, z=0, scope=("A", "B"))
        self.doc.recompute()
        self.assertVolume("A", 5000)
        return b

    def testAddSeedOverTwoPartsWithNothingBridgingMergesNothing(self):
        """Settled 2 with Reapply on (moved from T1a's "not yet"): the boss's instance joins A
        only: A 4000 + 10 x 10 x 5, B untouched, no merge record, both parts live."""
        self.gapPlates()
        b = self.boss("A", (12, 5, 18, 15), "Boss", scope=("A", "B"))
        self.doc.recompute()
        lp = linearOwner(self.doc, self.S, "LP", [b], 4, 2, reapply=True)
        self.assertValid(lp, self.step(lp, "A"))
        self.assertVolume("A", 4500)
        self.assertVolume("B", 4000)
        self.assertEqual(list(getattr(lp, "StudioMergedParts", [])), [])
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 2)

    def testAcceptance7InstanceBridgingMergesBIntoA(self):
        """Acceptance 7 (settled 2, Q2): instance 2 (x 25..30) bridges A grown by the seed and
        B: one part with A's id, 4000 + 1000 + 1000 + 4000; the pattern's record names it, the
        list reads it (settled 8: B consumed by the pattern, no step of it in B); re-spaced
        (instance 2 inside B) B comes back; with Reapply off: refused in Onshape's words."""
        self.gapPlates()
        b = self.bridgeSeed()
        lp = linearOwner(self.doc, self.S, "LP", [b], 5, 2, reapply=True)
        self.assertValid(lp, self.step(lp, "A"))
        self.assertEqual(list(lp.StudioMergedParts), ["B -> A"])
        live = PartDesign.studioLiveParts(self.list)
        self.assertEqual([p.StudioPartId for p in live], ["A"])
        self.assertIs(PartDesign.studioConsumerOf(self.part("B")), lp)
        self.assertIsNone(self.step(lp, "B"))
        self.assertVolume("A", 10000)
        self.assertEqual(len(self.part("A").Tip.Shape.Solids), 1)
        lp.Length = 10
        self.doc.recompute()
        self.assertValid(lp)
        self.assertEqual(list(lp.StudioMergedParts), [])
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 2)
        self.assertIsNotNone(self.step(lp, "B"))
        self.assertVolume("A", 5000)
        self.assertVolume("B", 4000)
        lp.Length = 5
        lp.Reapply = False
        self.doc.recompute()
        self.assertRefused(lp, *SWITCH_WORDS)
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 2)

    def testAddInstanceJoiningNoPartIsANewPart(self):
        """Q7: the boss's instance over the gap (x 22..28, z 10..15) joins no part: loud until
        the command makes it a part 'LP:1' of 300; A 4300, B untouched."""
        self.gapPlates()
        b = self.boss("A", (12, 5, 18, 15), "Boss", scope=("A", "B"))
        self.doc.recompute()
        lp = linearOwner(self.doc, self.S, "LP", [b], 10, 2, reapply=True)
        self.assertRefused(lp, "press OK")
        made = self.makePieces(lp)
        self.assertEqual([m.StudioPartId for m in made], ["LP:1"])
        self.assertValid(lp)
        self.assertAlmostEqual(made[0].Shape.Volume, 300, places=3)
        self.assertVolume("A", 4300)
        self.assertVolume("B", 4000)
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 3)

    def testMergeUndoRedoAndSaveReopen(self):
        """Acceptance 11 for a merge: undo brings B back, redo merges it again; saved and
        opened again, the same part, volume and element names."""
        self.gapPlates()
        b = self.bridgeSeed()
        self.doc.openTransaction("pattern")
        linearOwner(self.doc, self.S, "LP", [b], 5, 2, reapply=True)
        self.doc.commitTransaction()
        self.assertVolume("A", 10000)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("LP"))
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 2)
        self.assertVolume("A", 5000)
        self.doc.redo()
        self.doc.recompute()
        self.assertValid(self.doc.getObject("LP"))
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 1)
        self.assertVolume("A", 10000)
        before = elementNames(self.part("A").Tip.Shape)
        self.reopen()
        self.assertValid(self.doc.getObject("LP"))
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 1)
        self.assertVolume("A", 10000)
        self.assertEqual(elementNames(self.part("A").Tip.Shape), before)

    def testMergeInstanceBridgingTwoPiecesOfASplitMergesThem(self):
        """The gate's seed 1 op 8 (T1b gate half): the seed Add x 15..35, y 0..4 merges B into A;
        a through slot x 40..41 then splits A in two (pieces made); the pattern of the seed +x 10,
        Reapply on: its instance x 25..45 bridges the slot, so the right piece merges into the left
        one (the pattern's record says so) and one part is live, 8240, its pattern step valid. The
        left piece holds no step of the seed: its pattern step has no Originals there and still
        takes its place in the chain (it was left out, "it has no solid to add to"). Undo brings
        both pieces back, redo merges them again; saved and opened again, the same."""
        self.gapPlates()
        seed = self.boss("A", (15, 0, 35, 4), "Seed", length=10, z=0, scope=("A", "B"))
        self.doc.recompute()
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 1)
        sk = studioSketch(self.doc, self.S, "SlotSk", rects=((40, -1, 41, 21),), z=10)
        slot = makeOwner(self.doc, self.S, "Pocket", "Slot", sk, ("A",), Length=11)
        self.doc.recompute()
        pieces = self.makePieces(slot)
        self.assertEqual(len(pieces), 2)
        self.assertEqual(sorted(round(p.Shape.Volume, 3) for p in pieces), [1800, 6400])

        def merged():
            lp = self.doc.getObject("LP")
            live = PartDesign.studioLiveParts(self.list)
            self.assertEqual(len(live), 1)
            self.assertValid(lp, PartDesign.studioStepOf(lp, live[0]))
            self.assertEqual(live[0].Tip, PartDesign.studioStepOf(lp, live[0]))
            self.assertAlmostEqual(live[0].Shape.Volume, 8240, places=2)
            self.assertEqual(len(lp.StudioMergedParts), 1)
            return live[0]

        self.doc.openTransaction("pattern")
        linearOwner(self.doc, self.S, "LP", [seed], 10, 2, reapply=True)
        self.doc.commitTransaction()
        self.doc.recompute()
        merged()
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("LP"))
        live = PartDesign.studioLiveParts(self.list)
        self.assertEqual(sorted(round(p.Shape.Volume, 3) for p in live), [1800, 6400])
        self.doc.redo()
        self.doc.recompute()
        before = elementNames(merged().Tip.Shape)
        self.reopen()
        self.assertEqual(elementNames(merged().Tip.Shape), before)

    def reopen(self):
        self.dir = self.dir or tempfile.mkdtemp()
        path = os.path.join(self.dir, "pattern.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.docs.append(self.doc.Name)
        self.list = studioList(self.doc)
        self.doc.recompute()

    # ------------------------------------------------------------------------------- T1b: New
    def newSeed(self, rect=(0, 30, 10, 40)):
        """Plate A, and N: a New Pad 10 x 10 x 5 (500) on rect, its own part 'N:1'."""
        self.studio((("A", (0, 0, 60, 20), 10),))
        sk = studioSketch(self.doc, self.S, "NSk", rects=(rect,), z=0)
        n = makeOwner(self.doc, self.S, "Pad", "N", sk, (), Length=5)
        self.doc.openTransaction("new part")
        PartDesign.studioNewPart(n)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertValid(n)
        return n

    def madeBy(self, owner):
        bodies = [b for b in self.doc.Objects if b.TypeId == "PartDesign::Body"]
        return sorted((b for b in bodies if b.StudioMadeBy == owner), key=lambda b: b.StudioPartId)

    def makePieces(self, owner):
        self.doc.openTransaction("pieces")
        made = PartDesign.studioMakePieces(owner)
        self.doc.commitTransaction()
        self.doc.recompute()
        return made

    def testAcceptance6NewSeedMakesAPartPerInstance(self):
        """Acceptance 6 (O6, settled 3): the New seed patterned +x 20 x 3: loud until the
        command, then two new parts 'LP:1', 'LP:2' of 500 at x 20..30 and 40..50; N's part and A
        untouched, no step of the pattern in them; the same with Reapply on. Count 3 -> 4 adds a
        part, 4 -> 2 deletes the Bodies left empty."""
        n = self.newSeed()
        lp = linearOwner(self.doc, self.S, "LP", [n], 40, 3)
        self.assertRefused(lp, "press OK")
        made = self.makePieces(lp)
        self.assertEqual(sorted(m.StudioPartId for m in made), ["LP:1", "LP:2"])
        self.assertValid(lp)
        nPart = self.madeBy(n)[0]
        for reapply in (False, True):
            with self.subTest(reapply=reapply):
                lp.Reapply = reapply
                self.doc.recompute()
                self.assertValid(lp)
                parts = self.madeBy(lp)
                self.assertEqual(len(parts), 2)
                centres = sorted(b.Shape.BoundBox.Center.x for b in parts)
                for body in parts:
                    self.assertAlmostEqual(body.Shape.Volume, 500, places=3)
                self.assertAlmostEqual(centres[0], 25, places=6)
                self.assertAlmostEqual(centres[1], 45, places=6)
                self.assertAlmostEqual(nPart.Shape.Volume, 500, places=3)
                self.assertVolume("A", PLATE)
                self.assertIsNone(self.step(lp, "A"))
                self.assertIsNone(PartDesign.studioStepOf(lp, nPart))
        lp.Occurrences = 4
        lp.Length = 60
        self.doc.recompute()
        self.assertRefused(lp, "press OK")
        self.assertEqual(len(self.makePieces(lp)), 1)
        self.assertEqual(len(self.madeBy(lp)), 3)
        lp.Occurrences = 2
        lp.Length = 20
        self.doc.recompute()
        self.makePieces(lp)
        self.assertValid(lp)
        self.assertEqual(len(self.madeBy(lp)), 1)
        self.assertAlmostEqual(self.madeBy(lp)[0].Shape.BoundBox.Center.x, 25, places=6)
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 3)

    def testNewInstanceOverlappingTheSeedStaysAPartOfItsOwn(self):
        """Settled 3 (Onshape Q1): an instance overlapping the seed's part (+x 5) is a part of
        its own; N's part stays 500."""
        n = self.newSeed()
        lp = linearOwner(self.doc, self.S, "LP", [n], 5, 2)
        self.makePieces(lp)
        self.assertValid(lp)
        parts = self.madeBy(lp)
        self.assertEqual(len(parts), 1)
        self.assertAlmostEqual(parts[0].Shape.Volume, 500, places=3)
        self.assertAlmostEqual(self.madeBy(n)[0].Shape.Volume, 500, places=3)

    def testNewUndoRedoAndSaveReopen(self):
        """Acceptance 11 for a New seed: the command's parts go with undo and come back with
        redo; saved and opened again, the same parts and element names."""
        n = self.newSeed()
        lp = linearOwner(self.doc, self.S, "LP", [n], 40, 3)
        self.makePieces(lp)
        self.assertEqual(len(self.madeBy(lp)), 2)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(len(self.madeBy(lp)), 0)
        self.assertRefused(lp, "press OK")
        self.doc.redo()
        self.doc.recompute()
        self.assertValid(lp)
        before = {b.StudioPartId: elementNames(b.Shape) for b in self.madeBy(lp)}
        self.assertEqual(sorted(before), ["LP:1", "LP:2"])
        self.reopen()
        lp = self.doc.getObject("LP")
        self.assertValid(lp)
        after = {b.StudioPartId: elementNames(b.Shape) for b in self.madeBy(lp)}
        self.assertEqual(after, before)

    def testOriginalWhosePartWasAbsorbedIsRefused(self):
        """T1.9 (Onshape Q8): a hole on B, then B fused into A by a Union, then the pattern of
        the hole: refused loudly, naming the absorbed part."""
        self.studio((("A", (0, 0, 20, 20), 10), ("B", (20, 0, 50, 20), 10)))
        h = self.hole("B", 40, 10, "Hole")
        u = booleanOwner(self.doc, self.S, "U", "Fuse", targets=("A",), tools=("B",))
        PartDesign.studioInsert(u, -1)
        self.doc.recompute()
        lp = linearOwner(self.doc, self.S, "LP", [h], 4, 2)
        self.assertRefused(lp, "Hole", "B")

    def testInBodyPatternOfAnOwnerOnTwoPartsSaysMakeItAgain(self):
        """T1.5: an in-Body pattern (made by an old command) of an owner on two parts stays refused,
        and its refusal tells to make the pattern again."""
        self.twoPlates()
        g = self.groove()
        lp = linear(self.part("A"), "LP", [g], Y_AXIS, 1, 2)
        self.doc.recompute()
        self.assertRefused(lp, "make the pattern again")

    # ------------------------------------------------------------------------------- one part (T1.5)
    def testPolarOfABossOnADiscWithReapply(self):
        """TEST DOC's circular pattern (Reapply on): four 4 x 4 x 5 bosses on a disc r20 x 10."""
        self.studio((("R", 20, 10),))
        b = self.boss("R", (12, -2, 16, 2), "Boss")
        pp = ownerPattern(
            self.doc, self.S, "PolarPattern", "PP", [b], reapply=True,
            Axis=origin(self.S, Z_AXIS), Angle=360, Occurrences=4,
        )
        self.assertValid(pp)
        self.assertVolume("R", Part.makeCylinder(20, 10).Volume + 4 * 80)
        for x, y in ((14, 0), (0, 14), (-14, 0), (0, -14)):
            self.assertTrue(self.part("R").Tip.Shape.isInside(V(x, y, 12), 1e-6, True), (x, y))

    def mirrorPlate(self):
        self.studio((("P", (-30, -30, 30, 30), 5),))
        return self.boss("P", (2, 2, 8, 8), "Boss", length=5, z=5)

    def testMirrorOfABoss(self):
        """TEST DOC's feature mirror: the boss mirrored about the studio's YZ plane."""
        b = self.mirrorPlate()
        m = ownerPattern(self.doc, self.S, "Mirrored", "M", [b], reapply=True,
                         MirrorPlane=origin(self.S, YZ_PLANE))
        self.assertValid(m)
        self.assertVolume("P", 60 * 60 * 5 + 2 * 180)
        self.assertTrue(self.part("P").Tip.Shape.isInside(V(-5, 5, 7.5), 1e-6, True))

    def testMirrorOfAMirrorBringsItsInstanceOnly(self):
        """TEST DOC's mirror of a mirror (P2/P3, T7a): an owner mirror of the owner mirror M1
        about XZ adds M1's instance only, mirrored: (-5, -5)."""
        b = self.mirrorPlate()
        m1 = ownerPattern(self.doc, self.S, "Mirrored", "M1", [b],
                          MirrorPlane=origin(self.S, YZ_PLANE))
        m2 = ownerPattern(self.doc, self.S, "Mirrored", "M2", [m1],
                          MirrorPlane=origin(self.S, XZ_PLANE))
        self.assertValid(m1, m2)
        self.assertEqual(list(self.step(m2, "P").Originals), [self.step(m1, "P")])
        self.assertVolume("P", 60 * 60 * 5 + 3 * 180)
        tip = self.part("P").Tip.Shape
        for (x, y), there in (((5, 5), True), ((-5, 5), True), ((-5, -5), True), ((5, -5), False)):
            self.assertEqual(tip.isInside(V(x, y, 7.5), 1e-6, True), there, (x, y))

    def testChamferAmongTheOriginals(self):
        """TEST DOC's chamfer among the originals: a boss with its top edges chamfered 1 (a Body
        member), patterned with the chamfer +x 20 x 3 by an owner."""
        self.studio((("P", (0, 0, 60, 20), 5),))
        b = self.boss("P", (2, 7, 8, 13), "Boss", length=5, z=5)
        self.doc.recompute()
        p = self.part("P")
        s = PartDesign.studioStepOf(b, p)
        edges = [
            f"Edge{i}"
            for i, e in enumerate(s.Shape.Edges, 1)
            if all(abs(v.Point.z - 10) < 1e-6 for v in e.Vertexes)
        ]
        chamfer = p.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (s, edges)
        chamfer.Size = 1
        PartDesign.studioInsert(chamfer, -1)
        self.doc.recompute()
        lp = linearOwner(self.doc, self.S, "LP", [b, chamfer], 40, 3, reapply=True)
        self.assertValid(chamfer, lp)
        solid = box(2, 7, 5, 8, 13, 10)
        top = [e for e in solid.Edges if all(abs(v.Point.z - 10) < 1e-6 for v in e.Vertexes)]
        self.assertVolume("P", 60 * 20 * 5 + 3 * solid.makeChamfer(1, top).Volume)


if __name__ == "__main__":
    unittest.main()
