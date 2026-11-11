# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 P8a (10.14): one fillet or chamfer over several parts
#
# notes/parts-design.md 10.14 (its skeptic's seven points included), notes/onshape-facts.md O2,
# Q2c and oracle 9's P1/P2. In a listed studio a Fillet or a Chamfer is an owner outside every
# Body: it holds the parameters and the picks (StudioPickIds, "<part id>|<expanded name>"), and each
# part its picks resolve to at its place gets one step of its own type, reading the owner's values
# when it runs. A part whose step fails is left unchanged and the owner warns (O2); none rounded,
# the owner fails. A pick follows its part into a merge (Q2c) and into the piece of a split that
# holds it; a pick found nowhere warns (ops#127: louder than Onshape, never different).
#
# Designed geometry only: TestStudioList's three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50),
# y 0..10, z 0..10. A fillet r on an edge of length L removes r^2 (1 - pi/4) L; a chamfer s,
# s^2 L / 2. Expected values come from the boxes themselves.

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests.TestStudio import pad, rect, sketch, xyPlane
from PartDesignTests.TestStudioList import booleanOwner, newStudio, studioList
from PartDesignTests.TestStudioOwner import makeOwner, studioSketch

V = App.Vector


def rounded(r, length=10):
    """The material a fillet r takes off a right-angled edge of length."""
    return r * r * (1 - math.pi / 4) * length


def edgeAt(shape, point):
    """The name of shape's edge whose centre of mass is point."""
    for i, edge in enumerate(shape.Edges, 1):
        if (edge.CenterOfMass - point).Length < 1e-6:
            return "Edge%d" % i
    raise AssertionError("no edge at %s" % point)


def pickAt(obj, point):
    """The pick of obj's edge at point, as the owner stores it."""
    return PartDesign.studioPickId(obj, edgeAt(obj.Shape, point))


def frontTop(x0, z=10):
    """The top front edge (y 0) of the box at x0."""
    return V(x0 + 5, 0, z)


def makeDressUp(doc, studio, name, picks, size, kind="Fillet", index=-1):
    """A dress-up owner of class PartDesign::<kind> on picks (studioPickId strings), listed at index
    (-1: the end), computed."""
    owner = doc.addObject("PartDesign::" + kind, name)
    studio.addObject(owner)
    if kind == "Fillet":
        owner.Radius = size
    else:
        owner.Size = size
    owner.StudioPickIds = list(picks)
    PartDesign.studioInsert(owner, index)
    doc.recompute()
    return owner


class TestStudioDressUp(unittest.TestCase):
    def setUp(self):
        self.doc, self.S = newStudio("TestStudioDressUp")
        self.list = studioList(self.doc)
        self.doc.recompute()
        self.dir = None

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestStudioDressUp"):
                App.closeDocument(doc.Name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def body(self, name):
        return self.doc.getObject(name)

    def step(self, owner, part):
        return PartDesign.studioStepOf(owner, self.body(part) if isinstance(part, str) else part)

    def assertVolume(self, part, expected):
        body = self.body(part) if isinstance(part, str) else part
        self.assertAlmostEqual(body.Shape.Volume, expected, places=3, msg=body.Name)

    def assertClean(self, owner):
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertNotIn("Warning", owner.State, owner.getStatusString())

    def filletAB(self, r=2, **kw):
        a, b = self.body("A"), self.body("B")
        return makeDressUp(
            self.doc, self.S, "F", [pickAt(a, frontTop(0)), pickAt(b, frontTop(20))], r, **kw
        )

    # ------------------------------------------------------------------------------- O2
    def testOneOwnerTwoStepsBothRounded(self):
        """O2: r 2 on one edge of A and one of B: one entry in the list, a Fillet step in A and in
        B (none in C), both rounded; the owner computes no shape and is clean."""
        f = self.filletAB()
        self.assertEqual([e.Name for e in self.list.Entries].count("F"), 1)
        for part in ("A", "B"):
            step = self.step(f, part)
            self.assertIsNotNone(step, part)
            self.assertEqual(step.TypeId, "PartDesign::Fillet")
            self.assertTrue(step.isValid(), step.getStatusString())
            self.assertAlmostEqual(step.Radius.Value, 2)
            self.assertVolume(part, 1000 - rounded(2))
        self.assertIsNone(self.step(f, "C"))
        self.assertVolume("C", 1000)
        self.assertClean(f)
        self.assertTrue(f.Shape.isNull())
        self.assertNotIn("~", "".join(f.StudioPickIds))  # expanded: no name-table ids
        self.assertEqual([p.split("|")[0] for p in f.StudioPickIds], ["A", "B"])

    def testParametersLiveFromTheOwner(self):
        """Skeptic 3: the steps read the owner's values when they run: an edit of the owner's
        Radius by Python reaches both parts."""
        f = self.filletAB()
        f.Radius = 1
        self.doc.recompute()
        for part in ("A", "B"):
            self.assertVolume(part, 1000 - rounded(1))
            self.assertAlmostEqual(self.step(f, part).Radius.Value, 1)

    def testChamferOwner(self):
        """A Chamfer owner: s 2 on A's and B's top front edge, s^2 L / 2 = 20 each."""
        a, b = self.body("A"), self.body("B")
        c = makeDressUp(
            self.doc, self.S, "K", [pickAt(a, frontTop(0)), pickAt(b, frontTop(20))], 2, "Chamfer"
        )
        self.assertEqual(self.step(c, "A").TypeId, "PartDesign::Chamfer")
        self.assertVolume("A", 980)
        self.assertVolume("B", 980)
        self.assertClean(c)

    def testAFailingPartIsLeftUnchanged(self):
        """O2 (FILLET_PARTIAL_FAIL): B only 3 high, r 4 on both top front edges: A is rounded, B
        is left unchanged (its step passes its base through, valid), the owner warns naming B."""
        self.doc.getObject("BPad").Length = 3
        self.doc.recompute()
        a, b = self.body("A"), self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(a, frontTop(0)), pickAt(b, frontTop(20, 3))], 4)
        self.assertVolume("A", 1000 - rounded(4))
        self.assertVolume("B", 300)
        self.assertTrue(f.isValid(), f.getStatusString())
        self.assertIn("Warning", f.State)
        self.assertIn("Rounds 1 of 2 parts", f.getStatusString())
        self.assertIn("'B'", f.getStatusString())
        self.assertTrue(self.step(f, "B").isValid())

    def testNoPartRoundedFails(self):
        """O2 (FILLET_FAILED): r 4 on B's 3 high edge alone: the owner fails, B is unchanged."""
        self.doc.getObject("BPad").Length = 3
        self.doc.recompute()
        b = self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(b, frontTop(20, 3))], 4)
        self.assertFalse(f.isValid())
        self.assertIn("rounds no part", f.getStatusString())
        self.assertVolume("B", 300)

    def testAPickFoundNowhereWarns(self):
        """Skeptic 4 (ops#127; Onshape ignores it silently, oracle 9 P1): a pick of A that no edge
        holds warns, and the rest is rounded."""
        a, b = self.body("A"), self.body("B")
        f = makeDressUp(
            self.doc,
            self.S,
            "F",
            [pickAt(a, frontTop(0)), "A|_;g99;_;1;SKT;0;E;0;SRC", pickAt(b, frontTop(20))],
            2,
        )
        self.assertVolume("A", 1000 - rounded(2))
        self.assertVolume("B", 1000 - rounded(2))
        self.assertIn("Warning", f.State)
        self.assertIn("not found", f.getStatusString())

    # ------------------------------------------------------------------------------- edits
    def testAnEarlierEditMovesTheEdge(self):
        """An earlier edit lengthens A to 15: its pick re-resolves (the top front edge, now at z
        15), A is 1500 less the round."""
        f = self.filletAB()
        self.doc.getObject("APad").Length = 15
        self.doc.recompute()
        self.assertVolume("A", 1500 - rounded(2))
        self.assertVolume("B", 1000 - rounded(2))
        self.assertClean(f)

    def testAPickFollowsItsPartIntoAMerge(self):
        """Q2c: F rounds B's top front edge (r 1); the bar E, an Add joining A and B (10.13), is
        put before F: B merges into A, F's pick follows to A (a step in A, none in B)."""
        b = self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(b, frontTop(20))], 1)
        sk = studioSketch(self.doc, self.S, "ESk", ((5, 2, 25, 8),), z=5)
        e = makeOwner(self.doc, self.S, "Pad", "E", sk, ("A", "B"), Length=10, Refine=False)
        PartDesign.studioMove(e, list(self.list.Entries).index(f))
        self.doc.recompute()
        self.assertEqual(list(e.StudioMergedParts), ["B -> A"])
        self.assertIsNotNone(self.step(f, "A"))
        self.assertIsNone(self.step(f, "B"))
        self.assertVolume("A", 2900 - rounded(1))
        self.assertClean(f)

    def testAMergedEdgeCutAgainRoundsEveryPiece(self):
        """10.14 point 2 as amended (P8a-2, gate seed 6 ops 54-56): the list is the only truth, so
        a step's Base follows the owner's lookup, not FreeCAD's tracking of what it last held. F
        rounds C's top left edge (x 40, z 10, along y; r 1); E, an Add x 25..45, y 2..4, z 5..15
        joining B and C, put before F, merges them and cuts the edge into y 0..2 and 4..10, both
        pieces of the pick (oracle 9 P2), L 8. A second rectangle y 6..7 in E's sketch cuts it
        into three, y 0..2, 4..6 and 7..10 (L 7), F's step keeping its base: every piece is
        rounded (FreeCAD's tracking kept one and lost one). Each piece ends on a wall square to
        it, so the round takes r^2 (1 - pi/4) L. The union: 2000 + the tool's 400 (then 600) less
        what of it is inside B and C, 2 x 50 (then 2 x 75)."""
        c = self.body("C")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(c, V(40, 5, 10))], 1)
        sk = studioSketch(self.doc, self.S, "ESk", ((25, 2, 45, 4),), z=5)
        e = makeOwner(self.doc, self.S, "Pad", "E", sk, ("B", "C"), Length=10, Refine=False)
        PartDesign.studioMove(e, list(self.list.Entries).index(f))
        self.doc.recompute()
        [merged] = list(e.StudioMergedParts)
        survivor = self.body(merged.split(" -> ")[1])
        self.assertVolume(survivor, 2300 - rounded(1, 8))
        rect(sk, 25, 6, 45, 7)
        self.doc.recompute()
        self.assertVolume(survivor, 2450 - rounded(1, 7))
        self.assertClean(f)

    def testAPickFollowsItsPartIntoABooleanUnion(self):
        """Q2c through a Boolean (P5): C moved to x 30..40, y 5..15 (touching B's right face);
        F rounds C's top front edge (y 5, z 10, x 30..40; r 1); the Boolean Union of B with the
        tool C, put before F, absorbs C into B: the pick follows to B (a step in B, none in C).
        The edge ends on B's face x 30, square to it: B is 2000 less r^2 (1 - pi/4) 10."""
        self.doc.getObject("CSk").AttachmentOffset = App.Placement(V(-10, 5, 0), App.Rotation())
        self.doc.recompute()
        c = self.body("C")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(c, V(35, 5, 10))], 1)
        self.assertVolume("C", 1000 - rounded(1))
        u = booleanOwner(self.doc, self.S, "U", "Fuse", ("B",), ("C",))
        PartDesign.studioInsert(u, list(self.list.Entries).index(f))
        self.doc.recompute()
        self.assertIsNotNone(self.step(f, "B"))
        self.assertIsNone(self.step(f, "C"))
        self.assertVolume("B", 2000 - rounded(1))
        self.assertClean(f)

    def slot(self, rect, scope=("B",), index=None):
        """A Pocket owner through z 10..-1 on rect, before index of the list, computed."""
        sk = studioSketch(self.doc, self.S, "ESk", (rect,), z=10)
        e = makeOwner(self.doc, self.S, "Pocket", "E", sk, scope, Length=11, Refine=False)
        if index is not None:
            PartDesign.studioMove(e, index)
        self.doc.recompute()
        return e

    def testAnEdgeSplitInOnePartRoundsBothPieces(self):
        """Oracle 9 P2: a notch x 24.5..25.5, y 0..3 in B's front (B stays one part), put before F,
        splits the picked edge: both pieces are rounded (4.5 each)."""
        b = self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(b, frontTop(20))], 1)
        self.slot((24.5, -1, 25.5, 3), index=list(self.list.Entries).index(f))
        self.assertVolume("B", 1000 - 30 - rounded(1, 9))
        self.assertClean(f)

    def testAPickOfASplitPartGoesToItsPiece(self):
        """P6p: a slot x 24.5..25.5 through B, put before F and made pieces: the pick of B's edge
        at x 30 (along y) is held by the right piece alone, which is rounded; the left piece holds
        none of F's picks and passes through silently."""
        b = self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(b, V(30, 5, 10))], 1)
        e = self.slot((24.5, -1, 25.5, 11), index=list(self.list.Entries).index(f))
        self.doc.openTransaction("pieces")
        PartDesign.studioMakePieces(e)
        self.doc.commitTransaction()
        self.doc.recompute()
        pieces = sorted(
            (p for p in PartDesign.studioLiveParts(self.list) if 15 < p.Shape.BoundBox.XMin < 35),
            key=lambda p: p.Shape.BoundBox.XMin,
        )
        self.assertEqual(len(pieces), 2)
        self.assertVolume(pieces[0], 450)
        self.assertVolume(pieces[1], 450 - rounded(1))
        self.assertClean(f)

    def pieces(self, e):
        """E made pieces, in its own step; the live parts that were B, by their lowest x, then z."""
        self.doc.openTransaction("pieces")
        PartDesign.studioMakePieces(e)
        self.doc.commitTransaction()
        self.doc.recompute()
        return sorted(
            (p for p in PartDesign.studioLiveParts(self.list) if 15 < p.Shape.BoundBox.XMin < 35),
            key=lambda p: (round(p.Shape.BoundBox.XMin, 6), round(p.Shape.BoundBox.ZMin, 6)),
        )

    def testAnEdgeSplitBetweenTwoPiecesRoundsBoth(self):
        """Onshape (oracle, hub 11 P8a: a pick is its edge's whole history): a slot x 24.5..25.5
        through B, made pieces before F, splits the picked top front edge between the two pieces:
        each piece's half is rounded (L 4.5), a step in each, no warning; A's pick rounds A."""
        a, b = self.body("A"), self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(a, frontTop(0)), pickAt(b, frontTop(20))], 1)
        e = self.slot((24.5, -1, 25.5, 11), index=list(self.list.Entries).index(f))
        left, right = self.pieces(e)
        self.assertVolume("A", 1000 - rounded(1))
        for piece in (left, right):
            self.assertIsNotNone(self.step(f, piece), piece.Name)
            self.assertVolume(piece, 450 - rounded(1, 4.5))
        self.assertClean(f)

    def crossCut(self, f):
        """A Remove across B at z 4.5..5.5 (a sketch on y = -1, normal -y, cut 12 deep along +y),
        put before f and made pieces: B's lower and upper halves, 450 each before f."""
        sk = studioSketch(self.doc, self.S, "ESk", ((19, 4.5, 31, 5.5),))
        sk.Placement = App.Placement(V(0, -1, 0), App.Rotation(V(1, 0, 0), 90))
        e = makeOwner(self.doc, self.S, "Pocket", "E", sk, ("B",), Length=12, Refine=False)
        PartDesign.studioMove(e, list(self.list.Entries).index(f))
        self.doc.recompute()
        return self.pieces(e)

    def testAVerticalEdgeCutAcrossRoundsBothHalves(self):
        """Onshape (oracle, hub 11 P8a, its box 20 x 20 x 10 split at z 5): the studio splits by a
        Remove, so a 1 mm gap at z 4.5..5.5 cuts B in two; r 2 on B's vertical edge at x 30, y 10,
        picked before: both halves rounded, (4 - pi) 4.5 off each of 450, no warning."""
        b = self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(b, V(30, 10, 5))], 2)
        self.assertVolume("B", 1000 - rounded(2))
        lower, upper = self.crossCut(f)
        for piece in (lower, upper):
            self.assertVolume(piece, 450 - rounded(2, 4.5))
        self.assertClean(f)

    def testAChamferOnAVerticalEdgeCutAcrossDressesBothHalves(self):
        """The same with a 1 mm chamfer: s^2 L / 2 = 2.25 off each half."""
        b = self.body("B")
        f = makeDressUp(self.doc, self.S, "F", [pickAt(b, V(30, 10, 5))], 1, "Chamfer")
        lower, upper = self.crossCut(f)
        for piece in (lower, upper):
            self.assertVolume(piece, 450 - 2.25)
        self.assertClean(f)

    def testReorderAboveTheEdgesMakerIsLoud(self):
        """A boss on A's top (x 2..8, z 10..15) makes the edge F rounds; F moved above the boss
        finds nothing: it fails, and A is the boss unrounded."""
        a = self.body("A")
        boss = pad(a, "Boss", sketch(a, "BossSk", xyPlane(a), (2, 2, 8, 8), z=10), 5)
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        f = makeDressUp(self.doc, self.S, "F", [pickAt(a, V(5, 2, 15))], 1)
        self.assertVolume("A", 1180 - rounded(1, 6))
        PartDesign.studioMove(f, list(self.list.Entries).index(boss))
        self.doc.recompute()
        self.assertFalse(f.isValid())
        self.assertVolume("A", 1180)

    def testSuppressedOwnerRoundsNothing(self):
        f = self.filletAB()
        PartDesign.studioSuppress(f, True)
        self.doc.recompute()
        self.assertVolume("A", 1000)
        self.assertVolume("B", 1000)
        PartDesign.studioSuppress(f, False)
        self.doc.recompute()
        self.assertVolume("A", 1000 - rounded(2))

    # ------------------------------------------------------------------------------- history
    def testUndoAndRedo(self):
        """One transaction makes the owner and its steps; undo takes them all, redo brings them."""
        self.doc.openTransaction("fillet")
        f = self.filletAB()
        self.doc.commitTransaction()
        steps = sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Fillet")
        self.assertEqual(len(steps), 3)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual([o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Fillet"], [])
        self.assertVolume("A", 1000)
        self.assertVolume("B", 1000)
        self.doc.redo()
        self.doc.recompute()
        self.assertEqual(
            sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Fillet"), steps
        )
        self.assertVolume("A", 1000 - rounded(2))
        self.assertVolume("B", 1000 - rounded(2))

    def testSaveAndReopen(self):
        """Expanded picks survive the save: reopened, the parts are rounded, and an edit after
        the reopen re-resolves A's pick."""
        self.filletAB()
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "TestStudioDressUpSaved.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.assertVolume("A", 1000 - rounded(2))
        self.assertVolume("B", 1000 - rounded(2))
        self.doc.getObject("APad").Length = 12
        self.doc.recompute()
        self.assertVolume("A", 1200 - rounded(2))
        f = self.doc.getObject("F")
        self.assertClean(f)


if __name__ == "__main__":
    unittest.main()
