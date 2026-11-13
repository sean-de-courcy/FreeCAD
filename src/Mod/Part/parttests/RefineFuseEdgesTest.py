# SPDX-License-Identifier: LGPL-2.1-or-later

"""A refine that fuses the spans of one B-spline edge keeps the fused edge on its faces and raises
no tolerance (FreeCAD-CH ops#640, Case Base's Finger Hole after an exact Finger Grip Overhang
Fillet 2).

Designed model: a prism 20 x 10 x 8 whose cap (the plane y = 0) has a parabola for its right side,
from (10, 0, 0) to (10, 0, 10) through (9, 0, 5): chord 10, sagitta 1. The parabola edge is split
into three spans, at parameters 0.8 and 0.5, by vertices (generalFuse): both its faces stay whole.
A block fused on the other side makes the refine merge two coplanar faces, so that it fuses edges.

A guard, not the failing case. OCCT's BRepLib_FuseEdges joins the 2D curves of the edges it fuses,
and adds a span's whole 2D curve, not the part its edge lies on, where the spans carry different
stored 2D curves on one face: on Case Base the fused edge's curve on a side wall ran back along
itself, 7.98 mm off, the face fix raised the edge's and its vertices' tolerance to cover it, and the
next cut into that wall failed. The refine now joins such a curve again from its edges' own ranges,
leaves the edges unfused where that fails, and undoes a fuse after which a tolerance grew
(modelRefine.cpp, "The fuse of edges, checked"). The spans here carry no stored 2D curve on the
cap's plane (a Boolean stores none on a plane), so OCCT's fuse is right on this model with and
without that code. The failing model is this one with each span's 2D curve stored on the plane, as
the exact construction of a round leaves them: tests/src/Mod/Part/App/ModelRefine.cpp,
RefineFuseEdgesTest, which writes them with BRep_Builder.

Expected, geometrically: the cap one face of 20 * 10 - 2/3 * 10 * 1 = 193 1/3 mm2 with 4 edges (the
three spans one edge again, which follows its 3D curve on both its faces), the volume
193 1/3 * 8 + 60 mm3, valid, no tolerance above 1e-6 mm, and the bounding box the model's own."""

import unittest

import FreeCAD as App
import Part

V = App.Vector

CAP_AREA = 20 * 10 - 2.0 / 3.0 * 10 * 1
BLOCK = 3 * 4 * 5


def capFaces(shape):
    return [
        f
        for f in shape.Faces
        if f.Surface.__class__.__name__ == "Plane"
        and abs(abs(f.Surface.Axis.y) - 1) < 1e-9
        and abs(f.CenterOfMass.y) < 1e-6
    ]


def splineEdges(face):
    return [e for e in face.Edges if e.Curve.__class__.__name__ == "BSplineCurve"]


def worstTolerance(shape):
    return max([e.Tolerance for e in shape.Edges] + [v.Tolerance for v in shape.Vertexes])


def gapOnFaces(edge):
    """The largest distance of the edge's stored curves on its faces from its 3D curve, at the same parameter"""
    gap = 0.0
    for rank in range(4):
        on = edge.curveOnSurface(rank)
        if not on:
            break
        curve2d, surface, placement, first, last = on
        for k in range(21):
            at = k / 20.0
            uv = curve2d.value(first + (last - first) * at)
            onFace = placement.multVec(surface.value(uv.x, uv.y))
            on3d = edge.Curve.value(edge.FirstParameter + (edge.LastParameter - edge.FirstParameter) * at)
            gap = max(gap, onFace.distanceToPoint(on3d))
    return gap


class RefineFuseEdgesTest(unittest.TestCase):
    def setUp(self):
        self.curve = Part.BSplineCurve()
        self.curve.buildFromPolesMultsKnots(
            [V(10, 0, 0), V(8, 0, 5), V(10, 0, 10)], [3, 3], [0.0, 1.0], False, 2
        )
        outline = Part.Wire(
            [
                self.curve.toShape(),
                Part.makeLine(V(10, 0, 10), V(-10, 0, 10)),
                Part.makeLine(V(-10, 0, 10), V(-10, 0, 0)),
                Part.makeLine(V(-10, 0, 0), V(10, 0, 0)),
            ]
        )
        prism = Part.Face(outline).extrude(V(0, 8, 0))
        self.assertAlmostEqual(prism.Volume, CAP_AREA * 8, places=9)
        split = prism
        for at in (0.8, 0.5):
            split = split.generalFuse([Part.Vertex(self.curve.value(at))])[0].Solids[0]
        (cap,) = capFaces(split)
        spans = sorted((e.FirstParameter, e.LastParameter) for e in splineEdges(cap))
        self.assertEqual(len(spans), 3)
        for (first, last), expected in zip(spans, ((0.0, 0.5), (0.5, 0.8), (0.8, 1.0))):
            self.assertAlmostEqual(first, expected[0], places=9)
            self.assertAlmostEqual(last, expected[1], places=9)
        # the block: its bottom and the prism's are coplanar, and the refine merges them
        self.unrefined = split.fuse(Part.makeBox(3, 4, 5, V(-13, 2, 0)))
        self.assertEqual(len(self.unrefined.Solids), 1)
        self.assertLessEqual(worstTolerance(self.unrefined), 1e-6)

    def testTheFusedEdgeFollowsItsFaces(self):
        refined = self.unrefined.removeSplitter()
        self.assertTrue(refined.isValid())
        self.assertLess(len(refined.Faces), len(self.unrefined.Faces), "the refine merged faces")
        self.assertAlmostEqual(refined.Volume, CAP_AREA * 8 + BLOCK, places=6)
        (cap,) = capFaces(refined)
        self.assertAlmostEqual(cap.Area, CAP_AREA, places=6)
        self.assertEqual(len(cap.Edges), 4, "the three spans are one edge again")
        (edge,) = splineEdges(cap)
        self.assertAlmostEqual(edge.FirstParameter, 0.0, places=9)
        self.assertAlmostEqual(edge.LastParameter, 1.0, places=9)
        self.assertLess(gapOnFaces(edge), 1e-6)

    def testTheRefineRaisesNoTolerance(self):
        refined = self.unrefined.removeSplitter()
        self.assertLessEqual(worstTolerance(refined), 1e-6, "no tolerance grew through the refine")
        box = refined.BoundBox
        for got, expected in zip(
            (box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax), (-13, 0, 0, 10, 8, 10)
        ):
            self.assertAlmostEqual(got, expected, delta=1e-5)
        # nor in the shape refined: the refine works on what the two share
        self.assertLessEqual(worstTolerance(self.unrefined), 1e-6)
