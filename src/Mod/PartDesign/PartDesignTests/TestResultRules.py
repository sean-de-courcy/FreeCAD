# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""What an Extrude's result is when its profile can't be extruded, as Onshape's (FreeCAD-CH ops#640,
ranks 5 and 13).

- An Extrude that holds a curved face as its profile fails, and the part stays as it was (Onshape
  refuses a curved face at pick, hands-on check B3-4; a file or a script can still hold one).
- An Extrude with no profile says so in Onshape's words (hands-on check R3): "Select face or sketch
  region to extrude".

The model is designed here: a 20 x 20 x 10 block (4000 mm^3) with a boss of radius 3 and height 5
on its top (45 pi mm^3)."""

import math
import unittest

import FreeCAD as App

from PartDesignTests.Scenarios import models

V = App.Vector
BLOCK = 4000.0
BOSS = math.pi * 3**2 * 5
TOL = 1e-6
NO_PROFILE = "Select face or sketch region to extrude"


def faceWhere(shape, test):
    """The name of the one face of the shape that passes the test."""
    found = [i + 1 for i, face in enumerate(shape.Faces) if test(face)]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} faces match, expected one")
    return f"Face{found[0]}"


class TestResultRules(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("ResultRules")
        self.body = models.body(self.doc)
        sketch = models.sketch(self.doc, "BlockSketch", models.rectangle(0, 0, 20, 20), self.body)
        self.block = models.pad(self.body, sketch, 10, "Block")
        sketch = models.sketch(self.doc, "BossSketch", [models.circle(10, 10, 3)], self.body, z=10)
        self.boss = models.pad(self.body, sketch, 5, "Boss")
        self.doc.recompute()
        self.assertValid(self.block, self.boss)
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, delta=TOL)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertValid(self, *objects):
        for obj in objects:
            self.assertTrue(obj.isValid(), f"{obj.Name}: {obj.getStatusString()}")

    def assertFailed(self, obj, words):
        self.assertFalse(obj.isValid(), f"{obj.Name} stays valid")
        self.assertIn(words, obj.getStatusString())

    def cylinderFace(self):
        return faceWhere(self.boss.Shape, lambda f: f.Surface.__class__.__name__ == "Cylinder")

    def topFace(self):
        return faceWhere(
            self.boss.Shape,
            lambda f: f.Surface.__class__.__name__ == "Plane"
            and abs(f.CenterOfMass.z - 15) < TOL
            and abs(f.Area - math.pi * 9) < TOL,
        )

    def testPadOfAPlanarFaceStillWorks(self):
        """The planar top of the boss, extruded 2 up: a 2 mm taller boss."""
        pad = self.body.newObject("PartDesign::Pad", "OnTop")
        pad.Profile = (self.boss, [self.topFace()])
        pad.Length = 2
        self.doc.recompute()
        self.assertValid(pad)
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS + math.pi * 9 * 2, delta=TOL)

    def testPadOfACurvedFaceFailsAndKeepsThePart(self):
        """The boss's cylindrical side as the profile: the Pad fails, the part is the boss's."""
        pad = self.body.newObject("PartDesign::Pad", "OnSide")
        pad.Profile = (self.boss, [self.cylinderFace()])
        pad.Length = 2
        self.doc.recompute()
        self.assertFailed(pad, "isn't planar")
        self.assertAlmostEqual(pad.Shape.Volume, BLOCK + BOSS, delta=TOL)
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, delta=TOL)

    def testPocketOfACurvedFaceFailsAndKeepsThePart(self):
        pocket = self.body.newObject("PartDesign::Pocket", "IntoSide")
        pocket.Profile = (self.boss, [self.cylinderFace()])
        pocket.Length = 2
        self.doc.recompute()
        self.assertFailed(pocket, "isn't planar")
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, delta=TOL)

    def testPadWithNoProfileSaysOnshapesWords(self):
        pad = self.body.newObject("PartDesign::Pad", "Empty")
        self.doc.recompute()
        self.assertFailed(pad, NO_PROFILE)
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, delta=TOL)

    def testPocketWithNoProfileSaysOnshapesWords(self):
        pocket = self.body.newObject("PartDesign::Pocket", "Empty")
        self.doc.recompute()
        self.assertFailed(pocket, NO_PROFILE)
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, delta=TOL)


if __name__ == "__main__":
    unittest.main()
