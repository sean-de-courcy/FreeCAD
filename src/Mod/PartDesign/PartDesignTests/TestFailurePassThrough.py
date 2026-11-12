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
sketch with a malformed constraint, a split the Body doesn't allow, an expression in error), never
by a user's file. Each test runs with the reference solver (V2s), and in plain V2 (a file saved
before the solver) with FREECAD_OLD_FILE_TESTS set (decision 179)."""

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

from PartDesignTests import TestNamingDump as dump
from PartDesignTests.Scenarios import models

V = App.Vector
BLOCK = 4000.0
HOLE = math.pi * 3**2 * 3  # the pocket: a 3 mm deep hole of radius 3 in the top
BOSS = 125.0  # a 5 mm cube on a side
CHAMFER = 0.5 * 1**2 * 10  # a 1 mm chamfer on a 10 mm vertical edge
ROUND = (1 - math.pi / 4) * 1**2 * 10  # a 1 mm fillet on a 10 mm vertical edge
TOL = 1e-6


def elementWhere(shape, kind, test):
    """The name of the one element of the kind ("Face", "Edge", "Vertex") that passes the test."""
    elements = {"Face": shape.Faces, "Edge": shape.Edges, "Vertex": shape.Vertexes}[kind]
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

    def assertStopped(self, obj, *words):
        """Failed: a failure no rule claims, or its dependant (ops#579). A dependant stopped
        without running is no longer left touched (ops#640 round 8, J13: nothing is pending)."""
        self.assertFalse(obj.isValid(), f"{obj.Name} stays valid")
        self.assertIn("Invalid", obj.State)
        message = obj.getStatusString()
        for word in words:
            self.assertIn(word, message)
        return message

    def assertVolume(self, obj, volume):
        self.assertAlmostEqual(obj.Shape.Volume, volume, delta=1e-4)

    def assertBody(self, volume):
        self.assertValid(self.body)
        self.assertVolume(self.body, volume)

    def assertBodyShowsNothing(self, body=None):
        """A stopped Body writes an empty Shape and keeps its error (ops#640, regen item 6, F37):
        it shows nothing rather than its last result."""
        body = body or self.body
        self.assertFalse(body.isValid())
        self.assertTrue(body.Shape.isNull(), f"the stopped {body.Name} kept its last shape")

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
        """The hole's sketch has a malformed constraint: the sketch is red, the hole fails naming
        it and passes the block through, and a later boss computes (T3)."""
        block = self.block()
        hole = self.hole()
        boss = self.boss(block)
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS)

        sketch = hole.Profile[0]
        sketch.addConstraint(Sketcher.Constraint("Radius", 0, 3))
        sketch.addConstraint(Sketcher.Constraint("Midpoint", 0, 3, 0))  # malformed (ops#640)
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
        """A compound of the failed hole, outside the Body, fails naming it and keeps its shape
        (F4 for every dependant, ops#579; F5 left it Valid on that shape); a compound of the Body
        gets the end result (T5). Repaired, both compute."""
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
        self.assertStopped(ofHole, "Links links to", f"'{hole.Label}'")
        self.assertVolume(ofHole, BLOCK - HOLE)
        self.assertValid(ofBody)
        self.assertVolume(ofBody, BLOCK)

        hole.Length = 3
        self.recompute()
        self.assertValid(hole, ofHole, ofBody)
        self.assertVolume(ofHole, BLOCK - HOLE)

    def testPartFeatureOutsideABodyFailsItsDependant(self):
        """Outside a Body a failed Part box stays touched, and its dependant fails naming it,
        keeps its shape and stays touched (ops#579; F7 left it Valid on that shape)."""
        box = models.box(self.doc, "PlainBox", (2, 3, 4))
        compound = self.doc.addObject("Part::Compound", "OfPlainBox")
        compound.Links = [box]
        self.recompute()
        self.assertVolume(compound, 24)

        box.Length = 0
        self.recompute()
        self.assertStopped(box)
        self.assertStopped(compound, "Links links to", f"'{box.Label}'")
        self.assertVolume(compound, 24)
        self.assertEqual(self.doc.recompute(), 2)  # the box again, and the compound judged

        box.Length = 2
        self.recompute()
        self.assertValid(box, compound)
        self.assertNotIn("Touched", compound.State)

    # -- ops#579: the dependants of a failure no rule claims -------------------------------------

    def freeProfile(self, doc=None, name="FreeProfile"):
        """A sketch outside the Body: a circle of radius 3 at (10, 10), its radius constrained."""
        sketch = models.sketch(doc or self.doc, name, [models.circle(10, 10, 3)])
        sketch.addConstraint(Sketcher.Constraint("Radius", 0, 3))
        return sketch

    @staticmethod
    def breakProfile(sketch):
        """A malformed constraint (a Midpoint of the circle on itself): the sketch fails by
        itself. (A second radius in conflict no longer fails a sketch since ops#640.)"""
        sketch.addConstraint(Sketcher.Constraint("Midpoint", 0, 3, 0))

    @staticmethod
    def repairProfile(sketch):
        sketch.delConstraint(1)

    @staticmethod
    def prism(doc, base, name="Prism"):
        """A solid 5 mm extrusion of `base`'s circle: 45 pi mm^3."""
        prism = doc.addObject("Part::Extrusion", name)
        prism.Base = base
        prism.DirMode = "Custom"
        prism.Dir = V(0, 0, 1)
        prism.LengthFwd = 5
        prism.Solid = True
        return prism

    def testDependantsOfAFreeSketchFailNamingTheirInput(self):
        """A free sketch fails (a malformed constraint). Each dependant fails without running,
        naming its direct input, keeps its shape and stays touched: a sketch with the circle as
        external geometry, a Part extrusion of it, a plane attached to the extrusion's top and a
        sketch on that plane. The folder holding them isn't failed. The failure persists over a
        second recompute; repaired, everything computes (ops#579)."""
        profile = self.freeProfile()
        self.recompute()
        rim = models.sketch(self.doc, "Rim", [])
        rim.addExternal(profile.Name, "Edge1")
        prism = self.prism(self.doc, profile)
        self.recompute()
        top = elementWhere(prism.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 5) < TOL)
        lid = self.doc.addObject("Part::Plane", "Lid")
        lid.Length = lid.Width = 2
        lid.AttachmentSupport = [(prism, top)]
        lid.MapMode = "FlatFace"
        onLid = models.sketch(self.doc, "OnLid", models.rectangle(0, 0, 1, 1))
        onLid.AttachmentSupport = [(lid, "Face1")]
        onLid.MapMode = "FlatFace"
        folder = self.doc.addObject("App::DocumentObjectGroup", "Folder")
        folder.addObjects([profile, prism])
        self.recompute()
        everything = (profile, rim, prism, lid, onLid, folder)
        self.assertValid(*everything)
        self.assertVolume(prism, 45 * math.pi)

        self.breakProfile(profile)
        for _ in range(2):
            self.recompute()
            self.assertStopped(profile)
            self.assertStopped(rim, "links to", f"'{profile.Label}'")
            self.assertStopped(prism, "Base links to", f"'{profile.Label}'")
            self.assertStopped(lid, "AttachmentSupport links to", f"'{prism.Label}'")
            self.assertStopped(onLid, "AttachmentSupport links to", f"'{lid.Label}'")
            self.assertVolume(prism, 45 * math.pi)
            self.assertValid(folder)

        self.repairProfile(profile)
        self.recompute()
        self.assertValid(*everything)
        self.assertEqual([o.Name for o in everything if "Touched" in o.State], [])
        self.assertVolume(prism, 45 * math.pi)

    def testReadersOfAContainerOfAFailureFail(self):
        """An App::Part holds a 2 x 3 x 4 box. A compound of the Part, a binder of the box's top
        face through the Part's subname path, and a Link to the Part each read the box. The box
        fails (length zero) and keeps its shape: each reader fails naming the box and keeps its
        shape, and the Part itself isn't failed. Repaired, everything computes (decision 253)."""
        assy = self.doc.addObject("App::Part", "Assy")
        box = models.box(self.doc, "Crate", (2, 3, 4))
        assy.addObject(box)
        self.recompute()
        top = elementWhere(box.Shape, "Face", lambda f: abs(f.CenterOfMass.z - 4) < TOL)
        compound = self.doc.addObject("Part::Compound", "OfAssy")
        compound.Links = [assy]
        binder = self.doc.addObject("PartDesign::SubShapeBinder", "TopBinder")
        binder.Support = [(assy, (f"{box.Name}.{top}",))]
        link = self.doc.addObject("App::Link", "AssyLink")
        link.LinkedObject = assy
        self.recompute()
        readers = (compound, binder, link)
        self.assertValid(assy, box, *readers)
        self.assertVolume(compound, 24)

        box.Length = 0
        self.recompute()
        self.assertStopped(box)
        self.assertValid(assy)
        for reader in readers:
            self.assertStopped(reader, f"'{assy.Label}', and '{box.Label}' in it has an error")
        self.assertVolume(compound, 24)

        box.Length = 2
        self.recompute()
        self.assertValid(assy, box, *readers)
        self.assertEqual([o.Name for o in readers if "Touched" in o.State], [])

    def bossOnBase(self, base, volume):
        """The Body on `base` (its BaseFeature; `volume` mm^3) with the 5 mm boss on its top at
        z = 10, and a Part::Mirroring of the boss's Pad outside the Body."""
        self.body.BaseFeature = base
        sketch = models.sketch(self.doc, "BossSketch", models.rectangle(0, 0, 5, 5), self.body, z=10)
        boss = models.pad(self.body, sketch, 5, "Boss")
        mirror = self.doc.addObject("Part::Mirroring", "MirroredBoss")
        mirror.Source = boss
        mirror.Normal = V(1, 0, 0)
        self.recompute()
        self.assertValid(self.body, boss, mirror)
        self.assertBody(volume + BOSS)
        self.assertVolume(mirror, volume + BOSS)
        return self.body.Group[0], boss, mirror

    def assertBodyStopped(self, base, boss, mirror, volume, *words):
        """The Body doesn't continue past its failed FeatureBase (decision 254): the boss and the
        Body fail naming their inputs, the boss and the mirror outside keep their shapes, and the
        Body shows nothing (regen item 6)."""
        self.assertStopped(base, *words)
        self.assertStopped(boss, f"'{base.Label}', which has an error")
        self.assertStopped(self.body)
        self.assertStopped(mirror, f"'{boss.Label}', which has an error")
        self.assertVolume(boss, volume + BOSS)
        self.assertVolume(mirror, volume + BOSS)

    def testBodyOnAFailedBaseFeatureDoesNotContinue(self):
        """The Body's BaseFeature is a Part box outside it. The box fails (length zero): the
        FeatureBase fails naming it, and the Body doesn't continue: the boss after it doesn't
        compute on the empty pass-through (ops#579, decision 254). Repaired, everything computes."""
        stock = models.box(self.doc, "Stock", (20, 20, 10))
        base, boss, mirror = self.bossOnBase(stock, BLOCK)

        stock.Length = 0
        self.recompute()
        self.assertStopped(stock)
        self.assertBodyStopped(base, boss, mirror, BLOCK, f"'{stock.Label}', which has an error")

        stock.Length = 20
        self.recompute()
        self.assertValid(stock, base, boss, self.body, mirror)
        self.assertBody(BLOCK + BOSS)
        self.assertVolume(mirror, BLOCK + BOSS)

    def testBodyOnAContainerWithAFailedMemberDoesNotContinue(self):
        """The Body's BaseFeature is an App::Part holding the block and a spare 1 mm cube far off.
        The spare fails (length zero): the FeatureBase fails naming it through the Part, and the
        Body doesn't continue (decision 254). Repaired, everything computes."""
        lib = self.doc.addObject("App::Part", "Lib")
        lib.addObject(models.box(self.doc, "Stock", (20, 20, 10)))
        spare = models.box(self.doc, "Spare", (1, 1, 1), at=(100, 0, 0))
        lib.addObject(spare)
        base, boss, mirror = self.bossOnBase(lib, BLOCK + 1)

        spare.Length = 0
        self.recompute()
        self.assertStopped(spare)
        self.assertValid(lib)
        self.assertBodyStopped(
            base, boss, mirror, BLOCK + 1, f"'{lib.Label}', and '{spare.Label}' in it has an error"
        )

        spare.Length = 1
        self.recompute()
        self.assertValid(spare, base, boss, self.body, mirror)
        self.assertBody(BLOCK + 1 + BOSS)

    def testClaimedFailureKeepsItsTextWhenItsBodyStops(self):
        """A sketch in the Body has a malformed constraint: the Body's rule claims it, and it
        isn't re-run while nothing it reads changes. Then the BaseFeature fails and the Body stops
        (decision 254): the sketch keeps its own error text through that recompute and the repair,
        not a bare "Error" (review pr579-r3 T-R3-2, decision 255 (3))."""
        stock = models.box(self.doc, "Stock", (20, 20, 10))
        base, boss, mirror = self.bossOnBase(stock, BLOCK)
        sketch = models.sketch(self.doc, "Note", [models.circle(15, 15, 1)], self.body, z=10)
        sketch.addConstraint(Sketcher.Constraint("Radius", 0, 1))
        sketch.addConstraint(Sketcher.Constraint("Midpoint", 0, 3, 0))  # malformed (ops#640)
        self.recompute()
        text = self.assertFailed(sketch)
        self.assertNotEqual(text, "Error")
        self.assertValid(boss)

        stock.Length = 0
        self.recompute()
        self.assertBodyStopped(base, boss, mirror, BLOCK, f"'{stock.Label}', which has an error")
        self.assertEqual(sketch.getStatusString(), text)

        stock.Length = 20
        self.recompute()
        self.assertValid(base, boss, mirror)
        self.assertEqual(sketch.getStatusString(), text)

    def mirrorOf(self, source):
        mirror = self.doc.addObject("Part::Mirroring", f"Mirrored{source.Name}")
        mirror.Source = source
        mirror.Normal = V(1, 0, 0)
        return mirror

    def assertFirstFeatureStopped(self, block, boss, mirror, *words):
        """The Body doesn't continue past its failed first solid feature (decision 255 (1)): the
        block fails naming its input, the boss's sketch (attached to the block) and the boss after
        it and the Body fail naming theirs. The boss and the mirror of the boss outside keep their
        shapes; the Body shows nothing (regen item 6)."""
        self.assertStopped(block, *words)
        self.assertStopped(boss.Profile[0], f"'{block.Label}', which has an error")
        self.assertStopped(boss, f"'{boss.Profile[0].Label}', which has an error")
        self.assertStopped(self.body)
        self.assertStopped(mirror, f"'{boss.Label}', which has an error")
        for obj in (boss, mirror):
            self.assertVolume(obj, BLOCK + BOSS)
        self.assertBodyShowsNothing()

    def testFirstFeatureOfAFailureOutsideDoesNotContinue(self):
        """The block, the Body's first solid feature (no BaseFeature), takes its length from an
        expression on a Part box outside the Body. The box fails (length zero): the block fails
        naming it, and the Body doesn't continue: the boss after it doesn't compute alone on the
        empty pass-through, nor a Part::Mirroring of it or a second Body on the Body (ops#579,
        review pr579-r3 T-R3-1, decision 255 (1)); both Bodies show nothing (regen item 6).
        Repaired, everything computes."""
        gauge = models.box(self.doc, "Gauge", (2, 2, 10), at=(100, 0, 0))
        block = self.block()
        block.setExpression("Length", f"{gauge.Name}.Height")
        boss = self.boss(block)
        mirror = self.mirrorOf(boss)
        second = self.doc.addObject("PartDesign::Body", "Second")
        second.BaseFeature = self.body
        self.recompute()
        self.assertValid(block, boss, self.body, mirror, second)
        self.assertBody(BLOCK + BOSS)

        gauge.Length = 0
        self.recompute()
        self.assertStopped(gauge)
        self.assertFirstFeatureStopped(block, boss, mirror, f"'{gauge.Label}' has an error")
        self.assertStopped(second.Group[0], f"'{self.body.Label}', which has an error")
        self.assertStopped(second)
        # Its Tip, the base feature of the stopped Body, is an unclaimed failure: it shows
        # nothing either (regen item 6)
        self.assertBodyShowsNothing(second)

        gauge.Length = 2
        self.recompute()
        self.assertValid(gauge, block, boss, self.body, mirror, second, second.Group[0])
        self.assertBody(BLOCK + BOSS)
        self.assertVolume(second, BLOCK + BOSS)

    def testFirstFeatureOnABinderOfAFailureDoesNotContinue(self):
        """The block is padded from a SubShapeBinder in the Body of the top face of a Part box
        outside it. The box fails (length zero): the binder fails naming it, the block fails
        naming the binder, and the Body doesn't continue (review pr579-r3 T-R3-1, decision 255
        (1)). Repaired, everything computes."""
        plate = models.box(self.doc, "Plate", (20, 20, 1), at=(0, 0, -1))
        self.recompute()
        top = elementWhere(plate.Shape, "Face", lambda f: abs(f.CenterOfMass.z) < TOL)
        binder = self.body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(plate, (top,))]
        block = models.pad(self.body, binder, 10, "Block")
        boss = self.boss(block)
        mirror = self.mirrorOf(boss)
        self.recompute()
        self.assertValid(binder, block, boss, self.body, mirror)
        self.assertBody(BLOCK + BOSS)

        plate.Length = 0
        self.recompute()
        self.assertStopped(plate)
        self.assertFalse(binder.isValid())
        self.assertIn(f"'{plate.Label}'", binder.getStatusString())
        self.assertFirstFeatureStopped(block, boss, mirror, f"'{binder.Label}'")

        # Nothing changed: the same state, settled
        self.recompute()
        self.assertFirstFeatureStopped(block, boss, mirror, f"'{binder.Label}'")

        plate.Length = 20
        self.recompute()
        self.assertValid(plate, binder, block, boss, self.body, mirror)
        self.assertBody(BLOCK + BOSS)

    def testBodyMemberOfAFailureOutsideItPassesThrough(self):
        """The hole's depth is an expression on a Part box outside the Body. The box fails (length
        zero): the hole fails naming it, passes the block through, and the boss after it computes
        (the Body's rule, unchanged). Repaired, the hole is back (ops#579)."""
        self.block()
        gauge = models.box(self.doc, "Gauge", (2, 2, 3))
        hole = self.hole()
        hole.setExpression("Length", f"{gauge.Name}.Height")
        boss = self.boss(hole)
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS)

        gauge.Length = 0
        self.recompute()
        self.assertStopped(gauge)
        self.assertFailed(hole, f"'{gauge.Label}' has an error")
        self.assertVolume(hole, BLOCK)
        self.assertValid(boss)
        self.assertBody(BLOCK + BOSS)

        gauge.Length = 2
        self.recompute()
        self.assertValid(gauge, hole, boss)
        self.assertBody(BLOCK - HOLE + BOSS)

    def twoDocuments(self):
        """Document B holds the free sketch; document A a binder of its circle and an extrusion
        of the binder. Both saved, as a link across documents needs."""
        folder = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        docB = models.newDocument("FailurePassThroughB")
        docB.saveAs(os.path.join(folder, "B.FCStd"))
        profile = self.freeProfile(docB, "Profile")
        docB.recompute()
        docA = models.newDocument("FailurePassThroughA")
        docA.saveAs(os.path.join(folder, "A.FCStd"))
        binder = docA.addObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(profile, ("Edge1",))]
        prism = self.prism(docA, binder)
        docA.recompute()
        self.assertValid(profile, binder, prism)
        return docA, docB, profile, binder, prism

    def testDependantInAnotherDocumentFailsAtOnce(self):
        """B alone recomputes after its sketch fails: A's binder fails at once, in A, naming the
        sketch, and is left touched; the extrusion after it is judged by A's recompute, which
        fails it naming the binder. Repaired in B, A's recompute brings both back (ops#579)."""
        docA, docB, profile, binder, prism = self.twoDocuments()

        self.breakProfile(profile)
        docB.recompute()
        self.assertFalse(profile.isValid())
        self.assertStopped(binder, "Support links to", f"'{profile.Label}'")
        self.assertValid(prism)

        docA.recompute()
        self.assertStopped(binder, "Support links to", f"'{profile.Label}'")
        self.assertStopped(prism, "Base links to", f"'{binder.Label}'")

        self.repairProfile(profile)
        docB.recompute()
        self.assertTrue(profile.isValid())
        self.assertIn("Touched", binder.State)
        docA.recompute()
        self.assertValid(binder, prism)
        self.assertVolume(prism, 45 * math.pi)

    def testDependantsDocumentAloneOrBothFail(self):
        """A alone recomputes after B's sketch fails (the sketch runs in A's recompute): the binder
        and the extrusion fail. Then B and A both recompute: they stay failed. Repaired, A's
        recompute alone brings them back (ops#579)."""
        docA, docB, profile, binder, prism = self.twoDocuments()

        self.breakProfile(profile)
        docA.recompute()
        self.assertFalse(profile.isValid())
        self.assertStopped(binder, "Support links to", f"'{profile.Label}'")
        self.assertStopped(prism, "Base links to", f"'{binder.Label}'")

        docB.recompute()
        docA.recompute()
        self.assertStopped(binder, "Support links to", f"'{profile.Label}'")
        self.assertStopped(prism, "Base links to", f"'{binder.Label}'")

        self.repairProfile(profile)
        docA.recompute()
        self.assertTrue(profile.isValid())
        self.assertValid(binder, prism)
        self.assertVolume(prism, 45 * math.pi)

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
        """The first pad fails (length zero). Its pass-through would be the empty shape, so the
        Body doesn't continue (decision 255 (1); T8 and F6 passed it through, and a later pad
        computed alone on nothing): the pad keeps its last output, the Body and a Part::Mirroring
        of it outside fail, and so does a pad added after it, naming it. The stopped Body shows
        nothing (regen item 6); the mirror, which doesn't run, keeps its last shape. Repaired,
        everything computes."""
        block = self.block()
        mirror = self.mirrorOf(self.body)
        self.recompute()
        self.assertBody(BLOCK)

        block.Length = 0
        self.recompute()
        self.assertStopped(block, "zero")
        self.assertStopped(self.body)
        self.assertStopped(mirror, f"'{self.body.Label}', which has an error")
        for obj in (block, mirror):
            self.assertVolume(obj, BLOCK)
        self.assertBodyShowsNothing()

        sketch = models.sketch(self.doc, "PostSketch", models.rectangle(30, 0, 32, 3), self.body)
        post = models.pad(self.body, sketch, 4, "Post")
        self.recompute()
        self.assertStopped(post, f"'{block.Label}', which has an error")
        self.assertStopped(self.body)
        self.assertBodyShowsNothing()

        block.Length = 10
        self.recompute()
        self.assertValid(block, post, self.body, mirror)
        self.assertBody(BLOCK + 24)
        self.assertVolume(mirror, BLOCK + 24)

    def testReferenceIntoAStoppedFeatureBreaksAtTheFixAfterASlide(self):
        """Body1 is built on a Body whose only Pad then fails, so Body1's FeatureBase fails and
        Body1 stops (decision 254): its rim Pad doesn't run, and a sketch attached to the rim's
        front face (y = 0) fails naming it. In that edit a second rim is drawn at y = 20. Then
        the first rim is deleted, the second slid onto y = 0, and the base repaired: the front
        face is a face the second rim made, which was in the model while the Pad was down, so
        the sketch breaks, as it does without the failure. The record of the reference into the
        Pad is taken at the end of the recompute that left it unmade (ops#579, decision 256;
        before, it kept the build's record and re-bound in place, silently)."""
        ground = models.sketch(self.doc, "Ground", models.rectangle(100, 50, 110, 60), self.body)
        groundPad = models.pad(self.body, ground, 5, "GroundPad")
        self.recompute()
        body1 = self.doc.addObject("PartDesign::Body", "Body1")
        body1.BaseFeature = self.body
        self.recompute()
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 40, 2), body1)
        rim = models.pad(body1, profile, 10, "Rim")
        self.recompute()
        front = elementWhere(
            rim.Shape,
            "Face",
            lambda f: abs(f.CenterOfMass.y) < TOL and abs(f.normalAt(0, 0).y + 1) < TOL,
        )
        top = body1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(rim, front)]
        top.MapMode = "FlatFace"
        self.recompute()
        self.assertValid(rim, top)

        profile.addGeometry(models.rectangle(0, 20, 40, 22), False)
        groundPad.Length = 0
        self.recompute()
        self.assertStopped(rim)
        self.assertStopped(top, f"'{rim.Label}', which has an error")

        models.moveRectangle(profile, 0, 0, 40, 2, first=4)
        profile.delGeometries([0, 1, 2, 3])
        groundPad.Length = 5
        self.recompute()
        self.assertValid(groundPad, rim)
        self.assertFalse(top.isValid(), "the front face re-bound to the slid rim's")

    def testReferenceIntoAStoppedFeatureTakesWhatIsDrawnInALaterEdit(self):
        """The model above. The base fails first, and nothing else changes for a recompute: the
        records into the Pad aren't taken again while its closure's marks are as they hold them
        (decision 263). Then, in a later edit while it is still down, the second rim is drawn: the
        marks changed, so the records are taken, and the slide onto y = 0 with the repair breaks
        the sketch, as in one edit."""
        ground = models.sketch(self.doc, "Ground", models.rectangle(100, 50, 110, 60), self.body)
        groundPad = models.pad(self.body, ground, 5, "GroundPad")
        self.recompute()
        body1 = self.doc.addObject("PartDesign::Body", "Body1")
        body1.BaseFeature = self.body
        self.recompute()
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 40, 2), body1)
        rim = models.pad(body1, profile, 10, "Rim")
        self.recompute()
        front = elementWhere(
            rim.Shape,
            "Face",
            lambda f: abs(f.CenterOfMass.y) < TOL and abs(f.normalAt(0, 0).y + 1) < TOL,
        )
        top = body1.newObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(rim, front)]
        top.MapMode = "FlatFace"
        self.recompute()
        self.assertValid(rim, top)

        groundPad.Length = 0
        self.recompute()
        self.recompute()
        self.assertStopped(rim)
        self.assertStopped(top, f"'{rim.Label}', which has an error")

        profile.addGeometry(models.rectangle(0, 20, 40, 22), False)
        self.recompute()
        self.assertStopped(top, f"'{rim.Label}', which has an error")

        models.moveRectangle(profile, 0, 0, 40, 2, first=4)
        profile.delGeometries([0, 1, 2, 3])
        groundPad.Length = 5
        self.recompute()
        self.assertValid(groundPad, rim)
        self.assertFalse(top.isValid(), "the front face re-bound to the slid rim's")

    def testReferenceIntoAStoppedBodyBreaksAtTheFixAfterASlide(self):
        """The model above with the reference into the Body itself: a sketch outside it attached to
        the Body's front face (y = 0). In one edit a second rim is drawn at y = 20 and the rim, the
        Body's only feature, fails (length zero): the Body stops and shows nothing (F37). Then the
        first rim is deleted, the second slid onto y = 0, and the rim repaired: the sketch breaks,
        as it does into the rim. The records into the Body are taken before its shape is cleared
        (ops#652); taken after, from the empty shape, they kept the build's and the sketch
        re-bound in place, quietly."""
        body1 = self.doc.addObject("PartDesign::Body", "Body1")
        profile = models.sketch(self.doc, "Profile", models.rectangle(0, 0, 40, 2), body1)
        rim = models.pad(body1, profile, 10, "Rim")
        self.recompute()
        front = elementWhere(
            body1.Shape,
            "Face",
            lambda f: abs(f.CenterOfMass.y) < TOL and abs(f.normalAt(0, 0).y + 1) < TOL,
        )
        top = self.doc.addObject("Sketcher::SketchObject", "Top")
        top.AttachmentSupport = [(body1, front)]
        top.MapMode = "FlatFace"
        self.recompute()
        self.assertValid(rim, body1, top)

        profile.addGeometry(models.rectangle(0, 20, 40, 22), False)
        rim.Length = 0
        self.recompute()
        self.assertTrue(body1.Shape.isNull(), "a stopped Body shows nothing (F37)")
        self.assertFalse(top.isValid())

        models.moveRectangle(profile, 0, 0, 40, 2, first=4)
        profile.delGeometries([0, 1, 2, 3])
        rim.Length = 10
        self.recompute()
        self.assertValid(rim, body1)
        self.assertFalse(top.isValid(), "the front face re-bound to the slid rim's")

    def assertFirstFeatureOfAnyKindStops(self, first):
        """`first`, the Body's first solid feature, is in error and of a kind whose result on
        nothing isn't known to be nothing: the Body doesn't continue past it (decision 255 (1)):
        the block after it fails naming it. Removed, the block computes."""
        block = self.block()
        self.recompute()
        self.assertStopped(first)
        self.assertStopped(block, f"'{first.Label}', which has an error")
        self.assertStopped(self.body)

        self.body.removeObject(first)
        self.doc.removeObject(first.Name)
        self.recompute()
        self.assertValid(block)
        self.assertBody(BLOCK)

    def assertALeadThatMakesNothingHidesNoFailure(self, lead):
        """`lead`, the Body's first solid feature, is valid and makes nothing; the block after it
        takes its length from an expression on a Part box outside the Body. The box fails: the
        block's pass-through would be the empty shape, so the Body doesn't continue (decision
        255 (1): a claimed failure whose pass-through is empty; review pr579-r4f T-R4F-1: the
        boss computed on nothing, Valid). Repaired, everything computes."""
        gauge = models.box(self.doc, "Gauge", (2, 2, 10), at=(100, 0, 0))
        block = self.block()
        block.setExpression("Length", f"{gauge.Name}.Height")
        boss = self.boss(block)
        mirror = self.mirrorOf(boss)
        self.recompute()
        self.assertValid(lead, block, boss, self.body, mirror)
        self.assertBody(BLOCK + BOSS)

        gauge.Length = 0
        self.recompute()
        self.assertFirstFeatureStopped(block, boss, mirror, f"'{gauge.Label}' has an error")

        gauge.Length = 2
        self.recompute()
        self.assertValid(lead, block, boss, self.body, mirror)
        self.assertBody(BLOCK + BOSS)

    def testSuppressedBaseLeavesNothingPending(self):
        """Round 8 (J13): the block suppressed under a boss on its side and a 1 mm fillet on the
        boss's outer top edge (5 long): the boss's sketch loses its face, the boss, the fillet and
        the Body fail through it, red and not touched, as Onshape has no needs-recompute state;
        the document has nothing to recompute (Refresh stays grey) and a recompute changes
        nothing. Unsuppressed, everything computes again: 4000 + 125 - (1 - pi/4) 5."""
        block = self.block()
        boss = self.boss(block)
        self.recompute()
        # The boss's outer face is the solid's x = max; its top edge there
        outerX = boss.Shape.BoundBox.XMax
        outer = {
            i: e.BoundBox
            for i, e in enumerate(boss.Shape.Edges, 1)
            if abs(e.BoundBox.XMin - outerX) < TOL and abs(e.BoundBox.XMax - outerX) < TOL
        }
        topZ = max(b.ZMax for b in outer.values())
        [edge] = [f"Edge{i}" for i, b in outer.items() if b.ZMin > topZ - TOL]
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, [edge])
        fillet.Radius = 1
        self.recompute()
        expected = BLOCK + BOSS - (1 - math.pi / 4) * 5
        self.assertValid(boss, fillet)
        self.assertBody(expected)

        block.Suppressed = True
        self.recompute()
        sketch = boss.Profile[0]
        for obj in (sketch, boss, fillet, self.body):
            self.assertFalse(obj.isValid(), f"{obj.Name} stays valid")
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])
        self.assertFalse(self.doc.mustExecute())
        messages = [o.getStatusString() for o in (sketch, boss, fillet, self.body)]
        self.recompute()
        self.assertEqual([o.getStatusString() for o in (sketch, boss, fillet, self.body)], messages)
        self.assertEqual([o.Name for o in self.doc.Objects if "Touched" in o.State], [])

        block.Suppressed = False
        self.recompute()
        self.assertValid(block, sketch, boss, fillet)
        self.assertBody(expected)

    def testDeletedSketchPlaneFailsTheSketch(self):
        """Round 8 (J20, B1): a datum plane 10 above the origin's XY plane, a sketch on it (a
        circle of radius 3 over the block's middle) and a 5 mm pad from it: 4000 + 45 pi. The
        plane deleted, the sketch keeps no support; as Onshape's sketch whose plane is gone, it
        fails saying so (not left where it was), the pad fails through it and contributes
        nothing: the Body is the block. A second recompute keeps that. Undo of the delete heals."""
        self.doc.UndoMode = 1
        block = self.block()
        [xy] = [f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane"]
        plane = self.body.newObject("PartDesign::Plane", "Plane")
        plane.AttachmentSupport = [(xy, "")]
        plane.MapMode = "FlatFace"
        plane.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        sketch = models.sketch(self.doc, "OnPlane", [models.circle(10, 10, 3)])
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
        pad = models.pad(self.body, sketch, 5, "OnPlanePad")
        self.recompute()
        self.assertValid(plane, sketch, pad)
        self.assertBody(BLOCK + 45 * math.pi)

        self.doc.openTransaction("Delete")
        self.body.removeObject(plane)
        self.doc.removeObject(plane.Name)
        self.doc.commitTransaction()
        self.assertEqual(sketch.AttachmentSupport, [])
        # The delete itself doesn't position it and mark it in error; the recompute does (R8-2)
        self.assertNotIn("Invalid", sketch.State)
        self.recompute()
        self.assertFalse(sketch.isValid(), "the sketch stays valid with its plane gone")
        self.assertIn("The sketch plane is missing", sketch.getStatusString())
        self.assertFalse(pad.isValid(), "the pad stays valid on a sketch with no plane")
        self.assertValid(block)
        self.assertBody(BLOCK)
        self.recompute()
        self.assertFalse(sketch.isValid())
        self.assertBody(BLOCK)

        self.doc.undo()
        self.recompute()
        plane = self.doc.getObject("Plane")
        self.assertIsNotNone(plane)
        self.assertValid(plane, sketch, pad)
        self.assertBody(BLOCK + 45 * math.pi)

    def testSuppressedLeadDoesNotHideAFailedFirstPad(self):
        """The lead is a pocket a reorder left at the top, suppressed to get the Body back."""
        hole = self.hole()
        hole.Suppressed = True
        self.assertALeadThatMakesNothingHidesNoFailure(hole)

    def testEmptyBooleanLeadDoesNotHideAFailedFirstPad(self):
        """The lead is a Boolean without a tool: valid, on the empty shape."""
        lead = self.body.newObject("PartDesign::Boolean", "Empty")
        self.assertALeadThatMakesNothingHidesNoFailure(lead)

    def testSolidlessBaseFeatureDoesNotHideAFailedFirstPad(self):
        """The lead is the FeatureBase of a Part::Plane: valid, a face, no solid, so a pass-through
        after it is the empty shape as for a null lead (decision 259: the stop asks the
        pass-through's own question; review pr579-r4g T-R4G-1)."""
        plane = self.doc.addObject("Part::Plane", "Sheet")
        plane.Length = plane.Width = 50
        plane.Placement.Base = V(200, 0, 0)
        self.body.BaseFeature = plane
        self.recompute()
        self.assertALeadThatMakesNothingHidesNoFailure(self.body.Group[0])

    def assertALeadThatFailsOnNothingPassesNothing(self, lead):
        """`lead`, the Body's first solid feature, is of a kind whose result on nothing is
        nothing, and it fails there. Its empty pass-through is exactly that result, so it is
        claimed, and the block and the boss compute below it (ops#591, ops#127's park; decision
        262 (1); since ops#579 the Body stopped). The block takes its length from a Part box
        outside the Body; the box fails: the block's own pass-through would be the empty shape,
        so the Body stops (the claimed lead hides no failed first Pad, review pr579-r4 R4-1).
        Repaired, the Body computes below the lead again; the lead removed, the same."""
        gauge = models.box(self.doc, "Gauge", (2, 2, 10), at=(100, 0, 0))
        block = self.block()
        block.setExpression("Length", f"{gauge.Name}.Height")
        boss = self.boss(block)
        mirror = self.mirrorOf(boss)
        self.recompute()
        self.assertFailed(lead)
        self.assertTrue(lead.Shape.isNull())
        self.assertValid(block, boss, mirror)
        self.assertBody(BLOCK + BOSS)
        self.assertVolume(mirror, BLOCK + BOSS)

        gauge.Length = 0
        self.recompute()
        self.assertFirstFeatureStopped(block, boss, mirror, f"'{gauge.Label}' has an error")

        gauge.Length = 2
        self.recompute()
        self.assertFailed(lead)
        self.assertValid(block, boss, mirror)
        self.assertBody(BLOCK + BOSS)

        self.body.removeObject(lead)
        self.doc.removeObject(lead.Name)
        self.recompute()
        self.assertValid(block, boss)
        self.assertBody(BLOCK + BOSS)

    def testFailedSubtractiveLeadPassesNothing(self):
        """The lead is a pocket, with nothing to cut: a hole a reorder left at the top."""
        self.assertALeadThatFailsOnNothingPassesNothing(self.hole())

    def testFailedSubtractivePrimitiveLeadPassesNothing(self):
        """The lead is a subtractive box, without a base feature."""
        box = self.body.newObject("PartDesign::SubtractiveBox", "Cut")
        box.Placement.Base = V(2, 2, 7)
        self.assertALeadThatFailsOnNothingPassesNothing(box)

    def testFailedDressUpLeadPassesNothing(self):
        """The lead is a chamfer, with nothing to chamfer."""
        chamfer = self.body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Size = 1
        self.assertALeadThatFailsOnNothingPassesNothing(chamfer)

    def testDressUpLeadOnAFailedOutsideBaseStopsTheBody(self):
        """The Body's first solid feature is a fillet whose Base, set from Python, is an edge of a
        scripted solid outside the Body (its BaseFeature stays None, so its base is that solid).
        The boss after it is on the fillet. The solid fails and clears its shape: the fillet's
        pass-through is empty, but its base isn't absent, it is an unclaimed failure, so the boss
        and the Body stop instead of computing on nothing (review pr591-r1 T1; decision 268).
        Repaired, everything computes."""

        class EmptyingStock:
            """A 20 x 20 x 10 block, or with Size 0 no shape and an error."""

            def __init__(self, obj):
                obj.addProperty("App::PropertyLength", "Size")
                obj.Proxy = self

            def execute(self, obj):
                if obj.Size.Value <= 0:
                    obj.Shape = Part.Shape()
                    raise RuntimeError("no stock")
                obj.Shape = Part.makeBox(20, 20, 10)

        stock = self.doc.addObject("Part::FeaturePython", "Stock")
        EmptyingStock(stock)
        stock.Size = 20
        self.recompute()
        upright = elementWhere(
            stock.Shape,
            "Edge",
            lambda e: abs(e.CenterOfMass.x) < TOL and abs(e.CenterOfMass.y) < TOL,
        )
        fillet = self.body.newObject("PartDesign::Fillet", "Lead")
        fillet.Base = (stock, [upright])
        fillet.Radius = 1
        boss = self.topBoss("Boss", 1)
        self.recompute()
        self.assertIsNone(fillet.BaseFeature)
        self.assertValid(fillet, boss)
        rounded = BLOCK - (1 - math.pi / 4) * 10
        self.assertBody(rounded + BOSS)

        stock.Size = 0
        self.recompute()
        self.assertStopped(fillet)
        self.assertStopped(boss, f"'{fillet.Label}', which has an error")
        self.assertStopped(self.body)
        self.assertBodyShowsNothing()

        # The edge is picked again: a reference into a history-less scripted solid doesn't survive
        # its failure under C2's naming (ops#624)
        stock.Size = 20
        self.recompute()
        fillet.Base = (stock, [upright])
        self.recompute()
        self.assertValid(fillet, boss)
        self.assertBody(rounded + BOSS)

    def testAPocketWithoutABaseAfterTheBlockStopsTheBody(self):
        """A pocket after the block has its BaseFeature cleared from Python, and the boss after it
        is on the pocket. The pocket fails with nothing to cut. A solid comes before it, so its
        empty pass-through isn't its result on the Body: it isn't claimed, and the boss and the
        Body stop instead of computing on nothing (review pr591s-r1: a transform added before
        another solid is linked only in its execute())."""
        block = self.block()
        hole = self.hole()
        boss = self.topBoss("Boss", 1)
        self.recompute()
        self.assertBody(BLOCK - math.pi * 27 + BOSS)

        hole.BaseFeature = None
        self.recompute()
        self.assertStopped(hole)
        self.assertStopped(boss, f"'{hole.Label}', which has an error")
        self.assertStopped(self.body)
        self.assertValid(block)

    def testFailedScriptedSubtractiveLeadStopsTheBody(self):
        """The lead is a scripted subtractive feature whose execute() fails: its result on
        nothing is its script's, not known to be nothing, so it isn't claimed (ops#591)."""

        class Failing:
            def __init__(self, obj):
                obj.Proxy = self

            def execute(self, obj):
                raise RuntimeError("the script fails")

        lead = self.body.newObject("PartDesign::FeatureSubtractivePython", "Scripted")
        Failing(lead)
        self.assertFirstFeatureOfAnyKindStops(lead)

    def linkedStock(self):
        """A 20 x 20 x 10 Part box outside the Body, an App::Link to it, and the name of the box's
        vertical edge at x = y = 0."""
        stock = models.box(self.doc, "Stock", (20, 20, 10))
        link = self.doc.addObject("App::Link", "StockLink")
        link.LinkedObject = stock
        self.recompute()
        upright = elementWhere(
            stock.Shape,
            "Edge",
            lambda e: abs(e.CenterOfMass.x) < TOL and abs(e.CenterOfMass.y) < TOL,
        )
        return stock, link, upright

    def testDressUpLeadOnABaseThroughALinkStopsTheBody(self):
        """The Body's first solid feature is a fillet on an outside box's edge (Base set from
        Python), the boss after it. Its Base is then pointed at the same edge through an App::Link
        to the box: the fillet fails ("not a Part object"), and its base resolves to nothing, but
        it names one, so the boss and the Body stop instead of computing on nothing (review
        pr591s-r1b; design notes\\park-design.md 5 (N)). Pointed back, everything computes."""
        stock, link, upright = self.linkedStock()
        fillet = self.body.newObject("PartDesign::Fillet", "Lead")
        fillet.Base = (stock, [upright])
        fillet.Radius = 1
        boss = self.topBoss("Boss", 1)
        self.recompute()
        self.assertValid(fillet, boss)
        rounded = BLOCK - ROUND
        self.assertBody(rounded + BOSS)

        fillet.Base = (link, [upright])
        self.recompute()
        self.assertFalse(fillet.isValid())
        self.assertStopped(boss, f"'{fillet.Label}', which has an error")
        self.assertStopped(self.body)
        self.assertBodyShowsNothing()

        fillet.Base = (stock, [upright])
        self.recompute()
        self.assertValid(fillet, boss)
        self.assertBody(rounded + BOSS)

    def testPatternLeadWhoseOriginalIsNotAPartObjectStopsTheBody(self):
        """A pattern of the boss, moved above it (its Originals parked: claimed, the boss
        computes). Its Originals are then set from Python to an App::Link to an outside box: the
        pattern's base resolves to nothing, but it names one, so the boss after it and the Body
        stop (design notes\\park-design.md 5 (N), the pattern form of review pr591s-r1b). A
        pattern given only the Link from the start isn't a solid feature, so it can't come first."""
        stock, link, upright = self.linkedStock()
        boss = self.topBoss("Boss", 1)
        self.recompute()
        pattern = self.body.newObject("PartDesign::LinearPattern", "Lead")
        pattern.Direction = (models.originFeature(self.body, "X_Axis"), [""])
        pattern.Length = 30
        pattern.Occurrences = 2
        pattern.Originals = [boss]
        self.recompute()
        self.body.reorderObject([pattern], None, True)
        self.recompute()
        self.assertEqual(boss.BaseFeature, pattern)
        self.assertFailed(pattern, "Originals refers to")
        self.assertValid(boss)
        self.assertBody(BOSS)

        pattern.Originals = [link]
        self.recompute()
        self.assertFalse(pattern.isValid())
        self.assertStopped(boss, f"'{pattern.Label}', which has an error")
        self.assertStopped(self.body)

    def testTwoLeadsBothPassNothing(self):
        """A subtractive box, then a pocket on it, both before the block: each fails with nothing
        to cut. The pocket's base is the box, a claimed failure whose output is the empty shape,
        so the pocket is claimed too, and the block computes (design notes\\park-design.md 5
        (B1))."""
        box = self.body.newObject("PartDesign::SubtractiveBox", "Cut")
        box.Placement.Base = V(2, 2, 7)
        hole = self.hole()
        block = self.block()
        self.recompute()
        self.assertEqual(hole.BaseFeature, box)
        self.assertFailed(box)
        self.assertFailed(hole)
        self.assertValid(block)
        self.assertBody(BLOCK)

    def testPocketAfterASuppressedLeadPassesNothing(self):
        """A suppressed boss, then a pocket on it, before the block: the pocket fails with nothing
        to cut on a Valid base without a solid, so it passes the empty shape on and the block
        computes (design notes\\park-design.md 5 (B1); decision 258)."""
        lead = self.topBoss("Lead", 1)
        lead.Suppressed = True
        hole = self.hole()
        block = self.block()
        self.recompute()
        self.assertEqual(hole.BaseFeature, lead)
        self.assertFailed(hole)
        self.assertValid(lead, block)
        self.assertBody(BLOCK)

    # -- the park (ops#596, decisions 275 (2), 276, 281) -----------------------------------------

    def parkedBoss(self):
        """The block, the hole in its top, then the boss on its x = 20 face (its sketch attached
        to the block: W16's model), moved to the top of the Body: the reorder sets the sketch's
        attachment aside (ops#127)."""
        block = self.block()
        hole = self.hole()
        boss = self.boss(block)
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS)
        self.body.reorderObject([boss], None, True)
        self.recompute()
        self.assertEqual(block.BaseFeature, boss)
        return block, hole, boss

    def assertParked(self, boss):
        """The boss's sketch fails naming the park, the boss naming its sketch, and the boss
        passes the empty shape on (claimed: not touched)."""
        sketch = boss.Profile[0]
        self.assertEqual(sketch.AttachmentSupport, [])
        self.assertFailed(sketch, "AttachmentSupport refers to", "which now comes after")
        self.assertFailed(boss, f"'{sketch.Label}', which has an error")
        self.assertTrue(boss.Shape.isNull())

    def testParkedPadPassesNothing(self):
        """W16: a boss whose sketch sits on the block's face is moved above the block. Its failure
        is the park's, so it passes the empty shape on: the block computes as the Body's first
        solid and the hole cuts it (Onshape fails only the moved feature: ops#596, decisions 275
        (2) and 276). The block then fails through an outside input: it isn't parked and passes
        the empty shape, so the Body stops (decision 281; review pr579-r4 R4-1), the boss still
        parked. Repaired, the Body computes below the boss; moved back, the boss's attachment is
        put back and everything computes."""
        gauge = models.box(self.doc, "Gauge", (2, 2, 10), at=(100, 0, 0))
        block, hole, boss = self.parkedBoss()
        block.setExpression("Length", f"{gauge.Name}.Height")
        self.recompute()
        self.assertIsNone(boss.BaseFeature)
        self.assertParked(boss)
        self.assertValid(block, hole)
        self.assertBody(BLOCK - HOLE)

        gauge.Length = 0
        self.recompute()
        self.assertParked(boss)
        self.assertStopped(block, f"'{gauge.Label}' has an error")
        self.assertStopped(hole, f"'{block.Label}', which has an error")
        self.assertStopped(self.body)

        gauge.Length = 2
        self.recompute()
        self.assertParked(boss)
        self.assertValid(block, hole)
        self.assertBody(BLOCK - HOLE)

        self.body.reorderObject([boss], hole, True)
        self.recompute()
        self.assertEqual(boss.BaseFeature, hole)
        self.assertEqual(boss.Profile[0].AttachmentSupport[0][0], block)
        self.assertValid(boss.Profile[0], boss, block, hole)
        self.assertBody(BLOCK - HOLE + BOSS)

    def testAStockReadingAParkedSketchStopsTheBody(self):
        """The boss parked above the block; the block is then given the parked boss sketch's
        normal as its direction (the GUI's "Select reference..."). The block fails naming the
        sketch, whose record refers to the block itself: the block wasn't moved and the hole was
        built on it, so it isn't parked and the Body stops (review pr596-r1
        StockReadsParkedSketch). The link removed, the Body computes below the boss."""
        block, hole, boss = self.parkedBoss()
        block.ReferenceAxis = (boss.Profile[0], ["N_Axis"])
        self.recompute()
        self.assertParked(boss)
        self.assertStopped(block, f"'{boss.Profile[0].Label}', which has an error")
        self.assertStopped(hole, f"'{block.Label}', which has an error")
        self.assertStopped(self.body)

        block.ReferenceAxis = None
        self.recompute()
        self.assertParked(boss)
        self.assertValid(block, hole)
        self.assertBody(BLOCK - HOLE)

    def testAStockReadingASketchParkedPastItStopsTheBody(self):
        """The same with the boss's sketch on the x = 20 face of a riser after the block, so the
        sketch's record refers to a feature after the block: the block still isn't parked, the boss
        reads the sketch first (review pr596s-r1). The Body stops; the link removed, it computes."""
        block = self.block()
        self.hole()
        riser = self.topBoss("Riser", 1)
        boss = self.boss(riser)
        self.recompute()
        self.assertBody(BLOCK - HOLE + 2 * BOSS)
        self.body.reorderObject([boss], None, True)
        self.recompute()
        self.assertParked(boss)
        self.assertValid(block, riser)
        self.assertBody(BLOCK - HOLE + BOSS)

        block.ReferenceAxis = (boss.Profile[0], ["N_Axis"])
        self.recompute()
        self.assertStopped(block, f"'{boss.Profile[0].Label}', which has an error")
        self.assertStopped(riser)
        self.assertStopped(self.body)

        block.ReferenceAxis = None
        self.recompute()
        self.assertValid(block, riser)
        self.assertBody(BLOCK - HOLE + BOSS)

    def testParkedPadWhoseSketchIsOnADatumPassesNothing(self):
        """The boss's sketch sits on a datum plane on the block's x = 20 face. The boss moved above
        the block takes the plane and the sketch with it, and the plane's attachment is set aside:
        the boss's failure is the park's through its sketch and the plane (design
        notes\\park-design.md 5 (P)), so the block computes. Moved back, everything computes."""
        block = self.block()
        hole = self.hole()
        self.recompute()
        face = elementWhere(
            block.Shape,
            "Face",
            lambda f: abs(f.CenterOfMass.x - 20) < TOL and abs(abs(f.normalAt(0, 0).x) - 1) < TOL,
        )
        plane = self.body.newObject("PartDesign::Plane", "BossPlane")
        plane.AttachmentSupport = [(block, face)]
        plane.MapMode = "FlatFace"
        sketch = models.sketch(self.doc, "BossSketch", models.rectangle(-2.5, -2.5, 2.5, 2.5))
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(plane, "")]
        sketch.MapMode = "FlatFace"
        boss = models.pad(self.body, sketch, 5, "Boss")
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS)

        self.body.reorderObject([boss], None, True)
        self.recompute()
        self.assertEqual(plane.AttachmentSupport, [])
        self.assertFailed(plane, "which now comes after")
        self.assertFailed(sketch, f"'{plane.Label}', which has an error")
        self.assertFailed(boss, f"'{sketch.Label}', which has an error")
        self.assertValid(block, hole)
        self.assertBody(BLOCK - HOLE)

        self.body.reorderObject([boss], hole, True)
        self.recompute()
        self.assertValid(plane, sketch, boss, block, hole)
        self.assertBody(BLOCK - HOLE + BOSS)

    def testReferencesBelowAParkedPadFollowAnEdit(self):
        """A sketch on the block's top face, taken before the boss is parked above the block: the
        block made taller, the sketch follows. The parked boss passes the empty shape and is no
        shape input of anything (design notes\\park-design.md 5 (R), decision 275 (4))."""
        block = self.block()
        self.hole()
        top = self.topSketch(block)
        boss = self.boss(block)
        self.recompute()
        self.body.reorderObject([boss], None, True)
        self.recompute()
        self.assertParked(boss)
        self.assertAt(top, 10)

        block.Length = 12
        self.recompute()
        self.assertValid(block)
        self.assertAt(top, 12)

    def testReferencesBelowAParkedLeadFollowAnEdit(self):
        """The same with the hole parked above the block, its sketch on the block's top face."""
        block = self.block()
        top = self.topSketch(block)
        hole = models.pocket(self.body, self.topSketch(block, "HoleSketch"), 1, "Hole")
        self.recompute()
        self.assertValid(hole)
        self.body.reorderObject([hole], None, True)
        self.recompute()
        self.assertFailed(hole)
        self.assertBody(BLOCK)
        self.assertAt(top, 10)

        block.Length = 12
        self.recompute()
        self.assertAt(top, 12)
        self.assertBody(BLOCK * 1.2)

    def testFilletBelowAParkedPocketHoldsAtThePark(self):
        """A fillet on the boss's vertical edge; the hole then parked above the block: the fillet
        keeps its edge and the Body computes without the hole (design notes\\park-design.md 5
        (R); ParkedPocketReopened's park step)."""
        self.block()
        hole = self.hole()
        boss = self.topBoss("Boss", 1)
        self.recompute()
        edge = elementWhere(boss.Shape, "Edge", lambda e: isVerticalLineAt(e, 1, 1) and e.Length > 4)
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, [edge])
        fillet.Radius = 1
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS - ROUND / 2)

        self.body.reorderObject([hole], None, True)
        self.recompute()
        self.assertFailed(hole)
        self.assertValid(boss, fillet)
        self.assertBody(BLOCK + BOSS - ROUND / 2)

    def testFilletOnAParkedPadsEdgeBreaks(self):
        """A fillet on the boss's edge after it, the boss then parked above the block: the edge
        isn't there while the boss is parked, so the fillet fails, and the Body computes below it
        (design notes\\park-design.md 6.3). Moved back, the fillet computes."""
        block = self.block()
        hole = self.hole()
        boss = self.boss(block)
        self.recompute()
        # The boss's outer edge along z with the largest y
        outer = [
            (e.CenterOfMass.y, f"Edge{i + 1}")
            for i, e in enumerate(boss.Shape.Edges)
            if isinstance(e.Curve, Part.Line)
            and abs(e.CenterOfMass.x - 25) < TOL
            and abs(abs(e.Curve.Direction.z) - 1) < TOL
        ]
        edge = max(outer)[1]
        fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (boss, [edge])
        fillet.Radius = 1
        self.recompute()
        self.assertBody(BLOCK - HOLE + BOSS - ROUND / 2)

        self.body.reorderObject([boss], None, True)
        self.recompute()
        self.assertParked(boss)
        self.assertFalse(fillet.isValid())
        self.assertValid(block, hole)
        self.assertVolume(hole, BLOCK - HOLE)

        self.body.reorderObject([boss], hole, True)
        self.recompute()
        self.assertValid(boss, fillet)
        self.assertBody(BLOCK - HOLE + BOSS - ROUND / 2)

    def testTwoParkedAboveTheStockBothPassNothing(self):
        """The boss parked above the block, then the hole moved above the block too: first above
        the boss (the boss on the hole's empty pass-through, (P) on (B1)), then between the boss
        and the block (the hole on the boss's, (K) on (B1)). Both fail, the block computes."""
        block, hole, boss = self.parkedBoss()
        self.body.reorderObject([hole], None, True)
        self.recompute()
        self.assertEqual(boss.BaseFeature, hole)
        self.assertFailed(hole)
        self.assertParked(boss)
        self.assertValid(block)
        self.assertBody(BLOCK)

        self.body.reorderObject([hole], boss, True)
        self.recompute()
        self.assertEqual(hole.BaseFeature, boss)
        self.assertEqual(block.BaseFeature, hole)
        self.assertFailed(hole)
        self.assertParked(boss)
        self.assertValid(block)
        self.assertBody(BLOCK)

    def testParkedPadReopened(self):
        """Saved and reopened while the boss is parked: the same state, and moved back, everything
        computes (the claim reads only restored links and records)."""
        self.parkedBoss()
        folder = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "parked.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        name = self.doc.Name
        self.addCleanup(lambda: name in App.listDocuments() and App.closeDocument(name))
        self.body = self.doc.getObject("Body")
        block, hole, boss = (self.doc.getObject(n) for n in ("Block", "Hole", "Boss"))
        self.recompute()
        self.assertParked(boss)
        self.assertValid(block, hole)
        self.assertBody(BLOCK - HOLE)

        self.body.reorderObject([boss], hole, True)
        self.recompute()
        self.assertValid(boss, block, hole)
        self.assertBody(BLOCK - HOLE + BOSS)

    def testParkedHoleOnADatumSketchPassesNothing(self):
        """The hole moved above the block, then its sketch attached to a datum plane on the Body's
        XY plane at the top: the plane holds no solid, so the hole names no base and stays claimed
        (decision 275 (3); review pr591s-r1b LeadPocketSketchOnADatumPlane went loud on it)."""
        block = self.block()
        hole = self.hole()
        self.recompute()
        self.body.reorderObject([hole], None, True)
        self.recompute()
        plane = self.body.newObject("PartDesign::Plane", "Datum")
        plane.AttachmentSupport = [(models.originFeature(self.body, "XY_Plane"), [""])]
        plane.MapMode = "FlatFace"
        plane.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        self.recompute()
        sketch = hole.Profile[0]
        sketch.AttachmentSupport = [(plane, [""])]
        sketch.MapMode = "FlatFace"
        self.recompute()
        self.assertValid(plane, sketch, block)
        self.assertFailed(hole)
        self.assertBody(BLOCK)

    def testParkedHoleWhoseSketchIsStoppedByAnOutsideInputPassesNothing(self):
        """The hole moved above the block; its sketch's placement then reads an outside box that
        fails: the sketch stays stopped (decision 262 (2)), the hole fails naming it, and it is
        still the Body's first solid with nothing to cut: claimed, and the block computes."""
        gauge = models.box(self.doc, "Gauge", (2, 2, 10), at=(100, 0, 0))
        block = self.block()
        hole = self.hole()
        self.recompute()
        self.body.reorderObject([hole], None, True)
        sketch = hole.Profile[0]
        sketch.setExpression("Placement.Base.z", f"{gauge.Name}.Height")
        self.recompute()
        self.assertFailed(hole)
        self.assertBody(BLOCK)

        gauge.Length = 0
        self.recompute()
        self.assertStopped(sketch, f"'{gauge.Label}' has an error")
        self.assertFailed(hole, f"'{sketch.Label}', which has an error")
        self.assertValid(block)
        self.assertBody(BLOCK)

    # -- the chain rule (decision 262) -----------------------------------------------------------

    def topBoss(self, name, x, base=None):
        """A 5 mm cube on the block's top at x .. x + 5, y 1 .. 6: its sketch is placed, not
        attached, so it reads nothing of the Body."""
        sketch = models.sketch(
            self.doc, f"{name}Sketch", models.rectangle(x, 1, x + 5, 6), self.body, z=10
        )
        return models.pad(self.body, sketch, 5, name)

    def testClaimDoesNotFlipWhenAnOffChainMemberRecovers(self):
        """An orphan pad far off (BaseFeature None, from Python) sits between the boss and the
        cap, whose base is the boss. The orphan fails; in the next edit it is repaired and the
        boss fails. The boss's claim reads only its own chain (the block, Valid), so the orphan
        recomputing Valid in between can't change it: the boss passes the block through and the
        cap and the Body compute on it in the same recompute (review pr579-r4h T-R4H-1: a
        Body-wide test read the orphan, and the cap ran on the boss's last shape). The orphan is
        after the boss in the Body, then before it."""
        self.orphanFlip(orphanFirst=False)
        self.tearDown()
        self.setUp()
        self.orphanFlip(orphanFirst=True)

    def orphanFlip(self, orphanFirst):
        def orphanPad():
            sketch = models.sketch(
                self.doc, "OrphanSketch", models.rectangle(100, 0, 105, 5), self.body
            )
            return models.pad(self.body, sketch, 5, "Orphan")

        block = self.block()
        orphan = orphanPad() if orphanFirst else None
        boss = self.topBoss("Boss", 1)
        orphan = orphan or orphanPad()
        cap = self.topBoss("Cap", 13)
        orphan.BaseFeature = None
        boss.BaseFeature = block
        cap.BaseFeature = boss
        self.recompute()
        self.assertBody(BLOCK + 2 * BOSS)

        orphan.Length = 0
        self.recompute()
        self.assertStopped(orphan)
        self.assertBody(BLOCK + 2 * BOSS)

        orphan.Length = 5
        boss.Length = 0
        self.recompute()
        self.assertValid(orphan, cap)
        self.assertFailed(boss)
        self.assertVolume(boss, BLOCK)
        self.assertBody(BLOCK + BOSS)

    def testAStaleSuccessorDoesNotStopTheBody(self):
        """Two bosses are added while the block is broken: each fails naming its input without
        running, its shape null. Then the block is repaired and the first boss fails in the same
        edit: its base is the block, Valid, so it passes the block through and the second boss
        computes on it. Its successor's state from before isn't read (review pr579-r4h T-R4H-2:
        the Body stayed stopped)."""
        block = self.block()
        self.recompute()
        block.Length = 0
        bossA = self.topBoss("BossA", 1)
        bossB = self.topBoss("BossB", 13)
        self.recompute()
        self.assertStopped(block)
        self.assertStopped(bossA, f"'{block.Label}', which has an error")
        self.assertStopped(bossB, f"'{bossA.Label}', which has an error")

        block.Length = 10
        bossA.Length = 0
        self.recompute()
        self.assertFailed(bossA)
        self.assertVolume(bossA, BLOCK)
        self.assertValid(block, bossB)
        self.assertBody(BLOCK + BOSS)
        self.recompute()
        self.assertBody(BLOCK + BOSS)

    def testTwoFailuresInAChainBothPassThrough(self):
        """T10 (decision 262 (3)): Pad2 takes its length from a Part box outside the Body, and
        Pad3 after it fails on its own in the same edit. Pad2 fails naming the box and passes the
        block through; Pad3's base is Pad2, a claimed failure whose shape is that pass-through, so
        Pad3 passes it on, and Pad4 and the Body compute on the block, both failures red with
        their own texts. Repaired, everything is back."""
        gauge = models.box(self.doc, "Gauge", (2, 2, 5), at=(100, 0, 0))
        self.block()
        pad2 = self.topBoss("Pad2", 1)
        pad2.setExpression("Length", f"{gauge.Name}.Height")
        pad3 = self.topBoss("Pad3", 7.5)
        pad4 = self.topBoss("Pad4", 14)
        self.recompute()
        self.assertBody(BLOCK + 3 * BOSS)

        gauge.Length = 0
        pad3.Length = 0
        self.recompute()
        self.assertStopped(gauge)
        self.assertFailed(pad2, f"'{gauge.Label}' has an error")
        text = self.assertFailed(pad3)
        self.assertNotIn("which has an error", text)
        for obj in (pad2, pad3):
            self.assertVolume(obj, BLOCK)
        self.assertValid(pad4)
        self.assertBody(BLOCK + BOSS)

        gauge.Length = 2
        pad3.Length = 5
        self.recompute()
        self.assertValid(gauge, pad2, pad3, pad4)
        self.assertBody(BLOCK + 3 * BOSS)

    def testAFailureOnAStoppedBaseStaysStopped(self):
        """The block and Pad2 after it both fail on their own in one edit. The block has no base,
        so it isn't passed through and keeps its last shape. Pad2's base holds a solid, but one
        no recompute made: the block's stale output. So Pad2 isn't claimed either: Pad2, Pad3,
        Pad4 and the Body fail naming their direct inputs (the chain rule's "current" half: a
        claim that asked only whether the base holds a solid would compute Pad3 on the stale
        block). The features keep their shapes, and the Body shows nothing (regen item 6).
        Repaired, everything computes."""
        block = self.block()
        pad2 = self.topBoss("Pad2", 1)
        pad3 = self.topBoss("Pad3", 7.5)
        pad4 = self.topBoss("Pad4", 14)
        self.recompute()
        self.assertBody(BLOCK + 3 * BOSS)

        block.Length = 0
        pad2.Length = 0
        self.recompute()
        self.assertStopped(block)
        self.assertStopped(pad2, f"'{block.Label}', which has an error")
        self.assertStopped(pad3, f"'{pad2.Label}', which has an error")
        self.assertStopped(pad4, f"'{pad3.Label}', which has an error")
        self.assertStopped(self.body)
        self.assertVolume(pad4, BLOCK + 3 * BOSS)
        self.assertBodyShowsNothing()

        block.Length = 10
        pad2.Length = 5
        self.recompute()
        self.assertValid(block, pad2, pad3, pad4)
        self.assertBody(BLOCK + 3 * BOSS)

    def testAMemberStoppedByAnOutsideInputStaysTouchedAndItsPadPassesThrough(self):
        """The boss's sketch in the Body takes a dimension from a Part box outside it. The box
        fails: the sketch fails naming it and, its input an unclaimed failure, stays touched; the
        boss fails naming the sketch, and its base, the block, is Valid, so it passes the block
        through and the Body continues (decision 262 (2): before, the sketch was claimed and left
        alone). Repaired, everything computes."""
        gauge = models.box(self.doc, "Gauge", (2, 5, 2), at=(100, 0, 0))
        self.block()
        boss = self.topBoss("Boss", 1)
        sketch = boss.Profile[0]
        width = sketch.addConstraint(Sketcher.Constraint("DistanceX", 0, 1, 0, 2, 5))
        sketch.renameConstraint(width, "Width")
        sketch.setExpression(".Constraints.Width", f"{gauge.Name}.Width")
        self.recompute()
        self.assertValid(sketch, boss)
        self.assertBody(BLOCK + BOSS)

        gauge.Length = 0
        self.recompute()
        self.assertStopped(gauge)
        self.assertStopped(sketch, f"'{gauge.Label}' has an error")
        self.assertFailed(boss, f"'{sketch.Label}', which has an error")
        self.assertVolume(boss, BLOCK)
        self.assertBody(BLOCK)

        gauge.Length = 2
        self.recompute()
        self.assertValid(gauge, sketch, boss)
        self.assertBody(BLOCK + BOSS)

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

    # -- ops#487: the base stays where it was ----------------------------------------------------

    def notch(self, name="Notch", at=(-1, 9, 4), degrees=0):
        """An unattached 2 mm subtractive cube over the block's x = 0 face: its own Placement is
        the location of its shape, which a feature after it takes as its base."""
        box = self.body.newObject("PartDesign::SubtractiveBox", name)
        box.Length = box.Width = box.Height = 2
        box.Placement = App.Placement(V(*at), App.Rotation(V(0, 0, 1), degrees))
        return box

    def emptyPad(self):
        """A pad on a sketch with nothing in it: it fails at once, and never had a Placement of
        its own (identity)."""
        sketch = models.sketch(self.doc, "EmptySketch", [], self.body)
        return models.pad(self.body, sketch, 5, "EmptyPad")

    def assertSameShape(self, actual, expected):
        """The same solid in the same place: bounding box, volume, and nothing of either outside
        the other."""
        a = actual.optimalBoundingBox(False, False)
        b = expected.optimalBoundingBox(False, False)
        for x, y in zip(
            (a.XMin, a.YMin, a.ZMin, a.XMax, a.YMax, a.ZMax),
            (b.XMin, b.YMin, b.ZMin, b.XMax, b.YMax, b.ZMax),
        ):
            self.assertAlmostEqual(x, y, delta=1e-7, msg=f"{a} != {b}")
        self.assertAlmostEqual(actual.Volume, expected.Volume, delta=1e-4)
        self.assertLess(actual.cut(expected).Volume, 1e-4)
        self.assertLess(expected.cut(actual).Volume, 1e-4)

    def assertPassesThrough(self, failed, base):
        self.assertSameShape(failed.Shape, base.Shape)
        inBody = base.Shape.transformed(self.body.Placement.toMatrix())
        self.assertSameShape(self.body.Shape, inBody)

    def testFailureAfterAPlacedFeatureKeepsItsBase(self):
        """A pad on an empty sketch after a notch fails and passes the notched block on where it
        is, not moved by minus the notch's Placement; a hole after it cuts the top as it would
        without the pad (ops#487, the issue's model)."""
        self.block()
        notch = self.notch()
        self.recompute()
        self.assertBody(BLOCK - 4)
        pad = self.emptyPad()
        hole = self.hole()
        self.recompute()
        self.assertFailed(pad)
        self.assertTrue(pad.Placement.isIdentity(), pad.Placement)
        self.assertSameShape(pad.Shape, notch.Shape)
        self.assertValid(hole)
        self.assertBody(BLOCK - 4 - HOLE)
        shape = self.body.Shape
        self.assertFalse(shape.isInside(V(10, 10, 8), TOL, True))  # the hole
        self.assertTrue(shape.isInside(V(10, 10, 6), TOL, True))  # under it
        self.assertFalse(shape.isInside(V(0.5, 10, 5), TOL, True))  # the notch
        self.assertTrue(shape.isInside(V(0.5, 5, 5), TOL, True))

    def testFailedPrimitiveAfterATurnedPrimitive(self):
        """A turned subtractive box elsewhere fails (an expression in error) after a turned notch:
        its shape is the notched block in place, its own Placement stays (ops#487)."""
        self.block()
        notch = self.notch(degrees=30)
        other = self.notch("Other", (9, -1, 4), 45)
        self.recompute()
        self.assertValid(notch, other)
        placement = App.Placement(other.Placement)
        other.setExpression("Width", "Block.NoSuchProperty")
        self.recompute()
        self.assertFailed(other, "NoSuchProperty")
        self.assertTrue(other.Placement.isSame(placement, 1e-12), other.Placement)
        self.assertPassesThrough(other, notch)

    def testFailedBooleanAfterAPlacedFeature(self):
        """A Boolean's Placement stays at identity; one that fails (an expression in error) after
        the notch passes the notched block on in place (ops#487)."""
        self.block()
        notch = self.notch()
        tool = models.body(self.doc)
        toolSketch = models.sketch(self.doc, "ToolSketch", models.rectangle(5, 5, 8, 8), tool, z=10)
        models.pad(tool, toolSketch, 3, "Tool")
        boolean = self.body.newObject("PartDesign::Boolean", "Boolean")
        boolean.addObject(tool)
        self.recompute()
        self.assertValid(boolean)
        self.assertBody(BLOCK - 4 + 27)
        boolean.setExpression("Refine", "Block.NoSuchProperty")
        self.recompute()
        self.assertFailed(boolean, "NoSuchProperty")
        self.assertPassesThrough(boolean, notch)

    def testFailedDressUpAndPatternThatNeverRan(self):
        """A fillet and a pattern that fail before they ever computed have no Placement of their
        own yet: each passes the notched block on in place (ops#487)."""
        self.block()
        notch = self.notch()
        self.recompute()
        fillet = self.body.newObject("PartDesign::Fillet", "EdgeFillet")
        edge = elementWhere(notch.Shape, "Edge", lambda e: isVerticalLineAt(e, 20, 20))
        fillet.Base = (notch, [edge])
        fillet.setExpression("Radius", "Block.NoSuchProperty")
        self.recompute()
        self.assertFailed(fillet, "NoSuchProperty")
        self.assertPassesThrough(fillet, notch)

        self.doc.removeObject(fillet.Name)
        self.body.Tip = notch
        pattern = self.body.newObject("PartDesign::LinearPattern", "Pattern")
        pattern.Originals = [notch]
        pattern.Direction = (models.originFeature(self.body, "Y_Axis"), [""])
        pattern.Occurrences = 2
        pattern.setExpression("Length", "Block.NoSuchProperty")
        self.body.Tip = pattern
        self.recompute()
        self.assertFailed(pattern, "NoSuchProperty")
        self.assertPassesThrough(pattern, notch)

    def testFailureInAPlacedBody(self):
        """The same pad on an empty sketch in a Body that is moved and turned: the pad's shape is
        the notched block in the Body's coordinates, and the Body's is that moved by the Body
        (ops#487)."""
        self.body.Placement = App.Placement(V(100, 0, 0), App.Rotation(V(0, 0, 1), 30))
        self.block()
        notch = self.notch()
        pad = self.emptyPad()
        self.recompute()
        self.assertFailed(pad)
        self.assertPassesThrough(pad, notch)

    # -- ops#549: rule PT and suppression as an editing state (PS) --------------------------------

    def topSketch(self, target, name="TopSketch"):
        """A sketch on `target`'s top face (z = 10 on the block)."""
        self.recompute()
        top = elementWhere(
            target.Shape,
            "Face",
            lambda f: f.normalAt(0, 0).z > 1 - TOL and abs(f.CenterOfMass.z - 10) < TOL,
        )
        sketch = models.sketch(self.doc, name, models.rectangle(1, 1, 3, 3))
        self.body.addObject(sketch)
        sketch.AttachmentSupport = [(target, top)]
        sketch.MapMode = "FlatFace"
        self.recompute()
        return sketch

    def assertAt(self, sketch, z):
        self.assertValid(sketch)
        self.assertAlmostEqual(sketch.Placement.Base.z, z, delta=1e-6)

    def ringSweep(self):
        """ops#549's C1 shape: a 4 x 4 plate padded 1 down; a Pipe sweeps its top face round a
        closed 30 x 20 ring in the XZ plane. The Pipe's corner (-2, -2, -2) carries the square
        sketch's bare vertex name, which the plate's corner (2, 2, 0) carries too. A datum point
        on the corner."""
        spine = models.sketch(
            self.doc,
            "Spine",
            models.polygon([(0, 0), (0, 20), (30, 20), (30, 0)]),
            self.body,
            placement=App.Placement(V(), App.Rotation(V(1, 0, 0), 90)),
        )
        square = models.sketch(self.doc, "Square", models.rectangle(-2, -2, 2, 2), self.body)
        plate = models.pad(self.body, square, 1, "Plate")
        plate.Reversed = True
        self.recompute()
        top = elementWhere(
            plate.Shape,
            "Face",
            lambda f: abs(f.CenterOfMass.z) < TOL and abs(f.normalAt(0, 0).z) > 1 - TOL,
        )
        sweep = self.body.newObject("PartDesign::AdditivePipe", "Sweep")
        sweep.Profile = (plate, [top])
        sweep.Spine = (spine, [])
        sweep.Transition = "Right corner"
        sweep.Refine = False
        self.recompute()
        self.assertValid(sweep)
        corner = elementWhere(
            sweep.Shape, "Vertex", lambda v: (v.Point - V(-2, -2, -2)).Length < TOL
        )
        point = self.body.newObject("PartDesign::Point", "CornerPoint")
        point.AttachmentSupport = [(sweep, corner)]
        point.MapMode = "Vertex"
        self.recompute()
        self.assertValid(point)
        return plate, sweep, point

    def testSuppressedFeaturesOwnElementsBreakAndReturn(self):
        """A fillet on a suppressed hole's rim breaks, as if the hole were removed; the hole back,
        it finds the same rim (ops#549 PS)."""
        self.block()
        hole = self.hole()
        self.recompute()
        fillet = self.body.newObject("PartDesign::Fillet", "RimFillet")
        rim = elementWhere(hole.Shape, "Edge", lambda e: isCircle(e, V(10, 10, 10), 3))
        fillet.Base = (hole, [rim])
        fillet.Radius = 1
        self.recompute()
        self.assertValid(fillet)

        hole.Suppressed = True
        self.recompute()
        self.assertFalse(fillet.isValid(), "the fillet holds an edge of the suppressed hole")

        hole.Suppressed = False
        self.recompute()
        self.assertValid(hole, fillet)
        sub = fillet.Base[1][0]
        self.assertTrue(isCircle(hole.Shape.getElement(sub), V(10, 10, 10), 3), sub)

    def testEditingWhileSuppressed(self):
        """A sketch on the top a suppressed hole cut into stays on the block's top, follows the
        block while the hole stays suppressed, and stays on the top when the hole is back
        (ops#549 PS, decision 213: suppression doesn't stop editing)."""
        if not self.solver:
            self.skipTest("rule PS is the reference solver's")
        self.block()
        hole = self.hole()
        sketch = self.topSketch(hole)
        self.assertAt(sketch, 10)

        hole.Suppressed = True
        self.recompute()
        self.assertAt(sketch, 10)
        block = self.doc.getObject("Block")
        block.Length = 12
        self.recompute()
        self.assertAt(sketch, 12)
        block.Length = 14
        self.recompute()
        self.assertAt(sketch, 14)

        # The hole's sketch follows the top, and the hole is back in it
        self.doc.getObject("HoleSketch").Placement = App.Placement(V(0, 0, 14), App.Rotation())
        hole.Suppressed = False
        self.recompute()
        self.assertValid(hole)
        self.assertAt(sketch, 14)

    def testBareNameOnASuppressedOrFailedFeatureBreaks(self):
        """C1 (ops#549): the datum on the Pipe's corner, whose bare name the plate's corner
        carries, breaks while the Pipe is suppressed (and stays broken through an edit), or while
        it fails; it is back on the corner when the Pipe computes."""
        if not self.solver:
            self.skipTest("rule PT is the reference solver's")
        plate, sweep, point = self.ringSweep()
        spine = sweep.Spine[0]

        sweep.Suppressed = True
        self.recompute()
        self.assertFalse(point.isValid(), "the datum holds the plate's corner")
        plate.Length = 2
        self.recompute()
        self.assertFalse(point.isValid(), "the datum holds the plate's corner after an edit")
        plate.Length = 1
        sweep.Suppressed = False
        self.recompute()
        self.assertValid(sweep, point)
        self.assertLess((point.Placement.Base - V(-2, -2, -2)).Length, 1e-6)

        empty = models.sketch(self.doc, "Empty", [], self.body)
        sweep.Spine = (empty, [])
        self.recompute()
        self.assertFalse(sweep.isValid())
        self.assertFalse(point.isValid(), "the datum holds the plate's corner")
        sweep.Spine = (spine, [])
        self.recompute()
        self.assertValid(sweep, point)
        self.assertLess((point.Placement.Base - V(-2, -2, -2)).Length, 1e-6)

    def testHugeClosureKeepsTheRecordsWorld(self):
        """PLAN decision 216: a record whose target is built from more objects than its marks hold
        (4096) keeps the suppressed ones' flags. A datum taken on the Plate's corner while the
        Pipe is suppressed (the vertex whose bare name the Pipe's corner carries) breaks when the
        Pipe is back, not quietly onto the Pipe's corner (C1 reversed)."""
        if not self.solver:
            self.skipTest("rule PS is the reference solver's")
        plate, sweep, point = self.ringSweep()
        many = self.doc.addObject("App::DocumentObjectGroup", "Many")
        many.Group = [self.doc.addObject("App::DocumentObjectGroup", f"M{i}") for i in range(4100)]
        sweep.addProperty("App::PropertyLinkGlobal", "Extra")
        sweep.Extra = many
        sweep.Suppressed = True
        self.recompute()
        self.assertValid(sweep)
        corner = elementWhere(sweep.Shape, "Vertex", lambda v: (v.Point - V(2, 2, 0)).Length < TOL)
        late = self.body.newObject("PartDesign::Point", "LatePoint")
        late.AttachmentSupport = [(sweep, corner)]
        late.MapMode = "Vertex"
        self.recompute()
        self.assertValid(late)

        sweep.Suppressed = False
        self.recompute()
        self.assertValid(sweep)
        self.assertFalse(
            late.isValid() and (late.Placement.Base - V(-2, -2, -2)).Length < 1e-6,
            "the datum taken on the Plate's corner moved to the Pipe's corner",
        )
        self.assertFalse(late.isValid(), "the Plate's corner is gone with the Pipe back")

    def testReopenedWhileSuppressed(self):
        """Saved and reopened with the hole suppressed, a sketch on the top still follows the
        block: the record keeps the world it was taken in (ops#549 PS)."""
        if not self.solver:
            self.skipTest("rule PS is the reference solver's")
        self.block()
        hole = self.hole()
        self.topSketch(hole)
        hole.Suppressed = True
        self.recompute()

        folder = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "suppressed.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        name = self.doc.Name
        self.addCleanup(lambda: name in App.listDocuments() and App.closeDocument(name))
        self.doc.getObject("Block").Length = 12
        self.recompute()
        self.assertAt(self.doc.getObject("TopSketch"), 12)


@unittest.skipUnless(dump.OLD_FILE_TESTS, dump.OLD_FILE_SKIP)
class TestFailurePassThroughV2(FailurePassThroughBase, unittest.TestCase):
    solver = False


class TestFailurePassThroughV2s(FailurePassThroughBase, unittest.TestCase):
    solver = True
