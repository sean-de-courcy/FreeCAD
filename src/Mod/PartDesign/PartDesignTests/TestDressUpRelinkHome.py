# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#818: a dress-up's picks come back when its base does
#
# A dress-up's Base follows its base feature (notes/reorder-rollback-design.md 2.2): a reorder,
# an insert or a delete that changes the feature before it moves the picks to the new base,
# where the solver finds them again or breaks them. Each pick keeps what it was on the base it
# left (the re-target record), and is written back as it was when the link returns to that base:
# a move and its undo give the same part.
#
# Designed geometry (the fuzz lane's reduction, ops#818): a plate 60 x 40 x 10; a rib 25 x 3
# padded 4 on its top, whose end runs into the boss's corner and whose side is flush with the
# boss's (y = -12); a boss 10 x 10 padded 6 on the plate's top (top at z = 16); a draft of 3
# degrees on the boss's three free side faces, neutral at its top, so the top stays 10 x 10; a
# chamfer of 0.8 on the boss's four top edges.
#
# Oracle: the boss's top face is 10 x 10 before the chamfer. A chamfered edge sets each of its
# two neighbours on the top back by about the size (0.8; a little more against a drafted side),
# so with all four edges chamfered every side of the top is cut at both ends, about 8.4 long;
# with three, two sides are cut at one end only, about 9.2 long. A move down and back gives the
# volume from before.

import unittest

import FreeCAD as App
import Part
import PartDesign
import Sketcher

V = App.Vector

SIZE = 0.8
TOP = 16.0
# A side of the top face cut at both ends, and at one end only (see above)
BOTH_ENDS = (10 - 2 * SIZE - 0.1, 10 - 2 * SIZE + 0.1)
ONE_END = (10 - SIZE - 0.1, 10 - SIZE + 0.1)


def rect(sk, x, y, w, h):
    """A fully constrained rectangle at (x, y), w by h."""
    p = [V(x, y, 0), V(x + w, y, 0), V(x + w, y + h, 0), V(x, y + h, 0)]
    f = len(sk.Geometry)
    for i in range(4):
        sk.addGeometry(Part.LineSegment(p[i], p[(i + 1) % 4]), False)
    for i in range(4):
        sk.addConstraint(Sketcher.Constraint("Coincident", f + i, 2, f + (i + 1) % 4, 1))
    sk.addConstraint(Sketcher.Constraint("Horizontal", f))
    sk.addConstraint(Sketcher.Constraint("Horizontal", f + 2))
    sk.addConstraint(Sketcher.Constraint("Vertical", f + 1))
    sk.addConstraint(Sketcher.Constraint("Vertical", f + 3))
    sk.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, f, 1, x))
    sk.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, f, 1, y))
    sk.addConstraint(Sketcher.Constraint("DistanceX", f, 1, f, 2, w))
    sk.addConstraint(Sketcher.Constraint("DistanceY", f + 1, 1, f + 1, 2, h))


class TestDressUpRelinkHome(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("DressUpRelinkHome")
        PartDesign.studioList(self.doc, True)
        self.body = self.doc.addObject("PartDesign::Body", "B")
        self.addCleanup(App.closeDocument, self.doc.Name)

    def sketch(self, name, z, *r):
        s = self.body.newObject("Sketcher::SketchObject", name)
        s.AttachmentSupport = [(self.body.Origin.OriginFeatures[3], "")]
        s.MapMode = "FlatFace"
        s.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
        rect(s, *r)
        PartDesign.studioInsert(s, -1)
        return s

    def feature(self, kind, name, **values):
        f = self.body.newObject("PartDesign::" + kind, name)
        for key, value in values.items():
            setattr(f, key, value)
        PartDesign.studioInsert(f, -1)
        self.doc.recompute()
        return f

    def build(self):
        """The plate, the rib, the boss, the draft and the chamfer."""
        self.plate = self.feature("Pad", "Plate", Profile=self.sketch("PlateSk", 0, -30, -20, 60, 40), Length=10)
        self.feature("Pad", "Rib", Profile=self.sketch("RibSk", 10, -10, -12, 25, 3), Length=4)
        self.boss = self.feature("Pad", "Boss", Profile=self.sketch("BossSk", 10, 14, -12, 10, 10), Length=6)
        shape = self.boss.Shape
        sides = [
            "Face%d" % i
            for i, f in enumerate(shape.Faces, 1)
            if abs(f.normalAt(0, 0).z) < 1e-6
            and 13 < f.CenterOfMass.x < 25
            and -13 < f.CenterOfMass.y < -1
            and f.CenterOfMass.z > 10
        ]
        self.assertEqual(len(sides), 3)  # the fourth is one face with the rib's flush side
        top = [
            "Face%d" % i
            for i, f in enumerate(shape.Faces, 1)
            if abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - TOP) < 1e-6
        ]
        self.assertEqual(len(top), 1)
        self.draft = self.feature("Draft", "Draft", Base=(self.boss, sides), NeutralPlane=(self.boss, top), Angle=3)
        last = self.body.Tip
        edges = [
            "Edge%d" % i
            for i, e in enumerate(last.Shape.Edges, 1)
            if all(abs(v.Point.z - TOP) < 1e-6 and v.Point.x > 13 for v in e.Vertexes)
        ]
        self.assertEqual(len(edges), 4)
        self.chamfer = self.feature("Chamfer", "Chamfer", Base=(last, edges), Size=SIZE)
        self.assertTrue(self.chamfer.isValid())

    def topSides(self):
        """The lengths of the sides of the boss's top face in the Body's result, shortest first."""
        found = [
            f
            for f in self.body.Shape.Faces
            if abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - TOP) < 1e-6
        ]
        self.assertEqual(len(found), 1)
        return sorted(e.Length for e in found[0].Edges)

    def chamferedEdges(self):
        """How many of the boss's four top edges are chamfered, read from the top face."""
        sides = self.topSides()
        self.assertEqual(len(sides), 4)
        both = sum(1 for s in sides if BOTH_ENDS[0] < s < BOTH_ENDS[1])
        one = sum(1 for s in sides if ONE_END[0] < s < ONE_END[1])
        whole = sum(1 for s in sides if abs(s - 10) < 1e-6)
        self.assertEqual(both + one + whole, 4)
        # Each chamfered edge cuts two ends
        return (2 * both + one) // 2

    def moveBoss(self, by):
        names = [e.Name for e in PartDesign.studioList(self.doc).Entries]
        PartDesign.studioMove(self.boss, names.index("Boss") + by)
        self.doc.recompute()

    def assertAllFour(self):
        self.assertEqual(self.chamferedEdges(), 4)
        self.assertNotIn("?", "".join(self.chamfer.Base[1]))
        self.assertEqual(self.chamfer.Base[0], self.draft)
        self.assertEqual(len(self.chamfer.Base[1]), 4)

    def testDownAndBackRestoresThePart(self):
        """The boss moved below the draft and straight back: the chamfer has its four edges by
        name again, with no warning, and the part is the one from before."""
        self.build()
        self.assertAllFour()
        before = self.body.Shape.Volume
        self.moveBoss(1)
        self.assertEqual(self.chamfer.Base[0], self.boss)
        self.moveBoss(-1)
        self.assertAllFour()
        self.assertAlmostEqual(self.body.Shape.Volume, before, places=6)
        self.assertTrue(self.chamfer.isValid())
        self.assertEqual(self.chamfer.getStatusString(), "Valid")
        self.assertEqual(App.getReferenceReport(self.chamfer), [])

    def testAPlateEditKeepsTheFourEdgesByName(self):
        """ops#818, its first part (the cause is ops#806's): a thicker plate swallows the foot of
        the rib and the boss, so the fusion cuts their flush sides differently; refine makes
        them one face again, which keeps its whole names, and the draft's top edge on it keeps
        its name. The chamfer holds its four edges by name: no warning, nothing found by
        geometry."""
        self.build()
        self.plate.Length = 11.69
        self.doc.recompute()
        self.assertAllFour()
        self.assertEqual(self.chamfer.getStatusString(), "Valid")
        self.assertEqual(App.getReferenceReport(self.chamfer), [])
        before = self.body.Shape.Volume
        self.moveBoss(1)
        self.moveBoss(-1)
        self.assertAllFour()
        self.assertAlmostEqual(self.body.Shape.Volume, before, places=6)
        self.assertEqual(self.chamfer.getStatusString(), "Valid")

    def testAGuessedPickComesBackAsItWas(self):
        """ops#818: a pick the solver holds provisionally, its original's name gone. The boss
        sketch's side at y = -12 is drawn again in the same place, a new sketch element, and the
        old one deleted: the boss's top edge above it has another name, and the chamfer's pick
        is found again by geometry (tier 3, a warning). While the boss is below the draft that
        pick is found on the boss too, by geometry again, and its name there is no name of the
        draft's shape. Back on the draft it is the reference it was: the same four edges, the
        same warning and the same volume, not three edges. (Moving the rib off the boss's side
        used to make the guess; since ops#845 the draft's top edges keep their names then.)"""
        self.build()
        sk = self.doc.getObject("BossSk")
        sk.addGeometry(Part.LineSegment(V(14, -12, 0), V(24, -12, 0)), False)
        sk.delGeometry(0)  # the others move down one: 0 the side at x = 24, 2 at x = 14, 3 the new
        sk.addConstraint(Sketcher.Constraint("Coincident", 2, 2, 3, 1))
        sk.addConstraint(Sketcher.Constraint("Coincident", 3, 2, 0, 1))
        self.doc.recompute()
        self.assertAllFour()

        def report():
            return [(r["index"], r["sub"], r["guess_kind"]) for r in App.getReferenceReport(self.chamfer)]

        before = self.body.Shape.Volume
        held = list(self.chamfer.Base[1])
        status = self.chamfer.getStatusString()
        was = report()
        self.assertEqual([kind for _, _, kind in was], ["tier3"])  # the setup: one pick is a guess
        self.moveBoss(1)
        self.assertEqual(self.chamfer.Base[0], self.boss)
        self.moveBoss(-1)
        self.assertAllFour()
        self.assertAlmostEqual(self.body.Shape.Volume, before, places=6)
        self.assertEqual(list(self.chamfer.Base[1]), held)
        self.assertEqual(self.chamfer.getStatusString(), status)
        self.assertEqual(report(), was)

    def testTheBaseInBetweenIsNotBlamedOnAReorder(self):
        """While the boss is below the draft the chamfer's picks that broke on the boss say so,
        without the re-target rule's hint: the draft they were on is still before the chamfer.
        The boss is made 3 taller there, so that its top edges are out of tier 3's reach and the
        picks break (where they sit, they are found on the boss: ops#824)."""
        self.build()
        self.moveBoss(1)
        self.assertNotIn("?", "".join(self.chamfer.Base[1]))  # found where they sit (ops#824)
        self.boss.Length = 9
        self.doc.recompute()
        self.assertIn("?", "".join(self.chamfer.Base[1]))
        self.assertNotIn("which a reorder put after", self.chamfer.getStatusString())

    def testAPickMadeInBetweenStays(self):
        """A pick the user makes on the base in between ends the record: back on the draft the
        reference is carried by the name it has now, not put back as it was."""
        self.build()
        self.moveBoss(1)
        shape = self.boss.Shape
        front = [
            "Edge%d" % i
            for i, e in enumerate(shape.Edges, 1)
            if all(abs(v.Point.z - TOP) < 1e-6 and abs(v.Point.y + 2) < 1e-6 for v in e.Vertexes)
        ]
        self.assertEqual(len(front), 1)  # the boss's top edge at y = -2
        self.chamfer.Base = (self.boss, front)
        self.doc.recompute()
        self.assertTrue(self.chamfer.isValid())
        self.moveBoss(-1)
        self.assertEqual(self.chamfer.Base[0], self.draft)
        self.assertEqual(len(self.chamfer.Base[1]), 1)
        # One edge chamfered, if the solver finds it on the draft; never the four from before
        self.assertLessEqual(self.chamferedEdges(), 1)
        # A pick the draft doesn't have by name is solved from the boss's name for it (the pad's
        # edge), not from the name an earlier pick had on the draft
        for row in App.getReferenceReport(self.chamfer):
            self.assertIn(";XTR;", row["old"])
            self.assertNotIn(";DFT;", row["old"])
