# SPDX-License-Identifier: LGPL-2.1-or-later

"""The fillets and chamfers OCCT refuses, built exactly (ops#300).

OCCT fails whenever a fillet's or chamfer's new edge would land on an existing edge (a full round,
a chamfer to an edge). makeFillet and makeChamfer then build them as exact Booleans. Designed
models; the expectations are analytic volumes.
"""

import math
import unittest

import FreeCAD
import Part

V = FreeCAD.Vector


def fillet_section(r):
    return r * r * (1 - math.pi / 4)


def fillet_centroid(r):
    return r * (10 - 3 * math.pi) / (12 - 3 * math.pi)


def edge_between(shape, p, q):
    p, q = V(*p), V(*q)
    for edge in shape.Edges:
        a, b = edge.Vertexes[0].Point, edge.Vertexes[-1].Point
        if ((a - p).Length < 1e-7 and (b - q).Length < 1e-7) or (
            (a - q).Length < 1e-7 and (b - p).Length < 1e-7
        ):
            return edge
    raise RuntimeError("no edge between %s and %s" % (p, q))


def top_edges(box):
    """The long top edges of the box 30 x 4 x 20"""
    return [edge_between(box, (0, 0, 20), (30, 0, 20)), edge_between(box, (0, 4, 20), (30, 4, 20))]


def half_space(point, normal, size=100.0):
    """A box filling the side of the plane the normal points to, within size of the point"""
    normal = V(*normal).normalize()
    rotation = FreeCAD.Rotation(V(0, 0, 1), normal)
    box = Part.makeBox(2 * size, 2 * size, size)
    box.Placement = FreeCAD.Placement(V(*point) - rotation.multVec(V(size, size, 0)), rotation)
    return box


def gauss_legendre(f, a, b, n=32):
    """The integral of f over [a, b], its nodes by Newton's method"""
    total = 0.0
    for i in range(1, n + 1):
        x = math.cos(math.pi * (i - 0.25) / (n + 0.5))
        for _ in range(100):
            p0, p1 = 1.0, x
            for k in range(2, n + 1):
                p0, p1 = p1, ((2 * k - 1) * x * p1 - (k - 1) * p0) / k
            derivative = n * (x * p1 - p0) / (x * x - 1)
            step = p1 / derivative
            x -= step
            if abs(step) < 1e-16:
                break
        total += 2 / ((1 - x * x) * derivative * derivative) * f((a + b) / 2 + (b - a) / 2 * x)
    return total * (b - a) / 2


def plate_top_removed(a, b, alpha, r, depth):
    """What rounds of r on the four top edges of a plate remove: its top the rectangle a x b, its
    sides (x = 0, x = a, y = 0, y = b) meeting the top at the dihedral angles alpha. A slice at the
    depth z = r (1 - cos theta) is the rectangle with each side z cot(alpha) in from the top's,
    and it loses a band along each side, w = r cot(alpha / 2) - r sin theta - z cot(alpha) wide,
    down to theta = pi - alpha: the union of the rounds (their miter where the angles are equal)"""

    def removed(theta):
        z = r * (1 - math.cos(theta))
        outer = [z / math.tan(angle) for angle in alpha]
        inner = [
            o
            + (
                r / math.tan(angle / 2) - r * math.sin(theta) - o
                if theta <= math.pi - angle
                else 0.0
            )
            for o, angle in zip(outer, alpha)
        ]
        area = (a - outer[0] - outer[1]) * (b - outer[2] - outer[3])
        return (area - (a - inner[0] - inner[1]) * (b - inner[2] - inner[3])) * r * math.sin(theta)

    last = math.acos(1 - min(depth, 2 * r) / r)
    ends = sorted({0.0, last} | {min(max(math.pi - angle, 0.0), last) for angle in alpha})
    return sum(gauss_legendre(removed, p, q) for p, q in zip(ends, ends[1:]) if q > p)


def ribbed_wave_prism(waves):
    """A prism over a cosine wave with a rib along its flat side (ops#414). Its section in the
    plane z = 0: x from -5 to the wave x = 1.5 (1 - cos(2 pi y / 20)), interpolated by one cubic
    B-spline through points 1 mm apart (20 spans per wave), for y from 0 to the wave's length;
    extruded by 10. The rib is the box x in [-9, -5], z in [3, 7] along the whole length: its top
    x = -9 is 4 wide, so a round or chamfer of 2 on its two long edges is at the limit"""
    length = 20 * waves
    points = [V(1.5 * (1 - math.cos(2 * math.pi * y / 20)), y, 0) for y in range(length + 1)]
    spline = Part.BSplineCurve()
    spline.interpolate(points)
    corners = [V(0, length, 0), V(-5, length, 0), V(-5, 0, 0), V(0, 0, 0)]
    edges = [spline.toShape()] + [Part.makeLine(a, b) for a, b in zip(corners, corners[1:])]
    prism = Part.Face(Part.Wire(edges)).extrude(V(0, 0, 10))
    return prism.fuse(Part.makeBox(4, length, 4, V(-9, 0, 3)))


class FilletFallbackTest(unittest.TestCase):
    def assertExact(self, shape, volume):
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertFalse([face for face in shape.Faces if face.Area < 1e-7])
        self.assertAlmostEqual(shape.Volume, volume, delta=1e-6 * volume)

    def testFullRound(self):
        box = Part.makeBox(30, 4, 20)
        box.Tag = 1  # a tagged shape gets an element map
        edges = top_edges(box)
        result = box.makeFillet(2, edges)
        self.assertExact(result, 2400 - 2 * fillet_section(2) * 30)
        self.assertEqual(len(result.Faces), 7)
        # Names as a fillet's: the round faces are generated by their edges
        rounds = [
            name
            for name, index in result.ElementMap.items()
            if index.startswith("Face")
            and result.getElement(index).Surface.TypeId == "Part::GeomCylinder"
        ]
        self.assertEqual(len(rounds), 2)
        for name in rounds:
            self.assertIn("FLT", name)
            self.assertIn("GEN", name)

    def testFilletAsHighAsThePlate(self):
        plate = Part.makeBox(30, 20, 4)
        result = plate.makeFillet(4, [edge_between(plate, (0, 0, 4), (30, 0, 4))])
        self.assertExact(result, 2400 - fillet_section(4) * 30)

    def testTubeFullRound(self):
        tube = Part.makeCylinder(10, 10).cut(Part.makeCylinder(6, 10))
        top = [
            edge
            for edge in tube.Edges
            if edge.Curve.TypeId == "Part::GeomCircle" and abs(edge.Vertexes[0].Point.z - 10) < 1e-7
        ]
        c = fillet_centroid(2)
        removed = 2 * math.pi * ((10 - c) + (6 + c)) * fillet_section(2)
        result = tube.makeFillet(2, top)
        self.assertExact(result, math.pi * 64 * 10 - removed)
        self.assertEqual(
            sorted(f.Surface.TypeId for f in result.Faces).count("Part::GeomToroid"), 2
        )

    def testStepOgee(self):
        step = Part.makeBox(30, 20, 10).fuse(Part.makeBox(30, 10, 4, V(0, 10, 10))).removeSplitter()
        edges = [
            edge_between(step, (0, 10, 10), (30, 10, 10)),
            edge_between(step, (0, 10, 14), (30, 10, 14)),
        ]
        self.assertExact(step.makeFillet(2, edges), 7200)

    def testBaseWithALongSplineFace(self):
        # The construction's checks compare volumes: the base's, and the volume each Boolean
        # removes against its closed form. OCCT's default integration under-samples a face with
        # many curved B-spline spans (the wave's side, and the top and bottom it bounds), so it
        # refused every one of these: the base's volume came out negative at 30 and 50 waves, and
        # the cut "removed" 343.200 instead of 343.363 at 10. Part's mass-properties helper
        # integrates those faces adaptively (ops#414). Shape.Volume still reads OCCT's default, so
        # the volume is checked on the rib's side of x = -5, where no face carries the spline
        for waves in (10, 30, 50):
            length = 20 * waves
            base = ribbed_wave_prism(waves)
            edges = [
                edge_between(base, (-9, 0, 3), (-9, length, 3)),
                edge_between(base, (-9, 0, 7), (-9, length, 7)),
            ]
            rib_side = Part.makeBox(5, length + 2, 12, V(-10, -1, -1))
            # The rib's section, 4 x 4, less what the rounds or the chamfers remove
            for kind, section in (("fillet", 16 - 2 * fillet_section(2)), ("chamfer", 16 - 4)):
                with self.subTest(waves=waves, kind=kind):
                    if kind == "fillet":
                        result = base.makeFillet(2, edges)
                    else:
                        result = base.makeChamfer(2, edges)
                    self.assertTrue(result.isValid())
                    self.assertEqual(len(result.Solids), 1)
                    # the rib's top is gone, two rounds or chamfers in its place
                    self.assertEqual(len(result.Faces), len(base.Faces) + 1)
                    self.assertFalse(
                        [face for face in result.Faces if abs(face.CenterOfMass.x + 9) < 1e-7]
                    )
                    rib = result.common(rib_side)
                    self.assertAlmostEqual(rib.Volume, section * length, delta=1e-6 * length)

    def testChamfers(self):
        box = Part.makeBox(30, 4, 20)
        edges = top_edges(box)
        self.assertExact(box.makeChamfer(2, edges), 2400 - 4 * 30)
        self.assertExact(box.makeChamfer(4, edges[:1]), 2400 - 8 * 30)

    def testCorners(self):
        # Corners where selected edges meet, with equal sizes: miters, sphere patches named after
        # their vertex, and a box corner's chamfer triangle
        cube = Part.makeBox(4, 4, 4)
        cube.Tag = 1
        ball = cube.makeFillet(2, cube.Edges)
        self.assertExact(ball, 32 * math.pi / 3)
        spheres = [
            name
            for name, index in ball.ElementMap.items()
            if index.startswith("Face")
            and ball.getElement(index).Surface.TypeId == "Part::GeomSphere"
        ]
        self.assertEqual(len(spheres), 8)
        for name in spheres:
            self.assertIn("Vertex", name)
            self.assertIn("FLT", name)
        plate = Part.makeBox(30, 20, 4)
        top = [e for e in plate.Edges if all(abs(v.Point.z - 4) < 1e-7 for v in e.Vertexes)]
        miter = 5.0 / 3 - math.pi / 2
        self.assertExact(
            plate.makeFillet(4, top), 2400 - (100 * fillet_section(4) - 4 * 64 * miter)
        )
        self.assertExact(
            plate.makeChamfer(2, plate.Edges), 2400 - (8 * 5 * 8 / 6 + 4 * (26 + 16) * 2)
        )

    def testUnequalCorners(self):
        # The plate's end x = 30 leans in by 10 degrees: its top edge meets the long top edges at
        # 100 degrees against their 90. The top edges at r = t: the rounds meet there in an
        # ellipse on the plane bisecting their axes, not on the faces' bisector plane: the union
        # of the two rounds, each generated by its edge
        lean = 4 * math.tan(math.radians(10))
        profile = [V(0, 0, 0), V(30, 0, 0), V(30 - lean, 0, 4), V(0, 0, 4)]
        leaning = Part.Face(Part.makePolygon(profile + profile[:1])).extrude(V(0, 20, 0))
        leaning.Tag = 1
        top = [e for e in leaning.Edges if all(abs(v.Point.z - 4) < 1e-7 for v in e.Vertexes)]
        self.assertEqual(len(top), 4)
        alpha = [math.pi / 2, math.radians(100), math.pi / 2, math.pi / 2]
        removed = plate_top_removed(30 - lean, 20, alpha, 4, 4)
        result = leaning.makeFillet(4, top)
        self.assertExact(result, 2 * 20 * (60 - lean) - removed)
        rounds = [
            name
            for name, index in result.ElementMap.items()
            if index.startswith("Face")
            and result.getElement(index).Surface.TypeId == "Part::GeomCylinder"
        ]
        self.assertEqual(len(rounds), 4)
        for name in rounds:
            self.assertIn("FLT", name)
            self.assertIn("GEN", name)

    def testRefusalsKeepOcctsError(self):
        # A corner of two concave edges with unequal dihedral angles (the boss's wall x = 25
        # leans in by 10 degrees), variable radius, overlapping rounds, rounds just over the
        # limit (the strips overlap, or run off their face, by a hundredth)
        boss = Part.makeBox(10, 10, 2, V(15, 15, 4)).cut(
            half_space((25, 15, 4), (math.cos(math.radians(10)), 0, math.sin(math.radians(10))))
        )
        drafted = Part.makeBox(40, 40, 4).fuse(boss).removeSplitter()
        base = [
            e
            for e in drafted.Edges
            if all(
                abs(v.Point.z - 4) < 1e-7 and 14 < v.Point.x < 26 and 14 < v.Point.y < 26
                for v in e.Vertexes
            )
        ]
        self.assertEqual(len(base), 4)
        with self.assertRaises(Part.OCCError):
            drafted.makeFillet(2, base)
        box = Part.makeBox(30, 4, 20)
        edges = top_edges(box)
        with self.assertRaises(Part.OCCError):
            box.makeFillet(1, 2, edges)
        for r in (2.1, 2.01):
            with self.assertRaises(Part.OCCError):
                box.makeFillet(r, edges)
        with self.assertRaises(Part.OCCError):
            box.makeFillet(4.01, edges[:1])

    def testWholeOutlineOfAFusedStadium(self):
        # ops#298: OCCT "succeeds" on the whole top outline at r = 2 and d = 2 (half the width),
        # keeping the top face with area 0, also at r = 2 - 1e-8. makeFillet and makeChamfer
        # build the full round and the ridge exactly instead (10 faces: the half circle at x = 20
        # is in two)
        plate, outline = fused_stadium()
        plate.Tag = 1
        self.assertEqual(len(outline), 5)
        for r in (2, 2 - 1e-8):
            result = plate.makeFillet(r, outline)
            self.assertExact(result, fused_stadium_rounded(r))
            self.assertEqual(len(result.Faces), 10)
            self.assertGreater(narrowest(result, plate), 0.5)
        result = plate.makeChamfer(2, outline)
        self.assertExact(result, 20 * 4 * 3 + math.pi * 12 - 80 - 2 * math.pi * (2 - 2 / 3) * 2)
        self.assertEqual(len(result.Faces), 10)
        # At r = 2 - 1e-7 OCCT's top is a sliver 2e-7 wide, twice its tolerance: a face OCCT
        # built correctly, kept
        result = plate.makeFillet(2 - 1e-7, outline)
        self.assertExact(result, fused_stadium_rounded(2 - 1e-7))
        self.assertEqual(len(result.Faces), 11)
        self.assertAlmostEqual(narrowest(result, plate), 2e-7, delta=1e-9)

    def testSliversNarrowerThanTheirTolerance(self):
        # Just below the full round of the 4 mm top, OCCT leaves the top 2 (2 - r) wide. Under
        # its tolerance (1e-7) the exact construction builds the full round; from 2e-7 on the
        # sliver is a face OCCT built correctly
        box = Part.makeBox(30, 4, 20)
        box.Tag = 1
        edges = top_edges(box)
        for r in (2 - 1e-9, 2 - 1e-8):
            result = box.makeFillet(r, edges)
            self.assertExact(result, 2400 - 2 * fillet_section(r) * 30)
            self.assertEqual(len(result.Faces), 7)
        for r in (2 - 1e-7, 2 - 1e-5):
            result = box.makeFillet(r, edges)
            self.assertExact(result, 2400 - 2 * fillet_section(r) * 30)
            self.assertEqual(len(result.Faces), 8)
            self.assertAlmostEqual(narrowest(result, box), 2 * (2 - r), delta=1e-9)


def rib_against_wall():
    """A rib 30 x 4 x 20 against a wall as high as the rib, and its free top edge"""
    rib = Part.makeBox(30, 4, 20).fuse(Part.makeBox(5, 24, 20, V(-5, -10, 0))).removeSplitter()
    return rib, [edge_between(rib, (0, 0, 20), (30, 0, 20))]


def stadium_plate():
    """A plate 4 thick whose outline is two half discs of radius 5 and two straight sides 20
    long, and the edges of both outlines"""
    arcs = [
        Part.makeCircle(5, V(20, 0, 0), V(0, 0, 1), -90, 90),
        Part.makeCircle(5, V(0, 0, 0), V(0, 0, 1), 90, 270),
    ]
    lines = [Part.makeLine(V(20, 5, 0), V(0, 5, 0)), Part.makeLine(V(0, -5, 0), V(20, -5, 0))]
    plate = Part.Face(Part.Wire(Part.__sortEdges__(arcs + lines))).extrude(V(0, 0, 4))
    loops = [e for e in plate.Edges if e.BoundBox.ZLength < 1e-9]
    return plate, loops


def fused_stadium():
    """The stadium plate of ops#298: a box 20 x 4 x 3 fused with two cylinders of radius 2, and
    its whole top outline. The half circle at x = 20 is split at its cylinder's seam (22, 2), a
    vertex of two edges on two faces: five edges"""
    plate = (
        Part.makeBox(20, 4, 3)
        .fuse([Part.makeCylinder(2, 3, V(0, 2, 0)), Part.makeCylinder(2, 3, V(20, 2, 0))])
        .removeSplitter()
    )
    return plate, [e for e in plate.Edges if all(abs(v.Point.z - 3) < 1e-7 for v in e.Vertexes)]


def fused_stadium_rounded(r):
    """The fused stadium's volume after rounds of r on its whole top outline (Pappus for the
    half circles)"""
    return 20 * 4 * 3 + math.pi * 4 * 3 - 2 * fillet_section(r) * 20 - (
        2 * math.pi * (2 - fillet_centroid(r)) * fillet_section(r)
    )


def narrowest(shape, base):
    """The smallest width of the shape's faces that aren't faces of the base: that of the
    rectangle with the face's area and perimeter (a strip's width, a square's side)"""
    widths = []
    for face in shape.Faces:
        if any(face.isSame(old) for old in base.Faces):
            continue
        area = abs(face.Area)
        quarter = sum(e.Length for e in face.Edges) / 4
        widths.append(area / (quarter + math.sqrt(max(0.0, quarter * quarter - area))))
    return min(widths)


def disk():
    """A disk of radius 10, 2 thick, and its two rims"""
    cylinder = Part.makeCylinder(10, 2)
    return cylinder, [e for e in cylinder.Edges if e.Curve.TypeId == "Part::GeomCircle"]


def notched_block(k=1, size=(24, 16, 10)):
    """A block 24 x 16 x 10 with a notch 8 x 6 x 6 in its front top, and four edges: the front
    bottom edge and the notch floor's front edge, 4 apart on the front face, the right bottom
    edge and the notch floor's left edge. With k, the notch is k times as big and 4 k above the
    bottom, in the front left corner of a block of the given size."""
    length, width, height = size
    block = Part.makeBox(length, width, height).cut(
        Part.makeBox(8 * k, 6 * k, height, V(8 * k, 0, 4 * k))
    )
    ends = [
        ((0, 0, 0), (length, 0, 0)),
        ((8 * k, 0, 4 * k), (16 * k, 0, 4 * k)),
        ((length, 0, 0), (length, width, 0)),
        ((8 * k, 0, 4 * k), (8 * k, 6 * k, 4 * k)),
    ]
    return block, [edge_between(block, p, q) for p, q in ends]


def with_back_face_reversed(shape):
    """The shape, made invalid away from the notch: its back face reversed"""
    back = max(shape.Faces, key=lambda face: face.BoundBox.YMin)
    return Part.Solid(Part.Shell([f.reversed() if f.isSame(back) else f for f in shape.Faces]))


def pyramid():
    """A pyramid on a 20 x 20 square, 10 high, and the four edges at its apex"""
    apex = V(10, 10, 10)
    corners = [V(0, 0, 0), V(20, 0, 0), V(20, 20, 0), V(0, 20, 0)]
    faces = [Part.Face(Part.makePolygon(corners + corners[:1]))]
    faces += [
        Part.Face(Part.makePolygon([p, q, apex, p]))
        for p, q in zip(corners, corners[1:] + corners[:1])
    ]
    solid = Part.Solid(Part.Shell(faces))
    return solid, [e for e in solid.Edges if any(v.Point.isEqual(apex, 1e-9) for v in e.Vertexes)]


def pyramid_edge_rounds(r):
    """The volume four rounds of radius r would remove along the full length of the pyramid's
    apex edges (10 sqrt 3 long, where the faces meet at 120 degrees), counting their overlap at
    the apex four times: more than the fillet removes"""
    section = r * r * (1 / math.sqrt(3) - math.pi / 6)
    return 4 * section * 10 * math.sqrt(3)


def cube_with_fin():
    """A 10 mm cube with a fin (ops#12): a square face hanging inward at 45 degrees from the
    front bottom edge, so that three faces meet at the edge. Invalid; a dress-up passes the fin
    on, and ShapeFix moves it into an open shell beside the solid"""
    cube = Part.makeBox(10, 10, 10)
    edge = edge_between(cube, (0, 0, 0), (10, 0, 0))
    p0, p1, q0, q1 = V(0, 0, 0), V(10, 0, 0), V(0, 5, 5), V(10, 5, 5)
    fin = Part.Face(
        Part.Wire([edge, Part.makeLine(p1, q1), Part.makeLine(q1, q0), Part.makeLine(q0, p0)])
    )
    bottom = next(face for face in cube.Faces if face.CenterOfMass.z < 1e-6)
    # The same face on the same edges; a new face, so that the replacement keeps it
    new_bottom = Part.Face(bottom.Surface, bottom.OuterWire)
    if bottom.Orientation == "Reversed":
        new_bottom = new_bottom.reversed()
    return cube.replaceShape([(bottom, Part.Compound([new_bottom, fin]))])


class InvalidDressUpTest(unittest.TestCase):
    """OCCT (8.0.1) sometimes returns an invalid fillet or chamfer without an error (ops#297).

    makeFillet and makeChamfer build such a result by the exact construction where they can;
    otherwise they return OCCT's result as it is, and Part::Fillet and Part::Chamfer check it: they
    repair it if the repair keeps its solids and its faces, or fail.
    """

    def setUp(self):
        self.doc = FreeCAD.newDocument("InvalidDressUpTest")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def dressUp(self, kind, shape, edges, sizes):
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        feature = self.doc.addObject("Part::" + kind, kind)
        feature.Base = base
        indices = [
            next(i for i, e in enumerate(shape.Edges, 1) if e.isSame(edge)) for edge in edges
        ]
        feature.Edges = [(i, s[0], s[1]) for i, s in zip(indices, sizes)]
        self.doc.recompute()
        return feature

    def assertExact(self, shape, volume):
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, delta=1e-6 * volume)

    def assertFails(self, feature):
        self.assertFalse(feature.isValid())
        self.assertEqual(feature.getStatusString(), "Resulting shape is invalid")

    def testRibAgainstWallAtTheLimit(self):
        # A round as wide as the rib's top, ending against the wall: OCCT's result is invalid
        # (unorientable faces), the exact construction builds it
        rib, edges = rib_against_wall()
        expected = 4800 - fillet_section(4) * 30
        self.assertExact(rib.makeFillet(4, edges), expected)
        feature = self.dressUp("Fillet", rib, edges, [(4, 4)])
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertExact(feature.Shape, expected)

    @staticmethod
    def dressUpShape(kind, shape, size, edges):
        if kind == "Fillet":
            return shape.makeFillet(size, edges)
        return shape.makeChamfer(size, edges)

    def testOverlongFullRoundsFail(self):
        # Just over a full round, OCCT returns two invalid solids with more volume than the base,
        # which no fillet or chamfer can have
        for kind in ("Fillet", "Chamfer"):
            for model, size in ((stadium_plate, 2.0002), (disk, 1.00001)):
                shape, edges = model()
                raw = self.dressUpShape(kind, shape, size, edges)
                self.assertFalse(raw.isValid())  # returned as OCCT built it
                self.assertEqual(len(raw.Solids), 2)
                feature = self.dressUp(kind, shape, edges, [(size, size)] * len(edges))
                self.assertFails(feature)

    def testOverlappingRoundsFail(self):
        # Rounds or chamfers of 2.65 on two edges 4 apart overlap on the face between them: no
        # dress-up exists. OCCT's result has a self-intersecting wire; its repair adds two faces
        # (and 16.75 mm2 for the fillet)
        for kind in ("Fillet", "Chamfer"):
            block, edges = notched_block()
            self.assertFalse(self.dressUpShape(kind, block, 2.65, edges).isValid())
            self.assertFails(self.dressUp(kind, block, edges, [(2.65, 2.65)] * 4))

    def testOverlappingRoundsOnALargePartFail(self):
        # The notch at a tenth of the size in a block 1000 x 1000 x 1: the repair's added area
        # (0.17 mm2) is far below a millionth of the block's (2 m2)
        for kind in ("Fillet", "Chamfer"):
            block, edges = notched_block(0.1, (1000, 1000, 1))
            self.assertFalse(self.dressUpShape(kind, block, 0.265, edges).isValid())
            self.assertFails(self.dressUp(kind, block, edges, [(0.265, 0.265)] * 4))

    def testOverlappingRoundsOnAnInvalidBaseFail(self):
        # The base made invalid away from the notch (its back face reversed): the repair may
        # remove what the base passes on, but not add the two faces
        for kind in ("Fillet", "Chamfer"):
            block, _ = notched_block()
            base = with_back_face_reversed(block)
            self.assertFalse(base.isValid())
            _, edges = notched_block()
            edges = [
                edge_between(base, e.Vertexes[0].Point, e.Vertexes[-1].Point) for e in edges
            ]
            self.assertFails(self.dressUp(kind, base, edges, [(2.65, 2.65)] * 4))

    def testRepairKeepingTheSurface(self):
        # Four rounds or chamfers meeting at the pyramid's apex: OCCT's faces are misoriented
        # (negative volume); the repair reorients them and keeps every face and its area. Rounds
        # or chamfers along the full length of the four edges (10 sqrt 3, faces at 120 degrees)
        # remove a little more: their overlap at the apex counts four times
        chamfers = 4 * math.sqrt(3) / 4 * 10 * math.sqrt(3)  # section d * d * sin(120 deg) / 2
        bounds = {
            "Fillet": (0.98 * pyramid_edge_rounds(1), pyramid_edge_rounds(1)),
            "Chamfer": (0.9 * chamfers, chamfers),
        }
        for kind in ("Fillet", "Chamfer"):
            solid, edges = pyramid()
            raw = self.dressUpShape(kind, solid, 1, edges)
            self.assertFalse(raw.isValid())
            feature = self.dressUp(kind, solid, edges, [(1, 1)] * 4)
            self.assertTrue(feature.isValid(), feature.getStatusString())
            shape = feature.Shape
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids), 1)
            self.assertEqual(len(shape.Faces), len(raw.Faces))
            # raw is a second OCCT run, not the one the feature repaired: on macOS the chamfer's
            # (planar) faces came out 1.1e-6 apart in total between the two, the repair accepted
            # (each face within 1e-6 of the feature's own run). A wrong repair adds faces and
            # about 1 % of the area (the notch)
            self.assertAlmostEqual(shape.Area, raw.Area, delta=1e-5 * raw.Area)
            removed = 4000 / 3 - shape.Volume
            self.assertGreater(removed, bounds[kind][0])
            self.assertLess(removed, bounds[kind][1])

    def testRepairDropsTheFinOfAnInvalidBase(self):
        # The fin cube's fillet or chamfer: OCCT's result keeps the fin and is invalid, and its
        # repair is the dressed-up cube plus the fin in an open shell, a valid compound. On the
        # front top edge its volume counted the fin (974.3 for 997.9); the result is the solid
        base = cube_with_fin()
        self.assertFalse(base.isValid())
        removed = {"Fillet": fillet_section(1) * 10, "Chamfer": 0.5 * 10}
        for kind in ("Fillet", "Chamfer"):
            for ends in (((0, 0, 10), (10, 0, 10)), ((0, 10, 10), (10, 10, 10))):
                feature = self.dressUp(kind, base, [edge_between(base, *ends)], [(1, 1)])
                self.assertTrue(feature.isValid(), feature.getStatusString())
                shape = feature.Shape
                self.assertEqual(shape.ShapeType, "Solid")
                self.assertEqual(len(shape.Faces), 7)
                self.assertExact(shape, 1000 - removed[kind])

    def testRepairDropsTheFinOfAnInvalidBaseAtTheLimit(self):
        # At the limit (a fillet of 10, a chamfer within 1e-6 of 10) OCCT's result keeps the fin
        # as a second, open shell of its solid, which BRepCheck accepts, and a later cut through
        # the fin gave 500.0001 for 496 (ops#303). The feature repairs it as an invalid result:
        # the solid without the fin, and a cut through the fin as on the plain cube
        base = cube_with_fin()
        cube = Part.makeBox(10, 10, 10)
        d = 10 - 1e-6
        ends = (
            ((0, 0, 10), (10, 0, 10)),
            ((0, 10, 10), (10, 10, 10)),
            ((0, 10, 0), (10, 10, 0)),
        )
        cases = (
            ("Fillet", 10, fillet_section(10) * 10, 5),
            ("Chamfer", d, d * d / 2 * 10, 7),
        )
        through_fin = Part.makeBox(2, 2, 2, V(2, 1, 1))
        for kind, size, removed, faces in cases:
            for end in ends:
                feature = self.dressUp(kind, base, [edge_between(base, *end)], [(size, size)])
                self.assertTrue(feature.isValid(), feature.getStatusString())
                shape = feature.Shape
                self.assertEqual(shape.ShapeType, "Solid")
                self.assertEqual(len(shape.Shells), 1)
                self.assertEqual(len(shape.Faces), faces)
                self.assertExact(shape, 1000 - removed)
                tool = self.doc.addObject("Part::Feature", "Tool")
                tool.Shape = through_fin
                cut = self.doc.addObject("Part::Cut", "Cut")
                cut.Base, cut.Tool = feature, tool
                self.doc.recompute()
                self.assertTrue(cut.isValid(), cut.getStatusString())
                plain = self.dressUpShape(kind, cube, size, [edge_between(cube, *end)])
                self.assertExact(cut.Shape, plain.cut(through_fin).Volume)
        # The issue's case, the chamfer on the back bottom edge in the fin's plane: the box's half
        # z >= y - 1e-6 remains
        self.assertAlmostEqual(cut.Shape.Volume, 1000 - d * d / 2 * 10 - 4, delta=1e-4)

    def testRepairDropsTheFinOfABaseWithALooseFace(self):
        # The fin cube beside a loose square face: OCCT's result drops the face, a solid with the
        # fin, and its repair is the same compound with the fin outside the solid. The repair
        # keeps the solid, and the face is put back (ops#303)
        corners = [V(20, 0, 0), V(30, 0, 0), V(30, 10, 0), V(20, 10, 0)]
        loose = Part.Face(Part.makePolygon(corners, True))
        base = Part.Compound([cube_with_fin(), loose])
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        for kind, removed in (("Fillet", fillet_section(1) * 10), ("Chamfer", 0.5 * 10)):
            feature = self.dressUp(kind, base, [edge], [(1, 1)])
            self.assertTrue(feature.isValid(), feature.getStatusString())
            shape = feature.Shape
            self.assertEqual(shape.ShapeType, "Compound")
            self.assertEqual(len(shape.Solids), 1)
            self.assertEqual(len(shape.Solids[0].Faces), 7)
            self.assertExact(shape.Solids[0], 1000 - removed)
            faces, edges, vertices = loose_parts(shape)
            self.assertEqual((len(faces), len(edges), len(vertices)), (1, 0, 0))
            self.assertAlmostEqual(faces[0].Area, 100, delta=1e-9)
            self.assertTrue(faces[0].BoundBox.isInside(V(25, 5, 0)))

    def testPartFeaturesAtTheLimit(self):
        # Part::Fillet and Part::Chamfer build what OCCT refuses as makeFillet does (ops#300)
        box = Part.makeBox(30, 4, 20)
        edges = top_edges(box)
        fillet = self.dressUp("Fillet", box, edges, [(2, 2)] * 2)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertExact(fillet.Shape, 2400 - 2 * fillet_section(2) * 30)
        chamfer = self.dressUp("Chamfer", box, edges, [(2, 2)] * 2)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertExact(chamfer.Shape, 2400 - 4 * 30)

    def assertSameShape(self, shape, other):
        self.assertEqual(len(shape.Faces), len(other.Faces))
        self.assertEqual(len(shape.Edges), len(other.Edges))
        points = [
            sorted(tuple(round(c, 9) for c in v.Point) for v in s.Vertexes) for s in (shape, other)
        ]
        self.assertEqual(points[0], points[1])
        self.assertAlmostEqual(shape.Volume, other.Volume, delta=1e-9 * other.Volume)

    def testPartFeaturesBelowTheLimit(self):
        # OCCT's own result, the same as makeFillet's and makeChamfer's
        box = Part.makeBox(30, 4, 20)
        edges = top_edges(box)
        fillet = self.dressUp("Fillet", box, edges, [(1.5, 1.5)] * 2)
        self.assertSameShape(fillet.Shape, box.makeFillet(1.5, edges))
        self.assertExact(fillet.Shape, 2400 - 2 * fillet_section(1.5) * 30)
        chamfer = self.dressUp("Chamfer", box, edges, [(1.5, 1)] * 2)
        self.assertSameShape(chamfer.Shape, box.makeChamfer(1.5, 1, edges))
        self.assertExact(chamfer.Shape, 2400 - 2 * 0.75 * 30)

    def testPartFeaturesUnequalCorner(self):
        # The plate's top edges, the long ones at r = t and the short ones at 3: OCCT fails, and
        # a corner of unequal radii keeps its error
        plate = Part.makeBox(30, 20, 4)
        long_edges = [
            edge_between(plate, (0, 0, 4), (30, 0, 4)),
            edge_between(plate, (0, 20, 4), (30, 20, 4)),
        ]
        short_edges = [
            edge_between(plate, (0, 0, 4), (0, 20, 4)),
            edge_between(plate, (30, 0, 4), (30, 20, 4)),
        ]
        fillet = self.dressUp(
            "Fillet", plate, long_edges + short_edges, [(4, 4)] * 2 + [(3, 3)] * 2
        )
        self.assertFalse(fillet.isValid())
        self.assertEqual(fillet.getStatusString(), "BRep_API: command not done")
        # The same corners with equal radii are built
        fillet = self.dressUp("Fillet", plate, long_edges + short_edges, [(4, 4)] * 4)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        miter = 5.0 / 3 - math.pi / 2
        self.assertExact(fillet.Shape, 2400 - (100 * fillet_section(4) - 4 * 64 * miter))

    def testPartFeaturesPerEdgeSizes(self):
        # Different sizes per edge: OCCT's maker as before, with the check
        box = Part.makeBox(30, 4, 20)
        edges = top_edges(box)
        fillet = self.dressUp("Fillet", box, edges, [(1, 1), (1.5, 1.5)])
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertExact(fillet.Shape, 2400 - (fillet_section(1) + fillet_section(1.5)) * 30)
        chamfer = self.dressUp("Chamfer", box, edges, [(1, 1), (1.5, 1.5)])
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertExact(chamfer.Shape, 2400 - (0.5 + 1.125) * 30)

    def testPartFeaturesThinFace(self):
        # ops#298: Part::Fillet and Part::Chamfer build the fused stadium's whole outline
        # exactly, where OCCT keeps a face of area 0. With a size per edge they use OCCT's maker,
        # and fail on a top left narrower than its tolerance (rounds of 2 - 1e-8 and 2 - 2e-8 on
        # the 4 mm top)
        plate, outline = fused_stadium()
        fillet = self.dressUp("Fillet", plate, outline, [(2, 2)] * 5)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertExact(fillet.Shape, fused_stadium_rounded(2))
        self.assertGreater(narrowest(fillet.Shape, plate), 0.5)
        chamfer = self.dressUp("Chamfer", plate, outline, [(2, 2)] * 5)
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        self.assertGreater(narrowest(chamfer.Shape, plate), 0.5)
        box = Part.makeBox(30, 4, 20)
        fillet = self.dressUp("Fillet", box, top_edges(box), [(2 - 1e-8,) * 2, (2 - 2e-8,) * 2])
        self.assertFalse(fillet.isValid())
        self.assertIn("face of zero width", fillet.getStatusString())
        fillet = self.dressUp("Fillet", box, top_edges(box), [(2 - 1e-5,) * 2, (2 - 2e-5,) * 2])
        self.assertTrue(fillet.isValid(), fillet.getStatusString())


def loose_parts(shape):
    """The shape's faces outside its shells, edges outside its faces and vertices outside its
    edges"""
    shell_faces = [f for s in shape.Shells for f in s.Faces]
    faces = [f for f in shape.Faces if not any(f.isSame(g) for g in shell_faces)]
    face_edges = [e for f in shape.Faces for e in f.Edges]
    edges = [e for e in shape.Edges if not any(e.isSame(g) for g in face_edges)]
    edge_vertices = [v for e in shape.Edges for v in e.Vertexes]
    vertices = [v for v in shape.Vertexes if not any(v.isSame(w) for w in edge_vertices)]
    return faces, edges, vertices


def cube_beside_loose_parts():
    """A 10 mm cube in a compound with a 10 mm square face, a 10 mm line, a wire of two 10 mm
    lines and a vertex, all outside it"""
    square = [V(20, 0, 0), V(30, 0, 0), V(30, 10, 0), V(20, 10, 0)]
    return Part.Compound(
        [
            Part.makeBox(10, 10, 10),
            Part.Face(Part.makePolygon(square, True)),
            Part.makeLine(V(40, 0, 0), V(50, 0, 0)),
            Part.makePolygon([V(60, 0, 0), V(70, 0, 0), V(70, 10, 0)]),
            Part.Vertex(V(80, 0, 0)),
        ]
    )


def pad_on_dressed_up_base(doc, kind, size):
    """A PartDesign Body with Allow Compound whose BaseFeature is cube_beside_loose_parts(); a
    Fillet or Chamfer of the cube's front top edge; a Pad 3 high of a 4 mm square on its top, clear
    of the dress-up. Returns the Pad (for the PartDesign tests)"""
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = cube_beside_loose_parts()
    body = doc.addObject("PartDesign::Body", "Body")
    body.AllowCompound = True
    body.BaseFeature = base
    doc.recompute()
    dressed = body.newObject("PartDesign::" + kind, kind)
    edge = edge_between(base.Shape, (0, 0, 10), (10, 0, 10))
    index = next(i for i, e in enumerate(base.Shape.Edges, 1) if e.isSame(edge))
    dressed.Base = (body.BaseFeature, ["Edge%d" % index])
    if kind == "Fillet":
        dressed.Radius = size
    else:
        dressed.Size = size
    doc.recompute()
    sketch = body.newObject("Sketcher::SketchObject", "Sketch")
    sketch.Placement = FreeCAD.Placement(V(0, 0, 10), FreeCAD.Rotation())
    corners = [V(2, 2, 0), V(6, 2, 0), V(6, 6, 0), V(2, 6, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Length = 3
    doc.recompute()
    return pad


def cube_with_void(origin, size):
    """A 10 mm cube with a box-shaped void"""
    return Part.makeBox(10, 10, 10).cut(Part.makeBox(*size, V(*origin)))


def cube_with_moved_void(shell):
    """The 10 mm cube with a 2 mm void whose shell is replaced: an invalid solid"""
    solid = cube_with_void((4, 6, 6), (2, 2, 2))
    void = next(s for s in solid.Shells if s.BoundBox.XLength < 3)
    return solid.replaceShape([(void, shell(void))])


class DroppedBasePartsTest(unittest.TestCase):
    """OCCT's fillet and chamfer drop parts of the base they leave alone (ops#303): its faces,
    wires, edges and vertices outside its shells, and the shells of a solid they change that don't
    bound the rebuilt solid. Part::Fillet and Part::Chamfer put the loose parts back, and fail
    where a lost shell bounds material or a lost void is now inside material.
    """

    setUp = InvalidDressUpTest.setUp
    tearDown = InvalidDressUpTest.tearDown
    dressUp = InvalidDressUpTest.dressUp
    assertFails = InvalidDressUpTest.assertFails

    def testLoosePartsOfTheBaseStay(self):
        base = cube_beside_loose_parts()
        front = edge_between(base, (0, 0, 10), (10, 0, 10))
        back = edge_between(base, (0, 10, 10), (10, 10, 10))
        # One size, and a size per edge (OCCT's maker in Part::Fillet itself)
        two = [(1, 1), (0.5, 0.5)]
        for kind, edges, sizes, removed in (
            ("Fillet", [front], [(1, 1)], fillet_section(1) * 10),
            ("Chamfer", [front], [(1, 1)], 0.5 * 10),
            ("Fillet", [front, back], two, (fillet_section(1) + fillet_section(0.5)) * 10),
            ("Chamfer", [front, back], two, (0.5 + 0.125) * 10),
        ):
            feature = self.dressUp(kind, base, edges, sizes)
            self.assertTrue(feature.isValid(), feature.getStatusString())
            shape = feature.Shape
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids), 1)
            self.assertAlmostEqual(shape.Solids[0].Volume, 1000 - removed, delta=1e-6)
            faces, edges, vertices = loose_parts(shape)
            self.assertEqual((len(faces), len(edges), len(vertices)), (1, 3, 1))
            self.assertAlmostEqual(faces[0].Area, 100, delta=1e-9)
            self.assertAlmostEqual(sum(e.Length for e in edges), 30, delta=1e-9)
            self.assertEqual(len(shape.Wires), len(shape.Solids[0].Wires) + 2)
            self.assertTrue(vertices[0].Point.isEqual(V(80, 0, 0), 1e-12))

    def testSecondOuterShellFails(self):
        # The cube's solid with a second outer shell, a 5 mm cube beside it: OCCT's result is the
        # dressed-up cube alone, valid, without the 125 mm3 of the second shell
        base = cube_with_moved_void(lambda void: Part.makeBox(5, 5, 5, V(20, 0, 0)).Shells[0])
        self.assertAlmostEqual(base.Volume, 1125, delta=1e-9)
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        for kind in ("Fillet", "Chamfer"):
            self.assertFails(self.dressUp(kind, base, [edge], [(1, 1)]))

    def testChamferIntoAVoidFails(self):
        # A void 4 x 2 x 2 under the front top edge, which a chamfer of 3 cuts into: OCCT's result
        # has no void and the volume of the plain cube's chamfer, as if material filled it. A
        # fillet of 3 stays clear of the void ((3 - y)^2 + (z - 7)^2 <= 8 there), and keeps it
        base = cube_with_void((3, 1, 7), (4, 2, 2))
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        self.assertFails(self.dressUp("Chamfer", base, [edge], [(3, 3)]))
        fillet = self.dressUp("Fillet", base, [edge], [(3, 3)])
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertEqual(len(fillet.Shape.Shells), 2)
        self.assertAlmostEqual(fillet.Shape.Volume, 1000 - fillet_section(3) * 10 - 16, delta=1e-6)

    def testChamferIntoACurvedVoidFails(self):
        # A void a chamfer cuts into where no vertex or edge of it is (PR 341 review): a bore along
        # the edge, and a sphere centred on the chamfer's plane with its seam away from the cut.
        # OCCT's result has no void and the plain cube's chamfer volume
        cube = Part.makeBox(20, 20, 20)
        bore = cube.cut(Part.makeCylinder(1.9, 12, V(4, 1.95, 18.05), V(1, 0, 0)))
        edge = edge_between(bore, (0, 0, 20), (20, 0, 20))
        self.assertFails(self.dressUp("Chamfer", bore, [edge], [(6, 6)]))
        sphere = Part.makeSphere(2, V(0, 0, 0), V(1, 0, 0))
        sphere.translate(V(5, 3, 7))
        base = Part.makeBox(10, 10, 10).cut(sphere)
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        self.assertFails(self.dressUp("Chamfer", base, [edge], [(6, 6)]))

    def testVoidsOfSeveralSolids(self):
        # Two cubes with a void each: A's 4 x 2 x 2 void under its front top edge, which a chamfer
        # of 3 cuts into and a fillet of 3 clears; B's 2 mm void away from its edges
        a = cube_with_void((3, 1, 7), (4, 2, 2))
        b = Part.makeBox(10, 10, 10, V(20, 0, 0)).cut(Part.makeBox(2, 2, 2, V(24, 4, 4)))
        base = Part.Compound([a, b])
        front_a = edge_between(base, (0, 0, 10), (10, 0, 10))
        front_b = edge_between(base, (20, 0, 10), (30, 0, 10))
        self.assertFails(self.dressUp("Chamfer", base, [front_a], [(3, 3)]))
        for kind, edge, removed in (
            ("Chamfer", front_b, 4.5 * 10),
            ("Fillet", front_a, fillet_section(3) * 10),
            ("Fillet", front_b, fillet_section(3) * 10),
        ):
            feature = self.dressUp(kind, base, [edge], [(3, 3)])
            self.assertTrue(feature.isValid(), feature.getStatusString())
            self.assertEqual(len(feature.Shape.Solids), 2)
            self.assertEqual(len(feature.Shape.Shells), 4)
            self.assertAlmostEqual(feature.Shape.Volume, 2000 - 16 - 8 - removed, delta=1e-6)

    def testIslandInACavityFails(self):
        # A 20 mm cube's solid with an 8 mm cavity and a 2 mm island inside it, a third shell of the
        # same solid (invalid): OCCT's dress-up of an outer edge drops the island and its material
        hollow = Part.makeBox(20, 20, 20).cut(Part.makeBox(8, 8, 8, V(6, 6, 6)))
        hollow = hollow.cut(Part.makeBox(1, 1, 1, V(1, 1, 1)))
        small = next(s for s in hollow.Shells if s.BoundBox.XLength < 1.5)
        base = hollow.replaceShape([(small, Part.makeBox(2, 2, 2, V(9, 9, 9)).Shells[0])])
        self.assertAlmostEqual(base.Volume, 8000 - 512 + 8, delta=1e-9)
        edge = edge_between(base, (0, 0, 20), (20, 0, 20))
        for kind in ("Fillet", "Chamfer"):
            self.assertFails(self.dressUp(kind, base, [edge], [(3, 3)]))

    def testSolidInsideARemovedVoidStays(self):
        # The void the chamfer of 3 removes with its material, holding a 1 x 0.2 x 0.2 box, another
        # solid of the compound: the box was there in the base, so it fills nothing (PR 341 round 1
        # verification)
        cube = cube_with_void((3, 0.2, 9.3), (4, 0.5, 0.5))
        base = Part.Compound([cube, Part.makeBox(1, 0.2, 0.2, V(4, 0.35, 9.45))])
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        feature = self.dressUp("Chamfer", base, [edge], [(3, 3)])
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertEqual(len(feature.Shape.Solids), 2)
        self.assertAlmostEqual(feature.Shape.Volume, 1000 - 4.5 * 10 + 0.04, delta=1e-6)

    def testVoidRemovedWithItsMaterialStaysRemoved(self):
        # A void 4 x 0.5 x 0.5 inside the wedge a chamfer or fillet of 3 removes, and a void moved
        # outside the cube (an invalid solid): neither bounds what is left, and the result is the
        # plain cube's
        consumed = cube_with_void((3, 0.2, 9.3), (4, 0.5, 0.5))
        outside = cube_with_moved_void(lambda void: void.translated(V(20, 0, 0)))
        # A sphere's space and the solid around it share its face, where OCCT's Common warns
        sphere = Part.makeBox(10, 10, 10).cut(Part.makeSphere(0.2, V(5, 0.5, 9.5)))
        for base in (consumed, outside, sphere):
            edge = edge_between(base, (0, 0, 10), (10, 0, 10))
            for kind, removed in (("Fillet", fillet_section(3) * 10), ("Chamfer", 4.5 * 10)):
                feature = self.dressUp(kind, base, [edge], [(3, 3)])
                self.assertTrue(feature.isValid(), feature.getStatusString())
                self.assertEqual(len(feature.Shape.Shells), 1)
                self.assertAlmostEqual(feature.Shape.Volume, 1000 - removed, delta=1e-6)


def front_top_removed(kind, size):
    """What a fillet or chamfer of the size on the front top edge of the 10 mm cube removes: the
    prism z > 10 - size + y, or the square y < r, z > 10 - r outside the round's cylinder (1 mm past
    the cube's sides)"""
    if kind == "Chamfer":
        corners = [V(-1, 0, 10 - size), V(-1, size, 10), V(-1, -1, 10), V(-1, -1, 10 - size)]
        return Part.Face(Part.makePolygon(corners, True)).extrude(V(12, 0, 0))
    square = Part.makeBox(12, size + 1, size + 1, V(-1, -1, 10 - size))
    return square.cut(Part.makeCylinder(size, 12, V(-1, size, 10 - size), V(1, 0, 0)))


def concave_block():
    """The 10 mm cube without its quarter y > 5, z > 5: an L whose concave edge runs along x at
    y = z = 5"""
    return Part.makeBox(10, 10, 10).cut(Part.makeBox(12, 6, 6, V(-1, 5, 5)))


def concave_added(kind, size):
    """What a fillet or chamfer of the size on concave_block()'s concave edge adds: the square
    5 < y, z < 5 + r outside the round's cylinder, or the triangle y + z < 10 + size"""
    if kind == "Chamfer":
        corners = [V(0, 5, 5), V(0, 5 + size, 5), V(0, 5, 5 + size)]
        return Part.Face(Part.makePolygon(corners, True)).extrude(V(10, 0, 0))
    square = Part.makeBox(10, size, size, V(0, 5, 5))
    return square.cut(Part.makeCylinder(size, 10, V(0, 5 + size, 5 + size), V(1, 0, 0)))


# The round on rounded_concave_block()'s outer floor edge: its axis runs along x at y = 6, z = 1
FLOOR_ROUND = 4


def rounded_concave_block():
    """concave_block() with its outer floor edge (y = 10, z = 5) rounded 4: the floor ends at
    y = 6 and runs on into the round, tangentially"""
    block = concave_block()
    return block.makeFillet(FLOOR_ROUND, [edge_between(block, (0, 10, 5), (10, 10, 5))])


def concave_added_onto_round(kind, size):
    """What a fillet or chamfer of the size (over 1) on rounded_concave_block()'s concave edge adds,
    its band running on from the floor onto the round: under the rolling ball of the size that
    touches the wall y = 5 and the round, or under the chord from the wall at z = 5 + size to the
    round's point at the size's distance from the edge"""
    R = FLOOR_ROUND
    axis_y, axis_z = 10 - R, 5 - R
    if kind == "Chamfer":
        # The round's point (axis_y + R sin t, axis_z + R cos t) at the distance size from
        # (5, 5): a sin t + b cos t = k
        a, b = 2 * R * (axis_y - 5), 2 * R * (axis_z - 5)
        k = size**2 - (axis_y - 5) ** 2 - (axis_z - 5) ** 2 - R**2
        t = math.asin(k / math.hypot(a, b)) - math.atan2(b, a)
        y, z = axis_y + R * math.sin(t), axis_z + R * math.cos(t)
        corners = [V(0, 5, 5 + size), V(0, y, z), V(0, y, 3), V(0, 5, 3)]
        return Part.Face(Part.makePolygon(corners, True)).extrude(V(10, 0, 0))
    ball_y = 5 + size
    ball_z = axis_z + math.sqrt((R + size) ** 2 - (ball_y - axis_y) ** 2)
    contact_y = axis_y + (ball_y - axis_y) * R / (R + size)
    box = Part.makeBox(10, contact_y - 5, ball_z - 3, V(0, 5, 3))
    return box.cut(Part.makeCylinder(size, 10, V(0, ball_y, ball_z), V(1, 0, 0)))


def dimpled(shape, x, y, top):
    """The shape with a spherical dimple r 1 at (x, y, top - 0.4) in its face z = top, the dimple's
    rim rounded 0.15: the face, the rim and the dimple each join the next smoothly"""
    dimpled = shape.cut(Part.makeSphere(1, V(x, y, top - 0.4)))
    rim = [
        e
        for e in dimpled.Edges
        if abs(e.BoundBox.ZMin - top) < 1e-6
        and abs(e.BoundBox.ZMax - top) < 1e-6
        and x - 1.01 < e.BoundBox.XMin
        and e.BoundBox.XMax < x + 1.01
        and y - 1.01 < e.BoundBox.YMin
        and e.BoundBox.YMax < y + 1.01
    ]
    return dimpled.makeFillet(0.15, rim)


def smoothly_dimpled_block():
    """concave_block() with its wall's top edge (y = 5, z = 10) rounded 1, and that block with a
    dimpled() at (5, 1.2) in its top face: the wall, the round, the top face, the rim and the dimple
    each join the next smoothly. Returns both"""
    block = concave_block()
    block = block.makeFillet(1, [edge_between(block, (0, 5, 10), (10, 5, 10))])
    return block, dimpled(block, 5, 1.2, 10)


def deep_concave_block():
    """The block 10 x 14 x 10 without its part y > 5, z > 5: an L like concave_block() whose floor
    (z = 5) runs on to y = 14"""
    return Part.makeBox(10, 14, 10).cut(Part.makeBox(12, 10, 6, V(-1, 5, 5)))


def outer_floor_removed(kind, size):
    """What a fillet or chamfer of the size on deep_concave_block()'s outer floor edge (y = 14,
    z = 5) removes: the prism y + z > 19 - size, or the square y > 14 - r, z > 5 - r outside the
    round's cylinder (1 mm past the block's sides)"""
    if kind == "Chamfer":
        corners = [
            V(-1, 14 - size, 5),
            V(-1, 14 - size, 6),
            V(-1, 15, 6),
            V(-1, 15, 5 - size),
            V(-1, 14, 5 - size),
        ]
        return Part.Face(Part.makePolygon(corners, True)).extrude(V(12, 0, 0))
    square = Part.makeBox(12, size + 1, size + 1, V(-1, 14 - size, 5 - size))
    return square.cut(Part.makeCylinder(size, 12, V(-1, 14 - size, 5 - size), V(1, 0, 0)))


def upright_concave_block():
    """The 10 mm cube without its quarter x > 5, y > 5: its concave edge runs along z at x = y = 5"""
    return Part.makeBox(10, 10, 10).cut(Part.makeBox(6, 6, 12, V(5, 5, -1)))


def upright_concave_added(kind, size):
    """What a fillet or chamfer of the size on upright_concave_block()'s concave edge adds: the
    square 5 < x, y < 5 + r outside the round's cylinder, or the triangle x + y < 10 + size"""
    if kind == "Chamfer":
        corners = [V(5, 5, 0), V(5 + size, 5, 0), V(5, 5 + size, 0)]
        return Part.Face(Part.makePolygon(corners, True)).extrude(V(0, 0, 10))
    square = Part.makeBox(size, size, 10, V(5, 5, 0))
    return square.cut(Part.makeCylinder(size, 10, V(5 + size, 5 + size, 0)))


def dressed_up_in_a_body(doc, kind, recess, size):
    """A PartDesign Body whose BaseFeature is the 10 mm cube without the recess, and a Fillet or
    Chamfer of the size on the cube's front top edge (for the PartDesign tests). Returns the
    feature and the edge's name"""
    shape = Part.makeBox(10, 10, 10).cut(recess)
    return dressed_in_a_body(doc, kind, shape, ((0, 0, 10), (10, 0, 10)), size)


def dressed_in_a_body(doc, kind, shape, ends, size, *more):
    """A PartDesign Body whose BaseFeature is the shape, and a Fillet or Chamfer of the size on its
    edge between the two points (and on those between more pairs). Returns the feature and the
    (first) edge's name"""
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = shape
    body = doc.addObject("PartDesign::Body", "Body")
    body.BaseFeature = base
    doc.recompute()
    dressed = body.newObject("PartDesign::" + kind, kind)
    names = []
    for pair in (ends,) + more:
        edge = edge_between(base.Shape, *pair)
        index = next(i for i, e in enumerate(base.Shape.Edges, 1) if e.isSame(edge))
        names.append("Edge%d" % index)
    dressed.Base = (body.BaseFeature, names)
    if kind == "Fillet":
        dressed.Radius = size
    else:
        dressed.Size = size
    doc.recompute()
    return dressed, names[0]


class FilledRecessTest(unittest.TestCase):
    """OCCT's fillet and chamfer cover the opening of a recess their band crosses in a face next to
    the edge (a blind pocket, a notch, a hole), and fill the recess under the new face: a valid
    solid with the volume of the plain dress-up (ops#393). The result must be the Boolean
    construction (the base without the recess, dressed up, without the recess again), or the
    feature fails naming the edge.
    """

    setUp = InvalidDressUpTest.setUp
    tearDown = InvalidDressUpTest.tearDown
    dressUp = InvalidDressUpTest.dressUp

    def assertExactOrFails(self, feature, base, edge, expected):
        if feature.isValid():
            self.assertTrue(feature.Shape.isValid())
            self.assertAlmostEqual(feature.Shape.Volume, expected, delta=1e-6)
            return
        index = next(i for i, e in enumerate(base.Edges, 1) if e.isSame(edge))
        self.assertTrue(
            feature.getStatusString().startswith(
                "The %s fills a recess of the base next to Edge%d:"
                % (feature.TypeId[6:].lower(), index)
            ),
            feature.getStatusString(),
        )

    def assertFront(self, recess, kinds=("Chamfer", "Fillet")):
        """The cube without the recess, dressed up 3 on its front top edge"""
        base = Part.makeBox(10, 10, 10).cut(recess)
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        for kind in kinds:
            with self.subTest(kind=kind):
                expected = Part.makeBox(10, 10, 10).cut(front_top_removed(kind, 3)).cut(recess)
                feature = self.dressUp(kind, base, [edge], [(3, 3)])
                self.assertExactOrFails(feature, base, edge, expected.Volume)

    def testBandAcrossABlindPocket(self):
        # The issue's pocket, open at the top: chamfer 951 (OCCT 955), fillet 973.439 (980.686)
        self.assertFront(Part.makeBox(4, 1, 2, V(3, 1.5, 8)))

    def testBandAcrossAShallowerPocket(self):
        # z0 = 8.5, dz = 1.5: chamfer 953 (OCCT 955), fillet 975.439 (980.686)
        self.assertFront(Part.makeBox(4, 1, 1.5, V(3, 1.5, 8.5)))

    def testBandAcrossANotchInTheSideFace(self):
        # Open on the top and the right face: the top face has no inner wire. Chamfer 953, fillet
        # 977.062 (OCCT 955, 980.686)
        self.assertFront(Part.makeBox(2, 1, 2, V(8, 1.5, 8)))

    def testBandAcrossAPocketInTheFrontFace(self):
        # Open on the front face, under the edge: chamfer 954.5, fillet 975.881 (OCCT 955, 980.686)
        self.assertFront(Part.makeBox(4, 2, 1, V(3, 0, 8.5)))

    def testBandAcrossARoundHole(self):
        # A blind hole r 0.6, 2 deep: chamfer 953.869, fillet 978.638 (OCCT 955, 980.686)
        self.assertFront(Part.makeCylinder(0.6, 2, V(5, 2, 8)))

    def testBandAcrossAPocketWithASizePerEdge(self):
        # The front edge 3 and the back one 1: Part's own maker (a size per edge), not makeFillet
        recess = Part.makeBox(4, 1, 2, V(3, 1.5, 8))
        base = Part.makeBox(10, 10, 10).cut(recess)
        front = edge_between(base, (0, 0, 10), (10, 0, 10))
        back = edge_between(base, (0, 10, 10), (10, 10, 10))
        for kind, back_removed in (("Chamfer", 0.5 * 10), ("Fillet", fillet_section(1) * 10)):
            with self.subTest(kind=kind):
                cut = Part.makeBox(10, 10, 10).cut(front_top_removed(kind, 3)).cut(recess)
                feature = self.dressUp(kind, base, [front, back], [(3, 3), (1, 1)])
                self.assertExactOrFails(feature, base, front, cut.Volume - back_removed)

    def testConcaveBandOverAPocket(self):
        # A pocket 4 x 1 x 1 in the L's floor under the round of 2 on its concave edge: OCCT's
        # result has the pocket filled (758.584 for 754.584; the chamfer 770 for 766). The
        # material a concave edge adds in its corner and the filled pocket are one piece
        recess = Part.makeBox(4, 1, 1, V(3, 5.5, 4))
        base = concave_block().cut(recess)
        edge = edge_between(base, (0, 5, 5), (10, 5, 5))
        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                expected = concave_block().fuse(concave_added(kind, 2)).cut(recess)
                feature = self.dressUp(kind, base, [edge], [(2, 2)])
                self.assertExactOrFails(feature, base, edge, expected.Volume)

    def testConcaveBandStays(self):
        # The concave edge's round or chamfer adds material: right, and kept, also beside a
        # pocket the band doesn't reach (y 8 to 9; the band ends at y = 7)
        for recess in (None, Part.makeBox(4, 1, 1, V(3, 8, 4))):
            base = concave_block() if recess is None else concave_block().cut(recess)
            edge = edge_between(base, (0, 5, 5), (10, 5, 5))
            for kind in ("Fillet", "Chamfer"):
                with self.subTest(kind=kind, recess=recess is not None):
                    expected = base.fuse(concave_added(kind, 2)).Volume
                    feature = self.dressUp(kind, base, [edge], [(2, 2)])
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    self.assertAlmostEqual(feature.Shape.Volume, expected, delta=1e-6)

    def testConcaveBandOntoATangentRound(self):
        # The L's floor ends in a round R4 at y = 6, and a concave round or chamfer of 1.5 to 2.5
        # runs on from the floor onto it. The round holds no vertex of the edge and the dress-up
        # trims it, so the check runs: the material added on the round is the corner's, not a
        # filled recess (PR 346 review, H1; 153729a478 failed all six with "fills a recess")
        base = rounded_concave_block()
        edge = edge_between(base, (0, 5, 5), (10, 5, 5))
        for kind in ("Fillet", "Chamfer"):
            for size in (1.5, 2, 2.5):
                with self.subTest(kind=kind, size=size):
                    expected = base.fuse(concave_added_onto_round(kind, size)).Volume
                    feature = self.dressUp(kind, base, [edge], [(size, size)])
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    self.assertAlmostEqual(feature.Shape.Volume, expected, delta=1e-5)

    def testConcaveBandWhileTheCheckRuns(self):
        # The L's concave edge 2 and its front top edge 1, with a pocket 2 x 0.15 x 0.4 at the top
        # that the front's round or chamfer removes whole: its faces go, so the check runs, and
        # the concave edge's material passes (PR 346 review, L4; 756.438 and 765)
        recess = Part.makeBox(2, 0.15, 0.4, V(4, 0.05, 9.85))
        base = concave_block().cut(recess)
        edges = [
            edge_between(base, (0, 5, 5), (10, 5, 5)),
            edge_between(base, (0, 0, 10), (10, 0, 10)),
        ]
        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                added = concave_block().fuse(concave_added(kind, 2))
                expected = added.cut(front_top_removed(kind, 1)).Volume
                feature = self.dressUp(kind, base, edges, [(2, 2), (1, 1)])
                self.assertTrue(feature.isValid(), feature.getStatusString())
                # The L's 8 faces and the two new ones: the pocket's are gone
                self.assertEqual(len(feature.Shape.Faces), 10)
                self.assertAlmostEqual(feature.Shape.Volume, expected, delta=1e-6)

    def testConvexBandOverASmoothDimple(self):
        # The front top edge's chamfer or round of 2.5 crosses smoothly_dimpled_block()'s dimple,
        # with the concave edge's of 1 in the same feature. Every face from the concave edge's wall
        # to the dimple joins the next smoothly, but the faces the concave edge's material may lie
        # on grow only through faces the dress-up changes, and it leaves the wall's round alone:
        # the filled dimple is still caught. OCCT fills it (721.604 for 721.239, the fillet 736.587
        # for 734.550), and 8e642b9516 let both pass (PR 346 round 2)
        block, base = smoothly_dimpled_block()
        dimple = block.cut(base)
        front = edge_between(base, (0, 0, 10), (10, 0, 10))
        concave = edge_between(base, (0, 5, 5), (10, 5, 5))
        for kind in ("Chamfer", "Fillet"):
            with self.subTest(kind=kind):
                dressed = block.cut(front_top_removed(kind, 2.5)).fuse(concave_added(kind, 1))
                feature = self.dressUp(kind, base, [front, concave], [(2.5, 2.5), (1, 1)])
                self.assertExactOrFails(feature, base, front, dressed.cut(dimple).Volume)

    def testConvexBandOverASmoothDimpleInTheConcaveEdgesFace(self):
        # A dimpled() face under a convex edge's band of 2.5 that holds a vertex of a concave edge
        # dressed 1 in the same feature: deep_concave_block()'s floor under its outer floor edge's
        # band, or upright_concave_block()'s top face under its front top edge's. The face is one
        # the concave edge's material may lie on, and the dimple's faces join it smoothly and change
        # as the dimple is filled. OCCT fills it (floor 923.750 for 923.385, the fillet 938.733 for
        # 936.696; top 723.750 for 723.385, 738.733 for 736.695), and 2b534f9017 let all four pass:
        # the filled dimple lies apart from the concave edge (PR 346 round 3)
        floor = (
            deep_concave_block(),
            (5, 12.8, 5),
            ((0, 14, 5), (10, 14, 5)),
            outer_floor_removed,
            ((0, 5, 5), (10, 5, 5)),
            concave_added,
        )
        top = (
            upright_concave_block(),
            (3, 1.2, 10),
            ((0, 0, 10), (10, 0, 10)),
            front_top_removed,
            ((5, 5, 0), (5, 5, 10)),
            upright_concave_added,
        )
        for name, (block, at, convex, removed, concave, added) in (("floor", floor), ("top", top)):
            base = dimpled(block, *at)
            dimple = block.cut(base)
            edges = [edge_between(base, *convex), edge_between(base, *concave)]
            for kind in ("Chamfer", "Fillet"):
                with self.subTest(face=name, kind=kind):
                    dressed = block.cut(removed(kind, 2.5)).fuse(added(kind, 1))
                    feature = self.dressUp(kind, base, edges, [(2.5, 2.5), (1, 1)])
                    self.assertExactOrFails(feature, base, edges[0], dressed.cut(dimple).Volume)

    def testPocketOutOfReachStays(self):
        # A pocket 4 x 1 x 2 at y 6 to 7, beyond the band (y < 3): untouched, 947 and 972.686
        recess = Part.makeBox(4, 1, 2, V(3, 6, 8))
        base = Part.makeBox(10, 10, 10).cut(recess)
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        for kind, removed in (("Chamfer", 4.5 * 10), ("Fillet", fillet_section(3) * 10)):
            with self.subTest(kind=kind):
                feature = self.dressUp(kind, base, [edge], [(3, 3)])
                self.assertTrue(feature.isValid(), feature.getStatusString())
                self.assertEqual(len(feature.Shape.Faces), len(base.Faces) + 1)
                self.assertAlmostEqual(feature.Shape.Volume, 1000 - 8 - removed, delta=1e-6)

    def testPocketTheChamferRemovesStaysRemoved(self):
        # A pocket 4 x 1 x 0.5 at the top, y 0.5 to 1.5: above the chamfer's plane, so the chamfer
        # removes it with its material (955). Its faces go, which sends the result to the Boolean
        recess = Part.makeBox(4, 1, 0.5, V(3, 0.5, 9.5))
        base = Part.makeBox(10, 10, 10).cut(recess)
        edge = edge_between(base, (0, 0, 10), (10, 0, 10))
        feature = self.dressUp("Chamfer", base, [edge], [(3, 3)])
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertAlmostEqual(feature.Shape.Volume, 1000 - 4.5 * 10, delta=1e-6)


def tolerances(shape):
    return [s.Tolerance for s in shape.Vertexes + shape.Edges + shape.Faces]


class BaseToleranceTest(unittest.TestCase):
    """OCCT's fillet and chamfer maker raises its input's tolerances in place, to 1e-4 at the
    vertices where a round or chamfer ends against a wall, and a Part::Fillet's or Part::Chamfer's
    input shares its TShapes with the base feature's stored Shape. The maker runs on a copy: the
    base keeps its own tolerances, and the result those the maker raised (ops#345).
    """

    def setUp(self):
        self.doc = FreeCAD.newDocument("BaseToleranceTest")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    def base(self, placement=None):
        rib, _ = rib_against_wall()
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = rib
        if placement:
            base.Placement = placement
        self.doc.recompute()
        self.assertLess(max(tolerances(base.Shape)), 1e-6)
        return base

    def dressUp(self, kind, base, sizes):
        feature = self.doc.addObject("Part::" + kind, kind)
        feature.Base = base
        # The rib's top edges found where it was built, a placed Base's included
        unplaced = base.Shape.copy()
        unplaced.Placement = FreeCAD.Placement()
        indices = [
            next(i for i, e in enumerate(unplaced.Edges, 1) if e.isSame(edge))
            for edge in top_edges(unplaced)
        ]
        feature.Edges = [(i, s, s) for i, s in zip(indices, sizes)]
        self.doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        return feature

    def testBaseKeepsItsTolerances(self):
        # The rib's two top edges just under the limit and below it, with one size (makeFillet's
        # and makeChamfer's path) and a size per edge (OCCT's maker in the feature)
        for kind in ("Chamfer", "Fillet"):
            for sizes in ([2 - 1e-5] * 2, [1.5] * 2, [2 - 1e-5, 2 - 2e-5]):
                with self.subTest(kind=kind, sizes=sizes):
                    base = self.base()
                    before = tolerances(base.Shape)
                    feature = self.dressUp(kind, base, sizes)
                    self.assertEqual(tolerances(base.Shape), before)
                    self.assertGreater(max(tolerances(feature.Shape)), 1e-5)

    def testPlacedBaseKeepsItsTolerances(self):
        # A Base with a placement: the selected edges are found in the copy of the placed shape,
        # and the result lies where the base does (PR 318 review, low 3)
        placement = FreeCAD.Placement(
            FreeCAD.Vector(7, -3, 2), FreeCAD.Rotation(FreeCAD.Vector(1, 2, 3), 35)
        )
        for kind in ("Chamfer", "Fillet"):
            for sizes in ([2 - 1e-5] * 2, [2 - 1e-5, 2 - 2e-5]):
                with self.subTest(kind=kind, sizes=sizes):
                    base = self.base(placement)
                    before = tolerances(base.Shape)
                    feature = self.dressUp(kind, base, sizes)
                    self.assertEqual(tolerances(base.Shape), before)
                    unplaced = self.dressUp(kind, self.base(), sizes)
                    self.assertAlmostEqual(feature.Shape.Volume, unplaced.Shape.Volume, places=9)
                    moved = unplaced.Shape.copy()
                    moved.Placement = placement.multiply(moved.Placement)
                    # A dress-up's shape is a compound of the one solid
                    self.assertAlmostEqual(
                        feature.Shape.Solids[0].CenterOfMass.distanceToPoint(
                            moved.Solids[0].CenterOfMass
                        ),
                        0,
                        places=7,
                    )

    def testSecondDressUpOnTheSameBase(self):
        # A second chamfer on the same base starts from the base's own tolerances, as the first
        # did: the check for merged faces takes its thresholds from them (PR 314 review, item 2)
        base = self.base()
        before = tolerances(base.Shape)
        first = self.dressUp("Chamfer", base, [2 - 1e-5] * 2)
        self.assertEqual(tolerances(base.Shape), before)
        second = self.dressUp("Chamfer", base, [2 - 1e-5] * 2)
        self.assertEqual(tolerances(base.Shape), before)
        self.assertEqual(tolerances(second.Shape), tolerances(first.Shape))
