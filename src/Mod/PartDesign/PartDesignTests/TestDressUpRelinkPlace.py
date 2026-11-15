# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH ops#824: a dress-up moved above the feature that made its picks finds them in place
#
# A chamfer of a draft's top edges, moved above the draft, has its Base on the undrafted boss
# (notes/reorder-rollback-design.md 2.2). The boss's top edges sit where the draft's did (the
# draft is neutral at the top), but their sides are the boss's vertical faces, not the draft's
# tilted ones. The record's sides tell another element at the same place (ops#526 D2); here they
# only say that the draft, which tilted them, isn't in the boss. Before the fix the picks broke
# as "ambiguous" while the edges sat where they were, and resolved by geometry (tier 3) once a
# sketch edit moved them: the edit's undo then gave another part than before the edit.
#
# Designed geometry (TestDressUpRelinkHome's model, ops#818): a plate 60 x 40 x 10; a rib whose
# side is flush with the boss's (y = -12); a boss 10 x 10 padded 6 (top at z = 16); a draft of 3
# degrees on the boss's three free sides, neutral at its top; a chamfer of 0.8 on the four top
# edges.
#
# Oracle: on the undrafted boss a chamfer of all four top edges leaves a top face of four sides
# of exactly 10 - 2 x 0.8 = 8.4. The boss's sketch moved by 0.66 in x and back gives the chamfer
# the same picks, the same top and the same volume, and the draft after it the same state.

import unittest

import FreeCAD as App
import PartDesign

from PartDesignTests import TestDressUpRelinkHome as home

SIZE = home.SIZE
TOP = home.TOP

BOSS_X = 8  # the boss sketch's DistanceX of its corner (rect(): 4 coincident, 4 H/V, then x)


class TestDressUpRelinkPlace(unittest.TestCase):
    setUp = home.TestDressUpRelinkHome.setUp
    sketch = home.TestDressUpRelinkHome.sketch
    feature = home.TestDressUpRelinkHome.feature
    build = home.TestDressUpRelinkHome.build

    def moveChamferAboveDraft(self):
        names = [e.Name for e in PartDesign.studioList(self.doc).Entries]
        PartDesign.studioMove(self.chamfer, names.index("Draft"))
        self.doc.recompute()
        names = [e.Name for e in PartDesign.studioList(self.doc).Entries]
        self.assertLess(names.index("Chamfer"), names.index("Draft"))
        self.assertEqual(self.chamfer.Base[0], self.boss)

    def setBossX(self, x):
        self.doc.getObject("BossSk").setDatum(BOSS_X, App.Units.Quantity("%s mm" % x))
        self.doc.recompute()

    def chamferTop(self):
        """The side lengths of the boss's top face in the chamfer's result, shortest first."""
        found = [
            f
            for f in self.chamfer.Shape.Faces
            if abs(f.normalAt(0, 0).z - 1) < 1e-6 and abs(f.CenterOfMass.z - TOP) < 1e-6
            and f.Area < 101
        ]
        self.assertEqual(len(found), 1)
        return sorted(e.Length for e in found[0].Edges)

    def assertFourInPlace(self):
        self.assertTrue(self.chamfer.isValid())
        self.assertEqual(len(self.chamfer.Base[1]), 4)
        self.assertNotIn("?", "".join(self.chamfer.Base[1]))
        sides = self.chamferTop()
        self.assertEqual(len(sides), 4)
        for s in sides:
            self.assertAlmostEqual(s, 10 - 2 * SIZE, places=6)

    def testMovedAboveTheDraftItKeepsTheFourEdges(self):
        """The chamfer moved above the draft holds the boss's four top edges, which sit where
        the draft's were: none breaks as ambiguous."""
        self.build()
        self.moveChamferAboveDraft()
        self.assertFourInPlace()
        self.assertNotIn("mbiguous", self.chamfer.getStatusString())

    def testAnEditAndItsUndoGiveThePartBack(self):
        """ops#824's reproducer: after the move, the boss moved 0.66 in x and back. The chamfer
        has the same picks, top and volume as before the edit, and the draft the same state."""
        self.build()
        self.moveChamferAboveDraft()
        self.assertFourInPlace()
        held = list(self.chamfer.Base[1])
        volume = self.chamfer.Shape.Volume
        draft = (self.draft.isValid(), self.draft.Shape.isNull() or self.draft.Shape.Volume)
        self.setBossX(14.66)
        self.assertFourInPlace()
        self.assertEqual(list(self.chamfer.Base[1]), held)
        self.setBossX(14)
        self.assertFourInPlace()
        self.assertEqual(list(self.chamfer.Base[1]), held)
        self.assertAlmostEqual(self.chamfer.Shape.Volume, volume, places=6)
        self.assertEqual(self.draft.isValid(), draft[0])
        if draft[0]:
            self.assertAlmostEqual(self.draft.Shape.Volume, draft[1], places=6)

    def testMovedBackBelowTheDraftItIsAsBuilt(self):
        """Moved above the draft, edited and undone, then moved back below it: the chamfer is
        on the draft's four top edges again and the part is the one built."""
        self.build()
        before = self.body.Shape.Volume
        self.moveChamferAboveDraft()
        self.setBossX(14.66)
        self.setBossX(14)
        names = [e.Name for e in PartDesign.studioList(self.doc).Entries]
        PartDesign.studioMove(self.chamfer, names.index("Draft") + 1)
        self.doc.recompute()
        self.assertEqual(self.chamfer.Base[0], self.draft)
        self.assertTrue(self.chamfer.isValid())
        self.assertNotIn("?", "".join(self.chamfer.Base[1]))
        self.assertAlmostEqual(self.body.Shape.Volume, before, places=6)
