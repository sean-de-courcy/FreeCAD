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


if __name__ == "__main__":
    unittest.main()
