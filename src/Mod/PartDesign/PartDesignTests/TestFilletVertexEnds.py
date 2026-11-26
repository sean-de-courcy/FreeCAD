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
    (-6, 10) out of them (tangent to x = 0 at y = 10), form "step" leaves the step's corner at (0, 10)."""
    base = Part.makeBox(30, 10, 3).fuse(Part.makeBox(35, 10, 3, V(-5, 10, 0)))
    if form == "scallop":
        base = base.cut(Part.makeCylinder(6, 3, V(-6, 10, 0)))
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

    def testSixEdgeCornerWithAMergedFaceBehindTheFloor(self):
        """Cause D (HNY Honeypot #10): the end 3.9375 wide, r 2 (OCCT fails where the rounds overlap). The second
        block 8 away is past the tool's reach; 1 away it is within it, and the vertex stays refused."""
        width = 3.9375
        corner = block_corner(width)
        shape = self.dressUp(stepped_plate(width, second_x=8.0), corner, 2.0)
        alone = self.dressUp(stepped_plate(width), corner, 2.0)
        expected = alone.fuse(Part.makeBox(4, 4, 5, V(8, -4, 4))).removeSplitter()
        self.assertSameBody(shape, expected)
        self.assertTrue(self.refuses(stepped_plate(width, second_x=1.0), corner, 2.0))
