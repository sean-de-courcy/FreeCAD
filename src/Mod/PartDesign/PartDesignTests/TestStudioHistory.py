# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (S3): the history operations as list edits
#
# A studio with a list (PartDesign::StudioList) has the list's order and the list's bar: the
# history functions follow it (studioSequence, rollStudioTo, rollStudioToEnd, isStudioRolledBack,
# studioBarAfter, moveInStudio, studioMove), and the derived order is only for a studio without
# one. Each operation is a list edit and a reconcile in one transaction, so one undo takes list
# and chains back together; a delete or a suppress made outside the list (Std_Delete, the tree's
# toggle, Python) follows it too (notes/parts-design.md 3.2, 3.5; notes/one-history-design.md 5).
#
# Designed geometry only: TestStudioList's three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50)
# in the App::Part S, and its owners (a Part::Box in S with Operation and StudioScope: a cut box
# reaches down from the top, z 10 - depth .. 10.001; a fuse box sits on it, z 9.999 .. 10 + depth).
# Expected volumes come from Part booleans of the boxes, never from a run.

import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestStudioList import (
    NATIVES,
    PARTS,
    StudioCase,
    chainOf,
    isStep,
    makeOwner,
    newStudio,
    studioList,
)

V = App.Vector
CUT = [5, 2, 25, 8]  # over A and B


class TestStudioHistory(StudioCase):
    def setUp(self):
        self.doc, self.studio = newStudio("TestStudioHistory")
        self.list = studioList(self.doc)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestStudioHistory"):
                App.closeDocument(doc.Name)

    # -------------------------------------------------------------------------------- helpers
    def entries(self):
        return [e.Name for e in self.list.Entries]

    def chains(self):
        return {p: chainOf(self.doc.getObject(p)) for p, _ in PARTS}

    def tips(self):
        out = {}
        for p, _ in PARTS:
            tip = self.doc.getObject(p).Tip
            out[p] = None if tip is None else tip.StudioOwner.Name if isStep(tip) else tip.Name
        return out

    def tipVolume(self, part):
        """The part's volume at the bar: its Tip's (a rolled-back Body keeps its Shape, ops#127)"""
        tip = self.doc.getObject(part).Tip
        return 0.0 if tip is None or tip.Shape.isNull() else tip.Shape.Volume

    def volumes(self):
        return {p: round(self.tipVolume(p), 4) for p, _ in PARTS}

    def state(self):
        return self.entries(), self.list.Bar, self.chains(), self.tips(), self.volumes()

    def transaction(self, name, edit):
        self.doc.openTransaction(name)
        try:
            edit()
            self.doc.commitTransaction()
        except Exception:
            self.doc.abortTransaction()
            raise
        self.doc.recompute()

    def assertVolumes(self, expected):
        for p, volume in expected.items():
            self.assertAlmostEqual(self.tipVolume(p), volume, places=4, msg=p)

    # ---------------------------------------------------------------------------- adoption
    def testAdoptionKeepsTheDerivedOrderThenTheListRules(self):
        """A studio's list starts as the derived order (a member made late in A comes after C's,
        not after A's own), and from then on the list is the order: C's rows dragged to the top,
        studioSequence follows the list, not the derived order, and the chains stay A's own."""
        doc, studio = newStudio("TestStudioHistoryAdopt")
        a = doc.getObject("A")
        pad(a, "APad2", sketch(a, "ASk2", xyPlane(a), (2, 2, 8, 8), z=10), 3)
        doc.recompute()
        derived = [o.Name for o in PartDesign.studioSequence(studio)]
        self.assertEqual(derived, ["ASk", "APad", "BSk", "BPad", "CSk", "CPad", "ASk2", "APad2"])
        self.assertIsNone(PartDesign.studioList(studio))
        lst = PartDesign.studioList(studio, True)
        self.assertEqual([e.Name for e in lst.Entries], derived)

        doc.openTransaction("drag")
        PartDesign.studioMove(doc.getObject("CSk"), 0)
        PartDesign.studioMove(doc.getObject("CPad"), 1)
        doc.commitTransaction()
        doc.recompute()
        moved = ["CSk", "CPad", "ASk", "APad", "BSk", "BPad", "ASk2", "APad2"]
        self.assertEqual([e.Name for e in lst.Entries], moved)
        self.assertEqual([o.Name for o in PartDesign.studioSequence(studio)], moved)
        self.assertEqual(chainOf(a), ["ASk", "APad", "ASk2", "APad2"])
        self.assertAlmostEqual(a.Shape.Volume, 1000 + 36 * 3, places=4)

    # -------------------------------------------------------------------------------- drag
    def testDragAnOwnerBelowALaterFeature(self):
        """F1 cuts A and B through where F2 bosses B (scope A and B: a no-op in A; a boss over
        both would merge them, 10.13): dragged below F2 (the Features list's drag, moveInStudio),
        every part of its scope computes F2 then F1, in one undo step; undo brings list and chains
        back together."""
        f1 = makeOwner(self.doc, self.studio, "F1", CUT, 4, "Subtraction", ["A", "B"])
        f1.Height = 14  # z 6..20: through the later boss too, so the order shows in the volume
        self.transaction("F1", lambda: PartDesign.studioInsert(f1, -1))
        f2 = self.owner("F2", [21, 1, 26, 9], 2, "Union", ["A", "B"])
        tool1 = Part.makeBox(20, 6, 14, V(5, 2, 6))
        tool2 = self.tool([21, 1, 26, 9], 2, "Union")
        cut = self.partBox("A").cut(tool1).Volume
        cutThenBoss = {"A": cut, "B": self.partBox("B").cut(tool1).fuse(tool2).Volume}
        bossThenCut = {"A": cut, "B": self.partBox("B").fuse(tool2).cut(tool1).Volume}
        self.assertGreater(abs(cutThenBoss["B"] - bossThenCut["B"]), 1)  # the case tells them apart
        self.assertVolumes(cutThenBoss)
        before = self.state()
        undo = self.doc.UndoCount

        self.transaction("drag", lambda: PartDesign.moveInStudio(self.studio, [f1], f2))
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.entries()[NATIVES:], ["F2", "F1"])
        self.assertEqual(chainOf(self.doc.getObject("A")), ["ASk", "APad", "F2", "F1"])
        self.assertEqual(chainOf(self.doc.getObject("B")), ["BSk", "BPad", "F2", "F1"])
        self.assertEqual(chainOf(self.doc.getObject("C")), ["CSk", "CPad"])
        self.assertEqual(self.tips(), {"A": "F1", "B": "F1", "C": "CPad"})
        self.assertVolumes(bossThenCut)
        self.assertVolumes({"C": 1000})

        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.state(), before)

    def testDragKeepsTheBar(self):
        """Rolled back after F2, F1 dragged to the end: the bar stays right after F2, so F1 is held
        in both its parts and F3 stays held (a bar kept by its index would take F3 in)."""
        f1 = self.owner("F1", CUT, 2, "Subtraction", ["A", "B"])
        self.owner("F2", [22, 2, 45, 8], 3, "Subtraction", ["B", "C"])
        self.owner("F3", [42, 2, 48, 4], 1, "Union", ["A", "C"])
        self.transaction("bar", lambda: PartDesign.rollStudioTo(self.studio, self.doc.getObject("F2")))
        self.assertEqual(self.list.Bar, NATIVES + 2)
        self.transaction("drag", lambda: PartDesign.studioMove(f1, NATIVES + 2))
        self.assertEqual(self.entries()[NATIVES:], ["F2", "F3", "F1"])
        self.assertEqual(self.list.Bar, NATIVES + 1)
        self.assertEqual(self.tips(), {"A": "APad", "B": "F2", "C": "F2"})
        tool2 = self.tool([22, 2, 45, 8], 3, "Subtraction")
        self.assertVolumes(
            {
                "A": 1000,
                "B": self.partBox("B").cut(tool2).Volume,
                "C": self.partBox("C").cut(tool2).Volume,
            }
        )

    def testMoveAboveWhatItReadsIsRefused(self):
        """Onshape: a feature can't go above what it reads, nor what it reads below it. F3 reads
        B's later sketch (its Profile): dragged above it, or the sketch dragged below it, the move
        is refused naming both, and nothing changes; a move that breaks no read goes through."""
        self.owner("F1", [2, 2, 4, 4], 2, "Subtraction", ["A"])
        self.transaction("boss", self.laterBoss)
        sk2 = self.doc.getObject("BSk2")
        f3 = makeOwner(self.doc, self.studio, "F3", [22, 2, 26, 6], 2, "Subtraction", ["B"])
        f3.addProperty("App::PropertyLinkGlobal", "Profile", "Studio")
        f3.Profile = sk2
        self.transaction("F3", lambda: PartDesign.studioInsert(f3, -1))
        listed = ["F1", "BSk2", "BBoss", "F3"]
        self.assertEqual(self.entries()[NATIVES:], listed)
        before = self.state()

        for edit, words in (
            (lambda: PartDesign.studioMove(f3, NATIVES), ("'F3' uses 'BSk2'", "above")),
            (lambda: PartDesign.moveInStudio(self.studio, [f3], None), ("'F3' uses 'BSk2'", "above")),
            (lambda: PartDesign.studioMove(sk2, NATIVES + 3), ("'BSk2'", "below")),
        ):
            with self.assertRaises(ValueError) as refused:
                self.transaction("refused", edit)
            for word in words:
                self.assertIn(word, str(refused.exception))
            self.assertEqual(self.state(), before)

        f1 = self.doc.getObject("F1")
        self.transaction("drag", lambda: PartDesign.studioMove(f1, NATIVES + 3))
        self.assertEqual(self.entries()[NATIVES:], ["BSk2", "BBoss", "F3", "F1"])

    # ---------------------------------------------------------------------------------- bar
    def testBarAtAnOwnerHoldsItsStepsInEveryPart(self):
        """The bar after F2 (rollStudioTo, the Features list's bar): F2 is computed in both its
        parts and F3 in neither, each Body's Tip from the list's projection, in one undo step. The
        bar after a step is after its owner: never one part cut and the other not."""
        f1 = self.owner("F1", CUT, 2, "Subtraction", ["A", "B"])
        f2 = self.owner("F2", [22, 2, 45, 8], 3, "Subtraction", ["B", "C"])
        # F3 bosses C (scope A and C: a no-op in A; a boss over both would merge them, 10.13)
        self.owner("F3", [42, 2, 48, 4], 1, "Union", ["A", "C"])
        tool1 = self.tool(CUT, 2, "Subtraction")
        tool2 = self.tool([22, 2, 45, 8], 3, "Subtraction")
        tool3 = self.tool([42, 2, 48, 4], 1, "Union")
        self.assertFalse(PartDesign.isStudioRolledBack(self.studio))
        undo = self.doc.UndoCount

        self.transaction("bar", lambda: PartDesign.rollStudioTo(self.studio, f2))
        self.assertEqual(self.doc.UndoCount, undo + 1)
        self.assertEqual(self.list.Bar, NATIVES + 2)
        self.assertTrue(PartDesign.isStudioRolledBack(self.studio))
        self.assertEqual(self.tips(), {"A": "F1", "B": "F2", "C": "F2"})
        self.assertEqual(PartDesign.studioBarAfter(self.studio).Name, "F2_at_C")
        self.assertVolumes(
            {
                "A": self.partBox("A").cut(tool1).Volume,
                "B": self.partBox("B").cut(tool1).cut(tool2).Volume,
                "C": self.partBox("C").cut(tool2).Volume,
            }
        )

        self.transaction("bar", lambda: PartDesign.rollStudioTo(self.studio, self.step(f1, "B")))
        self.assertEqual(self.list.Bar, NATIVES + 1)
        self.assertEqual(self.tips(), {"A": "F1", "B": "F1", "C": "CPad"})

        self.transaction("end", lambda: PartDesign.rollStudioToEnd(self.studio))
        self.assertEqual(self.list.Bar, -1)
        self.assertFalse(PartDesign.isStudioRolledBack(self.studio))
        self.assertEqual(self.tips(), {"A": "F3", "B": "F2", "C": "F3"})
        self.assertVolumes(
            {
                "A": self.partBox("A").cut(tool1).Volume,
                "C": self.partBox("C").cut(tool2).fuse(tool3).Volume,
            }
        )
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.list.Bar, NATIVES + 1)
        self.assertEqual(self.tips(), {"A": "F1", "B": "F1", "C": "CPad"})

    # ---------------------------------------------------------------------- suppress, delete
    def testSuppressFollowsTheOwnerAndUndoes(self):
        """The owner's Suppressed set as the tree's toggle sets it (the property, no list call):
        its steps follow in both parts in the same undo step; undo and redo take both together.
        studioSuppress (the Features list's Suppress) does the same."""
        f1 = self.owner("F1", CUT, 2, "Subtraction", ["A", "B"])
        f1.addProperty("App::PropertyBool", "Suppressed", "Studio")
        tool = self.tool(CUT, 2, "Subtraction")
        cut = {p: self.partBox(p).cut(tool).Volume for p in "AB"}
        self.assertVolumes(cut)

        self.transaction("suppress", lambda: setattr(f1, "Suppressed", True))
        self.assertTrue(all(self.step(f1, p).Suppressed for p in "AB"))
        self.assertVolumes({"A": 1000, "B": 1000})
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse(f1.Suppressed)
        self.assertFalse(any(self.step(f1, p).Suppressed for p in "AB"))
        self.assertVolumes(cut)
        self.doc.redo()
        self.doc.recompute()
        self.assertTrue(all(self.step(f1, p).Suppressed for p in "AB"))
        self.assertVolumes({"A": 1000, "B": 1000})

        self.transaction("unsuppress", lambda: PartDesign.studioSuppress(f1, False))
        self.assertFalse(any(self.step(f1, p).Suppressed for p in "AB"))
        self.assertVolumes(cut)

    def testDeleteTakesItsStepsAndKeepsTheBar(self):
        """Deleted as Std_Delete deletes (the object removed, no list call): a Body member leaves
        the list, and an owner its steps too, the bar staying after the same entries (F3 held);
        undo brings list, steps and chains back together."""
        self.owner("F1", CUT, 2, "Subtraction", ["A", "B"])
        f2 = self.owner("F2", [22, 2, 26, 6], 3, "Union", ["B"])
        self.owner("F3", [2, 4, 8, 9], 1, "Subtraction", ["A"])
        self.transaction("bar", lambda: PartDesign.rollStudioTo(self.studio, f2))
        self.transaction("boss", self.laterBoss)  # at the bar: live
        self.assertEqual(self.entries()[NATIVES:], ["F1", "F2", "BSk2", "BBoss", "F3"])
        self.assertEqual(self.list.Bar, NATIVES + 4)
        self.assertEqual(self.tips()["B"], "BBoss")
        before = self.state()
        b = self.doc.getObject("B")

        def deleteBoss():
            b.removeObject(self.doc.getObject("BBoss"))  # as its view provider's onDelete
            self.doc.removeObject("BBoss")

        self.transaction("delete boss", deleteBoss)
        self.assertEqual(self.entries()[NATIVES:], ["F1", "F2", "BSk2", "F3"])
        self.assertEqual(self.list.Bar, NATIVES + 3)
        self.assertEqual(self.tips()["A"], "F1")

        self.transaction("delete F1", lambda: self.doc.removeObject("F1"))
        self.assertIsNone(self.doc.getObject("F1_at_A"))
        self.assertIsNone(self.doc.getObject("F1_at_B"))
        self.assertEqual(self.entries()[NATIVES:], ["F2", "BSk2", "F3"])
        self.assertEqual(self.list.Bar, NATIVES + 2)
        self.assertEqual(chainOf(self.doc.getObject("A")), ["ASk", "APad", "F3"])
        self.assertEqual(chainOf(b), ["BSk", "BPad", "F2", "BSk2"])
        self.assertEqual(self.tips(), {"A": "APad", "B": "F2", "C": "CPad"})
        tool2 = self.tool([22, 2, 26, 6], 3, "Union")
        self.assertVolumes({"A": 1000, "B": self.partBox("B").fuse(tool2).Volume})

        self.doc.undo()
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(self.state(), before)
        self.assertIsNotNone(self.doc.getObject("F1_at_A"))
        self.assertIsNotNone(self.doc.getObject("F1_at_B"))

    def testDeleteRetracesAcrossTheOwner(self):
        """notes/stored-tags.md 3, item 3: a step names what its cut makes with its owner's tag.
        Datum points on the cut's rim (a vertex and two edges at z 10) as a later Pocket of A
        passes them on: the Pocket deleted as Std_Delete deletes it, each re-targets to the step,
        where the element was made, and stays computed at its place (the history stopped at the
        owner, outside A, and the readers went red)."""
        f1 = self.owner("F1", CUT, 3, "Subtraction", ["A"])
        a = self.doc.getObject("A")
        step = self.step(f1, "A")
        pocket = a.newObject("PartDesign::Pocket", "APocket")
        pocket.Profile = sketch(a, "ASk2", xyPlane(a), (1, 1, 3, 3), z=10)
        pocket.Length = 2
        self.doc.recompute()
        self.assertTrue(pocket.isValid())
        self.assertAlmostEqual(a.Shape.Volume, 1000 - 5 * 6 * 3 - 2 * 2 * 2, places=4)

        def elementAt(shape, kind, at):
            items = shape.Vertexes if kind == "Vertex" else shape.Edges
            for i, item in enumerate(items, 1):
                point = item.Point if kind == "Vertex" else item.CenterOfMass
                if point.isEqual(at, 1e-6):
                    return f"{kind}{i}"
            raise AssertionError(f"no {kind} at {at}")

        readers = {"RV": ("Vertex", V(5, 2, 10)), "RE": ("Edge", V(7.5, 2, 10)), "RX": ("Edge", V(5, 5, 10))}
        for name, (kind, at) in readers.items():
            point = a.newObject("PartDesign::Point", name)
            point.AttachmentSupport = [(pocket, elementAt(pocket.Shape, kind, at))]
            point.MapMode = "Vertex" if kind == "Vertex" else "CenterOfMass"
        self.doc.recompute()
        for name, (_, at) in readers.items():
            self.assertTrue(self.doc.getObject(name).Placement.Base.isEqual(at, 1e-6), name)

        def delete():
            a.removeObject(pocket)  # as its view provider's onDelete
            self.doc.removeObject("APocket")

        self.transaction("delete", delete)
        for name, (_, at) in readers.items():
            point = self.doc.getObject(name)
            self.assertEqual([o.Name for o, _ in point.AttachmentSupport], [step.Name], name)
            self.assertTrue(point.isValid(), name)
            self.assertTrue(point.Placement.Base.isEqual(at, 1e-6), name)

    # ------------------------------------------------------------------------------ crossing
    def testCrossingOwnersComputeInTheListsOrder(self):
        """X cuts A and B (scope A, B), Y bosses B (scope B, A: a no-op in A; a boss over both
        would merge them, 10.13): both parts compute X then Y,
        the list's order, whatever each scope's order; the bar after X holds Y in both parts; Y
        dragged above X, both compute Y then X."""
        x = makeOwner(self.doc, self.studio, "X", [5, 3, 25, 7], 2, "Subtraction", ["A", "B"])
        x.Height = 14  # z 8..22: through Y's boss too
        self.transaction("X", lambda: PartDesign.studioInsert(x, -1))
        y = self.owner("Y", [21, 2, 26, 5], 2, "Union", ["B", "A"])
        toolX = Part.makeBox(20, 4, 14, V(5, 3, 8))
        toolY = self.tool([21, 2, 26, 5], 2, "Union")
        cut = self.partBox("A").cut(toolX).Volume
        xThenY = {"A": cut, "B": self.partBox("B").cut(toolX).fuse(toolY).Volume}
        yThenX = {"A": cut, "B": self.partBox("B").fuse(toolY).cut(toolX).Volume}
        self.assertGreater(abs(xThenY["B"] - yThenX["B"]), 1)
        for p in "AB":
            self.assertEqual(chainOf(self.doc.getObject(p))[2:], ["X", "Y"], p)
        self.assertVolumes(xThenY)

        self.transaction("bar", lambda: PartDesign.rollStudioTo(self.studio, x))
        self.assertEqual(self.tips(), {"A": "X", "B": "X", "C": "CPad"})
        self.assertVolumes({p: self.partBox(p).cut(toolX).Volume for p in "AB"})
        self.transaction("end", lambda: PartDesign.rollStudioToEnd(self.studio))

        self.transaction("drag", lambda: PartDesign.studioMove(y, NATIVES))
        self.assertEqual(self.entries()[NATIVES:], ["Y", "X"])
        for p in "AB":
            self.assertEqual(chainOf(self.doc.getObject(p))[2:], ["Y", "X"], p)
        self.assertVolumes(yThenX)

    # ------------------------------------------------------- a park held through other moves
    def parkedSlot(self):
        """A's Pocket ASlot (a Body member, 2 x 6 x 3 deep) on its sketch ASlotSk, then Pads ABoss
        and ABoss2 and an owner F1 bossing A's top elsewhere. ASlot dragged above ASlotSk: its
        Profile is parked (RO1) and it fails alone, the part uncut. Returns the slot, its sketch
        and the part's volumes cut and uncut"""
        a = self.doc.getObject("A")
        slotSk = sketch(a, "ASlotSk", xyPlane(a), (2, 2, 4, 8), z=10)
        slot = a.newObject("PartDesign::Pocket", "ASlot")
        slot.Profile = slotSk
        slot.Length = 3
        self.transaction("slot", lambda: PartDesign.studioInsert(slotSk, -1))
        bossSk = sketch(a, "ABossSk", xyPlane(a), (6, 6, 8, 8), z=10)
        pad(a, "ABoss", bossSk, 3)
        self.transaction("boss", lambda: PartDesign.studioInsert(bossSk, -1))
        boss2Sk = sketch(a, "ABoss2Sk", xyPlane(a), (6, 0.5, 8, 1.5), z=10)
        pad(a, "ABoss2", boss2Sk, 1)
        self.transaction("boss2", lambda: PartDesign.studioInsert(boss2Sk, -1))
        self.owner("F1", [6, 2, 8, 4], 2, "Union", ["A"])
        self.assertEqual(
            self.entries()[NATIVES:],
            ["ASlotSk", "ASlot", "ABossSk", "ABoss", "ABoss2Sk", "ABoss2", "F1"],
        )
        uncut = (
            self.partBox("A")
            .fuse(Part.makeBox(2, 2, 3, V(6, 6, 10)))
            .fuse(Part.makeBox(2, 1, 1, V(6, 0.5, 10)))
            .fuse(self.tool([6, 2, 8, 4], 2, "Union"))
        )
        cut = uncut.cut(Part.makeBox(2, 6, 3, V(2, 2, 7)))
        self.assertVolume("A", cut.Volume)

        self.transaction("up", lambda: PartDesign.studioMove(slot, NATIVES))
        self.assertParked(slot, uncut.Volume)
        return slot, slotSk, cut.Volume, uncut.Volume

    def assertParked(self, slot, uncut):
        names = self.entries()
        self.assertLess(names.index("ASlot"), names.index("ASlotSk"))
        self.assertFalse(slot.Profile)
        self.assertIn("Invalid", slot.State)
        self.assertVolume("A", uncut)

    def assertParkHeldThenPutBack(self, slot, slotSk, cut, uncut):
        """ops#853 (Onshape: a feature moved above its sketch stays in error until it's moved
        back): the park holds after an unrelated move and a full recompute, as a fresh build of
        that order; the sketch dragged back above the slot gives the Profile back"""
        self.assertParked(slot, uncut)
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        self.assertParked(slot, uncut)

        self.transaction("back", lambda: PartDesign.studioMove(slotSk, NATIVES))
        self.assertEqual(self.entries()[NATIVES : NATIVES + 2], ["ASlotSk", "ASlot"])
        self.assertIs(slot.Profile[0], slotSk)
        self.assertNotIn("Invalid", slot.State)
        self.assertVolume("A", cut)

    def testParkHeldWhenAnOwnerMoves(self):
        """The unrelated move is an owner's: F1 dragged above ABoss (its step alone moves in A's
        chain)."""
        slot, slotSk, cut, uncut = self.parkedSlot()
        f1 = self.doc.getObject("F1")
        self.transaction("F1 up", lambda: PartDesign.studioMove(f1, NATIVES + 2))
        self.assertEqual(
            self.entries()[NATIVES + 2 :], ["F1", "ABossSk", "ABoss", "ABoss2Sk", "ABoss2"]
        )
        self.assertParkHeldThenPutBack(slot, slotSk, cut, uncut)

    def testParkHeldWhenABodyMemberMoves(self):
        """The unrelated move is a Body member's: ABoss dragged below ABoss2, so A's chain is
        reordered (Body::reorderObject(), whose rule once gave the parked Profile back)."""
        slot, slotSk, cut, uncut = self.parkedSlot()
        boss = self.doc.getObject("ABoss")
        self.transaction("boss down", lambda: PartDesign.studioMove(boss, NATIVES + 5))
        self.assertEqual(
            self.entries()[NATIVES + 2 :], ["ABossSk", "ABoss2Sk", "ABoss2", "ABoss", "F1"]
        )
        solids = [n for n in chainOf(self.doc.getObject("A")) if not n.endswith("Sk")]
        self.assertEqual(solids, ["APad", "ASlot", "ABoss2", "ABoss", "F1"])
        self.assertParkHeldThenPutBack(slot, slotSk, cut, uncut)


    def testParkedProjectionHeldThenPutBack(self):
        """ops#853 for a projection: AProjSk projects an edge of the sketch ASlotSk (a sketch of
        the same Body, no solid). Dragged above it, the projection is parked; an unrelated Body
        reorder (ABoss below ABoss2) leaves it parked; ASlotSk dragged back above gives it back."""
        a = self.doc.getObject("A")
        slotSk = sketch(a, "ASlotSk", xyPlane(a), (2, 2, 4, 8), z=10)
        self.transaction("slot", lambda: PartDesign.studioInsert(slotSk, -1))
        proj = sketch(a, "AProjSk", xyPlane(a), z=10)
        proj.addExternal("ASlotSk", "Edge1")
        self.transaction("proj", lambda: PartDesign.studioInsert(proj, -1))
        for name, rect, height in (("ABoss", (6, 6, 8, 8), 3), ("ABoss2", (6, 0.5, 8, 1.5), 1)):
            sk = sketch(a, name + "Sk", xyPlane(a), rect, z=10)
            pad(a, name, sk, height)
            self.transaction(name, lambda sk=sk: PartDesign.studioInsert(sk, -1))
        self.doc.recompute()
        names = ["ASlotSk", "AProjSk", "ABossSk", "ABoss", "ABoss2Sk", "ABoss2"]
        self.assertEqual(self.entries()[NATIVES:], names)

        def projected():
            return {link[0].Name for link in proj.ExternalGeometry if link and link[0]}

        self.assertEqual(projected(), {"ASlotSk"})

        self.transaction("up", lambda: PartDesign.studioMove(proj, NATIVES))
        self.assertEqual(self.entries()[NATIVES : NATIVES + 2], ["AProjSk", "ASlotSk"])
        self.assertEqual(projected(), set())

        boss = self.doc.getObject("ABoss")
        self.transaction("boss down", lambda: PartDesign.studioMove(boss, NATIVES + 5))
        self.assertEqual(self.entries()[NATIVES + 3 :], ["ABoss2Sk", "ABoss2", "ABoss"])
        self.doc.recompute()
        self.assertEqual(projected(), set())

        self.transaction("back", lambda: PartDesign.studioMove(slotSk, NATIVES))
        self.assertEqual(self.entries()[NATIVES : NATIVES + 2], ["ASlotSk", "AProjSk"])
        self.assertEqual(projected(), {"ASlotSk"})
        self.doc.recompute()
        self.assertTrue(proj.isValid())

if __name__ == "__main__":
    unittest.main()
