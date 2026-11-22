# SPDX-License-Identifier: LGPL-2.1-or-later

"""The fillets and chamfers OCCT refuses, built exactly (ops#300).

OCCT fails whenever a fillet's or chamfer's new edge would land on an existing edge (a full round,
a chamfer to an edge). makeFillet and makeChamfer then build them as exact Booleans. Designed
models; the expectations are analytic volumes.
"""

import math
import time
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


def wave_prism(waves):
    """A prism over a cosine wave (ops#414). Its section in the plane z = 0: x from -5 to the wave
    x = 1.5 (1 - cos(2 pi y / 20)), interpolated by one cubic B-spline through points 1 mm apart
    (20 spans per wave), for y from 0 to the wave's length; extruded by 10"""
    length = 20 * waves
    points = [V(1.5 * (1 - math.cos(2 * math.pi * y / 20)), y, 0) for y in range(length + 1)]
    spline = Part.BSplineCurve()
    spline.interpolate(points)
    corners = [V(0, length, 0), V(-5, length, 0), V(-5, 0, 0), V(0, 0, 0)]
    edges = [spline.toShape()] + [Part.makeLine(a, b) for a, b in zip(corners, corners[1:])]
    return Part.Face(Part.Wire(edges)).extrude(V(0, 0, 10))


def ribbed_wave_prism(waves):
    """The wave prism with a rib along its flat side: the box x in [-9, -5], z in [3, 7] along the
    whole length. Its top x = -9 is 4 wide, so a round or chamfer of 2 on its two long edges is at
    the limit"""
    return wave_prism(waves).fuse(Part.makeBox(4, 20 * waves, 4, V(-9, 0, 3)))


def rim_edges(shape, z):
    return [
        e
        for e in shape.Edges
        if abs(e.BoundBox.ZMin - z) < 1e-9 and abs(e.BoundBox.ZMax - z) < 1e-9
    ]


def polar(radius, degrees, z=0.0):
    a = math.radians(degrees)
    return V(radius * math.cos(a), radius * math.sin(a), z)


def rim_ring(centre, rho, r, top):
    """The tool of a round r on the whole top rim of a solid vertical cylinder of radius rho about
    centre: the section (rim corner, quarter arc) revolved a full turn"""
    a = V(centre.x + rho, centre.y, top)
    b = V(centre.x + rho - r, centre.y, top)
    c = V(centre.x + rho, centre.y, top - r)
    q = V(centre.x + rho - r + r / math.sqrt(2), centre.y, top - r + r / math.sqrt(2))
    wire = Part.Wire([Part.makeLine(a, b), Part.Arc(b, q, c).toShape(), Part.makeLine(c, a)])
    return Part.Face(wire).revolve(V(centre.x, centre.y, 0), V(0, 0, 1), 360)


def tooth_on_a_round_root(height=6.0):
    """Oracle 18's FT2: a disc R 30, one tooth to R 34 over 84..96 degrees, its flanks arcs of
    radius 4 centred on the root circle (tangent to the tip), which meet the root at reflex
    corners. Returns the solid, and its pieces as (solid, centre, radius of its rim)"""
    centre = V(0, 0, 0)
    disc = Part.makeCylinder(30, height)
    flanks = [Part.makeCylinder(4, height, polar(30, a)) for a in (84, 96)]
    tip = Part.makeCylinder(34, height, centre, V(0, 0, 1), 12).rotated(centre, V(0, 0, 1), 84)
    tooth = disc.fuse(flanks + [tip]).removeSplitter()
    pieces = [(disc, centre, 30), (flanks[0], polar(30, 84), 4), (flanks[1], polar(30, 96), 4)]
    return tooth, pieces + [(tip, centre, 34)]


def toothed_wheel(teeth, pitch=11.25, height=3.0):
    """A disc R 30 with small teeth at the pitch (degrees): each tooth a tip arc R 31 over 2 degrees
    between two flanks of radius 1 centred on the root circle, which meet the root at reflex
    corners; with a rim round of 0.5 the flanks' tori are horn tori. Returns the solid and its top
    rim's edges"""
    centre = V(0, 0, 0)
    parts = []
    for k in range(teeth):
        a = k * pitch
        parts += [
            Part.makeCylinder(1.0, height, polar(30, a - 1.0)),
            Part.makeCylinder(1.0, height, polar(30, a + 1.0)),
            Part.makeCylinder(31, height, centre, V(0, 0, 1), 2.0).rotated(
                centre, V(0, 0, 1), a - 1.0
            ),
        ]
    wheel = Part.makeCylinder(30, height)
    if parts:
        wheel = wheel.fuse(parts).removeSplitter()
    return wheel, rim_edges(wheel, height)


def bump_on_an_edge(rho):
    """A 10 x 4 x 2 box with a half-disc bump of radius rho centred on its edge y = 4: the bump's
    rim meets the box's at two reflex corners. Returns the solid, the box and the bump"""
    box = Part.makeBox(10, 4, 2)
    bump = Part.makeCylinder(rho, 2, V(5, 4, 0))
    return box.fuse(bump).removeSplitter(), box, bump


def bump_rim_removed(rho, r):
    """What a round r of the whole top rim of bump_on_an_edge(rho) removes by Onshape's rule: at
    a plan point the round of each body that holds it removes h(depth behind that body's wall),
    h(d) = r - sqrt(r^2 - (r - d)^2) up to d = r, and the least of them is removed. That is the
    box's rim alone (closed form, mitres at its four corners), the bump's upper half ring
    (Pappus), and over the bump's lower half disc the difference min(h_box, h_bump) - h_box,
    integrated in polar coordinates about the bump's centre"""

    def h(d):
        return r - math.sqrt(max(r * r - (r - d) ** 2, 0.0)) if d < r else 0.0

    def over(f, a, b, panels=48):
        step = (b - a) / panels
        return sum(gauss_legendre(f, a + i * step, a + (i + 1) * step, 8) for i in range(panels))

    def ring(t):
        def f(x):
            behind_box = -x * math.sin(t)
            return (min(h(behind_box), h(rho - x)) - h(behind_box)) * x

        return over(f, 0, rho - r) + over(f, rho - r, rho)

    section = fillet_section(r)
    box_rim = section * (28 - 4 * 2 * fillet_centroid(r))
    upper_half = section * math.pi * (rho - fillet_centroid(r))
    return box_rim + upper_half + over(ring, math.pi, 2 * math.pi)


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
        # The two rounds are one half cylinder, as Onshape's (ops#900)
        self.assertEqual(len(result.Faces), 6)
        # Names as a fillet's: the round face is generated by its edges
        rounds = [
            name
            for name, index in result.ElementMap.items()
            if index.startswith("Face")
            and result.getElement(index).Surface.TypeId == "Part::GeomCylinder"
        ]
        # one face, which answers to each round's name (testFullRoundAnswersToEachRoundsName)
        self.assertEqual(len(rounds), 2)
        self.assertEqual(len({result.ElementMap[name] for name in rounds}), 1)
        for name in rounds:
            self.assertIn("FLT", name)
            self.assertIn("GEN", name)

    def testFullRoundAnswersToEachRoundsName(self):
        # Onshape keeps a reference to either round on the merged face at the limit, and it goes
        # back to its own round below; one made on the merged face goes to the round of the edge
        # first in the body's edge order, here the front one (oracle941 and oracle900r8, ops#900
        # R1-R8). So the merged face carries the names both rounds have below the limit, the front
        # round's first, and nothing else changes name
        box = Part.makeBox(30, 4, 20)
        box.Tag = 1
        edges = top_edges(box)
        below = box.makeFillet(1.9, edges)
        at = box.makeFillet(2, edges)

        def rounds(shape):
            return {
                name: index
                for name, index in shape.ElementMap.items()
                if index.startswith("Face")
                and shape.getElement(index).Surface.TypeId == "Part::GeomCylinder"
            }

        before = rounds(below)
        self.assertEqual(len(set(before.values())), 2)
        front = next(n for n, i in before.items() if below.getElement(i).CenterOfMass.y < 2)
        merged = rounds(at)
        self.assertEqual(set(merged), set(before))
        self.assertEqual(len(set(merged.values())), 1)
        first = at.getElementMappedName(merged[front])
        self.assertEqual(first[0] if isinstance(first, tuple) else first, front)
        # The faces the merge leaves alone keep their names: the ends, the sides, the bottom
        planes = lambda s: {n for n, i in s.ElementMap.items() if i.startswith("Face")} - set(
            rounds(s)
        )
        self.assertEqual(planes(at) - planes(below), set())
        self.assertEqual(len(planes(at)), 5)

    # The rib 30 x 4 x 20 drawn three ways (oracle900r8, ops#900 R8 by order: V1-V5b), with the
    # long edge of the segment drawn first: front for the first two, back for the others
    RIBS = (
        ("front first", [(0, 0), (30, 0), (30, 4), (0, 4)], "front"),
        ("back first", [(0, 4), (30, 4), (30, 0), (0, 0)], "back"),
        ("left, back, right, front", [(0, 0), (0, 4), (30, 4), (30, 0)], "back"),
    )

    def fullRoundFirstName(self, drawn, order):
        """The first name of the merged face of the rib's full round at r 2, as the round it
        names at r 1.9: "front" or "back", and the name itself"""
        points = [V(x, y, 0) for x, y in drawn]
        prism = Part.Face(Part.makePolygon(points + [points[0]])).extrude(V(0, 0, 20))
        prism.Tag = 1
        sides = {
            "front": edge_between(prism, (0, 0, 20), (30, 0, 20)),
            "back": edge_between(prism, (0, 4, 20), (30, 4, 20)),
        }
        edges = [sides[side] for side in order]
        below = prism.makeFillet(1.9, edges)
        at = prism.makeFillet(2, edges)
        merged = [
            f"Face{i}" for i, f in enumerate(at.Faces, 1) if f.Surface.TypeId == "Part::GeomCylinder"
        ]
        self.assertEqual(len(merged), 1)
        first = at.getElementMappedName(merged[0])
        first = first[0] if isinstance(first, tuple) else first
        y = below.getElement(below.ElementMap[first]).CenterOfMass.y
        return ("front" if y < 2 else "back"), first

    def testFullRoundIsNamedByTheEdgeDrawnFirst(self):
        # Onshape names the merged face after the round of the edge that comes first in the body's
        # edge order, the segment drawn first (oracle900r8, V1, V3, V5)
        for label, drawn, named in self.RIBS:
            with self.subTest(drawn=label):
                self.assertEqual(self.fullRoundFirstName(drawn, ("front", "back"))[0], named)

    def testFullRoundNameIgnoresTheSelectionOrder(self):
        # Selecting the edges the other way round gives the merged face the same name (oracle900r8,
        # V1/V2, V3/V4, V5/V5b): the selection order only turns the face in Onshape
        for label, drawn, named in self.RIBS:
            with self.subTest(drawn=label):
                forward = self.fullRoundFirstName(drawn, ("front", "back"))
                backward = self.fullRoundFirstName(drawn, ("back", "front"))
                self.assertEqual(backward, forward)
                self.assertEqual(backward[0], named)

    def testFullRoundOverTwoFilletsKeepsTheFirstFilletsName(self):
        # Two fillets, one long edge each, at r 2 (oracle900r8, V6, V7): the face of the first
        # fillet's round keeps its name, and the second's round never takes it. Onshape merges the
        # two rounds into one face named after the first fillet's; the fork keeps two faces on one
        # cylinder (ops#900, the merge across features is filed apart)
        rib = Part.Face(
            Part.makePolygon([V(0, 0, 0), V(30, 0, 0), V(30, 4, 0), V(0, 4, 0), V(0, 0, 0)])
        ).extrude(V(0, 0, 20))
        rib.Tag = 1
        ends = {"front": ((0, 0, 20), (30, 0, 20)), "back": ((0, 4, 20), (30, 4, 20))}

        def roundNames(shape):
            return {
                name
                for name, index in shape.ElementMap.items()
                if index.startswith("Face")
                and shape.getElement(index).Surface.TypeId == "Part::GeomCylinder"
            }

        for first, second in (("front", "back"), ("back", "front")):
            with self.subTest(first=first):
                one = rib.makeFillet(2, [edge_between(rib, *ends[first])])
                one.Tag = 2
                (own,) = roundNames(one)
                two = one.makeFillet(2, [edge_between(one, *ends[second])])
                self.assertIn(own, two.ElementMap)
                face = two.getElement(two.ElementMap[own])
                self.assertEqual(face.Surface.TypeId, "Part::GeomCylinder")
                y = face.CenterOfMass.y
                self.assertLess(y if first == "front" else 4 - y, 2)
                for name in roundNames(two) - {own}:
                    self.assertNotEqual(two.ElementMap[name], two.ElementMap[own])

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
        # The two rounds are one torus, as Onshape's (ops#900)
        self.assertEqual(
            sorted(f.Surface.TypeId for f in result.Faces).count("Part::GeomToroid"), 1
        )

    def fullRoundOfAPlate(self, rho, r=1.5, faces=1):
        """Cause C4 (ops#640), designed tests B3 and C3: a 30 x 20 plate 2 r thick, its vertical
        corners rounded 4 and the one at (30, 0) rounded rho, both rims rounded r. The wall
        vanishes, so OCCT fails and the exact construction builds the rounds. At the rho corner
        the round's torus has the major radius M = rho - r: a spindle (M < r) or a horn (M = r)"""
        radii = [4.0, rho, 4.0, 4.0]
        corners = [(0, 0), (30, 0), (30, 20), (0, 20)]
        plate = Part.makeBox(30, 20, 2 * r)
        for (x, y), radius in zip(corners, radii):
            plate = plate.makeFillet(radius, [edge_between(plate, (x, y, 0), (x, y, 2 * r))])
        volume = (600 - (1 - math.pi / 4) * sum(x * x for x in radii)) * 2 * r
        self.assertAlmostEqual(plate.Volume, volume, delta=1e-9 * volume)
        rims = [
            e
            for e in plate.Edges
            if abs(e.BoundBox.ZLength) < 1e-9 and abs(e.BoundBox.ZMin - r) > r / 2
        ]
        self.assertEqual(len(rims), 16)
        result = plate.makeFillet(r, rims)
        # Pappus per rim: straight runs and arcs, each arc at its centroid's radius
        straight = 100 - 2 * sum(radii)
        arcs = sum(math.pi / 2 * (x - fillet_centroid(r)) for x in radii)
        self.assertExact(result, volume - 2 * fillet_section(r) * (straight + arcs))
        # The rounds at the rho corner: every point at r from the circle of radius M about the
        # corner's axis, in the plate's middle plane (the kernel stores them as surfaces of
        # revolution, so the points are checked, not the type)
        centre, major = V(30 - rho, rho, r), rho - r
        rounds = 0
        for face in result.Faces:
            box = face.BoundBox
            if (
                face.Surface.TypeId in ("Part::GeomPlane", "Part::GeomCylinder")
                or box.XMin < 30 - rho - 1e-7
                or box.YMax > rho + 1e-7
            ):
                continue
            rounds += 1
            u0, u1, v0, v1 = face.ParameterRange
            for a in range(6):
                for b in range(6):
                    q = face.valueAt(u0 + (u1 - u0) * (a + 0.5) / 6, v0 + (v1 - v0) * (b + 0.5) / 6)
                    if not face.isInside(q, 1e-7, True):
                        continue
                    radial = math.hypot(q.x - centre.x, q.y - centre.y) - major
                    self.assertAlmostEqual(math.hypot(radial, q.z - centre.z), r, delta=1e-6)
        # The two rims' rounds at the corner are one face, as Onshape's (ops#900), but on a spindle:
        # its rounds are surfaces of revolution, not tori, and stay two (`faces`)
        self.assertEqual(rounds, faces)

    def testFullRoundWithASpindleTorus(self):
        self.fullRoundOfAPlate(2.4, faces=2)  # B3: M 0.9 < r 1.5

    def testFullRoundWithAHornTorus(self):
        self.fullRoundOfAPlate(3.0)  # C3: M = r = 1.5

    def testFullRoundWithARingTorus(self):
        self.fullRoundOfAPlate(4.0)  # N2, the control: M 2.5 > r

    def testFullRoundOfADiskWithSpindleTori(self):
        # Closed circles: a disk of radius 2.4, 3 thick, both rims rounded 1.5 (M 0.9 < r)
        rho, r = 2.4, 1.5
        disk = Part.makeCylinder(rho, 2 * r)
        rims = [e for e in disk.Edges if e.Curve.TypeId == "Part::GeomCircle"]
        self.assertEqual(len(rims), 2)
        result = disk.makeFillet(r, rims)
        removed = 2 * fillet_section(r) * 2 * math.pi * (rho - fillet_centroid(r))
        self.assertExact(result, math.pi * rho * rho * 2 * r - removed)

    def testFullRoundOfABlindHoleWithASpindleTorus(self):
        # A concave circle, its tool fused: a hole of radius 2.4, 3 deep, in a block, its top rim
        # (a ring torus about the hole's axis, M 3.9) and its floor edge (a spindle, M 0.9) both
        # rounded 1.5, so the hole's wall vanishes
        rho, r = 2.4, 1.5
        block = Part.makeBox(10, 10, 6).cut(Part.makeCylinder(rho, 2 * r, V(5, 5, 6 - 2 * r)))
        rims = [e for e in block.Edges if e.Curve.TypeId == "Part::GeomCircle"]
        self.assertEqual(len(rims), 2)
        result = block.makeFillet(r, rims)
        top = fillet_section(r) * 2 * math.pi * (rho + fillet_centroid(r))
        floor = fillet_section(r) * 2 * math.pi * (rho - fillet_centroid(r))
        self.assertExact(result, 600 - math.pi * rho * rho * 2 * r - top + floor)

    # Rounds that meet at a reflex corner with a circle (ops#640, FSLC #50; fillet-tight-arc 8).
    # Onshape's rule: the body is the union of each wall's own body rounded along its whole rim,
    # so each round runs on past the corner, the higher one is kept where both reach, and the
    # corner has no face of its own. OCCT's own result there is valid and wrong (a patch at a horn
    # or spindle torus, a misplaced mitre at a ring torus), so the construction is asked first.
    def assertNoPatch(self, result):
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        kinds = {face.Surface.TypeId for face in result.Faces}
        self.assertFalse(kinds & {"Part::GeomBSplineSurface", "Part::GeomBezierSurface"})

    def roundedTooth(self, r):
        tooth, pieces = tooth_on_a_round_root()
        rims = rim_edges(tooth, 6.0)
        self.assertEqual(len(rims), 6)  # the root's circle and a flank's are split at a seam
        result = tooth.makeFillet(r, rims)
        self.assertNoPatch(result)
        # (OCCT's volume of a body with such large trimmed tori is good to about 1e-3; its areas
        # to 1e-6)
        return tooth, result, pieces

    def testReflexCornersOfAToothWithHornTori(self):
        # r 2 on flanks of radius 4 (M = r): OCCT puts a B-spline patch at each root corner and
        # removes 0.281 less than Onshape (FT2)
        tooth, result, pieces = self.roundedTooth(2.0)
        self.assertAlmostEqual(result.Volume - tooth.Volume, -164.87904283, delta=2e-3)
        self.assertAlmostEqual(result.Area - tooth.Area, -168.40358530, delta=5e-5)

    def testReflexCornersOfAToothWithRingTori(self):
        # r 1 (M 3): Onshape's FT2 values
        tooth, result, pieces = self.roundedTooth(1.0)
        self.assertAlmostEqual(result.Volume - tooth.Volume, -41.46289585, delta=2e-3)
        self.assertAlmostEqual(result.Area - tooth.Area, -83.83556069, delta=1e-5)
        # Each flank's round, a torus about the flank's axis: 9.89499328 in Onshape (OCCT's own
        # mitre makes one of them 9.897019)
        for angle in (84, 96):
            centre = polar(30, angle)
            area = sum(
                face.Area
                for face in result.Faces
                if face.Surface.TypeId == "Part::GeomToroid"
                and face.Surface.Center.distanceToPoint(V(centre.x, centre.y, 5.0)) < 1e-6
            )
            self.assertAlmostEqual(area, 9.89499328, delta=1e-5)

    def testReflexCornersOfAToothNearTheHornTorus(self):
        # r 1.9 (M 2.1, still a ring torus): OCCT's result has only tori and is 0.22 off the
        # rule, which is built here from the pieces, each rounded along its own whole rim
        tooth, result, pieces = self.roundedTooth(1.9)
        rounded = [solid.cut(rim_ring(centre, rho, 1.9, 6.0)) for solid, centre, rho in pieces]
        rule = rounded[0].fuse(rounded[1:]).removeSplitter()
        self.assertAlmostEqual(result.Volume, rule.Volume, delta=2e-3)
        self.assertAlmostEqual(result.Area, rule.Area, delta=1e-5)

    def testReflexCornersOfABump(self):
        # A half-disc bump on a straight edge. The round half its radius (a horn torus, M = r):
        # OCCT fails. A quarter of it (a ring torus): OCCT's own result is the rule too
        for rho, r in ((0.4, 0.2), (1.0, 0.5), (0.4, 0.1)):
            with self.subTest(rho=rho, r=r):
                base, box, bump = bump_on_an_edge(rho)
                rims = rim_edges(base, 2.0)
                self.assertEqual(len(rims), 6)
                result = base.makeFillet(r, rims)
                self.assertNoPatch(result)
                removed = bump_rim_removed(rho, r)
                # (the integral above is good to about 1e-6 of it)
                self.assertAlmostEqual(base.Volume - result.Volume, removed, delta=1e-5 * removed)

    def testReflexCornersOfAWheelsTeeth(self):
        # The same tooth at two places of a wheel, each with two reflex corners of a horn torus.
        # OCCT stores a horn's round as a torus or as a surface of revolution by the last digit of
        # its major radius as it comes out at the tooth's place (0 and 11.25 degrees differ), and
        # its Booleans are wrong on the latter: the second tooth made the construction refuse.
        # Each tooth removes the same: 0.07166 by the rule (the height field, integrated), on top
        # of the plain rim's ring (Pappus)
        r = 0.5
        ring = fillet_section(r) * 2 * math.pi * (30 - fillet_centroid(r))
        removed = []
        # One face per arc of the rim: the root's arc that the second tooth leaves in two pieces
        # on one wall gets one round, as in Onshape (19 faces while each piece had its own)
        for teeth, faces in ((1, 10), (2, 18)):
            wheel, rims = toothed_wheel(teeth)
            result = wheel.makeFillet(r, rims)
            self.assertNoPatch(result)
            self.assertEqual(len(result.Faces), faces)
            removed.append(wheel.Volume - result.Volume)
        self.assertAlmostEqual(removed[0] - ring, 0.07166, delta=3e-4)
        self.assertAlmostEqual(removed[1] - removed[0], removed[0] - ring, delta=1e-4)

    def testReflexCornersOfAWholeWheel(self):
        # All 32 teeth, 64 reflex corners: whole rim loops on a plane face are built directly, each
        # round a torus and each mitre the crossing of its two walls' offsets, without a Boolean
        # (ops#640, notes/boolean-free-mitre.md). The rule by the height field: the plain rim's
        # ring and 0.07166 (+-1.5e-4) for each tooth; one round for each of the rim's 128 arcs
        r = 0.5
        ring = fillet_section(r) * 2 * math.pi * (30 - fillet_centroid(r))
        wheel, rims = toothed_wheel(32)
        result = wheel.makeFillet(r, rims)
        self.assertNoPatch(result)
        self.assertEqual(len(result.Faces), len(wheel.Faces) + 128)
        self.assertAlmostEqual(wheel.Volume - result.Volume, ring + 32 * 0.07166, delta=32 * 1.5e-4)

    def testReflexCornersBesideALoopOutOfTheDirectScope(self):
        # The wheel's rim with a countersunk hole's rim (a cone's, which the direct builder does
        # not take) in one fillet: the wheel's loop is built directly and the hole's rim is
        # rounded on the result, so the two remove what each removes alone, and one loop out of
        # scope does not send 64 corners to the construction by Booleans (FSLC #50, ops#640)
        r = 0.5
        wheel, rims = toothed_wheel(32)
        wheel = wheel.cut(Part.makeCone(2, 4, 3, V(0, 0, 0))).Solids[0]
        top = rim_edges(wheel, 3.0)
        hole = [
            e
            for e in top
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - 4) < 1e-9
            and e.Curve.Center.distanceToPoint(V(0, 0, 3)) < 1e-9
        ]
        self.assertEqual(len(hole), 1)
        outer = [e for e in top if not e.isSame(hole[0])]
        alone = [wheel.Volume - wheel.makeFillet(r, edges).Volume for edges in (hole, outer)]
        result = wheel.makeFillet(r, top)
        self.assertNoPatch(result)
        self.assertEqual(len(result.Faces), len(wheel.Faces) + 128 + 1)
        self.assertAlmostEqual(wheel.Volume - result.Volume, sum(alone), delta=1e-6)

    def assertFailsAtAReflexCorner(self, shape, r, reason):
        """The fillet fails, and its error names the reflex corner and why it was not built: OCCT's
        own result there is not Onshape's, and is never returned"""
        with self.assertRaises(Exception) as raised:
            shape.makeFillet(r, rim_edges(shape, 2.0))
        message = str(raised.exception)
        self.assertIn("reflex corner with a circle", message)
        self.assertIn(reason, message)

    def testReflexCornerWithASpindleTorusFails(self):
        # The round three quarters of the bump's radius (a spindle torus, M < r): the mitre runs
        # on to the corner's mirror image, which is not built yet. OCCT's result (valid, two
        # B-spline patches, 0.002 short of the rule's 0.54125010) is not returned
        base, box, bump = bump_on_an_edge(0.4)
        self.assertAlmostEqual(bump_rim_removed(0.4, 0.3), 0.54125010, delta=1e-6)
        self.assertFailsAtAReflexCorner(base, 0.3, "do not close within their run on")

    def testReflexCornersOfARidgeStripFail(self):
        # A row of bumps on a straight edge with valleys between them, each bump meeting its
        # valleys at right angles: the end bumps' reflex corners are built, the convex corners of
        # a bump with a valley are not yet (and OCCT fails there too)
        rho = valley = 0.4
        pitch = 2 * math.hypot(rho, valley)
        strip = Part.makeBox(4 * pitch, 4, 2).fuse(
            [Part.makeCylinder(rho, 2, V(pitch * (i + 1), 4, 0)) for i in range(3)]
        )
        strip = strip.removeSplitter().cut(
            [Part.makeCylinder(valley, 2, V(pitch * (i + 1.5), 4, 0)) for i in range(2)]
        )
        with self.assertRaises(Exception):
            strip.removeSplitter().makeFillet(0.2, rim_edges(strip.removeSplitter(), 2.0))

    def testReflexCornerOfStraightEdges(self):
        # An L plate's inner corner: OCCT's own mitre, left alone (closed form)
        outline = [V(0, 0, 0), V(20, 0, 0), V(20, 8, 0), V(8, 8, 0), V(8, 20, 0), V(0, 20, 0)]
        plate = Part.Face(Part.makePolygon(outline + outline[:1])).extrude(V(0, 0, 5))
        r = 0.5
        result = plate.makeFillet(r, rim_edges(plate, 5.0))
        mitres = (-5 + 1) * 2 * fillet_centroid(r)  # five convex corners, one reflex
        self.assertExact(result, plate.Volume - fillet_section(r) * (80 + mitres))

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
                    # the rib's top is gone, one full round (ops#900) or two chamfers in its place
                    added = 0 if kind == "fillet" else 1
                    self.assertEqual(len(result.Faces), len(base.Faces) + added)
                    self.assertFalse(
                        [face for face in result.Faces if abs(face.CenterOfMass.x + 9) < 1e-7]
                    )
                    rib = result.common(rib_side)
                    self.assertAlmostEqual(rib.Volume, section * length, delta=1e-6 * length)

    def testCutAcrossLongSplineFaces(self):
        # A short rib standing on the flat side, y in [3, 7], full height, refined into the prism's
        # top and bottom, which the wave bounds. Each Boolean trims those faces, so the volume it
        # removes, a difference of whole volumes, carries their integration error. The helper's
        # adaptive method with one integration per knot span is fine enough for the 1e-6 check;
        # without the spans it was off by 3e-6 (500 spans) and 3e-4 (1000), and every case was
        # refused, "the cut removed 17.16820164 instead of 17.16814693" (ops#414)
        for waves in (25, 50):
            length = 20 * waves
            base = wave_prism(waves).fuse(Part.makeBox(4, 4, 10, V(-9, 3, 0))).removeSplitter()
            edges = [
                edge_between(base, (-9, 3, 0), (-9, 3, 10)),
                edge_between(base, (-9, 7, 0), (-9, 7, 10)),
            ]
            rib_side = Part.makeBox(5, length + 2, 12, V(-10, -1, -1))
            for kind, section in (("fillet", 16 - 2 * fillet_section(2)), ("chamfer", 16 - 4)):
                with self.subTest(waves=waves, kind=kind):
                    if kind == "fillet":
                        result = base.makeFillet(2, edges)
                    else:
                        result = base.makeChamfer(2, edges)
                    self.assertTrue(result.isValid())
                    self.assertEqual(len(result.Solids), 1)
                    # one full round (ops#900) or two chamfers
                    added = 0 if kind == "fillet" else 1
                    self.assertEqual(len(result.Faces), len(base.Faces) + added)
                    self.assertFalse(
                        [face for face in result.Faces if abs(face.CenterOfMass.x + 9) < 1e-7]
                    )
                    rib = result.common(rib_side)
                    self.assertAlmostEqual(rib.Volume, section * 10, delta=1e-9 * section * 10)

    def testRoundAlongALongSplineIsQuick(self):
        # A round of 1 on the wave's top edge, which OCCT builds; FilletFallback then reads the area
        # of each new face. In round 2 of ops#414 the side face, trimmed by the round, was converted
        # to NURBS and integrated adaptively along its B-spline boundaries: 9.5 s at 500 spans, 18 s
        # at 1000, for an OCCT fillet of 0.14 s and 0.24 s. Its boundary integral takes milliseconds
        for waves in (25, 50):
            with self.subTest(waves=waves):
                prism = wave_prism(waves)
                top = [
                    edge
                    for edge in prism.Edges
                    if edge.Curve.TypeId == "Part::GeomBSplineCurve"
                    and abs(edge.Vertexes[0].Point.z - 10) < 1e-9
                ]
                self.assertEqual(len(top), 1)
                start = time.perf_counter()
                result = prism.makeFillet(1, top)
                elapsed = time.perf_counter() - start
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Faces), len(prism.Faces) + 1)
                self.assertLess(elapsed, 2.0)

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
        # leans in by 10 degrees), variable radius. (Rounds just over the limit build since S3:
        # OverflowTest.testRoundsJustPastTheLimit)
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

    def testWholeOutlineOfAFusedStadium(self):
        # ops#298: OCCT "succeeds" on the whole top outline at r = 2 and d = 2 (half the width),
        # keeping the top face with area 0, also at r = 2 - 1e-8. makeFillet and makeChamfer
        # build the full round and the ridge exactly instead (the full round in 9 faces, its rounds
        # one face per run, ops#900; the ridge in 10: the half circle at x = 20 is in two)
        plate, outline = fused_stadium()
        plate.Tag = 1
        self.assertEqual(len(outline), 5)
        for r in (2, 2 - 1e-8):
            result = plate.makeFillet(r, outline)
            self.assertExact(result, fused_stadium_rounded(r))
            self.assertEqual(len(result.Faces), 9)
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
            self.assertEqual(len(result.Faces), 6)
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

    def assertShapeRaises(self, kind, shape, size, edges):
        """The Python API never returns OCCT's invalid result (decision 418, ops#640): it raises,
        with why the exact construction refused"""
        with self.assertRaises(Part.OCCError) as raised:
            self.dressUpShape(kind, shape, size, edges)
        self.assertIn("is not a valid shape (exact construction refused: ", str(raised.exception))

    def testOverlongFullRoundsFail(self):
        # Just over a full round, OCCT builds two invalid solids with more volume than the base,
        # which no fillet can have. (Debt, ops#640: Onshape builds them, K2E. The chamfers build
        # since S3: OverflowTest.testOverlongFullChamfers)
        for kind in ("Fillet",):
            for model, size in ((stadium_plate, 2.0002), (disk, 1.00001)):
                shape, edges = model()
                self.assertShapeRaises(kind, shape, size, edges)
                feature = self.dressUp(kind, shape, edges, [(size, size)] * len(edges))
                self.assertFails(feature)

    def testOverlappingRoundsFail(self):
        # Rounds or chamfers of 2.65 on two edges 4 apart overlap on the face between them: no
        # dress-up exists. OCCT's result has a self-intersecting wire; its repair adds two faces
        # (and 16.75 mm2 for the fillet)
        for kind in ("Fillet", "Chamfer"):
            block, edges = notched_block()
            self.assertShapeRaises(kind, block, 2.65, edges)
            self.assertFails(self.dressUp(kind, block, edges, [(2.65, 2.65)] * 4))

    def testOverlappingRoundsOnALargePartFail(self):
        # The notch at a tenth of the size in a block 1000 x 1000 x 1: the repair's added area
        # (0.17 mm2) is far below a millionth of the block's (2 m2)
        for kind in ("Fillet", "Chamfer"):
            block, edges = notched_block(0.1, (1000, 1000, 1))
            self.assertShapeRaises(kind, block, 0.265, edges)
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
            self.assertShapeRaises(kind, solid, 1, edges)
            feature = self.dressUp(kind, solid, edges, [(1, 1)] * 4)
            self.assertTrue(feature.isValid(), feature.getStatusString())
            shape = feature.Shape
            self.assertTrue(shape.isValid())
            self.assertEqual(len(shape.Solids), 1)
            # OCCT's faces, each kept: the pyramid's 5, a face per edge, and the apex's. A wrong
            # repair adds faces (the notch: two)
            self.assertEqual(len(shape.Faces), 10)
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

    def testConcavePastItsFaceIntoARingFillsNothing(self):
        # Case Base #46 designed (ring_corner()), as a feature: the dress-up clipped by the ring
        # lies on the ring's outer wall and under its underside, faces beside the wall at the edge,
        # on the strip's side of them; the check for a filled recess lets it pass (it refused it,
        # "fills a recess ... next to" the edge), and nothing is added in the well
        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                base, ends, added, well = ring_corner(kind)
                feature, _ = dressed_in_a_body(self.doc, kind, base, ends, 10)
                self.assertTrue(feature.isValid(), feature.getStatusString())
                self.assertTrue(feature.Shape.isValid())
                self.assertAlmostEqual(feature.Shape.Volume, base.Volume + added, delta=1e-6)
                self.assertLess(feature.Shape.common(well).Volume, 1e-9)

    def testConcaveRoundRolledOnOverATangentEdgeFillsNothing(self):
        # Case Base #47 designed (rounded_ring_corner()), as a feature: the round rolled on over
        # the r 10 round's tangent edge onto the wall x 0 fills no recess, and adds Onshape's
        # +337.099410 (oracle 16, FR2)
        base, ends, added, _ = rounded_ring_corner()
        feature, _ = dressed_in_a_body(self.doc, "Fillet", base, ends, 6.5)
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertTrue(feature.Shape.isValid())
        self.assertEqual(len(feature.Shape.Faces), 14)
        self.assertAlmostEqual(feature.Shape.Volume, base.Volume + added, delta=1e-6)

    def testConcaveRoundRolledOnAtOrPastTheCornersRadius(self):
        # ops#757: at r >= the corner's R1 10, OCCT's fillet returned an invalid shape that the
        # limited validity check passed, so the exact construction was never asked. The round
        # rolls on over the r 10 round's tangent edge onto the wall x 0 as at r 6.5: its section
        # over z 4..10 is the r 10 round from the crease to (0, -10), the wall x 0 down to the
        # ball's touch, the ball's arc (centre (r, -1 - sqrt((15 + r)^2 - (19 - r)^2))) and the
        # ring back to the crease; 6 times its area (work/nudge/s47.py, plan())
        base, ends, _, _ = rounded_ring_corner()
        for r, added in ((10.0, 553.869536), (12.0, 668.123999), (16.0, 882.173238)):
            with self.subTest(r=r):
                feature, _ = dressed_in_a_body(self.doc, "Fillet", base, ends, r)
                self.assertTrue(feature.isValid(), feature.getStatusString())
                self.assertTrue(feature.Shape.isValid())
                self.assertEqual(len(feature.Shape.Faces), 14)
                self.assertAlmostEqual(feature.Shape.Volume, base.Volume + added, delta=1e-5)

    def testConcaveRoundRolledOnOntoAStepFillsNothing(self):
        # rounded_ring_corner(step=True): the rolled round's flat bottom (z 4) lands on the step's
        # top, a floor in the plane of the edge's end face (the ring's underside) beside the wall
        # it rolls onto, as Onshape's #47 does on its own input. It fills no recess: the base plus
        # the same region
        base, ends, added, _ = rounded_ring_corner(step=True)
        self.assertAlmostEqual(added, 337.099410, delta=1e-6)
        feature, _ = dressed_in_a_body(self.doc, "Fillet", base, ends, 6.5)
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertTrue(feature.Shape.isValid())
        self.assertAlmostEqual(feature.Shape.Volume, base.Volume + added, delta=1e-6)

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


def sketched_rectangle(body, support, x0, y0, x1, y1, z):
    """A sketch of the rectangle (global x0..x1, y0..y1 at height z) on the support, a plane or a
    (feature, face) pair"""
    import Sketcher

    sketch = body.newObject("Sketcher::SketchObject", "Sketch")
    sketch.AttachmentSupport = support
    sketch.MapMode = "FlatFace"
    body.Document.recompute()
    local = sketch.Placement.inverse()
    a = local.multVec(V(x0, y0, z))
    b = local.multVec(V(x1, y1, z))
    lo = V(min(a.x, b.x), min(a.y, b.y), 0)
    hi = V(max(a.x, b.x), max(a.y, b.y), 0)
    corners = [lo, V(hi.x, lo.y, 0), hi, V(lo.x, hi.y, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    return sketch


def on_outline(p):
    """Whether the point lies on the 40 x 40 outline of a stepped body's Pad1"""
    return min(abs(p.x), abs(p.x - 40), abs(p.y), abs(p.y - 40)) < 1e-9


def top_outer_edges(shape, which, height):
    """Pad1's four top outer edges, or the one at y = 0"""
    return [
        e
        for e in shape.Edges
        if all(abs(v.Point.z - height) < 1e-9 for v in e.Vertexes)
        and on_outline(e.CenterOfMass)
        and (which == "four" or abs(e.CenterOfMass.y) < 1e-9)
    ]


def stepped_body(doc, kind, size, inset, which="four", height=10.0):
    """A PartDesign Body of two Pads from sketches: Pad1 40 x 40 x height, and Pad2 10 high on its
    top face, a rectangle whose walls lie inset from Pad1's outline (with one edge, only the wall
    facing it, y = inset; the others at 5). A Fillet or Chamfer of the size on Pad1's four top outer
    edges, or on the one at y = 0. Returns the feature and its base's shape (ops#603)"""
    body = doc.addObject("PartDesign::Body", "Body")
    lower = sketched_rectangle(body, (body.Origin.OriginFeatures[3], [""]), 0, 0, 40, 40, 0)
    pad1 = body.newObject("PartDesign::Pad", "Pad1")
    pad1.Profile = lower
    pad1.Length = height
    doc.recompute()
    top = next(
        i for i, f in enumerate(pad1.Shape.Faces, 1) if abs(f.CenterOfMass.z - height) < 1e-9
    )
    walls = (inset, inset, 40 - inset, 40 - inset) if which == "four" else (5, inset, 35, 35)
    upper = sketched_rectangle(body, (pad1, ["Face%d" % top]), *walls, height)
    pad2 = body.newObject("PartDesign::Pad", "Pad2")
    pad2.Profile = upper
    pad2.Length = 10
    doc.recompute()
    base = pad2.Shape
    names = [
        "Edge%d" % next(i for i, e in enumerate(base.Edges, 1) if e.isSame(edge))
        for edge in top_outer_edges(base, which, height)
    ]
    dressed = body.newObject("PartDesign::" + kind, kind)
    dressed.Base = (pad2, names)
    if kind == "Fillet":
        dressed.Radius = size
    else:
        dressed.Size = size
    doc.recompute()
    return dressed, base


def stepped_expected(kind, size, which, base, height=10.0):
    """The step's dress-up: the base without what the same dress-up removes from Pad1 alone, which
    the step doesn't reach"""
    block = Part.makeBox(40, 40, height)
    edges = top_outer_edges(block, which, height)
    dressed = block.makeFillet(size, edges) if kind == "Fillet" else block.makeChamfer(size, edges)
    return base.Volume - (block.Volume - dressed.Volume)


class LostStepTest(unittest.TestCase):
    """OCCT's fillet and chamfer stopping a hair (1e-9 to 5e-7 mm) short of a step return a valid
    solid without the step's upper Pad (ops#603). The result must keep it, or the feature fails
    saying it drops a part of the base. The error of a dress-up the exact construction refused says
    why (ops#601).
    """

    def setUp(self):
        self.doc = FreeCAD.newDocument("LostStepTest")

    def tearDown(self):
        FreeCAD.closeDocument(self.doc.Name)

    dressUp = InvalidDressUpTest.dressUp

    def assertKeptOrFails(self, feature, expected):
        kind = feature.TypeId.split("::")[1].lower()
        if feature.isValid():
            self.assertTrue(feature.Shape.isValid())
            self.assertAlmostEqual(feature.Shape.Volume, expected, delta=1e-4)
            return
        self.assertTrue(
            feature.getStatusString().startswith("The %s drops a part of the base: Face" % kind),
            feature.getStatusString(),
        )

    def assertStepKeptOrFails(self, kind, inset, which, height=10.0):
        feature, base = stepped_body(self.doc, kind, 5, inset, which, height)
        self.assertKeptOrFails(feature, stepped_expected(kind, 5, which, base, height))

    def assertBuilds(self, kind, inset, which, height=10.0):
        feature, base = stepped_body(self.doc, kind, 5, inset, which, height)
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertTrue(feature.Shape.isValid())
        self.assertAlmostEqual(
            feature.Shape.Volume, stepped_expected(kind, 5, which, base, height), delta=1e-4
        )

    def testFourEdgesAHairShortOfTheStep(self):
        # OCCT returned Pad1 dressed alone: fillet 15189.53 for 24189.53, chamfer 14166.67 for
        # 23166.67
        for kind in ("Fillet", "Chamfer"):
            for d in (1e-9, 1e-8, 1e-7, 5e-7):
                with self.subTest(kind=kind, d=d):
                    self.assertStepKeptOrFails(kind, 5 + d, "four")

    def testOneEdgeAHairShortOfTheStep(self):
        # One edge with the wall facing it 5 + d in: on the 10 mm block (15785.40 for 24785.40
        # with all four walls in), and on the 25 mm one (39785.40 for 48785.40, chamfer 39500 for
        # 48500)
        for kind in ("Fillet", "Chamfer"):
            for d in (1e-9, 5e-7):
                for height in (10.0, 25.0):
                    with self.subTest(kind=kind, d=d, height=height):
                        self.assertStepKeptOrFails(kind, 5 + d, "one", height)

    def testAtAndNearTheStepStillBuild(self):
        # The exact step (the exact construction builds the limit shape), the round stopping 1e-6
        # or 1e-5 short (OCCT leaves a sliver of the ring) and well short (1 mm)
        for kind in ("Fillet", "Chamfer"):
            for which in ("four", "one"):
                for d in (0, 1e-6, 1e-5, 1):
                    with self.subTest(kind=kind, which=which, d=d):
                        self.assertBuilds(kind, 5 + d, which)
            with self.subTest(kind=kind, height=25):
                self.assertBuilds(kind, 5, "one", 25.0)

    def testDistanceAngleChamferAHairShortOfTheStep(self):
        # ops#622: a distance-angle chamfer had no lost-material check. At 45 degrees it is the
        # equal distance chamfer of 5, a hair short of the step: OCCT drops the step. At 30 and 60
        # degrees its other distance is 5 tan(a) or 5 / tan(a), with the walls that far in plus d:
        # either way the step (a boss above y = inset) must stay whole, or the feature fails
        for angle in (45.0, 30.0, 60.0):
            for d in (1e-9, 1e-7, 5e-7):
                for which in ("four", "one"):
                    reach = 5 * max(math.tan(math.radians(angle)), 1 / math.tan(math.radians(angle)))
                    inset = 5 + d if angle == 45.0 else reach + d
                    with self.subTest(angle=angle, d=d, which=which):
                        doc = FreeCAD.newDocument("LostStepDA")
                        try:
                            feature, base = stepped_body(doc, "Chamfer", 5, inset, which)
                            feature.ChamferType = "Distance and Angle"
                            feature.Angle = angle
                            doc.recompute()
                            if not feature.isValid():
                                self.assertKeptOrFails(feature, None)
                                continue
                            self.assertTrue(feature.Shape.isValid())
                            if which == "one":
                                # A triangle of legs 5 and 5 tan(a) along the 40 mm edge, which
                                # ever face takes the distance (a Boolean common with a boss
                                # whose faces lie on the step's is unreliable at 1e-7)
                                removed = 0.5 * 5 * 5 * math.tan(math.radians(angle)) * 40
                                self.assertAlmostEqual(
                                    feature.Shape.Volume, base.Volume - removed, delta=1e-4
                                )
                                continue
                            walls = (
                                (inset, inset, 40 - inset, 40 - inset)
                                if which == "four"
                                else (5, inset, 35, 35)
                            )
                            boss = Part.makeBox(
                                walls[2] - walls[0], walls[3] - walls[1], 10,
                                V(walls[0], walls[1], 10),
                            )
                            self.assertAlmostEqual(
                                feature.Shape.common(boss).Volume, boss.Volume, delta=1e-4
                            )
                        finally:
                            FreeCAD.closeDocument(doc.Name)

    def testRibWithinTheReachAHairBeyondTheBand(self):
        # ops#612: Pad1 40 x 40 x 10 and a rib 30 x 2 x 10 on it, its front wall d behind the band
        # of a fillet (or chamfer) of 5 on Pad1's front top edge. OCCT dropped the rib in a valid
        # solid (fillet 15785.40 for 16385.40), and the rib lies within the generous reach
        # 5 (1 + sqrt 2) everywhere. Between planes the band's far side is known (5): the rib must
        # stay, or the feature fails. Onshape keeps it (Parasolid; ops#603)
        for kind in ("Fillet", "Chamfer"):
            for d in (1e-9, 1e-7, 5e-7, 1e-3, 1.0):
                with self.subTest(kind=kind, d=d):
                    doc = FreeCAD.newDocument("RibInReach")
                    try:
                        body = doc.addObject("PartDesign::Body", "Body")
                        lower = sketched_rectangle(
                            body, (body.Origin.OriginFeatures[3], [""]), 0, 0, 40, 40, 0
                        )
                        pad1 = body.newObject("PartDesign::Pad", "Pad1")
                        pad1.Profile = lower
                        pad1.Length = 10
                        doc.recompute()
                        top = next(
                            i
                            for i, f in enumerate(pad1.Shape.Faces, 1)
                            if abs(f.CenterOfMass.z - 10) < 1e-9
                        )
                        upper = sketched_rectangle(
                            body, (pad1, ["Face%d" % top]), 5, 5 + d, 35, 7 + d, 10
                        )
                        rib = body.newObject("PartDesign::Pad", "Rib")
                        rib.Profile = upper
                        rib.Length = 10
                        doc.recompute()
                        base = rib.Shape
                        name = "Edge%d" % next(
                            i
                            for i, e in enumerate(base.Edges, 1)
                            if all(
                                abs(v.Point.z - 10) < 1e-9 and abs(v.Point.y) < 1e-9
                                for v in e.Vertexes
                            )
                        )
                        dressed = body.newObject("PartDesign::" + kind, kind)
                        dressed.Base = (rib, [name])
                        if kind == "Fillet":
                            dressed.Radius = 5
                        else:
                            dressed.Size = 5
                        doc.recompute()
                        block = Part.makeBox(40, 40, 10)
                        edges = top_outer_edges(block, "one", 10.0)
                        cut = block.makeFillet(5, edges) if kind == "Fillet" else block.makeChamfer(5, edges)
                        self.assertKeptOrFails(dressed, base.Volume - (block.Volume - cut.Volume))
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPartFeaturesAHairShortOfTheStep(self):
        # Part::Fillet and Part::Chamfer on the Body's shape, with one size (the exact
        # construction's route) and with a size per edge (OCCT's maker alone)
        d = 1e-7
        _, shape = stepped_body(self.doc, "Fillet", 5, 5 + d, "four")
        edges = top_outer_edges(shape, "four", 10.0)
        self.assertEqual(len(edges), 4)
        boss = Part.makeBox(30 - 2 * d, 30 - 2 * d, 10, V(5 + d, 5 + d, 10))
        for kind in ("Fillet", "Chamfer"):
            for sizes in ([(5, 5)] * 4, [(5, 5)] * 3 + [(4.5, 4.5)]):
                with self.subTest(kind=kind, last=sizes[-1][0]):
                    feature = self.dressUp(kind, shape, edges, sizes)
                    if not feature.isValid():
                        self.assertKeptOrFails(feature, None)
                        continue
                    # The dress-up doesn't reach the boss: all of it is kept
                    self.assertTrue(feature.Shape.isValid())
                    self.assertAlmostEqual(
                        feature.Shape.common(boss).Volume, boss.Volume, delta=1e-4
                    )

    def testErrorSaysWhyTheConstructionRefused(self):
        # r = 5.01 at the exact step on the four edges: OCCT fails, and the exact construction
        # refuses: at the ledge's corners two picked edges meet with both strips past the ledge's
        # outer loop, Onshape's *_OVERLAPS_EDGE_LOOP (K1; ops#601; Onshape fails too,
        # notes/fillet-parity.md 3.5x). PartDesign words it as Onshape does, the reason after it
        # (ops#640 F2)
        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                feature, _ = stepped_body(self.doc, kind, 5.01, 5, "four")
                self.assertFalse(feature.isValid())
                status = feature.getStatusString()
                self.assertTrue(
                    status.startswith("Failed to %s selections: " % kind.lower()), status
                )
                self.assertNotIn("command not done", status)
                self.assertIn("run past the face's outer loop", status)

    def testOneEdgeJustPastTheStepIsTrimmedByTheWall(self):
        # r = 5.01 on the one edge: its strip runs 0.01 past the ledge onto the step's wall (x 5..35,
        # y 5). Onshape trims the dress-up by the wall's plane run on under the ledge (Q-LEDGE
        # LD1-LD3): the base less the dress-up of Pad1 alone, but for the tool's sliver past y 5
        # under the wall, which stays
        r, a = 5.01, 0.01
        for kind, kept in (
            ("Chamfer", a * a / 2),
            ("Fillet", r * a - (a / 2 * math.sqrt(r * r - a * a) + r * r / 2 * math.asin(a / r))),
        ):
            with self.subTest(kind=kind):
                feature, base = stepped_body(self.doc, kind, r, 5, "one")
                self.assertTrue(feature.isValid(), feature.getStatusString())
                self.assertTrue(feature.Shape.isValid())
                self.assertAlmostEqual(
                    feature.Shape.Volume,
                    stepped_expected(kind, r, "one", base) + 30 * kept,
                    delta=1e-6,
                )


def front_top(shape):
    """The block's front top edges (y = 0, z = 10): one, or its pieces where a feature splits it"""
    return [
        e
        for e in shape.Edges
        if e.Curve.TypeId == "Part::GeomLine"
        and all(abs(v.Point.y) < 1e-9 and abs(v.Point.z - 10) < 1e-9 for v in e.Vertexes)
    ]


def filleted_in_a_body(doc, shape, select, radius):
    """A PartDesign Body whose BaseFeature is the shape, and a Fillet of the radius on the edges
    select() picks of the BaseFeature's shape"""
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = shape
    body = doc.addObject("PartDesign::Body", "Body")
    body.BaseFeature = base
    doc.recompute()
    fillet = body.newObject("PartDesign::Fillet", "Fillet")
    shape = base.Shape
    fillet.Base = (
        body.BaseFeature,
        [
            "Edge%d" % next(i for i, e in enumerate(shape.Edges, 1) if e.isSame(edge))
            for edge in select(shape)
        ],
    )
    fillet.Radius = radius
    doc.recompute()
    return fillet


def symmetric_difference(a, b):
    return a.cut(b).Volume + b.cut(a).Volume


class BridgedRecessTest(unittest.TestCase):
    """Where a round's band crosses a hole, a slot or a round boss in the face next to its edge,
    OCCT builds a B-spline bridge over the gap: a valid solid, slightly wrong (ops#604 gap 3a,
    decision 283). The fillet fails instead, naming the face. The block 30 x 20 x 10, its front top
    edge r 2; the right result is the plain block's round with the feature applied afterwards.
    """

    setUp = InvalidDressUpTest.setUp
    tearDown = InvalidDressUpTest.tearDown

    def assertBridgeFails(self, shape, top_face=True):
        fillet = filleted_in_a_body(self.doc, shape, front_top, 2)
        self.assertFalse(fillet.isValid())
        status = fillet.getStatusString()
        self.assertTrue(
            status.startswith("The fillet's band crosses a hole or pocket on Face"), status
        )
        self.assertTrue(status.endswith("; a round that rolls through it is not built yet"), status)
        if top_face:
            # The hole is in the top face
            top = next(
                i
                for i, f in enumerate(shape.Faces, 1)
                if f.Surface.TypeId == "Part::GeomPlane"
                and abs(f.BoundBox.ZMin - 10) < 1e-9
                and abs(f.BoundBox.ZMax - 10) < 1e-9
            )
            self.assertIn("on Face%d;" % top, status)

    def assertRight(self, shape, right):
        fillet = filleted_in_a_body(self.doc, shape, front_top, 2)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        self.assertLess(symmetric_difference(fillet.Shape, right), 1e-6)

    def rounded(self):
        block = Part.makeBox(30, 20, 10)
        return block.makeFillet(2, front_top(block))

    def testThroughHoleAcrossTheBand(self):
        # O1: the hole's rim 1 and 0.5 mm from the edge; OCCT's bridge is 0.75 and 1.34 mm3 off
        for y in (4.0, 3.5):
            with self.subTest(y=y):
                self.assertBridgeFails(
                    Part.makeBox(30, 20, 10).cut(Part.makeCylinder(3, 10, V(15, y, 0)))
                )

    def testBlindHoleAcrossTheBand(self):
        # O2: 4 deep
        self.assertBridgeFails(Part.makeBox(30, 20, 10).cut(Part.makeCylinder(3, 4, V(15, 4, 6))))

    def testSlotAcrossTheBand(self):
        # O4: a stadium 3 deep, 1 mm from the edge
        slot = (
            Part.makeBox(8, 4, 3, V(11, 1, 7))
            .fuse([Part.makeCylinder(2, 3, V(11, 3, 7)), Part.makeCylinder(2, 3, V(19, 3, 7))])
            .removeSplitter()
        )
        self.assertBridgeFails(Part.makeBox(30, 20, 10).cut(slot))

    def testRoundBossAcrossTheBand(self):
        # O5: its wall 1 mm from the edge. The boss's foot is an inner wire of the top face
        boss = Part.makeBox(30, 20, 10).fuse(Part.makeCylinder(3, 4, V(15, 4, 10))).removeSplitter()
        self.assertBridgeFails(boss)

    def testHoleBreakingTheEdgeStillBuilds(self):
        # O1 with the hole through the front face: the edge's two pieces end at the hole's wall
        hole = Part.makeCylinder(3, 10, V(15, 2.5, 0))
        shape = Part.makeBox(30, 20, 10).cut(hole)
        self.assertEqual(len(front_top(shape)), 2)
        self.assertRight(shape, self.rounded().cut(hole))

    def testRibAcrossTheEdgeStillBuilds(self):
        # O7 and O8: a rib 5 or 1 high across the edge; the oracle has the rib to the bottom
        for height in (5, 1):
            with self.subTest(height=height):
                shape = (
                    Part.makeBox(30, 20, 10)
                    .fuse(Part.makeBox(4, 20, height, V(13, 0, 10)))
                    .removeSplitter()
                )
                rib = Part.makeBox(4, 20, 10 + height, V(13, 0, 0))
                self.assertRight(shape, self.rounded().fuse(rib).removeSplitter())

    def testCornersAndSpaceCurvesAreNotChecked(self):
        # 1.11: the D plate's top loop, a line meeting an arc at an angle (a corner: OCCT's torus
        # patch); 1.13: the pipe T's junction, a space curve between two cylinders (its round is a
        # B-spline). Both build
        plate = (
            Part.makeBox(20, 20, 4).fuse(Part.makeCylinder(12, 4, V(20, 10, 0))).removeSplitter()
        )

        def top(shape):
            return [e for e in shape.Edges if all(abs(v.Point.z - 4) < 1e-9 for v in e.Vertexes)]

        tee = (
            Part.makeCylinder(5, 30, V(0, 0, 0), V(1, 0, 0))
            .fuse(Part.makeCylinder(4, 15, V(15, 0, 0), V(0, 0, 1)))
            .removeSplitter()
        )

        def junction(shape):
            return [
                e
                for e in shape.Edges
                if e.Curve.TypeId not in ("Part::GeomLine", "Part::GeomCircle")
            ]

        self.assertTrue(junction(tee))
        for name, shape, edges in (("D plate", plate, top), ("pipe T", tee, junction)):
            with self.subTest(name=name):
                fillet = filleted_in_a_body(self.doc, shape, edges, 1)
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertTrue(fillet.Shape.isValid())

    def testPartFilletAcrossAHole(self):
        # Part::Fillet with one radius fails the same; a variable radius isn't checked
        shape = Part.makeBox(30, 20, 10).cut(Part.makeCylinder(3, 10, V(15, 4, 0)))
        feature = InvalidDressUpTest.dressUp(self, "Fillet", shape, front_top(shape), [(2, 2)])
        self.assertFalse(feature.isValid())
        self.assertTrue(
            feature.getStatusString().startswith(
                "The fillet's band crosses a hole or pocket on Face"
            ),
            feature.getStatusString(),
        )

    def rimBlock(self, sink_y=None):
        # ops#932: the block 60 x 40 x 10 with its 4 vertical edges rounded r 6, and a countersink
        # (a cone r 4 at the top face to r 2 at depth 2, then a through hole r 2) whose axis is at
        # x 30, y sink_y
        block = Part.makeBox(60, 40, 10)
        block = block.makeFillet(6, [e for e in block.Edges if abs(e.BoundBox.ZLength - 10) < 1e-9])
        if sink_y is None:
            return block, None
        sink = (
            Part.makeCone(2, 4, 2, V(30, sink_y, 8))
            .fuse(Part.makeCylinder(2, 10, V(30, sink_y, 0)))
            .removeSplitter()
        )
        return block.cut(sink), sink

    @staticmethod
    def rim(shape):
        """The top face's outer loop: its 4 lines and 4 arcs at z 10 (an arc's centre of mass is
        2.18 from the sides; the countersink's circle, 5 or more)"""
        return [
            e
            for e in shape.Edges
            if all(abs(v.Point.z - 10) < 1e-9 for v in e.Vertexes)
            and min(abs(e.CenterOfMass.x), abs(e.CenterOfMass.x - 60), abs(e.CenterOfMass.y),
                    abs(e.CenterOfMass.y - 40)) < 3
        ]

    def testRimWithRoundedCornersAcrossACountersink(self):
        # The countersink's rim 1 mm from the long side: the rim round's band (2 wide) crosses it.
        # The picked loop runs round tangent corners, whose walls are tangent to the sides; the
        # check used to stop there and OCCT's B-spline bridge was kept (DSH front lid #14)
        shape, _ = self.rimBlock(5)
        self.assertEqual(len(self.rim(shape)), 8)
        fillet = filleted_in_a_body(self.doc, shape, self.rim, 2)
        self.assertFalse(fillet.isValid())
        status = fillet.getStatusString()
        self.assertTrue(
            status.startswith("The fillet's band crosses a hole or pocket on Face"), status
        )

    def testRimWithRoundedCornersClearOfACountersinkBuilds(self):
        # The countersink's rim 6 mm from the side, clear of the band; and no countersink: the
        # rim round builds, analytic faces only, the plain block's round with the sink cut after
        rounded, _ = self.rimBlock()
        plain = rounded.makeFillet(2, self.rim(rounded))
        for sink_y in (None, 10):
            with self.subTest(sink_y=sink_y):
                shape, sink = self.rimBlock(sink_y)
                fillet = filleted_in_a_body(self.doc, shape, self.rim, 2)
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                kinds = {f.Surface.TypeId for f in fillet.Shape.Faces}
                self.assertNotIn("Part::GeomBSplineSurface", kinds)
                right = plain if sink is None else plain.cut(sink)
                self.assertLess(symmetric_difference(fillet.Shape, right), 1e-6)

    def testBandOffOntoARoundAnotherPickBordersIsNotARecess(self):
        # Review pri931-r3, SplitRoundSelection: the block 40 x 20 x 5, its bottom front edge
        # rounded r 4, a groove x 20..22, z 0..2 through that round. The top front edge's band
        # (r 1.5) runs off its front wall onto the round; the groove walls' arcs on the round are
        # picked too. Their faces are faces of chain edges, but not of edges meeting the top
        # front edge, so the band still leaves the chain there: no hole is crossed, and the
        # round builds with one arc picked or both, as before ops#932
        block = Part.makeBox(40, 20, 5)
        block = block.makeFillet(
            4, [e for e in block.Edges if abs(e.BoundBox.YMax) < 1e-9 and abs(e.BoundBox.ZMax) < 1e-9]
        )
        block = block.cut(Part.makeBox(2, 20, 2, V(20, 0, 0))).removeSplitter()
        for walls in ((20.0,), (20.0, 22.0)):
            with self.subTest(walls=walls):

                def picked(shape, walls=walls):
                    edges = []
                    for e in shape.Edges:
                        b = e.BoundBox
                        top = abs(b.YMax) < 1e-9 and abs(b.ZMin - 5) < 1e-9 and b.XLength > 30
                        arc = (
                            b.XLength < 1e-9
                            and any(abs(b.XMin - x) < 1e-9 for x in walls)
                            and isinstance(e.Curve, Part.Circle)
                        )
                        if top or arc:
                            edges.append(e)
                    return edges

                self.assertEqual(len(picked(block)), 1 + len(walls))
                fillet = filleted_in_a_body(self.doc, block, picked, 1.5)
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertEqual(len(fillet.Shape.Solids), 1)


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


def finned_block(spline_back):
    """FilletFallbackTest's fin cube (a square face hanging inward at 45 degrees from the front
    bottom edge: invalid) made from the yz-profile extruded 10 along x, its back side a line or a
    B-spline through (y, z) = (11, 5), the same topology either way. Returns (the solid without the
    fin, the finned shape) (PR review r1, T1)"""
    if spline_back:
        curve = Part.BSplineCurve()
        curve.interpolate([V(0, 10, 0), V(0, 11, 5), V(0, 10, 10)])
        back = curve.toShape()
    else:
        back = Part.makeLine(V(0, 10, 0), V(0, 10, 10))
    wire = Part.Wire(
        [
            Part.makeLine(V(0, 0, 0), V(0, 10, 0)),
            back,
            Part.makeLine(V(0, 10, 10), V(0, 0, 10)),
            Part.makeLine(V(0, 0, 10), V(0, 0, 0)),
        ]
    )
    solid = Part.Solid(Part.Shell(Part.Face(wire).extrude(V(10, 0, 0)).Faces))
    if solid.Volume < 0:
        solid.reverse()
    hinge = next(
        e
        for e in solid.Edges
        if all(abs(v.Point.y) < 1e-9 and abs(v.Point.z) < 1e-9 for v in e.Vertexes)
    )
    fin = Part.Face(
        Part.Wire(
            [
                hinge,
                Part.makeLine(V(10, 0, 0), V(10, 5, 5)),
                Part.makeLine(V(10, 5, 5), V(0, 5, 5)),
                Part.makeLine(V(0, 5, 5), V(0, 0, 0)),
            ]
        )
    )
    bottom = next(
        f for f in solid.Faces if isinstance(f.Surface, Part.Plane) and abs(f.BoundBox.ZMax) < 1e-9
    )
    new_bottom = Part.Face(bottom.Surface, bottom.OuterWire)
    if bottom.Orientation == "Reversed":
        new_bottom = new_bottom.reversed()
    return solid, solid.replaceShape([(bottom, Part.Compound([new_bottom, fin]))])


def hexagonal_prism_with_pockets():
    """A hexagonal prism (circumradius 40, 20 high: its vertical edges are 120 degree corners), with
    a pocket 0.4 deep in each side face at the vertex (40, 0), 22.5 to 24.5 from its edge along the
    face, z 5 to 15. Returns the shape, the vertex's edge, and the two faces' directions from it
    (PR review r1, T2)"""
    corners = [
        V(40 * math.cos(math.radians(60 * k)), 40 * math.sin(math.radians(60 * k)), 0)
        for k in range(6)
    ]
    prism = Part.Face(Part.makePolygon(corners + [corners[0]])).extrude(V(0, 0, 20))
    corner = V(40, 0, 0)
    sides = []
    for sign in (1, -1):
        along = V(-0.5, sign * math.sqrt(3) / 2, 0)
        outward = V(math.sqrt(3) / 2, sign * 0.5, 0)
        sides.append(along)
        a = corner + along * 22.5 + V(0, 0, 5)
        b = corner + along * 24.5 + V(0, 0, 5)
        inward = outward * -0.4
        quad = [a + outward, b + outward, b + inward, a + inward]
        prism = prism.cut(Part.Face(Part.makePolygon(quad + [quad[0]])).extrude(V(0, 0, 10)))
    edge = next(
        e
        for e in prism.Edges
        if all(abs(v.Point.x - 40) < 1e-9 and abs(v.Point.y) < 1e-9 for v in e.Vertexes)
    )
    return prism, edge, sides


class DressUpCheckLimitsTest(unittest.TestCase):
    """What the result checks of ops#603 and ops#604 leave alone (PR review r1): a repaired result
    (its geometry copied) whose base has a B-spline face away from the round, and a distance-angle
    chamfer on an obtuse edge, whose far side lies beyond any reach taken from its size alone.
    """

    setUp = InvalidDressUpTest.setUp
    tearDown = InvalidDressUpTest.tearDown

    def testRepairedResultBesideASplineFace(self):
        # T1: the fin cube's repair copies the geometry, so no result face shares a base surface;
        # the B-spline back side is no bridge
        plain, finned = finned_block(True)
        fillet = filleted_in_a_body(self.doc, finned, front_top, 1)
        self.assertTrue(fillet.isValid(), fillet.getStatusString())
        right = plain.makeFillet(1, front_top(plain))
        self.assertLess(symmetric_difference(fillet.Shape, right), 1e-6)

    def testDistanceAngleChamferOnAnObtuseEdge(self):
        # T2: Size 10, Angle 45 on the 120 degree edge: 10 along one face and
        # 10 sin 45 / sin 165 = 27.32 along the other, which removes that face's pocket whole
        shape, edge, sides = hexagonal_prism_with_pockets()
        base = self.doc.addObject("Part::Feature", "Base")
        base.Shape = shape
        body = self.doc.addObject("PartDesign::Body", "Body")
        body.BaseFeature = base
        self.doc.recompute()
        stored = base.Shape
        name = next(
            "Edge%d" % i
            for i, e in enumerate(stored.Edges, 1)
            if all(abs(v.Point.x - 40) < 1e-9 and abs(v.Point.y) < 1e-9 for v in e.Vertexes)
        )
        chamfer = body.newObject("PartDesign::Chamfer", "Chamfer")
        chamfer.Base = (body.BaseFeature, [name])
        chamfer.ChamferType = "Distance and Angle"
        chamfer.Size = 10
        chamfer.Angle = 45
        self.doc.recompute()
        self.assertTrue(chamfer.isValid(), chamfer.getStatusString())
        far = 10 * math.sin(math.radians(45)) / math.sin(math.radians(165))
        corner = V(40, 0, -1)
        rights = []
        for one, other in ((sides[0], sides[1]), (sides[1], sides[0])):
            points = [corner, corner + one * 10, corner + other * far]
            wedge = Part.Face(Part.makePolygon(points + [points[0]])).extrude(V(0, 0, 22))
            rights.append(shape.cut(wedge))
        self.assertLess(min(symmetric_difference(chamfer.Shape, right) for right in rights), 1e-6)


def plate_with_holes(size, centres, radius=1.45):
    """A plate of the given size at the origin, with through holes of the radius at the centres
    (x, y), and the holes' top rims"""
    length, width, thickness = size
    plate = Part.makeBox(length, width, thickness)
    for x, y in centres:
        plate = plate.cut(Part.makeCylinder(radius, thickness + 2, V(x, y, -1)))
    rims = [
        e
        for e in plate.Edges
        if e.Curve.TypeId == "Part::GeomCircle"
        and abs(e.Curve.Radius - radius) < 1e-9
        and abs(e.Curve.Center.z - thickness) < 1e-9
    ]
    return plate, rims


def wall_on_base():
    """A base 20 x 10 x 2 with a wall 1.5 wide and 6 tall on it (x 0..20, y 4.25..5.75, z 2..8),
    and the wall's top edge at y 4.25"""
    wall = Part.makeBox(20, 10, 2).fuse(Part.makeBox(20, 1.5, 6, V(0, 4.25, 2))).removeSplitter()
    return wall, [edge_between(wall, (0, 4.25, 8), (20, 4.25, 8))]


class OverflowTest(unittest.TestCase):
    """Fillets and chamfers past their faces, and bands that meet or overlap (ops#640, S3).

    Onshape builds them all: the result is the base minus the union of the full section tools,
    trimmed by the base's own faces (notes/onshape-facts.md KP1, KP3, K2A-K2E in the ops repository).
    The expected volumes and face counts are Onshape's; the closed forms are given where they are
    short. OCCT 8.0.1 refuses most of these, and so did the exact construction before S3.
    """

    def assertBuilt(self, shape, volume, faces=None):
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, delta=2e-3)
        if faces is not None:
            self.assertEqual(len(shape.Faces), faces)

    def dressUp(self, kind, shape, size, edges):
        if kind == "Fillet":
            return shape.makeFillet(size, edges)
        return shape.makeChamfer(size, edges)

    def testRimsWhoseBandsMeetOrOverlap(self):
        # K2A, KP2: two holes 6 apart, 3.1 of land between the rims: the bands meet at 1.55
        plate, rims = plate_with_holes((30, 20, 5), [(12, 10), (18, 10)])
        for kind, size, volume in (
            ("Chamfer", 1.55, 2904.260),
            ("Chamfer", 1.5501, 2904.256),
            ("Chamfer", 1.56, 2903.825),
            ("Chamfer", 2.0, 2881.118),
            ("Fillet", 1.55, 2922.310),
            ("Fillet", 1.57, 2921.9784),  # oracle 9
            ("Fillet", 1.6, 2921.4703),
        ):
            with self.subTest(kind=kind, size=size):
                self.assertBuilt(self.dressUp(kind, plate, size, rims), volume, 10)

    def testRimsWhoseTipVerticesHaveRaisedTolerances(self):
        # ops#669: two rims' rounds meet the top face nearly tangentially at their lens's tips;
        # OCCT 8.0.1's cut leaves vertices of tolerance up to 4e-5 there, the faces' pcurve loops
        # open by that much, and the integrated volume is up to 1.3e-4 of the tool off: more than
        # 1e-6 of it (macOS refused K2A's fillet 1.6 so; on Windows these). The volumes: the plate
        # less the two rounds (Pappus) plus their lens (quadrature)
        for gap, size, volume in (
            (6.0, 1.62, 2921.1248),
            (6.0, 1.625, 2921.0376),
            (5.9, 1.54, 2922.4743),
            (5.9, 1.545, 2922.3925),
            (5.9, 1.565, 2922.0619),
            (5.8, 1.5, 2923.1168),
            (5.8, 1.505, 2923.0377),
        ):
            with self.subTest(gap=gap, size=size):
                plate, rims = plate_with_holes(
                    (30, 20, 5), [(15 - gap / 2, 10), (15 + gap / 2, 10)]
                )
                self.assertBuilt(plate.makeFillet(size, rims), volume, 10)

    def testRimsAtTwentyTimesWhoseLensIsBelowTheVolumesNoise(self):
        # ops#669: K2A's fillet 1.6 at 20x (holes r 29, 120 apart, fillet 32). The raised tolerances
        # (3.2e-4) put the integrated volume 0.099 off the closed form, and the lens the rounds share
        # is 0.105: the volume check can't tell a lens left from a lens removed (the construction
        # checks it by points). The shape is right: the material in a box around the lens is the
        # analytic 3105.6097 (midpoint quadrature of the material's height over x, y; 4000 x 4000
        # and 2000 x 2000 agree to 2e-7), and nothing of the lens is left
        plate, rims = plate_with_holes((600, 400, 100), [(240, 200), (360, 200)], 29)
        shape = plate.makeFillet(32, rims)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertEqual(len(shape.Faces), 10)
        # The plate less the two rounds (Pappus) plus the lens, to the measurement's noise: the
        # adaptive readout (SC7, ops#640) reads 0.28 under (1.2e-8), the default was 0.099 off
        self.assertAlmostEqual(shape.Volume, 23371762.554, delta=0.4)
        half = math.sqrt(61**2 - 58.6**2) + 0.4  # the lens's half length (to x 301.4), plus 0.4
        box = Part.makeBox(2.8, 2 * half, 32, V(298.6, 200 - half, 68))
        self.assertAlmostEqual(shape.common(box).Volume, 3105.6097, delta=0.01)
        # Points inside the lens (removed by both rounds; it is 0.0156 thick at its middle, x 300,
        # y 200, and ends 11 to either side): outside the result
        for x, y, z in ((300, 200, 99.995), (300, 198, 99.995), (300.3, 200, 99.995)):
            self.assertFalse(shape.isInside(V(x, y, z), 1e-6, True), (x, y, z))

    def testRimsWhoseRoundsBarelyOverlapFail(self):
        # Debt (ops#640): Onshape builds K2A's fillet 1.56 (2922.145). Where two rounds overlap by
        # less than about 0.02, each is within 1e-5 of the plate's top in the lens they share, and
        # OCCT 8.0.1's cut leaves a piece of the second tool's top face: the construction refuses
        plate, rims = plate_with_holes((30, 20, 5), [(12, 10), (18, 10)])
        with self.assertRaises(Part.OCCError):
            plate.makeFillet(1.56, rims)

    def testRimPastTheLandToASide(self):
        # KP1, K2B: a hole 1.55 from the plate's side: the band runs onto the side face
        plate, rims = plate_with_holes((20, 20, 5), [(3, 10)])
        for size, volume in ((1.56, 1951.913), (1.6, 1951.024)):
            with self.subTest(size=size):
                self.assertBuilt(self.dressUp("Chamfer", plate, size, rims), volume, 8)
        plate, rims = plate_with_holes((30, 20, 5), [(3, 10)])
        self.assertBuilt(self.dressUp("Chamfer", plate, 2.0, rims), 2940.559, 8)
        # OCCT builds this one itself, with a B-spline patch where the round meets the side: 10
        # faces against Onshape's 8, the same volume
        self.assertBuilt(self.dressUp("Fillet", plate, 1.6, rims), 2960.735)

    def testRimThroughAThinPlate(self):
        # K2C: a chamfer deeper than the plate consumes the hole's wall
        plate, rims = plate_with_holes((20, 20, 1.55), [(10, 10)])
        for size, volume in ((1.6, 593.823), (2.0, 584.181)):
            with self.subTest(size=size):
                self.assertBuilt(self.dressUp("Chamfer", plate, size, rims), volume, 7)

    def testWallTopPastItsWidth(self):
        # K2D: the top consumed, the band clipped by the far side (the base is 580; the chamfer
        # removes 20 (w^2 / 2 - (w - 1.5)^2 / 2))
        wall, edges = wall_on_base()
        for kind, size, volume in (
            ("Chamfer", 2.0, 580 - 20 * (2 - 0.5**2 / 2)),
            ("Chamfer", 3.0, 580 - 20 * (4.5 - 1.5**2 / 2)),
            ("Fillet", 2.0, 563.042),
        ):
            with self.subTest(kind=kind, size=size):
                self.assertBuilt(self.dressUp(kind, wall, size, edges), volume, 10)

    def testRoundsJustPastTheLimit(self):
        # The two long top edges of a box 30 x 4 x 20 rounded past half its width (the rounds
        # overlap), and one rounded past the whole width (KP3): 30 times the section's area
        box = Part.makeBox(30, 4, 20)
        edges = top_edges(box)
        for size, count in ((2.1, 2), (2.01, 2), (4.01, 1)):
            with self.subTest(size=size, edges=count):
                # One round's width at depth r (1 - cos t) is r (1 - sin t), t from 0 to pi / 2
                def section(t):
                    width = min(4.0, count * size * (1 - math.sin(t)))
                    return width * size * math.sin(t)

                kink = math.asin(max(0.0, 1 - 4.0 / count / size))
                area = gauss_legendre(section, 0, kink, 64) + gauss_legendre(section, kink, math.pi / 2, 64)
                self.assertBuilt(box.makeFillet(size, edges[:count]), 2400 - 30 * area, 7 if count == 2 else 6)

    def testOverlongFullChamfers(self):
        # Chamfers just past a full round of a stadium plate 4 thick and a disk 2 thick: the
        # two chamfers of a side face meet in a ridge. Removed: the straight sides' length times
        # the section, and the section about the arcs' axis (Pappus, by quadrature in u, the
        # distance in from the side)
        for model, size, thickness, straight, radius in ((stadium_plate, 2.0002, 4, 40, 5), (disk, 1.00001, 2, 0, 10)):
            with self.subTest(model=model.__name__):
                shape, edges = model()
                width = lambda u: min(thickness, 2 * (size - u))
                kink = size - thickness / 2
                removed = sum(
                    gauss_legendre(lambda u: (straight + 2 * math.pi * (radius - u)) * width(u), a, b, 32)
                    for a, b in ((0, kink), (kink, size))
                )
                self.assertBuilt(shape.makeChamfer(size, edges), shape.Volume - removed, 10 if straight else 4)

    def testEdgePastItsFace(self):
        # KP3: a box 10 x 10 x 2, a top edge rounded past the face's height
        box = Part.makeBox(10, 10, 2)
        edge = [edge_between(box, (0, 0, 2), (10, 0, 2))]
        self.assertBuilt(self.dressUp("Fillet", box, 2.1, edge), 190.537, 6)

    def testTwoBandsOverlappingOnOneFace(self):
        # K2E: both edges of a face 10 high: the chamfers meet in a ridge,
        # 20 (2 w^2 / 2 - (2 w - 10)^2 / 4)
        box = Part.makeBox(20, 20, 10)
        edges = [edge_between(box, (0, 0, 10), (20, 0, 10)), edge_between(box, (0, 0, 0), (20, 0, 0))]
        for size in (5.5, 6):
            with self.subTest(size=size):
                removed = 20 * (size**2 - (2 * size - 10) ** 2 / 4)
                self.assertBuilt(self.dressUp("Chamfer", box, size, edges), 4000 - removed, 7)
        for size, volume in ((5.5, 3740.483), (6, 3692.089)):
            with self.subTest(size=size):
                self.assertBuilt(self.dressUp("Fillet", box, size, edges), volume, 7)

    def testPastAConcaveEdgeTheWallGrows(self):
        # Q-LEDGE S1-S5 (oracle 12, notes/onshape-facts.md LD1-LD3): a step, top z 10 over y 4..10,
        # wall y 4 down to z 10 - h, ledge z 10 - h; the top's edge above the wall dressed up 1.0.
        # Past h the strip runs onto the ledge, and Onshape trims the dress-up by the ledge's plane:
        # the ledge grows under it, F stays 8. Volumes are Onshape's
        for case, h, kind, volume, ledge in (
            ("S1", 0.963, "Chamfer", 1912.97369, 4.037),
            ("S2", 0.5, "Chamfer", 1952.50000, 4.5),
            ("S3", 0.963, "Fillet", 1918.66813, 5 - math.sqrt(1 - 0.037**2)),
            ("S4", 0.5, "Fillet", 1956.14185, 5 - math.sqrt(0.75)),
            ("S5", 1.0, "Chamfer", 1910.00000, 4.0),
        ):
            with self.subTest(case=case):
                base = Part.makeBox(20, 10, 10).cut(Part.makeBox(22, 5, h + 1, V(-1, -1, 10 - h)))
                shape = self.dressUp(kind, base, 1.0, [edge_between(base, (0, 4, 10), (20, 4, 10))])
                self.assertBuilt(shape, volume, 8)
                self.assertAlmostEqual(shape.Volume, volume, delta=1e-5)
                floor = [f for f in shape.Faces if abs(f.BoundBox.ZMin - (10 - h)) < 1e-9
                         and f.BoundBox.ZLength < 1e-9]
                self.assertEqual(len(floor), 1)
                self.assertAlmostEqual(floor[0].BoundBox.YMax, ledge, delta=1e-6)

    def testAnArcAcrossItsCirclesSeamGetsOneRound(self):
        # Case Base #105's R 1 arcs rounded at r 1 (ops#640): a plate 10 x 10 x 1 with the corner at (10, 10)
        # rounded R 1, its top edges along x 10, the arc and y 10 rounded 1.0 (at the limit: the plate is 1
        # thick, so OCCT refuses). The arc's round is an octant of a sphere. Where the arc lies across its
        # circle's seam (the circle's X axis at 45 or 60 degrees: the arc runs 5.5..7.07), the round came in
        # two faces, split at the sphere's seam: F 8. On #105's body OCCT's cut by such a tool left an invalid
        # face. One face wherever the seam is: F 7. The volume: the plate less two prisms 9 long and the
        # quarter cylinder less the octant, pi / 4 - pi / 6
        for seam in (0.0, math.pi / 4, math.pi / 3, -math.pi / 2):
            with self.subTest(seam=seam):
                circle = Part.Circle(V(9, 9, 0), V(0, 0, 1), 1)
                circle.AngleXU = seam
                arc = Part.ArcOfCircle(circle, -seam, math.pi / 2 - seam).toShape()
                corners = [V(9, 10, 0), V(0, 10, 0), V(0, 0, 0), V(10, 0, 0), V(10, 9, 0)]
                lines = [Part.makeLine(a, b) for a, b in zip(corners, corners[1:])]
                base = Part.Face(Part.Wire([arc] + lines)).extrude(V(0, 0, 1))
                edges = [
                    edge_between(base, (10, 0, 1), (10, 9, 1)),
                    edge_between(base, (10, 9, 1), (9, 10, 1)),
                    edge_between(base, (9, 10, 1), (0, 10, 1)),
                ]
                shape = self.dressUp("Fillet", base, 1.0, edges)
                volume = 100 - (1 - math.pi / 4) - 18 * (1 - math.pi / 4) - math.pi / 12
                self.assertBuilt(shape, volume, 7)
                self.assertAlmostEqual(shape.Volume, volume, delta=1e-5)
                self.assertEqual(len([f for f in shape.Faces if f.Surface.TypeId == "Part::GeomSphere"]), 1)

    def testASphereRoundWhoseArcIsALastDigitOffItsRadius(self):
        # Case Base #105 on the fork's own #104 (ops#640): the R 1 arcs there have the radius 1 + 7e-15, so
        # the round's centre is 7e-15 off the arc's axis. The tool was a revolved ring less a sphere, and
        # OCCT's cut returned the ring whole, without an error: "a tool's volume 0.92 differs from its
        # closed form 0.31". The seam test's plate with the corner's radius a few last digits off 1, either
        # way: the round's section is revolved itself (no Boolean), an octant of a sphere, the seam test's
        # volume and F 7
        for off in (7e-15, -7e-15, 4e-15, 2e-12):
            with self.subTest(off=off):
                rho = 1 + off
                arc = Part.ArcOfCircle(Part.Circle(V(9, 9, 0), V(0, 0, 1), rho), 0, math.pi / 2).toShape()
                corners = [V(9, 9 + rho, 0), V(0, 9 + rho, 0), V(0, 0, 0), V(9 + rho, 0, 0), V(9 + rho, 9, 0)]
                lines = [Part.makeLine(a, b) for a, b in zip(corners, corners[1:])]
                base = Part.Face(Part.Wire([arc] + lines)).extrude(V(0, 0, 1))
                edges = [
                    e
                    for e in base.Edges
                    if abs(e.BoundBox.ZMin - 1) < 1e-9 and (e.BoundBox.XMin > 8.5 or e.BoundBox.YMin > 8.5)
                ]
                self.assertEqual(len(edges), 3)
                shape = self.dressUp("Fillet", base, 1.0, edges)
                volume = 100 - (1 - math.pi / 4) - 18 * (1 - math.pi / 4) - math.pi / 12
                self.assertBuilt(shape, volume, 7)
                self.assertAlmostEqual(shape.Volume, volume, delta=1e-5)
                self.assertEqual(len([f for f in shape.Faces if f.Surface.TypeId == "Part::GeomSphere"]), 1)

    def testAnArcStoredAsASplineIsRefused(self):
        # Case Base #105 on the fork's own body (ops#640): its R 1 corner arcs are B-spline curves within 1e-7
        # of a circle, on B-spline faces within as much of a cylinder (OCCT's fillet of an earlier feature;
        # Onshape's are arcs on cylinders), and the fillet fails with this message. The seam test's plate with
        # its corner arc stored as a B-spline, exact (rational) or interpolated through 41 points: the corner
        # face is then an extrusion of it. Not built yet: the construction knows lines and circles only, and
        # refuses, loudly. Built, it is the seam test's result (its volume, F 7)
        for how in ("rational", "interpolated"):
            with self.subTest(how=how):
                arc = Part.ArcOfCircle(Part.Circle(V(9, 9, 0), V(0, 0, 1), 1), 0, math.pi / 2)
                if how == "rational":
                    curve = arc.toBSpline()
                else:
                    curve = Part.BSplineCurve()
                    curve.interpolate(
                        [arc.value(math.pi / 2 * i / 40) for i in range(41)],
                        InitialTangent=V(0, 1, 0),
                        FinalTangent=V(-1, 0, 0),
                    )
                corners = [V(9, 10, 0), V(0, 10, 0), V(0, 0, 0), V(10, 0, 0), V(10, 9, 0)]
                lines = [Part.makeLine(a, b) for a, b in zip(corners, corners[1:])]
                base = Part.Face(Part.Wire([curve.toShape()] + lines)).extrude(V(0, 0, 1))
                self.assertTrue(base.isValid())
                edges = [
                    edge_between(base, (10, 0, 1), (10, 9, 1)),
                    edge_between(base, (10, 9, 1), (9, 10, 1)),
                    edge_between(base, (9, 10, 1), (0, 10, 1)),
                ]
                self.assertEqual(edges[1].Curve.TypeId, "Part::GeomBSplineCurve")
                with self.assertRaises(Part.OCCError) as refused:
                    self.dressUp("Fillet", base, 1.0, edges)
                # NEW-165: the refusal says OCCT failed on the curve, not that the edge is not allowed
                self.assertIn("the exact construction covers lines and circles", str(refused.exception))

    @staticmethod
    def tiltedLedge(h, t, wall):
        # testPastAConcaveEdgeTheWallGrows' step with its ledge tilted about the wall's foot (the line y 4,
        # z 10 - h): z = 10 - h + (y - 4) t, so the ledge is not square to the wall y 4 above it.
        # "plane": the ledge is a plane. "nurbs": the same plane as a bilinear B-spline patch that runs on
        # under the step (to y 6). "short": the patch ends at the wall's foot (y 4). "split": two such
        # patches, which meet at x 10, the middle of the dressed-up edge
        zl = lambda y: 10 - h + (y - 4) * t
        if wall == "plane":
            section = [V(-1, -1, zl(-1)), V(-1, 4, 10 - h), V(-1, 4, 11), V(-1, -1, 11)]
            air = Part.Face(Part.makePolygon(section + section[:1])).extrude(V(22, 0, 0))
            return Part.makeBox(20, 10, 10).cut(air)
        y1 = 6 if wall == "nurbs" else 4
        lower = []
        for x0, x1 in ((-5, 10), (10, 25)) if wall == "split" else ((-5, 25),):
            patch = Part.BSplineSurface()
            patch.buildFromPolesMultsKnots(
                [[V(x0, -1, zl(-1)), V(x0, y1, zl(y1))], [V(x1, -1, zl(-1)), V(x1, y1, zl(y1))]],
                [2, 2], [2, 2], [0, 1], [0, 1], False, False, 1, 1,
            )
            lower.append(patch.toShape().extrude(V(0, 0, -12)).common(Part.makeBox(20, 4, 10)))
        return Part.makeBox(20, 6, 10, V(0, 4, 0)).fuse(lower).removeSplitter()

    @staticmethod
    def tiltedLedgeResult(kind, h, t):
        # The base: the box less the air above the ledge, 20 int_0^4 (h - (y - 4) t) dy. The dress-up 1.0
        # removes its section above the ledge's plane run on under it (u = y - 4): the ledge grows to u,
        # where its line z = 10 - h + u t meets the dress-up. Returns the volume and that u
        base = 2000 - 20 * (4 * h + 8 * t)
        if kind == "Chamfer":
            # the triangle (0, 10), (1, 10), (0, 9) less its part under the line: 1 - h on u = 0, u wide
            u = (1 - h) / (1 - t)
            return base - 20 * (0.5 - (1 - h) * u / 2), u
        # the round's arc about (1, 9), z = 9 + sqrt(1 - (1 - u)^2), meets the line at the smaller root of
        # (1 + t^2) u^2 + 2 ((1 - h) t - 1) u + (1 - h)^2 = 0. Under the line up to there, then under the
        # arc: int_u^1 (1 - sqrt(1 - (1 - u)^2)) du = w - (w sqrt(1 - w^2) + asin w) / 2, w = 1 - u
        a, b, c = 1 + t * t, 2 * ((1 - h) * t - 1), (1 - h) ** 2
        u = (-b - math.sqrt(b * b - 4 * a * c)) / (2 * a)
        w = 1 - u
        return base - 20 * (h * u - t * u * u / 2 + w - (w * math.sqrt(1 - w * w) + math.asin(w)) / 2), u

    def testPastAConcaveEdgeATiltedWallGrows(self):
        # Case Base #105 (ops#640): a round's strip runs off its face over a concave edge into a wall that
        # does not rise square from the face (#103's blend, at 87 degrees). Onshape cuts the round off by the
        # wall, as by a square one (Q-LEDGE, testPastAConcaveEdgeTheWallGrows); the rule here is that result's,
        # the tilted ledge itself was not asked. The dress-up is trimmed by the ledge's own surface run on
        # under it: the ledge grows, F stays 8. Where the ledge's surface ends at the wall's foot ("short")
        # it is extended, and the part under the dress-up stays a face of its own: F 9
        for wall, faces in (("plane", 8), ("nurbs", 8), ("short", 9)):
            for kind in ("Chamfer", "Fillet"):
                for h, degrees in ((0.5, 5), (0.5, -5), (0.963, 3)):
                    with self.subTest(wall=wall, kind=kind, h=h, degrees=degrees):
                        t = math.tan(math.radians(degrees))
                        base = self.tiltedLedge(h, t, wall)
                        self.assertAlmostEqual(base.Volume, 2000 - 20 * (4 * h + 8 * t), delta=1e-6)
                        self.assertEqual(len(base.Faces), 8)
                        shape = self.dressUp(kind, base, 1.0, [edge_between(base, (0, 4, 10), (20, 4, 10))])
                        volume, u = self.tiltedLedgeResult(kind, h, t)
                        self.assertBuilt(shape, volume, faces)
                        self.assertAlmostEqual(shape.Volume, volume, delta=1e-5)
                        ledge = [
                            f for f in shape.Faces
                            if all(abs(v.Point.z - (10 - h + (v.Point.y - 4) * t)) < 1e-6 for v in f.Vertexes)
                        ]
                        self.assertEqual(len(ledge), faces - 7)
                        # by its vertices: a B-spline face's bound box is its surface's
                        reach = max(v.Point.y for f in ledge for v in f.Vertexes)
                        self.assertAlmostEqual(reach, 4 + u, delta=1e-6)

    def testATiltedWallThatWouldCutUncheckedIsRefused(self):
        # Review r1 of the tilted wall's trim (ops#640): two cases that the wall's surface would cut, with
        # nothing to check the result against. They are refused.
        # S1, two walls on two surfaces along one foot ("split": two patches that meet under the edge's
        # middle): the first patch, run on past its end, would cut the dress-up off in front of the second
        # too. Here the two are one plane, but the construction can't know it of two B-spline surfaces
        # (a second patch twisted to -5 degrees came out 0.117 mm3 wrong, built).
        # S2, a steep ledge (30 degrees over a wall 0.3 high): its plane would cut the whole chamfer or
        # round away and narrow the strip on the top face (it built a shape with no dress-up face)
        for wall, h, degrees, message in (
            ("split", 0.5, 5, "in front of another wall"),
            ("plane", 0.3, 30, "on its other face"),
            ("plane", 0.3, 60, "on its other face"),
        ):
            for kind in ("Chamfer", "Fillet"):
                with self.subTest(wall=wall, kind=kind, degrees=degrees):
                    base = self.tiltedLedge(h, math.tan(math.radians(degrees)), wall)
                    self.assertEqual(len(base.Faces), 9 if wall == "split" else 8)
                    with self.assertRaises(Part.OCCError) as refused:
                        self.dressUp(kind, base, 1.0, [edge_between(base, (0, 4, 10), (20, 4, 10))])
                    self.assertIn(message, str(refused.exception))

    def testConcavePastItsFaceIsClippedAtTheRibsTop(self):
        # A concave round past its face: r 8 at a rib's foot, the rib 4 high. Onshape clips it at
        # the rib's top (the face its strip reaches first, run on; ops#640, Case Base #46's rule):
        # the base plus the round's corner below z 14
        base = Part.makeBox(40, 20, 10).fuse(Part.makeBox(10, 20, 4, V(15, 0, 10))).removeSplitter()
        edge = [edge_between(base, (15, 0, 10), (15, 20, 10))]
        corner = Part.makeBox(8, 20, 8, V(7, 0, 10)).cut(
            Part.makeCylinder(8, 20, V(7, 0, 18), V(0, 1, 0))
        )
        added = corner.common(Part.makeBox(8, 20, 4, V(7, 0, 10))).Volume
        shape = base.makeFillet(8, edge)
        self.assertBuilt(shape, base.Volume + added)
        self.assertAlmostEqual(shape.Volume, base.Volume + added, delta=1e-6)
        self.assertLessEqual(shape.BoundBox.ZMax, 14 + 1e-6)

    def channel(self, wall):
        # A U channel 20 long in z: left wall x -5..0, slot floor x 0..2 at y 0, right wall x 2..2+wall, up to y 10
        base = (
            Part.makeBox(5, 15, 20, V(-5, -5, 0))
            .fuse([Part.makeBox(2, 5, 20, V(0, -5, 0)), Part.makeBox(wall, 15, 20, V(2, -5, 0))])
            .removeSplitter()
        )
        return base, [edge_between(base, (0, 0, 0), (0, 0, 20))]

    @staticmethod
    def slotSection(kind, size):
        # The dress-up's section (legs `size` on the floor and the left wall) inside the slot x 0..2
        if kind == "Chamfer":
            return 2 * size - 2
        # a fillet's: under y = size - sqrt(size^2 - (size - x)^2), x 0..2; u = size - x
        r = size
        prim = lambda u: u / 2 * math.sqrt(r * r - u * u) + r * r / 2 * math.asin(u / r)
        return 2 * r - (prim(r) - prim(r - 2))

    def testConcaveThroughAThinWallIsClipped(self):
        # Integrator 11 T2: the slot's floor edge dressed up at 6, wider than the slot (2): the
        # floor strip runs off the floor into the right wall. A wall 3 thick ends at x 5, so the
        # strip goes on into the air (x 5..6). Onshape clips the dress-up by the wall's back face
        # (oracle 9d): one solid with nothing past x 5, the base plus the section inside the slot.
        # The construction clips the tool by the wall's face its strip reaches first (x 2, ops#640
        # Case Base #46), the same result: the wall absorbs the rest
        for kind in ("Chamfer", "Fillet"):
            with self.subTest(kind=kind):
                base, edges = self.channel(3)
                shape = self.dressUp(kind, base, 6, edges)
                expected = base.Volume + 20 * self.slotSection(kind, 6)
                self.assertLessEqual(shape.BoundBox.XMax, 5 + 1e-6)
                self.assertBuilt(shape, expected)
                self.assertAlmostEqual(shape.Volume, expected, delta=1e-6)

    def testConcaveIntoAThickWallBuilds(self):
        # The control: a wall 10 thick (x 2..12) holds the strip's end (x 6): it builds, the base plus the slot's section
        for kind in ("Chamfer", "Fillet"):
            with self.subTest(kind=kind):
                base, edges = self.channel(10)
                shape = self.dressUp(kind, base, 6, edges)
                self.assertLessEqual(shape.BoundBox.XMax, 12 + 1e-6)
                self.assertBuilt(shape, base.Volume + 20 * self.slotSection(kind, 6))

    def testConcavePastItsFaceIntoARingIsClippedByTheRing(self):
        # The native replica's Case Base #46 (ops#640), designed (ring_corner()): Onshape clips the
        # dress-up by the cylinder its strip reaches first, R 15 above the ring's underside, r 12
        # under it (#46, read off Onshape's own result), so nothing is added inside the well. The
        # tool fused whole would leave a fin there
        for kind in ("Fillet", "Chamfer"):
            with self.subTest(kind=kind):
                base, ends, added, well = ring_corner(kind)
                shape = self.dressUp(kind, base, 10, [edge_between(base, *ends)])
                self.assertBuilt(shape, base.Volume + added)
                self.assertAlmostEqual(shape.Volume, base.Volume + added, delta=1e-6)
                self.assertLess(shape.common(well).Volume, 1e-9)


    def testConcaveRoundRollsOnOverATangentEdge(self):
        # The native replica's Case Base #47 (ops#640), designed (rounded_ring_corner()): r 6.5 on
        # the crease between the corner's r 10 round and the ring. No ball touches both faces, so
        # it rolls on over the round's tangent edge onto the wall x 0, as Onshape's does (oracle
        # 16, FR2): one round r 6.5 about (6.5, -18.4929) tangent to the wall and the ring, the r
        # 10 round left only under the ring (z 2..4, A 25.347863), 14 faces, +337.099410
        base, ends, added, axis = rounded_ring_corner()
        self.assertAlmostEqual(added, 337.099410, delta=1e-6)
        shape = base.makeFillet(6.5, [edge_between(base, *ends)])
        self.assertBuilt(shape, base.Volume + added, faces=14)
        self.assertAlmostEqual(shape.Volume, base.Volume + added, delta=1e-6)
        rounds = [
            f
            for f in shape.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - 6.5) < 1e-7
        ]
        self.assertEqual(len(rounds), 1)
        self.assertAlmostEqual(rounds[0].Surface.Center.x, axis[0], delta=1e-6)
        self.assertAlmostEqual(rounds[0].Surface.Center.y, axis[1], delta=1e-6)
        left = [
            f
            for f in shape.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - 10) < 1e-7
        ]
        self.assertEqual(len(left), 1)
        self.assertAlmostEqual(left[0].BoundBox.ZMin, 2, delta=1e-6)
        self.assertAlmostEqual(left[0].BoundBox.ZMax, 4, delta=1e-6)
        self.assertAlmostEqual(left[0].Area, 25.347863, delta=1e-5)

    def testConcaveRoundPastItsFacesTangentEdgeRollsOn(self):
        # Review r1 of #47 (small_round_ring_corner()): the ball of r 2 between the wall y 0 and the
        # ring would touch the wall's plane past the wall's end, over the tangent edge onto the
        # corner's r 3 round. It rolls on onto that round (13.762038), never left absorbed in its
        # material (4.836788, a crease of 22.85 degrees with the round)
        base, ends, added = small_round_ring_corner()
        self.assertAlmostEqual(added, 13.762038, delta=1e-5)
        shape = base.makeFillet(2, [edge_between(base, *ends)])
        self.assertBuilt(shape, base.Volume + added)
        self.assertAlmostEqual(shape.Volume, base.Volume + added, delta=1e-6)

    def testConcaveRoundAsBigAsTheRoundItLeavesRollsOn(self):
        # Nudge sweep of #47, gap 1 (ops#640): rounded_ring_corner()'s crease with r at and above the
        # corner's r 10. No ball that big rolls inside the r 10 round at all; OCCT returns a shape
        # that is not valid. The rule is the same as below r 10: the ball rolls on over the round's
        # tangent edge onto the wall x 0, one round tangent to the wall and the ring
        for corner, r in ((10, 10), (10, 12), (10, 22), (7, 9), (13, 14)):
            with self.subTest(corner=corner, r=r):
                base, ends, added, axis = rolled_ring_corner(corner, r)
                shape = base.makeFillet(r, [edge_between(base, *ends)])
                self.assertBuilt(shape, base.Volume + added)
                self.assertAlmostEqual(shape.Volume, base.Volume + added, delta=1e-6)
                rounds = [
                    f
                    for f in shape.Faces
                    if f.Surface.TypeId == "Part::GeomCylinder"
                    and abs(f.Surface.Radius - r) < 1e-7
                    and abs(f.Surface.Center.x - axis[0]) < 1e-6
                    and abs(f.Surface.Center.y - axis[1]) < 1e-6
                ]
                self.assertEqual(len(rounds), 1)

    def testConcaveRoundAsBigAsTheRoundItLeavesAsAFeature(self):
        # The same through the PartDesign feature (it refused: "Resulting shape is invalid"), and
        # the corner r 7 with r 4 (gap 2): the rolled round covers the r 7 round beyond the band
        # the check for lost material allows a direct round, which refused it ("drops a part of the
        # base"); the construction measured what it fused against its closed form
        for corner, r in ((10, 12), (7, 4)):
            with self.subTest(corner=corner, r=r):
                base, ends, added, _ = rolled_ring_corner(corner, r)
                doc = FreeCAD.newDocument("RollOnAsBig")
                try:
                    feature, _ = dressed_in_a_body(doc, "Fillet", base, ends, r)
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    self.assertTrue(feature.Shape.isValid())
                    self.assertAlmostEqual(feature.Shape.Volume, base.Volume + added, delta=1e-6)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testInvalidResultTheConstructionRefusesRaises(self):
        # Decision 418 (ops#640): where OCCT builds a shape that is not valid and the construction
        # refuses, the dress-up raises with the construction's reason; it never returns the invalid
        # shape. small_round_ring_corner() with r 2.5: the ball would roll on over two faces (the
        # r 3 round and the wall x 0 beyond it), which the construction does not build
        base, ends, _ = small_round_ring_corner()
        with self.assertRaises(Part.OCCError) as raised:
            base.makeFillet(2.5, [edge_between(base, *ends)])
        self.assertIn("is not a valid shape (exact construction refused: ", str(raised.exception))

    def testConcaveRoundPastASharpEndIsAbsorbedByTheWall(self):
        # Review r2 of #47: ring_corner()'s base, sharp corner, r 5 on the crease between the wall
        # y 0 and the ring. The ball (centre on y -5, 20 from the ring's axis) touches the wall's
        # plane at x -0.596, past the wall's end at x 0, a sharp concave edge onto the wall x 0: no
        # tangent edge to roll over. As past the limit (#46), the wall's material absorbs the part
        # past its end: the base plus the region between the walls, the ring and the ball
        base, _, _, _ = ring_corner("Fillet")
        x = 19 - math.sqrt(224)
        cx = 19 - math.sqrt(20**2 - 4**2)
        c = V(cx, -5, 0)
        b = V(19, -1, 0)
        touch = c + (b - c) * (5 / (b - c).Length)
        points = [V(cx, 0, 4), V(cx, -5, 4), V(touch.x, touch.y, 4), V(19, -1, 4), V(19, 0, 4), V(cx, 0, 4)]
        region = Part.Face(Part.makePolygon(points)).extrude(V(0, 0, 6))
        region = region.cut(Part.makeCylinder(5, 8, V(cx, -5, 3))).cut(Part.makeCylinder(15, 8, V(19, -1, 3)))
        added = region.cut(base).Volume
        self.assertAlmostEqual(added, 24.126342, delta=1e-5)
        shape = base.makeFillet(5, [edge_between(base, (x, 0, 4), (x, 0, 10))])
        self.assertBuilt(shape, base.Volume + added)
        self.assertAlmostEqual(shape.Volume, base.Volume + added, delta=1e-6)

    def testConcaveRoundPastAShortTangentEdgeFails(self):
        # Review r3 of #47: small_round_ring_corner(top=8), the corner rounded r 3 only up to z 8.
        # The wall's tangent edge onto that round runs z 2..8, the crease z 4..10: the ball of r 2
        # would roll on below z 8 and not above it (a mixed round the construction can't build).
        # It refuses, rather than leave the strip absorbed in the round's material (+4.867757, at a
        # crease of 22.85 degrees with the round)
        base, ends, _ = small_round_ring_corner(top=8)
        with self.assertRaises(Part.OCCError):
            shape = base.makeFillet(2, [edge_between(base, *ends)])
            if not shape.isValid():
                raise Part.OCCError("invalid")

    def testConvexRoundRollsOnOverATangentEdge(self):
        # rounded_ring_corner_mirror(): the convex mirror of Case Base #47's designed model. Onshape
        # builds it as the concave one, rolled on onto the wall x 0 (oracle 18, FR3): -337.099410,
        # 11 -> 12 faces, one r 6.5 face about (6.5, -18.4929), the r 10 round left at z 2..4
        base, ends, removed, axis = rounded_ring_corner_mirror()
        self.assertEqual(len(base.Faces), 11)
        shape = base.makeFillet(6.5, [edge_between(base, *ends)])
        self.assertBuilt(shape, base.Volume - removed, faces=12)
        self.assertAlmostEqual(shape.Volume, base.Volume - removed, delta=1e-6)
        rounds = [
            f
            for f in shape.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - 6.5) < 1e-7
        ]
        self.assertEqual(len(rounds), 1)
        self.assertAlmostEqual(rounds[0].Surface.Center.x, axis[0], delta=1e-6)
        self.assertAlmostEqual(rounds[0].Surface.Center.y, axis[1], delta=1e-6)
        self.assertAlmostEqual(rounds[0].Area, 85.458319, delta=1e-5)
        left = [
            f
            for f in shape.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - 10) < 1e-7
        ]
        self.assertEqual(len(left), 1)
        self.assertAlmostEqual(left[0].Area, 25.347863, delta=1e-5)

    def testConvexRoundRolledOnAsAFeature(self):
        # The same as a PartDesign feature: the checks for lost material and filled recesses pass
        base, ends, removed, _ = rounded_ring_corner_mirror()
        doc = FreeCAD.newDocument("ConvexRollOn")
        try:
            feature, _ = dressed_in_a_body(doc, "Fillet", base, ends, 6.5)
            self.assertTrue(feature.isValid(), feature.getStatusString())
            self.assertTrue(feature.Shape.isValid())
            self.assertEqual(len(feature.Shape.Faces), 12)
            self.assertAlmostEqual(feature.Shape.Volume, base.Volume - removed, delta=1e-6)
        finally:
            FreeCAD.closeDocument(doc.Name)

    def testConvexRolledRoundAgainstALedgeFails(self):
        # Review of the convex roll-on: rounded_ring_corner_mirror() with a block outside the wall
        # x 0 (x -3..0, y -40..-15, z 8..10), a ledge on the face the round rolls onto. The rules
        # for a strip past a ledge are Onshape's for direct rounds only: the rolled round refuses,
        # rather than build trimmed by the block's walls (15 faces, a 57.5 degree crease)
        base, ends, _, _ = rounded_ring_corner_mirror()
        base = base.fuse(Part.makeBox(3, 25, 2, V(-3, -40, 8))).removeSplitter()
        with self.assertRaises(Part.OCCError):
            shape = base.makeFillet(6.5, [edge_between(base, *ends)])
            if not shape.isValid():
                raise Part.OCCError("invalid")

    def testRoundOverANarrowStripFailsTruthfully(self):
        # A 100 x 100 x 2.6 plate, its outer top edges rounded r 1.5 (its top face ends 48.5 from
        # the middle), with a rounded rectangle hole (corners r 5) whose long side lies `gap` from
        # that round. One straight edge of the hole's top loop picked: OCCT's tangent chain runs
        # round the whole loop. A round r 1 across a 0.06 strip would run onto the outer round,
        # which neither OCCT nor the construction builds: the error says so, with the strip's
        # width and the radius, and no longer blames the tangent chain (ops#640)
        t = 2.6

        def holed(gap):
            plate = Part.makeBox(100, 100, t, V(-50, -50, 0))
            plate = plate.makeFillet(1.5, edges_at(plate, t))
            h = 2 * (48.5 - gap)
            hole = Part.makeBox(50.6, h, t + 2, V(-39.3, -h / 2, -1))
            hole = hole.makeFillet(5, [e for e in hole.Edges if e.BoundBox.ZLength > 1])
            return plate.cut(hole).removeSplitter()

        def hole_side(shape):
            return [
                e
                for e in edges_at(shape, t)
                if e.Curve.TypeId == "Part::GeomLine"
                and abs(e.CenterOfMass.x + 39.3) < 1e-6
                and abs(e.CenterOfMass.y) < 1e-6
            ]

        for gap in (3.0, 0.8):
            with self.subTest(gap=gap):
                shape = holed(gap)
                result = shape.makeFillet(1, hole_side(shape))
                self.assertTrue(result.isValid())
                self.assertLess(result.Volume, shape.Volume)
        shape = holed(0.06)
        self.assertTrue(shape.makeFillet(0.5, hole_side(shape)).isValid())
        with self.assertRaises(Part.OCCError) as caught:
            shape.makeFillet(1, hole_side(shape))
        message = str(caught.exception)
        self.assertNotIn("tangent chain", message)
        self.assertIn("round of radius 1 mm would overflow a strip of face 0.06 mm wide", message)
        self.assertIn("onto the neighbouring round", message)


def ring_corner(kind, size=10):
    """The native replica's Case Base #46, designed: a pocket's concave corner (x 0, y 0; floor z 2,
    top z 10) whose dress-up of the size is wider than the wall y 0 on its right: a ring (centre
    (19, -1), R 15, r 12, z 4..10) stands 4.03 from the corner, and under it (z 2..4) the ring's
    well, cut from z 2, ends the wall at 7.04. Returns the base, the corner edge's ends, the volume
    Onshape's dress-up adds (its corner, less the base, less everything inside the well's
    cylinder) and the well"""

    def cylinder(r, z0, z1):
        return Part.makeCylinder(r, z1 - z0, V(19, -1, z0))

    well = cylinder(12, 2, 10)
    base = (
        Part.makeBox(45, 60, 10, V(-5, -40, 0))
        .cut(Part.makeBox(40, 40, 8, V(0, -40, 2)))
        .fuse(cylinder(15, 4, 10))
        .cut(well)
        .removeSplitter()
    )
    if kind == "Fillet":
        arc = Part.ArcOfCircle(
            Part.Circle(V(size, -size, 2), V(0, 0, 1), size), math.pi / 2, math.pi
        ).toShape()
        rim = [
            Part.makeLine(V(0, 0, 2), V(size, 0, 2)),
            arc,
            Part.makeLine(V(0, -size, 2), V(0, 0, 2)),
        ]
    else:
        rim = [
            Part.makeLine(V(0, 0, 2), V(size, 0, 2)),
            Part.makeLine(V(size, 0, 2), V(0, -size, 2)),
            Part.makeLine(V(0, -size, 2), V(0, 0, 2)),
        ]
    prism = Part.Face(Part.Wire(rim)).extrude(V(0, 0, 8))
    added = prism.cut(base).cut(cylinder(12, 1, 11)).Volume
    return base, ((0, 0, 2), (0, 0, 10)), added, well

def rounded_ring_corner(step=False):
    """The native replica's Case Base #47, designed: ring_corner()'s base with its corner rounded
    r 10 as Onshape builds it (oracle 16: the round less the base and the well), and the crease
    between that round and the ring's outer wall (R 15), z 4..10. No ball of r 6.5 touches both: its
    centre would be 3.5 from the round's axis (10, -10) and 21.5 from the ring's (19, -1), 12.73
    apart. Onshape rolls it on over the round's tangent edge (x 0, y -10) onto the wall x 0: one
    round tangent to the wall and the ring, centre (6.5, -18.4929), with a flat bottom at z 4
    (oracle 16, FR2: +337.099410, 14 faces). Returns the base, the crease's ends, the volume the
    round adds (the region between the wall, the ring, that round and the base, over z 4..10) and
    the round's axis in the plane.

    With step, a step 3 wide along the wall from y -15 on, up to the ring's underside (z 4): the
    round's flat bottom lands on its top, a floor in the plane of the edge's end face that faces it
    (Onshape's #47 on its own input lands 1.345 of it on such a floor, z 3.075)"""
    base, ends, _, well = ring_corner("Fillet")
    if step:
        base = base.fuse(Part.makeBox(3, 25, 2, V(0, -40, 2))).removeSplitter()
    arc = Part.ArcOfCircle(Part.Circle(V(10, -10, 2), V(0, 0, 1), 10), math.pi / 2, math.pi)
    rim = [Part.makeLine(V(0, 0, 2), V(10, 0, 2)), arc.toShape(), Part.makeLine(V(0, -10, 2), V(0, 0, 2))]
    corner = Part.Face(Part.Wire(rim)).extrude(V(0, 0, 8)).cut(base)
    corner = corner.cut(Part.makeCylinder(12, 10, V(19, -1, 1)))
    rounded = base.fuse(corner).removeSplitter()
    crease = [
        e
        for e in rounded.Edges
        if e.Curve.TypeId == "Part::GeomLine"
        and abs(e.Length - 6) < 1e-7
        and sorted(
            round(f.Surface.Radius, 6)
            for f in rounded.ancestorsOfType(e, Part.Face)
            if f.Surface.TypeId == "Part::GeomCylinder"
        )
        == [10, 15]
    ]
    assert len(crease) == 1, crease
    a, b = (tuple(v.Point) for v in crease[0].Vertexes)
    y = -1 - math.sqrt(21.5**2 - 12.5**2)
    centre = V(6.5, y, 0)
    toward = V(19, -1, 0) - centre
    toward.normalize()
    touch = centre + toward * 6.5
    region = Part.Face(
        Part.makePolygon([V(0, y, 4), V(6.5, y, 4), V(touch.x, touch.y, 4), V(19, -1, 4), V(0, -1, 4), V(0, y, 4)])
    ).extrude(V(0, 0, 6))
    region = region.cut(Part.makeCylinder(6.5, 8, V(6.5, y, 3))).cut(Part.makeCylinder(15, 8, V(19, -1, 3)))
    return rounded, (a, b), region.cut(rounded).Volume, (6.5, y)


def rolled_ring_corner(corner, r):
    """rounded_ring_corner()'s body with its corner rounded r `corner`, and the crease between that
    round and the ring's outer wall (R 15, about (19, -1)), z 4..10, for a round of r that rolls on
    over the round's tangent edge (x 0, y -corner) onto the wall x 0: its centre is r from the wall
    and 15 + r from the ring's axis. Returns the base, the crease's ends, the volume the round adds
    (the region between the wall, the ring, the round and the base, over z 4..10) and the round's
    axis in the plane"""
    base, _, _, _ = ring_corner("Fillet")
    arc = Part.ArcOfCircle(Part.Circle(V(corner, -corner, 2), V(0, 0, 1), corner), math.pi / 2, math.pi)
    rim = [
        Part.makeLine(V(0, 0, 2), V(corner, 0, 2)),
        arc.toShape(),
        Part.makeLine(V(0, -corner, 2), V(0, 0, 2)),
    ]
    filled = Part.Face(Part.Wire(rim)).extrude(V(0, 0, 8)).cut(base)
    filled = filled.cut(Part.makeCylinder(12, 10, V(19, -1, 1)))
    rounded = base.fuse(filled).removeSplitter()
    # the crease: the left crossing of the round's circle (about (corner, -corner)) and the ring's
    a, b = V(corner, -corner, 0), V(19, -1, 0)
    d = (b - a).Length
    along = (corner**2 - 15**2 + d**2) / (2 * d)
    u = (b - a) * (1 / d)
    w = V(-u.y, u.x, 0)
    h = math.sqrt(corner**2 - along**2)
    cross = min((a + u * along + w * h, a + u * along - w * h), key=lambda p: p.x)
    ends = ((cross.x, cross.y, 4), (cross.x, cross.y, 10))
    y = -1 - math.sqrt((15 + r) ** 2 - (19 - r) ** 2)
    centre = V(r, y, 0)
    toward = b - centre
    toward.normalize()
    touch = centre + toward * r
    region = Part.Face(
        Part.makePolygon(
            [V(0, y, 4), V(r, y, 4), V(touch.x, touch.y, 4), V(19, -1, 4), V(19, 0, 4), V(0, 0, 4), V(0, y, 4)]
        )
    ).extrude(V(0, 0, 6))
    region = region.cut(Part.makeCylinder(r, 8, V(r, y, 3))).cut(Part.makeCylinder(15, 8, V(19, -1, 3)))
    return rounded, ends, region.cut(rounded).Volume, (r, y)


def rounded_ring_corner_mirror():
    """rounded_ring_corner()'s mirror: its box (45 x 60 x 10 from (-5, -40, 0)) less that body, so
    the pocket is the material and the crease between the r 10 round and the ring's wall is convex.
    The ball of r 6.5, now in the material, can't touch both faces either, and Onshape rolls it on
    over the same tangent edge onto the wall x 0 (oracle 18, FR3: -337.099410, 11 -> 12 faces, one
    r 6.5 face about (6.5, -18.4929), the r 10 round left at z 2..4 with A 25.347863). Returns the
    base, the crease's ends, the volume the round removes and its axis in the plane"""
    body, ends, added, axis = rounded_ring_corner()
    mirror = Part.makeBox(45, 60, 10, V(-5, -40, 0)).cut(body).removeSplitter()
    return mirror, ends, added, axis


def small_round_ring_corner(top=10):
    """ring_corner()'s base with its corner rounded r 3 (by Booleans, as rounded_ring_corner()), and
    the crease between the wall y 0 and the ring's outer wall (R 15) at x 19 - sqrt(224), z 4..10:
    the wall ends at x 3 in the r 3 round's tangent edge (review r1 of #47). A ball of r 2 tangent to
    the wall's plane and the ring would touch the plane at x 2.03, past the wall's end; by #47's rule
    it rolls on onto the r 3 round, tangent to it and to the ring. Returns the base, the crease's
    ends, and the volume that round adds: the region between the base, the ring and the ball, whose
    centre is 1 from the round's axis (3, -3) and 17 from the ring's (19, -1). With top under 10,
    the corner is rounded only up to z top, and sharp above it"""
    base, _, _, _ = ring_corner("Fillet")
    arc = Part.ArcOfCircle(Part.Circle(V(3, -3, 2), V(0, 0, 1), 3), math.pi / 2, math.pi)
    rim = [Part.makeLine(V(0, 0, 2), V(3, 0, 2)), arc.toShape(), Part.makeLine(V(0, -3, 2), V(0, 0, 2))]
    corner = Part.Face(Part.Wire(rim)).extrude(V(0, 0, top - 2)).cut(base)
    corner = corner.cut(Part.makeCylinder(12, 10, V(19, -1, 1)))
    rounded = base.fuse(corner).removeSplitter()
    x = 19 - math.sqrt(224)
    ends = ((x, 0, 4), (x, 0, 10))
    # the ball's centre: on the circle r 1 about A (3, -3) and the circle r 17 about B (19, -1), the
    # crossing on the corner's side (y above A's)
    a, b = V(3, -3, 0), V(19, -1, 0)
    d = (b - a).Length
    along = (1 - 17**2 + d**2) / (2 * d)
    u = (b - a) * (1 / d)
    w = V(-u.y, u.x, 0)
    c = a + u * along + w * math.sqrt(1 - along**2)
    touch_round = a + (c - a) * (3 / (c - a).Length)
    touch_ring = c + (b - c) * (2 / (b - c).Length)
    points = [touch_round, c, touch_ring, b, V(19, 0, 0), V(0, 0, 0), touch_round]
    region = Part.Face(Part.makePolygon([V(q.x, q.y, 4) for q in points])).extrude(V(0, 0, 6))
    region = region.cut(Part.makeCylinder(2, 8, V(c.x, c.y, 3))).cut(Part.makeCylinder(15, 8, V(19, -1, 3)))
    return rounded, ends, region.cut(rounded).Volume


def keyhole_ridge(arc_wall=1.0, leg_wall=0.963, height=3.0):
    """A keyhole-shaped wall (the native replica's #15, designed): the opening is a disc r 6.35
    and a slot toward +x; the wall's inner arc is 27.625 long and meets the slot's sides, each
    10.738 long, at sharp convex corners. The wall is arc_wall thick around the arc and leg_wall
    along the slot, whose ends are flat. Returns the solid and its inner top edges"""
    radius = 6.35
    half = (2 * math.pi - 27.625 / radius) / 2
    side = radius * math.sin(half)
    length = radius * math.cos(half) + 10.738
    outer = Part.makeCylinder(radius + arc_wall, height).fuse(
        Part.makeBox(length, 2 * (side + leg_wall), height, V(0, -side - leg_wall, 0))
    )
    opening = Part.makeCylinder(radius, height + 2, V(0, 0, -1)).fuse(
        Part.makeBox(length + 1, 2 * side, height + 2, V(0, -side, -1))
    )
    wall = outer.cut(opening).removeSplitter()
    edges = [
        e
        for e in wall.Edges
        if all(abs(v.Point.z - height) < 1e-9 for v in e.Vertexes)
        and (
            (e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Radius - radius) < 1e-9)
            or (e.Curve.TypeId == "Part::GeomLine" and abs(abs(e.CenterOfMass.y) - side) < 1e-9)
        )
    ]
    return wall, edges


def keyhole_groove(floor=2.6, height=0.8):
    """A plate 40 x 40 x 6 with a keyhole bore through it (a circle r 5 and a slot |x| < 3 open
    to y = -20) and a groove in the bore's wall from z = floor, height high (a circle r 6 and a
    slot |x| < 4). Returns the solid and the groove bottom's concave edges at the wall (the arc r 6
    and the two legs x = +-4), which meet at corners convex in the material"""

    def keyhole(r, h, z0, z1):
        y = -math.sqrt(r * r - h * h)
        arc = Part.Arc(V(h, y, z0), V(0, r, z0), V(-h, y, z0)).toShape()
        wire = Part.Wire(
            [
                arc,
                Part.makeLine(V(-h, y, z0), V(-h, -25, z0)),
                Part.makeLine(V(-h, -25, z0), V(h, -25, z0)),
                Part.makeLine(V(h, -25, z0), V(h, y, z0)),
            ]
        )
        return Part.Face(wire).extrude(V(0, 0, z1 - z0))

    plate = Part.makeBox(40, 40, 6, V(-20, -20, 0))
    plate = plate.cut(keyhole(5, 3, -1, 7)).cut(keyhole(6, 4, floor, floor + height)).removeSplitter()
    edges = [
        e
        for e in edges_at(plate, floor)
        if (e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Radius - 6) < 1e-9)
        or (
            e.Curve.TypeId == "Part::GeomLine"
            and abs(abs(e.BoundBox.XMin) - 4) < 1e-9
            and e.BoundBox.XLength < 1e-9
        )
    ]
    return plate, edges


def edges_at(shape, z):
    """The shape's edges in the plane at the height z"""
    return [
        e
        for e in shape.Edges
        if all(abs(v.Point.z - z) < 1e-9 for v in e.Vertexes) and abs(e.CenterOfMass.z - z) < 1e-9
    ]


def half_disc(thickness):
    return Part.makeCylinder(10, thickness).common(Part.makeBox(20, 20, thickness, V(0, -10, 0))).removeSplitter()


def lens(thickness):
    return Part.makeCylinder(10, thickness, V(-6, 0, 0)).common(
        Part.makeCylinder(10, thickness, V(6, 0, 0))
    ).removeSplitter()


class CornerWithACircleTest(unittest.TestCase):
    """Two-edge corners where an edge is a circle, at and past the limit (ops#640, the native
    replica's #15: a chamfer of a keyhole wall's inner top edges, as wide as the wall at the arc
    and wider than it along the slot; Onshape builds it).

    The expected shape is defined by OCCT's own dress-up, which builds these corners below the
    limit: the same edges on a base whose faces reach farther (a thicker wall, a taller plate), cut
    back to the base. At the limit or past it that is the base minus the dress-up's tools, as
    Onshape's results are (OverflowTest)."""

    def assertSameAs(self, shape, base, reference, faces):
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        expected = reference.common(base)
        # 1e-5: the readouts integrate adaptively only on free-form faces, and the reference's faces
        # may be analytic where the result's aren't. The chamfered lens: closed form 132.5514217
        # (the shrunken lenses' areas integrated over the depth), the result 1e-7 off it, the
        # reference's default integration 3.4e-6 off (SC7, ops#640)
        self.assertAlmostEqual(shape.Volume, expected.Volume, delta=1e-5)
        self.assertLess(symmetric_difference(shape, expected), 1e-6)
        self.assertEqual(len(shape.Faces), faces)

    def testKeyholeWallPastItsWidth(self):
        wall, edges = keyhole_ridge()
        wide, wideEdges = keyhole_ridge(1.6, 1.6)
        self.assertEqual(len(edges), 5)  # the arc in three pieces, at the cylinders' seams
        for kind in ("Chamfer", "Fillet"):
            with self.subTest(kind=kind, size=1.0):
                if kind == "Chamfer":
                    shape, reference = wall.makeChamfer(1.0, edges), wide.makeChamfer(1.0, wideEdges)
                else:
                    shape, reference = wall.makeFillet(1.0, edges), wide.makeFillet(1.0, wideEdges)
                # The wall's top is consumed: 10 faces, less the top, plus one per edge
                self.assertSameAs(shape, wall, reference, 14)
        # Past the arc's wall Onshape refuses (oracle 9e, CHAMFER/FILLET_OVERLAPS_EDGE_LOOP from
        # 1.001 on): the arc's strip and a leg's meet at a corner convex in the material, both
        # running past the top's outer loop. So does a wall 1.0 thick on the legs too
        legs = keyhole_ridge(1.0, 1.0)
        for name, solid, picked, size in (
            ("Chamfer", wall, edges, 1.05),
            ("Fillet", wall, edges, 1.05),
            ("Chamfer", wall, edges, 1.001),
            ("Chamfer", legs[0], legs[1], 1.001),
            ("Fillet", legs[0], legs[1], 1.05),
        ):
            with self.subTest(kind=name, size=size, legWall=solid is legs[0]):
                with self.assertRaises(Part.OCCError):
                    if name == "Chamfer":
                        solid.makeChamfer(size, picked)
                    else:
                        solid.makeFillet(size, picked)
        # Onshape (oracle 9, this wall): removed 25.0539 and 10.6857, area -30.2078 and -21.2981;
        # 12 faces, its arc being one edge
        for kind, removed, area in (("Chamfer", 25.0539, -30.2078), ("Fillet", 10.6857, -21.2981)):
            with self.subTest(onshape=kind):
                shape = wall.makeChamfer(1.0, edges) if kind == "Chamfer" else wall.makeFillet(1.0, edges)
                self.assertAlmostEqual(wall.Volume - shape.Volume, removed, delta=2e-4)
                self.assertAlmostEqual(shape.Area - wall.Area, area, delta=2e-4)

    def testKeyholeWallPartlyPastItsWidth(self):
        # Onshape (oracle 9e) builds a strip past the outer loop where no picked corner convex in
        # the material has such strips on both sides: the arc alone, one leg, both legs, thick legs.
        # Its volumes, to its 4 decimals; the faces differ, its arc being one edge
        wall, edges = keyhole_ridge()
        arc = [e for e in edges if e.Curve.TypeId == "Part::GeomCircle"]
        left = [e for e in edges if e.Curve.TypeId == "Part::GeomLine" and e.CenterOfMass.y > 0]
        right = [e for e in edges if e.Curve.TypeId == "Part::GeomLine" and e.CenterOfMass.y < 0]
        self.assertEqual((len(arc), len(left), len(right)), (3, 1, 1))
        self.assertAlmostEqual(wall.Volume, 149.6516, delta=1e-4)
        thick, thickEdges = keyhole_ridge(1.0, 1.775)
        # Debt (ops#676): the arc alone and the thick legs differ from Onshape, whose volumes are
        # in the comments; the current results are pinned (5e-4) so a change shows
        for name, solid, picked, kind, volume in (
            ("arc", wall, arc, "Fillet", 142.75744),  # Onshape 142.7221
            ("leg", wall, left, "Chamfer", 143.429),
            ("leg", wall, right, "Fillet", 147.019),
            ("legs", wall, left + right, "Chamfer", 137.2064),
            ("thick legs", thick, thickEdges, "Chamfer", 176.32184),  # Onshape 176.3182
        ):
            with self.subTest(picked=name, kind=kind):
                if kind == "Chamfer":
                    shape = solid.makeChamfer(1.05, picked)
                else:
                    shape = solid.makeFillet(1.05, picked)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Volume, volume, delta=5e-4)
        # The arc's chamfer alone, as Onshape's (V 133.1013, ops#676): its ends on the slot's sides,
        # planes that miss the arc's axis, trim it past the corners (ops#888 A2)
        alone = wall.makeChamfer(1.05, arc)
        self.assertTrue(alone.isValid())
        self.assertAlmostEqual(alone.Volume, 133.1013, delta=1e-4)
        # The arc and one leg: Onshape fails (CHAMFER_FAILED)
        with self.assertRaises(Part.OCCError):
            wall.makeChamfer(1.05, arc + left)

    def testRingAndUPastTheirWalls(self):
        # Onshape (oracle 9e) builds these at 1.05 on walls 1.0 thick, the top consumed: a ring's
        # inner top circle, and a U's three inner top edges, whose corners are concave
        ring = Part.makeCylinder(7.35, 3).cut(Part.makeCylinder(6.35, 5, V(0, 0, -1)))
        u = Part.makeBox(12, 12, 3).cut(Part.makeBox(10, 12, 5, V(1, 1, -1)))
        uEdges = [
            e
            for e in u.Edges
            if all(abs(v.Point.z - 3) < 1e-9 for v in e.Vertexes)
            and 0.75 < e.CenterOfMass.x < 11.25
            and 0.75 < e.CenterOfMass.y
        ]
        self.assertEqual(len(uEdges), 3)
        for name, solid, picked, kind, volume in (
            ("ring", ring, None, "Chamfer", 105.9712),
            ("ring", ring, None, "Fillet", 119.3319),
            ("U", u, uEdges, "Chamfer", 83.6333),
            ("U", u, uEdges, "Fillet", 94.2077),
        ):
            with self.subTest(solid=name, kind=kind):
                if name == "ring":
                    picked = [e for e in edges_at(solid, 3.0) if abs(e.Curve.Radius - 6.35) < 1e-9]
                    self.assertEqual(len(picked), 1)
                if kind == "Chamfer":
                    shape = solid.makeChamfer(1.05, picked)
                else:
                    shape = solid.makeFillet(1.05, picked)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Volume, volume, delta=1e-3)

    def testKeyholeWallAtItsWidth(self):
        wall, edges = keyhole_ridge(1.0, 1.0)
        wide, wideEdges = keyhole_ridge(1.6, 1.6)
        self.assertSameAs(wall.makeChamfer(1.0, edges), wall, wide.makeChamfer(1.0, wideEdges), 14)

    def testPlatesWithArcsChamferedThrough(self):
        # A half disc (a line and an arc at right angles) and a lens (two arcs), the whole top
        # loop chamfered as deep as the plate: the side faces vanish
        for maker in (half_disc, lens):
            with self.subTest(plate=maker.__name__):
                plate = maker(3.0)
                tall = maker(6.0)
                tall.translate(V(0, 0, -3))
                reference = tall.makeChamfer(3.0, edges_at(tall, 3.0))
                self.assertSameAs(plate.makeChamfer(3.0, edges_at(plate, 3.0)), plate, reference, 5)

    def assertKeyholeGrooveChamfer(self, size, added, area):
        plate, edges = keyhole_groove()
        self.assertEqual(len(edges), 3)
        shape = plate.makeChamfer(size, edges)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume - plate.Volume, added, delta=2e-4)
        self.assertAlmostEqual(shape.Area - plate.Area, area, delta=2e-4)
        self.assertEqual(len(shape.Faces), len(plate.Faces))

    def testKeyholeGrooveChamferAtTheLimit(self):
        # A groove 0.8 high cut into a keyhole bore's wall (ops#640, #15, designed): its bottom's
        # concave edges, an arc r 6 and two legs x = +-4 that meet it at corners convex in the
        # material, chamfered as wide as the groove is high. OCCT builds up to 0.79 (a sharp miter
        # at the corners) and refuses from 0.8 on. Onshape (oracle 9d) builds it with the sharp
        # miter: the walls vanish (one cone, two planes: faces +0)
        self.assertKeyholeGrooveChamfer(0.8, 18.94097, -27.87796)
        # A concave fillet there is not known from Onshape yet: OCCT's error
        plate, edges = keyhole_groove()
        with self.assertRaises(Part.OCCError):
            plate.makeFillet(0.8, edges)

    def testKeyholeGrooveChamferPastTheLimit(self):
        # Past the limit Onshape clips the chamfer by the groove's top (oracle 9d): one cone, two
        # planes, and the plate's side face whole, though the legs' ends rise past the groove's
        # top into the plate there (faces +0)
        self.assertKeyholeGrooveChamfer(0.81, 19.41115, -29.07163)

    def testReflexCornerWithACircle(self):
        # fillet-parity L8: a plate fused with a disc that bulges past its sides, the top loop
        # rounded as deep as the plate; Onshape builds it. The rounds meet past the reflex corners
        # of the outline, in Onshape's mitre (ops#640, fillet-tight-arc 8): the body is the plate
        # and the disc, each rounded along its own whole rim, fused
        box = Part.makeBox(20, 20, 3)
        disc = Part.makeCylinder(12, 3, V(20, 10, 0))
        plate = box.fuse(disc).removeSplitter()
        edges = edges_at(plate, 3.0)
        for r in (3.0, 1.0):
            with self.subTest(r=r):
                result = plate.makeFillet(r, edges)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                rule = (
                    box.makeFillet(r, edges_at(box, 3.0))
                    .fuse(disc.cut(rim_ring(V(20, 10, 0), 12, r, 3.0)))
                    .removeSplitter()
                )
                self.assertAlmostEqual(result.Volume, rule.Volume, delta=1e-3)
                self.assertAlmostEqual(result.Area, rule.Area, delta=1e-4)
        # A chamfer there is not built yet: OCCT's error
        with self.assertRaises(Part.OCCError):
            plate.makeChamfer(3.0, edges)


def wall_end_round(inner, outer, height):
    """A full round of a curved wall's flat end, r = half the wall: the volume it removes and the
    area the wall's end, cylinders and new blend change by. Between the end and the meridian of
    the rounds' common centre (sin beta = r / Rm), the annular sector goes and a half disc stays;
    the end face (t h) and the cylinders' strips ((Ri + Ro) beta h) give way to a half cylinder
    (pi r h). The caps' change (the section, on each face the round ends on) is the caller's."""
    r = (outer - inner) / 2
    beta = math.asin(r / ((inner + outer) / 2))
    section = beta * (outer**2 - inner**2) / 2 - math.pi * r * r / 2
    side = height * ((outer - inner) + (inner + outer) * beta - math.pi * r)
    return section, height * section, side


def curved_wall_on_base(start=0.0, refined=False):
    """ops#640 F1 (the replica's row 150): a curved wall R 10..11.5, 0..90 deg, z 2..6, joined to
    a base R 8..13.5, z 0..2, that starts at the angle `start`. At 0 the wall's end (y = 0) is
    flush with the base's; unrefined, they stay two faces in one plane, so four edges meet at the
    foot of each straight edge of the wall's end. Below 0 the wall's end stands on the base.
    Returns the solid and the two straight edges of the wall's end."""
    base = Part.makeCylinder(13.5, 2, V(0, 0, 0), V(0, 0, 1), 90 - start).cut(
        Part.makeCylinder(8, 4, V(0, 0, -1))
    )
    base.rotate(V(0, 0, 0), V(0, 0, 1), start)
    wall = Part.makeCylinder(11.5, 4, V(0, 0, 2), V(0, 0, 1), 90).cut(
        Part.makeCylinder(10, 6, V(0, 0, 1))
    )
    shape = base.fuse(wall)
    if refined:
        shape = shape.removeSplitter()
    edges = [edge_between(shape, (x, 0, 2), (x, 0, 6)) for x in (10, 11.5)]
    return shape, edges


def edge_count_at(shape, point):
    """The number of the shape's edges with a vertex at the point"""
    return sum(
        1 for e in shape.Edges if any((v.Point - V(*point)).Length < 1e-7 for v in e.Vertexes)
    )


class RoundUnderALipTest(unittest.TestCase):
    """A round that ends under a lip is built on the piece of the base in front of the lip's
    underside (ops#640, Case Base #103): only where every group of edges ends under one, and only
    where the round removes material."""

    C = 11.3125
    U = 21.225
    R = 0.79375

    def model(self):
        # A block with a corner rounded r 11.3125 about z, scooped below z 21.225 by an ellipsoid
        # under a 1 mm lip, and a 45 degree ramp rising on its top from the line x = -10
        c, u, top = self.C, self.U, self.U + 1
        block = Part.makeBox(40 + c, 40 + c, top, V(-40, -c, 0))
        block = block.cut(Part.makeBox(c, c, top, V(0, -c, 0)).cut(Part.makeCylinder(c, top)))
        m = FreeCAD.Matrix()
        m.scale(8, 8, 14)
        m.move(V(6, -6, 21.667))
        scoop = Part.makeSphere(1).transformGeometry(m)
        shape = block.cut(scoop.common(Part.makeBox(200, 200, u + 50, V(-100, -100, -50))))
        shape = shape.cut(Part.makeCylinder(7.658, 2, V(6, -6, u), V(0, 0, 1)))
        ramp = Part.makePolygon(
            [V(-10, -c, top), V(-20, -c, top + 10), V(-40, -c, top + 10), V(-40, -c, top), V(-10, -c, top)]
        )
        base = shape.fuse(Part.Face(ramp).extrude(V(0, 40 + c, 0))).removeSplitter()

        def ends(e):
            return [v.Point for v in e.Vertexes]

        def kinds(e):
            return [f.Surface.TypeId for f in base.ancestorsOfType(e, Part.Face)]

        lip = [
            e
            for e in base.Edges
            if "Part::GeomCylinder" in kinds(e)
            and any(k not in ("Part::GeomPlane", "Part::GeomCylinder") for k in kinds(e))
        ]
        back = [
            e
            for e in base.Edges
            if len(ends(e)) == 2
            and all(abs(q.y - 40) < 1e-7 and abs(q.z - top) < 1e-7 for q in ends(e))
            and abs(min(q.x for q in ends(e)) + 10) < 1e-7
            and abs(max(q.x for q in ends(e)) - c) < 1e-7
        ]
        foot = [
            e
            for e in base.Edges
            if len(ends(e)) == 2 and all(abs(q.x + 10) < 1e-7 and abs(q.z - top) < 1e-7 for q in ends(e))
        ]
        self.assertEqual((len(lip), len(back), len(foot)), (2, 1, 1))
        return base, lip, back, foot

    def testAConcaveEdgeInAnotherGroupIsNotLost(self):
        # Review pr103lip-r1, F1: with the lip's edges, a convex edge and the concave edge at the
        # ramp's foot (one group, no lip) came out valid without the foot's round: 0.69 mm3 of
        # material missing. The foot's round fills the point just inside the corner.
        base, lip, back, foot = self.model()
        inFoot = V(-9.95, 0, self.U + 1.05)
        alone = base.makeFillet(self.R, lip)
        self.assertTrue(alone.isValid())
        self.assertAlmostEqual(base.Volume - alone.Volume, 16.6663, delta=2e-3)
        others = base.makeFillet(self.R, back + foot)
        self.assertTrue(others.isValid())
        self.assertTrue(others.isInside(inFoot, 1e-7, True))
        expected = (base.Volume - alone.Volume) + (base.Volume - others.Volume)
        try:
            shape = base.makeFillet(self.R, lip + back + foot)
        except Part.OCCError:
            return
        if shape.isValid():
            self.assertTrue(shape.isInside(inFoot, 1e-7, True))
            self.assertAlmostEqual(base.Volume - shape.Volume, expected, delta=2e-3)


class CurvedWallEndTest(unittest.TestCase):
    """A full round of a curved wall's flat end (ops#640, the native replica's #150; Onshape's FR1,
    exact): the end's two straight edges lie between the end face and a cylinder, and rounds of
    half the wall's thickness share their centre, at the wall's middle radius Rm, r from the end.
    The end face is consumed: between the end and the centre's meridian the annular sector goes and
    a half disc stays, h (beta (Ro^2 - Ri^2) / 2 - pi r^2 / 2) with sin beta = r / Rm."""

    def wall(self, inner, outer, height):
        sector = Part.makeCylinder(outer, height, V(0, 0, 0), V(0, 0, 1), 90).cut(
            Part.makeCylinder(inner, height + 2, V(0, 0, -1))
        )
        edges = [
            e
            for e in sector.Edges
            if e.Curve.TypeId == "Part::GeomLine"
            and abs(e.Vertexes[0].Point.y) < 1e-9
            and abs(e.Vertexes[1].Point.y) < 1e-9
            and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) < 1e-9
        ]
        self.assertEqual(len(edges), 2)
        return sector, edges

    def testFullRoundOfACurvedWallsEnd(self):
        for inner, outer, height, volume in ((10, 11.5, 4, 100.34700), (10, 12, 3, None)):
            with self.subTest(inner=inner, outer=outer):
                sector, edges = self.wall(inner, outer, height)
                r = (outer - inner) / 2
                beta = math.asin(r / ((inner + outer) / 2))
                removed = height * (beta * (outer**2 - inner**2) / 2 - math.pi * r * r / 2)
                if volume is not None:
                    self.assertAlmostEqual(sector.Volume - removed, volume, delta=1e-5)  # FR1
                shape = sector.makeFillet(r, edges)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Volume, sector.Volume - removed, delta=1e-6)

    def testChamferOfACurvedWallsEndFails(self):
        # Not built yet: a chamfer's distances along a cylinder
        sector, edges = self.wall(10, 11.5, 4)
        with self.assertRaises(Part.OCCError):
            sector.makeChamfer(0.75, edges)

    def testFullRoundOfAWallOnABase(self):
        # ops#640 F1. The round ends square on the base's top: it removes the section over the
        # wall's height, the wall's top loses the section and the base's top gains it, and a half
        # cylinder takes the wall's end. Flush with the base's end and unrefined,
        # four edges meet at each foot (the end face and the base's are two faces in one plane);
        # refined (as Onshape's bodies are) or standing on the base, three.
        section, removed, side = wall_end_round(10, 11.5, 4)
        self.assertAlmostEqual(removed, 101.3164 - 100.3470, delta=1e-4)  # Onshape's FR1
        for start, refined, meeting in ((0, False, 4), (0, True, 3), (-10, False, 3)):
            with self.subTest(start=start, refined=refined):
                shape, edges = curved_wall_on_base(start, refined)
                self.assertEqual(edge_count_at(shape, (10, 0, 2)), meeting)
                self.assertEqual(edge_count_at(shape, (11.5, 0, 2)), meeting)
                result = shape.makeFillet(0.75, edges)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                self.assertAlmostEqual(result.Volume, shape.Volume - removed, delta=1e-6)
                self.assertAlmostEqual(result.Area, shape.Area - side, delta=1e-6)
                # One blend face, the half cylinder, as Onshape's (ops#900), and the wall's end
                # face goes unless it is also the base's (refined and flush)
                blends = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomCylinder"
                          and abs(f.Surface.Radius - 0.75) < 1e-7]
                self.assertEqual(len(blends), 1)
                self.assertAlmostEqual(sum(f.Area for f in blends), math.pi * 0.75 * 4, delta=1e-6)
                shared = refined and start == 0
                self.assertEqual(len(result.Faces), len(shape.Faces) + (1 if shared else 0))
                # The base is untouched: below its top the result is the base
                below = result.common(Part.makeBox(40, 40, 2, V(-20, -20, 0)))
                base = shape.common(Part.makeBox(40, 40, 2, V(-20, -20, 0)))
                self.assertAlmostEqual(below.Volume, base.Volume, delta=1e-6)

    def testWallFlushWithItsBaseStillRefusesAChain(self):
        # A split on the wall's own cylinder too (the base's inner radius the wall's): the base's
        # straight edge below the foot runs on from the picked one, and the round would have to
        # run on down it. Still refused, loudly, as before F1
        base = Part.makeCylinder(13.5, 2, V(0, 0, 0), V(0, 0, 1), 90).cut(
            Part.makeCylinder(10, 4, V(0, 0, -1))
        )
        wall = Part.makeCylinder(11.5, 4, V(0, 0, 2), V(0, 0, 1), 90).cut(
            Part.makeCylinder(10, 6, V(0, 0, 1))
        )
        shape = base.fuse(wall)
        edges = [edge_between(shape, (x, 0, 2), (x, 0, 6)) for x in (10, 11.5)]
        with self.assertRaises(Part.OCCError):
            shape.makeFillet(0.75, edges)


def wall_on_a_chamfered_rim(inset=0.0, chamfer=1.5):
    """ops#640 (the replica's #150, a full round at half a wall on a chamfered rim): a plate z -t..0
    (t 1.5), a box (y >= 0) and a half disc (y < 0) of radius Ro (11) whose rim is chamfered through
    the whole thickness (a cone from Ro - chamfer at z -t to Ro at z 0), and a wall of thickness t,
    -135..-45 deg, z 0..4, whose outer cylinder is `inset` inside the rim. At 0 it stands flush on
    the rim, and each outer end edge's foot has four edges and four faces: the wall's end, its outer
    cylinder, the plate's top and the cone. Returns the solid, the wall's four end edges, and the
    wall's inner and outer radii."""
    t = 1.5
    outer = 11.0
    h = 4.0
    wo = outer - inset
    wi = wo - t
    box = Part.makeBox(2 * outer, 15.0, t, V(-outer, 0, -t))
    cone = Part.makeCone(outer - chamfer, outer, t, V(0, 0, -t))
    half = cone.common(Part.makeBox(2 * outer + 2, outer + 1, t + 2, V(-outer - 1, -outer - 1, -t - 1)))
    plate = box.fuse(half).removeSplitter()
    ring = Part.makeCylinder(wo, h, V(0, 0, 0), V(0, 0, 1), 360).cut(
        Part.makeCylinder(wi, h, V(0, 0, 0))
    )
    sector = ring.common(
        Part.makeCylinder(wo + 1, h, V(0, 0, 0), V(0, 0, 1), 90).rotated(V(0, 0, 0), V(0, 0, 1), -135)
    )
    shape = plate.fuse(sector).removeSplitter()
    edges = []
    for e in shape.Edges:
        if e.Curve.TypeId != "Part::GeomLine" or len(e.Vertexes) != 2:
            continue
        a, b = e.Vertexes[0].Point, e.Vertexes[1].Point
        if abs(a.x - b.x) > 1e-9 or abs(a.y - b.y) > 1e-9 or abs(abs(a.z - b.z) - h) > 1e-9:
            continue
        if min(abs(math.hypot(a.x, a.y) - r) for r in (wo, wi)) < 1e-6 and a.y < 0:
            edges.append(e)
    return shape, edges, wi, wo


class WallOnAChamferedRimTest(unittest.TestCase):
    """A full round at half a wall whose outer face stands flush on a chamfered rim (ops#640, the
    replica's #150, refused by F1 as "a vertex where 4 edges meet"). The cone meets each outer
    foot only through the rim, which lies in the plate's top, and lies wholly below it; the round
    ends on the plate's top as it does on a plain plate (FR1 at each end), and the plate, its cone
    included, is untouched."""

    def check(self, inset, chamfer, feet):
        shape, edges, wi, wo = wall_on_a_chamfered_rim(inset, chamfer)
        self.assertEqual(len(edges), 4)
        self.assertEqual(
            sorted(edge_count_at(shape, min(e.Vertexes, key=lambda v: v.Point.z).Point) for e in edges),
            feet,
        )
        section, removed, side = wall_end_round(wi, wo, 4.0)
        result = shape.makeFillet((wo - wi) / 2, edges)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        expected = shape.Volume - 2 * removed
        self.assertAlmostEqual(result.Volume, expected, delta=1e-6 * expected)
        # The plate is untouched: below its top the result is the plate, the cone's area unchanged
        below = Part.makeBox(40, 40, 1.5, V(-20, -20, -1.5))
        self.assertAlmostEqual(
            result.common(below).Volume, shape.common(below).Volume, delta=1e-6 * expected
        )
        def cones(s):
            return sum(f.Area for f in s.Faces if f.Surface.TypeId == "Part::GeomCone")
        self.assertGreater(cones(shape), 0)
        self.assertAlmostEqual(cones(result), cones(shape), delta=1e-6)
        # The PartDesign feature refines; the raw result keeps the boolean's splits
        self.assertEqual(len(result.removeSplitter().Faces), len(shape.Faces))
        return result, cones(result)

    def testFullRoundOfAWallFlushOnAChamferedRim(self):
        for chamfer in (1.5, 0.8):
            with self.subTest(chamfer=chamfer):
                result, cone = self.check(0.0, chamfer, [3, 3, 4, 4])
                if chamfer == 1.5:
                    # Closed form (Onshape's check, oracle 14, notes/onshape-facts.md PB2): faces
                    # 13 -> 13; A 1281.195348 -> 1276.034170, the plate (top, bottom, sides, the two
                    # c t / 2 triangles at y = 0, the cone) and the wall (h (pi/2 (Ri + Ro) + 2 t))
                    # less wall_end_round's side at each end; the cone's area, half a frustum
                    # pi (2 R - c) sqrt(c^2 + t^2) / 2, 68.309325 unchanged
                    self.assertEqual(len(result.removeSplitter().Faces), 13)
                    self.assertAlmostEqual(result.Area, 1276.034170, delta=1e-6 * 1276.034170)
                    self.assertAlmostEqual(cone, 68.309325, delta=1e-6 * 68.309325)

    def testFullRoundOfAWallInsideAChamferedRim(self):
        # The control: the wall 0.2 inside the rim, three edges at every foot (F1 built it)
        self.check(0.2, 1.5, [3, 3, 3, 3])


def cusped_chamfer_volume(r, a, b):
    """The triangle (a on the end wall, b along the tunnel) swept round the half circle r and cut
    by the planes y = +-r: the integral over rho in [r, r + a] of 2 rho asin(r / rho) b (r + a - rho) / a."""

    def s(p):
        return math.sqrt(p * p - r * r)

    def f1(p):
        return p * p / 2 * math.asin(r / p) + r / 2 * s(p)

    def f2(p):
        return p**3 / 3 * math.asin(r / p) + r / 6 * (p * s(p) + r * r * math.log(p + s(p)))

    def g(p):
        return 2 * (r + a) * f1(p) - 2 * f2(p)

    return b / a * (g(r + a) - g(r))


class CuspTest(unittest.TestCase):
    """Case Base #76, designed (oracle 17 Q-CUSP, facts CU1-CU5): a tunnel r 5 along x through a block,
    and a slot as wide as the tunnel above its axis from x 15 on. The tunnel's upper half circle on the
    slot's end wall ends in cusps, where the slot's walls are tangent to the tunnel. Onshape chamfers
    it and ends the chamfer face on the wall planes y = +-5; OCCT left a face of zero width (two
    distances), or built a valid result removing ten times as much (equal distance)."""

    def slot(self, seam):
        V = FreeCAD.Vector
        block = Part.makeBox(30, 30, 20, V(0, -15, 0))
        tunnel = Part.makeCylinder(5, 32, V(-1, 0, 10), V(1, 0, 0))
        # turn the tunnel about its axis until its seam (a line edge) lies along `seam`
        line = [e for e in tunnel.Edges if e.Curve.TypeId == "Part::GeomLine"][0]
        p = line.Vertexes[0].Point
        now = V(0, p.y, p.z - 10)
        angle = math.degrees(math.atan2(now.cross(seam).x, now.dot(seam)))
        tunnel.rotate(V(0, 0, 10), V(1, 0, 0), angle)
        shape = block.cut(tunnel).cut(Part.makeBox(16, 10, 11, V(15, -5, 10)))
        rim = [
            e
            for e in shape.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.BoundBox.XMin - 15) < 1e-7
            and abs(e.BoundBox.XMax - 15) < 1e-7
            and e.BoundBox.ZMin > 10 - 1e-7
        ]
        return shape, rim

    def testChamfersAsOnshape(self):
        V = FreeCAD.Vector
        # the seam below the rim, on its top (the rim in two pieces), and on the cusp (as in Case Base)
        for seam in (V(0, 0, -1), V(0, 0, 1), V(0, 1, 0)):
            shape, rim = self.slot(seam)
            for wall, tunnel in ((1, 1), (1, 3), (3, 1)):
                with self.subTest(seam=tuple(seam), wall=wall, tunnel=tunnel):
                    if wall == tunnel:
                        result = shape.makeChamfer(wall, rim)
                    else:
                        # The first distance is on the edge's first face, here the tunnel
                        first = shape.ancestorsOfType(rim[0], Part.Face)[0]
                        on_tunnel = first.Surface.TypeId == "Part::GeomCylinder"
                        result = shape.makeChamfer(
                            tunnel if on_tunnel else wall, wall if on_tunnel else tunnel, rim
                        )
                    self.assertTrue(result.isValid())
                    expected = cusped_chamfer_volume(5, wall, tunnel)
                    self.assertAlmostEqual(shape.Volume - result.Volume, expected, delta=1e-6 * expected)
                    self.assertEqual(len(result.Faces), len(shape.Faces) + len(rim))

    def testStripEndingOnAnElbow(self):
        """Case Base #76 as built: the tunnel ends 3 behind the end wall in an elbow turning up, and
        the 3 along the tunnel ends exactly on the tangent edge into it. The elbow only gains the
        cusps' vertices on that edge; the chamfer is CU1's (Onshape's on the replica's own body)"""
        V = FreeCAD.Vector
        block = Part.makeBox(30, 30, 20, V(0, -15, 0))
        tunnel = Part.makeCylinder(5, 19, V(12, 0, 10), V(1, 0, 0))
        disc = Part.Face(Part.Wire(Part.makeCircle(5, V(12, 0, 10), V(1, 0, 0))))
        elbow = disc.revolve(V(12, 0, 18), V(0, 1, 0), 90)
        riser = Part.makeCylinder(5, 3, V(4, 0, 18), V(0, 0, 1))
        shape = block.cut(tunnel).cut(elbow).cut(riser).cut(Part.makeBox(16, 10, 11, V(15, -5, 10)))
        shape = shape.removeSplitter()
        self.assertTrue(shape.isValid())
        rim = [
            e
            for e in shape.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.BoundBox.XMin - 15) < 1e-7
            and abs(e.BoundBox.XMax - 15) < 1e-7
            and e.BoundBox.ZMin > 10 - 1e-7
        ]
        self.assertTrue(rim)
        first = shape.ancestorsOfType(rim[0], Part.Face)[0]
        on_tunnel = first.Surface.TypeId == "Part::GeomCylinder"
        result = shape.makeChamfer(3 if on_tunnel else 1, 1 if on_tunnel else 3, rim)
        self.assertTrue(result.isValid())
        expected = cusped_chamfer_volume(5, 1, 3)
        self.assertAlmostEqual(shape.Volume - result.Volume, expected, delta=1e-6 * expected)
        self.assertEqual(len(result.Faces), len(shape.Faces) + len(rim))

class CuspRefusalTest(unittest.TestCase):
    """Kernel layer step 1 (notes/kernel-layer.md P5, ops#640): a chamfer whose edge ends in a cusp is
    the exact construction's or an error that names the edge. OCCT's result, valid or not, is never
    kept where the construction refuses (Sean's ruling of 11-13: build like Onshape, else refuse
    loudly); it was, with no warning at all (Case Base #76)."""

    def slotWithACone(self):
        """CuspTest's slot with a cone frustum (r 3 to 2, 4 high) standing on the block's top away
        from the slot. Returns the body, the cusped rim and the frustum's top circle: an edge on a
        cone, which the construction refuses and OCCT chamfers (5.326054 removed at 1, alone)."""
        slot, _ = CuspTest().slot(V(0, 0, -1))
        shape = slot.fuse(Part.makeCone(3, 2, 4, V(6, 10, 20))).removeSplitter()
        circles = [e for e in shape.Edges if e.Curve.TypeId == "Part::GeomCircle"]
        rim = [
            e
            for e in circles
            if abs(e.BoundBox.XMin - 15) < 1e-7
            and abs(e.BoundBox.XMax - 15) < 1e-7
            and e.BoundBox.ZMin > 10 - 1e-7
        ]
        top = [e for e in circles if abs(e.BoundBox.ZMin - 24) < 1e-7]
        self.assertEqual((len(rim), len(top)), (1, 1))
        return shape, rim, top

    def testAChamferTheConstructionRefusesRaisesNamingTheEdge(self):
        # The rim and the cone's edge in one chamfer of 1: the construction refuses the selection
        # for the cone, and OCCT built both, valid, taking 45.885194 at the rim where the cusped
        # section is 6.608946. makeChamfer returned that; now the error names the rim, not the cone
        shape, rim, top = self.slotWithACone()
        alone = shape.makeChamfer(1, top)
        self.assertTrue(alone.isValid())
        self.assertAlmostEqual(shape.Volume - alone.Volume, 5.326054, delta=1e-4)
        name = "Edge%d" % next(i for i, e in enumerate(shape.Edges, 1) if e.isSame(rim[0]))
        with self.assertRaises(Exception) as caught:
            shape.makeChamfer(1, rim + top)
        message = str(caught.exception)
        self.assertIn("The chamfer of %s ends in a cusp" % name, message)
        self.assertIn("exact construction refused", message)

    def testTheFeatureFailsWithTheSameError(self):
        shape, rim, top = self.slotWithACone()
        doc = FreeCAD.newDocument("CuspRefusalTest")
        try:
            base = doc.addObject("Part::Feature", "Base")
            base.Shape = shape
            chamfer = doc.addObject("Part::Chamfer", "Chamfer")
            chamfer.Base = base
            picked = [
                next(i for i, e in enumerate(shape.Edges, 1) if e.isSame(edge)) for edge in rim + top
            ]
            chamfer.Edges = [(i, 1, 1) for i in picked]
            doc.recompute()
            self.assertFalse(chamfer.isValid())
            self.assertIn("ends in a cusp", chamfer.getStatusString())
        finally:
            FreeCAD.closeDocument(doc.Name)

    def testChamfersPastTheTopAreCutOffByIt(self):
        # The slot alone, 6 on both faces: the strip on the end wall runs past the block's top (10
        # above the tunnel's axis) and is cut off by it. The cusped section's integral, over the
        # wall's part below the top (the midpoint rule on 2000 x 400 cells, good to 1e-4)
        shape, rim = CuspTest().slot(V(0, 0, -1))
        r, a, top, n, m = 5.0, 6.0, 10.0, 2000, 400
        expected = 0.0
        for i in range(n):
            y = -r + (i + 0.5) * 2 * r / n
            z0 = math.sqrt(r * r - y * y)
            z1 = min(math.sqrt((r + a) ** 2 - y * y), top)
            for j in range(m):
                z = z0 + (j + 0.5) * (z1 - z0) / m
                expected += (r + a - math.hypot(y, z)) * (z1 - z0) / m * 2 * r / n
        result = shape.makeChamfer(6, rim)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(shape.Volume - result.Volume, expected, delta=1e-3)

    def testChamfersTheConstructionBuildsStay(self):
        # The control: within the wall the construction builds them, exact (CuspTest's values)
        shape, rim = CuspTest().slot(V(0, 0, -1))
        for size in (1, 4, 4.9):
            with self.subTest(size=size):
                result = shape.makeChamfer(size, rim)
                self.assertTrue(result.isValid())
                expected = cusped_chamfer_volume(5, size, size)
                self.assertAlmostEqual(shape.Volume - result.Volume, expected, delta=1e-6 * expected)
                self.assertEqual(len(result.Faces), len(shape.Faces) + 1)


class VolumeSignTest(unittest.TestCase):
    """The dress-up's volume-sign post-condition (kernel layer, ops#762): a round or chamfer of convex
    edges only removes material. OCCT's round of a regular 100-gon prism's top rim (sides 2, r 0.2)
    passes isValid() with every round face untrimmed at the 3.6 degree corners, and adds 5.39 mm3
    where 1.714 is removed; makeFillet returned it. Now it is built right or refused."""

    @staticmethod
    def prism(n, side=2.0, height=3.0):
        radius = side / (2 * math.sin(math.pi / n))
        points = [
            V(radius * math.cos(2 * math.pi * k / n), radius * math.sin(2 * math.pi * k / n), 0)
            for k in range(n)
        ]
        shape = Part.Face(Part.makePolygon(points + points[:1])).extrude(V(0, 0, height))
        rim = [e for e in shape.Edges if abs(e.BoundBox.ZMin - height) < 1e-9]
        return shape, rim

    @staticmethod
    def removed(n, r, side=2.0):
        """The rim's round of a regular n-gon prism: at the depth h below the top the section is the
        polygon offset inward by d = r - sqrt(r^2 - (r - h)^2), its area A - P d + n tan(pi/n) d^2
        (the rounds meet in mitres over the corners). Integrated over h in [0, r]."""
        return n * side * r * r * (1 - math.pi / 4) - n * math.tan(math.pi / n) * r**3 * (
            5 / 3 - math.pi / 2
        )

    def testARimOfFiftySidesIsOcctsAndRight(self):
        shape, rim = self.prism(50)
        self.assertEqual(len(rim), 50)
        result = shape.makeFillet(0.2, rim)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(shape.Volume - result.Volume, self.removed(50, 0.2), delta=1e-5)

    def testARimOfAHundredSidesIsRightOrRefused(self):
        shape, rim = self.prism(100)
        self.assertEqual(len(rim), 100)
        self.assertAlmostEqual(self.removed(100, 0.2), 1.714405, delta=1e-6)
        try:
            result = shape.makeFillet(0.2, rim)
        except Exception as e:
            self.assertIn("adds material", str(e))
            self.assertIn("where a dress-up of convex edges only removes it", str(e))
            return
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(shape.Volume - result.Volume, self.removed(100, 0.2), delta=1e-5)

    def testTheFeatureIsRightOrFailsToo(self):
        shape, rim = self.prism(100)
        doc = FreeCAD.newDocument("VolumeSignTest")
        try:
            base = doc.addObject("Part::Feature", "Base")
            base.Shape = shape
            fillet = doc.addObject("Part::Fillet", "Fillet")
            fillet.Base = base
            fillet.Edges = [
                (i, 0.2, 0.2) for i, e in enumerate(shape.Edges, 1) if any(e.isSame(x) for x in rim)
            ]
            doc.recompute()
            if fillet.isValid():
                removed = shape.Volume - fillet.Shape.Volume
                self.assertAlmostEqual(removed, self.removed(100, 0.2), delta=1e-5)
            else:
                self.assertIn("adds material", fillet.getStatusString())
        finally:
            FreeCAD.closeDocument(doc.Name)

    def testConcaveEdgesAddAndConvexRemove(self):
        # Controls: the sign rule passes OCCT's ordinary results both ways
        box = Part.makeBox(10, 10, 10)
        edge = edge_between(box, (0, 0, 10), (10, 0, 10))
        self.assertAlmostEqual(
            box.Volume - box.makeFillet(1, [edge]).Volume, fillet_section(1) * 10, delta=1e-6
        )
        step = box.cut(Part.makeBox(10, 5, 5, V(0, 0, 5)))
        inner = edge_between(step, (0, 5, 5), (10, 5, 5))
        self.assertAlmostEqual(
            step.makeFillet(1, [inner]).Volume - step.Volume, fillet_section(1) * 10, delta=1e-6
        )
        self.assertAlmostEqual(step.makeChamfer(1, [inner]).Volume - step.Volume, 5, delta=1e-6)


def tight_plate(radii, scoop=False):
    """A 30 x 20 x 5 plate whose four vertical corners are rounded radii, at (0, 0), (30, 0),
    (30, 20) and (0, 20). With scoop, a vertical cylinder R 7.5 about (27, 3) is cut out first,
    and radii[1] rounds its two edges against the walls."""
    box = Part.makeBox(30, 20, 5)
    if scoop:
        box = box.cut(Part.makeCylinder(7.5, 7, V(27, 3, -1), V(0, 0, 1)))

    def vertical(shape):
        return [
            e
            for e in shape.Edges
            if abs(e.BoundBox.ZLength - 5) < 1e-9
            and e.BoundBox.XLength < 1e-9
            and e.BoundBox.YLength < 1e-9
        ]

    shape = box
    for (x, y), radius in zip(((0, 0), (30, 0), (30, 20), (0, 20)), radii):
        if scoop and (x, y) == (30, 0):
            edges = [
                e
                for e in vertical(shape)
                if (abs(e.BoundBox.YMin) < 1e-6 and 1 < e.BoundBox.XMin < 29)
                or (abs(e.BoundBox.XMin - 30) < 1e-6 and 1 < e.BoundBox.YMin < 19)
            ]
        else:
            edges = [
                e
                for e in vertical(shape)
                if abs(e.BoundBox.XMin - x) < 1e-6 and abs(e.BoundBox.YMin - y) < 1e-6
            ]
        shape = shape.makeFillet(radius, edges)
    return shape


class TightWallArcTest(unittest.TestCase):
    """The top rim's round r = 1.5 of a plate whose wall arc rho is below r (ops#640, C4 shape A,
    notes/fillet-tight-arc.md): no ball of radius r fits the arc, and Onshape's corner is the canal
    surface of a ball of radius rho whose centre keeps the same depth from both neighbouring walls,
    rising from the wall arc at depth r to the apex on the top, where the neighbours' rounds' top
    edges cross. OCCT's own result is valid but wrong there. Expected values: Onshape's (oracle 17,
    Q-TIGHT TA1-TA3: volume, area, faces, the corner face's area); the wall arc stays a circle."""

    def round(self, base, r=1.5):
        top = [
            e
            for e in base.Edges
            if abs(e.BoundBox.ZMin - 5) < 1e-9 and abs(e.BoundBox.ZMax - 5) < 1e-9
        ]
        return base.makeFillet(r, top)

    def check(self, shape, onshape, apexes, arcs, r=1.5, rho=1.0):
        volume, area, faces, cornerArea = onshape
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume, volume, delta=1e-3)
        self.assertAlmostEqual(shape.Area, area, delta=1e-3)
        refined = shape.removeSplitter()
        self.assertEqual(len(refined.Faces), faces)
        free = [
            f.Area
            for f in refined.Faces
            if f.Surface.TypeId
            not in ("Part::GeomPlane", "Part::GeomCylinder", "Part::GeomToroid", "Part::GeomSurfaceOfRevolution")
        ]
        self.assertEqual(len(free), len(apexes))
        for a in free:
            self.assertAlmostEqual(a, cornerArea, delta=1e-4)
        for apex in apexes:
            self.assertLess(min((v.Point - apex).Length for v in shape.Vertexes), 1e-6)
        def wallArc(edge, centre):
            try:
                curve = edge.Curve
            except TypeError:  # a curve type without a Python wrapper: not a circle
                return False
            return (
                curve.TypeId == "Part::GeomCircle"
                and abs(curve.Radius - rho) < 1e-9
                and abs(edge.BoundBox.ZMin - (5 - r)) < 1e-9
                and abs(edge.BoundBox.ZMax - (5 - r)) < 1e-9
                and (V(curve.Center.x, curve.Center.y, 0) - centre).Length < 1e-9
            )

        for centre in arcs:
            # The wall arc at depth r survives whole, a circle
            self.assertTrue(any(wallArc(e, centre) for e in shape.Edges))

    def testWallArcBelowTheRound(self):
        # TA1 (rho 1) and TA2 (rho 0.5): the neighbours are the plate's straight walls
        for rho, onshape in (
            (1.0, (2902.820914, 1589.230881, 18, 2.435593)),
            (0.5, (2903.543273, 1590.464844, 18, 1.257495)),
        ):
            with self.subTest(rho=rho):
                shape = self.round(tight_plate([4.0, rho, 4.0, 4.0]))
                apex = V(30 - 1.5, 1.5, 5)
                self.check(shape, onshape, [apex], [V(30 - rho, rho, 0)], rho=rho)

    def testWallArcsBetweenAScoopAndAWall(self):
        # TA3: a concave scoop R 7.5 about (27, 3) between the walls, joined to each by an arc
        # rho 1; the arcs' centres at 1 from the wall and 8.5 from the scoop's axis
        shape = self.round(tight_plate([4.0, 1.0, 4.0, 4.0], scoop=True))
        s = math.sqrt(8.5**2 - 2**2)
        centres = [V(29, 3 + s, 0), V(27 - s, 1, 0)]
        # The apexes at 1.5 from the wall and 9 from the scoop's axis
        t = math.sqrt(9**2 - 1.5**2)
        apexes = [V(28.5, 3 + t, 5), V(27 - t, 1.5, 5)]
        self.check(shape, (2416.468426, 1380.349941, 22, 2.821144), apexes, centres)

    def scalloped(self, hole):
        """A plate 60 x 40 x 6: two opposite corners rounded 5, the other two scalloped by a
        concave cylinder R 8 about the corner's edge, joined to both walls by arcs rho 1: four wall
        arcs tighter than the round 1.5875, each between a plane and the scoop. With hole, a
        through hole R 4 that touches both straight top edges of the round beside a rounded corner
        (the lid's hole). Returns the plate, its top rim (without the hole's) and the round."""
        lx, ly, top, big, scoop, rho, r = 60.0, 40.0, 6.0, 5.0, 8.0, 1.0, 1.5875
        k = math.sqrt((scoop + rho) ** 2 - rho**2)
        a = math.degrees(math.atan2(rho, k))

        def arc(cx, cy, radius, a0, a1):
            circle = Part.Circle(V(cx, cy, 0), V(0, 0, 1), radius)
            return Part.ArcOfCircle(circle, math.radians(a0), math.radians(a1)).toShape()

        def half():
            return [
                Part.makeLine(V(big, 0, 0), V(lx - k, 0, 0)),
                arc(lx - k, rho, rho, -90, -a),
                arc(lx, 0, scoop, 90 + a, 180 - a),
                arc(lx - rho, k, rho, -(90 - a), 0),
                Part.makeLine(V(lx, k, 0), V(lx, ly - big, 0)),
                arc(lx - big, ly - big, big, 0, 90),
            ]

        other = half()
        for e in other:
            e.rotate(V(lx / 2, ly / 2, 0), V(0, 0, 1), 180)
        plate = Part.Face(Part.Wire(Part.__sortEdges__(half() + other))).extrude(V(0, 0, top))
        if hole:
            centre = V(lx - r - 4, ly - r - 4, -1)
            plate = plate.cut(Part.makeCylinder(4, top + 2, centre, V(0, 0, 1)))
        rim = [
            e
            for e in plate.Edges
            if abs(e.BoundBox.ZMin - top) < 1e-9
            and abs(e.BoundBox.ZMax - top) < 1e-9
            and not (abs(e.BoundBox.XLength - 8) < 1e-6 and abs(e.BoundBox.YLength - 8) < 1e-6)
        ]
        return plate, rim, r

    def testFourWallArcsOnOneRim(self):
        # Case Lid #121's rim, designed (probes/c4/rim_four.py): the whole top rim of the scalloped
        # plate, 12 edges with four tight wall arcs. A whole loop on a plane face with walls square
        # to it is assembled directly (notes/boolean-free-mitre.md): each tight arc's face is the
        # canal patch, its sides the neighbouring rounds' ends, and the neighbours' top edges cross
        # in one vertex, at r from the wall and 8 + r from the scoop's axis. One face per rim
        # edge; the four patches are equal by the model's symmetries. The patch's area and the
        # volume have no closed form: they are the construction by Booleans' on the same model
        # (lx6 adf71674be, where it took 60 s), whose patches lie on the canal surface to 2e-14.
        # With the hole, its rim touches two top edges: the top plane comes out in two faces, as
        # in Onshape, the smaller between the hole and the corner's top edges:
        # 4^2 - 4 pi - (5 - r)^2 (1 - pi/4)
        for hole, volume in ((False, 13627.9151), (True, 13326.3222)):
            with self.subTest(hole=hole):
                plate, rim, r = self.scalloped(hole)
                self.assertEqual(len(rim), 12)
                result = plate.makeFillet(r, rim)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                self.assertEqual(len(result.Faces), len(plate.Faces) + 12 + (1 if hole else 0))
                analytic = ("Part::GeomPlane", "Part::GeomCylinder", "Part::GeomToroid")
                free = [f for f in result.Faces if f.Surface.TypeId not in analytic]
                self.assertEqual(len(free), 4)
                for f in free:
                    self.assertEqual(f.Surface.TypeId, "Part::GeomBSplineSurface")
                    self.assertAlmostEqual(f.Area, 2.364206, delta=1e-5)
                self.assertAlmostEqual(result.Volume, volume, delta=1e-3)
                t = math.sqrt((8 + r) ** 2 - r**2)
                for apex in (V(60 - t, r, 6), V(60 - r, t, 6), V(t, 40 - r, 6), V(r, 40 - t, 6)):
                    self.assertLess(min((v.Point - apex).Length for v in result.Vertexes), 1e-6)
                tops = [
                    f
                    for f in result.Faces
                    if f.Surface.TypeId == "Part::GeomPlane"
                    and abs(f.BoundBox.ZMin - 6) < 1e-9
                    and abs(f.BoundBox.ZMax - 6) < 1e-9
                ]
                self.assertEqual(len(tops), 2 if hole else 1)
                if hole:
                    island = 16 - 4 * math.pi - (5 - r) ** 2 * (1 - math.pi / 4)
                    self.assertAlmostEqual(min(f.Area for f in tops), island, delta=1e-6)

    def testAHoleCrossingTheTopEdgeIsNotBuiltDirectly(self):
        # The same plate with the hole 0.5 further out: its rim crosses the round's top edges, so
        # the hole's wall cuts into the round. That is not the direct assembly's case (it refuses,
        # and the construction by Booleans or OCCT answers): whatever is returned is valid and
        # removes material from the plate, and nothing is pinched off the top
        plate, rim, r = self.scalloped(False)
        centre = V(60 - r - 4 + 0.5, 40 - r - 4 + 0.5, -1)
        plate = plate.cut(Part.makeCylinder(4, 8, centre, V(0, 0, 1)))
        rim = [
            e
            for e in plate.Edges
            if abs(e.BoundBox.ZMin - 6) < 1e-9
            and abs(e.BoundBox.ZMax - 6) < 1e-9
            and not (abs(e.BoundBox.XLength - 8) < 1e-6 and abs(e.BoundBox.YLength - 8) < 1e-6)
        ]
        self.assertEqual(len(rim), 12)
        try:
            result = plate.makeFillet(r, rim)
        except Part.OCCError:
            return
        self.assertTrue(result.isValid())
        self.assertLess(result.Volume, plate.Volume)

    def testAHoleInAReflexCornersRunOnIsNotBuiltDirectly(self):
        # An L-plate 60 x 40 x 6 (the notch x > 30, y > 20) with one wall arc rho 1 tighter than
        # the round r 1.5875, and a through hole R 0.5 inside the reflex corner's run-on: the
        # rounds of the walls x = 30 and y = 20 run on past the corner to where their top edges
        # cross, at r from both, and the hole touches both top edges from the rounds' side. Its
        # wall cuts through both rounds, which is not the direct assembly's case (a body built as
        # if the hole only pinched the top plane was valid and wrong). At depths d1, d2 behind
        # the two walls the rounds take min(h(d1), h(d2)) off the top, h(d) = r - sqrt(r^2 -
        # (r - d)^2): the plate with the hole loses that much less than the plate without it,
        # integrated over the hole's circle
        r, hole = 1.5875, 0.5

        def removed(withHole):
            plate = self.ell()
            if withHole:
                centre = V(30 - r + hole, 20 - r + hole, -1)
                cylinder = Part.makeCylinder(hole, 8, centre, V(0, 0, 1))
                # The hole's seam turned away from the top edges it touches
                cylinder.rotate(V(centre.x, centre.y, 0), V(0, 0, 1), 200)
                plate = plate.cut(cylinder)
            rim = [
                e
                for e in plate.Edges
                if abs(e.BoundBox.ZMin - 6) < 1e-9
                and abs(e.BoundBox.ZMax - 6) < 1e-9
                and not e.isClosed()  # the hole's rim
            ]
            self.assertEqual(len(rim), 7)
            result = plate.makeFillet(r, rim)
            self.assertTrue(result.isValid())
            self.assertEqual(len(result.Solids), 1)
            return plate.Volume - result.Volume

        def height(d):
            return r - math.sqrt(r * r - (r - d) ** 2) if d < r else 0.0

        inHole, rings, spokes = 0.0, 200, 400
        for i in range(rings):
            rho = hole * (i + 0.5) / rings
            for j in range(spokes):
                phi = 2 * math.pi * (j + 0.5) / spokes
                d1 = r - hole + rho * math.cos(phi)
                d2 = r - hole + rho * math.sin(phi)
                inHole += min(height(d1), height(d2)) * rho
        inHole *= (hole / rings) * (2 * math.pi / spokes)
        self.assertAlmostEqual(inHole, 0.041565, delta=2e-6)
        self.assertAlmostEqual(removed(False) - removed(True), inHole, delta=1e-4)

    def testABodyPartUnderTheRimIsNotBuiltThrough(self):
        # The same L-plate, hollowed from below 0.2 r from the wall y = 0 and from the top: (a) a
        # cavity 40 long, (b) a blind hole R 1. The hollow's top corner lies inside what the round
        # removes (anything nearer than r (1 - 1/sqrt 2) to both the wall and the top does), so
        # the round opens into it: the body loses less than the plain plate does, by the heights
        # above the hollow's top, h(d) - t for d from t to 0.4 r (where the round is t deep),
        # times the hollow's width there (1.82489 for the cavity, 0.036437 for the hole). The
        # direct assembly knows the plane face and the walls only: it built the round through
        # the hollow, valid and with the plain plate's volume. Now it refuses (another face
        # within r of the rim); the construction by Booleans refuses too, and OCCT's own round,
        # which runs through the hollow as well, is not returned: an error that names the cause
        r, top = 1.5875, 6.0
        t = 0.2 * r
        rim = lambda body: [
            e for e in body.Edges if abs(e.BoundBox.ZMin - top) < 1e-9 and abs(e.BoundBox.ZMax - top) < 1e-9
        ]
        plain = self.ell()
        self.assertTrue(plain.makeFillet(r, rim(plain)).isValid())
        self.assertLess(t, r * (1 - math.sqrt(0.5)))
        cavity = Part.makeBox(40, 10 - t, top - t + 1, V(10, t, -1))
        hole = Part.makeCylinder(1.0, top - t + 1, V(20, t + 1.0, -1), V(0, 0, 1))
        for name, tool in (("cavity", cavity), ("hole", hole)):
            with self.subTest(hollow=name):
                body = plain.cut(tool)
                self.assertEqual(len(rim(body)), 7)
                with self.assertRaisesRegex(FreeCAD.Base.CADKernelError, "a part of the body under its rim"):
                    body.makeFillet(r, rim(body))

    def ell(self):
        """An L-plate 60 x 40 x 6 (the notch x > 30, y > 20) with one wall arc rho 1 at (59, 19)."""
        circle = Part.Circle(V(59, 19, 0), V(0, 0, 1), 1.0)
        outline = [
            Part.makeLine(V(0, 0, 0), V(60, 0, 0)),
            Part.makeLine(V(60, 0, 0), V(60, 19, 0)),
            Part.ArcOfCircle(circle, 0, math.pi / 2).toShape(),
            Part.makeLine(V(59, 20, 0), V(30, 20, 0)),
            Part.makeLine(V(30, 20, 0), V(30, 40, 0)),
            Part.makeLine(V(30, 40, 0), V(0, 40, 0)),
            Part.makeLine(V(0, 40, 0), V(0, 0, 0)),
        ]
        return Part.Face(Part.Wire(outline)).extrude(V(0, 0, 6))


class CurvedEndTrimTest(unittest.TestCase):
    """Case Base #105, designed (notes r105-curved-end-trim): a block x -10..10, y 0..8, z 0..5 with
    a notch below z = 4, open at the front and the bottom, under a lip 1 tall. The lip's front-bottom
    chord (y 0, z 4, x -4..4) is rounded with r 1, the lip's height: the round is at its limit. The
    notch's wall meets the front at the chord's ends, the underside coming to a spike of 53.13 deg,
    narrower than r near the ends: the wall's surface cuts the round off there, as Onshape's #105
    ("cut off by #103's blend"), and grows by the round's section where it passes. The wall is the
    cylinder x^2 + (y + 3)^2 = 25, analytic or as a B-spline surface (as #105's end face); the control
    is two slanted planes with the same spike.

    In the section (y, z - 4) the round removes the corner of the unit square outside the circle about
    (1, 1), h(y) = 1 - sqrt(1 - (1 - y)^2) tall, kept where y < s(x), the underside's depth:
    dV = -int A(min(s, 1)) dx, A(w) = w - pi/4 + ((1 - w) sqrt(1 - (1 - w)^2) + asin(1 - w)) / 2;
    dA = blend int min(acos(1 - s), pi/2) dx - front band 8 - underside int min(s, 1) dx + the wall's
    growth int h(y) ds along the wall; faces +2 (the blend, and the front face split in two)."""

    rho, d = 5.0, 3.0

    def body(self, wall):
        rho, d = self.rho, self.d
        block = Part.makeBox(20, 8, 5, V(-10, 0, 0))
        if wall == "plane":
            c = math.sqrt(rho * rho - d * d)
            top = c * math.tan(math.acos(d / rho))
            w = Part.makePolygon([V(-c, 0, -1), V(c, 0, -1), V(0, top, -1), V(-c, 0, -1)])
            notch = Part.Face(w).extrude(V(0, 0, 5))
            notch = notch.fuse(Part.makeBox(2 * c, 1, 5, V(-c, -1, -1))).removeSplitter()
        else:
            # the seam turned out of the block (to -y)
            notch = Part.makeCylinder(rho, 7 if wall == "bsp" else 5, V(0, -d, -1))
            notch.rotate(V(0, -d, 0), V(0, 0, 1), -90)
            if wall == "bsp":
                # a B-spline surface whose domain runs on past the lip
                notch = notch.toNurbs().common(Part.makeBox(4 * rho, 4 * rho, 6, V(-2 * rho, -d - 2 * rho, -2)))
        body = block.cut(notch).removeSplitter()
        chord = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomLine"
            and all(abs(v.Point.y) < 1e-9 and abs(v.Point.z - 4) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(chord), 1)
        return body, chord[0]

    def depth(self, wall, x):
        rho, d = self.rho, self.d
        if wall == "plane":
            c = math.sqrt(rho * rho - d * d)
            return (c - abs(x)) * math.tan(math.acos(d / rho))
        return -d + math.sqrt(max(rho * rho - x * x, 0.0))

    def expected(self, wall):
        rho, d = self.rho, self.d
        c = math.sqrt(rho * rho - d * d)
        alpha = math.acos(d / rho)
        x1 = math.sqrt(rho * rho - (1 + d) ** 2) if wall != "plane" else c - 1 / math.tan(alpha)

        def h(y):
            return 1 - math.sqrt(max(1 - (1 - y) ** 2, 0.0))

        def section(w):
            u = 1 - min(max(w, 0.0), 1.0)
            return 1 - u - math.pi / 4 + (u * math.sqrt(max(1 - u * u, 0.0)) + math.asin(u)) / 2

        def graded(f, a, b, at_b=True):
            # the integral over [a, b], graded towards a square root's end point (b, else a)
            total = 0.0
            for k in range(40):
                lo, hi = 1 - 2.0**-k, 1 - 2.0 ** -(k + 1)
                if at_b:
                    total += gauss_legendre(f, a + (b - a) * lo, a + (b - a) * hi)
                else:
                    total += gauss_legendre(f, b - (b - a) * hi, b - (b - a) * lo)
            return total

        def integral(f):
            # smooth pieces, split where s = 1; acos(1 - s) goes as sqrt(s) towards the spikes
            middle = sum(gauss_legendre(f, -x1 + 2 * x1 * k / 8, -x1 + 2 * x1 * (k + 1) / 8) for k in range(8))
            return middle + graded(f, x1, c) + graded(f, -c, -x1, at_b=False)

        s = lambda x: self.depth(wall, x)
        dV = -integral(lambda x: section(s(x)))
        blend = integral(lambda x: min(math.acos(max(1 - s(x), -1.0)), math.pi / 2))
        under = -integral(lambda x: min(s(x), 1.0))
        # h goes as sqrt(y) at y = 0, where the wall meets the front
        if wall == "plane":
            grown = 2 * graded(h, 0.0, 1.0, at_b=False) / math.sin(alpha)
        else:
            f0, f1 = math.acos((1 + d) / rho), alpha
            grown = 2 * rho * graded(lambda f: h(-d + rho * math.cos(f)), f0, f1)
        return dV, blend - 2 * c + under + grown

    def testRoundCutOffByTheEndFacesSurface(self):
        # closed forms (notes r105-curved-end-trim): cylinder -1.636982 / -2.985847, plane -1.644912 / -3.003319
        known = {"cyl": (-1.636982, -2.985847), "plane": (-1.644912, -3.003319)}
        for wall in ("cyl", "bsp", "plane"):
            with self.subTest(wall=wall):
                body, chord = self.body(wall)
                dV, dA = self.expected(wall)
                self.assertAlmostEqual(dV, known["plane" if wall == "plane" else "cyl"][0], delta=1e-6)
                self.assertAlmostEqual(dA, known["plane" if wall == "plane" else "cyl"][1], delta=1e-6)
                shape = body.makeFillet(1.0, [chord])
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(shape.Volume - body.Volume, dV, delta=1e-5)
                self.assertAlmostEqual(shape.Area - body.Area, dA, delta=1e-5)
                self.assertEqual(len(shape.Faces), len(body.Faces) + 2)

    def testAnEndWallTangentToTheEdge(self):
        # Case Base #105 on the fork's own body (ops#640): the end blend runs out tangent to the lip's side,
        # so at the round's end the end face's normal is square to the edge (refused: "an end face that is
        # not a plane, tangent to the edge"; Onshape's STEP body passed that test on its noise, 1.8e-6).
        # The notch's wall here leaves the front tangentially at both ends of the chord: arcs R 3 about
        # (+-4, 3) from (+-4, 0) to (+-1, 3), joined by a half circle R 1 about (0, 3). The underside's depth
        # is s = 3 - sqrt(9 - t^2) at t = 4 - |x| from the end (a cusp of angle 0), 1 at t = sqrt(5). The
        # class's closed form with that s; on the arcs x = 4 - 3 sin(f), the wall's arc length 3 df
        block = Part.makeBox(20, 8, 5, V(-10, 0, 0))

        def arc(centre, r, a0, a1):
            circle = Part.Circle(V(centre[0], centre[1], -1), V(0, 0, 1), r)
            return Part.ArcOfCircle(circle, math.radians(a0), math.radians(a1)).toShape()

        corners = [V(4, 0, -1), V(4, -1, -1), V(-4, -1, -1), V(-4, 0, -1)]
        edges = [arc((4, 3), 3, 180, 270), arc((0, 3), 1, 0, 180), arc((-4, 3), 3, 270, 360)]
        edges += [Part.makeLine(a, b) for a, b in zip(corners, corners[1:])]
        notch = Part.Face(Part.Wire(Part.__sortEdges__(edges))).extrude(V(0, 0, 5))
        body = block.cut(notch).removeSplitter()
        chord = [
            e
            for e in body.Edges
            if e.Length > 7.9 and all(abs(v.Point.y) < 1e-9 and abs(v.Point.z - 4) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(chord), 1)

        def h(y):
            return 1 - math.sqrt(max(1 - (1 - y) ** 2, 0.0))

        def section(w):
            u = 1 - min(max(w, 0.0), 1.0)
            return 1 - u - math.pi / 4 + (u * math.sqrt(max(1 - u * u, 0.0)) + math.asin(u)) / 2

        def s(x):
            t = 4 - abs(x)
            return 3 - math.sqrt(9 - t * t)

        f1 = math.acos(2 / 3)  # where s = 1
        x1 = 4 - 3 * math.sin(f1)

        def pieces(g):
            return sum(gauss_legendre(g, f1 * k / 16, f1 * (k + 1) / 16) for k in range(16))

        def ends(g):
            # both ends' parts, where s < 1
            return 2 * pieces(lambda f: g(4 - 3 * math.sin(f)) * 3 * math.cos(f))

        dV = -(ends(lambda x: section(s(x))) + 2 * x1 * section(1.0))
        blend = ends(lambda x: math.acos(1 - s(x))) + 2 * x1 * math.pi / 2
        under = -(ends(s) + 2 * x1)
        grown = 2 * 3 * pieces(lambda f: h(3 * (1 - math.cos(f))))
        dA = blend - 8 + under + grown
        self.assertAlmostEqual(dV, -1.280342, delta=1e-6)
        self.assertAlmostEqual(dA, -2.277730, delta=1e-6)
        shape = body.makeFillet(1.0, chord)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        self.assertAlmostEqual(shape.Volume - body.Volume, dV, delta=1e-5)
        self.assertAlmostEqual(shape.Area - body.Area, dA, delta=1e-5)
        self.assertEqual(len(shape.Faces), len(body.Faces) + 2)

    def testBelowTheLimitAsOcct(self):
        # Below the limit OCCT builds, and trims at the wall's surface: the fallback isn't asked
        for wall in ("cyl", "bsp"):
            with self.subTest(wall=wall):
                body, chord = self.body(wall)
                shape = body.makeFillet(0.9, [chord])
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Faces), len(body.Faces) + 1)


class BlendEndTrimTest(unittest.TestCase):
    """Case Base #105's ends, designed (notes r105-curved-end-trim): a round at its limit cut off by an
    earlier blend's continuation past the blend's own face.

    A block x -10..10, y 0..8, z 0..4 + h0 with a notch below z = 4 under a lip h0 tall. The notch is
    the ball of radius 5 about (0, -d, 2): its wall is a sphere that meets the front (y = 0) along a
    circle about (0, 0, 2). Those two wall/front edges get an OCCT fillet r_b, which ends at the lip's
    underside and which OCCT stores as a B-spline surface. The blend widens the underside's front edge
    by two stubs that run into the blend tangentially (as #105's 0.74 lines). The lip is then
    thickened to h (a slab fused on top, as a later feature would), and the three edges are rounded
    with r = h, the round's limit: the blend cuts the round off at both ends, above its own face.

    The blend's exact continuation is a torus (the ball rolls on the plane and the sphere): its axis
    goes through the sphere's centre along y, the centres' circle lies in the plane y = r_b with
    radius sqrt((5 + r_b)^2 - (d + r_b)^2), and the minor radius is r_b. Expected, defined
    geometrically: every point of the round's edges on the blend lies on that torus.

    OCCT's own blend surface past its face is the blend only as far as the fillet needed it (about to
    the lip's top as it was then, 2e-6), and then continues the spine straight (7.6e-4 off 0.1
    further, 6.3e-3 off 0.2 further). Cut by that surface, the round of d 1, r_b 1, h 0.6 over h0 0.1
    was built 3.8e-4 off the torus, silently, and the other two cases were refused."""

    rho, zc = 5.0, 2.0

    def torusDeviation(self, p, d, rb):
        major = math.sqrt((self.rho + rb) ** 2 - (d + rb) ** 2)
        return abs(math.hypot(math.hypot(p.x, p.z - self.zc) - major, p.y - rb) - rb)

    def blended(self, d, rb, h, h0):
        block = Part.makeBox(20, 8, 4 + h0, V(-10, 0, 0))
        ball = Part.makeSphere(self.rho, V(0, -d, self.zc))
        notch = ball.common(Part.makeBox(40, 40, 10, V(-20, -20, -6)))  # below z = 4
        body = block.cut(notch).removeSplitter()

        def onFront(e):
            middle = e.valueAt((e.FirstParameter + e.LastParameter) / 2)
            return abs(middle.y) < 1e-7 and all(abs(v.Point.y) < 1e-7 for v in e.Vertexes)

        arcs = [e for e in body.Edges if onFront(e) and e.Curve.TypeId != "Part::GeomLine"]
        self.assertEqual(len(arcs), 2)
        blended = body.makeFillet(rb, arcs)
        self.assertTrue(blended.isValid())
        if h > h0:
            blended = blended.fuse(Part.makeBox(20, 8, h - h0, V(-10, 0, 4 + h0))).removeSplitter()
            self.assertTrue(blended.isValid())
        chain = [
            e
            for e in blended.Edges
            if e.Curve.TypeId == "Part::GeomLine"
            and all(abs(v.Point.y) < 1e-7 and abs(v.Point.z - 4) < 1e-7 for v in e.Vertexes)
        ]
        # the chord and its two stubs; one edge once the slab's refine has merged them
        self.assertEqual(len(chain), 3 if h == h0 else 1)
        return blended, chain

    def check(self, d, rb, h, h0, allowed):
        blended, chain = self.blended(d, rb, h, h0)
        shape = blended.makeFillet(h, chain)
        self.assertTrue(shape.isValid())
        self.assertEqual(len(shape.Solids), 1)
        worst = 0.0
        cut = 0
        for f in shape.Faces:
            s = f.Surface
            if s.TypeId != "Part::GeomCylinder" or abs(s.Radius - h) > 1e-9:
                continue
            for e in f.Edges:
                if e.Curve.TypeId != "Part::GeomBSplineCurve":
                    continue  # the round's own lines and section arcs
                cut += 1
                for k in range(17):
                    p = e.valueAt(e.FirstParameter + (e.LastParameter - e.FirstParameter) * k / 16.0)
                    worst = max(worst, self.torusDeviation(p, d, rb))
        self.assertGreaterEqual(cut, 2)  # a cut edge at each end
        self.assertLess(worst, allowed)
        return shape, blended

    def testARoundWithinTheBlendSurfacesOwnRunOn(self):
        # the lip as tall as when the blend was made: the cut lies where OCCT's surface is still the
        # blend, on the wall's own surface (measured 1e-8; the blend, the front split, two grown walls)
        shape, blended = self.check(3.0, 0.5, 0.1, 0.1, 1e-6)
        self.assertEqual(len(shape.Faces), len(blended.Faces) + 4)

    def testARoundPastTheBlendSurfacesOwnRunOn(self):
        # d, r_b, h, h0. On 17c18a4dc3: the first built 3.8e-4 off (2 new faces), the other two refused
        # ("the surface of an end face that is not a plane leaves 0 pieces beside its edge").
        # Measured 7.5e-7, 2.9e-6, 4.0e-6: the blend's own surface is that far from the torus inside
        # its face. Each end's continuation is one face more than the blend (Onshape: one face).
        # The third blend (4.4e-6 off) is made a rolling ball when it is built (RollingBallBlend,
        # ops#640): its own surface is then the blend past its face too, the round is cut by it and
        # each end is one face, as Onshape's. The other two blends are left as OCCT built them
        for d, rb, h, h0, more in (
            (1.0, 1.0, 0.6, 0.1, 4),
            (0.0, 1.5, 1.0, 0.2, 4),
            (0.0, 1.0, 0.8, 0.2, 2),
        ):
            with self.subTest(d=d, rb=rb, h=h):
                shape, blended = self.check(d, rb, h, h0, 1e-5)
                self.assertEqual(len(shape.Faces), len(blended.Faces) + more)


class RoundOnASplineLidEndingInAHoleTest(unittest.TestCase):
    """A rolling-ball round whose ends lie in a hole (ops#640, the review of the blend's run-on).

    A block x -20..20, y -10..10 under the twisted lid z = 20 + 0.03 x y (a bicubic B-spline), with
    a hole of radius R about the vertical axis through (0, -10): it crosses the edge between the lid
    and the front y = -10 and leaves two edges, each ending on the hole's wall. They are rounded
    with r = 1.5.

    Expected, in closed form: the ball's centre p - r n of every point p of a round lies r from the
    lid (Newton on the graph) and r behind the front. A blend's surface is run on past its end by
    twice its radius where it can; in a hole of radius 4 the ball gets only 2.5 clear of the wall,
    and marched on to the hole's axis the end could not be found: the round was refused where it
    had been built. The run-on now stops where the clearance stops growing."""

    twist, radius = 0.03, 1.5

    def lidDistance(self, a, b, h):
        k = self.twist
        x, y = a, b
        for _ in range(60):
            g = 20 + k * x * y - h
            fx = (x - a) + g * k * y
            fy = (y - b) + g * k * x
            fxx = 1 + k * k * y * y
            fyy = 1 + k * k * x * x
            fxy = g * k + k * k * x * y
            det = fxx * fyy - fxy * fxy
            dx = (fx * fyy - fy * fxy) / det
            dy = (fy * fxx - fx * fxy) / det
            x -= dx
            y -= dy
            if abs(dx) + abs(dy) < 1e-15:
                break
        return math.sqrt((x - a) ** 2 + (y - b) ** 2 + (20 + k * x * y - h) ** 2)

    def rounded(self, hole):
        k = self.twist
        lid = Part.BSplineSurface()
        poles = [
            [V(-45, -25, 20 + k * 45 * 25), V(-45, 25, 20 - k * 45 * 25)],
            [V(45, -25, 20 - k * 45 * 25), V(45, 25, 20 + k * 45 * 25)],
        ]
        lid.buildFromPolesMultsKnots(poles, [2, 2], [2, 2], [0, 1], [0, 1], False, False, 1, 1)
        lid.increaseDegree(3, 3)
        body = Part.makeBox(40, 20, 40, V(-20, -10, 0)).cut(lid.toShape().extrude(V(0, 0, 40)))
        body = body.cut(Part.makeCylinder(hole, 60, V(0, -10, -5)))
        edges = [
            e
            for e in body.Edges
            if len(e.Vertexes) == 2
            and all(abs(v.Point.y + 10) < 1e-7 and v.Point.z > 5 for v in e.Vertexes)
            and abs(e.valueAt((e.FirstParameter + e.LastParameter) / 2).y + 10) < 1e-7
            and abs(e.Vertexes[0].Point.x - e.Vertexes[1].Point.x) > 1e-3
        ]
        self.assertEqual(len(edges), 2)
        return body, body.makeFillet(self.radius, edges)

    def testTheEndsInAHoleAreFound(self):
        # 2.0 (ops#779): the ball gets 0.5 clear, less than two spacings, and the arc passes the
        # hole's axis, where the foot on the far wall read as clear all along the round
        for hole in (2.0, 4.0, 6.0):
            with self.subTest(hole=hole):
                body, shape = self.rounded(hole)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertEqual(len(shape.Faces), len(body.Faces) + 2)
                rounds = [
                    f
                    for f in shape.Faces
                    if f.Surface.TypeId == "Part::GeomBSplineSurface" and f.Area < 100
                ]
                self.assertEqual(len(rounds), 2)
                worst = 0.0
                for f in rounds:
                    u0, u1, v0, v1 = f.ParameterRange
                    for i in range(15):
                        for j in range(15):
                            u = u0 + (u1 - u0) * (i + 0.5) / 15
                            v = v0 + (v1 - v0) * (j + 0.5) / 15
                            p = f.valueAt(u, v)
                            if not f.isInside(p, 1e-7, True):
                                continue
                            c = p - f.normalAt(u, v) * self.radius
                            worst = max(
                                worst,
                                abs(self.lidDistance(c.x, c.y, c.z) - self.radius),
                                abs(c.y + 10 - self.radius),
                            )
                self.assertLess(worst, 1e-6)


class RoundBetweenCylindersTest(unittest.TestCase):
    """A round of a straight edge between two cylinders along it (ops#640, Case Base #104), on two
    cylinders R, height h, axes d apart: fused (two concave edges) and their common part, a lens
    (two convex edges). The exact round is a cylinder of radius r touching both, as Onshape's.
    OCCT's is valid, but a B-spline face between B-spline edges, so a later dress-up over one of
    its ends met "a selected edge that is neither a line nor a circle" (#105): the construction
    runs first. Closed forms: the plane figure between the two circles and the round's arc."""

    R, D = 10.0, 12.0

    def bodies(self, h):
        a = Part.makeCylinder(self.R, h)
        b = Part.makeCylinder(self.R, h, V(self.D, 0, 0))
        return a.fuse(b), a.common(b)

    def straight_edges(self, shape):
        y = math.sqrt(self.R**2 - self.D**2 / 4)
        edges = [
            e
            for e in shape.Edges
            if e.Curve.TypeId == "Part::GeomLine"
            and all(abs(v.Point.x - self.D / 2) < 1e-7 for v in e.Vertexes)
            and all(abs(abs(v.Point.y) - y) < 1e-7 for v in e.Vertexes)
        ]
        self.assertEqual(len(edges), 2)
        return edges

    @staticmethod
    def segment(radius, angle):
        return radius * radius * (angle - math.sin(angle)) / 2

    def concave(self, r):
        """What a round r fills at the concave edge of the fused discs (area); its arc's angle"""
        R, half = self.R, self.D / 2
        py = math.sqrt(R * R - half * half)  # the edge, at (half, py)
        cy = math.sqrt((R + r) ** 2 - half * half)  # the ball's centre, at (half, cy)
        tx, ty = R * half / (R + r), R * cy / (R + r)  # where it touches the disc at the origin
        triangle = (self.D - 2 * tx) * (ty - py) / 2
        on_disc = math.atan2(cy, half) - math.atan2(py, half)
        angle = 2 * math.asin(half / (R + r))
        return triangle - 2 * self.segment(R, on_disc) - self.segment(r, angle), angle

    def convex(self, r):
        """What a round r removes at the convex edge of the lens (area), and its arc's angle"""
        R, half = self.R, self.D / 2
        py = math.sqrt(R * R - half * half)
        cy = math.sqrt((R - r) ** 2 - half * half)
        tx, ty = R * half / (R - r), R * cy / (R - r)  # on the disc at the origin, past x = half
        kite = 2 * (tx - half) * (py - cy) / 2
        on_disc = math.atan2(py, half) - math.atan2(cy, half)
        angle = 2 * math.asin(half / (R - r))
        return kite + 2 * self.segment(R, on_disc) - r * r * angle / 2, angle

    def assertAnalytic(self, shape):
        for face in shape.Faces:
            self.assertNotIn("BSpline", face.Surface.TypeId)
        for edge in shape.Edges:
            self.assertIn(edge.Curve.TypeId, ("Part::GeomLine", "Part::GeomCircle"))

    def testTheRoundIsACylinder(self):
        h, r = 5.0, 2.0
        self.assertAlmostEqual(self.concave(r)[0], 0.269200651, delta=1e-9)
        self.assertAlmostEqual(self.convex(r)[0], 0.812864436, delta=1e-9)
        fused, lens = self.bodies(h)
        for name, base, (section, angle), sign in (
            ("fused", fused, self.concave(r), 1),
            ("lens", lens, self.convex(r), -1),
        ):
            with self.subTest(name):
                result = base.makeFillet(r, self.straight_edges(base))
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                added = result.Volume - base.Volume
                self.assertAlmostEqual(added, sign * 2 * h * section, delta=1e-6)
                self.assertAnalytic(result)
                rounds = [
                    f
                    for f in result.Faces
                    if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - r) < 1e-9
                ]
                self.assertAlmostEqual(sum(f.Area for f in rounds), 2 * h * r * angle, delta=1e-6)

    def testARoundOverItsEndsBuilds(self):
        # #105's kind: the lens h tall with its two edges rounded r, then its top rim rounded h, the
        # wall's whole height. OCCT fails at that limit; the construction takes the rim only if
        # the first rounds' ends are circles. The rim's round removes its section s along the
        # rim, by Pappus s (P - 2 pi c): P the rim's length, c the section's centroid from the wall
        h, r = 1.0, 2.0
        lens = self.bodies(h)[1]
        rounded = lens.makeFillet(r, self.straight_edges(lens))
        self.assertAnalytic(rounded)
        rim = [
            e
            for e in rounded.Edges
            if abs(e.BoundBox.ZMin - h) < 1e-7 and abs(e.BoundBox.ZMax - h) < 1e-7
        ]
        angle = self.convex(r)[1]
        length = 2 * self.R * (math.pi - angle) + 2 * r * angle
        self.assertAlmostEqual(sum(e.Length for e in rim), length, delta=1e-6)
        result = rounded.makeFillet(h, rim)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        removed = fillet_section(h) * (length - 2 * math.pi * fillet_centroid(h))
        self.assertAlmostEqual(result.Volume, rounded.Volume - removed, delta=1e-6)
        for face in result.Faces:
            self.assertNotIn("BSpline", face.Surface.TypeId)


class RoundOverASliverTest(unittest.TestCase):
    """A round of a convex straight edge between two cylinders, where the ball can't stay on one of
    them (ops#640, Case Base #104). A plate H thick with one vertical corner rounded R about
    a = (R, R), and a hole rho about m, the middle of the corner's arc. The hole leaves two slivers
    of the corner's cylinder, each from an edge E to the tangent edge T where the cylinder runs
    into its wall plane; the two vertical edges at E are rounded r.

    The round between the two cylinders would touch the corner's cylinder past T (3.4 degrees past
    it here), 0.018 mm inside the wall plane. Onshape's ball rolls on over T: the round is a
    cylinder tangent to the wall plane and the hole, and the sliver vanishes (oracle 19's face
    dumps before and after Case Base #104 fit this closed form to 1e-12: the round's centre, its
    area and the volume removed). OCCT builds the same shape with a B-spline round."""

    R, H, r = 10.0, 1.0, 1.0
    SLIVER = math.radians(5.0)  # the sliver's angle about a

    def geometry(self):
        R, r = self.R, self.r
        a = (R, R)
        m = (R - R / math.sqrt(2), R - R / math.sqrt(2))
        theta = math.radians(45.0) - self.SLIVER
        rho = 2 * R * math.sin(theta / 2)
        at = math.radians(225.0) - theta
        E = (a[0] + R * math.cos(at), a[1] + R * math.sin(at))
        T = (0.0, R)
        # The rolled-on round's centre: r from the wall x = 0, rho + r from m
        c = (r, m[1] + math.sqrt((rho + r) ** 2 - (r - m[0]) ** 2))
        P1 = (0.0, c[1])
        P2 = (m[0] + rho * (c[0] - m[0]) / (rho + r), m[1] + rho * (c[1] - m[1]) / (rho + r))
        return dict(a=a, m=m, rho=rho, E=E, T=T, c=c, P1=P1, P2=P2)

    @staticmethod
    def turned(centre, p, q):
        a0 = math.atan2(p[1] - centre[1], p[0] - centre[0])
        a1 = math.atan2(q[1] - centre[1], q[0] - centre[0])
        return (a1 - a0 + math.pi) % (2 * math.pi) - math.pi

    def section(self, g):
        """The area the round removes: the sliver's arc E-T, the wall T-P1, the round's arc P1-P2
        and the hole's arc P2-E (the polygon, plus each arc's signed segment)"""
        pieces = [
            (g["E"], g["T"], g["a"]),
            (g["T"], g["P1"], None),
            (g["P1"], g["P2"], g["c"]),
            (g["P2"], g["E"], g["m"]),
        ]
        o = pieces[0][0]
        area = 0.0
        for p, q, centre in pieces:
            area += ((p[0] - o[0]) * (q[1] - o[1]) - (p[1] - o[1]) * (q[0] - o[0])) / 2
            if centre is not None:
                radius = math.dist(centre, p)
                t = self.turned(centre, p, q)
                area += radius * radius * (t - math.sin(t)) / 2
        return abs(area)

    def body(self, g):
        R, H, size = self.R, self.H, 40.0
        mid = V(g["m"][0], g["m"][1], 0)
        outline = Part.Wire(
            [
                Part.makeLine(V(R, 0, 0), V(size, 0, 0)),
                Part.makeLine(V(size, 0, 0), V(size, size, 0)),
                Part.makeLine(V(size, size, 0), V(0, size, 0)),
                Part.makeLine(V(0, size, 0), V(0, R, 0)),
                Part.Arc(V(0, R, 0), mid, V(R, 0, 0)).toShape(),
            ]
        )
        plate = Part.Face(outline).extrude(V(0, 0, H))
        hole = Part.makeCylinder(g["rho"], H, mid)
        return plate.cut(hole)

    def picks(self, body, g):
        ex, ey = g["E"]
        edges = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomLine"
            and abs(e.Length - self.H) < 1e-7
            and all(
                min(
                    math.hypot(v.Point.x - ex, v.Point.y - ey),
                    math.hypot(v.Point.x - ey, v.Point.y - ex),
                )
                < 1e-6
                for v in e.Vertexes
            )
        ]
        self.assertEqual(len(edges), 2)
        return edges

    def testTheClosedForm(self):
        g = self.geometry()
        self.assertAlmostEqual(g["rho"], 6.840402866513, delta=1e-9)
        self.assertAlmostEqual(g["c"][1], 10.528349121216, delta=1e-9)
        self.assertAlmostEqual(self.section(g), 0.418488287552, delta=1e-9)
        angle = abs(self.turned(g["c"], g["P1"], g["P2"]))
        self.assertAlmostEqual(angle, 1.819372996450, delta=1e-9)
        # The premise: the round between the two cylinders touches the corner's cylinder past T
        R, r = self.R, self.r
        d = math.dist(g["a"], g["m"])
        x = (d * d + (R - r) ** 2 - (g["rho"] + r) ** 2) / (2 * d)
        h = math.sqrt((R - r) ** 2 - x * x)
        ux, uy = (g["m"][0] - g["a"][0]) / d, (g["m"][1] - g["a"][1]) / d
        between = min(
            ((g["a"][0] + x * ux - s * h * uy, g["a"][1] + x * uy + s * h * ux) for s in (1, -1)),
            key=lambda p: math.dist(p, g["E"]),
        )
        touch = math.degrees(math.atan2(between[1] - g["a"][1], between[0] - g["a"][0])) % 360
        self.assertLess(touch, 180.0)  # the sliver runs from 185 (E) to 180 (T)
        self.assertAlmostEqual(touch, 176.609094764, delta=1e-6)

    def testTheRoundRollsOnOntoTheWall(self):
        g = self.geometry()
        body = self.body(g)
        self.assertTrue(body.isValid())
        slivers = [
            f
            for f in body.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - self.R) < 1e-9
        ]
        self.assertEqual(len(slivers), 2)
        for f in slivers:
            self.assertAlmostEqual(f.Area, self.R * self.SLIVER * self.H, delta=1e-7)
        result = body.makeFillet(self.r, self.picks(body, g))
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        removed = 2 * self.H * self.section(g)
        self.assertAlmostEqual(result.Volume, body.Volume - removed, delta=1e-6)
        for face in result.Faces:
            self.assertNotIn("BSpline", face.Surface.TypeId)
        for edge in result.Edges:
            self.assertIn(edge.Curve.TypeId, ("Part::GeomLine", "Part::GeomCircle"))
        # The slivers are gone, and two rounds took their place
        self.assertEqual(len(result.Faces), len(body.Faces))
        left = [
            f
            for f in result.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - self.R) < 1e-9
        ]
        self.assertEqual(left, [])
        rounds = [
            f
            for f in result.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - self.r) < 1e-9
        ]
        self.assertEqual(len(rounds), 2)
        angle = abs(self.turned(g["c"], g["P1"], g["P2"]))
        self.assertAlmostEqual(sum(f.Area for f in rounds), 2 * self.H * self.r * angle, delta=1e-6)
        # Each round's axis is r from its wall plane: (r, c) and (c, r)
        cx, cy = g["c"]
        for f in rounds:
            axis = f.Surface.Axis
            self.assertAlmostEqual(abs(axis.z), 1.0, delta=1e-9)
            p = f.Surface.Center
            off = min(math.hypot(p.x - cx, p.y - cy), math.hypot(p.x - cy, p.y - cx))
            self.assertLess(off, 1e-7)


class RoundAlongASplineEdgeTest(unittest.TestCase):
    """A constant round along a spline edge is OCCT's (NEW-165, ops#640, notes/fillet-spline-edge.md).

    A prism of height 8 over a convex G1 stadium: two straight sides of 30 at y = +-10, and caps that
    are cubic Bezier curves with poles (+-15, -+10), (+-27, -+10), (+-27, +-10), (+-15, +-10). The
    round of the whole top rim has the same section everywhere, square to the rim; Pappus over the
    closed convex rim, whose inward offset by d has length P - 2 pi d, gives the removed volume
    r^2 (1 - pi/4) (P - 2 pi k r), k = (5/6 - pi/4) / (1 - pi/4), and the round's area
    (pi r / 2) (P - 2 pi r + 4 r). Faces: the 6 base faces plus 4 rounds, two of them cylinders and
    two B-splines (the pipe about the cap's offset). The least radius of curvature on a cap is
    7.9609: past it no round exists, and the failure names OCCT and the curve kind."""

    H = 8.0
    LIMIT = 7.9609

    def rim(self, z):
        def bezier(poles):
            curve = Part.BezierCurve()
            curve.setPoles([V(x, y, z) for x, y in poles])
            return curve.toShape()

        return Part.Wire(
            [
                Part.makeLine(V(-15, -10, z), V(15, -10, z)),
                bezier([(15, -10), (27, -10), (27, 10), (15, 10)]),
                Part.makeLine(V(15, 10, z), V(-15, 10, z)),
                bezier([(-15, 10), (-27, 10), (-27, -10), (-15, -10)]),
            ]
        )

    def prism(self, walls):
        if walls == "extrusion":
            return Part.Face(self.rim(0)).extrude(V(0, 0, self.H))
        # A ruled loft: the caps' walls are B-spline surfaces, #165's kind
        return Part.makeLoft([self.rim(0), self.rim(self.H)], True, True)

    def top(self, body):
        return [
            e
            for e in body.Edges
            if abs(e.BoundBox.ZMin - self.H) < 1e-9 and abs(e.BoundBox.ZMax - self.H) < 1e-9
        ]

    def testRoundAsClosedForm(self):
        k = (5 / 6 - math.pi / 4) / (1 - math.pi / 4)
        for walls in ("extrusion", "loft"):
            body = self.prism(walls)
            self.assertTrue(body.isValid())
            P = self.rim(0).Length
            for r in (0.5, 2.0, 4.0):
                with self.subTest(walls=walls, r=r):
                    shape = body.makeFillet(r, self.top(body))
                    self.assertTrue(shape.isValid())
                    self.assertEqual(len(shape.Solids), 1)
                    self.assertEqual(len(shape.Faces), 10)
                    removed = r * r * (1 - math.pi / 4) * (P - 2 * math.pi * k * r)
                    # Shape.Volume is OCCT's default integration, which is 1e-4 mm3 off on these
                    # bodies either way (measured against the adaptive one: the loft at r 0.5 reads
                    # 7097.58318 as the ball's and 7097.58299 as OCCT's, for 7097.58310 both). At
                    # r 0.5 that is more than 1e-5 of what the round removes
                    self.assertAlmostEqual(
                        (body.Volume - shape.Volume) / removed, 1.0, delta=1e-5 + 2e-4 / removed
                    )
                    # By their corners: a spline face's box is its poles', which the compact fit
                    # of the ball's surface takes below the round
                    rounds = [
                        f
                        for f in shape.Faces
                        if all(v.Point.z > self.H - r - 1e-7 for v in f.Vertexes)
                        and f.Surface.TypeId != "Part::GeomPlane"
                    ]
                    self.assertEqual(len(rounds), 4)
                    area = math.pi * r / 2 * (P - 2 * math.pi * r + 4 * r)
                    self.assertAlmostEqual(sum(f.Area for f in rounds) / area, 1.0, delta=1e-5)
                    kinds = sorted(f.Surface.TypeId for f in rounds)
                    self.assertEqual(kinds.count("Part::GeomCylinder"), 2)
                    self.assertEqual(kinds.count("Part::GeomBSplineSurface"), 2)

    def testPastTheCurvatureLimitFailsTruthfully(self):
        for walls in ("extrusion", "loft"):
            with self.subTest(walls=walls):
                body = self.prism(walls)
                with self.assertRaises(Part.OCCError) as caught:
                    body.makeFillet(1.05 * self.LIMIT, self.top(body))
                message = str(caught.exception)
                self.assertNotIn("neither a line nor a circle", message)
                self.assertIn("OCCT failed on a round along", message)
                self.assertTrue("Bezier" in message or "B-spline" in message, message)


def ribbed_slot(rib_height, sketched=True):
    """A block 24 x 12 x 10 with a stadium slot 3 deep (centres x 20 and 32, radius 4) and a rib
    2 wide across it (x 25 to 27) standing rib_height on the floor at z 7, and the slot's top rim.
    sketched: the outline as a sketch gives it (line, three-point arc, line, three-point arc);
    otherwise its arcs are half circles from their centres, whose seams differ"""
    if sketched:
        edges = [
            Part.LineSegment(V(20, 4, 7), V(32, 4, 7)).toShape(),
            Part.Arc(V(32, 4, 7), V(36, 0, 7), V(32, -4, 7)).toShape(),
            Part.LineSegment(V(32, -4, 7), V(20, -4, 7)).toShape(),
            Part.Arc(V(20, -4, 7), V(16, 0, 7), V(20, 4, 7)).toShape(),
        ]
        wire = Part.Wire(edges)
    else:
        edges = [
            Part.makeCircle(4, V(20, 0, 7), V(0, 0, 1), 90, 270),
            Part.makeLine(V(20, -4, 7), V(32, -4, 7)),
            Part.makeCircle(4, V(32, 0, 7), V(0, 0, 1), -90, 90),
            Part.makeLine(V(32, 4, 7), V(20, 4, 7)),
        ]
        wire = Part.Wire(Part.__sortEdges__(edges))
    slot = Part.Face(wire).extrude(V(0, 0, 3))
    body = Part.makeBox(24, 12, 10, V(14, -6, 0)).cut(slot).removeSplitter()
    body = body.fuse(Part.makeBox(2, 10, rib_height, V(25, -5, 7))).removeSplitter()
    body = Part.Solid(body.Shells[0])
    rim = [
        e
        for e in body.Edges
        if abs(e.BoundBox.ZMin - 10) < 1e-9
        and abs(e.BoundBox.ZMax - 10) < 1e-9
        and e.BoundBox.XMin > 15.9
        and e.BoundBox.XMax < 36.1
        and abs(e.BoundBox.YMax) < 4.1
    ]
    return body, rim


def ribbed_slot_volume(rib_height):
    """The ribbed slot's block before the round: the block, less the slot, plus the rib"""
    return 24 * 12 * 10 - (math.pi * 16 + 8 * 12) * 3 + 2 * 8 * rib_height


def slot_rim_removed(r):
    """What a round of r on the slot's whole rim removes: the straight sides, and the half
    circles by Pappus (the section lies outside the radius 4)"""
    return fillet_section(r) * (2 * 12 + 2 * math.pi * (4 + fillet_centroid(r)))


class TangentLineStepTest(unittest.TestCase):
    """ops#806: a rib in a slot whose top is level with the rim round's lower tangent line. The
    slot's wall then has an edge on the round's contact line for part of its length, where
    OCCT 8.0.1's fillet read an edge curve that is not set and the process died (SIGSEGV in
    BRepBlend_SurfRstConstRad::Values). Onshape rounds it, or fails with an error, never a crash.
    The rib stays below the round, so the round is the rim's as without the rib."""

    def testRoundAtTheTangentLineIsExact(self):
        r = 1.0
        for sketched in (True, False):
            with self.subTest(sketched=sketched):
                body, rim = ribbed_slot(3 - r, sketched)
                self.assertTrue(body.isValid())
                self.assertEqual(len(rim), 4)
                self.assertAlmostEqual(body.Volume, ribbed_slot_volume(3 - r), delta=1e-6)
                # Must not crash: a round, exact, or an error
                try:
                    shape = body.makeFillet(r, rim)
                except Part.OCCError as e:
                    self.fail("the round at the tangent line failed: %s" % e)
                self.assertTrue(shape.isValid())
                self.assertEqual(len(shape.Solids), 1)
                self.assertAlmostEqual(
                    body.Volume - shape.Volume, slot_rim_removed(r), delta=1e-6
                )
                # The rib's top keeps its edge on the wall: nothing of the rib is rounded
                self.assertTrue(
                    any(
                        abs(f.BoundBox.ZMin - 9) < 1e-9
                        and abs(f.BoundBox.ZMax - 9) < 1e-9
                        and abs(f.Area - 16) < 1e-6
                        for f in shape.Faces
                    )
                )

    def testOneSideAtTheTangentLineIsRightOrLoud(self):
        # One straight side alone: OCCT's contour would run on along the tangent chain (its
        # error), never a crash
        body, rim = ribbed_slot(2.0)
        side = [e for e in rim if abs(e.BoundBox.YMin + 4) < 1e-9 and abs(e.BoundBox.YMax + 4) < 1e-9]
        self.assertEqual(len(side), 1)
        try:
            shape = body.makeFillet(1.0, side)
        except (Part.OCCError, FreeCAD.Base.CADKernelError) as e:
            self.assertIn("tangent", str(e))
            return
        self.assertTrue(shape.isValid())
        self.assertAlmostEqual(body.Volume - shape.Volume, 12 * fillet_section(1.0), delta=1e-6)

    def testNearTheTangentLineIsUnchanged(self):
        # Just below the line OCCT builds the same round; the check leaves it to OCCT
        body, rim = ribbed_slot(2.0 - 1e-3)
        shape = body.makeFillet(1.0, rim)
        self.assertTrue(shape.isValid())
        self.assertAlmostEqual(body.Volume - shape.Volume, slot_rim_removed(1.0), delta=1e-6)


def bent_block(turn, reflex=False, length=10.0, height=5.0):
    """A prism whose front wall turns by `turn` degrees at the origin, to the inside (a convex
    corner in plan) or, reflex, to the outside. The two top edges of the front, each `length`
    long, meet at (0, 0, height); each ends on a wall square to it."""
    a = math.radians(turn) * (-1 if reflex else 1)
    along = V(math.cos(a), math.sin(a), 0)
    square = V(-math.sin(a), math.cos(a), 0)
    end = along * length
    outline = [V(-length, 0, 0), V(0, 0, 0), end, end + square * 15, V(-length, 20, 0)]
    shape = Part.Face(Part.makePolygon(outline + outline[:1])).extrude(V(0, 0, height))
    top = [
        e
        for e in shape.Edges
        if abs(e.BoundBox.ZMin - height) < 1e-9
        and any(v.Point.distanceToPoint(V(0, 0, height)) < 1e-9 for v in e.Vertexes)
    ]
    top.sort(key=lambda e: e.CenterOfMass.x)
    return shape, top


def bent_removed(turn, size, reflex=False, length=10.0, chamfer=False):
    """What a round r (or a chamfer c) of both top edges of bent_block() removes. At the depth h
    the section loses a strip of width d along both edges, meeting in a mitre at the corner: the
    area 2 L d - d^2 tan(turn / 2) (plus, at a reflex corner). d = r - sqrt(r^2 - (r - h)^2) for
    the round, c - h for the chamfer, integrated over the depth."""
    first = size * size / 2 if chamfer else size * size * (1 - math.pi / 4)
    second = size**3 / 3 if chamfer else size**3 * (5 / 3 - math.pi / 2)
    corner = math.tan(math.radians(turn) / 2) * second
    return 2 * length * first + (corner if reflex else -corner)


class KinkedContourTest(unittest.TestCase):
    """ops#762, the root cause: OCCT 8.0.1 carries a fillet's or chamfer's contour on past a vertex
    wherever the faces at the vertex's other edges meet within 0.1 rad (5.73 degrees), whatever the
    two edges' own directions. Each edge's strip then ends in a cross-section at the vertex and the
    wedge between the cross-sections is closed with planes: a valid solid with a tooth at the
    corner, short of the mitre by up to 2 % of the removed volume here, with no error. From 0.1 rad
    on OCCT builds the mitre itself. Onshape mitres both."""

    def testARoundOverASlightCornerMitres(self):
        for turn in (5.0, 3.0, 1.0):
            for reflex in (False, True):
                with self.subTest(turn=turn, reflex=reflex):
                    shape, top = bent_block(turn, reflex)
                    self.assertEqual(len(top), 2)
                    result = shape.makeFillet(1.0, top)
                    self.assertTrue(result.isValid())
                    self.assertEqual(len(result.Solids), 1)
                    self.assertAlmostEqual(
                        shape.Volume - result.Volume, bent_removed(turn, 1.0, reflex), delta=1e-6
                    )

    def testAChamferOverASlightCornerMitres(self):
        for turn in (5.0, 3.0, 1.0):
            for reflex in (False, True):
                with self.subTest(turn=turn, reflex=reflex):
                    shape, top = bent_block(turn, reflex)
                    result = shape.makeChamfer(1.0, top)
                    self.assertTrue(result.isValid())
                    self.assertEqual(len(result.Solids), 1)
                    self.assertAlmostEqual(
                        shape.Volume - result.Volume,
                        bent_removed(turn, 1.0, reflex, chamfer=True),
                        delta=1e-6,
                    )

    def testFromOcctsOwnLimitOnAsBefore(self):
        # Control: at 6 degrees OCCT ends its contours at the corner and mitres them itself
        shape, top = bent_block(6.0)
        result = shape.makeFillet(1.0, top)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(shape.Volume - result.Volume, bent_removed(6.0, 1.0), delta=1e-5)

    def testATangentChainIsStillOne(self):
        # Control: a turn below OCCT's own tangency (0.01 rad) stays a tangent chain, as before:
        # picking one edge rounds both
        shape, top = bent_block(0.3)
        one = shape.makeFillet(1.0, top[:1])
        both = shape.makeFillet(1.0, top)
        self.assertTrue(one.isValid())
        self.assertAlmostEqual(one.Volume, both.Volume, delta=1e-9)

    def testOneEdgeOfTheCornerRunsStraightOn(self):
        # One edge picked: the round does not carry on past the corner (Onshape's propagation
        # doesn't either); it runs straight on and leaves the body where the wall turns away,
        # as OCCT's does from 0.1 rad on. Past the corner it takes the wedge between the wall
        # and the strip: d^2 / (2 tan(turn)) at each depth (r 0.5: the wedge, r / tan(turn) long,
        # ends before the second edge does)
        r = 0.5
        for turn in (5.0, 3.0, 6.0):
            with self.subTest(turn=turn):
                shape, top = bent_block(turn)
                result = shape.makeFillet(r, top[:1])
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                self.assertLess(r / math.tan(math.radians(turn)), 10)
                expected = 10 * r * r * (1 - math.pi / 4) + r**3 * (5 / 3 - math.pi / 2) / (
                    2 * math.tan(math.radians(turn))
                )
                self.assertAlmostEqual(shape.Volume - result.Volume, expected, delta=1e-5)

    def testAPolygonsRimMitresAtEveryCorner(self):
        # The issue's model: OCCT's contours close round the rim from 63 sides on
        for sides in (63, 100):
            with self.subTest(sides=sides):
                shape, rim = VolumeSignTest.prism(sides)
                self.assertEqual(len(rim), sides)
                result = shape.makeFillet(0.2, rim)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Faces), 2 * sides + 2)
                self.assertAlmostEqual(
                    shape.Volume - result.Volume, VolumeSignTest.removed(sides, 0.2), delta=1e-6
                )
                chamfered = shape.makeChamfer(0.2, rim)
                self.assertTrue(chamfered.isValid())
                expected = sides * 2.0 * 0.02 - sides * math.tan(math.pi / sides) * 0.008 / 3
                self.assertAlmostEqual(shape.Volume - chamfered.Volume, expected, delta=1e-6)

    def testTwoRadiiOverTheCornerAreRefused(self):
        # Part::Fillet with a radius per edge runs OCCT's maker alone: it fails, never the tooth
        shape, top = bent_block(5.0)
        doc = FreeCAD.newDocument("KinkedContourTest")
        try:
            base = doc.addObject("Part::Feature", "Base")
            base.Shape = shape
            fillet = doc.addObject("Part::Fillet", "Fillet")
            fillet.Base = base
            picked = [i for i, e in enumerate(shape.Edges, 1) if any(e.isSame(x) for x in top)]
            self.assertEqual(len(picked), 2)
            fillet.Edges = [(picked[0], 1.0, 1.0), (picked[1], 0.5, 0.5)]
            doc.recompute()
            self.assertFalse(fillet.isValid())
            self.assertIn("slight corner", fillet.getStatusString())
            fillet.Edges = [(picked[0], 1.0, 1.0), (picked[1], 1.0, 1.0)]
            doc.recompute()
            self.assertTrue(fillet.isValid())
            self.assertAlmostEqual(
                shape.Volume - fillet.Shape.Volume, bent_removed(5.0, 1.0), delta=1e-6
            )
        finally:
            FreeCAD.closeDocument(doc.Name)


def graded_integral(f, a, b, at_b=True, levels=40):
    """The integral of f over [a, b], graded towards an end point where f has a square root's kink"""
    total = 0.0
    for k in range(levels):
        lo, hi = 1 - 2.0**-k, 1 - 2.0 ** -(k + 1)
        if at_b:
            total += gauss_legendre(f, a + (b - a) * lo, a + (b - a) * hi)
        else:
            total += gauss_legendre(f, b - (b - a) * hi, b - (b - a) * lo)
    return total


class ArcEndPlaneTest(unittest.TestCase):
    """ops#888 A2, designed: a boss of radius R = 10 and height H = 2, cut by the chord plane x = c = 5
    (the material x <= c), its top arc chamfered or rounded. OCCT fails from the limit (the size H) up,
    and the arc's ends lie on the chord plane, which does not contain the axis. Onshape's dress-up
    surface (the cone or torus) runs on to the chord face, which trims it: the result is the boss
    minus the ring of the section revolved about the axis, cut by the chord's half-space. Past
    R - c = 5 the section reaches in past the chord's distance from the axis, and the face runs on
    across the chord in one piece. With a second plane through the axis, y >= 0, only one end is on
    the chord: half the boss and half of what goes.

    In a slice at the depth z below the top the section spans the radii rho1(z)..R (the chamfer's
    rho1 = R - d + z, the round's R - d + sqrt(d^2 - (d - z)^2)); the ring takes pi (R^2 - rho1^2)
    of it, less the part beyond the chord, F(R) - F(max(c, rho1)) with
    F(rho) = rho^2 acos(c / rho) - c sqrt(rho^2 - c^2), the integral of 2 rho acos(c / rho)."""

    R, H, c = 10.0, 2.0, 5.0
    unit = 1.0  # the sizes below are in units of R / 10 (ArcEndPlaneAt600Test)

    def body(self, half=False):
        R, H, c = self.R, self.H, self.c
        keep = Part.makeBox(4 * R, 4 * R, 4 * H, V(c - 4 * R, -2 * R, -H))
        if half:
            keep = keep.common(Part.makeBox(4 * R, 4 * R, 4 * H, V(-2 * R, 0, -H)))
        body = Part.makeCylinder(R, H).common(keep).removeSplitter()
        arcs = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - R) < 1e-9
            and all(abs(v.Point.z - H) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(arcs), 1)
        return body, arcs[0]

    def removed(self, kind, d, half=False):
        R, c = self.R, self.c
        top = min(self.H, d)

        def F(rho):
            return rho * rho * math.acos(c / rho) - c * math.sqrt(rho * rho - c * c)

        def slice_area(rho1):
            return math.pi * (R * R - rho1 * rho1) - (F(R) - F(max(c, rho1)))

        if kind == "chamfer":
            rho = lambda z: R - d + z
            f = lambda z: slice_area(rho(z))
            a, b = 0.0, top
            split = d - (R - c)  # where rho1 = c
        else:
            # z = d (1 - cos t): rho1 = R - d + d sin t, dz = d sin t dt
            f = lambda t: slice_area(R - d + d * math.sin(t)) * d * math.sin(t)
            a, b = 0.0, math.acos(1 - top / d)
            s = 1 - (R - c) / d
            split = math.asin(s) if 0 < s < 1 else -1.0
        if a < split < b:
            total = graded_integral(f, a, split) + graded_integral(f, split, b, at_b=False)
        else:
            total = graded_integral(f, a, b)
        return total / 2 if half else total

    def ring(self, kind, d):
        """The section at the rim in the half-plane y = 0, x > 0, revolved a whole turn"""
        R, H = self.R, self.H
        if kind == "chamfer":
            section = Part.Face(Part.makePolygon([V(R, 0, H), V(R - d, 0, H), V(R, 0, H - d), V(R, 0, H)]))
        else:
            square = Part.makePolygon(
                [V(R, 0, H), V(R - d, 0, H), V(R - d, 0, H - d), V(R, 0, H - d), V(R, 0, H)]
            )
            ball = Part.Face(Part.Wire(Part.makeCircle(d, V(R - d, 0, H - d), V(0, 1, 0))))
            section = Part.Face(square).cut(ball)
        return section.revolve(V(0, 0, 0), V(0, 0, 1), 360)

    def check(self, kind, d, half=False, faces=None):
        d *= self.unit
        body, arc = self.body(half)
        result = body.makeChamfer(d, [arc]) if kind == "chamfer" else body.makeFillet(d, [arc])
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        # The shape: the boss less the ring, which the boss's own faces cut
        expected = body.cut(self.ring(kind, d))
        cube = self.unit**3
        self.assertLess(result.cut(expected).Volume, 1e-6 * cube)
        self.assertLess(expected.cut(result).Volume, 1e-6 * cube)
        # The volume in closed form; OCCT integrates a trimmed torus's volume only to about 5e-6
        removed = self.removed(kind, d, half)
        tolerance = 1e-6 * cube if kind == "chamfer" else 1e-5 * removed
        self.assertAlmostEqual(body.Volume - result.Volume, removed, delta=tolerance)
        if faces is not None:
            self.assertEqual(len(result.Faces), faces)
        # Nothing beyond the chord, whose face is one: the tool's end there merged into it
        chord = [
            f
            for f in result.Faces
            if f.Surface.TypeId == "Part::GeomPlane" and abs(f.normalAt(0, 0).x - 1) < 1e-9
        ]
        self.assertEqual(len(chord), 1)
        self.assertLessEqual(result.optimalBoundingBox().XMax, self.c + 1e-6 * self.unit)
        return result

    def testChamferToTheLimit(self):
        # the cone takes the whole wall: top, bottom, chord and cone
        self.check("chamfer", 2.0, faces=4)

    def testChamferPastItsStrip(self):
        # 4 on a strip 2 wide: the cone runs out through the bottom, past the vertex to the chord
        self.check("chamfer", 4.0, faces=4)

    def testChamferAcrossTheChord(self):
        # 6: the cone reaches in to radius 4 at the top, inside the chord's distance 5: one face across it
        result = self.check("chamfer", 6.0, faces=4)
        cones = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomCone"]
        self.assertEqual(len(cones), 1)

    def testRoundToTheLimit(self):
        self.check("fillet", 2.0, faces=4)

    def testRoundPastItsStrip(self):
        self.check("fillet", 4.0, faces=4)

    def testRoundAcrossTheChord(self):
        self.check("fillet", 6.0, faces=4)

    def testOneEndOnTheChord(self):
        # half the boss: one end on the plane y = 0 through the axis, the other on the chord
        for kind in ("chamfer", "fillet"):
            with self.subTest(kind=kind):
                self.check(kind, 4.0, half=True, faces=5)

    def testSplitBySeamAsOneArc(self):
        # The cylinder turned half a turn: its seam splits the top arc in two. The same boss, so
        # the same result, the ring across the chord (6) as one tool for both arcs (ops#888)
        R, H, c = self.R, self.H, self.c
        keep = Part.makeBox(4 * R, 4 * R, 4 * H, V(c - 4 * R, -2 * R, -H))
        cylinder = Part.makeCylinder(R, H)
        cylinder.rotate(V(0, 0, 0), V(0, 0, 1), 180)
        body = cylinder.common(keep).removeSplitter()
        arcs = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - R) < 1e-9
            and all(abs(v.Point.z - H) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(arcs), 2)
        cube = self.unit**3
        for kind in ("chamfer", "fillet"):
            for d in (2.0, 4.0, 6.0):
                with self.subTest(kind=kind, size=d):
                    one = self.check(kind, d)
                    size = d * self.unit
                    two = body.makeChamfer(size, arcs) if kind == "chamfer" else body.makeFillet(size, arcs)
                    self.assertTrue(two.isValid())
                    self.assertEqual(len(two.Solids), 1)
                    self.assertLess(two.cut(one).Volume, 1e-6 * cube)
                    self.assertLess(one.cut(two).Volume, 1e-6 * cube)

    def testOneEndOnTheChordAcrossItIsRefused(self):
        # 6 with one end on the chord: the turn on past it never reaches the chord's far side
        body, arc = self.body(half=True)
        with self.assertRaises(Exception) as caught:
            body.makeChamfer(6.0 * self.unit, [arc])
        self.assertIn("never reaches the end plane", str(caught.exception))


class ArcEndPlaneAt600Test(ArcEndPlaneTest):
    """ArcEndPlaneTest at 30 times the size (R 300 mm): a trimmed torus's volume integrates to about
    2e-6 of it there, which the construction's balance check allows (review of ops#888 A2)"""

    R, H, c = 300.0, 60.0, 150.0
    unit = 30.0


class ArcEndRingTest(unittest.TestCase):
    """ops#888 A2, where OCCT builds: oracle s8ecd's DU2 (notes/onshape-facts.md), a plate 30 x 30 x 3
    under a boss of radius 10, z 3..9, whose profile is cut by the chord y = 8 (one arc, as a sketch
    gives it). From the size R - c = 2 up the section reaches inside the chord's distance from the
    axis, and Onshape's cone or torus runs on across the chord, which cuts it: the top becomes a disc.
    OCCT builds a valid shape there that is not that (DU2's chamfer 4: 4121.743 against Onshape's
    4103.824, 13 faces against 10), so the exact construction builds it (FilletFallback::endsInRing).
    Below R - c OCCT's result is the ring's already and stays OCCT's."""

    R, top, c = 10.0, 9.0, 8.0

    def body(self, seam=False):
        R, c = self.R, self.c
        if seam:
            # the cylinder's seam splits the top circle into two arcs
            boss = Part.makeCylinder(R, 6, V(0, 0, 3)).common(Part.makeBox(40, 40, 20, V(-20, c - 40, 0)))
        else:
            x = math.sqrt(R * R - c * c)
            profile = Part.Wire(
                [
                    Part.Arc(V(x, c, 3), V(0, -R, 3), V(-x, c, 3)).toShape(),
                    Part.LineSegment(V(-x, c, 3), V(x, c, 3)).toShape(),
                ]
            )
            boss = Part.Face(profile).extrude(V(0, 0, 6))
        body = Part.makeBox(30, 30, 3, V(-15, -15, 0)).fuse(boss).removeSplitter()
        arcs = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and all(abs(v.Point.z - self.top) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(arcs), 2 if seam else 1)
        self.assertAlmostEqual(body.Volume, 4486.85493, delta=1e-4)
        return body, arcs

    def ring(self, kind, d):
        R, H = self.R, self.top
        if kind == "chamfer":
            section = Part.Face(Part.makePolygon([V(R, 0, H), V(R - d, 0, H), V(R, 0, H - d), V(R, 0, H)]))
        else:
            square = Part.makePolygon(
                [V(R, 0, H), V(R - d, 0, H), V(R - d, 0, H - d), V(R, 0, H - d), V(R, 0, H)]
            )
            ball = Part.Face(Part.Wire(Part.makeCircle(d, V(R - d, 0, H - d), V(0, 1, 0))))
            section = Part.Face(square).cut(ball)
        return section.revolve(V(0, 0, 0), V(0, 0, 1), 360)

    def dress(self, kind, d, seam=False):
        body, arcs = self.body(seam)
        result = body.makeChamfer(d, arcs) if kind == "chamfer" else body.makeFillet(d, arcs)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        expected = body.cut(self.ring(kind, d))
        self.assertLess(result.cut(expected).Volume, 1e-6)
        self.assertLess(expected.cut(result).Volume, 1e-6)
        return result

    def testAsOnshape(self):
        # Onshape's values (evVolume HIGH); a trimmed torus's volume integrates to about 1e-7 here
        for kind, volume, area, delta in (
            ("chamfer", 4103.82368, 2376.07238, 1e-4),
            ("fillet", 4320.18881, 2429.58734, 1e-3),
        ):
            with self.subTest(kind=kind):
                result = self.dress(kind, 4.0)
                self.assertAlmostEqual(result.Volume, volume, delta=delta)
                self.assertAlmostEqual(result.Area, area, delta=1e-4)
                self.assertEqual(len(result.Faces), 10)

    def testFromRMinusC(self):
        # Past the threshold: the ring cut by the chord, 10 faces (the top a disc)
        for kind, d in (("chamfer", 2.05), ("chamfer", 3.0), ("fillet", 2.5), ("fillet", 5.0)):
            with self.subTest(kind=kind, size=d):
                self.assertEqual(len(self.dress(kind, d).Faces), 10)

    def testAtRMinusC(self):
        # At d = R - c the section's inner circle touches the chord at one point, where both ends'
        # tangent points coincide: the ring, as on either side of it (review r2 of fork PR 474;
        # OCCT's is 0.566 more). On two walls Onshape is not the ring there (ArcEndTwoWallsTest)
        for kind in ("chamfer", "fillet"):
            with self.subTest(kind=kind):
                self.assertEqual(len(self.dress(kind, 2.0).Faces), 10)

    def testBelowRMinusCStaysOccts(self):
        # Below it each end's tool ends on the chord: OCCT's result, which is the same shape
        for kind in ("chamfer", "fillet"):
            with self.subTest(kind=kind):
                self.dress(kind, 1.5)

    def testSplitBySeamAsOnshape(self):
        # Two arcs of one circle (the cylinder's seam): the one ring across both, Onshape's single
        # arc's values (testAsOnshape), its faces generated by both arcs
        for kind, volume, area, delta in (
            ("chamfer", 4103.82368, 2376.07238, 1e-4),
            ("fillet", 4320.18881, 2429.58734, 1e-3),
        ):
            with self.subTest(kind=kind):
                result = self.dress(kind, 4.0, seam=True)
                self.assertAlmostEqual(result.Volume, volume, delta=delta)
                self.assertAlmostEqual(result.Area, area, delta=1e-4)
                self.assertEqual(len(result.Faces), 10)

    def testSplitBySeamFromRMinusC(self):
        for kind, d in (("chamfer", 2.05), ("chamfer", 3.0), ("fillet", 2.5), ("fillet", 5.0)):
            with self.subTest(kind=kind, size=d):
                self.assertEqual(len(self.dress(kind, d, seam=True).Faces), 10)

    def testSplitBySeamNamesBothArcs(self):
        # The ring's face is generated by both arcs, the single arc's by it alone
        for seam, sources in ((False, 1), (True, 2)):
            body, arcs = self.body(seam)
            body.Tag = 1  # a tagged shape gets an element map
            for kind in ("chamfer", "fillet"):
                with self.subTest(seam=seam, kind=kind):
                    result = body.makeChamfer(4.0, arcs) if kind == "chamfer" else body.makeFillet(4.0, arcs)
                    rings = [
                        name
                        for name, index in result.ElementMap.items()
                        if index.startswith("Face")
                        and result.getElement(index).Surface.TypeId
                        in ("Part::GeomCone", "Part::GeomToroid", "Part::GeomSurfaceOfRevolution")
                    ]
                    self.assertEqual(len(rings), 1)
                    self.assertIn("GEN", rings[0])
                    self.assertEqual(rings[0].count("SRC"), sources)

class ArcEndTwoWallsTest(unittest.TestCase):
    """ops#888 A2b, oracle 888b's DU4-DU5 (notes/onshape-facts.md): DU2's plate and boss of radius
    R = 10, z 3..9, the boss cut by the walls x = c and y = c, which meet at (c, c) inside the
    circle. Its top arc runs the long way round from one wall to the other. Where the section
    reaches inside both walls' distance from the axis (R - d < c), Onshape's surface runs on across
    both: the result is the body less the section revolved a whole turn, 11 faces, the top a full
    disc of radius R - d. OCCT builds a valid shape there that is not that (13 faces, 8 to 30 mm3
    off). At d = R - c the inner circle touches both walls: Onshape leaves the corner zone x > 0,
    y > 0 at full height (chamfer 3845.33352 against the ring's 3839.50260), which the
    construction doesn't build: refused, never OCCT's 3847.19886."""

    R = 10.0

    def body(self, c, seam=False):
        plate = Part.makeBox(30, 30, 3, V(-15, -15, 0))
        keep = Part.makeBox(40, 40, 20, V(c - 40, c - 40, 0))
        cylinder = Part.makeCylinder(self.R, 6, V(0, 0, 3))
        if seam:
            # turned half a turn: its seam splits the top arc in two
            cylinder.rotate(V(0, 0, 0), V(0, 0, 1), 180)
        body = plate.fuse(cylinder.common(keep)).removeSplitter()
        arcs = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - self.R) < 1e-9
            and all(abs(v.Point.z - 9) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(arcs), 2 if seam else 1)
        return body, arcs

    def ring(self, kind, d):
        R, H = self.R, 9.0
        if kind == "chamfer":
            section = Part.Face(Part.makePolygon([V(R, 0, H), V(R - d, 0, H), V(R, 0, H - d), V(R, 0, H)]))
        else:
            square = Part.makePolygon(
                [V(R, 0, H), V(R - d, 0, H), V(R - d, 0, H - d), V(R, 0, H - d), V(R, 0, H)]
            )
            ball = Part.Face(Part.Wire(Part.makeCircle(d, V(R - d, 0, H - d), V(0, 1, 0))))
            section = Part.Face(square).cut(ball)
        return section.revolve(V(0, 0, 0), V(0, 0, 1), 360)

    def dress(self, kind, c, d, seam=False):
        body, arcs = self.body(c, seam)
        return body, (body.makeChamfer(d, arcs) if kind == "chamfer" else body.makeFillet(d, arcs))

    def testTheRingCutByBothWalls(self):
        # Onshape: the full ring within 6e-5 mm3, 11 faces, in every case
        for kind, c, d in (
            ("chamfer", 7.0, 4.0),
            ("chamfer", 6.5, 4.0),
            ("chamfer", 6.0, 5.0),
            ("chamfer", 6.0, 4.05),
            ("chamfer", 6.02, 4.0),
            ("fillet", 7.0, 4.0),
            ("fillet", 6.5, 4.0),
            ("fillet", 6.0, 4.05),
            ("fillet", 6.0, 5.0),
        ):
            with self.subTest(kind=kind, c=c, size=d):
                body, result = self.dress(kind, c, d)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                expected = body.cut(self.ring(kind, d))
                self.assertLess(result.cut(expected).Volume, 1e-6)
                self.assertLess(expected.cut(result).Volume, 1e-6)
                # OCCT integrates a trimmed torus's volume to about 2e-7 of it (the shapes agree)
                delta = 6e-5 if kind == "chamfer" else 1e-3
                self.assertAlmostEqual(result.Volume, expected.Volume, delta=delta)
                self.assertEqual(len(result.Faces), 11)

    def testTheRingCutByBothWallsSplitBySeam(self):
        # The top arc in two at the cylinder's seam: the same ring, one tool for both (ops#888)
        for kind, c, d in (("chamfer", 7.0, 4.0), ("chamfer", 6.0, 5.0), ("fillet", 6.5, 4.0)):
            with self.subTest(kind=kind, c=c, size=d):
                body, result = self.dress(kind, c, d, seam=True)
                self.assertTrue(result.isValid())
                self.assertEqual(len(result.Solids), 1)
                expected = body.cut(self.ring(kind, d))
                self.assertLess(result.cut(expected).Volume, 1e-6)
                self.assertLess(expected.cut(result).Volume, 1e-6)
                self.assertEqual(len(result.Faces), 11)

    def testRingVolumeAsOnshape(self):
        # The boundary case's ring, as the oracle measured it: the model is the oracle's
        body, _ = self.body(6.0)
        self.assertAlmostEqual(body.cut(self.ring("chamfer", 4.0)).Volume, 3839.50260, delta=1e-4)
        self.assertAlmostEqual(body.cut(self.ring("fillet", 4.0)).Volume, 3966.13459, delta=1e-3)

    def testTangentToBothWallsIsRefused(self):
        # d = R - c: Onshape 3845.33352 (chamfer), 3967.04183 (round), OCCT's 3847.19886 and
        # 3967.37889 are wrong: the dress-up fails
        for kind in ("chamfer", "fillet"):
            with self.subTest(kind=kind):
                with self.assertRaises(Exception):
                    self.dress(kind, 6.0, 4.0)

    def testWallsBeyondTheSectionStayOccts(self):
        # c 5, d 2: the section stays outside both walls' distance; OCCT's result, the ring's shape
        body, result = self.dress("chamfer", 5.0, 2.0)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, body.cut(self.ring("chamfer", 2.0)).Volume, delta=1e-6)


class KeyholePocketChamferTest(unittest.TestCase):
    """ops#888 A3, designed (the oracle's DU3, notes/onshape-facts.md): a block x -10..20, y -10..10,
    z 0..10 with a keyhole pocket, the circle r 6 about the origin and the slot x 0..14, |y| < 2,
    sunk to the depth h. The floor's arc and its line y = +2 meet at (sqrt(32), 2), under the convex
    wall edge where the slot leaves the circle: concave edges at a corner convex in the material.
    A chamfer of 1.0 on both fills them. Below h = 1 the walls are lower than the chamfer: OCCT
    fails, and Onshape clips both fills and their sharp miter by the block top, which grows over
    them; the walls the fills run up are gone. Each fill runs past the corner to the other's
    setback (the plane from x sqrt(5^2 - 1^2)), and the cone past its other end to the unpicked
    wall y = -2 (from x sqrt(5^2 - 2^2))."""

    def body(self, depth):
        V = FreeCAD.Vector
        block = Part.makeBox(30, 20, 10, V(-10, -10, 0))
        floor = 10 - depth
        pocket = (
            Part.makeCylinder(6, depth + 1, V(0, 0, floor))
            .fuse(Part.makeBox(14, 4, depth + 1, V(0, -2, floor)))
            .removeSplitter()
        )
        body = block.cut(pocket).removeSplitter()
        on_floor = [e for e in body.Edges if all(abs(v.Point.z - floor) < 1e-9 for v in e.Vertexes)]
        arc = [e for e in on_floor if e.Curve.TypeId == "Part::GeomCircle"]
        line = [
            e
            for e in on_floor
            if e.Curve.TypeId == "Part::GeomLine" and all(abs(v.Point.y - 2) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual((len(arc), len(line)), (1, 1))
        return body, arc + line

    def faces(self, shape, type_id, test=lambda f: True):
        return [f for f in shape.Faces if f.Surface.TypeId == type_id and test(f)]

    def testWallsLowerThanTheChamfer(self):
        body, edges = self.body(0.9662)
        self.assertAlmostEqual(body.Volume, 5859.37007, delta=1e-4)
        result = body.makeChamfer(1.0, edges)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        # Onshape: 5879.57350 mm3, 2227.81949 mm2, 11 faces
        self.assertAlmostEqual(result.Volume, 5879.57350, delta=2e-4)
        self.assertAlmostEqual(result.Area, 2227.81949, delta=2e-4)
        self.assertEqual(len(result.Faces), 11)
        # Nothing above the block top, which grows over the fills
        self.assertLess(result.optimalBoundingBox().ZMax, 10 + 1e-6)
        top = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.z - 10) < 1e-9)
        self.assertEqual(len(top), 1)
        self.assertAlmostEqual(top[0].Area, 455.8663, delta=2e-4)
        # The cone r 5 at the floor to 5.9662 at the top; the walls it runs up are gone
        cones = self.faces(result, "Part::GeomCone")
        self.assertEqual(len(cones), 1)
        self.assertAlmostEqual(cones[0].Area, 42.22315, delta=2e-4)
        self.assertEqual(self.faces(result, "Part::GeomCylinder"), [])
        # The chamfer plane, from the other's setback x = sqrt(24)
        sloped = self.faces(result, "Part::GeomPlane", lambda f: abs(abs(f.normalAt(0, 0).z) - 0.5**0.5) < 1e-6)
        self.assertEqual(len(sloped), 1)
        self.assertAlmostEqual(sloped[0].Area, 11.92269, delta=2e-4)
        self.assertAlmostEqual(sloped[0].BoundBox.XMin, math.sqrt(24), delta=1e-6)
        # The unpicked wall y = -2 starts where the cone reaches it, x = sqrt(21)
        wall = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.y + 2) < 1e-9)
        self.assertEqual(len(wall), 1)
        self.assertAlmostEqual(wall[0].Area, 8.59517, delta=2e-4)
        self.assertAlmostEqual(wall[0].BoundBox.XMin, math.sqrt(21), delta=1e-6)
        floor = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.z - (10 - 0.9662)) < 1e-9)
        self.assertEqual(len(floor), 1)
        self.assertAlmostEqual(floor[0].Area, 105.84682, delta=2e-4)

    def testSteppedTopIsRefused(self):
        # A round pocket r 6, 0.5 deep, in a block whose top steps up by 2 over x < 0, its floor
        # circle chamfered 1.0: only the low wall is lower than the chamfer. The block top's plane
        # would clip the cone all the way round, under the tall wall too (review r1 of A3: 2.29 too
        # little, silently). No Onshape fact: refused, as before A3
        V = FreeCAD.Vector
        block = Part.makeBox(20, 20, 10, V(-10, -10, 0)).fuse(Part.makeBox(10, 20, 2, V(-10, -10, 10)))
        body = block.cut(Part.makeCylinder(6, 3, V(0, 0, 9.5))).removeSplitter()
        floor = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle" and all(abs(v.Point.z - 9.5) < 1e-9 for v in e.Vertexes)
        ]
        self.assertTrue(floor)
        with self.assertRaises(Exception):
            body.makeChamfer(1.0, floor)

    def testSteppedTopOverGroovedFloorIsRefused(self):
        # The same pocket with a groove 1 wide, 0.3 deep, across its floor, the slab over x < -2:
        # the floor circle in three arcs, the wall one face. The left arc's tool runs under the
        # low top only, yet part of it is under the slab (its fix's review: 1.78 too little)
        V = FreeCAD.Vector
        block = Part.makeBox(20, 20, 10, V(-10, -10, 0)).fuse(Part.makeBox(8, 20, 2, V(-10, -10, 10)))
        body = (
            block.cut(Part.makeCylinder(6, 3, V(0, 0, 9.5)))
            .cut(Part.makeBox(1, 12, 0.3, V(-0.5, -6, 9.2)))
            .removeSplitter()
        )
        floor = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - 6) < 1e-9
            and all(abs(v.Point.z - 9.5) < 1e-9 for v in e.Vertexes)
        ]
        self.assertTrue(floor)
        with self.assertRaises(Exception):
            body.makeChamfer(1.0, floor)

    def testRampTopOverRampFloorIsRefused(self):
        # A round pocket r 6 whose floor is z 9.5 over x < 0 and falls 0.5 per mm over x > 0 (one
        # floor arc of 180 deg, one wall face), in a block whose top is z 10 over x > -4 and rises
        # 0.2 per mm towards -x: the wall meets the ramps in ellipses. The z 10 top circles are
        # long enough in all, yet over the arc only near its ends, and the half-space would clip
        # the tool under the ramp too (review r1g of A3: 0.82 too little, silently). Refused
        V = FreeCAD.Vector

        def above(point, normal):
            box = Part.makeBox(200, 200, 100, V(-100, -100, 0))
            box.Placement = FreeCAD.Placement(point, FreeCAD.Rotation(V(0, 0, 1), normal))
            return box

        up = Part.makeBox(6, 20, 8, V(-10, -10, 10)).cut(above(V(-4, 0, 10), V(0.2, 0, 1).normalize()))
        block = Part.makeBox(20, 20, 10, V(-10, -10, 0)).fuse(up).removeSplitter()
        cylinder = Part.makeCylinder(6, 30, V(0, 0, 0))
        left = cylinder.common(Part.makeBox(20, 40, 30, V(-20, -20, 9.5)))
        right = cylinder.common(Part.makeBox(20, 40, 30, V(0, -20, 0))).common(
            above(V(0, 0, 9.5), V(0.5, 0, 1).normalize())
        )
        body = block.cut(left.fuse(right).removeSplitter()).removeSplitter()
        floor = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - 6) < 1e-7
            and all(abs(v.Point.z - 9.5) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(floor), 1)
        with self.assertRaises(Exception):
            body.makeChamfer(1.0, floor)

    def testTallWallsStayOccts(self):
        # Walls 3 high: OCCT builds it, as Onshape's (5583.57887, 13 faces)
        body, edges = self.body(3.0)
        result = body.makeChamfer(1.0, edges)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 5583.57887, delta=2e-4)
        self.assertAlmostEqual(result.Area, 2337.43788, delta=2e-4)
        self.assertEqual(len(result.Faces), 13)


class KeyholeBossCornerTest(unittest.TestCase):
    """ops#888 A3b, designed (the oracle's DU6, notes/onshape-facts.md): a plate x -10..20,
    y -10..10, z 0..3, with a keyhole boss on it, the circle r 6 about the origin and the slot
    x 0..14, |y| < 2, of height h. The boss's foot arc and its foot line y = +2 meet at
    (sqrt(32), 2), the outline's concave corner: concave edges at a vertex reflex in the material.
    A chamfer or fillet of 1.0 on both. Below h = 1 the walls are lower than the dress-up: OCCT
    fails, and Onshape's fills, clipped by the boss top, which grows over them, meet along their
    intersection, from (sqrt(40), 3, 3) at the foot to (5.6807, 2.0338, 3 + h) at the top. The
    cone runs on along the unpicked wall y = -2 and ends on it (from x sqrt(45) at the foot), and
    the line's fill ends flush with the slot's end wall x 14."""

    def body(self, height, step=None):
        V = FreeCAD.Vector
        plate = Part.makeBox(30, 20, 3, V(-10, -10, 0))
        boss = Part.makeCylinder(6, height, V(0, 0, 3)).fuse(Part.makeBox(14, 4, height, V(0, -2, 3)))
        if step is not None:
            # The slot taller from x = step on
            boss = boss.fuse(Part.makeBox(14 - step, 4, height + 1, V(step, -2, 3)))
        body = plate.fuse(boss.removeSplitter()).removeSplitter()
        foot = [e for e in body.Edges if all(abs(v.Point.z - 3) < 1e-9 for v in e.Vertexes)]
        arc = [e for e in foot if e.Curve.TypeId == "Part::GeomCircle"]
        line = [
            e
            for e in foot
            if e.Curve.TypeId == "Part::GeomLine" and all(abs(v.Point.y - 2) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual((len(arc), len(line)), (1, 1))
        return body, arc + line

    def faces(self, shape, type_id, test=lambda f: True):
        return [f for f in shape.Faces if f.Surface.TypeId == type_id and test(f)]

    def check(self, result, volume, area, top):
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, volume, delta=2e-4)
        self.assertAlmostEqual(result.Area, area, delta=2e-4)
        self.assertEqual(len(result.Faces), 11)
        # Nothing above the boss top, which grows over the fills; the walls they run up are gone
        self.assertLess(result.optimalBoundingBox().ZMax, 3.9662 + 1e-6)
        tops = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.z - 3.9662) < 1e-9)
        self.assertEqual(len(tops), 1)
        self.assertAlmostEqual(tops[0].Area, top, delta=2e-4)
        self.assertEqual(self.faces(result, "Part::GeomCylinder", lambda f: abs(f.Surface.Radius - 6) < 1e-9), [])
        # The plate top shrinks under both fills, as Onshape's
        plate = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.z - 3) < 1e-9)
        self.assertEqual(len(plate), 1)

    def testChamferOnWallsLowerThanIt(self):
        body, edges = self.body(0.9662)
        self.assertAlmostEqual(body.Volume, 1940.62993, delta=1e-4)
        result = body.makeChamfer(1.0, edges)
        # Onshape: 1962.34713 mm3, 1529.63646 mm2, 11 faces; the top 146.97048
        self.check(result, 1962.34713, 1529.63646, 146.97048)
        cones = self.faces(result, "Part::GeomCone")
        self.assertEqual(len(cones), 1)
        self.assertAlmostEqual(cones[0].Area, 49.64000, delta=2e-4)
        sloped = self.faces(result, "Part::GeomPlane", lambda f: abs(abs(f.normalAt(0, 0).z) - 0.5**0.5) < 1e-6)
        self.assertEqual(len(sloped), 1)
        self.assertAlmostEqual(sloped[0].Area, 10.91985, delta=2e-4)
        # The fills meet along their intersection: the plane from x sqrt(40) at the foot
        self.assertAlmostEqual(sloped[0].BoundBox.XMin, 5.6807, delta=1e-4)
        self.assertAlmostEqual(
            min(v.Point.x for v in sloped[0].Vertexes if abs(v.Point.z - 3) < 1e-9), math.sqrt(40), delta=1e-6
        )
        self.assertAlmostEqual(self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.z - 3) < 1e-9)[0].Area, 410.20723, delta=2e-4)
        # The unpicked wall y = -2 from where the cone ends on it, x sqrt(45) at the foot
        wall = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.y + 2) < 1e-9)
        self.assertEqual(len(wall), 1)
        self.assertAlmostEqual(wall[0].Area, 7.53466, delta=2e-4)
        self.assertAlmostEqual(
            min(v.Point.x for v in wall[0].Vertexes if abs(v.Point.z - 3) < 1e-9), math.sqrt(45), delta=1e-6
        )
        # The slot's end wall over the chamfer's section, y -2..3
        end = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.x - 14) < 1e-9)
        self.assertEqual(len(end), 1)
        self.assertAlmostEqual(end[0].Area, 4.36423, delta=2e-4)

    def testFilletOnWallsLowerThanIt(self):
        body, edges = self.body(0.9662)
        result = body.makeFillet(1.0, edges)
        # Onshape: 1949.85345 mm3, 1534.79436 mm2, 11 faces; the top 145.57348
        self.check(result, 1949.85345, 1534.79436, 145.57348)
        tori = self.faces(result, "Part::GeomToroid")
        self.assertEqual(len(tori), 1)
        self.assertAlmostEqual(tori[0].Area, 54.66558, delta=2e-4)
        rounds = self.faces(result, "Part::GeomCylinder")
        self.assertEqual(len(rounds), 1)
        self.assertAlmostEqual(rounds[0].Area, 12.43418, delta=2e-4)
        wall = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.y + 2) < 1e-9)
        self.assertEqual(len(wall), 1)
        self.assertAlmostEqual(wall[0].Area, 7.83449, delta=2e-4)
        end = self.faces(result, "Part::GeomPlane", lambda f: abs(f.CenterOfMass.x - 14) < 1e-9)
        self.assertEqual(len(end), 1)
        self.assertAlmostEqual(end[0].Area, 4.07940, delta=2e-4)

    def testTallWallsStayOccts(self):
        # Walls 3 high: OCCT builds it, as Onshape's (2258.38970, 13 faces)
        body, edges = self.body(3.0)
        result = body.makeChamfer(1.0, edges)
        self.assertTrue(result.isValid())
        self.assertAlmostEqual(result.Volume, 2258.38970, delta=2e-4)
        self.assertAlmostEqual(result.Area, 1639.25693, delta=2e-4)
        self.assertEqual(len(result.Faces), 13)

    def testSteppedSlotIsRefused(self):
        # The slot 1 taller from x 10 on: the line's wall steps, and the low top's plane would clip
        # its fill under the taller wall too. No Onshape fact: refused
        body, edges = self.body(0.9662, step=10)
        with self.assertRaises(Exception):
            body.makeChamfer(1.0, edges)

    def testEndLinePickedTooIsRefused(self):
        # The slot's end line x 14 picked too (skeptic A3b-R2-1): the end corner's miter belongs to
        # the end line's tool, clipped only over its own wall, and half of it would stand above the
        # boss top (zmax 4.0 at h 0.5). No Onshape fact: refused
        body, edges = self.body(0.5)
        end = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomLine"
            and all(abs(v.Point.z - 3) < 1e-9 and abs(v.Point.x - 14) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(end), 1)
        for dress in (body.makeChamfer, body.makeFillet):
            with self.assertRaises(Exception):
                dress(1.0, edges + end)


class DPocketCornerTest(unittest.TestCase):
    """ops#888 A3b, designed (skeptic A3b-R2-2): a block 24 x 24 x 5 with a D-shaped pocket of depth
    h, the disk r 6 about the z axis cut by the chord y = w, its seam turned away from the arc's
    ends. The floor's arc and chord meet at two concave corners reflex in the material, the same
    pair of fills at both. A chamfer or fillet c on both, with walls lower than c: the fills,
    clipped by the block top, meet along their intersection at each corner, and the pair's overlap
    outside the base is counted once. The reference: the base united with the arc's fill (its
    section revolved a whole turn) and the chord's (extruded past both corners), clipped by the top
    z 5."""

    def body(self, w, h):
        V = FreeCAD.Vector
        disk = Part.makeCylinder(6, h, V(0, 0, 5 - h))
        disk.rotate(V(0, 0, 0), V(0, 0, 1), 90)
        air = disk.common(Part.makeBox(40, 20 + w, 10, V(-20, -20, 0)))
        body = Part.makeBox(24, 24, 5, V(-12, -12, 0)).cut(air).removeSplitter()
        floor = [e for e in body.Edges if all(abs(v.Point.z - (5 - h)) < 1e-9 for v in e.Vertexes)]
        self.assertEqual(len(floor), 2)
        return body, floor

    def check(self, result, body, added):
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume - body.Volume, added, delta=5e-5)
        self.assertLess(result.optimalBoundingBox().ZMax, 5 + 1e-6)
        self.assertEqual(len(result.Faces), 9)

    def testChamfer(self):
        body, floor = self.body(2, 0.5)
        # The reference adds 11.865546; the two fills overlap by 0.609584 outside the base
        self.check(body.makeChamfer(1.0, floor), body, 11.865546)

    def testFillet(self):
        body, floor = self.body(4, 0.5)
        self.check(body.makeFillet(1.0, floor), body, 6.749786)


class NotchedDPocketCornerTest(unittest.TestCase):
    """ops#883 C, designed (the form of NS44 Vial Well Atrium #136): DPocketCornerTest's block with
    a tall-walled D pocket, depth 3, and a notch cut into the chord's wall from the top, 2 wide
    about x = 0, its bottom round, r 1 about an axis across the wall, its lowest point sill above
    the floor, nearer than the dress-up c = 1. The floor's arc and chord meet at two corners
    reflex in the material. OCCT's result is valid and refused there; Onshape's (measured on
    #136, 48 faces, area to 1e-10): the fills meet along their intersection, and the chord's is
    kept over its wall, the notch run on through it. The reference: the base united with the
    arc's fill (its section revolved a whole turn) and the chord's (extruded past both corners),
    less the notch run on"""

    W, H, C = 2.0, 3.0, 1.0

    def section(self, kind):
        """The fill's section in the XZ plane, x the distance from the wall, z the height"""
        V, c = FreeCAD.Vector, self.C
        if kind == "chamfer":
            return Part.Face(Part.makePolygon([V(0, 0, 0), V(c, 0, 0), V(0, 0, c), V(0, 0, 0)]))
        square = Part.Face(Part.makePolygon([V(0, 0, 0), V(c, 0, 0), V(c, 0, c), V(0, 0, c), V(0, 0, 0)]))
        return square.cut(Part.Face(Part.Wire(Part.makeCircle(c, V(c, 0, c), V(0, 1, 0)))))

    def pocket(self):
        V = FreeCAD.Vector
        disk = Part.makeCylinder(6, self.H, V(0, 0, 5 - self.H))
        disk.rotate(V(0, 0, 0), V(0, 0, 1), 90)
        air = disk.common(Part.makeBox(40, 20 + self.W, 10, V(-20, -20, 0)))
        return Part.makeBox(24, 24, 5, V(-12, -12, 0)).cut(air).removeSplitter()

    def notch(self, sill):
        V = FreeCAD.Vector
        z = 5 - self.H + sill + 1
        return Part.makeCylinder(1, 4, V(0, self.W - 1, z), V(0, 1, 0)).fuse(
            Part.makeBox(2, 4, 10, V(-1, self.W - 1, z))
        ).removeSplitter()

    def body(self, sill):
        body = self.pocket().cut(self.notch(sill)).removeSplitter()
        floor = [e for e in body.Edges if all(abs(v.Point.z - (5 - self.H)) < 1e-9 for v in e.Vertexes)]
        self.assertEqual(len(floor), 2)
        return body, floor

    def reference(self, kind, sill):
        V, floor = FreeCAD.Vector, 5 - self.H
        arc = self.section(kind).mirror(V(0, 0, 0), V(1, 0, 0))
        arc.translate(V(6, 0, floor))
        arc = arc.revolve(V(0, 0, 0), V(0, 0, 1), 360).Solids[0]
        chord = self.section(kind)
        chord.rotate(V(0, 0, 0), V(0, 0, 1), -90)
        chord.translate(V(-12, self.W, floor))
        chord = chord.extrude(V(24, 0, 0))
        block = Part.makeBox(24, 24, 5, V(-12, -12, 0))
        return self.pocket().fuse([arc, chord]).common(block).cut(self.notch(sill))

    def check(self, kind, sill, delta):
        body, floor = self.body(sill)
        result = getattr(body, "makeFillet" if kind == "fillet" else "makeChamfer")(self.C, floor)
        reference = self.reference(kind, sill)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, reference.Volume, delta=delta)
        self.assertLess(result.cut(reference).Volume + reference.cut(result).Volume, delta)
        self.assertLess(result.common(self.notch(sill)).Volume, 1e-9)

    def testFillet(self):
        # The revolved round's volume is good to about 5e-6 (DPocketCornerTest's tall form)
        self.check("fillet", 0.5, 1e-5)

    def testChamfer(self):
        self.check("chamfer", 0.5, 1e-6)

    def testFilletNotchNearerTheFloor(self):
        self.check("fillet", 0.3, 1e-5)


class FillOverALedgeTest(unittest.TestCase):
    """ops#898 cause A, designed: a keyhole boss (the circle r 7 about the z axis and the slot |y| < 2
    to x = 12, height 3) on a slab z -2..0 whose top is the ledge round the boss's foot; the slab's
    sides drop square from the ledge. A chamfer of 1.5 at the foot (the slot's two lines and the
    circle's arc, which meet at the outline's concave corners, reflex in the material). Where the
    ledge is narrower than the chamfer under a line (its outer edge parallel or tapering) or under
    the arc, OCCT fails, and Onshape keeps the fills of a wide ledge only over the ledge: its sides
    grow, and the ledge is consumed where it is narrower (the census rows' area and volume to 1e-6,
    ops#898). The reference: OCCT's chamfer on a wide ledge, its added material kept over this
    ledge's footprint."""

    R, S, L, H, T, C = 7.0, 2.0, 12.0, 3.0, 2.0, 1.5

    def body(self, arc, line0, line1, end=2.0):
        """The ledge as wide as arc round the circle, and line0 at x = 0 to line1 at the slab's end
        beside the slot's lines"""
        V = FreeCAD.Vector
        R, S, L, H, T = self.R, self.S, self.L, self.H, self.T
        boss = Part.makeCylinder(R, H).fuse(Part.makeBox(L, 2 * S, H, V(0, -S, 0))).removeSplitter()
        e = L + end
        outline = [V(0, -(S + line0), -T), V(e, -(S + line1), -T), V(e, S + line1, -T), V(0, S + line0, -T)]
        slab = Part.makeCylinder(R + arc, T, V(0, 0, -T)).fuse(
            Part.Face(Part.makePolygon(outline + [outline[0]])).extrude(V(0, 0, T))
        ).removeSplitter()
        return slab.fuse(boss).removeSplitter(), slab

    def picks(self, body, arc=True, lines=True):
        picked = []
        for e in body.Edges:
            if any(abs(v.Point.z) > 1e-9 for v in e.Vertexes):
                continue
            if arc and e.Curve.TypeId == "Part::GeomCircle" and abs(e.Curve.Radius - self.R) < 1e-9:
                picked.append(e)
            if (
                lines
                and e.Curve.TypeId == "Part::GeomLine"
                and all(abs(abs(v.Point.y) - self.S) < 1e-9 and v.Point.x > 1 for v in e.Vertexes)
            ):
                picked.append(e)
        return picked

    def footprint(self, slab, height):
        bottom = [f for f in slab.Faces if abs(f.CenterOfMass.z + self.T) < 1e-9]
        self.assertEqual(len(bottom), 1)
        return bottom[0].extrude(FreeCAD.Vector(0, 0, height))

    def reference(self, body, slab, arc=True, lines=True):
        wide, _ = self.body(4, 4, 4)
        added = wide.makeChamfer(self.C, self.picks(wide, arc, lines)).cut(wide)
        return body.fuse(added.common(self.footprint(slab, 10))).removeSplitter()

    def check(self, widths, faces, arc=True, lines=True):
        body, slab = self.body(*widths)
        result = body.makeChamfer(self.C, self.picks(body, arc, lines))
        reference = self.reference(body, slab, arc, lines)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, reference.Volume, delta=1e-6)
        self.assertAlmostEqual(result.Area, reference.Area, delta=1e-6)
        self.assertEqual(len(result.Faces), faces)
        self.assertEqual(len(reference.Faces), faces)
        # Nothing past the ledge
        self.assertLess(result.cut(self.footprint(slab, 10)).Volume, 1e-9)
        return result

    def testArcAtTheLimitLinesNarrowParallel(self):
        # The ledge consumed beside the lines, the arc's strip landing on its rim
        self.assertAlmostEqual(self.check((1.5, 1.3, 1.3), 15).Volume, 1117.318612, delta=1e-5)

    def testArcAtTheLimitLinesNarrowTapering(self):
        # The census rows' form: the ledge's outer edge beside each line not parallel to it
        self.assertAlmostEqual(self.check((1.5, 1.3, 1.42), 15).Volume, 1119.787129, delta=1e-5)

    def testArcNarrowLinesWide(self):
        self.assertAlmostEqual(self.check((1.2, 3.0, 3.0), 15).Volume, 1135.537223, delta=1e-5)

    def testArcAndLinesNarrow(self):
        self.assertAlmostEqual(self.check((1.2, 1.3, 1.42), 15).Volume, 1090.429422, delta=1e-5)

    def testArcAloneNarrow(self):
        self.assertAlmostEqual(self.check((1.2, 3.0, 3.0), 12, lines=False).Volume, 1118.869893, delta=1e-5)

    def testWideLedgeStaysOccts(self):
        body, _ = self.body(3, 3, 3)
        result = body.makeChamfer(self.C, self.picks(body))
        self.assertAlmostEqual(result.Volume, 1305.093836, delta=1e-5)
        self.assertEqual(len(result.Faces), 15)


class FillOverARingLedgeTest(unittest.TestCase):
    """ops#898 cause A, designed: a cylinder r 7, height 3, on a disk r 7 + w, 2 thick: a ledge of
    width w round its foot, whose rim drops square from it. A chamfer or fillet c = 1.5 at the foot,
    wider than the ledge (w = 1.2): Onshape's fill is the plain one kept over the ledge, the rim's
    cylinder grows over its cut (one face), and the ledge is consumed. Closed form: the fill's
    section revolved over r 7..7 + w"""

    R, C = 7.0, 1.5

    def body(self, width, lean=0.0):
        V = FreeCAD.Vector
        boss = Part.makeCylinder(self.R, 3)
        if lean:
            disk = Part.makeCone(self.R + width + lean, self.R + width, 2, V(0, 0, -2))
        else:
            disk = Part.makeCylinder(self.R + width, 2, V(0, 0, -2))
        body = disk.fuse(boss).removeSplitter()
        foot = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - self.R) < 1e-9
            and all(abs(v.Point.z) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(foot), 1)
        return body, foot

    def added(self, width, height):
        """The fill's section, height(s) high at s from the boss's wall, revolved over 0..width"""
        return gauss_legendre(lambda s: 2 * math.pi * (self.R + s) * height(s), 0, width)

    def check(self, result, body, added):
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume - body.Volume, added, delta=1e-6)
        # Nothing past the rim, and the rim one cylinder, grown over the fill's cut
        self.assertLess(result.optimalBoundingBox().XMax, self.R + 1.2 + 1e-6)
        self.assertEqual(len(result.Faces), 5)
        rims = [
            f
            for f in result.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - (self.R + 1.2)) < 1e-9
        ]
        self.assertEqual(len(rims), 1)

    def testChamfer(self):
        body, foot = self.body(1.2)
        c = self.C
        # 2 pi (R c w - R w^2/2 + c w^2/2 - w^3/3) = 2 pi 8.064
        self.assertAlmostEqual(self.added(1.2, lambda s: c - s), 2 * math.pi * 8.064, delta=1e-9)
        self.check(body.makeChamfer(c, foot), body, 2 * math.pi * 8.064)

    def testFillet(self):
        body, foot = self.body(1.2)
        R, c, w = self.R, self.C, 1.2

        # The round's section is c - sqrt(c^2 - u^2) high at u = c - s: the square less the disk's
        # part, integrated exactly (its slope is infinite at the wall)
        def disk(u):
            return (R + c) * (u * math.sqrt(c * c - u * u) + c * c * math.asin(u / c)) / 2 + (c * c - u * u) ** 1.5 / 3

        added = 2 * math.pi * (c * (R * w + w * w / 2) - (disk(c) - disk(c - w)))
        self.check(body.makeFillet(c, foot), body, added)

    def testAtTheLimitStaysOccts(self):
        body, foot = self.body(1.5)
        c = self.C
        result = body.makeChamfer(c, foot)
        self.assertAlmostEqual(result.Volume - body.Volume, self.added(1.5, lambda s: c - s), delta=1e-6)

    def testRimLeaningOutIsRefused(self):
        # The rim a cone, leaning out under the ledge: where Onshape trims is not measured. Refused
        body, foot = self.body(1.2, lean=0.8)
        for dress in (body.makeChamfer, body.makeFillet):
            with self.assertRaisesRegex(Exception, "kept over its face: .*face beyond is not square"):
                dress(self.C, foot)


class FillPastANotchTest(unittest.TestCase):
    """ops#898 cause A, designed (the form of FGC-NS44 #113, where an earlier blend cut the wall
    away beside the picked edge): a floor plate x -2..10, y 0..20, z -2..0, with a wall x -2..0,
    z 0..5 on it, and a notch cut down into the wall from its top, 4 wide (y 8..12), its bottom
    round, r 2 about the line y = 10, z = sill + 2. A chamfer of 1 at the wall's foot, the notch's
    sill at 0.6, below the chamfer's top: the fill keeps only what stands in front of the wall,
    the notch's own cylinder growing over its cut. Closed form: the plain fill (10 mm3) less its
    part in front of the notch. A closed window instead (a hole in the wall's face, ops#883 H): the
    hole runs on through the fill"""

    def body(self, sill, window=False, radius=2.0):
        V = FreeCAD.Vector
        plate = Part.makeBox(12, 20, 2, V(-2, 0, -2))
        wall = Part.makeBox(2, 20, 5, V(-2, 0, 0))
        hole = Part.makeCylinder(radius, 4, V(-3, 10, sill + radius), V(1, 0, 0))
        if not window:
            hole = hole.fuse(Part.makeBox(4, 4, 5, V(-3, 8, sill + 2))).removeSplitter()
        body = plate.fuse(wall).removeSplitter().cut(hole)
        foot = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomLine"
            and all(abs(v.Point.x) < 1e-9 and abs(v.Point.z) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(foot), 1)
        return body, foot

    def testChamferPastTheSill(self):
        body, foot = self.body(0.6)
        result = body.makeChamfer(1.0, foot)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        # In front of the notch: the fill's depth 1 - z over the window's chord 2 sqrt(4 - t^2) at
        # t = z - 2.6, integrated exactly over t -2..-1.6
        def chord(t):
            return 2 * (-1.6 * (t * math.sqrt(4 - t * t) + 4 * math.asin(t / 2)) / 2 + (4 - t * t) ** 1.5 / 3)

        window = chord(-1.6) - chord(-2)
        self.assertAlmostEqual(result.Volume - body.Volume, 10 - window, delta=1e-6)
        front = Part.makeCylinder(2, 2, FreeCAD.Vector(0, 10, 2.6), FreeCAD.Vector(1, 0, 0))
        self.assertLess(result.common(front).Volume, 1e-9)
        windows = [f for f in result.Faces if f.Surface.TypeId == "Part::GeomCylinder"]
        self.assertEqual(len(windows), 1)

    # A closed window (ops#883 H): a hole r 0.5 through the wall about y = 10, z = 1, its rim 0.5
    # above the floor, inside the fill's strip (OCCT fails on it, fillet and chamfer)
    WINDOW = (0.5, 1.0)

    def window_in_fill(self, depth):
        """What of the fill stands in front of the window, the hole run on through the fill, the
        fill depth(z) deep at height z: with z = zc - r cos(a), the chord 2 r sin(a) and dz =
        r sin(a) da, a smooth integrand over a 0..acos((zc - 1) / r) (z from the rim to 1)"""
        r, zc = self.WINDOW
        return gauss_legendre(
            lambda a: depth(zc - r * math.cos(a)) * 2 * r * r * math.sin(a) ** 2,
            0,
            math.acos((zc - 1) / r),
        )

    def check_window(self, result, body, added):
        r, zc = self.WINDOW
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume - body.Volume, added, delta=1e-6)
        # The hole runs on through the fill: nothing of the result in its cylinder, and its wall
        # grown over the fill's cut. (Onshape's wall is one face; here the cut's piece stays a face
        # of its own, on the coaxial cylinder of the other sense: debt, ops#883)
        hole = Part.makeCylinder(r, 4, FreeCAD.Vector(-3, 10, zc), FreeCAD.Vector(1, 0, 0))
        self.assertLess(result.common(hole).Volume, 1e-9)
        walls = [
            f
            for f in result.Faces
            if f.Surface.TypeId == "Part::GeomCylinder" and abs(f.Surface.Radius - r) < 1e-9
        ]
        self.assertAlmostEqual(sum(f.Area for f in walls), self.wall_area(), delta=1e-6)

    def wall_area(self):
        """The hole's wall through the wall (2 pi r 2) and on through the fill: over a 0..pi, the
        fill's depth at height zc - r cos(a), times r da (pi r, from either side)"""
        r, zc = self.WINDOW
        return 2 * math.pi * r * 2 + 2 * gauss_legendre(
            lambda a: self.depth(zc - r * math.cos(a)) * r, 0, math.acos((zc - 1) / r)
        )

    def window_body(self):
        r, zc = self.WINDOW
        return self.body(zc - r, window=True, radius=r)

    def testChamferThroughAClosedWindow(self):
        # ops#883 H (HNY-DSN Case #104, Onshape's capture to 1e-8 in area): the hole runs on
        # through the fill
        body, foot = self.window_body()
        self.depth = lambda z: 1 - z
        window = self.window_in_fill(self.depth)
        self.check_window(body.makeChamfer(1.0, foot), body, 10 - window)

    def testFilletThroughAClosedWindow(self):
        body, foot = self.window_body()
        # The round r 1 about the line x = 1, z = 1: the fill 1 - sqrt(1 - (1 - z)^2) deep at z,
        # (1 - pi / 4) in section, 20 long
        self.depth = lambda z: 1 - math.sqrt(1 - (1 - z) ** 2)
        window = self.window_in_fill(self.depth)
        self.check_window(body.makeFillet(1.0, foot), body, 20 * (1 - math.pi / 4) - window)

    def testSillAboveTheChamferStaysOccts(self):
        body, foot = self.body(1.4)
        result = body.makeChamfer(1.0, foot)
        self.assertAlmostEqual(result.Volume - body.Volume, 10.0, delta=1e-6)


class FillOverALedgeRefusalsTest(unittest.TestCase):
    """ops#898 cause A, what keeps a refusal (review of PR 484, S4): a cylinder r 7, h high, on
    a disk r 8.2 (a ledge 1.2 wide round its foot, narrower than the chamfer or fillet of 1.5), with
    something on the ledge's rim that Onshape's rule (the plain fill kept over the ledge, the rim
    dropping square) does not cover: no Onshape fact, so the dress-up stays an error"""

    R, W, C = 7.0, 1.2, 1.5

    def body(self, extra=None, height=3.0):
        V = FreeCAD.Vector
        body = Part.makeCylinder(self.R + self.W, 2, V(0, 0, -2)).fuse(Part.makeCylinder(self.R, height))
        if extra is not None:
            body = body.fuse(extra)
        body = body.removeSplitter()
        foot = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - self.R) < 1e-9
            and all(abs(v.Point.z) < 1e-9 for v in e.Vertexes)
        ]
        self.assertEqual(len(foot), 1)
        return body, foot

    def refused(self, body, foot, pattern, dresses=("makeChamfer", "makeFillet")):
        for dress in dresses:
            with self.assertRaisesRegex(Exception, "kept over its face: .*" + pattern):
                getattr(body, dress)(self.C, foot)

    def testPlainLedgeBuilds(self):
        # The control: the same ledge with nothing on it builds (FillOverARingLedgeTest)
        body, foot = self.body()
        self.assertTrue(body.makeChamfer(self.C, foot).isValid())

    def testStudOnTheRim(self):
        # Skeptic r1, find 1: a stud lower than the fill, standing on the rim and over the drop
        V = FreeCAD.Vector
        stud = Part.makeBox(0.8, 0.6, 0.3, V(self.R + self.W - 0.4, -0.3, 0))
        body, foot = self.body(stud)
        # The round on it builds (review of PR 484, S3: one air piece along the drop also stands
        # over the stud; Onshape's result there is not measured): debt on ops#898
        self.refused(body, foot, "a fused tool trimmed over its face stands in the air", ("makeChamfer",))

    def testCurbAlongTheRim(self):
        # A wall rising from the ledge along its whole rim, lower than the fill
        V = FreeCAD.Vector
        curb = Part.makeCylinder(self.R + self.W, 0.3).cut(Part.makeCylinder(self.R + self.W - 0.2, 0.3))
        body, foot = self.body(curb)
        self.refused(body, foot, "runs past its face into the air along no edge of it")

    def testCurbOnPartOfTheRim(self):
        # A curb lower than the fill on part of the rim, beside a square drop on the rest (the form
        # of S3, whose air pieces here stay apart: refused)
        V = FreeCAD.Vector
        ring = Part.makeCylinder(self.R + self.W, 0.3).cut(Part.makeCylinder(self.R + self.W - 0.2, 0.3))
        curb = ring.common(Part.makeBox(20, 20, 1, V(0, 0, -0.5)))
        body, foot = self.body(curb)
        # The round there stops earlier: OCCT's result is not valid
        self.refused(body, foot, "stands in the air", ("makeChamfer",))


class FillToARimCuspTest(unittest.TestCase):
    """ops#898 cause B, designed (the form of FGC-FM44 #152): a disk r 10, z -2..0, and on its rim a
    thin curved wall, 1.6 thick (r 8.4..10 over |angle| < a, 3 high), its ends fully rounded
    (cylinders r 0.8 about r 9.2 at +-a), its outer side flush with the disk's. A fillet at the
    wall's inner foot (the inner arc, in two pieces at its seam, and the end rounds' foot arcs,
    each from its tangent point with the inner arc round to the rim): each end arc meets the
    disk's rim tangentially, so the floor narrows to nothing there (a cusp), and the end face is
    the disk's cylinder. OCCT fails; Onshape's fill is each arc's plain fill kept over the floor
    (FGC-FM44 #152: area to 3e-6 mm2). Closed form: the inner arc's fill by Pappus, and each end
    round's fill integrated over its half turn, within the rim"""

    RO, T, H = 10.0, 1.6, 3.0

    def body(self, angle):
        V = FreeCAD.Vector
        a = math.radians(angle)
        ri = self.RO - self.T
        ring = Part.makeCylinder(self.RO, self.H).cut(Part.makeCylinder(ri, self.H))
        far = 2 * self.RO
        corners = [V(0, 0, 0), V(far * math.cos(a), -far * math.sin(a), 0), V(far, 0, 0)]
        corners += [V(far * math.cos(a), far * math.sin(a), 0), V(0, 0, 0)]
        wall = ring.common(Part.Face(Part.makePolygon(corners)).extrude(V(0, 0, self.H)))
        rc = self.RO - self.T / 2
        for side in (-1, 1):
            centre = V(rc * math.cos(side * a), rc * math.sin(side * a), 0)
            wall = wall.fuse(Part.makeCylinder(self.T / 2, self.H, centre))
        disk = Part.makeCylinder(self.RO, 2, V(0, 0, -2))
        body = disk.fuse(wall).removeSplitter()
        foot = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and all(abs(v.Point.z) < 1e-9 for v in e.Vertexes)
            and (abs(e.Curve.Radius - ri) < 1e-9 or abs(e.Curve.Radius - self.T / 2) < 1e-9)
        ]
        self.assertEqual(len(foot), 4)
        return body, foot

    def added(self, angle, r):
        a = math.radians(angle)
        re = self.T / 2
        rc = self.RO - re
        ri = self.RO - self.T

        def height(d):
            # The fill's height at d from the wall, 0 <= d <= r
            return r - math.sqrt(max(r * r - (r - d) ** 2, 0.0))

        # By d = s^2: the height goes as the root of d at the wall, which Gauss's rule does not
        inner = 2 * a * gauss_legendre(lambda s: height(s * s) * (ri - s * s) * 2 * s, 0, math.sqrt(r))

        # An end round, its centre at rc on the x axis: phi 0 at its tangent point with the inner
        # arc (towards the axis), pi at the cusp on the rim, through the wall's far side
        def reach(phi):
            # How far from the centre the rim is, along phi
            dx = -math.cos(phi)
            b = rc * dx
            return -b + math.sqrt(b * b - (rc * rc - self.RO**2))

        def slice_(phi):
            top = min(re + r, reach(phi))
            if top <= re:
                return 0.0
            return gauss_legendre(lambda s: height(s * s) * (re + s * s) * 2 * s, 0, math.sqrt(top - re))

        lo, hi = 0.0, math.pi
        for _ in range(100):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if reach(mid) > re + r else (lo, mid)
        end = gauss_legendre(slice_, 0, lo) + gauss_legendre(slice_, lo, math.pi)
        return inner + 2 * end

    def check(self, angle, r, faces):
        body, foot = self.body(angle)
        result = body.makeFillet(r, foot)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        # The added material on its own: the bodies' volumes differ in OCCT's precision on the disk
        self.assertAlmostEqual(result.cut(body).Volume, self.added(angle, r), delta=1e-5)
        self.assertLess(body.cut(result).Volume, 1e-9)
        rim = Part.makeCylinder(self.RO, 10, FreeCAD.Vector(0, 0, -5))
        self.assertLess(result.cut(rim).Volume, 1e-9)
        # Debt (ops#898): each end round is a torus and a B-spline piece of it at the cusp, and the
        # inner arc's round stays in its two pieces (Onshape: one face per arc)
        self.assertEqual(len(result.Faces), faces)
        return result

    def testRoundAsWideAsTheWall(self):
        self.check(40.0, 0.8, 13)

    def testSmallerRoundLongerWall(self):
        self.check(70.0, 0.5, 13)

    def testChamferIsRefused(self):
        # A chamfer ending on a face that is not a plane is not known from Onshape
        body, foot = self.body(40.0)
        with self.assertRaises(Exception):
            body.makeChamfer(0.8, foot)


def lobed_plate(noise=True):
    """ops#925: a ring plate (radii 2 and 9, 2 thick, under z 0) carrying four ring-sector lobes
    between radii 4 and 5, 60 degrees wide, 2 high; with `noise` turned half a turn about X and
    back, which leaves sin(pi) = 1.2e-16 in its axes, as a Body's placement does"""
    def polar(r, a):
        return V(r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), 0)

    shape = Part.makeCylinder(9, 2, V(0, 0, -2)).cut(Part.makeCylinder(2, 2, V(0, 0, -2)))
    for a0 in (15.0, 105.0, 195.0, 285.0):
        a1, am = a0 + 60, a0 + 30
        edges = [
            Part.Arc(polar(4, a0), polar(4, am), polar(4, a1)).toShape(),
            Part.makeLine(polar(4, a1), polar(5, a1)),
            Part.Arc(polar(5, a1), polar(5, am), polar(5, a0)).toShape(),
            Part.makeLine(polar(5, a0), polar(4, a0)),
        ]
        shape = shape.fuse(Part.Face(Part.Wire(edges)).extrude(V(0, 0, 2)))
    shape = shape.removeSplitter()
    if noise:
        m = FreeCAD.Rotation(V(1, 0, 0), 180).toMatrix()
        shape = shape.transformed(m, True).transformed(m, True)
    return shape


def lobe_feet(shape):
    """The lobes' 16 foot edges on the plate (z 0, between radii 4 and 5)"""
    return [
        e
        for e in shape.Edges
        if abs(e.BoundBox.ZMin) < 1e-9
        and abs(e.BoundBox.ZMax) < 1e-9
        and all(4 - 1e-6 <= math.hypot(v.X, v.Y) <= 5 + 1e-6 for v in e.Vertexes)
    ]


class CornerBandRetryTest(unittest.TestCase):
    """A fillet along the foot of ring-sector lobes: at each plan corner a line's round and an
    arc's round run on past the corner and meet in a mitre. In narrow bands of radius OCCT's
    result is invalid there and the exact construction refuses the corner; the same selection in
    the reverse order builds (ops#925, scripts/repro_925_fillet_corner_band.py). Expected by
    geometry: 16 new faces (8 cylinders, 8 tori), 16 mitre edges, a valid solid."""

    setUp = InvalidDressUpTest.setUp
    tearDown = InvalidDressUpTest.tearDown

    def testInvalidCornerBuildsInTheReverseOrder(self):
        base = lobed_plate()
        self.assertEqual(len(lobe_feet(base)), 16)
        for radius in (0.588, 0.55):  # inside a band; and a control outside
            with self.subTest(radius=radius):
                fillet = filleted_in_a_body(self.doc, base, lobe_feet, radius)
                self.assertTrue(fillet.isValid(), fillet.getStatusString())
                self.assertTrue(fillet.Shape.isValid())
                self.assertEqual(len(fillet.Shape.Faces) - len(base.Faces), 16)
                mitres = [
                    e for e in fillet.Shape.Edges if type(e.Curve).__name__ not in ("Line", "Circle")
                ]
                self.assertEqual(len(mitres), 16)
                # each mitre lies on both its rounds: exactly for the control; inside the band the
                # reverse order gives OCCT's in-band mitre, measured 3.1e-4 mm off (debt, ops#925
                # fixes 2 and 3, the exact mitre: review pri931-r3 T1, coordinator's ruling)
                shape = fillet.Shape
                off = 0.0
                for e in mitres:
                    faces = shape.ancestorsOfType(e, Part.Face)
                    self.assertEqual(len(faces), 2)
                    step = (e.LastParameter - e.FirstParameter) / 20
                    for k in range(21):
                        point = Part.Vertex(e.valueAt(e.FirstParameter + k * step))
                        off = max(off, max(point.distToShape(f)[0] for f in faces))
                self.assertLess(off, 1e-3 if radius > 0.58 else 1e-6, radius)


class SeveralSolidsTest(unittest.TestCase):
    """ops#937: a base of several solids (a Body whose shape holds several parts, as FGC-NS88's
    Labyrinth after an extrude of regions as new parts). Where OCCT fails, the construction runs on
    the solid that owns the picked edges, and the other solids stay as they are: Onshape dresses
    up each part on its own. Designed: testFullRound's wall (a full round, which OCCT refuses) and a
    cube beside it, in one compound"""

    def base(self):
        wall = Part.makeBox(30, 4, 20)
        cube = Part.makeBox(10, 10, 10, V(50, 0, 0))
        base = Part.makeCompound([wall, cube])
        base.Tag = 1
        return base

    def check(self, result, wall_volume, wall_faces):
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 2)
        wall, cube = sorted(result.Solids, key=lambda s: s.BoundBox.XMin)
        self.assertAlmostEqual(wall.Volume, wall_volume, delta=1e-6 * wall_volume)
        self.assertEqual(len(wall.Faces), wall_faces)
        self.assertFalse([face for face in wall.Faces if face.Area < 1e-7])
        # The cube is left as it was
        self.assertAlmostEqual(cube.Volume, 1000, delta=1e-9)
        self.assertEqual(len(cube.Faces), 6)
        self.assertTrue(cube.BoundBox.isInside(V(55, 5, 5)))
        self.assertAlmostEqual(cube.BoundBox.XMin, 50, delta=1e-9)
        self.assertAlmostEqual(cube.BoundBox.ZMax, 10, delta=1e-9)

    def testFullRoundOnOneSolid(self):
        base = self.base()
        result = base.makeFillet(2, top_edges(base))
        # The two rounds are one cylinder, as Onshape's (ops#900): 6 faces, not 7
        self.check(result, 2400 - 2 * fillet_section(2) * 30, 6)

    def testPicksOnTwoSolidsAreRefused(self):
        # One construction per solid is not built: OCCT's error stands
        base = self.base()
        edges = top_edges(base) + [edge_between(base, (50, 0, 10), (60, 0, 10))]
        with self.assertRaises(Exception):
            base.makeFillet(2, edges)

    def testOneSolidUnchanged(self):
        # The control: a single solid builds as before
        wall = Part.makeBox(30, 4, 20)
        result = wall.makeFillet(2, top_edges(wall))
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume, 2400 - 2 * fillet_section(2) * 30, delta=1e-3)


class ConeFootTest(unittest.TestCase):
    """ops#935: a round on the whole circle where a cone stands on a plane normal to its axis (HNY
    DSH Nest Insert #30's stalactites). The fill is the section between the plane, the cone's line
    and the arc tangent to both, revolved about the axis; where two such fills overlap, Onshape's
    result is their union (measured on the capture to 1e-4 mm2). Designed: cones of foot radius 4,
    top radius 1 and height 6 on a 40 x 20 x 4 plate, rounded by 2, so each fill reaches
    2 / tan(alpha / 2) beyond its foot; two cones whose feet are 1.8 apart, which their fills'
    reaches overlap and neither fill reaches the other cone"""

    R, TOP, H, T, r = 4.0, 1.0, 6.0, 4.0, 2.0

    def base(self, centres):
        plate = Part.makeBox(40, 20, self.T)
        cones = [Part.makeCone(self.R, self.TOP, self.H, V(x, 10, self.T)) for x in centres]
        body = plate.fuse(cones).removeSplitter()
        body.Tag = 1
        feet = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - self.R) < 1e-9
            and abs(e.BoundBox.ZMax - self.T) < 1e-9
        ]
        self.assertEqual(len(feet), len(centres))
        return body, feet

    def fill(self, x):
        """The fill about the cone at x: its section in the meridian plane y = 10, revolved"""
        up = V(self.TOP - self.R, 0, self.H).normalize()
        out = V(1, 0, 0)
        alpha = math.acos(out.dot(up))
        t = self.r / math.tan(alpha / 2)
        corner = V(x + self.R, 10, self.T)
        a = corner + out * t
        b = corner + up * t
        bisector = (out + up).normalize()
        centre = corner + bisector * (self.r / math.sin(alpha / 2))
        middle = centre - bisector * self.r
        wire = Part.Wire(
            [Part.makeLine(corner, a), Part.Arc(a, middle, b).toShape(), Part.makeLine(b, corner)]
        )
        return Part.Face(wire).revolve(V(x, 10, 0), V(0, 0, 1), 360), alpha, t

    def pappus(self):
        """The fill's volume in closed form: the section, the kite corner-end-centre-end minus the
        sector at the centre, revolved by Pappus about the axis"""
        _, alpha, t = self.fill(0)
        kite = self.r * t
        theta = math.pi - alpha
        sector = self.r * self.r * theta / 2
        up = (self.TOP - self.R) / math.hypot(self.TOP - self.R, self.H)
        dc = self.r / math.sin(alpha / 2)
        bis_x = (1 + up) / math.hypot(1 + up, math.sqrt(1 - up * up))
        # Radial centroids from the corner: the kite's (its four corners: 0, t, centre, t up)
        kite_x = (t + t * up + 2 * dc * bis_x) / 6
        sector_x = dc * bis_x - 4 * self.r * math.sin(theta / 2) / (3 * theta) * bis_x
        area = kite - sector
        centroid = (kite_x * kite - sector_x * sector) / area
        return area * 2 * math.pi * (self.R + centroid)

    def testOneConeIsPappus(self):
        body, feet = self.base([20])
        result = body.makeFillet(self.r, feet)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        self.assertAlmostEqual(result.Volume - body.Volume, self.pappus(), delta=1e-6 * body.Volume)

    def testOverlappingFillsAreTheirUnion(self):
        centres = [15.0, 15.0 + 2 * self.R + 1.8]
        _, _, t = self.fill(0)
        self.assertTrue(t < 1.8 < 2 * t)
        body, feet = self.base(centres)
        result = body.makeFillet(self.r, feet)
        self.assertTrue(result.isValid())
        self.assertEqual(len(result.Solids), 1)
        fills = [self.fill(x)[0] for x in centres]
        union = fills[0].fuse(fills[1])
        self.assertLess(fills[0].common(fills[1]).Volume, union.Volume)
        self.assertGreater(fills[0].common(fills[1]).Volume, 1e-3)
        self.assertAlmostEqual(result.Volume - body.Volume, union.Volume, delta=1e-6 * body.Volume)
        # The fills only: nothing of the body removed, nothing added beyond them
        self.assertLess(body.cut(result).Volume, 1e-7)
        self.assertLess(result.cut(body.fuse(union)).Volume, 1e-6)

    def testFillsReachingTheOtherFootAreRefused(self):
        # Feet 1.0 apart, nearer than a fill's reach (1.236): not known from Onshape (review of
        # fix935 r1, T2b), refused as before
        _, _, t = self.fill(0)
        self.assertTrue(1.0 < t)
        body, feet = self.base([15.0, 15.0 + 2 * self.R + 1.0])
        with self.assertRaises(Exception):
            body.makeFillet(self.r, feet)

    def testOverlappingCylinderFillsAreRefused(self):
        # Two bosses (cylinders) whose foot rounds overlap: not known from Onshape (T2a), refused
        # as before
        plate = Part.makeBox(40, 20, self.T)
        bosses = [Part.makeCylinder(self.R, self.H, V(x, 10, self.T)) for x in (15.0, 26.0)]
        body = plate.fuse(bosses).removeSplitter()
        feet = [
            e
            for e in body.Edges
            if e.Curve.TypeId == "Part::GeomCircle"
            and abs(e.Curve.Radius - self.R) < 1e-9
            and abs(e.BoundBox.ZMax - self.T) < 1e-9
        ]
        self.assertEqual(len(feet), 2)
        with self.assertRaises(Exception):
            body.makeFillet(self.r, feet)
