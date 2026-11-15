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

"""A boss sketched on the end cap of a base extrude, then the base flipped (FreeCAD-CH ops#640,
rank 7; hands-on checks B3-2 and B3-2b). Onshape keeps the sketch on the same face, the end cap,
now on the other side: its normal flips, its in-plane X is kept and its Y is reversed. Geometry
placed by the sketch's own coordinates follows that frame, so it mirrors in Y; geometry
dimensioned to the face's edges keeps its place on the part. Nothing goes red, and the bosses
point away from the part.

The model is designed here: a 40 x 20 block centred on the origin, 15 deep from the XY plane (z = 0
to 15; flipped, z = -15 to 0). On its end cap, two bosses of radius 2 and height 5: one placed by
sketch coordinates at (12, 4), one 10 from the face's -X edge and 5 from its +Y edge, at (-10, 5)."""

import math
import unittest

import FreeCAD as App
import Part
import Sketcher

V = App.Vector
TOL = 1e-6
BLOCK = 40 * 20 * 15
BOSS = math.pi * 2**2 * 5


def rect(sketch, x0, y0, x1, y1):
    points = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(points[i], points[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))


def planarFace(feature, z, nz):
    """The name of feature's planar face at height z whose outward normal is (0, 0, nz)."""
    found = [
        f"Face{i}"
        for i, face in enumerate(feature.Shape.Faces, 1)
        if face.Surface.__class__.__name__ == "Plane"
        and abs(face.CenterOfMass.z - z) < TOL
        and (face.normalAt(*face.Surface.parameter(face.CenterOfMass)) - V(0, 0, nz)).Length < TOL
    ]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} faces at z = {z} facing {nz}, expected one")
    return found[0]


def lineEdge(feature, test):
    """The name of feature's straight edge whose two ends pass test."""
    found = [
        f"Edge{i}"
        for i, edge in enumerate(feature.Shape.Edges, 1)
        if edge.Curve.__class__.__name__ in ("Line", "LineSegment")
        and all(test(v.Point) for v in edge.Vertexes)
    ]
    if len(found) != 1:
        raise AssertionError(f"{len(found)} edges match, expected one")
    return found[0]


class TestFlipKeepsTheSketch(unittest.TestCase):
    def setUp(self):
        self.doc = App.newDocument("FlipKeepsTheSketch")
        self.body = self.doc.addObject("PartDesign::Body", "Body")
        xy = next(f for f in self.body.Origin.OriginFeatures if f.Role == "XY_Plane")
        self.base = self.body.newObject("Sketcher::SketchObject", "BaseSketch")
        self.base.AttachmentSupport = [(xy, "")]
        self.base.MapMode = "FlatFace"
        rect(self.base, -20, -10, 20, 10)
        self.pad = self.body.newObject("PartDesign::Pad", "Base")
        self.pad.Profile = self.base
        self.pad.Length = 15
        self.doc.recompute()
        self.assertTrue(self.pad.isValid(), self.pad.getStatusString())
        self.cap = planarFace(self.pad, 15, 1)

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def bossSketch(self, name):
        sketch = self.body.newObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = [(self.pad, self.cap)]
        sketch.MapMode = "FlatFace"
        return sketch

    def boss(self, name, sketch):
        boss = self.body.newObject("PartDesign::Pad", name)
        boss.Profile = sketch
        boss.Length = 5
        return boss

    def originBoss(self):
        """The circle at (12, 4), dimensioned to the sketch origin only (B3-2b)."""
        sketch = self.bossSketch("OriginSketch")
        sketch.addGeometry(Part.Circle(V(12, 4, 0), V(0, 0, 1), 2))
        sketch.addConstraint(Sketcher.Constraint("Radius", 0, 2))
        sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, 0, 3, 12))
        sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, 0, 3, 4))
        return sketch, self.boss("OriginBoss", sketch)

    def edgeBoss(self):
        """The circle 10 from the end cap's -X edge and 5 from its +Y edge (B3-2): the edges are
        projected, and the centre's distances to them are the dimensions."""
        minusX = lineEdge(self.pad, lambda p: abs(p.x + 20) < TOL and abs(p.z - 15) < TOL)
        plusY = lineEdge(self.pad, lambda p: abs(p.y - 10) < TOL and abs(p.z - 15) < TOL)
        sketch = self.bossSketch("EdgeSketch")
        sketch.addExternal(self.pad.Name, minusX)
        sketch.addExternal(self.pad.Name, plusY)
        sketch.addGeometry(Part.Circle(V(-10, 5, 0), V(0, 0, 1), 2))
        sketch.addConstraint(Sketcher.Constraint("Radius", 0, 2))
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 3, -3, 10))
        sketch.addConstraint(Sketcher.Constraint("Distance", 0, 3, -4, 5))
        return sketch, self.boss("EdgeBoss", sketch)

    def centre(self, sketch):
        """The circle's centre in the world."""
        return sketch.getGlobalPlacement().multVec(sketch.Geometry[0].Center)

    def assertPoint(self, actual, expected):
        self.assertLess((actual - expected).Length, TOL, f"{actual} is not {expected}")

    def assertAllValid(self):
        self.assertEqual(
            [(o.Name, o.getStatusString()) for o in self.doc.Objects if not o.isValid()], []
        )

    def flip(self, reversed):
        self.pad.Reversed = reversed
        self.doc.recompute()
        self.assertAllValid()

    def assertOnTheEndCap(self, sketch, z, nz):
        """sketch is on the base's end cap: at height z, facing (0, 0, nz)."""
        support = sketch.AttachmentSupport
        self.assertEqual(len(support), 1)
        self.assertIs(support[0][0], self.pad)
        self.assertEqual(support[0][1], (planarFace(self.pad, z, nz),))

    def testTheSketchRidesTheEndCapAndItsFrameKeepsX(self):
        """B3-2 and B3-2b: flipped, the sketch is on the end cap at z = -15, facing -Z, with X kept
        and Y reversed; the circle placed by sketch coordinates mirrors in Y, (12, 4) to (12, -4);
        the boss points away from the part, z = -20 to -15. Flipped back, all is as before."""
        sketch, boss = self.originBoss()
        self.doc.recompute()
        self.assertAllValid()
        self.assertPoint(self.centre(sketch), V(12, 4, 15))
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, places=4)

        self.flip(True)
        self.assertOnTheEndCap(sketch, -15, -1)
        rotation = sketch.Placement.Rotation
        self.assertPoint(rotation.multVec(V(1, 0, 0)), V(1, 0, 0))
        self.assertPoint(rotation.multVec(V(0, 1, 0)), V(0, -1, 0))
        self.assertPoint(rotation.multVec(V(0, 0, 1)), V(0, 0, -1))
        self.assertPoint(sketch.Placement.Base, V(0, 0, -15))
        self.assertPoint(self.centre(sketch), V(12, -4, -15))
        self.assertAlmostEqual(boss.Shape.BoundBox.ZMin, -20, places=6)
        self.assertEqual(len(self.body.Shape.Solids), 1)
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + BOSS, places=4)

        self.flip(False)
        self.assertOnTheEndCap(sketch, 15, 1)
        self.assertPoint(self.centre(sketch), V(12, 4, 15))
        self.assertAlmostEqual(boss.Shape.BoundBox.ZMax, 20, places=6)

    def testGeometryDimensionedToTheEdgesKeepsItsPlace(self):
        """B3-2: the circle dimensioned to the end cap's -X and +Y edges stays 10 from the -X edge
        and 5 from the +Y edge after the flip, at (-10, 5) in the world, on the part; the boss
        placed by sketch coordinates mirrors beside it. Before: the side the +Y distance recorded
        was kept in the reversed frame, and the circle went to y = 15, off the part."""
        edgeSketch, edgeBoss = self.edgeBoss()
        originSketch, _ = self.originBoss()
        self.doc.recompute()
        self.assertAllValid()
        self.assertPoint(self.centre(edgeSketch), V(-10, 5, 15))
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + 2 * BOSS, places=4)

        self.flip(True)
        self.assertOnTheEndCap(edgeSketch, -15, -1)
        self.assertPoint(self.centre(edgeSketch), V(-10, 5, -15))
        self.assertPoint(self.centre(originSketch), V(12, -4, -15))
        self.assertAlmostEqual(edgeBoss.Shape.BoundBox.ZMin, -20, places=6)
        self.assertEqual(len(self.body.Shape.Solids), 1)
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + 2 * BOSS, places=4)

        self.flip(False)
        self.assertPoint(self.centre(edgeSketch), V(-10, 5, 15))
        self.assertPoint(self.centre(originSketch), V(12, 4, 15))
        self.assertAlmostEqual(self.body.Shape.Volume, BLOCK + 2 * BOSS, places=4)


if __name__ == "__main__":
    unittest.main()
