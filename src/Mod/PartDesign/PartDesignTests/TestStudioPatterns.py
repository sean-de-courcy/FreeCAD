# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (slice 8): in-Body patterns of studio features, and patterns of patterns
#
# In a listed studio, a Linear pattern, Polar pattern or Mirror is a member of the originals'
# part (a Body member in the studio's list, at the bar) and takes as originals the studio
# features (owners) the person picks: each owner maps to its step in that part, whose tool is
# copied at every instance, as today's copy engine copies a native feature's (notes/parts-design.md
# 10.11 row 8, notes/patterns-design.md 3.1). Until Reapply per instance (T3) a copy is made only
# where it provably equals Onshape's instance: Up to next and a Remove that split its part are
# refused (Onshape's own rule with Reapply off, onshape-facts O6, O10), and an Up to face, Up to
# vertex or Through all seed is copied only when the instances' depths provably agree (the
# coordinator's ruling on work/c719/hub-cut-skeptic.md finding 3). A pattern or mirror among the
# originals brings its own instances only, never its seed (onshape-facts P2, P3), each moved by
# the outer transforms; the instances' names stay distinct.
#
# Designed geometry only; expected values come from the geometry (Part solids), never from a run.

import math
import os
import shutil
import tempfile
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import pad, sketch, xyPlane
from PartDesignTests.TestStudioList import elementNames, studioList
from PartDesignTests.TestStudioOwner import makeOwner, studioSketch

V = App.Vector
X_AXIS, Y_AXIS, Z_AXIS, XY_PLANE, XZ_PLANE, YZ_PLANE = range(6)


def box(x0, y0, z0, x1, y1, z1):
    return Part.makeBox(x1 - x0, y1 - y0, z1 - z0, V(x0, y0, z0))


def circleSketch(body, name, radius):
    s = body.newObject("Sketcher::SketchObject", name)
    s.AttachmentSupport = xyPlane(body)
    s.MapMode = "FlatFace"
    s.addGeometry(Part.Circle(V(0, 0, 0), V(0, 0, 1), radius))
    return s


def newStudio(name, parts):
    """A listed studio of plates: parts = ((name, (x0, y0, x1, y1), height), ...); a part whose
    rect is a number is a disc of that radius at the origin."""
    doc = App.newDocument(name)
    doc.UndoMode = 1
    studio = doc.addObject("App::Part", "S")
    for p, rect, height in parts:
        body = doc.addObject("PartDesign::Body", p)
        studio.addObject(body)
        if isinstance(rect, (int, float)):
            profile = circleSketch(body, p + "Sk", rect)
        else:
            profile = sketch(body, p + "Sk", xyPlane(body), rect)
        pad(body, p + "Pad", profile, height)
    doc.recompute()
    studioList(doc)
    return doc, studio


def axis(body, index):
    return (body.Origin.OriginFeatures[index], [""])


def listed(feature):
    PartDesign.studioInsert(feature, -1)
    return feature


def linear(body, name, originals, direction, length, count):
    lp = body.newObject("PartDesign::LinearPattern", name)
    lp.Originals = list(originals)
    lp.Direction = axis(body, direction)
    lp.Mode = "Extent"
    lp.Length = length
    lp.Occurrences = count
    return listed(lp)


def polar(body, name, originals, count):
    pp = body.newObject("PartDesign::PolarPattern", name)
    pp.Originals = list(originals)
    pp.Axis = axis(body, Z_AXIS)
    pp.Angle = 360
    pp.Occurrences = count
    return listed(pp)


def mirror(body, name, originals, plane):
    m = body.newObject("PartDesign::Mirrored", name)
    m.Originals = list(originals)
    m.MirrorPlane = axis(body, plane)
    return listed(m)


def faceNames(shape):
    """Each face's mapped name (V2: one per face)."""
    out = []
    for i in range(1, len(shape.Faces) + 1):
        mapped = shape.getElementMappedName(f"Face{i}")
        out.append(mapped[0] if isinstance(mapped, tuple) else mapped)
    return out


HOLE_R = 3.0


class TestStudioPatterns(unittest.TestCase):
    def setUp(self):
        self.docs = []
        self.dir = None

    def tearDown(self):
        for name in self.docs:
            if name in App.listDocuments():
                App.closeDocument(name)
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)

    # ------------------------------------------------------------------------------- helpers
    def studio(self, parts, name="TestStudioPatterns"):
        doc, studio = newStudio(name, parts)
        self.docs.append(doc.Name)
        self.doc, self.S = doc, studio
        return doc, studio

    def plate(self, height=10, rect=(0, 0, 60, 20)):
        """One part P: a 60 x 20 plate of height (x 0..60, y 0..20)."""
        return self.studio((("P", rect, height),))

    def holeOwner(self, name="Hole", scope=("P",), x=10.0, y=10.0, z=10.0, **values):
        """A Remove owner: a circle r3 at (x, y) on a studio sketch at z, cutting down."""
        sk = studioSketch(self.doc, self.S, name + "Sk", z=z, circles=((x, y, HOLE_R),))
        values.setdefault("Refine", True)
        return makeOwner(self.doc, self.S, "Pocket", name, sk, scope, **values)

    def bossOwner(self, name, rect, z, length, scope=("P",)):
        """An Add owner: a rectangle on a studio sketch at z, padded up by length."""
        sk = studioSketch(self.doc, self.S, name + "Sk", rects=(rect,), z=z)
        return makeOwner(self.doc, self.S, "Pad", name, sk, scope, Length=length, Refine=True)

    def part(self, name="P"):
        return self.doc.getObject(name)

    def tipShape(self, name="P"):
        return self.part(name).Tip.Shape

    def assertValid(self, *features):
        for f in features:
            self.assertTrue(f.isValid(), f"{f.Name}: {f.getStatusString()}")

    def assertRefused(self, pattern, *words):
        self.assertFalse(pattern.isValid(), f"{pattern.Name} computed: no refusal")
        status = pattern.getStatusString()
        for word in words:
            self.assertIn(word, status, status)

    def assertTipVolume(self, expected, name="P"):
        self.assertAlmostEqual(self.tipShape(name).Volume, expected, places=3)

    def hole(self, depth):
        return math.pi * HOLE_R**2 * depth

    def assertNamesDistinct(self, shape):
        names = faceNames(shape)
        self.assertNotIn("", names)
        self.assertEqual(len(set(names)), len(names), "two faces share a name")

    # ------------------------------------------------------------------------------- copies
    def testLinearPatternOfARemoveOwner(self):
        """Three r3 holes 5 deep in a 60 x 20 x 10 plate: the seed's and two copies 20 apart."""
        self.plate()
        hole = self.holeOwner(Length=5)
        p = self.part()
        lp = linear(p, "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertEqual(p.Tip, lp)
        self.assertIn(lp, list(studioList(self.doc).Entries))
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(5))
        for x in (10, 30, 50):
            self.assertFalse(lp.Shape.isInside(V(x, 10, 7), 1e-6, True), x)
            self.assertTrue(lp.Shape.isInside(V(x, 10, 3), 1e-6, True), x)
        self.assertNamesDistinct(lp.Shape)

    def testPolarPatternOfAnAddOwnerOnARoundPart(self):
        """Four 4 x 4 x 5 bosses on a disc r20 x 10: the seed at x 12..16 and three copies."""
        self.studio((("R", 20, 10),))
        boss = self.bossOwner("Boss", (12, -2, 16, 2), 10, 5, scope=("R",))
        pp = polar(self.part("R"), "PP", [boss], 4)
        self.doc.recompute()
        self.assertValid(boss, pp)
        disc = Part.makeCylinder(20, 10)
        self.assertAlmostEqual(self.tipShape("R").Volume, disc.Volume + 4 * 80, places=2)
        for x, y in ((14, 0), (0, 14), (-14, 0), (0, -14)):
            self.assertTrue(pp.Shape.isInside(V(x, y, 12), 1e-6, True), (x, y))
        self.assertNamesDistinct(pp.Shape)

    def testUpToFaceParallelToTheMotionIsCopied(self):
        """A hole up to the plate's floor plane (z 0, a Part::Plane in the studio) patterned along
        x, which lies in the plane: every copy reaches the plane, as Onshape's would."""
        self.plate()
        floor = self.doc.addObject("Part::Plane", "Floor")
        self.S.addObject(floor)
        floor.Length, floor.Width = 100, 40
        floor.Placement = App.Placement(V(-20, -10, 0), App.Rotation())
        hole = self.holeOwner(Type="UpToFace", UpToFace=(floor, ["Face1"]))
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(10))

    def testThroughAllSpanningThePartIsCopied(self):
        """A Through all hole patterned along x: every copy spans the plate."""
        self.plate()
        hole = self.holeOwner(Type="ThroughAll")
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(10))

    def upToVertexHole(self):
        """A hole down to the plane of the plate's corner vertex at z 0 (a through hole)."""
        self.plate()
        pad = self.doc.getObject("PPad")
        corner = next(
            f"Vertex{i}"
            for i, v in enumerate(pad.Shape.Vertexes, 1)
            if v.Point.distanceToPoint(V(0, 0, 0)) < 1e-9
        )
        return self.holeOwner(Type="UpToVertex", UpToFace=(pad, [corner]))

    def testUpToVertexKeptByTheMotionIsCopied(self):
        """Up to vertex patterned along x: the vertex's end plane (z 0, parallel to the profile)
        is every instance's own, so the copies are Onshape's instances: three through holes."""
        hole = self.upToVertexHole()
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(10))

    def testUpToVertexMovedOffItsPlaneIsRefused(self):
        """Up to vertex patterned along z: an instance computed there would end on the vertex's
        plane at another depth, so copies are refused."""
        hole = self.upToVertexHole()
        lp = linear(self.part(), "LP", [hole], Z_AXIS, 2, 2)
        self.doc.recompute()
        self.assertValid(hole)
        self.assertRefused(lp, "Hole", "Up to vertex", "Reapply")

    # ------------------------------------------------------------------------------- refusals
    def testOwnerOnTwoPartsIsRefused(self):
        """An original cutting A and B (Onshape cuts both at every instance, O7: a pattern across
        parts, a later slice): refused loudly, and A keeps the cut without copies."""
        self.studio((("A", (0, 0, 10, 10), 10), ("B", (20, 0, 30, 10), 10)))
        sk = studioSketch(self.doc, self.S, "CutSk", rects=((5, 2, 25, 8),), z=10)
        cut = makeOwner(self.doc, self.S, "Pocket", "Cut", sk, ("A", "B"), Length=3)
        lp = linear(self.part("A"), "LP", [cut], Y_AXIS, 1, 2)
        self.doc.recompute()
        self.assertRefused(lp, "Cut", "parts")
        self.assertTipVolume(1000 - 5 * 6 * 3, "A")

    def testOwnerOnAnotherPartIsRefused(self):
        """An original acting on B only, picked by a pattern in A: refused loudly."""
        self.studio((("A", (0, 0, 10, 10), 10), ("B", (20, 0, 30, 10), 10)))
        sk = studioSketch(self.doc, self.S, "CutSk", rects=((22, 2, 28, 8),), z=10)
        cut = makeOwner(self.doc, self.S, "Pocket", "Cut", sk, ("B",), Length=3)
        lp = linear(self.part("A"), "LP", [cut], Y_AXIS, 1, 2)
        self.doc.recompute()
        self.assertRefused(lp, "Cut", "B")
        self.assertTipVolume(1000, "A")

    def testUpToNextIsRefused(self):
        """An Up to next seed: Onshape refuses it with Reapply off (O10, O10b)."""
        self.plate()
        hole = self.holeOwner(Type="UpToFirst")
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole)
        self.assertRefused(lp, "Hole", "Up to next", "Reapply")
        self.assertTipVolume(60 * 20 * 10 - self.hole(10))

    def testRemoveThatSplitItsPartIsRefused(self):
        """A seed Remove that cut the plate in two (Onshape refuses it with Reapply off, O7)."""
        self.plate()
        sk = studioSketch(self.doc, self.S, "SlotSk", rects=((28, -5, 32, 25),), z=10)
        slot = makeOwner(self.doc, self.S, "Pocket", "Slot", sk, ("P",), Type="ThroughAll")
        lp = linear(self.part(), "LP", [slot], X_AXIS, 20, 2)
        self.doc.recompute()
        self.assertRefused(lp, "Slot")

    def testPatternThatSplitsThePartFailsLoudly(self):
        """A slot through the plate's lower half (y -1..11), patterned 9 along y: the copy meets
        the seed and cuts the plate in two. Until pieces become parts (P6p) the pattern fails,
        and the part keeps the seed's slot only."""
        self.plate()
        sk = studioSketch(self.doc, self.S, "SlotSk", rects=((10, -1, 14, 11),), z=10)
        slot = makeOwner(self.doc, self.S, "Pocket", "Slot", sk, ("P",), Length=10)
        lp = linear(self.part(), "LP", [slot], Y_AXIS, 9, 2)
        self.doc.recompute()
        self.assertValid(slot)
        self.assertRefused(lp, "splits", "pieces")
        self.assertTipVolume(60 * 20 * 10 - 4 * 11 * 10)
        self.assertEqual(len(self.tipShape().Solids), 1)

    def testUpToASlantedFaceIsRefused(self):
        """A hole up to a slanted plane, patterned along x: each instance would reach the plane
        at its own depth (Onshape O6 with Reapply on), so copies are refused."""
        self.plate()
        floor = self.doc.addObject("Part::Plane", "Slant")
        self.S.addObject(floor)
        floor.Length, floor.Width = 100, 40
        floor.Placement = App.Placement(V(-20, -10, 2), App.Rotation(V(0, 1, 0), -3))
        hole = self.holeOwner(Type="UpToFace", UpToFace=(floor, ["Face1"]))
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole)
        self.assertRefused(lp, "Hole", "Up to face", "Reapply")

    def testThroughAllNotSpanningIsRefused(self):
        """A Through all hole from z 10 patterned onto a block raised to z 20: the copy can't be
        shown to agree with the instance re-solved there, so it is refused."""
        self.plate()
        p = self.part()
        raised = pad(p, "Raised", sketch(p, "RaisedSk", xyPlane(p), (40, 0, 60, 20), z=10), 10)
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        hole = self.holeOwner(Type="ThroughAll")
        lp = linear(p, "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole)
        self.assertRefused(lp, "Hole", "Through all", "Reapply")

    # ------------------------------------------------------------------------------- patterns of patterns
    def mirrorStudio(self):
        """A plate x -30..30, y -30..30, z 0..5, a 6 x 6 x 5 boss at (2..8, 2..8), and Mir1, the
        boss mirrored about YZ (x 0)."""
        self.plate(height=5, rect=(-30, -30, 30, 30))
        boss = self.bossOwner("Boss", (2, 2, 8, 8), 5, 5)
        mir1 = mirror(self.part(), "Mir1", [boss], YZ_PLANE)
        return boss, mir1

    PLATE = 60 * 60 * 5
    BOSS = 6 * 6 * 5

    def bossAt(self, shape, x, y):
        return shape.isInside(V(x, y, 7.5), 1e-6, True)

    def testMirrorOfAMirrorBringsItsInstanceOnly(self):
        """Onshape P2/P3: a mirror of [Mir1] about XZ (y 0) mirrors Mir1's copy only: +1 boss at
        (-5, -5), none at (5, -5)."""
        boss, mir1 = self.mirrorStudio()
        mir2 = mirror(self.part(), "Mir2", [mir1], XZ_PLANE)
        self.doc.recompute()
        self.assertValid(boss, mir1, mir2)
        self.assertTipVolume(self.PLATE + 3 * self.BOSS)
        shape = mir2.Shape
        for (x, y), there in (((5, 5), True), ((-5, 5), True), ((-5, -5), True), ((5, -5), False)):
            self.assertEqual(self.bossAt(shape, x, y), there, (x, y))
        self.assertNamesDistinct(shape)

    def testMirrorOfTheSeedAndAMirror(self):
        """A mirror of [Boss, Mir1] about XZ: +2 bosses, one in each quadrant."""
        boss, mir1 = self.mirrorStudio()
        mir2 = mirror(self.part(), "Mir2", [boss, mir1], XZ_PLANE)
        self.doc.recompute()
        self.assertValid(mir2)
        self.assertTipVolume(self.PLATE + 4 * self.BOSS)
        for x, y in ((5, 5), (-5, 5), (-5, -5), (5, -5)):
            self.assertTrue(self.bossAt(mir2.Shape, x, y), (x, y))
        self.assertNamesDistinct(mir2.Shape)

    def testLinearPatternOfALinearPattern(self):
        """Onshape P2: LPx = [Boss] +x 20 x 2; a pattern of [LPx] +y 20 x 2 copies LPx's
        instance only, to (22..28, 22..28)."""
        boss, _ = self.mirrorStudio()
        p = self.part()
        lpx = linear(p, "LPx", [boss], X_AXIS, 20, 2)
        lpy = linear(p, "LPy", [lpx], Y_AXIS, 20, 2)
        self.doc.recompute()
        self.assertValid(lpx, lpy)
        self.assertTipVolume(self.PLATE + 4 * self.BOSS)
        self.assertTrue(self.bossAt(lpy.Shape, 25, 25))
        self.assertFalse(self.bossAt(lpy.Shape, 5, 25))
        self.assertNamesDistinct(lpy.Shape)

    # ------------------------------------------------------------------------------- chamfer
    def testChamferAmongTheOriginals(self):
        """A 6 x 6 x 5 boss with its four top edges chamfered 1, patterned with the chamfer +x 20 x
        3: each instance is the chamfered boss (the chamfer's removed material copied)."""
        self.plate(height=5, rect=(0, 0, 60, 20))
        boss = self.bossOwner("Boss", (2, 7, 8, 13), 5, 5)
        self.doc.recompute()
        p = self.part()
        step = PartDesign.studioStepOf(boss, p)
        edges = [
            f"Edge{i}"
            for i, e in enumerate(step.Shape.Edges, 1)
            if all(abs(v.Point.z - 10) < 1e-6 for v in e.Vertexes)
        ]
        self.assertEqual(len(edges), 4)
        chamfer = p.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (step, edges)
        chamfer.Size = 1
        listed(chamfer)
        lp = linear(p, "LP", [boss, chamfer], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(chamfer, lp)
        solid = box(2, 7, 5, 8, 13, 10)
        top = [e for e in solid.Edges if all(abs(v.Point.z - 10) < 1e-6 for v in e.Vertexes)]
        chamfered = solid.makeChamfer(1, top)
        self.assertTipVolume(60 * 20 * 5 + 3 * chamfered.Volume)

    def testSuppressedOriginalContributesNothing(self):
        """The original suppressed: its step passes its base through, and so does the pattern
        (it kept its last shape, the copies included); unsuppressed, the three holes are back."""
        self.plate()
        hole = self.holeOwner(Length=5)
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        PartDesign.studioSuppress(hole, True)
        self.doc.recompute()
        self.assertValid(lp)
        self.assertTipVolume(60 * 20 * 10)
        PartDesign.studioSuppress(hole, False)
        self.doc.recompute()
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(5))

    # ------------------------------------------------------------------------------- history
    def testUndoRedo(self):
        """The pattern made in a transaction goes with undo and comes back with redo."""
        self.plate()
        hole = self.holeOwner(Length=5)
        self.doc.recompute()
        self.doc.openTransaction("pattern")
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(5))
        self.doc.undo()
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject("LP"))
        self.assertTipVolume(60 * 20 * 10 - self.hole(5))
        self.doc.redo()
        self.doc.recompute()
        lp = self.doc.getObject("LP")
        self.assertValid(lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(5))

    def testSaveAndReopenKeepsTheNames(self):
        """Saved and opened again: the same volume and the same element names."""
        boss, mir1 = self.mirrorStudio()
        mirror(self.part(), "Mir2", [mir1], XZ_PLANE)
        self.doc.recompute()
        before = elementNames(self.tipShape())
        volume = self.tipShape().Volume
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "patterns.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.docs.append(self.doc.Name)
        self.doc.recompute()
        self.assertTrue(self.doc.getObject("Mir2").isValid())
        self.assertAlmostEqual(self.tipShape().Volume, volume, places=4)
        self.assertEqual(elementNames(self.tipShape()), before)
