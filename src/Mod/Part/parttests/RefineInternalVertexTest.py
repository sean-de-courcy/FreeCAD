# SPDX-License-Identifier: LGPL-2.1-or-later

"""A refine merges coplanar faces when a face of the shape holds an INTERNAL vertex (FreeCAD-CH
ops#640, rehearsal 5 rb43).

Designed model: two 10 mm boxes side by side, A at the origin and B at x = 10, fused unrefined into
one 20 x 10 x 10 block whose top is two coplanar squares. A vertex at (20, 5, 5) is imprinted on the
far end face with generalFuse, so that face holds it as an INTERNAL vertex, on none of its edges
(as a revolved thread cap crossing a wall leaves one). The refine's face uniter re-sews the shell
after each merge, and the sewing handed that vertex back beside the shell, in a compound: the uniter
then failed. A solid's refine raised "Removing splitter failed"; the same solid in a compound (as
most features' shapes are) kept its faces split, with no error, and every later refine of the body
did too.

Expected, geometrically: the block's 6 faces, the top one face of 20 x 10 = 200 mm2 at z = 10, the
volume 2000 mm3, valid; as a solid and in a compound alike."""

import unittest

import FreeCAD as App
import Part

V = App.Vector


def topFaces(shape):
    return [
        f
        for f in shape.Faces
        if f.Surface.__class__.__name__ == "Plane"
        and abs(f.BoundBox.ZMin - 10) < 1e-9
        and abs(f.BoundBox.ZMax - 10) < 1e-9
    ]


class RefineInternalVertexTest(unittest.TestCase):
    def setUp(self):
        block = Part.makeBox(10, 10, 10).fuse(Part.makeBox(10, 10, 10, V(10, 0, 0)))
        pieces = block.generalFuse([Part.Vertex(V(20, 5, 5))])[0]
        self.assertEqual(len(pieces.Solids), 1)
        self.solid = pieces.Solids[0]
        # the designed state: split top, and the end face holding the vertex off its edges
        self.assertEqual(len(topFaces(self.solid)), 2)
        end = [
            f
            for f in self.solid.Faces
            if abs(f.BoundBox.XMin - 20) < 1e-9 and abs(f.BoundBox.XMax - 20) < 1e-9
        ]
        self.assertEqual(len(end), 1)
        onEdges = {v.hashCode() for e in end[0].Edges for v in e.Vertexes}
        internal = [v for v in end[0].Vertexes if v.hashCode() not in onEdges]
        self.assertEqual(len(internal), 1)
        self.assertLess(internal[0].Point.distanceToPoint(V(20, 5, 5)), 1e-9)

    def check(self, refined):
        self.assertTrue(refined.isValid())
        self.assertEqual(len(refined.Faces), 6)
        top = topFaces(refined)
        self.assertEqual(len(top), 1, [f.Area for f in top])
        self.assertAlmostEqual(top[0].Area, 200, places=9)
        self.assertAlmostEqual(refined.Volume, 2000, places=9)

    def testSolid(self):
        self.check(self.solid.removeSplitter())

    def testCompound(self):
        self.check(Part.Compound([self.solid]).removeSplitter())
