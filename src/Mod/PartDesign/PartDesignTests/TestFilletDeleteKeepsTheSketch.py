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

"""Deleting a fillet under a sketch's face (FreeCAD-CH ops#640, rank 4; hands-on check B3-1, blind
finding F29). Onshape keeps the sketch on the extrude's top face, which the fillet only trimmed:
nothing goes red, and a later change of the extrude's depth moves the boss with the face. Before,
the sketch's face reference was emptied at the delete and the boss stayed where it was.

The model is designed here: a 20 x 10 x 5 block at the origin; a Fillet of radius 1 on its top
edge along y = 0, which trims the top face to y >= 1; a sketch on that trimmed top face with a
circle of radius 2 at (10, 6), and a boss of 3 from it, merged into the block. The delete is the
Features list's: the Body lets the Fillet go (its view provider's onDelete), then the document
removes it, in one transaction."""

import math
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector
TOL = 1e-6
FILLET_LOSS = 20 * (1 - math.pi / 4)
BOSS = math.pi * 2**2 * 3


def rect(sketch, x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))


def topFace(feature, z):
    """The name of feature's planar face at height z facing up."""
    found = [
        f"Face{i}"
        for i, face in enumerate(feature.Shape.Faces, 1)
        if face.Surface.__class__.__name__ == "Plane"
        and abs(face.CenterOfMass.z - z) < TOL
        and (face.normalAt(*face.Surface.parameter(face.CenterOfMass)) - V(0, 0, 1)).Length < TOL
    ]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} faces at z = {z} facing up, expected one")
    return found[0]


class TestFilletDeleteKeepsTheSketch(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("FilletDeleteKeepsTheSketch")
        self.doc.UndoMode = 1  # a new document records no undo steps without it
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        xy = next(f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane")
        base = self.body.newObject("Sketcher::SketchObject", "BlockSketch")
        base.AttachmentSupport = [(xy, "")]
        base.MapMode = "FlatFace"
        rect(base, 0, 0, 20, 10)
        self.pad = self.body.newObject("PartDesign::Pad", "Block")
        self.pad.Profile = base
        self.pad.Length = 5
        self.doc.recompute()
        edge = next(
            f"Edge{i}"
            for i, e in enumerate(self.pad.Shape.Edges, 1)
            if all(abs(v.Point.z - 5) < TOL and abs(v.Point.y) < TOL for v in e.Vertexes)
        )
        self.fillet = self.body.newObject("PartDesign::Fillet", "Fillet")
        self.fillet.Base = (self.pad, [edge])
        self.fillet.Radius = 1
        self.doc.recompute()
        self.assertTrue(self.fillet.isValid(), self.fillet.getStatusString())
        self.sketch = self.body.newObject("Sketcher::SketchObject", "BossSketch")
        self.sketch.AttachmentSupport = [(self.fillet, topFace(self.fillet, 5))]
        self.sketch.MapMode = "FlatFace"
        self.sketch.addGeometry(Part.Circle(V(10, 6, 0), V(0, 0, 1), 2))
        self.sketch.addConstraint(Sketcher.Constraint("Radius", 0, 2))
        self.sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 10))
        self.sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 6))
        self.boss = self.body.newObject("PartDesign::Pad", "Boss")
        self.boss.Profile = self.sketch
        self.boss.Length = 3
        self.doc.recompute()
        self.assertAllValid()
        self.assertIs(self.body.Tip, self.boss)
        self.assertAlmostEqual(self.body.Shape.Volume, 1000 - FILLET_LOSS + BOSS, places=4)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def assertAllValid(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    def deleteFillet(self):
        """The Features list's delete: Std_Delete runs the view provider's onDelete, which takes
        the Fillet out of its Body, then removes it from the document."""
        self.doc.openTransaction("Delete")
        self.body.removeObject(self.fillet)
        self.doc.removeObject(self.fillet.Name)
        self.doc.commitTransaction()
        self.doc.recompute()

    def testTheSketchStaysOnTheTopFaceAndFollowsIt(self):
        """B3-1: after the delete the sketch is on the Block's top face, nothing is red, and the
        corner is sharp again. Then the Block 5 -> 8 deep: the boss moves up with the face."""
        self.deleteFillet()
        self.assertIsNone(self.doc.getObject("Fillet"))
        self.assertAllValid()
        support = self.sketch.AttachmentSupport
        self.assertEqual(len(support), 1)
        self.assertIs(support[0][0], self.pad)
        self.assertEqual(support[0][1], (topFace(self.pad, 5),))
        self.assertIs(self.boss.BaseFeature, self.pad)
        self.assertAlmostEqual(self.sketch.Placement.Base.z, 5, places=9)
        self.assertAlmostEqual(self.body.Shape.Volume, 1000 + BOSS, places=4)

        self.pad.Length = 8
        self.doc.recompute()
        self.assertAllValid()
        self.assertAlmostEqual(self.sketch.Placement.Base.z, 8, places=9)
        self.assertAlmostEqual(self.boss.Shape.BoundBox.ZMax, 11, places=6)
        self.assertEqual(len(self.body.Shape.Solids), 1)
        self.assertAlmostEqual(self.body.Shape.Volume, 20 * 10 * 8 + BOSS, places=4)

    def testUndoPutsTheFilletAndTheSketchBack(self):
        """The delete and the re-target are one undo step: undone, the Fillet is back and the
        sketch is on its face again."""
        count = self.doc.UndoCount
        self.deleteFillet()
        self.assertEqual(self.doc.UndoCount, count + 1)
        self.doc.undo()
        self.doc.recompute()
        fillet = self.doc.getObject("Fillet")
        self.assertIsNotNone(fillet)
        self.assertIs(self.sketch.AttachmentSupport[0][0], fillet)
        self.assertAllValid()
        self.assertAlmostEqual(self.body.Shape.Volume, 1000 - FILLET_LOSS + BOSS, places=4)


if __name__ == "__main__":
    unittest.main()
