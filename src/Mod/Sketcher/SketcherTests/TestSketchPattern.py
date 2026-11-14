# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: Onshape's editable sketch patterns (onshape-facts GA3-28, 28b, 28c;
# notes/sketch-patterns-design.md). One constraint of type 'Pattern' records a circular or linear
# pattern: its seeds, a pattern-owned pivot point (circular) or direction lines (linear), the
# counts, and an instance table naming each copy by its slot. The solver keeps every copy where the
# pattern puts its seed, so the copies follow edits of the seed, and an edit of a copy moves the
# seed. A count change keeps the copies' ids in their slots; a deleted copy leaves an empty slot
# that stays empty; deleting a seed or a pattern-owned point or line removes the pattern and
# leaves the copies free (as the mirror).
#
# The models are designed: a few circles, lines, arcs and points at known places, and the
# expectations are geometric (where each copy is, by rotation or translation of its seed).

import math
import os
import tempfile
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector
TOL = 1e-7
NONE, START, END, MID = 0, 1, 2, 3  # PointPos
ROOT = -1  # the sketch's root point is (-1, START)


def rot(x, y, deg, cx=0.0, cy=0.0):
    a = math.radians(deg)
    dx, dy = x - cx, y - cy
    return cx + dx * math.cos(a) - dy * math.sin(a), cy + dx * math.sin(a) + dy * math.cos(a)


class PatternCase(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument(type(self).__name__)
        self.sketch = self.doc.addObject("Sketcher::SketchObject", "Sketch")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def circle(self, x, y, r, sketch=None):
        sketch = sketch or self.sketch
        return sketch.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), r))

    def line(self, x1, y1, x2, y2):
        return self.sketch.addGeometry(Part.LineSegment(V(x1, y1, 0), V(x2, y2, 0)))

    def arc(self, x, y, r, a1, a2):
        circle = Part.Circle(V(x, y, 0), V(0, 0, 1), r)
        return self.sketch.addGeometry(Part.ArcOfCircle(circle, math.radians(a1), math.radians(a2)))

    def point(self, x, y):
        return self.sketch.addGeometry(Part.Point(V(x, y, 0)))

    def fixCentre(self, geoId, x, y, pos=MID):
        """DistanceX/DistanceY from the root point: returns the two constraint indices."""
        cx = self.sketch.addConstraint(Sketcher.Constraint("DistanceX", ROOT, START, geoId, pos, x))
        cy = self.sketch.addConstraint(Sketcher.Constraint("DistanceY", ROOT, START, geoId, pos, y))
        return cx, cy

    def assertAt(self, geoId, x, y, pos=MID, sketch=None):
        sketch = sketch or self.sketch
        p = sketch.getPoint(geoId, pos)
        self.assertAlmostEqual(p.x, x, delta=1e-6, msg=f"x of {geoId}.{pos}: {p}")
        self.assertAlmostEqual(p.y, y, delta=1e-6, msg=f"y of {geoId}.{pos}: {p}")

    def assertSolvedClean(self, sketch=None):
        sketch = sketch or self.sketch
        self.assertEqual(sketch.solve(), 0)
        self.assertEqual(list(sketch.MalformedConstraints), [])
        self.assertEqual(list(sketch.ConflictingConstraints), [])
        self.assertEqual(list(sketch.RedundantConstraints), [])

    def patterns(self, sketch=None):
        sketch = sketch or self.sketch
        return [i for i, c in enumerate(sketch.Constraints) if c.Type == "Pattern"]

    def copies(self, index, sketch=None):
        """The live copies, by slot."""
        sketch = sketch or self.sketch
        table = sketch.getPattern(index)["Instances"]
        return {slot: g for slot, g in table.items() if g is not None}


class TestSketchCircularPattern(PatternCase):
    """Seed: a circle of radius 2 at (10, 0); the pivot at the origin, tied to the root point."""

    def setUp(self):
        super().setUp()
        self.seed = self.circle(10, 0, 2)
        self.pattern = self.sketch.addCircularPattern([self.seed], 3, V(0, 0, 0))
        self.pivot = self.sketch.getPattern(self.pattern)["Pivot"]
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", self.pivot, START, ROOT, START))
        self.assertSolvedClean()

    def copyAt(self, k, index=None):
        return self.sketch.getPattern(self.pattern if index is None else index)["Instances"][(0, k, 0)]

    def testOneConstraintRecordsThePattern(self):
        self.assertEqual(self.patterns(), [self.pattern])
        record = self.sketch.getPattern(self.pattern)
        self.assertEqual(record["Kind"], "Circular")
        self.assertEqual(record["Seeds"], [self.seed])
        self.assertEqual(record["Counts"], (3, 1))
        self.assertAlmostEqual(record["Angle"], 2 * math.pi, delta=TOL)
        self.assertEqual(sorted(record["Instances"]), [(0, 1, 0), (0, 2, 0)])
        # the seed, the pivot (construction) and the two copies
        self.assertEqual(self.sketch.GeometryCount, 4)
        self.assertTrue(self.sketch.getConstruction(self.pivot))
        self.assertAt(self.pivot, 0, 0, START)

    def testCopiesSitAtTheirAngles(self):
        for k, deg in ((1, 120), (2, 240)):
            g = self.copyAt(k)
            self.assertAt(g, *rot(10, 0, deg))
            self.assertAlmostEqual(self.sketch.Geometry[g].Radius, 2, delta=1e-6)

    def testCopiesFollowEditsOfTheSeed(self):
        cx, cy = self.fixCentre(self.seed, 10, 0)
        radius = self.sketch.addConstraint(Sketcher.Constraint("Radius", self.seed, 2))
        self.assertSolvedClean()
        self.sketch.setDatum(cx, App.Units.Quantity("7 mm"))
        self.sketch.setDatum(cy, App.Units.Quantity("1 mm"))
        self.sketch.setDatum(radius, App.Units.Quantity("3 mm"))
        self.assertSolvedClean()
        for k, deg in ((1, 120), (2, 240)):
            g = self.copyAt(k)
            self.assertAt(g, *rot(7, 1, deg))
            self.assertAlmostEqual(self.sketch.Geometry[g].Radius, 3, delta=1e-6)

    def testDraggingACopyMovesTheSeed(self):
        self.sketch.addConstraint(Sketcher.Constraint("Radius", self.seed, 2))
        self.assertSolvedClean()
        target = rot(12, 0, 120)
        self.sketch.moveGeometry(self.copyAt(1), MID, V(target[0], target[1], 0), False)
        self.assertSolvedClean()
        self.assertAt(self.seed, 12, 0)
        self.assertAt(self.copyAt(2), *rot(12, 0, 240))

    def testTheSeedFullyConstrainedLeavesNoFreedom(self):
        self.fixCentre(self.seed, 10, 0)
        self.sketch.addConstraint(Sketcher.Constraint("Radius", self.seed, 2))
        self.assertSolvedClean()
        self.assertEqual(self.sketch.DoF, 0)

    def testCountUpKeepsTheCopiesIdsInTheirSlots(self):
        ids = {k: self.sketch.getGeometryId(self.copyAt(k)) for k in (1, 2)}
        self.sketch.setPatternCount(self.pattern, 5)
        self.assertSolvedClean()
        record = self.sketch.getPattern(self.pattern)
        self.assertEqual(record["Counts"], (5, 1))
        self.assertEqual(sorted(record["Instances"]), [(0, k, 0) for k in range(1, 5)])
        for k in (1, 2):
            self.assertEqual(self.sketch.getGeometryId(self.copyAt(k)), ids[k])
        for k in range(1, 5):
            self.assertAt(self.copyAt(k), *rot(10, 0, 72 * k))
        self.assertEqual(self.sketch.GeometryCount, 6)

    def testCountDownRemovesTheCopiesPastTheCount(self):
        self.sketch.setPatternCount(self.pattern, 5)
        ids = {k: self.sketch.getGeometryId(self.copyAt(k)) for k in (1, 2)}
        self.sketch.setPatternCount(self.pattern, 3)
        self.assertSolvedClean()
        self.assertEqual(sorted(self.sketch.getPattern(self.pattern)["Instances"]), [(0, 1, 0), (0, 2, 0)])
        self.assertEqual(self.sketch.GeometryCount, 4)
        for k, deg in ((1, 120), (2, 240)):
            self.assertEqual(self.sketch.getGeometryId(self.copyAt(k)), ids[k])
            self.assertAt(self.copyAt(k), *rot(10, 0, deg))

    def testADeletedCopyLeavesAnEmptySlotThatStaysEmpty(self):
        kept = self.sketch.getGeometryId(self.copyAt(2))
        self.sketch.delGeometry(self.copyAt(1))
        self.assertSolvedClean()
        self.assertEqual(self.patterns(), [self.pattern])
        self.assertIsNone(self.copyAt(1))
        self.sketch.setPatternCount(self.pattern, 5)
        self.assertSolvedClean()
        record = self.sketch.getPattern(self.pattern)
        self.assertIsNone(record["Instances"][(0, 1, 0)])
        self.assertEqual(self.sketch.getGeometryId(self.copyAt(2)), kept)
        for k in (2, 3, 4):
            self.assertAt(self.copyAt(k), *rot(10, 0, 72 * k))
        # the seed, the pivot and three copies
        self.assertEqual(self.sketch.GeometryCount, 5)

    def testDeletingOtherGeometryRenumbersTheRecord(self):
        # geometry after the pattern's: nothing in the record moves
        other = self.point(30, 30)
        before = self.sketch.getPattern(self.pattern)
        self.sketch.delGeometry(other)
        self.assertEqual(self.sketch.getPattern(self.pattern), before)
        # geometry before the pattern's: every index in the record moves down by one
        sk2 = self.doc.addObject("Sketcher::SketchObject", "Sketch2")
        lead = sk2.addGeometry(Part.Point(V(-30, 30, 0)))
        seed = self.circle(10, 0, 2, sketch=sk2)
        index = sk2.addCircularPattern([seed], 3, V(0, 0, 0))
        record = sk2.getPattern(index)
        sk2.delGeometry(lead)
        moved = sk2.getPattern(index)
        self.assertEqual(moved["Seeds"], [seed - 1])
        self.assertEqual(moved["Pivot"], record["Pivot"] - 1)
        self.assertEqual(
            {slot: g - 1 for slot, g in record["Instances"].items()}, moved["Instances"]
        )
        self.assertSolvedClean(sk2)
        self.assertAt(moved["Instances"][(0, 1, 0)], *rot(10, 0, 120), sketch=sk2)

    def testDeletingTheSeedRemovesThePatternAndLeavesTheCopies(self):
        copies = [self.copyAt(1), self.copyAt(2)]
        ids = [self.sketch.getGeometryId(g) for g in copies]
        self.sketch.delGeometry(self.seed)
        self.assertSolvedClean()
        self.assertEqual(self.patterns(), [])
        self.assertEqual(self.sketch.GeometryCount, 3)
        # the copies moved down by one; they stay where they were
        for g, deg, gid in zip(copies, (120, 240), ids):
            self.assertEqual(self.sketch.getGeometryId(g - 1), gid)
            self.assertAt(g - 1, *rot(10, 0, deg))

    def testDeletingThePivotRemovesThePattern(self):
        copy = self.copyAt(1)
        self.sketch.delGeometry(self.pivot)
        self.assertSolvedClean()
        self.assertEqual(self.patterns(), [])
        self.assertAt(copy - 1, *rot(10, 0, 120))

    def testDeletingThePatternConstraintLeavesTheCopiesFree(self):
        copies = [self.copyAt(1), self.copyAt(2)]
        self.sketch.delConstraint(self.pattern)
        self.assertSolvedClean()
        self.assertEqual(self.patterns(), [])
        self.sketch.moveGeometry(self.seed, MID, V(15, 0, 0), False)
        self.assertSolvedClean()
        self.assertAt(copies[0], *rot(10, 0, 120))
        self.assertAt(copies[1], *rot(10, 0, 240))

    def testSavedAndReopenedThePatternStillDrives(self):
        record = self.sketch.getPattern(self.pattern)
        path = os.path.join(tempfile.mkdtemp(), "pattern.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(sketch.getPattern(self.pattern), record)
        sketch.addConstraint(Sketcher.Constraint("DistanceX", ROOT, START, self.seed, MID, 6))
        sketch.addConstraint(Sketcher.Constraint("DistanceY", ROOT, START, self.seed, MID, 0))
        self.assertSolvedClean(sketch)
        for k, deg in ((1, 120), (2, 240)):
            self.assertAt(record["Instances"][(0, k, 0)], *rot(6, 0, deg), sketch=sketch)

    def testAPartialAngleSpreadsTheCopiesOverIt(self):
        seed = self.circle(5, 0, 1)
        index = self.sketch.addCircularPattern([seed], 3, V(0, 0, 0), math.radians(90))
        self.assertSolvedClean()
        table = self.sketch.getPattern(index)["Instances"]
        self.assertAt(table[(0, 1, 0)], *rot(5, 0, 45))
        self.assertAt(table[(0, 2, 0)], *rot(5, 0, 90))
        self.sketch.setPatternAngle(index, math.radians(60))
        self.assertSolvedClean()
        self.assertAt(table[(0, 2, 0)], *rot(5, 0, 60))

    def testSeveralSeedsAndAPivotOffTheOrigin(self):
        a = self.circle(13, 2, 1)
        b = self.point(14, 2)
        index = self.sketch.addCircularPattern([a, b], 4, V(10, 2, 0))
        self.assertSolvedClean()
        table = self.sketch.getPattern(index)["Instances"]
        self.assertEqual(sorted(table), [(i, k, 0) for i in (0, 1) for k in (1, 2, 3)])
        for k in (1, 2, 3):
            self.assertAt(table[(0, k, 0)], *rot(13, 2, 90 * k, 10, 2))
            self.assertAt(table[(1, k, 0)], *rot(14, 2, 90 * k, 10, 2), START)

    def testLinesAndArcsRotateWithTheirCopies(self):
        # open in Onshape (ops#640 6820075161): built rotating, as a part's circular pattern does
        ln = self.line(10, 0, 12, 1)
        ac = self.arc(0, 10, 3, 0, 90)
        index = self.sketch.addCircularPattern([ln, ac], 4, V(0, 0, 0))
        self.assertSolvedClean()
        table = self.sketch.getPattern(index)["Instances"]
        for k in (1, 2, 3):
            self.assertAt(table[(0, k, 0)], *rot(10, 0, 90 * k), START)
            self.assertAt(table[(0, k, 0)], *rot(12, 1, 90 * k), END)
            self.assertAt(table[(1, k, 0)], *rot(0, 10, 90 * k))
            self.assertAt(table[(1, k, 0)], *rot(3, 10, 90 * k), START)
            self.assertAt(table[(1, k, 0)], *rot(0, 13, 90 * k), END)

    def testAnArcCopyFollowsItsSeedsSweep(self):
        ac = self.arc(0, 10, 3, 0, 90)
        index = self.sketch.addCircularPattern([ac], 2, V(0, 0, 0))
        # the pivot tied to the root: a free pivot may move instead of the copy's ends
        pivot = self.sketch.getPattern(index)["Pivot"]
        self.sketch.addConstraint(Sketcher.Constraint("Coincident", pivot, START, ROOT, START))
        angle = self.sketch.addConstraint(Sketcher.Constraint("Angle", ac, math.radians(90)))
        self.fixCentre(ac, 0, 10)
        self.sketch.addConstraint(Sketcher.Constraint("Radius", ac, 3))
        self.assertSolvedClean()
        self.sketch.setDatum(angle, App.Units.Quantity("45 deg"))
        self.assertSolvedClean()
        g = self.sketch.getPattern(index)["Instances"][(0, 1, 0)]
        self.assertAt(g, *rot(0, 10, 180))
        sx, sy = self.sketch.getPoint(ac, START).x, self.sketch.getPoint(ac, START).y
        ex, ey = self.sketch.getPoint(ac, END).x, self.sketch.getPoint(ac, END).y
        self.assertAt(g, *rot(sx, sy, 180), START)
        self.assertAt(g, *rot(ex, ey, 180), END)

    def testCopiesTakeTheSeedsConstructionFlag(self):
        seed = self.circle(5, 5, 1)
        self.sketch.setConstruction(seed, True)
        index = self.sketch.addCircularPattern([seed], 2, V(0, 0, 0))
        g = self.sketch.getPattern(index)["Instances"][(0, 1, 0)]
        self.assertTrue(self.sketch.getConstruction(g))

    def testRefusedInput(self):
        ellipse = self.sketch.addGeometry(Part.Ellipse(V(20, 0, 0), 2, 1))
        with self.assertRaises(ValueError):
            self.sketch.addCircularPattern([ellipse], 3, V(0, 0, 0))
        with self.assertRaises(ValueError):
            self.sketch.addCircularPattern([self.seed], 0, V(0, 0, 0))
        with self.assertRaises(ValueError):
            self.sketch.addCircularPattern([], 3, V(0, 0, 0))
        with self.assertRaises(ValueError):
            self.sketch.addCircularPattern([99], 3, V(0, 0, 0))
        with self.assertRaises(ValueError):
            self.sketch.setPatternCount(self.pattern, 0)
        with self.assertRaises(ValueError):
            self.sketch.setPatternCount(1, 3)  # not a pattern: the pivot's coincidence is 1
        self.assertEqual(self.sketch.getPattern(self.pattern)["Counts"], (3, 1))

    def testMoreInstancesThanARecordHoldsAreRefused(self):
        other = self.circle(30, 0, 1)
        count = self.sketch.GeometryCount
        with self.assertRaises(ValueError):
            self.sketch.addCircularPattern([other], 100001, V(0, 0, 0))
        with self.assertRaises(ValueError):
            self.sketch.setPatternCount(self.pattern, 100001)
        with self.assertRaises(ValueError):
            self.sketch.addLinearPattern([other], 400, V(1, 0, 0), 400)
        self.assertEqual(self.sketch.GeometryCount, count)
        self.assertEqual(self.sketch.getPattern(self.pattern)["Counts"], (3, 1))

    def testAReferencePatternHoldsNothingAndSolves(self):
        # a pattern is no dimension: it can't be made a reference here (only a file could hold
        # one), and either way the sketch solves
        try:
            self.sketch.setDriving(self.pattern, False)
        except ValueError:
            pass
        self.assertEqual(self.sketch.solve(), 0)

    def testMirroringOrCopyingAWholePatternCopiesNoPattern(self):
        # the record is not copied with its geometry: the new geometry is free, and the pattern
        # still drives its own copies only
        everything = [self.seed, self.pivot, self.copyAt(1), self.copyAt(2)]
        axis = self.line(20, -5, 20, 5)
        count = self.sketch.GeometryCount
        self.sketch.addSymmetric(everything, axis, NONE)
        self.assertEqual(self.sketch.GeometryCount, count + 4)
        self.assertEqual(self.patterns(), [self.pattern])
        self.sketch.addCopy(everything, V(0, 30, 0), False)
        self.assertGreaterEqual(self.sketch.GeometryCount, count + 8)
        self.assertEqual(self.patterns(), [self.pattern])
        self.assertSolvedClean()
        self.assertEqual(self.sketch.getPattern(self.pattern)["Counts"], (3, 1))
        for k, deg in ((1, 120), (2, 240)):
            self.assertAt(self.copyAt(k), *rot(10, 0, deg))

    def testTrimmingTheSeedRemovesThePatternAndLeavesTheCopies(self):
        # a line through the seed circle (crossing it at (10, -2) and (10, 2)); the circle's
        # right half is trimmed away. The trim replaces the seed, so the pattern goes as for a
        # deleted seed: no record is left naming an arc as the seed of circles
        copies = [self.copyAt(1), self.copyAt(2)]
        self.line(10, -5, 10, 5)
        self.sketch.trim(self.seed, V(12, 0, 0))
        self.assertEqual(self.patterns(), [])
        self.assertEqual(self.sketch.Geometry[self.seed].TypeId, "Part::GeomArcOfCircle")
        for g, deg in zip(copies, (120, 240)):
            self.assertEqual(self.sketch.Geometry[g].TypeId, "Part::GeomCircle")
            self.assertAt(g, *rot(10, 0, deg))
        self.assertSolvedClean()


class TestSketchLinearPattern(PatternCase):
    """Seed: a circle of radius 1 at the origin; direction 1 along +X at a spacing of 5."""

    def setUp(self):
        super().setUp()
        self.seed = self.circle(0, 0, 1)
        self.pattern = self.sketch.addLinearPattern([self.seed], 3, V(5, 0, 0))
        record = self.sketch.getPattern(self.pattern)
        self.dir1, self.dir2 = record["Directions"]
        self.assertSolvedClean()

    def copyAt(self, a, b=0, index=None):
        return self.sketch.getPattern(self.pattern if index is None else index)["Instances"][(0, a, b)]

    def testOneConstraintRecordsThePattern(self):
        record = self.sketch.getPattern(self.pattern)
        self.assertEqual(record["Kind"], "Linear")
        self.assertEqual(record["Counts"], (3, 1))
        self.assertIsNone(self.dir2)
        self.assertEqual(sorted(record["Instances"]), [(0, 1, 0), (0, 2, 0)])
        # direction 1 starts at the seed's centre and is as long as the spacing (GA3-28c)
        self.assertTrue(self.sketch.getConstruction(self.dir1))
        self.assertAt(self.dir1, 0, 0, START)
        self.assertAt(self.dir1, 5, 0, END)
        self.assertEqual(self.sketch.GeometryCount, 4)

    def testCopiesSitAtMultiplesOfTheSpacing(self):
        self.assertAt(self.copyAt(1), 5, 0)
        self.assertAt(self.copyAt(2), 10, 0)
        self.assertAlmostEqual(self.sketch.Geometry[self.copyAt(2)].Radius, 1, delta=1e-6)

    def testTheSpacingIsTheDirectionLinesLength(self):
        self.fixCentre(self.dir1, 0, 0, START)
        spacing = self.sketch.addConstraint(Sketcher.Constraint("Distance", self.dir1, 5))
        self.sketch.addConstraint(Sketcher.Constraint("Horizontal", self.dir1))
        self.fixCentre(self.seed, 0, 0)
        self.assertSolvedClean()
        self.sketch.setDatum(spacing, App.Units.Quantity("6 mm"))
        self.assertSolvedClean()
        self.assertAt(self.copyAt(1), 6, 0)
        self.assertAt(self.copyAt(2), 12, 0)

    def testCopiesFollowEditsOfTheSeed(self):
        cx, cy = self.fixCentre(self.seed, 0, 0)
        radius = self.sketch.addConstraint(Sketcher.Constraint("Radius", self.seed, 1))
        self.assertSolvedClean()
        self.sketch.setDatum(cy, App.Units.Quantity("3 mm"))
        self.sketch.setDatum(radius, App.Units.Quantity("2 mm"))
        self.assertSolvedClean()
        d = self.sketch.getPoint(self.dir1, END) - self.sketch.getPoint(self.dir1, START)
        self.assertAt(self.copyAt(1), d.x, 3 + d.y)
        self.assertAt(self.copyAt(2), 2 * d.x, 3 + 2 * d.y)
        self.assertAlmostEqual(self.sketch.Geometry[self.copyAt(1)].Radius, 2, delta=1e-6)

    def testTwoDirectionsMakeAGrid(self):
        seed = self.point(0, 20)
        index = self.sketch.addLinearPattern([seed], 3, V(2, 0, 0), 2, V(0, 3, 0))
        self.assertSolvedClean()
        record = self.sketch.getPattern(index)
        self.assertEqual(record["Counts"], (3, 2))
        self.assertIsNotNone(record["Directions"][1])
        table = record["Instances"]
        self.assertEqual(len(table), 5)
        for (i, a, b), g in table.items():
            self.assertAt(g, 2 * a, 20 + 3 * b, START)

    def testCountChangesKeepIdsAndAddTheSecondDirection(self):
        ids = {a: self.sketch.getGeometryId(self.copyAt(a)) for a in (1, 2)}
        self.sketch.setPatternCount(self.pattern, 2, 2)
        self.assertSolvedClean()
        record = self.sketch.getPattern(self.pattern)
        self.assertEqual(record["Counts"], (2, 2))
        self.assertEqual(sorted(record["Instances"]), [(0, 0, 1), (0, 1, 0), (0, 1, 1)])
        self.assertEqual(self.sketch.getGeometryId(self.copyAt(1)), ids[1])
        dir2 = record["Directions"][1]
        self.assertIsNotNone(dir2)
        # the second direction, added at the first's spacing, turned a quarter counterclockwise
        d2 = self.sketch.getPoint(dir2, END) - self.sketch.getPoint(dir2, START)
        self.assertAlmostEqual(d2.x, 0, delta=1e-6)
        self.assertAlmostEqual(d2.y, 5, delta=1e-6)
        self.assertAt(self.copyAt(1, 1), 5, 5)
        self.assertAt(self.copyAt(0, 1), 0, 5)
        # the copy at slot (2, 0) is gone: seed, two directions and three copies
        self.assertEqual(self.sketch.GeometryCount, 6)

    def testADeletedCopyLeavesAnEmptySlotThatStaysEmpty(self):
        self.sketch.delGeometry(self.copyAt(1))
        self.assertSolvedClean()
        self.sketch.setPatternCount(self.pattern, 5)
        self.assertSolvedClean()
        record = self.sketch.getPattern(self.pattern)
        self.assertIsNone(record["Instances"][(0, 1, 0)])
        for a in (2, 3, 4):
            self.assertAt(self.copyAt(a), 5 * a, 0)

    def testDeletingTheDirectionLineRemovesThePattern(self):
        copy = self.copyAt(2)
        self.sketch.delGeometry(self.dir1)
        self.assertSolvedClean()
        self.assertEqual(self.patterns(), [])
        self.assertAt(copy - 1, 10, 0)

    def testArcsAndLinesTranslate(self):
        ac = self.arc(0, -10, 2, 30, 120)
        ln = self.line(0, -20, 1, -19)
        index = self.sketch.addLinearPattern([ac, ln], 3, V(0, -4, 0))
        self.assertSolvedClean()
        table = self.sketch.getPattern(index)["Instances"]
        for a in (1, 2):
            for pos in (MID, START, END):
                p = self.sketch.getPoint(ac, pos)
                self.assertAt(table[(0, a, 0)], p.x, p.y - 4 * a, pos)
            self.assertAt(table[(1, a, 0)], 0, -20 - 4 * a, START)
            self.assertAt(table[(1, a, 0)], 1, -19 - 4 * a, END)

    def testSavedAndReopenedThePatternStillDrives(self):
        self.sketch.setPatternCount(self.pattern, 2, 2)
        record = self.sketch.getPattern(self.pattern)
        path = os.path.join(tempfile.mkdtemp(), "linear.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        sketch = self.doc.getObject("Sketch")
        self.assertEqual(sketch.getPattern(self.pattern), record)
        # the direction lines held: free ones may take up the seed's move instead of the copies
        for direction in record["Directions"]:
            sketch.addConstraint(Sketcher.Constraint("Block", direction))
        sketch.addConstraint(Sketcher.Constraint("DistanceX", ROOT, START, self.seed, MID, 1))
        sketch.addConstraint(Sketcher.Constraint("DistanceY", ROOT, START, self.seed, MID, 1))
        self.assertSolvedClean(sketch)
        self.assertAt(record["Instances"][(0, 1, 1)], 6, 6, sketch=sketch)


if __name__ == "__main__":
    unittest.main()
