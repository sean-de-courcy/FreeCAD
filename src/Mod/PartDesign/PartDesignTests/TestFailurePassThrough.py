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

"""A failed feature in a Body passes its input through and the features after it compute
(FreeCAD-CH ops#126, ops#127; notes/reorder-rollback-design.md section 4).

Every model is designed here: a 20 x 20 x 10 block (4000 mm^3) and features whose effect on the
volume and the geometry is known. A feature is made to fail by itself (a pocket of length zero, a
sketch with conflicting constraints, a split the Body doesn't allow, an expression in error), never
by a user's file. Each test runs in plain V2 and with the reference solver (V2s)."""

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests.Scenarios import models

V = App.Vector
BLOCK = 4000.0
HOLE = math.pi * 3**2 * 3  # the pocket: a 3 mm deep hole of radius 3 in the top
BOSS = 125.0  # a 5 mm cube on a side
CHAMFER = 0.5 * 1**2 * 10  # a 1 mm chamfer on a 10 mm vertical edge
ROUND = (1 - math.pi / 4) * 1**2 * 10  # a 1 mm fillet on a 10 mm vertical edge
TOL = 1e-6


def elementWhere(shape, kind, test):
    """The name of the one element of the kind ("Face", "Edge") that passes the test."""
    elements = shape.Faces if kind == "Face" else shape.Edges
    found = [i + 1 for i, e in enumerate(elements) if test(e)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} {kind}s match, expected one")
    return f"{kind}{found[0]}"


def isCircle(edge, centre, radius):
    curve = edge.Curve
    return (
        isinstance(curve, Part.Circle)
        and abs(curve.Radius - radius) < TOL
        and (curve.Center - centre).Length < TOL
    )


def isVerticalLineAt(edge, x, y):
    if not isinstance(edge.Curve, Part.Line):
        return False
    a, b = (v.Point for v in edge.Vertexes)
    return all(abs(p.x - x) < TOL and abs(p.y - y) < TOL for p in (a, b))


class FailurePassThroughBase:
    """The tests; the subclasses choose the configuration."""

    solver = False

    def setUp(self):
        self.doc = models.newDocument(f"FailurePassThrough{type(self).__name__}")
        if hasattr(self.doc, "HistoryAlgorithm"):
            self.doc.HistoryAlgorithm = "V2"
        self.doc.ReferenceSolver = self.solver
        self.doc.InternNames = False
        self.body = models.body(self.doc)

    def tearDown(self):
        for name in list(App.listDocuments()):
            if name.startswith("FailurePassThrough"):
                App.closeDocument(name)

    # -- the model -------------------------------------------------------------------------------

    def block(self):
        sketch = models.sketch(self.doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body)
        return models.pad(self.body, sketch, 10, "Block")

    def hole(self):
        """A pocket 3 deep, radius 3, in the middle of the top."""
        sketch = models.sketch(self.doc, "HoleSketch", [models.circle(10, 10, 3)], self.body, z=10)
        return models.pocket(self.body, sketch, 3, "Hole")

    def boss(self, base, name="Boss"):
        """A 5 mm cube on the block's x = 20 face, its sketch attached to that face of `base`."""
        self.doc.recompute()
        face = elementWhere(
            base.Shape,
            "Face",
            lambda f: abs(f.CenterOfMass.x - 20) < TOL and abs(abs(f.normalAt(0, 0).x) - 1) < TOL,
        )
        sketch = models.sketch(self.doc, f"{name}Sketch", models.rectangle(-2.5, -2.5, 2.5, 2.5))
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(base, face)]
        sketch.MapMode = "FlatFace"
        return models.pad(self.body, sketch, 5, name)

    def recompute(self):
        self.doc.recompute()

    # -- assertions ------------------------------------------------------------------------------

    def assertValid(self, *objects):
        for obj in objects:
            self.assertTrue(obj.isValid(), f"{obj.Name}: {obj.getStatusString()}")

    def assertFailed(self, obj, *words):
        self.assertFalse(obj.isValid(), f"{obj.Name} stays valid")
        self.assertIn("Invalid", obj.State)
        self.assertNotIn("Touched", obj.State)
        message = obj.getStatusString()
        for word in words:
            self.assertIn(word, message)
        return message

    def assertVolume(self, obj, volume):
        self.assertAlmostEqual(obj.Shape.Volume, volume, delta=1e-4)

    def assertBody(self, volume):
        self.assertValid(self.body)
        self.assertVolume(self.body, volume)

    # -- T1 ------------------------------------------------------------------------------------

    def testChainContinuesAfterAFailure(self):
        """The hole fails (length zero): it passes the block through, the boss after it computes
        on the block, and the Body is block + boss. Repaired, the hole is back (T1)."""
        self.block()
        hole = self.hole()
        boss = self.boss(hole)
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS)

        hole.Length = 0
        self.recompute()
        self.assertFailed(hole, "zero")
        self.assertVolume(hole, BLOCK)
        self.assertValid(boss, boss.Profile[0])
        self.assertBody(BLOCK + BOSS)

        hole.Length = 3
        self.recompute()
        self.assertValid(hole, boss)
        self.assertBody(BLOCK - HOLE + BOSS)

    # -- T2 ------------------------------------------------------------------------------------

    def testElementsOfTheFailureBreakOthersHold(self):
        """A fillet on the hole's rim (an edge the hole made) breaks when the hole fails; a chamfer
        on a block edge after it computes. Repaired, the fillet finds the same rim (T2)."""
        self.block()
        hole = self.hole()
        self.recompute()
        fillet = self.body.newObject("PartDesign::Fillet", "RimFillet")
        rim = elementWhere(hole.Shape, "Edge", lambda e: isCircle(e, V(10, 10, 10), 3))
        fillet.Base = (hole, [rim])
        fillet.Radius = 1
        self.recompute()
        chamfer = self.body.newObject("PartDesign::Chamfer", "CornerChamfer")
        corner = elementWhere(fillet.Shape, "Edge", lambda e: isVerticalLineAt(e, 0, 0))
        chamfer.Base = (fillet, [corner])
        chamfer.Size = 1
        self.recompute()
        self.assertValid(hole, fillet, chamfer)
        whole = self.body.Shape.Volume

        hole.Length = 0
        self.recompute()
        self.assertFailed(hole)
        self.assertFailed(fillet)
        self.assertVolume(fillet, BLOCK)
        self.assertValid(chamfer)
        self.assertBody(BLOCK - CHAMFER)

        hole.Length = 3
        self.recompute()
        self.assertValid(hole, fillet, chamfer)
        sub = fillet.Base[1][0]
        self.assertTrue(isCircle(hole.Shape.getElement(sub), V(10, 10, 10), 3), sub)
        self.assertBody(whole)

    # -- T3 ------------------------------------------------------------------------------------

    def testProfileInErrorFailsItsFeature(self):
        """The hole's sketch has conflicting constraints: the sketch is red, the hole fails naming
        it and passes the block through, and a later boss computes (T3)."""
        block = self.block()
        hole = self.hole()
        boss = self.boss(block)
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS)

        sketch = hole.Profile[0]
        sketch.addConstraint(Sketcher.Constraint("Radius", 0, 3))
        sketch.addConstraint(Sketcher.Constraint("Radius", 0, 4))
        self.recompute()
        self.assertFailed(sketch)
        self.assertFailed(hole, "Profile", sketch.Label)
        self.assertVolume(hole, BLOCK)
        self.assertValid(boss)
        self.assertBody(BLOCK + BOSS)

    def testPatternOfAFailureFails(self):
        """A linear pattern of the failed hole fails naming it and passes the block through (T3)."""
        self.block()
        hole = self.hole()
        pattern = self.body.newObject("PartDesign::LinearPattern", "HolePattern")
        pattern.Originals = [hole]
        pattern.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        pattern.Length = 6.5  # the second hole at x = 16.5, clear of the first and of the side
        pattern.Occurrences = 2
        self.body.Tip = pattern  # newObject leaves the Tip on the original
        self.recompute()
        self.assertValid(pattern)
        self.assertBody(BLOCK - 2 * HOLE)

        hole.Length = 0
        self.recompute()
        self.assertFailed(hole)
        self.assertFailed(pattern, "Originals", hole.Label)
        self.assertVolume(pattern, BLOCK)
        self.assertBody(BLOCK)

    def testMultiTransformStepInErrorFailsItsMultiTransform(self):
        """A MultiTransform's step (added to the Body as the task panel does) in error is claimed
        like any member: it isn't left touched, the MultiTransform fails naming it and passes the
        hole through, and the boss after it computes (review M1 of fork PR 114)."""
        self.block()
        hole = self.hole()
        multi = self.doc.addObject("PartDesign::MultiTransform", "HoleMulti")
        multi.Originals = [hole]
        multi.Refine = False
        self.body.addObject(multi)
        step = self.doc.addObject("PartDesign::LinearPattern", "HoleStep")
        step.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        step.Mode = "Spacing"
        step.Offset = 6.5  # the second hole at x = 16.5, clear of the first and of the side
        step.Occurrences = 2
        self.body.addObject(step)
        multi.Transformations = [step]
        self.assertIs(self.body.Tip, multi)
        boss = self.boss(multi)
        self.recompute()
        self.assertValid(multi, boss)
        self.assertBody(BLOCK - 2 * HOLE + BOSS)

        step.setExpression("Offset", "Block.NoSuchProperty")
        self.recompute()
        self.assertFailed(step)
        self.assertFailed(multi, "Transformations", step.Label)
        self.assertVolume(multi, BLOCK - HOLE)
        self.assertValid(boss)
        self.assertBody(BLOCK - HOLE + BOSS)

        step.setExpression("Offset", None)
        self.recompute()
        self.assertValid(step, multi, boss)
        self.assertBody(BLOCK - 2 * HOLE + BOSS)

    def testSketchOnADatumInErrorFails(self):
        """A datum plane on the hole's floor (a face the hole made) fails with the hole; a sketch
        attached to the datum fails naming it, and so does the boss of that sketch (T3, F4)."""
        self.block()
        hole = self.hole()
        self.recompute()
        floor = elementWhere(hole.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 7) < TOL)
        datum = self.body.newObject("PartDesign::Plane", "FloorPlane")
        datum.AttachmentSupport = [(hole, floor)]
        datum.MapMode = "FlatFace"
        # The plane's origin is the global origin projected onto the floor: draw in the hole
        sketch = models.sketch(self.doc, "DatumSketch", models.rectangle(9, 9, 11, 11))
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(datum, "")]
        sketch.MapMode = "FlatFace"
        post = models.pad(self.body, sketch, 2, "Post")
        self.recompute()
        self.assertValid(datum, sketch, post)
        self.assertBody(BLOCK - HOLE + 2 * 2 * 2)

        hole.Length = 0
        self.recompute()
        self.assertFailed(hole)
        self.assertFailed(datum)
        self.assertFailed(sketch, "AttachmentSupport", datum.Label)
        self.assertFailed(post, "Profile", sketch.Label)
        self.assertVolume(post, BLOCK)
        self.assertBody(BLOCK)

    # -- T4 ------------------------------------------------------------------------------------

    def testPrimitiveKeepsItsPlacement(self):
        """An unattached, turned subtractive box (a notch in the side) fails (its width comes from
        an expression in error): its Placement stays, its shape is the block where the block is,
        and a fillet on a block edge after it computes (T4, F8)."""
        self.block()
        box = self.body.newObject("PartDesign::SubtractiveBox", "Slot")
        box.Length, box.Width, box.Height = 2, 6, 12
        placement = App.Placement(V(9, -1, -1), App.Rotation(V(0, 0, 1), 30))
        box.Placement = placement
        self.recompute()
        self.assertValid(box)
        fillet = self.body.newObject("PartDesign::Fillet", "EdgeFillet")
        edge = elementWhere(box.Shape, "Edge", lambda e: isVerticalLineAt(e, 20, 20))
        fillet.Base = (box, [edge])
        fillet.Radius = 1
        self.recompute()
        self.assertValid(fillet)

        box.setExpression("Width", "Block.NoSuchProperty")
        self.recompute()
        self.assertFailed(box, "NoSuchProperty")
        self.assertTrue(box.Placement.isSame(placement, 1e-12), box.Placement)
        expected = self.doc.getObject("Block").Shape.optimalBoundingBox(False, False)
        actual = box.Shape.optimalBoundingBox(False, False)
        for a, b in zip(
            (actual.XMin, actual.YMin, actual.ZMin, actual.XMax, actual.YMax, actual.ZMax),
            (
                expected.XMin,
                expected.YMin,
                expected.ZMin,
                expected.XMax,
                expected.YMax,
                expected.ZMax,
            ),
        ):
            self.assertAlmostEqual(a, b, delta=1e-7)
        self.assertVolume(box, BLOCK)
        self.assertValid(fillet)
        self.assertTrue(isVerticalLineAt(box.Shape.getElement(fillet.Base[1][0]), 20, 20))
        self.assertBody(BLOCK - ROUND)

        box.setExpression("Width", None)
        box.Width = 6
        self.recompute()
        self.assertValid(box, fillet)
        self.assertTrue(box.Placement.isSame(placement, 1e-12), box.Placement)

    # -- T5 ------------------------------------------------------------------------------------

    def testConsumersOutsideTheBody(self):
        """A compound of the failed hole, outside the Body, is skipped as upstream does (it keeps
        its shape and stays touched); a compound of the Body gets the end result (T5, F5)."""
        self.block()
        hole = self.hole()
        ofHole = self.doc.addObject("Part::Compound", "OfHole")
        ofHole.Links = [hole]
        ofBody = self.doc.addObject("Part::Compound", "OfBody")
        ofBody.Links = [self.body]
        self.recompute()
        self.assertVolume(ofHole, BLOCK - HOLE)

        hole.Length = 0
        self.recompute()
        self.assertFailed(hole)
        self.assertIn("Touched", ofHole.State)
        self.assertNotIn("Invalid", ofHole.State)
        self.assertVolume(ofHole, BLOCK - HOLE)
        self.assertValid(ofBody)
        self.assertVolume(ofBody, BLOCK)

    def testPartFeatureOutsideABodyKeepsUpstreamBehaviour(self):
        """Outside a Body nothing changes: a failed Part box stays touched and its dependant
        isn't run (F7)."""
        box = models.box(self.doc, "PlainBox", (2, 3, 4))
        compound = self.doc.addObject("Part::Compound", "OfPlainBox")
        compound.Links = [box]
        self.recompute()
        self.assertVolume(compound, 24)

        box.Length = 0
        self.recompute()
        self.assertFalse(box.isValid())
        self.assertIn("Touched", box.State)
        self.assertNotIn("Invalid", compound.State)
        self.assertVolume(compound, 24)
        self.assertEqual(self.doc.recompute(), 1)  # the box again, not the compound

    # -- T6 ------------------------------------------------------------------------------------

    def testFailureIsNotRerun(self):
        """A second recompute has nothing to do, and the failure keeps its message (T6)."""
        self.block()
        hole = self.hole()
        self.recompute()
        hole.Length = 0
        self.recompute()
        message = self.assertFailed(hole)

        self.assertEqual(self.doc.recompute(), 0)
        self.assertEqual(hole.getStatusString(), message)

    # -- T7 ------------------------------------------------------------------------------------

    def testSaveAndReopenKeepTheFailure(self):
        """Saved with the hole failed, the file reopens with the hole red and its message, the
        Body's end result and nothing to recompute (T7)."""
        self.block()
        hole = self.hole()
        self.boss(hole)
        self.recompute()
        hole.Length = 0
        self.recompute()
        message = self.assertFailed(hole)

        folder = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "failed.FCStd")
        self.doc.saveAs(path)
        name = self.doc.Name
        App.closeDocument(name)
        doc = App.openDocument(path)
        self.doc = doc
        hole = doc.getObject("Hole")
        self.assertIn("Invalid", hole.State)
        self.assertEqual(hole.getStatusString(), message)
        self.assertVolume(doc.getObject("Body"), BLOCK + BOSS)
        self.assertEqual([o.Name for o in doc.Objects if "Touched" in o.State], [])
        App.closeDocument(doc.Name)

    def testUndoRestoresTheModel(self):
        """Undoing the edit that made the hole fail, then recomputing, gives the whole model
        back (T7)."""
        self.doc.UndoMode = 1
        self.block()
        hole = self.hole()
        self.boss(hole)
        self.recompute()
        self.doc.openTransaction("Break")
        hole.Length = 0
        self.recompute()
        self.doc.commitTransaction()
        self.assertFailed(hole)

        self.doc.undo()
        self.recompute()
        self.assertValid(*self.body.Group)
        self.assertBody(BLOCK - HOLE + BOSS)

    # -- T8 ------------------------------------------------------------------------------------

    def testFirstFeatureFails(self):
        """The only pad fails: the Body is valid and empty; a later pad computes alone (T8, F6)."""
        block = self.block()
        block.Length = 0
        self.recompute()
        self.assertFailed(block, "zero")
        self.assertValid(self.body)
        self.assertTrue(self.body.Shape.isNull() or self.body.Shape.Volume < TOL)

        sketch = models.sketch(self.doc, "PostSketch", models.rectangle(0, 0, 2, 3), self.body)
        models.pad(self.body, sketch, 4, "Post")
        self.recompute()
        self.assertBody(24)

    # -- T9 ------------------------------------------------------------------------------------

    def testExpressionInErrorPassesThrough(self):
        """The hole's length comes from an expression that fails (a property that doesn't exist):
        the hole fails before it runs and passes the block through, not its old shape (T9, D1)."""
        block = self.block()
        hole = self.hole()
        boss = self.boss(hole)
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS)

        hole.setExpression("Length", f"{block.Name}.NoSuchProperty")
        self.recompute()
        self.assertFailed(hole, "NoSuchProperty")
        self.assertVolume(hole, BLOCK)
        self.assertValid(boss)
        self.assertBody(BLOCK + BOSS)

    # -- the kickoff's model ---------------------------------------------------------------------

    def testFilletOnARemovedEdge(self):
        """Two holes; a fillet on the second hole's rim; a later pocket. Deleting the second
        circle removes the rim: the fillet fails, the pocket still computes (the Body is the
        block minus the two pockets), and a sketch centred on the fillet's arc breaks. Drawing the
        circle again brings the fillet and the sketch back with the solver."""
        self.block()
        sketch = models.sketch(
            self.doc,
            "HolesSketch",
            [models.circle(5, 5, 3), models.circle(15, 15, 3)],
            self.body,
            z=10,
        )
        holes = models.pocket(self.body, sketch, 3, "Holes")
        self.recompute()
        fillet = self.body.newObject("PartDesign::Fillet", "RimFillet")
        rim = elementWhere(holes.Shape, "Edge", lambda e: isCircle(e, V(15, 15, 10), 3))
        fillet.Base = (holes, [rim])
        fillet.Radius = 1
        self.recompute()
        arc = elementWhere(fillet.Shape, "Edge", lambda e: isCircle(e, V(15, 15, 10), 4))
        centred = models.sketch(self.doc, "CentredSketch", [models.circle(0, 0, 1)])
        self.body.addObject(centred)
        centred.AttachmentSupport = [(fillet, arc)]
        centred.MapMode = "Concentric"
        later = self.doc.addObject("Sketcher::SketchObject", "LaterSketch")
        self.body.addObject(later)
        later.Placement = App.Placement(V(0, 0, 10), App.Rotation())
        later.addGeometry(models.rectangle(2, 14, 6, 18), False)
        pocket = models.pocket(self.body, later, 2, "LaterPocket")
        self.recompute()
        self.assertValid(holes, fillet, centred, pocket)
        self.assertTrue((centred.Placement.Base - V(15, 15, 10)).Length < TOL)
        whole = self.body.Shape.Volume

        sketch.delGeometry(1)
        self.recompute()
        self.assertValid(holes, pocket)
        self.assertFailed(fillet)
        self.assertFailed(centred)
        self.assertBody(BLOCK - HOLE - 4 * 4 * 2)

        if not self.solver:
            return  # plain V2 doesn't re-derive a broken reference (the solver's retry does)
        sketch.addGeometry(models.circle(15, 15, 3), False)
        self.recompute()
        self.assertValid(holes, fillet, centred, pocket)
        self.assertTrue((centred.Placement.Base - V(15, 15, 10)).Length < TOL)
        self.assertBody(whole)


class TestFailurePassThroughV2(FailurePassThroughBase, unittest.TestCase):
    solver = False


class TestFailurePassThroughV2s(FailurePassThroughBase, unittest.TestCase):
    solver = True
