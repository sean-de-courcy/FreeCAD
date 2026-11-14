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
# T3 (ops#654, patterns-design 3.3): with Reapply on (Onshape's Reapply features) each instance
# re-runs its originals there, in order, against the part as it grows: an extrusion whose tool
# depends on the base (Up to next, last, face, vertex or shape, Through all) is re-solved per
# instance (O6, O10, O10b); a Blind one's copy is its re-run. An Add instance touching nothing is
# refused (Onshape makes it a new part); a Remove instance off the part does nothing (P1).
#
# The T3 fix (oracle 9): instances are made instance by instance with Reapply on and off (R1); a
# failing re-run contributes nothing, silently, and Up to next is re-run with Reapply off too (R2);
# Reapply off copies an Up to face seed, and each pattern follows its own Reapply, nested too (R3).
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
import Sketcher

from PartDesignTests.TestStudio import pad, rect, sketch, xyPlane
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


def polygonSketch(body, name, support, points):
    """A closed polygon sketch on support (points in the sketch's own u, v)."""
    s = body.newObject("Sketcher::SketchObject", name)
    s.AttachmentSupport = support
    s.MapMode = "FlatFace"
    n = len(points)
    for i in range(n):
        a, b = points[i], points[(i + 1) % n]
        s.addGeometry(Part.LineSegment(V(a[0], a[1], 0), V(b[0], b[1], 0)))
    for i in range(n):
        s.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % n, 1))
    return s


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

    # ------------------------------------------------------------------- second direction
    def gridPattern(self, reapply=False, **values):
        """On a 60 x 40 x 10 plate, the hole owner (r3, 5 deep, at (10, hy)) patterned 3 times 20
        apart along X, and along Y as the second direction: values set Offset2, Occurrences2,
        Centered2, SkippedInstances (ops#655)."""
        self.plate(rect=(0, 0, 60, 40))
        hole = self.holeOwner(Length=5, y=values.pop("hy", 10.0))
        p = self.part()
        lp = p.newObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [hole]
        lp.Direction = axis(p, X_AXIS)
        lp.Mode = "Spacing"
        lp.Offset = 20
        lp.Occurrences = 3
        lp.Direction2 = axis(p, Y_AXIS)
        lp.Mode2 = "Spacing"
        for name, value in values.items():
            setattr(lp, name, value)
        lp.Reapply = reapply
        listed(lp)
        self.doc.recompute()
        self.assertValid(hole, lp)
        return lp

    def holesAt(self, lp, ys):
        """The (x, y) of the grid places, x 10, 30, 50, that have a hole 2 below the top."""
        return sorted(
            (x, y)
            for x in (10, 30, 50)
            for y in ys
            if not lp.Shape.isInside(V(x, y, 8), 1e-6, True)
        )

    def testSecondDirectionGrid(self):
        """Onshape's grid: 3 along X times 2 along Y, the seed counted once, six holes, with
        Reapply off and on; every face keeps its own name (instance numbers i:j)."""
        for reapply in (False, True):
            with self.subTest(reapply=reapply):
                lp = self.gridPattern(reapply, Offset2=15, Occurrences2=2)
                self.assertTipVolume(60 * 40 * 10 - 6 * self.hole(5))
                self.assertEqual(
                    self.holesAt(lp, (10, 25, 40)), [(x, y) for x in (10, 30, 50) for y in (10, 25)]
                )
                self.assertNamesDistinct(lp.Shape)
                App.closeDocument(self.doc.Name)

    def testSecondDirectionCenteredAndSkipped(self):
        """Centered along Y with count 2 puts rows at y 5, 20, 35 around the seed's y 20 (Onshape's
        count is per side, the seed included: oracle 9j); skipping (1, 2) leaves out x 30 on the
        last row (counted from the negative end): eight holes."""
        lp = self.gridPattern(
            hy=20.0, Offset2=15, Occurrences2=2, Centered2=True, SkippedInstances=[1, 2]
        )
        self.assertTipVolume(60 * 40 * 10 - 8 * self.hole(5))
        expected = [(x, y) for x in (10, 30, 50) for y in (5, 20, 35) if (x, y) != (30, 35)]
        self.assertEqual(self.holesAt(lp, (5, 20, 35)), expected)

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

    def testUpToNextIsReRunWithReapplyOff(self):
        """An Up to next seed with Reapply off: re-run at each instance all the same (oracle 9,
        R2): three holes through the plate."""
        self.plate()
        hole = self.holeOwner(Type="UpToFirst")
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(10))

    def testUpToNextFromReferenceReapplyOff(self):
        """An Up to next column starting at a reference (the floor's top face), patterned with
        Reapply off in a plain Body: copied as integration does (re-running it isn't available
        from a reference), no refusal (review prline-b4-r1 T2, case UpToNextFromReferenceLower).
        A floor x 0..60, y 0..20, z 0..5; a back wall y 16..20 up to z 33; ceiling A over
        x 0..30 (z 25..30), ceiling B over x 30..60 (z 28..33). The column x 5..10, y 5..10
        ends under ceiling A (z 25); the pattern +x 30 x 2: instance 2 is the seed's copy, z 5..25
        (a re-run would end at z 28)."""
        doc = App.newDocument("TestStudioPatternsPlain")
        self.docs.append(doc.Name)
        self.doc = doc
        body = doc.addObject("PartDesign::Body", "P")
        floor = pad(body, "FloorPad", sketch(body, "FloorSk", xyPlane(body), (0, 0, 60, 20)), 5)
        pad(body, "WallPad", sketch(body, "WallSk", xyPlane(body), (0, 16, 60, 20), z=5), 28)
        pad(body, "CeilAPad", sketch(body, "CeilASk", xyPlane(body), (0, 0, 30, 16), z=25), 5)
        pad(body, "CeilBPad", sketch(body, "CeilBSk", xyPlane(body), (30, 0, 60, 16), z=28), 5)
        doc.recompute()
        top = [
            f"Face{i + 1}"
            for i, f in enumerate(floor.Shape.Faces)
            if f.Surface.isPlanar() and abs(f.CenterOfMass.z - 5) < 1e-6
        ]
        self.assertEqual(len(top), 1, top)
        column = pad(
            body, "ColumnPad", sketch(body, "ColumnSk", xyPlane(body), (5, 5, 10, 10), z=5), 10
        )
        column.Type = "UpToFirst"
        column.StartType = "Reference"
        column.StartReference = (floor, top)
        doc.recompute()
        self.assertValid(column)
        walls = 60 * 20 * 5 + 60 * 4 * 28 + 30 * 16 * 5 + 30 * 16 * 5
        self.assertAlmostEqual(column.Shape.Volume, walls + 5 * 5 * 20, places=3)
        lp = doc.addObject("PartDesign::LinearPattern", "LP")
        lp.Originals = [column]
        lp.Direction = (body.Origin.OriginFeatures[X_AXIS], [""])
        lp.Mode = "Extent"
        lp.Length = 30
        lp.Occurrences = 2
        lp.Reapply = False
        body.addObject(lp)
        doc.recompute()
        self.assertValid(lp)
        self.assertAlmostEqual(lp.Shape.Volume, walls + 2 * 5 * 5 * 20, places=3)
        self.assertTrue(lp.Shape.isInside(V(37.5, 7.5, 24), 1e-6, True))
        self.assertFalse(lp.Shape.isInside(V(37.5, 7.5, 26.5), 1e-6, True))

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

    def slant(self):
        """A plane slanted along x, z = 2 + (x + 20) tan 3 deg (a Part::Plane in the studio)."""
        floor = self.doc.addObject("Part::Plane", "Slant")
        self.S.addObject(floor)
        floor.Length, floor.Width = 100, 40
        floor.Placement = App.Placement(V(-20, -10, 2), App.Rotation(V(0, 1, 0), -3))
        return floor

    def slantDepth(self, x, top=10.0):
        """The depth from z top down to the slanted plane at x (a planar floor: the mean depth
        over a disc is the depth at its centre)."""
        return top - (2 + (x + 20) * math.tan(math.radians(3)))

    def testUpToASlantedFaceIsCopiedWithReapplyOff(self):
        """A hole up to a slanted plane, patterned along x, Reapply off: each instance is a copy of
        the seed, at the seed's depth (oracle 9, R3)."""
        self.plate()
        floor = self.slant()
        hole = self.holeOwner(Type="UpToFace", UpToFace=(floor, ["Face1"]))
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(self.slantDepth(10)))

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

    def testThroughAllBesideABossIsCopied(self):
        """ops#640 F2: a Through all hole r3 at (-28, 15) on an 80 x 50 plate with a boss r12 at the
        origin up to z 30, patterned 26 along x: the copy at (-2, 15) clears the boss (its wall is
        12.13 from the axis), so it spans the plate as the instance would. The box around the copy
        reached the boss, and the pattern was refused."""
        self.plate(rect=(-40, -25, 40, 25))
        p = self.part()
        boss = circleSketch(p, "BossSk", 12)
        boss.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
        pad(p, "Boss", boss, 20)
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        hole = self.holeOwner(Type="ThroughAll", x=-28.0, y=15.0)
        lp = linear(p, "LP", [hole], X_AXIS, 26, 2)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(80 * 50 * 10 + math.pi * 12**2 * 20 - 2 * self.hole(10))

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

    # ------------------------------------------------------------------------------- Reapply (T3)
    # Reapply on (Onshape's Reapply features, onshape-facts O6, O10, P1): each instance re-runs the
    # originals there, in order, against the part as it grows; the expected volumes come from the
    # geometry of the re-solved instances.

    def roofStudio(self, x0=0.0, x1=100.0):
        """Part P, a roof: the Front-plane profile (x0, z(x0)) (x1, z(x1)) (x1, 70) (x0, 70) with
        z(x) = 40 + 0.2 x, padded symmetric 40 (y -20..20): its underside is z = 40 + 0.2 x (O6).
        Returns the roof's Pad and the underside's name."""
        doc = App.newDocument("TestStudioReapply")
        doc.UndoMode = 1
        self.docs.append(doc.Name)
        studio = doc.addObject("App::Part", "S")
        body = doc.addObject("PartDesign::Body", "P")
        studio.addObject(body)

        def z(x):
            return 40 + 0.2 * x

        profile = polygonSketch(
            body,
            "RoofSk",
            [(body.Origin.OriginFeatures[XZ_PLANE], "")],
            [(x0, z(x0)), (x1, z(x1)), (x1, 70), (x0, 70)],
        )
        roof = body.newObject("PartDesign::Pad", "Roof")
        roof.Profile = profile
        roof.SideType = "Symmetric"
        roof.Length = 40
        doc.recompute()
        studioList(doc)
        self.doc, self.S = doc, studio
        under = next(
            f"Face{i}"
            for i, f in enumerate(roof.Shape.Faces, 1)
            if f.normalAt(0, 0).z < -0.5 and abs(f.normalAt(0, 0).x) > 0.1
        )
        return roof, under

    def roofVolume(self, x0=0.0, x1=100.0):
        def z(x):
            return 40 + 0.2 * x

        return ((70 - z(x0)) + (70 - z(x1))) / 2 * (x1 - x0) * 40

    def column(self, x):
        """A 10 x 10 column from z 0 up to the underside, centred at x: 100 x (40 + 0.2 x)."""
        return 100 * (40 + 0.2 * x)

    def roofSeedOwner(self, roof, under, name="Seed"):
        """O6's seed as a studio feature: 10 x 10 at x 5..15, y -5..5 on z 0, Add up to the
        roof's underside."""
        sk = studioSketch(self.doc, self.S, name + "Sk", rects=((5, -5, 15, 5),), z=0)
        return makeOwner(
            self.doc, self.S, "Pad", name, sk, ("P",), Type="UpToFace", UpToFace=(roof, [under])
        )

    def testReapplyUpToASlantedFaceReachesItAtEachDepth(self):
        """O6: a linear pattern +x 30 x 3 of the seed up to the slanted underside, Reapply on:
        each instance reaches the face at its own depth (4200, 4800, 5400)."""
        roof, under = self.roofStudio()
        seed = self.roofSeedOwner(roof, under)
        lp = linear(self.part(), "LP", [seed], X_AXIS, 60, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(seed, lp)
        self.assertTipVolume(self.roofVolume() + self.column(10) + self.column(40) + self.column(70))
        self.assertEqual(len(self.tipShape().Solids), 1)
        self.assertNamesDistinct(lp.Shape)
        # Reapply off: copies of the seed, at its height (oracle 9, R3): their tops (z 41..43) stay
        # below the underside there (z 47 and up), so no copy reaches the part: Onshape's "Could
        # not create all instances" (ops#640 A-2' d), and the part keeps the seed only
        lp.Reapply = False
        self.doc.recompute()
        self.assertValid(seed)
        self.assertRefused(lp, "Could not create all instances")
        self.assertTipVolume(self.roofVolume() + self.column(10))

    def testReapplyNativeUpToFace(self):
        """O6 with a Body Pad as the seed: Reapply on re-runs it at each instance."""
        roof, under = self.roofStudio()
        p = self.part()
        seed = p.newObject("PartDesign::Pad", "Seed")
        seed.Profile = sketch(p, "SeedSk", xyPlane(p), (5, -5, 15, 5))
        seed.Type = "UpToFace"
        seed.UpToFace = (roof, [under])
        listed(seed)
        lp = linear(p, "LP", [seed], X_AXIS, 60, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(seed, lp)
        self.assertTipVolume(self.roofVolume() + self.column(10) + self.column(40) + self.column(70))

    def testReapplyUpToNextStopsOnTheInstanceBefore(self):
        """O10: a plate x -10..30, y 0..20, z 0..5; the seed 10 x 10 (x 0..10, y 5..15) from z 10
        Add up to next downward (z 5..10); a pattern +z 10 x 2, Reapply on: instance 2 (from z 20)
        stops on the seed's top (z 10): +1000."""
        self.plate(height=5, rect=(-10, 0, 30, 20))
        sk = studioSketch(self.doc, self.S, "SeedSk", rects=((0, 5, 10, 15),), z=10)
        seed = makeOwner(
            self.doc, self.S, "Pad", "Seed", sk, ("P",), Type="UpToFirst", Reversed=True
        )
        lp = linear(self.part(), "LP", [seed], Z_AXIS, 10, 2)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(seed, lp)
        self.assertTipVolume(40 * 20 * 5 + 500 + 1000)
        self.assertTrue(lp.Shape.isInside(V(5, 10, 15), 1e-6, True))
        self.assertFalse(lp.Shape.isInside(V(5, 10, 21), 1e-6, True))
        # Reapply off: an up to next seed is re-run at each instance all the same (oracle 9, R2)
        lp.Reapply = False
        self.doc.recompute()
        self.assertValid(seed, lp)
        self.assertTipVolume(40 * 20 * 5 + 500 + 1000)

    def testReapplyNativeUpToNext(self):
        """O10 with a Body Pad as the seed (Up to first, downward)."""
        self.plate(height=5, rect=(-10, 0, 30, 20))
        p = self.part()
        seed = p.newObject("PartDesign::Pad", "Seed")
        seed.Profile = sketch(p, "SeedSk", xyPlane(p), (0, 5, 10, 15), z=10)
        seed.Type = "UpToFirst"
        seed.Reversed = True
        listed(seed)
        lp = linear(p, "LP", [seed], Z_AXIS, 10, 2)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(seed, lp)
        self.assertTipVolume(40 * 20 * 5 + 500 + 1000)

    def steppedPlate(self):
        """O10b: a plate x -10..50, y 0..20, top z 5, raised to z 10 for x 20..50."""
        self.plate(height=5, rect=(-10, 0, 50, 20))
        p = self.part()
        pad(p, "Step", sketch(p, "StepSk", xyPlane(p), (20, 0, 50, 20), z=5), 5)
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        return p

    def testReapplyUpToNextOnAStep(self):
        """O10b: the seed from z 20 down to the plate (depth 15); a pattern +x 25 x 2, Reapply on:
        instance 2 (x 25..35) is re-solved, depth 10 to the high step (+1000)."""
        p = self.steppedPlate()
        sk = studioSketch(self.doc, self.S, "SeedSk", rects=((0, 5, 10, 15),), z=20)
        seed = makeOwner(
            self.doc, self.S, "Pad", "Seed", sk, ("P",), Type="UpToFirst", Reversed=True
        )
        lp = linear(p, "LP", [seed], X_AXIS, 25, 2)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(seed, lp)
        self.assertTipVolume(30 * 20 * 5 + 30 * 20 * 10 + 1500 + 1000)

    def testReapplyMirrorOfAnUpToFaceSeed(self):
        """A roof over x -100..100 (underside z = 40 + 0.2 x); the seed up to it at x 5..15 (4200),
        mirrored about YZ with Reapply on: the image at x -15..-5 reaches the face at z 38 (3800).
        Reapply off: a copy of the seed (top at z 41..43, oracle 9 R3), which goes into the roof
        there: the union is the same."""
        roof, under = self.roofStudio(-100, 100)
        seed = self.roofSeedOwner(roof, under)
        m = mirror(self.part(), "Mir", [seed], YZ_PLANE)
        m.Reapply = True
        self.doc.recompute()
        self.assertValid(seed, m)
        self.assertTipVolume(self.roofVolume(-100, 100) + self.column(10) + self.column(-10))
        m.Reapply = False
        self.doc.recompute()
        self.assertValid(seed, m)
        self.assertTipVolume(self.roofVolume(-100, 100) + self.column(10) + self.column(-10))
        self.assertTrue(m.Shape.isInside(V(-10, 0, 39), 1e-6, True))

    def testReapplyPatternOfAPattern(self):
        """LP1 = [Seed] +x 30 x 2 and LP2 = [LP1] +x 30 x 2, both Reapply on: LP2 re-runs LP1's
        instance only (Onshape P2), 60 from the seed: x 65..75, 5400."""
        roof, under = self.roofStudio()
        seed = self.roofSeedOwner(roof, under)
        p = self.part()
        lp1 = linear(p, "LP1", [seed], X_AXIS, 30, 2)
        lp1.Reapply = True
        lp2 = linear(p, "LP2", [lp1], X_AXIS, 30, 2)
        lp2.Reapply = True
        self.doc.recompute()
        self.assertValid(seed, lp1, lp2)
        self.assertTipVolume(self.roofVolume() + self.column(10) + self.column(40) + self.column(70))
        self.assertNamesDistinct(lp2.Shape)

    def testReapplyBlindIsTheCopy(self):
        """A Blind Remove with Reapply on: the instances are the copies, names and all."""
        self.plate()
        hole = self.holeOwner(Length=5)
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        names = elementNames(lp.Shape)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(5))
        self.assertEqual(elementNames(lp.Shape), names)

    def floorPlane(self, z=0.0):
        floor = self.doc.addObject("Part::Plane", "Floor")
        self.S.addObject(floor)
        floor.Length, floor.Width = 100, 40
        floor.Placement = App.Placement(V(-20, -10, z), App.Rotation())
        return floor

    def testReapplyMixedAddAndRemoveInOrder(self):
        """A boss (Add, Blind 5 at x 2..8) and a hole through it (Remove, Up to the plate's floor
        plane z 0), patterned +x 20 x 3 with Reapply on: each instance adds its boss then cuts
        its hole."""
        self.plate(height=5, rect=(0, 0, 60, 20))
        floor = self.floorPlane()
        boss = self.bossOwner("Boss", (2, 7, 8, 13), 5, 5)
        hole = self.holeOwner(x=5, y=10, z=10, Type="UpToFace", UpToFace=(floor, ["Face1"]))
        lp = linear(self.part(), "LP", [boss, hole], X_AXIS, 40, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(boss, hole, lp)
        self.assertTipVolume(60 * 20 * 5 + 3 * (6 * 6 * 5 - self.hole(10)))

    def testReapplyRemoveOffThePartDoesNothing(self):
        """P1: a plate x 0..30; an r3 hole up to the floor plane at (5, 10), patterned +x 20 x 3,
        Reapply on: instance 3 (x 45) misses the plate and does nothing, with no message."""
        self.plate(rect=(0, 0, 30, 20))
        floor = self.floorPlane()
        hole = self.holeOwner(x=5, Type="UpToFace", UpToFace=(floor, ["Face1"]))
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(30 * 20 * 10 - 2 * self.hole(10))

    def testReapplyFloatingAddFailsLoudly(self):
        """An Add instance touching nothing of the part (Onshape makes it a new part): refused
        loudly until parts are made then (P6b), re-run or copied."""
        self.plate()
        ceiling = self.doc.addObject("Part::Plane", "Ceiling")
        self.S.addObject(ceiling)
        ceiling.Length, ceiling.Width = 200, 40
        ceiling.Placement = App.Placement(V(-20, -10, 15), App.Rotation())
        sk = studioSketch(self.doc, self.S, "BossSk", rects=((2, 7, 8, 13),), z=10)
        boss = makeOwner(
            self.doc,
            self.S,
            "Pad",
            "Boss",
            sk,
            ("P",),
            Type="UpToFace",
            UpToFace=(ceiling, ["Face1"]),
        )
        lp = linear(self.part(), "LP", [boss], X_AXIS, 80, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertRefused(lp, "Boss", "instance 3", "new part")
        blind = self.bossOwner("Blind", (12, 7, 18, 13), 10, 5)
        lp2 = linear(self.part(), "LP2", [blind], X_AXIS, 80, 3)
        lp2.Reapply = True
        self.doc.recompute()
        self.assertRefused(lp2, "Blind", "new part")

    def testReapplyRefusesWhatItCantReRun(self):
        """Under Reapply on, an original it can't re-run yet is refused loudly, naming its type."""
        self.plate()
        p = self.part()
        base = self.doc.getObject("PPad")
        top = next(
            f"Face{i}"
            for i, f in enumerate(base.Shape.Faces, 1)
            if abs(f.CenterOfMass.z - 10) < 1e-6
        )
        thickness = p.newObject("PartDesign::Thickness", "Shell")
        thickness.Base = (base, [top])
        thickness.Value = 1
        listed(thickness)
        lp = linear(p, "LP", [thickness], X_AXIS, 10, 2)
        lp.Reapply = True
        self.doc.recompute()
        self.assertRefused(lp, "Reapply isn't available for Thickness")

    def filletOnInstance2(self):
        """Plate 60 x 20 x 10; an r3 hole up to the plane z 4 (parallel to the motion), patterned +x
        20 x 3, Reapply off (copies); a fillet r1 on instance 2's rim (x 30, z 10)."""
        self.plate()
        floor = self.floorPlane(4)
        hole = self.holeOwner(Type="UpToFace", UpToFace=(floor, ["Face1"]))
        p = self.part()
        lp = linear(p, "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        rim = next(
            f"Edge{i}"
            for i, e in enumerate(lp.Shape.Edges, 1)
            if e.Curve.__class__.__name__ == "Circle"
            and e.Curve.Center.distanceToPoint(V(30, 10, 10)) < 1e-6
        )
        fillet = p.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (lp, [rim])
        fillet.Radius = 1
        listed(fillet)
        self.doc.recompute()
        self.assertValid(fillet)
        return lp, fillet

    def testReapplyToggleKeepsALaterFillet(self):
        """Reapply toggled on and off: the instances are alike in both modes, so their faces keep
        their names and the fillet on instance 2's rim keeps working."""
        lp, fillet = self.filletOnInstance2()
        volume = self.tipShape().Volume
        self.assertLess(volume, 60 * 20 * 10 - 3 * self.hole(6))
        names = faceNames(lp.Shape)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(lp, fillet)
        self.assertEqual(sorted(faceNames(lp.Shape)), sorted(names))
        self.assertAlmostEqual(self.tipShape().Volume, volume, places=4)
        lp.Reapply = False
        self.doc.recompute()
        self.assertValid(lp, fillet)
        self.assertAlmostEqual(self.tipShape().Volume, volume, places=4)

    def testReapplyUndoRedo(self):
        """Reapply set in a transaction goes with undo and comes back with redo (O6's seed: off,
        copies at the seed's height, none reaching the roof: refused; on, each instance up to the
        slanted face)."""
        roof, under = self.roofStudio()
        seed = self.roofSeedOwner(roof, under)
        linear(self.part(), "LP", [seed], X_AXIS, 60, 3)
        self.doc.recompute()
        copies = self.roofVolume() + self.column(10)  # no copy reaches the part: refused
        reRun = self.roofVolume() + self.column(10) + self.column(40) + self.column(70)
        self.assertRefused(self.doc.getObject("LP"), "Could not create all instances")
        self.assertTipVolume(copies)
        self.doc.openTransaction("reapply")
        self.doc.getObject("LP").Reapply = True
        self.doc.recompute()
        self.doc.commitTransaction()
        self.assertTipVolume(reRun)
        self.doc.undo()
        self.doc.recompute()
        self.assertFalse(self.doc.getObject("LP").Reapply)
        self.assertRefused(self.doc.getObject("LP"), "Could not create all instances")
        self.assertTipVolume(copies)
        self.doc.redo()
        self.doc.recompute()
        self.assertTrue(self.doc.getObject("LP").Reapply)
        self.assertValid(self.doc.getObject("LP"))
        self.assertTipVolume(reRun)

    def testReapplySaveAndReopen(self):
        """Saved and opened again: Reapply kept, the same volume and element names."""
        roof, under = self.roofStudio()
        seed = self.roofSeedOwner(roof, under)
        lp = linear(self.part(), "LP", [seed], X_AXIS, 60, 3)
        lp.Reapply = True
        self.doc.recompute()
        before = elementNames(self.tipShape())
        volume = self.tipShape().Volume
        self.dir = tempfile.mkdtemp()
        path = os.path.join(self.dir, "reapply.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        self.docs.append(self.doc.Name)
        self.doc.recompute()
        self.assertTrue(self.doc.getObject("LP").Reapply)
        self.assertTrue(self.doc.getObject("LP").isValid())
        self.assertAlmostEqual(self.tipShape().Volume, volume, places=4)
        self.assertEqual(elementNames(self.tipShape()), before)

    # ------------------------------------------------------------------------------- Reapply (T3 B)
    def testReapplyHoleUpToNextStopsAtItsOwnMaterial(self):
        """A plate x 0..60, y 0..20, z 0..5 with a shelf z 10..15 over x 30..60 (held by a wall at
        x 55..60). An r3 flat hole sketched at z 15 at (10, 10), up to next: through the plate
        (depth to z 0). Patterned +x 30 x 2 with Reapply on: instance 2 at x 40 stops where the
        shelf's material ends (z 10), never reaching the plate."""
        self.plate(height=5, rect=(0, 0, 60, 20))
        p = self.part()
        pad(p, "Wall", sketch(p, "WallSk", xyPlane(p), (55, 0, 60, 20), z=5), 10)
        pad(p, "Shelf", sketch(p, "ShelfSk", xyPlane(p), (30, 0, 60, 20), z=10), 5)
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        base = 60 * 20 * 5 + 5 * 20 * 5 + 30 * 20 * 5
        sk = sketch(p, "HoleSk", xyPlane(p), z=15)
        sk.addGeometry(Part.Circle(V(10, 10, 0), V(0, 0, 1), HOLE_R))
        hole = p.newObject("PartDesign::Hole", "Drill")
        hole.Profile = sk
        hole.Diameter = 2 * HOLE_R
        hole.DepthType = "UpToFirst"
        hole.DrillPoint = "Flat"
        listed(hole)
        self.doc.recompute()
        self.assertValid(hole)
        self.assertTipVolume(base - self.hole(5))
        lp = linear(p, "LP", [hole], X_AXIS, 30, 2)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(lp)
        self.assertTipVolume(base - 2 * self.hole(5))
        self.assertTrue(lp.Shape.isInside(V(40, 10, 2.5), 1e-6, True))
        self.assertFalse(lp.Shape.isInside(V(40, 10, 12.5), 1e-6, True))

    def roundStudio(self):
        """Part R, a disc r20 x 10 at the origin."""
        return self.studio((("R", 20, 10),))

    def testReapplyCircularPatternWithARevolveAndAChamfer(self):
        """The team's shape (designed): on a disc r20 x 10, a pocket x 12..16, y -2..2 down to a datum
        plane at z 4 (Up to face), its rim chamfered 0.5, and a 45 deg revolve of a 4 x 2 profile
        (r 4..8, z 10..12) about z; circular pattern 4 x 90 deg of the three, Reapply on: each
        instance is the pocket, its chamfered rim and the sector."""
        self.roundStudio()
        r = self.part("R")
        floor = r.newObject("PartDesign::Plane", "Floor")
        floor.MapMode = "Deactivated"
        floor.Placement = App.Placement(V(0, 0, 4), App.Rotation())
        listed(floor)
        pocket = r.newObject("PartDesign::Pocket", "Slot")
        pocket.Profile = sketch(r, "SlotSk", xyPlane(r), (12, -2, 16, 2), z=10)
        pocket.Type = "UpToFace"
        pocket.UpToFace = (floor, [""])
        listed(pocket)
        self.doc.recompute()
        self.assertValid(pocket)
        rim = [
            f"Edge{i}"
            for i, e in enumerate(pocket.Shape.Edges, 1)
            if all(abs(v.Point.z - 10) < 1e-6 and 11.9 < v.Point.x < 16.1 for v in e.Vertexes)
        ]
        self.assertEqual(len(rim), 4)
        chamfer = r.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pocket, rim)
        chamfer.Size = 0.5
        listed(chamfer)
        profile = polygonSketch(
            r, "SectorSk", [(r.Origin.OriginFeatures[XZ_PLANE], "")],
            [(4, 10), (8, 10), (8, 12), (4, 12)],
        )
        sector = r.newObject("PartDesign::Revolution", "Sector")
        sector.Profile = profile
        sector.ReferenceAxis = (profile, ["V_Axis"])
        sector.Angle = 45
        listed(sector)
        self.doc.recompute()
        self.assertValid(chamfer, sector)
        pp = polar(r, "PP", [pocket, chamfer, sector], 4)
        pp.Reapply = True
        self.doc.recompute()
        self.assertValid(pp)
        disc = Part.makeCylinder(20, 10)
        cut = disc.cut(box(12, -2, 4, 16, 2, 10))
        edges = [
            e for e in cut.Edges
            if all(abs(v.Point.z - 10) < 1e-6 and 11.9 < v.Point.x < 16.1 for v in e.Vertexes)
        ]
        removed = disc.Volume - cut.makeChamfer(0.5, edges).Volume
        sectorVolume = math.pi * (8**2 - 4**2) * 2 / 8
        self.assertAlmostEqual(
            self.tipShape("R").Volume, disc.Volume - 4 * removed + 4 * sectorVolume, places=2
        )
        self.assertEqual(len(self.tipShape("R").Solids), 1)

    def testReapplyChamferWhoseEdgesAreNotOnTheInstanceFailsLoudly(self):
        """A chamfer of the plate's own edge (not made by a patterned feature) under Reapply on: the
        instance has no such edge, so the pattern fails naming the chamfer and the instance."""
        self.plate()
        p = self.part()
        base = self.doc.getObject("PPad")
        edge = next(
            f"Edge{i}"
            for i, e in enumerate(base.Shape.Edges, 1)
            if all(abs(v.Point.z - 10) < 1e-6 and abs(v.Point.y) < 1e-6 for v in e.Vertexes)
        )
        chamfer = p.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (base, [edge])
        chamfer.Size = 1
        listed(chamfer)
        lp = linear(p, "LP", [chamfer], Y_AXIS, 5, 2)
        lp.Reapply = True
        self.doc.recompute()
        self.assertRefused(lp, "Chamfer", "instance 2", "edges")

    def testReapplyRefusesARevolveUpToAFace(self):
        """A revolve up to a face under Reapply on: refused loudly, naming the end type."""
        self.roundStudio()
        r = self.part("R")
        profile = polygonSketch(
            r, "SectorSk", [(r.Origin.OriginFeatures[XZ_PLANE], "")],
            [(4, 10), (8, 10), (8, 12), (4, 12)],
        )
        stop = r.newObject("PartDesign::Plane", "Stop")
        stop.MapMode = "Deactivated"
        # a plane through the z axis at 60 deg from the profile's
        stop.Placement = App.Placement(
            V(0, 0, 0), App.Rotation(V(0, 0, 1), 60).multiply(App.Rotation(V(1, 0, 0), 90))
        )
        listed(stop)
        sector = r.newObject("PartDesign::Revolution", "Sector")
        sector.Profile = profile
        sector.ReferenceAxis = (profile, ["V_Axis"])
        sector.Type = "UpToFace"
        sector.UpToFace = (stop, [""])
        listed(sector)
        pp = polar(r, "PP", [sector], 4)
        pp.Reapply = True
        self.doc.recompute()
        self.assertRefused(pp, "Reapply isn't available for a revolve", "up to a face")

    def testReapplyTwoSidedRevolveUpToFaceRefused(self):
        """A two-sided revolve, side 1 by an angle (20 deg), side 2 up to a face (a plane through
        the z axis at -40 deg), under Reapply on: refused loudly, naming side 2's end type, as the
        one-sided case (review prline-b4-r1 T3: side 2 wasn't checked, the seed was copied)."""
        self.roundStudio()
        r = self.part("R")
        profile = polygonSketch(
            r, "SectorSk", [(r.Origin.OriginFeatures[XZ_PLANE], "")],
            [(4, 10), (8, 10), (8, 12), (4, 12)],
        )
        stop = r.newObject("PartDesign::Plane", "Stop")
        stop.MapMode = "Deactivated"
        stop.Placement = App.Placement(
            V(0, 0, 0), App.Rotation(V(0, 0, 1), -40).multiply(App.Rotation(V(1, 0, 0), 90))
        )
        listed(stop)
        sector = r.newObject("PartDesign::Revolution", "Sector")
        sector.Profile = profile
        sector.ReferenceAxis = (profile, ["V_Axis"])
        sector.SideType = "Two sides"
        sector.Type = "Angle"
        sector.Angle = 20
        sector.Type2 = "UpToFace"
        sector.UpToFace2 = (stop, [""])
        listed(sector)
        self.doc.recompute()
        self.assertValid(sector)
        pp = polar(r, "PP", [sector], 4)
        pp.Reapply = True
        self.doc.recompute()
        self.assertRefused(pp, "Reapply isn't available for a revolve", "up to a face")

    # ------------------------------------------------------------------------------- oracle 9 (T3 fix)
    # Onshape's answers, batch 9 (notes/onshape-facts.md): R1, a pattern's instances are made
    # instance by instance (each instance's originals in order), Reapply on and off; R2, an
    # instance that fails contributes nothing, silently, and an Up to next seed is re-run at each
    # instance with Reapply off too; R3, each pattern follows its own Reapply, nested too.

    def orderStudio(self, upTo=False):
        """R1: a block 100 x 20 x 10; seed A, a boss 10 x 10 x 10 on it at x 10..20, y 5..15 (z
        10..20; upTo: Up to face to a plane z 20 instead of Blind 10); seed B, a slot Remove from
        the plane x = 15, +x Blind 20, section y 8..12, z 12..18."""
        self.studio((("P", (0, 0, 100, 20), 10),), name="TestStudioOrder")
        if upTo:
            top = self.doc.addObject("Part::Plane", "Top")
            self.S.addObject(top)
            top.Length, top.Width = 200, 40
            top.Placement = App.Placement(V(-20, -10, 20), App.Rotation())
            sk = studioSketch(self.doc, self.S, "ASk", rects=((10, 5, 20, 15),), z=10)
            a = makeOwner(
                self.doc, self.S, "Pad", "A", sk, ("P",), Type="UpToFace", UpToFace=(top, ["Face1"])
            )
        else:
            a = self.bossOwner("A", (10, 5, 20, 15), 10, 10)
        sk = self.doc.addObject("Sketcher::SketchObject", "BSk")
        self.S.addObject(sk)
        # the sketch's u along -z, v along y, normal +x: (u, v) is the point (15, v, -u)
        sk.Placement = App.Placement(V(15, 0, 0), App.Rotation(V(0, 1, 0), 90))
        rect(sk, -18, 8, -12, 12)
        b = makeOwner(self.doc, self.S, "Pocket", "B", sk, ("P",), Length=20, Reversed=True)
        self.doc.recompute()
        self.assertValid(a, b)
        # the seeds: the slot cuts A's half x 15..20 only (x 20..35 is above the block)
        self.assertTipVolume(20000 + 1000 - 5 * 4 * 6)
        self.assertFalse(self.tipShape().isInside(V(17.5, 10, 15), 1e-6, True))
        self.assertTrue(self.tipShape().isInside(V(12.5, 10, 15), 1e-6, True))
        return a, b

    def assertInstanceMajor(self, lp):
        """R1's pattern: instance by instance (A2 B2 A3 B3) gives 22640, and boss 3 is solid at
        x 50..55; feature by feature (A2 A3 B2 B3) would give 22520, B2 cutting A3."""
        self.assertValid(lp)
        self.assertTipVolume(22640)
        self.assertTrue(self.tipShape().isInside(V(52.5, 10, 15), 1e-6, True))
        self.assertFalse(self.tipShape().isInside(V(37.5, 10, 15), 1e-6, True))
        self.assertFalse(self.tipShape().isInside(V(57.5, 10, 15), 1e-6, True))
        self.assertNamesDistinct(lp.Shape)

    def testOrderIsInstanceByInstance(self):
        """R1: the pattern [A, B] +x 20 x 3, Reapply off and on: 22640 both ways (Onshape)."""
        a, b = self.orderStudio()
        lp = linear(self.part(), "LP", [a, b], X_AXIS, 40, 3)
        for reapply in (False, True):
            with self.subTest(reapply=reapply):
                lp.Reapply = reapply
                self.doc.recompute()
                self.assertInstanceMajor(lp)

    def testReapplyOrderWithAnUpToFaceSeed(self):
        """R1 with A Up to face (a plane z 20, so its instances are its copies) and Reapply on, and
        off: still instance by instance, 22640."""
        a, b = self.orderStudio(upTo=True)
        lp = linear(self.part(), "LP", [a, b], X_AXIS, 40, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertInstanceMajor(lp)
        lp.Reapply = False
        self.doc.recompute()
        self.assertInstanceMajor(lp)

    def ceilingStudio(self):
        """R2: a plate x 0..60, y 0..20, z 0..5, and a ceiling x 0..40, z 20..25 over it, held by a
        back wall x 0..40, y 20..25 (the ceiling is of the same part here); the seed, a boss
        10 x 10 at x 5..15, y 5..15 from the plate's top Add up to next: up to the ceiling."""
        self.plate(height=5, rect=(0, 0, 60, 20))
        p = self.part()
        pad(p, "Wall", sketch(p, "WallSk", xyPlane(p), (0, 20, 40, 25)), 25)
        pad(p, "Ceiling", sketch(p, "CeilingSk", xyPlane(p), (0, 0, 40, 20), z=20), 5)
        PartDesign.studioReconcile(studioList(self.doc))
        self.doc.recompute()
        sk = studioSketch(self.doc, self.S, "BossSk", rects=((5, 5, 15, 15),), z=5)
        boss = makeOwner(self.doc, self.S, "Pad", "Boss", sk, ("P",), Type="UpToFirst")
        self.doc.recompute()
        self.assertValid(boss)
        base = 60 * 20 * 5 + 40 * 5 * 25 + 40 * 20 * 5
        self.assertTipVolume(base + 1500)
        return boss, base

    def testFailingInstanceContributesNothing(self):
        """R2: the boss patterned +x 20 x 3, Reapply on and off: instance 3 (x 45..55) has no
        ceiling over it and adds nothing, with no error; instance 2 reaches the ceiling."""
        boss, base = self.ceilingStudio()
        lp = linear(self.part(), "LP", [boss], X_AXIS, 40, 3)
        for reapply in (True, False):
            with self.subTest(reapply=reapply):
                lp.Reapply = reapply
                self.doc.recompute()
                self.assertValid(lp)
                self.assertEqual(lp.getStatusString(), "Valid")
                self.assertTipVolume(base + 2 * 1500)
                self.assertTrue(self.tipShape().isInside(V(30, 10, 12), 1e-6, True))
                self.assertFalse(self.tipShape().isInside(V(50, 10, 7), 1e-6, True))

    def tiltStudio(self):
        """R3: a plate 80 x 60 x 5; a plane z = 20 + 0.1 x + 0.1 y; the seed, a boss 10 x 10 at
        x 5..15, y 5..15 from the plate's top Add up to the plane: 17 high at its centre, 1700."""
        self.plate(height=5, rect=(0, 0, 80, 60))
        tilt = self.doc.addObject("Part::Plane", "Tilt")
        self.S.addObject(tilt)
        tilt.Length, tilt.Width = 250, 250
        tilt.Placement = App.Placement(
            V(-40, -40, 20 - 8), App.Rotation(V(0, 0, 1), V(-0.1, -0.1, 1))
        )
        sk = studioSketch(self.doc, self.S, "BossSk", rects=((5, 5, 15, 15),), z=5)
        boss = makeOwner(
            self.doc, self.S, "Pad", "Boss", sk, ("P",), Type="UpToFace", UpToFace=(tilt, ["Face1"])
        )
        self.doc.recompute()
        self.assertValid(boss)
        self.assertTipVolume(80 * 60 * 5 + 1700)
        return boss

    def testEachPatternFollowsItsReapply(self):
        """R3, one level: the boss +x 30 x 2; Reapply off copies the seed (1700), on follows the
        plane (2000)."""
        boss = self.tiltStudio()
        lp = linear(self.part(), "LP", [boss], X_AXIS, 30, 2)
        for reapply, second in ((False, 1700), (True, 2000)):
            with self.subTest(reapply=reapply):
                lp.Reapply = reapply
                self.doc.recompute()
                self.assertValid(lp)
                self.assertTipVolume(80 * 60 * 5 + 1700 + second)

    def testNestedPatternsFollowTheirOwnReapply(self):
        """R3, nested: inner [boss] +x 30 x 2, outer [inner] +y 30 x 2 (the inner's instance only).
        The outer's instance at (40, 40): both on, re-run there (2300); inner off and outer on,
        the seed's shape (1700); inner on and outer off, a copy of the inner's instance (2000);
        both off, 1700. The inner's own instance: 2000 on, 1700 off."""
        boss = self.tiltStudio()
        p = self.part()
        inner = linear(p, "Inner", [boss], X_AXIS, 30, 2)
        outer = linear(p, "Outer", [inner], Y_AXIS, 30, 2)
        cases = {(True, True): 2300, (False, True): 1700, (True, False): 2000, (False, False): 1700}
        for (innerOn, outerOn), at4040 in cases.items():
            with self.subTest(inner=innerOn, outer=outerOn):
                inner.Reapply = innerOn
                outer.Reapply = outerOn
                self.doc.recompute()
                self.assertValid(inner, outer)
                innerInstance = 2000 if innerOn else 1700
                self.assertTipVolume(80 * 60 * 5 + 1700 + innerInstance + at4040)
                top = 5 + at4040 / 100
                self.assertTrue(self.tipShape().isInside(V(40, 40, top - 0.5), 1e-6, True))
                self.assertFalse(self.tipShape().isInside(V(40, 40, top + 0.5), 1e-6, True))
                # nothing at the seed's place moved by the outer only (the inner's seed isn't one)
                self.assertFalse(self.tipShape().isInside(V(10, 40, 7), 1e-6, True))

    # ------------------------------------------------------------------------------- variants of T3's tests
    # Five of T3's tests pass on a build without T3 (work/hub4/red.sum): each has a variant here
    # whose expected geometry only the re-run (or the instance order) gives.

    def testReapplyBlindBesideAnUpToFaceSeed(self):
        """Variant of testReapplyBlindIsTheCopy: a Blind r3 hole 5 deep at (10, 5) and an r3 hole
        down to the slanted plane at (10, 15), patterned +x 20 x 3, Reapply on: the blind copies,
        the other hole at each instance's own depth."""
        self.plate()
        floor = self.slant()
        blind = self.holeOwner("Blind", y=5.0, Length=5)
        deep = self.holeOwner("Deep", y=15.0, Type="UpToFace", UpToFace=(floor, ["Face1"]))
        lp = linear(self.part(), "LP", [blind, deep], X_AXIS, 40, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(blind, deep, lp)
        depths = sum(self.slantDepth(x) for x in (10, 30, 50))
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(5) - self.hole(1) * depths)
        self.assertNamesDistinct(lp.Shape)

    def testReapplyCircularPatternDownToATiltedFloor(self):
        """Variant of testReapplyCircularPatternWithARevolveAndAChamfer: the pocket goes down to a
        floor plane tilted along x (z = 4 + 0.05 x), which the rotation doesn't keep: each
        instance's pocket reaches it at its own depth, its rim chamfered 0.5."""
        self.roundStudio()
        r = self.part("R")
        slope = math.degrees(math.atan(0.05))
        floor = r.newObject("PartDesign::Plane", "Floor")
        floor.MapMode = "Deactivated"
        floor.Placement = App.Placement(V(0, 0, 4), App.Rotation(V(0, 1, 0), -slope))
        listed(floor)
        pocket = r.newObject("PartDesign::Pocket", "Slot")
        pocket.Profile = sketch(r, "SlotSk", xyPlane(r), (12, -2, 16, 2), z=10)
        pocket.Type = "UpToFace"
        pocket.UpToFace = (floor, [""])
        listed(pocket)
        self.doc.recompute()
        self.assertValid(pocket)
        rim = [
            f"Edge{i}"
            for i, e in enumerate(pocket.Shape.Edges, 1)
            if all(abs(v.Point.z - 10) < 1e-6 and 11.9 < v.Point.x < 16.1 for v in e.Vertexes)
        ]
        self.assertEqual(len(rim), 4)
        chamfer = r.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (pocket, rim)
        chamfer.Size = 0.5
        listed(chamfer)
        self.doc.recompute()
        self.assertValid(chamfer)
        pp = polar(r, "PP", [pocket, chamfer], 4)
        pp.Reapply = True
        self.doc.recompute()
        self.assertValid(pp)
        disc = Part.makeCylinder(20, 10)
        # below the floor: a slab whose top is the plane z = 4 + 0.05 x
        below = Part.makeBox(200, 200, 100, V(-100, -100, -96))
        below.rotate(V(0, 0, 4), V(0, 1, 0), -slope)
        expected = disc
        for k in range(4):
            prism = box(12, -2, -10, 16, 2, 10)
            prism.rotate(V(0, 0, 0), V(0, 0, 1), 90 * k)
            expected = expected.cut(prism.cut(below))
        # the chamfer at the top takes the same at every instance
        seedCut = disc.cut(box(12, -2, 4, 16, 2, 10))
        edges = [
            e
            for e in seedCut.Edges
            if all(abs(v.Point.z - 10) < 1e-6 and 11.9 < v.Point.x < 16.1 for v in e.Vertexes)
        ]
        chamferTakes = seedCut.Volume - seedCut.makeChamfer(0.5, edges).Volume
        self.assertAlmostEqual(
            self.tipShape("R").Volume, expected.Volume - 4 * chamferTakes, places=2
        )
        # the instance at x -14 (low floor, z 3.3) is deeper than the seed's at x 14 (z 4.7)
        self.assertFalse(self.tipShape("R").isInside(V(-14, 0, 3.5), 1e-6, True))
        self.assertTrue(self.tipShape("R").isInside(V(14, 0, 4.5), 1e-6, True))

    def testReapplyRemoveOffThePartDownToASlant(self):
        """Variant of testReapplyRemoveOffThePartDoesNothing: the hole down to the slanted plane,
        Reapply on: instances 1-2 each at their own depth, instance 3 off the plate does nothing.
        Reapply off: copies at the seed's depth, the third doing nothing."""
        self.plate(rect=(0, 0, 30, 20))
        floor = self.slant()
        hole = self.holeOwner(x=5, Type="UpToFace", UpToFace=(floor, ["Face1"]))
        lp = linear(self.part(), "LP", [hole], X_AXIS, 40, 3)
        lp.Reapply = True
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(
            30 * 20 * 10 - self.hole(self.slantDepth(5)) - self.hole(self.slantDepth(25))
        )
        lp.Reapply = False
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(30 * 20 * 10 - 2 * self.hole(self.slantDepth(5)))

    def testReapplyToggleUpToNextKeepsALaterFillet(self):
        """Variant of testReapplyToggleKeepsALaterFillet: the holes are Up to next, re-run at each
        instance both ways (R2), so a fillet on instance 2's rim keeps working through the toggle."""
        self.plate()
        hole = self.holeOwner(Type="UpToFirst")
        p = self.part()
        lp = linear(p, "LP", [hole], X_AXIS, 40, 3)
        self.doc.recompute()
        self.assertValid(hole, lp)
        self.assertTipVolume(60 * 20 * 10 - 3 * self.hole(10))
        rim = next(
            f"Edge{i}"
            for i, e in enumerate(lp.Shape.Edges, 1)
            if e.Curve.__class__.__name__ == "Circle"
            and e.Curve.Center.distanceToPoint(V(30, 10, 10)) < 1e-6
        )
        fillet = p.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (lp, [rim])
        fillet.Radius = 1
        listed(fillet)
        self.doc.recompute()
        self.assertValid(fillet)
        volume = self.tipShape().Volume
        self.assertLess(volume, 60 * 20 * 10 - 3 * self.hole(10))
        names = faceNames(lp.Shape)
        for reapply in (True, False):
            lp.Reapply = reapply
            self.doc.recompute()
            self.assertValid(lp, fillet)
            self.assertEqual(sorted(faceNames(lp.Shape)), sorted(names))
            self.assertAlmostEqual(self.tipShape().Volume, volume, places=4)
