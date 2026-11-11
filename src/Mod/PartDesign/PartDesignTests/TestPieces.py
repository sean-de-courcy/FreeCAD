# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (P6p): pieces and leftovers become parts at command time
#
# notes/parts-design.md 10.12, notes/onshape-facts.md "Split by Remove; names through Add" (S1-S3),
# "One-history" H1-H2, batch 3 H1a, batch 9 R4. A Remove that splits a part gives both pieces new
# ids and the old one is gone; a scope naming the split part resolves to its pieces, also when the
# split is inserted before it; identity stays with the same physical side when an edit moves the
# cut; a renamed part's pieces keep its name; an Add region touching no scope part, and a part
# mirror's Add copy touching none, become new parts. The parts are made by a command
# (PartDesign.studioMakePieces, a dialog's OK), never by a recompute: until then the feature fails
# loudly, naming what is no part.
#
# Designed geometry only: a bar P 100 x 10 x 10 (x 0..100) cut by a slot 1 wide through it at
# x 30..31 (a Pocket studio feature on a studio sketch at z 10, 11 deep): pieces x 0..30 (3000)
# and x 31..100 (6900). Expected values come from the boxes themselves.

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestStudioList import studioList
from PartDesignTests.TestStudioOwner import makeOwner, studioSketch
from PartDesignTests.TestStudioPartMirror import originPlane, partMirror

V = App.Vector
SLOT = (30, -1, 31, 11)


def box(x0, y0, z0, x1, y1, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


class TestPieces(unittest.TestCase):
    def setUp(self):
        self.doc = None
        self.dir = None

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestPieces"):
                App.closeDocument(doc.Name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- the model
    def studio(self, parts=(("P", (0, 0, 100, 10), 10),)):
        """parts = ((name, (x0, y0, x1, y1), height), ...): each a Body with a sketch and a Pad."""
        self.doc = App.newDocument("TestPieces")
        self.doc.UndoMode = 1
        self.S = self.doc.addObject("App::Part", "S")
        for name, r, height in parts:
            body = self.doc.addObject("PartDesign::Body", name)
            self.S.addObject(body)
            pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), r), height)
        self.doc.recompute()
        self.list = studioList(self.doc)
        PartDesign.studioReconcile(self.list)
        return self.doc

    def pocket(self, name, rects, scope, length=11, refine=False, index=None):
        sk = studioSketch(self.doc, self.S, name + "Sk", rects, z=10)
        owner = makeOwner(self.doc, self.S, "Pocket", name, sk, scope, Length=length, Refine=refine)
        if index is not None:
            PartDesign.studioMove(owner, index)
        self.doc.recompute()
        return owner

    def command(self, entry, name="pieces"):
        self.doc.openTransaction(name)
        made = PartDesign.studioMakePieces(entry)
        self.doc.commitTransaction()
        return made

    def slotSplit(self, refine=False):
        self.studio()
        e = self.pocket("E", (SLOT,), ("P",), refine=refine)
        return e, self.command(e)

    def live(self):
        return sorted(PartDesign.studioLiveParts(self.list), key=lambda b: b.Shape.BoundBox.XMin)

    def byId(self, partId):
        for b in self.doc.Objects:
            if b.TypeId == "PartDesign::Body" and b.StudioPartId == partId:
                return b
        return None

    def step(self, owner, body):
        return PartDesign.studioStepOf(owner, body)

    def assertValid(self, *objs):
        for o in objs:
            self.assertTrue(o.isValid(), f"{o.Name}: {o.getStatusString()}")

    def assertVolume(self, body, expected):
        self.assertAlmostEqual(body.Shape.Volume, expected, places=3, msg=body.Name)

    def leftRight(self, made):
        self.assertEqual(len(made), 2)
        return sorted(made, key=lambda b: b.Shape.BoundBox.XMin)

    def moveSketch(self, owner, dx):
        self.doc.openTransaction("move")
        sk = owner.Profile[0] if isinstance(owner.Profile, tuple) else owner.Profile
        sk.Placement = App.Placement(sk.Placement.Base + V(dx, 0, 0), App.Rotation())
        self.doc.commitTransaction()
        self.doc.recompute()

    @staticmethod
    def faceNames(shape):
        names = set()
        for value in shape.ElementReverseMap.values():
            for name in [value] if isinstance(value, str) else value:
                names.add(App.expandMappedName(name))
        return names

    # ------------------------------------------------------------------------------- the probe
    def testFirstProbeWitnessNamesStayWhenTheCutMoves(self):
        """10.12's first probe: every name of each piece's witness (the slot's wall, the unsplit
        end face, the open faces' pieces) is on the same piece after the slot moves to x 70..71,
        Refine off and on; the tiers are all there."""
        for refine in (False, True):
            e, made = self.slotSplit(refine)
            left, right = self.leftRight(made)
            for body in (left, right):
                tiers = {w[0] for w in body.StudioPieceWitness}
                self.assertEqual(tiers, {"1", "2", "3"}, (refine, list(body.StudioPieceWitness)))
                self.assertFalse([w for w in body.StudioPieceWitness if "#" in w])  # expanded
            self.moveSketch(e, 40)
            self.assertAlmostEqual(left.Shape.BoundBox.XMax, 70, places=6)
            for body in (left, right):
                names = self.faceNames(body.Shape)
                for w in body.StudioPieceWitness:
                    self.assertIn(w[2:], names, (refine, body.Name, w))
            App.closeDocument(self.doc.Name)

    # ------------------------------------------------------------------------------- S1/S2
    def testS1SplitGivesTwoNewPartsAndTheOldIdIsGone(self):
        """S1/S2: two new parts E:1 and E:2 made by E from P, in the source's solid order; P is no
        part after E; a later Pocket scoped to P cuts both pieces."""
        e, made = self.slotSplit()
        self.assertEqual(sorted(b.StudioPartId for b in made), ["E:1", "E:2"])
        for b in made:
            self.assertEqual(b.StudioParentId, "P")
            self.assertIs(b.StudioMadeBy, e)
            self.assertIn(b, self.S.Group)
            self.assertValid(self.step(e, b))
        left, right = self.leftRight(made)
        self.assertVolume(left, 3000)
        self.assertVolume(right, 6900)
        p = self.doc.getObject("P")
        self.assertEqual(self.live(), [left, right])
        self.assertNotIn(p, PartDesign.studioLiveParts(self.list))
        self.assertValid(e, self.step(e, p))
        self.assertFalse(p.Visibility)
        f = self.pocket("F", ((10, 2, 90, 8),), ("P",), length=2)
        self.assertIsNone(self.step(f, p))
        self.assertValid(f, self.step(f, left), self.step(f, right))
        self.assertVolume(left, 3000 - 20 * 6 * 2)
        self.assertVolume(right, 6900 - 59 * 6 * 2)

    def testSplitWithoutTheCommandFailsLoudly(self):
        """A recompute alone makes no part: the split fails naming the count; the command makes
        the parts, undo takes them away (the split fails again), redo brings them back."""
        self.studio()
        e = self.pocket("E", (SLOT,), ("P",))
        p = self.doc.getObject("P")
        step = self.step(e, p)
        self.assertFalse(step.isValid())
        self.assertIn("splits 'P' into 2 pieces", step.getStatusString())
        self.assertIn("press OK", step.getStatusString())
        bodies = len([o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"])
        made = self.command(e)
        self.assertEqual(len(made), 2)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(len([o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]), bodies)
        self.assertFalse(self.step(e, p).isValid())
        self.assertEqual(PartDesign.studioLiveParts(self.list), [p])
        self.doc.redo()
        self.doc.recompute()
        left, right = sorted(self.live(), key=lambda b: b.Shape.BoundBox.XMin)
        self.assertVolume(left, 3000)
        self.assertVolume(right, 6900)
        self.assertValid(self.step(e, p))

    def testASecondSlotIsLoudUntilTheCommandRunsAgain(self):
        """E checks its own count: a second slot (x 60..61) splits P into 3, 2 are parts: loud;
        the command again makes the third (E:3), the first two keep their ids and sides."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        sk = e.Profile[0]
        self.doc.openTransaction("second slot")
        from PartDesignTests.TestStudio import rect

        rect(sk, 60, -1, 61, 11)
        self.doc.commitTransaction()
        self.doc.recompute()
        step = self.step(e, self.doc.getObject("P"))
        self.assertFalse(step.isValid())
        self.assertIn("into 3 pieces, 2 are parts", step.getStatusString())
        made = self.command(e)
        self.assertEqual([b.StudioPartId for b in made], ["E:3"])
        self.assertValid(step)
        self.assertVolume(left, 3000)
        self.assertEqual(sorted(round(b.Shape.Volume) for b in (right, made[0])), [2900, 3900])

    # ------------------------------------------------------------------------------- H1, H2
    def testH1MovedCutKeepsTheSideAndAPieceScopedPocketCutsNothing(self):
        """H1: the x 31..100 piece keeps its id when the slot moves to x 70..71; a Pocket scoped
        to it at x 50..60 then meets nothing of it: it cuts nothing, no error."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        g = self.pocket("G", ((50, 2, 60, 8),), (right.StudioPartId,), length=2)
        self.assertVolume(right, 6900 - 120)
        self.moveSketch(e, 40)
        self.assertAlmostEqual(right.Shape.BoundBox.XMin, 71, places=6)
        self.assertVolume(right, 2900)
        self.assertVolume(left, 7000)  # G is scoped to the right piece only
        self.assertValid(self.step(g, right))

    def testH2SplitInsertedBeforeAParentScopedFeature(self):
        """H2: F (scoped to P) first, the split E inserted before it: F resolves to both pieces."""
        self.studio()
        f = self.pocket("F", ((10, 2, 90, 8),), ("P",), length=2)
        p = self.doc.getObject("P")
        self.assertVolume(p, 10000 - 80 * 6 * 2)
        at = list(self.list.Entries).index(f)
        e = self.pocket("E", (SLOT,), ("P",), index=at)
        made = self.command(e)
        left, right = self.leftRight(made)
        self.assertIsNone(self.step(f, p))
        self.assertValid(self.step(f, left), self.step(f, right))
        self.assertVolume(left, 3000 - 240)
        self.assertVolume(right, 6900 - 708)

    # ------------------------------------------------------------------------------- S3
    def testS3PiecesShowTheParentsCustomName(self):
        """S3 (#167, "Nest Insert"): both pieces of a renamed part show its name; of a part with
        the default name, none."""
        self.studio()
        p = self.doc.getObject("P")
        p.Label = "Nest Insert"
        e = self.pocket("E", (SLOT,), ("P",))
        made = self.command(e)
        self.assertEqual([PartDesign.studioPieceName(b) for b in made], ["Nest Insert"] * 2)
        p.Label = "Part 1"
        self.assertEqual([PartDesign.studioPieceName(b) for b in made], ["", ""])

    # ------------------------------------------------------------------------------- H1a, R4
    def testH1aAddRegionTouchingNoScopePartBecomesANewPart(self):
        """H1a: a Pad of two regions, one on A's top, one beside every part: loud until the
        command, which makes the second region a new part (108), A gains the first (1108)."""
        self.studio((("A", (0, 0, 10, 10), 10),))
        sk = studioSketch(self.doc, self.S, "P1Sk", ((2, 2, 8, 8), (60, 2, 66, 8)), z=10)
        p1 = makeOwner(self.doc, self.S, "Pad", "P1", sk, ("A",), Length=3)
        self.doc.recompute()
        self.assertFalse(p1.isValid())
        self.assertIn("touches no part of the merge scope", p1.getStatusString())
        made = self.command(p1)
        self.assertEqual(len(made), 1)
        new = made[0]
        self.assertEqual(new.StudioParentId, "")
        self.assertEqual(new.StudioPartId, "P1:1")
        self.assertValid(p1, self.step(p1, new))
        self.assertVolume(new, 108)
        self.assertVolume(self.doc.getObject("A"), 1108)
        self.assertEqual(sorted(b.Name for b in PartDesign.studioLiveParts(self.list)), ["A", new.Name])
        # A third region beside everything: E fails, naming it, until the command runs again
        from PartDesignTests.TestStudio import rect

        rect(sk, 80, 2, 84, 8)
        self.doc.recompute()
        self.assertFalse(p1.isValid())
        self.assertIn("is no part", p1.getStatusString())
        made = self.command(p1)
        self.assertEqual([b.StudioPartId for b in made], ["P1:2"])
        self.assertVolume(new, 108)
        self.assertVolume(made[0], 72)
        self.assertValid(p1)

    def testR4MirrorAddCopyTouchingNoScopePartBecomesANewPart(self):
        """R4: Y's copy (x -10..0) touches no part of the scope (X at x -30..-20): loud until the
        command, which makes the copy a new part; X and Y unchanged, neither consumed."""
        self.studio((("Y", (0, 0, 10, 10), 10), ("X", (-30, 0, -20, 10), 10)))
        y, x = self.doc.getObject("Y"), self.doc.getObject("X")
        m = partMirror(self.doc, self.S, "Mir", "Y", (originPlane(y, "YZ_Plane"), [""]), "Add", ("X",))
        self.doc.recompute()
        self.assertFalse(m.isValid())
        made = self.command(m)
        self.assertEqual(len(made), 1)
        self.assertValid(m, self.step(m, made[0]))
        self.assertVolume(made[0], 1000)
        self.assertAlmostEqual(made[0].Shape.BoundBox.XMin, -10, places=6)
        self.assertVolume(x, 1000)
        self.assertVolume(y, 1000)
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 3)

    # ------------------------------------------------------------------------------- the skeptic
    def testBossesRespacedAcrossTheSlotDontSwapTheSides(self):
        """Skeptic 1: bosses on P at x 10..20 and x 80..90 (z 10..15), the slot at 50..51; both
        bosses moved to the other side: the slot's walls still decide, no swap."""
        self.studio()
        p = self.doc.getObject("P")
        bosses = []
        for name, r in (("B1", (10, 2, 20, 8)), ("B2", (80, 2, 90, 8))):
            boss = pad(p, name, sketch(p, name + "Sk", xyPlane(p), r, z=10), 5)
            PartDesign.studioInsert(boss.Profile[0], -1)
            bosses.append(boss)
        self.doc.recompute()
        e = self.pocket("E", ((50, -1, 51, 11),), ("P",))
        left, right = self.leftRight(self.command(e))
        self.assertAlmostEqual(left.Shape.BoundBox.XMax, 50, places=6)
        self.doc.openTransaction("respace")
        bosses[0].Profile[0].AttachmentOffset = App.Placement(V(55, 0, 10), App.Rotation())
        bosses[1].Profile[0].AttachmentOffset = App.Placement(V(-55, 0, 10), App.Rotation())
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertValid(self.step(e, left), self.step(e, right))
        self.assertAlmostEqual(left.Shape.BoundBox.XMax, 50, places=6)
        self.assertAlmostEqual(right.Shape.BoundBox.XMin, 51, places=6)

    def testRingCutAcrossKeepsItsHalves(self):
        """A ring (r 10..20, centre 0,0, height 10) cut across by a slot x -0.5..0.5: two halves;
        the slot moved to x 4.5..5.5: each half keeps its id (its side)."""
        self.doc = App.newDocument("TestPieces")
        self.doc.UndoMode = 1
        self.S = self.doc.addObject("App::Part", "S")
        ring = self.doc.addObject("PartDesign::Body", "R")
        self.S.addObject(ring)
        sk = sketch(ring, "RSk", xyPlane(ring))
        for radius in (20, 10):
            sk.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), radius))
        pad(ring, "RPad", sk, 10)
        self.doc.recompute()
        self.list = studioList(self.doc)
        PartDesign.studioReconcile(self.list)
        e = self.pocket("E", ((-0.5, -30, 0.5, 30),), ("R",))
        left, right = self.leftRight(self.command(e))
        self.moveSketch(e, 5)
        self.assertValid(self.step(e, left), self.step(e, right))
        self.assertAlmostEqual(left.Shape.BoundBox.XMin, -20, places=6)
        self.assertAlmostEqual(right.Shape.BoundBox.XMax, 20, places=6)
        self.assertGreater(left.Shape.Volume, right.Shape.Volume)

    def testSplitStoppedTheStrongerRecordClaims(self):
        """The slot made shallow (z 5..10): one solid. The left piece, which carries a boss (more
        unsplit faces), claims it; the right piece's step fails loudly."""
        self.studio()
        p = self.doc.getObject("P")
        boss = pad(p, "B1", sketch(p, "B1Sk", xyPlane(p), (10, 2, 20, 8), z=10), 5)
        PartDesign.studioInsert(boss.Profile[0], -1)
        self.doc.recompute()
        e = self.pocket("E", (SLOT,), ("P",))
        left, right = self.leftRight(self.command(e))
        self.doc.openTransaction("shallow")
        e.Length = 5
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertValid(self.step(e, left))
        self.assertVolume(left, 10000 + 300 - 50)
        self.assertFalse(self.step(e, right).isValid())

    def testSplitStoppedATieMakesTheParentLive(self):
        """The slot made shallow with nothing to tell the pieces apart: both piece steps fail and
        P is live again after E (records name it, none holds a solid)."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        self.doc.openTransaction("shallow")
        e.Length = 5
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertFalse(self.step(e, left).isValid())
        self.assertFalse(self.step(e, right).isValid())
        p = self.doc.getObject("P")
        self.assertIn(p, PartDesign.studioLiveParts(self.list))
        self.assertVolume(p, 10000 - 50)

    def testSuppressedSplitListsTheParentNotThePieces(self):
        """E suppressed: P and C listed (two parts, not three); unsuppressed: the pieces and C."""
        self.studio((("P", (0, 0, 100, 10), 10), ("C", (200, 0, 210, 10), 10)))
        e = self.pocket("E", (SLOT,), ("P",))
        left, right = self.leftRight(self.command(e))
        self.doc.openTransaction("suppress")
        PartDesign.studioSuppress(e, True)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(sorted(b.Name for b in PartDesign.studioLiveParts(self.list)), ["C", "P"])
        self.assertVolume(self.doc.getObject("P"), 10000)
        self.doc.openTransaction("unsuppress")
        PartDesign.studioSuppress(e, False)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(
            sorted(b.Name for b in PartDesign.studioLiveParts(self.list)),
            sorted(["C", left.Name, right.Name]),
        )
        self.assertVolume(left, 3000)

    def testDeletingTheSplitDeletesItsEmptyParts(self):
        """E deleted: the pieces that hold nothing else go with it, P is live and whole; undo
        brings them back. A piece holding a later feature stays, never live."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        rightName = right.Name
        boss = pad(right, "RBoss", sketch(right, "RBossSk", xyPlane(right), (60, 2, 70, 8), z=10), 2)
        PartDesign.studioInsert(boss.Profile[0], -1)
        self.doc.recompute()
        self.assertVolume(right, 6900 + 120)
        leftName = left.Name
        self.doc.openTransaction("delete")
        self.doc.removeObject("E")
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(leftName))
        right = self.doc.getObject(rightName)
        self.assertIsNotNone(right)
        p = self.doc.getObject("P")
        self.assertEqual(PartDesign.studioLiveParts(self.list), [p])
        self.assertVolume(p, 10000)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNotNone(self.doc.getObject(leftName))
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 2)

    def testSaveAndReopenKeepsThePiecesAndTheirSides(self):
        """Saved and reopened: the same parts, ids and volumes after a full recompute; the slot
        moved after the reopen: the sides keep their ids."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        ids = (left.StudioPartId, right.StudioPartId)
        self.dir = tempfile.mkdtemp(prefix="pieces")
        path = os.path.join(self.dir, "TestPiecesSaved.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.doc.UndoMode = 1
        self.list = studioList(self.doc)
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        left, right = self.byId(ids[0]), self.byId(ids[1])
        self.assertVolume(left, 3000)
        self.assertVolume(right, 6900)
        self.moveSketch(self.doc.getObject("E"), 40)
        self.assertVolume(left, 7000)
        self.assertVolume(right, 2900)

    # ------------------------------------------------------------------------------- Union, patterns
    def testUnionKeepsAToolApartAPart(self):
        """A Union of A with B (touching) and C (apart): B merges into A (2000), C stays a part,
        not consumed (Onshape A-2' b)."""
        self.studio((("A", (0, 0, 10, 10), 10), ("B", (10, 0, 20, 10), 10), ("C", (40, 0, 50, 10), 10)))
        b = self.doc.addObject("PartDesign::Boolean", "U")
        self.S.addObject(b)
        b.Type = "Fuse"
        b.Refine = False
        b.StudioScope = ["A"]
        b.StudioTools = ["B", "C"]
        self.doc.openTransaction("union")
        PartDesign.studioInsert(b, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        a, c = self.doc.getObject("A"), self.doc.getObject("C")
        self.assertValid(b, self.step(b, a))
        self.assertVolume(a, 2000)
        self.assertEqual(len(a.Shape.Solids), 1)
        self.assertEqual(sorted(x.Name for x in PartDesign.studioLiveParts(self.list)), ["A", "C"])
        self.assertIsNone(PartDesign.studioConsumerOf(c))
        self.assertVolume(c, 1000)

    def testSecondUnionApartIsTakenInTheSameRecompute(self):
        """Two Unions, each with C apart (C at x 40..50 touches neither A nor B): U1 of A and C,
        then U2 of B with C. Until U1's compute keeps C, U2 sees C consumed and decides nothing;
        it decides C apart only in the recompute after U1's resync. One recompute takes both
        (the resync goes on while it finds an entry stale): C stays a part, consumed by neither
        (gate seed 3 edit 63, ops#654 P6p open item b)."""
        self.studio((("A", (0, 0, 10, 10), 10), ("B", (20, 0, 30, 10), 10), ("C", (40, 0, 50, 10), 10)))
        unions = []
        for name, target in (("U1", "A"), ("U2", "B")):
            b = self.doc.addObject("PartDesign::Boolean", name)
            self.S.addObject(b)
            b.Type = "Fuse"
            b.Refine = False
            b.StudioScope = [target]
            b.StudioTools = ["C"]
            unions.append(b)
        self.doc.openTransaction("unions")
        for b in unions:
            PartDesign.studioInsert(b, -1)
        self.doc.recompute()
        # Checked before the commit, whose own resync would take what the recompute left
        c = self.doc.getObject("C")
        try:
            for b in unions:
                self.assertEqual(list(b.StudioApartTools), ["C"], b.Name)
                self.assertEqual(list(getattr(b, "StudioApartToolsSeen", [])), ["C"], b.Name)
            self.assertIsNone(PartDesign.studioConsumerOf(c))
            self.assertIn(c, PartDesign.studioLiveParts(self.list))
        finally:
            self.doc.commitTransaction()

    def testPatternThatSplitsItsPartMakesPieces(self):
        """An in-Body pattern whose copy meets the seed slot and cuts the plate in two (seed
        x 10..14, y -1..11; copy at y +9): loud until its command, which makes the halves parts."""
        self.studio((("P", (0, 0, 60, 20), 10),))
        p = self.doc.getObject("P")
        slot = self.pocket("Slot", ((10, -1, 14, 11),), ("P",), length=10)
        lp = p.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [slot]
        lp.Direction = (p.Origin.OriginFeatures[1], [""])
        lp.Mode = "Extent"
        lp.Length = 9
        lp.Occurrences = 2
        PartDesign.studioInsert(lp, -1)
        self.doc.recompute()
        self.assertFalse(lp.isValid())
        self.assertIn("splits", lp.getStatusString())
        made = self.command(lp)
        left, right = self.leftRight(made)
        self.assertValid(lp, self.step(lp, left), self.step(lp, right))
        self.assertVolume(left, 10 * 20 * 10)
        self.assertVolume(right, 46 * 20 * 10)
        self.assertNotIn(p, PartDesign.studioLiveParts(self.list))


if __name__ == "__main__":
    unittest.main()
