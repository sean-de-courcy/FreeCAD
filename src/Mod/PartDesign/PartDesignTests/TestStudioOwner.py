# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (S2): today's classes as studio owners
#
# An owner is a PartDesign feature (Pocket, Pad, Hole...) outside every Body, in the studio, held by
# the studio's list: it computes only its tool (AddSubShape), its own shape stays empty, and each
# part of its scope (part ids) gets a step (PartDesign::FeatureApply) that applies the tool
# (notes/parts-design.md 3.1, 10.1 "(b) on the build", 10.8, 10.9). Owners are made through the
# S1 Python API (studioInsert, studioSetScopeIds, studioNewPart), never by wiring steps by hand.
#
# Designed geometry only. The bake-off's studio: three 10 mm boxes A (x 0..10), B (x 20..30),
# C (x 40..50), each a Body with a sketch and a Pad; a cut x 5..25, y 2..8 from the top removes
# 5 x 6 x depth from A and from B. "Up to next" (UpToFirst) follows Onshape's O8 cases
# (notes/onshape-facts.md) at a small scale: one depth per profile region, against one part; a
# region with nothing ahead, or over two parts, fails the whole feature and no part changes.
# Expected values come from the geometry (Part booleans of boxes and cylinders), never from a run.

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import pad, rect, sketch, xyPlane
from PartDesignTests.TestStudioList import newStudio, studioList

V = App.Vector
CUT = (5, 2, 25, 8)  # the bake-off's cut, over A and B


def studioSketch(doc, studio, name, rects=(), z=0.0, circles=()):
    """A sketch in the studio, outside every Body, on the plane z (normal +z)."""
    s = doc.addObject("Sketcher::SketchObject", name)
    studio.addObject(s)
    s.Placement = App.Placement(V(0, 0, z), App.Rotation())
    for r in rects:
        rect(s, *r)
    for cx, cy, radius in circles:
        s.addGeometry(Part.Circle(V(cx, cy, 0), V(0, 0, 1), radius))
    return s


def makeOwner(doc, studio, kind, name, profile, scope, **values):
    """A studio owner of class PartDesign::<kind> on profile, put in the studio's list with scope
    (part ids) at the end; its values are set before it is listed. No recompute."""
    owner = doc.addObject("PartDesign::" + kind, name)
    studio.addObject(owner)
    owner.Profile = profile
    for key, value in values.items():
        setattr(owner, key, value)
    owner.StudioScope = list(scope)
    PartDesign.studioInsert(owner, -1)
    return owner


def floatingStudio(name, parts):
    """A studio of boxes 10 x 10 in plan: parts = ((name, x0, z0, height), ...)."""
    doc = App.newDocument(name)
    doc.UndoMode = 1
    studio = doc.addObject("App::Part", "S")
    for p, x, z0, height in parts:
        body = doc.addObject("PartDesign::Body", p)
        studio.addObject(body)
        pad(body, p + "Pad", sketch(body, p + "Sk", xyPlane(body), (x, 0, x + 10, 10), z=z0), height)
    doc.recompute()
    studioList(doc)
    return doc, studio


def box(x0, y0, z0, x1, y1, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


class TestStudioOwner(unittest.TestCase):
    def setUp(self):
        self.doc, self.studio = newStudio("TestStudioOwner")
        self.dir = None

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith(("TestStudioOwner", "O8")):
                App.closeDocument(doc.Name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def volume(self, part, doc=None):
        return (doc or self.doc).getObject(part).Shape.Volume

    def assertVolume(self, part, expected, doc=None):
        self.assertAlmostEqual(self.volume(part, doc), expected, places=3, msg=part)

    def assertOneSolid(self, part, doc=None):
        self.assertEqual(len((doc or self.doc).getObject(part).Shape.Solids), 1, part)

    def step(self, owner, part, doc=None):
        return PartDesign.studioStepOf(owner, (doc or self.doc).getObject(part))

    def assertIsOwner(self, owner):
        """An owner computes its tool, never shows as a part, and is in no Body."""
        self.assertTrue(owner.isValid(), owner.getStatusString())
        self.assertTrue(owner.Shape.isNull())
        self.assertFalse(owner.AddSubShape.isNull())
        for body in owner.Document.Objects:
            if body.TypeId == "PartDesign::Body":
                self.assertNotIn(owner, body.Group, body.Name)

    @staticmethod
    def partBox(x):
        return box(x, 0, 0, x + 10, 10, 10)

    def cutOwner(self, name="F1", scope=("A", "B"), rects=(CUT,), z=10.0, **values):
        sk = studioSketch(self.doc, self.studio, name + "Sk", rects, z=z)
        return makeOwner(self.doc, self.studio, "Pocket", name, sk, scope, **values)

    # ------------------------------------------------------------------------------- Pocket owners
    def testLengthPocketOwnerCutsTwoParts(self):
        """A Pocket of depth 3 outside every Body cuts A and B through their steps (90 each)."""
        f1 = self.cutOwner(Length=3)
        self.doc.recompute()
        self.assertIsOwner(f1)
        tool = box(5, 2, 7, 25, 8, 10)
        self.assertAlmostEqual(f1.AddSubShape.Volume, tool.Volume, places=3)
        for p, x in (("A", 0), ("B", 20)):
            self.assertTrue(self.step(f1, p).isValid(), p)
            self.assertEqual(self.step(f1, p).TypeId, "PartDesign::FeatureApply")
            self.assertVolume(p, self.partBox(x).cut(tool).Volume)
            self.assertAlmostEqual(self.volume(p), 1000 - 5 * 6 * 3, places=3)
        self.assertVolume("C", 1000)
        self.assertIsNone(self.step(f1, "C"))

    def testOwnerProfileInsideABody(self):
        """A sketch in A on A's top (the usual way: sketch on a part's face), the profile of a
        Pocket owner on A and B: each loses 90, and the sketch stays A's member."""
        a = self.doc.getObject("A")
        sk = sketch(a, "F1Sk", xyPlane(a), CUT, z=10)
        self.doc.recompute()
        f1 = makeOwner(self.doc, self.studio, "Pocket", "F1", sk, ("A", "B"), Length=3)
        self.doc.recompute()
        self.assertIsOwner(f1)
        self.assertIn(sk, a.Group)
        for p, x in (("A", 0), ("B", 20)):
            self.assertTrue(self.step(f1, p).isValid(), self.step(f1, p).getStatusString())
            self.assertVolume(p, self.partBox(x).cut(box(5, 2, 7, 25, 8, 10)).Volume)
        self.assertVolume("C", 1000)

    def testPlacedStudioAndPlacedBody(self):
        """The studio placed (moved and turned 90 degrees about z) and B placed 2 lower in it: a
        studio sketch on the studio's z 10 cuts 3 deep, so A loses 90 at its top and B 30 (its
        top is at 8); each cut where the studio's frame says, read in the Body's own frame."""
        b = self.doc.getObject("B")
        b.Placement = App.Placement(V(0, 0, -2), App.Rotation())
        self.studio.Placement = App.Placement(V(100, 50, 20), App.Rotation(V(0, 0, 1), 90))
        self.doc.recompute()
        f1 = self.cutOwner(Length=3)
        self.doc.recompute()
        self.assertIsOwner(f1)
        self.assertAlmostEqual(self.volume("A"), 1000 - 90, places=3)
        self.assertAlmostEqual(self.volume("B"), 1000 - 30, places=3)
        # In each Body's own frame (Shape carries the Body's local coordinates)
        self.assertVolume("A", self.partBox(0).cut(box(5, 2, 7, 10, 8, 10)).Volume)
        self.assertAlmostEqual(
            self.doc.getObject("A").Shape.common(box(5, 2, 7, 10, 8, 10)).Volume, 0, places=3)
        self.assertAlmostEqual(
            self.doc.getObject("B").Tip.Shape.common(box(20, 2, 9, 25, 8, 10)).Volume, 0,
            places=3)
        self.assertVolume("C", 1000)

    def testThroughAllPocketOwnerUsesTheScopeBases(self):
        """Through all reaches through the in-scope parts at the owner's place (300 each)."""
        f1 = self.cutOwner(Type="ThroughAll")
        self.doc.recompute()
        self.assertIsOwner(f1)
        for p, x in (("A", 0), ("B", 20)):
            self.assertVolume(p, self.partBox(x).cut(box(5, 2, 0, 25, 8, 10)).Volume)
            self.assertAlmostEqual(self.volume(p), 1000 - 5 * 6 * 10, places=3)
        self.assertVolume("C", 1000)

    def testUpToFacePocketOwner(self):
        """Up to face as today: a plane face at z 7 below both parts' tops (90 each)."""
        floor = self.doc.addObject("Part::Plane", "Floor")
        self.studio.addObject(floor)
        floor.Length, floor.Width = 80, 30
        floor.Placement = App.Placement(V(-10, -10, 7), App.Rotation())
        f1 = self.cutOwner(Type="UpToFace")
        f1.UpToFace = (floor, ["Face1"])
        self.doc.recompute()
        self.assertIsOwner(f1)
        for p in "AB":
            self.assertAlmostEqual(self.volume(p), 1000 - 5 * 6 * 3, places=3)
        self.assertVolume("C", 1000)

    def testScopeOfNothingFailsLoudly(self):
        """Onshape F2/F3: a dead pick beside a valid one is ignored; alone, the owner fails with
        "No merge scope selected" and no part changes."""
        f1 = self.cutOwner("F1", scope=("A", "Gone"), Length=3)
        f2 = self.cutOwner("F2", scope=("Gone",), rects=((22, 2, 28, 8),), Length=3)
        self.doc.recompute()
        self.assertTrue(f1.isValid(), f1.getStatusString())
        self.assertAlmostEqual(self.volume("A"), 1000 - 5 * 6 * 3, places=3)
        self.assertVolume("B", 1000)
        self.assertFalse(f2.isValid())
        self.assertIn("No merge scope selected", f2.getStatusString())
        self.assertIsNone(self.step(f2, "B"))
        self.assertTrue(f2.Shape.isNull())

    # ------------------------------------------------------------------------------- New result
    def testPadNewPart(self):
        """studioNewPart: a Body in the studio, id '<owner>:1', made by the owner, whose first
        step makes the tool itself (500); the other parts are untouched."""
        sk = studioSketch(self.doc, self.studio, "P1Sk", ((60, 0, 70, 10),), z=0)
        p1 = makeOwner(self.doc, self.studio, "Pad", "P1", sk, (), Length=5)
        self.doc.openTransaction("new part")
        body = PartDesign.studioNewPart(p1)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIsOwner(p1)
        self.assertEqual(body.TypeId, "PartDesign::Body")
        self.assertEqual(body.StudioPartId, "P1:1")
        self.assertIs(body.StudioMadeBy, p1)
        self.assertEqual(list(p1.StudioScope), ["P1:1"])
        self.assertIn(body, self.studio.Group)
        first = [o for o in body.Group if o.isDerivedFrom("PartDesign::Feature")][0]
        self.assertIs(first.StudioOwner, p1)
        self.assertIs(body.Tip, first)
        self.assertAlmostEqual(body.Shape.Volume, box(60, 0, 0, 70, 10, 5).Volume, places=3)
        for p in "ABC":
            self.assertVolume(p, 1000)
        # Undo takes the part away again
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse([b for b in self.doc.Objects if b.TypeId == "PartDesign::Body"
                          and b.Name not in ("A", "B", "C")])

    # ------------------------------------------------------------------------------- Hole
    def testHoleOwnerThroughAllOnTwoParts(self):
        """A Hole owner through all: one r1 hole per centre, through A and through B."""
        sk = studioSketch(self.doc, self.studio, "H1Sk", z=10, circles=((5, 5, 1), (25, 5, 1)))
        h1 = makeOwner(self.doc, self.studio, "Hole", "H1", sk, ("A", "B"), Diameter=2)
        h1.DepthType = "ThroughAll"  # listed first: Through all reads the scope's bases
        self.doc.recompute()
        self.assertIsOwner(h1)
        for p, x in (("A", 0), ("B", 20)):
            hole = Part.makeCylinder(1, 10, V(x + 5, 5, 0))
            self.assertVolume(p, self.partBox(x).cut(hole).Volume)
            self.assertAlmostEqual(self.volume(p), 1000 - math.pi * 10, places=3)
        self.assertVolume("C", 1000)

    # ------------------------------------------------------------------------------- Up to next (O8)
    def o8Add(self, name, rects):
        """O8's floating parts (A z 5..15, B z 8..18), an Add up to next from z 0."""
        doc, studio = floatingStudio(name, (("A", 0, 5, 10), ("B", 20, 8, 10)))
        sk = studioSketch(doc, studio, "F1Sk", rects, z=0)
        f1 = makeOwner(doc, studio, "Pad", "F1", sk, ("A", "B"), Type="UpToFirst")
        doc.recompute()
        return doc, f1

    def testO8bOneDepthPerRegion(self):
        """O8b: two regions, one under each part: each stops at its own part's bottom (A +180,
        B +288); still two parts of one solid each."""
        doc, f1 = self.o8Add("O8b", ((2, 2, 8, 8), (22, 2, 28, 8)))
        self.assertIsOwner(f1)
        a = box(0, 0, 5, 10, 10, 15).fuse(box(2, 2, 0, 8, 8, 5))
        b = box(20, 0, 8, 30, 10, 18).fuse(box(22, 2, 0, 28, 8, 8))
        self.assertVolume("A", a.Volume, doc)
        self.assertVolume("B", b.Volume, doc)
        self.assertAlmostEqual(self.volume("A", doc), 1000 + 6 * 6 * 5, places=3)
        self.assertAlmostEqual(self.volume("B", doc), 1000 + 6 * 6 * 8, places=3)
        self.assertOneSolid("A", doc)
        self.assertOneSolid("B", doc)

    def assertWholeFails(self, doc, f1, words, volumes):
        self.assertFalse(f1.isValid())
        for word in words:
            self.assertIn(word, f1.getStatusString())
        for p, expected in volumes.items():
            self.assertVolume(p, expected, doc)
            self.assertOneSolid(p, doc)
            self.assertFalse(self.step(f1, p, doc).isValid(), p)

    def testO8cARegionUnderNothingFailsTheWhole(self):
        """O8c: the same plus a region under nothing: the whole feature fails, no part changes."""
        doc, f1 = self.o8Add("O8c", ((2, 2, 8, 8), (22, 2, 28, 8), (42, 2, 48, 8)))
        self.assertWholeFails(doc, f1, ["Up to next", "meets no part ahead"],
                              {"A": 1000, "B": 1000})

    def testO8aARegionUnderTwoPartsFails(self):
        """O8a: one region spanning both parts fails the whole feature."""
        doc, f1 = self.o8Add("O8a", ((2, 2, 28, 8),))
        self.assertWholeFails(doc, f1, ["Up to next", "goes up to one part"],
                              {"A": 1000, "B": 1000})

    def o8Remove(self, name, rects):
        """O8f's standing parts (A z 0..10, B z 0..20), a Remove up to next from z 0, upward."""
        doc, studio = floatingStudio(name, (("A", 0, 0, 10), ("B", 20, 0, 20)))
        sk = studioSketch(doc, studio, "F1Sk", rects, z=0)
        f1 = makeOwner(doc, studio, "Pocket", "F1", sk, ("A", "B"), Type="UpToFirst",
                       Reversed=True)
        doc.recompute()
        return doc, f1

    def testO8fRemoveCutsEachRegionToItsPartsNextFace(self):
        """O8f: each region cuts up to its own part's next face (A's top at 10, B's at 20)."""
        doc, f1 = self.o8Remove("O8f", ((2, 2, 8, 8), (22, 2, 28, 8)))
        self.assertIsOwner(f1)
        a = box(0, 0, 0, 10, 10, 10).cut(box(2, 2, 0, 8, 8, 10))
        b = box(20, 0, 0, 30, 10, 20).cut(box(22, 2, 0, 28, 8, 20))
        self.assertVolume("A", a.Volume, doc)
        self.assertVolume("B", b.Volume, doc)
        self.assertAlmostEqual(self.volume("A", doc), 1000 - 360, places=3)
        self.assertAlmostEqual(self.volume("B", doc), 2000 - 720, places=3)

    def testO8gRemoveWithARegionUnderNothingFails(self):
        """O8g: the Remove plus a region under nothing: the whole feature fails."""
        doc, f1 = self.o8Remove("O8g", ((2, 2, 8, 8), (22, 2, 28, 8), (42, 2, 48, 8)))
        self.assertWholeFails(doc, f1, ["Up to next", "meets no part ahead"],
                              {"A": 1000, "B": 2000})

    def steppedStudio(self, name, low, high):
        """One part A of two boxes side by side, fused: x 0..10 at z low, x 10..20 at z high
        (each (z0, height)); the region x 2..18, y 2..8 on z 0 spans the step."""
        doc = App.newDocument(name)
        doc.UndoMode = 1
        studio = doc.addObject("App::Part", "S")
        body = doc.addObject("PartDesign::Body", "A")
        studio.addObject(body)
        pad(body, "APad", sketch(body, "ASk", xyPlane(body), (0, 0, 10, 10), z=low[0]), low[1])
        pad(body, "APad2", sketch(body, "ASk2", xyPlane(body), (10, 0, 20, 10), z=high[0]),
            high[1])
        doc.recompute()
        studioList(doc)
        return doc, studio

    def testO8hAStepOfOnePartGivesASteppedTool(self):
        """O8h: one region under one part whose bottom steps (z 5 over x 0..10, z 8 over
        x 10..20): the tool is stepped, x 2..10 rises 5 and x 10..18 rises 8 (+240 +384)."""
        doc, studio = self.steppedStudio("O8h", (5, 10), (8, 10))
        before = self.volume("A", doc)
        sk = studioSketch(doc, studio, "F1Sk", ((2, 2, 18, 8),), z=0)
        f1 = makeOwner(doc, studio, "Pad", "F1", sk, ("A",), Type="UpToFirst")
        doc.recompute()
        self.assertIsOwner(f1)
        part = box(0, 0, 5, 10, 10, 15).fuse(box(10, 0, 8, 20, 10, 18))
        tool = box(2, 2, 0, 10, 8, 5).fuse(box(10, 2, 0, 18, 8, 8))
        self.assertAlmostEqual(before, part.Volume, places=3)
        self.assertAlmostEqual(f1.AddSubShape.Volume, tool.Volume, places=3)
        self.assertVolume("A", part.fuse(tool).Volume, doc)
        self.assertAlmostEqual(self.volume("A", doc), before + 240 + 384, places=3)
        self.assertOneSolid("A", doc)

    def testO8hRemoveUpAStepCutsToEachNextFace(self):
        """Unverified on Onshape (O8h's Remove twin): a Remove up to next from z 0 under one part
        standing on z 0 whose top steps (z 10 over x 0..10, z 20 over x 10..20) cuts each side
        to its own top (-480 -960)."""
        doc, studio = self.steppedStudio("O8hr", (0, 10), (0, 20))
        sk = studioSketch(doc, studio, "F1Sk", ((2, 2, 18, 8),), z=0)
        f1 = makeOwner(doc, studio, "Pocket", "F1", sk, ("A",), Type="UpToFirst",
                       Reversed=True)
        doc.recompute()
        self.assertIsOwner(f1)
        part = box(0, 0, 0, 10, 10, 10).fuse(box(10, 0, 0, 20, 10, 20))
        tool = box(2, 2, 0, 10, 8, 10).fuse(box(10, 2, 0, 18, 8, 20))
        self.assertVolume("A", part.cut(tool).Volume, doc)
        self.assertAlmostEqual(self.volume("A", doc), 3000 - 480 - 960, places=3)

    def testH2RemoveUpToNextFromAboveCutsNothing(self):
        """Onshape H2: a Remove up to next downward from z 30 over A's stepped top (z 10 over
        x 0..10, z 18 over x 10..20) runs from the sketch to the next faces, wholly in air: A
        is unchanged and the feature is not an error. H2b: the same as an Add is stepped
        (x 2..10 down to 10, x 10..18 down to 18: +960 +576)."""
        for kind, name, gain in (("Pocket", "H2", 0), ("Pad", "H2b", 960 + 576)):
            doc, studio = self.steppedStudio(name, (0, 10), (0, 18))
            before = self.volume("A", doc)
            sk = studioSketch(doc, studio, "F1Sk", ((2, 2, 18, 8),), z=30)
            values = {"Reversed": True} if kind == "Pad" else {}
            f1 = makeOwner(doc, studio, kind, "F1", sk, ("A",), Type="UpToFirst", **values)
            doc.recompute()
            self.assertTrue(f1.isValid(), name + ": " + f1.getStatusString())
            self.assertTrue(self.step(f1, "A", doc).isValid(), name)
            self.assertAlmostEqual(self.volume("A", doc), before + gain, places=3, msg=name)
            self.assertOneSolid("A", doc)

    def testO8RegionPartlyUnderNothingFailsLoudly(self):
        """Unverified on Onshape (the loud choice): a region only part of which has the part
        ahead (x 2..28 under A's x 0..20) fails the whole feature; A is unchanged."""
        doc, studio = self.steppedStudio("O8p", (5, 10), (5, 10))
        sk = studioSketch(doc, studio, "F1Sk", ((2, 2, 28, 8),), z=0)
        f1 = makeOwner(doc, studio, "Pad", "F1", sk, ("A",), Type="UpToFirst")
        doc.recompute()
        self.assertWholeFails(doc, f1, ["Up to next", "part of it meets nothing ahead"],
                              {"A": 2000})

    def testAddRegionTouchingNoScopePartFailsLoudly(self):
        """Onshape H1a makes the second region a new part; until pieces become parts (P6p) a
        Blind Add of two regions, one on A's top and one beside every part, fails the whole
        feature loudly instead of dropping the second region; A is unchanged."""
        sk = studioSketch(self.doc, self.studio, "P1Sk", ((2, 2, 8, 8), (60, 2, 66, 8)), z=10)
        p1 = makeOwner(self.doc, self.studio, "Pad", "P1", sk, ("A",), Length=3)
        self.doc.recompute()
        self.assertFalse(p1.isValid())
        self.assertIn("touches no part of the merge scope", p1.getStatusString())
        self.assertIn("new part", p1.getStatusString())
        self.assertVolume("A", 1000)
        self.assertOneSolid("A")
        self.assertFalse(self.step(p1, "A").isValid())

    def testAddRegionsEachTouchingAScopePart(self):
        """The same Add with the second region on B's top, B in scope: each part gains its own
        region (A +108, B +108)."""
        sk = studioSketch(self.doc, self.studio, "P1Sk", ((2, 2, 8, 8), (22, 2, 28, 8)), z=10)
        p1 = makeOwner(self.doc, self.studio, "Pad", "P1", sk, ("A", "B"), Length=3)
        self.doc.recompute()
        self.assertIsOwner(p1)
        self.assertAlmostEqual(self.volume("A"), 1000 + 108, places=3)
        self.assertAlmostEqual(self.volume("B"), 1000 + 108, places=3)
        self.assertOneSolid("A")
        self.assertOneSolid("B")

    # ------------------------------------------------------------------------------- failure
    def testFailedOwnerContributesNothing(self):
        """Onshape F1: an Up to next that fails contributes nothing; a later owner on the same
        part computes against the state before it; only the failed one's steps fail."""
        f1 = self.cutOwner("F1", Length=3)
        f2 = self.cutOwner("F2", scope=("A",), rects=((60, 2, 66, 8),), Type="UpToFirst")
        f3 = self.cutOwner("F3", scope=("A",), rects=((1, 1, 3, 3),), Length=2)
        self.doc.recompute()
        self.assertTrue(f1.isValid(), f1.getStatusString())
        self.assertFalse(f2.isValid())
        self.assertIn("meets no part ahead", f2.getStatusString())
        self.assertFalse(self.step(f2, "A").isValid())
        self.assertTrue(f3.isValid(), f3.getStatusString())
        self.assertTrue(self.step(f3, "A").isValid(), self.step(f3, "A").getStatusString())
        expected = self.partBox(0).cut(box(5, 2, 7, 25, 8, 10)).cut(box(1, 1, 8, 3, 3, 10))
        self.assertVolume("A", expected.Volume)
        self.assertAlmostEqual(self.volume("A"), 1000 - 90 - 8, places=3)
        self.assertAlmostEqual(self.volume("B"), 1000 - 90, places=3)
        self.assertOneSolid("A")

    # ------------------------------------------------------------------------------- edits
    def testEditUndoRedoSaveReopen(self):
        """An edit of the owner drives its steps; undo, redo, save and reopen keep it so."""
        f1 = self.cutOwner(Length=3)
        self.doc.recompute()
        cut = lambda depth: 1000 - 5 * 6 * depth  # noqa: E731
        self.doc.openTransaction("depth")
        f1.Length = 4
        self.doc.commitTransaction()
        self.doc.recompute()
        for p in "AB":
            self.assertAlmostEqual(self.volume(p), cut(4), places=3)
        self.doc.undo()
        self.doc.recompute()
        for p in "AB":
            self.assertAlmostEqual(self.volume(p), cut(3), places=3)
        self.doc.redo()
        self.doc.recompute()
        for p in "AB":
            self.assertAlmostEqual(self.volume(p), cut(4), places=3)

        self.dir = tempfile.mkdtemp(prefix="studioowner")
        path = os.path.join(self.dir, "TestStudioOwnerSaved.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.doc.UndoMode = 1
        self.doc.recompute()
        f1 = self.doc.getObject("F1")
        self.assertEqual(PartDesign.studioScopeIds(f1), ["A", "B"])
        self.assertTrue(f1.Shape.isNull())
        for p in "AB":
            self.assertAlmostEqual(self.volume(p), cut(4), places=3)
        # A full recompute, then an edit after the reopen still drives both steps
        for obj in self.doc.Objects:
            obj.touch()
        self.doc.recompute()
        for p in "AB":
            self.assertAlmostEqual(self.volume(p), cut(4), places=3)
        self.doc.openTransaction("depth")
        f1.Length = 5
        self.doc.commitTransaction()
        self.doc.recompute()
        for p in "AB":
            self.assertAlmostEqual(self.volume(p), cut(5), places=3)
        self.assertVolume("C", 1000)


if __name__ == "__main__":
    unittest.main()
