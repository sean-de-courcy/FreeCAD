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

    def testRemoveMissingItsScopePartMakesNoPart(self):
        """A Remove only takes material away: a slot through P (x 30..31) scoped to Q alone (x 200..
        210), which it misses, cuts nothing at the command and makes no part of its own tool (the
        gate's seed 5 op 49, 10.13 gate round: the command made the cutter, 1 x 12 x 11, a part)."""
        self.studio((("P", (0, 0, 100, 10), 10), ("Q", (200, 0, 210, 10), 10)))
        bodies = sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body")
        e = self.pocket("E", (SLOT,), ("Q",))
        self.assertEqual(self.command(e), [])
        self.assertEqual(
            sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body"), bodies
        )
        self.assertVolume(self.doc.getObject("P"), 10000)
        self.assertVolume(self.doc.getObject("Q"), 1000)
        self.assertEqual(sorted(b.Name for b in PartDesign.studioLiveParts(self.list)), ["P", "Q"])

    def testMirrorRemoveCopyMissingItsScopePartMakesNoPart(self):
        """R4's mirror with Remove: Y's copy (x -10..0) misses the scope part X (x -30..-20); the
        command makes no part of the copy, X and Y keep 1000."""
        self.studio((("Y", (0, 0, 10, 10), 10), ("X", (-30, 0, -20, 10), 10)))
        y, x = self.doc.getObject("Y"), self.doc.getObject("X")
        m = partMirror(
            self.doc, self.S, "Mir", "Y", (originPlane(y, "YZ_Plane"), [""]), "Remove", ("X",)
        )
        self.doc.recompute()
        self.assertEqual(self.command(m), [])
        self.assertVolume(x, 1000)
        self.assertVolume(y, 1000)
        self.assertEqual(len(PartDesign.studioLiveParts(self.list)), 2)

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

    def testHoleSplitSketchTurnedKeepsTheSides(self):
        """A hole r 8 at (50, 5) through the bar splits it; a Pocket G (x 10..20 or 80..90, y 2..8,
        2 deep) scoped to E:1 and a sketch on E:1's top. E's circle turned about its centre by
        180, 90 and 270 degrees leaves the geometry as it was: E:1 keeps its side (its centre of
        mass), G still cuts it, the sketch stays on its top. The pieces of E's cylinder are
        placed by u from its seam, which the turn moves: no witness may come from them (review
        prline-b5-r1 R1, PieceHoleSketchTurnedHalf)."""
        bar = box(0, 0, 0, 100, 10, 10)
        hole = Part.makeCylinder(8, 12, V(50, 5, -1))
        pieces = sorted(bar.cut(hole).Solids, key=lambda s: s.BoundBox.XMin)
        for turn, stored in ((180, False), (90, False), (270, False), (180, True)):
            with self.subTest(turn=turn, stored=stored):
                self.studio()
                sk = studioSketch(self.doc, self.S, "ESk", circles=((0, 0, 8),), z=10)
                sk.Placement = App.Placement(V(50, 5, 10), App.Rotation())
                e = makeOwner(self.doc, self.S, "Pocket", "E", sk, ("P",), Length=11)
                self.doc.recompute()
                made = self.command(e)
                self.assertEqual(len(made), 2)
                for body in made:
                    self.assertFalse([w for w in body.StudioPieceWitness if "ORD" in w], body.Name)
                    if stored:
                        # As an older build stored it: the cylinder's pieces in tier 1 too
                        ordered = [n for n in self.faceNames(body.Shape) if "ORD" in n]
                        self.assertTrue(ordered)
                        body.StudioPieceWitness = list(body.StudioPieceWitness) + [
                            "1 " + n for n in ordered
                        ]
                first = self.byId("E:1")
                self.assertIsNotNone(first)
                leftSide = first.Shape.Solids[0].CenterOfMass.x < 50
                piece = pieces[0] if leftSide else pieces[1]
                self.assertAlmostEqual(first.Shape.Volume, piece.Volume, places=3)
                gx = 10 if leftSide else 80
                g = self.pocket("G", ((gx, 2, gx + 10, 8),), ("E:1",), length=2)
                self.assertVolume(first, piece.Volume - 120)
                top = [
                    f"Face{i + 1}"
                    for i, f in enumerate(first.Shape.Faces)
                    if f.Surface.isPlanar() and abs(f.CenterOfMass.z - 10) < 1e-6
                ]
                self.assertEqual(len(top), 1, top)
                on = self.doc.addObject("Sketcher::SketchObject", "OnFirst")
                on.AttachmentSupport = [(first, top[0])]
                on.MapMode = "FlatFace"
                self.doc.recompute()
                self.assertValid(on)
                self.doc.openTransaction("turn")
                sk.Placement = App.Placement(V(50, 5, 10), App.Rotation(V(0, 0, 1), turn))
                self.doc.commitTransaction()
                self.doc.recompute()
                self.assertValid(e, g, self.step(e, first), self.step(g, first), on)
                self.assertIs(self.byId("E:1"), first)
                self.assertEqual(len(first.Shape.Solids), 1, (turn, first.Shape.BoundBox))
                self.assertEqual(first.Shape.Solids[0].CenterOfMass.x < 50, leftSide, turn)
                self.assertVolume(first, piece.Volume - 120)
                sub = on.AttachmentSupport[0][1][0]
                onFace = first.getSubObject(sub)
                self.assertIsNotNone(onFace, sub)
                self.assertEqual(onFace.CenterOfMass.x < 50, leftSide, (turn, sub))
                self.assertAlmostEqual(on.Placement.Base.z, 10, places=6)
                App.closeDocument(self.doc.Name)

    def testRefusalPartWayLeavesNoPart(self):
        """One Remove E on two parts: the slot splits the bar P (whose pieces could be parts),
        two holes r 8 at (185, 0) and (215, 0) cut the ring R (r 10..20 at (200, 0)) into halves
        y > 0 and y < 0 that only the holes' order on their circles tells apart (no witness): the
        command refuses, and it leaves no part, P's pieces neither (the header's "empty on a
        refusal"; review prline-b5-r1 T3). E stays loud, naming the count."""
        self.studio()
        ring = self.doc.addObject("PartDesign::Body", "R")
        self.S.addObject(ring)
        sk = sketch(ring, "RSk", xyPlane(ring))
        for radius in (20, 10):
            sk.addGeometry(Part.Circle(V(200, 0, 0), V(0, 0, 1), radius))
        pad(ring, "RPad", sk, 10)
        self.doc.recompute()
        PartDesign.studioReconcile(self.list)
        esk = studioSketch(
            self.doc, self.S, "ESk", rects=(SLOT,), circles=((185, 0, 8), (215, 0, 8)), z=10
        )
        e = makeOwner(self.doc, self.S, "Pocket", "E", esk, ("P", "R"), Length=11)
        self.doc.recompute()
        bodies = sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body")
        self.doc.openTransaction("pieces")
        with self.assertRaises(ValueError) as refused:
            PartDesign.studioMakePieces(e)
        self.doc.commitTransaction()
        self.assertIn("No face tells piece", str(refused.exception))
        self.assertEqual(
            sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body"), bodies
        )
        self.doc.recompute()
        for name in ("P", "R"):
            step = self.step(e, self.doc.getObject(name))
            self.assertFalse(step.isValid(), name)
            self.assertIn("press OK", step.getStatusString())

    # ----------------------------------------------- a split that stops (10.12 amendment, Q13)
    def shallow(self, e, length=5):
        self.doc.openTransaction("depth")
        e.Length = length
        self.doc.commitTransaction()
        self.doc.recompute()

    def assertNothingFails(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    def assertGone(self, e, p, volume, *pieces):
        """The split is gone (Onshape SPLIT_NO_CHANGE): P is the one part, with volume; the pieces
        are no parts and have no step of E; nothing fails."""
        self.assertEqual(PartDesign.studioLiveParts(self.list), [p])
        self.assertVolume(p, volume)
        for piece in pieces:
            self.assertIsNone(self.step(e, piece), piece.Name)
        self.assertEqual(list(getattr(e, "StudioSplitLost", [])), ["P"])
        self.assertNothingFails()

    def testSplitStoppedResolvesToTheParent(self):
        """Q13: the slot made shallow (z 5..10), one solid. Neither piece claims it, though the
        left one carries a boss (more unsplit faces): P is the one part again (the boss's volume
        included), the pieces are no parts, and nothing fails."""
        self.studio()
        p = self.doc.getObject("P")
        boss = pad(p, "B1", sketch(p, "B1Sk", xyPlane(p), (10, 2, 20, 8), z=10), 5)
        PartDesign.studioInsert(boss.Profile[0], -1)
        self.doc.recompute()
        e = self.pocket("E", (SLOT,), ("P",))
        left, right = self.leftRight(self.command(e))
        self.shallow(e)
        self.assertGone(e, p, 10000 + 300 - 50, left, right)
        self.assertValid(e)

    def testSplitStoppedWithATieResolvesToTheParent(self):
        """The slot made shallow with nothing to tell the pieces apart: as above."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        self.shallow(e)
        self.assertGone(e, self.doc.getObject("P"), 10000 - 50, left, right)

    def addOwner(self, name, rect, scope, height=5):
        sk = studioSketch(self.doc, self.S, name + "Sk", (rect,), z=10)
        owner = makeOwner(self.doc, self.S, "Pad", name, sk, scope, Length=height)
        self.doc.recompute()
        return owner

    def testQ13aAnAddScopedToAVanishedPieceMergesIntoTheParent(self):
        """Q13a: F, an Add on the right piece (a 10 x 6 x 5 boss at x 70..80) scoped to it. The
        split stopped: F stays OK and adds to P."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        f = self.addOwner("F", (70, 2, 80, 8), (right.StudioPartId,))
        self.assertVolume(right, 6900 + 300)
        self.shallow(e)
        p = self.doc.getObject("P")
        self.assertGone(e, p, 10000 - 50 + 300, left, right)
        self.assertValid(f, self.step(f, p))
        self.assertIsNone(self.step(f, right))

    def testQ13bAScopeOfBothPiecesResolvesToTheParentOnce(self):
        """Q13b: F bridges the slot (x 25..36, 11 x 6 x 5), scope the right piece then the left:
        it rejoins them (the right survives, 10.13). The split stopped: F adds to P once."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        f = self.addOwner("F", (25, 2, 36, 8), (right.StudioPartId, left.StudioPartId))
        self.assertVolume(right, 3000 + 6900 + 330)
        self.shallow(e)
        p = self.doc.getObject("P")
        self.assertGone(e, p, 10000 - 50 + 330, left, right)
        self.assertValid(f, self.step(f, p))

    def testTheSplitComesBackWithItsIds(self):
        """Gone, then cutting again: the pieces are parts again with their ids, and G (a hole
        2 x 2 x 2 at x 70..72 scoped to the right piece) goes back to it, having cut P meanwhile.
        A command on E while the split is gone deletes no record (Onshape Q14a)."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        ids = (left.StudioPartId, right.StudioPartId)
        g = self.pocket("G", ((70, 2, 72, 4),), (right.StudioPartId,), length=2)
        self.assertVolume(right, 6900 - 8)
        self.shallow(e)
        p = self.doc.getObject("P")
        self.assertGone(e, p, 10000 - 50 - 8, left, right)
        self.assertEqual(self.command(e), [])
        self.assertGone(e, p, 10000 - 50 - 8, left, right)
        self.shallow(e, 11)
        self.assertEqual(self.live(), [left, right])
        self.assertEqual((left.StudioPartId, right.StudioPartId), ids)
        self.assertVolume(left, 3000)
        self.assertVolume(right, 6900 - 8)
        self.assertValid(e, g, self.step(g, right))
        self.assertIsNone(self.step(g, p))
        self.assertEqual(list(getattr(e, "StudioSplitLost", [])), [])

    def testABodyMemberOfAVanishedPieceIsLoud(self):
        """A Pad in the right piece's Body (a FreeCAD construct, no Onshape analogue), then the
        split stopped: the reconcile refuses, naming the member and the gone split, and the
        piece's step stays in error: loud, never a silent part (skeptic 5, 10.12 amendment)."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        rb = pad(right, "RB", sketch(right, "RBSk", xyPlane(right), (70, 2, 80, 8), z=10), 2)
        self.doc.recompute()
        PartDesign.studioReconcile(self.list)
        self.doc.recompute()
        self.assertVolume(right, 6900 + 120)
        self.shallow(e)
        with self.assertRaises(Exception) as refused:
            PartDesign.studioReconcile(self.list)
        self.assertIn("'RB' is in", str(refused.exception))
        self.assertIn("which is gone", str(refused.exception))
        self.assertFalse(self.step(e, right).isValid())

    def testSplitStoppedUndoRedo(self):
        """Undo of the edit that stops the split: the pieces are parts again; redo: P again. The
        recompute inside the edit's transaction, as a dialog's OK (a recompute after the commit
        is 10.15's)."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        p = self.doc.getObject("P")
        self.doc.openTransaction("depth")
        e.Length = 5
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertGone(e, p, 10000 - 50, left, right)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.live(), [left, right])
        self.assertVolume(left, 3000)
        self.assertValid(self.step(e, left), self.step(e, right))
        self.doc.redo()
        self.doc.recompute()
        self.assertGone(e, p, 10000 - 50, left, right)

    def testSplitStoppedSaveAndReopen(self):
        """Saved with the split gone: reopened, P is the one part and nothing fails."""
        e, made = self.slotSplit()
        self.shallow(e)
        names = [b.Name for b in made]
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "gone.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.list = studioList(self.doc)
        self.doc.recompute()
        e = self.doc.getObject("E")
        pieces = [self.doc.getObject(name) for name in names]
        self.assertGone(e, self.doc.getObject("P"), 10000 - 50, *pieces)

    def testPartMirrorOfAVanishedPieceMirrorsTheParent(self):
        """M, a part mirror (New) of the right piece about x = 0. The split stopped: M mirrors P
        (Onshape Q14c: a part pattern there, the part mirror here, our one part pattern)."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        p = self.doc.getObject("P")
        m = partMirror(self.doc, self.S, "M", right.StudioPartId, (originPlane(p, "YZ_Plane"), [""]))
        self.doc.recompute()
        copy = [b for b in self.live() if b not in (left, right)]
        self.assertEqual(len(copy), 1)
        self.assertVolume(copy[0], 6900)
        self.shallow(e)
        self.assertEqual(sorted(b.Name for b in PartDesign.studioLiveParts(self.list)), sorted([p.Name, copy[0].Name]))
        self.assertVolume(copy[0], 10000 - 50)
        self.assertValid(m)
        self.assertNothingFails()

    # ------------------------------------- a partial unsplit, the split back (Onshape Q14b-f)
    def setRect(self, owner, k, r, inside=False):
        """The k-th rectangle of owner's sketch moved to r (its lines edited, so they keep their
        ids, as a drag in the sketcher); with inside, recomputed inside the edit's transaction."""
        sk = owner.Profile[0] if isinstance(owner.Profile, tuple) else owner.Profile
        x0, y0, x1, y1 = r
        points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        geometry = sk.Geometry
        for i in range(4):
            line = geometry[4 * k + i]
            line.StartPoint = points[i]
            line.EndPoint = points[(i + 1) % 4]
            geometry[4 * k + i] = line
        self.doc.openTransaction("rect")
        sk.Geometry = geometry
        if inside:
            self.doc.recompute()
        self.doc.commitTransaction()
        self.doc.recompute()

    def threePieces(self):
        """Q14e's model: one Remove E with two through slots, x 29..31 and x 69..71: three pieces
        x 0..29 (2900), x 31..69 (3800), x 71..100 (2900), in x order."""
        self.studio()
        e = self.pocket("E", ((29, -1, 31, 11), (69, -1, 71, 11)), ("P",))
        made = sorted(self.command(e), key=lambda b: b.Shape.BoundBox.XMin)
        self.assertEqual(len(made), 3)
        for body, volume in zip(made, (2900, 3800, 2900)):
            self.assertVolume(body, volume)
        return e, made

    def assertAbsorbed(self, e, holder, piece, live):
        """A partial unsplit (Onshape Q14e): piece's solid is holder's now; piece is no part and
        has no step of E, the live parts are live, E records the absorption, nothing fails."""
        self.assertEqual(self.live(), live)
        self.assertIsNone(self.step(e, piece))
        self.assertValid(e, self.step(e, holder))
        self.assertEqual(
            list(getattr(e, "StudioSplitLost", [])),
            [piece.StudioPartId + ">" + holder.StudioPartId],
        )
        self.assertNothingFails()

    def testQ14eAPartialUnsplitIsQuietAndItsPicksGoToTheHolder(self):
        """Onshape Q14e: three pieces; Adds scoped to the middle piece (x 40..50) and to the right
        one (x 80..90), 10 x 6 x 5 each. The second slot shrunk to y 2..8 (a hole inside the part,
        no cut across): two parts, x 0..29 and x 31..100. The right piece vanishes quietly into the
        middle one, which holds the merged solid (ours: the stronger witness, two slot walls to
        one; Onshape kept the x 71..100 piece's id, unverified here and seen only in which Body
        holds the part); both Adds stay OK in it. The slot widened back: three parts with their
        ids, each Add on its piece again."""
        e, (left, middle, right) = self.threePieces()
        ids = [b.StudioPartId for b in (left, middle, right)]
        am = self.addOwner("AM", (40, 2, 50, 8), (middle.StudioPartId,))
        ar = self.addOwner("AR", (80, 2, 90, 8), (right.StudioPartId,))
        self.assertVolume(middle, 3800 + 300)
        self.assertVolume(right, 2900 + 300)
        self.setRect(e, 1, (69, 2, 71, 8))
        self.assertAbsorbed(e, middle, right, [left, middle])
        self.assertVolume(left, 2900)
        self.assertVolume(middle, 6900 - 2 * 6 * 10 + 600)
        self.assertEqual(len(middle.Shape.Solids), 1)
        self.assertValid(am, ar, self.step(am, middle), self.step(ar, middle))
        self.assertIsNone(self.step(ar, right))
        self.assertNotIn(right, PartDesign.studioLiveParts(self.list))
        # A command on E while the split is partly gone keeps the absorbed record (point 4)
        self.assertEqual(self.command(e), [])
        self.assertAbsorbed(e, middle, right, [left, middle])
        self.setRect(e, 1, (69, -1, 71, 11))
        self.assertEqual(self.live(), [left, middle, right])
        self.assertEqual([b.StudioPartId for b in (left, middle, right)], ids)
        self.assertVolume(middle, 3800 + 300)
        self.assertVolume(right, 2900 + 300)
        self.assertValid(am, ar, self.step(ar, right))
        self.assertIsNone(self.step(ar, middle))
        self.assertEqual(list(getattr(e, "StudioSplitLost", [])), [])
        self.assertNothingFails()

    def testQ14eTwoSlotsTheSecondShallowMergesIntoTheFirstsPiece(self):
        """Onshape Q14e's variant: E1 splits P at x 29..31, E2 splits its right piece at x 69..71;
        Adds scoped to each of E2's pieces. E2 made 5 deep: its split is gone (one solid), both
        its pieces vanish and both Adds merge into E1's right piece (Onshape: JMD, the id that
        piece has after slot 1 alone)."""
        self.studio()
        e1 = self.pocket("E1", ((29, -1, 31, 11),), ("P",))
        left1, right1 = self.leftRight(self.command(e1))
        e2 = self.pocket("E2", ((69, -1, 71, 11),), (right1.StudioPartId,))
        mid, right = self.leftRight(self.command(e2))
        a1 = self.addOwner("A1", (40, 2, 50, 8), (mid.StudioPartId,))
        a2 = self.addOwner("A2", (80, 2, 90, 8), (right.StudioPartId,))
        self.assertEqual(self.live(), [left1, mid, right])
        self.shallow(e2)
        self.assertEqual(self.live(), [left1, right1])
        self.assertVolume(right1, 6900 - 2 * 10 * 5 + 600)
        self.assertVolume(left1, 2900)
        self.assertValid(a1, a2, self.step(a1, right1), self.step(a2, right1))
        for piece in (mid, right):
            self.assertIsNone(self.step(e2, piece))
        self.assertEqual(list(getattr(e2, "StudioSplitLost", [])), [right1.StudioPartId])
        self.assertNothingFails()

    def testQ14bTheSplitComesBackElsewhereWithItsSides(self):
        """Onshape Q14b: G, an Add (x 70..80) scoped to the right piece. The slot made shallow (the
        split gone), moved to x 10..11, then through again: the ids keep their sides of the slot
        (the +x piece keeps the +x id), and G is on the +x piece again."""
        e, made = self.slotSplit()
        left, right = self.leftRight(made)
        ids = (left.StudioPartId, right.StudioPartId)
        g = self.addOwner("G", (70, 2, 80, 8), (right.StudioPartId,))
        self.shallow(e)
        p = self.doc.getObject("P")
        self.assertGone(e, p, 10000 - 50 + 300, left, right)
        self.moveSketch(e, -20)
        self.assertGone(e, p, 10000 - 50 + 300, left, right)
        self.shallow(e, 11)
        self.assertEqual(self.live(), [left, right])
        self.assertEqual((left.StudioPartId, right.StudioPartId), ids)
        self.assertVolume(left, 1000)
        self.assertVolume(right, 8900 + 300)
        self.assertValid(e, g, self.step(g, right))
        self.assertNothingFails()

    def testQ14eAPartMirrorOfAnAbsorbedPieceMirrorsItsHolder(self):
        """A part mirror (New) of the right piece about x = 0 (Onshape Q14c's principle with Q14e's
        partial unsplit): the right piece absorbed, M mirrors the merged middle part."""
        e, (left, middle, right) = self.threePieces()
        p = self.doc.getObject("P")
        m = partMirror(self.doc, self.S, "M", right.StudioPartId, (originPlane(p, "YZ_Plane"), [""]))
        self.doc.recompute()
        copy = [b for b in self.live() if b not in (left, middle, right)]
        self.assertEqual(len(copy), 1)
        self.assertVolume(copy[0], 2900)
        self.setRect(e, 1, (69, 2, 71, 8))
        self.assertAbsorbed(e, middle, right, [copy[0], left, middle])
        self.assertVolume(copy[0], 6900 - 120)
        self.assertValid(m)

    def testQ14fABooleanWithAVanishedToolConsumesTheWholePart(self):
        """Onshape Q14f: T a part touching P's end (x 100..110); U, a Union of T (target) with the
        right piece (tool), Keep tools off: T 1000 + 6900, the right piece consumed. The split made
        shallow: U consumes all of P into T (V = P + T), OK; T is the one part."""
        self.studio((("P", (0, 0, 100, 10), 10), ("T", (100, 0, 110, 10), 10)))
        e = self.pocket("E", (SLOT,), ("P",))
        left, right = self.leftRight(self.command(e))
        u = self.doc.addObject("PartDesign::Boolean", "U")
        self.S.addObject(u)
        u.Type = "Fuse"
        u.Refine = False
        u.StudioScope = ["T"]
        u.StudioTools = [right.StudioPartId]
        self.doc.openTransaction("union")
        PartDesign.studioInsert(u, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        t, p = self.doc.getObject("T"), self.doc.getObject("P")
        self.assertVolume(t, 1000 + 6900)
        self.assertEqual(self.live(), [left, t])
        self.shallow(e)
        self.assertEqual(PartDesign.studioLiveParts(self.list), [t])
        self.assertVolume(t, 1000 + 10000 - 50)
        self.assertEqual(len(t.Shape.Solids), 1)
        self.assertValid(u, self.step(u, t))
        self.assertNothingFails()

    def testPartialUnsplitUndoRedo(self):
        """Undo of the edit that shrinks the second slot: three parts again; redo: two, the right
        piece absorbed (recomputed inside the edit's transaction, as testSplitStoppedUndoRedo)."""
        e, (left, middle, right) = self.threePieces()
        self.setRect(e, 1, (69, 2, 71, 8), inside=True)
        self.assertAbsorbed(e, middle, right, [left, middle])
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.live(), [left, middle, right])
        self.assertVolume(right, 2900)
        self.assertValid(self.step(e, middle), self.step(e, right))
        self.doc.redo()
        self.doc.recompute()
        self.assertAbsorbed(e, middle, right, [left, middle])
        self.assertVolume(middle, 6900 - 120)

    def testPartialUnsplitSaveAndReopen(self):
        """Saved with the right piece absorbed: reopened, the same two parts and nothing fails."""
        e, made = self.threePieces()
        self.setRect(e, 1, (69, 2, 71, 8))
        names = [b.Name for b in made]
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "partial.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.list = studioList(self.doc)
        self.doc.recompute()
        left, middle, right = [self.doc.getObject(name) for name in names]
        self.assertAbsorbed(self.doc.getObject("E"), middle, right, [left, middle])
        self.assertVolume(middle, 6900 - 120)

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

    def testPatternSplitLostSettles(self):
        """The pattern's split lost (LP.Length 9 -> 5: the copy at y 5..16 overlaps the seed slot,
        y -1..11, and leaves the plate whole): one recompute settles (the lost split's Seen twin
        is taken, so the resync stops: no "doesn't settle" warning) and the plate is one part
        again, its pieces' steps failing loudly (review prline-b5-r1 T2: the Seen twin of a Body
        member's StudioSplitLost was never updated, every recompute ran its bound of rounds)."""
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
        self.leftRight(self.command(lp))
        self.doc.openTransaction("shorter")
        lp.Length = 5
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(list(getattr(lp, "StudioSplitLost", [])), ["P"])
        self.assertEqual(list(getattr(lp, "StudioSplitLostSeen", [])), ["P"])
        self.assertIn(p, PartDesign.studioLiveParts(self.list))
        self.assertValid(lp)
        # The plate less the seed slot and its copy: x 10..14, y 0..16 (y 5..16 the copy's)
        self.assertVolume(p, 60 * 20 * 10 - 4 * 16 * 10)

    def testAdoptedIdsDontRecomputeOtherParts(self):
        """ops#640 (FMCVW #167): the piece command on a history adopted from the document's order
        names every part (an empty id reads as the Body's name, so the id doesn't change) and
        recomputes the split and its pieces only. Before, each adopted Body was touched,
        re-executed and touched everything linking it: here a Boolean and a chamfer in another
        part (FMCVW: 819 s of earlier fillets for a 1 s Pocket).
        Bodies A (box 40 x 20 x 10 at x 0), B (the same at x 100), C (40 x 20 x 5 at x 0) fused
        with A, then a chamfer; a slot 2 wide through B at x 119..121 splits B into two
        19 x 20 x 10 pieces. Undoing the command puts the ids back to "", again without touching."""
        self.doc = App.newDocument("TestPieces")
        self.doc.UndoMode = 1

        def boxBody(name, x0, height):
            body = self.doc.addObject("PartDesign::Body", name)
            pad(body, name + "Pad", sketch(body, name + "Sk", xyPlane(body), (x0, 0, x0 + 40, 20)), height)
            return body

        a = boxBody("A", 0, 10)
        b = boxBody("B", 100, 10)
        c = boxBody("C", 0, 5)
        self.doc.recompute()
        fuse = c.newObject("PartDesign::Boolean", "CFuse")
        fuse.Type = "Fuse"
        fuse.addObjects([a])
        self.doc.recompute()
        chamfer = c.newObject("PartDesign::Chamfer", "CChamfer")
        chamfer.Base = (fuse, ["Edge1"])
        chamfer.Size = 0.5
        slotSketch = sketch(b, "BSlotSk", xyPlane(b), (119, -5, 121, 25))
        slot = b.newObject("PartDesign::Pocket", "BSlot")
        slot.Profile = slotSketch
        slot.Type = "ThroughAll"
        slot.Midplane = True
        self.doc.recompute()
        self.assertEqual(len(slot.Shape.Solids), 2)
        for obj in (fuse, chamfer):
            self.assertEqual(list(obj.State), ["Up-to-date"], obj.Name)
        self.assertIsNone(PartDesign.studioList(None, False))
        PartDesign.studioList(None, True)

        recomputed = []

        class Observer:
            def slotRecomputedObject(self, obj):
                recomputed.append(obj.Name)

        observer = Observer()
        App.addDocumentObserver(observer)
        try:
            made = list(self.command(slot))
            self.assertEqual(len(made), 2)
            for body in (a, c):
                self.assertEqual(body.StudioPartId, body.Name)
            others = ("A", "APad", "C", "CFuse", "CChamfer")
            self.assertIn("BSlot", recomputed)
            for name in others:
                self.assertNotIn(name, recomputed)
            del recomputed[:]
            self.doc.undo()
            self.doc.recompute()
            for name in others:
                self.assertNotIn(name, recomputed)
            self.assertEqual(c.StudioPartId, "")
            self.doc.redo()
            self.doc.recompute()
            for name in others:
                self.assertNotIn(name, recomputed)
        finally:
            App.removeDocumentObserver(observer)
        for piece in made:
            self.assertAlmostEqual(piece.Shape.Volume, 19 * 20 * 10, places=6)
        self.assertEqual(c.StudioPartId, c.Name)
        self.assertEqual(list(chamfer.State), ["Up-to-date"])


class TestStudioUndo(unittest.TestCase):
    """ops#654 10.15: the resync after a recompute outside any transaction records into the undo
    step it follows (the last one), so undoing the edit undoes the steps the resync made or
    deleted with it.

    Designed geometry: Y (x 2..12, y 0..10, 10 high) and X (x -20..-10), a part mirror Mir of Y
    about Y's YZ plane (x = 0), Add, scope X: the copy x -12..-2 joins X and stays apart from Y.
    E, a Pocket in Y (x 4..8, y 2..8, 3 deep), after Mir. Y's sketch moved by -2 (x 0..10): Y
    touches its copy at x = 0, Mir consumes it, and E's step in Y goes (decided at compute)."""

    def setUp(self):
        self.doc = None
        self.observer = None

    def tearDown(self):
        if self.observer is not None:
            App.removeDocumentObserver(self.observer)
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestStudioUndo"):
                App.closeDocument(doc.Name)

    # ------------------------------------------------------------------------------- the model
    def model(self):
        from PartDesignTests.TestStudioPartMirror import boxPart

        doc = self.doc = App.newDocument("TestStudioUndo")
        doc.UndoMode = 1
        # As the Gui has it (ops#640): an undo or redo regenerates before its own signal, so the
        # resync there sees the records the regeneration re-derives. Without it (FreeCADCmd's
        # default) the resync at undo()'s own signal reads a record written outside the step
        # against the restored inputs (ops#654 10.15, left open)
        doc.RegenerateOnCommit = True
        self.S = doc.addObject("App::Part", "S")
        self.y = boxPart(doc, self.S, "Y", 2, 0, 12, 10, 0, 10)
        self.x = boxPart(doc, self.S, "X", -20, 0, -10, 10, 0, 10)
        doc.recompute()
        self.list = PartDesign.studioList(self.S, True)
        doc.openTransaction("mirror")
        self.mir = partMirror(
            doc, self.S, "Mir", "Y", (originPlane(self.y, "YZ_Plane"), [""]), "Add", ("X",)
        )
        doc.recompute()
        doc.commitTransaction()
        doc.openTransaction("pocket")
        sk = studioSketch(doc, self.S, "ESk", ((4, 2, 8, 8),), z=10)
        self.e = makeOwner(doc, self.S, "Pocket", "E", sk, ("Y",), Length=3)
        doc.recompute()
        doc.commitTransaction()
        self.assertIsNone(PartDesign.studioConsumerOf(self.y))
        self.assertIsNotNone(PartDesign.studioStepOf(self.e, self.y))
        self.assertEqual(doc.UndoNames, ["pocket", "mirror"])
        return doc

    def moveY(self, dx):
        sk = self.doc.getObject("YSk")
        sk.AttachmentOffset = App.Placement(V(dx, 0, 0), App.Rotation())

    def state(self):
        """Every Body's Group (its origin left out), the list, the live parts, and every step's
        name and Body (None: a step in no Body)."""
        out = {}
        steps = []
        bodies = [o for o in self.doc.Objects if o.TypeId == "PartDesign::Body"]
        for body in bodies:
            out[body.Name] = [g.Name for g in body.Group if g.TypeId != "App::Origin"]
        for o in self.doc.Objects:
            if getattr(o, "StudioOwner", None) is not None:
                holder = [b.Name for b in bodies if o in b.Group]
                steps.append((o.Name, holder[0] if holder else None))
        out["list"] = [e.Name for e in self.list.Entries]
        out["live"] = sorted(b.Name for b in PartDesign.studioLiveParts(self.list))
        out["steps"] = sorted(steps)
        return out

    def assertNoStray(self, state):
        stray = [name for name, body in state["steps"] if body is None]
        self.assertEqual(stray, [], "steps in no Body")
        names = [name for name, _ in state["steps"]]
        self.assertFalse([n for n in names if n[-3:].isdigit()], f"suffixed steps: {names}")

    def consoleOutput(self, action):
        """What action() prints through FreeCADCmd's console observer (stderr), warnings on."""
        if "Console" not in App.Console.GetObservers():
            self.skipTest("no console observer to catch the warnings (the GUI)")
        status = App.Console.GetStatus("Console", "Wrn")
        App.Console.SetStatus("Console", "Wrn", True)
        saved = os.dup(2)
        with tempfile.TemporaryFile() as caught:
            os.dup2(caught.fileno(), 2)
            try:
                action()
            finally:
                os.dup2(saved, 2)
                os.close(saved)
                App.Console.SetStatus("Console", "Wrn", bool(status))
            caught.seek(0)
            return caught.read().decode("utf-8", "replace")

    # ------------------------------------------------------------------------------- the tests
    def testCommitThenRecomputeUndoesTheResyncWithTheEdit(self):
        """The move committed, then recomputed outside it: Mir consumes Y and E's step in Y goes,
        inside the move's step (no step of the resync's own). Undo: every Body, the list and every
        step as before the move, and a reconcile succeeds; redo: the moved state again."""
        doc = self.model()
        before = self.state()
        doc.openTransaction("move")
        self.moveY(-2)
        doc.commitTransaction()
        doc.recompute()
        after = self.state()
        self.assertIs(PartDesign.studioConsumerOf(self.y), self.mir)
        self.assertIsNone(PartDesign.studioStepOf(self.e, self.y))
        self.assertEqual(doc.UndoNames, ["move", "pocket", "mirror"])
        doc.undo()
        doc.recompute()
        self.assertEqual(self.state(), before)
        self.assertIsNone(PartDesign.studioConsumerOf(self.y))
        self.assertIsNotNone(PartDesign.studioStepOf(self.e, self.y))
        PartDesign.studioReconcile(self.list)
        self.assertEqual(self.state(), before)
        self.assertEqual(doc.UndoNames, ["pocket", "mirror"])
        doc.redo()
        doc.recompute()
        self.assertEqual(self.state(), after)
        self.assertIs(PartDesign.studioConsumerOf(self.y), self.mir)
        self.assertEqual(doc.UndoNames, ["move", "pocket", "mirror"])
        self.assertEqual(doc.RedoCount, 0)

    def testUnrecordedChangeThenUndoClearsRedoLoudly(self):
        """The skeptic's F1: the move made with no transaction (Python), recomputed: the resync
        joins the pocket's step. Undo it: the resync in the undo's regeneration (the move stayed,
        unrecorded) can't join a step (Redo isn't empty), so its writes clear Redo with a
        warning; redo then does nothing. No step in no Body, no suffixed duplicate, at any point."""
        doc = self.model()
        self.moveY(-2)
        doc.recompute()
        self.assertIs(PartDesign.studioConsumerOf(self.y), self.mir)
        self.assertEqual(doc.UndoNames, ["pocket", "mirror"])  # no "Delete" step of its own
        self.assertNoStray(self.state())

        def undoAndRecompute():
            doc.undo()
            doc.recompute()

        printed = self.consoleOutput(undoAndRecompute)
        self.assertIn("Redo cleared", printed)
        self.assertEqual(doc.RedoCount, 0)
        self.assertEqual(doc.UndoNames, ["mirror"])
        undone = self.state()
        self.assertNoStray(undone)
        self.assertIsNone(doc.getObject("E"))
        doc.redo()
        doc.recompute()
        self.assertEqual(self.state(), undone)
        self.assertNoStray(self.state())
        PartDesign.studioReconcile(self.list)

    def testBookedRecomputeMakesNoStepOfItsOwn(self):
        """Std_Refresh books "Recompute" before its recompute. With nothing stale it records
        only outputs and is set aside for the signal, then dropped at its close: no step. After
        an unrecorded move its recompute writes Mir's consumption record, an input: "Recompute"
        is a step, and the resync records into it, beside the record (no "Delete" step of its
        own, no step in no Body)."""
        doc = self.model()
        App.setActiveTransaction("Recompute")
        doc.getObject("ESk").touch()
        doc.recompute()
        App.closeActiveTransaction()
        self.assertEqual(doc.UndoNames, ["pocket", "mirror"])
        self.moveY(-2)
        App.setActiveTransaction("Recompute")
        doc.recompute()
        App.closeActiveTransaction()
        self.assertIs(PartDesign.studioConsumerOf(self.y), self.mir)
        self.assertIsNone(PartDesign.studioStepOf(self.e, self.y))
        self.assertEqual(doc.UndoNames, ["Recompute", "pocket", "mirror"])
        self.assertNoStray(self.state())

    def testObserverCreatingDuringTheResyncRecordsIntoTheSameStep(self):
        """Y moved in its own step (consumed), then moved back committed and recomputed: the
        resync makes E's step in Y again. A document observer that creates an object when it sees
        that step created records into the same step: undo takes both away."""
        doc = self.model()
        doc.openTransaction("move")
        self.moveY(-2)
        doc.recompute()
        doc.commitTransaction()
        consumed = self.state()
        self.assertIsNone(PartDesign.studioStepOf(self.e, self.y))
        test = self

        class Observer:
            made = []

            def slotCreatedObject(self, obj):
                if obj.Document == test.doc and obj.Name.startswith("E_at_") and not self.made:
                    self.made.append(test.doc.addObject("App::DocumentObjectGroup", "Witness"))

        self.observer = Observer()
        App.addDocumentObserver(self.observer)
        doc.openTransaction("back")
        self.moveY(0)
        doc.commitTransaction()
        doc.recompute()
        App.removeDocumentObserver(self.observer)
        self.observer = None
        self.assertIsNotNone(PartDesign.studioStepOf(self.e, self.y))
        self.assertIsNotNone(doc.getObject("Witness"))
        self.assertEqual(doc.UndoNames, ["back", "move", "pocket", "mirror"])
        doc.undo()
        doc.recompute()
        self.assertIsNone(doc.getObject("Witness"))
        self.assertEqual(self.state(), consumed)
        self.assertEqual(doc.UndoNames, ["move", "pocket", "mirror"])

    def testPlainRecomputeLeavesTheUndoStackAsItWas(self):
        """Nothing stale: a recompute after a touch leaves the undo steps as they were (count and
        names), and undoing the last one still undoes the whole pocket."""
        doc = self.model()
        pre = self.state()
        doc.openTransaction("noop")
        doc.commitTransaction()
        self.doc.getObject("ESk").touch()
        doc.recompute()
        self.assertEqual(doc.UndoNames, ["pocket", "mirror"])
        self.assertEqual(doc.UndoCount, 2)
        self.assertEqual(doc.RedoCount, 0)
        self.assertEqual(self.state(), pre)
        doc.undo()
        doc.recompute()
        self.assertIsNone(doc.getObject("E"))
        self.assertIsNone(doc.getObject("E_at_Y"))
        self.assertEqual(doc.UndoNames, ["mirror"])
        doc.redo()
        doc.recompute()
        self.assertEqual(self.state(), pre)


if __name__ == "__main__":
    unittest.main()
