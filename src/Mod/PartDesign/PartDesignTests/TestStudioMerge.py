# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (10.13): an Add merges the parts its tool joins
#
# notes/parts-design.md 10.13 (its skeptic's eight points included), notes/onshape-facts.md O9,
# O9b-e, Q1b/Q1d, Q2c, F2, F3, H1a and oracle 9's M1-M4. An Add owner E with a resolved scope
# computes the contact graph tool solid <-> scope part at its place (edges only tool to part, M1;
# contact = their fuse has fewer solids than its inputs: face contact, never an edge or a vertex,
# M2). Each component holding a scope part becomes one part: the survivor is its first listed scope
# part, the others are absorbed from E's place on (StudioMergedParts on E, decided at compute, taken
# by the projection after the recompute). Tool solids in no component are P6p's leftovers (H1a).
#
# Designed geometry only: TestStudioList's three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50),
# y 0..10, z 0..10. The bar: a Pad owner on a studio sketch at z 5, 10 long (z 5..15), y 2..8;
# x 5..25 bridges A and B: A + B + the bar = 2000 + 1200 - 2 * 150 = 2900. Expected values come
# from the boxes themselves.

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestStudioList import (
    insertPattern,
    makePattern,
    newStudio,
    studioList,
)
from PartDesignTests.TestStudioOwner import makeOwner, studioSketch

V = App.Vector
BRIDGE = (5, 2, 25, 8)  # over A (x 5..10) and B (x 20..25)
ON_A = (-5, 2, 15, 8)  # the bridge moved 10 to -x: A only
CUT = (5, 2, 25, 8)


def box(x0, y0, z0, x1, y1, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def partBox(x):
    return box(x, 0, 0, x + 10, 10, 10)


def merges(owner):
    """owner's merge record (StudioMergedParts; none until it merges once)."""
    return list(getattr(owner, "StudioMergedParts", []))


class TestStudioMerge(unittest.TestCase):
    def setUp(self):
        self.doc, self.S = newStudio("TestStudioMerge")
        self.list = studioList(self.doc)
        self.doc.recompute()
        self.dir = None

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestStudioMerge"):
                App.closeDocument(doc.Name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def body(self, name):
        return self.doc.getObject(name)

    def bar(self, name="E", scope=("A", "B"), rect=BRIDGE, z=5, length=10, mergeAll=False, **values):
        sk = studioSketch(self.doc, self.S, name + "Sk", (rect,), z=z)
        owner = makeOwner(self.doc, self.S, "Pad", name, sk, scope, Length=length, Refine=False, **values)
        if mergeAll:
            PartDesign.studioSetMergeAll(owner, True)
        self.doc.recompute()
        return owner

    def pocket(self, name, rect, scope, depth=2, z=10, mergeAll=False):
        sk = studioSketch(self.doc, self.S, name + "Sk", (rect,), z=z)
        owner = makeOwner(self.doc, self.S, "Pocket", name, sk, scope, Length=depth, Refine=False)
        if mergeAll:
            PartDesign.studioSetMergeAll(owner, True)
        self.doc.recompute()
        return owner

    def live(self):
        return [b.Name for b in PartDesign.studioLiveParts(self.list)]

    def step(self, owner, part):
        return PartDesign.studioStepOf(owner, self.body(part))

    def assertValid(self, *objs):
        for o in objs:
            self.assertTrue(o.isValid(), f"{o.Name}: {o.getStatusString()}")

    def assertVolume(self, part, expected):
        self.assertAlmostEqual(self.body(part).Shape.Volume, expected, places=3, msg=part)

    def assertOneSolid(self, part):
        self.assertEqual(len(self.body(part).Shape.Solids), 1, part)

    def assertMerged(self, owner, survivor, absorbed, volume):
        """absorbed (a list) merged into survivor by owner: one solid of volume, the others not
        live after owner, hidden, with no step of owner, and owner their consumer."""
        self.assertValid(owner, self.step(owner, survivor))
        self.assertVolume(survivor, volume)
        self.assertOneSolid(survivor)
        self.assertEqual(
            sorted(merges(owner)), sorted(f"{p} -> {survivor}" for p in absorbed)
        )
        for p in absorbed:
            self.assertNotIn(p, self.live())
            self.assertIsNone(self.step(owner, p), p)
            self.assertFalse(self.body(p).Visibility, p)
            self.assertIs(PartDesign.studioConsumerOf(self.body(p)), owner)
        self.assertIn(survivor, self.live())

    def moveSketch(self, owner, dx):
        self.doc.openTransaction("move")
        sk = owner.Profile[0]
        sk.Placement = App.Placement(sk.Placement.Base + V(dx, 0, 0), App.Rotation())
        self.doc.recompute()
        self.doc.commitTransaction()
        self.doc.recompute()

    def bridged(self):
        return partBox(0).fuse([partBox(20), box(5, 2, 5, 25, 8, 15)]).Volume

    # ------------------------------------------------------------------------------- O9
    def testO9AddJoiningAAndBMergesIntoA(self):
        """O9 (O9d/e): the bar joins A and B, scope A, B: one part with A's id and name (2900);
        B is no part after E (not live, hidden, no step of E), C untouched and live."""
        self.body("A").Label = "Ay"
        self.body("B").Label = "Bee"
        e = self.bar()
        self.assertAlmostEqual(self.bridged(), 2900, places=6)
        self.assertMerged(e, "A", ["B"], 2900)
        self.assertVolume("C", 1000)
        self.assertEqual(self.live(), ["A", "C"])
        self.assertEqual(self.body("A").Label, "Ay")
        self.assertEqual(self.body("A").StudioPartId, "A")
        # Before E (the bar above it) both are parts again, B with its own shape
        PartDesign.studioSetBar(self.list, list(self.list.Entries).index(e))
        self.doc.recompute()
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertVolume("B", 1000)
        self.assertTrue(self.body("B").Visibility)

    def testO9bScopeListedBAKeepsB(self):
        """O9b: scope listed B, A: B survives (the first listed), A is absorbed."""
        e = self.bar(scope=("B", "A"))
        self.assertMerged(e, "B", ["A"], 2900)
        self.assertEqual(self.live(), ["B", "C"])

    def testO9cScopeBOnlyLeavesAUntouched(self):
        """O9c: scope B only, the bar still overlapping A: B + bar (1000 + 900), A untouched, live."""
        e = self.bar(scope=("B",))
        self.assertValid(e, self.step(e, "B"))
        self.assertVolume("B", partBox(20).fuse(box(5, 2, 5, 25, 8, 15)).Volume)
        self.assertVolume("A", 1000)
        self.assertEqual(merges(e), [])
        self.assertEqual(self.live(), ["A", "B", "C"])

    def testTwoRegionsOnTwoPartsStayTwo(self):
        """M4: one sketch with a region on A's top and one on B's, scope A, B: two parts, each
        grown (1108), nothing merged."""
        sk = studioSketch(self.doc, self.S, "ESk", ((2, 2, 8, 8), (22, 2, 28, 8)), z=10)
        e = makeOwner(self.doc, self.S, "Pad", "E", sk, ("A", "B"), Length=3, Refine=False)
        self.doc.recompute()
        self.assertValid(e, self.step(e, "A"), self.step(e, "B"))
        self.assertVolume("A", 1108)
        self.assertVolume("B", 1108)
        self.assertEqual(merges(e), [])
        self.assertEqual(self.live(), ["A", "B", "C"])

    def testM1PartsTouchingEachOtherAreNotJoined(self):
        """M1a/M1b: A and B already in face contact (B at x 10..20), a boss on A's top only, scope
        A, B and Merge with all alike: B stays its own part (1000), only A grows (1180)."""
        App.closeDocument(self.doc.Name)
        self.doc, self.S = newStudio("TestStudioMergeM1", parts=(("A", 0), ("B", 10), ("C", 40)))
        self.list = studioList(self.doc)
        self.doc.recompute()
        for mergeAll in (False, True):
            e = self.bar("E", scope=() if mergeAll else ("A", "B"), rect=(2, 2, 8, 8), z=10,
                         length=5, mergeAll=mergeAll)
            self.assertValid(e, self.step(e, "A"))
            self.assertVolume("A", 1180)
            self.assertVolume("B", 1000)
            self.assertEqual(merges(e), [], mergeAll)
            self.assertEqual(self.live(), ["A", "B", "C"], mergeAll)
            PartDesign.studioRemove(e)
            self.doc.removeObject("E")
            self.doc.removeObject("ESk")
            self.doc.recompute()

    def testM2EdgeOnlyContactIsNoJoin(self):
        """M2: a bar x 10..18, z 10..20 on A's top-right edge (edge contact only), scope A: A is
        unchanged and the bar is a leftover (loud until the command makes it a part, 480); the
        face-contact control (x 5..13) joins A (1000 + 480)."""
        e = self.bar(scope=("A",), rect=(10, 2, 18, 8), z=10, length=10)
        self.assertFalse(e.isValid())
        self.assertIn("touches no part of the merge scope", e.getStatusString())
        self.assertVolume("A", 1000)
        self.doc.openTransaction("pieces")
        made = PartDesign.studioMakePieces(e)
        self.doc.commitTransaction()
        self.assertEqual(len(made), 1)
        self.assertValid(e)
        self.assertAlmostEqual(made[0].Shape.Volume, 480, places=3)
        self.assertVolume("A", 1000)
        control = self.bar("F", scope=("A",), rect=(5, 2, 13, 8), z=10, length=10)
        self.assertValid(control, self.step(control, "A"))
        self.assertVolume("A", 1480)

    def testEdgeContactBetweenTwoScopePartsDoesNotMerge(self):
        """Skeptic 3: a bar touching A on a face and B only along an edge (B at z 10..20 above the
        bar's end) joins A only: B stays a part."""
        App.closeDocument(self.doc.Name)
        self.doc = App.newDocument("TestStudioMergeEdge")
        self.doc.UndoMode = 1
        self.S = self.doc.addObject("App::Part", "S")
        for name, r, z0 in (("A", (0, 0, 10, 10), 0), ("B", (25, 0, 35, 10), 10)):
            body = self.doc.addObject("PartDesign::Body", name)
            self.S.addObject(body)
            pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), r, z=z0), 10)
        self.doc.recompute()
        self.list = studioList(self.doc)
        self.doc.recompute()
        # The bar z 0..10, x 5..25: B's bottom edge at x 25, z 10 meets the bar's top edge
        e = self.bar(scope=("A", "B"), rect=(5, 2, 25, 8), z=0, length=10)
        self.assertValid(e, self.step(e, "A"), self.step(e, "B"))
        self.assertEqual(merges(e), [])
        self.assertVolume("A", partBox(0).fuse(box(5, 2, 0, 25, 8, 10)).Volume)
        self.assertVolume("B", 1000)
        self.assertEqual(self.live(), ["A", "B"])

    # ------------------------------------------------------------------------------- Merge with all
    def testQ1bMergeWithAllAddMakesOnePart(self):
        """Q1b: Merge with all, no part ticked: the scope is every live part at E's place; the bar
        joins A and B (A first: its first feature is first in the history); C, untouched, stays."""
        e = self.bar(scope=(), mergeAll=True)
        self.assertTrue(e.StudioMergeAll)
        self.assertEqual([b.Name for b in PartDesign.studioScopeOf(e)], ["A", "B", "C"])
        self.assertMerged(e, "A", ["B"], 2900)
        self.assertVolume("C", 1000)
        self.assertValid(self.step(e, "C"))  # a no-op Union in an untouched part (skeptic 8)
        self.assertEqual(self.live(), ["A", "C"])

    def testQ1dMergeWithAllRemoveCutsBoth(self):
        """Q1d: Merge with all on a Remove over A and B: both cut (1000 - 5*6*3 each), still parts."""
        f = self.pocket("F", CUT, (), depth=3, mergeAll=True)
        self.assertValid(f, self.step(f, "A"), self.step(f, "B"))
        self.assertVolume("A", 910)
        self.assertVolume("B", 910)
        self.assertEqual(self.live(), ["A", "B", "C"])

    def testM3MergeWithAllOrdersByTheFirstFeature(self):
        """M3: B's sketch and Pad moved first in the history: with Merge with all, B survives."""
        PartDesign.studioMove(self.doc.getObject("BSk"), 0)
        PartDesign.studioMove(self.doc.getObject("BPad"), 1)
        self.doc.recompute()
        e = self.bar(scope=(), mergeAll=True)
        self.assertEqual([b.Name for b in PartDesign.studioScopeOf(e)], ["B", "A", "C"])
        self.assertMerged(e, "B", ["A"], 2900)

    # ------------------------------------------------------------------------------- edits
    def testSeparateAndRejoinWithLaterFeatures(self):
        """Q2c's round trip, F2, F3: E on A only first, G (a Remove scoped to B) and H (scoped to
        B and A) after it. E moved to join B: B is merged into A; G fails loudly (F3: B was merged
        into A by E), H cuts A alone (F2). Moved back: B is a part again, with its id, name and
        both later features. Undo and redo of each move."""
        e = self.bar(rect=ON_A)
        g = self.pocket("G", (22, 2, 28, 8), ("B",), depth=2)
        h = self.pocket("H", (24, 8.5, 27, 9.5), ("B", "A"), depth=1)  # beside G: 3 in B
        onA = partBox(0).fuse(box(-5, 2, 5, 15, 8, 15)).Volume
        b = 1000 - 72 - 3
        self.assertValid(e, g, h, self.step(g, "B"), self.step(h, "B"))
        self.assertVolume("A", onA)
        self.assertVolume("B", b)
        self.assertEqual(self.live(), ["A", "B", "C"])

        self.moveSketch(e, 10)  # joins B
        self.assertMerged(e, "A", ["B"], 2900 - 3)  # H cuts A (where B's material is now)
        self.assertFalse(g.isValid())
        self.assertIn("'B' was merged into 'A' by 'E'", g.getStatusString())
        self.assertValid(h, self.step(h, "A"))
        self.assertIsNone(self.step(h, "B"))
        self.assertIsNone(self.step(g, "B"))
        self.assertVolume("B", 1000)  # its chain ends before E

        self.moveSketch(e, -10)  # separated again
        self.assertEqual(merges(e), [])
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertValid(e, g, h, self.step(g, "B"), self.step(h, "B"))
        self.assertTrue(self.body("B").Visibility)
        self.assertEqual(self.body("B").Label, "B")
        self.assertVolume("A", onA)
        self.assertVolume("B", b)

        self.doc.undo()  # joined again
        self.doc.recompute()
        self.assertMerged(e, "A", ["B"], 2900 - 3)
        self.assertFalse(g.isValid())
        self.doc.undo()  # separated
        self.doc.recompute()
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertVolume("B", b)
        self.assertValid(g, h)
        self.doc.redo()
        self.doc.recompute()
        self.assertMerged(e, "A", ["B"], 2900 - 3)
        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertVolume("B", b)

    def testScopeEditJoinsAndUnjoins(self):
        """The bar over A and B, scope A: B is out of the scope, never absorbed (it overlaps).
        B ticked: absorbed; unticked again: a part again."""
        e = self.bar(scope=("A",))
        self.assertEqual(merges(e), [])
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertVolume("B", 1000)
        self.doc.openTransaction("scope")
        PartDesign.studioSetScopeIds(e, ["A", "B"])
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertMerged(e, "A", ["B"], 2900)
        self.doc.openTransaction("scope")
        PartDesign.studioSetScopeIds(e, ["A"])
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertEqual(merges(e), [])
        self.assertVolume("B", 1000)

    def testSuppressedOrDeletedMergesNothing(self):
        """Suppress E: nothing absorbed, B a part; unsuppress: merged again; delete E: B a part,
        undo of the delete: merged again."""
        e = self.bar()
        self.assertMerged(e, "A", ["B"], 2900)
        PartDesign.studioSuppress(e, True)
        self.doc.recompute()
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertVolume("A", 1000)
        self.assertTrue(self.body("B").Visibility)
        PartDesign.studioSuppress(e, False)
        self.doc.recompute()
        self.assertMerged(e, "A", ["B"], 2900)
        self.doc.openTransaction("delete")
        PartDesign.studioRemove(e)
        self.doc.removeObject("E")
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertVolume("A", 1000)
        self.assertVolume("B", 1000)
        self.doc.undo()
        self.doc.recompute()
        self.assertMerged(self.doc.getObject("E"), "A", ["B"], 2900)

    def testSaveAndReopenKeepsTheMerge(self):
        """The record is stored on E: the reopened document's recompute agrees, and an edit after
        the reopen still separates."""
        e = self.bar()
        self.dir = tempfile.mkdtemp(prefix="studiomerge")
        path = os.path.join(self.dir, "TestStudioMergeSaved.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.doc.UndoMode = 1
        self.list = studioList(self.doc)
        e = self.doc.getObject("E")
        self.assertMerged(e, "A", ["B"], 2900)
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        self.assertMerged(e, "A", ["B"], 2900)
        self.moveSketch(e, -10)
        self.assertEqual(self.live(), ["A", "B", "C"])
        self.assertVolume("B", 1000)

    def testAPartOfAPieceStaysAPartOfItsComponent(self):
        """Two bars in one sketch, one joining A and B, one on C alone, scope A, B, C: A absorbs
        B, C grows on its own (two components, two parts)."""
        sk = studioSketch(self.doc, self.S, "ESk", (BRIDGE, (42, 2, 48, 8)), z=5)
        e = makeOwner(self.doc, self.S, "Pad", "E", sk, ("C", "A", "B"), Length=10, Refine=False)
        self.doc.recompute()
        self.assertMerged(e, "A", ["B"], 2900)
        self.assertValid(self.step(e, "C"))
        self.assertVolume("C", partBox(40).fuse(box(42, 2, 5, 48, 8, 15)).Volume)

    # ------------------------------------------------------------------------------- loud cases
    def testALaterBodyMemberOfTheAbsorbedPartIsLoud(self):
        """A feature in B's Body after E (a later pick on B's geometry, P8a's debt): with B
        merged it has no part to act on. Inserting it after E is refused; E made to join B while
        it is there fails E's step in A loudly, naming it: never a silent follow."""
        e = self.bar()
        b = self.body("B")
        boss = pad(b, "BBoss", sketch(b, "BBossSk", xyPlane(b), (22, 2, 28, 8), z=10), 2)
        with self.assertRaises(Exception) as caught:
            PartDesign.studioInsert(boss.Profile[0], -1)
            PartDesign.studioInsert(boss, -1)
        self.assertIn("merged", str(caught.exception))
        # The other way: B's later feature first, then E joins B
        App.closeDocument(self.doc.Name)
        self.setUp()
        e = self.bar(rect=ON_A)
        b = self.body("B")
        bossSk = sketch(b, "BBossSk", xyPlane(b), (22, 2, 28, 8), z=10)
        boss = pad(b, "BBoss", bossSk, 2)
        PartDesign.studioReconcile(self.list)
        # reconcile adopts both at the end of the list, after E
        self.doc.recompute()
        self.assertGreater(list(self.list.Entries).index(boss), list(self.list.Entries).index(e))
        self.assertVolume("B", 1072)
        self.moveSketch(e, 10)
        self.assertFalse(self.step(e, "A").isValid())
        self.assertIn("BBoss", self.step(e, "A").getStatusString())

    def testAPatternOfAMergingAddIsLoud(self):
        """A pattern (T1/T2's) whose seed merges parts fails loudly."""
        e = self.bar()
        pat = makePattern(self.doc, "Pat", "Linear", "A", ["E"], 2, 2)
        insertPattern(pat, "A", -1)
        self.doc.recompute()
        self.assertFalse(pat.isValid())
        self.assertIn("merges", pat.getStatusString())


if __name__ == "__main__":
    unittest.main()
