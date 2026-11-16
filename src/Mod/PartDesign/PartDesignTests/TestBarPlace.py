# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the FreeCAD project.

"""Where the roll-back bar sits, and where a feature made while rolled back goes (FreeCAD-CH
ops#640 rank 34; blind tests F42, F43).

Onshape greys every row below the bar, the sketches of the rolled-back features too, and puts a
new feature in at the bar, above those sketches. Here a sketch or datum after its Body's bar whose
users are all held waits below the bar with them (Body::waitsBelowBar): the studio's bar, without
a hint, goes above it (studioBarAfter), and Body::addObject inserts a new member before it.

The model is designed: one Body with a 10 x 10 x 5 block (Sk1, Pad1) and a 4 x 4 x 2 boss on its
top (Sk2 at z = 5, Pad2); rolled back after the block, a 2 x 2 x 1 boss (Sk3, Pad3) is added.
Volumes are closed-form: 500, 500 + 32, 500 + 32 + 4."""

import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests.TestStudioSequence import sketch


class TestBarPlace(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("BarPlace")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.sk1 = sketch(self.body, "Sk1", (0, 0, 10, 10))
        self.pad1 = self.pad("Pad1", self.sk1, 5)
        self.sk2 = sketch(self.body, "Sk2", (2, 2, 6, 6), z=5)
        self.pad2 = self.pad("Pad2", self.sk2, 2)
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 500 + 32, places=6)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def pad(self, name, profile, length):
        pad = self.body.newObject("PartDesign::Pad", name)
        pad.Profile = profile
        pad.Length = length
        return pad

    def names(self, objs):
        return [o.Name for o in objs]

    def testTheBarGoesAboveTheWaitingSketch(self):
        """Rolled back after the block, the boss's sketch waits below the bar with the boss: the
        bar follows Pad1, not Sk2 (before: after Sk2, which looked live)."""
        self.body.rollTo(self.pad1)
        self.doc.recompute()
        self.assertTrue(self.body.holds(self.pad2))
        self.assertFalse(self.body.holds(self.sk2))
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "Pad1")
        # A hint is still the user's place: after the sketch, which is then above the bar
        self.assertEqual(PartDesign.studioBarAfter(self.doc, self.sk2).Name, "Sk2")
        # At the end nothing waits
        self.body.rollToEnd()
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "Pad2")

    def testAtTheTopTheFirstSketchWaits(self):
        """Rolled to the top, the block's sketch waits with the block: the bar is at the top."""
        self.body.rollTo(None)
        self.assertIsNone(PartDesign.studioBarAfter(self.doc))

    def testANewFeatureGoesInAtTheBar(self):
        """Made while rolled back after the block, a sketch and its Pad go in right after the bar,
        before the boss's waiting sketch (before: after it); the new sketch, unused yet, is live
        and the bar follows it; the history and the result are right at the end."""
        self.body.rollTo(self.pad1)
        self.doc.recompute()
        sk3 = sketch(self.body, "Sk3", (7, 7, 9, 9), z=5)
        self.assertEqual(self.names(self.body.Group), ["Sk1", "Pad1", "Sk3", "Sk2", "Pad2"])
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "Sk3")
        pad3 = self.pad("Pad3", sk3, 1)
        self.doc.recompute()
        self.assertEqual(self.names(self.body.Group), ["Sk1", "Pad1", "Sk3", "Pad3", "Sk2", "Pad2"])
        self.assertEqual(
            self.names(PartDesign.studioSequence(self.doc)), ["Sk1", "Pad1", "Sk3", "Pad3", "Sk2", "Pad2"]
        )
        self.assertIs(self.body.Tip, pad3)
        self.assertIs(self.pad2.BaseFeature, pad3)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "Pad3")
        self.assertAlmostEqual(pad3.Shape.Volume, 500 + 4, places=6)
        self.body.rollToEnd()
        self.doc.recompute()
        self.assertTrue(self.body.isValid())
        self.assertAlmostEqual(self.body.Shape.Volume, 500 + 32 + 4, places=6)

    def testAtTheTopANewSketchGoesFirst(self):
        """Rolled to the top, a new sketch goes in at the bar, before the block's waiting sketch
        (before: after it, below the bar), and the bar follows it."""
        self.body.rollTo(None)
        self.doc.recompute()
        sketch(self.body, "Sk0", (7, 7, 9, 9))
        self.assertEqual(self.names(self.body.Group), ["Sk0", "Sk1", "Pad1", "Sk2", "Pad2"])
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "Sk0")
        self.body.rollToEnd()
        self.doc.recompute()
        self.assertAlmostEqual(self.body.Shape.Volume, 500 + 32, places=6)

    def testASketchMadeEarlyStaysAboveTheBar(self):
        """Two more Bodies, made in this order: Body2's sketch SkA, Body3's sketch and Pad (a 10 x 10 x 4
        block at x = 20), Body2's Pad on SkA (10 x 10 x 5). Rolled to Body3's Pad, SkA comes before
        it in the history and is live there: the bar stays after Body3's Pad (a live solid isn't
        put below it), and a sketch made for Body2 is listed at the bar, after Body3's Pad."""
        body2 = self.doc.addObject("PartDesign::Body", "Body2")
        body3 = self.doc.addObject("PartDesign::Body", "Body3")
        skA = sketch(body2, "SkA", (0, 0, 10, 10))
        skC = sketch(body3, "SkC", (20, 0, 30, 10))
        padC = body3.newObject("PartDesign::Pad", "PadC")
        padC.Profile = skC
        padC.Length = 4
        padA = body2.newObject("PartDesign::Pad", "PadA")
        padA.Profile = skA
        padA.Length = 5
        self.doc.recompute()
        sequence = self.names(PartDesign.studioSequence(self.doc))
        mine = ["SkA", "SkC", "PadC", "PadA"]
        self.assertEqual([n for n in sequence if n in mine], mine)
        PartDesign.rollStudioTo(self.doc, padC)
        self.doc.recompute()
        self.assertIsNone(body2.Tip)
        self.assertIs(body3.Tip, padC)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "PadC")
        sketch(body2, "SkN", (2, 2, 4, 4), z=5)
        self.assertEqual(self.names(body2.Group), ["SkA", "SkN", "PadA"])
        sequence = self.names(PartDesign.studioSequence(self.doc))
        self.assertEqual(sequence.index("SkN"), sequence.index("PadC") + 1)
        self.assertEqual(PartDesign.studioBarAfter(self.doc).Name, "SkN")
        PartDesign.rollStudioToEnd(self.doc)
        self.doc.recompute()
        self.assertAlmostEqual(body2.Shape.Volume, 500, places=6)
        self.assertAlmostEqual(body3.Shape.Volume, 400, places=6)

    def testNotRolledBackAnInsertGoesLast(self):
        """At the end an insert goes last, as before."""
        sk3 = sketch(self.body, "Sk3", (7, 7, 9, 9), z=5)
        self.assertEqual(self.names(self.body.Group)[-1], "Sk3")
        self.pad("Pad3", sk3, 1)
        self.doc.recompute()
        self.assertEqual(self.names(self.body.Group)[-2:], ["Sk3", "Pad3"])
        self.assertAlmostEqual(self.body.Shape.Volume, 500 + 32 + 4, places=6)


if __name__ == "__main__":
    unittest.main()
