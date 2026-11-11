# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (P5): Boolean between parts
#
# A Boolean studio feature (owner) is a PartDesign::Boolean in the studio, outside every Body, held
# by the studio's list: its targets are its StudioScope and its tools its StudioTools (part ids).
# Onshape's Boolean (notes/onshape-facts.md O3, O9b): Subtract cuts the tools from each target, each
# target keeping its id; Union merges the parts listed (targets, then tools) into the first, which
# keeps its id; Keep tools off, the tool parts are consumed at the Boolean's place: no part from
# there on (not live, a later pick of one resolves to nothing, its Body hidden), live again before
# it (the bar above it, the Boolean suppressed or deleted). Intersect between parts makes a new part
# in Onshape, which waits for P6p: refused loudly.
#
# Designed geometry only: 10 mm boxes A (x 0..10), B (x 5..15, overlapping A by 500) and C
# (x 40..50), each a Body with a sketch and a Pad. Expected volumes come from the boxes.

import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests.TestStudioList import makeOwner, newStudio, studioList

PARTS = (("A", 0), ("B", 5), ("C", 40))


def booleanOwner(doc, studio, name, kind, targets=(), tools=(), keep=False, index=-1):
    """A Boolean studio feature of Type kind (Fuse, Cut, Common), listed at index (-1: the bar)."""
    owner = doc.addObject("PartDesign::Boolean", name)
    studio.addObject(owner)
    owner.Type = kind
    owner.KeepTools = keep
    owner.StudioScope = list(targets)
    owner.StudioTools = list(tools)
    PartDesign.studioInsert(owner, index)
    return owner


class TestBooleanScope(unittest.TestCase):
    def setUp(self):
        self.doc, self.studio = newStudio("TestBooleanScope", PARTS)
        self.list = studioList(self.doc)
        self.dir = None

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestBooleanScope"):
                App.closeDocument(doc.Name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def boolean(self, name="Bool", kind="Cut", targets=("A",), tools=("B",), keep=False):
        self.doc.openTransaction("boolean")
        owner = booleanOwner(self.doc, self.studio, name, kind, targets, tools, keep)
        self.doc.commitTransaction()
        self.doc.recompute()
        return owner

    def volume(self, part):
        return self.doc.getObject(part).Shape.Volume

    def assertVolume(self, part, expected):
        self.assertAlmostEqual(self.volume(part), expected, places=3, msg=part)

    def live(self):
        return sorted(b.Name for b in PartDesign.studioLiveParts(self.list))

    def step(self, owner, part):
        return PartDesign.studioStepOf(owner, self.doc.getObject(part))

    def assertConsumed(self, part, by):
        body = self.doc.getObject(part)
        self.assertNotIn(part, self.live())
        self.assertIs(PartDesign.studioConsumerOf(body), by)
        self.assertFalse(body.Visibility, part + " stays shown")

    def assertLive(self, part):
        body = self.doc.getObject(part)
        self.assertIn(part, self.live())
        self.assertIsNone(PartDesign.studioConsumerOf(body))
        self.assertTrue(body.Visibility, part + " stays hidden")

    # ------------------------------------------------------------------------------- Subtract
    def testSubtractOneTargetOneToolConsumesTheTool(self):
        """O3: Subtract target A, tool B: A keeps its id, 1000 - 500; B is consumed."""
        b = self.boolean()
        self.assertTrue(b.isValid(), b.getStatusString())
        self.assertTrue(b.Shape.isNull())
        step = self.step(b, "A")
        self.assertIsNotNone(step)
        self.assertEqual(step.TypeId, "PartDesign::FeatureApply")
        self.assertEqual(step.Operation, "Subtraction")
        self.assertTrue(step.isValid(), step.getStatusString())
        self.assertIs(self.doc.getObject("A").Tip, step)
        self.assertVolume("A", 500)
        self.assertEqual(len(self.doc.getObject("A").Shape.Solids), 1)
        self.assertIsNone(self.step(b, "B"))
        self.assertEqual(PartDesign.studioPartId(self.doc.getObject("A")), "A")
        self.assertConsumed("B", b)
        self.assertEqual(self.live(), ["A", "C"])
        self.assertVolume("C", 1000)

    def testSubtractKeepToolsKeepsTheTool(self):
        """O3: Keep tools on, B stays a part, unchanged."""
        b = self.boolean(keep=True)
        self.assertVolume("A", 500)
        self.assertLive("B")
        self.assertVolume("B", 1000)
        self.assertEqual(self.live(), ["A", "B", "C"])
        # Off again: consumed, hidden
        self.doc.openTransaction("keep off")
        b.KeepTools = False
        PartDesign.studioReconcile(self.list)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertConsumed("B", b)
        self.assertVolume("A", 500)

    def testToolIsItsPartAtTheBooleansPlace(self):
        """The tool is B as it is just before the Boolean: a fuse on B after it doesn't reach A;
        moved before it, it does."""
        b = self.boolean(keep=True)
        grow = makeOwner(self.doc, self.studio, "Grow", (12, 0, 18, 10), 0, "Union", ("B",))
        grow.Length, grow.Width, grow.Height = 6, 10, 10  # x 12..18, z 0..10: B becomes x 5..18
        grow.Placement = App.Placement(App.Vector(12, 0, 0), App.Rotation())
        self.doc.openTransaction("grow")
        PartDesign.studioInsert(grow, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume("B", 1300)
        self.assertVolume("A", 500)
        self.doc.openTransaction("move")
        PartDesign.studioMove(grow, self.list.Entries.index(b))
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertLess(self.list.Entries.index(grow), self.list.Entries.index(b))
        self.assertVolume("B", 1300)
        self.assertVolume("A", 500)  # the grown part is x 10..18 beyond A: A loses the same 500
        # A tool that grows into A before the Boolean cuts more of A
        self.doc.openTransaction("into A")
        grow.Placement = App.Placement(App.Vector(2, 0, 0), App.Rotation())  # x 2..8
        PartDesign.studioReconcile(self.list)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertVolume("A", 200)  # A keeps x 0..2

    # ------------------------------------------------------------------------------- Union
    def testUnionSurvivorIsTheFirstListed(self):
        """O3 / O9b: Union of B, A (tools listed B, A): B keeps its id, 1500; A is consumed."""
        b = self.boolean(kind="Fuse", targets=(), tools=("B", "A"))
        self.assertTrue(b.isValid(), b.getStatusString())
        self.assertIsNotNone(self.step(b, "B"))
        self.assertIsNone(self.step(b, "A"))
        self.assertEqual(self.step(b, "B").Operation, "Union")
        self.assertVolume("B", 1500)
        self.assertEqual(len(self.doc.getObject("B").Shape.Solids), 1)
        self.assertConsumed("A", b)
        self.assertEqual(self.live(), ["B", "C"])

    def testUnionTargetsComeFirst(self):
        """Targets then tools: target A, tool B: A survives."""
        b = self.boolean(kind="Fuse", targets=("A",), tools=("B",))
        self.assertIsNotNone(self.step(b, "A"))
        self.assertVolume("A", 1500)
        self.assertConsumed("B", b)

    def testUnionOfPartsApartFailsLoudly(self):
        """A Union whose only tool touches nothing it merges: Onshape keeps a tool apart a part
        of its own (P6p, A-2' b), so C stays a part, not consumed; with nothing left to merge the
        Union fails loudly (unverified on Onshape); no part changes."""
        b = self.boolean(kind="Fuse", targets=("A",), tools=("C",))
        self.assertFalse(b.isValid())
        self.assertIn("No tool part touches", b.getStatusString())
        self.assertVolume("A", 1000)
        self.assertVolume("C", 1000)
        self.assertIn("C", self.live())
        self.assertIsNone(PartDesign.studioConsumerOf(self.doc.getObject("C")))

    # ------------------------------------------------------------------------------- consumed parts
    def testPickOfAConsumedToolResolvesToNothing(self):
        """10.9: a later feature picking the consumed B: beside C, the dead pick is ignored; alone,
        the feature fails loudly."""
        b = self.boolean()
        cut = makeOwner(self.doc, self.studio, "Cut2", (6, 2, 48, 4), 2, "Subtraction", ("B", "C"))
        self.doc.openTransaction("cut")
        PartDesign.studioInsert(cut, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIsNone(self.step(cut, "B"))
        self.assertIsNotNone(self.step(cut, "C"))
        self.assertVolume("C", 1000 - 8 * 2 * 2)
        self.assertVolume("B", 1000)
        self.assertEqual([p.Name for p in PartDesign.studioScopeOf(cut)], ["C"])
        # A Boolean whose only target is the consumed part fails
        late = self.boolean("Late", targets=("B",), tools=("C",), keep=True)
        self.assertFalse(late.isValid())
        self.assertIn("Need at least one target part", late.getStatusString())
        self.assertIsNone(self.step(late, "B"))
        self.assertVolume("C", 1000 - 8 * 2 * 2)
        # And one whose only tool is it
        late2 = self.boolean("Late2", targets=("C",), tools=("B",), keep=True)
        self.assertFalse(late2.isValid())
        self.assertIn("Need at least one tool part", late2.getStatusString())

    def testBarAboveTheBooleanMakesTheToolLive(self):
        """Rolled back above the Boolean, B is a part again (shown, offered); at the end, consumed."""
        b = self.boolean()
        at = self.list.Entries.index(b)
        self.assertEqual(sorted(p.Name for p in PartDesign.studioLiveParts(self.list, at)),
                         ["A", "B", "C"])
        self.doc.openTransaction("bar")
        PartDesign.studioSetBar(self.list, at)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertLive("B")
        self.assertAlmostEqual(self.doc.getObject("A").Tip.Shape.Volume, 1000, places=3)
        self.doc.openTransaction("bar end")
        PartDesign.studioSetBar(self.list, -1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertConsumed("B", b)
        self.assertVolume("A", 500)

    def testSuppressedOrDeletedBooleanConsumesNothing(self):
        b = self.boolean()
        self.doc.openTransaction("suppress")
        PartDesign.studioSuppress(b, True)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertLive("B")
        self.assertVolume("A", 1000)
        self.doc.openTransaction("unsuppress")
        PartDesign.studioSuppress(b, False)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertConsumed("B", b)
        self.assertVolume("A", 500)
        self.doc.openTransaction("delete")
        PartDesign.studioRemove(b)
        self.doc.removeObject(b.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertLive("B")
        self.assertVolume("A", 1000)

    def testAPartTheUserHidStaysHidden(self):
        """Only a Body hidden for being consumed is shown again."""
        self.doc.getObject("C").Visibility = False
        b = self.boolean()
        self.doc.openTransaction("delete")
        PartDesign.studioRemove(b)
        self.doc.removeObject(b.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertTrue(self.doc.getObject("B").Visibility)
        self.assertFalse(self.doc.getObject("C").Visibility)

    # ------------------------------------------------------------------------------- undo, files
    def testUndoRedo(self):
        self.boolean()
        self.assertVolume("A", 500)
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("Bool"))
        self.assertLive("B")
        self.assertVolume("A", 1000)
        self.doc.redo()
        self.doc.recompute()
        b = self.doc.getObject("Bool")
        self.assertConsumed("B", b)
        self.assertVolume("A", 500)

    def testSaveAndReopen(self):
        self.boolean()
        self.dir = tempfile.mkdtemp(prefix="booleanscope")
        path = os.path.join(self.dir, "TestBooleanScopeSaved.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.doc.UndoMode = 1
        self.list = studioList(self.doc)
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        b = self.doc.getObject("Bool")
        self.assertTrue(b.isValid(), b.getStatusString())
        self.assertEqual(list(b.StudioTools), ["B"])
        self.assertVolume("A", 500)
        self.assertConsumed("B", b)
        # An edit after the reopen still drives it
        self.doc.openTransaction("keep")
        b.KeepTools = True
        PartDesign.studioReconcile(self.list)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertLive("B")

    # ------------------------------------------------------------------------------- refusals
    def testIntersectIsRefusedLoudly(self):
        """Onshape's Intersect between parts makes a new part (O3): not done yet, loud."""
        b = self.boolean(kind="Common", keep=True)
        self.assertFalse(b.isValid())
        self.assertIn("Intersect between parts", b.getStatusString())
        self.assertVolume("A", 1000)
        self.assertLive("B")

    def testNoToolFailsLoudly(self):
        b = self.boolean(tools=())
        self.assertFalse(b.isValid())
        self.assertIn("Need at least one tool part", b.getStatusString())
        self.assertVolume("A", 1000)

    def testATargetThatIsAToolFailsLoudly(self):
        b = self.boolean(targets=("A", "C"), tools=("B", "C"))
        self.assertFalse(b.isValid())
        self.assertIn("is a target and a tool", b.getStatusString())


if __name__ == "__main__":
    unittest.main()
