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
import re
import shutil
import tempfile
import unittest
import zipfile

import FreeCAD as App
import Part
import Sketcher

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


def faceWhere(shape, test):
    found = [i + 1 for i, f in enumerate(shape.Faces) if test(f)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} faces match, expected one")
    return f"Face{found[0]}"


def isPlaneFacing(face, normal, through):
    """A planar face with this outward normal whose plane holds the point."""
    if not isinstance(face.Surface, Part.Plane):
        return False
    n = face.normalAt(*face.ParameterRange[::2])
    return (n - normal).Length < TOL and abs((through - face.Surface.Position).dot(normal)) < TOL


PAD2 = 10 * 10 * 5  # a 10 x 10 x 5 pad on the block's top, (5, 5) to (15, 15)
HOLE2 = math.pi * 2**2 * 2  # radius 2, 2 deep


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

    def pad2(self):
        """A 10 x 10 x 5 pad on the block's top, (5, 5) to (15, 15): its top face is at z = 15."""
        sketch = models.sketch(
            self.doc, "Pad2Sketch", models.rectangle(5, 5, 15, 15), self.body, z=10
        )
        return models.pad(self.body, sketch, 5, "Pad2")

    def sketchOn(self, name, feature, face, centre, radius):
        """A sketch attached to the feature's face (FlatFace) holding a circle at the global point
        centre, added at the bar."""
        sketch = self.doc.addObject("Sketcher::SketchObject", name)
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(feature, face)]
        sketch.MapMode = "FlatFace"
        self.recompute()
        local = sketch.getGlobalPlacement().inverse().multVec(centre)
        sketch.addGeometry(models.circle(local.x, local.y, radius), False)
        return sketch

    def onPad2(self):
        """Block, Pad2, and a 2 deep hole of radius 2 at (10, 10) whose sketch sits on Pad2's top
        face (N1 3.7, the first case)."""
        block = self.block()
        pad2 = self.pad2()
        self.recompute()
        top = faceWhere(pad2.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 15)))
        sketch = self.sketchOn("OnPad2Sketch", pad2, top, V(10, 10, 15), 2)
        hole = models.pocket(self.body, sketch, 2, "OnPad2")
        self.recompute()
        self.assertValid(sketch, hole)
        self.assertBody(BLOCK + PAD2 - HOLE2)
        return block, pad2, sketch, hole

    def savedRetargets(self):
        """The `rt` attributes of the document as saved: the re-target records (N1 3.4 a)."""
        if not self.tempDir:
            self.tempDir = tempfile.mkdtemp()
        path = os.path.join(self.tempDir, "records.FCStd")
        self.doc.saveCopy(path)
        with zipfile.ZipFile(path) as archive:
            xml = archive.read("Document.xml").decode("utf-8")
        return re.findall(r'\brt="([^"]*)"', xml)

    def parked(self, obj):
        return list(obj.ParkedReferences) if "ParkedReferences" in obj.PropertiesList else []

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

    # -- above a dependency: the re-target rule (section 3) --------------------------------------

    def testMoveAboveTheFaceItSitsOn(self):
        """The hole moved above Pad2, the face its sketch sits on: the sketch's support goes to the
        hole's new base with a re-target record, the sketch and the hole fail and Pad2 computes;
        moved back, the support is on Pad2's top face again and the record is gone (RO6)."""
        block, pad2, sketch, hole = self.onPad2()
        self.body.reorderObject([hole], block, True)
        self.assertChain(block, hole, pad2)
        target, subs = sketch.AttachmentSupport[0]
        self.assertIs(target, block)
        self.assertTrue(all(s.startswith("?") for s in subs), subs)
        self.assertEqual(self.savedRetargets(), ["Pad2"])
        self.recompute()
        self.assertFalse(sketch.isValid())
        self.assertFalse(hole.isValid())
        self.assertValid(pad2)
        if self.solver:
            self.assertIn("it was on 'Pad2'", sketch.getStatusString())
        self.assertBody(BLOCK + PAD2)

        self.body.reorderObject([hole], pad2, True)
        self.assertChain(block, pad2, hole)
        self.assertEqual(self.savedRetargets(), [])
        self.recompute()
        self.assertValid(sketch, hole)
        target, subs = sketch.AttachmentSupport[0]
        self.assertIs(target, pad2)
        self.assertTrue(isPlaneFacing(pad2.Shape.getElement(subs[0]), V(0, 0, 1), V(0, 0, 15)))
        self.assertBody(BLOCK + PAD2 - HOLE2)

    def testMoveAboveAFaceTheBaseHolds(self):
        """The sketch on the block's side face, which Pad2 doesn't touch: moved above Pad2, the
        support is found on the block (the same face) and everything computes; moved back, it is
        on Pad2's face again (RO7)."""
        block = self.block()
        pad2 = self.pad2()
        self.recompute()
        side = faceWhere(pad2.Shape, lambda f: isPlaneFacing(f, V(1, 0, 0), V(20, 0, 0)))
        sketch = self.sketchOn("SideSketch", pad2, side, V(20, 10, 5), 2)
        hole = models.pocket(self.body, sketch, 2, "SideHole")
        self.recompute()
        self.assertValid(sketch, hole)
        self.assertBody(BLOCK + PAD2 - HOLE2)

        self.body.reorderObject([hole], block, True)
        self.recompute()
        self.assertValid(sketch, hole, pad2)
        target, subs = sketch.AttachmentSupport[0]
        self.assertIs(target, block)
        self.assertTrue(isPlaneFacing(block.Shape.getElement(subs[0]), V(1, 0, 0), V(20, 0, 0)))
        self.assertBody(BLOCK + PAD2 - HOLE2)

        self.body.reorderObject([hole], pad2, True)
        self.recompute()
        self.assertValid(sketch, hole)
        target, subs = sketch.AttachmentSupport[0]
        self.assertIs(target, pad2)
        self.assertEqual(self.savedRetargets(), [])
        self.assertBody(BLOCK + PAD2 - HOLE2)

    def testRepickEndsTheRecord(self):
        """After the move the user picks the block's top face: the record ends, and moving back
        leaves the pick (RO6c)."""
        block, pad2, sketch, hole = self.onPad2()
        self.body.reorderObject([hole], block, True)
        top = faceWhere(block.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 10)))
        sketch.AttachmentSupport = [(block, top)]
        self.assertEqual(self.savedRetargets(), [])
        self.body.reorderObject([hole], pad2, True)
        self.assertEqual(sketch.AttachmentSupport, [(block, (top,))])

    def testUndoTheMove(self):
        """One transaction: the move, its re-target and the recompute; undo gives the model as it
        was (no record), redo the moved one with its record (RO16)."""
        block, pad2, sketch, hole = self.onPad2()
        self.doc.UndoMode = 1
        group = list(self.body.Group)
        bases = [o.BaseFeature for o in group if o.isDerivedFrom("PartDesign::Feature")]
        support = sketch.AttachmentSupport
        self.doc.openTransaction("Move")
        self.body.reorderObject([hole], block, True)
        self.recompute()
        self.doc.commitTransaction()
        self.doc.undo()
        self.assertEqual(list(self.body.Group), group)
        self.assertEqual(
            [o.BaseFeature for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")],
            bases,
        )
        self.assertIs(self.body.Tip, hole)
        self.assertEqual(sketch.AttachmentSupport, support)
        self.assertEqual(self.savedRetargets(), [])
        self.doc.redo()
        self.assertIs(sketch.AttachmentSupport[0][0], block)
        self.assertEqual(self.savedRetargets(), ["Pad2"])

    def testSharedSketch(self):
        """One sketch on Pad2's top face, used by two holes: one moved above Pad2 fails them both;
        moved back, both compute (RO10, Q1)."""
        block = self.block()
        pad2 = self.pad2()
        self.recompute()
        top = faceWhere(pad2.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 15)))
        sketch = self.sketchOn("SharedSketch", pad2, top, V(10, 10, 15), 2)
        first = models.pocket(self.body, sketch, 1, "First")
        second = models.pocket(self.body, sketch, 2, "Second")
        self.recompute()
        self.assertValid(first, second)
        self.body.reorderObject([first], block, True)
        self.recompute()
        self.assertFalse(sketch.isValid())
        self.assertFalse(first.isValid())
        self.assertFalse(second.isValid())
        self.body.reorderObject([first], sketch, True)
        self.assertChain(block, pad2, first, second)
        self.recompute()
        self.assertValid(sketch, first, second)
        self.assertBody(BLOCK + PAD2 - HOLE2)

    def testExternalGeometryComesBack(self):
        """A sketch projecting Pad2's top edge, with a constraint on the projection: moved above
        Pad2 the projection goes to the block (broken); moved back it is on Pad2's edge with its
        constraint (RO11). Moved to the very top, nothing can take the projection: refused."""
        block = self.block()
        pad2 = self.pad2()
        self.recompute()
        edge = edgeWhere(
            pad2.Shape,
            lambda e: isinstance(e.Curve, Part.Line)
            and all(abs(v.Point.y - 5) < TOL and abs(v.Point.z - 15) < TOL for v in e.Vertexes),
        )
        sketch = models.sketch(self.doc, "Projecting", [models.circle(10, 10, 1)], self.body, z=15)
        sketch.addExternal(pad2.Name, edge)
        sketch.addConstraint(Sketcher.Constraint("DistanceY", -3, 1, 0, 3, 5.0))
        constraints = len(sketch.Constraints)
        hole = models.pocket(self.body, sketch, 1, "ProjectedHole")
        self.recompute()
        self.assertValid(sketch, hole)

        with self.assertRaises(ValueError) as refused:
            self.body.reorderObject([hole], None, True)
        self.assertIn("projects", str(refused.exception))
        self.assertIs(sketch.ExternalGeometry[0][0], pad2)

        self.body.reorderObject([hole], block, True)
        self.assertIs(sketch.ExternalGeometry[0][0], block)
        self.assertEqual(self.savedRetargets(), ["Pad2"])
        self.recompute()
        self.assertFalse(hole.isValid())

        self.body.reorderObject([hole], pad2, True)
        self.recompute()
        self.assertValid(sketch, hole)
        self.assertIs(sketch.ExternalGeometry[0][0], pad2)
        self.assertEqual(len(sketch.Constraints), constraints)
        self.assertEqual(len(sketch.ExternalGeo), 3)
        projected = pad2.Shape.getElement(sketch.ExternalGeometry[0][1][0])
        self.assertTrue(all(abs(v.Point.y - 5) < TOL for v in projected.Vertexes))
        self.assertEqual(self.savedRetargets(), [])

    def testPatternAboveItsOriginalIsParked(self):
        """A pattern moved above its original: the original is parked on the pattern, which fails
        with the message and passes its base through; moved back, Originals is restored (RO8)."""
        block, a, b, c = self.chain()
        pattern = self.body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [c]
        pattern.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        pattern.Length = 4
        pattern.Occurrences = 2
        self.body.Tip = pattern
        self.recompute()
        self.assertBody(BLOCK + 2 * BOSS - 2 * HOLE)

        self.body.reorderObject([pattern], b, True)
        self.assertEqual(pattern.Originals, [])
        self.assertEqual(len(self.parked(pattern)), 1)
        # Still a solid feature of the chain, not a MultiTransform step
        self.assertChain(block, a, b, pattern, c)
        self.assertIs(self.body.Tip, c)
        self.recompute()
        self.assertFalse(pattern.isValid())
        self.assertIn(
            "Originals refers to 'HoleC', which now comes after 'Pattern'",
            pattern.getStatusString(),
        )
        self.assertValid(c)
        self.assertBody(BLOCK + 2 * BOSS - HOLE)

        self.body.reorderObject([pattern], c, True)
        self.assertEqual(pattern.Originals, [c])
        self.assertChain(block, a, b, c, pattern)
        self.assertEqual(self.parked(pattern), [])
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(BLOCK + 2 * BOSS - 2 * HOLE)

    def testTwoParkedOriginalsAndAThird(self):
        """Two originals parked, the user adds a third meanwhile: moved back, all three are there,
        each once (RO9c, S1)."""
        block, a, b, c = self.chain()
        pattern = self.body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [b, c]
        pattern.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        pattern.Length = 4
        pattern.Occurrences = 2
        self.body.Tip = pattern
        self.recompute()
        self.body.reorderObject([pattern], a, True)
        self.assertEqual(pattern.Originals, [])
        self.assertEqual(len(self.parked(pattern)), 2)
        pattern.Originals = [a]
        self.body.reorderObject([pattern], c, True)
        self.assertEqual(
            sorted(o.Name for o in pattern.Originals), sorted([a.Name, b.Name, c.Name])
        )
        self.assertEqual(self.parked(pattern), [])

    def testExpressionReadingALaterFeature(self):
        """B's length reads A's: B moved above A has its expression set aside and fails with the
        message; moved back, the expression is back and follows A (RO9, Q4)."""
        block, a, b, c = self.chain()
        b.setExpression("Length", "BossA.Length")
        self.recompute()
        self.body.reorderObject([b], block, True)
        self.assertEqual(b.ExpressionEngine, [])
        self.recompute()
        self.assertFalse(b.isValid())
        self.assertIn(
            "the expression of 'Length' reads 'BossA', which now comes after 'BossB'",
            b.getStatusString(),
        )
        self.body.reorderObject([b], a, True)
        self.assertEqual([e[0] for e in b.ExpressionEngine], ["Length"])
        self.assertEqual(self.parked(b), [])
        a.Length = 7
        self.recompute()
        self.assertAlmostEqual(b.Length.Value, 7)
        self.assertValid(b)

    def testExpressionReadingAnotherFeaturesSketch(self):
        """C's length reads a sketch that sits on A's top face and belongs to another pocket: C
        moved above A has its expression set aside, and that sketch's support is untouched
        (RO9b, S4)."""
        block, a, b, c = self.chain()
        top = faceWhere(a.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 15)))
        onA = self.sketchOn("OnASketch", a, top, V(3, 3, 15), 1)
        pocketOnA = models.pocket(self.body, onA, 1, "PocketOnA")
        self.recompute()
        c.setExpression("Length", "OnASketch.AttachmentOffset.Base.z + 3 mm")
        self.recompute()
        self.assertValid(c, pocketOnA)
        self.body.reorderObject([c], block, True)
        self.assertEqual(c.ExpressionEngine, [])
        self.assertIs(onA.AttachmentSupport[0][0], a)
        self.recompute()
        self.assertFalse(c.isValid())
        self.assertValid(onA, pocketOnA)
        self.body.reorderObject([c], pocketOnA, True)
        self.assertEqual([e[0] for e in c.ExpressionEngine], ["Length"])

    def testCycleThroughAnOutsideBinderIsRefused(self):
        """The hole's sketch sits on a binder outside the Body that binds Pad2's top face: a path
        that leaves the Body, which the rule doesn't break. Moved above Pad2, from Python with no
        transaction open, the move is refused and nothing changes (RO12, S2)."""
        block = self.block()
        pad2 = self.pad2()
        self.recompute()
        top = faceWhere(pad2.Shape, lambda f: isPlaneFacing(f, V(0, 0, 1), V(0, 0, 15)))
        binder = self.doc.addObject("PartDesign::SubShapeBinder", "Outside")
        binder.Support = [(pad2, (top,))]
        self.recompute()
        sketch = self.sketchOn("ViaBinder", binder, "Face1", V(10, 10, 15), 1)
        hole = models.pocket(self.body, sketch, 1, "ViaBinderHole")
        self.recompute()
        self.assertValid(sketch, hole)
        group = list(self.body.Group)
        bases = [o.BaseFeature for o in group if o.isDerivedFrom("PartDesign::Feature")]
        tip = self.body.Tip
        support = sketch.AttachmentSupport
        with self.assertRaises(ValueError) as refused:
            self.body.reorderObject([hole], block, True)
        self.assertIn("cycle", str(refused.exception))
        self.assertEqual(list(self.body.Group), group)
        self.assertEqual(
            [o.BaseFeature for o in self.body.Group if o.isDerivedFrom("PartDesign::Feature")],
            bases,
        )
        self.assertIs(self.body.Tip, tip)
        self.assertEqual(sketch.AttachmentSupport, support)
        self.assertEqual(self.savedRetargets(), [])

    def testOtherBodyWaitsWhileRolledBack(self):
        """A binder in another body bound to this Body: rolled back and edited, the Body keeps its
        shape and the binder doesn't change; rolled to the end, it follows once (RO14)."""
        block, a, b, c = self.chain()
        other = self.doc.addObject("PartDesign::Body", "OtherBody")
        binder = other.newObject("PartDesign::SubShapeBinder", "Copy")
        binder.Support = [(self.body, ("",))]
        self.recompute()
        volume = binder.Shape.Volume
        self.body.rollTo(a)
        a.Length = 7
        self.recompute()
        self.assertAlmostEqual(binder.Shape.Volume, volume, delta=1e-4)
        self.assertNotTouched(binder)
        self.body.rollToEnd()
        self.recompute()
        self.assertAlmostEqual(binder.Shape.Volume, BLOCK + 4 * 4 * 7 + BOSS - HOLE, delta=1e-4)


class TestBodyReorderV2(BodyReorderBase, unittest.TestCase):
    solver = False


class TestBodyReorderV2s(BodyReorderBase, unittest.TestCase):
    solver = True

    def testRecordSurvivesTheSolver(self):
        """The hole's sketch on the block's front face, which a notch (Pad2's place taken by a
        pocket) trims: moved above the notch, the solver finds the face on the block at tier 1 and
        the record stays; moved back, the support is the notch's trimmed face again and the record
        is gone (RO6b, B2)."""
        block = self.block()
        notchSketch = models.sketch(
            self.doc, "NotchSketch", models.rectangle(8, -1, 12, 3), self.body, z=10
        )
        notch = models.pocket(self.body, notchSketch, 3, "Notch")
        self.recompute()
        front = faceWhere(notch.Shape, lambda f: isPlaneFacing(f, V(0, -1, 0), V(0, 0, 0)))
        sketch = self.sketchOn("FrontSketch", notch, front, V(4, 0, 4), 1)
        hole = models.pocket(self.body, sketch, 2, "FrontHole")
        self.recompute()
        self.assertValid(sketch, hole)

        self.body.reorderObject([hole], block, True)
        self.recompute()
        self.assertValid(sketch, hole, notch)
        target, subs = sketch.AttachmentSupport[0]
        self.assertIs(target, block)
        self.assertTrue(isPlaneFacing(block.Shape.getElement(subs[0]), V(0, -1, 0), V(0, 0, 0)))
        self.assertEqual(self.savedRetargets(), ["Notch"])

        self.body.reorderObject([hole], notch, True)
        self.recompute()
        self.assertValid(sketch, hole)
        target, subs = sketch.AttachmentSupport[0]
        self.assertIs(target, notch)
        restored = notch.Shape.getElement(subs[0])
        self.assertTrue(isPlaneFacing(restored, V(0, -1, 0), V(0, 0, 0)))
        self.assertAlmostEqual(restored.Area, 20 * 10 - 4 * 3, delta=1e-6)  # trimmed by the notch
        self.assertEqual(self.savedRetargets(), [])

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
