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
import os
import shutil
import tempfile
import unittest

import FreeCAD
import Part


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

    # Results that the full check rejects too (ops#12, see TestFillet): a 10 mm cube with a fin
    # hanging inward from the front bottom edge, and a chamfer on the back top edge

    def _add_cube_with_fin(self, body, closed=True, bottom_on_own_edges=False):
        V = FreeCAD.Vector
        cube = Part.makeBox(10, 10, 10)
        edge = cube.getElement(self._edge_between(cube, (0, 0, 0), (10, 0, 0)))
        p0, p1, q0, q1 = V(0, 0, 0), V(10, 0, 0), V(0, 5, 5), V(10, 5, 5)
        sides = [edge, Part.makeLine(p1, q1), Part.makeLine(q1, q0)]
        if closed:
            fin = Part.Face(Part.Wire(sides + [Part.makeLine(q0, p0)]))
        else:
            fin = Part.Face(Part.Plane(p0, p1, q0), Part.Wire(sides))
        bottom = next(face for face in cube.Faces if face.CenterOfMass.z < 1e-6)
        if bottom_on_own_edges:
            new_bottom = bottom.copy()
        else:
            new_bottom = Part.Face(bottom.Surface, bottom.OuterWire)
            if bottom.Orientation == "Reversed":
                new_bottom = new_bottom.reversed()
        shape = cube.replaceShape([(bottom, Part.Compound([new_bottom, fin]))])
        self.assertFalse(shape.isValid())
        faces_at_edge = 2 if bottom_on_own_edges else 3
        self.assertEqual(len(shape.ancestorsOfType(edge, Part.Face)), faces_at_edge)
        feature = self.Doc.addObject("Part::Feature", "CubeWithFin")
        feature.Shape = shape
        body.BaseFeature = feature
        self.Doc.recompute()
        return body.BaseFeature

    def testChamferRepairsInvalidResult(self):
        # A closed fin: the repair gives a valid solid, the chamfered cube
        body = self.Doc.addObject("PartDesign::Body", "Body")
        base = self._add_cube_with_fin(body)
        edge = self._edge_between(base.Shape, (0, 10, 10), (10, 10, 10))
        chamfer = self._add_chamfer(body, base, [edge], 1.0)
        self._assertValidDressUp(chamfer, 1000 - 1.0**2 / 2 * 10)

    def testChamferUnrepairableResultFails(self):
        # An open fin: the repair can't close its boundary
        body = self.Doc.addObject("PartDesign::Body", "Body")
        base = self._add_cube_with_fin(body, closed=False)
        edge = self._edge_between(base.Shape, (0, 10, 10), (10, 10, 10))
        chamfer = self._add_chamfer(body, base, [edge], 1.0)
        self.assertFalse(chamfer.isValid())
        self.assertEqual(chamfer.getStatusString(), "Resulting shape is invalid")

    def testChamferRepairLosingSolidFails(self):
        # A closed fin with the bottom face on edges of its own: the repair has no solid
        body = self.Doc.addObject("PartDesign::Body", "Body")
        base = self._add_cube_with_fin(body, bottom_on_own_edges=True)
        edge = self._edge_between(base.Shape, (0, 10, 10), (10, 10, 10))
        chamfer = self._add_chamfer(body, base, [edge], 1.0)
        self.assertFalse(chamfer.isValid())
        self.assertEqual(chamfer.getStatusString(), "Resulting shape is invalid")

    # A feature inserted before a dress-up (ops#82): Body::insertObject makes it the dress-up's
    # BaseFeature and leaves Base on the feature before it. A block 0..20 x 0..10, 10 high, with a
    # chamfer (size 1) on its back top edge; a boss (x 5..9, y 3..7, 3 high) inserted after the
    # block as a user does it: the tip set to the block, the boss added, the tip set back.

    def _add_pad(self, body, name, x0, y0, x1, y1, z, length):
        V = FreeCAD.Vector
        sketch = self.Doc.addObject("Sketcher::SketchObject", name + "Sketch")
        body.addObject(sketch)
        sketch.Placement = FreeCAD.Placement(V(0, 0, z), FreeCAD.Rotation())
        corners = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        sketch.addGeometry(
            [Part.LineSegment(a, b) for a, b in zip(corners, corners[1:] + corners[:1])], False
        )
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = sketch
        pad.Length = length
        self.Doc.recompute()
        return pad

    def _block_with_inserted_boss(self):
        body = self.Doc.addObject("PartDesign::Body", "Body")
        block = self._add_pad(body, "Block", 0, 0, 20, 10, 0, 10)
        edge = self._edge_between(block.Shape, (0, 10, 10), (20, 10, 10))
        chamfer = self._add_chamfer(body, block, [edge], 1.0)
        body.Tip = block
        boss = self._add_pad(body, "Boss", 5, 3, 9, 7, 10, 3)
        body.Tip = chamfer
        self.Doc.recompute()
        self.assertEqual(chamfer.BaseFeature, boss)
        self.assertEqual(chamfer.Base[0], block)
        self._assertValidDressUp(chamfer, 2000 + 48 - 1.0**2 / 2 * 20)
        return body, block, boss, chamfer

    def testInsertBeforeChamferKeptWhenReferencesChange(self):
        # Another edge of the block added to the chamfer: Base keeps its object, so BaseFeature
        # stays on the boss (it used to fall back to the block, dropping the boss)
        body, block, boss, chamfer = self._block_with_inserted_boss()
        front = self._edge_between(block.Shape, (0, 0, 10), (20, 0, 10))
        chamfer.Base = (block, chamfer.Base[1] + [front])
        self.assertEqual(chamfer.BaseFeature, boss)
        self.Doc.recompute()
        self._assertValidDressUp(chamfer, 2000 + 48 - 1.0**2 / 2 * 20 * 2)
        self.assertAlmostEqual(chamfer.Shape.BoundBox.ZMax, 13)

    def testInsertBeforeChamferKeptOnReload(self):
        names = [f.Name for f in self._block_with_inserted_boss()[1:]]
        path = os.path.join(tempfile.mkdtemp(), "InsertBeforeChamfer.FCStd")
        try:
            self.Doc.saveAs(path)
            FreeCAD.closeDocument(self.Doc.Name)
            self.Doc = FreeCAD.openDocument(path)
            block, boss, chamfer = [self.Doc.getObject(name) for name in names]
            self.assertEqual(chamfer.BaseFeature, boss)
            self.assertEqual(chamfer.Base[0], block)
            chamfer.touch()
            self.Doc.recompute()
            self._assertValidDressUp(chamfer, 2000 + 48 - 1.0**2 / 2 * 20)
        finally:
            FreeCAD.closeDocument(self.Doc.Name)
            self.Doc = FreeCAD.newDocument("PartDesignTestChamfer")
            shutil.rmtree(os.path.dirname(path), ignore_errors=True)

    def testChamferBaseLinkedToAnotherFeature(self):
        # What the reset in DressUp::onChanged is for: Base linked to another feature takes
        # BaseFeature with it, and undo restores both
        body, block, boss, chamfer = self._block_with_inserted_boss()
        self.Doc.UndoMode = 1
        top = self._edge_between(boss.Shape, (5, 7, 13), (9, 7, 13))
        self.Doc.openTransaction("Relink")
        chamfer.Base = (boss, [top])
        self.Doc.commitTransaction()
        self.assertEqual(chamfer.BaseFeature, boss)
        self.Doc.openTransaction("Relink")
        chamfer.Base = (block, [self._edge_between(block.Shape, (0, 10, 10), (20, 10, 10))])
        self.Doc.commitTransaction()
        self.assertEqual(chamfer.BaseFeature, block)
        self.Doc.recompute()
        self._assertValidDressUp(chamfer, 2000 - 1.0**2 / 2 * 20)
        self.Doc.undo()
        self.assertEqual(chamfer.Base[0], boss)
        self.assertEqual(chamfer.BaseFeature, boss)
        self.Doc.recompute()
        self._assertValidDressUp(chamfer, 2000 + 48 - 1.0**2 / 2 * 4)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestChamfer")
        # print ("omit closing document for debugging")
