# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#683, design group C slice C5): a mate after edits of its part, as Onshape's
# (notes/assemblies-design.md section 5; notes/onshape-facts.md GB11, B3, GB33c).
#
# - A mate between two face centres follows a changed height of the fixed part (GB11: the mated
#   part follows, the fixed one keeps its place), unflipped and flipped (the flip is kept).
# - A recompute of the document after the studio edit is enough: no solve by hand, no visit to
#   the assembly (Onshape: the assembly is up to date when its tab is shown).
# - A corner connector follows a changed length (B3: A's length 40 -> 50, B's top-face centre
#   stays on A's top corner, which moves from x 40 to x 50).
# - The mated face removed (a boss suppressed): the mate is in error with a message naming the
#   missing pick, the solve leaves it out and nothing moves; the boss back, the mate heals by
#   itself and holds again (B3: "Mate cannot resolve mate connectors", the instance stays, the
#   mate OK again when unsuppressed).
# - Kept difference (design section 5): the mated face split in two by a slot. Onshape keeps the
#   mate and moves the part to one piece's centre without a word (GB33c); FreeCAD-CH stops with
#   the mate in error and moves nothing.
#
# Designed geometry: studios are PartDesign Bodies at the document's root, made of AdditiveBoxes;
# the assembly holds App::Link instances of them, as Insert makes them. A = 40 x 20 x 10 at the
# origin (grounded), B = 20 x 10 x 5 placed at x 60..80 (GB31's and GB33c's boxes). A box's
# top-face centre is (L/2, W/2, H); expected positions follow from it.

import os
import tempfile
import unittest

import FreeCAD as App

import JointObject

V = App.Vector
TOL = 1e-6


class MateEditsBase(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument(self.__class__.__name__)
        self.files = []

    def tearDown(self):
        if self.doc.Name in App.listDocuments():
            App.closeDocument(self.doc.Name)
        for path in self.files:
            if os.path.exists(path):
                os.remove(path)

    def studio(self, name, length, width, height):
        """A Part Studio's part: a Body holding one AdditiveBox."""
        body = self.doc.addObject("PartDesign::Body", name)
        box = body.newObject("PartDesign::AdditiveBox", name + "Box")
        box.Length, box.Width, box.Height = length, width, height
        return body, box

    def assembly(self):
        asm = self.doc.addObject("Assembly::AssemblyObject", "Assembly")
        asm.Type = "Assembly"
        self.joints = asm.newObject("Assembly::JointGroup", "Joints")
        return asm

    def instance(self, asm, name, studio, at=V(0, 0, 0)):
        link = asm.newObject("App::Link", name)
        link.LinkedObject = studio
        link.Placement = App.Placement(at, App.Rotation())
        return link

    def ground(self, obj):
        joint = self.joints.newObject("App::FeaturePython", "Ground" + obj.Name)
        JointObject.GroundedJoint(joint, obj)
        return joint

    def fastened(self, moving, moving_sub, staying, staying_sub, name="Fastened"):
        """A Fixed joint (Onshape's Fastened mate) picked as the dialog does: moving first."""
        joint = self.joints.newObject("App::FeaturePython", name)
        JointObject.Joint(joint, 0)
        joint.Proxy.setJointConnectors(
            joint, [[moving, list(moving_sub)], [staying, list(staying_sub)]]
        )
        return joint

    @staticmethod
    def element(shape, kind, test):
        """The name of the one face or vertex of @shape (the studio's, in its own frame) that
        passes @test."""
        items = shape.Faces if kind == "Face" else shape.Vertexes
        found = [f"{kind}{i}" for i, item in enumerate(items, 1) if test(item)]
        assert len(found) == 1, f"{kind}: {found}"
        return found[0]

    @staticmethod
    def topFace(shape, z):
        return MateEditsBase.element(
            shape,
            "Face",
            lambda f: f.Surface.TypeId == "Part::GeomPlane"
            and abs(f.CenterOfMass.z - z) < 1e-6
            and f.normalAt(0, 0).z > 0.5,
        )

    def assertNear(self, got, expected, what, tol=TOL):
        self.assertLess((got - expected).Length, tol, f"{what}: {got}, expected {expected}")

    def saveAndReopen(self):
        path = os.path.join(tempfile.gettempdir(), f"{self.doc.Name}_{os.getpid()}.FCStd")
        self.files.append(path)
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        return self.doc


class TestMateAfterEdits(MateEditsBase):
    """C5: a Fastened mate after its part changes (GB11, B3)."""

    def boxes(self):
        """A (40 x 20 x 10, grounded) and B (20 x 10 x 5 at x 60), B's top-face centre fastened
        onto A's top-face centre."""
        self.bodyA, self.boxA = self.studio("PartA", 40, 20, 10)
        self.bodyB, self.boxB = self.studio("PartB", 20, 10, 5)
        self.asm = self.assembly()
        self.a = self.instance(self.asm, "A", self.bodyA)
        self.b = self.instance(self.asm, "B", self.bodyB, V(60, 0, 0))
        self.doc.recompute()
        self.ground(self.a)
        self.topA = self.topFace(self.bodyA.Shape, 10)
        self.topB = self.topFace(self.bodyB.Shape, 5)
        self.joint = self.fastened(self.b, (self.topB, self.topB), self.a, (self.topA, self.topA))
        self.doc.recompute()

    def bTop(self):
        """B's top-face centre and that face's normal, in the assembly."""
        plc = self.b.Placement
        return plc.multVec(V(10, 5, 5)), plc.Rotation.multVec(V(0, 0, 1))

    def testMateFollowsAChangedHeight(self):
        """GB11: A's height 10 -> 15; B's top-face centre stays on A's top-face centre, which
        rises by 5; A keeps its place; the mate stays valid. Unflipped (GC-B1): B's top faces
        up as A's does, the two boxes overlapping."""
        self.boxes()
        self.assertTrue(self.joint.isValid(), self.joint.getStatusString())
        centre, normal = self.bTop()
        self.assertNear(centre, V(20, 10, 10), "B's top-face centre on A's")
        self.assertNear(normal, V(0, 0, 1), "an unflipped mate: B's top faces up")
        before = self.b.Placement

        self.boxA.Height = 15
        self.doc.recompute()
        self.assertEqual(self.asm.solve(), 0)
        self.assertTrue(self.joint.isValid(), self.joint.getStatusString())
        self.assertEqual(self.asm.ErrorJoints, [])
        centre, normal = self.bTop()
        self.assertNear(centre, V(20, 10, 15), "B follows A's top face")
        self.assertNear(normal, V(0, 0, 1), "B still unflipped")
        self.assertNear(self.b.Placement.Base, before.Base + V(0, 0, 5), "B moved by the 5 mm")
        self.assertTrue(self.a.Placement.isSame(App.Placement(), TOL), "the grounded A moved")

    def testFlippedMateStaysFlippedAfterAChangedHeight(self):
        """GB11's mate is flipped (Flip primary axis; 67 of the team's 74 Fastened mates are,
        GC-A2). After A's height 10 -> 15 and a solve, B is still flipped, its top on A's top."""
        self.boxes()
        self.joint.Proxy.flipOnePart(self.joint)
        self.assertEqual(self.asm.solve(), 0)
        centre, normal = self.bTop()
        self.assertNear(centre, V(20, 10, 10), "flipped: B's top-face centre on A's")
        self.assertNear(normal, V(0, 0, -1), "flipped: B's top faces down onto A's")

        self.boxA.Height = 15
        self.doc.recompute()
        self.assertEqual(self.asm.solve(), 0)
        centre, normal = self.bTop()
        self.assertNear(centre, V(20, 10, 15), "flipped B follows A's top face")
        self.assertNear(normal, V(0, 0, -1), "the flip is kept through the edit")

    def testRecomputeIsEnough(self):
        """The studio edited and the document recomputed, with no solve by hand: B follows."""
        self.boxes()
        self.boxA.Height = 15
        self.doc.recompute()
        centre, _ = self.bTop()
        self.assertNear(centre, V(20, 10, 15), "a document recompute did not move B onto A's top")

    def testMateFollowsAChangedHeightAfterReopen(self):
        """The same edit made after a save and a reopen: the mate's picks resolve again."""
        self.boxes()
        doc = self.saveAndReopen()
        boxA = doc.getObject("PartABox")
        boxA.Height = 15
        doc.recompute()
        asm, b = doc.getObject("Assembly"), doc.getObject("B")
        self.assertEqual(asm.solve(), 0)
        self.assertTrue(doc.getObject("Fastened").isValid())
        self.assertNear(b.Placement.multVec(V(10, 5, 5)), V(20, 10, 15), "B after the reopen")

    def testCornerConnectorFollowsAChangedLength(self):
        """B3: B's top-face centre fastened onto A's top corner at (40, 0, 10); A's length
        40 -> 50: the corner moves to (50, 0, 10) and B with it, by (10, 0, 0) and unturned."""
        self.bodyA, self.boxA = self.studio("PartA", 40, 20, 10)
        self.bodyB, self.boxB = self.studio("PartB", 20, 10, 5)
        self.asm = self.assembly()
        self.a = self.instance(self.asm, "A", self.bodyA)
        self.b = self.instance(self.asm, "B", self.bodyB, V(60, 0, 0))
        self.doc.recompute()
        self.ground(self.a)
        topA = self.topFace(self.bodyA.Shape, 10)
        topB = self.topFace(self.bodyB.Shape, 5)
        corner = self.element(
            self.bodyA.Shape, "Vertex", lambda v: (v.Point - V(40, 0, 10)).Length < 1e-6
        )
        joint = self.fastened(self.b, (topB, topB), self.a, (topA, corner))
        self.doc.recompute()
        centre, normal = self.bTop()
        self.assertNear(centre, V(40, 0, 10), "B's top-face centre on A's corner")
        self.assertNear(normal, V(0, 0, 1), "unflipped")
        before = self.b.Placement

        self.boxA.Length = 50
        self.doc.recompute()
        self.assertEqual(self.asm.solve(), 0)
        self.assertTrue(joint.isValid(), joint.getStatusString())
        centre, _ = self.bTop()
        self.assertNear(centre, V(50, 0, 10), "B follows the corner")
        self.assertNear(self.b.Placement.Base, before.Base + V(10, 0, 0), "B moved by 10 along x")
        self.assertTrue(
            self.b.Placement.Rotation.isSame(before.Rotation, 1e-9), "B turned with the edit"
        )


class TestMateFaceGone(MateEditsBase):
    """C5: the mated face gone, then back (B3's boss), and a split face (GB33c, kept)."""

    def bossModel(self):
        """A = 40 x 20 x 10 with a boss 10 x 10 x 5 on its top at x 5..15, y 5..15 (the boss's
        top-face centre (10, 10, 15)); C = 20 x 10 x 5 at x 60, its top-face centre fastened
        onto the boss's."""
        self.bodyA, self.boxA = self.studio("PartA", 40, 20, 10)
        self.boss = self.bodyA.newObject("PartDesign::AdditiveBox", "Boss")
        self.boss.Length, self.boss.Width, self.boss.Height = 10, 10, 5
        self.boss.Placement = App.Placement(V(5, 5, 10), App.Rotation())
        self.bodyC, _ = self.studio("PartC", 20, 10, 5)
        self.asm = self.assembly()
        self.a = self.instance(self.asm, "A", self.bodyA)
        self.c = self.instance(self.asm, "C", self.bodyC, V(60, 0, 0))
        self.doc.recompute()
        self.assertAlmostEqual(self.bodyA.Shape.Volume, 8000 + 500, 6)
        self.ground(self.a)
        bossTop = self.topFace(self.bodyA.Shape, 15)
        topC = self.topFace(self.bodyC.Shape, 5)
        self.joint = self.fastened(self.c, (topC, topC), self.a, (bossTop, bossTop))
        self.doc.recompute()

    def cTop(self):
        return self.c.Placement.multVec(V(10, 5, 5))

    def testMateRedWhileItsFaceIsGoneAndHealsWhenItComesBack(self):
        self.bossModel()
        self.assertTrue(self.joint.isValid(), self.joint.getStatusString())
        self.assertNear(self.cTop(), V(10, 10, 15), "C's top-face centre on the boss's")
        placed = self.c.Placement

        # The boss suppressed: its top face is gone
        self.boss.Suppressed = True
        self.doc.recompute()
        self.assertAlmostEqual(self.bodyA.Shape.Volume, 8000, 6)
        self.assertFalse(self.joint.isValid(), "a mate whose face is gone is not in error")
        self.assertIn("Missing", self.joint.getStatusString())
        self.assertEqual(self.asm.ErrorJoints, [self.joint.Name])
        self.asm.solve()
        self.assertTrue(self.c.Placement.isSame(placed, 1e-9), "C moved while its mate was red")

        # Moved by hand while red (Onshape: C can be dragged; the mate is not solved)
        self.c.Placement = App.Placement(V(100, 0, 0), App.Rotation())
        self.asm.solve()
        self.assertNear(self.c.Placement.Base, V(100, 0, 0), "the red mate pulled C back")

        # The boss back: the mate heals by itself and holds C on the boss again
        self.boss.Suppressed = False
        self.doc.recompute()
        self.assertAlmostEqual(self.bodyA.Shape.Volume, 8500, 6)
        self.assertTrue(self.joint.isValid(), "the mate did not heal: " + self.joint.getStatusString())
        self.assertEqual(self.asm.ErrorJoints, [])
        self.assertEqual(self.asm.solve(), 0)
        self.assertNear(self.cTop(), V(10, 10, 15), "C back on the boss's top-face centre")

    def testSplitFaceStopsTheMate(self):
        """Kept difference (GB33c): A's top face split by a slot x 18..22, 3 deep, across it.
        Onshape moves B to one piece's centre without a word; FreeCAD-CH puts the mate in error
        and moves nothing (one re-pick)."""
        self.bodyA, self.boxA = self.studio("PartA", 40, 20, 10)
        self.bodyB, _ = self.studio("PartB", 20, 10, 5)
        self.asm = self.assembly()
        self.a = self.instance(self.asm, "A", self.bodyA)
        self.b = self.instance(self.asm, "B", self.bodyB, V(60, 0, 0))
        self.doc.recompute()
        self.ground(self.a)
        topA = self.topFace(self.bodyA.Shape, 10)
        topB = self.topFace(self.bodyB.Shape, 5)
        joint = self.fastened(self.b, (topB, topB), self.a, (topA, topA))
        self.doc.recompute()
        self.assertNear(self.b.Placement.multVec(V(10, 5, 5)), V(20, 10, 10), "B on A's top")
        placed = self.b.Placement

        slot = self.bodyA.newObject("PartDesign::SubtractiveBox", "Slot")
        slot.Length, slot.Width, slot.Height = 4, 20, 3
        slot.Placement = App.Placement(V(18, 0, 7), App.Rotation())
        self.doc.recompute()
        self.assertAlmostEqual(self.bodyA.Shape.Volume, 8000 - 240, 6)
        tops = [
            f
            for f in self.bodyA.Shape.Faces
            if abs(f.CenterOfMass.z - 10) < 1e-6 and f.normalAt(0, 0).z > 0.5
        ]
        self.assertEqual(len(tops), 2, "the slot splits A's top face in two")

        self.asm.solve()
        self.assertFalse(joint.isValid(), "a mate on a split face is not in error")
        self.assertEqual(self.asm.ErrorJoints, [joint.Name])
        self.assertTrue(self.b.Placement.isSame(placed, 1e-9), "B moved on a split face")


if __name__ == "__main__":
    unittest.main()
