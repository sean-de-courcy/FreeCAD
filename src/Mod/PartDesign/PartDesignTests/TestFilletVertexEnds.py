# SPDX-License-Identifier: LGPL-2.1-or-later
# FreeCAD-CH: fillets and chamfers ending at a vertex where 4 edges meet (ops#1040).
#
# Designed geometry (skeptic sk1125b's cases, ops#1033). The expected bodies are built without the vertex:
# - a wall's foot under a through hole that touches the floor, or clears it by 0.2: the dress-up of the same wall
#   without the hole, with the hole then cut on through it (the hole's cylinder runs on through the fill, as the
#   fork's rule for a hole under a strip, ops#883 H; Onshape CU1-CU5 cut a fill off by the walls' surfaces);
# - a ramp lip across a half-round bar, the foot line chamfered or rounded up to and past the lip's height: the
#   section times the bar's width, clipped by the ramp's plane past the wall's top (Onshape DU1b, DU6a: the wall
#   is consumed and the fill is clipped by the face beyond, which grows);
# - a round-nosed rib 0.3 short of the plate's side: the rib rounded on a plate long enough, then cut square at
#   the side (the face beyond drops away square, ops#898 A).

import math
import os
import tempfile
import unittest

import FreeCAD
import Part

from PartDesignTests.Scenarios import models

App = FreeCAD
V = App.Vector
QUARTER = 1 - 3.141592653589793 / 4  # a round's section per r^2


def on(edge, test):
    return all(test(v.Point) for v in edge.Vertexes) and test(edge.CenterOfMass)


def wall_with_hole(axis_z, hole=True):
    """Plate 40 x 30 x 4, wall x 0..40, y 0..5, z 4..20, a through hole r 3 along y about (20, axis_z)."""
    shape = Part.makeBox(40, 30, 4).fuse(Part.makeBox(40, 5, 16, V(0, 0, 4))).removeSplitter()
    if hole:
        shape = shape.cut(Part.makeCylinder(3, 5, V(20, 0, axis_z), V(0, 1, 0)))
    return shape


def long_hole(axis_z):
    return Part.makeCylinder(3, 30, V(20, -5, axis_z), V(0, 1, 0))


def foot(edge):
    return on(edge, lambda p: abs(p.y - 5) < 1e-7 and abs(p.z - 4) < 1e-7)


def lip_on_bar():
    """A half-round bar (r 6 about the y axis, y 0..40, z <= 0) and a ramp lip across it: the triangle (y 38, z 0),
    (38, 1), (39, 0) extruded x -6..6; its wall, 1 high, faces -y."""
    bar = Part.makeCylinder(6, 40, V(0, 0, 0), V(0, 1, 0)).common(Part.makeBox(12, 40, 6, V(-6, 0, -6)))
    lip = Part.Face(Part.makePolygon([V(-6, 38, 0), V(-6, 38, 1), V(-6, 39, 0), V(-6, 38, 0)])).extrude(V(12, 0, 0))
    return bar.fuse(lip).removeSplitter()


def lip_foot(edge):
    return on(edge, lambda p: abs(p.y - 38) < 1e-7 and abs(p.z) < 1e-7)


def nosed_rib(c, plate_from=0.0):
    """Plate x 0..40, y plate_from..30, z 0..4; on it a rib 5 high: box x 16..24, y c..c+16 and a cylinder r 4
    about (20, c)."""
    rib = Part.makeBox(8, 16, 5, V(16, c, 4)).fuse(Part.makeCylinder(4, 5, V(20, c, 4))).removeSplitter()
    return Part.makeBox(40, 30 - plate_from, 4, V(0, plate_from, 0)).fuse(rib).removeSplitter()


def nose(edge):
    return abs(edge.CenterOfMass.z - 4) < 1e-7 and isinstance(edge.Curve, Part.Circle)


class TestFilletVertexEnds(unittest.TestCase):
    def setUp(self):
        self.doc = models.newDocument("PartDesignTestFilletVertexEnds")

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def dressUp(self, shape, test, size, kind="Fillet"):
        body = self.doc.addObject("PartDesign::Body", "Body")
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        body.BaseFeature = base
        self.doc.recompute()
        names = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges) if test(e)]
        self.assertTrue(names)
        feature = body.newObject("PartDesign::" + kind, kind)
        feature.Base = (body.Group[0], names)
        feature.UseAllEdges = False
        feature.Refine = True
        if kind == "Fillet":
            feature.Radius = size
        else:
            feature.Size = size
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertTrue(feature.Shape.isValid())
        return feature.Shape

    def plain(self, shape, test, size, kind):
        edges = [e for e in shape.Edges if test(e)]
        return shape.makeFillet(size, edges) if kind == "Fillet" else shape.makeChamfer(size, edges)

    def assertSameBody(self, shape, expected):
        # Same faces to the area's 1e-6; OCCT's volume of the trimmed rounds drifts by up to 5e-5 where the
        # body is the same (the symmetric difference is empty)
        self.assertAlmostEqual(shape.Area, expected.Area, delta=1e-6)
        self.assertAlmostEqual(shape.Volume, expected.Volume, delta=1e-4)
        self.assertLess(shape.cut(expected).Volume, 1e-6)
        self.assertLess(expected.cut(shape).Volume, 1e-6)

    def testFootThroughAHoleTouchingTheFloor(self):
        """The foot line is two pieces meeting where the hole touches the floor (a vertex of 4 edges, 3 faces)."""
        for kind, size in (("Fillet", 0.3), ("Fillet", 0.8), ("Chamfer", 0.8)):
            with self.subTest(kind=kind, size=size):
                shape = self.dressUp(wall_with_hole(7.0), foot, size, kind)
                expected = self.plain(wall_with_hole(7.0, hole=False), foot, size, kind).cut(long_hole(7.0))
                self.assertSameBody(shape, expected)

    def testFootUnderAHoleClearOfTheFloor(self):
        """A strip 0.2 high under the hole: the round of 0.8 runs past it into the hole's mouth."""
        for kind, size in (("Fillet", 0.8), ("Chamfer", 0.8)):
            with self.subTest(kind=kind, size=size):
                shape = self.dressUp(wall_with_hole(7.2), foot, size, kind)
                expected = self.plain(wall_with_hole(7.2, hole=False), foot, size, kind).cut(long_hole(7.2))
                self.assertSameBody(shape, expected)

    def testLipFootUpToAndPastTheWallsHeight(self):
        """The section times the bar's width 12; past the wall's top (1) the chamfer is clipped by the ramp's
        plane z = 39 - y: 0.72 less the triangle (37.9, 1.1), (38, 1.2), (38, 1)."""
        base = lip_on_bar()
        rows = (
            ("Chamfer", 0.6, 12 * 0.18, 10),
            ("Chamfer", 1.0, 12 * 0.5, 9),
            ("Chamfer", 1.2, 12 * (0.72 - 0.01), 9),
            ("Fillet", 0.6, 12 * 0.36 * QUARTER, 10),
            ("Fillet", 1.0, 12 * QUARTER, 9),
        )
        for kind, size, added, faces in rows:
            with self.subTest(kind=kind, size=size):
                shape = self.dressUp(base, lip_foot, size, kind)
                self.assertAlmostEqual(shape.Volume - base.Volume, added, delta=1e-6)
                self.assertEqual(len(shape.Faces), faces)
                # Nothing past the bar's sides
                self.assertAlmostEqual(shape.BoundBox.XMin, -6, delta=1e-6)
                self.assertAlmostEqual(shape.BoundBox.XMax, 6, delta=1e-6)

    def testNoseShortOfThePlatesSide(self):
        """The nose 0.3 short of the side y = 0: the round is the one on a longer plate, cut square at y = 0."""
        for size in (0.5, 1.0):
            with self.subTest(size=size):
                shape = self.dressUp(nosed_rib(4.3), nose, size)
                longer = nosed_rib(4.3, plate_from=-10)
                rounded = longer.makeFillet(size, [e for e in longer.Edges if nose(e)])
                expected = rounded.common(Part.makeBox(60, 40, 20, V(-10, 0, -5)))
                self.assertSameBody(shape, expected)

    def testFootThroughATiltedWallsHole(self):
        """Case 1a turned 30 degrees about z: the same body, turned (the folds' bounds follow the planes)."""
        turn = App.Placement(V(0, 0, 0), App.Rotation(V(0, 0, 1), 30))

        def turned(shape):
            shape = shape.copy()
            shape.transformShape(turn.toMatrix())
            return shape


        def tilted_foot(edge):
            q = turn.inverse().multVec(edge.CenterOfMass)
            return abs(q.y - 5) < 1e-6 and abs(q.z - 4) < 1e-6 and all(
                abs(turn.inverse().multVec(v.Point).y - 5) < 1e-6 for v in edge.Vertexes
            )

        for kind, size in (("Fillet", 0.8), ("Chamfer", 0.8)):
            with self.subTest(kind=kind, size=size):
                shape = self.dressUp(turned(wall_with_hole(7.0)), tilted_foot, size, kind)
                expected = turned(self.plain(wall_with_hole(7.0, hole=False), foot, size, kind).cut(long_hole(7.0)))
                self.assertSameBody(shape, expected)

    def testFootThroughADimpleTouchingTheFloorRefuses(self):
        """A dimple in the wall touching the floor at (20, 5, 4): a ball (r 3 about (20, 5, 7)), an ellipsoid of
        revolution about the wall's normal (equator r 3 in the wall's face, half-depth 2) and the same as a
        B-spline. Each face is square to the wall only along its equator, and the fill cut by the mouth's prism
        would be no surface of the body (reviews pri1040 r1 and r2). Not known from Onshape: they stay refused."""
        # the half ellipse x >= 20 (3 along x, 2 along y, in the plane z 7) turned about the line x 20, z 7 along y
        arc = Part.ArcOfEllipse(Part.Ellipse(V(20, 5, 7), 3, 2), -1.5707963267948966, 1.5707963267948966)
        half = Part.Face(Part.Wire([arc.toShape(), Part.LineSegment(V(20, 7, 7), V(20, 3, 7)).toShape()]))
        ellipsoid = half.revolve(V(20, 5, 7), V(0, 1, 0), 360)
        dimples = {
            "ball": Part.makeSphere(3, V(20, 5, 7)),
            "ellipsoid": ellipsoid,
            "bspline": ellipsoid.toNurbs(),
        }
        for name, dimple in dimples.items():
            shape = wall_with_hole(7.0, hole=False).cut(dimple)
            self.assertTrue(shape.isValid())
            body = self.doc.addObject("PartDesign::Body", "Body")
            base = self.doc.addObject("Part::Feature", "Base")
            base.Shape = shape
            body.BaseFeature = base
            self.doc.recompute()
            names = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges) if foot(e)]
            for kind in ("Fillet", "Chamfer"):
                with self.subTest(dimple=name, kind=kind):
                    feature = body.newObject("PartDesign::" + kind, kind)
                    feature.Base = (body.Group[0], names)
                    feature.UseAllEdges = False
                    if kind == "Fillet":
                        feature.Radius = 0.8
                    else:
                        feature.Size = 0.8
                    self.doc.recompute()
                    self.assertFalse(feature.isValid())
                    body.removeObject(feature)
                    self.doc.removeObject(feature.Name)
                    self.doc.recompute()


# ops#1040 K2: three more vertex forms of 4 or 6 edges (fabvtx's census read, notes vertex-fillets-k2-1126).
# A: the foot line through a U-groove touching the floor whose axis is at the wall's top, so that the wall under it
#    is two cusp faces of one plane touching only at the vertex (4 edges, 4 faces). Expected: the same dress-up of
#    the wall without the groove, the groove then cut on through it (RB36 1a's rule, the fill run on by the groove).
# C: a wall's convex corner edge on a floor, its outer face running on below the floor into a face behind it (a
#    scallop's cylinder tangent to it, or a step's plane square to it): 4 edges, 4 faces. Both corners of the wall's
#    end at half its width, where OCCT fails. Expected: the wall rounded alone, then fused with the base.
# D: ops#938's 6-edge vertex (a block's corner above a cut's corner) with the cut's wall merged by refine with a
#    coplanar face of a second block that rises above the floor farther away. Expected: the body without the second
#    block, dressed, and the block fused back. Within the tool's reach the merged face is refused.


def grooved_wall(top, groove=True):
    """Plate 40 x 30 x 4, wall x 0..40, y 0..5, z 4..top; a groove r 3 along y about (20, 7)."""
    shape = Part.makeBox(40, 30, 4).fuse(Part.makeBox(40, 5, top - 4, V(0, 0, 4)))
    if groove:
        shape = shape.cut(groove_tool())
    return shape.removeSplitter()


def groove_tool():
    return Part.makeCylinder(3, 40, V(20, -10, 7), V(0, 1, 0))


def scalloped_base(form):
    """Two plates 3 thick, x 0..30 by y 0..10 and x -5..30 by y 10..20; form "scallop" cuts a cylinder r 6 about
    (-6, 10) out of them (tangent to x = 0 at y = 10), form "step" leaves the step's corner at (0, 10), form
    "slant" adds a wedge over x -5..0 whose sloped face runs from (y 10, z 3) down to (y 8, z 0)."""
    base = Part.makeBox(30, 10, 3).fuse(Part.makeBox(35, 10, 3, V(-5, 10, 0)))
    if form == "scallop":
        base = base.cut(Part.makeCylinder(6, 3, V(-6, 10, 0)))
    elif form == "slant":
        side = Part.Face(Part.makePolygon([V(-5, 10, 3), V(-5, 8, 0), V(-5, 10, 0), V(-5, 10, 3)]))
        base = base.fuse(side.extrude(V(5, 0, 0))).removeSplitter()
    return base


def end_wall():
    return Part.makeBox(8, 4, 4, V(0, 6, 3))


def end_corner(edge):
    """The wall's two vertical corner edges at x = 0."""
    return on(edge, lambda p: abs(p.x) < 1e-7 and (abs(p.y - 10) < 1e-7 or abs(p.y - 6) < 1e-7) and p.z > 3 - 1e-7)


def stepped_plate(width, second_x=None):
    """Plate 40 x 40 x 4 about the origin less the quadrant x, y >= 0; a block x -20..0, y -width..0, z 4..9; with
    second_x, a block x second_x..second_x+4, y -4..0, z 4..9 whose face y = 0 merges with the cut's wall."""
    shape = Part.makeBox(40, 40, 4, V(-20, -20, 0)).cut(Part.makeBox(20, 20, 4))
    shape = shape.fuse(Part.makeBox(20, width, 5, V(-20, -width, 4)))
    if second_x is not None:
        shape = shape.fuse(Part.makeBox(4, 4, 5, V(second_x, -4, 4)))
    return shape.removeSplitter()


def block_corner(width):
    return lambda edge: on(
        edge, lambda p: abs(p.x) < 1e-7 and (abs(p.y) < 1e-7 or abs(p.y + width) < 1e-7) and p.z > 4 - 1e-7
    )


class TestFilletVertexFolds(unittest.TestCase):
    setUp = TestFilletVertexEnds.setUp
    tearDown = TestFilletVertexEnds.tearDown
    dressUp = TestFilletVertexEnds.dressUp
    plain = TestFilletVertexEnds.plain
    assertSameBody = TestFilletVertexEnds.assertSameBody

    def refuses(self, shape, test, size, kind="Fillet"):
        body = self.doc.addObject("PartDesign::Body", "Body")
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        body.BaseFeature = base
        self.doc.recompute()
        feature = body.newObject("PartDesign::" + kind, kind)
        feature.Base = (body.Group[0], ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges) if test(e)])
        feature.UseAllEdges = False
        if kind == "Fillet":
            feature.Radius = size
        else:
            feature.Size = size
        self.doc.recompute()
        return not feature.isValid()

    def testFootThroughAGrooveWithTwoCuspFaces(self):
        """Cause A (FG Heat Wire Clip #14, Waffle Nuggets Holder #26): the wall's top at the groove's axis."""
        for kind, size in (("Fillet", 0.5), ("Fillet", 0.8), ("Chamfer", 0.8)):
            with self.subTest(kind=kind, size=size):
                shape = self.dressUp(grooved_wall(7.0), foot, size, kind)
                expected = self.plain(grooved_wall(7.0, groove=False), foot, size, kind).cut(groove_tool())
                self.assertSameBody(shape, expected)

    def testCornerOverAFaceBelowTheFloor(self):
        """Cause C (FG Vial #20, New FG #20, New HNY Trio #23): the wall's outer face x = 0 runs on below the
        floor z = 3 into a scallop tangent to it, or a step square to it; the end rounded whole at r 2."""
        for form in ("scallop", "step"):
            for size in (1.0, 2.0):
                with self.subTest(form=form, size=size):
                    base = scalloped_base(form).fuse(end_wall()).removeSplitter()
                    shape = self.dressUp(base, end_corner, size)
                    wall = end_wall()
                    rounded = wall.makeFillet(size, [e for e in wall.Edges if end_corner(e)])
                    expected = scalloped_base(form).fuse(rounded).removeSplitter()
                    self.assertSameBody(shape, expected)

    def testCornerOverASlopeBelowTheFloorStaysRefused(self):
        """Cause C's limit (review prfx1040k2-r1, Onshape RB149): below the floor the wall's face x = 0 runs on
        beside the corner (0, 10) down to a slope, and a round there runs on down that face, which the fold
        does not build: r 2 on both corners stays refused. The corner (0, 6) alone, where the face ends square
        below the floor, builds the wall's own round."""
        base = scalloped_base("slant").fuse(end_wall()).removeSplitter()
        self.assertTrue(self.refuses(base, end_corner, 2.0))
        lower = lambda e: end_corner(e) and e.CenterOfMass.y < 8
        shape = self.dressUp(base, lower, 2.0)
        wall = end_wall()
        rounded = wall.makeFillet(2.0, [e for e in wall.Edges if lower(e)])
        self.assertSameBody(shape, scalloped_base("slant").fuse(rounded).removeSplitter())

    def testSixEdgeCornerWithAMergedFaceBehindTheFloor(self):
        """Cause D (HNY Honeypot #10): the end 3.9375 wide, r 2 (OCCT fails where the rounds overlap). The second
        block 8, 5.5 or 3 away is past the tool's reach (its section's extent, 2, with a margin; fr1040: up to
        four radii refused); 2 or 1 away it is within it, and the vertex stays refused."""
        width = 3.9375
        corner = block_corner(width)
        alone = self.dressUp(stepped_plate(width), corner, 2.0)
        for gap in (8.0, 5.5, 3.0):
            with self.subTest(gap=gap):
                shape = self.dressUp(stepped_plate(width, second_x=gap), corner, 2.0)
                expected = alone.fuse(Part.makeBox(4, 4, 5, V(gap, -4, 4))).removeSplitter()
                self.assertSameBody(shape, expected)
        for gap in (2.0, 1.0):
            with self.subTest(gap=gap):
                self.assertTrue(self.refuses(stepped_plate(width, second_x=gap), corner, 2.0))

    def testTiltedCornerWithAMergedFaceBehindTheFloor(self):
        """Cause D with the block's end face leaning, x + 2 (z - 4) = 0 (review r1 T1 of ops#1040 D): the edge meets
        the floor at 26.6 degrees, and the tool's footprint on the floor is its section over the sine. The second
        block 8 away builds the plain round, fillet and chamfer; 2 and 4 away it stays refused."""
        width = 3.9375

        def tilted(second_x=None):
            shape = Part.makeBox(40, 40, 4, V(-20, -20, 0)).cut(Part.makeBox(20, 20, 4))
            side = Part.makePolygon([V(-20, 0, 4), V(0, 0, 4), V(-10, 0, 9), V(-20, 0, 9), V(-20, 0, 4)])
            shape = shape.fuse(Part.Face(side).extrude(V(0, -width, 0)))
            if second_x is not None:
                shape = shape.fuse(Part.makeBox(4, 4, 5, V(second_x, -4, 4)))
            return shape.removeSplitter()

        def corner(edge):
            if len(edge.Vertexes) != 2:
                return False
            low, high = sorted((v.Point for v in edge.Vertexes), key=lambda p: p.z)
            return (
                abs(low.x) < 1e-7
                and abs(low.z - 4) < 1e-7
                and abs(high.z - 9) < 1e-7
                and abs(low.y - high.y) < 1e-7
                and (abs(low.y) < 1e-7 or abs(low.y + width) < 1e-7)
            )

        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                alone = self.dressUp(tilted(), corner, 2.0, kind)
                shape = self.dressUp(tilted(second_x=8.0), corner, 2.0, kind)
                expected = alone.fuse(Part.makeBox(4, 4, 5, V(8, -4, 4))).removeSplitter()
                self.assertSameBody(shape, expected)
                self.assertTrue(self.refuses(tilted(second_x=2.0), corner, 2.0, kind))
                # 4 away: within the footprint over the sine (1.2 * 2 / sin 26.6 = 5.4), past 1.2 * 2 without
                # it (PR 567 review gap a)
                self.assertTrue(self.refuses(tilted(second_x=4.0), corner, 2.0, kind))

    def testShallowTiltedCornerKeepsTheFoldPastFourExtents(self):
        """Review r2 L1 of ops#1040 D: the corners leaning at 12 degrees to the floor (2 high), the second block
        (2 high) 9.5 away. The tool's footprint (2 / sin 12 = 9.6) runs the other way, and the bound stays the one
        before ops#1040 D, four extents (8): the fold builds the plain round, fillet and chamfer, as it did."""
        width = 3.9375
        run = 2 / math.tan(math.radians(12))

        def leaning(second_x=None):
            shape = Part.makeBox(40, 40, 4, V(-20, -20, 0)).cut(Part.makeBox(20, 20, 4))
            side = Part.makePolygon([V(-20, 0, 4), V(0, 0, 4), V(-run, 0, 6), V(-20, 0, 6), V(-20, 0, 4)])
            shape = shape.fuse(Part.Face(side).extrude(V(0, -width, 0)))
            if second_x is not None:
                shape = shape.fuse(Part.makeBox(4, 4, 2, V(second_x, -4, 4)))
            return shape.removeSplitter()

        def corner(edge):
            if len(edge.Vertexes) != 2:
                return False
            low, high = sorted((v.Point for v in edge.Vertexes), key=lambda p: p.z)
            return (
                abs(low.x) < 1e-7
                and abs(low.z - 4) < 1e-7
                and abs(high.z - 6) < 1e-7
                and abs(low.y - high.y) < 1e-7
                and (abs(low.y) < 1e-7 or abs(low.y + width) < 1e-7)
            )

        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                alone = self.dressUp(leaning(), corner, 2.0, kind)
                shape = self.dressUp(leaning(second_x=9.5), corner, 2.0, kind)
                expected = alone.fuse(Part.makeBox(4, 4, 2, V(9.5, -4, 4))).removeSplitter()
                self.assertSameBody(shape, expected)


# ops#898 causes L and P (sk898tlp's cases; Onshape RB136, RB138).
# L: a block's two long top edges rounded, a handle r 7 standing on the end face x = 24 under part of the round's end
#    section. Handle (b), the whole cylinder: neither of the edge's faces runs on past the end, and Onshape's round is
#    the plain one over the edge's own length (RB138 L6), the handle keeping a flat in x = 24.
# P: a stadium boss on a bar of its own width, each nose's foot arc ending tangent to the bar's sides, which drop below
#    the floor: the plain revolved fill kept between the side planes (RB136: one torus per arc, nothing removed).

    # ops#898 cause T (Case Base V2 #48 and eight more studios): a round past its floor into two walls that are
    # tangent neighbours, each cutting the round by its own continuation along its own foot (Onshape RB6, RB20)
    def fillet(self, shape, test, size):
        body = self.doc.addObject("PartDesign::Body", "Body")
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        body.BaseFeature = base
        self.doc.recompute()
        names = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges) if test(e)]
        self.assertTrue(names)
        feature = body.newObject("PartDesign::Fillet", "Fillet")
        feature.Base = (body.Group[0], names)
        feature.UseAllEdges = False
        feature.Refine = True
        feature.TangentPropagation = False
        feature.Radius = size
        self.doc.recompute()
        return (feature.Shape if feature.isValid() else None), names

    @staticmethod
    def wall(shape, x):
        """The area of the outer wall's plane face x = 0 (x) or y = 0."""
        for face in shape.Faces:
            if isinstance(face.Surface, Part.Plane) and all(
                abs(v.Point.x if x else v.Point.y) < 1e-9 for v in face.Vertexes
            ):
                return face.Area
        return 0.0

    @staticmethod
    def splines(shape):
        return sum(f.Area for f in shape.Faces if isinstance(f.Surface, Part.BSplineSurface))

    def testRoundPastAFloorIntoTangentNeighbourWalls(self):
        """RB6's corner (blends 0.8, lip corners 1), the rim chain: T4 r 0.97 as before; T1 r 0.98 (6.7e-4 under
        Onshape's: the scoop's sliver of growth under the round is not kept there); T2 r 0.999 (RB20); T3 r 1.0, where
        each outer wall loses 0.765395, the blends, not the scoop, take the growth along their feet (2 x 0.516421 +
        0.006414) and each lip corner takes a sphere."""
        base = scoop_corner()
        for size, area, within in ((0.97, -7.665097, 1e-4), (0.98, -7.740446, 1e-3), (0.999, -7.878888, 1e-4), (1.0, -7.886001, 1e-4)):
            with self.subTest(size=size):
                shape, names = self.fillet(base, rim_chain(1.0), size)
                self.assertEqual(len(names), 6)
                self.assertIsNotNone(shape)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Area - base.Area, area, delta=within)
                if size == 1.0:
                    self.assertAlmostEqual(self.wall(shape, True), self.wall(shape, False), delta=1e-6)
                    self.assertAlmostEqual(self.wall(shape, True) - self.wall(base, True), -0.765395, delta=1e-4)
                    self.assertAlmostEqual(self.splines(shape) - self.splines(base), 2 * 0.516421 + 0.006414, delta=1e-4)
                    self.assertTrue(any(isinstance(f.Surface, Part.Sphere) for f in shape.Faces))

    def testRoundPastTheLipCornersRadiusStaysRefused(self):
        """T6: past the lip corners' radius Onshape fails (FILLET_FACE_RANGE_TOO_LARGE); so does the fork."""
        shape, _ = self.fillet(scoop_corner(), rim_chain(1.0), 1.05)
        self.assertIsNone(shape)

    def testStripUnderAStraightBossIsCutByEachWall(self):
        """RB137 T4 (draft 0): the plate's front top edge rounded r 1.5 past the 1-wide strip under the boss's plane
        wall and its end cylinders: -19.003014. Drafted 15 deg (T2) the fork still refuses ("band crosses a hole or
        pocket"), where Onshape builds -18.979252: debt, never silent."""
        base = drafted_boss(0)
        shape, _ = self.fillet(base, front_top, 1.5)
        self.assertIsNotNone(shape)
        self.assertAlmostEqual(shape.Volume - base.Volume, -19.003014, delta=1e-4)
        shape, _ = self.fillet(drafted_boss(15), front_top, 1.5)
        self.assertIsNone(shape)


    def testRoundOnATangentTipKeepsItsNamesAfterReopen(self):
        """ops#1085 case 6: RB153's form from PartDesign features (a block, two pocket corners R 5 back to back, their
        cylinders tangent along the tip), the tip rounded r 0.5 with tangent propagation on: one edge, Onshape's
        removed volume 4.286734 and 14 faces. After save and reopen: the same volume, faces and round's name, and a
        Chamfer saved on one of the round's straight contact edges still finds that edge (and refuses it as
        smooth, as Onshape)."""
        body = self.doc.addObject("PartDesign::Body", "Body")
        block = body.newObject("PartDesign::AdditiveBox", "Block")
        block.Length, block.Width, block.Height = 20, 20, 10
        block.Placement = App.Placement(V(0, -10, -10), App.Rotation())
        for side in (-1, 1):
            box = body.newObject("PartDesign::SubtractiveBox", "PocketBox")
            box.Length, box.Width, box.Height = 10, 7, 6
            box.Placement = App.Placement(V(5, -12 if side < 0 else 5, -5), App.Rotation())
            corner = body.newObject("PartDesign::SubtractiveCylinder", "PocketCorner")
            corner.Radius, corner.Height = 5, 10
            corner.Placement = App.Placement(V(5, 5 * side, 0), App.Rotation(V(0, 1, 0), 90))
        self.doc.recompute()
        base = body.Tip
        tip = ["Edge%d" % (i + 1) for i, e in enumerate(base.Shape.Edges)
               if e.Length > 1 and all(abs(v.Point.y) < 1e-7 and abs(v.Point.z) < 1e-7 for v in e.Vertexes)]
        self.assertEqual(len(tip), 1)
        fillet = body.newObject("PartDesign::Fillet", "Fillet")
        fillet.Base = (base, tip)
        fillet.TangentPropagation = True
        fillet.Radius = 0.5
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())

        def state(shape):
            names = {v: k for k, v in shape.ElementMap.items()}
            rounds = [i + 1 for i, f in enumerate(shape.Faces)
                      if isinstance(f.Surface, Part.Cylinder) and abs(f.Surface.Radius - 0.5) < 1e-9]
            self.assertEqual(len(rounds), 1)
            lines = [i + 1 for i, e in enumerate(shape.Edges) if e.Curve.TypeId == "Part::GeomLine"
                     and any(e.isSame(c) for c in shape.Faces[rounds[0] - 1].Edges)]
            self.assertEqual(len(lines), 2)
            return shape.Volume, len(shape.Faces), names["Face%d" % rounds[0]], ["Edge%d" % i for i in lines]

        volume, faces, name, lines = state(fillet.Shape)
        d = math.sqrt(2 * 5 * 0.5 + 0.25)
        phi = math.atan(d / 5)
        removed = 10 * (5 * d - 25 * phi - 0.25 * (math.pi - 2 * phi) / 2)
        self.assertAlmostEqual(base.Shape.Volume - volume, removed, delta=1e-6)
        self.assertAlmostEqual(removed, 4.286734, delta=1e-6)
        self.assertEqual(faces, 14)
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (fillet, lines[:1])
        chamfer.Size = 0.2
        self.doc.recompute()
        self.assertIn("smooth", chamfer.getStatusString())

        path = os.path.join(tempfile.mkdtemp(), "TangentTip1085.FCStd")
        self.doc.saveAs(path)
        App.closeDocument(self.doc.Name)
        self.doc = App.openDocument(path)
        fillet, chamfer = self.doc.getObject("Fillet"), self.doc.getObject("Chamfer")
        fillet.touch()
        self.doc.recompute()
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        again = state(fillet.Shape)
        self.assertAlmostEqual(again[0], volume, delta=1e-9)
        self.assertEqual(again[1:3], (faces, name))
        self.assertIn("smooth", chamfer.getStatusString())
        edge = fillet.getSubObject(chamfer.Base[1][0])
        self.assertEqual(edge.Curve.TypeId, "Part::GeomLine")
        self.assertTrue(any(edge.isSame(fillet.Shape.Edges[int(n[4:]) - 1]) for n in again[3]))

def handle_block(flush=False):
    """Block x 0..24, y 0..17, z 0..10; a handle r 7 along x through (y 8.5, z 10) on x = 24, 10 long. flush: only
    its lower half, its top merged with the block's top."""
    handle = Part.makeCylinder(7, 10, V(24, 8.5, 10), V(1, 0, 0))
    if flush:
        handle = handle.common(Part.makeBox(10, 14, 7, V(24, 1.5, 3)))
    return Part.makeBox(24, 17, 10).fuse(handle).removeSplitter()


def long_top(edge):
    return on(edge, lambda p: abs(p.z - 10) < 1e-7 and (abs(p.y) < 1e-7 or abs(p.y - 17) < 1e-7) and p.x < 24 + 1e-7)


def stadium_bar(front=12.0, channel=False):
    """Bar x -3..3, y -front..front, z -6..0; a stadium boss z 0..4, sides x = -3 and 3, noses r 3 about (0, 5) and
    (0, -5). channel: walls 2 high beside the bar (x -6..-3 and 3..6), so the side planes rise above the floor."""
    boss = Part.makeBox(6, 10, 4, V(-3, -5, 0))
    boss = boss.fuse(Part.makeCylinder(3, 4, V(0, 5, 0))).fuse(Part.makeCylinder(3, 4, V(0, -5, 0)))
    shape = Part.makeBox(6, 2 * front, 6, V(-3, -front, -6)).fuse(boss)
    if channel:
        shape = shape.fuse(Part.makeBox(12, 2 * front, 6, V(-6, -front, -6)))
        shape = shape.fuse(Part.makeBox(3, 2 * front, 2, V(-6, -front, 0))).fuse(Part.makeBox(3, 2 * front, 2, V(3, -front, 0)))
    return shape.removeSplitter()


def foot_arcs(edge):
    return abs(edge.CenterOfMass.z) < 1e-7 and isinstance(edge.Curve, Part.Circle)


class TestFilletEndsPastTheEndFace(unittest.TestCase):
    setUp = TestFilletVertexEnds.setUp
    tearDown = TestFilletVertexEnds.tearDown
    dressUp = TestFilletVertexEnds.dressUp
    refuses = TestFilletVertexFolds.refuses

    def assertPlainRoundsOfTheTopEdges(self, base, shape, size):
        """The plain round of each 24 long edge: (1 - pi/4) r^2 per unit length removed, nothing added."""
        self.assertLess(shape.cut(base).Volume, 1e-6)
        self.assertAlmostEqual(base.cut(shape).Volume, 2 * QUARTER * size * size * 24, delta=1e-5)

    def testRoundIntoAHandleOnTheEndFace(self):
        """Cause L, handle (b): r 3 and 5 reach into the handle (1.5 of the end face is free beside it), and the
        round is the plain one; r 1.5 fits beside the handle, as before. sk898tlp L1-L3: dA -68.756040 at r 3,
        -118.478885 at r 5, 2 cylinders more."""
        base = handle_block()
        for size, area in ((1.5, -32.834081), (3.0, -68.756040), (5.0, -118.478885)):
            with self.subTest(size=size):
                shape = self.dressUp(base, long_top, size)
                self.assertPlainRoundsOfTheTopEdges(base, shape, size)
                self.assertAlmostEqual(shape.Area - base.Area, area, delta=1e-5)
                self.assertEqual(len(shape.Faces), len(base.Faces) + 2)

    def testRoundIntoAFlushHandleOrAChamferStaysRefused(self):
        """Cause L's limits: the handle flush with the top (Onshape runs the round on past the end, RB138 L3, L4),
        and a chamfer on handle (b) (no Onshape fact) stay refused."""
        self.assertTrue(self.refuses(handle_block(flush=True), long_top, 3.0))
        self.assertTrue(self.refuses(handle_block(), long_top, 3.0, "Chamfer"))

    def testFillsOfFootArcsEndingTangentToSidesBelowTheFloor(self):
        """Cause P (New HNY Duo Heat Wire Clip #27): both arcs; per arc sk898tlp P1, P2 (RB136's rule: Onshape is
        within 2.1e-5 of the closed form): r 0.4 +0.286808 dA -1.296938, r 0.75 +0.973232 -2.171134, r 1.5
        +3.717486 -3.453686; one face per arc, nothing removed."""
        base = stadium_bar()
        for size, volume, area in ((0.4, 0.286808, -1.296938), (0.75, 0.973232, -2.171134), (1.5, 3.717486, -3.453686)):
            with self.subTest(size=size):
                shape = self.dressUp(base, foot_arcs, size)
                self.assertLess(base.cut(shape).Volume, 1e-6)
                self.assertAlmostEqual(shape.cut(base).Volume, 2 * volume, delta=2e-4)
                self.assertAlmostEqual(shape.Area - base.Area, 2 * area, delta=1e-5)
                self.assertEqual(len(shape.Faces), len(base.Faces) + 2)

    def testFillsOfFootArcsWithTheBarsFrontInFront(self):
        """Cause P with the bar's front 0.4 past the nose tips (sk898tlp P5): +0.959141 and dA -2.048973 per arc, the
        floor in front of each nose left in two pieces."""
        base = stadium_bar(front=8.4)
        shape = self.dressUp(base, foot_arcs, 0.75)
        self.assertLess(base.cut(shape).Volume, 1e-6)
        self.assertAlmostEqual(shape.cut(base).Volume, 2 * 0.959141, delta=2e-4)
        self.assertAlmostEqual(shape.Area - base.Area, 2 * -2.048973, delta=1e-5)


def curve_of(edge):
    """The edge's curve, or None where Part has no type for it."""
    try:
        return edge.Curve
    except TypeError:
        return None


def scoop_corner(blend=0.8, corner=1.0):
    """RB6's corner (ops#898 cause T): a block 40 x 40 x 20; a sphere r 8 scaled 1.5 along z about (3, 3, 0) cut out
    above z 1 (the scoop, leaning over the floor); a cylinder r 7 about the same axis cut through z 0..1 (the lip, 1
    thick, its floor at z 1 0.9722 wide). The scoop's edges on the outer walls rounded blend (0: none), then the
    lip's two vertical edges on the r 7 face rounded corner."""
    import math

    sphere = Part.makeSphere(8)
    scale = App.Matrix()
    scale.A33 = 1.5
    sphere = sphere.transformGeometry(scale)
    sphere.translate(V(3, 3, 0))
    upper = sphere.common(Part.makeBox(60, 60, 60, V(-30, -30, 1)))
    shape = Part.makeBox(40, 40, 20).cut(upper).cut(Part.makeCylinder(7, 1, V(3, 3, 0))).removeSplitter()

    def mid(e):
        return e.valueAt((e.FirstParameter + e.LastParameter) / 2)

    if blend > 0:
        edges = [
            e
            for e in shape.Edges
            if not isinstance(curve_of(e), (Part.Line, type(None)))
            and mid(e).z > 1.001
            and (abs(mid(e).x) < 1e-6 or abs(mid(e).y) < 1e-6)
        ]
        shape = shape.makeFillet(blend, edges).removeSplitter()
    edges = [
        e
        for e in shape.Edges
        if isinstance(curve_of(e), Part.Line)
        and abs(e.Length - 1) < 1e-6
        and abs(mid(e).z - 0.5) < 1e-6
        and abs(math.hypot(mid(e).x - 3, mid(e).y - 3) - 7) < 1e-6
    ]
    return shape.makeFillet(corner, edges).removeSplitter()


def rim_chain(corner):
    """RB6's rim chain at z 1: the r 7 arc, the lip corners' arcs and the short lines on the outer walls."""

    def test(edge):
        if not on(edge, lambda p: abs(p.z - 1) < 1e-6):
            return False
        curve = curve_of(edge)
        if isinstance(curve, Part.Circle):
            return abs(curve.Radius - 7) < 1e-6 or abs(curve.Radius - corner) < 1e-6
        p = edge.CenterOfMass
        return isinstance(curve, Part.Line) and edge.Length < 3 and (abs(p.x) < 1e-6 or abs(p.y) < 1e-6)

    return test


def drafted_boss(draft):
    """RB137 (row K-T): a plate 40 x 20 x 10 with a stadium boss on its top (y 1..11, end arcs r 5 about (10, 6) and
    (30, 6)), 6 high, drafted narrowing upward."""
    import math

    def stadium(z, inset):
        r = 5 - inset
        return Part.Wire(
            [
                Part.ArcOfCircle(Part.Circle(V(10, 6, z), V(0, 0, 1), r), math.pi / 2, 3 * math.pi / 2).toShape(),
                Part.LineSegment(V(10, 6 - r, z), V(30, 6 - r, z)).toShape(),
                Part.ArcOfCircle(Part.Circle(V(30, 6, z), V(0, 0, 1), r), -math.pi / 2, math.pi / 2).toShape(),
                Part.LineSegment(V(30, 6 + r, z), V(10, 6 + r, z)).toShape(),
            ]
        )

    inset = 6 * math.tan(math.radians(draft))
    if draft:
        boss = Part.makeLoft([stadium(10, 0), stadium(16, inset)], True, True)
    else:
        boss = Part.Face(stadium(10, 0)).extrude(V(0, 0, 6))
    return Part.makeBox(40, 20, 10).fuse(boss).removeSplitter()


def front_top(edge):
    return on(edge, lambda p: abs(p.y) < 1e-9 and abs(p.z - 10) < 1e-9) and edge.Length > 39
