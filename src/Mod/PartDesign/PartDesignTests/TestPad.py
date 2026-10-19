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


def padUpToABallUnderAPlate(doc, half):
    """ops#357: a Body whose BaseFeature is the plate x, y -8..8, z 0..2 with the ball of radius
    5 about (0, 0, -0.1) through it (a dome above it to z 4.9) and the B-spline knob x 5..6, y
    -0.5..0.5, z 2..3 on it beside the dome (a freeform face in the Pad's path, so the Pad goes by
    the split), and a Pad from the square x, y -`half`..`half` at z = -15, along +z, up to the
    base (UpToShape, nothing selected). The ball's band between its equator and the plate (z
    -0.1..0, 0.02 of the sphere face's 1.59 range) faces the plate. Recomputed, not checked."""
    V = FreeCAD.Vector
    plate = Part.makeBox(16, 16, 2, V(-8, -8, 0))
    ball = Part.makeSphere(5, V(0, 0, -0.1))
    knob = Part.makeBox(1, 1, 1, V(5, -0.5, 2)).toNurbs()
    base = doc.addObject("Part::Feature", "Base")
    base.Shape = plate.fuse([ball, knob]).removeSplitter()
    body = doc.addObject("PartDesign::Body", "Body")
    baseFeature = body.newObject("PartDesign::FeatureBase", "BaseFeature")
    baseFeature.BaseFeature = base
    placement = FreeCAD.Placement(V(0, 0, -15), FreeCAD.Rotation())
    sketch = squareSketch(body, "Square", placement, [(-half, -half, half, half)])
    pad = body.newObject("PartDesign::Pad", "Pad")
    pad.Profile = sketch
    pad.Type = "UpToShape"
    doc.recompute()
    return pad


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


def freeformPlate(doc, z, seam=None):
    """A Part feature holding the rectangle x -10..20, y -10..10 of the plane z = `z` as a B-spline
    face (not elementary, so a prism up to it is built by the split), or with `seam`, a shell of
    two such faces meeting at x = `seam`"""
    V = FreeCAD.Vector
    faces = []
    for x0, x1 in ((-10, seam), (seam, 20)) if seam is not None else ((-10, 20),):
        corners = [V(x0, -10, z), V(x1, -10, z), V(x1, 10, z), V(x0, 10, z)]
        faces.append(Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0])
    plate = doc.addObject("Part::Feature", "Plate")
    plate.Shape = faces[0] if len(faces) == 1 else Part.Shell(faces)
    return plate


def freeformHoleShell(doc, z):
    """ops#360 round 1: a shell of two B-spline faces at height z: the rectangle x -10..20,
    y -10..10 with the hole x -1..1, y -2..2, and the hole's fill"""
    V = FreeCAD.Vector
    outer = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    hole = [V(-1, -2, z), V(-1, 2, z), V(1, 2, z), V(1, -2, z)]
    wires = [Part.makePolygon(corners + corners[:1]) for corners in (outer, hole)]
    plate = Part.Face(Part.Plane(V(0, 0, z), V(0, 0, 1)), wires).toNurbs().Faces[0]
    fill = [V(-1, -2, z), V(1, -2, z), V(1, 2, z), V(-1, 2, z)]
    fillFace = Part.Face(Part.makePolygon(fill + fill[:1])).toNurbs().Faces[0]
    shell = doc.addObject("Part::Feature", "Plate")
    shell.Shape = Part.Shell([plate, fillFace])
    return shell


def capsUpToAFreeformPlate(doc, kind, seam=None, hole=False, capA=CAP_A):
    """ops#360: a Pad from A and B in the XY plane up to a B-spline plate at z = 10 (UpToFace, or
    UpToShape up to the two-face shell meeting at x = `seam`, or with `hole` the plate with a hole
    and its fill); or a Pocket from them on top of the block x -2..12, y -5..8, z 0..10, down to
    the plate at z = 4. Returns the feature and the height of its far caps (the Pocket's floors)"""
    body = doc.addObject("PartDesign::Body", "Body")
    xy = [f for f in body.Origin.OriginFeatures if f.Role == "XY_Plane"][0]
    capZ = 10 if kind == "Pad" else 4
    plate = freeformHoleShell(doc, capZ) if hole else freeformPlate(doc, capZ, seam)
    if kind == "Pocket":
        blockSketch = body.newObject("Sketcher::SketchObject", "BlockSketch")
        blockSketch.AttachmentSupport = [(xy, "")]
        blockSketch.MapMode = "FlatFace"
        dimensionedRectangle(blockSketch, "Block", -2, -5, 12, 8)
        block = body.newObject("PartDesign::Pad", "Block")
        block.Profile = blockSketch
        block.Length = 10
    sketch = body.newObject("Sketcher::SketchObject", "Profile")
    sketch.AttachmentSupport = [(xy, "")]
    sketch.MapMode = "FlatFace"
    if kind == "Pocket":
        sketch.AttachmentOffset = FreeCAD.Placement(FreeCAD.Vector(0, 0, 10), FreeCAD.Rotation())
    dimensionedRectangle(sketch, "A", *capA)
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
        (TestProfileLinkDialog checks the dialog)."""
        for solver in (True, False):
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
                # Where the loft's seam crosses the far edges, the vertices are generated
                name = prism.getElementMappedName("Vertex%d" % i)
                self.assertTrue(";PRJ;" in name or ";GEN;" in name, name)

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
        # cap is two pieces: each a projection of A, marked by the shell's face it lies on and
        # the edges that bound it, with MOD among its flags (PR 340 round 1); B's is a
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
        # plate, the middle on the fill. Each is marked by its face and the edges that bound it.
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
