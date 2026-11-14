# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-CH (ops#640): refine merges a B-spline face into the face beside it on an extension of
its surface.

A wall's surface extended past its end (FilletFallback's wallSheet) carries other poles and knots
than the wall's own, so the face uniter's pole test kept a face on the extension apart from the
wall's face: Case Base #105 in rehearsal 5 left a 0.0197 mm2 face beside #103's blend, where
Onshape has one face. Designed here: a bent B-spline surface, a face on a segment of it (the wall)
and a thin face beside it on the whole surface (the extension). The expected result is geometric:
one face, on a surface that holds both, with the same area.
"""

import math
import unittest

import FreeCAD
import Part


def bentSurface():
    """A doubly curved B-spline surface over x in [0, 2], y in [0, 1]"""
    points = []
    for i in range(9):
        x = 2.0 * i / 8
        row = []
        for j in range(5):
            y = 1.0 * j / 4
            row.append(FreeCAD.Vector(x, y, 0.3 * math.sin(1.3 * x) + 0.2 * y * y))
        points.append(row)
    surface = Part.BSplineSurface()
    surface.interpolate(points)
    return surface


class RefineExtensionTest(unittest.TestCase):
    def wallAndExtension(self, width):
        whole = bentSurface()
        u0, u1, v0, v1 = whole.bounds()
        end = u0 + 0.6 * (u1 - u0)  # inside a knot span: the segment's poles differ
        wall = whole.copy()
        wall.segment(u0, end, v0, v1)
        wallFace = wall.toShape()
        extension = whole.toShape(end, end + width * (u1 - u0), v0, v1)
        shell = Part.Shell([wallFace, extension])
        shell.sewShape()
        return wallFace, extension, shell

    def testAFaceOnAnExtensionMergesIntoTheWall(self):
        wallFace, extension, shell = self.wallAndExtension(0.01)
        self.assertEqual(len(shell.Faces), 2)
        self.assertEqual(len(shell.Edges), 7, "the two faces share one edge")
        refined = shell.removeSplitter()
        self.assertTrue(refined.isValid())
        self.assertEqual(len(refined.Faces), 1)
        self.assertAlmostEqual(refined.Area, wallFace.Area + extension.Area, delta=1e-9)
        # On the whole surface: every point of both faces lies on the merged face's surface
        merged = refined.Faces[0]
        for face in (wallFace, extension):
            for point in [v.Point for v in face.Vertexes] + face.Edges[0].discretize(9):
                u, v = merged.Surface.parameter(point)
                self.assertLess(point.distanceToPoint(merged.Surface.value(u, v)), 1e-7)



if __name__ == "__main__":
    unittest.main()
