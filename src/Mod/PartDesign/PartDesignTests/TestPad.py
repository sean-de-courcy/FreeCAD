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

import math
import unittest

import FreeCAD
import Part
from FreeCAD import Base
import TestSketcherApp

from PartDesignTests import TestNamingDump as dump


# A Pad made from two regions of a sketch (ops#125): a 30 x 20 x 2 plate, and two bosses of
# radius 2 and height 5 from a sketch at z = 2, each with a 0.5 fillet on its top edge.
REGIONS = ["InternalFace1", "InternalFace2"]
BOSS_RADIUS = 2.0
BOSS_HEIGHT = 5.0
BOSS_FILLET = 0.5
REGION_PAD_VOLUME = 30 * 20 * 2 + 2 * math.pi * BOSS_RADIUS**2 * BOSS_HEIGHT
# Each fillet removes the area between a square of side r and its quarter circle,
# r^2 (1 - pi/4), turned around the boss's axis at its centroid, r (10 - 3 pi) / (12 - 3 pi)
# inside the edge (Pappus).
REGION_FILLET_VOLUME = REGION_PAD_VOLUME - 2 * (
    2
    * math.pi
    * (BOSS_RADIUS - BOSS_FILLET * (10 - 3 * math.pi) / (12 - 3 * math.pi))
    * BOSS_FILLET**2
    * (1 - math.pi / 4)
)


def makeRegionPad(doc):
    """The ops#125 model in doc, with the bosses at (-5, 0) and (5, 0).
    Returns the boss sketch, the Pad made from its two regions, and the fillet."""
    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    plateSketch = body.newObject("Sketcher::SketchObject", "PlateSketch")
    plateSketch.AttachmentSupport = [(xy, "")]
    plateSketch.MapMode = "FlatFace"
    corners = [
        FreeCAD.Vector(-15, -10, 0),
        FreeCAD.Vector(15, -10, 0),
        FreeCAD.Vector(15, 10, 0),
        FreeCAD.Vector(-15, 10, 0),
    ]
    for i in range(4):
        plateSketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    plate = body.newObject("PartDesign::Pad", "Plate")
    plate.Profile = plateSketch
    plate.Length = 2
    sketch = body.newObject("Sketcher::SketchObject", "BossSketch")
    sketch.AttachmentSupport = [(xy, "")]
    sketch.MapMode = "FlatFace"
    sketch.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(0, 0, 2), FreeCAD.Rotation())
    sketch.MakeInternals = True  # the regions (InternalFaceN)
    for x in (-5, 5):
        sketch.addGeometry(
            Part.Circle(FreeCAD.Vector(x, 0, 0), FreeCAD.Vector(0, 0, 1), BOSS_RADIUS)
        )
    doc.recompute()
    pad = body.newObject("PartDesign::Pad", "Bosses")
    pad.Profile = (sketch, REGIONS)
    pad.Length = BOSS_HEIGHT
    doc.recompute()
    fillet = body.newObject("PartDesign::Fillet", "Fillet")
    fillet.Base = (pad, bossTopEdges(pad))
    fillet.Radius = BOSS_FILLET
    doc.recompute()
    return sketch, pad, fillet


def redrawBosses(sketch):
    """Deletes the two circles and draws them again at (0, -5) and (0, 5): new geometry."""
    sketch.delGeometries([0, 1])
    for y in (-5, 5):
        sketch.addGeometry(
            Part.Circle(FreeCAD.Vector(0, y, 0), FreeCAD.Vector(0, 0, 1), BOSS_RADIUS)
        )


def bossTopEdges(pad):
    """The index names of the bosses' top circles."""
    top = 2 + BOSS_HEIGHT
    return [
        "Edge%d" % (i + 1)
        for i, e in enumerate(pad.Shape.Edges)
        if isinstance(e.Curve, Part.Circle)
        and abs(e.BoundBox.ZMin - top) < 1e-6
        and abs(e.BoundBox.ZMax - top) < 1e-6
    ]


def bossCentres(shape):
    """The (x, y) of each boss's axis, sorted."""
    return sorted(
        (round(f.Surface.Center.x, 6) + 0.0, round(f.Surface.Center.y, 6) + 0.0)
        for f in shape.Faces
        if isinstance(f.Surface, Part.Cylinder)
    )


def toleranceState(shape):
    """Each face's, edge's and vertex's tolerance and each edge's number of curves on surfaces: what
    a maker can change in place in the TShapes a feature's stored shape shares (ops#347)"""

    def pcurves(edge):
        n = 0
        while n < 50:
            try:
                if edge.curveOnSurface(n) is None:
                    break
            except Exception:  # noqa: BLE001  (past the last one)
                break
            n += 1
        return n

    return (
        [f.Tolerance for f in shape.Faces],
        [e.Tolerance for e in shape.Edges],
        [v.Tolerance for v in shape.Vertexes],
        [pcurves(e) for e in shape.Edges],
    )


def upToTheLoftSide(test, doc, kind):
    """ops#347's P5: the loft from the circle r 10 at z 0 to the ellipse 12 x 6 at z 15 as a Body's
    BaseFeature, a 4 x 4 square in the plane x = 22 whose top is 1e-6 under z 15, and a Pad or
    Pocket from it up to the loft's side face. BRepFeat raised the loft's top edge and its vertex
    in place, from 1e-7 to 5e-6, in the base feature's stored shape and the Part::Feature's. The
    base keeps its tolerances and curves; the feature is valid."""
    import Sketcher

    V = FreeCAD.Vector
    loft = Part.makeLoft(
        [
            Part.Wire(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10).toShape()),
            Part.Wire(Part.Ellipse(V(0, 0, 15), 12, 6).toShape()),
        ],
        True,
    )
    base = doc.addObject("Part::Feature", "Loft")
    base.Shape = loft
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    doc.recompute()
    side = next(
        "Face%d" % i
        for i, f in enumerate(baseFeature.Shape.Faces, 1)
        if f.Surface.TypeId != "Part::GeomPlane"
    )
    held = [(o.Name, o.Shape, toleranceState(o.Shape)) for o in (base, baseFeature)]
    sketch = body.newObject("Sketcher::SketchObject", "Square")
    # Sketch x is world -z, y is y, the normal +x
    sketch.Placement = FreeCAD.Placement(V(22, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    top = -(15 - 1e-6)
    corners = [V(top, -2, 0), V(top + 4, -2, 0), V(top + 4, 2, 0), V(top, 2, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    feature = body.newObject("PartDesign::" + kind, kind)
    feature.Profile = sketch
    feature.Type = "UpToFace"
    feature.UpToFace = (baseFeature, [side])
    feature.Reversed = True
    # Refined (the default): refine runs on a copy, and no longer adds a curve on surface to the
    # base's edges in place where the cut splits the side (ops#354)
    doc.recompute()
    test.assertTrue(feature.isValid(), feature.getStatusString())
    assertBasesKept(test, held)
    # The prism reaches the side (ops#353: BRepFeat gave an empty prism up to the lofted
    # B-spline face, and the feature stayed valid)
    expected = loftSideReach(22, -2, 2, 11 - 1e-6, 15 - 1e-6)
    test.assertAlmostEqual(
        feature.AddSubShape.Volume, expected, delta=PRISM_VOLUME_RELATIVE * expected
    )
    return baseFeature, feature


# The volume of a solid whose side is ops#347's loft side cut into pieces (a Pad or Pocket up to
# it) is off by up to 1.1e-3 in GProp's integration, while the pieces' areas add up to the side's
# within 1e-4 and the prism's volume is the computed one within 1e-5 (ops#353)
LOFT_VOLUME_DELTA = 5e-3
# A prism up to that side (an AddSubShape, about 170 to 180) is the computed volume within 1e-5:
# compared relative to its size, well above GProp's error and well below any wrong prism (ops#353
# review L6)
PRISM_VOLUME_RELATIVE = 1e-6


def loftSideReach(x0, y0, y1, z0, z1):
    """The volume between the plane x = x0 and the +x side of ops#347's loft (the circle r 10 at
    z 0 to the ellipse 12 x 6 at z 15) over the rectangle y0..y1, z0..z1 of that plane: from
    x0 >= 12 to the side, or from x0 = 0 inside the loft to the side. The ruled loft's section
    at height z is the ellipse with semi-axes a = 10 + 2z/15 along x and b = 10 - 4z/15 along y
    (its two curves have the same parameterisation), so the side is at x = a sqrt(1 - y^2/b^2).
    The y integral is exact, the z integral Simpson's rule with 1000 intervals (ops#353)."""
    import math

    def reach(z):
        a = 10 + 2 * z / 15
        b = 10 - 4 * z / 15

        def area(y):  # twice the integral of sqrt(1 - y^2/b^2)
            return y * math.sqrt(1 - y * y / (b * b)) + b * math.asin(y / b)

        side = a * (area(y1) - area(y0)) / 2
        return abs(x0 * (y1 - y0) - side)

    n = 1000
    h = (z1 - z0) / n
    total = reach(z0) + reach(z1)
    for i in range(1, n):
        total += (4 if i % 2 else 2) * reach(z0 + i * h)
    return total * h / 3


def squareUpToTheLoft(doc, kind, x0, z0, z1, reversed=True, direction=None, refine=True):
    """ops#353: ops#347's loft as a Body's BaseFeature, a 4 x 4 square y -2..2, z z0..z1 in the
    plane x = x0 (sketch normal +x), and a Pad or Pocket from it up to the loft's B-spline side
    face, along `direction` when given (a custom vector), refined or not. Recomputed, not
    checked."""
    import Sketcher

    V = FreeCAD.Vector
    base = doc.addObject("Part::Feature", "Loft")
    base.Shape = Part.makeLoft(
        [
            Part.Wire(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10).toShape()),
            Part.Wire(Part.Ellipse(V(0, 0, 15), 12, 6).toShape()),
        ],
        True,
    )
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    doc.recompute()
    side = next(
        "Face%d" % i
        for i, f in enumerate(baseFeature.Shape.Faces, 1)
        if f.Surface.TypeId != "Part::GeomPlane"
    )
    sketch = body.newObject("Sketcher::SketchObject", "Square")
    # Sketch x is world -z, y is y, the normal +x
    sketch.Placement = FreeCAD.Placement(V(x0, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    corners = [V(-z1, -2, 0), V(-z0, -2, 0), V(-z0, 2, 0), V(-z1, 2, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    feature = body.newObject("PartDesign::" + kind, kind)
    feature.Profile = sketch
    feature.Type = "UpToFace"
    feature.UpToFace = (baseFeature, [side])
    feature.Reversed = reversed
    feature.Refine = refine
    if direction is not None:
        feature.UseCustomVector = True
        feature.Direction = direction
    doc.recompute()
    return baseFeature, feature


def nurbsPlate(x, hole=None):
    """ops#353 review H1: the rectangle y -10..10, z 0..14 of the plane x = `x` as a B-spline face
    (not elementary, so a prism up to it is built by the split), with a hole of radius
    `hole[1]` around (x, hole[0][0], hole[0][1]) when given."""
    V = FreeCAD.Vector
    corners = [V(x, -10, 0), V(x, 10, 0), V(x, 10, 14), V(x, -10, 14)]
    face = Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]
    if hole:
        (y, z), radius = hole
        face = face.cut(Part.makeCylinder(radius, 4, V(x - 2, y, z), V(1, 0, 0))).Faces[0]
    return face


def squareUpToPlates(doc, holed):
    """ops#353 review H1: a Pad from the 4 x 4 square y -2..2, z 5..9 in the plane x = 22, along -x,
    up to the shape of three B-spline plates at x = 15, 5 and -5 (UpToShape, which leaves out the
    farthest one). With `holed`, the front plate has a hole of radius 1 around (15, 0, 7), inside
    the square's way. Recomputed, not checked."""
    import Sketcher

    V = FreeCAD.Vector
    plates = doc.addObject("Part::Feature", "Plates")
    plates.Shape = Part.Compound(
        [nurbsPlate(15, ((0, 7), 1) if holed else None), nurbsPlate(5), nurbsPlate(-5)]
    )
    body = doc.addObject("PartDesign::Body", "Body")
    sketch = body.newObject("Sketcher::SketchObject", "Square")
    # Sketch x is world -z, y is y, the normal +x
    sketch.Placement = FreeCAD.Placement(V(22, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    corners = [V(-9, -2, 0), V(-5, -2, 0), V(-5, 2, 0), V(-9, 2, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    pad.UpToShape = [(plates, [""])]
    pad.Reversed = True
    doc.recompute()
    return pad


def squareUpToABallBeforePlates(doc):
    """PR 324 round 1 verification: the Pad of squareUpToPlates() (the square y -2..2, z 5..9 at
    x = 22, along -x), up to a ball of radius 1 around (15, 0, 7), inside the square's way, and the
    B-spline plates at x = 5 and -5 (UpToShape, which leaves out the farthest one). Recomputed, not
    checked."""
    import Sketcher

    V = FreeCAD.Vector
    ball = doc.addObject("Part::Feature", "Ball")
    ball.Shape = Part.makeSphere(1, V(15, 0, 7))
    plates = doc.addObject("Part::Feature", "Plates")
    plates.Shape = Part.Compound([nurbsPlate(5), nurbsPlate(-5)])
    body = doc.addObject("PartDesign::Body", "Body")
    sketch = body.newObject("Sketcher::SketchObject", "Square")
    sketch.Placement = FreeCAD.Placement(V(22, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    corners = [V(-9, -2, 0), V(-5, -2, 0), V(-5, 2, 0), V(-9, 2, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    pad.UpToShape = [(ball, [""]), (plates, [""])]
    pad.Reversed = True
    doc.recompute()
    return pad


def postInTheGapOfACWithABump(doc):
    """PR 324 round 2 verification: postInTheGap()'s C (the polygon (0,0), (10,0), (10,3), (4,3),
    (4,7), (10,7), (10,10), (0,10) on the XY plane, 10 high) as a Body's BaseFeature, fused with a
    bump on the upper arm's outer face y = 10: the loft from the circle of radius 1 around
    (7, 10, 5) to the ellipse 1.2 x 0.6 around (7, 12, 5), whose B-spline side lies in the way of
    the post's square, so that the Pad goes by the split. A Pad from the 2 x 2 square x 6..8,
    z 4..6 on the lower arm's top (y = 3), up to the base (UpToShape, nothing selected).
    Recomputed, not checked. Returns the base feature and the Pad."""
    V = FreeCAD.Vector
    points = [V(0, 0), V(10, 0), V(10, 3), V(4, 3), V(4, 7), V(10, 7), V(10, 10), V(0, 10)]
    shape = Part.Face(Part.makePolygon(points + points[:1])).extrude(V(0, 0, 10))
    bump = Part.makeLoft(
        [
            Part.Wire(Part.Circle(V(0, 0, 0), V(0, 0, 1), 1).toShape()),
            Part.Wire(Part.Ellipse(V(0, 0, 2), 1.2, 0.6).toShape()),
        ],
        True,
    )
    bump.rotate(V(0, 0, 0), V(1, 0, 0), -90)  # along +y
    bump.translate(V(7, 10, 5))
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = shape.fuse(bump).removeSplitter()
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    doc.recompute()
    sketch = body.newObject("Sketcher::SketchObject", "Post")
    sketch.AttachmentSupport = [(baseFeature, [planarFaceAt(baseFeature.Shape, 1, 3)])]
    sketch.MapMode = "FlatFace"
    # The sketch's x is the world's -x and its y is z, its origin (0, 3, 0): the square x 6..8, z 4..6
    TestSketcherApp.CreateRectangleSketch(sketch, (-8, 4), (2, 2))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    doc.recompute()
    return baseFeature, pad


def padUpToAPlateWithALippedBoss(doc, half):
    """PR 324 round 2 verification: a Body whose BaseFeature is the plate x, y -8..8, z 0..2 with a
    boss hanging under it, revolved about the z axis from one degree-1 B-spline in the XZ plane:
    from (2, -10) widening to (4, -0.1), then a lip narrowing to (3.9, 0) at the plate. The lip,
    an undercut, is the last 1.4 % of the B-spline's parameter range (chord length). A Pad from
    the square x, y -`half`..`half` at z = -15, along +z, up to the base (UpToShape, nothing
    selected). Recomputed, not checked."""
    import Sketcher

    V = FreeCAD.Vector
    poles = [V(2, 0, -10), V(4, 0, -0.1), V(3.9, 0, 0)]
    first = (poles[1] - poles[0]).Length
    side = Part.BSplineCurve()
    side.buildFromPolesMultsKnots(
        poles, [2, 1, 2], [0, first, first + (poles[2] - poles[1]).Length], False, 1
    )
    outline = Part.Wire(
        [
            Part.LineSegment(V(0, 0, -10), poles[0]).toShape(),
            side.toShape(),
            Part.LineSegment(poles[2], V(0, 0, 0)).toShape(),
            Part.LineSegment(V(0, 0, 0), V(0, 0, -10)).toShape(),
        ]
    )
    boss = Part.Face(outline).revolve(V(0, 0, 0), V(0, 0, 1), 360)
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = Part.makeBox(16, 16, 2, V(-8, -8, 0)).fuse(boss).removeSplitter()
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    sketch = body.newObject("Sketcher::SketchObject", "Square")
    sketch.Placement = FreeCAD.Placement(V(0, 0, -15), FreeCAD.Rotation())
    corners = [V(-half, -half, 0), V(half, -half, 0), V(half, half, 0), V(-half, half, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    doc.recompute()
    return pad


def padUpToAPlateWithABulb(doc, half):
    """PR 324 round 1 verification: a Body whose BaseFeature is the plate x -10..10, y -10..10,
    z 10..12 with a bulb hanging under it, the smooth loft (one B-spline side) of the circles
    about the z axis of radius 2 at z = 10, 4 at z = 6 and 2 at z = 2. A Pad from the square
    x, y -`half`..`half` at z = -5, along +z, up to the base (UpToShape, nothing selected).
    Recomputed, not checked."""
    import Sketcher

    V = FreeCAD.Vector
    bulb = Part.makeLoft(
        [
            Part.Wire(Part.Circle(V(0, 0, 10), V(0, 0, 1), 2).toShape()),
            Part.Wire(Part.Circle(V(0, 0, 6), V(0, 0, 1), 4).toShape()),
            Part.Wire(Part.Circle(V(0, 0, 2), V(0, 0, 1), 2).toShape()),
        ],
        True,
        False,
    )
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = Part.makeBox(20, 20, 2, V(-10, -10, 10)).fuse(bulb).removeSplitter()
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    sketch = body.newObject("Sketcher::SketchObject", "Square")
    sketch.Placement = FreeCAD.Placement(V(0, 0, -5), FreeCAD.Rotation())
    corners = [V(-half, -half, 0), V(half, -half, 0), V(half, half, 0), V(-half, half, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    doc.recompute()
    return pad


def padUpToABoxBesideALoft(doc, withLoft, x0=25):
    """ops#353 review M2: the box x 10..35, y -5..5, z 0..10 as a Body's BaseFeature, fused with
    ops#347's loft when `withLoft` (its B-spline side is away from the Pad), and a Pad from the
    4 x 4 square x `x0`..`x0` + 4, y -2..2 at z = -5, along +z, up to the base (UpToShape, nothing
    selected). Recomputed, not checked."""
    import Sketcher

    V = FreeCAD.Vector
    shape = Part.makeBox(25, 10, 10, V(10, -5, 0))
    if withLoft:
        loft = Part.makeLoft(
            [
                Part.Wire(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10).toShape()),
                Part.Wire(Part.Ellipse(V(0, 0, 15), 12, 6).toShape()),
            ],
            True,
        )
        shape = shape.fuse(loft).removeSplitter()
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = shape
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    sketch = body.newObject("Sketcher::SketchObject", "Square")
    sketch.Placement = FreeCAD.Placement(V(0, 0, -5), FreeCAD.Rotation())
    corners = [V(x0, -2, 0), V(x0 + 4, -2, 0), V(x0 + 4, 2, 0), V(x0, 2, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    doc.recompute()
    return pad


def padUpToARevolvedFace(doc, y0, y1, far=False, whole=False):
    """ops#353 review M1: the face of the surface of revolution of a B-spline arc (r 20..21..20
    over z 0..10) about the z axis, 60 degrees about z, centred on the +x axis (y about -10..10 at r = 20,
    not elementary, so the Pad goes by the split), and a Pad from the rectangle y `y0`..`y1`,
    z 4..8 in the plane x = 40, along (-1, -0.1, -0.1), up to that face. The direction is oblique
    so that Part::Tools::isConcave() doesn't keep the face's limits. With `far`, the face is
    centred on the -x axis, on the far side of the axis, and the rectangle is z 8..10 (ops#357);
    with `whole`, the face is the whole surface. Recomputed, not checked."""
    import Sketcher

    V = FreeCAD.Vector
    arc = Part.BSplineCurve()
    arc.interpolate([V(20, 0, 0), V(21, 0, 5), V(20, 0, 10)])
    face = arc.toShape().revolve(V(0, 0, 0), V(0, 0, 1), 60)
    face.rotate(V(0, 0, 0), V(0, 0, 1), 150 if far else -30)
    if whole:
        face = Part.Face(face.Faces[0].Surface)
    z0, z1 = (8, 10) if far else (4, 8)
    wall = doc.addObject("Part::Feature", "Wall")
    wall.Shape = face
    body = doc.addObject("PartDesign::Body", "Body")
    sketch = body.newObject("Sketcher::SketchObject", "Rectangle")
    # Sketch x is world -z, y is y, the normal +x
    sketch.Placement = FreeCAD.Placement(V(40, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    corners = [V(-z1, y0, 0), V(-z0, y0, 0), V(-z0, y1, 0), V(-z1, y1, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(Sketcher.Constraint("Coincident", i, 2, (i + 1) % 4, 1))
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToFace"
    pad.UpToFace = (wall, ["Face1"])
    pad.UseCustomVector = True
    pad.AlongSketchNormal = False
    pad.Direction = V(-1, -0.1, -0.1)
    doc.recompute()
    return pad


def revolvedFaceReach(y0, y1, z0, z1, far=False):
    """The volume of padUpToARevolvedFace()'s prism over the rectangle y y0..y1, z z0..z1 of the
    plane x = 40, when all of it meets the face: from each point (40, y, z) along the unit d of
    (-1, -0.1, -0.1) to the surface, at the first t where the point's distance from the z axis is
    the arc's x where its z is the point's (the arc's z rises along it); with `far`, at the
    second, where the line leaves the surface on the far side of the axis (ops#357). Both by
    bisection; the volume is the integral of t |d.x| over the rectangle, by Simpson's rule with 16
    intervals in y and 8 in z (within 6e-8 relative of 64 and 32; PR 326 review)."""
    import math

    V = FreeCAD.Vector
    arc = Part.BSplineCurve()
    arc.interpolate([V(20, 0, 0), V(21, 0, 5), V(20, 0, 10)])

    def bisect(above, low, high):  # the last value in low..high where above() holds
        for _ in range(50):
            middle = (low + high) / 2
            if above(middle):
                low = middle
            else:
                high = middle
        return (low + high) / 2

    def radius(z):
        v = bisect(lambda v: arc.value(v).z < z, arc.FirstParameter, arc.LastParameter)
        return arc.value(v).x

    d = V(-1, -0.1, -0.1)
    d.normalize()

    def outside(y, z, t):
        p = V(40, y, z) + d * t
        return math.hypot(p.x, p.y) > radius(p.z)

    def reach(y, z):
        if far:  # inside the surface at t = 40 (x about 0), outside again by t = 80
            return bisect(lambda t: not outside(y, z, t), 40, 80)
        return bisect(lambda t: outside(y, z, t), 10, 30)

    def simpson(f, a, b, n):
        h = (b - a) / n
        weights = (1 if i in (0, n) else 4 if i % 2 else 2 for i in range(n + 1))
        return h / 3 * sum(w * f(a + i * h) for i, w in enumerate(weights))

    return abs(d.x) * simpson(lambda z: simpson(lambda y: reach(y, z), y0, y1, 16), z0, z1, 8)


def squareSketch(body, name, placement, rectangles):
    """A sketch in `body` at `placement` of closed rectangles (x0, y0, x1, y1) in its plane"""
    import Sketcher

    V = FreeCAD.Vector
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.Placement = placement
    for x0, y0, x1, y1 in rectangles:
        start = sketch.GeometryCount
        corners = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
        for i in range(4):
            sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        for i in range(4):
            sketch.addConstraint(
                Sketcher.Constraint("Coincident", start + i, 2, start + (i + 1) % 4, 1)
            )
    return sketch


def padUpToABallUnderAPlate(doc, half, knob=True, faces=False, length2=None):
    """ops#357: a Body whose BaseFeature is the plate x, y -8..8, z 0..2 with the ball of radius
    5 about (0, 0, -0.1) through it (a dome above it to z 4.9) and the B-spline knob x 5..6, y
    -0.5..0.5, z 2..3 on it beside the dome (a freeform face in the Pad's path, so the Pad goes by
    the split), and a Pad from the square x, y -`half`..`half` at z = -15, along +z, up to the
    base (UpToShape, nothing selected). The ball's band between its equator and the plate (z
    -0.1..0, 0.02 of the sphere face's 1.59 range) faces the plate. Without the `knob`, the base
    has only planes and spheres, and the Pad goes by BRepFeat (ops#361). With `faces`, the Pad goes
    up to the ball's lower face and the plate's bottom alone; with `length2`, it has a second side
    of that length. Recomputed, not checked."""
    V = FreeCAD.Vector
    plate = Part.makeBox(16, 16, 2, V(-8, -8, 0))
    ball = Part.makeSphere(5, V(0, 0, -0.1))
    tools = [ball, Part.makeBox(1, 1, 1, V(5, -0.5, 2)).toNurbs()] if knob else [ball]
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = plate.fuse(tools).removeSplitter()
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    placement = FreeCAD.Placement(V(0, 0, -15), FreeCAD.Rotation())
    sketch = squareSketch(body, "Square", placement, [(-half, -half, half, half)])
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    if faces:
        doc.recompute()
        pad.UpToShape = [(baseFeature, ballAndPlateBottom(baseFeature.Shape))]
    if length2 is not None:
        pad.SideType = "Two sides"
        pad.Type2 = "Length"
        pad.Length2 = length2
    doc.recompute()
    return pad


def ballAndPlateBottom(shape):
    """The names of `shape`'s faces on the sphere below z = 0 and on the plane z = 0: the faces of
    padUpToABallUnderAPlate()'s base (or of TestPocket's mold of it) that the square first meets"""
    names = []
    for i, face in enumerate(shape.Faces, 1):
        kind = face.Surface.TypeId
        centre = face.CenterOfMass
        if (kind == "Part::GeomSphere" and centre.z < 0) or (
            kind == "Part::GeomPlane" and abs(centre.z) < 1e-9 and face.Area < 300
        ):
            names.append("Face%d" % i)
    return names


def ballBandShadow():
    """The shadow of padUpToABallUnderAPlate()'s band: the cylinder of radius 5 between the ball's
    equator and the plate (z -0.1..0) less the ball, pi times the integral of z^2 over 0..0.1"""
    V = FreeCAD.Vector
    return Part.makeCylinder(5, 0.1, V(0, 0, -0.1)).cut(Part.makeSphere(5, V(0, 0, -0.1)))


def padUpToABumpOverABall(doc, theta, length, height=0.5):
    """PR 331 round 1: a Body whose BaseFeature is the ball of radius 5 about the origin under a
    plate x, y -8..8 whose bottom is the B-spline z = -0.2 + `height` exp(-(t/`length`)^2 -
    (r/0.4)^2), a bump about the point of the equator at `theta` degrees (t along the circle, r
    across it), and whose top is 2.2 above it. Where the bump rises above z = 0, the plate meets
    the ball above its equator: a band of the sphere face, short along its edge, faces the plate.
    A Pad from the square x, y -6..6 at z = -15, along +z, up to the base (UpToShape, nothing
    selected), by the split (the plate's bottom is a B-spline). Recomputed, not checked."""
    import math

    V = FreeCAD.Vector
    c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
    cx, cy = 5 * c, 5 * s

    def bottom(x, y):
        t = -(x - cx) * s + (y - cy) * c
        r = (x - cx) * c + (y - cy) * s
        return -0.2 + height * math.exp(-((t / length) ** 2) - ((r / 0.4) ** 2))

    def axis(centre):
        # Poles 0.05 apart within 1.5 of the bump's centre, 2 apart elsewhere
        fine = [round(centre + 0.05 * k, 6) for k in range(-30, 31)]
        coarse = [v for v in (-6, -4, -2, 2, 4, 6) if abs(v - centre) > 1.6]
        return sorted(set([-8.0, 8.0] + coarse + [v for v in fine if -8 < v < 8]))

    xs, ys = axis(cx), axis(cy)

    # Poles on the grid, clamped cubic: the surface stays within the poles' hull, unlike an
    # interpolation through them, which overshoots on so uneven a grid
    def knots(count):
        return [float(k) for k in range(count - 2)], [4] + [1] * (count - 4) + [4]

    uKnots, uMults = knots(len(xs))
    vKnots, vMults = knots(len(ys))
    surface = Part.BSplineSurface()
    surface.buildFromPolesMultsKnots(
        [[V(x, y, bottom(x, y)) for y in ys] for x in xs],
        uMults,
        vMults,
        uKnots,
        vKnots,
        False,
        False,
        3,
        3,
    )
    plate = surface.toShape().extrude(V(0, 0, 2.2))
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = plate.fuse(Part.makeSphere(5)).removeSplitter()
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    placement = FreeCAD.Placement(V(0, 0, -15), FreeCAD.Rotation())
    sketch = squareSketch(body, "Square", placement, [(-6, -6, 6, 6)])
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    pad.Refine = False
    doc.recompute()
    return pad


def ballBottomReach(half):
    """The volume from z = -15 up to the bottom of padUpToABallUnderAPlate()'s ball, z = -0.1 -
    sqrt(25 - x^2 - y^2), over the square x, y -half..half (half < 3.5), by Simpson's rule with
    64 x 64 intervals"""
    import math

    n = 64
    h = 2 * half / n
    weights = [1 if i in (0, n) else 4 if i % 2 else 2 for i in range(n + 1)]
    total = 0.0
    for i, wi in enumerate(weights):
        for j, wj in enumerate(weights):
            x, y = -half + i * h, -half + j * h
            total += wi * wj * (15 - 0.1 - math.sqrt(25 - x * x - y * y))
    return total * h * h / 9


def padUpToALoftedWall(doc, points):
    """ops#357: a Body whose BaseFeature is the plate x, y -8..8, z 0..2 with a wall under it: the
    loft from the circle of radius 5 about the z axis at z = -5 to a periodic B-spline through
    `points` points of the same circle at z = 1 (inside the plate), a near-vertical B-spline side
    that leans by the interpolation's error. A Pad from the square x, y -6..6 at z = -15, along
    +z, up to the base (UpToShape, nothing selected). Recomputed, not checked."""
    import math

    V = FreeCAD.Vector
    circle = [
        V(5 * math.cos(2 * math.pi * k / points), 5 * math.sin(2 * math.pi * k / points), 1)
        for k in range(points)
    ]
    top = Part.BSplineCurve()
    top.interpolate(circle, PeriodicFlag=True)
    bottom = Part.Circle(V(0, 0, -5), V(0, 0, 1), 5)
    wall = Part.makeLoft([Part.Wire(bottom.toShape()), Part.Wire(top.toShape())], True)
    plate = Part.makeBox(16, 16, 2, V(-8, -8, 0))
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = plate.fuse(wall).removeSplitter()
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    placement = FreeCAD.Placement(V(0, 0, -15), FreeCAD.Rotation())
    sketch = squareSketch(body, "Square", placement, [(-6, -6, 6, 6)])
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    doc.recompute()
    return pad


def padUpToATrimmedPlate(doc, trimmed):
    """ops#357: the B-spline plate x = 5, y -10..10, z 0..14, trimmed to y -2..2, z 4..10 when
    `trimmed` (the same surface), and a Pad from the square y -3..3, z 5..9 in the plane x = 22,
    along (-1, 0.1, -0.1), up to it. The square reaches the plane at y -1.3..4.7, z 3.3..7.3:
    past the trimmed face, within the plate. Part::Tools::isConcave() keeps a face's limits when
    one of its surface's parameter directions is at most 90 degrees from the direction; this
    direction is more than 90 degrees from both of the plate's. Recomputed, not checked."""
    V = FreeCAD.Vector
    corners = [V(5, -10, 0), V(5, 10, 0), V(5, 10, 14), V(5, -10, 14)]
    face = Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]
    if trimmed:
        face = face.common(Part.makeBox(2, 4, 6, V(4, -2, 4))).Faces[0]
    wall = doc.addObject("Part::Feature", "Wall")
    wall.Shape = face
    body = doc.addObject("PartDesign::Body", "Body")
    # Sketch x is world -z, y is y, the normal +x
    placement = FreeCAD.Placement(V(22, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    sketch = squareSketch(body, "Square", placement, [(-9, -3, -5, 3)])
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToFace"
    pad.UpToFace = (wall, ["Face1"])
    pad.UseCustomVector = True
    pad.AlongSketchNormal = False
    pad.Direction = V(-1, 0.1, -0.1)
    doc.recompute()
    return pad


def padUpToTheLoftFrom(doc, rectangles):
    """ops#357: ops#347's loft as a Body's BaseFeature, and a Pad up to its B-spline side from the
    rectangles (y0, z0, y1, z1) of the plane x = 22 (sketch normal +x, Reversed). Recomputed, not
    checked."""
    V = FreeCAD.Vector
    base = doc.addObject("Part::Feature", "Loft")
    base.Shape = Part.makeLoft(
        [
            Part.Wire(Part.Circle(V(0, 0, 0), V(0, 0, 1), 10).toShape()),
            Part.Wire(Part.Ellipse(V(0, 0, 15), 12, 6).toShape()),
        ],
        True,
    )
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    doc.recompute()
    side = next(
        "Face%d" % i
        for i, f in enumerate(baseFeature.Shape.Faces, 1)
        if f.Surface.TypeId != "Part::GeomPlane"
    )
    # Sketch x is world -z, y is y, the normal +x
    placement = FreeCAD.Placement(V(22, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    sketch = squareSketch(
        body, "Profile", placement, [(-z1, y0, -z0, y1) for y0, z0, y1, z1 in rectangles]
    )
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToFace"
    pad.UpToFace = (baseFeature, [side])
    pad.Reversed = True
    doc.recompute()
    return pad


# ops#360: two rectangles held by constraints, A 2 x 2 at the origin and B 3 x 3 at x 5..8, up to
# a B-spline plate. The face maker sorts the profile's faces by area, larger first, so A grown to
# 4 x 4 (16 mm^2, B's is 9) comes first: the far caps' order swaps, their geometry IDs kept
CAP_A = (0, 0, 2, 2)
CAP_B = (5, 0, 8, 3)
CAP_A_GROWN = 4


def dimensionedRectangle(sketch, tag, x0, y0, x1, y1):
    """A closed rectangle in sketch, held by constraints, its width and height named w<tag> and
    h<tag>, the place of its first corner x<tag> and y<tag>"""
    import Sketcher

    V = FreeCAD.Vector
    start = sketch.GeometryCount
    corners = [V(x0, y0, 0), V(x1, y0, 0), V(x1, y1, 0), V(x0, y1, 0)]
    for i in range(4):
        sketch.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
    for i in range(4):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", start + i, 2, start + (i + 1) % 4, 1)
        )
    sketch.addConstraint(Sketcher.Constraint("Horizontal", start))
    sketch.addConstraint(Sketcher.Constraint("Horizontal", start + 2))
    sketch.addConstraint(Sketcher.Constraint("Vertical", start + 1))
    sketch.addConstraint(Sketcher.Constraint("Vertical", start + 3))
    width = sketch.addConstraint(Sketcher.Constraint("DistanceX", start, 1, start, 2, x1 - x0))
    sketch.renameConstraint(width, "w" + tag)
    height = sketch.addConstraint(
        Sketcher.Constraint("DistanceY", start + 1, 1, start + 1, 2, y1 - y0)
    )
    sketch.renameConstraint(height, "h" + tag)
    left = sketch.addConstraint(Sketcher.Constraint("DistanceX", -1, 1, start, 1, x0))
    sketch.renameConstraint(left, "x" + tag)
    bottom = sketch.addConstraint(Sketcher.Constraint("DistanceY", -1, 1, start, 1, y0))
    sketch.renameConstraint(bottom, "y" + tag)


def freeformPlateShape(z, seam=None, swapped=False):
    """The rectangle x -10..20, y -10..10 of the plane z = `z` as a B-spline face (not elementary,
    so a prism up to it is built by the split), or with `seam`, a shell of two such faces meeting
    at x = `seam`, the right one first if `swapped`"""
    V = FreeCAD.Vector
    faces = []
    for x0, x1 in ((-10, seam), (seam, 20)) if seam is not None else ((-10, 20),):
        corners = [V(x0, -10, z), V(x1, -10, z), V(x1, 10, z), V(x0, 10, z)]
        faces.append(Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0])
    if swapped:
        faces.reverse()
    return faces[0] if len(faces) == 1 else Part.Shell(faces)


def freeformStripsShape(z, cuts, order=None, turn=0):
    """PR 366 round 2: the rectangle x -10..20, y -10..10 of the plane z = `z` as a shell of
    B-spline faces meeting at x = each of `cuts`, left to right, or in the order of `order`'s
    indexes. Round 5b: each face made from its corners turned by `turn` degrees about Z (its
    surface's parameters stay in the world's axes, unlike a shell turned once made)"""
    V = FreeCAD.Vector
    xs = [-10] + list(cuts) + [20]
    faces = []
    for x0, x1 in zip(xs, xs[1:]):
        corners = [
            V(*placeTurned(x, y, turn), z) for x, y in ((x0, -10), (x1, -10), (x1, 10), (x0, 10))
        ]
        faces.append(Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0])
    return Part.Shell([faces[i] for i in order] if order else faces)


def freeformPlate(doc, z, seam=None):
    """A Part feature holding freeformPlateShape(z, seam)"""
    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = freeformPlateShape(z, seam)
    return plate


def freeformHoleShellShape(z, swapped=False):
    """ops#360 round 1: a shell of two B-spline faces at height z: the rectangle x -10..20,
    y -10..10 with the hole x -1..1, y -2..2, and the hole's fill, first if `swapped`"""
    V = FreeCAD.Vector
    outer = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    hole = [V(-1, -2, z), V(-1, 2, z), V(1, 2, z), V(1, -2, z)]
    wires = [Part.makePolygon(corners + corners[:1]) for corners in (outer, hole)]
    plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), wires).toNurbs().Faces[0]
    fill = [V(-1, -2, z), V(1, -2, z), V(1, 2, z), V(-1, 2, z)]
    fillFace = Part.Face(Part.makePolygon(fill + fill[:1])).toNurbs().Faces[0]
    return Part.Shell([fillFace, plate] if swapped else [plate, fillFace])


def freeformHoleShell(doc, z):
    """A Part feature holding freeformHoleShellShape(z)"""
    shell = doc.addObject("Part::Feature", "Plate")
    shell.Shape = freeformHoleShellShape(z)
    return shell


def ellipticHoleShell(z, turn=0, centre=(3, 3), a=4, bounds=(-10, -10, 20, 10)):
    """PR 340 round 2: a shell of two B-spline faces at height z: the rectangle x -10..20,
    y -10..10 (or `bounds`' x0, y0, x1, y1) with an elliptic hole about (3, 3) (or `centre`),
    semi-axes 4 (or `a`) along x and 1 along y (one closed edge), and the hole's fill. `turn`
    turns the ellipse about its centre by that many degrees before the faces are built: 180
    gives the same faces, their edge starting on the other side"""
    V = FreeCAD.Vector
    edge = Part.Ellipse(V(centre[0], centre[1], z), a, 1).toShape()
    if turn:
        edge.rotate(V(centre[0], centre[1], z), V(0, 0, 1), turn)
    x0, y0, x1, y1 = bounds
    outer = [V(x0, y0, z), V(x1, y0, z), V(x1, y1, z), V(x0, y1, z)]
    plane = Part.Plane(V(0, 0, z), V(0, 0, 1))
    plate = Part.Face(plane, [Part.makePolygon(outer + outer[:1]), Part.Wire([edge])])
    fill = Part.Face(Part.Wire([edge]))
    return Part.Shell([plate.toNurbs().Faces[0], fill.toNurbs().Faces[0]])


def lobedHoleShell(z, lobes, turn=0):
    """PR 340 round 4: a shell of two B-spline faces at height z: the rectangle x -10..20,
    y -10..10 with a hole of `lobes` lobes about (3, 3) (radius 2 + 0.8 cos(lobes t), lobes at
    t = 0, 360 / lobes, ..., one closed B-spline edge), and the hole's fill. `turn` turns the
    hole about its centre by that many degrees. A disc of radius 2.3 about (3, 3) crosses it
    between the lobes: its cap is `lobes` twins on the plate and one piece on the fill"""
    V = FreeCAD.Vector
    points = []
    for k in range(60):
        t = 2 * math.pi * k / 60
        r = 2 + 0.8 * math.cos(lobes * t)
        points.append(V(3 + r * math.cos(t), 3 + r * math.sin(t), z))
    curve = Part.BSplineCurve()
    curve.interpolate(points, PeriodicFlag=True)
    edge = curve.toShape()
    if turn:
        edge.rotate(V(3, 3, z), V(0, 0, 1), turn)
    outer = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    plane = Part.Plane(V(0, 0, z), V(0, 0, 1))
    plate = Part.Face(plane, [Part.makePolygon(outer + outer[:1]), Part.Wire([edge])])
    fill = Part.Face(Part.Wire([edge]))
    return Part.Shell([plate.toNurbs().Faces[0], fill.toNurbs().Faces[0]])


def discUpToAnEllipticHole(doc, kind="Pad", shell=ellipticHoleShell, radius=3):
    """PR 340 round 2: a Pad from the disc A (centre (3, 3), radius 3, its centre's place named
    xA and yA, its radius rA) and the rectangle B up to the plate with the elliptic hole and its
    fill (UpToShape). The circle crosses the ellipse four times: A's cap is three pieces, the
    middle one on the fill, and the top and bottom ones on the plate, each bounded by the circle
    and the ellipse alone. Or a Pocket from them on top of the block x -2..15, y -5..8, z 0..10,
    down to the plate at z = 4 (round 3). `shell(z)` gives another up-to shell, and `radius`
    another radius (round 4). Returns the feature and the height of its far caps"""
    import Sketcher

    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    capZ = 10 if kind == "Pad" else 4
    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = shell(capZ)
    if kind == "Pocket":
        blockSketch = body.newObject("Sketcher::SketchObject", "BlockSketch")
        blockSketch.AttachmentSupport = [(xy, "")]
        blockSketch.MapMode = "FlatFace"
        dimensionedRectangle(blockSketch, "Block", -2, -5, 15, 8)
        block = body.newObject("PartDesign::Pad", "Block")
        block.Profile = blockSketch
        block.Length = 10
    sketch = body.newObject("Sketcher::SketchObject", "Profile")
    sketch.AttachmentSupport = [(xy, "")]
    sketch.MapMode = "FlatFace"
    if kind == "Pocket":
        sketch.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(0, 0, 10), FreeCAD.Rotation())
    circle = sketch.addGeometry(
        Part.Circle(FreeCAD.Vector(3, 3, 0), FreeCAD.Vector(0, 0, 1), radius)
    )
    radiusConstraint = sketch.addConstraint(Sketcher.Constraint("Radius", circle, radius))
    sketch.renameConstraint(radiusConstraint, "rA")
    for axis, tag in (("DistanceX", "xA"), ("DistanceY", "yA")):
        place = sketch.addConstraint(Sketcher.Constraint(axis, -1, 1, circle, 3, 3))
        sketch.renameConstraint(place, tag)
    dimensionedRectangle(sketch, "B", 10, 0, 13, 3)
    feature = body.newObject("PartDesign::" + kind, kind)
    feature.Profile = sketch
    feature.Type = "UpToShape"
    feature.UpToShape = (plate, ["Face1", "Face2"])
    feature.Refine = False
    doc.recompute()
    return feature, capZ


def centreOfFarCapAt(shape, z, x, y):
    """The (x, y) of the centre of mass of the far cap at height z that holds (x, y, z)"""
    centre = farCaps(shape, z)[farCapAt(shape, z, x, y)].CenterOfMass
    return centre.x, centre.y


def capsUpToAFreeformPlate(
    doc, kind, seam=None, hole=False, capA=CAP_A, block=(-2, -5, 12, 8), withB=True
):
    """ops#360: a Pad from A and B in the XY plane up to a B-spline plate at z = 10 (UpToFace, or
    UpToShape up to the two-face shell meeting at x = `seam`, or with `hole` the plate with a hole
    and its fill); or a Pocket from them on top of the block x -2..12, y -5..8 (or `block`'s x0,
    y0, x1, y1), z 0..10, down to the plate at z = 4. Without B if not `withB`. Returns the feature
    and the height of its far caps (the Pocket's floors)"""
    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    capZ = 10 if kind == "Pad" else 4
    plate = freeformHoleShell(doc, capZ) if hole else freeformPlate(doc, capZ, seam)
    if kind == "Pocket":
        blockSketch = body.newObject("Sketcher::SketchObject", "BlockSketch")
        blockSketch.AttachmentSupport = [(xy, "")]
        blockSketch.MapMode = "FlatFace"
        dimensionedRectangle(blockSketch, "Block", *block)
        blockPad = body.newObject("PartDesign::Pad", "Block")
        blockPad.Profile = blockSketch
        blockPad.Length = 10
    sketch = body.newObject("Sketcher::SketchObject", "Profile")
    sketch.AttachmentSupport = [(xy, "")]
    sketch.MapMode = "FlatFace"
    if kind == "Pocket":
        sketch.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(0, 0, 10), FreeCAD.Rotation())
    dimensionedRectangle(sketch, "A", *capA)
    if withB:
        dimensionedRectangle(sketch, "B", *CAP_B)
    feature = body.newObject("PartDesign::" + kind, kind)
    feature.Profile = sketch
    if seam is None and not hole:
        feature.Type = "UpToFace"
        feature.UpToFace = (plate, ["Face1"])
    else:
        feature.Type = "UpToShape"
        feature.UpToShape = (plate, ["Face1", "Face2"])
    feature.Refine = False
    doc.recompute()
    return feature, capZ


def growCapA(sketch):
    """A's width and height dimensions set to CAP_A_GROWN: its lines keep their geometry IDs"""
    sketch.setDatum("wA", FreeCAD.Units.Quantity(CAP_A_GROWN, FreeCAD.Units.Length))
    sketch.setDatum("hA", FreeCAD.Units.Quantity(CAP_A_GROWN, FreeCAD.Units.Length))


def farCaps(shape, z):
    """{index name: face} of shape's faces at height z smaller than the plate: the far caps"""
    return {
        "Face%d" % i: f
        for i, f in enumerate(shape.Faces, 1)
        if abs(f.BoundBox.ZMin - z) < 1e-6 and abs(f.BoundBox.ZMax - z) < 1e-6 and f.Area < 50
    }


def farCapAt(shape, z, x, y):
    """The index name of the far cap at height z that holds the point (x, y, z)"""
    point = FreeCAD.Vector(x, y, z)
    names = [n for n, f in farCaps(shape, z).items() if f.isInside(point, 1e-6, True)]
    if len(names) != 1:
        raise AssertionError("far caps at (%g, %g, %g): %s" % (x, y, z, names))
    return names[0]


def pointOnFarCap(feature, sub):
    """A datum point at the centre of mass of feature's face `sub`, the feature kept as the Tip"""
    body = feature.getParentGeoFeatureGroup()
    point = body.newObject("PartDesign::Point", "CapPoint")
    point.AttachmentSupport = [(feature, sub)]
    point.MapMode = "CenterOfMass"
    body.Tip = feature
    feature.Document.recompute()
    return point


def assertOnCap(test, point, z, x, y):
    """The datum point is valid, quiet, and at (x, y, z)"""
    test.assertTrue(point.isValid(), point.getStatusString())
    test.assertEqual(point.getStatusString(), "Valid")
    test.assertLess((point.Placement.Base - FreeCAD.Vector(x, y, z)).Length, 1e-6, point.Placement)


def assertNotQuietlyElsewhere(test, point, z, allowed):
    """ops#360 round 1: the datum point is at one of the `allowed` (x, y) places, or says it lost
    its cap (it is invalid, or its status warns); never valid and quiet on another cap"""
    if point.isValid() and point.getStatusString() == "Valid":
        base = point.Placement.Base
        test.assertTrue(
            any((base - FreeCAD.Vector(x, y, z)).Length < 1e-6 for x, y in allowed),
            "quietly at %s, not at one of %s" % (base, allowed),
        )


def farEdgeAt(shape, z, x, y):
    """ops#386: the index name of shape's edge at height z through the point (x, y, z): a far
    edge's piece, given a point on it away from the up-to shape's edges"""
    point = Part.Vertex(FreeCAD.Vector(x, y, z))
    names = [
        "Edge%d" % i
        for i, e in enumerate(shape.Edges, 1)
        if abs(e.BoundBox.ZMin - z) < 1e-6
        and abs(e.BoundBox.ZMax - z) < 1e-6
        and e.distToShape(point)[0] < 1e-6
    ]
    if len(names) != 1:
        raise AssertionError("far edges at (%g, %g, %g): %s" % (x, y, z, names))
    return names[0]


def centreOfFarEdgeAt(shape, z, x, y):
    """The (x, y) of the centre of mass of the far edge at height z through (x, y, z)"""
    centre = shape.getElement(farEdgeAt(shape, z, x, y)).CenterOfMass
    return centre.x, centre.y


def pointOnFarEdge(feature, sub):
    """A datum point at the centre of mass of feature's edge `sub`, the feature kept as the Tip"""
    body = feature.getParentGeoFeatureGroup()
    point = body.newObject("PartDesign::Point", "EdgePoint")
    point.AttachmentSupport = [(feature, sub)]
    point.MapMode = "CenterOfMass"
    body.Tip = feature
    feature.Document.recompute()
    return point


def replaceUpToShape(feature, shape):
    """The up-to Part feature's shape replaced by `shape`, the feature pointed at all its faces"""
    plate = feature.Document.getObject("Plate")
    plate.Shape = shape
    feature.UpToShape = (plate, ["Face%d" % i for i in range(1, len(shape.Faces) + 1)])


def dimensionedCircle(sketch, tag, x, y, radius):
    """PR 366 round 4: a circle in sketch, its radius named r<tag>, its centre's place x<tag> and
    y<tag>"""
    import Sketcher

    circle = sketch.addGeometry(
        Part.Circle(FreeCAD.Vector(x, y, 0), FreeCAD.Vector(0, 0, 1), radius)
    )
    for kind, arguments, value, name in (
        ("Radius", (circle,), radius, "r"),
        ("DistanceX", (-1, 1, circle, 3), x, "x"),
        ("DistanceY", (-1, 1, circle, 3), y, "y"),
    ):
        constraint = sketch.addConstraint(Sketcher.Constraint(kind, *arguments, value))
        sketch.renameConstraint(constraint, name + tag)


def turnedAboutZ(shape, turn):
    """PR 366 round 5: a copy of `shape` turned by `turn` degrees about the Z axis"""
    turned = shape.copy()
    if turn:
        turned.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), turn)
    return turned


def turnedStripsShape(z, cuts, order, turn, cornersTurned):
    """PR 366 round 5b: freeformStripsShape(z, cuts, order) turned by `turn` degrees about Z, or
    made from its turned corners if `cornersTurned`"""
    if cornersTurned:
        return freeformStripsShape(z, cuts, order, turn)
    return turnedAboutZ(freeformStripsShape(z, cuts, order), turn)


def placeTurned(x, y, turn):
    """PR 366 round 5: the point (x, y) turned by `turn` degrees about the origin"""
    angle = math.radians(turn)
    return (
        x * math.cos(angle) - y * math.sin(angle),
        x * math.sin(angle) + y * math.cos(angle),
    )


def profileUpToFreeformStrips(doc, kind, cuts, draw, turn=0, cornersTurned=False, attach="XY"):
    """PR 366 round 4: a Pad from the profile `draw(sketch)` draws in the XY plane up to the
    B-spline strips freeformStripsShape(z, cuts) at z = 10 (UpToShape, Refine off), or a Pocket
    from it on top of the block x -8..18, y -8..9, z 0..10, down to the strips at z = 4. Round 5:
    the whole model turned by `turn` degrees about Z (the strips and the sketches); round 5b:
    the strips made from turned corners if `cornersTurned`. Round 9: the profile's sketch is
    attached to the XY plane (`attach` "XY"), unattached and placed by its Placement ("none"), or
    attached to a datum plane DP on the XY plane ("datum"). Returns the feature and the height
    of its far caps"""
    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    capZ = 10 if kind == "Pad" else 4
    rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), turn)
    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = turnedStripsShape(capZ, cuts, None, turn, cornersTurned)
    if kind == "Pocket":
        blockSketch = body.newObject("Sketcher::SketchObject", "BlockSketch")
        blockSketch.AttachmentSupport = [(xy, "")]
        blockSketch.MapMode = "FlatFace"
        blockSketch.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(), rotation)
        dimensionedRectangle(blockSketch, "Block", -8, -8, 18, 9)
        blockPad = body.newObject("PartDesign::Pad", "Block")
        blockPad.Profile = blockSketch
        blockPad.Length = 10
    sketch = body.newObject("Sketcher::SketchObject", "Profile")
    placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 10 if kind == "Pocket" else 0), rotation)
    if attach == "none":
        sketch.Placement = placement
    else:
        support = xy
        if attach == "datum":
            support = body.newObject("PartDesign::Plane", "DP")
            support.AttachmentSupport = [(xy, "")]
            support.MapMode = "FlatFace"
        sketch.AttachmentSupport = [(support, "")]
        sketch.MapMode = "FlatFace"
        sketch.AttachmentOffset = placement
    draw(sketch)
    feature = body.newObject("PartDesign::" + kind, kind)
    feature.Profile = sketch
    feature.Type = "UpToShape"
    feature.UpToShape = (plate, ["Face%d" % i for i in range(1, len(plate.Shape.Faces) + 1)])
    feature.Refine = False
    doc.recompute()
    return feature, capZ


def slideOntoReorderedStrips(
    test, kind, cuts, draw, places, datums, order, after, turn=0, cornersTurned=False
):
    """PR 366 round 4: datum points on the pieces of profileUpToFreeformStrips(cuts, draw) at
    `places` ({piece: ("F" or "E", x, y)}), then A's `datums` ({name: value}) set while the
    strips are rebuilt in `order`; each point is then on the piece through one of its `after`
    places or says it lost its piece, never quietly elsewhere. Round 5: the model turned by
    `turn` degrees about Z, the places given unturned; round 5b: the strips made from turned
    corners if `cornersTurned`"""
    doc = FreeCAD.newDocument("PadUpToReorderedStrips")
    try:
        feature, z = profileUpToFreeformStrips(doc, kind, cuts, draw, turn, cornersTurned)
        test.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        points = {}
        for piece, (element, x, y) in places.items():
            x, y = placeTurned(x, y, turn)
            if element == "F":
                points[piece] = pointOnFarCap(feature, farCapAt(shape, z, x, y))
            else:
                points[piece] = pointOnFarEdge(feature, farEdgeAt(shape, z, x, y))
        for name, value in datums.items():
            feature.Profile[0].setDatum(name, FreeCAD.Units.Quantity(value, FreeCAD.Units.Length))
        replaceUpToShape(feature, turnedStripsShape(z, cuts, order, turn, cornersTurned))
        doc.recompute()
        test.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        for piece, allowed in after.items():
            centre = centreOfFarCapAt if places[piece][0] == "F" else centreOfFarEdgeAt
            assertNotQuietlyElsewhere(
                test,
                points[piece],
                z,
                [centre(shape, z, *placeTurned(x, y, turn)) for x, y in allowed],
            )
    finally:
        FreeCAD.closeDocument(doc.Name)


def polygonInSketch(sketch, corners):
    """PR 366 round 6: the closed polygon through `corners` ((x, y) pairs) in sketch"""
    import Sketcher

    start = sketch.GeometryCount
    count = len(corners)
    for i in range(count):
        sketch.addGeometry(
            Part.LineSegment(
                FreeCAD.Vector(*corners[i], 0), FreeCAD.Vector(*corners[(i + 1) % count], 0)
            )
        )
    for i in range(count):
        sketch.addConstraint(
            Sketcher.Constraint("Coincident", start + i, 2, start + (i + 1) % count, 1)
        )


def bsplinePlate(corners):
    """PR 366 round 6: the plane polygon through the (x, y, z) `corners` as a B-spline face"""
    points = [FreeCAD.Vector(*corner) for corner in corners]
    return Part.Face(Part.makePolygon(points + points[:1])).toNurbs().Faces[0]


def foldedPlates(slope, step):
    """PR 366 round 6: the faces at height z, as a function of z, of plate 1 (x -3..1) tilted,
    at z + slope (x - 1); a steep ramp (x 1..1.2) from z to z + step; and plates 2 and 3 (x 1.2..3
    and 3..20) flat at z + step; y -10..10, each a B-spline face"""

    def faces(z):
        def plate(x0, x1, height):
            return bsplinePlate(
                [(x, y, height(x)) for x, y in ((x0, -10), (x1, -10), (x1, 10), (x0, 10))]
            )

        return [
            plate(-3, 1, lambda x: z + slope * (x - 1)),
            plate(1, 1.2, lambda x: z + step * (x - 1) / 0.2),
            plate(1.2, 3, lambda x: z + step),
            plate(3, 20, lambda x: z + step),
        ]

    return faces


def notchedPlates(z):
    """PR 366 round 6: the faces at height z of the L-shaped plate x -10..4, y -10..10 without
    the square x 1..4, y 1..10; that square, in its notch; and the plate x 4..20, y -10..10; each
    a B-spline face"""
    outlines = (
        ((-10, -10), (4, -10), (4, 1), (1, 1), (1, 10), (-10, 10)),
        ((1, 1), (4, 1), (4, 10), (1, 10)),
        ((4, -10), (20, -10), (20, 10), (4, 10)),
    )
    return [bsplinePlate([(x, y, z) for x, y in outline]) for outline in outlines]


def ridgePlates(planar=False):
    """PR 366 round 8: the faces, as a function of z, of a ridge seen from below: plate 1 (x -4..0)
    at z + 2 x and plate 2 (x 0..4.5) at z - 2 x, meeting at x = 0 at 53 degrees; y -10..10. Each
    a B-spline face, or a plane face if `planar`"""

    def faces(z):
        def plate(x0, x1, height):
            corners = [(x, y, height(x)) for x, y in ((x0, -10), (x1, -10), (x1, 10), (x0, 10))]
            if not planar:
                return bsplinePlate(corners)
            points = [FreeCAD.Vector(*corner) for corner in corners]
            return Part.Face(Part.makePolygon(points + points[:1]))

        return [plate(-4, 0, lambda x: z + 2 * x), plate(0, 4.5, lambda x: z - 2 * x)]

    return faces


def seamPlates():
    """PR 366 round 9: the faces, as a function of z, of two plates at z meeting at a seam: x
    -10..0 and 0..10, y -12..12, each a B-spline face"""

    def faces(z):
        def plate(x0, x1):
            return bsplinePlate([(x, y, z) for x, y in ((x0, -12), (x1, -12), (x1, 12), (x0, 12))])

        return [plate(-10, 0), plate(0, 10)]

    return faces


def shellPointAt(shell, x, y):
    """PR 366 round 6: the point of `shell` above or below (x, y)"""
    line = Part.LineSegment(FreeCAD.Vector(x, y, -100), FreeCAD.Vector(x, y, 100)).toShape()
    distance, pairs, _ = shell.distToShape(line)
    if distance > 1e-6:
        raise AssertionError("no point of the shell at (%g, %g)" % (x, y))
    return pairs[0][0]


def farPieceAt(shape, element, point, capMax=50):
    """PR 366 round 6: the index name of shape's far cap ("F", smaller than the plates) or far
    edge ("E") through `point`, a point of the up-to shell inside the piece. Round 8: caps up to
    `capMax` in area (a tilted plate's caps are larger than their plan)"""
    vertex = Part.Vertex(point)
    if element == "F":
        names = [
            "Face%d" % i
            for i, face in enumerate(shape.Faces, 1)
            if face.Area < capMax and face.distToShape(vertex)[0] < 1e-6
        ]
    else:
        names = [
            "Edge%d" % i
            for i, edge in enumerate(shape.Edges, 1)
            if edge.distToShape(vertex)[0] < 1e-6
        ]
    if len(names) != 1:
        raise AssertionError("far pieces (%s) at %s: %s" % (element, point, names))
    return names[0]


def savedFingerprints(path, names):
    """PR 366 round 8: the fingerprint text the saved document at `path` holds for the reference
    of each datum in `names` ({piece: object name}), as written in the file ("" for none)"""
    import xml.etree.ElementTree as ElementTree
    import zipfile

    with zipfile.ZipFile(path) as archive:
        root = ElementTree.fromstring(archive.read("Document.xml"))
    found = {}
    for piece, name in names.items():
        data = root.find("ObjectData/Object[@name='%s']" % name)
        support = data.find("Properties/Property[@name='AttachmentSupport']")
        texts = [node.get("fp") for node in support.iter() if node.get("fp") is not None]
        found[piece] = texts[0] if texts else ""
    return found


def slideOntoReorderedPlates(
    test,
    kind,
    faces,
    draw,
    places,
    move,
    order,
    after,
    reopen=False,
    capMax=50,
    savedInside=(),
    mover="offset",
):
    """PR 366 round 6: as slideOntoReorderedStrips, up to the shell of `faces(z)` (a list of
    B-spline plates; z is the far caps' height where the plates are flat at it): datum points on
    the pieces through the shell's points at `places` ({piece: ("F" or "E", x, y)}), then the
    profile moved by `move` ((dx, dy)) while the shell is rebuilt from its faces in `order`. Each
    point is then on the piece through the shell's point at one of its `after` places (a list)
    or says it lost its piece, never quietly elsewhere; one whose `after` is a single place (a
    tuple) is on that piece, quietly. Round 7: with `reopen`, the document is saved, opened again
    and recomputed before the move (the fingerprints read back from the file). Round 8: with
    `reopen` "untouched", opened again and moved with nothing touched or recomputed first, so
    the references are solved from the fingerprints the file holds, not from new ones; the
    pieces in `savedInside` must have a point inside them in the file (its twelfth field).
    `capMax`: as farPieceAt()'s. Round 9: `mover` says what moves, the profile by its sketch's
    attachment offset ("offset"), by the Placement of its unattached sketch ("placement") or by
    the attachment offset of the datum plane its sketch is attached to ("datum"); or the plates
    the other way, by their feature's Placement ("platesPlacement") or rebuilt there
    ("platesGeometry"). The places are where the shapes are, with their placements"""
    import os
    import tempfile

    attach = {"placement": "none", "datum": "datum"}.get(mover, "XY")
    doc = FreeCAD.newDocument("PadUpToReorderedPlates")
    work = tempfile.mkdtemp(prefix="pad-plates-reopen-") if reopen else None
    try:
        feature, z = profileUpToFreeformStrips(doc, kind, (1, 3), draw, attach=attach)
        replaceUpToShape(feature, Part.Shell(faces(z)))
        doc.recompute()
        test.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        shell = doc.getObject("Plate").Shape
        points = {}
        for piece, (element, x, y) in places.items():
            sub = farPieceAt(shape, element, shellPointAt(shell, x, y), capMax)
            attach = pointOnFarCap if element == "F" else pointOnFarEdge
            points[piece] = attach(feature, sub)
        if reopen:
            path = os.path.join(work, "plates.FCStd")
            doc.saveAs(path)
            names = {piece: point.Name for piece, point in points.items()}
            featureName = feature.Name
            FreeCAD.closeDocument(doc.Name)
            saved = savedFingerprints(path, names)
            for piece in savedInside:
                # Version 6 (ops#522): the inside point, then the up-to faces
                fields = saved[piece].split("|")
                test.assertEqual(len(fields), 13, (piece, saved[piece]))
                test.assertNotEqual(fields[11], "_", (piece, saved[piece]))
            doc = FreeCAD.openDocument(path)
            if reopen != "untouched":
                for obj in doc.Objects:
                    obj.touch()
                doc.recompute()
            feature = doc.getObject(featureName)
            points = {piece: doc.getObject(name) for piece, name in names.items()}
        sketch = feature.Profile[0]
        shift = FreeCAD.Vector(move[0], move[1], 0)

        def moved(placement, by):
            return FreeCAD.Placement(placement.Base + by, placement.Rotation)

        if mover == "offset":
            sketch.AttachmentOffset = moved(sketch.AttachmentOffset, shift)
        elif mover == "placement":
            sketch.Placement = moved(sketch.Placement, shift)
        elif mover == "datum":
            datum = doc.getObject("DP")
            datum.AttachmentOffset = moved(datum.AttachmentOffset, shift)
        plates = faces(z)
        if mover == "platesGeometry":
            matrix = FreeCAD.Matrix()
            matrix.move(-shift)
            plates = [plate.transformGeometry(matrix) for plate in plates]
        replaceUpToShape(feature, Part.Shell([plates[i] for i in order]))
        if mover == "platesPlacement":
            plate = doc.getObject("Plate")
            plate.Placement = moved(plate.Placement, -shift)
        doc.recompute()
        test.assertTrue(feature.isValid(), feature.getStatusString())
        shape = feature.Shape
        shell = doc.getObject("Plate").Shape

        def centre(element, x, y):
            sub = farPieceAt(shape, element, shellPointAt(shell, x, y), capMax)
            return shape.getElement(sub).CenterOfMass

        for piece, allowed in after.items():
            element = places[piece][0]
            point = points[piece]
            base = point.Placement.Base
            if isinstance(allowed, tuple):
                test.assertTrue(point.isValid(), "%s: %s" % (piece, point.getStatusString()))
                test.assertEqual(point.getStatusString(), "Valid", piece)
                test.assertLess((base - centre(element, *allowed)).Length, 1e-6, piece)
            elif point.isValid() and point.getStatusString() == "Valid":
                test.assertTrue(
                    any((base - centre(element, x, y)).Length < 1e-6 for x, y in allowed),
                    "%s quietly at %s, not at one of %s" % (piece, base, allowed),
                )
    finally:
        FreeCAD.closeDocument(doc.Name)
        if work:
            import shutil

            shutil.rmtree(work, ignore_errors=True)


# The child of testPadUpToAFreeformFaceCapsMigrate: opens the saved file, recomputes every object
# (the naming migration), records the datum point, grows A and records it again
_MIGRATION_CHILD = """\
import json, os, traceback
import FreeCAD
out = os.environ["PAD_CAPS_OUT"]
try:
    doc = FreeCAD.openDocument(os.environ["PAD_CAPS_FILE"])
    for obj in doc.Objects:
        obj.touch()
    doc.recompute()
    point = doc.getObject("CapPoint")
    result = {"opened": list(point.Placement.Base), "valid": point.isValid()}
    sketch = doc.getObject("Profile")
    for name in ("wA", "hA"):
        sketch.setDatum(name, FreeCAD.Units.Quantity(%d, FreeCAD.Units.Length))
    doc.recompute()
    result["grown"] = list(point.Placement.Base)
    result["valid"] = result["valid"] and point.isValid()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh)
except Exception:
    with open(out + ".error", "w", encoding="utf-8") as fh:
        fh.write(traceback.format_exc())
os._exit(0)
""" % CAP_A_GROWN


# A split prism's vertices where it meets a freeform up-to face carry the intersection's
# tolerance: 5e-6 up to the loft's side (ops#357). A raise orders of magnitude more is a defect
SPLIT_TOLERANCE = 1e-5


def assertSplitPrismSound(test, prism):
    """A prism built by the split is valid, with tolerances as an intersection gives them"""
    test.assertTrue(prism.isValid())
    test.assertLessEqual(max(v.Tolerance for v in prism.Vertexes), SPLIT_TOLERANCE)
    test.assertLessEqual(max(e.Tolerance for e in prism.Edges), SPLIT_TOLERANCE)


def holdBases(*objects):
    """The shapes the objects hold now, with their toleranceState(). A shape shares its TShapes
    with the object's stored one: a maker that raised them in place changes the held state."""
    return [(o.Name, o.Shape, toleranceState(o.Shape)) for o in objects]


def assertBasesKept(test, held):
    """The held shapes are as they were: the same tolerances, exactly, and curves on surfaces.
    A boolean's refinement moved a tolerance the result shared with the base by an ULP (a Pad up
    to the last face) until refine ran on a copy (ops#354)"""
    for name, shape, before in held:
        test.assertEqual(toleranceState(shape), before, name)


def planarFaceAt(shape, axis, value):
    """The name of the face of shape that lies in the plane at value on the axis (0 x, 1 y, 2 z)"""
    for i, f in enumerate(shape.Faces, 1):
        if f.Surface.TypeId != "Part::GeomPlane":
            continue
        normal = f.normalAt(0, 0)
        if abs(tuple(normal)[axis]) > 1 - 1e-9 and abs(tuple(f.CenterOfMass)[axis] - value) < 1e-6:
            return "Face%d" % i
    raise AssertionError("no planar face at %d = %g" % (axis, value))


def topologyCounts(shape):
    return {
        kind: len(getattr(shape, kind))
        for kind in ("Solids", "Shells", "Faces", "Edges", "Vertexes")
    }


def namedFaces(shape):
    """The area, centre of mass and mapped names of each face of shape that has a mapped name"""
    names = {}
    for mapped, indexed in shape.ElementMap.items():
        if indexed.startswith("Face"):
            names.setdefault(indexed, set()).add(mapped)
    return [
        (shape.getElement(i).Area, shape.getElement(i).CenterOfMass, ns) for i, ns in names.items()
    ]


def assertNamesSurvive(test, source, result, atLeast, apart=()):
    """Each face of source that is a face of result too (the same area and centre of mass) keeps
    its mapped names, and there are atLeast of them: the names of what a feature leaves alone do
    not change with the copies its makers run on (ops#347). The planes (axis, value) in apart
    are the ones the feature meets: its tool's cap on such a face renames it."""
    after = namedFaces(result)
    kept = 0
    for area, centre, names in namedFaces(source):
        if any(abs(tuple(centre)[axis] - value) < 1e-6 for axis, value in apart):
            continue
        for area2, centre2, names2 in after:
            if abs(area - area2) < 1e-6 and (centre - centre2).Length < 1e-6:
                test.assertLessEqual(names, names2, "face at %s" % (tuple(centre),))
                kept += 1
                break
    test.assertGreaterEqual(kept, atLeast)


def assertFacesAllNamed(test, shape):
    mapped = set(shape.ElementMap.values())
    for i in range(1, len(shape.Faces) + 1):
        test.assertIn("Face%d" % i, mapped)


def tabOnNamedBase(test, doc, kind, upTo):
    """ops#347 (review of fork PR 321, round 1): a Pad or Pocket from a sketch outside a base that
    has a real element map (a Pad), up to the base. The base is the box x 0..10, y 5..15, z 0..10;
    the sketch the square x 2..6, z 2..6 on the XZ plane (y = 0). Pad: a 4 x 4 x 5 tab reaching
    the face y = 5 (up to a face, the first or last face, or the base itself as the shape).
    Pocket: the 4 x 4 x 10 hole through the box (up to the face y = 15).
    Checks the result against the box fused with the tab or cut by the hole, made with plain
    Part operations: volume, counts of solids, shells, faces, edges and vertices (an
    uncovered contact would leave the face y = 5 whole, or a second shell), the names of the
    faces and the tolerances of the base."""
    V = FreeCAD.Vector
    body = doc.addObject("PartDesign::Body", "Body")
    baseSketch = body.newObject("Sketcher::SketchObject", "BaseSketch")
    TestSketcherApp.CreateRectangleSketch(baseSketch, (0, 5), (10, 10))
    base = body.newObject("PartDesign::Pad", "Base")
    base.Profile = baseSketch
    base.Length = 10
    doc.recompute()
    test.assertTrue(base.isValid(), base.getStatusString())
    held = holdBases(base)
    xz = [f for f in body.Origin.OriginFeatures if f.Role == "XZ_Plane"][0]
    sketch = body.newObject("Sketcher::SketchObject", "Tab")
    sketch.AttachmentSupport = [(xz, "")]
    sketch.MapMode = "FlatFace"
    TestSketcherApp.CreateRectangleSketch(sketch, (2, 2), (4, 4))
    feature = body.newObject("PartDesign::" + kind, kind)
    feature.Profile = sketch
    feature.Type = upTo
    if upTo == "UpToFace":
        feature.UpToFace = (base, [planarFaceAt(base.Shape, 1, 5 if kind == "Pad" else 15)])
    feature.Reversed = kind == "Pad"
    doc.recompute()
    test.assertTrue(feature.isValid(), feature.getStatusString())
    assertBasesKept(test, held)
    box = Part.makeBox(10, 10, 10, V(0, 5, 0))
    if kind == "Pad":
        expected = box.fuse(Part.makeBox(4, 5, 4, V(2, 0, 2)))
    else:
        expected = box.cut(Part.makeBox(4, 20, 4, V(2, 0, 2)))
    test.assertAlmostEqual(feature.Shape.Volume, expected.Volume, places=6)
    test.assertEqual(topologyCounts(feature.Shape), topologyCounts(expected))
    # The box with the tab: 11 faces (the face y = 5 has the tab's square for a hole), 24 edges,
    # 16 vertexes. With the hole through it: 10 faces, 24 edges, 16 vertexes
    test.assertEqual(
        topologyCounts(feature.Shape),
        {
            "Solids": 1,
            "Shells": 1,
            "Faces": 11 if kind == "Pad" else 10,
            "Edges": 24,
            "Vertexes": 16,
        },
    )
    assertFacesAllNamed(test, feature.Shape)
    # The box's faces that the tool does not meet (those but y = 5 for the Pad, and y = 15 too up
    # to the last face, where the tool's cap lies in it; the 4 sides for the Pocket) and, for the
    # Pad, the tab's 4 sides keep the names the base and the feature's own tool gave them
    if kind == "Pad":
        apart = [(1, 5)] + ([(1, 15)] if upTo == "UpToLast" else [])
        assertNamesSurvive(test, base.Shape, feature.Shape, 6 - len(apart), apart)
        if upTo != "UpToLast":  # the tool to the last face goes on inside the box
            assertNamesSurvive(test, feature.AddSubShape, feature.Shape, 4)
    else:
        assertNamesSurvive(test, base.Shape, feature.Shape, 4)
    return base, feature


def postInTheGap(test, doc, upTo):
    """ops#347 (review of fork PR 321, round 1): a Pad from a sketch on a face of the base (a
    support face is given), up to the face across a gap. The base is a C: the polygon (0,0), (10,0),
    (10,3), (4,3), (4,7), (10,7), (10,10), (0,10) on the XY plane, 10 high. The sketch is on the top
    of the lower arm (y = 3, the first face of the gap), a 2 x 2 square, and the Pad goes up to the
    underside of the upper arm (y = 7) as a face, as the first face, or as the last face (y = 10).
    The post joins the arms: the result is the C and the 2 x 2 x 4 post."""
    V = FreeCAD.Vector
    body = doc.addObject("PartDesign::Body", "Body")
    baseSketch = body.newObject("Sketcher::SketchObject", "BaseSketch")
    points = [V(0, 0), V(10, 0), V(10, 3), V(4, 3), V(4, 7), V(10, 7), V(10, 10), V(0, 10)]
    for start, end in zip(points, points[1:] + points[:1]):
        baseSketch.addGeometry(Part.LineSegment(start, end), False)
    base = body.newObject("PartDesign::Pad", "Base")
    base.Profile = baseSketch
    base.Length = 10
    doc.recompute()
    test.assertTrue(base.isValid(), base.getStatusString())
    held = holdBases(base)
    sketch = body.newObject("Sketcher::SketchObject", "Post")
    sketch.AttachmentSupport = [(base, [planarFaceAt(base.Shape, 1, 3)])]
    sketch.MapMode = "FlatFace"
    # The sketch's x is the world's -x and its y is z, its origin (0, 3, 0): the square x 6..8, z 4..6
    TestSketcherApp.CreateRectangleSketch(sketch, (-8, 4), (2, 2))
    doc.recompute()
    # Where the sketch landed on the lower arm's top: a 2 x 2 square inside the face
    square = Part.Face(sketch.Shape.Wires[0])
    test.assertAlmostEqual(square.Area, 4, places=6)
    test.assertAlmostEqual(square.BoundBox.YMin, 3, places=6)
    test.assertAlmostEqual(square.BoundBox.YMax, 3, places=6)
    test.assertTrue(
        4 <= square.BoundBox.XMin and square.BoundBox.XMax <= 10, "the square is on the face"
    )
    test.assertTrue(0 <= square.BoundBox.ZMin and square.BoundBox.ZMax <= 10)
    feature = body.newObject("PartDesign::Pad", "Pad")
    feature.Profile = sketch
    feature.Type = upTo
    if upTo == "UpToFace":
        feature.UpToFace = (base, [planarFaceAt(base.Shape, 1, 7)])
    doc.recompute()
    test.assertTrue(feature.isValid(), feature.getStatusString())
    assertBasesKept(test, held)
    expected = base.Shape.fuse(square.extrude(V(0, 4, 0)))
    test.assertAlmostEqual(feature.Shape.Volume, base.Shape.Volume + 4 * 4, places=6)
    test.assertAlmostEqual(feature.Shape.Volume, expected.Volume, places=6)
    test.assertEqual(topologyCounts(feature.Shape), topologyCounts(expected))
    test.assertEqual(len(feature.Shape.Solids), 1)
    assertFacesAllNamed(test, feature.Shape)
    # The C's faces away from the post: 8 of its 10 faces (the post meets y = 3 and y = 7, and
    # y = 10 up to the last face)
    apart = [(1, 3), (1, 7)] + ([(1, 10)] if upTo == "UpToLast" else [])
    assertNamesSurvive(test, base.Shape, feature.Shape, 10 - len(apart), apart)
    return base, feature


class TestPad(unittest.TestCase):
    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestPad")

    def testBoxCase(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateSlotPlateSet(self.PadSketch)
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Doc.recompute()
        self.assertEqual(len(self.Pad.Shape.Faces), 6)

    def testSketchOnBasePlane(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.PadSketch.AttachmentSupport = (self.Doc.XY_Plane, [""])
        self.PadSketch.MapMode = "FlatFace"
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateSlotPlateSet(self.PadSketch)
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Body.addObject(self.Pad)
        self.Doc.recompute()
        self.assertEqual(len(self.Pad.Shape.Faces), 6)

    def testSketchOnDatumPlane(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.DatumPlane = self.Doc.addObject("PartDesign::Plane", "DatumPlane")
        self.DatumPlane.AttachmentSupport = (self.Doc.XY_Plane, [""])
        self.DatumPlane.MapMode = "FlatFace"
        self.Body.addObject(self.DatumPlane)
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.PadSketch.AttachmentSupport = (self.DatumPlane, [""])
        self.PadSketch.MapMode = "FlatFace"
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateSlotPlateSet(self.PadSketch)
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Body.addObject(self.Pad)
        self.Doc.recompute()
        self.assertEqual(len(self.Pad.Shape.Faces), 6)

    def testSketchAttachmentDoesNotImportExternalBody(self):
        source_body = self.Doc.addObject("PartDesign::Body", "SourceBody")
        source_box = source_body.newObject("PartDesign::AdditiveBox", "SourceBox")
        source_box.Length = 1
        source_box.Width = 1
        source_box.Height = 1

        target_body = self.Doc.addObject("PartDesign::Body", "TargetBody")
        sketch = target_body.newObject("Sketcher::SketchObject", "SketchPad")
        sketch.AttachmentSupport = (source_body, [""])
        sketch.MapMode = "ObjectXY"
        TestSketcherApp.CreateRectangleSketch(sketch, (2, 0), (1, 1))

        pad = target_body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 1
        self.Doc.recompute()

        self.assertIsNone(pad.BaseFeature)
        self.assertEqual(len(pad.Shape.Solids), 1)
        self.assertAlmostEqual(pad.Shape.Volume, 1)

    def testStartOffsetAndReference(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Pad.StartType = "Offset"
        self.Pad.StartOffset = 2
        self.Pad.Length = 3
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 2.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 5.0)

        reference = self.Doc.addObject("Part::Feature", "Reference")
        outer = Part.makeCylinder(2, 1, Base.Vector(0, 0, 10))
        inner = Part.makeCylinder(1, 1, Base.Vector(0, 0, 10))
        reference.Shape = outer.cut(inner)
        top_face = max(
            range(1, len(reference.Shape.Faces) + 1),
            key=lambda index: reference.Shape.Faces[index - 1].CenterOfMass.z,
        )
        self.Pad.StartReference = (reference, [f"Face{top_face}"])
        self.Pad.StartType = "Reference"
        self.Pad.StartOffset = 2
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 13.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 16.0)

    def testStartReferenceInternalSketchFace(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()

        reference = self.Doc.addObject("Sketcher::SketchObject", "Reference")
        reference.MakeInternals = True
        reference.Placement.Base = Base.Vector(0, 0, 10)
        TestSketcherApp.CreateRectangleSketch(reference, (0, 0), (1, 1))
        self.Doc.recompute()

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 3
        self.Pad.StartReference = (reference, ["InternalFace1"])
        self.Pad.StartType = "Reference"
        self.Pad.StartOffset = 2
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 12.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 15.0)

    def testStartOffsetForTwoSidedAndSymmetricPad(self):
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()

        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = self.PadSketch
        self.Pad.StartType = "Offset"
        self.Pad.StartOffset = 2
        self.Pad.SideType = "Two sides"
        self.Pad.Length = 1
        self.Pad.Length2 = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 1.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 3.0)

        self.Pad.SideType = "Symmetric"
        self.Pad.Length = 4
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMin, 0.0)
        self.assertAlmostEqual(self.Pad.Shape.BoundBox.ZMax, 4.0)

    def testPadToFirstCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 2
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 2.0)

    def testPadtoLastCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0.5, 1), (0.5, 2))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 1
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 3.0)

    def testPadToFaceCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to face on first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 3
        self.Pad1.UpToFace = (self.Pad, ["Face3"])
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 2.0)

    def testPadTwoDimensionsCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to face on first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.SideType = 1
        self.Pad1.Length = 1.0
        self.Pad1.Length2 = 2.0
        self.Pad1.Reversed = 1
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 4.0)

    def testPadToConcaveCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make a half revolution
        self.RevolutionSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.RevolutionSketch)
        TestSketcherApp.CreateRectangleSketch(self.RevolutionSketch, (9, 0), (10, 5))
        self.Doc.recompute()
        self.Revolution = self.Doc.addObject("PartDesign::Revolution", "Revolution")
        self.Body.addObject(self.Revolution)
        self.Revolution.Profile = self.RevolutionSketch
        self.Revolution.ReferenceAxis = (self.RevolutionSketch, ["V_Axis"])
        self.Revolution.Angle = 180
        self.Doc.recompute()
        # Make a sketch and pad to first
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 0), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Type = 2
        self.Pad.Reversed = True
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.Volume, 2208.0963, places=4)

    def testPadToShapeCase(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Length = 1
        self.Doc.recompute()
        # Make second pad on different plane and pad to first
        self.PadSketch1 = self.Doc.addObject("Sketcher::SketchObject", "SketchPad1")
        self.Body.addObject(self.PadSketch1)
        self.PadSketch1.MapMode = "FlatFace"
        self.PadSketch1.AttachmentSupport = (self.Doc.XZ_Plane, [""])
        self.PadSketch1.AttachmentOffset.Rotation.Axis = Base.Vector(0, 1, 0)
        self.PadSketch1.AttachmentOffset.Rotation.Angle = 0.436332  # 25°
        self.PadSketch1.AttachmentOffset.Base.z = 1
        self.Doc.recompute()
        TestSketcherApp.CreateRectangleSketch(self.PadSketch1, (1, 0), (1, 1))
        self.Doc.recompute()
        self.Pad1 = self.Doc.addObject("PartDesign::Pad", "Pad1")
        self.Body.addObject(self.Pad1)
        self.Pad1.Profile = self.PadSketch1
        self.Pad1.Type = 5
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad1.Shape.Volume, 2.58787, places=4)

    def testPadToPlaneCustomDir(self):
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        # Make first offset cube Pad
        self.PadSketch = self.Doc.addObject("Sketcher::SketchObject", "SketchPad")
        self.Body.addObject(self.PadSketch)
        TestSketcherApp.CreateRectangleSketch(self.PadSketch, (0, 1), (1, 1))
        self.Doc.recompute()
        self.Pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        self.Body.addObject(self.Pad)
        self.Pad.Profile = self.PadSketch
        self.Pad.Type = 3
        self.Doc.Pad.UseCustomVector = True
        self.Doc.Pad.Direction = Base.Vector(0, 1, 1)
        self.Pad.UpToFace = (self.Doc.XZ_Plane, [""])
        self.Doc.recompute()
        self.assertAlmostEqual(self.Pad.Shape.Volume, 1.5)

    def _twoSidedUpToPad(self, side1, side2, taper1=0.0, sideType="Two sides"):
        """A 5 x 5 square on XY centred on the origin, padded with SideType `sideType`. A side is
        ("Length", <length>) or ("UpToFace", (<object>, <face>)). Side 1 goes +z, side 2 -z."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = self.Doc.addObject("Sketcher::SketchObject", "Sketch")
        body.addObject(sketch)
        TestSketcherApp.CreateRectangleSketch(sketch, (-2.5, -2.5), (5, 5))
        self.Doc.recompute()
        pad = self.Doc.addObject("PartDesign::Pad", "Pad")
        body.addObject(pad)
        pad.Profile = sketch
        pad.SideType = sideType
        pad.TaperAngle = taper1
        for typeProp, lengthProp, faceProp, (kind, arg) in (
            ("Type", "Length", "UpToFace", side1),
            ("Type2", "Length2", "UpToFace2", side2),
        ):
            setattr(pad, typeProp, kind)
            if kind == "Length":
                setattr(pad, lengthProp, arg)
            else:
                setattr(pad, faceProp, (arg[0], [arg[1]]))
        self.Doc.recompute()
        return pad

    def testPadUpToLinkOfTwoFaces(self):
        """ops#304: an up-to link naming two faces (the planes z = 3 and z = 5 of one box) is an
        error. The Pad went up to the first face named alone, with no error: z = 5 for
        [Face6, Face5], past the nearer face z = 3. One face still works."""
        box = self.Doc.addObject("Part::Box", "Faces")
        box.Placement.Base = FreeCAD.Vector(-5, -5, 3)
        box.Length, box.Width, box.Height = 10, 10, 2
        self.Doc.recompute()
        pad = self._twoSidedUpToPad(
            ("UpToFace", (box, "Face5")), ("Length", 0.0), sideType="One side"
        )
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertAlmostEqual(pad.Shape.Volume, 25 * 3, places=6)
        for faces in (["Face6", "Face5"], ["Face5", "Face6"]):
            with self.subTest(faces=faces):
                pad.UpToFace = (box, faces)
                self.Doc.recompute()
                self.assertFalse(pad.isValid())
                self.assertIn("names several faces", pad.getStatusString())

    def testTwoSidedPadFarCapMarkedWithoutWarning(self):
        """PR 243 follow-up F2: side 1 by length, side 2 up to a face is one prism from side 1's
        end, whose far cap (side 2's end) is marked as side 2's (CPY;2). The Pad warns only when
        the start cap has the profile's names and no far cap name was marked; a far cap up to a
        face wider than the profile, to a plane off to the side, or to a face tilted by 10 degrees
        about the X axis through (0, 0, -10), gets no warning (PR 264 review L2: the tilted far
        cap's names come from the up-to face only, without the PRJ name)."""
        below = self.Doc.addObject("Part::Box", "Below")
        below.Placement.Base = FreeCAD.Vector(-5, -5, -15)
        wall = self.Doc.addObject("Part::Box", "Wall")
        wall.Placement.Base = FreeCAD.Vector(30, 0, -15)
        below.Length, below.Width, below.Height = 10, 10, 5
        wall.Length, wall.Width, wall.Height = 5, 5, 5
        tilt = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 10)
        tilted = self.Doc.addObject("Part::Feature", "Tilted")
        tiltedBox = Part.makeBox(10, 10, 5, FreeCAD.Vector(-5, -5, -15))
        tiltedBox.rotate(FreeCAD.Vector(0, 0, -10), FreeCAD.Vector(1, 0, 0), 10)
        tilted.Shape = tiltedBox
        self.Doc.recompute()
        [tiltedTop] = [
            "Face%d" % (i + 1)
            for i, face in enumerate(tilted.Shape.Faces)
            if face.normalAt(0, 0).isEqual(tilt.multVec(FreeCAD.Vector(0, 0, 1)), 1e-9)
        ]
        cases = (
            ("wider face", (below, "Face6")),
            ("plane off to the side", (wall, "Face6")),
            ("tilted face", (tilted, tiltedTop)),
        )
        for name, upTo in cases:
            with self.subTest(name):
                pad = self._twoSidedUpToPad(("Length", 5.0), ("UpToFace", upTo))
                self.assertTrue(pad.isValid(), pad.getStatusString())
                self.assertAlmostEqual(pad.Shape.Volume, 25 * 15, places=4)
                self.assertNotIn("Warning", pad.State)
                reverse = pad.Shape.ElementReverseMap
                # Its centre is at z = -10 in every case, the tilted one included
                farCaps = [
                    "Face%d" % (i + 1)
                    for i, face in enumerate(pad.Shape.Faces)
                    if abs(face.CenterOfMass.z + 10) < 1e-7 and abs(face.normalAt(0, 0).z) > 0.9
                ]
                self.assertEqual(len(farCaps), 1, farCaps)
                [farCap] = farCaps
                names = reverse.get(farCap)
                names = [names] if isinstance(names, str) else list(names or [])
                marked = f";{pad.ID};CPY;2;"
                self.assertTrue(
                    any(marked in FreeCAD.expandMappedName(n).replace("^", "") for n in names),
                    names,
                )

    def testTwoSidedPadUpToFaceBehindSide(self):
        """ops#73: a side of a two-sided Pad whose up-to face lies behind it is an error naming
        that side. It used to be turned around silently, and the XOR of the sides then cancelled
        the overlap: an empty valid Pad, or one on the wrong side. One side still pads backwards
        to such a face, and a plane off to the side is still reached on the side's own side."""
        # Above: plane z = 10 (Face5, the bottom of a box at z 10..15). Below: plane z = -10
        # (Face6, the top of a box at z -15..-10). Wall: a box off to the side whose Face6 is
        # the plane z = -10, outside the profile's projection.
        top = self.Doc.addObject("Part::Box", "Above")
        top.Placement.Base = FreeCAD.Vector(-5, -5, 10)
        bottom = self.Doc.addObject("Part::Box", "Below")
        bottom.Placement.Base = FreeCAD.Vector(-5, -5, -15)
        wall = self.Doc.addObject("Part::Box", "Wall")
        wall.Placement.Base = FreeCAD.Vector(30, 0, -15)
        for box in (top, bottom, wall):
            box.Length, box.Width, box.Height = 10, 10, 5
        wall.Length = wall.Width = 5
        self.Doc.recompute()
        above = ("UpToFace", (top, "Face5"))
        below = ("UpToFace", (bottom, "Face6"))

        def assertBuilt(pad, volume, zmin, zmax):
            self.assertTrue(pad.isValid(), pad.getStatusString())
            self.assertAlmostEqual(pad.Shape.Volume, volume, places=4)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, zmin, places=6)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, zmax, places=6)

        with self.subTest("control: each face ahead of its side"):
            assertBuilt(self._twoSidedUpToPad(above, below), 25 * 20, -10, 10)
        with self.subTest("a plane off to the side is reached on side 2's side"):
            assertBuilt(self._twoSidedUpToPad(above, ("UpToFace", (wall, "Face6"))), 500, -10, 10)
        with self.subTest("one side pads backwards to a face behind it"):
            pad = self._twoSidedUpToPad(below, ("Length", 0.0), sideType="One side")
            assertBuilt(pad, 250, -10, 0)
        length5 = ("Length", 5.0)
        cases = (
            # (name, side 1, side 2, taper 1, the side named in the error)
            ("both to the face above (two prisms)", above, above, 0.0, "Side 2"),
            ("length, then to the face above (one prism)", length5, above, 0.0, "Side 2"),
            ("tapered length, then to the face above (two prisms)", length5, above, 1.0, "Side 2"),
            ("to the face below, then length (one prism)", below, length5, 0.0, "Side 1"),
        )
        for name, side1, side2, taper1, side in cases:
            with self.subTest(name):
                pad = self._twoSidedUpToPad(side1, side2, taper1)
                self.assertFalse(pad.isValid())
                self.assertIn(side + " can't reach its face", pad.getStatusString())

    def testTwoSidedPadUpToFaceInsideOtherSide(self):
        """ops#73 (option B): an up-to face between the sketch plane and the other side's end is
        an error naming the up-to side, with or without a taper. Without one, the Pad takes a
        one-prism path that starts the up-to side at the other side's end, and it used to build
        a cut-down Pad there (z 3..5 instead of an error). A face beyond the sketch plane still
        builds on both paths."""
        # Inside: plane z = 3 (Face5, the bottom of a box at z 3..8), within side 1 (Length 5).
        # InsideBelow: plane z = -3 (Face6, the top of a box at z -8..-3), within side 2.
        inside = self.Doc.addObject("Part::Box", "Inside")
        inside.Placement.Base = FreeCAD.Vector(-5, -5, 3)
        insideBelow = self.Doc.addObject("Part::Box", "InsideBelow")
        insideBelow.Placement.Base = FreeCAD.Vector(-5, -5, -8)
        for box in (inside, insideBelow):
            box.Length, box.Width, box.Height = 10, 10, 5
        self.Doc.recompute()
        length5 = ("Length", 5.0)
        toInside = ("UpToFace", (inside, "Face5"))
        toInsideBelow = ("UpToFace", (insideBelow, "Face6"))
        errors = (
            # (name, side 1, side 2, taper 1, the side named in the error)
            ("length, then to a face inside side 1 (one prism)", length5, toInside, 0.0, "Side 2"),
            ("tapered length, then to a face inside side 1 (two prisms)", length5, toInside, 1.0,
             "Side 2"),
            ("to a face inside side 2, then length (one prism)", toInsideBelow, length5, 0.0,
             "Side 1"),
        )
        for name, side1, side2, taper1, side in errors:
            with self.subTest(name):
                pad = self._twoSidedUpToPad(side1, side2, taper1)
                self.assertFalse(pad.isValid())
                self.assertIn(side + " can't reach its face", pad.getStatusString())
        with self.subTest("control: length, then to a face beyond the sketch plane (one prism)"):
            pad = self._twoSidedUpToPad(length5, toInsideBelow)
            self.assertTrue(pad.isValid(), pad.getStatusString())
            self.assertAlmostEqual(pad.Shape.Volume, 25 * 8, places=4)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMin, -3, places=6)
            self.assertAlmostEqual(pad.Shape.BoundBox.ZMax, 5, places=6)
        with self.subTest("control: tapered length, then to a face beyond the sketch plane"):
            pad = self._twoSidedUpToPad(length5, toInsideBelow, 1.0)
            self.assertTrue(pad.isValid(), pad.getStatusString())
            box = pad.Shape.optimalBoundingBox(False, False)
            self.assertAlmostEqual(box.ZMin, -3, places=6)
            self.assertAlmostEqual(box.ZMax, 5, places=6)

    def testReselectedRegionsRepairThePad(self):
        """ops#125: a Pad made from two sketch regions breaks when the sketch's circles are
        drawn again elsewhere, and setting its Profile to the new regions repairs it. The fillet
        on it then breaks loudly. The property editor's link dialog sets the Profile this way
        (TestProfileLinkDialog checks the dialog). Without the solver (a file saved before it)
        only with FREECAD_OLD_FILE_TESTS set (decision 179)."""
        for solver in (True, False) if dump.OLD_FILE_TESTS else (True,):
            with self.subTest(solver=solver):
                doc = FreeCAD.newDocument("PartDesignTestPadRegions")
                try:
                    if hasattr(doc, "ReferenceSolver"):
                        doc.ReferenceSolver = solver
                    sketch, pad, fillet = makeRegionPad(doc)
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    self.assertAlmostEqual(pad.Shape.Volume, REGION_PAD_VOLUME, places=4)
                    self.assertAlmostEqual(fillet.Shape.Volume, REGION_FILLET_VOLUME, places=4)

                    redrawBosses(sketch)
                    doc.recompute()
                    self.assertFalse(pad.isValid())
                    self.assertIn("InternalFace", pad.getStatusString())

                    pad.Profile = (sketch, REGIONS)
                    doc.recompute()
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    self.assertEqual(pad.Profile[1], REGIONS)
                    self.assertAlmostEqual(pad.Shape.Volume, REGION_PAD_VOLUME, places=4)
                    self.assertEqual(bossCentres(pad.Shape), [(0.0, -5.0), (0.0, 5.0)])
                    self.assertFalse(fillet.isValid())
                    self.assertIn("Edge", fillet.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToFaceLeavesTheBaseAlone(self):
        # ops#347: BRepFeat runs on copies of the base and the up-to face
        base, pad = upToTheLoftSide(self, self.Doc, "Pad")
        self.assertTrue(pad.Shape.isValid())
        self.assertAlmostEqual(
            pad.Shape.Volume, base.Shape.Volume + pad.AddSubShape.Volume, delta=LOFT_VOLUME_DELTA
        )

    def testPadUpToALoftedFace(self):
        # ops#353: BRepFeat gave an empty prism up to the loft's B-spline side, and the Pad was
        # valid and added nothing. Either way the square faces the side: not reversed, the
        # extrusion is turned towards the face it doesn't find ahead
        expected = loftSideReach(22, -2, 2, 5, 9)
        for reversed in (True, False):
            with self.subTest(reversed=reversed):
                doc = FreeCAD.newDocument("PadUpToALoftedFace")
                try:
                    base, pad = squareUpToTheLoft(doc, "Pad", 22, 5, 9, reversed)
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    self.assertTrue(pad.Shape.isValid())
                    self.assertEqual(len(pad.Shape.Solids), 1)
                    self.assertAlmostEqual(
                        pad.AddSubShape.Volume, expected, delta=PRISM_VOLUME_RELATIVE * expected
                    )
                    self.assertAlmostEqual(
                        pad.Shape.Volume, base.Shape.Volume + expected, delta=LOFT_VOLUME_DELTA
                    )
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToALoftedFaceThatMissesPartOfIt(self):
        # ops#353: the square's top 2 mm pass over the loft (z 11..17, the loft ends at 15), and
        # the side face can't be extended: the Pad fails, saying so, not an empty or cut-down Pad
        base, pad = squareUpToTheLoft(self.Doc, "Pad", 22, 11, 17)
        self.assertFalse(pad.isValid())
        self.assertIn("doesn't meet", pad.getStatusString())

    def testPadUpToALoftedFaceWhoseRimIsInTheWay(self):
        # ops#353 review H1: the 4 x 3 rectangle at x = 22, z 14.5..17.5, along (-1, 0, -0.15).
        # At the near side (x about 12) its z is 13..16, and the loft's top rim (z 15) crosses
        # it: the lower part meets the side there, the upper part passes over the rim to the far
        # side (z about 9.4..12.4). The split left the near patch inside one solid reaching the
        # far side: a valid Pad through the loft (AddSubShape about 400, two internal faces). It
        # fails, saying why
        base, pad = squareUpToTheLoft(
            self.Doc, "Pad", 22, 14.5, 17.5, False, FreeCAD.Vector(-1, 0, -0.15)
        )
        self.assertFalse(pad.isValid())
        self.assertIn("lies in the profile's way", pad.getStatusString())

    def testPadUpToAShapeThroughAHole(self):
        # ops#353 review H1: the front plate stops the square except where its hole lies in the
        # square's way. The split left the holed plate inside one solid reaching the middle
        # plate: a valid Pad of 4 x 4 x 17 = 272 through the front plate. It fails, saying why
        for holed in (False, True):
            with self.subTest(holed=holed):
                doc = FreeCAD.newDocument("PadUpToAShapeThroughAHole")
                try:
                    pad = squareUpToPlates(doc, holed)
                    if holed:
                        self.assertFalse(pad.isValid())
                        self.assertIn("lies in the profile's way", pad.getStatusString())
                    else:
                        # The front plate stops all of it: 4 x 4 x 7
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        self.assertAlmostEqual(pad.AddSubShape.Volume, 112, places=6)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToABallBeforePlates(self):
        # PR 324 round 1 verification: the ball stops the square's middle, whose lines first meet
        # its near side. The split kept one solid up to the middle plate with the ball as a
        # cavity: a valid Pad of 4 x 4 x 17 less the ball (267.81), filling the ball's shadow,
        # with no internal face. It fails, saying why
        pad = squareUpToABallBeforePlates(self.Doc)
        self.assertFalse(pad.isValid())
        self.assertIn("meets the face from behind", pad.getStatusString())

    def testPadUpToABaseWithAnUndercut(self):
        # PR 324 round 1 verification: the square x, y -6..6 passes the bulb's widest point
        # (radius 4 at z = 6); lines at radius 2..4 first meet its lower half. The split kept one
        # solid up to the plate around the bulb, filling the undercut above its widest point
        # (1871.8). It fails, saying why. The square x, y -1..1 meets only the bulb's bottom and
        # stops there: 2 x 2 x 7
        for half in (1, 6):
            with self.subTest(half=half):
                doc = FreeCAD.newDocument("PadUpToABaseWithAnUndercut")
                try:
                    pad = padUpToAPlateWithABulb(doc, half)
                    if half == 1:
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        self.assertAlmostEqual(pad.AddSubShape.Volume, 28, places=6)
                    else:
                        self.assertFalse(pad.isValid())
                        self.assertIn("meets the face from behind", pad.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToABaseWithANarrowUndercut(self):
        # PR 324 round 2 verification: the square x, y -6..6 passes the boss's widest point
        # (radius 4 at z = -0.1); lines at radius 3.9..4 first meet its side below that, and the
        # lip above it faces the plate. Sampled evenly (16 x 16 over the face's range), the lip
        # was missed: the split kept one solid up to the plate, filling the undercut (1866.15).
        # It fails, saying why. The square x, y -1..1 meets only the boss's bottom and stops
        # there: 2 x 2 x 5
        for half in (1, 6):
            with self.subTest(half=half):
                doc = FreeCAD.newDocument("PadUpToABaseWithANarrowUndercut")
                try:
                    pad = padUpToAPlateWithALippedBoss(doc, half)
                    if half == 1:
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        self.assertAlmostEqual(pad.AddSubShape.Volume, 20, places=6)
                    else:
                        self.assertFalse(pad.isValid())
                        self.assertIn("meets the face from behind", pad.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadFromAFaceOfTheBaseUpToTheBaseWithAFreeformFace(self):
        # PR 324 round 2 verification: the square on the lower arm's top is a piece of the base,
        # and the splitter made it one face with the extrusion's start, facing against the
        # direction: the Pad failed, "meets the face from behind". The post joins the arms: the
        # result is the base and the 2 x 2 x 4 post
        V = FreeCAD.Vector
        base, pad = postInTheGapOfACWithABump(self.Doc)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        self.assertEqual(len(pad.Shape.Solids), 1)
        self.assertAlmostEqual(pad.AddSubShape.Volume, 16, places=6)
        # GProp's volume of the base with the bump's B-spline side varies by 5e-7
        self.assertAlmostEqual(pad.Shape.Volume, base.Shape.Volume + 16, delta=1e-5)
        post = Part.makeBox(2, 4, 2, V(6, 3, 4))
        self.assertAlmostEqual(pad.Shape.common(post).Volume, 16, places=6)

    def testPadUpToAShapeWithAnUnrelatedFreeformFace(self):
        # ops#353 review M2: up to a whole base, a freeform face the Pad can't meet doesn't change
        # how the Pad is built. With the loft's side in the base, the Pad went to the split, and
        # its top face was named from the far ends of the profile's edges (LOW), not projected
        # from the profile's face (PRJ) as BRepFeat names it
        import re

        def masked(shape):
            count = len(shape.Faces)
            names = (shape.getElementMappedName("Face%d" % i) for i in range(1, count + 1))
            return sorted(re.sub(r";\d+;", ";#;", re.sub(r"~[0-9a-z]+", "~", n)) for n in names)

        results = []
        for withLoft in (False, True):
            doc = FreeCAD.newDocument("PadUpToAShapeWithAnUnrelatedFreeformFace")
            try:
                pad = padUpToABoxBesideALoft(doc, withLoft)
                self.assertTrue(pad.isValid(), pad.getStatusString())
                self.assertAlmostEqual(pad.AddSubShape.Volume, 80, places=6)
                results.append(masked(pad.AddSubShape))
            finally:
                FreeCAD.closeDocument(doc.Name)
        self.assertEqual(results[1], results[0])

    def testPadUpToABaseItOverhangs(self):
        # ops#356: the square x 33..37 under the box x 10..35, half of it beside the box, up to
        # the base. BRepFeat (the base's faces are planar) extruded all of the square to
        # z = 155, through the box: a valid Pad, AddSubShape 2480. It fails as the split fails
        # (the base with the loft's side), saying why. The square x 25..29, all under the box,
        # stops at its bottom as before (4 x 4 x 5)
        for withLoft in (False, True):
            for x0 in (25, 33):
                with self.subTest(withLoft=withLoft, x0=x0):
                    doc = FreeCAD.newDocument("PadUpToABaseItOverhangs")
                    try:
                        pad = padUpToABoxBesideALoft(doc, withLoft, x0)
                        if x0 == 25:
                            self.assertTrue(pad.isValid(), pad.getStatusString())
                            self.assertAlmostEqual(pad.AddSubShape.Volume, 80, places=6)
                        else:
                            self.assertFalse(pad.isValid())
                            self.assertIn("doesn't meet", pad.getStatusString())
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToARevolvedFaceItOverhangs(self):
        # ops#353 review M1: the rectangle y -8..14 passes the face's edge (y about 11 where it
        # meets it). The retry without the face's limits went up to the whole surface of
        # revolution, which stopped the part beside the face on the surface past its edge: a
        # valid Pad. It fails now, with the first try's error. The rectangle y -6..6 lies all in
        # front of the face and is built as before, up to the face (revolvedFaceReach())
        for y0, y1 in ((-6, 6), (-8, 14)):
            with self.subTest(y0=y0, y1=y1):
                doc = FreeCAD.newDocument("PadUpToARevolvedFaceItOverhangs")
                try:
                    pad = padUpToARevolvedFace(doc, y0, y1)
                    if y1 == 6:
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        self.assertTrue(pad.AddSubShape.isValid())
                        expected = revolvedFaceReach(y0, y1, 4, 8)
                        self.assertAlmostEqual(
                            pad.AddSubShape.Volume,
                            expected,
                            delta=PRISM_VOLUME_RELATIVE * expected,
                        )
                    else:
                        self.assertFalse(pad.isValid())
                        self.assertIn("doesn't meet", pad.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToARevolvedFaceOnTheFarSide(self):
        # ops#357 (ops#353 review M1, the case it guards against): the face is on the far side of
        # the axis, and the rectangle y 0..10 reaches it through the surface's inside (1211.8).
        # The rectangle y -8..14 passes the face's edge: without its limits, the whole surface
        # would stop all of it at the near side, a valid Pad of the wrong shape (the whole
        # surface itself gives the near side's 392.1). It fails, with the first try's error
        expected = revolvedFaceReach(0, 10, 8, 10, far=True)
        for y0, y1, whole in ((0, 10, False), (-8, 14, False), (0, 10, True)):
            with self.subTest(y0=y0, y1=y1, whole=whole):
                doc = FreeCAD.newDocument("PadUpToARevolvedFaceOnTheFarSide")
                try:
                    pad = padUpToARevolvedFace(doc, y0, y1, far=True, whole=whole)
                    if y1 == 14:
                        self.assertFalse(pad.isValid())
                        self.assertIn("doesn't meet", pad.getStatusString())
                        continue
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    assertSplitPrismSound(self, pad.AddSubShape)
                    reach = revolvedFaceReach(0, 10, 8, 10) if whole else expected
                    self.assertAlmostEqual(
                        pad.AddSubShape.Volume, reach, delta=PRISM_VOLUME_RELATIVE * reach
                    )
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToATrimmedFaceWithoutItsLimits(self):
        # ops#357: the square passes the trimmed face, within its surface. The first try, up to
        # the face, fails; the retry up to the face without its limits (the whole plate) builds
        # it: 24 x 17, reaching the plate past the face (y up to 4.7). The whole plate is the
        # control
        for trimmed in (False, True):
            with self.subTest(trimmed=trimmed):
                doc = FreeCAD.newDocument("PadUpToATrimmedFaceWithoutItsLimits")
                try:
                    pad = padUpToATrimmedPlate(doc, trimmed)
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    assertSplitPrismSound(self, pad.AddSubShape)
                    self.assertAlmostEqual(pad.AddSubShape.Volume, 408, places=6)
                    box = pad.Shape.optimalBoundingBox(False, False)
                    self.assertAlmostEqual(box.XMin, 5, places=6)
                    self.assertAlmostEqual(box.YMax, 4.7, places=6)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToABallUnderAPlate(self):
        # ops#357: the square x, y -6..6 passes the ball's equator (radius 5 at z = -0.1); lines
        # at radius 4.999..5 first meet the ball below it, and the band above it faces the plate.
        # The grid's last row on the sphere face lies under the equator: the split kept one solid
        # up to the plate, filling the band's shadow (0.001). It fails, saying why. The control,
        # the square x, y -1..1, misses the knob, so BRepFeat builds it (only planes and the
        # sphere in its path), up to the ball's bottom
        for half in (1, 6):
            with self.subTest(half=half):
                doc = FreeCAD.newDocument("PadUpToABallUnderAPlate")
                try:
                    pad = padUpToABallUnderAPlate(doc, half)
                    if half == 1:
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        expected = ballBottomReach(1)
                        self.assertAlmostEqual(
                            pad.AddSubShape.Volume,
                            expected,
                            delta=PRISM_VOLUME_RELATIVE * expected,
                        )
                    else:
                        self.assertFalse(pad.isValid())
                        self.assertIn("meets the face from behind", pad.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToABallUnderAPlateOfElementaryFaces(self):
        # ops#361: testPadUpToABallUnderAPlate() without the knob, so the Pad goes by BRepFeat
        # (planes and spheres only), up to the base, up to the ball's lower face and the plate's
        # bottom, and with a second side 3 long. BRepFeat filled the band's shadow (0.00105): a
        # valid Pad, 1890.35. It fails as with the knob, saying why. The control, the square
        # x, y -1..1, stops at the ball's bottom (and reaches 3 below the sketch)
        for faces, length2 in ((False, None), (True, None), (False, 3)):
            for half in (1, 6):
                with self.subTest(faces=faces, length2=length2, half=half):
                    doc = FreeCAD.newDocument("PadUpToABallUnderAPlateOfElementaryFaces")
                    try:
                        pad = padUpToABallUnderAPlate(doc, half, False, faces, length2)
                        if half == 1:
                            self.assertTrue(pad.isValid(), pad.getStatusString())
                            expected = ballBottomReach(1) + 4 * (length2 or 0)
                            self.assertAlmostEqual(
                                pad.AddSubShape.Volume,
                                expected,
                                delta=PRISM_VOLUME_RELATIVE * expected,
                            )
                            shadow = pad.AddSubShape.common(ballBandShadow())
                            self.assertAlmostEqual(shadow.Volume, 0, places=9)
                        else:
                            self.assertFalse(pad.isValid())
                            self.assertIn("meets the face from behind", pad.getStatusString())
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadOfTwoSquaresUpToACylinderOfElementaryFaces(self):
        # ops#450 (fork PR 359 review, finding 1): the cylinder of radius 6 about the line y = 0,
        # z = 10 (x -20..20), and a Pad of the squares x -8..-4 and 4..8, y -3..3 at z = 0, along
        # +z, up to its cylinder face. Each square goes up to the cylinder's underside, z = 10 -
        # sqrt(36 - y^2): 4 (60 - integral of sqrt(36 - y^2) over y -3..3) = 4 (60 - 3 sqrt(27) -
        # 6 pi) each, 204.50 for both. BRepFeat built the second square up to the slab inside the
        # cylinder, whose lower face faces back: a valid Pad, 377.75. fillsBehind() sends it to
        # the split, which builds it right
        doc = FreeCAD.newDocument("PadOfTwoSquaresUpToACylinderOfElementaryFaces")
        try:
            V = FreeCAD.Vector
            cylinder = Part.makeCylinder(6, 40, V(-20, 0, 10), V(1, 0, 0))
            base = doc.addObject("Part::Feature", "Base")
            base.Shape = cylinder
            body = doc.addObject("PartDesign::Body", "Body")
            baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
            baseFeature.BaseFeature = base
            doc.recompute()
            names = [
                "Face%d" % i
                for i, face in enumerate(baseFeature.Shape.Faces, 1)
                if face.Surface.TypeId == "Part::GeomCylinder"
            ]
            sketch = squareSketch(
                body, "Squares", FreeCAD.Placement(), [(-8, -3, -4, 3), (4, -3, 8, 3)]
            )
            pad = body.newObject("PartDesign::Pad", "Pad")
            pad.Profile = sketch
            pad.Type = "UpToFace"
            pad.UpToFace = (baseFeature, names)
            doc.recompute()
            self.assertTrue(pad.isValid(), pad.getStatusString())
            expected = 2 * 4 * (60 - 3 * math.sqrt(27) - 6 * math.pi)
            self.assertAlmostEqual(
                pad.AddSubShape.Volume, expected, delta=PRISM_VOLUME_RELATIVE * expected
            )
            self.assertAlmostEqual(pad.AddSubShape.common(cylinder).Volume, 0, places=6)
            whole = cylinder.Volume + expected
            self.assertAlmostEqual(pad.Shape.Volume, whole, delta=PRISM_VOLUME_RELATIVE * whole)
        finally:
            FreeCAD.closeDocument(doc.Name)

    def testPadUpToABumpOverABallsEquator(self):
        # PR 331 round 1: the bump rises 0.3 over the equator, so a band of the sphere face up to
        # 0.29 high faces the plate, along 1 to 2 % of the face's edge with the plate. With 32
        # samples per edge, 3 % apart, the band was missed at these angles: the Pad was valid and
        # filled the band's shadow (8e-3 across). It fails, saying why. Under a bump 0.15 high,
        # which stays below the equator, the Pad stops at the ball and the plate: the control.
        # Its split edges carry the intersection's tolerance (4e-3), so it is checked by points:
        # outside the ball under the bump's centre, whose bottom is at z -0.052 there, the prism
        # reaches z -0.1 and not z 0
        import math

        for theta, length, height in ((42, 0.25, 0.5), (22, 0.12, 0.5), (42, 0.25, 0.15)):
            with self.subTest(theta=theta, length=length, height=height):
                doc = FreeCAD.newDocument("PadUpToABumpOverABallsEquator")
                try:
                    pad = padUpToABumpOverABall(doc, theta, length, height)
                    if height == 0.15:
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        prism = pad.AddSubShape
                        self.assertTrue(prism.isValid())
                        c, s = math.cos(math.radians(theta)), math.sin(math.radians(theta))
                        for z, inPrism in ((-0.1, True), (0.0, False)):
                            point = FreeCAD.Vector(5.05 * c, 5.05 * s, z)
                            self.assertEqual(prism.isInside(point, 1e-9, False), inPrism, z)
                    else:
                        self.assertFalse(pad.isValid())
                        self.assertIn("meets the face from behind", pad.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAnApproximatedWall(self):
        # ops#357: the wall lofted to a B-spline through 256 points of its circle leans by 5e-8
        # over its 5 under the plate, below Precision::Confusion(): the square stops at the plate
        # around it and at the wall's bottom inside it, as for a vertical wall. Under the strict
        # bound it failed as meeting the face from behind. Through 64 points it leans by 1.7e-5,
        # a fold at modelling precision, and still fails
        import math

        exact = 12 * 12 * 15 - math.pi * 25 * 5
        for points in (256, 64):
            with self.subTest(points=points):
                doc = FreeCAD.newDocument("PadUpToAnApproximatedWall")
                try:
                    pad = padUpToALoftedWall(doc, points)
                    if points == 256:
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        assertSplitPrismSound(self, pad.AddSubShape)
                        self.assertAlmostEqual(
                            pad.AddSubShape.Volume, exact, delta=PRISM_VOLUME_RELATIVE * exact
                        )
                    else:
                        self.assertFalse(pad.isValid())
                        self.assertIn("meets the face from behind", pad.getStatusString())
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToALoftedFaceFromSeveralFaces(self):
        # ops#357: two rectangles, and a rectangle with a hole, up to the loft's side: one prism
        # per face, each its own volume, the hole's taken out. Each far cap is the projection
        # (PRJ) of its own profile face, no longer a piece of the side told apart from the other
        # by a counter in the result's face order (ops#360)
        cases = {
            "two": [(-3, 3, -1, 5), (1, 7, 3, 10)],
            "hole": [(-2, 4, 2, 10), (-1, 6, 1, 8)],
        }
        expected = {
            "two": loftSideReach(22, -3, -1, 3, 5) + loftSideReach(22, 1, 3, 7, 10),
            "hole": loftSideReach(22, -2, 2, 4, 10) - loftSideReach(22, -1, 1, 6, 8),
        }
        for kind, rectangles in cases.items():
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToALoftedFaceFromSeveralFaces")
                try:
                    pad = padUpToTheLoftFrom(doc, rectangles)
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    prism = pad.AddSubShape
                    assertSplitPrismSound(self, prism)
                    self.assertEqual(len(prism.Solids), 2 if kind == "two" else 1)
                    self.assertAlmostEqual(
                        prism.Volume, expected[kind], delta=PRISM_VOLUME_RELATIVE * expected[kind]
                    )
                    assertFacesAllNamed(self, prism)
                    caps = [
                        prism.getElementMappedName("Face%d" % i)
                        for i, f in enumerate(prism.Faces, 1)
                        if f.Surface.TypeId == "Part::GeomBSplineSurface"
                    ]
                    self.assertEqual(len(caps), 2 if kind == "two" else 1)
                    self.assertEqual(len(set(caps)), len(caps))
                    self.assertTrue(all(";PRJ;" in name for name in caps), caps)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToALoftedFaceNames(self):
        # ops#357 (ops#334's rule for the split): the side faces are generated from the sketch's
        # edges, and the far cap's edges and vertices are the projections of the sketch's edges
        # and vertices (PRJ), not generated from the side faces, where the solver took a far edge
        # for the sketch's own. The far cap is the projection of the sketch's face (ops#360), no
        # longer the piece of the up-to face
        base, pad = squareUpToTheLoft(self.Doc, "Pad", 22, 5, 9)
        self.assertTrue(pad.isValid(), pad.getStatusString())
        prism = pad.AddSubShape
        assertSplitPrismSound(self, prism)
        assertFacesAllNamed(self, prism)
        cap = next(
            i
            for i, f in enumerate(prism.Faces, 1)
            if f.Surface.TypeId == "Part::GeomBSplineSurface"
        )
        self.assertIn(";PRJ;", prism.getElementMappedName("Face%d" % cap))
        sides = [
            i
            for i, f in enumerate(prism.Faces, 1)
            if i != cap and abs(f.CenterOfMass.x - 22) > 1e-6
        ]
        self.assertEqual(len(sides), 4)
        for i in sides:
            self.assertIn(";GEN;", prism.getElementMappedName("Face%d" % i))
        capFace = prism.Faces[cap - 1]
        for i, edge in enumerate(prism.Edges, 1):
            if any(edge.isSame(e) for e in capFace.Edges):
                self.assertIn(";PRJ;", prism.getElementMappedName("Edge%d" % i), "Edge%d" % i)
        for i, vertex in enumerate(prism.Vertexes, 1):
            if any(vertex.isSame(v) for v in capFace.Vertexes):
                # Where the loft's seam crosses the far edges, the vertices are generated, and
                # named by the side of the face the edge goes to there, with ORD (ops#468)
                name = prism.getElementMappedName("Vertex%d" % i)
                self.assertTrue(";PRJ;" in name or ";GEN;" in name or ";GEN,ORD;" in name, name)

    def testPadUpToAFreeformFaceCapsStayOnTheirFaces(self):
        # ops#360: the split named the far caps from the plate alone (MOD), told apart by a
        # counter in the result's face order, which follows the profile's faces, sorted by
        # area. A grown past B came first, and a datum on A's cap went to B's, valid and with no
        # warning: (6.5, 1.5, z). Each cap is now the projection of its own profile face
        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToAFreeformFaceCaps")
                try:
                    feature, z = capsUpToAFreeformPlate(doc, kind)
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    point = pointOnFarCap(feature, farCapAt(feature.Shape, z, 1, 1))
                    self.assertTrue(point.isValid(), point.getStatusString())
                    self.assertLess((point.Placement.Base - FreeCAD.Vector(1, 1, z)).Length, 1e-6)
                    growCapA(feature.Profile[0])
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    self.assertTrue(point.isValid(), point.getStatusString())
                    centre = CAP_A_GROWN / 2
                    self.assertLess(
                        (point.Placement.Base - FreeCAD.Vector(centre, centre, z)).Length,
                        1e-6,
                        point.Placement.Base,
                    )
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformFaceCapNames(self):
        # ops#360: each far cap is the projection (PRJ) of its own profile face, as BRepFeat
        # names the top, not a piece of the plate (MOD); the two differ, and each keeps its name
        # when A grows past B. The Pocket's floors are the caps' names modified by the cut
        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToAFreeformFaceCapNames")
                try:
                    feature, z = capsUpToAFreeformPlate(doc, kind)
                    caps = farCaps(feature.Shape, z)
                    self.assertEqual(len(caps), 2)
                    names = {n: feature.Shape.getElementMappedName(n) for n in caps}
                    for name in names.values():
                        self.assertIn(";PRJ;", name)
                        self.assertNotIn(";MOD;", name.split(";PRJ;")[-1])
                    self.assertEqual(len(set(names.values())), 2, names)
                    before = {
                        "A": names[farCapAt(feature.Shape, z, 1, 1)],
                        "B": names[farCapAt(feature.Shape, z, 6.5, 1.5)],
                    }
                    growCapA(feature.Profile[0])
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    shape = feature.Shape
                    after = {
                        "A": shape.getElementMappedName(farCapAt(shape, z, 2, 2)),
                        "B": shape.getElementMappedName(farCapAt(shape, z, 6.5, 1.5)),
                    }
                    self.assertEqual(after, before)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformShellCapsStayOnTheirFaces(self):
        # ops#360: up to a shell of two B-spline faces meeting at x = 1, under A's middle, A's
        # cap is two pieces: each a projection of A, marked by the shell's face it lies on (and
        # the edges that bound it where B's cap shares the face, round 2), with MOD among its
        # flags (PR 340 round 1); B's is a
        # projection of B, unmarked. Datums
        # on A's pieces stay there when A grows past B. When A moves onto the left face only,
        # its right piece is gone, and its datum must not land on another cap quietly: named
        # from the shell (MOD) it went to B's cap, and told apart by a counter alone to A's
        # left piece, valid and with no warning both times
        for edit in ("grow", "offTheRightFace"):
            with self.subTest(edit=edit):
                doc = FreeCAD.newDocument("PadUpToAFreeformShellCaps")
                try:
                    feature, z = capsUpToAFreeformPlate(doc, "Pad", seam=1)
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    shape = feature.Shape
                    self.assertEqual(len(farCaps(shape, z)), 3)
                    left = shape.getElementMappedName(farCapAt(shape, z, 0.5, 1))
                    right = shape.getElementMappedName(farCapAt(shape, z, 1.5, 1))
                    other = shape.getElementMappedName(farCapAt(shape, z, 6.5, 1.5))
                    for name, flags in ((left, {"PRJ", "MOD"}), (right, {"PRJ", "MOD"})):
                        top = FreeCAD.getDecodedMappedName(name)[-1]
                        self.assertEqual(set(top["mapperFlags"]), flags, name)
                        self.assertTrue(top["connectedElements"], name)
                    self.assertEqual(
                        FreeCAD.getDecodedMappedName(other)[-1]["mapperFlags"], ["PRJ"], other
                    )
                    self.assertEqual(len({left, right, other}), 3)
                    leftPoint = pointOnFarCap(feature, farCapAt(shape, z, 0.5, 1))
                    rightPoint = pointOnFarCap(feature, farCapAt(shape, z, 1.5, 1))
                    sketch = feature.Profile[0]
                    if edit == "grow":
                        growCapA(sketch)
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        assertOnCap(self, leftPoint, z, 0.5, CAP_A_GROWN / 2)
                        assertOnCap(self, rightPoint, z, 2.5, CAP_A_GROWN / 2)
                        shape = feature.Shape
                        self.assertEqual(
                            shape.getElementMappedName(farCapAt(shape, z, 0.5, 1)),
                            left,
                            "A's left piece",
                        )
                    else:
                        sketch.setDatum("xA", FreeCAD.Units.Quantity(-3, FreeCAD.Units.Length))
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        self.assertEqual(len(farCaps(feature.Shape, z)), 2)
                        assertNotQuietlyElsewhere(self, rightPoint, z, [])
                        assertNotQuietlyElsewhere(self, leftPoint, z, [(-2, 1)])
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformShellCapPieceAppears(self):
        # ops#360 round 1: A at x 2..4 lies on the shell's right face only, one cap. Moved to
        # x 0..2, it crosses the faces' seam at x = 1, and its cap is two pieces. A datum on its
        # cap stays on the right face's piece, or says it moved: told apart by a counter alone,
        # it went to the new left piece, valid and with no warning
        feature, z = capsUpToAFreeformPlate(self.Doc, "Pad", seam=1, capA=(2, 0, 4, 2))
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertEqual(len(farCaps(feature.Shape, z)), 2)
        point = pointOnFarCap(feature, farCapAt(feature.Shape, z, 3, 1))
        sketch = feature.Profile[0]
        sketch.setDatum("xA", FreeCAD.Units.Quantity(0, FreeCAD.Units.Length))
        self.Doc.recompute()
        self.assertTrue(feature.isValid(), feature.getStatusString())
        self.assertEqual(len(farCaps(feature.Shape, z)), 3)
        assertNotQuietlyElsewhere(self, point, z, [(1.5, 1)])

    def testPadUpToAFreeformHoleCapPieces(self):
        # ops#360 round 1: up to a B-spline plate with a hole x -1..1, y -2..2 and the hole's
        # fill, A (x -3..3, y -0.5..0.5) crosses the fill: three pieces, left and right on the
        # plate, the middle on the fill. Each is marked by its face, and the left and right ones,
        # which share the plate with B's cap, by the hole's edge that bounds them (round 2).
        # A piece whose marks stay keeps its datum when A changes; a datum on a piece that is
        # gone, or whose bounds changed, must not land on another piece quietly. Told apart by
        # a counter alone, the left one's went to the right piece and the right one's to the
        # middle when the left piece went
        cases = {
            # A x -4..3: all three pieces stay, the left one wider
            "wider": ((-4, 7), {"left": [(-2.5, 0)], "middle": [(0, 0)], "right": [(2, 0)]}),
            # A x -0.5..4.5: the left piece is gone, the middle one shorter
            "leftGone": ((-0.5, 5), {"left": [], "middle": [(0.25, 0)], "right": [(2.75, 0)]}),
            # A x -5..0.5: the right piece is gone
            "rightGone": ((-5, 5.5), {"left": [(-3, 0)], "middle": [(-0.25, 0)], "right": []}),
        }
        # Pieces whose bounds stay the same keep their names: their datums stay, quietly
        unchanged = {
            "wider": ("left", "middle", "right"),
            "leftGone": ("right",),
            "rightGone": ("left",),
        }
        for case, ((xA, wA), expected) in cases.items():
            with self.subTest(case=case):
                doc = FreeCAD.newDocument("PadUpToAFreeformHoleCapPieces")
                try:
                    feature, z = capsUpToAFreeformPlate(
                        doc, "Pad", hole=True, capA=(-3, -0.5, 3, 0.5)
                    )
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    shape = feature.Shape
                    self.assertEqual(len(farCaps(shape, z)), 4)
                    places = {"left": (-2, 0), "middle": (0, 0), "right": (2, 0)}
                    names = {
                        piece: shape.getElementMappedName(farCapAt(shape, z, x, y))
                        for piece, (x, y) in places.items()
                    }
                    self.assertEqual(len(set(names.values())), 3, names)
                    points = {
                        piece: pointOnFarCap(feature, farCapAt(shape, z, x, y))
                        for piece, (x, y) in places.items()
                    }
                    sketch = feature.Profile[0]
                    sketch.setDatum("wA", FreeCAD.Units.Quantity(wA, FreeCAD.Units.Length))
                    sketch.setDatum("xA", FreeCAD.Units.Quantity(xA, FreeCAD.Units.Length))
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    for piece, allowed in expected.items():
                        if piece in unchanged[case]:
                            assertOnCap(self, points[piece], z, *allowed[0])
                        else:
                            assertNotQuietlyElsewhere(self, points[piece], z, allowed)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAnEllipticHoleTwinPieces(self):
        # PR 340 round 2: the disc's top and bottom pieces on the plate are bounded by the circle
        # and the ellipse alone, so their marks are the same; the round 1 build told them apart
        # by the splitter's order alone. With the ellipse rebuilt turned by 180 degrees (the same
        # faces, its edge starting on the other side) the two datums swapped pieces, and with the
        # disc moved down so that the top piece is gone, the top's datum went to the bottom
        # piece, valid and with no warning both times. Now they are ordered by their centres
        # (the datums stay), and their duplicate counter holds how many there are (the top's
        # datum breaks or warns)
        for edit in ("turnedEllipse", "topGone"):
            with self.subTest(edit=edit):
                doc = FreeCAD.newDocument("PadUpToAnEllipticHoleTwinPieces")
                try:
                    pad, z = discUpToAnEllipticHole(doc)
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    shape = pad.Shape
                    self.assertEqual(len(farCaps(shape, z)), 4)
                    top = shape.getElementMappedName(farCapAt(shape, z, 3, 5.5))
                    bottom = shape.getElementMappedName(farCapAt(shape, z, 3, 0.5))
                    self.assertNotEqual(top, bottom)
                    topPoint = pointOnFarCap(pad, farCapAt(shape, z, 3, 5.5))
                    bottomPoint = pointOnFarCap(pad, farCapAt(shape, z, 3, 0.5))
                    if edit == "turnedEllipse":
                        doc.getObject("Plate").Shape = ellipticHoleShell(z, turn=180)
                        doc.recompute()
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        shape = pad.Shape
                        assertOnCap(self, topPoint, z, *centreOfFarCapAt(shape, z, 3, 5.5))
                        assertOnCap(self, bottomPoint, z, *centreOfFarCapAt(shape, z, 3, 0.5))
                    else:
                        pad.Profile[0].setDatum(
                            "yA", FreeCAD.Units.Quantity(0.8, FreeCAD.Units.Length)
                        )
                        doc.recompute()
                        self.assertTrue(pad.isValid(), pad.getStatusString())
                        shape = pad.Shape
                        self.assertEqual(len(farCaps(shape, z)), 3)
                        assertNotQuietlyElsewhere(self, topPoint, z, [])
                        assertNotQuietlyElsewhere(
                            self, bottomPoint, z, [centreOfFarCapAt(shape, z, 3, 0)]
                        )
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformHoleCapPieceCoversTheFill(self):
        # PR 340 round 2: A (x -3..3, y -0.5..0.5) across the plate's hole and its fill, a datum
        # on its middle piece, on the fill. A made taller than the hole (y -3..2.5) covers the
        # fill: the split leaves the fill whole, and it kept the fill's own name, while the
        # middle piece's name had the ring A's other pieces became as its only match: the datum
        # went to the ring (0, -0.33), valid and with no warning. The fill is now A's
        # projection too, marked by the fill alone (the only far cap on it), as the middle
        # piece was: the datum stays on it. Made taller on one side only (y -0.5..2.5), the
        # middle piece is still the only cap on the fill, its bounds changed: the round 1 build
        # broke the datum, now it stays
        for case, (yA, hA, centre) in {
            "covers": (-3, 5.5, (0, 0)),
            "half": (-0.5, 3, (0, 0.75)),
        }.items():
            with self.subTest(case=case):
                doc = FreeCAD.newDocument("PadUpToAFreeformHoleCapPieceCoversTheFill")
                try:
                    pad, z = capsUpToAFreeformPlate(doc, "Pad", hole=True, capA=(-3, -0.5, 3, 0.5))
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    point = pointOnFarCap(pad, farCapAt(pad.Shape, z, 0, 0))
                    sketch = pad.Profile[0]
                    sketch.setDatum("hA", FreeCAD.Units.Quantity(hA, FreeCAD.Units.Length))
                    sketch.setDatum("yA", FreeCAD.Units.Quantity(yA, FreeCAD.Units.Length))
                    doc.recompute()
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    assertOnCap(self, point, z, *centre)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAnEllipticHoleTwinsStayPut(self):
        # PR 340 round 3: the twins (the disc's top and bottom pieces on the plate) were ordered
        # by their centres along x first, ties only within 1e-5 mm. One above the other, any
        # small edit that moved one ahead in x swapped their names: the ellipse turned 0.01
        # degrees, or the disc moved from (3, 3) to (3.1, 3.1), and each datum went to the other
        # piece, valid and with no warning, for the Pad and the Pocket. Ordered along the axis
        # in which they spread most, they keep their names until the pair turns by about 45
        # degrees. Turned 60 degrees, their names swap (they did on the round 2 build too,
        # quietly), and the solver breaks both references: a counter sibling of the name lies
        # nearer the old place than the piece the name holds
        edits = {
            # edit: (the disc's centre, the ellipse's turn, the places in the top and bottom
            # pieces after it, whether the datums stay)
            "tilt": ((3, 3), 0.01, ((3, 5.5), (3, 0.5)), True),
            "move": ((3.1, 3.1), 0, ((3.1, 5.5), (3.1, 0.5)), True),
            "turn60": (
                (3, 3),
                60,
                ((3 - 1.1 * math.sqrt(3), 4.1), (3 + 1.1 * math.sqrt(3), 1.9)),
                False,
            ),
        }
        for kind in ("Pad", "Pocket"):
            for edit, (centre, turn, (topAfter, bottomAfter), stays) in edits.items():
                with self.subTest(kind=kind, edit=edit):
                    doc = FreeCAD.newDocument("PadUpToAnEllipticHoleTwinsStayPut")
                    try:
                        feature, z = discUpToAnEllipticHole(doc, kind)
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        self.assertEqual(len(farCaps(shape, z)), 4)
                        topPoint = pointOnFarCap(feature, farCapAt(shape, z, 3, 5.5))
                        bottomPoint = pointOnFarCap(feature, farCapAt(shape, z, 3, 0.5))
                        sketch = feature.Profile[0]
                        for tag, value in zip(("xA", "yA"), centre):
                            sketch.setDatum(
                                tag, FreeCAD.Units.Quantity(value, FreeCAD.Units.Length)
                            )
                        if turn:
                            doc.getObject("Plate").Shape = ellipticHoleShell(z, turn=turn)
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        self.assertEqual(len(farCaps(shape, z)), 4)
                        topCentre = centreOfFarCapAt(shape, z, *topAfter)
                        bottomCentre = centreOfFarCapAt(shape, z, *bottomAfter)
                        if stays:
                            assertOnCap(self, topPoint, z, *topCentre)
                            assertOnCap(self, bottomPoint, z, *bottomCentre)
                        else:
                            assertNotQuietlyElsewhere(self, topPoint, z, [topCentre])
                            assertNotQuietlyElsewhere(self, bottomPoint, z, [bottomCentre])
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformShellFarEdgePiecesStay(self):
        # ops#386: up to a shell of two B-spline faces meeting at x = 1, under A's middle, A's
        # far top and bottom edges are two pieces each, on the left and the right face. Told
        # apart by a counter in the splitter's order alone, the left pieces' datums followed the
        # right pieces quietly when A moved onto the right face, and all four went to the other
        # piece when the shell was rebuilt with its faces in the other order. Marked by their
        # faces, the pieces keep their datums when A moves along the seam or grows; when A moves
        # onto the right face, the datums of the left pieces, which went, say so; those of the
        # right pieces take the edge left in one piece (PR 366 round 1; refused in round 9, PLAN
        # decision 152; again since ops#522, decision 168: the up-to face under the piece's saved
        # point is the one it lay on); the swapped shell moves none quietly. For the Pad and the
        # Pocket
        places = {"TL": (0.5, 2), "TR": (1.5, 2), "BL": (0.5, 0), "BR": (1.5, 0)}
        edits = {
            # edit: the datums' places after it, None for a piece that went
            "shift": {"TL": (0.75, 2), "TR": (1.75, 2), "BL": (0.75, 0), "BR": (1.75, 0)},
            "grow": {"TL": (0.5, 4), "TR": (2.5, 4), "BL": (0.5, 0), "BR": (2.5, 0)},
            "offTheRightFace": {"TL": None, "TR": (2.5, 2), "BL": None, "BR": (2.5, 0)},
            "facesSwapped": places,
        }
        for kind in ("Pad", "Pocket"):
            for edit, after in edits.items():
                with self.subTest(kind=kind, edit=edit):
                    doc = FreeCAD.newDocument("PadUpToAFreeformShellFarEdgePieces")
                    try:
                        feature, z = capsUpToAFreeformPlate(doc, kind, seam=1)
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        points = {
                            piece: pointOnFarEdge(feature, farEdgeAt(shape, z, x, y))
                            for piece, (x, y) in places.items()
                        }
                        sketch = feature.Profile[0]
                        if edit == "shift":
                            sketch.setDatum("xA", FreeCAD.Units.Quantity(0.5, FreeCAD.Units.Length))
                        elif edit == "grow":
                            growCapA(sketch)
                        elif edit == "offTheRightFace":
                            sketch.setDatum("xA", FreeCAD.Units.Quantity(1.5, FreeCAD.Units.Length))
                        else:
                            replaceUpToShape(feature, freeformPlateShape(z, 1, swapped=True))
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        for piece, place in after.items():
                            if place is None:
                                assertNotQuietlyElsewhere(self, points[piece], z, [])
                            elif edit == "facesSwapped":
                                assertNotQuietlyElsewhere(self, points[piece], z, [place])
                            else:
                                assertOnCap(self, points[piece], z, *place)
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToAHoledShellFarEdgePiecesStay(self):
        # ops#386: up to the B-spline plate with the hole x -1..1, y -2..2 and the hole's fill,
        # A (x -3..3, y 1..3) has its far bottom edge in three pieces: left and right on the
        # plate (marked by it and the hole's edge through their ends, since they share it), the
        # middle on the fill (marked by the fill alone). Told apart by a counter
        # in the splitter's order (right, left, middle), the left one's datum went to the
        # middle piece when the left piece went, and the right one's to the left piece when the
        # right piece went, quietly; with the shell's faces swapped all three moved. Now a
        # datum on a piece that went says so, and the others are on their pieces or say they
        # lost them: the pieces are counted too (PR 366 round 2), so one going renames them all.
        # A piece going with the shell's faces swapped in the same recompute gave the
        # middle's marks (the fill's index) to a plate piece: the middle's datum followed it
        # quietly (round 1's marks alone). For the Pad and the Pocket
        places = {"L": (-2, 1), "M": (0, 1), "R": (2, 1)}
        edits = {
            # edit: (A's x and width after it, or None; the shell's faces swapped; the datums'
            # places after it, None for a piece that went)
            "leftGone": ((-0.5, 3.5), False, {"L": None, "M": (0.25, 1), "R": (2, 1)}),
            "rightGone": ((-3, 3.5), False, {"L": (-2, 1), "M": (-0.25, 1), "R": None}),
            "facesSwapped": (None, True, places),
            "leftGoneFacesSwapped": ((-0.5, 3.5), True, {"L": None, "M": (0.25, 1), "R": (2, 1)}),
            "rightGoneFacesSwapped": ((-3, 3.5), True, {"L": (-2, 1), "M": (-0.25, 1), "R": None}),
        }
        # Round 3: the middle piece, alone on the fill (the one piece with its marks, the saved
        # centre on it), follows it quietly when a piece beside it went, the shell unchanged
        quiet = {"leftGone": ("M",), "rightGone": ("M",)}
        for kind in ("Pad", "Pocket"):
            for edit, (dimensions, swapped, after) in edits.items():
                with self.subTest(kind=kind, edit=edit):
                    doc = FreeCAD.newDocument("PadUpToAHoledShellFarEdgePieces")
                    try:
                        feature, z = capsUpToAFreeformPlate(
                            doc, kind, hole=True, capA=(-3, 1, 3, 3), block=(-8, -8, 18, 9)
                        )
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        points = {
                            piece: pointOnFarEdge(feature, farEdgeAt(shape, z, x, y))
                            for piece, (x, y) in places.items()
                        }
                        if dimensions:
                            sketch = feature.Profile[0]
                            xA, wA = dimensions
                            sketch.setDatum("wA", FreeCAD.Units.Quantity(wA, FreeCAD.Units.Length))
                            sketch.setDatum("xA", FreeCAD.Units.Quantity(xA, FreeCAD.Units.Length))
                        if swapped:
                            replaceUpToShape(feature, freeformHoleShellShape(z, swapped=True))
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        for piece, place in after.items():
                            if piece in quiet.get(edit, ()):
                                assertOnCap(self, points[piece], z, *place)
                            else:
                                assertNotQuietlyElsewhere(
                                    self, points[piece], z, [place] if place else []
                                )
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToThreePlatesFarEdgePieceGone(self):
        # PR 366 round 2: up to a shell of three B-spline plates meeting at x = 1 and x = 3, A
        # (x 0..5) has its far top edge in three pieces, P1 to P3 left to right, each alone on its
        # plate, so marked by it alone: by its index in a shell without names. A shortened to
        # x 0..2.5 so that P3 went, with the shell's last two plates swapped (or its plates
        # turned by one) in the same recompute: the right plate's index went to the middle one,
        # and P3's datum followed the middle piece quietly to (1.75, 2). Counted by their place
        # and how many there are, the pieces are renamed when one goes: P3's datum says it lost
        # its piece, and P1's and P2's are on theirs or say they lost them. A shortened from the
        # left so that P1 went, the shell unchanged: P3, where it was and renumbered, keeps its
        # datum (a counted piece in its old place is no pattern's copy). For the Pad and the
        # Pocket
        places = {"P1": (0.5, 2), "P2": (2, 2), "P3": (4, 2)}
        edits = {
            # edit: (A's x and width after it; the plates' order; each datum's place after it,
            # or a list of the places it may be at unless it says it lost its piece)
            "rightGoneSwapped": (
                (0, 2.5),
                (0, 2, 1),
                {"P1": [(0.5, 2)], "P2": [(1.75, 2)], "P3": []},
            ),
            "rightGoneTurned": (
                (0, 2.5),
                (2, 0, 1),
                {"P1": [(0.5, 2)], "P2": [(1.75, 2)], "P3": []},
            ),
            "leftGone": ((1.5, 3.5), None, {"P1": [], "P2": [(2.25, 2)], "P3": (4, 2)}),
        }
        for kind in ("Pad", "Pocket"):
            for edit, ((xA, wA), order, after) in edits.items():
                with self.subTest(kind=kind, edit=edit):
                    doc = FreeCAD.newDocument("PadUpToThreePlatesFarEdgePieceGone")
                    try:
                        feature, z = capsUpToAFreeformPlate(
                            doc, kind, seam=1, capA=(0, 0, 5, 2), block=(-8, -8, 18, 9), withB=False
                        )
                        replaceUpToShape(feature, freeformStripsShape(z, (1, 3)))
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        points = {
                            piece: pointOnFarEdge(feature, farEdgeAt(shape, z, x, y))
                            for piece, (x, y) in places.items()
                        }
                        sketch = feature.Profile[0]
                        sketch.setDatum("wA", FreeCAD.Units.Quantity(wA, FreeCAD.Units.Length))
                        sketch.setDatum("xA", FreeCAD.Units.Quantity(xA, FreeCAD.Units.Length))
                        if order:
                            replaceUpToShape(feature, freeformStripsShape(z, (1, 3), order))
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        for piece, place in after.items():
                            if isinstance(place, list):
                                assertNotQuietlyElsewhere(self, points[piece], z, place)
                            else:
                                assertOnCap(self, points[piece], z, *place)
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToAReorderedShellFarEdgePiecesNotQuietlyElsewhere(self):
        # PR 366 round 2: A's far top and bottom edges across the seam of a two-face shell
        # without names, each piece marked by its face's index alone. The shell rebuilt with its
        # faces swapped while A moved along the seam (x 0.5..2.5), or with the seam moved to
        # x = 0.3: every piece's marks went to the other piece, which moved too, with nothing
        # left at the old place, and each datum followed the other piece quietly. A third face
        # put first in the shell, under A's middle (x 0.7..1.3): the left face's index went to
        # it, and TL's and BL's datums followed the new middle piece quietly. Counted by their
        # place along the edge too, the pieces' names are no piece's then, or the same place's:
        # each datum is on its own piece or says it lost it. For the Pad and the Pocket
        places = {"TL": (0.5, 2), "TR": (1.5, 2), "BL": (0.5, 0), "BR": (1.5, 0)}
        edits = {
            # edit: (A's x after it, or None; the shell after it (its cuts and their order); the
            # datums' right places after it)
            "swappedAndShifted": (
                0.5,
                ((1,), (1, 0)),
                {"TL": (0.75, 2), "TR": (1.75, 2), "BL": (0.75, 0), "BR": (1.75, 0)},
            ),
            "swappedSeamMoved": (
                None,
                ((0.3,), (1, 0)),
                {"TL": (0.15, 2), "TR": (1.15, 2), "BL": (0.15, 0), "BR": (1.15, 0)},
            ),
            "middleFaceFirst": (
                None,
                ((0.7, 1.3), (1, 0, 2)),
                {"TL": (0.35, 2), "TR": (1.65, 2), "BL": (0.35, 0), "BR": (1.65, 0)},
            ),
        }
        for kind in ("Pad", "Pocket"):
            for edit, (xA, (cuts, order), after) in edits.items():
                with self.subTest(kind=kind, edit=edit):
                    doc = FreeCAD.newDocument("PadUpToAReorderedShellFarEdgePieces")
                    try:
                        feature, z = capsUpToAFreeformPlate(doc, kind, seam=1)
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        points = {
                            piece: pointOnFarEdge(feature, farEdgeAt(shape, z, x, y))
                            for piece, (x, y) in places.items()
                        }
                        if xA is not None:
                            feature.Profile[0].setDatum(
                                "xA", FreeCAD.Units.Quantity(xA, FreeCAD.Units.Length)
                            )
                        replaceUpToShape(feature, freeformStripsShape(z, cuts, order))
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        for piece, place in after.items():
                            assertNotQuietlyElsewhere(self, points[piece], z, [place])
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToAHoledShellLonePiecesMovedAcrossTheHoleBreak(self):
        # ops#524 (PLAN decisions 199 and 202): shell_twins' MoveAcrossHalf. Up to the plate with the
        # hole x -1..1, y -2..2 and its fill, A (x -3..0, y -0.5..0.5) has a far cap piece on the
        # plate (L, x -3..-1) and one on the fill (M, x -1..0), each alone on its face. A moves to x
        # 0.5..3.5, by its geometry or by its sketch's attachment offset. L's piece is gone: the
        # plate's piece right of the hole takes its name, and moved by the offset it overlaps L's
        # old place in the Pad's own frame (the attack set's ALonePiece, silent before), but the
        # path from L's saved foot crosses the hole: its datum says so. M's piece carries on in the
        # fill at x 0.5..1, but a piece slid within its face can't be told from one reborn there
        # (review prA1c-r1's UArmSwapRedraw), so its datum says it lost its piece too. The datums
        # on the Pad itself, and on a later SubtractiveBox, the Tip, which passes the pieces on
        # with their names and has no up-to faces of its own (N2). B (x 8..14, y -5..-3) holds the
        # box. For the Pad and the Pocket
        for kind in ("Pad", "Pocket"):
            for edit in ("geometry", "offset"):
                for onTip in (False, True):
                    with self.subTest(kind=kind, edit=edit, onTip=onTip):
                        doc = FreeCAD.newDocument("PadUpToAHoledShellLonePiecesMovedAcrossTheHole")
                        try:
                            feature, z = capsUpToAFreeformPlate(
                                doc,
                                kind,
                                hole=True,
                                capA=(-3, -0.5, 0, 0.5),
                                block=(-8, -8, 18, 9),
                                withB=False,
                            )
                            sketch = feature.Profile[0]
                            dimensionedRectangle(sketch, "B", 8, -5, 14, -3)
                            doc.recompute()
                            self.assertTrue(feature.isValid(), feature.getStatusString())
                            target = feature
                            body = feature.getParentGeoFeatureGroup()
                            if onTip:
                                target = body.newObject("PartDesign::SubtractiveBox", "Tip")
                                target.Length = target.Width = target.Height = 1
                                target.MapMode = "Deactivated"
                                target.AttachmentOffset = FreeCAD.Placement()
                                target.Placement = FreeCAD.Placement(
                                    FreeCAD.Vector(12, -4.5, 2), FreeCAD.Rotation()
                                )
                                doc.recompute()
                                self.assertTrue(target.isValid(), target.getStatusString())
                            points = {}
                            for piece, (x, y) in {"L": (-2, 0), "M": (-0.5, 0)}.items():
                                point = body.newObject("PartDesign::Point", "On" + piece)
                                point.AttachmentSupport = [
                                    (target, farCapAt(target.Shape, z, x, y))
                                ]
                                point.MapMode = "CenterOfMass"
                                points[piece] = point
                            body.Tip = target
                            doc.recompute()
                            if edit == "geometry":
                                sketch.setDatum(
                                    "xA", FreeCAD.Units.Quantity(0.5, FreeCAD.Units.Length)
                                )
                            else:
                                sketch.AttachmentOffset = FreeCAD.Placement(
                                    FreeCAD.Vector(3.5, 0, 0) + sketch.AttachmentOffset.Base,
                                    FreeCAD.Rotation(),
                                )
                            doc.recompute()
                            self.assertTrue(feature.isValid(), feature.getStatusString())
                            self.assertTrue(target.isValid(), target.getStatusString())
                            for piece in ("L", "M"):
                                point = points[piece]
                                self.assertFalse(
                                    point.isValid() and point.getStatusString() == "Valid",
                                    "%s quiet at %s" % (piece, point.Placement.Base),
                                )
                        finally:
                            FreeCAD.closeDocument(doc.Name)

    def testPadUpToThreePlatesPiecesSlidOntoTheNextPlate(self):
        # PR 366 round 3: up to a shell of three B-spline plates without names meeting at x = 1
        # and x = 3, A (x 0..2) has its far cap and far edges in two pieces each, on plates 1
        # and 2, marked by their plate's index. A moved to x 2.5..4.5, over plates 2 and 3, with
        # the shell rebuilt in the order 2, 3, 1: plate 2 took plate 1's index and plate 3 plate
        # 2's, while the count and the places along the edges stayed. The old names lay exactly
        # on the new pieces: the left datums followed plate 2's pieces quietly, the right ones
        # plate 3's. Now a marked piece that moved off its old place, with nothing there,
        # breaks: the left datums say they lost their pieces, the right ones are on plate 2's
        # or say they lost them. For the Pad and the Pocket
        places = {
            "CL": (farCapAt, pointOnFarCap, 0.5, 1),
            "CR": (farCapAt, pointOnFarCap, 1.5, 1),
            "TL": (farEdgeAt, pointOnFarEdge, 0.5, 2),
            "TR": (farEdgeAt, pointOnFarEdge, 1.5, 2),
            "BL": (farEdgeAt, pointOnFarEdge, 0.5, 0),
            "BR": (farEdgeAt, pointOnFarEdge, 1.5, 0),
        }
        after = {
            "CL": [],
            "CR": [(2.75, 1)],
            "TL": [],
            "TR": [(2.75, 2)],
            "BL": [],
            "BR": [(2.75, 0)],
        }
        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToThreePlatesPiecesSlid")
                try:
                    feature, z = capsUpToAFreeformPlate(
                        doc, kind, seam=1, capA=(0, 0, 2, 2), block=(-8, -8, 18, 9), withB=False
                    )
                    replaceUpToShape(feature, freeformStripsShape(z, (1, 3)))
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    shape = feature.Shape
                    points = {
                        piece: attach(feature, find(shape, z, x, y))
                        for piece, (find, attach, x, y) in places.items()
                    }
                    feature.Profile[0].setDatum(
                        "xA", FreeCAD.Units.Quantity(2.5, FreeCAD.Units.Length)
                    )
                    replaceUpToShape(feature, freeformStripsShape(z, (1, 3), (1, 2, 0)))
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    for piece, allowed in after.items():
                        assertNotQuietlyElsewhere(self, points[piece], z, allowed)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToThreePlatesTallCapPiecesSlidOntoTheNextPlate(self):
        # PR 366 round 4: as testPadUpToThreePlatesPiecesSlidOntoTheNextPlate, with A 8 high
        # (x 0..2, y 0..8): its far cap's pieces are 1 x 8, on plates 1 and 2 of the strips meeting
        # at x = 1 and 3. A moved by 2 or 2.5 onto plates 2 and 3, the strips rebuilt in the order
        # 2, 1, 3 or 2, 3, 1: the left piece's name lay on plate 2's piece. B-spline caps had no
        # box, and the overlap guessed from their sizes (centres about 2 apart, half their sides
        # together 2.4 to 2.8) kept the left datum quietly on plate 2's piece. Every fingerprint
        # has a box now, and the two boxes share no width: the left datums say they lost their
        # pieces, the right ones are on plate 2's or say they lost them. For the Pad and the
        # Pocket
        def draw(sketch):
            dimensionedRectangle(sketch, "A", 0, 0, 2, 8)
            dimensionedRectangle(sketch, "B", 12, 0, 14, 3)

        places = {
            "CL": ("F", 0.5, 4),
            "CR": ("F", 1.5, 4),
            "TL": ("E", 0.5, 8),
            "TR": ("E", 1.5, 8),
        }
        for kind in ("Pad", "Pocket"):
            for x in (2, 2.5):
                for order in ((1, 0, 2), (1, 2, 0)):
                    with self.subTest(kind=kind, x=x, order=order):
                        middle = (x + 3) / 2
                        after = {"CL": [], "TL": [], "CR": [(middle, 4)], "TR": [(middle, 8)]}
                        slideOntoReorderedStrips(
                            self, kind, (1, 3), draw, places, {"xA": x}, order, after
                        )

    def testPadUpToThreePlatesArcsSlidOntoTheNextPlate(self):
        # PR 366 round 4: the disc A (radius 1, centre (1, 1)) up to the strips meeting at x = 1
        # and 3: its far circle in two arcs, on plates 1 and 2. A moved to x 3 (arcs on plates 2
        # and 3), the strips rebuilt in the order 2, 1, 3 or 2, 3, 1: the left arc's name lay on
        # plate 2's arc. The overlap along the edge compared the chord to the other arc (2) with
        # half the arcs' lengths together (3.1): the left datum stayed quietly on plate 2's arc.
        # Seen in the arcs' boxes, the two share no length along the edge: it says it lost its
        # arc. The right piece of the cap is on plate 2's piece or says it lost it. For the Pad
        # and the Pocket
        def draw(sketch):
            dimensionedCircle(sketch, "A", 1, 1, 1)
            dimensionedCircle(sketch, "B", 14, 3, 1)

        places = {"L": ("E", 0, 1), "CL": ("F", 0.5, 1), "CR": ("F", 1.5, 1)}
        after = {"L": [], "CL": [], "CR": [(2.5, 1)]}
        for kind in ("Pad", "Pocket"):
            for order in ((1, 0, 2), (1, 2, 0)):
                with self.subTest(kind=kind, order=order):
                    slideOntoReorderedStrips(
                        self, kind, (1, 3), draw, places, {"xA": 3}, order, after
                    )

    def testPadUpToThreePlatesCapPiecesSwapOnAPartialSlide(self):
        # PR 366 round 4: the disc A (radius 1.2, centre (1, 1)) up to the strips meeting at x = 1
        # and 3: its cap in two pieces, on plates 1 and 2. A moved by 1 (x 0.8..3.2), the strips
        # rebuilt in the order 2, 1, 3: each piece's name lay on the other plate's piece, and
        # both old places were bare. The pieces' sizes said they still overlapped them: the left
        # datum went quietly to plate 2's piece, the right one to plate 1's sliver. The boxes
        # only touch at x = 1: each datum is on its plate's piece now or says it lost it. For
        # the Pad and the Pocket
        def draw(sketch):
            dimensionedCircle(sketch, "A", 1, 1, 1.2)
            dimensionedCircle(sketch, "B", 14, 3, 1)

        places = {"L": ("E", -0.2, 1), "CL": ("F", 0.4, 1), "CR": ("F", 1.6, 1)}
        after = {"L": [], "CL": [(0.9, 1)], "CR": [(2, 1)]}
        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                slideOntoReorderedStrips(
                    self, kind, (1, 3), draw, places, {"xA": 2}, (1, 0, 2), after
                )

    def testPadUpToThreePlatesTurnedCapPiecesSlidOntoTheNextPlate(self):
        # PR 366 round 5: round 4's slides onto the next plate (A 2 x 2 or 2 x 8, the disc of
        # radius 1.2 moved by 1) with the whole model turned about Z, the strips and the sketch
        # alike. A turned piece's box in the world's axes is wider than the piece: a 1 x 2 piece
        # at 45 degrees has sides of 2.12 against a slide of 1.41 on each axis. The old and new
        # boxes kept sharing a length on both axes, and the left datum stayed quietly on plate 2's
        # piece (on the partial slide, each went to the other plate's). Seen along the pieces'
        # own outlines, the left piece left its old place: its datum says it lost it, and the
        # right one's is on plate 2's piece or says it lost it. For the Pad and the Pocket
        def rectangle(height):
            def draw(sketch):
                dimensionedRectangle(sketch, "A", 0, 0, 2, height)
                dimensionedRectangle(sketch, "B", 12, 0, 14, 3)

            return draw

        def disc(sketch):
            dimensionedCircle(sketch, "A", 1, 1, 1.2)
            dimensionedCircle(sketch, "B", 14, 3, 1)

        cases = {
            # case: (draw, turn, A's x after it, the strips' order, the datums' places before,
            # their places after them)
            "square30": (
                rectangle(2),
                30,
                2,
                (1, 2, 0),
                {"CL": ("F", 0.5, 1), "CR": ("F", 1.5, 1)},
                {"CL": [], "CR": [(2.5, 1)]},
            ),
            "square45": (
                rectangle(2),
                45,
                2.5,
                (1, 0, 2),
                {"CL": ("F", 0.5, 1), "CR": ("F", 1.5, 1)},
                {"CL": [], "CR": [(2.75, 1)]},
            ),
            "tall15": (
                rectangle(8),
                15,
                2,
                (1, 0, 2),
                {"CL": ("F", 0.5, 4), "CR": ("F", 1.5, 4)},
                {"CL": [], "CR": [(2.5, 4)]},
            ),
            "tall45": (
                rectangle(8),
                45,
                2,
                (1, 2, 0),
                {"CL": ("F", 0.5, 4), "CR": ("F", 1.5, 4)},
                {"CL": [], "CR": [(2.5, 4)]},
            ),
            "partial30": (
                disc,
                30,
                2,
                (1, 0, 2),
                {"CL": ("F", 0.4, 1), "CR": ("F", 1.6, 1)},
                {"CL": [(0.9, 1)], "CR": [(2, 1)]},
            ),
        }
        for kind in ("Pad", "Pocket"):
            for case, (draw, turn, x, order, places, after) in cases.items():
                with self.subTest(kind=kind, case=case):
                    slideOntoReorderedStrips(
                        self, kind, (1, 3), draw, places, {"xA": x}, order, after, turn
                    )

    def testPadUpToThreePlatesArcsSlidDiagonally(self):
        # PR 366 round 5: round 4's disc A (radius 1, centre (1, 1)) up to the strips meeting at
        # x = 1 and 3, its far circle in a half circle on plate 1 and two quarter arcs on plate 2
        # (the circle's vertex at angle 0 splits it). A moved to x 3 and y 1.5 or 2, the strips
        # rebuilt in the order 2, 1, 3 or 2, 3, 1: the left arc's name lay on plate 2's half
        # circle. The way along the edge, to the nearest other arc, was diagonal, and the arcs'
        # box corners seen along it shared 0.22 where the arcs themselves don't meet: the left
        # datum stayed quietly on plate 2's half circle. So did it with A moved to x 3 in the
        # model turned by 45 degrees about Z. Seen along their outlines, the arcs share no length:
        # the left datum says it lost its arc, and the right piece of the cap is on plate 2's piece
        # or says it lost it. For the Pad and the Pocket
        def draw(sketch):
            dimensionedCircle(sketch, "A", 1, 1, 1)
            dimensionedCircle(sketch, "B", 14, 3, 1)

        places = {"L": ("E", 0, 1), "CL": ("F", 0.5, 1), "CR": ("F", 1.5, 1)}
        cases = {
            # case: (A's datums after it, the strips' order, the turn)
            "up0.5": ({"xA": 3, "yA": 1.5}, (1, 0, 2), 0),
            "up1": ({"xA": 3, "yA": 2}, (1, 2, 0), 0),
            "turned45": ({"xA": 3}, (1, 0, 2), 45),
        }
        for kind in ("Pad", "Pocket"):
            for case, (datums, order, turn) in cases.items():
                with self.subTest(kind=kind, case=case):
                    y = datums.get("yA", 1)
                    after = {"L": [], "CL": [], "CR": [(2.5, y)]}
                    slideOntoReorderedStrips(
                        self, kind, (1, 3), draw, places, datums, order, after, turn
                    )

    def testPadUpToThreePlatesArcTwinsSlidOntoTheNextPlate(self):
        # PR 366 round 5b: round 4's disc A (radius 1, centre (1, 1)) up to the strips meeting at
        # x = 1 and 3, the model turned by 20 degrees about Z, each strip made from its turned
        # corners: the left half circle comes out in two pieces on plate 1 (lengths 1.98 and
        # 1.16), twins told apart only by their order. A moved to x 3 (its arcs on
        # plates 2 and 3), the strips rebuilt in the order 2, 1, 3 or 2, 3, 1: the left arc's name
        # lay on plate 2's upper-left arc. Twins went only by their places among them, which a
        # slide of them all keeps, and the left datum stayed quietly on plate 2's arc. The twins
        # left together, none of them where the left arc was: the left datum says it lost its
        # arc, and the right piece of the cap is on plate 2's piece or says it lost it. For the
        # Pad and the Pocket
        def draw(sketch):
            dimensionedCircle(sketch, "A", 1, 1, 1)
            dimensionedCircle(sketch, "B", 14, 3, 1)

        places = {"L": ("E", 0, 1), "CL": ("F", 0.5, 1), "CR": ("F", 1.5, 1)}
        after = {"L": [], "CL": [], "CR": [(2.5, 1)]}
        for kind in ("Pad", "Pocket"):
            for order in ((1, 0, 2), (1, 2, 0)):
                with self.subTest(kind=kind, order=order):
                    slideOntoReorderedStrips(
                        self, kind, (1, 3), draw, places, {"xA": 3}, order, after, 20, True
                    )

    def testPadUpToThreePlatesSlantedEdgesSlidOntoTheNextPlate(self):
        # PR 366 round 6: the parallelogram A (-1, -1) (1, -1) (4, 2) (2, 2) up to the strips
        # meeting at x = 1 and 3: its left edge (y = x) in two pieces, on plates 1 and 2, its
        # right edge (y = x - 2) on plates 2 and 3. A moved by 2 along x, the strips rebuilt in
        # the order 2, 1, 3 or 2, 3, 1: plate 1 has no piece of the left edge any more, and the
        # left edge's piece on plate 2, (1, -1) to (3, 1), took plate 1's piece's name. Seen
        # along the edge, the way across the seams, the old and new pieces shared 1.41, and with
        # the corner on the seam the edge's pieces kept their shape, as if moved with the plates:
        # the datum on plate 1's piece stayed quietly on plate 2's. Seen along the Pad's
        # direction, the old piece lies beyond the seam where the cap beside plate 2's piece
        # ends: it says it lost its piece now, and the other datums are on their plate's piece or
        # say they lost theirs. A moved by 0.2, each piece stays on its plate, and every datum
        # keeps its piece. For the Pad and the Pocket
        def draw(sketch):
            polygonInSketch(sketch, ((-1, -1), (1, -1), (4, 2), (2, 2)))
            dimensionedRectangle(sketch, "B", 12, 0, 14, 3)

        def strips(z):
            return freeformStripsShape(z, (1, 3)).Faces

        places = {
            "EL0": ("E", 0, 0),
            "EL1": ("E", 1.5, 1.5),
            "ER1": ("E", 2, 0),
            "ER2": ("E", 3.5, 1.5),
        }
        moved = {"EL0": [], "EL1": [(2, 0)], "ER1": [], "ER2": [(4.5, 0.5)]}
        kept = {"EL0": (0.2, 0), "EL1": (1.7, 1.5), "ER1": (2.2, 0), "ER2": (3.7, 1.5)}
        cases = {
            # case: (the move, the strips' order, the datums' places after it)
            "order213": ((2, 0), (1, 0, 2), moved),
            "order231": ((2, 0), (1, 2, 0), moved),
            "kept": ((0.2, 0), (0, 1, 2), kept),
        }
        for kind in ("Pad", "Pocket"):
            for case, (move, order, after) in cases.items():
                with self.subTest(kind=kind, case=case):
                    slideOntoReorderedPlates(self, kind, strips, draw, places, move, order, after)

    def testPadUpToATiltedPlateCapPiecesSlidOntoALowerPlate(self):
        # PR 366 round 6: up to a shell of plate 1 tilted (slope 1, -1 or 2 along x, x -3..1), a
        # steep ramp (x 1..1.2) up or down by 1.5 or 2, and plates 2 and 3 flat (x 1.2..3, 3..20),
        # A (x 0..2) has its far cap and top edge in pieces on plates 1, the ramp and 2. A moved
        # by 2 along x, onto plates 2 and 3, the shell rebuilt in the order 2, ramp, 1, 3 or 2, 1,
        # ramp, 3: plate 1 has no piece of A any more, and plate 2's cap piece took plate 1's
        # name. Seen along the tilted plate's normal, the old piece and plate 2's new one
        # overlapped (about 0.7) although they lie side by side, and the datum on plate 1's
        # piece stayed quietly on plate 2's. Seen along the Pad's direction, they share nothing:
        # it says it lost its piece, and the other datums are on plate 2's pieces or say they lost
        # theirs. A moved by 0.5 along y, along the seams, with the shell rebuilt in the order 2,
        # ramp, 1, 3: plate 2's piece took plate 1's name again, and the datum on plate 1's piece
        # followed it quietly (seen along the tilted plate's normal, the old piece overlapped it
        # too); each datum is on its plate's piece now or says it lost it. The same move with
        # the shell as it was: every datum keeps its piece. For the Pad and the Pocket
        def draw(sketch):
            dimensionedRectangle(sketch, "A", 0, 0, 2, 2)
            dimensionedRectangle(sketch, "B", 12, 0, 14, 3)

        places = {
            "CL": ("F", 0.5, 1),
            "CR": ("F", 1.5, 1),
            "TL": ("E", 0.5, 2),
            "TR": ("E", 1.5, 2),
        }
        moved = {"CL": [], "CR": [(2.5, 1)], "TL": [], "TR": [(2.5, 2)]}
        kept = {"CL": (0.5, 1.5), "CR": (1.5, 1.5), "TL": (0.5, 2.5), "TR": (1.5, 2.5)}
        slid = {piece: [place] for piece, place in kept.items()}
        for kind in ("Pad", "Pocket"):
            for slope, step in ((1, -2), (-1, 2), (2, -1.5)):
                cases = {
                    # case: (the move, the shell's order, the datums' places after it)
                    "order2r13": ((2, 0), (2, 1, 0, 3), moved),
                    "order21r3": ((2, 0), (2, 0, 1, 3), moved),
                    "slidAlong": ((0, 0.5), (2, 1, 0, 3), slid),
                    "kept": ((0, 0.5), (0, 1, 2, 3), kept),
                }
                for case, (move, order, after) in cases.items():
                    with self.subTest(kind=kind, slope=slope, step=step, case=case):
                        slideOntoReorderedPlates(
                            self, kind, foldedPlates(slope, step), draw, places, move, order, after
                        )

    def testPadUpToANotchedPlateLPieceNotMadeWholeElsewhere(self):
        # PR 366 round 6: up to a shell of an L-shaped plate (x < 1 or y < 1), the square plate in
        # its notch (x 1..4, y 1..10) and a plate beyond (x 4..20), the square A (x 0.5..2.5,
        # y 0.5..2.5) has an L-shaped cap piece on the L plate and a square one on the square
        # plate. A moved by 0.5 along x and y, wholly onto the square plate, the shell in any
        # order: the L plate has no piece of A any more, and the whole cap took a name. The L's
        # centre (1.18, 1.18) lies outside the L, and the whole cap holding it made the L piece
        # look whole again: its datum went quietly to the whole cap. It says it lost its piece
        # now, and the other datums are on their pieces or say they lost them. A moved by 0.2,
        # the L piece is a thinner L, and every datum keeps its piece. For the Pad and the Pocket
        def draw(sketch):
            dimensionedRectangle(sketch, "A", 0.5, 0.5, 2.5, 2.5)
            dimensionedRectangle(sketch, "B", 12, 0, 14, 3)

        places = {
            "CA": ("F", 0.75, 0.75),
            "CB": ("F", 2, 2),
            "TA": ("E", 0.75, 2.5),
            "TB": ("E", 1.75, 2.5),
            "RA": ("E", 2.5, 0.75),
            "RB": ("E", 2.5, 1.75),
        }
        moved = {"CA": [], "CB": [(2, 2)], "TA": [], "TB": [(2, 3)], "RA": [], "RB": [(3, 2)]}
        kept = {
            "CA": (0.85, 0.85),
            "CB": (2.2, 2.2),
            "TA": (0.85, 2.7),
            "TB": (1.85, 2.7),
            "RA": (2.7, 0.85),
            "RB": (2.7, 1.85),
        }
        cases = {
            # case: (the move, the shell's order, the datums' places after it)
            "order123": ((0.5, 0.5), (0, 1, 2), moved),
            "order213": ((0.5, 0.5), (1, 0, 2), moved),
            "order231": ((0.5, 0.5), (1, 2, 0), moved),
            "kept": ((0.2, 0.2), (0, 1, 2), kept),
        }
        for kind in ("Pad", "Pocket"):
            for case, (move, order, after) in cases.items():
                with self.subTest(kind=kind, case=case):
                    slideOntoReorderedPlates(
                        self, kind, notchedPlates, draw, places, move, order, after
                    )

    def testPadUpToANotchedPlateThinLPieceNotMadeWholeElsewhere(self):
        # PR 366 round 7 (ops#386): as the test above, A drawn from (x0, x0) to (x0 + 2, x0 + 2)
        # with x0 = 0.9 or 0.92: the L piece's arms are 0.1 or 0.08 wide. The point inside the L
        # was taken from the centres of a 9 x 9 grid over the piece's parameters, none of them in
        # an arm narrower than a 18th of the span; no point was saved, the L's centre stood in for
        # it, and with A moved wholly onto the square plate the whole cap there held it: the L
        # piece's datum went quietly to the whole cap. Its datum says it lost its piece now, for
        # every move onto the square plate, in the open document and in one saved and opened
        # again; the square piece's datum is on the whole cap or says it lost its piece. The
        # first case is the round 6 verdict's (0.1, moved by 0.5). For the Pad and the Pocket
        cases = [
            # (x0, the move, saved and opened again)
            (0.9, 0.5, False),
            (0.9, 0.1, False),
            (0.9, 0.12, False),
            (0.9, 0.2, False),
            (0.9, 1, False),
            (0.92, 0.1, False),
            (0.92, 0.12, False),
            (0.92, 0.2, False),
            (0.92, 0.5, False),
            (0.92, 1, False),
            (0.9, 0.15, True),
            (0.95, 0.1, True),
        ]
        for kind in ("Pad", "Pocket"):
            for x0, move, reopen in cases:
                arm = 1 - x0
                x1 = x0 + 2

                def draw(sketch, x0=x0, x1=x1):
                    dimensionedRectangle(sketch, "A", x0, x0, x1, x1)
                    dimensionedRectangle(sketch, "B", 12, 0, 14, 3)

                places = {
                    "CA": ("F", x0 + arm / 2, 2),
                    "CA2": ("F", 2, x0 + arm / 2),
                    "CB": ("F", 2, 2),
                }
                after = {"CA": [], "CA2": [], "CB": [(2, 2)]}
                with self.subTest(kind=kind, x0=x0, move=move, reopen=reopen):
                    slideOntoReorderedPlates(
                        self,
                        kind,
                        notchedPlates,
                        draw,
                        places,
                        (move, move),
                        (0, 1, 2),
                        after,
                        reopen,
                    )

    def testPadUpToARidgeStripNotMadeWholeOnTheNextPlate(self):
        # PR 366 round 8 (ops#386): a Pad from below up to a ridge, plates z = 10 + 2x (x < 0) and
        # z = 10 - 2x (x > 0) at 53 degrees, B-spline faces. A (x -0.5..3, y 0..8) has a strip
        # CL on plate 1 and a piece CR on plate 2. A moved by 0.6, wholly onto plate 2: the strip
        # is gone, and the whole cap on plate 2 took a name. The cap made whole held CL's saved
        # centre (-0.25, 4, 9.5) by its nearest point (0.15, 4, 9.7), inside the cap, so CL's
        # datum went quietly to the whole cap (the round 7 verdict). Seen along the sweep, the
        # centre lies beside the cap (x -0.25, the cap from x 0.1): CL says it lost its piece now,
        # in either shell order, in the open document and in one saved and opened again without a
        # recompute. CR is on the whole cap or says it lost its piece. Moved by 0.3 or 1, as before:
        # CL keeps its strip or breaks. The Pad only: a Pocket down to it meets the valley's
        # faces from above, another model
        places = {"CL": ("F", -0.25, 4), "CR": ("F", 1.5, 4)}

        def draw(sketch):
            dimensionedRectangle(sketch, "A", -0.5, 0, 3, 8)

        cases = [
            # (the move, the shell's order, saved and opened again, the datums' places after it)
            (0.6, (0, 1), False, {"CL": [], "CR": [(2.1, 4)]}),
            (0.6, (1, 0), False, {"CL": [], "CR": [(2.1, 4)]}),
            (0.6, (0, 1), "untouched", {"CL": [], "CR": [(2.1, 4)]}),
            (0.6, (1, 0), "untouched", {"CL": [], "CR": [(2.1, 4)]}),
            (1, (0, 1), False, {"CL": [], "CR": [(2.5, 4)]}),
            (0.3, (0, 1), False, {"CL": [(-0.1, 4)], "CR": [(1.8, 4)]}),
        ]
        for move, order, reopen, after in cases:
            with self.subTest(move=move, order=order, reopen=reopen):
                slideOntoReorderedPlates(
                    self,
                    "Pad",
                    ridgePlates(),
                    draw,
                    places,
                    (move, 0),
                    order,
                    after,
                    reopen,
                    capMax=200,
                )

    def testPadUpToPlatesMovedUnderTheProfilePieceNotMadeWhole(self):
        # PR 366 round 9 (ops#386): the ridge strip above and the notch's L piece (A x 0.5..2.5,
        # moved by (0.5, 0.5) wholly onto the square plate), with the profile moved some other way
        # than its attachment offset: by its unattached sketch's Placement, or by the datum plane
        # its sketch is attached to (the Pad's Placement follows both, so in the Pad's own frame
        # the profile stays and the plates move under it); or with the plates moved the other way,
        # by their feature's Placement or rebuilt there. In each the gone piece's datum (CL, CA)
        # went quietly to the cap made whole on the next plate in round 8, its saved point under
        # that cap in the Pad's frame. It says it lost its piece now. ops#522 (PLAN decision 168):
        # the other piece's datum (CR, CB) is on the whole cap, quietly, since the plate under its
        # saved point (carried by the Pad's placement, in the plates' own frame) is its own; with
        # the plates rebuilt elsewhere every plate's box changed, and it says it lost its piece
        # (decision 150). Either shell order
        ridge = {
            "faces": ridgePlates(),
            "draw": lambda sketch: dimensionedRectangle(sketch, "A", -0.5, 0, 3, 8),
            "places": {"CL": ("F", -0.25, 4), "CR": ("F", 1.5, 4)},
            "move": (0.6, 0),
            "orders": ((0, 1), (1, 0)),
            "after": {"CL": [], "CR": [(2.1, 4)]},
            "capMax": 200,
        }
        notch = {
            "faces": notchedPlates,
            "draw": lambda sketch: dimensionedRectangle(sketch, "A", 0.5, 0.5, 2.5, 2.5),
            "places": {"CA": ("F", 0.75, 2), "CB": ("F", 2, 2)},
            "move": (0.5, 0.5),
            "orders": ((0, 1, 2), (1, 0, 2)),
            "after": {"CA": [], "CB": [(2, 2)]},
            "capMax": 50,
        }
        for name, case in (("ridge", ridge), ("notch", notch)):
            for mover in ("placement", "datum", "platesPlacement", "platesGeometry"):
                # The piece that stays: on the whole cap (a tuple), or broken (no place)
                after = {
                    piece: (places[0] if mover != "platesGeometry" else [])
                    if places
                    else []
                    for piece, places in case["after"].items()
                }
                for order in case["orders"]:
                    with self.subTest(model=name, mover=mover, order=order):
                        slideOntoReorderedPlates(
                            self,
                            "Pad",
                            case["faces"],
                            case["draw"],
                            case["places"],
                            case["move"],
                            order,
                            after,
                            capMax=case["capMax"],
                            mover=mover,
                        )

    def testPadUpToASeamRibStripNotMadeWholeByItsCentre(self):
        # PR 366 round 9 (ops#386, the round 8 cloud review's S1): a Pad from below up to two
        # plates meeting at a seam x = 0 (B-spline faces; plane faces name the strip's cap by the
        # bare projection, which the whole cap then takes: ops#513), A a long thin rib x -0.1..0.3,
        # y -10..10, its cap a strip CS on the first plate (x -0.1..0) and a piece CP on the
        # second. A moved by 0.12 or 0.2 is wholly on the second plate: the strip is gone. The
        # whole cap's centre of mass lies within the strip's reach of its saved centre (a quarter
        # of the side of a 0.1 x 20 strip: 0.35), and round 8 took that as holding it, though the
        # line through the strip's centre along the sweep misses the cap: CS went quietly to the
        # whole cap. It says it lost its piece now; CP is on the whole cap or says it lost its
        # piece. Moved by 0.3, beyond the reach, as before. The same rib, y -9..9, up to the ridge
        # (B-spline plates at 53 degrees), moved by 0.12
        def rib(y0, y1):
            return lambda sketch: dimensionedRectangle(sketch, "A", -0.1, y0, 0.3, y1)

        places = {"CS": ("F", -0.05, 0), "CP": ("F", 0.15, 0)}
        cases = [
            # (the plates, the rib, the move, the shell's order, capMax)
            (seamPlates(), rib(-10, 10), 0.12, (0, 1), 50),
            (seamPlates(), rib(-10, 10), 0.12, (1, 0), 50),
            (seamPlates(), rib(-10, 10), 0.2, (0, 1), 50),
            (seamPlates(), rib(-10, 10), 0.3, (0, 1), 50),
            (ridgePlates(), rib(-9, 9), 0.12, (0, 1), 200),
        ]
        for index, (faces, draw, move, order, capMax) in enumerate(cases):
            with self.subTest(case=index, move=move, order=order):
                slideOntoReorderedPlates(
                    self,
                    "Pad",
                    faces,
                    draw,
                    places,
                    (move, 0),
                    order,
                    {"CS": [], "CP": [(move + 0.1, 0)]},
                    capMax=capMax,
                )

    def testPadUpToANotchedPlateThinLPieceFromTheSavedFile(self):
        # PR 366 round 8 (ops#386): the round 7 reopen cases above touch and recompute the opened
        # document before the move, so its references are solved from fingerprints made again,
        # not from those the file holds. Here the document is opened again and moved with nothing
        # recomputed: the thin L piece's fingerprint in the file has its point inside the L (the
        # twelfth field), and with A moved wholly onto the square plate its datums say they lost
        # their piece, in any shell order; the square piece's datum is on the whole cap or says it
        # lost its piece. A moved by 0.05, every datum keeps its piece or breaks. For the Pad
        # and the Pocket
        cases = [
            # (x0, the move, the shell's order, the datums' places after it)
            (0.9, 0.15, (0, 1, 2), {"CA": [], "CA2": [], "CB": [(2, 2)]}),
            (0.9, 0.15, (1, 2, 0), {"CA": [], "CA2": [], "CB": [(2, 2)]}),
            (0.95, 0.5, (1, 0, 2), {"CA": [], "CA2": [], "CB": [(2, 2)]}),
            (0.9, 0.05, (0, 1, 2), {"CA": [(0.97, 2)], "CA2": [(2, 0.97)], "CB": [(2, 2)]}),
        ]
        for kind in ("Pad", "Pocket"):
            for x0, move, order, after in cases:
                arm = 1 - x0
                x1 = x0 + 2

                def draw(sketch, x0=x0, x1=x1):
                    dimensionedRectangle(sketch, "A", x0, x0, x1, x1)
                    dimensionedRectangle(sketch, "B", 12, 0, 14, 3)

                places = {
                    "CA": ("F", x0 + arm / 2, 2),
                    "CA2": ("F", 2, x0 + arm / 2),
                    "CB": ("F", 2, 2),
                }
                with self.subTest(kind=kind, x0=x0, move=move, order=order):
                    slideOntoReorderedPlates(
                        self,
                        kind,
                        notchedPlates,
                        draw,
                        places,
                        (move, move),
                        order,
                        after,
                        "untouched",
                        savedInside=("CA", "CA2"),
                    )

    def testPadUpToAHoledShellFarEdgePiecesOfAFlippedRectangle(self):
        # PR 366 round 3: A (x -3..3, y 1..3) across the plate's hole and its fill, its far bottom
        # edge in three pieces, ordered along A's edge. A drawn again from its other corner (x 3,
        # width -6), the geometry the same: the edge runs the other way, and the pieces' order
        # along it flipped, so the left and right pieces' datums warned that they were found
        # again in the same place. The order no longer depends on the edge's direction: each
        # datum stays on its piece, quietly. For the Pad and the Pocket
        places = {"L": (-2, 1), "M": (0, 1), "R": (2, 1)}
        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToAHoledShellFlippedRectangle")
                try:
                    feature, z = capsUpToAFreeformPlate(
                        doc, kind, hole=True, capA=(-3, 1, 3, 3), block=(-8, -8, 18, 9)
                    )
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    shape = feature.Shape
                    points = {
                        piece: pointOnFarEdge(feature, farEdgeAt(shape, z, x, y))
                        for piece, (x, y) in places.items()
                    }
                    sketch = feature.Profile[0]
                    sketch.setDatum("xA", FreeCAD.Units.Quantity(3, FreeCAD.Units.Length))
                    sketch.setDatum("wA", FreeCAD.Units.Quantity(-6, FreeCAD.Units.Length))
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    for piece, (x, y) in places.items():
                        assertOnCap(self, points[piece], z, x, y)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAnEllipticHoleFarEdgeTwins(self):
        # ops#386: the disc's far circle across the elliptic hole: its top and bottom arcs lie on
        # the plate, each bounded by the ellipse alone, with no vertex of the circle (it sits on
        # the fill): twins, told apart by their places. The ellipse turned 0.01 degrees, or
        # rebuilt turned 180 (the same faces, its edge starting on the other side): each datum
        # stays on its arc. The disc moved down so that the top arc is gone: its datum says so,
        # and the bottom one's isn't quietly elsewhere
        for kind in ("Pad", "Pocket"):
            for edit in ("tilt", "turn180", "topGone"):
                with self.subTest(kind=kind, edit=edit):
                    doc = FreeCAD.newDocument("PadUpToAnEllipticHoleFarEdgeTwins")
                    try:
                        feature, z = discUpToAnEllipticHole(doc, kind)
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        top = shape.getElementMappedName(farEdgeAt(shape, z, 3, 6))
                        bottom = shape.getElementMappedName(farEdgeAt(shape, z, 3, 0))
                        self.assertNotEqual(top, bottom)
                        for name in (top, bottom):
                            flags = FreeCAD.getDecodedMappedName(name)[-1]["mapperFlags"]
                            self.assertEqual(set(flags), {"PRJ", "MOD", "ORD"}, name)
                        topPoint = pointOnFarEdge(feature, farEdgeAt(shape, z, 3, 6))
                        bottomPoint = pointOnFarEdge(feature, farEdgeAt(shape, z, 3, 0))
                        if edit == "topGone":
                            feature.Profile[0].setDatum(
                                "yA", FreeCAD.Units.Quantity(0.8, FreeCAD.Units.Length)
                            )
                        else:
                            doc.getObject("Plate").Shape = ellipticHoleShell(
                                z, turn=0.01 if edit == "tilt" else 180
                            )
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        if edit == "topGone":
                            assertNotQuietlyElsewhere(self, topPoint, z, [])
                            assertNotQuietlyElsewhere(
                                self, bottomPoint, z, [centreOfFarEdgeAt(shape, z, 3, -2.2)]
                            )
                        else:
                            assertOnCap(self, topPoint, z, *centreOfFarEdgeAt(shape, z, 3, 6))
                            assertOnCap(self, bottomPoint, z, *centreOfFarEdgeAt(shape, z, 3, 0))
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformFarEdgePieceNames(self):
        # ops#386: each piece of a far edge the up-to shape cuts (A's top edge across the
        # shell's seam at x = 1) is a projection of the profile edge marked by what tells it
        # apart, PRJ with MOD, and counted by its place along the edge (ORD, PR 366 round 2),
        # and the pieces' names differ; a far edge in one piece (B's top edge, on the right
        # face) stays the projection alone, PRJ with index 0
        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToAFreeformFarEdgePieceNames")
                try:
                    feature, z = capsUpToAFreeformPlate(doc, kind, seam=1)
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    shape = feature.Shape
                    names = [
                        shape.getElementMappedName(farEdgeAt(shape, z, x, y))
                        for x, y in ((0.5, 2), (1.5, 2), (0.5, 0), (1.5, 0))
                    ]
                    self.assertEqual(len(set(names)), 4, names)
                    for name in names:
                        top = FreeCAD.getDecodedMappedName(name)[-1]
                        self.assertEqual(set(top["mapperFlags"]), {"PRJ", "MOD", "ORD"}, name)
                        self.assertTrue(top["connectedElements"], name)
                    single = shape.getElementMappedName(farEdgeAt(shape, z, 6.5, 3))
                    top = FreeCAD.getDecodedMappedName(single)[-1]
                    self.assertEqual(top["mapperFlags"], ["PRJ"], single)
                    self.assertEqual(top["index"], "0", single)
                    self.assertFalse(top["connectedElements"], single)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAnEllipticHoleTwinsMovedOrGrownStay(self):
        # PR 340 round 4 (N2): round 3's traded-twin check broke a reference whenever a counter
        # sibling of its name lay nearer the saved centre than the piece the name holds. So it
        # did when the disc and the hole moved together by more than half the twins' spacing
        # (3 mm down: the bottom twin's new place is nearer the top one's old place), or when
        # one twin grew a lot while the other stayed (the disc grown upward to radius 8 with
        # its bottom fixed, over a longer hole): "Face5 moved and Face4 sits nearer where it
        # was", where integration and round 2 kept the datums. Nothing was traded: the sibling
        # must now also lie as far from the twins' centroid as the saved centre does, as after
        # a turn about their centre, and the datums stay on their pieces, quietly
        def longHole(z):
            return ellipticHoleShell(z, a=12, bounds=(-12, -10, 22, 20))

        def centreAt(shape, z, x, y):
            # the centre of the face at height z that holds (x, y, z), of any size
            point = FreeCAD.Vector(x, y, z)
            faces = [
                f
                for f in shape.Faces
                if abs(f.BoundBox.ZMin - z) < 1e-6
                and abs(f.BoundBox.ZMax - z) < 1e-6
                and f.isInside(point, 1e-6, True)
            ]
            self.assertEqual(len(faces), 1, (x, y, z))
            return faces[0].CenterOfMass.x, faces[0].CenterOfMass.y

        edits = {
            # edit: (kinds, the up-to shell, the sketch's datums, the places in the top and
            # bottom pieces after it)
            "move": (("Pad", "Pocket"), ellipticHoleShell, {"yA": 0}, ((3, 2.5), (3, -2.5))),
            "grow": (("Pad",), longHole, {"yA": 8, "rA": 8}, ((3, 5.5), (3, 0.5))),
        }
        for edit, (kinds, shell, datums, (topAfter, bottomAfter)) in edits.items():
            for kind in kinds:
                with self.subTest(kind=kind, edit=edit):
                    doc = FreeCAD.newDocument("PadUpToAnEllipticHoleTwinsMovedOrGrownStay")
                    try:
                        feature, z = discUpToAnEllipticHole(doc, kind, shell=shell)
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        topPoint = pointOnFarCap(feature, farCapAt(shape, z, 3, 5.5))
                        bottomPoint = pointOnFarCap(feature, farCapAt(shape, z, 3, 0.5))
                        sketch = feature.Profile[0]
                        for tag, value in datums.items():
                            sketch.setDatum(
                                tag, FreeCAD.Units.Quantity(value, FreeCAD.Units.Length)
                            )
                        if edit == "move":
                            doc.getObject("Plate").Shape = ellipticHoleShell(z, centre=(3, 0))
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        shape = feature.Shape
                        assertOnCap(self, topPoint, z, *centreAt(shape, z, *topAfter))
                        assertOnCap(self, bottomPoint, z, *centreAt(shape, z, *bottomAfter))
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToALobedHoleTiedTwinsBreak(self):
        # PR 340 round 4 (N3): a disc across a hole of three lobes turned 60 degrees, or of
        # four lobes turned 45, trades the twins' names, and the name of the twin at 300 (or
        # 45) degrees lands on a piece exactly as far from its saved centre as the twin's own
        # piece, now at 0 (or 90) degrees. Round 3's check wanted a sibling strictly nearer, so
        # the tie let the datum stand there, valid and with no warning. A tie now counts too,
        # and the reference breaks (or stays on the twin's own piece)
        cases = {
            # case: (lobes, the turn, the twin's place before and after it)
            "three": (3, 60, (3 + 2.1 * 0.5, 3 - 2.1 * math.sqrt(3) / 2), (5.1, 3)),
            "four": (4, 45, (3 + 1.9 / math.sqrt(2), 3 + 1.9 / math.sqrt(2)), (3, 4.9)),
        }
        for kind in ("Pad", "Pocket"):
            for case, (lobes, turn, before, after) in cases.items():
                with self.subTest(kind=kind, case=case):
                    doc = FreeCAD.newDocument("PadUpToALobedHoleTiedTwinsBreak")
                    try:
                        feature, z = discUpToAnEllipticHole(
                            doc, kind, shell=lambda z: lobedHoleShell(z, lobes), radius=2.3
                        )
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        self.assertEqual(len(farCaps(feature.Shape, z)), lobes + 2)
                        point = pointOnFarCap(feature, farCapAt(feature.Shape, z, *before))
                        doc.getObject("Plate").Shape = lobedHoleShell(z, lobes, turn=turn)
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        own = centreOfFarCapAt(feature.Shape, z, *after)
                        assertNotQuietlyElsewhere(self, point, z, [own])
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToAnEllipticHoleUnequalTwinsTurnedBreak(self):
        # PR 340 round 5 (N5): the disc off the hole's centre, along the twins' axis (unequal
        # twins) or across it, the long hole (a 6) turned 50-75 degrees about its own centre:
        # the twins trade names. Round 4's check wanted the counter sibling as far from the
        # twins' centroid as the saved centre (within 20 %), as after a turn about their
        # centroid; turned about the hole's centre, the twins changed shape and the centroid
        # moved, and both datums stood on the other twin's piece, valid and with no warning. The
        # saved fingerprint now holds the twins' centroid, and the offsets from it show the trade:
        # each datum breaks (or stays on its own piece)
        def turned(x, y, turn):
            a = math.radians(turn)
            x, y = x - 3, y - 3
            return 3 + x * math.cos(a) - y * math.sin(a), 3 + x * math.sin(a) + y * math.cos(a)

        cases = {
            # case: (the disc's centre and radius, the hole's turn, the top and bottom twins'
            # places before the turn and after it)
            "unequal60": ((3, 4), 3, 60, ((3, 5.5), (3, 1.5))),
            "unequal75": ((3, 4), 3, 75, ((3, 5.5), (3, 1.5))),
            "unequal50": ((3, 4), 3, 50, ((3, 5.5), (3, 1.5))),
            "across50": ((4.5, 3), 3, 50, ((4.5, 5.5), (4.5, 0.5))),
            "across60": ((5, 3), 3, 60, ((5, 5.5), (5, 0.5))),
            "across75": ((5, 3), 3, 75, ((5, 5.5), (5, 0.5))),
        }
        for kind in ("Pad", "Pocket"):
            for case, (centre, radius, turn, places) in cases.items():
                with self.subTest(kind=kind, case=case):
                    doc = FreeCAD.newDocument("PadUpToAnEllipticHoleUnequalTwinsTurnedBreak")
                    try:
                        feature, z = discUpToAnEllipticHole(
                            doc, kind, shell=lambda z: ellipticHoleShell(z, a=6), radius=radius
                        )
                        sketch = feature.Profile[0]
                        for tag, value in zip(("xA", "yA"), centre):
                            sketch.setDatum(
                                tag, FreeCAD.Units.Quantity(value, FreeCAD.Units.Length)
                            )
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        self.assertEqual(len(farCaps(feature.Shape, z)), 4)
                        points = [
                            pointOnFarCap(feature, farCapAt(feature.Shape, z, *place))
                            for place in places
                        ]
                        doc.getObject("Plate").Shape = ellipticHoleShell(z, turn=turn, a=6)
                        doc.recompute()
                        self.assertTrue(feature.isValid(), feature.getStatusString())
                        for point, place in zip(points, places):
                            if case.startswith("unequal"):
                                after = turned(*place, turn)
                            else:
                                # the place as far along the hole's normal through the disc
                                d = place[1] - 3
                                a = math.radians(turn)
                                after = (centre[0] - d * math.sin(a), 3 + d * math.cos(a))
                            own = centreOfFarCapAt(feature.Shape, z, *after)
                            assertNotQuietlyElsewhere(self, point, z, [own])
                    finally:
                        FreeCAD.closeDocument(doc.Name)

    def testPadUpToALobedHoleOffCentreTurnedBySymmetryBreaks(self):
        # PR 340 round 6 (N9): the disc 0.3 mm off the centre of a hole of four lobes, the hole
        # turned exactly 45 degrees, its symmetry angle: +45 and -45 give the same hole, and the
        # twins trade names. Off the centre, the twin at 225 degrees has its two candidates'
        # offsets from the twins' centroid 4 % apart from its old offset (1.36 and 1.42 mm),
        # beyond the 2 % tie, and the datum stood on the -45 piece, valid and with no warning,
        # while the +45 piece holds all of its material. The offsets lie at the same angle from
        # the old one: an angular tie, and every datum breaks (or stays on its own piece)
        def turned(x, y, turn):
            a = math.radians(turn)
            x, y = x - 3, y - 3
            return 3 + x * math.cos(a) - y * math.sin(a), 3 + x * math.sin(a) + y * math.cos(a)

        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToALobedHoleOffCentreTurnedBySymmetryBreaks")
                try:
                    feature, z = discUpToAnEllipticHole(
                        doc, kind, shell=lambda z: lobedHoleShell(z, 4), radius=2.3
                    )
                    sketch = feature.Profile[0]
                    sketch.setDatum("xA", FreeCAD.Units.Quantity(3.3, FreeCAD.Units.Length))
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    self.assertEqual(len(farCaps(feature.Shape, z)), 6)
                    # the twins, between the lobes at 45, 135, 225 and 315 degrees
                    places = [
                        (3 + 1.7 * math.cos(math.radians(t)), 3 + 1.7 * math.sin(math.radians(t)))
                        for t in (45, 135, 225, 315)
                    ]
                    names = [farCapAt(feature.Shape, z, *place) for place in places]
                    self.assertEqual(len(set(names)), 4)
                    centres = [centreOfFarCapAt(feature.Shape, z, *place) for place in places]
                    points = [pointOnFarCap(feature, name) for name in names]
                    doc.getObject("Plate").Shape = lobedHoleShell(z, 4, turn=45)
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    for point, centre in zip(points, centres):
                        own = centreOfFarCapAt(feature.Shape, z, *turned(*centre, 45))
                        assertNotQuietlyElsewhere(self, point, z, [own])
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToALobedHoleFarOffCentreTurnedBySymmetryBreaks(self):
        # PR 340 round 7 (N12): as above, with a disc of radius 2 0.75 mm off the centre (0.37 of
        # its radius). The twin at 225 degrees now has its two candidates' offsets from the twins'
        # centroid 38 and 47 degrees from its old offset: past round 6's 5-degree band, and the
        # hit is 27 % nearer by distance, so the datum stood quietly on the piece at 180 degrees
        # while the piece at 270 holds all of its material. A 12-degree band ties them. The
        # other twins' material, carried by the turn, lies partly outside the disc: a datum
        # there may stand only on the piece holding its turned centre, if there is one
        def turned(x, y, turn):
            a = math.radians(turn)
            x, y = x - 3, y - 3
            return 3 + x * math.cos(a) - y * math.sin(a), 3 + x * math.sin(a) + y * math.cos(a)

        def capsAt(shape, x, y):
            """The (x, y) centres of the far caps holding (x, y): one, or none"""
            point = FreeCAD.Vector(x, y, z)
            return [
                (cap.CenterOfMass.x, cap.CenterOfMass.y)
                for cap in farCaps(shape, z).values()
                if cap.isInside(point, 1e-6, True)
            ]

        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToALobedHoleFarOffCentreTurnedBySymmetryBreaks")
                try:
                    feature, z = discUpToAnEllipticHole(
                        doc, kind, shell=lambda z: lobedHoleShell(z, 4), radius=2
                    )
                    sketch = feature.Profile[0]
                    sketch.setDatum("xA", FreeCAD.Units.Quantity(3.75, FreeCAD.Units.Length))
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    self.assertEqual(len(farCaps(feature.Shape, z)), 6)
                    # the twins, between the lobes at 45, 135, 225 and 315 degrees; the ones at
                    # 135 and 225 reach from the hole (1.2 from its centre) to about 1.4
                    places = [
                        (3 + 1.3 * math.cos(math.radians(t)), 3 + 1.3 * math.sin(math.radians(t)))
                        for t in (45, 135, 225, 315)
                    ]
                    names = [farCapAt(feature.Shape, z, *place) for place in places]
                    self.assertEqual(len(set(names)), 4)
                    centres = [centreOfFarCapAt(feature.Shape, z, *place) for place in places]
                    points = [pointOnFarCap(feature, name) for name in names]
                    doc.getObject("Plate").Shape = lobedHoleShell(z, 4, turn=45)
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    # the twin at 225 degrees went to the piece at 270
                    self.assertEqual(
                        len(capsAt(feature.Shape, *turned(*centres[2], 45))), 1, centres[2]
                    )
                    for point, centre in zip(points, centres):
                        own = capsAt(feature.Shape, *turned(*centre, 45))
                        assertNotQuietlyElsewhere(self, point, z, own)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformHoleCapPiecesMergeIntoARing(self):
        # PR 340 round 3: A (x -3..3, y -0.5..0.5) across the plate's hole and its fill, datums
        # on its left and right pieces, on the plate. A made taller than the hole (y -3..2.5)
        # makes them one ring around the fill; taller on one side (y -0.5..2.5), one U around
        # the fill's top. The new piece's marks hold each old piece's, but tier 1's overlap is
        # mostly the start cap's, which the piece on the fill shares as much: both references
        # broke (round 2), where integration's names (MOD of the plate) took them to the ring.
        # Now the one candidate whose name holds the old piece's takes it: the datums go to
        # the ring, quietly, also when only one of them is there, and for the Pocket's floors.
        # Round 4 (N1): without B, the ring is the only far cap on the plate, and its marks are
        # the plate alone, which don't hold the old piece's (the plate and the hole's edge):
        # both references broke again. The one candidate marked by the old piece's face alone
        # takes it when the old piece's centre lies over it
        for kind in ("Pad", "Pocket"):
            for case, (yA, hA) in {"ring": (-3, 5.5), "u": (-0.5, 3)}.items():
                for pieces in (("left", "right"), ("left",)):
                    for alone in (False, True) if case == "ring" else (False,):
                        with self.subTest(kind=kind, case=case, pieces=pieces, alone=alone):
                            self.mergeIntoARing(kind, yA, hA, pieces, alone)

    def mergeIntoARing(self, kind, yA, hA, pieces, alone):
        """testPadUpToAFreeformHoleCapPiecesMergeIntoARing's case: B on the plate unless
        `alone`"""
        doc = FreeCAD.newDocument("PadUpToAFreeformHoleCapPiecesMergeIntoARing")
        try:
            feature, z = capsUpToAFreeformPlate(
                doc,
                kind,
                hole=True,
                capA=(-3, -0.5, 3, 0.5),
                block=(-8, -8, 18, 10),
                withB=not alone,
            )
            self.assertTrue(feature.isValid(), feature.getStatusString())
            shape = feature.Shape
            self.assertEqual(len(farCaps(shape, z)), 3 if alone else 4)
            places = {"left": (-2, 0), "right": (2, 0)}
            points = {
                piece: pointOnFarCap(feature, farCapAt(shape, z, *places[piece]))
                for piece in pieces
            }
            sketch = feature.Profile[0]
            sketch.setDatum("hA", FreeCAD.Units.Quantity(hA, FreeCAD.Units.Length))
            sketch.setDatum("yA", FreeCAD.Units.Quantity(yA, FreeCAD.Units.Length))
            doc.recompute()
            self.assertTrue(feature.isValid(), feature.getStatusString())
            shape = feature.Shape
            self.assertEqual(farCapAt(shape, z, -2, 0), farCapAt(shape, z, 2, 0))
            merged = centreOfFarCapAt(shape, z, -2, 0)
            for piece in pieces:
                assertOnCap(self, points[piece], z, *merged)
        finally:
            FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformHoleCapPieceLeftAloneStays(self):
        # PR 340 round 5 (N7): A (x -3..3, y 0.3..2.5) across the top of the plate's hole: its
        # piece on the plate is an n around the hole's top, its centre of mass (0, 1.49) over
        # the hole, and its piece on the fill is a strip. B deleted from the sketch leaves A's
        # n the only far cap on the plate: renamed with the plate alone as its marks, it takes
        # the old reference only when the old centre lies over it, and the check wanted the
        # face's nearest point to that centre inside the face. The n's is on its edge along
        # the hole: "Missing face reference". Its own centre of mass is the old centre, which
        # counts the same now
        for kind in ("Pad", "Pocket"):
            with self.subTest(kind=kind):
                doc = FreeCAD.newDocument("PadUpToAFreeformHoleCapPieceLeftAloneStays")
                try:
                    feature, z = capsUpToAFreeformPlate(
                        doc, kind, hole=True, capA=(-3, 0.3, 3, 2.5), block=(-8, -8, 18, 10)
                    )
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    shape = feature.Shape
                    self.assertEqual(len(farCaps(shape, z)), 3)
                    n = centreOfFarCapAt(shape, z, -2, 1.4)
                    self.assertAlmostEqual(n[0], 0, places=6)
                    point = pointOnFarCap(feature, farCapAt(shape, z, -2, 1.4))
                    sketch = feature.Profile[0]
                    sketch.delGeometries([4, 5, 6, 7])
                    doc.recompute()
                    self.assertTrue(feature.isValid(), feature.getStatusString())
                    self.assertEqual(len(farCaps(feature.Shape, z)), 2)
                    self.assertTrue(point.isValid(), point.getStatusString())
                    assertOnCap(self, point, z, *n)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadUpToAFreeformFaceCapsMigrate(self):
        # ops#360's naming revision: a file saved with a datum on A's cap, reopened by a child
        # FreeCADCmd under FREECAD_TEST_NAMING_REVISION_OFFSET=1, looks older and takes the
        # naming migration: its reference is re-derived from geometry onto A's cap (none moved
        # back, none broken), and stays there when A grows past B
        import json
        import os
        import re
        import subprocess
        import tempfile

        from PartDesignTests.TestNamingDump import _freecadCmd

        feature, z = capsUpToAFreeformPlate(self.Doc, "Pad")
        pointOnFarCap(feature, farCapAt(feature.Shape, z, 1, 1))
        work = tempfile.mkdtemp(prefix="pad-caps-migrate-")
        path = os.path.join(work, "caps.FCStd")
        self.Doc.saveAs(path)
        script = os.path.join(work, "child.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(_MIGRATION_CHILD)
        out = os.path.join(work, "child.json")
        env = dict(os.environ)
        env["FREECAD_TEST_NAMING_REVISION_OFFSET"] = "1"
        env["PAD_CAPS_FILE"] = path
        env["PAD_CAPS_OUT"] = out
        run = subprocess.run(
            [_freecadCmd(), script],
            env=env,
            cwd=work,
            timeout=600,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        log = run.stdout.decode("utf-8", "replace")
        if os.path.isfile(out + ".error"):
            with open(out + ".error", encoding="utf-8") as fh:
                self.fail(fh.read() + "\n" + log)
        with open(out, encoding="utf-8") as fh:
            result = json.load(fh)
        self.assertIn("FREECAD_TEST_NAMING_REVISION_OFFSET=1", log)
        found = re.findall(
            r"(\d+) element references re-derived from their geometry after a naming change: "
            r"(\d+) moved back to their element, (\d+) broken",
            log,
        )
        self.assertTrue(found, log)
        self.assertGreater(sum(int(total) for total, _, _ in found), 0, log)
        self.assertEqual(
            [(int(moved), int(broken)) for _, moved, broken in found], [(0, 0)] * len(found), log
        )
        self.assertTrue(result["valid"], result)
        self.assertLess((FreeCAD.Vector(*result["opened"]) - FreeCAD.Vector(1, 1, z)).Length, 1e-6)
        centre = CAP_A_GROWN / 2
        self.assertLess(
            (FreeCAD.Vector(*result["grown"]) - FreeCAD.Vector(centre, centre, z)).Length,
            1e-6,
            result,
        )

    def testTwoSidedPadWhoseSideMissesAFreeformFace(self):
        # ops#357 (ops#353's rethrow): side 2 of the 5 x 5 square goes up to a B-spline plate at
        # z = -5 that misses part of it (x -1..10). The side failed as "Resulting fused extrusion
        # is null." before ops#353; it fails now with the side's error. The plate x -10..10 is the
        # control: 25 x (5 + 5)
        V = FreeCAD.Vector
        for x0 in (-10, -1):
            with self.subTest(x0=x0):
                corners = [V(x0, -10, -5), V(10, -10, -5), V(10, 10, -5), V(x0, 10, -5)]
                plate = self.Doc.addObject("Part::Feature", "Plate")
                plate.Shape = Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]
                self.Doc.recompute()
                pad = self._twoSidedUpToPad(("Length", 5), ("UpToFace", (plate, "Face1")))
                if x0 == -10:
                    self.assertTrue(pad.isValid(), pad.getStatusString())
                    self.assertAlmostEqual(pad.Shape.Volume, 250, places=6)
                else:
                    self.assertFalse(pad.isValid())
                    self.assertIn("doesn't meet", pad.getStatusString())

    def testPadUpToABaseWithNames(self):
        """ops#347, review of fork PR 321: a Pad up to the base keeps the base's names and has
        the topology of the box fused with the tab, whichever way it is given."""
        for upTo in ("UpToFace", "UpToFirst", "UpToLast", "UpToShape"):
            with self.subTest(upTo=upTo):
                doc = FreeCAD.newDocument("PartDesignTestPadTab")
                try:
                    tabOnNamedBase(self, doc, "Pad", upTo)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def testPadFromAFaceOfTheBaseUpToTheFaceAcrossAGap(self):
        """ops#347, review of fork PR 321: a support face of the base, up to a face and the last
        face."""
        for upTo in ("UpToFace", "UpToLast"):
            with self.subTest(upTo=upTo):
                doc = FreeCAD.newDocument("PartDesignTestPadPost")
                try:
                    postInTheGap(self, doc, upTo)
                finally:
                    FreeCAD.closeDocument(doc.Name)

    def _tubeWithTabAtTheSeam(self, refine):
        """A tube (radii 6 and 10, height 10) and a tab Pad 5 high, x 6..14 and y -2..2, whose
        side x = 6 is tangent to the bore along the bore's seam (upstream issue 32645, ops#389).
        """
        body = self.Doc.addObject("PartDesign::Body", "Body")
        tube = body.newObject("Sketcher::SketchObject", "TubeSketch")
        tube.AttachmentSupport = (self.Doc.getObject("XY_Plane"), [""])
        tube.MapMode = "FlatFace"
        for radius in (10, 6):
            tube.addGeometry(
                Part.Circle(FreeCAD.Vector(), FreeCAD.Vector(0, 0, 1), radius)
            )
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = tube
        pad.Length = 10
        pad.Refine = refine
        self.Doc.recompute()
        tab = body.newObject("Sketcher::SketchObject", "TabSketch")
        tab.AttachmentSupport = (self.Doc.getObject("XY_Plane"), [""])
        tab.MapMode = "FlatFace"
        corners = [FreeCAD.Vector(x, y, 0) for x, y in ((6, -2), (14, -2), (14, 2), (6, 2))]
        for i in range(4):
            tab.addGeometry(Part.LineSegment(corners[i], corners[(i + 1) % 4]))
        tabPad = body.newObject("PartDesign::Pad", "TabPad")
        tabPad.Profile = tab
        tabPad.Length = 5
        tabPad.Refine = refine
        self.Doc.recompute()
        return tabPad

    def testRefineKeepsATabTangentAtTheSeamValid(self):
        """Refine merged the seam halves of the bore into one edge, leaving the bore's wire
        open: an invalid solid of the wrong volume, without an error (ops#389)."""
        # The tube, and the tab outside the outer radius: its area of 32 less the part inside
        # the wall, the integral of sqrt(100 - y^2) - 6 over y in -2..2
        inWall = 2 * (math.sqrt(96) + 50 * math.asin(0.2)) - 24
        expected = math.pi * (10**2 - 6**2) * 10 + 5 * (32 - inWall)
        for refine in (False, True):
            with self.subTest(refine=refine):
                tabPad = self._tubeWithTabAtTheSeam(refine)
                self.assertTrue(tabPad.isValid())
                self.assertTrue(tabPad.Shape.isValid())
                self.assertAlmostEqual(tabPad.Shape.Volume, expected, places=4)
                self.assertNotIn("Warning", tabPad.State)
                FreeCAD.closeDocument(self.Doc.Name)
                self.Doc = FreeCAD.newDocument("PartDesignTestPad")

    def testRefineMergesATabTangentAtTheSeam(self):
        """Refine still merges there (the tab's bottom face with the tube's): the seam is kept
        out of the edge fuse, the refine isn't dropped (ops#389)."""
        unrefined = len(self._tubeWithTabAtTheSeam(False).Shape.Faces)
        FreeCAD.closeDocument(self.Doc.Name)
        self.Doc = FreeCAD.newDocument("PartDesignTestPad")
        refined = len(self._tubeWithTabAtTheSeam(True).Shape.Faces)
        self.assertLess(refined, unrefined)

    @staticmethod
    def _flatFaceNormal(shape, z):
        """The outward normal, as its orientation within the shape gives it, of the shape's one
        planar face at height z: up on the top of a solid oriented outwards. An orientation oracle
        that uses neither OCCT's classifier nor its mass integration, which both go wrong on long
        curved B-spline faces (ops#414, ops#426)."""
        faces = [
            face
            for face in shape.Faces
            if face.Surface.TypeId == "Part::GeomPlane"
            and abs(face.BoundBox.ZMin - z) < 1e-7
            and abs(face.BoundBox.ZMax - z) < 1e-7
        ]
        assert len(faces) == 1, len(faces)
        return faces[0].normalAt(0, 0)

    def _waveSketch(self, body, name, spans, amplitude, period):
        """A sketch on XY of the wave x = amplitude (1 - cos(2 pi y / period)), y = 0..spans, one
        cubic B-spline of `spans` spans, closed at x = -5"""
        points = [
            FreeCAD.Vector(amplitude * (1 - math.cos(2 * math.pi * y / period)), y, 0)
            for y in range(spans + 1)
        ]
        wave = Part.BSplineCurve()
        wave.interpolate(points)
        sketch = body.newObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = (self.Doc.getObject("XY_Plane"), [""])
        sketch.MapMode = "FlatFace"
        sketch.addGeometry(wave, False)
        corners = [(0, spans), (-5, spans), (-5, 0), (0, 0)]
        for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
            sketch.addGeometry(
                Part.LineSegment(FreeCAD.Vector(x0, y0, 0), FreeCAD.Vector(x1, y1, 0)), False
            )
        return sketch

    def _squareSketch(self, body, name, x, y, z=0):
        """A 2 x 2 square sketch on XY at height z, its corner at (x, y)"""
        sketch = body.newObject("Sketcher::SketchObject", name)
        sketch.AttachmentSupport = (self.Doc.getObject("XY_Plane"), [""])
        sketch.MapMode = "FlatFace"
        sketch.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(0, 0, z), FreeCAD.Rotation())
        corners = [(x, y), (x + 2, y), (x + 2, y + 2), (x, y + 2), (x, y)]
        for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
            sketch.addGeometry(
                Part.LineSegment(FreeCAD.Vector(x0, y0, 0), FreeCAD.Vector(x1, y1, 0)), False
            )
        return sketch

    def testRefineKeepsALongWaveOutward(self):
        """A Pad, a Pocket and a Pad, all with Refine, on a steep wave of 1000 spans stay
        outward (ops#426).

        The Pad of the wave (period 10, amplitude 4, closed at x = -5, 10 high), a 2 x 2 Pocket
        through all at y = 500, a 2 x 2 x 5 Pad on top at y = 250. Refine's orientation step
        (BRepLib::OrientClosedSolid) turned the Pocket's solid inside out with status Valid, and
        the Pad on top of it then lost its material."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        sketch = self._waveSketch(body, "Sketch", 1000, 4, 10)
        self.Doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Length = 10
        pad.Refine = True
        self.Doc.recompute()
        pocket = body.newObject("PartDesign::Pocket", "Pocket")
        pocket.Profile = self._squareSketch(body, "Sketch001", -4, 500)
        pocket.Type = "ThroughAll"
        pocket.Reversed = True
        pocket.Refine = True
        self.Doc.recompute()
        top = body.newObject("PartDesign::Pad", "Pad001")
        top.Profile = self._squareSketch(body, "Sketch002", -4, 250, 10)
        top.Length = 5
        top.Refine = True
        self.Doc.recompute()
        V = FreeCAD.Vector
        for feature in (pad, pocket, top):
            self.assertTrue(feature.isValid(), feature.Name)
            self.assertLess((self._flatFaceNormal(feature.Shape, 10) - V(0, 0, 1)).Length, 1e-9)
            self.assertLess((self._flatFaceNormal(feature.Shape, 0) - V(0, 0, -1)).Length, 1e-9)
        # 1 mm cubes in the pocket and in the second Pad: plain boxes, away from the wave, so
        # their common volumes are exact
        inPocket = Part.makeBox(1, 1, 1, V(-3.5, 500.5, 4.5))
        inTop = Part.makeBox(1, 1, 1, V(-3.5, 250.5, 12))
        self.assertAlmostEqual(top.Shape.common(inPocket).Volume, 0, places=6)
        self.assertAlmostEqual(top.Shape.common(inTop).Volume, 1, places=6)

    def testUpToFirstFromTheProfilesCentre(self):
        """Pad UpToFirst finds its face from the profile's true centre (ops#428).

        The profile is a steep wave (period 10, amplitude 4) of 400 spans closed at x = -5: its
        centre is at x = -0.054, and OCCT's default integration put it at x = -0.78. The base is a
        plate at z = 10..12 over x > -0.5 and one at z = 20..22 over all of the profile, joined by a
        wall beyond it. The ray up from the true centre meets the lower plate first, so the Pad
        ends at z = 10 under the whole profile; from the wrong centre it went on to z = 20."""
        body = self.Doc.addObject("PartDesign::Body", "Body")
        spans = 400
        V = FreeCAD.Vector
        lower = Part.makeBox(17.5, spans + 20, 2, V(-0.5, -10, 10))
        upper = Part.makeBox(27, spans + 20, 2, V(-10, -10, 20))
        wall = Part.makeBox(2, spans + 20, 8, V(15, -10, 12))
        plates = self.Doc.addObject("Part::Feature", "Plates")
        plates.Shape = lower.fuse([upper, wall]).removeSplitter()
        body.BaseFeature = plates
        sketch = self._waveSketch(body, "Sketch", spans, 4, 10)
        self.Doc.recompute()
        pad = body.newObject("PartDesign::Pad", "Pad")
        pad.Profile = sketch
        pad.Type = "UpToFirst"
        pad.Refine = False
        self.Doc.recompute()
        self.assertTrue(pad.isValid(), pad.getStatusString())
        # 1 mm cubes beside the lower plate's edge, below and above z = 10: plain boxes, away
        # from the wave, so their common volumes are exact
        below = Part.makeBox(1, 1, 1, V(-3.5, spans / 2, 8.5))
        above = Part.makeBox(1, 1, 1, V(-3.5, spans / 2, 14.5))
        self.assertAlmostEqual(pad.Shape.common(below).Volume, 1, places=6)
        self.assertAlmostEqual(pad.Shape.common(above).Volume, 0, places=6)

    @staticmethod
    def _trough(spans, cx):
        """The trough z = 10 + 0.002 (x - cx)^2 as a B-spline surface parametrised along the
        diagonals (u ~ x + y, v ~ x - y), trimmed to x >= -2, y = -10..spans + 10. Its concavity
        seen from a point below, which decides whether a Pad up to it may remove its limits
        (Part::Tools::isConcave()), is then (x of the point >= cx)."""
        n = 24
        us = [-30 + (spans + 60) * i / (n - 1) for i in range(n)]
        vs = [-spans - 60 + (spans + 90) * j / (n - 1) for j in range(n)]
        grid = [
            [
                FreeCAD.Vector((u + v) / 2, (u - v) / 2, 10 + 0.002 * ((u + v) / 2 - cx) ** 2)
                for v in vs
            ]
            for u in us
        ]
        surface = Part.BSplineSurface()
        surface.interpolate(grid)
        box = Part.makeBox(40, spans + 20, 200, FreeCAD.Vector(-2, -10, -50))
        return Part.Face(surface).common(box).Faces[0]

    def testUpToFaceLimitsFromTheProfilesCentre(self):
        """Pad UpToFace decides whether to remove a curved face's limits from the profile's true
        centre (ops#428, fork PR 371 round 2).

        The profile is the steep wave of testUpToFirstFromTheProfilesCentre() (400 spans, true
        centre x = -0.054, OCCT's default x = -0.78). The face is _trough() with cx = -0.4, between
        the two: seen from the true centre it is concave, so its limits stay, and the profile's part
        at x < -2 doesn't meet it, as for a rectangle with the same centre (x = -5..4.892). From the
        default centre the limits went and the Pad filled up to the extended surface. With
        cx = +0.5 both centres see it convex, and the wave pads up to the extended surface."""
        spans = 400
        V = FreeCAD.Vector

        def padUpTo(cx, rectangle):
            body = self.Doc.addObject("PartDesign::Body", "Body")
            if rectangle:
                sketch = body.newObject("Sketcher::SketchObject", "Rectangle")
                sketch.AttachmentSupport = (self.Doc.getObject("XY_Plane"), [""])
                sketch.MapMode = "FlatFace"
                corners = [(4.892, 0), (4.892, spans), (-5, spans), (-5, 0), (4.892, 0)]
                for (x0, y0), (x1, y1) in zip(corners, corners[1:]):
                    sketch.addGeometry(Part.LineSegment(V(x0, y0, 0), V(x1, y1, 0)), False)
            else:
                sketch = self._waveSketch(body, "Wave", spans, 4, 10)
            upTo = self.Doc.addObject("Part::Feature", "Trough")
            upTo.Shape = self._trough(spans, cx)
            self.Doc.recompute()
            pad = body.newObject("PartDesign::Pad", "Pad")
            pad.Profile = sketch
            pad.Type = "UpToFace"
            pad.UpToFace = (upTo, ["Face1"])
            pad.Refine = False
            self.Doc.recompute()
            return pad

        control = padUpTo(-0.4, rectangle=True)
        self.assertFalse(control.isValid())
        self.assertIn("doesn't meet it", control.getStatusString())
        wave = padUpTo(-0.4, rectangle=False)
        self.assertFalse(wave.isValid())
        self.assertIn("doesn't meet it", wave.getStatusString())
        convex = padUpTo(0.5, rectangle=False)
        self.assertTrue(convex.isValid(), convex.getStatusString())
        # A 1 mm cube at x = -3.5, outside the trimmed face, just under the extended surface: a
        # plain box away from the wave, so its common volume is exact
        z = 10 + 0.002 * (-3.5 - 0.5) ** 2
        below = Part.makeBox(1, 1, 1, V(-4, spans / 2, z - 1.5))
        self.assertAlmostEqual(convex.Shape.common(below).Volume, 1, places=6)

    def tearDown(self):
        # closing doc
        FreeCAD.closeDocument("PartDesignTestPad")
        # print ("omit closing document for debugging")


class TestUpToPlanePlacement(unittest.TestCase):
    """A pad up to a plane that isn't a face (FreeCAD-CH ops#198): a 2 x 2 square at z = -3 in
    the body, padded up to the body's XY origin plane (12 mm^3), or up to a coordinate
    system's XY plane, the coordinate system at z = 7 in the body (40 mm^3; it was taken at
    z = 0), as the face or as the shape."""

    bodyPlacement = FreeCAD.Placement()

    def setUp(self):
        self.Doc = FreeCAD.newDocument("PartDesignTestUpToPlane")
        self.Body = self.Doc.addObject("PartDesign::Body", "Body")
        self.Body.Placement = self.bodyPlacement
        sketch = self.Body.newObject("Sketcher::SketchObject", "Square")
        sketch.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, -3), FreeCAD.Rotation())
        corners = [FreeCAD.Vector(x, y, 0) for x, y in ((0, 0), (2, 0), (2, 2), (0, 2))]
        sketch.addGeometry(
            [Part.LineSegment(p, q) for p, q in zip(corners, corners[1:] + corners[:1])], False
        )
        self.Pad = self.Body.newObject("PartDesign::Pad", "Pad")
        self.Pad.Profile = sketch

    def tearDown(self):
        FreeCAD.closeDocument(self.Doc.Name)

    def planeOf(self, coordinateSystem, role="XY_Plane"):
        [plane] = [f for f in coordinateSystem.OriginFeatures if f.Role == role]
        return plane

    def coordinateSystemPlane(self):
        lcs = self.Doc.addObject("Part::LocalCoordinateSystem", "LCS")
        self.Body.addObject(lcs)
        lcs.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 7), FreeCAD.Rotation())
        return self.planeOf(lcs)

    def assertVolume(self, volume):
        self.Doc.recompute()
        self.assertTrue(self.Pad.isValid(), self.Pad.getStatusString())
        self.assertAlmostEqual(self.Pad.Shape.Volume, volume, places=6)

    def testUpToOriginPlane(self):
        self.Pad.Type = "UpToFace"
        self.Pad.UpToFace = (self.planeOf(self.Body.Origin), [""])
        self.assertVolume(12)

    def testUpToCoordinateSystemPlane(self):
        self.Pad.Type = "UpToFace"
        self.Pad.UpToFace = (self.coordinateSystemPlane(), [""])
        self.assertVolume(40)

    def testUpToCoordinateSystemPlaneAsShape(self):
        self.Pad.Type = "UpToShape"
        self.Pad.UpToShape = [(self.coordinateSystemPlane(), [""])]
        self.assertVolume(40)

    def testUpToCoordinateSystemPlaneAsShapeWithOffset(self):
        """A plane alone as the shape is taken as a face, so the offset applies: 1 further, 44
        (PR 175 review, Low 3)."""
        self.Pad.Type = "UpToShape"
        self.Pad.UpToShape = [(self.coordinateSystemPlane(), [""])]
        self.Pad.Offset = 1
        self.assertVolume(44)

    def testUpToOriginXZPlaneAsShape(self):
        """The square turned to face -Y at y = 3, up to the body's XZ origin plane as the shape:
        3 long, 12. Alone it was taken without its placement, as the XY plane (PR 175 review,
        Low 3)."""
        self.Pad.Profile[0].Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 3, 0), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
        )
        self.Pad.Type = "UpToShape"
        self.Pad.UpToShape = [(self.planeOf(self.Body.Origin, "XZ_Plane"), [""])]
        self.assertVolume(12)

    def testUpToTurnedCoordinateSystemPlane(self):
        """The coordinate system at z = 7 turned 90 degrees about X; its XZ plane lies flat at
        z = 7 only as the coordinate system's placement times the plane's (the other order puts
        it at z = 0): 40, as the face and as the shape (PR 175 review, Low 4)."""
        lcs = self.Doc.addObject("Part::LocalCoordinateSystem", "Turned")
        self.Body.addObject(lcs)
        lcs.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0, 0, 7), FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
        )
        plane = self.planeOf(lcs, "XZ_Plane")
        self.Pad.Type = "UpToFace"
        self.Pad.UpToFace = (plane, [""])
        self.assertVolume(40)
        self.Pad.Type = "UpToShape"
        self.Pad.UpToShape = [(plane, [""])]
        self.assertVolume(40)

    def testUpToADatumPlaneAsShape(self):
        """A PartDesign datum plane at z = 7 alone as the shape: 40. It was taken without its
        placement, at z = 0 (PR 175 review, Medium 2)."""
        plane = self.Body.newObject("PartDesign::Plane", "DatumPlane")
        plane.MapMode = "Deactivated"
        plane.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 7), FreeCAD.Rotation())
        self.Pad.Type = "UpToShape"
        self.Pad.UpToShape = [(plane, [""])]
        self.assertVolume(40)

    def testUpToAPlaneWithACoordinateSystemAttached(self):
        """A plane of no coordinate system (a Part datum plane at z = 7) with a coordinate system
        attached to it, 10 above: the pad stops at the plane (40), not moved by the attached
        coordinate system (PR 175 review, Medium 1)."""
        plane = self.Doc.addObject("Part::DatumPlane", "DatumPlane")
        self.Body.addObject(plane)
        plane.MapMode = "Deactivated"
        plane.Placement = FreeCAD.Placement(FreeCAD.Vector(0, 0, 7), FreeCAD.Rotation())
        lcs = self.Doc.addObject("Part::LocalCoordinateSystem", "Attached")
        self.Body.addObject(lcs)
        lcs.AttachmentSupport = [(plane, "")]
        lcs.MapMode = "ObjectXY"
        lcs.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(0, 0, 10), FreeCAD.Rotation())
        self.Doc.recompute()
        self.assertIn(lcs, plane.InList)
        self.Pad.Type = "UpToFace"
        self.Pad.UpToFace = (plane, [""])
        self.assertVolume(40)


class TestUpToPlanePlacementInAPlacedBody(TestUpToPlanePlacement):
    """The same in a body moved and turned: the same volumes."""

    bodyPlacement = FreeCAD.Placement(
        FreeCAD.Vector(5, -4, 9), FreeCAD.Rotation(FreeCAD.Vector(1, 1, 0), 30)
    )
