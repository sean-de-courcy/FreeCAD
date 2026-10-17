# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#325, B+ Stage 1 session 3a)

"""Remove from / Intersect with several parts: one cut, one sibling per extra part
(PartDesign.makeSiblings, notes/bplus-stage1-design.md 2.4, R-t1 to R-t8). A sibling is a
feature of the same type in the other part's Body, on the same sketch; its parameters follow the
primary by expression, its links are copies, and SiblingOf names the primary without a
dependency. Designed geometry: S1's lid and enclosure. The enclosure is 40 x 40 x 10 (16000), the
lid 40 x 40 x 5 on top of it (8000), both at the origin; four clearance holes of radius 2 at
(5, 5), (35, 5), (5, 35) and (35, 35), sketched on the lid's top. Oracles are volumes and point
membership."""

import math
import unittest

import FreeCAD as App
import Part
import PartDesign

from PartDesignTests.TestStudio import inside, pad, rect, sketch, xyPlane

V = App.Vector

R = 2
CENTERS = ((5, 5), (35, 5), (5, 35), (35, 35))
HOLES = len(CENTERS) * math.pi * R**2  # the holes' area


class TestSiblings(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestSiblings")
        self.doc.UndoMode = 1

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def model(self, profile=None, type="ThroughAll", length=5, container=None, placement=None):
        """The enclosure and the lid, and a pocket in the lid from the hole sketch (or from
        `profile`, a function of the lid Body that makes the sketch). The sketch sits on the
        lid's XY plane at z 15, not on the lid's plate, so the plate can fail without it. Both
        Bodies go in `container` if given, both with `placement` (a studio's parts are placed
        alike)."""
        doc = self.doc

        def body(name):
            made = doc.addObject("PartDesign::Body", name)
            made.Label = name
            if container:
                container.addObject(made)
            if placement:
                made.Placement = placement
            return made

        self.enclosure = body("Enclosure")
        self.baseSk = sketch(self.enclosure, "BaseSk", xyPlane(self.enclosure), (0, 0, 40, 40))
        self.base = pad(self.enclosure, "Base", self.baseSk, 10)
        self.lid = body("Lid")
        plateSk = sketch(self.lid, "PlateSk", xyPlane(self.lid), (0, 0, 40, 40), z=10)
        self.plate = pad(self.lid, "Plate", plateSk, 5)
        if profile:
            self.holeSk = profile(self.lid)
        else:
            self.holeSk = sketch(self.lid, "HoleSk", xyPlane(self.lid), z=15)
            self.circles(CENTERS)
        self.pocket = self.lid.newObject("PartDesign::Pocket", "Holes")
        self.pocket.Profile = self.holeSk
        self.pocket.Type = type
        self.pocket.Length = length
        doc.recompute()
        self.assertTrue(self.pocket.isValid(), self.pocket.getStatusString())
        return self.pocket

    def circles(self, centers):
        for x, y in centers:
            self.holeSk.addGeometry(Part.Circle(V(x, y, 0), V(0, 0, 1), R))

    def sibling(self, bodies=None):
        siblings = PartDesign.makeSiblings(self.pocket, bodies or [self.enclosure])
        self.doc.recompute()
        self.assertEqual(len(siblings), len(bodies or [self.enclosure]))
        for sibling in siblings:
            self.assertTrue(sibling.isValid(), sibling.getStatusString())
        return siblings[0]

    def assertHolesAt(self, centers, enclosureDepth=10):
        """Both parts are cut through at `centers` (the enclosure to `enclosureDepth` below its
        top), and solid between them."""
        for x, y in centers:
            self.assertFalse(inside(self.lid.Shape, V(x, y, 12.5)), (x, y))
            if enclosureDepth:
                self.assertFalse(inside(self.enclosure.Shape, V(x, y, 10.5 - enclosureDepth)))
        self.assertTrue(inside(self.lid.Shape, V(20, 20, 12.5)))
        self.assertTrue(inside(self.enclosure.Shape, V(20, 20, 5)))

    def testHolesThroughTwoParts(self):
        """R-t1: the clearance holes, Through all, as a pocket in the lid and its sibling in the
        enclosure: a Pocket in each Body on the one sketch. Both volumes lose the four holes, and
        the holes line up (point membership through both)."""
        self.model()
        sibling = self.sibling()
        self.assertEqual(sibling.TypeId, "PartDesign::Pocket")
        self.assertIn(sibling, self.enclosure.Group)
        self.assertIs(self.enclosure.Tip, sibling)
        self.assertIs(sibling.SiblingOf, self.pocket)
        self.assertEqual(sibling.Label, "Holes (Enclosure)")
        self.assertEqual(sibling.Profile, self.pocket.Profile)
        self.assertEqual(PartDesign.siblingsOf(self.pocket), [sibling])
        self.assertAlmostEqual(self.lid.Shape.Volume, 8000 - HOLES * 5, places=6)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000 - HOLES * 10, places=6)
        self.assertHolesAt(CENTERS)
        self.assertNotIn("Warning", sibling.State)

    def testSiblingFollowsTheLength(self):
        """R-t2: by length, 5 from the lid's top, the holes end at the enclosure's top (16000,
        touching, no warning). The primary's Length 5 -> 8: the sibling's is 8 too, and the
        enclosure loses 3 of each hole."""
        self.model(type="Length", length=5)
        sibling = self.sibling()
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000, places=6)
        self.assertNotIn("Warning", sibling.State)
        self.pocket.Length = 8
        self.doc.recompute()
        self.assertEqual(sibling.Length.Value, 8)
        self.assertAlmostEqual(self.lid.Shape.Volume, 8000 - HOLES * 5, places=6)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000 - HOLES * 3, places=6)
        self.assertHolesAt(CENTERS, enclosureDepth=3)

    def testIntersectWithTwoParts(self):
        """R-t3: Intersect with (Operation Common) through both parts, a 20 x 20 square: each
        part keeps what the tool shares with it, the lid 20 x 20 x 5 (2000) and the enclosure
        20 x 20 x 10 (4000). The sibling's Operation follows."""

        def square(lid):
            return sketch(lid, "SquareSk", xyPlane(lid), (10, 10, 30, 30), z=15)

        self.model(profile=square)
        self.pocket.Operation = "Common"
        self.doc.recompute()
        sibling = self.sibling()
        self.assertEqual(sibling.Operation, "Common")
        self.assertAlmostEqual(self.lid.Shape.Volume, 2000, places=6)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 4000, places=6)

    def testRedrawnSketchMovesBothCuts(self):
        """R-t4: the hole sketch redrawn, its circles deleted and added again 2 further in x and
        y: both cuts move the same way, and both stay valid with the same volumes."""
        self.model()
        sibling = self.sibling()
        self.holeSk.deleteAllGeometry()
        moved = [(x + 2, y + 2) for x, y in CENTERS]
        self.circles(moved)
        self.doc.recompute()
        self.assertTrue(self.pocket.isValid(), self.pocket.getStatusString())
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        self.assertAlmostEqual(self.lid.Shape.Volume, 8000 - HOLES * 5, places=6)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000 - HOLES * 10, places=6)
        self.assertHolesAt(moved)
        # the old centres are solid again in both
        self.assertTrue(inside(self.lid.Shape, V(5, 5, 12.5)))
        self.assertTrue(inside(self.enclosure.Shape, V(5, 5, 5)))

    def testSiblingThatMissesItsPartWarns(self):
        """R-t5: the enclosure moved away by an earlier edit (its sketch 100 along x): the
        sibling's holes miss it. The sibling computes, with a warning that it doesn't touch the
        Enclosure; the enclosure is whole (16000). The primary is unaffected, without a
        warning."""
        self.model()
        sibling = self.sibling()
        self.baseSk.AttachmentOffset = App.Placement(V(100, 0, 0), App.Rotation())
        self.doc.recompute()
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        self.assertIn("Warning", sibling.State)
        self.assertIn("doesn't touch Enclosure", sibling.getStatusString())
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000, places=6)
        self.assertNotIn("Warning", self.pocket.State)
        self.assertAlmostEqual(self.lid.Shape.Volume, 8000 - HOLES * 5, places=6)

    def testAbortAndUndoRemoveTheSiblings(self):
        """R-t6: siblings made in a transaction that is aborted leave nothing; made in one that
        is committed, one undo removes them all, and the enclosure is whole again."""
        self.model()
        other = self.doc.addObject("PartDesign::Body", "Other")
        pad(other, "Block", sketch(other, "BlockSk", xyPlane(other), (0, 0, 10, 10)), 20)
        self.doc.recompute()
        before = sorted(o.Name for o in self.doc.Objects)
        self.doc.openTransaction("Siblings")
        PartDesign.makeSiblings(self.pocket, [self.enclosure, other])
        self.doc.abortTransaction()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.doc.openTransaction("Siblings")
        self.assertEqual(len(PartDesign.makeSiblings(self.pocket, [self.enclosure, other])), 2)
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertEqual(len(self.doc.Objects), len(before) + 2)
        self.doc.undo()
        self.doc.recompute()
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertIs(self.enclosure.Tip, self.base)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000, places=6)

    def testChangesFromPython(self):
        """R-t7: the primary's Type changed from Python, Through all to Length 7: the sibling's
        follow (expressions), Length too, which Pocket keeps read-only while the siblings were
        made. The primary's UpToFace changed from Python (read-only too, by Type): the sibling
        fails, out of step with the primary, until the primary's siblings are made again (as its
        panel's OK does)."""
        self.model()
        sibling = self.sibling()
        self.pocket.Type = "Length"
        self.pocket.Length = 7
        self.doc.recompute()
        self.assertEqual(sibling.Type, "Length")
        self.assertEqual(sibling.Length.Value, 7)
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        self.pocket.UpToFace = (self.base, ["Face1"])
        self.doc.recompute()
        self.assertFalse(sibling.isValid())
        self.assertIn("out of step with Holes", sibling.getStatusString())
        self.assertTrue(self.pocket.isValid(), self.pocket.getStatusString())
        PartDesign.makeSiblings(self.pocket, [self.enclosure])
        self.doc.recompute()
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        self.assertEqual(sibling.UpToFace, self.pocket.UpToFace)

    def testSiblingComputesWhenThePrimaryFails(self):
        """R-t8: the lid's plate fails (length 0), and the primary with it: the sibling still
        cuts the enclosure. SiblingOf is no dependency, and the expressions don't fail it."""
        self.model()
        sibling = self.sibling()
        self.plate.Length = 0
        self.doc.recompute()
        self.assertFalse(self.pocket.isValid())
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000 - HOLES * 10, places=6)

    def testHoleSiblings(self):
        """S1's clearance holes as a Hole, Through all, diameter 4 on the four circles: its
        sibling in the enclosure is a Hole too, and both parts lose the four holes."""
        self.model()
        hole = self.lid.newObject("PartDesign::Hole", "Clearance")
        hole.Profile = self.holeSk
        hole.Diameter = 2 * R
        hole.DepthType = "ThroughAll"
        self.lid.removeObject(self.pocket)
        self.doc.removeObject(self.pocket.Name)
        self.doc.recompute()
        self.assertTrue(hole.isValid(), hole.getStatusString())
        [sibling] = PartDesign.makeSiblings(hole, [self.enclosure])
        self.doc.recompute()
        self.assertEqual(sibling.TypeId, "PartDesign::Hole")
        self.assertTrue(sibling.isValid(), sibling.getStatusString())
        self.assertAlmostEqual(self.lid.Shape.Volume, 8000 - HOLES * 5, places=4)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000 - HOLES * 10, places=4)
        self.assertHolesAt(CENTERS)

    def testHoleSiblingFollowsAThreadTypeChange(self):
        """PR 304 round 1: a Hole's ThreadType rewrites its ThreadSize list and value and its
        Diameter, and the sibling's expressions set ThreadSize before ThreadType. The primary's
        ThreadType to UNC, then back to ISO metric: after each, the sibling has the primary's
        type, size and diameter, and computes. Each part loses the four holes at the primary's
        diameter, through its own thickness (the lid 5, the enclosure 10)."""
        self.model()
        hole = self.lid.newObject("PartDesign::Hole", "Clearance")
        hole.Profile = self.holeSk
        hole.Diameter = 2 * R
        hole.DepthType = "ThroughAll"
        self.lid.removeObject(self.pocket)
        self.doc.removeObject(self.pocket.Name)
        self.doc.recompute()
        [sibling] = PartDesign.makeSiblings(hole, [self.enclosure])
        self.doc.recompute()
        for threadType in ("UNC", "ISOMetricProfile"):
            hole.ThreadType = threadType
            self.doc.recompute()
            self.assertTrue(hole.isValid(), hole.getStatusString())
            self.assertTrue(sibling.isValid(), sibling.getStatusString())
            self.assertEqual(
                (sibling.ThreadType, sibling.ThreadSize, sibling.Diameter.Value),
                (hole.ThreadType, hole.ThreadSize, hole.Diameter.Value),
            )
            area = len(CENTERS) * math.pi * (hole.Diameter.Value / 2) ** 2
            self.assertAlmostEqual(self.lid.Shape.Volume, 8000 - area * 5, places=4)
            self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000 - area * 10, places=4)

    def testPrimaryNamedLikeAUnit(self):
        """PR 304 round 1: a primary named "H" (made from Python) can't be named in an
        expression, "H" being a unit: makeSiblings refuses before it adds anything."""
        self.model(type="Length", length=5)
        named = self.lid.newObject("PartDesign::Pocket", "H")
        named.Profile = self.holeSk
        named.Type = "Length"
        named.Length = 5
        self.lid.removeObject(self.pocket)
        self.doc.removeObject(self.pocket.Name)
        self.doc.recompute()
        self.assertEqual(named.Name, "H")
        self.assertTrue(named.isValid(), named.getStatusString())
        before = sorted(o.Name for o in self.doc.Objects)
        with self.assertRaisesRegex(Exception, "can't be read in an expression"):
            PartDesign.makeSiblings(named, [self.enclosure])
        self.assertEqual(sorted(o.Name for o in self.doc.Objects), before)
        self.assertIs(self.enclosure.Tip, self.base)

    def testRedrawRebindsSubElementProfiles(self):
        """R-t4 with a sub-element Profile, per owner: two squares, 10 x 10 at (5, 5) and at
        (25, 25); the pocket's Profile is the second's four edges (Edge5 to Edge8). The first
        square deleted renumbers them Edge1 to Edge4: the primary and its sibling re-bind alike
        and keep cutting the second square only (the lid 7500, the enclosure 15000)."""

        def squares(lid):
            return sketch(lid, "SquaresSk", xyPlane(lid), (5, 5, 15, 15), (25, 25, 35, 35), z=15)

        self.model(profile=squares)
        self.pocket.Profile = (self.holeSk, ["Edge5", "Edge6", "Edge7", "Edge8"])
        self.doc.recompute()
        sibling = self.sibling()
        self.assertEqual(sibling.Profile[1], ["Edge5", "Edge6", "Edge7", "Edge8"])
        self.assertAlmostEqual(self.lid.Shape.Volume, 7500, places=6)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 15000, places=6)
        for i in range(3, -1, -1):
            self.holeSk.delGeometry(i)
        self.doc.recompute()
        for feature in (self.pocket, sibling):
            self.assertTrue(feature.isValid(), feature.getStatusString())
            self.assertEqual(feature.Profile[1], ["Edge1", "Edge2", "Edge3", "Edge4"])
        self.assertAlmostEqual(self.lid.Shape.Volume, 7500, places=6)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 15000, places=6)
        self.assertFalse(inside(self.lid.Shape, V(30, 30, 12.5)))
        self.assertFalse(inside(self.enclosure.Shape, V(30, 30, 5)))
        self.assertTrue(inside(self.lid.Shape, V(10, 10, 12.5)))
        self.assertTrue(inside(self.enclosure.Shape, V(10, 10, 5)))

    def testSiblingsInAPlacedPart(self):
        """R-t1 off the origin: the lid and the enclosure in an App::Part placed (-50, 3, 7),
        turned 70 degrees, each Body placed alike (17, -9, 4), turned 33 degrees. The sibling
        computes, both parts lose the four holes, and the holes line up in the document's frame
        (point membership through both global shapes)."""
        part = self.doc.addObject("App::Part", "Studio")
        part.Placement = App.Placement(V(-50, 3, 7), App.Rotation(V(0, 1, 1), 70))
        placement = App.Placement(V(17, -9, 4), App.Rotation(V(1, 2, 3), 33))
        self.model(container=part, placement=placement)
        sibling = self.sibling()
        self.assertAlmostEqual(self.lid.Shape.Volume, 8000 - HOLES * 5, places=4)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000 - HOLES * 10, places=4)
        frame = part.Placement.multiply(placement)

        def placed(body):
            shape = body.Shape.copy()
            shape.Placement = body.getGlobalPlacement()
            return shape

        lid, enclosure = placed(self.lid), placed(self.enclosure)
        for x, y in CENTERS:
            self.assertFalse(inside(lid, frame.multVec(V(x, y, 12.5))), (x, y))
            self.assertFalse(inside(enclosure, frame.multVec(V(x, y, 5))), (x, y))
        self.assertTrue(inside(lid, frame.multVec(V(20, 20, 12.5))))
        self.assertTrue(inside(enclosure, frame.multVec(V(20, 20, 5))))
        self.assertNotIn("Warning", sibling.State)

    def testUntickRemovesASibling(self):
        """The ticks again: makeSiblings with the enclosure unticked deletes its sibling, and
        the enclosure is whole. A sibling that something else uses (a sketch on it) is kept,
        and the error names the user."""
        self.model()
        name = self.sibling().Name
        PartDesign.makeSiblings(self.pocket, [])
        self.doc.recompute()
        self.assertIsNone(self.doc.getObject(name))
        self.assertEqual(PartDesign.siblingsOf(self.pocket), [])
        self.assertIs(self.enclosure.Tip, self.base)
        self.assertAlmostEqual(self.enclosure.Shape.Volume, 16000, places=6)
        sibling = self.sibling()
        user = self.enclosure.newObject("Sketcher::SketchObject", "OnTheSibling")
        user.AttachmentSupport = [(sibling, "Face1")]
        user.MapMode = "FlatFace"
        self.doc.recompute()
        with self.assertRaisesRegex(Exception, "OnTheSibling"):
            PartDesign.makeSiblings(self.pocket, [])
        self.assertIsNotNone(self.doc.getObject(sibling.Name))

    def testUnlink(self):
        """Unlink: the sibling keeps its values but no longer follows (no expressions, no
        SiblingOf); the primary's Length 5 -> 8 then leaves it at 5."""
        self.model(type="Length", length=5)
        sibling = self.sibling()
        PartDesign.unlinkSibling(sibling)
        self.assertIsNone(sibling.SiblingOf)
        self.assertEqual(sibling.ExpressionEngine, [])
        self.assertEqual(PartDesign.siblingsOf(self.pocket), [])
        self.pocket.Length = 8
        self.doc.recompute()
        self.assertEqual(sibling.Length.Value, 5)
        self.assertTrue(sibling.isValid(), sibling.getStatusString())

    def testRefusedTargets(self):
        """A target that isn't a part of the primary's studio (a Body placed elsewhere), the
        primary's own Body, and a part rolled back are refused, with the reason."""
        self.model()
        away = self.doc.addObject("PartDesign::Body", "Away")
        away.Placement.Base = V(0, 0, 50)
        self.doc.recompute()
        with self.assertRaisesRegex(Exception, "studio"):
            PartDesign.makeSiblings(self.pocket, [away])
        with self.assertRaisesRegex(Exception, "own"):
            PartDesign.makeSiblings(self.pocket, [self.lid])
        self.enclosure.Tip = self.baseSk  # the bar above the base
        self.doc.recompute()
        with self.assertRaisesRegex(Exception, "Roll Enclosure to the end first"):
            PartDesign.makeSiblings(self.pocket, [self.enclosure])
        self.assertEqual(PartDesign.siblingsOf(self.pocket), [])


if __name__ == "__main__":
    unittest.main()
