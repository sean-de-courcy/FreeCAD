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
import math
import unittest

import FreeCAD
import Part
from parttests import FilletFallbackTest as models


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

    def testDeletingPreviousFeatureRelinksTrimmedBaseEdgeToFullEdge(self):
        # FreeCAD-CH (ops#7 Q7): upstream's testDeletingPreviousFeatureDoesNotRelinkUnsafeBaseEdge
        # expects no relink. With the reference solver, on in new documents, a dress-up on an
        # edge that the deleted feature trimmed follows the base's full edge.
        body, box, fillet = self._create_box_with_fillet()
        self.assertTrue(self.Doc.ReferenceSolver)
        # The fillet on the box's Edge1 shortens the four box edges that meet it by its radius.
        trimmed = next(
            index + 1
            for index, edge in enumerate(fillet.Shape.Edges)
            if isinstance(edge.Curve, Part.Line) and abs(edge.Length - 9.0) < 1e-6
        )
        trimmed_edge = fillet.Shape.Edges[trimmed - 1]
        full = [
            "Edge" + str(index + 1)
            for index, edge in enumerate(box.Shape.Edges)
            if all(edge.distToShape(vertex)[0] < 1e-6 for vertex in trimmed_edge.Vertexes)
        ]
        self.assertEqual(len(full), 1)

        followup = self.Doc.addObject("PartDesign::Fillet", "FollowupFillet")
        followup.Base = (fillet, ["Edge" + str(trimmed)])
        followup.Radius = 0.25
        body.addObject(followup)
        self.Doc.recompute()
        self.assertTrue(followup.isValid())

        body.removeObject(fillet)

        self.assertEqual(followup.Base[0].Name, box.Name)
        self.assertEqual(list(followup.Base[1]), full)
        self.Doc.recompute()
        self.assertTrue(followup.isValid())

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
        # Neither lowered by a repair (ops#12) nor raised by OCCT's maker, which runs on a copy
        # (ops#345)
        self.assertTrue(base.Shape.isValid())
        self.assertEqual(self._tolerances(base.Shape), tolerances)

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
        # A block 2a x 2a x h with its vertical corners filleted (radius R), then a small fillet
        # (radius r) on one bottom edge. The bottom edges and the corner arcs are tangent, so the
        # fillet runs around the whole bottom; along each arc the section turns about the
        # corner's axis (Pappus). Volumes 198283.185307, then 198099.349866.
        a, h, R, r = 50.0, 20.0, 10.0, 1.5
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

    def testFilletConsumingWholeFace(self):
        # OCCT (8.0.1) fails when two fillets whose radius is half the width of the face between
        # them leave nothing of it; the exact construction builds the full round (ops#300)
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
        self._assertValidFillet(fillet, 30 * 4 * 20 - 2 * self._fillet_section(2.0) * 30)
        # The two quarter cylinders are one half cylinder, refined or not (ops#900)
        self.assertEqual(len(fillet.Shape.Faces), 6)

    def testFilletFullRoundOfAWallFlushWithItsBase(self):
        # ops#640 F1 (the replica's row 150): a curved wall's end flush with its base's end, the two
        # left as faces in one plane, so four edges meet at the foot of each rounded edge. The
        # feature builds the full round at half the wall: FR1's section over the wall's height
        shape, edges = models.curved_wall_on_base()
        _, removed, side = models.wall_end_round(10, 11.5, 4)
        fillet = self._fillet_on_base(shape, edges, 0.75)
        self._assertValidFillet(fillet, shape.Volume - removed)
        self.assertAlmostEqual(fillet.Shape.Area, shape.Area - side, places=5)
        # Refined, as Onshape's: the base's faces without its splits, and one half cylinder
        self.assertTrue(fillet.Refine)
        self.assertEqual(len(fillet.Shape.Faces), len(shape.removeSplitter().Faces) + 1)

    def testFilletFullRoundOfAWallFlushOnAChamferedRim(self):
        # ops#640 (the replica's #150): a wall's outer face flush with a plate's chamfered rim, so
        # four edges and four faces meet at each outer foot, the rim's cone one of them. The
        # feature builds FR1's round at each end of the wall and leaves the plate as it was
        shape, edges, inner, outer = models.wall_on_a_chamfered_rim()
        _, removed, _ = models.wall_end_round(inner, outer, 4.0)
        fillet = self._fillet_on_base(shape, edges, (outer - inner) / 2)
        self._assertValidFillet(fillet, shape.Volume - 2 * removed)
        below = Part.makeBox(40, 40, 1.5, FreeCAD.Vector(-20, -20, -1.5))
        self.assertAlmostEqual(
            fillet.Shape.common(below).Volume, shape.common(below).Volume, places=6
        )
        # The closed form of FilletFallbackTest.WallOnAChamferedRimTest: faces 13 -> 13,
        # A 1281.195348 -> 1276.034170, the cone's area 68.309325 unchanged
        result = fillet.Shape
        self.assertEqual(len(result.Faces), 13)
        self.assertAlmostEqual(result.Area, 1276.034170, delta=1e-6 * 1276.034170)
        cone = sum(f.Area for f in result.Faces if f.Surface.TypeId == "Part::GeomCone")
        self.assertAlmostEqual(cone, 68.309325, delta=1e-6 * 68.309325)

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

    # Invalid results that OCCT (8.0.1) returns without an error (ops#297), on the models of
    # parttests.FilletFallbackTest. The exact construction builds them where it can (at the
    # limit); the feature repairs the others only if the repair keeps the solids and the faces,
    # or fails.

    def _fillet_on_base(self, shape, edges, radius, allow_compound=False):
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
        return self._add_fillet(body, body.BaseFeature, names, radius)

    def _assertFails(self, fillet):
        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.getStatusString(), "Resulting shape is invalid")

    def testFilletLeavesTheBaseTolerancesAlone(self):
        # The rib's top edges rounded, ending against the wall: OCCT's maker raises its input's
        # vertices there to 1e-4, and the base feature's stored shape shares them. The maker runs
        # on a copy; the result keeps what it raised (ops#345)
        rib, _ = models.rib_against_wall()
        tolerances = self._tolerances(rib)
        self.assertLess(max(tolerances), 1e-6)
        fillet = self._fillet_on_base(rib, models.top_edges(rib), 1.5)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self._assertBaseKept(self.Doc.getObject("Base"), tolerances)
        self.assertGreater(max(self._tolerances(fillet.Shape)), 1e-5)

    def testFilletInvalidOcctResultAtLimit(self):
        # A round as wide as a rib's top, against a wall: OCCT's result is invalid; the exact
        # construction builds it
        rib, edges = models.rib_against_wall()
        fillet = self._fillet_on_base(rib, edges, 4.0)
        self._assertValidFillet(fillet, 4800 - self._fillet_section(4.0) * 30)

    def testFilletOverlongFullRoundFails(self):
        # Just over the full round of a disk's rims, OCCT returns two invalid solids with
        # three quarters more volume, which the feature stored with Allow Compound on
        disk, rims = models.disk()
        fillet = self._fillet_on_base(disk, rims, 1.00001, allow_compound=True)
        self._assertFails(fillet)
        fillet.Radius = 1.0
        self.Doc.recompute()
        c = self._fillet_section_centroid(1.0)
        self._assertValidFillet(
            fillet, 200 * pi - 2 * self._fillet_section(1.0) * 2 * pi * (10 - c)
        )

    def testFilletOverlappingRoundsFail(self):
        # Rounds of 2.65 on two edges 4 apart overlap on the face between them, and no fillet
        # exists. OCCT's result has a self-intersecting wire, which the repair turned into a
        # valid solid with two more faces: on the block, on a large block (where the faces'
        # total area hardly changes), and on a base made invalid elsewhere
        block, edges = models.notched_block()
        self._assertFails(self._fillet_on_base(block, edges, 2.65))
        block, edges = models.notched_block(0.1, (1000, 1000, 1))
        self._assertFails(self._fillet_on_base(block, edges, 0.265))
        block, edges = models.notched_block()
        base = models.with_back_face_reversed(block)
        edges = [
            models.edge_between(base, e.Vertexes[0].Point, e.Vertexes[-1].Point) for e in edges
        ]
        self._assertFails(self._fillet_on_base(base, edges, 2.65))

    def testRoundOnASplineSupportIsTheBallsContact(self):
        # ops#640, decision 425: a round is the surface a ball of its radius sweeps while it
        # touches both walls. On a twisted B-spline lid OCCT's fillet (a circle in the plane
        # normal to the edge) is 3.6e-3 off that, and its seams 0.07. The corpus model
        # RoundOnSpline states the contact in closed form and raises when it is missed
        from PartDesignTests.Compat import models  # first: it imports models_partdesign
        from PartDesignTests.Compat import models_partdesign as corpus

        models.MODELS["RoundOnSpline"](FreeCAD.newDocument)
        document = FreeCAD.getDocument("RoundOnSpline")
        self.addCleanup(FreeCAD.closeDocument, "RoundOnSpline")
        fillet = document.getObject("RimRound")
        self.assertTrue(fillet.isValid())
        self.assertTrue(fillet.Shape.isValid())
        self.assertEqual(len(fillet.Shape.Faces), 10)
        faces, ball, seam, seams = corpus.roundOnSplineContact(
            fillet, corpus.ROUND_ON_SPLINE_TWIST, corpus.ROUND_ON_SPLINE_RADIUS, grid=33
        )
        self.assertEqual((faces, seams), (4, 4))
        self.assertLess(ball, 1e-6)
        self.assertLess(seam, 1e-6)
        # The round takes less than the plane-normal circle's: between the stadium's prism
        # under the lid (its volume is 20 times the stadium's area: x y integrates to zero)
        # and that prism less a quarter-round bead of the rim's length
        prism = 20 * (40 * 20 + pi * 100)
        self.assertLess(fillet.Shape.Volume, prism)
        self.assertGreater(fillet.Shape.Volume, prism - 2 * (1 - pi / 4) * 1.5**2 * (80 + 20 * pi))

    def testRoundUnderALeaningWallIsTheBallsContact(self):
        # ops#640, decision 425: a round's chain of cylinders and spline faces (a leaning stadium
        # boss on a slab; Nest Insert's slot round). The cylinders under the leaning planes are
        # the ball's already and stay; the faces under the leaning circles' walls, 5e-3 off as
        # OCCT builds them, become the ball's. The corpus model RoundUnderLeaningWall states the
        # contact in closed form and raises when it is missed
        from PartDesignTests.Compat import models  # first: it imports models_partdesign
        from PartDesignTests.Compat import models_partdesign as corpus

        models.MODELS["RoundUnderLeaningWall"](FreeCAD.newDocument)
        document = FreeCAD.getDocument("RoundUnderLeaningWall")
        self.addCleanup(FreeCAD.closeDocument, "RoundUnderLeaningWall")
        fillet = document.getObject("FootRound")
        self.assertTrue(fillet.isValid())
        self.assertTrue(fillet.Shape.isValid())
        self.assertEqual(len(fillet.Shape.Faces), 15)
        cylinders, others, ball = corpus.roundUnderLeaningWallContact(
            fillet, corpus.LEANING_BOSS_RADIUS, grid=25
        )
        self.assertEqual((cylinders, others), (2, 2))
        self.assertLess(ball, 1e-6)
        # The round adds material at the boss's foot: more than the slab and the leaning boss
        # (30 high over the stadium's area, less the 5 inside the slab), less than those with a
        # quarter-round bead of twice the foot's length
        base = 100 * 70 * 5 + 25 * (40 * 20 + pi * 100)
        self.assertGreater(fillet.Shape.Volume, base)
        self.assertLess(fillet.Shape.Volume, base + 2 * (1 - pi / 4) * 2.0**2 * (80 + 20 * pi))

    def testFilletWholeOutlineOfAStadium(self):
        # ops#298: OCCT "succeeds" on a stadium's whole top outline at r = 2 (half its width),
        # keeping the top face with area 0; the exact construction builds the full round. Just
        # below, a top narrower than its tolerance is built the same way, and a sliver 2e-7
        # wide (twice its tolerance) is OCCT's correct result
        plate, outline = models.fused_stadium()
        fillet = self._fillet_on_base(plate, outline, 2.0)
        self._assertValidFillet(fillet, models.fused_stadium_rounded(2))
        self.assertGreater(models.narrowest(fillet.Shape, plate), 0.5)
        for radius, width in ((2 - 1e-8, 0.5), (2 - 1e-7, 1e-7)):
            fillet.Radius = radius
            self.Doc.recompute()
            self._assertValidFillet(fillet, models.fused_stadium_rounded(radius))
            self.assertGreater(models.narrowest(fillet.Shape, plate), width)

    def testFilletCoincidentCases(self):
        # Section 1 of the design note: OCCT fails at each of these limits; the feature gets the
        # exact construction's result with the analytic volume. A plate's edge at its thickness,
        # a column's four edges (a cylinder), a cube's twelve (a sphere: eight corners) and a
        # tube's two rims (a toroidal full round)
        plate = Part.makeBox(30, 20, 4)
        edge = models.edge_between(plate, (0, 0, 4), (30, 0, 4))
        self._assertValidFillet(
            self._fillet_on_base(plate, [edge], 4.0), 2400 - self._fillet_section(4) * 30
        )
        column = Part.makeBox(4, 4, 20)
        vertical = [e for e in column.Edges if e.BoundBox.ZLength > 1]
        self._assertValidFillet(self._fillet_on_base(column, vertical, 2.0), pi * 4 * 20)
        cube = Part.makeBox(4, 4, 4)
        self._assertValidFillet(self._fillet_on_base(cube, cube.Edges, 2.0), 4 / 3 * pi * 8)
        tube = Part.makeCylinder(10, 10).cut(Part.makeCylinder(6, 10))
        rims = [e for e in tube.Edges if e.BoundBox.ZMin > 9.9]
        c = self._fillet_section_centroid(2)
        rounds = self._fillet_section(2) * 2 * pi * ((10 - c) + (6 + c))
        self._assertValidFillet(self._fillet_on_base(tube, rims, 2.0), pi * 64 * 10 - rounds)

    def testFilletRepairKeepingTheSurface(self):
        # Four rounds meeting at a pyramid's apex: OCCT's faces are misoriented; the repair
        # reorients them. Rounds along the full length of the edges remove a little more
        solid, edges = models.pyramid()
        fillet = self._fillet_on_base(solid, edges, 1.0)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertTrue(fillet.Shape.isValid())
        removed = 4000 / 3 - fillet.Shape.Volume
        self.assertLess(removed, models.pyramid_edge_rounds(1))
        self.assertGreater(removed, 0.98 * models.pyramid_edge_rounds(1))

    def testFilletDropsTheLoosePartsOfABaseFeature(self):
        # With Allow Compound, a BaseFeature of a cube beside loose parts: the Fillet keeps solids
        # and shells only, as OCCT returns them, and a Pad on its top works (ops#303; PR 341
        # review: the Pad failed with "Null shape" on a Fillet that kept a loose face)
        pad = models.pad_on_dressed_up_base(self.Doc, "Fillet", 1.0)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        fillet = self.Doc.getObject("Fillet")
        self.assertEqual(models.loose_parts(fillet.Shape), ([], [], []))
        volume = sum(s.Volume for s in pad.Shape.Solids)
        self.assertAlmostEqual(volume, 1000 - self._fillet_section(1) * 10 + 48, delta=1e-6)

    def testFilletAcrossAPocketFillsNothing(self):
        # A round of 3 on the front top edge of a 10 mm cube whose top has a pocket 4 x 1 x 2 at
        # (3, 1.5, 8): OCCT covers the pocket's opening and fills it under the round (980.686 for
        # the Boolean construction's 973.439). The Fillet is that construction, or fails naming
        # the edge (ops#393)
        recess = Part.makeBox(4, 1, 2, FreeCAD.Vector(3, 1.5, 8))
        fillet, edge = models.dressed_up_in_a_body(self.Doc, "Fillet", recess, 3)
        removed = models.front_top_removed("Fillet", 3)
        expected = Part.makeBox(10, 10, 10).cut(removed).cut(recess).Volume
        if fillet.isValid():
            self.assertAlmostEqual(fillet.Shape.Volume, expected, delta=1e-6)
        else:
            message = "The fillet fills a recess of the base next to %s:" % edge
            self.assertTrue(fillet.getStatusString().startswith(message), fillet.getStatusString())

    def testFilletOntoATangentRound(self):
        # A round of 2 on the concave edge of an L whose floor ends in a round R4: its band runs on
        # onto that round, and the material it adds there is the corner's (722.942; PR 346 review,
        # H1: the Fillet failed with "fills a recess")
        base = models.rounded_concave_block()
        ends = ((0, 5, 5), (10, 5, 5))
        fillet, _ = models.dressed_in_a_body(self.Doc, "Fillet", base, ends, 2)
        expected = base.fuse(models.concave_added_onto_round("Fillet", 2)).Volume
        self.assertAlmostEqual(expected, 722.942091, delta=1e-5)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertAlmostEqual(fillet.Shape.Volume, expected, delta=1e-5)

    def testFilletOverASmoothDimpleFillsNothing(self):
        # Rounds of 2.5 on the front top edge and the concave edge of the L whose dimple lies under
        # the front's band and joins the concave edge's wall through faces that each join the next
        # smoothly (models.smoothly_dimpled_block()). OCCT fills the dimple (747.854 for 745.816);
        # the Fillet is the construction or fails naming the front edge (PR 346 round 2:
        # 8e642b9516 let it pass)
        block, base = models.smoothly_dimpled_block()
        front, concave = ((0, 0, 10), (10, 0, 10)), ((0, 5, 5), (10, 5, 5))
        fillet, edge = models.dressed_in_a_body(self.Doc, "Fillet", base, front, 2.5, concave)
        dressed = block.cut(models.front_top_removed("Fillet", 2.5))
        dressed = dressed.fuse(models.concave_added("Fillet", 2.5))
        expected = dressed.cut(block.cut(base)).Volume
        # The adaptive readout of the B-spline dimple (SC7, ops#640): OCCT's default read 745.816371;
        # meshes at deflections 1e-3 to 3e-5 tend to 745.81636, both within 2e-5
        self.assertAlmostEqual(expected, 745.816341, delta=1e-5)
        if fillet.isValid():
            self.assertAlmostEqual(fillet.Shape.Volume, expected, delta=1e-6)
        else:
            message = "The fillet fills a recess of the base next to %s:" % edge
            self.assertTrue(fillet.getStatusString().startswith(message), fillet.getStatusString())

    def testFilletOverASmoothDimpleInTheFloorFillsNothing(self):
        # Rounds of 2.5 on the outer floor edge and the concave edge of the deep L, with a dimple
        # whose rim is rounded in the floor under the outer edge's band: the floor holds the
        # concave edge, and the dimple joins it smoothly. OCCT fills the dimple (950 for 947.962);
        # the Fillet is the construction or fails naming the outer edge (PR 346 round 3:
        # 2b534f9017 let it pass, also after a reopen)
        block = models.deep_concave_block()
        base = models.dimpled(block, 5, 12.8, 5)
        outer, concave = ((0, 14, 5), (10, 14, 5)), ((0, 5, 5), (10, 5, 5))
        fillet, edge = models.dressed_in_a_body(self.Doc, "Fillet", base, outer, 2.5, concave)
        dressed = block.cut(models.outer_floor_removed("Fillet", 2.5))
        dressed = dressed.fuse(models.concave_added("Fillet", 2.5))
        expected = dressed.cut(block.cut(base)).Volume
        # The adaptive readout (SC7, ops#640): OCCT's default read 947.961856, 5e-4 under the
        # meshes' limit (deflections 1e-3 to 1e-4: 947.96246, .96240, .96239)
        self.assertAlmostEqual(expected, 947.962368, delta=1e-5)
        if fillet.isValid():
            self.assertAlmostEqual(fillet.Shape.Volume, expected, delta=1e-6)
        else:
            message = "The fillet fills a recess of the base next to %s:" % edge
            self.assertTrue(fillet.getStatusString().startswith(message), fillet.getStatusString())

    # ops#900: a full round (radius half the wall) is one face where its two rounds meet on one
    # surface, as Onshape's: one cylinder along a straight run, one torus around a corner
    @staticmethod
    def _rounded_ring_wall(corner, wall=2.0, height=15.0):
        """A wall of thickness `wall` along a 40 x 30 rectangle, its corners rounded at `corner`
        outside (0: sharp), extruded to `height`. Returns the solid and its top rim's edges."""
        V = FreeCAD.Vector

        def outline(w, h, r):
            x, y = w / 2, h / 2
            if r <= 0:
                return Part.makePolygon(
                    [V(-x, -y, 0), V(x, -y, 0), V(x, y, 0), V(-x, y, 0), V(-x, -y, 0)]
                )
            centres = [(x - r, -y + r), (x - r, y - r), (-x + r, y - r), (-x + r, -y + r)]
            starts = [V(-x + r, -y, 0), V(x, -y + r, 0), V(x - r, y, 0), V(-x, y - r, 0)]
            ends = [V(x - r, -y, 0), V(x, y - r, 0), V(-x + r, y, 0), V(-x, -y + r, 0)]
            edges = []
            for k in range(4):
                edges.append(Part.LineSegment(starts[k], ends[k]).toShape())
                circle = Part.Circle(V(centres[k][0], centres[k][1], 0), V(0, 0, 1), r)
                edges.append(
                    Part.ArcOfCircle(circle, (k - 1) * pi / 2, k * pi / 2).toShape()
                )
            return Part.Wire(edges)

        inner = corner - wall if corner > 0 else 0
        face = Part.makeFace(
            [outline(40, 30, corner), outline(40 - 2 * wall, 30 - 2 * wall, inner)],
            "Part::FaceMakerBullseye",
        )
        solid = face.extrude(V(0, 0, height))
        rim = [
            e
            for e in solid.Edges
            if abs(e.BoundBox.ZMin - height) < 1e-9 and abs(e.BoundBox.ZMax - height) < 1e-9
        ]
        return solid, rim

    @staticmethod
    def _kinds(shape):
        kinds = {}
        for face in shape.Faces:
            name = face.Surface.__class__.__name__
            kinds[name] = kinds.get(name, 0) + 1
        return kinds

    def testFullRoundAroundCornersIsOneTorusPerCorner(self):
        # Wall 2 thick along a 40 x 30 rectangle with corners R 6 outside (R 4 inside), 15 high;
        # its whole top rim rounded at 1, half the wall. The wall's mid line is 92 + 10 pi long
        # (straights 2 * 28 + 2 * 18, four quarter circles of R 5), and the section removed,
        # 2 * 1 - pi / 2, is symmetric about it (Pappus). Faces: bottom, 8 lateral planes, 8
        # lateral cylinders, 4 half cylinders and 4 half tori: 25. Each half torus is the half
        # circle of length pi turned a quarter about R 5: area pi * 5 pi / 2. Edges: 16 at the
        # bottom, 16 upright, 16 where the rounds start, 8 half circles between a half cylinder
        # and a half torus: 56, on 32 vertices. The two rounds of an arc were two faces of one
        # torus (29 faces refined, 33 not); the crest between them is no edge in Onshape
        mid = 92 + 10 * pi
        for refine in (True, False):
            with self.subTest(refine=refine):
                solid, rim = self._rounded_ring_wall(6.0)
                fillet = self._fillet_on_base(solid, rim, 1.0)
                fillet.Refine = refine
                self.Doc.recompute()
                self._assertValidFillet(fillet, mid * (2 * 15 - (2 - pi / 2)))
                shape = fillet.Shape
                self.assertEqual(self._kinds(shape), {"Plane": 9, "Cylinder": 12, "Toroid": 4})
                self.assertEqual((len(shape.Edges), len(shape.Vertexes)), (56, 32))
                for face in shape.Faces:
                    if face.Surface.__class__.__name__ == "Toroid":
                        self.assertAlmostEqual(face.Area, pi * 5 * pi / 2, places=6)
                rounds = [
                    f
                    for f in shape.Faces
                    if f.Surface.__class__.__name__ == "Cylinder"
                    and abs(f.Surface.Radius - 1.0) < 1e-9
                ]
                self.assertEqual(len(rounds), 4)
                # Every face and edge has its name
                named = shape.ElementReverseMap
                for kind, count in (("Face", 25), ("Edge", 56)):
                    for index in range(1, count + 1):
                        self.assertTrue(named.get("%s%d" % (kind, index)), (kind, index))

    def testFullRoundOfASharpCorneredWallKeepsItsCount(self):
        # The same wall with sharp corners: four half cylinders mitred at the corners, 13 faces
        # (bottom, 8 lateral planes, 4 half cylinders), refined or not; the wall's mid line is
        # 2 * 38 + 2 * 28 long
        for refine in (True, False):
            with self.subTest(refine=refine):
                solid, rim = self._rounded_ring_wall(0.0)
                fillet = self._fillet_on_base(solid, rim, 1.0)
                fillet.Refine = refine
                self.Doc.recompute()
                self._assertValidFillet(fillet, 132 * (2 * 15 - (2 - pi / 2)))
                self.assertEqual(self._kinds(fillet.Shape), {"Plane": 9, "Cylinder": 4})

    def testRoundsBelowHalfTheWallStayApart(self):
        # Radius 0.6 on the wall 2 thick: a strip 0.8 wide of the top is left between the two
        # rounds, which stay two faces each: 17 lateral and bottom faces, the top, 8 quarter
        # cylinders and 8 quarter tori
        solid, rim = self._rounded_ring_wall(6.0)
        fillet = self._fillet_on_base(solid, rim, 0.6)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(self._kinds(fillet.Shape), {"Plane": 10, "Cylinder": 16, "Toroid": 8})

    def testFullRoundOfATubeIsOneTorus(self):
        # A tube R 6..10, 10 high, both top rims rounded at 2: bottom, two cylinders and one
        # half torus, the half circle of length 2 pi turned about R 8: area 2 pi * 2 pi * 8
        tube = Part.makeCylinder(10, 10).cut(Part.makeCylinder(6, 10))
        rims = [e for e in tube.Edges if e.BoundBox.ZMin > 9.9]
        fillet = self._fillet_on_base(tube, rims, 2.0)
        self._assertValidFillet(fillet, pi * 64 * 10 - (2 * 4 - pi * 4 / 2) * 2 * pi * 8)
        self.assertEqual(self._kinds(fillet.Shape), {"Plane": 1, "Cylinder": 2, "Toroid": 1})
        torus = [f for f in fillet.Shape.Faces if f.Surface.__class__.__name__ == "Toroid"][0]
        self.assertAlmostEqual(torus.Area, 2 * pi * 2 * pi * 8, places=6)

    def testReferencesAcrossAFullRound(self):
        # Two later references picked on the full round's result: a round on the wall's outer
        # bottom edge along y = -15, which runs on around the whole tangent rim (92 straight and
        # a full turn about R 6), and a binder on the half torus of the corner about (14, -9).
        # Below the limit (0.6) the corner has two quarter tori instead; back at the limit both
        # references give what they gave: the round its own section, the binder the half torus
        # of area pi * 5 pi / 2 about that corner
        solid, rim = self._rounded_ring_wall(6.0)
        fillet = self._fillet_on_base(solid, rim, 1.0)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        body = fillet.getParentGeoFeatureGroup()
        edge = self._edge_between(fillet.Shape, (-14, -15, 0), (14, -15, 0))
        later = self.Doc.addObject("PartDesign::Fillet", "Later")
        body.addObject(later)
        later.Base = (fillet, [edge])
        later.Radius = 0.5
        corner = FreeCAD.Vector(14, -9, 15)
        torus = next(
            "Face%d" % i
            for i, f in enumerate(fillet.Shape.Faces, 1)
            if f.Surface.__class__.__name__ == "Toroid"
            and f.Surface.Center.isEqual(FreeCAD.Vector(14, -9, 14), 1e-7)
        )
        binder = body.newObject("PartDesign::SubShapeBinder", "Binder")
        binder.Support = [(fillet, (torus,))]
        self.Doc.recompute()
        centroid = self._fillet_section_centroid(0.5)
        removed = self._fillet_section(0.5) * (92 + 2 * pi * (6 - centroid))

        def check():
            self.assertTrue(later.isValid(), later.getStatusString())
            self.assertAlmostEqual(fillet.Shape.Volume - later.Shape.Volume, removed, places=6)
            self.assertTrue(binder.isValid(), binder.getStatusString())
            self.assertEqual(len(binder.Shape.Faces), 1)
            self.assertAlmostEqual(binder.Shape.Area, pi * 5 * pi / 2, places=6)
            self.assertLess(binder.Shape.BoundBox.Center.distanceToPoint(corner), 6.0)

        check()
        fillet.Radius = 0.6
        self.Doc.recompute()
        self.assertTrue(later.isValid(), later.getStatusString())
        self.assertAlmostEqual(fillet.Shape.Volume - later.Shape.Volume, removed, places=6)
        fillet.Radius = 1.0
        self.Doc.recompute()
        self.assertEqual(self._kinds(fillet.Shape), {"Plane": 9, "Cylinder": 12, "Toroid": 4})
        check()

    # ops#900 R8 by order (oracle900r8): the merged full-round face is named after the round of
    # the edge drawn first in the sketch, whatever the selection order; the base's own edge
    # order is not the drawing order on a plate, for segments not drawn as one chain, or for a
    # hole drawn before its outline (review pr501-r2, T1)
    def _sketch_of_lines(self, body, segments, z=0.0):
        V = FreeCAD.Vector
        sketch = body.newObject("Sketcher::SketchObject", "Profile")
        sketch.Placement = FreeCAD.Placement(V(0, 0, z), FreeCAD.Rotation())
        for a, b in segments:
            sketch.addGeometry(Part.LineSegment(V(a[0], a[1], 0), V(b[0], b[1], 0)))
        self.Doc.recompute()
        return sketch

    def _first_round_at_the_limit(self, body, pad, edges, radius, below, where):
        """Fillets the pad's edges at the limit, then just below it: what the merged face's first
        name is there, as where(face) of the round it names"""
        fillet = self._add_fillet(body, pad, edges, radius)
        self._last_fillet = fillet
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        merged = [
            "Face%d" % i
            for i, f in enumerate(fillet.Shape.Faces, 1)
            if f.Surface.__class__.__name__ in ("Cylinder", "Toroid")
        ]
        self.assertEqual(len(merged), 1)
        first = fillet.Shape.getElementMappedName(merged[0])
        first = first[0] if isinstance(first, tuple) else first
        fillet.Radius = below
        self.Doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertIn(first, fillet.Shape.ElementMap)
        return where(fillet.Shape.getElement(fillet.Shape.ElementMap[first]))

    _RIB = {
        "front": ((0, 0), (30, 0)),
        "right": ((30, 0), (30, 4)),
        "back": ((30, 4), (0, 4)),
        "left": ((0, 4), (0, 0)),
    }

    def _rib_first_round(self, order, picked, plate):
        body = self.Doc.addObject("PartDesign::Body", "Body")
        if plate:
            corners = [(-5, -8), (35, -8), (35, 12), (-5, 12)]
            outline = [(corners[k], corners[(k + 1) % 4]) for k in range(4)]
            base = body.newObject("PartDesign::Pad", "Plate")
            base.Profile = self._sketch_of_lines(body, outline, -5.0)
            base.Length = 5
            self.Doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = self._sketch_of_lines(body, [self._RIB[side] for side in order])
        pad.Length = 20
        self.Doc.recompute()
        ends = {"front": ((0, 0, 20), (30, 0, 20)), "back": ((0, 4, 20), (30, 4, 20))}
        edges = [self._edge_between(pad.Shape, *ends[side]) for side in picked]
        return self._first_round_at_the_limit(
            body, pad, edges, 2.0, 1.9, lambda f: "front" if f.CenterOfMass.y < 2 else "back"
        )

    def testFullRoundIsNamedByTheSegmentDrawnFirst(self):
        # (order drawn, on a plate, the round it names): the long edge drawn first
        rows = (
            (("front", "right", "back", "left"), False, "front"),
            (("back", "left", "front", "right"), False, "back"),
            (("left", "back", "right", "front"), False, "back"),
            (("right", "front", "left", "back"), False, "front"),
            (("left", "back", "right", "front"), True, "back"),
            (("right", "front", "left", "back"), True, "front"),
        )
        for order, plate, named in rows:
            for picked in (("front", "back"), ("back", "front")):
                with self.subTest(order=order, plate=plate, picked=picked):
                    self.assertEqual(self._rib_first_round(order, picked, plate), named)

    def testFullRoundIsNamedByTheSegmentDrawnFirstAfterALaterFeature(self):
        # A pocket between the pad and the fillet (review pr501-r3, T1'): the edges' names go
        # through it, and the segment drawn first still names the merged face
        for order, named in ((("left", "back", "right", "front"), "back"), (("right", "front", "left", "back"), "front")):
            for picked in (("front", "back"), ("back", "front")):
                with self.subTest(order=order, picked=picked):
                    body = self.Doc.addObject("PartDesign::Body", "Body")
                    pad = body.newObject("PartDesign::Pad", "Pad")
                    pad.Profile = self._sketch_of_lines(body, [self._RIB[side] for side in order])
                    pad.Length = 20
                    self.Doc.recompute()
                    cut = body.newObject("PartDesign::SubtractiveBox", "Cut")
                    cut.Length, cut.Width, cut.Height = 10, 10, 30
                    cut.Placement.Base = FreeCAD.Vector(25, -3, -5)
                    self.Doc.recompute()
                    ends = {"front": ((0, 0, 20), (25, 0, 20)), "back": ((0, 4, 20), (25, 4, 20))}
                    edges = [self._edge_between(cut.Shape, *ends[side]) for side in picked]
                    named_here = self._first_round_at_the_limit(
                        body, cut, edges, 2.0, 1.9, lambda f: "front" if f.CenterOfMass.y < 2 else "back"
                    )
                    self.assertEqual(named_here, named)

    def testFullRoundOfTwoPadsIsNamedByTheEarlierPad(self):
        # The rib as two pads, its front half and its back half (review pr501-r3, T2'): the round
        # of the edge the earlier pad made names the merged face, whichever sketch came first
        halves = {
            "front": [((0, 0), (30, 0)), ((30, 0), (30, 2)), ((30, 2), (0, 2)), ((0, 2), (0, 0))],
            "back": [((0, 2), (30, 2)), ((30, 2), (30, 4)), ((30, 4), (0, 4)), ((0, 4), (0, 2))],
        }
        for sketches, pads in (
            (("back", "front"), ("front", "back")),
            (("front", "back"), ("back", "front")),
            (("front", "back"), ("front", "back")),
        ):
            with self.subTest(sketches=sketches, pads=pads):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                profile = {side: self._sketch_of_lines(body, halves[side]) for side in sketches}
                tip = None
                for side in pads:
                    tip = body.newObject("PartDesign::Pad", "Pad")
                    tip.Profile = profile[side]
                    tip.Length = 20
                    self.Doc.recompute()
                edges = [
                    self._edge_between(tip.Shape, (0, 0, 20), (30, 0, 20)),
                    self._edge_between(tip.Shape, (0, 4, 20), (30, 4, 20)),
                ]
                named = self._first_round_at_the_limit(
                    body, tip, edges, 2.0, 1.9, lambda f: "front" if f.CenterOfMass.y < 2 else "back"
                )
                self.assertEqual(named, pads[0])

    def testFullRoundOfARingIsNamedByTheOutlineDrawnFirst(self):
        # A ring wall 2 thick (40 x 20 outside), both rims rounded at the limit: each run's
        # merged face is named after the rim of the outline drawn first, the hole's included
        outer = [(0, 0), (40, 0), (40, 20), (0, 20)]
        inner = [(2, 2), (38, 2), (38, 18), (2, 18)]
        loop = lambda c: [(c[k], c[(k + 1) % 4]) for k in range(4)]
        for first, loops in (("outer", loop(outer) + loop(inner)), ("inner", loop(inner) + loop(outer))):
            with self.subTest(first=first):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                pad = body.newObject("PartDesign::Pad", "Pad")
                pad.Profile = self._sketch_of_lines(body, loops)
                pad.Length = 10
                self.Doc.recompute()
                edges = [
                    self._edge_between(pad.Shape, (0, 0, 10), (40, 0, 10)),
                    self._edge_between(pad.Shape, (2, 2, 10), (38, 2, 10)),
                ]
                named = self._first_round_at_the_limit(
                    body, pad, edges, 1.0, 0.9, lambda f: "outer" if f.CenterOfMass.y < 1 else "inner"
                )
                self.assertEqual(named, first)

    def testFullRoundSurvivesSaveAndReopen(self):
        # ops#956 (a): a wall 3 wide, both long top edges rounded at 1.5. The full round is one face
        # on a cylinder trimmed in U only (V from -2e100 to 2e100), which a document save wrote in
        # fixed notation, 119 characters a number, beyond what OCCT reads: the Fillet and the Body
        # came back null on reopen. Reopened, they keep their faces and edges.
        import os
        import tempfile
        import Sketcher

        doc = FreeCAD.newDocument("FullRoundSave")
        path = os.path.join(tempfile.mkdtemp(prefix="fc956"), "fullround.FCStd")
        try:
            body = doc.addObject("PartDesign::Body", "Body")
            sketch = body.newObject("Sketcher::SketchObject", "Sketch")
            xy = [o for o in body.Origin.OriginFeatures if o.Role == "XY_Plane"][0]
            sketch.AttachmentSupport = [(xy, "")]
            sketch.MapMode = "FlatFace"
            pts = [(-1.5, 0), (1.5, 0), (1.5, 10), (-1.5, 10)]
            for i in range(4):
                a, c = pts[i], pts[(i + 1) % 4]
                sketch.addGeometry(
                    Part.LineSegment(FreeCAD.Vector(a[0], a[1], 0), FreeCAD.Vector(c[0], c[1], 0))
                )
            for i in range(4):
                sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
            pad = body.newObject("PartDesign::Pad", "Pad")
            pad.Profile = sketch
            pad.Length = 5
            doc.recompute()
            top = [
                "Edge%d" % (i + 1)
                for i, e in enumerate(pad.Shape.Edges)
                if e.BoundBox.ZMin > 4.999 and e.BoundBox.XLength < 1e-9
            ]
            self.assertEqual(len(top), 2)
            fillet = body.newObject("PartDesign::Fillet", "Fillet")
            fillet.Base = (pad, top)
            fillet.Radius = 1.5
            doc.recompute()
            self.assertTrue(fillet.Shape.isValid(), fillet.getStatusString())
            faces, edges = len(fillet.Shape.Faces), len(fillet.Shape.Edges)
            self.assertEqual(faces, 6)
            doc.saveAs(path)
            FreeCAD.closeDocument(doc.Name)
            doc = FreeCAD.openDocument(path)
            for name in ("Pad", "Fillet", "Body"):
                shape = doc.getObject(name).Shape
                self.assertFalse(shape.isNull(), name)
                self.assertTrue(shape.isValid(), name)
            self.assertEqual(len(doc.getObject("Fillet").Shape.Faces), faces)
            self.assertEqual(len(doc.getObject("Fillet").Shape.Edges), edges)
            self.assertEqual(len(doc.getObject("Body").Shape.Edges), edges)
        finally:
            for name in list(FreeCAD.listDocuments()):
                if name.startswith("FullRoundSave"):
                    FreeCAD.closeDocument(name)
            if os.path.exists(path):
                os.remove(path)
            os.rmdir(os.path.dirname(path))

    # ops#951 (oracle951, rows T1-T3): Onshape names the merged face after the edge whose making
    # feature comes first in the body's feature list (its place, not the order it was made in),
    # then by the sketch segment drawn first; an edge born of sketch vertices goes by its first
    # vertex in segment order. The selection order never changes it
    @staticmethod
    def _chain(points):
        return [(points[k], points[(k + 1) % len(points)]) for k in range(len(points))]

    def _pad_of_lines(self, body, name, segments, length):
        pad = body.newObject("PartDesign::Pad", name)
        pad.Profile = self._sketch_of_lines(body, segments)
        pad.Length = length
        pad.Refine = True
        self.Doc.recompute()
        return pad

    def _front_or_back(self, face):
        return "front" if face.CenterOfMass.y < 2 else "back"

    def testFullRoundAfterAPocketIsNamedByThePocketsEdge(self):
        # T1: a block y 2..10, a through pocket from its top cutting away everything behind
        # y = 4 (its segment along y = 4 makes the back top edge), then PadF adds y 0..2. The
        # back top edge is the pocket's, which comes before PadF: the back round names the face,
        # whatever the segment numbers
        cut_orders = {
            4: [(31, 4), (31, 11), (-1, 11), (-1, 4)],
            1: [(-1, 4), (31, 4), (31, 11), (-1, 11)],
        }
        front_orders = {
            1: [(0, 0), (30, 0), (30, 2), (0, 2)],
            3: [(30, 2), (0, 2), (0, 0), (30, 0)],
        }
        for cut_at, front_at in ((4, 1), (1, 3)):
            for picked in (("front", "back"), ("back", "front")):
                with self.subTest(cut_at=cut_at, front_at=front_at, picked=picked):
                    body = self.Doc.addObject("PartDesign::Body", "Body")
                    self._pad_of_lines(body, "Block", self._chain([(0, 2), (30, 2), (30, 10), (0, 10)]), 20)
                    cut = body.newObject("PartDesign::Pocket", "Cut")
                    cut.Profile = self._sketch_of_lines(body, self._chain(cut_orders[cut_at]), 20.0)
                    cut.Type = "ThroughAll"
                    cut.Refine = True
                    self.Doc.recompute()
                    self.assertTrue(cut.isValid(), cut.getStatusString())
                    pad = self._pad_of_lines(body, "PadF", self._chain(front_orders[front_at]), 20)
                    self.assertEqual(len(pad.Shape.Faces), 6)
                    ends = {"front": ((0, 0, 20), (30, 0, 20)), "back": ((0, 4, 20), (30, 4, 20))}
                    edges = [self._edge_between(pad.Shape, *ends[side]) for side in picked]
                    named = self._first_round_at_the_limit(body, pad, edges, 2.0, 1.9, self._front_or_back)
                    self.assertEqual(named, "back")
                    self._assertNoNamingWarning()

    _HALVES = {
        "front": [(0, 0), (30, 0), (30, 2), (0, 2)],
        "back": [(0, 2), (30, 2), (30, 4), (0, 4)],
    }

    def testFullRoundOfTwoPadsVerticalEdgesIsNamedByTheEarlierPad(self):
        # T2: the rib 30 x 4 x 20 as two pads, each of its own sketch; the two vertical edges at
        # x = 0, each born of sketch vertices, filleted at the limit. The round of the earlier
        # pad's edge names the face, whichever sketch came first (S: sketch, P: pad)
        rows = (
            (("SB", "SF", "PF", "PB"), "front"),
            (("SF", "SB", "PF", "PB"), "front"),
            (("SF", "PF", "SB", "PB"), "front"),
            (("SF", "SB", "PB", "PF"), "back"),
            (("SB", "PB", "SF", "PF"), "back"),
        )
        sides = {"F": "front", "B": "back"}
        for order, named in rows:
            for picked in (("front", "back"), ("back", "front")):
                with self.subTest(order=order, picked=picked):
                    body = self.Doc.addObject("PartDesign::Body", "Body")
                    sketches = {}
                    tip = None
                    for step in order:
                        side = sides[step[1]]
                        if step[0] == "S":
                            sketches[side] = self._sketch_of_lines(body, self._chain(self._HALVES[side]))
                        else:
                            tip = body.newObject("PartDesign::Pad", "Pad")
                            tip.Profile = sketches[side]
                            tip.Length = 20
                            tip.Refine = True
                            self.Doc.recompute()
                    self.assertEqual(len(tip.Shape.Faces), 6)
                    ends = {"front": ((0, 0, 0), (0, 0, 20)), "back": ((0, 4, 0), (0, 4, 20))}
                    edges = [self._edge_between(tip.Shape, *ends[side]) for side in picked]
                    self.assertEqual(
                        self._first_round_at_the_limit(body, tip, edges, 2.0, 1.9, self._front_or_back), named
                    )
                    self._assertNoNamingWarning()

    def testFullRoundOfVertexBornEdgesIsNamedByTheFirstVertex(self):
        # T2, one pad: both vertical edges at x = 0 are born of the sketch's vertices. The edge
        # of the vertex first in segment order names the face, a segment's start before its end
        rows = (
            ([(0, 0), (30, 0), (30, 4), (0, 4)], "front"),  # front, right, back, left
            ([(30, 4), (0, 4), (0, 0), (30, 0)], "back"),  # back, left, front, right
            ([(0, 0), (0, 4), (30, 4), (30, 0)], "front"),  # left (from (0, 0)), back, right, front
        )
        for points, named in rows:
            for picked in (("front", "back"), ("back", "front")):
                with self.subTest(points=points, picked=picked):
                    body = self.Doc.addObject("PartDesign::Body", "Body")
                    pad = self._pad_of_lines(body, "Pad", self._chain(points), 20)
                    ends = {"front": ((0, 0, 0), (0, 0, 20)), "back": ((0, 4, 0), (0, 4, 20))}
                    edges = [self._edge_between(pad.Shape, *ends[side]) for side in picked]
                    self.assertEqual(
                        self._first_round_at_the_limit(body, pad, edges, 2.0, 1.9, self._front_or_back), named
                    )
                    self._assertNoNamingWarning()

    def testFullRoundOfAPadInsertedBeforeIsNamedByIt(self):
        # T3: PadB (the back half) made first, then PadF (the front half) inserted before it in the
        # body: PadF comes first in the feature list and its round names the face. The control
        # made in the same order without the insertion is named by PadB's
        for inserted, named in ((True, "front"), (False, "back")):
            for picked in (("front", "back"), ("back", "front")):
                with self.subTest(inserted=inserted, picked=picked):
                    body = self.Doc.addObject("PartDesign::Body", "Body")
                    pad_b = self._pad_of_lines(body, "PadB", self._chain(self._HALVES["back"]), 20)
                    profile = self._sketch_of_lines(body, self._chain(self._HALVES["front"]))
                    if inserted:
                        pad_f = self.Doc.addObject("PartDesign::Pad", "PadF")
                        pad_f.Profile = profile
                        pad_f.Length = 20
                        pad_f.Refine = True
                        body.insertObject(pad_f, pad_b, False)
                        body.Tip = pad_b
                        self.Doc.recompute()
                        self.assertEqual(pad_b.BaseFeature, pad_f)
                        self.assertIsNone(pad_f.BaseFeature)
                        tip = pad_b
                    else:
                        tip = body.newObject("PartDesign::Pad", "PadF")
                        tip.Profile = profile
                        tip.Length = 20
                        tip.Refine = True
                        self.Doc.recompute()
                    self.assertEqual(len(tip.Shape.Faces), 6)
                    ends = {"front": ((0, 0, 20), (30, 0, 20)), "back": ((0, 4, 20), (30, 4, 20))}
                    edges = [self._edge_between(tip.Shape, *ends[side]) for side in picked]
                    self.assertEqual(
                        self._first_round_at_the_limit(body, tip, edges, 2.0, 1.9, self._front_or_back), named
                    )
                    self._assertNoNamingWarning()

    def _assertNoNamingWarning(self):
        self.assertNotIn("named after", self._last_fillet.getStatusString())

    def testFullRoundOfAMirroredHalfRibIsNamedByTheOriginal(self):
        # oracle900b row d (fullround-name-order-900.md 6.4): the half rib y 0..2 mirrored
        # about the sketch's H axis; the mirror's copy is made by the mirror, after the pad, so
        # the original's round (y 2) names the face, whichever edge was picked first
        for picked in ((2, -2), (-2, 2)):
            with self.subTest(picked=picked):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                pad = self._pad_of_lines(body, "Pad", self._chain(self._HALVES["front"]), 20)
                mirror = self.Doc.addObject("PartDesign::Mirrored", "Mirror")
                mirror.Originals = [pad]
                mirror.MirrorPlane = (pad.Profile[0], ["H_Axis"])
                mirror.Refine = True
                body.addObject(mirror)
                self.Doc.recompute()
                self.assertEqual(len(mirror.Shape.Faces), 6)
                edges = [self._edge_between(mirror.Shape, (0, y, 20), (30, y, 20)) for y in picked]
                named = self._first_round_at_the_limit(
                    body, mirror, edges, 2.0, 1.9, lambda f: "original" if f.CenterOfMass.y > 0 else "copy"
                )
                self.assertEqual(named, "original")
                self._assertNoNamingWarning()

    def testFullRoundOfAPlateBullnoseIsNamedByTheSketchPlaneEdge(self):
        # oracle900b row a (fullround-name-order-900.md 3f, 6.1): a plate 4 thick, its front
        # side's bottom and top edges rounded at r 2 (a bullnose): the bottom edge, the sketch's
        # own, names the face, with no warning
        for picked in ((0, 4), (4, 0)):
            with self.subTest(picked=picked):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                plate = self._pad_of_lines(body, "Plate", self._chain([(0, 0), (30, 0), (30, 20), (0, 20)]), 4)
                edges = [self._edge_between(plate.Shape, (0, 0, z), (30, 0, z)) for z in picked]
                named = self._first_round_at_the_limit(
                    body, plate, edges, 2.0, 1.9, lambda f: "bottom" if f.CenterOfMass.z < 2 else "top"
                )
                self.assertEqual(named, "bottom")
                self._assertNoNamingWarning()

    def testFullRoundOfARibLeftByOneCutIsNamedByTheCutsSegment(self):
        # oracle900b row b (fullround-name-order-900.md 6.2): a block
        # 30 x 20 x 20, one through pocket from a sketch above it with two windows, leaving the rib
        # y 8..12. Both long top edges are the pocket's; the window segment drawn first (y 8, g3,
        # against y 12, g5) names the face
        for picked in ((8, 12), (12, 8)):
            with self.subTest(picked=picked):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                self._pad_of_lines(body, "Block", self._chain([(0, 0), (30, 0), (30, 20), (0, 20)]), 20)
                windows = self._chain([(-1, -1), (31, -1), (31, 8), (-1, 8)]) + self._chain(
                    [(-1, 12), (31, 12), (31, 21), (-1, 21)]
                )
                cut = body.newObject("PartDesign::Pocket", "Cut")
                cut.Profile = self._sketch_of_lines(body, windows, 30.0)
                cut.Type = "ThroughAll"
                cut.Refine = True
                self.Doc.recompute()
                self.assertTrue(cut.isValid(), cut.getStatusString())
                self.assertEqual(len(cut.Shape.Faces), 6)
                edges = [self._edge_between(cut.Shape, (0, y, 20), (30, y, 20)) for y in picked]
                named = self._first_round_at_the_limit(
                    body, cut, edges, 2.0, 1.9, lambda f: "front" if f.CenterOfMass.y < 10 else "back"
                )
                self.assertEqual(named, "front")
                self._assertNoNamingWarning()

    def testFullRoundOfAShortenedEdgeRanksAtTheCutsPlace(self):
        # oracle900b row c: PadF (the front half, x 0..30), PadB (the back half, x 0..25) and a
        # cut that shortens PadF's front edge to x 0..25, leaving PadB's back edge as it is. An
        # edge ranks at the place of the last feature that made or changed it: PadF, Cut, PadB
        # gives front; PadF, PadB, Cut gives back (PadB's round)
        for cut_first, named in ((True, "front"), (False, "back")):
            for picked in (("front", "back"), ("back", "front")):
                with self.subTest(cut_first=cut_first, picked=picked):
                    body = self.Doc.addObject("PartDesign::Body", "Body")
                    self._pad_of_lines(body, "PadF", self._chain(self._HALVES["front"]), 20)

                    def cut():
                        box = body.newObject("PartDesign::SubtractiveBox", "Cut")
                        box.Length, box.Width, box.Height = 10, 10, 30
                        box.Placement.Base = FreeCAD.Vector(25, -3, -5)
                        box.Refine = True
                        self.Doc.recompute()
                        return box

                    def back():
                        return self._pad_of_lines(
                            body, "PadB", self._chain([(0, 2), (25, 2), (25, 4), (0, 4)]), 20
                        )

                    tip = (cut(), back())[1] if cut_first else (back(), cut())[1]
                    self.assertTrue(tip.isValid(), tip.getStatusString())
                    self.assertEqual(len(tip.Shape.Faces), 6)
                    ends = {"front": ((0, 0, 20), (25, 0, 20)), "back": ((0, 4, 20), (25, 4, 20))}
                    edges = [self._edge_between(tip.Shape, *ends[side]) for side in picked]
                    got = self._first_round_at_the_limit(body, tip, edges, 2.0, 1.9, self._front_or_back)
                    self.assertEqual(got, named)
                    self._assertNoNamingWarning()

    def testFullRoundOfAnEdgeSplitByALaterCutRanksAtTheCutsPlace(self):
        # Review pr503-r1 T1 (row c's rule on a split edge, not measured): PadF (x 0..30), PadB
        # (x 0..25), then a slot x 25..28 through the top half leaving a remnant of PadF's front
        # edge beyond it. The near piece is renamed by the cut, which is last: back
        for picked in (("front", "back"), ("back", "front")):
            with self.subTest(picked=picked):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                self._pad_of_lines(body, "PadF", self._chain(self._HALVES["front"]), 20)
                self._pad_of_lines(body, "PadB", self._chain([(0, 2), (25, 2), (25, 4), (0, 4)]), 20)
                slot = body.newObject("PartDesign::SubtractiveBox", "Slot")
                slot.Length, slot.Width, slot.Height = 3, 10, 20
                slot.Placement.Base = FreeCAD.Vector(25, -3, 10)
                slot.Refine = True
                self.Doc.recompute()
                self.assertTrue(slot.isValid(), slot.getStatusString())
                ends = {"front": ((0, 0, 20), (25, 0, 20)), "back": ((0, 4, 20), (25, 4, 20))}
                edges = [self._edge_between(slot.Shape, *ends[side]) for side in picked]
                got = self._first_round_at_the_limit(body, slot, edges, 2.0, 1.9, self._front_or_back)
                self.assertEqual(got, "back")
                self._assertNoNamingWarning()

    def testFullRoundEndingInAWallHasNoNamingWarning(self):
        # review pr503-r2 L1: PadF, PadB, then a taller wall across the rib's end (x 30..35). The
        # round runs into the wall, so two of the merged face's sources come from one base edge: a
        # tie, not an undecided order. PadF's edge is made first: the front round, no warning
        for picked in (("front", "back"), ("back", "front")):
            with self.subTest(picked=picked):
                body = self.Doc.addObject("PartDesign::Body", "Body")
                self._pad_of_lines(body, "PadF", self._chain(self._HALVES["front"]), 20)
                self._pad_of_lines(body, "PadB", self._chain(self._HALVES["back"]), 20)
                wall = self._pad_of_lines(
                    body, "Wall", self._chain([(30, -5), (35, -5), (35, 9), (30, 9)]), 30
                )
                self.Doc.recompute()
                self.assertTrue(wall.isValid(), wall.getStatusString())
                ends = {"front": ((0, 0, 20), (30, 0, 20)), "back": ((0, 4, 20), (30, 4, 20))}
                edges = [self._edge_between(wall.Shape, *ends[side]) for side in picked]
                got = self._first_round_at_the_limit(body, wall, edges, 2.0, 1.9, self._front_or_back)
                self.assertEqual(got, "front")
                self._assertNoNamingWarning()

    def testFullRoundWithoutHistoryIsNamedByTheEdgeOrderAndWarns(self):
        # fullround-name-order-900.md 5: a Part::Box's edges carry no sketch, so neither edge is
        # known to be made first: the round of the lower base edge names the face, for either
        # selection order, and the feature says so
        answers = set()
        for back_first in (False, True):
            with self.subTest(back_first=back_first):
                box = self.Doc.addObject("Part::Box", "Box")
                box.Length, box.Width, box.Height = 30, 4, 20
                self.Doc.recompute()
                ends = [((0, 0, 20), (30, 0, 20)), ((0, 4, 20), (30, 4, 20))]
                if back_first:
                    ends.reverse()
                indices = [int(self._edge_between(box.Shape, *e)[4:]) for e in ends]
                fillet = self.Doc.addObject("Part::Fillet", "Fillet")
                fillet.Base = box
                fillet.Edges = [(i, 2.0, 2.0) for i in indices]
                self.Doc.recompute()
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertIn("named after Edge%d" % min(indices), fillet.getStatusString())
                merged = [
                    "Face%d" % i
                    for i, f in enumerate(fillet.Shape.Faces, 1)
                    if f.Surface.__class__.__name__ == "Cylinder"
                ]
                self.assertEqual(len(merged), 1)
                first = fillet.Shape.getElementMappedName(merged[0])
                first = first[0] if isinstance(first, tuple) else first
                fillet.Edges = [(i, 1.9, 1.9) for i in indices]
                self.Doc.recompute()
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                face = fillet.Shape.getElement(fillet.Shape.ElementMap[first])
                lower = self._edge_between(box.Shape, *ends[indices.index(min(indices))])
                self.assertEqual(
                    face.CenterOfMass.y < 2, box.Shape.getElement(lower).CenterOfMass.y < 2
                )
                answers.add(face.CenterOfMass.y < 2)
        self.assertEqual(len(answers), 1)

    def testFilletMixedCoverageInPartDesign(self):
        # As FilletFallbackTest.MixedCoverageTest (ops#952, NS88 Labyrinth Fillet 3): a full-round
        # pair OCCT fails on and an edge on an extruded ellipse the construction doesn't cover,
        # in one Fillet: the pair first, then the edge on its result
        mixed = models.MixedCoverageTest()
        shape, x0 = mixed.base()
        R, top, H = mixed.R, 2 * mixed.R, mixed.H
        ends = [((x, y, 0), (x, y, H)) for x, y in ((30, 0), (30, top), (x0, top))]
        fillet, _ = models.dressed_in_a_body(self.Doc, "Fillet", shape, ends[0], R, *ends[1:])
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        pair = shape.makeFillet(R, [mixed.edge_at(shape, 30, 0), mixed.edge_at(shape, 30, top)])
        expected = pair.makeFillet(R, [mixed.edge_at(pair, x0, top)])
        result = fillet.Shape
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertLess(result.cut(expected).Volume + expected.cut(result).Volume, 1e-6)

    def testRoundOverANarrowStripOntoADipIsThePlainRound(self):
        # ops#990 (HNY-DSN #108, #111): a wall meets a floor that slopes down from it by 16 deg
        # (an opening of 106 deg) for a strip 3 wide, then dips into a concave arc of radius 12 and
        # rises over a bump. The round of radius 10 at the wall's foot has a setback of 7.536, past
        # the strip, and no ball fits into the dip: OCCT rolls the ball on to the bump and bridges
        # the dip, and the feature's check refused it ("drops a part of the base"). Onshape builds
        # the plain round, tangent to the wall and to the strip's own plane, the part of its fill in
        # the material absorbed: the base fused with that fill
        from math import radians, sin, cos, tan

        V = FreeCAD.Vector
        r, L, a, s, Rd, H = 10.0, 20.0, radians(16.0), 3.0, 12.0, 25.0
        p0 = V(0, 0, 0)
        d1 = V(cos(a), -sin(a), 0)
        p1 = p0 + d1 * s
        c1 = p1 + V(sin(a), cos(a), 0) * Rd
        p2 = V(2 * c1.x - p1.x, p1.y, 0)
        p3 = p2 + V(cos(a), sin(a), 0) * s
        c2 = p3 - V(-sin(a), cos(a), 0) * Rd
        p4 = V(2 * c2.x - p3.x, p3.y, 0)
        p5 = p4 + V(cos(a), -sin(a), 0) * 6.0
        profile = [Part.makeLine(V(0, H, 0), p0), Part.makeLine(p0, p1)]
        profile.append(Part.Arc(p1, c1 + V(0, -Rd, 0), p2).toShape())
        profile.append(Part.makeLine(p2, p3))
        profile.append(Part.Arc(p3, c2 + V(0, Rd, 0), p4).toShape())
        corners = [p4, p5, V(p5.x, -15, 0), V(-8, -15, 0), V(-8, H, 0), V(0, H, 0)]
        profile += [Part.makeLine(corners[i], corners[i + 1]) for i in range(len(corners) - 1)]
        shape = Part.Face(Part.Wire(profile)).extrude(V(0, 0, L))
        opening = pi / 2 + a
        setback = r / tan(opening / 2)
        self.assertGreater(setback, s)
        ta, tb = V(0, setback, 0), d1 * setback
        bisector = (V(0, 1, 0) + d1).normalize()
        centre = bisector * (r / sin(opening / 2))
        fill = Part.Face(
            Part.Wire(
                [Part.makeLine(p0, ta), Part.Arc(ta, centre - bisector * r, tb).toShape(), Part.makeLine(tb, p0)]
            )
        ).extrude(V(0, 0, L))
        expected = shape.fuse(fill).removeSplitter()
        fillet, _ = models.dressed_in_a_body(self.Doc, "Fillet", shape, ((0, 0, 0), (0, 0, L)), r)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        result = fillet.Shape
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume - shape.Volume, expected.Volume - shape.Volume, delta=1e-6)
        self.assertLess(result.cut(expected).Volume + expected.cut(result).Volume, 1e-6)
        self.assertEqual(len(result.Faces), len(expected.Faces))

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestFillet")
        # print ("omit closing document for debugging")


class TestSmoothEdgePicks(unittest.TestCase):
    """ops#1005, Onshape's rule for smooth picks in a fillet or chamfer (notes/onshape-facts.md SE1,
    SE2, RB15). Designed geometry, Onshape's figures:
    - the bend: a section in the y-z plane (0, 0), (40, 0), (40, 10 - 20 tan d), (20, 10), (0, 10)
      extruded 30 along x, its top turning down by d at the edge (y 20, z 10). Up to 0.1 degree the
      bend is near-smooth: alone it is refused; a fillet with another edge rounds the other edge
      (dV -25.7522204 at r 2; Onshape's sliver face on the bend, of width r d, is left out); a
      chamfer with another edge fails (CHAMFER_FACE_RANGE_TOO_LARGE).
    - SE1's box: 30 x 20 x 10, its vertical edge at the origin rounded r 3; the tangent lines at
      (3, 0) and (0, 3) are smooth: alone they are refused, with other edges they are dropped. The
      same box built by a Boolean (two boxes and a cylinder) has the same tangent lines, stored C0.
    - A tangent line next to an edge only the exact construction builds (a ridge turning by 4
      degrees, at its limit radius): the line no longer makes the construction refuse the whole
      fillet (the census stops' path)."""

    SMOOTH = "every picked edge is smooth"
    NEARLY = "a picked edge is nearly smooth"

    def setUp(self):
        self.doc = FreeCAD.newDocument("PartDesignTestSmoothEdgePicks")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    @staticmethod
    def bend(d_deg):
        t = math.tan(math.radians(d_deg))
        V = FreeCAD.Vector
        points = [V(0, 0, 0), V(0, 40, 0), V(0, 40, 10 - 20 * t), V(0, 20, 10), V(0, 0, 10), V(0, 0, 0)]
        return Part.Face(Part.makePolygon(points)).extrude(V(30, 0, 0))

    @staticmethod
    def boss():
        box = Part.makeBox(30, 20, 10)
        corner = [e for e in box.Edges if all(abs(v.X) < 1e-9 and abs(v.Y) < 1e-9 for v in e.Vertexes)]
        return box.makeFillet(3, corner)

    @staticmethod
    def booleanBoss():
        V = FreeCAD.Vector
        boxes = Part.makeBox(27, 20, 10, V(3, 0, 0)).fuse(Part.makeBox(30, 17, 10, V(0, 3, 0)))
        return boxes.fuse(Part.makeCylinder(3, 10, V(3, 3, 0))).removeSplitter()

    def edge(self, shape, test):
        found = [e for e in shape.Edges if len(e.Vertexes) == 2 and test(e)]
        self.assertEqual(len(found), 1)
        return found[0]

    def line(self, shape, y, z):
        return self.edge(shape, lambda e: all(abs(v.Y - y) < 1e-7 and abs(v.Z - z) < 1e-7 for v in e.Vertexes))

    def vertical(self, shape, x, y):
        return self.edge(shape, lambda e: all(abs(v.X - x) < 1e-7 and abs(v.Y - y) < 1e-7 for v in e.Vertexes))

    def top(self, shape, x=None, y=None):
        return self.edge(
            shape,
            lambda e: all(
                abs(v.Z - 10) < 1e-7 and (x is None or abs(v.X - x) < 1e-7) and (y is None or abs(v.Y - y) < 1e-7)
                for v in e.Vertexes
            ),
        )

    def dressUp(self, kind, shape, edges, size):
        body = self.doc.addObject("PartDesign::Body", "Body")
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        body.BaseFeature = base
        self.doc.recompute()
        names = ["Edge%d" % next(i for i, e in enumerate(shape.Edges, 1) if e.isSame(edge)) for edge in edges]
        feature = self.doc.addObject("PartDesign::" + kind, kind)
        body.addObject(feature)
        feature.Base = (body.BaseFeature, names)
        if kind == "Fillet":
            feature.Radius = size
        else:
            feature.Size = size
        self.doc.recompute()
        return feature

    def assertBuilds(self, feature, shape, removed, delta=1e-6):
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertTrue(feature.Shape.isValid())
        self.assertAlmostEqual(shape.Volume - feature.Shape.Volume, removed, delta=delta)

    def assertRefused(self, feature, text):
        self.assertFalse(feature.isValid())
        self.assertIn(text, feature.getStatusString())

    # RB15: near-smooth edges

    def testNearSmoothEdgeAloneIsRefused(self):
        for d in (0.01, 0.05, 0.1):
            shape = self.bend(d)
            bend = self.line(shape, 20, 10)
            self.assertRefused(self.dressUp("Fillet", shape, [bend], 2.0), self.SMOOTH)
            self.assertRefused(self.dressUp("Chamfer", shape, [bend], 1.0), self.SMOOTH)

    def testFilletRoundsTheOtherEdgeOfANearSmoothPick(self):
        # Onshape: OK, dV -25.7522204 (the front top edge's plain round, 30 (4 - pi)), at 0.01, 0.05
        # and 0.1 degrees; the same with the bottom front edge
        for d in (0.01, 0.05, 0.1):
            shape = self.bend(d)
            for other in (self.line(shape, 0, 10), self.line(shape, 0, 0)):
                fillet = self.dressUp("Fillet", shape, [self.line(shape, 20, 10), other], 2.0)
                self.assertBuilds(fillet, shape, 25.7522204)

    def testChamferWithANearSmoothPickFails(self):
        # Onshape: CHAMFER_FACE_RANGE_TOO_LARGE with the front top, bottom front or left end edge,
        # widths 1 and 0.5; each partner chamfered alone builds (dV -15 at width 1)
        for d in (0.01, 0.05, 0.1):
            shape = self.bend(d)
            for other in (self.line(shape, 0, 10), self.line(shape, 0, 0)):
                for width in (1.0, 0.5):
                    chamfer = self.dressUp("Chamfer", shape, [self.line(shape, 20, 10), other], width)
                    self.assertRefused(chamfer, self.NEARLY)
            self.assertBuilds(self.dressUp("Chamfer", shape, [self.line(shape, 0, 10)], 1.0), shape, 15.0)

    def testBendPastTheLimitIsAnOrdinaryPick(self):
        # 0.12 degrees is an ordinary edge in Onshape: every selection with it builds. Its own chamfer
        # face (dV 0.0314159 at width 1) is not built here: OCCT skips an edge turning by less than
        # 0.1 rad in a mixed selection, as on integration (filed as debt on ops#1005); the volume
        # is the front edge's within that
        shape = self.bend(0.12)
        picks = [self.line(shape, 20, 10), self.line(shape, 0, 10)]
        self.assertBuilds(self.dressUp("Fillet", shape, picks, 2.0), shape, 25.7522204, delta=1e-5)
        self.assertBuilds(self.dressUp("Chamfer", shape, picks, 1.0), shape, 15.0314159, delta=0.04)

    # SE1, SE2: tangent edges

    def testTangentLineAloneIsRefused(self):
        for shape in (self.boss(), self.booleanBoss()):
            for line in (self.vertical(shape, 3, 0), self.vertical(shape, 0, 3)):
                for radius in (2.0, 3.5, 5.0):
                    self.assertRefused(self.dressUp("Fillet", shape, [line], radius), self.SMOOTH)
                self.assertRefused(self.dressUp("Chamfer", shape, [line], 1.0), self.SMOOTH)

    def testTangentLineWithAnOrdinaryEdgeIsDropped(self):
        # Onshape: a tangent line plus the top right edge, fillet r 1 dV -4.292037 (20 (1 - pi/4)),
        # chamfer 1 dV -10
        for shape in (self.boss(), self.booleanBoss()):
            picks = [self.vertical(shape, 3, 0), self.top(shape, x=30)]
            self.assertBuilds(self.dressUp("Fillet", shape, picks, 1.0), shape, 20 * (1 - pi / 4))
            self.assertBuilds(self.dressUp("Chamfer", shape, picks, 1.0), shape, 10.0)

    def testBothTangentLinesWithTwoTopEdgesAtACorner(self):
        # Onshape: both tangent lines plus two top edges meeting at a corner build (fillet r 1, 9
        # faces). The lines are dropped: the result is the two edges' rounds at (30, 20) alone, whose
        # mitred corner removes (1 - pi/4) 50 - (2 - pi/2 - 1/3) = 10.634221. Onshape's figure,
        # dV -10.617255, differs by 0.017 with no edge pair named: asked of the oracle on ops#1005
        shape = self.boss()
        corner = [self.top(shape, x=30), self.top(shape, y=20)]
        picks = [self.vertical(shape, 3, 0), self.vertical(shape, 0, 3)] + corner
        mitred = (1 - pi / 4) * 50 - (2 - pi / 2 - 1 / 3)
        self.assertBuilds(self.dressUp("Fillet", shape, picks, 1.0), shape, mitred, delta=1e-5)
        self.assertBuilds(self.dressUp("Fillet", shape, corner, 1.0), shape, mitred, delta=1e-5)

    def testTangentLineDoesNotStopTheExactConstruction(self):
        # A ridge turning by 4 degrees at its limit radius, which OCCT refuses and the exact
        # construction builds (parttests.FilletFallbackTest.ShallowRidgeTest), with a tangent line of
        # a notch cut from the bottom by a Boolean picked too: the construction refused the whole
        # selection for the line; Onshape drops the line. Removed: R^2 (tan(phi/2) - phi/2) 30
        V = FreeCAD.Vector
        phi = math.radians(4.0)
        t = math.tan(phi / 2)
        points = [V(-20, 0, 0), V(12, 0, 0), V(12, 0, 10 - 12 * t), V(0, 0, 10), V(-20, 0, 10 - 20 * t), V(-20, 0, 0)]
        roof = Part.Face(Part.makePolygon(points)).extrude(V(0, 30, 0))
        notch = Part.makeBox(30, 20, 4, V(-12, 10, -1)).fuse(Part.makeBox(27, 17, 4, V(-15, 13, -1)))
        notch = notch.fuse(Part.makeCylinder(3, 4, V(-12, 13, -1))).removeSplitter()
        shape = roof.cut(notch).removeSplitter()
        self.assertTrue(shape.isValid())
        ridge = self.edge(shape, lambda e: all(abs(v.X) < 1e-9 and abs(v.Z - 10) < 1e-9 for v in e.Vertexes))
        line = self.vertical(shape, -12, 10)
        radius = 12.0 / math.cos(phi / 2) / t
        removed = radius**2 * (t - phi / 2) * 30
        with self.assertRaises(Exception):
            shape.makeFillet(radius, [ridge, line])  # the maker alone, without the rule
        self.assertBuilds(self.dressUp("Fillet", shape, [ridge, line], radius), shape, removed, delta=1e-5)
