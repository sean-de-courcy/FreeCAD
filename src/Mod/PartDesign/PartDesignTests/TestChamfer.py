# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *   Copyright (c) 2011 Juergen Riegel <FreeCAD@juergen-riegel.net>        *
# *                                                                         *
# *   This program is free software; you can redistribute it and/or modify  *
# *   it under the terms of the GNU Lesser General Public License (LGPL)    *
# *   as published by the Free Software Foundation; either version 2 of     *
# *   the License, or (at your option) any later version.                   *
# *   for detail see the LICENCE text file.                                 *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU Library General Public License for more details.                  *
# *                                                                         *
# *   You should have received a copy of the GNU Library General Public     *
# *   License along with this program; if not, write to the Free Software   *
# *   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
# *   USA                                                                   *
# *                                                                         *
# ***************************************************************************

from math import pi
import unittest

import FreeCAD


class TestChamfer(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestChamfer")

    def testChamferCubeToOctahedron(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.Chamfer = self.Doc.addObject("PartDesign::Chamfer", "Chamfer")
        self.Chamfer.Base = (self.Box, ["Face" + str(i + 1) for i in range(6)])
        self.Chamfer.Size = 4.999999
        self.Body.addObject(self.Chamfer)
        self.Doc.recompute()
        self.MajorFaces = [face for face in self.Chamfer.Shape.Faces if face.Area > 1e-3]
        self.assertEqual(len(self.MajorFaces), 8)
        # test UseAllEdges property
        self.Chamfer.UseAllEdges = True
        self.Chamfer.Base = (self.Box, [""])  # no subobjects, should still work
        self.Doc.recompute()
        self.MajorFaces = [face for face in self.Chamfer.Shape.Faces if face.Area > 1e-3]
        self.assertEqual(len(self.MajorFaces), 8)
        self.Chamfer.Base = (self.Box, ["Face50"])  # non-existent face, test topo naming resilience
        self.Doc.recompute()
        self.MajorFaces = [face for face in self.Chamfer.Shape.Faces if face.Area > 1e-3]
        self.assertEqual(len(self.MajorFaces), 8)
        self.Chamfer.UseAllEdges = False
        self.Chamfer.Base = (self.Box, ["Face1"])
        self.Doc.recompute()
        self.MajorFaces = [face for face in self.Chamfer.Shape.Faces if face.Area > 1e-3]
        self.assertEqual(len(self.MajorFaces), 9)

    # The result must be a valid solid with the volume the geometry gives, and the base
    # feature's shape must stay valid with no tolerance lowered (ops#12, see TestFillet).

    def _add_box(self, body, length, width, height, position=(0, 0, 0)):
        box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        body.addObject(box)
        box.Length = length
        box.Width = width
        box.Height = height
        box.Placement.Base = FreeCAD.Vector(*position)
        box.Refine = True
        self.Doc.recompute()
        return box

    def _edge_between(self, shape, a, b):
        a, b = FreeCAD.Vector(*a), FreeCAD.Vector(*b)
        for index, edge in enumerate(shape.Edges):
            ends = [vertex.Point for vertex in edge.Vertexes]
            if len(ends) == 2 and (
                (ends[0].isEqual(a, 1e-6) and ends[1].isEqual(b, 1e-6))
                or (ends[0].isEqual(b, 1e-6) and ends[1].isEqual(a, 1e-6))
            ):
                return "Edge" + str(index + 1)
        self.fail("No edge from {} to {}".format(a, b))

    def _add_chamfer(self, body, base, edges, size):
        chamfer = self.Doc.addObject("PartDesign::Chamfer", "Chamfer")
        body.addObject(chamfer)
        chamfer.Base = (base, edges)
        chamfer.Size = size
        self.Doc.recompute()
        return chamfer

    @staticmethod
    def _tolerances(shape):
        return [s.Tolerance for s in shape.Vertexes + shape.Edges + shape.Faces]

    def _assertValidDressUp(self, feature, volume):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, places=3)

    def _assertBaseKept(self, base, tolerances):
        self.assertTrue(base.Shape.isValid())
        for after, before in zip(self._tolerances(base.Shape), tolerances, strict=True):
            self.assertGreaterEqual(after, before)

    def testChamferEndingAgainstFace(self):
        # A step: the lower block's front top edge ends against the riser at x = 20
        for size in (1.0, 3.0, 6.0):
            with self.subTest(size=size):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                self._add_box(body, 40, 20, 10)
                step = self._add_box(body, 20, 20, 20)
                tolerances = self._tolerances(step.Shape)
                edge = self._edge_between(step.Shape, (20, 0, 10), (40, 0, 10))
                chamfer = self._add_chamfer(body, step, [edge], size)
                self._assertValidDressUp(chamfer, 12000 - size**2 / 2 * 20)
                self._assertBaseKept(step, tolerances)

    def testChamferAroundRoundedCorners(self):
        # A block 2a x 2a x h with its vertical corners filleted (radius R), then a chamfer
        # (size s) on one bottom edge. The bottom edges and the corner arcs are tangent, so the
        # chamfer runs around the whole bottom; along each arc its triangular section turns
        # about the corner's axis at the distance R - s / 3 (Pappus).
        a, h, R, s = 50.8, 22.225, 11.3125, 1.5875
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = self._add_box(body, 2 * a, 2 * a, h, (-a, -a, 0))
        rounded = self.Doc.addObject("PartDesign::Fillet", "Fillet")
        body.addObject(rounded)
        rounded.Base = (
            box,
            [self._edge_between(box.Shape, (x, y, 0), (x, y, h)) for x in (-a, a) for y in (-a, a)],
        )
        rounded.Radius = R
        self.Doc.recompute()
        volume1 = (4 * a * a - (4 - pi) * R * R) * h
        self._assertValidDressUp(rounded, volume1)
        tolerances = self._tolerances(rounded.Shape)
        edge = self._edge_between(rounded.Shape, (-a + R, -a, 0), (a - R, -a, 0))
        chamfer = self._add_chamfer(body, rounded, [edge], s)
        path = 4 * (2 * a - 2 * R) + 4 * pi / 2 * (R - s / 3)
        self._assertValidDressUp(chamfer, volume1 - s**2 / 2 * path)
        self._assertBaseKept(rounded, tolerances)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestChamfer")
        # print ("omit closing document for debugging")
