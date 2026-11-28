# SPDX-License-Identifier: LGPL-2.1-or-later

"""Refine merges two faces on one surface that it left split before (FreeCAD-CH ops#1044).

C. A cone, torus or sphere group bounded by an approximated edge (a fillet's): the merged face is
built on a copy of the surface, so the curves of its edges on it are projected again, and its area
moves off the group's by about the sum over the boundary edges of (gap of the curve on the surface
from the 3D curve, before and after) times the edge's length. The area test allowed only
1e-7 * area and refused a right merge. Designed model: two coaxial cones meeting in a crease at
radius 16 (a polygon revolved about Z), the crease filleted, then two wedges about the axis cut
away from the lower cone either side of its seam, so a strip of the lower cone is left across the
seam, bounded by the fillet's edge.

B. A B-spline wall symmetric about a mirror plane (a ruled loft of two symmetric arch sections) is
its own mirror image run backwards: a mirror fuse of its halves gives two faces whose poles are each
other's in reversed order. The uniter compared poles index for index only.

Expected, geometrically: each connected region of faces on one surface becomes one face (the
lower cone: the main part and the strip, two faces; the arch wall: one face), while walls on other surfaces (an arch
that is not symmetric, one moved off symmetry by 1e-4) stay apart; the refined shape is valid and
has the unrefined one's volume and area."""

import math
import unittest

import FreeCAD as App
import Part

V = App.Vector

LOWER_ANGLE = math.atan2(4, 6)  # the lower cone, (12, 0) to (16, 6) in XZ
ARCH = [(-6, 3), (-3, 6), (0, 7), (3, 6), (6, 3)]
PLACED = App.Placement(V(5, -3, 2), App.Rotation(V(1, 1, 0), 30))


def kinds(shape):
    counts = {}
    for face in shape.Faces:
        name = type(face.Surface).__name__
        counts[name] = counts.get(name, 0) + 1
    return counts


def relativelyEqual(a, b, tolerance=1e-6):
    return abs(a - b) <= tolerance * max(abs(a), abs(b), 1.0)


def doubleCone(fillet):
    """Two cones meeting in a crease at radius 16, the crease filleted by `fillet` (0: not)."""
    points = [V(0, 0, 0), V(12, 0, 0), V(16, 0, 6), V(10, 0, 14), V(0, 0, 14)]
    profile = Part.Face(Part.makePolygon(points + [points[0]]))
    solid = profile.revolve(V(0, 0, 0), V(0, 0, 1), 360)
    if fillet:
        crease = [
            e
            for e in solid.Edges
            if isinstance(e.Curve, Part.Circle) and abs(e.Curve.Radius - 16) < 1e-6
        ]
        assert len(crease) == 1, len(crease)
        solid = solid.makeFillet(fillet, crease)
    return solid


def sector(start, end):
    """The annular wedge between the angles `start` and `end` (radians) about Z, radii 8 to 30,
    over the lower cone's height (z -1 to 6)."""
    span = math.degrees(end - start)
    outer = Part.makeCylinder(30, 7, V(0, 0, -1), V(0, 0, 1), span)
    inner = Part.makeCylinder(8, 7, V(0, 0, -1), V(0, 0, 1), span)
    wedge = outer.cut(inner)
    wedge.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(start))
    return wedge


def strippedCone(fillet):
    """The double cone with two wedges cut away either side of the lower cone's seam: a strip of
    the lower cone from -0.08 to 0.08 rad is left across the seam."""
    return doubleCone(fillet).cut(sector(0.08, 0.6)).cut(sector(-0.6, -0.08))


def lowerConeFaces(shape):
    return [
        f
        for f in shape.Faces
        if isinstance(f.Surface, Part.Cone)
        and abs(abs(f.Surface.SemiAngle) - LOWER_ANGLE) < 1e-6
    ]


def archSection(z, scale, points=ARCH):
    """A spline through `points` (x, y) with y scaled, closed by three lines down to y = 0, at z."""
    through = [V(x, y * scale, z) for x, y in points]
    spline = Part.BSplineCurve()
    spline.interpolate(through)
    first, last = through[0], through[-1]
    return Part.Wire(
        [
            spline.toShape(),
            Part.makeLine(last, V(last.x, 0, z)),
            Part.makeLine(V(last.x, 0, z), V(first.x, 0, z)),
            Part.makeLine(V(first.x, 0, z), first),
        ]
    )


def archLoft(points=ARCH, top=0.7, height=12):
    """A ruled loft of the arch section at z = 0 and the same with its arch `top` as high above."""
    return Part.makeLoft([archSection(0, 1, points), archSection(height, top, points)], True, True)


def mirroredHalves(solid, base, normal, placement=None):
    """`solid`'s half on the negative side of the plane through `base` at right angles to the axis
    `normal` (X, Y or Z), and its mirror image, fused unrefined; both placed by `placement`."""
    axis = [abs(normal.x), abs(normal.y), abs(normal.z)].index(1)
    size = [400.0, 400.0, 400.0]
    size[axis] = 200.0 + [base.x, base.y, base.z][axis]
    half = solid.common(Part.makeBox(size[0], size[1], size[2], V(-200, -200, -200)))
    image = half.mirror(base, normal)
    if placement is not None:
        half.Placement = placement
        image.Placement = placement
    return half.fuse(image)


def bsplineFaces(shape):
    return [f for f in shape.Faces if isinstance(f.Surface, Part.BSplineSurface)]


class RefineSplitWallsTest(unittest.TestCase):
    def refined(self, fused):
        refined = fused.removeSplitter()
        self.assertTrue(refined.isValid())
        volumes = (refined.Volume, fused.Volume)
        self.assertTrue(relativelyEqual(*volumes), volumes)
        areas = (refined.Area, fused.Area)
        self.assertTrue(relativelyEqual(*areas), areas)
        return refined

    def cutThrough(self, refined, fused, box):
        """A cut through the merged face gives what it gives on the unrefined shape."""
        cut = refined.cut(box)
        self.assertTrue(cut.isValid())
        self.assertTrue(relativelyEqual(cut.Volume, fused.cut(box).Volume))

    # C: cones bounded by a fillet's edge

    def checkStrip(self, fillet):
        fused = strippedCone(fillet)
        self.assertTrue(fused.isValid())
        before = len(lowerConeFaces(fused))
        self.assertGreaterEqual(before, 2, kinds(fused))
        refined = self.refined(fused)
        # the main part of the lower cone and the strip across its seam: two faces apart
        self.assertEqual(len(lowerConeFaces(refined)), 2, (fillet, before, kinds(refined)))
        self.cutThrough(refined, fused, Part.makeBox(4, 40, 4, V(10, -20, 1)))
        return before

    def testFilletedStripMerges(self):
        self.checkStrip(1.5)

    def testFilletedStripMergesWithOtherRadii(self):
        for fillet in (0.5, 3.0):
            with self.subTest(fillet=fillet):
                self.checkStrip(fillet)

    def testUnfilletedStripMerges(self):
        # the control: exact edges, merged before
        self.checkStrip(0)

    # B: B-spline walls run backwards

    def checkWalls(self, fused, expected):
        self.assertEqual(len(bsplineFaces(fused)), 2, kinds(fused))
        refined = self.refined(fused)
        self.assertEqual(len(bsplineFaces(refined)), expected, kinds(refined))
        return refined

    def testSymmetricLoftHalvesMerge(self):
        fused = mirroredHalves(archLoft(), V(0, 0, 0), V(1, 0, 0))
        refined = self.checkWalls(fused, 1)
        wall = bsplineFaces(refined)[0]
        self.assertLess(abs(wall.CenterOfMass.x), 1e-6)
        self.cutThrough(refined, fused, Part.makeBox(4, 20, 4, V(-2, -5, 4)))

    def testSymmetricLoftHalvesMergeWithPlacement(self):
        fused = mirroredHalves(archLoft(), V(0, 0, 0), V(1, 0, 0), PLACED)
        self.checkWalls(fused, 1)

    def testLoftHalvesReversedAlongTheRulingMerge(self):
        # equal sections, cut at mid height and mirrored there: the wall run backwards in v
        fused = mirroredHalves(archLoft(top=1.0), V(0, 0, 6), V(0, 0, 1))
        self.checkWalls(fused, 1)

    def testAsymmetricLoftHalvesStayApart(self):
        fused = mirroredHalves(archLoft([(-6, 3), (0, 7), (6, 6)]), V(0, 0, 0), V(1, 0, 0))
        self.checkWalls(fused, 2)

    def testLoftOffSymmetryStaysApart(self):
        moved = [(x + (1e-4 if x == 0 else 0), y) for x, y in ARCH]
        fused = mirroredHalves(archLoft(moved), V(0, 0, 0), V(1, 0, 0))
        self.checkWalls(fused, 2)

    def testBSplinePetalPairStaysSplit(self):
        self.a, self.b, self.loop = squaresAndPetal()
        a = withPetal(self.a, self.loop)
        # the designed state: A valid, one wire holding the loop, sharing the line x = 5 with B
        self.assertTrue(a.isValid())
        self.assertEqual(len(a.Wires), 1)
        self.assertTrue(any(e.isSame(self.loop) for e in a.Edges))
        # 51 mm2, to the accuracy of the petal's projected curves on the surface
        self.assertAlmostEqual(a.Area, 51, delta=0.01)
        shell = Part.Shell([a, self.b])
        self.assertTrue(shell.isValid())
        self.assertTrue(any(e.isSame(x) for e in a.Edges for x in self.b.Edges))

        refined = shell.removeSplitter()
        self.assertTrue(refined.isValid())
        self.assertAlmostEqual(refined.Area, shell.Area, places=6)
        self.assertEqual(len(refined.Faces), 2, [f.Area for f in refined.Faces])

    # ops#1106 (the B-spline groups checked in the finished shell; models below the classes)
    def patchRefined(self, base, radius):
        # a cylinder through one side of the wall: its patch fused back, the wall in two pieces
        tool = Part.makeCylinder(radius, 20, V(-20, 0.4, 5), V(1, 0, 0))
        fused = base.common(tool).fuse(base.cut(tool))
        self.assertEqual(len(fused.Faces), len(base.Faces) + 1)
        refined = fused.removeSplitter()
        self.assertTrue(refined.isValid())
        self.assertAlmostEqual(refined.Volume, base.Volume, delta=1e-7 * base.Volume)
        return refined

    def testClosedLoftWallPatchMerges(self):
        # review pr1106-r1 R1: a wall on a closed B-spline surface, its seam face in the group; the
        # merged face is built without its seam and is whole only after sewing
        def circle(r, x, y, z):
            return Part.Wire([Part.Circle(V(x, y, z), V(0, 0, 1), r).toShape()])

        base = Part.makeLoft(
            [circle(5, 0, 0, 0), circle(6.5, 0.6, 0.3, 5), circle(4, -0.4, 0.5, 10)], True, False
        )
        self.assertEqual(len(self.patchRefined(base, 1.5).Faces), len(base.Faces))

    def testRationalPatchesMerge(self):
        # review pr1106-r1 R2: on a rational surface the areas of a face and of its pieces differ
        # by about 2e-7 of the area, more than an exact comparison allows
        for base in (
            Part.makeSphere(5).toNurbs(),
            Part.makeCylinder(5, 10).toNurbs(),
        ):
            self.assertEqual(len(self.patchRefined(base, 1.5).Faces), len(base.Faces))

    def testRationalCylinderHalvesKeepTheirVolume(self):
        # review pr1106-r2 C1: a NURBS cylinder (r 5, h 10) cut at y = 1 and fused back. Integration
        # merged its top cap halves into a face 4e-4 smaller than the cap (volume 1e-4 off, valid,
        # silent); the cap's halves now stay apart, and the wall and the bottom cap merge
        base = Part.makeCylinder(5, 10).toNurbs()
        low = Part.makeBox(200, 101, 200, V(-100, -100, -100))
        high = Part.makeBox(200, 99, 200, V(-100, 1, -100))
        fused = base.common(low).fuse(base.common(high))
        refined = fused.removeSplitter()
        self.assertTrue(refined.isValid())
        exact = math.pi * 25 * 10
        self.assertLess(abs(refined.Volume - exact), 1e-6 * exact)
        self.assertLessEqual(len(refined.Faces), 4)

    # ops#1120: a strip across the seam of a wall that closes around its axis but is clamped there,
    # not periodic. The two pieces lie at the two ends of the parameters; the merged face's wire
    # ran on past the end, where the clamped surface is extrapolated (integration before 559: one
    # face 2 % short of the strip, the volume 0.44 off; with 559 the pieces stayed apart). Onshape
    # makes it one face. Expected: one face of the strip's area 0.16 * 5 * 10, the volume kept,
    # the edges' tolerances not raised
    def seamStrip(self, opening):
        cut = clampedSeamCylinder(opening).cut(wedge(0.08, math.pi - 0.3)).cut(
            wedge(-(math.pi - 0.3), -0.08)
        )
        self.assertTrue(cut.isValid())
        refined = cut.removeSplitter()
        self.assertTrue(refined.isValid())
        self.assertTrue(relativelyEqual(refined.Volume, cut.Volume))
        strip = [
            f
            for f in refined.Faces
            if isinstance(f.Surface, Part.BSplineSurface) and abs(f.CenterOfMass.x - 5) < 0.1
        ]
        tolerance = max(e.Tolerance for e in cut.Edges)
        self.assertLessEqual(max(e.Tolerance for e in refined.Edges), tolerance)
        return cut, refined, strip

    def testStripAcrossClampedSeamMerges(self):
        for opening in (0.0, 1e-14, 1e-9):
            cut, refined, strip = self.seamStrip(opening)
            self.assertEqual(len(refined.Faces), len(cut.Faces) - 1, opening)
            self.assertEqual(len(strip), 1, opening)
            self.assertTrue(relativelyEqual(strip[0].Area, 0.16 * 5 * 10, 1e-9), strip[0].Area)
            self.assertTrue(strip[0].Surface.isUPeriodic())

    def testStripAcrossCreasedSeamStaysApart(self):
        # the control: the seam creased (the second row of poles moved out by 0.5), so the wall is
        # not smooth there and the strip keeps its seam edge; the refused attempt across it leaves
        # no raised tolerance on the shape's edges (integration: 2.75e-2 on edges of 5e-6)
        cut = creasedSeamCylinder().cut(wedge(0.08, math.pi - 0.3)).cut(
            wedge(-(math.pi - 0.3), -0.08)
        )
        self.assertTrue(cut.isValid())
        tolerance = max(e.Tolerance for e in cut.Edges)
        refined = cut.removeSplitter()
        self.assertTrue(refined.isValid())
        self.assertEqual(len(refined.Faces), len(cut.Faces))
        self.assertLessEqual(max(e.Tolerance for e in refined.Edges), tolerance)
        self.assertLessEqual(max(e.Tolerance for e in cut.Edges), tolerance)

    def testStripAcrossSeamCreasedBetweenSamplesStaysApart(self):
        # review pr1120-r1 R1: the wall raised to degree 3 along the axis with 40 spans and one pole
        # of the second row around the axis moved out by 0.5, so the seam is creased (about 2 deg)
        # only for z in about 5.1 to 6.1 and smooth at z = 0, 1.25, ... 10. A test of the seam at
        # samples merged the strip across the crease; the strip stays two faces. Its smooth twin
        # (the same degree and spans, no pole moved) merges
        def raised(surface, crease):
            surface.increaseDegree(surface.UDegree, 3)
            v0, v1 = surface.bounds()[2:]
            for k in range(1, 40):
                surface.insertVKnot(v0 + (v1 - v0) * k / 40.0, 1, 1e-12)
            if crease:
                pole = surface.getPole(2, 24) + V(0.5, 0, 0)
                surface.setPole(2, 24, pole, surface.getWeight(2, 24))

        probe = Part.Vertex(V(5, 0, 5.6))
        for crease, seamFaces in ((True, 2), (False, 0)):
            solid = clampedSeamCylinder(0.0, lambda s: raised(s, crease))
            cut = solid.cut(wedge(0.08, 2 * math.pi - 0.08))
            refined = cut.removeSplitter()
            self.assertTrue(refined.isValid())
            onSeam = [
                f for f in refined.Faces if any(e.distToShape(probe)[0] < 1e-6 for e in f.Edges)
            ]
            self.assertEqual(len(onSeam), seamFaces, crease)

    def testBSplineSquaresMerge(self):
        a, b, _ = squaresAndPetal()
        refined = Part.Shell([a, b]).removeSplitter()
        self.assertTrue(refined.isValid())
        self.assertEqual(len(refined.Faces), 1)
        self.assertAlmostEqual(refined.Faces[0].Area, 100, places=6)
        self.assertEqual(refined.Faces[0].Surface.__class__.__name__, "BSplineSurface")


class RefineSplitWallReferenceTest(unittest.TestCase):
    """A Part::Refine of the symmetric loft's mirrored halves; a datum point at the centre of mass
    of its wall face, which stays on the merged wall after an edit of the loft's top section."""

    def setUp(self):
        self.doc = App.newDocument("RefineSplitWallReference")
        doc = self.doc
        self.bottom = doc.addObject("Part::Feature", "Bottom")
        self.bottom.Shape = archSection(0, 1)
        self.top = doc.addObject("Part::Feature", "Top")
        self.top.Shape = archSection(12, 0.7)
        loft = doc.addObject("Part::Loft", "Loft")
        loft.Sections = [self.bottom, self.top]
        loft.Solid = True
        loft.Ruled = True
        box = doc.addObject("Part::Box", "Box")
        box.Length = box.Width = box.Height = 200
        box.Placement.Base = V(-200, -100, -100)
        common = doc.addObject("Part::Common", "Common")
        common.Base, common.Tool = loft, box
        mirror = doc.addObject("Part::Mirroring", "Mirror")
        mirror.Source = common
        mirror.Base = V(0, 0, 0)
        mirror.Normal = V(1, 0, 0)
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [common, mirror]
        fuse.Refine = False
        self.refine = doc.addObject("Part::Refine", "Refine")
        self.refine.Source = fuse
        doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def wallFace(self):
        faces = [
            (i, f)
            for i, f in enumerate(self.refine.Shape.Faces, 1)
            if isinstance(f.Surface, Part.BSplineSurface)
        ]
        self.assertEqual(len(faces), 1, kinds(self.refine.Shape))
        return faces[0]

    def testReferenceOnTheMergedWall(self):
        index, face = self.wallFace()
        point = self.doc.addObject("Part::DatumPoint", "Point")
        point.AttachmentSupport = [(self.refine, "Face%d" % index)]
        point.MapMode = "CenterOfMass"
        self.doc.recompute()
        self.assertLess((point.Placement.Base - face.CenterOfMass).Length, 1e-6)
        self.assertLess(abs(point.Placement.Base.x), 1e-6)  # the whole wall's, on the mirror plane

        self.top.Shape = archSection(12, 0.6)
        self.doc.recompute()
        index, face = self.wallFace()
        self.assertEqual(point.AttachmentSupport[0][1], ("Face%d" % index,))
        self.assertLess((point.Placement.Base - face.CenterOfMass).Length, 1e-6)


def unevenArch(fourth):
    """ARCH with its fourth point at y = `fourth`: symmetric about x = 0 at 6"""
    return [(-6, 3), (-3, 6), (0, 7), (3, fourth), (6, 3)]


class RefineMergedHoledWallReferenceTest(unittest.TestCase):
    """A reference to the left wall of a Part::Refine that merges two walls only after an edit.

    The loft of arch sections with the fourth point at y = 5 (not symmetric), drilled along Y by a
    round hole of radius 1.5 at (x, z) = (`holeX`, 6), halved at x = 0 and fused with its mirror
    image: two walls meeting in a crease. A datum point at the centre of mass of the left wall.
    The edit moves the fourth point to y = 6, the arch symmetric: the right wall is the left one's
    surface run backwards in u and the refine merges them. With the hole across x = 0 the hole's
    two halves merge too. Sewing after the merge changed both merged faces and only the first
    face's history followed (ops#1044, review pr1044pre-r2): the wall was then named as new, and
    the reference broke. Expected: the reference holds the merged wall, whose centre of mass is
    on the mirror plane."""

    holeX = 0.0

    def setUp(self):
        self.doc = App.newDocument("RefineMergedHoledWallReference")
        doc = self.doc
        self.bottom = doc.addObject("Part::Feature", "Bottom")
        self.top = doc.addObject("Part::Feature", "Top")
        self.sections(5)
        loft = doc.addObject("Part::Loft", "Loft")
        loft.Sections = [self.bottom, self.top]
        loft.Solid = True
        loft.Ruled = True
        drill = doc.addObject("Part::Cylinder", "Drill")
        drill.Radius = 1.5
        drill.Height = 40
        drill.Placement = App.Placement(V(self.holeX, -10, 6), App.Rotation(V(1, 0, 0), -90))
        holed = doc.addObject("Part::Cut", "Holed")
        holed.Base, holed.Tool = loft, drill
        holed.Refine = False
        box = doc.addObject("Part::Box", "Box")
        box.Length = 100
        box.Width = box.Height = 200
        box.Placement.Base = V(-100, -100, -100)
        common = doc.addObject("Part::Common", "Common")
        common.Base, common.Tool = holed, box
        common.Refine = False
        mirror = doc.addObject("Part::Mirroring", "Mirror")
        mirror.Source = common
        mirror.Base = V(0, 0, 0)
        mirror.Normal = V(1, 0, 0)
        fuse = doc.addObject("Part::MultiFuse", "Fuse")
        fuse.Shapes = [common, mirror]
        fuse.Refine = False
        self.refine = doc.addObject("Part::Refine", "Refine")
        self.refine.Source = fuse
        doc.recompute()

    def tearDown(self):
        App.closeDocument(self.doc.Name)

    def sections(self, fourth):
        self.bottom.Shape = archSection(0, 1, unevenArch(fourth))
        self.top.Shape = archSection(12, 0.7, unevenArch(fourth))

    def leftWall(self):
        """The B-spline wall through the bottom section's point (-3, 6, 0)"""
        at = Part.Vertex(V(-3, 6, 0))
        faces = [
            (i, f)
            for i, f in enumerate(self.refine.Shape.Faces, 1)
            if isinstance(f.Surface, Part.BSplineSurface) and f.distToShape(at)[0] < 1e-6
        ]
        self.assertEqual(len(faces), 1, kinds(self.refine.Shape))
        return faces[0]

    def testReferenceFollowsTheMerge(self):
        self.assertEqual(len(bsplineFaces(self.refine.Shape)), 2, kinds(self.refine.Shape))
        index, face = self.leftWall()
        point = self.doc.addObject("Part::DatumPoint", "Point")
        point.AttachmentSupport = [(self.refine, "Face%d" % index)]
        point.MapMode = "CenterOfMass"
        self.doc.recompute()
        self.assertLess((point.Placement.Base - face.CenterOfMass).Length, 1e-6)

        self.sections(6)
        self.doc.recompute()
        self.assertEqual(len(bsplineFaces(self.refine.Shape)), 1, kinds(self.refine.Shape))
        index, face = self.leftWall()
        self.assertTrue(point.isValid(), point.getStatusString())
        self.assertEqual(point.AttachmentSupport[0][1], ("Face%d" % index,))
        self.assertLess((point.Placement.Base - face.CenterOfMass).Length, 1e-6)
        self.assertLess(abs(point.Placement.Base.x), 1e-6)


class RefineMergedWallHoledInEachHalfReferenceTest(RefineMergedHoledWallReferenceTest):
    """The control: the hole at x = -3, a whole hole in each half; the hole's halves don't merge."""

    holeX = -3.0


# ops#1120: a wall closed around its axis, clamped there.


def clampedWall(change=None):
    """A cylinder wall (r 5, h 10) as one clamped rational B-spline, not periodic: the quadratic
    circle around the axis (9 poles, knots 0 to 4, end multiplicities 3), first and last rows of
    poles equal, then `change` applied to the surface (if given)."""
    w = math.sqrt(0.5)
    ring = [(5, 0), (5, 5), (0, 5), (-5, 5), (-5, 0), (-5, -5), (0, -5), (5, -5), (5, 0)]
    poles = [[V(x, y, 0), V(x, y, 10)] for x, y in ring]
    weights = [[1.0 if i % 2 == 0 else w] * 2 for i in range(len(ring))]
    surface = Part.BSplineSurface()
    surface.buildFromPolesMultsKnots(
        poles, [3, 2, 2, 2, 3], [2, 2], [0, 1, 2, 3, 4], [0, 1], False, False, 2, 1, weights
    )
    if change:
        change(surface)
    return surface


def wallSolid(surface):
    """The solid of a closed wall and its two caps, made from the wall's own end circles."""
    face = Part.Face(surface)
    caps = [
        Part.Face(Part.Wire([e])) for e in face.Edges if e.isClosed() and e.BoundBox.ZLength < 1e-9
    ]
    shell = Part.makeShell([face] + caps)
    shell.sewShape(1e-4)
    return Part.Solid(shell if shell.ShapeType == "Shell" else shell.Shells[0])


def clampedSeamCylinder(opening, change=None):
    """The clamped wall's solid, its last row of poles around the axis moved by `opening` along X,
    then `change` applied (if given)."""

    def opened(surface):
        last = surface.NbUPoles
        for j in range(1, surface.NbVPoles + 1):
            pole = surface.getPole(last, j) + V(opening, 0, 0)
            surface.setPole(last, j, pole, surface.getWeight(last, j))
        if change:
            change(surface)

    return wallSolid(clampedWall(opened))


def creasedSeamCylinder():
    """The clamped wall with its second row of poles around the axis moved by 0.5 along X: closed,
    but creased at the seam."""

    def creased(surface):
        for j in range(1, surface.NbVPoles + 1):
            surface.setPole(2, j, surface.getPole(2, j) + V(0.5, 0, 0), surface.getWeight(2, j))

    return wallSolid(clampedWall(creased))


def wedge(start, end):
    """The annular wedge between the angles `start` and `end` (radians) about Z, radii 2 to 15."""
    span = math.degrees(end - start)
    outer = Part.makeCylinder(15, 30, V(0, 0, -1), V(0, 0, 1), span)
    shape = outer.cut(Part.makeCylinder(2, 30, V(0, 0, -1), V(0, 0, 1), span))
    shape.rotate(V(0, 0, 0), V(0, 0, 1), math.degrees(start))
    return shape


# ops#1106: the B-spline kind's index-equal merge gets the guards of the reversed kind.
#


def flatBSplineSurface():
    s = Part.BSplineSurface()
    s.buildFromPolesMultsKnots(
        [[V(0, -2, 0), V(0, 10, 0)], [V(10, -2, 0), V(10, 10, 0)]],
        [2, 2],
        [2, 2],
        [0, 1],
        [0, 1],
        False,
        False,
        1,
        1,
    )
    return s


def squaresAndPetal():
    """The squares A and B and the petal's loop edge, on one surface, sharing their edges."""
    tools = [
        Part.LineSegment(V(5, 0, 0), V(5, 11, 0)).toShape(),
        Part.LineSegment(V(-1, 0, 0), V(11, 0, 0)).toShape(),
    ]
    petal = Part.BSplineCurve()
    petal.buildFromPolesMultsKnots(
        [V(5, 0, 0), V(4, -1, 0), V(6, -1, 0), V(5, 0, 0)], [2, 1, 1, 2], [0, 1, 2, 3], False, 1
    )
    tools.append(petal.toShape())
    faces = Part.Face(flatBSplineSurface()).generalFuse(tools)[0].Faces
    squares = [f for f in faces if abs(f.Area - 50) < 1e-9]
    a = [f for f in squares if f.CenterOfMass.x < 5]
    b = [f for f in squares if f.CenterOfMass.x > 5]
    small = [f for f in faces if f.Area < 2]
    assert len(a) == 1 and len(b) == 1 and len(small) == 1, [f.Area for f in faces]
    loops = [e for e in small[0].Edges if e.isClosed()]
    assert len(loops) == 1
    return a[0], b[0], loops[0]


def withPetal(a, loop):
    """A with the loop wired into its outer wire at the corner (5, 0)."""
    corner = V(5, 0, 0)
    edges = a.OuterWire.OrderedEdges
    sequence = []
    for index, edge in enumerate(edges):
        sequence.append(edge)
        following = edges[(index + 1) % len(edges)]
        shared = [x for x in edge.Vertexes if any(x.isSame(y) for y in following.Vertexes)]
        if shared and shared[0].Point.distanceToPoint(corner) < 1e-9 and len(sequence) <= len(edges):
            sequence.append(loop)
    wire = Part.Wire(sequence)
    fixer = Part.ShapeFix.Edge()
    for candidate in (wire, wire.reversed()):
        face = Part.Face(a.Surface, candidate)
        for edge in face.Edges:
            fixer.fixAddPCurve(edge, face, False, 1e-7)
        if face.Area > 0:
            return face
    raise AssertionError("no orientation of the petal wire gives a face")


if __name__ == "__main__":
    unittest.main()
