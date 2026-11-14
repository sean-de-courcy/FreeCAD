# SPDX-License-Identifier: LGPL-2.1-or-later

# ***************************************************************************
# *                                                                         *
# *   This file is part of FreeCAD.                                         *
# *                                                                         *
# *   FreeCAD is free software: you can redistribute it and/or modify it    *
# *   under the terms of the GNU Lesser General Public License as           *
# *   published by the Free Software Foundation, either version 2.1 of the  *
# *   License, or (at your option) any later version.                       *
# *                                                                         *
# *   FreeCAD is distributed in the hope that it will be useful, but        *
# *   WITHOUT ANY WARRANTY; without even the implied warranty of            *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU      *
# *   Lesser General Public License for more details.                       *
# *                                                                         *
# *   You should have received a copy of the GNU Lesser General Public      *
# *   License along with FreeCAD. If not, see                               *
# *   <https://www.gnu.org/licenses/>.                                      *
# *                                                                         *
# ***************************************************************************

"""The corpus's PartDesign models beyond B1's core (FreeCAD-CH ops#323 PR B2,
notes/beta-compatibility.md 3.6, "B2"). Same conventions as `models.py`: each builder takes
`make(stem)` and returns the stated volumes."""

import math

import FreeCAD as App
import Part

from PartDesignTests.Compat.models import (
    TOP,
    V,
    attachedSketch,
    edgeWhere,
    faceWhere,
    lineThrough,
    plane,
    planeFacing,
    vertexAt,
)
from PartDesignTests.Scenarios import models as m


def newBody(doc, name):
    return doc.addObject("PartDesign::Body", name)


def block(body, x0, y0, x1, y1, height, name="Pad"):
    """A rectangle on the Body's XY plane, padded `height`."""
    sketch = attachedSketch(
        body, name + "Sketch", plane(body, "XY_Plane"), m.rectangle(x0, y0, x1, y1)
    )
    return m.pad(body, sketch, height, name)


def frustum(a, b, h):
    """The volume of a square frustum, sides a and b, height h."""
    return h / 3 * (a * a + a * b + b * b)


def RevolutionGroove(make):
    """Revolution and Groove: whole, symmetric and two-sided.

    Body: a rectangle x 0..10, z 0..20 on the XZ plane revolved 360 degrees about its vertical
    axis (the Z axis): a cylinder, radius 10, height 20; a groove of x 6..10, z 8..12 about the
    same axis, symmetric, 90 degrees in all (a quarter of a ring, radii 6..10, 4 high).
    Body001: a rectangle x 5..10, z 0..4 revolved two-sided, 30 and 60 degrees (a quarter ring,
    radii 5..10); a groove of x 8..10, z 1..3, two-sided, 10 and 15 degrees (25 degrees of a
    ring, radii 8..10, 2 high), inside the revolution's span."""
    doc = make("RevolutionGroove")
    body = newBody(doc, "Body")
    profile = attachedSketch(body, "Sketch", plane(body, "XZ_Plane"), m.rectangle(0, 0, 10, 20))
    revolution = body.newObject("PartDesign::Revolution", "Revolution")
    revolution.Profile = profile
    revolution.ReferenceAxis = (profile, ["V_Axis"])
    revolution.Angle = 360
    grooveSketch = attachedSketch(
        body, "GrooveSketch", plane(body, "XZ_Plane"), m.rectangle(6, 8, 10, 12)
    )
    groove = body.newObject("PartDesign::Groove", "Groove")
    groove.Profile = grooveSketch
    groove.ReferenceAxis = (grooveSketch, ["V_Axis"])
    groove.SideType = "Symmetric"
    groove.Angle = 90
    body2 = newBody(doc, "Body001")
    profile2 = attachedSketch(
        body2, "Sketch001", plane(body2, "XZ_Plane"), m.rectangle(5, 0, 10, 4)
    )
    revolution2 = body2.newObject("PartDesign::Revolution", "Revolution001")
    revolution2.Profile = profile2
    revolution2.ReferenceAxis = (profile2, ["V_Axis"])
    revolution2.SideType = "Two sides"
    revolution2.Angle = 30
    revolution2.Angle2 = 60
    grooveSketch2 = attachedSketch(
        body2, "GrooveSketch001", plane(body2, "XZ_Plane"), m.rectangle(8, 1, 10, 3)
    )
    groove2 = body2.newObject("PartDesign::Groove", "Groove001")
    groove2.Profile = grooveSketch2
    groove2.ReferenceAxis = (grooveSketch2, ["V_Axis"])
    groove2.SideType = "Two sides"
    groove2.Angle = 10
    groove2.Angle2 = 15
    doc.recompute()
    return {
        "volumes": {
            "Revolution": math.pi * 100 * 20,
            "Groove": math.pi * 100 * 20 - math.pi * (100 - 36) * 4 / 4,
            "Groove001": math.pi * (100 - 25) * 4 / 4 - math.pi * (100 - 64) * 2 * 25 / 360,
        }
    }


def SidedVariants(make):
    """Pad symmetric to its plane and Pocket two-sided (B1's PadPocket has the other two).

    A rectangle 0..30 x 0..20 on the XY plane padded 10 symmetric (z -5..5); a circle, radius
    3, at (8, 10) on the XY plane pocketed two-sided, 2 one way and 4 the other (6 in all,
    inside the block)."""
    doc = make("SidedVariants")
    body = newBody(doc, "Body")
    sketch = attachedSketch(body, "Sketch", plane(body, "XY_Plane"), m.rectangle(0, 0, 30, 20))
    pad = m.pad(body, sketch, 10)
    pad.SideType = "Symmetric"
    holeSketch = attachedSketch(body, "HoleSketch", plane(body, "XY_Plane"), [m.circle(8, 10, 3)])
    pocket = m.pocket(body, holeSketch, 2)
    pocket.SideType = "Two sides"
    pocket.Length2 = 4
    doc.recompute()
    return {"volumes": {"Pad": 6000, "Pocket": 6000 - math.pi * 9 * 6}}


def DraftThickness(make):
    """Draft and Thickness.

    Body: a 20 x 20 x 10 block (0..20) with a 5 degree draft on its four sides, neutral plane
    its bottom face, leaning inward going up: a square frustum, sides 20 and 20 - 20 tan 5.
    Body001: a 20 x 20 x 10 block (x 30..50), its top face removed and the rest thickened 1
    towards the inside, joined by intersection: a box open at the top, walls and floor 1."""
    doc = make("DraftThickness")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 20, 20, 10)
    doc.recompute()
    sides = [
        faceWhere(pad.Shape, planeFacing(n, p))
        for n, p in (
            (V(1, 0, 0), V(20, 0, 0)),
            (V(-1, 0, 0), V(0, 0, 0)),
            (V(0, 1, 0), V(0, 20, 0)),
            (V(0, -1, 0), V(0, 0, 0)),
        )
    ]
    draft = body.newObject("PartDesign::Draft", "Draft")
    draft.Base = (pad, sides)
    draft.NeutralPlane = (pad, [faceWhere(pad.Shape, planeFacing(V(0, 0, -1), V(0, 0, 0)))])
    draft.Angle = 5
    body2 = newBody(doc, "Body001")
    pad2 = block(body2, 30, 0, 50, 20, 10, "Pad001")
    doc.recompute()
    thickness = body2.newObject("PartDesign::Thickness", "Thickness")
    thickness.Base = (pad2, [faceWhere(pad2.Shape, planeFacing(TOP, V(0, 0, 10)))])
    thickness.Value = 1
    thickness.Reversed = True
    thickness.Join = "Intersection"
    doc.recompute()
    return {
        "volumes": {
            "Draft": frustum(20, 20 - 20 * math.tan(math.radians(5)), 10),
            "Thickness": 4000 - 18 * 18 * 9,
        }
    }


def MirroredMultiTransform(make):
    """Mirrored and MultiTransform.

    A 40 x 20 x 10 block (x -20..20, y 0..20); a boss, radius 3, 5 high, at (-12, 10) on its
    top face, mirrored in the YZ plane (a second boss at (12, 10)); a hole, radius 2, 3 deep, at
    (-15, 4) on the top face, transformed by a MultiTransform: mirrored in the YZ plane, then a
    linear pattern along the Y axis, 12 long, 2 occurrences (holes at x +-15, y 4 and 16)."""
    doc = make("MirroredMultiTransform")
    body = newBody(doc, "Body")
    pad = block(body, -20, 0, 20, 20, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    boss = m.pad(
        body, attachedSketch(body, "BossSketch", (pad, top), [m.circle(-12, 10, 3)]), 5, "Boss"
    )
    mirrored = body.newObject("PartDesign::Mirrored", "Mirrored")
    mirrored.Originals = [boss]
    mirrored.MirrorPlane = (plane(body, "YZ_Plane"), [""])
    body.Tip = mirrored  # newObject leaves the Tip (the roll-back bar, ops#127) before a pattern
    doc.recompute()
    hole = m.pocket(
        body, attachedSketch(body, "HoleSketch", (pad, top), [m.circle(-15, 4, 2)]), 3, "Hole"
    )
    doc.recompute()
    multi = body.newObject("PartDesign::MultiTransform", "MultiTransform")
    multi.Originals = [hole]
    step1 = body.newObject("PartDesign::Mirrored", "MultiMirrored")
    step1.MirrorPlane = (plane(body, "YZ_Plane"), [""])
    step2 = body.newObject("PartDesign::LinearPattern", "MultiLinear")
    step2.Direction = (plane(body, "Y_Axis"), [""])
    step2.Length = 12
    step2.Occurrences = 2
    multi.Transformations = [step1, step2]
    body.Tip = multi
    doc.recompute()
    bosses = 2 * math.pi * 9 * 5
    return {
        "volumes": {
            "Mirrored": 8000 + bosses,
            "MultiTransform": 8000 + bosses - 4 * math.pi * 4 * 3,
        }
    }


def LoftPipe(make):
    """Loft and Pipe.

    Body: a ruled loft from a square, side 20, on the XY plane (centred) to a square, side 10,
    10 up (a frustum); an additive pipe of a circle, radius 2, on the loft's top face at its
    centre, along a quarter circle, radius 10, from (0, 0, 10) up and over to (10, 0, 20) in
    the XZ plane (a quarter torus: Pappus, area times path). Body001: a smooth (BSpline) loft
    through a circle, radius 5, a square, side 8, 10 up, and a circle, radius 3, 20 up; its
    volume is integrated numerically, so it isn't stated: the gate's records pin it, and its
    drift calibrates the BSpline tolerance (3.2). Body002 (ops#376 F2): a square, side 4, centred
    on (40, 0) on the XY plane, piped along an L, up from (40, 0, 0) to (40, 0, 10), then along
    +X to (50, 0, 10), Right corner; a fillet, radius 1, on a start edge (y = -2, z = 0), and a
    datum point at the centre of the first leg's side face x = 38, so the naming migration's
    rehearsal covers references to a Pipe's start and first-leg elements."""
    doc = make("LoftPipe")
    body = newBody(doc, "Body")
    xy = plane(body, "XY_Plane")
    bottom = attachedSketch(body, "Bottom", xy, m.rectangle(-10, -10, 10, 10))
    top = attachedSketch(body, "Top", xy, m.rectangle(-5, -5, 5, 5))
    top.AttachmentOffset = App.Placement(V(0, 0, 10), App.Rotation())
    loft = body.newObject("PartDesign::AdditiveLoft", "Loft")
    loft.Profile = bottom
    loft.Sections = [top]
    loft.Ruled = True
    doc.recompute()
    capFace = faceWhere(loft.Shape, planeFacing(TOP, V(0, 0, 10)))
    profile = attachedSketch(body, "PipeProfile", (loft, capFace), [m.circle(0, 0, 2)])
    spine = attachedSketch(body, "Spine", plane(body, "XZ_Plane"), [])
    spine.AttachmentOffset = App.Placement(V(0, 10, 0), App.Rotation())
    # in the XZ plane's sketch, x is X and y is Z: the arc centred on (10, 10) from 180 to 90
    # degrees runs from (0, 10) to (10, 20)
    spine.addGeometry(
        Part.ArcOfCircle(Part.Circle(V(10, 0, 0), V(0, 0, 1), 10), math.pi / 2, math.pi), False
    )
    pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
    pipe.Profile = profile
    pipe.Spine = spine
    pipe.Transition = "Transformed"  # the default before ops#370 (the spine is smooth)
    body2 = newBody(doc, "Body001")
    xy2 = plane(body2, "XY_Plane")
    sections = []
    for i, (geometry, z) in enumerate(
        ((m.circle(0, 0, 5), 0), (m.rectangle(-4, -4, 4, 4), 10), (m.circle(0, 0, 3), 20))
    ):
        section = attachedSketch(
            body2, f"Section{i}", xy2, geometry if isinstance(geometry, list) else [geometry]
        )
        section.AttachmentOffset = App.Placement(V(0, 0, z), App.Rotation())
        sections.append(section)
    smooth = body2.newObject("PartDesign::AdditiveLoft", "SmoothLoft")
    smooth.Profile = sections[0]
    smooth.Sections = sections[1:]
    body3 = newBody(doc, "Body002")
    square = attachedSketch(
        body3, "SquareProfile", plane(body3, "XY_Plane"), m.rectangle(38, -2, 42, 2)
    )
    # in the XZ plane's sketch, x is X and y is Z
    path = attachedSketch(
        body3, "LPath", plane(body3, "XZ_Plane"), m.polyline([(40, 0), (40, 10), (50, 10)])
    )
    lPipe = body3.newObject("PartDesign::AdditivePipe", "LPipe")
    lPipe.Profile = square
    lPipe.Spine = path
    lPipe.Transition = "Right corner"
    doc.recompute()
    fillet = body3.newObject("PartDesign::Fillet", "StartEdgeFillet")
    fillet.Base = (lPipe, [edgeWhere(lPipe.Shape, lineThrough((38, -2, 0), (42, -2, 0)))])
    fillet.Radius = 1
    point = body3.newObject("PartDesign::Point", "SidePoint")
    point.AttachmentSupport = [
        (lPipe, faceWhere(lPipe.Shape, planeFacing(V(-1, 0, 0), V(38, 0, 0))))
    ]
    point.MapMode = "CenterOfMass"
    body3.Tip = fillet
    doc.recompute()
    loftVolume = frustum(20, 10, 10)
    return {
        "volumes": {
            "Loft": loftVolume,
            "Pipe": loftVolume + math.pi * 4 * (math.pi * 10 / 2),
        }
    }


def PipeCorners(make):
    """A Pipe's spine corners (ops#370).

    Body: a square, side 4, centred on the XY plane, swept with "Transformed" along an L on the
    XZ plane: up 30, then 20 turned 120 degrees from +Z towards +X. "Transformed" doesn't turn
    the profile at the corner, so the second leg, past 90 degrees, runs back under the corner:
    the pipe is the union of the square's extrusions along the two legs, 4 * 4 * 30 and
    4 * 4 * 20 * |cos 120|, less their overlap below the corner, a wedge 4 deep with the
    triangle of legs 4 and 4 / tan 60 (32 / sqrt 3). Body001: the same square along an L with a
    right angle (up 30, then 20 along +X), its Transition as a new pipe has it ("Right corner"):
    4 * 4 * 50."""
    doc = make("PipeCorners")
    turned = math.radians(120)
    for name, end, transition in (
        ("Body", (20 * math.sin(turned), 30 + 20 * math.cos(turned)), "Transformed"),
        ("Body001", (20, 30), None),
    ):
        body = newBody(doc, name)
        profile = attachedSketch(
            body, "Profile" + name[4:], plane(body, "XY_Plane"), m.rectangle(-2, -2, 2, 2)
        )
        # in the XZ plane's sketch, x is X and y is Z
        spine = attachedSketch(
            body, "Spine" + name[4:], plane(body, "XZ_Plane"), m.polyline([(0, 0), (0, 30), end])
        )
        pipe = body.newObject("PartDesign::AdditivePipe", "Pipe" + name[4:])
        pipe.Profile = profile
        pipe.Spine = spine
        if transition:
            pipe.Transition = transition
    doc.recompute()
    return {"volumes": {"Pipe": 480 + 160 - 32 / math.sqrt(3), "Pipe001": 800}}


def HoleFeature(make):
    """A Hole: counterbored, with an angled drill point.

    A 20 x 20 x 10 block (0..20); a sketch on its top face with a circle at (10, 10); a Hole,
    diameter 6, depth 8 from the top face, counterbore diameter 10, 2 deep, drill point
    angled 118 degrees (a cone below the 8 mm, its height 3 / tan 59)."""
    doc = make("HoleFeature")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 20, 20, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    sketch = attachedSketch(body, "HoleSketch", (pad, top), [m.circle(10, 10, 1)])
    hole = body.newObject("PartDesign::Hole", "Hole")
    hole.Profile = sketch
    # Set as the Hole panel does: a Hole's thread fields take their ThreadType's values only when
    # ThreadType is set, and a restore sets it (CosmeticThread, ThreadFit), so a Hole left with
    # its constructor's values would reopen different.
    hole.ThreadType = "None"
    hole.Diameter = 6
    hole.DepthType = "Dimension"
    hole.Depth = 8
    hole.HoleCutType = "Counterbore"
    hole.HoleCutDiameter = 10
    hole.HoleCutDepth = 2
    hole.DrillPoint = "Angled"
    hole.DrillPointAngle = 118
    doc.recompute()
    cone = math.pi * 9 * (3 / math.tan(math.radians(59))) / 3
    return {"volumes": {"Hole": 4000 - math.pi * 25 * 2 - math.pi * 9 * 6 - cone}}


def UpToFace(make):
    """Pad, Pocket and Revolution up to a face, each in its plain case (one planar face, met
    directly; ops#296/#299/#304's edge cases are not modelled).

    Body: a 40 x 20 x 10 block (0..40) and a wall x 30..40 on its top, 15 more (to z 25); a
    square x 5..15, y 5..15 on the block's top face padded up to the wall's top face (to z 25);
    a circle, radius 2, at (35, 10) on the wall's top face pocketed up to the block's top face
    (15 deep). Body001: a datum plane on the YZ plane; a rectangle x 4..8, z 0..4 on the XZ
    plane revolved about the Z axis up to the datum plane (a quarter of a ring, radii 4..8).
    Body002 (ops#360): a SubShapeBinder of a Part feature's B-spline plate x -10..20, y 25..45 at
    z = 10 (not elementary, so the prism is built by the split); a block x -1..9, y 29..34, 2 high;
    two rectangles on its top, A x 0..2, y 30..32 and B x 5..8, y 30..33, padded up to the
    binder's face; a datum point at the centre of A's far cap. Each far cap is the projection of
    its own profile face."""
    doc = make("UpToFace")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 40, 20, 10)
    doc.recompute()
    top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
    wall = m.pad(
        body, attachedSketch(body, "WallSketch", (pad, top), m.rectangle(30, 0, 40, 20)), 15, "Wall"
    )
    doc.recompute()
    wallTop = faceWhere(wall.Shape, planeFacing(TOP, V(0, 0, 25)))
    blockTop = faceWhere(wall.Shape, planeFacing(TOP, V(0, 0, 10)))
    post = body.newObject("PartDesign::Pad", "Post")
    post.Profile = attachedSketch(body, "PostSketch", (wall, blockTop), m.rectangle(5, 5, 15, 15))
    post.Type = "UpToFace"
    post.UpToFace = (wall, [wallTop])
    doc.recompute()
    wallTop2 = faceWhere(
        post.Shape,
        lambda f: planeFacing(TOP, V(0, 0, 25))(f)
        and (f.CenterOfMass - V(35, 10, 25)).Length < 1e-6,
    )
    blockTop2 = faceWhere(post.Shape, planeFacing(TOP, V(0, 0, 10)))
    pocket = body.newObject("PartDesign::Pocket", "Pocket")
    pocket.Profile = attachedSketch(body, "PocketSketch", (post, wallTop2), [m.circle(35, 10, 2)])
    pocket.Type = "UpToFace"
    pocket.UpToFace = (post, [blockTop2])
    body2 = newBody(doc, "Body001")
    datum = body2.newObject("PartDesign::Plane", "DatumPlane")
    datum.AttachmentSupport = [(plane(body2, "YZ_Plane"), "")]
    datum.MapMode = "FlatFace"
    profile = attachedSketch(body2, "Sketch001", plane(body2, "XZ_Plane"), m.rectangle(4, 0, 8, 4))
    revolution = body2.newObject("PartDesign::Revolution", "Revolution")
    revolution.Profile = profile
    revolution.ReferenceAxis = (profile, ["V_Axis"])
    revolution.Type = "UpToFace"
    revolution.UpToFace = (datum, [""])
    corners = [V(-10, 25, 10), V(20, 25, 10), V(20, 45, 10), V(-10, 45, 10)]
    plate = doc.addObject("Part::Feature", "FreeformPlate")
    plate.Shape = Part.Face(Part.makePolygon(corners + corners[:1])).toNurbs().Faces[0]
    body3 = newBody(doc, "Body002")
    plateBinder = body3.newObject("PartDesign::SubShapeBinder", "PlateBinder")
    plateBinder.Support = [(plate, ("Face1",))]
    splitBase = block(body3, -1, 29, 9, 34, 2, "SplitBase")
    doc.recompute()
    baseTop = faceWhere(splitBase.Shape, planeFacing(TOP, V(0, 0, 2)))
    rectangles = m.rectangle(0, 30, 2, 32) + m.rectangle(5, 30, 8, 33)
    splitPad = body3.newObject("PartDesign::Pad", "SplitPad")
    splitPad.Profile = attachedSketch(body3, "SplitPadSketch", (splitBase, baseTop), rectangles)
    splitPad.Type = "UpToFace"
    splitPad.UpToFace = (plateBinder, ["Face1"])
    doc.recompute()
    capA = faceWhere(
        splitPad.Shape,
        lambda f: abs(f.BoundBox.ZMin - 10) < 1e-6
        and abs(f.BoundBox.ZMax - 10) < 1e-6
        and f.isInside(V(1, 31, 10), 1e-6, True),
    )
    point = body3.newObject("PartDesign::Point", "CapPoint")
    point.AttachmentSupport = [(splitPad, capA)]
    point.MapMode = "CenterOfMass"
    body3.Tip = splitPad
    doc.recompute()
    walls = 8000 + 10 * 20 * 15
    return {
        "volumes": {
            "Post": walls + 10 * 10 * 15,
            "Pocket": walls + 10 * 10 * 15 - math.pi * 4 * 15,
            "Revolution": math.pi * (64 - 16) * 4 / 4,
            "SplitPad": 10 * 5 * 2 + (4 + 9) * 8,
        }
    }


def lobedHoleShell(z, lobes):
    """A shell of two B-spline faces at height z: the rectangle x -10..20, y -10..10 with a hole
    of `lobes` lobes about (3, 3) (radius 2 + 0.8 cos(lobes t), one closed B-spline edge), and the
    hole's fill (as TestPad's lobedHoleShell)."""
    points = []
    for k in range(60):
        t = 2 * math.pi * k / 60
        r = 2 + 0.8 * math.cos(lobes * t)
        points.append(V(3 + r * math.cos(t), 3 + r * math.sin(t), z))
    curve = Part.BSplineCurve()
    curve.interpolate(points, PeriodicFlag=True)
    edge = curve.toShape()
    outer = [V(-10, -10, z), V(20, -10, z), V(20, 10, z), V(-10, 10, z)]
    plate = Part.Face(
        Part.Plane(V(0, 0, z), TOP), [Part.makePolygon(outer + outer[:1]), Part.Wire([edge])]
    )
    fill = Part.Face(Part.Wire([edge]))
    return Part.Shell([plate.toNurbs().Faces[0], fill.toNurbs().Faces[0]])


def UpToTwins(make):
    """A Pad up to a shell whose far cap is split into identical twins, with a datum on one twin
    (PLAN decision 121 (3), ops#422/ops#423: what a twin reference computes at the beta).

    A Part feature's shell at z = 10: a plate x -10..20, y -10..10 with a four-lobed hole about
    (3, 3) (radius 2 + 0.8 cos 4t: tips 2.8 on the axes, valleys 1.2 on the diagonals) and the
    hole's fill, both B-spline faces. Body: a SubShapeBinder of both faces; a disc, radius 2.3,
    at (3, 3) on the XY plane padded up to the binder's faces (UpToShape). The disc crosses the
    hole between the tips, so the far cap is five pieces: one on the fill and four twins on the
    plate, one in each valley. A datum point at the centre of the twin in the valley at 45
    degrees."""
    doc = make("UpToTwins")
    shell = doc.addObject("Part::Feature", "LobedShell")
    shell.Shape = lobedHoleShell(10, 4)
    body = newBody(doc, "Body")
    binder = body.newObject("PartDesign::SubShapeBinder", "ShellBinder")
    binder.Support = [(shell, ("Face1", "Face2"))]
    pad = body.newObject("PartDesign::Pad", "TwinPad")
    pad.Profile = attachedSketch(body, "DiscSketch", plane(body, "XY_Plane"), [m.circle(3, 3, 2.3)])
    pad.Type = "UpToShape"
    pad.UpToShape = (binder, ["Face1", "Face2"])
    pad.Refine = False
    doc.recompute()

    def farCap(f):
        return abs(f.BoundBox.ZMin - 10) < 1e-6 and abs(f.BoundBox.ZMax - 10) < 1e-6

    caps = [f for f in pad.Shape.Faces if farCap(f)]
    if len(caps) != 5:
        raise AssertionError(f"TwinPad has {len(caps)} far caps, expected five")
    valley = V(3 + 1.75 * math.cos(math.pi / 4), 3 + 1.75 * math.sin(math.pi / 4), 10)
    twin = faceWhere(pad.Shape, lambda f: farCap(f) and f.isInside(valley, 1e-6, True))
    point = body.newObject("PartDesign::Point", "TwinPoint")
    point.AttachmentSupport = [(pad, twin)]
    point.MapMode = "CenterOfMass"
    body.Tip = pad
    doc.recompute()
    # The volume is pi 2.3^2 10, but OCCT integrates the trimmed B-spline caps only to about
    # 1e-6 (166.19004 against 166.19025): checked here at 1e-5, not as an exact stated volume.
    volume = math.pi * 2.3 * 2.3 * 10
    if abs(pad.Shape.Volume - volume) > 1e-5 * volume:
        raise AssertionError(f"TwinPad volume {pad.Shape.Volume}, expected {volume}")
    return {"volumes": {}}


def BodyFromFeature(make):
    """A Body based on another Body's feature, and a Boolean of two Bodies.

    Body: a 30 x 20 x 10 block (0..30). Body001: its BaseFeature is Body's Pad; a circle,
    radius 3, at (10, 10) on its XY plane pocketed through all. Body002: a box 10 x 10 x 10 at
    (-5, 0, 0) (an additive primitive), cut by Body (a PartDesign Boolean of the whole Body):
    5 x 10 x 10 is left."""
    doc = make("BodyFromFeature")
    body = newBody(doc, "Body")
    pad = block(body, 0, 0, 30, 20, 10)
    doc.recompute()
    body2 = newBody(doc, "Body001")
    body2.BaseFeature = pad
    doc.recompute()
    hole = m.pocketThroughAll(
        body2,
        attachedSketch(body2, "HoleSketch", plane(body2, "XY_Plane"), [m.circle(10, 10, 3)]),
        "Hole",
    )
    hole.SideType = "Symmetric"
    body3 = newBody(doc, "Body002")
    box = body3.newObject("PartDesign::AdditiveBox", "Box")
    box.Length = box.Width = box.Height = 10
    box.Placement = App.Placement(V(-5, 0, 0), App.Rotation())
    doc.recompute()
    boolean = body3.newObject("PartDesign::Boolean", "Boolean")
    boolean.setObjects([body])
    boolean.Type = "Cut"
    doc.recompute()
    return {"volumes": {"Pad": 6000, "Hole": 6000 - math.pi * 9 * 10, "Boolean": 500}}


def Binders(make):
    """A ShapeBinder, a moved source Body (ops#308 T4), an expression across Bodies, and an
    ambiguous reference (two coincident faces) kept by its index.

    Source: a Body at (100, 50, 0), a 40 x 40 x 10 block on its XY plane (so x 100..140,
    y 50..90 in the document). Lid: a SubShapeBinder of the block's top face (it follows the
    moved Body), a rectangle x 105..135, y 55..85 on it, padded 5. Cap: a ShapeBinder of the
    same face, a circle, radius 4, at (120, 70) on it, padded by the expression
    `LidPad.Length * 2` (10). Twin and Twin001: two Bodies, each a 10 x 10 x 5 block (0..10),
    whose top faces coincide; Tag: a SubShapeBinder of both top faces (a compound of two equal
    faces), a sketch on its second face with a circle, radius 2, at (5, 5), padded 3."""
    doc = make("Binders")
    source = newBody(doc, "Source")
    source.Placement = App.Placement(V(100, 50, 0), App.Rotation())
    sourcePad = block(source, 0, 0, 40, 40, 10, "SourcePad")
    doc.recompute()
    top = faceWhere(sourcePad.Shape, planeFacing(TOP, V(0, 0, 10)))
    lid = newBody(doc, "Lid")
    binder = lid.newObject("PartDesign::SubShapeBinder", "SourceTop")
    binder.Support = [(sourcePad, (top,))]
    doc.recompute()
    lidPad = m.pad(
        lid,
        attachedSketch(lid, "LidSketch", (binder, "Face1"), m.rectangle(105, 55, 135, 85)),
        5,
        "LidPad",
    )
    cap = newBody(doc, "Cap")
    shapeBinder = cap.newObject("PartDesign::ShapeBinder", "ShapeBinder")
    shapeBinder.Support = [(sourcePad, top)]
    doc.recompute()
    capPad = m.pad(
        cap,
        attachedSketch(cap, "CapSketch", (shapeBinder, "Face1"), [m.circle(120, 70, 4)]),
        1,
        "CapPad",
    )
    capPad.setExpression("Length", "LidPad.Length * 2")
    twins = []
    for name in ("Twin", "Twin001"):
        twin = newBody(doc, name)
        twins.append(block(twin, 0, 0, 10, 10, 5, name + "Pad"))
    doc.recompute()
    tag = newBody(doc, "Tag")
    both = tag.newObject("PartDesign::SubShapeBinder", "TwinTops")
    both.Support = [
        (t, (faceWhere(t.Shape, planeFacing(TOP, V(0, 0, 5))),)) for t in twins
    ]
    doc.recompute()
    if len(both.Shape.Faces) != 2:
        raise AssertionError(f"TwinTops has {len(both.Shape.Faces)} faces, expected two")
    m.pad(tag, attachedSketch(tag, "TagSketch", (both, "Face2"), [m.circle(5, 5, 2)]), 3, "TagPad")
    doc.recompute()
    return {
        "volumes": {
            "SourcePad": 16000,
            "LidPad": 900 * 5,
            "CapPad": math.pi * 16 * 10,
            "TagPad": math.pi * 4 * 3,
        }
    }


def IndexToldGroups(make):
    """References to elements named alike and told apart only by an index (ops#378).

    Body: a 6 x 6 square with a round hole, radius 1, centred on the XY plane's origin, piped
    along an L in the XZ plane, up from (0, 0, 0) to (0, 0, 30), then along +X to (20, 0, 30),
    Right corner (TestNamingDump's PipeShell Pipe). At the bend the hole's two side faces meet in
    four quarter arcs, and the four vertexes between them, all named from the same two faces;
    OCCT stores the arcs in opposite orders on Windows and macOS, and the index follows their
    places since ops#378. A chamfer, size 0.2, on the arc centred at (-0.6009, -0.6729, 30.6009)
    (a fillet there fails in OCCT: "command not done"), and a datum point on the bend vertex
    (0, -1, 30). CornerCut: two overlapping boxes, 1 x 2 x 2 and 2 x 1 x 2, as a compound, cut
    by a cylinder, radius 0.5, 2 high, on their shared corner (TestNamingDump's CompoundCut); a
    sphere, radius 0.1, attached to the cut corner (0, 0.5, 2), the one of its two coincident
    vertexes named `UPP` (index 1, counted on from an edge named from the same faces)."""
    doc = make("IndexToldGroups")
    body = newBody(doc, "Body")
    profile = attachedSketch(
        body,
        "HoledSquare",
        plane(body, "XY_Plane"),
        m.rectangle(-3, -3, 3, 3) + [m.circle(0, 0, 1)],
    )
    # in the XZ plane's sketch, x is X and y is Z
    path = attachedSketch(
        body, "LPath", plane(body, "XZ_Plane"), m.polyline([(0, 0), (0, 30), (20, 30)])
    )
    pipe = body.newObject("PartDesign::AdditivePipe", "Pipe")
    pipe.Profile = profile
    pipe.Spine = path
    pipe.Transition = "Right corner"
    doc.recompute()
    arc = edgeWhere(
        pipe.Shape, lambda e: (e.CenterOfMass - V(-0.6009, -0.6729, 30.6009)).Length < 1e-3
    )
    chamfer = body.newObject("PartDesign::Chamfer", "ArcChamfer")
    chamfer.Base = (pipe, [arc])
    chamfer.Size = 0.2
    point = body.newObject("PartDesign::Point", "BendPoint")
    point.AttachmentSupport = [(pipe, vertexAt(pipe.Shape, V(0, -1, 30)))]
    point.MapMode = "Vertex"
    body.Tip = chamfer
    first = m.box(doc, "First", (1, 2, 2))
    second = m.box(doc, "Second", (2, 1, 2))
    cylinder = doc.addObject("Part::Cylinder", "Cylinder")
    cylinder.Radius = 0.5
    cylinder.Height = 2
    compound = doc.addObject("Part::Compound", "Compound")
    compound.Links = [first, second]
    cut = doc.addObject("Part::Cut", "CornerCut")
    cut.Base, cut.Tool, cut.Refine = compound, cylinder, False
    doc.recompute()
    corners = [
        f"Vertex{i + 1}"
        for i, v in enumerate(cut.Shape.Vertexes)
        if (v.Point - V(0, 0.5, 2)).Length < 1e-6
        and ";UPP;" in cut.Shape.getElementMappedName(f"Vertex{i + 1}")
    ]
    if len(corners) != 1:
        raise AssertionError(f"{len(corners)} UPP vertexes at the cut corner, expected one")
    ball = doc.addObject("Part::Sphere", "CornerBall")
    ball.Radius = 0.1
    ball.AttachmentSupport = [(cut, corners[0])]
    ball.MapMode = "Translate"
    doc.recompute()
    return {
        "volumes": {
            "Pipe": (36 - math.pi) * 50,
            "CornerCut": 8 - 2 * (math.pi * 0.25 * 2 / 4),
            "CornerBall": 4 / 3 * math.pi * 0.001,
        }
    }


ROUND_ON_SPLINE_TWIST = 0.02
ROUND_ON_SPLINE_RADIUS = 1.5


def twistedLid(twist):
    """The face z = 20 + twist x y over x -45..45, y -25..25, as a bicubic B-spline."""
    x, y = 45.0, 25.0
    surface = Part.BSplineSurface()
    poles = [
        [V(-x, -y, 20 + twist * x * y), V(-x, y, 20 - twist * x * y)],
        [V(x, -y, 20 - twist * x * y), V(x, y, 20 + twist * x * y)],
    ]
    surface.buildFromPolesMultsKnots(poles, [2, 2], [2, 2], [0, 1], [0, 1], False, False, 1, 1)
    surface.increaseDegree(3, 3)
    return surface.toShape()


def roundOnSplineContact(fillet, twist, radius, grid=17):
    """How far the rim round of `RoundOnSpline` is from the ball's contact, in closed form (no
    kernel distance): (blend faces, ball residual, seam residual, seams).

    A round of radius r is the surface a ball of radius r sweeps while it touches both walls.
    For a point p of a blend face with outward normal n the ball's centre is c = p - r n, and
    it must be at distance r from the lid z = 20 + twist x y and from the stadium's side wall
    (the planes y = -10 and y = 10 for |x| <= 20, else the cylinders of radius 10 about
    x = -20 and x = 20). The ball residual is the largest | distance - r | over a grid on
    every blend face. Two blend faces meet where the ball's contact crosses a tangent line
    x = +-20, y = +-10 of the wall: there the centre is at (+-20, +-(10 - r), z) with z at
    distance r below the lid, and the seam is that ball's circle. The seam residual is the
    largest | distance from that centre - r | along the four seams."""

    def lidDistance(a, b, h):
        x, y = a, b
        for _ in range(50):
            g = 20 + twist * x * y - h
            fx = (x - a) + g * twist * y
            fy = (y - b) + g * twist * x
            fxx = 1 + twist * twist * y * y
            fyy = 1 + twist * twist * x * x
            fxy = g * twist + twist * twist * x * y
            det = fxx * fyy - fxy * fxy
            dx = (fx * fyy - fy * fxy) / det
            dy = (fy * fxx - fx * fxy) / det
            x -= dx
            y -= dy
            if abs(dx) + abs(dy) < 1e-15:
                break
        return math.sqrt((x - a) ** 2 + (y - b) ** 2 + (20 + twist * x * y - h) ** 2)

    def wallDistance(a, b):
        return 10 - abs(b) if abs(a) <= 20 else 10 - math.hypot(abs(a) - 20, b)

    def isBlend(face):
        if isinstance(face.Surface, Part.Plane):
            return False
        if isinstance(face.Surface, Part.Cylinder) and abs(face.Surface.Radius - 10) < 1e-9:
            return False
        return face.Area < 500  # the lid is over 1000

    blends = [f for f in fillet.Shape.Faces if isBlend(f)]
    ball = 0.0
    for face in blends:
        u0, u1, v0, v1 = face.ParameterRange
        for i in range(grid):
            for j in range(grid):
                u = u0 + (u1 - u0) * (i + 0.5) / grid
                v = v0 + (v1 - v0) * (j + 0.5) / grid
                c = face.valueAt(u, v) - face.normalAt(u, v) * radius
                ball = max(
                    ball,
                    abs(lidDistance(c.x, c.y, c.z) - radius),
                    abs(wallDistance(c.x, c.y) - radius),
                )
    seamEdges = [
        e
        for e in fillet.Shape.Edges
        if sum(1 for f in blends if any(e.isSame(x) for x in f.Edges)) == 2
    ]
    seam = 0.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            a, b = 20.0 * sx, (10.0 - radius) * sy
            low, high = 0.0, 20 + twist * a * b
            for _ in range(200):
                middle = (low + high) / 2
                if lidDistance(a, b, middle) > radius:
                    low = middle
                else:
                    high = middle
            centre = V(a, b, (low + high) / 2)
            if not seamEdges:
                continue
            seam = max(
                seam,
                min(
                    max(abs((p - centre).Length - radius) for p in e.discretize(25))
                    for e in seamEdges
                ),
            )
    return len(blends), ball, seam, len(seamEdges)


def RoundOnSpline(make):
    """A round on a B-spline support (ops#640, decision 425: a round is the rolling ball's
    surface, also where the kernel's own fillet is not).

    A Part feature's face, the twisted lid z = 20 + 0.02 x y (a bicubic B-spline). Body: a
    SubShapeBinder of the lid; a stadium on the XY plane (the lines y = -10 and y = 10 for x
    -20..20, half circles of radius 10 about (-20, 0) and (20, 0)) padded up to the binder's
    face (UpToShape), so the Pad's top is the B-spline; a Fillet of radius 1.5 round the
    top's whole rim (five edges: the half cylinder about x = 20 is cut at its seam, so its
    rim is two edges): four blend faces in one closed chain, meeting on the wall's four
    tangent lines. The lid's normal turns about the rim, so a circle swept in the plane
    normal to the edge is off the ball by 3.6e-3 and its seams by 0.07.

    The expected result is the ball's contact, in closed form (`roundOnSplineContact`): every
    blend face within 1e-6 of it, and each seam the ball's circle where the contact crosses a
    tangent line of the wall."""
    twist, radius = ROUND_ON_SPLINE_TWIST, ROUND_ON_SPLINE_RADIUS
    doc = make("RoundOnSpline")
    lid = doc.addObject("Part::Feature", "TwistedLid")
    lid.Shape = twistedLid(twist)
    body = newBody(doc, "Body")
    binder = body.newObject("PartDesign::SubShapeBinder", "LidBinder")
    binder.Support = [(lid, ("Face1",))]
    stadium = [
        Part.LineSegment(V(-20, -10, 0), V(20, -10, 0)),
        Part.ArcOfCircle(Part.Circle(V(20, 0, 0), TOP, 10), -math.pi / 2, math.pi / 2),
        Part.LineSegment(V(20, 10, 0), V(-20, 10, 0)),
        Part.ArcOfCircle(Part.Circle(V(-20, 0, 0), TOP, 10), math.pi / 2, 3 * math.pi / 2),
    ]
    pad = body.newObject("PartDesign::Pad", "StadiumPad")
    pad.Profile = attachedSketch(body, "StadiumSketch", plane(body, "XY_Plane"), stadium)
    pad.Type = "UpToShape"
    pad.UpToShape = (binder, ["Face1"])
    pad.Refine = False
    doc.recompute()
    top = [f for f in pad.Shape.Faces if isinstance(f.Surface, Part.BSplineSurface)]
    if len(top) != 1:
        raise AssertionError(f"StadiumPad has {len(top)} B-spline faces, expected its top")
    rim = [
        f"Edge{i + 1}"
        for i, e in enumerate(pad.Shape.Edges)
        if any(e.isSame(x) for x in top[0].Edges)
    ]
    if len(rim) != 5:
        raise AssertionError(f"the top's rim has {len(rim)} edges, expected five")
    fillet = body.newObject("PartDesign::Fillet", "RimRound")
    fillet.Base = (pad, rim)
    fillet.Radius = radius
    body.Tip = fillet
    doc.recompute()
    faces, ball, seam, seams = roundOnSplineContact(fillet, twist, radius)
    if (faces, seams) != (4, 4):
        raise AssertionError(f"RimRound has {faces} blend faces and {seams} seams, expected 4 and 4")
    if ball > 1e-6 or seam > 1e-6:
        raise AssertionError(
            f"RimRound is off the ball's contact by {ball:.3g} (seams {seam:.3g}), allowed 1e-6"
        )
    return {"volumes": {}}


def bossTops(shape, z):
    """The (x, y) centres of the shape's 6 x 6 planar faces facing +z at height z, sorted."""
    return sorted(
        (round(f.CenterOfMass.x, 6), round(f.CenterOfMass.y, 6))
        for f in shape.Faces
        if isinstance(f.Surface, Part.Plane)
        and abs(f.CenterOfMass.z - z) < 1e-6
        and abs(f.Area - 36) < 1e-6
    )


def FacePatternCentered(make):
    """Face patterns with Centered and a second direction (ops#655, ops#640; Onshape's rule,
    notes/patterns-design.md section 10: Centered counts per side, the seed included, so count n
    makes 2n - 1 instances along that direction).

    Two Bodies, each a 60 x 30 x 10 plate (x -30..30, y 0..30) with a 6 x 6 boss, 5 high, at its
    centre (x -3..3, y 12..18), patterned by its faces (the boss's top and four sides):
    - `Row`: a face linear pattern along the X axis, spacing 15, count 2, Centered: three bosses,
      centres x -15, 0, 15 at y 15;
    - `Grid`: the same along X, and a second direction along the Y axis, spacing 10, count 2,
      Centered2: a 3 x 3 grid, centres x -15, 0, 15 by y 5, 15, 25 (the bosses 4 apart in y)."""
    doc = make("FacePatternCentered")
    plate = 60 * 30 * 10
    boss = 6 * 6 * 5
    expected = {
        "Row": [(x, 15) for x in (-15, 0, 15)],
        "Grid": sorted((x, y) for x in (-15, 0, 15) for y in (5, 15, 25)),
    }
    volumes = {}
    for name, centres in expected.items():
        body = newBody(doc, name + "Body")
        pad = block(body, -30, 0, 30, 30, 10, name + "Plate")
        doc.recompute()
        top = faceWhere(pad.Shape, planeFacing(TOP, V(0, 0, 10)))
        seed = m.pad(
            body,
            attachedSketch(body, name + "BossSketch", (pad, top), m.rectangle(-3, 12, 3, 18)),
            5,
            name + "Boss",
        )
        doc.recompute()
        picks = [
            f"Face{i + 1}"
            for i, f in enumerate(seed.Shape.Faces)
            if -3 - 1e-6 <= f.CenterOfMass.x <= 3 + 1e-6
            and 12 - 1e-6 <= f.CenterOfMass.y <= 18 + 1e-6
            and 10 + 1e-3 <= f.CenterOfMass.z <= 15 + 1e-6
        ]
        if len(picks) != 5:
            raise AssertionError(f"{name}: {len(picks)} boss faces, expected 5")
        pattern = body.newObject("PartDesign::FaceLinearPattern", name)
        pattern.Base = (seed, picks)
        pattern.Direction = (plane(body, "X_Axis"), [""])
        pattern.Mode = "Spacing"
        pattern.Offset = 15
        pattern.Occurrences = 2
        pattern.Centered = True
        if name == "Grid":
            pattern.Direction2 = (plane(body, "Y_Axis"), [""])
            pattern.Mode2 = "Spacing"
            pattern.Offset2 = 10
            pattern.Occurrences2 = 2
            pattern.Centered2 = True
        body.Tip = pattern
        doc.recompute()
        found = bossTops(pattern.Shape, 15)
        if found != sorted(centres):
            raise AssertionError(f"{name}: boss tops at {found}, expected {sorted(centres)}")
        volumes[name] = plate + len(centres) * boss
    return {"volumes": volumes}


MODELS = [
    RevolutionGroove,
    SidedVariants,
    DraftThickness,
    MirroredMultiTransform,
    LoftPipe,
    PipeCorners,
    HoleFeature,
    UpToFace,
    UpToTwins,
    BodyFromFeature,
    Binders,
    IndexToldGroups,
    RoundOnSpline,
    FacePatternCentered,
]
