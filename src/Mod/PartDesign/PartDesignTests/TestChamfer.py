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

import math
from math import pi
import os
import shutil
import tempfile
import unittest

import FreeCAD
import Part
from parttests import FilletFallbackTest as models


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
        # Neither lowered by a repair (ops#12) nor raised by OCCT's maker, which runs on a copy
        # (ops#345)
        self.assertTrue(base.Shape.isValid())
        self.assertEqual(self._tolerances(base.Shape), tolerances)

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
        # The insert reroutes Base onto the inserted boss with its edges (ops#127, a change of
        # BaseFeature moves what follows the base); the edge is the same (the boss doesn't touch it)
        self.assertEqual(chamfer.Base[0], boss)
        self._assertValidDressUp(chamfer, 2000 + 48 - 1.0**2 / 2 * 20)
        return body, block, boss, chamfer

    def testInsertBeforeChamferKeptWhenReferencesChange(self):
        # Another edge of the block added to the chamfer: Base keeps its object, so BaseFeature
        # stays on the boss (it used to fall back to the block, dropping the boss)
        body, block, boss, chamfer = self._block_with_inserted_boss()
        front = self._edge_between(boss.Shape, (0, 0, 10), (20, 0, 10))
        chamfer.Base = (boss, chamfer.Base[1] + [front])
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
            self.assertEqual(chamfer.Base[0], boss)
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

    # Invalid results that OCCT (8.0.1) returns without an error (ops#297), on the models of
    # parttests.FilletFallbackTest. The exact construction builds them where it can (at the
    # limit); the feature repairs the others only if the repair keeps the solids and the faces,
    # or fails.

    def _chamfer_on_base(self, shape, edges, size, allow_compound=False):
        body = self.Doc.addObject("PartDesign::Body", "Body")
        body.AllowCompound = allow_compound
        feature = self.Doc.addObject("Part::Feature", "Base")
        feature.Shape = shape
        body.BaseFeature = feature
        self.Doc.recompute()
        names = [
            "Edge%d" % next(i for i, e in enumerate(shape.Edges, 1) if e.isSame(edge))
            for edge in edges
        ]
        return self._add_chamfer(body, body.BaseFeature, names, size)

    def _assertFails(self, chamfer):
        self.assertFalse(chamfer.isValid())
        self.assertEqual(chamfer.getStatusString(), "Resulting shape is invalid")

    def testChamferLeavesTheBaseTolerancesAlone(self):
        # The rib's top edges chamfered just under the limit, ending against the wall: OCCT's
        # maker raises its input's vertices there to 1e-4, and the base feature's stored shape
        # shares them. The maker runs on a copy; the result keeps what it raised (ops#345)
        rib, _ = models.rib_against_wall()
        tolerances = self._tolerances(rib)
        self.assertLess(max(tolerances), 1e-6)
        chamfer = self._chamfer_on_base(rib, models.top_edges(rib), 2 - 1e-5)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self._assertBaseKept(self.Doc.getObject("Base"), tolerances)
        self.assertGreater(max(self._tolerances(chamfer.Shape)), 1e-5)

    def testChamferInvalidOcctResultAtLimit(self):
        # A chamfer as wide as a rib's top, against a wall
        rib, edges = models.rib_against_wall()
        self._assertValidDressUp(self._chamfer_on_base(rib, edges, 4.0), 4800 - 8 * 30)

    def testChamferOverlongBuilds(self):
        # Just over chamfers meeting on a disk's rim face, and on a stadium plate's: OCCT returns
        # two invalid solids; the chamfers meet in a ridge, as Onshape's (ops#640, S3; volumes by
        # quadrature, Part's OverflowTest.testOverlongFullChamfers)
        for model, size, volume in ((models.disk, 1.00001, 567.579879), (models.stadium_plate, 2.0002, 845.198614)):
            shape, edges = model()
            chamfer = self._chamfer_on_base(shape, edges, size, allow_compound=True)
            self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
            self.assertAlmostEqual(chamfer.Shape.Volume, volume, delta=1e-5)

    def testChamferOverlappingFail(self):
        # Chamfers of 2.65 on two edges 4 apart overlap on the face between them, and no chamfer
        # exists. OCCT's result has a self-intersecting wire, which the repair turned into a
        # valid solid with two more faces: on the block, on a large block (where the faces'
        # total area hardly changes), and on a base made invalid elsewhere
        block, edges = models.notched_block()
        self._assertFails(self._chamfer_on_base(block, edges, 2.65))
        block, edges = models.notched_block(0.1, (1000, 1000, 1))
        self._assertFails(self._chamfer_on_base(block, edges, 0.265))
        block, edges = models.notched_block()
        base = models.with_back_face_reversed(block)
        edges = [
            models.edge_between(base, e.Vertexes[0].Point, e.Vertexes[-1].Point) for e in edges
        ]
        self._assertFails(self._chamfer_on_base(base, edges, 2.65))

    def testChamferWholeOutlineOfAStadium(self):
        # ops#298: OCCT "succeeds" on a stadium's whole top outline at d = 2 (half its width),
        # keeping the top face with area 0; the exact construction builds the ridge: two
        # 45 degree strips and a cone on each end
        plate, outline = models.fused_stadium()
        chamfer = self._chamfer_on_base(plate, outline, 2.0)
        self._assertValidDressUp(chamfer, 240 + pi * 12 - 80 - 2 * pi * (2 - 2 / 3) * 2)
        self.assertGreater(models.narrowest(chamfer.Shape, plate), 0.5)

    def testChamferCoincidentCases(self):
        # Section 1 of the design note: OCCT fails at each of these limits; the feature gets the
        # exact construction's result with the analytic volume. The 4 mm top of a rib (a ridge),
        # a plate's edge at its thickness, and a cube's twelve edges (an octahedron's corners)
        rib = Part.makeBox(30, 4, 20)
        self._assertValidDressUp(
            self._chamfer_on_base(rib, models.top_edges(rib), 2.0), 2400 - 4 * 30
        )
        plate = Part.makeBox(30, 20, 4)
        edge = models.edge_between(plate, (0, 0, 4), (30, 0, 4))
        self._assertValidDressUp(self._chamfer_on_base(plate, [edge], 4.0), 2400 - 8 * 30)

    def testChamferRepairKeepingTheSurface(self):
        # Four chamfers meeting at a pyramid's apex: OCCT's faces are misoriented; the repair
        # reorients them. Chamfers along the full length of the four edges (10 sqrt 3, faces at
        # 120 degrees, section sin(120 degrees) / 2) remove a little more
        solid, edges = models.pyramid()
        chamfer = self._chamfer_on_base(solid, edges, 1.0)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertTrue(chamfer.Shape.isValid())
        chamfers = 4 * 3**0.5 / 4 * 10 * 3**0.5
        removed = 4000 / 3 - chamfer.Shape.Volume
        self.assertLess(removed, chamfers)
        self.assertGreater(removed, 0.9 * chamfers)

    def testChamferDropsTheLoosePartsOfABaseFeature(self):
        # As testFilletDropsTheLoosePartsOfABaseFeature (ops#303): solids and shells only, and a
        # Pad on the top works
        pad = models.pad_on_dressed_up_base(self.Doc, "Chamfer", 1.0)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        chamfer = self.Doc.getObject("Chamfer")
        self.assertEqual(models.loose_parts(chamfer.Shape), ([], [], []))
        volume = sum(s.Volume for s in pad.Shape.Solids)
        self.assertAlmostEqual(volume, 1000 - 0.5 * 10 + 48, delta=1e-6)

    def testChamferAcrossAPocketFillsNothing(self):
        # As testFilletAcrossAPocketFillsNothing (ops#393): a chamfer of 3 across the pocket gives
        # 955 for the Boolean construction's 951; the Chamfer is 951 or fails naming the edge
        recess = Part.makeBox(4, 1, 2, FreeCAD.Vector(3, 1.5, 8))
        chamfer, edge = models.dressed_up_in_a_body(self.Doc, "Chamfer", recess, 3)
        removed = models.front_top_removed("Chamfer", 3)
        expected = Part.makeBox(10, 10, 10).cut(removed).cut(recess).Volume
        self.assertAlmostEqual(expected, 951, delta=1e-9)
        if chamfer.isValid():
            self.assertAlmostEqual(chamfer.Shape.Volume, expected, delta=1e-6)
        else:
            message = "The chamfer fills a recess of the base next to %s:" % edge
            self.assertTrue(
                chamfer.getStatusString().startswith(message), chamfer.getStatusString()
            )

    def testChamferOntoATangentRound(self):
        # As testFilletOntoATangentRound: a chamfer of 2 on the concave edge reaches the round the
        # L's floor ends in, at its point 2 from the edge (734.782; PR 346 review, H1)
        base = models.rounded_concave_block()
        ends = ((0, 5, 5), (10, 5, 5))
        chamfer, _ = models.dressed_in_a_body(self.Doc, "Chamfer", base, ends, 2)
        expected = base.fuse(models.concave_added_onto_round("Chamfer", 2)).Volume
        self.assertAlmostEqual(expected, 734.782190, delta=1e-5)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertAlmostEqual(chamfer.Shape.Volume, expected, delta=1e-5)

    def testChamferOverASmoothDimpleFillsNothing(self):
        # As testFilletOverASmoothDimpleFillsNothing: chamfers of 2.5 give 747.854 for the
        # construction's 747.489; the Chamfer is that or fails naming the front edge
        block, base = models.smoothly_dimpled_block()
        front, concave = ((0, 0, 10), (10, 0, 10)), ((0, 5, 5), (10, 5, 5))
        chamfer, edge = models.dressed_in_a_body(self.Doc, "Chamfer", base, front, 2.5, concave)
        dressed = block.cut(models.front_top_removed("Chamfer", 2.5))
        dressed = dressed.fuse(models.concave_added("Chamfer", 2.5))
        expected = dressed.cut(block.cut(base)).Volume
        self.assertAlmostEqual(expected, 747.488978, delta=1e-5)
        if chamfer.isValid():
            self.assertAlmostEqual(chamfer.Shape.Volume, expected, delta=1e-6)
        else:
            message = "The chamfer fills a recess of the base next to %s:" % edge
            self.assertTrue(
                chamfer.getStatusString().startswith(message), chamfer.getStatusString()
            )

    def testChamferOverASmoothDimpleInTheFloorFillsNothing(self):
        # As testFilletOverASmoothDimpleInTheFloorFillsNothing: chamfers of 2.5 give 950 for the
        # construction's 949.635; the Chamfer is that or fails naming the outer edge
        block = models.deep_concave_block()
        base = models.dimpled(block, 5, 12.8, 5)
        outer, concave = ((0, 14, 5), (10, 14, 5)), ((0, 5, 5), (10, 5, 5))
        chamfer, edge = models.dressed_in_a_body(self.Doc, "Chamfer", base, outer, 2.5, concave)
        dressed = block.cut(models.outer_floor_removed("Chamfer", 2.5))
        dressed = dressed.fuse(models.concave_added("Chamfer", 2.5))
        expected = dressed.cut(block.cut(base)).Volume
        self.assertAlmostEqual(expected, 949.634998, delta=1e-5)
        if chamfer.isValid():
            self.assertAlmostEqual(chamfer.Shape.Volume, expected, delta=1e-6)
        else:
            message = "The chamfer fills a recess of the base next to %s:" % edge
            self.assertTrue(
                chamfer.getStatusString().startswith(message), chamfer.getStatusString()
            )

    # Chamfers by equal distances over a chain of edges at different angles, as Onshape's
    # (notes/chamfer-chain-setbacks.md in the ops repository, oracle 14 CT1-CT3): the chain's first
    # edge in Base gets the size, every other edge size tan(a1 / 2) / tan(a / 2), a its wedge
    # angle. Q-TAPER: a block 20 x 20 x 5 with a pocket open at z = 0, its end walls x = 5 and
    # x = 15 square, its side walls leaning in by 6 degrees (bottom edges at 96 degrees).

    def _taper_body(self, t=6, cut=None):
        # cut: a shape also cut from the block (holes), before the edges are named
        k = math.tan(math.radians(t))
        V = FreeCAD.Vector
        block = Part.makeBox(20, 20, 5, V(0, -10, 0))
        section = Part.makePolygon(
            [
                V(5, -3 - k, -1),
                V(5, 3 + k, -1),
                V(5, 3 - 3 * k, 3),
                V(5, -3 + 3 * k, 3),
                V(5, -3 - k, -1),
            ]
        )
        pocket = Part.Face(section).extrude(V(10, 0, 0))
        body = self.Doc.addObject("PartDesign::Body", "Body")
        feature = self.Doc.addObject("Part::Feature", "Taper")
        solid = block.cut(pocket).Solids[0]
        feature.Shape = solid.cut(cut).Solids[0] if cut else solid
        body.BaseFeature = feature
        self.Doc.recompute()
        base = body.BaseFeature
        shape = base.Shape
        edges = {
            "end5": self._edge_between(shape, (5, -3, 0), (5, 3, 0)),
            "end15": self._edge_between(shape, (15, -3, 0), (15, 3, 0)),
            "side+": self._edge_between(shape, (5, 3, 0), (15, 3, 0)),
            "side-": self._edge_between(shape, (5, -3, 0), (15, -3, 0)),
        }
        return body, base, edges

    def _assertHole(self, chamfer, x_min, x_max, y_max, sharp_y=None):
        # The bottom face's hole: its corners at x_min and x_max, |y| = y_max. With sharp_y, the end
        # at x_min isn't chamfered: the side chamfers stop on its wall, which adds corners at |y| = sharp_y
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        shape = chamfer.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        bottoms = [
            face
            for face in shape.Faces
            if face.Area > 100 and all(abs(v.Point.z) < 1e-7 for v in face.Vertexes)
        ]
        self.assertEqual(len(bottoms), 1)
        hole = [v.Point for v in bottoms[0].Vertexes if 1 < v.Point.x < 19 and abs(v.Point.y) < 9]
        self.assertEqual(len(hole), 4 if sharp_y is None else 6)
        self.assertAlmostEqual(min(p.x for p in hole), x_min, places=7)
        self.assertAlmostEqual(max(p.x for p in hole), x_max, places=7)
        sharp = [p for p in hole if sharp_y is not None and abs(abs(p.y) - sharp_y) < 1e-7]
        self.assertEqual(len(sharp), 0 if sharp_y is None else 2)
        for p in sharp:
            self.assertAlmostEqual(p.x, x_min, places=7)
        for p in hole:
            if p not in sharp:
                self.assertAlmostEqual(abs(p.y), y_max, places=7)

    def testChamferChainSquareEdgeFirst(self):
        # A square end edge first: the 96-degree sides get 0.5 / tan 48 = 0.450202
        body, base, e = self._taper_body()
        edges = [e["end5"], e["side+"], e["end15"], e["side-"]]
        chamfer = self._add_chamfer(body, base, edges, 0.5)
        side = 0.5 / math.tan(math.radians(48))
        self.assertAlmostEqual(side, 0.450202, places=6)
        self._assertHole(chamfer, 4.5, 15.5, 3 + side)

    def testChamferChainReorderedBase(self):
        # Base reordered so a tapered side comes first: the square ends get 0.5 tan 48 = 0.555306
        body, base, e = self._taper_body()
        edges = [e["end5"], e["side+"], e["end15"], e["side-"]]
        chamfer = self._add_chamfer(body, base, edges, 0.5)
        chamfer.Base = (base, [e["side+"], e["end5"], e["side-"], e["end15"]])
        self.Doc.recompute()
        end = 0.5 * math.tan(math.radians(48))
        self.assertAlmostEqual(end, 0.555306, places=6)
        self._assertHole(chamfer, 5 - end, 15 + end, 3.5)

    def testChamferChainRemovingTheFirstPickPromotesTheNext(self):
        # Without the end edge at x = 5 the chain is side, end, side, led by the tapered side: the
        # end at x = 15 gets 0.555306, the sides 0.5, and the end at x = 5 isn't chamfered
        body, base, e = self._taper_body()
        edges = [e["end5"], e["side+"], e["end15"], e["side-"]]
        chamfer = self._add_chamfer(body, base, edges, 0.5)
        chamfer.Base = (base, [e["side+"], e["end15"], e["side-"]])
        self.Doc.recompute()
        self._assertHole(chamfer, 5, 15 + 0.5 * math.tan(math.radians(48)), 3.5, sharp_y=3.5 - 0.5)

    def testChamferChainBandOverAHoleKeepsTheWidth(self):
        # Sides leaning in by 20 degrees (110-degree bottom edges) and a tapered side first: the
        # ends get 0.5 tan 55 = 0.714074, whose band on the bottom face crosses a blind hole r 0.05
        # centred 0.62 beyond each end edge, which OCCT fills. Built again with 0.5 on every edge
        # (ruling A, review r1 T1), the band stops short of the hole: the hole stays open, and its
        # point (4.38, 0, 0.2) lies above the chamfer plane either way, outside the result
        V = FreeCAD.Vector
        holes = Part.makeCylinder(0.05, 0.3, V(5 - 0.62, 0, 0)).fuse(
            Part.makeCylinder(0.05, 0.3, V(15 + 0.62, 0, 0))
        )
        body, base, e = self._taper_body(t=20, cut=holes)
        edges = [e["side+"], e["end5"], e["side-"], e["end15"]]
        chamfer = self._add_chamfer(body, base, edges, 0.5)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        shape = chamfer.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertFalse(shape.isInside(V(5 - 0.62, 0, 0.2), 1e-9, True))
        # The ends came out at 0.5, not 0.714: 0.55 + 0.01 from the end edge is still material
        self.assertTrue(shape.isInside(V(5 - 0.55, 1, 0.01), 1e-9, True))
        self.assertTrue(shape.isInside(V(15 + 0.55, 1, 0.01), 1e-9, True))

    def testChamferHalfTubeRunsThroughInPartDesign(self):
        # As FilletFallbackTest.ChamferRunThroughTest (ops#936, Test Tube Feeder #45): a half tube
        # (r 6, R 10, length 30), its end edge across one leg chamfered 10. The wedge runs on
        # across the bore and cuts the far leg too; the lost-material check must not refuse that
        # far leg's cut (review r1, T1)
        tube = models.ChamferRunThroughTest()
        R, r, L = tube.R, tube.r, tube.L
        shape = tube.half_tube()
        chamfer, _ = models.dressed_in_a_body(
            self.Doc, "Chamfer", shape, ((r, 0, 0), (R, 0, 0)), R
        )
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        result = chamfer.Shape
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        removed = math.pi * R * (R * R - r * r) / 2 - 2 * (R**3 - r**3) / 3
        expected = math.pi * (R * R - r * r) * L / 2 - removed
        self.assertAlmostEqual(result.Volume, expected, delta=1e-6 * expected)
        far = Part.makeBox(R, R, L, FreeCAD.Vector(-R, 0, 0))
        self.assertGreater(shape.common(far).Volume - result.common(far).Volume, 1.0)

    # ops#942 (notes/chamfer-varying-angle-942.md sections 2 and 6): an equal distance chamfer along
    # a closed edge between a cylinder of radius R and a plane tilted by t from its cross-section
    # is one ball rolled round the edge, d = w tan(a / 2) at the reference angle a; it fills or
    # cuts pi d^2 (R + s d / 3) (1 + sin^2 t / 2) / cos t, s = +1 where the ball lies outside the
    # cylinder. R 10, w 2, t 20 deg
    R942 = 10.0
    W942 = 2.0
    T942 = math.radians(20)
    # T3's fill: 72.6404 less the part outside the plate's cylinder, by the integral of section 6
    # (midpoint rule over theta and the triangle, 1600 x 800 x 800: 66.06024; the exact sweep cut by
    # the plate's cylinder: 66.06017). Onshape's VA-E reading is +66.0214, 5.9e-4 of it apart
    # (notes/chamfer-varying-angle-942.md section 7)
    RUNOFF942 = 66.0602

    @staticmethod
    def _tiltedPlate(tilt, half=30.0, depth=30.0):
        """A block whose top is the plane z = x tan(tilt)"""
        V = FreeCAD.Vector
        k = math.tan(tilt)
        points = [V(-half, -half, -depth), V(half, -half, -depth), V(half, -half, half * k),
                  V(-half, -half, -half * k)]
        return Part.Face(Part.makePolygon(points + [points[0]])).extrude(V(0, 2 * half, 0))

    def _varyingModel(self, kind, tilt=None):
        V = FreeCAD.Vector
        tilt = self.T942 if tilt is None else tilt
        R = self.R942
        if kind == "boss":
            return self._tiltedPlate(tilt).fuse(Part.makeCylinder(R, 40, V(0, 0, -20))).removeSplitter()
        if kind == "rod":
            return Part.makeCylinder(R, 40, V(0, 0, -30)).common(
                self._tiltedPlate(tilt, depth=35)).removeSplitter()
        if kind == "hole":
            return self._tiltedPlate(tilt, depth=20).cut(
                Part.makeCylinder(R, 60, V(0, 0, -30))).removeSplitter()
        if kind == "cone":
            return self._tiltedPlate(tilt).fuse(
                Part.makeCone(R, R - 2, 40, V(0, 0, -20))).removeSplitter()
        raise ValueError(kind)

    def _varyingChamfer(self, shape, widthAt=0, edges=None, size=None):
        base = self.Doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        body = self.Doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = base
        self.Doc.recompute()
        if edges is None:
            edges = ["Edge%d" % (i + 1) for i, e in enumerate(base.Shape.Edges)
                     if e.Curve.TypeId in ("Part::GeomEllipse", "Part::GeomBSplineCurve")
                     and e.isClosed()]
        chamfer = self.Doc.addObject("PartDesign::Chamfer", "Chamfer")
        body.addObject(chamfer)
        chamfer.Base = (base, edges)
        chamfer.Size = self.W942 if size is None else size
        chamfer.WidthAt = widthAt
        self.Doc.recompute()
        return base, chamfer

    def _ballVolume(self, d, s, tilt=None):
        tilt = self.T942 if tilt is None else tilt
        return pi * d * d * (self.R942 + s * d / 3) * (1 + math.sin(tilt) ** 2 / 2) / math.cos(tilt)

    def _assertVolume(self, change, expected):
        # The Booleans' and the body's measures: 1e-5 of the chamfer's own volume (Onshape's
        # readings were within 1.3e-4 of the closed forms)
        self.assertLess(abs(change - expected), 1e-5 * abs(expected), (change, expected))

    def _assertBall(self, kind, widthAt, sign, s, legNarrow, legWide):
        """The chamfer's volume and its legs at the narrow and the wide side, where the rails' points
        lie in the plane y = 0 at legNarrow / legWide from the picked edge's point"""
        R, t = self.R942, self.T942
        base, chamfer = self._varyingChamfer(self._varyingModel(kind), widthAt)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        shape = chamfer.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        a = pi / 2 - t if widthAt == 0 else pi / 2 + t
        d = self.W942 * math.tan(a / 2)
        self._assertVolume(shape.Volume - base.Shape.Volume, sign * self._ballVolume(d, s))
        self.assertEqual(len(shape.Faces), len(base.Shape.Faces) + 1)
        # The chamfer face: the one face that is neither the plane, the cylinder nor the base's
        new = [f for f in shape.Faces if f.Surface.TypeId == "Part::GeomBSplineSurface"]
        self.assertEqual(len(new), 1)
        # Its two rails at theta 0 and 180 deg: the points of its edges in the plane y = 0
        V = FreeCAD.Vector
        for x, leg in ((R, legNarrow), (-R, legWide)):
            corner = V(x, 0, x * math.tan(t))
            near = [p for e in new[0].Edges if not e.isSeam(new[0])
                    for p in [e.valueAt(e.Curve.parameter(corner))] if abs(p.y) < 1e-6]
            self.assertEqual(len(near), 2, (x, near))
            for p in near:
                self.assertAlmostEqual((p - corner).Length, leg, places=5)
        return base, chamfer

    def testChamferVaryingAngleBossFoot(self):
        # T1, concave: d = 2 tan 35 = 1.400415; +72.6404; legs 2 at the narrow side, 0.980581 at
        # the wide side. The narrow side of a boss's foot on z = x tan t is x = +R
        self._assertBall("boss", 0, 1, 1, 2.0, 0.980581)

    def testChamferVaryingAngleRodRim(self):
        # T2, convex: the ball inside the rod, -66.1611; the narrow side of a rim cut at the rod's
        # top is its high point, x = +R, as a boss's foot's
        self._assertBall("rod", 0, -1, -1, 2.0, 0.980581)

    def testChamferVaryingAngleWidest(self):
        # T7: Widest angle, d = 2 tan 55 = 2.856296: the boss +316.194 (Onshape +316.1822), the rod
        # -261.219 (Onshape -261.2353), the leg 2 at the wide side and 4.079213 at the narrow side
        self._assertBall("boss", 1, 1, 1, 4.079213, 2.0)
        self.Doc.removeObject("Chamfer")
        self._assertBall("rod", 1, -1, -1, 4.079213, 2.0)

    def testChamferVaryingAngleHoleRim(self):
        # T7, a hole's rim: the ball outside the cylinder, cutting -72.640 (Onshape -72.6334) with
        # Narrowest angle and -316.194 (Onshape -316.1823) with Widest angle; the narrow side of a
        # hole's rim on z = x tan t is x = -R
        self._assertBall("hole", 0, -1, 1, 0.980581, 2.0)
        self.Doc.removeObject("Chamfer")
        self._assertBall("hole", 1, -1, 1, 2.0, 4.079213)

    def testChamferVaryingAngleRunsOffTheLedge(self):
        # T3 (section 3 b): T1's boss on a round plate of radius 11.6 whose axis is at x = -0.6, the
        # ledge 1.064 wide in the plane at the narrow side: the fill runs off it over the plate's
        # rim and is cut off by the plate's wall, run on. One face more; the ledge a crescent; the
        # volume T1's less the part outside the plate's cylinder (RUNOFF942, the fork's integral)
        V = FreeCAD.Vector
        R = self.R942
        plate = Part.makeCylinder(11.6, 60, V(-0.6, 0, -40)).common(self._tiltedPlate(self.T942))
        shape = plate.removeSplitter().fuse(Part.makeCylinder(R, 40, V(0, 0, -20))).removeSplitter()
        foot = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                if e.Curve.TypeId == "Part::GeomEllipse" and abs(e.Curve.MinorRadius - R) < 1e-6]
        self.assertEqual(len(foot), 1)
        base, chamfer = self._varyingChamfer(shape, 0, foot)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        result = chamfer.Shape
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), len(shape.Faces) + 1)
        # The fill alone (the body's own measure is good to about 4e-7 of its 18900 mm3, 6e-3 here)
        self.assertLess(shape.cut(result).Volume, 1e-6)
        self._assertVolume(result.cut(shape).Volume, self.RUNOFF942)
        # The plate's wall is one face, grown above the rim; the ledge one face, off the boss's foot
        walls = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomCylinder"
                 and abs(f.Surface.Radius - 11.6) < 1e-6]
        self.assertEqual(len(walls), 1)
        self.assertGreater(walls[0].BoundBox.ZMax, 11.0 * math.tan(self.T942))
        planes = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomPlane"
                  and abs(f.Surface.Axis.z) < 0.99]
        self.assertEqual(len(planes), 1)
        self.assertGreater(planes[0].distToShape(Part.Vertex(V(R, 0, R * math.tan(self.T942))))[0], 1)

    def testChamferVaryingAngleRunsOffOntoALeaningWall(self):
        # T6 (section 3 b): T3 with the plate's wall drafted 5 deg (a cone): the fill runs off the
        # ledge onto a face that is not measured. The construction refuses, OCCT fails as on T3, and
        # the chamfer fails with the construction's refusal
        V = FreeCAD.Vector
        R = self.R942
        lean = math.tan(math.radians(5))
        wall = Part.makeCone(11.6 + 40 * lean, 11.6 - 20 * lean, 60, V(-0.6, 0, -40))
        shape = wall.common(self._tiltedPlate(self.T942)).removeSplitter().fuse(
            Part.makeCylinder(R, 40, V(0, 0, -20))).removeSplitter()
        foot = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                if e.Curve.TypeId == "Part::GeomEllipse" and abs(e.Curve.MinorRadius - R) < 1e-6]
        self.assertEqual(len(foot), 1)
        base, chamfer = self._varyingChamfer(shape, 0, foot)
        self.assertFalse(chamfer.isValid())
        self.assertIn("neither a plane nor a cylinder along the chamfered cylinder",
                      chamfer.getStatusString())

    # Section 14 (the ridges' run-offs, measured on Onshape's faces): the whole ball's tool, d
    # unchanged, kept on the picked edge's side of the face beyond's surface, extended; the face
    # beyond grows to meet the chamfer face. T14a and T14b: the volumes are the test's own quadrature
    # of section 2's triangle sweep E W L kept inside the wall's prism (midpoint rule, 2000 x 200 and
    # 4000 x 400 samples over theta and the triangle's first side, the second side's interval in the
    # prism in closed form; extrapolated: 28.94835 and 11.23471)
    RUNOFF14A = 28.94835
    RUNOFF14B = 11.23471

    @staticmethod
    def _frame942(tilt):
        V = FreeCAD.Vector
        return (V(math.cos(tilt), 0, math.sin(tilt)), V(0, 1, 0), V(-math.sin(tilt), 0, math.cos(tilt)))

    def _ellipseInPlane(self, tilt, radius, grow, shift):
        """A face in the plane z = x tan(tilt) through the origin: the ellipse that is the section of
        the cylinder of the given radius about z, grown by `grow` and moved `shift` along the plane's
        x direction"""
        u, v, n = self._frame942(tilt)
        centre = u * shift
        ellipse = Part.Ellipse(centre + u * (radius / math.cos(tilt) + grow), centre + v * (radius + grow), centre)
        return Part.Face(Part.Wire([ellipse.toShape()]))

    def _assertOn(self, result, chamfer, faces):
        """Every point of the chamfer face's edges lies on one of the given faces of the result"""
        for edge in chamfer.Edges:
            for p in edge.discretize(64):
                self.assertLess(min(f.distToShape(Part.Vertex(p))[0] for f in faces), 1e-6, p)

    def testChamferVaryingAngleRunsOffOntoAnExtrudedWall(self):
        # T14a, the gaskets' #9: a tube of radius 10 through a collar whose top leans 3 deg and whose
        # wall is an ellipse extruded along the top's normal, 1.0 outside the tube's section and
        # moved 0.2 toward -x: the strip is 0.8 wide at the narrow side (legs 0.900 to 1.0, d =
        # 0.948965), where the fill runs off it, and 1.2 at the wide side. The fill is cut off by
        # the wall's surface run on; the wall grows to meet it, the strip is a crescent; one face more
        V = FreeCAD.Vector
        t = math.radians(3)
        u, v, n = self._frame942(t)
        wall = self._ellipseInPlane(t, 10.0, 1.0, -0.2).extrude(n * -5)
        shape = wall.fuse(Part.makeCylinder(10.0, 40, V(0, 0, -20))).removeSplitter()
        foot = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                if e.isClosed() and e.Curve.TypeId == "Part::GeomEllipse" and abs(e.Curve.MinorRadius - 10.0) < 1e-6
                and all(abs(p.z - p.x * math.tan(t)) < 1e-6 for p in e.discretize(12))]
        self.assertEqual(len(foot), 1)
        base, chamfer = self._varyingChamfer(shape, 0, foot, size=1.0)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        result = chamfer.Shape
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), len(shape.Faces) + 1)
        self.assertLess(shape.cut(result).Volume, 1e-6)
        self._assertVolume(result.cut(shape).Volume, self.RUNOFF14A)
        # The wall one face, grown; the strip one face, a crescent off the narrow side
        before = [f for f in shape.Faces if "Extrusion" in f.Surface.TypeId]
        walls = [f for f in result.Faces if "Extrusion" in f.Surface.TypeId]
        self.assertEqual(len(walls), 1)
        self.assertGreater(walls[0].Area, before[0].Area + 1.0)
        self.assertGreater(max(p.dot(n) for e in walls[0].Edges for p in e.discretize(200)), 0.01)
        strips = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomPlane"
                  and abs(f.Surface.Axis.dot(n)) > 0.999 and f.CenterOfMass.dot(n) > -1]
        self.assertEqual(len(strips), 1)
        self.assertGreater(strips[0].distToShape(Part.Vertex(V(10.0, 0, 10.0 * math.tan(t))))[0], 0.5)
        # The chamfer face's edges lie on the tube, the strip or the wall
        new = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomBSplineSurface"]
        self.assertEqual(len(new), 1)
        tube = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomCylinder" and f.BoundBox.ZMax > 5]
        self._assertOn(result, new[0], tube + strips + walls)

    def testChamferVaryingAngleCutRunsOffIntoACounterbore(self):
        # T14b, Case Base #90 and #97: a bore of radius 6 through the floor of a counterbore that
        # leans 1 deg, the counterbore's wall an ellipse extruded along the floor's normal, 0.70
        # outside the bore's section and moved 0.1 toward +x; Widest angle, w 0.75: d = 0.763206,
        # legs 0.75 to 0.777, the floor 0.80 wide at the wide side and 0.60 at the narrow side,
        # where the cut runs off it into the wall. The cut is kept inside the wall's surface run
        # on; the wall grows below the floor, a sliver of floor is left; one face more
        V = FreeCAD.Vector
        t = math.radians(1)
        u, v, n = self._frame942(t)
        plate = self._tiltedPlate(t)
        plate.translate(n * 2)
        pocket = self._ellipseInPlane(t, 6.0, 0.70, 0.1).extrude(n * 3)
        shape = plate.cut(pocket).cut(Part.makeCylinder(6.0, 80, V(0, 0, -40))).removeSplitter()
        rim = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
               if e.isClosed() and e.Curve.TypeId == "Part::GeomEllipse" and abs(e.Curve.MinorRadius - 6.0) < 1e-6
               and all(abs(p.dot(n)) < 1e-6 for p in e.discretize(12))]
        self.assertEqual(len(rim), 1)
        base, chamfer = self._varyingChamfer(shape, 1, rim, size=0.75)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        result = chamfer.Shape
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Faces), len(shape.Faces) + 1)
        self.assertLess(result.cut(shape).Volume, 1e-6)
        self._assertVolume(shape.cut(result).Volume, self.RUNOFF14B)
        before = [f for f in shape.Faces if "Extrusion" in f.Surface.TypeId]
        walls = [f for f in result.Faces if "Extrusion" in f.Surface.TypeId]
        self.assertEqual(len(walls), 1)
        self.assertGreater(walls[0].Area, before[0].Area + 1.0)
        self.assertLess(min(p.dot(n) for e in walls[0].Edges for p in e.discretize(200)), -0.01)
        floors = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomPlane"
                  and abs(f.Surface.Axis.dot(n)) > 0.999 and abs(f.CenterOfMass.dot(n)) < 1e-6]
        self.assertEqual(len(floors), 1)
        self.assertLess(floors[0].Area, 1.0)
        # The bore's rail is whole: one closed edge of the chamfer face on the bore
        new = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomBSplineSurface"]
        self.assertEqual(len(new), 1)
        bore = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomCylinder"]
        self.assertEqual(len(bore), 1)
        self.assertTrue(any(e.isClosed() and bore[0].distToShape(e)[0] < 1e-6
                            and all(abs(p.dot(n)) > 0.7 for p in e.discretize(12)) for e in new[0].Edges))
        self._assertOn(result, new[0], bore + floors + walls)

    def testChamferVaryingAngleRunOffsNotMeasuredAreRefused(self):
        # T14c: what section 14 did not measure is refused, and OCCT fails on each too: (1) a strip
        # narrower than the shortest leg all round (T14a's collar 0.5 outside the tube); (2) a fill
        # running over a concave far edge into a wall that rises from the strip; (3) a cut into a
        # counterbore whose wall is a cylinder along the bore's axis, not the floor's normal
        V = FreeCAD.Vector
        t = math.radians(3)
        u, v, n = self._frame942(t)
        tube = Part.makeCylinder(10.0, 40, V(0, 0, -20))

        def foot(shape, radius, tilt):
            return ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                    if e.isClosed() and e.Curve.TypeId == "Part::GeomEllipse"
                    and abs(e.Curve.MinorRadius - radius) < 1e-6
                    and all(abs(p.z - p.x * math.tan(tilt)) < 1e-6 for p in e.discretize(12))]

        def refused(shape, edges, widthAt, size, text):
            self.assertEqual(len(edges), 1)
            base, chamfer = self._varyingChamfer(shape, widthAt, edges, size=size)
            self.assertFalse(chamfer.isValid())
            self.assertIn(text, chamfer.getStatusString())
            for name in ("Chamfer", "Body", "Base"):
                self.Doc.removeObject(name)

        ring = self._ellipseInPlane(t, 10.0, 0.5, 0.0).extrude(n * -5).fuse(tube).removeSplitter()
        refused(ring, foot(ring, 10.0, t), 0, 1.0, "runs off its plane all round")
        bank = self._ellipseInPlane(t, 10.0, 6.0, 0.0).extrude(n * 3).cut(
            self._ellipseInPlane(t, 10.0, 1.0, -0.2).extrude(n * 3))
        rising = self._tiltedPlate(t).fuse(bank).fuse(tube).removeSplitter()
        refused(rising, foot(rising, 10.0, t), 0, 1.0, "runs off its face into a wall")
        t1 = math.radians(1)
        plate = self._tiltedPlate(t1)
        plate.translate(V(0, 0, 2))
        pocket = Part.makeCylinder(6.7, 10, V(0.1, 0, -5)).cut(self._tiltedPlate(t1))
        axis = plate.cut(pocket).cut(Part.makeCylinder(6.0, 80, V(0, 0, -40))).removeSplitter()
        refused(axis, foot(axis, 6.0, t1), 1, 0.75, "closed extrusion along the plane's normal")

    def testChamferVaryingAngleCutRunningOffIsRefused(self):
        # Review pr942-r1 A1 (section 3 b): a cut tool (a hole's rim, a convex edge) whose contact
        # runs off its face is not measured against Onshape, so the construction refuses it. T7's
        # hole in a block whose side x = -11 stands 1 mm from the rim at the narrow side: the legs
        # (2 there with Narrowest angle, 4.08 with Widest) run over the side. OCCT fails there too,
        # so the chamfer fails with either value, as it does without this change. With the side at
        # x = -13 the legs stay on the top face: the ball's cut, -72.640 as T7's
        V = FreeCAD.Vector
        R, t = self.R942, self.T942

        def hole(xs):
            block = self._tiltedPlate(t, depth=20).common(Part.makeBox(30 - xs, 60, 80, V(xs, -30, -40)))
            shape = block.cut(Part.makeCylinder(R, 80, V(0, 0, -40))).removeSplitter()
            rim = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                   if e.Curve.TypeId == "Part::GeomEllipse" and abs(e.Curve.MinorRadius - R) < 1e-6
                   and all(abs(p.z - p.x * math.tan(t)) < 1e-6 for p in e.discretize(12))]
            self.assertEqual(len(rim), 1)
            return shape, rim

        shape, rim = hole(-11.0)
        base, chamfer = self._varyingChamfer(shape, 0, rim)
        self.assertFalse(chamfer.isValid())
        chamfer.WidthAt = "Widest angle"
        self.Doc.recompute()
        self.assertFalse(chamfer.isValid())
        self.assertIn("runs off its face", chamfer.getStatusString())
        self.Doc.removeObject("Chamfer")
        self.Doc.removeObject("Body")
        self.Doc.removeObject("Base")
        shape, rim = hole(-13.0)
        base, chamfer = self._varyingChamfer(shape, 0, rim)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self._assertVolume(chamfer.Shape.Volume - shape.Volume, -self._ballVolume(
            self.W942 * math.tan((pi / 2 - t) / 2), 1))

    def testChamferVaryingAngleConeHoleCutRunningOffIsRefused(self):
        # Review pr942-r1 A1 on the cylinder-cone kind: a hole of radius 2 along y through a
        # frustum (radius 30 at z 0, 28 at z 20) at height 17.6, chamfered 1: the cut runs off the
        # cone over the frustum's top rim. Refused, and OCCT fails there too
        V = FreeCAD.Vector
        cone = Part.makeCone(30, 28, 20)
        shape = cone.cut(Part.makeCylinder(2, 40, V(0, 0, 17.6), V(0, 1, 0))).removeSplitter()
        rim = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges) if e.isClosed()
               and e.Curve.TypeId not in ("Part::GeomCircle", "Part::GeomLine")
               and all(abs(math.hypot(p.x, p.z - 17.6) - 2) < 1e-5 for p in e.discretize(12))
               and min(p.y for p in e.discretize(12)) > 20]
        self.assertEqual(len(rim), 1)
        base, chamfer = self._varyingChamfer(shape, 1, rim, size=1.0)
        self.assertFalse(chamfer.isValid())
        self.assertIn("runs off its face", chamfer.getStatusString())
        chamfer.WidthAt = "Narrowest angle"
        self.Doc.recompute()
        self.assertFalse(chamfer.isValid())

    def testChamferVaryingAngleKeepsOtherCases(self):
        # T4: square to the cylinder (t = 0), two distances, and a box edge: WidthAt changes nothing
        V = FreeCAD.Vector
        flat = self._varyingModel("boss", tilt=0.0)
        foot = ["Edge%d" % (i + 1) for i, e in enumerate(flat.Edges)
                if e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Center.z) < 1e-9]
        volumes = []
        for widthAt in (0, 1):
            base, chamfer = self._varyingChamfer(flat, widthAt, foot)
            self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
            volumes.append(chamfer.Shape.Volume - base.Shape.Volume)
            for name in ("Chamfer", "Body", "Base"):
                self.Doc.removeObject(name)
        self.assertAlmostEqual(volumes[0], pi * 4 * (10 + 2 / 3), places=6)
        self.assertEqual(volumes[0], volumes[1])
        base, chamfer = self._varyingChamfer(self._varyingModel("boss"), 0)
        chamfer.ChamferType = "Two distances"
        chamfer.Size2 = self.W942
        self.Doc.recompute()
        twoDistances = chamfer.Shape.Volume
        chamfer.WidthAt = "Widest angle"
        self.Doc.recompute()
        self.assertEqual(chamfer.Shape.Volume, twoDistances)

    def testChamferVaryingAngleConeFallsBack(self):
        # T5: on a cone the construction refuses; Narrowest angle keeps OCCT's chamfer (w on both
        # faces), Widest angle fails with the refusal's text
        base, chamfer = self._varyingChamfer(self._varyingModel("cone"), 0)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        occt = chamfer.Shape.Volume
        chamfer.WidthAt = "Widest angle"
        self.Doc.recompute()
        self.assertFalse(chamfer.isValid())
        self.assertIn("widest", chamfer.getStatusString())
        chamfer.WidthAt = "Narrowest angle"
        self.Doc.recompute()
        self.assertEqual(chamfer.Shape.Volume, occt)

    def testChamferVaryingAngleSeamAndSides(self):
        # T7: the result depends on WidthAt and the geometry only: the base cylinder's seam turned by
        # 37 deg about its axis, and the tilt's sign reversed (the narrow side moves across), give
        # the same volume
        V = FreeCAD.Vector
        R, t = self.R942, self.T942
        expected = self._ballVolume(self.W942 * math.tan((pi / 2 - t) / 2), 1)
        turned = Part.makeCylinder(R, 40, V(0, 0, -20))
        turned.rotate(V(0, 0, 0), V(0, 0, 1), 37)
        shapes = {
            "seam": self._tiltedPlate(t).fuse(turned).removeSplitter(),
            "sign": self._varyingModel("boss", tilt=-t),
        }
        for name, shape in shapes.items():
            with self.subTest(name):
                base, chamfer = self._varyingChamfer(shape, 0)
                self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
                self._assertVolume(chamfer.Shape.Volume - base.Shape.Volume, expected)
                for obj in ("Chamfer", "Body", "Base"):
                    self.Doc.removeObject(obj)

    def testChamferVaryingAngleSavedAndReopened(self):
        # The property keeps its value through save and reopen; a new chamfer's is Narrowest angle
        base, chamfer = self._varyingChamfer(self._varyingModel("boss"), 1)
        self.assertEqual(self.Doc.addObject("PartDesign::Chamfer", "Other").WidthAt, "Narrowest angle")
        volume = chamfer.Shape.Volume
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "varying.FCStd")
            self.Doc.saveAs(path)
            copy = os.path.join(folder, "copy.FCStd")
            shutil.copy(path, copy)
            doc = FreeCAD.openDocument(copy)
            try:
                again = doc.getObject("Chamfer")
                self.assertEqual(again.WidthAt, "Widest angle")
                again.touch()
                doc.recompute()
                self.assertAlmostEqual(again.Shape.Volume, volume, places=6)
            finally:
                FreeCAD.closeDocument(doc.Name)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    # ops#942 section 4 point 12: a hole of radius 3 through the drafted wall of a cone (radius 20 at
    # z 0, the wall leaning in by 10 deg), its axis horizontal at z 10, away from the cone's seam.
    # The rim is a closed edge between the cylinder and the cone; its angle varies round it
    CONE_R0 = 20.0
    CONE_DRAFT = math.radians(10)
    HOLE_R = 3.0

    def _coneWallHoles(self, angles=(90.0,)):
        V = FreeCAD.Vector
        shape = Part.makeCone(self.CONE_R0, self.CONE_R0 - 20 * math.tan(self.CONE_DRAFT), 20)
        for degrees in angles:
            p = math.radians(degrees)
            along = V(math.cos(p), math.sin(p), 0)
            shape = shape.cut(Part.makeCylinder(self.HOLE_R, 20, V(0, 0, 10) + along * 10, along))
        return shape.removeSplitter()

    def _coneWallChamfer(self, width, a=None):
        """The test's own measure of one hole's chamfer (no fork code): the ball of radius
        d = width tan(a / 2) rolled round the rim, at a, or at the narrowest or widest angle
        (a = "narrowest" / "widest"), found by sampling. Its centre at each angle theta about the
        hole's axis lies on that ruling of the cylinder of radius r + d and d inside the cone (by
        Newton); W, L and E are its contacts and the rim's point. The volume of the region between
        the three patches (E W on the cylinder, W L ruled, L E on the cone) by the divergence
        theorem: trapezoid rule in theta (periodic), Gauss in the patches' other parameter.
        Returns (volume, d, a)"""
        r, zc = self.HOLE_R, 10.0
        ta, ca = math.tan(self.CONE_DRAFT), math.cos(self.CONE_DRAFT)

        def off(p):  # signed distance from the cone along its outward normal
            return (math.hypot(p[0], p[1]) - (self.CONE_R0 - p[2] * ta)) * ca

        def normal(p):
            rho = math.hypot(p[0], p[1])
            return (p[0] / rho * ca, p[1] / rho * ca, ta * ca)

        def ruling(theta, radius, target):
            # the point at angle theta about the hole's axis (+y through (0, 0, zc))
            x, z, y = radius * math.cos(theta), zc + radius * math.sin(theta), 18.0
            for _ in range(80):
                f = off((x, y, z)) - target
                slope = (off((x, y + 1e-7, z)) - off((x, y - 1e-7, z))) / 2e-7
                step = f / slope
                y -= step
                if abs(step) < 1e-14:
                    break
            return (x, y, z)

        def angleAt(theta):
            n0 = (-math.cos(theta), 0.0, -math.sin(theta))  # the hole wall's outward normal
            n1 = normal(ruling(theta, r, 0.0))
            return pi - math.acos(max(-1.0, min(1.0, sum(p * q for p, q in zip(n0, n1)))))

        if a in ("narrowest", "widest"):
            angles = [angleAt(2 * pi * k / 3600) for k in range(3600)]
            a = min(angles) if a == "narrowest" else max(angles)
        d = width * math.tan(a / 2)

        def points(theta):
            e = ruling(theta, r, 0.0)
            c = ruling(theta, r + d, -d)
            n = normal(c)
            return e, (r * math.cos(theta), c[1], zc + r * math.sin(theta)), \
                tuple(ci + d * ni for ci, ni in zip(c, n))

        def onCone(p):
            n, f = normal(p), off(p)
            return tuple(pi_ - f * ni for pi_, ni in zip(p, n))

        def patch(e, w, l, v, k):
            if k == 0:
                return tuple((1 - v) * p + v * q for p, q in zip(e, w))
            if k == 1:
                return tuple((1 - v) * p + v * q for p, q in zip(w, l))
            return onCone(tuple((1 - v) * p + v * q for p, q in zip(l, e)))

        nodes = (-0.9324695142, -0.6612093865, -0.2386191861, 0.2386191861, 0.6612093865,
                 0.9324695142)
        weights = (0.1713244924, 0.3607615730, 0.4679139346, 0.4679139346, 0.3607615730,
                   0.1713244924)
        stations, h, dv = 720, 1e-5, 1e-6
        total = 0.0
        for i in range(stations):
            theta = 2 * pi * i / stations
            at, before, after = points(theta), points(theta - h), points(theta + h)
            for node, weight in zip(nodes, weights):
                v = (node + 1) / 2
                for k in range(3):
                    X = patch(*at, v, k)
                    Xt = [(p - q) / (2 * h) for p, q in zip(patch(*after, v, k), patch(*before, v, k))]
                    Xv = [(p - q) / (2 * dv) for p, q in zip(patch(*at, v + dv, k), patch(*at, v - dv, k))]
                    cross = (Xt[1] * Xv[2] - Xt[2] * Xv[1], Xt[2] * Xv[0] - Xt[0] * Xv[2],
                             Xt[0] * Xv[1] - Xt[1] * Xv[0])
                    total += sum(p * q for p, q in zip(X, cross)) * weight / 2 * (2 * pi / stations)
        return abs(total) / 3, d, a

    def testChamferVaryingAngleConeWallHole(self):
        # Section 4 point 12: the rim of a hole through a drafted wall, the ball outside the hole
        # and inside the cone. With Narrowest angle (77.86 deg) and Widest angle (100 deg) the
        # material cut off is the test's own integral; one face more, ruled between the ball's
        # contacts, which lie on the hole's cylinder and on the cone
        shape = self._coneWallHoles()
        for widthAt, which in ((0, "narrowest"), (1, "widest")):
            with self.subTest(which):
                base, chamfer = self._varyingChamfer(shape, widthAt, size=1.0)
                self.assertEqual(len(chamfer.Base[1]), 1)
                self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
                result = chamfer.Shape
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Faces), len(shape.Faces) + 1)
                expected, d, a = self._coneWallChamfer(1.0, which)
                # The cut alone (the body's measure is good to about 4e-7 of its 20700 mm3)
                self.assertLess(result.cut(shape).Volume, 1e-6)
                self._assertVolume(shape.cut(result).Volume, expected)
                new = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomBSplineSurface"]
                self.assertEqual(len(new), 1)
                ta = math.tan(self.CONE_DRAFT)
                rails = [e for e in new[0].Edges if not e.isSeam(new[0])]
                self.assertEqual(len(rails), 2)
                onHole = onCone = 0
                for edge in rails:
                    samples = [edge.valueAt(edge.FirstParameter + (edge.LastParameter
                               - edge.FirstParameter) * k / 16) for k in range(16)]
                    if all(abs(math.hypot(p.x, p.z - 10) - self.HOLE_R) < 1e-6 for p in samples):
                        onHole += 1
                    elif all(abs(math.hypot(p.x, p.y) - (self.CONE_R0 - p.z * ta)) < 1e-6
                             for p in samples):
                        onCone += 1
                self.assertEqual((onHole, onCone), (1, 1))
                for name in ("Chamfer", "Body", "Base"):
                    self.Doc.removeObject(name)

    def testChamferVaryingAngleSeveralEdges(self):
        # Section 4 point 12: four holes round the cone, each rim a closed edge of its own: one tool
        # each, four times one hole's cut. With At a reference point, one point per edge in the
        # selection's order (each at its hole's lowest point, the widest angle); the same points in
        # another order lie far from the edges they are for, and the chamfer fails
        V = FreeCAD.Vector
        shape = self._coneWallHoles((45.0, 135.0, 225.0, 315.0))
        base, chamfer = self._varyingChamfer(shape, 0, size=1.0)
        self.assertEqual(len(chamfer.Base[1]), 4)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        result = chamfer.Shape
        self.assertEqual(len(result.Faces), len(shape.Faces) + 4)
        one, d, a = self._coneWallChamfer(1.0, "narrowest")
        self._assertVolume(shape.cut(result).Volume, 4 * one)
        wide, d, a = self._coneWallChamfer(1.0, "widest")
        lowest = []
        for name in chamfer.Base[1]:
            edge = base.Shape.getElement(name)
            low = min((edge.valueAt(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter)
                                    * k / 720) for k in range(720)), key=lambda p: p.z)
            lowest.append(low)
        chamfer.WidthAt = "At a reference point"
        chamfer.WidthPoints = lowest
        self.Doc.recompute()
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertLess(abs(shape.cut(chamfer.Shape).Volume - 4 * wide), 1e-4 * wide)
        chamfer.WidthPoints = lowest[1:] + lowest[:1]
        self.Doc.recompute()
        self.assertFalse(chamfer.isValid())
        self.assertIn("the reference point for edge 1 is", chamfer.getStatusString())

    def testChamferVaryingAngleAtAReferencePoint(self):
        # Section 4 points 8-10 on T1: a point at the narrow side gives Narrowest angle's chamfer, one
        # at the wide side Widest angle's; one 1.5 off the narrow side (within w) still the narrow
        # station's. Fails, with the message: a point further than w, no point, two for one edge
        V = FreeCAD.Vector
        R, t = self.R942, self.T942
        narrow = self._ballVolume(self.W942 * math.tan((pi / 2 - t) / 2), 1)
        wide = self._ballVolume(self.W942 * math.tan((pi / 2 + t) / 2), 1)
        base, chamfer = self._varyingChamfer(self._varyingModel("boss"), 0)
        edgeAt = V(R, 0, R * math.tan(t))
        for points, expected in (([edgeAt], narrow), ([V(-R, 0, -R * math.tan(t))], wide),
                                 ([edgeAt + V(1.5, 0, 0)], narrow)):
            with self.subTest(points):
                chamfer.WidthAt = "At a reference point"
                chamfer.WidthPoints = points
                self.Doc.recompute()
                self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
                self._assertVolume(chamfer.Shape.Volume - base.Shape.Volume, expected)
        for points, words in (([edgeAt + V(5, 0, 0)], "mm from it"), ([], "0 reference points"),
                              ([edgeAt, edgeAt], "2 reference points")):
            with self.subTest(points):
                chamfer.WidthPoints = points
                self.Doc.recompute()
                self.assertFalse(chamfer.isValid())
                self.assertIn(words, chamfer.getStatusString())

    def testChamferVaryingAngleOutsideTheGate(self):
        # Section 4 point 10: a varying edge picked with a straight edge is outside the gate: with
        # Narrowest angle OCCT's chamfer stands, with Widest angle it fails, saying why
        shape = self._varyingModel("boss")
        foot = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                if e.Curve.TypeId == "Part::GeomEllipse"]
        line = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges)
                if e.Curve.TypeId == "Part::GeomLine"
                and all(abs(v.Point.x) > 29 for v in e.Vertexes)][:1]
        base, chamfer = self._varyingChamfer(shape, 0, foot + line)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        chamfer.WidthAt = "Widest angle"
        self.Doc.recompute()
        self.assertFalse(chamfer.isValid())
        self.assertIn("closed edge of its own", chamfer.getStatusString())

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestChamfer")
        # print ("omit closing document for debugging")
