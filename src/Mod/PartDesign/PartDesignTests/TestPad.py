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


def padUpToARevolvedFace(doc, y0, y1):
    """ops#353 review M1: the face of the surface of revolution of a B-spline arc (r 20..21..20
    over z 0..10) about the z axis, 60 degrees about z, centred on the +x axis (y about -10..10 at r = 20,
    not elementary, so the Pad goes by the split), and a Pad from the rectangle y `y0`..`y1`,
    z 4..8 in the plane x = 40, along (-1, -0.1, -0.1), up to that face. The direction is oblique
    so that Part::Tools::isConcave() doesn't keep the face's limits. Recomputed, not checked."""
    import Sketcher

    V = FreeCAD.Vector
    arc = Part.BSplineCurve()
    arc.interpolate([V(20, 0, 0), V(21, 0, 5), V(20, 0, 10)])
    face = arc.toShape().revolve(V(0, 0, 0), V(0, 0, 1), 60)
    face.rotate(V(0, 0, 0), V(0, 0, 1), -30)
    wall = doc.addObject("Part::Feature", "Wall")
    wall.Shape = face
    body = doc.addObject("PartDesign::Body", "Body")
    sketch = body.newObject("Sketcher::SketchObject", "Rectangle")
    # Sketch x is world -z, y is y, the normal +x
    sketch.Placement = FreeCAD.Placement(V(40, 0, 0), FreeCAD.Rotation(V(0, 1, 0), 90))
    corners = [V(-8, y0, 0), V(-4, y0, 0), V(-4, y1, 0), V(-8, y1, 0)]
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


def revolvedFaceReach(y0, y1, z0, z1):
    """The volume of padUpToARevolvedFace()'s prism over the rectangle y y0..y1, z z0..z1 of the
    plane x = 40, when all of it meets the face: from each point (40, y, z) along the unit d of
    (-1, -0.1, -0.1) to the surface, at the first t where the point's distance from the z axis is
    the arc's x where its z is the point's (the arc's z rises along it). Both by bisection; the
    volume is the integral of t |d.x| over the rectangle, by Simpson's rule with 16 intervals in y
    and 8 in z (within 6e-8 relative of 64 and 32; PR 326 review)."""
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
        return bisect(lambda t: outside(y, z, t), 10, 30)

    def simpson(f, a, b, n):
        h = (b - a) / n
        weights = (1 if i in (0, n) else 4 if i % 2 else 2 for i in range(n + 1))
        return h / 3 * sum(w * f(a + i * h) for i, w in enumerate(weights))

    return abs(d.x) * simpson(lambda z: simpson(lambda y: reach(y, z), y0, y1, 16), z0, z1, 8)


def holdBases(*objects):
    """The shapes the objects hold now, with their toleranceState(). A shape shares its TShapes
    with the object's stored one: a maker that raised them in place changes the held state."""
    return [(o.Name, o.Shape, toleranceState(o.Shape)) for o in objects]


def assertBasesKept(test, held):
    """The held shapes are as they were: the same tolerances and curves on surfaces. A tolerance
    may differ by an ULP (1e-23 at 1e-7): a boolean's refinement moves the tolerance of an edge
    or vertex the result shares with the base that much (a Pad up to the last face), and a raise
    that matters is orders of magnitude more (1e-7 to 5e-6, or 1.8e-15 in the research)."""
    for name, shape, before in held:
        after = toleranceState(shape)
        for kept, was in zip(after[:3], before[:3]):
            test.assertEqual(len(kept), len(was), name)
            for x, y in zip(kept, was):
                test.assertAlmostEqual(x, y, delta=1e-18, msg=name)
        test.assertEqual(after[3], before[3], name)


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
