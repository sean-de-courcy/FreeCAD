# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
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
# *                                                                         *
# ***************************************************************************

"""The roll-back bar, reorder and insert at the bar in a PartDesign Body (FreeCAD-CH ops#127;
notes/reorder-rollback-design.md sections 1-3).

Every model is designed here: a 20 x 20 x 10 block (4000 mm^3), 4 x 4 x 5 bosses on its top and a
hole in it, whose volumes are known, so each step has a volume oracle. Each test runs in plain V2
and with the reference solver (V2s)."""

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part

from PartDesignTests.Scenarios import models

V = App.Vector
BLOCK = 4000.0
BOSS = 4 * 4 * 5
HOLE = math.pi * 2**2 * 3  # radius 2, 3 deep from the top
ROUND = (1 - math.pi / 4) * 1**2 * 10  # a 1 mm fillet on a 10 mm vertical edge
TOL = 1e-6


def isVerticalLineAt(edge, x, y):
    if not isinstance(edge.Curve, Part.Line):
        return False
    return all(abs(v.Point.x - x) < TOL and abs(v.Point.y - y) < TOL for v in edge.Vertexes)


def edgeWhere(shape, test):
    found = [i + 1 for i, e in enumerate(shape.Edges) if test(e)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} edges match, expected one")
    return f"Edge{found[0]}"


class BodyReorderBase:
    """The tests; the subclasses choose the configuration."""

    solver = False

    def setUp(self):
        self.doc = models.newDocument(f"BodyReorder{type(self).__name__}")
        if hasattr(self.doc, "HistoryAlgorithm"):
            self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = self.solver
        self.doc.InternNames = False
        self.body = models.body(self.doc)
        self.tempDir = None

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name.startswith("BodyReorder"):
                App.closeDocument(name)
        if self.tempDir:
            shutil.rmtree(self.tempDir, ignore_errors=True)

    # -- the model -------------------------------------------------------------------------------

    def block(self):
        sketch = models.sketch(self.doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body)
        return models.pad(self.body, sketch, 10, "Block")

    def boss(self, name, x, y):
        """A 4 x 4 x 5 boss on the top, its corner at (x, y), from an unattached sketch."""
        sketch = models.sketch(
            self.doc, f"{name}Sketch", models.rectangle(x, y, x + 4, y + 4), self.body, z=10
        )
        return models.pad(self.body, sketch, 5, name)

    def hole(self, name="Hole", x=10, y=10):
        sketch = models.sketch(self.doc, f"{name}Sketch", [models.circle(x, y, 2)], self.body, z=10)
        return models.pocket(self.body, sketch, 3, name)

    def chain(self):
        """Block, boss A, boss B, hole C: 4000 + 80 + 80 - 12 pi."""
        block = self.block()
        a = self.boss("BossA", 1, 1)
        b = self.boss("BossB", 15, 15)
        c = self.hole("HoleC")
        self.recompute()
        self.assertBody(BLOCK + 2 * BOSS - HOLE)
        return block, a, b, c

    def recompute(self):
        return self.doc.recompute()

    # -- assertions ------------------------------------------------------------------------------

    def assertValid(self, *objects):
        for obj in objects:
            self.assertTrue(obj.isValid(), f"{obj.Name}: {obj.getStatusString()}")

    def assertBody(self, volume):
        self.assertTrue(self.body.isValid(), self.body.getStatusString())
        self.assertAlmostEqual(self.body.Shape.Volume, volume, delta=1e-4)

    def assertTouched(self, *objects):
        for obj in objects:
            self.assertIn("Touched", obj.State, obj.Name)

    def assertNotTouched(self, *objects):
        for obj in objects:
            self.assertNotIn("Touched", obj.State, obj.Name)

    def assertChain(self, *solids):
        """The solids are the Body's solid features in this order, each on the one before."""
        group = [o for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")]
        self.assertEqual([o.Name for o in group], [o.Name for o in solids])
        previous = None
        for solid in solids:
            self.assertEqual(solid.BaseFeature, previous, solid.Name)
            previous = solid

    # -- the roll-back bar (section 1) -----------------------------------------------------------

    def testHoldsByBarPosition(self):
        """Rolled back to A: B, C, C's sketch and the Body are held; the block, A, their sketches
        and B's sketch (before B: above the insert point, R2) aren't. At the end nothing is held;
        with the bar at the top every solid is."""
        block, a, b, c = self.chain()
        self.assertFalse(self.body.isRolledBack())
        self.assertFalse(any(self.body.holds(o) for o in self.body.Group))
        self.assertFalse(self.body.holds(self.body))

        self.body.rollTo(a)
        self.assertTrue(self.body.isRolledBack())
        self.assertIs(self.body.Tip, a)
        for obj in (b, c, c.Profile[0], self.body):
            self.assertTrue(self.body.holds(obj), obj.Name)
        for obj in (block, a, block.Profile[0], a.Profile[0], b.Profile[0]):
            self.assertFalse(self.body.holds(obj), obj.Name)

        self.body.rollTo(None)
        self.assertIsNone(self.body.Tip)
        self.assertTrue(all(self.body.holds(o) for o in (block, a, b, c)))

        self.body.rollToEnd()
        self.assertIs(self.body.Tip, c)
        self.assertFalse(self.body.isRolledBack())

    def testEditRollPointIsTheBar(self):
        """The edit roll-back point holds what is after it while set, and changes no Tip."""
        block, a, b, c = self.chain()
        self.body.setEditRollPoint(a)
        self.assertIs(self.body.Tip, c)
        self.assertTrue(self.body.isRolledBack())
        self.assertTrue(self.body.holds(b))
        self.assertFalse(self.body.holds(a))
        self.body.setEditRollPoint(None)
        self.assertFalse(self.body.isRolledBack())

    def testHeldTailIsNotRecomputed(self):
        """Rolled back to A, an edit of A recomputes A; B stays touched (C follows it when it
        runs) and keeps its old shape, the Body keeps its full shape and the document has nothing
        to do. Rolling to the end recomputes them and the Body."""
        block, a, b, c = self.chain()
        bVolume = b.Shape.Volume
        self.body.rollTo(a)
        self.assertEqual(self.recompute(), 0)
        a.Length = 7
        self.recompute()
        self.assertAlmostEqual(a.Shape.Volume, BLOCK + 4 * 4 * 7, delta=1e-4)
        self.assertTouched(b)
        self.assertAlmostEqual(b.Shape.Volume, bVolume, delta=1e-4)
        self.assertBody(BLOCK + 2 * BOSS - HOLE)
        self.assertFalse(self.doc.mustExecute())

        b.recompute()  # a held feature doesn't run on that path either
        self.assertTouched(b)

        self.body.rollToEnd()
        self.recompute()
        self.assertNotTouched(b, c, self.body)
        self.assertValid(a, b, c)
        self.assertBody(BLOCK + 4 * 4 * 7 + BOSS - HOLE)

    def testRollBackAndForwardWithoutAnEditRewritesNothing(self):
        """A roll back and forward with nothing edited recomputes nothing and doesn't rewrite the
        Body's shape (R7), so nothing outside the Body re-solves."""
        block, a, b, c = self.chain()
        before = self.body.Shape
        self.body.rollTo(a)
        self.assertEqual(self.recompute(), 0)
        self.body.rollToEnd()
        self.assertFalse(self.doc.mustExecute())
        self.assertEqual(self.recompute(), 0)
        self.assertTrue(self.body.Shape.isSame(before))

    def testInsertAtTheBar(self):
        """A feature added while rolled back goes after the bar and becomes the Tip; the next
        solid is now on it, held; rolling to the end computes everything."""
        block, a, b, c = self.chain()
        self.body.rollTo(a)
        d = self.boss("BossD", 15, 1)
        self.assertIs(self.body.Tip, d)
        self.assertChain(block, a, d, b, c)
        self.assertTrue(self.body.holds(b))
        self.recompute()
        self.assertValid(d)
        self.assertBody(BLOCK + 2 * BOSS - HOLE)  # held: the old full shape
        self.body.rollToEnd()
        self.recompute()
        self.assertBody(BLOCK + 3 * BOSS - HOLE)

    def testInsertAtTheTop(self):
        """With the bar at the top a new feature goes first."""
        block, a, b, c = self.chain()
        self.body.rollTo(None)
        sketch = models.sketch(
            self.doc, "FirstSketch", models.rectangle(30, 0, 34, 4), self.body, z=0
        )
        first = models.pad(self.body, sketch, 5, "First")
        self.assertIs(self.body.Tip, first)
        self.assertChain(first, block, a, b, c)
        self.body.rollToEnd()
        self.recompute()
        self.assertBody(BLOCK + 3 * BOSS - HOLE)

    def testRollToChecks(self):
        block, a, b, c = self.chain()
        with self.assertRaises(ValueError):
            self.body.rollTo(a.Profile[0])
        self.assertIs(self.body.Tip, c)

    def testSaveAndReopenRolledBack(self):
        """A document saved rolled back reopens rolled back: the Tip, the held features still
        touched, the Body's full shape; rolling to the end applies the edit (RO15)."""
        block, a, b, c = self.chain()
        self.body.rollTo(a)
        a.Length = 7
        self.recompute()
        self.tempDir = tempfile.mkdtemp()
        path = os.path.join(self.tempDir, "rolledback.FCStd")
        self.doc.saveAs(path)
        names = [o.Name for o in (self.body, a, b, c)]
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        body, a, b, c = (self.doc.getObject(name) for name in names)
        self.body = body
        self.assertIs(body.Tip, a)
        self.assertTrue(body.isRolledBack())
        self.assertTouched(b)
        self.assertBody(BLOCK + 2 * BOSS - HOLE)
        body.rollToEnd()
        self.recompute()
        self.assertBody(BLOCK + 4 * 4 * 7 + BOSS - HOLE)

    def testDatumAtTheEndUsedEarlierIsNotHeld(self):
        """A datum plane made with the Tip at the end, used by an earlier sketch: rolled back
        above the datum, it isn't held, and moving it moves the hole that uses it (B1, RO19)."""
        block = self.block()
        a = self.boss("BossA", 1, 1)
        self.recompute()
        datum = self.body.newObject("PartDesign::Plane", "Level")
        datum.AttachmentSupport = [(models.originFeature(self.body, "XY_Plane"), "")]
        datum.MapMode = "FlatFace"
        datum.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        self.recompute()
        sketch = models.sketch(self.doc, "HoleSketch", [models.circle(12, 12, 2)])
        self.body.insertObject(sketch, a, False)
        sketch.AttachmentSupport = [(datum, "")]
        sketch.MapMode = "FlatFace"
        hole = self.body.newObject("PartDesign::Pocket", "Hole")
        self.body.removeObject(hole)
        self.body.insertObject(hole, sketch, True)
        hole.Profile = sketch
        hole.Length = 3
        self.body.Tip = a
        self.recompute()
        self.assertChain(block, hole, a)
        self.body.rollTo(hole)
        self.assertFalse(self.body.holds(datum))
        self.assertTrue(self.body.holds(a))
        datum.AttachmentOffset = App.Placement(V(0, 0, 9), App.Rotation())
        self.recompute()
        self.assertValid(hole)
        # The pocket now starts at z = 9: a closed cavity from 6 to 9 under a 1 mm roof
        floors = [
            f.CenterOfMass.z
            for f in hole.Shape.Faces
            if abs(f.normalAt(0, 0).z) > 0.9
            and abs(f.CenterOfMass.x - 12) < TOL
            and abs(f.CenterOfMass.y - 12) < TOL
        ]
        self.assertAlmostEqual(min(floors), 6.0, delta=1e-6)

    # -- reorder (section 2) ---------------------------------------------------------------------

    def testReorderOneFeatureDown(self):
        """A moved below B, with its sketch: the chain is rewired, the Tip stays at the end."""
        block, a, b, c = self.chain()
        self.body.reorderObject([a], b, True)
        self.assertChain(block, b, a, c)
        group = list(self.body.Group)
        self.assertEqual(group.index(a.Profile[0]) + 1, group.index(a))
        self.assertIs(self.body.Tip, c)
        self.recompute()
        self.assertValid(block, a, b, c)
        self.assertBody(BLOCK + 2 * BOSS - HOLE)

    def testReorderTheTipKeepsTheBarAtTheEnd(self):
        block, a, b, c = self.chain()
        self.body.reorderObject([c], a, True)
        self.assertChain(block, a, c, b)
        self.assertIs(self.body.Tip, b)
        self.recompute()
        self.assertBody(BLOCK + 2 * BOSS - HOLE)

    def testReorderBelowTheBarIsHeld(self):
        """Rolled back to A, B moved above A is active and C stays held; the bar stays after A."""
        block, a, b, c = self.chain()
        self.body.rollTo(a)
        self.body.reorderObject([b], block, True)
        self.assertChain(block, b, a, c)
        self.assertIs(self.body.Tip, a)
        self.assertFalse(self.body.holds(b))
        self.assertTrue(self.body.holds(c))
        self.body.reorderObject([b], c, True)
        self.assertChain(block, a, c, b)
        self.assertIs(self.body.Tip, a)
        self.assertTrue(self.body.holds(b))

    def testReorderTwoToTheTop(self):
        """A block of two moved to the start: the first of them has no base."""
        block, a, b, c = self.chain()
        self.body.reorderObject([a, b], None, True)
        self.assertChain(a, b, block, c)
        self.recompute()
        self.assertBody(BLOCK + 2 * BOSS - HOLE)

    def testReorderChecksChangeNothing(self):
        block, a, b, c = self.chain()
        group = list(self.body.Group)
        other = self.doc.addObject("PartDesign::Body", "Other")
        sketch = models.sketch(self.doc, "Stray", models.rectangle(0, 0, 1, 1), other)
        for objects, target in (([sketch], a), ([a], sketch), ([a], a)):
            with self.assertRaises(ValueError):
                self.body.reorderObject(objects, target, True)
            self.assertEqual(list(self.body.Group), group)
            self.assertChain(block, a, b, c)

    def testRemoveObjectsKeepsTheChain(self):
        block, a, b, c = self.chain()
        self.body.removeObjects([a, b])
        self.assertChain(block, c)
        self.assertIs(self.body.Tip, c)

    def testCycleIsRefusedWithNothingChanged(self):
        """A hole whose sketch sits on boss A's top face, moved above A: a cycle the rule doesn't
        break yet is refused, from Python with no transaction open, and nothing changes."""
        block, a, b, c = self.chain()
        top = None
        for i, f in enumerate(a.Shape.Faces):
            if abs(f.CenterOfMass.z - 15) < TOL:
                top = f"Face{i + 1}"
        sketch = models.sketch(self.doc, "OnASketch", [models.circle(3, 3, 1)])
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(a, top)]
        sketch.MapMode = "FlatFace"
        onA = models.pocket(self.body, sketch, 1, "OnA")
        self.recompute()
        self.assertValid(onA)
        group = list(self.body.Group)
        bases = [o.BaseFeature for o in group if o.isDerivedFrom("PartDesign::Feature")]
        tip = self.body.Tip
        support = sketch.AttachmentSupport
        try:
            self.body.reorderObject([onA], block, True)
        except ValueError as e:
            self.assertIn("cycle", str(e))
        else:
            # Once the re-target rule breaks this cycle, the move succeeds instead
            return
        self.assertEqual(list(self.body.Group), group)
        self.assertEqual(
            [o.BaseFeature for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")],
            bases,
        )
        self.assertIs(self.body.Tip, tip)
        self.assertEqual(sketch.AttachmentSupport, support)


class TestBodyReorderV2(BodyReorderBase, unittest.TestCase):
    solver = False


class TestBodyReorderV2s(BodyReorderBase, unittest.TestCase):
    solver = True

    def testFilletFollowsItsBaseThroughAMove(self):
        """A fillet on a block edge moved below the hole: its Base moves to the hole and finds the
        same edge (geometry), and back again (RO5)."""
        block = self.block()
        self.recompute()
        fillet = self.body.newObject("PartDesign::Fillet", "Round")
        fillet.Base = (block, [edgeWhere(block.Shape, lambda e: isVerticalLineAt(e, 0, 0))])
        fillet.Radius = 1
        hole = self.hole()
        self.recompute()
        self.assertBody(BLOCK - ROUND - HOLE)

        self.body.reorderObject([fillet], hole, True)
        self.assertChain(block, hole, fillet)
        self.assertIs(fillet.Base[0], hole)
        self.recompute()
        self.assertValid(hole, fillet)
        edge = fillet.Base[0].Shape.getElement(fillet.Base[1][0])
        self.assertTrue(isVerticalLineAt(edge, 0, 0))
        self.assertBody(BLOCK - ROUND - HOLE)

        self.body.reorderObject([fillet], block, True)
        self.assertChain(block, fillet, hole)
        self.assertIs(fillet.Base[0], block)
        self.recompute()
        self.assertValid(hole, fillet)
        edge = fillet.Base[0].Shape.getElement(fillet.Base[1][0])
        self.assertTrue(isVerticalLineAt(edge, 0, 0))
        self.assertBody(BLOCK - ROUND - HOLE)
