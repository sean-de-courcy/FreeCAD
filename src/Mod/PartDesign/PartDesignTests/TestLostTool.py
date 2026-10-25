# SPDX-License-Identifier: LGPL-2.1-or-later

"""A PartDesign primitive wholly inside its base doesn't get lost silently (FreeCAD-CH ops#472).

The base is the 1000-span wave prism of parttests.BooleanLostToolTest, whose outer shell OCCT's
solid builder takes for a hole: a subtractive box wholly inside then left the body without the
void, and an additive one left a second, overlapping solid, both with the feature up to date. The
feature now fails with the loud check's message. Once the boolean is repaired instead, the right
results also pass: a void (2 shells, no material around the box's centre), or the prism unchanged.
"""

import unittest

import FreeCAD as App
import Part

from parttests.BooleanLostToolTest import wavePrism

V = App.Vector


class TestLostTool(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("PartDesignTestLostTool")
        self.wave = self.doc.addObject("Part::Feature", "Wave")
        self.wave.Shape = wavePrism(1000)
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        self.body.BaseFeature = self.wave

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def addBox(self, kind, position):
        box = self.body.newObject("PartDesign::" + kind, kind)
        box.Length = box.Width = box.Height = 2
        box.Placement = App.Placement(position, App.Rotation())
        box.Refine = False
        self.doc.recompute()
        return box

    def testSubtractiveBoxInside(self):
        box = self.addBox("SubtractiveBox", V(-4, 5, 4))
        if not box.isValid():
            self.assertIn("ops#472", box.getStatusString())
            return
        shape = box.Shape
        self.assertEqual(len(shape.Shells), 2)
        cube = Part.makeBox(1, 1, 1, V(-3.5, 5.5, 4.5))
        self.assertAlmostEqual(shape.common(cube).Volume, 0.0, places=6)

    def testAdditiveBoxInside(self):
        box = self.addBox("AdditiveBox", V(-4, 20, 4))
        if not box.isValid():
            self.assertIn("ops#472", box.getStatusString())
            return
        self.assertEqual(len(box.Shape.Solids), 1)
        self.assertEqual(len(box.Shape.Faces), len(self.wave.Shape.Faces))


if __name__ == "__main__":
    unittest.main()
