# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Undo, redo and regeneration (FreeCAD-CH ops#640; work/sd03f/regen-design.md, plan items 1-6, 8).

Onshape's behaviour is the bar (decision 276; the user's answers, notes/onshape-experiment.md
section 6): an edit regenerates the model when it is committed, undo and redo give the
regenerated state at once; with a feature dialog open nothing undoes behind it; an unchanged
accept leaves no undo step; a failed feature contributes nothing.

- TestRegenerate: with the document's RegenerateOnCommit on (the Gui sets it; FreeCADCmd suites
  keep their own recompute() calls), a committed transaction (Document.commitTransaction(), the
  dialog's path, and App.closeActiveTransaction(False, tid), the sketcher's), an abort, an undo,
  a redo and a Suppress toggle leave nothing to recompute and the volumes right, without a
  recompute() call; one regeneration heals the dependants after an undo of a delete or an
  unsuppress (F34); the step lock (the open dialog) refuses undo, redo and a new transaction and
  lets the dialog's own commit and abort through (F6, J1's block); a transaction that changed no
  input leaves no step (F13, J8).
- TestPatternWithoutOriginals: a pattern whose originals went stays in the solid chain, fails
  with "Select features to pattern" and passes its base through (F3).
- TestStoppedBody: a Body whose first feature fails with nothing to pass through keeps its error
  and has an empty Shape (F37).

Designed model (as TestRollBackBarGui): a 20 x 20 x 10 block on XY; a 4 x 4 x 5 boss at
x, y 1..5 on its top, its sketch attached to the block's top face; a hole of radius 2, 3 deep, at
(12, 12) in the top, its sketch attached to the same face; a fillet of radius 1 on the block's
vertical edge at (20, 0). Every volume is computed from these numbers."""

import math
import unittest

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector
TOL = 1e-6

HOLE = math.pi * 2**2 * 3  # the hole: radius 2, 3 deep
ROUND = 1 - math.pi / 4  # a radius-1 fillet removes this much per mm of its edge


def total(length=10, boss=5, withBoss=True, withHole=True, withFillet=True):
    """The model's volume for a block `length` high and a boss `boss` high."""
    volume = 400 * length
    if withBoss:
        volume += 16 * boss
    if withHole:
        volume -= HOLE
    if withFillet:
        volume -= ROUND * length
    return volume


def topFace(feature, z):
    """The name of the feature's planar face facing +Z at height z."""
    for i, face in enumerate(feature.Shape.Faces, 1):
        if face.Surface.TypeId != "Part::GeomPlane":
            continue
        if face.normalAt(0, 0).isEqual(V(0, 0, 1), TOL) and abs(face.CenterOfMass.z - z) < TOL:
            return f"Face{i}"
    raise AssertionError(f"{feature.Name} has no top face at z = {z}")


def verticalEdge(feature, x, y):
    """The name of the feature's vertical straight edge at (x, y)."""
    for i, edge in enumerate(feature.Shape.Edges, 1):
        box = edge.BoundBox
        if (
            abs(box.XMin - x) < TOL
            and abs(box.XMax - x) < TOL
            and abs(box.YMin - y) < TOL
            and abs(box.YMax - y) < TOL
            and box.ZLength > 1
        ):
            return f"Edge{i}"
    raise AssertionError(f"{feature.Name} has no vertical edge at ({x}, {y})")


class RegenerateModel:
    """The designed model and the helpers both TestRegenerate and TestRegenerateGui use."""

    def build(self, fillet=True):
        """Block, Boss, Hole and (unless fillet is False) Fillet, computed once."""
        doc = self.doc
        self.body = models.body(doc)
        self.blockSketch = models.sketch(
            doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body
        )
        self.block = models.pad(self.body, self.blockSketch, 10, "Block")
        doc.recompute()
        self.bossSketch = self.sketchOnTop("BossSketch", models.rectangle(1, 1, 5, 5))
        self.boss = models.pad(self.body, self.bossSketch, 5, "Boss")
        self.holeSketch = self.sketchOnTop("HoleSketch", [models.circle(12, 12, 2)])
        self.hole = models.pocket(self.body, self.holeSketch, 3, "Hole")
        doc.recompute()
        self.fillet = self.addFillet() if fillet else None
        doc.recompute()

    def sketchOnTop(self, name, geometry):
        """A sketch attached to the block's top face; the geometry is given in global x, y."""
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(self.block, topFace(self.block, 10))]
        sketch.MapMode = "FlatFace"
        self.doc.recompute()
        local = sketch.getGlobalPlacement().inverse()
        for geo in geometry:
            moved = geo.copy()
            moved.transform(local.toMatrix())
            sketch.addGeometry(moved, False)
        return sketch

    def addFillet(self):
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (self.hole, [verticalEdge(self.hole, 20, 0)])
        fillet.Radius = 1
        return fillet

    def features(self):
        return [
            f
            for f in (
                self.blockSketch,
                self.block,
                self.bossSketch,
                self.boss,
                self.holeSketch,
                self.hole,
                self.fillet,
            )
            if f is not None
        ]

    # -- assertions ------------------------------------------------------------------------------

    def assertVolume(self, obj, volume, msg=None):
        self.assertAlmostEqual(obj.Shape.Volume, volume, delta=1e-4, msg=msg or obj.Name)

    def assertRegenerated(self, volume, msg=None):
        """Nothing left to recompute, every object valid and not touched, the Body at volume."""
        self.assertFalse(self.doc.mustExecute(), msg or "the document still needs a recompute")
        for obj in self.features() + [self.body]:
            self.assertTrue(obj.isValid(), f"{obj.Name}: {obj.getStatusString()}")
            self.assertNotIn("Touched", obj.State, obj.Name)
        self.assertVolume(self.body, volume, msg)


class TestRegenerate(RegenerateModel, unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("Regenerate")
        self.doc.UndoMode = 1
        self.others = []
        self.build()
        self.assertRegenerated(total())
        self.regenerate(True)

    def tearDown(self):
        if hasattr(self.doc, "isStepLocked"):
            while self.doc.isStepLocked():
                self.doc.unlockStep()
        for doc in [self.doc] + self.others:
            App.closeDocument(doc.Name)

    # -- the transactions, as the Gui's paths run them -------------------------------------------

    def regenerate(self, on, doc=None):
        (doc or self.doc).RegenerateOnCommit = on

    def edit(self, name, change):
        """One committed step: open, change, commit (Document.commitTransaction(), as a dialog's
        OK)."""
        self.doc.openTransaction(name)
        change()
        self.doc.commitTransaction()

    def setLength(self, feature, length):
        return lambda: setattr(feature, "Length", length)

    # -- item 4: regenerate on close and after undo and redo (F17, F32, F33) ----------------------

    def testOffUnlessTheDocumentAsks(self):
        """A document doesn't regenerate on commit unless RegenerateOnCommit is set (the Gui sets
        it on its documents; FreeCADCmd suites keep their own recompute() calls)."""
        if App.GuiUp:
            self.skipTest("a Gui document sets RegenerateOnCommit itself")
        other = models.newDocument("RegenerateOff")
        self.others.append(other)
        self.assertFalse(other.RegenerateOnCommit)
        self.regenerate(False)
        self.edit("Edit Boss", self.setLength(self.boss, 8))
        self.assertTrue(self.doc.mustExecute())
        self.assertVolume(self.body, total())

    def testCommitRegenerates(self):
        """A committed Length change: the Body has the new volume with no recompute() call, and
        the regeneration added no step."""
        self.edit("Edit Boss", self.setLength(self.boss, 8))
        self.assertRegenerated(total(boss=8))
        self.assertEqual(self.doc.UndoNames, ["Edit Boss"])
        self.assertFalse(self.doc.HasPendingTransaction)

    def testGroupedCommitRegeneratesEveryDocument(self):
        """Two documents changed under one transaction id and closed through the Application
        (Gui::Command::commitCommand's path, the sketcher's): both regenerate."""
        other, otherBody, plate = self.otherPlate("RegenerateOther")
        self.closeGrouped(lambda: setattr(plate, "Length", 3))
        self.assertRegenerated(total(boss=8))
        self.assertFalse(other.mustExecute())
        self.assertAlmostEqual(otherBody.Shape.Volume, 300, delta=1e-4)
        self.assertEqual(self.doc.UndoNames, ["Grouped"])
        self.assertEqual(other.UndoNames, ["Grouped"])

    def closeGrouped(self, otherChange):
        """The boss to 8 here and otherChange() in the other document, under one Application
        transaction "Grouped", closed through App.closeActiveTransaction. A failed assertion
        before the close aborts the transaction, so later tests don't book its id."""
        App.setActiveDocument("")  # no active document: the id is the Application's
        tid = 0
        closed = False
        try:
            tid = App.setActiveTransaction("Grouped")
            self.assertTrue(tid)
            self.boss.Length = 8
            otherChange()
            self.assertTrue(self.doc.HasPendingTransaction)
            App.closeActiveTransaction(False, tid)
            closed = True
        finally:
            if tid and not closed:
                App.closeActiveTransaction(True, tid)
            App.setActiveDocument(self.doc.Name)

    def otherPlate(self, name):
        other = models.newDocument(name)
        self.others.append(other)
        other.UndoMode = 1
        otherBody = models.body(other)
        otherSketch = models.sketch(other, "PlateSketch", models.rectangle(0, 0, 10, 10), otherBody)
        plate = models.pad(otherBody, otherSketch, 2, "Plate")
        other.recompute()
        self.assertAlmostEqual(otherBody.Shape.Volume, 200, delta=1e-4)
        self.regenerate(True, other)
        return other, otherBody, plate

    def testGroupedNoOpPartIsKept(self):
        """Under one transaction id, this document's change is real and the other's goes there
        and back (Length 2 -> 3 -> 2): the other document keeps its step, since the id marks a
        change elsewhere (Document::transactionSharedElsewhere, design 2(ii)); both regenerate."""
        other, otherBody, plate = self.otherPlate("RegenerateShared")

        def there_and_back():
            plate.Length = 3
            plate.Length = 2

        self.closeGrouped(there_and_back)
        self.assertRegenerated(total(boss=8))
        self.assertAlmostEqual(otherBody.Shape.Volume, 200, delta=1e-4)
        self.assertEqual(self.doc.UndoNames, ["Grouped"])
        self.assertEqual(other.UndoNames, ["Grouped"])

    def testImplicitCommitDoesNotRegenerate(self):
        """A transaction opened while another is open commits the first one implicitly: that
        commit doesn't regenerate (design 1(b): only the close of a step does, and the
        TransactionSignaller guard in Application::closeActiveTransaction). The explicit commit
        of the second one does."""
        self.doc.openTransaction("A")
        self.boss.Length = 8
        self.doc.openTransaction("B")
        self.block.Length = 12
        self.assertEqual(self.doc.UndoNames, ["B", "A"])
        self.assertTrue(self.doc.mustExecute(), "the implicit commit of A regenerated")
        self.assertVolume(self.body, total())
        self.doc.commitTransaction()
        self.assertRegenerated(total(length=12, boss=8))
        self.assertEqual(self.doc.UndoNames, ["B", "A"])

    def testAbortRegenerates(self):
        """An aborted transaction (a dialog's Cancel) restores the values and regenerates: nothing
        stays touched, no step, no redo entry."""
        self.doc.openTransaction("Edit Boss")
        self.boss.Length = 8
        self.doc.recompute()  # the dialog's preview
        self.assertVolume(self.body, total(boss=8))
        self.doc.abortTransaction()
        self.assertAlmostEqual(self.boss.Length.Value, 5, places=6)
        self.assertRegenerated(total())
        self.assertEqual(self.doc.UndoCount, 0)
        self.assertEqual(self.doc.RedoCount, 0)

    def testUndoAndRedoRegenerate(self):
        """Undo and redo of a Length edit give the regenerated volumes at once; the regenerations
        add no step and keep the redo entry."""
        self.edit("Edit Boss", self.setLength(self.boss, 8))
        self.edit("Edit Block", self.setLength(self.block, 12))
        self.assertRegenerated(total(length=12, boss=8))

        self.doc.undo()
        self.assertRegenerated(total(length=10, boss=8), "after the first undo")
        self.doc.undo()
        self.assertRegenerated(total(), "after the second undo")
        self.assertEqual(self.doc.RedoNames, ["Edit Boss", "Edit Block"])
        self.assertEqual(self.doc.UndoCount, 0)

        self.doc.redo()
        self.assertRegenerated(total(boss=8), "after the first redo")
        self.doc.redo()
        self.assertRegenerated(total(length=12, boss=8), "after the second redo")
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Edit Boss"])
        self.assertEqual(self.doc.RedoCount, 0)

    def testSuppressRegeneratesBothWays(self):
        """Suppress and Unsuppress (Std_ToggleSuppress's transaction): the Body loses the boss at
        once and gets it back at once (F32). The undo of each regenerates too."""
        self.edit("Toggle suppress", lambda: setattr(self.boss, "Suppressed", True))
        self.assertFalse(self.doc.mustExecute())
        self.assertVolume(self.body, total(withBoss=False))
        self.edit("Toggle suppress", lambda: setattr(self.boss, "Suppressed", False))
        self.assertRegenerated(total())
        self.doc.undo()
        self.assertFalse(self.doc.mustExecute())
        self.assertVolume(self.body, total(withBoss=False))
        self.doc.undo()
        self.assertRegenerated(total())

    # -- item 5: one regeneration heals the dependants (F34) ---------------------------------------

    def deleteBlock(self):
        self.doc.openTransaction("Delete")
        self.body.removeObject(self.block)
        self.doc.removeObject(self.block.Name)
        self.doc.commitTransaction()

    def testUndoOfADeleteHealsInOnePass(self):
        """The block deleted (its sketches lose their face, the boss becomes the first solid),
        then the delete undone: the one regeneration after the undo leaves every dependant valid
        and nothing touched, with the whole model's volume (J6, J7)."""
        self.deleteBlock()
        self.assertIsNone(self.doc.getObject("Block"))
        self.doc.undo()
        self.block = self.doc.getObject("Block")
        self.assertIsNotNone(self.block)
        self.assertRegenerated(total())
        self.assertIs(self.body.Tip, self.fillet)

    def testUnsuppressHealsInOnePass(self):
        """The block (the first feature) suppressed, then unsuppressed: one regeneration after the
        unsuppress leaves the boss, the hole, the fillet, their sketches and the Body valid (J13).
        The suppressed state itself is hands-on (#4) and not asserted."""
        self.edit("Toggle suppress", lambda: setattr(self.block, "Suppressed", True))
        self.edit("Toggle suppress", lambda: setattr(self.block, "Suppressed", False))
        self.assertRegenerated(total())
        self.doc.undo()  # suppressed again
        self.doc.redo()  # and unsuppressed by the redo
        self.assertRegenerated(total(), "after the redo of the unsuppress")

    # -- item 1: the step lock (F6, J1's block, F35) -----------------------------------------------

    def openLockedEdit(self):
        """A prior step "Edit Boss", then the block's dialog: "Edit Block" open with Length 12 and
        the step locked, as Gui::Document::setEdit leaves it."""
        self.edit("Edit Boss", self.setLength(self.boss, 8))
        self.doc.openTransaction("Edit Block")
        self.block.Length = 12
        self.doc.lockStep()
        self.assertTrue(self.doc.isStepLocked())

    def testStepLockRefusesUndoAndRedo(self):
        """Locked, undo() changes nothing: the open edit isn't committed behind the dialog and the
        step before it stays (F6). The dialog's commit passes while locked and leaves one step;
        still locked, undo is refused; unlocked, it works; locked again, redo is refused."""
        self.openLockedEdit()
        self.assertFalse(self.doc.undo())
        self.assertAlmostEqual(self.block.Length.Value, 12, places=6)
        self.assertAlmostEqual(self.boss.Length.Value, 8, places=6)
        self.assertTrue(self.doc.HasPendingTransaction)
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Edit Boss"])
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertFalse(self.doc.redo())

        self.doc.commitTransaction()  # the dialog's OK, before its resetEdit releases the lock
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Edit Boss"])
        self.assertRegenerated(total(length=12, boss=8))
        self.assertFalse(self.doc.undo())
        self.assertAlmostEqual(self.block.Length.Value, 12, places=6)

        self.doc.unlockStep()
        self.assertFalse(self.doc.isStepLocked())
        self.doc.undo()
        self.assertAlmostEqual(self.block.Length.Value, 10, places=6)
        self.assertEqual(self.doc.RedoNames, ["Edit Block"])
        self.doc.lockStep()
        self.assertFalse(self.doc.redo())
        self.assertAlmostEqual(self.block.Length.Value, 10, places=6)
        self.assertEqual(self.doc.RedoNames, ["Edit Block"])
        self.doc.unlockStep()
        self.doc.redo()
        self.assertRegenerated(total(length=12, boss=8))

    def testStepLockRefusesANewTransaction(self):
        """Locked, neither Document.openTransaction() nor App.setActiveTransaction() opens a
        transaction beside the dialog's or commits it: a change made meanwhile joins the open edit,
        and one undo takes both back."""
        self.openLockedEdit()
        self.assertFalse(self.doc.openTransaction("Beside"))
        App.setActiveDocument(self.doc.Name)
        self.assertFalse(App.setActiveTransaction("Beside too"))
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Edit Boss"])
        self.boss.Length = 6
        self.doc.commitTransaction()
        self.doc.unlockStep()
        self.assertEqual(self.doc.UndoNames, ["Edit Block", "Edit Boss"])
        self.assertRegenerated(total(length=12, boss=6))
        self.doc.undo()
        self.assertAlmostEqual(self.block.Length.Value, 10, places=6)
        self.assertAlmostEqual(self.boss.Length.Value, 8, places=6)
        self.assertRegenerated(total(boss=8))

    def testStepLockLetsTheDialogAbort(self):
        """Locked, the dialog's Cancel (abortTransaction) passes: the values are back, no step, no
        redo entry, nothing touched."""
        self.openLockedEdit()
        self.doc.abortTransaction()
        self.assertFalse(self.doc.HasPendingTransaction)
        self.assertAlmostEqual(self.block.Length.Value, 10, places=6)
        self.assertEqual(self.doc.UndoNames, ["Edit Boss"])
        self.assertEqual(self.doc.RedoCount, 0)
        self.assertRegenerated(total(boss=8))

    def testStepLockCounts(self):
        """The lock is a counter (a reset-and-set of the edit nests it): two locks need two
        unlocks."""
        self.doc.lockStep()
        self.doc.lockStep()
        self.doc.unlockStep()
        self.assertTrue(self.doc.isStepLocked())
        self.doc.unlockStep()
        self.assertFalse(self.doc.isStepLocked())
        self.doc.unlockStep()  # an extra unlock is harmless
        self.assertFalse(self.doc.isStepLocked())

    # -- item 8: a no-op edit leaves no step (F13, J8) ---------------------------------------------

    def testUnchangedInputsLeaveNoStep(self):
        """An edit whose inputs end as they began (Length 5 -> 7 -> 5) leaves no step. (The Redo
        stack is not asserted: a transaction clears it when it opens, at its first change,
        Document::_openTransaction; the design promises only "no step".)"""

        def there_and_back():
            self.boss.Length = 7
            self.boss.Length = 5

        self.edit("Edit Boss", there_and_back)
        self.assertEqual(self.doc.UndoCount, 0)
        self.assertRegenerated(total())

    def testResultOnlyChangeLeavesNoStep(self):
        """An unchanged accept: the dialog's preview recomputed the feature (its Shape changed) and
        the edit hid the base (Visibility, an output): no step."""
        self.edit("Edit Boss", self.setLength(self.boss, 8))

        def preview():
            self.boss.recompute()  # the preview (Document::recomputeFeature)
            self.block.Visibility = not self.block.Visibility

        self.edit("Edit Boss", preview)
        self.assertEqual(self.doc.UndoNames, ["Edit Boss"])
        self.assertRegenerated(total(boss=8))

    def testInputChangeLeavesOneStep(self):
        """A Length change with the preview's recompute: one step, whose undo restores the
        Length."""
        def change():
            self.boss.Length = 8
            self.boss.recompute()  # the preview (Document::recomputeFeature)

        self.edit("Edit Boss", change)
        self.assertEqual(self.doc.UndoNames, ["Edit Boss"])
        self.doc.undo()
        self.assertAlmostEqual(self.boss.Length.Value, 5, places=6)
        self.assertRegenerated(total())

    def testTipOnlyChangeIsAStep(self):
        """A transaction that changes only the Body's Tip (the bar's move, an Output property but
        an input) is a step, and its undo puts the Tip back (S6; Transactions.cpp isResult).
        Rolled back, the Body keeps its last complete shape for what reads it and the bar's
        feature holds the rolled state (the fork's rule R7, ops#127)."""
        self.assertIs(self.body.Tip, self.fillet)
        count = self.doc.UndoCount
        self.edit("Move Bar", lambda: setattr(self.body, "Tip", self.boss))
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(self.doc.UndoNames[0], "Move Bar")
        self.assertFalse(self.doc.mustExecute())
        self.assertVolume(self.boss, total(withHole=False, withFillet=False))
        self.assertVolume(self.body, total())
        self.doc.undo()
        self.assertIs(self.body.Tip, self.fillet)
        self.assertRegenerated(total())

    def testLabelOnlyChangeIsAStep(self):
        """A transaction that changes only a Label (a rename, an Output property but an input) is
        a step, and its undo restores the name (S6)."""
        count = self.doc.UndoCount
        self.edit("Rename Boss", lambda: setattr(self.boss, "Label", "Riser"))
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertEqual(self.doc.UndoNames[0], "Rename Boss")
        self.doc.undo()
        self.assertEqual(self.boss.Label, "Boss")
        self.assertRegenerated(total())

    def testExpressionChangeIsAStep(self):
        """An expression set is a step (an expression engine recorded is always a change: its
        links don't tell two expressions on one object apart), and its undo takes it away. (Not
        asserted: the Length the expression wrote in the regeneration after the commit, outside
        the step, stays 8 after the undo, as upstream's Refresh after the commit left it.)"""
        self.edit("Edit Boss", lambda: self.boss.setExpression("Length", "4 + 4"))
        self.assertEqual(self.doc.UndoNames, ["Edit Boss"])
        self.assertRegenerated(total(boss=8))
        self.doc.undo()
        self.assertEqual(self.boss.ExpressionEngine, [])
        self.assertFalse(self.doc.mustExecute())

    def testPlainShapeChangeIsAStep(self):
        """A plain Part::Feature's Shape is its input (an import's, a script's): replacing it is a
        step, even with a shape of the same size in memory, and its undo restores it."""
        stock = self.doc.addObject("Part::Feature", "Stock")
        stock.Shape = Part.makeBox(1, 1, 1)
        self.doc.recompute()
        count = self.doc.UndoCount
        self.edit("Replace Stock", lambda: setattr(stock, "Shape", Part.makeBox(2, 1, 1)))
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.assertAlmostEqual(stock.Shape.Volume, 2, delta=TOL)
        self.doc.undo()
        self.assertAlmostEqual(stock.Shape.Volume, 1, delta=TOL)


class TestPatternWithoutOriginals(unittest.TestCase):
    """F3: the pattern's original is deleted. Model: the 20 x 20 x 10 block, a hole of radius 1,
    3 deep, at (5, 10), and a linear pattern of the hole along X, 3 occurrences over 10 mm (holes
    at x 5, 10, 15)."""

    HOLE = math.pi * 1**2 * 3

    def setUp(self):
        self.doc = models.newDocument("PatternWithoutOriginals")
        self.doc.UndoMode = 1
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body)
        self.block = models.pad(self.body, sketch, 10, "Block")
        holeSketch = models.sketch(self.doc, "HoleSketch", [models.circle(5, 10, 1)], self.body, z=10)
        self.hole = models.pocket(self.body, holeSketch, 3, "Hole")
        self.doc.recompute()
        self.pattern = self.body.newObject("PartDesign::LinearPattern", "Pattern")
        self.pattern.Originals = [self.hole]
        self.pattern.Direction = (self.body.Origin.OriginFeatures[0], [""])  # the X axis
        self.pattern.Length = 10
        self.pattern.Occurrences = 3
        self.body.Tip = self.pattern
        self.doc.recompute()
        self.assertTrue(self.pattern.isValid(), self.pattern.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 4000 - 3 * self.HOLE, delta=1e-4)
        self.assertIs(self.pattern.BaseFeature, self.hole)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertFailsOnTheBase(self, base, volume):
        self.assertFalse(self.pattern.isValid(), "the pattern stays valid")
        self.assertIn("Select features to pattern", self.pattern.getStatusString())
        self.assertIs(self.pattern.BaseFeature, base)
        self.assertAlmostEqual(self.pattern.Shape.Volume, volume, delta=1e-4)
        self.assertTrue(self.body.isValid(), self.body.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, volume, delta=1e-4)

    def testDeletedOriginalFailsAndPassesTheBase(self):
        """The hole deleted: the pattern stays in the chain on the block, fails with "Select
        features to pattern" and passes the block through: the Body is the block, no holes (F3:
        the pattern was Valid with BaseFeature None and the Body kept the three holes). An edit of
        the block reaches the Body; the undos bring everything back."""
        self.doc.openTransaction("Delete")
        self.body.removeObject(self.hole)
        self.doc.removeObject(self.hole.Name)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(self.pattern.Originals, [])
        self.assertIs(self.body.Tip, self.pattern)
        self.assertFailsOnTheBase(self.block, 4000)

        self.doc.openTransaction("Edit Block")
        self.block.Length = 12
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertFailsOnTheBase(self.block, 4800)

        self.doc.undo()
        self.doc.undo()
        self.doc.recompute()
        self.hole = self.doc.getObject("Hole")
        self.assertIsNotNone(self.hole)
        self.assertEqual(self.pattern.Originals, [self.hole])
        self.assertIs(self.pattern.BaseFeature, self.hole)
        self.assertTrue(self.pattern.isValid(), self.pattern.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 4000 - 3 * self.HOLE, delta=1e-4)

    def testPatternEmptiedFails(self):
        """The pattern's originals emptied (in its dialog): the same error, the hole passes
        through, the Body has the one hole."""
        self.pattern.Originals = []
        self.doc.recompute()
        self.assertFailsOnTheBase(self.hole, 4000 - self.HOLE)

    def testNewPatternWithoutOriginalsStaysOut(self):
        """A pattern just made, nothing picked yet (no BaseFeature): out of the chain, red in
        Onshape's words as Onshape shows an empty pattern (the hub's rule for the first build:
        ops#579/590's exemption from the error went), the Body unchanged."""
        fresh = self.body.newObject("PartDesign::LinearPattern", "Fresh")
        self.doc.recompute()
        self.assertIsNone(fresh.BaseFeature)
        self.assertFalse(fresh.isValid(), "the empty pattern stays valid")
        self.assertIn("Select features to pattern", fresh.getStatusString())
        self.assertTrue(self.body.isValid(), self.body.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 4000 - 3 * self.HOLE, delta=1e-4)

    def testConversionStillTakesTheStepOut(self):
        """Converting the pattern to a MultiTransform, as the command does: the pattern becomes a
        step, out of the chain (no BaseFeature, no error), and the MultiTransform builds on the
        hole (ops#590's case, unchanged)."""
        self.body.Tip = self.hole
        multi = self.body.newObject("PartDesign::MultiTransform", "MultiTransform")
        multi.Originals = self.pattern.Originals
        multi.TransformMode = self.pattern.TransformMode
        multi.BaseFeature = self.pattern.BaseFeature
        multi.Transformations = [self.pattern]
        self.pattern.Originals = []
        self.body.Tip = multi
        self.doc.recompute()
        self.assertIsNone(self.pattern.BaseFeature)
        self.assertIs(multi.BaseFeature, self.hole)
        for feature in (self.pattern, multi, self.body):
            self.assertTrue(feature.isValid(), f"{feature.Name}: {feature.getStatusString()}")
        self.assertAlmostEqual(self.body.Shape.Volume, 4000 - 3 * self.HOLE, delta=1e-4)


class TestStoppedBody(unittest.TestCase):
    """F37: a Body whose first feature fails with nothing to pass through (an unclaimed failure,
    decisions 254-259) keeps its error and has an empty Shape, as Onshape shows no part when the
    base extrude fails. Model: the 20 x 20 x 10 block."""

    def setUp(self):
        self.doc = models.newDocument("StoppedBody")
        self.body = models.body(self.doc)
        self.sketch = models.sketch(
            self.doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body
        )
        self.block = models.pad(self.body, self.sketch, 10, "Block")
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 4000, delta=1e-4)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def testOpenWireFirstPad(self):
        """The block's sketch loses a side (an open wire): the pad fails, the Body is in error and
        its Shape is empty (F37: it kept the 20 x 20 x 10 box). Closed again, the box is back."""
        side = self.sketch.Geometry[3]
        self.sketch.delGeometry(3)
        self.doc.recompute()
        self.assertFalse(self.block.isValid(), "the pad on an open wire stays valid")
        self.assertFalse(self.body.isValid(), "the Body isn't in error")
        self.assertIn("Invalid", self.body.State)
        shape = self.body.Shape
        self.assertTrue(shape.isNull(), shape.isNull() or f"the Body keeps a shape: {shape.Volume}")

        self.sketch.addGeometry(side, False)
        self.doc.recompute()
        self.assertTrue(self.block.isValid(), self.block.getStatusString())
        self.assertTrue(self.body.isValid(), self.body.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, 4000, delta=1e-4)
