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
        """A ball's dimple (r 3, centred on the wall's face at z 7) touching the floor: its face is square to the wall
        only along its equator, and the fill cut by the mouth's prism would be no surface of the body (review
        pri1040 r1). Not known from Onshape: it stays refused."""
        shape = wall_with_hole(7.0, hole=False).cut(Part.makeSphere(3, V(20, 5, 7)))
        body = self.doc.addObject("PartDesign::Body", "Body")
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        body.BaseFeature = base
        self.doc.recompute()
        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                names = ["Edge%d" % (i + 1) for i, e in enumerate(shape.Edges) if foot(e)]
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
