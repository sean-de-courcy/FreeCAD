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

from __future__ import division
from math import pi
import unittest

import FreeCAD
import Part


class TestFillet(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestFillet")

    def _create_box_with_fillet(self):
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        box.Length = 10.00
        box.Width = 10.00
        box.Height = 10.00
        body.addObject(box)
        self.Doc.recompute()

        fillet = self.Doc.addObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (box, ["Edge1"])
        fillet.Radius = 1.0
        body.addObject(fillet)
        self.Doc.recompute()
        self.assertTrue(fillet.isValid())
        return body, box, fillet

    def _find_edge_with_match_count(self, source_shape, target_shape, match_count):
        for index in range(1, source_shape.countElement("Edge") + 1):
            source_name = "Edge" + str(index)
            source_edge = source_shape.getElement(source_name, True)
            matches = target_shape.findSubShapesWithSharedVertex(
                source_edge,
                needName=True,
                checkGeometry=True,
            )
            if len(matches) == match_count:
                return source_name, matches[0][0] if matches else None
        self.skipTest("Test model did not contain a suitable edge")

    def testFilletCubeToSphere(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Box = self.Doc.addObject("PartDesign::AdditiveBox", "Box")
        self.Body.addObject(self.Box)
        self.Box.Length = 10.00
        self.Box.Width = 10.00
        self.Box.Height = 10.00
        self.Doc.recompute()
        self.Fillet = self.Doc.addObject("PartDesign::Fillet", "Fillet")
        self.Fillet.Base = (self.Box, ["Face" + str(i + 1) for i in range(6)])
        self.Fillet.Radius = 4.999999
        self.Body.addObject(self.Fillet)
        self.Doc.recompute()
        self.assertAlmostEqual(self.Fillet.Shape.Volume, 4 / 3 * pi * 5**3, places=3)
        # test UseAllEdges property
        self.Fillet.UseAllEdges = True
        self.Fillet.Base = (self.Box, [""])  # no subobjects, should still work
        self.Doc.recompute()
        self.assertAlmostEqual(self.Fillet.Shape.Volume, 4 / 3 * pi * 5**3, places=3)
        self.Fillet.Base = (self.Box, ["Face50"])  # non-existent face, topo naming resilience
        self.Doc.recompute()
        self.assertAlmostEqual(self.Fillet.Shape.Volume, 4 / 3 * pi * 5**3, places=3)
        self.Fillet.UseAllEdges = False
        self.Fillet.Base = (self.Box, ["Face1"])
        self.Doc.recompute()
        self.assertNotAlmostEqual(self.Fillet.Shape.Volume, 4 / 3 * pi * 5**3, places=3)

    def testDeletingPreviousFeatureRelinksUniqueMatchingBaseEdge(self):
        body, box, fillet = self._create_box_with_fillet()
        old_edge, new_edge = self._find_edge_with_match_count(fillet.Shape, box.Shape, 1)

        followup = self.Doc.addObject("PartDesign::Fillet", "FollowupFillet")
        followup.Base = (fillet, [old_edge])
        followup.Radius = 0.25
        body.addObject(followup)
        self.Doc.recompute()
        self.assertTrue(followup.isValid())

        body.removeObject(fillet)

        self.assertEqual(followup.Base[0].Name, box.Name)
        self.assertEqual(list(followup.Base[1]), [new_edge])

    def testDeletingPreviousFeatureDoesNotRelinkUnsafeBaseEdge(self):
        body, box, fillet = self._create_box_with_fillet()
        old_edge, _new_edge = self._find_edge_with_match_count(fillet.Shape, box.Shape, 0)

        followup = self.Doc.addObject("PartDesign::Fillet", "FollowupFillet")
        followup.Base = (fillet, [old_edge])
        followup.Radius = 0.25
        body.addObject(followup)
        self.Doc.recompute()

        body.removeObject(fillet)

        if followup.Base[0]:
            self.assertNotEqual(followup.Base[0].Name, box.Name)

    # Fillets that OCCT makes with tolerances above Precision::Confusion(): the result must be a
    # valid solid with the volume the geometry gives, and the base feature's shape must stay
    # valid with no tolerance lowered (ops#12: limiting every tolerance to Precision::Confusion()
    # turned valid fillets into invalid solids, and lowered tolerances of sub-shapes shared with
    # the base shape). OCCT itself may raise the tolerance of a shared vertex.

    # Area between a square corner and the quarter circle of radius r inscribed in it
    @staticmethod
    def _fillet_section(r):
        return (1 - pi / 4) * r**2

    # Distance of that section's centroid from either side of the corner
    @staticmethod
    def _fillet_section_centroid(r):
        return r * (10 - 3 * pi) / (12 - 3 * pi)

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

    def _add_fillet(self, body, base, edges, radius):
        fillet = self.Doc.addObject("PartDesign::Fillet", "Fillet")
        body.addObject(fillet)
        fillet.Base = (base, edges)
        fillet.Radius = radius
        self.Doc.recompute()
        return fillet

    @staticmethod
    def _tolerances(shape):
        return [s.Tolerance for s in shape.Vertexes + shape.Edges + shape.Faces]

    def _assertValidFillet(self, fillet, volume):
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        shape = fillet.Shape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, places=3)

    def _assertBaseKept(self, base, tolerances):
        self.assertTrue(base.Shape.isValid())
        for after, before in zip(self._tolerances(base.Shape), tolerances, strict=True):
            self.assertGreaterEqual(after, before)

    def testFilletEndingAgainstFace(self):
        # A step: the lower block's front top edge ends against the riser at x = 20
        for radius in (1.0, 3.0, 6.0):
            with self.subTest(radius=radius):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                self._add_box(body, 40, 20, 10)
                step = self._add_box(body, 20, 20, 20)
                tolerances = self._tolerances(step.Shape)
                edge = self._edge_between(step.Shape, (20, 0, 10), (40, 0, 10))
                fillet = self._add_fillet(body, step, [edge], radius)
                self._assertValidFillet(fillet, 12000 - self._fillet_section(radius) * 20)
                self._assertBaseKept(step, tolerances)

    def testSuccessiveFilletsMeetingAtVertex(self):
        # Box 20 x 20 x 10. The first fillet rounds the front top edge (radius r1). The second
        # (radius r2 <= r1) rounds the right top edge, which is tangent to the first fillet's arc
        # on the right face, which is tangent to the front right edge: the fillet follows all
        # three. Along the arc the removed section turns about the first fillet's axis at the
        # distance r1 - centroid (Pappus).
        for r1, r2 in ((2.0, 2.0), (3.0, 2.0)):
            with self.subTest(r1=r1, r2=r2):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                box = self._add_box(body, 20, 20, 10)
                front = self._edge_between(box.Shape, (0, 0, 10), (20, 0, 10))
                first = self._add_fillet(body, box, [front], r1)
                volume1 = 4000 - self._fillet_section(r1) * 20
                self._assertValidFillet(first, volume1)
                tolerances = self._tolerances(first.Shape)
                edge = self._edge_between(first.Shape, (20, r1, 10), (20, 20, 10))
                second = self._add_fillet(body, first, [edge], r2)
                path = (20 - r1) + (10 - r1)
                arc = pi / 2 * (r1 - self._fillet_section_centroid(r2))
                self._assertValidFillet(second, volume1 - self._fillet_section(r2) * (path + arc))
                self._assertBaseKept(first, tolerances)

    def testFilletAroundRoundedCorners(self):
        # The shape of the report: a block 2a x 2a x h with its vertical corners filleted
        # (radius R), then a small fillet (radius r) on one bottom edge. The bottom edges and the
        # corner arcs are tangent, so the fillet runs around the whole bottom; along each arc
        # the section turns about the corner's axis (Pappus).
        a, h, R, r = 50.8, 22.225, 11.3125, 1.5875
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = self._add_box(body, 2 * a, 2 * a, h, (-a, -a, 0))
        corners = [
            self._edge_between(box.Shape, (x, y, 0), (x, y, h)) for x in (-a, a) for y in (-a, a)
        ]
        rounded = self._add_fillet(body, box, corners, R)
        volume1 = (4 * a * a - 4 * self._fillet_section(R)) * h
        self._assertValidFillet(rounded, volume1)
        tolerances = self._tolerances(rounded.Shape)
        edge = self._edge_between(rounded.Shape, (-a + R, -a, 0), (a - R, -a, 0))
        bottom = self._add_fillet(body, rounded, [edge], r)
        path = 4 * (2 * a - 2 * R) + 4 * pi / 2 * (R - self._fillet_section_centroid(r))
        self._assertValidFillet(bottom, volume1 - self._fillet_section(r) * path)
        self._assertBaseKept(rounded, tolerances)

    def testFilletConsumingWholeFaceFails(self):
        # Known OCCT limitation (checked on OCCT 8.0.1): two fillets whose radius is half the
        # width of the face between them leave nothing of it, and OCCT fails. The feature must
        # report the error rather than produce a shape. If this starts to pass, OCCT has changed.
        body = self.Doc.addObject("PartDesign::Body", "Body")
        box = self._add_box(body, 30, 4, 20)
        edges = [
            self._edge_between(box.Shape, (0, 0, 20), (30, 0, 20)),
            self._edge_between(box.Shape, (0, 4, 20), (30, 4, 20)),
        ]
        fillet = self._add_fillet(body, box, edges, 1.9)
        self._assertValidFillet(fillet, 30 * 4 * 20 - 2 * self._fillet_section(1.9) * 30)
        fillet.Radius = 2.0
        self.Doc.recompute()
        self.assertFalse(fillet.isValid())
        self.assertTrue(box.Shape.isValid())

    # Results that the full check rejects too (ops#12): the base is a 10 mm cube with a fin, a
    # face hanging inward at 45 degrees from the front bottom edge, so that three faces meet at
    # the edge. The fillet on the back top edge keeps the fin, and its result is invalid. The
    # feature repairs it on a copy, or fails with "Resulting shape is invalid" as up to 0.21.

    def _add_cube_with_fin(self, body, closed=True, bottom_on_own_edges=False):
        V = FreeCAD.Vector
        cube = Part.makeBox(10, 10, 10)
        edge = cube.getElement(self._edge_between(cube, (0, 0, 0), (10, 0, 0)))
        p0, p1, q0, q1 = V(0, 0, 0), V(10, 0, 0), V(0, 5, 5), V(10, 5, 5)
        sides = [edge, Part.makeLine(p1, q1), Part.makeLine(q1, q0)]
        if closed:
            fin = Part.Face(Part.Wire(sides + [Part.makeLine(q0, p0)]))
        else:
            # Three sides of the square: a boundary with a 7 mm gap, which no repair closes
            fin = Part.Face(Part.Plane(p0, p1, q0), Part.Wire(sides))
        bottom = next(face for face in cube.Faces if face.CenterOfMass.z < 1e-6)
        if bottom_on_own_edges:
            new_bottom = bottom.copy()
        else:
            # The same face on the same edges; a new face, so that the replacement keeps it
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

    def testFilletRepairsInvalidResult(self):
        # A closed fin: the repair gives a valid solid, the filleted cube
        body = self.Doc.addObject("PartDesign::Body", "Body")
        base = self._add_cube_with_fin(body)
        edge = self._edge_between(base.Shape, (0, 10, 10), (10, 10, 10))
        fillet = self._add_fillet(body, base, [edge], 1.0)
        self._assertValidFillet(fillet, 1000 - self._fillet_section(1.0) * 10)

    def testFilletUnrepairableResultFails(self):
        # An open fin: the repair can't close its boundary
        body = self.Doc.addObject("PartDesign::Body", "Body")
        base = self._add_cube_with_fin(body, closed=False)
        edge = self._edge_between(base.Shape, (0, 10, 10), (10, 10, 10))
        fillet = self._add_fillet(body, base, [edge], 1.0)
        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.getStatusString(), "Resulting shape is invalid")

    def testFilletRepairLosingSolidFails(self):
        # A closed fin with the bottom face on edges of its own: the repair gives a valid shape
        # with no solid, which the feature doesn't take as a repair
        body = self.Doc.addObject("PartDesign::Body", "Body")
        base = self._add_cube_with_fin(body, bottom_on_own_edges=True)
        edge = self._edge_between(base.Shape, (0, 10, 10), (10, 10, 10))
        fillet = self._add_fillet(body, base, [edge], 1.0)
        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.getStatusString(), "Resulting shape is invalid")

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestFillet")
        # print ("omit closing document for debugging")
