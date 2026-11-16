# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#654 (S1, S2): the generic applier step, with today's classes as owners
#
# A step (PartDesign::FeatureApply) applies its owner's tool to its part. Its names are its
# owner's: the Boolean and the refine carry the owner's object ID, never the step's own
# (format rule 2, notes/stored-tags.md 3), so a step deleted and made again in the same place
# gives identical names, and an edit of the owner keeps them. An Add fuses into a part only the
# tool's solids that touch it (Onshape O8b: each region belongs to the part it stops on).
#
# Designed geometry only: the bake-off's three 10 mm boxes A (x 0..10), B (x 20..30), C (x 40..50)
# and the cut x 5..25, y 2..8 from the top. Expected values come from the geometry.

import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests.Scenarios.harness import Masker
from PartDesignTests.TestStudioList import newStudio, partNames, studioList
from PartDesignTests.TestStudioOwner import CUT, makeOwner, studioSketch


def namesOf(shape, index):
    found = shape.ElementReverseMap.get(f"Face{index}") or []
    return sorted([found] if isinstance(found, str) else found)


def floor(shape, z, x0, x1):
    """The mapped names of the upward planar face at height z whose centre lies in x0..x1."""
    for i, face in enumerate(shape.Faces, 1):
        com = face.CenterOfMass
        if (
            face.Surface.__class__.__name__ == "Plane"
            and abs(face.normalAt(0, 0).z - 1) < 1e-9
            and abs(com.z - z) < 1e-6
            and x0 < com.x < x1
        ):
            return namesOf(shape, i)
    return None


class TestApply(unittest.TestCase):
    def setUp(self):
        self.doc, self.studio = newStudio("TestApply")
        studioList(self.doc)

    def tearDown(self):
        for doc in list(App.listDocuments().values()):
            if doc.Name.startswith("TestApply"):
                App.closeDocument(doc.Name)

    def pocket(self, name="F1", scope=("A", "B"), depth=3):
        sk = studioSketch(self.doc, self.studio, name + "Sk", (CUT,), z=10)
        owner = makeOwner(self.doc, self.studio, "Pocket", name, sk, scope, Length=depth)
        self.doc.recompute()
        return owner

    def floors(self, depth):
        a = self.doc.getObject("A").Shape
        b = self.doc.getObject("B").Shape
        return floor(a, 10 - depth, 5, 10), floor(b, 10 - depth, 20, 25)

    def testStepNamesCarryTheOwnersId(self):
        """Every tag in a part's names after the cut is an object's, the owner's among them,
        never the step's own."""
        f1 = self.pocket()
        masker = Masker(self.doc)
        for p in "AB":
            step = PartDesign.studioStepOf(f1, self.doc.getObject(p))
            self.assertTrue(step.isValid(), step.getStatusString())
            expand = getattr(App, "expandMappedName", None) or (lambda n: n)
            names = [masker.v2(expand(n)) for n in self.doc.getObject(p).Shape.ElementMap]
            text = "\n".join(names)
            self.assertIn("{F1}", text, p)
            self.assertNotIn("{" + step.Name + "}", text, p)
            self.assertNotIn("{-" + step.Name + "}", text, p)

    def testFloorNamesStableUnderAnEditOfTheOwner(self):
        """The floor faces' mapped names stay the same in both parts when the depth changes."""
        f1 = self.pocket(depth=3)
        before = self.floors(3)
        self.assertTrue(all(before), before)
        self.doc.openTransaction("depth")
        f1.Length = 4
        self.doc.commitTransaction()
        self.doc.recompute()
        after = self.floors(4)
        self.assertEqual(after, before)

    def testRegeneratedStepGivesIdenticalNames(self):
        """A step deleted (its part dropped from the scope) and made again (re-added) gives its
        part identical element names."""
        f1 = self.pocket()
        names = partNames(self.doc)
        floors = self.floors(3)
        stepId = PartDesign.studioStepOf(f1, self.doc.getObject("B")).ID
        self.doc.openTransaction("drop B")
        PartDesign.studioSetScopeIds(f1, ["A"])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertIsNone(PartDesign.studioStepOf(f1, self.doc.getObject("B")))
        self.assertAlmostEqual(self.doc.getObject("B").Shape.Volume, 1000, places=4)
        self.doc.openTransaction("add B")
        PartDesign.studioSetScopeIds(f1, ["A", "B"])
        self.doc.commitTransaction()
        self.doc.recompute()
        self.assertNotEqual(PartDesign.studioStepOf(f1, self.doc.getObject("B")).ID, stepId)
        self.assertEqual(partNames(self.doc), names)
        self.assertEqual(self.floors(3), floors)

    def testAddFusesOnlyTheSolidsThatTouchThePart(self):
        """A Pad owner with a region on A's top and one on B's: each part gains its own region's
        boss (6 x 6 x 2) and stays one solid."""
        sk = studioSketch(self.doc, self.studio, "P1Sk", ((2, 2, 8, 8), (22, 2, 28, 8)), z=10)
        p1 = makeOwner(self.doc, self.studio, "Pad", "P1", sk, ("A", "B"), Length=2)
        self.doc.recompute()
        self.assertTrue(p1.isValid(), p1.getStatusString())
        self.assertTrue(p1.Shape.isNull())
        self.assertEqual(len(p1.AddSubShape.Solids), 2)
        for p in "AB":
            shape = self.doc.getObject(p).Shape
            self.assertEqual(len(shape.Solids), 1, p)
            self.assertAlmostEqual(shape.Volume, 1000 + 6 * 6 * 2, places=3, msg=p)
        self.assertAlmostEqual(self.doc.getObject("C").Shape.Volume, 1000, places=4)

    def testPartLevelFuseOfTwoPartsMeasured(self):
        """Measured, not fixed (the Merge rule is P5's): what a Part-level fuse of A and B does to
        their floors' names, which are the same string in both parts. Prints the names."""
        self.pocket()
        a, b = self.floors(3)
        fuse = self.doc.addObject("Part::MultiFuse", "Fuse")
        self.studio.addObject(fuse)
        fuse.Shapes = [self.doc.getObject("A"), self.doc.getObject("B")]
        self.doc.recompute()
        shape = fuse.Shape
        fa, fb = floor(shape, 7, 5, 10), floor(shape, 7, 20, 25)
        self.assertIsNotNone(fa)
        self.assertIsNotNone(fb)
        masker = Masker(self.doc)
        mask = lambda names: [masker.v2(n) for n in names or []]  # noqa: E731
        print("\nops#654 S2 measure (P5): floors of A and B, then in a Part::MultiFuse of A, B")
        print("  A and B floors the same names:", a == b)
        print("  A    :", mask(a))
        print("  B    :", mask(b))
        print("  fused A floor:", mask(fa))
        print("  fused B floor:", mask(fb))
        print("  told apart in the fuse:", fa != fb, "; A's kept:", fa == a, "; B's kept:", fb == b)


if __name__ == "__main__":
    unittest.main()
