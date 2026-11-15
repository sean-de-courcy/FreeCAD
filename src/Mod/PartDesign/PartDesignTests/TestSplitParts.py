# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH (ops#640, the Onshape experiment, rank 3b)

"""A part cut in two (ops#640 rank 3b, hands-on A-2' a): Onshape's Remove that cuts a part into two
pieces makes two parts. FreeCAD-CH keeps one Body (AllowCompound stays on, no Body is made during
the recompute) whose shape holds the two solids; the Parts list shows a row per solid
(FeaturesView's partPieces, TestBooleanDialogGui.TestPartsListGui). These App tests pin the model
side: the Body's solids, their volumes, and that no Body was made.

Designed geometry: a bar 30 x 10 x 10 at the origin (3000); a cutter 10 x 20 x 20 at
(10, -5, -5), through the bar's middle third, leaves two 10 mm cubes (1000 each)."""

import unittest

import FreeCAD as App
import PartDesign

V = App.Vector


class TestSplitParts(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("TestSplitParts")
        self.bar = self.doc.addObject("PartDesign::Body", "Bar")
        self.barBox = self.bar.newObject("PartDesign::AdditiveBox", "BarBox")
        self.barBox.Length = 30
        self.barBox.Width = self.barBox.Height = 10
        self.doc.recompute()
        self.assertAlmostEqual(self.bar.Shape.Volume, 3000, places=6)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def bodies(self):
        return sorted(o.Name for o in self.doc.Objects if o.TypeId == "PartDesign::Body")

    def assertTwoCubes(self, body):
        self.assertTrue(body.AllowCompound)
        solids = body.Shape.Solids
        self.assertEqual(len(solids), 2)
        for solid in solids:
            self.assertAlmostEqual(solid.Volume, 1000, places=6)
        self.assertEqual(
            sorted(round(s.BoundBox.XMin, 6) for s in solids), [0.0, 20.0], "the outer thirds"
        )

    def testARemoveThatCutsThePartInTwo(self):
        """A subtractive box through the middle third: the Bar's shape is the two outer cubes,
        valid, and no Body was made."""
        before = self.bodies()
        cutter = self.bar.newObject("PartDesign::SubtractiveBox", "Cutter")
        cutter.Length = 10
        cutter.Width = cutter.Height = 20
        cutter.Placement.Base = V(10, -5, -5)
        self.doc.recompute()
        self.assertTrue(cutter.isValid(), cutter.getStatusString())
        self.assertTwoCubes(self.bar)
        self.assertEqual(self.bodies(), before)

    def testABooleanSubtractThatCutsThePartInTwo(self):
        """The same cut by a Boolean Subtract of a cutter part: two cubes in the Bar, the
        cutter consumed (Keep tools off), no Body made."""
        cutter = self.doc.addObject("PartDesign::Body", "Cutter")
        box = cutter.newObject("PartDesign::AdditiveBox", "CutterBox")
        box.Length = 10
        box.Width = box.Height = 20
        box.Placement.Base = V(10, -5, -5)
        self.doc.recompute()
        before = self.bodies()
        cut = self.bar.newObject("PartDesign::Boolean", "Subtract")
        cut.setObjects([cutter])
        cut.Type = "Cut"
        cut.KeepTools = False
        self.doc.recompute()
        self.assertTrue(cut.isValid(), cut.getStatusString())
        self.assertTwoCubes(self.bar)
        self.assertEqual(self.bodies(), before)
        self.assertIs(PartDesign.consumerOf(cutter), cut)

    def testFillingTheGapJoinsThePiecesAgain(self):
        """After the split, an additive box back in the gap: one solid, 3000 (the two pieces
        were one part all along, so nothing needs re-merging)."""
        cutter = self.bar.newObject("PartDesign::SubtractiveBox", "Cutter")
        cutter.Length = 10
        cutter.Width = cutter.Height = 20
        cutter.Placement.Base = V(10, -5, -5)
        self.doc.recompute()
        self.assertTwoCubes(self.bar)
        filler = self.bar.newObject("PartDesign::AdditiveBox", "Filler")
        filler.Length = filler.Width = filler.Height = 10
        filler.Placement.Base = V(10, 0, 0)
        self.doc.recompute()
        self.assertTrue(filler.isValid(), filler.getStatusString())
        self.assertEqual(len(self.bar.Shape.Solids), 1)
        self.assertAlmostEqual(self.bar.Shape.Volume, 3000, places=6)


if __name__ == "__main__":
    unittest.main()
